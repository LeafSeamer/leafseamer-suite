"""实际组合SQLite中的完整执行和命令请求持久化及故障回滚。"""
import argparse,copy,hashlib,json,sqlite3
from pathlib import Path
from jsonschema.exceptions import ValidationError
import typed_seamer_model as M
import check_continuation_trigger as T
import check_continuation_binding as Q
G=M.G;C=T.C;R=T.R;P=T.P;I=T.I;SC=T.SC;AT=T.AT
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def fixture(*,sql_factory=G.build,controller_factory=T.G.controller_sql,expected_control=None):
    d,q,s,cds,ctx=T.T.fixture(seamer_factory=sql_factory,controller_factory=controller_factory)
    old,_,_=Q.J.fixtures();template=Q.upgraded(old)['DISPATCH']['body']['request']
    steps=copy.deepcopy(ctx['evaluations']['r0']['steps'])
    for n,step in enumerate(steps):
        fixed={k:copy.deepcopy(template[k]) for k in ('capability_version','expected_control','required_completion','preconditions','dispatch','evidence_timeout_ms')}
        if expected_control is not None:fixed['expected_control']=copy.deepcopy(expected_control)
        fixed.update(action_id='synthetic.set',device_id='dev.1',parameters=dict(value=n))
        step.update(request=fixed,logical_action_id='action.'+str(n))
    plan=dict(ref=T.T.ref(q['origin_scope'],'continued.plan',T.M.M.digest(steps)),steps=steps)
    q=T.M.M.seal(dict(q,continuation_plan_ref=plan['ref']),'request_digest');s.update(binding={k:q[k] for k in s['binding']},approval_subject=T.M.M.approval_subject(q))
    for cd,cc in cds.values():cc.update(plan_ref=plan['ref'],approval_subject=T.M.M.approval_subject(q),parameters_verified=True)
    a,rs=T.T.issued(d,q,s,cds);C.adopt(d,q,a,s,cds);C.finish(d,q,s,cds)
    ctx['evaluations']['r0']['steps']=steps;ctx['continuation_plans']={'r0':plan}
    digest=R.one(d,'ingress_listener','run_id','r0')['artifact_digest']
    clock={k:old['GUARD_INSTALL']['body']['guard'][k] for k in ('clock_domain_id','descriptor_digest')}
    ctx.update(clock=clock,program_current=True,clock_current=True,namespace_current=True,
        typed_programs={'r0':dict(artifact_ref=M.ref('artifact',q['origin_scope'],'synthetic-artifact',digest),definition_version='1')},
        command_namespace=dict(context_id='typed-context',issuer_id='typed-issuer',issuer_epoch='issuer-1',principal_id='seamer-service',request_epoch='request-1'))
    return d,q,cds,ctx
def start(d,ctx):
    M.receive_event(d,T.W.event(12),ctx);ex=T.active(d);C.tx(d,lambda:T.F.anchor_steps(d,ex,ctx));return ex
def deferred_probe():
    # 仅隔离内存库禁用新增seal，观察原引擎提交行为；不修改正式DDL。
    d,q,cds,ctx=fixture()
    try:
        d.execute('DROP TRIGGER typed_plan_source_seal')
        writes=AT.planned(d,lambda:M.ingress_steps(d,T.W.event(12),ctx))
        omitted=[w for w in writes if T.M.inserted(*w)[0]!='typed_execution_source']
        try:SC.execute(d,omitted);committed=True
        except sqlite3.IntegrityError:committed=False
        return dict(sqlite_version=sqlite3.sqlite_version,foreign_keys=d.execute('PRAGMA foreign_keys').fetchone()[0],
            omitted_source_committed=committed,violations=[dict(table=r[0],parent=r[2],constraint=r[3]) for r in d.execute('PRAGMA foreign_key_check')],
            cause='not_determined',production_clearance=False)
    finally:
        for db in [d]+[x[0] for x in cds.values()]:db.close()
def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def fresh():
        d,q,cds,ctx=fixture();dbs.append(d);dbs.extend(x[0] for x in cds.values());return d,q,cds,ctx
    def denied(n,d,fn,reason=None):
        before=SC.snapshot(d)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError) as err:
            if reason:assert reason in str(err),(n,str(err))
            check(n,SC.snapshot(d)==before);return
        raise AssertionError(n)
    def atomic(n,d,builder):
        writes=AT.planned(d,builder)
        for i in range(len(writes)):
            denied(n+'写后异常'+str(i),d,lambda i=i:M.apply(d,builder,fail_after=i),'injected')
        return writes
    try:
        check('生成SQL一致',(HERE/'seamer-typed.sql').read_bytes()==G.build())
        d,q,cds,ctx=fresh();check('Seamer120表',len(SC.snapshot(d))==120)
        check('外键已启用',d.execute('PRAGMA foreign_keys').fetchone()[0]==1)
        denied('失效编译原件不计划',d,lambda:M.receive_event(d,T.W.event(12),dict(ctx,program_current=False)))
        denied('失效时钟不计划',d,lambda:M.receive_event(d,T.W.event(12),dict(ctx,clock_current=False)))
        writes=atomic('完整执行摄取',d,lambda:M.ingress_steps(d,T.W.event(12),ctx))
        index=next(i for i,w in enumerate(writes) if T.M.inserted(*w)[0]=='typed_execution_source')
        denied('漏原件写入不能提交',d,lambda:SC.execute(d,writes[:index]+writes[index+1:]),'typed_source_required_at_seal')
        denied('SQL不允许无完整执行正文',d,lambda:SC.execute(d,SC.mutate(writes,'execution',dict(binding_body=b'{}'))))
        denied('SQL原件错输入快照',d,lambda:SC.execute(d,SC.mutate(writes,'typed_execution_source',dict(snapshot_id='wrong'))))
        ex=start(d,ctx);e=R.one(d,'execution','execution_id',ex);eb=json.loads(e['binding_body']);M.S.validate('ExecutionBinding',eb)
        check('执行正文实际持久且摘要正确',e['binding_digest']==M.T.M.digest({k:v for k,v in eb.items() if k!='binding_digest'}))
        check('批准计划与执行计划独立',eb['plan_digest']!=q['continuation_plan_ref']['digest'])
        source=R.one(d,'typed_execution_source','execution_id',ex)
        check('完整参数快照摘要',json.loads(source['parameters_ref_body'])['digest']==P.digest(source['parameters_body']))
        before=SC.snapshot(d);check('重复摄取不再创建计划',M.receive_event(d,T.W.event(12),dict(ctx,program_current=False))=='existing' and SC.snapshot(d)==before)
        denied('原件不可更新',d,lambda:SC.execute(d,[('UPDATE typed_execution_source SET clock_body=?',(b'{}',))]),'immutable')
        C.tx(d,lambda:T.F.ready_steps(d,ex,'step.0',ctx));writes=atomic('完整提交',d,lambda:M.submit_steps(d,ex,'step.0',ctx))
        for i in range(len(writes)):denied('提交漏写'+str(i),d,lambda i=i:SC.execute(d,writes[:i]+writes[i+1:]))
        denied('新提交命名空间失效',d,lambda:M.submit(d,ex,'step.0',dict(ctx,namespace_current=False)))
        changed=copy.deepcopy(ctx);changed['clock']['descriptor_digest']=M.T.M.digest('other')
        denied('时钟域变化禁止新提交',d,lambda:M.submit(d,ex,'step.0',changed),'clock_domain_changed')
        denied('SQL身份epoch不匹配',d,lambda:SC.execute(d,SC.mutate(writes,'command_submission',dict(issuer_epoch='other'))))
        denied('SQL拒旧简化正文',d,lambda:SC.execute(d,SC.mutate(writes,'command_submission',dict(request_body=b'{"device_id":"dev.1"}'))))
        changed=copy.deepcopy(ctx);changed['typed_programs']['r0']['definition_version']='999'
        check('完整提交成功',M.submit(d,ex,'step.0',changed)=='accepted')
        sub=T.F.step(d,ex,'step.0')['submission_id'];sr=R.one(d,'command_submission','submission_id',sub)
        check('六类旧差异已消除',M.S.findings(d,sub)==[])
        check('实际命名空间epoch保存',sr['issuer_epoch']=='issuer-1')
        check('固定版本来自持久原件',json.loads(sr['request_body'])['run_binding']['definition_version']==source['definition_version']=='1')
        check('摘要仅对内容',sr['request_digest']==M.T.M.digest(M.B.content(json.loads(sr['request_body']))))
        indexes=[tuple(r[2] for r in d.execute('PRAGMA index_info('+x[1]+')')) for x in d.execute('PRAGMA index_list(command_submission)') if x[2]]
        check('完整八列唯一键',('target_authority','target_database','issuer_id','issuer_epoch','principal_id','request_epoch','operation_id','idempotency_key') in indexes)
        check('旧七列唯一键移除',('target_authority','target_database','issuer_id','principal_id','request_epoch','operation_id','idempotency_key') not in indexes)
        before=SC.snapshot(d);check('重进提交仅返回已存结果',M.submit(d,ex,'step.0',dict(ctx,namespace_current=False))=='existing' and SC.snapshot(d)==before)
        other=copy.deepcopy(ctx);other['command_namespace']['principal_id']='other-service'
        denied('异主体不能查原结果',d,lambda:M.submit(d,ex,'step.0',other),'historical_namespace_owner')
        denied('持久身份不可更新',d,lambda:SC.execute(d,[('UPDATE command_submission SET issuer_epoch=?',('other',))]),'immutable')
        T.F.attempt(d,sub,ctx);check('完整请求仍进入原attempt状态机',R.one(d,'command_submission','submission_id',sub)['state']=='attempt_recorded')
        C.tx(d,lambda:T.F.ready_steps(d,ex,'step.1',ctx));M.submit(d,ex,'step.1',ctx)
        sub2=T.F.step(d,ex,'step.1')['submission_id'];check('两目标新请求均完整',M.S.findings(d,sub2)==[])
        check('两动作键独立',R.one(d,'command_submission','submission_id',sub2)['idempotency_key']!=sr['idempotency_key'])
        d.execute('PRAGMA foreign_keys=OFF');denied('外键关闭拒绝writer',d,lambda:M.submit(d,ex,'step.0',ctx),'foreign_keys_required');d.execute('PRAGMA foreign_keys=ON')
        probe=deferred_probe();check('外键诊断有明确环境与边界',probe['foreign_keys']==1 and not probe['production_clearance'])
        extra,_,extra_cds,extra_ctx=fresh();extra.execute('DROP TRIGGER typed_plan_source_seal')
        missing=AT.planned(extra,lambda:M.ingress_steps(extra,T.W.event(12),extra_ctx));missing=[w for w in missing if T.M.inserted(*w)[0]!='typed_execution_source']
        denied('独立提交前外键检查阻断漏原件',extra,lambda:M.apply(extra,lambda:missing),'foreign_key_check_failed')
        for db in dbs:check('外键完整'+str(len(checks)),not db.execute('PRAGMA foreign_key_check').fetchall())
        return checks,probe
    finally:
        for d in dbs:d.close()
def inputs():
    prior=json.loads((HERE/'command-contract-report.json').read_bytes())
    return list(dict.fromkeys([ROOT/p for p in prior['inputs']]+T.INPUTS+G.SOURCES+[HERE/n for n in ('command-contract-report.json','typed_seamer_model.py','check_typed_seamer.py','seamer-typed.sql','TYPED_SEAMER.md')]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};path=HERE/'typed-seamer-report.json'
    if a.check_report:
        assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks,probe=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=120,deferred_fk_probe=probe,
            controller_typed_admission=False,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(M.S.G.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
