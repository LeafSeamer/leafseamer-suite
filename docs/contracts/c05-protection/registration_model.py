"""恢复准备的固定离线写集；gate参数为合成可信上下文，不是产品鉴权或网络发送器。"""
import json
import storage_model as P


def require(ok,reason):
    if not ok:raise ValueError(reason)
def one(db,table,key,value):
    values=P.rows(db,f'SELECT * FROM {table} WHERE {key}=?',(value,));require(len(values)==1,'missing_original');return values[0]
def event(operation,run,phase):
    tx=operation+'.'+phase
    return [P.row('transaction_record',tx_id=tx,run_id=run,phase=phase,business_id=operation,audit_body=P.canonical(dict(operation_id=operation,phase=phase)),event_id=tx+'.event'),
      P.row('event_outbox',event_id=tx+'.event',tx_id=tx,payload_digest=P.digest(P.canonical(dict(operation_id=operation,phase=phase))),payload_body=P.canonical(dict(operation_id=operation,phase=phase)))]


def reserve_steps(db,request,gates):
    require(db.in_transaction,'transaction_required')
    require(gates['authorized'] and gates['current'] and gates['old_resources_clear'],'unqualified_context')
    r=one(db,'run','run_id',request['run_id']);p=one(db,'recovery_preview','preview_id',request['preview_id'])
    s=one(db,'activation_slot','definition_id',r['definition_id']);scope=P.rows(db,'SELECT * FROM storage_scope')[0]
    require(r['lifecycle']=='paused' and r['active_operation_id'] is None,'recovery_busy')
    require(p['run_id']==r['run_id'] and p['run_revision']==r['revision'] and p['slot_revision']==s['revision'] and p['prior_execution_id']==r['active_execution_id'] and p['consumed_operation_id'] is None,'stale_preview')
    require(s['active_run_id']==r['run_id'] and s['version']==r['version'],'inactive_run')
    require(p['clock_body']==gates['clock_body'] and int(p['issued_tick'])<=gates['now']<int(p['expires_tick']),'preview_time')
    require(request['mode'] in ('execute','reconcile_commit'),'mode')
    generation=P.inc(r['arm_generation']);revision=P.inc(r['revision']);slot_revision=P.inc(s['revision'])
    op=request['operation_id'];ex=request['execution_id'];targets=request['targets'];raw=P.canonical(request)
    aliases=[t['controller_id'] for t in targets]
    require(len(aliases)==len(set(aliases))<=db.execute('SELECT max_targets FROM p1_limit').fetchone()[0],'target_set')
    state=one(db,'business_state','run_id',r['run_id']) if request['kind']=='state_machine' else None
    require(request['kind'] in ('rule','state_machine'),'kind')
    items=event(op,r['run_id'],'R2')
    items.append(P.row('recovery_operation',operation_id=op,run_id=r['run_id'],preview_id=p['preview_id'],execution_id=ex,
      request_epoch=request['request_epoch'],actor_identity=P.canonical(request['actor']),idempotency_key=request['idempotency_key'],
      operation_kind='resumeAutomationRun',request_digest=P.digest(raw),revision='1',state='preparing',mode=request['mode'],
      plan_digest=request['plan_digest'],targets_digest=P.digest(P.canonical(aliases)),targets_body=P.canonical(aliases),
      resolved_latches_body=P.canonical(request['resolved_latches']),start_id=None,tx_id=op+'.R2'))
    items.append(P.row('execution',execution_id=ex,run_id=r['run_id'],recovery_operation_id=op,origin_kind='recovery',trigger_decision_ref_body=None,
      arm_generation=generation,binding_digest=P.digest(raw),plan_digest=request['plan_digest'],binding_body=raw,kind=request['kind'],
      source_state_id=state['state_id'] if state else None,source_state_revision=state['revision'] if state else None,
      target_state_id=request['target_state_id'] if state else None,state='prepared'))
    items.append(P.row('recovery_lock',operation_id=op,run_id=r['run_id'],release_id=None))
    items += [P.row('preparation_target',operation_id=op,controller_id=t['controller_id'],target_digest=P.digest(P.canonical(t)),target_body=P.canonical(t),state='pending') for t in targets]
    items += [('UPDATE recovery_preview SET consumed_operation_id=? WHERE preview_id=? AND consumed_operation_id IS NULL',(op,p['preview_id'])),
      ('UPDATE run SET revision=?,arm_generation=?,active_operation_id=?,active_execution_id=? WHERE run_id=? AND revision=?',(revision,generation,op,ex,r['run_id'],r['revision'])),
      ('UPDATE activation_slot SET revision=? WHERE definition_id=? AND revision=?',(slot_revision,r['definition_id'],s['revision']))]
    nextseq=db.execute('SELECT coalesce(max(sequence),0)+1 FROM p1_preparation').fetchone()[0];manifest=[]
    for i,t in enumerate(targets):
        body=P.canonical(t['request_body']);binding=dict(controller_scope=t['controller_scope'],
          origin_scope=dict(authority_service_id=scope['authority_id'],database_instance_id=scope['database_id']),
          preparation_id=t['preparation_id'],run_id=r['run_id'],generation=generation,mode='recovery',execution_id=ex,request_digest=P.digest(body))
        manifest.append(dict(registration_id=t['registration_id'],binding=binding))
        items.append(P.row('p1_preparation',registration_id=t['registration_id'],sequence=nextseq+i,run_id=r['run_id'],generation=generation,
          controller_authority=t['controller_scope']['authority_service_id'],controller_database=t['controller_scope']['database_instance_id'],
          preparation_id=t['preparation_id'],mode='recovery',execution_id=ex,request_digest=binding['request_digest'],
          recovery_operation_id=op,recovery_controller_id=t['controller_id'],binding_body=P.canonical(binding),request_body=body,
          outbox_body=P.canonical(dict(kind='prepare_original_request',registration_id=t['registration_id'])),audit_body=P.canonical(dict(operation_id=op))))
    body=P.canonical(dict(operation_id=op,run_id=r['run_id'],execution_id=ex,generation=generation,registrations=manifest))
    items.append(P.row('pr_commit',operation_id=op,run_revision=revision,slot_revision=slot_revision,
      dependency_head=db.execute('SELECT coalesce(max(sequence),0) FROM p1_dependency').fetchone()[0],target_count=len(targets),
      manifest_digest=P.digest(body),manifest_body=body,audit_body=P.canonical(dict(operation_id=op,manifest_digest=P.digest(body)))))
    return items


def reserve(db,request,gates):
    require(gates['authorized'],'unqualified_context')
    db.execute('BEGIN IMMEDIATE')
    try:
        prior=db.execute('SELECT operation_id,request_digest FROM recovery_operation WHERE operation_id=? OR (request_epoch=? AND actor_identity=? AND operation_kind=? AND idempotency_key=?)',
          (request['operation_id'],request['request_epoch'],P.canonical(request['actor']),'resumeAutomationRun',request['idempotency_key'])).fetchall()
        if prior:
            require(len(prior)==1 and prior[0][0]==request['operation_id'] and prior[0][1]==P.digest(P.canonical(request)),'identity_conflict')
            result='existing'
        else:
            for sql,args in reserve_steps(db,request,gates):db.execute(sql,args)
            result='accepted'
        db.commit();return result
    except BaseException:db.rollback();raise


def apply(db,builder):
    """正常写入入口在同一写事务中读取原件并构造写集，不跨I/O持有事务。"""
    db.execute('BEGIN IMMEDIATE')
    try:
        items=builder()
        for sql,args in items:db.execute(sql,args)
        db.commit();return len(items)
    except BaseException:db.rollback();raise


def attempt_step(db,registration_id,attempt_id,runtime_body):
    p=one(db,'p1_preparation','registration_id',registration_id)
    return P.row('pr_attempt',registration_id=registration_id,attempt_id=attempt_id,request_digest=p['request_digest'],binding_body=p['binding_body'],runtime_body=runtime_body,
      audit_body=P.canonical(dict(registration_id=registration_id,attempt_id=attempt_id)))


def receipt_steps(db,registration_id,value,authenticated_controller):
    import preparation_delivery_model as PO
    PO.validate(value);require(value['state']=='applied','not_applied')
    require(authenticated_controller==value['binding']['controller_scope'],'authenticated_controller')
    p=one(db,'p1_preparation','registration_id',registration_id)
    require(P.canonical(value['binding'])==p['binding_body'],'receipt_binding')
    ident=registration_id+'.receipt';raw=P.canonical(value);prior=db.execute('SELECT body FROM external_evidence WHERE evidence_id=?',(ident,)).fetchone()
    if prior:
        require(prior[0]==raw,'receipt_conflict')
        if db.execute('SELECT 1 FROM pr_receipt WHERE registration_id=? AND evidence_id=?',(registration_id,ident)).fetchone():return []
    records=[] if prior else [P.row('external_evidence',evidence_id=ident,authority_id=p['controller_authority'],database_id=p['controller_database'],kind='preparation',
      object_id=value['applied_receipt_ref']['id'],revision=value['preparation_revision'],digest=value['observation_digest'],body=raw)]
    return records+[P.row('pr_receipt',registration_id=registration_id,operation_id=p['recovery_operation_id'],controller_id=p['recovery_controller_id'],evidence_id=ident,audit_body=P.canonical(dict(registration_id=registration_id))),
      ("UPDATE preparation_target SET state='applied',receipt_id=? WHERE operation_id=? AND controller_id=?",(ident,p['recovery_operation_id'],p['recovery_controller_id']))]


def ready_steps(db,operation_id):
    o=one(db,'recovery_operation','operation_id',operation_id)
    require(o['state']=='preparing','operation_state')
    require(not db.execute("SELECT 1 FROM preparation_target WHERE operation_id=? AND state!='applied'",(operation_id,)).fetchone(),'incomplete_preparations')
    return [("UPDATE recovery_operation SET state='ready',revision=? WHERE operation_id=?",(P.inc(o['revision']),operation_id))]+event(operation_id,o['run_id'],'R3')


def start_steps(db,operation_id,gates):
    o=one(db,'recovery_operation','operation_id',operation_id);r=one(db,'run','run_id',o['run_id']);s=one(db,'activation_slot','definition_id',r['definition_id'])
    require(gates['authorized'] and gates['current'] and gates['old_resources_clear'],'unqualified_context')
    require(o['state']=='ready' and r['lifecycle']=='paused' and r['active_operation_id']==operation_id and r['active_execution_id']==o['execution_id'],'operation_state')
    latches=sorted(x[0] for x in db.execute('SELECT latch_id FROM pause_latch WHERE run_id=? AND cleared_start_id IS NULL',(r['run_id'],)))
    require(latches==sorted(json.loads(o['resolved_latches_body'])),'new_latch')
    require(not db.execute("SELECT 1 FROM preparation_target WHERE operation_id=? AND state!='applied'",(operation_id,)).fetchone(),'incomplete_preparations')
    start=operation_id+'.start';tx=operation_id+'.R4'
    # R4业务身份必须为start_id，保持旧复合外键，不复用R2操作事件身份。
    items=[P.row('transaction_record',tx_id=tx,run_id=r['run_id'],phase='R4',business_id=start,audit_body=P.canonical(dict(start_id=start)),event_id=tx+'.event'),
      P.row('event_outbox',event_id=tx+'.event',tx_id=tx,payload_digest=P.digest(P.canonical(dict(start_id=start))),payload_body=P.canonical(dict(start_id=start))),
      P.row('execution_start',start_id=start,operation_id=operation_id,run_id=r['run_id'],execution_id=o['execution_id'],mode=o['mode'],
        run_revision_before=r['revision'],run_revision_after=P.inc(r['revision']),slot_revision=s['revision'],operation_revision=o['revision'],start_body=P.canonical(dict(start_id=start)),start_digest=P.digest(P.canonical(dict(start_id=start))),tx_id=tx)]
    items += [('UPDATE pause_latch SET cleared_start_id=? WHERE latch_id=?',(start,l)) for l in latches]
    items += [('UPDATE recovery_operation SET state=?,revision=?,start_id=? WHERE operation_id=?',('running' if o['mode']=='execute' else 'reconciling',P.inc(o['revision']),start,operation_id)),
      ("UPDATE execution SET state='running',start_id=? WHERE execution_id=?",(start,o['execution_id'])),
      ("UPDATE run SET lifecycle='running',revision=?,dispatch_eligible=?,active_operation_id=NULL WHERE run_id=?",(P.inc(r['revision']),int(o['mode']=='execute'),r['run_id']))]
    return items
