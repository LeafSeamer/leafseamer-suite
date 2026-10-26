"""跨域保护到混合关闭恢复seal的合成SQLite验收，实际线路及提供者未实现。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_snapshot_domain_order as T
import domain_protection_model as Q
import typed_gate_path_model as O
Z=Q.Z;Y=Z.Y;X=Z.X;R=Z.R;N=Z.N;M=Z.M;P=Z.P;D=N.D;A=N.A;E=N.E;I=Z.I;HERE=Q.G.HERE;ROOT=HERE.parents[2]
def inputs():return T.inputs()+[HERE/n for n in ('build_domain_protection.py','domain-protection.schema.json','domain-protection.sql','domain_protection_model.py','check_domain_protection.py','DOMAIN_PROTECTION.md')]+[HERE/'typed_gate_path_model.py']
def fixture():
    db,connections,sd,domain,eid,cid=T.T.fixture();Y.install(db);Z.install(db)
    for e in ('exit_dev_1','exit_dev_2'):R.adopt(db,e,sd,'old','retirement.complete',domain,'3')
    X.complete(db,eid,'domain.retired');descriptor=R.read(db,eid)['source_bundle']['evaluator_descriptor'];Z.restart(db,'dev.1','domain.restart',descriptor,'5',E.ref('synthetic.provider'))
    fresh=T.new_exit(db,eid,descriptor);Q.install(db);c=dict(exit=fresh,device='dev.1',prefix='domain.worker')
    def bootstrap():
        for sql,args in O.session(db,c,7):db.execute(sql,tuple('ipc/0.14.0-continuation-draft.1' if v=='ipc/0.13.0-journal-draft.1' else v for v in args))
    N.transaction(db,bootstrap);b=R.runtime(db,fresh)[0]['binding'];fault=D.C.I.ingest(db,b,b'{');plan=D.C.prepare(db,b,fault['fault_ref'])
    timing=dict(device_id='dev.1',clock_domain_id=descriptor['clock_domain_id'],descriptor_digest=descriptor['descriptor_digest'],selected_tick_ns='10',source_ref=E.ref('synthetic.current.tick'))
    return db,connections,eid,fresh,D.C.pref(plan),[timing],[dict(exit_id=eid,completion_id='domain.retired')]
def run():
    checks=[];connections=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def snap(c):return T.T.T.T.T.T.V.SC.snapshot(c)
    def fork(c):
        x=sqlite3.connect(':memory:',isolation_level=None);c.backup(x);x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON');connections.append(x);return x
    def denied(n,fn):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error,N.C.I.ClockIngressStop):check(n)
        else:raise AssertionError('应拒绝:'+n)
    try:
        db,others,eid,fresh,plan,timings,retired=fixture();connections.extend(others);base=fork(db)
        check('266表组合',len(snap(db))==266)
        before=snap(db);denied('旧writer无法生成跨域关闭',lambda:P.apply(db,plan,timings));check('旧writer拒绝整笔回滚',snap(db)==before)
        value,writes=Q.apply(db,plan,timings,retired);ident=value['protection_id'];active=value['active_protection'];newcid=active['exits'][0]['close_id']
        check('当前域生成关闭且旧域复用退役',len(active['exits'])==1 and active['exits'][0]['target']['binding']['writer_exit_id']==fresh and value['retired'][0]['writer_exit_id']==eid)
        for table in ('pd_member','ep_revocation','authorization_close_dispatch','ij_frame'):
            check('保护不新增旧出口数据:'+table,snap(db)[table]==before[table])
        check('旧关闭集合仍当前',X.current(db,'domain.retired') and Q.current(db,ident))
        check('旧cut与新域时间不混用',db.execute('SELECT p.selected_tick FROM pd_cut p JOIN go_close c ON c.prepare_cut_id=p.cut_id WHERE c.close_id=?',(newcid,)).fetchone()[0]==P.u(10))
        original=snap(db);check('重复只查原',Q.apply(db,plan,[],retired)==(value,[]) and snap(db)==original)
        denied('重复更换退役绑定拒绝',lambda:Q.apply(db,plan,[],[dict(exit_id=eid,completion_id='other')]))
        for choices in ([],retired+retired,[dict(exit_id='exit_dev_2',completion_id='domain.retired')],[dict(exit_id=eid,completion_id='missing')]):
            x=fork(base);before=snap(x);denied('退休选择不完整或错绑:'+str(choices),lambda:Q.apply(x,plan,timings,choices));check('错误选择无部分写入',snap(x)==before)
        x=fork(base);R.revoke(x,'exit_dev_2',dict(synthetic='revoked'));before=snap(x);denied('兄弟出口撤回阻止保护采用',lambda:Q.apply(x,plan,timings,retired));check('撤回后失败整笔回滚',snap(x)==before)
        for i in range(len(writes)):
            x=fork(base);before=snap(x);denied('逐写故障:'+str(i),lambda:Q.apply(x,plan,timings,retired,fail_after=i));check('逐写回滚:'+str(i),snap(x)==before)
        class Omit:
            def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
            def __getattr__(self,n):return getattr(self.c,n)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
                return self.c.execute(sql,args)
        for table in sorted(set(writes)):
            x=fork(base);before=snap(x);proxy=Omit(x,table);denied('漏写:'+table,lambda:Q.apply(proxy,plan,timings,retired));check('漏写整笔回滚:'+table,proxy.hit>0 and snap(x)==before)
        class CommitFault:
            def __init__(self,c,committed):self.c=c;self.committed=committed
            def __getattr__(self,n):return getattr(self.c,n)
            def commit(self):
                if self.committed:self.c.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation')
        for committed in (False,True):
            x=fork(base);before=snap(x);denied('提交观察异常要求停止:'+str(committed),lambda:Q.apply(CommitFault(x,committed),plan,timings,retired))
            if committed:check('回执丢失后查原不重做',Q.apply(x,plan,[],retired)==(value,[]))
            else:check('未提交观察故障完整回滚',snap(x)==before)
        x=fork(db);R.revoke(x,'exit_dev_2',dict(synthetic='later'));check('后续撤回使当前资格失效',not Q.current(x,ident));check('失效后历史查原不复活',Q.apply(x,plan,[],retired)==(value,[]) and not Q.current(x,ident))
        # 新域真实结构的日志与ACK；握手、接收者身份及物理完成仍是合成提供者。
        D.queue(db,D.pref(active),newcid,'11');D.begin_write(db,newcid,'12');dispatch,_=D.read(db,newcid);b=R.runtime(db,fresh)[0]['binding'];sid=dispatch['target']['session_id']
        seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
        frame=E.frame(dict(b,device_id=None),'CLOSE_GATE_ACK','domain.close.ack',seq,dict(close_id=newcid,closed_device_ids=['dev.1']),dispatch['dispatch_id']);raw=M.raw(frame)
        A.receive(db,newcid,len(raw).to_bytes(4,'big')+raw,'13',E.ref('synthetic.observer'));N.complete(db,newcid,'14')
        check('当前域完整ACK及空准备核销',N.current(db,newcid))
        probe=T.snapshot(db,'domain.probe',fresh,20);probe.update(snapshot_id='domain.recovery.snapshot',sampled_tick=P.u(21),expires_tick=P.u(121),safety_revision=P.u(int(probe['safety_revision'])+1))
        choices=[dict(kind='worker_ack',close_id=newcid),dict(kind='supervisor_retired',close_id=value['retired'][0]['close_ref']['id'],completion_id='domain.retired')]
        recovered,usable,_=Y.complete(db,'domain.recovery',probe,[],choices,'21',E.ref('synthetic.snapshot'))
        check('新域快照与混合关闭进入恢复seal',usable and Y.current(db,'domain.recovery'))
        R.revoke(db,'exit_dev_2',dict(synthetic='after_recovery'))
        check('恢复seal后兄弟撤回同步失效',not Y.current(db,'domain.recovery') and not Q.current(db,ident))
        check('失效恢复仍可读取历史',Y.read(db,'domain.recovery')==recovered)
        for table in ('xdp_protection','xdp_retired','xdp_commit'):
            denied('封存不可删:'+table,lambda table=table:N.transaction(db,lambda:db.execute('DELETE FROM '+table)))
        check('旧worker永久禁写仍有效',db.execute('SELECT count(*) FROM rcs_stopped_worker').fetchone()[0]>0)
        check('四个最终阻断保留',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        check('未产生实际发送许可',not db.execute('SELECT 1 FROM ci_issue').fetchone())
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'domain-protection-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=266,cross_domain_protection_to_recovery_seal_verified=True,full_reopen_verified=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(M.raw(v))
        print(json.dumps({k:x for k,x in v.items() if k not in ('checks','inputs')}))
