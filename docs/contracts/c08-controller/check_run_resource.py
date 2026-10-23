"""RUN证据依赖与资源通知235表内存实验，保留全部现有发送阻断。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_run_resource as G
import check_protection_delivery as P
import check_protection_outbox as N
import check_cancel_resource as X
import check_protected_hold as H
I,U,F,J,A,B,D,u=P.I,P.U,P.F,P.J,P.A,P.B,P.D,P.u
Q=P.P;R=X.R;HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(P.INPUTS+G.SOURCES+N.INPUTS+[HERE/n for n in
 ('RUN_RESOURCE.md','controller-run-resource.sql','check_run_resource.py')]))
def manifest(vid,sources=(),provider='trusted.fixture'):
    return [I('rr_manifest',validation_id=vid,source_count=len(sources),manifest_digest=D,manifest_body=B)]+[
      I('rr_source',validation_id=vid,kind=kind,source_id=sid,fence_id='f',source_body=B) for kind,sid in sources]+[
      I('rr_manifest_commit',validation_id=vid,manifest_digest=D,provider_ref=provider,receipt_body=B,audit_body=B)]
def bind(steps,sources=None):
    out=[]
    for table,v in steps:
        out.append((table,v))
        if table=='cr_validation':out+=manifest(v['validation_id'],(sources or {}).get(v['validation_id'],()),v['provider_ref'])
    return out
def tx(db,steps,sources=None,fault=None):U.tx(db,bind(steps,sources),fault)
def fixture(retired=False):
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    for steps in ([F.F.A.namespace()],F.F.P.register(),F.F.P.change()):tx(db,F.adapt(steps))
    tx(db,U.mutate(F.adapt([F.F.A.namespace()]),'ca_namespace',namespace_id='cancel.ns',issuer_id='issuer',issuer_epoch='epoch',principal_id='bob',request_epoch='cancel.requests',owner_evidence_id='cancel.owner'))
    for eid in ('exit.0','exit.1'):tx(db,U.mutate(F.adapt([F.F.exit_step(eid)]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
    tx(db,F.adapt(F.V.public(F.C.initial(),1)));tx(db,U.bootstrap(db,'bob'))
    steps=U.mutate(F.adapt(F.V.cancel(2,attempts=(),permits=(),cut=0)),'cv_cancel',mode='cooperative')
    tx(db,U.mutate(steps,'cv_cancel_key',namespace_id='cancel.ns'))
    ordinary=U.mutate(F.adapt(H.X.cut(members=[])),'cc_cut',issued_revision=u(0))
    tx(db,Q.capture(db,ordinary,'cancel','ordinary',(),0,15))
    for eid in ('exit.0','exit.1'):
        tx(db,F.adapt([H.X.attempt(eid=eid)]));tx(db,F.adapt([s for s in H.X.ack(eid=eid) if not s[0].startswith('INSERT INTO cc_coverage ')]))
    tx(db,Q.closure('ordinary',[],cid='ordinary.preparations',tick=16))
    tx(db,U.mutate(F.adapt(H.X.closure()),'cc_closure',prepare_closure_id='ordinary.preparations'))
    tx(db,Q.O.acquire(db))
    all_steps=U.mutate(F.adapt(H.X.cut('all',members=[],prepares=[])),'cc_cut',issued_revision=u(0))
    tx(db,Q.capture(db,all_steps,'cancel','all',(),0,26))
    tx(db,Q.closure('all',[],cid='all.preparations',tick=27))
    for eid in ('exit.0','exit.1'):
        tx(db,F.adapt([H.X.attempt('all',eid)]));tx(db,F.adapt([s for s in H.X.ack('all',eid) if not s[0].startswith(('INSERT INTO cc_coverage ','INSERT INTO cc_ack_prepare '))]))
    tx(db,U.mutate(F.adapt(H.X.closure('all')),'cc_closure',prepare_closure_id='all.preparations'))
    tx(db,F.adapt(H.X.extra(F.V.progress(3,2,'indeterminate','closed',dict(resource='held')),'cv_cancel_revision',closure_id='close.all')))
    tx(db,F.adapt(X.closure()))
    run_steps=U.mutate(Q.run_cut(db,pids=(),head=0),'pd_cut',selected_tick=u(28))
    tx(db,U.mutate(run_steps,'pd_cut_commit',committed_tick=u(28)))
    tx(db,Q.closure('f',[],cid='run.preparations',tick=29))
    for n,eid in enumerate(('exit.0','exit.1')):
        bid='run.barrier.'+str(n)
        if retired and n==1:
            tx(db,[Q.E.retire(eid)]);bid=None;kind='supervisor_retired'
        else:
            tx(db,F.adapt([A.attempt(bid,eid=eid)]));tx(db,F.adapt(A.ack(bid,eid,items=False,tick=30)));kind='worker_ack'
        tx(db,F.adapt([A.I('ce_result_binding',fence_id='f',exit_id=eid,barrier_id=bid,kind=kind,binding_body=B),F.F.result(eid,items=(),kind=kind)[-1]]))
    tx(db,P.application())
    return db
def release(rid='rc'):
    steps=U.mutate(F.adapt(R.release(rid=rid,hid='hc',revision=1,kind='module_settled',attempts=(),members=())),
      'cr_release',issued_cut_revision=u(0),cancel_validation_id='own.'+rid)
    steps[:0]=F.adapt([R.validation('own.'+rid,'release',rid,policy='cancel.release.policy')])
    steps.insert(-1,I('cx_release_cancel',release_id=rid,cancellation_id='cancel',closure_validation_id='close.cancel'))
    return steps
def revoke(bid='run.barrier.0'):return I('ra_barrier_revocation',barrier_id=bid,reason_body=B,audit_body=B)
def recovery(name='recovery',n=1,retired=()):
    steps=F.adapt(R.recovery(name,members=('rc',)))
    steps[-1:-1]=[I('ro_recovery_target',recovery_id=name,release_id='rc',exit_id=e,
      ack_id=None if e in retired else 'ack.rc.'+e+'.'+str(n),retirement_exit_id=e if e in retired else None) for e in ('exit.0','exit.1')]
    return steps
def acknowledge(db,n=1,exits=('exit.0','exit.1')):
    for e in exits:
        aid='rc.'+e+'.'+str(n);vid='v.ack.'+aid
        tx(db,F.adapt([N.attempt(e,n,rid='rc')]))
        tx(db,F.adapt([R.validation(vid,'close','close.'+aid,policy='resource-close/1')])+
          [I('ro_ack',ack_id='ack.'+aid,attempt_id=aid,validation_id=vid,ack_digest=D,ack_body=B,audit_body=B)])

def run():
    assert (HERE/'controller-run-resource.sql').read_bytes()==G.build()
    checks=[];connections=[]
    def check(n,a,e=True):assert a==e,(n,a,e);checks.append(dict(name=n,observed=a,expected=e))
    def fresh(**kw):db=fixture(**kw);connections.append(db);return db
    def denied(n,db,steps):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError:pass
        else:raise AssertionError(n+':未拒绝')
        check(n+'全库回滚',U.snapshot(db)==before)
    try:
        db=fresh();check('235表',len(U.snapshot(db)),235)
        sources={'v.rc':[('run_ack','run.barrier.0'),('run_application','receipt.f')]}
        tx(db,release(),sources)
        check('完整双政策释放',db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(),[])
        tx(db,[revoke()])
        check('原回执失效',db.execute('SELECT state FROM ra_current_status').fetchone()[0],'indeterminate')
        check('资源验证同步撤回',db.execute("SELECT count(*) FROM cr_validation_revocation WHERE validation_id='v.rc'").fetchone()[0],1)
        check('释放失效保留原记录',db.execute('SELECT release_id FROM cr_release_invalidation').fetchall(),[('rc',)])
        check('风险重新可见',db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(),[('hc',)])
        check('完整出口关闭通知',db.execute('SELECT exit_id FROM ro_pending ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        check('原取消许可集合保留为空',db.execute('SELECT count(*) FROM ci_cancel_transmission').fetchone()[0],0)
        # 原ACK即使已推翻完整application，另一未撤回出口ACK仍是独立的可审计直接来源。
        tx(db,release('rc2'));check('独立重新取证可清资源风险',db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(),[])
        denied('只清资源不能恢复',db,bind(recovery()))
        acknowledge(db)
        tx(db,recovery(),{'v.recovery':[('run_ack','run.barrier.1')]})
        check('完整关闭及取证后恢复',db.execute('SELECT release_id FROM cr_device_protection').fetchall(),[])
        tx(db,[revoke('run.barrier.1')])
        check('恢复来源撤回重开设备保护',db.execute('SELECT release_id FROM cr_device_protection').fetchall(),[('rc',)])
        check('已消费关闭ACK不能再次当当前关闭',db.execute('SELECT exit_id FROM ro_pending ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        check('独立释放不被关联撤回',db.execute("SELECT count(*) FROM cr_validation_revocation WHERE validation_id='v.rc2'").fetchone()[0],0)
        denied('旧关闭ACK不得复用恢复',db,bind(recovery('retry')))
        acknowledge(db,2);tx(db,recovery('retry',2))
        check('新的独立证据与关闭可再次恢复',db.execute('SELECT release_id FROM cr_device_protection').fetchall(),[])
        for source in ([('run_ack','run.barrier.0')],[('run_application','receipt.f')]):
            db=fresh();tx(db,release(),{'own.rc':source});tx(db,[revoke()])
            check(source[0][0]+'取消自身释放政策也传播',db.execute('SELECT release_id FROM cr_release_invalidation').fetchall(),[('rc',)])
        db=fresh();tx(db,release());tx(db,[revoke()])
        check('显式零依赖不误撤独立释放',db.execute('SELECT release_id FROM cr_release_invalidation').fetchall(),[])
        check('独立释放风险仍清',db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(),[])
        db=fresh(retired=True);tx(db,release(),{'v.rc':[('run_application','receipt.f')]})
        tx(db,[I('cu_revocation',kind='retirement',object_id='exit.1',reason_body=B,audit_body=B)])
        check('完整应用退役证明撤回影响资源',db.execute('SELECT release_id FROM cr_release_invalidation').fetchall(),[('rc',)])
        check('已撤回退役出口不能从关闭全集消失',db.execute('SELECT exit_id FROM ro_pending ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        db=fresh(retired=True);tx(db,release(),{'v.rc':[('run_ack','run.barrier.0')]});tx(db,[revoke()])
        check('有效退役仍登记完整历史目标',db.execute('SELECT exit_id FROM ro_target ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        check('有效退役无需网络关闭',db.execute('SELECT exit_id FROM ro_pending ORDER BY exit_id').fetchall(),[('exit.0',)])
        tx(db,release('rc2'));acknowledge(db,exits=('exit.0',));tx(db,recovery(retired=('exit.1',)))
        check('ACK与显式退役覆盖完整后恢复',db.execute('SELECT release_id FROM cr_device_protection').fetchall(),[])
        tx(db,[I('cu_revocation',kind='retirement',object_id='exit.1',reason_body=B,audit_body=B)])
        check('直接恢复退役证据撤回也重新保护',db.execute('SELECT release_id FROM cr_device_protection').fetchall(),[('rc',)])
        check('退役撤回重开旧出口与已消费ACK',db.execute('SELECT exit_id FROM ro_pending ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        # 完整来源写集缺写、逐步主动异常与后续资源提交的复核。
        validation=F.adapt([R.validation('probe','settlement','not.a.settlement')])
        proof=bind(validation,{'probe':[('run_ack','run.barrier.0')]})
        for i in range(len(proof)):
            db=fresh();denied('来源缺写'+str(i),db,proof[:i]+proof[i+1:])
            before=U.snapshot(db)
            try:U.tx(db,proof,fault=i)
            except RuntimeError as e:assert str(e)=='injected'
            else:raise AssertionError('故障未注入')
            check('来源逐写异常回滚'+str(i),U.snapshot(db)==before)
        for field,value in [('source_id','missing'),('source_body',b'other'),('fence_id','wrong')]:
            denied('来源错配'+field,fresh(),U.mutate(proof,'rr_source',**{field:value}))
        for field,value in [('provider_ref','wrong'),('receipt_body',b'other'),('manifest_digest','wrong')]:
            denied('封存错配'+field,fresh(),U.mutate(proof,'rr_manifest_commit',**{field:value}))
        denied('同数量错设备',fresh(),U.mutate(proof,'cr_validation',device_id='other'))
        db=fresh();tx(db,F.adapt(F.F.P.register('other',run='other.run')));tx(db,F.adapt(F.F.P.change('other')))
        command=U.mutate(F.adapt(F.V.public(F.C.initial('two'),1,'two')),'ce_command',prep_key='other',receipt_id='receipt.other')
        tx(db,command)
        denied('同设备另一run不得借证明',db,U.mutate(proof,'cr_validation',command_id='command.two'))
        denied('来源数量错误',fresh(),U.mutate(proof,'rr_manifest',source_count=2))
        db=fresh();tx(db,[revoke()]);denied('撤回先到不能再封存原件',db,proof)
        db=fresh();steps=proof[:-1]+[revoke()]+proof[-1:]
        denied('预写来源后撤回最后seal拒绝',db,steps)
        db=fresh();steps=bind(release(),sources);steps.insert(-1,revoke())
        denied('来源有效时预写不能跨撤回提交释放',db,steps)
        for table in ('cr_validation_revocation','cr_release_invalidation','ro_incident','ro_target'):
            db=fresh();tx(db,release(),sources)
            db.execute(f"CREATE TRIGGER inject_failure BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
            denied('撤回传播失败'+table,db,[revoke()])
            check('失败不留下半个状态通知'+table,db.execute('SELECT revision FROM ra_status_event').fetchall(),[(1,)])
        db=fresh();tx(db,release(),sources);tx(db,release('rc2'),{'v.rc2':[('run_ack','run.barrier.0')]});tx(db,[revoke()])
        check('同来源扇出全部释放',db.execute('SELECT release_id FROM cr_release_invalidation ORDER BY release_id').fetchall(),[('rc',),('rc2',)])
        check('双来源同验证只撤回一次',db.execute("SELECT count(*) FROM cr_validation_revocation WHERE validation_id='v.rc'").fetchone()[0],1)
        for table in G.TABLES:
            check(table+'非空样本',db.execute('SELECT count(*) FROM '+table).fetchone()[0]>0)
            col=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for statement in (f'UPDATE {table} SET {col}={col}','DELETE FROM '+table):
                before=U.snapshot(db)
                try:db.execute(statement)
                except sqlite3.IntegrityError:pass
                else:raise AssertionError('可变:'+table)
                check(table+statement.split()[0],U.snapshot(db)==before)
        check('外键完整',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        return checks
    finally:
        for db in connections:db.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'run-resource-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        d=json.loads(read(target));assert set(d['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert d['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=235,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
