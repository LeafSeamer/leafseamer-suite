"""类型化PLAN/SUBMISSION参考writer。仅设计测试，不调用Controller或设备。"""
import copy,json
import continuation_trigger_model as T
import command_storage_mapping as S
import build_typed_seamer as G
B=S.B;C=T.C;R=T.R;P=T.P;I=T.I;raw=T.raw;need=T.M.require
def apply(db,builder,fail_after=None):
    need(db.execute('PRAGMA foreign_keys').fetchone()[0]==1,'foreign_keys_required')
    db.execute('BEGIN IMMEDIATE')
    try:
        writes=builder()
        for n,(sql,args) in enumerate(writes):
            db.execute(sql,args)
            if fail_after==n:raise RuntimeError('injected')
        # 离线参考防线。生产库须另验该SQLite版本的延迟外键提交行为及检查成本。
        need(not db.execute('PRAGMA foreign_key_check').fetchone(),'foreign_key_check_failed')
        db.commit()
    except BaseException:db.rollback();raise
def ref(kind,scope,ident,digest):return dict(kind=kind,scope=scope,object_id=ident,revision='1',digest=digest)
def originals(db,run,generation):
    q=json.loads(P.rows(db,'SELECT request_body FROM rc_request WHERE run_id=? AND generation=?',(run,generation))[0]['request_body'])
    a=json.loads(R.one(db,'rc_adoption','transfer_id',q['transfer_id'])['adoption_body'])
    rs=[json.loads(r['receipt_body']) for r in P.rows(db,'SELECT receipt_body FROM rc_receipt WHERE transfer_id=?',(q['transfer_id'],))]
    rs.sort(key=lambda r:T.M.scope_key(r['controller_scope']));return q,a,rs
def ingress_steps(db,event,ctx):
    need(db.in_transaction,'transaction_required');writes=T.ingress_steps(db,event,ctx)
    values=[T.inserted(*w) for w in writes];bytable={}
    for table,v in values:
        if table:bytable.setdefault(table,[]).append(v)
    replacements={};sources={}
    for e in bytable.get('execution',[]):
        q,a,rs=originals(db,e['run_id'],e['arm_generation']);scope=q['origin_scope'];program=ctx['typed_programs'][e['run_id']]
        need(ctx['program_current'] and ctx['clock_current'],'typed_plan_provider')
        listener=R.one(db,'ingress_listener','run_id',e['run_id'])
        need(program['artifact_ref']['digest']==listener['artifact_digest'],'artifact_original')
        plan=next(p for p in bytable['execution_plan_set'] if p['execution_id']==e['execution_id'])
        steps=json.loads(plan['plan_body'])['steps']
        params={p['step_id']:p['request']['parameters'] for p in steps}
        pblob=raw(params);pref=ref('resolved_parameters',scope,e['execution_id']+'.parameters',P.digest(pblob))
        decision=next(p for p in bytable['ingress_decision'] if p['execution_id']==e['execution_id'])
        snap=next(p for p in bytable['ingress_snapshot'] if p['snapshot_id']==decision['snapshot_id'])
        iref=ref('input_snapshot',scope,snap['snapshot_id'],snap['digest'])
        base=dict(scope=scope,execution_id=e['execution_id'],run_id=e['run_id'],artifact_ref=program['artifact_ref'],
            origin=dict(kind='trigger',decision_id=decision['decision_id'],decision_digest=decision['digest']),arm_generation=e['arm_generation'],
            source_state=None if e['kind']=='rule' else dict(state_id=e['source_state_id'],revision=e['source_state_revision']),target_state_id=e['target_state_id'],
            input_snapshot_ref=iref,resolved_parameters_ref=pref,grants=[],clock=ctx['clock'],plan_digest=plan['plan_digest'])
        binding=B.execution(base,q,a,rs);replacements[e['execution_id']]=dict(e,typed_source_id=e['execution_id'],binding_body=raw(binding),binding_digest=binding['binding_digest'])
        sources[e['execution_id']]=I('typed_execution_source',execution_id=e['execution_id'],snapshot_id=snap['snapshot_id'],definition_version=R.one(db,'run','run_id',e['run_id'])['version'],
            artifact_ref_body=raw(program['artifact_ref']),input_ref_body=raw(iref),parameters_ref_body=raw(pref),parameters_body=pblob,clock_body=raw(ctx['clock']))
    result=[]
    for w,(table,v) in zip(writes,values):
        if table=='execution':result += [I('execution',**replacements[v['execution_id']]),sources[v['execution_id']]]
        else:result.append(w)
    return result
def receive_event(db,event,ctx,fail_after=None):
    need(ctx['authorized'] and ctx['source_authenticated'],'source_authority');existing=[]
    def builder():
        old=P.rows(db,'SELECT * FROM ingress_inbox WHERE source_id=? AND(event_id=? OR source_sequence=?)',(event['source_id'],event['event_id'],event['source_sequence']))
        if old:need(len(old)==1 and old[0]['content_body']==raw(event),'event_conflict');existing.append(True);return []
        return ingress_steps(db,event,ctx)
    apply(db,builder,fail_after);return 'existing' if existing else 'accepted'
def submit_steps(db,execution,step,ctx):
    need(db.in_transaction and ctx['namespace_current'],'namespace_current')
    writes=T.F.submit_steps(db,execution,step,ctx)
    e=R.one(db,'execution','execution_id',execution);binding=json.loads(e['binding_body'])
    source=R.one(db,'typed_execution_source','execution_id',execution)
    need(ctx['clock_current'] and ctx['clock']==binding['clock'],'clock_domain_changed')
    plan=P.rows(db,'SELECT * FROM execution_step_plan WHERE execution_id=? AND step_id=?',(execution,step))[0];fixed=json.loads(plan['plan_body'])
    request=copy.deepcopy(fixed['request']);request.pop('continuation')
    need(set(request)=={'device_id','action_id','capability_version','parameters','expected_control','required_completion','preconditions','dispatch','evidence_timeout_ms'},'fixed_request_fields')
    need(request['parameters']==json.loads(source['parameters_body'])[step],'parameter_snapshot')
    selected=[x for x in binding['continuations'] if x['controller_scope']==fixed['controller_scope']];need(len(selected)==1,'controller_target');selected=selected[0]
    grant=selected['selection']['grant_ref'];ns=ctx['command_namespace'];key_id='cmd_'+T.M.digest(dict(execution_id=execution,step_id=step)).split(':')[1]
    ab=dict(binding_version=B.G.VERSION,authorization_mode='continuation',continuation=selected['selection'],origin_scope=binding['scope'],run_id=e['run_id'],
        definition_version=source['definition_version'],arm_generation=e['arm_generation'],execution_id=execution,execution_binding_ref=B.eref(binding),step_id=step,logical_action_id=fixed['logical_action_id'])
    rb=dict(run_id=e['run_id'],definition_version=ab['definition_version'],grant_id=grant['id'],grant_revision=grant['revision'],arm_generation=e['arm_generation'],step_id=step,logical_action_id=ab['logical_action_id'])
    request.update(context_id=ns['context_id'],idempotency_key=key_id,origin='automation',run_binding=rb,automation_binding=ab)
    key=dict(target_scope=fixed['controller_scope'],**{k:ns[k] for k in ('issuer_id','issuer_epoch','principal_id','request_epoch')},operation_id='createCommand',idempotency_key=key_id)
    S.validate('CommandRequest',request);S.validate('RequestKey',key);q,a,rs=originals(db,e['run_id'],e['arm_generation']);out=[]
    for w in writes:
        table,v=T.inserted(*w)
        if table=='command_submission':
            v.update(**{k:key[k] for k in ('issuer_id','issuer_epoch','principal_id','request_epoch','operation_id','idempotency_key')},
                request_key_body=raw(key),request_body=raw(request),request_digest=T.M.digest(B.content(request)))
            rows=dict(execution=e,submission=v,scope=q['origin_scope'],decision=R.one(db,'ingress_decision','execution_id',execution),
                plan=R.one(db,'execution_plan_set','execution_id',execution),transfer=q,adoption=a,receipts=rs)
            S.verify_originals(binding,request,key,rows);out.append(I(table,**v))
        else:out.append(w)
    return out
def submit(db,execution,step,ctx,fail_after=None):
    need(ctx['authorized'],'current_authority');old=[]
    def builder():
        rows=P.rows(db,'SELECT * FROM command_submission WHERE execution_id=? AND step_id=?',(execution,step))
        if rows:
            need(all(rows[0][k]==ctx['command_namespace'][k] for k in ('issuer_id','issuer_epoch','principal_id','request_epoch')),'historical_namespace_owner')
            old.append(rows[0]['submission_id']);return []
        return submit_steps(db,execution,step,ctx)
    apply(db,builder,fail_after)
    return 'existing' if old else 'accepted'
