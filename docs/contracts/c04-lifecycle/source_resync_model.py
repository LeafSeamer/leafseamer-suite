"""来源重新同步的离线参考writer；真实快照、输送资格与连续性由可信提供者核验。"""
import jsonschema
import build_source_resync as G
import instance_budget_model as B
A=B.A;P=B.P;R=B.R;I=B.I

def validate(request):
    names={'baseline':'Baseline','delta':'Delta','ready':'Ready'}
    R.require(request.get('kind') in names,'resync_kind')
    jsonschema.Draft202012Validator({'$ref':'#/$defs/'+names[request['kind']],'$defs':G.schema()['$defs']}).validate(request)

def transition_steps(db,request,ctx):
    R.require(db.in_transaction,'transaction_required');validate(request)
    R.require(ctx['authorized'] and ctx['current'] and ctx['source_identity_verified'] and ctx['delivery_current'],'resync_authority')
    R.require(request['delivery_ref']==ctx['delivery_ref'],'resync_delivery_binding')
    kind=request['kind'];s=R.one(db,'ingress_source','source_id',request['source_id'])
    R.require(P.digest(s['source_key'])==request['source_key_digest'],'resync_source_identity')
    R.require(s['revision']==request['expected_source_revision'],'resync_stale_source')
    after=P.inc(s['revision']);seq=s['contiguous_sequence'];floor=s['reject_floor'];state='baseline_required'
    if kind=='baseline':
        R.require(ctx['human'] and ctx['snapshot_verified'] and ctx['snapshot_ref']==request['snapshot_ref'],'resync_snapshot')
        seq=floor=request['watermark'];P.inc(seq)
    elif kind=='delta':
        R.require(ctx['continuity_verified'] and ctx['event_ref']==request['event_ref'],'resync_delta_evidence')
        R.require(request['source_sequence']==P.inc(seq),'resync_sequence_gap');seq=request['source_sequence']
    else:
        R.require(ctx['checkpoint_verified'] and ctx['checkpoint_ref']==request['checkpoint_ref'],'resync_checkpoint')
        R.require(request['through_sequence']==seq,'resync_checkpoint_frontier');state='synchronized'
    raw=P.canonical(request);digest=P.digest(raw)
    row=dict(transition_id=request['transition_id'],baseline_id=request['baseline_id'],source_id=s['source_id'],fault_id=request['fault_id'],kind=kind,
        revision_before=s['revision'],revision_after=after,state_before=s['state'],state_after=state,sequence_before=s['contiguous_sequence'],sequence_after=seq,
        floor_before=s['reject_floor'],floor_after=floor,request_epoch=request['request_epoch'],actor_body=P.canonical(request['actor']),idempotency_key=request['idempotency_key'],request_digest=digest,request_body=raw)
    R.require(len(raw)<=4096 and len(B.C.encoded(tuple(row.values())))<=16384,'resync_row_capacity')
    return [I('rs_transition',**row),('UPDATE ingress_source SET revision=?,state=?,contiguous_sequence=?,reject_floor=? WHERE source_id=? AND revision=?',
        (after,state,seq,floor,s['source_id'],s['revision'])),I('rs_commit',transition_id=request['transition_id'],request_digest=digest,
        audit_body=P.canonical(dict(kind=kind,transition_id=request['transition_id'])),notification_body=P.canonical(dict(kind='source_'+kind,source_id=s['source_id'],revision=after)))]

def apply(db,request,ctx,fail_after=None):
    validate(request);R.require(ctx['authorized'] and ctx['current'],'resync_authority');result='accepted'
    def builder():
        nonlocal result
        rows=P.rows(db,'SELECT * FROM rs_transition WHERE transition_id=? OR(request_epoch=? AND actor_body=? AND idempotency_key=?)',
            (request['transition_id'],request['request_epoch'],P.canonical(request['actor']),request['idempotency_key']))
        if rows:
            R.require(len(rows)==1 and rows[0]['request_body']==P.canonical(request),'resync_identity_conflict')
            R.one(db,'rs_commit','transition_id',rows[0]['transition_id']);result='existing';return []
        return transition_steps(db,request,ctx)
    A.apply(db,builder,fail_after);return result
