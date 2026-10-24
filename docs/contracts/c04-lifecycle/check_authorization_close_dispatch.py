"""认证关闭领域与共享日志的SQLite配对实验；不执行线路I/O或设备动作。"""
import argparse,hashlib,json,sqlite3
from pathlib import Path
from unittest.mock import patch
import check_final_authorization as T
import authorization_close_dispatch_model as D
import check_ipc_journal_storage as J
M=D.M;P=D.P;G=D.G;HERE=G.HERE;ROOT=HERE.parents[2]
def inputs():return list(dict.fromkeys(T.inputs()+G.SOURCES+J.INPUTS+[Path(J.__file__)]+[HERE/n for n in ('authorization-close-journal.sql','authorization-close-dispatch.schema.json','authorization_close_dispatch_model.py','check_authorization_close_dispatch.py','AUTHORIZATION_CLOSE_DISPATCH.md')]))
def run():
    checks=[];connections=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fork(db):
        x=sqlite3.connect(':memory:',isolation_level=None);db.backup(x);x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON');connections.append(x);return x
    def snapshot(db):return T.T.T.V.SC.snapshot(db)
    def denied(name,fn):
        try:fn()
        except (D.C.I.ClockIngressStop,sqlite3.IntegrityError,ValueError):check(name)
        else:raise AssertionError('应拒绝:'+name)
    try:
        db,other,command,auth,pid,provider,response=T.fixture();connections.extend([db]+other);D.install(db)
        binding=provider['binding'];device=binding['device_id'];eid=binding['writer_exit_id']
        fault=D.C.I.ingest(db,binding,b'{');plan=D.C.prepare(db,binding,fault['fault_ref'])
        state=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(device,))
        timing=dict(device_id=device,clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns='200',source_ref=T.T.V.ref('synthetic.close.tick'))
        protection,_=P.apply(db,D.C.pref(plan),[timing]);pr=D.pref(protection);cid=protection['exits'][0]['close_id'];sid=protection['exits'][0]['target']['session_id']
        base=fork(db);count=db.execute('SELECT count(*) FROM ij_frame').fetchone()[0]
        value,writes=D.queue(db,pr,cid,'201');f=M.E.one(db,'SELECT * FROM ij_frame WHERE frame_id=?',(value['dispatch_id'],))
        check('254表真实组合',len(snapshot(db))==254)
        check('完整关闭帧规范可验证',D.E.FRAME.is_valid(M.document(f['frame_body'])) and f['wire_body']==len(f['frame_body']).to_bytes(4,'big')+f['frame_body'])
        check('领域记录和日志同次预约',writes==['ij_frame','authorization_close_dispatch','ij_commit'] and db.execute('SELECT count(*) FROM ij_frame').fetchone()[0]==count+1)
        check('唯一同域序号连续',int(f['seq'])==1+int(base.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='c2w'",(sid,)).fetchone()[0]))
        old=snapshot(db);again,more=D.queue(db,pr,cid,'999')
        check('重试不新增序号预算或刷新时间',again==value and more==[] and snapshot(db)==old)
        bad=dict(pr,digest='sha256:'+'0'*64)
        denied('同close重试不能换保护引用',lambda:D.queue(db,bad,cid,'201'))
        denied('关闭选取不得早于准备cut',lambda:D.queue(fork(base),pr,cid,'199'))
        class CommitFault:
            def __init__(self,c,committed):self.c=c;self.committed=committed
            def __getattr__(self,key):return getattr(self.c,key)
            def commit(self):
                if self.committed:self.c.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation_failure')
        for committed in (False,True):
            x=fork(base);old=snapshot(x)
            denied('预约提交观察故障:'+str(committed),lambda:D.queue(CommitFault(x,committed),pr,cid,'201'))
            if committed:check('提交后丢失回执查原不重复扣费',D.queue(x,pr,cid,'999')==(value,[]))
            else:check('提交前失败不消耗日志额度',snapshot(x)==old)
        for i in range(len(writes)):
            x=fork(base);old=snapshot(x);denied('逐写回滚:'+str(i),lambda:D.queue(x,pr,cid,'201',fail_after=i));check('逐写不漏预算:'+str(i),snapshot(x)==old)
        class Omit:
            def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
            def __getattr__(self,key):return getattr(self.c,key)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
                return self.c.execute(sql,args)
        for table in writes:
            x=fork(base);old=snapshot(x);proxy=Omit(x,table)
            denied('缺写不能提交:'+table,lambda:D.queue(proxy,pr,cid,'201'));check('实际缺写且全库回滚:'+table,proxy.hit>0 and snapshot(x)==old)
        for table,field,badvalue in [('ij_frame','body_body',b'{}'),('ij_frame','domain_id','wrong.close'),('authorization_close_dispatch','protection_id','missing.protection')]:
            x=fork(base);old=snapshot(x);insert=D.I
            def changed(name,**row):
                if name==table:row[field]=badvalue
                return insert(name,**row)
            with patch.object(D,'I',side_effect=changed):denied('原件字段错配:'+field,lambda:D.queue(x,pr,cid,'201'))
            check('字段错配全库回滚:'+field,snapshot(x)==old)
        check('入流尝试一次登记',D.begin_write(db,cid,'202')=='attempt_recorded')
        old=snapshot(db);check('尝试不重复写线路',D.begin_write(db,cid,'999')=='lookup_only' and snapshot(db)==old)
        check('日志applied不当设备关闭',not db.execute('SELECT 1 FROM pd_close_completion WHERE close_id=?',(cid,)).fetchone() and not db.execute('SELECT 1 FROM go_close_ack WHERE close_id=?',(cid,)).fetchone())
        # 会话结束是日志事实，不生成监督退役或PreparationClosure。
        for queued in (False,True):
            x=fork(db if queued else base);T.tx(x,lambda:x.execute(*D.I('ij_end',**J.end(session=sid,tick=210)[1])))
            if queued:check('已预约终止会话只查原',D.queue(x,pr,cid,'211')[0]==value)
            else:denied('结束后不预约关闭帧',lambda:D.queue(x,pr,cid,'211'))
            check('结束不冒充退役或准备核销',not x.execute('SELECT 1 FROM ce_retirement WHERE exit_id=?',(eid,)).fetchone() and not x.execute('SELECT 1 FROM pd_close_completion WHERE close_id=?',(cid,)).fetchone())
        x=fork(base);v,_=D.queue(x,pr,cid,'201');T.tx(x,lambda:x.execute(*D.I('ij_end',**J.end(session=sid,tick=210)[1])))
        denied('预约后结束禁止首次入流',lambda:D.begin_write(x,cid,'211'))
        x=fork(base);D.queue(x,pr,cid,'201')
        denied('入流尝试提交后观察失败仍要求停止',lambda:D.begin_write(CommitFault(x,True),cid,'202'))
        check('尝试提交不确定禁止重复入流',D.begin_write(x,cid,'203')=='lookup_only')
        # 容量填充行是显式合成的拒收日志，仅测SQL计数；关闭帧本身为完整JCS线路字节。
        def fill(c,typ,n,length=2):
            seq=int(c.execute("SELECT coalesce(max(seq),'0') FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
            steps=J.rejection(seq=seq,mid='capacity.'+str(n),typ=typ,session=sid,eid=eid,device=device)
            steps[0][1].update(wire_body=b'x'*length,wire_length=length)
            T.tx(c,lambda:[c.execute(*D.I(table,**row)) for table,row in steps])
        x=fork(base);limit=M.E.one(x,'SELECT * FROM ij_session WHERE session_id=?',(sid,))
        ordinary=x.execute("SELECT name FROM ij_type WHERE direction='w2c' AND response=0 AND protected=0 ORDER BY name LIMIT 1").fetchone()[0]
        n=0
        while x.execute('SELECT count(*) FROM ij_frame WHERE session_id=?',(sid,)).fetchone()[0]<limit['max_frames']-limit['reserved_frames']:
            fill(x,ordinary,n);n+=1
        denied('普通日志不得侵占保护预留',lambda:fill(x,ordinary,n))
        check('关闭可使用保护帧预留',D.queue(x,pr,cid,'201')[0]['state']=='queued')
        while x.execute('SELECT count(*) FROM ij_frame WHERE session_id=?',(sid,)).fetchone()[0]<limit['max_frames']:
            fill(x,'SEND_REPORT',n);n+=1
        old=snapshot(x);check('满额仍可幂等查原',D.queue(x,pr,cid,'999')[1]==[] and snapshot(x)==old)
        x=fork(base);n=0
        while x.execute('SELECT count(*) FROM ij_frame WHERE session_id=?',(sid,)).fetchone()[0]<limit['max_frames']:
            fill(x,'SEND_REPORT',n);n+=1
        old=snapshot(x);denied('保护总额耗尽停止而不跳号',lambda:D.queue(x,pr,cid,'201'));check('耗尽不写半边预约',snapshot(x)==old)
        for spare,success in ((int(value['wire_bytes']),True),(int(value['wire_bytes'])-1,False)):
            x=fork(base);used=x.execute('SELECT sum(wire_length) FROM ij_frame WHERE session_id=?',(sid,)).fetchone()[0]
            fill(x,'SEND_REPORT',0,limit['max_bytes']-used-spare);old=snapshot(x)
            if success:
                D.queue(x,pr,cid,'201');check('完整线路字节恰好用满额度',x.execute('SELECT sum(wire_length) FROM ij_frame WHERE session_id=?',(sid,)).fetchone()[0]==limit['max_bytes'])
            else:
                denied('线路预算少一字节整事务拒绝',lambda:D.queue(x,pr,cid,'201'));check('字节拒绝不消耗序号',snapshot(x)==old)
        x=fork(base);used=x.execute('SELECT sum(wire_length) FROM ij_frame WHERE session_id=?',(sid,)).fetchone()[0]
        denied('普通字节不得侵占保护预留',lambda:fill(x,ordinary,0,limit['max_bytes']-limit['reserved_bytes']-used+1))
        for sql in ('DELETE FROM authorization_close_dispatch','UPDATE authorization_close_dispatch SET digest=digest'):
            denied('关闭预约不可变:'+sql,lambda sql=sql:T.tx(db,lambda:db.execute(sql)))
        check('四个最终签发阻断保持',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        check('仍无最终设备许可',not db.execute('SELECT 1 FROM ci_issue').fetchone())
        for x in connections:assert not x.in_transaction and not x.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'authorization-close-dispatch-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();value=dict(all_passed=True,approved=False,candidate_tables=254,cases_passed=len(checks),protected_journal_capacity_verified=True,
            full_p0_reservation_verified=False,ipc_io_executed=False,close_ack_verified=False,preparation_closure_executed=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(value))
        print(json.dumps({k:v for k,v in value.items() if k not in ('checks','inputs')}))
