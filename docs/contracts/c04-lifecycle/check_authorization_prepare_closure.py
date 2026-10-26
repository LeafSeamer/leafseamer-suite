"""实际准备原件到完整核销的SQLite实验；线路、时钟及设备提供者仍为合成。"""
import argparse,copy,hashlib,json,sqlite3
from unittest.mock import patch
import check_authorization_close_ack as Q
import authorization_prepare_closure_model as N
A=N.A;D=N.D;P=N.P;M=N.M;E=N.E;T=Q.T;HERE=N.HERE;ROOT=HERE.parents[2]
def inputs():return list(dict.fromkeys(Q.inputs()+[N.SCHEMA_PATH,HERE.parent/'c08-controller/encoding-release.schema.json']+[HERE/n for n in ('close_evidence_model.py','authorization_prepare_closure_model.py','authorization_prepare_release_model.py','check_authorization_prepare_closure.py','AUTHORIZATION_PREPARE_CLOSURE.md')]))
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
    class Omit:
        def __init__(self,c,table,pid=None):self.c=c;self.table=table;self.pid=pid;self.hit=0
        def __getattr__(self,key):return getattr(self.c,key)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' (') and (self.pid is None or self.pid in args):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
            return self.c.execute(sql,args)
    class CommitFault:
        def __init__(self,c,committed):self.c=c;self.committed=committed
        def __getattr__(self,key):return getattr(self.c,key)
        def commit(self):
            if self.committed:self.c.commit()
            raise sqlite3.OperationalError('synthetic_commit_observation_failure')
    def written(c,mid,tick):
        length=c.execute('SELECT wire_length FROM ij_frame WHERE frame_id=?',(mid,)).fetchone()[0]
        T.tx(c,lambda:c.execute(*D.I('ij_write_result',frame_id=mid,state='written',completed_tick=P.u(tick),written_bytes=length,end_id=None,result_body=M.raw({'synthetic_written':True}))))
    try:
        db,other,command,auth,pid,provider,response=T.fixture();connections.extend([db]+other);D.install(db);A.install(db)
        binding=provider['binding'];device=binding['device_id'];eid=binding['writer_exit_id'];pid2='prepare_unattempted'
        original=M.document(db.execute('SELECT authorization_body FROM ep_request WHERE prepare_id=?',(pid,)).fetchone()[0]);p2=copy.deepcopy(provider)
        p2['primitive_id']='synthetic_second_primitive';p2['encoding_reservation_ref']=E.ref('synthetic.second.reservation')
        E.transaction(db,lambda:E.authorize(db,command,original['target']['proposed_attempt_id'],eid,p2,pid=pid2,now=33))
        fault=D.C.I.ingest(db,binding,b'{');plan=D.C.prepare(db,binding,fault['fault_ref']);state=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(device,))
        timing=dict(device_id=device,clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns='200',source_ref=T.T.V.ref('synthetic.prepare.tick'))
        protection,_=P.apply(db,D.C.pref(plan),[timing]);cid=protection['exits'][0]['close_id'];dispatch,_=D.queue(db,D.pref(protection),cid,'201');sid=dispatch['target']['session_id']
        D.begin_write(db,cid,'202');written(db,dispatch['dispatch_id'],'202')
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        closeframe=E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','synthetic.close.ack',seq,dict(close_id=cid,closed_device_ids=[device]),dispatch['dispatch_id'])
        closeack,_=A.receive(db,cid,Q.wire(closeframe),'203',T.T.V.ref('synthetic.close.observer'));base=fork(db)
        cut=db.execute('SELECT prepare_cut_id FROM go_close WHERE close_id=?',(cid,)).fetchone()[0]
        check('两个实际准备进入固定cut',db.execute('SELECT count(*) FROM pd_member WHERE cut_id=?',(cut,)).fetchone()[0]==2)
        deny,dw=N.deny(db,cid,pid,'204');queued=fork(db)
        check('DENY原件与日志同事务',dw==['ij_frame','pd_deny_request','ij_commit'] and N.read_request(db,cid,pid)[0]==deny)
        check('DENY引用实际授权及撤回',deny['body']['encoding_authorization_ref']==N.ref(original,'authorization_id','authorization_digest') and deny['body']['revocation_ref']['id']==db.execute('SELECT revocation_id FROM ep_revocation WHERE prepare_id=?',(pid,)).fetchone()[0])
        before=snapshot(db);check('重复DENY仅查原',N.deny(db,cid,pid,'999')==(deny,[]) and snapshot(db)==before)
        check('唯一入流尝试',N.begin_write(db,cid,pid,'205')=='attempt_recorded');before=snapshot(db)
        check('重复入流不重写',N.begin_write(db,cid,pid,'999')=='lookup_only' and snapshot(db)==before);written(db,deny['message_id'],'205');sent=fork(db)
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        body=dict(deny_ref=N.ref(deny['body'],'deny_id','request_digest'),binding=binding,prepare_id=pid,deny_message_id=deny['message_id'],deny_frame_digest=M.F.digest(deny),effective_tick_ns='206',state='denied',future_use_denied=True)
        reply=E.frame(binding,'DENY_ENCODING_ACK','synthetic.deny.ack',seq,body,deny['message_id']);data=Q.wire(reply)
        ack,aw=N.receive(db,cid,pid,data,'207');acked=fork(db)
        check('ACK完整原件同批保存',aw==['ij_frame','pd_deny_ack','ij_commit'] and N.read_ack(db,cid,pid)[0]==reply)
        before=snapshot(db);check('重复ACK仅查原',N.receive(db,cid,pid,data,'999')==(ack,[]) and snapshot(db)==before)
        closure,valid,cw=N.complete(db,cid,'208')
        check('255表实际组合',len(snapshot(db))==255)
        check('完整双成员核销有效',valid and {p['prepare_id']:p['basis'] for p in closure['members']}=={pid:'deny_ack',pid2:'never_attempted'})
        check('核销写集完整',cw==['pd_closure','pd_coverage','pd_coverage','pd_closure_commit','pd_close_completion'])
        check('正文符合现有Schema',N.validate('PreparationClosure',closure) is None and M.sealed(closure,'closure_digest')==closure)
        check('核销不恢复持有人或gate',tuple(db.execute('SELECT gate_state,holder_id FROM ct_current_state WHERE device_id=?',(device,)).fetchone())==tuple(base.execute('SELECT gate_state,holder_id FROM ct_current_state WHERE device_id=?',(device,)).fetchone()))
        before=snapshot(db);check('重复完成不刷新时间',N.complete(db,cid,'999')==(closure,True,[]) and snapshot(db)==before)
        denied('ACK未发送不采用',lambda:N.receive(fork(queued),cid,pid,data,'207'))
        denied('缺DENY证明不得完成',lambda:N.complete(fork(base),cid,'208'))
        denied('只有DENY请求不得完成',lambda:N.complete(fork(queued),cid,'208'))
        denied('核销不得早于ACK',lambda:N.complete(fork(acked),cid,'206'))
        for name,mutate in [('会话',lambda f:f.update(ipc_session_id='wrong.session')),('准备',lambda f:f['body'].update(prepare_id=pid2)),('reply',lambda f:f.update(reply_to='wrong.reply')),('摘要',lambda f:f['body'].update(deny_frame_digest=M.F.digest('wrong'))),('未来生效',lambda f:f['body'].update(effective_tick_ns='208')),('早于尝试',lambda f:f['body'].update(effective_tick_ns='204')),('乱序',lambda f:f.update(seq=str(seq+1))),('禁止承诺',lambda f:f['body'].update(future_use_denied=False))]:
            f=copy.deepcopy(reply);mutate(f);x=fork(sent);before=snapshot(x)
            denied('错配拒绝:'+name,lambda:N.receive(x,cid,pid,Q.wire(f),'207'));check('错配全库回滚:'+name,snapshot(x)==before)
        changed=copy.deepcopy(reply);changed['message_id']='different.ack'
        denied('已采用ACK不得换原件',lambda:N.receive(db,cid,pid,Q.wire(changed),'209'))
        for name,raw in [('长度',b'\0\0\0\1'+data[4:]),('空格',b' '+data[4:]),('重复键',data[4:-1]+b',"seq":"2"}')]:
            raw=raw if name=='长度' else len(raw).to_bytes(4,'big')+raw
            denied('线路拒绝:'+name,lambda:N.receive(fork(sent),cid,pid,raw,'207'))
        stages=[('请求',base,dw,lambda c,**k:N.deny(c,cid,pid,'204',**k)),('ACK',sent,aw,lambda c,**k:N.receive(c,cid,pid,data,'207',**k)),('核销',acked,cw,lambda c,**k:N.complete(c,cid,'208',**k))]
        for stage,source,writes,call in stages:
            for i in range(len(writes)):
                x=fork(source);before=snapshot(x);denied(stage+'逐写异常:'+str(i),lambda:call(x,fail_after=i));check(stage+'逐写回滚:'+str(i),snapshot(x)==before)
            for table in dict.fromkeys(writes):
                x=fork(source);before=snapshot(x);proxy=Omit(x,table)
                denied(stage+'缺写:'+table,lambda:call(proxy));check(stage+'缺写命中并回滚:'+table,proxy.hit>0 and snapshot(x)==before)
            for committed in (False,True):
                x=fork(source);before=snapshot(x);denied(stage+'提交观察故障:'+str(committed),lambda:call(CommitFault(x,committed)))
                if committed:
                    stable=snapshot(x);check(stage+'提交后只查原',call(x)[-1]==[] and snapshot(x)==stable)
                else:check(stage+'提交前回滚',snapshot(x)==before)
        x=fork(acked);before=snapshot(x);proxy=Omit(x,'pd_coverage',pid2)
        denied('不得遗漏未尝试成员',lambda:N.complete(proxy,cid,'208'));check('单成员遗漏全库回滚',proxy.hit==1 and snapshot(x)==before)
        insert=N.I
        def false_basis(table,**row):
            if table=='pd_coverage' and row['prepare_id']==pid:row.update(basis='never_attempted',ack_id=None)
            return insert(table,**row)
        with patch.object(N,'I',side_effect=false_basis):denied('已尝试不能伪造never_attempted',lambda:N.complete(fork(acked),cid,'208'))
        with patch.object(N,'MAX_MEMBERS',1):denied('成员超限不得截断',lambda:N.complete(fork(acked),cid,'208'))
        with patch.object(N,'MAX_CLOSURE_BYTES',1):denied('正文超限拒绝',lambda:N.complete(fork(acked),cid,'208'))
        denyack=N.read_ack(db,cid,pid)[2];proof=M.raw({'synthetic_revocation':True})
        def revoke(c):T.tx(c,lambda:c.execute(*D.I('pd_ack_revocation',ack_id=denyack['ack_id'],reason_body=proof,audit_body=proof,outbox_body=proof)))
        x=fork(acked);revoke(x);denied('先撤回DENY证明不得核销',lambda:N.complete(x,cid,'208'))
        x=fork(db);revoke(x)
        check('后撤回使已有核销失效',not N.current(x,cid) and not x.execute('SELECT 1 FROM pd_valid_closure WHERE closure_id=?',(closure['closure_id'],)).fetchone())
        before=snapshot(x);check('失效历史不自动重建',N.complete(x,cid,'999')==(closure,False,[]) and snapshot(x)==before)
        x=fork(db);T.tx(x,lambda:x.execute(*D.I('go_revocation',kind='close_ack',object_id=closeack['ack_id'],reason_body=proof,audit_body=proof)))
        check('关闭ACK撤回使完成资格失效',not N.current(x,cid) and N.complete(x,cid,'999')==(closure,False,[]))
        def end(c):T.tx(c,lambda:c.execute(*D.I('ij_end',**Q.Q.J.end(session=sid,tick=210)[1])))
        x=fork(base);end(x);denied('结束会话不能新增DENY',lambda:N.deny(x,cid,pid,'211'))
        x=fork(sent);end(x);N.receive(x,cid,pid,data,'211')
        check('结束后ACK仅为历史',N.read_ack(x,cid,pid)[3]['disposition']=='historical');denied('历史ACK不得核销',lambda:N.complete(x,cid,'212'))
        x=fork(db);end(x);check('后结束使当前资格失效',not N.current(x,cid) and N.complete(x,cid,'999')==(closure,False,[]))
        check('未退款未签发许可',db.execute('SELECT count(*) FROM ep_release').fetchone()[0]==base.execute('SELECT count(*) FROM ep_release').fetchone()[0] and not db.execute('SELECT 1 FROM ci_issue').fetchone())
        check('四个最终阻断保留',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'authorization-prepare-closure-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,candidate_tables=255,cases_passed=len(checks),mixed_preparation_closure_executed=True,denial_invalidation_verified=True,
            released_retired_providers_verified=False,physical_close_verified=False,clock_authenticity_verified=False,full_p0_reservation_verified=False,ipc_io_executed=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
