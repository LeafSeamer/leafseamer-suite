"""跨域恢复和监督撤回的真实双SQLite连接交错；不执行设备或进程崩溃。"""
import argparse,hashlib,json,sqlite3,tempfile
from pathlib import Path
from unittest.mock import patch
import check_domain_protection as T
Q=T.Q;Y=T.Y;R=T.R;N=T.N;M=T.M;P=T.P;D=T.D;A=T.A;E=T.E;HERE=T.HERE;ROOT=T.ROOT
def inputs():return T.inputs()+[HERE/n for n in ('check_domain_recovery_races.py','DOMAIN_RECOVERY_RACES.md')]
def run():
    checks=[];connections=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def snap(c):return T.T.T.T.T.T.T.V.SC.snapshot(c)
    def denied(name,fn,reason):
        try:fn()
        except (ValueError,sqlite3.Error,N.C.I.ClockIngressStop) as error:
            chain=[]
            while error is not None:chain.append(str(error));error=error.__cause__
            assert any(reason in s for s in chain),(name,chain);check(name)
        else:raise AssertionError('应拒绝:'+name)
    ingest=D.C.I.ingest
    def before_fault(db,binding,data):
        if binding['writer_exit_id']=='domain.new.exit':
            old=M.document(db.execute('SELECT authorization_body FROM ep_request ORDER BY prepare_id LIMIT 1').fetchone()[0])
            provider={k:old[k] for k in ('max_bytes','authorization_snapshot_ref','capability_ref','primitive_plan_ref','transport_profile_ref')}
            provider.update(binding=binding,primitive_id='current.primitive',expires_tick_ns='70',encoding_reservation_ref=E.ref('current.reservation'))
            provider.update({k:True for k in ('authorized','capability_verified','parameters_verified','time_verified','reservation_verified','current_transport_verified')})
            original=snap(db)
            denied('旧命令不能换绑新域构造准备',lambda:E.transaction(db,lambda:E.authorize(db,old['target']['command_ref']['id'],old['target']['proposed_attempt_id'],binding['writer_exit_id'],provider,pid='current.prepare',now=8)),'encoding_origin')
            check('拒绝旧授权后无准备或预留变化',snap(db)==original)
        return ingest(db,binding,data)
    class BeforeCommit:
        def __init__(self,c,fn):self.c=c;self.fn=fn;self.hit=0
        def __getattr__(self,k):return getattr(self.c,k)
        def commit(self):self.hit+=1;self.fn();self.c.commit()
    try:
        with patch.object(D.C.I,'ingest',side_effect=before_fault):db,others,eid,fresh,plan,timings,retired=T.fixture()
        connections.extend(others);protection,_=Q.apply(db,plan,timings,retired);active=protection['active_protection'];cid=active['exits'][0]['close_id']
        D.queue(db,D.pref(active),cid,'11');D.begin_write(db,cid,'12');dispatch,_=D.read(db,cid);binding=R.runtime(db,fresh)[0]['binding'];sid=dispatch['target']['session_id']
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        frame=E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','race.close.ack',seq,dict(close_id=cid,closed_device_ids=['dev.1']),dispatch['dispatch_id']);raw=M.raw(frame)
        A.receive(db,cid,len(raw).to_bytes(4,'big')+raw,'13',E.ref('synthetic.observer'));N.complete(db,cid,'14')
        snapshot=T.T.snapshot(db,'race.probe',fresh,20);snapshot.update(snapshot_id='race.snapshot',sampled_tick=P.u(21),expires_tick=P.u(121),safety_revision=P.u(int(snapshot['safety_revision'])+1))
        selections=[dict(kind='worker_ack',close_id=cid),dict(kind='supervisor_retired',close_id=protection['retired'][0]['close_ref']['id'],completion_id='domain.retired')]
        def recover(c):return Y.complete(c,'race.recovery',snapshot,[],selections,'21',E.ref('synthetic.snapshot'))
        reason=dict(reason='synthetic ordered withdrawal')
        scratch=(ROOT/'logs').resolve();scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='domain-recovery-sqlite-',dir=scratch) as folder:
            folder=Path(folder);assert folder.resolve().parent==scratch and not folder.is_symlink()
            for mode in ('DELETE','WAL'):
                for order in ('withdraw_first','recover_first'):
                    label=mode+':'+order;path=folder/(label.replace(':','-')+'.sqlite');a=sqlite3.connect(path,isolation_level=None,timeout=0);db.backup(a)
                    check(label+':日志模式',a.execute('PRAGMA journal_mode='+mode).fetchone()[0].upper()==mode)
                    b=sqlite3.connect(path,isolation_level=None,timeout=0)
                    try:
                        for c in (a,b):c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON')
                        if order=='withdraw_first':
                            def competing():
                                denied(label+':恢复writer遇锁拒绝',lambda:recover(b),'database is locked')
                                check(label+':未接管锁持有者事务',a.in_transaction and not b.in_transaction)
                                check(label+':撤回提交前读者仍见旧资格',Q.current(b,protection['protection_id']))
                            proxy=BeforeCommit(a,competing);R.revoke(proxy,'exit_dev_2',reason);check(label+':真实撤回提交钩子一次',proxy.hit==1)
                            denied(label+':撤回先提交禁止恢复',lambda:recover(b),'recovery_retired_not_current')
                            check(label+':恢复失败无部分写入',not b.execute("SELECT 1 FROM go_recovery WHERE recovery_id='race.recovery'").fetchone() and not b.execute("SELECT 1 FROM go_snapshot WHERE snapshot_id='race.snapshot'").fetchone())
                        else:
                            def competing():
                                check(label+':未提交恢复对另一连接不可见',not Y.current(b,'race.recovery'))
                                denied(label+':撤回writer遇锁拒绝',lambda:R.revoke(b,'exit_dev_2',reason),'database is locked')
                                check(label+':竞争者未留下事务',a.in_transaction and not b.in_transaction)
                            proxy=BeforeCommit(a,competing);value,usable,writes=recover(proxy);check(label+':恢复先提交曾有效',proxy.hit==1 and usable and Y.current(b,'race.recovery'))
                            R.revoke(b,'exit_dev_2',reason);check(label+':后提交撤回同步取消资格',not Y.current(a,'race.recovery') and not Q.current(a,protection['protection_id']))
                            count=a.total_changes;again=recover(a);check(label+':已失效恢复只查原',again==(value,False,[]) and a.total_changes==count)
                        check(label+':没有最终发送许可',not a.execute('SELECT 1 FROM ci_issue').fetchone())
                        check(label+':外键及事务完整',not a.in_transaction and not b.in_transaction and not a.execute('PRAGMA foreign_key_check').fetchone())
                    finally:a.close();b.close()
                    c=sqlite3.connect(path,isolation_level=None)
                    try:
                        c.execute('PRAGMA foreign_keys=ON');check(label+':重新连接仍失效',not Y.current(c,'race.recovery') and not Q.current(c,protection['protection_id']))
                        if order=='recover_first':check(label+':持久历史仍可核验',Y.read(c,'race.recovery')==value)
                    finally:c.close()
            path=folder/'snapshot-reader.sqlite';a=sqlite3.connect(path,isolation_level=None,timeout=0);db.backup(a);a.execute('PRAGMA journal_mode=WAL');b=sqlite3.connect(path,isolation_level=None,timeout=0)
            try:
                for c in (a,b):c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON')
                recover(a);b.execute('BEGIN');check('WAL读事务固定旧有效视图',Y.current(b,'race.recovery'));R.revoke(a,'exit_dev_2',reason)
                check('旧读快照仍可显示历史有效值',Y.current(b,'race.recovery') and not Y.current(a,'race.recovery'))
                denied('不得在旧读事务内追加恢复',lambda:recover(b),'nested_transaction');check('拒绝不回滚调用者读事务',b.in_transaction);b.rollback()
                check('结束旧读事务后观察失效',not Y.current(b,'race.recovery'))
                check('旧worker禁写墓碑未消失',b.execute('SELECT count(*) FROM rcs_stopped_worker').fetchone()[0]>0)
            finally:a.close();b.close()
        check('临时SQLite目录已清理',not folder.exists())
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'domain-recovery-races-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=266,two_connection_orders_verified=True,journal_modes=['DELETE','WAL'],nonempty_current_domain_preparation_verified=False,process_crash_verified=False,full_reopen_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(M.raw(v))
        print(json.dumps({k:x for k,x in v.items() if k not in ('checks','inputs')}))
