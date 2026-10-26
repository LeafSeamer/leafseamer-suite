"""释放原件和原预留采用实验；不验证真实worker或监督终止。"""
import argparse,copy,hashlib,json,sqlite3
from unittest.mock import patch
import check_authorization_prepare_closure as Q
import authorization_prepare_release_model as R
N=R.N;M=R.M;P=R.P;D=R.D;E=R.E;T=Q.T;A=N.A;HERE=R.HERE;ROOT=HERE.parents[2]
def inputs():return list(dict.fromkeys(Q.inputs()+[R.SCHEMA_PATH]+[HERE/n for n in ('authorization_prepare_release_model.py','check_authorization_prepare_release.py','AUTHORIZATION_PREPARE_RELEASE.md')]))
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
    def written(c,mid,tick):
        length=c.execute('SELECT wire_length FROM ij_frame WHERE frame_id=?',(mid,)).fetchone()[0]
        T.tx(c,lambda:c.execute(*D.I('ij_write_result',frame_id=mid,state='written',completed_tick=P.u(tick),written_bytes=length,end_id=None,result_body=M.raw({'synthetic_written':True}))))
    class Omit:
        def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
        def __getattr__(self,key):return getattr(self.c,key)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
            return self.c.execute(sql,args)
    class CommitFault:
        def __init__(self,c,committed):self.c=c;self.committed=committed
        def __getattr__(self,key):return getattr(self.c,key)
        def commit(self):
            if self.committed:self.c.commit()
            raise sqlite3.OperationalError('synthetic_commit_observation_failure')
    try:
        db,other,command,auth,pid,provider,response=T.fixture();connections.extend([db]+other);D.install(db);A.install(db)
        binding=provider['binding'];device=binding['device_id'];eid=binding['writer_exit_id'];pid2='prepare_unattempted'
        original=M.document(db.execute('SELECT authorization_body FROM ep_request WHERE prepare_id=?',(pid,)).fetchone()[0]);p2=copy.deepcopy(provider);p2['primitive_id']='second.primitive';p2['encoding_reservation_ref']=E.ref('second.reservation')
        E.transaction(db,lambda:E.authorize(db,command,original['target']['proposed_attempt_id'],eid,p2,pid=pid2,now=33))
        fault=D.C.I.ingest(db,binding,b'{');plan=D.C.prepare(db,binding,fault['fault_ref']);state=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(device,))
        timing=dict(device_id=device,clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns='200',source_ref=T.T.V.ref('synthetic.release.tick'))
        protection,_=P.apply(db,D.C.pref(plan),[timing]);cid=protection['exits'][0]['close_id'];dispatch,_=D.queue(db,D.pref(protection),cid,'201');sid=dispatch['target']['session_id']
        D.begin_write(db,cid,'202');written(db,dispatch['dispatch_id'],'202')
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        closeframe=E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','synthetic.close.ack',seq,dict(close_id=cid,closed_device_ids=[device]),dispatch['dispatch_id'])
        closeack,_=A.receive(db,cid,Q.Q.wire(closeframe),'203',T.T.V.ref('synthetic.close.observer'));base=fork(db)
        request,qw=R.queue(db,cid,pid,'204');queued=fork(db);before=snapshot(db)
        check('请求重试查原',R.queue(db,cid,pid,'999')==(request,[]) and snapshot(db)==before)
        check('释放预约不提前回收',db.execute('SELECT count(*) FROM ep_live_reservation').fetchone()[0]==2)
        check('单次入流尝试',R.begin_write(db,cid,pid,'205')=='attempt_recorded');before=snapshot(db)
        check('重复尝试不重新发送',R.begin_write(db,cid,pid,'999')=='lookup_only' and snapshot(db)==before);written(db,request['message_id'],'205');sent=fork(db)
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        body=dict(release_ref=R.rref(request['body']),binding=binding,prepare_id=pid,release_message_id=request['message_id'],release_frame_digest=M.F.digest(request),disposed_tick_ns='206',state='released',encoder_quiescent=True,consumers_quiescent=True,cache_empty=True)
        frame=E.frame(binding,'RELEASE_ENCODING_ACK','synthetic.release.ack',seq,body,request['message_id']);data=Q.Q.wire(frame)
        adoption,aw=R.receive(db,cid,pid,data,'207');released=fork(db)
        check('255表实际组合',len(snapshot(db))==255)
        check('六项采用写集',aw==['ij_frame','er_ack','er_adoption','ep_release','er_ack_commit','ij_commit'])
        check('原预留ID版本摘要及字节精确回收',adoption['encoding_reservation_ref']==original['encoding_reservation_ref'] and adoption['reserved_bytes']==original['max_bytes'] and db.execute('SELECT prepare_id FROM ep_live_reservation').fetchone()[0]==pid2)
        check('完整采用查原',R.read_adoption(db,cid,pid)[0]==adoption)
        before=snapshot(db);check('重复ACK不双重退款',R.receive(db,cid,pid,data,'999')==(adoption,[]) and snapshot(db)==before)
        closure,valid,writes=N.complete(db,cid,'208')
        check('释放与未尝试完整混合核销',valid and {p['prepare_id']:p['basis'] for p in closure['members']}=={pid:'released',pid2:'never_attempted'})
        check('释放证明不要求伪造DENY',not db.execute('SELECT 1 FROM pd_deny_ack').fetchone())
        check('不恢复控制或持有人',tuple(db.execute('SELECT gate_state,holder_id FROM ct_current_state WHERE device_id=?',(device,)).fetchone())==tuple(base.execute('SELECT gate_state,holder_id FROM ct_current_state WHERE device_id=?',(device,)).fetchone()))
        denied('未尝试释放不能收ACK',lambda:R.receive(fork(queued),cid,pid,data,'207'))
        denied('未尝试编码不能发释放',lambda:R.queue(fork(base),cid,pid2,'204'))
        denied('只有释放请求不能核销',lambda:N.complete(fork(queued),cid,'208'))
        denied('核销不得早于释放采用',lambda:N.complete(fork(released),cid,'206'))
        for name,mutate in [('会话',lambda f:f.update(ipc_session_id='wrong')),('运行域',lambda f:f.update(clock_domain_id='wrong')),('准备',lambda f:f['body'].update(prepare_id=pid2)),('请求摘要',lambda f:f['body'].update(release_frame_digest=M.F.digest('wrong'))),('reply',lambda f:f.update(reply_to='wrong')),('早于尝试',lambda f:f['body'].update(disposed_tick_ns='204')),('未来处置',lambda f:f['body'].update(disposed_tick_ns='208')),('乱序',lambda f:f.update(seq=str(seq+1))),('编码未停止',lambda f:f['body'].update(encoder_quiescent=False)),('消费者未停止',lambda f:f['body'].update(consumers_quiescent=False)),('缓存非空',lambda f:f['body'].update(cache_empty=False))]:
            f=copy.deepcopy(frame);mutate(f);x=fork(sent);before=snapshot(x)
            denied('ACK拒绝:'+name,lambda:R.receive(x,cid,pid,Q.Q.wire(f),'207'));check('拒绝无退款:'+name,snapshot(x)==before)
        for name,wire in [('长度',b'\0\0\0\1'+data[4:]),('非规范',b' '+data[4:]),('重复键',data[4:-1]+b',"seq":"2"}')]:
            wire=wire if name=='长度' else len(wire).to_bytes(4,'big')+wire
            denied('线路拒绝:'+name,lambda:R.receive(fork(sent),cid,pid,wire,'207'))
        f=copy.deepcopy(frame);f['message_id']='replacement';denied('重复ACK不可换原件',lambda:R.receive(db,cid,pid,Q.Q.wire(f),'209'))
        for stage,source,rows,call in [('释放预约',base,qw,lambda c,**k:R.queue(c,cid,pid,'204',**k)),('释放采用',sent,aw,lambda c,**k:R.receive(c,cid,pid,data,'207',**k)),('释放核销',released,writes,lambda c,**k:N.complete(c,cid,'208',**k))]:
            for i in range(len(rows)):
                x=fork(source);before=snapshot(x);denied(stage+'写后异常:'+str(i),lambda:call(x,fail_after=i));check(stage+'异常回滚:'+str(i),snapshot(x)==before)
            for table in dict.fromkeys(rows):
                x=fork(source);before=snapshot(x);proxy=Omit(x,table);denied(stage+'缺写:'+table,lambda:call(proxy));check(stage+'缺写命中且回滚:'+table,proxy.hit>0 and snapshot(x)==before)
            for committed in (False,True):
                x=fork(source);before=snapshot(x);denied(stage+'提交观察故障:'+str(committed),lambda:call(CommitFault(x,committed)))
                if committed:
                    stable=snapshot(x);check(stage+'已提交仅查原',call(x)[-1]==[] and snapshot(x)==stable)
                else:check(stage+'未提交全回滚',snapshot(x)==before)
        insert=N.I
        for name,field,value in [('字节','reserved_bytes',1),('预留','reservation_id','wrong.reservation')]:
            def wrong(table,**row):
                if table=='er_adoption':row[field]=value
                return insert(table,**row)
            x=fork(sent);before=snapshot(x)
            with patch.object(N,'I',side_effect=wrong):denied('退款错配:'+name,lambda:R.receive(x,cid,pid,data,'207'))
            check('错配不回收:'+name,snapshot(x)==before)
        def end(c):T.tx(c,lambda:c.execute(*D.I('ij_end',**Q.Q.Q.J.end(session=sid,tick=210)[1])))
        x=fork(sent);end(x);before=snapshot(x);denied('结束后不得新采用释放',lambda:R.receive(x,cid,pid,data,'211'));check('结束后无退款',snapshot(x)==before)
        x=fork(db);end(x);before=snapshot(x)
        check('已采用释放保留历史且不重复回收',R.receive(x,cid,pid,data,'999')==(adoption,[]) and snapshot(x)==before)
        check('会话结束不复活关闭完成',not N.current(x,cid) and N.complete(x,cid,'999')==(closure,False,[]))
        # 旧SQL允许不透明监督BODY，但它不能单独充当本参考路径的完整退役证据。
        x=fork(base);T.tx(x,lambda:x.execute(*D.I('ce_retirement',exit_id=eid,supervisor_evidence_body=M.raw({'synthetic':True}))))
        denied('退役出口不得新增释放请求',lambda:R.queue(x,cid,pid,'204'));denied('仅退役占位不能核销',lambda:N.complete(x,cid,'208'))
        check('未签发最终许可',not db.execute('SELECT 1 FROM ci_issue').fetchone())
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'authorization-prepare-release-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,candidate_tables=255,cases_passed=len(checks),release_adoption_and_closure_verified=True,refund_binding_verified=True,
            retirement_provider_verified=False,physical_disposal_verified=False,full_p0_reservation_verified=False,ipc_io_executed=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
