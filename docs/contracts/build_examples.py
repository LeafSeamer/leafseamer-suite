"""人工编排的合成协议例子；不从Schema自动抽取样例，不执行设备动作。"""
from copy import deepcopy as copy
from pathlib import Path
import argparse
import hashlib
import json

ROOT=Path(__file__).resolve().parent
V='1.0.0-draft.2'
T='2026-10-17T00:00:00.000Z'
T2='2026-10-17T00:01:00.000Z'
DIGEST='sha256:'+'a'*64

def examples():
    e={}
    identity={'context_id':'ctx-test','idempotency_key':'key-test'}
    control={'epoch':'control-test','version':'8'}
    actor={'principal_id':'user-test','session_id':'session-test','authorization_revision':'2'}
    request_identity=dict(service_id='controller-test',context_epoch='ctx-epoch-test',principal_id='user-test',operation='submitCommand',**identity)
    clock={'status':'synchronized','source_ref':'clock-test','sampled_at':T,'offset_ms':0,'uncertainty_ms':5,'sample_age_ms':1,'policy_revision':'1'}
    scene={'collection_ref':'collection-test','scene_id':'scene-b','catalog_revision':'3'}
    dispatch={'mode':'immediate','max_queue_ms':2000}
    schema_doc={'type':'object','properties':{'scene_ref':{'type':'string'}},'required':['scene_ref'],'additionalProperties':False}
    # 目录Schema摘要按RFC8785计算；示例构建不调用生产代码。
    import rfc8785
    descriptor={'schema_id':'schema-test','digest':'sha256:'+hashlib.sha256(rfc8785.dumps(schema_doc)).hexdigest(),'dialect':'https://json-schema.org/draft/2020-12/schema','document':schema_doc}
    action={'action_id':'test.set','capability_version':V,'parameters_schema':descriptor,'result_schema':descriptor,'resources':['device/test/value'],
        'completion':{'supported':['effect_verified'],'default':'effect_verified','evidence_policy_id':'evidence-test'},'cancel':{'mode':'before_dispatch_only'},'retry':{'mode':'never'},
        'preconditions_schema':descriptor,'read_set':[],'write_set':['device/test/value'],'evidence_timeout_ms':5000,'limits_profile':'sim-first-loop',
        'platforms':[{'os':'windows','arch':'x64','status':'untested'}],'dependencies':[]}
    trigger={'trigger_id':'test.changed','capability_version':V,'payload_schema':descriptor,'delivery_semantics':'discrete','time_requirement':'relative_age','max_age_ms':2000,'causation_support':'none','sampling_policy':None}
    device={'device_id':'obs-test','device_kind':'obs','display_name':'隔离测试','connection_state':'ready','actions':[action],'triggers':[trigger],'state_schema':descriptor}
    catalog={'provider_id':'provider-test','provider_boot_id':'provider-boot-test','catalog_revision':'3','module_id':'module-test','module_version':V,'devices':[device]}
    observation={'observation_id':'obs-evidence-test','device_id':'obs-test','provider_boot_id':'provider-boot-test','device_session_id':'device-session-test','state_revision':'5','observed_at':T,'clock':clock,'freshness_ms':10,'values':{'scene_ref':scene},'integrity':'complete'}
    event={'event_id':'event-test','provider_id':'provider-test','provider_boot_id':'provider-boot-test','source_sequence':'7','trigger_id':'test.changed','capability_version':V,'device_id':'obs-test','occurred_at':None,'observed_at':T,'clock':clock,'payload':{'scene_ref':'scene-b'}}
    command=dict(**identity,device_id='obs-test',action_id='obs.program_scene.set',capability_version=V,parameters={'scene_ref':scene},expected_control=control,origin='manual',required_completion='effect_verified',preconditions=[],dispatch=dispatch,evidence_timeout_ms=5000)
    run_binding={'run_id':'run-test','definition_version':V,'grant_id':'grant-test','grant_revision':'2','arm_generation':'4','step_id':'step-test','logical_action_id':'action-test'}
    completion={'required':'effect_verified','achieved':None,'evidence_policy_id':'evidence-test','evidence_ids':[]}
    record={'command_id':'command-test','revision':'1','request_identity':request_identity,'content_digest':DIGEST,'target':{'device_id':'obs-test','action_id':'obs.program_scene.set','capability_version':V},'actor':actor,'origin':'manual',
        'accepted_at':T,'phase':'queued','outcome':'pending','effect_status':'not_sent','resource_status':'held','resource_evidence_ids':[],'cancellation':{'status':'none','operation_id':None,'reason_code':None},'completion':completion,
        'attempts':[],'dispatch':dispatch,'control_binding':control,'automation_continuation':'eligible','reason_code':None,'retry_policy':None}
    attempt={'attempt_id':'attempt-test','worker_boot_id':'worker-test','device_session_id':'device-session-test','dispatch_intent_id':'intent-test','send_started_at':T,'protocol_request_id':'wire-test','evidence_ids':['evidence-test'],'outcome':'succeeded'}
    ack={'barrier_id':'barrier-test','operation_id':'control-op-test','device_id':'obs-test','controller_boot_id':'controller-boot-test','worker_boot_id':'worker-test','control_epoch':'control-test','installed_version':'9',
        'discarded_permit_ids':['permit-old'],'in_flight_command_ids':['command-test'],'unresolved_command_ids':[],'all_write_exits_fenced':True}
    operation={'operation_id':'control-op-test','device_id':'obs-test','request_identity':dict(request_identity,operation='acquireControl'),'expected_control':control,'state':'pending','barrier_id':'barrier-test',
        'target':{'version':'9','mode':'manual','holder_id':'user-test'},'controller_boot_id':'controller-boot-test','worker_boot_id':'worker-test','in_flight_snapshot':[],'unresolved_snapshot':[],'applied_revision':None,'failure_code':None,'barrier_ack':None,'effective_record_durable':False}
    control_record={'device_id':'obs-test','revision':'1','control_epoch':'control-test','effective_version':'8','effective_holder_id':None,'mode':'automatic','pending_change':None,'gate_state':'ready','in_flight_command_ids':[],'unresolved_command_ids':[]}
    mutation={'operation_id':'mutation-test','state':'pending','entity_id':'run-test','revision':'1','targets':[{'service_id':'controller-test','status':'pending','applied_revision':None}]}
    validity={'not_before':T,'not_after':T2,'authorization_policy_revision':'1'}
    grant={'grant_id':'grant-test','revision':'2','run_id':'run-test','definition_version':V,'arm_generation':'4','principal_id':'service-test','device_actions':[{'device_id':'obs-test','action_id':'obs.program_scene.set','capability_version':V}],
        'parameter_constraints':[],'validity':validity,'state':'active'}
    action_ref={'provider_id':'provider-test','device_id':'obs-test','action_id':'obs.program_scene.set','capability_version':V}
    step={'step_id':'step-test','action_ref':action_ref,'parameters':{'scene_ref':scene},'required':True,'on_failure':'stop','depends_on':[],'preconditions':[],'completion':'effect_verified','deadlines':{'max_queue_ms':2000,'evidence_timeout_ms':5000}}
    binding={'provider_id':'provider-test','device_id':'obs-test','trigger_id':'test.changed','capability_version':V,'conditions':[]}
    transition={'transition_id':'transition-test','from_state':'state-a','to_state':'state-b','priority':1,'trigger':binding,'guards':[],'exit_steps':[],'transition_steps':[step],'enter_steps':[]}
    definition={'kind':'state_machine','name':'隔离闭环','initial_state':'state-a','states':['state-a','state-b'],'transitions':[transition]}
    definition_record={'definition_id':'definition-test','revision':'1','definition_version':None,'definition':definition,'published':False}
    run={'run_id':'run-test','definition_id':'definition-test','definition_version':V,'revision':'1','business_state':'state-a','transition':None,'lifecycle':'disarmed','execution_summary':'pending','arm_generation':'0','grant_bindings':[],'active_execution_id':None}
    control_input=dict(**identity,expected_control=control,reason='隔离验证')
    e.update(Meta={'protocol_version':V,'component_version':V,'service_id':'controller-test','service_boot_id':'controller-boot-test','features':['commands-v1'],'limits_profile':'sim-first-loop'},ClockStatus=clock,
        Session=dict(actor,permissions=['device.read'],validity=validity),RequestContextRequest={'audience':'controller-test','operations':['submitCommand'],'ttl_ms':60000,'max_unique_requests':256},
        RequestContext={'context_id':'ctx-test','service_id':'controller-test','principal_id':'user-test','audience':'controller-test','operations':['submitCommand'],'issued_at':T,'expires_at':T2,'ttl_ms':60000,'max_unique_requests':256,'context_epoch':'ctx-epoch-test'},
        DevicePage={'items':[device],'next_cursor':None,'catalog_revision':'3'},CapabilityCatalog=catalog,CatalogUpdate={'expected_revision':None,'catalog':catalog},Observation=observation,EventEnvelope=event,CommandRequest=command,CommandRecord=record,
        CancelRequest=dict(**identity,expected_revision='1',reason='隔离取消'),CancelOperation={'operation_id':'cancel-test','command_id':'command-test','state':'requested','reason_code':None},
        AcquireRequest=control_input,ReleaseRequest=control_input,TransferRequest=dict(**control_input,target_principal_id='user-b',offer_ttl_ms=60000),TransferAcceptRequest=control_input,
        TransferOffer={'transfer_id':'transfer-test','device_id':'obs-test','from_principal_id':'user-test','target_principal_id':'user-b','expected_control':control,'expires_at':T2,'state':'offered'},
        ControlRecord=control_record,ControlOperation=operation,BarrierAck=ack,GrantUpdate=dict(**identity,expected_revision=None,grant=grant),RevokeRequest=dict(**identity,expected_revision='2',reason='暂停测试'),MutationReceipt=mutation,
        DefinitionCreate=dict(**identity,definition=definition),DraftUpdate={'expected_revision':'1','definition':definition},PublishRequest=dict(**identity,expected_revision='1'),DefinitionRecord=definition_record,
        RunCreate=dict(**identity,definition_id='definition-test',definition_version=V),RunRecord=run,RunRevisionRequest={'expected_revision':'1'},RunMutationRequest=dict(**identity,expected_revision='1',reason='暂停测试'),
        ArmRequest=dict(**identity,expected_revision='1',preflight_id='preflight-test',approval_id='approval-test'),ResumeRequest=dict(**identity,expected_revision='1',preview_id='preview-test',preview_digest=DIGEST),
        Preflight={'preflight_id':'preflight-test','run_id':'run-test','run_revision':'1','passed':True,'checks':[{'code':'storage-ready','passed':True,'details':'模拟'}],'observed_at':T},
        RecoveryPreview={'preview_id':'preview-test','preview_digest':DIGEST,'run_id':'run-test','run_revision':'1','proposed_step_ids':[],'unresolved_command_ids':[],'observations':[observation]},
        SubscriptionRequest={'scope':['obs-test'],'event_types':['command.updated']},Subscription={'subscription_id':'subscription-test','stream_id':'stream-test','snapshot_id':'snapshot-test','snapshot_cursor':'8','expires_in_ms':60000},
        Snapshot={'snapshot_id':'snapshot-test','stream_id':'stream-test','snapshot_cursor':'8','commands':[record],'controls':[control_record],'observations':[observation],'next_cursor':None},
        EventReceipt={'event_id':'event-test','ingest_id':'ingest-test','received_at':T,'receive_sequence':'1','age_at_admission_ms':10,'validity_basis':'bounded_age','duplicate':False})
    e['GrantUpdate']['grant']={k:copy(v) for k,v in grant.items() if k not in ('grant_id','revision','principal_id','state')}
    e['GrantUpdate']['grant']['approval_id']='approval-test'
    e['Session'].pop('session_id',None)
    e['Session']['session_id']='session-test'
    e['CompletionEvidence']={'evidence_id':'evidence-test','command_id':'command-test','attempt_id':'attempt-test','kind':'fresh_query','worker_boot_id':'worker-test','device_session_id':'device-session-test',
        'observation_id':'obs-evidence-test','protocol_request_id':'query-test','captured_at':T2,'clock':clock,'predicate_id':'target-scene','predicate_result':True,'durable':True}
    e['DispatchPermit']={'permit_id':'permit-test','command_id':'command-test','attempt_id':'attempt-test','dispatch_intent_id':'intent-test','controller_boot_id':'controller-boot-test','worker_boot_id':'worker-test','device_session_id':'device-session-test',
        'control_epoch':'control-test','control_version':'8','authorization_revision':'2','origin':'manual','grant_revision':None,'arm_generation':None,'gate_revision':'1','deadline_policy':dispatch,'content_digest':DIGEST}
    e['StepDefinition']=step
    e['Definition']=definition
    e['RunGrant']=grant
    e['RetryPolicy']={'policy_id':'retry-test','allowed_error_codes':['TEMPORARY_REJECT'],'safety_predicate_id':'no-effect','max_attempts':2,'backoff_ms':100,'total_budget_ms':1000}
    e['WsFrame']={'subscription_id':'subscription-test','stream_id':'stream-test','cursor':'9','previous_cursor':'8','entity_id':'command-test','entity_revision':'1','event_type':'command.updated','payload':record}
    envelope={'request_id':'request-test','service_id':'controller-test','service_boot_id':'controller-boot-test','protocol_version':V}
    response_models=['Meta','ClockStatus','Session','RequestContext','DevicePage','CapabilityCatalog','Observation','CommandRecord','CancelOperation','ControlRecord','ControlOperation','TransferOffer','MutationReceipt','Subscription','Snapshot','EventReceipt','DefinitionRecord','RunRecord','Preflight','RecoveryPreview']
    for model in response_models: e[model+'Response']=dict(**envelope,data=e[model])
    e['ErrorResponse']=dict(**envelope,error={'code':'CONTROL_VERSION_MISMATCH','message_key':'control.version_mismatch','request_id':'request-test','details':{'current_version':'9'},'existing_command_id':None,'retry_advice':'query_existing'})
    cases=[]
    def add(name,model,value,valid=True,semantic=True,note='合成正例'):
        cases.append({'case_id':name,'model':model,'schema_valid':valid,'contract_valid':semantic,'note':note,'instance':copy(value)})
    for model,value in e.items(): add('valid-'+model,model,value)
    auto=copy(command); auto.update(origin='automation',run_binding=run_binding); add('valid-automation','CommandRequest',auto)
    scheduled=copy(auto); scheduled['dispatch']={'mode':'scheduled','occurrence_id':'occ-test','not_before':T,'not_after':T2,'clock_policy_revision':'1','max_queue_ms':2000};add('valid-scheduled','CommandRequest',scheduled)
    success=copy(record);success.update(phase='finished',outcome='succeeded',effect_status='verified',resource_status='clear',resource_evidence_ids=['evidence-test'],attempts=[attempt]);success['completion'].update(achieved='effect_verified',evidence_ids=['evidence-test']);add('valid-success','CommandRecord',success)
    unknown=copy(record);unknown.update(phase='finished',outcome='unknown',effect_status='possible',resource_status='unresolved',automation_continuation='paused_latched',reason_code='DEVICE_RESULT_UNKNOWN',attempts=[dict(attempt,outcome='unknown')]);add('valid-unknown','CommandRecord',unknown)
    late=copy(unknown);late['resolution']={'revision':'2','resolved_outcome':'succeeded','evidence_ids':['evidence-late'],'resolved_at':T2,'resolver':'worker-test'};add('valid-late-resolution','CommandRecord',late)
    retry=copy(record);retry.update(effect_status='acknowledged',attempts=[dict(attempt,outcome='failed')],retry_policy=e['RetryPolicy']);add('valid-retry-queued-history','CommandRecord',retry)
    cancelled=copy(record);cancelled.update(phase='finished',outcome='cancelled',resource_status='clear',reason_code='USER_CANCELLED');cancelled['cancellation'].update(status='confirmed',operation_id='cancel-test');add('valid-cancelled-before-send','CommandRecord',cancelled)
    effective=copy(operation);effective.update(state='effective',barrier_ack=ack,applied_revision='2',effective_record_durable=True,in_flight_snapshot=['command-test']);add('valid-effective-with-inflight','ControlOperation',effective)
    pending=copy(control_record);pending.update(gate_state='fencing',pending_change={'operation_id':'control-op-test','target_version':'9','target_holder_id':'user-test','target_mode':'manual','reason':'接管','requested_by':'user-test'});add('valid-control-pending','ControlRecord',pending)
    optional=copy(step);optional.update(required=False,on_failure='continue_if_independent',independence_proof_revision='3');add('valid-optional-step','StepDefinition',optional)
    rule={'kind':'rule','name':'独立步骤','trigger':binding,'groups':[{'kind':'sequential','steps':[optional]}]};add('valid-rule-optional','Definition',rule)
    armed=copy(run);armed.update(lifecycle='armed',arm_generation='4',grant_bindings=[{'controller_id':'controller-test','grant_id':'grant-test','grant_revision':'2','arm_generation':'4','application_state':'applied'}]);add('valid-run-armed','RunRecord',armed)
    def bad(name,model,base,path,value=None,remove=False,structural=True,note='必须拒绝'):
        obj=copy(base); cursor=obj
        for key in path[:-1]: cursor=cursor[key]
        if remove: del cursor[path[-1]]
        else: cursor[path[-1]]=value
        add(name,model,obj,not structural,False,note)
    for name,path,val in [('unknown-field',['role'],'admin'),('server-field',['principal_id'],'admin'),('numeric-revision',['expected_control','version'],8),('null-id',['device_id'],None),
        ('extra-parameter',['parameters','unexpected'],True),('weak-obs-evidence',['required_completion'],'sent'),('unbounded-queue',['dispatch','max_queue_ms'],0),('string-timeout',['evidence_timeout_ms'],'5000'),('float-timeout',['evidence_timeout_ms'],2.5),('manual-run-binding',['run_binding'],run_binding)]:
        bad('invalid-'+name,'CommandRequest',command,path,val)
    bad('invalid-missing-automation-binding','CommandRequest',auto,['run_binding'],remove=True)
    bad('invalid-mixed-time-mode','CommandRequest',scheduled,['dispatch','mode'],'immediate')
    bad('invalid-date','CommandRequest',scheduled,['dispatch','not_after'],'2026-02-30T00:00:00.000Z')
    bad('invalid-reversed-window','CommandRequest',scheduled,['dispatch','not_after'],'2026-10-16T23:59:59.000Z',structural=False)
    bad('invalid-finished-pending','CommandRecord',record,['phase'],'finished')
    bad('invalid-success-queued','CommandRecord',success,['phase'],'queued')
    bad('invalid-success-without-evidence','CommandRecord',success,['completion','evidence_ids'],[])
    bad('invalid-success-below-standard','CommandRecord',success,['completion','achieved'],'sent')
    bad('invalid-success-claims-unsent','CommandRecord',success,['effect_status'],'not_sent')
    bad('invalid-release-resource-no-evidence','CommandRecord',success,['resource_evidence_ids'],[])
    bad('invalid-unknown-resource-clear','CommandRecord',unknown,['resource_status'],'clear')
    bad('invalid-unknown-without-reason','CommandRecord',unknown,['reason_code'],None)
    bad('invalid-late-resumes','CommandRecord',late,['automation_continuation'],'eligible')
    bad('invalid-requested-is-cancelled','CommandRecord',cancelled,['cancellation','status'],'requested')
    bad('invalid-forged-effective','ControlOperation',effective,['effective_record_durable'],False)
    bad('invalid-effective-no-ack','ControlOperation',effective,['barrier_ack'],None)
    bad('invalid-partial-fence','ControlOperation',effective,['barrier_ack','all_write_exits_fenced'],False)
    for field,value in [('barrier_id','wrong-barrier'),('controller_boot_id','old-controller'),('worker_boot_id','old-worker'),('installed_version','8'),('control_epoch','old-epoch'),('operation_id','old-operation'),('device_id','other-device')]:
        bad('invalid-ack-'+field,'ControlOperation',effective,['barrier_ack',field],value,structural=False)
    bad('invalid-version-not-advanced','ControlOperation',operation,['target','version'],'8',structural=False)
    bad('invalid-lost-inflight','ControlOperation',effective,['in_flight_snapshot'],[],structural=False)
    bad('invalid-lost-unknown','ControlOperation',effective,['barrier_ack','unresolved_command_ids'],['unknown-test'],structural=False)
    bad('invalid-ready-with-pending','ControlRecord',pending,['gate_state'],'ready')
    bad('invalid-auto-has-holder','ControlRecord',control_record,['effective_holder_id'],'user-test')
    bad('invalid-transition-optional','Definition',definition,['transitions',0,'transition_steps',0],optional)
    parallel=copy(rule);parallel['groups'][0]['kind']='parallel';add('invalid-parallel-optional','Definition',parallel,False,False)
    bad('invalid-continue-without-proof','StepDefinition',optional,['independence_proof_revision'],remove=True)
    bad('invalid-unknown-state-reference','Definition',definition,['initial_state'],'nonexistent',structural=False)
    bad('invalid-duplicate-state','Definition',definition,['states'],['state-a','state-a'],structural=False)
    bad('invalid-permit-manual-grant','DispatchPermit',e['DispatchPermit'],['grant_revision'],'1')
    bad('invalid-sync-without-quality','ClockStatus',clock,['uncertainty_ms'],None)
    bad('invalid-context-reversed-time','RequestContext',e['RequestContext'],['expires_at'],T,structural=False)
    bad('invalid-catalog-schema-digest','CapabilityCatalog',catalog,['devices',0,'actions',0,'parameters_schema','digest'],DIGEST,structural=False)
    bad('invalid-ws-payload','WsFrame',e['WsFrame'],['payload'],control_record)
    bad('invalid-body-role','AcquireRequest',control_input,['role'],'admin')
    bad('invalid-premature-arm','RunRecord',armed,['grant_bindings',0,'application_state'],'pending')
    bad('invalid-global-applied-before-targets','MutationReceipt',mutation,['state'],'applied')
    bad('invalid-published-no-version','DefinitionRecord',definition_record,['published'],True)
    bad('invalid-preflight-false-success','Preflight',e['Preflight'],['checks',0,'passed'],False)
    bad('invalid-grant-self-assign-principal','GrantUpdate',e['GrantUpdate'],['grant','principal_id'],'admin')
    bad('invalid-grant-self-activate','GrantUpdate',e['GrantUpdate'],['grant','state'],'active')
    # 正负例均是静态快照；不能用这些布尔值冒充设备运行证据。
    return cases

def traces():
    good_barrier=[{'event':'pending_saved','version':'9'},{'event':'send_old','command':'c1'}, {'event':'fence_ack','version':'9','worker':'w1','barrier':'b1','in_flight':['c1']},
        {'event':'effective_saved','version':'9','worker':'w1','barrier':'b1','in_flight':['c1']},{'event':'report_effective'}]
    return [
      {'case_id':'trace-barrier-before-send','kind':'barrier','valid':True,'steps':[{'event':'pending_saved','version':'9'},{'event':'fence_ack','version':'9','worker':'w1','barrier':'b1','in_flight':[]},{'event':'effective_saved','version':'9','worker':'w1','barrier':'b1','in_flight':[]},{'event':'report_effective'}]},
      {'case_id':'trace-send-before-barrier','kind':'barrier','valid':True,'steps':good_barrier},
      {'case_id':'trace-report-without-commit','kind':'barrier','valid':False,'steps':good_barrier[:3]+[{'event':'report_effective'}]},
      {'case_id':'trace-old-send-after-fence','kind':'barrier','valid':False,'steps':good_barrier+[{'event':'send_old','command':'c2'}]},
      {'case_id':'trace-lost-ack','kind':'barrier','valid':True,'steps':[{'event':'pending_saved','version':'9'},{'event':'timeout'},{'event':'remain_protected'}]},
      {'case_id':'trace-timeout-success','kind':'barrier','valid':False,'steps':[{'event':'pending_saved','version':'9'},{'event':'timeout'},{'event':'report_effective'}]},
      {'case_id':'trace-lost-inflight','kind':'barrier','valid':False,'steps':good_barrier[:3]+[dict(good_barrier[3],in_flight=[]),{'event':'report_effective'}]},
      {'case_id':'trace-no-pending-ack','kind':'barrier','valid':False,'steps':good_barrier[2:]},
      {'case_id':'trace-old-worker-ack','kind':'barrier','valid':False,'steps':good_barrier[:2]+[dict(good_barrier[2],worker='old-worker')]+good_barrier[3:]},
      {'case_id':'trace-reconcile-same-barrier','kind':'barrier','valid':True,'steps':good_barrier[:1]+[{'event':'timeout'},{'event':'remain_protected'}]+good_barrier[1:]},
      {'case_id':'trace-command-success','kind':'command','valid':True,'steps':['queued','dispatching','awaiting_evidence','finished:succeeded'],'guards':['intent_durable','permit_consumed','completion_durable']},
      {'case_id':'trace-command-finish-reopens','kind':'command','valid':False,'steps':['queued','finished:cancelled','queued'],'guards':['not_sent_proven']},
      {'case_id':'trace-command-unknown-late','kind':'command','valid':True,'steps':['queued','dispatching','finished:unknown','resolution'],'guards':['intent_durable','paused_latched']},
      {'case_id':'trace-command-unknown-auto-resume','kind':'command','valid':False,'steps':['queued','dispatching','finished:unknown','resolution','queued'],'guards':['intent_durable','paused_latched']},
      {'case_id':'trace-command-no-intent','kind':'command','valid':False,'steps':['queued','dispatching','awaiting_evidence'],'guards':['permit_consumed']},
      {'case_id':'trace-command-safe-retry','kind':'command','valid':True,'steps':['queued','dispatching','awaiting_evidence','queued','dispatching','awaiting_evidence','finished:succeeded'],'guards':['intent_durable','permit_consumed','retry_safe_failure','retry_budget','completion_durable']},
      {'case_id':'trace-command-unsafe-retry','kind':'command','valid':False,'steps':['queued','dispatching','awaiting_evidence','queued'],'guards':['intent_durable','permit_consumed','retry_budget']},
      {'case_id':'trace-command-cancel-not-proven','kind':'command','valid':False,'steps':['queued','dispatching','finished:cancelled'],'guards':['intent_durable']}
    ]

def canonical_vectors():
    return [
      {'case_id':'jcs-order','input':{'b':2,'a':1},'canonical':'{"a":1,"b":2}'},
      {'case_id':'jcs-negative-zero','input':{'zero':-0.0,'fraction':1.5},'canonical':'{"fraction":1.5,"zero":0}'},
      {'case_id':'jcs-unicode-preserved','input':{'text':'é','decomposed':'e\u0301'},'canonical':'{"decomposed":"é","text":"é"}'},
      {'case_id':'jcs-arrays','input':{'b':[2,1],'a':None},'canonical':'{"a":null,"b":[2,1]}'},
      {'case_id':'jcs-exponents','input':{'tiny':1e-7,'big':1e21},'canonical':'{"big":1e+21,"tiny":1e-7}'}
    ]

def identity_vectors():
    canonical='{"expected_control":{"epoch":"control-test","version":"8"},"force":false,"reason":"隔离验证"}'
    base={'context_id':'ctx-test','idempotency_key':'key-test','expected_control':{'epoch':'control-test','version':'8'},'reason':'隔离验证'}
    return [
      {'case_id':'identity-force-default','operation':'acquireControl','body':base,'canonical':canonical},
      {'case_id':'identity-force-explicit','operation':'acquireControl','body':dict(base,force=False),'canonical':canonical},
      {'case_id':'identity-change-reason','operation':'acquireControl','body':dict(base,reason='different'),'canonical':'{"expected_control":{"epoch":"control-test","version":"8"},"force":false,"reason":"different"}'},
      {'case_id':'identity-correlation-excluded','operation':'submitCommand','body':{'context_id':'ctx-test','idempotency_key':'key-test','correlation_id':'trace-test','parameters':{'value':1}},'canonical':'{"parameters":{"value":1}}'}
    ]

def capability_cases():
    schema={'type':'object','properties':{'scene_ref':{'type':'string','minLength':1}},'required':['scene_ref'],'additionalProperties':False}
    return [
      {'case_id':'capability-valid','schema':schema,'parameters':{'scene_ref':'scene-b'},'valid':True},
      {'case_id':'capability-extra-write','schema':schema,'parameters':{'scene_ref':'scene-b','force':True},'valid':False},
      {'case_id':'capability-wrong-type','schema':schema,'parameters':{'scene_ref':8},'valid':False},
      {'case_id':'capability-missing','schema':schema,'parameters':{},'valid':False}
    ]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    files={'examples.json':examples(),'boundary-traces.json':traces(),'canonical-vectors.json':canonical_vectors(),'identity-vectors.json':identity_vectors(),'capability-cases.json':capability_cases(),
        'invalid-wire.json':[{'case_id':'duplicate-key','raw':'{"x":1,"x":2}'},{'case_id':'non-finite','raw':'{"x":NaN}'},{'case_id':'lone-surrogate','raw':'{"x":"\\ud800"}'},{'case_id':'unsafe-integer','raw':'{"x":9007199254740992}'}]}
    for name,value in files.items():
        content=json.dumps(value,ensure_ascii=False,indent=2)+'\n';path=ROOT/name
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8')!=content:raise SystemExit('例子生成物过时：'+name)
        else:path.write_text(content,encoding='utf-8',newline='\n')
    print('正反例生成物核对通过' if args.check else '正反例已生成')

if __name__=='__main__':main()
