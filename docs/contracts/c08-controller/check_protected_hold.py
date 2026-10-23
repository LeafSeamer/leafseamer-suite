"""取消独立资源占用内存实验；不运行产品writer或设备。"""
import argparse,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_protected_hold as G
import check_cancel_plan as P
X=P.X;R=X.R;Z=X.X;T=X.T
HERE,ROOT,F,I,B,D,U,V,C,Q=G.HERE,P.ROOT,P.F,P.I,P.B,P.D,P.U,P.V,P.C,P.Q
INPUTS=list(dict.fromkeys(P.INPUTS+G.SOURCES+[HERE/n for n in
 ('build_protected_hold.py','controller-protected-hold.sql','PROTECTED_HOLD.md','check_protected_hold.py')]))

def acquire():
    steps=X.extra(P.plan(),'cg_plan',protected_hold_id='hc',protected_hold_digest=D)
    steps[1:1]=[R.validation('v.hc','hold','hc',policy='cancel.release.policy'),
        I('cr_hold',hold_id='hc',command_id='command.one',attempt_id=None,cancel_execution_id=P.E,
          cancel_release_policy_ref='cancel.release.policy',validation_id='v.hc',hold_digest=D,hold_body=B)]
    steps.append(I('cr_hold_commit',hold_id='hc',audit_body=B,outbox_id='hold.cancel',outbox_body=B))
    return steps

def release(rid='rc',parent=False,cancel_sent=True,hold='hc'):
    steps=R.release(rid=rid,hid=hold,revision=int(parent)+int(cancel_sent),kind='module_settled',
        attempts=(('a','h','close.h'),) if parent else (),members=(('permit.1','s'),) if parent else ())
    if hold=='hc':
        steps=X.extra(steps,'cr_release',cancel_validation_id='own.'+rid)
        steps.insert(0,R.validation('own.'+rid,'release',rid,policy='cancel.release.policy'))
    steps[-1:-1]=[I('cx_release_cancel',release_id=rid,cancellation_id='cancel',closure_validation_id='close.cancel')]+(
        [I('cx_release_member',release_id=rid,permit_id='cancel.1',settlement_id='cs')] if cancel_sent else [])
    return steps

def revoke(vid):return I('cr_validation_revocation',validation_id=vid,reason_body=B,audit_body=B)

def run():
    assert (HERE/'controller-protected-hold.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,expected=expected,observed=actual))
    def fresh(stage='held',parent=False):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        db.execute(*F.A.namespace());F.tx(db,F.P.register());F.tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'));F.tx(db,V.public(C.initial(),1))
        if parent:
            F.tx(db,V.public(C.prepare(),2));F.tx(db,Q.ordinary(V.public(C.dispatch(),3)))
        F.tx(db,F.P.mutate(V.cancel(4 if parent else 2,attempts=('a',) if parent else (),
            permits=('permit.1',) if parent else (),cut=int(parent),state_args=V.SENT if parent else None),'cv_cancel','mode','cooperative'))
        F.tx(db,X.extra(X.cut(members=[('permit.1','exit.0',0)] if parent else []),'cc_cut',issued_revision=U(int(parent))))
        for e in ('exit.0','exit.1'):
            F.tx(db,[X.attempt(eid=e)]);F.tx(db,[s for s in X.ack(eid=e) if parent or not s[0].startswith('INSERT INTO cc_coverage ')])
        F.tx(db,X.closure())
        if stage=='empty':return db
        F.tx(db,acquire())
        if stage=='held':return db
        F.tx(db,P.prepare('primitive.cancel'));F.tx(db,P.dispatch(n=1+int(parent)))
        if stage=='sent':return db
        F.tx(db,X.extra(X.cut('all',members=([('permit.1','exit.0',0)] if parent else [])+[
            ('cancel.1','exit.0',0)],prepares=['prep.primitive.cancel']),'cc_cut',issued_revision=U(1+int(parent))))
        for e in ('exit.0','exit.1'):
            F.tx(db,[X.attempt('all',e)])
            steps=X.extra(X.ack('all',e),'cc_ack_prepare',prepare_id='prep.primitive.cancel')
            if not parent:steps=[s for s in steps if not(s[0].startswith('INSERT INTO cc_coverage ') and 'permit.1' in s[1])]
            F.tx(db,steps)
        F.tx(db,X.closure('all'))
        state=V.SENT if parent else dict(resource='held')
        F.tx(db,X.extra(V.progress(5 if parent else 3,2,'indeterminate','closed',state),'cv_cancel_revision',closure_id='close.all'))
        F.tx(db,Z.closure())
        if parent:F.tx(db,R.close()+R.settle(kind='effect_resolved'))
        F.tx(db,[T.report(state='not_sent')]+Z.settlement())
        if stage=='closed':return db
        F.tx(db,release(parent=parent))
        if parent:F.tx(db,release('rp',parent=True,hold='h'))
        return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    def atomic(name,stage,steps):
        for n in range(len(steps)):
            denied(name+'缺写'+str(n),fresh(stage),steps[:n]+steps[n+1:])
            db=fresh(stage);before=F.snapshot(db)
            try:F.tx(db,steps,n)
            except RuntimeError:check(name+'主动异常回滚'+str(n),F.snapshot(db)==before)
            else:raise AssertionError('未注入异常')
    def risks(db):return db.execute('SELECT hold_id FROM cr_risk_hold ORDER BY hold_id').fetchall()
    try:
        db=fresh();check('仍为129表同权威',len(F.snapshot(db)),129)
        check('父命令未发送可保护',risks(db),[('hc',)])
        check('没有伪造普通attempt',db.execute('SELECT count(*) FROM ce_attempt').fetchone()[0],0)
        check('未发送占用不公开旧clear',db.execute('SELECT count(*) FROM cm_current').fetchone()[0],0)
        db=fresh(parent=True);check('父普通与取消占用并存',risks(db),[('h',),('hc',)])
        atomic('计划与独立占用','empty',acquire());atomic('双政策释放','closed',release())
        db=fresh('empty');denied('错父命令',db,X.extra(acquire(),'cr_hold',command_id='missing'),'protected_hold_binding')
        denied('错占用摘要',fresh('empty'),X.extra(acquire(),'cg_plan',protected_hold_digest='sha256:'+'f'*64),'protected_hold_binding')
        denied('普通attempt与取消身份不可同时存在',fresh('empty'),X.extra(acquire(),'cr_hold',attempt_id='fake'))
        db=fresh();F.tx(db,[revoke('v.hc')]);F.tx(db,P.prepare('primitive.cancel'))
        denied('占用准入撤回后禁止发送',db,P.dispatch(n=1),'protected_hold_unavailable')
        db=fresh();F.tx(db,P.prepare('primitive.cancel'));steps=P.dispatch(n=1);steps.insert(-1,revoke('v.hc'))
        denied('签发中撤回不得提交',db,steps,'protected_hold_unavailable')
        for parent in (False,True):
            db=fresh('released',parent);check('释放两类占用'+str(parent),risks(db),[])
            F.tx(db,[revoke('own.rc')]);check('自身政策撤回重开取消占用'+str(parent),risks(db),[('hc',)])
            check('沿原保护视图锁设备'+str(parent),db.execute('SELECT count(*) FROM cr_device_protection').fetchone()[0],1)
        db=fresh('closed');denied('缺独立释放政策证明',db,X.extra(release(),'cr_release',cancel_validation_id=None),'protected_release_policy')
        denied('错误独立政策',db,X.extra(release(),'cr_validation',policy_ref='wrong'))
        db=fresh('held');F.tx(db,V.public(C.initial('other'),1,'other'));F.tx(db,V.public(C.prepare('other','oa',n=2),2,'other'))
        denied('取消占用阻挡无关普通命令',db,Q.ordinary(V.public(C.dispatch('other','oa','oh','op',n=3,issued=1,attempts=('oa',)),3,'other')))
        db=fresh('empty');F.tx(db,V.public(C.initial('other'),1,'other'));F.tx(db,V.public(C.prepare('other','oa',n=2),2,'other'))
        F.tx(db,Q.ordinary(V.public(C.dispatch('other','oa','oh','op',n=3,issued=1,attempts=('oa',)),3,'other')))
        denied('无关普通占用阻挡取消准入',db,acquire(),'resource_busy')
        db=fresh('released');F.tx(db,[revoke('own.rc')]);F.tx(db,release('rc2'))
        check('新释放清风险不清锁存',risks(db),[])
        check('恢复前仍有保护',db.execute('SELECT count(*) FROM cr_device_protection').fetchone()[0],1)
        F.tx(db,R.recovery(members=('rc',)));check('显式恢复清保护',db.execute('SELECT count(*) FROM cr_device_protection').fetchone()[0],0)
        F.tx(db,[revoke('own.rc2')]);check('旧恢复不覆盖新失效',db.execute('SELECT count(*) FROM cr_device_protection').fetchone()[0],1)
        db=fresh('released');F.tx(db,V.public(C.revision(4,'observe',releases=('rc',)),4,cancel='cancel',cancel_revision=2))
        F.tx(db,V.public(C.initial('other'),1,'other'));F.tx(db,V.public(C.prepare('other','oa',n=2),2,'other'))
        F.tx(db,Q.ordinary(V.public(C.dispatch('other','oa','oh','op',n=3,issued=2,attempts=('oa',)),3,'other')))
        F.tx(db,[revoke('own.rc')]);check('晚撤回保留两份风险占用',risks(db),[('hc',),('oh',)])
        check('晚撤回未丢新普通许可',db.execute("SELECT count(*) FROM ce_permit WHERE permit_id='op'").fetchone()[0],1)
        db=fresh(parent=True)
        denied('取消仍禁止新普通占用',db,[I('cr_hold',hold_id='fake',command_id='command.one',attempt_id='a',
            validation_id='v.h',hold_digest=D,hold_body=B)],'command_cancelled')
        for d in connections:
            assert d.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert d.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('所有内存库完整性',True);return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(HERE/'protected-hold-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='129表独立取消占用同权威候选',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'protected-hold-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
