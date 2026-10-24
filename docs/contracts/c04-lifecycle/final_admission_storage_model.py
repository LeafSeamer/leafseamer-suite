"""封存写集与提交观察参考适配；不提供设备发送入口。"""
import json
import rfc8785
import final_admission_model as F
import build_final_admission_storage as G
need=F.need
def raw(v):return rfc8785.dumps(v)
def u(v):F.validate('Counter',v);return v.zfill(20)
def insert(table,**v):return f"INSERT INTO {table} ({','.join(v)}) VALUES ({','.join('?' for _ in v)})",tuple(v.values())
def scope(db):
    row=db.execute('SELECT authority_service_id,database_instance_id FROM controller_scope WHERE singleton=1').fetchone()
    need(row is not None,'controller_scope');return dict(authority_service_id=row[0],database_instance_id=row[1])
def candidate(db,v):
    F.validate('Seal',v);need(v==F.seal(v),'seal_digest');need(v['binding']['scope']==scope(db),'seal_scope')
def planned(v,originals,cut):
    """调用者必须在同一个T2中提供真实领域写集；不能把这些行单独提交当作许可。"""
    need(F.verify(v,originals,cut)=='cross_object_binding_valid','seal_binding')
    kind=v['identity']['kind'];source=lambda n:originals[n]['source_ref']['id']
    out=[insert('fa_seal',transaction_id=v['transaction_id'],seal_id=v['seal_id'],permit_id=v['permit_id'],issued_revision=u(v['issued_revision']),kind=kind,
        command_id=v['identity']['command_ref']['id'],state_revision=u(v['command_state_ref']['revision']),exit_id=v['binding']['writer_exit_id'],hold_id=v['hold_ref']['id'],
        ownership_id=source('ownership'),before_snapshot_id=source('resource_before'),after_snapshot_id=source('resource_after'),ordinary_id=v['permit_id'] if kind=='ordinary' else None,cancel_id=v['permit_id'] if kind=='cancel' else None,
        selected_tick=u(v['selected_tick_ns']),sealed_tick=u(v['sealed_tick_ns']),not_before_tick=u(v['send_window']['not_before_tick_ns']),before_tick=u(v['send_window']['before_tick_ns']),seal_digest=v['seal_digest'],seal_body=raw(v))]
    for role,s in sorted(originals.items()):
        out.append(insert('fa_input',seal_id=v['seal_id'],role=role,projection_id=s['ref']['id'],projection_revision=s['ref']['revision'],projection_digest=s['ref']['digest'],
            source_id=s['source_ref']['id'],source_revision=s['source_ref']['revision'],source_digest=s['source_ref']['digest'],body=raw(s)))
    return out
def finish(v,tick,audit,outbox_id,outbox):
    return insert('fa_commit',seal_id=v['seal_id'],permit_id=v['permit_id'],committed_tick=u(tick),audit_body=raw(audit),outbox_id=outbox_id,outbox_body=raw(outbox))

def _original(db,v):
    """必须在已有事务中读取；只有精确完整闭合才称committed，半边作为损坏拒绝。"""
    need(db.in_transaction,'observation_transaction_required')
    rows=db.execute('SELECT seal_id,permit_id,transaction_id,seal_body FROM fa_seal WHERE transaction_id=? OR seal_id=? OR permit_id=?',(v['transaction_id'],v['seal_id'],v['permit_id'])).fetchall()
    if not rows:
        # 新布局禁止无seal的issue；若见到旧/损坏半边，不把它解释为回滚。
        need(not db.execute('SELECT 1 FROM ci_issue WHERE permit_id=?',(v['permit_id'],)).fetchone(),'issue_without_seal')
        return None
    need(len(rows)==1 and tuple(rows[0])==(v['seal_id'],v['permit_id'],v['transaction_id'],raw(v)),'seal_identity_conflict')
    need(db.execute('SELECT 1 FROM fa_commit k JOIN ci_issue i USING(permit_id) WHERE k.seal_id=? AND k.permit_id=? AND i.issued_revision=? AND i.kind=?',(v['seal_id'],v['permit_id'],u(v['issued_revision']),v['identity']['kind'])).fetchone(),'incomplete_issue_group')
    table='ce_transmission_commit' if v['identity']['kind']=='ordinary' else 'ci_cancel_commit'
    need(db.execute(f'SELECT 1 FROM {table} WHERE permit_id=?',(v['permit_id'],)).fetchone(),'missing_domain_commit')
    return v

def observe(db,v,observation_id,tick,observer_ref,*,lookup=True,fail_after_write=False):
    """BEGIN IMMEDIATE取排他writer顺序，并在查无原件时同事务写永久不重签墓碑。"""
    need(not db.in_transaction,'observation_requires_own_transaction');candidate(db,v)
    F.validate('Id',observation_id);u(tick);F.validate('Ref',observer_ref)
    db.execute('BEGIN IMMEDIATE')
    try:
        old=db.execute('SELECT candidate_body,observation_body FROM fa_observation WHERE observation_id=?',(observation_id,)).fetchone()
        if old:
            need(old[0]==raw(v),'observation_id_conflict');o=json.loads(old[1]);F.observe(v,o)
            need(o['observer_ref']==observer_ref,'observation_owner');db.commit();return o
        prior=_original(db,v)
        outcome=('committed' if prior is not None else 'rolled_back') if lookup else 'unknown'
        o=F.seal(dict(observation_id=observation_id,transaction_id=v['transaction_id'],scope=scope(db),seal_ref=F.reference(v),permit_id=v['permit_id'],
            outcome=outcome,observed_tick_ns=tick,observer_ref=observer_ref),'observation_digest');F.observe(v,o)
        db.execute(*insert('fa_observation',observation_id=observation_id,transaction_id=v['transaction_id'],seal_id=v['seal_id'],permit_id=v['permit_id'],seal_digest=v['seal_digest'],outcome=outcome,
            observed_tick=u(tick),candidate_body=raw(v),observation_body=raw(o)))
        if fail_after_write:raise RuntimeError('injected')
        db.commit();return o
    except BaseException:
        # 结果未知时即使rollback未能执行也不能返回rolled_back；异常原样交调用方隔离。
        db.rollback();raise
