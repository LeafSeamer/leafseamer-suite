"""健康关闭原件贯通准备核销与混合恢复；仅合成离线验收。"""
import argparse,hashlib,json,sqlite3
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import check_gate_close as T
import close_evidence_model as CE
D=T.D;A=T.A;Y=T.Y;X=T.X;R=T.R;N=T.N;M=T.M;P=T.P;E=T.E;HERE=T.HERE;ROOT=T.ROOT

def inputs():return T.inputs()+[HERE/n for n in ('close_evidence_model.py','check_close_evidence.py','CLOSE_EVIDENCE.md')]
def snapshot(db):
    return {t:sorted([tuple(r) for r in db.execute('SELECT * FROM "'+t+'"')],key=repr) for t, in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")}

def run():
    checks=[];connections=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fork(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');connections.append(c);return c
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error,N.C.I.ClockIngressStop) as error:
            chain=[]
            while error is not None:chain.append(str(error));error=error.__cause__
            if reason:assert any(reason in s for s in chain),(name,chain)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    class Omit:
        def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
        def __getattr__(self,k):return getattr(self.c,k)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
            return self.c.execute(sql,args)
    try:
        db,others,eid,cid=T.fixture();connections.extend(others)
        check('无关闭来源不具当前资格',CE.kind(db,cid,required=False) is None and not N.current(db,cid))
        denied('无来源不回退占位ACK',lambda:CE.ack(db,cid),'missing_close_original')
        request,_=D.queue(db,cid,'8');D.begin_write(db,cid,'9');sid=request['target']['session_id'];binding=R.runtime(db,eid)[0]['binding']
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        frame=E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','closure.healthy.ack',seq,dict(close_id=cid,closed_device_ids=['dev.1']),request['dispatch_id']);raw=M.raw(frame)
        ack,_=A.receive(db,cid,len(raw).to_bytes(4,'big')+raw,'10',E.ref('synthetic.observer'));base=fork(db)
        check('普通来源读完整原件',CE.kind(db,cid)=='gate' and CE.dispatch(db,cid)[0]==request and CE.ack(db,cid)[0]==ack)
        check('ACK身份必须绑定同关闭',CE.usable(db,cid,ack['ack_id']) and not CE.usable(db,cid,'another.ack'))
        oldcid=db.execute('SELECT close_id FROM authorization_close_dispatch LIMIT 1').fetchone()[0]
        check('认证来源由持久记录选择',CE.kind(db,oldcid)=='authentication' and CE.dispatch(db,oldcid)==N.A.D.read(db,oldcid))
        denied('核销早于ACK拒绝',lambda:N.complete(fork(base),cid,'9'),'prepare_close_ack_not_current')
        closure,valid,cwrites=N.complete(db,cid,'11');closed=fork(db)
        check('健康关闭完成空cut核销',valid and closure['members']==[] and int(closure['prepare_head'])>0)
        check('旧准备仍在注册表且未冒用',db.execute('SELECT count(*) FROM pd_registration').fetchone()[0]>0 and not db.execute('SELECT 1 FROM pd_member WHERE cut_id=(SELECT prepare_cut_id FROM go_close WHERE close_id=?)',(cid,)).fetchone())
        before=snapshot(db);check('核销重复不刷新时间',N.complete(db,cid,'999')==(closure,True,[]) and snapshot(db)==before)
        probe=T.T.T.snapshot(db,'healthy.probe',eid,20)
        recovery_snapshot=dict(probe,snapshot_id='healthy.recovery.snapshot',sampled_tick=P.u(21),expires_tick=P.u(121),safety_revision=P.u(int(probe['safety_revision'])+1))
        selections=[dict(kind='worker_ack',close_id=c) if e==eid else dict(kind='supervisor_retired',close_id=c,completion_id='healthy.retired') for c,e in db.execute("SELECT close_id,exit_id FROM go_latest_close WHERE device_id='dev.1' ORDER BY close_id")]
        ready=fork(db);provider=E.ref('synthetic.snapshot.provider')
        def recover(c,**kw):return Y.complete(c,'healthy.recovery',recovery_snapshot,[],selections,'21',provider,**kw)
        receipt,valid,rwrites=recover(db)
        check('普通ACK与旧worker退役共同恢复',valid and sorted(t['kind'] for t in receipt['targets'])==['supervisor_retired','worker_ack'])
        check('恢复查原及ACK摘要精确绑定',Y.read(db,'healthy.recovery')==receipt and next(t for t in receipt['targets'] if t['kind']=='worker_ack')['ack_ref']==M.reference(ack,'ack_id','ack_digest'))
        before=snapshot(db);check('重复恢复只查原',recover(db)==(receipt,True,[]) and snapshot(db)==before)
        for label,seed,writes,call in [('核销',base,cwrites,lambda c,**kw:N.complete(c,cid,'11',**kw)),('恢复',ready,rwrites,recover)]:
            for i in range(len(writes)):
                c=fork(seed);before=snapshot(c);denied(label+'逐写故障:'+str(i),lambda:call(c,fail_after=i));check(label+'逐写回滚:'+str(i),snapshot(c)==before)
            for table in writes:
                c=fork(seed);before=snapshot(c);proxy=Omit(c,table);denied(label+'缺写:'+table,lambda:call(proxy));check(label+'缺写回滚:'+table,proxy.hit>0 and snapshot(c)==before)
            class CommitFault:
                def __init__(self,c,committed):self.c=c;self.committed=committed
                def __getattr__(self,k):return getattr(self.c,k)
                def commit(self):
                    if self.committed:self.c.commit()
                    raise sqlite3.OperationalError('synthetic_commit_observation')
            for committed in (False,True):
                c=fork(seed);before=snapshot(c);denied(label+'提交观察故障:'+str(committed),lambda:call(CommitFault(c,committed)))
                if committed:
                    after=snapshot(c);check(label+'提交后重入只查原',call(c)[2]==[] and snapshot(c)==after)
                else:check(label+'提交前故障回滚',snapshot(c)==before)
            c=fork(seed);c.execute('BEGIN');before=snapshot(c);denied(label+'不接管外事务',lambda:call(c),'nested_transaction');check(label+'保留外事务',c.in_transaction and snapshot(c)==before);c.rollback()
        def revoke(c):
            body=M.raw(dict(synthetic='withdraw'))
            N.transaction(c,lambda:c.execute(*T.T.I('go_revocation',kind='close_ack',object_id=ack['ack_id'],reason_body=body,audit_body=body)))
        def end(c):
            body=M.raw(dict(synthetic='session_end'))
            N.transaction(c,lambda:c.execute(*T.T.I('ij_end',end_id='healthy.end',session_id=sid,reason='shutdown',cause_frame_id=None,observed_tick=P.u(22),evidence_body=body,audit_body=body)))
        for name,mutate in [('撤回ACK',revoke),('结束会话',end)]:
            c=fork(base);mutate(c);before=snapshot(c);denied(name+'禁止首次核销',lambda:N.complete(c,cid,'23'),'prepare_close_ack_not_current');check(name+'拒绝无部分写',snapshot(c)==before)
            c=fork(ready);mutate(c);before=snapshot(c);denied(name+'禁止首次恢复',lambda:recover(c),'recovery_ack_not_current');check(name+'恢复拒绝无部分写',snapshot(c)==before)
            c=fork(db);mutate(c);check(name+'同步取消核销与恢复资格',not N.current(c,cid) and not Y.current(c,'healthy.recovery'))
            before=snapshot(c);check(name+'历史查原保留',CE.ack(c,cid)[0]==ack and Y.read(c,'healthy.recovery')==receipt and N.complete(c,cid,'999')==(closure,False,[]) and recover(c)==(receipt,False,[]) and snapshot(c)==before)
        c=fork(db);R.revoke(c,'exit_dev_2',dict(reason='synthetic withdrawal'));check('同worker另一设备撤回阻断恢复',N.current(c,cid) and not Y.current(c,'healthy.recovery') and Y.read(c,'healthy.recovery')==receipt)
        # 只读注入双来源读取结果，模拟损坏目录；不绕过真实SQL互斥写守卫。
        class Ambiguous:
            def execute(self,sql,args=()):
                if sql=='SELECT 1 FROM authorization_close_dispatch WHERE close_id=?' and args==(cid,):return db.execute('SELECT 1')
                return db.execute(sql,args)
        denied('双来源拒绝而非挑选',lambda:CE.kind(Ambiguous(),cid),'ambiguous_close_original')
        with patch.object(N.A,'read',side_effect=AssertionError('不应回退认证路径')):check('普通ACK不调用认证读取器',CE.ack(db,cid)[0]==ack)
        check('恢复仍保持保护且无签发',M.E.one(db,"SELECT * FROM ct_current_state WHERE device_id='dev.1'")['gate_state']=='protected' and not db.execute('SELECT 1 FROM ci_issue').fetchone())
        check('四个最终发送阻断仍在',db.execute("SELECT count(*) FROM sqlite_schema WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        check('没有新认证故障',D.C.I.fault(db,binding) is None)
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'close-evidence-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=268,healthy_close_preparation_recovery_verified=True,current_domain_nonempty_preparation_verified=False,full_reopen_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(M.raw(v))
        print(json.dumps({k:x for k,x in v.items() if k not in ('checks','inputs')}))
