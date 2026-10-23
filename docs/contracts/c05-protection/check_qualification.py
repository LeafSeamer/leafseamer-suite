"""准备当前资格与独立保护计划的内存验收，不代表真实时间、身份或网络证明。"""
import argparse,copy,hashlib,json,sqlite3,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path[:0]=[str(HERE.parent/'c08-controller'),str(HERE.parent/'c04-storage')]
import check_registration as F
import check_storage as C
import build_qualification as G
import qualification_model as Q
import registration_model as R
import storage_model as P
import preparation_delivery_model as O
import protection_delivery_model as SP
I=P.row;B=F.B;H=F.H
PROVIDER=dict(authority_service_id='supervisor',database_instance_id='provider.db')
INPUTS=list(dict.fromkeys(F.INPUTS+G.SOURCES+[HERE/n for n in ('QUALIFICATION.md','qualification_model.py','check_qualification.py','seamer-qualification.sql','preparation-qualification.schema.json')]))


def withdrawal(db,ident='registration.a',reason='authorization_revoked'):
    binding=json.loads(db.execute('SELECT binding_body FROM p1_preparation WHERE registration_id=?',(ident,)).fetchone()[0])
    return Q.seal_withdrawal(dict(contract_version=G.VERSION,event_id='withdrawal.1',binding=binding,reason=reason,
      proof_ref=dict(scope=PROVIDER,id='proof.1',revision='1',digest=H)))
def closing(db,ident='registration.a'):
    value=F.granted(db,ident)
    value.update(preparation_revision='3',previous_revision='2',state='closing',protection_state='pending',
      close_ref=dict(id='close.1',operation_id='close.operation',operation_digest=H,bytes_digest=H))
    return O.seal(value)


def prepare(db,r,g,start=False):
    for t in r['targets']:
        ident=t['registration_id'];R.apply(db,lambda:[R.attempt_step(db,ident,ident+'.attempt',B)])
        Q.receive(db,ident,F.granted(db,ident),t['controller_scope'])
    R.apply(db,lambda:R.ready_steps(db,r['operation_id']));F.execution_plan(db,r)
    if start:R.apply(db,lambda:R.start_steps(db,r['operation_id'],g))


def planned_fault(db,value,kind='withdrawal'):
    db.execute('BEGIN IMMEDIATE')
    try:return Q.invalidate_steps(db,'registration.a',kind,value)
    finally:db.rollback()


def submission_history(db,r):
    """由旧执行层约束建立已尝试且响应未知的第三Controller提交；没有实际发送。"""
    ex=r['execution_id'];run=r['run_id'];start=db.execute('SELECT start_id FROM execution WHERE execution_id=?',(ex,)).fetchone()[0]
    items=[]
    for phase,ident in [('ANCHOR','anchor'),('READY','ready'),('SUBMISSION','submission'),('ATTEMPT','attempt')]:
        tx='history.'+ident
        items += [I('transaction_record',tx_id=tx,run_id=run,phase=phase,business_id=ident,audit_body=B,event_id=tx+'.event'),
          I('event_outbox',event_id=tx+'.event',tx_id=tx,payload_digest=H,payload_body=B)]
        if phase=='ANCHOR':items.append(I('execution_anchor',anchor_id=ident,execution_id=ex,run_id=run,origin_kind='recovery',start_id=start,trigger_decision_ref_body=None,clock_body=B,tick_ns='1000',anchor_digest=H,anchor_body=B,tx_id=tx))
        elif phase=='READY':items += [I('step_ready',ready_id=ident,execution_id=ex,step_id='step',run_id=run,plan_digest='step.plan',anchor_id='anchor',clock_body=B,tick_ns='1000',dependencies_digest=H,dependencies_body=B,ready_digest=H,ready_body=B,tx_id=tx),
          ("UPDATE step_state SET revision='2',state='ready',ready_id='ready' WHERE execution_id=?",(ex,))]
        elif phase=='SUBMISSION':items += [I('command_submission',submission_id=ident,execution_id=ex,step_id='step',run_id=run,target_authority='controller-extra',target_database='extra.db',issuer_id='issuer',principal_id='actor',request_epoch='epoch',operation_id='createCommand',idempotency_key='command.key',request_digest=H,request_body=B,parameters_ref_body=B,state='planned',tx_id=tx),
          ("UPDATE step_state SET revision='3',state='submission_pending',submission_id='submission' WHERE execution_id=?",(ex,))]
        else:items += [I('submission_attempt',attempt_id=ident,submission_id='submission',run_id=run,runtime_binding_ref_body=B,clock_body=B,tick_ns='1000',attempt_body=B,tx_id=tx),
          ("UPDATE command_submission SET state='attempt_recorded',attempt_id='attempt' WHERE submission_id='submission'",()),
          ("UPDATE command_submission SET state='indeterminate' WHERE submission_id='submission'",())]
    C.execute(db,items)


def next_generation(db,r,g):
    run=r['run_id'];rev=db.execute('SELECT revision FROM run WHERE run_id=?',(run,)).fetchone()[0]
    db.execute('UPDATE run SET revision=?,lifecycle=?,dispatch_eligible=0 WHERE run_id=?',(P.inc(rev),'paused',run))
    db.execute("UPDATE execution SET state='unknown' WHERE execution_id=?",(r['execution_id'],))
    db.execute("UPDATE recovery_operation SET state='paused',revision='4' WHERE operation_id=?",(r['operation_id'],))
    db.execute(*I('external_evidence',evidence_id='release.1',authority_id='supervisor',database_id='provider.db',kind='release',object_id='release.1',revision='1',digest=H,body=B))
    db.execute('UPDATE recovery_lock SET release_id=? WHERE operation_id=?',('release.1',r['operation_id']))
    rev=db.execute('SELECT revision FROM run WHERE run_id=?',(run,)).fetchone()[0]
    db.execute(*I('pause_latch',latch_id='next.latch',run_id=run,reason='pause',created_revision=rev,body=B,cleared_start_id=None))
    slot=db.execute('SELECT revision FROM activation_slot').fetchone()[0]
    db.execute(*I('recovery_preview',preview_id='next.preview',run_id=run,run_revision=rev,slot_revision=slot,prior_execution_id=r['execution_id'],preview_digest=H,plan_digest='next.plan',preview_body=B,clock_body=B,issued_tick='100',expires_tick='200',consumed_operation_id=None))
    request=copy.deepcopy(r);request.update(operation_id='next.recovery',preview_id='next.preview',execution_id='next.execution',idempotency_key='next.key',plan_digest='next.plan',resolved_latches=['next.latch'])
    for t in request['targets']:
        t['registration_id']='next.'+t['registration_id'];t['preparation_id']='next.'+t['preparation_id'];t['request_body']['preparation_id']=t['preparation_id']
    R.reserve(db,request,g);return request


def run():
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,observed=actual,expected=expected))
    def f(stage=0,**limits):
        d,r,g=F.fixture(layout=G.build(),**limits);connections.append(d);R.reserve(d,r,g)
        if stage:prepare(d,r,g,start=stage==2)
        return d,r,g
    def denied(name,db,action,reason=None):
        before=C.snapshot(db)
        try:action()
        except (sqlite3.IntegrityError,ValueError,RuntimeError,O.jsonschema.ValidationError) as e:
            if reason:assert reason in str(e),(name,str(e),reason)
        else:raise AssertionError(name+':未拒绝')
        check(name+'全库不变',C.snapshot(db)==before)
    try:
        check('SQL生成一致',(HERE/'seamer-qualification.sql').read_bytes()==G.build());check('Schema生成一致',(HERE/'preparation-qualification.schema.json').read_bytes()==G.schema_bytes())
        d,r,g=f();check('72表',len(C.snapshot(d)),72)
        check('初始资格不伪造applied',sorted(x[0] for x in d.execute('SELECT qualification FROM pq_current')),['pending','pending'])
        denied('旧采用入口不能绕过当前观察',d,lambda:C.execute(d,R.receipt_steps(d,'registration.a',F.granted(d,'registration.a'),r['targets'][0]['controller_scope'])),'preparation_current_unqualified')
        prepare(d,r,g);planned=R.start_steps(d,r['operation_id'],g);v=withdrawal(d);s=planned_fault(d,v);before=C.snapshot(d)
        check('撤回原子封存',Q.withdraw(d,'registration.a',v,PROVIDER),'withdrawn')
        check('来源未被伪造故障',C.snapshot(d)['ingress_source']==before['ingress_source'])
        check('原回执不改写',C.snapshot(d)['pr_receipt']==before['pr_receipt'])
        check('同run暂停关闭派发',tuple(d.execute('SELECT lifecycle,dispatch_eligible FROM run').fetchone()),('paused',0))
        check('拒绝下界',tuple(d.execute('SELECT generation FROM p1_deny').fetchone()),('00000000000000000002',))
        check('两Controller完整固定',sorted(x[0] for x in d.execute('SELECT controller_authority FROM pq_target')),['controller-a','controller-b'])
        check('独立计划注册类型',d.execute('SELECT source_plan IS NULL AND preparation_plan IS NOT NULL FROM protection_plan_registry').fetchone()[0],1)
        check('旧unknown仍在',d.execute("SELECT state FROM execution WHERE execution_id='execution0'").fetchone()[0],'unknown')
        denied('已规划R4不能越过撤回',d,lambda:C.execute(d,planned))
        saved=C.snapshot(d);check('重复撤回查原',Q.withdraw(d,'registration.a',v,PROVIDER),'retained');check('重复撤回零写',C.snapshot(d)==saved)
        good=F.granted(d,'registration.a');check('迟到相同成功查原',Q.receive(d,'registration.a',good,good['binding']['controller_scope']),'duplicate')
        check('成功不能清除失效',d.execute("SELECT qualification FROM pq_current WHERE registration_id='registration.a'").fetchone()[0],'invalidated')
        for i in range(len(s)):
            x,rr,gg=f(1);denied('撤回缺写'+str(i),x,lambda x=x,i=i:C.execute(x,s[:i]+s[i+1:]))
            x,rr,gg=f(1);denied('撤回写后异常'+str(i),x,lambda x=x,i=i:Q.withdraw(x,'registration.a',withdrawal(x),PROVIDER,fail_after=i))
        for name,table,ch in [('前态错修订','pq_plan',dict(revision_before='1')),('后态跳修订','pq_plan',dict(revision_after='9')),('登记水位陈旧','pq_plan',dict(preparation_head=1)),
          ('Controller同数替换','pq_target',dict(controller_database='other')),('接收器同数替换','sp_target',dict(binding_body=b'{}')),('锁存原因不符','pause_latch',dict(reason='other'))]:
            x,rr,gg=f(1);denied(name,x,lambda x=x,t=table,ch=ch:C.execute(x,C.mutate(s,t,ch)))
        members=json.loads(next(args for sql,args in s if sql.startswith('INSERT INTO pq_plan('))[-3]);members['preparations'][0]='invented'
        x,rr,gg=f(1);denied('同数换准备成员',x,lambda:C.execute(x,C.mutate(s,'pq_plan',dict(members_body=P.canonical(members)))),'qualification_complete_set')
        x,rr,gg=f(1,max_payload_bytes=1);denied('保护写集容量失败',x,lambda:Q.withdraw(x,'registration.a',withdrawal(x),PROVIDER),'capacity')
        x,rr,gg=f(1);bad=withdrawal(x);bad['binding']['controller_scope']['database_instance_id']='other';Q.seal_withdrawal(bad)
        denied('撤回绑定不符',x,lambda:Q.withdraw(x,'registration.a',bad,PROVIDER),'qualification_binding')
        denied('证明提供者不符',x,lambda:Q.withdraw(x,'registration.a',withdrawal(x),dict(authority_service_id='other',database_instance_id='provider.db')),'qualified_provider')
        bad=withdrawal(x);bad['withdrawal_digest']=H;denied('撤回摘要错误',x,lambda:Q.withdraw(x,'registration.a',bad,PROVIDER),'withdrawal_digest')
        for reason in ('grant_expired','controller_instance_changed','stream_unconfirmed'):
            x,rr,gg=f(1);Q.withdraw(x,'registration.a',withdrawal(x,reason=reason),PROVIDER);check(reason+'关闭旧代次',x.execute('SELECT count(*) FROM pq_commit').fetchone()[0],1)
        x,rr,gg=f(1);conflict=F.granted(x,'registration.a');conflict['applied_receipt_ref']['id']='different';O.seal(conflict)
        check('同键矛盾持久隔离',Q.receive(x,'registration.a',conflict,conflict['binding']['controller_scope']),'conflict')
        check('首冲突一槽',x.execute('SELECT count(*) FROM pq_fault').fetchone()[0],1)
        saved=C.snapshot(x);conflict['applied_receipt_ref']['id']='third';O.seal(conflict)
        check('更多冲突不增长',Q.receive(x,'registration.a',conflict,conflict['binding']['controller_scope']),'conflict_retained');check('更多冲突零写',C.snapshot(x)==saved)
        for stage in (0,1,2):
            x,rr,gg=f(stage);close=closing(x)
            check('关闭阶段'+str(stage),Q.receive(x,'registration.a',close,close['binding']['controller_scope']),'stored')
            check('关闭丢失资格'+str(stage),x.execute("SELECT qualification FROM pq_current WHERE registration_id='registration.a'").fetchone()[0],'invalidated')
            if stage==0:
                old=F.granted(x,'registration.a');check('关闭先到允许补旧观察',Q.receive(x,'registration.a',old,old['binding']['controller_scope']),'stored')
                check('不伪造历史采用',x.execute('SELECT count(*) FROM pr_receipt').fetchone()[0],0)
        for kind in ('unavailable','conflict'):
            x,rr,gg=f(1);value=closing(x) if kind=='unavailable' else F.granted(x,'registration.a')
            if kind=='conflict':value['applied_receipt_ref']['id']='conflicting.receipt';O.seal(value)
            count=len(planned_fault(x,value,kind))+(kind=='unavailable')
            for i in range(count):
                z,zr,zg=f(1)
                denied(kind+'接收写后异常'+str(i),z,lambda z=z,v=value,i=i:Q.receive(z,'registration.a',v,v['binding']['controller_scope'],fail_after=i),'injected')
        x,rr,gg=f();bad=F.granted(x,'registration.a');bad.update(state='indeterminate',applied_receipt_ref=None);O.seal(bad)
        Q.receive(x,'registration.a',bad,bad['binding']['controller_scope']);check('未获grant失败也保护全集',x.execute('SELECT count(*) FROM pq_target').fetchone()[0],2)
        x,rr,gg=f(2);submission_history(x,rr);before=C.snapshot(x);Q.withdraw(x,'registration.a',withdrawal(x),PROVIDER)
        check('未知提交增加第三Controller',x.execute('SELECT count(*) FROM pq_target').fetchone()[0],3)
        check('已有提交及尝试不改写',all(C.snapshot(x)[t]==before[t] for t in ('command_submission','submission_attempt','execution')))
        for table in ('step_ready','command_submission','submission_attempt'):
            row=dict(x.execute('SELECT * FROM '+table).fetchone());denied('后续'+table+'拒绝',x,lambda t=table,row=row:C.execute(x,[I(t,**row)]))
        denied('R5最后写入也拒绝旧代次',x,lambda:C.execute(x,[I('transition_commit',commit_id='blocked',run_id='r0',execution_id=rr['execution_id'])]),'preparation_current_unqualified')
        x,rr,gg=f(2);new=next_generation(x,rr,gg);before=C.snapshot(x);Q.withdraw(x,'registration.a',withdrawal(x),PROVIDER)
        check('迟到旧代次不改变新run',C.snapshot(x)['run']==before['run'])
        check('旧代次不添加新锁存',C.snapshot(x)['pause_latch']==before['pause_latch'])
        check('只固定旧准备',json.loads(x.execute('SELECT members_body FROM pq_plan').fetchone()[0])['preparations'],['registration.a','registration.b'])
        prepare(x,new,gg,start=True);check('新代次仍能显式启动',x.execute('SELECT arm_generation FROM run').fetchone()[0],'3')
        x,rr,gg=f(1);Q.withdraw(x,'registration.a',withdrawal(x),PROVIDER);P.protect(x,C.fault())
        check('来源与准备两计划共同存在',x.execute('SELECT count(*) FROM protection_plan_registry').fetchone()[0],2)
        check('原来源路径仍封存',x.execute('SELECT count(*) FROM p1_commit').fetchone()[0],1)
        plan,target,binding=x.execute('SELECT plan_id,target_id,binding_body FROM pq_target ORDER BY target_id LIMIT 1').fetchone();binding=json.loads(binding)
        SP.receive(x,plan,target,C.observation(binding),binding['controller_scope'])
        check('共享接收器收到保护回执',x.execute('SELECT count(*) FROM pq_pending_protection').fetchone()[0],1)
        check('保护applied不恢复准备资格',x.execute("SELECT qualification FROM pq_current WHERE registration_id='registration.a'").fetchone()[0],'invalidated')
        SP.receive(x,plan,target,C.observation(binding,2),binding['controller_scope']);check('保护证明撤回重回待处理',x.execute('SELECT count(*) FROM pq_pending_protection').fetchone()[0],2)
        check('组合外键完整',list(x.execute('PRAGMA foreign_key_check')),[])
        for table in ('protection_plan_registry','pq_observation','pq_fault','pq_plan','pq_target','pq_commit'):
            column=x.execute('PRAGMA table_info('+table+')').fetchone()[1]
            denied(table+'不可更新',x,lambda t=table,c=column:C.execute(x,[(f'UPDATE {t} SET {c}={c}',())]),'immutable')
        return checks
    finally:
        for d in connections:d.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'qualification-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=72,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,
          inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
