"""普通触发至R5的同库参考写集；求值、授权、时钟和完成证据均为显式外部输入。"""
import json
import build_trigger_flow as G
import arm_storage_model as A
P=A.P;R=A.R;I=A.I
def event(db,run,phase,identity):return R.event(identity,run,phase)
def step(db,execution,ident):
    values=P.rows(db,'SELECT * FROM step_state WHERE execution_id=? AND step_id=?',(execution,ident));R.require(len(values)==1,'step_missing');return values[0]
def digest(value):return P.digest(P.canonical(value))
def gate(db,execution,ctx,writing=False):
    R.require(db.in_transaction,'transaction_required');e=R.one(db,'execution','execution_id',execution);r=R.one(db,'run','run_id',e['run_id'])
    R.require(ctx['authorized'] and ctx['current'] and ctx['runtime_current'],'current_authority')
    R.require(r['active_execution_id']==execution and r['lifecycle']=='running' and e['state']=='running' and r['arm_generation']==e['arm_generation'],'execution_current')
    R.require(not db.execute('SELECT 1 FROM pause_latch WHERE run_id=? AND cleared_start_id IS NULL',(r['run_id'],)).fetchone(),'pause_latch')
    R.require(not db.execute("SELECT 1 FROM step_state s JOIN execution_step_plan p USING(execution_id,step_id) WHERE s.execution_id=? AND (s.outcome IN ('unknown','blocked','expired','cancelled') OR(p.required=1 AND s.outcome='failed'))",(execution,)).fetchone(),'step_failure_protected')
    if writing:R.require(r['dispatch_eligible']==1 and ctx['budget_valid'] and ctx['window_valid'] and ctx['parameters_verified'],'write_gate')
    return e,r

def ingress_steps(db,request,ctx):
    R.require(db.in_transaction,'transaction_required');R.require(ctx['authorized'] and ctx['source_authenticated'] and ctx['age_verified'],'source_authority')
    A.u20(request['source_sequence']);src=R.one(db,'ingress_source','source_id',request['source_id'])
    R.require(src['state']=='synchronized' and request['source_sequence']==P.inc(src['contiguous_sequence']),'source_frontier')
    epoch=P.rows(db,"SELECT * FROM ingest_epoch WHERE state='open'")[0];seq=P.inc(epoch['last_sequence'])
    registry=R.one(db,'ingress_registry','source_id',request['source_id']);listeners=P.rows(db,'SELECT * FROM ingress_listener WHERE source_id=? ORDER BY run_id',(request['source_id'],))
    R.require({x['run_id'] for x in listeners}==set(ctx['evaluations']),'complete_match_set')
    raw=P.canonical(request);key=digest(request).split(':',1)[1];inbox='inbox.'+key;commit='ingress.'+key
    source_after=P.inc(src['revision']);plans=[];decisions=[]
    for n,l in enumerate(listeners):
        r=R.one(db,'run','run_id',l['run_id']);slot=R.one(db,'activation_slot','definition_id',r['definition_id']);progress=R.one(db,'run_ingest_progress','run_id',r['run_id'])
        value=ctx['evaluations'][r['run_id']];R.require(value['qualified'],'evaluation_unqualified')
        result='suppressed_busy' if r['active_execution_id'] or r['active_operation_id'] else 'suppressed_inactive' if r['lifecycle']!='armed' or not r['dispatch_eligible'] else 'accepted' if value['matched'] else 'no_match'
        accepted=result=='accepted';after=P.inc(r['revision']) if accepted else r['revision'];post_progress=P.inc(progress['revision'])
        did='decision.'+key+'.'+str(n);sid='snapshot.'+key+'.'+str(n);eid='execution.'+key+'.'+str(n) if accepted else None
        snap=dict(flow_version=G.VERSION,run_id=r['run_id'],run_revision=r['revision'],generation=r['arm_generation'],
            slot_revision_before=slot['revision'],slot_revision_after=P.inc(slot['revision']) if accepted else slot['revision'],input=request['payload'])
        decision=dict(decision_id=did,result=result,run_id=r['run_id'],execution_id=eid,run_before=r['revision'],run_after=after,receive_sequence=seq)
        dblob=P.canonical(decision);decisions.append(dict(run_id=r['run_id'],decision_id=did,decision_digest=P.digest(dblob)))
        writes=[I('ingress_target',commit_id=commit,run_id=r['run_id'],artifact_digest=l['artifact_digest'],binding_body=l['binding_body'],decision_id=did)]
        snapshot=result in ('accepted','no_match')
        if snapshot:writes.append(I('ingress_snapshot',snapshot_id=sid,commit_id=commit,run_id=r['run_id'],digest=digest(snap),body=P.canonical(snap)))
        writes.append(I('ingress_decision',decision_id=did,commit_id=commit,run_id=r['run_id'],inbox_id=inbox,result=result,snapshot_id=sid if snapshot else None,
            execution_id=eid,digest=P.digest(dblob),body=dblob,run_before=r['revision'],run_after=after,progress_before=progress['revision'],progress_after=post_progress))
        if accepted:
            R.require(ctx['current'] and ctx['plan_verified'],'plan_authority');steps=value['steps'];R.require(len(steps)<=4096 and len({x['step_id'] for x in steps})==len(steps),'plan_steps')
            state=P.rows(db,'SELECT * FROM business_state WHERE run_id=?',(r['run_id'],));state=state[0] if state else None
            plan=P.canonical(dict(steps=steps));binding=P.canonical(dict(decision=decision,artifact_digest=l['artifact_digest'],plan_digest=P.digest(plan)))
            writes += [I('ingress_execution',execution_id=eid,run_id=r['run_id'],decision_id=did),
                I('execution',execution_id=eid,run_id=r['run_id'],origin_kind='trigger',trigger_decision_ref_body=P.canonical(dict(id=did,digest=P.digest(dblob))),
                  arm_generation=r['arm_generation'],binding_digest=P.digest(binding),plan_digest=P.digest(plan),binding_body=binding,
                  kind='state_machine' if state else 'rule',source_state_id=state['state_id'] if state else None,source_state_revision=state['revision'] if state else None,
                  target_state_id=value['target_state_id'] if state else None,state='prepared')]
            writes += event(db,r['run_id'],'PLAN',eid)
            writes.append(I('execution_plan_set',execution_id=eid,run_id=r['run_id'],expected_steps=len(steps),plan_digest=P.digest(plan),plan_body=plan,sealed=0,tx_id=eid+'.PLAN'))
            for ordinal,s in enumerate(steps):
                writes += [I('execution_step_plan',execution_id=eid,step_id=s['step_id'],kind='action',ordinal=ordinal,required=int(s['required']),plan_digest=digest(s),plan_body=P.canonical(s)),
                    I('step_state',execution_id=eid,step_id=s['step_id'],revision='0',state='waiting',outcome='pending')]
            writes += [('UPDATE execution_plan_set SET sealed=1 WHERE execution_id=?',(eid,)),("UPDATE execution SET state='running' WHERE execution_id=?",(eid,)),
                ("UPDATE run SET revision=?,lifecycle='running',active_execution_id=? WHERE run_id=? AND revision=?",(after,eid,r['run_id'],r['revision'])),
                ('UPDATE activation_slot SET revision=? WHERE definition_id=? AND revision=?',(snap['slot_revision_after'],r['definition_id'],slot['revision']))]
        writes += [('UPDATE run_ingest_progress SET revision=?,last_sequence=?,last_commit_id=? WHERE run_id=? AND revision=?',(post_progress,seq,commit,r['run_id'],progress['revision'])),
            I('ingress_run_audit',commit_id=commit,run_id=r['run_id'],phase='INGRESS_RUN',audit_body=dblob,event_body=dblob)]
        plans+=writes
    body=P.canonical(dict(decisions=decisions,inbox_id=inbox,receive_sequence=seq))
    return [I('ingress_inbox',inbox_id=inbox,source_id=request['source_id'],event_id=request['event_id'],source_sequence=request['source_sequence'],origin_digest=P.digest(raw),
            content_body=raw,first_observation_body=P.canonical(ctx['first_observation']),observed_only=0),
        I('ingress_commit',commit_id=commit,inbox_id=inbox,epoch=epoch['epoch'],receive_sequence=seq,registry_revision=registry['revision'],source_revision_before=src['revision'],
            source_revision_after=source_after,expected_targets=len(listeners),decision_set_digest=digest(decisions),body=body,notification_id=commit+'.event',sealed=0)]+plans+[
        ('UPDATE ingress_source SET revision=?,contiguous_sequence=? WHERE source_id=?',(source_after,request['source_sequence'],request['source_id'])),
        ('UPDATE ingest_epoch SET last_sequence=? WHERE epoch=?',(seq,epoch['epoch'])),('UPDATE ingress_inbox SET commit_id=? WHERE inbox_id=?',(commit,inbox)),
        I('ingress_notification',notification_id=commit+'.event',commit_id=commit,payload_body=body),
        I('ingress_charge',commit_id=commit,profile_body=P.canonical(dict(kind='synthetic_profile')),charge_body=P.canonical(dict(target_count=len(listeners)))),
        ('UPDATE ingress_commit SET sealed=1 WHERE commit_id=?',(commit,))]

def receive_event(db,request,ctx,fail_after=None):
    R.require(ctx['authorized'] and ctx['source_authenticated'],'source_authority');found=[]
    def builder():
        rows=P.rows(db,'SELECT origin_digest,content_body FROM ingress_inbox WHERE source_id=? AND(event_id=? OR source_sequence=?)',(request['source_id'],request['event_id'],request['source_sequence']))
        if rows:R.require(len(rows)==1 and rows[0]['content_body']==P.canonical(request) and rows[0]['origin_digest']==digest(request),'event_conflict');found.append(True);return []
        return ingress_steps(db,request,ctx)
    A.apply(db,builder,fail_after);return 'duplicate' if found else 'committed'

def anchor_steps(db,execution,ctx):
    e,r=gate(db,execution,ctx);R.require(ctx['origin_commit_observed'],'origin_commit_unconfirmed');A.u20(ctx['tick'])
    ident=execution+'.anchor';body=P.canonical(dict(execution_id=execution,clock=ctx['clock'],tick=ctx['tick']))
    return event(db,r['run_id'],'ANCHOR',ident)+[I('execution_anchor',anchor_id=ident,execution_id=execution,run_id=r['run_id'],origin_kind=e['origin_kind'],
        start_id=e['start_id'],trigger_decision_ref_body=e['trigger_decision_ref_body'],clock_body=P.canonical(ctx['clock']),tick_ns=ctx['tick'],anchor_digest=P.digest(body),anchor_body=body,tx_id=ident+'.ANCHOR')]

def ready_steps(db,execution,step_id,ctx):
    e,r=gate(db,execution,ctx);st=step(db,execution,step_id);R.require(st['state']=='waiting' and ctx['dependencies_verified'],'step_not_ready')
    plan=P.rows(db,'SELECT * FROM execution_step_plan WHERE execution_id=? AND step_id=?',(execution,step_id))[0]
    ident=execution+'.'+step_id+'.ready';body=P.canonical(dict(step_id=step_id,dependencies=[]))
    return event(db,r['run_id'],'READY',ident)+[I('step_ready',ready_id=ident,execution_id=execution,step_id=step_id,run_id=r['run_id'],plan_digest=plan['plan_digest'],anchor_id=execution+'.anchor',
        clock_body=P.canonical(ctx['clock']),tick_ns=ctx['tick'],dependencies_digest=P.digest(body),dependencies_body=body,ready_digest=P.digest(body),ready_body=body,tx_id=ident+'.READY'),
        ("UPDATE step_state SET ready_id=?,state='ready',revision=? WHERE execution_id=? AND step_id=?",(ident,P.inc(st['revision']),execution,step_id))]

def submit_steps(db,execution,step_id,ctx):
    e,r=gate(db,execution,ctx,True);st=step(db,execution,step_id);R.require(st['state']=='ready','step_not_ready')
    plan=json.loads(db.execute('SELECT plan_body FROM execution_step_plan WHERE execution_id=? AND step_id=?',(execution,step_id)).fetchone()[0])
    ident=execution+'.'+step_id+'.submission';body=P.canonical(plan['request']);scope=plan['controller_scope']
    return event(db,r['run_id'],'SUBMISSION',ident)+[I('command_submission',submission_id=ident,execution_id=execution,step_id=step_id,run_id=r['run_id'],
        target_authority=scope['authority_service_id'],target_database=scope['database_instance_id'],issuer_id='synthetic.issuer',principal_id='operator',request_epoch='flow.epoch',operation_id='createCommand',
        idempotency_key=digest(dict(execution_id=execution,step_id=step_id)),request_digest=P.digest(body),request_body=body,parameters_ref_body=P.canonical(plan['parameters_ref']),state='planned',tx_id=ident+'.SUBMISSION'),
        ("UPDATE step_state SET revision=?,state='submission_pending',submission_id=? WHERE execution_id=? AND step_id=?",(P.inc(st['revision']),ident,execution,step_id))]

def attempt(db,submission,ctx,fail_after=None):
    R.require(ctx['authorized'],'current_authority')
    fresh=[]
    def builder():
        s=R.one(db,'command_submission','submission_id',submission)
        if s['state']!='planned':return []
        e,r=gate(db,s['execution_id'],ctx,True);ident=submission+'.attempt';fresh.append(True)
        return event(db,r['run_id'],'ATTEMPT',ident)+[I('submission_attempt',attempt_id=ident,submission_id=submission,run_id=r['run_id'],runtime_binding_ref_body=P.canonical(ctx['runtime']),
            clock_body=P.canonical(ctx['clock']),tick_ns=ctx['tick'],attempt_body=P.canonical(dict(submission_id=submission)),tx_id=ident+'.ATTEMPT'),
            ("UPDATE command_submission SET state='attempt_recorded',attempt_id=? WHERE submission_id=?",(ident,submission))]
    A.apply(db,builder,fail_after);return 'live_path_call_once' if fresh else 'query_original_identity_only'

def receipt(db,submission):
    s=R.one(db,'command_submission','submission_id',submission);scope=dict(authority_service_id=s['target_authority'],database_instance_id=s['target_database'])
    return dict(submission_id=submission,request_digest=s['request_digest'],scope=scope,command_ref=dict(scope=scope,id='command.'+digest(submission).split(':',1)[1],revision='1',digest=digest(submission)),result='accepted')

def accept_steps(db,submission,value,ctx):
    R.require(db.in_transaction,'transaction_required')
    R.require(ctx['receipt_verified'] and ctx['receipt_durable'],'receipt_unqualified');s=R.one(db,'command_submission','submission_id',submission)
    R.require(value==receipt(db,submission),'receipt_binding');R.require(s['state'] in ('attempt_recorded','indeterminate'),'not_attempted')
    ident=submission+'.accepted';body=P.canonical(value);st=step(db,s['execution_id'],s['step_id'])
    writes=event(db,s['run_id'],'ADJUDICATION',ident)+[I('submission_adjudication',adjudication_id=ident,submission_id=submission,run_id=s['run_id'],target_authority=s['target_authority'],target_database=s['target_database'],
        request_digest=s['request_digest'],outcome='accepted',command_ref_body=P.canonical(value['command_ref']),receipt_ref_body=P.canonical(dict(id=ident,scope=value['scope'])),receipt_body=body,tx_id=ident+'.ADJUDICATION'),
        ("UPDATE command_submission SET state='accepted',adjudication_id=? WHERE submission_id=?",(ident,submission))]
    if st['outcome']=='pending':writes.append(("UPDATE step_state SET revision=?,state='accepted' WHERE execution_id=? AND step_id=?",(P.inc(st['revision']),s['execution_id'],s['step_id'])))
    return writes

def terminal_steps(db,execution,step_id,outcome,ctx):
    R.require(db.in_transaction,'transaction_required')
    R.require(ctx['terminal_evidence_verified'],'terminal_unqualified');st=step(db,execution,step_id);e=R.one(db,'execution','execution_id',execution);R.require(st['outcome']=='pending','terminal_already_fixed')
    if outcome=='succeeded':
        accepted=P.rows(db,'SELECT * FROM submission_adjudication WHERE submission_id=?',(st['submission_id'],))
        R.require(ctx['completion_verified'] and len(accepted)==1 and accepted[0]['command_ref_body']==P.canonical(ctx['completion_command_ref']),'completion_binding')
    ident=execution+'.'+step_id+'.terminal';body=P.canonical(dict(outcome=outcome,completion_ref=ctx.get('completion_command_ref')))
    state='indeterminate' if outcome=='unknown' else 'cancelled' if outcome=='cancelled' else 'finished'
    writes=event(db,e['run_id'],'STEP_TERMINAL',ident)+[I('step_terminal',terminal_id=ident,execution_id=execution,step_id=step_id,run_id=e['run_id'],outcome=outcome,
        evidence_body=body,result_ref_body=P.canonical(ctx['completion_command_ref']) if outcome=='succeeded' else None,tx_id=ident+'.STEP_TERMINAL'),
        ('UPDATE step_state SET revision=?,state=?,outcome=?,terminal_id=? WHERE execution_id=? AND step_id=?',(P.inc(st['revision']),state,outcome,ident,execution,step_id))]
    required=db.execute('SELECT required FROM execution_step_plan WHERE execution_id=? AND step_id=?',(execution,step_id)).fetchone()[0]
    if outcome!='succeeded' and (required or outcome!='failed'):
        r=R.one(db,'run','run_id',e['run_id'])
        if r['active_execution_id']==execution and r['arm_generation']==e['arm_generation'] and r['lifecycle']!='completed':
            rev=P.inc(r['revision'])
            writes += [("UPDATE run SET revision=?,lifecycle='paused',dispatch_eligible=0 WHERE run_id=? AND revision=?",(rev,r['run_id'],r['revision'])),
                I('pause_latch',latch_id=ident+'.latch',run_id=r['run_id'],reason='step_terminal_failure',created_revision=rev,body=body)]
        if e['state'] in ('prepared','running','paused'):
            writes.append(('UPDATE execution SET state=? WHERE execution_id=?',('unknown' if outcome=='unknown' else 'failed' if outcome=='failed' else 'paused',execution)))
    return writes

def finish_steps(db,execution,ctx):
    e,r=gate(db,execution,ctx);R.require(ctx['required_evidence'] and ctx['no_unresolved'],'commit_evidence')
    R.require(e['origin_kind']=='trigger','use_recovery_protocol')
    slot=R.one(db,'activation_slot','definition_id',r['definition_id']);state=P.rows(db,'SELECT * FROM business_state WHERE run_id=?',(r['run_id'],));state=state[0] if state else None
    if e['kind']=='state_machine':R.require(state and (state['state_id'],state['revision'])==(e['source_state_id'],e['source_state_revision']),'state_cas')
    ident=execution+'.commit';rev=P.inc(r['revision']);body=P.canonical(dict(execution_id=execution,run_id=r['run_id'],run_revision_after=rev))
    writes=event(db,r['run_id'],'R5',ident)+[I('transition_commit',commit_id=ident,run_id=r['run_id'],execution_id=execution,kind=e['kind'],
        source_state_id=e['source_state_id'],source_state_revision=e['source_state_revision'],target_state_id=e['target_state_id'],target_state_revision=P.inc(state['revision']) if state else None,
        evidence_set_body=P.canonical([dict(x) for x in db.execute('SELECT step_id,outcome,terminal_id FROM step_state WHERE execution_id=? ORDER BY step_id',(execution,))]),
        commit_body=body,commit_digest=P.digest(body),tx_id=ident+'.R5',run_revision_before=r['revision'],run_revision_after=rev,slot_revision=slot['revision']),
        ("UPDATE execution SET state='succeeded',commit_id=? WHERE execution_id=?",(ident,execution))]
    if state:writes.append(('UPDATE business_state SET state_id=?,revision=?,last_commit_id=? WHERE run_id=? AND revision=?',(e['target_state_id'],P.inc(state['revision']),ident,r['run_id'],state['revision'])))
    writes += [("UPDATE run SET lifecycle='armed',revision=?,active_execution_id=NULL,dispatch_eligible=1,last_commit_id=? WHERE run_id=? AND revision=?",(rev,ident,r['run_id'],r['revision'])),
        I('flow_commit_seal',commit_id=ident,audit_body=body,notification_body=P.canonical(dict(kind='transition_committed',commit_id=ident)))]
    return writes

def finish(db,execution,ctx,fail_after=None):
    R.require(ctx['authorized'],'current_authority');found=[]
    def builder():
        e=R.one(db,'execution','execution_id',execution)
        if e['commit_id']:R.one(db,'flow_commit_seal','commit_id',e['commit_id']);found.append(True);return []
        return finish_steps(db,execution,ctx)
    A.apply(db,builder,fail_after);return 'existing' if found else 'committed'
