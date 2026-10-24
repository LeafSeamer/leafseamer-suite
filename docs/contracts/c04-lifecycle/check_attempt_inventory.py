"""238表固定库存的事务封存与历史来源检查；不运行网络或设备。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_attempt_projection as T
import attempt_inventory_model as S
import check_continuation_binding as W
M=S.M;A=S.A;E=S.E;G=S.G;P=S.P;I=S.I;R=S.R;HERE=G.HERE;ROOT=T.ROOT;SC=T.T.T.SC

def fixture():
    d,cds,items,c=T.T.T.fixture(controller_factory=G.build);item=items[0];cd=item[0]
    adjudication=M.decide(*item);cmd=adjudication['command_ref']['object_id'];auth=T.T.T.reader(item)
    return d,cds,cd,cmd,auth
def provider(state,valid=()):return dict(scope=state['scope'],state_ref=M.V.state_ref(state),originals_verified=True,redaction_verified=True,decisions_verified=True,time_verified=True,
    valid_decision_refs=list(valid),time_projections=[],max_members=32,max_inventory_bytes=65536,max_bundle_bytes=262144)

def register_exit(db,device):
    """新出口按既有登记关闭义务与零准备cut同事务登记，不跳过闸守卫。"""
    previous=P.rows(db,'SELECT * FROM ct_current_change WHERE device_id=?',(device,))[0]
    state=P.rows(db,'SELECT * FROM ct_current_state WHERE device_id=?',(device,))[0]
    cid='inventory_registration';eid='unassigned_exit';close='registration.'+eid;cut='inventory_registration_cut';now=M.U(str(int(previous['now_tick'])+1));b=b'{"synthetic":true}'
    change=dict(previous,change_id=cid,sequence=M.U(str(int(previous['sequence'])+1)),previous_id=previous['change_id'],kind='gate_protect',state_id=cid,operation_id=None,offer_id=None,request_id=None,now_tick=now)
    next_state={k:v for k,v in state.items() if k!='device_id'};next_state.update(change_id=cid,record_revision=M.U(str(int(state['record_revision'])+1)),gate_state='protected')
    head=db.execute("SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration").fetchone()[0]
    return [I('ce_exit',exit_id=eid,device_id=device,controller_boot_id='new_controller',worker_boot_id='new_worker',ipc_session_id='new_ipc',device_session_id='new_device',clock_domain_id='new_clock',descriptor_digest=M.digest('new_clock'),runtime_binding_body=b),
        I('ct_change',**change),I('ct_state',**next_state),
        I('go_close',prepare_cut_id=cut,close_id=close,device_id=device,exit_id=eid,revision=M.U('1'),protection_change_id=cid,gate_id=None,reason_ref='new_exit',body=b,outbox_body=b,audit_body=b),
        I('pd_cut',cut_id=cut,kind='close',prepare_head=head,selected_tick=now,selector_digest=M.digest('new_exit'),selector_body=b,control_id=None,cancel_id=None,run_id=None,close_id=close),
        I('pd_cut_commit',cut_id=cut,committed_tick=now,audit_body=b,outbox_body=b),
        I('ct_audit',change_id=cid,body=b),I('ct_outbox',change_id=cid,event_id=cid,body=b),I('ct_commit',change_id=cid)]

def publish(db,cmd,auth,*,prepare=False,names=(),fail_after=None,preview=False,provider_patch=None):
    before=S.read(db,cmd,auth)['record'];revision=str(int(before['revision'])+1);state=dict(before['state'],revision=revision);aid='attempt_inventory';op='inventory_'+cmd+'_'+revision
    if prepare:state['attempt_ids']=[aid]
    selections={aid:dict(kind='pending',ref=None)} if prepare else json.loads(P.rows(db,'SELECT selection_body FROM av_snapshot WHERE command_id=? AND revision=?',(cmd,M.U(before['revision'])))[0]['selection_body'])
    views=[]
    for name in names:
        body=M.V.seal(dict(evidence_id='decision.inventory_'+name,command_id=cmd,scope=state['scope'],kind='failure',policy_ref=before['policy']['completion_policy_ref'],retry_policy_ref=None,attempt_ids=[aid],achieved=None,effect_status='not_sent',resolved_outcome=None),'evidence_digest')
        view=M.V.seal(dict(scope=state['scope'],command_id=cmd,kind='decision',source_ref=dict(id=body['evidence_id'],revision='1',digest=body['evidence_digest']),body=body),'view_digest');views.append(view)
        selections[aid]=dict(kind='decision',ref=view['source_ref'])
    writes=[];db.execute('BEGIN IMMEDIATE')
    def execute(parts):
        for sql,args in parts:
            index=len(writes);writes.append((sql,args));db.execute(sql,args)
            if index==fail_after:raise RuntimeError('injected')
    try:
        if prepare:execute([I('cm_attempt',attempt_id=aid,command_id=cmd,ordinal=1,prepared_revision=M.U(revision)),I('ce_attempt',attempt_id=aid,command_id=cmd,authorization_body=b'{"synthetic":true}',attempt_body=b'{"synthetic":true}')])
        sd=M.digest(state);execute([I('cm_validation',validation_id=op,command_id=cmd,purpose='transition',subject_id=op,subject_digest=sd,policy_ref=before['policy']['completion_policy_ref']['id'],provider_ref='synthetic_state',source_body=M.raw(state),receipt_body=b'{"synthetic":true}'),
            I('cm_revision',command_id=cmd,revision=M.U(revision),operation_id=op,kind='prepare' if prepare else 'observe',previous_revision=M.U(before['revision']),previous_digest=before['state_ref']['digest'],state_digest=sd,transition_digest=sd,
                phase=state['phase'],outcome=state['outcome'],effect_status=state['effect_status'],resource_status=state['resource_status'],paused_latched=0,terminal_revision=None,resolution_id=None,decision_id=None,validation_id=op,state_body=M.raw(state)),
            *[I('cm_revision_attempt',command_id=cmd,revision=M.U(revision),attempt_id=a) for a in state['attempt_ids']]])
        proof=dict(authorized=True,originals_verified=True,projection_verified=True,redaction_verified=True,state_ref=M.V.state_ref(state),view_digests=[v['view_digest'] for v in views],max_snapshot_members=32,
            projection={k:before[k] for k in ('attempts','completion','cancellation')});proof['projection_digest']=M.digest(proof['projection'])
        for v in views:
            b=v['body'];vid=b['evidence_id']+'_validation';execute([I('cm_validation',validation_id=vid,command_id=cmd,purpose='failure',subject_id=b['evidence_id'],subject_digest=b['evidence_digest'],policy_ref=b['policy_ref']['id'],provider_ref='synthetic_decision',source_body=M.raw(b),receipt_body=b'{"synthetic":true}'),
                I('cm_decision',evidence_id=b['evidence_id'],command_id=cmd,kind='failure',achieved=None,effect_status='not_sent',retry_policy_ref=None,resolved_outcome=None,validation_id=vid,evidence_digest=b['evidence_digest'],evidence_body=M.raw(b))])
        # 先持久证据原件，随后从实际库采集完整库存，再组装最终公开投影。
        execute([w for w in E.evidence_steps(db,cmd,revision,views,proof) if M.data(w)[0]=='cv_evidence'])
        valid=[json.loads(r['view_body'])['source_ref'] for r in P.rows(db,"SELECT * FROM cv_evidence WHERE command_id=? AND kind='decision' ORDER BY evidence_id,revision",(cmd,))]
        trusted=provider(state,valid);trusted.update(provider_patch or {});inventory=S.capture(db,cmd,revision,trusted)
        provisional=dict(before,revision=revision,state=state,state_ref=M.V.state_ref(state));projection=A.project(provisional,inventory,selections)
        proof['projection']['attempts']=projection['attempts'];proof['projection_digest']=M.digest(proof['projection']);proof['view_digests']=[]
        execute(E.evidence_steps(db,cmd,revision,[],proof));execute(S.publication_steps(db,cmd,revision,inventory,selections,trusted))
        M.complete_record(db,P.rows(db,'SELECT * FROM cv_record WHERE command_id=? AND revision=?',(cmd,M.U(revision)))[0],attempt_source=S.source)
        execute([I('cm_commit',operation_id=op,command_id=cmd,revision=M.U(revision),audit_body=b'{}',outbox_id=op,outbox_body=b'{}')])
        if preview:db.rollback();return writes
        db.commit();return inventory
    except BaseException:db.rollback();raise

def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def fresh():
        d,cds,db,cmd,auth=fixture();dbs.extend([d]+[x[0] for x in cds.values()]);return db,cmd,auth
    def rejected(n,db,fn,reason=None):
        before=SC.snapshot(db)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError,IndexError) as err:
            if reason:assert reason in str(err),(n,str(err))
            check(n,SC.snapshot(db)==before and not db.in_transaction);return
        raise AssertionError(n)
    try:
        check('组合DDL可重现',(HERE/'controller-attempt-inventory.sql').read_bytes()==G.build())
        db,cmd,auth=fresh();check('238表组合',len(SC.snapshot(db))==238)
        # 完整公共许可原件的列投影检查；不把此独立向量称为数据库发送成功链。
        wire=W.upgraded(W.J.fixtures()[0])['DISPATCH']['body']['permit'];intent=wire['transmission']['intent']
        row=dict(permit_id=wire['permit_id'],packet_id=wire['transmission']['packet_ref']['packet_id'],attempt_id=wire['attempt_id'],exit_id='synthetic_exit',ordinal=int(wire['transmission']['ordinal']),permit_body=M.raw(wire))
        commit=dict(permit_id=wire['permit_id'],dispatch_intent_body=M.raw(intent));exit_row=dict(exit_id=row['exit_id'],**{k:intent[k] for k in A.EXIT_FIELDS if k!='exit_id'})
        check('完整许可列映射正例',S.transmission(row,commit,exit_row,wire['command_id'])['permit_id']==wire['permit_id'])
        for field in ('permit_id','packet_id','attempt_id','exit_id','ordinal'):
            wrong=dict(row,**{field:9 if field=='ordinal' else 'wrong'})
            rejected('完整许可列错绑'+field,db,lambda wrong=wrong:S.transmission(wrong,commit,exit_row,wire['command_id']))
        for field in ('worker_boot_id','ipc_session_id','clock_domain_id','descriptor_digest'):
            rejected('完整许可出口错绑'+field,db,lambda field=field:S.transmission(row,commit,dict(exit_row,**{field:'wrong'}),wire['command_id']))
        wrong=copy.deepcopy(intent);wrong['attempt_id']='wrong'
        rejected('原intent不能只比ID',db,lambda:S.transmission(row,dict(commit,dispatch_intent_body=M.raw(wrong)),exit_row,wire['command_id']),'inventory_intent_original')
        original=M.read(db,cmd,auth,'1');writes=publish(db,cmd,auth,prepare=True,preview=True)
        for index in range(len(writes)):
            rejected('prepared逐写异常'+str(index),db,lambda index=index:publish(db,cmd,auth,prepare=True,fail_after=index),'injected')
            rejected('prepared漏写'+str(index),db,lambda index=index:SC.execute(db,writes[:index]+writes[index+1:]))
        for flag in ('originals_verified','redaction_verified','decisions_verified','time_verified'):
            rejected('缺提供者'+flag,db,lambda flag=flag:publish(db,cmd,auth,prepare=True,provider_patch={flag:False}),'inventory_provider')
        rejected('超字节容量整笔回滚',db,lambda:publish(db,cmd,auth,prepare=True,provider_patch=dict(max_inventory_bytes=1)),'inventory_byte_capacity')
        rejected('四份正文合计容量拒绝',db,lambda:publish(db,cmd,auth,prepare=True,provider_patch=dict(max_bundle_bytes=1)),'inventory_bundle_capacity')
        inv=publish(db,cmd,auth,prepare=True);v=S.read(db,cmd,auth)['record']
        check('来源从实际固定库存加载',v['attempts'][0]['outcome']=='pending' and v['revision']=='2')
        check('初始历史不增加attempt',S.read(db,cmd,auth,'1')==original)
        history=S.read(db,cmd,auth,'2');first_bytes=db.execute('SELECT inventory_body FROM av_snapshot WHERE command_id=? AND revision=?',(cmd,M.U('2'))).fetchone()[0]
        writes=publish(db,cmd,auth,names=['one'],preview=True)
        rejected('完整成员超额不截断',db,lambda:publish(db,cmd,auth,names=['one','two'],provider_patch=dict(max_members=1)),'inventory_member_capacity')
        late_writes=publish(db,cmd,auth,names=['one','late'],preview=True)
        late=[w for w in late_writes if M.data(w)[0] in ('cm_validation','cm_decision','cv_evidence') and any(str(v)=='decision.inventory_late' for v in M.data(w)[1].values())]
        check('迟到向量包含完整原件',len(late)==3)
        rejected('封存后增加原件不能漏入旧清单',db,lambda:SC.execute(db,writes[:-1]+late+writes[-1:]))
        for index in range(len(writes)):
            rejected('含证据逐写异常'+str(index),db,lambda index=index:publish(db,cmd,auth,names=['one'],fail_after=index),'injected')
            rejected('含证据漏写'+str(index),db,lambda index=index:SC.execute(db,writes[:index]+writes[index+1:]))
        # 即使直接重放SQL写集，缺或替换真实成员仍由最后提交点拒绝。
        for group,extra in [('packets',dict(packet_id='missing')),('transmissions',dict(permit_id='missing')),('reports',dict(report_id='missing')),('assignments',dict(prepare_id='missing'))]:
            modified=[]
            for sql,args in writes:
                table,row=M.data((sql,args))
                if table=='av_snapshot':
                    value=json.loads(row['inventory_body']);value[group].append(extra);row['inventory_body']=M.raw(value);row['inventory_digest']=M.digest(value)
                modified.append(I(table,**row))
            rejected('SQL额外原件拒绝'+group,db,lambda modified=modified:SC.execute(db,modified))
        modified=[]
        for sql,args in writes:
            table,row=M.data((sql,args))
            if table=='av_snapshot':
                value=json.loads(row['inventory_body']);value['attempts'].append(copy.deepcopy(value['attempts'][0]));row['inventory_body']=M.raw(value);row['inventory_digest']=M.digest(value)
            modified.append(I(table,**row))
        rejected('SQL重复成员不能靠集合差集漏过',db,lambda:SC.execute(db,modified),'attempt_inventory_member_count')
        for group in ('attempts','packets','exits','transmissions','reports','evidence','assignments','valid_decision_refs','time_projections'):
            modified=[]
            for sql,args in writes:
                table,row=M.data((sql,args))
                if table=='av_snapshot':
                    value=json.loads(row['inventory_body']);del value[group];row['inventory_body']=M.raw(value);row['inventory_digest']=M.digest(value)
                modified.append(I(table,**row))
            rejected('空集合也不能省字段'+group,db,lambda modified=modified:SC.execute(db,modified),'attempt_inventory_array_types')
        publish(db,cmd,auth,names=['one']);current=S.read(db,cmd,auth)['record']
        check('新修订采用实际持久裁决',current['attempts'][0]['outcome']=='failed' and len(current['attempts'][0]['evidence_refs'])==1)
        check('观察裁决不伪造全命令终态',current['state']['phase']=='queued' and current['state']['outcome']=='pending')
        check('迟到证据不污染旧库存',S.read(db,cmd,auth,'2')==history and db.execute('SELECT inventory_body FROM av_snapshot WHERE command_id=? AND revision=?',(cmd,M.U('2'))).fetchone()[0]==first_bytes)
        # 新增未指派出口不能把当前worker信息塞入任何历史attempt。
        SC.execute(db,register_exit(db,current['target']['device_id']))
        check('新出口不改旧历史',S.read(db,cmd,auth,'2')==history)
        old=S.read(db,cmd,auth,'3');publish(db,cmd,auth,names=['two']);check('多修订保持固定来源',S.read(db,cmd,auth,'3')==old and len(S.read(db,cmd,auth)['record']['attempts'][0]['evidence_refs'])==2)
        evidence_auth=dict(auth,permissions=['command.evidence.read'],cursor_subject=dict(issuer_id='viewer',issuer_epoch='viewer_epoch',principal_id='viewer',session_id='session',authorization_revision='1'))
        clock=dict(verified=True,now_tick='100',clock_domain_id='synthetic_clock',descriptor_digest=M.digest('synthetic_clock'))
        keys=dict(available=True,active_key_id='synthetic_key',keys={'synthetic_key':bytes(range(32))},ttl_ns='50',max_snapshot_members=32)
        first=S.page(db,cmd,'4',1,evidence_auth,clock,keys);publish(db,cmd,auth,names=['three'])
        tail=S.page(db,cmd,'4',1,evidence_auth,clock,keys,first['next_cursor'])
        check('实际库存分页不混迟到修订',first['total']==tail['total']=='2' and len(tail['items'])==1 and tail['next_cursor'] is None and S.page(db,cmd,'5',64,evidence_auth,clock,keys)['total']=='3')
        for column in ('inventory_body','projection_body','provider_body','selection_body'):
            rejected('库存不可更新'+column,db,lambda column=column:SC.execute(db,[(f'UPDATE av_snapshot SET {column}=?',(b'{}',))]),'immutable_attempt_inventory')
        rejected('库存不可删除',db,lambda:SC.execute(db,[('DELETE FROM av_snapshot',())]),'immutable_attempt_inventory')
        row=P.rows(db,'SELECT * FROM av_snapshot WHERE command_id=? ORDER BY revision',(cmd,))[0]
        rejected('库存不可REPLACE',db,lambda:SC.execute(db,[(I('av_snapshot',**row)[0].replace('INSERT INTO','INSERT OR REPLACE INTO'),I('av_snapshot',**row)[1])]))
        for flag in ('authenticated','authorization_current','response_authorized'):
            rejected('存储适配不绕过读权'+flag,db,lambda flag=flag:S.read(db,cmd,dict(auth,**{flag:False})))
        # 读取必须处于调用方已有快照，不能单独在事务外装配跨时点事实。
        rejected('来源禁止事务外读取',db,lambda:S.source(db,cmd,'2'),'inventory_transaction_required')
        for n,d in enumerate(dbs):check('外键完整'+str(n),not d.execute('PRAGMA foreign_key_check').fetchone())
        return checks
    finally:
        for d in dbs:d.close()

def inputs():return list(dict.fromkeys(T.inputs()+G.SOURCES+[HERE/n for n in ('attempt-projection-report.json','attempt_inventory_model.py','check_attempt_inventory.py','controller-attempt-inventory.sql','ATTEMPT_INVENTORY.md')]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};target=HERE/'attempt-inventory-report.json'
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=238,production_clearance=False,synthetic_qualification_provider=True,
            full_transmission_chain_tested=False,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.G.C.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
