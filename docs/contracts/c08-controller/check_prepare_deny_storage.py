"""准备拒绝、完整cut与旧关闭seal的内存SQLite检查。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_prepare_deny_storage as G
import check_ipc_journal_storage as J
import check_barrier_attempt as A
I,U,F,H,O,u,B,D=J.I,J.U,J.F,J.H,J.O,J.u,J.B,J.D
R=J.R;E=J.E;HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(J.INPUTS+G.SOURCES+[HERE/n for n in ('PREPARE_DENY_STORAGE.md','check_prepare_deny_storage.py','controller-prepare-deny.sql')]))
INPUTS=list(dict.fromkeys(INPUTS+A.INPUTS))

def fresh():
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    for steps in ([F.F.A.namespace()],F.F.P.register(),F.F.P.change()):U.tx(db,F.adapt(steps))
    U.tx(db,U.mutate(F.adapt([F.F.A.namespace()]),'ca_namespace',namespace_id='cancel.ns',issuer_id='issuer',issuer_epoch='epoch',principal_id='bob',request_epoch='cancel.requests',owner_evidence_id='cancel.owner'))
    for n in (0,1):
        eid='exit.'+str(n);sid='session.'+str(n)
        U.tx(db,U.mutate(F.adapt([F.F.exit_step(eid)]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
        e=U.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,))
        U.tx(db,[I('ij_session',session_id=sid,scope_id=1,controller_boot_id=e['controller_boot_id'],worker_boot_id=e['worker_boot_id'],ipc_session_id=e['ipc_session_id'],clock_domain_id='domain',descriptor_digest='descriptor',protocol_version='ipc/0.13.0-journal-draft.1',profile_body=B,binding_body=B,max_frames=128,reserved_frames=16,max_bytes=32768,reserved_bytes=1024),I('ij_exit',exit_id=eid,session_id=sid)])
        U.tx(db,J.handshake(sid))
    U.tx(db,F.adapt(F.V.public(F.C.initial(),1)));U.tx(db,U.bootstrap(db,'bob'))
    U.tx(db,[I('ep_limit',singleton=1,profile_id='fixture',profile_revision=u(1),profile_digest=D,max_live_prepares=8,max_live_bytes=32,max_metadata_prepares=16,profile_body=B)])
    return db

def registration(db,kind='ordinary',pid='prepare',seq=1,origin=None,prep=None,receipt=None,**kw):
    steps=J.request(db,kind,pid=pid,**kw)
    # 普通来源对应已有命令；取消必须显式给自己的来源，不默认借父来源。
    if origin is None:origin='automation' if kind=='ordinary' else 'manual'
    if kind=='ordinary' and origin=='automation':prep,receipt='p','receipt.p'
    current=U.current(db)
    return steps[:-1]+[I('pd_registration',prepare_id=pid,sequence=u(seq),origin=origin,prep_key=prep,receipt_id=receipt,
      control_epoch=current['control_epoch'],effective_version=current['effective_version'],provenance_body=B)]+steps[-1:]

def capture(db,steps,kind,old_id,pids,head,tick):
    table,seal,key,ref={'control':('cu_cut','ct_commit','operation_id','control_id'),
      'cancel':('cc_cut','cc_cut_commit','cut_id','cancel_id'),'run':('ce_fence','ce_cut_commit','fence_id','run_id'),
      'close':('go_close','ct_commit','close_id','close_id')}[kind]
    cid='prepare.cut.'+old_id;steps=copy.deepcopy(steps)
    next(v for t,v in steps if t==table and v[key]==old_id)['prepare_cut_id']=cid
    refs=dict(control_id=None,cancel_id=None,run_id=None,close_id=None);refs[ref]=old_id
    additions=[I('pd_cut',cut_id=cid,kind=kind,prepare_head=u(head),selected_tick=u(tick),selector_digest=D,selector_body=B,**refs)]
    for pid in pids:
        row=U.one(db,'SELECT * FROM ep_request WHERE prepare_id=?',(pid,))
        additions.append(I('pd_member',cut_id=cid,prepare_id=pid,exit_id=row['exit_id'],authorization_id=row['authorization_id'],authorization_digest=row['authorization_digest']))
        if not db.execute('SELECT 1 FROM ep_revocation WHERE prepare_id=?',(pid,)).fetchone():additions.append(R.revoke(pid,tick))
    additions.append(I('pd_cut_commit',cut_id=cid,committed_tick=u(tick),audit_body=B,outbox_body=B))
    index=next(i for i,(t,v) in enumerate(steps) if t==seal and (seal=='ct_commit' or v[key]==old_id))
    return steps[:index]+additions+steps[index:]

def close_control(db,pids=('prepare',),head=1):
    steps=F.start(db,kind='acquire',members=(),water=0)
    steps=U.mutate(steps,'ct_operation',requester_id='charlie',target_id='charlie')
    steps=U.mutate(steps,'ct_request',actor_id='charlie')
    # 原queued关闭保持真实公开修订，不跳过旧控制守卫。
    block=F.adapt(F.V.public(F.C.revision(2,'block',phase='finished',outcome='blocked',effect='not_sent',latched=1,terminal=2),2))
    return capture(db,steps[:-1]+block+steps[-1:],'control','op',pids,head,15)

def closure(cut,proofs,cid='closure',tick=19):
    steps=[I('pd_closure',closure_id=cid,cut_id='prepare.cut.'+cut,revision=u(1),closure_digest=D,committed_tick=u(tick),body=B)]
    for pid,basis in proofs:
        steps.append(I('pd_coverage',closure_id=cid,cut_id='prepare.cut.'+cut,prepare_id=pid,basis=basis,
          ack_id='deny.ack.'+pid if basis=='deny_ack' else None,retirement_exit_id='exit.0' if basis=='retired' else None,proof_body=B))
    return steps+[I('pd_closure_commit',closure_id=cid,audit_body=B,outbox_body=B)]

def deny(pid='prepare',seq=3,tick=16):
    fid='deny.request.'+pid
    return [J.frame(fid,'c2w','DENY_ENCODING',seq,'prepare_deny_request','deny.'+pid,tick=tick),
      I('pd_deny_request',deny_id='deny.'+pid,prepare_id=pid,journal_frame_id=fid,revision=u(1),request_digest=D,exit_id='exit.0',authorization_id='auth.'+pid,authorization_digest=D,encode_message_id='encode.'+pid,encode_frame_digest=D,revocation_id='revocation.'+pid,revocation_revision=u(1),revocation_digest=D,selected_tick=u(tick),frame_body=B,body=B,audit_body=B),J.seal(fid,tick)]

def ack(pid='prepare',seq=3,disposition='applied'):
    fid='deny.ack.'+pid;req='deny.request.'+pid
    return [J.frame(fid,'w2c','DENY_ENCODING_ACK',seq,'prepare_deny_ack',fid,tick=18,reply=req,reply_to=req),
      I('pd_deny_ack',ack_id=fid,deny_id='deny.'+pid,prepare_id=pid,journal_frame_id=fid,exit_id='exit.0',deny_revision=u(1),deny_digest=D,deny_message_id=req,deny_frame_digest=D,effective_tick=u(17),received_tick=u(18),future_use_denied=1,frame_body=B,validation_body=B,audit_body=B),J.seal(fid,18,disposition)]

def effective(db,cid='closure'):
    return U.mutate(F.effective(db,members=(),now=19),'cu_effective',prepare_closure_id=cid)

def cancellation(db,pids=(),head=0):
    steps=U.mutate(F.adapt(F.V.cancel(2,attempts=(),permits=(),cut=0)),'cv_cancel',mode='cooperative')
    U.tx(db,U.mutate(steps,'cv_cancel_key',namespace_id='cancel.ns'))
    steps=U.mutate(F.adapt(H.X.cut(members=[])),'cc_cut',issued_revision=u(0))
    U.tx(db,capture(db,steps,'cancel','ordinary',pids,head,15))
    for eid in ('exit.0','exit.1'):
        U.tx(db,F.adapt([H.X.attempt(eid=eid)]))
        U.tx(db,F.adapt([x for x in H.X.ack(eid=eid) if not x[0].startswith('INSERT INTO cc_coverage ')]))
    U.tx(db,closure('ordinary',[(p,'never_attempted') for p in pids],cid='ordinary.preparations'))
    U.tx(db,U.mutate(F.adapt(H.X.closure()),'cc_closure',prepare_closure_id='ordinary.preparations'))
    U.tx(db,O.acquire(db))

def run_cut(db,pids=('prepare',),head=1):
    return capture(db,F.adapt(F.F.fence(items=(),queued=('one',),revision=0)),'run','f',pids,head,20)

def protection(db,pids=('prepare',),head=1):
    steps=J.S.protect(db,gid=None)
    steps.insert(-1,I('go_close',close_id='close.exit.1',device_id='device',exit_id='exit.1',revision=u(1),protection_change_id='protect',gate_id=None,reason_ref='fixture',body=B,outbox_body=B,audit_body=B))
    steps=capture(db,steps,'close','close',pids,head,40)
    return capture(db,steps,'close','close.exit.1',(),head,40)

def run():
    assert (HERE/'controller-prepare-deny.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(n,a,e=True):assert a==e,(n,a,e);checks.append(dict(name=n,observed=a,expected=e))
    def stage(level='base'):
        db=fresh();connections.append(db)
        if level=='base':return db
        U.tx(db,registration(db))
        if level=='registered':return db
        U.tx(db,J.encoding());U.tx(db,J.send_encoding());U.tx(db,[J.written('encode.prepare',12)])
        if level=='unknown':return db
        U.tx(db,J.reply())
        if level=='prepared':return db
        U.tx(db,close_control(db))
        for e in ('exit.0','exit.1'):U.tx(db,U.mutate(F.ack(e,members=()),'cu_ack',issued_revision=u(0)))
        if level=='cut':return db
        U.tx(db,deny())
        if level=='deny_reserved':return db
        U.tx(db,[J.attempted('deny.request.prepare',16),J.written('deny.request.prepare',16)])
        if level=='denying':return db
        U.tx(db,ack())
        if level=='acked':return db
        U.tx(db,closure('op',[('prepare','deny_ack')]))
        if level=='closed':return db
        U.tx(db,effective(db));return db
    def denied(n,db,steps,error=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as e:
            if error:assert str(e)==error,(n,str(e),error)
            check(n,U.snapshot(db)==before)
        else:raise AssertionError(n+':未拒绝')
    def atomic(n,level,make):
        for i in range(len(make(stage(level)))):
            db=stage(level);steps=make(db);denied(n+'缺写'+str(i),db,steps[:i]+steps[i+1:])
            before=U.snapshot(db)
            try:U.tx(db,steps,fault=i)
            except RuntimeError as e:assert str(e)=='injected'
            else:raise AssertionError('未注入故障')
            check(n+'异常回滚'+str(i),U.snapshot(db)==before)
    try:
        db=stage();check('230表',len(U.snapshot(db)),230)
        atomic('准备登记','base',registration)
        atomic('接管准备捕获','prepared',close_control)
        atomic('拒绝出站','cut',lambda _:deny())
        atomic('拒绝入站','denying',lambda _:ack())
        atomic('完整准备关闭','acked',lambda _:closure('op',[('prepare','deny_ack')]))
        atomic('RUN准备捕获','registered',run_cut)
        atomic('保护关闭准备捕获','registered',protection)
        db=stage('effective');check('真实T4生效',U.current(db)['effective_version'],u(4))
        check('Deny不退款',db.execute('SELECT count(*) FROM ep_release').fetchone()[0],0)
        check('准备字节仍预留',db.execute('SELECT sum(max_bytes) FROM ep_live_reservation').fetchone()[0],4)
        check('外键完整',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        db=stage('acked');denied('无Closure禁止T4',db,effective(db))
        db=stage('closed');steps=effective(db)
        steps.insert(-1,I('pd_ack_revocation',ack_id='deny.ack.prepare',reason_body=B,audit_body=B,outbox_body=B))
        denied('T4最终seal重核准备证明',db,steps)
        db=stage('acked');denied('尝试过不能声称未尝试',db,closure('op',[('prepare','never_attempted')]))
        denied('未实际退款不能声称released',db,closure('op',[('prepare','released')]))
        denied('缺成员不能关闭',db,closure('op',[]))
        denied('错准备不能关闭',db,closure('op',[('other','deny_ack')]))
        db=stage('prepared');denied('遗漏捕获不能封存',db,close_control(db,pids=()))
        denied('旧登记水位不能封存',db,close_control(db,head=0))
        denied('错授权成员',db,U.mutate(close_control(db),'pd_member',authorization_digest='other'))
        db=stage('registered');other=registration(db,pid='other',seq=2,primitive='primitive.2')
        U.tx(db,U.mutate(other,'ep_request',exit_id='exit.1'))
        denied('不同旧出口不能遗漏',db,close_control(db,head=2))
        U.tx(db,close_control(db,pids=('prepare','other'),head=2))
        U.tx(db,closure('op',[('prepare','never_attempted'),('other','never_attempted')]))
        check('两出口准备完整捕获',db.execute('SELECT count(*) FROM pd_member').fetchone()[0],2)
        db=stage('unknown');U.tx(db,J.reply(outcome='failed',disposition='failed'));U.tx(db,close_control(db))
        check('编码失败仍纳入全集',db.execute('SELECT count(*) FROM pd_member').fetchone()[0],1)
        denied('失败不等于未尝试',db,closure('op',[('prepare','never_attempted')]))
        db=stage('cut');denied('接管后旧版本不能登记',db,registration(db,pid='late',seq=2,primitive='late.primitive'))
        for field,value in [('encode_message_id','other'),('authorization_id','other'),('revocation_digest','other'),('encode_frame_digest','other'),('exit_id','exit.1')]:
            denied('拒绝错绑定'+field,stage('cut'),U.mutate(deny(),'pd_deny_request',**{field:value}))
        for field,value in [('deny_digest','other'),('deny_message_id','other'),('prepare_id','other'),('effective_tick',u(15)),('exit_id','exit.1')]:
            denied('ACK错绑定'+field,stage('denying'),U.mutate(ack(),'pd_deny_ack',**{field:value}))
        denied('未入流不可有ACK',stage('deny_reserved'),ack())
        db=stage('denying');U.tx(db,[J.end(tick=18)]);U.tx(db,ack(disposition='historical'))
        denied('终止后历史ACK不能完成Closure',db,closure('op',[('prepare','deny_ack')]))
        db=stage('effective');U.tx(db,[I('pd_ack_revocation',ack_id='deny.ack.prepare',reason_body=B,audit_body=B,outbox_body=B)])
        check('撤回准备证据使控制候选失效',db.execute('SELECT count(*) FROM cu_valid_effective').fetchone()[0],0)
        db=stage('registered');U.tx(db,close_control(db));U.tx(db,closure('op',[('prepare','never_attempted')]))
        check('未尝试本地永久拒绝',db.execute('SELECT count(*) FROM pd_valid_closure').fetchone()[0],1)
        denied('被捕获准备不可新预约',db,J.encoding())
        db=stage('unknown');U.tx(db,close_control(db));U.tx(db,[E.retire()]);U.tx(db,closure('op',[('prepare','retired')]))
        check('未知编码只能用真实退役关闭',db.execute('SELECT count(*) FROM pd_valid_closure').fetchone()[0],1)
        db=stage('cut');U.tx(db,[E.retire('exit.1')]);denied('错误worker退役不能覆盖',db,U.mutate(closure('op',[('prepare','retired')]),'pd_coverage',retirement_exit_id='exit.1'))
        db=stage('prepared');U.tx(db,J.release_request());U.tx(db,[J.attempted('release.request.prepare',51),J.written('release.request.prepare',51)]);U.tx(db,J.release_ack())
        steps=U.mutate(close_control(db),'ct_change',now_tick=u(60));steps=U.mutate(steps,'pd_cut',selected_tick=u(60));steps=U.mutate(steps,'pd_cut_commit',committed_tick=u(60))
        U.tx(db,steps);U.tx(db,closure('op',[('prepare','released')],tick=61))
        check('已释放历史仍在全集',db.execute('SELECT count(*) FROM pd_member').fetchone()[0],1)
        db=stage('registered');cancellation(db,('prepare',),1)
        U.tx(db,registration(db,'cancel',pid='cancel.prepare',seq=2))
        check('取消使用自身manual来源',db.execute("SELECT origin,run_id FROM pd_source WHERE prepare_id='cancel.prepare'").fetchone(),('manual',None))
        denied('同取消不能中途改来源',db,registration(db,'cancel',pid='cancel.other',seq=3,primitive='cancel.other',origin='automation',prep='p',receipt='receipt.p'))
        U.tx(db,run_cut(db,head=2));check('RUN不借父来源关闭手动取消',db.execute("SELECT prepare_id FROM pd_member WHERE cut_id='prepare.cut.f'").fetchall(),[('prepare',)])
        U.tx(db,closure('f',[('prepare','never_attempted')],cid='run.preparations',tick=21))
        for n,eid in enumerate(('exit.0','exit.1')):
            bid='run.barrier.'+str(n);U.tx(db,F.adapt([A.attempt(bid,eid=eid)]));U.tx(db,F.adapt(A.ack(bid,eid,items=False)))
            U.tx(db,F.adapt([A.I('ce_result_binding',fence_id='f',exit_id=eid,barrier_id=bid,kind='worker_ack',binding_body=B),A.F.result(eid,items=())[-1]]))
        denied('RUN采用缺准备Closure',db,F.adapt([F.F.application()]))
        U.tx(db,U.mutate(F.adapt([F.F.application()]),'ce_application',prepare_closure_id='run.preparations'))
        check('RUN应用有真实双封存',db.execute('SELECT count(*) FROM pd_valid_application').fetchone()[0],1)
        denied('RUN已拒绝代次不再登记',db,registration(db,pid='later',seq=3,primitive='p.later'))
        db=stage('registered');cancellation(db,('prepare',),1);U.tx(db,registration(db,'cancel',pid='cancel.prepare',seq=2))
        all_steps=U.mutate(F.adapt(H.X.cut('all',members=[],prepares=['cancel.prepare'])),'cc_cut',issued_revision=u(0))
        denied('all不能遗漏自身取消准备',db,capture(db,all_steps,'cancel','all',('prepare',),2,20))
        U.tx(db,capture(db,all_steps,'cancel','all',('prepare','cancel.prepare'),2,20))
        U.tx(db,closure('all',[('prepare','never_attempted'),('cancel.prepare','never_attempted')],cid='all.preparations',tick=21))
        for eid in ('exit.0','exit.1'):
            U.tx(db,F.adapt([H.X.attempt('all',eid)]))
            steps=[x for x in H.X.ack('all',eid) if not x[0].startswith('INSERT INTO cc_coverage ')]
            if eid=='exit.0':steps=H.X.extra(steps,'cc_ack_prepare',prepare_id='cancel.prepare')
            U.tx(db,F.adapt(steps))
        old=F.adapt(H.X.closure('all'));denied('all旧关闭必须带准备Closure',db,old)
        U.tx(db,U.mutate(old,'cc_closure',prepare_closure_id='all.preparations'))
        check('取消all真实完成',db.execute("SELECT count(*) FROM cc_valid_closure WHERE cut_id='all'").fetchone()[0],1)
        db=stage('registered');U.tx(db,protection(db));U.tx(db,J.S.close_ack())
        U.tx(db,U.mutate(J.S.close_ack('close.exit.1','close.ack.1'),'go_close_ack',exit_id='exit.1'))
        complete=[I('pd_close_completion',close_id='close',ack_id='close.ack',closure_id='protected.preparations',audit_body=B)]
        denied('物理关闭ACK不代替准备证明',db,complete)
        U.tx(db,closure('close',[('prepare','never_attempted')],cid='protected.preparations',tick=42))
        U.tx(db,closure('close.exit.1',[],cid='other.preparations',tick=42))
        U.tx(db,complete+[I('pd_close_completion',close_id='close.exit.1',ack_id='close.ack.1',closure_id='other.preparations',audit_body=B)])
        check('保护关闭逐出口完成',db.execute('SELECT count(*) FROM pd_close_completion').fetchone()[0],2)
        for statement in ('UPDATE pd_close_completion SET close_id=close_id','DELETE FROM pd_close_completion'):
            try:db.execute(statement)
            except sqlite3.IntegrityError:check('保护完成不可变'+statement.split()[0],True)
            else:raise AssertionError('保护完成可变')
        db=stage('prepared');U.tx(db,protection(db))
        U.tx(db,J.S.close_ack());U.tx(db,U.mutate(J.S.close_ack('close.exit.1','close.ack.1'),'go_close_ack',exit_id='exit.1'))
        U.tx(db,deny(tick=41));U.tx(db,[J.attempted('deny.request.prepare',41),J.written('deny.request.prepare',41)])
        ack_steps=U.mutate(ack(),'ij_frame',observed_tick=u(42))
        ack_steps=U.mutate(ack_steps,'pd_deny_ack',effective_tick=u(42),received_tick=u(42))
        U.tx(db,U.mutate(ack_steps,'ij_commit',committed_tick=u(42)))
        U.tx(db,closure('close',[('prepare','deny_ack')],cid='protected.preparations',tick=43))
        U.tx(db,closure('close.exit.1',[],cid='other.preparations',tick=43))
        recovery=U.mutate(J.S.recovery(db),'go_snapshot',authority_state_id='base')
        recovery.insert(-1,I('go_recovery_target',recovery_id='recover',close_id='close.exit.1',ack_id='close.ack.1'))
        denied('无准备完成记录不能恢复',db,recovery)
        U.tx(db,[I('pd_close_completion',close_id='close',ack_id='close.ack',closure_id='protected.preparations',audit_body=B),
                 I('pd_close_completion',close_id='close.exit.1',ack_id='close.ack.1',closure_id='other.preparations',audit_body=B)])
        U.tx(db,recovery);check('关闭恢复正常采用',db.execute('SELECT count(*) FROM go_valid_recovery').fetchone()[0],1)
        U.tx(db,[J.frame('request.renew','c2w','GATE_FENCE',4,'renewal_request','renew',tick=46)]+
          U.mutate(J.Q.request(db,previous=None,tick=46,seq=4),'gf_request',journal_frame_id='request.renew')+[J.seal('request.renew',46)])
        U.tx(db,[J.attempted('request.renew',46),J.written('request.renew',46)])
        renewal_ack=U.mutate(J.renewal_ack(seq=4),'ij_frame',observed_tick=u(48))
        renewal_ack=U.mutate(renewal_ack,'gf_ack',effective_tick=u(47),received_tick=u(48))
        U.tx(db,U.mutate(renewal_ack,'ij_commit',committed_tick=u(48)))
        U.tx(db,J.Q.commit(gid='gate.1',previous=None,rev=1,tick=49))
        U.tx(db,J.S.plan('plan','snap.2','gate.1','protect','recover',50))
        opened=U.mutate(J.opening(seq=5),'ij_frame',observed_tick=u(51))
        opened=U.mutate(opened,'go_dispatch',reserved_tick=u(51));U.tx(db,U.mutate(opened,'ij_commit',committed_tick=u(51)))
        U.tx(db,[J.attempted('dispatch.message',51),J.written('dispatch.message',51)])
        evidence=U.mutate(J.open_ack(seq=5),'ij_frame',observed_tick=u(55))
        evidence=U.mutate(evidence,'go_evidence',received_tick=u(55),gate_revision=u(2),gate_token='token.2')
        U.tx(db,U.mutate(evidence,'ij_commit',committed_tick=u(55)))
        ready=U.mutate(J.S.ready(db,wire=2,tick=56),'go_gate',control_barrier_id=None,renewal_id='renew',barrier_id='renew')
        U.tx(db,ready);check('完整准备证明后实际ready',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0]>0)
        U.tx(db,[I('pd_ack_revocation',ack_id='deny.ack.prepare',reason_body=B,audit_body=B,outbox_body=B)])
        check('撤回使旧恢复失效',db.execute('SELECT count(*) FROM go_valid_recovery').fetchone()[0],0)
        check('撤回使旧ready候选失效',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        db=stage('effective');before=U.snapshot(db)
        check('提交响应丢失查原',db.execute("SELECT closure_id FROM pd_valid_closure WHERE cut_id='prepare.cut.op'").fetchone()[0],'closure')
        check('查原不重效果',U.snapshot(db)==before)
        denied('重复原ACK不重复采用',db,ack())
        for table in G.TABLES:
            if table=='pd_close_completion':continue
            if table=='pd_ack_revocation':U.tx(db,[I(table,ack_id='deny.ack.prepare',reason_body=B,audit_body=B,outbox_body=B)])
            check(table+'非空不可变样本',db.execute('SELECT count(*) FROM '+table).fetchone()[0]>0)
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for statement in (f'UPDATE {table} SET {column}={column}','DELETE FROM '+table):
                before=U.snapshot(db)
                try:db.execute(statement)
                except sqlite3.IntegrityError:check(table+statement.split()[0],U.snapshot(db)==before)
                else:raise AssertionError('可变:'+table)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'prepare-deny-storage-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=230,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
