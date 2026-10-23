"""人工预期的C04执行候选离线检查；不运行服务、网络或SQLite。"""
import argparse
import copy
import hashlib
import json
import platform
import subprocess
import sys
from importlib.metadata import version
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from build_contracts import ROOT, SID, VERSION
from reference_model import MAX_U20, charge_budget, delay_status, delay_binding_error, digest, dispatch_once, edge_step, resolve_submission, seal, semantic_error, start_recovery, tick, translated_bounds, translated_gate

SUITE = ROOT.parents[2]
INPUTS = [ROOT / n for n in ('README.md', 'build_contracts.py', 'reference_model.py', 'check_contracts.py', 'execution.schema.json')]
INPUTS += [ROOT.parent / 'c04-lifecycle/lifecycle.schema.json', ROOT.parent / 'c04-program/program.schema.json', SUITE / 'docs/rebirth-c04-automation-design.md']
SCOPE = dict(authority_service_id='seamer', database_instance_id='db')
CLOCK = dict(clock_domain_id='clock_' + '1' * 64, descriptor_digest='sha256:' + '2' * 64)
HASH = 'sha256:' + 'a' * 64


def ref(kind, name=None, scope=None):
    return dict(kind=kind, scope=copy.deepcopy(scope or SCOPE), object_id=name or kind, revision='1', digest=HASH)


def context():
    return dict(authorized=True, storage_healthy=True, clock=copy.deepcopy(CLOCK), now=10000000, abort_before_commit=False,
        slot_owned=True, baseline_current=True, targets_applied=True, old_resources_clear=True, plan_complete=True,
        gates_valid=True, budget_valid=True, schedule_valid=True, plan_has_device_write=True,
        step_ready=True, parameters_valid=True, execution_current=True, response_trusted=True, rejection_durable=True,
        restarted=False, sample_trusted=True, busy=False, armed=True, challenge_trusted=True, rate_profiles_approved=True, binding_current=True)


def recovery():
    latch = ref('pause_latch', 'old-failure')
    run = dict(scope=copy.deepcopy(SCOPE), run_id='run', revision='7', lifecycle='paused', active_execution_id='new-execution',
        active_operation_id='recovery', pause_latch_refs=[latch], dispatch_eligible=False)
    op = dict(operation_id='recovery', execution_id='new-execution', revision='4', state='ready', mode='execute',
        execution_binding_ref=ref('execution_binding'), plan_ref=ref('execution_plan'), prepared_targets_digest=HASH, resolved_latch_refs=[latch])
    world = dict(run=run, operation=op, slot_revision='5', starts={})
    start = seal(dict(scope=copy.deepcopy(SCOPE), start_id='start', operation_id='recovery', run_id='run',
        execution_binding_ref=ref('execution_binding'), plan_ref=ref('execution_plan'), expected_operation_revision='4',
        run_revision_before='7', run_revision_after='8', slot_revision='5', prepared_targets_digest=HASH,
        cleared_latch_refs=[latch], clock=copy.deepcopy(CLOCK), start_tick_ns='10000000', mode='execute'), 'start_digest')
    return world, start


def submission():
    remote = dict(authority_service_id='controller', database_instance_id='remote-db')
    return seal(dict(scope=copy.deepcopy(SCOPE), submission_id='submission', execution_id='new-execution', step_id='step',
        step_plan_ref=ref('step_plan'), identity=dict(target_scope=remote, issuer_id='issuer', principal_id='automation',
            request_epoch='epoch', operation_id='createCommand', idempotency_key='key', request_digest=HASH),
        parameters_ref=ref('parameters'), state='planned', attempt_clock=None, attempt_tick_ns=None, command_ref=None, adjudication_ref=None), 'submission_digest')


def anchors(ready_tick=0):
    execution = seal(dict(scope=copy.deepcopy(SCOPE), anchor_id='execution_anchor', revision='1', execution_id='execution', origin_ref=ref('trigger_decision'), clock=copy.deepcopy(CLOCK), anchor_tick_ns='0'), 'anchor_digest')
    ready = seal(dict(scope=copy.deepcopy(SCOPE), ready_id='step_ready', revision='1', execution_id='execution', step_id='wait', step_plan_ref=ref('step_plan'),
        clock=copy.deepcopy(CLOCK), ready_tick_ns=str(ready_tick), dependencies_digest=HASH), 'ready_digest')
    return execution, ready


def delay(anchor=0, kind='step_ready', delay_ms=5, lateness=5):
    execution, ready = anchors(anchor)
    execution_ref = dict(ref('execution_anchor'), digest=execution['anchor_digest'])
    anchor_ref = execution_ref if kind == 'execution_admitted' else dict(ref('step_ready'), digest=ready['ready_digest'])
    return seal(dict(scope=copy.deepcopy(SCOPE), execution_id='execution', step_id='wait', execution_anchor_ref=execution_ref, anchor_ref=anchor_ref,
        policy=dict(anchor_kind=kind, window_scope='direct_successor', delay_ms=delay_ms, max_lateness_ms=lateness), clock=copy.deepcopy(CLOCK), anchor_tick_ns=tick(anchor),
        due_tick_ns=tick(anchor + delay_ms * 1000000), deadline_tick_ns=tick(anchor + (delay_ms + lateness) * 1000000), state='waiting', revision='1'), 'delay_digest')


def edge():
    policy = dict(direction='rising', enter_raw='10', reset_raw='5', unit='raw', stable_for_ms=2, max_sample_gap_ms=5, rearm_policy='reset_required')
    binding = dict(scope=copy.deepcopy(SCOPE), definition_id='definition', run_id='run', arm_generation='3',
        source_registration_id='source', source_revision='1', source_epoch='epoch', clock=copy.deepcopy(CLOCK), policy_ref=ref('edge_policy'))
    binding['policy_ref']['digest'] = digest(policy)
    state = dict(binding=binding, revision='0', phase='needs_reset', last_sequence=None, last_sample_digest=None,
        last_sample_tick_ns=None, candidate_since_tick_ns=None, last_decision_id=None)
    return policy, state


def translation():
    source_clock = dict(clock_domain_id='clock_' + '3' * 64, descriptor_digest='sha256:' + '4' * 64)
    return seal(dict(delay_ref=ref('delay'), execution_id='execution', step_id='step', source_clock=source_clock,
        target_clock=copy.deepcopy(CLOCK), challenge_ref=ref('window_challenge'), source_rate_profile_ref=ref('clock_rate_profile', 'source-rate'),
        target_rate_profile_ref=ref('clock_rate_profile', 'target-rate'), source_rate_error_ppm=0, target_rate_error_ppm=0,
        target_challenge_sent_tick_ns='100', target_response_received_tick_ns='120', source_sample_tick_ns='1000',
        source_due_tick_ns='1010', source_deadline_tick_ns='1100', target_not_before_tick_ns='130', target_deadline_tick_ns='200'), 'translation_digest')


def sample(state, seq, t, value, delivery='live'):
    return seal(dict(binding=copy.deepcopy(state['binding']), observation_ref=ref('observation', 'sample-' + str(seq)),
        age_evidence_ref=ref('age_evidence', 'age-' + str(seq)), sequence=str(seq), sample_tick_ns=str(t), raw=str(value), unit='raw',
        delivery=delivery), 'sample_digest')


def budget():
    key = dict(owner_scope=copy.deepcopy(SCOPE), organization_id='org', namespace='definition', stable_subject_id='definition', unit='execution')
    policy = dict(key=key, policy_ref=ref('budget_limit'), window_ms=10, limit=2, max_live_charges=2)
    policy['policy_ref']['digest'] = digest({k: policy[k] for k in ('window_ms', 'limit', 'max_live_charges')})
    ledger = dict(key=key, policy_ref=copy.deepcopy(policy['policy_ref']), clock=copy.deepcopy(CLOCK), last_tick_ns='0', charges={}, blocked=False)
    charge = seal(dict(key=key, charge_id='charge-1', policy_ref=copy.deepcopy(policy['policy_ref']), execution_id='execution', step_id=None,
        amount=1, clock=copy.deepcopy(CLOCK), charged_tick_ns='10000000'), 'charge_digest')
    return ledger, policy, charge


def samples():
    _, start = recovery(); policy, edge_state = edge(); _, budget_policy, charge = budget()
    action = dict(kind='action', action_binding_ref=ref('action_binding'), controller_id='controller', device_id='device',
        parameters_ref=ref('parameters'), parameter_schema_ref=ref('parameter_schema'), completion_policy_ref=ref('completion_policy'),
        supersedes_command_ref=None, budget_charge_refs=[ref('budget_charge')], delay_window_refs=[], schedule_window_ref=None)
    plan = seal(dict(scope=copy.deepcopy(SCOPE), execution_id='execution', step_id='step', phase='sequence', group_id='group',
        group_mode='sequence', ordinal=0, required=True, execution_binding_ref=ref('execution_binding'), runtime_policy_ref=ref('runtime_policy'), payload=action), 'plan_digest')
    retained = dict(kind='retain_success', command_ref=ref('command'), evidence_refs=[ref('completion_evidence')])
    record = dict(scope=copy.deepcopy(SCOPE), execution_id='execution', step_id='step', plan_ref=ref('step_plan'), revision='1',
        state='waiting', outcome='pending', submission_ref=None, command_ref=None, evidence_refs=[], result_ref=None)
    decision = seal(dict(binding=copy.deepcopy(edge_state['binding']), decision_id='decision', sequence='1', sample_digest=HASH,
        result='baseline', state_revision_before='0', state_revision_after='1'), 'decision_digest')
    return dict(PauseLatch=seal(dict(scope=copy.deepcopy(SCOPE), latch_id='latch', run_id='run', reason_code='failure', created_run_revision='5',
        resolution_refs=[], latch_digest=HASH), 'latch_digest'), ExecutionStart=start, DelayPolicy=delay()['policy'], ActionPlan=action,
        RetainPlan=retained, DelayPlan=dict(kind='delay', policy=delay()['policy']), CommitPlan=dict(kind='reconcile_commit', evidence_refs=[ref('completion_evidence')]),
        StepPlan=plan, StepRecord=record, RequestIdentity=submission()['identity'], CommandSubmission=submission(), DelayRecord=delay(),
        EdgePolicy=policy, EdgeBinding=edge_state['binding'], EdgeSample=sample(edge_state, 1, 0, 5), EdgeState=edge_state,
        EdgeDecision=decision, BudgetKey=budget_policy['key'], BudgetPolicy=budget_policy, BudgetCharge=charge, WindowTranslation=translation(),
        ExecutionAnchor=anchors()[0], StepReady=anchors()[1],
        ExecutionRuntimePolicy=seal(dict(version=VERSION, delay_policies=[dict(step_id='wait', policy=delay()['policy'])],
            edge_policies=[dict(binding_id='threshold', policy=policy)], budget_policies=[budget_policy]), 'policy_digest'))


def run():
    subprocess.run([sys.executable, str(ROOT / 'build_contracts.py'), '--check'], check=True)
    schemas = [json.loads(p.read_bytes()) for p in (ROOT / 'execution.schema.json', ROOT.parent / 'c04-lifecycle/lifecycle.schema.json', ROOT.parent / 'c04-program/program.schema.json')]
    registry = Registry().with_resources([(s['$id'], Resource.from_contents(s)) for s in schemas])
    Draft202012Validator.check_schema(schemas[0]); checks = []
    def expect(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(id=name, actual=actual, expected=expected))
    def valid(model, value): return Draft202012Validator({'$ref': SID + '#/$defs/' + model}, registry=registry).is_valid(value)
    data = samples()
    for name, value in data.items():
        expect('schema.' + name, valid(name, value), True)
        expect('semantic.' + name, semantic_error(name, value), None)
        bad = dict(value, extra=True); expect('closed.' + name, valid(name, bad), False)
    for name, field, value, reason, seal_field in [
        ('ExecutionStart', 'run_revision_after', '9', 'start_revision', 'start_digest'),
        ('ExecutionStart', 'cleared_latch_refs', data['ExecutionStart']['cleared_latch_refs'] * 2, 'duplicate_latch', 'start_digest'),
        ('DelayRecord', 'due_tick_ns', '0', 'delay_arithmetic', 'delay_digest'),
        ('CommandSubmission', 'state', 'accepted', 'attempt_marker', 'submission_digest'),
        ('EdgePolicy', 'reset_raw', '10', 'hysteresis', None),
        ('EdgeState', 'phase', 'tracking', 'tracking_anchor', None),
        ('StepRecord', 'outcome', 'succeeded', 'step_outcome', None),
        ('BudgetCharge', 'step_id', 'step', 'budget_unit', 'charge_digest')]:
        bad = copy.deepcopy(data[name]); bad[field] = value
        if seal_field: seal(bad, seal_field)
        expect('semantic.reject.' + reason, semantic_error(name, bad), reason)
    for kind in ('retain_success', 'reconcile_commit', 'delay'):
        plan = copy.deepcopy(data['StepPlan'])
        plan['payload'] = data[{'retain_success': 'RetainPlan', 'reconcile_commit': 'CommitPlan', 'delay': 'DelayPlan'}[kind]]
        if kind == 'reconcile_commit': plan['phase'] = 'commit'
        seal(plan, 'plan_digest'); expect('step_plan.' + kind, valid('StepPlan', plan) and semantic_error('StepPlan', plan) is None, True)
    retained = copy.deepcopy(data['StepPlan']); retained.update(payload=data['RetainPlan'], required=False); seal(retained, 'plan_digest')
    expect('step_plan.optional_success_retained', semantic_error('StepPlan', retained), None)
    retained['payload'] = dict(data['RetainPlan'], evidence_refs=[]); seal(retained, 'plan_digest')
    expect('step_plan.retained_without_evidence', semantic_error('StepPlan', retained), 'evidence_required')
    ctx = context(); w, start = recovery(); started, result = start_recovery(w, start, ctx)
    expect('r4.start', result, 'started'); expect('r4.run', started['run']['lifecycle'], 'running')
    expect('r4.clear_only_approved', started['run']['pause_latch_refs'], [])
    expect('r4.clear_active_operation', started['run']['active_operation_id'], None)
    expect('r4.repeat', start_recovery(started, start, ctx), (started, 'existing'))
    altered = copy.deepcopy(start); altered['start_id'] = 'second'; seal(altered, 'start_digest')
    expect('r4.second_id', start_recovery(started, altered, ctx)[1], 'binding')
    altered = copy.deepcopy(start); altered['plan_ref']['digest'] = 'sha256:' + 'b' * 64; seal(altered, 'start_digest')
    expect('r4.same_id_changed', start_recovery(started, altered, ctx)[1], 'identity_conflict')
    for field, value in [('expected_operation_revision', '3'), ('slot_revision', '4'), ('prepared_targets_digest', 'sha256:' + 'b' * 64)]:
        bad = copy.deepcopy(start); bad[field] = value; seal(bad, 'start_digest')
        expect('r4.' + field, start_recovery(w, bad, ctx), (w, 'binding'))
    changed = copy.deepcopy(w); changed['run']['pause_latch_refs'].append(ref('pause_latch', 'new-takeover'))
    expect('r4.new_latch', start_recovery(changed, start, ctx), (changed, 'new_latch'))
    for gate in ('slot_owned', 'baseline_current', 'targets_applied', 'old_resources_clear', 'plan_complete', 'gates_valid', 'budget_valid', 'schedule_valid'):
        paused, result = start_recovery(w, start, dict(ctx, **{gate: False}))
        expect('r4.gate.' + gate, result, 'protected')
        expect('r4.latched.' + gate, paused['operation']['state'], 'paused')
        expect('r4.no_auto_restart.' + gate, start_recovery(paused, start, ctx)[1], 'binding')
    closed, _ = start_recovery(w, start, dict(ctx, storage_healthy=False))
    expect('r4.storage_recovery', start_recovery(closed, start, ctx)[1], 'protected')
    expect('r4.rollback', start_recovery(w, start, dict(ctx, abort_before_commit=True)), (w, 'rolled_back'))
    reconcile = copy.deepcopy(w); reconcile['operation']['mode'] = 'reconcile_commit'
    rs = copy.deepcopy(start); rs['mode'] = 'reconcile_commit'; seal(rs, 'start_digest')
    expect('r4.no_write_reconcile', start_recovery(reconcile, rs, ctx)[1], 'write_forbidden')
    done, result = start_recovery(reconcile, rs, dict(ctx, plan_has_device_write=False))
    expect('r4.reconcile', result, 'started'); expect('r4.reconcile_no_dispatch', done['run']['dispatch_eligible'], False)
    expect('r4.reconcile_phase', done['operation']['state'], 'reconciling')
    initial = submission(); sent, result = dispatch_once(initial, ctx)
    expect('send.first', result, 'call_once'); expect('send.marker_schema', valid('CommandSubmission', sent), True)
    expect('send.after_marker_crash', dispatch_once(sent, ctx), (sent, 'query_only'))
    expect('send.rollback', dispatch_once(initial, dict(ctx, abort_before_commit=True)), (initial, 'rolled_back'))
    for gate in ('authorized', 'storage_healthy', 'step_ready', 'parameters_valid', 'gates_valid', 'budget_valid', 'schedule_valid', 'execution_current'):
        expect('send.' + gate, dispatch_once(initial, dict(ctx, **{gate: False})), (initial, 'protected'))
    reply = dict(identity=copy.deepcopy(sent['identity']), result='accepted', command_ref=ref('command', scope=sent['identity']['target_scope']),
        adjudication_ref=ref('request_adjudication', scope=sent['identity']['target_scope']))
    accepted, result = resolve_submission(sent, reply, ctx)
    expect('send.accepted', result, 'accepted'); expect('send.accepted_shape', valid('CommandSubmission', accepted) and semantic_error('CommandSubmission', accepted) is None, True)
    expect('send.duplicate_response', resolve_submission(accepted, reply, ctx), (accepted, 'terminal'))
    bad_reply = copy.deepcopy(reply); bad_reply['identity']['request_digest'] = 'sha256:' + 'b' * 64
    expect('send.wrong_body', resolve_submission(sent, bad_reply, ctx), (sent, 'response_binding'))
    for response in ('not_found', 'transport_timeout', 'rejected_final'):
        unknown, result = resolve_submission(sent, dict(reply, result=response), dict(ctx, rejection_durable=False))
        expect('send.uncertain.' + response, result, 'indeterminate')
        expect('send.never_retry.' + response, dispatch_once(unknown, ctx)[1], 'query_only')
    expect('send.durable_reject', resolve_submission(sent, dict(reply, result='rejected_final'), ctx)[1], 'rejected')
    expect('send.no_durable_receipt', resolve_submission(sent, dict(reply, result='rejected_final', adjudication_ref=None), ctx), (sent, 'response_receipt'))
    wrong_scope = copy.deepcopy(reply); wrong_scope['command_ref']['scope'] = copy.deepcopy(SCOPE)
    expect('send.other_command_scope_no_mutation', resolve_submission(sent, wrong_scope, ctx), (sent, 'response_scope'))
    for now, expected in [(0, 'waiting'), (4999999, 'waiting'), (5000000, 'elapsed'), (9999999, 'elapsed'), (10000000, 'expired')]:
        expect('delay.tick.' + str(now), delay_status(delay(), dict(ctx, now=now)), expected)
    expect('delay.zero', delay_status(delay(delay_ms=0), dict(ctx, now=0)), 'elapsed')
    expect('delay.restart', delay_status(delay(), dict(ctx, now=5000000, restarted=True)), 'cancelled')
    expect('delay.protected', delay_status(delay(), dict(ctx, now=5000000, gates_valid=False)), 'cancelled')
    expect('delay.other_domain', delay_status(delay(), dict(ctx, clock=dict(CLOCK, descriptor_digest=HASH))), 'cancelled')
    cancelled = seal(dict(delay(), state='cancelled'), 'delay_digest')
    expect('delay.no_resume', delay_status(cancelled, dict(ctx, now=5000000)), 'terminal_cancelled')
    expect('delay.sequential_second_wait', delay_status(delay(anchor=5000000), dict(ctx, now=5000000)), 'waiting')
    expect('delay.execution_offset', delay_status(delay(kind='execution_admitted'), dict(ctx, now=5000000)), 'elapsed')
    expect('delay.bound_step_ready', delay_binding_error(delay(), *anchors()), None)
    expect('delay.bound_admission', delay_binding_error(delay(kind='execution_admitted'), *anchors()), None)
    ex, ready = anchors(); changed = seal(dict(ready, step_id='other'), 'ready_digest')
    expect('delay.rehashed_other_step', delay_binding_error(delay(), ex, changed), 'ready_binding')
    changed = seal(dict(ex, execution_id='other'), 'anchor_digest')
    expect('delay.rehashed_other_execution', delay_binding_error(delay(), changed, ready), 'execution_anchor')
    wrong = delay(); wrong['anchor_ref']['object_id'] = 'other'; seal(wrong, 'delay_digest')
    expect('delay.same_digest_wrong_id', delay_binding_error(wrong, ex, ready), 'ready_digest')
    try: delay(anchor=MAX_U20)
    except ValueError as e: expect('delay.overflow', str(e), 'u20_overflow')
    else: raise AssertionError('未拒绝溢出')
    for now, expected in [(129, 'waiting'), (130, 'eligible'), (199, 'eligible'), (200, 'expired')]:
        expect('window.tick.' + str(now), translated_gate(translation(), dict(ctx, now=now)), expected)
    for flag in ('challenge_trusted', 'rate_profiles_approved', 'binding_current'):
        expect('window.' + flag, translated_gate(translation(), dict(ctx, now=130, **{flag: False})), 'protected')
    rates = translation(); rates.update(source_rate_error_ppm=100000, target_rate_error_ppm=100000)
    expect('window.outward_rounding', translated_bounds(rates), ('133', '181'))
    seal(rates, 'translation_digest')
    expect('window.rehashed_wrong_interval', semantic_error('WindowTranslation', rates), 'window_arithmetic')
    empty = translation(); empty['target_response_received_tick_ns'] = '200'; seal(empty, 'translation_digest')
    expect('window.network_exhausted', semantic_error('WindowTranslation', empty), 'window_invalid')
    old_due = translation(); old_due['source_due_tick_ns'] = '900'
    expect('window.due_already_passed', translated_bounds(old_due), ('120', '200'))
    expect('window.foreign_target_tick', translated_gate(translation(), dict(ctx, now=130, clock=dict(CLOCK, descriptor_digest=HASH))), 'clock_domain')
    reversed_window = translation(); reversed_window['source_deadline_tick_ns'] = '1000'; seal(reversed_window, 'translation_digest')
    expect('window.source_expired', semantic_error('WindowTranslation', reversed_window), 'window_invalid')
    policy, state = edge()
    for seq, t, value, expected in [(1, 0, 12, 'idle'), (2, 1000000, 5, 'reset_observed'), (3, 2000000, 10, 'tracking'),
            (4, 3000000, 11, 'tracking'), (5, 4000000, 12, 'edge'), (6, 5000000, 12, 'idle')]:
        state, result = edge_step(state, policy, sample(state, seq, t, value), dict(ctx, now=t))
        expect('edge.normal.' + str(seq), result, expected); expect('edge.state.' + str(seq), valid('EdgeState', state) and semantic_error('EdgeState', state) is None, True)
    same = sample(state, 6, 5000000, 12)
    expect('edge.repeat', edge_step(state, policy, same, dict(ctx, now=5000000)), (state, 'duplicate_or_old'))
    changed = seal(dict(same, raw='13'), 'sample_digest')
    expect('edge.same_sequence_changed', edge_step(state, policy, changed, dict(ctx, now=5000000))[1], 'sequence_conflict')
    for delivery in ('baseline', 'reconcile'):
        p, s = edge(); s, result = edge_step(s, p, sample(s, 1, 0, 5, delivery), dict(ctx, now=0))
        expect('edge.' + delivery, (result, s['phase']), ('baseline', 'needs_reset'))
    for flag, expected in [('busy', 'suppressed_busy'), ('armed', 'suppressed_inactive')]:
        p, s = edge(); p['stable_for_ms'] = 0
        s['binding']['policy_ref']['digest'] = digest(p)
        s, _ = edge_step(s, p, sample(s, 1, 0, 5), dict(ctx, now=0))
        s, result = edge_step(s, p, sample(s, 2, 1000000, 10), dict(ctx, now=1000000, **{flag: flag == 'busy'}))
        expect('edge.' + flag, result, expected)
        expect('edge.' + flag + '_consumed', s['phase'], 'needs_reset')
        expect('edge.' + flag + '_no_replay', edge_step(s, p, sample(s, 3, 2000000, 11), dict(ctx, now=2000000))[1], 'idle')
    p, s = edge(); s, _ = edge_step(s, p, sample(s, 1, 0, 5), dict(ctx, now=0))
    s, _ = edge_step(s, p, sample(s, 2, 1000000, 10), dict(ctx, now=1000000))
    for name, t, now, patch in [('gap', 7000000, 7000000, {}), ('age_equal', 2000000, 7000000, {}), ('future', 3000000, 2000000, {}),
            ('backward', 0, 2000000, {}), ('untrusted', 2000000, 2000000, {'sample_trusted': False})]:
        out, result = edge_step(s, p, sample(s, 3, t, 10), dict(ctx, now=now, **patch))
        expect('edge.invalid.' + name, (result, out['phase']), ('invalid', 'needs_reset'))
    falling, fs = edge(); falling.update(direction='falling', enter_raw='5', reset_raw='10', stable_for_ms=0)
    fs['binding']['policy_ref']['digest'] = digest(falling)
    fs, _ = edge_step(fs, falling, sample(fs, 1, 0, 10), dict(ctx, now=0))
    expect('edge.falling', edge_step(fs, falling, sample(fs, 2, 1, 5), dict(ctx, now=1))[1], 'edge')
    changed = sample(s, 3, 2000000, 10); changed['binding']['source_epoch'] = 'new'; seal(changed, 'sample_digest')
    expect('edge.source_epoch', edge_step(s, p, changed, dict(ctx, now=2000000)), (s, 'source_binding'))
    expect('edge.policy_swap', edge_step(s, dict(p, stable_for_ms=0), sample(s, 3, 2000000, 10), dict(ctx, now=2000000))[1], 'policy_binding')
    unit_wrong = seal(dict(sample(s, 3, 2000000, 10), unit='other-unit'), 'sample_digest')
    expect('edge.unit_swap', edge_step(s, p, unit_wrong, dict(ctx, now=2000000))[1], 'invalid')
    ledger, policy, charge = budget(); charged, result = charge_budget(ledger, policy, charge, ctx)
    expect('budget.first', result, 'charged'); expect('budget.duplicate', charge_budget(charged, policy, charge, ctx), (charged, 'existing'))
    changed = seal(dict(charge, amount=2), 'charge_digest')
    expect('budget.same_id_changed', charge_budget(charged, policy, changed, ctx)[1], 'identity_conflict')
    second = seal(dict(charge, charge_id='charge-2', execution_id='new-run-execution'), 'charge_digest')
    two, _ = charge_budget(charged, policy, second, ctx)
    third = seal(dict(charge, charge_id='charge-3'), 'charge_digest')
    blocked, result = charge_budget(two, policy, third, ctx)
    expect('budget.new_run_not_reset', result, 'exceeded')
    expect('budget.window_no_auto_resume', charge_budget(blocked, policy, third, dict(ctx, now=100000000))[1], 'latched')
    at_end = seal(dict(charge, charge_id='charge-end', charged_tick_ns='20000000'), 'charge_digest')
    expect('budget.window_equality', charge_budget(two, policy, at_end, dict(ctx, now=20000000))[1], 'charged')
    before = seal(dict(at_end, charged_tick_ns='19999999'), 'charge_digest')
    expect('budget.window_before', charge_budget(two, policy, before, dict(ctx, now=19999999))[1], 'exceeded')
    expect('budget.rollback', charge_budget(ledger, policy, charge, dict(ctx, abort_before_commit=True)), (ledger, 'rolled_back'))
    changed = copy.deepcopy(charge); changed['clock']['descriptor_digest'] = HASH; seal(changed, 'charge_digest')
    expect('budget.restart', charge_budget(ledger, policy, changed, ctx)[1], 'clock_domain')
    changed = copy.deepcopy(policy); changed['policy_ref']['revision'] = '2'
    expect('budget.new_policy_not_reset', charge_budget(charged, changed, second, ctx)[1], 'policy_binding')
    changed = dict(policy, limit=100)
    expect('budget.false_limit', charge_budget(charged, changed, second, ctx)[1], 'invalid')
    expect('checks.unique', len({c['id'] for c in checks}), len(checks))
    recorded = [dict(id=c['id'], comparison='whole_fixture_snapshot', equal=True) if isinstance(c['actual'], tuple) and c['actual'] and isinstance(c['actual'][0], dict) else c for c in checks]
    return dict(contract=VERSION, approved=False, checks_passed=len(checks), all_passed=True, checks=recorded,
        runtime_validation=dict(http=0, ipc=0, sqlite=0, concurrency=0, clock_provider=0, devices=0),
        versions=dict(python=platform.python_version(), jsonschema=version('jsonschema'), rfc8785=version('rfc8785')),
        input_sha256={p.relative_to(SUITE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--report', action='store_true'); p.add_argument('--check-report', action='store_true'); p.add_argument('--staged', action='store_true'); a = p.parse_args()
    if a.staged and not a.check_report: p.error('--staged要求--check-report')
    target = ROOT / 'reference-report.json'
    if a.check_report:
        def read(path): return subprocess.check_output(['git', 'show', ':' + path.relative_to(SUITE).as_posix()], cwd=SUITE) if a.staged else path.read_bytes()
        report = json.loads(read(target)); assert set(report['input_sha256']) == {p.relative_to(SUITE).as_posix() for p in INPUTS}
        for path in INPUTS: assert hashlib.sha256(read(path)).hexdigest() == report['input_sha256'][path.relative_to(SUITE).as_posix()], path
        print(json.dumps(dict(report_bindings_passed=len(INPUTS), staged=a.staged)))
    else:
        report = run()
        if a.report: target.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        print(json.dumps({k: v for k, v in report.items() if k not in ('checks', 'input_sha256')}, ensure_ascii=False, indent=2))
