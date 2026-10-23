"""完整共享日志布局的内存SQLite实验；不执行产品IPC或真实设备。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_ipc_journal_storage as G
import check_encoding_release_storage as R
import check_gate_renewal as Q
I,U,F,H,O,u,B,D=R.I,R.U,R.F,R.H,R.O,R.u,R.B,R.D
E=R.E;S=Q.S;HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(R.INPUTS+G.SOURCES+[HERE/n for n in
 ('IPC_JOURNAL_STORAGE.md','IPC_JOURNAL.md','check_ipc_journal_storage.py','controller-ipc-journal.sql','ipc-journal-messages.json')]))

def frame(fid,direction,kind,seq,domain,oid,mid=None,tick=1,eid='exit.0',reply=None,reply_to=None,session='session.0',device='device'):
    return I('ij_frame',frame_id=fid,session_id=session,exit_id=eid,device_id=device if eid else None,
      direction=direction,message_type=kind,message_id=mid or fid,seq=u(seq),reply_frame_id=reply,reply_to=reply_to,
      frame_digest=D,wire_digest=D,frame_body=B,body_body=B,wire_body=B,wire_length=len(B),observed_tick=u(tick),
      domain_kind=domain,domain_id=oid,validation_body=B)

def seal(fid,tick=1,disposition='applied'):
    return I('ij_commit',frame_id=fid,disposition=disposition,committed_tick=u(tick),audit_body=B,effect_body=B)

def attempted(fid,tick=2,pid=None):
    return I('ij_write_attempt',frame_id=fid,attempt_id='send.'+pid if pid else 'attempt.'+fid,attempted_tick=u(tick),encoding_prepare_id=pid,current_validation_body=B,audit_body=B)

def written(fid,tick=2):return I('ij_write_result',frame_id=fid,state='written',completed_tick=u(tick),written_bytes=len(B),end_id=None,result_body=B)

def end(fid=None,tick=60,session='session.0',reason='shutdown'):
    return I('ij_end',end_id='end.'+session,session_id=session,reason=reason,cause_frame_id=fid,observed_tick=u(tick),evidence_body=B,audit_body=B)

def handshake(session='session.0'):
    hello='hello.'+session;ack='hello_ack.'+session
    return [frame(hello,'w2c','HELLO',1,'handshake',hello,eid=None,session=session),
      I('ij_handshake',handshake_id=hello,frame_id=hello,kind='HELLO',negotiation_body=B),seal(hello),
      frame(ack,'c2w','HELLO_ACK',1,'handshake',ack,eid=None,session=session,reply=hello,reply_to=hello),
      I('ij_handshake',handshake_id=ack,frame_id=ack,kind='HELLO_ACK',negotiation_body=B),seal(ack),attempted(ack),written(ack)]

def fresh(kind='ordinary',frames=64,reserved=8,bytes_limit=32768,reserved_bytes=512,handshaken=True):
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    for steps in ([F.F.A.namespace()],F.F.P.register(),F.F.P.change()):U.tx(db,F.adapt(steps))
    U.tx(db,U.mutate(F.adapt([F.F.A.namespace()]),'ca_namespace',namespace_id='cancel.ns',issuer_id='issuer',issuer_epoch='epoch',
      principal_id='bob',request_epoch='cancel.requests',owner_evidence_id='cancel.owner'))
    for n in (0,1):
        eid='exit.'+str(n);sid='session.'+str(n)
        U.tx(db,U.mutate(F.adapt([F.F.exit_step(eid)]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
        e=U.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,))
        U.tx(db,[I('ij_session',session_id=sid,scope_id=1,controller_boot_id=e['controller_boot_id'],worker_boot_id=e['worker_boot_id'],
          ipc_session_id=e['ipc_session_id'],clock_domain_id='domain',descriptor_digest='descriptor',protocol_version='ipc/0.13.0-journal-draft.1',
          profile_body=B,binding_body=B,max_frames=frames,reserved_frames=reserved,max_bytes=bytes_limit,reserved_bytes=reserved_bytes),
          I('ij_exit',exit_id=eid,session_id=sid)])
        if handshaken:U.tx(db,handshake(sid))
    if kind!='gate':U.tx(db,F.adapt(F.V.public(F.C.initial(),1)))
    U.tx(db,U.bootstrap(db,'alice' if kind=='gate' else 'bob'))
    if kind in ('cancel','scope'):
        steps=U.mutate(F.adapt(F.V.cancel(2,attempts=(),permits=(),cut=0)),'cv_cancel',mode='cooperative')
        U.tx(db,U.mutate(steps,'cv_cancel_key',namespace_id='cancel.ns'))
        U.tx(db,U.mutate(F.adapt(H.X.cut(members=[])),'cc_cut',issued_revision=u(0)))
        for eid in ('exit.0','exit.1'):
            U.tx(db,F.adapt([H.X.attempt(eid=eid)]))
            U.tx(db,F.adapt([x for x in H.X.ack(eid=eid) if not x[0].startswith('INSERT INTO cc_coverage ')]))
        U.tx(db,F.adapt(H.X.closure()))
        owners=O.acquire(db)
        if kind=='scope':
            owners=U.mutate(owners,'ow_source',source_id='cancel.source',sampled_tick=u(30),acquired_tick=u(30),expires_tick=u(90))
            owners=U.mutate(owners,'ow_ownership',ownership_id='cancel.owner',source_id='cancel.source')
            owners=U.mutate(owners,'ow_commit',ownership_id='cancel.owner',committed_tick=u(30),outbox_id='cancel.owner.outbox')
        U.tx(db,owners)
    if kind=='gate':
        U.tx(db,U.offer(db));U.tx(db,F.start(db,members=(),exits=('exit.0','exit.1'),water=0))
        for eid in ('exit.0','exit.1'):U.tx(db,U.mutate(F.ack(eid,members=()),'cu_ack',issued_revision=u(0)))
        U.tx(db,F.effective(db,members=(),exits=('exit.0','exit.1')));U.tx(db,[Q.gate()])
    U.tx(db,[I('ep_limit',singleton=1,profile_id='fixture.profile',profile_revision=u(1),profile_digest=D,
      max_live_prepares=4,max_live_bytes=16,max_metadata_prepares=8,profile_body=B)])
    return db

def request(db,kind='ordinary',pid='prepare',**kw):
    steps=R.request(db,kind,pid=pid,**kw)
    row=next(v for t,v in steps if t=='ep_request')
    for k in ('request_seq','request_frame_digest','request_frame'):del row[k]
    return steps

def encoding(kind='ordinary',pid='prepare',seq=2):
    fid='encode.'+pid
    return [frame(fid,'c2w','ENCODE_CANCEL_PACKET' if kind=='cancel' else 'ENCODE_PACKET',seq,'encoding_request',pid,tick=11),
      I('ij_encoding_frame',prepare_id=pid,journal_frame_id=fid,request_seq=u(seq),request_frame_digest=D,request_frame=B),seal(fid,11)]

def send_encoding(pid='prepare'):
    fid='encode.'+pid
    return U.mutate(E.attempt(pid),'ep_send_attempt',journal_frame_id=fid)+[attempted(fid,12,pid)]

def reply(kind='ordinary',pid='prepare',seq=2,disposition='prepared',outcome='prepared'):
    fid='response.'+pid
    typ=('PREPARE_CANCEL_PACKET' if kind=='cancel' else 'PREPARE_PACKET') if outcome=='prepared' else ('CANCEL_ENCODING_FAILED' if kind=='cancel' else 'PACKET_ENCODING_FAILED')
    return [frame(fid,'w2c',typ,seq,'encoding_reply',pid,tick=13,reply='encode.'+pid,reply_to='encode.'+pid)]+U.mutate(
      E.reply(pid,seq=seq,disposition=disposition,outcome=outcome),'ep_reply',journal_frame_id=fid)+[seal(fid,13,'historical' if disposition=='historical' else 'applied')]

def release_request(pid='prepare',seq=3):
    fid='release.request.'+pid;steps=R.release_request(pid,seq)
    return steps[:1]+[frame(fid,'c2w','RELEASE_ENCODING',seq,'release_request','release.'+pid,tick=50)]+U.mutate(
      steps[1:],'er_request',journal_frame_id=fid)+[seal(fid,51)]

def release_ack(pid='prepare',seq=3,historical=False):
    fid='release.ack.'+pid;req='release.request.'+pid
    return [frame(fid,'w2c','RELEASE_ENCODING_ACK',seq,'release_ack','ack.'+pid,tick=53,reply=req,reply_to=req)]+U.mutate(
      R.acknowledgement(pid,seq,historical),'er_ack',journal_frame_id=fid)+[seal(fid,54,'historical' if historical else 'applied')]

def opening(seq=2):
    fid='dispatch.message'
    return [frame(fid,'c2w','OPEN_GATE',seq,'open_request','dispatch',tick=26)]+U.mutate(S.dispatch(seq=seq),'go_dispatch',journal_frame_id=fid)+[seal(fid,26)]

def open_ack(seq=2,disposition='applied'):
    fid='evidence.message';req='dispatch.message'
    return [frame(fid,'w2c','OPEN_GATE_ACK',seq,'open_ack','evidence',tick=28,reply=req,reply_to=req)]+U.mutate(S.evidence(seq=seq),'go_evidence',journal_frame_id=fid)+[seal(fid,28,disposition)]

def renewal(db,seq=3):
    fid='request.renew'
    return [frame(fid,'c2w','GATE_FENCE',seq,'renewal_request','renew',tick=42)]+U.mutate(Q.request(db,seq=seq,previous='gate.2'),'gf_request',journal_frame_id=fid)+[seal(fid,42)]

def renewal_ack(seq=3,disposition='applied'):
    return [frame('renew.ack','w2c','GATE_FENCE_ACK',seq,'renewal_ack','renew.ack',tick=44,reply='request.renew',reply_to='request.renew')]+U.mutate(
      Q.ack(seq=seq),'gf_ack',journal_frame_id='renew.ack')+[seal('renew.ack',44,disposition)]

def rejection(seq=2,mid='report',typ='SEND_REPORT',session='session.0',eid='exit.0',device='device',reply_to=None,reply=None):
    return [frame(mid,'w2c',typ,seq,'rejection',mid,tick=20,session=session,eid=eid,device=device,reply=reply,reply_to=reply_to),
      I('ij_rejection',rejection_id=mid,frame_id=mid,reason='domain_not_migrated',evidence_body=B),seal(mid,20,'rejected')]

def run():
    assert (HERE/'controller-ipc-journal.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(n,a,e=True):
        assert a==e,(n,a,e);checks.append(dict(name=n,observed=a,expected=e))
    def stage(level='base',kind='ordinary',**kw):
        db=fresh(kind,**kw);connections.append(db)
        if level=='base':return db
        if kind=='gate':
            U.tx(db,S.snapshot(db));U.tx(db,S.plan())
            if level=='planned':return db
            U.tx(db,opening());U.tx(db,[attempted('dispatch.message',27),written('dispatch.message',27)])
            if level=='open_sent':return db
            U.tx(db,open_ack())
            if level=='open_acked':return db
            ready=S.ready(db);ready=U.mutate(ready,'go_gate',control_barrier_id='barrier.1.exit.0',renewal_id=None)
            U.tx(db,ready)
            if level=='ready':return db
            steps=S.protect(db)
            steps.insert(-1,I('go_close',close_id='close.exit.1',device_id='device',exit_id='exit.1',revision=u(1),protection_change_id='protect',gate_id=None,reason_ref='fixture',body=B,outbox_body=B,audit_body=B))
            U.tx(db,steps);U.tx(db,S.close_ack())
            if level=='protected':return db
            U.tx(db,renewal(db));U.tx(db,[attempted('request.renew',42),written('request.renew',42)])
            if level=='renewing':return db
            U.tx(db,renewal_ack());return db
        U.tx(db,request(db,kind))
        if level=='requested':return db
        U.tx(db,encoding(kind))
        if level=='reserved':return db
        U.tx(db,send_encoding())
        if level=='attempted':return db
        U.tx(db,[written('encode.prepare',12)])
        if level=='written':return db
        U.tx(db,reply(kind))
        if level=='prepared':return db
        U.tx(db,release_request())
        if level=='release_reserved':return db
        U.tx(db,[attempted('release.request.prepare',51),written('release.request.prepare',51)])
        if level=='releasing':return db
        U.tx(db,release_ack());return db
    def denied(n,db,steps,expected=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as error:
            if expected:assert str(error)==expected,(n,str(error),expected)
            check(n,U.snapshot(db)==before)
        else:raise AssertionError('未拒绝:'+n)
    def scoped(terminal=False):
        db=stage(kind='scope');C=E.S
        steps=S.protect(db,gid=None)
        steps.insert(-1,I('go_close',close_id='close.exit.1',device_id='device',exit_id='exit.1',revision=u(1),protection_change_id='protect',gate_id=None,reason_ref='fixture',body=B,outbox_body=B,audit_body=B))
        U.tx(db,steps);U.tx(db,S.close_ack())
        U.tx(db,[frame('request.renew','c2w','GATE_FENCE',2,'renewal_request','renew',tick=42)]+
          U.mutate(Q.request(db,previous=None,seq=2),'gf_request',journal_frame_id='request.renew')+[seal('request.renew',42)])
        U.tx(db,[attempted('request.renew',42),written('request.renew',42)])
        U.tx(db,renewal_ack(seq=2));U.tx(db,Q.commit(gid='gate.1',previous=None,rev=1))
        U.tx(db,C.policy(db));U.tx(db,C.assessment(db));U.tx(db,C.plan(db))
        opening_steps=U.mutate(opening(seq=3),'ij_frame',observed_tick=u(48))
        opening_steps=U.mutate(opening_steps,'go_dispatch',reserved_tick=u(48))
        U.tx(db,U.mutate(opening_steps,'ij_commit',committed_tick=u(48)))
        U.tx(db,[attempted('dispatch.message',48),written('dispatch.message',48)])
        if terminal:U.tx(db,[end(tick=49)])
        evidence=U.mutate(C.evidence(),'go_evidence',inbound_seq=u(3),journal_frame_id='evidence.message')
        U.tx(db,[frame('evidence.message','w2c','OPEN_GATE_ACK',3,'open_ack','evidence',tick=49,reply='dispatch.message',reply_to='dispatch.message')]+evidence+
             [seal('evidence.message',49,'historical' if terminal else 'applied')])
        return db
    def atomic(n,level,make,kind='ordinary'):
        total=len(make(stage(level,kind)))
        for i in range(total):
            db=stage(level,kind);steps=make(db)
            denied(n+'缺写'+str(i),db,steps[:i]+steps[i+1:])
            before=U.snapshot(db)
            try:U.tx(db,steps,fault=i)
            except RuntimeError as e:assert str(e)=='injected'
            else:raise AssertionError('未注入')
            check(n+'异常回滚'+str(i),U.snapshot(db)==before)
    try:
        db=stage();check('219表',len(U.snapshot(db)),219)
        check('真实外键与递归触发器',(db.execute('PRAGMA foreign_keys').fetchone()[0],db.execute('PRAGMA recursive_triggers').fetchone()[0]),(1,1))
        check('完整52类型',db.execute('SELECT count(*) FROM ij_type').fetchone()[0],52)
        for kind in ('ordinary','cancel'):
            db=stage('requested',kind);check(kind+'登记不分序号',db.execute('SELECT count(*) FROM ij_frame WHERE session_id=?',('session.0',)).fetchone()[0],2)
            atomic(kind+'编码预约','requested',lambda _:encoding(kind),kind)
            atomic(kind+'发送尝试','reserved',lambda _:send_encoding(),kind)
            atomic(kind+'编码入站','written',lambda _:reply(kind),kind)
            atomic(kind+'释放出站','prepared',lambda _:release_request(),kind)
            atomic(kind+'退款入站','releasing',lambda _:release_ack(),kind)
            db=stage('released',kind)
            check(kind+'唯一退款',db.execute('SELECT count(*) FROM ep_release').fetchone()[0],1)
            check(kind+'未产生设备许可',db.execute('SELECT count(*) FROM ce_permit').fetchone()[0],0)
            check(kind+'外键完整',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        for n,level,make in [('开放出站','planned',lambda _:opening()),('开放入站','open_sent',lambda _:open_ack()),
                              ('换闸出站','protected',renewal),('换闸入站','renewing',lambda _:renewal_ack())]:
            atomic(n,level,make,'gate')
        db=stage('renew_acked','gate');U.tx(db,Q.commit(previous='gate.2',gid='gate.3',rev=3))
        check('换闸采用',db.execute('SELECT count(*) FROM gf_commit').fetchone()[0],1)
        U.tx(db,[end()]);check('结束后换闸候选失效',db.execute('SELECT count(*) FROM gf_valid_fence').fetchone()[0],0)
        db=stage('ready','gate');check('开放真实采用',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0]>0)
        U.tx(db,[end()]);check('结束后ready候选失效',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        db=scoped();U.tx(db,E.S.commit(db));check('限定取消正常采用',db.execute('SELECT count(*) FROM gs_scope_candidate').fetchone()[0]>0)
        U.tx(db,[end()]);check('结束后限定取消候选失效',db.execute('SELECT count(*) FROM gs_scope_candidate').fetchone()[0],0)
        db=scoped(terminal=True);denied('限定取消迟到ACK禁止采用',db,E.S.commit(db))
        db=stage('open_sent','gate');U.tx(db,[end(tick=28)]);U.tx(db,open_ack(disposition='historical'))
        ready=U.mutate(S.ready(db),'go_gate',control_barrier_id='barrier.1.exit.0',renewal_id=None)
        denied('迟到开放ACK禁止采用',db,ready)
        db=stage('renewing','gate');U.tx(db,[end(tick=44)]);U.tx(db,renewal_ack(disposition='historical'))
        denied('迟到换闸ACK禁止采用',db,Q.commit(previous='gate.2',gid='gate.3',rev=3))
        db=stage('written');U.tx(db,[end(tick=13)]);U.tx(db,reply(disposition='historical'))
        check('终止后编码仅历史',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0],0)
        db=stage('written');U.tx(db,[end(tick=13)]);denied('终止后禁止编码采用',db,reply())
        db=stage('releasing');U.tx(db,[E.retire(),E.release(basis='supervisor_retired',eid='exit.0'),end(tick=53)])
        U.tx(db,release_ack(historical=True));check('退役后ACK不重复退款',db.execute('SELECT count(*) FROM ep_release').fetchone()[0],1)
        db=stage('attempted')
        U.tx(db,[end('encode.prepare',13,reason='write_uncertain'),I('ij_write_result',frame_id='encode.prepare',state='uncertain',completed_tick=u(13),written_bytes=1,end_id='end.session.0',result_body=B)])
        check('半帧只查原退役',db.execute("SELECT recovery_action FROM ij_recovery WHERE frame_id='encode.prepare'").fetchone()[0],'ended_never_replay')
        denied('结束后禁止预约',db,release_request())
        db=stage('attempted');denied('部分写不能标完整',db,[U.mutate([written('encode.prepare',12)],'ij_write_result',written_bytes=1)[0]])
        db=stage('attempted');U.tx(db,release_request())
        denied('前帧未完整不可越过',db,[attempted('release.request.prepare',51)])
        db=stage('release_reserved');denied('未尝试请求不能有ACK',db,release_ack())
        for field,value in [('seq',u(0)),('seq',u(3)),('seq','2'),('direction','w2c'),('exit_id','exit.1'),('message_type','OPEN_GATE'),('domain_kind','unbound')]:
            denied('编码错字段'+field+str(value),stage('requested'),U.mutate(encoding(),'ij_frame',**{field:value}))
        for field,value in [('response_seq',u(3)),('response_frame',b'other'),('response_frame_digest','other'),('reply_to','other'),('outcome','rejected')]:
            denied('响应错字段'+field,stage('written'),U.mutate(reply(),'ep_reply',**{field:value}))
        denied('把失败伪装成功帧',stage('written'),U.mutate(reply(outcome='failed'),'ij_frame',message_type='PREPARE_PACKET'))
        denied('编码领域历史与日志采用不符',stage('written'),U.mutate(reply(disposition='historical'),'ij_commit',disposition='applied'))
        denied('编码尝试双边tick不符',stage('reserved'),U.mutate(send_encoding(),'ij_write_attempt',attempted_tick=u(13)))
        denied('编码尝试双边身份不符',stage('reserved'),U.mutate(send_encoding(),'ij_write_attempt',attempt_id='other'))
        db=stage('planned','gate');U.tx(db,opening());denied('开放最终发送截止等号',db,[attempted('dispatch.message',80)])
        db=stage('protected','gate');U.tx(db,renewal(db));denied('换闸最终发送截止等号',db,[attempted('request.renew',52)])
        db=stage();U.tx(db,[end()]);denied('结束后新准备不能排队',db,request(db))
        db=stage('released');before=U.snapshot(db)
        check('丢提交响应查原ACK',db.execute("SELECT adoption_id FROM er_ack_commit WHERE ack_id='ack.prepare'").fetchone()[0],'adoption.prepare')
        check('查原无再执行',U.snapshot(db)==before)
        denied('重复完整写集不能再执行',db,release_ack())
        db=stage('prepared');denied('编码和释放序号碰撞',db,release_request(seq=2))
        db=stage('prepared');denied('跨领域复用消息ID',db,U.mutate(release_request(),'ij_frame',message_id='encode.prepare'))
        db=stage('planned','gate');U.tx(db,F.adapt(F.V.public(F.C.initial(),1)));U.tx(db,request(db));U.tx(db,encoding());denied('开放和编码共享序号',db,opening(seq=2))
        db=stage();U.tx(db,rejection());check('未迁移消息明确拒收',db.execute("SELECT recovery_action FROM ij_recovery WHERE frame_id='report'").fetchone()[0],'query_rejection_never_send')
        denied('非响应不能伪造reply',stage(),rejection(reply='hello_ack.session.0',reply_to='hello_ack.session.0'))
        denied('响应不能无原请求',stage(),rejection(typ='RELEASE_ENCODING_ACK'))
        denied('拒收不能伪装领域采用',stage(),U.mutate(rejection(),'ij_commit',disposition='applied'))
        db=stage();e=U.one(db,"SELECT * FROM ce_exit WHERE exit_id='exit.0'");e.update(exit_id='other.device.exit',device_id='other',device_session_id='other.device.session')
        U.tx(db,[I('ce_exit',**e),I('ij_exit',exit_id=e['exit_id'],session_id='session.0')])
        U.tx(db,rejection(mid='first'));denied('同worker多设备共享序号',db,rejection(mid='other',eid=e['exit_id'],device='other'))
        U.tx(db,rejection(seq=3,mid='other',eid=e['exit_id'],device='other'))
        check('跨设备连续号',db.execute("SELECT seq FROM ij_frame WHERE frame_id='other'").fetchone()[0],u(3))
        db=stage(frames=5,reserved=2);U.tx(db,rejection(typ='EVIDENCE_CANDIDATE'))
        denied('普通帧不得占保护预留',db,rejection(3,'ordinary','EVIDENCE_CANDIDATE'))
        U.tx(db,rejection(3,'protected'));U.tx(db,rejection(4,'protected2'))
        denied('保护槽也有硬上限',db,rejection(5,'overflow'))
        db=stage(bytes_limit=4*len(B),reserved_bytes=len(B));U.tx(db,rejection(typ='EVIDENCE_CANDIDATE'))
        denied('字节保护预留',db,rejection(3,'ordinary','EVIDENCE_CANDIDATE'))
        U.tx(db,rejection(3,'protected'));denied('字节硬上限',db,rejection(4,'overflow'))
        db=stage(handshaken=False)
        denied('握手前普通消息',db,rejection(seq=1))
        for i in range(6):
            steps=handshake()[:6];denied('握手缺写'+str(i),db,steps[:i]+steps[i+1:])
        db=stage('released');U.tx(db,rejection(4,'stored.rejection'));U.tx(db,[end()])
        for table in G.TABLES:
            check(table+'已填充不可变样本',db.execute('SELECT count(*) FROM '+table).fetchone()[0]>0)
            for action in ('UPDATE','DELETE'):
                before=U.snapshot(db);column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
                sql=f'UPDATE {table} SET {column}={column}' if action=='UPDATE' else 'DELETE FROM '+table
                try:db.execute(sql)
                except sqlite3.IntegrityError:check(table+action,U.snapshot(db)==before)
                else:raise AssertionError(table+'可变')
        check('四最终准入阻断保留',db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0],4)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'ipc-journal-storage-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=219,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
