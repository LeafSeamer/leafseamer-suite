"""当前恢复布局中的非空取消准备切点与OPEN前态离线验收。"""
import argparse,copy,hashlib,json,sqlite3
from pathlib import Path
from jsonschema.exceptions import ValidationError
import current_open_fixture as F
import command_snapshot_model as S
import check_command_snapshot as B
import check_cancel_source as T
import check_run_snapshot as U
import check_attempt_inventory as AI
C=S.C;N=C.N;P=C.P;I=C.I;raw=C.raw;digest=C.digest;seal=C.M.sealed;HERE=S.HERE;ROOT=T.ROOT
LOCAL=('current_open_fixture.py','check_prepared_cancel.py','PREPARED_CANCEL.md')
def inputs():return list(dict.fromkeys(B.inputs()+[HERE/n for n in LOCAL]))

def accept(db):
    """合成授权下登记完整取消受理写集，命令本身来自实际Seamer/Controller模型。"""
    scope=C.M.E.A.scope(db);r=C.one(db,'SELECT * FROM cm_latest');cmd=r['command_id'];n=int(r['revision'])+1
    before=N.transaction(db,lambda:C.state(db,cmd,r['revision']));after=dict(before,revision=str(n));attempts=before['attempt_ids']
    ns=C.one(db,'SELECT * FROM ca_namespace');policy=C.one(db,'SELECT completion_policy_ref FROM cm_policy WHERE command_id=?',(cmd,))['completion_policy_ref']
    content=dict(scope=scope,command_id=cmd,expected_state_ref=C.reference(cmd,digest(before),before['revision']),reason='synthetic cancellation')
    identity=dict(key=dict(target_scope=scope,**{k:ns[k] for k in ('issuer_id','issuer_epoch','principal_id','request_epoch')},operation_id='cancelCommand',idempotency_key='cancel_idem'),request_digest=digest(content))
    operation=seal(dict(cancellation_id='cancel',scope=scope,command_id=cmd,revision='1',identity=identity,state='requested',mode='before_dispatch_only',future_writes='pending',command_state_ref=C.reference(cmd,digest(after),str(n)),evidence_refs=[],reason_code=None),'operation_digest')
    receipt=seal(dict(identity=identity,command_id=cmd,scope=scope,cancellation_id='cancel',initial_operation_ref=C.reference('cancel',operation['operation_digest']),accepted_state_ref=content['expected_state_ref']),'receipt_digest')
    cancel_policy=seal(dict(policy_id='cancel_policy',revision='1',mode='before_dispatch_only',procedure_ref=None,completion_policy_ref=T.ref('completion'),release_policy_ref=T.ref('release'),resource_keys=[F.DEVICES[0]],max_transmissions=1,allow_protocol_resend=False,application_attempts=1),'policy_digest')
    binding=dict(scope=scope,cancellation_id='cancel',parent_command_id=cmd,initial_operation_ref=receipt['initial_operation_ref'],identity=identity,mode='before_dispatch_only',policy_ref=C.reference('cancel_policy',cancel_policy['policy_digest']))
    exits=N.transaction(db,lambda:[C.socket(db,e[0]) for e in db.execute('SELECT exit_id FROM ce_exit WHERE device_id=? ORDER BY exit_id',(F.DEVICES[0],))])
    targets=[seal(dict(exit=e,ordinary_attempt_ids=attempts,ordinary_transmissions=[],cancel_prepare_ids=[],cancel_transmissions=[]),'target_digest') for e in exits]
    cut=seal(dict(cut_id='ordinary',binding=binding,stage='ordinary',previous_cut_ref=None,issued_revision='0',deny_revision='1',targets=targets),'cut_digest')
    for name,value in [('CommandState',after),('CancelContent',content),('CancelOperation',operation),('CancelReceipt',receipt),('CancelPolicy',cancel_policy),('CancelCut',cut)]:C.validate(name,value)
    steps=[]
    for sql,args in T.X.V.cancel(n,key='integrated',attempts=attempts,state_args=dict(attempts=attempts)):
        table=sql.split()[2];fields=sql.split('(',1)[1].split(')',1)[0].split(',');row=dict(zip(fields,args))
        if table in ('cv_cancel_target','cv_snapshot','cv_record'):continue
        row={k:(cmd if v=='command.integrated' else v) for k,v in row.items()}
        if table=='cv_cancel_key':row.update(namespace_id=ns['namespace_id'],idempotency_key='cancel_idem',request_digest=digest(content),content_body=raw(content))
        if table=='cv_cancel':row.update(accepted_state_digest=digest(before),cut_digest=cut['cut_digest'],cut_body=raw(cut),policy_body=raw(cancel_policy))
        if table=='cv_cancel_revision':row.update(operation_digest=operation['operation_digest'],operation_body=raw(operation))
        if table=='cv_cancel_receipt':row.update(initial_operation_digest=operation['operation_digest'],receipt_digest=receipt['receipt_digest'],receipt_body=raw(receipt))
        if table=='cm_validation':row.update(subject_digest=digest(after),source_body=raw(after),policy_ref=policy)
        if table=='cm_revision':row.update(previous_digest=digest(before),state_digest=digest(after),transition_digest=digest(after),state_body=raw(after))
        if table=='cv_cancel_commit':steps.extend(I('cv_cancel_target',cancellation_id='cancel',exit_id=e['writer_exit_id']) for e in exits)
        steps.append(I(table,**row))
    def publish():
        prior=json.loads(C.one(db,'SELECT record_body FROM cv_record WHERE command_id=? AND revision=?',(cmd,r['revision']))['record_body'])
        selections=json.loads(C.one(db,'SELECT selection_body FROM av_snapshot WHERE command_id=? AND revision=?',(cmd,r['revision']))['selection_body'])
        for step in steps:
            if step[0].startswith('INSERT INTO cm_commit '):
                provider=AI.provider(after);inventory=AI.S.capture(db,cmd,str(n),provider)
                projected=AI.A.project(dict(prior,revision=str(n),state=after,state_ref=AI.M.V.state_ref(after)),inventory,selections)
                cancellation=dict(operation_ref=C.reference('cancel',operation['operation_digest']),state='requested',future_writes='pending',reason_code=None)
                projection=dict(attempts=projected['attempts'],completion=prior['completion'],cancellation=cancellation)
                proof=dict(authorized=True,originals_verified=True,projection_verified=True,redaction_verified=True,state_ref=AI.M.V.state_ref(after),view_digests=[],max_snapshot_members=32,projection=projection,projection_digest=digest(projection))
                for write in AI.E.evidence_steps(db,cmd,str(n),[],proof):db.execute(*write)
                for write in AI.S.publication_steps(db,cmd,str(n),inventory,selections,provider):db.execute(*write)
                AI.M.complete_record(db,C.one(db,'SELECT * FROM cv_record WHERE command_id=? AND revision=?',(cmd,P.u(n))),attempt_source=AI.S.source)
            db.execute(*step)
    N.transaction(db,publish);return cut

def context(db,tick='205'):
    row=C.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(F.DEVICES[0],))
    return dict(clock_domain_id=row['clock_domain'],descriptor_digest=row['descriptor'],selected_tick_ns=tick)

def integrated(snapshot_stage='all',capture_seeds=None):
    observed={}
    def before_restart(db):
        observed['issue_plan_counts']=[db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('ci_issue','go_plan')]
        observed['ordinary_expected']=accept(db);observed['context']=context(db)
        if capture_seeds is not None:capture_seeds('accepted',db)
        observed['ordinary'],observed['ordinary_writes']=C.capture(db,'cancel','ordinary','ordinary',prepare_context=observed['context'])
        if capture_seeds is not None:capture_seeds('ordinary',db)
        S.install(db);S.capture(db,'ordinary.snapshot',F.DEVICES[0])
        observed['all'],observed['all_writes']=C.capture(db,'cancel','all','all',prepare_context=context(db,'206'))
    db,others,eid,cid,sid,selections=F.fixture(before_restart);S.R.install(db)
    U.protection(db,'source.protect',run='unrelated_run');run=S.R.capture(db,'run.full')[0];commands=S.capture(db,'command.full',F.DEVICES[0])[0]
    links=dict(F.O.LINKS,run_snapshot_ref='run.full',command_snapshot_ref='command.full' if snapshot_stage=='all' else 'ordinary.snapshot')
    S.R.O.recover(db,'full.recovery','full.snapshot',eid,links,'22','100',F.O.E.ref('provider.full'),selections);F.O.fence(db,cid,sid)
    observed.update(run=run,commands=commands,eid=eid);return db,others,observed

def run():
    checks=[];dbs=[];seeds={}
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def clone(db):
        other=sqlite3.connect(':memory:',isolation_level=None);db.backup(other);other.execute('PRAGMA foreign_keys=ON');other.execute('PRAGMA recursive_triggers=ON');dbs.append(other);return other
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,sqlite3.Error,ValidationError) as e:
            messages=[]
            while e:
                assert isinstance(e,(ValueError,RuntimeError,sqlite3.Error,ValidationError)),type(e)
                messages.append(str(e));e=e.__cause__
            if reason:assert any(reason in m for m in messages),(name,messages)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    def state(db):
        return {name:sorted([tuple(row) for row in db.execute('SELECT * FROM '+name)],key=repr) for name, in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")}
    class Omit:
        def __init__(self,db,index):self.db=db;self.index=index;self.count=0
        def __getattr__(self,key):return getattr(self.db,key)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '):
                n=self.count;self.count+=1
                if n==self.index:return self.db.execute('SELECT 1 WHERE 0')
            return self.db.execute(sql,args)
    def atomic(seed,stage,ctx,label):
        probe=clone(seed);_,writes=C.capture(probe,'cancel',stage,stage,prepare_context=ctx)
        for index in range(len(writes)):
            db=clone(seed);before=state(db);denied(label+'逐写:'+str(index),lambda:C.capture(db,'cancel',stage,stage,index,prepare_context=ctx),'injected');check(label+'回滚:'+str(index),state(db)==before)
            db=clone(seed);before=state(db);denied(label+'缺写:'+str(index),lambda:C.capture(Omit(db,index),'cancel',stage,stage,prepare_context=ctx));check(label+'漏写回滚:'+str(index),state(db)==before)
        return writes
    try:
        db,others,v=integrated(capture_seeds=lambda name,c:seeds.update({name:clone(c)}));dbs.extend(others)
        result=N.transaction(db,lambda:S.for_open(db,'full.recovery','full.fence','27'))
        check('275表完整恢复非空双快照进入OPEN前态',len(state(db))==275 and len(result['run_deny_snapshot']['entries'])==len(result['command_deny_snapshot']['entries'])==1 and result['command_deny_snapshot']==v['commands'])
        check('实际准备成员纳入两阶段cut',db.execute('SELECT count(*) FROM pd_member WHERE cut_id IN(SELECT prepare_cut_id FROM cc_cut)').fetchone()[0]==2 and all('pd_member' in v[k] for k in ('ordinary_writes','all_writes')))
        check('取消受理保留完整固定attempt库存',db.execute('SELECT count(*) FROM av_snapshot').fetchone()[0]==2 and N.transaction(db,lambda:C.admission(db,'cancel'))[0]==v['ordinary']['binding'])
        check('本轮未新增开放计划或最终发送许可',v['issue_plan_counts']==[db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('ci_issue','go_plan')] and not db.execute("SELECT 1 FROM go_plan WHERE snapshot_id='full.snapshot'").fetchone())
        before=state(db);check('新域重入只读取旧域历史切点',C.capture(db,'cancel','ordinary','ordinary',prepare_context=v['context'])==(v['ordinary'],[]) and state(db)==before)
        denied('重入不能改时钟上下文',lambda:C.capture(db,'cancel','ordinary','ordinary',prepare_context=context(db,'27')),'cancel_cut_replay_conflict')
        for stage,seed in seeds.items():
            if stage=='accepted':atomic(seed,'ordinary',v['context'],'ordinary既有撤销')
            else:atomic(seed,'all',dict(v['context'],selected_tick_ns='206'),'all既有撤销')
        denied('完整布局不得省准备上下文',lambda:C.capture(clone(seeds['accepted']),'cancel','ordinary','ordinary'),'cancel_prepare_context_required')
        for name,ctx in [('旧tick',dict(v['context'],selected_tick_ns='199')),('错域',dict(v['context'],clock_domain_id='clock_'+'0'*64)),('错描述',dict(v['context'],descriptor_digest=digest('wrong')))]:
            candidate=clone(seeds['accepted']);before=state(candidate);denied(name,lambda:C.capture(candidate,'cancel','ordinary','ordinary',prepare_context=ctx),'cancel_prepare_domain');check(name+'无残留',state(candidate)==before)
        for table in ('pd_member','pd_cut_commit'):
            candidate=clone(seeds['ordinary']);record=C.one(candidate,'SELECT * FROM '+table+' LIMIT 1')
            denied('准备原件不可变:'+table,lambda:candidate.execute('DELETE FROM '+table),'immutable_prepare_deny')
        source=N.transaction(db,lambda:C.read_prepare_cut(db,v['ordinary']))
        for name,sample in [('CancelPrepareContext',v['context']),('CancelPrepareSource',source)]:
            for key in sample:
                wrong=copy.deepcopy(sample);del wrong[key];denied('Schema必填:'+name+':'+key,lambda name=name,wrong=wrong:C.validate(name,wrong))
            wrong=dict(sample,extra=True);denied('Schema拒绝扩字段:'+name,lambda name=name,wrong=wrong:C.validate(name,wrong))
        candidate=clone(db)
        # 隔离损坏原件：同时重算摘要和seal，也不能改变所引用控制代次的真实时钟域。
        for table in ('pd_cut','pd_cut_commit'):
            for t in candidate.execute("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name=? AND sql LIKE '%BEFORE UPDATE%'",(table,)).fetchall():candidate.execute('DROP TRIGGER '+t[0])
        pid=C.one(candidate,"SELECT prepare_cut_id FROM cc_cut WHERE cut_id='ordinary'")['prepare_cut_id'];wrong=dict(source,clock_domain_id='clock_'+'0'*64);body=raw(wrong)
        candidate.execute('UPDATE pd_cut SET selector_body=?,selector_digest=? WHERE cut_id=?',(body,digest(wrong),pid));candidate.execute('UPDATE pd_cut_commit SET audit_body=?,outbox_body=? WHERE cut_id=?',(body,body,pid))
        denied('重算摘要仍不能换历史时钟域',lambda:N.transaction(candidate,lambda:C.read_cut(candidate,'ordinary')),'cancel_prepare_domain')
        candidate=clone(db)
        for t in candidate.execute("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name='pd_member' AND sql LIKE '%BEFORE UPDATE%'").fetchall():candidate.execute('DROP TRIGGER '+t[0])
        candidate.execute('UPDATE pd_member SET authorization_digest=? WHERE cut_id=?',(digest('wrong'),pid))
        denied('同数量错授权成员拒绝',lambda:N.transaction(candidate,lambda:C.read_cut(candidate,'ordinary')),'cancel_prepare_members')
        stale,others,_=integrated('ordinary');dbs.extend(others)
        denied('真实恢复链拒绝同数量旧命令水位',lambda:N.transaction(stale,lambda:S.for_open(stale,'full.recovery','full.fence','27')),'command_snapshot_stale')
        fresh={}
        def before_protection(c):
            if not fresh:fresh['db']=clone(c)
        unused,others,*_=F.fixture(before_protection=before_protection);dbs.extend(others);freshdb=fresh['db'];check('新撤销支路此前没有撤销原件',freshdb.execute('SELECT count(*) FROM ep_revocation').fetchone()[0]==0)
        accept(freshdb);freshctx=context(freshdb,'50');writes=atomic(freshdb,'ordinary',freshctx,'ordinary新撤销');check('准备撤销与两阶段seal同一事务','ep_revocation' in writes)
        class CommitFault:
            def __init__(self,db,committed):self.db=db;self.committed=committed
            def __getattr__(self,key):return getattr(self.db,key)
            def commit(self):
                if self.committed:self.db.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation')
        for committed in (False,True):
            candidate=clone(freshdb);before=state(candidate)
            denied('准备撤销提交观察失效:'+str(committed),lambda:C.capture(CommitFault(candidate,committed),'cancel','ordinary','ordinary',prepare_context=freshctx))
            if committed:
                after=state(candidate);check('提交后按原ID查原不重撤销',C.capture(candidate,'cancel','ordinary','ordinary',prepare_context=freshctx)[1]==[] and state(candidate)==after)
            else:check('提交前故障连同新撤销全回滚',state(candidate)==before)
        body,_=C.capture(freshdb,'cancel','ordinary','ordinary',prepare_context=freshctx);check('新撤销原件可重建',N.transaction(freshdb,lambda:C.read_cut(freshdb,'ordinary'))==body)
        def only_ordinary(c):accept(c);C.capture(c,'cancel','ordinary','ordinary',prepare_context=context(c))
        crossed,others,*_=F.fixture(only_ordinary);dbs.extend(others);before=state(crossed)
        denied('新域不能用裸tick核销旧域准备',lambda:C.capture(crossed,'cancel','all','all',prepare_context=context(crossed,'27')),'cancel_prepare_cross_domain');check('跨域拒绝不留下部分cut',state(crossed)==before)
        for c in dbs:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in dbs:c.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'prepared-cancel-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),integrated_controller_tables=275,prepared_cut_transaction_verified=True,integrated_nonempty_open_sources_verified=True,full_open_verified=False,cross_domain_prepare_retirement_supported=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(raw(v))
        print(json.dumps({k:v for k,v in v.items() if k not in ('checks','inputs')}))
