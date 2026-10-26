"""关闭ACK持久原件与当前资格实验；时间、observer及设备响应为合成输入。"""
import argparse,copy,hashlib,json,re,sqlite3
from pathlib import Path
from unittest.mock import patch
import check_authorization_close_dispatch as Q
import authorization_close_ack_model as A
T=Q.T;D=A.D;P=A.P;M=A.M;E=A.E;G=A.G;HERE=G.HERE;ROOT=HERE.parents[2]
def inputs():return list(dict.fromkeys(Q.inputs()+G.SOURCES+[HERE/n for n in ('authorization-close-ack-journal.sql','authorization-close-ack.schema.json','authorization_close_ack_model.py','check_authorization_close_ack.py','AUTHORIZATION_CLOSE_ACK.md')]))
def wire(frame):raw=M.raw(frame);return len(raw).to_bytes(4,'big')+raw
def run():
    checks=[];connections=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def snapshot(c):return T.T.T.V.SC.snapshot(c)
    def fork(c):
        x=sqlite3.connect(':memory:',isolation_level=None);c.backup(x);x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON');connections.append(x);return x
    def denied(name,fn):
        try:fn()
        except (D.C.I.ClockIngressStop,sqlite3.IntegrityError,ValueError):check(name)
        else:raise AssertionError('应拒绝:'+name)
    try:
        db,other,command,auth,pid,provider,response=T.fixture();connections.extend([db]+other);D.install(db);A.install(db)
        binding=provider['binding'];device=binding['device_id'];eid=binding['writer_exit_id'];observer=T.T.V.ref('synthetic.close.observer')
        fault=D.C.I.ingest(db,binding,b'{');plan=D.C.prepare(db,binding,fault['fault_ref']);state=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(device,))
        timing=dict(device_id=device,clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns='200',source_ref=T.T.V.ref('synthetic.ack.tick'))
        protection,_=P.apply(db,D.C.pref(plan),[timing]);pr=D.pref(protection);cid=protection['exits'][0]['close_id'];dispatch,_=D.queue(db,pr,cid,'201');unattempted=fork(db)
        D.begin_write(db,cid,'202');base=fork(db);sid=dispatch['target']['session_id']
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        frame=E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','synthetic.close.ack',seq,dict(close_id=cid,closed_device_ids=[device]),dispatch['dispatch_id']);data=wire(frame)
        value,writes=A.receive(db,cid,data,'203',observer);aid=value['ack_id']
        check('255表完整候选',len(snapshot(db))==255)
        check('当前ACK与日志及采用原件同批保存',writes==['ij_frame','authorization_close_ack','go_close_ack','ij_commit'] and A.usable(db,aid))
        check('非空prepare仍待核销',db.execute('SELECT count(*) FROM pd_member WHERE cut_id=(SELECT prepare_cut_id FROM go_close WHERE close_id=?)',(cid,)).fetchone()[0]==1 and not db.execute('SELECT 1 FROM pd_close_completion WHERE close_id=?',(cid,)).fetchone())
        check('ACK不恢复控制或转交持有人',tuple(db.execute('SELECT gate_state,holder_id FROM ct_current_state WHERE device_id=?',(device,)).fetchone())==tuple(base.execute('SELECT gate_state,holder_id FROM ct_current_state WHERE device_id=?',(device,)).fetchone()))
        old=snapshot(db);check('重复仅查原不刷新接收时刻',A.receive(db,cid,data,'999',observer)==(value,[]) and snapshot(db)==old)
        denied('未尝试发送不接受ACK',lambda:A.receive(unattempted,cid,data,'203',observer))
        denied('ACK早于原入流尝试',lambda:A.receive(fork(base),cid,data,'201',observer))
        for name,mutate in [('会话',lambda f:f.update(ipc_session_id='wrong.session')),('reply',lambda f:f.update(reply_to='wrong.reply')),('空覆盖',lambda f:f['body'].update(closed_device_ids=[])),('额外覆盖',lambda f:f['body'].update(closed_device_ids=[device,'other.device'])),('close',lambda f:f['body'].update(close_id='wrong.close')),('序号跳跃',lambda f:f.update(seq=str(seq+1))),('设备字段',lambda f:f.update(device_id=device))]:
            f=copy.deepcopy(frame);mutate(f);x=fork(base);old=snapshot(x)
            denied('拒绝错配:'+name,lambda:A.receive(x,cid,wire(f),'203',observer));check('错配无半边日志:'+name,snapshot(x)==old)
        for name,raw in [('长度',b'\0\0\0\1'+data[4:]),('重复键',data[4:-1]+b',"seq":"2"}'),('非规范空格',b' '+data[4:])]:
            raw=raw if name=='长度' else len(raw).to_bytes(4,'big')+raw
            denied('线路格式拒绝:'+name,lambda raw=raw:A.receive(fork(base),cid,raw,'203',observer))
        changed=copy.deepcopy(frame);changed['message_id']='another.ack'
        denied('已保存close不能换message重放',lambda:A.receive(db,cid,wire(changed),'204',observer))
        denied('重复ACK不能换观察来源',lambda:A.receive(db,cid,data,'204',T.T.V.ref('different.observer')))
        for i in range(len(writes)):
            x=fork(base);old=snapshot(x);denied('逐写回滚:'+str(i),lambda:A.receive(x,cid,data,'203',observer,fail_after=i));check('逐写全库回滚:'+str(i),snapshot(x)==old)
        class Omit:
            def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
            def __getattr__(self,key):return getattr(self.c,key)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
                return self.c.execute(sql,args)
        for table in writes:
            x=fork(base);old=snapshot(x);proxy=Omit(x,table)
            denied('缺写拒绝:'+table,lambda:A.receive(proxy,cid,data,'203',observer));check('省略命中且全库回滚:'+table,proxy.hit>0 and snapshot(x)==old)
        x=fork(base);insert=A.I
        def missing_adoption(table,**row):
            if table=='authorization_close_ack':row['adopted_ack_id']=None
            return insert(table,**row)
        with patch.object(A,'I',side_effect=missing_adoption):denied('applied采用ID不允许SQL空值绕过',lambda:A.receive(x,cid,data,'203',observer))
        class CommitFault:
            def __init__(self,c,committed):self.c=c;self.committed=committed
            def __getattr__(self,key):return getattr(self.c,key)
            def commit(self):
                if self.committed:self.c.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation_failure')
        for committed in (False,True):
            x=fork(base);old=snapshot(x);denied('提交观察失败:'+str(committed),lambda:A.receive(CommitFault(x,committed),cid,data,'203',observer))
            if committed:check('已提交未知结果只查原',A.receive(x,cid,data,'999',observer)==(value,[]))
            else:check('未提交故障全库回滚',snapshot(x)==old)
        def end(c):T.tx(c,lambda:c.execute(*D.I('ij_end',**Q.J.end(session=sid,tick=210)[1])))
        x=fork(base);end(x);history,hw=A.receive(x,cid,data,'211',observer)
        check('结束后的ACK只保存历史',history['disposition']=='historical' and not A.usable(x,history['ack_id']) and 'go_close_ack' not in hw)
        adopted=M.E.one(db,'SELECT * FROM go_close_ack WHERE ack_id=?',(aid,))
        denied('历史ACK不能直接补造采用',lambda:T.tx(x,lambda:x.execute(*D.I('go_close_ack',**adopted))))
        x=fork(db);end(x);check('先采用后结束立即失去资格',not A.usable(x,aid))
        check('失效不改写历史回执',A.receive(x,cid,data,'999',observer)==(value,[]))
        x=fork(db);T.tx(x,lambda:x.execute(*D.I('go_revocation',kind='close_ack',object_id=aid,reason_body=M.raw({'reason':'synthetic_revocation'}),audit_body=M.raw({'audit':True}))))
        check('关闭证明撤回失去资格',not A.usable(x,aid))
        # 只隔离验证视图的前后态依赖，不假装执行了完整T5恢复事务。
        viewdb=sqlite3.connect(':memory:');connections.append(viewdb)
        viewdb.executescript('''CREATE TABLE authorization_close_dispatch(close_id,frame_id);CREATE TABLE go_latest_close(close_id);
          CREATE TABLE go_close(close_id,protection_change_id);CREATE TABLE ct_current_state(change_id,gate_state);
          CREATE TABLE ij_frame(frame_id,session_id);CREATE TABLE ij_end(session_id);
          CREATE TABLE authorization_close_ack(ack_id,close_id,frame_id,adopted_ack_id,disposition);
          CREATE TABLE ij_commit(frame_id,disposition);CREATE TABLE go_close_ack(ack_id);CREATE TABLE go_revocation(kind,object_id);
          INSERT INTO authorization_close_dispatch VALUES('close','request');INSERT INTO go_latest_close VALUES('close');
          INSERT INTO go_close VALUES('close','protected');INSERT INTO ct_current_state VALUES('protected','protected');
          INSERT INTO ij_frame VALUES('request','session');INSERT INTO authorization_close_ack VALUES('ack','close','reply','ack','applied');
          INSERT INTO ij_commit VALUES('reply','applied');INSERT INTO go_close_ack VALUES('ack');''')
        source=(HERE/'authorization-close-ack.sql').read_text('utf-8')
        for name in ('authorization_close_live_dispatch','authorization_close_accepting_dispatch','authorization_close_usable_ack'):
            definitions=re.findall('CREATE VIEW '+name+r' AS.*?;',source,re.S);assert len(definitions)==1;viewdb.executescript(definitions[0])
        check('隔离视图初始允许采用且证据可用',viewdb.execute('SELECT count(*) FROM authorization_close_accepting_dispatch').fetchone()[0]==1 and A.usable(viewdb,'ack'))
        viewdb.execute("UPDATE ct_current_state SET change_id='ready',gate_state='ready'");viewdb.commit()
        check('隔离视图正常恢复不使原ACK自失效',not viewdb.execute('SELECT 1 FROM authorization_close_accepting_dispatch').fetchone() and A.usable(viewdb,'ack'))
        viewdb.execute("UPDATE go_latest_close SET close_id='new.close'");viewdb.commit();check('隔离视图新关闭使旧证据失效',not A.usable(viewdb,'ack'))
        # 实际已尝试prepare不能借关闭ACK伪造无须核销的空集合或never_attempted证明。
        cut=db.execute('SELECT prepare_cut_id FROM go_close WHERE close_id=?',(cid,)).fetchone()[0]
        def incomplete(c,proof):
            c.execute(*D.I('pd_closure',closure_id='synthetic.closure',cut_id=cut,revision=P.u(1),closure_digest=M.F.digest('closure'),committed_tick=P.u(220),body=M.raw({'synthetic':True})))
            if proof:c.execute(*D.I('pd_coverage',closure_id='synthetic.closure',cut_id=cut,prepare_id=pid,basis='never_attempted',ack_id=None,retirement_exit_id=None,proof_body=M.raw({'synthetic':True})))
            c.execute(*D.I('pd_closure_commit',closure_id='synthetic.closure',audit_body=M.raw({'synthetic':True}),outbox_body=M.raw({'synthetic':True})))
        for proof in (False,True):
            x=fork(db);old=snapshot(x);denied('ACK不能代替完整准备证明:'+str(proof),lambda:T.tx(x,lambda:incomplete(x,proof)));check('无效核销全库回滚:'+str(proof),snapshot(x)==old)
        for statement in ('DELETE FROM authorization_close_ack','UPDATE authorization_close_ack SET digest=digest'):
            denied('ACK原件不可变:'+statement,lambda statement=statement:T.tx(db,lambda:db.execute(statement)))
        check('四个最终签发阻断仍在',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        check('无最终许可及新准备核销',not db.execute('SELECT 1 FROM ci_issue').fetchone() and not db.execute('SELECT 1 FROM pd_close_completion WHERE close_id=?',(cid,)).fetchone())
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'authorization-close-ack-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,candidate_tables=255,cases_passed=len(checks),stored_close_ack_verified=True,current_ack_invalidation_verified=True,
            physical_close_verified=False,observer_authenticity_verified=False,preparation_closure_executed=False,full_p0_reservation_verified=False,ipc_io_executed=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
