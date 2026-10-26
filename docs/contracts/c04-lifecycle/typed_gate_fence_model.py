"""完整换闸请求、ACK及fenced采用；不发OPEN或实际线路。"""
from jsonschema import Draft202012Validator
import authorization_prepare_closure_model as N
import build_typed_gate_fence as G
M=N.M;P=N.P;E=N.E;C=N.C;S=P.S;I=N.I;CE=N.CE
def validate(name,value):Draft202012Validator({'$defs':G.schema()['$defs'],'$ref':'#/$defs/'+name}).validate(value)
def install(db):
    M.need(not db.in_transaction,'typed_fence_install_transaction')
    expected='CREATE VIEW gf_valid_fence AS SELECT b.* FROM ij_base_gf_valid_fence b JOIN ij_exit x ON x.exit_id=b.exit_id WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id)'
    M.need(M.E.one(db,"SELECT sql FROM sqlite_schema WHERE name='gf_valid_fence'")['sql'].rstrip(';')==expected,'typed_fence_layout_anchor')
    try:db.executescript('BEGIN IMMEDIATE;\n'+(G.HERE/'typed-gate-fence.sql').read_text('utf-8')+'\nCOMMIT;')
    except Exception:
        if db.in_transaction:db.rollback()
        raise
def reference(v,key,digest):return M.E.ref(v[key],'1' if key=='request_id' else v['revision'],v[digest])
def seq(db,sid,direction):return int(db.execute('SELECT coalesce(max(seq),0) FROM ij_frame WHERE session_id=? AND direction=?',(sid,direction)).fetchone()[0])+1
def origin(db,request,row):
    close=M.E.one(db,'SELECT * FROM go_close WHERE close_id=?',(row['close_id'],));ack,_=CE.ack(db,close['close_id'])
    completion=M.E.one(db,'SELECT * FROM pd_close_completion WHERE close_id=?',(close['close_id'],));p=M.E.one(db,'SELECT * FROM pd_closure WHERE closure_id=?',(completion['closure_id'],));closure=M.document(p['body']);N.validate('PreparationClosure',closure)
    M.need(closure==M.sealed(closure,'closure_digest') and closure['closure_id']==row['closure_id']==completion['closure_id'] and closure['closure_digest']==p['closure_digest'] and completion['ack_id']==request['close_ack_ref']['id']==ack['ack_id'],'typed_fence_preparation_original')
    r=M.E.one(db,'SELECT * FROM gf_request WHERE request_id=?',(request['request_id'],));control=S.control(db,r['control_state_id'])
    return M.sealed(dict(format_version='gate-fence-origin/0.1.0-draft.1',request_id=request['request_id'],request_ref=reference(request,'request_id','request_digest'),close_ref=C.source_ref('close_operation',C.columns(close)),close_ack_ref=reference(ack,'ack_id','ack_digest'),preparation_closure_ref=reference(closure,'closure_id','closure_digest'),control_state_ref=S.control_ref(control),safety_revision=str(int(r['safety_revision']))),'origin_digest')
def read_request(db,rid):
    r=M.E.one(db,'SELECT * FROM gf_request WHERE request_id=?',(rid,));frame,f=N.stored_frame(db,r['journal_frame_id']);v=frame['body'];E.validate('GF__Request',v)
    M.need(v==M.sealed(v,'request_digest') and v['request_id']==rid and v['request_digest']==r['request_digest'] and r['body']==r['outbox_body']==r['audit_body']==M.raw(v),'typed_fence_request_body')
    binding=S.binding(db,r['exit_id']);authority=S.control_ref(S.control(db,r['authority_state_id']));previous=None
    if r['previous_gate_id'] is not None:
        g=M.E.one(db,'SELECT * FROM go_gate WHERE gate_id=?',(r['previous_gate_id'],));previous=M.E.ref(g['gate_id'],int(g['record_revision']),g['record_digest'])
    M.need(v['binding']==binding and v['control_authority_ref']==authority and v['before_gate_ref']==previous and v['close_ack_ref']['id']==r['close_ack_id'] and v['gate_token']==r['gate_token'],'typed_fence_request_sources')
    for wire,column in [('target_gate_revision','target_revision'),('selected_tick_ns','selected_tick'),('expires_tick_ns','expires_tick'),('lease_until_tick_ns','lease_until_tick')]:M.need(P.u(v[wire])==r[column],'typed_fence_request_columns')
    M.need(frame==E.frame(binding,'GATE_FENCE',r['message_id'],int(r['outbound_seq']),v) and f['exit_id']==r['exit_id'] and f['direction']=='c2w' and f['domain_kind']=='renewal_request' and f['domain_id']==rid and f['observed_tick']==r['selected_tick'],'typed_fence_request_frame')
    o=M.E.one(db,'SELECT * FROM tf_origin WHERE request_id=?',(rid,));value=M.document(o['body']);validate('FenceOrigin',value)
    M.need(value==origin(db,v,o) and o['digest']==value['origin_digest'] and value['close_ack_ref']==v['close_ack_ref'] and r['original_id']==rid,'typed_fence_origin')
    k=M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(f['frame_id'],));M.need(k['disposition']=='applied' and k['committed_tick']==r['selected_tick'],'typed_fence_request_seal')
    return v,f,r
def queue(db,cid,rid,token,tick,expires,lease,fail_after=None):
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM gf_request WHERE request_id=?',(rid,)).fetchone():
            v,_,_=read_request(db,rid);o=M.E.one(db,'SELECT * FROM tf_origin WHERE request_id=?',(rid,))
            M.need(o['close_id']==cid and v['gate_token']==token and v['expires_tick_ns']==str(int(P.u(expires))) and v['lease_until_tick_ns']==str(int(P.u(lease))),'typed_fence_replay_conflict');return v,writes
        M.need(N.current(db,cid),'typed_fence_close_not_current');ack,_=CE.ack(db,cid);dispatch,original=CE.dispatch(db,cid);binding=dispatch['target']['binding'];device=binding['device_id'];eid=binding['writer_exit_id']
        control=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(device,));authority=M.E.one(db,'SELECT * FROM go_authority WHERE device_id=?',(device,));previous=db.execute('SELECT gate_id FROM go_current_gate WHERE exit_id=?',(eid,)).fetchone();previous=previous[0] if previous else None
        g=M.E.one(db,'SELECT * FROM go_gate WHERE gate_id=?',(previous,)) if previous else None
        if g:
            M.need(g['phase']=='fenced' and g['renewal_id'] is not None,'typed_fence_previous_original')
            M.need(read_gate(db,g['renewal_id'])['gate_id']==g['gate_id'],'typed_fence_previous_original')
        maxrev=max(int(db.execute('SELECT coalesce(max(target_revision),0) FROM gf_request WHERE exit_id=?',(eid,)).fetchone()[0]),int(g['gate_revision']) if g else 0);revision=str(int(P.u(maxrev+1)))
        v=M.sealed(dict(request_id=rid,binding=binding,control_authority_ref=S.control_ref(S.control(db,authority['change_id'])),before_gate_ref=M.E.ref(previous,int(g['record_revision']),g['record_digest']) if g else None,close_ack_ref=reference(ack,'ack_id','ack_digest'),target_gate_revision=revision,gate_token=token,selected_tick_ns=str(int(P.u(tick))),expires_tick_ns=str(int(P.u(expires))),lease_until_tick_ns=str(int(P.u(lease)))),'request_digest');E.validate('GF__Request',v)
        mid=rid+'.frame';frame=E.frame(binding,'GATE_FENCE',mid,seq(db,original['session_id'],'c2w'),v);N.journal(db,frame,original['session_id'],eid,tick,'renewal_request',rid,write)
        write('gf_request',original_id=rid,journal_frame_id=mid,request_id=rid,device_id=device,exit_id=eid,previous_gate_id=previous,authority_state_id=authority['change_id'],control_state_id=control['change_id'],close_ack_id=ack['ack_id'],safety_revision=db.execute('SELECT max(revision) FROM go_hazard WHERE device_id=?',(device,)).fetchone()[0],target_revision=P.u(revision),gate_token=token,message_id=mid,outbound_seq=P.u(frame['seq']),selected_tick=P.u(tick),expires_tick=P.u(expires),lease_until_tick=P.u(lease),request_digest=v['request_digest'],body=M.raw(v),outbox_body=M.raw(v),audit_body=M.raw(v))
        p=M.E.one(db,'SELECT * FROM pd_close_completion WHERE close_id=?',(cid,));o=origin(db,v,dict(close_id=cid,closure_id=p['closure_id']));validate('FenceOrigin',o)
        write('tf_origin',request_id=rid,close_id=cid,closure_id=p['closure_id'],digest=o['origin_digest'],body=M.raw(o));N.seal(write,mid,tick,v);read_request(db,rid);return v,writes
    return N.transaction(db,run)
def begin_write(db,rid,tick):
    def run():
        v,f,r=read_request(db,rid)
        if db.execute('SELECT 1 FROM ij_write_attempt WHERE frame_id=?',(f['frame_id'],)).fetchone():return 'lookup_only'
        body=M.raw(dict(request_ref=reference(v,'request_id','request_digest')));db.execute(*I('ij_write_attempt',frame_id=f['frame_id'],attempt_id=f['frame_id']+'.write',attempted_tick=P.u(tick),encoding_prepare_id=None,current_validation_body=body,audit_body=body));return 'attempt_recorded'
    return N.transaction(db,run)
def accepting(db,rid,tick):
    return db.execute('SELECT 1 FROM gf_context r JOIN tf_current_origin o USING(request_id) JOIN ij_exit x ON x.exit_id=r.exit_id WHERE r.request_id=? AND ?<r.expires_tick AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id)',(rid,P.u(tick))).fetchone() is not None
def read_ack(db,rid):
    request,original,r=read_request(db,rid);a=M.E.one(db,'SELECT * FROM gf_ack WHERE request_id=?',(rid,));frame,f=N.stored_frame(db,a['journal_frame_id']);b=frame['body'];E.validate('GF__Ack',b)
    expected=dict(request_id=rid,request_digest=request['request_digest'],binding=request['binding'],gate_revision=request['target_gate_revision'],gate_token=request['gate_token'],effective_tick_ns=str(int(a['effective_tick'])),state='fenced')
    M.need(b==expected and frame==E.frame(request['binding'],'GATE_FENCE_ACK',a['message_id'],int(a['inbound_seq']),b,r['message_id']) and a['body']==M.raw(b) and a['evidence_digest']==M.F.digest(frame),'typed_fence_ack_body')
    observation=M.document(a['validation_body']);validate('FenceObservation',observation);M.need(observation['frame_ref']==M.E.ref(frame['message_id'],1,M.F.digest(frame)) and observation['received_tick_ns']==str(int(a['received_tick'])) and observation['observer_ref']['id']==a['observer_ref'] and a['audit_body']==a['validation_body'],'typed_fence_ack_observation')
    M.need(a['exit_id']==r['exit_id']==f['exit_id'] and a['reply_to']==r['message_id'] and a['request_digest']==r['request_digest'] and a['gate_revision']==r['target_revision'] and a['gate_token']==r['gate_token'] and f['session_id']==original['session_id'] and f['reply_frame_id']==original['frame_id'] and f['direction']=='w2c' and f['domain_kind']=='renewal_ack' and f['domain_id']==a['ack_id'] and f['observed_tick']==a['received_tick'],'typed_fence_ack_columns')
    w=M.E.one(db,'SELECT * FROM ij_write_attempt WHERE frame_id=?',(original['frame_id'],));M.need(w['attempted_tick']<=a['effective_tick']<=a['received_tick'],'typed_fence_ack_time')
    k=M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(f['frame_id'],));M.need(k['committed_tick']==a['received_tick'] and k['disposition'] in ('applied','historical'),'typed_fence_ack_seal');return frame,f,a,k
def receive(db,rid,wire,tick,observer,fail_after=None):
    def run():
        writes,write=N.writer(db,fail_after);M.need(isinstance(wire,bytes) and 4<len(wire)<=262148 and int.from_bytes(wire[:4],'big')==len(wire)-4,'typed_fence_ack_wire');frame=M.document(wire[4:]);E.FRAME.validate(frame);M.need(M.raw(frame)==wire[4:],'typed_fence_ack_canonical');M.validate('Ref',observer)
        if db.execute('SELECT 1 FROM gf_ack WHERE request_id=?',(rid,)).fetchone():
            old,f,a,_=read_ack(db,rid);M.need(f['wire_body']==wire and M.document(a['validation_body'])['observer_ref']==observer,'typed_fence_ack_replay_conflict');return old,writes
        request,original,r=read_request(db,rid);body=frame['body'];E.validate('GF__Ack',body);aid=rid+'.ack';disposition='applied' if accepting(db,rid,tick) else 'historical'
        M.need(frame['type']=='GATE_FENCE_ACK' and frame['reply_to']==r['message_id'] and body['binding']==request['binding'],'typed_fence_ack_binding')
        observation=dict(frame_ref=M.E.ref(frame['message_id'],1,M.F.digest(frame)),observer_ref=observer,received_tick_ns=str(int(P.u(tick))));validate('FenceObservation',observation)
        N.journal(db,frame,original['session_id'],r['exit_id'],tick,'renewal_ack',aid,write,original['frame_id'])
        write('gf_ack',journal_frame_id=frame['message_id'],ack_id=aid,request_id=rid,exit_id=r['exit_id'],message_id=frame['message_id'],reply_to=frame['reply_to'],inbound_seq=P.u(frame['seq']),request_digest=body['request_digest'],gate_revision=P.u(body['gate_revision']),gate_token=body['gate_token'],effective_tick=P.u(body['effective_tick_ns']),received_tick=P.u(tick),evidence_digest=M.F.digest(frame),observer_ref=observer['id'],body=M.raw(body),validation_body=M.raw(observation),audit_body=M.raw(observation))
        N.seal(write,frame['message_id'],tick,observation,disposition);read_ack(db,rid);return frame,writes
    return N.transaction(db,run)
def current(db,rid):return db.execute('SELECT 1 FROM gf_valid_fence WHERE request_id=?',(rid,)).fetchone() is not None
def read_gate(db,rid):
    request,_,r=read_request(db,rid);frame,_,a,_=read_ack(db,rid);k=M.E.one(db,'SELECT * FROM gf_commit WHERE request_id=?',(rid,));g=M.E.one(db,'SELECT * FROM go_gate WHERE gate_id=?',(k['gate_id'],));v=M.document(g['record_body']);validate('FencedGateRecord',v)
    expected=M.sealed(dict(format_version='fenced-gate-record/0.1.0-draft.1',gate_id=g['gate_id'],revision=str(int(g['record_revision'])),binding=request['binding'],previous_gate_ref=request['before_gate_ref'],request_ref=reference(request,'request_id','request_digest'),ack_frame_ref=M.E.ref(frame['message_id'],1,M.F.digest(frame)),gate_revision=request['target_gate_revision'],gate_token=request['gate_token'],barrier_id=rid,phase='fenced',lease_until_tick_ns=request['lease_until_tick_ns'],committed_tick_ns=str(int(k['committed_tick']))),'record_digest')
    M.need(v==expected and g['record_digest']==v['record_digest'] and g['exit_id']==r['exit_id'] and g['previous_id']==r['previous_gate_id'] and g['renewal_id']==g['barrier_id']==rid and g['control_barrier_id'] is None and g['phase']=='fenced' and g['ready_id'] is None and g['gate_revision']==r['target_revision'] and g['gate_token']==r['gate_token'] and g['lease_until_tick']==r['lease_until_tick'] and k['ack_id']==a['ack_id'] and k['audit_body']==k['outbox_body']==g['record_body'],'typed_fence_gate_original');return v
def adopt(db,rid,tick,fail_after=None):
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM gf_commit WHERE request_id=?',(rid,)).fetchone():return read_gate(db,rid),current(db,rid),writes
        request,_,r=read_request(db,rid);frame,_,a,k=read_ack(db,rid);M.need(k['disposition']=='applied' and accepting(db,rid,tick),'typed_fence_not_current')
        previous=M.E.one(db,'SELECT * FROM go_gate WHERE gate_id=?',(r['previous_gate_id'],)) if r['previous_gate_id'] else None
        revision=str(int(P.u(int(previous['record_revision'])+1 if previous else 1)));gid=rid+'.gate'
        v=M.sealed(dict(format_version='fenced-gate-record/0.1.0-draft.1',gate_id=gid,revision=revision,binding=request['binding'],previous_gate_ref=request['before_gate_ref'],request_ref=reference(request,'request_id','request_digest'),ack_frame_ref=M.E.ref(frame['message_id'],1,M.F.digest(frame)),gate_revision=request['target_gate_revision'],gate_token=request['gate_token'],barrier_id=rid,phase='fenced',lease_until_tick_ns=request['lease_until_tick_ns'],committed_tick_ns=str(int(P.u(tick)))),'record_digest');validate('FencedGateRecord',v)
        write('go_gate',gate_id=gid,exit_id=r['exit_id'],previous_id=r['previous_gate_id'],record_revision=P.u(revision),gate_revision=r['target_revision'],gate_token=r['gate_token'],barrier_id=rid,control_barrier_id=None,renewal_id=rid,phase='fenced',ready_id=None,lease_until_tick=r['lease_until_tick'],record_digest=v['record_digest'],record_body=M.raw(v))
        write('gf_commit',request_id=rid,ack_id=a['ack_id'],gate_id=gid,committed_tick=P.u(tick),audit_body=M.raw(v),outbox_body=M.raw(v));read_gate(db,rid);M.need(current(db,rid),'typed_fence_not_current');return v,True,writes
    return N.transaction(db,run)
