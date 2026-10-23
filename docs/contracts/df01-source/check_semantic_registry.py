"""只校验语义注册设计元数据和结果形状；不执行产品语义规则。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = ['SEMANTIC_REGISTRY.md', 'semantic-registry.schema.json',
          'semantic-registry-cases.json', 'check_semantic_registry.py',
          'source/public.schema.json']
REPORT = ROOT / 'semantic-registry-report.json'
MODEL = re.compile(r'#/\$defs/[A-Za-z][A-Za-z0-9_]{0,95}')


def strict_loads(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('重复JSON键')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非法JSON数值')))


def pointer_token(value):
    return value.replace('~', '~0').replace('/', '~1')


class SelectionError(ValueError):
    pass


def model_node(source, model):
    if not MODEL.fullmatch(model) or model[8:] not in source['$defs']:
        raise SelectionError('model_ref')
    return source['$defs'][model[8:]]


def boundary(root, pointer, pattern):
    # 实例边界与Schema位置同时检查，阻止allOf/then覆盖绕过Payload。
    if pointer == '#/$defs/Payload':
        return 'dynamic_payload'
    if pointer == '#/$defs/SchemaDescriptor/properties/document':
        return 'schema_document'
    if root == '#/$defs/CommandRequest' and pattern == [{'property': 'parameters'}]:
        return 'dynamic_payload'
    if root == '#/$defs/SchemaDescriptor' and pattern == [{'property': 'document'}]:
        return 'schema_document'
    return None


def select(source, root, steps, kind):
    node = model_node(source, root)
    pointer, pattern, guards = root, [], []
    for step in steps:
        if boundary(root, pointer, pattern):
            raise SelectionError('opaque_boundary')
        op = step['kind']
        if not isinstance(node, dict):
            raise SelectionError('selector_node')
        if op == 'property':
            name = step['name']
            if name not in node.get('properties', {}):
                raise SelectionError('selector_property')
            node = node['properties'][name]
            pointer += '/properties/' + pointer_token(name)
            pattern.append({'property': name})
        elif op == 'items':
            if node.get('type') != 'array' or not isinstance(node.get('items'), (dict, bool)):
                raise SelectionError('selector_items')
            node = node['items']
            pointer += '/items'
            pattern.append({'items': True})
        elif op == 'ref':
            target = node.get('$ref')
            if not isinstance(target, str) or not MODEL.fullmatch(target):
                raise SelectionError('selector_ref')
            node = model_node(source, target)
            pointer = target
        elif op == 'branch':
            keyword, index = step['keyword'], step['index']
            branches = node.get(keyword)
            if not isinstance(branches, list) or index >= len(branches):
                raise SelectionError('selector_branch')
            if keyword != 'allOf':
                guards.append({'kind': keyword, 'parent_schema_pointer': pointer,
                               'instance_pattern': copy.deepcopy(pattern),
                               'branch_index': index})
            node = branches[index]
            pointer += '/' + keyword + '/' + str(index)
        elif op == 'conditional':
            arm = step['arm']
            if 'if' not in node or arm not in node:
                raise SelectionError('selector_conditional')
            guards.append({'kind': 'if', 'schema_pointer': pointer + '/if',
                           'instance_pattern': copy.deepcopy(pattern),
                           'expected': arm == 'then'})
            node = node[arm]
            pointer += '/' + arm
        else:
            raise SelectionError('selector_step')
    stop = boundary(root, pointer, pattern)
    if kind == 'first_party' and stop:
        raise SelectionError('opaque_boundary')
    if kind != 'first_party' and stop != kind:
        raise SelectionError('specialized_boundary')
    return {'schema_pointer': pointer, 'instance_pattern': pattern, 'guards': guards}


def validator(schema, name):
    return Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': schema['$defs']})


def duplicates(items):
    return len(items) != len(set(items))


def registry_errors(value, schema, source, source_sha):
    if not validator(schema, 'Registry').is_valid(value):
        return {'schema'}, {}
    errors, compiled = set(), {}
    if value['schema_source']['sha256'] != source_sha:
        errors.add('source_digest')
    providers = {p['provider_id']: p for p in value['providers']}
    if len(providers) != len(value['providers']):
        errors.add('duplicate_provider')
    for provider in providers.values():
        for model in provider['model_refs']:
            try:
                model_node(source, model)
            except SelectionError as exc:
                errors.add(str(exc))
    plans = {p['fixture_id']: p for p in value['vector_plans']}
    if len(plans) != len(value['vector_plans']):
        errors.add('duplicate_fixture')
    if duplicates([r['rule_id'] for r in value['rules']]):
        errors.add('duplicate_rule')
    consumed = set()
    for rule in value['rules']:
        rid, kind = rule['rule_id'], rule['validator_kind']
        contexts = rule['context_requirements']
        if (rule['phase'] == 'linked') != bool(contexts):
            errors.add('phase_context')
        if kind != 'first_party' and (rule['phase'] != 'linked' or not contexts):
            errors.add('specialized_context')
        if duplicates([c['context_id'] for c in contexts]):
            errors.add('duplicate_context')
        for context in contexts:
            try:
                model_node(source, context['model_ref'])
            except SelectionError as exc:
                errors.add(str(exc))
            provider = providers.get(context['provider_id'])
            if provider is None:
                errors.add('context_provider')
            else:
                if context['model_ref'] not in provider['model_refs']:
                    errors.add('context_model')
                if context['policy_ref'] not in provider['policy_refs']:
                    errors.add('context_policy')
        locations = {v['location_id'] for v in rule['locations']}
        if len(locations) != len(rule['locations']):
            errors.add('duplicate_location')
        if duplicates([v['reason_code'] for v in rule['reason_codes']]):
            errors.add('duplicate_reason')
        for reason in rule['reason_codes']:
            if not set(reason['location_ids']) <= locations:
                errors.add('reason_location')
        if duplicates([v['language'] for v in rule['implementation_bindings']]):
            errors.add('duplicate_binding')
        for binding in rule['implementation_bindings']:
            path = binding['module_path']
            if any(part in ('', '.', '..') for part in path.split('/')):
                errors.add('binding_path')
            if not path.endswith('.ts' if binding['language'] == 'typescript' else '.py'):
                errors.add('binding_language')
        expected = set()
        for fid in rule['fixture_refs']:
            plan = plans.get(fid)
            if plan is None or plan['rule_id'] != rid:
                errors.add('fixture_binding')
            if plan is not None:
                consumed.add(fid)
                expected.add(plan['expected_status'])
        if not {'valid', 'invalid'} <= expected:
            errors.add('fixture_coverage')
        try:
            item = select(source, rule['input_model_ref'], rule['instance_selector'], kind)
            item['locations'] = {}
            for loc in rule['locations']:
                item['locations'][loc['location_id']] = select(
                    source, rule['input_model_ref'], rule['instance_selector'] + loc['selector'], kind)
            compiled[rid] = item
        except SelectionError as exc:
            errors.add(str(exc))
    if consumed != set(plans):
        errors.add('orphan_fixture')
    return errors, compiled


def result_errors(value, schema, registry):
    if not validator(schema, 'Result').is_valid(value):
        return {'schema'}
    rules = {r['rule_id']: r for r in registry['rules']}
    rule = rules.get(value['rule_id'])
    if rule is None:
        return {'result_rule'}
    errors = set()
    if value['revision'] != rule['revision']:
        errors.add('result_revision')
    if value['status'] == 'invalid':
        codes = {r['reason_code']: set(r['location_ids']) for r in rule['reason_codes']}
        order = {(r['reason_code'], loc): (i, j)
                 for i, r in enumerate(rule['reason_codes'])
                 for j, loc in enumerate(r['location_ids'])}
        for violation in value['violations']:
            allowed = codes.get(violation['reason_code'])
            if allowed is None:
                errors.add('result_reason')
            elif violation['location_id'] not in allowed:
                errors.add('result_location')
        pairs = [(v['reason_code'], v['location_id']) for v in value['violations']]
        if all(pair in order for pair in pairs) and pairs != sorted(pairs, key=order.__getitem__):
            errors.add('result_order')
    if value['status'] == 'context_unavailable':
        allowed = {c['context_id'] for c in rule['context_requirements']}
        if not set(value['context_ids']) <= allowed:
            errors.add('result_context')
    return errors


def input_hashes(staged=False):
    result = {}
    for name in INPUTS:
        path = ROOT / name
        key = path.relative_to(REPO).as_posix()
        raw = subprocess.check_output(['git', 'show', ':' + key], cwd=REPO) if staged else path.read_bytes()
        result[key] = hashlib.sha256(raw).hexdigest()
    return result


def run():
    schema = strict_loads((ROOT / 'semantic-registry.schema.json').read_bytes())
    cases = strict_loads((ROOT / 'semantic-registry-cases.json').read_bytes())
    source_bytes = (ROOT / 'source/public.schema.json').read_bytes()
    source = strict_loads(source_bytes)
    sha = hashlib.sha256(source_bytes).hexdigest()
    Draft202012Validator.check_schema(schema)
    errors, compiled = registry_errors(cases['base'], schema, source, sha)
    assert not errors, errors
    observations, ids = [], set()
    for case in cases['registry_cases']:
        assert case['id'] not in ids
        ids.add(case['id'])
        value = copy.deepcopy(cases['base'])
        for path, replacement in case['set']:
            target = value
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = copy.deepcopy(replacement)
        actual, paths = registry_errors(value, schema, source, sha)
        assert actual == set(case['expected_errors']), (case['id'], sorted(actual), case['expected_errors'])
        for rid, expected in case.get('expected_compilation', {}).items():
            assert paths[rid] == expected, (case['id'], '编译路径不符合独立预期')
        observations.append({'id': case['id'], 'errors': sorted(actual),
                             'compiled_paths': paths if not actual else None})
    for case in cases['result_cases']:
        assert case['id'] not in ids
        ids.add(case['id'])
        actual = result_errors(case['value'], schema, cases['base'])
        assert actual == set(case['expected_errors']), (case['id'], sorted(actual), case['expected_errors'])
        observations.append({'id': case['id'], 'errors': sorted(actual)})
    Draft202012Validator.check_schema(cases['selector_source'])
    for case in cases['selector_cases']:
        assert case['id'] not in ids
        ids.add(case['id'])
        assert validator(schema, 'Selector').is_valid(case['steps'])
        actual_error, actual_path = None, None
        try:
            actual_path = select(cases['selector_source'], case['root'], case['steps'], case['validator_kind'])
        except SelectionError as exc:
            actual_error = str(exc)
        assert actual_error == case['expected_error'], (case['id'], actual_error)
        assert actual_path == case['expected_compilation'], (case['id'], actual_path)
        observations.append({'id': case['id'], 'error': actual_error, 'compiled_path': actual_path})
    return {'all_passed': True, 'scope': '语义注册元数据及结果形状离线检查',
            'registry_cases': len(cases['registry_cases']), 'result_cases': len(cases['result_cases']),
            'synthetic_selector_cases': len(cases['selector_cases']),
            'business_vector_plans_not_executed': len(cases['base']['vector_plans']),
            'production_rules_executed': 0, 'runtime_tests_executed': 0,
            'sdk_authority_switched': False, 'compiled_base': compiled,
            'observations': observations, 'input_sha256': input_hashes()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--report', action='store_true')
    group.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged仅用于--check-report')
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + REPORT.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else REPORT.read_bytes()
        report = strict_loads(raw)
        assert report['input_sha256'] == input_hashes(args.staged), '报告输入绑定不一致'
        print(json.dumps({'bindings_matched': len(INPUTS), 'tests_rerun': False, 'staged': args.staged}))
        return
    report = run()
    if args.report:
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('observations', 'compiled_base', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
