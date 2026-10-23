"""103表取消资源写集、迟到证据及恢复的内存参考检查。"""
import argparse,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_cancel_resource as G
import check_cancel_fence as T
HERE,ROOT,F,I,B,D,U,V,C,Q=G.HERE,T.ROOT,T.F,T.I,T.B,T.D,T.U,T.V,T.C,T.Q
R=C.R
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in
 ('build_cancel_resource.py','controller-cancel-resource.sql','CANCEL_RESOURCE.md','check_cancel_resource.py')]))

def closure(vid='close.cancel'):
    return [R.validation(vid,'close','cancel'),I('cx_closure',cancellation_id='cancel',operation_revision=U(2),
        validation_id=vid,closure_digest=D,closure_body=B)]
def settlement(sid='cs',kind='never_sent',vid=None,pid='cancel.1'):
    vid=vid or 'v.'+sid
    return [T.settle(pid=pid,sid=sid,kind=kind),R.validation(vid,'settlement',sid),
        I('cx_settlement',settlement_id=sid,validation_id=vid,settlement_digest=D)]
def release(rid='r',sid='cs',vid='close.cancel'):
    steps=R.release(rid=rid,revision=2,kind='module_settled')
    return steps[:-1]+[I('cx_release_cancel',release_id=rid,cancellation_id='cancel',closure_validation_id=vid),
        I('cx_release_member',release_id=rid,permit_id='cancel.1',settlement_id=sid)]+steps[-1:]
def cut(count=1):
    steps=F.fence(revision=count+1)
    at=next(i for i,s in enumerate(steps) if s[0].startswith('INSERT INTO ce_cut_commit '))
    steps[at:at]=[I('cf_run_item',fence_id='f',permit_id='cancel.'+str(n),exit_id='exit.0',entered_known=0) for n in range(1,count+1)]
    return steps

def run():
    assert (HERE/'controller-cancel-resource.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,expected=expected,observed=actual))
    def fresh(stage='settled',count=1):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        db.execute(*F.A.namespace());F.tx(db,F.P.register());F.tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        F.tx(db,V.public(C.initial(),1));F.tx(db,V.public(C.prepare(),2));F.tx(db,Q.ordinary(V.public(C.dispatch(),3)))
        if stage=='ordinary':return db
        state=dict(phase='dispatching',effect='possible',resource='held',attempts=('a',))
        F.tx(db,F.P.mutate(V.cancel(4,attempts=('a',),permits=('permit.1',),cut=1,state_args=state),'cv_cancel','mode','cooperative'))
        F.tx(db,Q.cancel(origin='automation'))
        for n in range(2,count+1):F.tx(db,Q.cancel('cancel.'+str(n),n+1,n-1,'cancel.1',origin='automation'))
        F.tx(db,cut(count));F.tx(db,[T.BA.attempt()])
        if stage=='open':return db
        F.tx(db,V.progress(5,2,'indeterminate','closed',state_args=state));F.tx(db,closure())
        if stage=='closed':return db
        F.tx(db,R.close()+R.settle(kind='effect_resolved')+[T.report(state='not_sent')]+settlement())
        if stage=='released':F.tx(db,release())
        return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 必须拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    def risks(db):return [r[0] for r in db.execute('SELECT hold_id FROM cr_risk_hold ORDER BY hold_id')]
    def protected(db):return [r[0] for r in db.execute('SELECT release_id FROM cr_device_protection ORDER BY release_id')]
    try:
        db=fresh();check('103表组合',len(F.snapshot(db)),103);check('未释放仍占用',risks(db),['h'])
        steps=release()
        for n in range(len(steps)):
            db=fresh();denied('完整释放缺写'+str(n),db,steps[:n]+steps[n+1:])
            db=fresh();before=F.snapshot(db)
            try:F.tx(db,steps,n)
            except RuntimeError as e:check('主动异常'+str(n),str(e),'injected_before_commit')
            else:raise AssertionError('未发生异常')
            check('异常全部103表回滚'+str(n),F.snapshot(db)==before)
        db=fresh('open');denied('ordinary关闭不能冒充all',db,closure(),'cancel_all_closure_binding')
        db=fresh('closed')
        denied('未核销不清资源',db,release())
        db=fresh();F.tx(db,release());check('两类历史齐全可释放',risks(db),[])
        db=fresh('ordinary');F.tx(db,R.close()+R.settle(kind='effect_resolved'))
        F.tx(db,R.release(revision=1,kind='module_settled'))
        check('103表普通路径无取消也可释放',risks(db),[])
        db=fresh('released');F.tx(db,[T.report(rid='late.not.sent',state='not_sent')])
        check('迟到未发不制造资源失效',protected(db),[])
        denied('释放后不得补取消传输',db,Q.cancel('later',3,1,'cancel.1',origin='automation'),'cancel_after_release')
        for table,field,value,error in [('cx_release_member','permit_id','permit.1',None),
          ('cx_release_member','settlement_id','missing',None),('cx_release_cancel','cancellation_id','missing',None),
          ('cr_release','issued_cut_revision',U(1),'release_binding')]:
            db=fresh();denied('成员关联'+field,db,F.P.mutate(release(),table,field,value),error)
        db=fresh(count=2);F.tx(db,settlement('cs2','effect_resolved',pid='cancel.2'))
        two=F.P.mutate(release(),'cr_release','issued_cut_revision',U(3))
        denied('历史重传不能漏掉',db,two,'cancel_release_permit_set')
        two.insert(-1,I('cx_release_member',release_id='r',permit_id='cancel.2',settlement_id='cs2'))
        wrong=list(two);wrong[-2]=I('cx_release_member',release_id='r',permit_id='cancel.2',settlement_id='cs')
        denied('重传不能借初始核销',db,wrong,'cancel_release_member_unproven')
        F.tx(db,two);check('已核销历史亦完整保留',db.execute('SELECT count(*) FROM cx_release_member').fetchone()[0],2)
        wrong_digest='sha256:'+'b'*64
        assert wrong_digest!=D,'反例摘要必须不同于原件'
        for field,value in [('operation_revision',U(1)),('closure_digest',wrong_digest)]:
            db=fresh();denied('关闭原件关联'+field,db,F.P.mutate(closure('new.close'),'cx_closure',field,value),'cancel_all_closure_binding')
        db=fresh();bad=F.P.mutate(closure('new.close'),'cr_validation','subject_id','other')
        denied('关闭提供者必须绑定原取消',db,bad,'cancel_all_closure_binding')
        for table,field,value in [('cx_settlement','settlement_digest',wrong_digest),
          ('cr_validation','subject_id','other'),('cr_validation','purpose','close'),
          ('cr_validation','device_id','other')]:
            db=fresh();denied('核销提供者关联'+field,db,
                F.P.mutate(settlement('new.cs'),table,field,value),'cancel_settlement_binding')
        db=fresh();st=release();st.insert(-1,I('cr_validation_revocation',validation_id='v.cs',reason_body=B,audit_body=B))
        denied('封存前撤回不能释放',db,st,'cancel_release_member_unproven')
        db=fresh();st=release();st.insert(-1,I('cr_validation_revocation',validation_id='close.cancel',reason_body=B,audit_body=B))
        denied('封存前关闭证明撤回',db,st,'cancel_closure_revoked')
        for vid in ('close.cancel','v.cs','v.r'):
            db=fresh('released');step=I('cr_validation_revocation',validation_id=vid,reason_body=B,audit_body=B)
            before=F.snapshot(db)
            try:F.tx(db,[step],0)
            except RuntimeError:check('撤回原子回滚'+vid,F.snapshot(db)==before)
            else:raise AssertionError('没有故障')
            F.tx(db,[step]);check('撤回重开占用'+vid,risks(db),['h']);check('撤回锁存保护'+vid,protected(db),['r'])
        for kind in ('report','ack','target'):
            db=fresh('released')
            if kind=='report':steps=[T.report(rid='late')]
            elif kind=='ack':steps=T.ack(items=(('cancel.1','in_flight'),))
            else:
                db.execute(*I('ce_retirement',exit_id='exit.0',supervisor_evidence_body=B))
                steps=T.select(kind='supervisor_retired',items=(('cancel.1','in_flight'),))
            before=F.snapshot(db)
            try:F.tx(db,steps,len(steps)-1)
            except RuntimeError:check('迟到与失效同回滚'+kind,F.snapshot(db)==before)
            else:raise AssertionError('没有故障')
            F.tx(db,steps);check('迟到重开资源'+kind,risks(db),['h']);check('迟到锁存设备'+kind,protected(db),['r'])
            check('迟到不抹旧释放'+kind,db.execute('SELECT count(*) FROM cr_release_commit').fetchone()[0],1)
        # 修复写新完整释放，旧失效锁存必须显式恢复，恢复不能重放设备动作。
        db=fresh('released');F.tx(db,[T.report(rid='late')])
        denied('未核销不能恢复',db,R.recovery(),'recovery_resource_busy')
        F.tx(db,settlement('fixed','effect_resolved')+release('r.fixed','fixed'))
        check('新释放可消除占用',risks(db),[]);check('旧保护仍锁存',protected(db),['r'])
        denied('恢复不能漏旧失效',db,R.recovery(members=()),'recovery_protection_set')
        F.tx(db,R.recovery());check('完整恢复才解锁',protected(db),[])
        check('历史终态未改写',db.execute('SELECT state,future_writes FROM cv_cancel_current').fetchone(),('indeterminate','closed'))
        # later in_flight不能撤回独立效果核销；撤回其提供者证明则再次锁存。
        F.tx(db,[T.report(rid='later')]);check('效果核销不被重复传输报告推翻',risks(db),[])
        F.tx(db,[I('cr_validation_revocation',validation_id='v.fixed',reason_body=B,audit_body=B)])
        check('新撤回不被旧恢复覆盖',protected(db),['r.fixed'])
        check('资源再次未决',risks(db),['h'])
        denied('新恢复不能遗漏新失效',db,R.recovery('second',members=('r',)))
        db=fresh('released')
        for table in G.TABLES:
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for sql in (f'UPDATE {table} SET {column}={column}',f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                denied(table+sql.split()[0],db,[(sql,())])
        for d in connections:
            assert d.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert d.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('全部内存库FK与完整性',True)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(HERE/'cancel-resource-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='103表取消资源核销候选',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'cancel-resource-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
