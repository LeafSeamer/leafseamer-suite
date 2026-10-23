"""沿用人工夹具并显式升级字段；预期结果不从Schema生成。"""
import argparse
from copy import deepcopy as cp
import hashlib
import json
from pathlib import Path
import rfc8785
from datetime import datetime
from build_contracts import source, PARENT, ROOT, VERSION, IPC_VERSION, FEATURES

D='sha256:'+'a'*64
T='2026-10-17T00:00:00.000Z'


def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def proof_digest(p):return digest({k:p[k] for k in ('definition_id','definition_version','definition_digest','action_bindings','dependency_graph_digest','dsl_version','generator_version','alias_revision')})


def build():
    old=source(PARENT/'build_examples.py').examples()
    e={}
    for c in old:
        if c['schema_valid'] and c['contract_valid']:e.setdefault(c['model'],cp(c['instance']))
    f4=source(PARENT/'f04-f05/build_cases.py').build()
    f6=source(PARENT/'f06-f07/build_cases.py').build()
    for collection in (f4,f6):
        for c in collection['examples']:
            if c['schema_valid'] and c['semantic_error'] is None:e.setdefault(c['model'],cp(c['instance']))
    footprint=dict(e['EffectFootprint']);footprint['action_id']=footprint.pop('action_ref')
    admission=cp(e['AdmissionDecision'])
    def upgrade(v):
        if isinstance(v,list):return [upgrade(x) for x in v]
        if not isinstance(v,dict):return v
        v={k:upgrade(x) for k,x in v.items()}
        if 'protocol_version' in v:v['protocol_version']=VERSION
        if 'principal_id' in v and 'issuer_id' not in v:v.update(issuer_id='issuer-test',issuer_epoch='issuer-epoch-test')
        if set(v)=={'principal_id','session_id','authorization_revision','issuer_id','issuer_epoch'}:v['local_subject_id']='subject-test'
        if {'collection_ref','scene_id','catalog_revision'}<=v.keys():v.update(collection_generation='1',binding_revision='1')
        if {'action_id','parameters_schema','completion'}<=v.keys():
            v['footprint']=dict(cp(footprint),action_id=v['action_id'],reads=cp(v['read_set']),writes=cp(v['write_set']))
        if {'event_id','payload','source_sequence'}<=v.keys():
            v['age_proof']=dict(cp(e['EventAgeProof']),event_id=v['event_id'],provider_boot_id=v['provider_boot_id'],source_sequence=v['source_sequence'])
        if {'permit_id','deadline_policy'}<=v.keys():v.update(guard_id='guard-test',guard_digest=D)
        if {'evidence_id','predicate_result'}<=v.keys():v['obs_bundle']=None
        if {'phase','attempts','command_id'}<=v.keys():
            v.update(completion_evidence=[],resource_release_evidence=[],admission=dict(cp(admission),command_id=v['command_id']))
        if {'definition_id','published','definition'}<=v.keys():v['independence_proofs']=[]
        if 'independence_proof_revision' in v:v['independence_proof']=dict(proof_id='proof-1',proof_revision=v.pop('independence_proof_revision'))
        if {'code','message_key','retry_advice'}<=v.keys():v['existing_operation_id']=None
        if {'io_seq','tick_ns','evidence_id'}<=v.keys() or {'policy_id','frames'}<=v.keys():v['clock_domain_id']='worker-clock-1'
        if {'safe_failure_classes','action_ref'}<=v.keys():v['action_id']=v.pop('action_ref')
        return v
    e={k:upgrade(v) for k,v in e.items()}
    e['ObsSceneParameters']=cp(e['CommandRequest']['parameters'])
    ar=dict(provider_id='provider-1',device_id='device-A',action_id='sim.marker.set',capability_version='1.0.0')
    proof=e['IndependenceProof']
    proof.update(definition_id='definition-proof',definition_version='1.0.0',dependency_graph_digest=D,dsl_version='finite-dsl-1',alias_revision='1',
        action_bindings=[dict(action_ref=ar,manifest_digest=proof['failed_footprint']['manifest_digest'],module_artifact_digest=D,
            semantics_revision='1',parameters_schema_digest=D,catalog_revision='1',controller_id='controller-1',control_epoch='epoch-1')])
    proof['bindings_digest']=proof_digest(proof)
    e['PrincipalRef']=dict(issuer_id='issuer-test',issuer_epoch='issuer-epoch-test',principal_id='user-test')
    e['SubjectRecord']=dict(local_subject_id='subject-test',principal=e['PrincipalRef'])
    e['ProofRef']=dict(proof_id=proof['proof_id'],proof_revision=proof['proof_revision'])
    e['ProofActionBinding']=proof['action_bindings'][0]
    e['BootstrapRequest']=dict(bootstrap_token='synthetic-bootstrap-token',login='synthetic-user',password='synthetic-password-only',mode='standalone')
    e['LoginRequest']=dict(login='synthetic-user',password='synthetic-password-only')
    e['RefreshRequest']=dict(client_instance_id='client-test')
    e['TokenRequest']=dict(audience='controller-test',requested_scopes=['device.read'],extension_instance_id=None)
    e['TokenResult']=dict(access_token='synthetic-token-not-usable',token_type='Bearer',expires_in=60,audience='controller-test')
    e['IntrospectRequest']=dict(token='synthetic-token-not-usable',audience='controller-test',challenge_id='challenge-test',required_revision='1')
    e['IntrospectResult']=dict(active=True,snapshot=e['AuthorizationSnapshot'])
    identity=dict(context_id='ctx-test',idempotency_key='key-test')
    e['RevocationRequest']=dict(**identity,selector=e['RevocationSelector'],expected_revision='9',reason='logout')
    e['WsTicketRequest']=dict(**identity,origin='https://gui.example.invalid',subscription_scope=['device.read'],client_instance_id='client-test')
    e['WsTicketResult']=dict(ticket='synthetic_unused_ticket',binding=e['WsTicketBinding'])
    e['CapacityStatus']=dict(profile_id='sim-f04-f05-v1',profile_revision='1',pressure='normal',usage=[dict(dimension='devices',used=0,limit=8)],reasons=[])
    e['CapacityUpdate']=dict(**identity,expected_revision='1',profile=dict(cp(e['CapacityProfile']),purpose='release_candidate',validated_environment='synthetic-lab',evidence_ref='synthetic-evidence-not-approval'))
    item=dict(step_id='step-2',source_execution_id='exec-1',source_command_id=None,decision='execute_new',reason='never_dispatched',parameters_digest=D,evidence_ids=[],max_queue_ms=1000,evidence_timeout_ms=5000,not_before=None,not_after=None)
    plan=dict(items=[item],resource_keys=['device/B'],target_controller_ids=['controller-B'])
    snapshot=e['RecoverySnapshot'];snapshot['plan_digest']=digest(plan);snapshot['preview_digest']=digest({k:v for k,v in snapshot.items() if k!='preview_digest'})
    e.update(RecoveryPlanItem=item,RecoveryPlan=plan,RecoveryPreview=dict(snapshot=snapshot,plan=plan,observations=[e['Observation']]))
    e['ResumeRequest']=dict(**identity,expected_revision=snapshot['run_revision'],preview_id=snapshot['preview_id'],preview_digest=snapshot['preview_digest'])
    target=dict(controller_id='controller-B',operation_id='recovery-1',execution_id='exec-2',baseline_control_digest=D,target_control_digest=D,baseline_arm_generation='2',
        target_arm_generation='3',grant_id='new-grant',grant_revision='1',state='pending',receipt_id=None,durable=False)
    e['RecoveryTarget']=target;e['RecoveryOperation'].update(plan_digest=snapshot['plan_digest'],baseline_snapshot_digest=snapshot['preview_digest'],target_controller_ids=['controller-B'],targets=[target])
    e['ResourceReleaseEvidence']=dict(evidence_id='release-1',command_id='command-test',attempt_id='attempt-test',worker_boot_id='worker-test',
        device_session_id='device-session-test',policy_id='synthetic-settled',kind='module_settled',durable=True)
    e['EvidencePage']=dict(items=[e['CompletionEvidence']],resource_releases=[],next_cursor=None)
    # 把继承的封装重新指向升级后的模型，避免旧RecoveryPreview残留。
    from build_contracts import build as contracts
    docs=contracts()
    for n in docs['first-loop.schema.json']['$defs']:
        if n.endswith('Response') and n!='ErrorResponse':
            model=n[:-8]
            if model in e:e[n]=dict(request_id='request-test',service_id='service-test',service_boot_id='boot-test',protocol_version=VERSION,data=cp(e[model]))
    cases=[dict(case_id='positive-'+n,model=n,instance=v,schema_valid=True,semantic_valid=True) for n,v in e.items()]
    def case(cid,model,edit,struct=True,semantic=False):
        v=cp(e[model]);edit(v);cases.append(dict(case_id=cid,model=model,instance=v,schema_valid=struct,semantic_valid=semantic));return v
    case('no-issuer','Session',lambda v:v.pop('issuer_id'),False)
    case('old-scene','ObsSceneParameters',lambda v:v['scene_ref'].pop('collection_generation'),False)
    case('self-verdict-write','DefinitionCreate',lambda v:v.update(independence_proofs=[proof]),False)
    case('old-proof-field','StepDefinition',lambda v:v.update(independence_proof_revision='1'),False)
    case('fake-durable-public','ObsCompletionBundle',lambda v:v.update(durable=False),False)
    case('old-envelope','Meta',lambda v:v.update(protocol_version='1.0.0-draft.2'),False)
    case('missing-event-age','EventEnvelope',lambda v:v.pop('age_proof'),False)
    case('missing-permit-guard','DispatchPermit',lambda v:v.pop('guard_id'),False)
    case('ready-with-pending-target','RecoveryOperation',lambda v:v.update(state='ready'),False)
    case('unmeasured-capacity','CapacityUpdate',lambda v:v['profile'].update(purpose='simulation'),False)
    case('active-introspection-revoked','IntrospectResult',lambda v:v['snapshot'].update(state='revoked'),False)
    case('active-introspection-expired','IntrospectResult',lambda v:v['snapshot'].update(state='expired'),False)
    case('event-proof-other-event','EventEnvelope',lambda v:v['age_proof'].update(event_id='other'))
    case('footprint-diverges','CapabilityCatalog',lambda v:v['devices'][0]['actions'][0]['footprint'].update(writes=['device/other']))
    case('proof-bindings-changed','IndependenceProof',lambda v:v['action_bindings'][0].update(module_artifact_digest='sha256:'+'b'*64))
    case('recovery-plan-tampered','RecoveryPreview',lambda v:v['plan']['items'][0].update(step_id='other'))
    case('wrong-target-operation','RecoveryOperation',lambda v:v['targets'][0].update(operation_id='other'))
    case('wrong-admission-command','CommandRecord',lambda v:v['admission'].update(command_id='other'))
    case('obs-clock-domain','ObsCompletionBundle',lambda v:v['frames'][3].update(clock_domain_id='other-clock'))
    case('revocation-missing-target','RevocationRecord',lambda v:v['target_service_ids'].append('other'))
    case('revocation-wrong-operation','RevocationRecord',lambda v:v['receipts'][0].update(operation_id='other'))
    case('guard-tampered','ExecutionGuard',lambda v:v.update(command_id='other'))
    case('snapshot-expiry-order','RecoverySnapshot',lambda v:v.update(expires_tick_ns=v['issued_tick_ns']))
    case('obs-query-before-ack','ObsCompletionBundle',lambda v:v['frames'][2].update(io_seq='1'))
    # unknown清资源正例：可靠失败事实与独立资源证明均保留，原outcome不改。
    unknown=cp(e['CommandRecord']);release=cp(e['ResourceReleaseEvidence']);ev=cp(e['CompletionEvidence'])
    ev.update(kind='device_ack',predicate_result=False)
    attempt=dict(attempt_id='attempt-test',worker_boot_id='worker-test',device_session_id='device-session-test',dispatch_intent_id='intent-test',send_started_at=T,protocol_request_id='wire-test',evidence_ids=[ev['evidence_id']],outcome='unknown')
    unknown.update(phase='finished',outcome='unknown',effect_status='acknowledged',resource_status='clear',resource_evidence_ids=[release['evidence_id']],
        completion_evidence=[ev],resource_release_evidence=[release],attempts=[attempt],automation_continuation='paused_latched',reason_code='ACK_TIMEOUT',
        resolution=dict(revision='2',resolved_outcome='failed',evidence_ids=[ev['evidence_id']],resolved_at=T,resolver='synthetic-policy'))
    cases.append(dict(case_id='unknown-cleared-still-paused',model='CommandRecord',instance=unknown,schema_valid=True,semantic_valid=True))
    for cid,edit,struct in [('unknown-clear-no-resolution',lambda v:v.pop('resolution'),False),
        ('unknown-clear-no-resource-proof',lambda v:v.update(resource_release_evidence=[]),True),
        ('unknown-clear-unpause',lambda v:v.update(automation_continuation='eligible'),False),
        ('unknown-other-attempt-proof',lambda v:v['resource_release_evidence'][0].update(attempt_id='other'),True)]:
        v=cp(unknown);edit(v);cases.append(dict(case_id=cid,model='CommandRecord',instance=v,schema_valid=struct,semantic_valid=False))
    # OBS完整成功记录与嵌套证据绑定，不能只验证孤立bundle。
    success=cp(unknown);success.pop('resolution');success.update(outcome='succeeded',effect_status='verified',reason_code=None,automation_continuation='eligible')
    bundle=cp(e['ObsCompletionBundle'])
    for key in ('command_id','attempt_id','worker_boot_id','device_session_id'):bundle[key]=ev[key]
    for row in bundle['frames']:
        for key in ('command_id','attempt_id','worker_boot_id','device_session_id'):row[key]=bundle[key]
    evidence=dict(cp(ev),kind='fresh_query',predicate_result=True,obs_bundle=bundle)
    success['completion_evidence']=[evidence];success['attempts'][0]['outcome']='succeeded'
    success['completion'].update(achieved='effect_verified',evidence_ids=[evidence['evidence_id']],evidence_policy_id=bundle['policy_id'])
    cases.append(dict(case_id='obs-succeeded-linked',model='CommandRecord',instance=success,schema_valid=True,semantic_valid=True))
    for cid,edit in [('obs-bundle-other-command',lambda v:v['completion_evidence'][0]['obs_bundle'].update(command_id='other')),
        ('obs-release-other-session',lambda v:v['resource_release_evidence'][0].update(device_session_id='other')),
        ('obs-completion-refers-release',lambda v:v['completion'].update(evidence_ids=[release['evidence_id']])),
        ('obs-policy-disagrees',lambda v:v['completion'].update(evidence_policy_id='other-policy'))]:
        v=cp(success);edit(v);cases.append(dict(case_id=cid,model='CommandRecord',instance=v,schema_valid=True,semantic_valid=False))
    ready=cp(e['RecoveryOperation']);ready['state']='ready';ready['targets'][0].update(state='applied',receipt_id='receipt-test',durable=True)
    cases.append(dict(case_id='recovery-all-targets-ready',model='RecoveryOperation',instance=ready,schema_valid=True,semantic_valid=True))
    v=cp(ready);v['targets'][0]['target_arm_generation']='99'
    cases.append(dict(case_id='recovery-wrong-arm-generation',model='RecoveryOperation',instance=v,schema_valid=True,semantic_valid=False))
    # 发布态证明的完整引用链；定义摘要排除证明引用，避免自指。
    first=cp(e['StepDefinition']);first.update(required=False,on_failure='continue_if_independent',action_ref=ar,
        parameters={'value':1},independence_proof=e['ProofRef'])
    second=cp(e['StepDefinition']);second.update(step_id='step-next',action_ref=dict(ar,device_id='device-B'),parameters={'value':2})
    definition=dict(kind='rule',name='independent-synthetic',trigger=e['Definition']['transitions'][0]['trigger'],groups=[dict(kind='sequential',steps=[first,second])])
    projected=cp(definition);projected['groups'][0]['steps'][0].pop('independence_proof')
    published_proof=cp(proof);published_proof.update(definition_digest=digest(projected),failed_step_id=first['step_id'],successor_step_ids=[second['step_id']])
    published_proof['bindings_digest']=proof_digest(published_proof)
    published=dict(definition_id=proof['definition_id'],revision='2',definition_version=proof['definition_version'],definition=definition,published=True,independence_proofs=[published_proof])
    cases.append(dict(case_id='published-independent-step',model='DefinitionRecord',instance=published,schema_valid=True,semantic_valid=True))
    v=cp(published);v['definition']['groups'][0]['steps'][0]['parameters']['value']=99
    cases.append(dict(case_id='published-definition-tampered',model='DefinitionRecord',instance=v,schema_valid=True,semantic_valid=False))
    v=cp(published);v['definition']['groups'][0]['steps'][0]['step_id']='other-step'
    cases.append(dict(case_id='proof-for-other-step',model='DefinitionRecord',instance=v,schema_valid=True,semantic_valid=False))
    v=cp(proof);v['action_bindings'].append(dict(cp(v['action_bindings'][0]),module_artifact_digest='sha256:'+'b'*64));v['bindings_digest']=proof_digest(v)
    cases.append(dict(case_id='duplicate-action-binding',model='IndependenceProof',instance=v,schema_valid=True,semantic_valid=False))
    ipc_cases,links=ipc_examples(e)
    return dict(examples=cases,ipc_examples=ipc_cases,link_cases=links)


def ipc_examples(e):
    old=source(PARENT/'f02-f03/build_cases.py').build()
    frames={c['frame']['type']:cp(c['frame']) for c in old['frames'] if c['valid']}
    # 意图/coverage同步升级守卫引用。
    def up(v):
        if isinstance(v,list):return [up(x) for x in v]
        if not isinstance(v,dict):return v
        v={k:up(x) for k,x in v.items()}
        if 'ipc_version' in v:v['ipc_version']=IPC_VERSION
        for k in ('supported_ipc_versions','selected_ipc_version'):
            if k in v:v[k]=[IPC_VERSION] if isinstance(v[k],list) else IPC_VERSION
        if {'permit_id','dispatch_intent_id','worker_boot_id'}<=v.keys():v.update(guard_id='guard-demo',guard_digest=D)
        if {'collection_ref','scene_id'}<=v.keys():v.update(collection_generation='1',binding_revision='1')
        return v
    frames={k:up(v) for k,v in frames.items()}
    frames['HELLO']['body']['supported_features']=FEATURES
    frames['HELLO_ACK']['body']['selected_features']=FEATURES
    dispatch=frames['DISPATCH'];p=dispatch['body']['permit'];p['content_digest']=digest({k:v for k,v in dispatch['body']['request'].items() if k not in ('context_id','idempotency_key','correlation_id')})
    g=cp(e['ExecutionGuard']);g.update(guard_id='guard-demo',permit_id=p['permit_id'],command_id=p['command_id'],device_id=dispatch['device_id'],
        controller_boot_id=dispatch['controller_boot_id'],worker_boot_id=dispatch['worker_boot_id'],ipc_session_id=dispatch['ipc_session_id'],authorization_revision=p['authorization_revision'],clock_domain_id=dispatch['body']['send_window']['clock_domain_id'])
    g['guard_digest']=digest({k:v for k,v in g.items() if k!='guard_digest'});p.update(guard_id=g['guard_id'],guard_digest=g['guard_digest'])
    dispatch['body'].update(guard_id=g['guard_id'],guard_digest=g['guard_digest'])
    def frame(kind,body):return dict(ipc_version=IPC_VERSION,type=kind,message_id='m-'+kind.lower(),reply_to='m-'+kind.lower().removesuffix('_ack') if kind.endswith('_ACK') else None,
        ipc_session_id=dispatch['ipc_session_id'],controller_boot_id=dispatch['controller_boot_id'],worker_boot_id=dispatch['worker_boot_id'],seq='1',device_id=dispatch['device_id'],body=body)
    frames['GUARD_INSTALL']=frame('GUARD_INSTALL',dict(guard=g,content_digest=p['content_digest'],clock_sample=None,schedule_guard=None))
    frames['GUARD_ACK']=frame('GUARD_ACK',dict(guard_id=g['guard_id'],guard_digest=g['guard_digest'],content_digest=p['content_digest'],permit_id=p['permit_id'],command_id=p['command_id'],installed_authorization_revision=p['authorization_revision'],state='installed'))
    frames['GUARD_ACK']['reply_to']=frames['GUARD_INSTALL']['message_id']
    # 既有控制屏障的ledger摘要随新增守卫字段更新。
    fence=frames['FENCE']['body'];ack=frames['FENCE_ACK']['body'];fence['ledger_digest']=digest(sorted(fence['open_intents'],key=lambda x:x['permit_id']));ack['ledger_digest']=fence['ledger_digest']
    intent=cp(fence['open_intents'][0]);intent.update(guard_id=g['guard_id'],guard_digest=g['guard_digest'])
    common=dict(operation_id='op-auth',barrier_id='barrier-auth',issued_cut_revision='2',ledger_digest=digest([intent]),open_intents=[intent])
    auth=dict(common,selector=cp(e['RevocationSelector']),target_authorization_revision='10')
    time=dict(common,operation_id='op-time',barrier_id='barrier-time',clock_domain_id=g['clock_domain_id'],time_policy_revision='2',old_clock_generation='generation-a',new_clock_generation='generation-a')
    for kind,body in [('AUTH_FENCE',auth),('TIME_FENCE',time)]:
        frames[kind]=frame(kind,body);b={k:cp(v) for k,v in body.items() if k!='open_intents'}
        b.update(coverage=[dict(intent=intent,disposition='not_sent',proof='discarded_unconsumed')],invalidated_permit_ids=[intent['permit_id']],in_flight_command_ids=[],unresolved_command_ids=[],all_write_exits_fenced=True)
        if kind=='AUTH_FENCE':b['applied_authorization_revision']='10'
        frames[kind+'_ACK']=frame(kind+'_ACK',b)
    cases=[dict(case_id='ipc-positive-'+k,frame=v,valid=True) for k,v in frames.items()]
    def bad(cid,kind,edit):
        v=cp(frames[kind]);edit(v);cases.append(dict(case_id=cid,frame=v,valid=False))
    bad('ipc-old-version','DISPATCH',lambda v:v.update(ipc_version='ipc/0.1.0-draft.1'))
    bad('ipc-missing-guard','DISPATCH',lambda v:v['body'].pop('guard_id'))
    bad('ipc-no-feature','HELLO_ACK',lambda v:v['body'].update(selected_features=['execution_guard']))
    bad('ipc-time-no-sample','GUARD_INSTALL',lambda v:v['body']['guard'].update(time_required=True,clock_generation='generation-a',time_policy_revision='2'))
    # 新typed OBS候选具有false durable，公共证据恰好相反。
    v=cp(frames['EVIDENCE_CANDIDATE']);v['body'].update(evidence_kind='obs_completion',payload=dict(cp(e['ObsCompletionBundle']),durable=False))
    bundle=v['body']['payload'];bundle.update(command_id=v['body']['command_id'],attempt_id=v['body']['attempt_id'],worker_boot_id=v['worker_boot_id'],device_session_id=v['body']['device_session_id'])
    for row in bundle['frames']:
        for key in ('command_id','attempt_id','worker_boot_id','device_session_id'):row[key]=bundle[key]
    cases.append(dict(case_id='ipc-obs-candidate',frame=v,valid=True));v=cp(v);v['body']['payload']['durable']=True
    cases.append(dict(case_id='ipc-worker-claims-durable',frame=v,valid=False))
    links=[]
    def link(cid,kind,value,expected,edit=None):
        value=cp(value)
        if edit:edit(value)
        links.append(dict(case_id=cid,kind=kind,input=value,expected=expected))
    guard=dict(install=frames['GUARD_INSTALL'],ack=frames['GUARD_ACK'],dispatch=dispatch,now_tick_ns=dispatch['body']['send_window']['earliest_tick_ns'])
    link('guard-linked','guard',guard,True)
    link('guard-wrong-session','guard',guard,False,lambda v:v['ack'].update(ipc_session_id='other'))
    link('guard-wrong-digest','guard',guard,False,lambda v:v['ack']['body'].update(guard_digest=D))
    link('guard-expired','guard',guard,False,lambda v:v.update(now_tick_ns=g['authorization_deadline_tick_ns']))
    link('guard-wrong-content','guard',guard,False,lambda v:v['install']['body'].update(content_digest=D))
    auto=cp(guard);ag=auto['install']['body']['guard'];ap=auto['dispatch']['body']['permit'];arq=auto['dispatch']['body']['request']
    ag['binding'].update(principal_kind='service',principal_id='service-a',session_id=None,session_revision=None,origin='automation',grant_id='grant-auto',grant_revision='17',arm_generation='22')
    ap.update(origin='automation',grant_revision='17',arm_generation='22');arq.update(origin='automation',run_binding=dict(run_id='run-auto',definition_version='1.0.0',grant_id='grant-auto',grant_revision='17',arm_generation='22',step_id='step-auto',logical_action_id='logical-auto'))
    def rehash_guard(v):
        gi=v['install']['body']['guard'];gi['guard_digest']=digest({k:x for k,x in gi.items() if k!='guard_digest'})
        v['dispatch']['body']['permit']['guard_digest']=v['dispatch']['body']['guard_digest']=v['ack']['body']['guard_digest']=gi['guard_digest']
        rq=v['dispatch']['body']['request'];h=digest({k:x for k,x in rq.items() if k not in ('context_id','idempotency_key','correlation_id')})
        v['dispatch']['body']['permit']['content_digest']=v['install']['body']['content_digest']=v['ack']['body']['content_digest']=h
    rehash_guard(auto);link('automation-guard-linked','guard',auto,True)
    wrong=cp(auto);wrong['install']['body']['guard']['binding'].update(grant_revision='999',arm_generation='999');rehash_guard(wrong)
    link('automation-wrong-grant-with-valid-digest','guard',wrong,False)
    wrong=cp(auto);wrong['dispatch']['body']['request']['run_binding']['grant_id']='other-grant';rehash_guard(wrong)
    link('automation-request-wrong-grant','guard',wrong,False)
    wrong=cp(guard);wrong['dispatch']['body']['request']['device_id']='other-device';rehash_guard(wrong)
    link('guard-request-wrong-device','guard',wrong,False)
    scheduled=cp(guard);scheduled['now_tick_ns']='1100000000';sg=cp(e['ScheduleGuard']);sample=cp(e['ClockSample'])
    sg.update(window_enter_tick_ns='1000000000',queue_deadline_tick_ns='2000000000')
    sample.update(clock_domain_id=g['clock_domain_id'],sample_tick_ns='1000000000',estimated_utc_ms=int(datetime.fromisoformat(sg['not_before']).timestamp()*1000))
    gi=scheduled['install']['body']['guard'];gi.update(time_required=True,clock_generation=sample['clock_generation'],time_policy_revision=sample['policy_revision'])
    gi['guard_digest']=digest({k:v for k,v in gi.items() if k!='guard_digest'})
    sp=scheduled['dispatch']['body']['permit'];sd=scheduled['dispatch']['body']
    sd['request']['dispatch']=dict(mode='scheduled',occurrence_id=sg['occurrence_id'],not_before=sg['not_before'],not_after=sg['not_after'],clock_policy_revision=sg['time_policy_revision'],max_queue_ms=1000)
    sp['deadline_policy']=cp(sd['request']['dispatch']);sp['content_digest']=digest({k:v for k,v in sd['request'].items() if k not in ('context_id','idempotency_key','correlation_id')})
    sd['send_window'].update(earliest_tick_ns='1000000000',latest_tick_ns='2000000000')
    sp['guard_digest']=sd['guard_digest']=scheduled['ack']['body']['guard_digest']=gi['guard_digest']
    scheduled['install']['body'].update(clock_sample=sample,schedule_guard=sg,content_digest=sp['content_digest'])
    scheduled['ack']['body']['content_digest']=sp['content_digest']
    link('scheduled-guard-current','guard',scheduled,True)
    link('scheduled-guard-stale-sample','guard',scheduled,False,lambda v:v['install']['body']['clock_sample'].update(max_sample_age_ms=100))
    link('scheduled-guard-wrong-policy','guard',scheduled,False,lambda v:v['install']['body']['clock_sample'].update(policy_revision='99'))
    link('scheduled-guard-latched','guard',scheduled,False,lambda v:v['install']['body']['schedule_guard'].update(health_latched=True,block_reason='CLOCK_UNTRUSTED'))
    link('scheduled-guard-end-exclusive','guard',scheduled,False,lambda v:v.update(now_tick_ns='2000000000'))
    for kind in ('AUTH_FENCE','TIME_FENCE'):
        value=dict(request=frames[kind],ack=frames[kind+'_ACK'])
        link(kind+'-complete','fence',value,True)
        link(kind+'-missing-coverage','fence',value,False,lambda v:v['ack']['body'].update(coverage=[]))
        link(kind+'-wrong-operation','fence',value,False,lambda v:v['ack']['body'].update(operation_id='other'))
        link(kind+'-bad-projection','fence',value,False,lambda v:v['ack']['body'].update(invalidated_permit_ids=[]))
        link(kind+'-duplicate-coverage','fence',value,False,lambda v:v['ack']['body']['coverage'].append(dict(cp(v['ack']['body']['coverage'][0]),disposition='unknown',proof='send_uncertain')))
    candidate=next(c['frame'] for c in cases if c['case_id']=='ipc-obs-candidate')
    link('obs-candidate-linked','obs_candidate',dict(frame=candidate),True)
    for key in ('command_id','worker_boot_id'):
        value=cp(candidate);value['body']['payload'][key]='other'
        for row in value['body']['payload']['frames']:row[key]='other'
        link('obs-candidate-other-'+key,'obs_candidate',dict(frame=value),False)
    recovery=dict(request=e['ResumeRequest'],preview=e['RecoveryPreview'],operation=e['RecoveryOperation'])
    link('recovery-linked','recovery',recovery,True)
    link('recovery-request-other-preview','recovery',recovery,False,lambda v:v['request'].update(preview_id='other'))
    link('recovery-other-execution','recovery',recovery,False,lambda v:v['operation']['targets'][0].update(execution_id='other'))
    link('recovery-missing-fixed-target','recovery',recovery,False,lambda v:v['operation'].update(targets=[]))
    link('recovery-other-plan','recovery',recovery,False,lambda v:v['operation'].update(plan_digest=D))
    return cases,links


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    data=json.dumps(build(),ensure_ascii=False,indent=2)+'\n';path=ROOT/'examples.json'
    if args.check:
        if not path.exists() or path.read_text(encoding='utf-8')!=data:raise SystemExit('正反例漂移')
    else:path.write_text(data,encoding='utf-8',newline='\n')
