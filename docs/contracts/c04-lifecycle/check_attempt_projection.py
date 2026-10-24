"""独立固定库存映射、重摘要反例与实际SQLite读取接线；无真实设备来源。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import check_command_evidence as T
import attempt_projection_model as A
M=A.M;E=T.E;G=A.G;HERE=T.HERE;ROOT=T.ROOT;P=M.P;I=M.I
def sealed(v,key):return M.V.seal(v,key)
def fixture():
    d,cds,item,cmd,auth,clock,keys=T.fixture();db=item[0]
    record=M.read(db,cmd,T.T.reader(item))['record']
    for conn in [d]+[x[0] for x in cds.values()]:conn.close()
    prepared=dict(record['state'],revision='2',attempt_ids=['attempt_a'])
    running=dict(prepared,revision='3',phase='awaiting_evidence',effect_status='possible',resource_status='held')
    record.update(revision='3',state=running,state_ref=M.V.state_ref(running))
    record['evidence_index']['state_ref']=copy.deepcopy(record['state_ref'])
    inv=dict(scope=record['scope'],command_id=cmd,state=copy.deepcopy(record['state']),state_ref=copy.deepcopy(record['state_ref']),complete=True,originals_verified=True,redaction_verified=True,
        attempts=[dict(attempt_id='attempt_a',ordinal=1,prepared_state=prepared,exit_ids=['exit_a','exit_b'])],packets=[],exits=[],reports=[],transmissions=[],evidence=[],valid_decision_refs=[],time_projections=[])
    for letter in ('a','b'):
        ex=dict(exit_id='exit_'+letter,device_id=record['target']['device_id'],controller_boot_id='controller_a',worker_boot_id='worker_'+letter,ipc_session_id='ipc_'+letter,device_session_id='device_'+letter,clock_domain_id='clock_'+letter,descriptor_digest=M.digest('clock_'+letter))
        inv['exits'].append(ex)
        packet=sealed(dict(packet_id='packet_'+letter,command_id=cmd,attempt_id='attempt_a',primitive_id='primitive_'+letter,writer_exit_id=ex['exit_id'],device_session_id=ex['device_session_id'],socket_instance_id='socket_'+letter,
            protocol_session='protocol_'+letter,wire_packet_id='1',tracking_ids=['tracking_not_request'],immutable_bytes_ref=dict(object_id='bytes_'+letter,digest=M.digest('bytes')),
            byte_length=1,sha256=M.digest('bytes'),transport_profile_ref=dict(object_id='profile',digest=M.digest('profile')),primitive_plan_ref=dict(object_id='plan',digest=M.digest('plan'))),'packet_digest')
        inv['packets'].append(packet)
        for n,tick in [(0,'9007199254740993'),(1,'9007199254740994')]:
            ident=letter+str(n);permit='permit_'+ident;rid='report_'+ident
            inv['transmissions'].append(dict(permit_id=permit,packet_id=packet['packet_id'],attempt_id='attempt_a',exit_id=ex['exit_id'],ordinal=n,transmission_id='transmission_'+ident,dispatch_intent_id='intent_'+ident))
            body=dict(report_id=rid,permit_id=permit,attempt_id='attempt_a',dispatch_intent_id='intent_'+ident,device_session_id=ex['device_session_id'],disposition='in_flight',proof='transport_entered',protocol_request_id='request_'+ident,
                transmission_id='transmission_'+ident,packet_ref={k:packet[k] for k in ('packet_id','packet_digest')},ordinal=str(n),gate_io_seq=str(n+1),transport_entered_tick_ns=tick,socket_callback_observation_ref=None)
            r=dict(report_id=rid,exit_id=ex['exit_id'],worker_boot_id=ex['worker_boot_id'],ipc_session_id=ex['ipc_session_id'],body=body);inv['reports'].insert(0,r)
            inv['time_projections'].append(dict(report_id=rid,report_ref=A.ref(rid,r),entered_tick_ns=tick,clock_domain_id=ex['clock_domain_id'],descriptor_digest=ex['descriptor_digest'],verified=True,utc='2026-10-24T00:00:00.00'+str(n)+'Z'))
    choose={'attempt_a':dict(kind='pending',ref=None)}
    projection=A.project(record,inv,choose);record['attempts']=copy.deepcopy(projection['attempts']);sealed(record,'record_digest')
    return record,inv,choose,projection

def evidence(record,kind='completion',achieved='effect_verified',resolved=None):
    b=sealed(dict(evidence_id='decision_a',command_id=record['command_id'],scope=record['scope'],kind=kind,policy_ref=record['policy']['completion_policy_ref'],retry_policy_ref=None,
        attempt_ids=['attempt_a'],achieved=achieved if kind=='completion' else None,effect_status='verified' if kind=='completion' else 'possible',resolved_outcome=resolved),'evidence_digest')
    return sealed(dict(scope=record['scope'],command_id=record['command_id'],kind='decision',source_ref=dict(id=b['evidence_id'],revision='1',digest=b['evidence_digest']),body=b),'view_digest')

def sql_prepare(db,command):
    before=M.read(db,command,SQL_AUTH)['record'];state=dict(before['state'],revision='2',attempt_ids=['attempt_sql']);sd=M.digest(state);op='prepare_sql';aid='attempt_sql'
    inv=dict(scope=state['scope'],command_id=command,state=state,state_ref=M.V.state_ref(state),complete=True,originals_verified=True,redaction_verified=True,
        attempts=[dict(attempt_id=aid,ordinal=1,prepared_state=state,exit_ids=[])],packets=[],exits=[],reports=[],transmissions=[],evidence=[],valid_decision_refs=[],time_projections=[])
    selection={aid:dict(kind='pending',ref=None)}
    candidate=dict(before,revision='2',state=state,state_ref=M.V.state_ref(state))
    projection=A.project(candidate,inv,selection);candidate['attempts']=projection['attempts']
    proof=dict(authorized=True,originals_verified=True,projection_verified=True,redaction_verified=True,state_ref=M.V.state_ref(state),view_digests=[],max_snapshot_members=32,
        projection={k:candidate[k] for k in ('attempts','completion','cancellation')})
    proof['projection_digest']=M.digest(proof['projection']);db.execute('BEGIN IMMEDIATE')
    try:
        for write in [I('cm_attempt',attempt_id=aid,command_id=command,ordinal=1,prepared_revision=M.U('2')),
            I('ce_attempt',attempt_id=aid,command_id=command,authorization_body=b'{"synthetic":true}',attempt_body=b'{"synthetic":true}'),
            I('cm_validation',validation_id=op,command_id=command,purpose='transition',subject_id=op,subject_digest=sd,policy_ref=before['policy']['completion_policy_ref']['id'],provider_ref='synthetic_state',source_body=M.raw(state),receipt_body=b'{"synthetic":true}'),
            I('cm_revision',command_id=command,revision=M.U('2'),operation_id=op,kind='prepare',previous_revision=M.U('1'),previous_digest=before['state_ref']['digest'],state_digest=sd,transition_digest=sd,
                phase='queued',outcome='pending',effect_status='not_sent',resource_status='clear',paused_latched=0,terminal_revision=None,resolution_id=None,decision_id=None,validation_id=op,state_body=M.raw(state)),
            I('cm_revision_attempt',command_id=command,revision=M.U('2'),attempt_id=aid)]:db.execute(*write)
        for write in E.evidence_steps(db,command,'2',[],proof):db.execute(*write)
        db.execute(*I('cm_commit',operation_id=op,command_id=command,revision=M.U('2'),audit_body=b'{}',outbox_id=op,outbox_body=b'{}'));db.commit()
    except BaseException:db.rollback();raise
    return inv,selection,projection

def run():
    checks=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def reject(n,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError) as e:
            if reason:assert reason in str(e),(n,str(e))
            check(n);return
        raise AssertionError(n)
    base=fixture();record,inv,choice,projection=base
    check('Schema生成一致',(HERE/'attempt-projection.schema.json').read_bytes()==G.C.raw(G.build()));Draft202012Validator.check_schema(G.build())
    check('独立库存完整投影',A.verify(*base)==record['attempts'])
    check('保留两个旧出口身份',len(record['attempts'][0]['exits'])==2)
    check('发送时间按精确tick取最早',all(e['send_started_at']=='2026-10-24T00:00:00.000Z' for e in record['attempts'][0]['exits']))
    check('协议请求ID不借packet tracking',record['attempts'][0]['exits'][0]['protocol_request_ids']==['request_a0','request_a1'])
    unordered=copy.deepcopy(inv)
    for field in ('packets','exits','reports','transmissions','time_projections'):unordered[field].reverse()
    check('库存遍历顺序不改固定投影',A.project(record,unordered,choice)==projection)
    mutations=[('packet摘要',lambda v:v['packet_refs'][0].update(packet_digest=M.digest('wrong'))),('packet漏项',lambda v:v['packet_refs'].pop()),
        ('出口漏项',lambda v:v['exits'].pop()),('出口会话',lambda v:v['exits'][0].update(ipc_session_id='other')),
        ('发送时间',lambda v:v['exits'][0].update(send_started_at='2026-10-24T00:00:01.000Z')),('协议请求',lambda v:v['exits'][0].update(protocol_request_ids=['wrong'])),
        ('结果伪成功',lambda v:v.update(outcome='succeeded')),('证据伪引用',lambda v:v.update(evidence_refs=[dict(id='fake',revision='1',digest=M.digest('fake'))])),
        ('prepared错绑',lambda v:v['prepared_state_ref'].update(digest=M.digest('fake')))]
    for name,change in mutations:
        r=copy.deepcopy(record);change(r['attempts'][0]);sealed(r,'record_digest')
        reject('重新摘要仍拒'+name,lambda r=r:A.verify(r,inv,choice,projection),'attempt_projection_originals')
        p=copy.deepcopy(projection);p['attempts']=copy.deepcopy(r['attempts']);sealed(p,'projection_digest')
        reject('连投影重摘要仍拒'+name,lambda r=r,p=p:A.verify(r,inv,choice,p),'projection_originals')
    wrongs=[('完整性',lambda i:i.update(complete=False)),('脱敏资格',lambda i:i.update(redaction_verified=False)),('原件资格',lambda i:i.update(originals_verified=False)),
        ('状态修订',lambda i:i['state_ref'].update(revision='4')),('重复packet',lambda i:i['packets'].append(copy.deepcopy(i['packets'][0]))),
        ('跨命令packet',lambda i:i['packets'][0].update(command_id='other')),('错packet出口',lambda i:i['packets'][0].update(writer_exit_id='missing')),
        ('出口设备',lambda i:i['exits'][0].update(device_id='other')),('报告旧会话',lambda i:i['reports'][0].update(ipc_session_id='other')),
        ('报告错许可',lambda i:i['reports'][0]['body'].update(permit_id='other')),('报告ordinal',lambda i:i['reports'][0]['body'].update(ordinal='9')),
        ('报告错packet',lambda i:i['reports'][0]['body']['packet_ref'].update(packet_digest=M.digest('wrong'))),
        ('TIME撤回',lambda i:i['time_projections'][0].update(verified=False)),('TIME错报告',lambda i:i['time_projections'][0]['report_ref'].update(digest=M.digest('wrong'))),
        ('TIME换域',lambda i:i['time_projections'][0].update(clock_domain_id='other')),('TIME错tick',lambda i:i['time_projections'][0].update(entered_tick_ns='1')),
        ('未指派出口',lambda i:i['attempts'][0].update(exit_ids=['exit_a'])),
        ('重复传输ordinal',lambda i:i['transmissions'].append(dict(i['transmissions'][0],permit_id='duplicate_permit'))),
        ('选择缺项',None)]
    for name,change in wrongs:
        i=copy.deepcopy(inv)
        if change:change(i)
        reject('原件拒绝'+name,lambda i=i,change=change:A.project(record,i,choice if change else {}))
    i=copy.deepcopy(inv);i['time_projections']=[t for t in i['time_projections'] if t['report_id']!='report_a0']
    check('缺最早UTC不借晚报告',A.project(record,i,choice)['attempts'][0]['exits'][0]['send_started_at'] is None)
    i=copy.deepcopy(inv);i['packets']=[];i['reports']=[];i['transmissions']=[];i['time_projections']=[]
    check('编码未知仍保留已指派出口',len(A.project(record,i,choice)['attempts'][0]['exits'])==2)
    for kind,resolved,outcome in [('completion',None,'succeeded'),('failure',None,'failed'),('cancellation',None,'cancelled'),('resolution','not_sent','not_sent')]:
        i=copy.deepcopy(inv);ev=evidence(record,kind,resolved=resolved);i['evidence']=[ev];i['valid_decision_refs']=[ev['source_ref']];s={'attempt_a':dict(kind='decision',ref=ev['source_ref'])}
        p=A.project(record,i,s);r=copy.deepcopy(record);r['attempts']=p['attempts'];sealed(r,'record_digest');check('明确结果'+outcome,A.verify(r,i,s,p)[0]['outcome']==outcome)
        i['valid_decision_refs']=[];reject('撤回结果不发布'+outcome,lambda i=i,s=s:A.project(record,i,s),'attempt_decision_invalid')
    i=copy.deepcopy(inv);ev=evidence(record,achieved='sent');i['evidence']=[ev];i['valid_decision_refs']=[ev['source_ref']]
    reject('sent不冒充effect_verified',lambda:A.project(record,i,{'attempt_a':dict(kind='decision',ref=ev['source_ref'])}),'attempt_completion_level')
    reject('有裁决不能藏为pending',lambda:A.project(record,i,choice),'pending_unproven')
    ev=evidence(record);i=copy.deepcopy(inv);i['evidence']=[ev];i['valid_decision_refs']=[ev['source_ref']]
    body=dict(invalidation_id='invalidation_a',scope=record['scope'],command_id=record['command_id'],subject_ref=ev['source_ref'],reason_code='withdrawn',protection_ref=dict(id='protection_a',revision='1',digest=M.digest('protection')))
    invalid=sealed(dict(scope=record['scope'],command_id=record['command_id'],kind='invalidation',source_ref=A.ref('invalidation_a',body),body=body),'view_digest');i['evidence'].append(invalid)
    reject('有效列表不能覆盖明确撤回',lambda:A.project(record,i,{'attempt_a':dict(kind='decision',ref=ev['source_ref'])}),'attempt_decision_invalidated')
    r=copy.deepcopy(record);r['state'].update(phase='finished',outcome='unknown',effect_status='possible',resource_status='unresolved',automation_continuation='paused_latched',terminal_revision='3',reason_code='timeout')
    r['state_ref']=M.V.state_ref(r['state']);sealed(r,'record_digest');i=copy.deepcopy(inv);i.update(state=copy.deepcopy(r['state']),state_ref=copy.deepcopy(r['state_ref']));s={'attempt_a':dict(kind='unknown',ref=r['state_ref'])}
    p=A.project(r,i,s);r['attempts']=p['attempts'];sealed(r,'record_digest');check('unknown固定原终态',A.verify(r,i,s,p)[0]['outcome']=='unknown')
    ev=evidence(r);i['evidence']=[ev];i['valid_decision_refs']=[ev['source_ref']]
    reject('迟到成功不覆写unknown',lambda:A.project(r,i,{'attempt_a':dict(kind='decision',ref=ev['source_ref'])}),'unknown_rewrite')
    i['evidence'].append(invalid)
    check('撤回证据沿subject进入attempt',len(A.project(r,i,s)['attempts'][0]['evidence_refs'])==2)
    # 实际237表库接线；prepared正例没有伪造最终发送、packet或设备效果。
    global SQL_AUTH
    d,cds,item,cmd,auth,clock,keys=T.fixture();db=item[0];SQL_AUTH=T.T.reader(item)
    try:
        bundle=sql_prepare(db,cmd);source=lambda conn,command,revision:copy.deepcopy(bundle)
        reject('有attempt无原件提供者拒绝',lambda:M.read(db,cmd,SQL_AUTH),'attempt_originals_unavailable')
        observed=M.read(db,cmd,SQL_AUTH,attempt_source=source);check('真实存储prepared公开读取',observed['record']['attempts']==bundle[2]['attempts'])
        row=P.rows(db,'SELECT * FROM cv_history WHERE command_id=? AND revision=?',(cmd,M.U('2')))[0]
        forged=json.loads(row['record_body']);forged['attempts'][0]['outcome']='failed';sealed(forged,'record_digest');row.update(record_body=M.raw(forged),record_digest=forged['record_digest'])
        reject('实际完整读取拒重摘要假结果',lambda:M.complete_record(db,row,attempt_source=source),'attempt_projection_originals')
        check('旧历史不混新attempt',M.read(db,cmd,SQL_AUTH,'1')['record']['attempts']==[])
        reject('证据页也不得绕过提供者',lambda:E.page(db,cmd,'2',2,auth,clock,keys),'attempt_originals_unavailable')
        check('证据页同原件校验',E.page(db,cmd,'2',2,auth,clock,keys,attempt_source=source)['items']==[])
        wrong=copy.deepcopy(bundle);wrong[0]['state_ref']['revision']='9'
        reject('实际reader错原件拒绝',lambda:M.read(db,cmd,SQL_AUTH,attempt_source=lambda *args:wrong),'snapshot_state')
        check('外键完整',not db.execute('PRAGMA foreign_key_check').fetchone())
    finally:
        for conn in [d]+[x[0] for x in cds.values()]:conn.close()
    return checks

def inputs():return list(dict.fromkeys(T.inputs()+[HERE/n for n in ('command-evidence-report.json','attempt_projection_model.py','build_attempt_projection.py','attempt-projection.schema.json','check_attempt_projection.py','ATTEMPT_PROJECTION.md')]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};path=HERE/'attempt-projection-report.json'
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),runtime_tests_executed=0,device_tests_executed=0,production_clearance=False,
            full_inventory_storage_adapter=False,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(G.C.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
