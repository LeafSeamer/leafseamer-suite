"""实际取消写集的拒绝水位验收；磁盘双连接仅限自建临时库，不接入服务或设备。"""
import argparse,hashlib,json,sqlite3,tempfile
from pathlib import Path
import command_deny_model as M
import check_cancel_closure as X
import check_run_snapshot as T
N=M.N;P=M.P;I=X.I;ROOT=T.ROOT;HERE=M.HERE
LOCAL=('command_deny.sql','command_deny_model.py','check_command_deny.py','COMMAND_DENY.md')
def inputs():return list(dict.fromkeys(X.INPUTS+T.inputs()+[HERE/n for n in LOCAL]))

def fresh(path=':memory:',install=True):
    c=sqlite3.connect(path,isolation_level=None,timeout=0);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');c.executescript(X.G.build().decode())
    c.execute("INSERT INTO controller_scope VALUES(1,'controller','database_1','controller-storage/0.1.0-draft.1')")
    c.execute(*X.F.A.namespace());X.F.tx(c,X.F.P.register());X.F.tx(c,X.F.P.change())
    c.execute(*X.F.exit_step());c.execute(*X.F.exit_step('exit.1'));X.F.tx(c,X.V.public(X.C.initial(),1))
    if install:M.install(c)
    return c

def cancel(key='one',cid='cancel'):return X.V.cancel(2,key=key,cid=cid)
def cut(stage='ordinary',cid='cancel'):
    steps=X.cut(stage,members=[],prepares=[])
    steps=X.extra(steps,'cc_cut',cut_id=cid+'.'+stage,cancellation_id=cid,previous_cut_id=cid+'.ordinary' if stage=='all' else None,issued_revision=X.U(0))
    for table in ('cc_target','cc_cut_commit'):steps=X.extra(steps,table,cut_id=cid+'.'+stage)
    return X.extra(steps,'cc_cut_commit',outbox_id=cid+'.'+stage+'.event')

def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def new(**kw):c=fresh(**kw);dbs.append(c);return c
    def clone(c):
        d=sqlite3.connect(':memory:',isolation_level=None);c.backup(d);d.execute('PRAGMA foreign_keys=ON');d.execute('PRAGMA recursive_triggers=ON');dbs.append(d);return d
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,sqlite3.Error) as error:
            messages=[]
            while error:
                assert isinstance(error,(ValueError,RuntimeError,sqlite3.Error)),type(error)
                messages.append(str(error));error=error.__cause__
            if reason:assert any(reason in v for v in messages),(name,messages)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    def view(c,revision=None,device='dev.1'):return N.transaction(c,lambda:M.materialize(c,device,revision))
    def atomic(seed,steps,label):
        for at in range(len(steps)):
            d=clone(seed);before=X.F.snapshot(d)
            def fail():
                for i,step in enumerate(steps):
                    d.execute(*step)
                    if i==at:raise RuntimeError('synthetic_write_failure')
            denied(label+'逐写:'+str(at),lambda:N.transaction(d,fail),'synthetic_write_failure')
            check(label+'全事务回滚:'+str(at),X.F.snapshot(d)==before)
    try:
        c=new();zero=view(c);check('120表组合与空水位',len(X.F.snapshot(c))==120 and zero['snapshot_revision']=='0' and zero['entries']==[])
        denied('外事务拒绝读取',lambda:M.materialize(c,'dev.1'),'command_deny_transaction_required')
        atomic(c,cancel(),'取消受理');X.F.tx(c,cancel());accepted=view(c)
        check('源受理自动登记一次',accepted['snapshot_revision']=='1' and accepted['entries']==[dict(parent_command_id='command.one',cancellation_id='cancel',stage='ordinary',deny_revision='1',cut_id=None,cut_pending=True)])
        denied('未完成cut不被过滤为空',lambda:N.transaction(c,lambda:M.complete_cut_ids(c,'dev.1')),'command_deny_cut_pending')
        atomic(c,cut(),'ordinary切点');X.F.tx(c,cut());ordinary=view(c)
        check('ordinary绑定同一拒绝代次且推进快照',ordinary['snapshot_revision']=='2' and ordinary['entries'][0]['deny_revision']=='1' and ordinary['entries'][0]['cut_id']=='cancel.ordinary' and not ordinary['entries'][0]['cut_pending'])
        atomic(c,cut('all'),'all切点');X.F.tx(c,cut('all'));all_source=view(c)
        check('all推进拒绝代次与水位',all_source['snapshot_revision']=='3' and all_source['entries'][0]['deny_revision']=='2' and all_source['entries'][0]['stage']=='all')
        check('同数量推进使旧水位失效',N.transaction(c,lambda:M.current(c,ordinary)) is False)
        check('受理历史仍完整',view(c,'1')==accepted and view(c,'2')==ordinary and view(c,'0')==zero)
        check('全部cut仍须核验原件',N.transaction(c,lambda:M.complete_cut_ids(c,'dev.1'))==(all_source,['cancel.all']))
        before=X.F.snapshot(c);denied('重复原始提交不重复推进',lambda:X.F.tx(c,[cancel()[-1]]));check('重复提交全库不变',X.F.snapshot(c)==before)
        denied('未来水位拒绝',lambda:view(c,'4'),'command_deny_future')
        wrong=dict(all_source,snapshot_revision='2');denied('修改旧水位不能冒充历史',lambda:N.transaction(c,lambda:M.current(c,wrong)),'command_deny_original')
        for sql in ('DELETE FROM cd_event','UPDATE cd_event SET event_kind=event_kind','INSERT OR REPLACE INTO cd_event SELECT * FROM cd_event'):
            denied('禁止改删替换:'+sql,lambda sql=sql:c.execute(sql))
        # 新命令的取消必须分配新的设备水位，不复用原命令修订或签发水位。
        X.F.tx(c,X.V.public(X.C.initial('aaa'),1,'aaa'));X.F.tx(c,cancel('aaa','cancel.aaa'));mixed=view(c)
        check('按父命令排序完整保留墓碑',[e['parent_command_id'] for e in mixed['entries']]==['command.aaa','command.one'] and mixed['snapshot_revision']=='4')
        check('两命令拒绝修订彼此独立',[e['deny_revision'] for e in mixed['entries']]==['1','2'])
        check('其他设备水位不受影响',view(c,device='device_other')['snapshot_revision']=='0')
        # 第二设备使用新的手动来源；只在首次登记前选择设备身份，不改已存身份。
        steps=X.V.public(X.C.initial('other'),1,'other')
        steps=X.extra(steps,'ce_command',device_id='device_other',origin='manual',prep_key=None,receipt_id=None)
        steps=X.extra(steps,'ca_request_key',device_id='device_other');X.F.tx(c,steps)
        steps=[s for s in cancel('other','cancel.other') if not s[0].startswith('INSERT INTO cv_cancel_target ')]
        X.F.tx(c,steps);check('第二设备独立从一开始',view(c,device='device_other')['snapshot_revision']=='1' and view(c)['snapshot_revision']=='4')
        # 原取消后续状态改变不解除永久拒绝；不需要设备关闭成功才保留墓碑。
        d=new();X.F.tx(d,cancel());before=view(d);X.F.tx(d,X.V.progress(3,2,'unsupported','pending',state_args=dict(phase='queued')))
        check('取消终态不删除拒绝',view(d)==before)
        # 事件写入本身失败时，源提交和其余写集均回滚。
        d=new();d.execute("CREATE TEMP TRIGGER synthetic_fail BEFORE INSERT ON main.cd_event BEGIN SELECT RAISE(ABORT,'synthetic_ledger_failure'); END")
        before=X.F.snapshot(d);denied('拒绝账本失败阻止受理提交',lambda:X.F.tx(d,cancel()),'synthetic_ledger_failure');check('源提交不留半边',X.F.snapshot(d)==before)
        # 读取双向覆盖故障注入只发生在隔离副本，不能成为生产安装/修复路径。
        d=clone(c);d.execute('DROP TRIGGER cd_event_d');d.execute("DELETE FROM cd_event WHERE event_kind='accepted' AND cancellation_id='cancel.aaa'")
        denied('缺事件即使其他水位存在也拒绝',lambda:view(d),'command_deny_coverage')
        d=new(install=False);X.F.tx(d,cancel());before=X.F.snapshot(d);denied('旧取消库禁止猜造事件顺序',lambda:M.install(d));check('安装失败没有新表或残留事务',X.F.snapshot(d)==before and not d.in_transaction)
        d=new(install=False);d.execute('PRAGMA recursive_triggers=OFF');denied('递归触发未启用拒绝安装',lambda:M.install(d),'command_deny_pragmas')
        d=new();d.execute('BEGIN');denied('安装不隐式提交调用方事务',lambda:M.install(d),'command_deny_install_transaction');check('原事务仍在',d.in_transaction);d.rollback()
        # 与SQL完全相同的两段运算单独验证64位以上和耗尽，不伪造历史账本水位。
        expression="SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),(CAST(substr(v,11,10) AS INTEGER)+1)%10000000000) FROM (SELECT ? v)"
        for value in ('00000000009999999999','09223372036854775807','10000000000000000000','99999999999999999998','99999999999999999999'):
            result=d.execute(expression,(value,)).fetchone()[0];check('精确进位:'+value,int(result)==int(value)+1 and (len(result)==20)==(int(value)<10**20-1))
        class CommitFault:
            def __init__(self,db,committed):self.db=db;self.committed=committed
            def __getattr__(self,key):return getattr(self.db,key)
            def commit(self):
                if self.committed:self.db.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation')
        for committed in (False,True):
            d=new();denied('提交观察丢失:'+str(committed),lambda:N.transaction(CommitFault(d,committed),lambda:[d.execute(*s) for s in cancel()]))
            check('观察丢失查原:'+str(committed),view(d)['snapshot_revision']==('1' if committed else '0'))
        capacity=new()
        def populate(start,stop):
            for index in range(start,stop):
                key='capacity_'+str(index).zfill(4)
                for step in X.V.public(X.C.initial(key),1,key)+cancel(key,'cancel.'+key):capacity.execute(*step)
        N.transaction(capacity,lambda:populate(0,4096));check('4096个取消完整保留',len(view(capacity)['entries'])==4096)
        N.transaction(capacity,lambda:populate(4096,4097));check('容量已满仍允许追加保护拒绝',M.head(capacity,'dev.1')=='4097')
        denied('4097完整读取拒绝不截断',lambda:view(capacity),'command_deny_capacity')
        for mode in ('DELETE','WAL'):
            with tempfile.TemporaryDirectory(prefix='leafseamer-command-deny-') as folder:
                path=str(Path(folder)/'case.sqlite');d=fresh(path);peer=sqlite3.connect(path,isolation_level=None,timeout=0)
                try:
                    check(mode+'日志模式',d.execute('PRAGMA journal_mode='+mode).fetchone()[0].upper()==mode)
                    peer.execute('PRAGMA foreign_keys=ON');peer.execute('PRAGMA recursive_triggers=ON');peer.execute('PRAGMA synchronous=FULL');d.execute('PRAGMA synchronous=FULL')
                    d.execute('BEGIN IMMEDIATE')
                    for step in cancel():d.execute(*step)
                    peer.execute('BEGIN');check(mode+'提交前其他连接看不到半边',M.materialize(peer,'dev.1')['snapshot_revision']=='0');peer.rollback()
                    denied(mode+'第二writer遇锁停止',lambda:peer.execute('BEGIN IMMEDIATE'),'locked');d.commit()
                    check(mode+'源与拒绝水位共同可见',view(peer)['snapshot_revision']=='1')
                    if mode=='WAL':
                        peer.execute('BEGIN');old=M.materialize(peer,'dev.1');X.F.tx(d,cut())
                        check('WAL旧读视图不能充当最新发送判据',M.materialize(peer,'dev.1')==old and M.current(peer,old));peer.rollback()
                        check('WAL新事务看到推进并拒绝旧水位',not N.transaction(peer,lambda:M.current(peer,old)))
                finally:peer.close();d.close()
                reopened=sqlite3.connect(path,isolation_level=None)
                try:check(mode+'重开数据库保留源与水位',view(reopened)['snapshot_revision']==('2' if mode=='WAL' else '1'))
                finally:reopened.close()
        d,others,*_=T.integrated_fixture();dbs.extend(others);check('完整恢复夹具无旧取消',d.execute('SELECT count(*) FROM cv_cancel').fetchone()[0]==0);M.install(d)
        check('当前269表恢复链可组合为270表',len(X.F.snapshot(d))==270 and view(d,device=d.execute('SELECT device_id FROM ce_command').fetchone()[0])['entries']==[])
        M.R.install(d);run_original,run_current,_=M.R.capture(d,'run.with.command.frontier')
        check('命令水位与运行快照同时组合为272表',len(X.F.snapshot(d))==272 and run_current and run_original['entries']==[])
        for d in dbs:assert not d.in_transaction and not d.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for d in dbs:d.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'command-deny-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),command_deny_frontier_verified=True,command_snapshot_storage_verified=False,typed_cut_verified=False,full_open_verified=False,actual_process_crash_tested=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.M.raw(v))
        print(json.dumps({k:v for k,v in v.items() if k not in ('checks','inputs')}))
