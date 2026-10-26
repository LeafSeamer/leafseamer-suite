"""完整306表恢复链的提供者来源及撤回下界验证；不运行业务服务。"""
import argparse,copy,hashlib,json,sqlite3,subprocess,sys,tempfile
from functools import lru_cache
from pathlib import Path
import check_open_time_source as F
import open_provider_source_model as O
P=O.P;N=O.N;M=O.M;T=O.T;HERE=O.HERE;ROOT=HERE.parents[2];C=F.F
@lru_cache(maxsize=1)
def provider_template():
    script='import check_adoption as C,json;print(json.dumps(dict(context=C.template(),inputs=[str(p) for p in C.inputs()])))'
    return json.loads(subprocess.check_output([sys.executable,'-c',script],cwd=HERE.parent/'df03-provider'))
def inputs():return list(dict.fromkeys(F.inputs()+[Path(p) for p in provider_template()['inputs']]+[HERE/n for n in ('open_provider_source_model.py','check_open_provider_source.py','OPEN_PROVIDER_SOURCE.md')]))
def register_provider(supervisor,worker):
    source=worker['source'];S=P.P.S;sid=worker['intent']['supervisor_instance_id'];runtime,descriptor=S.runtime(supervisor,sid)
    intent=copy.deepcopy(worker['intent']);intent.pop('extension_binding',None)
    intent.update(launch_id='time',member_id='time.member',role='time_provider',device_ids=[],containment_ref=dict(group_id='group.time',generation='group.gen.time',backend='windows_job'))
    receipt=copy.deepcopy(worker['admission_receipt']);receipt.update(launch_id='time',member_id='time.member',role='time_provider',
        launch_intent_digest=S.digest(intent),member_boot_id='boot.time',bootstrap_id='bootstrap.time',channel_binding_id='channel.time',receipt_id='receipt.time',
        containment_ref=intent['containment_ref'],os_observation_ref='process.time',admitted_tick_ns='15')
    obs=dict(format_version='process-admission-observation/1',observation_id='process.time',provider_id=source['os_provider_id'],domain_ref=S.domain(descriptor),
        member_id='time.member',member_boot_id='boot.time',channel_binding_id='channel.time',containment_ref=intent['containment_ref'],artifact_manifest_ref=intent['artifact_manifest_ref'],
        observed_tick_ns='15',process_instance_ref=dict(id='synthetic.time.process',revision='1',digest=S.digest('synthetic.time.process')),group_owned=True,artifact_matches=True,channel_exclusive=True)
    J=C.F.SR.F.J
    with J.tx(supervisor):
        supervisor.execute('INSERT INTO launch_intent VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,'time',S.digest(intent),S.raw(intent),'time.member','time_provider','group.time','group.gen.time','protected_config',S.raw(dict(protected_policy_digest=runtime['protected_policy_digest'],intent_digest=S.digest(intent)))))
        supervisor.execute('INSERT INTO launch_state(supervisor_id,launch_id) VALUES(?,?)',(sid,'time'));J.attempt(supervisor,'time',sid,protected=True,recovery=False)
        supervisor.execute("UPDATE launch_state SET state='awaiting_bootstrap' WHERE supervisor_id=? AND launch_id='time'",(sid,))
        supervisor.execute('INSERT INTO bootstrap_challenge VALUES(?,?,?,?,?,?,?,?)',(sid,'time','bootstrap.time','boot.time','channel.time','10','20',S.digest('synthetic.transcript')))
        supervisor.execute('INSERT INTO os_observation VALUES(?,?,?,?,?,?,?,?,?)',('process.time',sid,'time',sid,'process_instance','group.time','group.gen.time','15',S.raw(obs)))
        supervisor.execute('INSERT INTO admission_receipt VALUES(?,?,?,?,?,?,?)',(sid,'time','receipt.time','bootstrap.time','process.time','15',S.raw(receipt)))
        supervisor.execute("UPDATE launch_state SET state='admitted_closed',admission_id='receipt.time' WHERE supervisor_id=? AND launch_id='time'",(sid,))
    return P.P.capture(supervisor,sid,'time',source)
def start_time(db,others,eid):
    worker=F.O.R.runtime(db,eid)[0];sid=worker['intent']['supervisor_instance_id']
    candidates=[]
    for d in dict.fromkeys(others):
        if d.execute("SELECT 1 FROM sqlite_schema WHERE name='journal_meta'").fetchone():
            r=d.execute('SELECT descriptor_digest FROM runtime WHERE supervisor_id=?',(sid,)).fetchone()
            if r and r[0]==worker['binding']['descriptor_digest']:candidates.append(d)
    M.need(len(candidates)==1,'provider_supervisor_unique');sd=candidates[0];runtime=register_provider(sd,worker)
    template=copy.deepcopy(provider_template()['context']);config=template['config'];channel=template['channel'];source=runtime['source']
    domain=dict(worker['binding']['scope'],provider_id='time.member',provider_boot_id='boot.time',runtime_binding_ref=P.P.reference(runtime),clock_generation='1',**P.P.S.domain(runtime['descriptor']))
    manifest=runtime['intent']['artifact_manifest_ref'];artifact=dict(id=manifest['manifest_id'],revision=manifest['revision'],digest=manifest['digest'])
    config['profile']['collector_artifact_ref']=artifact;P.T.seal(config['profile'],'profile_digest')
    config['approval'].update(authority_service_id=source['service_id'],profile_ref=P.cref(config['profile'],'profile'));P.T.seal(config['approval'],'approval_digest')
    config['binding'].update(domain=domain,profile_ref=P.cref(config['profile'],'profile'),approval_ref=P.cref(config['approval'],'approval'))
    channel.update(channel_id='channel.time',domain=domain,core_boot_id=worker['binding']['controller_boot_id'],bootstrap_receipt_ref=P.receipt_ref(runtime))
    config.update(bootstrap_receipt_ref=channel['bootstrap_receipt_ref'],collector_artifact_ref=artifact);P.T.seal(config,'config_digest')
    state=copy.deepcopy(template['time_context']['state']);state.update(revision='1',status='collecting',binding=config['binding'],current_anchor_ref=None,invalidation_ref=None);P.T.seal(state,'state_digest')
    P.install(db)
    db.execute(*P.insert('ts_scope',1,source['service_id'],source['database_instance_id'],'reference-time-storage/0.1.0-draft.1'))
    db.execute(*P.insert('tc_policy',1,1,1,100000,8,1,64,P.raw(config['limits'])))
    db.execute(*P.insert('tc_source','source.slot',P.T.digest(config['source']),P.raw(config['source'])))
    adoption,_=P.adopt(db,sd,sid,'time',source,channel,config,state,'source.slot','binding.initial','bootstrap.initial',F.ref('synthetic.interval'))
    return adoption
def revoke(db,value,**fault):
    inv=P.T.seal(dict(invalidation_id='provider.invalidate',revision='1',old_binding=value['configuration']['binding'],next_time_generation='2',
        cause_ref=F.ref('synthetic.cause'),deny_new_utc_permits=True,protection_operation_ref=F.ref('synthetic.protection')),'invalidation_digest')
    return P.revoke(db,'channel.time',inv,'invalidate.commit','binding.next','stop.intent',**fault)
def fixture(withdrawn=False,placeholder=False):
    db,others,v=C.fixture()
    try:
        C.R.capture(db,'cancel','all','all',v['refs'],v['context']);adoption=start_time(db,others,v['eid'])
        if withdrawn:revoke(db,adoption)
        _,_,snapshot,_=N.transaction(db,lambda:O.floor_source(db))
        S=F.S;S.install(db);S.R.install(db);C.T.U.protection(db,'source.protect',run='unrelated_run')
        S.R.capture(db,'run.full');S.capture(db,'command.full',C.F.DEVICES[0])
        links=dict(C.F.O.LINKS,run_snapshot_ref='run.full',command_snapshot_ref='command.full',time_snapshot_ref='pending.time' if placeholder else snapshot['snapshot_id'])
        S.R.O.recover(db,'full.recovery','full.snapshot',v['eid'],links,'22','100',C.F.O.E.ref('provider.full'),v['selections'])
        C.F.O.fence(db,v['cid'],v['sid']);return db,others,adoption,snapshot
    except BaseException:
        for c in dict.fromkeys([db]+others):c.close()
        raise
def run():
    checks=[];connections=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fresh(**kw):
        db,others,a,s=fixture(**kw);connections.extend([db]+others);return db,a,s
    def clone(db):
        d=sqlite3.connect(':memory:',isolation_level=None);db.backup(d);d.execute('PRAGMA foreign_keys=ON');d.execute('PRAGMA recursive_triggers=ON');connections.append(d);return d
    def read(db,retained=None):return N.transaction(db,lambda:O.for_open(db,'full.recovery','full.fence','27',retained))
    def denied(name,fn,reason):
        try:fn()
        except Exception as error:
            chain=[]
            while error:chain.append(str(error));error=error.__cause__
            assert any(reason in s for s in chain),(name,chain);check(name)
        else:raise AssertionError('应拒绝:'+name)
    try:
        db,adoption,snapshot=fresh();before=C.state(db);sources=read(db)
        check('完整306表组合',len(before)==306)
        check('原运行和命令拒绝来源均非空',bool(sources['run_deny_snapshot']['entries']) and bool(sources['command_deny_snapshot']['entries']))
        check('采用原件实际进入恢复读取',sources['originals']['time_provider_adoption']==adoption)
        check('时间下界来自同库固定State',sources['reference_time_snapshot']==snapshot and sources['time_source_provenance']=='current_adoption')
        check('worker与provider不同成员同域',sources['originals']['worker_runtime']['admission_receipt']['member_boot_id']!=adoption['runtime']['admission_receipt']['member_boot_id'] and sources['binding']['clock_domain_id']==snapshot['domain']['clock_domain_id'])
        check('读取无写入且仍protected',before==C.state(db) and sources['control_before']['gate_state']=='protected')
        changed=clone(db);revocation,_=revoke(changed,adoption)
        denied('撤回后旧恢复引用拒绝',lambda:read(changed),'open_time_snapshot_reference')
        denied('撤回后不返回有效提供者',lambda:N.transaction(changed,lambda:P.current(changed)),'provider_revoked')
        old,state,floor,kind=N.transaction(changed,lambda:O.floor_source(changed))
        check('撤回仅保留提高的拒绝下界',old==adoption and state['status']=='unavailable' and floor['minimum_time_generation']=='2' and kind=='withdrawn_floor_only')
        check('不可用来源无UTC锚',state['current_anchor_ref'] is None)
        for field,reason in (('adoption_ref','provider_floor_revocation'),('invalidation_ref','provider_floor_invalidation'),
            ('cause_ref','provider_floor_invalidation'),('next_binding_storage_id','provider_floor_invalidation'),('invalidation_commit_id','provider_floor_revocation')):
            c=clone(db);bad=copy.deepcopy(revocation)
            if isinstance(bad[field],dict):bad[field]['id']='wrong.original'
            else:bad[field]='wrong.original'
            P.T.seal(bad,'revocation_digest');expected=P.raw(revocation);altered=P.raw(bad)
            class WrongOriginal:
                # 在首次INSERT时注入错原件；不改已提交历史，不绕SQL触发器。
                def __getattr__(self,k):return getattr(c,k)
                def execute(self,sql,args=()):return c.execute(sql,tuple(altered if isinstance(v,bytes) and v==expected else v for v in args))
            revoke(WrongOriginal(),adoption)
            denied('重新摘要仍拒撤回错关联:'+field,lambda:N.transaction(c,lambda:O.floor_source(c)),reason)
        for index in range(10):
            c=clone(db);saved=C.state(c)
            denied('撤回逐写异常:'+str(index),lambda:revoke(c,adoption,fail_after=index),'synthetic_write_fault')
            check('306表整笔回滚:'+str(index),C.state(c)==saved)
            check('回滚仍原恢复引用:'+str(index),read(c)['reference_time_snapshot']==snapshot)
        closed,a,s=fresh(withdrawn=True)
        result=read(closed)
        check('重新选择撤回后下界可供恢复前态',result['reference_time_snapshot']==s and result['time_source_provenance']=='withdrawn_floor_only')
        check('恢复没有复活Provider',result['originals']['time_state']['status']=='unavailable' and result['originals']['time_state']['current_anchor_ref'] is None)
        check('撤回后仍无最终许可',not closed.execute('SELECT 1 FROM ci_issue').fetchone())
        retained=copy.deepcopy(s);retained['minimum_time_generation']='3';P.T.seal(retained,'snapshot_digest')
        denied('较高已安装下界不可回退',lambda:read(closed,retained),'time_retained_floor')
        with tempfile.TemporaryDirectory(prefix='leafseamer-provider-open-') as folder:
            path=Path(folder)/'case.sqlite';left=sqlite3.connect(path,isolation_level=None);right=None
            try:
                db.backup(left);check('实际WAL模式',left.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal')
                left.execute('PRAGMA foreign_keys=ON');left.execute('PRAGMA recursive_triggers=ON')
                right=sqlite3.connect(path,isolation_level=None,timeout=0);right.execute('PRAGMA foreign_keys=ON');right.execute('PRAGMA recursive_triggers=ON')
                left.execute('BEGIN');check('旧读事务初始原件',O.for_open(left,'full.recovery','full.fence','27')['reference_time_snapshot']==snapshot)
                revoke(right,adoption);check('旧读仍可见先前采用',O.for_open(left,'full.recovery','full.fence','27')['time_source_provenance']=='current_adoption');left.rollback()
                denied('最终writer重读拒绝旧选择',lambda:read(left),'open_time_snapshot_reference')
                check('新读明确只剩拒绝下界',N.transaction(right,lambda:O.floor_source(right))[3]=='withdrawn_floor_only')
            finally:
                if right:right.close()
                left.close()
        for c in dict.fromkeys(connections):check('连接退出事务且外键完整',not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone())
        return dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=306,checks=checks,
            provider_originals_integrated=True,withdrawn_floor_not_utc_verified=True,wal_snapshot_boundary_verified=True,
            supervisor_race_closed=False,approval_authority_verified=False,time_protection_atomicity_verified=False,full_open_verified=False,device_tests_executed=0,
            inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()})
    finally:
        for c in dict.fromkeys(connections):c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'open-provider-source-report.json'
    if a.check_report:
        r=json.loads(path.read_bytes());assert r['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};print(json.dumps(dict(bindings_valid=True,inputs=len(r['inputs']),rerun=False)))
    else:
        r=run()
        if a.report:path.write_bytes(M.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
