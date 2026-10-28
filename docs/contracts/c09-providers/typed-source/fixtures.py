"""在固定旧合成样例上显式编写新结果示例，不作为真实来源。"""
import copy,json
from pathlib import Path
D='sha256:'+'1'*64
SCOPE=dict(authority_service_id='seamer.fixture',database_instance_id='db.fixture')
ARTIFACT=dict(kind='artifact',scope=SCOPE,object_id='artifact.fixture',revision='2',digest=D)
CONTENT=dict(program=dict(kind='rule',trigger_binding_id='trigger.fixture',condition=dict(kind='literal',value=True),
 groups=[dict(mode='sequence',steps=[dict(step_id='delay.fixture',depends_on=[],required=True,failure_policy='stop',kind='delay',delay_ms=1,max_lateness_ms=100)])]),
 selections=[],policy_ref=dict(kind='policy',scope=SCOPE,object_id='policy.fixture',revision='1',digest=D))
def examples():
 old=json.loads((Path(__file__).resolve().parent/'source/legacy-cases.json').read_bytes())['fixtures'];v=copy.deepcopy(old)
 v['MetaView']['protocol_version']='leafseamer.api.v1.events2'
 clock=dict(model_id='reference-bound/1',model_revision='1',status='conditional',reference_utc=dict(lower_ns='1000000000000000000',upper_ns='1000000000000000020'),estimated_utc_ns='1000000000000000010',error_radius_ns='10',reasons=[],grants_execution=False)
 v['ClockView']=copy.deepcopy(clock);v['ClockAssessmentView']=copy.deepcopy(clock)
 v['CancelView'].update(revision='2',future_writes='pending')
 v['CommandView']['state_ref']=dict(id='state.fixture',revision='4',digest=D)
 v['TransferView'].pop('expires_at');v['TransferView']['remaining_ms']=1000
 v['GrantMutationView']=dict(v.pop('MutationView'),kind='grant_revocation')
 targets=dict(items=[dict(service_alias='controller.local',state='closing')],has_hidden=False)
 v['LifecycleMutationView']=dict(operation_id='operation.fixture',run_id='run.1',kind='pause',state='reconciling',committed_run_revision='5',committed_slot_revision='3',target_arm_generation='2',locally_closed=True,protection_complete=False,target_status_summary=copy.deepcopy(targets))
 v.pop('DefinitionView')
 v['DraftDefinitionView']=dict(kind='draft',definition_id='definition.1',revision='2',content_digest=D,selection_digest=D,metadata_revision='1',content=CONTENT,metadata=dict(name='fixture',description='',layout={}),proof_summaries=[])
 v['PublishedDefinitionView']=dict(kind='published',definition_id='definition.1',definition_version='2',source_draft_revision='2',artifact_ref=ARTIFACT,program_digest=D,bindings_digest=D,content=CONTENT,metadata=dict(name='fixture',description='',layout={}),proof_summaries=[])
 v['RunView'].update(definition_version='2',artifact_ref=ARTIFACT,slot_revision='3',business_state=dict(state_id='state.fixture',revision='1'),execution_summary=dict(execution_id='execution.1',phase='reconciling',outcome='unknown'),grant_summaries=copy.deepcopy(targets))
 v['RunView']['grant_summaries']['items'][0].update(baseline_grant_id='grant.old',target_grant_id='grant.current')
 v['PreflightView']=dict(run_id='run.1',run_revision='4',slot_revision='3',passed=True,checks=[dict(service_alias='controller.local',status='passed',reason_code='ready')],remaining_ms=1000,assessment_handle='assessment.fixture')
 v['RecoveryPlanView']=dict(run_id='run.1',prior_execution_id='execution.previous',run_revision='4',slot_revision='3',recovery_handle='recovery.fixture',remaining_ms=1000,
  items=[dict(step_id='step.1',disposition='retain_success',previous_command_id='command.1',has_hidden_previous=False,evidence_summaries=[],parameters_summary=None)],unresolved=dict(visible_command_ids=['command.2'],has_hidden=False))
 r=v['RecoveryOperationView'];r.pop('recovery_generation');r.update(committed_slot_revision='3',target_arm_generation='2',state='reconciling',new_execution_id=None,visible_new_command_ids=[],has_hidden_commands=False,target_status_summary=copy.deepcopy(targets))
 v['IndependenceView']['definition_version']='2'
 return copy.deepcopy(v)
