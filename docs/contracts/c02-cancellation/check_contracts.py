"""取消保护46帧候选参考检查；合成权威和有限模型不证明运行。"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
from build_contracts import HERE,BASE,CID,IID,VERSION,FEATURES,FENCES,NEW_FRAMES,RESPONSES,build,encoded
import reference_model as M

sys.path.insert(0,str(BASE/'c08-controller'))
spec=importlib.util.spec_from_file_location('execution_check',BASE/'c08-controller/check_execution_ipc.py')
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
ROOT=HERE.parents[2]
RESOURCE_PATHS=[BASE/n for n in ('draft4/first-loop.schema.json','c05-protection/protection.schema.json',
    'c05-protection/protocol.schema.json','c09-panel-ipc/binding.schema.json',
    'c08-controller/execution-ipc.schema.json','c08-controller/lifecycle.schema.json',
    'c02-command-view/command.schema.json','c02-admission/admission.schema.json')]+[
    HERE/'cancellation.schema.json',HERE/'ipc.schema.json']
INPUTS=list(dict.fromkeys(E.INPUTS+RESOURCE_PATHS+[BASE/'c02-command-view/README.md',
    BASE/'c02-command-view/STORAGE.md']+[HERE/n for n in
    ('README.md','build_contracts.py','reference_model.py','check_contracts.py','cancellation.schema.json','ipc.schema.json')]))


def R(name):return dict(id=name,revision='1',digest=M.digest(name))
def clone(v):return copy.deepcopy(v)
def fixtures():
    frames=E.fixtures()
    original=frames['DISPATCH']['body']['permit']['transmission']
    i=original['intent'];scope=dict(authority_service_id='controller',database_instance_id='database')
    exit=dict(writer_exit_id='exit-a',socket_instance_id='socket-a',**{k:i[k] for k in
        ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','device_session_id','clock_domain_id','descriptor_digest')})
    binding=dict(scope=scope,cancellation_id='cancel-a',parent_command_id=i['command_id'],
        initial_operation_ref=R('cancel-a'),identity=dict(key=dict(target_scope=scope,issuer_id='issuer',
            issuer_epoch='issuer-1',principal_id='person',request_epoch='request-1',
            operation_id='cancelCommand',idempotency_key='cancel-key'),request_digest=M.digest('cancel-content')),
        mode='cooperative',policy_ref=R('policy'))
    policy=M.seal(dict(policy_id='policy',revision='1',mode='cooperative',procedure_ref=R('procedure'),
        completion_policy_ref=R('completion'),release_policy_ref=R('release'),resource_keys=['device-resource'],
        max_transmissions=4,allow_protocol_resend=True,application_attempts=1),'policy_digest')
    binding['policy_ref']=M.ref(policy,'policy_id','policy_digest')
    requester=dict(actor_ref=R('person'),authorization_ref=R('authorization'),origin='manual',
        admission_origin='non_panel',panel_binding_ref=None,automation_binding_ref=None)
    target=M.seal(dict(exit=clone(exit),ordinary_attempt_ids=[i['attempt_id']],
        ordinary_transmissions=[clone(original)],cancel_prepare_ids=[],cancel_transmissions=[]),'target_digest')
    cut=M.seal(dict(cut_id='cut-ordinary',binding=clone(binding),stage='ordinary',previous_cut_ref=None,
        issued_revision='1',deny_revision='1',targets=[clone(target)]),'cut_digest')
    cutref=M.ref(cut,'cut_id','cut_digest')
    plan=M.seal(dict(execution_id='cancel-execution',binding=clone(binding),requester=clone(requester),
        device_id=exit['device_id'],ordinary_closure_ref=R('ordinary-closure'),policy_ref=binding['policy_ref'],
        protected_hold_ref=R('protected-hold'),resource_keys=['device-resource'],primitives=[
            dict(primitive_id='cancel-primitive',action_ref=R('stop-action'),parameters_schema_ref=R('stop-parameters'),
                parameters={'stop':True},after=[],completion_policy_ref=R('stop-completion'))]),'execution_digest')
    er=M.ref(plan,'execution_id','execution_digest')
    window=clone(frames['DISPATCH']['body']['send_window']);window.update(earliest_tick_ns='10',latest_tick_ns='200')
    guard=M.seal(dict(guard_id='cancel-guard',execution_ref=er,requester=clone(requester),exit=clone(exit),
        control_epoch='control-current',control_version='2',gate_revision='2',authorization_revision='2',
        time_required=True,time_evidence_ref=R('time-evidence'),time_policy_ref=R('time-policy'),guard_provider_ref=R('guard-provider'),
        protected_hold_ref=plan['protected_hold_ref'],deny_revision='1',send_window=window),'guard_digest')
    sha='sha256:'+hashlib.sha256(b'\x03\x04').hexdigest()
    packet=M.seal(dict(packet_id='cancel-packet',execution_ref=er,cancellation_id='cancel-a',
        parent_command_id=i['command_id'],primitive_id='cancel-primitive',exit=clone(exit),
        protocol_session='protocol-1',wire_packet_id='2',tracking_ids=['tracking'],
        immutable_bytes_ref=dict(object_id='cancel-bytes',digest=sha),byte_length=2,sha256=sha,
        transport_profile_ref=R('transport')),'packet_digest')
    tx=dict(permit_id='cancel-permit',transmission_id='cancel-transmission',execution_ref=er,
        cancellation_id='cancel-a',parent_command_id=i['command_id'],primitive_id='cancel-primitive',
        packet_ref={k:packet[k] for k in ('packet_id','packet_digest')},exit=clone(exit),requester=clone(requester),
        guard_ref=M.ref(guard,'guard_id','guard_digest'),ordinal='0',initial_permit_id='cancel-permit',
        issued_revision='2',kind='initial',trigger_observation_ref=None,budget_receipt_ref=R('budget'),send_window=clone(window))
    deny=dict(cancellation_id='cancel-a',parent_command_id=i['command_id'],stage='ordinary',
        deny_revision='1',cut_ref=cutref)
    snapshot=M.seal(dict(scope=scope,device_id=exit['device_id'],snapshot_revision='1',entries=[deny]),'snapshot_digest')
    for n,f in frames.items():
        f['ipc_version']=VERSION
        if n=='HELLO':f['body']['supported_ipc_versions']=[VERSION];f['body']['supported_features']+=list(FEATURES)
        if n=='HELLO_ACK':f['body']['selected_ipc_version']=VERSION;f['body']['selected_features']+=list(FEATURES)
        if n=='OPEN_GATE':f['body']['command_deny_snapshot']=clone(snapshot)
        if n=='OPEN_GATE_ACK':f['body'].update(command_deny_snapshot_revision='1',command_deny_snapshot_digest=snapshot['snapshot_digest'])
    for n in FENCES:
        frames[n]['body'].update(cancel_transmissions=[],cancel_ledger_digest=M.digest([]))
        frames[n]['body']['attempt_binding']['cut_digest']=E.cut_digest(frames[n])
        frames[n+'_ACK']['body'].update(cancel_coverage=[],cancel_ledger_digest=M.digest([]))
        frames[n+'_ACK']['body']['attempt_binding']=clone(frames[n]['body']['attempt_binding'])
    def frame(n,body):
        f=clone(frames['FENCE_ACK' if n in RESPONSES else 'FENCE'])
        f.update(type=n,message_id='message-'+n,reply_to='request-'+n if n in RESPONSES else None,
                 body=body,**{k:exit[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id',
                     'device_id','clock_domain_id','descriptor_digest')})
        return f
    fence=dict(operation_id='cancel-a',barrier_id='cancel-barrier',binding=clone(binding),stage='ordinary',
        cut_ref=cutref,deny_revision='1',target=clone(target),attempt_binding=dict(cut_id=cut['cut_id'],
            cut_digest=cut['cut_digest'],target_exit_id='exit-a',attempt_ordinal='1',previous_barrier_id=None))
    ack=M.seal({k:clone(v) for k,v in fence.items() if k!='target'}|dict(target_digest=target['target_digest'],
        ordinary_attempt_ids=target['ordinary_attempt_ids'],cancel_prepare_ids=[],ordinary_coverage=[
            dict(intent=clone(original),disposition='in_flight',proof='transport_entered')],
        cancel_coverage=[],effective_tick_ns='100',gate_io_seq='3'),'ack_digest')
    bodies={
        'CANCEL_FENCE':fence,'CANCEL_FENCE_ACK':ack,
        'CANCEL_GUARD':dict(plan=plan,guard=guard),
        'CANCEL_GUARD_ACK':dict(execution_ref=er,guard_ref=tx['guard_ref'],status='installed'),
        'ENCODE_CANCEL_PACKET':dict(prepare_id='cancel-prepare',execution_ref=er,primitive_id='cancel-primitive',
            guard_ref=tx['guard_ref'],expires_tick_ns='200'),
        'PREPARE_CANCEL_PACKET':dict(prepare_id='cancel-prepare',packet=packet,bytes_hex='0304'),
        'CANCEL_ENCODING_FAILED':dict(prepare_id='cancel-prepare',execution_ref=er,reason='expired'),
        'CANCEL_PREPARE_REJECTED':dict(prepare_id='cancel-prepare',execution_ref=er,reason='protected'),
        'DISPATCH_CANCEL':dict(prepare_id='cancel-prepare',packet=packet,permit=tx,resend_request_id=None),
        'CANCEL_RESEND_REQUEST':dict(request_id='cancel-resend',execution_ref=er,packet_ref=tx['packet_ref'],
            cause='timeout',observation_ref=R('resend-observation')),
        'CANCEL_RESEND_REJECTED':dict(request_id='cancel-resend',execution_ref=er,reason='protected'),
        'CANCEL_SEND_REPORT':dict(report_id='cancel-report',transmission=tx,disposition='in_flight',
            gate_io_seq='2',transport_entered_tick_ns='50',observation_ref=R('send-observation')),
        'CANCEL_REPORT_STORED':dict(report_id='cancel-report',report_digest=M.digest('report'),record_ref=R('stored-report')),
        'CANCEL_EVIDENCE_CANDIDATE':dict(report_id='cancel-evidence',execution_ref=er,primitive_id='cancel-primitive',
            packet_refs=[tx['packet_ref']],evidence_schema_ref=R('stop-evidence'),payload={'stopped':True}),
        'QUERY_CANCEL_EXECUTION':dict(execution_ref=er),
        'CANCEL_EXECUTION_STATUS':dict(execution_ref=er,status='known',stored_report_refs=[R('stored-report')])}
    for n in NEW_FRAMES:frames[n]=frame(n,clone(bodies[n]))
    for n,request in [('CANCEL_FENCE_ACK','CANCEL_FENCE'),('CANCEL_GUARD_ACK','CANCEL_GUARD'),
        ('PREPARE_CANCEL_PACKET','ENCODE_CANCEL_PACKET'),('CANCEL_EXECUTION_STATUS','QUERY_CANCEL_EXECUTION')]:
        frames[n]['reply_to']=frames[request]['message_id']
    return frames,dict(exit=exit,binding=binding,policy=policy,plan=plan,guard=guard,packet=packet,tx=tx,
        cut=cut,target=target,snapshot=snapshot,requester=requester)


def run():
    checks=[]
    def check(name,got,want=None):
        assert got==want,(name,got,want)
        checks.append(dict(name=name,expected=want,observed=got))
    schemas=build()
    for n,s in schemas.items():check(n+'生成字节',(HERE/n).read_bytes()==encoded(s),True)
    resources={}
    # 只读取实际引用的本地资源；沿引用闭包装配，无网络retriever。
    candidates={json.loads(p.read_bytes())['$id']:p for p in RESOURCE_PATHS}
    for uri,p in candidates.items():resources[uri]=json.loads(p.read_bytes())
    registry=Registry().with_resources((u,Resource.from_contents(s)) for u,s in resources.items())
    for s in schemas.values():Draft202012Validator.check_schema(s)
    validator=Draft202012Validator(schemas['ipc.schema.json'],registry=registry)
    def valid(f):return validator.is_valid(f)
    frames,x=fixtures();check('完整46帧',len(frames),46)
    for n,f in frames.items():
        errors=list(validator.iter_errors(f))
        check(n+'结构',[e.message for e in errors],[])
        bad=clone(f);bad['ipc_version']='ipc/0.6.0-transmission-draft.1';check(n+'拒绝降级',valid(bad),False)
    for n in NEW_FRAMES:
        f=clone(frames[n]);f['body']['unexpected']=True;check(n+'封闭正文',valid(f),False)
        f=clone(frames[n]);f['reply_to']=None if n in RESPONSES else 'unsolicited';check(n+'响应关联形状',valid(f),False)
    for n,field in [('HELLO','supported_features'),('HELLO_ACK','selected_features')]:
        for feat in FEATURES:
            f=clone(frames[n]);f['body'][field].remove(feat);check(n+'必选'+feat,valid(f),False)
    def model_valid(n,v):
        return Draft202012Validator({'$ref':CID+'#/$defs/'+n},registry=registry).is_valid(v)
    for n,key in [('Policy','policy'),('ExecutionPlan','plan'),('Guard','guard'),('Packet','packet'),
        ('Transmission','tx'),('Cut','cut'),('DenySnapshot','snapshot')]:check(n+'结构',model_valid(n,x[key]),True)
    for v in ('01','-1','1\n','1.0','100000000000000000000'):
        f=clone(frames['DISPATCH_CANCEL']);f['body']['permit']['issued_revision']=v;check('计数拒绝'+repr(v),valid(f),False)
    c=dict(scope=x['snapshot']['scope'],device_id=x['exit']['device_id'],expected_entries=clone(x['snapshot']['entries']),
        authority_revision=1,installed_revision=0,installed_entries=[])
    check('完整deny快照',M.snapshot_error(x['snapshot'],c))
    for label,field,value,expected in [('错库','scope',{'authority_service_id':'other','database_instance_id':'database'},'owner'),
        ('漏项','entries',[],'incomplete'),('重复','entries',x['snapshot']['entries']*2,'order'),
        ('旧修订','snapshot_revision','0','incomplete')]:
        s=clone(x['snapshot']);s[field]=value;M.seal(s,'snapshot_digest');check(label,M.snapshot_error(s,c),expected)
    old=clone(x['snapshot']['entries']);old[0]['stage']='all'
    check('不得降all为ordinary',M.snapshot_error(x['snapshot'],{**c,'installed_entries':old}),'regression')
    check('较旧快照不开闸',M.snapshot_error(x['snapshot'],{**c,'installed_revision':2}),'stale')
    cc=dict(binding=x['binding'],issued_revision=1,deny_revision=1,expected_targets=[clone(x['target'])],
        device_id=x['exit']['device_id'],previous_cut=None)
    check('完整普通cut',M.cut_error(x['cut'],cc))
    for label,field,value,expected in [('漏出口','targets',[],'incomplete'),('错水位','issued_revision','2','cut'),
        ('重复出口','targets',x['cut']['targets']*2,'order')]:
        q=clone(x['cut']);q[field]=value;M.seal(q,'cut_digest');check(label,M.cut_error(q,cc),expected)
    f,a=clone([frames['CANCEL_FENCE'],frames['CANCEL_FENCE_ACK']])
    ac=dict(request_tick=90,received_tick=110,last_send_io_seq=2,request_body=clone(f['body']),
        known_dispositions={x['target']['ordinary_transmissions'][0]['intent']['permit_id']:'in_flight'},proven_unconsumed=[])
    check('精确取消ACK',M.ack_error(f,a,ac))
    for label,field,value,expected in [('遗漏准备','ordinary_attempt_ids',[],'preparation'),
        ('遗漏许可','ordinary_coverage',[],'coverage'),('过早生效','effective_tick_ns','89','time'),
        ('过晚生效','effective_tick_ns','111','time'),('未串行关闭','gate_io_seq','2','gate_order'),
        ('错target','target_digest',M.digest('wrong'),'target')]:
        z=clone(a);z['body'][field]=value;M.seal(z['body'],'ack_digest');check(label,M.ack_error(f,z,ac),expected)
    z=clone(a);z['worker_boot_id']='other';check('新worker不能回复旧出口',M.ack_error(f,z,ac),'exit')
    z=clone(a);z['body']['ordinary_coverage'][0].update(disposition='not_sent',proof='never_received');M.seal(z['body'],'ack_digest')
    check('不能降已发送为未发',M.ack_error(f,z,ac),'downgrade')
    check('无已知发送仍须未消费证明',M.ack_error(f,z,{**ac,'known_dispositions':{}}),'no_unconsumed_proof')
    # all切点追加保护传输，保持原普通历史，不重算取消受理切点。
    alltarget=clone(x['target']);alltarget.update(cancel_prepare_ids=['cancel-prepare'],cancel_transmissions=[clone(x['tx'])])
    M.seal(alltarget,'target_digest')
    allcut=M.seal({**clone(x['cut']),'cut_id':'cut-all','stage':'all','previous_cut_ref':M.ref(x['cut'],'cut_id','cut_digest'),
        'issued_revision':'2','deny_revision':'2','targets':[alltarget]},'cut_digest')
    allcontext={**cc,'issued_revision':2,'deny_revision':2,'expected_targets':[alltarget],'previous_cut':x['cut']}
    check('完整all切点',M.cut_error(allcut,allcontext))
    af=clone(f);af['body'].update(stage='all',cut_ref=M.ref(allcut,'cut_id','cut_digest'),
        deny_revision='2',target=alltarget,attempt_binding=dict(cut_id=allcut['cut_id'],
            cut_digest=allcut['cut_digest'],target_exit_id='exit-a',attempt_ordinal='1',previous_barrier_id=None))
    aa=clone(a);aa['body'].update({k:clone(af['body'][k]) for k in ('stage','cut_ref','deny_revision','attempt_binding')})
    aa['body'].update(target_digest=alltarget['target_digest'],cancel_prepare_ids=['cancel-prepare'],
        cancel_coverage=[dict(intent=clone(x['tx']),disposition='unknown',proof='send_uncertain')])
    M.seal(aa['body'],'ack_digest');allac={**ac,'request_body':af['body']}
    check('all取消屏障结构',valid(af) and valid(aa),True)
    check('关闭允许效果未知',M.ack_error(af,aa,allac))
    z=clone(aa);z['body']['cancel_coverage']=[];M.seal(z['body'],'ack_digest')
    check('all不能漏保护许可',M.ack_error(af,z,allac),'coverage')
    z=clone(aa);z['body']['cancel_prepare_ids']=[];M.seal(z['body'],'ack_digest')
    check('all不能漏编码准备',M.ack_error(af,z,allac),'preparation')
    bad=clone(allcut);bad['previous_cut_ref']=R('other');M.seal(bad,'cut_digest');check('all不得替换原cut',M.cut_error(bad,allcontext),'predecessor')
    target_closure=dict(target_exit_id='exit-a',target_digest=alltarget['target_digest'],kind='barrier_ack',
        source_ref=R('all-ack'),validation_ref=R('ack-validation'))
    closure=M.seal(dict(closure_id='closure-all',revision='1',binding=x['binding'],stage='all',
        cut_ref=M.ref(allcut,'cut_id','cut_digest'),targets=[target_closure],
        provider_receipt_ref=R('closure-provider')),'closure_digest')
    clc=dict(target_sources={'exit-a':target_closure},provider_receipt_ref=R('closure-provider'),cancel_issuance_closed=True)
    check('关闭证据结构',model_valid('ClosureEvidence',closure),True)
    check('all完整关闭',M.closure_error(closure,allcut,clc))
    check('仍可签取消许可不能报all关闭',M.closure_error(closure,allcut,{**clc,'cancel_issuance_closed':False}),'issuance_open')
    z=clone(closure);z['targets']=[];M.seal(z,'closure_digest');check('关闭证据不能漏出口',M.closure_error(z,allcut,clc),'coverage')
    pc=dict(approved_plan=clone(x['plan']),policy=x['policy'],binding=x['binding'],
        ordinary_closure_ref=x['plan']['ordinary_closure_ref'],ordinary_closure_valid=True,
        protected_hold_ref=x['plan']['protected_hold_ref'],requester=x['requester'],device_id=x['exit']['device_id'],
        existing_execution_id=None,parameters_valid={'cancel-primitive':True})
    check('保护计划',M.plan_error(x['plan'],pc))
    check('不能再建第二执行',M.plan_error(x['plan'],{**pc,'existing_execution_id':'other'}),'one_execution')
    check('普通出口未关闭不能执行取消',M.plan_error(x['plan'],{**pc,'ordinary_closure_valid':False}),'ordinary_open')
    check('动态参数未验证拒绝',M.plan_error(x['plan'],{**pc,'parameters_valid':{}}),'parameters')
    z=clone(x['plan']);z['primitives'][0]['after']=['cancel-primitive'];M.seal(z,'execution_digest')
    check('取消计划禁止自环',M.plan_error(z,{**pc,'approved_plan':z}),'graph')
    z=clone(x['plan']);z['primitives']*=2;M.seal(z,'execution_digest')
    check('取消计划不能重复primitive',M.plan_error(z,{**pc,'approved_plan':z}),'graph')
    sc=dict(plan=x['plan'],policy=x['policy'],guard=x['guard'],current_guard=clone(x['guard']),
        durable_intent=True,gate_open=True,authorization_current=True,time_qualified=True,
        runtime_clock_valid=True,approved_time_required=True,ordinary_closure_valid=True,
        deny_stage='ordinary',issuance_closed=False,execution_status='active',live_exit=x['exit'],hold_valid=True,
        deny_revision=1,prepared_packet=clone(x['packet']),prepare_id='cancel-prepare',bytes=b'\x03\x04',
        completed_primitives=[],now=50,transmissions_issued=0,budget_receipt_ref=R('budget'),next_issued_revision=2,
        next_ordinal=0,pending_permit=None,initial_sent_primitives=[],initial_disposition=None,
        initial_permit_id=None,resend_observation_ref=None,resend_request_id=None,packet_acknowledged=False)
    body=clone(frames['DISPATCH_CANCEL']['body']);sc['committed_dispatch']=clone(body)
    check('独立许可允许一次发送',M.send_error(body,sc))
    z=clone(body);z['permit']['permit_id']='invented'
    check('持久标志不能授权伪造许可',M.send_error(z,sc),'intent')
    for field,value,error in [('durable_intent',False,'gate'),('gate_open',False,'gate'),
        ('authorization_current',False,'authorization'),('time_qualified',False,'time'),
        ('ordinary_closure_valid',False,'ordinary_open'),('deny_stage','all','protected'),
        ('issuance_closed',True,'protected'),('execution_status','indeterminate','execution'),
        ('hold_valid',False,'resources'),('now',200,'expired'),('now',9,'expired'),
        ('transmissions_issued',4,'budget'),('next_issued_revision',3,'ordinal'),
        ('pending_permit','other','pending'),('initial_sent_primitives',['cancel-primitive'],'replay'),
        ('bytes',b'\x04\x03','bytes')]:
        check('发送拒绝'+field,M.send_error(body,{**sc,field:value}),error)
    current=clone(x['guard']);current['control_version']='3';M.seal(current,'guard_digest')
    check('接管优先于旧取消许可',M.send_error(body,{**sc,'current_guard':current}),'guard')
    check('期限起点可发送',M.send_error(body,{**sc,'now':10}))
    immediate=clone(x['guard']);immediate.update(time_required=False,time_evidence_ref=None,time_policy_ref=None)
    M.seal(immediate,'guard_digest')
    ib=clone(body);ib['permit']['guard_ref']=M.ref(immediate,'guard_id','guard_digest')
    ic={**sc,'guard':immediate,'current_guard':clone(immediate),'committed_dispatch':clone(ib),
        'approved_time_required':False,'time_qualified':False}
    check('即时保护无UTC资格仍有合法结构',model_valid('Guard',immediate),True)
    check('即时保护不因NTP不可用拒绝',M.send_error(ib,ic))
    check('即时保护仍要求有效单调运行域',M.send_error(ib,{**ic,'runtime_clock_valid':False}),'runtime_clock')
    check('即时保护仍受期限约束',M.send_error(ib,{**ic,'now':200}),'expired')
    check('不能自行关闭批准时间要求',M.send_error(ib,{**ic,'approved_time_required':True}),'time_policy')
    z=clone(immediate);z['time_evidence_ref']=R('old-time')
    check('即时guard不能夹带旧UTC证据',model_valid('Guard',z),False)
    z=clone(x['guard']);z['time_policy_ref']=None
    check('要求UTC时不能缺批准政策',model_valid('Guard',z),False)
    ledger={};check('先消费再I/O',M.consume(body,sc,ledger),'consume_before_io')
    check('消费后崩溃保持未知',ledger['cancel-permit']['disposition'],'unknown')
    check('原消息重投只读原消费',M.consume(body,sc,ledger),'cached')
    z=clone(body);z['permit']['ordinal']='1';check('同许可异内容拒绝',M.consume(z,sc,ledger),'identity_conflict')
    check('账本只有一次消费',len(ledger),1)
    rb=clone(body);rb['permit'].update(permit_id='cancel-resend-permit',transmission_id='cancel-resend-transmission',
        ordinal='1',issued_revision='3',kind='protocol_resend',trigger_observation_ref=R('resend-observation'))
    rb['resend_request_id']='cancel-resend'
    rc={**sc,'committed_dispatch':clone(rb),'next_ordinal':1,'next_issued_revision':3,'initial_disposition':'in_flight','initial_permit_id':'cancel-permit',
        'resend_observation_ref':R('resend-observation'),'resend_request_id':'cancel-resend'}
    check('协议重传结构',model_valid('DISPATCH_CANCELBody',rb),True)
    check('同包新许可协议重传',M.send_error(rb,rc))
    check('消费未知不能协议重传',M.send_error(rb,{**rc,'initial_disposition':'unknown'}),'resend')
    check('收到ACK不能继续重传',M.send_error(rb,{**rc,'packet_acknowledged':True}),'resend')
    check('保护关闭不能重传',M.send_error(rb,{**rc,'deny_stage':'all'}),'protected')
    en,pr=frames['ENCODE_CANCEL_PACKET'],frames['PREPARE_CANCEL_PACKET']
    ec=dict(request_body=en['body'],pure_encoding_verified=True,exit=x['exit'],now=50,approved_packet=x['packet'])
    check('只编码关联',M.encoding_error(en,pr,ec))
    z=clone(pr);z['body']['bytes_hex']='0403';check('编码字节错配',M.encoding_error(en,z,ec),'bytes')
    check('编码到期不临时重做',M.encoding_error(en,pr,{**ec,'now':200}),'expired_or_exit')
    check('未证明纯编码不放行',M.encoding_error(en,pr,{**ec,'pure_encoding_verified':False}),'encoder')
    for n in FENCES:
        ff,aa=clone([frames[n],frames[n+'_ACK']]);tx=clone(x['tx'])
        if n=='RUN_FENCE':tx['requester'].update(origin='automation',automation_binding_ref=R('cancel-run'))
        ff['body'].update(cancel_transmissions=[tx],cancel_ledger_digest=M.digest([tx]))
        ff['body']['attempt_binding']['cut_digest']=E.cut_digest(ff)
        aa['body'].update(cancel_coverage=[dict(intent=tx,disposition='in_flight',proof='transport_entered')],
            cancel_ledger_digest=M.digest([tx]),attempt_binding=clone(ff['body']['attempt_binding']))
        gc=dict(expected_cancel_transmissions=[tx],exit=x['exit'],selector_matches=['cancel-permit'],proven_unconsumed=[],
            known_dispositions={'cancel-permit':'in_flight'})
        check(n+'新增完整取消覆盖结构',valid(ff) and valid(aa),True)
        check(n+'取消传输覆盖',M.general_fence_error(ff,aa,gc))
        z=clone(aa);z['body']['cancel_coverage']=[];check(n+'拒漏取消许可',M.general_fence_error(ff,z,gc),'coverage')
        check(n+'不得假匹配selector',M.general_fence_error(ff,aa,{**gc,'selector_matches':[]}),'selector')
    query,response=frames['QUERY_CANCEL_EXECUTION'],frames['CANCEL_EXECUTION_STATUS']
    qc=dict(exit=x['exit'],stored_report_refs=[R('stored-report')])
    check('查询原记录',M.query_error(query,response,qc))
    z=clone(response);z['body'].update(status='cache_missing',stored_report_refs=[])
    check('缓存丢失只有未知无重发许可',M.query_error(query,z,qc))
    z['worker_boot_id']='new-worker';check('新进程不回答旧执行',M.query_error(query,z,qc),'exit')
    report=frames['CANCEL_SEND_REPORT'];stored=clone(frames['CANCEL_REPORT_STORED'])
    stored['body']['report_digest']=M.digest(report['body'])
    stc=dict(exit=x['exit'],record_ref=R('stored-report'),committed=True)
    check('原报告提交后确认',M.stored_error(stored,report,stc))
    check('未提交不得释放报告缓存',M.stored_error(stored,report,{**stc,'committed':False}),'not_stored')
    z=clone(stored);z['body']['report_digest']=M.digest('other')
    check('报告确认不能换原正文',M.stored_error(z,report,stc),'binding')
    decision=M.seal(dict(decision_id='cancel-decision',revision='1',binding=x['binding'],
        command_state_ref=R('parent-state'),all_closure_ref=M.ref(closure,'closure_id','closure_digest'),
        execution_ref=M.ref(x['plan'],'execution_id','execution_digest'),outcome='confirmed',
        evidence_refs=[R('stop-observation')],provider_receipt_ref=R('decision-provider')),'decision_digest')
    dc=dict(binding=x['binding'],command_state_ref=R('parent-state'),provider_receipt_ref=R('decision-provider'),
        evidence_refs=[R('stop-observation')],execution_ref=decision['execution_ref'],all_closure_valid=True,
        all_closure_ref=decision['all_closure_ref'],all_ordinary_proven_not_sent=False,
        cancellation_effect_verified=True,parent_outcome='unknown')
    check('取消裁决结构',model_valid('DecisionEvidence',decision),True)
    check('取消效果确认',M.decision_error(decision,dc))
    check('只有关闭无效果不确认',M.decision_error(decision,{**dc,'cancellation_effect_verified':False}),'effect')
    check('只有ordinary关闭不确认',M.decision_error(decision,{**dc,'all_closure_valid':False}),'closure')
    z=clone(decision);z['outcome']='too_late';M.seal(z,'decision_digest')
    check('父unknown不能判too_late',M.decision_error(z,dc),'not_definite')
    check('父确定完成可判too_late',M.decision_error(z,{**dc,'parent_outcome':'succeeded'}))
    b=clone(x['binding']);b['mode']='before_dispatch_only'
    z=clone(decision);z.update(binding=b,execution_ref=None);M.seal(z,'decision_digest')
    bc={**dc,'binding':b,'execution_ref':None,'all_ordinary_proven_not_sent':True}
    check('发送前取消完整未发可确认',M.decision_error(z,bc))
    check('发送前取消最后未发不足',M.decision_error(z,{**bc,'all_ordinary_proven_not_sent':False}),'not_sent_unproven')
    z['outcome']='unsupported';M.seal(z,'decision_digest')
    check('仅发送前模式可判不支持已发取消',M.decision_error(z,bc))
    # 退休关闭仅证明后续无写；不将未知消费改成未发送。
    retired=clone(target_closure);retired.update(kind='supervisor_retired',source_ref=R('retirement'))
    z=clone(closure);z['targets']=[retired];M.seal(z,'closure_digest')
    check('旧出口退休可封闭后续写',M.closure_error(z,allcut,{**clc,'target_sources':{'exit-a':retired}}))
    # 保留限制反证：合法扩展payload不会被静态格式自动脱敏或取得设备权威。
    z=clone(frames['CANCEL_EVIDENCE_CANDIDATE']);z['body']['payload']={'unverified_text':'synthetic-only'}
    check('开放证据必须另验Schema与来源',valid(z),True)
    return checks


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true')
    p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        report=json.loads(read(HERE/'reference-report.json'))
        assert set(report['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert report['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();report=dict(all_passed=True,cases_passed=len(checks),approved=False,
            scope='46帧取消保护格式及合成关联与有限消费模型',runtime_tests_executed=0,
            sqlite_tests_executed=0,device_tests_executed=0,checks=checks,
            inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'reference-report.json').write_bytes(encoded(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')},ensure_ascii=False))
