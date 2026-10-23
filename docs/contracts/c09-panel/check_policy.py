"""核对面板操作策略候选；仅检查元数据，不实现面板代理或真实授权。"""
import argparse
from collections import Counter
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
SOURCE_NAMES = ['docs/contracts/df01-source/authorization-candidate.json',
                'docs/contracts/df01-source/source/http/controller.operations.json',
                'docs/contracts/df01-source/source/http/seamer.operations.json']
INPUTS = [ROOT / name for name in ('README.md', 'operation-policy.json', 'policy.schema.json',
                                  'cases.json', 'check_policy.py')]
INPUTS += [REPO / 'docs/rebirth-c09-extension-design.md'] + [REPO / name for name in SOURCE_NAMES]
EXPOSED = {'panel_read', 'panel_write', 'host_confirm'}
# 以下是独立审阅预期，不是未来生产实现的第二套策略源。
CONFIRM = {'controller:acceptTransfer', 'controller:acquireControl', 'controller:offerTransfer',
           'controller:releaseControl', 'controller:revokeRunGrant', 'seamer:armRun',
           'seamer:publishDefinition', 'seamer:resumeRun'}
WRITE = {'controller:submitCommand', 'controller:cancelCommand', 'seamer:createDefinition',
         'seamer:createRun', 'seamer:pauseRun', 'seamer:updateDraft'}
TRANSPORT = {service + ':' + name for service in ('controller', 'seamer') for name in (
    'createRequestContext', 'createSubscription', 'getSnapshot', 'issueWsTicket', 'openEvents')}
ACCOUNT = {'controller:' + name for name in ('getRevocation', 'getSession', 'getSubject',
                                           'issueToken', 'login', 'refreshSession')}
ACCOUNT |= {'seamer:' + name for name in ('getRevocation', 'getSession', 'getSubject')}
COUNTS = {'panel_read': 21, 'panel_write': 6, 'host_confirm': 8, 'host_transport': 10,
          'host_account': 9, 'unavailable': 17}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('重复键')
        result[key] = value
    return result


def load(raw):
    def invalid(value):
        raise ValueError('非法JSON常量：' + value)
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid)


def source_operations():
    operations = {}
    for service, name in zip(('controller', 'seamer'), SOURCE_NAMES[1:]):
        source = load((REPO / name).read_bytes())
        for path, item in source['paths'].items():
            for method, operation in item.items():
                if method not in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'):
                    continue
                key = service + ':' + operation['operationId']
                assert key not in operations, '来源operationId重复'
                encoded = path.replace('~', '~0').replace('/', '~1')
                operations[key] = {'method': method, 'permission': operation.get('x-permission'),
                                   'source_pointer': '/paths/' + encoded + '/' + method,
                                   'security': operation.get('security', source.get('security', []))}
    return operations


def policy_errors(policy, validator, source, authorization, hashes):
    if not validator.is_valid(policy):
        return {'structure'}
    errors = set()
    if policy['source_sha256'] != hashes:
        errors.add('source_hash')
    rows = policy['operations']
    if rows.keys() != source.keys():
        errors.add('coverage')
    if Counter(row['mode'] for row in rows.values()) != COUNTS:
        errors.add('mode_coverage')
    methods = [row['method_name'] for row in rows.values() if row['method_name'] is not None]
    if len(methods) != len(set(methods)):
        errors.add('duplicate_method')
    for key in rows.keys() & source.keys():
        row, original = rows[key], source[key]
        mode = row['mode']
        if any(row[field] != original[field] for field in ('permission', 'source_pointer')):
            errors.add('source_mapping')
        expected_name = key.replace(':', '.') if mode in EXPOSED else None
        if row['method_name'] != expected_name:
            errors.add('method_mapping')
        for required, expected_mode in ((CONFIRM, 'host_confirm'), (WRITE, 'panel_write'),
                                        (TRANSPORT, 'host_transport'), (ACCOUNT, 'host_account')):
            if (key in required) != (mode == expected_mode):
                errors.add('reserved_mode')
        if mode not in EXPOSED:
            continue
        branches = authorization[key]['branches']
        if not any(branch['profile'] == 'human' for branch in branches):
            errors.add('human_branch')
        if any('serviceMtls' in requirement for requirement in original['security']):
            errors.add('internal_exposure')
        permission = original['permission'] or ''
        if permission.startswith(('auth.', 'identity.', 'session.', 'clock.internal.', 'provider.')):
            errors.add('reserved_permission')
        if permission in ('grant.manage', 'capacity.manage'):
            errors.add('reserved_permission')
        if mode == 'panel_read' and original['method'] != 'get' and key not in (
                'seamer:preflightRun', 'seamer:previewRecovery'):
            errors.add('read_effect')
        if key == 'controller:submitCommand' and not any(
                branch['profile'] == 'human' and branch['origin'] == 'manual' for branch in branches):
            errors.add('manual_branch')
    return errors


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


def input_hashes(staged=False):
    hashes = {}
    for path in INPUTS:
        name = path.relative_to(REPO).as_posix()
        raw = subprocess.check_output(['git', 'show', ':' + name], cwd=REPO) if staged else path.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
    return hashes


def run():
    schema = load((ROOT / 'policy.schema.json').read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    policy = load((ROOT / 'operation-policy.json').read_bytes())
    cases = load((ROOT / 'cases.json').read_bytes())
    assert cases['purpose'] == 'design_fixture_only' and cases['runtime_approved'] is False
    source = source_operations()
    authorization = load((REPO / SOURCE_NAMES[0]).read_bytes())['operations']
    assert source.keys() == authorization.keys()
    for key in source:
        assert all(source[key][field] == authorization[key][field]
                   for field in ('permission', 'source_pointer')), ('授权元数据来源漂移', key)
    hashes = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in SOURCE_NAMES}
    assert not policy_errors(policy, validator, source, authorization, hashes)
    results = []
    for case in cases['cases']:
        errors = policy_errors(changed(policy, case['changes']), validator, source, authorization, hashes)
        assert (not errors) == case['expected_valid'], (case['id'], sorted(errors))
        results.append({'id': case['id'], 'errors': sorted(errors), 'passed': True})
    assert len({result['id'] for result in results}) == len(results)
    return {'all_passed': True, 'approved': False, 'runtime_approved': False,
            'scope': '现有71操作的面板策略元数据，非完整面板RPC或生产授权',
            'operations_checked': len(source), 'mode_counts': dict(Counter(row['mode'] for row in policy['operations'].values())),
            'metadata_cases_passed': len(results), 'browser_tests_executed': 0,
            'runtime_authorization_tests_executed': 0, 'device_tests_executed': 0,
            'python': platform.python_version(), 'jsonschema': version('jsonschema'),
            'results': results, 'input_sha256': input_hashes()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--report', action='store_true')
    mode.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged仅配合--check-report')
    path = ROOT / 'reference-report.json'
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + path.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else path.read_bytes()
        report = load(raw)
        assert report['all_passed'] is True and report['runtime_approved'] is False and report['approved'] is False
        assert report['input_sha256'] == input_hashes(args.staged), '报告输入已变化'
        print(json.dumps({'bindings_matched': len(INPUTS), 'staged': args.staged, 'tests_rerun': False}))
        return
    report = run()
    if args.report:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ('results', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
