"""旧worker退役与新worker ACK共同消费到恢复seal的离线实验。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_retired_close_set as T
import recovery_close_choice_model as Y
import typed_gate_path_model as O
X=Y.X;R=Y.R;N=Y.N;M=Y.M;P=Y.P;D=N.D;A=N.A;E=N.E;I=Y.I;HERE=Y.G.HERE;ROOT=HERE.parents[2]
def inputs():return T.inputs()+[HERE/n for n in ('build_recovery_close_choice.py','recovery-close-choice.sql','recovery-close-choice-layout.sql','recovery-close-choice.schema.json','recovery_close_choice_model.py','check_recovery_close_choice.py','RECOVERY_CLOSE_CHOICE.md')]
def fixture():
    db,connections,sd,domain,eid,cid=T.fixture();Y.install(db)
    for e in ('exit_dev_1','exit_dev_2'):R.adopt(db,e,sd,'old','retirement.complete',domain,'3')
    X.complete(db,eid,'retired.initial')
    old=M.E.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,));runtime=copy.deepcopy(R.runtime(db,eid)[0]);fresh='fresh.exit'
    row=dict(old,exit_id=fresh,controller_boot_id='fresh.controller',worker_boot_id='fresh.worker',ipc_session_id='fresh.ipc',device_session_id='fresh.device')
    runtime['binding'].update(writer_exit_id=fresh,controller_boot_id=row['controller_boot_id'],worker_boot_id=row['worker_boot_id'],ipc_session_id=row['ipc_session_id'],device_session_id=row['device_session_id'])
    runtime['binding_id']='fresh.runtime';runtime['intent'].update(launch_id='fresh.launch',member_id='fresh.member',containment_ref=dict(group_id='fresh.group',generation='fresh.generation',backend='windows_job'))
    runtime['admission_receipt'].update(launch_id='fresh.launch',launch_intent_digest=M.F.digest(runtime['intent']),member_id='fresh.member',member_boot_id='fresh.worker',containment_ref=runtime['intent']['containment_ref'])
    runtime=M.sealed(runtime,'binding_digest');row['runtime_binding_body']=M.raw(runtime);R.validate('RuntimeExitBinding',runtime)
    c=dict(exit=fresh,device=old['device_id'],prefix='fresh.worker');tick=P.u(210);control='fresh.protection';cut='fresh.cut';close='registration.'+fresh;body=M.raw({'synthetic_start':True})
    def register():
        db.execute(*I('ce_exit',**row));previous=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(c['device'],));state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(c['device'],))
        change=dict(previous,change_id=control,sequence=P.u(int(previous['sequence'])+1),previous_id=previous['change_id'],kind='gate_protect',state_id=control,operation_id=None,offer_id=None,request_id=None,now_tick=tick);db.execute(*I('ct_change',**change))
        after={k:v for k,v in state.items() if k!='device_id'};after.update(change_id=control,record_revision=P.u(int(state['record_revision'])+1),gate_state='protected')
        record=P.S.control_body(db,after);after.update(record_digest=record['record_digest'],record_body=M.raw(record));db.execute(*I('ct_state',**after))
        db.execute(*I('go_close',prepare_cut_id=cut,close_id=close,device_id=c['device'],exit_id=fresh,revision=P.u(1),protection_change_id=control,gate_id=None,reason_ref='synthetic_start',body=body,outbox_body=body,audit_body=body))
        head=db.execute('SELECT max(sequence) FROM pd_registration').fetchone()[0]
        db.execute(*I('pd_cut',cut_id=cut,kind='close',prepare_head=head,selected_tick=tick,selector_digest=M.F.digest({'synthetic_start':True}),selector_body=body,control_id=None,cancel_id=None,run_id=None,close_id=close))
        db.execute(*I('pd_cut_commit',cut_id=cut,committed_tick=tick,audit_body=body,outbox_body=body))
        for table in ('ct_audit','ct_outbox','ct_commit'):
            values=dict(change_id=control)
            if table!='ct_commit':values['body']=body
            if table=='ct_outbox':values['event_id']=control
            db.execute(*I(table,**values))
    N.transaction(db,register)
    steps=O.session(db,c,211)
    def bootstrap():
        for sql,args in steps:
            args=tuple('ipc/0.14.0-continuation-draft.1' if v=='ipc/0.13.0-journal-draft.1' else v for v in args);db.execute(sql,args)
    N.transaction(db,bootstrap)
    b=runtime['binding'];fault=D.C.I.ingest(db,b,b'{');plan=D.C.prepare(db,b,fault['fault_ref']);state=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(c['device'],))
    timing=dict(device_id=c['device'],clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns='220',source_ref=E.ref('synthetic.recovery.tick'))
    protection,_=P.apply(db,D.C.pref(plan),[timing]);newcid=None
    for t in protection['exits']:
        D.queue(db,D.pref(protection),t['close_id'],'221')
        if t['target']['binding']['writer_exit_id']==fresh:newcid=t['close_id']
    X.complete(db,eid,'retired.current');dispatch,_=D.read(db,newcid);D.begin_write(db,newcid,'222')
    sid=dispatch['target']['session_id'];seq=int(db.execute("SELECT max(seq) FROM ij_frame WHERE session_id=? AND direction='w2c'",(sid,)).fetchone()[0])+1
    frame=E.frame(dict(b,device_id=None),'CLOSE_GATE_ACK','fresh.close.ack',seq,dict(close_id=newcid,closed_device_ids=[c['device']]),dispatch['dispatch_id']);raw=M.raw(frame)
    A.receive(db,newcid,len(raw).to_bytes(4,'big')+raw,'223',E.ref('synthetic.observer'));N.complete(db,newcid,'224')
    choices=[]
    for closeid,exitid in db.execute('SELECT close_id,exit_id FROM go_latest_close WHERE device_id=? ORDER BY close_id',(c['device'],)):
        choices.append(dict(kind='worker_ack',close_id=closeid) if exitid==fresh else dict(kind='supervisor_retired',close_id=closeid,completion_id='retired.current'))
    state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(c['device'],));auth=M.E.one(db,'SELECT * FROM go_authority WHERE device_id=?',(c['device'],))
    snapshot=dict(snapshot_id='recovery.snapshot',device_id=c['device'],exit_id=fresh,authority_state_id=auth['change_id'],control_state_id=state['change_id'],safety_revision=P.u(int(db.execute('SELECT max(revision) FROM go_hazard WHERE device_id=?',(c['device'],)).fetchone()[0])+1),authorization_ref='synthetic.authorization',resource_ref='synthetic.resources',run_snapshot_ref='synthetic.runs',command_snapshot_ref='synthetic.commands',time_snapshot_ref='synthetic.time',sampled_tick=P.u(250),expires_tick=P.u(300),provider_ref='synthetic.provider',evidence_digest=M.F.digest({'synthetic_snapshot':True}),evidence_body=M.raw({'synthetic_snapshot':True}))
    return db,connections,eid,fresh,newcid,snapshot,choices
def run():
    checks=[];connections=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def snap(c):return T.T.T.T.T.V.SC.snapshot(c)
    def fork(c):
        x=sqlite3.connect(':memory:',isolation_level=None);c.backup(x);x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON');connections.append(x);return x
    def denied(n,fn):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error,D.C.I.ClockIngressStop):check(n)
        else:raise AssertionError('应拒绝:'+n)
    try:
        db,others,eid,fresh,cid,snapshot,choices=fixture();connections.extend(others);base=fork(db);provider=E.ref('synthetic.snapshot.provider')
        def complete(c,**kw):return Y.complete(c,'recovery.mixed',snapshot,[],choices,'251',provider,**kw)
        value,valid,writes=complete(db)
        check('261表混合依据恢复seal',valid and len(snap(db))==261 and sorted(t['kind'] for t in value['targets'])==['supervisor_retired','worker_ack'])
        check('完整原件查询',Y.read(db,'recovery.mixed')==value)
        check('仅一项进入旧ACK目标表',db.execute("SELECT count(*) FROM go_recovery_target WHERE recovery_id='recovery.mixed'").fetchone()[0]==1)
        check('退役分支独立存储',db.execute("SELECT count(*) FROM gr_retired_target WHERE recovery_id='recovery.mixed'").fetchone()[0]==1)
        old=snap(db);check('重复查原不刷新',complete(db)==(value,True,[]) and snap(db)==old)
        for i in range(len(writes)):
            x=fork(base);before=snap(x);denied('逐写异常:'+str(i),lambda:complete(x,fail_after=i));check('逐写全库回滚:'+str(i),snap(x)==before)
        class Omit:
            def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
            def __getattr__(self,k):return getattr(self.c,k)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
                return self.c.execute(sql,args)
        for table in set(writes):
            x=fork(base);before=snap(x);proxy=Omit(x,table);denied('缺写:'+table,lambda:complete(proxy));check('缺写全库回滚:'+table,proxy.hit>0 and snap(x)==before)
        class CommitFault:
            def __init__(self,c,committed):self.c=c;self.committed=committed
            def __getattr__(self,k):return getattr(self.c,k)
            def commit(self):
                if self.committed:self.c.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation_failure')
        for committed in (False,True):
            x=fork(base);before=snap(x);denied('提交观察故障:'+str(committed),lambda:complete(CommitFault(x,committed)))
            if committed:
                after=snap(x);check('已提交查原无重复写',complete(x)==(value,True,[]) and snap(x)==after)
            else:check('未提交完整回滚',snap(x)==before)
        for name,selected in [('漏ACK',[t for t in choices if t['kind']!='worker_ack']),('漏退役',[t for t in choices if t['kind']!='supervisor_retired']),('重复',choices+[choices[0]]),('历史失效完成',[dict(t,completion_id='retired.initial') if t['kind']=='supervisor_retired' else t for t in choices]),('新出口借退役',[dict(kind='supervisor_retired',close_id=t['close_id'],completion_id='retired.current') for t in choices])]:
            x=fork(base);before=snap(x);denied('无效目标集合:'+name,lambda:Y.complete(x,'recovery.mixed',snapshot,[],selected,'251',provider));check('集合拒绝完整回滚:'+name,snap(x)==before)
        for name,change in [('过期边界',dict(expires_tick=P.u(251))),('旧退役出口',dict(exit_id=eid)),('错设备',dict(device_id='dev.2')),('错误安全代次',dict(safety_revision=P.u(0)))]:
            x=fork(base);before=snap(x);s=dict(snapshot,**change);denied('快照拒绝:'+name,lambda:Y.complete(x,'recovery.mixed',s,[],choices,'251',provider));check('快照拒绝完整回滚:'+name,snap(x)==before)
        for name,change in [('双分支',lambda t:t.update(retired_completion_ref=E.ref('wrong'))),('缺ACK',lambda t:t.pop('ack_ref')),('未知分支',lambda t:t.update(kind='unknown'))]:
            bad=copy.deepcopy(value);ack=next(t for t in bad['targets'] if t['kind']=='worker_ack');change(ack);denied('Schema二选一:'+name,lambda:Y.validate(bad))
        denied('重复不能换提供者',lambda:Y.complete(db,'recovery.mixed',snapshot,[],choices,'251',E.ref('changed.provider')))
        denied('重复不能刷新时刻',lambda:Y.complete(db,'recovery.mixed',snapshot,[],choices,'252',provider))
        db.execute('BEGIN');denied('外部事务不接管',lambda:complete(db));check('调用方事务保留',db.in_transaction);db.rollback()
        for target in ('retired','ack'):
            x=fork(db)
            if target=='retired':R.revoke(x,'exit_dev_2',{'reason':'synthetic sibling withdrawal'})
            else:
                aid=x.execute('SELECT adopted_ack_id FROM authorization_close_ack WHERE close_id=?',(cid,)).fetchone()[0];proof=M.raw({'reason':'synthetic ACK withdrawal'})
                N.transaction(x,lambda:x.execute(*I('go_revocation',kind='close_ack',object_id=aid,reason_body=proof,audit_body=proof)))
            check('撤回使恢复资格失效:'+target,not Y.current(x,'recovery.mixed'))
            before=snap(x);check('撤回后仍查历史且无写:'+target,complete(x)==(value,False,[]) and snap(x)==before)
            denied('撤回后新恢复ID不能绕过:'+target,lambda:Y.complete(x,'recovery.retry',dict(snapshot,snapshot_id='retry.snapshot'),[],choices,'251',provider))
        for op in ('DELETE FROM gr_retired_target','UPDATE gr_retired_target SET completion_id=completion_id'):denied('分支原件不可变:'+op,lambda op=op:N.transaction(db,lambda:db.execute(op)))
        check('没有制造旧worker ACK',db.execute('SELECT count(*) FROM go_close_ack').fetchone()[0]==base.execute('SELECT count(*) FROM go_close_ack').fetchone()[0])
        check('恢复seal不直接开放或签发',not db.execute('SELECT 1 FROM ci_issue').fetchone() and [tuple(r) for r in db.execute('SELECT device_id,gate_state,holder_id FROM ct_current_state')]==[tuple(r) for r in base.execute('SELECT device_id,gate_state,holder_id FROM ct_current_state')])
        check('四个最终发送阻断保留',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'recovery-close-choice-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=261,recovery_seal_consumption_verified=True,full_reopen_verified=False,snapshot_provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
