"""准备观察的离线设计模型：输入已解码对象，不是认证器、HTTP服务或业务数据库迁移。"""
import hashlib,json,sqlite3
from pathlib import Path
import jsonschema,rfc8785
from build_preparation_delivery import VERSION
HERE=Path(__file__).resolve().parent
SCHEMA=json.loads((HERE/'preparation-delivery.schema.json').read_bytes())
TABLES=('po_plan','po_target','po_plan_commit','po_observation','po_observation_commit','po_conflict')
HISTORIES=(('accepted','applied','closing','closed'),('accepted','indeterminate','closing','closed'),
 ('accepted','closing','closed'),('accepted','rejected'),('closing','closed'))
def canonical(value):return rfc8785.dumps(value)
def digest(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def seal(value):
    value['observation_digest']=digest(canonical({k:v for k,v in value.items() if k!='observation_digest'}));return value
def definition(name,value):jsonschema.Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']}).validate(value)
def histories(values):
    return [h for h in HISTORIES if all(int(v['preparation_revision'])<=len(h)
      and h[int(v['preparation_revision'])-1]==v['state']
      and (v['applied_receipt_ref'] is not None)==('applied' in h[:int(v['preparation_revision'])]) for v in values)]
def validate(value):
    definition('Observation',value)
    if len(canonical(value))>16384:raise ValueError('observation_capacity')
    if value['observation_digest']!=digest(canonical({k:v for k,v in value.items() if k!='observation_digest'})):raise ValueError('observation_digest')
    revision=int(value['preparation_revision'])
    if value['previous_revision']!=(None if revision==1 else str(revision-1)):raise ValueError('previous_revision')
    if not histories([value]):raise ValueError('preparation_history')
    c=value['completion']
    if c:
        if c['fence_id']!=c['cut_ref']['id']:raise ValueError('cut_identity')
        cause=value['cause']
        if cause['kind']=='initial' and cause['object_id']!=c['fence_id']:raise ValueError('initial_cause')
        if cause['kind']=='prepare_closure' and cause['object_id']!=c['prepare_closure_ref']['id']:raise ValueError('closure_cause')
def export_event(db,prep_key,revision=None,protection_revision=None):
    # 一条SELECT读取固定快照；历史版本必须显式给出两条修订轴，不以当前资格改写历史事件。
    current=revision is None
    if not current and protection_revision is None:raise ValueError('historical_protection_revision_required')
    source='pc_current' if current else 'cp_event'
    ps_clause='(SELECT max(n.revision) FROM pc_status_event n WHERE n.completion_id=e.completion_id)' if current else '?'
    args=[] if current else [int(protection_revision)]
    args.append(prep_key)
    tail='' if current else ' AND e.revision=?'
    if not current:args.append(str(int(revision)).zfill(20))
    cur=db.execute(f'''SELECT e.revision,e.previous_revision,e.state,e.receipt_id,
      pr.receipt_body AS applied_body,cs.authority_service_id,cs.database_instance_id,
      r.origin_authority,r.origin_database,r.preparation_id,r.run_id,r.generation,r.mode,r.execution_id,r.request_digest,
      cl.close_id,cl.operation_id,cl.operation_digest,cl.request_body AS close_body,
      c.completion_id,b.fence_id,b.receipt_id AS protection_receipt_id,b.receipt_body AS protection_receipt_body,
      f.cut_body,a.prepare_closure_id,p.closure_digest,ps.revision AS protection_revision,
      rs.state AS protection_state,rs.cause_kind,rs.cause_id,now.protection_state AS current_protection_state
      FROM {source} e JOIN cp_commit k ON k.commit_id=e.commit_id JOIN cp_request r USING(prep_key)
      JOIN controller_scope cs ON cs.singleton=r.scope_id JOIN pc_current now ON now.prep_key=e.prep_key
      LEFT JOIN cp_receipt pr ON pr.prep_key=e.prep_key AND pr.receipt_id=e.receipt_id
      LEFT JOIN cp_completion c ON c.completion_id=e.completion_id
      LEFT JOIN cp_close cl ON cl.close_id=coalesce(c.close_id,k.close_id)
      LEFT JOIN pc_binding b ON b.completion_id=c.completion_id LEFT JOIN ce_fence f ON f.fence_id=b.fence_id
      LEFT JOIN ce_application a ON a.fence_id=b.fence_id LEFT JOIN pd_closure p ON p.closure_id=a.prepare_closure_id
      LEFT JOIN pc_status_event ps ON ps.completion_id=e.completion_id AND ps.revision={ps_clause}
      LEFT JOIN ra_status_event rs ON rs.fence_id=ps.fence_id AND rs.revision=ps.run_status_revision
      WHERE e.prep_key=?'''+tail,args)
    row=cur.fetchone()
    if row is None:raise ValueError('preparation_observation_absent')
    r=dict(zip([d[0] for d in cur.description],row))
    closed=r['state']=='closed'
    if closed and (r['protection_revision'] is None or (current and r['current_protection_state'] not in ('applied','indeterminate'))):raise ValueError('preparation_protection_unconfirmed')
    if not current and not closed and int(protection_revision)!=0:raise ValueError('nonclosed_protection_revision')
    ref=lambda ident,raw:dict(id=ident,bytes_digest=digest(raw)) if ident else None
    value=seal(dict(contract_version=VERSION,binding=dict(
      controller_scope=dict(authority_service_id=r['authority_service_id'],database_instance_id=r['database_instance_id']),
      origin_scope=dict(authority_service_id=r['origin_authority'],database_instance_id=r['origin_database']),
      preparation_id=r['preparation_id'],run_id=r['run_id'],generation=str(int(r['generation'])),
      mode=r['mode'],execution_id=r['execution_id'],request_digest=r['request_digest']),
      preparation_revision=str(int(r['revision'])),previous_revision=str(int(r['previous_revision'])) if r['previous_revision'] else None,
      state=r['state'],applied_receipt_ref=ref(r['receipt_id'],r['applied_body']),
      close_ref=dict(id=r['close_id'],operation_id=r['operation_id'],operation_digest=r['operation_digest'],bytes_digest=digest(r['close_body'])) if r['close_id'] else None,
      completion=dict(id=r['completion_id'],fence_id=r['fence_id'],cut_ref=ref(r['fence_id'],r['cut_body']),
        receipt_ref=ref(r['protection_receipt_id'],r['protection_receipt_body']),prepare_closure_ref=dict(id=r['prepare_closure_id'],digest=r['closure_digest'])) if closed else None,
      protection_revision=str(r['protection_revision']) if closed else '0',
      protection_state=r['protection_state'] if closed else ('pending' if r['state']=='closing' else 'not_applicable'),
      cause=dict(kind=r['cause_kind'],object_id=r['cause_id']) if closed else None))
    validate(value);return value
def receiver():
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON')
    db.executescript((HERE/'preparation-receiver.sql').read_text(encoding='utf-8'))
    for table in TABLES:
        for op,suffix in [('UPDATE','u'),('DELETE','d')]:
            db.execute(f"CREATE TRIGGER {table}_{suffix} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_preparation_observation'); END")
    return db
def plan_steps(plan_id,bindings,validation_body):
    for b in bindings.values():definition('Binding',b)
    body=canonical(bindings)
    return [('INSERT INTO po_plan VALUES(?,?,?,?)',(plan_id,digest(body),len(bindings),body))]+[
      ('INSERT INTO po_target VALUES(?,?,?)',(plan_id,t,canonical(b))) for t,b in bindings.items()]+[
      ('INSERT INTO po_plan_commit VALUES(?,?)',(plan_id,validation_body))]
def execute(db,steps,fail_after=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        for n,(sql,args) in enumerate(steps):
            db.execute(sql,args)
            if n==fail_after:raise RuntimeError('injected')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
def identity(value):return {k:v for k,v in value.items() if k not in ('observation_digest','protection_revision','protection_state','cause')}
def conflict_reason(prior,value):
    for old in prior:
        if (old['preparation_revision'],old['protection_revision'])==(value['preparation_revision'],value['protection_revision']):
            if canonical(old)!=canonical(value):return 'same_revision_conflict'
        if old['preparation_revision']==value['preparation_revision'] and identity(old)!=identity(value):return 'completion_conflict'
        if old['applied_receipt_ref'] and value['applied_receipt_ref'] and old['applied_receipt_ref']!=value['applied_receipt_ref']:return 'receipt_conflict'
    if not histories(prior+[value]):return 'history_conflict'
    return None
def receive(db,plan_id,target_id,value,authenticated_controller,fail_after=None):
    validate(value)
    if authenticated_controller!=value['binding']['controller_scope']:raise ValueError('authenticated_controller')
    binding=canonical(value['binding']);raw=canonical(value)
    db.execute('BEGIN IMMEDIATE')
    try:
        expected=db.execute('SELECT binding_body FROM po_target JOIN po_plan_commit USING(plan_id) WHERE plan_id=? AND target_id=?',(plan_id,target_id)).fetchone()
        if not expected or expected[0]!=binding:raise ValueError('plan_binding')
        prior=[json.loads(b) for b, in db.execute('SELECT body FROM po_observation WHERE plan_id=? AND target_id=?',(plan_id,target_id))]
        reason=conflict_reason(prior,value)
        if reason:
            existing=db.execute('SELECT observation_digest,body FROM po_conflict WHERE plan_id=? AND target_id=?',(plan_id,target_id)).fetchone()
            if existing:
                if existing[0]==value['observation_digest'] and existing[1]!=raw:raise ValueError('conflict_digest_collision')
                db.execute('COMMIT');return 'conflict_duplicate' if existing[0]==value['observation_digest'] else 'conflict_retained'
            db.execute('INSERT INTO po_conflict VALUES(?,?,?,?,?,?,?,?)',(plan_id,target_id,value['observation_digest'],reason,binding,raw,
              canonical(dict(kind=reason,observation_digest=value['observation_digest'])),canonical(dict(kind='preparation_observation_unconfirmed',plan_id=plan_id,target_id=target_id))))
            if fail_after==0:raise RuntimeError('injected')
            db.execute('COMMIT');return 'conflict'
        if any(canonical(v)==raw for v in prior):db.execute('COMMIT');return 'duplicate'
        key=(plan_id,target_id,value['preparation_revision'].zfill(20),int(value['protection_revision']))
        db.execute('INSERT INTO po_observation VALUES(?,?,?,?,?,?,?,?,?)',key+(value['state'],value['protection_state'],binding,value['observation_digest'],raw))
        if fail_after==0:raise RuntimeError('injected')
        db.execute('INSERT INTO po_observation_commit VALUES(?,?,?,?,?,?)',key+(
          canonical(dict(observation_digest=value['observation_digest'])),canonical(dict(kind='requery_preparation_observation',plan_id=plan_id,target_id=target_id))))
        if fail_after==1:raise RuntimeError('injected')
        db.execute('COMMIT');return 'stored'
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
