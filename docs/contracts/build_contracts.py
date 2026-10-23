"""只生成协议文档；不导入业务代码，不连接服务或设备。"""
from pathlib import Path
import argparse
import json
import re

ROOT = Path(__file__).resolve().parent
DIALECT = 'https://json-schema.org/draft/2020-12/schema'
BASE = 'https://leafseamer.invalid/contracts/first-loop.schema.json'
VERSION = '1.0.0-draft.2'

def ref(name): return {'$ref': '#/$defs/' + name}
def enum(*values): return {'enum': list(values)}
def nullable(schema): return {'anyOf': [schema, {'type': 'null'}]}
def array(schema, maximum=256, minimum=0):
    return {'type': 'array', 'items': schema, 'minItems': minimum, 'maxItems': maximum}
def obj(properties, optional=()):
    return {'type': 'object', 'properties': properties,
            'required': [k for k in properties if k not in optional], 'additionalProperties': False}
def when(properties, then, otherwise=None):
    result = {'if': {'properties': properties, 'required': list(properties)}, 'then': then}
    if otherwise is not None: result['else'] = otherwise
    return result
def props(**values): return {'properties': values}
def text(maximum=1024): return {'type': 'string', 'maxLength': maximum}
def integer(maximum=86400000, minimum=0): return {'type': 'integer', 'minimum': minimum, 'maximum': maximum}

def build():
    d = {}
    d['Id'] = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': '^[A-Za-z0-9._-]+$'}
    d['Revision'] = {'type': 'string', 'maxLength': 20, 'pattern': '^(0|[1-9][0-9]*)$'}
    d['Timestamp'] = {'type': 'string', 'format': 'date-time', 'pattern': r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$'}
    d['Version'] = {'type': 'string', 'maxLength': 128, 'pattern': r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?$'}
    d['Digest'] = {'type': 'string', 'pattern': '^sha256:[0-9a-f]{64}$'}
    d['Duration'] = integer(minimum=1)
    d['CompletionLevel'] = enum('sent', 'acknowledged', 'effect_verified')
    d['JsonValue'] = {'anyOf': [{'type': 'null'}, {'type': 'boolean'}, text(16384),
        {'type': 'number', 'minimum': -9007199254740991, 'maximum': 9007199254740991},
        array(ref('JsonValue')), {'type': 'object', 'maxProperties': 256, 'additionalProperties': ref('JsonValue')}]}
    d['Payload'] = {'type': 'object', 'maxProperties': 256, 'additionalProperties': ref('JsonValue'),
        'description': '开放容器仅用于动态能力数据，须再通过固定摘要的能力Schema；不是免校验任意写入。'}
    d['ClockStatus'] = obj(dict(status=enum('synchronized','degraded','unsynchronized'),source_ref=nullable(ref('Id')),
        sampled_at=nullable(ref('Timestamp')),offset_ms=nullable({'type':'number'}),uncertainty_ms=nullable({'type':'number','minimum':0}),
        sample_age_ms=nullable(integer()),policy_revision=ref('Revision')))
    d['ClockStatus']['allOf'] = [when({'status':{'const':'synchronized'}}, props(source_ref=ref('Id'),sampled_at=ref('Timestamp'),
        offset_ms={'type':'number'},uncertainty_ms={'type':'number','minimum':0},sample_age_ms=integer()))]
    d['ControlVersion'] = obj(dict(epoch=ref('Id'), version=ref('Revision')))
    d['RequestIdentity'] = obj(dict(service_id=ref('Id'), context_epoch=ref('Id'), context_id=ref('Id'),principal_id=ref('Id'),idempotency_key=ref('Id'),operation=ref('Id')))
    identity = dict(context_id=ref('Id'),idempotency_key=ref('Id'))
    d['RequestContextRequest'] = obj(dict(audience=ref('Id'),operations=array(ref('Id'),32,1),ttl_ms=ref('Duration'),max_unique_requests=integer(4096,1)))
    d['RequestContext'] = obj(dict(context_id=ref('Id'),service_id=ref('Id'),principal_id=ref('Id'),audience=ref('Id'),operations=array(ref('Id'),32,1),
        issued_at=ref('Timestamp'),expires_at=ref('Timestamp'),ttl_ms=ref('Duration'),max_unique_requests=integer(4096,1),context_epoch=ref('Id')))
    d['SchemaDescriptor'] = obj(dict(schema_id=ref('Id'),digest=ref('Digest'),dialect={'const':DIALECT},
        document={'type':['object','boolean']}))
    d['RetryPolicy'] = obj(dict(policy_id=ref('Id'),allowed_error_codes=array(ref('Id'),32,1),safety_predicate_id=ref('Id'),
        max_attempts=integer(16,1),backoff_ms=integer(),total_budget_ms=ref('Duration')))
    d['RetryDescriptor'] = {'oneOf':[obj({'mode':{'const':'never'}}),obj({'mode':{'const':'conditional'},'policy':ref('RetryPolicy')})]}
    d['CancelDescriptor'] = {'oneOf':[obj({'mode':{'const':'before_dispatch_only'}}),obj({'mode':{'const':'cooperative'},'evidence_policy_id':ref('Id')})]}
    d['ResourceSet'] = {'oneOf':[{'const':'unknown'},array(text(256),64)]}
    d['Platform'] = obj(dict(os=enum('windows','linux'),arch=enum('x64','arm64'),status=enum('tested','untested','unsupported')))
    d['ActionDescriptor'] = obj(dict(action_id=ref('Id'),capability_version=ref('Version'),parameters_schema=ref('SchemaDescriptor'),result_schema=ref('SchemaDescriptor'),
        resources=array(text(256),64,1),completion=obj(dict(supported=array(ref('CompletionLevel'),3,1),default=ref('CompletionLevel'),evidence_policy_id=ref('Id'))),
        cancel=ref('CancelDescriptor'),retry=ref('RetryDescriptor'),preconditions_schema=ref('SchemaDescriptor'),read_set=ref('ResourceSet'),write_set=ref('ResourceSet'),
        evidence_timeout_ms=ref('Duration'),limits_profile=ref('Id'),platforms=array(ref('Platform'),16,1),dependencies=array(ref('Id'),64)))
    d['TriggerDescriptor'] = obj(dict(trigger_id=ref('Id'),capability_version=ref('Version'),payload_schema=ref('SchemaDescriptor'),delivery_semantics=enum('discrete','sampled'),
        time_requirement=enum('relative_age','trusted_utc'),max_age_ms=ref('Duration'),causation_support=enum('none','verified_reference'),sampling_policy=nullable(ref('Id'))))
    d['DeviceDescriptor'] = obj(dict(device_id=ref('Id'),device_kind=ref('Id'),display_name=text(),connection_state=enum('disconnected','connecting','ready','faulted'),
        actions=array(ref('ActionDescriptor')),triggers=array(ref('TriggerDescriptor')),state_schema=ref('SchemaDescriptor')))
    d['CapabilityCatalog'] = obj(dict(provider_id=ref('Id'),provider_boot_id=ref('Id'),catalog_revision=ref('Revision'),module_id=ref('Id'),module_version=ref('Version'),devices=array(ref('DeviceDescriptor'))))
    d['CatalogUpdate'] = obj(dict(expected_revision=nullable(ref('Revision')),catalog=ref('CapabilityCatalog')))
    d['SceneRef'] = obj(dict(collection_ref=ref('Id'),scene_id=ref('Id'),catalog_revision=ref('Revision')))
    d['ObsSceneParameters'] = obj(dict(scene_ref=ref('SceneRef')))
    d['Predicate'] = obj(dict(predicate_id=ref('Id'),device_id=ref('Id'),field=text(256),operator=enum('eq','ne','lt','lte','gt','gte'),value=ref('JsonValue'),max_age_ms=ref('Duration')))
    d['EventEnvelope'] = obj(dict(event_id=ref('Id'),provider_id=ref('Id'),provider_boot_id=ref('Id'),source_sequence=ref('Revision'),trigger_id=ref('Id'),capability_version=ref('Version'),
        device_id=ref('Id'),occurred_at=nullable(ref('Timestamp')),observed_at=ref('Timestamp'),clock=ref('ClockStatus'),payload=ref('Payload'),causation_command_id=ref('Id')),('causation_command_id',))
    d['Observation'] = obj(dict(observation_id=ref('Id'),device_id=ref('Id'),provider_boot_id=ref('Id'),device_session_id=ref('Id'),state_revision=ref('Revision'),observed_at=ref('Timestamp'),
        clock=ref('ClockStatus'),freshness_ms=nullable(integer()),values=ref('Payload'),integrity=enum('complete','gap','unavailable')))
    d['Dispatch'] = {'oneOf':[obj(dict(mode={'const':'immediate'},max_queue_ms=ref('Duration'))),obj(dict(mode={'const':'scheduled'},occurrence_id=ref('Id'),not_before=ref('Timestamp'),not_after=ref('Timestamp'),clock_policy_revision=ref('Revision'),max_queue_ms=ref('Duration')))]}
    d['RunBinding'] = obj({k:ref('Revision') if k in ('grant_revision','arm_generation') else ref('Version') if k=='definition_version' else ref('Id') for k in
        ['run_id','definition_version','grant_id','grant_revision','arm_generation','step_id','logical_action_id']})
    command = dict(**identity,device_id=ref('Id'),action_id=ref('Id'),capability_version=ref('Version'),parameters=ref('Payload'),expected_control=ref('ControlVersion'),
        origin=enum('manual','automation'),run_binding=ref('RunBinding'),required_completion=ref('CompletionLevel'),preconditions=array(ref('Predicate'),64),dispatch=ref('Dispatch'),evidence_timeout_ms=ref('Duration'),correlation_id=ref('Id'))
    d['CommandRequest'] = obj(command,('run_binding','correlation_id'))
    d['CommandRequest']['allOf'] = [when({'origin':{'const':'automation'}},{'required':['run_binding']},{'not':{'required':['run_binding']}}),
        when({'action_id':{'const':'obs.program_scene.set'}},props(parameters=ref('ObsSceneParameters'),required_completion={'const':'effect_verified'}))]
    d['Actor'] = obj(dict(principal_id=ref('Id'),session_id=nullable(ref('Id')),authorization_revision=ref('Revision')))
    d['Completion'] = obj(dict(required=ref('CompletionLevel'),achieved=nullable(ref('CompletionLevel')),evidence_policy_id=ref('Id'),evidence_ids=array(ref('Id'),256)))
    d['Cancellation'] = obj(dict(status=enum('none','requested','confirmed','unsupported','failed'),operation_id=nullable(ref('Id')),reason_code=nullable(ref('Id'))))
    d['Cancellation']['allOf']=[when({'status':{'const':'none'}},props(operation_id={'type':'null'}),props(operation_id=ref('Id')))]
    d['Attempt'] = obj(dict(attempt_id=ref('Id'),worker_boot_id=ref('Id'),device_session_id=ref('Id'),dispatch_intent_id=ref('Id'),send_started_at=nullable(ref('Timestamp')),
        protocol_request_id=nullable(ref('Id')),evidence_ids=array(ref('Id')),outcome=enum('pending','succeeded','failed','unknown','cancelled','not_sent')))
    d['Resolution'] = obj(dict(revision=ref('Revision'),resolved_outcome=enum('succeeded','failed','cancelled','not_sent'),evidence_ids=array(ref('Id'),256,1),resolved_at=ref('Timestamp'),resolver=ref('Id')))
    d['CommandRecord'] = obj(dict(command_id=ref('Id'),revision=ref('Revision'),request_identity=ref('RequestIdentity'),content_digest=ref('Digest'),target=obj(dict(device_id=ref('Id'),action_id=ref('Id'),capability_version=ref('Version'))),actor=ref('Actor'),
        origin=enum('manual','automation'),run_binding=ref('RunBinding'),accepted_at=ref('Timestamp'),phase=enum('queued','dispatching','awaiting_evidence','finished'),outcome=enum('pending','succeeded','failed','unknown','cancelled','expired','blocked'),
        effect_status=enum('not_sent','possible','acknowledged','verified','partial'),resource_status=enum('held','clear','unresolved'),resource_evidence_ids=array(ref('Id')),cancellation=ref('Cancellation'),completion=ref('Completion'),attempts=array(ref('Attempt'),16),
        dispatch=ref('Dispatch'),control_binding=ref('ControlVersion'),automation_continuation=enum('eligible','paused_latched'),reason_code=nullable(ref('Id')),resolution=ref('Resolution'),retry_policy=nullable(ref('RetryPolicy'))),('resolution','run_binding'))
    d['CommandRecord']['allOf']=[
        when({'phase':{'const':'finished'}},{'properties':{'outcome':{'not':{'const':'pending'}}}},props(outcome={'const':'pending'})),
        when({'origin':{'const':'automation'}},{'required':['run_binding']},{'not':{'required':['run_binding']}}),
        when({'outcome':enum('unknown','blocked','expired')},props(automation_continuation={'const':'paused_latched'})),
        when({'outcome':enum('failed','unknown','cancelled','expired','blocked')},props(reason_code=ref('Id'))),
        when({'outcome':{'const':'unknown'}},props(resource_status={'const':'unresolved'},effect_status={'not':{'const':'not_sent'}})),
        when({'outcome':{'const':'succeeded'}},{'properties':{'completion':{'properties':{'achieved':ref('CompletionLevel'),'evidence_ids':{'minItems':1}}}}}),
        when({'phase':enum('dispatching','awaiting_evidence')},props(attempts={'minItems':1})),
        when({'outcome':{'const':'cancelled'}},{'properties':{'cancellation':{'properties':{'status':{'const':'confirmed'}}}}}),
        when({'resolution':{'type':'object'}},props(phase={'const':'finished'},automation_continuation={'const':'paused_latched'})),
        when({'resource_status':{'const':'clear'},'effect_status':{'not':{'const':'not_sent'}}},props(resource_evidence_ids={'minItems':1}))]
    for level,effects in [('sent',['possible','acknowledged','verified']),('acknowledged',['acknowledged','verified']),('effect_verified',['verified'])]:
        d['CommandRecord']['allOf'].append(when({'outcome':{'const':'succeeded'},'completion':{'properties':{'achieved':{'const':level}}}},props(effect_status=enum(*effects))))
    for level,accepted in [('sent',['sent','acknowledged','effect_verified']),('acknowledged',['acknowledged','effect_verified']),('effect_verified',['effect_verified'])]:
        d['CommandRecord']['allOf'].append(when({'outcome':{'const':'succeeded'},'completion':{'properties':{'required':{'const':level}}}},
            {'properties':{'completion':{'properties':{'achieved':enum(*accepted)}}}}))
    d['CompletionEvidence'] = obj(dict(evidence_id=ref('Id'),command_id=ref('Id'),attempt_id=ref('Id'),kind=enum('transport_submission','device_ack','fresh_query','device_event','cancel_ack'),
        worker_boot_id=ref('Id'),device_session_id=ref('Id'),observation_id=nullable(ref('Id')),protocol_request_id=nullable(ref('Id')),captured_at=ref('Timestamp'),clock=ref('ClockStatus'),predicate_id=nullable(ref('Id')),predicate_result=nullable({'type':'boolean'}),durable={'const':True}))
    d['ControlTarget'] = obj(dict(version=ref('Revision'),mode=enum('manual','automatic'),holder_id=nullable(ref('Id'))))
    mode_check=when({'mode':{'const':'manual'}},props(holder_id=ref('Id')),props(holder_id={'type':'null'}))
    d['ControlTarget']['allOf']=[mode_check]
    d['PendingChange'] = obj(dict(operation_id=ref('Id'),target_version=ref('Revision'),target_holder_id=nullable(ref('Id')),target_mode=enum('manual','automatic'),reason=text(),requested_by=ref('Id')))
    d['PendingChange']['allOf']=[when({'target_mode':{'const':'manual'}},props(target_holder_id=ref('Id')),props(target_holder_id={'type':'null'}))]
    d['ControlRecord'] = obj(dict(device_id=ref('Id'),revision=ref('Revision'),control_epoch=ref('Id'),effective_version=ref('Revision'),effective_holder_id=nullable(ref('Id')),mode=enum('manual','automatic'),
        pending_change=nullable(ref('PendingChange')),gate_state=enum('ready','fencing','protected'),in_flight_command_ids=array(ref('Id')),unresolved_command_ids=array(ref('Id'))))
    d['ControlRecord']['allOf']=[when({'mode':{'const':'manual'}},props(effective_holder_id=ref('Id')),props(effective_holder_id={'type':'null'})),
        when({'gate_state':{'const':'ready'}},props(pending_change={'type':'null'})),when({'gate_state':{'const':'fencing'}},props(pending_change=ref('PendingChange')))]
    d['BarrierAck'] = obj(dict(barrier_id=ref('Id'),operation_id=ref('Id'),device_id=ref('Id'),controller_boot_id=ref('Id'),worker_boot_id=ref('Id'),control_epoch=ref('Id'),installed_version=ref('Revision'),
        discarded_permit_ids=array(ref('Id')),in_flight_command_ids=array(ref('Id')),unresolved_command_ids=array(ref('Id')),all_write_exits_fenced={'const':True}))
    d['ControlOperation'] = obj(dict(operation_id=ref('Id'),device_id=ref('Id'),request_identity=ref('RequestIdentity'),expected_control=ref('ControlVersion'),state=enum('pending','effective','rejected','indeterminate'),
        barrier_id=nullable(ref('Id')),target=ref('ControlTarget'),controller_boot_id=ref('Id'),worker_boot_id=nullable(ref('Id')),in_flight_snapshot=array(ref('Id')),unresolved_snapshot=array(ref('Id')),applied_revision=nullable(ref('Revision')),failure_code=nullable(ref('Id')),barrier_ack=nullable(ref('BarrierAck')),effective_record_durable={'type':'boolean'}))
    d['ControlOperation']['allOf']=[when({'state':{'const':'effective'}},props(barrier_id=ref('Id'),worker_boot_id=ref('Id'),applied_revision=ref('Revision'),failure_code={'type':'null'},barrier_ack=ref('BarrierAck'),effective_record_durable={'const':True}),
        props(applied_revision={'type':'null'},effective_record_durable={'const':False})),when({'state':enum('rejected','indeterminate')},props(failure_code=ref('Id')))]
    control_input=dict(**identity,expected_control=ref('ControlVersion'),reason=text())
    d['AcquireRequest']=obj(dict(**control_input,force={'type':'boolean','default':False}),('force',))
    d['ReleaseRequest']=obj(control_input)
    d['TransferRequest']=obj(dict(**control_input,target_principal_id=ref('Id'),offer_ttl_ms=ref('Duration')))
    d['TransferAcceptRequest']=obj(control_input)
    d['TransferOffer']=obj(dict(transfer_id=ref('Id'),device_id=ref('Id'),from_principal_id=ref('Id'),target_principal_id=ref('Id'),expected_control=ref('ControlVersion'),expires_at=ref('Timestamp'),state=enum('offered','accepted','expired','cancelled')))
    d['CancelRequest']=obj(dict(**identity,expected_revision=ref('Revision'),reason=text()))
    d['CancelOperation']=obj(dict(operation_id=ref('Id'),command_id=ref('Id'),state=enum('requested','confirmed','unsupported','failed'),reason_code=nullable(ref('Id'))))
    d['DispatchPermit']=obj(dict(permit_id=ref('Id'),command_id=ref('Id'),attempt_id=ref('Id'),dispatch_intent_id=ref('Id'),controller_boot_id=ref('Id'),worker_boot_id=ref('Id'),device_session_id=ref('Id'),
        control_epoch=ref('Id'),control_version=ref('Revision'),authorization_revision=ref('Revision'),origin=enum('manual','automation'),grant_revision=nullable(ref('Revision')),arm_generation=nullable(ref('Revision')),
        gate_revision=ref('Revision'),deadline_policy=ref('Dispatch'),content_digest=ref('Digest')))
    d['DispatchPermit']['allOf']=[when({'origin':{'const':'automation'}},props(grant_revision=ref('Revision'),arm_generation=ref('Revision')),props(grant_revision={'type':'null'},arm_generation={'type':'null'}))]
    d['Validity']=obj(dict(not_before=ref('Timestamp'),not_after=ref('Timestamp'),authorization_policy_revision=ref('Revision')))
    d['DeviceActionScope']=obj(dict(device_id=ref('Id'),action_id=ref('Id'),capability_version=ref('Version')))
    d['RunGrant']=obj(dict(grant_id=ref('Id'),revision=ref('Revision'),run_id=ref('Id'),definition_version=ref('Version'),arm_generation=ref('Revision'),principal_id=ref('Id'),
        device_actions=array(ref('DeviceActionScope'),256,1),parameter_constraints=array(ref('Predicate'),64),validity=ref('Validity'),state=enum('active','revoking','revoked','expired')))
    d['GrantProposal']=obj(dict(run_id=ref('Id'),definition_version=ref('Version'),arm_generation=ref('Revision'),approval_id=ref('Id'),device_actions=array(ref('DeviceActionScope'),256,1),parameter_constraints=array(ref('Predicate'),64),validity=ref('Validity')))
    d['GrantUpdate']=obj(dict(**identity,expected_revision=nullable(ref('Revision')),grant=ref('GrantProposal')))
    d['RevokeRequest']=obj(dict(**identity,expected_revision=ref('Revision'),reason=text()))
    d['TargetApplication']=obj(dict(service_id=ref('Id'),status=enum('pending','applied','indeterminate'),applied_revision=nullable(ref('Revision'))))
    d['TargetApplication']['allOf']=[when({'status':{'const':'applied'}},props(applied_revision=ref('Revision')),props(applied_revision={'type':'null'}))]
    d['MutationReceipt']=obj(dict(operation_id=ref('Id'),state=enum('pending','applied','rejected','indeterminate'),entity_id=ref('Id'),revision=ref('Revision'),targets=array(ref('TargetApplication'))))
    d['MutationReceipt']['allOf']=[when({'state':{'const':'applied'}},props(targets={'items':{'properties':{'status':{'const':'applied'}}}}))]
    d['ActionRef']=obj(dict(provider_id=ref('Id'),device_id=ref('Id'),action_id=ref('Id'),capability_version=ref('Version')))
    d['StepDefinition']=obj(dict(step_id=ref('Id'),action_ref=ref('ActionRef'),parameters=ref('Payload'),required={'type':'boolean'},on_failure=enum('stop','continue_if_independent'),depends_on=array(ref('Id'),64),
        preconditions=array(ref('Predicate'),64),completion=ref('CompletionLevel'),deadlines=obj(dict(max_queue_ms=ref('Duration'),evidence_timeout_ms=ref('Duration'))),independence_proof_revision=ref('Revision')),('independence_proof_revision',))
    d['StepDefinition']['allOf']=[when({'on_failure':{'const':'continue_if_independent'}},{'properties':{'required':{'const':False}},'required':['independence_proof_revision']}),when({'required':{'const':True}},props(on_failure={'const':'stop'}))]
    d['RequiredStep']={'allOf':[ref('StepDefinition'),props(required={'const':True},on_failure={'const':'stop'})]}
    d['StepGroup']={'oneOf':[obj(dict(kind={'const':'sequential'},steps=array(ref('StepDefinition'),64,1))),obj(dict(kind={'const':'parallel'},steps=array(ref('RequiredStep'),64,1)))]}
    d['TriggerBinding']=obj(dict(provider_id=ref('Id'),device_id=ref('Id'),trigger_id=ref('Id'),capability_version=ref('Version'),conditions=array(ref('Predicate'),64)))
    d['TransitionDefinition']=obj(dict(transition_id=ref('Id'),from_state=ref('Id'),to_state=ref('Id'),priority=integer(100000),trigger=ref('TriggerBinding'),guards=array(ref('Predicate'),64),
        exit_steps=array(ref('RequiredStep'),64),transition_steps=array(ref('RequiredStep'),64),enter_steps=array(ref('RequiredStep'),64)))
    d['Definition']= {'oneOf':[obj(dict(kind={'const':'rule'},name=text(),trigger=ref('TriggerBinding'),groups=array(ref('StepGroup'),64,1))),
        obj(dict(kind={'const':'state_machine'},name=text(),initial_state=ref('Id'),states=array(ref('Id'),128,1),transitions=array(ref('TransitionDefinition'),256,1)))]}
    d['DefinitionCreate']=obj(dict(**identity,definition=ref('Definition')))
    d['DraftUpdate']=obj(dict(expected_revision=ref('Revision'),definition=ref('Definition')))
    d['PublishRequest']=obj(dict(**identity,expected_revision=ref('Revision')))
    d['DefinitionRecord']=obj(dict(definition_id=ref('Id'),revision=ref('Revision'),definition_version=nullable(ref('Version')),definition=ref('Definition'),published={'type':'boolean'}))
    d['DefinitionRecord']['allOf']=[when({'published':{'const':True}},props(definition_version=ref('Version')),props(definition_version={'type':'null'}))]
    d['RunCreate']=obj(dict(**identity,definition_id=ref('Id'),definition_version=ref('Version')))
    d['RunRevisionRequest']=obj(dict(expected_revision=ref('Revision')))
    d['RunMutationRequest']=obj(dict(**identity,expected_revision=ref('Revision'),reason=text()))
    d['ArmRequest']=obj(dict(**identity,expected_revision=ref('Revision'),preflight_id=ref('Id'),approval_id=ref('Id')))
    d['ResumeRequest']=obj(dict(**identity,expected_revision=ref('Revision'),preview_id=ref('Id'),preview_digest=ref('Digest')))
    d['StepResult']=obj(dict(step_id=ref('Id'),command_id=nullable(ref('Id')),outcome=enum('not_executed','pending','succeeded','failed','unknown','blocked','cancelled','expired'),evidence_ids=array(ref('Id'))))
    d['TransitionRecord']=obj(dict(transition_id=ref('Id'),from_state=ref('Id'),to_state=ref('Id'),stage=enum('validating','exit','transition','enter','committing','completed','failed','unknown'),step_results=array(ref('StepResult'))))
    d['GrantBinding']=obj(dict(controller_id=ref('Id'),grant_id=ref('Id'),grant_revision=ref('Revision'),arm_generation=ref('Revision'),application_state=enum('pending','applied','revoking','revoked','indeterminate')))
    d['RunRecord']=obj(dict(run_id=ref('Id'),definition_id=ref('Id'),definition_version=ref('Version'),revision=ref('Revision'),business_state=nullable(ref('Id')),transition=nullable(ref('TransitionRecord')),
        lifecycle=enum('disarmed','armed','running','paused','completed'),execution_summary=enum('pending','succeeded','completed_with_failures','failed','unknown','blocked'),arm_generation=ref('Revision'),grant_bindings=array(ref('GrantBinding')),active_execution_id=nullable(ref('Id'))))
    d['RunRecord']['allOf']=[when({'lifecycle':enum('armed','running')},props(grant_bindings={'minItems':1,'items':{'properties':{'application_state':{'const':'applied'}}}}))]
    d['CheckResult']=obj(dict(code=ref('Id'),passed={'type':'boolean'},details=text()))
    d['Preflight']=obj(dict(preflight_id=ref('Id'),run_id=ref('Id'),run_revision=ref('Revision'),passed={'type':'boolean'},checks=array(ref('CheckResult')),observed_at=ref('Timestamp')))
    d['Preflight']['allOf']=[when({'passed':{'const':True}},props(checks={'minItems':1,'items':{'properties':{'passed':{'const':True}}}}))]
    d['RecoveryPreview']=obj(dict(preview_id=ref('Id'),preview_digest=ref('Digest'),run_id=ref('Id'),run_revision=ref('Revision'),proposed_step_ids=array(ref('Id')),unresolved_command_ids=array(ref('Id')),observations=array(ref('Observation'))))
    d['SubscriptionRequest']=obj(dict(scope=array(ref('Id'),64,1),event_types=array(ref('Id'),64,1),resume_cursor=ref('Revision')),('resume_cursor',))
    d['Subscription']=obj(dict(subscription_id=ref('Id'),stream_id=ref('Id'),snapshot_id=ref('Id'),snapshot_cursor=ref('Revision'),expires_in_ms=ref('Duration')))
    d['Snapshot']=obj(dict(snapshot_id=ref('Id'),stream_id=ref('Id'),snapshot_cursor=ref('Revision'),commands=array(ref('CommandRecord')),controls=array(ref('ControlRecord')),observations=array(ref('Observation')),next_cursor=nullable(ref('Id'))))
    ws_common=dict(subscription_id=ref('Id'),stream_id=ref('Id'),cursor=ref('Revision'),previous_cursor=nullable(ref('Revision')),entity_id=ref('Id'),entity_revision=ref('Revision'))
    d['WsEvent']={'oneOf':[obj(dict(**ws_common,event_type={'const':tag},payload=ref(model))) for tag,model in
        [('command.updated','CommandRecord'),('control.updated','ControlRecord'),('device.observed','Observation'),('trigger.received','EventEnvelope'),('run.updated','RunRecord')]]}
    d['WsResync']=obj(dict(subscription_id=ref('Id'),stream_id=ref('Id'),event_type={'const':'resync.required'},code={'const':'RESYNC_REQUIRED'},reason=text()))
    d['WsFrame']={'oneOf':[ref('WsEvent'),ref('WsResync')]}
    d['EventReceipt']=obj(dict(event_id=ref('Id'),ingest_id=ref('Id'),received_at=ref('Timestamp'),receive_sequence=ref('Revision'),age_at_admission_ms=nullable(integer()),validity_basis=enum('bounded_age','trusted_utc','unproven'),duplicate={'type':'boolean'}))
    d['Session']=obj(dict(principal_id=ref('Id'),session_id=ref('Id'),authorization_revision=ref('Revision'),permissions=array(ref('Id')),validity=ref('Validity')))
    d['Meta']=obj(dict(protocol_version={'const':VERSION},component_version=ref('Version'),service_id=ref('Id'),service_boot_id=ref('Id'),features=array(ref('Id')),limits_profile=ref('Id')))
    d['DevicePage']=obj(dict(items=array(ref('DeviceDescriptor')),next_cursor=nullable(ref('Id')),catalog_revision=ref('Revision')))
    d['ErrorCode']=enum('INVALID_REQUEST','UNKNOWN_WRITE_FIELD','UNSUPPORTED_COMPLETION','INVALID_CONTINUE_POLICY','AUTH_REQUIRED','PERMISSION_DENIED','GRANT_REVOKED','NOT_FOUND',
        'REVISION_CONFLICT','IDEMPOTENCY_CONFLICT','CONTROL_VERSION_MISMATCH','CONTROL_NOT_EFFECTIVE','DEVICE_IN_FLIGHT','REQUEST_EXPIRED','REQUEST_EPOCH_RETIRED',
        'PAYLOAD_TOO_LARGE','CAPACITY_EXCEEDED','CRITICAL_STORAGE_UNAVAILABLE','WORKER_NOT_READY','CLOCK_UNTRUSTED','RESYNC_REQUIRED','PROTOCOL_INCOMPATIBLE')
    d['Error']=obj(dict(code=ref('ErrorCode'),message_key=ref('Id'),request_id=ref('Id'),details=ref('Payload'),existing_command_id=nullable(ref('Id')),retry_advice=nullable(enum('query_existing','wait_then_reassess','do_not_retry'))))
    envelope=dict(request_id=ref('Id'),service_id=ref('Id'),service_boot_id=ref('Id'),protocol_version={'const':VERSION})
    d['ErrorResponse']=obj(dict(**envelope,error=ref('Error')))
    models=['Meta','ClockStatus','Session','RequestContext','DevicePage','CapabilityCatalog','Observation','CommandRecord','CancelOperation','ControlRecord','ControlOperation','TransferOffer',
        'MutationReceipt','Subscription','Snapshot','EventReceipt','DefinitionRecord','RunRecord','Preflight','RecoveryPreview']
    for model in models: d[model+'Response']=obj(dict(**envelope,data=ref(model)))
    schema={'$schema':DIALECT,'$id':BASE,'title':'LeafSeamer 首闭环协议模型','description':'工程契约 draft.2；结构校验不等于执行授权或设备安全证明。','$defs':d}
    routes=[]
    def route(service,method,path,name,request,response,status='200',permission='status.read'):
        routes.append(dict(service=service,method=method,path='/api/v1'+path,operation_id=name,request=request,response=response,status=status,permission=permission))
    for method,path,name,req,res,status,perm in [
        ('get','/meta','getMeta',None,'MetaResponse','200','status.read'),('get','/clock','getClock',None,'ClockStatusResponse','200','status.read'),
        ('get','/session','getSession',None,'SessionResponse','200','session.read'),('post','/request-contexts','createRequestContext','RequestContextRequest','RequestContextResponse','201','request.create'),
        ('post','/subscriptions','createSubscription','SubscriptionRequest','SubscriptionResponse','201','status.read'),('get','/subscriptions/{subscription_id}/snapshot','getSnapshot',None,'SnapshotResponse','200','status.read')]:
        route('common',method,path,name,req,res,status,perm)
    for method,path,name,req,res,status,perm in [
        ('get','/devices','listDevices',None,'DevicePageResponse','200','device.read'),('get','/devices/{device_id}/capabilities','getCapabilities',None,'CapabilityCatalogResponse','200','device.read'),
        ('get','/devices/{device_id}/state','getDeviceState',None,'ObservationResponse','200','device.read'),('post','/commands','submitCommand','CommandRequest','CommandRecordResponse','202','device.command'),
        ('get','/commands/{command_id}','getCommand',None,'CommandRecordResponse','200','device.read'),('post','/commands/{command_id}/cancel','cancelCommand','CancelRequest','CancelOperationResponse','202','command.cancel'),
        ('get','/control-operations/{operation_id}','getControlOperation',None,'ControlOperationResponse','200','control.read'),('get','/devices/{device_id}/control','getControl',None,'ControlRecordResponse','200','control.read'),
        ('post','/devices/{device_id}/control/acquire','acquireControl','AcquireRequest','ControlOperationResponse','202','control.acquire'),
        ('post','/devices/{device_id}/control/release','releaseControl','ReleaseRequest','ControlOperationResponse','202','control.release'),
        ('post','/devices/{device_id}/control/transfers','offerTransfer','TransferRequest','TransferOfferResponse','201','control.transfer'),
        ('post','/devices/{device_id}/control/transfers/{transfer_id}/accept','acceptTransfer','TransferAcceptRequest','ControlOperationResponse','202','control.accept'),
        ('put','/run-grants/{grant_id}','updateRunGrant','GrantUpdate','MutationReceiptResponse','202','grant.manage'),('post','/run-grants/{grant_id}/revoke','revokeRunGrant','RevokeRequest','MutationReceiptResponse','202','grant.revoke')]:
        route('controller',method,path,name,req,res,status,perm)
    for method,path,name,req,res,status,perm in [
        ('put','/providers/{provider_id}/catalog','updateCatalog','CatalogUpdate','CapabilityCatalogResponse','200','provider.publish'),
        ('post','/providers/{provider_id}/events','ingestEvent','EventEnvelope','EventReceiptResponse','202','provider.publish'),
        ('post','/definitions','createDefinition','DefinitionCreate','DefinitionRecordResponse','201','definition.edit'),('put','/definitions/{definition_id}/draft','updateDraft','DraftUpdate','DefinitionRecordResponse','200','definition.edit'),
        ('post','/definitions/{definition_id}/publish','publishDefinition','PublishRequest','DefinitionRecordResponse','201','definition.publish'),
        ('post','/runs','createRun','RunCreate','RunRecordResponse','201','run.manage'),('get','/runs/{run_id}','getRun',None,'RunRecordResponse','200','run.read'),
        ('post','/runs/{run_id}/preflight','preflightRun','RunRevisionRequest','PreflightResponse','200','run.read'),
        ('post','/runs/{run_id}/arm','armRun','ArmRequest','MutationReceiptResponse','202','run.arm'),('post','/runs/{run_id}/pause','pauseRun','RunMutationRequest','MutationReceiptResponse','202','run.pause'),
        ('post','/runs/{run_id}/recovery-preview','previewRecovery','RunRevisionRequest','RecoveryPreviewResponse','200','run.read'),('post','/runs/{run_id}/resume','resumeRun','ResumeRequest','MutationReceiptResponse','202','run.resume')]:
        route('seamer',method,path,name,req,res,status,perm)
    files={'first-loop.schema.json':schema,'routes.json':routes}
    for service in ('controller','seamer'):
        # 各OpenAPI自包含，转换引用不需要联网解析Schema标识。
        schemas=json.loads(json.dumps(d).replace('#/$defs/','#/components/schemas/'))
        api={'openapi':'3.1.1','jsonSchemaDialect':DIALECT,'info':{'title':'LeafSeamer '+service+' 首闭环','version':VERSION},
            'servers':[{'url':'https://'+service+'.example.invalid'}], 'security':[{'bearerAuth':[]}], 'paths':{},
            'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer','description':'业务认证占位；令牌格式、签发与配对在F04冻结，不代表已实现。'}},'schemas':schemas}}
        def media(model): return {'application/json':{'schema':{'$ref':'#/components/schemas/'+model}}}
        for r in routes:
            if r['service'] not in ('common',service): continue
            operation={'operationId':r['operation_id'],'summary':r['operation_id'],'x-permission':r['permission'],
                'responses':{r['status']:{'description':'可靠受理；202不是设备完成或接管生效。' if r['status']=='202' else '查询或管理结果','content':media(r['response'])}}}
            params=[{'name':p,'in':'path','required':True,'schema':{'$ref':'#/components/schemas/Id'}} for p in re.findall(r'{(\w+)}',r['path'])]
            if r['operation_id']=='listDevices': params.append({'name':'cursor','in':'query','required':False,'schema':{'$ref':'#/components/schemas/Id'}})
            if r['operation_id']=='getSnapshot': params.append({'name':'cursor','in':'query','required':False,'schema':{'$ref':'#/components/schemas/Id'}})
            if params: operation['parameters']=params
            if r['request']:
                operation['requestBody']={'required':True,'content':media(r['request'])}
                if r['status'] in ('201','202'): operation['responses']['200']={'description':'同请求身份的既有受理结果；不新增设备副作用。','content':media(r['response'])}
            for status in ('400','401','403','404','409','410','413','422','429','503'):
                operation['responses'][status]={'description':'结构、授权、版本、限额或依赖拒绝；错误不授权重发。','content':media('ErrorResponse')}
            api['paths'].setdefault(r['path'],{})[r['method']]=operation
        api['paths']['/api/v1/events']={'get':{'operationId':'openEvents','summary':'仅描述WebSocket升级；帧由WsFrame校验',
            'x-websocket-frame-schema':'#/components/schemas/WsFrame','responses':{'101':{'description':'协议升级；之后不是HTTP JSON响应。'},'401':{'description':'未授权','content':media('ErrorResponse')}}}}
        files[service+'.openapi.json']=api
    return files

def main():
    parser=argparse.ArgumentParser(description='生成或核对文档契约，不执行业务。')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    for name,value in build().items():
        content=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
        path=ROOT/name
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8')!=content: raise SystemExit('生成物过时：'+name)
        else: path.write_text(content,encoding='utf-8',newline='\n')
    print('契约生成物核对通过' if args.check else '契约生成物已写入')

if __name__=='__main__': main()
