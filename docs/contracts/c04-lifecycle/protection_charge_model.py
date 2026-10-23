"""共享保护消费参考事务；计量为逻辑行正文，非SQLite文件/WAL或CPU证明。"""
import json
import build_protection_charge as G
import protection_retry_model as RY
M=RY.M;A=M.A;P=M.P;R=M.R;I=M.I
SHAPE=('dependencies','runs','executions','preparations','submissions','controller_targets')
def encoded(row):return P.canonical([dict(blob=x.hex()) if isinstance(x,bytes) else x for x in row])
def snapshot(db):
    return {t[0]:{encoded(row) for row in db.execute('SELECT * FROM "'+t[0]+'"')} for t in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
def charge_steps(db,plans,before,ctx):
    R.require(db.in_transaction,'transaction_required');R.require(ctx['volatile_close_verified'] and ctx['clock_wait_verified'],'protection_runtime_unconfirmed')
    elapsed=ctx['elapsed_wait_ns'];A.u20(elapsed)
    after=snapshot(db);changed=[(t,b) for t in after for b in after[t]-before.get(t,set())]
    accounts=[dict(x) for pid in plans for x in db.execute('SELECT * FROM pb_expected_account WHERE plan_id=? ORDER BY run_id,generation',(pid,))]
    # 每个账户保守承担完整事务的逻辑峰值；新增计量原件也纳入固定上界，随后验证其实际大小。
    rows=len(changed)+len(accounts)+len(plans);size=sum(len(b) for _,b in changed)+8192*len(accounts)+4096*len(plans)
    maximum=max([len(b) for _,b in changed]+[8192]);summary=dict(version='logical-protection-measurement/1',rows=rows,bytes=size,max_row_bytes=maximum,
        changed_tables={t:sum(k==t for k,_ in changed) for t in sorted({t for t,_ in changed})},account_overhead=8192,seal_overhead=4096)
    writes=[];ordinals={}
    for acc in accounts:
        found=P.rows(db,'SELECT o.operation_id,b.*,c.profile_body FROM arm_operation o JOIN arm_budget_reservation b USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest WHERE o.run_id=? AND o.generation=?',(acc['run_id'],acc['generation']))
        R.require(len(found)==1,'generation_budget_missing');b=found[0];ticket=json.loads(b['budget_body']);profile=json.loads(b['profile_body']);episodes=int(profile['episodes'])
        shape=R.one(db,'pb_shape','plan_id',acc['plan_id']) if len(accounts)==1 else next(x for x in P.rows(db,'SELECT * FROM pb_shape WHERE plan_id=?',(acc['plan_id'],)) if x['run_id']==acc['run_id'] and x['generation']==acc['generation'])
        ordinal=ordinals.get(b['operation_id'],db.execute('SELECT count(*) FROM pb_use WHERE operation_id=?',(b['operation_id'],)).fetchone()[0])+1;ordinals[b['operation_id']]=ordinal
        value=dict(**acc,operation_id=b['operation_id'],ordinal=ordinal,
            binding_digest=ticket['binding_digest'],profile_digest=b['profile_digest'],plan_digest=R.one(db,'sp_plan','plan_id',acc['plan_id'])['plan_digest'],
            **{d:b[d]//episodes for d in G.DIMENSIONS},shape_body=P.canonical({k:str(shape[k]) for k in SHAPE}),observed_rows=rows,observed_bytes=size,
            observed_max_row_bytes=maximum,elapsed_wait_ns=elapsed,measurement_body=P.canonical(summary),audit_body=P.canonical(dict(plan_id=acc['plan_id'],operation_id=b['operation_id'])))
        R.require(len(encoded(tuple(value.values())))<=8192,'charge_row_bound');writes.append(I('pb_use',**value))
    for pid in plans:
        value=dict(plan_id=pid,audit_body=P.canonical(dict(kind='protection_budget_consumed',plan_id=pid)),notification_body=P.canonical(dict(kind='budget_balance_changed',plan_id=pid)))
        R.require(len(encoded(tuple(value.values())))<=4096,'charge_seal_bound');writes.append(I('pb_commit',**value))
    return writes
def apply(db,builder,ctx,fail_after=None):
    R.require(ctx['volatile_close_verified'] and ctx['clock_wait_verified'],'protection_runtime_unconfirmed')
    ctx['protection_confirmation']='unconfirmed';db.execute('BEGIN IMMEDIATE')
    try:
        before=snapshot(db);existing={x[0] for x in db.execute('SELECT plan_id FROM protection_plan_registry')};index=0
        def execute(parts):
            nonlocal index
            for sql,args in parts:
                db.execute(sql,args)
                if index==fail_after:raise RuntimeError('injected')
                index+=1
        execute(builder());plans=sorted({x[0] for x in db.execute('SELECT plan_id FROM protection_plan_registry')}-existing)
        execute(charge_steps(db,plans,before,ctx));db.commit();ctx['protection_confirmation']='durable';return plans
    except BaseException:db.rollback();raise
def terminal(db,execution,step,outcome,ctx,fail_after=None):
    R.require(ctx['terminal_evidence_verified'] and ctx['trusted_system_closer'],'protection_authority')
    def builder():
        prior=P.rows(db,'SELECT * FROM step_terminal WHERE execution_id=? AND step_id=?',(execution,step))
        if prior:
            R.require(prior[0]['outcome']==outcome and prior[0]['evidence_body']==P.canonical(dict(outcome=outcome,completion_ref=ctx.get('completion_command_ref'))),'terminal_identity_conflict')
            if prior[0]['protection_plan_id']:R.one(db,'pb_commit','plan_id',prior[0]['protection_plan_id'])
            return []
        return M.terminal_steps(db,execution,step,outcome,ctx)
    return apply(db,builder,ctx,fail_after)
def retry(db,request,ctx,fail_after=None):
    RY.X.permission(ctx);RY.validate('RetryIntent',request)
    def builder():
        prior=P.rows(db,'SELECT * FROM sr_attempt WHERE request_epoch=? AND actor_body=? AND idempotency_key=?',(request['request_epoch'],P.canonical(request['actor']),request['idempotency_key']))
        if prior:
            R.require(len(prior)==1 and prior[0]['request_body']==P.canonical(request),'identity_conflict');R.one(db,'pb_commit','plan_id',prior[0]['plan_id']);return []
        return RY.retry_steps(db,request,ctx)
    return apply(db,builder,ctx,fail_after)
