"""290表恢复时间来源及真实SQLite读快照边界；不发OPEN或操作设备。"""
import argparse,copy,hashlib,json,sqlite3,tempfile
from pathlib import Path
import check_retired_cancel as F
import open_time_source_model as O

N=O.N;M=O.M;T=O.T;S=O.C;I=F.C.I;HERE=O.HERE;ROOT=HERE.parents[2]
TIME=HERE.parent/'df03-service'


def inputs():
    return list(dict.fromkeys(F.inputs()+[HERE/n for n in ('open_time_source_model.py','check_open_time_source.py','OPEN_TIME_SOURCE.md')]
        +[TIME/n for n in ('gate_snapshot_source_model.py','reference_model.py','GATE_SNAPSHOT_SOURCE.md')]
        +[HERE.parent/'df03-reference'/n for n in ('reference_model.py','reference.schema.json')]
        +[HERE.parent/'df03-collector/storage.sql']))


def ref(ident):return dict(id=ident,revision='1',digest=T.T.digest(ident))


def start_time(db,eid):
    """无采样时的完整collecting State；提供者运行Ref显式为合成前提。"""
    binding=O.R.runtime(db,eid)[0]['binding']
    domain=dict(binding['scope'],provider_id='synthetic_time_provider',provider_boot_id='synthetic_time_boot',
        runtime_binding_ref=ref('synthetic_time_runtime'),clock_domain_id=binding['clock_domain_id'],
        descriptor_digest=binding['descriptor_digest'],clock_generation='1')
    b=dict(domain=domain,time_generation='1',**{k:ref('synthetic_time_'+k) for k in ('source_ref','profile_ref','approval_ref','policy_ref')})
    state=T.T.seal(dict(state_id='reference_time',revision='1',binding=b,status='collecting',current_anchor_ref=None,invalidation_ref=None),'state_digest')
    def run():
        F.F.GC.Z.statements(db,(HERE.parent/'df03-collector/storage.sql').read_text('utf-8'))
        body=T.raw(state)
        db.execute('INSERT INTO ts_scope VALUES(1,?,?,?)',(domain['authority_service_id'],domain['database_instance_id'],'reference-time-storage/0.1.0-draft.1'))
        db.execute('INSERT INTO ts_binding VALUES(?,?,?,?)',('time_binding_1',1,'1'.zfill(20),T.raw(b)))
        db.execute('INSERT INTO ts_commit VALUES(?,?,?)',('time_boot','bootstrap',body))
        db.execute('INSERT INTO ts_audit VALUES(?,?)',('time_boot',body))
        db.execute('INSERT INTO ts_outbox VALUES(?,?,?)',('time_boot','notification',body))
        db.execute('INSERT INTO ts_state VALUES(?,?,?,?,?,?,?)',('1'.zfill(20),None,'time_binding_1','collecting',None,'time_boot',body))
        db.execute('INSERT INTO ts_head VALUES(1,?)',('1'.zfill(20),))
        db.execute('INSERT INTO ts_seal VALUES(?,?)',('time_boot',body))
    N.transaction(db,run)
    return domain


def invalidate(db,domain,fail_after=None):
    def run():
        before=T.source(db,'1');binding=copy.deepcopy(before['binding']);binding['time_generation']='2'
        inv=T.T.seal(dict(invalidation_id='time_invalid',revision='1',old_binding=before['binding'],next_time_generation='2',
            cause_ref=ref('synthetic_time_failure'),deny_new_utc_permits=True,protection_operation_ref=ref('synthetic_time_protection')),'invalidation_digest')
        after=T.T.seal(dict(before,revision='2',binding=binding,status='unavailable',invalidation_ref=T.T.object_ref(inv,'invalidation_id','invalidation_digest')),'state_digest')
        body=T.raw(after);steps=[
            ('INSERT INTO ts_binding VALUES(?,?,?,?)',('time_binding_2',1,'2'.zfill(20),T.raw(binding))),
            ('INSERT INTO ts_commit VALUES(?,?,?)',('time_invalid','invalidate',body)),
            ('INSERT INTO ts_audit VALUES(?,?)',('time_invalid',body)),
            ('INSERT INTO ts_outbox VALUES(?,?,?)',('time_invalid','time_fence',body)),
            ('INSERT INTO ts_invalidation VALUES(?,?,?,?,?,?)',('time_invalid','time_binding_1','time_binding_2','time_invalid',T.raw(inv['protection_operation_ref']),T.raw(inv))),
            ('INSERT INTO ts_state VALUES(?,?,?,?,?,?,?)',('2'.zfill(20),'1'.zfill(20),'time_binding_2','unavailable',None,'time_invalid',body)),
            ('UPDATE ts_head SET revision=? WHERE id=1',('2'.zfill(20),)),
            ('INSERT INTO ts_seal VALUES(?,?)',('time_invalid',body))]
        for index,(sql,args) in enumerate(steps):
            db.execute(sql,args)
            if index==fail_after:raise RuntimeError('injected_time_invalidation')
        return T.current(db,domain)
    return N.transaction(db,run)


def fixture(unavailable=False,placeholder=False):
    db,others,v=F.fixture()
    try:
        F.R.capture(db,'cancel','all','all',v['refs'],v['context'])
        domain=start_time(db,v['eid'])
        if unavailable:invalidate(db,domain)
        snapshot=N.transaction(db,lambda:T.current(db,domain))
        S.install(db);S.R.install(db);F.T.U.protection(db,'source.protect',run='unrelated_run')
        S.R.capture(db,'run.full');S.capture(db,'command.full',F.F.DEVICES[0])
        links=dict(F.F.O.LINKS,run_snapshot_ref='run.full',command_snapshot_ref='command.full',time_snapshot_ref='pending.time' if placeholder else snapshot['snapshot_id'])
        S.R.O.recover(db,'full.recovery','full.snapshot',v['eid'],links,'22','100',F.F.O.E.ref('provider.full'),v['selections'])
        F.F.O.fence(db,v['cid'],v['sid'])
        return db,others,domain,snapshot
    except BaseException:
        for c in [db]+others:c.close()
        raise


def run():
    checks=[];connections=[]
    def check(name,v=True):assert v,name;checks.append(dict(name=name,passed=True))
    def fresh(**kw):
        db,others,domain,snapshot=fixture(**kw);connections.extend([db]+others);return db,domain,snapshot
    def clone(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');connections.append(c);return c
    def denied(name,fn,reason):
        try:fn()
        except Exception as error:
            chain=[]
            while error:chain.append(str(error));error=error.__cause__
            assert any(reason in e for e in chain),(name,chain);check(name)
        else:raise AssertionError('未拒绝:'+name)
    def read(db,domain):return N.transaction(db,lambda:O.for_open(db,'full.recovery','full.fence','27',domain))
    try:
        db,domain,snapshot=fresh();seed=F.state(db);sources=read(db,domain)
        check('290表实际组合',len(seed)==290)
        check('非空运行拒绝来源',bool(sources['run_deny_snapshot']['entries']))
        check('非空命令拒绝来源',bool(sources['command_deny_snapshot']['entries']))
        check('时间原件精确进入恢复前态',sources['reference_time_snapshot']==snapshot)
        check('恢复已登记真实时间ID',sources['originals']['resource']['time_snapshot_id']==snapshot['snapshot_id'])
        check('完整worker启动原件参与校验',sources['originals']['worker_runtime']['admission_receipt']['role']=='worker')
        check('完整链仍protected且fenced',sources['control_before']['gate_state']=='protected' and sources['gate_before']['phase']=='fenced')
        check('联合读取无写入',F.state(db)==seed)
        old=clone(db);invalidate(old,domain)
        denied('同库失效使旧恢复时间引用失效',lambda:read(old,domain),'open_time_snapshot_reference')
        check('旧时间原件仍可重建',N.transaction(old,lambda:T.derive(T.source(old,'1')))==snapshot)
        for index in range(8):
            c=clone(db);before=F.state(c)
            denied('失效逐写故障:'+str(index),lambda c=c,index=index:invalidate(c,domain,index),'injected_time_invalidation')
            check('失效全库回滚:'+str(index),F.state(c)==before)
            check('回滚仍使用原来源:'+str(index),read(c,domain)['reference_time_snapshot']==snapshot)
        c,d,s=fresh(placeholder=True)
        denied('占位引用不能被读取器洗白',lambda:read(c,d),'open_time_snapshot_reference')
        c,d,s=fresh(unavailable=True)
        check('不可用快照提供提高的floor',read(c,d)['reference_time_snapshot']['minimum_time_generation']=='2')
        check('无UTC资格不伪造锚点',N.transaction(c,lambda:T.source(c,'2'))['current_anchor_ref'] is None)
        # 同一文件两条真实SQLite连接：旧读事务成功只说明旧快照，不能当最终裁决。
        with tempfile.TemporaryDirectory(prefix='leafseamer-time-source-') as directory:
            path=Path(directory)/'case.sqlite'
            a=sqlite3.connect(path,isolation_level=None);b=None
            try:
                db.backup(a);check('实际WAL模式',a.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal')
                a.execute('PRAGMA foreign_keys=ON');a.execute('PRAGMA recursive_triggers=ON')
                b=sqlite3.connect(path,isolation_level=None,timeout=0);b.execute('PRAGMA foreign_keys=ON');b.execute('PRAGMA recursive_triggers=ON')
                a.execute('BEGIN');check('初始读快照',O.for_open(a,'full.recovery','full.fence','27',domain)['reference_time_snapshot']==snapshot)
                invalidate(b,domain)
                check('旧读事务仍看到旧资格',O.for_open(a,'full.recovery','full.fence','27',domain)['reference_time_snapshot']==snapshot)
                a.rollback()
                denied('最终writer重读拒绝旧引用',lambda:read(a,domain),'open_time_snapshot_reference')
                check('另一连接看到新floor',N.transaction(b,lambda:T.current(b,domain))['minimum_time_generation']=='2')
            finally:
                if b:b.close()
                a.close()
        for c in connections:check('事务结束且外键完整',not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone())
        return dict(all_passed=True,approved=False,cases_passed=len(checks),integrated_controller_tables=290,
            integrated_nonempty_time_sources_verified=True,wal_snapshot_boundary_verified=True,
            full_open_verified=False,provider_authenticity_verified=False,time_protection_atomicity_verified=False,
            device_tests_executed=0,checks=checks,inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()})
    finally:
        for c in connections:c.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');args=p.parse_args();path=HERE/'open-time-source-report.json'
    if args.check_report:
        r=json.loads(path.read_bytes());assert r['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
        print(json.dumps(dict(bindings_valid=True,input_count=len(r['inputs']),rerun=False)))
    else:
        r=run()
        if args.report:path.write_bytes(M.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
