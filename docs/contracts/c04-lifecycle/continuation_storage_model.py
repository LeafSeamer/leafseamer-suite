"""两侧内存SQLite转交参考writer；外部身份/时间/资源提供者仍为显式前提。"""
import json
import rfc8785
import continuation_model as M
import build_continuation_storage as G
import instance_budget_model as B
P=B.P;R=B.R;I=B.I;A=B.A
raw=rfc8785.dumps

def tx(db,builder,fail_after=None):return A.apply(db,builder,fail_after=fail_after)
def one(db,table,key,value):return R.one(db,table,key,value)
def common(q):return {k:q[k] for k in M.COMMON}
def proofref(scope,ident,body):return dict(scope=scope,id=ident,revision='1',digest=M.digest(body))

def seamer_snapshot(db,q,external):
    r=one(db,'run','run_id',q['run_id']);o=one(db,'recovery_operation','operation_id',q['recovery_operation_id'])
    e=one(db,'execution','execution_id',q['recovery_execution_id']);sl=one(db,'activation_slot','definition_id',r['definition_id'])
    lk=one(db,'recovery_lock','operation_id',o['operation_id']);scope=one(db,'storage_scope','singleton',1)
    binding=dict(origin_scope=dict(authority_service_id=scope['authority_id'],database_instance_id=scope['database_id']),run_id=r['run_id'],
        generation=r['arm_generation'],recovery_operation_id=o['operation_id'],recovery_execution_id=o['execution_id'],continuation_plan_ref=external['binding']['continuation_plan_ref'])
    return dict(external,binding=binding,run_revision=r['revision'],slot_revision=sl['revision'],operation_revision=o['revision'],
        run_state=r['lifecycle'],operation_state=o['state'],execution_state=e['state'],recovery_lock_held=lk['release_id'] is None,
        pause_latched=bool(db.execute('SELECT 1 FROM pause_latch WHERE run_id=? AND cleared_start_id IS NULL',(q['run_id'],)).fetchone()),
        recovery_steps_complete=external['recovery_steps_complete'] and bool(db.execute('SELECT 1 FROM step_state WHERE execution_id=?',(e['execution_id'],)).fetchone())
            and not db.execute("SELECT 1 FROM step_state WHERE execution_id=? AND(state!='finished' OR outcome!='succeeded')",(e['execution_id'],)).fetchone())

def request_steps(db,q,ctx):
    M.require(db.in_transaction,'transaction_required');M.request_eligible(q,seamer_snapshot(db,q,ctx))
    writes=[I('rc_request',transfer_id=q['transfer_id'],run_id=q['run_id'],generation=q['generation'],operation_id=q['recovery_operation_id'],
        execution_id=q['recovery_execution_id'],request_epoch=q['request_epoch'],actor_body=raw(q['actor']),idempotency_key=q['idempotency_key'],request_digest=q['request_digest'],request_body=raw(q))]
    for t in q['targets']:
        p=P.rows(db,'SELECT * FROM p1_preparation WHERE run_id=? AND generation=? AND controller_authority=? AND controller_database=?',
            (q['run_id'],q['generation'],*M.scope_key(t['controller_scope'])))
        M.require(len(p)==1,'registration');writes.append(I('rc_target',transfer_id=q['transfer_id'],registration_id=p[0]['registration_id'],target_body=raw(t)))
    return writes+[I('rc_request_commit',transfer_id=q['transfer_id'],request_digest=q['request_digest'],audit_body=raw({'kind':'continuation_requested'}),outbox_body=raw({'transfer_id':q['transfer_id']}))]

def register(db,q,ctx,fail_after=None):
    M.request_shape(q);M.require(ctx['read_authorized'],'read_authority')
    old=P.rows(db,'SELECT * FROM rc_request WHERE transfer_id=? OR(run_id=? AND generation=?) OR(request_epoch=? AND actor_body=? AND idempotency_key=?)',
        (q['transfer_id'],q['run_id'],q['generation'],q['request_epoch'],raw(q['actor']),q['idempotency_key']))
    if old:
        M.require(len(old)==1 and old[0]['request_body']==raw(q),'identity_conflict');one(db,'rc_request_commit','transfer_id',q['transfer_id']);return 'existing'
    tx(db,lambda:request_steps(db,q,ctx),fail_after);return 'accepted'

def controller_snapshot(db,q,t,external):
    p=P.rows(db,'SELECT * FROM cp_request WHERE origin_authority=? AND origin_database=? AND preparation_id=?',(*M.scope_key(q['origin_scope']),t['preparation_ref']['id']))
    M.require(len(p)==1,'parent_missing');p=p[0];state=one(db,'cp_current','prep_key',p['prep_key']);sc=one(db,'controller_scope','singleton',1)
    deny=P.rows(db,'SELECT * FROM run_deny_current WHERE origin_authority=? AND origin_database=? AND run_id=?',(*M.scope_key(q['origin_scope']),q['run_id']))
    states=P.rows(db,'SELECT * FROM ct_current_state WHERE device_id IN(SELECT device_id FROM cp_request_device WHERE prep_key=?)',(p['prep_key'],))
    c=dict(external,scope=dict(authority_service_id=sc['authority_service_id'],database_instance_id=sc['database_instance_id']),
        origin_scope=dict(authority_service_id=p['origin_authority'],database_instance_id=p['origin_database']),run_id=p['run_id'],generation=str(int(p['generation'])),
        recovery_execution_id=p['execution_id'],mode=p['mode'],preparation_state=state['state'],deny_through_generation=str(int(deny[0]['generation'])) if deny else '0',
        closed=bool(db.execute('SELECT 1 FROM cp_close WHERE prep_key=?',(p['prep_key'],)).fetchone()),
        automatic_control=len(states)==len(t['devices']) and all(x['mode']=='automatic' for x in states),pending_takeover=any(x['pending_operation_id'] is not None for x in states))
    for d in t['devices']:
        actual=[s for s in states if s['device_id']==d['device_id']]
        M.require(len(actual)==1 and actual[0]['change_id']==d['control_ref']['id'] and str(int(actual[0]['record_revision']))==d['control_ref']['revision']
            and actual[0]['record_digest']==d['control_ref']['digest'],'control_snapshot_changed')
    rows=P.rows(db,'SELECT * FROM cr_issue WHERE prep_key=?',(p['prep_key'],))
    c['same_generation_transfer_id']=rows[0]['transfer_id'] if rows else None
    if rows:
        row=rows[0];c.update(durable_receipt=json.loads(row['receipt_body']),grant=json.loads(row['grant_body']))
        c['qualification_ref']=c['durable_receipt']['qualification_ref']
        c['closed']=c['closed'] or bool(db.execute('SELECT 1 FROM cr_revocation WHERE transfer_id=?',(row['transfer_id'],)).fetchone())
    return p,c

def issue_steps(db,q,t,external):
    M.require(db.in_transaction,'transaction_required');p,c=controller_snapshot(db,q,t,external)
    M.issue_decision(q,t,c,None,c['read_authorized'])
    grant=dict(scope='run_generation',request_digest=q['request_digest'],target_digest=M.digest(t),plan_ref=q['continuation_plan_ref'],
        parent_preparation_ref=t['preparation_ref'],activation='adoption_and_r5')
    grant['ref']=proofref(c['scope'],q['transfer_id']+'.grant',grant)
    r=M.seal(dict(**common(q),request_digest=q['request_digest'],controller_scope=c['scope'],receipt_id=q['transfer_id']+'.receipt',revision='1',
        target_digest=M.digest(t),preparation_ref=t['preparation_ref'],recovery_grant_ref=t['recovery_grant_ref'],continuation_grant_ref=grant['ref'],qualification_ref=c['qualification_ref']),'receipt_digest')
    M.receipt_eligible(q,r,dict(c,durable_receipt=r,grant=grant))
    writes=[I('cr_issue',transfer_id=q['transfer_id'],prep_key=p['prep_key'],request_digest=q['request_digest'],request_body=raw(q),target_body=raw(t),
        receipt_id=r['receipt_id'],receipt_digest=r['receipt_digest'],receipt_body=raw(r),grant_id=grant['ref']['id'],grant_body=raw(grant))]
    for d in t['devices']:writes.append(I('cr_device',transfer_id=q['transfer_id'],device_id=d['device_id'],control_state_id=d['control_ref']['id'],device_body=raw(d)))
    return writes+[I('cr_commit',transfer_id=q['transfer_id'],request_digest=q['request_digest'],audit_body=raw({'kind':'continuation_issued'}),outbox_body=raw({'receipt_id':r['receipt_id']}))]

def issue(db,q,t,ctx,fail_after=None):
    M.request_shape(q);M.require(ctx['read_authorized'],'read_authority')
    rows=P.rows(db,'SELECT * FROM cr_issue WHERE transfer_id=?',(q['transfer_id'],))
    if rows:
        M.require(rows[0]['request_body']==raw(q) and rows[0]['target_body']==raw(t),'identity_conflict')
        one(db,'cr_commit','transfer_id',q['transfer_id']);return json.loads(rows[0]['receipt_body'])
    tx(db,lambda:issue_steps(db,q,t,ctx),fail_after)
    return json.loads(one(db,'cr_issue','transfer_id',q['transfer_id'])['receipt_body'])

def receive_steps(db,q,r,controller_db,ctx):
    M.require(db.in_transaction,'transaction_required')
    M.require(ctx['read_authorized'],'read_authority');M.request_shape(q);M.validate('Receipt',r);M.common(r,q)
    req=one(db,'rc_request','transfer_id',q['transfer_id']);M.require(req['request_body']==raw(q),'request_original')
    t=next(x for x in q['targets'] if x['controller_scope']==r['controller_scope'])
    original=one(controller_db,'cr_issue','transfer_id',q['transfer_id']);one(controller_db,'cr_commit','transfer_id',q['transfer_id'])
    sc=one(controller_db,'controller_scope','singleton',1)
    M.require(M.scope_key(t['controller_scope'])==(sc['authority_service_id'],sc['database_instance_id']) and
        original['request_body']==raw(q) and original['target_body']==raw(t) and original['receipt_body']==raw(r),'receipt_original')
    p=P.rows(db,'SELECT * FROM rc_target WHERE transfer_id=? AND json(target_body)=json(?)',(q['transfer_id'],raw(t)))
    M.require(len(p)==1,'target_original')
    return [I('rc_receipt',transfer_id=q['transfer_id'],registration_id=p[0]['registration_id'],receipt_digest=r['receipt_digest'],receipt_body=raw(r),audit_body=raw({'kind':'continuation_observed'}))]

def receive(db,q,r,controller_db,ctx,fail_after=None):
    M.require(ctx['read_authorized'],'read_authority');M.request_shape(q)
    M.require(one(db,'rc_request','transfer_id',q['transfer_id'])['request_body']==raw(q),'request_original')
    old=P.rows(db,'SELECT * FROM rc_receipt WHERE transfer_id=? AND receipt_body=?',(q['transfer_id'],raw(r)))
    if old:return 'existing'
    tx(db,lambda:receive_steps(db,q,r,controller_db,ctx),fail_after);return 'accepted'

def adopt(db,q,a,ctx,controllers,fail_after=None):
    M.require(ctx['read_authorized'],'read_authority')
    old=P.rows(db,'SELECT * FROM rc_adoption WHERE transfer_id=?',(q['transfer_id'],))
    if old:
        M.require(old[0]['adoption_body']==raw(a) and one(db,'rc_request','transfer_id',q['transfer_id'])['request_body']==raw(q),'identity_conflict')
        one(db,'rc_adoption_commit','transfer_id',q['transfer_id']);return 'existing'
    tx(db,lambda:adoption_steps(db,q,a,ctx,controllers),fail_after);return 'accepted'

def finish(db,q,ctx,controllers,fail_after=None):
    M.require(ctx['read_authorized'],'read_authority')
    M.require(one(db,'rc_request','transfer_id',q['transfer_id'])['request_body']==raw(q),'request_original')
    old=P.rows(db,'SELECT * FROM rc_r5_link WHERE transfer_id=?',(q['transfer_id'],))
    if old:one(db,'flow_commit_seal','commit_id',old[0]['commit_id']);return 'existing'
    tx(db,lambda:r5_steps(db,q,ctx,controllers),fail_after);return 'accepted'

def adoption_steps(db,q,a,ctx,controllers):
    M.require(db.in_transaction,'transaction_required');req=one(db,'rc_request','transfer_id',q['transfer_id'])
    M.require(req['request_body']==raw(q),'request_original')
    receipts=[json.loads(x['receipt_body']) for x in P.rows(db,'SELECT * FROM rc_receipt WHERE transfer_id=?',(q['transfer_id'],))]
    receipts.sort(key=lambda r:M.scope_key(r['controller_scope']));cs={}
    for t in q['targets']:
        key=M.scope_key(t['controller_scope']);cd,external=controllers[key];_,cs[key]=controller_snapshot(cd,q,t,external)
        one(cd,'cr_commit','transfer_id',q['transfer_id'])
    M.adoption_eligible(q,a,receipts,seamer_snapshot(db,q,ctx),cs)
    return [I('rc_adoption',transfer_id=q['transfer_id'],adoption_id=a['adoption_id'],adoption_digest=a['adoption_digest'],adoption_body=raw(a),release_proof_body=raw(ctx['release_proof'])),
        I('rc_adoption_commit',transfer_id=q['transfer_id'],adoption_digest=a['adoption_digest'],audit_body=raw({'kind':'continuation_adopted'}),outbox_body=raw({'adoption_id':a['adoption_id']}))]

def r5_steps(db,q,ctx,controllers):
    M.require(db.in_transaction,'transaction_required');ad=one(db,'rc_adoption','transfer_id',q['transfer_id']);a=json.loads(ad['adoption_body'])
    # 使用同一当前资格检查，但不重复写采用；SQL最终seal再次核对本地身份。
    adoption_steps(db,q,a,ctx,controllers)
    e=one(db,'execution','execution_id',q['recovery_execution_id']);r=one(db,'run','run_id',q['run_id'])
    o=one(db,'recovery_operation','operation_id',q['recovery_operation_id']);sl=one(db,'activation_slot','definition_id',r['definition_id'])
    M.require(ctx['required_evidence'] and ctx['no_unresolved'],'commit_evidence')
    states=P.rows(db,'SELECT * FROM business_state WHERE run_id=?',(r['run_id'],));state=states[0] if states else None
    if e['kind']=='state_machine':M.require(state and (state['state_id'],state['revision'])==(e['source_state_id'],e['source_state_revision']),'state_cas')
    ident=q['transfer_id']+'.r5';rev=P.inc(r['revision']);body=raw(dict(transfer_id=q['transfer_id'],adoption_digest=a['adoption_digest']))
    release=ctx['release_proof']['ref'];release_id=q['transfer_id']+'.release'
    writes=R.event(ident,r['run_id'],'R5')+[I('transition_commit',commit_id=ident,run_id=r['run_id'],execution_id=e['execution_id'],kind=e['kind'],
        source_state_id=e['source_state_id'],source_state_revision=e['source_state_revision'],target_state_id=e['target_state_id'],target_state_revision=P.inc(state['revision']) if state else None,
        evidence_set_body=raw([dict(x) for x in db.execute('SELECT step_id,outcome,terminal_id FROM step_state WHERE execution_id=? ORDER BY step_id',(e['execution_id'],))]),
        commit_body=body,commit_digest=M.digest(json.loads(body)),tx_id=ident+'.R5',run_revision_before=r['revision'],run_revision_after=rev,slot_revision=sl['revision']),
        ("UPDATE execution SET state='succeeded',commit_id=? WHERE execution_id=?",(ident,e['execution_id']))]
    if state:writes.append(('UPDATE business_state SET state_id=?,revision=?,last_commit_id=? WHERE run_id=? AND revision=?',(e['target_state_id'],P.inc(state['revision']),ident,r['run_id'],state['revision'])))
    writes += [("UPDATE run SET lifecycle='armed',revision=?,active_execution_id=NULL,dispatch_eligible=1,last_commit_id=? WHERE run_id=? AND revision=?",(rev,ident,r['run_id'],r['revision'])),
        ("UPDATE recovery_operation SET state='completed',revision=? WHERE operation_id=?",(P.inc(o['revision']),o['operation_id'])),
        I('external_evidence',evidence_id=release_id,authority_id=release['scope']['authority_service_id'],database_id=release['scope']['database_instance_id'],kind='release',
            object_id=release['id'],revision=release['revision'],digest=release['digest'],body=raw(ctx['release_proof'])),
        ('UPDATE recovery_lock SET release_id=? WHERE operation_id=?',(release_id,o['operation_id'])),
        I('rc_r5_link',commit_id=ident,transfer_id=q['transfer_id'],adoption_digest=a['adoption_digest']),
        I('flow_commit_seal',commit_id=ident,audit_body=body,notification_body=raw({'kind':'recovery_committed','commit_id':ident}))]
    return writes
