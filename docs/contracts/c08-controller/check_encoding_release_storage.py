"""完整207表的缓存释放事务实验，仅使用内存SQLite。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_encoding_release_storage as G
import check_encoding_storage as E
I,U,F,H,O,u,B,D=E.I,E.U,E.F,E.H,E.O,E.u,E.B,E.D
HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(E.INPUTS+G.SOURCES+[HERE/n for n in ('ENCODING_RELEASE_STORAGE.md','ENCODING_RELEASE.md',
 'check_encoding_release_storage.py','controller-encoding-release.sql','encoding-release.schema.json','encoding-release-ipc.schema.json')]))

def fresh(kind='ordinary',slots=2,bytes_limit=8,metadata_slots=4):
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
      max_live_prepares=slots,max_live_bytes=bytes_limit,max_metadata_prepares=metadata_slots,profile_body=B)])
    return db

def request(db,kind='ordinary',pid='prepare',**kw):
    return U.mutate(E.request(db,kind,pid=pid,**kw),'ep_request',reservation_id='reservation.'+pid,reservation_revision=u(1),reservation_digest=D)
def revoke(pid='prepare',tick=45):
    return U.mutate([E.revoke(pid)],'ep_revocation',revocation_id='revocation.'+pid,revocation_revision=u(1),revocation_digest=D,revoked_tick=u(tick))[0]
def release_request(pid='prepare',seq=2):
    return [revoke(pid),I('er_request',release_id='release.'+pid,release_revision=u(1),release_digest=D,prepare_id=pid,exit_id='exit.0',
      authorization_id='auth.'+pid,authorization_digest=D,encode_message_id='encode.'+pid,encode_frame_digest=D,
      revocation_id='revocation.'+pid,revocation_revision=u(1),revocation_digest=D,selected_tick=u(50),
      message_id='release.request.'+pid,outbound_seq=u(seq),frame_digest=D,frame_body=B,body=B),
      I('er_request_commit',release_id='release.'+pid,committed_tick=u(51),validation_body=B,audit_body=B,outbox_id='release.outbox.'+pid,outbox_body=B)]
def acknowledgement(pid='prepare',seq=2,historical=False):
    steps=[I('er_ack',ack_id='ack.'+pid,release_id='release.'+pid,prepare_id=pid,exit_id='exit.0',release_revision=u(1),release_digest=D,
      message_id='release.ack.'+pid,inbound_seq=u(seq),reply_to='release.request.'+pid,release_frame_digest=D,
      disposed_tick=u(52),received_tick=u(53),state='released',encoder_quiescent=1,consumers_quiescent=1,cache_empty=1,
      frame_digest=D,frame_body=B,validation_body=B)]
    if not historical:
        steps += [I('er_adoption',adoption_id='adoption.'+pid,adoption_revision=u(1),adoption_digest=D,prepare_id=pid,
          ack_id='ack.'+pid,release_id='release.'+pid,reservation_id='reservation.'+pid,reservation_revision=u(1),reservation_digest=D,
          reserved_bytes=4,received_tick=u(53),committed_tick=u(54),body=B,audit_body=B),
          I('ep_release',prepare_id=pid,basis='worker_released',retirement_exit_id=None,worker_adoption_id='adoption.'+pid,proof_body=B,audit_body=B)]
    return steps+[I('er_ack_commit',ack_id='ack.'+pid,disposition='historical' if historical else 'released',
      adoption_id=None if historical else 'adoption.'+pid,committed_tick=u(54),audit_body=B)]

def run():
    assert (HERE/'controller-encoding-release.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(n,a,e=True):
        assert a==e,(n,a,e);checks.append(dict(name=n,observed=copy.deepcopy(a),expected=copy.deepcopy(e)))
    def stage(kind='ordinary',level='prepared',**kw):
        db=fresh(kind,**kw);connections.append(db);U.tx(db,request(db,kind))
        if level=='requested':return db
        U.tx(db,E.attempt())
        if level=='attempted':return db
        U.tx(db,E.reply())
        if level=='prepared':return db
        U.tx(db,release_request())
        if level=='releasing':return db
        U.tx(db,[E.retire(),E.release(basis='supervisor_retired',eid='exit.0')]);return db
    def denied(n,db,steps,error=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as e:
            if error:assert str(e)==error,(n,str(e),error)
            check(n,U.snapshot(db)==before)
        else:raise AssertionError('未拒绝:'+n)
    try:
        for kind in ('ordinary','cancel'):
            db=stage(kind,'releasing');check(kind+'完整207表',len(U.snapshot(db)),207)
            check(kind+'墓碑立即隐藏准备',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0],0)
            check(kind+'等待ACK保留额度',db.execute('SELECT sum(max_bytes) FROM ep_live_reservation').fetchone()[0],4)
            before={k:v for k,v in U.snapshot(db).items() if not k.startswith(('ep_','er_'))}
            U.tx(db,acknowledgement());check(kind+'活额度归还',db.execute('SELECT count(*) FROM ep_live_reservation').fetchone()[0],0)
            check(kind+'命令资源与设备预算不变',{k:v for k,v in U.snapshot(db).items() if not k.startswith(('ep_','er_'))}==before)
            check(kind+'原字节历史不删除',db.execute('SELECT packet_bytes FROM ep_reply').fetchone()[0]==b'\x01\x02')
            check(kind+'恢复只查原ACK',db.execute('SELECT recovery_action FROM er_recovery').fetchone()[0],'query_recorded_ack')
            for title,level,make in [('请求','prepared',release_request),('采用','releasing',acknowledgement),('迟到历史','retired',lambda:acknowledgement(historical=True))]:
                for index in range(len(make())):
                    db=stage(kind,level);steps=make();denied(kind+title+'缺写'+str(index),db,steps[:index]+steps[index+1:])
                    before=U.snapshot(db)
                    try:U.tx(db,steps,fault=index)
                    except RuntimeError as e:assert str(e)=='injected'
                    else:raise AssertionError('故障未触发')
                    check(kind+title+'异常全库回滚'+str(index),U.snapshot(db)==before)
            for field,value in [('exit_id','exit.1'),('authorization_id','other'),('authorization_digest','other'),
              ('encode_message_id','other'),('encode_frame_digest','other'),('revocation_id','other'),('revocation_digest','other'),('selected_tick',u(44))]:
                db=stage(kind);denied(kind+'释放原件错配:'+field,db,U.mutate(release_request(),'er_request',**{field:value}),'encoding_release_request_source')
            db=stage(kind);denied(kind+'原帧与outbox不符',db,U.mutate(release_request(),'er_request_commit',outbox_body=b'other'),'encoding_release_request_seal')
            db=stage(kind);U.tx(db,[revoke()]);U.tx(db,release_request()[1:]);U.tx(db,acknowledgement())
            check(kind+'复用既有撤回原件',db.execute('SELECT count(*) FROM ep_revocation').fetchone()[0],1)
            db=stage(kind);denied(kind+'撤回早于原提交',db,[revoke(tick=10)],'encoding_revocation_time')
            db=stage(kind,'requested');denied(kind+'未尝试不能请求worker释放',db,release_request(),'encoding_release_request_source')
            U.tx(db,[revoke(),E.release()]);check(kind+'保留未尝试退款分支',db.execute('SELECT count(*) FROM ep_live_reservation').fetchone()[0],0)
            db=stage(kind,'attempted');U.tx(db,release_request());U.tx(db,acknowledgement())
            check(kind+'编码响应未知仍可释放',db.execute('SELECT count(*) FROM ep_release').fetchone()[0],1)
            U.tx(db,E.reply(disposition='historical'));check(kind+'释放后晚编码响应不复活',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0],0)
            for field,value in [('exit_id','exit.1'),('prepare_id','other'),('release_digest','other'),('reply_to','other'),
              ('release_frame_digest','other'),('disposed_tick',u(50)),('received_tick',u(51)),('encoder_quiescent',0),('consumers_quiescent',0),('cache_empty',0)]:
                db=stage(kind,'releasing');denied(kind+'ACK反例:'+field,db,U.mutate(acknowledgement(),'er_ack',**{field:value}))
            for field,value in [('reservation_id','other'),('reservation_revision',u(2)),('reservation_digest','other'),('reserved_bytes',3),
              ('received_tick',u(52)),('committed_tick',u(52)),('release_id','other')]:
                db=stage(kind,'releasing');denied(kind+'采用反例:'+field,db,U.mutate(acknowledgement(),'er_adoption',**{field:value}),'encoding_release_adoption_source')
            db=stage(kind,'releasing');denied(kind+'不能无采用退款',db,[I('ep_release',prepare_id='prepare',basis='worker_released',
              retirement_exit_id=None,worker_adoption_id='missing',proof_body=B,audit_body=B)],'encoding_release_refund_source')
            db=stage(kind,'releasing');denied(kind+'不能历史ACK跳过退款',db,acknowledgement(historical=True),'encoding_release_ack_seal')
            db=stage(kind,'releasing');denied(kind+'不能借其他出口退役',db,[E.retire('exit.1'),E.release(basis='supervisor_retired',eid='exit.1')],'encoding_release_proof')
            db=stage(kind,'retired');denied(kind+'退役后不再采用退款',db,acknowledgement(),'encoding_release_adoption_source')
            U.tx(db,acknowledgement(historical=True));check(kind+'退役后迟到ACK留历史',db.execute('SELECT disposition FROM er_ack_commit').fetchone()[0],'historical')
            check(kind+'退役单次退款',db.execute('SELECT count(*) FROM ep_release').fetchone()[0],1)
            db=stage(kind,'releasing');U.tx(db,acknowledgement());denied(kind+'ACK后退役不能再退款',db,[E.retire(),E.release(basis='supervisor_retired',eid='exit.0')])
            U.tx(db,[E.retire()]);check(kind+'退役事实独立保存',db.execute('SELECT count(*) FROM ce_retirement').fetchone()[0],1)
            for table in G.TABLES:
                check(kind+'不可变表含行:'+table,db.execute('SELECT count(*) FROM '+table).fetchone()[0]>0)
                col=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
                for sql in ('UPDATE '+table+' SET '+col+'='+col,'DELETE FROM '+table):
                    before=U.snapshot(db)
                    try:db.execute(sql)
                    except sqlite3.IntegrityError as e:check(kind+'历史不可变:'+sql,str(e),'immutable_encoding_release')
                    else:raise AssertionError('历史可改')
                    assert U.snapshot(db)==before
            db=stage(kind);denied(kind+'释放与编码出站seq冲突',db,release_request(seq=1),'encoding_release_outbound_collision')
            db=stage(kind,'releasing');denied(kind+'ACK与编码入站seq冲突',db,acknowledgement(seq=1),'encoding_release_inbound_collision')
            db=stage(kind);denied(kind+'释放出站消息ID冲突',db,U.mutate(release_request(),'er_request',message_id='encode.prepare'),'encoding_release_outbound_collision')
            db=stage(kind,'releasing');denied(kind+'ACK入站消息ID冲突',db,U.mutate(acknowledgement(),'er_ack',message_id='response.prepare'),'encoding_release_inbound_collision')
            db=stage(kind,'attempted');U.tx(db,release_request());U.tx(db,acknowledgement())
            denied(kind+'晚编码不能占原ACK序号',db,E.reply(disposition='historical',seq=2),'encoding_release_inbound_collision')
            db=stage(kind,'prepared');U.tx(db,E.packet(db,kind));U.tx(db,release_request())
            check(kind+'旧packet撤回映射保留',db.execute('SELECT packet_id FROM er_packet_revoked').fetchall(),[('packet.prepare',)])
            # 历史packet可保存不等于允许新传输；四最终准入阻断始终保留。
            check(kind+'旧packet仍存在',db.execute('SELECT count(*) FROM '+('ce_packet' if kind=='ordinary' else 'cc_packet')).fetchone()[0],1)
        db=stage(slots=1,bytes_limit=4,metadata_slots=2)
        denied('释放前无第二份额度',db,request(db,pid='next',seq=3),'encoding_capacity')
        U.tx(db,release_request());U.tx(db,acknowledgement());U.tx(db,request(db,pid='next',seq=3))
        check('正常会话继续准备',db.execute('SELECT prepare_id FROM ep_live_reservation').fetchall(),[('next',)])
        denied('重复旧ACK不退新额度',db,acknowledgement())
        check('新准备额度仍占用',db.execute('SELECT sum(max_bytes) FROM ep_live_reservation').fetchone()[0],4)
        U.tx(db,[revoke('next'),E.release('next')]);denied('活额度归还不清元数据',db,request(db,pid='third',seq=4),'encoding_metadata_capacity')
        denied('prepare身份不复用',db,request(db))
        db=stage(level='releasing',slots=1,bytes_limit=4)
        combined=acknowledgement()+request(db,pid='next',seq=3)
        before=U.snapshot(db)
        try:U.tx(db,combined,fault=len(combined)-1)
        except RuntimeError as e:assert str(e)=='injected'
        else:raise AssertionError('末尾故障未触发')
        check('释放并再预留末尾失败全部回滚',U.snapshot(db)==before)
        denied('不完整ACK不可借额度提交新准备',db,acknowledgement()[:-1]+request(db,pid='next',seq=3))
        U.tx(db,combined);check('完整退款再预留同事务',db.execute('SELECT prepare_id FROM ep_live_reservation').fetchall(),[('next',)])
        db=stage('ordinary','releasing');U.tx(db,acknowledgement())
        denied('后来编码不能占释放消息序号',db,request(db,pid='next',seq=2),'encoding_release_outbound_collision')
        # 模拟提交已发生但响应丢失：不再次提交写集，查询同一原件；不是实际COMMIT I/O故障。
        db=stage('ordinary','releasing');U.tx(db,acknowledgement());before=U.snapshot(db)
        check('丢提交响应后查询原采用',db.execute('SELECT adoption_id FROM er_adoption').fetchone()[0],'adoption.prepare')
        check('查原不改变余额或历史',U.snapshot(db)==before)
        check('四最终准入阻断保留',db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0],4)
        check('合成BODY不证明真实清空',db.execute('SELECT validation_body FROM er_ack').fetchone()[0]==B)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'encoding-release-storage-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=207,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
