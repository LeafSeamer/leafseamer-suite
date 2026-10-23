"""恢复后普通触发的三库合成验收；真实发送/完成提供者另行验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import continuation_trigger_model as M
import check_continuation_storage as T
import check_prepare_deny_storage as PD
G=M.G;C=M.C;P=M.P;R=M.R;I=M.I;F=M.F;AT=T.AT;W=T.W;SC=T.C
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+PD.INPUTS+G.SOURCES+[Path(T.__file__),HERE/'continuation_trigger_model.py',HERE/'check_continuation_trigger.py',HERE/'CONTINUATION_TRIGGER.md']))

def fixture():
    d,q,s,cds,ctx=T.fixture(seamer_factory=G.seamer_sql,controller_factory=G.controller_sql)
    steps=copy.deepcopy(ctx['evaluations']['r0']['steps'])
    for step in steps:step['request']['device_id']='dev.1'
    plan=dict(ref=T.ref(q['origin_scope'],'continued.plan',M.M.digest(steps)),steps=steps)
    q=M.M.seal(dict(q,continuation_plan_ref=plan['ref']),'request_digest')
    s.update(binding={k:q[k] for k in s['binding']},approval_subject=M.M.approval_subject(q))
    for cd,cc in cds.values():
        cc.update(plan_ref=plan['ref'],approval_subject=M.M.approval_subject(q),parameters_verified=True)
        base=PD.F.adapt([PD.F.F.A.namespace()]);SC.execute(cd,[I(t,**v) for t,v in base])
    a,rs=T.issued(d,q,s,cds);C.adopt(d,q,a,s,cds);C.finish(d,q,s,cds)
    ctx['evaluations']['r0']['steps']=steps;ctx['continuation_plans']={'r0':plan}
    return d,q,s,cds,ctx

def active(d):return R.one(d,'run','run_id','r0')['active_execution_id']
def start(d,ctx,n=12):
    M.receive_event(d,W.event(n),ctx);ex=active(d);C.tx(d,lambda:F.anchor_steps(d,ex,ctx));return ex
def submitted(d,ex,step,ctx):
    C.tx(d,lambda:F.ready_steps(d,ex,step,ctx));C.tx(d,lambda:F.submit_steps(d,ex,step,ctx))
    sub=F.step(d,ex,step)['submission_id'];F.attempt(d,sub,ctx);return sub

def admission_steps(d,cd,sub,cc):
    # 复用现有Controller完整受理/公开状态夹具；只在INSERT之前绑定本次真实引用。
    value=F.receipt(d,sub);command=value['command_ref']['id'];s=R.one(d,'command_submission','submission_id',sub)
    key=F.digest(sub).split(':',1)[1]
    rows=PD.F.adapt(PD.F.V.public(PD.F.C.initial(key=key),1,key=key));writes=[];link=M.admission_link(d,cd,sub,command,cc)
    body=dict(execution_id=s['execution_id'],step_id=s['step_id'],submission_id=sub)
    for table,v in rows:
        v={k:(command if val=='command.one' else 'dev.1' if val=='device' else val) for k,val in v.items()}
        if table=='ca_request_key':v.update(request_digest=s['request_digest'],content_body=s['request_body'])
        if table=='ce_command':v.update(binding_body=C.raw(body))
        if table=='ca_commit':writes.append(link)
        writes.append(I(table,**v))
    return writes

def success(d,cds,ctx,ex,step):
    sub=submitted(d,ex,step,ctx);s=R.one(d,'command_submission','submission_id',sub);cd,cc=cds[(s['target_authority'],s['target_database'])]
    C.tx(cd,lambda:admission_steps(d,cd,sub,cc));value=F.receipt(d,sub)
    C.tx(d,lambda:F.accept_steps(d,sub,value,ctx))
    C.tx(d,lambda:F.terminal_steps(d,ex,step,'succeeded',dict(ctx,completion_command_ref=value['command_ref'])))
    return sub

def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def fresh():
        values=fixture();dbs.append(values[0]);dbs.extend(x[0] for x in values[3].values());return values
    def denied(n,d,call,reason=None):
        before=SC.snapshot(d)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError) as err:
            if reason:assert reason in str(err),(n,str(err))
            check(n,SC.snapshot(d)==before);return
        raise AssertionError(n+':应拒绝')
    def atomic(n,d,builder):
        writes=AT.planned(d,builder)
        for i in range(len(writes)):
            denied(n+'缺写'+str(i),d,lambda i=i:SC.execute(d,writes[:i]+writes[i+1:]))
            denied(n+'异常'+str(i),d,lambda i=i:C.tx(d,builder,fail_after=i),'injected')
        return writes
    try:
        d,q,s,cds,ctx=fresh();check('119表',len(SC.snapshot(d))==119);check('236表',all(len(SC.snapshot(cd))==236 for cd,_ in cds.values()))
        writes=atomic('新触发完整计划',d,lambda:M.ingress_steps(d,W.event(12),ctx))
        for patch in (dict(adoption_digest='wrong'),dict(registration_id='new.registration.b'),dict(device_id='other'),dict(grant_ref_body=C.raw(q['targets'][0]['recovery_grant_ref']))):
            denied('计划关联错配'+str(patch),d,lambda patch=patch:SC.execute(d,SC.mutate(writes,'cn_step',patch)))
        denied('原入口不得跳过新grant关联',d,lambda:F.receive_event(d,W.event(12),ctx),'resync_plan_target_unprepared')
        bad=copy.deepcopy(ctx);bad['evaluations']['r0']['steps'][0]['request']['value']=99
        denied('不得偏离已批准参数',d,lambda:M.receive_event(d,W.event(12),bad),'approved_program')
        ex=start(d,ctx);check('每动作有独立关联',d.execute('SELECT count(*) FROM cn_step').fetchone()[0]==2)
        sub=submitted(d,ex,'step.0',ctx);cd,cc=next(iter(cds.values()))
        accepted_writes=atomic('Controller受理关联',cd,lambda:admission_steps(d,cd,sub,cc))
        for table,patch in [('cn_command',dict(adoption_digest='wrong')),('cn_command',dict(execution_id=q['recovery_execution_id'])),
            ('cn_command',dict(grant_ref_body=C.raw(q['targets'][0]['recovery_grant_ref']))),('ce_command',dict(device_id='dev.2'))]:
            denied('Controller错关联'+table+str(patch),cd,lambda table=table,patch=patch:SC.execute(cd,SC.mutate(accepted_writes,table,patch)))
        C.tx(cd,lambda:admission_steps(d,cd,sub,cc))
        value=F.receipt(d,sub);C.tx(d,lambda:F.accept_steps(d,sub,value,ctx));C.tx(d,lambda:F.terminal_steps(d,ex,'step.0','succeeded',dict(ctx,completion_command_ref=value['command_ref'])))
        success(d,cds,ctx,ex,'step.1');F.finish(d,ex,ctx)
        check('来源恢复到新触发完成',tuple(d.execute('SELECT lifecycle,active_execution_id FROM run').fetchone())==('armed',None))
        check('恢复及普通执行均成功',d.execute("SELECT count(*) FROM execution WHERE state='succeeded'").fetchone()[0]==2)
        check('两个Controller保存新grant命令',all(cd.execute('SELECT count(*) FROM cn_command').fetchone()[0]==1 for cd,_ in cds.values()))
        check('旧恢复准备仍绑定原execution',all(row[0]==q['recovery_execution_id'] for row in d.execute("SELECT execution_id FROM p1_preparation WHERE generation='2'")))
        check('原grant与新grant分开',all(cd.execute('SELECT i.grant_id!=g.grant_id FROM cr_issue i JOIN cp_grant g USING(prep_key)').fetchone()[0]==1 for cd,_ in cds.values()))
        before=SC.snapshot(d);check('已完成事件查原零写',M.receive_event(d,W.event(12),ctx)=='existing' and SC.snapshot(d)==before)
        ex2=start(d,ctx,13)
        for step in ('step.0','step.1'):success(d,cds,ctx,ex2,step)
        F.finish(d,ex2,ctx)
        check('第二次普通触发继续成功且不重签',d.execute("SELECT count(*) FROM execution WHERE state='succeeded'").fetchone()[0]==3
            and all(cd.execute('SELECT count(*) FROM cr_issue').fetchone()[0]==1 and cd.execute('SELECT count(*) FROM cn_command').fetchone()[0]==2 for cd,_ in cds.values()))
        check('所有新命令保持原run保护归属',all(cd.execute("SELECT count(*) FROM ce_run_command WHERE run_id='r0' AND generation=?",(T.U.u(2),)).fetchone()[0]==2 for cd,_ in cds.values()))
        SC.execute(cd,[I('cr_revocation',transfer_id=q['transfer_id'],proof_body=AT.B,audit_body=AT.B,outbox_body=AT.B)])
        check('撤回后原受理命令失去当前资格',cd.execute('SELECT count(*) FROM cn_live_command').fetchone()[0]==0)
        command=cd.execute('SELECT command_id FROM cn_command LIMIT 1').fetchone()[0]
        denied('受理后撤回不能新建attempt',cd,lambda:SC.execute(cd,[I('ce_attempt',attempt_id='late',command_id=command,authorization_body=AT.B,attempt_body=AT.B)]),'continuation_command_revoked')
        # 新命令尚未受理时远端撤回，Seamer旧缓存不能授予Controller受理。
        d,q,s,cds,ctx=fresh();ex=start(d,ctx);sub=submitted(d,ex,'step.0',ctx);cd,cc=next(iter(cds.values()))
        SC.execute(cd,[I('cr_revocation',transfer_id=q['transfer_id'],proof_body=AT.B,audit_body=AT.B,outbox_body=AT.B)])
        denied('Controller撤回后拒绝新受理',cd,lambda:C.tx(cd,lambda:admission_steps(d,cd,sub,cc)),'preparation_denied')
        registration=d.execute("SELECT registration_id FROM rc_target ORDER BY registration_id").fetchone()[0]
        plans=AT.planned(d,lambda:M.withdrawal_steps(d,cd,q['transfer_id'],registration,ctx))
        denied('保护不能漏预算seal',d,lambda:SC.execute(d,plans))
        for i in range(len(plans)):
            denied('撤回保护缺写'+str(i),d,lambda i=i:M.B.apply(d,lambda:plans[:i]+plans[i+1:],ctx))
        before_budget=[tuple(x) for x in d.execute('SELECT operation_id,episodes_left FROM pb_balance ORDER BY operation_id')]
        # PQ计划归属受损的第2代账户；其预算覆盖计划捕获的旧历史，一条use加一条seal。
        for i in range(len(plans)+2):
            denied('撤回保护逐写异常'+str(i),d,lambda i=i:M.withdraw(d,cd,q['transfer_id'],registration,ctx,fail_after=i),'injected')
        M.withdraw(d,cd,q['transfer_id'],registration,ctx)
        after_budget=[tuple(x) for x in d.execute('SELECT operation_id,episodes_left FROM pb_balance ORDER BY operation_id')]
        check('只扣受损代账户且保留旧账',[(n,v-1 if n=='recovery.1' else v) for n,v in before_budget]==after_budget)
        check('撤回暂停当前run',d.execute('SELECT lifecycle FROM run').fetchone()[0]=='paused')
        check('保护目标含两Controller',d.execute("SELECT count(*) FROM pq_target").fetchone()[0]==2)
        check('保护捕获新普通提交',sub in json.loads(d.execute('SELECT members_body FROM pq_plan').fetchone()[0])['submissions'])
        measurements=[json.loads(row[0]) for row in d.execute("SELECT measurement_body FROM pb_use WHERE plan_id LIKE 'pq.%'")]
        check('新撤回原件计入实际预算',all(x['changed_tables'].get('cn_withdrawal')==1 for x in measurements))
        check('撤回不冒充来源故障',d.execute('SELECT count(*) FROM ib_use').fetchone()[0]==1)
        denied('暂停后不再提交下一动作',d,lambda:C.tx(d,lambda:F.ready_steps(d,ex,'step.1',ctx)))
        before=SC.snapshot(d);M.withdraw(d,cd,q['transfer_id'],registration,ctx);check('重复撤回不重复扣账',SC.snapshot(d)==before)
        M.receive_event(d,W.event(13),ctx);check('暂停且仍占执行槽时新事件抑制',d.execute("SELECT result FROM ingress_decision ORDER BY rowid DESC LIMIT 1").fetchone()[0]=='suppressed_busy'
            and d.execute('SELECT count(*) FROM execution').fetchone()[0]==2)
        for i,db in enumerate(dbs):check('外键完整'+str(i),not db.execute('PRAGMA foreign_key_check').fetchall())
        return checks
    finally:
        for d in dbs:d.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'continuation-trigger-report.json'
    def read(path):return subprocess.check_output(['git','show',':'+path.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else path.read_bytes()
    if a.check_report:
        report=json.loads(read(target));assert report['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(read(p)).hexdigest() for p in INPUTS};print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=119,controller_tables=236,
            runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if a.report:target.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
