"""健康恢复后的完整换闸屏障验收，不执行真实IPC或OPEN。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_close_evidence as H
import typed_gate_fence_model as F
T=H.T;D=T.D;A=T.A;N=T.N;Y=T.Y;R=T.R;M=T.M;P=T.P;E=T.E;I=F.I;HERE=T.HERE;ROOT=T.ROOT;snapshot=H.snapshot
def inputs():return H.inputs()+[HERE/n for n in ('build_typed_gate_fence.py','typed-gate-fence.schema.json','typed-gate-fence.sql','typed_gate_fence_model.py','check_typed_gate_fence.py','TYPED_GATE_FENCE.md')]
def fixture():
    db,connections,eid,cid=T.fixture();request,_=D.queue(db,cid,'8');D.begin_write(db,cid,'9');binding=R.runtime(db,eid)[0]['binding'];sid=request['target']['session_id']
    original=D.read(db,cid)[1];proof=M.raw(dict(synthetic='full_write_observation'))
    N.transaction(db,lambda:db.execute(*I('ij_write_result',frame_id=original['frame_id'],state='written',completed_tick=P.u(9),written_bytes=original['wire_length'],end_id=None,result_body=proof)))
    frame=E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','fence.close.ack',F.seq(db,sid,'w2c'),dict(close_id=cid,closed_device_ids=['dev.1']),request['dispatch_id']);b=M.raw(frame)
    ack,_=A.receive(db,cid,len(b).to_bytes(4,'big')+b,'10',E.ref('synthetic.observer'));N.complete(db,cid,'11')
    probe=T.T.T.snapshot(db,'fence.probe',eid,20);s=dict(probe,snapshot_id='fence.recovery.snapshot',sampled_tick=P.u(21),expires_tick=P.u(121),safety_revision=P.u(int(probe['safety_revision'])+1))
    choices=[dict(kind='worker_ack',close_id=c) if e==eid else dict(kind='supervisor_retired',close_id=c,completion_id='healthy.retired') for c,e in db.execute("SELECT close_id,exit_id FROM go_latest_close WHERE device_id='dev.1' ORDER BY close_id")]
    Y.complete(db,'fence.recovery',s,[],choices,'21',E.ref('synthetic.snapshot.provider'));F.install(db)
    return db,connections,eid,cid,ack,sid
def run():
    checks=[];connections=[]
    def check(name,v=True):assert v,name;checks.append(dict(name=name,passed=True))
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
    def wire(f):b=M.raw(f);return len(b).to_bytes(4,'big')+b
    class Omit:
        def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
        def __getattr__(self,k):return getattr(self.c,k)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
            return self.c.execute(sql,args)
    try:
        db,others,eid,cid,closeack,sid=fixture();connections.extend(others);base=fork(db);rid='healthy.fence';token='healthy.fence.token';observer=E.ref('synthetic.fence.observer')
        def queue(c,**kw):return F.queue(c,cid,rid,token,'22','30','100',**kw)
        request,qwrites=queue(db);queued=fork(db);check('269表完整请求',len(snapshot(db))==269 and request['close_ack_ref']==M.reference(closeack,'ack_id','ack_digest'))
        rows=[('ij_frame',M.E.one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(rid+'.frame',))),('gf_request',M.E.one(db,'SELECT * FROM gf_request WHERE request_id=?',(rid,))),('tf_origin',M.E.one(db,'SELECT * FROM tf_origin WHERE request_id=?',(rid,))),('ij_commit',M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(rid+'.frame',)))]
        for omitted in ('tf_origin','ij_commit'):
            c=fork(base);before=snapshot(c)
            def raw_write():
                for table,row in rows:
                    if table!=omitted:c.execute(*I(table,**row))
            denied('原始事务缺写拒绝提交:'+omitted,lambda:N.transaction(c,raw_write),'FOREIGN KEY constraint failed');check('原始事务缺写完整回滚:'+omitted,snapshot(c)==before)
        c=fork(base);before=snapshot(c)
        def untyped():
            c.execute(*I(rows[0][0],**rows[0][1]));c.execute(*I('gf_request',**dict(rows[1][1],original_id=None)))
        denied('安装后不接受占位请求',lambda:N.transaction(c,untyped),'typed_fence_origin_required');check('占位请求回滚',snapshot(c)==before)
        for label,expires,lease in [('选择等于到期','22','100'),('到期超过租约','101','100')]:
            c=fork(base);before=snapshot(c);denied(label,lambda:F.queue(c,cid,rid,token,'22',expires,lease));check(label+'无部分写',snapshot(c)==before)
        check('请求完整查原',N.transaction(db,lambda:F.read_request(db,rid)[0])==request)
        before=snapshot(db);check('重复请求仅查原',F.queue(db,cid,rid,token,'999','30','100')==(request,[]) and snapshot(db)==before)
        denied('同请求更换token拒绝',lambda:F.queue(fork(db),cid,rid,'different','22','30','100'),'typed_fence_replay_conflict')
        check('唯一入流尝试',F.begin_write(db,rid,'23')=='attempt_recorded');before=snapshot(db);check('重复入流只查原',F.begin_write(db,rid,'999')=='lookup_only' and snapshot(db)==before);sent=fork(db)
        body=dict(request_id=rid,request_digest=request['request_digest'],binding=request['binding'],gate_revision=request['target_gate_revision'],gate_token=token,effective_tick_ns='23',state='fenced')
        frame=E.frame(request['binding'],'GATE_FENCE_ACK','healthy.fence.response',F.seq(db,sid,'w2c'),body,rid+'.frame');data=wire(frame)
        def receive(c,**kw):return F.receive(c,rid,data,'24',observer,**kw)
        ack,awrites=receive(db);received=fork(db);gate,valid,gwrites=F.adopt(db,rid,'25');check('采用完整fenced原件',valid and gate['phase']=='fenced' and N.transaction(db,lambda:F.read_gate(db,rid))==gate)
        before=snapshot(db);check('ACK重试不刷新',F.receive(db,rid,data,'999',observer)==(ack,[]) and snapshot(db)==before);check('采用重试不续租',F.adopt(db,rid,'999')==(gate,True,[]) and snapshot(db)==before)
        denied('未尝试不能接收ACK',lambda:receive(fork(queued)),'journal_reply_binding')
        denied('入流到期等号拒绝',lambda:F.begin_write(fork(queued),rid,'30'),'journal_send_not_current')
        denied('采用到期等号拒绝',lambda:F.adopt(fork(received),rid,'30'),'typed_fence_not_current')
        denied('采用早于接收拒绝',lambda:F.adopt(fork(received),rid,'23'),'gate_fence_commit')
        for label,change in [('reply',lambda f:f.update(reply_to='wrong')),('域',lambda f:f.update(clock_domain_id='clock_'+'a'*64)),('token',lambda f:f['body'].update(gate_token='wrong')),('摘要',lambda f:f['body'].update(request_digest='sha256:'+'0'*64)),('修订',lambda f:f['body'].update(gate_revision='2')),('绑定',lambda f:f['body']['binding'].update(writer_exit_id='wrong')),('时刻',lambda f:f['body'].update(effective_tick_ns='22')),('序号',lambda f:f.update(seq=str(int(f['seq'])+1)))]:
            wrong=copy.deepcopy(frame);change(wrong);c=fork(sent);before=snapshot(c);denied('ACK错绑:'+label,lambda:F.receive(c,rid,wire(wrong),'24',observer));check('错绑回滚:'+label,snapshot(c)==before)
        for name,seed,writes,call in [('请求',base,qwrites,queue),('ACK',sent,awrites,receive),('采用',received,gwrites,lambda c,**kw:F.adopt(c,rid,'25',**kw))]:
            for i in range(len(writes)):
                c=fork(seed);before=snapshot(c);denied(name+'逐写异常:'+str(i),lambda:call(c,fail_after=i));check(name+'逐写回滚:'+str(i),snapshot(c)==before)
            for table in writes:
                c=fork(seed);before=snapshot(c);proxy=Omit(c,table);denied(name+'缺写:'+table,lambda:call(proxy));check(name+'缺写回滚:'+table,proxy.hit>0 and snapshot(c)==before)
            class CommitFault:
                def __init__(self,c,committed):self.c=c;self.committed=committed
                def __getattr__(self,k):return getattr(self.c,k)
                def commit(self):
                    if self.committed:self.c.commit()
                    raise sqlite3.OperationalError('synthetic_commit_observation')
            for committed in (False,True):
                c=fork(seed);before=snapshot(c);denied(name+'提交观察故障:'+str(committed),lambda:call(CommitFault(c,committed)))
                if committed:
                    after=snapshot(c);check(name+'提交后查原',call(c)[-1]==[] and snapshot(c)==after)
                else:check(name+'提交前回滚',snapshot(c)==before)
            c=fork(seed);c.execute('BEGIN');denied(name+'拒绝外事务',lambda:call(c),'nested_transaction');check(name+'保留外事务',c.in_transaction);c.rollback()
        def revoke(c):
            b=M.raw(dict(synthetic='close_withdrawal'));N.transaction(c,lambda:c.execute(*I('go_revocation',kind='close_ack',object_id=closeack['ack_id'],reason_body=b,audit_body=b)))
        def end(c):
            b=M.raw(dict(synthetic='session_end'));N.transaction(c,lambda:c.execute(*I('ij_end',end_id='fence.end',session_id=sid,reason='shutdown',cause_frame_id=None,observed_tick=P.u(26),evidence_body=b,audit_body=b)))
        for name,change in [('关闭撤回',revoke),('会话结束',end)]:
            c=fork(queued);change(c);before=snapshot(c);denied(name+'阻止入流',lambda:F.begin_write(c,rid,'27'));check(name+'入流拒绝不写入',snapshot(c)==before)
            c=fork(sent);change(c);F.receive(c,rid,data,'27',observer);check(name+'迟到ACK仅历史',N.transaction(c,lambda:F.read_ack(c,rid)[3]['disposition'])=='historical');denied(name+'迟到不采用',lambda:F.adopt(c,rid,'28'),'typed_fence_not_current')
            c=fork(received);change(c);before=snapshot(c);denied(name+'阻止采用',lambda:F.adopt(c,rid,'27'),'typed_fence_not_current');check(name+'采用拒绝无新闸',snapshot(c)==before)
            c=fork(db);change(c);before=snapshot(c);check(name+'资格失效历史保留',not F.current(c,rid) and F.adopt(c,rid,'999')==(gate,False,[]) and snapshot(c)==before)
        c=fork(sent);F.receive(c,rid,data,'30',observer);check('到期ACK仅历史',N.transaction(c,lambda:F.read_ack(c,rid)[3]['disposition'])=='historical')
        c=fork(db);b=M.raw(dict(synthetic='fence_withdrawal'));N.transaction(c,lambda:c.execute(*I('gf_revocation',ack_id=rid+'.ack',reason_body=b,audit_body=b)));check('换闸ACK撤回取消资格',not F.current(c,rid) and N.transaction(c,lambda:F.read_gate(c,rid))==gate)
        check('屏障不改变控制或签发',M.E.one(db,"SELECT * FROM ct_current_state WHERE device_id='dev.1'")['gate_state']=='protected' and not db.execute('SELECT 1 FROM ci_issue').fetchone() and not db.execute('SELECT 1 FROM go_ready WHERE after_gate_id=?',(gate['gate_id'],)).fetchone())
        check('恢复资格仍有效且无新认证故障',Y.current(db,'fence.recovery') and D.C.I.fault(db,request['binding']) is None)
        check('最终发送四阻断保留',db.execute("SELECT count(*) FROM sqlite_schema WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'typed-gate-fence-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=269,healthy_recovery_fence_verified=True,full_open_verified=False,physical_fence_verified=False,current_domain_nonempty_preparation_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(M.raw(v))
        print(json.dumps({k:x for k,x in v.items() if k not in ('checks','inputs')}))
