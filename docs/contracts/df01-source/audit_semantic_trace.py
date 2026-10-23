"""只读追踪历史判定器与模型引用图；--report仅写本目录参考报告。"""
import argparse
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
SUITE = ROOT.parents[2]
MAP = ROOT / 'semantic-trace-map.json'
PROJECTIONS = ROOT / 'digest-projection-map.json'
REPORT = ROOT / 'semantic-trace-report.json'
BASE = SUITE / 'docs/contracts/draft4'
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}


def pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise ValueError('重复键')
        out[k] = v
    return out


def read(path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def walk(v):
    yield v
    if isinstance(v, dict):
        for x in v.values():
            yield from walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from walk(x)


def graph_observation(schema, ipc):
    defs = schema['$defs']
    def refs(v, prefix):
        return {n['$ref'][len(prefix):] for n in walk(v)
                if isinstance(n, dict) and isinstance(n.get('$ref'), str) and n['$ref'].startswith(prefix)}
    def closure(roots):
        found = set()
        pending = list(roots)
        while pending:
            model = pending.pop()
            if model in found:
                continue
            if model not in defs:
                raise ValueError('不存在的模型根: ' + model)
            found.add(model)
            pending.extend(refs(defs[model], '#/$defs/') - found)
        return found
    public_http, public_ws, internal = set(), set(), set()
    services = {}
    for service in ('controller', 'seamer'):
        api = read(BASE / (service + '.openapi.json'))
        service_roots = set()
        for path, item in api['paths'].items():
            for method, op in item.items():
                if method not in METHODS:
                    continue
                roots = refs(op, '#/components/schemas/')
                if path.startswith('/internal/'):
                    internal.update(roots)
                else:
                    public_http.update(roots)
                    service_roots.update(roots)
                    for key in ('x-ticket-binding-schema', 'x-websocket-frame-schema'):
                        if key in op:
                            value = op[key]
                            if not value.startswith('#/components/schemas/'):
                                raise ValueError('未知WS具名根')
                            model = value.split('/')[-1]
                            public_ws.add(model)
                            service_roots.add(model)
        services[service] = {'roots': sorted(service_roots), 'closure': sorted(closure(service_roots))}
    public = public_http | public_ws
    ipc_roots = refs(ipc, schema['$id'] + '#/$defs/')
    a, b, c = closure(public), closure(internal), closure(ipc_roots)
    only = (b | c) - a
    unused = set(defs) - (a | b | c)
    return {'counts': {'public_http_roots': len(public_http), 'public_with_ws_roots': len(public),
                      'public_closure': len(a), 'internal_roots': len(internal), 'internal_closure': len(b),
                      'ipc_external_roots': len(ipc_roots), 'ipc_external_closure': len(c),
                      'internal_or_ipc_only': len(only), 'unreferenced': sorted(unused)},
            'services': services, 'public_roots': sorted(public), 'internal_roots': sorted(internal),
            'ipc_external_roots': sorted(ipc_roots), 'public_closure': sorted(a),
            'internal_closure': sorted(b), 'ipc_external_closure': sorted(c),
            'internal_or_ipc_only': sorted(only), 'unreferenced': sorted(unused),
            'exports_approved': False, 'open_payload_content_inspected': False}


def run():
    mapping = read(MAP)
    if mapping['purpose'] != 'design_reference_only' or mapping['authority_switched'] is not False:
        raise ValueError('追踪不是SDK权威切换')
    # 先执行完整历史验证，包括结构、生成漂移、关联和OpenAPI检查。
    prior = json.loads(subprocess.check_output([sys.executable, str(BASE / 'validate_contracts.py')],
                                              cwd=SUITE, text=True, encoding='utf-8'))
    if prior.get('all_passed') is not True:
        raise ValueError('历史检查未通过')
    report_path = 'docs/contracts/draft4/validation-report.json'
    report_raw = (SUITE / report_path).read_bytes()
    if report_raw != subprocess.check_output(['git', 'show', mapping['source_commit'] + ':' + report_path], cwd=SUITE):
        raise ValueError('历史报告本身与固定提交不符')
    historical_report = json.loads(report_raw, object_pairs_hook=pairs)
    inputs = {str(p.relative_to(SUITE)).replace('\\', '/') for p in (MAP, PROJECTIONS, Path(__file__), BASE / 'validation-report.json')}
    # 来源逐字节与固定提交比对，不把本轮报告期望从当前改变后的源码生成。
    for path, expected in historical_report['input_sha256'].items():
        rel = 'docs/' + path
        raw = (SUITE / rel).read_bytes()
        committed = subprocess.check_output(['git', 'show', mapping['source_commit'] + ':' + rel], cwd=SUITE)
        if raw != committed or sha(raw) != expected:
            raise ValueError('历史来源漂移: ' + rel)
        inputs.add(rel)
    module_paths = {str((SUITE / p).resolve()): alias for alias, p in mapping['modules'].items()}
    groups = {}
    source_symbols = {}
    for group in mapping['groups']:
        key = group['module'], group['symbol']
        if key in groups:
            raise ValueError('重复语义入口')
        groups[key] = group['id']
    if len(set(groups.values())) != len(groups):
        raise ValueError('重复规则ID')
    for alias, path in mapping['modules'].items():
        raw = (SUITE / path).read_bytes()
        text = raw.decode('utf-8')
        source_symbols[alias] = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
    symbols = []
    for group in mapping['groups']:
        node = source_symbols[group['module']][group['symbol']]
        symbols.append({'id': group['id'], 'source': mapping['modules'][group['module']],
                        'symbol': group['symbol'], 'line': node.lineno, 'end_line': node.end_lineno})
    # 导入已固定摘要的离线判定器；不调用产品服务或联网。
    sys.path.insert(0, str(BASE))
    spec = importlib.util.spec_from_file_location('draft4_trace', BASE / 'validate_contracts.py')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    schema, ipc, fixtures = (read(BASE / p) for p in ('first-loop.schema.json', 'ipc.schema.json', 'examples.json'))
    projection_map = read(PROJECTIONS)
    if projection_map['purpose'] != 'historical_projection_reference' or projection_map['authority_switched'] is not False:
        raise ValueError('投影映射不是运行批准')
    projection_ids = set()
    fixture_ids = {'public': {c['case_id'] for c in fixtures['examples']}, 'linked': {c['case_id'] for c in fixtures['link_cases']}}
    for p in projection_map['projections']:
        if p['id'] in projection_ids or p['source']['symbol'] not in source_symbols[p['source']['module']]:
            raise ValueError('投影ID重复或符号缺失')
        projection_ids.add(p['id'])
        if p['input_model'] is not None and p['input_model'] not in schema['$defs']:
            raise ValueError('投影模型缺失')
        for ref in p['fixture_refs']:
            if ref['case_id'] not in fixture_ids[ref['group']]:
                raise ValueError('投影夹具缺失')
    symbol_hits = set()
    def trace_call(function, *args):
        hits = set()
        def profile(frame, event, arg):
            if event == 'call':
                alias = module_paths.get(frame.f_code.co_filename)
                name = frame.f_code.co_name
                if alias and not name.startswith('<'):
                    hits.add((alias, name))
        old_profile = sys.getprofile()
        sys.setprofile(profile)
        try:
            result = function(*args)
        finally:
            sys.setprofile(old_profile)
        symbol_hits.update(hits)
        unknown = hits - set(groups) - {(a, n) for a, names in mapping['helpers'].items() for n in names}
        if unknown:
            raise ValueError('执行到未登记函数: ' + repr(sorted(unknown)))
        return result, sorted(groups[k] for k in hits if k in groups)
    observed = []
    for case in fixtures['examples']:
        errors, hits = trace_call(validator.semantics, case['model'], case['instance']) if case['schema_valid'] else (None, [])
        if errors is not None and (not errors) != case['semantic_valid']:
            raise ValueError('公共语义与独立预期不符: ' + case['case_id'])
        observed.append({'case_id': case['case_id'], 'group': 'public', 'model': case['model'],
                         'stage': 'semantic' if errors is not None else 'structural_rejection',
                         'entered_groups': hits, 'observed_errors': errors})
    for case in fixtures['ipc_examples']:
        observed.append({'case_id': case['case_id'], 'group': 'ipc', 'stage': 'structural_only',
                         'entered_groups': [], 'observed_valid': case['valid']})
    for case in fixtures['link_cases']:
        result, hits = trace_call(validator.linked, case['kind'], case['input'])
        if result != case['expected']:
            raise ValueError('关联结果与独立预期不符: ' + case['case_id'])
        observed.append({'case_id': case['case_id'], 'group': 'linked', 'kind': case['kind'],
                         'stage': 'linked_boolean', 'entered_groups': hits, 'observed_valid': result})
    counts = {'public': len(fixtures['examples']), 'ipc': len(fixtures['ipc_examples']),
              'linked': len(fixtures['link_cases']),
              'public_structural_negative': sum(not c['schema_valid'] for c in fixtures['examples']),
              'public_semantic_negative': sum(c['schema_valid'] and not c['semantic_valid'] for c in fixtures['examples'])}
    if counts != mapping['historical_case_counts']:
        raise ValueError('历史分层计数发生变化')
    group_entries = {g['id']: sum(g['id'] in c['entered_groups'] for c in observed) for g in mapping['groups']}
    if any(n == 0 for n in group_entries.values()):
        raise ValueError('预期参与的函数未被跟踪；不能将空跟踪当作覆盖证据')
    inactive = []
    for item in mapping['not_in_232']:
        if item['symbol'] not in source_symbols[item['module']] or (item['module'], item['symbol']) in symbol_hits:
            raise ValueError('未执行函数声明不符')
        inactive.append(dict(item, entered=False))
    # 新探针独立于232，固定“历史接受/拒绝/异常”，不把已知缺口包装为修复。
    probes = []
    for p in mapping['probes']:
        value = deepcopy(next(c['instance'] for c in fixtures['examples'] if c['case_id'] == p['fixture_id']))
        if p['model'] == 'CommandRequest':
            value['action_id'] = 'fixture.generic.set'
            value['parameters'] = {'descriptor_shaped_payload': {'descriptor_version': 'fixture'},
                                   'window_shaped_payload': {'not_before': 'z', 'not_after': 'a'},
                                   'state_machine_shaped_payload': {'kind': 'state_machine'}}[p['mutation']]
        elif p['mutation'] == 'duplicate_scene_identity':
            entry = deepcopy(value['entries'][0]); entry['obs_scene_uuid'] = '22222222-2222-4222-8222-222222222222'
            entry['display_name'] = '合成重复身份'; value['entries'].append(entry)
        else:
            raise ValueError('未知探针')
        structural = Draft202012Validator(dict(schema, **{'$ref': '#/$defs/' + p['model']}), format_checker=FormatChecker()).is_valid(value)
        try:
            errors = validator.semantics(p['model'], value)
            result, detail = ('rejected', errors) if errors else ('accepted', None)
        except Exception as e:
            result, detail = 'exception', type(e).__name__
        if structural != p['expected_schema_valid'] or result != p['expected_result']:
            raise ValueError('历史探针结果不符: ' + p['id'])
        if p['expected_detail'] is not None and p['expected_detail'] not in (detail if isinstance(detail, list) else [detail]):
            raise ValueError('历史探针错误类型不符: ' + p['id'])
        probes.append({'id': p['id'], 'schema_valid': structural, 'result': result, 'detail': detail,
                       'fixed': False, 'capability_schema_checked': False})
    exposure = graph_observation(schema, ipc)
    if exposure['counts'] != mapping['exposure_expected']:
        raise ValueError('引用图计数与人工复核不符')
    return {'all_passed': True, 'purpose': 'historical_trace_and_gap_reproduction', 'source_commit': mapping['source_commit'],
            'coverage_unit': mapping['coverage_unit'], 'case_counts': counts, 'source_symbols': symbols,
            'cases_entering_group': group_entries,
            'case_observations': observed, 'not_in_232': inactive, 'probes': probes, 'exposure': exposure,
            'projection_references_checked': len(projection_ids), 'projection_algorithms_executed_from_map': False,
            'runtime_tests_executed': 0, 'sdk_semantics_implemented': False,
            'input_sha256': {p: sha((SUITE / p).read_bytes()) for p in sorted(inputs)}}


def check_report(staged):
    def raw(path):
        if not path.startswith('docs/') or '..' in path.split('/') or '\\' in path or ':' in path:
            raise ValueError('非法绑定路径')
        return subprocess.check_output(['git', 'show', ':' + path], cwd=SUITE) if staged else (SUITE / path).read_bytes()
    report = json.loads(raw(str(REPORT.relative_to(SUITE)).replace('\\', '/')), object_pairs_hook=pairs)
    if report.get('all_passed') is not True or not report.get('input_sha256'):
        raise ValueError('缺少有效报告')
    for path, expected in report['input_sha256'].items():
        if sha(raw(path)) != expected:
            raise ValueError('报告输入漂移: ' + path)
    return {'all_passed': True, 'scope': '仅声明输入字节绑定', 'staged': staged,
            'matched_bindings': len(report['input_sha256'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report or args.report and args.check_report:
        parser.error('staged仅配合check-report，report与check-report互斥')
    result = check_report(args.staged) if args.check_report else run()
    if args.report:
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('case_observations', 'input_sha256', 'exposure', 'source_symbols')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
