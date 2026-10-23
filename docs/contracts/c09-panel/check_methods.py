"""离线核验面板方法输入及HTTP字段归属；不运行代理、鉴权或结果投影。"""
import argparse
import copy
import hashlib
import json
from importlib.metadata import version
from pathlib import Path
import subprocess
from urllib.parse import urljoin

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
SOURCE = REPO / 'docs/contracts/df01-source/source'
INPUTS = [ROOT / n for n in ('METHODS.md', 'method-input.schema.json', 'method-bindings.json',
                            'method-cases.json', 'check_methods.py', 'operation-policy.json')]
INPUTS += [SOURCE / 'public.schema.json', SOURCE / 'http/controller.operations.json',
           SOURCE / 'http/seamer.operations.json']
EXTERNAL = '../df01-source/source/public.schema.json#/$defs/'
HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}


def load(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ValueError('重复JSON键')
            out[key] = value
        return out
    def invalid(value): raise ValueError('非法JSON常量：' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def externalize(value):
    if isinstance(value, dict):
        return {k: (EXTERNAL + v.rsplit('/', 1)[-1] if k == '$ref' else externalize(v))
                for k, v in value.items()}
    if isinstance(value, list): return [externalize(v) for v in value]
    return value


def source_operations():
    result = {}
    for service in ('controller', 'seamer'):
        source = load((SOURCE / f'http/{service}.operations.json').read_bytes())
        for path, item in source['paths'].items():
            for method, op in item.items():
                if method not in HTTP_METHODS: continue
                parameters = {(p['in'], p['name']): p for p in item.get('parameters', [])}
                parameters.update({(p['in'], p['name']): p for p in op.get('parameters', [])})
                body = op.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
                result[service + ':' + op['operationId']] = (parameters, body)
    return result


def metadata_errors(binding, schema, policy, public, source):
    errors = set()
    if set(binding) != {'format_version', 'approved', 'runtime_approved', 'authority_switched', 'methods'}:
        return {'metadata_shape'}
    if binding['format_version'] != 'panel-method-inputs/0.1.0-draft.1': errors.add('version')
    if any(binding[k] is not False for k in ('approved', 'runtime_approved', 'authority_switched')):
        errors.add('approval')
    expected = {v['method_name']: (k, v) for k, v in policy['operations'].items() if v['method_name']}
    if set(binding['methods']) != set(expected): errors.add('method_coverage')
    if len(expected) != 35: errors.add('source_scope')
    seen_models = set()
    for method, row in binding['methods'].items():
        if method not in expected: continue
        key, p = expected[method]
        if set(row) != {'operation_key', 'mode', 'input_definition', 'request_model', 'source_fields',
                       'result_view', 'raw_response_allowed'}:
            errors.add('row_shape'); continue
        if row['operation_key'] != key or row['mode'] != p['mode']: errors.add('policy')
        if row['raw_response_allowed'] is not False: errors.add('raw_response')
        if row['result_view'] != VIEW_BY_OPERATION.get(key.split(':', 1)[1]): errors.add('result_view')
        model = row['input_definition']
        if model != key.replace(':', '_') or model in seen_models: errors.add('model_identity')
        seen_models.add(model)
        arg = schema['$defs'].get(model)
        if arg is None: errors.add('input_missing'); continue
        parameters, body = source[key]
        body_name = body['$ref'].rsplit('/', 1)[-1] if body else None
        if row['request_model'] != body_name: errors.add('request_model')
        fields, props, required = {}, {}, []
        for (location, name), parameter in parameters.items():
            if location == 'path':
                fields[location + '.' + name] = 'panel_bound'
                props[name] = externalize(parameter['schema'])
                if parameter.get('required'): required.append(name)
            elif location == 'query' and name == 'cursor':
                fields['query.cursor'] = 'host_page_binding'
                props['page_handle'] = {'$ref': EXTERNAL + 'Id'}
            else:
                errors.add('unreviewed_parameter')
        op = key.split(':', 1)[1]
        if body_name:
            body_schema = public['$defs'][body_name]
            for name, shape in body_schema['properties'].items():
                mode = 'panel'
                if name in ('context_id', 'idempotency_key'): mode = 'host_identity'
                if op == 'submitCommand':
                    mode = {'origin': 'fixed_manual', 'run_binding': 'forbidden',
                            'correlation_id': 'host_correlation'}.get(name, mode)
                if op == 'armRun':
                    mode = {'preflight_id': 'host_assessment_binding',
                            'approval_id': 'host_approval_binding'}.get(name, mode)
                if op == 'resumeRun' and name in ('preview_id', 'preview_digest'): mode = 'host_recovery_binding'
                fields['body.' + name] = mode
                if mode == 'panel':
                    props[name] = externalize(shape)
                    if name in body_schema['required']: required.append(name)
        for operation, handle in (('armRun', 'assessment_handle'), ('resumeRun', 'recovery_handle')):
            if op == operation:
                props[handle] = {'$ref': EXTERNAL + 'Id'}; required.append(handle)
        if row['source_fields'] != fields: errors.add('field_ownership')
        if arg.get('properties') != props or set(arg.get('required', [])) != set(required):
            errors.add('input_fields')
        if arg.get('type') != 'object' or arg.get('additionalProperties') is not False:
            errors.add('input_open')
        # 条件语义的实际正反例另验；此处拒绝偷偷移除整个约束或添加宽分支。
        allowed = {'type', 'properties', 'required', 'additionalProperties'}
        if op == 'submitCommand': allowed.add('allOf')
        if set(arg) != allowed: errors.add('input_shape')
    if set(schema['$defs']) != seen_models: errors.add('model_coverage')
    expected_roots = [{'type': 'object', 'properties': {'method': {'const': m},
                       'arguments': {'$ref': '#/$defs/' + r['input_definition']}},
                       'required': ['method', 'arguments'], 'additionalProperties': False}
                      for m, r in binding['methods'].items()]
    if schema.get('oneOf') != expected_roots: errors.add('dispatch_union')
    return errors


# 独立审阅的21个结果名；具体白名单在METHODS，不代表投影器已执行。
VIEWS = {'MetaView', 'ClockView', 'ClockAssessmentView', 'DevicePageView', 'CapabilityView',
         'ObservationView', 'CommandView', 'CancelView', 'ControlOperationView', 'ControlView',
         'TransferView', 'MutationView', 'CapacityView', 'SceneCatalogView', 'EvidencePageView',
         'DefinitionView', 'RunView', 'PreflightView', 'RecoveryPlanView', 'RecoveryOperationView',
         'IndependenceView'}
VIEW_BY_OPERATION = {operation: view for view, operations in {
    'MetaView': ['getMeta'], 'ClockView': ['getClock'], 'ClockAssessmentView': ['getClockAssessment'],
    'DevicePageView': ['listDevices'], 'CapabilityView': ['getCapabilities'],
    'ObservationView': ['getDeviceState'], 'CommandView': ['submitCommand', 'getCommand'],
    'CancelView': ['cancelCommand'], 'ControlOperationView': ['getControlOperation', 'acquireControl', 'releaseControl', 'acceptTransfer'],
    'ControlView': ['getControl'], 'TransferView': ['offerTransfer'],
    'MutationView': ['revokeRunGrant', 'armRun', 'pauseRun'], 'CapacityView': ['getCapacity'],
    'SceneCatalogView': ['getSceneCatalog'], 'EvidencePageView': ['getCommandEvidence'],
    'DefinitionView': ['createDefinition', 'updateDraft', 'publishDefinition'],
    'RunView': ['createRun', 'getRun'], 'PreflightView': ['preflightRun'],
    'RecoveryPlanView': ['previewRecovery'], 'RecoveryOperationView': ['resumeRun', 'getRecoveryOperation'],
    'IndependenceView': ['getIndependenceProof']}.items() for operation in operations}


def mutate(value, changes):
    for change in changes:
        current = value
        for part in change['path'][:-1]: current = current[part]
        if change.get('delete'): del current[change['path'][-1]]
        else: current[change['path'][-1]] = copy.deepcopy(change['value'])


def hashes(staged=False):
    return {p.relative_to(REPO).as_posix(): hashlib.sha256(
        subprocess.check_output(['git', 'show', ':' + p.relative_to(REPO).as_posix()], cwd=REPO)
        if staged else p.read_bytes()).hexdigest() for p in INPUTS}


def run():
    schema = load((ROOT / 'method-input.schema.json').read_bytes())
    binding = load((ROOT / 'method-bindings.json').read_bytes())
    cases = load((ROOT / 'method-cases.json').read_bytes())
    policy = load((ROOT / 'operation-policy.json').read_bytes())
    public = load((SOURCE / 'public.schema.json').read_bytes())
    Draft202012Validator.check_schema(schema)
    # 注册精确本地资源；默认Registry没有网络retriever。
    registry = Registry().with_resources([(public['$id'], Resource.from_contents(public)),
        (urljoin(schema['$id'], EXTERNAL.split('#')[0]), Resource.from_contents(public))])
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    source = source_operations()
    assert not metadata_errors(binding, schema, policy, public, source)
    assert cases['purpose'] == 'design_fixture_only' and cases['runtime_approved'] is False
    assert set(cases['fixtures']) == set(binding['methods']), '35个手写方法正例必须齐全'
    results = []
    for method, arguments in cases['fixtures'].items():
        errors = list(validator.iter_errors({'method': method, 'arguments': arguments}))
        assert not errors, (method, [e.message for e in errors])
        results.append({'id': method, 'passed': True, 'kind': 'positive_structure'})
    for case in cases['structure_cases']:
        packet = {'method': case['method'], 'arguments': copy.deepcopy(cases['fixtures'][case['method']])}
        mutate(packet, case['changes'])
        valid = validator.is_valid(packet)
        assert valid == case['valid'], case['id']
        results.append({'id': case['id'], 'passed': True, 'kind': 'structure', 'valid': valid})
    for case in cases['metadata_cases']:
        packet = {'bindings': copy.deepcopy(binding), 'schema': copy.deepcopy(schema)}
        mutate(packet, case['changes'])
        errors = metadata_errors(packet['bindings'], packet['schema'], policy, public, source)
        assert case['expected_error'] in errors, (case['id'], errors)
        results.append({'id': case['id'], 'passed': True, 'kind': 'metadata', 'errors': sorted(errors)})
    assert len({r['id'] for r in results}) == len(results)
    return dict(all_passed=True, approved=False, runtime_approved=False,
                scope='35个具名输入结构与HTTP字段归属；不验证结果投影或权威绑定',
                methods=len(binding['methods']), views_declared=len(VIEWS), cases_passed=len(results),
                source_fields=sum(len(r['source_fields']) for r in binding['methods'].values()),
                browser_tests_executed=0, database_tests_executed=0, device_tests_executed=0,
                result_projection_tests_executed=0, authority_binding_tests_executed=0,
                tools={n: version(n) for n in ('jsonschema', 'referencing')},
                results=results, input_sha256=hashes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--report', action='store_true')
    group.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report: parser.error('--staged仅配合--check-report')
    target = ROOT / 'method-report.json'
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + target.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else target.read_bytes()
        report = load(raw)
        assert report['all_passed'] is True and report['approved'] is False and report['runtime_approved'] is False
        assert report['input_sha256'] == hashes(args.staged), '报告输入已变化'
        print(json.dumps(dict(bindings_matched=len(INPUTS), staged=args.staged, tests_rerun=False))); return
    report = run()
    if args.report: target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('results', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__': main()
