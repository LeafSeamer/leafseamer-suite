"""只核验待审阅授权元数据；不验证真实身份，不提供生产鉴权函数。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
SOURCES = ['source/public.schema.json', 'source/http/controller.operations.json',
           'source/http/seamer.operations.json', 'exports-candidate.json']
INPUTS = ['AUTHORIZATION.md', 'authorization.schema.json', 'authorization-candidate.json',
          'authorization-cases.json', 'check_authorization.py'] + SOURCES
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}
SECURITY = {'human': [{'bearerAuth': []}], 'service': [{'bearerAuth': []}],
            'seamer': [{'bearerAuth': []}], 'provider': [{'bearerAuth': []}],
            'internal': [{'serviceMtls': []}], 'cookie': [{'sessionCookie': [], 'csrfHeader': []}],
            'ticket': [{'wsTicketHeader': []}], 'bootstrap': [], 'login': []}
# 以下为依据审阅文稿独立写出的最低策略约束，不作为生产第二套授权源。
HUMAN_ONLY = {'getSession', 'createSubscription', 'getSnapshot', 'issueWsTicket',
              'revokeAuthorization', 'setCapacity', 'acquireControl', 'releaseControl',
              'offerTransfer', 'acceptTransfer', 'publishDefinition', 'armRun', 'resumeRun'}
SPECIAL = {'submitCommand': {('human', 'manual'), ('seamer', 'automation')},
           'updateRunGrant': {('seamer', None)}, 'revokeRunGrant': {('human', None), ('seamer', None)},
           'updateCatalog': {('provider', None)}, 'ingestEvent': {('provider', None)},
           'bootstrap': {('bootstrap', None)}, 'login': {('login', None)},
           'refreshSession': {('cookie', None)}, 'issueToken': {('cookie', None)},
           'openEvents': {('ticket', None)}}
MINIMUM_GUARDS = {
    'getMeta': {'public_projection'}, 'getClock': {'public_projection'},
    'getClockAssessment': {'public_projection'}, 'getCapacity': {'public_projection'},
    'getSession': {'own_session'}, 'createRequestContext': {'context_intersection'},
    'createSubscription': {'subscription_owner'}, 'getSnapshot': {'subscription_owner'},
    'issueWsTicket': {'ticket_issue'}, 'openEvents': {'subscription_owner', 'ticket_binding'},
    'listDevices': {'device_scope'}, 'getCapabilities': {'device_scope'},
    'getDeviceState': {'device_scope'}, 'getSceneCatalog': {'device_scope'},
    'getCommand': {'command_scope'}, 'getCommandEvidence': {'command_scope'},
    'getControl': {'control_scope'}, 'getControlOperation': {'control_scope'},
    'cancelCommand': {'cancel_target'}, 'acquireControl': {'acquire_target'},
    'releaseControl': {'release_target'}, 'offerTransfer': {'offer_target'},
    'acceptTransfer': {'accept_target'}, 'updateRunGrant': {'grant_proposal'},
    'revokeRunGrant': {'grant_revoke_target'}, 'bootstrap': {'bootstrap_once'},
    'login': {'login_proof'}, 'refreshSession': {'cookie_binding', 'refresh_rotation'},
    'issueToken': {'cookie_binding', 'token_intersection'}, 'introspect': {'introspection_audience'},
    'revokeAuthorization': {'revocation_target', 'recent_auth'},
    'getRevocation': {'revocation_visibility'}, 'getSubject': {'subject_visibility'},
    'setCapacity': {'capacity_profile', 'recent_auth'}, 'updateCatalog': {'provider_catalog'},
    'ingestEvent': {'provider_event'}, 'createDefinition': {'definition_edit'},
    'updateDraft': {'definition_edit'}, 'publishDefinition': {'definition_publish'},
    'createRun': {'run_create_unarmed'}, 'getRun': {'run_read'},
    'preflightRun': {'run_read', 'preflight_readonly'},
    'previewRecovery': {'run_read', 'recovery_readonly'}, 'armRun': {'arm_approval'},
    'pauseRun': {'pause_target'}, 'resumeRun': {'recovery_confirm'},
    'getRecoveryOperation': {'recovery_visibility'}, 'getIndependenceProof': {'proof_visibility'},
    'getClockDomainDescriptor': {'internal_object'}, 'getTimeBoundEvidence': {'internal_object'},
    'getTimeBoundProfile': {'internal_object'}, 'getClockSample': {'internal_object'}}


def load(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('重复JSON键')
            result[key] = value
        return result
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非法JSON数值')))


def source_operations():
    out = {}
    for service in ('controller', 'seamer'):
        api = load((ROOT / 'source/http' / (service + '.operations.json')).read_bytes())
        for path, item in api['paths'].items():
            for method, op in item.items():
                if method not in METHODS:
                    continue
                key = service + ':' + op['operationId']
                if key in out:
                    raise ValueError('重复源操作')
                out[key] = {'source_pointer': '/paths/' + path.replace('~', '~0').replace('/', '~1') + '/' + method,
                            'permission': op.get('x-permission'), 'security': op.get('security', api.get('security')),
                            'internal': path.startswith('/internal/')}
    previous = load((ROOT / 'exports-candidate.json').read_bytes())['operations']
    if set(previous) != set(out):
        raise ValueError('导出清单与HTTP源操作集合不符')
    for key, value in out.items():
        if any(value[field] != previous[key][field] for field in ('source_pointer', 'permission')):
            raise ValueError('导出清单与HTTP源定位或权限不符')
        if value['security'] != previous[key]['effective_security']:
            raise ValueError('导出清单认证不符')
    return out


def policy_errors(value, validator, source, hashes):
    if not validator.is_valid(value):
        return {'schema'}
    errors = set()
    if value['source_sha256'] != hashes:
        errors.add('source_binding')
    if set(value['operations']) != set(source):
        errors.add('operation_coverage')
    used = set()
    for key in value['operations'].keys() & source.keys():
        row, observed = value['operations'][key], source[key]
        name = key.split(':')[1]
        if any(row[f] != observed[f] for f in ('source_pointer', 'permission')):
            errors.add('source_metadata')
        actual = [(b['profile'], b['origin']) for b in row['branches']]
        if len(actual) != len(set(actual)):
            errors.add('duplicate_branch')
        expected = {('internal', None)} if observed['internal'] else SPECIAL.get(name)
        if expected is None:
            expected = {('human', None)} if name in HUMAN_ONLY else {('human', None), ('service', None)}
        if set(actual) != expected:
            errors.add('principal_policy')
        for branch in row['branches']:
            if SECURITY[branch['profile']] != observed['security']:
                errors.add('transport_policy')
            minimum = MINIMUM_GUARDS.get(name)
            if name == 'submitCommand':
                minimum = {'manual_holder'} if branch['origin'] == 'manual' else {'automation_grant'}
            if minimum is None:
                errors.add('unreviewed_operation')
            elif not minimum <= set(branch['guards']):
                errors.add('missing_guard')
            used.update(branch['guards'])
    if used != set(value['guard_registry']):
        errors.add('guard_coverage')
    return errors


def input_hashes(staged=False):
    result = {}
    for name in INPUTS:
        key = (ROOT / name).relative_to(REPO).as_posix()
        raw = subprocess.check_output(['git', 'show', ':' + key], cwd=REPO) if staged else (ROOT / name).read_bytes()
        result[key] = hashlib.sha256(raw).hexdigest()
    return result


def run():
    schema = load((ROOT / 'authorization.schema.json').read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    value = load((ROOT / 'authorization-candidate.json').read_bytes())
    source = source_operations()
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in SOURCES}
    assert not policy_errors(value, validator, source, hashes), '完整候选不符'
    cases = load((ROOT / 'authorization-cases.json').read_bytes())['cases']
    results, ids = [], set()
    for case in cases:
        assert case['id'] not in ids
        ids.add(case['id'])
        modified = copy.deepcopy(value)
        for change in case['changes']:
            target = modified
            for segment in change['path'][:-1]:
                target = target[segment]
            key = change['path'][-1]
            if change['action'] == 'delete':
                del target[key]
            elif change['action'] == 'set':
                target[key] = change['value']
            else:
                raise ValueError('未知变异操作')
        errors = policy_errors(modified, validator, source, hashes)
        assert errors == set(case['expected_errors']), (case['id'], errors)
        results.append({'id': case['id'], 'errors': sorted(errors), 'passed': True})
    return {'all_passed': True, 'scope': '逐操作授权元数据与源对账，不执行真实鉴权',
            'operation_count': len(source), 'branch_count': sum(len(x['branches']) for x in value['operations'].values()),
            'guard_count': len(value['guard_registry']), 'metadata_cases_passed': len(results),
            'runtime_authorization_tests_executed': 0, 'device_tests_executed': 0,
            'approved': False, 'results': results, 'input_sha256': input_hashes()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--report', action='store_true')
    mode.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged仅配合--check-report')
    path = ROOT / 'authorization-report.json'
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + path.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else path.read_bytes()
        report = load(raw)
        assert report['all_passed'] is True and report['approved'] is False
        assert report['input_sha256'] == input_hashes(args.staged), '报告输入已变化'
        print(json.dumps({'bindings_matched': len(INPUTS), 'tests_rerun': False, 'staged': args.staged}))
        return
    report = run()
    if args.report:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('results', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
