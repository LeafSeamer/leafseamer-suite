"""临时SQLite库的并发、重开及独立测试writer终止验收，不操作业务库。"""
import argparse,hashlib,json,platform,queue,sqlite3,subprocess,sys,tempfile,threading,time
from contextlib import contextmanager
from pathlib import Path
import check_retired_cancel as T
R=T.R;C=T.C;N=T.N;S=T.S;HERE=T.HERE;ROOT=T.ROOT
LOCAL=('check_retired_cancel_durability.py','RETIRED_CANCEL_DURABILITY.md')
def inputs():return T.inputs()+[HERE/n for n in LOCAL]
def connect(path):
    db=sqlite3.connect(str(path),isolation_level=None,timeout=0)
    try:
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.execute('PRAGMA synchronous=FULL');return db
    except sqlite3.Error as e:
        db.close();raise RuntimeError('test_open_failed:'+str(getattr(e,'sqlite_errorname','unknown'))+':'+str(getattr(e,'sqlite_errorcode','unknown'))) from e
@contextmanager
def temporary(connections):
    with tempfile.TemporaryDirectory(prefix='leafseamer-retired-cancel-') as directory:
        try:yield directory
        finally:
            for db in connections:db.close()
            connections.clear()
def capture(db):return R.capture(db,'cancel','all','all',{'prepare_typed':'healthy.retired'},T.T.context(db,'12'))
def revoke(db):return R.X.R.revoke(db,'exit_dev_1',dict(reason='synthetic_concurrent_withdrawal'))
class Wrapped:
    def __init__(self,db):self.db=db
    def __getattr__(self,k):return getattr(self.db,k)
def worker(path,phase):
    path=Path(path).resolve();assert path.name=='case.sqlite' and (path.parent/'.leafseamer-offline-test').read_text()=='retired-cancel-durability/1'
    db=connect(path)
    def barrier():
        print(json.dumps(dict(barrier=phase,in_transaction=db.in_transaction)),flush=True)
        # 只等待父进程终止这个独立测试writer；没有超时后自动提交的路径。
        sys.stdin.readline();raise RuntimeError('test_writer_barrier_released')
    class Writer(Wrapped):
        def execute(self,sql,args=()):
            result=self.db.execute(sql,args)
            if (phase=='after_member' and sql.startswith('INSERT INTO crp_member ')) or (phase=='after_seal' and sql.startswith('INSERT INTO cc_cut_commit ')):barrier()
            return result
        def commit(self):
            self.db.commit()
            if phase=='after_commit':barrier()
    try:capture(Writer(db))
    finally:db.close()
def terminate_at(path,phase):
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(path),'--phase',phase],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    messages=queue.Queue();reader=threading.Thread(target=lambda:messages.put(child.stdout.readline()),daemon=True);reader.start()
    try:
        line=messages.get(timeout=45)
        if not line:
            _,err=child.communicate(timeout=5);raise AssertionError('test_writer_failed:'+err)
        value=json.loads(line);assert value==dict(barrier=phase,in_transaction=phase!='after_commit'),value
        assert child.poll() is None,'测试writer在终止前必须仍存活'
        child.kill();_,err=child.communicate(timeout=15);assert child.returncode is not None and child.returncode!=0,(child.returncode,err)
        reader.join(timeout=1);return value
    finally:
        if child.poll() is None:child.kill();child.communicate(timeout=15)
        for stream in (child.stdin,child.stdout,child.stderr):
            if stream and not stream.closed:stream.close()
def run():
    checks=[];connections=[];killed=0;reopen_errors=[]
    def check(name,condition=True):assert condition,name;checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,sqlite3.Error) as error:
            chain=[]
            while error:chain.append(str(error));error=error.__cause__
            if reason:assert any(reason in s for s in chain),(name,chain)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    seed,others,v=T.fixture();connections.extend(others);connections.append(seed)
    try:
        with temporary(connections) as directory:
            root=Path(directory)
            def disk(name,mode,source=seed):
                folder=root/name;folder.mkdir();(folder/'.leafseamer-offline-test').write_text('retired-cancel-durability/1');path=folder/'case.sqlite';db=connect(path);source.backup(db)
                actual=db.execute('PRAGMA journal_mode='+mode).fetchone()[0];assert actual.upper()==mode;assert db.execute('PRAGMA synchronous').fetchone()[0]==2
                connections.append(db);return path,db
            for mode in ('DELETE','WAL'):
                prefix=mode+':'
                path,a=disk(mode+'_capture_first',mode);b=connect(path);connections.append(b);before=T.state(a)
                class CaptureFirst(Wrapped):
                    def commit(self):
                        check(prefix+'取消writer持锁',self.db.in_transaction)
                        denied(prefix+'取消提交前撤回writer被排他',lambda:revoke(b),'locked')
                        check(prefix+'其他连接查无未提交all不代表已回滚',b.execute("SELECT count(*) FROM cc_cut WHERE cut_id='all'").fetchone()[0]==0)
                        self.db.commit()
                cut,_=capture(CaptureFirst(a));check(prefix+'取消先提交后其他连接看见完整切点',N.transaction(b,lambda:C.read_cut(b,'all'))==cut)
                revoke(b);check(prefix+'后续撤回保留原切点',N.transaction(a,lambda:C.read_cut(a,'all'))==cut)
                denied(prefix+'后续撤回阻止live核销',lambda:N.transaction(a,lambda:R.read(a,cut,live=True)),'retired_cancel_not_current')
                path,a=disk(mode+'_revoke_first',mode);b=connect(path);connections.append(b)
                class RevokeFirst(Wrapped):
                    def commit(self):
                        check(prefix+'撤回writer持锁',self.db.in_transaction)
                        denied(prefix+'撤回提交前取消writer被排他',lambda:capture(a),'locked')
                        self.db.commit()
                revoke(RevokeFirst(b));before=T.state(a);denied(prefix+'撤回先提交后取消重新读取失败',lambda:capture(a),'retired_cancel_not_current');check(prefix+'失败取消无部分写入',T.state(a)==before)
                for phase in ('after_member','after_seal','after_commit'):
                    path,initial=disk(mode+'_'+phase,mode);before=T.state(initial);initial.close();connections.remove(initial)
                    terminate_at(path,phase);killed+=1
                    try:db=connect(path)
                    except RuntimeError as error:
                        cause=error.__cause__;assert isinstance(cause,sqlite3.Error)
                        reopen_errors.append(dict(journal_mode=mode,phase=phase,error_name=cause.sqlite_errorname,error_code=cause.sqlite_errorcode))
                        checks.append(dict(name=prefix+phase+'首次重开无I/O错误',passed=False))
                        # 仅进一步取证；不把再次打开成功当成首次重开或生产恢复通过。
                        time.sleep(.1);db=connect(path)
                    else:check(prefix+phase+'首次重开无I/O错误')
                    connections.append(db)
                    check(prefix+phase+'终止后数据库结构完整',db.execute('PRAGMA integrity_check').fetchall()==[('ok',)] and not db.execute('PRAGMA foreign_key_check').fetchone())
                    if phase!='after_commit':
                        check(prefix+phase+'未提交写集全部恢复',T.state(db)==before)
                        check(prefix+phase+'恢复后原ID可完整提交',len(capture(db)[1])==8)
                    else:
                        saved=T.state(db);cut=N.transaction(db,lambda:C.read_cut(db,'all'));check(prefix+'提交后终止只能按原ID查原',capture(db)==(cut,[]) and T.state(db)==saved)
                        check(prefix+'提交后终止未丢失拒绝水位',C.D.head(db,'dev_1')=='3')
                    T.recovery(db,v);sources=N.transaction(db,lambda:S.for_open(db,'full.recovery','full.fence','27'))
                    check(prefix+phase+'恢复链仍有非空命令拒绝来源',len(sources['command_deny_snapshot']['entries'])==1 and len(T.state(db))==276)
                    db.close();connections.remove(db);db=connect(path);connections.append(db)
                    check(prefix+phase+'再次重开仍能重建来源',N.transaction(db,lambda:S.for_open(db,'full.recovery','full.fence','27'))['command_deny_snapshot']==sources['command_deny_snapshot'])
                if mode=='WAL':
                    path,a=disk('wal_stale_reader',mode);cut,_=capture(a);T.recovery(a,v);b=connect(path);connections.append(b)
                    b.execute('BEGIN');old=S.for_open(b,'full.recovery','full.fence','27');revoke(a)
                    check('WAL旧读事务仍能看到旧资格',S.for_open(b,'full.recovery','full.fence','27')==old)
                    denied('WAL旧视图不能升级writer',lambda:b.execute('DELETE FROM crp_member WHERE 0'),'locked');b.rollback()
                    denied('WAL新writer必须看到撤回',lambda:N.transaction(b,lambda:S.for_open(b,'full.recovery','full.fence','27')))
            for db in connections:
                if db is seed or db in others:continue
                check('磁盘连接无未决事务:'+str(len(checks)),not db.in_transaction and not db.execute('PRAGMA foreign_key_check').fetchone())
            # Windows删除临时目录前关闭所有磁盘连接。
            for db in list(connections):
                if db is not seed and db not in others:db.close();connections.remove(db)
        return checks,killed,reopen_errors
    finally:
        for db in connections:db.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--phase',choices=['after_member','after_seal','after_commit']);p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    if a.worker:
        assert a.phase;worker(a.worker,a.phase)
    else:
        target=HERE/'retired-cancel-durability-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
        if a.check_report:
            report=json.loads(target.read_bytes());assert report['inputs']==hashes;print(json.dumps(dict(bindings_match=True,report_all_passed=report['all_passed'],matched_bindings=len(hashes))))
        else:
            checks,killed,errors=run();v=dict(all_passed=all(c['passed'] for c in checks),approved=False,cases_passed=sum(c['passed'] for c in checks),cases_failed=sum(not c['passed'] for c in checks),journal_modes=['DELETE','WAL'],synchronous='FULL',python_version=platform.python_version(),sqlite_version=sqlite3.sqlite_version,platform=platform.system(),test_writer_terminations=killed,actual_test_writer_kill_verified=True,immediate_reopen_verified=not errors,reopen_errors=errors,production_service_crash_verified=False,power_failure_tested=False,full_open_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
            if a.report:target.write_bytes(R.raw(v))
            print(json.dumps({k:v for k,v in v.items() if k not in ('checks','inputs')}))
            if not v['all_passed']:raise SystemExit(1)
