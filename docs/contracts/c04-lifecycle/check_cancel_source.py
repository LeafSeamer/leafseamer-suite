"""完整取消原件的结构、数据库来源与故障验收；来源授权仍为合成。"""
import argparse,copy,hashlib,json,sqlite3,re
from jsonschema.exceptions import ValidationError
import cancel_source_model as M
import check_command_deny as T
import check_continuation_binding as W
X=T.X;I=X.I;N=M.N;P=M.P;HERE=M.G.HERE;ROOT=T.ROOT;raw=M.raw;digest=M.digest;seal=M.M.sealed
LOCAL=('build_cancel_source.py','cancel-source.schema.json','cancel_source.sql','cancel_source_model.py','check_cancel_source.py','CANCEL_SOURCE.md')
def inputs():return list(dict.fromkeys(T.inputs()+M.G.SOURCES+[HERE/n for n in LOCAL]))
def ref(name):return M.reference(name,digest(name))
def data(step):
    # 仅测试夹具在首次登记前选择合法ID；不转换任何已经落库的身份或BODY。
    values=[v.replace('.', '_') if isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_.-]+',v) else v for v in step[1]]
    return step[0].split(' ',3)[2],dict(zip(step[0].split('(',1)[1].split(')',1)[0].split(','),values))
def execute_steps(db,steps):X.F.tx(db,[I(table,**row) for table,row in map(data,steps)])
def states(steps,scope,db):
    mapped={};out=[]
    for table,r in map(data,steps):
        if table=='cm_revision':
            ids=sorted(v['attempt_id'] for t,v in map(data,steps) if t=='cm_revision_attempt' and v['command_id']==r['command_id'] and v['revision']==r['revision'])
            v=dict(command_id=r['command_id'],scope=scope,revision=str(int(r['revision'])),phase=r['phase'],outcome=r['outcome'],effect_status=r['effect_status'],resource_status=r['resource_status'],automation_continuation='paused_latched' if r['paused_latched'] else 'eligible',reason_code=None,terminal_revision=str(int(r['terminal_revision'])) if r['terminal_revision'] else None,resolution_ref=None,completion_evidence_refs=[],resource_evidence_refs=[],attempt_ids=ids)
            M.validate('CommandState',v);mapped[r['revision']]=v
    for table,r in map(data,steps):
        revision=r.get('revision') if table in ('cm_revision','cv_record') else r.get('state_revision')
        if table=='cm_revision':
            r.update(state_body=raw(mapped[revision]),state_digest=digest(mapped[revision]),transition_digest=digest(mapped[revision]))
            if r['previous_revision'] is not None:r['previous_digest']=M.one(db,'SELECT state_digest FROM cm_revision WHERE command_id=? AND revision=?',(r['command_id'],r['previous_revision']))['state_digest']
        if table=='cm_validation':
            match=next((v for t,v in map(data,steps) if t=='cm_revision' and v['validation_id']==r['validation_id']),None)
            if match:r.update(subject_digest=digest(mapped[match['revision']]),source_body=raw(mapped[match['revision']]))
        if table in ('cv_record','cv_snapshot'):r['state_digest']=digest(mapped[revision])
        out.append(I(table,**r))
    return out,mapped
def fixture(level='accepted',register=True):
    c=sqlite3.connect(':memory:',isolation_level=None);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');c.executescript(X.G.build().decode())
    scope=dict(authority_service_id='controller',database_instance_id='database_1');c.execute("INSERT INTO controller_scope VALUES(1,'controller','database_1','controller-storage/0.1.0-draft.1')")
    execute_steps(c,[X.F.A.namespace()]);execute_steps(c,X.F.P.register());execute_steps(c,X.F.P.change());M.D.install(c);M.install(c)
    base=W.upgraded(W.J.fixtures()[0]);permit=copy.deepcopy(base['DISPATCH']['body']['permit']);clock={k:permit[k] for k in ('clock_domain_id','descriptor_digest')}
    exits={}
    for eid in ('exit_0','exit_1'):
        step=X.extra([X.F.exit_step(eid)],'ce_exit',**clock)[0];execute_steps(c,[step])
        e=M.one(c,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,));exits[eid]=dict(writer_exit_id=eid,socket_instance_id='socket_'+eid,**{k:e[k] for k in M.EXIT_FIELDS})
        if register:M.register_socket(c,eid,'socket_'+eid,ref('observer'))
    initial=X.extra(X.V.public(X.C.initial(),1),'ce_command',origin='manual',prep_key=None,receipt_id=None);execute_steps(c,states(initial,scope,c)[0])
    if level=='initial':return c,dict(scope=scope,exits=exits,frames=base)
    execute_steps(c,states(X.V.public(X.C.prepare(),2),scope,c)[0])
    ex=exits['exit_0'];tx=permit['transmission'];intent=tx['intent']
    replacements=dict(permit_id='permit_1',command_id='command_one',attempt_id='a',**{k:ex[k] for k in M.EXIT_FIELDS})
    for key,value in replacements.items():
        if key in permit:permit[key]=value
        if key in intent:intent[key]=value
    packet=seal(dict(packet_id='pkt',command_id='command_one',attempt_id='a',primitive_id='ordinary_primitive',writer_exit_id='exit_0',device_session_id=ex['device_session_id'],socket_instance_id=ex['socket_instance_id'],protocol_session=None,wire_packet_id=None,tracking_ids=[],immutable_bytes_ref=dict(object_id='ordinary_bytes',digest=digest('bytes')),byte_length=1,sha256=digest('bytes'),transport_profile_ref=dict(object_id='transport',digest=digest('transport')),primitive_plan_ref=dict(object_id='plan',digest=digest('plan'))),'packet_digest')
    tx.update(packet_ref=dict(packet_id='pkt',packet_digest=packet['packet_digest']),primitive_id=packet['primitive_id'],initial_permit_id='permit_1',issued_revision='1');tx['send_window'].update(clock)
    M.validate('TransmissionPermit',permit);M.validate('S9__TransportPacket',packet)
    dispatch=X.Q.ordinary(X.V.public(X.C.dispatch(),3));dispatch=X.extra(dispatch,'ce_packet',primitive_id=packet['primitive_id'],packet_body=raw(packet));dispatch=X.extra(dispatch,'ce_permit',permit_body=raw(permit));dispatch=X.extra(dispatch,'ce_transmission_commit',dispatch_intent_body=raw(intent));execute_steps(c,states(dispatch,scope,c)[0])
    if level=='dispatched':return c,dict(scope=scope,exits=exits,frames=base)
    steps,after=states(X.V.cancel(4,attempts=('a',),permits=('permit_1',),cut=1,state_args=X.V.SENT),scope,c)
    ns=M.one(c,'SELECT * FROM ca_namespace WHERE namespace_id=\'ns\'');before=N.transaction(c,lambda:M.state(c,'command_one',P.u(3)))
    content=dict(scope=scope,command_id='command_one',expected_state_ref=M.reference('command_one',digest(before),'3'),reason='synthetic cancellation')
    identity=dict(key=dict(target_scope=scope,**{k:ns[k] for k in ('issuer_id','issuer_epoch','principal_id','request_epoch')},operation_id='cancelCommand',idempotency_key='idem_cancel'),request_digest=digest(content))
    op=seal(dict(cancellation_id='cancel',scope=scope,command_id='command_one',revision='1',identity=identity,state='requested',mode='cooperative',future_writes='pending',command_state_ref=M.reference('command_one',digest(after[P.u(4)]),'4'),evidence_refs=[],reason_code=None),'operation_digest')
    receipt=seal(dict(identity=identity,command_id='command_one',scope=scope,cancellation_id='cancel',initial_operation_ref=M.reference('cancel',op['operation_digest']),accepted_state_ref=content['expected_state_ref']),'receipt_digest')
    policy=seal(dict(policy_id='cancel_policy',revision='1',mode='cooperative',procedure_ref=ref('stop'),completion_policy_ref=ref('completion'),release_policy_ref=ref('release'),resource_keys=['device'],max_transmissions=4,allow_protocol_resend=True,application_attempts=1),'policy_digest')
    binding=dict(scope=scope,cancellation_id='cancel',parent_command_id='command_one',initial_operation_ref=receipt['initial_operation_ref'],identity=identity,mode='cooperative',policy_ref=M.reference(policy['policy_id'],policy['policy_digest']))
    targets=[seal(dict(exit=exits[eid],ordinary_attempt_ids=['a'],ordinary_transmissions=[tx] if eid=='exit_0' else [],cancel_prepare_ids=[],cancel_transmissions=[]),'target_digest') for eid in ('exit_0','exit_1')]
    cut=seal(dict(cut_id='ordinary',binding=binding,stage='ordinary',previous_cut_ref=None,issued_revision='1',deny_revision='1',targets=targets),'cut_digest')
    for name,value in [('CancelContent',content),('CancelOperation',op),('CancelReceipt',receipt),('CancelPolicy',policy),('CancelCut',cut)]:M.validate(name,value)
    steps=X.extra(steps,'cv_cancel_key',request_digest=digest(content),content_body=raw(content));steps=X.extra(steps,'cv_cancel',mode='cooperative',accepted_state_digest=digest(before),cut_digest=cut['cut_digest'],cut_body=raw(cut),policy_body=raw(policy))
    steps=X.extra(steps,'cv_cancel_revision',operation_digest=op['operation_digest'],operation_body=raw(op));steps=X.extra(steps,'cv_cancel_receipt',initial_operation_digest=op['operation_digest'],receipt_digest=receipt['receipt_digest'],receipt_body=raw(receipt));execute_steps(c,steps)
    context=dict(scope=scope,exits=exits,frames=base,cut=cut,binding=binding)
    if level=='accepted':return c,context
    M.capture(c,'cancel','ordinary','ordinary')
    if level=='ordinary':return c,context
    for eid in ('exit_0','exit_1'):execute_steps(c,[X.attempt(eid=eid)]);execute_steps(c,X.ack(eid=eid.replace('_','.')))
    execute_steps(c,X.closure())
    ex=exits['exit_0'];frame=base['DISPATCH_CANCEL'];cancel=copy.deepcopy(frame['body']['permit']);packet=copy.deepcopy(frame['body']['packet'])
    execution=M.reference('execution_cancel',digest('execution_cancel'));packet.update(packet_id='packet_cancel',execution_ref=execution,cancellation_id='cancel',parent_command_id='command_one',primitive_id='primitive_cancel',exit=ex)
    payload=bytes.fromhex(frame['body'].get('bytes_hex','0304'));sha='sha256:'+hashlib.sha256(payload).hexdigest();packet.update(sha256=sha,byte_length=len(payload),immutable_bytes_ref=dict(object_id='cancel_bytes',digest=sha));packet=seal(packet,'packet_digest')
    cancel.update(permit_id='cancel_1',transmission_id='cancel_transmission',execution_ref=execution,cancellation_id='cancel',parent_command_id='command_one',primitive_id='primitive_cancel',packet_ref=dict(packet_id=packet['packet_id'],packet_digest=packet['packet_digest']),exit=ex,initial_permit_id='cancel_1',issued_revision='2');cancel['send_window'].update(clock)
    M.validate('S8__Transmission',cancel);M.validate('S8__Packet',packet)
    execute_steps(c,X.extra([X.prepare()],'cc_prepare',execution_digest=execution['digest']))
    execute_steps(c,X.extra([X.packet()],'cc_packet',packet_digest=packet['packet_digest'],packet_bytes=payload,packet_body=raw(packet)))
    steps=X.dispatch();steps=X.extra(steps,'ci_cancel_transmission',execution_digest=execution['digest'],packet_digest=packet['packet_digest'],transmission_body=raw(cancel));steps=X.extra(steps,'ci_cancel_commit',packet_bytes=payload,dispatch_intent_body=raw(cancel));execute_steps(c,steps)
    context.update(cancel=cancel,cancel_packet=packet)
    return c,context

def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def new(level='accepted',**kw):d,c=fixture(level,**kw);dbs.append(d);return d,c
    def clone(d):
        c=sqlite3.connect(':memory:',isolation_level=None);d.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');dbs.append(c);return c
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,sqlite3.Error,ValidationError) as e:
            messages=[]
            while e:
                assert isinstance(e,(ValueError,RuntimeError,sqlite3.Error,ValidationError)),type(e)
                messages.append(str(e));e=e.__cause__
            if reason:assert any(reason in x for x in messages),(name,messages)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    def atomic(seed,fn,label):
        probe=clone(seed);_,writes=fn(probe)
        class Omit:
            def __init__(self,db,index):self.db=db;self.index=index;self.count=0
            def __getattr__(self,name):return getattr(self.db,name)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '):
                    current=self.count;self.count+=1
                    if current==self.index:return self.db.execute('SELECT 1 WHERE 0')
                return self.db.execute(sql,args)
        for i in range(len(writes)):
            d=clone(seed);before=X.F.snapshot(d);denied(label+'逐写故障:'+str(i),lambda:fn(d,i),'injected');check(label+'回滚:'+str(i),X.F.snapshot(d)==before)
            d=clone(seed);before=X.F.snapshot(d);denied(label+'缺写:'+str(i),lambda:fn(Omit(d,i)));check(label+'缺写回滚:'+str(i),X.F.snapshot(d)==before)
    try:
        M.Draft202012Validator.check_schema(M.SCHEMA);check('Schema生成无漂移',(HERE/'cancel-source.schema.json').read_bytes()==M.G.encoded());M.validate('CancelContent',dict(scope=dict(authority_service_id='controller',database_instance_id='database'),command_id='command',expected_state_ref=ref('state'),reason=''))
        d,c=new();check('121表非空来源',len(X.F.snapshot(d))==121 and N.transaction(d,lambda:M.admission(d,'cancel'))[0]==c['binding'])
        denied('受理pending不能投影空快照',lambda:N.transaction(d,lambda:M.snapshot_body(d,'dev_1')),'command_deny_cut_pending')
        atomic(d,lambda x,i=None:M.capture(x,'cancel','ordinary','ordinary',i),'ordinary')
        cut,writes=M.capture(d,'cancel','ordinary','ordinary');check('普通切点原件完整等于受理',cut==c['cut'] and len(cut['targets'])==2 and len(cut['targets'][0]['ordinary_transmissions'])==1)
        before=X.F.snapshot(d);check('重入只查原',M.capture(d,'cancel','ordinary','ordinary')==(cut,[]) and X.F.snapshot(d)==before)
        denied('同ID不同阶段拒绝',lambda:M.capture(d,'cancel','ordinary','all'),'cancel_cut_replay_conflict')
        denied('事务外查原拒绝',lambda:M.read_cut(d,'ordinary'),'cancel_source_transaction_required')
        seed,c=new('sent');atomic(seed,lambda x,i=None:M.capture(x,'cancel','all','all',i),'all')
        all_cut,_=M.capture(seed,'cancel','all','all');check('all纳入取消准备与取消许可',all_cut['deny_revision']=='2' and all_cut['targets'][0]['cancel_prepare_ids']==['prepare_cancel'] and all_cut['targets'][0]['cancel_transmissions']==[c['cancel']])
        body=N.transaction(seed,lambda:M.snapshot_body(seed,'dev_1'));check('非空完整命令快照正文符合当前IPC',body['snapshot_revision']=='3' and body['entries']==[dict(cancellation_id='cancel',parent_command_id='command_one',stage='all',deny_revision='2',cut_ref=M.reference('all',all_cut['cut_digest']))])
        historical=N.transaction(seed,lambda:M.snapshot_body(seed,'dev_1','2'));check('历史水位保留ordinary而非回填all',historical['entries'][0]['stage']=='ordinary' and historical['entries'][0]['cut_ref']==M.reference('ordinary',c['cut']['cut_digest']))
        check('零水位可读历史空集合',N.transaction(seed,lambda:M.snapshot_body(seed,'dev_1','0'))['entries']==[])
        check('all保留ordinary原引用',all_cut['previous_cut_ref']==M.reference('ordinary',c['cut']['cut_digest']) and N.transaction(seed,lambda:M.read_cut(seed,'ordinary'))==c['cut'])
        execute_steps(seed,[X.revoke('close_ordinary')]);check('关闭撤回不删除历史cut或拒绝墓碑',N.transaction(seed,lambda:M.read_cut(seed,'all'))==all_cut and M.D.head(seed,'dev_1')=='3')
        # 错配在隔离数据库中构造；原件读取不依赖仅有自摘要的正文。
        def corrupt(db,table,key,value,column,fn,digest_column=None,digest_key=None):
            for row in db.execute("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name=? AND sql LIKE '%BEFORE UPDATE%'",(table,)).fetchall():db.execute('DROP TRIGGER '+row[0])
            original=M.one(db,'SELECT * FROM '+table+' WHERE '+key+'=?',(value,));body=json.loads(original[column]);fn(body)
            if digest_key:body=seal(body,digest_key)
            assignments={column:raw(body)}
            if digest_column:assignments[digest_column]=body[digest_key]
            db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in assignments)+' WHERE '+key+'=?',(*assignments.values(),value))
        cases=[('受理请求错命令','cv_cancel_key','key_id','key_cancel','content_body',lambda b:b.update(command_id='other'),None,None),
          ('初始operation错身份','cv_cancel_revision','cancellation_id','cancel','operation_body',lambda b:b['identity']['key'].update(principal_id='other'),'operation_digest','operation_digest'),
          ('Receipt错前态','cv_cancel_receipt','cancellation_id','cancel','receipt_body',lambda b:b['accepted_state_ref'].update(revision='2'),'receipt_digest','receipt_digest'),
          ('policy错mode','cv_cancel','cancellation_id','cancel','policy_body',lambda b:b.update(mode='before_dispatch_only',procedure_ref=None,allow_protocol_resend=False),None,'policy_digest'),
          ('许可错源intent','ce_transmission_commit','permit_id','permit_1','dispatch_intent_body',lambda b:b.update(command_id='other'),None,None),
          ('许可外层错worker','ce_permit','permit_id','permit_1','permit_body',lambda b:b.update(worker_boot_id='other'),None,None),
          ('普通发送窗口换时钟','ce_permit','permit_id','permit_1','permit_body',lambda b:b['transmission']['send_window'].update(clock_domain_id='clock_'+'0'*64),None,None),
          ('切点漏目标并重算摘要','cc_cut','cut_id','ordinary','cut_body',lambda b:b['targets'].pop(),'cut_digest','cut_digest'),
          ('目标偷换socket并重算摘要','cc_target','exit_id','exit_0','target_body',lambda b:b['exit'].update(socket_instance_id='other'),'target_digest','target_digest'),
          ('packet摘要重算也不能换socket','ce_packet','packet_id','pkt','packet_body',lambda b:b.update(socket_instance_id='other'),None,'packet_digest')]
        for name,table,key,value,column,fn,dc,dk in cases:
            d=clone(seed);corrupt(d,table,key,value,column,fn,dc,dk);denied(name,lambda:N.transaction(d,lambda:M.read_cut(d,'all')))
        for field,value in [('execution_ref',ref('other')),('issued_revision','1'),('parent_command_id','other')]:
            d=clone(seed);corrupt(d,'ci_cancel_transmission','permit_id','cancel_1','transmission_body',lambda b:b.update({field:value}));denied('取消传输错绑:'+field,lambda:N.transaction(d,lambda:M.read_cut(d,'all')))
        d=clone(seed)
        for row in d.execute("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name='cc_packet' AND sql LIKE '%BEFORE UPDATE%'").fetchall():d.execute('DROP TRIGGER '+row[0])
        d.execute("UPDATE cc_packet SET packet_bytes=x'00' WHERE packet_id='packet_cancel'");denied('取消字节不匹配拒绝',lambda:N.transaction(d,lambda:M.read_cut(d,'all')),'cancel_transmission_packet')
        d,c=new('initial');before=X.F.snapshot(d);check('出口重入查原',M.register_socket(d,'exit_0','socket_exit_0',ref('observer'))[1]==[] and X.F.snapshot(d)==before)
        denied('出口不能换socket',lambda:M.register_socket(d,'exit_0','other',ref('observer')),'cancel_socket_replay_conflict')
        for sql in ('DELETE FROM cs_socket','UPDATE cs_socket SET socket_instance_id=socket_instance_id'):denied('出口绑定不可变:'+sql,lambda sql=sql:d.execute(sql),'immutable_cancel_socket')
        late,c=new('dispatched',register=False);denied('准备后不能补出口身份',lambda:M.register_socket(late,'exit_0','socket_exit_0',ref('observer')),'cancel_socket_registered_too_late')
        old=T.fresh();dbs.append(old);M.install(old);X.F.tx(old,T.cancel());denied('旧占位受理不冒充完整原件',lambda:N.transaction(old,lambda:M.admission(old,'cancel')))
        class CommitFault:
            def __init__(self,db,committed):self.db=db;self.committed=committed
            def __getattr__(self,name):return getattr(self.db,name)
            def commit(self):
                if self.committed:self.db.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation')
        for committed in (False,True):
            d,c=new();before=X.F.snapshot(d);denied('提交观察丢失:'+str(committed),lambda:M.capture(CommitFault(d,committed),'cancel','ordinary','ordinary'))
            if committed:
                after=X.F.snapshot(d);check('提交观察丢失后只查原',M.capture(d,'cancel','ordinary','ordinary')==(c['cut'],[]) and X.F.snapshot(d)==after)
            else:check('提交前故障保留受理pending水位',X.F.snapshot(d)==before and M.D.head(d,'dev_1')=='1')
        d,c=new('sent');new_exit='exit_2';execute_steps(d,X.extra([X.F.exit_step(new_exit)],'ce_exit',**{k:c['exits']['exit_0'][k] for k in ('clock_domain_id','descriptor_digest')}));M.register_socket(d,new_exit,'socket_'+new_exit,ref('observer'))
        extended,_=M.capture(d,'cancel','all','all');check('all包含受理之后新登记出口',[t['exit']['writer_exit_id'] for t in extended['targets']]==['exit_0','exit_1','exit_2'])
        for name in ('CancelCut','SocketRegistration','CancelPolicy','CancelOperation'):
            sample={'CancelCut':all_cut,'SocketRegistration':json.loads(seed.execute("SELECT body FROM cs_socket LIMIT 1").fetchone()[0]),'CancelPolicy':json.loads(seed.execute('SELECT policy_body FROM cv_cancel').fetchone()[0]),'CancelOperation':json.loads(seed.execute('SELECT operation_body FROM cv_cancel_revision LIMIT 1').fetchone()[0])}[name]
            for key in sample:
                bad=copy.deepcopy(sample);del bad[key];denied('必填:'+name+':'+key,lambda name=name,bad=bad:M.validate(name,bad))
        for d in dbs:assert not d.in_transaction and not d.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for d in dbs:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'cancel-source-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),typed_cancel_cut_verified=True,command_snapshot_projection_verified=True,integrated_current_runtime_verified=False,command_snapshot_storage_verified=False,full_open_verified=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(raw(v))
        print(json.dumps({k:v for k,v in v.items() if k not in ('checks','inputs')}))
