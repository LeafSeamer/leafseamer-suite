"""只验证合成 Bundle 设计、引用图和有限轨迹，不是生产加载器。"""
import argparse
import base64
import copy
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

import rfc8785
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = [ROOT / n for n in ('BUNDLE.md', 'bundle.schema.json', 'bundle-cases.json', 'check_bundle.py')]
DIALECT = 'https://json-schema.org/draft/2020-12/schema'
MAP = {'$defs', 'properties', 'patternProperties', 'dependentSchemas'}
ARRAY = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}
SINGLE = {'items', 'additionalProperties', 'propertyNames', 'contains', 'not', 'if', 'then', 'else',
          'unevaluatedItems', 'unevaluatedProperties'}
SAME = {'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else', 'dependentSchemas'}
KEYWORDS = MAP | ARRAY | SINGLE | {
    '$schema', '$id', '$anchor', '$ref', 'type', 'enum', 'const', 'multipleOf', 'maximum', 'minimum',
    'exclusiveMaximum', 'exclusiveMinimum', 'maxLength', 'minLength', 'pattern', 'format',
    'maxItems', 'minItems', 'uniqueItems', 'maxContains', 'minContains', 'maxProperties',
    'minProperties', 'required', 'dependentRequired', 'title', 'description', 'readOnly', 'writeOnly', 'deprecated'}


def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(v): return rfc8785.dumps(v)
def digest(v): return sha(canonical(v))


def load(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise ValueError('重复键')
            out[k] = v
        return out
    def invalid(v): raise ValueError('非法JSON常量')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def budget(v, depth=0):
    if isinstance(v, (dict, list)):
        if depth >= 64: raise ValueError('深度超限')
        for item in v.values() if isinstance(v, dict) else v: budget(item, depth + 1)
    if isinstance(v, int) and not isinstance(v, bool) and abs(v) > 9007199254740991:
        raise ValueError('不安全整数')
    if isinstance(v, float) and (not math.isfinite(v) or (v.is_integer() and abs(v) > 9007199254740991)):
        raise ValueError('不安全数值')


def validator(schema, name):
    return Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/' + name})


def profile_errors(documents, exports, context):
    errors = set(); nodes = {}; edges = {}; anchors = {}; refs = []
    resource_edges = {sid: set() for sid in documents}
    for sid, doc in documents.items():
        try:
            budget(doc); Draft202012Validator.check_schema(doc)
        except (ValueError, RecursionError, SchemaError):
            # 输入是有限离线夹具；此处将第三方meta验证错误归入同一类。
            errors.add('schema_invalid'); continue
        count = 0
        def walk(node, path=()):
            nonlocal count
            key = (sid, path); nodes[key] = node; edges.setdefault(key, set()); count += 1
            if isinstance(node, bool): return
            if not isinstance(node, dict): errors.add('schema_invalid'); return
            if set(node) - KEYWORDS: errors.add('keyword')
            if ('$id' in node and (path or node['$id'] != sid)) or ('$schema' in node and (path or node['$schema'] != DIALECT)):
                errors.add('resource_identity')
            if '$anchor' in node:
                anchor = node['$anchor']; ak = (sid, anchor)
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9._-]*', anchor) or ak in anchors: errors.add('anchor')
                anchors[ak] = key
            if '$ref' in node: refs.append((key, node['$ref']))
            if 'format' in node and node['format'] not in context['approved_formats']: errors.add('format')
            patterns = ([node['pattern']] if 'pattern' in node else []) + list(node.get('patternProperties', {}))
            if any(p not in context['approved_patterns'] for p in patterns): errors.add('pattern')
            children = []
            for keyword in MAP & node.keys():
                children.extend((keyword, path + (keyword, name), child) for name, child in node[keyword].items())
            for keyword in ARRAY & node.keys():
                children.extend((keyword, path + (keyword, str(i)), child) for i, child in enumerate(node[keyword]))
            for keyword in SINGLE & node.keys(): children.append((keyword, path + (keyword,), node[keyword]))
            for keyword, target, child in children:
                if keyword in SAME: edges[key].add((sid, target))
                walk(child, target)
        walk(doc)
        if count > 4096: errors.add('schema_capacity')
    if len(nodes) > 8192 or len(refs) > 4096: errors.add('schema_capacity')
    for origin, ref in refs:
        sid, _, fragment = ref.partition('#')
        if not sid: sid = origin[0]
        if sid not in documents or (not ref.startswith('#') and not ref.startswith('urn:leafseamer:panel-schema:')):
            errors.add('reference'); continue
        if re.search(r'%(?![0-9a-fA-F]{2})', fragment): errors.add('reference'); continue
        try: fragment = unquote(fragment, encoding='utf-8', errors='strict')
        except UnicodeError: errors.add('reference'); continue
        target = None
        if fragment == '': target = (sid, ())
        elif fragment.startswith('/'):
            parts = fragment[1:].split('/')
            if any(re.search(r'~(?![01])', p) for p in parts): errors.add('reference'); continue
            target = (sid, tuple(p.replace('~1', '/').replace('~0', '~') for p in parts))
        else: target = anchors.get((sid, fragment))
        if target not in nodes: errors.add('reference'); continue
        edges[origin].add(target); resource_edges[origin[0]].add(sid)
    # Kahn 拓扑检测避免用递归 DFS 在长引用链上击穿检查器栈。
    indegree = {n: 0 for n in nodes}
    for targets in edges.values():
        for target in targets: indegree[target] += 1
    pending = [n for n, degree in indegree.items() if degree == 0]; visited = 0
    while pending:
        n = pending.pop(); visited += 1
        for target in edges[n]:
            indegree[target] -= 1
            if indegree[target] == 0: pending.append(target)
    if visited != len(nodes): errors.add('same_instance_cycle')
    reachable = set()
    for e in exports:
        ref = e['schema_ref']; sid = ref['schema_id']
        if (sid, ('$defs', ref['definition'])) not in nodes: errors.add('export_definition')
        if sid not in documents or ref['schema_digest'] != digest(documents[sid]): errors.add('export_digest')
        reachable.add(sid)
    pending = list(reachable)
    while pending:
        for child in resource_edges.get(pending.pop(), set()) - reachable:
            reachable.add(child); pending.append(child)
    if reachable != set(documents): errors.add('resource_closure')
    return errors


def authority_errors(m, c):
    errors = set()
    if not c['authorized'] or not c['approval_active']: errors.add('authority')
    for field in ('manifest_digest', 'registry_ref', 'scope_revision', 'profile_ref', 'exports'):
        if m[field] != c[field]: errors.add('authority_' + field)
    return errors


def manifest_errors(m, c, schema):
    if not validator(schema, 'Manifest').is_valid(m): return {'structure'}
    errors = authority_errors(m, c)
    if len(canonical(m)) > 65536: errors.add('manifest_capacity')
    if m['manifest_digest'] != digest({k: v for k, v in m.items() if k != 'manifest_digest'}): errors.add('manifest_digest')
    ids = [r['schema_id'] for r in m['resources']]; keys = [e['binding_key'] for e in m['exports']]
    if ids != sorted(set(ids)) or keys != sorted(set(keys)): errors.add('identity_order')
    if sum(r['canonical_bytes'] for r in m['resources']) > 1048576 or sum(len(r['chunks']) for r in m['resources']) > 64:
        errors.add('bundle_capacity')
    for r in m['resources']:
        sizes = [min(16384, r['canonical_bytes'] - i) for i in range(0, r['canonical_bytes'], 16384)]
        if [x['index'] for x in r['chunks']] != list(range(len(sizes))) or [x['byte_count'] for x in r['chunks']] != sizes:
            errors.add('chunk_layout')
    return errors


def bundle_errors(m, raws, c, schema):
    errors = manifest_errors(m, c, schema)
    if 'structure' in errors: return errors
    if set(raws) != {r['schema_id'] for r in m['resources']}: return errors | {'document_set'}
    docs = {}
    for r in m['resources']:
        raw = raws[r['schema_id']]
        if len(raw) != r['canonical_bytes'] or sha(raw) != r['document_digest']: errors.add('document_digest')
        for part in r['chunks']:
            b = raw[part['index'] * 16384:(part['index'] + 1) * 16384]
            if len(b) != part['byte_count'] or sha(b) != part['digest']: errors.add('chunk_digest')
        try:
            doc = load(raw.decode('utf-8')); budget(doc)
            if canonical(doc) != raw: errors.add('noncanonical_document')
            docs[r['schema_id']] = doc
        except (ValueError, UnicodeError, RecursionError): errors.add('document_json')
    if len(docs) == len(raws): errors |= profile_errors(docs, m['exports'], c)
    return errors


def frame_errors(frame, c, schema, direction, last):
    name = {'host.bundle_offer': 'Offer', 'host.bundle_chunk': 'Chunk',
            'panel.bundle_ready': 'Ready', 'host.bundle_revoke': 'Revoke'}.get(frame.get('type'))
    if name is None or not validator(schema, name).is_valid(frame): return {'structure'}
    errors = set()
    if len(canonical(frame)) > 65536: errors.add('frame_capacity')
    if frame['public_binding'] != c['public_binding'] or not c['port_matches']: errors.add('binding')
    if direction != ('panel' if name == 'Ready' else 'host'): errors.add('direction')
    if int(frame['channel_sequence']) <= last: errors.add('sequence')
    return errors


def delivery(trace, fixture, schema):
    """离散模型动作；所有权威、原子执行及端口事实均由人工上下文假定。"""
    m = fixture['manifest']; c = copy.deepcopy(fixture['context']); state = 'inactive'
    buffer = {}; last = {'host': 0, 'panel': 0}; decisions = []
    for event in trace:
        kind = event['kind']; errors = set()
        if kind == 'context':
            c.update(copy.deepcopy(event['values'])); decisions.append(True); continue
        if kind == 'frame':
            f = copy.deepcopy(fixture['frames'][event['name']]); mutate(f, event.get('changes', []))
            direction = event['direction']; errors |= frame_errors(f, c, schema, direction, last[direction])
            if not errors:
                last[direction] = int(f['channel_sequence']); typ = f['type']
                if typ == 'host.bundle_offer':
                    if state != 'inactive': errors.add('state')
                    errors |= manifest_errors(f['manifest'], c, schema)
                    if f['manifest'] != m: errors.add('manifest_binding')
                    if not errors: state = 'staging'
                else:
                    if f['bundle_id'] != m['bundle_id'] or f['manifest_digest'] != m['manifest_digest']: errors.add('bundle_binding')
                    if typ == 'host.bundle_revoke':
                        if not errors: state = 'revoked'; c['approval_active'] = False; buffer.clear()
                    elif typ == 'host.bundle_chunk':
                        if state != 'staging': errors.add('state')
                        key = (f['schema_id'], f['index'])
                        resource = next((r for r in m['resources'] if r['schema_id'] == key[0]), None)
                        part = next((x for x in resource['chunks'] if x['index'] == key[1]), None) if resource else None
                        try:
                            raw = base64.b64decode(f['content_base64'], validate=True)
                            if base64.b64encode(raw).decode('ascii') != f['content_base64']: raise ValueError('非规范base64')
                            if part is None or len(raw) != part['byte_count'] or sha(raw) != part['digest']: errors.add('chunk_digest')
                            if key in buffer and buffer[key] != raw: errors.add('chunk_conflict')
                            if not errors: buffer[key] = raw
                        except ValueError: errors.add('base64')
                    elif typ == 'panel.bundle_ready':
                        if state != 'verified': errors.add('state')
                        if f['registry_ref'] != m['registry_ref'] or f['scope_revision'] != m['scope_revision']: errors.add('ready_binding')
                        errors |= authority_errors(m, c)
                        if not errors: state = 'ready_reported'
        elif kind == 'verify':
            expected = {(r['schema_id'], x['index']) for r in m['resources'] for x in r['chunks']}
            if state != 'staging' or set(buffer) != expected: errors.add('incomplete')
            else:
                raws = {r['schema_id']: b''.join(buffer[(r['schema_id'], x['index'])] for x in r['chunks']) for r in m['resources']}
                errors |= bundle_errors(m, raws, c, schema)
            if not errors: state = 'verified'
        elif kind in ('activate', 'use'):
            if state != ('ready_reported' if kind == 'activate' else 'active'): errors.add('state')
            errors |= authority_errors(m, c)
            if c['public_binding'] != fixture['context']['public_binding'] or not c['port_matches']: errors.add('binding')
            if not errors and kind == 'activate': state = 'active'
        else: raise ValueError('未知轨迹动作')
        if errors and state != 'revoked': state = 'failed'
        decisions.append(not errors)
    return decisions, state


def mutate(value, changes):
    for change in changes:
        node = value
        for key in change['path'][:-1]: node = node[key]
        if change.get('delete'): del node[change['path'][-1]]
        else: node[change['path'][-1]] = copy.deepcopy(change['value'])


def hashes(staged=False):
    return {p.relative_to(REPO).as_posix(): sha(subprocess.check_output(
        ['git', 'show', ':' + p.relative_to(REPO).as_posix()], cwd=REPO) if staged else p.read_bytes()) for p in INPUTS}


def reseal_fixture(f, trust=False):
    """测试构造：重算公开摘要；trust只表示人工夹具批准前提，不是产品批准。"""
    m = f['manifest']; resources = []
    for sid, doc in sorted(f['documents'].items()):
        raw = canonical(doc)
        resources.append({'schema_id': sid, 'document_digest': sha(raw), 'canonical_bytes': len(raw),
                          'chunks': [{'index': i // 16384, 'byte_count': len(raw[i:i+16384]), 'digest': sha(raw[i:i+16384])}
                                     for i in range(0, len(raw), 16384)]})
    m['resources'] = resources
    for e in m['exports']:
        if e['schema_ref']['schema_id'] in f['documents']:
            e['schema_ref']['schema_digest'] = digest(f['documents'][e['schema_ref']['schema_id']])
    m['manifest_digest'] = digest({k: v for k, v in m.items() if k != 'manifest_digest'})
    if trust:
        for field in ('manifest_digest', 'registry_ref', 'scope_revision', 'profile_ref', 'exports'):
            f['context'][field] = copy.deepcopy(m[field])


def run():
    schema = load((ROOT / 'bundle.schema.json').read_bytes()); Draft202012Validator.check_schema(schema)
    data = load((ROOT / 'bundle-cases.json').read_bytes())
    assert data['purpose'] == 'synthetic_bundle_design_only' and data['runtime_approved'] is False
    results = []
    for case in data['bundle_cases']:
        f = copy.deepcopy(data['fixtures'][case.get('fixture', 'basic')])
        mutate(f, case.get('before', []))
        if case.get('reseal'): reseal_fixture(f, case.get('trust_resealed', False))
        mutate(f, case.get('after', []))
        raws = {k: canonical(v) for k, v in f['documents'].items()}
        raws.update({k: v.encode('utf-8') for k, v in case.get('raw_overrides', {}).items()})
        errors = bundle_errors(f['manifest'], raws, f['context'], schema)
        assert (not errors) == case['valid'], (case['id'], errors)
        if 'error' in case: assert case['error'] in errors, (case['id'], errors)
        results.append({'id': case['id'], 'passed': True, 'errors': sorted(errors)})
    fixture = data['delivery_fixture']
    for case in data['frame_cases']:
        f = copy.deepcopy(fixture['frames'][case['name']]); mutate(f, case['changes'])
        errors = frame_errors(f, fixture['context'], schema, case['direction'], case['last'])
        assert (not errors) == case['valid'], (case['id'], errors)
        results.append({'id': case['id'], 'passed': True, 'errors': sorted(errors)})
    for case in data['trace_cases']:
        decisions, state = delivery(case['events'], fixture, schema)
        assert decisions == case['decisions'] and state == case['state'], (case['id'], decisions, state)
        results.append({'id': case['id'], 'passed': True, 'decisions': decisions, 'state': state})
    assert len({r['id'] for r in results}) == len(results)
    return {'format_version': 'panel-bundle-reference/1', 'approved': False, 'runtime_approved': False,
            'all_passed': True, 'case_count': len(results), 'results': results,
            'tools': {'python': platform.python_version(), 'jsonschema': importlib.metadata.version('jsonschema'),
                      'rfc8785': importlib.metadata.version('rfc8785')},
            'runtime_validation': {'browser': 0, 'authority_provider': 0, 'worker': 0, 'device': 0},
            'artifact_sha256': hashes()}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true'); parser.add_argument('--staged', action='store_true')
    args = parser.parse_args(); path = ROOT / 'bundle-report.json'
    if args.staged and not args.check_report: parser.error('--staged需要--check-report')
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + path.relative_to(REPO).as_posix()], cwd=REPO) if args.staged else path.read_bytes()
        assert load(raw)['artifact_sha256'] == hashes(args.staged), '报告输入已改变'
        print('Bundle报告4输入字节绑定通过'); return
    report = run()
    if args.report: path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('Bundle参考检查通过：' + str(report['case_count']) + '项；真实运行0')


if __name__ == '__main__': main()
