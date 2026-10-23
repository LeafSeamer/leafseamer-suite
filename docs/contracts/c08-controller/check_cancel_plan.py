"""取消图129表内存契约检查；不连接服务、网络、设备或磁盘数据库。"""
import argparse,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_cancel_plan as G
import check_cancel_closure as X
HERE,ROOT,F,I,B,D,U,V,C,Q=G.HERE,X.ROOT,X.F,X.I,X.B,X.D,X.U,X.V,X.C,X.Q
INPUTS=list(dict.fromkeys(X.INPUTS+G.SOURCES+[HERE/n for n in
 ('build_cancel_plan.py','controller-cancel-plan.sql','CANCEL_PLAN.md','check_cancel_plan.py')]))
E='execution.cancel'

def plan():
    return [I('cg_plan',execution_id=E,cancellation_id='cancel',ordinary_closure_id='close.ordinary',
        execution_digest=D,policy_ref_body=B,protected_hold_ref_body=B,resource_count=1,
        primitive_count=3,dependency_count=2,plan_body=B),
        I('cg_resource',execution_id=E,resource_key='device')]+[
        I('cg_primitive',execution_id=E,primitive_id=p,position=n,action_ref_body=B,
          parameters_schema_ref_body=B,parameters_body=B,completion_policy_ref_body=B)
        for n,p in enumerate(('primitive.cancel','second','third'),1)]+[
        I('cg_dependency',execution_id=E,primitive_id=p,predecessor_id=q)
        for p,q in (('second','primitive.cancel'),('third','second'))]+[
        I('cg_plan_commit',execution_id=E,provider_ref_body=B,validation_body=B,audit_body=B)]

def prepare(p):
    return X.extra([X.prepare()],'cc_prepare',prepare_id='prep.'+p,primitive_id=p,outbox_id='prepare.'+p)+X.extra(
        [X.packet()],'cc_packet',packet_id='packet.'+p,prepare_id='prep.'+p)

def dispatch(p='primitive.cancel',pid='cancel.1',n=2,ordinal=0,initial=None,deps=()):
    steps=X.extra(Q.cancel(pid,n,ordinal,initial),'ci_cancel_transmission',primitive_id=p,packet_id='packet.'+p)
    steps.insert(-1,I('cc_dispatch',permit_id=pid,packet_id='packet.'+p))
    steps[-1:-1]=[I('cg_dispatch_dependency',permit_id=pid,execution_id=E,primitive_id=p,
        predecessor_id=q,result_id=r) for q,r in deps]
    return steps

def result(p='primitive.cancel',rid='result.1',n=2,members=('cancel.1',),state='succeeded'):
    return [I('cg_result',result_id=rid,execution_id=E,primitive_id=p,disposition=state,
        evidence_kind={'succeeded':'protocol_effect','failed':'definite_failure','unknown':'indeterminate'}[state],
        evidence_digest=D,evidence_body=B,completion_policy_ref_body=B,issued_revision=U(n))]+[
        I('cg_result_member',result_id=rid,permit_id=k) for k in members]+[
        I('cg_result_commit',result_id=rid,provider_ref_body=B,validation_body=B,audit_body=B,
          outbox_id='result.'+rid,outbox_body=B)]

def revoke(rid='result.1'):
    return I('cg_revocation',result_id=rid,reason_body=B,audit_body=B,outbox_id='revoked.'+rid,outbox_body=B)

def run():
    assert (HERE/'controller-cancel-plan.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,observed,expected=True):
        assert observed==expected,(name,observed,expected)
        checks.append(dict(name=name,expected=expected,observed=observed))
    def fresh(stage='sent'):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        db.execute(*F.A.namespace());F.tx(db,F.P.register());F.tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        F.tx(db,V.public(C.initial(),1));F.tx(db,V.public(C.prepare(),2));F.tx(db,Q.ordinary(V.public(C.dispatch(),3)))
        F.tx(db,F.P.mutate(V.cancel(4,attempts=('a',),permits=('permit.1',),cut=1,state_args=V.SENT),'cv_cancel','mode','cooperative'))
        F.tx(db,X.cut())
        for e in ('exit.0','exit.1'):F.tx(db,[X.attempt(eid=e)]);F.tx(db,X.ack(eid=e))
        F.tx(db,X.closure())
        if stage=='unplanned':return db
        F.tx(db,plan())
        if stage=='planned':return db
        for p in ('primitive.cancel','second','third'):F.tx(db,prepare(p))
        if stage=='prepared':return db
        F.tx(db,dispatch())
        if stage=='sent':return db
        F.tx(db,result());return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 必须拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    def atomic(name,stage,steps):
        for n in range(len(steps)):
            db=fresh(stage);denied(name+'缺写'+str(n),db,steps[:n]+steps[n+1:])
            db=fresh(stage);before=F.snapshot(db)
            try:F.tx(db,steps,n)
            except RuntimeError as e:check(name+'异常'+str(n),str(e),'injected_before_commit')
            else:raise AssertionError('未注入异常')
            check(name+'回滚'+str(n),F.snapshot(db)==before)
    try:
        db=fresh();check('129表组合',len(F.snapshot(db)),129)
        atomic('完整动作图','unplanned',plan());atomic('完成原件','sent',result())
        atomic('后继发送','succeeded',dispatch('second','cancel.2',3,deps=(('primitive.cancel','result.1'),)))
        db=fresh('unplanned');denied('未登记图不可准备',db,prepare('primitive.cancel'),'prepare_plan_binding')
        denied('未登记图不可发送',db,dispatch(),'send_plan_binding')
        for label,fields in [('错执行摘要',dict(execution_digest='sha256:'+'f'*64)),('错动作',dict(primitive_id='absent'))]:
            db=fresh('planned');denied(label,db,X.extra(prepare('primitive.cancel'),'cc_prepare',**fields),'prepare_plan_binding')
        for p,q in [('primitive.cancel','third'),('second','second')]:
            steps=plan();steps.insert(-1,I('cg_dependency',execution_id=E,primitive_id=p,predecessor_id=q))
            denied('逆边或自环'+p,fresh('unplanned'),steps,'plan_not_dag')
        db=fresh('unplanned');steps=plan();steps[0]=X.extra([steps[0]],'cg_plan',primitive_count=4)[0]
        denied('动作数量不符',db,steps,'plan_projection_incomplete')
        db=fresh('planned');denied('冻结后不得补边',db,[I('cg_dependency',execution_id=E,primitive_id='third',predecessor_id='primitive.cancel')],'plan_frozen')
        for state in ('failed','unknown'):
            db=fresh();F.tx(db,result(state=state));check(state+'锁存',db.execute('SELECT count(*) FROM cg_stopped').fetchone()[0],1)
            denied(state+'禁止后继',db,dispatch('second','cancel.2',3,deps=(('primitive.cancel','result.1'),)),'cancel_plan_stopped')
            denied(state+'不能迟到改成功',db,result(rid='later'))
        db=fresh('prepared');F.tx(db,result(n=1,members=(),state='failed'))
        check('发送前确定失败仍可记录',db.execute('SELECT count(*) FROM cg_stopped').fetchone()[0],1)
        denied('无发送不能成功',fresh('prepared'),result(n=1,members=()),'success_without_transmission')
        denied('仅传输ACK不证明成功',fresh(),X.extra(result(),'cg_result',evidence_kind='transport_ack'))
        denied('策略错配',fresh(),X.extra(result(),'cg_result',completion_policy_ref_body=b'wrong'),'result_policy_binding')
        denied('遗漏传输',fresh(),result(members=()),'result_transmission_set')
        denied('未来水位',fresh(),result(n=3),'result_watermark')
        db=fresh();F.tx(db,dispatch(pid='resend.1',n=3,ordinal=1,initial='cancel.1'))
        denied('不得省略重传历史',db,result(n=3),'result_transmission_set')
        F.tx(db,result(n=3,members=('cancel.1','resend.1')))
        check('完整重传历史可成功',db.execute('SELECT count(*) FROM cg_valid_success').fetchone()[0],1)
        denied('成功后不能重传',db,dispatch(pid='resend.2',n=4,ordinal=2,initial='cancel.1'),'cancel_plan_stopped')
        denied('后继不可无证据派发',fresh('succeeded'),dispatch('second','cancel.2',3),'dependency_not_satisfied')
        db=fresh();denied('未完成不能伪指结果',db,dispatch('second','cancel.2',3,deps=(('primitive.cancel','absent'),)))
        db=fresh('succeeded');F.tx(db,dispatch('second','cancel.2',3,deps=(('primitive.cancel','result.1'),)))
        F.tx(db,result('second','result.2',3,('cancel.2',)))
        F.tx(db,[revoke()]);check('撤回祖先锁存执行',db.execute('SELECT count(*) FROM cg_stopped').fetchone()[0],1)
        denied('直接前驱仍成功也不能越过祖先撤回',db,dispatch('third','cancel.3',4,deps=(('second','result.2'),)),'cancel_plan_stopped')
        check('撤回不改后继历史成功',db.execute("SELECT disposition FROM cg_result WHERE result_id='result.2'").fetchone()[0],'succeeded')
        db=fresh('succeeded');before=F.snapshot(db)
        try:F.tx(db,[revoke()],0)
        except RuntimeError:pass
        check('撤回与保护通知回滚配对',F.snapshot(db)==before)
        # permit已经写入但commit前发生撤回，仍不得提交新派发。
        steps=dispatch('second','cancel.2',3,deps=(('primitive.cancel','result.1'),));steps.insert(-1,revoke())
        denied('签发中撤回不能绕过最终检查',db,steps,'cancel_plan_stopped')
        db=fresh('planned');F.tx(db,[X.revoke('close.ordinary')]);denied('关闭撤回不能准备',db,prepare('primitive.cancel'))
        db=fresh('unplanned');F.tx(db,X.extra(X.cut('all',members=[('permit.1','exit.0',0)],prepares=[]),'cc_cut',issued_revision=U(1)))
        denied('all切点后不能新建图',db,plan(),'plan_not_admissible')
        # SQL不解释可信BODY，显式记录该限制，不能据此宣称已验证真实提供者。
        db=fresh('succeeded');check('合成BODY通过仅为约束边界',db.execute('SELECT plan_body FROM cg_plan').fetchone()[0]==B)
        F.tx(db,dispatch('second','cancel.2',3,deps=(('primitive.cancel','result.1'),)));F.tx(db,[revoke()])
        for table in G.TABLES:
            assert db.execute('SELECT 1 FROM '+table).fetchone(),table
            col=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for sql in (f'UPDATE {table} SET {col}={col}',f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                denied(table+sql.split()[0],db,[(sql,())])
        for d in connections:
            assert d.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert d.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('全部内存库完整性',True);return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(HERE/'cancel-plan-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='129表取消动作图与完成原件候选',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'cancel-plan-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
