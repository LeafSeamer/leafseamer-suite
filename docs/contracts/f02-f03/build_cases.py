"""人工编排的 IPC 正反例和故障顺序；不从 Schema 推导预期结果。"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path

import rfc8785

ROOT = Path(__file__).resolve().parent
DIGEST = 'sha256:' + '1' * 64


def frame(kind, body, device='device-demo'):
    return dict(ipc_version='ipc/0.1.0-draft.1', type=kind, message_id='m-' + kind.lower(),
                reply_to='m-request' if kind.endswith('_ACK') else None,
                ipc_session_id='ipc-demo', controller_boot_id='cb-demo', worker_boot_id='wb-demo',
                seq='1', device_id=device, body=body)


def build():
    intent = dict(permit_id='permit-1', command_id='cmd-1', attempt_id='attempt-1',
                  dispatch_intent_id='intent-1', worker_boot_id='wb-demo', device_session_id='ds-demo')
    old = dict(intent, permit_id='permit-2', command_id='cmd-2', attempt_id='attempt-2',
               dispatch_intent_id='intent-2', worker_boot_id='wb-old', device_session_id='ds-old')
    ledger = [intent, old]
    ledger_digest = 'sha256:' + hashlib.sha256(rfc8785.dumps(ledger)).hexdigest()
    request = dict(context_id='context-demo', idempotency_key='key-demo', device_id='device-demo',
                   action_id='obs.program_scene.set', capability_version='1.0.0-draft.2',
                   parameters={'scene_ref': {'collection_ref': 'collection-demo', 'scene_id': 'scene-demo', 'catalog_revision': '2'}},
                   expected_control={'epoch': 'epoch-demo', 'version': '7'}, origin='manual',
                   required_completion='effect_verified', preconditions=[],
                   dispatch={'mode': 'immediate', 'max_queue_ms': 1000}, evidence_timeout_ms=2000)
    content = {k: v for k, v in request.items() if k not in ('context_id', 'idempotency_key', 'correlation_id')}
    content_digest = 'sha256:' + hashlib.sha256(rfc8785.dumps(content)).hexdigest()
    permit = dict(permit_id='permit-1', command_id='cmd-1', attempt_id='attempt-1', dispatch_intent_id='intent-1',
                  controller_boot_id='cb-demo', worker_boot_id='wb-demo', device_session_id='ds-demo',
                  control_epoch='epoch-demo', control_version='7', authorization_revision='3', origin='manual',
                  grant_revision=None, arm_generation=None, gate_revision='5',
                  deadline_policy={'mode': 'immediate', 'max_queue_ms': 1000}, content_digest=content_digest)
    messages = [
        frame('HELLO', dict(module_id='obs-demo', module_digest=DIGEST, clock_domain_id='clock-demo',
                           supported_ipc_versions=['ipc/0.1.0-draft.1']), None),
        frame('HELLO_ACK', dict(selected_ipc_version='ipc/0.1.0-draft.1', clock_domain_id='clock-demo', gate_state='closed'), None),
        frame('OPEN_GATE', dict(barrier_id='installed-barrier', gate_token='gate-demo', device_session_id='ds-demo', control_epoch='epoch-demo',
                               control_version='7', gate_revision='5', authorization_revision='3',
                               clock_domain_id='clock-demo', lease_until_tick_ns='1000000000')),
        frame('OPEN_GATE_ACK', dict(gate_token='gate-demo', gate_revision='5', state='open')),
        frame('DISPATCH', dict(permit=permit, gate_token='gate-demo',
                              send_window=dict(clock_domain_id='clock-demo', earliest_tick_ns='100', latest_tick_ns='900'),
                              request=request, parameters_schema_digest=DIGEST)),
        frame('SEND_REPORT', dict(report_id='report-demo', permit_id='permit-1', attempt_id='attempt-1',
                                 dispatch_intent_id='intent-1', device_session_id='ds-demo', disposition='in_flight',
                                 proof='transport_entered', protocol_request_id='protocol-demo')),
        frame('EVIDENCE_CANDIDATE', dict(report_id='report-evidence', command_id='cmd-1', attempt_id='attempt-1',
                                       device_session_id='ds-demo', evidence_kind='fresh_query', observation_id='obs-1',
                                       payload={'scene_uuid': 'scene-demo'})),
        frame('REPORT_STORED', dict(report_id='report-evidence', record_revision='11')),
        frame('FENCE', dict(barrier_id='barrier-demo', operation_id='op-demo', control_epoch='epoch-demo', target_version='8',
                           target_gate_revision='6', issued_cut_revision='12', ledger_digest=ledger_digest, open_intents=ledger)),
        frame('FENCE_ACK', dict(ack=dict(barrier_id='barrier-demo', operation_id='op-demo', device_id='device-demo',
                                       controller_boot_id='cb-demo', worker_boot_id='wb-demo', control_epoch='epoch-demo',
                                       installed_version='8', discarded_permit_ids=['permit-1'], in_flight_command_ids=[],
                                       unresolved_command_ids=['cmd-2'], all_write_exits_fenced=True),
                               issued_cut_revision='12', ledger_digest=ledger_digest, gate_revision='6',
                               coverage=[dict(intent=intent, disposition='not_sent', proof='never_received'),
                                         dict(intent=old, disposition='unknown', proof='send_uncertain')])),
        frame('QUERY_BARRIER', dict(barrier_id='barrier-demo', operation_id='op-demo')),
        frame('CLOSE_GATE', dict(close_id='close-demo', reason='storage_fault', scope='controller'), None),
        frame('CLOSE_GATE_ACK', dict(close_id='close-demo', closed_device_ids=['device-demo']), None),
    ]
    lookup = {m['type']: m for m in messages}
    lookup['FENCE_ACK']['reply_to'] = lookup['FENCE']['message_id']
    frames = [dict(case_id='IP-' + m['type'], valid=True, frame=m) for m in messages]

    def bad_frame(name, kind, change):
        value = deepcopy(lookup[kind]); change(value)
        frames.append(dict(case_id=name, valid=False, frame=value))

    bad_frame('IP-extra-field', 'FENCE', lambda m: m['body'].update(ignore_unknown=True))
    bad_frame('IP-fake-durable', 'EVIDENCE_CANDIDATE', lambda m: m['body'].update(durable=True))
    bad_frame('IP-incomplete-exits', 'FENCE_ACK', lambda m: m['body']['ack'].update(all_write_exits_fenced=False))
    bad_frame('IP-zero-seq', 'DISPATCH', lambda m: m.update(seq='0'))
    bad_frame('IP-unknown-version', 'HELLO', lambda m: m.update(ipc_version='ipc/9'))
    bad_frame('IP-close-scope', 'CLOSE_GATE', lambda m: m.update(device_id='device-demo'))
    bad_frame('IP-missing-reply', 'OPEN_GATE_ACK', lambda m: m.update(reply_to=None))
    bad_frame('IP-false-not-sent', 'SEND_REPORT', lambda m: m['body'].update(disposition='not_sent', proof='transport_entered'))
    bad_frame('IP-empty-coverage-item', 'FENCE_ACK', lambda m: m['body']['coverage'].append({}))

    fence, ack = lookup['FENCE'], lookup['FENCE_ACK']
    barriers = [dict(case_id='BK-complete', expected_error=None, fence=fence, ack=ack)]

    def bad_barrier(name, error, change):
        f, a = deepcopy(fence), deepcopy(ack); change(f, a)
        barriers.append(dict(case_id=name, expected_error=error, fence=f, ack=a))

    bad_barrier('BK-missing', 'coverage_set', lambda f, a: a['body']['coverage'].pop())
    bad_barrier('BK-duplicate', 'coverage_duplicate', lambda f, a: a['body']['coverage'].append(deepcopy(a['body']['coverage'][0])))
    bad_barrier('BK-worker-mismatch', 'frame_identity', lambda f, a: a.update(worker_boot_id='wb-other'))
    bad_barrier('BK-session-mismatch', 'frame_identity', lambda f, a: a.update(ipc_session_id='ipc-other'))
    bad_barrier('BK-ack-operation', 'ack_binding', lambda f, a: a['body']['ack'].update(operation_id='op-other'))
    bad_barrier('BK-digest', 'ledger_digest', lambda f, a: a['body'].update(ledger_digest=DIGEST))
    bad_barrier('BK-cut', 'cut_revision', lambda f, a: a['body'].update(issued_cut_revision='13'))
    bad_barrier('BK-gate', 'gate_revision', lambda f, a: a['body'].update(gate_revision='4'))
    bad_barrier('BK-intent-replaced', 'intent_identity', lambda f, a: a['body']['coverage'][0]['intent'].update(attempt_id='attempt-other'))
    def false_unsent(f, a):
        a['body']['coverage'][1].update(disposition='not_sent', proof='never_received')
        a['body']['ack'].update(discarded_permit_ids=['permit-1', 'permit-2'], unresolved_command_ids=[])
    bad_barrier('BK-old-worker-unsent', 'old_worker_unsent', false_unsent)
    bad_barrier('BK-lost-unknown-list', 'projection', lambda f, a: a['body']['ack'].update(unresolved_command_ids=[]))
    bad_barrier('BK-duplicate-list', 'projection', lambda f, a: a['body']['ack'].update(discarded_permit_ids=['permit-1', 'permit-1']))

    gate = lookup['OPEN_GATE']['body']
    dispatch_checks = [dict(case_id='DG-open', expected_error=None, frame=lookup['DISPATCH'], gate=gate,
                           gate_open=True, now_tick_ns='500', consumed=[], storage_healthy=True)]
    for name, error, field, value in [
        ('DG-deadline-equal', 'deadline', 'now_tick_ns', '900'),
        ('DG-too-early', 'deadline', 'now_tick_ns', '99'),
        ('DG-closed', 'gate_closed', 'gate_open', False),
        ('DG-consumed', 'permit_consumed', 'consumed', ['permit-1']),
        ('DG-storage', 'storage_fault', 'storage_healthy', False),
    ]:
        c = deepcopy(dispatch_checks[0]); c.update(case_id=name, expected_error=error); c[field] = value; dispatch_checks.append(c)
    for name, error, field, value in [
        ('DG-old-token', 'gate_binding', 'gate_token', 'old-token'),
        ('DG-other-clock', 'clock_domain', 'clock_domain_id', 'other-clock'),
        ('DG-expired-lease', 'lease_expired', 'lease_until_tick_ns', '500'),
        ('DG-old-session', 'gate_binding', 'device_session_id', 'ds-old'),
    ]:
        c = deepcopy(dispatch_checks[0]); c.update(case_id=name, expected_error=error); c['gate'][field] = value; dispatch_checks.append(c)
    for name, error, change in [
        ('DG-changed-content', 'content_digest', lambda b: b['request'].update(evidence_timeout_ms=3000)),
        ('DG-other-device', 'request_binding', lambda b: b['request'].update(device_id='other-device')),
        ('DG-old-control', 'request_binding', lambda b: b['request']['expected_control'].update(version='6')),
        ('DG-extended-deadline', 'request_binding', lambda b: b['permit']['deadline_policy'].update(max_queue_ms=2000)),
    ]:
        c = deepcopy(dispatch_checks[0]); c.update(case_id=name, expected_error=error); change(c['frame']['body']); dispatch_checks.append(c)

    traces = []
    def trace(name, valid, events):
        traces.append(dict(case_id=name, valid=valid, events=events.split()))
    trace('TR-fence-first', True, 'accept_commit intent_commit dispatch fence_commit fence_apply fence_ack effective_commit open_gate open_ack ready_commit manual_send')
    trace('TR-send-first-clear', True, 'accept_commit intent_commit dispatch send fence_commit fence_apply fence_ack effective_commit open_gate open_ack ready_commit resource_clear manual_send')
    trace('TR-no-intent', False, 'accept_commit dispatch send')
    trace('TR-double-permit', False, 'accept_commit intent_commit dispatch send send')
    trace('TR-send-after-fence', False, 'accept_commit intent_commit dispatch fence_commit fence_apply send')
    trace('TR-effective-without-ack', False, 'fence_commit effective_commit')
    trace('TR-open-before-commit', False, 'fence_commit fence_apply fence_ack open_gate')
    trace('TR-held-resource', False, 'accept_commit intent_commit dispatch send fence_commit fence_apply fence_ack effective_commit open_gate open_ack ready_commit manual_send')
    trace('TR-unknown-resolution-paused', False, 'accept_commit intent_commit dispatch unknown resolve automatic_continue')
    trace('TR-unknown-resolution-observe', True, 'accept_commit intent_commit dispatch unknown resolve')
    trace('TR-restart-no-replay', True, 'accept_commit intent_commit crash restart unknown old_writer_dead new_worker')
    trace('TR-restart-replay', False, 'accept_commit intent_commit crash restart replay_device')
    trace('TR-second-writer', False, 'worker_lost new_worker')
    trace('TR-safe-replacement', True, 'worker_lost old_writer_dead new_worker')
    trace('TR-store-fault-before-close-window', True, 'accept_commit intent_commit dispatch storage_fault send close_apply unknown')
    trace('TR-store-fault-new-dispatch', False, 'accept_commit intent_commit storage_fault dispatch')
    trace('TR-send-after-close', False, 'accept_commit intent_commit dispatch storage_fault close_apply send')
    trace('TR-outbox-repeat', True, 'outbox_commit publish replay_event')
    trace('TR-event-without-commit', False, 'publish')
    trace('TR-ack-db-failed', True, 'fence_commit fence_apply fence_ack storage_fault')
    trace('TR-close-no-database', True, 'storage_fault close_apply')
    trace('TR-close-late-open', False, 'fence_commit fence_apply fence_ack effective_commit close_apply open_gate')
    trace('TR-close-old-fence', False, 'fence_commit fence_apply fence_ack effective_commit close_apply fence_apply open_gate')
    return dict(frames=frames, barriers=barriers, dispatch_checks=dispatch_checks, traces=traces)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true'); args = parser.parse_args()
    output = json.dumps(build(), ensure_ascii=False, indent=2) + '\n'
    path = ROOT / 'cases.json'
    if args.check:
        if path.read_text(encoding='utf-8') != output:
            raise SystemExit('IPC 人工案例与生成物不一致')
    else:
        path.write_text(output, encoding='utf-8', newline='\n')
    print('IPC 人工案例一致')


if __name__ == '__main__':
    main()
