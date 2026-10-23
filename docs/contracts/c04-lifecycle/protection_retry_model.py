"""重新关闭的离线写集；身份及关闭权限由可信上下文提供，不执行网络重试。"""
import json,jsonschema
import build_protection_retry as G
import failure_protection_model as M
import arm_exit_model as X
A=M.A;P=M.P;R=M.R;I=M.I
def validate(name,value):jsonschema.Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':G.schema()['$defs']}).validate(value)
def retry_steps(db,request,ctx):
    R.require(db.in_transaction,'transaction_required');X.permission(ctx);validate('RetryIntent',request)
    root=R.one(db,'sf_plan','plan_id',request['root_plan_id']);last=R.one(db,'sr_latest','root_plan_id',root['plan_id'])
    R.require(last['plan_id']==request['previous_plan_id'],'stale_attempt')
    ordinal=last['attempt_index']+1;R.require(ordinal<=16,'retry_capacity')
    raw=P.canonical(request);pid='sr.'+P.digest(P.canonical(dict(root_plan_id=root['plan_id'],attempt_index=ordinal))).split(':',1)[1]
    body=P.canonical(dict(root_plan_id=root['plan_id'],root_plan_digest=root['plan_digest'],run_id=root['run_id'],generation=root['generation'],attempt_index=ordinal,request_digest=P.digest(raw)))
    targets=P.rows(db,'SELECT * FROM sf_target WHERE plan_id=? ORDER BY controller_authority,controller_database',(root['plan_id'],))
    writes=[I('sr_attempt',plan_id=pid,root_plan_id=root['plan_id'],attempt_index=ordinal,previous_plan_id=last['plan_id'],request_epoch=request['request_epoch'],
        actor_body=P.canonical(request['actor']),idempotency_key=request['idempotency_key'],request_digest=P.digest(raw),request_body=raw,plan_digest=P.digest(body),plan_body=body,target_count=len(targets)),
        I('sp_plan',plan_id=pid,plan_digest=P.digest(body),plan_body=body,target_count=len(targets))]
    for i,t in enumerate(targets):
        tid=pid+'.'+str(i);binding=json.loads(t['binding_body']);binding.update(operation_id=tid,target_set_digest=P.digest(body));blob=P.canonical(binding)
        writes += [I('sr_target',plan_id=pid,target_id=tid,controller_authority=t['controller_authority'],controller_database=t['controller_database'],binding_body=blob,
            dispatch_body=P.canonical(dict(kind='protect_registered_run',binding=binding))),I('sp_target',plan_id=pid,target_id=tid,binding_body=blob)]
    return writes+[I('sp_plan_commit',plan_id=pid,validation_body=P.canonical(dict(root_plan_id=root['plan_id']))),
        I('sr_commit',plan_id=pid,audit_body=raw,notification_body=P.canonical(dict(kind='failure_protection_retried',plan_id=pid,root_plan_id=root['plan_id'])))]
def retry(db,request,ctx,fail_after=None):
    X.permission(ctx);validate('RetryIntent',request);ids=[]
    def builder():
        raw=P.canonical(request);prior=P.rows(db,'SELECT * FROM sr_attempt WHERE request_epoch=? AND actor_body=? AND idempotency_key=?',
            (request['request_epoch'],P.canonical(request['actor']),request['idempotency_key']))
        if prior:
            R.require(len(prior)==1 and prior[0]['request_body']==raw and prior[0]['request_digest']==P.digest(raw),'identity_conflict')
            R.one(db,'sr_commit','plan_id',prior[0]['plan_id']);ids.append(prior[0]['plan_id']);return []
        return retry_steps(db,request,ctx)
    A.apply(db,builder,fail_after)
    row=R.one(db,'sr_attempt','plan_id',ids[0]) if ids else P.rows(db,'SELECT * FROM sr_attempt WHERE request_epoch=? AND actor_body=? AND idempotency_key=?',
        (request['request_epoch'],P.canonical(request['actor']),request['idempotency_key']))[0]
    result=dict(contract_version=G.VERSION,root_plan_id=row['root_plan_id'],plan_id=row['plan_id'],attempt_index=row['attempt_index'],actions_replayed=False,resources_cleared=False,budget_released=False)
    validate('RetryResult',result);return result
