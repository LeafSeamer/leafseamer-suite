"""准备完成237表内存候选检查；不连接业务服务或真实设备。"""
import argparse,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_preparation_completion as G
import check_run_resource as R
I,U,F,J,A,B,D,u=R.I,R.U,R.F,R.J,R.A,R.B,R.D,R.u
Q=R.Q;HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(R.INPUTS+G.SOURCES+[HERE/n for n in
 ('PREPARATION_COMPLETION.md','controller-preparation-completion.sql','check_preparation_completion.py')]))

def tx(db,steps):R.tx(db,steps)

def fixture(prepared=True,retired=False,apply=True,old=False,hold=False):
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON')
    db.executescript((R.G.build() if old else G.build()).decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    for steps in ([F.F.A.namespace()],F.F.P.register(),F.F.P.change()):tx(db,F.adapt(steps))
    tx(db,U.mutate(F.adapt([F.F.A.namespace()]),'ca_namespace',namespace_id='cancel.ns',issuer_id='issuer',issuer_epoch='epoch',principal_id='bob',request_epoch='cancel.requests',owner_evidence_id='cancel.owner'))
    for n in (0,1):
        eid='exit.'+str(n);sid='session.'+str(n)
        tx(db,U.mutate(F.adapt([F.F.exit_step(eid)]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
        e=U.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,))
        tx(db,[I('ij_session',session_id=sid,scope_id=1,controller_boot_id=e['controller_boot_id'],worker_boot_id=e['worker_boot_id'],ipc_session_id=e['ipc_session_id'],clock_domain_id='domain',descriptor_digest='descriptor',protocol_version='ipc/0.13.0-journal-draft.1',profile_body=B,binding_body=B,max_frames=128,reserved_frames=16,max_bytes=32768,reserved_bytes=1024),I('ij_exit',exit_id=eid,session_id=sid)])
        tx(db,J.handshake(sid))
    tx(db,F.adapt(F.V.public(F.C.initial(),1)));tx(db,U.bootstrap(db,'bob'))
    tx(db,[I('ep_limit',singleton=1,profile_id='fixture',profile_revision=u(1),profile_digest=D,max_live_prepares=8,max_live_bytes=32,max_metadata_prepares=16,profile_body=B)])
    if hold:
        assert not prepared
        steps=U.mutate(F.adapt(F.V.cancel(2,attempts=(),permits=(),cut=0)),'cv_cancel',mode='cooperative')
        tx(db,U.mutate(steps,'cv_cancel_key',namespace_id='cancel.ns'))
        ordinary=U.mutate(F.adapt(R.H.X.cut(members=[])),'cc_cut',issued_revision=u(0))
        tx(db,Q.capture(db,ordinary,'cancel','ordinary',(),0,15))
        for eid in ('exit.0','exit.1'):
            tx(db,F.adapt([R.H.X.attempt(eid=eid)]))
            tx(db,F.adapt([s for s in R.H.X.ack(eid=eid) if not s[0].startswith('INSERT INTO cc_coverage ')]))
        tx(db,Q.closure('ordinary',[],cid='ordinary.preparations',tick=16))
        tx(db,U.mutate(F.adapt(R.H.X.closure()),'cc_closure',prepare_closure_id='ordinary.preparations'))
        tx(db,Q.O.acquire(db))
    if prepared:
        tx(db,Q.registration(db));tx(db,J.encoding());tx(db,J.send_encoding())
        tx(db,[J.written('encode.prepare',12)]);tx(db,J.reply())
    steps=F.adapt(F.F.fence(source='close',items=(),queued=('one',),revision=0))
    steps=[('run_deny_event' if t=='cp_deny_event' else t,v) for t,v in steps]
    tx(db,Q.capture(db,steps,'run','f',('prepare',) if prepared else (),int(prepared),20))
    if prepared:
        tx(db,Q.deny(tick=21));tx(db,[J.attempted('deny.request.prepare',21),J.written('deny.request.prepare',21)])
        steps=U.mutate(Q.ack(),'ij_frame',observed_tick=u(23))
        steps=U.mutate(steps,'pd_deny_ack',effective_tick=u(22),received_tick=u(23))
        tx(db,U.mutate(steps,'ij_commit',committed_tick=u(23)))
    tx(db,Q.closure('f',[('prepare','deny_ack')] if prepared else [],cid='run.preparations',tick=24))
    for n,eid in enumerate(('exit.0','exit.1')):
        bid='run.barrier.'+str(n)
        if retired and n==1:tx(db,[Q.E.retire(eid)]);bid=None;kind='supervisor_retired'
        else:
            tx(db,F.adapt([A.attempt(bid,eid=eid)]));tx(db,F.adapt(A.ack(bid,eid,items=False,tick=25)));kind='worker_ack'
        tx(db,F.adapt([A.I('ce_result_binding',fence_id='f',exit_id=eid,barrier_id=bid,kind=kind,binding_body=B),F.F.result(eid,items=(),kind=kind)[-1]]))
    if apply:tx(db,R.P.application())
    return db

def complete(bound=True):
    steps=F.adapt(F.F.P.complete(previous='3',receipt='receipt.p'))
    if bound:steps.insert(2,I('pc_binding',completion_id='evidence.p',fence_id='f',receipt_id='receipt.f',receipt_body=B,binding_body=B,audit_body=B))
    return steps

def revoke(kind):
    return {'barrier':R.revoke(),
      'prepare':I('pd_ack_revocation',ack_id='deny.ack.prepare',reason_body=B,audit_body=B,outbox_body=B),
      'retirement':I('cu_revocation',kind='retirement',object_id='exit.1',reason_body=B,audit_body=B)}[kind]

def current(db):return db.execute('SELECT state,revision,receipt_id,protection_revision,protection_state FROM pc_current').fetchone()

def other_application(db,kind):
    """同RUN但另一真实来源；不能以不存在ID替代关联反例。"""
    name='other.f'
    if kind=='http':
        steps=F.adapt(F.F.fence(name=name,key='other.protection',items=(),queued=(),revision=0,raise_deny=False))
    else:
        steps=F.adapt(F.F.P.close(previous='3',receipt='receipt.p',noop=True,suffix='two',raise_deny=False))
        steps=[s for s in steps if s[0]!='cp_protection_target']
        index=next(i for i,(t,v) in enumerate(steps) if t=='cp_protection')+1
        steps[index:index]=[I('cp_protection_target',close_id='close.p.two',target_id=e,target_body=B) for e in ('exit.0','exit.1')]
        steps[-1:-1]=[I('ce_fence',fence_id=name,protection_id=None,close_id='close.p.two',issued_cut_revision=u(0),cut_body=B)]+[
          I('ce_target',fence_id=name,exit_id=e,ledger_digest=D,target_body=B) for e in ('exit.0','exit.1')]+[
          I('ce_cut_commit',fence_id=name,audit_body=B,outbox_event_id='cut.'+name,outbox_body=B)]
    tx(db,Q.capture(db,steps,'run',name,('prepare',),1,30))
    tx(db,Q.closure(name,[('prepare','deny_ack')],cid='other.preparations',tick=31))
    for n,e in enumerate(('exit.0','exit.1')):
        bid='other.barrier.'+str(n)
        tx(db,U.mutate(F.adapt([A.attempt(bid,eid=e)]),'ce_barrier_attempt',fence_id=name))
        tx(db,F.adapt(A.ack(bid,e,items=False,tick=32)))
        tx(db,[I('ce_result_binding',fence_id=name,exit_id=e,barrier_id=bid,kind='worker_ack',binding_body=B)]+
          F.adapt([F.F.result(e,items=(),name=name)[-1]]))
    tx(db,U.mutate(F.adapt([F.F.application(name)]),'ce_application',prepare_closure_id='other.preparations'))

def run():
    assert (HERE/'controller-preparation-completion.sql').read_bytes()==G.build()
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
        db=fresh(old=True,apply=False);tx(db,complete(False))
        check('旧235表无应用仍可closed的缺口复现',db.execute('SELECT state FROM cp_current').fetchone(),('closed',))
        db=fresh();check('237表',len(U.snapshot(db)),237)
        check('关闭中投影',current(db),('closing',u(3),'receipt.p',None,'pending'))
        tx(db,complete());check('真实close来源完成',current(db),('closed',u(4),'receipt.p',1,'applied'))
        check('非HTTP保护无需伪造HTTP记录',db.execute('SELECT count(*) FROM run_protection_request').fetchone()[0],0)
        check('关闭准备不退款缓存',db.execute('SELECT count(*) FROM ep_release').fetchone()[0],0)
        check('固定准备集合含实际编码项',db.execute('SELECT prepare_id FROM pd_member').fetchall(),[('prepare',)])
        denied('相同complete不能追加修订',db,complete())
        denied('closed不能复活applied',db,F.adapt(F.F.P.change()))
        for kind in ('barrier','prepare','retirement'):
            db=fresh(retired=kind=='retirement');tx(db,complete());tx(db,[revoke(kind)])
            check(kind+'撤回保留历史并失效',current(db),('closed',u(4),'receipt.p',2,'indeterminate'))
            check(kind+'有效完成为空',db.execute('SELECT count(*) FROM pc_valid_completion').fetchone()[0],0)
            check(kind+'新状态事件保留原因引用',db.execute('SELECT revision,state FROM pc_status_event ORDER BY revision').fetchall(),[(1,'applied'),(2,'indeterminate')])
            check(kind+'拒绝下界保留',db.execute('SELECT generation FROM run_deny_current').fetchone()[0],u(1))
            denied(kind+'禁止恢复旧成功事件',db,[I('pc_status_event',completion_id='evidence.p',revision=1,state='applied',fence_id='f',run_status_revision=1)])
        steps=complete()
        for i in range(len(steps)):
            db=fresh();denied('完成缺写'+str(i),db,steps[:i]+steps[i+1:])
            before=U.snapshot(db)
            try:U.tx(db,steps,fault=i)
            except RuntimeError:pass
            else:raise AssertionError('未注入故障')
            check('完成逐写异常'+str(i),U.snapshot(db)==before)
        denied('无实际应用不能完成',fresh(apply=False),complete())
        denied('无绑定不能完成',fresh(),complete(False))
        for field,value in [('completion_id','other'),('fence_id','other'),('receipt_id','other'),('receipt_body',b'other')]:
            denied('绑定错配'+field,fresh(),U.mutate(complete(),'pc_binding',**{field:value}))
        for source in ('http','close'):
            db=fresh();other_application(db,source)
            check(source+'另一个应用实际有效',db.execute("SELECT count(*) FROM pd_valid_application WHERE fence_id='other.f'").fetchone()[0],1)
            denied(source+'同RUN有效回执不得替换原close',db,U.mutate(complete(),'pc_binding',fence_id='other.f',receipt_id='receipt.other.f'))
            tx(db,complete());tx(db,[I('ra_barrier_revocation',barrier_id='other.barrier.0',reason_body=B,audit_body=B)])
            check(source+'其他应用撤回不误伤本完成',current(db)[-2:],(1,'applied'))
            check(source+'未产生额外完成事件',db.execute('SELECT count(*) FROM pc_status_event').fetchone()[0],1)
        for kind in ('barrier','prepare','retirement'):
            db=fresh(retired=kind=='retirement');tx(db,[revoke(kind)])
            denied(kind+'撤回先到',db,complete())
            db=fresh(retired=kind=='retirement');steps=complete();steps.insert(-1,revoke(kind))
            denied(kind+'绑定后最终提交前撤回',db,steps)
            db=fresh(retired=kind=='retirement');tx(db,complete()+[revoke(kind)])
            check(kind+'完成后同事务撤回留下两事件',current(db)[-2:],(2,'indeterminate'))
        # 状态生成失败必须连同原完成/撤回全部回滚，不能落下一半事实。
        for phase in ('initial','invalidated'):
            db=fresh()
            if phase=='invalidated':tx(db,complete())
            revision=1 if phase=='initial' else 2
            db.execute(f"CREATE TRIGGER inject_failure BEFORE INSERT ON pc_status_event WHEN NEW.revision={revision} BEGIN SELECT RAISE(ABORT,'injected'); END")
            denied(phase+'状态写入失败',db,complete() if phase=='initial' else [revoke('barrier')])
        db=fresh(prepared=False,hold=True)
        check('关闭前保留取消独立资源hold',db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(),[('hc',)])
        tx(db,complete());check('closed仍显示资源风险',db.execute('SELECT hold_id FROM pc_run_risk').fetchall(),[('hc',)])
        tx(db,[revoke('barrier')]);check('证明撤回不删除资源风险',db.execute('SELECT hold_id FROM pc_run_risk').fetchall(),[('hc',)])
        check('没有暗中释放或恢复',db.execute('SELECT (SELECT count(*) FROM cr_release),(SELECT count(*) FROM cr_recovery)').fetchone(),(0,0))
        gates=('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')
        check('四最终发送阻断均保留',db.execute('SELECT count(*) FROM sqlite_schema WHERE type=? AND name IN (?,?,?,?)',('trigger',)+gates).fetchone()[0],4)
        for table in G.TABLES:
            for operation in ('UPDATE','DELETE'):
                before=U.snapshot(db)
                sql=f'UPDATE {table} SET completion_id=completion_id' if operation=='UPDATE' else f'DELETE FROM {table}'
                try:db.execute(sql)
                except sqlite3.IntegrityError:pass
                else:raise AssertionError('不可变守卫失效')
                check(table+operation+'不可变',U.snapshot(db)==before)
        check('外键完整',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'preparation-completion-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        d=json.loads(read(target));assert set(d['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert d['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=237,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
