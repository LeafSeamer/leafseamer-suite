"""Controller本地裁决参考writer；外部证据由显式可信接口提供，不读取Seamer数据库。"""
import json
import typed_seamer_model as T
S=T.S;B=T.B;P=T.P;R=T.R;I=T.I;raw=T.raw;need=T.need;digest=B.M.digest
OWNER=('issuer_id','issuer_epoch','principal_id','request_epoch')
def uid(kind,value):return kind+'_'+digest(value).split(':')[1]
def scope(db):
    row=R.one(db,'controller_scope','singleton',1);return {k:row[k] for k in ('authority_service_id','database_instance_id')}
def authorize(db,key,auth,action):
    S.validate('RequestKey',key)
    need(auth['authenticated'] and auth['permissions'][action] and auth['historical_owner_verified'] and auth['read_scope_verified'],'authority')
    need(key['target_scope']==scope(db)==auth['target_scope'],'target_scope')
    need({k:key[k] for k in OWNER}==auth['owner'],'historical_owner')
    rows=P.rows(db,'SELECT * FROM ca_namespace WHERE issuer_id=? AND issuer_epoch=? AND principal_id=? AND request_epoch=?',tuple(key[k] for k in OWNER))
    need(len(rows)==1,'namespace_original');return rows[0]
def existing(db,identity):
    rows=P.rows(db,'SELECT a.* FROM ca_request_key k JOIN ca_adjudication a USING(key_id) WHERE k.request_key_body=?',(raw(identity['key']),))
    if not rows:return None
    a=json.loads(rows[0]['adjudication_body']);need(a['identity']==identity,'identity_conflict')
    S.validate('RequestAdjudication',a);need(digest({k:v for k,v in a.items() if k!='adjudication_digest'})==a['adjudication_digest'],'stored_digest')
    R.one(db,'ca_commit','commit_id',a['commit_ref']['object_id']);return a
def lookup(db,identity,auth):
    S.validate('RequestIdentity',identity);authorize(db,identity['key'],auth,'lookup')
    if not auth['storage_readable']:
        need(auth['response_authorized'],'response_authority');return dict(state='indeterminate',adjudication=None)
    db.execute('BEGIN')
    try:a=existing(db,identity);db.commit()
    except BaseException:db.rollback();raise
    value=dict(state='found' if a else 'not_found',adjudication=a);S.validate('LookupResult',value)
    need(auth['response_authorized'],'response_authority');return value

def verify_new(db,key,request,provider):
    need(request['origin']=='automation' and request['automation_binding']['authorization_mode']=='continuation','continuation_path_required')
    for flag in ('authorization_current','control_current','source_current','time_current','budget_current','adoption_current','r5_committed','execution_original_verified','plan_original_verified'):
        need(provider[flag],flag)
    ab=request['automation_binding'];selection=ab['continuation'];row=R.one(db,'cr_current','transfer_id',selection['transfer_ref']['id'])
    q=json.loads(row['request_body']);target=json.loads(row['target_body']);receipt=json.loads(row['receipt_body'])
    e=provider['execution'];a=provider['adoption'];receipts=provider['receipts']
    need(digest({k:v for k,v in a.items() if k!='adoption_digest'})==a['adoption_digest'],'adoption_digest')
    B.validate_execution(e,q,a,receipts)
    need(next(r for r in receipts if r['controller_scope']==scope(db))==receipt,'local_receipt')
    need(selection==B.selection(q,a,receipt,target),'selected_originals')
    need(ab['execution_binding_ref']==B.eref(e) and ab['execution_id']==e['execution_id'] and ab['origin_scope']==e['scope'] and ab['run_id']==e['run_id'] and ab['arm_generation']==e['arm_generation'],'execution_reference')
    plan=provider['plan'];need(digest(plan)==e['plan_digest'],'plan_digest')
    steps=[p for p in plan['steps'] if p['step_id']==ab['step_id']];need(len(steps)==1,'step_original');step=steps[0]
    need(step['controller_scope']==key['target_scope'] and request['device_id'] in [x['device_id'] for x in target['devices']],'selected_device')
    fixed={k:v for k,v in step['request'].items() if k!='continuation'}
    need({k:request[k] for k in fixed}==fixed and ab['logical_action_id']==step['logical_action_id'] and ab['definition_version']==provider['definition_version'],'fixed_command')
    grant=selection['grant_ref'];need(request['run_binding']==dict(run_id=e['run_id'],definition_version=ab['definition_version'],grant_id=grant['id'],grant_revision=grant['revision'],arm_generation=e['arm_generation'],step_id=ab['step_id'],logical_action_id=ab['logical_action_id']),'run_binding')
    control=R.one(db,'ct_current_state','device_id',request['device_id'])
    need(request['expected_control']==dict(epoch=control['control_epoch'],version=str(int(control['effective_version']))),'expected_control')
    return row,e,a

def initial_rows(command,key_id,content,admission,provider):
    """内部初始状态投影；公开CommandRecord和最终准入证据仍须单独归并。"""
    one='00000000000000000001';zero='00000000000000000000';op=command+'_initial';vid=op+'_validation';sid=op+'_snapshot'
    state=dict(command_id=command,revision='1',phase='queued',outcome='pending',effect_status='not_sent',resource_status='clear')
    sd=digest(state);metadata=dict(command_id=command,content=content,admission=admission);md=digest(metadata)
    manifest=dict(command_id=command,revision='1',members=[]);record=dict(metadata_digest=md,state_digest=sd,snapshot_digest=digest(manifest))
    proof=provider['initial_state_evidence'];policy=provider['policies'];capacity=provider['capacity']
    return [I('cr_claim',command_id=command,release_policy_ref=policy['release_ref'],policy_body=raw(policy['release'])),
      I('cm_policy',command_id=command,required_completion=content['required_completion'],completion_policy_ref=policy['completion_ref'],retry_policy_ref=None,max_attempts=1,original_deadline_body=raw(content['dispatch']),policy_body=raw(policy['completion'])),
      I('cm_validation',validation_id=vid,command_id=command,purpose='transition',subject_id=op,subject_digest=sd,policy_ref=policy['completion_ref'],provider_ref=proof['provider_ref'],source_body=raw(state),receipt_body=raw(proof)),
      I('cm_revision',command_id=command,revision=one,operation_id=op,kind='initial',previous_revision=None,previous_digest=None,state_digest=sd,transition_digest=sd,phase='queued',outcome='pending',effect_status='not_sent',resource_status='clear',paused_latched=0,terminal_revision=None,resolution_id=None,decision_id=None,validation_id=vid,state_body=raw(state)),
      I('cv_metadata',command_id=command,initial_revision=one,metadata_digest=md,metadata_body=raw(metadata)),
      I('cv_snapshot',snapshot_id=sid,command_id=command,state_revision=one,state_digest=sd,total=zero,snapshot_digest=digest(manifest),manifest_body=raw(manifest),validation_body=raw(proof)),
      I('cv_record',command_id=command,revision=one,state_digest=sd,metadata_digest=md,snapshot_id=sid,cancellation_id=None,cancellation_revision=None,record_digest=digest(record),record_body=raw(record),validation_body=raw(proof)),
      I('cm_commit',operation_id=op,command_id=command,revision=one,audit_body=raw(dict(kind='command_initial')),outbox_id=op+'_event',outbox_body=raw(dict(command_id=command))),
      I('ca_reservation',key_id=key_id,command_id=command,capacity_profile_ref_body=raw(capacity['profile']),dimensions_body=raw(capacity['dimensions']))]

def commit_rows(commit,key_id,kind,creation,rid,body):
    return [I('ca_commit',commit_id=commit,key_id=key_id,kind=kind,creation_key_id=creation,rejection_id=rid,commit_body=raw(body)),
      I('ca_audit',commit_id=commit,key_id=key_id,kind=kind,redacted_body=raw(dict(kind=kind,key_id=key_id))),
      I('ca_notification',commit_id=commit,key_id=key_id,kind=kind,event_id=commit+'_event',payload_body=raw(dict(key_id=key_id,kind=kind)))]

def creation_steps(db,identity,content,ns,transport,provider=None,rejection=None,initial_factory=None):
    key=identity['key'];kid=uid('key',key);accepted=rejection is None;kind='accept' if accepted else 'reject_new'
    commit=uid('commit',dict(key=key,kind=kind));command=uid('command',key) if accepted else None
    command_body=dict(command_id=command,identity=identity,content=content) if accepted else None
    cb=dict(key_id=kid,decision='accepted' if accepted else 'rejected',request_digest=identity['request_digest'])
    a=dict(contract_version='command-admission/0.1.0-draft.1',adjudication_id=uid('adjudication',key),revision='1',identity=identity,decision=cb['decision'],
        command_ref=T.ref('command',key['target_scope'],command,digest(command_body)) if accepted else None,
        commit_ref=T.ref('controller_commit',key['target_scope'],commit,digest(cb)))
    a=B.M.seal(a,'adjudication_digest');S.validate('RequestAdjudication',a)
    out=[I('ca_request_key',key_id=kid,namespace_id=ns['namespace_id'],operation_id=key['operation_id'],idempotency_key=key['idempotency_key'],request_digest=identity['request_digest'],device_id=content['device_id'],content_body=raw(content),request_key_body=raw(key),transport_body=raw(transport) if transport else None),
      I('ca_adjudication',key_id=kid,adjudication_id=a['adjudication_id'],revision='1',decision=a['decision'],command_id=command,commit_id=commit,commit_kind=kind,adjudication_digest=a['adjudication_digest'],adjudication_body=raw(a))]
    if accepted:
        issue,e,adoption=verify_new(db,key,transport,provider);ab=content['automation_binding'];prep=R.one(db,'cp_receipt','prep_key',issue['prep_key'])
        out += [I('ca_command_initial',command_id=command,key_id=kid,decision='accepted',revision='1',command_digest=digest(command_body),command_body=raw(command_body),admission_binding_body=raw(ab)),
          I('ce_command',command_id=command,device_id=content['device_id'],origin=content['origin'],prep_key=issue['prep_key'],receipt_id=prep['receipt_id'],binding_body=raw(ab))]
        out += (initial_factory or initial_rows)(command,kid,content,a,provider)
        out += [I('typed_command_source',command_id=command,execution_body=raw(e),adoption_body=raw(adoption),evidence_body=raw(provider)),
          I('cn_command',command_id=command,transfer_id=issue['transfer_id'],execution_id=ab['execution_id'],step_id=ab['step_id'],request_digest=identity['request_digest'],adoption_digest=adoption['adoption_digest'],grant_ref_body=raw(ab['continuation']['grant_ref']),binding_body=raw(ab))]
    rid=rejection['rejection_id'] if rejection else None
    out += commit_rows(commit,kid,kind,kid,rid,cb)
    if rejection:out.append(I('ca_rejection',**dict(rejection,key_id=kid,commit_id=commit)))
    return out,a

def decide(db,identity,body,auth,provider=None,operation=None,fail_after=None,initial_factory=None):
    S.validate('RequestIdentity',identity);key=identity['key'];submit=operation is None;action='submit' if submit else 'reject'
    ns=authorize(db,key,auth,action);need(auth['storage_readable'],'indeterminate')
    S.validate('CommandRequest' if submit else 'CommandContent',body);content=B.content(body) if submit else body
    need(digest(content)==identity['request_digest'],'request_digest')
    need((auth['principal_kind'],auth['peer_kind'],content['origin'])==('service','seamer','automation'),'subject_origin')
    if submit:
        need(body['idempotency_key']==key['idempotency_key'] and body['context_id']==auth['context_id'],'transport_identity')
        need(body['automation_binding']['origin_scope']==auth['origin_scope'],'service_origin_scope')
    else:S.validate('RejectRequest',dict(rejection_operation_id=operation,identity=identity,content=content))
    output=[]
    def builder():
        current_ns=authorize(db,key,auth,action);old=existing(db,identity);rejection=None
        if not submit:
            actor=auth['actor'];opbody=dict(identity=identity,content=content,rejection_operation_id=operation);od=digest(opbody)
            prior=P.rows(db,'SELECT * FROM ca_rejection WHERE actor_issuer_id=? AND actor_issuer_epoch=? AND actor_principal_id=? AND rejection_operation_id=?',tuple(actor[k] for k in ('issuer_id','issuer_epoch','principal_id'))+(operation,))
            if prior:need(prior[0]['operation_digest']==od and old is not None,'rejection_conflict');output.append(old);return []
            need(auth['capacity_reserved'],'capacity')
            rejection=dict(rejection_id=uid('rejection',dict(actor=actor,operation=operation)),**{'actor_'+k:v for k,v in actor.items()},rejection_operation_id=operation,operation_digest=od,request_body=raw(opbody),authorization_evidence_body=raw(auth['rejection_evidence']))
        if old:
            output.append(old)
            if submit:return []
            kid=uid('key',key);rid=rejection['rejection_id'];commit=rid+'_commit'
            return commit_rows(commit,kid,'reject_existing',None,rid,dict(kind='reject_existing',adjudication_digest=old['adjudication_digest']))+[I('ca_rejection',**dict(rejection,key_id=kid,commit_id=commit))]
        need(auth['capacity_reserved'],'capacity')
        if submit:
            need(auth['namespace_writable'] and not db.execute('SELECT 1 FROM ca_namespace_closure WHERE namespace_id=?',(current_ns['namespace_id'],)).fetchone(),'namespace_closed')
        writes,a=creation_steps(db,identity,content,current_ns,body if submit else None,provider,rejection,initial_factory);output.append(a);return writes
    T.apply(db,builder,fail_after)
    need(auth['response_authorized'],'response_authority');return output[0]
