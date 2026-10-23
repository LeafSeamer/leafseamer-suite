"""C04执行记录候选生成器；只生成设计Schema，不提供业务执行器。"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = 'automation-execution/0.1.0-draft.1'
SID = 'https://leafseamer.invalid/design/c04-execution/execution.schema.json'
LIFE = 'https://leafseamer.invalid/design/c04-lifecycle/lifecycle.schema.json'


def ref(name): return {'$ref': '#/$defs/' + name}
def obj(**fields): return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)
def enum(*values): return {'enum': list(values)}
def nullable(v): return {'anyOf': [v, {'type': 'null'}]}
def arr(v, maximum=4096): return dict(type='array', items=v, maxItems=maximum, uniqueItems=True)
def ms(maximum=86400000, minimum=0): return dict(type='integer', minimum=minimum, maximum=maximum)


def build():
    d = {n: {'$ref': LIFE + '#/$defs/' + n} for n in ('Id', 'Revision', 'Digest', 'Scope', 'ClockRef')}
    ident, rev, digest = ref('Id'), ref('Revision'), ref('Digest')
    kinds = ['execution_binding', 'execution_plan', 'execution_start', 'pause_latch', 'action_binding', 'parameters',
             'parameter_schema', 'completion_policy', 'completion_evidence', 'release_evidence', 'command', 'command_submission',
             'step_plan', 'step_result', 'budget_charge', 'schedule_window', 'observation', 'age_evidence', 'edge_policy', 'runtime_policy',
             'delay', 'clock_rate_profile', 'window_challenge', 'budget_limit', 'execution_anchor', 'step_ready', 'trigger_decision', 'request_adjudication']
    for kind in kinds:
        d[kind.title().replace('_', '') + 'Ref'] = obj(kind={'const': kind}, scope=ref('Scope'), object_id=ident, revision=rev, digest=digest)
    d['PauseLatch'] = obj(scope=ref('Scope'), latch_id=ident, run_id=ident, reason_code=ident, created_run_revision=rev,
        resolution_refs=arr(ref('ReleaseEvidenceRef')), latch_digest=digest)
    d['ExecutionStart'] = obj(scope=ref('Scope'), start_id=ident, operation_id=ident, run_id=ident,
        execution_binding_ref=ref('ExecutionBindingRef'), plan_ref=ref('ExecutionPlanRef'),
        expected_operation_revision=rev, run_revision_before=rev, run_revision_after=rev, slot_revision=rev,
        prepared_targets_digest=digest, cleared_latch_refs=arr(ref('PauseLatchRef'), 256),
        clock=ref('ClockRef'), start_tick_ns=rev, mode=enum('execute', 'reconcile_commit'), start_digest=digest)
    d['ExecutionAnchor'] = obj(scope=ref('Scope'), anchor_id=ident, revision={'const': '1'}, execution_id=ident,
        origin_ref={'oneOf': [ref('TriggerDecisionRef'), ref('ExecutionStartRef')]}, clock=ref('ClockRef'), anchor_tick_ns=rev, anchor_digest=digest)
    d['StepReady'] = obj(scope=ref('Scope'), ready_id=ident, revision={'const': '1'}, execution_id=ident, step_id=ident, step_plan_ref=ref('StepPlanRef'),
        clock=ref('ClockRef'), ready_tick_ns=rev, dependencies_digest=digest, ready_digest=digest)
    d['DelayPolicy'] = obj(anchor_kind=enum('execution_admitted', 'step_ready'), window_scope={'const': 'direct_successor'}, delay_ms=ms(), max_lateness_ms=ms(60000, 1))
    d['ActionPlan'] = obj(kind={'const': 'action'}, action_binding_ref=ref('ActionBindingRef'), controller_id=ident, device_id=ident,
        parameters_ref=ref('ParametersRef'), parameter_schema_ref=ref('ParameterSchemaRef'), completion_policy_ref=ref('CompletionPolicyRef'),
        supersedes_command_ref=nullable(ref('CommandRef')), budget_charge_refs=arr(ref('BudgetChargeRef'), 3), delay_window_refs=arr(ref('DelayRef')),
        schedule_window_ref=nullable(ref('ScheduleWindowRef')))
    d['RetainPlan'] = obj(kind={'const': 'retain_success'}, command_ref=ref('CommandRef'), evidence_refs=arr(ref('CompletionEvidenceRef')))
    d['DelayPlan'] = obj(kind={'const': 'delay'}, policy=ref('DelayPolicy'))
    d['CommitPlan'] = obj(kind={'const': 'reconcile_commit'}, evidence_refs=arr(ref('CompletionEvidenceRef')))
    d['StepPlan'] = obj(scope=ref('Scope'), execution_id=ident, step_id=ident, phase=enum('exit', 'transition', 'enter', 'sequence', 'commit'),
        group_id=ident, group_mode=enum('sequence', 'parallel'), ordinal=ms(4095), required={'type': 'boolean'},
        execution_binding_ref=ref('ExecutionBindingRef'), runtime_policy_ref=ref('RuntimePolicyRef'),
        payload={'oneOf': [ref(n) for n in ('ActionPlan', 'RetainPlan', 'DelayPlan', 'CommitPlan')]}, plan_digest=digest)
    d['StepRecord'] = obj(scope=ref('Scope'), execution_id=ident, step_id=ident, plan_ref=ref('StepPlanRef'), revision=rev,
        state=enum('waiting', 'ready', 'submission_pending', 'accepted', 'awaiting_evidence', 'finished', 'retained', 'cancelled', 'indeterminate'),
        outcome=enum('pending', 'succeeded', 'failed', 'unknown', 'blocked', 'expired', 'cancelled'),
        submission_ref=nullable(ref('CommandSubmissionRef')), command_ref=nullable(ref('CommandRef')),
        evidence_refs=arr(ref('CompletionEvidenceRef')), result_ref=nullable(ref('StepResultRef')))
    d['RequestIdentity'] = obj(target_scope=ref('Scope'), issuer_id=ident, principal_id=ident, request_epoch=ident,
        operation_id={'const': 'createCommand'}, idempotency_key=ident, request_digest=digest)
    d['CommandSubmission'] = obj(scope=ref('Scope'), submission_id=ident, execution_id=ident, step_id=ident,
        step_plan_ref=ref('StepPlanRef'), identity=ref('RequestIdentity'), parameters_ref=ref('ParametersRef'),
        state=enum('planned', 'attempt_recorded', 'accepted', 'rejected', 'indeterminate'),
        attempt_clock=nullable(ref('ClockRef')), attempt_tick_ns=nullable(rev), command_ref=nullable(ref('CommandRef')),
        adjudication_ref=nullable(ref('RequestAdjudicationRef')),
        submission_digest=digest)
    d['DelayRecord'] = obj(scope=ref('Scope'), execution_id=ident, step_id=ident, execution_anchor_ref=ref('ExecutionAnchorRef'),
        anchor_ref={'oneOf': [ref('ExecutionAnchorRef'), ref('StepReadyRef')]},
        policy=ref('DelayPolicy'), clock=ref('ClockRef'), anchor_tick_ns=rev, due_tick_ns=rev, deadline_tick_ns=rev,
        state=enum('waiting', 'elapsed', 'expired', 'cancelled'), revision=rev, delay_digest=digest)
    d['WindowTranslation'] = obj(delay_ref=ref('DelayRef'), execution_id=ident, step_id=ident,
        source_clock=ref('ClockRef'), target_clock=ref('ClockRef'), challenge_ref=ref('WindowChallengeRef'),
        source_rate_profile_ref=ref('ClockRateProfileRef'), target_rate_profile_ref=ref('ClockRateProfileRef'),
        source_rate_error_ppm=ms(999999), target_rate_error_ppm=ms(999999),
        target_challenge_sent_tick_ns=rev, target_response_received_tick_ns=rev, source_sample_tick_ns=rev,
        source_due_tick_ns=rev, source_deadline_tick_ns=rev, target_not_before_tick_ns=rev, target_deadline_tick_ns=rev,
        translation_digest=digest)
    signed = dict(type='string', pattern=r'^-?(0|[1-9][0-9]{0,19})$(?![\s\S])')
    d['EdgePolicy'] = obj(direction=enum('rising', 'falling'), enter_raw=signed, reset_raw=signed, unit=ident,
        stable_for_ms=ms(), max_sample_gap_ms=ms(60000, 1), rearm_policy={'const': 'reset_required'})
    d['EdgeBinding'] = obj(scope=ref('Scope'), definition_id=ident, run_id=ident, arm_generation=rev,
        source_registration_id=ident, source_revision=rev, source_epoch=ident, clock=ref('ClockRef'), policy_ref=ref('EdgePolicyRef'))
    d['EdgeSample'] = obj(binding=ref('EdgeBinding'), observation_ref=ref('ObservationRef'), age_evidence_ref=ref('AgeEvidenceRef'),
        sequence=rev, sample_tick_ns=rev, raw=signed, unit=ident, delivery=enum('live', 'baseline', 'reconcile'), sample_digest=digest)
    d['EdgeState'] = obj(binding=ref('EdgeBinding'), revision=rev, phase=enum('needs_reset', 'armed', 'tracking'),
        last_sequence=nullable(rev), last_sample_digest=nullable(digest), last_sample_tick_ns=nullable(rev),
        candidate_since_tick_ns=nullable(rev), last_decision_id=nullable(ident))
    d['EdgeDecision'] = obj(binding=ref('EdgeBinding'), decision_id=ident, sequence=rev, sample_digest=digest,
        result=enum('baseline', 'reset_observed', 'tracking', 'idle', 'edge', 'suppressed_busy', 'suppressed_inactive', 'invalid'),
        state_revision_before=rev, state_revision_after=rev, decision_digest=digest)
    d['BudgetKey'] = obj(owner_scope=ref('Scope'), organization_id=ident, namespace=enum('definition', 'verified_chain', 'unattributed_chain', 'device'),
        stable_subject_id=ident, unit=enum('execution', 'command'))
    d['BudgetPolicy'] = obj(key=ref('BudgetKey'), policy_ref=ref('BudgetLimitRef'), window_ms=ms(86400000, 1),
        limit=dict(type='integer', minimum=1, maximum=4096), max_live_charges=dict(type='integer', minimum=1, maximum=4096))
    d['BudgetCharge'] = obj(key=ref('BudgetKey'), charge_id=ident, policy_ref=ref('BudgetLimitRef'),
        execution_id=ident, step_id=nullable(ident), amount=dict(type='integer', minimum=1, maximum=4096),
        clock=ref('ClockRef'), charged_tick_ns=rev, charge_digest=digest)
    d['ExecutionRuntimePolicy'] = obj(version={'const': VERSION},
        delay_policies=arr(obj(step_id=ident, policy=ref('DelayPolicy'))),
        edge_policies=arr(obj(binding_id=ident, policy=ref('EdgePolicy')), 256),
        budget_policies=arr(ref('BudgetPolicy'), 256), policy_digest=digest)
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SID, 'title': VERSION + ' 待审阅', 'not': {}, '$defs': d}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--check', action='store_true'); a = p.parse_args()
    raw = (json.dumps(build(), ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if a.check: assert (ROOT / 'execution.schema.json').read_bytes() == raw, '生成漂移'
    else: (ROOT / 'execution.schema.json').write_bytes(raw)
