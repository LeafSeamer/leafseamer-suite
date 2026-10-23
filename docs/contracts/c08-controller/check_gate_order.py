"""只运行最终发送的有限参考顺序；不连接数据库、IPC或设备。"""
import argparse
import copy
import hashlib
import json
import subprocess
from dataclasses import replace
from itertools import permutations
from pathlib import Path
from gate_order_model import Gate, Rejected

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUTS = [HERE/n for n in ('GATE_ORDER.md', 'gate_order_model.py', 'check_gate_order.py',
    'PROTECTION_OUTBOX.md', 'protection-outbox.sql', 'BARRIER_ATTEMPTS.md')]
INPUTS += [HERE.parent/'df03-service/ipc.schema.json', ROOT/'docs/rebirth-f02-f03-design.md']


def run():
    checks = []
    def check(name, actual, expected=True):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(name=name, expected=copy.deepcopy(expected), observed=copy.deepcopy(actual)))
    def denied(name, operation, reason):
        try:
            operation()
        except Rejected as error:
            check(name, str(error), reason)
        else:
            raise AssertionError(name+': 应拒绝')
    def closed():
        gate = Gate()
        gate.protect('target', 1)
        frame = gate.close('target', 1)
        gate.deliver(); gate.store_ack(frame)
        return gate
    def recovered():
        gate = closed(); gate.resources_clear = True; gate.recover('recovery.1')
        return gate
    def installed():
        gate = recovered(); frame = gate.fence(); gate.deliver(); gate.store_ack(frame)
        return gate
    def opened():
        gate = installed(); frame = gate.open(gate.plan_open(100)); gate.deliver(); gate.store_ack(frame)
        return gate

    g = Gate(); check('握手默认关闭', (g.worker_open, g.ready), (False, False))
    denied('握手不授开放权', lambda: g.plan_open(100), 'open_precondition')
    g.protect('target', 1); f = g.close('target', 1)
    check('IPC入流不等worker关闭确认', g.receipts, [])
    denied('没有接收原件不得制造ACK', lambda: g.store_ack(f), 'no_worker_receipt')
    g.deliver(); g.store_ack(f)
    denied('关闭ACK不清资源', lambda: g.recover('r'), 'recovery_precondition')
    g.resources_clear = True; g.recover('r')
    check('恢复提交仍未ready', g.ready, False)
    denied('恢复不跳过完整屏障', lambda: g.plan_open(100), 'open_precondition')
    f = g.fence(); g.deliver(); g.store_ack(f)
    f = g.open(g.plan_open(100)); g.deliver()
    denied('worker已OPEN但未存ACK不发许可', lambda: g.dispatch('p'), 'not_ready')
    g.store_ack(f); g.dispatch('p'); g.deliver()
    check('正常闭环只进入一次设备传输', g.effects, ['p'])
    g.dispatch('p'); denied('同permit不得再次进入传输', lambda: g.deliver(), 'permit_consumed')
    check('重复permit无新增副作用', g.effects, ['p'])

    g = Gate(); g.protect('target', 1); g.protect('target', 2)
    denied('未入流旧尝试淘汰', lambda: g.close('target', 1), 'stale_attempt')
    check('淘汰不消耗流序号', g.next_seq, 1)
    denied('跳号不能取代原尝试', lambda: g.protect('target', 4), 'attempt_successor')
    g = Gate(); g.protect('target', 1); old = g.close('target', 1)
    g.protect('target', 2); new = g.close('target', 2)
    g.deliver(); g.store_ack(old); g.resources_clear = True
    denied('已入流旧ACK不代新尝试', lambda: g.recover('r'), 'fresh_close_required')
    g.deliver(); g.store_ack(new); g.recover('r')
    check('最新关闭可恢复但不ready', (g.protected, g.ready), (False, False))

    g = installed(); plan = g.plan_open(100); g.protect('target', 2)
    denied('未入流旧开放计划淘汰', lambda: g.open(plan), 'protected')
    check('保护后无旧OPEN入流', [f.kind for f in g.wire], [])
    g = installed(); old_open = g.open(g.plan_open(100)); g.protect('target', 2); g.close('target', 2)
    g.deliver(); check('已入流OPEN的传播窗口如实保留', g.worker_open)
    denied('传播窗口不接纳新许可', lambda: g.dispatch('p'), 'not_ready')
    denied('迟到OPEN_ACK不得重新ready', lambda: g.store_ack(old_open), 'stale_ack')
    g.deliver(); check('后续关闭最终到达worker', g.worker_open, False)
    g = installed(); plan = g.plan_open(100); g.serial += 1
    denied('相关快照更新使开放计划过期', lambda: g.open(plan), 'stale_open')
    g = installed(); plan = g.plan_open(100); g.resources_clear = False
    denied('资源失效后不创建开放计划', lambda: g.plan_open(100), 'open_precondition')
    denied('资源失效后旧开放计划不入流', lambda: g.open(plan), 'protected')
    g = recovered(); old_fence = g.fence(); g.fence(); g.deliver()
    denied('旧屏障ACK不提供新开放资格', lambda: g.store_ack(old_fence), 'stale_ack')
    g = installed(); f = g.open(g.plan_open(100)); g.deliver(); g.resources_clear = False
    denied('ACK前资源事实变化不发布ready', lambda: g.store_ack(f), 'open_ack_precondition')

    g = opened(); cached = next(f for f in g.receipts if f.kind == 'close')
    duplicate = g.enqueue('close', cached.key, cached.body); g.deliver()
    check('逻辑关闭重复只回历史ACK不再次关闸', g.worker_open)
    check('重复ACK仍指原逻辑正文', duplicate.body, cached.body)
    g.enqueue('close', cached.key, ('changed', 99))
    denied('同close_id异正文关闭会话', lambda: g.deliver(), 'close_content_conflict')
    check('协议故障不可保留开放', (g.worker_live, g.worker_open), (False, False))

    g = opened(); g.protect('target', 2); g.resources_clear = True
    denied('恢复用过的ACK不可重新恢复', lambda: g.recover('recovery.2'), 'fresh_close_required')
    new = g.close('target', 2); g.deliver(); g.store_ack(new); g.recover('recovery.2')
    f = g.fence(); g.deliver(); g.store_ack(f); g.open(g.plan_open(100)); g.deliver()
    check('重新关闭和新屏障允许新OPEN', g.worker_open)
    g = Gate()
    for target in ('a', 'b'):
        g.protect(target, 1); frame = g.close(target, 1); g.deliver(); g.store_ack(frame)
    g.resources_clear = True; g.recover('both')
    g.protect('a', 2); frame = g.close('a', 2); g.deliver(); g.store_ack(frame)
    denied('多目标不能漏掉已消费的另一关闭', lambda: g.recover('again'), 'fresh_close_required')
    g.protect('b', 2); frame = g.close('b', 2); g.deliver(); g.store_ack(frame); g.recover('again')
    check('全部目标有新关闭才允许恢复', g.protected, False)

    g = opened(); emergency = g.fail_storage()
    check('数据库故障立即撤销本地ready', g.ready, False)
    denied('故障时禁止普通发送', lambda: g.dispatch('p'), 'not_ready')
    denied('故障时禁止OPEN', lambda: g.open(('session.1', 0, 'b', 1, 100, 'r')), 'protected')
    g.deliver(); check('无数据库仍可紧急关闸', g.worker_open, False)
    denied('故障不能制造durable ACK', lambda: g.store_ack(emergency), 'storage_failed')
    g = installed(); f = g.open(g.plan_open(100)); g.deliver(); g.fail_storage()
    denied('OPEN_ACK与存储故障竞争不发布ready', lambda: g.store_ack(f), 'storage_failed')

    g = opened(); g.lose_cache()
    denied('缓存丢失不得继续原会话', lambda: g.receive(replace(cached, seq=g.worker_next)), 'session_closed')
    g = opened(); g.dispatch('p'); g.restart('session.2')
    check('已退役后重启不重放队列和许可', (g.wire, g.effects, g.ready), ([], [], False))
    denied('旧会话ACK不能恢复新实例', lambda: g.store_ack(cached), 'ack_origin')
    g = opened(); frame = g.dispatch('p')
    denied('输入缺号关闭会话', lambda: g.receive(replace(frame, seq=frame.seq+1)), 'sequence_gap')
    check('缺号不能进入设备传输', (g.effects, g.worker_open), ([], False))
    g = opened(); frame = g.dispatch('p')
    denied('旧会话帧不能进入新会话', lambda: g.receive(replace(frame, session='old')), 'wrong_session')
    g = installed(); f = g.open(g.plan_open(100)); g.deliver()
    denied('ACK到期等号不发布ready', lambda: g.store_ack(f, 100), 'open_ack_precondition')
    g = opened(); g.dispatch('p')
    denied('发送到期等号不进传输', lambda: g.deliver(100), 'worker_closed')
    denied('Controller到期等号不投递新许可', lambda: g.dispatch('new', 100), 'not_ready')
    old = next(f for f in g.receipts if f.kind == 'open')
    g.enqueue('open', old.key, (old.body[0], old.body[1], 200))
    denied('到期后迟到续约不复活原闸', lambda: g.deliver(101), 'worker_open_binding')

    # 原机器字段是独立对照，模型的简化元组绝不是新的线上结构。
    definitions = json.loads((HERE.parent/'df03-service/ipc.schema.json').read_bytes())['$defs']
    bodies = {name.split('__')[-1]: schema for name,schema in definitions.items()
              if name.endswith(('CLOSE_GATEBody','CLOSE_GATE_ACKBody','OPEN_GATEBody','OPEN_GATE_ACKBody'))}
    check('关闭正文保持原三字段', sorted(bodies['CLOSE_GATEBody']['required']), ['close_id','reason','scope'])
    check('关闭ACK保持原两字段', sorted(bodies['CLOSE_GATE_ACKBody']['required']), ['close_id','closed_device_ids'])
    check('开放仍要求三类完整快照', {'run_deny_snapshot','command_deny_snapshot','reference_time_snapshot'} <= set(bodies['OPEN_GATEBody']['required']))
    check('开放ACK仍绑定token与修订', {'gate_token','gate_revision','reference_time_snapshot_ref'} <= set(bodies['OPEN_GATE_ACKBody']['required']))

    # 手工oracle：只有dispatch入流严格早于protect，可靠流前缀中的许可才可能进入设备。
    results = []
    for order in permutations(('dispatch', 'protect', 'drain')):
        g = opened()
        for event in order:
            if event == 'dispatch':
                try: g.dispatch('p')
                except Rejected as e: assert str(e) == 'not_ready'
            elif event == 'protect':
                g.protect('target', 2); g.close('target', 2)
            else:
                while g.wire: g.deliver()
        while g.wire: g.deliver()
        expected = ['p'] if order.index('dispatch') < order.index('protect') else []
        check('有序前缀排列:'+','.join(order), g.effects, expected)
        check('排列终态关闭:'+','.join(order), (g.worker_open, g.ready), (False, False))
        results.append(list(order))
    return checks, results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report: parser.error('--staged需配合--check-report')
    path = HERE/'gate-order-report.json'
    if args.check_report:
        read = (lambda f: subprocess.check_output(['git', 'show', ':'+f.relative_to(ROOT).as_posix()], cwd=ROOT)) if args.staged else Path.read_bytes
        data = json.loads(read(path))
        assert set(data['inputs']) == {f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS: assert data['inputs'][f.relative_to(ROOT).as_posix()] == hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True, matched_bindings=len(INPUTS))))
    else:
        checks, orders = run()
        data = dict(all_passed=True, approved=False, cases_passed=len(checks), explored_orderings=orders,
                    scope='单设备最终有序出口有限参考模型', runtime_tests_executed=0, device_tests_executed=0,
                    concurrency_tests_executed=0, disk_crash_tests_executed=0, checks=checks,
                    inputs={f.relative_to(ROOT).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if args.report: path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs','explored_orderings')},ensure_ascii=False))
