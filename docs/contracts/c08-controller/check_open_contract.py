"""普通与限定用途完整OPEN契约的合成验收；不执行数据库或设备。"""
import argparse,copy,hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator
import build_open_contract as G
import open_contract_model as M
import check_open_lifecycle as L
import check_scoped_gate as Q
O=M.O;S=M.S;HERE=G.HERE;ROOT=HERE.parents[2];clone=copy.deepcopy
LOCAL=('OPEN_CONTRACT.md','build_open_contract.py','open_contract_model.py','check_open_contract.py','open-contract.schema.json','open-contract-examples.json')
def inputs():return list(dict.fromkeys(L.INPUTS+Q.H.INPUTS+[G.IPC]+[HERE/n for n in Q.LOCAL+LOCAL]))
def fixture(kind='ordinary'):
    p,d,e,_,c=L.fixture();a,assessment,_,sc=Q.fixture(kind);plan=p['plan'];b=plan['body'];control=clone(sc['control_projection']);control['gate_state']='protected';sc['control_projection']=clone(control)
    p['format_version']='gate-open-proposal/0.3.0-draft.1';plan['format_version']='gate-open-plan/0.3.0-draft.1';plan['binding']=clone(a['binding']);b.update(gate_access=a,protection_assessment=assessment)
    b.update({k:a['binding'][k] for k in ('device_session_id','clock_domain_id','descriptor_digest')});b.update(control_epoch=a['control_epoch'],control_version=a['effective_version'])
    b['reference_time_snapshot']['domain'].update(a['binding']['scope']);b['reference_time_snapshot']['domain'].update({k:a['binding'][k] for k in ('clock_domain_id','descriptor_digest')});O.seal(b['reference_time_snapshot'],'snapshot_digest')
    p['control_before']=control;p['gate_before'].pop('ready_activation_id');p['gate_before'].update(binding=clone(a['binding']),activation_id=None)
    eligibility=dict(control_authority=a['control_authority_ref'],authorization=a['authorization_ref'],resource_safety=a['resource_safety_ref'],gate_safety=a['gate_safety_ref']);p['eligibility_refs']=eligibility
    plan['state_refs'].update(control=control['record_ref'],gate=p['gate_before']['record_ref'],authorization=a['authorization_ref'],resource=sc['resource_ref']);plan.update(selected_tick_ns='52',expires_tick_ns='69',basis=dict(kind='scope' if kind=='cancel' else 'gate_recovery',record_ref=S.eref(assessment) if assessment else Q.ref('recovery')));O.seal(plan,'plan_digest');O.seal(p,'proposal_digest')
    d['format_version']='gate-open-dispatch/0.3.0-draft.1';d.update(plan_ref=O.reference(plan,'plan_id','plan_digest'),reserved_tick_ns='53');d['frame'].update(journal_mode='durable',ipc_version=M.IPC['$defs']['S9__OPEN_GATE']['properties']['ipc_version']['const'],body=clone(b));d['frame'].update({k:a['binding'][k] for k in O.FRAME_BINDING});O.seal(d,'dispatch_digest')
    e['format_version']='gate-open-evidence/0.3.0-draft.1';e.update(plan_ref=d['plan_ref'],dispatch_ref=O.reference(d,'dispatch_id','dispatch_digest'),received_tick_ns='54');e['frame'].update(journal_mode='durable',ipc_version=d['frame']['ipc_version']);e['frame'].update({k:a['binding'][k] for k in O.FRAME_BINDING});e['frame']['body'].update(gate_access_ref=S.aref(a),reference_time_snapshot_ref=dict(id=b['reference_time_snapshot']['snapshot_id'],revision=b['reference_time_snapshot']['snapshot_revision'],digest=b['reference_time_snapshot']['snapshot_digest']));O.seal(e,'evidence_digest')
    after=clone(control);after.update(record_ref=Q.ref('control.after',int(control['record_ref']['revision'])+1),gate_state='ready' if kind=='ordinary' else 'protected');gate=clone(p['gate_before']);gate.update(record_ref=Q.ref('gate.after',int(gate['record_ref']['revision'])+1),phase='ready' if kind=='ordinary' else 'scoped',activation_id='adopt')
    t=O.seal(dict(format_version='gate-open-adoption/0.3.0-draft.1',commit_id='adopt',revision='1',purpose=a['purpose'],proposal_ref=M.proposal_ref(p),dispatch_ref=O.reference(d,'dispatch_id','dispatch_digest'),evidence_ref=O.reference(e,'evidence_id','evidence_digest'),gate_access_ref=S.aref(a),protection_assessment_ref=S.eref(assessment) if assessment else None,eligibility_refs=eligibility,control_after=after,gate_after=gate,committed_tick_ns='55'),'adoption_digest')
    holds=[dict(hold_ref=r['hold_ref'],owner_ref=r['ownership_ref'],control_authority_ref=a['control_authority_ref'],state=r['classification']) for r in sc['risk_observations']] if kind=='ordinary' else []
    safety=c['stored_resource_evidence'];safety.update(observed_resource_ref=sc['resource_ref'],resource_safety_ref=a['resource_safety_ref'],control_authority_ref=a['control_authority_ref'],holds=holds);O.seal(safety,'evidence_digest')
    c.update(binding=a['binding'],state_refs=plan['state_refs'],basis=plan['basis'],stored_plan=plan,stored_proposal=p,stored_dispatch=d,stored_evidence=e,stored_adoption=t,control_projection=control,gate_projection=p['gate_before'],eligibility_refs=eligibility,scope_context=sc,current_assessment=assessment,current_holds=holds,adoption_committed=False,received_ack=e['frame'],observer_received_tick_ns='54',snapshots={k:b[k] for k in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot')})
    c['control']={k:b[k] for k in ('control_epoch','control_version','gate_revision','authorization_revision','gate_token','barrier_id')}
    return json.loads(json.dumps([p,d,e,t,c]))
def post(values):
    p,d,e,t,c=clone(values);c.update(adoption_committed=True,control_projection=clone(t['control_after']),gate_projection=clone(t['gate_after']));c['state_refs'].update(control=clone(t['control_after']['record_ref']),gate=clone(t['gate_after']['record_ref']));c['scope_context']['control_projection']=clone(t['control_after']);return p,d,e,t,c
def run():
    assert (HERE/'open-contract.schema.json').read_bytes()==G.encoded();Draft202012Validator.check_schema(G.build())
    checks=[]
    def check(name,actual,expected=None):assert actual==expected,(name,actual,expected);checks.append(dict(name=name,passed=True))
    def evaluate(values,stage=3,now=55):
        p,d,e,t,c=values;return (lambda:M.proposal_error(p,c,now),lambda:M.dispatch_error(d,p,c,now),lambda:M.evidence_error(e,d,p,c,now),lambda:M.adoption_error(t,e,d,p,c,now))[stage]()
    def bad(name,fn,expected,kind='ordinary',stage=3):
        v=fixture(kind);fn(*v);check(name,evaluate(v,stage),expected)
    def after(name,fn,expected,kind='ordinary',now=55):
        p,d,e,t,c=post(fixture(kind));fn(p,d,e,t,c);check(name,M.current_error(t,p,c,now),expected)
    for kind in ('ordinary','cancel'):
        values=fixture(kind)
        for n,v in zip(('OpenProposal','OpenDispatch','OpenAckEvidence','OpenAdoption'),values):check(kind+':结构:'+n,M.valid(n,v),True)
        for stage in range(4):check(kind+':关联阶段:'+str(stage),evaluate(values,stage))
        p,d,e,t,c=post(values);check(kind+':提交后资格',M.current_error(t,p,c,55))
        check(kind+':用途与控制状态',(t['control_after']['gate_state'],t['gate_after']['phase']),('ready','ready') if kind=='ordinary' else ('protected','scoped'))
        for tick,expected in [(54,'expired'),(55,None),(68,None),(69,'expired')]:check(kind+':当前期限:'+str(tick),M.current_error(t,p,c,tick),expected)
        after(kind+':提交未确认',lambda p,d,e,t,c:c.update(adoption_committed=False),'not_committed',kind)
        after(kind+':原ACK未持久',lambda p,d,e,t,c:c.update(ack_durable=False),'not_committed',kind)
        after(kind+':接管改变持有人',lambda p,d,e,t,c:c['control_projection']['holder'].update(principal_id='other'),'post_state_changed',kind)
        after(kind+':原件身份不能换',lambda p,d,e,t,c:c['gate_projection']['record_ref'].update(id='other'),'post_state_changed',kind)
        for flag in ('storage_healthy','runtime_current','basis_valid','barrier_valid','authority_current'):
            bad(kind+':提交前失效:'+flag,lambda p,d,e,t,c,f=flag:c.update({f:False}),'unavailable',kind)
            after(kind+':提交后失效:'+flag,lambda p,d,e,t,c,f=flag:c.update({f:False}),'unavailable',kind)
        for role in ('authorization','resource_safety','gate_safety','control_authority'):
            bad(kind+':资格修订改变:'+role,lambda p,d,e,t,c,r=role:c['eligibility_refs'].update({r:Q.ref('changed')}),'eligibility_changed',kind)
        for key in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot'):
            after(kind+':快照更新:'+key,lambda p,d,e,t,c,k=key:c['snapshots'][k].update(snapshot_revision='99'),'snapshot_changed',kind)
    bad('旧OPEN缺GateAccess不再可用',lambda p,d,e,t,c:p['plan']['body'].pop('gate_access'),'schema',stage=0)
    bad('旧IPC发送帧拒绝',lambda p,d,e,t,c:d['frame'].update(journal_mode='durable',ipc_version='ipc/0.8.0-reference-time-draft.1'),'schema',stage=1)
    bad('旧ACK缺Access引用拒绝',lambda p,d,e,t,c:e['frame']['body'].pop('gate_access_ref'),'schema',stage=2)
    bad('限定用途不得提交普通Ready',lambda p,d,e,t,c:t['control_after'].update(gate_state='ready'),'schema','cancel')
    bad('普通用途不得携带评估',lambda p,d,e,t,c:p['plan']['body'].update(protection_assessment=fixture('cancel')[0]['plan']['body']['protection_assessment']),'schema',stage=0)
    bad('限定用途不能缺评估',lambda p,d,e,t,c:p['plan']['body'].update(protection_assessment=None),'schema','cancel',0)
    def wrong_echo(p,d,e,t,c):
        e['frame']['body']['gate_access_ref']=Q.ref('other');O.seal(e,'evidence_digest');c['received_ack']=clone(e['frame'])
    bad('ACK回显错误Access',wrong_echo,'ack_access',stage=2)
    def reseal_t(t,c):O.seal(t,'adoption_digest');c['stored_adoption']=clone(t)
    bad('不能把Plan摘要冒充Proposal',lambda p,d,e,t,c:(t.update(proposal_ref=d['plan_ref']),reseal_t(t,c)),'adoption_proposal')
    for key in ('control_after','gate_after'):
        bad('物理原件必须新ID:'+key,lambda p,d,e,t,c,k=key:(t[k]['record_ref'].update(id=p['control_before' if k=='control_after' else 'gate_before']['record_ref']['id']),reseal_t(t,c)),'storage_successor')
        bad('修订必须精确后继:'+key,lambda p,d,e,t,c,k=key:(t[k]['record_ref'].update(revision='99'),reseal_t(t,c)),'storage_successor')
    bad('开放不转交控制权',lambda p,d,e,t,c:(t['control_after']['holder'].update(principal_id='other'),reseal_t(t,c)),'control_transfer')
    bad('Access提供者与计划资格脱节',lambda p,d,e,t,c:c['scope_context'].update(gate_safety_ref=Q.ref('other')),'scope_context_eligibility',stage=0)
    bad('硬保护不能由普通资格覆盖',lambda p,d,e,t,c:c['scope_context'].update(hard_protection_reasons=['fault']),'hard_protection',stage=0)
    bad('限定用途全关闭后不再可用',lambda p,d,e,t,c:c['scope_context'].update(all_closed=True),'closure','cancel',0)
    bad('限定用途非父命令风险拒绝',lambda p,d,e,t,c:c['scope_context']['risk_hold_ids'].append('unrelated'),'risk_set','cancel',0)
    after('Access撤回取消当前资格',lambda p,d,e,t,c:c['scope_context']['revoked_refs'].append(S.aref(p['plan']['body']['gate_access'])),'revoked')
    after('限定评估撤回取消资格',lambda p,d,e,t,c:c['scope_context']['revoked_refs'].append(S.eref(c['current_assessment'])),'revoked','cancel')
    for kind in ('ordinary','cancel'):
        after(kind+':当前采用仍核发送引用',lambda p,d,e,t,c:(t.update(dispatch_ref=Q.ref('other')),reseal_t(t,c)),'chain_ref',kind)
        after(kind+':当前采用仍核证据引用',lambda p,d,e,t,c:(t.update(evidence_ref=Q.ref('other')),reseal_t(t,c)),'chain_ref',kind)
        after(kind+':当前发送原件摘要损坏',lambda p,d,e,t,c:c['stored_dispatch'].update(reserved_tick_ns='51'),'chain_digest',kind)
        after(kind+':当前ACK原件缺持久模式',lambda p,d,e,t,c:c['stored_evidence']['frame'].pop('journal_mode'),'chain_schema',kind)
        after(kind+':当前采用不可早于ACK',lambda p,d,e,t,c:(t.update(committed_tick_ns='53'),reseal_t(t,c)),'chain_time',kind)
        after(kind+':当前闸采用ID须关联',lambda p,d,e,t,c:(t['gate_after'].update(activation_id='other'),reseal_t(t,c)),'chain_transition',kind)
    after('限定初始评估引用不可更换',lambda p,d,e,t,c:(t.update(protection_assessment_ref=Q.ref('other')),reseal_t(t,c)),'chain_assessment','cancel')
    def altered_ack(p,d,e,t,c):
        original=c['stored_evidence'];original['frame']['body']['gate_token']='other';O.seal(original,'evidence_digest');t['evidence_ref']=O.reference(original,'evidence_id','evidence_digest');reseal_t(t,c)
    after('ACK重算摘要仍不能改变回显',altered_ack,'chain_echo')
    bad('ACK尚未持久不得采用',lambda p,d,e,t,c:c.update(ack_durable=False),'ack_not_durable')
    bad('接收观察身份未验证',lambda p,d,e,t,c:c.update(observer_verified=False),'observer',stage=2)
    for tick,expected in [(51,'access_plan_window'),(52,None),(68,None),(69,'access_plan_window')]:check('计划时间边界:'+str(tick),evaluate(fixture(),0,tick),expected)
    check('根Schema不直接接收对象',Draft202012Validator(G.build(),registry=M.REGISTRY).is_valid(fixture()[0]),False)
    examples={kind:dict(zip(('proposal','dispatch','evidence','adoption'),fixture(kind)[:4])) for kind in ('ordinary','cancel')}
    assert json.loads((HERE/'open-contract-examples.json').read_bytes())==examples
    return checks
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--examples',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    if a.examples:
        examples={kind:dict(zip(('proposal','dispatch','evidence','adoption'),fixture(kind)[:4])) for kind in ('ordinary','cancel')};(HERE/'open-contract-examples.json').write_bytes((json.dumps(examples,ensure_ascii=False,indent=2)+'\n').encode())
    elif a.check_report:
        hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};assert json.loads((HERE/'open-contract-report.json').read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};v=dict(all_passed=True,approved=False,cases_passed=len(checks),current_ipc_contract_verified=True,sqlite_integration_verified=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:(HERE/'open-contract-report.json').write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:x for k,x in v.items() if k not in ('checks','inputs')}))
