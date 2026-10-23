"""服务订阅候选资料的有限参考检查；不实现TLS、持久订阅或业务事件消费。"""
import argparse
import copy
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = [ROOT / name for name in ('README.md', 'service-subscription.schema.json',
                                  'cases.json', 'check_candidates.py')]
INPUTS += [REPO / 'docs/rebirth-c05-event-sync-design.md',
           REPO / 'docs/rebirth-df06-internal-trust-design.md']
MAX_COUNTER = 10**20 - 1


def unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('重复JSON键')
        out[key] = value
    return out


def load(raw):
    def invalid(value):
        raise ValueError('非法JSON常量：' + value)
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid)


def changed(base, changes):
    result = copy.deepcopy(base)
    for change in changes:
        current = result
        for segment in change['path'][:-1]:
            current = current[segment]
        key = change['path'][-1]
        if change.get('delete') is True:
            del current[key]
        else:
            current[key] = change['value']
    return result


def common(case):
    """这些可信前提来自人工夹具；不是远端可提交的API字段。"""
    peer, view = case['peer'], case['subscription']
    if peer['authority_available'] is not True:
        return 'unavailable'
    if peer['transport_authenticated'] is not True or peer['pairing_active'] is not True:
        return 'identity'
    if peer['purpose_allowed'] is not True or peer['authorization_current'] is not True:
        return 'authorization'
    if peer['owner'] != view['owner']:
        return 'owner'
    if view['purpose'] == 'canonical_trigger' and (
            peer['seamer_role'] is not True or peer['canonical_scope_complete'] is not True):
        return 'purpose'
    if view['state'] in ('resync_required', 'revoked', 'expired', 'closed'):
        return 'state'
    return None


def attach_decision(case):
    error = common(case)
    if error:
        return error
    view, request = case['subscription'], case['request']
    binding = view['binding']
    if request['owner'] != view['owner']:
        return 'owner'
    if any(request[key] != binding[key] for key in (
            'subscription_id', 'stream_id', 'stream_epoch', 'scope_digest', 'authorization_revision')):
        return 'binding'
    if request['expected_connection_generation'] != binding['connection_generation']:
        return 'generation'
    if int(binding['connection_generation']) == MAX_COUNTER:
        return 'generation_exhausted'
    if case['current_connection_open'] and not request['replace_existing']:
        return 'connection_busy'
    resume = request['resume']
    if resume is None:
        return 'snapshot_wait' if view['state'] in ('building', 'snapshot_ready') else 'snapshot_required'
    if view['state'] not in ('catching_up', 'live'):
        return 'state'
    if not case['consumer_state_preserved']:
        return 'projection_lost'
    if not case['retention_mapping_available']:
        return 'retention_lost'
    if view['purpose'] == 'canonical_trigger' and resume['ack_kind'] != 'durable_ingest':
        return 'ack_kind'
    if resume['cursor'] != view['ack_cursor'] or resume['payload_digest'] != view['ack_payload_digest']:
        return 'resume'
    return 'catching_up'


def ack_decision(case):
    error = common(case)
    if error:
        return error
    view, request = case['subscription'], case['request']
    if request['binding'] != view['binding']:
        return 'binding'
    if view['state'] not in ('catching_up', 'live'):
        return 'state'
    if view['purpose'] == 'canonical_trigger' and request['ack_kind'] != 'durable_ingest':
        return 'ack_kind'
    target = int(request['cursor'])
    if target > int(case['last_sent']):
        return 'unsent'
    previous = case['baseline_cursor']
    mapping = {previous: case['baseline_digest']}
    for entry in case['delivery_map']:
        cursor = entry['cursor']
        if int(cursor) > int(case['last_sent']):
            break
        if cursor in mapping or entry['previous_cursor'] != previous or int(cursor) <= int(previous):
            return 'chain'
        mapping[cursor] = entry['payload_digest']
        previous = cursor
    if previous != case['last_sent']:
        return 'chain'
    if mapping.get(view['ack_cursor']) != view['ack_payload_digest']:
        return 'chain'
    if request['cursor'] not in mapping:
        return 'retention_lost'
    if request['payload_digest'] != mapping[request['cursor']]:
        return 'digest'
    return 'duplicate' if target <= int(view['ack_cursor']) else 'advance'


def input_hashes(staged=False):
    output = {}
    for path in INPUTS:
        name = path.relative_to(REPO).as_posix()
        raw = subprocess.check_output(['git', 'show', ':' + name], cwd=REPO) if staged else path.read_bytes()
        output[name] = hashlib.sha256(raw).hexdigest()
    return output


def run():
    schema = load((ROOT / 'service-subscription.schema.json').read_bytes())
    Draft202012Validator.check_schema(schema)
    fixtures = load((ROOT / 'cases.json').read_bytes())
    assert fixtures['purpose'] == 'design_fixture_only' and fixtures['runtime_approved'] is False
    validators = {name: Draft202012Validator({**schema, 'oneOf': [{'$ref': '#/$defs/' + name}]})
                  for name in schema['$defs']}
    results = []
    for case in fixtures['structure_cases']:
        value = changed(fixtures['models'][case['model']], case['changes'])
        valid = validators[case['model']].is_valid(value)
        assert valid == case['expected_valid'], (case['id'], valid)
        results.append({'id': case['id'], 'category': 'structure', 'actual': valid, 'passed': True})
    for case in fixtures['decision_cases']:
        kind = case['kind']
        assert kind in ('attach', 'ack')
        value = changed(fixtures['fixtures'][kind], case['changes'])
        validators['SubscriptionView'].validate(value['subscription'])
        validators['ClientAttach' if kind == 'attach' else 'ClientAck'].validate(value['request'])
        if kind == 'ack':
            for field in ('last_sent', 'baseline_cursor'):
                validators['Counter'].validate(value[field])
            validators['Digest'].validate(value['baseline_digest'])
            for entry in value['delivery_map']:
                assert set(entry) == {'cursor', 'previous_cursor', 'payload_digest'}
                validators['Counter'].validate(entry['cursor'])
                validators['Counter'].validate(entry['previous_cursor'])
                validators['Digest'].validate(entry['payload_digest'])
        actual = attach_decision(value) if kind == 'attach' else ack_decision(value)
        assert actual == case['expected'], (case['id'], actual, case['expected'])
        results.append({'id': case['id'], 'category': kind, 'actual': actual, 'passed': True})
    assert len({item['id'] for item in results}) == len(results), '用例ID重复'
    return {'all_passed': True, 'runtime_approved': False,
            'scope': '局部结构及人工可信前提下的有限关联判定，不执行真实服务状态机',
            'structure_cases_passed': len(fixtures['structure_cases']),
            'decision_cases_passed': len(fixtures['decision_cases']),
            'runtime_tests_executed': 0, 'device_tests_executed': 0,
            'jcs_digests_computed': 0, 'python': platform.python_version(),
            'jsonschema': version('jsonschema'), 'results': results,
            'input_sha256': input_hashes()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--report', action='store_true')
    mode.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged仅用于--check-report')
    path = ROOT / 'reference-report.json'
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + path.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else path.read_bytes()
        report = load(raw)
        assert report['all_passed'] is True and report['runtime_approved'] is False
        assert report['input_sha256'] == input_hashes(args.staged), '报告输入发生变化'
        print(json.dumps({'bindings_matched': len(INPUTS), 'staged': args.staged, 'tests_rerun': False}))
        return
    report = run()
    if args.report:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ('results', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
