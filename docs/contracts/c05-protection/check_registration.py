"""新66表内存库验证R2登记、原请求尝试、回执采用和故障保护；不连接外部服务。"""
import argparse,copy,hashlib,importlib.util,json,sqlite3,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path[:0]=[str(HERE.parent/'c04-storage'),str(HERE.parent/'c08-controller')]
import check_storage as C
import storage_model as P
import registration_model as M
import build_registration as G
import preparation_delivery_model as PO
spec=importlib.util.spec_from_file_location('ingress_checks',HERE.parent/'c05-ingress/check_storage.py')
ING=importlib.util.module_from_spec(spec);spec.loader.exec_module(ING)
I=P.row;B=b'synthetic-evidence';H=P.digest(B)
INPUTS=list(dict.fromkeys(C.INPUTS+G.SOURCES+[HERE/n for n in ('REGISTRATION.md','registration_model.py','check_registration.py','seamer-registration.sql')]+[Path(ING.__file__)]))


def fixture(**limits):
    db=sqlite3.connect(':memory:',isolation_level=None);db.row_factory=sqlite3.Row
    db.executescript(G.build().decode())
    seeds=[I('storage_scope',singleton=1,authority_id='seamer',database_id='db',format_version='automation-storage/0.1.0-draft.2'),
      I('ingress_storage_profile',singleton=1,version='ingress-storage/0.1.0-draft.1'),I('ingest_epoch',epoch='epoch',state='open',last_sequence='0'),
      I('ingress_source',source_id='source',source_key=B,revision='0',contiguous_sequence='0',reject_floor='0',state='synchronized'),
      I('ingress_registry',source_id='source',revision='1'),I('published_version',definition_id='d0',version='1',artifact_digest='artifact',artifact_body=B),
      I('run',run_id='r0',definition_id='d0',version='1',revision='1',arm_generation='1',lifecycle='armed',dispatch_eligible=1),
      I('activation_slot',definition_id='d0',revision='1',active_run_id='r0',version='1'),
      I('ingress_listener',source_id='source',run_id='r0',artifact_digest='artifact',binding_body=b'synthetic-binding'),
      I('run_ingest_progress',run_id='r0',revision='0',epoch='epoch',last_sequence='0',baseline_body=B,last_commit_id=None)]
    for sql,args in seeds:db.execute(sql,args)
    # 真实执行既有摄取写集，生成原trigger引用和完整旧执行计划；所有新守卫从建库起存在。
    ING.write_batch(db,('accepted',))
    db.execute("UPDATE execution SET state='unknown' WHERE execution_id='execution0'")
    db.execute("UPDATE run SET revision='3',lifecycle='paused',dispatch_eligible=0 WHERE run_id='r0'")
    db.execute(*I('recovery_preview',preview_id='preview',run_id='r0',run_revision='3',slot_revision='1',prior_execution_id='execution0',
      preview_digest=H,plan_digest='recovery.plan',preview_body=B,clock_body=B,issued_tick='100',expires_tick='200',consumed_operation_id=None))
    db.execute(*I('pause_latch',latch_id='old.latch',run_id='r0',reason='prior_unknown',created_revision='3',body=B,cleared_start_id=None))
    profile=dict(singleton=1,profile_body=B,max_dependencies=100,max_preparations=100,max_plans=10,max_runs=10,max_targets=20,max_payload_bytes=1000000)
    profile.update(limits);db.execute(*I('p1_limit',**profile))
    db.execute(*I('p1_dependency',dependency_id='source.run',sequence=1,source_id='source',run_id='r0',owner_kind='run',owner_ref='r0',execution_id=None,recovery_id=None,artifact_digest='artifact',binding_body=B))
    targets=[dict(controller_id='route.'+x,registration_id='registration.'+x,preparation_id='preparation.'+x,
      controller_scope=dict(authority_service_id='controller-'+x,database_instance_id='controller.db'),
      request_body=dict(kind='internal_preparation_request',preparation_id='preparation.'+x)) for x in ('a','b')]
    request=dict(operation_id='recovery.1',run_id='r0',preview_id='preview',execution_id='recovery.execution',request_epoch='epoch.1',
      actor=dict(principal_id='operator'),idempotency_key='key.1',mode='execute',kind='rule',plan_digest='recovery.plan',resolved_latches=['old.latch'],targets=targets)
    gates=dict(authorized=True,current=True,old_resources_clear=True,clock_body=B,now=150)
    return db,request,gates


def planned(db,request,gates):
    db.execute('BEGIN IMMEDIATE')
    try:return M.reserve_steps(db,request,gates)
    finally:db.rollback()


def granted(db,ident):
    binding=json.loads(db.execute('SELECT binding_body FROM p1_preparation WHERE registration_id=?',(ident,)).fetchone()[0])
    return PO.seal(dict(contract_version=PO.VERSION,binding=binding,preparation_revision='2',previous_revision='1',state='applied',
      applied_receipt_ref=dict(id=ident+'.grant',bytes_digest=H),close_ref=None,completion=None,protection_revision='0',protection_state='not_applicable',cause=None))


def execution_plan(db,request):
    run=request['run_id'];ex=request['execution_id'];tx=ex+'.plan';body=P.canonical(dict(execution_id=ex))
    C.execute(db,[I('transaction_record',tx_id=tx,run_id=run,phase='PLAN',business_id=ex,audit_body=B,event_id=tx+'.event'),
      I('event_outbox',event_id=tx+'.event',tx_id=tx,payload_digest=H,payload_body=B),
      I('execution_plan_set',execution_id=ex,run_id=run,expected_steps=1,plan_digest=request['plan_digest'],plan_body=body,sealed=0,tx_id=tx),
      I('execution_step_plan',execution_id=ex,step_id='step',kind='action' if request['mode']=='execute' else 'reconcile_commit',ordinal=0,required=1,plan_digest='step.plan',plan_body=B),
      I('step_state',execution_id=ex,step_id='step',revision='1',state='waiting',outcome='pending'),
      ('UPDATE execution_plan_set SET sealed=1 WHERE execution_id=?',(ex,))])


def prepare(db,request):
    for t in request['targets']:
        ident=t['registration_id'];M.apply(db,lambda:[M.attempt_step(db,ident,ident+'.attempt',B)])
        value=granted(db,ident);M.apply(db,lambda:M.receipt_steps(db,ident,value,t['controller_scope']))
    M.apply(db,lambda:M.ready_steps(db,request['operation_id']));execution_plan(db,request)


def run():
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,observed=actual,expected=expected))
    def f(**kw):d,r,g=fixture(**kw);connections.append(d);return d,r,g
    def denied(name,db,action,reason=None):
        before=C.snapshot(db)
        try:action()
        except (sqlite3.IntegrityError,ValueError,RuntimeError,PO.jsonschema.ValidationError) as e:
            if reason:assert reason in str(e),(name,str(e),reason)
        else:raise AssertionError(name+':未拒绝')
        check(name+'全库不变',C.snapshot(db)==before)
    try:
        check('生成一致',(HERE/'seamer-registration.sql').read_bytes()==G.build())
        d,r,g=f();check('66表',len(C.snapshot(d)),66);before=C.snapshot(d);s=planned(d,r,g)
        check('规划无写入',C.snapshot(d)==before)
        check('R2与准备原子提交',M.reserve(d,r,g),'accepted')
        check('声明别名与真实scope不混同',sorted(tuple(x) for x in d.execute('SELECT recovery_controller_id,controller_authority FROM p1_preparation')),[('route.a','controller-a'),('route.b','controller-b')])
        check('双向集合各两项',[d.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('preparation_target','p1_preparation')],[2,2])
        check('未发送库存',sorted(x[0] for x in d.execute('SELECT classification FROM pr_recovery_inventory')),['unattempted','unattempted'])
        check('旧执行真实来源保留',d.execute("SELECT decision_id FROM ingress_execution WHERE execution_id='execution0'").fetchone()[0],'decision0')
        check('旧unknown保留',d.execute("SELECT state FROM execution WHERE execution_id='execution0'").fetchone()[0],'unknown')
        saved=C.snapshot(d);check('重复R2查原',M.reserve(d,r,g),'existing');check('重复R2零写',C.snapshot(d)==saved)
        denied('重复R2仍须身份有效',d,lambda:M.reserve(d,r,{**g,'authorized':False}),'unqualified_context')
        changed=copy.deepcopy(r);changed['targets'][0]['controller_scope']['database_instance_id']='wrong'
        denied('重复请求换目标',d,lambda:M.reserve(d,changed,g),'identity_conflict')
        prepare(d,r);M.apply(d,lambda:M.start_steps(d,r['operation_id'],g))
        check('完整R2至R4',tuple(d.execute("SELECT lifecycle,dispatch_eligible FROM run WHERE run_id='r0'").fetchone()),('running',1))
        check('原unknown不被恢复覆盖',d.execute("SELECT state FROM execution WHERE execution_id='execution0'").fetchone()[0],'unknown')
        check('外键全部满足',list(d.execute('PRAGMA foreign_key_check')),[])
        for i in range(len(s)):
            d,r,g=f();denied('R2缺写'+str(i),d,lambda d=d,i=i:C.execute(d,s[:i]+s[i+1:]))
            d,r,g=f();denied('R2写后故障'+str(i),d,lambda d=d,i=i:C.execute(d,s,fail=i))
        d,r,g=f();old=[x for x in s if not x[0].startswith(('INSERT INTO p1_preparation(','INSERT INTO pr_commit('))]
        denied('原R2不能先单独提交',d,lambda:C.execute(d,old),'FOREIGN KEY')
        d,r,g=f();M.reserve(d,r,g)
        denied('直接写ready不能跳过回执',d,lambda:C.execute(d,[("UPDATE recovery_operation SET state='ready',revision='2'",())]),'recovery_preparations_incomplete')
        denied('封存后不能新增恢复目标',d,lambda:C.execute(d,[I('preparation_target',operation_id=r['operation_id'],controller_id='late',target_digest=H,target_body=B,state='pending')]),'recovery_registration_sealed')
        for name,table,changes in [('错水位','pr_commit',dict(dependency_head=0)),('错run修订','pr_commit',dict(run_revision='3')),
          ('错slot修订','pr_commit',dict(slot_revision='1')),('同数改声明','recovery_operation',dict(targets_body=P.canonical(['route.a','other']))),
          ('重复声明','recovery_operation',dict(targets_body=P.canonical(['route.a','route.a']))),('声明缺目标','recovery_operation',dict(targets_body=P.canonical(['route.a']))),
          ('登记错原目标','p1_preparation',dict(recovery_controller_id='other')),('登记错数据库','p1_preparation',dict(controller_database='wrong')),
          ('登记错请求正文','p1_preparation',dict(request_body=b'{}')),('原目标预先applied','preparation_target',dict(state='applied',receipt_id='fake'))]:
            d,r,g=f();denied(name,d,lambda d=d,t=table,v=changes:C.execute(d,C.mutate(s,t,v)))
        original=json.loads(next(args for sql,args in s if sql.startswith('INSERT INTO pr_commit('))[-2]);original['registrations'][0]['binding']['controller_scope']['authority_service_id']='other'
        d,r,g=f();denied('manifest同数换scope',d,lambda:C.execute(d,C.mutate(s,'pr_commit',dict(manifest_body=P.canonical(original)))),'recovery_registration_members')
        target=copy.deepcopy(r['targets'][0]);target['controller_scope']['database_instance_id']='other'
        denied('声明与登记scope必须相同',d,lambda:C.execute(d,C.mutate(s,'preparation_target',dict(target_body=P.canonical(target)))),'recovery_registration_members')
        for profile in (dict(max_preparations=1),dict(max_targets=1)):
            d,r,g=f(**profile);denied('R2容量失败'+next(iter(profile)),d,lambda d=d,r=r,g=g:M.reserve(d,r,g))
        for state in ('desynchronized','quarantined','closed','baseline_required'):
            d,r,g=f();d.execute('UPDATE ingress_source SET revision=?,state=?',('2',state));denied(state+'不允许R2',d,lambda d=d,r=r,g=g:M.reserve(d,r,g),'recovery_registration_seal')
        d,r,g=f();g['now']=200;denied('预览截止等号拒绝',d,lambda:M.reserve(d,r,g),'preview_time')
        d,r,g=f();g['current']=False;denied('当前提供者未合格',d,lambda:M.reserve(d,r,g),'unqualified_context')
        d,r,g=f();r['targets']=[];r['mode']='reconcile_commit';M.reserve(d,r,g);prepare(d,r);C.execute(d,M.start_steps(d,r['operation_id'],g))
        check('零设备恢复无虚构准备',d.execute('SELECT count(*) FROM p1_preparation').fetchone()[0],0)
        check('零设备reconcile仍不派发',d.execute('SELECT dispatch_eligible FROM run').fetchone()[0],0)
        d,r,g=f();M.reserve(d,r,g);attempt=M.attempt_step(d,'registration.a','attempt.a',B)
        denied('发送尝试请求摘要必须绑定',d,lambda:C.execute(d,C.mutate([attempt],'pr_attempt',dict(request_digest='wrong'))),'preparation_attempt_ineligible')
        denied('发送尝试原绑定必须相同',d,lambda:C.execute(d,C.mutate([attempt],'pr_attempt',dict(binding_body=b'{}'))),'preparation_attempt_ineligible')
        denied('尝试提交前故障',d,lambda:C.execute(d,[attempt],fail=0))
        C.execute(d,[attempt]);check('提交后重启分类只查询',d.execute("SELECT classification FROM pr_recovery_inventory WHERE registration_id='registration.a'").fetchone()[0],'query_only')
        denied('不允许第二次尝试',d,lambda:C.execute(d,[M.attempt_step(d,'registration.a','different.attempt',B)]),'UNIQUE')
        p1before=C.snapshot(d);P.protect(d,C.fault());check('P1固定已尝试和未尝试准备',d.execute('SELECT count(*) FROM p1_preparation_member').fetchone()[0],2)
        check('P1仍固定旧执行',sorted(x[0] for x in d.execute('SELECT execution_id FROM p1_execution_pin')),['execution0','recovery.execution'])
        check('P1不改写已记录尝试',C.snapshot(d)['pr_attempt']==p1before['pr_attempt'])
        denied('P1后尚未尝试也不能发送',d,lambda:C.execute(d,[M.attempt_step(d,'registration.b','attempt.b',B)]),'preparation_attempt_ineligible')
        late=granted(d,'registration.a');C.execute(d,M.receipt_steps(d,'registration.a',late,late['binding']['controller_scope']))
        check('迟到回执保留而不解除保护',sorted(set(x[0] for x in d.execute('SELECT classification FROM pr_recovery_inventory'))),['protected_query_only'])
        for omitted in range(3):
            d,r,g=f();M.reserve(d,r,g);C.execute(d,[M.attempt_step(d,'registration.a','attempt.a',B)])
            v=granted(d,'registration.a');adopt=M.receipt_steps(d,'registration.a',v,v['binding']['controller_scope'])
            denied('采用缺写'+str(omitted),d,lambda d=d,x=adopt,i=omitted:C.execute(d,x[:i]+x[i+1:]))
            denied('采用写后故障'+str(omitted),d,lambda d=d,x=adopt,i=omitted:C.execute(d,x,fail=i))
        d,r,g=f();M.reserve(d,r,g);v=granted(d,'registration.a')
        denied('无原尝试不得采用回执',d,lambda:C.execute(d,M.receipt_steps(d,'registration.a',v,v['binding']['controller_scope'])),'FOREIGN KEY')
        C.execute(d,[M.attempt_step(d,'registration.a','attempt.a',B)]);adopt=M.receipt_steps(d,'registration.a',v,v['binding']['controller_scope'])
        for name,table,changes in [('回执scope错配','external_evidence',dict(database_id='wrong')),('回执object错配','external_evidence',dict(object_id='wrong')),
          ('回执修订错配','external_evidence',dict(revision='1')),('回执登记错配','pr_receipt',dict(registration_id='registration.b'))]:
            denied(name,d,lambda t=table,ch=changes:C.execute(d,C.mutate(adopt,t,ch)))
        denied('认证域不符',d,lambda:M.receipt_steps(d,'registration.a',v,dict(authority_service_id='other',database_instance_id='controller.db')),'authenticated_controller')
        C.execute(d,adopt);saved=C.snapshot(d);check('重复采用空写集',M.receipt_steps(d,'registration.a',v,v['binding']['controller_scope']),[]);check('重复采用不改历史',C.snapshot(d)==saved)
        conflict=copy.deepcopy(v);conflict['applied_receipt_ref']['id']='changed';PO.seal(conflict)
        denied('同登记矛盾回执拒绝',d,lambda:M.receipt_steps(d,'registration.a',conflict,v['binding']['controller_scope']),'receipt_conflict')
        denied('回执未齐不能ready',d,lambda:M.ready_steps(d,r['operation_id']),'incomplete_preparations')
        d,r,g=f();M.reserve(d,r,g);C.execute(d,[M.attempt_step(d,'registration.a','attempt.a',B)]);v=granted(d,'registration.a')
        adopt=M.receipt_steps(d,'registration.a',v,v['binding']['controller_scope']);C.execute(d,adopt[:1])
        check('原件已存仍需采用',len(M.receipt_steps(d,'registration.a',v,v['binding']['controller_scope'])),2)
        M.apply(d,lambda:M.receipt_steps(d,'registration.a',v,v['binding']['controller_scope']))
        check('已有原件正常采用',d.execute("SELECT state FROM preparation_target WHERE controller_id='route.a'").fetchone()[0],'applied')
        for stage in ('before_receipts','after_ready'):
            d,r,g=f();M.reserve(d,r,g)
            if stage=='after_ready':prepare(d,r)
            else:
                for t in r['targets']:C.execute(d,[M.attempt_step(d,t['registration_id'],t['registration_id']+'.attempt',B)])
            P.protect(d,C.fault())
            if stage=='before_receipts':
                for t in r['targets']:
                    v=granted(d,t['registration_id']);C.execute(d,M.receipt_steps(d,t['registration_id'],v,t['controller_scope']))
                C.execute(d,M.ready_steps(d,r['operation_id']));execution_plan(d,r)
            denied(stage+'迟到回执不能启动',d,lambda d=d,r=r,g=g:M.start_steps(d,r['operation_id'],g),'new_latch')
        d,r,g=f();M.reserve(d,r,g);prepare(d,r);start=M.start_steps(d,r['operation_id'],g);P.protect(d,C.fault())
        denied('已经规划的R4仍须最后拒绝',d,lambda:C.execute(d,start))
        d,r,g=f();M.reserve(d,r,g);prepare(d,r);start=M.start_steps(d,r['operation_id'],g);d.execute("UPDATE ingress_source SET revision='2',state='desynchronized'")
        denied('只有来源失效也拒绝R4',d,lambda:C.execute(d,start),'recovery_source_unqualified')
        for table in ('pr_commit','pr_attempt','pr_receipt'):
            d,r,g=f();M.reserve(d,r,g);prepare(d,r);column=d.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for op in ('UPDATE','DELETE'):
                sql=f'UPDATE {table} SET {column}={column}' if op=='UPDATE' else 'DELETE FROM '+table
                denied(table+op+'不可变',d,lambda d=d,sql=sql:C.execute(d,[(sql,())]),'immutable')
        return checks
    finally:
        for d in connections:d.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    report=HERE/'registration-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(report));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=66,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,
          inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:report.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
