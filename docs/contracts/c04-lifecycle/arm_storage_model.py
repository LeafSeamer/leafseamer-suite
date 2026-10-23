"""普通布防的同库参考写集；权限、库存、时钟和平台资格仍由合成提供者输入。"""
import json,re
import build_arm_storage as G
import arm_budget_model as B
import storage_model as P
import registration_model as R
import qualification_model as Q
I=P.row
def u20(v):R.require(isinstance(v,str) and re.fullmatch(r'0|[1-9][0-9]{0,19}',v),'u20')
def sources(db,run):
    return P.rows(db,'SELECT source_id,revision,state FROM ingress_source WHERE source_id IN (SELECT source_id FROM p1_dependency WHERE run_id=?) ORDER BY source_id',(run,))
def preflight_step(db,ident,run,targets,context):
    r=R.one(db,'run','run_id',run);s=R.one(db,'activation_slot','definition_id',r['definition_id'])
    v=db.execute('SELECT artifact_digest FROM published_version WHERE definition_id=? AND version=?',(r['definition_id'],r['version'])).fetchone()[0]
    for t in targets:R.require(set(t)=={'controller_id','registration_id','preparation_id','controller_scope','request_body'},'target_fields')
    for name in ('issued_tick','expires_tick'):u20(context[name])
    R.require(int(context['issued_tick'])<int(context['expires_tick']),'preflight_time')
    fields=dict(preflight_id=ident,run_id=run,run_revision=r['revision'],slot_revision=s['revision'],generation_before=r['arm_generation'],
        artifact_digest=v,dependency_head=db.execute('SELECT coalesce(max(sequence),0) FROM p1_dependency').fetchone()[0],source_body=P.canonical(sources(db,run)),
        targets_body=P.canonical(targets),clock_body=context['clock_body'],issued_tick=context['issued_tick'],expires_tick=context['expires_tick'])
    # 将BLOB转为正文对象后计算摘要，避免把二进制当JSON数值列表。
    normalized={k:(json.loads(v) if k in ('source_body','targets_body') else v.hex() if isinstance(v,bytes) else v) for k,v in fields.items()}
    return I('arm_preflight',**fields,preflight_digest=P.digest(P.canonical(normalized)),consumed_operation_id=None)
def reserve_steps(db,request,context):
    R.require(db.in_transaction,'transaction_required')
    R.require(context['authorized'] and context['human'] and context['current'] and context['inventory_verified'] and context['controller_capacity_verified'],'unqualified_context')
    u20(context['now_tick'])
    r=R.one(db,'run','run_id',request['run_id']);f=R.one(db,'arm_preflight','preflight_id',request['preflight_id']);s=R.one(db,'activation_slot','definition_id',r['definition_id'])
    cap=P.rows(db,'SELECT * FROM arm_capacity')[0];profile=json.loads(cap['profile_body']);B.validate('Profile',profile)
    R.require(B.digest(profile)==cap['profile_digest'],'profile_digest')
    targets=json.loads(f['targets_body']);R.require(P.digest(f['targets_body'])==context['target_manifest_digest'],'target_inventory')
    aliases=[t['controller_id'] for t in targets];R.require(len(aliases)==len(set(aliases))<=256,'target_aliases')
    forecast=context['forecast'];per=B.cost(profile,forecast);charge={k:str(int(v)*int(profile['episodes'])) for k,v in per.items()}
    for v in charge.values():u20(v)
    R.require(int(forecast['runs'])>=1 and int(forecast['preparations'])>=len(targets) and int(forecast['controller_targets'])>=len(targets),'understated_forecast')
    op=request['operation_id'];generation=P.inc(r['arm_generation']);run_after=P.inc(r['revision']);slot_after=P.inc(s['revision']);raw=P.canonical(request)
    scope=P.rows(db,'SELECT * FROM storage_scope')[0]
    binding=dict(scope=dict(authority_service_id=scope['authority_id'],database_instance_id=scope['database_id']),run_id=r['run_id'],generation=generation,operation_id=op,
        artifact_digest=f['artifact_digest'],inventory_digest=context['inventory_digest'],profile_id=profile['profile_id'],profile_revision=profile['revision'],profile_digest=cap['profile_digest'],forecast=forecast)
    ticket=dict(reservation_id='budget.'+B.digest(binding).split(':',1)[1],binding=binding,binding_digest=B.digest(binding),per_episode=per,
        held=charge,spent=B.vector(),episodes_left=profile['episodes'],state='held');B.validate('Reservation',ticket)
    steps=[I('arm_operation',operation_id=op,run_id=r['run_id'],preflight_id=f['preflight_id'],request_epoch=request['request_epoch'],actor_body=P.canonical(request['actor']),
        idempotency_key=request['idempotency_key'],request_digest=P.digest(raw),request_body=raw,run_before=r['revision'],run_after=run_after,slot_before=s['revision'],slot_after=slot_after,
        generation_before=r['arm_generation'],generation=generation,clock_body=context['clock_body'],now_tick=context['now_tick'],target_count=len(targets)),
      I('arm_budget_reservation',operation_id=op,profile_digest=cap['profile_digest'],**{k:int(v) for k,v in charge.items()},budget_body=P.canonical(ticket),audit_body=P.canonical(dict(operation_id=op))),
      ('UPDATE arm_preflight SET consumed_operation_id=? WHERE preflight_id=?',(op,f['preflight_id'])),
      ('UPDATE run SET revision=?,arm_generation=?,active_operation_id=? WHERE run_id=? AND revision=?',(run_after,generation,op,r['run_id'],r['revision'])),
      ('UPDATE activation_slot SET revision=?,active_run_id=?,version=? WHERE definition_id=? AND revision=?',(slot_after,r['run_id'],r['version'],r['definition_id'],s['revision']))]
    seq=db.execute('SELECT coalesce(max(sequence),0)+1 FROM p1_preparation').fetchone()[0];manifest=[]
    for i,t in enumerate(targets):
        request_body=P.canonical(t['request_body']);pb=dict(controller_scope=t['controller_scope'],origin_scope=binding['scope'],preparation_id=t['preparation_id'],
            run_id=r['run_id'],generation=generation,mode='arm',execution_id=None,request_digest=P.digest(request_body))
        manifest.append(dict(registration_id=t['registration_id'],binding=pb))
        steps += [I('arm_target',operation_id=op,controller_id=t['controller_id'],registration_id=t['registration_id'],target_body=P.canonical(t)),
          I('p1_preparation',registration_id=t['registration_id'],sequence=seq+i,run_id=r['run_id'],generation=generation,
            controller_authority=t['controller_scope']['authority_service_id'],controller_database=t['controller_scope']['database_instance_id'],preparation_id=t['preparation_id'],
            mode='arm',execution_id=None,request_digest=pb['request_digest'],recovery_operation_id=None,recovery_controller_id=None,arm_operation_id=op,arm_controller_id=t['controller_id'],
            binding_body=P.canonical(pb),request_body=request_body,outbox_body=P.canonical(dict(kind='prepare_original_request',registration_id=t['registration_id'])),audit_body=P.canonical(dict(operation_id=op)))]
    steps.append(I('arm_register_commit',operation_id=op,manifest_body=P.canonical(manifest),audit_body=P.canonical(dict(operation_id=op)),notification_body=P.canonical(dict(kind='arm_accepted',operation_id=op))))
    return steps
def apply(db,builder,fail_after=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        steps=builder()
        for i,(sql,args) in enumerate(steps):
            db.execute(sql,args)
            if i==fail_after:raise RuntimeError('injected')
        db.commit();return len(steps)
    except BaseException:db.rollback();raise
def reserve(db,request,context,fail_after=None):
    R.require(context['authorized'],'unqualified_context')
    raw=P.canonical(request);found=[]
    def builder():
        prior=db.execute('SELECT operation_id,request_digest FROM arm_operation WHERE operation_id=? OR(request_epoch=? AND actor_body=? AND idempotency_key=?)',
            (request['operation_id'],request['request_epoch'],P.canonical(request['actor']),request['idempotency_key'])).fetchall()
        if prior:
            R.require(len(prior)==1 and tuple(prior[0])==(request['operation_id'],P.digest(raw)),'identity_conflict');found.append(True);return []
        return reserve_steps(db,request,context)
    apply(db,builder,fail_after);return 'existing' if found else 'accepted'
def attempt_step(db,registration_id):
    p=R.one(db,'p1_preparation','registration_id',registration_id)
    return I('arm_attempt',registration_id=registration_id,attempt_id=registration_id+'.attempt',binding_body=p['binding_body'],runtime_body=b'synthetic-runtime',audit_body=P.canonical(dict(registration_id=registration_id)))
def adoption_steps(db,ident,value,controller):
    Q.O.validate(value);R.require(value['state']=='applied' and controller==value['binding']['controller_scope'],'receipt_context')
    p=R.one(db,'p1_preparation','registration_id',ident);R.require(p['binding_body']==P.canonical(value['binding']),'receipt_binding')
    ref=ident+'.receipt';raw=P.canonical(value);prior=db.execute('SELECT body FROM external_evidence WHERE evidence_id=?',(ref,)).fetchone()
    if prior:
        R.require(prior[0]==raw,'receipt_conflict')
        if db.execute('SELECT 1 FROM arm_receipt WHERE registration_id=?',(ident,)).fetchone():return []
    steps=[] if prior else [I('external_evidence',evidence_id=ref,authority_id=p['controller_authority'],database_id=p['controller_database'],kind='preparation',object_id=value['applied_receipt_ref']['id'],
        revision=value['preparation_revision'],digest=value['observation_digest'],body=raw)]
    return steps+[I('arm_receipt',registration_id=ident,evidence_id=ref,audit_body=P.canonical(dict(registration_id=ident)))]
def receive(db,ident,value,controller,fail_after=None):return Q.receive(db,ident,value,controller,fail_after=fail_after,adopt=adoption_steps)
def complete_steps(db,op,context):
    R.require(db.in_transaction,'transaction_required');R.require(context['authorized'] and context['human'] and context['current'] and context['inventory_verified'] and context['controller_capacity_verified'],'unqualified_context')
    o=R.one(db,'arm_operation','operation_id',op);r=R.one(db,'run','run_id',o['run_id']);s=R.one(db,'activation_slot','definition_id',r['definition_id'])
    b=R.one(db,'arm_budget_reservation','operation_id',op);ticket=json.loads(b['budget_body'])
    R.require(ticket['binding']['inventory_digest']==context['inventory_digest'],'inventory_changed')
    rev=P.inc(r['revision'])
    return [I('arm_complete',operation_id=op,run_id=r['run_id'],generation=r['arm_generation'],revision_before=r['revision'],revision_after=rev,slot_revision=s['revision'],body=P.canonical(dict(operation_id=op))),
        ("UPDATE run SET revision=?,lifecycle='armed',dispatch_eligible=1,active_operation_id=NULL WHERE run_id=? AND revision=?",(rev,r['run_id'],r['revision'])),
        I('arm_ready_commit',operation_id=op,audit_body=P.canonical(dict(operation_id=op)),notification_body=P.canonical(dict(kind='arm_ready',operation_id=op)))]
