"""完整普通编码帧到SQL原件的参考适配；可信外部提供者仍为调用方责任。"""
import copy,hashlib,json
from jsonschema import Draft202012Validator
import typed_gate_path_model as O
import build_typed_encoding_path as G

I=O.I;u=O.u;raw=O.raw;digest=O.digest;B=O.B;need=O.A.F.need
SCHEMA=json.loads((G.HERE/'continuation-binding-ipc.schema.json').read_bytes())
EVIDENCE_SCHEMA=json.loads((G.HERE.parent/'c08-controller/encoding-authority.schema.json').read_bytes())
FRAME=Draft202012Validator(SCHEMA)
def validate(name,v):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name}).validate(v)
def ref(name):return dict(id=name,revision='1',digest=digest(name))
def seal(v,key):v=copy.deepcopy(v);v[key]=digest({k:x for k,x in v.items() if k!=key});return v
def byte_digest(v):return 'sha256:'+hashlib.sha256(v).hexdigest()
def content_ref(v):return dict(object_id=v['id'],digest=v['digest'])
def one(db,sql,args=()):return O.one(db,sql,args)

def source(db,command,attempt,exit_id):
    need(db.in_transaction,'encoding_transaction_required')
    initial=one(db,'SELECT * FROM ca_command_initial WHERE command_id=?',(command,))
    request=one(db,'SELECT * FROM ca_request_key WHERE key_id=?',(initial['key_id'],));ns=one(db,'SELECT * FROM ca_namespace WHERE namespace_id=?',(request['namespace_id'],))
    ex=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(exit_id,));cmd=one(db,'SELECT * FROM ce_command WHERE command_id=?',(command,))
    attempt_row=one(db,'SELECT * FROM ce_attempt WHERE attempt_id=?',(attempt,))
    need(cmd['device_id']==ex['device_id'] and attempt_row['command_id']==command,'encoding_target')
    need(bool(db.execute('SELECT 1 FROM cn_live_command WHERE command_id=?',(command,)).fetchone()),'encoding_origin')
    need(not db.execute('SELECT 1 FROM ca_namespace_closure WHERE namespace_id=?',(ns['namespace_id'],)).fetchone(),'encoding_namespace_closed')
    session=one(db,'SELECT s.* FROM ij_session s JOIN ij_exit e USING(session_id) WHERE e.exit_id=?',(exit_id,))
    need(session['protocol_version']=='ipc/0.14.0-continuation-draft.1','encoding_ipc_version')
    need(not db.execute('SELECT 1 FROM ij_end WHERE session_id=?',(session['session_id'],)).fetchone(),'encoding_session_ended')
    binding=dict(scope=O.A.scope(db),writer_exit_id=exit_id,**{k:ex[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','device_session_id','clock_domain_id','descriptor_digest')})
    validate('EA__Binding',binding)
    return dict(initial=initial,key=request,namespace=ns,exit=ex,command=cmd,session=session,binding=binding)

def authorize(db,command,attempt,exit_id,provider,pid='prepare_typed',now=30):
    s=source(db,command,attempt,exit_id)
    need(all(provider.get(k) is True for k in ('authorized','capability_verified','parameters_verified','time_verified','reservation_verified','current_transport_verified')),'encoding_provider')
    need(provider['binding']==s['binding'],'encoding_provider_binding')
    initial=s['initial'];request=s['key'];ns=s['namespace']
    a=dict(format_version='encoding-authorization/0.1.0-draft.1',authorization_id=pid+'.authorization',revision='1',binding=s['binding'],
        target=dict(kind='ordinary',command_ref=dict(id=command,revision='1',digest=initial['command_digest']),proposed_attempt_id=attempt,cancellation_ref=None,execution_ref=None),
        requester=dict(kind='service',**{k:ns[k] for k in ('issuer_id','issuer_epoch','principal_id')}),
        admission_source_ref=dict(id=command,revision='1',digest=initial['command_digest']),content_digest=request['request_digest'],primitive_id=provider['primitive_id'],
        **{k:provider[k] for k in ('authorization_snapshot_ref','capability_ref','primitive_plan_ref','transport_profile_ref','encoding_reservation_ref','max_bytes')},created_tick_ns=str(now),expires_tick_ns=provider['expires_tick_ns'])
    a=seal(a,'authorization_digest');validate('EA__EncodingAuthorization',a);need(now<int(a['expires_tick_ns']),'encoding_expired')
    r=a['encoding_reservation_ref'];state=one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(s['exit']['device_id'],));cmd=s['command']
    sequence=int(db.execute('SELECT coalesce(max(sequence),?) FROM pd_registration',(u('0'),)).fetchone()[0])+1
    rows=[I('ep_request',prepare_id=pid,scope_id=1,kind='ordinary',command_id=command,proposed_attempt_id=attempt,cancellation_id=None,cancel_prepare_id=None,
        namespace_id=ns['namespace_id'],request_digest=request['request_digest'],**{k:ns[k] for k in ('issuer_id','issuer_epoch','principal_id')},exit_id=exit_id,primitive_id=a['primitive_id'],
        reservation_id=r['id'],reservation_revision=u(r['revision']),reservation_digest=r['digest'],authorization_id=a['authorization_id'],authorization_digest=a['authorization_digest'],authorization_body=raw(a),
        request_message_id=pid+'.request',max_bytes=a['max_bytes'],created_tick=u(str(now)),expires_tick=u(a['expires_tick_ns'])),
        I('pd_registration',prepare_id=pid,sequence=u(str(sequence)),origin=cmd['origin'],prep_key=cmd['prep_key'],receipt_id=cmd['receipt_id'],control_epoch=state['control_epoch'],effective_version=state['effective_version'],provenance_body=B),
        I('ep_request_commit',prepare_id=pid,committed_tick=u(str(now)),validation_body=raw(provider),audit_body=B,outbox_id=pid+'.request',outbox_body=raw({'prepare_id':pid}))]
    return a,rows

def frame(binding,typ,message,seq,body,reply=None):
    f=dict(ipc_version='ipc/0.14.0-continuation-draft.1',type=typ,message_id=message,reply_to=reply,seq=str(seq),body=body,journal_mode='durable',
        **{k:binding[k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id','clock_domain_id','descriptor_digest')})
    FRAME.validate(f);return f

def journal(s,f,kind,oid,tick,reply=None):
    wire=raw(f);framed=len(wire).to_bytes(4,'big')+wire
    return I('ij_frame',frame_id=f['message_id'],session_id=s['session']['session_id'],exit_id=s['exit']['exit_id'],device_id=f['device_id'],direction='w2c' if reply else 'c2w',message_type=f['type'],
        message_id=f['message_id'],seq=u(f['seq']),reply_frame_id=reply,reply_to=f['reply_to'],frame_digest=digest(f),wire_digest=byte_digest(framed),frame_body=wire,body_body=raw(f['body']),
        wire_body=framed,wire_length=len(framed),observed_tick=u(str(tick)),domain_kind=kind,domain_id=oid,validation_body=B)

def commit(mid,tick,disposition='applied'):return I('ij_commit',frame_id=mid,disposition=disposition,committed_tick=u(str(tick)),audit_body=B,effect_body=B)

def encoding(db,pid,now=31):
    r=one(db,'SELECT * FROM ep_open_request WHERE prepare_id=?',(pid,));s=source(db,r['command_id'],r['proposed_attempt_id'],r['exit_id']);a=json.loads(r['authorization_body'])
    request=json.loads(s['key']['transport_body']);validate('EA__EncodingAuthorization',a)
    body=dict(prepare_id=pid,command_id=r['command_id'],attempt_id=r['proposed_attempt_id'],primitive_id=a['primitive_id'],device_session_id=s['binding']['device_session_id'],request=request,
        primitive_plan_ref=content_ref(a['primitive_plan_ref']),transport_profile_ref=content_ref(a['transport_profile_ref']),expires_tick_ns=a['expires_tick_ns'],encoding_authorization=a)
    seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='c2w'",(s['session']['session_id'],)).fetchone()[0])+1
    f=frame(s['binding'],'ENCODE_PACKET',r['request_message_id'],seq,body)
    return f,[journal(s,f,'encoding_request',pid,now),I('ij_encoding_frame',prepare_id=pid,journal_frame_id=f['message_id'],request_seq=u(f['seq']),request_frame_digest=digest(f),request_frame=raw(f)),commit(f['message_id'],now)]

def send(db,pid,now=32):
    r=one(db,'SELECT * FROM ep_open_request WHERE prepare_id=?',(pid,));source(db,r['command_id'],r['proposed_attempt_id'],r['exit_id'])
    f=one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(r['request_message_id'],));mid=f['frame_id'];aid=pid+'.send'
    return [I('ep_send_attempt',prepare_id=pid,journal_frame_id=mid,attempt_id=aid,attempted_tick=u(str(now)),request_frame_digest=f['frame_digest'],attempt_body=B),
        I('ij_write_attempt',frame_id=mid,attempt_id=aid,attempted_tick=u(str(now)),encoding_prepare_id=pid,current_validation_body=B,audit_body=B)]

def written(db,pid,now=32):
    f=one(db,'SELECT f.* FROM ij_frame f JOIN ij_encoding_frame e ON e.journal_frame_id=f.frame_id WHERE e.prepare_id=?',(pid,))
    return [I('ij_write_result',frame_id=f['frame_id'],state='written',completed_tick=u(str(now)),written_bytes=f['wire_length'],end_id=None,result_body=B)]

def response(request,provider,seq=4,data=b'\x01\x02'):
    a=request['body']['encoding_authorization'];b=a['binding'];pid=request['body']['prepare_id'];sha=byte_digest(data)
    p=seal(dict(packet_id=pid+'_packet',command_id=a['target']['command_ref']['id'],attempt_id=a['target']['proposed_attempt_id'],primitive_id=a['primitive_id'],writer_exit_id=b['writer_exit_id'],
        device_session_id=b['device_session_id'],socket_instance_id=provider['socket_instance_id'],protocol_session=provider['protocol_session'],wire_packet_id='1',tracking_ids=[],
        immutable_bytes_ref=dict(object_id=pid+'_bytes',digest=sha),byte_length=len(data),sha256=sha,transport_profile_ref=content_ref(a['transport_profile_ref']),primitive_plan_ref=content_ref(a['primitive_plan_ref'])),'packet_digest')
    return frame(b,'PREPARE_PACKET',pid+'.response',seq,dict(prepare_id=pid,packet=p,bytes_hex=data.hex(),encoding_authorization_ref=dict(id=a['authorization_id'],revision=a['revision'],digest=a['authorization_digest'])),request['message_id'])

def receive(db,pid,f,provider,now=33):
    need(db.in_transaction,'encoding_transaction_required');FRAME.validate(f)
    r=one(db,'SELECT * FROM ep_open_request WHERE prepare_id=?',(pid,));s=source(db,r['command_id'],r['proposed_attempt_id'],r['exit_id'])
    a=json.loads(r['authorization_body']);validate('EA__EncodingAuthorization',a);need(a==seal(a,'authorization_digest'),'encoding_authorization_digest')
    original=one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(r['request_message_id'],));request=json.loads(original['frame_body']);FRAME.validate(request)
    need(request['body']['encoding_authorization']==a and digest(request)==original['frame_digest'],'encoding_request_original')
    need(request['body']['request']==json.loads(s['key']['transport_body']),'encoding_command_original')
    content={k:v for k,v in request['body']['request'].items() if k not in ('context_id','idempotency_key','correlation_id')}
    need(digest(content)==r['request_digest']==a['content_digest'],'encoding_content_digest')
    need(all(provider.get(k) is True for k in ('authorized','capability_verified','parameters_verified','time_verified','reservation_verified','current_transport_verified')),'encoding_provider')
    need(provider['binding']==a['binding']==s['binding'],'encoding_provider_binding')
    need(all(provider[k]==a[k] for k in ('authorization_snapshot_ref','capability_ref','primitive_plan_ref','transport_profile_ref','encoding_reservation_ref','primitive_id','max_bytes','expires_tick_ns')),'encoding_source_changed')
    need(int(a['created_tick_ns'])<=int(original['observed_tick'])<=now<int(a['expires_tick_ns']),'encoding_expired')
    body=f['body'];p=body['packet'];data=bytes.fromhex(body['bytes_hex'])
    need(f['type']=='PREPARE_PACKET' and f['reply_to']==request['message_id'] and body['prepare_id']==pid,'encoding_reply')
    need(all(f[k]==a['binding'][k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id','clock_domain_id','descriptor_digest')),'encoding_response_exit')
    need(body['encoding_authorization_ref']==dict(id=a['authorization_id'],revision=a['revision'],digest=a['authorization_digest']),'encoding_reply_authorization')
    need(p==seal(p,'packet_digest') and p['sha256']==byte_digest(data)==p['immutable_bytes_ref']['digest'] and len(data)==p['byte_length']<=a['max_bytes'],'encoding_packet_bytes')
    need((p['command_id'],p['attempt_id'],p['primitive_id'],p['writer_exit_id'],p['device_session_id'])==(r['command_id'],r['proposed_attempt_id'],r['primitive_id'],r['exit_id'],s['exit']['device_session_id']),'encoding_packet_target')
    need(p['transport_profile_ref']==content_ref(a['transport_profile_ref']) and p['primitive_plan_ref']==content_ref(a['primitive_plan_ref']),'encoding_packet_profile')
    need(p['socket_instance_id']==provider['socket_instance_id'] and p['protocol_session']==provider['protocol_session'],'encoding_packet_session')
    e=seal(dict(evidence_id=pid+'.evidence',revision='1',authorization_ref=body['encoding_authorization_ref'],binding=a['binding'],prepare_id=pid,request_message_id=request['message_id'],response_message_id=f['message_id'],
        request_digest=digest(request),response_digest=digest(f),packet_ref={k:p[k] for k in ('packet_id','packet_digest')},bytes_digest=p['sha256'],byte_length=p['byte_length'],received_tick_ns=str(now)),'evidence_digest')
    Draft202012Validator({'$defs':EVIDENCE_SCHEMA['$defs'],'$ref':'#/$defs/EncodingEvidence'}).validate(e)
    return [journal(s,f,'encoding_reply',pid,now,request['message_id']),I('ep_reply',prepare_id=pid,journal_frame_id=f['message_id'],exit_id=r['exit_id'],response_message_id=f['message_id'],response_seq=u(f['seq']),reply_to=f['reply_to'],
        authorization_id=a['authorization_id'],authorization_digest=a['authorization_digest'],response_frame_digest=digest(f),response_frame=raw(f),outcome='prepared',packet_id=p['packet_id'],packet_digest=p['packet_digest'],bytes_digest=p['sha256'],packet_bytes=data,
        packet_body=raw(p),evidence_id=e['evidence_id'],evidence_digest=e['evidence_digest'],evidence_body=raw(e),received_tick=u(str(now))),
        I('ep_receive_commit',prepare_id=pid,disposition='prepared',committed_tick=u(str(now)),validation_body=raw(provider),audit_body=B),commit(f['message_id'],now),
        I('ce_packet',packet_id=p['packet_id'],attempt_id=p['attempt_id'],exit_id=r['exit_id'],primitive_id=p['primitive_id'],packet_body=raw(p))]

def transaction(db,builder,fail_after=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        value,rows=builder()
        for n,(sql,args) in enumerate(rows):
            db.execute(sql,args)
            if n==fail_after:raise RuntimeError('injected')
        db.commit();return value
    except BaseException:
        if db.in_transaction:db.rollback()
        raise
