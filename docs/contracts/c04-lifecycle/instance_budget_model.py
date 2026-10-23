"""来源实例分区与消费的离线模型；不实现运行时关闭或物理预分配。"""
import json
import jsonschema
import build_instance_budget as G
import protection_charge_model as C
A=C.A;P=C.P;R=C.R;I=C.I
def validate(profile):jsonschema.Draft202012Validator({'$ref':'#/$defs/PoolProfile','$defs':G.schema()['$defs']}).validate(profile)
def provision(db,profile):
    validate(profile);n=int(profile['episodes']);per=profile['per_episode'];sc=profile['scope']
    R.require(1<=n<=65536 and 1<=int(profile['per_source_episodes'])<=n,'instance_episode_range')
    R.require(all(1<=int(v)<=10**12 for v in list(per.values())+list(profile['total_capacity'].values())),'instance_vector_range')
    R.require(1<=int(profile['max_row_bytes'])<=1048576,'instance_row_range')
    value=dict(singleton=1,authority_id=sc['authority_service_id'],database_id=sc['database_instance_id'],arm_profile_digest=profile['arm_profile_digest'],
        profile_digest=P.digest(P.canonical(profile)),profile_body=P.canonical(profile),episodes=n,per_source_episodes=int(profile['per_source_episodes']),
        **{k:int(per[k]) for k in G.DIMENSIONS},**{'total_'+k:int(profile['total_capacity'][k]) for k in G.DIMENSIONS},
        max_row_bytes=int(profile['max_row_bytes']),max_queue_wait_ns=profile['max_queue_wait_ns'],audit_body=P.canonical(dict(kind='source_budget_provisioned')))
    A.apply(db,lambda:[I('ib_pool',**value)])
def charge_steps(db,plans,before,ctx):
    R.require(db.in_transaction,'transaction_required');A.u20(ctx['elapsed_wait_ns'])
    sources=[R.one(db,'p1_plan','plan_id',pid) for pid in plans if db.execute('SELECT 1 FROM p1_plan WHERE plan_id=?',(pid,)).fetchone()]
    if not sources:return []
    pool=R.one(db,'ib_pool','singleton',1);profile=json.loads(pool['profile_body']);validate(profile)
    R.require(pool['profile_digest']==P.digest(P.canonical(profile)),'instance_profile_digest')
    after=C.snapshot(db);changed=[b for t in after for b in after[t]-before.get(t,set())]
    count=sum(db.execute('SELECT count(*) FROM pb_expected_account WHERE plan_id=?',(pid,)).fetchone()[0] for pid in plans)
    # 全事务峰值包含所有run消费、实例消费和最终seal；每个账户保守承担整笔峰值。
    rows=len(changed)+count+len(sources)+len(plans);size=sum(len(b) for b in changed)+8192*(count+len(sources))+4096*len(plans)
    maximum=max([len(b) for b in changed]+[8192]);ordinal=db.execute('SELECT count(*) FROM ib_use').fetchone()[0];by_source={};writes=[]
    for q in sources:
        ordinal+=1;source=q['source_id'];seq=by_source.get(source,db.execute('SELECT count(*) FROM ib_use WHERE source_id=?',(source,)).fetchone()[0])+1;by_source[source]=seq
        f=R.one(db,'p1_fault','fault_id',q['fault_id'])
        value=dict(plan_id=q['plan_id'],pool_id=1,source_id=source,ordinal=ordinal,source_ordinal=seq,profile_digest=pool['profile_digest'],fault_digest=f['fault_digest'],plan_digest=q['plan_digest'],
            **{k:pool[k] for k in G.DIMENSIONS},observed_rows=rows,observed_bytes=size,observed_max_row_bytes=maximum,elapsed_wait_ns=ctx['elapsed_wait_ns'],
            measurement_body=P.canonical(dict(version='logical-source-measurement/1',rows=rows,bytes=size,max_row_bytes=maximum,run_accounts=count,source_accounts=len(sources),seals=len(plans))),
            audit_body=P.canonical(dict(kind='source_budget_consumed',plan_id=q['plan_id'],source_id=source)))
        R.require(len(C.encoded(tuple(value.values())))<=8192,'instance_charge_row_bound');writes.append(I('ib_use',**value))
    return writes
def apply(db,builder,ctx,fail_after=None):
    R.require(ctx['volatile_close_verified'] and ctx['clock_wait_verified'],'protection_runtime_unconfirmed')
    ctx['protection_confirmation']='unconfirmed';db.execute('BEGIN IMMEDIATE')
    try:
        before=C.snapshot(db);old={x[0] for x in db.execute('SELECT plan_id FROM protection_plan_registry')};index=0
        def execute(parts):
            nonlocal index
            for sql,args in parts:
                db.execute(sql,args)
                if index==fail_after:raise RuntimeError('injected')
                index+=1
        execute(builder());plans=sorted({x[0] for x in db.execute('SELECT plan_id FROM protection_plan_registry')}-old)
        execute(charge_steps(db,plans,before,ctx))
        # 原run计量在实例行写入后采样，必须包含这些新增字节。
        execute(C.charge_steps(db,plans,before,ctx));db.commit();ctx['protection_confirmation']='durable';return plans
    except BaseException:db.rollback();raise
def protect(db,fault,ctx,fail_after=None):
    R.require(ctx['source_fault_verified'] and ctx['trusted_system_closer'],'source_fault_authority')
    def builder():
        prior=P.rows(db,'SELECT fault_body,plan_id FROM p1_fault WHERE fault_id=? OR(detector_domain=? AND detector_sequence=?)',(fault['fault_id'],fault['detector_domain'],fault['detector_sequence']))
        if prior:
            R.require(len(prior)==1 and prior[0]['fault_body']==P.canonical(fault),'fault_identity_conflict')
            R.one(db,'ib_use','plan_id',prior[0]['plan_id']);R.one(db,'pb_commit','plan_id',prior[0]['plan_id']);return []
        return P.plan_steps(db,fault)
    apply(db,builder,ctx,fail_after);return fault['fault_id']
