"""限定取消范围的内存SQLite写集验证；不是产品服务、并发或设备测试。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_scope_storage as G
import check_gate_renewal as R
import check_ownership_storage as O
U,F,I,u,B,D=R.U,R.F,R.I,R.u,R.B,R.D
S=R.S;H=O.H;HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(R.INPUTS+O.INPUTS+G.SOURCES+[HERE/n for n in ('SCOPE_STORAGE.md','check_scope_storage.py','controller-scope.sql')]))

def fresh(parent=False):
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    for steps in ([F.F.A.namespace()],F.F.P.register(),F.F.P.change()):U.tx(db,F.adapt(steps))
    ns=U.mutate(F.adapt([F.F.A.namespace()]),'ca_namespace',namespace_id='cancel.ns',issuer_id='issuer',issuer_epoch='epoch',principal_id='bob',request_epoch='cancel.requests',owner_evidence_id='cancel.owner')
    U.tx(db,ns)
    for e in ('exit.0','exit.1'):U.tx(db,U.mutate(F.adapt([F.F.exit_step(e)]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
    U.tx(db,F.adapt(F.V.public(F.C.initial(),1)))
    if parent:
        U.tx(db,F.adapt(F.V.public(F.C.prepare(),2)))
        # 合成历史前态：普通写集先于控制bootstrap；同事务随后配对真实Owner。
        # 不停用任何守卫，但此路径不证明产品最终普通准入已实现。
        db.execute('BEGIN IMMEDIATE')
        try:
            for step in F.adapt(F.Q.ordinary(F.V.public(F.C.dispatch(),3))):U.execute(db,step)
            for step in U.bootstrap(db,None):U.execute(db,step)
            for step in O.ownership(db,origin='automation',kind='ordinary'):U.execute(db,step)
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK');raise
        U.tx(db,F.adapt(F.V.public(F.C.revision(4,'timeout',phase='finished',outcome='unknown',effect='possible',resource='unresolved',latched=1,terminal=4,attempts=('a',)),4)))
        U.tx(db,F.start(db,kind='acquire',members=('permit.1',),water=1))
        U.tx(db,U.mutate(F.ack(members=('permit.1',)),'cu_ack',issued_revision=u(1)))
        U.tx(db,U.mutate(F.ack('exit.1',members=()),'cu_ack',issued_revision=u(1)))
        U.tx(db,F.effective(db,members=('permit.1',)))
    else:U.tx(db,U.bootstrap(db,'bob'))
    steps=F.adapt(F.V.cancel(5 if parent else 2,attempts=('a',) if parent else (),permits=('permit.1',) if parent else (),cut=int(parent),state_args=dict(F.V.UNKNOWN,terminal=4) if parent else None))
    steps=U.mutate(steps,'cv_cancel',mode='cooperative');steps=U.mutate(steps,'cv_cancel_key',namespace_id='cancel.ns');U.tx(db,steps)
    U.tx(db,U.mutate(F.adapt(H.X.cut(members=[('permit.1','exit.0',0)] if parent else [])),'cc_cut',issued_revision=u(int(parent))))
    for e in ('exit.0','exit.1'):
        U.tx(db,F.adapt([H.X.attempt(eid=e)]));U.tx(db,F.adapt([x for x in H.X.ack(eid=e) if parent or not x[0].startswith('INSERT INTO cc_coverage ')]))
    U.tx(db,F.adapt(H.X.closure()))
    steps=O.acquire(db)
    steps=U.mutate(steps,'ow_source',source_id='cancel.source',sampled_tick=u(30),acquired_tick=u(30),expires_tick=u(90))
    steps=U.mutate(steps,'ow_ownership',ownership_id='cancel.owner',source_id='cancel.source')
    steps=U.mutate(steps,'ow_commit',ownership_id='cancel.owner',committed_tick=u(30),outbox_id='cancel.owner.outbox')
    U.tx(db,steps)
    steps=S.protect(db,gid=None)
    steps.insert(-1,I('go_close',close_id='close.exit.1',device_id='device',exit_id='exit.1',revision=u(1),protection_change_id='protect',gate_id=None,reason_ref='fixture',body=B,outbox_body=B,audit_body=B))
    U.tx(db,steps);U.tx(db,S.close_ack())
    U.tx(db,R.request(db,previous=None));U.tx(db,R.ack());U.tx(db,R.commit(gid='gate.1',previous=None,rev=1))
    return db

def policy(db,classes=('active','unknown','unresolved')):
    return [I('gs_policy',policy_id='policy',execution_id=H.P.E,policy_ref_body=B,expires_tick=u(85),provider_ref='fixture.policy',receipt_body=B),
      *[I('gs_parent_class',policy_id='policy',classification=k) for k in classes],I('gs_policy_commit',policy_id='policy',audit_body=B)]

def assessment(db,aid='assessment',sid='snap',tick=46,parent_class='unknown',**fields):
    authority=U.one(db,'SELECT * FROM go_authority')['change_id'];steps=S.snapshot(db,sid,tick,authority)
    for owner in db.execute('SELECT ownership_id,hold_id,authority_state_id,kind FROM ow_record ORDER BY hold_id'):
        steps.insert(-1,I('go_hold',snapshot_id=sid,hold_id=owner[1],authority_state_id=owner[2],owner_ref=owner[0],owner_revision=u(1),owner_digest=D,classification='active' if owner[3]=='cancel' else parent_class))
    values=dict(assessment_id=aid,revision=u(1),assessment_digest=D,snapshot_id=sid,policy_id='policy',ownership_id='cancel.owner',
      resource_safety_id='resource.safety',resource_safety_revision=u(1),resource_safety_digest=D,
      gate_safety_id='gate.safety',gate_safety_revision=u(1),gate_safety_digest=D,provider_ref='fixture.assessment',receipt_body=B,body=B)
    values.update(fields)
    return steps+[I('gs_assessment',**values),I('gs_assessment_commit',assessment_id=aid,audit_body=B)]

def plan(db):
    steps=S.plan(gid='gate.1',cid='protect',selected=47)
    steps=U.mutate(steps,'go_plan',basis_kind='scope',scope_assessment_id='assessment',activation_id=None)
    steps.insert(-1,I('gs_access',access_id='access',revision=u(1),access_digest=D,plan_id='plan',initial_assessment_id='assessment',body=B,audit_body=B))
    return steps

def evidence():return U.mutate(S.evidence(tick=49,wire=2),'go_evidence',scope_access_id='access',scope_access_revision=u(1),scope_access_digest=D)

def commit(db,tick=50):
    steps=U.change(db,'scope','scope_commit',now=tick);steps[0][1]['state_id']='scope'
    steps+=[U.state(U.current(db),'scope',gate_state='protected',record_digest='sha256:'+'c'*64)]
    gate=R.gate('gate.2','gate.1',2,2,phase='scoped',renewal='renew');gate[1]['scope_commit_id']='scope'
    steps+=[gate,I('gs_scope_commit',commit_id='scope',access_id='access',evidence_id='evidence',change_id='scope',after_gate_id='gate.2',committed_tick=u(tick),commit_digest=D,body=B)]
    return U.finish(steps)

def revoke(kind='assessment',key='assessment'):return I('gs_revocation',kind=kind,object_id=key,reason_body=B,audit_body=B,outbox_body=B)

def takeover(db):
    steps=F.start(db,kind='acquire',members=(),water=0)
    steps=U.mutate(steps,'ct_change',now_tick=u(52))
    steps=U.mutate(steps,'ct_operation',requester_id='charlie',target_id='charlie')
    steps=U.mutate(steps,'ct_request',actor_id='charlie')
    steps[-1:-1]=F.adapt(F.V.public(F.C.revision(3,'block',phase='finished',outcome='blocked',effect='not_sent',resource='unresolved',latched=1,terminal=3),3,cancel='cancel',cancel_revision=1))
    return steps

def ordinary():
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    U.tx(db,U.mutate(F.adapt([F.F.exit_step()]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
    U.tx(db,U.bootstrap(db));U.tx(db,U.offer(db));U.tx(db,F.start(db,members=(),exits=('exit.0',),water=0))
    U.tx(db,U.mutate(F.ack(members=()),'cu_ack',issued_revision=u(0)));U.tx(db,F.effective(db,members=(),exits=('exit.0',)))
    U.tx(db,[R.gate()]);U.tx(db,S.protect(db,gid='gate.1'));U.tx(db,S.close_ack())
    U.tx(db,R.request(db));U.tx(db,R.ack());U.tx(db,R.commit())
    U.tx(db,S.recovery(db));U.tx(db,S.plan('plan.2','snap.2','gate.2','protect','recover',46));U.tx(db,S.dispatch('plan.2','dispatch.2',47,2))
    return db

def run():
    assert (HERE/'controller-scope.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,observed=copy.deepcopy(actual),expected=copy.deepcopy(expected)))
    def stage(level='acked',parent=False):
        db=fresh(parent);connections.append(db)
        if level=='base':return db
        U.tx(db,policy(db))
        if level=='policy':return db
        U.tx(db,assessment(db))
        if level=='assessed':return db
        U.tx(db,plan(db))
        if level=='planned':return db
        U.tx(db,S.dispatch(tick=48))
        if level=='dispatched':return db
        U.tx(db,evidence())
        if level=='acked':return db
        U.tx(db,commit(db));return db
    def denied(name,db,steps,error=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as exc:
            if error:assert str(exc)==error,(name,str(exc),error)
            check(name,U.snapshot(db)==before)
        else:raise AssertionError('未拒绝:'+name)
    try:
        for parent in (False,True):
            db=stage('committed',parent)
            check('共享194表:'+str(parent),len(U.snapshot(db)),194)
            check('限定范围可用:'+str(parent),db.execute('SELECT commit_id FROM gs_scope_candidate').fetchall(),[('scope',)])
            check('保持全局protected:'+str(parent),U.current(db)['gate_state'],'protected')
            check('不制造普通ready:'+str(parent),db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
            check('单个物理当前闸:'+str(parent),db.execute("SELECT phase FROM go_current_gate WHERE exit_id='exit.0'").fetchall(),[('scoped',)])
            if parent:
                check('父unknown保留',db.execute('SELECT outcome FROM cm_latest').fetchall(),[('unknown',)])
                check('父Owner未迁移',db.execute("SELECT principal_id,authority_state_id FROM ow_record WHERE kind='ordinary'").fetchall(),[('person','base')])
                check('普通快照仍拒父unknown',db.execute('SELECT count(*) FROM go_valid_snapshot').fetchone()[0],0)
            else:check('父未发不伪造普通attempt',db.execute('SELECT count(*) FROM ce_attempt').fetchone()[0],0)
        for name,level,make in [('政策','base',policy),('评估','policy',assessment),('开放计划','assessed',plan),('采用','acked',commit)]:
            for index in range(len(make(stage(level)))):
                db=stage(level);steps=make(db)
                # 政策允许空父集合，成员缺失本身不是不完整清单的证据。
                if steps[index][0]!='gs_parent_class':denied(name+'缺写'+str(index),db,steps[:index]+steps[index+1:])
                before=U.snapshot(db)
                try:U.tx(db,steps,fault=index)
                except RuntimeError as exc:assert str(exc)=='injected'
                else:raise AssertionError('未触发主动异常')
                check(name+'主动异常'+str(index),U.snapshot(db)==before)
        db=stage('policy',True);denied('父unknown不得重标active',db,assessment(db,parent_class='active'),'scope_assessment_invalid')
        db=stage('base',True);U.tx(db,policy(db,('active',)));denied('政策未允许unknown',db,assessment(db),'scope_assessment_invalid')
        db=stage('policy');denied('缺少自身hold风险',db,[x for x in assessment(db) if x[0]!='go_hold'],'open_hold_set')
        for field,value in [('ownership_id','missing'),('policy_id','missing'),('resource_safety_revision','1'),('gate_safety_digest','bad')]:
            db=stage('policy');denied('评估错配:'+field,db,assessment(db,**{field:value}))
        for field,value in [('scope_access_id',None),('scope_access_revision',u(2)),('scope_access_digest','bad')]:
            db=stage('dispatched');denied('原ACK错配:'+field,db,U.mutate(evidence(),'go_evidence',**{field:value}),'scope_ack_binding')
        for tick,ok in [(49,True),(79,True),(80,False)]:
            db=stage()
            if ok:U.tx(db,commit(db,tick));check('采用有效期:'+str(tick),True)
            else:denied('到期等号拒绝',db,commit(db,tick),'scope_commit_binding')
        db=stage('planned');denied('范围开放后不得补换Access',db,[I('gs_access',access_id='replacement',revision=u(1),access_digest=D,plan_id='plan',initial_assessment_id='assessment',body=B,audit_body=B)],'scope_access_sealed')
        db=stage('policy');denied('政策成员封存',db,[I('gs_parent_class',policy_id='policy',classification='active')],'scope_policy_sealed')
        for kind,key in [('policy','policy'),('assessment','assessment'),('access','access')]:
            db=stage();U.tx(db,[revoke(kind,key)]);denied('采用前撤回:'+kind,db,commit(db),'scope_commit_binding')
            db=stage();steps=commit(db);steps.insert(-1,revoke(kind,key));denied('最后seal重核撤回:'+kind,db,steps,'scope_commit_binding')
            db=stage('committed');U.tx(db,[revoke(kind,key)]);check('采用后撤回:'+kind,db.execute('SELECT count(*) FROM gs_scope_candidate').fetchone()[0],0)
            check('撤回保留原件:'+kind,db.execute('SELECT count(*) FROM gs_scope_commit').fetchone()[0],1)
        db=stage();U.tx(db,assessment(db,'assessment.2','snap.2',49));denied('旧OPEN初始评估已过期换代',db,commit(db),'scope_commit_binding')
        db=stage('committed');U.tx(db,assessment(db,'assessment.2','snap.2',51))
        check('当前Guard可换新评估不重开',db.execute('SELECT current_assessment_id FROM gs_scope_candidate').fetchall(),[('assessment.2',)])
        for field,value in [('resource_safety_id','other'),('resource_safety_revision',u(2)),('resource_safety_digest','sha256:'+'b'*64),('gate_safety_id','other'),('gate_safety_revision',u(2)),('gate_safety_digest','sha256:'+'b'*64)]:
            db=stage('committed');U.tx(db,assessment(db,'assessment.2','snap.2',51,**{field:value}))
            check('两安全Ref分别失效:'+field,db.execute('SELECT count(*) FROM gs_scope_candidate').fetchone()[0],0)
        db=stage('committed');U.tx(db,[I('gf_revocation',ack_id='renew.ack',reason_body=B,audit_body=B)])
        check('新屏障撤回撤范围',db.execute('SELECT count(*) FROM gs_scope_candidate').fetchone()[0],0)
        db=stage('committed');U.tx(db,[I('go_revocation',kind='open_ack',object_id='evidence',reason_body=B,audit_body=B)])
        check('开放ACK撤回撤范围',db.execute('SELECT count(*) FROM gs_scope_candidate').fetchone()[0],0)
        for level in ('acked','committed'):
            for name,make in [('自身归属撤回',lambda db:[I('ow_revocation',source_id='cancel.source',provider_ref='fixture',reason_body=B,audit_body=B,outbox_id='owner.revoke',outbox_body=B)]),
              ('ordinary证明撤回',lambda db:F.adapt([H.X.revoke('close.ordinary')])),
              ('all关闭',lambda db:U.mutate(F.adapt(H.X.cut('all',members=[],prepares=[])),'cc_cut',issued_revision=u(0))),
              ('接管pending',takeover)]:
                db=stage(level);U.tx(db,make(db))
                check(level+name+'撤销当前候选',db.execute('SELECT count(*) FROM gs_scope_candidate').fetchone()[0],0)
                if level=='acked':denied(name+'禁止采用',db,commit(db,53),'scope_commit_binding')
        db=stage('committed');steps=S.protect(db,'protect.2','close.2',2,'gate.2')
        steps.insert(-1,I('go_close',close_id='close.2.exit.1',device_id='device',exit_id='exit.1',revision=u(2),protection_change_id='protect.2',gate_id=None,reason_ref='fixture',body=B,outbox_body=B,audit_body=B))
        U.tx(db,steps);check('新关闭撤销当前范围',db.execute('SELECT count(*) FROM gs_scope_candidate').fetchone()[0],0)
        db=stage('assessed');steps=plan(db);steps=U.mutate(steps,'go_plan',selected_tick=u(45));denied('选择不得早于初始采样',db,steps)
        db=stage('assessed');steps=plan(db);steps=U.mutate(steps,'go_plan',expires_tick=u(86));denied('Access不得超过政策截止',db,steps)
        db=stage('policy');U.tx(db,U.mutate(assessment(db),'go_snapshot',expires_tick=u(49)));U.tx(db,plan(db))
        denied('初始评估到期禁止派发OPEN',db,S.dispatch(tick=49),'scope_dispatch_expired')
        U.tx(db,S.dispatch(tick=48));U.tx(db,evidence());denied('ACK不续初始评估',db,commit(db),'scope_commit_binding')
        db=stage('committed');denied('ScopeCommit不能直接升级ready',db,S.ready(db,'promote','plan','evidence','gate.3','gate.2',3,2,51))
        db=stage('committed');denied('伪造撤回原件',db,[revoke('access','missing')],'scope_revocation_source')
        db=stage('committed');U.tx(db,[revoke()])
        for table in G.TABLES:
            row=db.execute('SELECT * FROM '+table).fetchone();assert row is not None
            cols=[x[1] for x in db.execute('PRAGMA table_info('+table+')')]
            for action in ('update','delete','replace'):
                before=U.snapshot(db);db.execute('BEGIN IMMEDIATE')
                try:
                    if action=='update':db.execute(f'UPDATE {table} SET {cols[0]}={cols[0]}')
                    elif action=='delete':db.execute('DELETE FROM '+table)
                    else:db.execute('INSERT OR REPLACE INTO '+table+' VALUES('+','.join('?' for _ in row)+')',row)
                    db.execute('COMMIT')
                except sqlite3.IntegrityError:db.execute('ROLLBACK');check(table+':'+action,U.snapshot(db)==before)
                else:raise AssertionError('不可变性失效:'+table)
        check('四个最终签发阻断保持',db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0],4)
        db=ordinary();connections.append(db)
        denied('普通ACK不得夹取消Access',db,U.mutate(S.evidence('dispatch.2','evidence.2',48,2,2),'go_evidence',scope_access_id='access',scope_access_revision=u(1),scope_access_digest=D),'scope_ack_binding')
        U.tx(db,S.evidence('dispatch.2','evidence.2',48,2,2))
        steps=S.ready(db,'ready.2','plan.2','evidence.2','gate.3','gate.2',3,2,49)
        U.tx(db,U.mutate(steps,'go_gate',barrier_id='renew',control_barrier_id=None,renewal_id='renew'))
        check('194表普通恢复T5仍可用',db.execute('SELECT ready_id FROM go_ready_candidate').fetchall(),[('ready.2',)])
        check('普通ready不产生ScopeCommit',db.execute('SELECT count(*) FROM gs_scope_commit').fetchone()[0],0)
        for db in connections:
            check('外键完整性',db.execute('PRAGMA foreign_key_check').fetchall(),[])
            check('数据库完整性',db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
    finally:
        for db in connections:db.close()
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    target=HERE/'scope-storage-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=194,sqlite_version=sqlite3.sqlite_version,
          scope='限定取消评估开放及ScopeCommit的共享内存SQLite约束',runtime_tests_executed=0,device_tests_executed=0,
          concurrency_tests_executed=0,disk_crash_tests_executed=0,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
