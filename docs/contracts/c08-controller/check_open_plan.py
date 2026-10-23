"""开放计划的结构与合成原件关联检查，不执行真实发送或存储。"""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
import build_open_plan as G
import open_plan_model as M

HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=[HERE/n for n in ('build_open_plan.py','open_plan_model.py','check_open_plan.py',
    'open-plan.schema.json','OPEN_PLAN.md','GATE_ORDER.md','PROTECTION_OUTBOX.md')]+[G.IPC]


def fixture():
    ref=lambda name:dict(id=name,revision='1',digest=M.digest(name))
    scope=dict(authority_service_id='controller',database_instance_id='database')
    clock='clock_'+'1'*64;descriptor=M.digest('domain')
    run=M.seal(dict(controller_scope=scope,snapshot_revision='4',entries=[]),'snapshot_digest')
    command=M.seal(dict(scope=scope,device_id='device',snapshot_revision='3',entries=[]),'snapshot_digest')
    domain=dict(**scope,provider_id='provider',provider_boot_id='provider.boot',runtime_binding_ref=ref('runtime'),
                clock_domain_id=clock,descriptor_digest=descriptor,clock_generation='1')
    time=M.seal(dict(snapshot_id='time',domain=domain,snapshot_revision='2',minimum_time_generation='1',state_ref=ref('time.state')),'snapshot_digest')
    body=dict(barrier_id='barrier',gate_token='gate.token',device_session_id='device.session',control_epoch='control.epoch',
        control_version='2',gate_revision='3',authorization_revision='1',clock_domain_id=clock,
        lease_until_tick_ns='100',descriptor_digest=descriptor,run_deny_snapshot=run,
        command_deny_snapshot=command,reference_time_snapshot=time)
    binding=dict(scope=scope,controller_boot_id='controller.boot',worker_boot_id='worker.boot',writer_exit_id='exit',
        ipc_session_id='ipc',device_id='device',device_session_id='device.session',clock_domain_id=clock,descriptor_digest=descriptor)
    plan=M.seal(dict(plan_id='plan',revision='1',binding=binding,state_refs={n:ref(n) for n in ('control','gate','authorization','resource')},
        basis=dict(kind='resource_recovery',record_ref=ref('recovery')),body=body,selected_tick_ns='10',expires_tick_ns='90'),'plan_digest')
    frame=dict(ipc_version='ipc/0.8.0-reference-time-draft.1',type='OPEN_GATE',message_id='open.message',reply_to=None,
        **{k:binding[k] for k in M.FRAME_BINDING},seq='2',body=body)
    dispatch=M.seal(dict(dispatch_id='dispatch',revision='1',plan_ref=M.reference(plan,'plan_id','plan_digest'),frame=frame,reserved_tick_ns='20'),'dispatch_digest')
    ack_body=dict(gate_token=body['gate_token'],gate_revision=body['gate_revision'],state='open',
        run_deny_snapshot_revision=run['snapshot_revision'],run_deny_snapshot_digest=run['snapshot_digest'],
        command_deny_snapshot_revision=command['snapshot_revision'],command_deny_snapshot_digest=command['snapshot_digest'],
        reference_time_snapshot_ref=dict(id=time['snapshot_id'],revision=time['snapshot_revision'],digest=time['snapshot_digest']))
    ack=dict(ipc_version=frame['ipc_version'],type='OPEN_GATE_ACK',message_id='ack.message',reply_to=frame['message_id'],
        **{k:binding[k] for k in M.FRAME_BINDING},seq='1',body=ack_body)
    evidence=M.seal(dict(evidence_id='evidence',revision='1',plan_ref=dispatch['plan_ref'],dispatch_ref=M.reference(dispatch,'dispatch_id','dispatch_digest'),
        frame=ack,received_tick_ns='30',observer_receipt_ref=ref('observer')),'evidence_digest')
    ready=M.seal(dict(ready_id='ready',revision='1',plan_ref=dispatch['plan_ref'],dispatch_ref=evidence['dispatch_ref'],
        evidence_ref=M.reference(evidence,'evidence_id','evidence_digest'),state_refs=plan['state_refs'],committed_tick_ns='40'),'ready_digest')
    context=dict(binding=binding,state_refs=plan['state_refs'],basis=plan['basis'],stored_plan=plan,stored_dispatch=dispatch,
        stored_evidence=evidence,stored_ready=ready,storage_healthy=True,runtime_current=True,basis_valid=True,barrier_valid=True,
        resources_clear=True,authority_current=True,protected=False,control={k:body[k] for k in
        ('control_epoch','control_version','gate_revision','authorization_revision','gate_token','barrier_id')},max_lease_tick_ns='100',
        snapshots={k:body[k] for k in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot')},
        outbound_message_id=frame['message_id'],outbound_seq=frame['seq'],observer_receipt_ref=evidence['observer_receipt_ref'],
        received_ack=ack,observer_received_tick_ns=evidence['received_tick_ns'],observer_verified=True,inbound_seq=ack['seq'],inbound_message_id=ack['message_id'],
        ack_durable=True,ready_transaction_committed=True)
    # JSON往返拆开每一份权威快照和被测对象，变异不能顺带改变预期事实。
    return json.loads(json.dumps([plan,dispatch,evidence,ready,context]))


def run():
    assert (HERE/'open-plan.schema.json').read_bytes()==G.encoded(),'生成漂移'
    schema=G.build();ipc=json.loads(G.IPC.read_bytes())
    registry=Registry().with_resources([(x['$id'],Resource.from_contents(x)) for x in (schema,ipc)])
    Draft202012Validator.check_schema(schema)
    models=('OpenPlan','OpenDispatch','OpenAckEvidence','ReadyCommit')
    checks=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=copy.deepcopy(expected),observed=copy.deepcopy(actual)))
    def schema_ok(name,value):
        return Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=registry).is_valid(value)
    def evaluate(values,stage=3,now=50):
        p,d,e,r,c=values
        if not all(schema_ok(n,v) for n,v in zip(models,values)):return 'schema'
        return (lambda:M.plan_error(p,c,now),lambda:M.dispatch_error(d,p,c,now),
            lambda:M.evidence_error(e,d,p,c,now),lambda:M.ready_error(r,e,d,p,c,now))[stage]()
    def case(name,mutate,expected,stage=3,now=50):
        values=fixture();mutate(*values);check(name,evaluate(values,stage,now),expected)
    def reseal_plan(p,c):
        M.seal(p,'plan_digest');c['stored_plan']=copy.deepcopy(p)
    def reseal_dispatch(d,c):
        M.seal(d,'dispatch_digest');c['stored_dispatch']=copy.deepcopy(d)
    def reseal_evidence(e,c):
        M.seal(e,'evidence_digest');c['received_ack']=copy.deepcopy(e['frame'])
    p,d,e,r,c=fixture()
    for name,value in zip(models,(p,d,e,r)):check('结构正例:'+name,schema_ok(name,value),True)
    for stage in range(4):check('完整关联阶段'+str(stage),evaluate(fixture(),stage),None)
    check('根Schema拒绝直接对象',Draft202012Validator(schema,registry=registry).is_valid(p),False)
    check('ACK方向序号不与出站共用',e['frame']['seq']<d['frame']['seq'],True)
    for flag in ('storage_healthy','runtime_current','basis_valid','barrier_valid','resources_clear','authority_current'):
        case('当前前提失效:'+flag,lambda p,d,e,r,c,k=flag:c.update({k:False}),'unavailable')
    case('保护重新出现',lambda p,d,e,r,c:c.update(protected=True),'protected')
    for name in ('control','gate','authorization','resource'):
        case('引用修订变化:'+name,lambda p,d,e,r,c,k=name:c['state_refs'][k].update(revision='2'),'state_changed')
    case('恢复依据换代',lambda p,d,e,r,c:c['basis']['record_ref'].update(revision='2'),'state_changed')
    for name in ('writer_exit_id','ipc_session_id','worker_boot_id','device_session_id'):
        case('当前绑定变化:'+name,lambda p,d,e,r,c,k=name:c['binding'].update({k:'other'}),'binding')
    case('计划期限等号',lambda *args:None,'expired',now=90)
    case('选择前不得生效',lambda *args:None,'expired',now=9)
    case('租期超过批准上限',lambda p,d,e,r,c:c.update(max_lease_tick_ns='99'),'lease_limit')
    case('旧计划字段篡改未重算',lambda p,d,e,r,c:p['body'].update(gate_token='other'),'digest')
    def false_control(p,d,e,r,c):
        p['body']['control_version']='9';reseal_plan(p,c)
    case('重算计划不授新控制版本',false_control,'control_binding',stage=0)
    for kind in ('activation','gate_recovery'):
        def alternate_basis(p,d,e,r,c,k=kind):
            p['basis']['kind']=k;c['basis']=copy.deepcopy(p['basis']);reseal_plan(p,c)
        case('正常开放无需伪造资源事故:'+kind,alternate_basis,None,stage=0)
    def wrong_body_clock(p,d,e,r,c):
        p['body']['clock_domain_id']='clock_'+'2'*64;reseal_plan(p,c)
    case('正文时钟必须绑定信封域',wrong_body_clock,'body_binding',stage=0)
    def wrong_scope(p,d,e,r,c):
        p['body']['run_deny_snapshot']['controller_scope']['database_instance_id']='other'
        M.seal(p['body']['run_deny_snapshot'],'snapshot_digest');reseal_plan(p,c)
        c['snapshots']['run_deny_snapshot']=copy.deepcopy(p['body']['run_deny_snapshot'])
    case('重算且保存快照仍拒绝跨库scope',wrong_scope,'snapshot_scope',stage=0)
    def wrong_clock(p,d,e,r,c):
        p['body']['reference_time_snapshot']['domain']['clock_domain_id']='clock_'+'2'*64
        M.seal(p['body']['reference_time_snapshot'],'snapshot_digest');reseal_plan(p,c)
        c['snapshots']['reference_time_snapshot']=copy.deepcopy(p['body']['reference_time_snapshot'])
    case('重算时间快照仍拒绝跨时钟域',wrong_clock,'time_domain',stage=0)
    for name in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot'):
        case('当前快照不同:'+name,lambda p,d,e,r,c,k=name:c['snapshots'][k].update(snapshot_revision='99'),'snapshot_changed')
    def wrong_frame(p,d,e,r,c):
        d['frame']['body']['gate_token']='other';reseal_dispatch(d,c)
    case('重算已存派发仍须原计划正文',wrong_frame,'frame_binding',stage=1)
    def wrong_plan_ref(p,d,e,r,c):
        d['plan_ref']['revision']='9';reseal_dispatch(d,c)
    case('派发不可借同id不同修订计划',wrong_plan_ref,'plan_ref',stage=1)
    case('出站seq不匹配',lambda p,d,e,r,c:c.update(outbound_seq='9'),'outbound_identity')
    case('observer资格不可由摘要证明',lambda p,d,e,r,c:c.update(observer_verified=False),'observer')
    def wrong_dispatch_ref(p,d,e,r,c):
        e['dispatch_ref']['digest']=M.digest('other');M.seal(e,'evidence_digest')
    case('ACK证据必须绑定精确派发',wrong_dispatch_ref,'evidence_ref',stage=2)
    def forged_time(p,d,e,r,c):
        e['received_tick_ns']='31';M.seal(e,'evidence_digest')
    case('重算ACK证据不得改写接收时刻',forged_time,'observer',stage=2)
    for name in ('reply_to','ipc_session_id','worker_boot_id','descriptor_digest'):
        def mutate(p,d,e,r,c,k=name):
            e['frame'][k]=M.digest('other') if k=='descriptor_digest' else 'other';reseal_evidence(e,c)
        case('可信原件仍需ACK关联:'+name,mutate,'ack_binding',stage=2)
    for name in ('gate_token','gate_revision','run_deny_snapshot_digest','command_deny_snapshot_revision'):
        def mutate(p,d,e,r,c,k=name):
            e['frame']['body'][k]=M.digest('other') if k.endswith('digest') else '9';reseal_evidence(e,c)
        case('重算ACK仍需精确回显:'+name,mutate,'ack_gate' if name in ('gate_token','gate_revision') else 'ack_snapshot',stage=2)
    def wrong_time_ack(p,d,e,r,c):
        e['frame']['body']['reference_time_snapshot_ref']['revision']='9';reseal_evidence(e,c)
    case('时间快照ACK不可只比id',wrong_time_ack,'ack_snapshot',stage=2)
    def early_ack(p,d,e,r,c):
        e['received_tick_ns']='19';c['observer_received_tick_ns']='19';M.seal(e,'evidence_digest')
    case('ACK不早于预留发送',early_ack,'ack_time',stage=2)
    case('入站seq来自独立接收器',lambda p,d,e,r,c:c.update(inbound_seq='3'),'inbound_identity')
    case('ACK未落库不得ready',lambda p,d,e,r,c:c.update(ack_durable=False),'not_committed')
    case('ready提交未知不得ready',lambda p,d,e,r,c:c.update(ready_transaction_committed=False),'not_committed')
    case('持久ACK必须是精确原件',lambda p,d,e,r,c:c['stored_evidence'].update(evidence_id='other'),'not_committed')
    case('持久ready必须是精确原件',lambda p,d,e,r,c:c['stored_ready'].update(ready_id='other'),'not_committed')
    def wrong_ready(p,d,e,r,c):
        r['state_refs']['resource']['revision']='9';M.seal(r,'ready_digest')
    case('ready不借新资源引用',wrong_ready,'ready_state')
    def wrong_evidence_ref(p,d,e,r,c):
        r['evidence_ref']['id']='other';M.seal(r,'ready_digest')
    case('ready不能采用别的ACK证据',wrong_evidence_ref,'ready_ref')
    for value in ('01','1\n',str(10**20)):
        case('严格新计数字段:'+repr(value),lambda p,d,e,r,c,v=value:p.update(selected_tick_ns=v),'schema')
    case('未知计划字段拒绝',lambda p,d,e,r,c:p.update(extra=True),'schema')
    case('旧IPC写版本拒绝',lambda p,d,e,r,c:d['frame'].update(ipc_version='ipc/0.3.0-draft.1'),'schema')
    # 合成可信上下文全部成立时，格式与关联通过；不能据此宣称真实权威或掉电耐久。
    check('合成权威限制反证',evaluate(fixture()),None)
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    if args.staged and not args.check_report:parser.error('--staged需配合--check-report')
    path=HERE/'open-plan-report.json'
    if args.check_report:
        read=(lambda p:subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        report=json.loads(read(path));assert set(report['inputs'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS:assert report['inputs'][p.relative_to(ROOT).as_posix()]==hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),scope='开放计划原件关联候选',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            checks=checks,inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if args.report:path.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')},ensure_ascii=False))
