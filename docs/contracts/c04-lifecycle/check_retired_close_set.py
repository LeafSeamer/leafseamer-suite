"""双出口退役关闭集合、跨域无时间捏造与撤回失效的离线验收。"""
import argparse,copy,hashlib,json,sqlite3,tempfile
from pathlib import Path
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import check_supervisor_retirement_adoption as T
import retired_close_set_model as X
R=X.R;N=X.N;M=X.M;P=X.P;D=N.D;HERE=X.G.HERE;ROOT=HERE.parents[2]
def inputs():return T.inputs()+[HERE/n for n in ('build_retired_close_set.py','retired-close-set.schema.json','retired-close-set.sql','retired_close_set_model.py','check_retired_close_set.py','RETIRED_CLOSE_SET.md')]
def fixture():
    db,connections,sd,domain,eid,cid=T.fixture(worker_devices=['dev.1','dev.2']);X.install(db)
    for exitid in ('exit_dev_1','exit_dev_2'):
        b=R.runtime(db,exitid)[0]['binding']
        if not db.execute('SELECT 1 FROM authorization_close_dispatch d JOIN go_latest_close x USING(close_id) WHERE x.exit_id=?',(exitid,)).fetchone():
            fault=D.C.I.ingest(db,b,b'{');plan=D.C.prepare(db,b,fault['fault_ref']);state=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(b['device_id'],))
            timing=dict(device_id=b['device_id'],clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns='200',source_ref=T.T.T.V.ref('synthetic.retirement.tick'))
            protection,_=P.apply(db,D.C.pref(plan),[timing]);othercid=protection['exits'][0]['close_id'];D.queue(db,D.pref(protection),othercid,'201')
    return db,connections,sd,domain,eid,cid
def run():
    checks=[];connections=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def snap(c):return T.T.T.T.V.SC.snapshot(c)
    def fork(c):
        x=sqlite3.connect(':memory:',isolation_level=None);c.backup(x);x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON');connections.append(x);return x
    def denied(n,fn,contains=None):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error,D.C.I.ClockIngressStop) as e:
            if contains:
                chain=[];v=e
                while v is not None:chain.append(str(v));v=v.__cause__
                assert any(contains in s for s in chain),(n,chain)
            check(n)
        else:raise AssertionError('应拒绝:'+n)
    try:
        db,others,sd,domain,eid,cid=fixture();connections.extend(others)
        def adopt(c,e):return R.adopt(c,e,sd,'old','retirement.complete',domain,'3')
        def complete(c,**kw):return X.complete(c,eid,'retired.complete',**kw)
        denied('缺全部采用不得完成',lambda:complete(db),'retired_close_adoption_not_current')
        adopt(db,eid);other='exit_dev_2'
        denied('缺兄弟出口采用不得完成',lambda:complete(db),'retired_close_adoption_not_current')
        othercid=db.execute('SELECT close_id FROM go_latest_close WHERE exit_id=?',(other,)).fetchone()[0]
        denied('首出口退役即阻止兄弟会话发送',lambda:D.begin_write(db,othercid,'202'),'retired_worker_write')
        old=M.E.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(other,));new=dict(old,exit_id='late.exit',controller_boot_id='new.controller',ipc_session_id='new.ipc',device_session_id='new.device.session')
        denied('换controller和IPC不能登记旧worker出口',lambda:db.execute(*X.I('ce_exit',**new)),'retired_worker_registration')
        session=M.E.one(db,'SELECT s.* FROM ij_session s JOIN ij_exit e USING(session_id) WHERE e.exit_id=?',(other,));session.update(session_id='late.session',controller_boot_id='new.controller',ipc_session_id='new.ipc')
        denied('旧worker不能登记新会话',lambda:db.execute(*X.I('ij_session',**session)),'retired_worker_session')
        request=M.E.one(db,'SELECT * FROM ep_request LIMIT 1');request.update(prepare_id='late.prepare')
        denied('旧worker不能登记新准备',lambda:db.execute(*X.I('ep_request',**request)),'retired_worker_prepare')
        adopt(db,other);base=fork(db);v,valid,writes=complete(db)
        check('260表实际组合',len(snap(db))==260)
        check('双出口全部覆盖',valid and [t['binding']['writer_exit_id'] for t in v['targets']]==[eid,other])
        check('非空与空准备集合均核销',[len(t['preparations']) for t in v['targets']]==[1,0])
        check('三表四写完整封存',writes==['rcs_completion','rcs_target','rcs_target','rcs_commit'] and X.read(db,v['completion_id'])==v)
        check('跨域不制造完成时间','tick' not in json.dumps(v) and int(domain['clock_domain_id']!=v['targets'][0]['binding']['clock_domain_id'])==1)
        for field in ('completed_tick_ns','ack_id'):
            bad=copy.deepcopy(v);bad[field]='1';denied('Schema拒绝伪造字段:'+field,lambda:X.validate(bad))
        check('独立资格覆盖双出口',db.execute('SELECT count(*) FROM retired_close_usable').fetchone()[0]==2)
        before=snap(db);check('重复查原无写',complete(db)==(v,True,[]) and snap(db)==before)
        for table in ('go_close_ack','pd_close_completion','ep_release','ci_issue','go_recovery_commit'):
            check('不伪造或推进:'+table,[tuple(r) for r in db.execute('SELECT * FROM '+table)]==[tuple(r) for r in base.execute('SELECT * FROM '+table)])
        check('持有人及保护状态不变',[tuple(r) for r in db.execute('SELECT device_id,gate_state,holder_id FROM ct_current_state')]==[tuple(r) for r in base.execute('SELECT device_id,gate_state,holder_id FROM ct_current_state')])
        for i in range(len(writes)):
            x=fork(base);before=snap(x);denied('逐写异常:'+str(i),lambda:complete(x,fail_after=i));check('逐写整体回滚:'+str(i),snap(x)==before)
        class Omit:
            def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
            def __getattr__(self,k):return getattr(self.c,k)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
                return self.c.execute(sql,args)
        for table in set(writes):
            x=fork(base);before=snap(x);proxy=Omit(x,table);denied('缺写:'+table,lambda:complete(proxy));check('缺写回滚:'+table,proxy.hit>0 and snap(x)==before)
        class CommitFault:
            def __init__(self,c,committed):self.c=c;self.committed=committed
            def __getattr__(self,k):return getattr(self.c,k)
            def commit(self):
                if self.committed:self.c.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation_failure')
        for committed in (False,True):
            x=fork(base);before=snap(x);denied('提交观察故障:'+str(committed),lambda:complete(CommitFault(x,committed)))
            if committed:
                after=snap(x);check('已提交按原ID查询',complete(x)==(v,True,[]) and snap(x)==after)
            else:check('未提交整体回滚',snap(x)==before)
        # 直接提交故意重算摘要的错误正文，验证SQL投影不能漏掉准备成员。
        for name,mutate in [('漏准备',lambda t:t['preparations'].clear()),('重复准备',lambda t:t['preparations'].append(copy.deepcopy(t['preparations'][0]))),('换撤回',lambda t:t['preparations'][0]['revocation_ref'].update(id='wrong'))]:
            x=fork(base);bad=copy.deepcopy(v);mutate(bad['targets'][0]);bad=M.sealed(bad,'completion_digest');raw=M.raw(bad);before=snap(x)
            def invalid():
                x.execute(*X.I('rcs_completion',completion_id=bad['completion_id'],anchor_exit_id=eid,digest=bad['completion_digest'],body=raw))
                for t in bad['targets']:x.execute(*X.I('rcs_target',completion_id=bad['completion_id'],exit_id=t['binding']['writer_exit_id'],close_id=t['close_ref']['id'],adoption_digest=t['retirement_adoption_ref']['digest'],body=M.raw(t)))
            denied('SQL拒绝:'+name,lambda:N.transaction(x,invalid),'retired_close_prepare_coverage');check('错误集合回滚:'+name,snap(x)==before)
        for attr,value in [('MAX_EXITS',1),('MAX_PREPARES',0),('MAX_BYTES',1)]:
            x=fork(base);before=snap(x)
            with patch.object(X,attr,value):denied('容量拒绝:'+attr,lambda:complete(x))
            check('容量拒绝不留半写:'+attr,snap(x)==before)
        db.execute('BEGIN');denied('不接管外部事务',lambda:complete(db));check('调用方事务保留',db.in_transaction);db.rollback()
        denied('重复ID不能换anchor',lambda:X.complete(db,other,'retired.complete'),'retired_close_replay_anchor')
        collision,collision_others,_,_,collision_eid,_=T.fixture();connections.extend(collision_others)
        denied('相同boot及域却不同完整启动身份拒绝合并',lambda:X.inventory(collision,collision_eid),'retired_close_worker_collision')
        # 两个真实SQLite连接：先撤回占writer锁，完成方失败后必须重新读取当前资格。
        scratch=(ROOT/'logs').resolve();scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='retired-close-sqlite-',dir=scratch) as folder:
            assert Path(folder).resolve().parent==scratch and not Path(folder).is_symlink()
            path=Path(folder)/'controller.sqlite';a=sqlite3.connect(path,isolation_level=None,timeout=0);base.backup(a)
            b=sqlite3.connect(path,isolation_level=None,timeout=0)
            try:
                for c in (a,b):c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON')
                a.execute('BEGIN IMMEDIATE');reason=M.raw({'reason':'synthetic ordered withdrawal'})
                a.execute(*X.I('cu_revocation',kind='retirement',object_id=other,reason_body=reason,audit_body=reason))
                denied('另一writer占锁时不能完成',lambda:complete(b),'database is locked')
                check('占锁事务不被接管',a.in_transaction and not b.in_transaction)
                a.commit();denied('撤回先提交则完成拒绝',lambda:complete(b),'retired_close_adoption_not_current')
                check('竞争失败无半完成',not b.execute('SELECT 1 FROM rcs_completion').fetchone())
            finally:a.close();b.close()
        R.revoke(db,other,{'reason':'synthetic withdrawal'})
        check('单出口撤回使整个集合失效',not X.current(db,'retired.complete') and not db.execute('SELECT 1 FROM retired_close_usable').fetchone())
        before=snap(db);check('撤回后查原不复活',complete(db)==(v,False,[]) and snap(db)==before)
        denied('新ID不能绕过撤回',lambda:X.complete(db,eid,'retired.retry'),'retired_close_adoption_not_current')
        denied('撤回后兄弟会话仍禁写',lambda:D.begin_write(db,othercid,'203'),'retired_worker_write')
        for table in ('rcs_completion','rcs_target','rcs_commit'):
            for op in ('DELETE FROM '+table,'UPDATE '+table+' SET completion_id=completion_id'):denied('不可变:'+op,lambda op=op:N.transaction(db,lambda:db.execute(op)))
        check('四个最终发送阻断保持',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'retired-close-set-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=260,complete_retired_worker_set_verified=True,recovery_consumption_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
