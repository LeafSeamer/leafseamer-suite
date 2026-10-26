"""验证旧域大tick到新域小tick的快照排序与protected换域，不执行设备I/O。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_retired_close_set as T
import snapshot_domain_order_model as Z
Y=Z.Y;X=Z.X;R=Z.R;N=Z.N;M=Z.M;P=Z.P;S=Z.S;I=Z.I;HERE=Z.G.HERE;ROOT=HERE.parents[2]
def inputs():return T.inputs()+[HERE/n for n in ('build_recovery_close_choice.py','recovery-close-choice.sql','recovery-close-choice-layout.sql','recovery-close-choice.schema.json','recovery_close_choice_model.py','build_snapshot_domain_order.py','snapshot-domain-order.sql','snapshot-domain-order.schema.json','snapshot_domain_order_model.py','check_snapshot_domain_order.py','SNAPSHOT_DOMAIN_ORDER.md')]
def snapshot(db,ident,eid,tick):
    e=M.E.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,));device=e['device_id'];state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(device,));auth=M.E.one(db,'SELECT * FROM go_authority WHERE device_id=?',(device,))
    body=M.raw({'synthetic_snapshot':ident})
    row=dict(snapshot_id=ident,device_id=device,exit_id=eid,authority_state_id=auth['change_id'],control_state_id=state['change_id'],safety_revision=P.u(int(db.execute('SELECT max(revision) FROM go_hazard WHERE device_id=?',(device,)).fetchone()[0])),authorization_ref='synthetic.auth',resource_ref='synthetic.resource',run_snapshot_ref='synthetic.run',command_snapshot_ref='synthetic.commands',time_snapshot_ref='synthetic.time',sampled_tick=P.u(tick),expires_tick=P.u(int(tick)+100),provider_ref='synthetic.provider',evidence_digest=M.F.digest({'synthetic_snapshot':ident}),evidence_body=body)
    def write():db.execute(*I('go_snapshot',**row));db.execute(*I('go_snapshot_commit',snapshot_id=ident,audit_body=body))
    N.transaction(db,write);return row
def new_exit(db,oldid,descriptor):
    r,e=R.runtime(db,oldid);r=copy.deepcopy(r);eid='domain.new.exit';row=dict(e,exit_id=eid,controller_boot_id='domain.new.controller',worker_boot_id='domain.new.worker',ipc_session_id='domain.new.ipc',device_session_id='domain.new.device',clock_domain_id=descriptor['clock_domain_id'],descriptor_digest=descriptor['descriptor_digest'])
    r['binding'].update(writer_exit_id=eid,**{k:row[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_session_id','clock_domain_id','descriptor_digest')})
    r['binding_id']='domain.new.runtime';r['intent'].update(launch_id='domain.new.launch',member_id='domain.new.member',supervisor_instance_id=descriptor['supervisor_instance_id'],runtime_generation=descriptor['runtime_generation'])
    r['admission_receipt'].update(launch_id='domain.new.launch',member_id='domain.new.member',member_boot_id=row['worker_boot_id'],launch_intent_digest=M.F.digest(r['intent']),domain_ref=R.S.domain(descriptor));r=M.sealed(r,'binding_digest');row['runtime_binding_body']=M.raw(r);R.validate('RuntimeExitBinding',r)
    ident='domain.new.protection';cut='domain.new.cut';close='registration.'+eid;body=M.raw({'synthetic_registration':eid})
    def register():
        db.execute(*I('ce_exit',**row));old=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(row['device_id'],));state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(row['device_id'],))
        change=dict(old,change_id=ident,sequence=P.u(int(old['sequence'])+1),previous_id=old['change_id'],kind='gate_protect',state_id=ident,operation_id=None,offer_id=None,request_id=None,now_tick=P.u(6));db.execute(*I('ct_change',**change))
        after={k:v for k,v in state.items() if k!='device_id'};after.update(change_id=ident,record_revision=P.u(int(state['record_revision'])+1),gate_state='protected');record=S.control_body(db,after);after.update(record_digest=record['record_digest'],record_body=M.raw(record));db.execute(*I('ct_state',**after))
        db.execute(*I('go_close',prepare_cut_id=cut,close_id=close,device_id=row['device_id'],exit_id=eid,revision=P.u(1),protection_change_id=ident,gate_id=None,reason_ref='synthetic_new_domain',body=body,outbox_body=body,audit_body=body))
        head=db.execute('SELECT max(sequence) FROM pd_registration').fetchone()[0]
        db.execute(*I('pd_cut',cut_id=cut,kind='close',prepare_head=head,selected_tick=P.u(6),selector_digest=M.F.digest({'synthetic_registration':eid}),selector_body=body,control_id=None,cancel_id=None,run_id=None,close_id=close))
        db.execute(*I('pd_cut_commit',cut_id=cut,committed_tick=P.u(6),audit_body=body,outbox_body=body))
        db.execute(*I('ct_audit',change_id=ident,body=body));db.execute(*I('ct_outbox',change_id=ident,event_id=ident,body=body));db.execute(*I('ct_commit',change_id=ident))
    N.transaction(db,register);return eid
def run():
    checks=[];connections=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def snap(c):return T.T.T.T.T.V.SC.snapshot(c)
    def fork(c):
        x=sqlite3.connect(':memory:',isolation_level=None);c.backup(x);x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON');connections.append(x);return x
    def denied(n,fn):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error,N.C.I.ClockIngressStop):check(n)
        else:raise AssertionError('应拒绝:'+n)
    try:
        db,others,sd,domain,eid,cid=T.fixture();connections.extend(others);Y.install(db)
        snapshot(db,'old.high',eid,1000);before=snap(db)
        x=fork(db);x.execute('DROP VIEW go_current_snapshot');x.execute('CREATE VIEW go_current_snapshot AS SELECT * FROM go_snapshot')
        denied('布局漂移不猜装',lambda:Z.install(x));check('安装失败无附属表',not x.execute("SELECT 1 FROM sqlite_schema WHERE name='gso_order'").fetchone())
        Z.install(db)
        check('263表候选',len(snap(db))==263)
        check('安装不改历史快照',snap(db)['go_snapshot']==before['go_snapshot'])
        initial=Z.order(db,'old.high');check('既有同域严格排序回填',db.execute("SELECT snapshot_id FROM go_current_snapshot WHERE device_id='dev.1'").fetchone()[0]=='old.high')
        for oldid in ('exit_dev_1','exit_dev_2'):R.adopt(db,oldid,sd,'old','retirement.complete',domain,'3')
        X.complete(db,eid,'domain.retired');base=fork(db);descriptor=R.read(db,eid)['source_bundle']['evaluator_descriptor'];provider=N.E.ref('synthetic.domain.provider')
        def restart(c,**kw):return Z.restart(c,'dev.1','domain.restart',descriptor,'5',provider,**kw)
        value,writes=restart(db);state=M.E.one(db,"SELECT * FROM ct_current_state WHERE device_id='dev.1'");prior=M.E.one(base,"SELECT * FROM ct_current_state WHERE device_id='dev.1'")
        stable=('control_epoch','effective_version','reserved_version','mode','holder_issuer','holder_epoch','holder_id','pending_operation_id')
        check('换域保留控制归属与待决操作',all(state[k]==prior[k] for k in stable) and state['gate_state']=='protected')
        check('新域小tick不与旧域1000比较',value['selected_tick_ns']=='5' and value['new_clock_descriptor']['clock_domain_id']!=initial['binding']['clock_domain_id'])
        check('换域后旧快照不再当前',not db.execute("SELECT 1 FROM go_current_snapshot WHERE device_id='dev.1'").fetchone())
        before=snap(db);check('重复换域只查原',restart(db)==(value,[]) and snap(db)==before)
        denied('重复换域不刷新时间',lambda:Z.restart(db,'dev.1','domain.restart',descriptor,'6',provider))
        old_descriptor=R.read(db,eid)['source_bundle']['old_descriptor'];denied('不能回用旧域身份',lambda:Z.restart(db,'dev.1','domain.back',old_descriptor,'1001',provider))
        bad=copy.deepcopy(descriptor);bad['runtime_generation']='changed.generation'
        denied('描述符摘要篡改拒绝',lambda:Z.restart(db,'dev.1','domain.bad',bad,'6',provider))
        denied('同域不能伪装换域原件',lambda:Z.restart(db,'dev.1','domain.same',descriptor,'6',provider))
        x=fork(base);x.execute('BEGIN IMMEDIATE');denied('拒绝接管调用者事务',lambda:restart(x));check('调用者事务仍由调用者持有',x.in_transaction);x.rollback()
        for i in range(len(writes)):
            x=fork(base);before=snap(x);denied('逐写异常:'+str(i),lambda:restart(x,fail_after=i));check('逐写完整回滚:'+str(i),snap(x)==before)
        class Omit:
            def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
            def __getattr__(self,k):return getattr(self.c,k)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
                return self.c.execute(sql,args)
        for table in writes:
            x=fork(base);before=snap(x);proxy=Omit(x,table);denied('缺写:'+table,lambda:restart(proxy));check('缺写完整回滚:'+table,proxy.hit>0 and snap(x)==before)
        fresh=new_exit(db,eid,descriptor);snapshot(db,'new.small',fresh,7);current=Z.order(db,'new.small')
        check('新域7成为当前快照',db.execute("SELECT snapshot_id FROM go_current_snapshot WHERE device_id='dev.1'").fetchone()[0]=='new.small' and int(current['ordinal'])>int(initial['ordinal']))
        check('新域快照通过现有关系验证',db.execute("SELECT 1 FROM go_valid_snapshot WHERE snapshot_id='new.small'").fetchone() is not None)
        for ident,tick in [('new.equal',7),('new.rewind',6)]:
            before=snap(db);denied('同域非递增拒绝:'+ident,lambda:snapshot(db,ident,fresh,tick));check('失败不占提交序号:'+ident,snap(db)==before)
        snapshot(db,'new.next',fresh,8);check('同域递增精确推进序号',int(Z.order(db,'new.next')['ordinal'])==int(current['ordinal'])+1)
        for seed,expected in [('00000000009999999999','10000000000'),('09007199254740992999','9007199254740993000')]:
            x=fork(db);guard=x.execute("SELECT sql FROM sqlite_schema WHERE name='gso_order_u'").fetchone()[0]
            # 仅故障/边界夹具移到巨大序号；随后恢复真实不可变守卫。
            x.execute('DROP TRIGGER gso_order_u');x.execute("UPDATE gso_order SET ordinal=? WHERE snapshot_id='new.next'",(seed,));x.execute(guard)
            snapshot(x,'large.next',fresh,9);check('精确十进制进位:'+seed,Z.order(x,'large.next')['ordinal']==expected)
        x=fork(db);x.execute('DROP TRIGGER gso_order_u');x.execute("UPDATE gso_order SET ordinal='99999999999999999999' WHERE snapshot_id='new.next'");x.execute(guard);before=snap(x)
        denied('序号耗尽不回绕',lambda:snapshot(x,'overflow',fresh,9));check('耗尽整笔回滚',snap(x)==before)
        for ordinal in ('0','01','100000000000000000000'):
            bad=dict(current,ordinal=ordinal);denied('序号词法拒绝:'+ordinal,lambda bad=bad:Z.validate('SnapshotDomainOrder',bad))
        denied('旧域快照不能借大tick回流',lambda:snapshot(db,'old.late',eid,9999))
        x=fork(db);x.execute('DROP TRIGGER gso_snapshot_order');before=snap(x);denied('缺序号写入无法封存',lambda:snapshot(x,'missing.order',fresh,9));check('缺序号整笔回滚',snap(x)==before)
        for table in ('gso_order','gso_transition'):
            for op in ('DELETE FROM '+table,'UPDATE '+table+' SET '+('snapshot_id=snapshot_id' if table=='gso_order' else 'change_id=change_id')):denied('元数据不可变:'+op,lambda op=op:N.transaction(db,lambda:db.execute(op)))
        check('未生成恢复或发送许可',db.execute('SELECT count(*) FROM go_recovery_commit').fetchone()[0]==base.execute('SELECT count(*) FROM go_recovery_commit').fetchone()[0] and not db.execute('SELECT 1 FROM ci_issue').fetchone())
        check('四个最终阻断保留',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'snapshot-domain-order-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=263,cross_domain_snapshot_order_verified=True,protected_domain_transition_verified=True,full_cross_domain_recovery_verified=False,clock_provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
