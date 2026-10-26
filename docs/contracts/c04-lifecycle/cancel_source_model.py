"""核对完整取消受理与两阶段切点原件；不证明提供者真实性或授予OPEN权限。"""
import hashlib
from jsonschema import Draft202012Validator
import command_deny_model as D
import build_cancel_source as G
M=D.M;N=D.N;P=D.P;I=D.R.I;need=M.need;one=M.E.one;rows=D.R.O.rows;raw=M.raw;digest=M.F.digest
SCHEMA=G.schema();EXIT_FIELDS=('controller_boot_id','worker_boot_id','ipc_session_id','device_id','device_session_id','clock_domain_id','descriptor_digest')
def validate(name,value):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name}).validate(value)
def reference(ident,sha,revision='1'):return dict(id=ident,revision=revision,digest=sha)
def decode(name,body,key=None,expected=None):
    need(isinstance(body,bytes) and 0<len(body)<=16777216,'cancel_source_body_capacity');v=M.document(body);validate(name,v)
    need(raw(v)==body,'cancel_source_canonical')
    if key:need(v==M.sealed(v,key) and (expected is None or v[key]==expected),'cancel_source_digest')
    return v
def install(db):
    need(not db.in_transaction and db.execute('PRAGMA foreign_keys').fetchone()[0]==1 and db.execute('PRAGMA recursive_triggers').fetchone()[0]==1,'cancel_source_install')
    need(db.execute("SELECT 1 FROM sqlite_schema WHERE name='cd_event'").fetchone() is not None,'cancel_source_frontier_required')
    extra="CREATE TRIGGER cs_socket_prepare_guard BEFORE INSERT ON cs_socket WHEN EXISTS(SELECT 1 FROM ep_request WHERE exit_id=NEW.exit_id) BEGIN SELECT RAISE(ABORT,'cancel_socket_registered_too_late'); END;" if db.execute("SELECT 1 FROM sqlite_schema WHERE name='ep_request'").fetchone() else ''
    try:
        db.executescript('BEGIN IMMEDIATE;\n'+(G.HERE/'cancel_source.sql').read_text('utf-8')+'\n'+extra+'\nCOMMIT;')
    except Exception:
        if db.in_transaction:db.rollback()
        raise
def socket(db,eid):
    need(db.in_transaction,'cancel_source_transaction_required');r=one(db,'SELECT * FROM cs_socket WHERE exit_id=?',(eid,));v=decode('SocketRegistration',r['body'],'registration_digest',r['registration_digest'])
    e=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,));b=v['exit']
    need(v['scope']==M.E.A.scope(db) and b['writer_exit_id']==eid and b['socket_instance_id']==r['socket_instance_id'] and r['audit_body']==r['body'] and all(b[k]==e[k] for k in EXIT_FIELDS),'cancel_socket_columns');return b
def register_socket(db,eid,sid,observer,fail_after=None):
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM cs_socket WHERE exit_id=?',(eid,)).fetchone():
            b=socket(db,eid);r=one(db,'SELECT body FROM cs_socket WHERE exit_id=?',(eid,))
            need(b['socket_instance_id']==sid and M.document(r['body'])['observer_ref']==observer,'cancel_socket_replay_conflict');return b,writes
        e=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,));b=dict(writer_exit_id=eid,socket_instance_id=sid,**{k:e[k] for k in EXIT_FIELDS})
        v=M.sealed(dict(format_version='cancel-socket-registration/0.1.0-draft.1',scope=M.E.A.scope(db),exit=b,observer_ref=observer),'registration_digest');validate('SocketRegistration',v)
        write('cs_socket',exit_id=eid,socket_instance_id=sid,registration_digest=v['registration_digest'],body=raw(v),audit_body=raw(v));need(socket(db,eid)==b,'cancel_socket_readback');return b,writes
    return N.transaction(db,run)
def state(db,command,revision):
    r=one(db,'SELECT s.* FROM cm_revision s JOIN cm_commit k USING(command_id,revision) WHERE s.command_id=? AND s.revision=?',(command,revision))
    v=decode('CommandState',r['state_body']);need(digest(v)==r['state_digest'] and v['scope']==M.E.A.scope(db) and v['command_id']==command and v['revision']==str(int(revision)),'cancel_state_original')
    for key in ('phase','outcome','effect_status','resource_status'):need(v[key]==r[key],'cancel_state_columns')
    need((v['automation_continuation']=='paused_latched')==bool(r['paused_latched']) and v['terminal_revision']==(str(int(r['terminal_revision'])) if r['terminal_revision'] else None) and v['attempt_ids']==[x['attempt_id'] for x in rows(db,'SELECT a.attempt_id FROM cm_revision_attempt r JOIN cm_attempt a USING(attempt_id) WHERE r.command_id=? AND r.revision=? ORDER BY a.ordinal',(command,revision))],'cancel_state_members');return v
def admission(db,cid):
    need(db.in_transaction,'cancel_source_transaction_required');c=one(db,'SELECT c.* FROM cv_cancel c JOIN cv_cancel_commit k USING(cancellation_id) WHERE cancellation_id=?',(cid,))
    k=one(db,'SELECT * FROM cv_cancel_key WHERE key_id=?',(c['key_id'],));ns=one(db,'SELECT * FROM ca_namespace WHERE namespace_id=?',(k['namespace_id'],));scope=M.E.A.scope(db)
    key=dict(target_scope=scope,**{x:ns[x] for x in ('issuer_id','issuer_epoch','principal_id','request_epoch')},operation_id=k['operation_id'],idempotency_key=k['idempotency_key'])
    content=decode('CancelContent',k['content_body']);identity=dict(key=key,request_digest=k['request_digest']);validate('S8__CancelIdentity',identity)
    before=state(db,c['command_id'],c['accepted_revision']);expected=reference(c['command_id'],digest(before),before['revision'])
    need(content['scope']==scope and content['command_id']==c['command_id'] and content['expected_state_ref']==expected and digest(content)==k['request_digest'] and c['accepted_state_digest']==expected['digest'],'cancel_content_original')
    r=one(db,'SELECT * FROM cv_cancel_revision WHERE cancellation_id=? AND revision=?',(cid,P.u(1)));op=decode('CancelOperation',r['operation_body'],'operation_digest',r['operation_digest']);after=state(db,c['command_id'],r['state_revision'])
    need(op['cancellation_id']==cid and op['scope']==scope and op['command_id']==c['command_id'] and op['identity']==identity and op['revision']=='1' and op['mode']==c['mode'] and op['state']==r['state']=='requested' and op['future_writes']==r['future_writes']=='pending' and op['command_state_ref']==reference(c['command_id'],digest(after),after['revision']) and op['evidence_refs']==[] and op['reason_code'] is None,'cancel_initial_operation')
    rr=one(db,'SELECT * FROM cv_cancel_receipt WHERE cancellation_id=?',(cid,));receipt=decode('CancelReceipt',rr['receipt_body'],'receipt_digest',rr['receipt_digest'])
    opref=reference(cid,op['operation_digest']);need(receipt==M.sealed(dict(identity=identity,command_id=c['command_id'],scope=scope,cancellation_id=cid,initial_operation_ref=opref,accepted_state_ref=expected),'receipt_digest') and rr['initial_operation_digest']==opref['digest'],'cancel_receipt_original')
    policy=decode('CancelPolicy',c['policy_body'],'policy_digest');need(policy['mode']==c['mode'] and policy['resource_keys']==sorted(set(policy['resource_keys'])),'cancel_policy_original')
    binding=dict(scope=scope,cancellation_id=cid,parent_command_id=c['command_id'],initial_operation_ref=opref,identity=identity,mode=c['mode'],policy_ref=reference(policy['policy_id'],policy['policy_digest'],policy['revision']));validate('S8__CancellationBinding',binding)
    return binding,c
def ordinary(db,pid,command,exit):
    p=one(db,'SELECT * FROM ce_permit WHERE permit_id=?',(pid,));k=one(db,'SELECT * FROM ce_transmission_commit WHERE permit_id=?',(pid,));v=decode('TransmissionPermit',p['permit_body']);t=v['transmission'];i=t['intent'];validate('S8__TransmissionRef',t)
    need(v['permit_id']==i['permit_id']==pid and v['command_id']==i['command_id']==command and v['attempt_id']==i['attempt_id']==p['attempt_id'] and t['issued_revision']==str(int(p['issued_revision'])) and t['ordinal']==str(p['ordinal']) and t['kind']==p['kind'] and t['packet_ref']['packet_id']==p['packet_id'] and p['exit_id']==exit['writer_exit_id'],'cancel_ordinary_columns')
    intent=M.document(k['dispatch_intent_body']);need(raw(intent)==k['dispatch_intent_body'] and all(intent.get(n)==x for n,x in i.items()) and all(i[n]==exit[n] for n in EXIT_FIELDS),'cancel_ordinary_intent')
    need(all(v[n]==i[n] for n in set(v)&set(i)) and v['origin']==one(db,'SELECT origin FROM ce_command WHERE command_id=?',(command,))['origin'] and all(t['send_window'][n]==exit[n] for n in ('clock_domain_id','descriptor_digest')),'cancel_ordinary_permit_binding')
    packet=one(db,'SELECT * FROM ce_packet WHERE packet_id=?',(p['packet_id'],));body=decode('S9__TransportPacket',packet['packet_body'],'packet_digest',t['packet_ref']['packet_digest'])
    need(body['socket_instance_id']==exit['socket_instance_id'] and body['writer_exit_id']==p['exit_id'] and body['device_session_id']==exit['device_session_id'] and body['command_id']==command and body['packet_id']==p['packet_id'] and body['attempt_id']==p['attempt_id'] and body['primitive_id']==packet['primitive_id']==t['primitive_id'] and body['immutable_bytes_ref']['digest']==body['sha256'],'cancel_ordinary_packet')
    initial=p if p['ordinal']==0 else one(db,'SELECT * FROM ce_permit WHERE permit_id=?',(p['parent_permit_id'],))
    need(initial['ordinal']==0 and initial['packet_id']==p['packet_id'] and t['initial_permit_id']==initial['permit_id'],'cancel_ordinary_parent');return t
def cancellation_tx(db,pid,cid,command,exit):
    r=one(db,'SELECT * FROM ci_cancel_transmission WHERE permit_id=?',(pid,));k=one(db,'SELECT * FROM ci_cancel_commit WHERE permit_id=?',(pid,));v=decode('S8__Transmission',r['transmission_body'])
    need(v['permit_id']==pid and v['cancellation_id']==r['cancellation_id']==cid and v['parent_command_id']==command and v['exit']==exit and r['exit_id']==exit['writer_exit_id'] and v['issued_revision']==str(int(r['issued_revision'])) and v['ordinal']==str(r['ordinal']) and v['execution_ref']==reference(r['execution_id'],r['execution_digest']) and v['primitive_id']==r['primitive_id'] and v['packet_ref']==dict(packet_id=r['packet_id'],packet_digest=r['packet_digest']) and k['dispatch_intent_body']==r['transmission_body'],'cancel_transmission_columns')
    need(v['initial_permit_id']==(pid if r['ordinal']==0 else r['initial_permit_id']),'cancel_transmission_parent')
    need(v['kind']==('initial' if r['ordinal']==0 else 'protocol_resend') and v['requester']['origin']==r['origin'],'cancel_transmission_origin')
    need(all(v['send_window'][n]==exit[n] for n in ('clock_domain_id','descriptor_digest')),'cancel_transmission_clock')
    p=one(db,'SELECT p.* FROM cc_dispatch d JOIN cc_packet p USING(packet_id) WHERE d.permit_id=?',(pid,));prep=one(db,'SELECT * FROM cc_prepare WHERE prepare_id=?',(p['prepare_id'],))
    need(p['packet_id']==r['packet_id'] and p['packet_digest']==r['packet_digest'] and prep['cancellation_id']==cid and prep['exit_id']==r['exit_id'] and prep['execution_id']==r['execution_id'] and prep['execution_digest']==r['execution_digest'],'cancel_transmission_prepare')
    packet=decode('S8__Packet',p['packet_body'],'packet_digest',p['packet_digest'])
    need(packet['exit']==exit and packet['execution_ref']==v['execution_ref'] and packet['cancellation_id']==cid and packet['parent_command_id']==command and packet['primitive_id']==v['primitive_id'] and packet['packet_id']==r['packet_id'] and p['packet_bytes']==k['packet_bytes'] and len(p['packet_bytes'])==packet['byte_length'] and packet['sha256']==packet['immutable_bytes_ref']['digest']=='sha256:'+hashlib.sha256(p['packet_bytes']).hexdigest(),'cancel_transmission_packet');return v
def expected(db,cid,cut_id,stage,issued,previous=None,stored=False):
    binding,c=admission(db,cid);device=one(db,'SELECT device_id FROM ce_command WHERE command_id=?',(c['command_id'],))['device_id']
    attempts=[r['attempt_id'] for r in rows(db,'SELECT attempt_id FROM cv_cancel_attempt WHERE cancellation_id=? ORDER BY attempt_id',(cid,))]
    for aid in attempts:need(one(db,'SELECT command_id FROM ce_attempt WHERE attempt_id=?',(aid,))['command_id']==c['command_id'],'cancel_attempt_owner')
    if stored:
        exits=[r['exit_id'] for r in rows(db,'SELECT exit_id FROM cc_target WHERE cut_id=? ORDER BY exit_id',(cut_id,))]
    else:
        exits=[r['exit_id'] for r in rows(db,'SELECT exit_id FROM cv_cancel_target WHERE cancellation_id=? UNION SELECT exit_id FROM ce_exit WHERE device_id=? AND ?=\'all\' ORDER BY exit_id',(cid,device,stage))]
    targets=[]
    for eid in exits:
        ex=socket(db,eid);need(ex['device_id']==device,'cancel_target_device')
        ps=rows(db,'SELECT p.* FROM cv_cancel_permit s JOIN ce_permit p USING(permit_id) WHERE s.cancellation_id=? AND p.exit_id=? ORDER BY p.permit_id',(cid,eid))
        ts=rows(db,'SELECT * FROM ci_cancel_transmission WHERE cancellation_id=? AND exit_id=? AND issued_revision<=? ORDER BY permit_id',(cid,eid,P.u(issued))) if stage=='all' else []
        preps=[r['prepare_id'] for r in rows(db,('SELECT prepare_id FROM cc_cut_prepare WHERE cut_id=? AND exit_id=? ORDER BY prepare_id' if stored else 'SELECT prepare_id FROM cc_prepare WHERE cancellation_id=? AND exit_id=? ORDER BY prepare_id'),(cut_id if stored else cid,eid))] if stage=='all' else []
        for pid in preps:
            p=one(db,'SELECT * FROM cc_prepare WHERE prepare_id=?',(pid,));need(p['cancellation_id']==cid and p['exit_id']==eid,'cancel_prepare_owner')
        target=M.sealed(dict(exit=ex,ordinary_attempt_ids=attempts,ordinary_transmissions=[ordinary(db,p['permit_id'],c['command_id'],ex) for p in ps],cancel_prepare_ids=preps,cancel_transmissions=[cancellation_tx(db,t['permit_id'],cid,c['command_id'],ex) for t in ts]),'target_digest');targets.append(target)
    body=M.sealed(dict(cut_id=cut_id,binding=binding,stage=stage,previous_cut_ref=reference(previous['cut_id'],previous['cut_digest']) if previous else None,issued_revision=issued,deny_revision='2' if stage=='all' else '1',targets=targets),'cut_digest');validate('CancelCut',body)
    transmission_ids=[p['transmission_id'] for t in targets for p in t['ordinary_transmissions']+t['cancel_transmissions']];need(len(transmission_ids)==len(set(transmission_ids)),'cancel_cut_transmission_identity')
    if previous:
        for old in previous['targets']:
            new=next((t for t in targets if t['exit']==old['exit']),None);need(new is not None and all(new[k]==old[k] for k in ('ordinary_attempt_ids','ordinary_transmissions')),'cancel_cut_predecessor')
    return body
def read_cut(db,cut_id):
    need(db.in_transaction,'cancel_source_transaction_required');r=one(db,'SELECT c.* FROM cc_cut c JOIN cc_cut_commit k USING(cut_id) WHERE cut_id=?',(cut_id,))
    body=decode('CancelCut',r['cut_body'],'cut_digest',r['cut_digest']);previous=read_cut(db,r['previous_cut_id']) if r['stage']=='all' else None
    need(body==expected(db,r['cancellation_id'],cut_id,r['stage'],str(int(r['issued_revision'])),previous,True),'cancel_cut_source')
    c=one(db,'SELECT * FROM cv_cancel WHERE cancellation_id=?',(r['cancellation_id'],))
    if r['stage']=='ordinary':need(c['cut_body']==r['cut_body'] and c['cut_digest']==r['cut_digest'] and c['cut_revision']==r['issued_revision'],'cancel_ordinary_admission_cut')
    e=one(db,'SELECT * FROM cd_event WHERE cut_id=?',(cut_id,));need(str(int(e['deny_revision']))==body['deny_revision'] and e['event_kind']==body['stage'],'cancel_cut_deny_revision')
    for target in body['targets']:
        t=one(db,'SELECT * FROM cc_target WHERE cut_id=? AND exit_id=?',(cut_id,target['exit']['writer_exit_id'],));need(raw(target)==t['target_body'] and target['target_digest']==t['target_digest'],'cancel_target_original')
    expected_members=sorted((t['exit']['writer_exit_id'],p['intent']['permit_id']) for t in body['targets'] for p in t['ordinary_transmissions'])+sorted((t['exit']['writer_exit_id'],p['permit_id']) for t in body['targets'] for p in t['cancel_transmissions'])
    actual=sorted((m['exit_id'],m['permit_id']) for m in rows(db,'SELECT * FROM cc_member WHERE cut_id=?',(cut_id,)));need(sorted(expected_members)==actual,'cancel_cut_members')
    k=one(db,'SELECT * FROM cc_cut_commit WHERE cut_id=?',(cut_id,));need(k['audit_body']==k['outbox_body']==r['cut_body'],'cancel_cut_seal');return body
def capture(db,cid,cut_id,stage,fail_after=None):
    need(stage in ('ordinary','all'),'cancel_cut_stage')
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM cc_cut WHERE cut_id=?',(cut_id,)).fetchone():
            old=read_cut(db,cut_id);need(old['stage']==stage and old['binding']['cancellation_id']==cid,'cancel_cut_replay_conflict');return old,writes
        c=one(db,'SELECT * FROM cv_cancel WHERE cancellation_id=?',(cid,));previous=None
        if stage=='all':previous=read_cut(db,one(db,"SELECT cut_id FROM cc_cut WHERE cancellation_id=? AND stage='ordinary'",(cid,))['cut_id'])
        issued=str(int(c['cut_revision'])) if stage=='ordinary' else str(int(db.execute("SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue").fetchone()[0]))
        body=expected(db,cid,cut_id,stage,issued,previous)
        if stage=='ordinary':need(raw(body)==c['cut_body'] and body['cut_digest']==c['cut_digest'],'cancel_ordinary_admission_cut')
        write('cc_cut',cut_id=cut_id,cancellation_id=cid,stage=stage,previous_cut_id=previous['cut_id'] if previous else None,issued_revision=P.u(issued),cut_digest=body['cut_digest'],cut_body=raw(body))
        for t in body['targets']:
            eid=t['exit']['writer_exit_id'];write('cc_target',cut_id=cut_id,exit_id=eid,target_digest=t['target_digest'],target_body=raw(t))
            for pid in [p['intent']['permit_id'] for p in t['ordinary_transmissions']]+[p['permit_id'] for p in t['cancel_transmissions']]:
                fact=db.execute('SELECT disposition FROM ce_current_disposition WHERE permit_id=? UNION ALL SELECT disposition FROM cf_disposition WHERE permit_id=?',(pid,pid)).fetchone()
                write('cc_member',cut_id=cut_id,exit_id=eid,permit_id=pid,entered_known=int(fact is not None and fact[0]=='in_flight'))
            for pid in t['cancel_prepare_ids']:write('cc_cut_prepare',cut_id=cut_id,exit_id=eid,prepare_id=pid)
        write('cc_cut_commit',cut_id=cut_id,validation_body=raw(body),audit_body=raw(body),outbox_id=cut_id+'.event',outbox_body=raw(body));need(read_cut(db,cut_id)==body,'cancel_cut_readback');return body,writes
    return N.transaction(db,run)

def snapshot_body(db,device,revision=None):
    """从完整历史原件投影当前IPC形状；没有持久封存，也不提供开放资格。"""
    source=D.materialize(db,device,revision);entries=[]
    for event in source['entries']:
        need(not event['cut_pending'],'command_deny_cut_pending');cut=read_cut(db,event['cut_id'])
        need(cut['binding']['cancellation_id']==event['cancellation_id'] and cut['binding']['parent_command_id']==event['parent_command_id'] and cut['stage']==event['stage'] and cut['deny_revision']==event['deny_revision'],'cancel_snapshot_entry')
        entries.append(dict(cancellation_id=event['cancellation_id'],parent_command_id=event['parent_command_id'],stage=event['stage'],deny_revision=event['deny_revision'],cut_ref=reference(cut['cut_id'],cut['cut_digest'])))
    body=M.sealed(dict(scope=M.E.A.scope(db),device_id=device,snapshot_revision=source['snapshot_revision'],entries=entries),'snapshot_digest');validate('S8__DenySnapshot',body);return body
