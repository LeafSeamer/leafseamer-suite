"""P1固定写集的离线参考模型；只接受已核验来源事实，不含网络或设备调用。"""
import hashlib
import rfc8785


def canonical(value):return rfc8785.dumps(value)
def digest(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def row(table,**values):
    # 标识符仅来自本模块和固定测试，不作为对外API。
    return f'INSERT INTO {table}({",".join(values)}) VALUES({",".join("?" for _ in values)})',tuple(values.values())
def rows(db,sql,args=()):
    c=db.execute(sql,args);return [dict(zip([x[0] for x in c.description],r)) for r in c]
def inc(text):
    n=int(text)+1
    if n>=10**20:raise ValueError('u20_exhausted')
    return str(n)


def plan_steps(db,fault):
    """调用方须已持有BEGIN IMMEDIATE；返回固定完整写集，不能跨事务缓存后发送。"""
    if not db.in_transaction:raise ValueError('transaction_required')
    source=rows(db,'SELECT * FROM ingress_source WHERE source_id=?',(fault['source_id'],))[0]
    origin=rows(db,'SELECT * FROM storage_scope')[0]
    deps=rows(db,'SELECT * FROM p1_dependency WHERE source_id=? ORDER BY dependency_id',(fault['source_id'],))
    runs=rows(db,'SELECT * FROM run WHERE run_id IN (SELECT run_id FROM p1_dependency WHERE source_id=?) ORDER BY run_id',(fault['source_id'],))
    selected={r['run_id'] for r in runs}
    executions=[e for e in rows(db,'SELECT * FROM execution ORDER BY execution_id') if e['run_id'] in selected]
    preparations=[p for p in rows(db,'SELECT * FROM p1_preparation ORDER BY registration_id') if p['run_id'] in selected]
    submissions=[s for s in rows(db,'SELECT * FROM command_submission ORDER BY submission_id') if s['run_id'] in selected]
    keys=sorted({(p['run_id'],p['controller_authority'],p['controller_database']) for p in preparations}
      |{(s['run_id'],s['target_authority'],s['target_database']) for s in submissions})
    plan_id=fault['fault_id'];raw=canonical(fault)
    body=canonical(dict(fault_digest=digest(raw),dependencies=[d['dependency_id'] for d in deps],
      runs=[dict(run_id=r['run_id'],revision=r['revision'],generation=r['arm_generation']) for r in runs],
      executions=[dict(execution_id=e['execution_id'],binding_digest=e['binding_digest']) for e in executions],
      preparations=[p['registration_id'] for p in preparations],submissions=[s['submission_id'] for s in submissions],controllers=[list(k) for k in keys]))
    source_after=source['revision'] if source['state']=='closed' else inc(source['revision'])
    source_state=source['state'] if source['state'] in ('closed','quarantined') else 'desynchronized'
    steps=[row('p1_fault',**fault,fault_digest=digest(raw),fault_body=raw,plan_id=plan_id),
      row('p1_plan',plan_id=plan_id,fault_id=fault['fault_id'],source_id=fault['source_id'],
        dependency_head=db.execute('SELECT coalesce(max(sequence),0) FROM p1_dependency').fetchone()[0],
        preparation_head=db.execute('SELECT coalesce(max(sequence),0) FROM p1_preparation').fetchone()[0],
        source_before=source['revision'],source_after=source_after,source_state_before=source['state'],source_state_after=source_state,
        source_sequence=source['contiguous_sequence'],reject_floor=source['reject_floor'],run_count=len(runs),target_count=len(keys),
        preparation_count=len(preparations),preparation_plan_id=plan_id if preparations else None,plan_digest=digest(body),plan_body=body)]
    steps += [row('p1_dependency_member',plan_id=plan_id,dependency_id=d['dependency_id']) for d in deps]
    for r in runs:
        revision=r['revision'] if r['lifecycle']=='completed' else inc(r['revision'])
        steps.append(row('p1_run',plan_id=plan_id,run_id=r['run_id'],revision_before=r['revision'],revision_after=revision,
          generation=r['arm_generation'],lifecycle_before=r['lifecycle'],latch_id=plan_id+'.latch.'+r['run_id']))
    steps += [row('p1_execution_pin',plan_id=plan_id,run_id=e['run_id'],execution_id=e['execution_id'],binding_digest=e['binding_digest']) for e in executions]
    target_map={k:plan_id+'.target.'+str(i) for i,k in enumerate(keys)}
    bindings={}
    for key,target in target_map.items():
        run,ca,cd=key;r=next(r for r in runs if r['run_id']==run)
        selector=canonical(dict(origin_scope=dict(authority_service_id=origin['authority_id'],database_instance_id=origin['database_id']),run_id=run,deny_through_generation=r['arm_generation']))
        binding=dict(controller_scope=dict(authority_service_id=ca,database_instance_id=cd),
          origin_scope=dict(authority_service_id=origin['authority_id'],database_instance_id=origin['database_id']),
          operation_id=target,run_id=run,deny_through_generation=r['arm_generation'],selector_digest=digest(selector),target_set_digest=digest(body))
        bindings[target]=canonical(binding)
        steps.append(row('p1_controller',plan_id=plan_id,target_id=target,run_id=run,controller_authority=ca,controller_database=cd,
          operation_id=target,selector_digest=binding['selector_digest'],target_set_digest=binding['target_set_digest'],binding_body=bindings[target],
          dispatch_body=canonical(dict(kind='protect_registered_run',binding=binding)),audit_body=canonical(dict(plan_id=plan_id,target_id=target))))
    steps += [row('p1_preparation_member',plan_id=plan_id,registration_id=p['registration_id'],target_id=target_map[(p['run_id'],p['controller_authority'],p['controller_database'])]) for p in preparations]
    steps += [row('p1_submission_member',plan_id=plan_id,submission_id=s['submission_id'],target_id=target_map[(s['run_id'],s['target_authority'],s['target_database'])]) for s in submissions]
    if source['state']!='closed':
        steps.append(('UPDATE ingress_source SET revision=?,state=? WHERE source_id=? AND revision=?',(source_after,source_state,source['source_id'],source['revision'])))
    for r in runs:
        revision=r['revision'] if r['lifecycle']=='completed' else inc(r['revision'])
        if r['lifecycle']!='completed':
            steps.append(("UPDATE run SET revision=?,lifecycle='paused',dispatch_eligible=0 WHERE run_id=? AND revision=?",(revision,r['run_id'],r['revision'])))
        steps.append(row('pause_latch',latch_id=plan_id+'.latch.'+r['run_id'],run_id=r['run_id'],reason='source_fault',created_revision=revision,body=raw,cleared_start_id=None))
    steps.append(row('sp_plan',plan_id=plan_id,plan_digest=digest(body),target_count=len(keys),plan_body=body))
    steps += [row('sp_target',plan_id=plan_id,target_id=t,binding_body=b) for t,b in bindings.items()]
    steps.append(row('sp_plan_commit',plan_id=plan_id,validation_body=canonical(dict(p1_plan_id=plan_id))))
    if preparations:
        prep_body=canonical(dict(plan_id=plan_id,preparations=[p['registration_id'] for p in preparations]))
        steps.append(row('po_plan',plan_id=plan_id,plan_digest=digest(prep_body),target_count=len(preparations),plan_body=prep_body))
        steps += [row('po_target',plan_id=plan_id,target_id=p['registration_id'],binding_body=p['binding_body']) for p in preparations]
        steps.append(row('po_plan_commit',plan_id=plan_id,validation_body=canonical(dict(p1_plan_id=plan_id))))
    steps.append(row('p1_commit',plan_id=plan_id,audit_body=canonical(dict(fault_id=fault['fault_id'],plan_digest=digest(body))),notification_body=canonical(dict(kind='source_protected',plan_id=plan_id))))
    return steps


def protect(db,fault):
    # 精确重复只查原计划；相同detector键换正文必须拒绝，不能扩大旧计划。
    db.execute('BEGIN IMMEDIATE')
    try:
        prior=db.execute('SELECT fault_body,plan_id FROM p1_fault WHERE fault_id=? OR (detector_domain=? AND detector_sequence=?)',
          (fault['fault_id'],fault['detector_domain'],fault['detector_sequence'])).fetchall()
        if prior:
            if len(prior)!=1 or prior[0][0]!=canonical(fault):raise ValueError('fault_identity_conflict')
            result=prior[0][1]
        else:
            for sql,args in plan_steps(db,fault):db.execute(sql,args)
            result=fault['fault_id']
        db.commit();return result
    except BaseException:
        db.rollback();raise
