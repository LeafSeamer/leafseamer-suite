"""离线核验音频候选资料的结构与关联；不实现协议、授权或持久状态机。"""
import argparse
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess

import rfc8785
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
INPUTS = ('audio-candidate.schema.json', 'audio-candidate-cases.json',
          'dm3-legacy-catalog.json', 'check_audio_candidates.py')


def unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('重复JSON键: ' + key)
        result[key] = value
    return result


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'), object_pairs_hook=unique_pairs)


def digest_without(value, field):
    return hashlib.sha256(rfc8785.dumps({k: v for k, v in value.items() if k != field})).hexdigest()


def modified(base, changes):
    result = copy.deepcopy(base)
    for change in changes:
        parent = result
        for key in change['path'][:-1]:
            parent = parent[int(key)] if isinstance(parent, list) else parent[key]
        key = change['path'][-1]
        parent[int(key) if isinstance(parent, list) else key] = copy.deepcopy(change['value'])
    return result


def parameter_decision(c, inventory, inventory_hash):
    definition, access = c['definition'], c['access']
    source = definition['legacy_source_ref']
    item = inventory.get(source['index'])
    if (source['inventory_sha256'] != inventory_hash or item is None
            or item['action'] != 'prminfo' or source['address'] != item['address']
            or definition['address'] != item['address']):
        return 'source_binding'
    if access['context'] != c['trusted_context']:
        return 'context_binding'
    if not (access['definition_ref'] == definition['definition_ref'] == c['trusted_definition_ref']):
        return 'definition_binding'
    advertised, approved = set(definition['advertised_access']), set(definition['approved_access'])
    if not approved <= advertised:
        return 'access_expansion'
    # 这里只用已经绑定摘要的旧来源定位秘密，绝不按现场数字index推断。
    if source['index'] == 119:
        if (definition['sensitivity'] != 'secret' or definition['value_mode'] != 'secret_ref_only'
                or definition['ordinary_exposure'] or definition['read_codec_ref'] is not None
                or 'read' in approved):
            return 'secret_exposure'
    elif definition['sensitivity'] != 'ordinary' or definition['value_mode'] != 'typed':
        return 'secret_exposure'
    for action in ('read', 'write'):
        if (action in approved) != (definition[action + '_codec_ref'] is not None):
            return 'access_codec'
    if 'write' in approved and any(definition[k] is None for k in ('completion_policy_ref', 'release_policy_ref')):
        return 'access_codec'
    if definition['ordinary_exposure'] and 'read' not in approved:
        return 'exposure_access'
    if set(access['effective_access']) != advertised & approved & set(access['session_access']):
        return 'access_intersection'
    return 'definition_consistent'


def vban_decision(c):
    request, reply = c['request'], c['reply']
    if any(int(v['wire_counter']) > 2**32 - 1 for v in (request, reply)):
        return 'counter_range'
    ticks = [request[k] for k in ('issued_tick_ns', 'deadline_tick_ns', 'task_deadline_tick_ns')]
    ticks += [reply['received_tick_ns'], c['now_tick_ns'], c['max_age_ns']]
    if any(int(v) > 2**64 - 1 for v in ticks):
        return 'integer_range'
    if request['request_digest'] != digest_without(request, 'request_digest'):
        return 'request_digest'
    if request['context'] != c['trusted_context'] or reply['context'] != request['context']:
        return 'context_binding'
    if request['clock_domain'] != c['trusted_clock_domain'] or reply['clock_domain'] != request['clock_domain']:
        return 'clock_binding'
    domain = request['clock_domain']
    if domain['clock_domain_id'] != 'clock_' + domain['descriptor_digest'][7:]:
        return 'clock_identity'
    if any(reply[k] != request[k] for k in ('request_id', 'request_digest')):
        return 'request_binding'
    if any(reply[k] != request[k] for k in ('transport_namespace', 'local_socket_ref', 'remote_endpoint_ref',
                                          'stream_binding_ref', 'wire_counter', 'target', 'property')):
        return 'reply_binding'
    if request['target']['endpoint_binding_ref'] != request['remote_endpoint_ref']:
        return 'target_endpoint_binding'
    if c['pending_state'] != 'submitted':
        return 'retired_request'
    # high_water是独占上界；夹具只检查数值关系，不证明预留已落盘或跨重启不回退。
    if not int(request['wire_counter']) < int(c['namespace_high_water']) <= 2**32:
        return 'counter_not_reserved'
    issued, deadline, task_deadline = (int(v) for v in ticks[:3])
    received, now, max_age = (int(v) for v in ticks[3:])
    if not issued < deadline <= task_deadline:
        return 'deadline_order'
    if not issued <= received <= now:
        return 'time_order'
    if received >= deadline or now >= deadline:
        return 'expired'
    if reply['result']['kind'] == 'error':
        return 'query_error'
    kind = reply['result']['value']['kind']
    if (request['property'] == 'gain' and kind not in ('finite_level', 'negative_infinity')) or (
            request['property'] != 'gain' and kind != 'boolean'):
        return 'value_type'
    if c['sample_policy'] != 'sample_after_request_qualified_fixture':
        return 'unqualified_observation'
    if now - issued >= max_age:
        return 'stale_observation'
    # 不返回presence、command succeeded或resource released；只有合成前提下的观察分类。
    return 'fresh_observation'


def source_tuple(source):
    return source['group'], source['index']


def wing_decision(c):
    plan = c['plan']
    if plan['plan_digest'] != digest_without(plan, 'plan_digest'):
        return 'plan_digest'
    if plan['context'] != c['trusted_context']:
        return 'context_binding'
    if plan['channel'] != c['current_observation_channel']:
        return 'channel_binding'
    if plan['initial_observation_ref'] != c['current_observation_ref']:
        return 'observation_binding'
    if not c['coherent']:
        return 'incoherent'
    if plan['footprint_ref'] != c['expected_footprint_ref']:
        return 'footprint_binding'
    before, target, branch = plan['before'], plan['target'], plan['branch']
    other = 'alternate' if branch == 'primary' else 'primary'
    if target[other] != before[other]:
        return 'unrequested_branch_change'
    if target['srcauto'] != before['srcauto']:
        return 'srcauto_change'
    if target['altsrc'] != (branch if plan['activate'] else before['altsrc']):
        return 'activation'
    required = {branch + '.' + p for p in ('group', 'index') if before[branch][p] != target[branch][p]}
    if target['altsrc'] != before['altsrc']:
        required.add('altsrc')
    steps = plan['ordered_primitives']
    if len(steps) != len(required) or {s['property'] for s in steps} != required:
        return 'step_set'
    if 'altsrc' in required and steps[-1]['property'] != 'altsrc':
        return 'activation_order'
    for key in ('primitive_id', 'observation_slot', 'permit_slot'):
        if len({s[key] for s in steps}) != len(steps):
            return 'duplicate_slot'
    if any(s['observation_slot'] == 'initial' for s in steps):
        return 'duplicate_slot'
    previous, precondition = before, 'initial'
    states = [before]
    for i, step in enumerate(steps):
        if step['before'] != previous:
            return 'step_chain'
        if step['precondition_slot'] != precondition:
            return 'step_precondition'
        projection = copy.deepcopy(previous)
        path = step['property'].split('.')
        parent = projection[path[0]] if len(path) == 2 else projection
        expected = target[path[0]][path[1]] if len(path) == 2 else target[path[0]]
        if type(step['value']) is not type(expected) or step['value'] != expected:
            return 'step_value'
        parent[path[-1]] = step['value']
        if step['after'] != projection:
            return 'step_projection'
        if i < len(steps) - 1 and step['after'] not in c['approved_intermediates']:
            return 'intermediate_policy'
        previous, precondition = step['after'], step['observation_slot']
        states.append(previous)
    if previous != target:
        return 'target_projection'
    sources = {source_tuple(s[b]) for s in states for b in ('primary', 'alternate')}
    if [source_tuple(s) for s in plan['affected_sources']] != sorted(sources):
        return 'footprint_sources'
    if not sources <= {source_tuple(s) for s in c['topology_sources']}:
        return 'topology'
    # expected_footprint_ref为人工前提；本函数不计算DCA/HA传播，也不派发permit。
    return 'plan_consistent'


def run():
    schema, data = load('audio-candidate.schema.json'), load('audio-candidate-cases.json')
    if data['purpose'] != 'synthetic-design-fixtures-no-network-no-runtime-authorization':
        raise ValueError('夹具用途不符')
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    inventory = {e['index']: e for e in load('dm3-legacy-catalog.json')['entries']}
    inventory_hash = hashlib.sha256((ROOT / 'dm3-legacy-catalog.json').read_bytes()).hexdigest()
    fields = {'parameter': ('definition', 'access'), 'vban': ('request', 'reply'), 'wing': ('plan',)}
    results, ids = [], set()
    for case in data['cases']:
        if case['id'] in ids:
            raise ValueError('重复用例ID')
        ids.add(case['id'])
        c = modified(data['bases'][case['kind']], case['changes'])
        if case['reseal']:
            key, field = ('request', 'request_digest') if case['kind'] == 'vban' else ('plan', 'plan_digest')
            c[key][field] = digest_without(c[key], field)
            # 重算请求摘要后同步声明引用，仍必须通过所有独立关联判定。
            if case['kind'] == 'vban':
                c['reply']['request_digest'] = c[key][field]
        valid = all(validator.is_valid({'purpose': 'design_fixture_only', 'runtime_approved': False, 'model': c[k]})
                    for k in fields[case['kind']])
        actual = 'schema'
        if valid:
            if case['kind'] == 'parameter':
                actual = parameter_decision(c, inventory, inventory_hash)
            elif case['kind'] == 'vban':
                actual = vban_decision(c)
            else:
                actual = wing_decision(c)
        if actual != case['expect']:
            raise ValueError(f"{case['id']}: 预期{case['expect']}，实际{actual}")
        results.append({'id': case['id'], 'schema_valid': valid, 'decision': actual, 'passed': True})
    return {'scope': '局部候选结构与合成前提下的关联；不是完整资格、协议或运行证明',
            'all_passed': True, 'cases_passed': len(results), 'runtime_approved': False,
            'runtime_tests_executed': 0, 'device_tests_executed': 0,
            'tools': {n: importlib.metadata.version(n) for n in ('jsonschema', 'rfc8785')},
            'artifact_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in INPUTS},
            'results': results}


def check_bindings(staged):
    def read(name):
        if staged:
            return subprocess.check_output(['git', 'show', ':docs/contracts/c11-audio/' + name], cwd=ROOT)
        return (ROOT / name).read_bytes()
    report = json.loads(read('audio-candidate-report.json').decode('utf-8'), object_pairs_hook=unique_pairs)
    if report.get('all_passed') is not True or set(report['artifact_sha256']) != set(INPUTS):
        raise ValueError('报告状态或输入集合不符')
    for name in INPUTS:
        if hashlib.sha256(read(name)).hexdigest() != report['artifact_sha256'][name]:
            raise ValueError('报告绑定失效: ' + name)
    return {'scope': '报告输入字节绑定，不重新执行用例', 'source': 'index' if staged else 'worktree',
            'matched_bindings': len(INPUTS), 'all_passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--report', action='store_true')
    group.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged仅适用于--check-report')
    result = check_bindings(args.staged) if args.check_report else run()
    if args.report:
        (ROOT / 'audio-candidate-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                                                        encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('artifact_sha256', 'results')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
