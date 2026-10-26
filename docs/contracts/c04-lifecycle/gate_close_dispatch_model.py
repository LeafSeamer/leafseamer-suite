"""已持久设备关闭到完整IPC日志；不要求认证故障，不执行线路。"""
import json
from jsonschema import Draft202012Validator
import authorization_clock_protection_model as P
import build_gate_close as G
M=P.M;E=M.E.E;C=P.C;I=P.I
def validate(value):Draft202012Validator({'$defs':G.schema()['$defs'],'$ref':'#/$defs/GateCloseDispatch'}).validate(value)
def install(db):
    M.need(not db.in_transaction,'gate_close_install_transaction')
    for name,expected in G.originals().items():
        actual=M.E.one(db,'SELECT sql FROM sqlite_schema WHERE name=?',(name,))['sql'];M.need(actual.rstrip(';')==expected.rstrip(';'),'gate_close_layout_anchor')
    try:db.executescript('BEGIN IMMEDIATE;\n'+G.sql().decode()+'\nCOMMIT;')
    except Exception:
        if db.in_transaction:db.rollback()
        raise

def close_ref(db,cid):
    row=M.E.one(db,'SELECT * FROM go_close WHERE close_id=?',(cid,));return M.E.ref(cid,str(int(row['revision'])),M.F.digest(C.columns(row)))

def read(db,close_id):
    row=M.E.one(db,'SELECT * FROM gate_close_dispatch WHERE close_id=?',(close_id,))
    value=M.document(row['body']);validate(value);M.need(M.sealed(value,'dispatch_digest')==value and row['digest']==value['dispatch_digest'],'gate_close_digest')
    M.need(value['close_id']==row['close_id'] and value['close_ref']==close_ref(db,close_id) and value['frame_ref']['id']==row['frame_id'] and P.u(value['selected_tick_ns'])==row['selected_tick'],'gate_close_columns')
    close=M.E.one(db,'SELECT * FROM go_close WHERE close_id=?',(close_id,));exit_row=M.E.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(close['exit_id'],))
    binding=P.S.binding(db,close['exit_id']);target=value['target']
    M.need(target['binding']==binding and target['exit_source_ref']==C.source_ref('clock_exit',C.columns(exit_row)) and target['close_body']==dict(close_id=close_id,reason=close['reason_ref'],scope='device'),'gate_close_source')
    f=M.E.one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(row['frame_id'],));frame=M.document(f['frame_body']);E.FRAME.validate(frame)
    wire=len(f['frame_body']).to_bytes(4,'big')+f['frame_body']
    M.need(f['frame_digest']==M.F.digest(frame)==value['frame_ref']['digest'] and f['wire_body']==wire and E.byte_digest(wire)==f['wire_digest']==value['wire_digest'] and len(wire)==f['wire_length']==int(value['wire_bytes']),'gate_close_original')
    M.need(frame['body']==value['target']['close_body'] and frame['type']=='CLOSE_GATE' and frame['message_id']==f['frame_id']==value['dispatch_id'] and frame['seq']==str(int(f['seq'])),'gate_close_frame')
    M.need(f['body_body']==M.raw(frame['body']) and f['session_id']==value['target']['session_id'] and f['exit_id']==value['target']['binding']['writer_exit_id'] and f['device_id']==frame['device_id'] and f['observed_tick']==row['selected_tick'] and f['domain_kind']=='gate_close' and f['domain_id']==close_id,'gate_close_frame_columns')
    M.need(all(frame[k]==value['target']['binding'][k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id','clock_domain_id','descriptor_digest')),'gate_close_binding')
    M.need(f['direction']=='c2w' and f['message_type']=='CLOSE_GATE' and f['message_id']==f['frame_id'],'gate_close_direction')
    seal=M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(f['frame_id'],));M.need(seal['disposition']=='applied' and seal['committed_tick']==row['selected_tick'],'gate_close_seal')
    return value,f
def queue(db,close_id,tick,fail_after=None):
    if db.in_transaction:raise C.I.ClockIngressStop('gate_close_nested_transaction')
    writes=[]
    def write(table,**row):
        db.execute(*I(table,**row));writes.append(table)
        if fail_after==len(writes)-1:raise RuntimeError('injected_close_write')
    try:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM gate_close_dispatch WHERE close_id=?',(close_id,)).fetchone():
            value,_=read(db,close_id);db.commit();return value,[]
        close=M.E.one(db,'SELECT * FROM go_close WHERE close_id=?',(close_id,));exit_row=M.E.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(close['exit_id'],));reference=close_ref(db,close_id)
        target=C.route_target(db,exit_row,reference);M.need(target['required_action']=='close_gate','gate_close_requires_termination')
        target['close_body']=dict(close_id=close_id,reason=close['reason_ref'],scope='device')
        control=M.E.one(db,'SELECT * FROM ct_change WHERE change_id=?',(close['protection_change_id'],))
        M.need((control['clock_domain'],control['descriptor'])==(exit_row['clock_domain_id'],exit_row['descriptor_digest']),'gate_close_domain_binding')
        session=M.E.one(db,'SELECT * FROM ij_session WHERE session_id=?',(target['session_id'],))
        tick=P.u(tick);seq=int(db.execute("SELECT coalesce(max(seq),'0') FROM ij_frame WHERE session_id=? AND direction='c2w'",(target['session_id'],)).fetchone()[0])+1;P.u(seq)
        mid=P.identity('gate_close',dict(close_ref=reference,close_id=close_id))
        frame=E.frame(target['binding'],'CLOSE_GATE',mid,seq,target['close_body'])
        # 使用现有JCS与4字节长度前缀格式，避免合成短正文冒充完整线路容量。
        raw=M.raw(frame);wire=len(raw).to_bytes(4,'big')+raw
        value=M.sealed(dict(format_version='gate-close-dispatch/0.1.0-draft.1',dispatch_id=mid,revision='1',close_ref=reference,close_id=close_id,target=target,
            frame_ref=M.E.ref(mid,1,M.F.digest(frame)),wire_digest=E.byte_digest(wire),wire_bytes=str(len(wire)),selected_tick_ns=str(int(tick)),state='queued'),'dispatch_digest');validate(value)
        evidence=M.raw(value)
        write('ij_frame',frame_id=mid,session_id=session['session_id'],exit_id=exit_row['exit_id'],device_id=exit_row['device_id'],direction='c2w',message_type='CLOSE_GATE',message_id=mid,seq=P.u(seq),reply_frame_id=None,reply_to=None,
            frame_digest=value['frame_ref']['digest'],wire_digest=value['wire_digest'],frame_body=raw,body_body=M.raw(frame['body']),wire_body=wire,wire_length=len(wire),observed_tick=tick,domain_kind='gate_close',domain_id=close_id,validation_body=evidence)
        write('gate_close_dispatch',close_id=close_id,frame_id=mid,selected_tick=tick,digest=value['dispatch_digest'],body=evidence)
        write('ij_commit',frame_id=mid,disposition='applied',committed_tick=tick,audit_body=evidence,effect_body=evidence)
        read(db,close_id);db.commit();return value,writes
    except Exception as error:
        try:
            if db.in_transaction:db.rollback()
        except Exception:pass
        raise C.I.ClockIngressStop('gate_close_exit_required') from error
def begin_write(db,close_id,tick):
    """只登记一次入流尝试；重复返回查原状态，不授权重新写线路。"""
    if db.in_transaction:raise C.I.ClockIngressStop('gate_close_nested_transaction')
    try:
        db.execute('BEGIN IMMEDIATE');value,f=read(db,close_id)
        if db.execute('SELECT 1 FROM ij_write_attempt WHERE frame_id=?',(f['frame_id'],)).fetchone():db.commit();return 'lookup_only'
        # 已固定的关闭命令不可换路由；会话终止由既有日志守卫拒绝。
        body=M.raw(dict(close_ref=M.reference(value,'dispatch_id','dispatch_digest'),attempted_tick_ns=str(int(P.u(tick)))))
        db.execute(*I('ij_write_attempt',frame_id=f['frame_id'],attempt_id=f['frame_id']+'.write',attempted_tick=P.u(tick),encoding_prepare_id=None,current_validation_body=body,audit_body=body))
        db.commit();return 'attempt_recorded'
    except Exception as error:
        try:
            if db.in_transaction:db.rollback()
        except Exception:pass
        raise C.I.ClockIngressStop('gate_close_exit_required') from error
