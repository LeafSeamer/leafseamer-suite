"""HTTP及21帧IPC候选的离线参考验证；权威快照为夹具，不连接服务或设备。"""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry,Resource
from openapi_spec_validator import validate as validate_openapi
from build_protocol import HERE,BASE,FILES,PID,IID,VERSION,IPC_VERSION,FEATURES,build,encoded

ROOT=HERE.parents[2]
REPORT=HERE/'protocol-report.json'
PANEL_CASES=BASE/'c09-panel-ipc/cases.json'
CHANNEL=BASE/'c09-panel/channel-v02.schema.json'
INPUTS=[HERE/n for n in ('PROTOCOL.md','build_protocol.py','check_protocol.py','protocol.schema.json',
    'ipc-v05.schema.json','protection.openapi.json')]+list(FILES.values())+[PANEL_CASES,CHANNEL]
KEYS=('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest')


def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def seal(v,k):v[k]=digest({a:b for a,b in v.items() if a!=k});return v
def identity(q):return digest({k:v for k,v in q.items() if k not in ('context_id','idempotency_key','correlation_id')})
def matches(s,o):
    return o is not None and s['origin_scope']==o['origin_scope'] and s['run_id']==o['run_id'] \
        and int(o['arm_generation'])<=int(s['deny_through_generation'])


def snapshot_key(e):
    s=e['selector'];return (s['origin_scope']['authority_service_id'],s['origin_scope']['database_instance_id'],s['run_id'])


def snapshot_error(s,c):
    if s['controller_scope']!=c['controller_scope']:return 'scope'
    if seal(copy.deepcopy(s),'snapshot_digest')!=s:return 'digest'
    if s!=c['authoritative_snapshot']:return 'current_complete_snapshot'
    keys=[snapshot_key(e) for e in s['entries']]
    if keys!=sorted(set(keys)):return 'canonical_set'
    now={snapshot_key(e):e for e in s['entries']}
    for old in c['installed_entries']:
        new=now.get(snapshot_key(old))
        if new is None:return 'lost_tombstone'
        if int(new['deny_revision'])<int(old['deny_revision']) or \
           int(new['selector']['deny_through_generation'])<int(old['selector']['deny_through_generation']):return 'rollback'
    if int(s['snapshot_revision'])<int(c['installed_snapshot_revision']):return 'snapshot_revision_rollback'
    if s['snapshot_revision']==c['installed_snapshot_revision'] and c['installed_snapshot_digest'] is not None \
        and s['snapshot_digest']!=c['installed_snapshot_digest']:return 'snapshot_revision_conflict'
    return None


def chain_error(q,g,p,i,c):
    if q!=c['accepted_request'] or g['automation_binding']!=c['accepted_binding']:return 'admission'
    origin=q['origin'];binding=g['automation_binding'];auth=g['binding']
    if any(x!=origin for x in (auth['origin'],p['origin'],i['origin'])):return 'origin'
    if any(x!=binding for x in (q['automation_binding'],p['automation_binding'],i['automation_binding'])):return 'binding'
    if i['automation_binding_digest']!=(digest(binding) if binding else None):return 'binding_digest'
    if seal(copy.deepcopy(g),'guard_digest')!=g:return 'guard_digest'
    if p['content_digest']!=identity(q):return 'content_digest'
    for k in ('guard_id','guard_digest','permit_id','command_id','controller_boot_id','worker_boot_id','clock_domain_id','descriptor_digest'):
        if g[k]!=p[k] or g[k]!=i[k]:return 'chain_identity'
    for k in ('attempt_id','dispatch_intent_id','device_session_id'):
        if p[k]!=i[k]:return 'dispatch_identity'
    for k in KEYS:
        if g[k]!=c['current'][k] or i[k]!=c['current'][k]:return 'generation'
    if p['device_session_id']!=c['current']['device_session_id']:return 'device_session'
    if q['device_id']!=g['device_id']:return 'device'
    if g['admission_origin']!=c['admission_origin'] or p['admission_origin']!=g['admission_origin'] or i['admission_origin']!=g['admission_origin']:return 'provenance'
    if g['panel_binding']!=c['panel_binding']:return 'panel_authority'
    panel_hash=digest(g['panel_binding']) if g['panel_binding'] else None
    if p['panel_binding_digest']!=panel_hash or i['panel_binding_digest']!=panel_hash:return 'panel_digest'
    if int(c['now'])>=int(g['authorization_deadline_tick_ns']):return 'deadline'
    if not c['other_current_gates']:return 'other_gate'
    if binding is None:return None
    if auth['principal_kind']!='service' or g['admission_origin']!='non_panel':return 'actor'
    grant=c['grant'];run=q['run_binding']
    if grant['state']!='active' or not c['grant_current']:return 'grant_state'
    if binding['origin_scope']!=c['paired_origin'] or grant['origin_scope']!=binding['origin_scope']:return 'origin_scope'
    if binding['execution_binding_ref']!=c['execution_ref'] or binding['execution_binding_ref']['scope']!=binding['origin_scope']:return 'execution_ref'
    for k in ('run_id','definition_version','arm_generation'):
        if binding[k]!=run[k] or binding[k]!=grant[k]:return 'run'
    for k in ('step_id','logical_action_id'):
        if binding[k]!=run[k]:return 'step'
    if grant['grant_id']!=run['grant_id'] or auth['grant_id']!=run['grant_id']:return 'grant_id'
    if grant['revision']!=run['grant_revision'] or auth['grant_revision']!=grant['revision'] or p['grant_revision']!=grant['revision']:return 'grant_revision'
    if auth['arm_generation']!=binding['arm_generation'] or p['arm_generation']!=binding['arm_generation']:return 'generation_binding'
    if any(matches(x['selector'],binding) for x in c['installed_entries']):return 'run_denied'
    return None


def envelope_error(request,ack,c):
    if request['reply_to'] is not None or ack['reply_to']!=request['message_id']:return 'reply'
    if not c['peer_authenticated'] or c['request_direction']!='controller_to_worker' or c['ack_direction']!='worker_to_controller':return 'peer_direction'
    for k in KEYS:
        if request[k]!=c['current'][k] or ack[k]!=request[k]:return 'envelope_generation'
    if int(request['seq'])<=int(c['last_request_seq']) or int(ack['seq'])<=int(c['last_ack_seq']):return 'sequence'
    return None


def guard_ack_error(request,ack,c):
    if envelope_error(request,ack,c):return 'envelope'
    g=request['body']['guard'];a=ack['body']
    for k in ('guard_id','guard_digest','permit_id','command_id'):
        if a[k]!=g[k]:return 'guard'
    if a['content_digest']!=request['body']['content_digest']:return 'content'
    if a['installed_authorization_revision']!=g['authorization_revision']:return 'revision'
    for field in ('panel_binding','automation_binding'):
        if a[field+'_digest']!=(digest(g[field]) if g[field] else None):return 'binding'
    return None


def gate_ack_error(request,ack,c):
    if envelope_error(request,ack,c):return 'envelope'
    r,a=request['body'],ack['body'];s=r['run_deny_snapshot']
    if snapshot_error(s,c['snapshot_context']):return 'snapshot'
    if r['gate_token']!=c['current_gate_token']:return 'gate_token'
    for k in ('gate_token','gate_revision'):
        if a[k]!=r[k]:return 'gate_echo'
    if a['run_deny_snapshot_revision']!=s['snapshot_revision'] or a['run_deny_snapshot_digest']!=s['snapshot_digest']:return 'snapshot_echo'
    return None


def handshake_error(hello,ack,c):
    # HELLO为无device的连接握手；两方向各自从初始序号开始。
    if not c['peer_authenticated'] or hello['seq']!='1' or ack['seq']!='1' or hello['reply_to'] is not None:return 'connection'
    for k in KEYS:
        if k=='device_id':
            if hello[k] is not None or ack[k] is not None:return 'handshake_scope'
            continue
        if hello[k]!=ack[k] or ack[k]!=c['current'][k]:return 'generation'
    if ack['reply_to']!=hello['message_id']:return 'reply'
    offered=hello['body']['supported_features'];selected=ack['body']['selected_features']
    if not set(selected)<=set(offered):return 'unoffered_feature'
    if ack['body']['selected_ipc_version'] not in hello['body']['supported_ipc_versions']:return 'version'
    return None


def query_barrier_error(query,ack,frozen,c):
    if envelope_error(query,ack,c):return 'envelope'
    if ack['type']!=frozen['type'] or ack['body']!=frozen['body']:return 'frozen_result'
    for k in ('operation_id','barrier_id'):
        if query['body'][k]!=frozen['body'][k]:return 'barrier_identity'
    return None


def fence_error(f,a,c):
    if envelope_error(f,a,c):return 'envelope'
    f,a=f['body'],a['body']
    if f['controller_scope']!=c['controller_scope'] or f['selector']!=c['selector']:return 'selector_authority'
    if f['selector_digest']!=digest(f['selector']) or f['ledger_digest']!=digest(f['open_intents']):return 'digest'
    if f['open_intents']!=c['ledger']:return 'complete_ledger'
    ids=[i['permit_id'] for i in f['open_intents']]
    if ids!=sorted(set(ids)):return 'canonical_ledger'
    for k in f:
        if k!='open_intents' and a[k]!=f[k]:return 'echo'
    if not c['all_exits_proven'] or not a['all_write_exits_fenced']:return 'exits'
    if [x['intent'] for x in a['coverage']]!=f['open_intents']:return 'coverage'
    for item in a['coverage']:
        i=item['intent']
        if i['origin']!='automation' or not matches(f['selector'],i['automation_binding']):return 'selector_match'
        if i['automation_binding_digest']!=digest(i['automation_binding']):return 'binding_digest'
        if item['proof'] not in {'not_sent':['never_received','discarded_unconsumed'],
            'in_flight':['transport_entered'],'unknown':['send_uncertain']}[item['disposition']]:return 'proof'
        if item['disposition']=='not_sent' and any(i[k]!=c['current'][k] for k in (*KEYS,'device_session_id')):return 'old_exit'
        if i['permit_id'] in c['known_entered'] and item['disposition']!='in_flight':return 'lost_send_fact'
    return None


def http_error(q,c):
    if not c['mtls'] or not c['paired']:return 'unauthenticated'
    if not c['permission'] or q['selector']['origin_scope']!=c['origin_scope']:return 'forbidden'
    if q['controller_scope']!=c['controller_scope']:return 'forbidden'
    if c['stored_request'] is not None:
        return None if c['stored_request']==q else 'conflict'
    if q['selector_digest']!=digest(q['selector']):return 'invalid'
    if q['target_set_digest']!=c['target_set_digest'] or q['detector_domain_ref']!=c['detector_domain_ref']:return 'invalid'
    if q['basis']=='durable_protection' and q['protection_ref']!=c['plan_ref']:return 'invalid'
    if not c['capacity']:return 'capacity'
    return None


def fixture():
    old=json.loads(PANEL_CASES.read_bytes());b=old['base']
    g=copy.deepcopy(b['guard']);p=copy.deepcopy(b['permit']);q=copy.deepcopy(old['frames']['DISPATCH']['body']['request'])
    scope=dict(authority_service_id='seamer-a',database_instance_id='seamer-db-a')
    controller=dict(authority_service_id='controller-a',database_instance_id='controller-db-a')
    er=dict(kind='execution_binding',scope=scope,object_id='execution-binding',revision='1',digest=digest('execution'))
    origin=dict(origin_scope=scope,run_id='run-a',definition_version='1',arm_generation='6',
        execution_id='execution-a',execution_binding_ref=er,step_id='step-a',logical_action_id='action-a')
    q.update(origin='automation',automation_binding=copy.deepcopy(origin),run_binding=dict(run_id='run-a',definition_version='1',
        grant_id='grant-a',grant_revision='3',arm_generation='6',step_id='step-a',logical_action_id='action-a'))
    g.update(admission_origin='non_panel',panel_binding=None,automation_binding=copy.deepcopy(origin))
    g['binding'].update(origin='automation',principal_kind='service',principal_id='seamer-service',session_id=None,session_revision=None,
        grant_id='grant-a',grant_revision='3',arm_generation='6')
    seal(g,'guard_digest')
    p.update(origin='automation',admission_origin='non_panel',panel_binding_digest=None,automation_binding=copy.deepcopy(origin),
        grant_revision='3',arm_generation='6',guard_digest=g['guard_digest'],content_digest=identity(q))
    i={k:copy.deepcopy(g[k]) for k in KEYS}
    i.update({k:copy.deepcopy(p[k]) for k in ('permit_id','command_id','attempt_id','dispatch_intent_id','device_session_id',
        'guard_id','guard_digest','origin','admission_origin','panel_binding_digest','automation_binding')})
    i['automation_binding_digest']=digest(origin)
    grant=dict(origin_scope=scope,run_id='run-a',definition_version='1',arm_generation='6',grant_id='grant-a',revision='3',state='active')
    selector=dict(kind='run_generation',origin_scope=scope,run_id='run-a',deny_through_generation='5')
    entry=dict(selector=selector,deny_revision='2')
    c=dict(accepted_request=copy.deepcopy(q),accepted_binding=copy.deepcopy(origin),grant=grant,grant_current=True,paired_origin=scope,
        execution_ref=er,current=copy.deepcopy(b['authority']['current']),now='100',other_current_gates=True,
        admission_origin='non_panel',panel_binding=None,installed_entries=[entry])
    snapshot=seal(dict(controller_scope=controller,snapshot_revision='9',entries=[entry]),'snapshot_digest')
    snapctx=dict(controller_scope=controller,authoritative_snapshot=copy.deepcopy(snapshot),installed_entries=copy.deepcopy(snapshot['entries']),
        installed_snapshot_revision=snapshot['snapshot_revision'],installed_snapshot_digest=snapshot['snapshot_digest'])
    f=copy.deepcopy(old['frames']['AUTH_FENCE']);f.update(ipc_version=IPC_VERSION,type='RUN_FENCE',message_id='run-fence',seq='10')
    sel=copy.deepcopy(selector);sel['deny_through_generation']='6'
    f['body']=dict(operation_id='protect-a',barrier_id='barrier-a',controller_scope=controller,selector=sel,selector_digest=digest(sel),
        issued_cut_revision='10',target_deny_revision='3',ledger_digest=digest([i]),open_intents=[copy.deepcopy(i)])
    a=copy.deepcopy(old['frames']['AUTH_FENCE_ACK']);a.update(ipc_version=IPC_VERSION,type='RUN_FENCE_ACK',reply_to=f['message_id'],seq='11')
    a['body']={k:copy.deepcopy(v) for k,v in f['body'].items() if k!='open_intents'}
    a['body'].update(coverage=[dict(intent=copy.deepcopy(i),disposition='in_flight',proof='transport_entered')],all_write_exits_fenced=True)
    fc=dict(current=copy.deepcopy(c['current']),controller_scope=controller,selector=sel,ledger=[copy.deepcopy(i)],known_entered=[i['permit_id']],
        all_exits_proven=True,peer_authenticated=True,request_direction='controller_to_worker',ack_direction='worker_to_controller',
        last_request_seq='9',last_ack_seq='10')
    domain=dict(kind='runtime_domain',scope=scope,object_id='domain',revision='1',digest=digest('domain'))
    plan=dict(kind='source_protection_plan',scope=scope,object_id='plan',revision='1',digest=digest('plan'))
    h=dict(contract_version=VERSION,operation_id='protect-a',controller_scope=controller,selector=sel,selector_digest=digest(sel),
        target_set_digest=digest('targets'),basis='durable_protection',protection_ref=plan,detector_domain_ref=domain)
    hc=dict(mtls=True,paired=True,permission=True,origin_scope=scope,controller_scope=controller,plan_ref=plan,
        target_set_digest=h['target_set_digest'],detector_domain_ref=domain,stored_request=None,capacity=True,original_grant_active=False)
    # 往返序列化避免夹具共享对象让变异污染“可信”前提。
    return json.loads(json.dumps([old,q,g,p,i,c,snapshot,snapctx,f,a,fc,h,hc]))


def run():
    generated=build()
    resources={json.loads(p.read_bytes())['$id']:json.loads(p.read_bytes()) for p in [*FILES.values(),CHANNEL]}
    for n,s in generated.items():
        assert (HERE/n).read_bytes()==encoded(s),n
        if '$id' in s:Draft202012Validator.check_schema(s);resources[s['$id']]=s
    validate_openapi(generated['protection.openapi.json'])
    registry=Registry().with_resources((u,Resource.from_contents(s)) for u,s in resources.items())
    def valid(uri,v):
        return Draft202012Validator({'$ref':uri},registry=registry,format_checker=FormatChecker()).is_valid(v)
    results=[]
    def expect(n,condition):
        assert condition,n
        results.append(dict(id=n,passed=True))
    old,q,g,p,i,c,s,sc,f,a,fc,h,hc=fixture()
    def typed(n,v):return valid(PID+'#/$defs/'+n,v)
    def chain(q,g,p,i,c):
        return all(typed(n,v) for n,v in [('CommandRequest',q),('ExecutionGuard',g),('DispatchPermit',p)]) \
            and valid(IID+'#/$defs/IntentRef',i) and chain_error(q,g,p,i,c) is None
    expect('自动化来源贯穿全部对象',chain(q,g,p,i,c))
    qq=copy.deepcopy(q);qq.update(context_id='other',idempotency_key='other',correlation_id='other')
    expect('身份只排顶层运输字段',identity(qq)==identity(q))
    qq=copy.deepcopy(q);qq['automation_binding']['execution_id']='other'
    expect('新来源字段进入命令身份',identity(qq)!=identity(q))
    qq=copy.deepcopy(q);qq['parameters']['context_id']='business-value'
    expect('嵌套同名业务字段不被移除',identity(qq)!=identity(q))
    grant=copy.deepcopy(c['grant']);grant.update(principal_id='seamer-service',device_actions=[dict(device_id=q['device_id'],
        action_id=q['action_id'],capability_version=q['capability_version'])],parameter_constraints=[],
        validity=dict(not_before='2026-10-20T00:00:00.000Z',not_after='2026-10-21T00:00:00.000Z',authorization_policy_revision='1'),
        issuer_id='issuer-demo',issuer_epoch='issuer-epoch')
    expect('来源域RunGrant结构',typed('RunGrant',grant))
    bad=copy.deepcopy(grant);del bad['origin_scope']
    expect('旧无域RunGrant拒绝',not typed('RunGrant',bad))
    expect('拒绝快照结构与全集',typed('RunDenySnapshot',s) and snapshot_error(s,sc) is None)
    expect('完整RUN屏障',valid(IID,f) and valid(IID,a) and fence_error(f,a,fc) is None)
    query=copy.deepcopy(old['frames']['QUERY_BARRIER']);query.update(ipc_version=IPC_VERSION,message_id='query-a',seq='12')
    query['body']={k:f['body'][k] for k in ('operation_id','barrier_id')}
    queried=copy.deepcopy(a);queried.update(message_id='query-result',reply_to='query-a',seq='13')
    expect('查询返回原冻结RUN覆盖',valid(IID,query) and valid(IID,queried) and query_barrier_error(query,queried,a,fc) is None)
    missing=copy.deepcopy(queried);missing['body']['coverage']=[]
    expect('查询不能重算为空覆盖',query_barrier_error(query,missing,a,fc)=='frozen_result')
    wrong=copy.deepcopy(query);wrong['body']['operation_id']='other'
    expect('查询必须绑定原操作',query_barrier_error(wrong,queried,a,fc)=='barrier_identity')
    wrong=copy.deepcopy(queried);wrong['reply_to']=f['message_id']
    expect('查询回复不借原FENCE消息身份',query_barrier_error(query,wrong,a,fc)=='envelope')
    expect('过期grant不阻止当前授权保护',typed('ProtectionRequest',h) and http_error(h,hc) is None)
    # 全21帧：19历史正例只升级形状，新增两帧另作完整新关联检查。
    frames=copy.deepcopy(old['frames'])
    def upgrade(v):
        if isinstance(v,list):return [upgrade(x) for x in v]
        if not isinstance(v,dict):return v
        v={k:upgrade(x) for k,x in v.items()}
        if 'origin' in v and ('idempotency_key' in v or 'deadline_policy' in v):v['automation_binding']=None
        if 'guard_digest' in v and 'binding' in v:v['automation_binding']=None
        if 'dispatch_intent_id' in v and 'admission_origin' in v and 'deadline_policy' not in v:
            v.update(origin='manual',automation_binding=None,automation_binding_digest=None)
        return v
    frames=upgrade(frames)
    for name,frame in frames.items():
        frame['ipc_version']=IPC_VERSION
        if name=='HELLO':
            frame['body']['supported_ipc_versions']=[IPC_VERSION];frame['body']['supported_features']+=list(FEATURES)
        if name=='HELLO_ACK':
            frame['body']['selected_ipc_version']=IPC_VERSION;frame['body']['selected_features']+=list(FEATURES)
        if name=='GUARD_ACK':frame['body']['automation_binding_digest']=None
        if name=='OPEN_GATE':frame['body']['run_deny_snapshot']=copy.deepcopy(s)
        if name=='OPEN_GATE_ACK':frame['body'].update(run_deny_snapshot_revision=s['snapshot_revision'],run_deny_snapshot_digest=s['snapshot_digest'])
    frames.update(RUN_FENCE=f,RUN_FENCE_ACK=a)
    expect('完整21帧集合',len(frames)==21 and {r['$ref'].split('/')[-1] for r in generated['ipc-v05.schema.json']['oneOf']}==set(frames))
    for n,v in frames.items():
        expect('帧结构-'+n,valid(IID,v))
        bad=copy.deepcopy(v);bad['ipc_version']='ipc/0.4.0-panel-draft.1'
        expect('拒旧协议-'+n,not valid(IID,bad))
    for name,field in [('HELLO','supported_features'),('HELLO_ACK','selected_features')]:
        for feature in FEATURES:
            v=copy.deepcopy(frames[name]);v['body'][field].remove(feature)
            expect(name+'缺特性-'+feature,not valid(IID,v))
    hello=copy.deepcopy(frames['HELLO']);hello_ack=copy.deepcopy(frames['HELLO_ACK'])
    hello['body']['supported_features']=copy.deepcopy(hello_ack['body']['selected_features'])
    hello_ack['reply_to']=hello['message_id']
    expect('握手选择来自实际offer',valid(IID,hello) and valid(IID,hello_ack) and handshake_error(hello,hello_ack,fc) is None)
    hello['body']['supported_features'].remove('typed_obs_evidence')
    expect('不能选择未提供的历史特性',handshake_error(hello,hello_ack,fc)=='unoffered_feature')
    bad=copy.deepcopy(frames['OPEN_GATE']);del bad['body']['run_deny_snapshot']
    expect('缺完整拒绝快照不开闸',not valid(IID,bad))
    for field in ('run_id','execution_id','step_id','definition_version'):
        qq,gg,pp,ii=copy.deepcopy([q,g,p,i]);value='2' if field=='definition_version' else 'other'
        for item in (qq,gg,pp,ii):item['automation_binding'][field]=value
        if field in qq['run_binding']:qq['run_binding'][field]=value
        seal(gg,'guard_digest');pp['guard_digest']=ii['guard_digest']=gg['guard_digest']
        pp['content_digest']=identity(qq);ii['automation_binding_digest']=digest(ii['automation_binding'])
        expect('全重算仍拒错原受理-'+field,not chain(qq,gg,pp,ii,c))
    for n,value in [('definition_version','1.0.0'),('definition_version','01'),('arm_generation','6\n')]:
        qq=copy.deepcopy(q);qq['run_binding'][n]=value
        expect('拒旧或非法RunBinding-'+n+repr(value),not typed('CommandRequest',qq))
    for field,value in [('other_current_gates',False),('grant_current',False),('now',g['authorization_deadline_tick_ns'])]:
        cc=copy.deepcopy(c);cc[field]=value
        expect('发送仍需原门控-'+field,not chain(q,g,p,i,cc))
    for field in ('origin_scope','run_id','definition_version','arm_generation','grant_id','revision'):
        cc=copy.deepcopy(c);cc['grant'][field]={'authority_service_id':'other','database_instance_id':'other'} if field=='origin_scope' else '999'
        expect('拒错grant-'+field,not chain(q,g,p,i,cc))
    cc=copy.deepcopy(c);cc['installed_entries'][0]['selector']['deny_through_generation']='6'
    expect('等号代次被拒绝',not chain(q,g,p,i,cc))
    cc['installed_entries'][0]['selector']['origin_scope']['database_instance_id']='other'
    expect('另一来源库不误拒',chain(q,g,p,i,cc))
    # 合法人工和面板仍可承载，原权限当前性只作为明确合成前提。
    for panel in (False,True):
        qq,gg,pp,ii,cc=copy.deepcopy([q,g,p,i,c])
        qq['origin']='manual';qq['automation_binding']=None;del qq['run_binding']
        gg=copy.deepcopy(old['base']['guard']);gg['automation_binding']=None
        if not panel:gg.update(admission_origin='non_panel',panel_binding=None)
        seal(gg,'guard_digest')
        pp.update(origin='manual',arm_generation=None,grant_revision=None,automation_binding=None,
            admission_origin=gg['admission_origin'],panel_binding_digest=digest(gg['panel_binding']) if panel else None,
            content_digest=identity(qq),guard_digest=gg['guard_digest'])
        ii.update(origin='manual',automation_binding=None,automation_binding_digest=None,admission_origin=gg['admission_origin'],
            panel_binding_digest=pp['panel_binding_digest'],guard_digest=gg['guard_digest'])
        cc.update(accepted_request=qq,accepted_binding=None,admission_origin=gg['admission_origin'],panel_binding=gg['panel_binding'])
        expect('保留人工路径-'+str(panel),chain(qq,gg,pp,ii,cc))
    gg=copy.deepcopy(g);gg['admission_origin']='panel';gg['panel_binding']=old['base']['guard']['panel_binding'];seal(gg,'guard_digest')
    expect('面板不能自动化',not typed('ExecutionGuard',gg))
    # Guard与开闸ACK必须回显当前请求，旧ACK不证明新状态。
    install=copy.deepcopy(frames['GUARD_INSTALL']);install['body']['guard']=g;install['body']['content_digest']=identity(q)
    ga=copy.deepcopy(frames['GUARD_ACK']);ga['reply_to']=install['message_id']
    ga['body'].update({k:g[k] for k in ('guard_id','guard_digest','permit_id','command_id')})
    ga['body'].update(content_digest=identity(q),automation_binding_digest=digest(g['automation_binding']))
    ga['body']['panel_binding_digest']=None
    ac=copy.deepcopy(fc);ac.update(last_request_seq='0',last_ack_seq='0')
    expect('自动化GUARD_INSTALL',valid(IID,install))
    expect('自动化GUARD_ACK',valid(IID,ga) and guard_ack_error(install,ga,ac) is None)
    for field in ('automation_binding_digest','guard_digest','content_digest'):
        v=copy.deepcopy(ga);v['body'][field]=digest('other')
        expect('ACK错绑定-'+field,valid(IID,v) and guard_ack_error(install,v,ac) is not None)
    gate=copy.deepcopy(frames['OPEN_GATE']);gate_ack=copy.deepcopy(frames['OPEN_GATE_ACK']);gate_ack['reply_to']=gate['message_id']
    gate_ctx=copy.deepcopy(ac);gate_ctx.update(snapshot_context=sc,current_gate_token=gate['body']['gate_token'])
    expect('开闸ACK绑定完整快照',gate_ack_error(gate,gate_ack,gate_ctx) is None)
    for field,value in [('gate_token','other'),('run_deny_snapshot_revision','8'),('run_deny_snapshot_digest',digest('other'))]:
        v=copy.deepcopy(gate_ack);v['body'][field]=value
        expect('拒错误开闸ACK-'+field,valid(IID,v) and gate_ack_error(gate,v,gate_ctx) is not None)
    v=copy.deepcopy(gate_ack);v['ipc_session_id']='old'
    expect('拒旧连接开闸ACK',gate_ack_error(gate,v,gate_ctx)=='envelope')
    for mutate,name in [(lambda x:x['entries'].clear(),'漏墓碑'),(lambda x:x['entries'][0]['selector'].update(run_id='other'),'同数量换run'),
                        (lambda x:x['entries'].append(copy.deepcopy(x['entries'][0])),'重复项')]:
        v=copy.deepcopy(s);mutate(v);seal(v,'snapshot_digest')
        expect('重算快照仍拒-'+name,snapshot_error(v,sc) is not None)
    cc=copy.deepcopy(sc);cc['installed_entries'][0]['selector']['deny_through_generation']='6'
    expect('新fence先到旧快照拒绝',snapshot_error(s,cc)=='rollback')
    stale_ctx=copy.deepcopy(gate_ctx);stale_ctx['snapshot_context']=cc
    expect('旧快照ACK不得抵消新屏障',gate_ack_error(gate,gate_ack,stale_ctx)=='snapshot')
    second=copy.deepcopy(s['entries'][0]);second['selector']['run_id']='run-b'
    ordered=copy.deepcopy(s);ordered['entries'].append(second);ordered['snapshot_revision']='10';seal(ordered,'snapshot_digest')
    oc=copy.deepcopy(sc);oc['authoritative_snapshot']=copy.deepcopy(ordered)
    expect('多run完整拒绝快照',snapshot_error(ordered,oc) is None)
    ordered['entries'].reverse();seal(ordered,'snapshot_digest');oc['authoritative_snapshot']=copy.deepcopy(ordered)
    expect('权威声称也不能绕过规范顺序',snapshot_error(ordered,oc)=='canonical_set')
    same_revision=copy.deepcopy(s);same_revision['entries'].append(second);seal(same_revision,'snapshot_digest')
    cc=copy.deepcopy(sc);cc['authoritative_snapshot']=copy.deepcopy(same_revision)
    expect('相同快照修订不能换正文',snapshot_error(same_revision,cc)=='snapshot_revision_conflict')
    empty=seal(dict(controller_scope=s['controller_scope'],snapshot_revision='0',entries=[]),'snapshot_digest')
    expect('真空全集可用',snapshot_error(empty,dict(controller_scope=s['controller_scope'],authoritative_snapshot=empty,
        installed_entries=[],installed_snapshot_revision='0',installed_snapshot_digest=None)) is None)
    for field in KEYS:
        ff,aa,cc=copy.deepcopy([f,a,fc])
        ff['body']['open_intents'][0][field]='clock_'+'f'*64 if field=='clock_domain_id' else digest('other') if field=='descriptor_digest' else 'old'
        cc['ledger']=copy.deepcopy(ff['body']['open_intents']);ff['body']['ledger_digest']=digest(cc['ledger'])
        aa['body']['ledger_digest']=ff['body']['ledger_digest'];aa['body']['coverage'][0].update(intent=copy.deepcopy(cc['ledger'][0]),disposition='not_sent',proof='never_received')
        cc['known_entered']=[]
        expect('旧发送世代不能报未发-'+field,fence_error(ff,aa,cc)=='old_exit')
    for field,value in [('reply_to','other'),('ipc_session_id','old'),('seq','10')]:
        aa=copy.deepcopy(a);aa[field]=value
        expect('拒旧ACK-'+field,fence_error(f,aa,fc)=='envelope')
    for field,value in [('peer_authenticated',False),('ack_direction','controller_to_worker'),('all_exits_proven',False)]:
        cc=copy.deepcopy(fc);cc[field]=value
        expect('屏障可信前提-'+field,fence_error(f,a,cc) is not None)
    aa=copy.deepcopy(a);aa['body']['coverage'][0].update(disposition='unknown',proof='send_uncertain')
    expect('已发事实不降级',fence_error(f,aa,fc)=='lost_send_fact')
    cc=copy.deepcopy(fc);cc['known_entered']=[]
    expect('未知可保留',fence_error(f,aa,cc) is None)
    ff,aa,cc=copy.deepcopy([f,a,fc])
    another=copy.deepcopy(i);another.update(permit_id='permit-2',dispatch_intent_id='intent-2')
    ff['body']['open_intents'].append(another);ff['body']['ledger_digest']=digest(ff['body']['open_intents'])
    cc['ledger']=copy.deepcopy(ff['body']['open_intents'])
    aa['body']['ledger_digest']=ff['body']['ledger_digest']
    aa['body']['coverage'].append(dict(intent=copy.deepcopy(another),disposition='unknown',proof='send_uncertain'))
    expect('同command多许可混合覆盖',valid(IID,ff) and valid(IID,aa) and fence_error(ff,aa,cc) is None)
    ff['body']['open_intents'].reverse();cc['ledger'].reverse();aa['body']['coverage'].reverse()
    ff['body']['ledger_digest']=aa['body']['ledger_digest']=digest(cc['ledger'])
    expect('重算仍拒乱序多许可',fence_error(ff,aa,cc)=='canonical_ledger')
    cc=copy.deepcopy(hc);cc['stored_request']=copy.deepcopy(h);cc['capacity']=False
    expect('原保护查旧不再占额度',http_error(h,cc) is None)
    for field,value in [('basis','emergency_fault'),('target_set_digest',digest('other')),('operation_id','other')]:
        hh=copy.deepcopy(h);hh[field]=value
        # operation_id为新键，应由不同上下文查库；此断言只验证不能错误返回原记录。
        expect('原请求不能换字段-'+field,http_error(hh,cc) is not None)
    for field in ('mtls','paired','permission','capacity'):
        cc=copy.deepcopy(hc);cc[field]=False
        expect('保护准入-'+field,http_error(h,cc) is not None)
    lookup=dict(contract_version=VERSION,controller_scope=h['controller_scope'],origin_scope=h['selector']['origin_scope'],
        operation_id=h['operation_id'],selector_digest=h['selector_digest'],target_set_digest=h['target_set_digest'])
    expect('lookup结构',typed('ProtectionLookup',lookup))
    expect('lookup未找到不能带记录',not typed('ProtectionLookupResult',dict(state='not_found',record={})))
    api=generated['protection.openapi.json']
    expect('仅两保护HTTP操作',len(api['paths'])==2)
    for path,op in api['paths'].items():
        post=op['post'];expect('mTLS及权限-'+path,post['security']==[{'InternalMTLS':[]}] and post['x-required-permission']=='automation.protect')
        expect('所有响应不可缓存-'+path,all(r['headers']['Cache-Control']['schema']=={'const':'no-store'} for r in post['responses'].values()))
        sample=h if post['operationId']=='protectRunGeneration' else lookup
        schema=post['requestBody']['content']['application/json']['schema']
        root={**api,'$schema':'https://json-schema.org/draft/2020-12/schema'}
        expect('HTTP投影正例-'+path,Draft202012Validator({**root,**schema}).is_valid(sample))
        bad=copy.deepcopy(sample);bad['unexpected']=True
        expect('HTTP投影拒额外字段-'+path,not Draft202012Validator({**root,**schema}).is_valid(bad))
    expect('HTTP闭包不导出设备或面板内部对象',not any(x.endswith(('_ExecutionGuard','_DispatchPermit','_PanelExecutionBinding','_CommandRequest')) for x in api['components']['schemas']))
    return dict(all_passed=True,approved=False,checks=len(results),results=results,
        runtime_validation=dict(http=0,ipc=0,identity_providers=0,sqlite=0,concurrency=0,devices=0),
        limitations=['19帧旧路径只验证升级后结构','完整权限时钟资源门控为人工前提，新增判定非生产授权',
            '固定快照比较非真实writer或网络顺序','公共HTTP和准备账本尚未整体迁移'],
        input_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})


def bindings(staged):
    def read(p):return subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else p.read_bytes()
    r=json.loads(read(REPORT));assert r['all_passed']
    assert set(r['input_sha256'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
    for p in INPUTS:assert hashlib.sha256(read(p)).hexdigest()==r['input_sha256'][p.relative_to(ROOT).as_posix()],p
    print('保护协议报告字节绑定通过:',len(INPUTS),'；未重跑检查')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true')
    args=parser.parse_args()
    if args.check_report:bindings(args.staged)
    else:
        result=run()
        if args.report:REPORT.write_bytes(encoded(result))
        print('保护HTTP与完整IPC候选检查通过:',result['checks'])
