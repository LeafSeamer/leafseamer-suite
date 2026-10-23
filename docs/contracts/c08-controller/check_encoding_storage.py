"""编码准备的共享内存SQLite实验；不运行网络、设备或磁盘数据库。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_encoding_storage as G
import check_scope_storage as S
O,U,F,H=S.O,S.U,S.F,S.H
I,u,B,D=S.I,S.u,S.B,S.D
HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(S.INPUTS+G.SOURCES+[HERE/n for n in ('ENCODING_STORAGE.md','ENCODING_AUTHORITY.md',
 'check_encoding_storage.py','controller-encoding.sql','encoding-authority.schema.json','encoding-authority-ipc.schema.json')]))

def fresh(kind='ordinary',slots=2,bytes_limit=8):
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    for steps in ([F.F.A.namespace()],F.F.P.register(),F.F.P.change()):U.tx(db,F.adapt(steps))
    U.tx(db,U.mutate(F.adapt([F.F.A.namespace()]),'ca_namespace',namespace_id='cancel.ns',issuer_id='issuer',issuer_epoch='epoch',
       principal_id='bob',request_epoch='cancel.requests',owner_evidence_id='cancel.owner'))
    for eid in ('exit.0','exit.1'):U.tx(db,U.mutate(F.adapt([F.F.exit_step(eid)]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
    U.tx(db,F.adapt(F.V.public(F.C.initial(),1)));U.tx(db,U.bootstrap(db,'bob'))
    if kind=='cancel':
        steps=U.mutate(F.adapt(F.V.cancel(2,attempts=(),permits=(),cut=0)),'cv_cancel',mode='cooperative')
        U.tx(db,U.mutate(steps,'cv_cancel_key',namespace_id='cancel.ns'))
        U.tx(db,U.mutate(F.adapt(H.X.cut(members=[])),'cc_cut',issued_revision=u(0)))
        for eid in ('exit.0','exit.1'):
            U.tx(db,F.adapt([H.X.attempt(eid=eid)]))
            U.tx(db,F.adapt([x for x in H.X.ack(eid=eid) if not x[0].startswith('INSERT INTO cc_coverage ')]))
        U.tx(db,F.adapt(H.X.closure()));U.tx(db,O.acquire(db))
    U.tx(db,[I('ep_limit',singleton=1,profile_id='fixture.profile',profile_revision=u(1),profile_digest=D,
      max_live_prepares=slots,max_live_bytes=bytes_limit,profile_body=B)])
    return db

def request(db,kind='ordinary',pid='prepare',seq=1,max_bytes=4,primitive=None,command='command.one'):
    primitive=primitive or ('primitive.cancel' if kind=='cancel' else 'primitive.1')
    key=U.one(db,'SELECT k.* FROM cv_cancel_key k JOIN cv_cancel c USING(key_id) WHERE c.command_id=?',(command,)) if kind=='cancel' else U.one(db,
      'SELECT k.* FROM ca_request_key k JOIN ca_command_initial c USING(key_id) WHERE c.command_id=?',(command,))
    ns=U.one(db,'SELECT * FROM ca_namespace WHERE namespace_id=?',(key['namespace_id'],))
    steps=[]
    if kind=='cancel':steps=U.mutate(F.adapt([H.X.prepare()]),'cc_prepare',prepare_id=pid,primitive_id=primitive,outbox_id='cancel.'+pid)
    return steps+[I('ep_request',prepare_id=pid,scope_id=1,kind=kind,command_id=command,
      proposed_attempt_id='attempt.'+pid if kind=='ordinary' else None,cancellation_id='cancel' if kind=='cancel' else None,
      cancel_prepare_id=pid if kind=='cancel' else None,namespace_id=ns['namespace_id'],request_digest=key['request_digest'],
      issuer_id=ns['issuer_id'],issuer_epoch=ns['issuer_epoch'],principal_id=ns['principal_id'],exit_id='exit.0',primitive_id=primitive,
      authorization_id='auth.'+pid,authorization_digest=D,authorization_body=B,request_message_id='encode.'+pid,request_seq=u(seq),
      request_frame_digest=D,request_frame=B,max_bytes=max_bytes,created_tick=u(10),expires_tick=u(40)),
      I('ep_request_commit',prepare_id=pid,committed_tick=u(11),validation_body=B,audit_body=B,outbox_id='encode.'+pid,outbox_body=B)]

def attempt(pid='prepare',tick=12):return [I('ep_send_attempt',prepare_id=pid,attempt_id='send.'+pid,attempted_tick=u(tick),request_frame_digest=D,attempt_body=B)]
def reply(pid='prepare',outcome='prepared',disposition=None,tick=13,seq=1):
    ok=outcome=='prepared';raw=b'\x01\x02'
    return [I('ep_reply',prepare_id=pid,exit_id='exit.0',response_message_id='response.'+pid,response_seq=u(seq),reply_to='encode.'+pid,
      authorization_id='auth.'+pid,authorization_digest=D,response_frame_digest=D,response_frame=B,outcome=outcome,
      packet_id='packet.'+pid if ok else None,packet_digest=D if ok else None,bytes_digest='sha256:'+hashlib.sha256(raw).hexdigest() if ok else None,
      packet_bytes=raw if ok else None,packet_body=B if ok else None,evidence_id='evidence.'+pid if ok else None,
      evidence_digest=D if ok else None,evidence_body=B if ok else None,received_tick=u(tick)),
      I('ep_receive_commit',prepare_id=pid,disposition=disposition or ('prepared' if ok else 'failed'),committed_tick=u(tick),validation_body=B,audit_body=B)]
def revoke(pid='prepare'):return I('ep_revocation',prepare_id=pid,reason_body=B,audit_body=B,outbox_id='revoke.'+pid,outbox_body=B)
def retire(eid='exit.0'):return I('ce_retirement',exit_id=eid,supervisor_evidence_body=B)
def release(pid='prepare',basis='never_attempted',eid=None):return I('ep_release',prepare_id=pid,basis=basis,retirement_exit_id=eid,proof_body=B,audit_body=B)
def packet(db,kind='ordinary',pid='prepare'):
    if kind=='cancel':return [I('cc_packet',packet_id='packet.'+pid,prepare_id=pid,packet_digest=D,packet_bytes=b'\x01\x02',packet_body=B,validation_body=B)]
    return F.adapt(F.V.public(F.C.prepare(aid='attempt.'+pid),2))+[I('ce_packet',packet_id='packet.'+pid,attempt_id='attempt.'+pid,
      exit_id='exit.0',primitive_id='primitive.1',packet_body=B)]

def run():
    assert (HERE/'controller-encoding.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,observed=copy.deepcopy(actual),expected=copy.deepcopy(expected)))
    def stage(kind='ordinary',level='requested',**kw):
        db=fresh(kind,**kw);connections.append(db)
        if level=='base':return db
        U.tx(db,request(db,kind))
        if level=='requested':return db
        U.tx(db,attempt())
        if level=='attempted':return db
        U.tx(db,reply());return db
    def denied(name,db,steps,error=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as e:
            if error:assert str(e)==error,(name,str(e),error)
            check(name,U.snapshot(db)==before)
        else:raise AssertionError('未拒绝:'+name)
    try:
        for kind in ('ordinary','cancel'):
            db=stage(kind,'prepared');check(kind+'共享202表',len(U.snapshot(db)),202)
            check(kind+'准备不签发',db.execute('SELECT count(*) FROM ci_issue').fetchone()[0],0)
            check(kind+'准备无普通attempt',db.execute('SELECT count(*) FROM ce_attempt').fetchone()[0],0)
            U.tx(db,packet(db,kind));check(kind+'旧packet入口已关联',db.execute('SELECT count(*) FROM '+('ce_packet' if kind=='ordinary' else 'cc_packet')).fetchone()[0],1)
            db=stage(kind,'attempted');denied(kind+'无响应不产生旧packet',db,packet(db,kind))
            for title,level,make in [('登记','base',lambda d:request(d,kind)),('响应','attempted',lambda d:reply())]:
                db=stage(kind,level);count=len(make(db))
                for index in range(count):
                    db=stage(kind,level);steps=make(db);denied(kind+title+'缺写'+str(index),db,steps[:index]+steps[index+1:])
                    before=U.snapshot(db)
                    try:U.tx(db,steps,fault=index)
                    except RuntimeError as e:assert str(e)=='injected'
                    else:raise AssertionError('故障未触发')
                    check(kind+title+'异常回滚'+str(index),U.snapshot(db)==before)
            db=stage(kind,'base');bad=U.mutate(request(db,kind),'ep_request',principal_id='forged')
            denied(kind+'原请求主体不可伪造',db,bad,'encoding_request_source')
            db=stage(kind,'base');bad=U.mutate(request(db,kind),'ep_request',request_digest='changed')
            denied(kind+'原受理内容错配',db,bad,'encoding_request_source')
            db=stage(kind);denied(kind+'重复编码尝试不能二次入流',db,attempt()+attempt())
            db=stage(kind,'attempted');denied(kind+'已提交尝试不能恢复重投',db,attempt())
            db=stage(kind);denied(kind+'尝试截止等号',db,attempt(tick=40),'encoding_attempt_not_current')
            db=stage(kind);U.tx(db,[revoke()]);denied(kind+'撤回后不开始',db,attempt(),'encoding_attempt_not_current')
            for field,value in [('reply_to','other'),('authorization_id','other'),('authorization_digest','other'),('exit_id','exit.1'),('packet_bytes',b'12345')]:
                db=stage(kind,'attempted');denied(kind+'响应错配:'+field,db,U.mutate(reply(),'ep_reply',**{field:value}),'encoding_reply_binding')
            db=stage(kind,'attempted');denied(kind+'响应采用截止等号',db,reply(tick=40),'encoding_not_adoptable')
            U.tx(db,reply(tick=40,disposition='historical'));check(kind+'迟到仅历史',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0],0)
            db=stage(kind,'attempted');U.tx(db,[revoke()]);denied(kind+'撤回与接收同轮不得采用',db,reply(),'encoding_not_adoptable')
            U.tx(db,reply(disposition='historical'));check(kind+'撤回仍可留历史',db.execute('SELECT count(*) FROM ep_reply').fetchone()[0],1)
            db=stage(kind,'attempted');steps=reply();steps.insert(-1,revoke())
            denied(kind+'接收最终seal前撤回',db,steps,'encoding_not_adoptable')
            db=stage(kind,'prepared');bad=U.mutate(packet(db,kind),'ce_packet' if kind=='ordinary' else 'cc_packet',packet_body=b'changed')
            denied(kind+'旧packet原件不可替换',db,bad)
            for result in ('failed','rejected'):
                db=stage(kind,'attempted');U.tx(db,reply(outcome=result));check(kind+result+'不产生可用字节',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0],0)
                denied(kind+result+'不转换成功',db,reply())
            db=stage(kind,'prepared');before=U.snapshot(db);stored=U.one(db,"SELECT * FROM ep_reply WHERE prepare_id='prepare'")
            check(kind+'重复查询返回原响应',stored['response_message_id'],'response.prepare');check(kind+'查询不改状态',U.snapshot(db)==before)
            denied(kind+'新消息不覆盖原结果',db,U.mutate(reply(seq=2),'ep_reply',response_message_id='replacement'))
            db=stage(kind,'attempted');denied(kind+'尝试后不能称从未调用',db,[revoke(),release()],'encoding_release_proof')
            U.tx(db,[retire('exit.1')]);denied(kind+'其他出口退役不释放',db,[revoke(),release(basis='supervisor_retired',eid='exit.1')],'encoding_release_proof')
            U.tx(db,[retire(),revoke(),release(basis='supervisor_retired',eid='exit.0')])
            check(kind+'退役回收活缓存预算',db.execute('SELECT count(*) FROM ep_live_reservation').fetchone()[0],0)
            U.tx(db,reply(disposition='historical'));check(kind+'退役后迟到不复活',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0],0)
            for table in G.TABLES:
                check(kind+'不可变表有真实行:'+table,db.execute('SELECT count(*) FROM '+table).fetchone()[0]>0)
                col=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
                for sql in ('UPDATE '+table+' SET '+col+'='+col,'DELETE FROM '+table):
                    before=U.snapshot(db)
                    try:db.execute(sql)
                    except sqlite3.IntegrityError as e:check(kind+'历史不可变:'+sql,str(e),'immutable_encoding')
                    else:raise AssertionError('不可变保护失效')
                    assert U.snapshot(db)==before
            db=stage(kind,'attempted')
            if kind=='cancel':
                closing=U.mutate(F.adapt(H.X.cut('all',members=[],prepares=['prepare'])),'cc_cut',issued_revision=u(0))
            else:
                closing=F.adapt(F.V.cancel(2,attempts=(),permits=(),cut=0))
            U.tx(db,closing);denied(kind+'关闭先到不采用',db,reply(),'encoding_not_adoptable')
            U.tx(db,reply(disposition='historical'));check(kind+'关闭迟到仅历史',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0],0)
        # 容量预留按两个种类共享；不等于磁盘物理字节回收。
        db=stage(slots=1);denied('满槽拒新准备',db,request(db,pid='two',seq=2),'encoding_capacity')
        U.tx(db,[revoke(),release()]);U.tx(db,request(db,pid='two',seq=2));check('未尝试撤回后可重新分配',db.execute('SELECT count(*) FROM ep_live_reservation').fetchone()[0],1)
        db=stage(bytes_limit=7);denied('字节预算差一拒绝',db,request(db,pid='two',seq=2),'encoding_capacity')
        db=stage(bytes_limit=8);U.tx(db,request(db,pid='two',seq=2));check('字节预算等号允许',db.execute('SELECT sum(max_bytes) FROM ep_live_reservation').fetchone()[0],8)
        db=stage();denied('请求seq冲突',db,request(db,pid='two',seq=1))
        db=stage('cancel');U.tx(db,F.adapt(F.V.public(F.C.initial('two'),1,key='two')))
        U.tx(db,request(db,pid='ordinary.two',seq=2,command='command.two'))
        check('普通取消共享同份容量',db.execute('SELECT sum(max_bytes),count(*) FROM ep_live_reservation').fetchone(),(8,2))
        denied('混合准备不得取得第二份额度',db,request(db,pid='third',seq=3,command='command.two'),'encoding_capacity')
        for level,expected in [('requested','never_attempted_do_not_replay'),('attempted','query_or_retire_unknown'),('prepared','query_recorded_result')]:
            db=stage(level=level);check('恢复分类:'+level,db.execute('SELECT recovery_action FROM ep_recovery').fetchone()[0],expected)
        db=stage('cancel','base');denied('旧取消准备不能跳过新登记',db,F.adapt([H.X.prepare()]))
        # SQL不计算BODY和JCS：该限制反证不得当作真实签发证明。
        db=stage();check('合成BODY可通过的限制',db.execute('SELECT authorization_body FROM ep_request').fetchone()[0]==B)
        check('旧四个最终签发阻断保留',db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0],4)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'encoding-storage-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=202,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
