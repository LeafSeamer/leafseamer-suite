"""监督原件与Controller采用写集的离线验收；不启动产品服务。"""
import argparse,copy,hashlib,json,sqlite3,subprocess,sys
from functools import lru_cache
from jsonschema.exceptions import ValidationError
import adoption_model as M
import check_time_provider_source as P
G=M.G;ROOT=G.HERE.parents[2]
@lru_cache(maxsize=1)
def template():
    script='import check_contracts as C,json;print(json.dumps(C.fixture()[0]))'
    return json.loads(subprocess.check_output([sys.executable,'-c',script],cwd=G.BASE/'df03-collector'))
def fixture():
    supervisor,source=P.fixture();runtime=M.P.capture(supervisor,'new','time',source)
    old=copy.deepcopy(template());config=old['config'];channel=old['channel'];t=old['time_context']
    domain=dict(authority_service_id=source['service_id'],database_instance_id=source['database_instance_id'],provider_id='time.member',
        provider_boot_id='boot.time',runtime_binding_ref=M.P.reference(runtime),clock_generation='1',**M.P.S.domain(runtime['descriptor']))
    manifest=runtime['intent']['artifact_manifest_ref'];artifact=dict(id=manifest['manifest_id'],revision=manifest['revision'],digest=manifest['digest'])
    config['profile']['collector_artifact_ref']=artifact;M.T.seal(config['profile'],'profile_digest')
    config['approval'].update(authority_service_id=source['service_id'],profile_ref=M.cref(config['profile'],'profile'));M.T.seal(config['approval'],'approval_digest')
    binding=config['binding'];binding.update(domain=domain,profile_ref=M.cref(config['profile'],'profile'),approval_ref=M.cref(config['approval'],'approval'))
    bootstrap=M.receipt_ref(runtime);channel.update(channel_id='channel.time',domain=domain,bootstrap_receipt_ref=bootstrap)
    config.update(bootstrap_receipt_ref=bootstrap,collector_artifact_ref=artifact);M.T.seal(config,'config_digest')
    state=copy.deepcopy(t['state']);state.update(revision='1',status='collecting',binding=binding,current_anchor_ref=None,invalidation_ref=None);M.T.seal(state,'state_digest')
    db=sqlite3.connect(':memory:',isolation_level=None);M.install(db)
    db.execute(*M.insert('ts_scope',1,source['service_id'],source['database_instance_id'],'reference-time-storage/0.1.0-draft.1'))
    db.execute(*M.insert('tc_policy',1,1,1,100000,8,1,64,M.raw(config['limits'])))
    db.execute(*M.insert('tc_source','source.slot',M.T.digest(config['source']),M.raw(config['source'])))
    args=(supervisor,'new','time',source,channel,config,state,'source.slot','binding.initial','bootstrap.initial',dict(id='synthetic.interval',revision='1',digest=M.T.digest('interval')))
    return db,args
def invalidation(adoption):
    ref=lambda s:dict(id=s,revision='1',digest=M.T.digest(s))
    return M.T.seal(dict(invalidation_id='provider.invalidate',revision='1',old_binding=adoption['configuration']['binding'],next_time_generation='2',
        cause_ref=ref('synthetic.cause'),deny_new_utc_permits=True,protection_operation_ref=ref('synthetic.protection')),'invalidation_digest')
def snapshot(db):return {n:db.execute('SELECT * FROM "'+n+'" ORDER BY rowid').fetchall() for n, in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")}
def inputs():
    files=list(P.inputs())+[G.HERE/n for n in ('build_provider_adoption.py','adoption.schema.json','storage.sql','adoption_model.py','check_adoption.py','README.md')]
    files += [G.BASE/'df03-collector'/n for n in ('collector-storage-v02.sql','channel-v02.schema.json','check_contracts.py','reference_model.py','build_contracts.py')]
    files += [G.BASE/'df03-service'/n for n in ('gate_snapshot_source_model.py','reference_model.py')]+[G.BASE/'df03-reference'/n for n in ('reference_model.py','check_contracts.py','build_contracts.py')]
    return list(dict.fromkeys(files))
def run():
    checks=[];connections=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fresh():
        db,args=fixture();connections.extend((db,args[0]));return db,args
    def denied(name,fn):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error,RuntimeError):check(name)
        else:raise AssertionError('应拒绝:'+name)
    def current(db):
        db.execute('BEGIN IMMEDIATE')
        try:return M.current(db)
        finally:db.rollback()
    def historical(db):
        db.execute('BEGIN')
        try:return M.read(db,'channel.time')
        finally:db.rollback()
    def revoke(db,value,**fault):return M.revoke(db,'channel.time',invalidation(value),'invalidate.commit','binding.next','stop.intent',**fault)
    try:
        check('生成Schema逐字节',(G.HERE/'adoption.schema.json').read_bytes()==G.encoded())
        db,args=fresh();value,writes=M.adopt(db,*args);tables=len(snapshot(db));check('完整采用十步',len(writes)==10)
        check('同库原件来源',current(db)[0]==value and current(db)[1]['status']=='collecting')
        check('无UTC锚',current(db)[1]['current_anchor_ref'] is None)
        before=snapshot(db);again,empty=M.adopt(db,*args);check('重复采用只查原',again==value and not empty and snapshot(db)==before)
        for pos in (7,8,9,10):
            changed=list(args)
            changed[pos]=dict(changed[pos],id='changed.interval') if pos==10 else 'changed.storage'
            denied('重复采用换持久参数'+str(pos),lambda:M.adopt(db,*changed));check('冲突不改原件'+str(pos),snapshot(db)==before)
        for i in range(len(writes)):
            for mode in ('fail_after','omit'):
                d,a=fresh();before=snapshot(d);denied(f'采用{mode}{i}',lambda:M.adopt(d,*a,**{mode:i}));check(f'采用{mode}{i}全表回滚',snapshot(d)==before)
        for field in ('channel_id','bootstrap_receipt_ref','domain'):
            d,a=fresh();a=list(a);a[4]=copy.deepcopy(a[4])
            if field=='domain':a[4][field]['provider_boot_id']='wrong'
            elif field=='bootstrap_receipt_ref':a[4][field]['id']='wrong'
            else:a[4][field]='wrong'
            before=snapshot(d);denied('采用错通道:'+field,lambda:M.adopt(d,*a));check('错通道无写入:'+field,snapshot(d)==before)
        d,a=fresh();a=list(a);a[5]=copy.deepcopy(a[5]);a[5]['collector_artifact_ref']['id']='wrong';M.T.seal(a[5],'config_digest')
        denied('重算摘要错制品拒绝',lambda:M.adopt(d,*a))
        for table in ('ts_commit','ts_audit','ts_outbox','ts_seal'):
            d,a=fresh();before=snapshot(d)
            class WrongDelivery:
                def __getattr__(self,k):return getattr(d,k)
                def execute(self,sql,parameters=()):
                    if sql.startswith('INSERT INTO '+table+' '):parameters=tuple(parameters[:-1])+(b'{}',)
                    return d.execute(sql,parameters)
            denied('首次写入错交付原件:'+table,lambda:M.adopt(WrongDelivery(),*a));check('错交付原件全表回滚:'+table,snapshot(d)==before)
        d,a=fresh();d.execute('BEGIN');denied('外部事务拒绝',lambda:M.adopt(d,*a));check('外部事务保留',d.in_transaction);d.rollback()
        d,a=fresh();denied('采用提交观察丢失',lambda:M.adopt(d,*a,commit_fault=True));stored=historical(d);check('丢回执后原件仍在',stored==M.adopt(d,*a)[0])
        rev,rwrites=revoke(db,value);check('撤回完整十步',len(rwrites)==10);denied('撤回后当前来源拒绝',lambda:current(db))
        check('撤回后历史原件保持',historical(db)==value);before=snapshot(db);check('撤回只查原',revoke(db,value)[1]==[] and snapshot(db)==before)
        denied('撤回重投换后继Binding',lambda:M.revoke(db,'channel.time',invalidation(value),'invalidate.commit','wrong.binding','stop.intent'))
        for i in range(len(rwrites)):
            for mode in ('fail_after','omit'):
                d,a=fresh();v,_=M.adopt(d,*a);before=snapshot(d);denied(f'撤回{mode}{i}',lambda:revoke(d,v,**{mode:i}));check(f'撤回{mode}{i}全表回滚',snapshot(d)==before)
        d,a=fresh();v,_=M.adopt(d,*a);denied('撤回提交观察丢失',lambda:revoke(d,v,commit_fault=True));denied('丢回执仍已撤回',lambda:current(d));check('撤回丢回执查原',revoke(d,v)[0]==rev)
        denied('旧Binding不能再采样',lambda:db.execute(*M.insert('ts_poll','late','binding.initial','late.correlation',b'{}')))
        d,a=fresh();supervisor=a[0]
        class RetireAfterCapture:
            def __getattr__(self,k):return getattr(supervisor,k)
            def commit(self):
                supervisor.commit()
                supervisor.execute("UPDATE launch_state SET state='retiring' WHERE supervisor_id='new' AND launch_id='time'")
        raced=list(a);raced[0]=RetireAfterCapture();old,_=M.adopt(d,*raced)
        check('监督读取后退役仍能本地提交',supervisor.execute("SELECT state FROM launch_state WHERE supervisor_id='new' AND launch_id='time'").fetchone()[0]=='retiring')
        check('本地current不证明监督活性',current(d)[0]==old)
        denied('后续监督读取拒绝退役成员',lambda:M.P.capture(supervisor,'new','time',a[3]))
        denied('当前读取必须有事务',lambda:M.current(d))
        for table in ('tp_runtime','tp_adoption','tp_revocation'):
            denied(table+'不可删除',lambda table=table:db.execute('DELETE FROM '+table))
        check('所有外键完整',all(not d.execute('PRAGMA foreign_key_check').fetchone() for d in connections))
        return dict(all_passed=True,approved=False,cases_passed=len(checks),checks=checks,controller_tables=tables,
            local_adoption_atomicity_verified=True,local_revocation_atomicity_verified=True,supervisor_race_closed=False,
            supervisor_retirement_interleaving_reproduced=True,approval_authority_verified=False,real_ipc_verified=False,full_open_verified=False,device_tests_executed=0,
            inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()})
    finally:
        for d in connections:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=G.HERE/'adoption-report.json'
    if a.check_report:
        r=json.loads(path.read_bytes());assert r['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};print(json.dumps(dict(bindings_valid=True,inputs=len(r['inputs']),rerun=False)))
    else:
        r=run()
        if a.report:path.write_bytes(M.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
