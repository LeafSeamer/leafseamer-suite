"""DF06 限定参考判定；可信上下文为合成输入，不实现TLS、授权或设备采样。"""
import copy
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def modified(base, changes):
    result = copy.deepcopy(base)
    for change in changes:
        parent = result
        for part in change['path'][:-1]:
            parent = parent[part]
        parent[change['path'][-1]] = change['value']
    return result


def read_decision(c):
    g = c['grant']
    if not c['transport_authenticated']:
        return 'unauthenticated'
    if not c['pairing_active'] or not c['permission_present'] or g['state'] != 'active':
        return 'forbidden'
    if any(g[k] != c[k] for k in ('peer_binding_id', 'peer_binding_revision', 'purpose')):
        return 'forbidden'
    if not c['object_exists'] or any(g[k] != c[k] for k in (
            'authority_service_id', 'object_id', 'object_kind', 'object_revision')):
        return 'not_found'
    if c['purpose'] == 'validation' and not c['object_current']:
        return 'precondition_failed'
    if not c['capacity_available']:
        return 'limited'
    return 'allow'


def capture_decision(c):
    q, p, r = (c[k] for k in ('challenge', 'pending', 'receipt'))
    if not c['transport_authenticated']:
        return 'unauthenticated'
    if not c['pairing_active'] or not c['source_approved']:
        return 'forbidden'
    if p['state'] != 'pending':
        return 'not_pending'
    if q['verifier_service_id'] != c['local_verifier_service_id']:
        return 'wrong_verifier'
    if q['verifier_domain'] != p['verifier_domain'] or p['verifier_domain'] != c['live_verifier_domain']:
        return 'wrong_domain'
    if q['source_binding'] != c['current_source_binding'] or r['source_binding'] != q['source_binding']:
        return 'source_mismatch'
    if c['trusted_peer_service_id'] != q['source_binding']['owner_service_id']:
        return 'source_mismatch'
    if q['source_binding']['delivery_semantics'] != 'sampled':
        return 'not_sampled'
    if not c['capture_attested']:
        return 'unproven'
    if q['challenge_id'] != p['challenge_id'] or r['challenge_id'] != p['challenge_id']:
        return 'request_mismatch'
    if p['request_digest'] != c['expected_request_digest'] or r['request_digest'] != p['request_digest']:
        return 'request_mismatch'
    if q['scope_digest'] != c['expected_scope_digest'] or r['scope_digest'] != q['scope_digest']:
        return 'request_mismatch'
    if r['origin_digest'] != c['expected_origin_digest'] or any(r[k] != c[k] for k in ('event_id', 'source_sequence')):
        return 'origin_mismatch'
    if r['source_session_id'] != c['source_session_id'] or any(
            r[k] != q['source_binding'][k] for k in ('capture_policy_id', 'capture_policy_revision')):
        return 'capture_mismatch'
    sent, received, now, expires = map(int, (
        p['sent_tick_ns'], c['received_tick_ns'], c['now_tick_ns'], p['expires_tick_ns']))
    if not sent <= received <= now or expires <= sent:
        return 'tick_order'
    if now >= expires:
        return 'expired'
    age_upper_ms = (now - sent + 999999) // 1000000
    if age_upper_ms > q['max_age_ms']:
        return 'stale'
    return 'fresh'


def main():
    schema, data = load('internal-trust.schema.json'), load('examples.json')
    assert data['purpose'] == 'synthetic-reference-no-authentication-no-network'
    Draft202012Validator.check_schema(schema)
    def validator(model):
        return Draft202012Validator({'$schema': schema['$schema'], '$defs': schema['$defs'],
                                     '$ref': '#/$defs/' + model})
    results = []
    ids = set()
    for c in data['schema_cases']:
        assert c['id'] not in ids
        ids.add(c['id'])
        actual = validator(c['model']).is_valid(modified(data['models'][c['model']], c['changes']))
        assert actual == c['valid'], c['id']
        results.append({'id': c['id'], 'schema_valid': actual, 'passed': True})
    for c in data['decision_cases']:
        assert c['id'] not in ids
        ids.add(c['id'])
        value = modified(data['bases'][c['kind']], c['changes'])
        if c['kind'] == 'read':
            validator('EvidenceReadGrant').validate(value['grant'])
            actual = read_decision(value)
        else:
            for name, model in [('challenge', 'SampleChallenge'), ('pending', 'PendingCapture'), ('receipt', 'CaptureReceipt')]:
                validator(model).validate(value[name])
            actual = capture_decision(value)
        assert actual == c['expect'], (c['id'], actual, c['expect'])
        results.append({'id': c['id'], 'decision': actual, 'passed': True})
    consumed = None
    for i, c in enumerate(data['consumption_sequence'], 1):
        binding = (c['request_digest'], c['result_digest'])
        actual = 'consumed' if consumed is None else 'existing' if binding == consumed else 'conflict'
        assert actual == c['expected']
        if consumed is None:
            consumed = binding
        results.append({'id': f'DP{i:02}', 'decision': actual, 'passed': True})
    report = {
        'purpose': 'DF06合成上下文参考；不是身份或真实来源证明',
        'all_passed': True, 'check_count': len(results),
        'schema_cases': len(data['schema_cases']), 'decision_cases': len(data['decision_cases']),
        'serial_consumption_cases': len(data['consumption_sequence']),
        'tool_versions': {'python': platform.python_version(), 'jsonschema': version('jsonschema')},
        'artifact_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in (
            'internal-trust.schema.json', 'examples.json', 'check_reference_cases.py')},
        'runtime_validation': {'tls': 0, 'authorization': 0, 'concurrent_consumption': 0,
                               'source_capture': 0, 'log_redaction': 0, 'services': 0},
        'jcs_digest_generation_executed': False,
        'checks': results,
    }
    (ROOT / 'reference-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: report[k] for k in ('all_passed', 'check_count', 'schema_cases', 'decision_cases', 'serial_consumption_cases')}))


if __name__ == '__main__':
    main()
