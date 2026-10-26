"""同会话编码释放原件、精确预留回收及核销证明；不执行产品IPC。"""
import json
from jsonschema import Draft202012Validator
import authorization_prepare_closure_model as N
M=N.M;P=N.P;D=N.D;E=N.E;C=N.C;I=N.I;HERE=N.HERE
SCHEMA_PATH=HERE.parent/'c08-controller/encoding-release.schema.json'
SCHEMA=json.loads(SCHEMA_PATH.read_bytes())
FIELDS=('ipc_session_id','controller_boot_id','worker_boot_id','device_id','clock_domain_id','descriptor_digest')
def validate(name,v):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name}).validate(v)
def rref(v):return N.ref(v,'release_id','request_digest')
def request_body(db,cid,pid,rid,tick):
    dispatch,original,member,r,a,encoded,v=N.source(db,cid,pid)
    body=M.sealed(dict(release_id=rid,revision='1',binding=dispatch['target']['binding'],prepare_id=pid,encoding_authorization_ref=N.ref(a,'authorization_id','authorization_digest'),
        encode_message_id=r['request_message_id'],encode_frame_digest=encoded['frame_digest'],revocation_ref=M.E.ref(v['revocation_id'],str(int(v['revocation_revision'])),v['revocation_digest']),selected_tick_ns=str(int(P.u(tick)))),'request_digest')
    validate('ReleaseRequest',body);return body,original,member,r,v
def read_request(db,cid,pid):
    row=M.E.one(db,'SELECT * FROM er_request WHERE prepare_id=?',(pid,));frame,f=N.stored_frame(db,row['journal_frame_id'])
    expected,original,member,r,v=request_body(db,cid,pid,row['release_id'],str(int(row['selected_tick'])))
    M.need(frame['body']==expected and row['body']==M.raw(expected) and row['release_digest']==expected['request_digest'] and row['release_revision']==P.u(1),'release_request_body')
    M.need(all(frame[k]==expected['binding'][k] for k in FIELDS) and frame['type']=='RELEASE_ENCODING' and frame['reply_to'] is None and f['reply_frame_id'] is None and f['direction']=='c2w','release_request_envelope')
    M.need(f['session_id']==original['session_id'] and f['exit_id']==row['exit_id']==member['exit_id'] and f['domain_kind']=='release_request' and f['domain_id']==row['release_id'] and f['frame_body']==row['frame_body'] and f['frame_digest']==row['frame_digest'] and f['seq']==row['outbound_seq'] and f['message_id']==row['message_id'] and f['observed_tick']==row['selected_tick'],'release_request_columns')
    M.need(row['authorization_id']==r['authorization_id'] and row['authorization_digest']==r['authorization_digest'] and row['encode_message_id']==expected['encode_message_id'] and row['encode_frame_digest']==expected['encode_frame_digest'] and row['revocation_id']==v['revocation_id'] and row['revocation_revision']==v['revocation_revision'] and row['revocation_digest']==v['revocation_digest'],'release_request_sources')
    k=M.E.one(db,'SELECT * FROM er_request_commit WHERE release_id=?',(row['release_id'],));j=M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(f['frame_id'],))
    M.need(k['committed_tick']==j['committed_tick']==row['selected_tick'] and k['outbox_body']==M.raw(frame) and j['disposition']=='applied','release_request_seals')
    return frame,f,row
def queue(db,cid,pid,tick,fail_after=None):
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM er_request WHERE prepare_id=?',(pid,)).fetchone():return read_request(db,cid,pid)[0],writes
        rid=P.identity('encoding_release',dict(close_id=cid,prepare_id=pid));body,original,member,r,v=request_body(db,cid,pid,rid,tick)
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='c2w'",(original['session_id'],)).fetchone()[0])+1
        frame=E.frame(body['binding'],'RELEASE_ENCODING',rid,seq,body)
        N.journal(db,frame,original['session_id'],member['exit_id'],tick,'release_request',rid,write)
        write('er_request',journal_frame_id=rid,release_id=rid,release_revision=P.u(1),release_digest=body['request_digest'],prepare_id=pid,exit_id=member['exit_id'],authorization_id=r['authorization_id'],authorization_digest=r['authorization_digest'],encode_message_id=r['request_message_id'],encode_frame_digest=body['encode_frame_digest'],
            revocation_id=v['revocation_id'],revocation_revision=v['revocation_revision'],revocation_digest=v['revocation_digest'],selected_tick=P.u(tick),message_id=rid,outbound_seq=P.u(seq),frame_digest=M.F.digest(frame),frame_body=M.raw(frame),body=M.raw(body))
        write('er_request_commit',release_id=rid,committed_tick=P.u(tick),validation_body=M.raw(body),audit_body=M.raw(body),outbox_id=rid+'.outbox',outbox_body=M.raw(frame))
        N.seal(write,rid,tick,body);read_request(db,cid,pid);return frame,writes
    return N.transaction(db,run)
def begin_write(db,cid,pid,tick):
    def run():
        frame,f,r=read_request(db,cid,pid)
        if db.execute('SELECT 1 FROM ij_write_attempt WHERE frame_id=?',(f['frame_id'],)).fetchone():return 'lookup_only'
        proof=M.raw(dict(release_ref=rref(frame['body'])))
        db.execute(*I('ij_write_attempt',frame_id=f['frame_id'],attempt_id=f['frame_id']+'.write',attempted_tick=P.u(tick),encoding_prepare_id=None,current_validation_body=proof,audit_body=proof));return 'attempt_recorded'
    return N.transaction(db,run)
def check_ack(db,request,original,frame,tick):
    body=frame['body'];validate('ReleaseAck',body)
    M.need(all(frame[k]==request[k] for k in FIELDS) and body['binding']==request['body']['binding'] and frame['type']=='RELEASE_ENCODING_ACK' and frame['reply_to']==request['message_id'],'release_ack_binding')
    M.need(body['release_ref']==rref(request['body']) and body['prepare_id']==request['body']['prepare_id'] and body['release_message_id']==request['message_id'] and body['release_frame_digest']==M.F.digest(request),'release_ack_request')
    attempt=M.E.one(db,'SELECT * FROM ij_write_attempt WHERE frame_id=?',(original['frame_id'],))
    M.need(attempt['attempted_tick']<=P.u(body['disposed_tick_ns'])<=P.u(tick),'release_ack_time')
    return body
def adoption(request,frame,r,aid,received,committed):
    value=M.sealed(dict(adoption_id=aid,revision='1',binding=request['body']['binding'],prepare_id=r['prepare_id'],release_ref=rref(request['body']),ack_message_id=frame['message_id'],ack_frame_digest=M.F.digest(frame),
        encoding_reservation_ref=M.E.ref(r['reservation_id'],str(int(r['reservation_revision'])),r['reservation_digest']),reserved_bytes=r['max_bytes'],received_tick_ns=str(int(P.u(received))),committed_tick_ns=str(int(P.u(committed)))),'adoption_digest')
    validate('ReleaseAdoption',value);return value
def read_adoption(db,cid,pid):
    request,original,q=read_request(db,cid,pid);r=M.E.one(db,'SELECT * FROM ep_request WHERE prepare_id=?',(pid,));a=M.E.one(db,'SELECT * FROM er_adoption WHERE prepare_id=?',(pid,))
    ack=M.E.one(db,'SELECT * FROM er_ack WHERE ack_id=?',(a['ack_id'],));frame,f=N.stored_frame(db,ack['journal_frame_id']);body=check_ack(db,request,original,frame,str(int(ack['received_tick'])))
    value=adoption(request,frame,r,a['adoption_id'],str(int(a['received_tick'])),str(int(a['committed_tick'])))
    M.need(M.document(a['body'])==value and a['adoption_digest']==value['adoption_digest'] and a['adoption_revision']==P.u(1) and a['release_id']==q['release_id'] and a['reservation_id']==r['reservation_id'] and a['reservation_revision']==r['reservation_revision'] and a['reservation_digest']==r['reservation_digest'] and a['reserved_bytes']==r['max_bytes'] and a['received_tick']==ack['received_tick']<=a['committed_tick'],'release_adoption_source')
    M.need(f['domain_kind']=='release_ack' and f['domain_id']==ack['ack_id'] and f['direction']=='w2c' and f['session_id']==original['session_id'] and f['exit_id']==ack['exit_id']==q['exit_id'] and f['reply_frame_id']==original['frame_id'] and f['observed_tick']==ack['received_tick'],'release_ack_journal')
    M.need(ack['release_id']==q['release_id'] and ack['prepare_id']==pid and ack['release_revision']==q['release_revision'] and ack['release_digest']==q['release_digest'] and ack['frame_body']==M.raw(frame) and ack['frame_digest']==M.F.digest(frame) and ack['message_id']==frame['message_id'] and ack['inbound_seq']==P.u(frame['seq']) and ack['reply_to']==request['message_id'] and ack['release_frame_digest']==M.F.digest(request) and ack['disposed_tick']==P.u(body['disposed_tick_ns']) and ack['state']=='released' and all(ack[k]==1 for k in ('encoder_quiescent','consumers_quiescent','cache_empty')),'release_ack_columns')
    k=M.E.one(db,'SELECT * FROM er_ack_commit WHERE ack_id=?',(ack['ack_id'],));j=M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(f['frame_id'],));release=M.E.one(db,'SELECT * FROM ep_release WHERE prepare_id=?',(pid,))
    M.need(k['adoption_id']==a['adoption_id'] and k['disposition']=='released' and k['committed_tick']==j['committed_tick']==a['committed_tick'] and j['disposition']=='applied' and release['basis']=='worker_released' and release['worker_adoption_id']==a['adoption_id'] and release['retirement_exit_id'] is None and release['proof_body']==M.raw(value),'release_atomic_adoption')
    return value,frame,f
def receive(db,cid,pid,wire,tick,fail_after=None):
    def run():
        writes,write=N.writer(db,fail_after)
        M.need(isinstance(wire,bytes) and 4<len(wire)<=262148 and int.from_bytes(wire[:4],'big')==len(wire)-4,'release_ack_wire')
        frame=M.document(wire[4:]);E.FRAME.validate(frame);M.need(M.raw(frame)==wire[4:],'release_ack_canonical')
        if db.execute('SELECT 1 FROM er_adoption WHERE prepare_id=?',(pid,)).fetchone():
            value,old,f=read_adoption(db,cid,pid);M.need(f['wire_body']==wire,'release_ack_replay_conflict');return value,writes
        request,original,q=read_request(db,cid,pid);body=check_ack(db,request,original,frame,tick)
        M.need(not db.execute('SELECT 1 FROM ij_end WHERE session_id=?',(original['session_id'],)).fetchone() and not db.execute('SELECT 1 FROM ce_retirement WHERE exit_id=?',(q['exit_id'],)).fetchone(),'release_session_not_current')
        r=M.E.one(db,'SELECT * FROM ep_request WHERE prepare_id=?',(pid,));aid=P.identity('release_adoption',dict(prepare_id=pid,frame_digest=M.F.digest(frame)));ackid=aid+'.ack';value=adoption(request,frame,r,aid,tick,tick)
        N.journal(db,frame,original['session_id'],q['exit_id'],tick,'release_ack',ackid,write,original['frame_id'])
        write('er_ack',journal_frame_id=frame['message_id'],ack_id=ackid,release_id=q['release_id'],prepare_id=pid,exit_id=q['exit_id'],release_revision=q['release_revision'],release_digest=q['release_digest'],message_id=frame['message_id'],inbound_seq=P.u(frame['seq']),reply_to=frame['reply_to'],release_frame_digest=M.F.digest(request),disposed_tick=P.u(body['disposed_tick_ns']),received_tick=P.u(tick),state='released',encoder_quiescent=1,consumers_quiescent=1,cache_empty=1,frame_digest=M.F.digest(frame),frame_body=M.raw(frame),validation_body=M.raw(body))
        write('er_adoption',adoption_id=aid,adoption_revision=P.u(1),adoption_digest=value['adoption_digest'],prepare_id=pid,ack_id=ackid,release_id=q['release_id'],reservation_id=r['reservation_id'],reservation_revision=r['reservation_revision'],reservation_digest=r['reservation_digest'],reserved_bytes=r['max_bytes'],received_tick=P.u(tick),committed_tick=P.u(tick),body=M.raw(value),audit_body=M.raw(value))
        write('ep_release',prepare_id=pid,basis='worker_released',retirement_exit_id=None,worker_adoption_id=aid,proof_body=M.raw(value),audit_body=M.raw(value))
        write('er_ack_commit',ack_id=ackid,disposition='released',adoption_id=aid,committed_tick=P.u(tick),audit_body=M.raw(value))
        N.seal(write,frame['message_id'],tick,value);read_adoption(db,cid,pid);return value,writes
    return N.transaction(db,run)
