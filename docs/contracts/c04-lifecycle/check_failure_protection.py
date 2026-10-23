"""动作失败与完整保护库存、共享接收计划的内存SQLite验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import failure_protection_model as M
import check_trigger_flow as T
F=M.F;G=M.G;A=M.A;R=M.R;P=M.P;I=M.I;C=T.C;SP=T.E.SP;B=T.B
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in ('FAILURE_PROTECTION.md','failure_protection_model.py','check_failure_protection.py','seamer-failure-protection.sql')]))
def fixture(*,optional=False,history=False,machine=True,limits=None,sql_factory=G.build):
    db,c,q=T.fixture(steps=4,machine=machine,sql_factory=sql_factory,protection_limits=limits);c['trusted_system_closer']=True
    c['evaluations']['r0']['steps'][0]['required']=not optional
    if history:
        F.receive_event(db,q,c);old=T.active(db);A.apply(db,lambda:F.anchor_steps(db,old,c))
        for i in range(4):T.success(db,old,'step.'+str(i),c)
        F.finish(db,old,c);q.update(event_id='event.2',source_sequence='2')
    F.receive_event(db,q,c);e=T.active(db);A.apply(db,lambda:F.anchor_steps(db,e,c));T.prepare_step(db,e,'step.0',c)
    for ident in ('step.1','step.2'):
        A.apply(db,lambda ident=ident:F.ready_steps(db,e,ident,c));A.apply(db,lambda ident=ident:F.submit_steps(db,e,ident,c))
    F.attempt(db,T.submission(db,e,'step.1'),c)
    return db,c,e
def observations(db,plan,revision=1):
    for t in P.rows(db,'SELECT * FROM sf_target WHERE plan_id=? ORDER BY target_id',(plan,)):
        binding=json.loads(t['binding_body']);SP.receive(db,plan,t['target_id'],C.observation(binding,revision),binding['controller_scope'])
def run():
    checks=[];dbs=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(**kw):
        d,c,e=fixture(**kw);dbs.append(d);return d,c,e
    def denied(n,d,call,reason=None):
        before=C.snapshot(d)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError) as err:
            if reason:assert reason in str(err),(n,str(err),reason)
            check(n,C.snapshot(d)==before);return
        raise AssertionError(n)
    try:
        check('生成字节',(HERE/'seamer-failure-protection.sql').read_bytes()==G.build())
        d,c,e=f();check('94表布局',len(C.snapshot(d)),94)
        parts=T.T.planned(d,lambda:M.terminal_steps(d,e,'step.0','failed',c))
        for i in range(len(parts)):
            denied('终态保护漏写'+str(i),d,lambda i=i:C.execute(d,parts[:i]+parts[i+1:]))
            denied('终态保护写后故障'+str(i),d,lambda i=i:M.terminal(d,e,'step.0','failed',c,fail_after=i),'injected')
        denied('旧终态写集不可漏保护',d,lambda:A.apply(d,lambda:F.terminal_steps(d,e,'step.0','failed',c)),'failure_plan_required')
        denied('缺系统关闭资格',d,lambda:M.terminal(d,e,'step.0','failed',dict(c,trusted_system_closer=False)),'protection_authority')
        # 人类权限失效不能阻止已授信的系统关闭。
        check('独立系统关闭不依赖人类权限',M.terminal(d,e,'step.0','failed',dict(c,authorized=False)),'committed')
        plan=e+'.step.0.terminal.protection';row=R.one(d,'sf_plan','plan_id',plan);inv=json.loads(row['inventory_body'])
        check('库存包含全部三类引用',sorted(x['kind'] for x in inv),['execution','preparation','preparation','submission','submission','submission'])
        check('planned和未知在途均保留',sorted(x[0] for x in d.execute('SELECT state FROM command_submission')),['accepted','attempt_recorded','planned'])
        check('目标准备并集完整',d.execute('SELECT count(*) FROM sf_target').fetchone()[0],2)
        check('run暂停但活动引用保留',tuple(d.execute('SELECT lifecycle,dispatch_eligible,active_execution_id FROM run').fetchone()),('paused',0,e))
        check('来源不被伪造失步',d.execute('SELECT state FROM ingress_source').fetchone()[0],'synchronized')
        check('准备失效事实不伪造',d.execute('SELECT count(*) FROM pq_fault').fetchone()[0],0)
        check('共享旧代次拒绝下界',d.execute('SELECT generation FROM p1_deny').fetchone()[0],'1'.zfill(20))
        before=C.snapshot(d);check('终态重复查原',M.terminal(d,e,'step.0','failed',c),'existing');check('重复零写',C.snapshot(d)==before)
        denied('终态异内容冲突',d,lambda:M.terminal(d,e,'step.0','unknown',c),'identity_conflict')
        denied('暂停后planned不可attempt',d,lambda:F.attempt(d,T.submission(d,e,'step.2'),c))
        denied('暂停后不可准备下一动作',d,lambda:A.apply(d,lambda:F.ready_steps(d,e,'step.3',c)))
        denied('暂停后不可R5',d,lambda:F.finish(d,e,c))
        observations(d,plan);check('全部applied待查空',d.execute('SELECT count(*) FROM sf_pending_dispatch').fetchone()[0],0)
        check('保护applied不自动恢复',d.execute('SELECT lifecycle FROM run').fetchone()[0],'paused')
        check('保护不退款',d.execute('SELECT count(*) FROM arm_budget_reservation').fetchone()[0],1)
        observations(d,plan,2);check('失效重新待查',d.execute('SELECT count(*) FROM sf_pending_dispatch').fetchone()[0],2)
        observations(d,plan,1);check('旧applied不覆盖高修订失效',d.execute('SELECT count(*) FROM sf_pending_dispatch').fetchone()[0],2)
        sub=T.submission(d,e,'step.1');A.apply(d,lambda:F.accept_steps(d,sub,F.receipt(d,sub),c))
        check('迟到其它受理只补历史',d.execute('SELECT lifecycle FROM run').fetchone()[0],'paused')
        # 失败前缓存的全写集不能跨槽、run和库存变化使用。
        for name,patch in [('跳修订',dict(revision_after='9')),('错代次',dict(generation='2')),('错槽',dict(slot_revision='8')),('错动作',dict(step_id='step.3'))]:
            z,cc,ee=f();writes=T.T.planned(z,lambda:M.terminal_steps(z,ee,'step.0','failed',cc));denied(name,z,lambda z=z,writes=writes,patch=patch:C.execute(z,C.mutate(writes,'sf_plan',patch)))
        z,cc,ee=f();writes=T.T.planned(z,lambda:M.terminal_steps(z,ee,'step.0','failed',cc));raw=next(args for sql,args in writes if sql.startswith('INSERT INTO sf_plan('));sql=next(sql for sql,args in writes if sql.startswith('INSERT INTO sf_plan('));values=dict(zip(sql.split('(',1)[1].split(')',1)[0].split(','),raw))
        inventory=json.loads(values['inventory_body']);inventory[-1]=copy.deepcopy(inventory[-2])
        denied('同数替换库存',z,lambda:C.execute(z,C.mutate(writes,'sf_plan',dict(inventory_body=P.canonical(inventory)))),'complete_inventory')
        denied('篡改派发正文',z,lambda:C.execute(z,C.mutate(writes,'sf_target',dict(dispatch_body=P.canonical(dict(kind='other'))))))
        denied('最终槽变化',z,lambda:C.execute(z,writes[:-1]+[("UPDATE activation_slot SET revision='99'",())]+writes[-1:]),'final_projection')
        # profile从首次建库即固定；不能为测试移除不可变守卫。
        zz,ccc,eee=f(limits=dict(max_payload_bytes=5000));denied('保护正文容量',zz,lambda:M.terminal(zz,eee,'step.0','failed',ccc),'capacity')
        z,cc,ee=f(history=True);M.terminal(z,ee,'step.0','failed',cc);inv=json.loads(z.execute('SELECT inventory_body FROM sf_plan').fetchone()[0])
        check('完整历史执行固定',sum(x['kind']=='execution' for x in inv),2);check('历史成功提交也保留',sum(x['kind']=='submission' for x in inv),7)
        for outcome in ('unknown','blocked','expired','cancelled'):
            z,cc,ee=f(optional=True);M.terminal(z,ee,'step.0',outcome,cc);check('可选'+outcome+'仍保护',z.execute('SELECT count(*) FROM sf_plan').fetchone()[0],1)
        z,cc,ee=f(optional=True);M.terminal(z,ee,'step.0','failed',cc);check('可选确定失败无保护',z.execute('SELECT count(*) FROM sf_plan').fetchone()[0],0)
        check('可选失败仍running',z.execute('SELECT lifecycle FROM run').fetchone()[0],'running')
        # 相邻两个失败各有原始终态与计划，第二计划覆盖同一完整历史，不清首锁存。
        z,cc,ee=f(limits=dict(max_plans=2));M.terminal(z,ee,'step.0','failed',cc);M.terminal(z,ee,'step.1','unknown',cc)
        check('并行组两失败分别保留',z.execute('SELECT count(*) FROM sf_plan').fetchone()[0],2)
        check('首锁存保留',z.execute("SELECT count(*) FROM pause_latch WHERE reason='step_terminal_failure'").fetchone()[0],2)
        denied('计划容量耗尽不截断',z,lambda:M.terminal(z,ee,'step.2','unknown',cc),'capacity')
        check('第二失败不改首执行终态',z.execute('SELECT state FROM execution WHERE execution_id=?',(ee,)).fetchone()[0],'failed')
        # 新预览必须引用原活动执行；旧资源核对为显式合成提供者，applied不替代它。
        z,cc,ee=f(machine=False);M.terminal(z,ee,'step.0','unknown',cc)
        rr=R.one(z,'run','run_id','r0');slot=R.one(z,'activation_slot','definition_id','d0')
        C.execute(z,[I('recovery_preview',preview_id='failure.preview',run_id='r0',run_revision=rr['revision'],slot_revision=slot['revision'],prior_execution_id=ee,
            preview_digest=T.H,plan_digest='recovery.plan',preview_body=B,clock_body=B,issued_tick='100',expires_tick='200')])
        req=dict(operation_id='recovery.1',execution_id='recovery.execution',run_id='r0',preview_id='failure.preview',request_epoch='recovery.epoch',
            actor=dict(principal_id='operator'),idempotency_key='recovery.key',mode='reconcile_commit',kind='rule',plan_digest='recovery.plan',
            resolved_latches=[x[0] for x in z.execute("SELECT latch_id FROM pause_latch WHERE cleared_start_id IS NULL ORDER BY latch_id")],targets=[])
        gates=dict(authorized=True,current=True,old_resources_clear=True,clock_body=B,now=150)
        denied('资源未知时禁止新代次恢复',z,lambda:R.reserve(z,req,dict(gates,old_resources_clear=False)),'unqualified_context')
        R.reserve(z,req,gates);before=R.one(z,'run','run_id','r0');M.terminal(z,ee,'step.1','unknown',cc)
        check('旧代次迟到失败不改当前run',R.one(z,'run','run_id','r0')==before)
        late=R.one(z,'sf_plan','terminal_id',ee+'.step.1.terminal');check('迟到旧代次不增加当前锁存',late['latch_id'],None)
        check('旧保护不含新恢复执行',all(x['ref']!='recovery.execution' for x in json.loads(late['inventory_body'])))
        R.apply(z,lambda:R.ready_steps(z,req['operation_id']));T.T.Q.F.execution_plan(z,req)
        R.apply(z,lambda:R.start_steps(z,req['operation_id'],gates))
        check('显式新代次允许启动',tuple(z.execute('SELECT lifecycle,arm_generation FROM run').fetchone()),('running','2'))
        check('旧unknown原样保留',F.step(z,ee,'step.0')['outcome'],'unknown')
        check('旧DENY不升为新代次',z.execute('SELECT generation FROM p1_deny').fetchone()[0],'1'.zfill(20))
        # 正常成功仍使用原动作和R5路径，失败扩展不能阻断已批准成功语义。
        z,cc,q=T.fixture(sql_factory=G.build);dbs.append(z);F.receive_event(z,q,cc);ee=T.active(z);A.apply(z,lambda:F.anchor_steps(z,ee,cc));T.success(z,ee,'step.0',cc)
        check('正常成功仍可R5',F.finish(z,ee,cc),'committed')
        check('组合外键完整',list(z.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'failure-protection-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=94,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
