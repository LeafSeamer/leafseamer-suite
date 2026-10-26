"""完整恢复快照和OPEN前态读取的SQLite验收；外部提供者仍为合成。"""
import argparse,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_typed_gate_fence as T
import check_final_source_bodies as B
import open_source_model as M
F=M.F;N=M.N;P=M.P;S=M.S;I=M.I;E=T.E;HERE=T.HERE;ROOT=T.ROOT
LINKS=dict(authorization_ref='pending.auth',resource_ref='resource.full',run_snapshot_ref='pending.runs',command_snapshot_ref='pending.commands',time_snapshot_ref='pending.time')
LOCAL=('open_source_model.py','check_open_source.py','OPEN_SOURCE.md')
def inputs():
    import check_open_contract as C
    return list(dict.fromkeys(T.inputs()+B.inputs()+C.inputs()+[HERE/n for n in LOCAL]))
def fixture():
    db,connections,eid,cid=T.T.fixture();request,_=T.D.queue(db,cid,'8');T.D.begin_write(db,cid,'9');binding=T.R.runtime(db,eid)[0]['binding'];sid=request['target']['session_id']
    original=T.D.read(db,cid)[1];proof=T.M.raw(dict(synthetic='full_write_observation'))
    N.transaction(db,lambda:db.execute(*I('ij_write_result',frame_id=original['frame_id'],state='written',completed_tick=P.u(9),written_bytes=original['wire_length'],end_id=None,result_body=proof)))
    frame=E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','source.close.ack',F.seq(db,sid,'w2c'),dict(close_id=cid,closed_device_ids=['dev.1']),request['dispatch_id']);raw=T.M.raw(frame)
    T.A.receive(db,cid,len(raw).to_bytes(4,'big')+raw,'10',E.ref('synthetic.observer'));N.complete(db,cid,'11');F.install(db)
    selections=[dict(kind='worker_ack',close_id=c) if e==eid else dict(kind='supervisor_retired',close_id=c,completion_id='healthy.retired') for c,e in db.execute("SELECT close_id,exit_id FROM go_latest_close WHERE device_id='dev.1' ORDER BY close_id")]
    return db,connections,eid,cid,sid,selections
def recover(db,eid,selections,**kw):return M.recover(db,'full.recovery','full.snapshot',eid,LINKS,'22','100',E.ref('provider.full'),selections,**kw)
def fence(db,cid,sid):
    q,_=F.queue(db,cid,'full.fence','full.token','23','40','90');F.begin_write(db,'full.fence','24')
    b=dict(request_id='full.fence',request_digest=q['request_digest'],binding=q['binding'],gate_revision=q['target_gate_revision'],gate_token='full.token',effective_tick_ns='24',state='fenced')
    f=E.frame(q['binding'],'GATE_FENCE_ACK','full.response',F.seq(db,sid,'w2c'),b,'full.fence.frame');raw=T.M.raw(f);F.receive(db,'full.fence',len(raw).to_bytes(4,'big')+raw,'25',E.ref('observer.full'));return F.adopt(db,'full.fence','26')[0]
def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fork(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');dbs.append(c);return c
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,sqlite3.Error,ValidationError) as error:
            messages=[]
            while error:
                assert isinstance(error,(ValueError,RuntimeError,sqlite3.Error,ValidationError)),type(error)
                messages.append(str(error));error=error.__cause__
            if reason:assert any(reason in m for m in messages),(name,messages)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    class Omit:
        def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
        def __getattr__(self,k):return getattr(self.c,k)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
            return self.c.execute(sql,args)
    try:
        db,others,eid,cid,sid,selections=fixture();dbs.extend(others);base=fork(db)
        receipt,body,valid,writes=recover(db,eid,selections);check('完整恢复采用',valid and body['holds']==[] and len(T.snapshot(db))==269)
        check('后继安全cut由实际行核对',N.transaction(db,lambda:S.snapshot(db,'full.snapshot'))==body)
        check('完整读取闭包',N.transaction(db,lambda:M.read(db,'full.recovery'))==(receipt,body))
        prior=T.snapshot(db);check('重复恢复仅查原',recover(db,eid,selections)==(receipt,body,True,[]) and prior==T.snapshot(db))
        denied('重入不能刷新期限',lambda:M.recover(db,'full.recovery','full.snapshot',eid,LINKS,'22','101',E.ref('provider.full'),selections),'open_source_replay_conflict')
        denied('重入不能换来源链接',lambda:M.recover(db,'full.recovery','full.snapshot',eid,dict(LINKS,time_snapshot_ref='other'),'22','100',E.ref('provider.full'),selections),'open_source_replay_conflict')
        denied('重入不能遗漏关闭目标',lambda:recover(db,eid,selections[:-1]),'open_source_replay_targets')
        for key in LINKS:
            c=fork(base);bad=dict(LINKS);bad.pop(key);before=T.snapshot(c)
            denied('关联字段不能缺失:'+key,lambda:M.recover(c,'full.recovery','full.snapshot',eid,bad,'22','100',E.ref('provider.full'),selections),'open_source_link_fields');check('关联错误无写:'+key,T.snapshot(c)==before)
        c=fork(base);denied('采样等于到期拒绝',lambda:M.recover(c,'full.recovery','full.snapshot',eid,LINKS,'22','22',E.ref('provider.full'),selections),'open_source_window')
        for index in range(len(writes)):
            c=fork(base);before=T.snapshot(c);denied('逐写故障:'+str(index),lambda:recover(c,eid,selections,fail_after=index));check('逐写回滚:'+str(index),before==T.snapshot(c))
        for table in sorted(set(writes)):
            c=fork(base);before=T.snapshot(c);proxy=Omit(c,table);denied('缺写拒绝:'+table,lambda:recover(proxy,eid,selections));check('缺写回滚:'+table,proxy.hit>0 and before==T.snapshot(c))
        class CommitFault:
            def __init__(self,c,committed):self.c=c;self.committed=committed
            def __getattr__(self,k):return getattr(self.c,k)
            def commit(self):
                if self.committed:self.c.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation')
        for committed in (False,True):
            c=fork(base);before=T.snapshot(c);denied('提交观察故障:'+str(committed),lambda:recover(CommitFault(c,committed),eid,selections))
            if committed:
                after=T.snapshot(c);check('已提交恢复查原不再推进代次',recover(c,eid,selections)[3]==[] and after==T.snapshot(c))
            else:check('提交前失败回滚',before==T.snapshot(c))
        gate=fence(db,cid,sid);post=fork(db)
        def source(c=db,tick='27'):return N.transaction(c,lambda:M.before_open(c,'full.recovery','full.fence',tick))
        v=source();check('开放前态对应完整物理原件',v['gate_before']['record_ref']['id']==gate['gate_id'] and v['resource_snapshot_ref']['digest']==body['evidence_digest'] and v['control_before']['record_ref']==body['control_state_ref'])
        holder=v['originals']['control']['holder'];check('控制身份未转交',v['control_before']['holder']==(None if holder is None else {k:holder[k] for k in ('issuer_id','issuer_epoch','principal_id')}))
        check('gate仍fenced且控制protected',v['gate_before']['phase']=='fenced' and v['control_before']['gate_state']=='protected')
        for tick in ('26','89'):check('有效时窗:'+tick,source(tick=tick)==v)
        for tick in ('25','90','100'):denied('时窗拒绝:'+tick,lambda:source(tick=tick),'open_source_gate_window')
        denied('读取要求事务',lambda:M.before_open(db,'full.recovery','full.fence','27'),'open_source_transaction_required')
        N.transaction(db,lambda:db.execute(*I('gf_revocation',ack_id='full.fence.ack',reason_body=T.M.raw({'withdrawn':True}),audit_body=T.M.raw({'withdrawn':True}))))
        denied('屏障撤回不再供开放',lambda:source(),'open_source_not_current')
        check('失效仍可查历史恢复',N.transaction(db,lambda:M.read(db,'full.recovery'))==(receipt,body))
        c=fork(post);N.transaction(c,lambda:c.execute(*I('go_revocation',kind='close_ack',object_id=T.N.CE.ack_row(c,cid)['adopted_ack_id'],reason_body=T.M.raw({'withdrawn':True}),audit_body=T.M.raw({'withdrawn':True}))))
        denied('关闭证明撤回传播',lambda:source(c),'open_source_not_current')
        c=fork(post);b=T.M.raw(dict(synthetic='session_end'));N.transaction(c,lambda:c.execute(*I('ij_end',end_id='source.end',session_id=sid,reason='shutdown',cause_frame_id=None,observed_tick=P.u(28),evidence_body=b,audit_body=b)))
        denied('会话结束不再供开放',lambda:source(c),'open_source_not_current')
        legacy,others,*_=T.fixture();dbs.extend(others);denied('旧占位资源正文不能升级',lambda:N.transaction(legacy,lambda:M.read(legacy,'fence.recovery')))
        nonempty,*_=B.fixture();dbs.append(nonempty)
        hs=N.transaction(nonempty,lambda:M.observations(nonempty,'device','full.nonempty'));check('非空风险原件不省略',len(hs)==1 and hs[0]['hold_id']=='hc' and hs[0]['owner_ref']=='owner')
        check('完整归属而非占位ID',N.transaction(nonempty,lambda:S.ownership(nonempty,hs[0]['owner_ref']))['hold_ref']['id']=='hc')
        s,hh,bb=N.transaction(nonempty,lambda:M.prepare_snapshot(nonempty,'nonempty.recovery','nonempty.snapshot','exit.0',LINKS,'24','90',E.ref('provider.full')))
        check('非空候选正文保留完整成员',len(bb['holds'])==1 and bb['holds'][0]['owner_ref']['id']=='owner' and len(hh)==1)
        c=fork(nonempty);B.O.U.tx(c,[B.O.revoke()]);denied('撤回归属不能继续普通恢复',lambda:N.transaction(c,lambda:M.observations(c,'device','refused')),'open_source_owner_missing')
        c=fork(nonempty);B.T.execute(c,B.O.U.offer(c));B.T.execute(c,B.O.takeover(c));denied('接管及未解决命令拒绝恢复',lambda:N.transaction(c,lambda:M.observations(c,'device','refused')))
        check('最终四阻断保持',post.execute("SELECT count(*) FROM sqlite_schema WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for c in dbs:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in dbs:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'open-source-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=269,full_recovery_snapshot_verified=True,open_before_projection_verified=True,full_open_verified=False,nonempty_recovery_verified=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(T.M.raw(v))
        print(json.dumps({k:x for k,x in v.items() if k not in ('checks','inputs')}))
