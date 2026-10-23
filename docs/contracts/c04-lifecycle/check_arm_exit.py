"""失败布防关闭与显式恢复的SQLite离线验收，外部输送域和证明为合成。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import arm_exit_model as X
import check_arm_storage as T
G=X.G;A=X.A;P=X.P;R=X.R;I=X.I;C=T.C;SP=T.Q.SP;B=T.B;H=T.H
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in ('ARM_EXIT.md','arm-exit.schema.json','seamer-arm-exit.sql','arm_exit_model.py','check_arm_exit.py')]))
def request(db):
    return dict(contract_version=G.VERSION,arm_operation_id='arm.1',request_epoch='stop.epoch',actor=dict(principal_id='operator'),idempotency_key='stop.key',
        expected_run_revision=R.one(db,'run','run_id','r0')['revision'],reason='operator_cancel')
def retry_request(db,key='retry.key'):
    return dict(contract_version=G.VERSION,arm_operation_id='arm.1',request_epoch='stop.epoch',actor=dict(principal_id='operator'),idempotency_key=key,
        previous_plan_id=R.one(db,'aa_latest_attempt','operation_id','arm.1')['plan_id'],reason='proof_invalidated')
def observations(db,revision=1,pid=None):
    pid=pid or R.one(db,'aa_latest_attempt','operation_id','arm.1')['plan_id']
    for t in P.rows(db,'SELECT * FROM aa_target WHERE plan_id=? ORDER BY target_id',(pid,)):
        binding=json.loads(t['binding_body']);value=C.observation(binding,revision)
        SP.receive(db,pid,t['target_id'],value,binding['controller_scope'])

def run():
    checks=[];connections=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(stage=0,zero=False,prepared=False):
        db,r,c,t=T.fixture(zero=zero,sql_factory=G.build);connections.append(db);A.reserve(db,r,c)
        if prepared:T.receive_all(db,t)
        q=request(db)
        if stage:X.stop(db,q,c)
        if stage>=2:observations(db)
        if stage>=3:X.complete(db,'arm.1',c)
        return db,r,c,t,q
    def denied(n,db,call,reason=None):
        before=C.snapshot(db)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError,X.jsonschema.ValidationError) as e:
            if reason:assert reason in str(e),(n,str(e),reason)
            check(n,C.snapshot(db)==before);return
        raise AssertionError(n)
    try:
        check('90表生成字节',(HERE/'seamer-arm-exit.sql').read_bytes()==G.build())
        check('退出Schema字节',(HERE/'arm-exit.schema.json').read_bytes()==G.schema_bytes());X.jsonschema.Draft202012Validator.check_schema(G.schema())
        db,r,c,t,q=f();check('完整90表',len(C.snapshot(db)),90)
        denied('停止前不得直接清active',db,lambda:C.execute(db,[("UPDATE run SET revision='3',active_operation_id=NULL",())]),'active_arm_requires_exit')
        writes=T.planned(db,lambda:X.stop_steps(db,q,c));check('停止可靠受理',X.stop(db,q,c),'accepted')
        check('准备操作仍占用且暂停',tuple(db.execute('SELECT lifecycle,dispatch_eligible,active_operation_id,active_execution_id FROM run').fetchone()),('paused',0,'arm.1',None))
        check('关闭目标完整',db.execute('SELECT count(*) FROM aa_target').fetchone()[0],2)
        check('独立拒绝旧代次',db.execute('SELECT generation FROM p1_deny').fetchone()[0],'1'.zfill(20))
        before=C.snapshot(db);check('同请求查原',X.stop(db,q,c),'existing');check('查原零写',C.snapshot(db)==before)
        changed=copy.deepcopy(q);changed['reason']='preparation_failed';denied('同键异内容',db,lambda:X.stop(db,changed,c),'identity_conflict')
        for i in range(len(writes)):
            d,rr,cc,tt,qq=f();denied('停止缺写'+str(i),d,lambda d=d,i=i:C.execute(d,writes[:i]+writes[i+1:]))
            d,rr,cc,tt,qq=f();denied('停止写后故障'+str(i),d,lambda d=d,qq=qq,cc=cc,i=i:X.stop(d,qq,cc,fail_after=i),'injected')
        for name,table,patch in [('少库存','aa_stop',dict(inventory_body=b'[]')),('错代次','aa_stop',dict(generation='2')),
            ('跳修订','aa_stop',dict(revision_after='9')),('槽错修订','aa_stop',dict(slot_revision='9')),('U20换行','aa_stop',dict(revision_before='2\n')),
            ('错目标scope','aa_target',dict(controller_database='other')),('缺目标数','aa_attempt',dict(target_count=1)),('错首尝试','aa_attempt',dict(ordinal=2)),
            ('同数换目标','aa_target',dict(target_id='other')),('错计划正文','sp_plan',dict(plan_body=b'{}'))]:
            d,rr,cc,tt,qq=f();denied(name,d,lambda d=d,table=table,patch=patch:C.execute(d,C.mutate(writes,table,patch)))
        denied('缺保护回执不能退出',db,lambda:X.complete(db,'arm.1',c),'unconfirmed')
        denied('关闭未确认不得直接清active',db,lambda:C.execute(db,[("UPDATE run SET revision='4',active_operation_id=NULL",())]),'active_arm_requires_exit')
        denied('停止后不能完成原arm',db,lambda:A.apply(db,lambda:A.complete_steps(db,'arm.1',c)),'unqualified')
        denied('停止后不能新尝试准备',db,lambda:A.apply(db,lambda:[A.attempt_step(db,'registration.a')]),'ineligible')
        denied('pending只查原不能换屏障',db,lambda:X.retry(db,retry_request(db),c),'attempt_prestate')
        d,rr,cc,tt,qq=f();A.apply(d,lambda:[A.attempt_step(d,'registration.a')]);X.stop(d,qq,cc)
        value=T.Q.F.granted(d,'registration.a');check('迟到成功仅存历史',X.receive_preparation(d,'registration.a',value,value['binding']['controller_scope']),'stored')
        check('迟到成功无arm采用',d.execute('SELECT count(*) FROM arm_receipt').fetchone()[0],0)
        denied('绕过历史接收器采用拒绝',d,lambda:A.apply(d,lambda:A.adoption_steps(d,'registration.a',value,value['binding']['controller_scope'])),'history_only')
        observations(db);finish=T.planned(db,lambda:X.exit_steps(db,'arm.1'))
        for i in range(len(finish)):
            d,rr,cc,tt,qq=f(2);denied('退出缺写'+str(i),d,lambda d=d,i=i:C.execute(d,finish[:i]+finish[i+1:]))
            d,rr,cc,tt,qq=f(2);denied('退出写后故障'+str(i),d,lambda d=d,cc=cc,i=i:X.complete(d,'arm.1',cc,fail_after=i),'injected')
        for name,table,patch in [('错观察摘要','aa_exit_pin',dict(observation_digest='sha256:'+'0'*64)),('退出跨代','aa_exit',dict(generation='2')),
            ('退出跳修订','aa_exit',dict(revision_after='9')),('退出错plan','aa_exit',dict(plan_id='wrong'))]:
            d,rr,cc,tt,qq=f(2);denied(name,d,lambda d=d,table=table,patch=patch:C.execute(d,C.mutate(finish,table,patch)))
        d,rr,cc,tt,qq=f(2);denied('退出最后槽漂移',d,lambda:C.execute(d,finish[:-1]+[("UPDATE activation_slot SET revision='3'",())]+finish[-1:]),'final_projection')
        d,rr,cc,tt,qq=f(2);before=C.snapshot(d)
        # 在同一事务的最终seal之前写入真实接收表的后续失效，验证末次重核而非重演前态。
        target=R.one(d,'aa_latest_attempt','operation_id','arm.1')['plan_id'];row=P.rows(d,'SELECT * FROM aa_target WHERE plan_id=? ORDER BY target_id',(target,))[0]
        binding=json.loads(row['binding_body']);v=C.observation(binding,2)
        revoke=[I('sp_observation',plan_id=target,target_id=row['target_id'],revision=2,state='indeterminate',binding_body=P.canonical(binding),identity_body=P.canonical(SP.identity(v)),observation_digest=v['observation_digest'],body=P.canonical(v)),
            I('sp_observation_commit',plan_id=target,target_id=row['target_id'],revision=2,audit_body=B,outbox_body=B)]
        denied('退出最后保护失效',d,lambda:C.execute(d,finish[:-1]+revoke+finish[-1:]),'final_projection')
        result=X.complete(db,'arm.1',c);check('退出明确未释放资源',(result['state'],result['resources_cleared'],result['budget_released']),('paused',False,False))
        check('退出清active但不恢复',tuple(db.execute('SELECT lifecycle,dispatch_eligible,active_operation_id FROM run').fetchone()),('paused',0,None))
        check('退出保留锁存',db.execute('SELECT count(*) FROM pause_latch WHERE cleared_start_id IS NULL').fetchone()[0],1)
        check('退出保留预算',db.execute('SELECT count(*) FROM arm_budget_reservation').fetchone()[0],1)
        before=C.snapshot(db);check('退出查原结果',X.complete(db,'arm.1',c),result);check('退出查原零写',C.snapshot(db)==before)
        malformed=copy.deepcopy(result);malformed['resources_cleared']=True
        denied('退出结果不得暗示资源clear',db,lambda:X.validate('ExitResult',malformed))
        for field in ('expected_run_revision','contract_version','reason'):
            d,rr,cc,tt,qq=f();qq[field]='invalid';denied('停止Schema拒绝'+field,d,lambda d=d,qq=qq,cc=cc:X.stop(d,qq,cc))
        d,rr,cc,tt,qq=f();cc['authorized']=False;denied('无关闭权限',d,lambda:X.stop(d,qq,cc),'authority')
        cc['trusted_system_closer']=True;check('独立系统关闭不依赖旧人类权限',X.stop(d,qq,cc),'accepted')
        d,rr,cc,tt,qq=f(2);old=R.one(d,'aa_latest_attempt','operation_id','arm.1')['plan_id'];observations(d,2)
        denied('保护失效不能退出',d,lambda:X.complete(d,'arm.1',cc),'unconfirmed')
        rq=retry_request(d);retry_writes=T.planned(d,lambda:X.attempt_steps(d,R.one(d,'aa_stop','operation_id','arm.1'),rq,2,old))
        for i in range(len(retry_writes)):
            z,rz,cz,tz,qz=f(2);observations(z,2)
            denied('新屏障缺写'+str(i),z,lambda z=z,i=i:C.execute(z,retry_writes[:i]+retry_writes[i+1:]))
            denied('新屏障写后故障'+str(i),z,lambda z=z,cz=cz,i=i:X.retry(z,rq,cz,fail_after=i),'injected')
        check('显式新屏障尝试',X.retry(d,rq,cc),'accepted')
        check('新尝试不复用旧目标',d.execute('SELECT count(DISTINCT target_id) FROM aa_target').fetchone()[0],4)
        denied('新尝试未回执不能用旧applied',d,lambda:X.complete(d,'arm.1',cc),'unconfirmed')
        before=C.snapshot(d);check('新尝试重复查原',X.retry(d,rq,cc),'existing');check('新尝试查原零写',C.snapshot(d)==before)
        stale=copy.deepcopy(rq);stale['idempotency_key']='stale';denied('旧previous_plan拒绝',d,lambda:X.retry(d,stale,cc),'stale_attempt')
        observations(d);X.complete(d,'arm.1',cc);check('新屏障完成保留旧失效',d.execute('SELECT observed_state FROM sp_observed_summary WHERE plan_id=?',(old,)).fetchone()[0],'indeterminate')
        denied('已退出不再新尝试',d,lambda:X.retry(d,retry_request(d,'after.exit'),cc),'attempt_prestate')
        d,rr,cc,tt,qq=f(2)
        for ordinal in range(2,17):observations(d,2);X.retry(d,retry_request(d,'retry.'+str(ordinal)),cc);observations(d)
        observations(d,2);denied('第17次超容量保持关闭',d,lambda:X.retry(d,retry_request(d,'retry.17'),cc))
        check('尝试上限没有半计划',d.execute('SELECT count(*) FROM aa_attempt').fetchone()[0],16)
        d,rr,cc,tt,qq=f(3,zero=True);check('零目标可退出',len(X.complete(d,'arm.1',cc)['observations']),0)
        d,rr,cc,tt,qq=f(prepared=True);A.apply(d,lambda:A.complete_steps(d,'arm.1',cc));qq=request(d)
        denied('已armed须走显式disarm协议',d,lambda:X.stop(d,qq,cc),'prestate')
        d,rr,cc,tt,qq=f(prepared=True);P.protect(d,C.fault());qq=request(d);qq['reason']='source_fault';X.stop(d,qq,cc);observations(d);X.complete(d,'arm.1',cc)
        check('来源保护未被退出清除',d.execute('SELECT state FROM ingress_source').fetchone()[0],'desynchronized')
        check('两类保护计划共存',d.execute('SELECT count(*) FROM protection_plan_registry').fetchone()[0],2)
        restore,gates=T.reconcile_preflight(d)
        denied('来源未恢复不能跳过核验',d,lambda:R.reserve(d,restore,gates),'recovery_registration_seal')
        d,rr,cc,tt,qq=f(prepared=True);T.Q.Q.withdraw(d,'registration.a',T.Q.withdrawal(d),T.Q.PROVIDER)
        qq=request(d);qq['reason']='preparation_failed';X.stop(d,qq,cc);observations(d);X.complete(d,'arm.1',cc)
        recovery=T.reconcile(d);C.execute(d,recovery)
        check('资格失败退出后可新代次恢复',tuple(d.execute('SELECT lifecycle,arm_generation FROM run').fetchone()),('armed','2'))
        check('新恢复不删除首失效',d.execute('SELECT count(*) FROM pq_fault').fetchone()[0],1)
        # 原恢复写集使用新预览、新代次和全部当前锁存；提供者仍为显式合成上下文。
        recovery=T.reconcile(db);C.execute(db,recovery)
        check('退出后显式恢复回armed',tuple(db.execute('SELECT lifecycle,dispatch_eligible,arm_generation FROM run').fetchone()),('armed',1,'2'))
        check('恢复保留旧拒绝代次',db.execute('SELECT generation FROM p1_deny').fetchone()[0],'1'.zfill(20))
        check('恢复保留旧退出和预算',(db.execute('SELECT count(*) FROM aa_exit_commit').fetchone()[0],db.execute('SELECT count(*) FROM arm_budget_reservation').fetchone()[0]),(1,1))
        observations(db,2);check('迟到旧保护失效不改新代次',tuple(db.execute('SELECT lifecycle,arm_generation FROM run').fetchone()),('armed','2'))
        for table in G.TABLES:denied(table+'不可删除',db,lambda table=table:C.execute(db,[('DELETE FROM '+table,())]),'immutable')
        check('组合外键完整',list(db.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');args=p.parse_args()
    if args.staged and not args.check_report:p.error('--staged需--check-report')
    path=HERE/'arm-exit-report.json'
    def inputs():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if args.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if args.check_report:
        value=json.loads(subprocess.check_output(['git','show',':'+path.relative_to(ROOT).as_posix()],cwd=ROOT) if args.staged else path.read_bytes());assert value['inputs']==inputs();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();value=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=90,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=inputs())
        if args.report:path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in value.items() if k not in ('checks','inputs')}))
