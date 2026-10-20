"""合并通道的离线参考检查；无真实鉴权、浏览器、SQLite或设备操作。"""
import argparse
import base64
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urljoin
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
import build_channel_v02 as build
import check_bundle as bundle

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
PUBLIC = ROOT.parent / 'df01-source/source/public.schema.json'
INPUTS = [ROOT / n for n in ('CHANNEL_V02.md', 'build_channel_v02.py', 'check_channel_v02.py',
    'channel-v02.schema.json', 'method-registry-v02.json', 'channel-v02-cases.json',
    'channel.schema.json', 'bundle.schema.json', 'check_bundle.py', 'method-bindings.json',
    'method-input.schema.json', 'method-cases.json', 'result.schema.json', 'result-cases.json')] + [PUBLIC]
load = bundle.load
digest = bundle.digest
mutate = bundle.mutate


def resources(schema, fixture):
    items = [(schema['$id'], Resource.from_contents(schema))]
    public = load(PUBLIC.read_bytes()); items.append((public['$id'], Resource.from_contents(public)))
    for name in ('method-input.schema.json', 'result.schema.json', 'bundle.schema.json'):
        doc = load((ROOT / name).read_bytes()); items.append((doc['$id'], Resource.from_contents(doc)))
        items.append((urljoin(doc['$id'], '../df01-source/source/public.schema.json'), Resource.from_contents(public)))
    items.extend((sid, Resource.from_contents(doc, default_specification=DRAFT202012)) for sid, doc in fixture['documents'].items())
    return Registry().with_resources(items)


def active_errors(f, c, require_active=True):
    errors = set()
    if not c['authorized'] or not c['approval_active'] or c['expired']: errors.add('authority')
    if require_active and not c['active']: errors.add('inactive')
    if f['public_binding'] != c['public_binding'] or not c['port_matches']: errors.add('binding')
    if f['activation_ref'] != c['activation_ref']: errors.add('activation')
    a = f['activation_ref']
    if a['registry_ref'] != c['registry_ref'] or a['scope_revision'] != c['scope_revision']: errors.add('activation')
    if a['bundle_ref'] is not None and (not c['bundle_verified'] or a['bundle_ref'] != c['bundle_ref']): errors.add('bundle')
    return errors


def check_dynamic(method, value, kind, c, fixture, registry):
    errors = set()
    def role(name, actual, supplied=None, evaluate=True):
        expected = c['roles'][name]
        if c['activation_ref']['bundle_ref'] is None: errors.add('dynamic_bundle'); return
        export = next((e for e in fixture['manifest']['exports'] if e['binding_key'] == expected), None)
        if export is None: errors.add('dynamic_role'); return
        ref = export['schema_ref']
        if supplied is not None and supplied != ref: errors.add('dynamic_ref'); return
        uri = ref['schema_id'] + '#/$defs/' + ref['definition']
        if evaluate and not Draft202012Validator({'$ref': uri}, registry=registry, format_checker=FormatChecker()).is_valid(actual): errors.add('dynamic_value')
    if kind == 'input':
        if method == 'controller.submitCommand':
            if any(value[k] != c['action'][k] for k in ('device_id', 'action_id', 'capability_version')): errors.add('action_binding')
            role('parameters', value['parameters'])
        if method in ('seamer.createDefinition', 'seamer.updateDraft'): role('definition', value['definition'])
    else:
        view = c['methods'][method]['result_view']
        if view == 'ObservationView': role('state', value['values']['value'], value['values']['schema_ref'])
        if view == 'DefinitionView': role('definition', value['definition']['value'], value['definition']['schema_ref'])
        if view == 'CapabilityView':
            role('state', None, value['state_schema_ref'], False)
            for a in value['actions']:
                if a['action_id'] != c['action']['action_id'] or a['capability_version'] != c['action']['capability_version']: errors.add('action_binding')
                role('parameters', None, a['parameters_schema_ref'], False)
                role('action_result', None, a['result_schema_ref'], False)
            for t in value['triggers']: role('trigger', None, t['payload_schema_ref'], False)
    return errors


def frame_errors(f, c, validator, fixture, registry, direction, last=0):
    if not validator.is_valid(f): return {'structure'}
    if len(bundle.canonical(f)) > 65536: return {'frame_capacity'}
    typ = f['type']; errors = set()
    if direction != ('panel' if typ.startswith('panel.') else 'host'): errors.add('direction')
    if 'channel_sequence' in f and int(f['channel_sequence']) <= last: errors.add('sequence')
    if 'activation_ref' in f: errors |= active_errors(f, c, typ != 'host.active')
    elif 'public_binding' in f and f['public_binding'] != c['public_binding']: errors.add('binding')
    if typ == 'host.port':
        if f['registry_ref'] != c['registry_ref']: errors.add('registry')
        if f['target_handle'] != c['target_handle']: errors.add('target')
        rows = {r['method']: r for r in load((ROOT / 'method-registry-v02.json').read_bytes())['registry']['methods']}
        if f['methods'] != [rows[m] for m in sorted(c['offered_methods'])]: errors.add('offered_methods')
    if typ in ('host.bundle_offer', 'host.bundle_chunk', 'panel.bundle_ready', 'host.bundle_revoke'):
        m = fixture['manifest']; expected = {'bundle_id': m['bundle_id'], 'manifest_digest': m['manifest_digest']}
        if typ == 'host.bundle_offer':
            if f['manifest'] != m or f['manifest']['registry_ref'] != c['registry_ref']: errors.add('bundle_binding')
        else:
            if any(f[k] != v for k, v in expected.items()): errors.add('bundle_binding')
        if typ != 'host.bundle_revoke' and c['active']: errors.add('bundle_stage')
        if typ == 'panel.bundle_ready':
            if not c['bundle_received_complete']: errors.add('bundle_incomplete')
            if f['registry_ref'] != c['registry_ref'] or f['scope_revision'] != c['scope_revision']: errors.add('bundle_binding')
        if typ == 'host.bundle_chunk':
            raw = bundle.canonical(fixture['documents'][f['schema_id']]) if f['schema_id'] in fixture['documents'] else b''
            expected_chunk = raw[f['index']*16384:(f['index']+1)*16384]
            if not expected_chunk or f['content_base64'] != base64.b64encode(expected_chunk).decode('ascii'): errors.add('bundle_chunk')
    if typ in ('panel.request', 'panel.subscribe'):
        m = f['method']
        if m not in c['allowed_methods'] or f['target_handle'] != c['target_handle']: errors.add('method_scope')
        if f['resource_ref'] is not None and any(f['resource_ref'][k] != c[k] for k in ('authority_service_id', 'database_instance_id')): errors.add('target')
        errors |= check_dynamic(m, f['payload']['value'], 'input', c, fixture, registry)
    if 'method' in f and f['method'].split('.')[0] != c['service_family']: errors.add('authority_family')
    if typ == 'host.result':
        if f['method'] not in c['allowed_methods']: errors.add('method_scope')
        if f['request_id'] != c['original_request']['request_id'] or f['method'] != c['original_request']['method'] or f['activation_ref'] != c['original_request']['activation_ref']: errors.add('request_binding')
        expected = {'accepted': {'ok'}, 'pending_confirmation': {'needs_host_confirmation'}, 'cancelled': {'user_cancelled'},
                    'rejected': {'authority_denied', 'activation_stale', 'schema_invalid', 'target_changed', 'conflict', 'not_found_or_invisible', 'capacity_exceeded', 'expired', 'protocol_error'},
                    'unavailable': {'source_unavailable', 'capacity_exceeded', 'unknown_outcome', 'not_found_or_invisible', 'activation_stale'}}
        if f['reason_code'] not in expected[f['status']]: errors.add('result_reason')
        mode = c['methods'][f['method']]['mode']
        if f['status'] == 'pending_confirmation' and mode != 'host_confirm': errors.add('confirmation_mode')
        if f['status'] == 'accepted':
            if mode == 'host_confirm' and not c['confirmation_consumed']: errors.add('confirmation')
            errors |= check_dynamic(f['method'], f['result']['value'], 'result', c, fixture, registry)
    if typ == 'host.projection' and f['value'] is not None:
        errors |= check_dynamic(f['method'], f['value']['value'], 'result', c, fixture, registry)
    if typ == 'host.active':
        if f['target_handle'] != c['target_handle']: errors.add('target')
        if c['activation_already_issued'] or c['active']: errors.add('activation_reuse')
        if f['activation_ref']['bundle_ref'] is not None and not c['bundle_ready_reported']: errors.add('bundle_ready')
    return errors


def subscription_trace(events, frames, context, validator, fixture, registry):
    c = copy.deepcopy(context); records = {}; seq = {'host': 0, 'panel': 0}; decisions = []
    rows = {r['method']: r for r in load((ROOT / 'method-registry-v02.json').read_bytes())['registry']['methods']}
    for event in events:
        if event['kind'] == 'context': c.update(copy.deepcopy(event['values'])); decisions.append(True); continue
        f = copy.deepcopy(frames[event['frame']]); mutate(f, event.get('changes', []))
        direction = event['direction']; errors = frame_errors(f, c, validator, fixture, registry, direction, seq[direction])
        typ = f['type']; sid = f.get('subscription_id'); record = records.get(sid)
        if not errors:
            seq[direction] = int(f['channel_sequence'])
            if typ == 'panel.subscribe':
                identity = digest({k: v for k, v in f.items() if k != 'channel_sequence'})
                if record:
                    if record['identity'] != identity or record['state'] in ('gap', 'closed', 'closing'): errors.add('subscription_reuse')
                elif len(records) >= c['used_id_limit'] or sum(r['state'] in ('pending', 'live', 'invalidated') for r in records.values()) >= c['subscription_limit']: errors.add('subscription_capacity')
                else: records[sid] = {'identity': identity, 'method': f['method'], 'mode': rows[f['method']]['subscription_mode'], 'state': 'pending', 'sent': 0, 'acked': 0, 'pending': {}}
            elif typ in ('host.projection', 'panel.projection_ack', 'panel.unsubscribe'):
                if record is None: errors.add('subscription_missing')
                elif typ == 'panel.unsubscribe':
                    if record['state'] != 'closed': record['state'] = 'closing'
                elif typ == 'panel.projection_ack':
                    n = int(f['projection_sequence'])
                    if n <= record['acked'] or record['pending'].get(n) != f['projection_digest']: errors.add('projection_ack')
                    else:
                        record['acked'] = n; record['pending'] = {k: v for k, v in record['pending'].items() if k > n}
                else:
                    n = int(f['projection_sequence']); kind = f['kind']
                    if f['method'] != record['method']: errors.add('subscription_method')
                    if n != record['sent'] + 1: errors.add('projection_sequence')
                    if record['state'] in ('closed', 'gap') or (record['state'] == 'closing' and kind != 'closed'): errors.add('projection_state')
                    if kind == 'baseline' and record['state'] != 'pending': errors.add('projection_baseline')
                    if kind == 'update' and record['state'] != 'live': errors.add('projection_baseline')
                    if kind == 'invalidated' and record['mode'] != 'invalidation': errors.add('projection_mode')
                    if kind in ('baseline', 'update', 'invalidated') and sum(len(r['pending']) for r in records.values()) >= c['window_limit']:
                        errors.add('projection_capacity'); record['state'] = 'gap'
                    if not errors:
                        record['sent'] = n
                        record['state'] = {'baseline': 'live', 'update': 'live', 'invalidated': 'invalidated', 'gap': 'gap', 'closed': 'closed'}[kind]
                        if kind in ('baseline', 'update', 'invalidated'): record['pending'][n] = digest(f)
            elif typ == 'panel.ack': pass  # 传输ACK不改变投影消费窗口。
            else: raise ValueError('轨迹只接收订阅及传输ACK')
        if errors and typ == 'host.projection' and record and record['state'] not in ('closing', 'closed'):
            record['state'] = 'gap'
        # 退役释放的是流控槽，不提升消费ACK；有限墓碑保留sent/acked防止ID复用。
        if record and record['state'] in ('gap', 'closed'): record['pending'].clear()
        decisions.append(not errors)
    return decisions, {k: {'state': v['state'], 'sent': v['sent'], 'acked': v['acked'], 'pending': len(v['pending'])} for k, v in records.items()}


def hashes(staged=False):
    return {p.relative_to(REPO).as_posix(): hashlib.sha256(subprocess.check_output(['git', 'show', ':' + p.relative_to(REPO).as_posix()], cwd=REPO) if staged else p.read_bytes()).hexdigest() for p in INPUTS}


def run():
    for name, value in build.build().items(): assert (ROOT / name).read_bytes() == build.encoded(value), name
    data = load((ROOT / 'channel-v02-cases.json').read_bytes()); schema = load((ROOT / 'channel-v02.schema.json').read_bytes())
    assert data['runtime_approved'] is False and data['purpose'] == 'synthetic_channel_v02_only'
    Draft202012Validator.check_schema(schema)
    registry = resources(schema, data['bundle']); validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    b = data['bundle']; bs = load((ROOT / 'bundle.schema.json').read_bytes())
    assert not bundle.bundle_errors(b['manifest'], {k: bundle.canonical(v) for k, v in b['documents'].items()}, b['context'], bs)
    method_rows = load((ROOT / 'method-registry-v02.json').read_bytes())
    assert method_rows['registry_ref'] == {'revision': method_rows['registry']['revision'], 'digest': digest(method_rows['registry'])}
    rows = {r['method']: r for r in method_rows['registry']['methods']}
    assert len(rows) == 35 and sum(r['subscription_mode'] == 'projection' for r in rows.values()) == 17
    assert {m for m, r in rows.items() if r['subscription_mode'] == 'invalidation'} == {'controller.listDevices', 'controller.getCommandEvidence'}
    results = []
    for case in data['frame_cases']:
        f = copy.deepcopy(data['frames'][case['frame']]); c = copy.deepcopy(data['context'])
        mutate(f, case.get('changes', [])); mutate(c, case.get('context_changes', []))
        if 'original_method' in case: c['original_request']['method'] = case['original_method']
        errors = frame_errors(f, c, validator, b, registry, case['direction'], case.get('last_sequence', 0))
        assert (not errors) == case['valid'], (case['id'], errors)
        if 'error' in case: assert case['error'] in errors, (case['id'], errors)
        results.append({'id': case['id'], 'passed': True, 'errors': sorted(errors)})
    for case in data['traces']:
        c = copy.deepcopy(data['context']); mutate(c, case.get('context_changes', []))
        decisions, states = subscription_trace(case['events'], data['frames'], c, validator, b, registry)
        assert decisions == case['decisions'] and states == case['states'], (case['id'], decisions, states)
        results.append({'id': case['id'], 'passed': True, 'decisions': decisions, 'states': states})
    assert len({r['id'] for r in results}) == len(results)
    return {'all_passed': True, 'approved': False, 'runtime_approved': False, 'cases_passed': len(results),
            'method_count': 35, 'projection_methods': 17, 'invalidation_methods': 2, 'results': results,
            'runtime_validation': {'browser': 0, 'authority_provider': 0, 'sqlite': 0, 'device': 0}, 'artifact_sha256': hashes()}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--report', action='store_true'); p.add_argument('--check-report', action='store_true'); p.add_argument('--staged', action='store_true'); args = p.parse_args()
    path = ROOT / 'channel-v02-report.json'
    if args.staged and not args.check_report: p.error('--staged需要--check-report')
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + path.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else path.read_bytes()
        assert load(raw)['artifact_sha256'] == hashes(args.staged), '报告字节过期'
        print('channel0.2报告15输入绑定通过'); return
    report = run()
    if args.report: path.write_bytes(build.encoded(report))
    print('channel0.2合并参考检查通过：' + str(report['cases_passed']) + '项；真实运行0')


if __name__ == '__main__': main()
