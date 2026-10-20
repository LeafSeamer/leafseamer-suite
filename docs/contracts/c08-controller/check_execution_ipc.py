"""30帧逐传输及屏障尝试候选的离线检查；可信状态为夹具，不执行真实IPC。"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import rfc8785
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from build_execution_ipc import HERE,BASE,OLD,PROTOCOL,IID,VERSION,FEATURES,FENCES,NEW_FRAMES,build,encoded

sys.path.insert(0,str(BASE/'c05-protection'))
spec=importlib.util.spec_from_file_location('old_protocol_check',BASE/'c05-protection/check_protocol.py')
O=importlib.util.module_from_spec(spec);spec.loader.exec_module(O)
ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(O.INPUTS+[OLD,PROTOCOL]+[HERE/n for n in (
    'BARRIER_ATTEMPTS.md','build_execution_ipc.py','execution-ipc.schema.json','check_execution_ipc.py')]))


def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def seal(v,key):v[key]=digest({k:x for k,x in v.items() if k!=key});return v
def packet_ref(p):return {k:p[k] for k in ('packet_id','packet_digest')}
def packet(i):
    raw=b'\x01\x02';sha='sha256:'+hashlib.sha256(raw).hexdigest()
    return seal(dict(packet_id='packet-'+i['dispatch_intent_id'],command_id=i['command_id'],attempt_id=i['attempt_id'],
        primitive_id='primitive-'+i['dispatch_intent_id'],writer_exit_id='exit-a',device_session_id=i['device_session_id'],
        socket_instance_id='socket-a',protocol_session='session-a',wire_packet_id='1',tracking_ids=['track-a'],
        immutable_bytes_ref=dict(object_id='bytes-a',digest=sha),byte_length=len(raw),sha256=sha,
        transport_profile_ref=dict(object_id='profile-a',digest=digest('profile')),
        primitive_plan_ref=dict(object_id='plan-a',digest=digest('plan'))),'packet_digest')


def transmission(i,window,ordinal='0',permit=None):
    intent=copy.deepcopy(i)
    if permit:intent['permit_id']=permit
    return dict(transmission_id='transmission-'+i['dispatch_intent_id']+'-'+ordinal,
        packet_ref=packet_ref(packet(i)),primitive_id=packet(i)['primitive_id'],
        intent=intent,ordinal=ordinal,kind='initial' if ordinal=='0' else 'protocol_resend',
        cause='dispatch' if ordinal=='0' else 'timeout',
        trigger_observation_ref=None if ordinal=='0' else dict(object_id='timeout-a',digest=digest('timeout')),
        parent_dispatch_intent_id=i['dispatch_intent_id'],initial_permit_id=i['permit_id'],
        issued_revision=str(int(ordinal)+1),send_window=copy.deepcopy(window))


def binding(name):
    return dict(cut_id='cut-'+name,cut_digest=digest('placeholder'),target_exit_id='exit-a',
                attempt_ordinal='1',previous_barrier_id=None)


def cut_digest(frame):
    return digest(dict(type=frame['type'],target_exit_id=frame['body']['attempt_binding']['target_exit_id'],
        body={k:v for k,v in frame['body'].items() if k not in ('barrier_id','attempt_binding')}))


def fixtures():
    old,q,g,p,i,c,s,sc,run,run_ack,fc,h,hc=O.fixture()
    def upgrade(v):
        if isinstance(v,list):return [upgrade(x) for x in v]
        if not isinstance(v,dict):return v
        v={k:upgrade(x) for k,x in v.items()}
        if 'origin' in v and ('idempotency_key' in v or 'deadline_policy' in v):v['automation_binding']=None
        if 'guard_digest' in v and 'binding' in v:v['automation_binding']=None
        if 'dispatch_intent_id' in v and 'admission_origin' in v and 'deadline_policy' not in v:
            v.update(origin='manual',automation_binding=None,automation_binding_digest=None)
        return v
    frames=upgrade(copy.deepcopy(old['frames']))
    frames.update(RUN_FENCE=copy.deepcopy(run),RUN_FENCE_ACK=copy.deepcopy(run_ack))
    window=copy.deepcopy(frames['DISPATCH']['body']['send_window'])
    for name,frame in frames.items():
        frame['ipc_version']=VERSION
        if name=='HELLO':
            frame['body']['supported_ipc_versions']=[VERSION]
            frame['body']['supported_features']+=list(O.FEATURES)+list(FEATURES)
        if name=='HELLO_ACK':
            frame['body']['selected_ipc_version']=VERSION
            frame['body']['selected_features']+=list(O.FEATURES)+list(FEATURES)
        if name=='GUARD_ACK':frame['body']['automation_binding_digest']=None
        if name=='OPEN_GATE':frame['body']['run_deny_snapshot']=copy.deepcopy(s)
        if name=='OPEN_GATE_ACK':frame['body'].update(run_deny_snapshot_revision=s['snapshot_revision'],run_deny_snapshot_digest=s['snapshot_digest'])
    for name in FENCES:
        f,a=frames[name],frames[name+'_ACK']
        f['body']['ledger_digest']=digest(f['body']['open_intents'])
        a['body']['ledger_digest']=f['body']['ledger_digest']
        txs=[transmission(x,window) for x in f['body']['open_intents']]
        f['body'].update(attempt_binding=binding(name),open_transmission_intents=txs,
                         transmission_ledger_digest=digest(txs))
        f['body']['attempt_binding']['cut_digest']=cut_digest(f)
        cov=[dict(intent=transmission(x['intent'],window),disposition=x['disposition'],proof=x['proof'])
             for x in a['body']['coverage']]
        a['body'].update(attempt_binding=copy.deepcopy(f['body']['attempt_binding']),
            transmission_ledger_digest=digest(txs),transmission_coverage=cov,effective_tick_ns='100')
    frames['QUERY_BARRIER']['body']['attempt_binding']=copy.deepcopy(frames['FENCE']['body']['attempt_binding'])
    body=frames['DISPATCH']['body'];permit=body['permit']
    mi={k:copy.deepcopy(i[k]) for k in i}
    for k in mi:
        if k in permit:mi[k]=copy.deepcopy(permit[k])
        elif k in frames['DISPATCH']:mi[k]=copy.deepcopy(frames['DISPATCH'][k])
    mi.update(origin='manual',automation_binding=None,automation_binding_digest=None)
    pkt=packet(mi);t=transmission(mi,window)
    permit.update(transmission=t,budget_revision='1')
    body.update(prepare_id='prepare-a',packet=pkt,resend_request_id=None)
    frames['SEND_REPORT']['body'].update(transmission_id=t['transmission_id'],packet_ref=packet_ref(pkt),
        ordinal='0',gate_io_seq='1',transport_entered_tick_ns=
        '100' if frames['SEND_REPORT']['body']['disposition']=='in_flight' else None,
        socket_callback_observation_ref=None)
    def frame(name,body,response=False):
        f=copy.deepcopy(frames['FENCE_ACK'] if response else frames['FENCE'])
        f.update(type=name,message_id='message-'+name,reply_to='request-a' if response else None,body=body)
        return f
    frames['ENCODE_PACKET']=frame('ENCODE_PACKET',dict(prepare_id='prepare-a',command_id=mi['command_id'],
        attempt_id=mi['attempt_id'],primitive_id=pkt['primitive_id'],device_session_id=mi['device_session_id'],
        request=copy.deepcopy(body['request']),primitive_plan_ref=copy.deepcopy(pkt['primitive_plan_ref']),
        transport_profile_ref=copy.deepcopy(pkt['transport_profile_ref']),guard_id=mi['guard_id'],
        guard_digest=mi['guard_digest'],expires_tick_ns=window['latest_tick_ns']))
    frames['PACKET_ENCODING_FAILED']=frame('PACKET_ENCODING_FAILED',dict(prepare_id='prepare-a',reason='expired'),True)
    frames['PREPARE_PACKET']=frame('PREPARE_PACKET',dict(prepare_id='prepare-a',packet=pkt,bytes_hex='0102'),True)
    frames['PREPARE_PACKET_REJECTED']=frame('PREPARE_PACKET_REJECTED',
        dict(prepare_id='prepare-a',packet_ref=packet_ref(pkt),reason='protected'),True)
    frames['RESEND_REQUEST']=frame('RESEND_REQUEST',dict(request_id='resend-a',packet_ref=packet_ref(pkt),
        cause='timeout',observation_ref=dict(object_id='timeout-a',digest=digest('timeout'))))
    rb=copy.deepcopy(body);rt=transmission(mi,window,'1','resend-permit')
    rb['permit'].update(permit_id='resend-permit',transmission=rt,budget_revision='2')
    rb['resend_request_id']='resend-a'
    frames['RESEND_DISPATCH']=frame('RESEND_DISPATCH',rb,True)
    frames['RESEND_REJECTED']=frame('RESEND_REJECTED',dict(request_id='resend-a',packet_ref=packet_ref(pkt),reason='budget'),True)
    b=frames['RUN_FENCE']['body']
    bid={k:copy.deepcopy(b[k]) for k in ('operation_id','barrier_id','attempt_binding')}
    frames['BARRIER_UNAVAILABLE']=frame('BARRIER_UNAVAILABLE',{**bid,'reason':'cache_miss'},True)
    frames['BARRIER_STORED']=frame('BARRIER_STORED',{**bid,'ack_digest':digest(frames['RUN_FENCE_ACK']['body']),'record_revision':'1'})
    return frames


def packet_error(p,raw,c):
    if not c['trusted_preparation'] or p!=c['expected_packet']:return 'binding'
    if seal(copy.deepcopy(p),'packet_digest')!=p:return 'digest'
    if p['byte_length']!=len(raw) or p['sha256']!='sha256:'+hashlib.sha256(raw).hexdigest():return 'bytes'
    if p['immutable_bytes_ref']['digest']!=p['sha256']:return 'bytes_ref'
    return None


def encoding_error(request,response,c):
    if not c['trusted_preparation']:return 'binding'
    if any(request[k]!=c['current'][k] or response[k]!=c['current'][k] for k in O.KEYS):return 'exit'
    if response['reply_to']!=request['message_id']:return 'reply'
    b=request['body']
    if b!=c['expected_request'] or response['body']['prepare_id']!=b['prepare_id']:return 'binding'
    if c['now']>=int(b['expires_tick_ns']):return 'expired'
    if response['type']=='PACKET_ENCODING_FAILED':return 'encoding_failed'
    p=response['body']['packet']
    for k in ('command_id','attempt_id','primitive_id','device_session_id','primitive_plan_ref','transport_profile_ref'):
        if p[k]!=b[k]:return 'plan_binding'
    return packet_error(p,bytes.fromhex(response['body']['bytes_hex']),c)


def send_error(body,c):
    p,t=body['permit'],body['permit']['transmission']
    i=t['intent'];root=c['root_intent']
    if not c['guard_current'] or not c['resource_clear'] or not c['budget_available']:return 'gate'
    if c['packet_acknowledged'] or c['pending_permit']:return 'resend_blocked'
    if body['request']!=c['request'] or body['prepare_id']!=c['prepare_id']:return 'accepted_request'
    if any(p[k]!=c['current_permit'][k] for k in c['current_permit']):return 'current_permit'
    if (body['guard_id'],body['guard_digest'])!=(p['guard_id'],p['guard_digest']):return 'guard_binding'
    if body['packet']!=c['packet'] or t['packet_ref']!=packet_ref(c['packet']):return 'packet'
    if t['primitive_id']!=c['packet']['primitive_id']:return 'primitive'
    if any(i[k]!=root[k] for k in root if k not in ('permit_id','guard_id','guard_digest')):return 'origin_binding'
    if any(p[k]!=i[k] for k in ('command_id','attempt_id','dispatch_intent_id','permit_id','guard_id','guard_digest',
                               'origin','automation_binding','worker_boot_id','controller_boot_id','device_session_id',
                               'clock_domain_id','descriptor_digest','admission_origin','panel_binding_digest')):return 'permit'
    if t['initial_permit_id']!=root['permit_id'] or t['parent_dispatch_intent_id']!=root['dispatch_intent_id']:return 'parent'
    if int(t['ordinal'])!=c['next_ordinal'] or int(t['issued_revision'])!=c['next_issued']:return 'sequence'
    if t['kind']=='initial' and i['permit_id']!=root['permit_id']:return 'initial'
    if t['kind']=='protocol_resend' and i['permit_id']==root['permit_id']:return 'permit_reuse'
    if body['send_window']!=t['send_window']:return 'window'
    w=t['send_window']
    if w['clock_domain_id']!=i['clock_domain_id'] or w['descriptor_digest']!=i['descriptor_digest']:return 'clock'
    if not int(w['earliest_tick_ns'])<=c['now']<int(w['latest_tick_ns'])<=c['original_deadline']:return 'deadline'
    if t['kind']=='protocol_resend':
        r=c['resend_request']
        if body['resend_request_id']!=r['request_id'] or t['cause']!=r['cause'] \
           or t['trigger_observation_ref']!=r['observation_ref']:return 'resend_request'
    return None


def fence_error(f,a,c):
    b,ack=f['body'],a['body']
    if not c['peer_authenticated']:return 'peer'
    if any(f[k]!=c['current'][k] or a[k]!=c['current'][k] for k in O.KEYS):return 'exit'
    if a['reply_to']!=f['message_id'] or a['type']!=f['type']+'_ACK':return 'reply'
    if b['attempt_binding']!=c['attempt_binding'] or ack['attempt_binding']!=b['attempt_binding']:return 'attempt'
    if cut_digest(f)!=b['attempt_binding']['cut_digest']:return 'cut_digest'
    if b['open_intents']!=c['business'] or b['open_transmission_intents']!=c['transmissions']:return 'complete_cut'
    if b['issued_cut_revision']!=c['cut_revision'] or ack['issued_cut_revision']!=b['issued_cut_revision']:return 'cut_revision'
    intents=b['open_intents'];ts=b['open_transmission_intents']
    for values,field in ((intents,'ledger_digest'),(ts,'transmission_ledger_digest')):
        keys=[v['permit_id'] if field=='ledger_digest' else v['intent']['permit_id'] for v in values]
        if keys!=sorted(set(keys)) or b[field]!=digest(values) or ack[field]!=b[field]:return 'ledger'
    roots={x['dispatch_intent_id']:x for x in intents}
    if len(roots)!=len(intents):return 'duplicate_business_identity'
    if len({t['transmission_id'] for t in ts})!=len(ts) or len({
        (t['packet_ref']['packet_id'],t['ordinal']) for t in ts})!=len(ts):return 'transmission_identity'
    packets,parents={},{}
    for t in ts:
        root=roots.get(t['parent_dispatch_intent_id'])
        if root is None or any(t['intent'][k]!=root[k] for k in root if k not in ('permit_id','guard_id','guard_digest')):return 'parent'
        if t['initial_permit_id']!=root['permit_id'] or int(t['issued_revision'])>int(b['issued_cut_revision']):return 'parent'
        if (t['kind']=='initial')!=(t['intent']['permit_id']==root['permit_id']):return 'parent'
        packet_id=t['packet_ref']['packet_id']
        identity=(t['packet_ref']['packet_digest'],t['parent_dispatch_intent_id'],t['primitive_id'])
        if packet_id in packets and packets[packet_id]!=identity:return 'packet_alias'
        if t['parent_dispatch_intent_id'] in parents and parents[t['parent_dispatch_intent_id']]!=packet_id:return 'packet_alias'
        packets[packet_id]=identity;parents[t['parent_dispatch_intent_id']]=packet_id
    if [x['intent'] for x in ack['coverage']]!=intents \
       or [x['intent'] for x in ack['transmission_coverage']]!=ts:return 'coverage'
    for x in ack['transmission_coverage']:
        if x['intent']['intent']['permit_id'] in c['known_entered'] and x['disposition']!='in_flight':return 'downgrade'
    for x in ack['coverage']:
        children=[v['disposition'] for v in ack['transmission_coverage']
                  if v['intent']['parent_dispatch_intent_id']==x['intent']['dispatch_intent_id']]
        expected='in_flight' if 'in_flight' in children or x['intent']['permit_id'] in c['known_business_entered'] \
            else 'unknown' if not children or 'unknown' in children else 'not_sent'
        if x['disposition']!=expected:return 'business_summary'
    if not c['request_tick']<=int(ack['effective_tick_ns'])<=c['received_tick']:return 'effective_time'
    # 原领域绑定不因新增覆盖被删除。
    for k in ('operation_id','barrier_id','selector','selector_digest','controller_scope','target_deny_revision'):
        if f['type']=='FENCE' and k in ('operation_id','barrier_id'):
            if ack['ack'][k]!=b[k]:return 'domain_binding'
            continue
        if k in b and ack.get(k)!=b[k]:return 'domain_binding'
    if f['type']=='FENCE':
        nested=ack['ack']
        if nested['control_epoch']!=b['control_epoch'] or nested['installed_version']!=b['target_version'] \
           or ack['gate_revision']!=b['target_gate_revision']:return 'control_binding'
        if any(nested[k]!=f[k] for k in ('controller_boot_id','worker_boot_id','device_id','clock_domain_id','descriptor_digest')):return 'exit'
    if f['type']=='AUTH_FENCE' and (ack['target_authorization_revision']!=b['target_authorization_revision']
        or ack['applied_authorization_revision']!=b['target_authorization_revision']):return 'authorization_binding'
    if f['type']=='TIME_FENCE' and any(ack[k]!=b[k] for k in (
        'clock_domain_id','descriptor_digest','time_policy_revision','old_clock_generation','new_clock_generation')):return 'time_binding'
    return None


def query_error(query,response,original,c):
    if not c['peer_authenticated']:return 'peer'
    if any(query[k]!=c['current'][k] or response[k]!=c['current'][k] for k in O.KEYS):return 'exit'
    if response['reply_to']!=query['message_id']:return 'reply'
    identity=original['body']['ack'] if original['type']=='FENCE_ACK' else original['body']
    expected={k:identity[k] for k in ('operation_id','barrier_id')}
    expected['attempt_binding']=original['body']['attempt_binding']
    if query['body']!=expected:return 'query_binding'
    if response['type']=='BARRIER_UNAVAILABLE':
        if any(response['body'][k]!=v for k,v in expected.items()):return 'query_binding'
        return 'unavailable_without_effect'
    if response['type']!=original['type'] or response['body']!=original['body']:return 'frozen_ack'
    return None


def stored_error(stored,original,c):
    if not c['peer_authenticated'] or not c['ack_durable']:return 'not_durable'
    if any(stored[k]!=c['current'][k] for k in O.KEYS):return 'exit'
    identity=original['body']['ack'] if original['type']=='FENCE_ACK' else original['body']
    if any(stored['body'][k]!=identity[k] for k in ('operation_id','barrier_id')) \
       or stored['body']['attempt_binding']!=original['body']['attempt_binding']:return 'binding'
    if stored['body']['ack_digest']!=digest(original['body']) \
       or stored['body']['record_revision']!=c['stored_revision']:return 'stored_reference'
    return None


def run():
    schema=build();assert (HERE/'execution-ipc.schema.json').read_bytes()==encoded(schema)
    resources={json.loads(p.read_bytes())['$id']:json.loads(p.read_bytes()) for p in [*O.FILES.values(),O.CHANNEL,OLD,PROTOCOL]}
    resources[IID]=schema
    Draft202012Validator.check_schema(schema)
    registry=Registry().with_resources((u,Resource.from_contents(s)) for u,s in resources.items())
    def valid(v,definition=None):
        target={'$ref':IID+('#/$defs/'+definition if definition else '')}
        return Draft202012Validator(target,registry=registry).is_valid(v)
    checks=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    frames=fixtures()
    check('30帧完整集合',set(frames)=={x['$ref'].split('/')[-1] for x in schema['oneOf']} and len(frames)==30)
    for name,frame in frames.items():
        check('帧结构'+name,valid(frame))
        bad=copy.deepcopy(frame);bad['ipc_version']=O.IPC_VERSION
        check('旧协议不可混投'+name,valid(bad),False)
        bad=copy.deepcopy(frame);bad['body']['unexpected']=True
        check('拒绝额外写字段'+name,valid(bad),False)
    for name,field in [('HELLO','supported_features'),('HELLO_ACK','selected_features')]:
        for feature in FEATURES:
            bad=copy.deepcopy(frames[name]);bad['body'][field].remove(feature)
            check('缺特性'+name+feature,valid(bad),False)
    for value in ('01','-1','1\n','100000000000000000000'):
        check('新计数拒绝'+repr(value),valid(value,'Counter'),False)
    prepare=frames['PREPARE_PACKET']['body'];p=prepare['packet']
    check('准备仅绑定已核对字节',packet_error(p,bytes.fromhex(prepare['bytes_hex']),
          dict(trusted_preparation=True,expected_packet=p)),None)
    check('准备字节不可换',packet_error(p,b'\x01\x03',dict(trusted_preparation=True,expected_packet=p)),'bytes')
    bad=copy.deepcopy(p);bad['primitive_id']='other';seal(bad,'packet_digest')
    check('重算包摘要不改变原primitive',packet_error(bad,b'\x01\x02',dict(trusted_preparation=True,expected_packet=p)),'binding')
    encode,prepared=copy.deepcopy([frames['ENCODE_PACKET'],frames['PREPARE_PACKET']])
    prepared['reply_to']=encode['message_id']
    ec=dict(trusted_preparation=True,current={k:encode[k] for k in O.KEYS},now=0,
            expected_request=copy.deepcopy(encode['body']),expected_packet=copy.deepcopy(p))
    check('只编码往返关联',encoding_error(encode,prepared,ec),None)
    bad=copy.deepcopy(prepared);bad['reply_to']='other'
    check('不能借另编码请求',encoding_error(encode,bad,ec),'reply')
    bad=copy.deepcopy(prepared);bad['body']['packet']['primitive_id']='other'
    seal(bad['body']['packet'],'packet_digest')
    check('编码结果不换批准计划',encoding_error(encode,bad,ec),'plan_binding')
    check('准备截止等号失效',encoding_error(encode,prepared,{**ec,'now':int(encode['body']['expires_tick_ns'])}),'expired')
    failed=copy.deepcopy(frames['PACKET_ENCODING_FAILED']);failed['reply_to']=encode['message_id']
    check('编码失败无设备发送含义',encoding_error(encode,failed,ec),'encoding_failed')
    b=frames['DISPATCH']['body'];t=b['permit']['transmission'];w=t['send_window']
    c=dict(root_intent=t['intent'],packet=b['packet'],guard_current=True,resource_clear=True,budget_available=True,
           packet_acknowledged=False,pending_permit=False,next_ordinal=0,next_issued=1,
           now=int(w['earliest_tick_ns']),original_deadline=int(w['latest_tick_ns']),
           resend_request=frames['RESEND_REQUEST']['body'],request=copy.deepcopy(b['request']),prepare_id=b['prepare_id'],
           current_permit={k:copy.deepcopy(v) for k,v in b['permit'].items()
                           if k not in ('permit_id','transmission','budget_revision')})
    check('初次派发关联',send_error(b,c),None)
    rb=frames['RESEND_DISPATCH']['body'];rc={**c,'next_ordinal':1,'next_issued':2}
    check('重传独立许可关联',send_error(rb,rc),None)
    bad=copy.deepcopy(rb);bad['request']['parameters']['extra']='changed'
    check('不能换原业务参数',send_error(bad,rc),'accepted_request')
    bad=copy.deepcopy(rb);bad['permit']['gate_revision']='999'
    check('重传当前闸修订必须匹配',send_error(bad,rc),'current_permit')
    renewed=copy.deepcopy(rb);renewed_context=copy.deepcopy(rc)
    for k,v in [('guard_id','renewed-guard'),('guard_digest',digest('renewed-guard'))]:
        renewed[k]=v;renewed['permit'][k]=v;renewed['permit']['transmission']['intent'][k]=v
        renewed_context['current_permit'][k]=v
    check('同原packet可绑定已批准新守卫',send_error(renewed,renewed_context),None)
    for field in ('guard_current','resource_clear','budget_available'):
        check('重传仍受门控'+field,send_error(rb,{**rc,field:False}),'gate')
    for field in ('packet_acknowledged','pending_permit'):
        check('重传被抑制'+field,send_error(rb,{**rc,field:True}),'resend_blocked')
    check('截止等号不可发',send_error(rb,{**rc,'now':rc['original_deadline']}),'deadline')
    bad=copy.deepcopy(rb);bad['permit']['transmission']['intent']['permit_id']=c['root_intent']['permit_id']
    bad['permit']['permit_id']=c['root_intent']['permit_id']
    check('不可再次消费原许可',send_error(bad,rc),'permit_reuse')
    for field,value,expected in [('primitive_id','other','primitive'),('ordinal','3','sequence'),
                                 ('parent_dispatch_intent_id','other','parent')]:
        bad=copy.deepcopy(rb);bad['permit']['transmission'][field]=value
        check('传输绑定-'+field,send_error(bad,rc),expected)
    f,a=copy.deepcopy([frames['RUN_FENCE'],frames['RUN_FENCE_ACK']])
    a['reply_to']=f['message_id']
    ctx=dict(current={k:f[k] for k in O.KEYS},peer_authenticated=True,
             attempt_binding=copy.deepcopy(f['body']['attempt_binding']),business=copy.deepcopy(f['body']['open_intents']),
             transmissions=copy.deepcopy(f['body']['open_transmission_intents']),cut_revision=f['body']['issued_cut_revision'],
             known_entered=[f['body']['open_intents'][0]['permit_id']],
             known_business_entered=[f['body']['open_intents'][0]['permit_id']],request_tick=90,received_tick=110)
    check('完整双清单屏障',fence_error(f,a,ctx),None)
    for name in ('FENCE','AUTH_FENCE','TIME_FENCE'):
        ff,aa=copy.deepcopy([frames[name],frames[name+'_ACK']]);aa['reply_to']=ff['message_id']
        cc=dict(current={k:ff[k] for k in O.KEYS},peer_authenticated=True,
                attempt_binding=copy.deepcopy(ff['body']['attempt_binding']),
                business=copy.deepcopy(ff['body']['open_intents']),
                transmissions=copy.deepcopy(ff['body']['open_transmission_intents']),
                cut_revision=ff['body']['issued_cut_revision'],known_entered=[],known_business_entered=[],
                request_tick=90,received_tick=110)
        check(name+'双清单关联',fence_error(ff,aa,cc),None)
        bad=copy.deepcopy(aa);bad['body']['issued_cut_revision']='999'
        check(name+'ACK不能换切点',fence_error(ff,bad,cc),'cut_revision')
        query=copy.deepcopy(frames['QUERY_BARRIER'])
        query.update({k:ff[k] for k in O.KEYS})
        query['body']={k:copy.deepcopy(ff['body'][k]) for k in ('operation_id','barrier_id','attempt_binding')}
        reply=copy.deepcopy(aa);reply['reply_to']=query['message_id']
        check(name+'查原ACK关联',query_error(query,reply,aa,cc),None)
    bad=copy.deepcopy(a);bad['body']['effective_tick_ns']='80'
    check('不能编造旧生效tick',fence_error(f,bad,ctx),'effective_time')
    bad=copy.deepcopy(a);bad['worker_boot_id']='new-worker'
    check('新worker不代旧出口ACK',fence_error(f,bad,ctx),'exit')
    bad=copy.deepcopy(a);bad['body']['attempt_binding']['attempt_ordinal']='2'
    check('ACK不能借另次尝试',fence_error(f,bad,ctx),'attempt')
    bad=copy.deepcopy(a);bad['body']['transmission_coverage']=[]
    check('不能只覆盖业务清单',fence_error(f,bad,ctx),'coverage')
    bad=copy.deepcopy(a);bad['body']['transmission_coverage'][0].update(disposition='not_sent',proof='never_received')
    check('已知发送不可降级',fence_error(f,bad,ctx),'downgrade')
    ff=copy.deepcopy(f);ff['body']['open_transmission_intents']=[]
    ff['body']['transmission_ledger_digest']=digest([])
    ff['body']['attempt_binding']['cut_digest']=cut_digest(ff)
    cc=copy.deepcopy(ctx);cc['attempt_binding']=copy.deepcopy(ff['body']['attempt_binding'])
    aa=copy.deepcopy(a);aa['body']['attempt_binding']=copy.deepcopy(ff['body']['attempt_binding'])
    check('重算摘要不能漏原全集',fence_error(ff,aa,cc),'complete_cut')
    # 两次传输共一个业务锚：最后未发不覆盖原已发。
    ff,aa=copy.deepcopy([f,a]);root=ff['body']['open_intents'][0]
    second=transmission(root,ff['body']['open_transmission_intents'][0]['send_window'],'1','zz-resend')
    ff['body']['open_transmission_intents'].append(second)
    ff['body']['transmission_ledger_digest']=digest(ff['body']['open_transmission_intents'])
    ff['body']['attempt_binding']['cut_digest']=cut_digest(ff)
    aa['body'].update(attempt_binding=copy.deepcopy(ff['body']['attempt_binding']),
        transmission_ledger_digest=ff['body']['transmission_ledger_digest'])
    aa['body']['transmission_coverage'].append(dict(intent=copy.deepcopy(second),disposition='not_sent',proof='discarded_unconsumed'))
    cc={**ctx,'attempt_binding':ff['body']['attempt_binding'],'transmissions':ff['body']['open_transmission_intents']}
    check('原已发加重传未发可同时覆盖',valid(ff) and valid(aa) and fence_error(ff,aa,cc) is None)
    bad=copy.deepcopy(aa);bad['body']['coverage'][0].update(disposition='not_sent',proof='never_received')
    check('业务汇总不可取最后一次',fence_error(ff,bad,cc),'business_summary')
    badf,bada=copy.deepcopy([ff,aa])
    badf['body']['open_transmission_intents'][1]['transmission_id']=badf['body']['open_transmission_intents'][0]['transmission_id']
    badf['body']['transmission_ledger_digest']=digest(badf['body']['open_transmission_intents'])
    badf['body']['attempt_binding']['cut_digest']=cut_digest(badf)
    bada['body'].update(attempt_binding=copy.deepcopy(badf['body']['attempt_binding']),
                        transmission_ledger_digest=badf['body']['transmission_ledger_digest'])
    badc={**cc,'attempt_binding':badf['body']['attempt_binding'],'transmissions':badf['body']['open_transmission_intents']}
    check('不同permit不能复用传输ID',fence_error(badf,bada,badc),'transmission_identity')
    unavailable=frames['BARRIER_UNAVAILABLE']
    check('缓存失效响应无覆盖或时间',valid(unavailable) and 'coverage' not in unavailable['body']
          and 'effective_tick_ns' not in unavailable['body'])
    bad=copy.deepcopy(unavailable);bad['body']['effective_tick_ns']='100'
    check('缓存丢失不得补造生效时间',valid(bad),False)
    query=copy.deepcopy(frames['QUERY_BARRIER'])
    query.update({k:f[k] for k in O.KEYS});query['message_id']='query-current'
    query['body']={k:copy.deepcopy(f['body'][k]) for k in ('operation_id','barrier_id','attempt_binding')}
    queried=copy.deepcopy(a);queried['reply_to']=query['message_id']
    check('查询复用固定ACK正文',query_error(query,queried,a,ctx),None)
    bad=copy.deepcopy(queried);bad['body']['effective_tick_ns']='101'
    check('查询不重新采样生效时间',query_error(query,bad,a,ctx),'frozen_ack')
    missing=copy.deepcopy(frames['BARRIER_UNAVAILABLE'])
    missing.update({k:f[k] for k in O.KEYS});missing['reply_to']=query['message_id']
    check('查不到只是不确定',query_error(query,missing,a,ctx),'unavailable_without_effect')
    bad=copy.deepcopy(missing);bad['body']['barrier_id']='other'
    check('未知回复也核对原屏障',query_error(query,bad,a,ctx),'query_binding')
    retired=copy.deepcopy(query);retired['worker_boot_id']='replacement'
    check('新出口不能查询旧缓存冒认结果',query_error(retired,queried,a,ctx),'exit')
    stored=copy.deepcopy(frames['BARRIER_STORED']);stored.update({k:f[k] for k in O.KEYS})
    stored['body']['ack_digest']=digest(a['body'])
    stored_context={**ctx,'ack_durable':True,'stored_revision':'1'}
    check('存储确认绑定原ACK',stored_error(stored,a,stored_context),None)
    check('未持久不得释放ACK缓存',stored_error(stored,a,{**stored_context,'ack_durable':False}),'not_durable')
    bad=copy.deepcopy(stored);bad['body']['ack_digest']=digest('other')
    check('确认不可释放另一ACK缓存',stored_error(bad,a,stored_context),'stored_reference')
    ackobs=dict(observation_id='obs-a',writer_exit_id='exit-a',device_session_id=p['device_session_id'],
        socket_instance_id=p['socket_instance_id'],protocol_session=p['protocol_session'],receive_io_seq='2',
        raw_ack_ref=dict(object_id='raw-a',digest=digest('raw')),wire_ack_id='1',covered_packet_refs=[packet_ref(p)])
    check('累计ACK只含packet身份',valid(ackobs,'PacketAckObservation'))
    bad=copy.deepcopy(ackobs);bad['ordinal']='1'
    check('累计ACK不冒认具体重传',valid(bad,'PacketAckObservation'),False)
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true')
    parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true')
    args=parser.parse_args()
    if args.staged and not args.check_report:parser.error('--staged需与--check-report共用')
    if args.check_report:
        read=(lambda p:subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        data=json.loads(read(HERE/'execution-ipc-report.json'))
        assert set(data['inputs'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS:assert data['inputs'][p.relative_to(ROOT).as_posix()]==hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run()
        data=dict(all_passed=True,cases_passed=len(checks),approved=False,runtime_tests_executed=0,
                  device_tests_executed=0,checks=checks,
                  inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if args.report:(HERE/'execution-ipc-report.json').write_bytes(encoded(data))
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
