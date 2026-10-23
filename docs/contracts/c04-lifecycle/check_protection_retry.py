"""保护证明失效后重新关闭的同库与Schema离线验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import protection_retry_model as M
import check_failure_protection as T
G=M.G;A=M.A;P=M.P;R=M.R;I=M.I;C=T.C;SP=T.SP;B=T.B
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in ('PROTECTION_RETRY.md','protection-retry.schema.json','protection_retry_model.py','check_protection_retry.py','seamer-protection-retry.sql')]))
def request(root,previous=None,key='retry.1'):
    return dict(contract_version=G.VERSION,root_plan_id=root,previous_plan_id=previous or root,request_epoch='retry.epoch',actor=dict(principal_id='operator'),idempotency_key=key,reason='proof_invalidated')
def observe(db,plan,revision=1):
    for t in P.rows(db,'SELECT * FROM sr_all_targets WHERE plan_id=? ORDER BY target_id',(plan,)):
        b=json.loads(t['binding_body']);SP.receive(db,plan,t['target_id'],C.observation(b,revision),b['controller_scope'])
def run():
    checks=[];dbs=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(revision=None,**kw):
        d,c,e=T.fixture(sql_factory=G.build,**kw);dbs.append(d);T.M.terminal(d,e,'step.0','unknown',c);root=e+'.step.0.terminal.protection'
        if revision:observe(d,root,revision)
        return d,c,e,root,request(root)
    def denied(n,d,call,reason=None):
        before=C.snapshot(d)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError,M.jsonschema.ValidationError) as err:
            if reason:assert reason in str(err),(n,str(err),reason)
            check(n,C.snapshot(d)==before);return
        raise AssertionError(n)
    try:
        check('生成SQL字节',(HERE/'seamer-protection-retry.sql').read_bytes()==G.build());check('生成Schema字节',(HERE/'protection-retry.schema.json').read_bytes()==G.schema_bytes())
        M.jsonschema.Draft202012Validator.check_schema(G.schema())
        d,c,e,root,q=f();check('97表布局',len(C.snapshot(d)),97)
        denied('pending不建新关闭身份',d,lambda:M.retry(d,q,c),'latest_invalidated')
        observe(d,root);denied('applied不无故重试',d,lambda:M.retry(d,q,c),'latest_invalidated')
        observe(d,root,2);writes=T.T.T.planned(d,lambda:M.retry_steps(d,q,c))
        for i in range(len(writes)):
            denied('重试漏写'+str(i),d,lambda i=i:C.execute(d,writes[:i]+writes[i+1:]))
            denied('重试写后故障'+str(i),d,lambda i=i:M.retry(d,q,c,fail_after=i),'injected')
        for key in q:
            bad=copy.deepcopy(q);bad.pop(key);denied('缺字段'+key,d,lambda bad=bad:M.retry(d,bad,c))
        for patch in (dict(contract_version='wrong'),dict(reason='timeout'),dict(extra=True),dict(actor=dict(principal_id='')),dict(idempotency_key='x\n')):
            denied('Schema拒绝'+str(patch),d,lambda patch=patch:M.retry(d,dict(q,**patch),c))
        denied('无当前关闭资格',d,lambda:M.retry(d,q,dict(c,trusted_system_closer=False,authorized=False)),'close_authority')
        before=C.snapshot(d);result=M.retry(d,q,dict(c,authorized=False));pid=result['plan_id'];check('首次重试序号',result['attempt_index'],1)
        after=C.snapshot(d);stable=('run','execution','step_terminal','step_state','activation_slot','business_state','command_submission','submission_attempt','arm_budget_reservation','pause_latch')
        check('重试不重放动作不改当前运行',all(before[k]==after[k] for k in stable))
        check('旧保护原件保留',before['sf_plan']==after['sf_plan'] and before['sf_target']==after['sf_target'])
        check('最新待查只指向新计划',sorted({x[0] for x in d.execute('SELECT plan_id FROM sf_pending_dispatch')}),[pid])
        check('全部目标重新关闭',d.execute('SELECT count(*) FROM sf_pending_dispatch').fetchone()[0],2)
        before=C.snapshot(d);check('原请求查原结果',M.retry(d,q,c),result);check('重复全库零写',C.snapshot(d)==before)
        denied('同键更换原计划冲突',d,lambda:M.retry(d,dict(q,root_plan_id='other'),c),'identity_conflict')
        denied('过期previous拒绝',d,lambda:M.retry(d,dict(q,idempotency_key='new.key'),c),'stale_attempt')
        denied('当前pending不得重试',d,lambda:M.retry(d,request(root,pid,'retry.2'),c),'latest_invalidated')
        observe(d,root,1);check('旧成功不完成新计划',d.execute('SELECT observed_state FROM sp_observed_summary WHERE plan_id=?',(pid,)).fetchone()[0],'pending')
        old=P.rows(d,'SELECT * FROM sf_target WHERE plan_id=? ORDER BY target_id',(root,))[0];new=P.rows(d,'SELECT * FROM sr_target WHERE plan_id=? ORDER BY target_id',(pid,))[0]
        old_binding=json.loads(old['binding_body']);denied('旧ACK不可移植新目标',d,lambda:SP.receive(d,pid,new['target_id'],C.observation(old_binding),old_binding['controller_scope']),'binding')
        observe(d,pid);check('新计划全applied不自动恢复',R.one(d,'run','run_id','r0')['lifecycle'],'paused')
        check('最新完成待查归零',d.execute('SELECT count(*) FROM sf_pending_dispatch').fetchone()[0],0)
        observe(d,pid,2);check('最新失效重新待查',d.execute('SELECT count(*) FROM sf_pending_dispatch').fetchone()[0],2)
        r2=M.retry(d,request(root,pid,'retry.2'),c);check('再次重试连续序号',r2['attempt_index'],2)
        before=C.snapshot(d);check('较旧幂等请求仍查原',M.retry(d,q,c),result);check('较旧查原不回退latest',C.snapshot(d)==before)
        for col,val in [('attempt_index',3),('root_plan_id','wrong'),('previous_plan_id','wrong'),('target_count',1)]:
            z,cc,ee,rr,qq=f(2);w=T.T.T.planned(z,lambda:M.retry_steps(z,qq,cc));denied('错'+col,z,lambda z=z,w=w,col=col,val=val:C.execute(z,C.mutate(w,'sr_attempt',{col:val})))
        z,cc,ee,rr,qq=f(2);w=T.T.T.planned(z,lambda:M.retry_steps(z,qq,cc));denied('篡改目标scope',z,lambda:C.execute(z,C.mutate(w,'sr_target',dict(controller_authority='other'))),'target_binding')
        # 同一序号提交后，旧缓存写集不能再次执行。
        result0=M.retry(z,qq,cc);denied('旧缓存写集重复提交',z,lambda:C.execute(z,w))
        z,cc,ee,rr,qq=f(1);one=P.rows(z,'SELECT * FROM sf_target WHERE plan_id=? ORDER BY target_id',(rr,))[0];binding=json.loads(one['binding_body'])
        SP.receive(z,rr,one['target_id'],C.observation(binding,2),binding['controller_scope']);M.retry(z,qq,cc)
        check('单目标失效仍关闭全部目标',z.execute('SELECT count(*) FROM sr_target').fetchone()[0],2)
        check('旧局部成功不计入新计划',z.execute('SELECT count(*) FROM sf_pending_dispatch').fetchone()[0],2)
        # 同一原失败最多16次新关闭尝试；耗尽不清记录，原请求查原仍可用。
        z,cc,ee,rr,qq=f(2);first=None;last=rr
        for n in range(1,17):
            res=M.retry(z,request(rr,last,'capacity.'+str(n)),cc);first=first or res;last=res['plan_id'];observe(z,last,2)
        check('16次完整保留',z.execute('SELECT count(*) FROM sr_attempt').fetchone()[0],16)
        denied('第17次拒绝且不截断',z,lambda:M.retry(z,request(rr,last,'capacity.17'),cc),'retry_capacity')
        check('耗尽仍可查询原请求',M.retry(z,request(rr,rr,'capacity.1'),cc),first)
        check('耗尽仍暂停且无动作重投',R.one(z,'run','run_id','r0')['lifecycle'],'paused')
        # 正在准备新代次时，旧代次重新关闭只沿原选择器推进。
        z,cc,ee,rr,qq=f(2,machine=False);r=R.one(z,'run','run_id','r0');s=R.one(z,'activation_slot','definition_id','d0')
        C.execute(z,[I('recovery_preview',preview_id='retry.preview',run_id='r0',run_revision=r['revision'],slot_revision=s['revision'],prior_execution_id=ee,
            preview_digest=T.T.H,plan_digest='recovery.plan',preview_body=B,clock_body=B,issued_tick='100',expires_tick='200')])
        recovery=dict(operation_id='recovery.1',execution_id='recovery.execution',run_id='r0',preview_id='retry.preview',request_epoch='resume.epoch',actor=dict(principal_id='operator'),
            idempotency_key='resume.key',mode='reconcile_commit',kind='rule',plan_digest='recovery.plan',resolved_latches=[x[0] for x in z.execute('SELECT latch_id FROM pause_latch WHERE cleared_start_id IS NULL')],targets=[])
        gates=dict(authorized=True,current=True,old_resources_clear=True,clock_body=B,now=150);R.reserve(z,recovery,gates)
        before=C.snapshot(z);res=M.retry(z,qq,cc);after=C.snapshot(z);check('旧重试不改新代次',all(before[k]==after[k] for k in stable))
        check('旧重试选择器仍为一代',sorted(set(json.loads(x[0])['deny_through_generation'] for x in z.execute('SELECT binding_body FROM sr_target'))),['1'])
        R.apply(z,lambda:R.ready_steps(z,recovery['operation_id']));T.T.T.Q.F.execution_plan(z,recovery);R.apply(z,lambda:R.start_steps(z,recovery['operation_id'],gates))
        check('新代次显式启动仍成功',tuple(z.execute('SELECT lifecycle,arm_generation FROM run').fetchone()),('running','2'))
        check('最终外键完整',list(z.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'protection-retry-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=97,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
