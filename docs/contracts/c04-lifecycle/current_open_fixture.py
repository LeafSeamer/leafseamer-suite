"""当前Id格式的完整恢复测试数据；所有身份在首次登记前选择，不转换历史库。"""
import copy,sqlite3
from unittest.mock import patch
import check_continuation_storage as CS
import check_typed_seamer as TS
import check_typed_encoding_path as EP
import check_supervisor_retirement_adoption as SR
import check_gate_close as GC
import check_open_source as O
import check_arm_storage as A
import cancel_source_model as C
I=C.I;N=C.N;P=C.P;raw=C.raw;digest=C.digest
DEVICES=('dev_1','dev_2')

class SocketConnection(sqlite3.Connection):
    """模拟出口创建者在同一首次登记事务中登记socket观察值。"""
    def execute(self,sql,args=()):
        result=super().execute(sql,args)
        if sql.startswith('INSERT INTO ce_exit '):
            fields=[s.strip() for s in sql.split('(',1)[1].split(')',1)[0].split(',')];eid=args[fields.index('exit_id')]
            e=C.one(self,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,));sid='socket_'+eid
            value=C.M.sealed(dict(format_version='cancel-socket-registration/0.1.0-draft.1',scope=C.M.E.A.scope(self),exit=dict(writer_exit_id=eid,socket_instance_id=sid,**{k:e[k] for k in C.EXIT_FIELDS}),observer_ref=C.reference('synthetic_socket_observer',digest('synthetic_socket_observer'))),'registration_digest')
            C.validate('SocketRegistration',value)
            super().execute(*I('cs_socket',exit_id=eid,socket_instance_id=sid,registration_digest=value['registration_digest'],body=raw(value),audit_body=raw(value)))
        return result

def controller_seed(p,sql_factory):
    d=sqlite3.connect(':memory:',isolation_level=None,factory=SocketConnection);d.row_factory=sqlite3.Row
    d.execute('PRAGMA foreign_keys=ON');d.execute('PRAGMA recursive_triggers=ON');d.executescript(sql_factory().decode());C.D.install(d);C.install(d)
    sc=dict(authority_service_id=p['controller_authority'],database_instance_id=p['controller_database'])
    d.execute('INSERT INTO controller_scope VALUES(1,?,?,?)',(*CS.M.M.scope_key(sc),'controller-storage/0.1.0-draft.1'));d.execute('INSERT INTO cr_limit VALUES(1,8)')
    for steps in (CS.PRE.register(preparation=p['preparation_id'],generation=p['generation'],run=p['run_id']),CS.PRE.change()):
        chosen=[]
        for sql,args in steps:
            # 只替换旧夹具这两个显式设备输入；此时尚未写入任何准备原件。
            if sql.startswith('INSERT INTO cp_request_device '):args=tuple({'dev.1':DEVICES[0],'dev.2':DEVICES[1]}.get(v,v) if isinstance(v,str) else v for v in args)
            chosen.append((sql,args))
        CS.C.execute(d,CS.alter(chosen,dict(cp_request=dict(origin_database='db',mode='recovery',execution_id=p['execution_id'],request_digest=p['request_digest'],request_body=p['request_body']),cp_receipt=dict(request_digest=p['request_digest']))))
    devices=[]
    for dev in DEVICES:
        steps=[]
        for table,value in CS.U.bootstrap(d,holder=None):
            value={k:(v.replace('base','base.'+dev) if isinstance(v,str) else v) for k,v in value.items()}
            if table=='ct_change':value['device_id']=dev
            steps.append(I(table,**value))
        CS.C.execute(d,steps);devices.append(dict(device_id=dev,control_ref=CS.ref(sc,'base.'+dev,CS.U.DIGEST),authorization_ref=CS.ref(sc,'authorization.'+dev),action_set_ref=CS.ref(sc,'actions.'+dev)))
    return d,dict(controller_scope=sc,preparation_ref=CS.ref(sc,p['preparation_id'],p['request_digest']),recovery_grant_ref=CS.ref(sc,'grant.p',CS.PRE.DIGEST),devices=devices)

def seamer_fixture(*,sql_factory=TS.G.build,controller_factory=TS.T.G.controller_sql,expected_control=None):
    d,q,s,cds,ctx=TS.T.T.fixture(seamer_factory=sql_factory,controller_factory=controller_factory)
    old,_,_=TS.Q.J.fixtures();template=TS.Q.upgraded(old)['DISPATCH']['body']['request'];steps=copy.deepcopy(ctx['evaluations']['r0']['steps'])
    for n,step in enumerate(steps):
        fixed={k:copy.deepcopy(template[k]) for k in ('capability_version','expected_control','required_completion','preconditions','dispatch','evidence_timeout_ms')}
        if expected_control is not None:fixed['expected_control']=copy.deepcopy(expected_control)
        fixed.update(action_id='synthetic.set',device_id=DEVICES[0],parameters=dict(value=n));step.update(request=fixed,logical_action_id='action.'+str(n))
    plan=dict(ref=TS.T.T.ref(q['origin_scope'],'continued.plan',TS.T.M.M.digest(steps)),steps=steps)
    q=TS.T.M.M.seal(dict(q,continuation_plan_ref=plan['ref']),'request_digest');s.update(binding={k:q[k] for k in s['binding']},approval_subject=TS.T.M.M.approval_subject(q))
    for cd,cc in cds.values():cc.update(plan_ref=plan['ref'],approval_subject=TS.T.M.M.approval_subject(q),parameters_verified=True)
    a,rs=TS.T.T.issued(d,q,s,cds);TS.C.adopt(d,q,a,s,cds);TS.C.finish(d,q,s,cds)
    ctx['evaluations']['r0']['steps']=steps;ctx['continuation_plans']={'r0':plan};sha=TS.R.one(d,'ingress_listener','run_id','r0')['artifact_digest']
    ctx.update(clock={k:old['GUARD_INSTALL']['body']['guard'][k] for k in ('clock_domain_id','descriptor_digest')},program_current=True,clock_current=True,namespace_current=True,typed_programs={'r0':dict(artifact_ref=TS.M.ref('artifact',q['origin_scope'],'synthetic-artifact',sha),definition_version='1')},command_namespace=dict(context_id='typed-context',issuer_id='typed-issuer',issuer_epoch='issuer-1',principal_id='seamer-service',request_epoch='request-1'))
    return d,q,cds,ctx

def new_exit(db,oldid,descriptor):
    r,e=GC.R.runtime(db,oldid);r=copy.deepcopy(r);eid='domain_new_exit'
    row=dict(e,exit_id=eid,controller_boot_id='domain_new_controller',worker_boot_id='domain_new_worker',ipc_session_id='domain_new_ipc',device_session_id='domain_new_device',clock_domain_id=descriptor['clock_domain_id'],descriptor_digest=descriptor['descriptor_digest'])
    r['binding'].update(writer_exit_id=eid,**{k:row[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_session_id','clock_domain_id','descriptor_digest')})
    r['binding_id']='domain.new.runtime';r['intent'].update(launch_id='domain.new.launch',member_id='domain.new.member',supervisor_instance_id=descriptor['supervisor_instance_id'],runtime_generation=descriptor['runtime_generation'])
    r['admission_receipt'].update(launch_id='domain.new.launch',member_id='domain.new.member',member_boot_id=row['worker_boot_id'],launch_intent_digest=digest(r['intent']),domain_ref=GC.R.S.domain(descriptor));r=C.M.sealed(r,'binding_digest');row['runtime_binding_body']=raw(r);GC.R.validate('RuntimeExitBinding',r)
    ident='domain.new.protection';cut='domain.new.cut';close='registration.'+eid;body=raw(dict(synthetic_registration=eid))
    def register():
        db.execute(*I('ce_exit',**row));old=C.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(row['device_id'],));state=C.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(row['device_id'],))
        db.execute(*I('ct_change',**dict(old,change_id=ident,sequence=P.u(int(old['sequence'])+1),previous_id=old['change_id'],kind='gate_protect',state_id=ident,operation_id=None,offer_id=None,request_id=None,now_tick=P.u(6))))
        after={k:v for k,v in state.items() if k!='device_id'};after.update(change_id=ident,record_revision=P.u(int(state['record_revision'])+1),gate_state='protected');record=GC.T.T.S.control_body(db,after);after.update(record_digest=record['record_digest'],record_body=raw(record));db.execute(*I('ct_state',**after))
        db.execute(*I('go_close',prepare_cut_id=cut,close_id=close,device_id=row['device_id'],exit_id=eid,revision=P.u(1),protection_change_id=ident,gate_id=None,reason_ref='synthetic_new_domain',body=body,outbox_body=body,audit_body=body))
        head=db.execute('SELECT max(sequence) FROM pd_registration').fetchone()[0]
        db.execute(*I('pd_cut',cut_id=cut,kind='close',prepare_head=head,selected_tick=P.u(6),selector_digest=digest(dict(synthetic_registration=eid)),selector_body=body,control_id=None,cancel_id=None,run_id=None,close_id=close))
        db.execute(*I('pd_cut_commit',cut_id=cut,committed_tick=P.u(6),audit_body=body,outbox_body=body))
        db.execute(*I('ct_audit',change_id=ident,body=body));db.execute(*I('ct_outbox',change_id=ident,event_id=ident,body=body));db.execute(*I('ct_commit',change_id=ident))
    N.transaction(db,register);return eid

def fixture(before_restart=None,before_protection=None):
    original_preflight=A.M.preflight_step;source=SR.F.fixture;provider=EP.provider;protect=SR.P.apply
    def preflight(db,pid,rid,targets,ctx):
        for target in targets:target['controller_scope']['database_instance_id']='controller_db'
        ctx['target_manifest_digest']=A.P.digest(A.P.canonical(targets));return original_preflight(db,pid,rid,targets,ctx)
    def awaiting(db,launch='one',sup='old'):
        db.execute("UPDATE launch_state SET state='awaiting_bootstrap' WHERE supervisor_id=? AND launch_id=?",(sup,launch))
        db.execute('INSERT INTO bootstrap_challenge VALUES(?,?,?,?,?,?,?,?)',(sup,launch,'bootstrap.'+sup+'.'+launch,'boot_'+sup+'_'+launch,'channel.'+sup+'.'+launch,'10','20','transcript.hash'));SR.F.J.observation(db,'process.'+sup+'.'+launch,'process_instance',launch,sup,sup)
    def source_fixture(*args,**kw):
        return source(*args,**dict(kw,mutate=lambda kind,b:b.update(member_boot_id='boot_old_'+b['launch_id']) if kind=='receipt' else None))
    def encoding_provider(db,command,attempt,eid):
        v=provider(db,command,attempt,eid);v['socket_instance_id']=C.one(db,'SELECT socket_instance_id FROM cs_socket WHERE exit_id=?',(eid,))['socket_instance_id'];return v
    def protection(db,*args,**kw):
        if before_protection is not None:before_protection(db)
        return protect(db,*args,**kw)
    with patch.object(A.M,'preflight_step',side_effect=preflight),patch.object(CS,'controller_seed',side_effect=controller_seed),patch.object(TS,'fixture',side_effect=seamer_fixture),patch.object(SR.F,'fixture',side_effect=source_fixture),patch.object(SR.F.J,'awaiting',side_effect=awaiting),patch.object(EP,'provider',side_effect=encoding_provider),patch.object(SR.P,'apply',side_effect=protection):
        db,connections,sd,domain,eid,cid=SR.fixture(worker_devices=list(DEVICES))
    GC.T.T.T.X.install(db)
    for exitid in ('exit_dev_1','exit_dev_2'):
        binding=GC.R.runtime(db,exitid)[0]['binding']
        if not db.execute('SELECT 1 FROM authorization_close_dispatch d JOIN go_latest_close x USING(close_id) WHERE x.exit_id=?',(exitid,)).fetchone():
            fault=SR.D.C.I.ingest(db,binding,b'{');plan=SR.D.C.prepare(db,binding,fault['fault_ref']);state=C.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(binding['device_id'],))
            timing=dict(device_id=binding['device_id'],clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns='200',source_ref=GC.E.ref('synthetic.retirement.tick'))
            protection,_=SR.P.apply(db,SR.D.C.pref(plan),[timing]);othercid=protection['exits'][0]['close_id'];SR.D.queue(db,SR.D.pref(protection),othercid,'201')
    if before_restart is not None:before_restart(db)
    GC.Y.install(db);GC.Z.install(db)
    for e in ('exit_dev_1','exit_dev_2'):GC.R.adopt(db,e,sd,'old','retirement.complete',domain,'3')
    GC.X.complete(db,eid,'healthy.retired');descriptor=GC.R.read(db,eid)['source_bundle']['evaluator_descriptor'];GC.Z.restart(db,DEVICES[0],'healthy.restart',descriptor,'5',GC.E.ref('synthetic.provider'))
    eid=new_exit(db,eid,descriptor);GC.T.Q.install(db);ctx=dict(exit=eid,device=DEVICES[0],prefix='healthy.worker')
    N.transaction(db,lambda:[db.execute(sql,tuple('ipc/0.14.0-continuation-draft.1' if v=='ipc/0.13.0-journal-draft.1' else v for v in args)) for sql,args in GC.O.session(db,ctx,7)])
    GC.D.install(db);cid='registration.'+eid;request,_=GC.D.queue(db,cid,'8');GC.D.begin_write(db,cid,'9');binding=GC.R.runtime(db,eid)[0]['binding'];sid=request['target']['session_id'];original=GC.D.read(db,cid)[1]
    N.transaction(db,lambda:db.execute(*I('ij_write_result',frame_id=original['frame_id'],state='written',completed_tick=P.u(9),written_bytes=original['wire_length'],end_id=None,result_body=raw(dict(synthetic='full_write_observation')))))
    frame=O.E.frame(dict(binding,device_id=None),'CLOSE_GATE_ACK','source.close.ack',O.F.seq(db,sid,'w2c'),dict(close_id=cid,closed_device_ids=[DEVICES[0]]),request['dispatch_id']);body=raw(frame)
    GC.A.receive(db,cid,len(body).to_bytes(4,'big')+body,'10',O.E.ref('synthetic.observer'));N.complete(db,cid,'11');O.F.install(db)
    selections=[dict(kind='worker_ack',close_id=close) if e==eid else dict(kind='supervisor_retired',close_id=close,completion_id='healthy.retired') for close,e in db.execute('SELECT close_id,exit_id FROM go_latest_close WHERE device_id=? ORDER BY close_id',(DEVICES[0],))]
    return db,connections,eid,cid,sid,selections
