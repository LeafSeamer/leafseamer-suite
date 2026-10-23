"""人工权威前提下的来源保护参考检查；无服务、网络或SQLite写入。"""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
from build_contracts import HERE,INGRESS,SID,VERSION,build,encoded

ROOT=HERE.parents[2]
REPORT=HERE/'reference-report.json'
INPUTS=[HERE/n for n in ('README.md','build_contracts.py','check_contracts.py','protection.schema.json','run-fence.schema.json')]
INPUTS+=[INGRESS]+[ROOT/'docs'/n for n in ('rebirth-c05-event-sync-design.md','rebirth-c04-automation-design.md',
    'rebirth-df04-storage-design.md','rebirth-f04-f05-design.md')]
SCOPE=dict(authority_service_id='seamer',database_instance_id='db')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(v):return 'sha256:'+sha(rfc8785.dumps(v))
def seal(v,field):v[field]=digest({k:x for k,x in v.items() if k!=field});return v
def ref(kind,identity,hash_value=None):
    return dict(kind=kind,scope=copy.deepcopy(SCOPE),object_id=identity,revision='1',digest=hash_value or digest(identity))
def inc(v):
    n=int(v)+1
    if n>=10**20:raise ValueError('generation_exhausted')
    return str(n)


def failure_state(before,reason):
    """同一来源key仅增强故障；恢复需独立基线操作。"""
    order=['baseline_required','desynchronized','quarantined','closed']
    requested='closed' if reason in ('source_closed','source_changed') else 'quarantined' if reason=='content_conflict' else 'desynchronized'
    return max((before if before!='synchronized' else 'baseline_required',requested),key=order.index)


def matches(selector,origin):
    if origin is None:return False
    return selector['origin_scope']==origin['origin_scope'] and selector['run_id']==origin['run_id'] \
        and int(origin['arm_generation'])<=int(selector['deny_through_generation'])


def intent_key(i):
    return tuple(i[k] for k in ('controller_boot_id','worker_boot_id','device_session_id',
                               'ipc_session_id','permit_id','dispatch_intent_id'))


def fixtures():
    source=dict(**SCOPE,registration_id='registration',source_stream_id='stream',source_epoch='source_epoch')
    fault=dict(scope=copy.deepcopy(SCOPE),fault_id='fault',detector_domain_ref=ref('runtime_domain','domain'),detector_sequence='1',
        source_key=source,reason='sequence_gap',source_revision_at_detection='8',observed_event_ref=None,
        gap=dict(kind='known',first='11',last='12'),evidence_refs=[ref('source_observation','observation')])
    seal(fault,'fault_digest')
    targets=[]
    for n in range(2):
        rid='run'+str(n);g='5' if n==0 else '3'
        selector=dict(kind='run_generation',origin_scope=copy.deepcopy(SCOPE),run_id=rid,deny_through_generation=g)
        ct=dict(target_id='controller_target'+str(n),controller_scope=dict(authority_service_id='controller'+str(n),database_instance_id='controller_db'+str(n)),
            selector=selector,selector_digest=digest(selector),preparation_refs=[ref('preparation_intent','prepare'+str(n))],
            submission_refs=[ref('command_submission','submission'+str(n))] if n else [])
        seal(ct,'target_digest')
        targets.append(dict(target_id='run_target'+str(n),run_id=rid,run_revision_before='2',run_revision_after='3' if n==0 else '2',
            arm_generation=g,dependency_refs=[ref('source_dependency','guard' if n==0 else 'old_execution_pin')],
            execution_refs=[ref('execution_binding','old_execution')] if n else [],latch_id='latch'+str(n),controllers=[ct]))
    plan=dict(scope=copy.deepcopy(SCOPE),protection_id='protection',fault_ref=ref('source_fault','fault',fault['fault_digest']),
        dependency_index_revision='9',source_state_before='synchronized',source_state_after='desynchronized',
        source_revision_before='8',source_revision_after='9',targets=targets,targets_digest=digest(targets))
    seal(plan,'plan_digest')
    ctx=dict(authenticated_source=True,scope=copy.deepcopy(SCOPE),source=copy.deepcopy(source),
        source_revision='8',source_state='synchronized',dependency_index_revision='9',targets=copy.deepcopy(targets),
        run_states={'run0':'armed','run1':'completed'},current_controller_scopes=[copy.deepcopy(t['controllers'][0]['controller_scope']) for t in targets])
    origin=dict(origin_scope=copy.deepcopy(SCOPE),run_id='run0',definition_version='1',arm_generation='5',
        execution_id='execution',execution_binding_ref=ref('execution_binding','execution'),step_id='step',logical_action_id='action')
    intent=dict(permit_id='permit',command_id='command',attempt_id='attempt',dispatch_intent_id='intent',controller_boot_id='controller_boot',
        worker_boot_id='worker_boot',device_session_id='device_session',ipc_session_id='ipc_session',device_id='device',
        guard_id='guard',guard_digest=digest('guard'),clock_domain_id='clock_'+'a'*64,descriptor_digest=digest('descriptor'),
        automation_binding=origin,automation_binding_digest=digest(origin))
    target=targets[0]['controllers'][0]
    fence=dict(operation_id='fence',barrier_id='barrier',controller_scope=copy.deepcopy(target['controller_scope']),
        selector=copy.deepcopy(target['selector']),selector_digest=target['selector_digest'],issued_cut_revision='10',
        target_deny_revision='4',ledger_digest=digest([intent]),open_intents=[intent])
    ack={k:copy.deepcopy(v) for k,v in fence.items() if k!='open_intents'}
    ack.update(coverage=[dict(intent=copy.deepcopy(intent),disposition='in_flight',proof='transport_entered')],all_write_exits_fenced=True)
    fence_ctx=dict(authorized_origin=copy.deepcopy(SCOPE),controller_scope=copy.deepcopy(target['controller_scope']),
        ledger=copy.deepcopy(fence['open_intents']),selector=copy.deepcopy(target['selector']),
        current_worker_boot='worker_boot',current_ipc_session='ipc_session',exit_evidence_complete=True)
    return fault,plan,ctx,fence,ack,fence_ctx


def reseal_plan(fault,plan):
    seal(fault,'fault_digest')
    plan['fault_ref']=ref('source_fault',fault['fault_id'],fault['fault_digest'])
    for target in plan['targets']:
        for c in target['controllers']:
            c['selector_digest']=digest(c['selector']);seal(c,'target_digest')
    plan['targets_digest']=digest(plan['targets']);seal(plan,'plan_digest')


def plan_error(fault,p,c):
    if not c['authenticated_source']:return 'unauthenticated'
    if fault['scope']!=c['scope'] or p['scope']!=c['scope'] or fault['source_key']!=c['source']:return 'scope'
    if fault['source_revision_at_detection']!=c['source_revision'] or p['source_revision_before']!=c['source_revision']:return 'source_revision'
    if p['source_revision_after']!=inc(p['source_revision_before']):return 'source_revision_after'
    if p['dependency_index_revision']!=c['dependency_index_revision']:return 'dependency_revision'
    if p['source_state_before']!=c['source_state'] or p['source_state_after']!=failure_state(c['source_state'],fault['reason']):return 'source_state'
    if fault['gap']['kind']=='known' and int(fault['gap']['first'])>int(fault['gap']['last']):return 'gap'
    if p['targets']!=c['targets']:return 'whole_dependency_set'
    ids=[t['run_id'] for t in p['targets']]
    if ids!=sorted(set(ids)):return 'run_duplicate'
    target_ids=[]
    for t in p['targets']:
        if t['run_revision_after']!=(t['run_revision_before'] if c['run_states'][t['run_id']]=='completed' else inc(t['run_revision_before'])):return 'run_revision'
        if not t['dependency_refs']:return 'dependency_evidence'
        for x in t['controllers']:
            target_ids.append(x['target_id'])
            s=x['selector']
            if s['origin_scope']!=p['scope'] or s['run_id']!=t['run_id'] or s['deny_through_generation']!=t['arm_generation']:return 'selector'
            if x['controller_scope'] not in c['current_controller_scopes']:return 'controller_scope'
    if len(set(target_ids))!=len(target_ids):return 'target_duplicate'
    a,b=copy.deepcopy(fault),copy.deepcopy(p);reseal_plan(a,b)
    if a!=fault or b!=p:return 'digest'
    return None


def fence_error(f,a,c):
    if f['controller_scope']!=c['controller_scope'] or f['selector']!=c['selector'] or f['selector']['origin_scope']!=c['authorized_origin']:return 'authority'
    if f['selector_digest']!=digest(f['selector']) or f['ledger_digest']!=digest(f['open_intents']):return 'digest'
    if f['open_intents']!=c['ledger']:return 'ledger_set'
    if f['open_intents']!=sorted(f['open_intents'],key=intent_key):return 'ledger_order'
    ids=[i['dispatch_intent_id'] for i in f['open_intents']]
    if len(set(ids))!=len(ids):return 'duplicate_intent'
    for i in f['open_intents']:
        if i['automation_binding_digest']!=digest(i['automation_binding']) or not matches(f['selector'],i['automation_binding']):return 'binding'
        if i['automation_binding']['execution_binding_ref']['scope']!=i['automation_binding']['origin_scope']:return 'execution_scope'
    for k in f:
        if k!='open_intents' and a[k]!=f[k]:return 'ack_binding'
    if not a['all_write_exits_fenced'] or not c['exit_evidence_complete']:return 'exit_coverage'
    if [x['intent'] for x in a['coverage']]!=f['open_intents']:return 'coverage_set'
    for x in a['coverage']:
        expected={'not_sent':('never_received','discarded_unconsumed'),'in_flight':('transport_entered',),'unknown':('send_uncertain',)}
        if x['proof'] not in expected[x['disposition']]:return 'proof'
        i=x['intent']
        if x['disposition']=='not_sent' and (i['worker_boot_id']!=c['current_worker_boot'] or i['ipc_session_id']!=c['current_ipc_session']):return 'old_exit_not_sent'
    return None


def receipt_error(r,request,c):
    for k in ('controller_scope','operation_id','selector','selector_digest','target_set_digest'):
        if r[k]!=request[k]:return 'receipt_binding'
    if r['selector_digest']!=digest(r['selector']):return 'selector_digest'
    if r['cut_revision']!=c['cut_revision']:return 'cut'
    if r['status']=='applied' and (not c['durable'] or not c['coverage_complete']):return 'not_durable_applied'
    if int(r['applied_deny_through_generation'])<int(r['selector']['deny_through_generation']):return 'deny_floor'
    for field,kind in [('barrier_ref','run_barrier'),('coverage_ref','run_coverage')]:
        if r[field]['scope']!=r['controller_scope'] or r[field]['kind']!=kind:return 'receipt_ref'
    copy_r=copy.deepcopy(r);seal(copy_r,'receipt_digest')
    if copy_r!=r:return 'receipt_digest'
    return None


def protected_state(plan,states,cut=None):
    """有限事务模型：逐阶段构造私有副本；故障丢弃副本，RAM门始终保持关闭。"""
    before=copy.deepcopy(states);work=copy.deepcopy(states);steps=0
    def tick():
        nonlocal steps
        steps+=1
        if steps==cut:raise RuntimeError('injected')
    try:
        key=plan['protection_id']
        if key in work['plans']:
            if work['plans'][key]!=plan['plan_digest']:return before,True,'conflict'
            return before,True,'existing'
        work['plans'][key]=plan['plan_digest'];tick()
        work['source_state']=plan['source_state_after'];work['source_revision']=plan['source_revision_after'];tick()
        for t in plan['targets']:
            rid=t['run_id']
            work['deny'][rid]=str(max(int(work['deny'].get(rid,'0')),int(t['arm_generation'])))
            if work['runs'][rid]!='completed':work['runs'][rid]='paused'
            work['latches'].append(t['latch_id']);tick()
            work['outbox']+=[x['target_id'] for x in t['controllers']];tick()
        work['audit'].append(key);tick()
        return work,True,'committed'
    except RuntimeError:
        return before,True,'unconfirmed'


def recovery_error(c):
    if not c['explicit_preview']:return 'explicit_required'
    if not c['source_synchronized'] or c['baseline_revision']!=c['current_source_revision']:return 'source'
    if c['preview_dependency_revision']!=c['dependency_revision']:return 'dependency'
    if sorted(c['resolved_latches'])!=sorted(c['current_latches']) or len(set(c['resolved_latches']))!=len(c['resolved_latches']):return 'latches'
    if sorted(c['receipt_targets'])!=sorted(c['expected_targets']) or len(set(c['receipt_targets']))!=len(c['receipt_targets']):return 'targets'
    if not c['all_receipts_applied'] or not c['receipts_durable']:return 'remote'
    if not c['resources_clear']:return 'resources'
    if int(c['baseline_sequence'])<max(int(c['highest_seen']),int(c['reject_floor'])):return 'floor'
    if int(c['new_generation'])<=max(map(int,c['deny_floors'])):return 'generation'
    if not c['current_gates'] or not c['preflight_valid']:return 'gates'
    return None


def run():
    generated=build()
    for name,s in generated.items():
        assert (HERE/name).read_bytes()==encoded(s),name
        Draft202012Validator.check_schema(s)
    registry=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in generated.values()])
    def valid(n,v):return Draft202012Validator({'$ref':SID+'#/$defs/'+n},registry=registry).is_valid(v)
    results=[]
    def expect(n,ok):
        assert ok,n
        results.append(dict(id=n,passed=True))
    fault,plan,ctx,fence,ack,fc=fixtures()
    expect('完整来源依赖计划',plan_error(fault,plan,ctx) is None)
    expect('完整代次屏障',fence_error(fence,ack,fc) is None)
    origin=fence['open_intents'][0]['automation_binding']
    latch=dict(scope=copy.deepcopy(SCOPE),latch_id='latch0',run_id='run0',
        protection_ref=ref('source_protection_plan','protection',plan['plan_digest']),source_key=fault['source_key'],
        blocked_through_generation='5',created_run_revision='3')
    seal(latch,'latch_digest')
    request=dict(contract_version=VERSION,operation_id='fence',controller_scope=fc['controller_scope'],selector=fc['selector'],
        selector_digest=digest(fc['selector']),target_set_digest=digest([plan['targets'][0]['controllers'][0]]),
        basis='durable_protection',protection_ref=latch['protection_ref'],
        detector_domain_ref=fault['detector_domain_ref'])
    reb=dict(source_key=fault['source_key'],old_source_revision='9',new_source_revision='10',baseline_ref=ref('source_baseline','baseline'),
        baseline_sequence='20',reject_floor='20',unresolved_gap_refs=[ref('source_gap','gap')],protection_refs=[latch['protection_ref']])
    seal(reb,'receipt_digest')
    receipt=dict(controller_scope=fc['controller_scope'],operation_id='fence',selector=fc['selector'],selector_digest=digest(fc['selector']),
        cut_revision='10',target_set_digest=digest([plan['targets'][0]['controllers'][0]]),barrier_ref=ref('run_barrier','barrier'),
        applied_deny_through_generation='5',coverage_ref=ref('run_coverage','coverage'),status='applied')
    receipt['barrier_ref']['scope']=copy.deepcopy(fc['controller_scope'])
    receipt['coverage_ref']['scope']=copy.deepcopy(fc['controller_scope'])
    seal(receipt,'receipt_digest')
    resolution=dict(latch_ref=ref('source_pause_latch','latch0',latch['latch_digest']),rebaseline_ref=ref('source_rebaseline','baseline',reb['receipt_digest']),
        fence_receipt_refs=[ref('run_fence_receipt','receipt',receipt['receipt_digest'])],resource_resolution_refs=[ref('resource_resolution','clear')],
        new_arm_generation='6',preflight_ref=ref('recovery_preflight','preflight'))
    resolution['fence_receipt_refs'][0]['scope']=copy.deepcopy(fc['controller_scope'])
    seal(resolution,'resolution_digest')
    samples=dict(SourceFault=fault,SourceProtectionPlan=plan,SourcePauseLatch=latch,AutomationOriginBinding=origin,
        RunGenerationSelector=fc['selector'],OriginExtension=dict(origin='automation',automation_binding=origin,automation_binding_digest=digest(origin)),
        ProtectionRequest=request,RunFenceBody=fence,RunFenceAckBody=ack,SourceRebaselineReceipt=reb,
        ControllerRunFenceReceipt=receipt,SourcePauseResolution=resolution,
        ControllerProtectionRecord=dict(controller_scope=fc['controller_scope'],operation_id='fence',selector=fc['selector'],
            selector_digest=digest(fc['selector']),target_set_digest=request['target_set_digest'],revision='1',state='accepted',receipt_ref=None),
        SourceProtectionRecord=dict(plan_ref=latch['protection_ref'],revision='1',local_state='committed',
            remote_state='pending',receipt_refs=[],unresolved_target_ids=['controller_target0','controller_target1']))
    for model,value in samples.items():
        expect('结构-'+model,valid(model,value))
        bad=copy.deepcopy(value);bad['unexpected']=True;expect('额外字段-'+model,not valid(model,bad))
        bad=copy.deepcopy(value);del bad[next(iter(value))];expect('缺必填-'+model,not valid(model,bad))
    for typ,body in [('RUN_FENCE',fence),('RUN_FENCE_ACK',ack)]:
        v=dict(protocol='run-fence-body/0.1.0-draft.1',type=typ,body=body)
        expect('正文包络-'+typ,Draft202012Validator(generated['run-fence.schema.json'],registry=registry).is_valid(v))
        v['protocol']='ipc/0.3.0-draft.1'
        expect('拒绝冒充旧IPC-'+typ,not Draft202012Validator(generated['run-fence.schema.json'],registry=registry).is_valid(v))
    record=copy.deepcopy(samples['ControllerProtectionRecord']);record['state']='applied'
    expect('applied不能没有回执',not valid('ControllerProtectionRecord',record))
    record['receipt_ref']=copy.deepcopy(resolution['fence_receipt_refs'][0])
    expect('applied回执结构',valid('ControllerProtectionRecord',record))
    manual=dict(origin='manual',automation_binding=None,automation_binding_digest=None)
    expect('manual无自动化绑定',valid('OriginExtension',manual))
    manual['automation_binding']=origin
    expect('manual禁止伪装自动化绑定',not valid('OriginExtension',manual))
    for basis,protection,expected in [('emergency_fault',None,True),('durable_protection',None,False),('emergency_fault',ref('source_protection_plan','fake'),False)]:
        v=copy.deepcopy(request);v.update(basis=basis,protection_ref=protection)
        expect('紧急路径引用-'+basis+str(protection is None),valid('ProtectionRequest',v)==expected)
    for bad in ('01','1\n','-1','100000000000000000000'):
        v=copy.deepcopy(fc['selector']);v['deny_through_generation']=bad
        expect('拒绝非U20-'+repr(bad),not valid('RunGenerationSelector',v))
    expect('精确大整数',inc('9007199254740992')=='9007199254740993')
    try:inc('99999999999999999999');raise AssertionError('overflow')
    except ValueError:expect('代次耗尽不回绕',True)
    mutations=[
        ('遗漏旧执行依赖',lambda f,p:p['targets'].pop()),
        ('同count换run',lambda f,p:p['targets'][1].update(run_id='other')),
        ('遗漏准备未确认目标',lambda f,p:p['targets'][0]['controllers'].clear()),
        ('同count换Controller库',lambda f,p:p['targets'][1]['controllers'][0]['controller_scope'].update(database_instance_id='other')),
        ('换source_epoch',lambda f,p:f['source_key'].update(source_epoch='other')),
        ('前态修订错',lambda f,p:p.update(source_revision_before='7')),
        ('索引修订旧',lambda f,p:p.update(dependency_index_revision='8')),
        ('source修订跳跃',lambda f,p:p.update(source_revision_after='10')),
        ('故障降级',lambda f,p:p.update(source_state_after='synchronized')),
        ('gap反向',lambda f,p:f['gap'].update(first='13',last='12')),
        ('错运行代次',lambda f,p:p['targets'][0]['controllers'][0]['selector'].update(deny_through_generation='4')),
        ('错运行来源域',lambda f,p:p['targets'][0]['controllers'][0]['selector']['origin_scope'].update(database_instance_id='other')),
    ]
    for n,mutate in mutations:
        f,p=copy.deepcopy(fault),copy.deepcopy(plan);mutate(f,p);reseal_plan(f,p)
        expect('重算仍拒绝-'+n,valid('SourceFault',f) and valid('SourceProtectionPlan',p) and plan_error(f,p,ctx) is not None)
    c=copy.deepcopy(ctx);c['authenticated_source']=False
    expect('未认证不得暂停冒名来源',plan_error(fault,plan,c)=='unauthenticated')
    for before,reason,expected in [('quarantined','sequence_gap','quarantined'),('closed','sequence_gap','closed'),
        ('desynchronized','content_conflict','quarantined'),('synchronized','source_changed','closed')]:
        expect('故障合并-'+before+reason,failure_state(before,reason)==expected)
    for field,value,expected in [('arm_generation','4',True),('arm_generation','5',True),('arm_generation','6',False),('run_id','other',False)]:
        o=copy.deepcopy(origin);o[field]=value
        expect('选择器-'+field+value,matches(fc['selector'],o)==expected)
    o=copy.deepcopy(origin);o['origin_scope']['database_instance_id']='other'
    expect('选择器不同库不匹配',not matches(fc['selector'],o));expect('选择器人工不匹配',not matches(fc['selector'],None))
    for name,mutate in [
        ('少coverage',lambda a:a['coverage'].clear()),('重复coverage',lambda a:a['coverage'].append(copy.deepcopy(a['coverage'][0]))),
        ('错切点',lambda a:a.update(issued_cut_revision='9')),('错屏障',lambda a:a.update(barrier_id='other')),
        ('错selector',lambda a:a['selector'].update(run_id='other')),('ACK未覆盖',lambda a:a.update(all_write_exits_fenced=False))]:
        a=copy.deepcopy(ack);mutate(a);expect('屏障拒绝-'+name,fence_error(fence,a,fc) is not None)
    for disposition,proof in [('not_sent','discarded_unconsumed'),('unknown','send_uncertain')]:
        a=copy.deepcopy(ack);a['coverage'][0].update(disposition=disposition,proof=proof)
        expect('屏障允许-'+disposition,valid('RunFenceAckBody',a) and fence_error(fence,a,fc) is None)
    a=copy.deepcopy(ack);a['coverage'][0].update(disposition='not_sent',proof='discarded_unconsumed')
    c=copy.deepcopy(fc);c['current_worker_boot']='new_worker'
    expect('旧出口不得自证未发',fence_error(fence,a,c)=='old_exit_not_sent')
    c=copy.deepcopy(fc);c['exit_evidence_complete']=False
    expect('ACK布尔不替代出口证据',fence_error(fence,ack,c)=='exit_coverage')
    f,a,c=copy.deepcopy(fence),copy.deepcopy(ack),copy.deepcopy(fc)
    second=copy.deepcopy(f['open_intents'][0]);second.update(permit_id='permit2',dispatch_intent_id='intent2')
    f['open_intents'].append(second);f['ledger_digest']=digest(f['open_intents']);c['ledger']=copy.deepcopy(f['open_intents'])
    a['ledger_digest']=f['ledger_digest'];a['coverage'].append(dict(intent=copy.deepcopy(second),disposition='unknown',proof='send_uncertain'))
    expect('多出口完整混合覆盖',fence_error(f,a,c) is None)
    f['open_intents'].reverse();f['ledger_digest']=digest(f['open_intents']);c['ledger']=copy.deepcopy(f['open_intents'])
    a['coverage'].reverse();a['ledger_digest']=f['ledger_digest']
    expect('重算摘要仍拒乱序账本',fence_error(f,a,c)=='ledger_order')
    rc=dict(cut_revision='10',durable=True,coverage_complete=True)
    expect('持久Controller回执',receipt_error(receipt,request,rc) is None)
    for field,value in [('operation_id','other'),('cut_revision','9'),('target_set_digest',digest('other')),
                        ('applied_deny_through_generation','4')]:
        r=copy.deepcopy(receipt);r[field]=value;seal(r,'receipt_digest')
        expect('重算回执仍拒绝-'+field,receipt_error(r,request,rc) is not None)
    r=copy.deepcopy(receipt);r['barrier_ref']['scope']=copy.deepcopy(SCOPE);seal(r,'receipt_digest')
    expect('回执不借Seamer域冒充Controller',receipt_error(r,request,rc)=='receipt_ref')
    for field in ('durable','coverage_complete'):
        c=copy.deepcopy(rc);c[field]=False
        expect('applied必须有-'+field,receipt_error(receipt,request,c)=='not_durable_applied')
    states=dict(plans={},source_state='synchronized',source_revision='8',runs={'run0':'armed','run1':'completed'},
        deny={},latches=[],outbox=[],audit=[],original_decisions={'event':'suppressed_busy'})
    final,closed,result=protected_state(plan,states)
    expect('P1完整提交',result=='committed' and closed and final['runs']=={'run0':'paused','run1':'completed'}
        and final['deny']=={'run0':'5','run1':'3'} and final['outbox']==['controller_target0','controller_target1']
        and final['original_decisions']==states['original_decisions'])
    for cut in range(1,8):
        state,closed,result=protected_state(plan,states,cut)
        expect('P1故障切点-'+str(cut),state==states and closed and result=='unconfirmed')
    dup,closed,result=protected_state(plan,final)
    expect('重复fault不增加latch或outbox',dup==final and closed and result=='existing')
    changed=copy.deepcopy(plan);changed['plan_digest']=digest('different')
    state,closed,result=protected_state(changed,final)
    expect('同身份异内容保留原件',state==final and closed and result=='conflict')
    recovery=dict(explicit_preview=True,source_synchronized=True,baseline_revision='10',current_source_revision='10',
        preview_dependency_revision='9',dependency_revision='9',resolved_latches=['latch0','manual_latch'],
        current_latches=['latch0','manual_latch'],receipt_targets=['controller_target0','controller_target1'],
        expected_targets=['controller_target0','controller_target1'],all_receipts_applied=True,receipts_durable=True,
        resources_clear=True,baseline_sequence='20',highest_seen='20',reject_floor='20',new_generation='6',
        deny_floors=['5','3'],current_gates=True,preflight_valid=True)
    expect('显式新代次恢复前提',recovery_error(recovery) is None)
    for field,value in [('explicit_preview',False),('source_synchronized',False),('current_source_revision','11'),
        ('dependency_revision','10'),('current_latches',['latch0','manual_latch','new_fault']),('resolved_latches',['latch0']),
        ('receipt_targets',['controller_target0']),('all_receipts_applied',False),('receipts_durable',False),
        ('resources_clear',False),('baseline_sequence','19'),('reject_floor','21'),('new_generation','5'),
        ('current_gates',False),('preflight_valid',False)]:
        c=copy.deepcopy(recovery);c[field]=value;expect('恢复拒绝-'+field,recovery_error(c) is not None)
    # 重启默认未布防是模型前提；不把RAM告警存活当作持久性证明。
    restarted={rid:('completed' if status=='completed' else 'paused') for rid,status in states['runs'].items()}
    expect('无故障记录的启动仍不布防',restarted=={'run0':'paused','run1':'completed'})
    return dict(all_passed=True,approved=False,checks=len(results),results=results,
        runtime_validation=dict(services=0,authentication=0,ipc=0,sqlite=0,concurrency=0,disk_crash=0,devices=0),
        limitations=['权威集合和出口证据为人工前提','P1为私有副本的有限原子模型，不执行SQLite','ACK不证明资源clear',
            '恢复只核有限门槛，未执行R2至R4或完整引用取证','两个正文包络非完整设备IPC或HTTP实现'],
        input_sha256={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in INPUTS})


def bindings(staged):
    def read(p):return subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else p.read_bytes()
    r=json.loads(read(REPORT));assert r['all_passed'] is True
    assert set(r['input_sha256'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
    for p in INPUTS:assert sha(read(p))==r['input_sha256'][p.relative_to(ROOT).as_posix()],p
    print('保护候选报告输入绑定通过:',len(INPUTS),'；未重跑用例')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true')
    a=p.parse_args()
    if a.check_report:bindings(a.staged)
    else:
        r=run()
        if a.report:REPORT.write_bytes(encoded(r))
        print('来源保护参考检查通过:',r['checks'])
