"""资源关闭通知137表内存参考检查；不运行真实IPC。"""
import argparse,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_protection_outbox as G
import check_result_dependency as D
HERE,ROOT,F,I,B,DIG,U,V,C,Q,R=G.HERE,D.ROOT,D.F,D.I,D.B,D.D,D.U,D.V,D.C,D.Q,D.R
INPUTS=list(dict.fromkeys(D.INPUTS+G.SOURCES+[HERE/n for n in
 ('build_protection_outbox.py','controller-protection-outbox.sql','PROTECTION_OUTBOX.md','check_protection_outbox.py')]))
def attempt(e='exit.0',n=1,rid='r'):
    aid=('' if rid=='r' else rid+'.')+e+'.'+str(n)
    return I('ro_attempt',attempt_id=aid,close_id='close.'+aid,release_id=rid,exit_id=e,ordinal=n,
        message_body=B,validation_body=B,audit_body=B)
def ack(e='exit.0',n=1,rid='r'):
    aid=('' if rid=='r' else rid+'.')+e+'.'+str(n);vid='v.ack.'+aid
    return D.bind([R.validation(vid,'close','close.'+aid,policy='resource-close/1'),
        I('ro_ack',ack_id='ack.'+aid,attempt_id=aid,validation_id=vid,ack_digest=DIG,ack_body=B,audit_body=B)])
def recovery(name='recovery',targets=(('exit.0',1),('exit.1',1)),retired=()):
    steps=D.bind(R.recovery(name,members=('r',)))
    steps[-1:-1]=[I('ro_recovery_target',recovery_id=name,release_id='r',exit_id=e,
        ack_id=None if e in retired else 'ack.'+e+'.'+str(n),retirement_exit_id=e if e in retired else None) for e,n in targets]
    return steps
def run():
    assert (HERE/'controller-protection-outbox.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,expected=expected,observed=actual))
    def tx(db,steps):F.tx(db,D.bind(steps))
    def fresh(stage='incident'):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        db.execute(*F.A.namespace());tx(db,F.P.register());tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        tx(db,V.public(C.initial(),1));tx(db,V.public(C.prepare(),2));tx(db,Q.ordinary(V.public(C.dispatch(),3)))
        tx(db,R.close()+R.settle(kind='effect_resolved')+R.release(kind='module_settled'))
        if stage=='released':return db
        tx(db,[D.H.revoke('v.r')])
        if stage=='incident':return db
        tx(db,R.release(rid='r2',kind='module_settled'))
        if stage=='clear':return db
        for e in ('exit.0','exit.1'):tx(db,[attempt(e)]);F.tx(db,ack(e))
        if stage=='acked':return db
        F.tx(db,recovery());return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    def pending(db):return db.execute('SELECT exit_id FROM ro_pending ORDER BY exit_id').fetchall()
    def protection(db):return db.execute('SELECT release_id FROM cr_device_protection ORDER BY release_id').fetchall()
    try:
        db=fresh();check('137表组合',len(F.snapshot(db)),137)
        check('失效自动生成完整活出口通知',pending(db),[('exit.0',),('exit.1',)])
        check('共享签发切点绑定',db.execute('SELECT issued_revision FROM ro_incident').fetchall(),[(U(1),)])
        before=F.snapshot(db);denied('同源重复不生成新通知',db,[D.H.revoke('v.r')])
        check('通知身份稳定',F.snapshot(db)==before)
        db=fresh('released');before=F.snapshot(db)
        try:F.tx(db,[D.H.revoke('v.r'),('SELECT 1',())],1)
        except RuntimeError:check('撤回与通知全库原子回滚',F.snapshot(db)==before)
        else:raise AssertionError('未注入异常')
        db=fresh('released');db.execute("CREATE TRIGGER fault_target BEFORE INSERT ON ro_target BEGIN SELECT RAISE(ABORT,'injected'); END")
        denied('通知写失败撤回不得半提交',db,[D.H.revoke('v.r')],'injected')
        db=fresh();tx(db,[F.exit_step('exit.new')]);check('保护期间新出口加入通知',pending(db),[('exit.0',),('exit.1',),('exit.new',)])
        db=fresh();tx(db,[attempt()]);check('仅尝试发送不算关闭',pending(db),[('exit.0',),('exit.1',)])
        denied('跳号尝试',db,[attempt(n=3)],'close_attempt_successor')
        tx(db,[attempt(n=2)]);F.tx(db,ack());check('迟到旧ACK不代替新尝试',pending(db),[('exit.0',),('exit.1',)])
        F.tx(db,ack(n=2));check('最新ACK只关闭对应出口',pending(db),[('exit.1',)])
        denied('已关出口不重复发新尝试',db,[attempt(n=3)],'close_not_pending')
        check('关闭ACK不清资源',db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(),[('h',)])
        db=fresh('clear');denied('资源清理不等恢复关闭',db,D.bind(R.recovery(members=('r',))),'recovery_close_set')
        db=fresh('acked');steps=recovery()
        for n in range(len(steps)):
            denied('恢复写集缺写'+str(n),fresh('acked'),steps[:n]+steps[n+1:])
            d=fresh('acked');before=F.snapshot(d)
            try:F.tx(d,steps,n)
            except RuntimeError:check('恢复逐写回滚'+str(n),F.snapshot(d)==before)
            else:raise AssertionError('未注入异常')
        F.tx(db,steps);check('完整关闭加清资源后恢复',protection(db),[])
        denied('已恢复禁止旧通知再发',db,[attempt(n=2)],'close_not_pending')
        tx(db,[F.exit_step('exit.after')]);check('正常恢复后新出口不继承旧关闭',db.execute("SELECT count(*) FROM ro_target WHERE exit_id='exit.after'").fetchone()[0],0)
        tx(db,[D.H.revoke('v.ack.exit.0.1')]);check('关闭证明撤回重新保护',protection(db),[('r',)])
        check('重新保护补新出口并重新关闭已恢复出口',pending(db),[('exit.0',),('exit.1',),('exit.after',)])
        tx(db,[attempt(n=2)]);F.tx(db,ack(n=2));check('新ACK不能自动复用旧恢复',protection(db),[('r',)])
        tx(db,[attempt('exit.after')]);F.tx(db,ack('exit.after'))
        tx(db,[attempt('exit.1',2)]);F.tx(db,ack('exit.1',2))
        F.tx(db,recovery('recovery2',(('exit.0',2),('exit.1',2),('exit.after',1))))
        check('新恢复绑定新关闭证据',protection(db),[])
        db=fresh('recovered');tx(db,[D.H.revoke('v.recovery')])
        check('恢复证明撤回必须重新关闭全部活出口',pending(db),[('exit.0',),('exit.1',)])
        denied('历史已消费ACK不能再次恢复',db,recovery('reuse'),'recovery_close_consumed')
        for e in ('exit.0','exit.1'):tx(db,[attempt(e,2)]);F.tx(db,ack(e,2))
        F.tx(db,recovery('fresh',(('exit.0',2),('exit.1',2))))
        check('重新关闭后可显式恢复',protection(db),[])
        db=fresh('recovered');tx(db,[F.exit_step('exit.after')]);tx(db,[D.H.revoke('v.r2')])
        check('新失效补齐所有历史事件活出口',db.execute('SELECT release_id,exit_id FROM ro_pending ORDER BY 1,2').fetchall(),
            [(r,e) for r in ('r','r2') for e in ('exit.0','exit.1','exit.after')])
        tx(db,R.release(rid='r3',kind='module_settled'))
        selections=[]
        for rid in ('r','r2'):
            for e in ('exit.0','exit.1','exit.after'):
                n=2 if rid=='r' and e!='exit.after' else 1
                tx(db,[attempt(e,n,rid)]);F.tx(db,ack(e,n,rid))
                aid=('' if rid=='r' else rid+'.')+e+'.'+str(n)
                selections.append(I('ro_recovery_target',recovery_id='multi',release_id=rid,exit_id=e,
                    ack_id='ack.'+aid,retirement_exit_id=None))
        steps=D.bind(R.recovery('multi',members=('r','r2')));steps[-1:-1]=selections
        F.tx(db,steps);check('多事件关闭证据完整后恢复',protection(db),[])
        db=fresh('clear')
        for e in ('exit.0','exit.1'):tx(db,[I('ce_retirement',exit_id=e,supervisor_evidence_body=B)])
        check('已退役出口无发送任务',pending(db),[])
        F.tx(db,recovery(retired=('exit.0','exit.1')));check('退役证据可替代关闭ACK',protection(db),[])
        db=fresh();tx(db,[attempt()]);bad=D.X.extra(ack(),'cr_validation',subject_id='wrong')
        denied('ACK错关闭身份',db,bad,'close_ack_binding')
        for table in G.TABLES:
            sample=fresh('recovered')
            denied('不可删除'+table,sample,[('DELETE FROM '+table,())],'immutable_resource_close')
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
        data=json.loads(read(HERE/'protection-outbox-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='137表资源保护通知候选',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'protection-outbox-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
