"""完整公开命令记录参考持久化与只读查询；不实现HTTP、设备发送或真实认证。"""
import copy,importlib.util,json,re
from jsonschema import Draft202012Validator,FormatChecker
import typed_controller_model as C
import build_typed_command_view as G
S=C.S;P=C.P;R=C.R;I=C.I;raw=C.raw;need=C.need;digest=C.digest
spec=importlib.util.spec_from_file_location('public_command_reference',G.HERE.parent/'c02-command-view/reference_model.py')
V=importlib.util.module_from_spec(spec);spec.loader.exec_module(V)
IMMUTABLE=('command_id','scope','initial_command_ref','request_identity','target','actor','origin','run_binding','automation_binding','accepted_at','dispatch','control_binding')
def validate(name,value):
    Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':S.SCHEMA['$defs']},format_checker=FormatChecker()).validate(value)
def ref(ident,body,revision='1'):return dict(id=ident,revision=revision,digest=digest(body))
def U(value):
    need(isinstance(value,str) and re.fullmatch(r'[1-9][0-9]{0,19}',value) is not None,'revision_format')
    return value.zfill(20)
def data(write):return write[0].split('(',1)[0].split()[-1],dict(zip(write[0].split('(',1)[1].split(')',1)[0].split(','),write[1]))

def record(metadata,policy,state,manifest,snapshot,attempts=None,completion=None,cancellation=None):
    v=dict(copy.deepcopy(metadata),revision=state['revision'],policy=copy.deepcopy(policy),state=copy.deepcopy(state),state_ref=V.state_ref(state),
        completion=completion or dict(required=policy['required_completion'],achieved=None,policy_ref=policy['completion_policy_ref'],evidence_refs=state['completion_evidence_refs']),
        attempts=attempts or [],cancellation=cancellation,evidence_index=dict(snapshot_ref=ref(snapshot,manifest),state_ref=V.state_ref(state),total=str(len(manifest['members']))))
    V.seal(v,'record_digest');validate('CommandRecord',v);return v

def initial_rows(command,key_id,content,admission,provider):
    public=provider['public_view'];key=admission['identity']['key'];actor=public['actor']
    need(public['actor_verified'] and public['accepted_time_verified'] and public['deadline_verified'],'public_metadata_provider')
    need(all(actor[k]==key[k] for k in ('principal_id','issuer_id','issuer_epoch')),'public_actor_owner')
    deadline=public['original_deadline'];need(deadline['dispatch']==content['dispatch'],'original_deadline_binding')
    state=dict(command_id=command,scope=key['target_scope'],revision='1',phase='queued',outcome='pending',effect_status='not_sent',resource_status='clear',
        automation_continuation='eligible',reason_code=None,terminal_revision=None,resolution_ref=None,completion_evidence_refs=[],resource_evidence_refs=[],attempt_ids=[])
    policies=provider['policies']
    policy=dict(command_id=command,scope=key['target_scope'],device_id=content['device_id'],admission_ref=dict(id=admission['adjudication_id'],revision='1',digest=admission['adjudication_digest']),
        required_completion=content['required_completion'],completion_policy_ref=ref(policies['completion_ref'],policies['completion']),
        release_policy_ref=ref(policies['release_ref'],policies['release']),retry_policy_ref=None,max_attempts=1,
        original_deadline_ref=ref(command+'_deadline',deadline),conflict_scope='whole_device')
    metadata=dict(command_id=command,scope=key['target_scope'],initial_command_ref=admission['command_ref'],request_identity=admission['identity'],
        target={k:content[k] for k in ('device_id','action_id','capability_version')},actor=actor,origin=content['origin'],run_binding=content['run_binding'],
        automation_binding=content['automation_binding'],accepted_at=public['accepted_at'],dispatch=content['dispatch'],control_binding=content['expected_control'])
    sd=digest(state);md=digest(metadata);snapshot=command+'_initial_snapshot'
    manifest=dict(command_id=command,revision='1',members=[]);v=record(metadata,policy,state,manifest,snapshot)
    out=[]
    for write in C.initial_rows(command,key_id,content,admission,provider):
        table,row=data(write)
        if table=='cm_policy':row.update(policy_body=raw(policy),original_deadline_body=raw(deadline))
        elif table=='cm_validation':row.update(subject_digest=sd,source_body=raw(state))
        elif table=='cm_revision':row.update(state_digest=sd,transition_digest=sd,state_body=raw(state))
        elif table=='cv_metadata':row.update(metadata_digest=md,metadata_body=raw(metadata))
        elif table=='cv_snapshot':row.update(state_digest=sd,snapshot_digest=digest(manifest),manifest_body=raw(manifest))
        elif table=='cv_record':row.update(state_digest=sd,metadata_digest=md,record_digest=v['record_digest'],record_body=raw(v))
        out.append(I(table,**row))
    return out

def decide(db,identity,body,auth,provider=None,operation=None,fail_after=None):
    return C.decide(db,identity,body,auth,provider,operation,fail_after,initial_factory=initial_rows)

def authorize(metadata,auth,permission='command.read'):
    need(auth['authenticated'] and permission in auth['permissions'] and auth['scope']==metadata['scope'],'read_authority')
    if auth['subject_kind']=='human':need(metadata['target']['device_id'] in auth['allowed_devices'],'device_scope')
    else:
        need(auth['subject_kind']=='service' and auth['paired'] and metadata['origin']=='automation','service_pair')
        need(auth['service_scope']==metadata['automation_binding']['origin_scope'],'service_origin')

def complete_record(db,row):
    v=json.loads(row['record_body']);validate('CommandRecord',v);command=row['command_id'];revision=row['revision']
    m=R.one(db,'cv_metadata','command_id',command);p=R.one(db,'cm_policy','command_id',command)
    s=P.rows(db,'SELECT * FROM cm_revision WHERE command_id=? AND revision=?',(command,revision))[0]
    metadata=json.loads(m['metadata_body']);state=json.loads(s['state_body']);policy=json.loads(p['policy_body'])
    need(digest(metadata)==m['metadata_digest']==row['metadata_digest'] and digest(state)==s['state_digest']==row['state_digest'],'stored_projection_digest')
    need(v['record_digest']==row['record_digest'] and V.valid_digest(v,'record_digest'),'stored_record_digest')
    need({k:v[k] for k in IMMUTABLE}==metadata and v['state']==state and v['policy']==policy,'stored_projection_body')
    initial=R.one(db,'ca_command_initial','command_id',command);key=R.one(db,'ca_request_key','key_id',initial['key_id']);ad=R.one(db,'ca_adjudication','key_id',key['key_id'])
    need(digest(json.loads(key['content_body']))==key['request_digest'],'request_content_digest')
    need(V.valid_digest(json.loads(ad['adjudication_body']),'adjudication_digest'),'adjudication_digest')
    need(digest(json.loads(initial['command_body']))==initial['command_digest']==v['initial_command_ref']['digest'],'initial_command_digest')
    need(v['request_identity']==dict(key=json.loads(key['request_key_body']),request_digest=key['request_digest']),'request_identity')
    need(v['initial_command_ref']==json.loads(ad['adjudication_body'])['command_ref'],'initial_command_reference')
    policyrefs=policy['admission_ref'];need(policyrefs==dict(id=ad['adjudication_id'],revision='1',digest=ad['adjudication_digest']),'admission_policy')
    need(policy['original_deadline_ref']==ref(command+'_deadline',json.loads(p['original_deadline_body'])),'deadline_reference')
    provider=json.loads(R.one(db,'typed_command_source','command_id',command)['evidence_body'])
    for role in ('completion','release'):
        need(policy[role+'_policy_ref']==ref(provider['policies'][role+'_ref'],provider['policies'][role]),'policy_reference')
    snapshot=R.one(db,'cv_snapshot','snapshot_id',row['snapshot_id']);manifest=json.loads(snapshot['manifest_body'])
    members=P.rows(db,'SELECT e.* FROM cv_snapshot_member m JOIN cv_evidence e ON e.evidence_id=m.evidence_id AND e.revision=m.evidence_revision WHERE m.snapshot_id=? ORDER BY m.ordinal',(row['snapshot_id'],))
    need(digest(manifest)==snapshot['snapshot_digest'] and int(snapshot['total'])==len(members),'snapshot_digest')
    expected=[dict(kind=e['kind'],source_ref=dict(id=e['evidence_id'],revision=str(int(e['revision'])),digest=e['source_digest']),view_digest=e['view_digest']) for e in members]
    need(manifest==dict(command_id=command,revision=str(int(revision)),members=expected),'snapshot_manifest')
    index=dict(snapshot_ref=ref(row['snapshot_id'],manifest),state_ref=V.state_ref(state),total=str(len(members)))
    attempts=P.rows(db,'SELECT a.* FROM cm_revision_attempt r JOIN cm_attempt a USING(attempt_id) WHERE r.command_id=? AND r.revision=? ORDER BY a.ordinal',(command,revision))
    need(state['attempt_ids']==[a['attempt_id'] for a in attempts],'attempt_original_set')
    # 每次公开attempt必须指向实际prepared State；出口和packet的完整提供者映射另在写入边界验证。
    need(len(v['attempts'])==len(attempts),'attempt_projection_set')
    for view,a in zip(v['attempts'],attempts):
        prepared=P.rows(db,'SELECT state_digest FROM cm_revision WHERE command_id=? AND revision=?',(command,a['prepared_revision']))[0]
        need(view['attempt_id']==a['attempt_id'] and view['ordinal']==a['ordinal'] and view['prepared_state_ref']==dict(id=command,revision=str(int(a['prepared_revision'])),digest=prepared['state_digest']),'prepared_state_reference')
    levels={'sent':0,'acknowledged':1,'effect_verified':2};achieved=[]
    for er in state['completion_evidence_refs']:
        ev=R.one(db,'cm_decision','evidence_id',er['id']);body=json.loads(ev['evidence_body'])
        need(ev['command_id']==command and ev['kind']=='completion' and er==dict(id=ev['evidence_id'],revision='1',digest=ev['evidence_digest']),'completion_original')
        need(body['evidence_digest']==ev['evidence_digest'] and V.valid_digest(body,'evidence_digest'),'completion_digest');achieved.append(ev['achieved'])
    completion=dict(required=policy['required_completion'],achieved=max(achieved,key=levels.get) if achieved else None,policy_ref=policy['completion_policy_ref'],evidence_refs=state['completion_evidence_refs'])
    cancels=P.rows(db,'SELECT * FROM cv_cancel_revision WHERE command_id=? AND state_revision<=? ORDER BY revision DESC LIMIT 1',(command,revision));cancel=None
    if cancels:
        ca=cancels[0];body=json.loads(ca['operation_body']);validate('CancelOperation',body)
        need(body['operation_digest']==ca['operation_digest'] and V.valid_digest(body,'operation_digest'),'cancel_digest')
        cancel=dict(operation_ref=dict(id=ca['cancellation_id'],revision=str(int(ca['revision'])),digest=ca['operation_digest']),state=ca['state'],future_writes=ca['future_writes'],reason_code=body['reason_code'])
    context=dict(scope=metadata['scope'],command_id=command,state=state,policy=policy,initial_command_ref=metadata['initial_command_ref'],request_identity=metadata['request_identity'],
        immutable={k:metadata[k] for k in ('target','actor','origin','run_binding','automation_binding','accepted_at','dispatch','control_binding')},
        attempts=v['attempts'],completion=completion,cancellation=cancel,evidence_index=index)
    need(V.record_error(v,context) is None,'record_semantics')
    return v

def read(db,command,auth,revision=None):
    need(not db.in_transaction,'read_requires_committed_snapshot');need(auth['storage_readable'],'unavailable')
    need(auth['authenticated'] and auth['authorization_current'] and 'command.read' in auth['permissions'] and auth['scope']==C.scope(db),'read_authority')
    if revision is not None:U(revision)
    db.execute('BEGIN')
    try:
        metadata=json.loads(R.one(db,'cv_metadata','command_id',command)['metadata_body']);authorize(metadata,auth)
        rows=P.rows(db,'SELECT * FROM cv_current WHERE command_id=?',(command,)) if revision is None else P.rows(db,'SELECT * FROM cv_history WHERE command_id=? AND revision=?',(command,U(revision)))
        need(bool(rows),'state_projection_pending' if revision is None else 'not_found');v=complete_record(db,rows[0]);db.commit()
    except BaseException:db.rollback();raise
    need(auth['response_authorized'],'response_authority');return dict(view='current' if revision is None else 'historical',record=v)

def stop_steps(db,command,kind,expected,proof):
    """仅未准备且无许可的排队阻断/过期；可信监督证据必须绑定原State。"""
    need(db.in_transaction,'transaction_required');need(kind in ('block','expire'),'stop_kind')
    row=R.one(db,'cm_latest','command_id',command);before=json.loads(row['state_body'])
    need(expected==V.state_ref(before) and before['phase']=='queued' and not before['attempt_ids'],'stop_prestate')
    need(not db.execute('SELECT 1 FROM ce_attempt WHERE command_id=?',(command,)).fetchone(),'attempt_exists')
    need(proof['trusted_provider'] and proof['future_writes_closed'] and proof['state_ref']==expected,'stop_provider')
    if kind=='expire':need(proof['deadline_elapsed'],'deadline_unproven')
    after=dict(before,revision=str(int(before['revision'])+1),phase='finished',outcome='blocked' if kind=='block' else 'expired',automation_continuation='paused_latched',reason_code=kind,terminal_revision=str(int(before['revision'])+1))
    revision=U(after['revision']);op=command+'_'+kind;vid=op+'_validation';sid=op+'_snapshot';sd=digest(after)
    metadata=json.loads(R.one(db,'cv_metadata','command_id',command)['metadata_body']);policy=json.loads(R.one(db,'cm_policy','command_id',command)['policy_body'])
    need(proof['scope']==metadata['scope'] and proof['original_deadline_ref']==policy['original_deadline_ref'],'stop_original_binding')
    need(not db.execute('SELECT 1 FROM cv_evidence WHERE command_id=?',(command,)).fetchone(),'stop_requires_complete_evidence_projection')
    manifest=dict(command_id=command,revision=after['revision'],members=[]);v=record(metadata,policy,after,manifest,sid)
    return [I('cm_validation',validation_id=vid,command_id=command,purpose='transition',subject_id=op,subject_digest=sd,policy_ref=policy['completion_policy_ref']['id'],provider_ref=proof['provider_ref'],source_body=raw(after),receipt_body=raw(proof)),
        I('cm_revision',command_id=command,revision=revision,operation_id=op,kind=kind,previous_revision=row['revision'],previous_digest=row['state_digest'],state_digest=sd,transition_digest=sd,
          phase=after['phase'],outcome=after['outcome'],effect_status=after['effect_status'],resource_status=after['resource_status'],paused_latched=1,terminal_revision=revision,resolution_id=None,decision_id=None,validation_id=vid,state_body=raw(after)),
        I('cv_snapshot',snapshot_id=sid,command_id=command,state_revision=revision,state_digest=sd,total='0'.zfill(20),snapshot_digest=digest(manifest),manifest_body=raw(manifest),validation_body=raw(proof)),
        I('cv_record',command_id=command,revision=revision,state_digest=sd,metadata_digest=digest(metadata),snapshot_id=sid,cancellation_id=None,cancellation_revision=None,record_digest=v['record_digest'],record_body=raw(v),validation_body=raw(proof)),
        I('cm_commit',operation_id=op,command_id=command,revision=revision,audit_body=raw(dict(kind=kind)),outbox_id=op+'_event',outbox_body=raw(dict(command_id=command,revision=after['revision'])))]
