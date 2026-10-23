"""仅内存验证P1完整写集及P4目标来源，不访问网络、设备或产品数据库。"""
import argparse,hashlib,json,sqlite3,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path[:0]=[str(HERE.parent/'c04-storage'),str(HERE.parent/'c08-controller')]
import check_dispatch as D
import build_storage as G
import storage_model as M
import protection_delivery_model as SP
import preparation_delivery_model as PO
I=M.row;B=b'synthetic-evidence';H=M.digest(B)
INPUTS=list(dict.fromkeys(D.INPUTS+D.core.INPUTS+G.SOURCES+[HERE/n for n in ('STORAGE.md','storage_model.py','check_storage.py','seamer-protection.sql')]
  +[HERE.parent/'c08-controller'/n for n in ('protection_delivery_model.py','protection-delivery.schema.json','build_protection_delivery.py',
    'preparation_delivery_model.py','preparation-delivery.schema.json','build_preparation_delivery.py')]))


def snapshot(db):
    return {t:sorted([tuple(r) for r in db.execute('SELECT * FROM '+t)],key=repr)
      for t, in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")}


def execute(db,steps,fail=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        for i,(sql,args) in enumerate(steps):
            db.execute(sql,args)
            if fail==i:raise RuntimeError('injected')
        db.commit()
    except BaseException:db.rollback();raise


def fault(n='1',source='source'):
    return dict(fault_id='fault.'+n,source_id=source,detector_domain='detector.1',detector_sequence=n,reason='source_gap')


def steps(db,f=None):
    db.execute('BEGIN IMMEDIATE')
    try:return M.plan_steps(db,f or fault())
    finally:db.rollback()


def registration(db,run,ca,mode='arm',execution=None,recovery=None):
    generation=db.execute('SELECT arm_generation FROM run WHERE run_id=?',(run,)).fetchone()[0]
    ident=run+'.'+ca;sequence=db.execute('SELECT coalesce(max(sequence),0)+1 FROM p1_preparation').fetchone()[0]
    binding=dict(controller_scope=dict(authority_service_id=ca,database_instance_id='database.1'),
      origin_scope=dict(authority_service_id='seamer',database_instance_id='database'),preparation_id='prepare.'+ident,
      run_id=run,generation=generation,mode=mode,execution_id=execution,request_digest=H)
    return I('p1_preparation',registration_id=ident,sequence=sequence,run_id=run,generation=generation,
      controller_authority=ca,controller_database='database.1',preparation_id=binding['preparation_id'],mode=mode,
      execution_id=execution,request_digest=H,recovery_operation_id=recovery,recovery_controller_id=ca if recovery else None,
      binding_body=M.canonical(binding),request_body=B,outbox_body=B,audit_body=B)


def dependency(db,ident,run,kind='run',owner=None,source='source'):
    return I('p1_dependency',dependency_id=ident,sequence=db.execute('SELECT coalesce(max(sequence),0)+1 FROM p1_dependency').fetchone()[0],
      source_id=source,run_id=run,owner_kind=kind,owner_ref=owner or run,execution_id=owner if kind=='execution' else None,
      recovery_id=owner if kind=='recovery' else None,artifact_digest='artifact',binding_body=B)


def fixture(stage=3,bridge=True,**limits):
    # 复用旧候选真实约束下的R2/R4/提交历史。新布局并非生产迁移，旧BODY仍是合成原件。
    db,ctx=D.core.fixture(1)
    db.executescript((HERE.parent/'c04-storage/dispatch.sql').read_text(encoding='utf-8'))
    for run in ('run.second','run.completed','unrelated'):
        db.execute(*I('run',run_id=run,definition_id='definition',version='1',revision='1',arm_generation='2',lifecycle='armed',dispatch_eligible=1))
    db.executescript(G.extension().decode())
    profile=dict(singleton=1,profile_body=B,max_dependencies=100,max_preparations=100,max_plans=10,max_runs=10,max_targets=20,max_payload_bytes=1000000)
    profile.update(limits);db.execute(*I('p1_limit',**profile))
    for source in ('source','other.source','empty.source'):
        db.execute(*I('ingress_source',source_id=source,source_key=source.encode(),revision='1',contiguous_sequence='7',reject_floor='3',state='synchronized'))
    for ident,run,kind,owner in [('dep.run','run','run',None),('dep.old','run','execution','old-execution'),('dep.recovery','run','recovery','operation'),
      ('dep.second','run.second','run',None),('dep.completed','run.completed','run',None)]:
        db.execute(*dependency(db,ident,run,kind,owner))
    db.execute(*dependency(db,'dep.unrelated','unrelated',source='other.source'))
    if bridge:
        for ca in ('controller-a','controller-b'):db.execute(*registration(db,'run',ca,'recovery','execution','operation'))
    for run in ('run.second','run.completed'):db.execute(*registration(db,run,'controller-a'))
    db.execute("UPDATE run SET revision='2',lifecycle='completed',dispatch_eligible=0 WHERE run_id='run.completed'")
    if stage>=0:
        ctx.update(step_kind='action',whole_plan_verified=True,dependencies_verified=True,parameters_verified=True,budget_valid=True,
          window_valid=True,runtime_current=True,origin_commit_observed=True,terminal_evidence_verified=True,completion_verified=True)
        D.core.transact(db,D.core.prepare,ctx);D.core.transact(db,D.plan,ctx);D.core.transact(db,D.core.start,ctx)
        ctx['now']=1000;ctx['response']=D.response(ctx);ctx['completion_command_ref']=ctx['response']['command_ref']
        for action in (D.anchor,D.ready,D.submit,D.attempt,D.adjudicate,D.terminal)[:stage]:D.core.transact(db,action,ctx)
    return db,ctx


def mutate(items,table,changes,ordinal=0):
    out=list(items);seen=0
    for i,(sql,args) in enumerate(items):
        if sql.startswith('INSERT INTO '+table+'('):
            if seen==ordinal:
                names=sql.split('(',1)[1].split(')',1)[0].split(',');v=dict(zip(names,args));v.update(changes);out[i]=I(table,**v);return out
            seen+=1
    raise AssertionError(table)


def observation(binding,revision=1):
    return SP.seal(dict(contract_version=SP.VERSION,binding=binding,fence_id='fence.1',cut_ref=dict(id='fence.1',bytes_digest=H),
      receipt_ref=dict(id='receipt.1',bytes_digest=H),prepare_closure_ref=dict(id='closure.1',digest=H),status_revision=str(revision),
      state='applied' if revision==1 else 'indeterminate',cause=dict(kind='initial' if revision==1 else 'prepare_closure',object_id='fence.1' if revision==1 else 'closure.1')))


def run():
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,observed=actual,expected=expected))
    def c(**kw):db,ctx=fixture(**kw);connections.append(db);return db,ctx
    def denied(name,db,action,reason=None):
        before=snapshot(db)
        try:action()
        except (sqlite3.IntegrityError,ValueError,RuntimeError,SP.jsonschema.ValidationError,D.core.Rejected) as e:
            if reason:assert reason in str(e),(name,str(e),reason)
        else:raise AssertionError(name+':未拒绝')
        check(name+'全库回滚',snapshot(db)==before)
    try:
        check('生成物等于源组合',(HERE/'seamer-protection.sql').read_bytes()==G.build())
        db,ctx=c();fresh=sqlite3.connect(':memory:',isolation_level=None);connections.append(fresh);fresh.executescript(G.build().decode())
        schema=lambda d:list(d.execute("SELECT type,name,sql FROM sqlite_schema ORDER BY type,name"))
        check('新库和历史夹具扩展布局一致',[tuple(r) for r in schema(db)]==schema(fresh))
        check('表数',len(snapshot(db)),63)
        before=snapshot(db);s=steps(db);check('规划不写库',snapshot(db)==before)
        check('空事件匹配集合仍保护依赖',db.execute('SELECT count(*) FROM ingress_listener').fetchone()[0],0)
        check('P1封存',M.protect(db,fault()),'fault.1')
        check('来源边界保留',tuple(db.execute("SELECT revision,state,contiguous_sequence,reject_floor FROM ingress_source WHERE source_id='source'").fetchone()),('2','desynchronized','7','3'))
        check('来源依赖并集',sorted(r[0] for r in db.execute('SELECT run_id FROM p1_run')),['run','run.completed','run.second'])
        check('五条依赖全部捕获',db.execute('SELECT count(*) FROM p1_dependency_member').fetchone()[0],5)
        check('旧unknown与新execution均固定',sorted(r[0] for r in db.execute('SELECT execution_id FROM p1_execution_pin')),['execution','old-execution'])
        check('准备与提交目标并集',sorted(tuple(r) for r in db.execute('SELECT run_id,controller_authority,controller_database FROM p1_controller')),
          [('run','controller','controller-db'),('run','controller-a','database.1'),('run','controller-b','database.1'),('run.completed','controller-a','database.1'),('run.second','controller-a','database.1')])
        check('准备未知响应也保留',db.execute('SELECT count(*) FROM p1_preparation_member').fetchone()[0],4)
        check('尚未发送的提交仍捕获',db.execute('SELECT count(*) FROM p1_submission_member').fetchone()[0],1)
        check('旧unknown没有改写',tuple(db.execute("SELECT state FROM execution WHERE execution_id='old-execution'").fetchone()),('unknown',))
        check('completed不复活不增修订',tuple(db.execute("SELECT lifecycle,revision FROM run WHERE run_id='run.completed'").fetchone()),('completed','2'))
        check('无关run不改写',[tuple(r) for r in db.execute("SELECT * FROM run WHERE run_id='unrelated'")],[r for r in before['run'] if r[0]=='unrelated'])
        check('拒绝下界',sorted(tuple(r) for r in db.execute('SELECT * FROM p1_deny')),[(r,'00000000000000000002') for r in ('run','run.completed','run.second')])
        for table in ('execution','business_state','command_submission','step_state','ingress_inbox','ingress_decision'):
            check(table+'原历史不改写',snapshot(db)[table]==before[table])
        check('外键完整',list(db.execute('PRAGMA foreign_key_check')),[])
        saved=snapshot(db);check('重复fault查原',M.protect(db,fault()),'fault.1');check('重复fault零写',snapshot(db)==saved)
        denied('相同检测键改正文',db,lambda:M.protect(db,{**fault(),'reason':'different'}),'fault_identity_conflict')
        check('不同fault追加独立锁存',M.protect(db,fault('2')),'fault.2')
        check('拒绝下界不降低',sorted(set(r[0] for r in db.execute('SELECT generation FROM p1_deny'))),['00000000000000000002'])
        check('原计划保持原body',db.execute("SELECT plan_body FROM p1_plan WHERE plan_id='fault.1'").fetchone()[0]==saved['p1_plan'][0][-1])
        for i in range(len(s)):
            d,_=c();denied('缺少写入'+str(i),d,lambda d=d,i=i:execute(d,s[:i]+s[i+1:]))
            d,_=c();denied('写后异常'+str(i),d,lambda d=d,i=i:execute(d,s,fail=i))
        for name,table,changes in [
          ('错误来源前态','p1_plan',dict(source_before='0')),('来源修订跳跃','p1_plan',dict(source_after='3')),
          ('错误run前态','p1_run',dict(revision_before='0')),('run修订跳跃','p1_run',dict(revision_after='5')),
          ('登记水位陈旧','p1_plan',dict(dependency_head=5)),('准备水位陈旧','p1_plan',dict(preparation_head=3)),
          ('同数替换来源依赖','p1_dependency_member',dict(dependency_id='dep.unrelated')),
          ('旧执行绑定被换','p1_execution_pin',dict(binding_digest='wrong')),('同数换Controller','p1_controller',dict(controller_database='wrong')),
          ('错配准备目标','p1_preparation_member',dict(target_id='fault.1.target.0')),('错配提交目标','p1_submission_member',dict(target_id='fault.1.target.1')),
          ('P4同数替换binding','sp_target',dict(binding_body=b'{}')),('准备P4同数替换binding','po_target',dict(binding_body=b'{}')),
          ('锁存reason错误','pause_latch',dict(reason='other')),('锁存修订错误','pause_latch',dict(created_revision='1')),
          ('receiver计划摘要换掉','sp_plan',dict(plan_digest='wrong'))]:
            d,_=c();denied(name,d,lambda d=d,t=table,v=changes:execute(d,mutate(s,t,v)))
        d,_=c(bridge=False);denied('旧R2准备缺桥接',d,lambda:M.protect(d,fault()),'protection_member_set')
        d,_=c(bridge=False);denied('启动后不能伪造恢复准备登记',d,lambda:execute(d,[registration(d,'run','controller-a','recovery','execution','operation')]),'preparation_registration')
        d,ctx=c(stage=-1)
        check('恢复准备登记时尚未开放dispatch',tuple(d.execute("SELECT lifecycle,dispatch_eligible FROM run WHERE run_id='run'").fetchone()),('paused',0))
        check('恢复准备原目标仍pending',sorted(set(r[0] for r in d.execute('SELECT state FROM preparation_target'))),['pending'])
        M.protect(d,fault());check('准备途中故障固定全部目标',d.execute('SELECT target_count FROM p1_plan').fetchone()[0],4)
        D.core.transact(d,D.core.prepare,ctx)
        denied('迟到准备回执不能跨新锁存启动',d,lambda:D.core.transact(d,D.core.start,ctx),'new_latch')
        start=dict(start_id='new.start',operation_id='operation',run_id='run',execution_id='execution',mode='execute',run_revision_before='3',run_revision_after='4',slot_revision='2',operation_revision='2',start_body=B,start_digest=H,tx_id='new.tx',tx_phase='R4')
        denied('直接写R4也不能复用拒绝代次',d,lambda:execute(d,[I('execution_start',**start)]),'source_generation_denied')
        d,_=c();denied('规划后新增登记水位',d,lambda:execute(d,[registration(d,'unrelated','extra')]+s),'capacity')
        d,_=c();denied('规划后新增来源依赖',d,lambda:execute(d,[dependency(d,'dep.new','unrelated')]+s),'capacity')
        d,_=c(max_preparations=4);denied('准备登记总量超限',d,lambda:execute(d,[registration(d,'unrelated','extra')]),'preparation_registration')
        d,_=c(max_dependencies=6);denied('依赖登记总量超限',d,lambda:execute(d,[dependency(d,'dep.new','unrelated')]),'source_dependency_registration')
        for limits in (dict(max_runs=2),dict(max_targets=4),dict(max_payload_bytes=1)):
            d,_=c(**limits);denied('超限'+next(iter(limits)),d,lambda d=d:M.protect(d,fault()),'capacity')
        d,_=c(max_plans=1);M.protect(d,fault());denied('计划总量超限',d,lambda:M.protect(d,fault('2')),'capacity')
        for table in G.TABLES:
            d,_=c();M.protect(d,fault())
            column=d.execute('PRAGMA table_info('+table+')').fetchone()[1]
            denied('不可变'+table,d,lambda d=d,t=table,col=column:execute(d,[(f'UPDATE {t} SET {col}={col}',())]),'immutable')
        d,_=c();M.protect(d,fault())
        denied('封存后成员不能扩充',d,lambda:execute(d,[I('p1_dependency_member',plan_id='fault.1',dependency_id='dep.unrelated')]),'sealed')
        for table in ('step_ready','command_submission'):
            r=dict(d.execute('SELECT * FROM '+table).fetchone())
            denied('旧代次拒新'+table,d,lambda t=table,r=r:execute(d,[I(t,**r)]),'source_generation_denied')
        denied('旧代次拒发送尝试',d,lambda:execute(d,[I('submission_attempt',attempt_id='new.attempt',submission_id='submission',run_id='run',runtime_binding_ref_body=B,clock_body=B,tick_ns='1001',attempt_body=B,tx_id='new.tx')]),'source_generation_denied')
        denied('旧代次拒新准备',d,lambda:execute(d,[registration(d,'run','new-controller')]),'preparation_registration')
        d,ctx=c(stage=4);ctx['response']=D.response(ctx,'timeout');D.core.transact(d,D.adjudicate,ctx);M.protect(d,fault())
        check('响应未知提交仍保护',tuple(d.execute('SELECT state FROM command_submission').fetchone()),('indeterminate',))
        for state in ('closed','quarantined'):
            d,_=c();d.execute('UPDATE ingress_source SET revision=?,state=? WHERE source_id=?',('2',state,'source'));M.protect(d,fault())
            check(state+'来源不重新开放',tuple(d.execute("SELECT revision,state FROM ingress_source WHERE source_id='source'").fetchone()),('2' if state=='closed' else '3',state))
        d,_=c();M.protect(d,fault(source='empty.source'));check('无依赖零目标计划',tuple(d.execute('SELECT run_count,target_count,preparation_count FROM p1_plan').fetchone()),(0,0,0))
        denied('零准备不得事后挂接计划',d,lambda:execute(d,[I('po_plan',plan_id='fault.1',plan_digest=H,target_count=1,plan_body=B)]),'unplanned_preparation_observation')
        for field in ('source','run'):
            d,_=c()
            sql="UPDATE ingress_source SET revision=? WHERE source_id='source'" if field=='source' else "UPDATE run SET revision=? WHERE run_id='run'"
            d.execute(sql,('99999999999999999998',));M.protect(d,fault())
            check(field+'20位末值精确',d.execute('SELECT '+('source_after' if field=='source' else 'revision_after')+' FROM '+('p1_plan' if field=='source' else 'p1_run')+(" WHERE run_id='run'" if field=='run' else '')).fetchone()[0],'99999999999999999999')
            denied(field+'耗尽拒绝',d,lambda d=d:M.protect(d,fault('2')),'u20_exhausted')
        d,_=c();denied('无P1不能独立导入P4',d,lambda:execute(d,[I('sp_plan',plan_id='orphan',plan_digest=H,target_count=0,plan_body=B),I('sp_plan_commit',plan_id='orphan',validation_body=B)]),'FOREIGN KEY')
        d,_=c();M.protect(d,fault());target,binding=d.execute('SELECT target_id,binding_body FROM p1_controller ORDER BY target_id LIMIT 1').fetchone();binding=json.loads(binding)
        newer=observation(binding,2);older=observation(binding,1)
        check('先收到失效',SP.receive(d,'fault.1',target,newer,binding['controller_scope']),'stored')
        check('后补历史成功',SP.receive(d,'fault.1',target,older,binding['controller_scope']),'stored')
        check('历史成功不能恢复当前资格',d.execute('SELECT state FROM sp_current_observation').fetchone()[0],'indeterminate')
        check('失效目标仍待保护',d.execute('SELECT count(*) FROM p1_pending_dispatch').fetchone()[0],5)
        denied('接收域错误',d,lambda:SP.receive(d,'fault.1',target,older,dict(authority_service_id='wrong',database_instance_id='database.1')),'authenticated_controller')
        # 准备观察只验绑定到真实P1注册；本轮不冒领Controller导出和运行证据。
        ident,pbody=d.execute('SELECT registration_id,binding_body FROM p1_preparation ORDER BY registration_id LIMIT 1').fetchone();pb=json.loads(pbody)
        value=PO.seal(dict(contract_version=PO.VERSION,binding=pb,preparation_revision='1',previous_revision=None,state='accepted',applied_receipt_ref=None,close_ref=None,completion=None,protection_revision='0',protection_state='not_applicable',cause=None))
        check('准备观察引用P1真实登记',PO.receive(d,'fault.1',ident,value,pb['controller_scope']),'stored')
        check('accepted不等关闭完成',d.execute('SELECT observed_state FROM po_closure_summary').fetchone()[0],'pending')
        return checks
    finally:
        for db in connections:db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'storage-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=63,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
