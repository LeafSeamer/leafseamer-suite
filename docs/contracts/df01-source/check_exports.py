"""对账完整SDK导出候选及引用图；不生成或运行产品SDK。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
FILES = ('public.schema.json', 'ipc.schema.json', 'http/controller.operations.json', 'http/seamer.operations.json')
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}
POLICY = {
    './seamer': ('seamer', 'browser_node', '''getMeta getClock getSession createRequestContext createSubscription getSnapshot
        createDefinition updateDraft publishDefinition createRun getRun preflightRun armRun pauseRun previewRecovery resumeRun
        revokeAuthorization issueWsTicket getRevocation getClockAssessment getCapacity getSubject setCapacity
        getRecoveryOperation getIndependenceProof openEvents'''.split()),
    './controller': ('controller', 'browser_node', '''getMeta getClock getSession createRequestContext createSubscription getSnapshot
        listDevices getCapabilities getDeviceState submitCommand getCommand cancelCommand getControlOperation getControl
        acquireControl releaseControl offerTransfer acceptTransfer revokeRunGrant bootstrap login refreshSession issueToken
        revokeAuthorization issueWsTicket getRevocation getClockAssessment getCapacity getSubject setCapacity
        getSceneCatalog getCommandEvidence openEvents'''.split()),
    './provider': ('seamer', 'node', ['updateCatalog', 'ingestEvent']),
    './seamer-controller': ('controller', 'node', ['updateRunGrant']),
    './internal/controller': ('controller', 'node', ['introspect', 'getClockDomainDescriptor', 'getTimeBoundEvidence', 'getTimeBoundProfile', 'getClockSample']),
    './internal/seamer': ('seamer', 'node', ['getClockDomainDescriptor', 'getTimeBoundEvidence', 'getTimeBoundProfile', 'getClockSample']),
}
INPUTS = ['EXPORTS.md', 'check_exports.py', 'exports-candidate.json', 'exports-cases.json',
          'semantic-trace-report.json'] + ['source/' + p for p in FILES]


def load(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non_json_number')))


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def token(value):
    return value.replace('~', '~0').replace('/', '~1')


def schema_refs(node):
    """只遍历Schema关键字；default/const/examples中的同名键属于数据。"""
    if isinstance(node, bool):
        return set()
    if not isinstance(node, dict):
        raise ValueError('invalid_schema_node')
    if any(key in node for key in ('$id', '$dynamicRef', '$recursiveRef', '$defs', 'definitions')):
        raise ValueError('unsupported_schema_scope')
    found = set()
    if '$ref' in node:
        if not isinstance(node['$ref'], str):
            raise ValueError('invalid_ref')
        found.add(node['$ref'])
    maps = {'properties', 'patternProperties', 'dependentSchemas'}
    lists = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}
    singles = {'items', 'additionalProperties', 'unevaluatedProperties', 'unevaluatedItems',
               'contains', 'propertyNames', 'not', 'if', 'then', 'else'}
    annotations = {'$comment', 'title', 'description', 'default', 'examples', 'deprecated', 'readOnly', 'writeOnly'}
    leaves = {'$ref', 'type', 'enum', 'const', 'required', 'dependentRequired', 'format', 'pattern',
              'minLength', 'maxLength', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
              'multipleOf', 'minItems', 'maxItems', 'uniqueItems', 'minContains', 'maxContains',
              'minProperties', 'maxProperties', 'contentEncoding', 'contentMediaType'}
    if set(node) - maps - lists - singles - annotations - leaves:
        raise ValueError('unsupported_schema_keyword')
    for key in maps & node.keys():
        for child in node[key].values():
            found |= schema_refs(child)
    for key in lists & node.keys():
        for child in node[key]:
            found |= schema_refs(child)
    for key in singles & node.keys():
        found |= schema_refs(node[key])
    return found


def model_key(ref, namespace, public_id):
    prefixes = [(public_id + '#/$defs/', 'public')]
    prefixes += [('#/components/schemas/', 'public')] if namespace == 'openapi' else [('#/$defs/', namespace)]
    for prefix, owner in prefixes:
        if ref.startswith(prefix) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', ref[len(prefix):]):
            return owner + '/' + ref[len(prefix):]
    raise ValueError('unknown_model_ref')


def local_component(api, node, bucket, seen=()):
    if '$ref' not in node:
        return node
    ref = node['$ref']
    prefix = '#/components/' + bucket + '/'
    if not isinstance(ref, str) or not ref.startswith(prefix) or '/' in ref[len(prefix):]:
        raise ValueError('unknown_component_ref')
    if ref in seen:
        raise ValueError('component_cycle')
    if set(node) - {'$ref', 'summary', 'description'}:
        raise ValueError('unsupported_reference_sibling')
    try:
        target = api['components'][bucket][ref[len(prefix):]]
    except KeyError as exc:
        raise ValueError('missing_component') from exc
    return local_component(api, target, bucket, (*seen, ref))


def content_roots(content):
    roots = set()
    for media in content.values():
        if 'encoding' in media:
            raise ValueError('unsupported_encoding')
        if 'schema' in media:
            roots |= schema_refs(media['schema'])
    return roots


def parameter_roots(param):
    if 'schema' in param and 'content' in param:
        raise ValueError('ambiguous_parameter')
    return schema_refs(param['schema']) if 'schema' in param else content_roots(param.get('content', {}))


def operation_roots(api, item, op):
    roots, params = set(), {}
    if 'callbacks' in op:
        raise ValueError('unsupported_callbacks')
    # Operation同name/in参数覆盖Path Item的声明，不取两者并集。
    for group in (item.get('parameters', []), op.get('parameters', [])):
        group_seen = set()
        for raw in group:
            param = local_component(api, raw, 'parameters')
            key = param['name'], param['in']
            if key in group_seen:
                raise ValueError('duplicate_parameter')
            group_seen.add(key)
            params[key] = param
    for param in params.values():
        roots |= parameter_roots(param)
    if 'requestBody' in op:
        body = local_component(api, op['requestBody'], 'requestBodies')
        roots |= content_roots(body.get('content', {}))
    for raw in op['responses'].values():
        response = local_component(api, raw, 'responses')
        roots |= content_roots(response.get('content', {}))
        for raw_header in response.get('headers', {}).values():
            roots |= parameter_roots(local_component(api, raw_header, 'headers'))
    ws = '101' in op['responses']
    extensions = ('x-ticket-binding-schema', 'x-websocket-frame-schema')
    if ws and not all(key in op for key in extensions):
        raise ValueError('missing_ws_model')
    if not ws and any(key in op for key in extensions):
        raise ValueError('unexpected_ws_model')
    for key in extensions:
        if key in op:
            if not isinstance(op[key], str):
                raise ValueError('invalid_ws_model')
            roots.add(op[key])
    return roots, ws


def inventory(files):
    public, ipc = files['public.schema.json'], files['ipc.schema.json']
    graph = {}
    for ns, schema in (('public', public), ('ipc', ipc)):
        for name, node in schema['$defs'].items():
            graph[ns + '/' + name] = {model_key(ref, ns, public['$id']) for ref in schema_refs(node)}
    if any(target not in graph for targets in graph.values() for target in targets):
        raise ValueError('missing_model')
    def closure(roots):
        found, pending = set(), list(roots)
        while pending:
            key = pending.pop()
            if key not in graph:
                raise ValueError('missing_model')
            if key not in found:
                found.add(key)
                pending.extend(graph[key] - found)
        return sorted(found)
    owners = {}
    for entry, (service, _, operations) in POLICY.items():
        for oid in operations:
            key = service + ':' + oid
            if key in owners:
                raise ValueError('duplicate_operation_policy')
            owners[key] = entry
    operations = {}
    entries = {entry: {'runtime': runtime, 'operations': [], 'roots': [], 'models': []}
               for entry, (_, runtime, _) in POLICY.items()}
    public_roots, internal_roots = set(), set()
    for service in ('controller', 'seamer'):
        api = files['http/' + service + '.operations.json']
        if 'webhooks' in api:
            raise ValueError('unsupported_webhooks')
        for path, item in api['paths'].items():
            if '$ref' in item:
                raise ValueError('unsupported_path_reference')
            for method, op in item.items():
                if method not in METHODS:
                    continue
                key = service + ':' + op['operationId']
                if key not in owners:
                    raise ValueError('unclassified_operation')
                if key in operations:
                    raise ValueError('duplicate_operation')
                entry = owners[key]
                roots, ws = operation_roots(api, item, op)
                models = {model_key(ref, 'openapi', public['$id']) for ref in roots}
                is_internal = entry.startswith('./internal/')
                if path.startswith('/internal/') != is_internal:
                    raise ValueError('internal_path_mismatch')
                effective_security = op.get('security', api.get('security'))
                if is_internal and effective_security != [{'serviceMtls': []}]:
                    raise ValueError('internal_security_mismatch')
                operations[key] = {'service': service, 'method': method, 'path': path,
                    'operation_id': op['operationId'], 'source_pointer': '/paths/' + token(path) + '/' + method,
                    'transport': 'websocket' if ws else 'http', 'entrypoint': entry,
                    'security_source': 'operation' if 'security' in op else 'root',
                    'effective_security': effective_security, 'permission': op.get('x-permission'),
                    'roots': sorted(models)}
                entries[entry]['operations'].append(key)
                entries[entry]['roots'].extend(models)
                (internal_roots if is_internal else public_roots).update(models)
    if set(operations) != set(owners):
        raise ValueError('missing_operation')
    ipc_roots = {model_key(ref, 'ipc', public['$id']) for ref in schema_refs({'oneOf': ipc['oneOf']})}
    entries['./ipc'] = {'runtime': 'node', 'operations': [], 'roots': sorted(ipc_roots), 'models': []}
    entries['./models'] = {'runtime': 'browser_node_types_only', 'operations': [], 'roots': sorted(public_roots), 'models': []}
    for entry in entries.values():
        entry['operations'] = sorted(entry['operations'])
        entry['roots'] = sorted(set(entry['roots']))
        entry['models'] = closure(entry['roots'])
    models = {}
    for key in sorted(graph):
        ns, name = key.split('/')
        used = sorted(entry for entry, spec in entries.items() if key in spec['models'])
        models[key] = {'source': ns + '.schema.json', 'pointer': '/$defs/' + name,
                       'export_name': ('Ipc' if ns == 'ipc' else '') + name,
                       'entrypoints': used, 'status': 'candidate_export' if used else 'retained_unexported'}
    for entry in entries.values():
        names = [models[key]['export_name'] for key in entry['models']]
        if len(names) != len(set(names)) or ('./ipc' in entries and 'IpcMessage' in names):
            raise ValueError('export_name_collision')
    return {'operations': dict(sorted(operations.items())), 'entrypoints': entries, 'models': models}, {
        'public_closure': closure(public_roots), 'internal_closure': closure(internal_roots),
        'ipc_public_closure': [key for key in closure(ipc_roots) if key.startswith('public/')],
        'ipc_local_closure': [key for key in closure(ipc_roots) if key.startswith('ipc/')],
        'retained_unexported': [key for key, value in models.items() if not value['entrypoints']]}


def candidate_errors(plan, expected, hashes):
    fields = {'format_version', 'approved', 'authority_switched', 'scope', 'source_sha256', 'operations', 'entrypoints', 'models'}
    if not isinstance(plan, dict) or set(plan) != fields:
        return {'plan_fields'}
    errors = set()
    if type(plan['approved']) is not bool or type(plan['authority_switched']) is not bool or (plan['format_version'], plan['approved'], plan['authority_switched'], plan['scope']) != (
            'sdk-exports/0.1.0-draft.1', False, False, 'draft4_design_candidate'):
        errors.add('plan_status')
    if plan['source_sha256'] != hashes:
        errors.add('source_binding')
    for field in ('operations', 'entrypoints', 'models'):
        if plan[field] != expected[field]:
            errors.add(field + '_mismatch')
    return errors


def bindings(staged=False):
    result = {}
    for name in INPUTS:
        path = ROOT / name
        key = path.relative_to(REPO).as_posix()
        raw = subprocess.check_output(['git', 'show', ':' + key], cwd=REPO) if staged else path.read_bytes()
        result[key] = hashlib.sha256(raw).hexdigest()
    return result


def run():
    raw = {name: (ROOT / 'source' / name).read_bytes() for name in FILES}
    files = {name: load(value) for name, value in raw.items()}
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    expected, graph = inventory(files)
    plan = load((ROOT / 'exports-candidate.json').read_bytes())
    assert not candidate_errors(plan, expected, hashes), '完整候选与源不符'
    previous = load((ROOT / 'semantic-trace-report.json').read_bytes())['exposure']
    for new, old in [('public_closure', 'public_closure'), ('internal_closure', 'internal_closure'),
                     ('ipc_public_closure', 'ipc_external_closure')]:
        assert graph[new] == ['public/' + name for name in previous[old]], (new, '历史独立图不一致')
    assert graph['retained_unexported'] == ['public/AuthorizationSnapshotResponse', 'public/RunGrant']
    cases = load((ROOT / 'exports-cases.json').read_bytes())
    observed, ids = [], set()
    for case in cases['mutations']:
        assert case['id'] not in ids
        ids.add(case['id'])
        value = copy.deepcopy(plan)
        for path, replacement in case['set']:
            target = value
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = replacement
        errors = candidate_errors(value, expected, hashes)
        assert errors == set(case['expected_errors']), (case['id'], errors)
        observed.append({'id': case['id'], 'errors': sorted(errors)})
    for case in cases['schema_probes']:
        assert case['id'] not in ids
        ids.add(case['id'])
        error, refs = None, None
        try:
            refs = sorted(schema_refs(case['schema']))
        except ValueError as exc:
            error = str(exc)
        assert error == case['error'] and refs == case['refs'], case['id']
        observed.append({'id': case['id'], 'error': error, 'refs': refs})
    for case in cases['operation_probes']:
        assert case['id'] not in ids
        ids.add(case['id'])
        error, actual = None, None
        try:
            roots, ws = operation_roots(case['api'], case['item'], case['operation'])
            actual = {'refs': sorted(roots), 'websocket': ws}
        except ValueError as exc:
            error = str(exc)
        assert error == case['error'] and actual == case['expected'], (case['id'], error, actual)
        observed.append({'id': case['id'], 'error': error, 'actual': actual})
    return {'all_passed': True, 'scope': '完整导出清单静态对账与引用图参考检查',
            'counts': {'operations': len(plan['operations']), 'entrypoints': len(plan['entrypoints']),
                       'public_models': len(files['public.schema.json']['$defs']), 'ipc_models': len(files['ipc.schema.json']['$defs']),
                       'mutations': len(cases['mutations']), 'schema_probes': len(cases['schema_probes']),
                       'operation_probes': len(cases['operation_probes'])},
            'graph_observation': graph, 'entrypoint_counts': {key: {'operations': len(v['operations']),
                 'roots': len(v['roots']), 'models': len(v['models'])} for key, v in plan['entrypoints'].items()},
            'cases': observed, 'sdk_builds_executed': 0, 'browser_import_tests_executed': 0,
            'authorization_tests_executed': 0, 'input_sha256': bindings()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--report', action='store_true')
    group.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged仅配合--check-report')
    report_path = ROOT / 'exports-report.json'
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + report_path.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else report_path.read_bytes()
        assert load(raw)['input_sha256'] == bindings(args.staged), '报告绑定不一致'
        print(json.dumps({'bindings_matched': len(INPUTS), 'tests_rerun': False, 'staged': args.staged}))
        return
    report = run()
    if args.report:
        report_path.write_bytes(encode(report))
    print(json.dumps({k: v for k, v in report.items() if k not in ('graph_observation', 'cases', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
