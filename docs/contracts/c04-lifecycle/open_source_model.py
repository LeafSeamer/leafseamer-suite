"""恢复快照与开放前态的同库来源参考适配；不签发开放或发送资格。"""
import copy
import typed_gate_fence_model as F
import recovery_close_choice_model as Y
import open_contract_model as O
S=F.S;M=F.M;N=F.N;P=F.P;I=F.I;need=M.need

def rows(db,sql,args=()):
    c=db.execute(sql,args);return [dict(zip([d[0] for d in c.description],r)) for r in c.fetchall()]

def observations(db,device,sid):
    """普通恢复只接受完整且可继续的现存风险集合，不把风险清空。"""
    need(db.in_transaction,'open_source_transaction_required')
    result=[];risks=rows(db,'SELECT * FROM cr_risk_hold WHERE device_id=? ORDER BY hold_id LIMIT 4097',(device,))
    need(len(risks)<=4096,'open_source_hold_capacity')
    authority=M.E.one(db,'SELECT * FROM go_authority WHERE device_id=?',(device,))
    for h in risks:
        owners=rows(db,'SELECT * FROM ow_current_owner WHERE hold_id=?',(h['hold_id'],));need(len(owners)==1,'open_source_owner_missing')
        owner=owners[0];original=S.ownership(db,owner['ownership_id'])
        command=M.E.one(db,'SELECT * FROM cm_latest WHERE command_id=?',(h['command_id'],))
        need(command['outcome']!='unknown' and command['resource_status']!='unresolved','open_source_unresolved_hold')
        need(owner['authority_state_id']==authority['change_id'],'open_source_old_authority')
        need(original['hold_ref']==M.E.ref(h['hold_id'],1,h['hold_digest']),'open_source_owner_hold')
        result.append(dict(snapshot_id=sid,hold_id=h['hold_id'],authority_state_id=owner['authority_state_id'],owner_ref=owner['ownership_id'],owner_revision=owner['revision'],owner_digest=owner['ownership_digest'],classification='active'))
    return result

def prepare_snapshot(db,rid,sid,eid,links,tick,expires,provider):
    need(db.in_transaction,'open_source_transaction_required')
    need(set(links)=={'authorization_ref','resource_ref','run_snapshot_ref','command_snapshot_ref','time_snapshot_ref'},'open_source_link_fields')
    for v in (rid,sid,eid,*links.values()):S.validate('Id',v)
    M.validate('Ref',provider);S.validate('Counter',str(tick));S.validate('Counter',str(expires));need(int(tick)<int(expires),'open_source_window')
    binding=S.binding(db,eid);device=binding['device_id'];state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(device,));authority=M.E.one(db,'SELECT * FROM go_authority WHERE device_id=?',(device,))
    need(state['gate_state']=='protected' and state['pending_operation_id'] is None,'open_source_requires_protection')
    revision=int(db.execute("SELECT coalesce(max(revision),'0') FROM go_hazard WHERE device_id=?",(device,)).fetchone()[0]);need(revision<10**20-1,'open_source_safety_exhausted')
    s=dict(snapshot_id=sid,device_id=device,exit_id=eid,authority_state_id=authority['change_id'],control_state_id=state['change_id'],safety_revision=P.u(revision),**links,sampled_tick=P.u(tick),expires_tick=P.u(expires),provider_ref=provider['id'])
    holds=observations(db,device,sid);body=S.snapshot_body(db,s,holds)
    # 后继head仅引用恢复ID，不引用恢复摘要；可先计算，写入后必须按物理行重建相等。
    cut=S.sealed(dict(format_version='resource-safety-cut/1',scope=binding['scope'],device_id=device,revision=str(revision+1),head=dict(source_kind='recovery',source_id=rid,recovery_id=rid)),'cut_digest')
    S.validate('ResourceSafetyCut',cut);body['resource_safety_ref']=S.safety_ref(cut);body=S.sealed(body,'evidence_digest');S.validate('ResourceSnapshotRecord',body)
    s.update(safety_revision=P.u(revision+1),evidence_body=M.raw(body),evidence_digest=body['evidence_digest']);return s,holds,body

def read(db,rid):
    need(db.in_transaction,'open_source_transaction_required')
    receipt=Y.read(db,rid);row=M.E.one(db,'SELECT * FROM go_recovery WHERE recovery_id=?',(rid,));body=S.snapshot(db,row['snapshot_id'])
    need(receipt['binding']==body['binding'] and receipt['selected_tick_ns']==body['sampled_tick_ns'] and receipt['provider_ref']['id']==body['provider_id'],'open_source_recovery_binding')
    return receipt,body

def recover(db,rid,sid,eid,links,tick,expires,provider,selections,fail_after=None):
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM go_recovery WHERE recovery_id=?',(rid,)).fetchone():
            receipt,body=read(db,rid);stored=M.E.one(db,'SELECT * FROM go_snapshot WHERE snapshot_id=?',(body['snapshot_id'],))
            need(body['snapshot_id']==sid and body['binding']['writer_exit_id']==eid and receipt['provider_ref']==provider and body['sampled_tick_ns']==str(tick) and body['expires_tick_ns']==str(expires) and set(links)=={'authorization_ref','resource_ref','run_snapshot_ref','command_snapshot_ref','time_snapshot_ref'} and all(stored[k]==v for k,v in links.items()),'open_source_replay_conflict')
            expected=sorted([Y.choice(db,s)[0] for s in selections],key=lambda x:x['close_ref']['id']);need(expected==receipt['targets'],'open_source_replay_targets');return receipt,body,Y.current(db,rid),writes
        s,holds,body=prepare_snapshot(db,rid,sid,eid,links,tick,expires,provider);receipt=Y.receipt(db,rid,s,holds,selections,tick,provider)
        for target in receipt['targets']:
            need(Y.X.current(db,target['retired_completion_ref']['id']) if target['kind']=='supervisor_retired' else N.current(db,target['close_ref']['id']),'open_source_close_not_current')
        raw=M.raw(receipt)
        write('go_recovery',recovery_id=rid,device_id=s['device_id'],snapshot_id=sid,now_tick=P.u(tick),recovery_digest=receipt['recovery_digest'],body=raw,provider_ref=M.raw(provider).decode())
        need(S.snapshot_body(db,s,holds)==body,'open_source_predicted_cut')
        write('go_snapshot',**s)
        for h in holds:write('go_hold',**h)
        write('go_snapshot_commit',snapshot_id=sid,audit_body=raw)
        for selection in selections:
            value,aid=Y.choice(db,selection)
            if selection['kind']=='worker_ack':write('go_recovery_target',recovery_id=rid,close_id=selection['close_id'],ack_id=aid)
            else:write('gr_retired_target',recovery_id=rid,close_id=selection['close_id'],completion_id=selection['completion_id'],exit_id=value['writer_exit_id'])
        write('go_recovery_commit',recovery_id=rid,audit_body=raw,outbox_body=raw)
        need(Y.current(db,rid),'open_source_recovery_not_current');need(read(db,rid)==(receipt,body),'open_source_readback');return receipt,body,True,writes
    return N.transaction(db,run)

def before_open(db,rid,fid,now):
    need(db.in_transaction,'open_source_transaction_required');S.validate('Counter',str(now))
    recovery,snapshot=read(db,rid);gate=F.read_gate(db,fid);binding=snapshot['binding'];device=binding['device_id']
    need(Y.current(db,rid) and F.current(db,fid),'open_source_not_current')
    need(db.execute('SELECT 1 FROM go_current_gate WHERE gate_id=?',(gate['gate_id'],)).fetchone() is not None,'open_source_gate_superseded')
    need(gate['binding']==binding and int(gate['committed_tick_ns'])<=int(now)<min(int(gate['lease_until_tick_ns']),int(snapshot['expires_tick_ns'])),'open_source_gate_window')
    state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(device,));authority=M.E.one(db,'SELECT * FROM go_authority WHERE device_id=?',(device,))
    control=S.control(db,state['change_id']);a=S.control(db,authority['change_id']);cut=S.safety(db,device,snapshot['resource_safety_ref']['revision'])
    need(snapshot['control_state_ref']==S.control_ref(control) and snapshot['control_authority_ref']==S.control_ref(a) and snapshot['resource_safety_ref']==S.safety_ref(cut),'open_source_current_refs')
    need(control['gate_state']=='protected' and control['pending_operation_id'] is None,'open_source_control_closed')
    holder=None if control['holder'] is None else {k:control['holder'][k] for k in ('issuer_id','issuer_epoch','principal_id')}
    cp=dict(record_ref=S.control_ref(control),authority_ref=S.control_ref(a),control_epoch=control['control_epoch'],effective_version=control['effective_version'],mode=control['mode'],holder=holder,pending_operation_id=control['pending_operation_id'],gate_state=control['gate_state'])
    gp=dict(record_ref=M.E.ref(gate['gate_id'],gate['revision'],gate['record_digest']),binding=binding,gate_revision=gate['gate_revision'],gate_token=gate['gate_token'],barrier_id=gate['barrier_id'],phase='fenced',activation_id=None,lease_until_tick_ns=gate['lease_until_tick_ns'])
    need(O.valid('ControlProjection',cp) and O.valid('GateProjection',gp),'open_source_projection_schema')
    return dict(binding=copy.deepcopy(binding),control_before=cp,gate_before=gp,resource_snapshot_ref=M.E.ref(snapshot['snapshot_id'],1,snapshot['evidence_digest']),resource_safety_ref=S.safety_ref(cut),originals=dict(control=control,authority=a,gate=gate,resource=snapshot,safety=cut,recovery=recovery))
