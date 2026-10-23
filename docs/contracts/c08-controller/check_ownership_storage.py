"""不可变归属的内存SQLite实验；不连接业务库，不执行设备发送。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_ownership_storage as G
import check_open_storage as S
import check_protected_hold as H
U,F,I,u,B,D=S.U,S.F,S.I,S.u,S.B,S.H
HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(S.INPUTS+H.INPUTS+G.SOURCES+[HERE/n for n in
 ('check_ownership_storage.py','controller-ownership.sql','OWNERSHIP_STORAGE.md','hold-ownership.schema.json','scoped-gate.schema.json')]))

def fresh(holder='bob',origin='manual',cancel=True):
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    U.tx(db,F.adapt([F.F.A.namespace()]));U.tx(db,F.adapt(F.F.P.register()));U.tx(db,F.adapt(F.F.P.change()))
    ns=U.mutate(F.adapt([F.F.A.namespace()]),'ca_namespace',namespace_id='cancel.ns',issuer_id='issuer',issuer_epoch='epoch',
        principal_id=holder if origin=='manual' else 'seamer',request_epoch='cancel.requests',owner_evidence_id='cancel.owner')
    U.tx(db,ns)
    for e in ('exit.0','exit.1'):U.tx(db,U.mutate(F.adapt([F.F.exit_step(e)]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
    U.tx(db,F.adapt(F.V.public(F.C.initial(),1)))
    U.tx(db,U.bootstrap(db,holder if origin=='manual' else None))
    if not cancel:return db
    steps=U.mutate(F.adapt(F.V.cancel(2,attempts=(),permits=(),cut=0)),'cv_cancel',mode='cooperative')
    U.tx(db,U.mutate(steps,'cv_cancel_key',namespace_id='cancel.ns'))
    U.tx(db,U.mutate(F.adapt(H.X.cut(members=[])),'cc_cut',issued_revision=u(0)))
    for e in ('exit.0','exit.1'):
        U.tx(db,F.adapt([H.X.attempt(eid=e)]))
        U.tx(db,F.adapt([x for x in H.X.ack(eid=e) if not x[0].startswith('INSERT INTO cc_coverage ')]))
    U.tx(db,F.adapt(H.X.closure()))
    return db

def ownership(db,origin='manual',kind='cancel'):
    key=U.one(db,'SELECT * FROM '+('cv_cancel_key' if kind=='cancel' else 'ca_request_key'))
    ns=U.one(db,'SELECT * FROM ca_namespace WHERE namespace_id=?',(key['namespace_id'],))
    a=U.one(db,'SELECT * FROM go_authority')
    return [I('ow_source',source_id='source',scope_id=1,source_revision=u(1),source_digest=D,
        hold_id='hc' if kind=='cancel' else 'h',hold_digest=D,command_id='command.one',device_id='device',kind=kind,
        attempt_id=None if kind=='cancel' else 'a',cancellation_id='cancel' if kind=='cancel' else None,
        execution_id=H.P.E if kind=='cancel' else None,command_key_id=key['key_id'] if kind=='ordinary' else None,
        cancel_key_id=key['key_id'] if kind=='cancel' else None,namespace_id=ns['namespace_id'],request_digest=key['request_digest'],
        origin=origin,principal_kind='human' if origin=='manual' else 'service',issuer_id=ns['issuer_id'],issuer_epoch=ns['issuer_epoch'],principal_id=ns['principal_id'],
        authority_state_id=a['change_id'],control_epoch=a['control_epoch'],effective_version=a['effective_version'],
        clock_domain='domain',descriptor='descriptor',sampled_tick=u(10),acquired_tick=u(10),expires_tick=u(30),
        provider_ref='fixture.provider',receipt_body=B),
      I('ow_ownership',ownership_id='owner',revision=u(1),hold_id='hc' if kind=='cancel' else 'h',source_id='source',ownership_digest=D,ownership_body=B),
      I('ow_commit',ownership_id='owner',hold_id='hc' if kind=='cancel' else 'h',committed_tick=u(10),audit_body=B,outbox_id='ownership.outbox',outbox_body=B)]

def acquire(db,origin='manual'):
    source,owner,seal=ownership(db,origin)
    return [source]+F.adapt(H.acquire())+[owner,seal]

def snapshot(db,sid='snap',tick=20,authority=None,classification='active'):
    authority=authority or U.one(db,'SELECT * FROM go_authority')['change_id']
    steps=S.snapshot(db,sid,tick,authority)
    steps.insert(1,I('go_hold',snapshot_id=sid,hold_id='hc',authority_state_id='base',owner_ref='owner',owner_revision=u(1),owner_digest=D,classification=classification))
    return steps

def revoke():return I('ow_revocation',source_id='source',provider_ref='fixture.provider',reason_body=B,audit_body=B,outbox_id='revoke.outbox',outbox_body=B)

def takeover(db):
    steps=F.start(db,members=(),water=0)
    steps[-1:-1]=F.adapt(F.V.public(F.C.revision(3,'block',phase='finished',outcome='blocked',effect='not_sent',
        resource='unresolved',latched=1,terminal=3),3,cancel='cancel',cancel_revision=1))
    return steps

def run():
    assert (HERE/'controller-ownership.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,observed=copy.deepcopy(actual),expected=copy.deepcopy(expected)))
    def stage(held=False,**kw):
        db=fresh(**kw);connections.append(db)
        if held:U.tx(db,acquire(db,kw.get('origin','manual')))
        return db
    def denied(name,db,steps,error=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚',U.snapshot(db)==before)
    try:
        db=stage(True)
        check('182表仍共用原资源与控制权威',len(U.snapshot(db)),182)
        check('取消独立归属已提交',db.execute('SELECT ownership_id,principal_id,origin FROM ow_record').fetchall(),[('owner','bob','manual')])
        check('父命令保留不同服务主体',db.execute('SELECT principal_id FROM ca_namespace WHERE namespace_id=\'ns\'').fetchall(),[('person',)])
        check('父命令未发不伪造attempt',db.execute('SELECT count(*) FROM ce_attempt').fetchone()[0],0)
        U.tx(db,snapshot(db));check('当前真实归属可进入资源候选',db.execute('SELECT count(*) FROM go_valid_snapshot').fetchone()[0],1)
        check('四个最终签发阻断保持',db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0],4)
        db=stage(True,origin='automation');check('自动化Requester独立取服务来源',db.execute('SELECT principal_id,origin FROM ow_current_owner').fetchall(),[('seamer','automation')])
        # 缺少任何一条同库写入均不能提交；异常逐写注入，未删除或停用安全触发器。
        steps=acquire(stage())
        for n in range(len(steps)):
            db=stage();denied('占用事务缺写'+str(n),db,steps[:n]+steps[n+1:]);db.close();connections.remove(db)
            db=stage();before=U.snapshot(db)
            try:U.tx(db,steps,n)
            except RuntimeError:check('占用事务主动异常'+str(n),U.snapshot(db)==before)
            else:raise AssertionError('未注入异常')
            db.close();connections.remove(db)
        bad=[('hold_id','other'),('hold_digest','sha256:'+'b'*64),('command_id','missing'),('device_id','other'),
          ('cancellation_id','missing'),('execution_id','missing'),('namespace_id','ns'),('cancel_key_id','missing'),
          ('request_digest','sha256:'+'b'*64),('issuer_id','other'),('issuer_epoch','other'),('principal_id','alice'),
          ('authority_state_id','missing'),('control_epoch','other'),('effective_version',u(3)),
          ('clock_domain','other'),('descriptor','other'),('acquired_tick',u(11)),('expires_tick',u(10))]
        for field,value in bad:
            db=stage();denied('来源或归属错配:'+field,db,U.mutate(acquire(db),'ow_source',**{field:value}))
        for table,changes in [('ow_ownership',dict(hold_id='other')),('ow_ownership',dict(source_id='other')),
          ('ow_commit',dict(hold_id='other')),('ow_commit',dict(ownership_id='other')),
          ('ow_commit',dict(committed_tick=u(9))),('ow_commit',dict(committed_tick=u(30))),
          ('ow_source',dict(attempt_id='a')),('ow_source',dict(principal_kind='service'))]:
            db=stage();denied('封存关联:'+table+str(changes),db,U.mutate(acquire(db),table,**changes))
        db=stage();U.tx(db,U.mutate(acquire(db),'ow_commit',committed_tick=u(29)))
        check('来源期限前一刻可封存',db.execute('SELECT committed_tick FROM ow_commit').fetchall(),[(u(29),)])
        db=stage();steps=acquire(db);steps.insert(-1,revoke())
        denied('封存前撤回来源',db,steps,'ownership_source_or_authority')
        for value in ('01','-1','1\n',str(10**20),None):
            db=stage();denied('U20严格词法:'+repr(value),db,U.mutate(acquire(db),'ow_source',effective_version=value))
        for origin,kind in [('automation','service'),('manual','human')]:
            db=stage(origin='manual' if origin=='automation' else 'automation')
            denied('当前模式不能互换:'+origin,db,U.mutate(acquire(db,origin),'ow_source',principal_kind=kind))
        db=stage(True)
        for changes in (dict(owner_ref='self.reported'),dict(owner_revision=u(2)),dict(owner_digest='sha256:'+'b'*64),dict(authority_state_id='missing')):
            denied('快照不能自报owner:'+str(changes),db,U.mutate(snapshot(db),'go_hold',**changes))
        # 真实T3/T4写集改变控制权，父命令资源保留unresolved，旧Ownership不迁移。
        db=stage(True,holder='alice');original=db.execute('SELECT * FROM ow_record').fetchall()
        U.tx(db,U.offer(db));U.tx(db,takeover(db))
        check('接管pending立即撤当前主体资格',db.execute('SELECT count(*) FROM ow_current_owner').fetchone()[0],0)
        for e in ('exit.0','exit.1'):U.tx(db,U.mutate(F.ack(e,members=()),'cu_ack',issued_revision=u(0)))
        U.tx(db,F.effective(db,members=()))
        check('T4保持完整原归属历史',db.execute('SELECT * FROM ow_record').fetchall()==original)
        check('新holder不继承旧占用',db.execute('SELECT count(*) FROM ow_current_owner').fetchone()[0],0)
        denied('接管后把旧hold标成新authority',db,U.mutate(snapshot(db),'go_hold',authority_state_id='effective'),'ownership_snapshot_binding')
        U.tx(db,snapshot(db,classification='orphaned'))
        check('诚实旧归属快照仍不普通ready',db.execute('SELECT count(*) FROM go_valid_snapshot').fetchone()[0],0)
        check('接管保留实际风险',db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(),[('hc',)])
        db=stage(True);before=U.snapshot(db)
        try:U.tx(db,[revoke()],0)
        except RuntimeError:check('撤回与安全代次主动异常同回滚',U.snapshot(db)==before)
        old=int(db.execute('SELECT max(revision) FROM go_hazard').fetchone()[0]);U.tx(db,[revoke()])
        check('撤回推进同一安全代次',int(db.execute('SELECT max(revision) FROM go_hazard').fetchone()[0]),old+1)
        check('撤回保留归属历史',db.execute('SELECT count(*) FROM ow_record').fetchone()[0],1)
        check('撤回不授当前资格',db.execute('SELECT count(*) FROM ow_current_owner').fetchone()[0],0)
        check('撤回不释放实际占用',db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(),[('hc',)])
        denied('相同撤回不得新增代次',db,[revoke()])
        denied('不能伪造归属撤回代次',db,[I('go_hazard',device_id='device',revision=u(old+2),source_kind='ownership',source_id='missing',recovery_id=None)],'hazard_source')
        for table in G.TABLES:
            check('不可变验证确有行:'+table,db.execute('SELECT count(*) FROM '+table).fetchone()[0]>0)
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for action in ('UPDATE '+table+' SET '+column+'='+column,'DELETE FROM '+table,'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table):
                before=U.snapshot(db)
                try:db.execute(action)
                except sqlite3.IntegrityError as e:
                    expected='ownership_source_or_authority' if table=='ow_commit' and action.startswith('INSERT') else 'immutable_ownership'
                    check('原件不可变:'+action,str(e),expected)
                else:raise AssertionError('原件可变')
                check('原件不可变后全库保持',U.snapshot(db)==before)
        db=stage(True)
        for n,(stored,wire) in enumerate([('active','active'),('unknown','unknown'),('failed_unresolved','unresolved'),('orphaned','stale'),('proof_revoked','stale')]):
            U.tx(db,snapshot(db,'class.'+str(n),20+n,classification=stored))
            check('风险词表显式映射:'+stored,db.execute('SELECT classification FROM ow_risk_projection WHERE snapshot_id=?',('class.'+str(n),)).fetchone()[0],wire)
        # 普通来源投影有实际RequestKey/attempt；只读未提交写集后回滚，不冒充完整普通派发。
        for field,value,expected in [(None,None,1),('namespace_id','cancel.ns',0),('issuer_epoch','other',0),('request_digest','sha256:'+'b'*64,0),
          ('origin','manual',0),('command_key_id','missing',0),('attempt_id','missing',0)]:
            db=stage(origin='automation',cancel=False);before=U.snapshot(db);db.execute('BEGIN IMMEDIATE')
            try:
                U.execute(db,I('cm_attempt',attempt_id='a',command_id='command.one',ordinal=1,prepared_revision=u(2)))
                U.execute(db,I('ce_attempt',attempt_id='a',command_id='command.one',authorization_body=B,attempt_body=B))
                source=ownership(db,'automation','ordinary')[0]
                if field:source[1][field]=value
                if field=='origin':source[1]['principal_kind']='human'
                # 两个实际外键错配会在插入点拒绝；其他错配由来源视图拒绝。
                try:U.execute(db,source)
                except sqlite3.IntegrityError:
                    if field not in ('command_key_id','attempt_id'):raise
                    check('普通来源真实外键:'+str(field),0,expected)
                else:check('普通来源实际请求关联:'+str(field),db.execute('SELECT count(*) FROM ow_request_source').fetchone()[0],expected)
            finally:db.execute('ROLLBACK')
            check('普通来源投影不提交半边占用',U.snapshot(db)==before)
        db=stage(True);U.tx(db,F.adapt(H.P.prepare('primitive.cancel')))
        denied('归属成功不绕最终签发阻断',db,F.adapt(H.P.dispatch(n=1)),'control_gate_not_ready')
        check('BODY占位通过仅为来源真实性限制',len(db.execute('SELECT * FROM ow_record').fetchall()),1)
        for db in connections:
            check('外键完整性',db.execute('PRAGMA foreign_key_check').fetchall(),[])
            check('数据库完整性',db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
    finally:
        for db in connections:db.close()
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    target=HERE/'ownership-storage-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=182,sqlite_version=sqlite3.sqlite_version,
          scope='占用来源封存与当前资源归属的内存持久化约束',runtime_tests_executed=0,device_tests_executed=0,
          concurrency_tests_executed=0,disk_crash_tests_executed=0,checks=checks,
          inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
