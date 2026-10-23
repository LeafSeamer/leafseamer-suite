"""共享保护预留消费、完整事务和旧代次隔离的离线检查。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import protection_charge_model as M
import check_protection_retry as T
G=M.G;A=M.A;P=M.P;R=M.R;I=M.I;C=T.C;B=T.B;SP=T.SP
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in ('PROTECTION_CHARGE.md','protection_charge_model.py','check_protection_charge.py','seamer-protection-charge.sql')]))
def context(c):return dict(c,volatile_close_verified=True,clock_wait_verified=True,elapsed_wait_ns='0')
def fixture(**kw):
    d,c,e=T.T.fixture(sql_factory=G.build,**kw);return d,context(c),e
def planned(d,builder,c):
    d.execute('BEGIN IMMEDIATE')
    try:
        before=M.snapshot(d);old={x[0] for x in d.execute('SELECT plan_id FROM protection_plan_registry')};w=builder()
        for sql,args in w:d.execute(sql,args)
        plans=sorted({x[0] for x in d.execute('SELECT plan_id FROM protection_plan_registry')}-old)
        return w+M.charge_steps(d,plans,before,c)
    finally:d.rollback()
def balance(d):return dict(d.execute('SELECT * FROM pb_balance').fetchone())
def extra_dependency(d,ident):
    return [I('ingress_source',source_id=ident,source_key=ident.encode(),revision='0',contiguous_sequence='0',reject_floor='0',state='synchronized'),
        I('p1_dependency',dependency_id=ident,sequence=d.execute('SELECT max(sequence)+1 FROM p1_dependency').fetchone()[0],source_id=ident,run_id='r0',owner_kind='run',owner_ref='r0',execution_id=None,recovery_id=None,
            artifact_digest=d.execute('SELECT artifact_digest FROM published_version').fetchone()[0],binding_body=B)]
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
        check('生成字节',(HERE/'seamer-protection-charge.sql').read_bytes()==G.build())
        d,c,e=f();check('99表组合',len(C.snapshot(d)),99);check('初始两份预留',balance(d)['episodes_left'],2)
        writes=planned(d,lambda:M.M.terminal_steps(d,e,'step.0','unknown',c),c)
        for i in range(len(writes)):
            denied('完整保护消费漏写'+str(i),d,lambda i=i:C.execute(d,writes[:i]+writes[i+1:]))
            denied('完整保护消费写后故障'+str(i),d,lambda i=i:M.terminal(d,e,'step.0','unknown',c,fail_after=i),'injected')
        check('故障不伪造持久确认',c['protection_confirmation'],'unconfirmed')
        denied('旧保护writer不可漏扣账',d,lambda:M.M.terminal(d,e,'step.0','unknown',c))
        for dim in G.DIMENSIONS:denied('少扣'+dim,d,lambda dim=dim:C.execute(d,C.mutate(writes,'pb_use',{dim:1})),'charge_vector')
        for name,patch in [('错预留',dict(operation_id='missing')),('错绑定',dict(binding_digest='wrong')),('错代次',dict(generation='2')),('跳序号',dict(ordinal=2)),('错计划摘要',dict(plan_digest='wrong'))]:
            denied(name,d,lambda patch=patch:C.execute(d,C.mutate(writes,'pb_use',patch)))
        for elapsed in ('-1','01','500000000','99999999999999999999'):
            denied('等待边界'+elapsed,d,lambda elapsed=elapsed:M.terminal(d,e,'step.0','unknown',dict(c,elapsed_wait_ns=elapsed)))
        denied('监督关闭未确认',d,lambda:M.terminal(d,e,'step.0','unknown',dict(c,volatile_close_verified=False)),'runtime_unconfirmed')
        initial=balance(d);root=M.terminal(d,e,'step.0','unknown',dict(c,elapsed_wait_ns='499999999'))[0]
        check('首保护消耗一份',balance(d)['episodes_left'],1)
        for dim in G.DIMENSIONS:
            check('四维守恒'+dim,balance(d)['held_'+dim]+balance(d)['spent_'+dim],initial['held_'+dim])
        before=C.snapshot(d);check('重复终态无新计划',M.terminal(d,e,'step.0','unknown',c),[]);check('重复不二次扣账',C.snapshot(d)==before)
        T.observe(d,root);check('applied不退额度',balance(d)['episodes_left'],1)
        T.observe(d,root,2);req=T.request(root);pid=M.retry(d,req,c)[0];check('重新关闭消耗第二份',balance(d)['episodes_left'],0)
        check('四维held归零',all(balance(d)['held_'+dim]==0 for dim in G.DIMENSIONS))
        T.observe(d,pid,2);denied('两份耗尽第三计划整笔回滚',d,lambda:M.retry(d,T.request(root,pid,'third'),c),'capacity')
        check('耗尽维持暂停',R.one(d,'run','run_id','r0')['lifecycle'],'paused')
        before=C.snapshot(d);check('耗尽查原不再扣',M.retry(d,req,dict(c,elapsed_wait_ns='99999999999999999999')),[]);check('耗尽查原零写',C.snapshot(d)==before)
        # 终态计划与来源P1共享同一预留，不得各自重新计算可用两份。
        z,cc,ee=f();M.apply(z,lambda:P.plan_steps(z,C.fault()),cc);check('来源P1已扣一份',balance(z)['episodes_left'],1)
        M.terminal(z,ee,'step.0','unknown',cc);check('来源与动作共享池耗尽',balance(z)['episodes_left'],0)
        Q=T.T.T.T.Q;value=Q.withdrawal(z)
        denied('准备撤回不能绕过已耗尽池',z,lambda:M.apply(z,lambda:Q.Q.invalidate_steps(z,'registration.a','withdrawal',value),cc),'capacity')
        z,cc,ee=f();value=Q.withdrawal(z);M.apply(z,lambda:Q.Q.invalidate_steps(z,'registration.a','withdrawal',value),cc)
        check('准备资格保护成功扣账',balance(z)['episodes_left'],1)
        # arm准备尚未完成时退出也必须消费同一代次的原预留。
        z,arm,cc,targets=T.T.T.T.fixture(sql_factory=G.build);dbs.append(z);A.reserve(z,arm,cc);cc=context(dict(cc,trusted_system_closer=True))
        X=T.T.T.E.X;q=T.T.T.E.request(z);M.apply(z,lambda:X.stop_steps(z,q,cc),cc);check('失败arm退出初次关闭扣账',balance(z)['episodes_left'],1)
        # 完整库存增长越过预测时拒绝，不能少报shape以通过消费。
        z,cc,ee=f()
        for i in range(4):C.execute(z,extra_dependency(z,'extra.'+str(i)))
        denied('依赖增长超过原forecast',z,lambda:M.terminal(z,ee,'step.0','unknown',cc),'charge_shape')
        z,cc,ee=f();w=planned(z,lambda:M.M.terminal_steps(z,ee,'step.0','unknown',cc),cc)
        denied('最后封存前shape变化',z,lambda:C.execute(z,w[:-1]+extra_dependency(z,'late')+w[-1:]),'final_shape')
        # 同一来源影响两个run，必须分别扣各自预留，不能用一个账户代付另一个。
        z,cc,ee=f();artifact=z.execute('SELECT artifact_digest FROM published_version').fetchone()[0]
        C.execute(z,[I('published_version',definition_id='d1',version='1',artifact_digest=artifact,artifact_body=B),
            I('run',run_id='r1',definition_id='d1',version='1',revision='1',arm_generation='0',lifecycle='disarmed',dispatch_eligible=0),
            I('activation_slot',definition_id='d1',revision='1',active_run_id=None,version=None),
            I('p1_dependency',dependency_id='source.r1',sequence=2,source_id='source',run_id='r1',owner_kind='run',owner_ref='r1',execution_id=None,recovery_id=None,artifact_digest=artifact,binding_body=B)])
        targets=json.loads(z.execute('SELECT targets_body FROM arm_preflight').fetchone()[0])
        for t in targets:t['registration_id']='second.'+t['registration_id'];t['preparation_id']='second.'+t['preparation_id'];t['request_body']['preparation_id']=t['preparation_id']
        c2=dict(cc,target_manifest_digest=P.digest(P.canonical(targets)))
        z.execute(*A.preflight_step(z,'second.preflight','r1',targets,c2));A.reserve(z,dict(operation_id='arm.2',run_id='r1',preflight_id='second.preflight',request_epoch='second.epoch',actor=dict(principal_id='operator'),idempotency_key='second.key'),c2)
        T.T.T.T.receive_all(z,targets);A.apply(z,lambda:A.complete_steps(z,'arm.2',c2))
        w=planned(z,lambda:P.plan_steps(z,C.fault()),cc);uses=[i for i,(sql,args) in enumerate(w) if sql.startswith('INSERT INTO pb_use(')]
        for i in uses:denied('跨run缺一个账户'+str(i),z,lambda i=i:C.execute(z,w[:i]+w[i+1:]))
        M.apply(z,lambda:P.plan_steps(z,C.fault()),cc)
        check('跨run分别扣原预留',[(x['run_id'],x['episodes_left']) for x in P.rows(z,'SELECT * FROM pb_balance ORDER BY run_id')],[('r0',1),('r1',1)])
        check('同一计划含两账户',z.execute('SELECT count(*) FROM pb_use').fetchone()[0],2)
        # 原两份预算保持在一代；新恢复不自动继承旧额度。
        z,cc,ee=f(machine=False);rr=M.terminal(z,ee,'step.0','unknown',cc)[0];T.observe(z,rr,2)
        r=R.one(z,'run','run_id','r0');s=R.one(z,'activation_slot','definition_id','d0')
        C.execute(z,[I('recovery_preview',preview_id='charge.preview',run_id='r0',run_revision=r['revision'],slot_revision=s['revision'],prior_execution_id=ee,
            preview_digest=T.T.T.H,plan_digest='recovery.plan',preview_body=B,clock_body=B,issued_tick='100',expires_tick='200')])
        recovery=dict(operation_id='recovery.1',execution_id='recovery.execution',run_id='r0',preview_id='charge.preview',request_epoch='resume.epoch',actor=dict(principal_id='operator'),
            idempotency_key='resume.key',mode='reconcile_commit',kind='rule',plan_digest='recovery.plan',resolved_latches=[x[0] for x in z.execute('SELECT latch_id FROM pause_latch WHERE cleared_start_id IS NULL')],targets=[])
        gates=dict(authorized=True,current=True,old_resources_clear=True,clock_body=B,now=150);R.reserve(z,recovery,gates)
        before=R.one(z,'run','run_id','r0');M.retry(z,T.request(rr),cc);check('旧重试不改新代次run',R.one(z,'run','run_id','r0')==before)
        check('消费仍引用原arm一代',[(x['operation_id'],x['generation']) for x in P.rows(z,'SELECT * FROM pb_use ORDER BY ordinal')],[('arm.1','1'),('arm.1','1')])
        denied('新代次无预算不得借旧池',z,lambda:M.apply(z,lambda:P.plan_steps(z,C.fault('2')),cc),'generation_budget_missing')
        check('外键完整',list(z.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'protection-charge-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=99,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
