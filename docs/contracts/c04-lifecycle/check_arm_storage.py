"""普通arm同库登记、准备完成与保护路径的内存SQLite验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_arm_storage as G
import arm_storage_model as M
import check_arm_budget as A
import check_qualification as Q
I=M.I;P=M.P;R=M.R;C=Q.C;B=Q.B;H=Q.H
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(A.INPUTS+G.SOURCES+[HERE/n for n in ('ARM_STORAGE.md','arm_storage_model.py','check_arm_storage.py','seamer-arm.sql')]))
def fixture(*,zero=False,capacity=None,sql_factory=G.build):
    db=sqlite3.connect(':memory:',isolation_level=None);db.row_factory=sqlite3.Row;db.executescript(sql_factory().decode())
    profile=A.profile()
    if capacity:profile['capacity'].update(capacity)
    targets=[dict(controller_id='route.'+x,registration_id='registration.'+x,preparation_id='preparation.'+x,
        controller_scope=dict(authority_service_id='controller-'+x,database_instance_id='controller.db'),
        request_body=dict(kind='internal_preparation_request',preparation_id='preparation.'+x)) for x in (() if zero else ('a','b'))]
    seeds=[I('storage_scope',singleton=1,authority_id='seamer',database_id='db',format_version='automation-storage/0.1.0-draft.2'),
        I('ingress_storage_profile',singleton=1,version='ingress-storage/0.1.0-draft.1'),I('ingest_epoch',epoch='epoch',state='open',last_sequence='0'),
        I('ingress_source',source_id='source',source_key=B,revision='0',contiguous_sequence='0',reject_floor='0',state='synchronized'),
        I('ingress_registry',source_id='source',revision='1'),I('published_version',definition_id='d0',version='1',artifact_digest=H,artifact_body=B),
        I('run',run_id='r0',definition_id='d0',version='1',revision='1',arm_generation='0',lifecycle='disarmed',dispatch_eligible=0),
        I('activation_slot',definition_id='d0',revision='1',active_run_id=None,version=None),
        I('ingress_listener',source_id='source',run_id='r0',artifact_digest=H,binding_body=B),
        I('run_ingest_progress',run_id='r0',revision='0',epoch='epoch',last_sequence='0',baseline_body=B,last_commit_id=None),
        I('p1_limit',singleton=1,profile_body=B,max_dependencies=100,max_preparations=100,max_plans=10,max_runs=10,max_targets=20,max_payload_bytes=1000000),
        I('p1_dependency',dependency_id='source.run',sequence=1,source_id='source',run_id='r0',owner_kind='run',owner_ref='r0',execution_id=None,recovery_id=None,artifact_digest=H,binding_body=B),
        I('arm_capacity',singleton=1,profile_digest=M.B.digest(profile),profile_body=P.canonical(profile),max_operations=100,**{k:int(v) for k,v in profile['capacity'].items()})]
    C.execute(db,seeds)
    ctx=dict(authorized=True,human=True,current=True,inventory_verified=True,controller_capacity_verified=True,clock_body=B,
        issued_tick='100',expires_tick='200',now_tick='150',inventory_digest=H,forecast=copy.deepcopy(A.SHAPE),target_manifest_digest=P.digest(P.canonical(targets)))
    db.execute(*M.preflight_step(db,'preflight','r0',targets,ctx))
    request=dict(operation_id='arm.1',run_id='r0',preflight_id='preflight',request_epoch='epoch.1',actor=dict(principal_id='operator'),idempotency_key='arm.key')
    return db,request,ctx,targets
def planned(db,builder):
    db.execute('BEGIN IMMEDIATE')
    try:return builder()
    finally:db.rollback()
def receive_all(db,targets):
    for t in targets:
        ident=t['registration_id'];M.apply(db,lambda ident=ident:[M.attempt_step(db,ident)])
        value=Q.F.granted(db,ident);M.receive(db,ident,value,t['controller_scope'])

def reconcile_preflight(db):
    """显式暂停并建立新预览；不将它与后续R2误当成同一事务。"""
    run=R.one(db,'run','run_id','r0');slot=R.one(db,'activation_slot','definition_id','d0');rev=P.inc(run['revision'])
    C.execute(db,[("UPDATE run SET lifecycle='paused',dispatch_eligible=0,revision=? WHERE run_id='r0'",(rev,)),
        I('pause_latch',latch_id='resume.latch',run_id='r0',reason='operator_pause',created_revision=rev,body=B),
        I('recovery_preview',preview_id='resume.preview',run_id='r0',run_revision=rev,slot_revision=slot['revision'],prior_execution_id=None,
          preview_digest=H,plan_digest='recovery.plan',preview_body=B,clock_body=B,issued_tick='100',expires_tick='200')])
    request=dict(operation_id='recovery.1',execution_id='recovery.execution',run_id='r0',preview_id='resume.preview',request_epoch='epoch.1',
        actor=dict(principal_id='operator'),idempotency_key='resume.key',mode='reconcile_commit',kind='rule',plan_digest='recovery.plan',
        resolved_latches=[x[0] for x in db.execute("SELECT latch_id FROM pause_latch WHERE run_id='r0' AND cleared_start_id IS NULL ORDER BY latch_id")],targets=[])
    gates=dict(authorized=True,current=True,old_resources_clear=True,clock_body=B,now=150)
    return request,gates

def reconcile(db):
    """从真实arm就绪前态推进R2/R4；所有守卫始终启用，外部核对证据为合成。"""
    request,gates=reconcile_preflight(db)
    R.reserve(db,request,gates);R.apply(db,lambda:R.ready_steps(db,request['operation_id']));Q.F.execution_plan(db,request)
    R.apply(db,lambda:R.start_steps(db,request['operation_id'],gates))
    C.execute(db,R.event('terminal','r0','STEP_TERMINAL')+[
        I('step_terminal',terminal_id='terminal',execution_id=request['execution_id'],step_id='step',run_id='r0',outcome='succeeded',evidence_body=B,result_ref_body=B,tx_id='terminal.STEP_TERMINAL'),
        ("UPDATE step_state SET state='finished',outcome='succeeded',terminal_id='terminal',revision='2' WHERE execution_id=?",(request['execution_id'],))])
    run=R.one(db,'run','run_id','r0');op=R.one(db,'recovery_operation','operation_id',request['operation_id'])
    return R.event('commit','r0','R5')+[
        I('transition_commit',commit_id='commit',run_id='r0',execution_id=request['execution_id'],kind='rule',source_state_id=None,source_state_revision=None,
          target_state_id=None,target_state_revision=None,evidence_set_body=B,commit_body=B,commit_digest=H,tx_id='commit.R5'),
        ("UPDATE execution SET state='succeeded',commit_id='commit' WHERE execution_id=?",(request['execution_id'],)),
        ("UPDATE run SET lifecycle='armed',revision=?,active_execution_id=NULL,dispatch_eligible=1,last_commit_id='commit' WHERE run_id='r0'",(P.inc(run['revision']),)),
        ("UPDATE recovery_operation SET state='completed',revision=? WHERE operation_id=?",(P.inc(op['revision']),request['operation_id'])),
        I('external_evidence',evidence_id='release',authority_id='supervisor',database_id='provider.db',kind='release',object_id='release',revision='1',digest=H,body=B),
        ("UPDATE recovery_lock SET release_id='release' WHERE operation_id=?",(request['operation_id'],))]
def run():
    checks=[];connections=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(stage=0,**kw):
        db,r,c,t=fixture(**kw);connections.append(db)
        if stage:M.reserve(db,r,c)
        if stage>=2:receive_all(db,t)
        if stage>=3:M.apply(db,lambda:M.complete_steps(db,r['operation_id'],c))
        return db,r,c,t
    def denied(name,db,call,reason=None):
        before=C.snapshot(db)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError) as e:
            if reason:assert reason in str(e),(name,str(e),reason)
            check(name,C.snapshot(db)==before);return
        raise AssertionError(name)
    try:
        check('生成布局字节匹配',(HERE/'seamer-arm.sql').read_bytes()==G.build())
        db,r,c,t=f();check('83表',len(C.snapshot(db)),83)
        denied('禁止直接插入armed',db,lambda:C.execute(db,[I('run',run_id='bypass',definition_id='d0',version='1',revision='1',arm_generation='0',lifecycle='armed',dispatch_eligible=1)]),'run_initial_disarmed')
        writes=planned(db,lambda:M.reserve_steps(db,r,c));check('普通布防可靠受理',M.reserve(db,r,c),'accepted')
        check('准备保持disarmed',tuple(db.execute('SELECT lifecycle,dispatch_eligible,arm_generation,active_operation_id,active_execution_id FROM run').fetchone()),('disarmed',0,'1','arm.1',None))
        check('共享身份为arm',db.execute('SELECT kind FROM lifecycle_operation_identity').fetchone()[0],'arm')
        check('全目标有保护登记',db.execute('SELECT count(*) FROM p1_preparation').fetchone()[0],2)
        check('原预算持有',db.execute('SELECT logical_rows FROM arm_budget_reservation').fetchone()[0],int(M.B.cost(A.profile(),A.SHAPE)['logical_rows'])*2)
        before=C.snapshot(db);check('重复原请求查账',M.reserve(db,r,c),'existing');check('重复不写',C.snapshot(db)==before)
        conflict=copy.deepcopy(r);conflict['preflight_id']='other'
        denied('重复键异内容拒绝',db,lambda:M.reserve(db,conflict,c),'identity_conflict')
        for i in range(len(writes)):
            x,rr,cc,tt=f();denied('登记缺写'+str(i),x,lambda x=x,i=i:C.execute(x,writes[:i]+writes[i+1:]))
            x,rr,cc,tt=f();denied('登记写后故障'+str(i),x,lambda x=x,rr=rr,cc=cc,i=i:M.reserve(x,rr,cc,fail_after=i),'injected')
        for name,table,patch in [('目标同数换别名','arm_target',dict(controller_id='wrong')),('错登记身份','arm_target',dict(registration_id='wrong')),
            ('准备错Controller','p1_preparation',dict(controller_database='other')),('run跳修订','arm_operation',dict(run_after='9')),
            ('代次跳跃','arm_operation',dict(generation='9')),('时基不符','arm_operation',dict(clock_body=b'other')),('截止等号','arm_operation',dict(now_tick='200')),
            ('非法U20尾换行','arm_operation',dict(now_tick='150\n')),('预算少记行','arm_budget_reservation',dict(logical_rows=1)),('预算错profile','arm_budget_reservation',dict(profile_digest=H)),
            ('缺集合正文','arm_register_commit',dict(manifest_body=b'[]'))]:
            x,rr,cc,tt=f();denied(name,x,lambda x=x,table=table,patch=patch:C.execute(x,C.mutate(writes,table,patch)))
        for dim in M.B.G.DIMENSIONS:
            x,rr,cc,tt=f(capacity={dim:'1'});denied(dim+'满额无半次布防',x,lambda x=x,rr=rr,cc=cc:M.reserve(x,rr,cc),'capacity')
        denied('尚未准备不能armed',db,lambda:M.apply(db,lambda:M.complete_steps(db,r['operation_id'],c)),'unqualified')
        denied('不能直接改armed',db,lambda:C.execute(db,[("UPDATE run SET revision='3',lifecycle='armed',dispatch_eligible=1,active_operation_id=NULL WHERE run_id='r0'",())]))
        denied('不能直接改running开放',db,lambda:C.execute(db,[("UPDATE run SET revision='3',lifecycle='running',dispatch_eligible=1 WHERE run_id='r0'",())]),'dispatch_open')
        receive_all(db,t);complete=planned(db,lambda:M.complete_steps(db,r['operation_id'],c));before=C.snapshot(db)
        ident=t[0]['registration_id'];value=Q.F.granted(db,ident)
        M.receive(db,ident,value,t[0]['controller_scope']);check('重复准备观察零写',C.snapshot(db)==before)
        M.apply(db,lambda:M.complete_steps(db,r['operation_id'],c));check('全部准备后armed',tuple(db.execute('SELECT lifecycle,dispatch_eligible,active_operation_id FROM run').fetchone()),('armed',1,None))
        check('arm不创建执行',db.execute('SELECT count(*) FROM execution').fetchone()[0],0)
        check('ready不退预算',C.snapshot(db)['arm_budget_reservation']==before['arm_budget_reservation'])
        for i in range(len(complete)):
            x,rr,cc,tt=f(2);denied('完成缺写'+str(i),x,lambda x=x,i=i:C.execute(x,complete[:i]+complete[i+1:]))
            x,rr,cc,tt=f(2);denied('完成写后故障'+str(i),x,lambda x=x,rr=rr,cc=cc,i=i:M.apply(x,lambda:M.complete_steps(x,rr['operation_id'],cc),fail_after=i),'injected')
        for patch,reason in (("revision='3'",'arm_ready_projection'),("active_run_id=NULL,version=NULL",'slot_owned')):
            x,rr,cc,tt=f(2);denied('最终封存重核槽'+patch,x,lambda x=x,patch=patch:C.execute(x,complete[:2]+[('UPDATE activation_slot SET '+patch,())]+complete[2:]),reason)
        for flag in ('authorized','human','current','inventory_verified','controller_capacity_verified'):
            x,rr,cc,tt=f(2);cc[flag]=False
            denied('完成前提供者失效'+flag,x,lambda x=x,rr=rr,cc=cc:M.apply(x,lambda:M.complete_steps(x,rr['operation_id'],cc)),'unqualified_context')
        x,rr,cc,tt=f(2);cc['inventory_digest']='sha256:'+'0'*64
        denied('库存摘要改变',x,lambda:M.apply(x,lambda:M.complete_steps(x,rr['operation_id'],cc)),'inventory_changed')
        x,rr,cc,tt=f(2);C.execute(x,[("UPDATE ingress_source SET revision='1' WHERE source_id='source'",())])
        denied('来源修订改变拒完成',x,lambda:M.apply(x,lambda:M.complete_steps(x,rr['operation_id'],cc)),'unqualified')
        x,rr,cc,tt=f();budget=json.loads(dict(zip(writes[1][0].split('(')[1].split(')')[0].split(','),writes[1][1]))['budget_body']);budget['held']['logical_rows']='1'
        denied('同步少记列与正文仍拒绝',x,lambda:C.execute(x,C.mutate(writes,'arm_budget_reservation',dict(logical_rows=1,budget_body=P.canonical(budget)))),'arm_budget_cost')
        x,rr,cc,tt=f(3);finish=reconcile(x)
        check('reconcile执行中保持关闭',tuple(x.execute('SELECT lifecycle,dispatch_eligible FROM run').fetchone()),('running',0))
        for i in range(len(finish)):
            denied('R5写后故障'+str(i),x,lambda i=i:M.apply(x,lambda:finish,fail_after=i),'injected')
        C.execute(x,finish)
        check('reconcile成功回armed',tuple(x.execute('SELECT lifecycle,dispatch_eligible,active_execution_id,last_commit_id FROM run').fetchone()),('armed',1,None,'commit'))
        check('双类型身份共存',[v[0] for v in x.execute('SELECT kind FROM lifecycle_operation_identity ORDER BY kind')],['arm','recovery'])
        check('恢复保留原arm预算',x.execute('SELECT count(*) FROM arm_budget_reservation').fetchone()[0],1)
        check('恢复组合外键完整',list(x.execute('PRAGMA foreign_key_check')),[])
        C.execute(x,[("UPDATE run SET lifecycle='paused',dispatch_eligible=0,last_commit_id=NULL,revision=?",(P.inc(R.one(x,'run','run_id','r0')['revision']),))])
        denied('不能借旧transition重开',x,lambda:C.execute(x,[("UPDATE run SET lifecycle='armed',dispatch_eligible=1,last_commit_id='commit',revision=?",(P.inc(R.one(x,'run','run_id','r0')['revision']),))]))
        x,rr,cc,tt=f(1);ident=tt[0]['registration_id'];M.apply(x,lambda:[M.attempt_step(x,ident)]);value=Q.F.granted(x,ident)
        for i in range(3):denied('观察采用写后故障'+str(i),x,lambda i=i:M.receive(x,ident,value,value['binding']['controller_scope'],fail_after=i),'injected')
        for stage in (1,2,3):
            x,rr,cc,tt=f(stage);P.protect(x,C.fault());check('来源保护覆盖arm阶段'+str(stage),x.execute('SELECT count(*) FROM p1_preparation_member').fetchone()[0],2)
            denied('来源保护后不完成'+str(stage),x,lambda:M.apply(x,lambda:M.complete_steps(x,rr['operation_id'],cc)))
        x,rr,cc,tt=f(2);Q.Q.withdraw(x,'registration.a',Q.withdrawal(x),Q.PROVIDER)
        check('资格撤回完整arm目标',x.execute('SELECT count(*) FROM pq_target').fetchone()[0],2)
        denied('撤回阻止arm完成',x,lambda:M.apply(x,lambda:M.complete_steps(x,rr['operation_id'],cc)))
        x,rr,cc,tt=f(1);P.protect(x,C.fault());denied('保护后不能首次尝试',x,lambda:M.apply(x,lambda:[M.attempt_step(x,'registration.a')]),'ineligible')
        x,rr,cc,tt=f(3,zero=True);check('零设备普通布防',x.execute('SELECT lifecycle FROM run').fetchone()[0],'armed');check('零设备仍有预算',x.execute('SELECT count(*) FROM arm_budget_reservation').fetchone()[0],1)
        check('组合外键完整',list(db.execute('PRAGMA foreign_key_check')),[])
        for table in G.TABLES:
            denied(table+'不可删除',db,lambda table=table:C.execute(db,[('DELETE FROM '+table,())]),'immutable')
        return checks
    finally:
        for db in connections:db.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args();target=HERE/'arm-storage-report.json'
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    def bindings():return {p.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else p.read_bytes()).hexdigest() for p in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=83,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
