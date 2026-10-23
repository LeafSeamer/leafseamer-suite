"""布防、普通触发、动作记账与R5的完整同库离线验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import trigger_flow_model as F
import check_arm_storage as T
import check_arm_exit as E
G=F.G;A=F.A;P=F.P;R=F.R;I=F.I;C=T.C;B=T.B;H=T.H
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(E.INPUTS+G.SOURCES+[HERE/n for n in ('TRIGGER_FLOW.md','trigger_flow_model.py','check_trigger_flow.py','seamer-trigger-flow.sql')]))

def fixture(*,machine=True,steps=1,sql_factory=G.build):
    db,arm,ctx,targets=T.fixture(sql_factory=sql_factory)
    if machine:db.execute(*I('business_state',run_id='r0',state_id='idle',revision='1',last_commit_id=None))
    A.reserve(db,arm,ctx);T.receive_all(db,targets);A.apply(db,lambda:A.complete_steps(db,'arm.1',ctx))
    ctx.update(source_authenticated=True,age_verified=True,plan_verified=True,runtime_current=True,budget_valid=True,window_valid=True,parameters_verified=True,
        origin_commit_observed=True,dependencies_verified=True,receipt_verified=True,receipt_durable=True,terminal_evidence_verified=True,completion_verified=True,
        required_evidence=True,no_unresolved=True,tick='1000',clock=dict(domain='synthetic.domain'),runtime=dict(id='synthetic.runtime'),first_observation=dict(tick='900',domain='synthetic.domain'))
    actions=[dict(step_id='step.'+str(i),required=True,controller_scope=targets[i%len(targets)]['controller_scope'],
        request=dict(action_id='synthetic.set',value=i),parameters_ref=dict(id='parameters.'+str(i),digest=H)) for i in range(steps)]
    ctx['evaluations']={'r0':dict(qualified=True,matched=True,target_state_id='live' if machine else None,steps=actions)}
    req=dict(source_id='source',event_id='event.1',source_sequence='1',payload=dict(value=True))
    return db,ctx,req

def active(db):return R.one(db,'run','run_id','r0')['active_execution_id']
def submission(db,execution,ident):return F.step(db,execution,ident)['submission_id']
def prepare_step(db,execution,ident,ctx):
    A.apply(db,lambda:F.ready_steps(db,execution,ident,ctx));A.apply(db,lambda:F.submit_steps(db,execution,ident,ctx))
    sub=submission(db,execution,ident);F.attempt(db,sub,ctx);value=F.receipt(db,sub)
    A.apply(db,lambda:F.accept_steps(db,sub,value,ctx));return value
def success(db,execution,ident,ctx):
    value=prepare_step(db,execution,ident,ctx);ctx=dict(ctx,completion_command_ref=value['command_ref'])
    A.apply(db,lambda:F.terminal_steps(db,execution,ident,'succeeded',ctx))

def run():
    checks=[];dbs=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(stage=0,**kw):
        db,c,q=fixture(**kw);dbs.append(db)
        if stage:F.receive_event(db,q,c)
        ex=active(db)
        if stage>=2:A.apply(db,lambda:F.anchor_steps(db,ex,c))
        if stage>=3:
            for p in c['evaluations']['r0']['steps']:success(db,ex,p['step_id'],c)
        if stage>=4:F.finish(db,ex,c)
        return db,c,q,ex
    def denied(n,db,call,reason=None):
        before=C.snapshot(db)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError) as e:
            if reason:assert reason in str(e),(n,str(e),reason)
            check(n,C.snapshot(db)==before);return
        raise AssertionError(n)
    try:
        check('组合生成字节',(HERE/'seamer-trigger-flow.sql').read_bytes()==G.build())
        db,c,q,ex=f();check('91表完整布局',len(C.snapshot(db)),91)
        check('从真实arm完成起步',tuple(db.execute('SELECT lifecycle,revision,arm_generation FROM run').fetchone()),('armed','3','1'))
        writes=T.planned(db,lambda:F.ingress_steps(db,q,c));check('普通事件可靠受理',F.receive_event(db,q,c),'committed');ex=active(db)
        check('触发沿当前修订推进',tuple(db.execute('SELECT lifecycle,revision,arm_generation FROM run').fetchone()),('running','4','1'))
        check('槽随受理推进',db.execute('SELECT revision FROM activation_slot').fetchone()[0],'3')
        before=C.snapshot(db);check('重复事件查原',F.receive_event(db,q,c),'duplicate');check('重复事件全库零写',C.snapshot(db)==before)
        changed=copy.deepcopy(q);changed['payload']['value']=False;denied('重复事件异内容',db,lambda:F.receive_event(db,changed,c),'event_conflict')
        for i in range(len(writes)):
            d,cc,qq,ee=f();denied('摄取缺写'+str(i),d,lambda d=d,i=i:C.execute(d,writes[:i]+writes[i+1:]))
            d,cc,qq,ee=f();denied('摄取写后故障'+str(i),d,lambda d=d,cc=cc,qq=qq,i=i:F.receive_event(d,qq,cc,fail_after=i),'injected')
        busy=copy.deepcopy(q);busy.update(event_id='event.2',source_sequence='2');F.receive_event(db,busy,c)
        check('忙时事件只抑制',db.execute("SELECT result FROM ingress_decision ORDER BY rowid DESC LIMIT 1").fetchone()[0],'suppressed_busy')
        check('忙时不增加run修订',R.one(db,'run','run_id','r0')['revision'],'4')
        A.apply(db,lambda:F.anchor_steps(db,ex,c));value=prepare_step(db,ex,'step.0',c)
        check('受理未完成不提交业务状态',db.execute('SELECT state_id FROM business_state').fetchone()[0],'idle')
        denied('受理不等于动作成功',db,lambda:F.finish(db,ex,c),'steps_not_committable')
        denied('错command完成证据',db,lambda:A.apply(db,lambda:F.terminal_steps(db,ex,'step.0','succeeded',dict(c,completion_command_ref={'id':'wrong'}))),'completion_binding')
        c['completion_command_ref']=value['command_ref'];A.apply(db,lambda:F.terminal_steps(db,ex,'step.0','succeeded',c))
        check('动作完成仍未提交业务状态',db.execute('SELECT state_id FROM business_state').fetchone()[0],'idle')
        check('完成提交',F.finish(db,ex,c),'committed');check('状态与run共同推进',tuple(db.execute('SELECT state_id,revision FROM business_state').fetchone()),('live','2'))
        check('正常执行回armed',tuple(db.execute('SELECT lifecycle,revision,active_execution_id FROM run').fetchone()),('armed','5',None))
        before=C.snapshot(db);check('重复完成查原',F.finish(db,ex,c),'existing');check('重复完成零写',C.snapshot(db)==before)
        check('忙事件不补发',db.execute('SELECT count(*) FROM execution').fetchone()[0],1)
        second=copy.deepcopy(q);second.update(event_id='event.3',source_sequence='3');F.receive_event(db,second,c);ex2=active(db)
        check('新事件使用当前业务状态',tuple(db.execute('SELECT source_state_id,source_state_revision FROM execution WHERE execution_id=?',(ex2,)).fetchone()),('live','2'))
        check('新执行不复用旧执行',ex2!=ex)
        # 各动作阶段的主动异常，检查完整组合库回滚；不等同于物理崩溃验收。
        z,cz,qz,ez=f(1)
        for label,builder in [('anchor',lambda:F.anchor_steps(z,ez,cz)),('ready',lambda:F.ready_steps(z,ez,'step.0',cz)),('submit',lambda:F.submit_steps(z,ez,'step.0',cz))]:
            parts=T.planned(z,builder)
            for i in range(len(parts)):denied(label+'写后故障'+str(i),z,lambda builder=builder,i=i:A.apply(z,builder,fail_after=i),'injected')
            A.apply(z,builder)
        sub=submission(z,ez,'step.0')
        for i in range(4):denied('attempt写后故障'+str(i),z,lambda i=i:F.attempt(z,sub,cz,fail_after=i),'injected')
        F.attempt(z,sub,cz);value=F.receipt(z,sub)
        for label,builder in [('accept',lambda:F.accept_steps(z,sub,value,cz)),('terminal',lambda:F.terminal_steps(z,ez,'step.0','succeeded',dict(cz,completion_command_ref=value['command_ref'])))]:
            parts=T.planned(z,builder)
            for i in range(len(parts)):denied(label+'写后故障'+str(i),z,lambda builder=builder,i=i:A.apply(z,builder,fail_after=i),'injected')
            A.apply(z,builder)
        denied('查原仍须读取授权',z,lambda:F.attempt(z,sub,dict(cz,authorized=False)),'authority')
        d,cc,qq,ee=f(3);finish=T.planned(d,lambda:F.finish_steps(d,ee,cc))
        for i in range(len(finish)):
            z,cz,qz,ez=f(3);denied('R5缺写'+str(i),z,lambda z=z,i=i:C.execute(z,finish[:i]+finish[i+1:]))
            z,cz,qz,ez=f(3);denied('R5写后故障'+str(i),z,lambda z=z,ez=ez,cz=cz,i=i:F.finish(z,ez,cz,fail_after=i),'injected')
        for name,patch in [('R5错源状态',dict(source_state_id='wrong')),('R5错目标',dict(target_state_id='wrong')),('R5跳修订',dict(run_revision_after='9')),('R5错槽',dict(slot_revision='9'))]:
            z,cz,qz,ez=f(3);denied(name,z,lambda z=z,patch=patch:C.execute(z,C.mutate(finish,'transition_commit',patch)),'prestate')
        z,cz,qz,ez=f(3);denied('R5最终槽漂移',z,lambda:C.execute(z,finish[:-1]+[("UPDATE activation_slot SET revision='4'",())]+finish[-1:]),'final')
        z,cz,qz,ez=f(3);denied('R5最终锁存插入',z,lambda:C.execute(z,finish[:-1]+[I('pause_latch',latch_id='late',run_id='r0',reason='operator_pause',created_revision='5',body=B)]+finish[-1:]),'final')
        z,cz,qz,ez=f(3,machine=False);check('规则无伪状态行',z.execute('SELECT count(*) FROM business_state').fetchone()[0],0);check('规则完成',F.finish(z,ez,cz),'committed')
        z,cz,qz,ez=f();cz['evaluations']['r0']['matched']=False;F.receive_event(z,qz,cz);check('no_match不执行',z.execute('SELECT count(*) FROM execution').fetchone()[0],0)
        check('no_match不变run修订',R.one(z,'run','run_id','r0')['revision'],'3')
        z,cz,qz,ez=f();cz['evaluations']={};denied('不完整监听集合',z,lambda:F.receive_event(z,qz,cz),'complete_match_set')
        z,cz,qz,ez=f();P.protect(z,C.fault());denied('来源保护后不接受新事件',z,lambda:F.receive_event(z,qz,cz),'frontier')
        z,cz,qz,ez=f(2);T.Q.Q.withdraw(z,'registration.a',T.Q.withdrawal(z),T.Q.PROVIDER)
        denied('准备撤回后不能ready',z,lambda:A.apply(z,lambda:F.ready_steps(z,ez,'step.0',cz)))
        z,cz,qz,ez=f(2);ready=T.planned(z,lambda:F.ready_steps(z,ez,'step.0',cz));A.apply(z,lambda:F.ready_steps(z,ez,'step.0',cz))
        bad=T.planned(z,lambda:F.submit_steps(z,ez,'step.0',cz));denied('未准备Controller不可提交',z,lambda:C.execute(z,C.mutate(bad,'command_submission',dict(target_authority='other'))),'target_unprepared')
        A.apply(z,lambda:F.submit_steps(z,ez,'step.0',cz));sub=submission(z,ez,'step.0');check('首次尝试只返回一次调用标记',F.attempt(z,sub,cz),'live_path_call_once')
        before=C.snapshot(z);check('重启查原不重投',F.attempt(z,sub,cz),'query_original_identity_only');check('不重投零写',C.snapshot(z)==before)
        A.apply(z,lambda:F.terminal_steps(z,ez,'step.0','unknown',cz));v=F.receipt(z,sub);A.apply(z,lambda:F.accept_steps(z,sub,v,cz))
        check('迟到受理不覆盖unknown',F.step(z,ez,'step.0')['outcome'],'unknown');denied('unknown不能提交状态',z,lambda:F.finish(z,ez,cz))
        check('unknown锁存暂停',tuple(z.execute('SELECT lifecycle,dispatch_eligible,active_execution_id FROM run').fetchone()),('paused',0,ez))
        z,cz,qz,ez=f(2,steps=2);success(z,ez,'step.0',cz);prepare_step(z,ez,'step.1',cz);A.apply(z,lambda:F.terminal_steps(z,ez,'step.1','failed',cz))
        denied('必需动作失败不得提交',z,lambda:F.finish(z,ez,cz));check('失败保留旧状态',z.execute('SELECT state_id FROM business_state').fetchone()[0],'idle')
        check('必需失败保存执行终态',z.execute('SELECT state FROM execution WHERE execution_id=?',(ez,)).fetchone()[0],'failed')
        z,cz,qz,ez=f(2,steps=2);prepare_step(z,ez,'step.0',cz);later=T.planned(z,lambda:F.ready_steps(z,ez,'step.1',cz))
        failed=T.planned(z,lambda:F.terminal_steps(z,ez,'step.0','failed',cz))
        for i in range(len(failed)):denied('失败投影写后故障'+str(i),z,lambda i=i:A.apply(z,lambda:F.terminal_steps(z,ez,'step.0','failed',cz),fail_after=i),'injected')
        A.apply(z,lambda:F.terminal_steps(z,ez,'step.0','failed',cz))
        denied('必需失败后writer不再准备下一动作',z,lambda:A.apply(z,lambda:F.ready_steps(z,ez,'step.1',cz)))
        denied('必需失败后旧ready写集也被SQL拒绝',z,lambda:C.execute(z,later),'flow_execution_inactive')
        z,cz,qz,ez=f(steps=2);cz['evaluations']['r0']['steps'][1]['required']=False;F.receive_event(z,qz,cz);ez=active(z);A.apply(z,lambda:F.anchor_steps(z,ez,cz))
        success(z,ez,'step.0',cz);prepare_step(z,ez,'step.1',cz);A.apply(z,lambda:F.terminal_steps(z,ez,'step.1','failed',cz))
        check('可选确定失败允许提交',F.finish(z,ez,cz),'committed')
        z,cz,qz,ez=f(4,steps=2);check('双动作成功才R5',z.execute('SELECT state_id FROM business_state').fetchone()[0],'live')
        z,cz,qz,ez=f(machine=False);recovery=T.reconcile(z);rr=R.one(z,'run','run_id','r0');ss=R.one(z,'activation_slot','definition_id','d0')
        recovery=C.mutate(recovery,'transition_commit',dict(run_revision_before=rr['revision'],run_revision_after=P.inc(rr['revision']),slot_revision=ss['revision']))
        denied('恢复不得借普通完成省略释放',z,lambda:F.finish(z,rr['active_execution_id'],cz),'use_recovery_protocol')
        for prefix in ('UPDATE recovery_operation','UPDATE recovery_lock'):
            missing=[w for w in recovery if not w[0].startswith(prefix)]
            denied('恢复R5缺投影'+prefix,z,lambda missing=missing:C.execute(z,missing+[I('flow_commit_seal',commit_id='commit',audit_body=B,notification_body=B)]),'flow_commit_final')
        C.execute(z,recovery+[I('flow_commit_seal',commit_id='commit',audit_body=B,notification_body=B)])
        check('新R5布局兼容显式恢复',tuple(z.execute('SELECT lifecycle,dispatch_eligible FROM run').fetchone()),('armed',1))
        check('恢复锁仍按原协议释放',z.execute('SELECT release_id FROM recovery_lock').fetchone()[0],'release')
        # 旧90表允许执行成功而遗漏run和业务状态投影；反例只在隔离内存库保留。
        z,cz,qz,ez=f(3,sql_factory=G.A.build);legacy=T.planned(z,lambda:F.finish_steps(z,ez,cz));legacy=[w for w in legacy if not w[0].startswith(('UPDATE run ','UPDATE business_state ','INSERT INTO flow_commit_seal('))]
        fixed=[]
        for sql,args in legacy:
            if sql.startswith('INSERT INTO transition_commit('):
                data=dict(zip(sql.split('(',1)[1].split(')',1)[0].split(','),args))
                for name in ('run_revision_before','run_revision_after','slot_revision'):data.pop(name)
                fixed.append(I('transition_commit',**data))
            else:fixed.append((sql,args))
        C.execute(z,fixed);check('旧布局R5半投影反例',tuple(z.execute('SELECT r.lifecycle,b.state_id,e.state FROM run r JOIN business_state b USING(run_id) JOIN execution e ON e.execution_id=r.active_execution_id').fetchone()),('running','idle','succeeded'))
        check('新组合外键完整',list(db.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'trigger-flow-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=91,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
