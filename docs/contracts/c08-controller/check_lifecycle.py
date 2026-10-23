"""人工预期的终态、释放及重试快照检查；无业务服务或数据库I/O。"""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
from build_lifecycle import HERE,build,encoded
import lifecycle_model as M

ROOT=HERE.parents[2]
INPUTS=[HERE/n for n in ('LIFECYCLE.md','build_lifecycle.py','lifecycle_model.py',
    'check_lifecycle.py','lifecycle.schema.json','BARRIER_ATTEMPTS.md','fence.sql','barrier-attempt.sql')]
INPUTS += [ROOT/'docs'/n for n in ('rebirth-f02-f03-design.md','rebirth-f06-f07-design.md',
                                  'rebirth-df04-storage-design.md')]
def ref(name):return dict(id=name,revision='1',digest=M.digest(name))
def fixture():
    scope=dict(authority_service_id='controller',database_instance_id='database')
    p=dict(command_id='command',scope=scope,device_id='device',admission_ref=ref('admission'),
           required_completion='effect_verified',completion_policy_ref=ref('completion-policy'),
           release_policy_ref=ref('release-policy'),retry_policy_ref=None,max_attempts=1,
           original_deadline_ref=ref('deadline'),conflict_scope='whole_device')
    before=dict(command_id='command',scope=scope,revision='3',phase='awaiting_evidence',
        outcome='pending',effect_status='possible',resource_status='held',
        automation_continuation='eligible',reason_code=None,terminal_revision=None,resolution_ref=None,
        completion_evidence_refs=[],resource_evidence_refs=[],attempt_ids=['attempt'])
    tx=dict(permit_id='permit',transmission_id='tx',attempt_id='attempt',
        packet_ref=dict(packet_id='packet',packet_digest=M.digest('packet')),exit_ref=ref('exit'),
        issued_revision='1',disposition='in_flight',settlement_kind=None,settlement_ref=None)
    cut=M.seal(dict(cut_id='cut',command_id='command',scope=scope,device_id='device',hold_id='hold',
        issued_cut_revision='1',attempt_ids=['attempt'],transmissions=[tx]),'cut_digest')
    c=dict(policy=p,current_state=before,attempt_ids=['attempt'],cut=cut,
        authoritative_cut=copy.deepcopy(cut),cut_record_revision='1',
        provider_receipts={},future_writes_closed_ref=ref('closed'),settlement_proof_ref=ref('settled'),
        next_resolution_revision=1,resolver_ref=ref('resolver'),device_blockers=[],
        dispatch_committed=True,queued_cancel_committed=True,current_attempt_closed=True,
        now_tick=100,original_deadline_tick=200,
        evidence_deadline_tick=100,approved_retry_policy_ref=None,retry_error_allowed=True,
        retry_budget_remaining=True,has_hold=True,persisted_release_evidence=None,historical_effects=[])
    a=copy.deepcopy(before);a.update(revision='4',phase='finished',outcome='unknown',
        terminal_revision='4',resource_status='unresolved',automation_continuation='paused_latched',
        reason_code='EVIDENCE_TIMEOUT')
    t=dict(operation_id='op',expected_state_ref=M.state_ref(before),kind='timeout',after=a,
           decision_evidence=None,release_evidence=None,resolution=None,audit_ref=ref('audit'),outbox_ref=ref('outbox'))
    return copy.deepcopy((before,t,c))

def accept(e,claims,c):
    c['provider_receipts'][e['evidence_digest']]=dict(receipt_id='provider',scope=copy.deepcopy(e['scope']),
        command_id=e['command_id'],subject_digest=e['evidence_digest'],policy_ref=copy.deepcopy(e['policy_ref']),
        verdict='accepted',claims=claims,source_refs=[ref('source')],record_revision='1')

def decision(c,kind='completion',achieved='effect_verified',effect='verified',resolved=None):
    e=M.seal(dict(evidence_id='evidence-'+kind,command_id='command',scope=copy.deepcopy(c['policy']['scope']),
        kind=kind,policy_ref=copy.deepcopy(c['policy']['completion_policy_ref']),
        retry_policy_ref=copy.deepcopy(c['policy']['retry_policy_ref']) if kind=='failure' else None,
        attempt_ids=['attempt'],
        achieved=achieved,effect_status=effect,resolved_outcome=resolved),'evidence_digest')
    claims={'completion':['completion_verified'],'failure':['failure_confirmed','safe_failure'],
            'resolution':['resolution_supported'],'cancellation':['cancellation_confirmed']}[kind]
    accept(e,claims,c);return e

def release(c,kind='module_settled'):
    for tx in c['cut']['transmissions']:
        tx.update(disposition='not_sent' if kind=='never_sent' else 'in_flight',
                  settlement_kind='never_sent' if kind=='never_sent' else 'effect_resolved',
                  settlement_ref=ref('settlement'))
    M.seal(c['cut'],'cut_digest');c['authoritative_cut']=copy.deepcopy(c['cut'])
    e=M.seal(dict(evidence_id='release',command_id='command',scope=copy.deepcopy(c['policy']['scope']),
        device_id='device',hold_id='hold',cut_ref=dict(id='cut',revision='1',digest=c['cut']['cut_digest']),
        kind=kind,policy_ref=copy.deepcopy(c['policy']['release_policy_ref']),
        future_writes_closed_ref=copy.deepcopy(c['future_writes_closed_ref']),
        settlement_proof_ref=None if kind=='never_sent' else copy.deepcopy(c['settlement_proof_ref'])),'evidence_digest')
    accept(e,['future_writes_closed',{'module_settled':'module_settled','never_sent':'never_sent',
                                    'maintenance_fenced':'maintenance_settled'}[kind]],c)
    return e

def success():
    b,t,c=fixture();t['kind']='complete';e=decision(c);t['decision_evidence']=e
    t['after'].update(outcome='succeeded',effect_status='verified',automation_continuation='eligible',
                      reason_code=None,completion_evidence_refs=[M.evidence_ref(e)])
    return b,t,c

def reconciled():
    _,old,c=fixture();b=copy.deepcopy(old['after']);c['current_state']=copy.deepcopy(b)
    e=decision(c,'resolution',None,'verified','succeeded')
    r=M.seal(dict(resolution_id='resolution',command_id='command',scope=copy.deepcopy(b['scope']),
        original_terminal_revision='4',revision='1',resolved_outcome='succeeded',
        evidence_refs=[M.evidence_ref(e)],resolver_ref=copy.deepcopy(c['resolver_ref'])),'resolution_digest')
    t=copy.deepcopy(old);t.update(kind='reconcile',expected_state_ref=M.state_ref(b),
        decision_evidence=e,resolution=r);t['after'].update(revision='5',effect_status='verified',
        resolution_ref=M.resolution_ref(r))
    t['release_evidence']=release(c)
    t['after'].update(resource_status='clear',resource_evidence_refs=[M.evidence_ref(t['release_evidence'])])
    return b,t,c

def run():
    schema=build();assert (HERE/'lifecycle.schema.json').read_bytes()==encoded(schema)
    Draft202012Validator.check_schema(schema)
    def valid(name,v):
        return Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':schema['$defs']}).is_valid(v)
    checks=[]
    def check(name,actual,expected=None):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    def evaluate(name,b,t,c,expected=None):
        check(name+'结构',valid('State',b) and valid('Transition',t) and valid('Policy',c['policy']),True)
        check(name,M.transition_error(b,t,c),expected)
    b,t,c=fixture();evaluate('超时保留未知',b,t,c)
    b,t,c=fixture();b.update(phase='dispatching',attempt_ids=['attempt','attempt.new'])
    c['current_state']=copy.deepcopy(b);c['attempt_ids']=list(b['attempt_ids'])
    c['policy'].update(max_attempts=2,retry_policy_ref=ref('retry-policy'))
    c['cut']['attempt_ids']=list(b['attempt_ids']);c['cut']['issued_cut_revision']='2'
    newer=copy.deepcopy(c['cut']['transmissions'][0])
    newer.update(permit_id='permit.new',transmission_id='tx.new',attempt_id='attempt.new',
                 issued_revision='2',disposition='unknown')
    c['cut']['transmissions'].append(newer);M.seal(c['cut'],'cut_digest')
    c['authoritative_cut']=copy.deepcopy(c['cut'])
    t.update(kind='transport',expected_state_ref=M.state_ref(b),after=copy.deepcopy(b))
    t['after'].update(revision='4',phase='awaiting_evidence')
    evaluate('新尝试不借旧尝试进入传输',b,t,c,'transport_unproven')
    c['cut']['transmissions'][-1]['disposition']='in_flight';M.seal(c['cut'],'cut_digest')
    c['authoritative_cut']=copy.deepcopy(c['cut'])
    evaluate('当前尝试有独立进入证据',b,t,c)
    b,t,c=fixture()
    for model,value in [('State',b),('Transition',t),('Policy',c['policy']),('ResourceCut',c['cut']),
                        ('Transmission',c['cut']['transmissions'][0])]:
        bad=copy.deepcopy(value);bad['extra']=True;check('封闭字段'+model,valid(model,bad),False)
    for value in ('01','-1','1\n','100000000000000000000'):
        check('严格计数'+repr(value),valid('Counter',value),False)
    bad=copy.deepcopy(t);bad['after']['revision']='6';evaluate('修订不跳号',b,bad,c,'state_revision')
    bad=copy.deepcopy(t);bad['expected_state_ref']['digest']=M.digest('other')
    evaluate('过期CAS',b,bad,c,'state_cas')
    bad=copy.deepcopy(t);bad['after']['scope']['database_instance_id']='other'
    evaluate('跨库拒绝',b,bad,c,'state_owner')
    evaluate('观测期限未到',b,t,{**c,'now_tick':99},'not_timed_out')
    b,t,c=success();evaluate('完成不自动清资源',b,t,c)
    cc=copy.deepcopy(c);bad=copy.deepcopy(t);e=bad['decision_evidence']
    e.update(achieved='acknowledged',effect_status='acknowledged');M.seal(e,'evidence_digest')
    accept(e,['completion_acknowledged'],cc)
    bad['after'].update(effect_status='acknowledged',completion_evidence_refs=[M.evidence_ref(e)])
    evaluate('协议确认不冒充效果完成',b,bad,cc,'completion_level')
    cc['policy']['required_completion']='acknowledged'
    evaluate('独立批准较弱完成标准',b,bad,cc)
    for status in ('rejected','indeterminate'):
        cc=copy.deepcopy(c);next(iter(cc['provider_receipts'].values()))['verdict']=status
        evaluate('提供者'+status,b,t,cc,'provider_unconfirmed')
    evaluate('无提供者记录',b,t,{**c,'provider_receipts':{}},'provider_missing')
    bad=copy.deepcopy(t);bad['decision_evidence']['effect_status']='partial'
    evaluate('证据摘要不可改',b,bad,c,'decision_digest')
    M.seal(bad['decision_evidence'],'evidence_digest')
    evaluate('完成层级与效果不可矛盾',b,bad,c,'completion_effect')
    bad['decision_evidence'].update(effect_status='verified',evidence_id='forged')
    M.seal(bad['decision_evidence'],'evidence_digest')
    evaluate('重算摘要不取得权威',b,bad,c,'provider_missing')
    t['release_evidence']=release(c);t['after'].update(resource_status='clear',
        resource_evidence_refs=[M.evidence_ref(t['release_evidence'])])
    evaluate('完成与独立释放同提交',b,t,c)
    check('释放模型',valid('ReleaseEvidence',t['release_evidence']),True)
    for receipt in c['provider_receipts'].values():check('回执模型'+receipt['subject_digest'],valid('ProviderReceipt',receipt),True)
    for field,new,expected in [('hold_id','wrong','release_binding'),('device_id','other','release_binding'),
                              ('future_writes_closed_ref',ref('wrong'),'future_writes'),
                              ('settlement_proof_ref',ref('wrong'),'settlement_binding')]:
        e=copy.deepcopy(t['release_evidence']);e[field]=new;M.seal(e,'evidence_digest')
        check('释放绑定'+field,M.release_error(e,c),expected)
    cc=copy.deepcopy(c);cc['cut']['transmissions']=[];M.seal(cc['cut'],'cut_digest')
    check('重算摘要不能省传输',M.release_error(t['release_evidence'],cc),'cut_binding')
    cc=copy.deepcopy(c);cc['provider_receipts'][t['release_evidence']['evidence_digest']]['claims']=['module_settled']
    check('仅效果证明不能排除后续写',M.release_error(t['release_evidence'],cc),'provider_claims')
    cc=copy.deepcopy(c);cc['provider_receipts'][t['release_evidence']['evidence_digest']]['scope']['database_instance_id']='other'
    check('同摘要跨库不授权',M.release_error(t['release_evidence'],cc),'provider_binding')
    b,t,c=reconciled();evaluate('未知追加核对并释放',b,t,c)
    check('核对模型',valid('Resolution',t['resolution']),True)
    for field,new,expected in [('outcome','succeeded','terminal_immutable'),
                              ('terminal_revision','5','terminal_immutable')]:
        bad=copy.deepcopy(t);bad['after'][field]=new;evaluate('终态固定'+field,b,bad,c,expected)
    bad=copy.deepcopy(t);bad['resolution']['original_terminal_revision']='3'
    M.seal(bad['resolution'],'resolution_digest')
    evaluate('核对不能换原终态',b,bad,c,'resolution_binding')
    bad=copy.deepcopy(t);bad['resolution']['revision']='2';M.seal(bad['resolution'],'resolution_digest')
    evaluate('核对修订精确后继',b,bad,c,'resolution_revision')
    # phase/outcome不变但去掉锁存仍必须拒绝；Schema本身也禁止unknown自动继续。
    bad=copy.deepcopy(t);bad['after']['automation_continuation']='eligible'
    check('未知不得恢复自动化结构',valid('Transition',bad),False)
    check('锁存不可清除语义',M.transition_error(b,bad,c),'latch_immutable')
    bad=copy.deepcopy(t);bad.update(kind='release',resolution=None,decision_evidence=None)
    bad['after'].update(resolution_ref=None,effect_status='possible')
    check('未知只清资源不附核对结构',valid('Transition',bad),False)
    check('未知只清资源不附核对语义',M.transition_error(b,bad,c),'unknown_clear_without_resolution')
    b,t,c=fixture();t['kind']='fail';e=decision(c,'failure',None,'partial');t['decision_evidence']=e
    t['after'].update(outcome='failed',effect_status='partial',reason_code='EXPLICIT_FAILURE')
    c['provider_receipts'][e['evidence_digest']]['claims']=['failure_confirmed']
    evaluate('明确失败仍可部分影响',b,t,c)
    # 条件重试使用同命令，尚未终结，既往效果不抹除，已核对资源与预算。
    c['policy'].update(retry_policy_ref=ref('retry-policy'),max_attempts=2)
    c['approved_retry_policy_ref']=ref('retry-policy')
    t['kind']='retry';t['after'].update(phase='queued',outcome='pending',terminal_revision=None,
        automation_continuation='eligible',reason_code=None)
    t['release_evidence']=release(c);t['after'].update(resource_status='clear',
        resource_evidence_refs=[M.evidence_ref(t['release_evidence'])])
    evaluate('明确失败不是安全重试证明',b,t,c,'provider_claims')
    c['provider_receipts'][e['evidence_digest']]['claims'].append('safe_failure')
    evaluate('安全断言仍须绑定固定重试政策',b,t,c,'retry_policy_binding')
    e['retry_policy_ref']=copy.deepcopy(c['policy']['retry_policy_ref']);M.seal(e,'evidence_digest')
    accept(e,['failure_confirmed','safe_failure'],c)
    evaluate('安全条件重试仍保留部分影响',b,t,c)
    for field,value in [('retry_error_allowed',False),('retry_budget_remaining',False),('now_tick',200)]:
        evaluate('重试边界'+field,b,t,{**c,field:value},'retry_forbidden')
    cc=copy.deepcopy(c);cc['policy']['max_attempts']=1
    evaluate('初次计入尝试预算',b,t,cc,'retry_forbidden')
    bad=copy.deepcopy(t);bad['release_evidence']=None;bad['after']['resource_evidence_refs']=[]
    evaluate('重试需独立清资源',b,bad,c,'retry_release_required')
    b,t,c=fixture();b.update(phase='queued',effect_status='not_sent',resource_status='clear',attempt_ids=[])
    c.update(current_state=copy.deepcopy(b),attempt_ids=[],has_hold=False)
    c['cut'].update(attempt_ids=[],transmissions=[]);M.seal(c['cut'],'cut_digest');c['authoritative_cut']=copy.deepcopy(c['cut'])
    t.update(kind='cancel',expected_state_ref=M.state_ref(b));t['after'].update(
        outcome='cancelled',effect_status='not_sent',resource_status='clear',attempt_ids=[],reason_code='USER_CANCEL')
    evaluate('纯排队取消无虚构释放',b,t,c)
    evaluate('排队取消必须持久排除派发',b,t,{**c,'queued_cancel_committed':False},'queued_cancel_unproven')
    t['kind']='expire';t['after'].update(outcome='expired',reason_code='EXPIRED')
    evaluate('排队截止等号前',b,t,c,'not_expired')
    evaluate('排队截止等号',b,t,{**c,'now_tick':200})
    for kind in ('never_sent','maintenance_fenced'):
        _,_,cc=fixture();e=release(cc,kind);check('释放路径'+kind,M.release_error(e,cc))
        if kind=='never_sent':
            cc['cut']['transmissions'][0]['disposition']='in_flight';M.seal(cc['cut'],'cut_digest')
            cc['authoritative_cut']=copy.deepcopy(cc['cut']);e['cut_ref']['digest']=cc['cut']['cut_digest']
            M.seal(e,'evidence_digest');check('迟到发送推翻未发释放',M.release_error(e,cc),'not_sent_unproven')
    holds=[dict(hold_id='old',command_id='old-command',device_id='device',release_recorded=True),
           dict(hold_id='new',command_id='new-command',device_id='device',release_recorded=False)]
    txs=[dict(command_id='old-command',settlement_kind='never_sent',disposition='not_sent')]
    check('释放后新命令唯一占用',[h['hold_id'] for h in M.hold_blockers(holds,txs)],['new'])
    txs[0]['disposition']='in_flight'
    check('迟到强证据保留两个风险占用',[h['hold_id'] for h in M.hold_blockers(holds,txs)],['old','new'])
    txs[0]['settlement_kind']='effect_resolved'
    check('原发送观察不推翻独立效果核销',[h['hold_id'] for h in M.hold_blockers(holds,txs)],['new'])
    b,t,c=fixture();b.update(phase='queued');c['current_state']=copy.deepcopy(b)
    t.update(kind='dispatch',expected_state_ref=M.state_ref(b))
    t['after'].update(phase='dispatching',outcome='pending',terminal_revision=None,
        resource_status='held',automation_continuation='eligible',reason_code=None)
    evaluate('单次派发状态',b,t,c)
    evaluate('手动也不越过其他风险占用',b,t,{**c,'device_blockers':['old-hold']},'dispatch_gate')
    evaluate('未提交许可不可派发',b,t,{**c,'dispatch_committed':False},'dispatch_gate')
    evaluate('派发截止等号',b,t,{**c,'now_tick':200},'dispatch_gate')
    b,t,c=fixture();b['phase']='dispatching';c['current_state']=copy.deepcopy(b)
    t.update(kind='transport',expected_state_ref=M.state_ref(b))
    t['after'].update(phase='awaiting_evidence',outcome='pending',terminal_revision=None,
        resource_status='held',automation_continuation='eligible',reason_code=None)
    evaluate('传输事实进入证据等待',b,t,c)
    cc=copy.deepcopy(c);cc['cut']['transmissions'][0]['disposition']='unknown'
    M.seal(cc['cut'],'cut_digest');cc['authoritative_cut']=copy.deepcopy(cc['cut'])
    evaluate('IPC投递不证实际发送',b,t,cc,'transport_unproven')
    b,t,c=fixture();t['kind']='block';t['after'].update(outcome='blocked',reason_code='CONTROL_REPLACED')
    evaluate('在途不能伪装门控前未发',b,t,c,'stop_uncertain')
    c['attempt_ids'].append('attempt-2');b['attempt_ids'].append('attempt-2')
    c['current_state']=copy.deepcopy(b);t['expected_state_ref']=M.state_ref(b)
    t['after']['attempt_ids'].append('attempt-2')
    c['policy'].update(retry_policy_ref=ref('retry-policy'),max_attempts=2)
    c['cut']['attempt_ids'].append('attempt-2')
    next_tx=copy.deepcopy(c['cut']['transmissions'][0])
    next_tx.update(permit_id='permit-2',transmission_id='tx-2',attempt_id='attempt-2',
                   disposition='not_sent',settlement_kind='never_sent',settlement_ref=ref('new-unconsumed'))
    c['cut']['transmissions'].append(next_tx);M.seal(c['cut'],'cut_digest')
    c['authoritative_cut']=copy.deepcopy(c['cut'])
    c['historical_effects']=['acknowledged'];t['after']['effect_status']='acknowledged'
    evaluate('当前未发仍保留前次效果',b,t,c)
    b,t,c=reconciled();old=copy.deepcopy(t['after']);stored=copy.deepcopy(t['release_evidence'])
    c.update(current_state=copy.deepcopy(old),persisted_release_evidence=stored)
    p=copy.deepcopy(t);p.update(kind='protect',expected_state_ref=M.state_ref(old),
        decision_evidence=None,resolution=None,release_evidence=None);p['after']['revision']='6'
    evaluate('已有完整释放仍核验原证据',old,p,c)
    cc=copy.deepcopy(c);cc['authoritative_cut']['issued_cut_revision']='2'
    p['after']['resource_status']='unresolved'
    evaluate('过期切点不能裁决当前资源',old,p,cc,'cut_binding')
    # 使用真实新cut裁决保护；旧释放引用仍保留，但不能继续证明新集合已清。
    cc['cut']['issued_cut_revision']='2';M.seal(cc['cut'],'cut_digest')
    cc['authoritative_cut']=copy.deepcopy(cc['cut'])
    evaluate('新切点使旧释放资格失效',old,p,cc)
    b,t,c=fixture();t['kind']='block';t['after'].update(outcome='blocked',
        reason_code='CLOSED_BEFORE_SEND',effect_status='not_sent')
    c['cut']['transmissions'][0]['disposition']='not_sent';M.seal(c['cut'],'cut_digest')
    c['authoritative_cut']=copy.deepcopy(c['cut'])
    evaluate('完整未发证据可排除先前不确定',b,t,c)
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true')
    p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true')
    args=p.parse_args()
    if args.staged and not args.check_report:p.error('--staged需与--check-report共用')
    report=HERE/'lifecycle-report.json'
    if args.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        data=json.loads(read(report));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,
            runtime_tests_executed=0,device_tests_executed=0,sqlite_tests_executed=0,
            checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if args.report:report.write_bytes(encoded(data))
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
