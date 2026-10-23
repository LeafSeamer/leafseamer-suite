"""运行库存与整组动作占位准入；全部外部资格为公开合成输入。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_workload_budget as G
import check_source_budget as T
import check_recovery_budget as RB
A=T.A;P=T.P;R=T.R;I=T.I;C=T.C;F=T.F;FLOW=T.FLOW;AT=T.AT;B=T.B
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in ('WORKLOAD_BUDGET.md','check_workload_budget.py','seamer-workload-budget.sql')]))

def fixture(forecast=None):
    d,q,c,ts=T.fixture(arm=False,sql_factory=G.build)
    c['forecast'].update(forecast or {})
    A.reserve(d,q,c);AT.receive_all(d,ts);A.apply(d,lambda:A.complete_steps(d,q['operation_id'],c))
    return d,q,c,ts

def event(n):return dict(source_id='source',event_id='event.'+str(n),source_sequence=str(n),payload=dict(value=True))

def execute(d,c,n):
    F.receive_event(d,event(n),c);ex=FLOW.active(d);A.apply(d,lambda:F.anchor_steps(d,ex,c))
    for s in c['evaluations']['r0']['steps']:FLOW.success(d,ex,s['step_id'],c)
    F.finish(d,ex,c);return ex

def dependency(d,ex):
    return I('p1_dependency',dependency_id='dep.'+ex,sequence=d.execute('SELECT max(sequence)+1 FROM p1_dependency').fetchone()[0],source_id='source',run_id='r0',
        owner_kind='execution',owner_ref=ex,execution_id=ex,recovery_id=None,artifact_digest=AT.H,binding_body=T.T.B)

def recovery(d,c,ts):
    r=R.one(d,'run','run_id','r0');s=R.one(d,'activation_slot','definition_id','d0');rev=P.inc(r['revision'])
    C.execute(d,[("UPDATE run SET lifecycle='paused',dispatch_eligible=0,revision=? WHERE run_id='r0'",(rev,)),
        I('pause_latch',latch_id='resume.latch',run_id='r0',reason='operator_pause',created_revision=rev,body=AT.B),
        I('recovery_preview',preview_id='resume.preview',run_id='r0',run_revision=rev,slot_revision=s['revision'],prior_execution_id=r['active_execution_id'],
            preview_digest=AT.H,plan_digest='recovery.plan',preview_body=AT.B,clock_body=AT.B,issued_tick='100',expires_tick='200')])
    q=dict(operation_id='recovery.1',execution_id='recovery.execution',run_id='r0',preview_id='resume.preview',request_epoch='resume.epoch',
        actor=dict(principal_id='operator'),idempotency_key='resume.key',mode='reconcile_commit',kind='rule',plan_digest='recovery.plan',resolved_latches=['resume.latch'])
    gate=dict(authorized=True,current=True,old_resources_clear=True,clock_body=AT.B,now=150);ts=copy.deepcopy(ts)
    for t in ts:
        t['registration_id']='new.'+t['registration_id'];t['preparation_id']='new.'+t['preparation_id'];t['request_body']['preparation_id']=t['preparation_id']
    q['targets']=ts
    ctx=dict(c,**gate);ctx['forecast']=dict(c['forecast'],executions='9',preparations='4',dependencies='6')
    return q,ctx

def run():
    checks=[];dbs=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(**kw):
        v=fixture(**kw);dbs.append(v[0]);return v
    def denied(n,d,call,reason=None):
        before=C.snapshot(d)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError) as err:
            if reason:assert reason in str(err),(n,str(err),reason)
            check(n,C.snapshot(d)==before);return
        raise AssertionError(n)
    try:
        check('生成SQL字节',(HERE/'seamer-workload-budget.sql').read_bytes()==G.build())
        d,q,c,ts=f();check('106表加增长守卫',len(C.snapshot(d)),106)
        planned=AT.planned(d,lambda:F.ingress_steps(d,event(1),c))
        for i in range(len(planned)):
            denied('摄取增长写后故障'+str(i),d,lambda i=i:F.receive_event(d,event(1),c,fail_after=i),'injected')
        for n in range(1,9):
            ex=execute(d,c,n)
            shape=dict(d.execute('SELECT * FROM wb_shape').fetchone())
            check('双动作循环库存'+str(n),(shape['executions'],shape['submissions'],shape['controller_targets']),(n,2*n,2))
        denied('第九执行整体拒绝',d,lambda:F.receive_event(d,event(9),c),'workload_budget_exceeded')
        check('拒绝后摄取水位不跳过',R.one(d,'ingress_source','source_id','source')['contiguous_sequence'],'8')
        before=C.snapshot(d);F.receive_event(d,event(8),c);check('满额查原零写',C.snapshot(d)==before)
        check('满额仍有保护两份',d.execute('SELECT episodes_left FROM pb_balance').fetchone()[0],2)
        B.protect(d,C.fault('1'),c);check('满额拒绝后P1仍可保护',d.execute('SELECT episodes_left FROM pb_balance').fetchone()[0],1)
        # 只有一个submission余量时，两动作必须在任何动作可发送之前整体拒绝。
        d,q,c,ts=f(forecast=dict(submissions='1'))
        denied('两动作不能逐条争一个槽',d,lambda:F.receive_event(d,event(1),c),'workload_budget_exceeded')
        check('计划被拒绝尚无attempt',d.execute('SELECT count(*) FROM submission_attempt').fetchone()[0],0)
        check('计划被拒绝无半个execution',d.execute('SELECT count(*) FROM execution').fetchone()[0],0)
        # 同一目标的多个动作仍各占命令槽；Controller去重不能连带少算命令。
        d,q,c,ts=f(forecast=dict(submissions='2'));same=copy.deepcopy(c)
        same['evaluations']['r0']['steps'][1]['controller_scope']=copy.deepcopy(ts[0]['controller_scope'])
        execute(d,same,1);check('同目标双动作各占槽',d.execute('SELECT submissions FROM wb_shape').fetchone()[0],2)
        denied('满命令槽拒绝后续执行',d,lambda:F.receive_event(d,event(2),same),'workload_budget_exceeded')
        # 一个新Controller与两项既有准备共同占三目标；第四个在提交前即拒绝。
        d,q,c,ts=f();bad=copy.deepcopy(c)
        for i,s in enumerate(bad['evaluations']['r0']['steps']):s['controller_scope']['authority_service_id']='new.'+str(i)
        denied('计划目标并集超额提前拒绝',d,lambda:F.receive_event(d,event(1),bad),'workload_budget_exceeded')
        bad=copy.deepcopy(c);bad['evaluations']['r0']['steps'][0]['controller_scope'].pop('database_instance_id')
        denied('缺目标字段不能少计',d,lambda:F.receive_event(d,event(1),bad),'workload_action_scope_required')
        F.receive_event(d,event(1),c);ex=FLOW.active(d)
        check('未提交动作已经占位',tuple(d.execute('SELECT submissions,controller_targets FROM wb_shape').fetchone()),(2,2))
        A.apply(d,lambda:F.anchor_steps(d,ex,c));A.apply(d,lambda:F.ready_steps(d,ex,'step.0',c))
        subwrites=AT.planned(d,lambda:F.submit_steps(d,ex,'step.0',c))
        denied('提交不可更换已占位目标',d,lambda:C.execute(d,C.mutate(subwrites,'command_submission',dict(target_authority='controller-b'))),'workload_submission_slot_mismatch')
        C.execute(d,subwrites);check('提交后不重复占槽',d.execute('SELECT submissions FROM wb_shape').fetchone()[0],2)
        sub=FLOW.submission(d,ex,'step.0');F.attempt(d,sub,c);value=F.receipt(d,sub)
        B.protect(d,C.fault('1'),c);B.protect(d,C.fault('2'),c)
        A.apply(d,lambda:F.accept_steps(d,sub,value,c));check('耗尽后在途证据仍能提交',R.one(d,'command_submission','submission_id',sub)['state'],'accepted')
        # 依赖无代次过滤，必须同时保护新旧代次剩余额度。
        d,q,c,ts=f();executions=[execute(d,c,n) for n in range(1,5)]
        for ex in executions[:3]:C.execute(d,[dependency(d,ex)])
        denied('第五依赖整体拒绝',d,lambda:C.execute(d,[dependency(d,executions[3])]),'workload_budget_exceeded')
        rq,rc=recovery(d,c,ts);writes=AT.planned(d,lambda:RB.M.reserve_steps(d,rq,rc))
        for i,(sql,args) in enumerate(writes):
            denied('恢复增长写后故障'+str(i),d,lambda i=i:RB.M.reserve(d,rq,rc,fail_after=i),'injected')
            if sql.startswith('INSERT INTO recovery_budget_'):
                denied('恢复不能遗漏最后预算'+str(i),d,lambda i=i:C.execute(d,writes[:i]+writes[i+1:]))
        small=dict(rc,forecast=dict(rc['forecast'],preparations='3'))
        denied('新代次准备超额整体回滚',d,lambda:RB.M.reserve(d,rq,small),'workload_budget_seal')
        check('有界恢复先登记后预算成功',RB.M.reserve(d,rq,rc),'accepted')
        shapes={r['generation']:dict(r) for r in P.rows(d,'SELECT * FROM wb_shape')}
        check('新准备与执行不扩大旧代次',(shapes['1']['executions'],shapes['1']['preparations']),(4,2))
        check('新代次包含历史库存',(shapes['2']['executions'],shapes['2']['preparations']),(5,4))
        denied('新预算较大不能突破旧依赖预算',d,lambda:C.execute(d,[dependency(d,executions[3])]),'workload_budget_exceeded')
        RB.prepared(d,rq);R.apply(d,lambda:R.start_steps(d,rq['operation_id'],rc));RB.finish(d,rq)
        check('增长约束兼容恢复R4R5',R.one(d,'run','run_id','r0')['lifecycle'],'armed')
        shape=dict(d.execute("SELECT * FROM wb_shape WHERE generation='2'").fetchone())
        check('reconcile步骤不虚占命令槽',shape['submissions'],8)
        # 预算最后封存也要检查尚未提交的动作，不能仅查实际submission。
        d,q,c,ts=f();F.receive_event(d,event(1),c);ex=FLOW.active(d)
        # 当前计划仍含两个动作，但没有任何submission；暂停后新预算不得只预留一个。
        rq,rc=recovery(d,c,ts);rc['forecast']['submissions']='1'
        denied('恢复seal计入历史未提交动作',d,lambda:RB.M.reserve(d,rq,rc),'workload_budget_seal')
        # 普通历史代次不可新增执行，新的动作不向耗尽账户借用额度。
        d,q,c,ts=f();writes=AT.planned(d,lambda:F.ingress_steps(d,event(1),c))
        denied('执行不能伪造无账户代次',d,lambda:C.execute(d,C.mutate(writes,'execution',dict(arm_generation='999'))),'workload_account_required')
        for n,db in enumerate(dbs):check('外键完整'+str(n),list(db.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'workload-budget-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=106,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
