"""来源实例池的零run、独立分区、限额与完整原子事务验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import instance_budget_model as M
import check_recovery_budget as T
G=M.G;A=M.A;P=M.P;R=M.R;I=M.I;C=T.C;B=T.B;AT=T.AT;CH=M.C
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in ('INSTANCE_BUDGET.md','instance-budget.schema.json','instance_budget_model.py','check_instance_budget.py','seamer-instance-budget.sql')]))
def profile(d,episodes=4,per_source=2,per=None):
    arm=R.one(d,'arm_capacity','singleton',1);sc=R.one(d,'storage_scope','singleton',1)
    cost=dict(logical_rows='2048',logical_bytes='33554432',queue_slots='64',work_units='4096')
    if per:cost.update(per)
    return dict(contract_version=G.VERSION,profile_id='sim-source-pool',purpose='simulation',scope=dict(authority_service_id=sc['authority_id'],database_instance_id=sc['database_id']),
        arm_profile_digest=arm['profile_digest'],episodes=str(episodes),per_source_episodes=str(per_source),per_episode=cost,
        total_capacity={k:str(arm[k]+int(cost[k])*episodes) for k in G.DIMENSIONS},max_row_bytes='16384',max_queue_wait_ns='500000000')
def fixture(*,arm=True,pool=True,capacity=None,episodes=4,per_source=2,per=None):
    d,q,c,ts=AT.fixture(sql_factory=G.build,capacity=capacity)
    for s in ('empty.a','empty.b'):d.execute(*I('ingress_source',source_id=s,source_key=s.encode(),revision='1',contiguous_sequence='7',reject_floor='3',state='synchronized'))
    p=profile(d,episodes,per_source,per)
    if pool:M.provision(d,p)
    if arm:A.reserve(d,q,c);AT.receive_all(d,ts);A.apply(d,lambda:A.complete_steps(d,q['operation_id'],c))
    c=T.T.context(dict(c,trusted_system_closer=True,source_fault_verified=True))
    return d,q,c,ts,p
def planned(d,f,c):
    d.execute('BEGIN IMMEDIATE')
    try:
        before=CH.snapshot(d);steps=P.plan_steps(d,f)
        for sql,args in steps:d.execute(sql,args)
        more=M.charge_steps(d,[f['fault_id']],before,c)
        for sql,args in more:d.execute(sql,args)
        return steps+more+CH.charge_steps(d,[f['fault_id']],before,c)
    finally:d.rollback()
def balance(d):return dict(d.execute('SELECT * FROM ib_balance').fetchone())
def run():
    checks=[];dbs=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(**kw):
        v=fixture(**kw);dbs.append(v[0]);return v
    def denied(n,d,call,reason=None):
        before=C.snapshot(d)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError,M.jsonschema.ValidationError) as err:
            if reason:assert reason in str(err),(n,str(err),reason)
            check(n,C.snapshot(d)==before);return
        raise AssertionError(n)
    try:
        check('生成SQL字节',(HERE/'seamer-instance-budget.sql').read_bytes()==G.build());check('生成Schema字节',(HERE/'instance-budget.schema.json').read_bytes()==G.schema_bytes())
        M.jsonschema.Draft202012Validator.check_schema(G.schema())
        d,q,c,ts,p=f();check('104表组合',len(C.snapshot(d)),104)
        zero=C.fault(source='empty.a');writes=planned(d,zero,c)
        for i in range(len(writes)):
            denied('零run漏写'+str(i),d,lambda i=i:C.execute(d,writes[:i]+writes[i+1:]))
            denied('零run写后故障'+str(i),d,lambda i=i:M.protect(d,zero,c,fail_after=i),'injected')
        denied('旧writer不可漏实例账',d,lambda:CH.apply(d,lambda:P.plan_steps(d,zero),c),'instance_charge_required')
        for key in ('source_fault_verified','trusted_system_closer','volatile_close_verified','clock_wait_verified'):
            denied('缺提供者前提'+key,d,lambda key=key:M.protect(d,zero,dict(c,**{key:False})))
        for key,value in [('pool_id',2),('source_id','empty.b'),('ordinal',2),('source_ordinal',2),('profile_digest','wrong'),('fault_digest','wrong'),('plan_digest','wrong')]:
            denied('错消费身份'+key,d,lambda key=key,value=value:C.execute(d,C.mutate(writes,'ib_use',{key:value})))
        for dim in G.DIMENSIONS:denied('少扣实例维度'+dim,d,lambda dim=dim:C.execute(d,C.mutate(writes,'ib_use',{dim:1})),'instance_charge_vector')
        for elapsed in ('01','-1','500000000','99999999999999999999'):
            denied('实例等待边界'+elapsed,d,lambda elapsed=elapsed:M.protect(d,zero,dict(c,elapsed_wait_ns=elapsed)))
        before=C.snapshot(d);initial=balance(d);check('零run可靠记账',M.protect(d,zero,dict(c,elapsed_wait_ns='499999999')),zero['fault_id'])
        check('零run不动运行及代次账',all(before[t]==C.snapshot(d)[t] for t in ('run','activation_slot','arm_budget_reservation','pb_use','pause_latch')))
        check('零run来源明确失步',R.one(d,'ingress_source','source_id','empty.a')['state'],'desynchronized')
        check('零run没有虚构Controller目标',d.execute('SELECT count(*) FROM sp_target').fetchone()[0],0)
        check('单次消费来源池',balance(d)['episodes_left'],3)
        for dim in G.DIMENSIONS:check('实例四维守恒'+dim,balance(d)['held_'+dim]+balance(d)['spent_'+dim],initial['held_'+dim])
        before=C.snapshot(d);M.protect(d,zero,dict(c,elapsed_wait_ns='99999999999999999999'));check('相同故障先查原零写',C.snapshot(d)==before)
        denied('同检测器序号换正文',d,lambda:M.protect(d,dict(zero,reason='other'),c),'fault_identity_conflict')
        M.protect(d,C.fault('2','empty.a'),c);denied('单来源额度耗尽拒绝新故障',d,lambda:M.protect(d,C.fault('3','empty.a'),c),'binding_or_capacity')
        check('另一来源仍有独立机会',M.protect(d,C.fault('3','empty.b'),c),'fault.3');M.protect(d,C.fault('4','empty.b'),c)
        check('实例全池耗尽',balance(d)['episodes_left'],0)
        denied('实例耗尽不借run池',d,lambda:M.protect(d,C.fault('5'),c),'binding_or_capacity')
        check('实例耗尽run预留未用',d.execute('SELECT episodes_left FROM pb_balance').fetchone()[0],2)
        before=C.snapshot(d);M.protect(d,zero,c);check('全池耗尽仍能查原',C.snapshot(d)==before)
        for table in ('ib_pool','ib_use'):
            denied('不可删除'+table,d,lambda table=table:C.execute(d,[('DELETE FROM '+table,())]),'immutable')
            denied('不可更新'+table,d,lambda table=table:C.execute(d,[('UPDATE '+table+' SET logical_rows=logical_rows',())]),'immutable')
        # 有run时双层消费是AND，不是允许实例池代付的OR。
        z,qq,cc,tt,pp=f(per_source=4);request=C.fault();ww=planned(z,request,cc)
        denied('不能伪装零run逃代次消费',z,lambda:C.execute(z,C.mutate(ww,'p1_plan',dict(run_count=0))))
        for table in ('ib_use','pb_use','pb_commit'):
            denied('双层漏账'+table,z,lambda table=table:C.execute(z,[w for w in ww if not w[0].startswith('INSERT INTO '+table+'(')]))
        M.protect(z,request,cc);check('双层同时扣一份',(balance(z)['episodes_left'],z.execute('SELECT episodes_left FROM pb_balance').fetchone()[0]),(3,1))
        for target in P.rows(z,'SELECT * FROM sp_target WHERE plan_id=?',(request['fault_id'],)):
            binding=json.loads(target['binding_body']);T.T.T.SP.receive(z,request['fault_id'],target['target_id'],C.observation(binding),binding['controller_scope'])
        check('实际P1观察全applied',z.execute('SELECT observed_state FROM sp_observed_summary WHERE plan_id=?',(request['fault_id'],)).fetchone()[0],'applied')
        check('applied不退款',balance(z)['episodes_left'],3)
        M.protect(z,C.fault('2'),cc);denied('run池耗尽不能借实例池',z,lambda:M.protect(z,C.fault('3'),cc),'capacity')
        check('run拒绝时实例账也回滚',balance(z)['episodes_left'],2)
        M.protect(z,C.fault('3','empty.a'),cc);check('run池耗尽零run仍可保护',balance(z)['episodes_left'],1)
        # 同一事务里两来源各记一笔，ordinal必须连续，不重复使用尚未提交的余额。
        z,qq,cc,tt,pp=f();one=C.fault('1','empty.a');two=C.fault('2','empty.b')
        M.apply(z,lambda:P.plan_steps(z,one)+P.plan_steps(z,two),cc)
        check('两计划同事务连续编号',[(x['ordinal'],x['source_ordinal']) for x in P.rows(z,'SELECT * FROM ib_use ORDER BY ordinal')],[(1,1),(2,1)])
        check('两计划各扣一份',balance(z)['episodes_left'],2)
        z,qq,cc,tt,pp=f(episodes=1,per_source=1)
        denied('多计划超过实例剩余整笔回滚',z,lambda:M.apply(z,lambda:P.plan_steps(z,one)+P.plan_steps(z,two),cc),'capacity')
        z,qq,cc,tt,pp=f(arm=False)
        denied('有run缺代次预留不得用实例代付',z,lambda:M.protect(z,C.fault(),cc),'generation_budget_missing')
        # 跨run仍只有一个来源计划账户，而每个run分别承担本代次完整保护包络。
        z,qq,cc,tt,pp=f();artifact=z.execute('SELECT artifact_digest FROM published_version').fetchone()[0]
        C.execute(z,[I('published_version',definition_id='d1',version='1',artifact_digest=artifact,artifact_body=B),
            I('run',run_id='r1',definition_id='d1',version='1',revision='1',arm_generation='0',lifecycle='disarmed',dispatch_eligible=0),
            I('activation_slot',definition_id='d1',revision='1',active_run_id=None,version=None),
            I('p1_dependency',dependency_id='second.dep',sequence=2,source_id='source',run_id='r1',owner_kind='run',owner_ref='r1',execution_id=None,recovery_id=None,artifact_digest=artifact,binding_body=B)])
        targets=copy.deepcopy(tt)
        for target in targets:
            target['registration_id']='second.'+target['registration_id'];target['preparation_id']='second.'+target['preparation_id'];target['request_body']['preparation_id']=target['preparation_id']
        c2=dict(cc,target_manifest_digest=P.digest(P.canonical(targets)));z.execute(*A.preflight_step(z,'second.preflight','r1',targets,c2))
        A.reserve(z,dict(qq,operation_id='arm.2',run_id='r1',preflight_id='second.preflight',idempotency_key='second.key'),c2)
        AT.receive_all(z,targets);A.apply(z,lambda:A.complete_steps(z,'arm.2',c2));ww=planned(z,C.fault(),cc)
        uses=[i for i,w in enumerate(ww) if w[0].startswith('INSERT INTO pb_use(')]
        for i in uses:denied('跨run缺账户'+str(i),z,lambda i=i:C.execute(z,ww[:i]+ww[i+1:]))
        M.protect(z,C.fault(),cc)
        check('跨run实例只扣一次',(z.execute('SELECT count(*) FROM ib_use').fetchone()[0],z.execute('SELECT count(*) FROM pb_use').fetchone()[0]),(1,2))
        # 小于实际初写峰值必须拒绝，不能只保存来源状态而省掉账本。
        for dim in ('logical_rows','logical_bytes'):
            z,qq,cc,tt,pp=f(per={dim:'1'});denied('初写计量超包络'+dim,z,lambda:M.protect(z,C.fault(source='empty.a'),cc),'capacity')
        # 启动分区不可与run容量重复计算；未配置来源池不得开始arm。
        z,qq,cc,tt,pp=f(arm=False,pool=False);denied('无实例池禁止arm',z,lambda:A.reserve(z,qq,cc),'instance_budget_unavailable')
        for key in pp:
            bad=copy.deepcopy(pp);bad.pop(key);denied('Profile缺字段'+key,z,lambda bad=bad:M.provision(z,bad))
        for patch in (dict(extra=True),dict(episodes='01'),dict(episodes='65537'),dict(per_source_episodes='5'),dict(purpose='release_candidate')):
            denied('Profile非法'+str(patch),z,lambda patch=patch:M.provision(z,dict(pp,**patch)))
        for dim in G.DIMENSIONS:
            bad=copy.deepcopy(pp);bad['total_capacity'][dim]=str(int(bad['total_capacity'][dim])-1)
            denied('容量分区不闭合'+dim,z,lambda bad=bad:M.provision(z,bad),'partition')
        for value in ('0','1000000000001','99999999999999999999'):
            bad=copy.deepcopy(pp);bad['per_episode']['logical_rows']=value
            denied('U20至SQL有界转换'+value,z,lambda bad=bad:M.provision(z,bad),'instance_vector_range')
        for key,value in [('scope',dict(authority_service_id='other',database_instance_id='db')),('arm_profile_digest','sha256:'+'0'*64)]:
            denied('启动身份错配'+key,z,lambda key=key,value=value:M.provision(z,dict(pp,**{key:value})))
        # 即使run区已经全部持有，独立来源区仍可记录零run故障。
        amount=int(A.B.cost(AT.A.profile(),AT.A.SHAPE)['logical_rows'])*2
        z,qq,cc,tt,pp=f(capacity={'logical_rows':str(amount)});M.protect(z,C.fault(source='empty.a'),cc)
        check('run区满额不挤占来源区',balance(z)['episodes_left'],3)
        # 无run故障耗尽实例池后，进行中的布防和恢复也不得开放。
        z,qq,cc,tt,pp=f(arm=False,episodes=1,per_source=1);A.reserve(z,qq,cc);AT.receive_all(z,tt)
        M.protect(z,C.fault(source='empty.a'),cc);denied('arm就绪前实例耗尽',z,lambda:A.apply(z,lambda:A.complete_steps(z,qq['operation_id'],cc)),'instance_budget_unavailable')
        z,qq,cc,tt,pp=f(episodes=1,per_source=1);rec,gg=AT.reconcile_preflight(z);cc.update(gg);T.M.reserve(z,rec,cc);T.prepared(z,rec)
        M.protect(z,C.fault(source='empty.a'),cc);denied('R4前实例耗尽',z,lambda:R.apply(z,lambda:R.start_steps(z,rec['operation_id'],cc)),'instance_budget_unavailable')
        # 正常恢复代次的P1也必须同时消费实例与新代次账户。
        z,qq,cc,tt,pp=f();rec,gg=AT.reconcile_preflight(z);cc.update(gg);T.M.reserve(z,rec,cc)
        M.protect(z,C.fault(),cc);check('恢复与实例同步消费',(balance(z)['episodes_left'],T.balances(z)),(3,[('arm.1','1',2),('recovery.1','2',1)]))
        for i,conn in enumerate(dbs):check('外键完整'+str(i),list(conn.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'instance-budget-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=104,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
