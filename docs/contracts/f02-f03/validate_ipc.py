"""离线检查 IPC 形状、有限快照约束与人工顺序；不启动 IPC／SQLite／设备。"""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
import rfc8785

ROOT = Path(__file__).resolve().parent


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def barrier_error(f, a):
    """只检查给定的完整屏障快照，不证明数据来源或真实出口覆盖。"""
    x, y = f['body'], a['body']; ack = y['ack']
    for field in ('ipc_session_id', 'controller_boot_id', 'worker_boot_id', 'device_id'):
        if f[field] != a[field]: return 'frame_identity'
    if a['reply_to'] != f['message_id']: return 'reply_binding'
    for field in ('controller_boot_id', 'worker_boot_id', 'device_id'):
        if ack[field] != f[field]: return 'ack_binding'
    for field in ('barrier_id', 'operation_id', 'control_epoch'):
        if ack[field] != x[field]: return 'ack_binding'
    if ack['installed_version'] != x['target_version']: return 'ack_binding'
    if y['gate_revision'] != x['target_gate_revision']: return 'gate_revision'
    if y['issued_cut_revision'] != x['issued_cut_revision']: return 'cut_revision'
    ordered = sorted(x['open_intents'], key=lambda i: i['permit_id'])
    digest = 'sha256:' + hashlib.sha256(rfc8785.dumps(ordered)).hexdigest()
    if x['ledger_digest'] != digest or y['ledger_digest'] != digest: return 'ledger_digest'
    keys = [i['permit_id'] for i in x['open_intents']]
    covered = [i['intent']['permit_id'] for i in y['coverage']]
    if len(set(keys)) != len(keys): return 'ledger_duplicate'
    if len(set(covered)) != len(covered): return 'coverage_duplicate'
    if set(keys) != set(covered): return 'coverage_set'
    by_key = {i['permit_id']: i for i in x['open_intents']}
    projected = {'discarded_permit_ids': set(), 'in_flight_command_ids': set(), 'unresolved_command_ids': set()}
    for row in y['coverage']:
        intent = row['intent']
        if intent != by_key[intent['permit_id']]: return 'intent_identity'
        if intent['worker_boot_id'] != f['worker_boot_id'] and row['disposition'] != 'unknown':
            return 'old_worker_unsent'
        name, value = {
            'not_sent': ('discarded_permit_ids', intent['permit_id']),
            'in_flight': ('in_flight_command_ids', intent['command_id']),
            'unknown': ('unresolved_command_ids', intent['command_id']),
        }[row['disposition']]
        projected[name].add(value)
    for field, expected in projected.items():
        if set(ack[field]) != expected or len(set(ack[field])) != len(ack[field]): return 'projection'
    return None


def dispatch_error(case):
    """给定可信当前门控快照的静态比较；不验证真实授权及设备前提。"""
    frame, gate = case['frame'], case['gate']; body = frame['body']; p = body['permit']; w = body['send_window']
    if not case['storage_healthy']: return 'storage_fault'
    if not case['gate_open']: return 'gate_closed'
    if p['permit_id'] in case['consumed']: return 'permit_consumed'
    for field in ('controller_boot_id', 'worker_boot_id'):
        if p[field] != frame[field]: return 'frame_identity'
    request = body['request']
    if (request['device_id'] != frame['device_id'] or request['origin'] != p['origin'] or
        request['expected_control'] != {'epoch': p['control_epoch'], 'version': p['control_version']} or
        request['dispatch'] != p['deadline_policy']): return 'request_binding'
    if request['origin'] == 'automation':
        for field in ('grant_revision', 'arm_generation'):
            if request['run_binding'][field] != p[field]: return 'request_binding'
    content = {k: v for k, v in request.items() if k not in ('context_id', 'idempotency_key', 'correlation_id')}
    digest = 'sha256:' + hashlib.sha256(rfc8785.dumps(content)).hexdigest()
    if p['content_digest'] != digest: return 'content_digest'
    if body['gate_token'] != gate['gate_token']: return 'gate_binding'
    for field in ('device_session_id', 'control_epoch', 'control_version', 'gate_revision', 'authorization_revision'):
        if p[field] != gate[field]: return 'gate_binding'
    if w['clock_domain_id'] != gate['clock_domain_id']: return 'clock_domain'
    now = int(case['now_tick_ns'])
    if now >= int(gate['lease_until_tick_ns']): return 'lease_expired'
    if not int(w['earliest_tick_ns']) <= now < int(w['latest_tick_ns']): return 'deadline'
    return None


def trace_valid(events):
    """单设备、一个旧尝试的审阅模型；不模拟 OS 调度、SQLite 或设备网络。"""
    accepted = intent = dispatched = sent = held = False
    fence_pending = fenced = acked = effective = opened = open_ack = ready = False
    fault = closed = paused = dead = crashed = outbox = protection_latched = False
    for e in events:
        if e == 'accept_commit':
            if fault or crashed: return False
            accepted = True
        elif e == 'intent_commit':
            if not accepted or fault or closed or crashed: return False
            intent = True
        elif e == 'dispatch':
            if not intent or fault or closed or crashed or dispatched: return False
            dispatched = True
        elif e == 'send':
            # 存储故障已被主服务发现、出口尚未关闸的传播窗口允许旧许可已发。
            if not dispatched or sent or closed or crashed: return False
            sent = held = True
        elif e == 'fence_commit':
            if fault or crashed: return False
            fence_pending = True; ready = False
        elif e == 'fence_apply':
            if not fence_pending or fenced: return False
            fenced = closed = True; dispatched = False; protection_latched = False
        elif e == 'fence_ack':
            if not fenced: return False
            acked = True
        elif e == 'effective_commit':
            if not acked or fault or crashed: return False
            effective = True
        elif e == 'open_gate':
            if not effective or fault or crashed or protection_latched: return False
            opened = True; closed = False
        elif e == 'open_ack':
            if not opened: return False
            open_ack = True
        elif e == 'ready_commit':
            if not open_ack or fault or crashed: return False
            ready = True
        elif e == 'manual_send':
            if not ready or closed or held or fault or crashed: return False
        elif e == 'storage_fault': fault = True; paused = True
        elif e == 'close_apply': closed = True; ready = False; protection_latched = True
        elif e == 'unknown': held = paused = True
        elif e == 'resolve':
            if not paused: return False
            # 迟到结果不清暂停，不假装资源已释放。
        elif e == 'resource_clear': held = False
        elif e == 'automatic_continue':
            if paused or fault or crashed: return False
        elif e == 'worker_lost': dead = False; ready = False; paused = True
        elif e == 'old_writer_dead': dead = True
        elif e == 'new_worker':
            if not dead: return False
            closed = True; ready = False; dispatched = False; dead = False
        elif e == 'crash': crashed = True; ready = False; paused = True
        elif e == 'restart':
            if not crashed: return False
            crashed = False; closed = True; ready = False; dispatched = False; dead = False
        elif e == 'outbox_commit':
            if fault or crashed: return False
            outbox = True
        elif e in ('publish', 'replay_event'):
            if not outbox: return False
        elif e == 'replay_device': return False
        else: raise AssertionError('未知模型事件：' + e)
    return True


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--report', action='store_true'); args = parser.parse_args()
    for name in ('build_ipc.py', 'build_cases.py'):
        subprocess.run([sys.executable, str(ROOT / name), '--check'], check=True)
    schema = load(ROOT / 'ipc.schema.json'); public = load(ROOT.parent / 'first-loop.schema.json')
    registry = Registry().with_resources([(s['$id'], Resource.from_contents(s)) for s in (schema, public)])
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    # 逐一定义解析引用，不只验证被正例覆盖的分支；注册表不会从网络获取其他引用。
    def check_refs(node, resolver):
        if isinstance(node, dict):
            if '$ref' in node: resolver.lookup(node['$ref'])
            for child in node.values(): check_refs(child, resolver)
        elif isinstance(node, list):
            for child in node: check_refs(child, resolver)
    check_refs(schema, registry.resolver(schema['$id']))
    cases = load(ROOT / 'cases.json'); seen = set()
    for group in cases.values():
        for case in group:
            if case['case_id'] in seen: raise AssertionError('用例 ID 重复')
            seen.add(case['case_id'])
    for case in cases['frames']:
        errors = list(validator.iter_errors(case['frame']))
        if bool(not errors) != case['valid']:
            raise AssertionError(case['case_id'] + '：' + str([e.message for e in errors]))
    kinds = {c['frame']['type'] for c in cases['frames'] if c['valid']}
    if len(kinds) != len(schema['oneOf']): raise AssertionError('缺少消息正例')
    for case in cases['barriers']:
        validator.validate(case['fence']); validator.validate(case['ack'])
        actual = barrier_error(case['fence'], case['ack'])
        if actual != case['expected_error']: raise AssertionError((case['case_id'], actual))
    for case in cases['dispatch_checks']:
        validator.validate(case['frame'])
        actual = dispatch_error(case)
        if actual != case['expected_error']: raise AssertionError((case['case_id'], actual))
    for case in cases['traces']:
        if trace_valid(case['events']) != case['valid']: raise AssertionError(case['case_id'])
    files = sorted([p for p in ROOT.iterdir() if p.is_file() and p.name != 'validation-report.json'] +
                   [ROOT.parent / 'first-loop.schema.json', ROOT.parent.parent / 'rebirth-f02-f03-design.md'])
    report = dict(scope='仅离线结构、快照约束和人工顺序检查；非 IPC、SQLite、设备或故障注入运行验收',
                  public_protocol='1.0.0-draft.2', internal_protocol='ipc/0.1.0-draft.1',
                  message_types=len(kinds), frame_positive=sum(c['valid'] for c in cases['frames']),
                  frame_negative=sum(not c['valid'] for c in cases['frames']),
                  barrier_cases=len(cases['barriers']), dispatch_gate_cases=len(cases['dispatch_checks']),
                  symbolic_traces=len(cases['traces']), runtime_acceptance_cases_executed=0,
                  versions={'python': platform.python_version(), 'jsonschema': version('jsonschema'), 'rfc8785': version('rfc8785')},
                  input_sha256={str(p.relative_to(ROOT.parent.parent)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                  all_passed=True)
    if args.report:
        (ROOT / 'validation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'input_sha256'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
