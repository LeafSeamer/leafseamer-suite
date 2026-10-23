"""P3/P4离线可执行设计模型：接收已解码对象，非生产认证、原始JSON解析器或网络客户端。"""
import hashlib,json
import jsonschema,rfc8785
from pathlib import Path
from build_protection_delivery import VERSION
HERE=Path(__file__).resolve().parent
SCHEMA=json.loads((HERE/'protection-delivery.schema.json').read_bytes())
def canonical(value):return rfc8785.dumps(value)
def raw_digest(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def seal(value):
    value['observation_digest']=raw_digest(canonical({k:v for k,v in value.items() if k!='observation_digest'}))
    return value
def validate(value):
    jsonschema.Draft202012Validator({'$ref':'#/$defs/Observation','$defs':SCHEMA['$defs']}).validate(value)
    if value['observation_digest']!=raw_digest(canonical({k:v for k,v in value.items() if k!='observation_digest'})):
        raise ValueError('observation_digest')
    if value['cause']['kind']=='initial' and value['cause']['object_id']!=value['fence_id']:raise ValueError('initial_cause')
    if value['cause']['kind']=='prepare_closure' and value['cause']['object_id']!=value['prepare_closure_ref']['id']:raise ValueError('closure_cause')
    if value['cut_ref']['id']!=value['fence_id']:raise ValueError('cut_identity')
def export_event(db,fence_id,revision=None):
    # 一条SELECT固定同一个SQLite快照；revision=None只能走当前资格视图。
    source='ra_current_status' if revision is None else 'ra_status_event'
    tail='' if revision is None else ' AND e.revision=?'
    row=db.execute(f'''SELECT e.revision,e.state,e.cause_kind,e.cause_id,a.receipt_id,a.receipt_body,
      a.prepare_closure_id,p.closure_digest,f.cut_body,r.operation_id,r.origin_authority,r.origin_database,
      r.run_id,r.generation,r.selector_digest,r.target_set_digest,s.authority_service_id,s.database_instance_id
      FROM {source} e JOIN ce_application a USING(fence_id) JOIN ce_fence f USING(fence_id)
      JOIN run_protection_request r USING(protection_id) JOIN controller_scope s ON s.singleton=r.scope_id
      JOIN pd_closure p ON p.closure_id=a.prepare_closure_id WHERE e.fence_id=?'''+tail,
      (fence_id,) if revision is None else (fence_id,revision)).fetchone()
    if row is None:raise ValueError('application_unconfirmed_or_non_http_source')
    rev,state,kind,cause,rid,body,pid,pdigest,cut,op,oa,od,run,generation,selector,targets,ca,cd=row
    value=seal(dict(contract_version=VERSION,binding=dict(controller_scope=dict(authority_service_id=ca,database_instance_id=cd),
      origin_scope=dict(authority_service_id=oa,database_instance_id=od),operation_id=op,run_id=run,
      deny_through_generation=str(int(generation)),selector_digest=selector,target_set_digest=targets),fence_id=fence_id,
      cut_ref=dict(id=fence_id,bytes_digest=raw_digest(cut)),receipt_ref=dict(id=rid,bytes_digest=raw_digest(body)),
      prepare_closure_ref=dict(id=pid,digest=pdigest),status_revision=str(rev),state=state,cause=dict(kind=kind,object_id=cause)))
    validate(value);return value
def identity(value):
    return {k:value[k] for k in ('fence_id','cut_ref','receipt_ref','prepare_closure_ref')}
def receiver():
    import sqlite3
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON')
    db.executescript((HERE/'protection-receiver.sql').read_text(encoding='utf-8'));return db
def receive(db,plan_id,target_id,value,authenticated_controller,fail_after=None):
    # authenticated_controller是已认证输送域，不能从正文自行生成。
    validate(value)
    if authenticated_controller!=value['binding']['controller_scope']:raise ValueError('authenticated_controller')
    raw=canonical(value);rev=int(value['status_revision'])
    db.execute('BEGIN IMMEDIATE')
    try:
        prior=db.execute('SELECT body FROM sp_observation WHERE plan_id=? AND target_id=? AND revision=?',(plan_id,target_id,rev)).fetchone()
        if prior:
            if prior[0]!=raw:raise ValueError('same_revision_conflict')
            db.execute('COMMIT');return 'duplicate'
        db.execute('INSERT INTO sp_observation VALUES(?,?,?,?,?,?,?,?)',
          (plan_id,target_id,rev,value['state'],canonical(value['binding']),canonical(identity(value)),value['observation_digest'],raw))
        if fail_after==0:raise RuntimeError('injected')
        db.execute('INSERT INTO sp_observation_commit VALUES(?,?,?,?,?)',
          (plan_id,target_id,rev,canonical(dict(observation_digest=value['observation_digest'])),
           canonical(dict(plan_id=plan_id,target_id=target_id,status_revision=value['status_revision'],kind='requery_observed_summary'))))
        if fail_after==1:raise RuntimeError('injected')
        db.execute('COMMIT');return 'stored'
    except BaseException:
        db.execute('ROLLBACK');raise
