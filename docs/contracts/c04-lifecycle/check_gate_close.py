"""健康新域出口的关闭日志与完整ACK验收，无认证故障前提。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_domain_protection as T
import gate_close_dispatch_model as D
import gate_close_ack_model as A
Z=T.Z;Y=T.Y;X=T.X;R=T.R;N=T.N;M=T.M;P=T.P;E=T.E;O=T.O;HERE=D.G.HERE;ROOT=T.ROOT
def inputs():return T.inputs()+[HERE/n for n in ('build_gate_close.py','gate-close.schema.json','gate-close.sql','gate-close-journal.sql','gate_close_dispatch_model.py','gate_close_ack_model.py','check_gate_close.py','GATE_CLOSE.md')]
def fixture():
    db,connections,sd,domain,eid,cid=T.T.T.fixture();Y.install(db);Z.install(db)
    for e in ('exit_dev_1','exit_dev_2'):R.adopt(db,e,sd,'old','retirement.complete',domain,'3')
    X.complete(db,eid,'healthy.retired');descriptor=R.read(db,eid)['source_bundle']['evaluator_descriptor'];Z.restart(db,'dev.1','healthy.restart',descriptor,'5',E.ref('synthetic.provider'))
    fresh=T.T.new_exit(db,eid,descriptor);T.Q.install(db);c=dict(exit=fresh,device='dev.1',prefix='healthy.worker')
    def bootstrap():
        for sql,args in O.session(db,c,7):db.execute(sql,tuple('ipc/0.14.0-continuation-draft.1' if v=='ipc/0.13.0-journal-draft.1' else v for v in args))
    N.transaction(db,bootstrap);D.install(db);return db,connections,fresh,'registration.'+fresh
def run():
    checks=[];connections=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def snap(c):return T.T.T.T.T.T.T.V.SC.snapshot(c)
    def fork(c):
        x=sqlite3.connect(':memory:',isolation_level=None);c.backup(x);x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON');connections.append(x);return x
    def denied(n,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error,N.C.I.ClockIngressStop) as error:
            chain=[]
            while error is not None:chain.append(str(error));error=error.__cause__
            if reason:assert any(reason in s for s in chain),(n,chain)
            check(n)
        else:raise AssertionError('应拒绝:'+n)
    def wire(f):b=M.raw(f);return len(b).to_bytes(4,'big')+b
    def end(c,sid):
        body=M.raw(dict(synthetic='end'))
        N.transaction(c,lambda:c.execute(*T.I('ij_end',end_id='healthy.end',session_id=sid,reason='shutdown',cause_frame_id=None,observed_tick=P.u(12),evidence_body=body,audit_body=body)))
    class Omit:
        def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
        def __getattr__(self,k):return getattr(self.c,k)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
            return self.c.execute(sql,args)
    try:
        db,others,eid,cid=fixture();connections.extend(others);base=fork(db);binding=R.runtime(db,eid)[0]['binding']
        check('268表组合',len(snap(db))==268);check('新出口没有认证时钟故障',D.C.I.fault(db,binding) is None)
        before=snap(db);request,qw=D.queue(db,cid,'8');queued=fork(db);check('普通关闭不创建故障保护',snap(db)['authorization_clock_fault']==before['authorization_clock_fault'] and snap(db)['authorization_clock_protection']==before['authorization_clock_protection'])
        check('请求绑定实际注册关闭',request['close_ref']==D.close_ref(db,cid) and request['target']['close_body']['reason']=='synthetic_new_domain')
        original=snap(db);check('重复排队不刷新',D.queue(db,cid,'999')==(request,[]) and snap(db)==original)
        check('唯一入流尝试',D.begin_write(db,cid,'9')=='attempt_recorded');original=snap(db);check('重复入流不重发',D.begin_write(db,cid,'999')=='lookup_only' and snap(db)==original);sent=fork(db)
        sid=request['target']['session_id'];seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        frame=E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','healthy.ack',seq,dict(close_id=cid,closed_device_ids=['dev.1']),request['dispatch_id']);data=wire(frame);observer=E.ref('synthetic.observer')
        ack,aw=A.receive(db,cid,data,'10',observer);check('完整ACK被采用',ack['disposition']=='applied' and A.usable(db,ack['ack_id']));check('读取原件等于写入',A.read(db,cid)[0]==ack and D.read(db,cid)[0]==request)
        original=snap(db);check('重复ACK只查原',A.receive(db,cid,data,'999',observer)==(ack,[]) and snap(db)==original)
        denied('未尝试关闭不能采用ACK',lambda:A.receive(fork(queued),cid,data,'10',observer))
        denied('关闭早于cut拒绝',lambda:D.queue(fork(base),cid,'5'))
        for label,change in [('域',lambda f:f.update(clock_domain_id='clock_'+'a'*64)),('reply',lambda f:f.update(reply_to='wrong')),('设备',lambda f:f['body'].update(closed_device_ids=['dev.2'])),('设备多列',lambda f:f['body'].update(closed_device_ids=['dev.1','dev.2'])),('序号',lambda f:f.update(seq=str(seq+1)))]:
            f=copy.deepcopy(frame);change(f);x=fork(sent);before=snap(x);denied('ACK错绑:'+label,lambda:A.receive(x,cid,wire(f),'10',observer));check('错绑不采用:'+label,snap(x)==before)
        for label,body in [('长度',b'\0\0\0\1'+data[4:]),('非规范',len(data[4:]+b' ').to_bytes(4,'big')+data[4:]+b' ')]:denied('线路拒绝:'+label,lambda body=body:A.receive(fork(sent),cid,body,'10',observer))
        for label,seed,writes,call in [('请求',base,qw,lambda c,**k:D.queue(c,cid,'8',**k)),('ACK',sent,aw,lambda c,**k:A.receive(c,cid,data,'10',observer,**k))]:
            for i in range(len(writes)):
                x=fork(seed);before=snap(x);denied(label+'逐写异常:'+str(i),lambda:call(x,fail_after=i));check(label+'逐写回滚:'+str(i),snap(x)==before)
            for table in writes:
                x=fork(seed);before=snap(x);proxy=Omit(x,table);denied(label+'缺写:'+table,lambda:call(proxy));check(label+'缺写回滚:'+table,proxy.hit>0 and snap(x)==before)
            class CommitFault:
                def __init__(self,c,committed):self.c=c;self.committed=committed
                def __getattr__(self,k):return getattr(self.c,k)
                def commit(self):
                    if self.committed:self.c.commit()
                    raise sqlite3.OperationalError('synthetic_commit_observation')
            for committed in (False,True):
                x=fork(seed);before=snap(x);denied(label+'提交观察故障:'+str(committed),lambda:call(CommitFault(x,committed)))
                if committed:
                    original=snap(x);check(label+'提交后只查原',call(x)[1]==[] and snap(x)==original)
                else:check(label+'提交前完整回滚',snap(x)==before)
        x=fork(sent);end(x,sid);late,_=A.receive(x,cid,data,'13',observer);check('结束后迟到ACK只入历史',late['disposition']=='historical' and not A.usable(x,late['ack_id']) and not x.execute('SELECT 1 FROM go_close_ack WHERE close_id=?',(cid,)).fetchone())
        x=fork(db);end(x,sid);check('结束使已采用ACK失效',not A.usable(x,ack['ack_id']));check('结束不删除ACK历史',A.read(x,cid)[0]==ack)
        x=fork(db);proof=M.raw(dict(synthetic='withdraw'));N.transaction(x,lambda:x.execute(*T.I('go_revocation',kind='close_ack',object_id=ack['ack_id'],reason_body=proof,audit_body=proof)));check('撤回关闭证据取消资格',not A.usable(x,ack['ack_id']))
        denied('不能与旧认证关闭重复排队',lambda:D.queue(db,M.E.one(db,"SELECT close_id FROM authorization_close_dispatch LIMIT 1")['close_id'],'300'),'duplicate_close_protocol')
        check('未创建准备核销或恢复许可',db.execute('SELECT count(*) FROM pd_close_completion').fetchone()[0]==base.execute('SELECT count(*) FROM pd_close_completion').fetchone()[0] and not db.execute('SELECT 1 FROM ci_issue').fetchone())
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'gate-close-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=268,healthy_close_ack_verified=True,preparation_closure_integration_verified=False,full_reopen_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(M.raw(v))
        print(json.dumps({k:x for k,x in v.items() if k not in ('checks','inputs')}))
