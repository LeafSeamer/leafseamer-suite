"""稳定授权状态与短期证据续约的纯契约正反例；不运行身份提供者。"""
import argparse,copy,hashlib,json
from pathlib import Path
from jsonschema.exceptions import ValidationError
import check_open_authorization as F
import device_authorization_model as M
HERE=M.B.HERE;ROOT=HERE.parents[2]
def context(mode='manual',purpose='ordinary'):
    q=F.fixture(mode,purpose);lineage=dict(principal=copy.deepcopy(q['holder'] or F.fixture()['holder']),principal_kind='human',credential_id='credential',session_id='session',subject_revision='4',session_revision='4',policy_revision='2',scope_digest=F.reference('scope')['digest'])
    evaluator=copy.deepcopy(lineage);evaluator.update(principal_kind='service',session_id=None,session_revision=None);evaluator['principal']['principal_id']='controller'
    return dict(scope=q['binding']['scope'],device_id=q['binding']['device_id'],control_authority_ref=q['control_authority_ref'],control_epoch='epoch.control',control_version='2',
        mode=mode,holder=q['holder'],purpose=purpose,evaluator_lineage=evaluator,evaluator_policy_ref=q['evaluator']['policy_ref'],device_scope_ref=F.reference('device.scope'),
        holder_lineage=lineage if mode=='manual' and purpose=='ordinary' else None,cancel_scope_ref=q['cancel_evidence']['protection_scope_ref'] if purpose=='cancel_only' else None,
        cancel_lineage_ref=F.reference('cancel.lineage') if purpose=='cancel_only' else None)
def recovery(initial,binding):
    return M.seal(dict(format_version='device-recovery-authorization/0.1.0-draft.1',authorization_id='revalidation',revision='1',operation_id='recovery.operation',request_receipt_ref=F.reference('request.receipt'),
        binding=copy.deepcopy(binding),protected_state_ref=M.reference(initial,'state'),control_authority_ref=initial['context']['control_authority_ref'],
        requester=F.fixture()['holder'],requester_kind='human',purpose='revalidate_device_authorization',proposed_context_digest=F.M.digest(initial['context']),evidence_refs=[F.reference('authorized.request')],issued_tick_ns='5',expires_tick_ns='20'),'authorization_digest')
def fixture(mode='manual',purpose='ordinary'):
    c=context(mode,purpose);initial=M.transition(None,c,'protected',['initial']);binding=F.fixture(mode,purpose)['binding'];s=M.revalidate(initial,c,recovery(initial,binding),binding,'10')
    q=F.fixture(mode,purpose);q['authorization_state_ref']=M.reference(s,'state');F.M.seal(q)
    refs={'evaluator':q['evaluator']['authority_response_ref']}
    if purpose=='cancel_only':refs['cancel']=q['cancel_evidence']['cancel_authorization_ref']
    elif mode=='manual':refs['holder']=q['holder_evidence']['response_ref']
    e=M.seal(dict(format_version='device-authorization-evidence/0.1.0-draft.1',evidence_id='evidence',revision='1',state_ref=M.reference(s,'state'),requirement=q,
        context_digest=F.M.digest(c),windows=[dict(role=role,evidence_ref=refs[role],not_before_tick_ns='10',before_tick_ns='20') for role in sorted(refs)]),'evidence_digest')
    return initial,s,e
def refreshed(e):
    v=copy.deepcopy(e);v['evidence_id']='evidence.next';q=v['requirement'];q.update(requirement_id='requirement.next',selected_tick_ns='15',expires_tick_ns='25')
    q['evaluator']['authority_response_ref']=F.reference('response.next.evaluator')
    if q['holder_evidence']:q['holder_evidence']['response_ref']=F.reference('response.next.holder')
    if q['cancel_evidence']:q['cancel_evidence']['cancel_authorization_ref']=F.reference('response.next.cancel')
    for w in v['windows']:w.update(evidence_ref=F.reference('response.next.'+w['role']),before_tick_ns='25')
    F.M.seal(q);return M.seal(v,'evidence_digest')
def inputs():return list(dict.fromkeys(F.inputs()+[HERE/n for n in ('build_device_authorization.py','device-authorization.schema.json','device_authorization_model.py','check_device_authorization.py')]+[ROOT/'docs/rebirth-df06-internal-trust-design.md']))
def run():
    checks=[]
    def check(name,condition=True):
        if not condition:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError) as e:check(name,reason is None or reason in str(e));return
        raise AssertionError('未拒绝:'+name)
    check('Schema生成字节一致',(HERE/'device-authorization.schema.json').read_bytes()==M.B.encoded())
    for mode in ('manual','automatic'):
        for purpose in ('ordinary','cancel_only'):
            initial,s,e=fixture(mode,purpose);next_e=refreshed(e);before=copy.deepcopy(s)
            check('四分支完整取证结构/'+mode+'/'+purpose,M.evidence(s,e,'10') is None)
            check('有效窗口内刷新不变设备修订/'+mode+'/'+purpose,M.renewal(s,e,next_e,'15') is None and s==before)
            check('短期新响应有新证据身份/'+mode+'/'+purpose,e!=next_e and e['state_ref']==next_e['state_ref'])
            denied('到期等号不能续约/'+mode+'/'+purpose,lambda:M.renewal(s,e,next_e,'20'),'requirement_window')
            protected=M.transition(s,s['context'],'protected',['evidence_expired'])
            denied('新证据不能复活已保护状态/'+mode+'/'+purpose,lambda:M.evidence(protected,next_e,'20'),'state_protected')
            denied('恢复不能只有新响应/'+mode+'/'+purpose,lambda:M.transition(protected,s['context'],'policy_selected',[]),'recovery_required')
    initial,s,e=fixture();c=s['context'];fresh=refreshed(e)
    binding=e['requirement']['binding'];authorization=recovery(initial,binding)
    check('恢复授权不引用新状态或恢复快照',authorization['protected_state_ref']==M.reference(initial,'state') and s['recovery_ref']==M.reference(authorization,'authorization'))
    denied('恢复授权到期等号拒绝',lambda:M.revalidate(initial,c,authorization,binding,'20'),'revalidation_window')
    denied('恢复授权未来时刻拒绝',lambda:M.revalidate(initial,c,authorization,binding,'4'),'revalidation_window')
    for label,field in [('错误原保护状态','protected_state_ref'),('错误控制权','control_authority_ref')]:
        bad=copy.deepcopy(authorization);bad[field]=F.reference('other');bad=M.seal(bad,'authorization_digest');denied('恢复/'+label,lambda:M.revalidate(initial,c,bad,binding,'10'))
    denied('恢复不能跨worker绑定',lambda:M.revalidate(initial,c,authorization,dict(binding,worker_boot_id='other'),'10'),'revalidation_binding')
    denied('恢复授权不能用于另一策略上下文',lambda:M.revalidate(initial,dict(c,device_scope_ref=F.reference('other.scope')),authorization,binding,'10'),'revalidation_context')
    check('状态修订使用独立ID',initial['state_id']!=s['state_id'])
    check('重复语义选择不增加修订',M.transition(s,c,'policy_selected',[])==s)
    check('重复证据只查相同正文',M.renewal(s,e,e,'15') is None)
    denied('初始化不能直接选择开放策略',lambda:M.transition(None,c,'policy_selected',[]),'initial_protected')
    denied('初始保护不接收伪恢复',lambda:M.transition(None,c,'protected',['initial'],recovery_ref=F.reference('recovery')),'initial_protected')
    for label,mutate in [('持有人凭证轮换',lambda v:v['holder_lineage'].update(credential_id='rotated')),
        ('人员会话轮换',lambda v:v['holder_lineage'].update(session_id='rotated')),
        ('当前主体修订变化',lambda v:v['holder_lineage'].update(subject_revision='5')),
        ('内部策略变化',lambda v:v.update(evaluator_policy_ref=F.reference('new.policy'))),
        ('设备范围变化',lambda v:v.update(device_scope_ref=F.reference('new.scope'))),
        ('控制版本变化',lambda v:v.update(control_version='3'))]:
        changed=copy.deepcopy(c);mutate(changed)
        denied('语义变化必须先保护/'+label,lambda:M.transition(s,changed,'policy_selected',[],recovery_ref=F.reference('new.recovery')),'semantic_change_requires_protection')
        blocked=M.transition(s,changed,'protected',['scope_changed']);check('保护消费后继修订/'+label,int(blocked['revision'])==int(s['revision'])+1 and blocked['parent_ref']==M.reference(s,'state'))
    denied('跨设备不能沿用状态链',lambda:M.transition(s,dict(c,device_id='other'),'protected',['control_changed']),'state_target')
    blocked=M.transition(s,c,'protected',['revoked']);resumed=M.transition(blocked,c,'policy_selected',[],recovery_ref=F.reference('fresh.recovery'))
    check('恢复继续递增而非回用原修订',resumed['revision']=='4')
    denied('恢复后旧证据Ref不能复用',lambda:M.evidence(resumed,e,'15'),'evidence_state')
    maximum=copy.deepcopy(s);maximum['revision']=str(M.MAX);maximum['state_id']=M.state_id(c,maximum['revision']);maximum['parent_ref'].update(revision=str(M.MAX-1),id=M.state_id(c,str(M.MAX-1)));maximum=M.seal(maximum,'state_digest')
    denied('修订耗尽不能回绕',lambda:M.transition(maximum,c,'protected',['revoked']),'state_revision_exhausted')
    for label,mutate,reason in [
        ('更换上下文投影',lambda v:v.update(context_digest=F.M.digest('other')),'evidence_context'),
        ('删人员窗口',lambda v:v.update(windows=[v['windows'][0]]),'evidence_window_roles'),
        ('重复窗口',lambda v:v['windows'].append(copy.deepcopy(v['windows'][0])),'evidence_window_roles'),
        ('借另一响应窗口',lambda v:v['windows'][0].update(evidence_ref=F.reference('other')),'evidence_window_source'),
        ('夸大认证有效期',lambda v:v['windows'][0].update(before_tick_ns='19'),'evidence_window'),
        ('尚未有效的来源',lambda v:v['windows'][0].update(not_before_tick_ns='11'),'evidence_window'),
        ('旧授权状态',lambda v:v['state_ref'].update(revision='1'),'evidence_state')]:
        bad=copy.deepcopy(e);mutate(bad);bad=M.seal(bad,'evidence_digest');denied('取证边界/'+label,lambda:M.evidence(s,bad,'15'),reason)
    for field in ('worker_boot_id','controller_boot_id','device_session_id','ipc_session_id','writer_exit_id','descriptor_digest'):
        bad=copy.deepcopy(fresh);bad['requirement']['binding'][field]=F.reference('other')['digest'] if field=='descriptor_digest' else 'other'
        F.M.seal(bad['requirement']);bad=M.seal(bad,'evidence_digest');denied('刷新不跨运行绑定/'+field,lambda:M.renewal(s,e,bad,'15'),'renewal_binding')
    bad=copy.deepcopy(fresh);bad['requirement']['evaluator']['runtime_ref']=F.reference('other.runtime');F.M.seal(bad['requirement']);bad=M.seal(bad,'evidence_digest')
    denied('内部评估器重启不能当普通刷新',lambda:M.renewal(s,e,bad,'15'),'renewal_runtime')
    bad=copy.deepcopy(fresh);bad['requirement']['requirement_id']=e['requirement']['requirement_id'];F.M.seal(bad['requirement']);bad=M.seal(bad,'evidence_digest')
    denied('需求身份不允许异内容复用',lambda:M.renewal(s,e,bad,'15'),'renewal_requirement_identity')
    check('孤立证据格式可过但不得绕过续约入口',M.evidence(s,fresh,'20') is None)
    return dict(all_passed=True,approved=False,cases_passed=len(checks),checks=checks,stable_revision_refresh_verified=True,expiry_requires_recovery_verified=True,
        authority_sources_verified=False,sqlite_adoption_verified=False,gate_renewal_ipc_executed=False,full_open_verified=False,device_tests_executed=0,
        inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'device-authorization-report.json'
    if a.check_report:
        r=json.loads(path.read_bytes());assert r['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};print(json.dumps(dict(bindings_valid=True,inputs=len(r['inputs']),rerun=False)))
    else:
        r=run()
        if a.report:path.write_bytes(F.rfc8785.dumps(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
