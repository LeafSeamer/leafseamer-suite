"""类型化命令的首次出口开放参考写集；只验证持久关系，不执行IPC或授发送权。"""
import final_admission_storage_model as A

I=A.insert;u=A.u;raw=A.raw;G=A.G
B=raw({'synthetic':True})

def one(db,sql,args=()):
    cursor=db.execute(sql,args);row=cursor.fetchone()
    if row is None:raise ValueError('missing_gate_original')
    return dict(zip([x[0] for x in cursor.description],row))

def digest(value):return A.F.digest(value)

def context(db,command):
    c=one(db,'SELECT * FROM ce_command WHERE command_id=?',(command,))
    device=c['device_id'];prefix='gate.'+command
    return dict(command=command,device=device,prefix=prefix,exit=prefix+'.exit')

def current(db,c):return one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(c['device'],))
def authority(db,c):return one(db,'SELECT * FROM go_authority WHERE device_id=?',(c['device'],))
def hazard(db,c):return int(db.execute('SELECT coalesce(max(revision),?) FROM go_hazard WHERE device_id=?',(u('0'),c['device'])).fetchone()[0])
def key(c,name):return c['prefix']+'.'+name

def frame(c,name,direction,typ,seq,domain,oid,tick,reply=None,device=True,frame_digest=None):
    fid=key(c,name)
    return I('ij_frame',frame_id=fid,session_id=key(c,'session'),exit_id=c['exit'] if device else None,device_id=c['device'] if device else None,
        direction=direction,message_type=typ,message_id=fid,seq=u(str(seq)),reply_frame_id=key(c,reply) if reply else None,reply_to=key(c,reply) if reply else None,
        frame_digest=frame_digest or digest(fid),wire_digest=digest({'synthetic':True}),frame_body=B,body_body=B,wire_body=B,wire_length=len(B),
        observed_tick=u(str(tick)),domain_kind=domain,domain_id=key(c,oid),validation_body=B)

def seal(c,name,tick,disposition='applied'):
    return I('ij_commit',frame_id=key(c,name),disposition=disposition,committed_tick=u(str(tick)),audit_body=B,effect_body=B)

def write(c,name,tick):
    fid=key(c,name)
    return [I('ij_write_attempt',frame_id=fid,attempt_id=fid+'.write',attempted_tick=u(str(tick)),encoding_prepare_id=None,current_validation_body=B,audit_body=B),
        I('ij_write_result',frame_id=fid,state='written',completed_tick=u(str(tick)),written_bytes=len(B),end_id=None,result_body=B)]

def session(db,c,tick=11):
    e=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(c['exit'],));sid=key(c,'session')
    steps=[I('ij_session',session_id=sid,scope_id=1,**{k:e[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','clock_domain_id','descriptor_digest')},
        protocol_version='ipc/0.13.0-journal-draft.1',profile_body=B,binding_body=B,max_frames=64,reserved_frames=8,max_bytes=32768,reserved_bytes=1024),
        I('ij_exit',exit_id=c['exit'],session_id=sid)]
    for name,direction,typ,reply in [('hello','w2c','HELLO',None),('hello_ack','c2w','HELLO_ACK','hello')]:
        steps += [frame(c,name,direction,typ,1,'handshake',name,tick,reply,False),I('ij_handshake',handshake_id=key(c,name),frame_id=key(c,name),kind=typ,negotiation_body=B),seal(c,name,tick)]
    return steps+write(c,'hello_ack',tick)

def control(db,c,name,kind,tick,gate):
    old=one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(c['device'],));state=current(db,c);cid=key(c,name)
    change=dict(old,change_id=cid,sequence=u(str(int(old['sequence'])+1)),previous_id=old['change_id'],kind=kind,state_id=cid,
        operation_id=None,offer_id=None,request_id=None,now_tick=u(str(tick)))
    after={k:v for k,v in state.items() if k!='device_id'}
    after.update(change_id=cid,record_revision=u(str(int(state['record_revision'])+1)),gate_state=gate,record_digest=digest(cid),record_body=B)
    return [I('ct_change',**change),I('ct_state',**after)]

def finish(c,name):
    cid=key(c,name)
    return [I('ct_audit',change_id=cid,body=B),I('ct_outbox',change_id=cid,event_id=cid,body=B),I('ct_commit',change_id=cid)]

def register(db,c):
    """首次出口、空准备集合；若已有出口或准备，交由完整集合writer处理，不能漏列。"""
    if db.execute('SELECT 1 FROM ce_exit WHERE device_id=?',(c['device'],)).fetchone():raise ValueError('initial_exit_only')
    if db.execute('SELECT 1 FROM ep_request').fetchone():raise ValueError('initial_preparation_set_only')
    old=one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(c['device'],));tick=int(old['now_tick'])+1
    close='registration.'+c['exit'];cut=key(c,'cut');cid=key(c,'protect')
    head=db.execute('SELECT coalesce(max(sequence),?) FROM pd_registration',(u('0'),)).fetchone()[0]
    return [I('ce_exit',exit_id=c['exit'],device_id=c['device'],controller_boot_id=key(c,'controller'),worker_boot_id=key(c,'worker'),
        ipc_session_id=key(c,'ipc'),device_session_id=key(c,'device'),clock_domain_id=old['clock_domain'],descriptor_digest=old['descriptor'],runtime_binding_body=B),
        *control(db,c,'protect','gate_protect',tick,'protected'),
        I('go_close',prepare_cut_id=cut,close_id=close,device_id=c['device'],exit_id=c['exit'],revision=u('1'),protection_change_id=cid,gate_id=None,reason_ref='new_exit',body=B,outbox_body=B,audit_body=B),
        I('pd_cut',cut_id=cut,kind='close',prepare_head=head,selected_tick=u(str(tick)),selector_digest=digest(cut),selector_body=B,control_id=None,cancel_id=None,run_id=None,close_id=close),
        I('pd_cut_commit',cut_id=cut,committed_tick=u(str(tick)),audit_body=B,outbox_body=B),*finish(c,'protect')]

def close_ack(c,tick=12):
    return [I('go_close_ack',ack_id=key(c,'close.ack'),close_id='registration.'+c['exit'],exit_id=c['exit'],evidence_digest=digest(key(c,'close.ack')),
        observer_ref='synthetic.observer',received_tick=u(str(tick)),body=B,validation_body=B,audit_body=B)]

def close_preparations(c,tick=13):
    closure=key(c,'closure')
    return [I('pd_closure',closure_id=closure,cut_id=key(c,'cut'),revision=u('1'),closure_digest=digest(closure),committed_tick=u(str(tick)),body=B),
        I('pd_closure_commit',closure_id=closure,audit_body=B,outbox_body=B),
        I('pd_close_completion',close_id='registration.'+c['exit'],ack_id=key(c,'close.ack'),closure_id=closure,audit_body=B)]

def renew(db,c,tick=14):
    return [frame(c,'fence.message','c2w','GATE_FENCE',2,'renewal_request','renew',tick),
        I('gf_request',journal_frame_id=key(c,'fence.message'),request_id=key(c,'renew'),device_id=c['device'],exit_id=c['exit'],previous_gate_id=None,
        authority_state_id=authority(db,c)['change_id'],control_state_id=current(db,c)['change_id'],close_ack_id=key(c,'close.ack'),safety_revision=u(str(hazard(db,c))),
        target_revision=u('1'),gate_token=key(c,'token'),message_id=key(c,'fence.message'),outbound_seq=u('2'),selected_tick=u(str(tick)),expires_tick=u('30'),
        lease_until_tick=u('100'),request_digest=digest(key(c,'renew')),body=B,outbox_body=B,audit_body=B),seal(c,'fence.message',tick)]

def fence_ack(c,tick=16,disposition='applied'):
    return [frame(c,'fence.reply','w2c','GATE_FENCE_ACK',2,'renewal_ack','fence.ack',tick,'fence.message'),
        I('gf_ack',journal_frame_id=key(c,'fence.reply'),ack_id=key(c,'fence.ack'),request_id=key(c,'renew'),exit_id=c['exit'],message_id=key(c,'fence.reply'),reply_to=key(c,'fence.message'),
        inbound_seq=u('2'),request_digest=digest(key(c,'renew')),gate_revision=u('1'),gate_token=key(c,'token'),effective_tick=u('15'),received_tick=u(str(tick)),
        evidence_digest=digest(key(c,'fence.ack')),observer_ref='synthetic.observer',body=B,validation_body=B,audit_body=B),seal(c,'fence.reply',tick,disposition)]

def gate(c,ready=False):
    return I('go_gate',gate_id=key(c,'ready.gate' if ready else 'fenced.gate'),exit_id=c['exit'],previous_id=key(c,'fenced.gate') if ready else None,
        record_revision=u('2' if ready else '1'),gate_revision=u('1'),gate_token=key(c,'token'),barrier_id=key(c,'renew'),control_barrier_id=None,
        renewal_id=key(c,'renew'),phase='ready' if ready else 'fenced',ready_id=key(c,'ready') if ready else None,lease_until_tick=u('100'),
        record_digest=digest(key(c,'ready.gate' if ready else 'fenced.gate')),record_body=B)

def fence_commit(c,tick=17):
    return [gate(c),I('gf_commit',request_id=key(c,'renew'),ack_id=key(c,'fence.ack'),gate_id=key(c,'fenced.gate'),committed_tick=u(str(tick)),audit_body=B,outbox_body=B)]

def recovery(db,c,tick=18):
    """当前空hold首次开放；来源正文与提供者仍为合成，不能当产品资格证明。"""
    if db.execute('SELECT 1 FROM cr_risk_hold WHERE device_id=?',(c['device'],)).fetchone():raise ValueError('initial_hold_set_only')
    sid=key(c,'snapshot');rid=key(c,'recovery')
    return [I('go_recovery',recovery_id=rid,device_id=c['device'],snapshot_id=sid,now_tick=u(str(tick)),recovery_digest=digest(rid),body=B,provider_ref='synthetic.provider'),
        I('go_snapshot',snapshot_id=sid,device_id=c['device'],exit_id=c['exit'],authority_state_id=authority(db,c)['change_id'],control_state_id=current(db,c)['change_id'],
          safety_revision=u(str(hazard(db,c)+1)),authorization_ref=key(c,'authorization'),resource_ref=key(c,'resources'),run_snapshot_ref=key(c,'runs'),
          command_snapshot_ref=key(c,'commands'),time_snapshot_ref=key(c,'time'),sampled_tick=u(str(tick)),expires_tick=u('90'),provider_ref='synthetic.provider',evidence_digest=digest(sid),evidence_body=B),
        I('go_snapshot_commit',snapshot_id=sid,audit_body=B),
        I('go_recovery_target',recovery_id=rid,close_id='registration.'+c['exit'],ack_id=key(c,'close.ack')),
        I('go_recovery_commit',recovery_id=rid,audit_body=B,outbox_body=B)]

def plan(db,c,tick=19):
    pid=key(c,'plan')
    return [I('go_plan',plan_id=pid,snapshot_id=key(c,'snapshot'),before_gate_id=key(c,'fenced.gate'),before_control_id=current(db,c)['change_id'],
        basis_kind='gate_recovery',activation_id=None,resource_recovery_id=None,gate_recovery_id=key(c,'recovery'),selected_tick=u(str(tick)),expires_tick=u('80'),
        plan_digest=digest(pid),proposal_digest=digest(key(c,'proposal')),body=B),I('go_plan_commit',plan_id=pid,audit_body=B)]

def dispatch(c,tick=20):
    return [frame(c,'open.message','c2w','OPEN_GATE',3,'open_request','dispatch',tick,frame_digest=digest(key(c,'dispatch'))),
        I('go_dispatch',journal_frame_id=key(c,'open.message'),dispatch_id=key(c,'dispatch'),plan_id=key(c,'plan'),exit_id=c['exit'],message_id=key(c,'open.message'),outbound_seq=u('3'),
        reserved_tick=u(str(tick)),frame_digest=digest(key(c,'dispatch')),frame_body=B,outbox_body=B,audit_body=B),seal(c,'open.message',tick)]

def evidence(c,tick=21,disposition='applied'):
    return [frame(c,'open.reply','w2c','OPEN_GATE_ACK',3,'open_ack','open.ack',tick,'open.message'),
        I('go_evidence',journal_frame_id=key(c,'open.reply'),evidence_id=key(c,'open.ack'),dispatch_id=key(c,'dispatch'),exit_id=c['exit'],message_id=key(c,'open.reply'),reply_to=key(c,'open.message'),
        inbound_seq=u('3'),received_tick=u(str(tick)),gate_token=key(c,'token'),gate_revision=u('1'),run_snapshot_ref=key(c,'runs'),command_snapshot_ref=key(c,'commands'),
        time_snapshot_ref=key(c,'time'),observer_ref='synthetic.observer',evidence_digest=digest(key(c,'open.ack')),frame_body=B,validation_body=B,audit_body=B),seal(c,'open.reply',tick,disposition)]

def ready(db,c,tick=22):
    rid=key(c,'ready')
    return [*control(db,c,'ready','ready',tick,'ready'),gate(c,True),I('go_ready',ready_id=rid,plan_id=key(c,'plan'),evidence_id=key(c,'open.ack'),
        change_id=rid,after_gate_id=key(c,'ready.gate'),committed_tick=u(str(tick)),ready_digest=digest(rid),transition_digest=digest(key(c,'transition')),transition_body=B),*finish(c,'ready')]

def execute(db,steps,fail_after=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        for index,(sql,args) in enumerate(steps):
            db.execute(sql,args)
            if index==fail_after:raise RuntimeError('injected')
        db.commit()
    except BaseException:
        if db.in_transaction:db.rollback()
        raise
