"""来源独享预留、启用原子性及受预算约束的正常触发验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import source_budget_model as M
import check_instance_budget as T
G=M.G;B=M.B;A=M.A;P=M.P;R=M.R;I=M.I;C=T.C;AT=T.AT;FLOW=T.T.TF;F=FLOW.F
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+G.SOURCES+[HERE/n for n in ('SOURCE_BUDGET.md','source-budget.schema.json','source_budget_model.py','check_source_budget.py','seamer-source-budget.sql')]))
def request(d,source='source',episodes='2'):
    s=R.one(d,'ingress_source','source_id',source);p=R.one(d,'ib_pool','singleton',1)
    return dict(contract_version=G.VERSION,source_id=source,expected_source_revision=s['revision'],source_key_digest=P.digest(s['source_key']),pool_profile_digest=p['profile_digest'],
        episodes=episodes,request_epoch='source.epoch',actor=dict(principal_id='operator'),idempotency_key='admit.'+source)
def fixture(*,activate=('source','empty.a'),arm=True,episodes=4,sql_factory=G.build):
    # 只从旧夹具取得公开合成种子，新库按先实例池、后来源启用再运行登记的顺序执行所有守卫。
    old,q,c,ts=AT.fixture();d=sqlite3.connect(':memory:',isolation_level=None);d.row_factory=sqlite3.Row;d.executescript(sql_factory().decode())
    try:
        tables=('storage_scope','ingress_storage_profile','ingest_epoch','ingress_source','published_version','run','activation_slot','run_ingest_progress','p1_limit','arm_capacity')
        C.execute(d,[I(table,**row) for table in tables for row in P.rows(old,'SELECT * FROM '+table)])
    finally:old.close()
    for source in ('empty.a','empty.b'):d.execute(*I('ingress_source',source_id=source,source_key=source.encode(),revision='0',contiguous_sequence='0',reject_floor='0',state='synchronized'))
    B.provision(d,T.profile(d,episodes,2));c=T.T.T.context(dict(c,trusted_system_closer=True,source_fault_verified=True,source_identity_verified=True))
    for source in activate:M.reserve(d,request(d,source),c)
    if 'source' in activate:
        C.execute(d,[I('ingress_listener',source_id='source',run_id='r0',artifact_digest=AT.H,binding_body=T.B),
            I('p1_dependency',dependency_id='source.run',sequence=1,source_id='source',run_id='r0',owner_kind='run',owner_ref='r0',execution_id=None,recovery_id=None,artifact_digest=AT.H,binding_body=T.B)])
    d.execute(*A.preflight_step(d,'preflight','r0',ts,c))
    if arm:A.reserve(d,q,c);AT.receive_all(d,ts);A.apply(d,lambda:A.complete_steps(d,q['operation_id'],c))
    c.update(source_authenticated=True,age_verified=True,plan_verified=True,runtime_current=True,budget_valid=True,window_valid=True,parameters_verified=True,
        origin_commit_observed=True,dependencies_verified=True,receipt_verified=True,receipt_durable=True,terminal_evidence_verified=True,completion_verified=True,
        required_evidence=True,no_unresolved=True,tick='1000',clock=dict(domain='synthetic.domain'),runtime=dict(id='synthetic.runtime'),first_observation=dict(tick='900',domain='synthetic.domain'))
    actions=[dict(step_id='step.'+str(i),required=True,controller_scope=t['controller_scope'],request=dict(action_id='synthetic.set',value=i),parameters_ref=dict(id='parameters.'+str(i),digest=AT.H)) for i,t in enumerate(ts)]
    c['evaluations']={'r0':dict(qualified=True,matched=True,target_state_id=None,steps=actions)}
    return d,q,c,ts
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
        check('生成SQL字节',(HERE/'seamer-source-budget.sql').read_bytes()==G.build());check('生成Schema字节',(HERE/'source-budget.schema.json').read_bytes()==G.schema_bytes())
        M.jsonschema.Draft202012Validator.check_schema(G.schema())
        d,q,c,ts=f(activate=(),arm=False);req=request(d);writes=AT.planned(d,lambda:M.reserve_steps(d,req,c));check('106表组合',len(C.snapshot(d)),106)
        for i in range(len(writes)):
            denied('启用漏写'+str(i),d,lambda i=i:C.execute(d,writes[:i]+writes[i+1:]))
            denied('启用写后故障'+str(i),d,lambda i=i:M.reserve(d,req,c,fail_after=i),'injected')
        denied('直接注册不得漏预留',d,lambda:C.execute(d,[I('ingress_registry',source_id='source',revision='1')]))
        denied('待启用source不能消费实例池',d,lambda:B.protect(d,C.fault(),c),'source_budget_not_reserved_or_exhausted')
        for field in ('authorized','human','current','source_identity_verified'):
            denied('缺准入资格'+field,d,lambda field=field:M.reserve(d,req,dict(c,**{field:False})),'source_admission_authority')
        for field in req:
            bad=copy.deepcopy(req);bad.pop(field);denied('缺字段'+field,d,lambda bad=bad:M.reserve(d,bad,c))
        for patch in (dict(episodes='0'),dict(episodes='01'),dict(episodes='65537'),dict(episodes='99999999999999999999'),dict(episodes='3'),dict(extra=True),
            dict(expected_source_revision='1'),dict(source_key_digest='sha256:'+'0'*64),dict(pool_profile_digest='sha256:'+'0'*64)):
            denied('准入错配'+str(patch),d,lambda patch=patch:M.reserve(d,dict(req,**patch),c))
        for table,patch in [('sb_commit',dict(request_digest='sha256:'+'0'*64)),('sb_commit',dict(reservation_id='wrong')),('sb_commit',dict(registry_revision='2')),
            ('sb_commit',dict(audit_body=b'')),('sb_commit',dict(notification_body=b'')),('sb_reservation',dict(episodes=1)),('sb_reservation',dict(source_id='empty.a'))]:
            denied('封存错配'+str(patch),d,lambda table=table,patch=patch:C.execute(d,C.mutate(writes,table,patch)))
        padded=dict(req,padding='');padded['padding']='x'*(4096-len(P.canonical(padded)));oversized=P.canonical(padded)
        check_bytes=C.mutate(writes,'sb_reservation',dict(request_body=oversized,request_digest=P.digest(oversized)))
        check_bytes=C.mutate(check_bytes,'sb_commit',dict(request_digest=P.digest(oversized)))
        denied('SQL预留行必须计入BLOB编码扩张',d,lambda:C.execute(d,check_bytes))
        denied('SQL封存行不得超过固定包络',d,lambda:C.execute(d,C.mutate(writes,'sb_commit',dict(audit_body=b'x'*1024,notification_body=b'y'*1024))))
        check('来源启用受理',M.reserve(d,req,c),'accepted');check('预留两份',d.execute('SELECT unallocated_episodes FROM sb_unallocated').fetchone()[0],2)
        prior=C.snapshot(d);check('准入重复查原',M.reserve(d,req,dict(c,human=False,source_identity_verified=False)),'existing');check('重复零写',C.snapshot(d)==prior)
        denied('同来源换请求不能补额度',d,lambda:M.reserve(d,dict(req,idempotency_key='new'),c),'identity_conflict')
        denied('同幂等键换来源',d,lambda:M.reserve(d,dict(request(d,'empty.a'),idempotency_key=req['idempotency_key']),c),'identity_conflict')
        req2=request(d,'empty.a');check('第二来源精确占满',M.reserve(d,req2,c),'accepted')
        check('未分配份额为零',d.execute('SELECT unallocated_episodes FROM sb_unallocated').fetchone()[0],0)
        denied('第三来源不可超卖',d,lambda:M.reserve(d,request(d,'empty.b','1'),c),'capacity')
        check('拒绝不启用第三来源',d.execute("SELECT count(*) FROM ingress_registry WHERE source_id='empty.b'").fetchone()[0],0)
        B.protect(d,C.fault('1','empty.a'),c);B.protect(d,C.fault('2','empty.a'),c)
        check('消费不回收可分配额度',d.execute('SELECT unallocated_episodes FROM sb_unallocated').fetchone()[0],0)
        denied('消费后不能将spent卖给新来源',d,lambda:M.reserve(d,request(d,'empty.b','1'),c),'capacity')
        check('其他来源独享两份仍在',d.execute("SELECT episodes_left FROM sb_balance WHERE source_id='source'").fetchone()[0],2)
        src=R.one(d,'ingress_source','source_id','empty.a');d.execute("UPDATE ingress_source SET state='closed',revision=? WHERE source_id='empty.a'",(P.inc(src['revision']),))
        denied('来源关闭不释放预留',d,lambda:M.reserve(d,request(d,'empty.b','1'),c),'capacity')
        before=C.snapshot(d);M.reserve(d,req2,c);check('耗尽来源仍查原不补额度',C.snapshot(d)==before)
        for table in ('sb_reservation','sb_commit'):
            denied('预留不可删'+table,d,lambda table=table:C.execute(d,[('DELETE FROM '+table,())]),'immutable')
            denied('预留不可改'+table,d,lambda table=table:C.execute(d,[('UPDATE '+table+' SET source_id=source_id',())]),'immutable')
        denied('耗尽来源不能新增listener',d,lambda:C.execute(d,[I('ingress_listener',source_id='empty.a',run_id='r0',artifact_digest=AT.H,binding_body=T.B)]),'source_budget_unavailable')
        dep=I('p1_dependency',dependency_id='empty.dep',sequence=1,source_id='empty.a',run_id='r0',owner_kind='run',owner_ref='r0',execution_id=None,recovery_id=None,artifact_digest=AT.H,binding_body=T.B)
        denied('耗尽来源不能新增运行依赖',d,lambda:C.execute(d,[dep]),'source_budget_unavailable')
        # 一个来源只申请一份，不得借其尚未分配的第二份；其他来源可分得剩余额度。
        z,qq,cc,tt=f(activate=(),arm=False);M.reserve(z,request(z,'empty.a','1'),cc);B.protect(z,C.fault('1','empty.a'),cc)
        denied('申请一份只能消费一次',z,lambda:B.protect(z,C.fault('2','empty.a'),cc),'source_budget_not_reserved_or_exhausted')
        M.reserve(z,request(z,'source','2'),cc);M.reserve(z,request(z,'empty.b','1'),cc);check('不等份预留总额守恒',z.execute('SELECT sum(episodes) FROM sb_reservation').fetchone()[0],4)
        # 缓存的启用写集不得越过另一个来源已经提交的额度占用。
        z,qq,cc,tt=f(activate=('source',),arm=False);old=AT.planned(z,lambda:M.reserve_steps(z,request(z,'empty.a'),cc))
        M.reserve(z,request(z,'empty.b'),cc);denied('过期启用写集拒绝超卖',z,lambda:C.execute(z,old),'capacity')
        # 正常事件到R5保留可执行性，其他来源耗尽不会耗掉本来源的独享份数。
        z,qq,cc,tt=f();B.protect(z,C.fault('1','empty.a'),cc);B.protect(z,C.fault('2','empty.a'),cc)
        event=dict(source_id='source',event_id='event.1',source_sequence='1',payload=dict(value=True));check('其他来源耗尽仍可摄取',F.receive_event(z,event,cc),'committed')
        ex=FLOW.active(z);A.apply(z,lambda:F.anchor_steps(z,ex,cc))
        for i in range(2):FLOW.success(z,ex,'step.'+str(i),cc)
        check('正常双动作完成R5',F.finish(z,ex,cc),'committed');check('回到armed',R.one(z,'run','run_id','r0')['lifecycle'],'armed')
        check('来源独享保护份额未被普通动作消费',z.execute("SELECT episodes_left FROM sb_balance WHERE source_id='source'").fetchone()[0],2)
        # 真正P1消耗本来源预算后，旧终态及查原保留，新写入不能绕过预算门槛。
        z,qq,cc,tt=f();F.receive_event(z,event,cc);ex=FLOW.active(z);A.apply(z,lambda:F.anchor_steps(z,ex,cc));ready=AT.planned(z,lambda:F.ready_steps(z,ex,'step.0',cc))
        B.protect(z,C.fault('1'),cc);B.protect(z,C.fault('2'),cc)
        denied('缓存ready在预算耗尽后拒绝',z,lambda:C.execute(z,ready),'source_budget_run_unavailable')
        before=C.snapshot(z);check('耗尽后旧事件仍查原',F.receive_event(z,event,cc),'duplicate');check('旧事件查原零写',C.snapshot(z)==before)
        # 缓存提交/发送记账均重新核验来源预算；已在途回执仍可记录，不触发重新发送。
        z,qq,cc,tt=f();F.receive_event(z,event,cc);ex=FLOW.active(z);A.apply(z,lambda:F.anchor_steps(z,ex,cc));A.apply(z,lambda:F.ready_steps(z,ex,'step.0',cc))
        submit=AT.planned(z,lambda:F.submit_steps(z,ex,'step.0',cc));C.execute(z,submit);sub=FLOW.submission(z,ex,'step.0');ident=sub+'.attempt'
        attempt=F.event(z,'r0','ATTEMPT',ident)+[I('submission_attempt',attempt_id=ident,submission_id=sub,run_id='r0',runtime_binding_ref_body=P.canonical(cc['runtime']),
            clock_body=P.canonical(cc['clock']),tick_ns=cc['tick'],attempt_body=P.canonical(dict(submission_id=sub)),tx_id=ident+'.ATTEMPT'),
            ("UPDATE command_submission SET state='attempt_recorded',attempt_id=? WHERE submission_id=?",(ident,sub))]
        B.protect(z,C.fault('1'),cc);B.protect(z,C.fault('2'),cc)
        denied('缓存attempt在耗尽后拒绝',z,lambda:C.execute(z,attempt),'source_budget_run_unavailable')
        z,qq,cc,tt=f();F.receive_event(z,event,cc);ex=FLOW.active(z);A.apply(z,lambda:F.anchor_steps(z,ex,cc));A.apply(z,lambda:F.ready_steps(z,ex,'step.0',cc))
        submit=AT.planned(z,lambda:F.submit_steps(z,ex,'step.0',cc));B.protect(z,C.fault('1'),cc);B.protect(z,C.fault('2'),cc)
        denied('缓存submission在耗尽后拒绝',z,lambda:C.execute(z,submit),'source_budget_run_unavailable')
        z,qq,cc,tt=f();ec=dict(cc,evaluations={});incoming=dict(event,source_id='empty.a');ingress=AT.planned(z,lambda:F.ingress_steps(z,incoming,ec))
        B.protect(z,C.fault('1','empty.a'),cc);B.protect(z,C.fault('2','empty.a'),cc)
        denied('缓存摄取在耗尽后拒绝',z,lambda:C.execute(z,ingress),'source_budget_ingress_unavailable')
        z,qq,cc,tt=f();F.receive_event(z,event,cc);ex=FLOW.active(z);A.apply(z,lambda:F.anchor_steps(z,ex,cc));A.apply(z,lambda:F.ready_steps(z,ex,'step.0',cc));A.apply(z,lambda:F.submit_steps(z,ex,'step.0',cc))
        sub=FLOW.submission(z,ex,'step.0');F.attempt(z,sub,cc);value=F.receipt(z,sub);B.protect(z,C.fault('1'),cc);B.protect(z,C.fault('2'),cc)
        A.apply(z,lambda:F.accept_steps(z,sub,value,cc));check('耗尽不拒绝已在途受理证据',R.one(z,'command_submission','submission_id',sub)['state'],'accepted')
        check('已有attempt只查原',F.attempt(z,sub,cc),'query_original_identity_only')
        # 独享预留元数据的三行上界也必须装入保护包络。
        z,qq,cc,tt=f();ww=T.planned(z,C.fault('1','empty.a'),cc)
        per=z.execute('SELECT logical_rows,logical_bytes FROM ib_pool').fetchone()
        denied('省掉准入行成本',z,lambda:C.execute(z,C.mutate(ww,'ib_use',dict(observed_rows=per[0]))),'source_budget_not_reserved_or_exhausted')
        denied('省掉准入字节成本',z,lambda:C.execute(z,C.mutate(ww,'ib_use',dict(observed_bytes=per[1]))),'source_budget_not_reserved_or_exhausted')
        for i,conn in enumerate(dbs):check('外键完整'+str(i),list(conn.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'source-budget-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=106,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
