"""安装0.2关联候选的离线参考；权威及运行证据为人工前提。"""
import argparse
import copy
import hashlib
import json
import subprocess
from importlib.metadata import version
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
import check_contracts as old
from build_v02 import HERE,VERSION,build,encoded,ref

ROOT=HERE.parents[2];REPORT=HERE/'reference-v02-report.json'
INPUTS=[HERE/n for n in ('LIFECYCLE_V02.md','build_v02.py','check_v02.py','installation-v02.schema.json','installation-v02.openapi.json','build_contracts.py','check_contracts.py')]
INPUTS += [HERE.parent/'c09-artifact-import/artifact.schema.json',ROOT/'docs/rebirth-c09-extension-design.md',ROOT/'docs/rebirth-df02-runtime-design.md']


def digest(v): return old.digest(v)
def permissions(review,ids):
    by_id={x['request_id']:x for x in review['proposed_permissions']}
    return [by_id[k] for k in sorted(ids)]
def seal_resolution(r): r['resolution_digest']=digest({k:v for k,v in r.items() if k!='resolution_digest'})


def fixtures():
    f=old.fixtures();review=f['PermissionReview'];approval=f['Approval'];ins=f['InstanceView']['installation_ref'];conf=review['configuration_ref']
    # 上游解析提供者为人工前提；本批检查解析后各权威对象的完整关联。
    r=dict(resolution_id='resolution.test',authority_service_id=ins['authority_service_id'],database_instance_id=ins['database_instance_id'],installation_id=ins['object_id'],
        manifest_digest=review['manifest_digest'],artifact_set_digest=review['artifact_set_digest'],configuration_ref=conf,bindings=[],permissions=review['requested_permissions'],resolution_digest='')
    seal_resolution(r);rr=old.reference('role_resolution');rr['object_id']=r['resolution_id'];rr['digest']=r['resolution_digest']
    review['role_resolution_ref']=rr;old.seal(review,'review_ref')
    approval['review_ref']=review['review_ref'];approval['role_resolution_ref']=rr
    approval['permissions_digest']=digest(permissions(review,approval['approved_permission_ids']))
    f['Review']['role_resolution_ref']=rr;f['Approve']['permission_review_ref']=review['review_ref'];f['InstanceView']['role_resolution_ref']=rr
    f['Stage']=dict(context=f['Stage']['context'],slot_ref=f['Stage']['slot_ref'],expected_slot_revision='1',source=dict(kind='retained',content_ref=old.reference('content')))
    f['Enable']=copy.deepcopy(f['Activate'])
    f['ResolutionView']=dict(resolution_ref=rr,record=r)
    f['ResolveRoles']=dict(context=old.identity(),expected_installation_revision='1',configuration_ref=conf,bindings=[])
    binding=dict(installation_ref=ins,approval_ref=approval['approval_ref'],review_ref=review['review_ref'],role_resolution_ref=rr,configuration_ref=conf,
        intake_ref=f['InstanceView']['intake_ref'],platform_profile_ref=approval['platform_profile_ref'],host_installation_id='host.test',host_trust_epoch='1',
        manifest_digest=review['manifest_digest'],artifact_set_digest=review['artifact_set_digest'],entry_id='worker.test',permissions_digest=approval['permissions_digest'])
    launch=dict(launch_id='launch.test',service_id='controller.test',supervisor_instance_id='supervisor.test',runtime_generation='generation.test',member_id='member.test',role='worker',
        artifact_manifest_ref=dict(manifest_id='runtime.test',revision='1',digest=digest('runtime')),
        containment_ref=dict(group_id='group.test',generation='group.generation',backend='windows_job'),device_ids=['device.test'],policy_revision='1',extension_binding=binding)
    grant=dict(authorization_ref=old.reference('launch_authorization'),launch_id=launch['launch_id'],launch_intent_digest=digest(launch),installation_ref=ins,approval_ref=approval['approval_ref'],
        role_resolution_ref=rr,permissions_digest=approval['permissions_digest'],supervisor_instance_id='supervisor.test',fence_revision='1',lifetime=dict(clock=old.reference('clock'),issued_tick='10',deadline_tick='20'))
    grant['lifetime']['clock']=dict(clock_domain_id='clock.test',descriptor_digest=digest('clock'))
    grant['authorization_ref']['digest']=digest({k:v for k,v in grant.items() if k!='authorization_ref'})
    record=dict(launch_id=launch['launch_id'],launch_intent_digest=digest(launch),supervisor_instance_id='supervisor.test',state='registered',creation_attempted=False,runtime_binding_ref=None,retirement_ref=None,gate_state='closed')
    f.update(ExtensionLaunchIntent=launch,LaunchAuthorization=grant,LaunchRecord=record)
    return json.loads(json.dumps(f))


def resolution_error(view,instance,configuration):
    r=view['record'];rr=view['resolution_ref'];ir=instance['installation_ref']
    if r['resolution_digest']!=digest({k:v for k,v in r.items() if k!='resolution_digest'}) or rr['digest']!=r['resolution_digest']: return 'resolution_digest'
    if rr['object_id']!=r['resolution_id'] or (rr['authority_service_id'],rr['database_instance_id'])!=(r['authority_service_id'],r['database_instance_id']): return 'resolution_ref'
    if (r['authority_service_id'],r['database_instance_id'],r['installation_id'])!=(ir['authority_service_id'],ir['database_instance_id'],ir['object_id']): return 'installation'
    if any(r[k]!=instance[k] for k in ('manifest_digest','artifact_set_digest')): return 'content'
    if r['configuration_ref']!=configuration: return 'configuration'
    return None


def chain_error(f):
    rv=f['ResolutionView'];r=rv['record'];review=f['PermissionReview'];approval=f['Approval'];instance=f['InstanceView']
    err=resolution_error(rv,instance,review['configuration_ref'])
    if err: return err
    if review['role_resolution_ref']!=rv['resolution_ref'] or approval['role_resolution_ref']!=rv['resolution_ref'] or instance['role_resolution_ref']!=rv['resolution_ref']: return 'resolution_link'
    expected=dict(installation_ref=instance['installation_ref'],manifest_digest=instance['manifest_digest'],artifact_set_digest=instance['artifact_set_digest'],configuration_ref=r['configuration_ref'],policy_ref=review['policy_ref'],requested_permissions=r['permissions'])
    err=old.review_error(review,expected)
    if err: return 'review:'+err
    err=old.approval_error(approval,review)
    if err: return 'approval:'+err
    if len(set(approval['approved_permission_ids']))!=len(approval['approved_permission_ids']): return 'permission_ids'
    if approval['permissions_digest']!=digest(permissions(review,approval['approved_permission_ids'])): return 'permissions_digest'
    return None


def launch_error(f,c,record=None):
    l=f['ExtensionLaunchIntent'];g=f['LaunchAuthorization'];b=l['extension_binding'];a=f['Approval'];r=f['PermissionReview'];i=f['InstanceView']
    if not c['peer_authenticated']: return 'peer'
    # 重投先核同id固定内容；既有进程的查询结果不意味着可新建或恢复许可。
    if record is not None:
        if (record['launch_id'],record['supervisor_instance_id'])!=(l['launch_id'],l['supervisor_instance_id']): return 'record_identity'
        return 'query_existing' if record['launch_intent_digest']==digest(l) else 'identity_conflict'
    if not c['resolution_provider_valid'] or not c['approval_current'] or c['installation_denied']: return 'revoked'
    if (i['installation_ref']['authority_service_id'],i['installation_ref']['database_instance_id'])!=(c['service_id'],c['database_instance_id']): return 'authority_binding'
    err=chain_error(f)
    if err: return err
    expected=dict(installation_ref=i['installation_ref'],approval_ref=a['approval_ref'],review_ref=r['review_ref'],role_resolution_ref=r['role_resolution_ref'],
        configuration_ref=r['configuration_ref'],intake_ref=i['intake_ref'],platform_profile_ref=a['platform_profile_ref'],host_installation_id=c['host'],host_trust_epoch=c['trust_epoch'],
        manifest_digest=r['manifest_digest'],artifact_set_digest=r['artifact_set_digest'],entry_id=c['entry_id'],permissions_digest=a['permissions_digest'])
    if b!=expected: return 'extension_binding'
    if any(l[k]!=c[k] for k in ('service_id','supervisor_instance_id','runtime_generation','artifact_manifest_ref','containment_ref','policy_revision','device_ids')): return 'runtime_binding'
    if l['device_ids']!=sorted(set(l['device_ids'])): return 'device_order'
    if i['state'] not in ('approved','installed_disabled','activating'): return 'instance_state'
    if not all(c[k] for k in ('closure_complete','runtime_retired','resources_reconciled','owner_registered','materialization_verified')): return 'prerequisite'
    verification=dict(intake_id=b['intake_ref']['object_id'],target_authority_service_id=l['service_id'],manifest_digest=b['manifest_digest'],artifact_set_digest=b['artifact_set_digest'],host_trust_epoch=b['host_trust_epoch'],challenge_id=c['materialization_challenge'],launch_intent_digest=digest(l))
    if c['materialization_request']!=verification: return 'materialization_binding'
    if g['launch_id']!=l['launch_id'] or g['launch_intent_digest']!=digest(l) or g['supervisor_instance_id']!=l['supervisor_instance_id']: return 'grant_binding'
    if any(g[k]!=b[k] for k in ('installation_ref','approval_ref','role_resolution_ref','permissions_digest')): return 'grant_scope'
    if g['fence_revision']!=c['fence_revision']: return 'fence'
    gr=g['authorization_ref'];ir=i['installation_ref']
    if (gr['authority_service_id'],gr['database_instance_id'])!=(ir['authority_service_id'],ir['database_instance_id']) or gr['digest']!=digest({k:v for k,v in g.items() if k!='authorization_ref'}): return 'grant_ref'
    life=g['lifetime']
    if life['clock']!=c['clock'] or not 0<int(life['deadline_tick'])-int(life['issued_tick'])<=c['max_grant_age'] or not int(life['issued_tick'])<=c['now']<int(life['deadline_tick']): return 'expired'
    return 'register_closed'


def record_error(v):
    state=v['state']
    if state=='registered' and v['creation_attempted']: return 'premature_attempt'
    if state in ('creating','awaiting_bootstrap','admitted_closed','retiring') and not v['creation_attempted']: return 'missing_attempt'
    if (state=='admitted_closed')!=(v['runtime_binding_ref'] is not None) and state not in ('retiring','retired','indeterminate'): return 'runtime_result'
    if state=='retired' and v['retirement_ref'] is None: return 'retirement'
    if state!='retired' and v['retirement_ref'] is not None: return 'retirement'
    if state=='rejected' and v['creation_attempted']: return 'rejection_after_create'
    return None


def create_step(record,event):
    # 串行原子步模型，不执行CreateProcess、clone3或数据库。
    if event=='retry': return 'query_existing' if record['creation_attempted'] or record['state']!='registered' else 'may_create_same_intent'
    if event=='lost_response': return 'query_existing'
    if event=='revoke': return 'retiring' if record['creation_attempted'] else 'rejected'
    if event=='recover_without_group_proof': return 'indeterminate'
    if event=='prove_empty': return 'retired' if record['creation_attempted'] else 'registered'
    raise ValueError(event)


def run():
    docs=build()
    for n,v in docs.items(): assert (HERE/n).read_bytes()==encoded(v),n
    schema,api=docs.values();Draft202012Validator.check_schema(schema);validate(api)
    checks=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    def shape(name,model,v,expected=True):
        check(name+'.schema',Draft202012Validator(dict(ref(model),**{'$defs':schema['$defs']})).is_valid(v),expected)
        if model in api['components']['schemas']: check(name+'.openapi',Draft202012Validator({'$ref':'#/components/schemas/'+model,'components':api['components']}).is_valid(v),expected)
    def change(v,edit): v=copy.deepcopy(v);edit(v);return v
    f=fixtures()
    for model,v in f.items():
        for index,x in enumerate(v if model=='Permission' else [v]): shape(model+str(index),model,x)
    for model in ('Stage','Enable','Review','Approval','ResolutionView','LaunchAuthorization','ExtensionLaunchIntent','LaunchRecord'): shape(model+'额外字段',model,dict(f[model],unexpected=True),False)
    for model in ('Stage','Enable','Review','Approval','PermissionReview'): shape(model+'旧版拒绝',model,old.fixtures()[model],False)
    shape('enable计划必须有新target','PlanSelection',dict(f['DependencyPlan']['selection'],kind='enable'))
    shape('旧enable计划拒绝','PlanSelection',dict(f['DependencyPlan']['selection'],kind='enable',target_installation_ref=None,reuse_content_ref=old.reference('content')),False)
    shape('解析幂等查询','LookupResult',dict(identity=old.identity(),intent_digest=digest('resolve'),result_kind='ResolutionView',original_result=f['ResolutionView']))
    check('十五接口',sum(len(v) for v in api['paths'].values()),15)
    for path,verbs in api['paths'].items():
        for verb,op in verbs.items():
            check(op['operationId']+'显式版本',next(p for p in op['parameters'] if p['name']=='X-LeafSeamer-Contract')['schema']['const'],VERSION)
            check(op['operationId']+'人员认证',op['security'],[{'humanBearer':[],'sessionCsrf':[]}] if verb=='post' else [{'humanBearer':[]}])
    check('内部启动对象不发布',set(('ExtensionLaunchIntent','LaunchRecord','LaunchAuthorization')) & api['components']['schemas'].keys(),set())
    check('完整解析审批链',chain_error(f),None)
    for name,edit,expected in [
        ('解析Ref错对象',lambda v:v['ResolutionView']['resolution_ref'].update(object_id='other'),'resolution_ref'),
        ('解析旧实例',lambda v:v['ResolutionView']['record'].update(installation_id='old'),'installation'),
        ('换配置',lambda v:v['PermissionReview'].update(configuration_ref=old.reference('other')),'configuration'),
        ('review未关联解析',lambda v:v['PermissionReview'].update(role_resolution_ref=old.reference('role_resolution')),'resolution_link'),
        ('审批未关联解析',lambda v:v['Approval'].update(role_resolution_ref=old.reference('role_resolution')),'resolution_link'),
        ('审批已撤销',lambda v:v['Approval'].update(revoked_by=old.reference('deny_record')),'approval:revoked'),
        ('审批范围摘要错误',lambda v:v['Approval'].update(permissions_digest=digest('other')),'permissions_digest'),
    ]:
        candidate=change(f,edit)
        if name=='解析旧实例':
            seal_resolution(candidate['ResolutionView']['record']);candidate['ResolutionView']['resolution_ref']['digest']=candidate['ResolutionView']['record']['resolution_digest']
        check(name,chain_error(candidate),expected)
    narrowed=copy.deepcopy(f);rr=narrowed['PermissionReview'];next(p for p in rr['proposed_permissions'] if p['kind']=='filesystem_root_role')['scope']['quota_bytes']='512';old.seal(rr,'review_ref')
    narrowed['Approval']['review_ref']=rr['review_ref'];narrowed['Approval']['permissions_digest']=digest(permissions(rr,narrowed['Approval']['approved_permission_ids']))
    check('审批精确保留收窄',chain_error(narrowed),None)
    check('审批摘要不能回查宽模板',chain_error(change(narrowed,lambda v:v['Approval'].update(permissions_digest=f['Approval']['permissions_digest']))),'permissions_digest')
    l=f['ExtensionLaunchIntent'];g=f['LaunchAuthorization'];c={k:l[k] for k in ('service_id','supervisor_instance_id','runtime_generation','artifact_manifest_ref','containment_ref','policy_revision','device_ids')}
    c.update(peer_authenticated=True,resolution_provider_valid=True,approval_current=True,installation_denied=False,host='host.test',trust_epoch='1',entry_id='worker.test',database_instance_id='db.test',
        closure_complete=True,runtime_retired=True,resources_reconciled=True,owner_registered=True,materialization_verified=True,fence_revision='1',clock=g['lifetime']['clock'],now=15,max_grant_age=20,
        materialization_challenge='challenge.test',materialization_request=dict(intake_id=l['extension_binding']['intake_ref']['object_id'],target_authority_service_id=l['service_id'],manifest_digest=l['extension_binding']['manifest_digest'],artifact_set_digest=l['extension_binding']['artifact_set_digest'],host_trust_epoch='1',challenge_id='challenge.test',launch_intent_digest=digest(l)))
    check('新启动仍closed',launch_error(f,c),'register_closed')
    for name,key,value,expected in [('当前peer失效','peer_authenticated',False,'peer'),('审批当前失效','approval_current',False,'revoked'),('拒绝墓碑','installation_denied',True,'revoked'),
        ('平台变更','trust_epoch','2','extension_binding'),('旧屏障','fence_revision','2','fence'),('截止等号','now',20,'expired'),('发起前时间','now',9,'expired'),
        ('设备未核清','resources_reconciled',False,'prerequisite'),('组未退役','runtime_retired',False,'prerequisite'),('出口未关闭','closure_complete',False,'prerequisite'),
        ('未登记owner','owner_registered',False,'prerequisite'),('实物不符','materialization_verified',False,'prerequisite'),('错运行域','runtime_generation','other','runtime_binding')]: check(name,launch_error(f,dict(c,**{key:value})),expected)
    for key in l['extension_binding']:
        candidate=copy.deepcopy(f);value=candidate['ExtensionLaunchIntent']['extension_binding'][key]
        candidate['ExtensionLaunchIntent']['extension_binding'][key]=dict(value,object_id='other') if isinstance(value,dict) else digest('other') if key.endswith('digest') else 'other'
        candidate['LaunchAuthorization']['launch_intent_digest']=digest(candidate['ExtensionLaunchIntent'])
        check('重算意图仍拒绝错绑:'+key,launch_error(candidate,c),'extension_binding')
    check('同launch重送只查询',launch_error(f,c,f['LaunchRecord']),'query_existing')
    check('撤销后可查原launch不启动',launch_error(f,dict(c,approval_current=False),f['LaunchRecord']),'query_existing')
    check('同launch更改intent',launch_error(change(f,lambda v:v['ExtensionLaunchIntent'].update(policy_revision='2')),c,f['LaunchRecord']),'identity_conflict')
    check('核验结果属于别的launch',launch_error(f,dict(c,materialization_request=dict(c['materialization_request'],launch_intent_digest=digest('other')))),'materialization_binding')
    check('启动授权寿命超profile',launch_error(f,dict(c,max_grant_age=9)),'expired')
    check('授权Ref跨authority',launch_error(change(f,lambda v:v['LaunchAuthorization']['authorization_ref'].update(authority_service_id='other')),c),'grant_ref')
    check('跨业务数据库借实例',launch_error(f,dict(c,database_instance_id='other')),'authority_binding')
    for state in ('disabled','removed','active'):
        check('禁止重启实例:'+state,launch_error(change(f,lambda v:v['InstanceView'].update(state=state)),c),'instance_state')
    shape('扩展不能冒充core','ExtensionLaunchIntent',dict(l,role='core'),False)
    check('启动账本正常',record_error(f['LaunchRecord']),None)
    for state,attempt,bind,retire,expected in [('registered',True,None,None,'premature_attempt'),('creating',False,None,None,'missing_attempt'),
        ('admitted_closed',True,old.reference('runtime_binding'),None,None),('admitted_closed',True,None,None,'runtime_result'),
        ('retired',True,old.reference('runtime_binding'),old.reference('retirement'),None),('retired',True,None,None,'retirement'),('rejected',True,None,None,'rejection_after_create')]:
        record=dict(f['LaunchRecord'],state=state,creation_attempted=attempt,runtime_binding_ref=bind,retirement_ref=retire)
        shape('账本'+state+str(attempt),'LaunchRecord',record);check('账本语义'+state+str(attempt)+str(bind),record_error(record),expected)
    for state,attempt,event,expected in [('registered',False,'retry','may_create_same_intent'),('creating',True,'retry','query_existing'),('admitted_closed',True,'lost_response','query_existing'),
        ('registered',False,'revoke','rejected'),('creating',True,'revoke','retiring'),('creating',True,'recover_without_group_proof','indeterminate'),('creating',True,'prove_empty','retired'),('retired',True,'retry','query_existing')]:
        check('轨迹'+state+event,create_step(dict(f['LaunchRecord'],state=state,creation_attempted=attempt),event),expected)
    # 报告结果只用JSON值，不保留集合等内部比较对象。
    for row in checks:
        for k in ('expected','observed'):
            if isinstance(row[k],set): row[k]=sorted(row[k])
    return dict(all_passed=True,approved=False,runtime_approved=False,checks=checks,versions=dict(jsonschema=version('jsonschema'),rfc8785=version('rfc8785'),openapi_spec_validator=version('openapi-spec-validator')),
        limitations=['上游解析与权威提供者为人工前提，未重新执行完整manifest解析','LaunchRecord是局部快照及串行步骤，不是实际监督器状态机','短期授权和fence不证明跨进程传播即时完成','未运行HTTP鉴权、SQLite、OS进程、文件加载或设备'],runtime_validation=dict(http=0,database=0,supervisor=0,device=0))


def hashes(staged=False):
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else p.read_bytes()).hexdigest() for p in INPUTS}


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group();g.add_argument('--report',action='store_true');g.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report: p.error('--staged仅配合--check-report')
    if a.check_report:
        r=json.loads(subprocess.check_output(['git','show',':'+REPORT.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else REPORT.read_bytes());assert r['all_passed'] and not r['approved'] and not r['runtime_approved'];assert r['input_sha256']==hashes(a.staged)
        print('10份输入字节绑定一致；未重跑检查')
    else:
        r=run();r['input_sha256']=hashes()
        if a.report: REPORT.write_bytes(encoded(r))
        print('安装0.2候选检查通过:',len(r['checks']))
