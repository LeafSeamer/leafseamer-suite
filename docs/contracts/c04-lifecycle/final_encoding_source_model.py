"""从持久编码原件构造最终封存输入；不签发许可、不执行设备I/O。"""
import json
import typed_encoding_path_model as E
import final_admission_storage_model as A
F=A.F;need=F.need;one=E.one;raw=E.raw;digest=E.digest

def ref(oid,revision,sha):return dict(id=oid,revision=str(int(revision)),digest=sha)

def original(role,tx,binding,identity,source,**fields):
    value=dict(role=role,source_ref=source,scope=binding['scope'],transaction_id=tx,
        body=dict(binding=binding,identity=identity,**fields))
    value['ref']=ref('projection_'+digest(value)[7:],1,F.projection_digest(value))
    F.validate('Original_'+role,value);return value

def match_write(db,write,key,value):
    """只解析本地insert构造器的固定语法，用于对账其全部命名列。"""
    sql,args=write;table=sql.split(' ',3)[2];cols=sql.split('(',1)[1].split(')',1)[0].split(',')
    actual=one(db,'SELECT * FROM '+table+' WHERE '+key+'=?',(value,))
    need(all(actual[c]==v for c,v in zip(cols,args)),'encoding_stored_'+table)

def read(db,pid,transaction_id,selected_tick,sealed_tick,provider):
    need(db.in_transaction,'final_encoding_transaction_required')
    F.validate('Id',transaction_id)
    for tick in (selected_tick,sealed_tick):F.validate('Counter',tick)
    selected=int(selected_tick);now=int(sealed_tick)
    r=one(db,'SELECT * FROM ep_prepared_candidate WHERE prepare_id=?',(pid,))
    need(r['kind']=='ordinary','final_encoding_ordinary_only')
    s=E.source(db,r['command_id'],r['proposed_attempt_id'],r['exit_id'])
    stored=one(db,'SELECT * FROM ep_reply WHERE prepare_id=?',(pid,))
    need(int(stored['received_tick'])<=selected<=now<int(r['expires_tick']),'final_encoding_window')
    request=one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(r['request_message_id'],))
    response=json.loads(stored['response_frame'])
    # 当前提供者重核，但历史证据仍按其实际接收tick重建，禁止重写历史时间。
    writes=E.receive(db,pid,response,provider,int(stored['received_tick']))
    match_write(db,writes[0],'frame_id',stored['journal_frame_id'])
    match_write(db,writes[1],'prepare_id',pid)
    match_write(db,writes[4],'packet_id',stored['packet_id'])
    request_frame=json.loads(request['frame_body'])
    match_write(db,E.journal(s,request_frame,'encoding_request',pid,int(request['observed_tick'])),'frame_id',request['frame_id'])
    journal=one(db,'SELECT * FROM ij_encoding_frame WHERE prepare_id=?',(pid,))
    need(journal['request_frame']==request['frame_body'] and journal['request_frame_digest']==request['frame_digest']
        and journal['request_seq']==request['seq'],'final_encoding_request_journal')
    for fid in (request['frame_id'],stored['journal_frame_id']):
        committed=one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(fid,))
        need(committed['disposition']=='applied' and int(committed['committed_tick'])<=now,'final_encoding_log_commit')
    committed=one(db,'SELECT * FROM ep_receive_commit WHERE prepare_id=?',(pid,))
    need(committed['disposition']=='prepared' and int(stored['received_tick'])<=int(committed['committed_tick'])<=selected,'final_encoding_receive_commit')
    need(bool(db.execute('SELECT 1 FROM ce_packet WHERE packet_id=?',(stored['packet_id'],)).fetchone()),'final_encoding_packet_mapping')
    state=one(db,'SELECT * FROM cm_latest WHERE command_id=?',(r['command_id'],))
    state_body=json.loads(state['state_body']);initial=s['initial'];command=json.loads(initial['command_body'])
    need(digest(state_body)==state['state_digest'] and digest(command)==initial['command_digest'],'final_encoding_command_digest')
    need(state['outcome']=='pending' and not state['paused_latched'] and state['terminal_revision'] is None,'final_encoding_command_current')
    attempt=one(db,'SELECT * FROM cm_attempt WHERE attempt_id=?',(r['proposed_attempt_id'],))
    prepared=one(db,'SELECT * FROM cm_revision WHERE command_id=? AND revision=?',(r['command_id'],attempt['prepared_revision']))
    need(prepared['kind']=='prepare' and digest(json.loads(prepared['state_body']))==prepared['state_digest'],'final_encoding_attempt_original')
    need(r['proposed_attempt_id'] in state_body['attempt_ids'] and attempt['command_id']==r['command_id'],'final_encoding_attempt_member')
    ns=s['namespace'];key=s['key'];content=json.loads(key['content_body']);request_key=json.loads(key['request_key_body'])
    need(command['content']==content and command['identity']==dict(key=request_key,request_digest=key['request_digest']), 'final_encoding_command_source')
    need(digest(content)==key['request_digest'] and content['origin']==s['command']['origin'],'final_encoding_request_digest')
    # 两种旧表没有统一self-digest，显式构造具名源描述，不能冒充整行摘要。
    request_source=dict(format_version='request-source/1',scope=s['binding']['scope'],key_id=key['key_id'],key=request_key,request_digest=key['request_digest'])
    attempt_source=dict(format_version='attempt-source/1',scope=s['binding']['scope'],command_id=r['command_id'],attempt_id=attempt['attempt_id'],
        ordinal=str(attempt['ordinal']),prepared_revision=str(int(attempt['prepared_revision'])),prepared_state_digest=prepared['state_digest'])
    identity=dict(kind='ordinary',command_ref=ref(r['command_id'],initial['revision'],initial['command_digest']),
        attempt_ref=ref(attempt['attempt_id'],1,digest(attempt_source)),cancellation_ref=None,execution_ref=None,
        requester=dict(kind='service' if content['origin']=='automation' else 'human',**{k:ns[k] for k in ('issuer_id','issuer_epoch','principal_id')}),
        origin=content['origin'],source_ref=ref(key['key_id'],1,digest(request_source)))
    F.validate('ExecutionIdentity',identity)
    binding=s['binding'];control=one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(binding['device_id'],))
    need(control['pending_operation_id'] is None,'final_encoding_pending_control')
    ready=one(db,'SELECT * FROM go_ready_candidate WHERE device_id=? AND exit_id=?',(binding['device_id'],binding['writer_exit_id']))
    gate=one(db,'SELECT * FROM go_current_gate WHERE gate_id=?',(ready['after_gate_id'],))
    snapshot=one(db,'SELECT * FROM go_valid_snapshot WHERE device_id=? AND exit_id=?',(binding['device_id'],binding['writer_exit_id']))
    need(int(ready['committed_tick'])<=selected and now<min(int(ready['expires_tick']),int(gate['lease_until_tick']),int(snapshot['expires_tick'])),'final_encoding_ready_window')
    state_ref=ref(r['command_id'],state['revision'],state['state_digest'])
    packet=json.loads(stored['packet_body']);evidence=json.loads(stored['evidence_body'])
    encoding=original('encoding',transaction_id,binding,identity,ref(evidence['evidence_id'],evidence['revision'],evidence['evidence_digest']),
        packet_record_ref=ref(packet['packet_id'],1,packet['packet_digest']),packet_ref={k:packet[k] for k in ('packet_id','packet_digest')},
        received_tick_ns=str(int(stored['received_tick'])),expires_tick_ns=str(int(r['expires_tick'])))
    origin=original('origin',transaction_id,binding,identity,identity['source_ref'],command_state_ref=state_ref)
    return dict(binding=binding,identity=identity,command_state_ref=state_ref,encoding=encoding,origin=origin,
        source_descriptors=dict(request=request_source,attempt=attempt_source))

def planned(db,seal,originals,cut,pid,provider):
    """重新查原，不能把上次read结果当成当前资格；其余16角色仍由各可信解析器负责。"""
    current=read(db,pid,seal['transaction_id'],seal['selected_tick_ns'],seal['sealed_tick_ns'],provider)
    for name in ('binding','identity','command_state_ref'):need(seal[name]==current[name],'final_encoding_'+name)
    for role in ('origin','encoding'):need(originals[role]==current[role],'final_encoding_projection_'+role)
    return A.planned(seal,originals,cut)
