"""扩展包候选的合成元数据参考检查；不解析ZIP、不导入文件、不启动扩展。"""
import argparse
import copy
import hashlib
import ipaddress
import json
import re
import subprocess
from importlib.metadata import version
import rfc8785
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from build_contracts import HERE, SID, IID, INSTALL, VERSION, IPC_VERSION, build, encoded

ROOT=HERE.parents[2]
REPORT=HERE/'reference-report.json'
INPUTS=[HERE/n for n in ('README.md','build_contracts.py','check_contracts.py','artifact.schema.json','ipc.schema.json')]
INPUTS += [HERE.parent/'c09-installation/installation.schema.json',ROOT/'docs/rebirth-c09-extension-design.md']


def digest(v): return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def raw_digest(v): return 'sha256:'+hashlib.sha256(v).hexdigest()
def reference(kind):
    return dict(kind=kind,authority_service_id='controller.test',database_instance_id='db.test',object_id=kind+'.test',revision='1',digest=digest(kind))
def ordered(values): return sorted(values,key=rfc8785.dumps)
def seal(v): v['resolution_digest']=digest({k:x for k,x in v.items() if k!='resolution_digest'})


def fixtures():
    roles={'device':'device','data':'data_object','endpoint':'endpoint','protocol':'protocol_profile',
           'secret':'secret_role','files':'filesystem_role','helper':'helper_artifact','policy':'validation_policy'}
    config=reference('configuration')
    bindings=[dict(role_id=n,kind=k,values=[dict(host='192.0.2.10',port=49280)] if k=='endpoint' else [reference(k)],configuration_ref=config) for n,k in sorted(roles.items())]
    scopes={
        'device_scope':dict(device_role='device',action_ids=['fader.set'],trigger_ids=['fader.changed']),
        'data_scope':dict(data_role='data',access='read'),
        'network_endpoint':dict(endpoint_role='endpoint',protocol_profile_role='protocol',transport='tcp',min_port=49280,max_port=49280),
        'secret_role':dict(secret_role='secret',device_role='device',source_role=None),
        'filesystem_root_role':dict(filesystem_role='files',access='cache_write',quota_bytes='1024'),
        'helper_artifact':dict(helper_role='helper',launch_policy_role='policy',helper_file_id='helper'),
        'panel_method':dict(authority='controller',method_ids=['controller.listDevices'],object_roles=['device']),
        'protocol_io':dict(protocol_profile_role='protocol',endpoint_request_id='network_endpoint',frame_classes=['query']),
    }
    payload={name:('synthetic '+name).encode() for name in ('worker','helper','panel','config','license','lock','policy')}
    file_roles=dict(worker='module',helper='native_helper',panel='panel',config='schema',license='license',lock='dependency_lock',policy='policy')
    inventory=dict(inventory_version='extension-files/1',files=[dict(file_id=n,path='payload/'+n+'.bin',size_bytes=str(len(v)),digest=raw_digest(v),role=file_roles[n],executable=n=='helper') for n,v in sorted(payload.items())])
    manifest=dict(manifest_version=VERSION,extension_id='synthetic.extension',extension_version='0.1.0',kind='device_module',publisher_id='publisher.test',source_revision='synthetic.rev',
        inventory_digest=digest(inventory),dependency_lock_file_id='lock',license_file_ids=['license'],capability_template_file_ids=[],configuration_schema_file_id='config',
        platforms=['windows-x64'],api_versions=['api.test'],ipc_versions=['ipc.test'],required_features=[],
        entrypoints=[dict(entry_id=k,kind=k,file_id=f,loader=l,io_policy_file_id=None if k=='panel' else 'policy') for k,f,l in [('worker','worker','node_module'),('helper','helper','native_binary'),('panel','panel','static_document')]],
        roles=[dict(role_id=n,kind=k,minimum=1,maximum=1,purpose='合成本地角色') for n,k in sorted(roles.items())],
        permission_templates=[dict(request_id=k,kind=k,purpose='合成用途',scope=v) for k,v in sorted(scopes.items())])
    # 独立手写投影预期，不调用解析器生成预期。
    permissions={
        'device_scope':dict(devices=[reference('device')],action_ids=['fader.set'],trigger_ids=['fader.changed']),
        'data_scope':dict(objects=[reference('data_object')],access='read'),
        'network_endpoint':dict(transport='tcp',host='192.0.2.10',port=49280,profile_ref=reference('protocol_profile')),
        'secret_role':dict(role_ref=reference('secret_role'),devices=[reference('device')],sources=[]),
        'filesystem_root_role':dict(role_ref=reference('filesystem_role'),access='cache_write',quota_bytes='1024'),
        'helper_artifact':dict(artifact_ref=reference('helper_artifact'),launch_profile_ref=reference('validation_policy')),
        'panel_method':dict(authority='controller',method_ids=['controller.listDevices'],object_refs=[reference('device')]),
        'protocol_io':dict(profile_ref=reference('protocol_profile'),endpoint_request_id='network_endpoint',frame_classes=['query']),
    }
    resolution=dict(resolution_id='resolution.test',authority_service_id='controller.test',database_instance_id='db.test',installation_id='installation.test',manifest_digest=digest(manifest),artifact_set_digest=digest(inventory),configuration_ref=config,
        bindings=bindings,permissions=[dict(request_id=k,kind=k,purpose='合成用途',scope=v) for k,v in sorted(permissions.items())],resolution_digest='')
    seal(resolution)
    begin=dict(identity=dict(host_installation_id='host.test',client_registration_id='client.test',import_request_id='request.test'),target_authority_service_id='controller.test',source_attachment_id='attachment.test',
        package_digest=digest('synthetic zip bytes'),package_bytes='1024',expected_manifest_digest=digest(manifest),host_trust_epoch='1',release_authorization_ref=reference('release_authorization'),validation_policy_ref=reference('validation_policy'))
    verify=dict(intake_id='intake.test',target_authority_service_id='controller.test',manifest_digest=digest(manifest),artifact_set_digest=digest(inventory),host_trust_epoch='1',challenge_id='challenge.test',launch_intent_digest=digest('launch'))
    receipt=dict(host_installation_id='host.test',host_trust_epoch='1',import_operation_id='operation.test',intake_id='intake.test',target_authority_service_id='controller.test',manifest_digest=digest(manifest),artifact_set_digest=digest(inventory),package_bytes='1024',file_inventory_digest=digest(inventory),dependency_lock_digest=raw_digest(payload['lock']),platform_profile_ref=reference('platform_profile'),validation_policy_ref=reference('validation_policy'),release_authorization_ref=reference('release_authorization'),verification_record_ref=reference('verification'))
    review=dict(review_ref=reference('review'),installation_ref=reference('installation'),manifest_digest=digest(manifest),artifact_set_digest=digest(inventory),configuration_ref=config,requested_permissions=resolution['permissions'],proposed_permissions=resolution['permissions'],policy_ref=reference('validation_policy'),content_digest='')
    review['content_digest']=digest({k:v for k,v in review.items() if k not in ('review_ref','content_digest')});review['review_ref']['digest']=review['content_digest']
    models=dict(Manifest=manifest,FileInventory=inventory,RoleResolution=resolution,ResolvedReview=dict(resolution_id=resolution['resolution_id'],resolution_digest=resolution['resolution_digest'],review=review),ImportBegin=begin,
        ImportIdentity=begin['identity'],ImportStatus=dict(identity=begin['identity'],intent_digest=intent(begin),operation_id='operation.test',state='sealed',target_authority_service_id='controller.test',package_digest=begin['package_digest'],receipt=receipt,reason_code=None),
        IntakeQuery=dict(intake_id='intake.test',target_authority_service_id='controller.test'),IntakeResult=dict(intake_id='intake.test',status='available',receipt=receipt),VerifyMaterialization=verify,
        MaterializationResult=dict(request=verify,result='verified',evidence_id='evidence.test',observer_domain=dict(clock_domain_id='clock.test',descriptor_digest=digest('clock')),observed_tick='10'),Error=dict(code='invalid_request',operation_id=None))
    return json.loads(json.dumps(models)),payload


def path_valid(path):
    parts=path.split('/')
    return bool(len(path)<=240 and all(re.fullmatch(r'[A-Za-z0-9_.-]+',p) and p not in ('.','..') and not p.endswith('.') and
        not re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])',p.split('.')[0]) for p in parts))


def artifact_error(m,i,observed):
    files=i['files'];ids=[f['file_id'] for f in files];paths=[f['path'].lower() for f in files]
    if ids!=sorted(set(ids)) or len(set(paths))!=len(paths): return 'identity'
    if any(not path_valid(f['path']) or f['path'].lower() in ('extension.json','files.json') for f in files): return 'path'
    if any(any('/'.join(p.split('/')[:n]) in paths for n in range(1,len(p.split('/')))) for p in paths): return 'path_prefix'
    if set(observed)!=set(ids): return 'closure'
    if any(str(len(observed[f['file_id']]))!=f['size_bytes'] or raw_digest(observed[f['file_id']])!=f['digest'] for f in files): return 'bytes'
    if m['inventory_digest']!=digest(i): return 'inventory_digest'
    by_id={f['file_id']:f for f in files}
    def has(k,role): return k in by_id and by_id[k]['role']==role
    if not has(m['dependency_lock_file_id'],'dependency_lock') or not has(m['configuration_schema_file_id'],'schema'): return 'file_role'
    if any(not has(k,'license') for k in m['license_file_ids']) or any(not has(k,'schema') for k in m['capability_template_file_ids']): return 'file_role'
    if len({e['entry_id'] for e in m['entrypoints']})!=len(m['entrypoints']): return 'entry_identity'
    for e in m['entrypoints']:
        role,loader={'worker':('module','node_module'),'panel':('panel','static_document'),'helper':('native_helper','native_binary')}[e['kind']]
        if not has(e['file_id'],role) or e['loader']!=loader: return 'entry_role'
        if (e['io_policy_file_id'] is not None) if e['kind']=='panel' else not has(e['io_policy_file_id'],'policy'): return 'io_policy'
    if any(f['executable']!=(f['role']=='native_helper') for f in files): return 'executable'
    if any(not has(t['scope']['helper_file_id'],'native_helper') for t in m['permission_templates'] if t['kind']=='helper_artifact'): return 'helper_file'
    return None


def resolve(m,r,helper_evidence):
    declarations={x['role_id']:x for x in m['roles']};bindings={x['role_id']:x for x in r['bindings']};used=set()
    if len(declarations)!=len(m['roles']) or len(bindings)!=len(r['bindings']) or declarations.keys()!=bindings.keys(): raise ValueError('role_set')
    for name,d in declarations.items():
        b=bindings[name]
        if d['kind']!=b['kind'] or not 1<=d['minimum']<=len(b['values'])<=d['maximum']<=64: raise ValueError('role_kind_count')
        if b['configuration_ref']!=r['configuration_ref']: raise ValueError('configuration')
        if b['values']!=ordered(b['values']) or len({rfc8785.dumps(v) for v in b['values']})!=len(b['values']): raise ValueError('role_order')
        if b['kind']!='endpoint' and any(v['authority_service_id']!=r['authority_service_id'] or v['database_instance_id']!=r['database_instance_id'] for v in b['values']): raise ValueError('role_authority')
        if b['kind']!='endpoint' and len({(v['kind'],v['authority_service_id'],v['database_instance_id'],v['object_id']) for v in b['values']})!=len(b['values']): raise ValueError('duplicate_object')
    def take(name,kind,single=False):
        if name not in bindings or bindings[name]['kind']!=kind: raise ValueError('role_reference')
        used.add(name);values=bindings[name]['values']
        if single and len(values)!=1: raise ValueError('single_role')
        return values[0] if single else values
    result=[];ids=[]
    for t in m['permission_templates']:
        s=t['scope'];k=t['kind'];ids.append(t['request_id'])
        for field in ('action_ids','trigger_ids','method_ids','object_roles','frame_classes'):
            if field in s and s[field]!=sorted(set(s[field])): raise ValueError('template_order')
        if k=='device_scope':
            if not s['action_ids'] and not s['trigger_ids']: raise ValueError('empty_device')
            out=dict(devices=take(s['device_role'],'device'),action_ids=s['action_ids'],trigger_ids=s['trigger_ids'])
        elif k=='data_scope': out=dict(objects=take(s['data_role'],'data_object'),access=s['access'])
        elif k=='network_endpoint':
            e=take(s['endpoint_role'],'endpoint',True);host=e['host']
            try: valid=str(ipaddress.ip_address(host))==host
            except ValueError: valid=bool(len(host)<=253 and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in host.split('.')))
            if not valid or not s['min_port']<=e['port']<=s['max_port']: raise ValueError('endpoint')
            out=dict(transport=s['transport'],**e,profile_ref=take(s['protocol_profile_role'],'protocol_profile',True))
        elif k=='secret_role':
            out=dict(role_ref=take(s['secret_role'],'secret_role',True),devices=[] if s['device_role'] is None else take(s['device_role'],'device'),sources=[] if s['source_role'] is None else take(s['source_role'],'source'))
            if not out['devices'] and not out['sources']: raise ValueError('secret_scope')
        elif k=='filesystem_root_role': out=dict(role_ref=take(s['filesystem_role'],'filesystem_role',True),access=s['access'],quota_bytes=s['quota_bytes'])
        elif k=='helper_artifact':
            artifact=take(s['helper_role'],'helper_artifact',True)
            if helper_evidence!=dict(artifact_ref=artifact,file_id=s['helper_file_id'],artifact_set_digest=r['artifact_set_digest']): raise ValueError('helper_binding')
            out=dict(artifact_ref=artifact,launch_profile_ref=take(s['launch_policy_role'],'validation_policy',True))
        elif k=='panel_method':
            values=[]
            for name in s['object_roles']:
                kind=bindings.get(name,{}).get('kind')
                if kind not in ('device','data_object','run'): raise ValueError('panel_role')
                values+=take(name,kind)
            values=list({rfc8785.dumps(v):v for v in values}.values())
            out=dict(authority=s['authority'],method_ids=s['method_ids'],object_refs=ordered(values))
        elif k=='protocol_io': out=dict(profile_ref=take(s['protocol_profile_role'],'protocol_profile',True),endpoint_request_id=s['endpoint_request_id'],frame_classes=s['frame_classes'])
        else: raise ValueError('kind')
        result.append(dict(request_id=t['request_id'],kind=k,purpose=t['purpose'],scope=out))
    if ids!=sorted(set(ids)): raise ValueError('template_identity')
    if used!=declarations.keys(): raise ValueError('unused_role')
    by_id={x['request_id']:x for x in result}
    for p in result:
        if p['kind']=='protocol_io':
            endpoint=by_id.get(p['scope']['endpoint_request_id'])
            if endpoint is None or endpoint['kind']!='network_endpoint' or endpoint['scope']['profile_ref']!=p['scope']['profile_ref']: raise ValueError('protocol_binding')
    return result


def resolution_error(m,r,trusted,helper):
    for key in ('authority_service_id','database_instance_id','installation_id','configuration_ref','artifact_set_digest'):
        if r[key]!=trusted[key]: return 'authority_binding'
    if r['manifest_digest']!=digest(m): return 'manifest_binding'
    if r['resolution_digest']!=digest({k:v for k,v in r.items() if k!='resolution_digest'}): return 'digest'
    try: expected=resolve(m,r,helper)
    except ValueError as e: return str(e)
    if r['permissions']!=expected: return 'projection'
    if any(p['kind']=='panel_method' and p['scope']['authority']!=trusted['service_kind'] for p in expected): return 'service_kind'
    return None


def review_error(wrapper,r):
    if wrapper['resolution_id']!=r['resolution_id'] or wrapper['resolution_digest']!=r['resolution_digest']: return 'resolution_binding'
    v=wrapper['review'];ir=v['installation_ref']
    if any(v[k]!=r[k] for k in ('manifest_digest','artifact_set_digest','configuration_ref')) or v['requested_permissions']!=r['permissions']: return 'review_projection'
    if (ir['authority_service_id'],ir['database_instance_id'],ir['object_id'])!=(r['authority_service_id'],r['database_instance_id'],r['installation_id']): return 'review_installation'
    return None  # 原review内容摘要和收窄规则由安装候选独立检查。


def intent(b): return digest({k:v for k,v in b.items() if k!='source_attachment_id'})
def status_error(v,b,operation_id):
    if v['identity']!=b['identity'] or v['intent_digest']!=intent(b) or v['operation_id']!=operation_id: return 'operation_binding'
    if v['target_authority_service_id']!=b['target_authority_service_id'] or v['package_digest']!=b['package_digest']: return 'package_binding'
    if v['state']=='sealed':
        r=v['receipt']
        if r['import_operation_id']!=operation_id or r['host_installation_id']!=b['identity']['host_installation_id']: return 'receipt_identity'
        if any(r[k]!=b[k] for k in ('host_trust_epoch','target_authority_service_id','package_bytes','release_authorization_ref','validation_policy_ref')) or r['manifest_digest']!=b['expected_manifest_digest']: return 'receipt_binding'
        if r['artifact_set_digest']!=r['file_inventory_digest']: return 'inventory_binding'
    return None


def intake_available(receipt,e):
    return e['materialized'] and e['current_trust'] and e['verified_receipt']==receipt


def admission(b,peer,stored=None):
    if not peer['authorized'] or b['identity']['client_registration_id']!=peer['client'] or b['identity']['host_installation_id']!=peer['host'] or b['target_authority_service_id']!=peer['target']: return 'unauthorized_peer'
    if stored is not None:
        if stored['identity']!=b['identity']: return 'record_binding'
        return 'existing' if stored['intent_digest']==intent(b) else 'identity_conflict'
    if b['host_trust_epoch']!=peer['epoch'] or not peer['release_valid']: return 'trust_denied'
    return 'accept' if peer['capacity'] else 'capacity'


def transition(state,event,e):
    if state in ('sealed','cancelled','rejected'): return state
    if event=='commit_unknown': return 'indeterminate'
    if event=='cancel': return 'indeterminate' if state=='indeterminate' else 'cancelled'
    if event=='recover':
        if not e['ledger_known']: return 'indeterminate'
        if e['sealed_record']: return 'sealed'  # 历史提交与当前实物可用性分别返回。
        return 'validating' if e['verified_spool'] else 'rejected'
    next_state={'accepted':'copying','copying':'validating','validating':'sealing','sealing':'sealed'}
    if event!='advance' or state not in next_state: return 'indeterminate'
    if state=='copying' and not e['package_matches']: return 'rejected'
    if state=='validating' and not (e['all_files_verified'] and e['current_trust']): return 'rejected'
    if state=='sealing' and not (e['materialized'] and e['durable'] and e['current_trust'] and e['ledger_known']): return 'indeterminate'
    return next_state[state]


def frame_error(f,c):
    if not c['authorized']: return 'peer'
    if f['channel_id']!=c['channel'] or f['sequence']!=c['next_sequence'] or f['message_id'] in c['seen']: return 'channel'
    if f['type'] not in c['allowed_types']: return 'direction'
    if f['reply_to'] is not None and (f['reply_to']!=c['pending_id'] or f['type'] not in c['response_types']): return 'reply'
    return None


def materialization_error(v,request,c):
    if v['request']!=request: return 'request_binding'
    if v['result']!='verified': return 'unavailable'
    if v['observer_domain']!=c['observer'] or c['local_clock']!=c['issued_clock'] or not 0<=int(c['now'])-int(c['issued'])<int(c['window']): return 'freshness'
    return None  # 远端tick真实性和启动器实物核验必须另取证。


def run():
    generated=build()
    for name,data in generated.items(): assert (HERE/name).read_bytes()==encoded(data),name
    resources=[json.loads((HERE/name).read_bytes()) for name in generated]+[json.loads((HERE.parent/'c09-installation/installation.schema.json').read_bytes())]
    for s in resources: Draft202012Validator.check_schema(s)
    registry=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in resources])
    def valid(model,value): return Draft202012Validator({'$ref':SID+'#/$defs/'+model},registry=registry).is_valid(value)
    ipc=Draft202012Validator(generated['ipc.schema.json'],registry=registry)
    models,payload=fixtures();checks=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    def change(v,f):
        v=copy.deepcopy(v);f(v);return v
    for model,v in models.items():
        check(model+'正常结构',valid(model,v),True)
        check(model+'拒绝额外字段',valid(model,dict(v,unexpected=True)),False)
    for value,expected in [('0',True),('99999999999999999999',True),('01',False),('1\n',False),(1,False),('100000000000000000000',False)]: check('U20:'+repr(value),valid('U20',value),expected)
    for p,expected in [('a/b.bin',True),('../x',False),('/x',False),('a//b',False),('a/CON.txt',False),('a/x.',False),('a:b',False),('a\\b',False),('a/设备',False),('a/.. /x',False)]: check('路径:'+p,path_valid(p),expected)
    m=models['Manifest'];i=models['FileInventory'];r=models['RoleResolution']
    check('完整清单与原字节',artifact_error(m,i,payload),None)
    for name,edit,expected in [
        ('未声明payload',lambda v:v.update(extra=b'x'),'closure'),('缺失payload',lambda v:v.pop('helper'),'closure'),('字节变化',lambda v:v.update(helper=b'changed'),'bytes')]: check(name,artifact_error(m,i,change(payload,edit)),expected)
    for name,edit,expected in [
        ('重复file_id',lambda v:v['files'].append(copy.deepcopy(v['files'][0])),'identity'),
        ('控制文件重占',lambda v:v['files'][0].update(path='extension.json'),'path'),
        ('文件目录冲突',lambda v:v['files'][0].update(path='payload'),'path_prefix'),
        ('清单hash失配',lambda v:v['files'][0].update(path='other/config'),'inventory_digest')]: check(name,artifact_error(m,change(i,edit),payload),expected)
    for name,edit,expected in [('入口loader错配',lambda v:v['entrypoints'][0].update(loader='native_binary'),'entry_role'),('policy缺失',lambda v:v['entrypoints'][0].update(io_policy_file_id=None),'io_policy'),('lock角色错配',lambda v:v.update(dependency_lock_file_id='license'),'file_role')]: check(name,artifact_error(change(m,edit),i,payload),expected)
    trusted={k:r[k] for k in ('authority_service_id','database_instance_id','installation_id','configuration_ref','artifact_set_digest')};trusted['service_kind']='controller'
    helper=dict(artifact_ref=reference('helper_artifact'),file_id='helper',artifact_set_digest=r['artifact_set_digest'])
    check('八类权限独立预期',resolve(m,r,helper),r['permissions'])
    check('解析记录完整绑定',resolution_error(m,r,trusted,helper),None)
    def bind(v,name): return next(x for x in v['bindings'] if x['role_id']==name)
    for name,edit,expected in [
        ('跨authority重新摘要',lambda v:bind(v,'device')['values'][0].update(authority_service_id='other'),'role_authority'),
        ('错配置重新摘要',lambda v:bind(v,'device').update(configuration_ref=reference('other')),'configuration'),
        ('端口越界',lambda v:bind(v,'endpoint')['values'][0].update(port=443),'endpoint'),
        ('URL不是host',lambda v:bind(v,'endpoint')['values'][0].update(host='https://example.test'),'endpoint'),
        ('缺角色',lambda v:v['bindings'].pop(),'role_set'),
        ('错kind',lambda v:bind(v,'device').update(kind='source'),'role_kind_count'),
        ('重复role',lambda v:v['bindings'].append(copy.deepcopy(v['bindings'][0])),'role_set'),
        ('空多值',lambda v:bind(v,'device').update(values=[]),'role_kind_count'),
        ('篡改权限后重算摘要',lambda v:v['permissions'][0]['scope'].update(access='propose'),'projection'),
        ('换installation后重算摘要',lambda v:v.update(installation_id='other'),'authority_binding'),
    ]:
        candidate=change(r,edit);seal(candidate);check(name,resolution_error(m,candidate,trusted,helper),expected)
    check('helper跨包错绑',resolution_error(m,r,trusted,dict(helper,artifact_set_digest=digest('other'))),'helper_binding')
    check('面板目标服务错配',resolution_error(m,r,dict(trusted,service_kind='seamer'),helper),'service_kind')
    def template(v,kind): return next(t['scope'] for t in v['permission_templates'] if t['kind']==kind)
    for name,edit,expected in [
        ('secret无精确目标',lambda v:template(v,'secret_role').update(device_role=None),'secret_scope'),
        ('protocol引用不存在端点',lambda v:template(v,'protocol_io').update(endpoint_request_id='missing'),'protocol_binding'),
        ('device模板错角色',lambda v:template(v,'device_scope').update(device_role='data'),'role_reference'),
        ('device空用途',lambda v:template(v,'device_scope').update(action_ids=[],trigger_ids=[]),'empty_device'),
        ('panel引用秘密',lambda v:template(v,'panel_method').update(object_roles=['secret']),'panel_role'),
        ('模板Id重复',lambda v:v['permission_templates'].append(copy.deepcopy(v['permission_templates'][-1])),'template_identity'),
        ('角色下界倒置',lambda v:v['roles'][0].update(minimum=2),'role_kind_count'),
    ]:
        candidate=change(m,edit);rr=copy.deepcopy(r);rr['manifest_digest']=digest(candidate);seal(rr)
        check(name,resolution_error(candidate,rr,trusted,helper),expected)
    multi=copy.deepcopy(r);bind(multi,'protocol')['values'].append(dict(reference('protocol_profile'),object_id='second'))
    bind(multi,'protocol')['values']=ordered(bind(multi,'protocol')['values']);mm=copy.deepcopy(m)
    next(x for x in mm['roles'] if x['role_id']=='protocol')['maximum']=2;multi['manifest_digest']=digest(mm);seal(multi)
    check('单值角色不可多值展开',resolution_error(mm,multi,trusted,helper),'single_role')
    duplicate=copy.deepcopy(multi);bind(duplicate,'protocol')['values'][1]=dict(bind(duplicate,'protocol')['values'][0],revision='2')
    bind(duplicate,'protocol')['values']=ordered(bind(duplicate,'protocol')['values']);seal(duplicate)
    check('同对象不同revision重复绑定',resolution_error(mm,duplicate,trusted,helper),'duplicate_object')
    check('resolution摘要失配',resolution_error(m,dict(r,resolution_digest=digest('other')),trusted,helper),'digest')
    check('review绑定解析',review_error(models['ResolvedReview'],r),None)
    check('review跨解析',review_error(dict(models['ResolvedReview'],resolution_id='other'),r),'resolution_binding')
    check('review回到宽权限',review_error(change(models['ResolvedReview'],lambda v:v['review']['requested_permissions'].pop()),r),'review_projection')
    b=models['ImportBegin'];stored=dict(identity=b['identity'],intent_digest=intent(b));peer=dict(authorized=True,client='client.test',host='host.test',target='controller.test',epoch='1',release_valid=True,capacity=True)
    check('sealed收据关联',status_error(models['ImportStatus'],b,'operation.test'),None)
    for name,edit,expected in [('操作身份错绑',lambda v:v.update(operation_id='other'),'operation_binding'),('包错绑',lambda v:v.update(package_digest=digest('other')),'package_binding'),
        ('收据导入身份错绑',lambda v:v['receipt'].update(import_operation_id='other'),'receipt_identity'),('收据目标错绑',lambda v:v['receipt'].update(target_authority_service_id='other'),'receipt_binding'),
        ('收据manifest错绑',lambda v:v['receipt'].update(manifest_digest=digest('other')),'receipt_binding'),('收据inventory错绑',lambda v:v['receipt'].update(file_inventory_digest=digest('other')),'inventory_binding')]:
        check(name,status_error(change(models['ImportStatus'],edit),b,'operation.test'),expected)
    for name,request,context,record,expected in [
        ('新导入',b,peer,None,'accept'),('重复请求',b,peer,stored,'existing'),('新attachment同内容',dict(b,source_attachment_id='new'),peer,stored,'existing'),
        ('同identity换包',dict(b,package_digest=digest('other')),peer,stored,'identity_conflict'),('同identity换trust',dict(b,host_trust_epoch='2'),dict(peer,epoch='2'),stored,'identity_conflict'),
        ('当前权限优先',b,dict(peer,authorized=False),stored,'unauthorized_peer'),('历史结果不新占容量',b,dict(peer,capacity=False),stored,'existing'),
        ('新导入容量拒绝',b,dict(peer,capacity=False),None,'capacity'),('新导入旧trust',b,dict(peer,epoch='2'),None,'trust_denied'),('跨目标',dict(b,target_authority_service_id='other'),peer,None,'unauthorized_peer')]: check(name,admission(request,context,record),expected)
    e=dict(ledger_known=True,sealed_record=False,materialized=True,verified_spool=True,package_matches=True,all_files_verified=True,current_trust=True,durable=True)
    for state,nxt in [('accepted','copying'),('copying','validating'),('validating','sealing'),('sealing','sealed')]: check(state+'正常推进',transition(state,'advance',e),nxt)
    for name,state,event,ctx,expected in [
        ('源变化','copying','advance',dict(e,package_matches=False),'rejected'),('未核全部文件','validating','advance',dict(e,all_files_verified=False),'rejected'),
        ('耐久未证','sealing','advance',dict(e,durable=False),'indeterminate'),('信任撤销','validating','advance',dict(e,current_trust=False),'rejected'),
        ('提交未知','sealing','commit_unknown',e,'indeterminate'),('取消先提交','sealing','cancel',e,'cancelled'),('sealed先提交','sealed','cancel',e,'sealed'),
        ('未知不能直接取消','indeterminate','cancel',e,'indeterminate'),('恢复spool','indeterminate','recover',e,'validating'),
        ('恢复未知账本','indeterminate','recover',dict(e,ledger_known=False),'indeterminate'),('恢复原sealed','indeterminate','recover',dict(e,sealed_record=True),'sealed'),
        ('sealed后丢实物保留历史','indeterminate','recover',dict(e,sealed_record=True,materialized=False),'sealed'),
        ('恢复无材料','indeterminate','recover',dict(e,verified_spool=False),'rejected')]: check(name,transition(state,event,ctx),expected)
    receipt=models['ImportStatus']['receipt'];available=dict(e,verified_receipt=receipt)
    check('当前实物可用',intake_available(receipt,available),True)
    check('历史sealed不掩盖文件丢失',intake_available(receipt,dict(available,materialized=False)),False)
    check('历史sealed不掩盖撤销',intake_available(receipt,dict(available,current_trust=False)),False)
    types={'IMPORT_BEGIN':'ImportBegin','IMPORT_QUERY':'ImportIdentity','IMPORT_CANCEL':'ImportIdentity','IMPORT_STATUS':'ImportStatus','INTAKE_QUERY':'IntakeQuery','INTAKE_RESULT':'IntakeResult','VERIFY_MATERIALIZATION':'VerifyMaterialization','MATERIALIZATION_RESULT':'MaterializationResult','ERROR':'Error'}
    responses={'IMPORT_STATUS','INTAKE_RESULT','MATERIALIZATION_RESULT','ERROR'}
    for t,model in types.items():
        frame=dict(ipc_version=IPC_VERSION,type=t,channel_id='channel.test',sequence='1',message_id='message.test',reply_to='request.test' if t in responses else None,payload=models[model])
        check(t+'结构',ipc.is_valid(frame),True)
        check(t+'拒绝错版本',ipc.is_valid(dict(frame,ipc_version='ipc/0.3.0')),False)
        check(t+'拒绝错reply形状',ipc.is_valid(dict(frame,reply_to=None if t in responses else 'request.test')),False)
        c=dict(authorized=True,channel='channel.test',next_sequence='1',seen=[],allowed_types=[t],pending_id='request.test',response_types=[t])
        check(t+'通道绑定',frame_error(frame,c),None)
        check(t+'拒绝旧channel',frame_error(frame,dict(c,channel='new')),'channel')
    for state,reason,has_receipt in [('accepted',None,False),('cancelled','operator_cancelled',False),('rejected','invalid_archive',False),('indeterminate','storage_unknown',False),('sealed',None,True)]:
        status=dict(models['ImportStatus'],state=state,reason_code=reason,receipt=models['ImportStatus']['receipt'] if has_receipt else None)
        check(state+'状态结构',valid('ImportStatus',status),True)
        check(state+'拒绝错误收据',valid('ImportStatus',dict(status,receipt=None if has_receipt else models['ImportStatus']['receipt'])),False)
    v=models['MaterializationResult'];req=models['VerifyMaterialization'];context=dict(observer=v['observer_domain'],local_clock='local',issued_clock='local',issued='10',now='14',window='5')
    check('物化核验关联',materialization_error(v,req,context),None)
    for key in req: check('物化错绑:'+key,materialization_error(change(v,lambda x:x['request'].update({key:digest('other') if key.endswith('digest') else 'other'})),req,context),'request_binding')
    check('物化截止等号',materialization_error(v,req,dict(context,now='15')),'freshness')
    check('物化本地域变化',materialization_error(v,req,dict(context,local_clock='other')),'freshness')
    check('物化远端域变化',materialization_error(v,req,dict(context,observer=dict(v['observer_domain'],clock_domain_id='other'))),'freshness')
    return dict(all_passed=True,approved=False,runtime_approved=False,checks=checks,versions=dict(jsonschema=version('jsonschema'),rfc8785=version('rfc8785')),
        limitations=['仅合成清单和有限状态快照，不执行ZIP/FD/IPC/进程或数据库','权威对象、helper与信任前提人工提供','不验证完整依赖锁、能力模板、实际路径和加载竞态','未并入SDK或安装HTTP；运行验收未执行'],runtime_validation=dict(zip=0,ipc=0,installer=0,database=0,device=0))


def hashes(staged=False):
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else p.read_bytes()).hexdigest() for p in INPUTS}


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group();g.add_argument('--report',action='store_true');g.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report: p.error('--staged仅配合--check-report')
    if a.check_report:
        raw=subprocess.check_output(['git','show',':'+REPORT.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else REPORT.read_bytes()
        result=json.loads(raw);assert result['all_passed'] and not result['approved'] and not result['runtime_approved'];assert result['input_sha256']==hashes(a.staged)
        print('7份输入绑定一致；未重跑用例')
    else:
        result=run();result['input_sha256']=hashes()
        if a.report: REPORT.write_bytes(encoded(result))
        print('扩展包与导入候选参考检查通过:',len(result['checks']))
