"""离线结构、HTTP投影与有限原子步用例；不提供服务或实际并发证明。"""
import argparse
import copy
import json
import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from importlib.metadata import version
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from openapi_spec_validator import validate_spec
from build_contracts import ROOT, SID, VERSION, ROUTES
from reference_model import baseline, choose, commit_state, digest, increment, prepare, reserve, semantic_error, trigger, trigger_binding_error, without

SUITE = ROOT.parents[2]
INPUTS = [ROOT / n for n in ('README.md', 'build_contracts.py', 'reference_model.py', 'check_contracts.py', 'lifecycle.schema.json', 'lifecycle.openapi.json')]
INPUTS += [ROOT.parent / 'c04-program/program.schema.json', SUITE / 'docs/rebirth-c04-automation-design.md']
SCOPE = dict(authority_service_id='seamer', database_instance_id='db')
CLOCK = dict(clock_domain_id='clock_' + '1' * 64, descriptor_digest='sha256:' + '2' * 64)
HASH = 'sha256:' + 'a' * 64


def ref(kind, name=None):
    scope = dict(authority_service_id='controller', database_instance_id='controller-db') if kind in ('grant', 'barrier', 'command', 'completion_evidence', 'preparation_receipt') else copy.deepcopy(SCOPE)
    return dict(kind=kind, scope=scope, object_id=name or kind, revision='1', digest=HASH)
def seal(v, field): v[field] = digest(without(v, field)); return v
def fixture():
    run = dict(scope=copy.deepcopy(SCOPE), run_id='run', definition_id='definition', definition_version='1', artifact_ref=ref('artifact'),
        revision='5', lifecycle='disarmed', business_state=None, arm_generation='2', last_receive_seq='0', active_execution_id=None,
        active_operation_id=None, last_execution_id=None, pause_latches=[], dispatch_eligible=False)
    slot = dict(scope=copy.deepcopy(SCOPE), definition_id='definition', revision='3', active_run_id=None, definition_version=None)
    deps = dict(bindings_digest=HASH, authorization_digest=HASH, control_digest=HASH, source_digest=HASH, evidence_digest=HASH, policy_ref=ref('policy'))
    w = dict(run=run, slot=slot, dependencies=deps, requests={}, consumed=set(), decisions={}, commits={}, outbox=[], new_executions=[])
    ctx = dict(authorized=True, subject_kind='human', storage_healthy=True, request_epoch='epoch', actor='alice', clock=copy.deepcopy(CLOCK),
        now=15, gates_valid=True, abort_before_commit=False, required_targets={'controller': ['device']}, unresolved=False,
        recovery_plan_approved=True, all_required_evidence=True, expected_artifact_ref=ref('artifact'), expected_arm_generation='2',
        target_grants={'controller': ref('grant', 'new-grant')})
    preflight = seal(dict(scope=copy.deepcopy(SCOPE), preflight_id='preflight', run_id='run', purpose='arm', baseline=baseline(w),
        clock=copy.deepcopy(CLOCK), issued_tick_ns='10', expires_tick_ns='20', checks=[dict(controller_id='controller', device_ids=['device'],
            grant_ref=None, status='passed', reason_code='passed')], passed=True, preflight_digest=HASH), 'preflight_digest')
    request = dict(context=dict(context_id='context', idempotency_key='key'), expected_run_revision='5', expected_slot_revision='3',
        preflight_id='preflight', preflight_digest=preflight['preflight_digest'])
    return w, ctx, preflight, request


def recovery():
    w, ctx, _, _ = fixture(); w['run'].update(lifecycle='paused', active_execution_id='old', pause_latches=['failure'])
    w['slot'].update(active_run_id='run', definition_version='1')
    preview = seal(dict(scope=copy.deepcopy(SCOPE), preview_id='preview', run_id='run', prior_execution_id='old', baseline=baseline(w),
        clock=copy.deepcopy(CLOCK), request_epoch='epoch', issued_tick_ns='10', expires_tick_ns='20', trigger_decision_id='decision',
        plan=[dict(step_id='step', disposition='retain_success', previous_command_ref=ref('command'), evidence_refs=[ref('completion_evidence')], parameters_ref=None)],
        unresolved_command_refs=[], preview_digest=HASH), 'preview_digest')
    request = dict(context=dict(context_id='context', idempotency_key='key'), expected_run_revision='5', expected_slot_revision='3', preview_id='preview', preview_digest=preview['preview_digest'])
    return w, ctx, preview, request


def receipts(w):
    r = w['reservation']
    return [dict(controller_id='controller', device_ids=['device'], operation_id=r['operation_id'], execution_id=r['execution_id'],
        arm_generation=r['arm_generation'], target_grant_ref=copy.deepcopy(r['expected_grants']['controller']), state='applied', trusted=True, durable=True)]
def armed():
    w, ctx, p, request = fixture(); w, _ = reserve(w, 'arm', request, p, ctx); w, _ = prepare(w, receipts(w), ctx)
    ctx['expected_arm_generation'] = w['run']['arm_generation']
    return w, ctx
def snapshot(w, event='event', seq='1'):
    return seal(dict(scope=copy.deepcopy(SCOPE), snapshot_id='snapshot_' + event, run_id='run', run_revision=w['run']['revision'],
        artifact_ref=ref('artifact'), inbox_ref=ref('inbox', event), receive_seq=seq, source_state=copy.deepcopy(w['run']['business_state']),
        clock=copy.deepcopy(CLOCK), observations=[], input_snapshot_ref=ref('input_snapshot'), rule_result='true', transitions=[], snapshot_digest=HASH), 'snapshot_digest')


def samples():
    w, ctx, pre, arm_request = fixture(); rw, _, preview, resume_request = recovery()
    snap = snapshot(w)
    decision = seal(dict(scope=copy.deepcopy(SCOPE), decision_id='decision', run_id='run', run_revision_before='5', definition_version='1',
        artifact_ref=ref('artifact'), inbox_ref=ref('inbox', 'event'), receive_seq='1', snapshot_id=snap['snapshot_id'], snapshot_digest=snap['snapshot_digest'],
        result='accepted', reason_code='matched', selected_transition_id=None, execution_id='execution', decision_digest=HASH), 'decision_digest')
    binding = seal(dict(scope=copy.deepcopy(SCOPE), execution_id='execution', run_id='run', artifact_ref=ref('artifact'),
        origin=dict(kind='trigger', decision_id='decision', decision_digest=decision['decision_digest']), arm_generation='3', source_state=None,
        target_state_id=None, input_snapshot_ref=ref('input_snapshot'), resolved_parameters_ref=ref('resolved_parameters'), grants=[ref('grant')],
        clock=copy.deepcopy(CLOCK), plan_digest=HASH, binding_digest=HASH), 'binding_digest')
    op = dict(scope=copy.deepcopy(SCOPE), operation_id='operation', run_id='run', kind='arm', request_digest=HASH, baseline=baseline(w),
        committed_run_revision='6', committed_slot_revision='4', target_arm_generation='3', state='reserved', execution_id=None,
        consumed_preflight_id='preflight', consumed_preview_id=None, targets=[dict(controller_id='controller', device_ids=['device'],
            baseline_grant_ref=None, target_grant_ref=ref('grant'), state='pending', receipt_ref=None, barrier_ref=None)], locally_closed=True, protection_complete=False)
    published = dict(scope=copy.deepcopy(SCOPE), definition_id='definition', definition_version='1', source_draft_revision='1',
        artifact_ref=ref('artifact'), program_digest=HASH, bindings_digest=HASH, published_by='alice')
    draft_content = dict(program=dict(kind='rule', trigger_binding_id='event', condition=dict(kind='literal', value=True), groups=[dict(mode='sequence', steps=[
        dict(kind='delay', step_id='delay', depends_on=[], required=True, failure_policy='stop', delay_ms=0, max_lateness_ms=1000)])]), selections=[], policy_ref=ref('policy'))
    metadata = dict(name='示例', description='', layout={})
    draft = dict(scope=copy.deepcopy(SCOPE), definition_id='definition', revision='1', content=draft_content, content_digest=digest(draft_content),
        selection_digest=digest(draft_content['selections']), metadata_revision='1', metadata=metadata)
    context = dict(context_id='context', idempotency_key='key')
    return dict(DraftRecord=draft, PublishedVersion=published, ActivationSlot=w['slot'], RunRecord=w['run'], DependencyBaseline=baseline(w),
        Preflight=pre, LifecycleOperation=op, EvaluationSnapshot=snap, TriggerDecision=decision, ExecutionBinding=binding,
        ExecutionRecord=dict(binding=binding, revision='1', phase='reserved', outcome='pending', unresolved_command_refs=[], completion_evidence_refs=[], state_commit_event_id=None),
        RecoveryPreview=preview, CreateDefinition=dict(context=context, content=draft_content, metadata=metadata),
        UpdateDraft=dict(context=context, expected_draft_revision='1', content=draft_content),
        UpdateMetadata=dict(context=context, expected_metadata_revision='1', metadata=metadata),
        Publish=dict(context=context, expected_draft_revision='1', expected_content_digest=digest(draft_content), expected_selection_digest=digest(draft_content['selections'])),
        CreateRun=dict(context=context, definition_id='definition', definition_version='1', expected_artifact_ref=ref('artifact')),
        InspectRun=dict(context=context, expected_run_revision='5', expected_slot_revision='3'), Arm=arm_request,
        ProtectRun=dict(context=context, expected_run_revision='5', reason_code='operator'), Resume=resume_request,
        Lookup=dict(context_id='context', idempotency_key='key', operation_id='armRun'),
        LookupResult=dict(operation_id='armRun', request_digest=HASH, result=dict(kind='LifecycleOperation', value=op)))


def run():
    subprocess.run([sys.executable, str(ROOT / 'build_contracts.py'), '--check'], check=True)
    schema = json.loads((ROOT / 'lifecycle.schema.json').read_bytes()); api = json.loads((ROOT / 'lifecycle.openapi.json').read_bytes())
    program = json.loads((ROOT.parent / 'c04-program/program.schema.json').read_bytes())
    registry = Registry().with_resources([(v['$id'], Resource.from_contents(v)) for v in (schema, program)])
    Draft202012Validator.check_schema(schema); validate_spec(api)
    checks = []
    def expect(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(id=name, actual=actual, expected=expected))
    def valid(model, value): return Draft202012Validator({'$ref': SID + '#/$defs/' + model}, registry=registry).is_valid(value)
    def projected(model, value): return Draft202012Validator(dict(components=api['components'], **{'$ref': '#/components/schemas/' + model})).is_valid(value)
    data = samples()
    for name, value in data.items():
        expect('schema.' + name, valid(name, value), True)
        expect('projection.' + name, projected(name, value), True)
        expect('semantic.' + name, semantic_error(name, value), None)
        bad = copy.deepcopy(value); bad['unrecognized'] = True
        expect('closed.' + name, valid(name, bad) or projected(name, bad), False)
    for model, path, value, error in [
        ('ActivationSlot', ['definition_version'], '1', 'slot_pair'),
        ('RunRecord', ['dispatch_eligible'], True, 'run_gate'),
        ('RunRecord', ['lifecycle'], 'running', 'execution_required'),
        ('Preflight', ['checks', 0, 'status'], 'unknown', 'preflight_checks'),
        ('Preflight', ['expires_tick_ns'], '10', 'lifetime'),
        ('RecoveryPreview', ['plan', 0, 'evidence_refs'], [], 'retain_evidence'),
        ('TriggerDecision', ['execution_id'], None, 'decision_execution'),
        ('TriggerDecision', ['snapshot_digest'], None, 'snapshot_pair'),
        ('ExecutionRecord', ['phase'], 'finished', 'finished_pending'),
        ('LifecycleOperation', ['target_arm_generation'], '2', 'arm_generation'),
        ('LifecycleOperation', ['committed_run_revision'], '7', 'run_revision'),
        ('LifecycleOperation', ['committed_slot_revision'], '3', 'slot_revision'),
        ('LifecycleOperation', ['state'], 'ready', 'ready_targets'),
        ('LifecycleOperation', ['protection_complete'], True, 'barrier_incomplete')]:
        bad = copy.deepcopy(data[model]); target = bad
        for key in path[:-1]: target = target[key]
        target[path[-1]] = value
        for field in ('preflight_digest', 'preview_digest', 'decision_digest'):
            if field in bad: seal(bad, field)
        expect('rehashed.' + model + '.' + error, valid(model, bad), True)
        expect('reject.' + model + '.' + error, semantic_error(model, bad), error)
    human_only = {'publishDefinition', 'armRun', 'resumeRun', 'disarmRun', 'retireRun'}
    operations = {op['operationId']: (method, op) for path in api['paths'].values() for method, op in path.items()}
    expect('api.operation_count', len(operations), 24)
    for name, (method, op) in operations.items():
        expect('api.subject.' + name, op['x-subject-kinds'], ['human'] if name in human_only else ['human', 'service'])
        expect('api.version.' + name, any(p['name'] == 'X-LeafSeamer-Contract' and p['required'] and p['schema'] == {'const': VERSION} for p in op['parameters']), True)
        expect('api.csrf.' + name, 'csrf' in op['security'][0], method != 'get')
    snap, decision, execution = (data[n] for n in ('EvaluationSnapshot', 'TriggerDecision', 'ExecutionBinding'))
    expect('binding.trigger', trigger_binding_error(snap, decision, execution, '1', {}), None)
    for field, value, expected in [('run_id', 'other', 'execution_scope'), ('execution_id', 'other', 'execution_identity'),
            ('target_state_id', 'other', 'target_state'), ('input_snapshot_ref', ref('input_snapshot', 'other'), 'execution_snapshot')]:
        changed = copy.deepcopy(execution); changed[field] = value; seal(changed, 'binding_digest')
        expect('binding.rehashed_' + field, trigger_binding_error(snap, decision, changed, '1', {}), expected)
    transition = lambda name, priority, result: dict(transition_id=name, priority=priority, result=result)
    for name, values, expected in [
        ('empty', [], ('no_match', None)), ('none_true', [transition('a', 1, 'unknown')], ('evaluation_unknown', None)),
        ('winner', [transition('a', 2, 'true'), transition('b', 1, 'unknown')], ('accepted', 'a')),
        ('higher_unknown', [transition('a', 2, 'unknown'), transition('b', 1, 'true')], ('evaluation_unknown', None)),
        ('equal_unknown', [transition('a', 2, 'true'), transition('b', 2, 'unknown')], ('evaluation_unknown', None)),
        ('tie', [transition('a', 2, 'true'), transition('b', 2, 'true')], ('ambiguous', None))]:
        expect('choose.' + name, choose(None, values), expected)
    for kind, factory in [('arm', fixture), ('resume', recovery)]:
        w, ctx, preview, request = factory(); new, outcome = reserve(w, kind, request, preview, ctx)
        expect(kind + '.accepted', outcome, 'accepted')
        expect(kind + '.not_eligible', new['run']['dispatch_eligible'], False)
        expect(kind + '.slot', new['slot']['active_run_id'], 'run')
        expect(kind + '.generation', new['run']['arm_generation'], '3')
        expect(kind + '.execution_count', len(new['new_executions']), int(kind == 'resume'))
        same, outcome = reserve(new, kind, request, preview, ctx)
        expect(kind + '.lost_reply', outcome, 'existing'); expect(kind + '.no_second_execution', same, new)
        second = copy.deepcopy(request); second['context']['idempotency_key'] = 'other'
        expect(kind + '.second_consumer', reserve(new, kind, second, preview, ctx)[1], 'conflict')
        altered = copy.deepcopy(request); altered['expected_run_revision'] = '6'
        expect(kind + '.same_key_changed', reserve(new, kind, altered, preview, ctx)[1], 'request_conflict')
        for name, patch, expected in [('revoked', dict(authorized=False), 'forbidden'), ('service', dict(subject_kind='service'), 'forbidden'),
            ('expired', dict(now=20), 'expired'), ('before', dict(now=9), 'expired'), ('storage', dict(storage_healthy=False), 'protected'),
            ('gates', dict(gates_valid=False), 'protected'), ('rollback', dict(abort_before_commit=True), 'rolled_back')]:
            c = dict(ctx, **patch); after, result = reserve(w, kind, request, preview, c)
            expect(kind + '.' + name, result, expected); expect(kind + '.' + name + '_no_mutation', after, w)
        stale = copy.deepcopy(w); stale['dependencies']['control_digest'] = 'sha256:' + 'b' * 64
        expect(kind + '.takeover', reserve(stale, kind, request, preview, ctx)[1], 'stale')
        changed = copy.deepcopy(w); changed['slot'].update(active_run_id='other_run', definition_version='2')
        expect(kind + '.cross_version_slot', reserve(changed, kind, request, preview, ctx)[1], 'slot_owned')
        ready, result = prepare(new, receipts(new), ctx); expect(kind + '.ready', result, 'ready')
        expect(kind + '.ready_lifecycle', ready['run']['lifecycle'], 'armed' if kind == 'arm' else 'paused')
        for field, value, expected in [('state', 'unknown', 'target_unready'), ('durable', False, 'target_unready'),
            ('operation_id', 'other', 'receipt_binding'), ('arm_generation', '2', 'receipt_binding'),
            ('target_grant_ref', ref('grant', 'other-grant'), 'grant_binding')]:
            r = receipts(new); r[0][field] = value
            expect(kind + '.receipt_' + field, prepare(new, r, ctx)[1], expected)
        expect(kind + '.partial_preparation', prepare(new, [], ctx)[1], 'target_coverage')
        failed, _ = prepare(new, [], ctx)
        expect(kind + '.late_receipts_no_restart', prepare(failed, receipts(new), ctx)[1], 'operation_terminal')
        stopped, _ = prepare(new, receipts(new), dict(ctx, storage_healthy=False))
        expect(kind + '.storage_recovery_no_restart', prepare(stopped, receipts(new), ctx)[1], 'protected')
        stale = copy.deepcopy(new); stale['dependencies']['authorization_digest'] = 'sha256:' + 'b' * 64
        expect(kind + '.prepare_revoked', prepare(stale, receipts(new), ctx)[1], 'stale')
    w, ctx, preview, request = recovery(); ctx['unresolved'] = True
    expect('recovery.unresolved', reserve(w, 'resume', request, preview, ctx)[1], 'unresolved')
    w, ctx = armed(); snap = snapshot(w); accepted, result = trigger(w, snap, ctx)
    expect('trigger.accepted', result, 'accepted'); expect('trigger.one_execution', len(accepted['new_executions']), 1)
    expect('trigger.repeat', trigger(accepted, snap, ctx)[1], 'existing_accepted')
    busy_snapshot = snapshot(accepted, 'busy', '2'); busy, result = trigger(accepted, busy_snapshot, ctx)
    expect('trigger.busy', result, 'suppressed_busy')
    idle = copy.deepcopy(busy); idle['run'].update(lifecycle='armed', active_execution_id=None)
    expect('trigger.no_busy_replay', trigger(idle, busy_snapshot, ctx)[1], 'existing_suppressed_busy')
    changed = copy.deepcopy(snap); changed['inbox_ref']['digest'] = 'sha256:' + 'b' * 64; seal(changed, 'snapshot_digest')
    expect('trigger.immutable_event', trigger(accepted, changed, ctx)[1], 'event_conflict')
    for name, change, expected in [('closed', dict(dispatch_eligible=False), 'protected'), ('paused', dict(lifecycle='paused'), 'suppressed_inactive')]:
        changed = copy.deepcopy(w); changed['run'].update(change)
        expect('trigger.' + name, trigger(changed, snapshot(changed), ctx)[1], expected)
    late = copy.deepcopy(w); late['run']['last_receive_seq'] = '10'
    expect('trigger.old_unseen', trigger(late, snapshot(late, 'older', '9'), ctx)[1], 'suppressed_obsolete')
    after, result = trigger(w, snap, dict(ctx, abort_before_commit=True))
    expect('trigger.rollback', result, 'rolled_back'); expect('trigger.rollback_empty', after, w)
    closed = dict(ctx, gates_valid=False)
    expect('trigger.true_not_permission', trigger(w, snap, closed)[1], 'protected')
    execution = accepted['run']['active_execution_id']; committed, result = commit_state(accepted, execution, None, None, ctx)
    expect('commit.success', result, 'committed'); expect('commit.outbox_once', len(committed['outbox']), 1)
    repeated, result = commit_state(committed, execution, None, None, ctx)
    expect('commit.lost_reply', result, 'existing'); expect('commit.no_duplicate_outbox', repeated, committed)
    for name, patch in [('latch', dict(gates_valid=False)), ('evidence', dict(all_required_evidence=False)),
            ('unresolved', dict(unresolved=True))]:
        expect('commit.' + name, commit_state(accepted, execution, None, None, dict(ctx, **patch))[1], 'protected')
    expect('commit.new_generation', commit_state(accepted, execution, None, None, dict(ctx, expected_arm_generation='99'))[1], 'stale')
    expect('commit.rollback', commit_state(accepted, execution, None, None, dict(ctx, abort_before_commit=True))[0], accepted)
    expect('checks.unique', len({c['id'] for c in checks}), len(checks))
    # 大状态快照仅作内部断言，不将tuple-key/set等模拟状态写入JSON报告。
    recorded = [c if not isinstance(c['actual'], dict) else dict(id=c['id'], comparison='whole_fixture_snapshot', equal=True) for c in checks]
    return dict(contract=VERSION, approved=False, checks_passed=len(checks), all_passed=True, operations=len(operations),
        scope='结构和HTTP投影及合成基线、有限串行原子步；不运行服务或数据库', checks=recorded,
        snapshot_assertions_passed=sum(isinstance(c['actual'], dict) for c in checks), runtime_validation=dict(http=0, identity_providers=0, sqlite=0, concurrency=0, devices=0),
        versions=dict(python=platform.python_version(), jsonschema=version('jsonschema'), openapi_spec_validator=version('openapi-spec-validator'), rfc8785=version('rfc8785')),
        input_sha256={p.relative_to(SUITE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})


def main():
    p = argparse.ArgumentParser(); p.add_argument('--report', action='store_true'); p.add_argument('--check-report', action='store_true'); p.add_argument('--staged', action='store_true'); a = p.parse_args()
    target = ROOT / 'reference-report.json'
    if a.staged and not a.check_report: p.error('--staged要求--check-report')
    if a.check_report:
        def read(path): return subprocess.check_output(['git', 'show', ':' + path.relative_to(SUITE).as_posix()], cwd=SUITE) if a.staged else path.read_bytes()
        report = json.loads(read(target)); assert set(report['input_sha256']) == {p.relative_to(SUITE).as_posix() for p in INPUTS}
        for path in INPUTS: assert hashlib.sha256(read(path)).hexdigest() == report['input_sha256'][path.relative_to(SUITE).as_posix()], path
        print(json.dumps(dict(report_bindings_passed=len(INPUTS), staged=a.staged))); return
    report = run()
    if a.report: target.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({k: v for k, v in report.items() if k not in ('checks', 'input_sha256')}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
