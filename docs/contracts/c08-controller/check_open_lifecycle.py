"""开放提交前后引用及资源仲裁候选；仅合成快照与原子副本，不执行SQLite或设备。"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
import build_open_lifecycle as G
import check_open_plan as P
import open_lifecycle_model as M
O=P.M;HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(P.INPUTS+[HERE/n for n in ('OPEN_LIFECYCLE.md','build_open_lifecycle.py',
 'open_lifecycle_model.py','check_open_lifecycle.py','open-lifecycle.schema.json')]))
def ref(name,revision=1):return dict(id=name,revision=str(revision),digest=O.digest([name,revision]))
def fixture():
    p,d,e,r,c=P.fixture()
    er=dict(control_authority=ref('authority'),resource_safety=ref('safety'),authorization=p['state_refs']['authorization'])
    control=dict(record_ref=p['state_refs']['control'],authority_ref=er['control_authority'],control_epoch='control.epoch',
      effective_version='2',mode='manual',holder=dict(issuer_id='issuer',issuer_epoch='epoch',principal_id='bob'),pending_operation_id=None,gate_state='protected')
    gate=dict(record_ref=p['state_refs']['gate'],binding=p['binding'],gate_revision='3',gate_token='gate.token',barrier_id='barrier',
      phase='fenced',ready_activation_id=None,lease_until_tick_ns='100')
    proposal=O.seal(dict(format_version='gate-open-plan/0.2.0-draft.1',plan=p,eligibility_refs=er,
      control_before=control,gate_before=gate),'proposal_digest')
    ac=copy.deepcopy(control);ac.update(record_ref=ref('control',2),gate_state='ready')
    ag=copy.deepcopy(gate);ag.update(record_ref=ref('gate',2),phase='ready',ready_activation_id='ready')
    transition=O.seal(dict(format_version='gate-ready-transition/0.2.0-draft.1',ready=r,
      proposal_ref=dict(id=p['plan_id'],revision='1',digest=proposal['proposal_digest']),
      control_after=ac,gate_after=ag,eligibility_refs=er),'transition_digest')
    safety=O.seal(dict(evidence_id='resource.evidence',revision='1',device_id='device',observed_resource_ref=p['state_refs']['resource'],
      resource_safety_ref=er['resource_safety'],control_authority_ref=er['control_authority'],holds=[],provider_receipt_ref=ref('resource.provider')),'evidence_digest')
    c.update(eligibility_refs=er,control_projection=control,gate_projection=gate,stored_proposal=proposal,stored_transition=transition,
      stored_resource_evidence=safety,resource_provider_receipt_ref=safety['provider_receipt_ref'],current_holds=[],ready_transaction_committed=False)
    return json.loads(json.dumps([proposal,d,e,transition,c]))

def resource_update(context,holds,revision=2,safety_revision=None):
    context['state_refs']['resource']=ref('resource',revision)
    if safety_revision is not None:context['eligibility_refs']['resource_safety']=ref('safety',safety_revision)
    context['current_holds']=copy.deepcopy(holds)
    evidence=context['stored_resource_evidence'];evidence['evidence_id']='resource.evidence.'+str(revision)
    evidence.update(observed_resource_ref=copy.deepcopy(context['state_refs']['resource']),resource_safety_ref=copy.deepcopy(context['eligibility_refs']['resource_safety']),
        holds=copy.deepcopy(holds),provider_receipt_ref=ref('resource.provider',revision))
    O.seal(evidence,'evidence_digest');context['resource_provider_receipt_ref']=copy.deepcopy(evidence['provider_receipt_ref'])

def run():
    assert (HERE/'open-lifecycle.schema.json').read_bytes()==G.encoded(),'生成漂移'
    schemas=[G.build(),P.G.build(),json.loads(P.G.IPC.read_bytes())]
    for s in schemas:Draft202012Validator.check_schema(s)
    registry=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in schemas])
    def valid(name,v):return Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=registry).is_valid(v)
    checks=[]
    def check(name,value,expected):
        assert value==expected,(name,value,expected)
        checks.append(dict(name=name,observed=copy.deepcopy(value),expected=copy.deepcopy(expected)))
    def evaluate(values,now=50):
        p,d,e,t,c=values
        if not all(valid(n,v) for n,v in [('OpenPlanV02',p),('ReadyTransition',t),('ResourceSafetyEvidence',c['stored_resource_evidence'])]):return 'schema'
        return M.transition_error(t,e,d,p,c,now)
    def before(name,mutate,expected,now=50):
        values=fixture();mutate(*values);check(name,evaluate(values,now),expected)
    def adopted():
        p,d,e,t,c=fixture();c,error=M.publish(t,e,d,p,c,50);assert error is None
        return p,d,e,t,c
    def after(name,mutate,expected,now=50):
        p,d,e,t,c=adopted();mutate(p,d,e,t,c);check(name,M.current_error(t,p,c,now),expected)
    def seal_transition(t,c):O.seal(t,'transition_digest');c['stored_transition']=copy.deepcopy(t)
    check('原子写集完整关联',evaluate(fixture()),None)
    p,d,e,t,c=adopted()
    check('提交后新ControlRecord不使自身ready失效',M.current_error(t,p,c,50),None)
    check('旧模型重用前态比较确实自失效',O.ready_error(t['ready'],e,d,p['plan'],c,50),'state_changed')
    check('提交后不能重跑提交前检查',M.proposal_error(p,c,50),'projection_changed')
    check('正常T5不转交控制权',M.key(c['control_projection'])==M.key(p['control_before']),True)
    for field in ('control_authority','resource_safety','authorization'):
        before('提交前资格改变:'+field,lambda p,d,e,t,c,f=field:c['eligibility_refs'].update({f:ref(f,9)}),'eligibility_changed')
        after('提交后资格改变:'+field,lambda p,d,e,t,c,f=field:c['eligibility_refs'].update({f:ref(f,9)}),'eligibility_changed')
    for field in ('control','gate','resource','authorization'):
        before('输入完整Ref的CAS:'+field,lambda p,d,e,t,c,f=field:c['state_refs'].update({f:ref(f,9)}),
          'resource_snapshot' if field=='resource' else 'state_changed')
    for field in ('control_epoch','effective_version','mode','holder','pending_operation_id'):
        values={'control_epoch':'other','effective_version':'3','mode':'automatic','holder':None,'pending_operation_id':'pending'}
        after('实际控制事实改变:'+field,lambda p,d,e,t,c,f=field:c['control_projection'].update({f:values[f]}),'control_changed')
    for field in ('controller_boot_id','worker_boot_id','writer_exit_id','ipc_session_id','device_session_id','clock_domain_id','descriptor_digest'):
        after('当前绑定改变:'+field,lambda p,d,e,t,c,f=field:c['binding'].update({f:'other'}),'binding')
    for field in ('phase','gate_token','gate_revision','barrier_id','ready_activation_id','lease_until_tick_ns'):
        after('闸记录改变:'+field,lambda p,d,e,t,c,f=field:c['gate_projection'].update({f:'other'}),'gate_changed')
    def control_ref(c,value):
        c['control_projection']['record_ref']=copy.deepcopy(value);c['state_refs']['control']=copy.deepcopy(value)
    after('仅公开投影修订更新不撤销控制权',lambda p,d,e,t,c:control_ref(c,ref('control',3)),None)
    for value in (ref('other.control',3),ref('control',1),dict(ref('control',2),digest=O.digest('different'))):
        after('控制历史身份或修订错配:'+value['id']+value['revision'],lambda p,d,e,t,c,v=value:control_ref(c,v),'control_history')
    for field in ('control','gate','authorization'):
        after('当前引用提供者不能脱节:'+field,lambda p,d,e,t,c,f=field:c['state_refs'].update({f:ref('wrong',3)}),'current_refs')
    after('公开投影不能把闸隐藏成保护',lambda p,d,e,t,c:c['control_projection'].update(gate_state='protected'),'control_not_ready')
    for field in ('storage_healthy','runtime_current','authority_current','basis_valid','barrier_valid'):
        after('实际提供者失效:'+field,lambda p,d,e,t,c,f=field:c.update({f:False}),'unavailable')
    after('当前有保护不能ready',lambda p,d,e,t,c:c.update(protected=True),'unavailable')
    for tick,expected in ((39,'expired'),(40,None),(89,None),(90,'expired'),(100,'expired')):
        after('发布期限边界:'+str(tick),lambda *v:None,expected,now=tick)
    for name in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot'):
        def change(p,d,e,t,c,n=name):
            c['snapshots'][n]['snapshot_revision']='9';O.seal(c['snapshots'][n],'snapshot_digest')
        after('重算新快照不能延用ready:'+name,change,'snapshot_changed')
    for field in ('control_after','gate_after'):
        for value in ('1','3',str(10**20)):
            def bad(p,d,e,t,c,f=field,v=value):t[f]['record_ref']['revision']=v;seal_transition(t,c)
            before('输出修订严格后继:'+field+value,bad,'schema' if value==str(10**20) else 'projection_successor')
        before('输出必须新摘要:'+field,lambda p,d,e,t,c,f=field:(t[f]['record_ref'].update(digest=p['control_before' if f=='control_after' else 'gate_before']['record_ref']['digest']),seal_transition(t,c)),'projection_successor')
    before('T5不得改变holder',lambda p,d,e,t,c:(t['control_after']['holder'].update(principal_id='other'),seal_transition(t,c)),'control_transition')
    before('T5不得改变gate修订',lambda p,d,e,t,c:(t['gate_after'].update(gate_revision='4'),seal_transition(t,c)),'gate_transition')
    before('gate只带ready原始身份防循环引用',lambda p,d,e,t,c:(t['gate_after'].update(ready_activation_id='other'),seal_transition(t,c)),'gate_activation')
    before('不得把旧Plan摘要当新包络Ref',lambda p,d,e,t,c:(t.update(proposal_ref=O.reference(p['plan'],'plan_id','plan_digest')),seal_transition(t,c)),'proposal_ref')
    before('ACK未持久不能提交',lambda p,d,e,t,c:c.update(ack_durable=False),'not_committed')
    before('接收器未验证不能提交',lambda p,d,e,t,c:c.update(observer_verified=False),'observer')
    # 正常在途占用属于当前控制权，既不等于安全故障，也不免除命令级资源仲裁。
    hold=dict(hold_ref=ref('hold'),owner_ref=ref('command'),control_authority_ref=ref('authority'),state='active')
    after('正常当前命令占用保持ready',lambda p,d,e,t,c:resource_update(c,[hold]),None)
    after('正常取消与父命令占用可共存',lambda p,d,e,t,c:resource_update(c,[hold,dict(hold,hold_ref=ref('cancel.hold'),owner_ref=ref('cancellation'))]),None)
    for state in ('unknown','failed_unresolved','orphaned','proof_revoked'):
        after('异常占用不借正常分配豁免:'+state,lambda p,d,e,t,c,s=state:resource_update(c,[dict(hold,state=s)]),'resource_blocked')
    after('旧持有人未决占用不能称正常',lambda p,d,e,t,c:resource_update(c,[dict(hold,control_authority_ref=ref('previous.authority'))]),'resource_blocked')
    after('当前全集不可漏隐藏hold',lambda p,d,e,t,c:c['current_holds'].append(hold),'resource_hold_set')
    after('当前全集不可重复hold',lambda p,d,e,t,c:resource_update(c,[hold,hold]),'resource_hold_set')
    after('提供者Ref不能伪造',lambda p,d,e,t,c:c.update(resource_provider_receipt_ref=ref('forged')),'resource_provider')
    after('只更新分配Ref而不重取全集拒绝',lambda p,d,e,t,c:c['state_refs'].update(resource=ref('resource',2)),'resource_snapshot')
    p,d,e,t,c=adopted();resource_update(c,[hold]);resource_update(c,[],revision=3)
    check('正常占用释放不需重开闸',M.current_error(t,p,c,60),None)
    resource_update(c,[],revision=4,safety_revision=2)
    check('故障恢复即使再次无占用也不复活旧ready',M.current_error(t,p,c,60),'eligibility_changed')
    for result in ('failed','unknown'):
        p,d,e,t,c=fixture();new,error=M.publish(t,e,d,p,c,50,commit_result=result)
        check('提交结果:'+result,error,'commit_failed' if result=='failed' else 'commit_uncertain')
        check('不可靠提交保持保护:'+result,new['protected'],True)
        check('不可靠提交不替换原控制:'+result,new['control_projection']==c['control_projection'],True)
    for cut in range(3):
        p,d,e,t,c=fixture();new,error=M.publish(t,e,d,p,c,50,fault=cut)
        check('副本写集故障:'+str(cut),error,'rollback');check('副本写集全量未变:'+str(cut),new==c,True)
    p,d,e,t,c=fixture();new,error=M.publish(t,e,d,p,c,50,visible_tick=90)
    check('COMMIT跨截止保留历史但不发布ready',error,'expired')
    check('历史提交仍可查',new['ready_transaction_committed'],True)
    p,d,e,t,c=fixture();new,error=M.publish(t,e,d,p,c,50,visible_tick=49)
    check('COMMIT发布时单调时钟回退拒绝',error,'clock_regressed')
    check('时钟异常保留已提交历史',new['ready_transaction_committed'],True)
    check('时钟异常立即保护',new['protected'],True)
    p,d,e,t,c=fixture();new,error=M.publish(t,e,d,p,c,50,visible_tick=50)
    check('发布时刻等于校验时刻允许',error,None)
    p,d,e,t,c=adopted();new,error=M.publish(t,e,d,p,c,50)
    check('重复提交不生成第二次状态转换',error,'projection_changed');check('重复提交完整状态不变',new==c,True)
    check('伪造全部可信上下文可通过仅为模型限制',evaluate(fixture()),None)
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    target=HERE/'open-lifecycle-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),scope='开放提交前后引用及资源安全代次候选',
          runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,sqlite_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
