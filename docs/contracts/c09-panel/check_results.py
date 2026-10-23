"""面板结果结构和合成上下文关联参考检查；不实现服务器投影器或授权提供者。"""
import argparse
import copy
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path
import subprocess
from urllib.parse import urljoin

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
PUBLIC = REPO / 'docs/contracts/df01-source/source/public.schema.json'
INPUTS = [ROOT / n for n in ('RESULTS.md', 'result.schema.json', 'result-cases.json',
                            'check_results.py', 'method-bindings.json')] + [PUBLIC]
RANK = {'sent': 0, 'acknowledged': 1, 'effect_verified': 2}


def load(raw):
    def pairs(items):
        value = {}
        for k, v in items:
            if k in value: raise ValueError('重复键')
            value[k] = v
        return value
    def invalid(v): raise ValueError('非法常量：' + v)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    def finite(v):
        if isinstance(v, float) and not math.isfinite(v): raise ValueError('非有限JSON数值')
        if isinstance(v, dict):
            for item in v.values(): finite(item)
        if isinstance(v, list):
            for item in v: finite(item)
    finite(value)
    return value


def digest(value): return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def duplicate(items, key): return len({item[key] for item in items}) != len(items)


def holder_valid(mode, holder): return (holder['relation'] == 'none') == (mode == 'automatic')


def target_errors(items):
    if duplicate(items, 'service_alias'): return {'duplicate_target'}
    return {'target_revision'} if any((i['status'] == 'applied') != (i['applied_revision'] is not None) for i in items) else set()


def dynamic_errors(ref, value, c, registry, evaluate=True):
    item = c['approved_schemas'].get(ref['schema_id'])
    if item is None or ref['definition'] != item['definition'] or ref['schema_digest'] != digest(item['schema']):
        return {'schema_binding'}
    if evaluate and not Draft202012Validator(item['schema'], registry=registry, format_checker=FormatChecker()).is_valid(value):
        return {'dynamic_value'}
    return set()


def decision(packet, c, validator, registry, bindings):
    if not validator.is_valid(packet): return {'structure'}
    v = packet['value']; view = bindings[packet['method']]['result_view']; errors = set()
    # 以下权威、投影批准和快照全是人工夹具，不从响应自证，也未调用实际服务。
    if not c['authorized'] or not c['delegation_active'] or not c['request_binding_matches']:
        errors.add('authority')
    for field, expected in c['expected_fields'].items():
        if v.get(field) != expected: errors.add('object_binding')
    if view == 'MetaView' and not set(v['panel_features']) <= set(c['allowed_features']): errors.add('features')
    if view == 'ClockView' and v['status'] == 'synchronized':
        if any(v[k] is None for k in ('sampled_at', 'offset_ms', 'uncertainty_ms', 'sample_age_ms')): errors.add('clock_quality')
    if view == 'ClockAssessmentView':
        keys = ('sample_age_ms', 'uncertainty_now_ms', 'utc_lower_ms', 'utc_upper_ms')
        if v['eligible_for_absolute'] and any(v[k] is None for k in keys): errors.add('clock_quality')
        if v['utc_lower_ms'] is not None and v['utc_upper_ms'] is not None and v['utc_lower_ms'] > v['utc_upper_ms']:
            errors.add('clock_interval')
    if view == 'DevicePageView' and duplicate(v['items'], 'device_id'): errors.add('duplicate_device')
    if view == 'CapabilityView':
        if duplicate(v['actions'], 'action_id') or duplicate(v['triggers'], 'trigger_id'): errors.add('duplicate_capability')
        refs = [v['state_schema_ref']]
        for action in v['actions']:
            if action['default_completion'] not in action['supported_completion']: errors.add('completion_default')
            refs.extend([action['parameters_schema_ref'], action['result_schema_ref']])
        refs.extend(t['payload_schema_ref'] for t in v['triggers'])
        for r in refs: errors |= dynamic_errors(r, None, c, registry, False)
    if view in ('ObservationView', 'DefinitionView'):
        q = v['values'] if view == 'ObservationView' else v['definition']
        errors |= dynamic_errors(q['schema_ref'], q['value'], c, registry)
        if view == 'ObservationView':
            if v['projection_status'] != c['projection_status']: errors.add('projection_scope')
        elif not c['definition_fully_visible']: errors.add('definition_scope')
    if view == 'CommandView':
        if (v['phase'] == 'finished') == (v['outcome'] == 'pending'): errors.add('command_phase')
        if v['outcome'] in ('unknown', 'blocked', 'expired') and v['automation_continuation'] != 'paused_latched': errors.add('continuation')
        if v['outcome'] in ('failed', 'unknown', 'cancelled', 'expired', 'blocked') and v['reason_code'] is None: errors.add('reason')
        if v['outcome'] == 'unknown':
            if v['effect_status'] == 'not_sent' or v['resource_status'] == 'held': errors.add('unknown_effect')
            if v['resource_status'] == 'clear' and v['resolution_summary'] is None: errors.add('unknown_resolution')
        if v['outcome'] == 'cancelled' and v['cancellation_state'] != 'confirmed': errors.add('cancellation')
        if v['outcome'] == 'succeeded':
            a = v['achieved_completion']
            if a is None or RANK[a] < RANK[v['required_completion']]: errors.add('completion')
            allowed = {'sent': ('possible', 'acknowledged', 'verified'), 'acknowledged': ('acknowledged', 'verified'), 'effect_verified': ('verified',)}
            if a is not None and v['effect_status'] not in allowed[a]: errors.add('effect')
        if v['resolution_summary'] is not None and (v['phase'] != 'finished' or v['automation_continuation'] != 'paused_latched'):
            errors.add('resolution')
    if view == 'ControlView':
        if not holder_valid(v['mode'], v['holder']): errors.add('holder')
        pending = v['pending_change']
        if pending is not None and not holder_valid(pending['target_mode'], pending['holder']): errors.add('holder')
        if v['gate_state'] == 'fencing' and pending is None: errors.add('pending_control')
        if v['gate_state'] == 'ready' and (pending is not None or v['unresolved']['has_hidden'] or v['unresolved']['visible_command_ids']): errors.add('ready')
    if view == 'ControlOperationView':
        if not holder_valid(v['target']['mode'], v['target']['holder']): errors.add('holder')
        if (v['state'] == 'effective') != (v['effective_version'] is not None): errors.add('effective_version')
        if v['state'] == 'effective' and v['effective_version'] != v['target']['version']: errors.add('effective_version')
        current = c['current_control']
        ready = (v['state'] == 'effective' and c['operation_epoch'] == current['epoch']
                 and v['target']['version'] == current['version'] and v['target']['mode'] == current['mode']
                 and v['target']['holder'] == current['holder'] and current['gate_state'] == 'ready'
                 and not current['pending'] and not current['unresolved'])
        if v['ready'] != ready: errors.add('ready_binding')
    if view == 'TransferView' and (v['state'] == 'accepted') != (v['accept_operation_id'] is not None): errors.add('transfer_operation')
    if view == 'MutationView':
        errors |= target_errors(v['visible_targets'])
        if v['state'] == 'applied' and (not c['all_targets_applied'] or any(t['status'] != 'applied' for t in v['visible_targets'])):
            errors.add('global_application')
    if view == 'CapacityView':
        if v['panel_budget'] != c['panel_budget'] or v['current_panel_usage'] != c['panel_usage']: errors.add('capacity_scope')
    if view == 'SceneCatalogView' and duplicate(v['entries'], 'scene_id'): errors.add('duplicate_scene')
    if view == 'EvidencePageView':
        if duplicate(v['items'], 'evidence_id'): errors.add('duplicate_evidence')
        if not {i['evidence_id'] for i in v['items']} <= set(c['command_evidence_ids']): errors.add('evidence_owner')
        if v['resource_release_summary']['status'] != c['resource_status']: errors.add('resource_release')
    if view == 'DefinitionView':
        if v['published'] != (v['definition_version'] is not None): errors.add('definition_version')
        if duplicate(v['proof_summaries'], 'proof_id'): errors.add('duplicate_proof')
    if view == 'RunView':
        if duplicate(v['grant_summaries']['items'], 'controller_alias'): errors.add('duplicate_grant')
        if v['lifecycle'] in ('armed', 'running') and (not c['all_grants_applied'] or any(i['status'] != 'applied' for i in v['grant_summaries']['items']) or not (v['grant_summaries']['items'] or v['grant_summaries']['has_hidden'])):
            errors.add('run_grants')
    if view == 'PreflightView' and v['passed'] and (not v['checks'] or not all(i['passed'] for i in v['checks'])): errors.add('preflight_checks')
    if view == 'RecoveryPlanView':
        if duplicate(v['items'], 'step_id'): errors.add('duplicate_step')
        if not c['recovery_plan_fully_visible']: errors.add('recovery_scope')
    if view == 'RecoveryOperationView':
        errors |= target_errors(v['target_status_summary']['items'])
        if int(v['committed_run_revision']) <= int(v['previous_run_revision']): errors.add('recovery_revision')
        if v['state'] in ('ready', 'running', 'completed') and (not c['all_targets_applied'] or any(i['status'] != 'applied' for i in v['target_status_summary']['items'])): errors.add('recovery_targets')
    if view == 'IndependenceView' and v['verdict'] != c['authoritative_verdict']: errors.add('proof_verdict')
    return errors


def mutate(value, changes):
    for change in changes:
        node = value
        for part in change['path'][:-1]: node = node[part]
        if change.get('delete'): del node[change['path'][-1]]
        else: node[change['path'][-1]] = copy.deepcopy(change['value'])


def hashes(staged=False):
    return {p.relative_to(REPO).as_posix(): hashlib.sha256(subprocess.check_output(
        ['git', 'show', ':' + p.relative_to(REPO).as_posix()], cwd=REPO) if staged else p.read_bytes()).hexdigest() for p in INPUTS}


def run():
    schema = load((ROOT / 'result.schema.json').read_bytes())
    data = load((ROOT / 'result-cases.json').read_bytes())
    bindings = load((ROOT / 'method-bindings.json').read_bytes())['methods']
    public = load(PUBLIC.read_bytes())
    Draft202012Validator.check_schema(schema)
    views = {v['result_view'] for v in bindings.values()}
    assert len(bindings) == 35 and len(views) == 21
    assert set(data['fixtures']) == views
    expected_branches = [{'type': 'object', 'properties': {'method': {'const': m}, 'value': {'$ref': '#/$defs/' + v['result_view']}}, 'required': ['method', 'value'], 'additionalProperties': False} for m, v in bindings.items()]
    assert schema['oneOf'] == expected_branches, '35个方法与View错配'
    for name, definition in schema['$defs'].items():
        if definition.get('type') == 'object':
            assert definition['additionalProperties'] is False and set(definition['required']) == set(definition['properties']), name
    registry = Registry().with_resources([(public['$id'], Resource.from_contents(public)),
        (urljoin(schema['$id'], '../df01-source/source/public.schema.json'), Resource.from_contents(public))])
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    assert data['purpose'] == 'design_fixture_only' and data['runtime_approved'] is False
    results = []
    for method, row in bindings.items():
        v = copy.deepcopy(data['fixtures'][row['result_view']]); c = copy.deepcopy(data['context'])
        errors = decision({'method': method, 'value': v}, c, validator, registry, bindings)
        assert not errors, (method, errors)
        results.append({'id': method, 'passed': True, 'kind': 'positive_result'})
    for case in data['cases']:
        method = case['method']; view = bindings[method]['result_view']
        packet = {'result': {'method': method, 'value': copy.deepcopy(data['fixtures'][view])}, 'context': copy.deepcopy(data['context'])}
        mutate(packet, case['changes'])
        errors = decision(packet['result'], packet['context'], validator, registry, bindings)
        assert (not errors) == case['valid'], (case['id'], errors)
        if not case['valid']: assert case['expected_error'] in errors, (case['id'], errors)
        results.append({'id': case['id'], 'passed': True, 'errors': sorted(errors)})
    assert len({r['id'] for r in results}) == len(results)
    return dict(all_passed=True, approved=False, runtime_approved=False, scope='21结果结构与人工可信上下文关联；不执行生产投影或真实授权',
                methods=35, views=21, cases_passed=len(results), browser_tests_executed=0, database_tests_executed=0,
                device_tests_executed=0, runtime_projection_tests_executed=0, authority_provider_tests_executed=0,
                tools={n: version(n) for n in ('jsonschema', 'referencing', 'rfc8785')}, results=results, input_sha256=hashes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(); group.add_argument('--report', action='store_true'); group.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true'); args = parser.parse_args()
    if args.staged and not args.check_report: parser.error('--staged仅配合--check-report')
    target = ROOT / 'result-report.json'
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + target.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else target.read_bytes()
        report = load(raw)
        assert report['all_passed'] is True and report['approved'] is False and report['runtime_approved'] is False
        assert report['input_sha256'] == hashes(args.staged), '报告输入变化'
        print(json.dumps(dict(bindings_matched=len(INPUTS), staged=args.staged, tests_rerun=False))); return
    report = run()
    if args.report: target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('results', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__': main()
