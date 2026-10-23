"""来源准入、独享份额及注册封存的离线参考事务。"""
import jsonschema
import build_source_budget as G
import instance_budget_model as B
A=B.A;P=B.P;R=B.R;I=B.I
def validate(request):jsonschema.Draft202012Validator({'$ref':'#/$defs/Admission','$defs':G.schema()['$defs']}).validate(request)
def reserve_steps(db,request,ctx):
    R.require(db.in_transaction,'transaction_required');validate(request)
    R.require(ctx['authorized'] and ctx['human'] and ctx['current'] and ctx['source_identity_verified'],'source_admission_authority')
    source=R.one(db,'ingress_source','source_id',request['source_id']);pool=R.one(db,'ib_pool','singleton',1)
    R.require(request['source_key_digest']==P.digest(source['source_key']),'source_identity_digest')
    R.require(request['expected_source_revision']==source['revision'] and request['pool_profile_digest']==pool['profile_digest'],'source_admission_prestate')
    R.require(1<=int(request['episodes'])<=65536,'source_episode_range');raw=P.canonical(request);digest=P.digest(raw);ident='source.budget.'+digest.split(':',1)[1]
    reservation=dict(source_id=source['source_id'],reservation_id=ident,pool_id=1,profile_digest=pool['profile_digest'],source_revision=source['revision'],source_key_digest=request['source_key_digest'],
        episodes=int(request['episodes']),request_epoch=request['request_epoch'],actor_body=P.canonical(request['actor']),idempotency_key=request['idempotency_key'],request_digest=digest,request_body=raw)
    registry=dict(source_id=source['source_id'],revision='1')
    seal=dict(source_id=source['source_id'],reservation_id=ident,request_digest=digest,registry_revision='1',audit_body=P.canonical(dict(kind='source_admitted',reservation_id=ident)),
        notification_body=P.canonical(dict(kind='source_ready',source_id=source['source_id'])))
    for fields,limit in ((reservation,8192),(registry,2048),(seal,4096)):R.require(len(B.C.encoded(tuple(fields.values())))<=limit,'source_admission_row_bound')
    return [I('sb_reservation',**reservation),I('ingress_registry',**registry),I('sb_commit',**seal)]
def reserve(db,request,ctx,fail_after=None):
    validate(request);R.require(ctx['authorized'],'source_admission_authority');result='accepted'
    def builder():
        nonlocal result
        old=P.rows(db,'SELECT * FROM sb_reservation WHERE source_id=? OR(request_epoch=? AND actor_body=? AND idempotency_key=?)',
            (request['source_id'],request['request_epoch'],P.canonical(request['actor']),request['idempotency_key']))
        if old:
            R.require(len(old)==1 and old[0]['request_body']==P.canonical(request),'source_admission_identity_conflict');R.one(db,'sb_commit','source_id',request['source_id']);result='existing';return []
        return reserve_steps(db,request,ctx)
    A.apply(db,builder,fail_after);return result
