"""固定候选Node制品执行完整取消SQL写集；不替代服务writer或监督验收。"""
import argparse,base64,hashlib,json,platform,queue,sqlite3,subprocess,tempfile,threading,time
from contextlib import contextmanager
from pathlib import Path
import check_retired_cancel_durability as T
HERE=T.HERE;ROOT=T.ROOT
def inputs():return T.inputs()+[HERE/n for n in ('node_sqlite_worker.cjs','check_node_sqlite_durability.py','NODE_SQLITE_DURABILITY.md')]
def encoded(v):
    if isinstance(v,bytes):return {'$blob':v.hex()}
    if isinstance(v,int):return {'$integer':str(v)}
    return v
def state(db):return {k:[[encoded(v) for v in row] for row in rows] for k,rows in T.T.state(db).items()}
def normalized(v):return {k:sorted(rows,key=lambda row:json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False)) for k,rows in v.items()}
@contextmanager
def temporary(bridges,connections):
    with tempfile.TemporaryDirectory(prefix='leafseamer-node-sqlite-') as directory:
        try:yield directory
        finally:
            for bridge in bridges:bridge.close()
            bridges.clear()
            for db in connections:db.close()
            connections.clear()
class Bridge:
    def __init__(self,node,package):
        self.child=subprocess.Popen([str(node),str(HERE/'node_sqlite_worker.cjs'),str(package)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.messages=queue.Queue()
        def read():
            for line in self.child.stdout:self.messages.put(line)
            self.messages.put(None)
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
    def request(self,value):
        assert self.child.poll() is None,'测试进程已退出'
        self.child.stdin.write(json.dumps(value)+'\n');self.child.stdin.flush();line=self.messages.get(timeout=45)
        assert line,'测试进程未返回结果';return json.loads(line)
    def kill(self):
        assert self.child.poll() is None;self.child.kill();self.child.wait(timeout=15);assert self.child.returncode!=0
    def close(self):
        if self.child.poll() is None:
            self.child.stdin.close()
            try:self.child.wait(timeout=15)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=15)
        self.reader.join(timeout=1)
        for stream in (self.child.stdin,self.child.stdout,self.child.stderr):
            if not stream.closed:stream.close()
def artifacts(runtime):
    node=runtime/'node-v24.22.0-win-x64/node.exe';package=runtime/'better-sqlite3/package';archive=runtime/'node-v24.22.0-win-x64.zip';tarball=runtime/'better-sqlite3-13.0.3.tgz'
    sums=(runtime/'SHASUMS256.txt').read_text();expected=next(line.split()[0] for line in sums.splitlines() if line.split()[-1]==archive.name)
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
    meta=json.loads((ROOT/'docs/contracts/toolchain/metadata-observation.json').read_bytes());pkg=next(p for p in meta['packages'] if p['name']=='better-sqlite3')
    integrity='sha512-'+base64.b64encode(hashlib.sha512(tarball.read_bytes()).digest()).decode();assert integrity==pkg['distribution_declaration']['integrity']
    import tarfile,zipfile
    with zipfile.ZipFile(archive) as z:assert z.read('node-v24.22.0-win-x64/node.exe')==node.read_bytes()
    with tarfile.open(tarball) as t:
        members=[m for m in t.getmembers() if m.isfile() and (m.name.startswith('package/lib/') or m.name in ('package/package.json','package/prebuilds/win32-x64.node'))]
        for member in members:assert t.extractfile(member).read()==(package/Path(member.name).relative_to('package')).read_bytes()
    files=[node,package/'prebuilds/win32-x64.node',archive,tarball]
    return node,package,dict(node_version='24.22.0',driver_version='13.0.3',node_archive_official_sha256=expected,package_integrity=integrity,checked_runtime_files=len(members)+1,sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},cryptographic_signatures_verified=False)
def run(runtime):
    assert platform.system()=='Windows','此profile仅覆盖Windows'
    node,package,identity=artifacts(runtime);checks=[];results=[];bridges=[];connections=[]
    def check(name,condition=True):checks.append(dict(name=name,passed=bool(condition)))
    try:
        seed,others,v=T.T.fixture();connections.extend(others);connections.append(seed);before=state(seed);statements=[]
        class Record(T.Wrapped):
            def execute(self,sql,args=()):
                result=self.db.execute(sql,args)
                if sql.startswith('INSERT INTO '):statements.append(dict(sql=sql,parameters=[encoded(x) for x in args]))
                return result
        copy=sqlite3.connect(':memory:',isolation_level=None);connections.append(copy);seed.backup(copy);copy.execute('PRAGMA foreign_keys=ON');copy.execute('PRAGMA recursive_triggers=ON')
        _,writes=T.capture(Record(copy));after=state(copy);check('模型完整生成八条取消写入',len(statements)==len(writes)==8)
        inspector=Bridge(node,package);bridges.append(inspector);assert inspector.request(dict(action='ping'))==dict(ok=True)
        with temporary(bridges,connections) as directory:
            for mode in ('DELETE','WAL'):
                for phase in ('after_member','after_seal','after_commit'):
                    name=mode+':'+phase;folder=Path(directory)/(mode+'_'+phase);folder.mkdir();(folder/'.leafseamer-offline-test').write_text('node-sqlite-retired-cancel/1');path=folder/'case.sqlite'
                    disk=sqlite3.connect(path);seed.backup(disk);disk.close()
                    setup=inspector.request(dict(action='setup',path=str(path),mode=mode));assert setup['ok'],setup
                    facts=setup['facts'];check(name+'实际配置',facts['sqlite']['version']=='3.53.4' and facts['pragmas']==dict(journal_mode=mode.lower(),synchronous={'$integer':'2'},foreign_keys={'$integer':'1'},recursive_triggers={'$integer':'1'},busy_timeout={'$integer':'0'},wal_autocheckpoint={'$integer':'1000'},mmap_size={'$integer':'0'}))
                    writer=Bridge(node,package);bridges.append(writer);barrier=writer.request(dict(action='write',path=str(path),phase=phase,statements=statements));assert barrier==dict(ok=True,barrier=phase,in_transaction=phase!='after_commit'),barrier
                    writer.kill();writer.close();bridges.remove(writer);check(name+'屏障确认后真实终止测试进程')
                    opened=inspector.request(dict(action='inspect',path=str(path)));first=dict(ok=opened['ok'],code=opened.get('code'));check(name+'首次重开无I/O错误',opened['ok'])
                    if not opened['ok']:time.sleep(.1);opened=inspector.request(dict(action='inspect',path=str(path)))
                    assert opened['ok'],opened
                    check(name+'重开配置不降级',opened['facts']==facts)
                    check(name+'目标引擎完整性',opened['integrity']==['ok'] and not opened['foreign_keys'])
                    check(name+'目标引擎全表值',normalized(opened['state'])==normalized(after if phase=='after_commit' else before))
                    db=T.connect(path);connections.append(db)
                    if phase=='after_commit':check(name+'参考模型同ID只查原',T.capture(db)[1]==[])
                    else:check(name+'参考模型重新完整提交',len(T.capture(db)[1])==8)
                    T.T.recovery(db,v);sources=T.N.transaction(db,lambda:T.S.for_open(db,'full.recovery','full.fence','27'))
                    check(name+'参考模型276表恢复来源',len(T.T.state(db))==276 and len(sources['command_deny_snapshot']['entries'])==1)
                    db.close();connections.remove(db);results.append(dict(journal_mode=mode,phase=phase,first_reopen=first,facts=facts))
        return dict(all_passed=all(c['passed'] for c in checks),approved=False,cases_passed=sum(c['passed'] for c in checks),cases_failed=sum(not c['passed'] for c in checks),checks=checks,results=results,artifacts=identity,windows_version=platform.version(),python_version=platform.python_version(),reference_sqlite_version=sqlite3.sqlite_version,workload_sha256=hashlib.sha256(T.R.raw(statements)).hexdigest(),snapshot_table_count=len(before),snapshot_before_sha256=hashlib.sha256(T.R.raw(normalized(before))).hexdigest(),snapshot_after_sha256=hashlib.sha256(T.R.raw(normalized(after))).hexdigest(),test_writer_terminations=6,storage_worker_thread_used=True,first_reopen_uses_prestarted_worker=True,actual_service_supervision_verified=False,complete_node_writer_verified=False,linux_verified=False,device_tests_executed=0)
    finally:
        for bridge in bridges:bridge.close()
        for db in connections:db.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path);p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    target=HERE/'node-sqlite-durability-report.json';files=inputs()+[ROOT/'docs/contracts/toolchain/metadata-observation.json'];hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if a.check_report:
        r=json.loads(target.read_bytes());assert r['inputs']==hashes;print(json.dumps(dict(bindings_match=True,report_all_passed=r['all_passed'],matched_bindings=len(hashes))))
    else:
        assert a.runtime;r=run(a.runtime.resolve());r['inputs']=hashes
        if a.report:target.write_bytes(T.R.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs','results')}))
        if not r['all_passed']:raise SystemExit(1)
