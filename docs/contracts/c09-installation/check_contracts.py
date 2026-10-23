"""安装候选的离线结构、投影及合成关联检查；不执行安装、数据库或设备操作。"""
import argparse
import copy
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from build_contracts import HERE, ROUTES, build, encoded, ref

ROOT=HERE.parents[2]
REPORT=HERE/'reference-report.json'
INPUTS=[HERE/n for n in ('README.md','build_contracts.py','check_contracts.py','installation.schema.json','installation.openapi.json')]
INPUTS += [ROOT/'docs/rebirth-c09-extension-design.md', ROOT/'docs/contracts/c09-panel-storage/README.md']


def digest(v): return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def reference(kind, name=None):
    return dict(kind=kind,authority_service_id='controller.test',database_instance_id='db.test',
                object_id=name or kind+'.test',revision='1',digest=digest(kind))
def identity():
    return dict(authority_service_id='controller.test',database_instance_id='db.test',identity_issuer_id='issuer.test',
                identity_epoch='1',auth_session_id='auth.test',gui_instance_id='gui.test',host_operation_id='request.test')
def permission(kind, scope): return dict(request_id=kind+'.test',kind=kind,purpose='合成权限审阅',scope=scope)
def fixtures():
    permissions=[
        permission('device_scope',dict(devices=[reference('device')],action_ids=['fader.set'],trigger_ids=['fader.changed'])),
        permission('data_scope',dict(objects=[reference('data_object')],access='read')),
        permission('network_endpoint',dict(transport='tcp',host='192.0.2.10',port=49280,profile_ref=reference('protocol_profile'))),
        permission('secret_role',dict(role_ref=reference('secret_role'),devices=[reference('device')],sources=[])),
        permission('filesystem_root_role',dict(role_ref=reference('filesystem_role'),access='cache_write',quota_bytes='1024')),
        permission('helper_artifact',dict(artifact_ref=reference('helper_artifact'),launch_profile_ref=reference('validation_policy'))),
        permission('panel_method',dict(authority='controller',method_ids=['controller.listDevices'],object_refs=[reference('device')])),
        permission('protocol_io',dict(profile_ref=reference('protocol_profile'),endpoint_request_id='network_endpoint.test',frame_classes=['query'])),
    ]
    context=identity(); slot_ref=reference('slot'); ins=reference('installation')
    review=dict(review_ref=reference('review'),installation_ref=ins,manifest_digest=digest('manifest'),artifact_set_digest=digest('artifacts'),
        configuration_ref=reference('configuration'),requested_permissions=permissions,proposed_permissions=copy.deepcopy(permissions),
        policy_ref=reference('validation_policy'),content_digest='')
    seal(review,'review_ref')
    selection=dict(kind='activate',source_installation_ref=None,target_installation_ref=ins,reuse_content_ref=None,configuration_ref=reference('configuration'))
    plan=dict(plan_ref=reference('dependency_plan'),slot_ref=slot_ref,dependency_revision='1',selection=selection,configuration_digest=digest('configuration'),
        impacts=[dict(object_ref=reference('device'),consequence='reconcile',reason_code='installation_dependency')],
        platform_profile_ref=reference('platform_profile'),policy_ref=reference('validation_policy'),
        lifetime=dict(clock=dict(clock_domain_id='clock.test',descriptor_digest=digest('clock')),issued_tick='1',deadline_tick='100'),content_digest='')
    seal(plan,'plan_ref')
    slot=dict(slot_ref=slot_ref,extension_id='synthetic.extension',kind='device_module',display_name='合成扩展',desired_state='disabled',
        current_installation_ref=None,pending_operation_ref=None,configuration_ref=reference('configuration'),dependency_revision='1')
    instance=dict(installation_ref=ins,slot_ref=slot_ref,state='installed_disabled',manifest_digest=digest('manifest'),artifact_set_digest=digest('artifacts'),
        intake_ref=reference('intake'),approval_ref=reference('approval'),review_ref=review['review_ref'],deny_record_ref=None,predecessor_ref=None,runtime_binding_refs=[])
    operation=dict(operation_ref=reference('installation_operation'),identity=context,intent_digest=digest('intent'),kind='activate',slot_ref=slot_ref,
        source_installation_ref=None,target_installation_ref=ins,phase='accepted',dependency_plan_ref=plan['plan_ref'],close_batch_refs=[],retirement_refs=[],
        reconciliation_refs=[],result=None,blockers=dict(snapshot_ref=reference('blocker_snapshot'),total='0',offset='0',items=[],has_more=False,next_cursor=None),
        runtime_readiness='closed')
    approval=dict(approval_ref=reference('approval'),installation_ref=ins,review_ref=review['review_ref'],approved_permission_ids=[p['request_id'] for p in permissions],
        configuration_ref=reference('configuration'),manifest_digest=digest('manifest'),artifact_set_digest=digest('artifacts'),platform_profile_ref=reference('platform_profile'),
        approval_operation_ref=reference('installation_operation'),revoked_by=None)
    intake=dict(host_installation_id='host.test',host_trust_epoch='1',import_operation_id='import.test',intake_id='intake.test',target_authority_service_id='controller.test',
        manifest_digest=digest('manifest'),artifact_set_digest=digest('artifacts'),package_bytes='1024',file_inventory_digest=digest('files'),dependency_lock_digest=digest('lock'),
        platform_profile_ref=reference('platform_profile'),validation_policy_ref=reference('validation_policy'),release_authorization_ref=reference('release_authorization'),verification_record_ref=reference('verification'))
    requests={
        'CreateSlot':dict(extension_id='synthetic.extension',kind='device_module',display_name='合成扩展'),
        'Stage':dict(slot_ref=slot_ref,intake_ref=reference('intake')),
        'Review':dict(expected_installation_revision='1',proposed_permissions=permissions,configuration_ref=reference('configuration')),
        'Approve':dict(expected_installation_revision='1',permission_review_ref=review['review_ref'],approved_permission_ids=approval['approved_permission_ids'],configuration_ref=reference('configuration')),
        'Activate':dict(expected_slot_revision='1',target_installation_ref=ins,approval_ref=reference('approval'),dependency_plan_ref=plan['plan_ref']),
        'Enable':dict(expected_slot_revision='1',reuse_content_ref=reference('content'),permission_review_ref=review['review_ref'],configuration_ref=reference('configuration'),dependency_plan_ref=plan['plan_ref']),
        'Disable':dict(expected_slot_revision='1',source_installation_ref=ins,reason='operator_request'),
        'Upgrade':dict(expected_slot_revision='1',source_installation_ref=ins,target_installation_ref=reference('installation','next.test'),approval_ref=reference('approval'),dependency_plan_ref=plan['plan_ref']),
        'Uninstall':dict(expected_slot_revision='1',source_installation_ref=None,dependency_plan_ref=plan['plan_ref'],reason='operator_request'),
        'PlanRequest':dict(expected_slot_revision='1',selection=selection),
    }
    requests={k:dict(context=context,**v) for k,v in requests.items()}
    requests['LookupRequest']=dict(identity=context)
    result=dict(SlotView=slot,InstanceView=instance,OperationView=operation,PermissionReview=review,Approval=approval,
        ArtifactIntakeReceipt=intake,DependencyPlan=plan,Permission=permissions,**requests)
    # 正例之间不共享可变对象；变异不能污染可信快照。
    return json.loads(json.dumps(result))


def seal(record, ref_key):
    record['content_digest']=digest({k:v for k,v in record.items() if k not in (ref_key,'content_digest')})
    record[ref_key]['digest']=record['content_digest']


def permissions_error(requested, proposed):
    src={p['request_id']:p for p in requested}
    if len(src)!=len(requested) or len({p['request_id'] for p in proposed})!=len(proposed): return 'duplicate_id'
    for p in proposed:
        old=src.get(p['request_id'])
        if old is None or any(p[k]!=old[k] for k in ('kind','purpose')): return 'request_binding'
        for k,value in p['scope'].items():
            original=old['scope'][k]
            if isinstance(value,list):
                if any(x not in original for x in value): return 'scope_expansion'
            elif k=='quota_bytes':
                if int(value)>int(original): return 'scope_expansion'
            elif value!=original: return 'scope_expansion'
        if p['kind']=='secret_role' and not (p['scope']['devices'] or p['scope']['sources']): return 'empty_secret_scope'
        if p['kind']=='network_endpoint':
            host=p['scope']['host']
            try: valid=str(ipaddress.ip_address(host))==host
            except ValueError: valid=bool(re.fullmatch(r'(?=.{1,253}\Z)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host)) and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',x) for x in host.split('.'))
            if not valid: return 'endpoint'
    ids={p['request_id']:p for p in proposed}
    for p in proposed:
        if p['kind']=='protocol_io':
            endpoint=ids.get(p['scope']['endpoint_request_id'])
            if endpoint is None or endpoint['kind']!='network_endpoint': return 'missing_endpoint'
            if endpoint['scope']['profile_ref']!=p['scope']['profile_ref']: return 'protocol_binding'
    return None


def review_error(review, trusted):
    if any(review[k]!=trusted[k] for k in ('installation_ref','manifest_digest','artifact_set_digest','configuration_ref','policy_ref','requested_permissions')): return 'authority_binding'
    clone=copy.deepcopy(review);seal(clone,'review_ref')
    if clone!=review: return 'digest'
    return permissions_error(review['requested_permissions'],review['proposed_permissions'])


def admission_decision(request, trusted, stored=None):
    # trusted只是一组人工权威前提；不是身份或数据库实现。
    ctx=request['context']
    if not trusted['authorized'] or {k:v for k,v in ctx.items() if k!='host_operation_id'}!=trusted['context']: return 'authority_denied'
    value=digest(dict(operation=trusted['operation'],path=trusted['path'],body={k:v for k,v in request.items() if k!='context'}))
    if stored is not None:
        if stored['identity']!=ctx: return 'identity_mismatch'
        return 'original' if stored['intent_digest']==value else 'conflict'
    if request['expected_slot_revision']!=trusted['slot_revision']: return 'stale'
    if trusted['slot_removed'] or trusted['operation_pending']: return 'conflict'
    return 'accept'


def approval_error(approval, review):
    for a,b in [('installation_ref','installation_ref'),('review_ref','review_ref'),('configuration_ref','configuration_ref'),
                ('manifest_digest','manifest_digest'),('artifact_set_digest','artifact_set_digest')]:
        if approval[a]!=review[b]: return 'binding'
    if approval['revoked_by'] is not None: return 'revoked'
    source={p['request_id']:p for p in review['proposed_permissions']}
    ids=approval['approved_permission_ids']
    if len(set(ids))!=len(ids) or not set(ids)<=source.keys(): return 'permission_ids'
    return permissions_error(review['requested_permissions'],[source[k] for k in ids])


def plan_error(plan,trusted):
    clone=copy.deepcopy(plan);seal(clone,'plan_ref')
    if clone!=plan: return 'digest'
    if any(plan[k]!=trusted[k] for k in ('slot_ref','dependency_revision','selection','impacts','platform_profile_ref','policy_ref')): return 'binding'
    if plan['configuration_digest']!=plan['selection']['configuration_ref']['digest']: return 'configuration'
    life=plan['lifetime']
    if life['clock']!=trusted['clock']: return 'clock'
    if not int(life['issued_tick'])<=trusted['now']<int(life['deadline_tick']): return 'expired'
    return None


def operation_error(operation):
    results={'stage':{'verified'},'approve':{'approved'},'activate':{'active_closed'},'enable':{'active_closed'},
        'upgrade':{'active_closed'},'disable':{'disabled','no_change'},'uninstall':{'removed','no_change'}}
    if operation['phase']=='completed' and operation['result'] not in results[operation['kind']]: return 'result_kind'
    if operation['phase']!='completed' and operation['result'] is not None: return 'premature_result'
    return None


def transition_decision(old,new,evidence):
    allowed={('staged','verified'),('staged','rejected'),('verified','rejected'),('verified','approved'),('approved','installed_disabled'),
        ('installed_disabled','activating'),('activating','active'),('activating','revoking'),('active','revoking'),('approved','revoking'),
        ('installed_disabled','revoking'),('revoking','disabled'),('disabled','removed'),('rejected','removed')}
    if (old,new) not in allowed: return 'transition'
    if new in ('activating','active') and (not evidence['currently_authorized'] or evidence['denied']): return 'denied'
    if new=='activating' and not all(evidence[k] for k in ('closure_complete','runtime_retired','resources_reconciled','owner_registered')): return 'not_ready'
    if new=='active' and not evidence['baseline_valid']: return 'baseline'
    if new=='disabled' and not evidence['closure_complete']: return 'closure'
    if new=='removed' and not (evidence['runtime_retired'] and evidence['closure_complete']): return 'retirement'
    return 'accept'


def page_error(page,snapshot):
    if page['snapshot_ref']!=snapshot['ref']: return 'snapshot'
    total=len(snapshot['items']); offset=int(page['offset']); count=len(page['items'])
    if int(page['total'])!=total or not 0<=offset<=total: return 'range'
    if page['items']!=snapshot['items'][offset:offset+count]: return 'content'
    if count==0 and offset<total: return 'empty_prefix'
    more=offset+count<total
    if page['has_more']!=more or (more and page['next_cursor']!=snapshot['next_cursor']) or (not more and page['next_cursor'] is not None): return 'cursor'
    return None


def run():
    outputs=build()
    for name,value in outputs.items(): assert (HERE/name).read_bytes()==encoded(value),name
    schema,api=outputs.values();Draft202012Validator.check_schema(schema);validate(api)
    results=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        results.append(dict(id=name,passed=True))
    def structure(name,model,value,expected=True):
        plain=Draft202012Validator(dict(ref(model),**{'$defs':schema['$defs']})).is_valid(value)
        projected=Draft202012Validator({'$ref':'#/components/schemas/'+model,'components':api['components']}).is_valid(value)
        check(name+'.schema',plain,expected);check(name+'.projection',projected,expected)
    f=fixtures()
    for model,value in f.items():
        for i,v in enumerate(value if model=='Permission' else [value]): structure(model+str(i),model,v)
    for kind in ('SlotView','OperationView','DependencyPlan','PermissionReview'):
        structure('lookup.'+kind,'LookupResult',dict(identity=identity(),intent_digest=digest('intent'),result_kind=kind,original_result=f[kind]))
    for key,value in [('leading_zero','01'),('newline','1\n'),('negative','-1'),('number',1),('overflow','1'*21),('max','9'*20),('over_uint64','18446744073709551616')]:
        structure('integer.'+key,'U20',value,key in ('max','over_uint64'))
    for model,key,value in [('Stage','path','C:/tmp/pkg'),('Stage','url','https://example.invalid/pkg'),('Approve','approved',True),
        ('CreateSlot','context',dict(identity(),role='admin')),('Activate','target_installation_ref',reference('approval')),
        ('OperationView','phase','unknown_outcome'),('InstanceView','state','failed'),('ArtifactIntakeReceipt','secret','synthetic-only')]:
        v=copy.deepcopy(f[model]);v[key]=value;structure('reject.'+model+'.'+key,model,v,False)
    for kind in ('activate','enable','upgrade','uninstall'):
        v=copy.deepcopy(f['PlanRequest']);sel=v['selection'];sel.update(kind=kind,source_installation_ref=reference('installation') if kind=='upgrade' else None,
            target_installation_ref=reference('installation','target') if kind in ('activate','upgrade') else None,
            reuse_content_ref=reference('content') if kind=='enable' else None)
        structure('plan.'+kind,'PlanRequest',v)
        sel['reuse_content_ref']=reference('content') if kind!='enable' else None
        structure('plan.bad.'+kind,'PlanRequest',v,False)
    check('review.exact',review_error(f['PermissionReview'],f['PermissionReview']),None)
    narrow=copy.deepcopy(f['PermissionReview']);narrow['proposed_permissions'][0]['scope']['trigger_ids']=[]
    narrow['proposed_permissions'][4]['scope']['quota_bytes']='1';seal(narrow,'review_ref')
    check('review.narrow',review_error(narrow,f['PermissionReview']),None)
    for name,mutate,expected in [
        ('expanded',lambda r:r['proposed_permissions'][0]['scope']['action_ids'].append('scene.recall'),'scope_expansion'),
        ('duplicate',lambda r:r['proposed_permissions'].append(copy.deepcopy(r['proposed_permissions'][0])),'duplicate_id'),
        ('missing_endpoint',lambda r:r['proposed_permissions'].pop(2),'missing_endpoint'),
        ('wrong_instance',lambda r:r['installation_ref'].update(object_id='other'),'authority_binding'),
        ('forged_original',lambda r:r['requested_permissions'][0]['scope']['action_ids'].append('scene.recall'),'authority_binding'),
        ('wrong_configuration',lambda r:r['configuration_ref'].update(revision='2'),'authority_binding'),
    ]:
        v=copy.deepcopy(f['PermissionReview']);mutate(v);seal(v,'review_ref');check('review.'+name,review_error(v,f['PermissionReview']),expected)
    v=copy.deepcopy(f['PermissionReview']);v['content_digest']=digest('wrong');check('review.hash',review_error(v,f['PermissionReview']),'digest')
    check('approval.exact',approval_error(f['Approval'],f['PermissionReview']),None)
    for name,changes,expected in [
        ('wrong_instance',dict(installation_ref=reference('installation','other')),'binding'),
        ('wrong_review',dict(review_ref=reference('review','other')),'binding'),
        ('wrong_config',dict(configuration_ref=reference('configuration','other')),'binding'),
        ('revoked',dict(revoked_by=reference('deny_record')),'revoked'),
        ('extra_id',dict(approved_permission_ids=['not_requested']),'permission_ids'),
        ('duplicate',dict(approved_permission_ids=['device_scope.test']*2),'permission_ids'),
        ('lost_endpoint',dict(approved_permission_ids=['protocol_io.test']),'missing_endpoint'),
    ]: check('approval.'+name,approval_error(dict(f['Approval'],**changes),f['PermissionReview']),expected)
    p=f['DependencyPlan']; pt={k:copy.deepcopy(p[k]) for k in ('slot_ref','dependency_revision','selection','impacts','platform_profile_ref','policy_ref')}
    pt.update(clock=copy.deepcopy(p['lifetime']['clock']),now=50)
    check('plan.current',plan_error(p,pt),None)
    for name,key,value,expected in [('revision','dependency_revision','2','binding'),('lost_impact','impacts',[],'binding'),
        ('wrong_authority','slot_ref',dict(p['slot_ref'],authority_service_id='other'),'binding'),
        ('configuration','configuration_digest',digest('other'),'configuration')]:
        v=copy.deepcopy(p);v[key]=value;seal(v,'plan_ref');check('plan.'+name,plan_error(v,pt),expected)
    check('plan.deadline_equal',plan_error(p,dict(pt,now=100)),'expired')
    check('plan.clock_changed',plan_error(p,dict(pt,clock=dict(pt['clock'],clock_domain_id='other'))),'clock')
    done=dict(f['OperationView'],phase='completed',result='active_closed')
    structure('operation.completed','OperationView',done);check('operation.completed',operation_error(done),None)
    check('operation.wrong_result',operation_error(dict(done,result='removed')),'result_kind')
    premature=dict(f['OperationView'],result='active_closed')
    structure('operation.premature','OperationView',premature,False)
    check('operation.premature',operation_error(premature),'premature_result')
    ev=dict(currently_authorized=True,denied=False,closure_complete=True,runtime_retired=True,resources_reconciled=True,owner_registered=True,baseline_valid=True)
    for name,old,new,changes,expected in [
        ('normal','installed_disabled','activating',{},'accept'),('revived','disabled','active',{},'transition'),
        ('revived_removed','removed','activating',{},'transition'),('missing_owner','installed_disabled','activating',{'owner_registered':False},'not_ready'),
        ('unknown_upgrade','installed_disabled','activating',{'resources_reconciled':False},'not_ready'),
        ('disabled_unknown','revoking','disabled',{'resources_reconciled':False},'accept'),
        ('remove_unknown','disabled','removed',{'resources_reconciled':False},'accept'),
        ('remove_live','disabled','removed',{'runtime_retired':False},'retirement'),
        ('missing_exit','revoking','disabled',{'closure_complete':False},'closure'),
        ('denied','installed_disabled','activating',{'denied':True},'denied'),
        ('no_baseline','activating','active',{'baseline_valid':False},'baseline'),
        ('direct_failure','active','failed',{},'transition'),
    ]: check('transition.'+name,transition_decision(old,new,dict(ev,**changes)),expected)
    req=f['Activate']; trusted=dict(authorized=True,context={k:v for k,v in req['context'].items() if k!='host_operation_id'},
        operation='activateExtension',path='/api/v1/extension-slots/slot.test/activate',slot_revision='1',slot_removed=False,operation_pending=False)
    stored=dict(identity=copy.deepcopy(req['context']),intent_digest=digest(dict(operation=trusted['operation'],path=trusted['path'],body={k:v for k,v in req.items() if k!='context'})))
    check('admission.normal',admission_decision(req,trusted),'accept')
    check('admission.duplicate_before_cas',admission_decision(req,dict(trusted,slot_revision='2'),stored),'original')
    check('admission.new_stale',admission_decision(req,dict(trusted,slot_revision='2')),'stale')
    check('admission.duplicate_current_auth',admission_decision(req,dict(trusted,authorized=False),stored),'authority_denied')
    changed=copy.deepcopy(req);changed['target_installation_ref']['object_id']='other'
    check('admission.same_id_other_body',admission_decision(changed,trusted,stored),'conflict')
    check('admission.pending',admission_decision(req,dict(trusted,operation_pending=True)),'conflict')
    check('admission.removed',admission_decision(req,dict(trusted,slot_removed=True)),'conflict')
    items=[dict(blocker_id='b'+str(i),code='unknown_effect',object_ref=reference('command',str(i))) for i in (1,2)]
    snapshot=dict(ref=reference('blocker_snapshot'),items=items,next_cursor='opaque.page.2')
    page=dict(snapshot_ref=snapshot['ref'],total='2',offset='0',items=items[:1],has_more=True,next_cursor='opaque.page.2')
    structure('page.normal','BlockerPage',page);check('page.normal',page_error(page,snapshot),None)
    for name,changes,expected in [('truncated',dict(has_more=False,next_cursor=None),'cursor'),('lost_total',dict(total='1'),'range'),
        ('gap',dict(items=items[1:]),'content'),('empty',dict(items=[]),'empty_prefix'),('wrong_snapshot',dict(snapshot_ref=reference('blocker_snapshot','other')),'snapshot')]:
        check('page.'+name,page_error(dict(page,**changes),snapshot),expected)
    last=dict(page,offset='1',items=items[1:],has_more=False,next_cursor=None)
    check('page.last',page_error(last,snapshot),None)
    operations=[op for methods in api['paths'].values() for op in methods.values()]
    check('metadata.operations',len(operations),14)
    for op in operations:
        check(op['operationId']+'.no_retry',op['x-automatic-write-retry'],False)
        check(op['operationId']+'.human','humanBearer' in op['security'][0],True)
        if 'requestBody' in op: check(op['operationId']+'.csrf','sessionCsrf' in op['security'][0],True)
        check(op['operationId']+'.no_store',all(r['headers']['Cache-Control']['schema']['const']=='no-store' for r in op['responses'].values()),True)
    return dict(approved=False,runtime_approved=False,all_passed=True,operations=14,checks=results,
        versions=dict(python=sys.version.split()[0],jsonschema=version('jsonschema'),rfc8785=version('rfc8785'),openapi_spec_validator=version('openapi-spec-validator')),
        limitations=['权威身份、实物及证据为合成前提','状态判断为局部快照，不是完整执行器','未执行导入协议、完整发布信任或真实权限',
                     '未执行HTTP、IPC、SQLite、监督器、磁盘及设备','未证明字段脱敏、动态网络目标授权或全部生命周期并发'],
        runtime_validation=dict(http=0,installer=0,database=0,supervisor=0,device=0))


def hashes(staged=False):
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)
        if staged else p.read_bytes()).hexdigest() for p in INPUTS}


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group();g.add_argument('--report',action='store_true');g.add_argument('--check-report',action='store_true')
    p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report: p.error('--staged仅配合--check-report')
    if a.check_report:
        raw=subprocess.check_output(['git','show',':'+REPORT.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else REPORT.read_bytes()
        r=json.loads(raw);assert r['all_passed'] and not r['approved'] and not r['runtime_approved'];assert r['input_sha256']==hashes(a.staged)
        print('7份输入字节绑定一致；未重跑检查')
    else:
        r=run();r['input_sha256']=hashes()
        if a.report: REPORT.write_bytes(encoded(r))
        print('安装管理候选参考检查通过:',len(r['checks']))
