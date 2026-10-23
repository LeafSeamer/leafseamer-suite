"""准备观察与资格撤回的离线联接；不执行网络、时钟判定或设备操作。"""
import json
from pathlib import Path
import jsonschema
import preparation_delivery_model as O
import storage_model as P
import registration_model as R
HERE=Path(__file__).resolve().parent
SCHEMA=json.loads((HERE/'preparation-qualification.schema.json').read_bytes())


def seal_withdrawal(value):
    value['withdrawal_digest']=P.digest(P.canonical({k:v for k,v in value.items() if k!='withdrawal_digest'}));return value
def withdrawal_valid(value):
    jsonschema.Draft202012Validator({'$ref':'#/$defs/Withdrawal','$defs':SCHEMA['$defs']}).validate(value)
    R.require(len(P.canonical(value))<=16384,'withdrawal_capacity')
    R.require(value['withdrawal_digest']==P.digest(P.canonical({k:v for k,v in value.items() if k!='withdrawal_digest'})),'withdrawal_digest')


def invalidate_steps(db,registration_id,kind,value):
    R.require(db.in_transaction,'transaction_required')
    p=R.one(db,'p1_preparation','registration_id',registration_id)
    R.require(P.canonical(value['binding'])==p['binding_body'],'qualification_binding')
    if db.execute('SELECT 1 FROM pq_fault WHERE registration_id=?',(registration_id,)).fetchone():return []
    r=R.one(db,'run','run_id',p['run_id']);generation=p['generation'];now=r['arm_generation']
    preparations=[x for x in P.rows(db,'SELECT * FROM p1_preparation WHERE run_id=? ORDER BY registration_id',(r['run_id'],)) if int(x['generation'])<=int(generation)]
    executions=[x for x in P.rows(db,'SELECT * FROM execution WHERE run_id=? ORDER BY execution_id',(r['run_id'],)) if int(x['arm_generation'])<=int(generation)]
    exids={x['execution_id'] for x in executions}
    submissions=[x for x in P.rows(db,'SELECT * FROM command_submission WHERE run_id=? ORDER BY submission_id',(r['run_id'],)) if x['execution_id'] in exids]
    targets=sorted({(x['controller_authority'],x['controller_database']) for x in preparations}|{(x['target_authority'],x['target_database']) for x in submissions})
    members=dict(preparations=[x['registration_id'] for x in preparations],submissions=[x['submission_id'] for x in submissions],
      executions=[dict(execution_id=x['execution_id'],binding_digest=x['binding_digest']) for x in executions])
    plan='pq.'+P.digest(registration_id.encode()).split(':',1)[1];latch=plan+'.latch' if now==generation else None
    revision=P.inc(r['revision']) if now==generation and r['lifecycle']!='completed' else r['revision']
    raw=P.canonical(value);body=P.canonical(dict(registration_id=registration_id,reason=kind,evidence_digest=P.digest(raw),run_id=r['run_id'],generation=generation,members=members,controllers=[list(t) for t in targets]))
    steps=[P.row('pq_fault',registration_id=registration_id,kind=kind,evidence_digest=P.digest(raw),evidence_body=raw,plan_id=plan),
      P.row('pq_plan',plan_id=plan,registration_id=registration_id,run_id=r['run_id'],generation=generation,current_generation=now,
        revision_before=r['revision'],revision_after=revision,lifecycle_before=r['lifecycle'],preparation_head=db.execute('SELECT coalesce(max(sequence),0) FROM p1_preparation').fetchone()[0],
        target_count=len(targets),latch_id=latch,members_body=P.canonical(members),plan_digest=P.digest(body),plan_body=body)]
    origin=P.rows(db,'SELECT * FROM storage_scope')[0];bindings={}
    for i,(ca,cd) in enumerate(targets):
        target=plan+'.'+str(i);selector=dict(origin_scope=dict(authority_service_id=origin['authority_id'],database_instance_id=origin['database_id']),run_id=r['run_id'],deny_through_generation=generation)
        binding=dict(controller_scope=dict(authority_service_id=ca,database_instance_id=cd),operation_id=target,**selector,selector_digest=P.digest(P.canonical(selector)),target_set_digest=P.digest(body))
        bindings[target]=P.canonical(binding)
        steps.append(P.row('pq_target',plan_id=plan,target_id=target,controller_authority=ca,controller_database=cd,binding_body=bindings[target],dispatch_body=P.canonical(dict(kind='protect_registered_run',binding=binding))))
    if revision!=r['revision']:
        steps.append(("UPDATE run SET revision=?,lifecycle='paused',dispatch_eligible=0 WHERE run_id=? AND revision=?",(revision,r['run_id'],r['revision'])))
    if latch:steps.append(P.row('pause_latch',latch_id=latch,run_id=r['run_id'],reason='preparation_qualification',created_revision=revision,body=raw,cleared_start_id=None))
    steps.append(P.row('sp_plan',plan_id=plan,plan_digest=P.digest(body),target_count=len(targets),plan_body=body))
    steps += [P.row('sp_target',plan_id=plan,target_id=t,binding_body=b) for t,b in bindings.items()]
    steps.append(P.row('sp_plan_commit',plan_id=plan,validation_body=P.canonical(dict(preparation_plan_id=plan))))
    steps.append(P.row('pq_commit',plan_id=plan,audit_body=P.canonical(dict(registration_id=registration_id,kind=kind)),notification_body=P.canonical(dict(kind='preparation_invalidated',plan_id=plan))))
    return steps


def receive(db,registration_id,value,authenticated_controller,fail_after=None,adopt=None):
    O.validate(value);R.require(value['binding']['controller_scope']==authenticated_controller,'authenticated_controller')
    db.execute('BEGIN IMMEDIATE')
    try:
        p=R.one(db,'p1_preparation','registration_id',registration_id)
        R.require(p['binding_body']==P.canonical(value['binding']),'qualification_binding')
        prior=[json.loads(x[0]) for x in db.execute('SELECT body FROM pq_observation WHERE registration_id=?',(registration_id,))]
        reason=O.conflict_reason(prior,value);raw=P.canonical(value)
        if reason:
            steps=invalidate_steps(db,registration_id,'conflict',value);result='conflict' if steps else 'conflict_retained'
        elif any(P.canonical(x)==raw for x in prior):steps=[];result='duplicate'
        else:
            steps=[P.row('pq_observation',registration_id=registration_id,revision=int(value['preparation_revision']),protection_revision=int(value['protection_revision']),
              state=value['state'],binding_body=p['binding_body'],observation_digest=value['observation_digest'],body=raw,
              audit_body=P.canonical(dict(registration_id=registration_id)),notification_body=P.canonical(dict(kind='preparation_observed',registration_id=registration_id)))]
            if value['state'] not in ('accepted','applied'):steps+=invalidate_steps(db,registration_id,'unavailable',value)
            elif value['state']=='applied' and not db.execute('SELECT 1 FROM pq_fault WHERE registration_id=?',(registration_id,)).fetchone():
                steps+=(adopt or R.receipt_steps)(db,registration_id,value,authenticated_controller)
            result='stored'
        for i,(sql,args) in enumerate(steps):
            db.execute(sql,args)
            if i==fail_after:raise RuntimeError('injected')
        db.commit();return result
    except BaseException:db.rollback();raise


def withdraw(db,registration_id,value,trusted_provider,fail_after=None):
    withdrawal_valid(value);R.require(value['proof_ref']['scope']==trusted_provider,'qualified_provider')
    db.execute('BEGIN IMMEDIATE')
    try:
        steps=invalidate_steps(db,registration_id,'withdrawal',value)
        for i,(sql,args) in enumerate(steps):
            db.execute(sql,args)
            if i==fail_after:raise RuntimeError('injected')
        db.commit();return 'withdrawn' if steps else 'retained'
    except BaseException:db.rollback();raise
