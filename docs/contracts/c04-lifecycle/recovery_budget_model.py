"""恢复R2新预留的离线事务；可信库存、当前身份与设备容量仍由合成提供者声明。"""
import json
import build_recovery_budget as G
import protection_charge_model as C
A=C.A;P=C.P;R=C.R;I=C.I;B=A.B
def reserve_steps(db,request,ctx):
    R.require(db.in_transaction,'transaction_required')
    R.require(ctx['human'] and ctx['inventory_verified'] and ctx['controller_capacity_verified'],'recovery_budget_context')
    original=R.reserve_steps(db,request,ctx)
    r=R.one(db,'run','run_id',request['run_id']);p=R.one(db,'recovery_preview','preview_id',request['preview_id'])
    cap=P.rows(db,'SELECT * FROM arm_capacity')[0];profile=json.loads(cap['profile_body']);B.validate('Profile',profile)
    R.require(B.digest(profile)==cap['profile_digest'],'profile_digest')
    forecast=ctx['forecast'];per=B.cost(profile,forecast);held={k:str(int(v)*int(profile['episodes'])) for k,v in per.items()}
    sc=P.rows(db,'SELECT * FROM storage_scope')[0]
    artifact=db.execute('SELECT artifact_digest FROM published_version WHERE definition_id=? AND version=?',(r['definition_id'],r['version'])).fetchone()[0]
    binding=dict(scope=dict(authority_service_id=sc['authority_id'],database_instance_id=sc['database_id']),run_id=r['run_id'],generation=P.inc(r['arm_generation']),
        operation_id=request['operation_id'],artifact_digest=artifact,inventory_digest=ctx['inventory_digest'],profile_id=profile['profile_id'],profile_revision=profile['revision'],profile_digest=cap['profile_digest'],forecast=forecast)
    ticket=dict(reservation_id='budget.'+B.digest(binding).split(':',1)[1],binding=binding,binding_digest=B.digest(binding),per_episode=per,held=held,spent=B.vector(),episodes_left=profile['episodes'],state='held')
    B.validate('Reservation',ticket)
    sql,args=original[-1];seal=dict(zip(sql.split('(',1)[1].split(')',1)[0].split(','),args));op=request['operation_id']
    original += [I('recovery_budget_reservation',operation_id=op,profile_digest=cap['profile_digest'],**{k:int(v) for k,v in held.items()},preview_digest=p['preview_digest'],
        manifest_digest=seal['manifest_digest'],request_digest=P.digest(P.canonical(request)),budget_body=P.canonical(ticket),audit_body=P.canonical(dict(operation_id=op))),
        I('recovery_budget_commit',operation_id=op,binding_digest=ticket['binding_digest'],preview_digest=p['preview_digest'],manifest_digest=seal['manifest_digest'],
            audit_body=P.canonical(dict(kind='recovery_budget_reserved',operation_id=op)),notification_body=P.canonical(dict(kind='recovery_accepted',operation_id=op)))]
    return original
def reserve(db,request,ctx,fail_after=None):
    R.require(ctx['authorized'],'unqualified_context');result='accepted'
    def builder():
        nonlocal result
        prior=P.rows(db,'SELECT operation_id,request_digest FROM recovery_operation WHERE operation_id=? OR (request_epoch=? AND actor_identity=? AND operation_kind=? AND idempotency_key=?)',
            (request['operation_id'],request['request_epoch'],P.canonical(request['actor']),'resumeAutomationRun',request['idempotency_key']))
        if prior:
            R.require(len(prior)==1 and prior[0]['operation_id']==request['operation_id'] and prior[0]['request_digest']==P.digest(P.canonical(request)),'identity_conflict')
            R.one(db,'recovery_budget_commit','operation_id',request['operation_id']);result='existing';return []
        return reserve_steps(db,request,ctx)
    A.apply(db,builder,fail_after);return result
