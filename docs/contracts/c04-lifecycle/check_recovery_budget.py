"""恢复新预留、旧账隔离、共享容量及R4/R5的内存SQLite验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import recovery_budget_model as M
import check_protection_charge as T
G=M.G;A=M.A;P=M.P;R=M.R;I=M.I;C=T.C;B=T.B;CH=M.C
FS=T.T.T;TF=FS.T;AT=TF.T;REG=AT.Q.F
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in ('RECOVERY_BUDGET.md','recovery_budget_model.py','check_recovery_budget.py','seamer-recovery-budget.sql')]))
def gates(c):return dict(c,now=150,old_resources_clear=True)
def fixture(*,targets=False):
    d,c,e=FS.fixture(sql_factory=G.build,machine=False);c=T.context(c)
    root=CH.terminal(d,e,'step.0','unknown',c)[0];T.T.observe(d,root)
    r=R.one(d,'run','run_id','r0');s=R.one(d,'activation_slot','definition_id','d0')
    d.execute(*I('recovery_preview',preview_id='budget.preview',run_id='r0',run_revision=r['revision'],slot_revision=s['revision'],prior_execution_id=e,
        preview_digest=AT.H,plan_digest='recovery.plan',preview_body=B,clock_body=B,issued_tick='100',expires_tick='200'))
    ts=json.loads(d.execute('SELECT targets_body FROM arm_preflight').fetchone()[0]) if targets else []
    for t in ts:
        t['registration_id']='new.'+t['registration_id'];t['preparation_id']='new.'+t['preparation_id'];t['request_body']['preparation_id']=t['preparation_id']
    req=dict(operation_id='recovery.1',execution_id='recovery.execution',run_id='r0',preview_id='budget.preview',request_epoch='resume.epoch',actor=dict(principal_id='operator'),
        idempotency_key='resume.key',mode='reconcile_commit',kind='rule',plan_digest='recovery.plan',
        resolved_latches=[x[0] for x in d.execute('SELECT latch_id FROM pause_latch WHERE cleared_start_id IS NULL')],targets=ts)
    c=gates(c);c['forecast']=dict(c['forecast'],preparations='4')
    return d,req,c,root
def prepared(d,q):
    for t in q['targets']:
        ident=t['registration_id'];R.apply(d,lambda:[R.attempt_step(d,ident,ident+'.attempt',B)])
        A.Q.receive(d,ident,REG.granted(d,ident),t['controller_scope'])
    R.apply(d,lambda:R.ready_steps(d,q['operation_id']));REG.execution_plan(d,q)
def finish(d,q):
    """沿原reconcile协议提交R5，不以普通触发finish替代恢复锁释放。"""
    ex=q['execution_id'];op=q['operation_id'];r=R.one(d,'run','run_id','r0');s=R.one(d,'activation_slot','definition_id','d0');o=R.one(d,'recovery_operation','operation_id',op)
    C.execute(d,R.event('terminal','r0','STEP_TERMINAL')+[
        I('step_terminal',terminal_id='terminal',execution_id=ex,step_id='step',run_id='r0',outcome='succeeded',evidence_body=B,result_ref_body=B,tx_id='terminal.STEP_TERMINAL'),
        ("UPDATE step_state SET state='finished',outcome='succeeded',terminal_id='terminal',revision='2' WHERE execution_id=?",(ex,))])
    C.execute(d,R.event('commit','r0','R5')+[
        I('transition_commit',commit_id='commit',run_id='r0',execution_id=ex,kind='rule',source_state_id=None,source_state_revision=None,target_state_id=None,target_state_revision=None,
            evidence_set_body=B,commit_body=B,commit_digest=AT.H,tx_id='commit.R5',run_revision_before=r['revision'],run_revision_after=P.inc(r['revision']),slot_revision=s['revision']),
        ("UPDATE execution SET state='succeeded',commit_id='commit' WHERE execution_id=?",(ex,)),
        ("UPDATE run SET lifecycle='armed',revision=?,active_execution_id=NULL,dispatch_eligible=1,last_commit_id='commit' WHERE run_id='r0'",(P.inc(r['revision']),)),
        ("UPDATE recovery_operation SET state='completed',revision=? WHERE operation_id=?",(P.inc(o['revision']),op)),
        I('external_evidence',evidence_id='release',authority_id='supervisor',database_id='provider.db',kind='release',object_id='release',revision='1',digest=AT.H,body=B),
        ("UPDATE recovery_lock SET release_id='release' WHERE operation_id=?",(op,)),I('flow_commit_seal',commit_id='commit',audit_body=B,notification_body=B)])
def balances(d):return [(x['operation_id'],x['generation'],x['episodes_left']) for x in P.rows(d,'SELECT * FROM pb_balance ORDER BY generation')]
def run():
    checks=[];dbs=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(**kw):
        d,q,c,root=fixture(**kw);dbs.append(d);return d,q,c,root
    def denied(n,d,call,reason=None):
        before=C.snapshot(d)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError) as err:
            if reason:assert reason in str(err),(n,str(err),reason)
            check(n,C.snapshot(d)==before);return
        raise AssertionError(n)
    try:
        check('生成布局字节',(HERE/'seamer-recovery-budget.sql').read_bytes()==G.build())
        d,q,c,root=f(targets=True);check('102表组合',len(C.snapshot(d)),102)
        writes=AT.planned(d,lambda:M.reserve_steps(d,q,c))
        for i in range(len(writes)):
            denied('R2预留缺写'+str(i),d,lambda i=i:C.execute(d,writes[:i]+writes[i+1:]))
            denied('R2预留写后故障'+str(i),d,lambda i=i:M.reserve(d,q,c,fail_after=i),'injected')
        denied('旧R2不能绕过预算',d,lambda:R.reserve(d,q,c))
        for field in ('human','inventory_verified','controller_capacity_verified','old_resources_clear','authorized'):
            denied('资格拒绝'+field,d,lambda field=field:M.reserve(d,q,dict(c,**{field:False})))
        for table,field,value in [('recovery_budget_reservation','preview_digest','wrong'),('recovery_budget_reservation','manifest_digest','wrong'),
            ('recovery_budget_reservation','request_digest','wrong'),('recovery_budget_reservation','profile_digest','wrong'),
            ('recovery_budget_commit','binding_digest','wrong'),('recovery_budget_commit','preview_digest','wrong'),('recovery_budget_commit','manifest_digest','wrong'),
            ('recovery_budget_commit','audit_body',b''),('recovery_budget_commit','notification_body',b'')]:
            denied('原件错配'+table+field,d,lambda table=table,field=field,value=value:C.execute(d,C.mutate(writes,table,{field:value})))
        for dim in G.DIMENSIONS:
            denied('四维少留'+dim,d,lambda dim=dim:C.execute(d,C.mutate(writes,'recovery_budget_reservation',{dim:1})))
        original_budget=next(dict(zip(sql.split('(',1)[1].split(')',1)[0].split(','),args))['budget_body'] for sql,args in writes if sql.startswith('INSERT INTO recovery_budget_reservation('))
        for key,value in [('operation_id','arm.1'),('run_id','other'),('generation','1'),('profile_id','other'),('profile_revision','2'),('profile_digest','wrong'),('artifact_digest','wrong')]:
            ticket=json.loads(original_budget);ticket['binding'][key]=value;ticket['binding_digest']=A.B.digest(ticket['binding'])
            changed=C.mutate(writes,'recovery_budget_reservation',dict(budget_body=P.canonical(ticket)))
            changed=C.mutate(changed,'recovery_budget_commit',dict(binding_digest=ticket['binding_digest']))
            denied('重算摘要后绑定错配'+key,d,lambda changed=changed:C.execute(d,changed))
        for dim,value in [('preparations','3'),('executions','1'),('submissions','2'),('controller_targets','1'),('dependencies','0')]:
            denied('恢复库存低估'+dim,d,lambda dim=dim,value=value:M.reserve(d,q,dict(c,forecast=dict(c['forecast'],**{dim:value}))))
        denied('最后seal前依赖变化',d,lambda:C.execute(d,writes[:-1]+T.extra_dependency(d,'late')+writes[-1:]),'recovery_budget_seal')
        old=C.snapshot(d);check('R2新代次有预留',M.reserve(d,q,c),'accepted')
        check('旧预算原件与消费不改',all(old[t]==C.snapshot(d)[t] for t in ('arm_budget_reservation','pb_use','pb_commit')))
        check('新旧预算分别持有',balances(d),[('arm.1','1',1),('recovery.1','2',2)])
        check('账户类型精确',[(x['kind'],x['generation']) for x in P.rows(d,'SELECT * FROM budget_account ORDER BY generation')],[('arm','1'),('recovery','2')])
        old=C.snapshot(d);check('重复R2先查原',M.reserve(d,q,dict(c,forecast={},inventory_verified=False)),'existing');check('重复R2零写',C.snapshot(d)==old)
        denied('同键不同正文',d,lambda:M.reserve(d,dict(q,mode='execute'),c),'identity_conflict')
        for table in ('budget_account','recovery_budget_reservation','recovery_budget_commit'):
            denied('原件不可删'+table,d,lambda table=table:C.execute(d,[('DELETE FROM '+table,())]),'immutable')
            denied('原件不可改'+table,d,lambda table=table:C.execute(d,[('UPDATE '+table+' SET operation_id=operation_id',())]),'immutable')
        denied('不能插入空账户',d,lambda:C.execute(d,[I('budget_account',operation_id='phantom',run_id='r0',generation='3',kind='recovery')]),'account_original')
        # 旧重试用旧池，不改新R2；成功观察不会退款。
        T.T.observe(d,root,2);before=R.one(d,'run','run_id','r0');CH.retry(d,T.T.request(root),c)
        check('旧重试不改变新代次',R.one(d,'run','run_id','r0')==before);check('旧池耗尽新池完整',balances(d),[('arm.1','1',0),('recovery.1','2',2)])
        prepared(d,q);R.apply(d,lambda:R.start_steps(d,q['operation_id'],c));check('有预算R4运行',R.one(d,'run','run_id','r0')['lifecycle'],'running')
        finish(d,q);check('显式恢复R5回armed',tuple(d.execute('SELECT lifecycle,arm_generation,dispatch_eligible FROM run').fetchone()),('armed','2',1))
        check('R5仍保留新旧账',balances(d),[('arm.1','1',0),('recovery.1','2',2)])
        # 新代次保护消费新池；旧池耗尽不阻新代次独立保护。
        CH.apply(d,lambda:P.plan_steps(d,C.fault('2')),c)
        check('新代次独立消费',balances(d),[('arm.1','1',0),('recovery.1','2',1)])
        check('新消费指向恢复原件',d.execute("SELECT operation_id FROM pb_use WHERE generation='2'").fetchone()[0],'recovery.1')
        # R4之后动作失败也按恢复代次记账，而非只有来源故障可消费新账户。
        z,qq,cc,rr=f();M.reserve(z,qq,cc);prepared(z,qq);R.apply(z,lambda:R.start_steps(z,qq['operation_id'],cc))
        CH.terminal(z,qq['execution_id'],'step','unknown',cc)
        check('恢复执行失败消费新池',balances(z),[('arm.1','1',1),('recovery.1','2',1)])
        check('恢复执行失败保持暂停',R.one(z,'run','run_id','r0')['lifecycle'],'paused')
        z,qq,cc,rr=f();M.reserve(z,qq,cc);prepared(z,qq);start=R.start_steps(z,qq['operation_id'],cc)
        CH.apply(z,lambda:P.plan_steps(z,C.fault('2')),cc)
        denied('R4前已消费整份不能启动',z,lambda:C.execute(z,start),'recovery_start_budget_unavailable')
        z,qq,cc,rr=f();M.reserve(z,qq,cc);prepared(z,qq)
        for i in range(4):C.execute(z,T.extra_dependency(z,'growth.'+str(i)))
        denied('R4前库存增长拒绝',z,lambda:R.apply(z,lambda:R.start_steps(z,qq['operation_id'],cc)),'recovery_start_budget_unavailable')
        # 初始容量配置为一份arm总预留或arm+恢复精确总量；所有原触发器保持启用。
        for dim in G.DIMENSIONS:
            amount=int(A.B.cost(AT.A.profile(),AT.A.SHAPE)[dim])*2
            z,arm,cc,ts=AT.fixture(sql_factory=G.build,capacity={dim:str(amount)});dbs.append(z)
            A.reserve(z,arm,cc);AT.receive_all(z,ts);A.apply(z,lambda:A.complete_steps(z,arm['operation_id'],cc))
            qq,gg=AT.reconcile_preflight(z);cc.update(gg)
            denied('共享容量不足'+dim,z,lambda:M.reserve(z,qq,cc),'binding_or_capacity')
            check('容量不足不消费预览'+dim,R.one(z,'recovery_preview','preview_id',qq['preview_id'])['consumed_operation_id'],None)
        # 反向验证：恢复预留已占满实例后，另一个run的新arm也不能越过同一个容量上限。
        amount=int(A.B.cost(AT.A.profile(),AT.A.SHAPE)['logical_rows'])*2
        z,arm,cc,ts=AT.fixture(sql_factory=G.build,capacity={'logical_rows':str(amount*2)});dbs.append(z)
        A.reserve(z,arm,cc);AT.receive_all(z,ts);A.apply(z,lambda:A.complete_steps(z,arm['operation_id'],cc));qq,gg=AT.reconcile_preflight(z);cc.update(gg)
        M.reserve(z,qq,cc);check('精确容量等号可准入',z.execute('SELECT sum(logical_rows) FROM protection_budget_reservation').fetchone()[0],amount*2)
        C.execute(z,[I('published_version',definition_id='d1',version='1',artifact_digest=AT.H,artifact_body=B),
            I('run',run_id='r1',definition_id='d1',version='1',revision='1',arm_generation='0',lifecycle='disarmed',dispatch_eligible=0),
            I('activation_slot',definition_id='d1',revision='1',active_run_id=None,version=None)])
        c2=dict(cc,target_manifest_digest=P.digest(P.canonical([])));z.execute(*A.preflight_step(z,'second.preflight','r1',[],c2))
        newarm=dict(arm,operation_id='arm.2',run_id='r1',preflight_id='second.preflight',idempotency_key='second.key')
        denied('新arm必须计入恢复占用',z,lambda:A.reserve(z,newarm,c2),'binding_or_capacity')
        check('预算满额仍能查原R2',M.reserve(z,qq,cc),'existing')
        for conn in dbs:check('外键完整'+str(dbs.index(conn)),list(conn.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'recovery-budget-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=102,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
