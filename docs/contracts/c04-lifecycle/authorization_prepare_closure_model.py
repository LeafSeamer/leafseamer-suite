"""从实际编码撤回与DENY原件形成完整准备核销；不退款、不恢复、不操作设备。"""
import json
from jsonschema import Draft202012Validator
import authorization_close_ack_model as A
import close_evidence_model as CE
M=A.M;P=A.P;D=A.D;E=A.E;I=A.I;C=D.C;HERE=A.G.HERE
SCHEMA_PATH=HERE.parent/'c08-controller/ipc-journal.schema.json'
SCHEMA=json.loads(SCHEMA_PATH.read_bytes());MAX_MEMBERS=4096;MAX_CLOSURE_BYTES=16*1024*1024
def ref(value,idkey,digestkey):return M.reference(value,idkey,digestkey)
def validate(name,value):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name}).validate(value)
def transaction(db,fn):
    if db.in_transaction:raise C.I.ClockIngressStop('preparation_closure_nested_transaction')
    try:
        db.execute('BEGIN IMMEDIATE');value=fn();db.commit();return value
    except Exception as error:
        try:
            if db.in_transaction:db.rollback()
        except Exception:pass
        raise C.I.ClockIngressStop('preparation_closure_exit_required') from error
def writer(db,fail_after):
    writes=[]
    def write(table,**row):
        db.execute(*I(table,**row));writes.append(table)
        if fail_after==len(writes)-1:raise RuntimeError('injected_prepare_closure_write')
    return writes,write
def source(db,close_id,pid):
    dispatch,original=CE.dispatch(db,close_id);binding=dispatch['target']['binding']
    member=M.E.one(db,'SELECT m.* FROM pd_member m JOIN go_close c ON c.prepare_cut_id=m.cut_id WHERE c.close_id=? AND m.prepare_id=?',(close_id,pid))
    request=M.E.one(db,'SELECT * FROM ep_request WHERE prepare_id=?',(pid,));authorization=M.document(request['authorization_body']);E.validate('EA__EncodingAuthorization',authorization)
    M.need(authorization==M.sealed(authorization,'authorization_digest') and authorization['binding']==binding and authorization['authorization_id']==request['authorization_id']==member['authorization_id'] and authorization['authorization_digest']==request['authorization_digest']==member['authorization_digest'] and request['exit_id']==member['exit_id']==binding['writer_exit_id'],'deny_authorization_source')
    encoding=M.E.one(db,'SELECT * FROM ij_encoding_frame WHERE prepare_id=?',(pid,));encoded=M.E.one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(encoding['journal_frame_id'],));frame=M.document(encoded['frame_body']);E.FRAME.validate(frame)
    M.need(encoded['frame_body']==encoding['request_frame'] and encoded['frame_digest']==encoding['request_frame_digest']==M.F.digest(frame) and frame['message_id']==request['request_message_id'] and frame['body']['encoding_authorization']==authorization,'deny_encoding_source')
    revocation=M.E.one(db,'SELECT * FROM ep_revocation WHERE prepare_id=?',(pid,));reason=M.document(revocation['reason_body'])
    M.need(M.F.digest(reason)==revocation['revocation_digest'],'deny_revocation_digest')
    return dispatch,original,member,request,authorization,encoded,revocation
def journal(db,frame,session,exit_id,tick,kind,identity,write,reply=None):
    E.FRAME.validate(frame);raw=M.raw(frame);wire=len(raw).to_bytes(4,'big')+raw
    evidence=M.raw(dict(kind=kind,source_id=identity,frame_digest=M.F.digest(frame)))
    write('ij_frame',frame_id=frame['message_id'],session_id=session,exit_id=exit_id,device_id=frame['device_id'],direction='w2c' if reply else 'c2w',message_type=frame['type'],message_id=frame['message_id'],seq=P.u(frame['seq']),reply_frame_id=reply,reply_to=frame['reply_to'],
        frame_digest=M.F.digest(frame),wire_digest=E.byte_digest(wire),frame_body=raw,body_body=M.raw(frame['body']),wire_body=wire,wire_length=len(wire),observed_tick=P.u(tick),domain_kind=kind,domain_id=identity,validation_body=evidence)
def seal(write,mid,tick,evidence,disposition='applied'):write('ij_commit',frame_id=mid,disposition=disposition,committed_tick=P.u(tick),audit_body=M.raw(evidence),effect_body=M.raw(evidence))
def stored_frame(db,mid):
    f=M.E.one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(mid,));frame=M.document(f['frame_body']);E.FRAME.validate(frame)
    wire=len(f['frame_body']).to_bytes(4,'big')+f['frame_body']
    M.need(M.raw(frame)==f['frame_body'] and M.F.digest(frame)==f['frame_digest'] and f['body_body']==M.raw(frame['body']) and f['wire_body']==wire and f['wire_digest']==E.byte_digest(wire) and f['wire_length']==len(wire),'deny_frame_original')
    M.need(frame['message_id']==f['message_id']==mid and frame['seq']==str(int(f['seq'])) and frame['type']==f['message_type'] and frame['device_id']==f['device_id'] and frame['reply_to']==f['reply_to'],'deny_frame_columns')
    return frame,f
def read_request(db,close_id,pid):
    dispatch,original,member,request,authorization,encoded,revocation=source(db,close_id,pid)
    row=M.E.one(db,'SELECT * FROM pd_deny_request WHERE prepare_id=?',(pid,));frame,f=stored_frame(db,row['journal_frame_id']);body=frame['body']
    expected=M.sealed(dict(deny_id=row['deny_id'],revision='1',binding=dispatch['target']['binding'],prepare_id=pid,
        encoding_authorization_ref=ref(authorization,'authorization_id','authorization_digest'),encode_message_id=request['request_message_id'],encode_frame_digest=encoded['frame_digest'],
        revocation_ref=M.E.ref(revocation['revocation_id'],str(int(revocation['revocation_revision'])),revocation['revocation_digest']),selected_tick_ns=str(int(row['selected_tick']))),'request_digest')
    validate('DenyRequest',body);M.need(body==expected and row['body']==M.raw(body) and row['frame_body']==M.raw(frame) and row['request_digest']==body['request_digest'],'deny_request_body')
    M.need(f['domain_kind']=='prepare_deny_request' and f['domain_id']==row['deny_id'] and f['direction']=='c2w' and frame['type']=='DENY_ENCODING' and f['session_id']==original['session_id'] and f['exit_id']==member['exit_id'] and f['observed_tick']==row['selected_tick'],'deny_request_columns')
    k=M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(f['frame_id'],));M.need(k['disposition']=='applied' and k['committed_tick']==row['selected_tick'],'deny_request_commit')
    return frame,f,row
def deny(db,close_id,pid,tick,fail_after=None):
    def run():
        writes,write=writer(db,fail_after)
        if db.execute('SELECT 1 FROM pd_deny_request WHERE prepare_id=?',(pid,)).fetchone():return read_request(db,close_id,pid)[0],writes
        dispatch,original,member,request,authorization,encoded,revocation=source(db,close_id,pid)
        M.need(not db.execute('SELECT 1 FROM ij_end WHERE session_id=?',(original['session_id'],)).fetchone(),'deny_session_ended')
        did=P.identity('encoding_deny',dict(prepare_id=pid,revocation_id=revocation['revocation_id']))
        body=M.sealed(dict(deny_id=did,revision='1',binding=dispatch['target']['binding'],prepare_id=pid,encoding_authorization_ref=ref(authorization,'authorization_id','authorization_digest'),
            encode_message_id=request['request_message_id'],encode_frame_digest=encoded['frame_digest'],revocation_ref=M.E.ref(revocation['revocation_id'],str(int(revocation['revocation_revision'])),revocation['revocation_digest']),selected_tick_ns=str(int(P.u(tick)))),'request_digest');validate('DenyRequest',body)
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='c2w'",(original['session_id'],)).fetchone()[0])+1
        frame=E.frame(body['binding'],'DENY_ENCODING',did,seq,body)
        journal(db,frame,original['session_id'],member['exit_id'],tick,'prepare_deny_request',did,write)
        write('pd_deny_request',deny_id=did,prepare_id=pid,journal_frame_id=did,revision=P.u(1),request_digest=body['request_digest'],exit_id=member['exit_id'],authorization_id=request['authorization_id'],authorization_digest=request['authorization_digest'],
            encode_message_id=request['request_message_id'],encode_frame_digest=encoded['frame_digest'],revocation_id=revocation['revocation_id'],revocation_revision=revocation['revocation_revision'],revocation_digest=revocation['revocation_digest'],selected_tick=P.u(tick),frame_body=M.raw(frame),body=M.raw(body),audit_body=M.raw(body))
        seal(write,did,tick,body);read_request(db,close_id,pid);return frame,writes
    return transaction(db,run)
def begin_write(db,close_id,pid,tick):
    def run():
        frame,f,row=read_request(db,close_id,pid)
        if db.execute('SELECT 1 FROM ij_write_attempt WHERE frame_id=?',(f['frame_id'],)).fetchone():return 'lookup_only'
        proof=M.raw(dict(deny_ref=ref(frame['body'],'deny_id','request_digest')))
        db.execute(*I('ij_write_attempt',frame_id=f['frame_id'],attempt_id=f['frame_id']+'.write',attempted_tick=P.u(tick),encoding_prepare_id=None,current_validation_body=proof,audit_body=proof));return 'attempt_recorded'
    return transaction(db,run)
def read_ack(db,close_id,pid):
    request,original,r=read_request(db,close_id,pid);row=M.E.one(db,'SELECT * FROM pd_deny_ack WHERE deny_id=?',(r['deny_id'],));frame,f=stored_frame(db,row['journal_frame_id']);body=frame['body'];validate('DenyAck',body)
    M.need(frame['type']=='DENY_ENCODING_ACK' and frame['reply_to']==request['message_id'] and body['binding']==request['body']['binding'] and body['prepare_id']==pid and body['deny_ref']==ref(request['body'],'deny_id','request_digest') and body['deny_message_id']==request['message_id'] and body['deny_frame_digest']==M.F.digest(request),'deny_ack_source')
    M.need(f['session_id']==original['session_id'] and f['reply_frame_id']==original['frame_id'] and f['domain_kind']=='prepare_deny_ack' and f['domain_id']==row['ack_id'] and f['frame_body']==row['frame_body'] and f['observed_tick']==row['received_tick'] and P.u(body['effective_tick_ns'])==row['effective_tick'],'deny_ack_columns')
    M.need(all(frame[k]==request[k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id','clock_domain_id','descriptor_digest')) and f['direction']=='w2c' and f['exit_id']==row['exit_id']==r['exit_id'],'deny_ack_envelope')
    M.need(row['prepare_id']==pid and row['deny_revision']==r['revision'] and row['deny_digest']==r['request_digest'] and row['deny_message_id']==request['message_id'] and row['deny_frame_digest']==M.F.digest(request) and row['future_use_denied']==1 and row['validation_body']==M.raw(body),'deny_ack_query_columns')
    attempt=M.E.one(db,'SELECT * FROM ij_write_attempt WHERE frame_id=?',(original['frame_id'],))
    M.need(attempt['attempted_tick']<=row['effective_tick']<=row['received_tick'],'deny_ack_time_order')
    k=M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(f['frame_id'],));M.need(k['committed_tick']==row['received_tick'],'deny_ack_commit')
    return frame,f,row,k
def receive(db,close_id,pid,wire,tick,fail_after=None):
    def run():
        writes,write=writer(db,fail_after)
        M.need(isinstance(wire,bytes) and 4<len(wire)<=262148 and int.from_bytes(wire[:4],'big')==len(wire)-4,'deny_ack_wire')
        frame=M.document(wire[4:]);E.FRAME.validate(frame);M.need(M.raw(frame)==wire[4:],'deny_ack_canonical')
        if db.execute('SELECT 1 FROM pd_deny_ack WHERE prepare_id=?',(pid,)).fetchone():
            old,f,_,_=read_ack(db,close_id,pid);M.need(f['wire_body']==wire,'deny_ack_replay_conflict');return old,writes
        request,original,r=read_request(db,close_id,pid);body=frame['body'];validate('DenyAck',body)
        M.need(frame['type']=='DENY_ENCODING_ACK' and frame['reply_to']==request['message_id'] and body['binding']==request['body']['binding'] and body['prepare_id']==pid and body['deny_ref']==ref(request['body'],'deny_id','request_digest') and body['deny_message_id']==request['message_id'] and body['deny_frame_digest']==M.F.digest(request),'deny_ack_binding')
        M.need(all(frame[k]==request[k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id','clock_domain_id','descriptor_digest')),'deny_ack_session')
        aid=P.identity('deny_ack',dict(prepare_id=pid,frame_digest=M.F.digest(frame)));disposition='historical' if db.execute('SELECT 1 FROM ij_end WHERE session_id=?',(original['session_id'],)).fetchone() else 'applied'
        journal(db,frame,original['session_id'],r['exit_id'],tick,'prepare_deny_ack',aid,write,original['frame_id'])
        write('pd_deny_ack',ack_id=aid,deny_id=r['deny_id'],prepare_id=pid,journal_frame_id=frame['message_id'],exit_id=r['exit_id'],deny_revision=r['revision'],deny_digest=r['request_digest'],deny_message_id=request['message_id'],deny_frame_digest=M.F.digest(request),
            effective_tick=P.u(body['effective_tick_ns']),received_tick=P.u(tick),future_use_denied=1,frame_body=M.raw(frame),validation_body=M.raw(body),audit_body=M.raw(body))
        seal(write,frame['message_id'],tick,body,disposition);read_ack(db,close_id,pid);return frame,writes
    return transaction(db,run)
def current(db,close_id):
    view=CE.current_view(db,close_id)
    return view is not None and db.execute('SELECT 1 FROM pd_close_completion c JOIN pd_valid_closure p USING(closure_id) JOIN '+view+' a ON a.adopted_ack_id=c.ack_id WHERE c.close_id=?',(close_id,)).fetchone() is not None
def complete(db,close_id,tick,fail_after=None):
    def run():
        writes,write=writer(db,fail_after)
        old=db.execute('SELECT p.body FROM pd_close_completion c JOIN pd_closure p USING(closure_id) WHERE c.close_id=?',(close_id,)).fetchone()
        if old:
            value=M.document(old[0]);validate('PreparationClosure',value);M.need(M.sealed(value,'closure_digest')==value,'prepare_closure_digest');return value,current(db,close_id),writes
        ack,_=CE.ack(db,close_id);M.need(CE.usable(db,close_id,ack['ack_id']) and P.u(tick)>=P.u(ack['received_tick_ns']),'prepare_close_ack_not_current')
        close=M.E.one(db,'SELECT * FROM go_close WHERE close_id=?',(close_id,));cut=M.E.one(db,'SELECT * FROM pd_cut WHERE cut_id=?',(close['prepare_cut_id'],));selector=M.document(cut['selector_body']);M.need(M.F.digest(selector)==cut['selector_digest'],'prepare_selector_digest')
        members=P.rows(db,'SELECT prepare_id,exit_id,authorization_id,authorization_digest FROM pd_member WHERE cut_id=? ORDER BY prepare_id LIMIT ?',(cut['cut_id'],MAX_MEMBERS+1));M.need(len(members)<=MAX_MEMBERS,'prepare_closure_capacity')
        registry=P.rows(db,'SELECT * FROM pd_registration WHERE sequence<=? ORDER BY sequence LIMIT ?',(cut['prepare_head'],MAX_MEMBERS+1));M.need(len(registry)<=MAX_MEMBERS,'prepare_registry_capacity')
        proofs=[];coverage=[]
        for member in members:
            pid=member['prepare_id'];r=M.E.one(db,'SELECT * FROM ep_request WHERE prepare_id=?',(pid,));authorization=M.document(r['authorization_body']);E.validate('EA__EncodingAuthorization',authorization)
            M.need(M.sealed(authorization,'authorization_digest')==authorization and authorization['authorization_id']==member['authorization_id'] and authorization['authorization_digest']==member['authorization_digest'],'prepare_closure_authorization')
            release=db.execute("SELECT 1 FROM ep_release WHERE prepare_id=? AND basis='worker_released'",(pid,)).fetchone()
            if release:
                import authorization_prepare_release_model as R
                adopted,frame,f=R.read_adoption(db,close_id,pid)
                M.need(P.u(adopted['committed_tick_ns'])<=P.u(tick),'prepare_release_after_closure')
                basis='released';proof=C.source_ref('release_proof',dict(adoption=adopted,frame=frame));ack_id=None
            elif db.execute('SELECT 1 FROM ep_send_attempt WHERE prepare_id=?',(pid,)).fetchone():
                frame,f,a,k=read_ack(db,close_id,pid);M.need(k['disposition']=='applied' and k['committed_tick']<=P.u(tick) and not db.execute('SELECT 1 FROM pd_ack_revocation WHERE ack_id=?',(a['ack_id'],)).fetchone(),'prepare_deny_ack_not_current')
                basis='deny_ack';proof=C.source_ref('denial_proof',dict(ack=C.columns(a),frame=frame));ack_id=a['ack_id']
            else:
                rev=M.E.one(db,'SELECT * FROM ep_revocation WHERE prepare_id=?',(pid,));basis='never_attempted';ack_id=None
                proof=C.source_ref('unattempted_proof',dict(request=C.columns(r),revocation=C.columns(rev),registry_head=str(int(cut['prepare_head']))))
            proofs.append(dict(prepare_id=pid,encoding_authorization_ref=ref(authorization,'authorization_id','authorization_digest'),writer_exit_id=member['exit_id'],basis=basis,proof_ref=proof))
            coverage.append(dict(cut_id=cut['cut_id'],prepare_id=pid,basis=basis,ack_id=ack_id,retirement_exit_id=None,proof_body=M.raw(proofs[-1])))
        ident=P.identity('preparation_closure',dict(close_id=close_id,cut_id=cut['cut_id']))
        value=M.sealed(dict(closure_id=ident,revision='1',scope=M.E.A.scope(db),operation_ref=C.source_ref('close_operation',C.columns(close)),selector_ref=C.source_ref('close_selector',selector),
            registry_ref=C.source_ref('preparation_registry',dict(head=str(int(cut['prepare_head'])),entries=[C.columns(r) for r in registry])),prepare_head=str(int(cut['prepare_head'])),members=proofs),'closure_digest');validate('PreparationClosure',value)
        M.need(len(M.raw(value))<=MAX_CLOSURE_BYTES,'prepare_closure_byte_capacity')
        write('pd_closure',closure_id=ident,cut_id=cut['cut_id'],revision=P.u(1),closure_digest=value['closure_digest'],committed_tick=P.u(tick),body=M.raw(value))
        for row in coverage:write('pd_coverage',closure_id=ident,**row)
        write('pd_closure_commit',closure_id=ident,audit_body=M.raw(value),outbox_body=M.raw(value))
        write('pd_close_completion',close_id=close_id,ack_id=ack['ack_id'],closure_id=ident,audit_body=M.raw(value))
        M.need(current(db,close_id),'prepare_closure_incomplete')
        return value,current(db,close_id),writes
    return transaction(db,run)
