"""失败布防退出的同库离线写集；不发送网络，也不替代资源释放与提供者授信。"""
import json
import jsonschema
import build_arm_exit as G
import arm_storage_model as A
P=A.P;R=A.R;I=A.I
SCHEMA=G.schema()
def validate(name,value):jsonschema.Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']}).validate(value)
def permission(ctx):R.require(ctx.get('trusted_system_closer') or(ctx.get('authorized') and ctx.get('current') and ctx.get('human')),'close_authority')
def plan_id(operation,ordinal):return 'aa.'+P.digest(P.canonical(dict(operation_id=operation,ordinal=ordinal))).split(':',1)[1]

def inventory(db,run,generation):
    ceiling=generation.zfill(20);items=[]
    for x in P.rows(db,"SELECT registration_id,binding_body FROM p1_preparation WHERE run_id=? AND substr('00000000000000000000'||generation,-20)<=?",(run,ceiling)):
        items.append(dict(kind='preparation',ref=x['registration_id'],body=x['binding_body'].hex().upper()))
    for x in P.rows(db,"SELECT execution_id,binding_digest FROM execution WHERE run_id=? AND substr('00000000000000000000'||arm_generation,-20)<=?",(run,ceiling)):
        items.append(dict(kind='execution',ref=x['execution_id'],body=x['binding_digest']))
    for x in P.rows(db,"SELECT s.submission_id,s.request_body FROM command_submission s JOIN execution e USING(execution_id) WHERE s.run_id=? AND substr('00000000000000000000'||e.arm_generation,-20)<=?",(run,ceiling)):
        items.append(dict(kind='submission',ref=x['submission_id'],body=x['request_body'].hex().upper()))
    R.require(len(items)<=65536,'inventory_capacity');return sorted(items,key=lambda x:(x['kind'],x['ref']))

def targets(db,run,generation):
    args=(run,generation.zfill(20),run,generation.zfill(20))
    return [tuple(x) for x in db.execute("""SELECT controller_authority,controller_database FROM p1_preparation
      WHERE run_id=? AND substr('00000000000000000000'||generation,-20)<=? UNION
      SELECT s.target_authority,s.target_database FROM command_submission s JOIN execution e USING(execution_id)
      WHERE s.run_id=? AND substr('00000000000000000000'||e.arm_generation,-20)<=? ORDER BY 1,2""",args)]

def attempt_steps(db,stop,request,ordinal,previous):
    R.require(db.in_transaction,'transaction_required')
    op=stop['operation_id'];run=stop['run_id'];generation=stop['generation'];pid=plan_id(op,ordinal)
    R.require(P.canonical(inventory(db,run,generation))==stop['inventory_body'],'inventory_changed')
    scopes=targets(db,run,generation);R.require(len(scopes)<=256,'target_capacity')
    scope=P.rows(db,'SELECT * FROM storage_scope')[0];raw=P.canonical(request)
    body=P.canonical(dict(arm_operation_id=op,run_id=run,generation=generation,inventory=json.loads(stop['inventory_body']),ordinal=ordinal,request_digest=P.digest(raw)))
    digest=P.digest(body);steps=[I('aa_attempt',plan_id=pid,operation_id=op,ordinal=ordinal,previous_plan_id=previous,
        request_epoch=request['request_epoch'],actor_body=P.canonical(request['actor']),idempotency_key=request['idempotency_key'],request_digest=P.digest(raw),request_body=raw,
        plan_digest=digest,plan_body=body,target_count=len(scopes)),I('sp_plan',plan_id=pid,plan_digest=digest,plan_body=body,target_count=len(scopes))]
    selector=dict(origin_scope=dict(authority_service_id=scope['authority_id'],database_instance_id=scope['database_id']),run_id=run,deny_through_generation=generation)
    for i,(ca,cd) in enumerate(scopes):
        ident=pid+'.t.'+str(i);binding=dict(controller_scope=dict(authority_service_id=ca,database_instance_id=cd),operation_id=ident,
            **selector,selector_digest=P.digest(P.canonical(selector)),target_set_digest=digest)
        blob=P.canonical(binding)
        steps += [I('aa_target',plan_id=pid,target_id=ident,controller_authority=ca,controller_database=cd,binding_body=blob,
                    dispatch_body=P.canonical(dict(kind='protect_registered_run',binding=binding))),I('sp_target',plan_id=pid,target_id=ident,binding_body=blob)]
    steps += [I('sp_plan_commit',plan_id=pid,validation_body=P.canonical(dict(arm_stop_operation_id=op))),
        I('aa_attempt_commit',plan_id=pid,audit_body=raw,notification_body=P.canonical(dict(kind='arm_exit_protection_pending',operation_id=op,plan_id=pid)))]
    return steps

def stop_steps(db,request,ctx):
    R.require(db.in_transaction,'transaction_required');permission(ctx);validate('StopIntent',request)
    op=R.one(db,'arm_operation','operation_id',request['arm_operation_id']);r=R.one(db,'run','run_id',op['run_id']);s=R.one(db,'activation_slot','definition_id',r['definition_id'])
    R.require(r['revision']==request['expected_run_revision'],'run_cas')
    raw=P.canonical(request);rev=P.inc(r['revision']);pid=plan_id(op['operation_id'],1)
    value=dict(operation_id=op['operation_id'],run_id=r['run_id'],generation=op['generation'],revision_before=r['revision'],revision_after=rev,slot_revision=s['revision'],
        request_epoch=request['request_epoch'],actor_body=P.canonical(request['actor']),idempotency_key=request['idempotency_key'],request_digest=P.digest(raw),request_body=raw,
        first_plan_id=pid,inventory_body=P.canonical(inventory(db,r['run_id'],op['generation'])),latch_id=pid+'.latch')
    return [I('aa_stop',**value),("UPDATE run SET revision=?,lifecycle='paused',dispatch_eligible=0 WHERE run_id=? AND revision=?",(rev,r['run_id'],r['revision'])),
        I('pause_latch',latch_id=value['latch_id'],run_id=r['run_id'],reason='arm_exit',created_revision=rev,body=raw)]+attempt_steps(db,value,request,1,None)

def stop(db,request,ctx,fail_after=None):
    permission(ctx);validate('StopIntent',request);found=[];digest=P.digest(P.canonical(request))
    def builder():
        rows=db.execute('SELECT operation_id,request_digest FROM aa_stop WHERE operation_id=? OR(request_epoch=? AND actor_body=? AND idempotency_key=?)',
            (request['arm_operation_id'],request['request_epoch'],P.canonical(request['actor']),request['idempotency_key'])).fetchall()
        if rows:R.require(len(rows)==1 and tuple(rows[0])==(request['arm_operation_id'],digest),'identity_conflict');found.append(True);return []
        return stop_steps(db,request,ctx)
    A.apply(db,builder,fail_after);return 'existing' if found else 'accepted'

def retry(db,request,ctx,fail_after=None):
    permission(ctx);validate('RetryIntent',request);found=[]
    def builder():
        raw=P.canonical(request);rows=db.execute('SELECT operation_id,request_digest FROM aa_attempt WHERE request_epoch=? AND actor_body=? AND idempotency_key=?',
            (request['request_epoch'],P.canonical(request['actor']),request['idempotency_key'])).fetchall()
        if rows:R.require(len(rows)==1 and tuple(rows[0])==(request['arm_operation_id'],P.digest(raw)),'identity_conflict');found.append(True);return []
        a=R.one(db,'aa_stop','operation_id',request['arm_operation_id']);p=R.one(db,'aa_latest_attempt','operation_id',a['operation_id'])
        R.require(request['previous_plan_id']==p['plan_id'],'stale_attempt')
        return attempt_steps(db,a,request,p['ordinal']+1,p['plan_id'])
    A.apply(db,builder,fail_after);return 'existing' if found else 'accepted'

def exit_steps(db,operation):
    R.require(db.in_transaction,'transaction_required');a=R.one(db,'aa_stop','operation_id',operation)
    t=R.one(db,'aa_latest_attempt','operation_id',operation);r=R.one(db,'run','run_id',a['run_id']);s=R.one(db,'activation_slot','definition_id',r['definition_id'])
    rev=P.inc(r['revision']);steps=[I('aa_exit',operation_id=operation,plan_id=t['plan_id'],run_id=r['run_id'],generation=a['generation'],revision_before=r['revision'],revision_after=rev,slot_revision=s['revision'])]
    observations=P.rows(db,'SELECT target_id,revision,observation_digest FROM sp_current_observation WHERE plan_id=? ORDER BY target_id',(t['plan_id'],))
    steps += [I('aa_exit_pin',operation_id=operation,plan_id=t['plan_id'],**x) for x in observations]
    steps += [("UPDATE run SET revision=?,active_operation_id=NULL WHERE run_id=? AND revision=?",(rev,r['run_id'],r['revision'])),
        I('aa_exit_commit',operation_id=operation,audit_body=P.canonical(dict(operation_id=operation)),notification_body=P.canonical(dict(kind='arm_exit_observed',operation_id=operation,resources_cleared=False,budget_released=False)))]
    return steps

def complete(db,operation,ctx,fail_after=None):
    permission(ctx)
    def builder():return [] if db.execute('SELECT 1 FROM aa_exit_commit WHERE operation_id=?',(operation,)).fetchone() else exit_steps(db,operation)
    A.apply(db,builder,fail_after);e=R.one(db,'aa_exit','operation_id',operation)
    pins=[dict(target_id=x['target_id'],status_revision=str(x['revision']),observation_digest=x['observation_digest']) for x in P.rows(db,'SELECT * FROM aa_exit_pin WHERE operation_id=? ORDER BY target_id',(operation,))]
    result=dict(contract_version=G.VERSION,arm_operation_id=operation,run_id=e['run_id'],generation=e['generation'],plan_id=e['plan_id'],run_revision=e['revision_after'],
        state='paused',resources_cleared=False,budget_released=False,observations=pins);validate('ExitResult',result);return result

def receive_preparation(db,ident,value,controller):
    def adopt(db,ident,value,controller):
        p=R.one(db,'p1_preparation','registration_id',ident)
        return [] if db.execute('SELECT 1 FROM aa_stop WHERE operation_id=?',(p['arm_operation_id'],)).fetchone() else A.adoption_steps(db,ident,value,controller)
    return A.Q.receive(db,ident,value,controller,adopt=adopt)
