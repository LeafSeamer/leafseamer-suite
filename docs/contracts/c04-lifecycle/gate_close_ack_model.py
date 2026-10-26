"""读取完整关闭ACK并保存日志及可用关闭原件；不会生成准备核销或恢复写闸。"""
from jsonschema import Draft202012Validator
import gate_close_dispatch_model as D
import build_gate_close as G
M=D.M;P=D.P;E=D.E;I=D.I
def validate(value):Draft202012Validator({'$defs':G.schema()['$defs'],'$ref':'#/$defs/GateCloseAcknowledgement'}).validate(value)

def usable(db,ack_id):return db.execute('SELECT 1 FROM gate_close_usable_ack WHERE ack_id=?',(ack_id,)).fetchone() is not None
def read(db,close_id):
    row=M.E.one(db,'SELECT * FROM gate_close_ack WHERE close_id=?',(close_id,));value=M.document(row['body']);validate(value)
    M.need(M.sealed(value,'ack_digest')==value and value['ack_digest']==row['digest'] and value['ack_id']==row['ack_id'] and value['close_id']==close_id and value['disposition']==row['disposition'] and P.u(value['received_tick_ns'])==row['received_tick'],'gate_ack_columns')
    f=M.E.one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(row['frame_id'],));frame=M.document(f['frame_body']);E.FRAME.validate(frame)
    wire=len(f['frame_body']).to_bytes(4,'big')+f['frame_body']
    M.need(value['frame_ref']==M.E.ref(f['frame_id'],1,M.F.digest(frame)) and value['wire_digest']==E.byte_digest(wire)==f['wire_digest'] and f['wire_body']==wire and f['wire_length']==len(wire) and f['frame_digest']==value['frame_ref']['digest'],'gate_ack_original')
    dispatch,original=D.read(db,close_id);binding=dispatch['target']['binding']
    M.need(frame['type']=='CLOSE_GATE_ACK' and frame['device_id'] is None and frame['body']==dict(close_id=close_id,closed_device_ids=[binding['device_id']]) and frame['reply_to']==original['message_id'] and value['dispatch_ref']==M.reference(dispatch,'dispatch_id','dispatch_digest'),'gate_ack_request')
    M.need(all(frame[k]==binding[k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','clock_domain_id','descriptor_digest')),'gate_ack_frame_binding')
    M.need(f['body_body']==M.raw(frame['body']) and f['session_id']==original['session_id'] and f['reply_frame_id']==original['frame_id'] and f['reply_to']==frame['reply_to'] and f['device_id'] is None and f['exit_id'] is None and f['observed_tick']==row['received_tick'] and f['direction']=='w2c' and f['message_type']=='CLOSE_GATE_ACK' and f['domain_kind']=='gate_close_ack' and f['domain_id']==value['ack_id'] and frame['message_id']==f['message_id']==f['frame_id'] and frame['seq']==str(int(f['seq'])),'gate_ack_frame_columns')
    seal=M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(f['frame_id'],));M.need(seal['disposition']==row['disposition'] and seal['committed_tick']==row['received_tick'],'gate_ack_seal')
    return value,f
def receive(db,close_id,wire,received_tick,observer_ref,fail_after=None):
    if db.in_transaction:raise D.C.I.ClockIngressStop('gate_ack_nested_transaction')
    writes=[]
    def write(table,**row):
        db.execute(*I(table,**row));writes.append(table)
        if fail_after==len(writes)-1:raise RuntimeError('injected_close_ack_write')
    try:
        M.need(isinstance(wire,bytes) and 4<len(wire)<=262148 and int.from_bytes(wire[:4],'big')==len(wire)-4,'gate_ack_wire')
        frame=M.document(wire[4:]);E.FRAME.validate(frame);M.need(M.raw(frame)==wire[4:],'gate_ack_canonical');M.validate('Ref',observer_ref)
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM gate_close_ack WHERE close_id=?',(close_id,)).fetchone():
            value,f=read(db,close_id);M.need(wire==f['wire_body'] and value['observer_ref']==observer_ref,'gate_ack_replay_conflict');db.commit();return value,[]
        dispatch,original=D.read(db,close_id);binding=dispatch['target']['binding'];tick=P.u(received_tick)
        M.need(frame['type']=='CLOSE_GATE_ACK' and frame['device_id'] is None and frame['reply_to']==original['message_id'] and frame['body']==dict(close_id=close_id,closed_device_ids=[binding['device_id']]),'gate_ack_target')
        M.need(all(frame[k]==binding[k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','clock_domain_id','descriptor_digest')),'gate_ack_session')
        disposition='applied' if db.execute('SELECT 1 FROM gate_close_accepting_dispatch WHERE close_id=?',(close_id,)).fetchone() else 'historical'
        aid=P.identity('gate_ack',dict(close_id=close_id,frame_digest=M.F.digest(frame)))
        value=M.sealed(dict(format_version='gate-close-ack/0.1.0-draft.1',ack_id=aid,revision='1',close_id=close_id,dispatch_ref=M.reference(dispatch,'dispatch_id','dispatch_digest'),
            frame_ref=M.E.ref(frame['message_id'],1,M.F.digest(frame)),observer_ref=observer_ref,wire_digest=E.byte_digest(wire),received_tick_ns=str(int(tick)),disposition=disposition),'ack_digest');validate(value);body=M.raw(value)
        write('ij_frame',frame_id=frame['message_id'],session_id=original['session_id'],exit_id=None,device_id=None,direction='w2c',message_type='CLOSE_GATE_ACK',message_id=frame['message_id'],seq=P.u(frame['seq']),reply_frame_id=original['frame_id'],reply_to=frame['reply_to'],
            frame_digest=value['frame_ref']['digest'],wire_digest=value['wire_digest'],frame_body=wire[4:],body_body=M.raw(frame['body']),wire_body=wire,wire_length=len(wire),observed_tick=tick,domain_kind='gate_close_ack',domain_id=aid,validation_body=body)
        write('gate_close_ack',ack_id=aid,close_id=close_id,frame_id=frame['message_id'],received_tick=tick,disposition=disposition,adopted_ack_id=aid if disposition=='applied' else None,digest=value['ack_digest'],body=body)
        if disposition=='applied':write('go_close_ack',ack_id=aid,close_id=close_id,exit_id=binding['writer_exit_id'],evidence_digest=value['ack_digest'],observer_ref=observer_ref['id'],received_tick=tick,body=body,validation_body=body,audit_body=body)
        write('ij_commit',frame_id=frame['message_id'],disposition=disposition,committed_tick=tick,audit_body=body,effect_body=body)
        read(db,close_id);db.commit();return value,writes
    except Exception as error:
        try:
            if db.in_transaction:db.rollback()
        except Exception:pass
        raise D.C.I.ClockIngressStop('gate_ack_exit_required') from error
