"""结果依赖与撤回扇出内存实验；不访问真实设备或业务数据库。"""
import argparse,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_result_dependency as G
import check_protected_hold as H
P,X,R,Z,T=H.P,H.X,H.R,H.Z,H.T
HERE,ROOT,F,I,B,D,U,V,C,Q=G.HERE,H.ROOT,H.F,H.I,H.B,H.D,H.U,H.V,H.C,H.Q
INPUTS=list(dict.fromkeys(H.INPUTS+G.SOURCES+[HERE/n for n in
 ('build_result_dependency.py','controller-result-dependency.sql','RESULT_DEPENDENCY.md','check_result_dependency.py')]))

def manifest(vid,sources=(),basis=None,provider='trusted.fixture'):
    return [I('cd_manifest',validation_id=vid,basis=basis or ('cancel_result' if sources else 'independent'),
        source_count=len(sources),manifest_digest=D,manifest_body=B)]+[
        I('cd_result_source',validation_id=vid,result_id=s,result_digest=D) for s in sources]+[
        I('cd_manifest_commit',validation_id=vid,provider_ref=provider,manifest_digest=D,receipt_body=B,audit_body=B)]

def bind(steps,sources=None):
    out=[]
    for sql,args in steps:
        out.append((sql,args))
        if sql.startswith('INSERT INTO cr_validation '):
            v=dict(zip(sql.split('(',1)[1].split(')',1)[0].split(','),args))
            out+=manifest(v['validation_id'],(sources or {}).get(v['validation_id'],()))
    return out

def release(rid='rc',hold='hc',sources=None):
    steps=R.release(rid=rid,hid=hold,revision=3,kind='module_settled')
    if hold=='hc':
        steps=X.extra(steps,'cr_release',cancel_validation_id='own.'+rid)
        steps.insert(0,R.validation('own.'+rid,'release',rid,policy='cancel.release.policy'))
    steps[-1:-1]=[I('cx_release_cancel',release_id=rid,cancellation_id='cancel',closure_validation_id='close.cancel')]+[
        I('cx_release_member',release_id=rid,permit_id=p,settlement_id=s) for p,s in (('cancel.1','cs'),('cancel.2','cs2'))]
    return bind(steps,sources)

def run():
    assert (HERE/'controller-result-dependency.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,expected=expected,observed=actual))
    def tx(db,steps):F.tx(db,bind(steps))
    def fresh(stage='evidence',state='succeeded'):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        db.execute(*F.A.namespace());tx(db,F.P.register());tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        tx(db,V.public(C.initial(),1));tx(db,V.public(C.prepare(),2));tx(db,Q.ordinary(V.public(C.dispatch(),3)))
        tx(db,F.P.mutate(V.cancel(4,attempts=('a',),permits=('permit.1',),cut=1,state_args=V.SENT),'cv_cancel','mode','cooperative'))
        tx(db,X.cut())
        for e in ('exit.0','exit.1'):tx(db,[X.attempt(eid=e)]);tx(db,X.ack(eid=e))
        tx(db,X.closure());tx(db,H.acquire());tx(db,P.prepare('primitive.cancel'));tx(db,P.dispatch())
        tx(db,P.result(state=state))
        if stage=='first':return db
        tx(db,P.prepare('second'));tx(db,P.dispatch('second','cancel.2',3,deps=(('primitive.cancel','result.1'),)))
        tx(db,P.result('second','result.2',3,('cancel.2',)))
        if stage=='evidence':return db
        tx(db,X.extra(X.cut('all',members=[('permit.1','exit.0',0),('cancel.1','exit.0',0),('cancel.2','exit.0',0)],
            prepares=['prep.primitive.cancel','prep.second']),'cc_cut',issued_revision=U(3)))
        for e in ('exit.0','exit.1'):
            tx(db,[X.attempt('all',e)])
            steps=X.extra(X.ack('all',e),'cc_ack_prepare',prepare_id='prep.primitive.cancel')
            if e=='exit.0':steps[-1:-1]=[
                I('cc_coverage',barrier_id='all.'+e,cut_id='all',exit_id=e,permit_id='cancel.2',disposition='unknown',proof='send_uncertain'),
                I('cc_ack_prepare',barrier_id='all.'+e,cut_id='all',exit_id=e,prepare_id='prep.second')]
            tx(db,steps)
        tx(db,X.closure('all'));tx(db,X.extra(V.progress(5,2,'indeterminate','closed',V.SENT),'cv_cancel_revision',closure_id='close.all'))
        tx(db,Z.closure());tx(db,R.close()+R.settle(kind='effect_resolved'))
        tx(db,Z.settlement(kind='effect_resolved'));tx(db,Z.settlement('cs2',kind='effect_resolved',pid='cancel.2'))
        if stage=='closed':return db
        F.tx(db,release(sources={'own.rc':('result.2',)}));F.tx(db,release('rp','h',{'v.rp':('result.1',)}))
        return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    def risks(db):return db.execute('SELECT hold_id FROM cr_risk_hold ORDER BY hold_id').fetchall()
    def affected(db,rid):return db.execute('SELECT validation_id FROM cd_affected_validation WHERE result_id=? ORDER BY validation_id',(rid,)).fetchall()
    try:
        db=fresh();check('132表完整组合',len(F.snapshot(db)),132)
        steps=[R.validation('test','release','subject')]+manifest('test',('result.2',))
        F.tx(db,steps);check('递归采用含祖先',affected(db,'result.1'),[('test',)])
        check('直接结果仍可独立定位',affected(db,'result.2'),[('test',)])
        db=fresh();tx(db,P.prepare('third'));tx(db,P.dispatch('third','cancel.3',4,deps=(('second','result.2'),)))
        tx(db,P.result('third','result.3',4,('cancel.3',)))
        F.tx(db,[R.validation('deep','release','deep')]+manifest('deep',('result.3',)))
        check('三层祖先完整闭包',db.execute("SELECT result_id FROM cd_affected_validation WHERE validation_id='deep' ORDER BY result_id").fetchall(),[('result.1',),('result.2',),('result.3',)])
        tx(db,[P.revoke()]);check('三层撤回到验证',db.execute("SELECT count(*) FROM cr_validation_revocation WHERE validation_id='deep'").fetchone()[0],1)
        db=fresh();F.tx(db,[R.validation('both','release','both')]+manifest('both',('result.1','result.2')))
        check('直接及间接同源去重',affected(db,'result.1'),[('both',)])
        denied('重复直接来源',fresh(),[R.validation('both','release','both')]+manifest('both',('result.1','result.1')))
        for n in range(len(steps)):
            denied('来源写集缺写'+str(n),fresh(),steps[:n]+steps[n+1:])
            db=fresh();before=F.snapshot(db)
            try:F.tx(db,steps,n)
            except RuntimeError:check('来源写集主动异常'+str(n),F.snapshot(db)==before)
            else:raise AssertionError('未注入异常')
        for name,table,fields in (
            ('错父命令','cr_validation',{'command_id':'command.other'}),
            ('错设备','cr_validation',{'device_id':'wrong'}),
            ('错结果摘要','cd_result_source',{'result_digest':'sha256:'+'f'*64}),
            ('错提供者','cd_manifest_commit',{'provider_ref':'other'}),
            ('错回执','cd_manifest_commit',{'receipt_body':b'other'}),
            ('错清单摘要','cd_manifest_commit',{'manifest_digest':'sha256:'+'f'*64}),
            ('少来源','cd_manifest',{'source_count':2}),
            ('结果来源伪装独立','cd_manifest',{'basis':'independent'})):
            denied(name,fresh(),X.extra(steps,table,**fields))
        denied('非独立空清单',fresh(),[R.validation('test','release','subject')]+manifest('test',basis='cancel_result'))
        for state in ('failed','unknown'):
            denied(state+'不授释放来源',fresh('first',state),[R.validation('test','release','subject')]+manifest('test',('result.1',)),'dependency_result_binding')
        db=fresh();tx(db,[P.revoke()]);denied('祖先已撤回不能封存',db,steps,'dependency_revoked')
        db=fresh();during=steps[:-1]+[P.revoke()]+steps[-1:]
        denied('成员预写后祖先撤回',db,during,'dependency_revoked')
        db=fresh();F.tx(db,steps)
        denied('封存后不能补来源',db,[I('cd_result_source',validation_id='test',result_id='result.1',result_digest=D)],'dependency_manifest_frozen')
        for table in G.TABLES:
            denied('不可更改'+table,db,[('UPDATE '+table+' SET validation_id=validation_id',())],'immutable_dependency')
            denied('不可删除'+table,db,[('DELETE FROM '+table,())],'immutable_dependency')
        db=fresh('released');check('初始两占用已释放',risks(db),[])
        before=F.snapshot(db)
        try:F.tx(db,[P.revoke(),('SELECT 1',())],1)
        except RuntimeError:check('撤回扇出异常全库回滚',F.snapshot(db)==before)
        else:raise AssertionError('未注入异常')
        tx(db,[P.revoke()]);check('祖先撤回影响两种释放',risks(db),[('h',),('hc',)])
        check('两个释放均持久锁存',db.execute('SELECT release_id FROM cr_release_invalidation ORDER BY release_id').fetchall(),[('rc',),('rp',)])
        check('撤回直接与间接验证',db.execute('SELECT validation_id FROM cr_validation_revocation ORDER BY validation_id').fetchall(),[('own.rc',),('v.rp',)])
        check('独立关闭验证不被误撤',db.execute("SELECT count(*) FROM cr_valid_validation WHERE validation_id='close.cancel'").fetchone()[0],1)
        check('原结果终态未被改写',db.execute('SELECT disposition FROM cg_result ORDER BY result_id').fetchall(),[('succeeded',),('succeeded',)])
        tx(db,[P.revoke('result.2')]);check('多个撤回原因永久保留',db.execute('SELECT count(*) FROM cg_revocation').fetchone()[0],2)
        denied('失效后不能复用旧结果新释放',db,release('rc2',sources={'own.rc2':('result.2',)}))
        F.tx(db,release('rc2'));F.tx(db,release('rp2','h'));check('独立取证清风险',risks(db),[])
        check('清风险仍须恢复',db.execute('SELECT count(*) FROM cr_device_protection').fetchone()[0],2)
        tx(db,R.recovery(members=('rc','rp')));check('显式恢复消费完整旧失效',db.execute('SELECT count(*) FROM cr_device_protection').fetchone()[0],0)
        tx(db,[H.revoke('own.rc2')]);check('旧恢复不覆盖新失效',db.execute('SELECT release_id FROM cr_device_protection').fetchall(),[('rc2',)])
        db=fresh('released');tx(db,[P.revoke('result.2')])
        check('直接子结果撤回不误伤祖先独立释放',risks(db),[('hc',)])
        check('祖先来源验证仍有效',db.execute("SELECT count(*) FROM cr_valid_validation WHERE validation_id='v.rp'").fetchone()[0],1)
        db=fresh('closed');F.tx(db,bind(Z.closure('derived.close'),{'derived.close':('result.2',)}))
        F.tx(db,X.extra(release(),'cx_release_cancel',closure_validation_id='derived.close'))
        tx(db,[P.revoke()]);check('经关闭证明间接撤回释放',db.execute('SELECT release_id FROM cr_release_invalidation').fetchall(),[('rc',)])
        db=fresh('closed');s=release(sources={'own.rc':('result.2',)});denied('释放封存窗口祖先撤回',db,s[:-1]+[P.revoke()]+s[-1:])
        db=fresh('released');tx(db,V.public(C.revision(6,'observe',phase='dispatching',effect='possible',attempts=('a',),releases=('rc','rp')),6,cancel='cancel',cancel_revision=2))
        tx(db,V.public(C.initial('other'),1,'other'));tx(db,V.public(C.prepare('other','oa',n=2),2,'other'))
        tx(db,Q.ordinary(V.public(C.dispatch('other','oa','oh','op',pkt='other.packet',n=3,issued=4,attempts=('oa',)),3,'other')))
        tx(db,[P.revoke()]);check('晚撤回保留三个风险占用',risks(db),[('h',),('hc',),('oh',)])
        check('不丢新holder许可',db.execute("SELECT count(*) FROM ce_permit WHERE permit_id='op'").fetchone()[0],1)
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
        data=json.loads(read(HERE/'result-dependency-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='132表结果依赖及撤回扇出候选',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'result-dependency-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
