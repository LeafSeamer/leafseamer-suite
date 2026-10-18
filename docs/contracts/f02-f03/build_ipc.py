"""仅生成内部 IPC 协议资料，不实现进程、发送或数据库。"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = 'https://leafseamer.invalid/contracts/first-loop.schema.json#/$defs/'


def ref(name):
    return {'$ref': '#/$defs/' + name}


def base(name):
    return {'$ref': BASE + name}


def obj(**fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def enum(*values):
    return {'enum': list(values)}


def nullable(value):
    return {'anyOf': [value, {'type': 'null'}]}


def array(value, maximum=256):
    return {'type': 'array', 'items': value, 'maxItems': maximum}


def build():
    ident, rev = base('Id'), base('Revision')
    d = {}
    d['IntentRef'] = obj(permit_id=ident, command_id=ident, attempt_id=ident,
                         dispatch_intent_id=ident, worker_boot_id=ident, device_session_id=ident)
    d['Coverage'] = obj(intent=ref('IntentRef'), disposition=enum('not_sent', 'in_flight', 'unknown'),
                        proof=enum('never_received', 'discarded_unconsumed', 'transport_entered', 'send_uncertain'))
    d['Coverage']['allOf'] = [
        {'if': {'properties': {'disposition': {'const': state}}},
         'then': {'properties': {'proof': enum(*proofs)}}}
        for state, proofs in [('not_sent', ['never_received', 'discarded_unconsumed']),
                              ('in_flight', ['transport_entered']), ('unknown', ['send_uncertain'])]]
    d['SendWindow'] = obj(clock_domain_id=ident, earliest_tick_ns=rev, latest_tick_ns=rev)
    bodies = {
        'HELLO': obj(module_id=ident, module_digest=base('Digest'), clock_domain_id=ident,
                     supported_ipc_versions={'type': 'array', 'items': {'const': 'ipc/0.1.0-draft.1'}, 'minItems': 1, 'maxItems': 1}),
        'HELLO_ACK': obj(selected_ipc_version={'const': 'ipc/0.1.0-draft.1'}, clock_domain_id=ident, gate_state={'const': 'closed'}),
        'OPEN_GATE': obj(barrier_id=ident, gate_token=ident, device_session_id=ident, control_epoch=ident, control_version=rev,
                         gate_revision=rev, authorization_revision=rev, clock_domain_id=ident, lease_until_tick_ns=rev),
        'OPEN_GATE_ACK': obj(gate_token=ident, gate_revision=rev, state={'const': 'open'}),
        'DISPATCH': obj(permit=base('DispatchPermit'), gate_token=ident, send_window=ref('SendWindow'),
                        request=base('CommandRequest'), parameters_schema_digest=base('Digest')),
        'SEND_REPORT': obj(report_id=ident, permit_id=ident, attempt_id=ident, dispatch_intent_id=ident,
                           device_session_id=ident, disposition=enum('not_sent', 'in_flight', 'unknown'),
                           proof=enum('never_received', 'discarded_unconsumed', 'transport_entered', 'send_uncertain'),
                           protocol_request_id=nullable(ident)),
        'EVIDENCE_CANDIDATE': obj(report_id=ident, command_id=ident, attempt_id=ident, device_session_id=ident,
                                  evidence_kind=enum('protocol_ack', 'fresh_query', 'module_observation'),
                                  observation_id=ident, payload=base('Payload')),
        'REPORT_STORED': obj(report_id=ident, record_revision=rev),
        'FENCE': obj(barrier_id=ident, operation_id=ident, control_epoch=ident, target_version=rev,
                     target_gate_revision=rev, issued_cut_revision=rev, ledger_digest=base('Digest'),
                     open_intents=array(ref('IntentRef'))),
        'FENCE_ACK': obj(ack=base('BarrierAck'), issued_cut_revision=rev, ledger_digest=base('Digest'),
                         gate_revision=rev, coverage=array(ref('Coverage'))),
        'QUERY_BARRIER': obj(barrier_id=ident, operation_id=ident),
        'CLOSE_GATE': obj(close_id=ident, reason=ident, scope=enum('device', 'controller')),
        'CLOSE_GATE_ACK': obj(close_id=ident, closed_device_ids={**array(ident), 'uniqueItems': True}),
    }
    bodies['SEND_REPORT']['allOf'] = d['Coverage']['allOf']
    response_types = {'HELLO_ACK', 'OPEN_GATE_ACK', 'FENCE_ACK', 'CLOSE_GATE_ACK'}
    for kind, body in bodies.items():
        d[kind + 'Body'] = body
        device_schema = {'type': 'null'} if kind in ('HELLO', 'HELLO_ACK', 'CLOSE_GATE_ACK') else ident
        if kind == 'CLOSE_GATE':
            device_schema = nullable(ident)
        frame = obj(ipc_version={'const': 'ipc/0.1.0-draft.1'}, type={'const': kind}, message_id=ident,
                    reply_to=ident if kind in response_types else {'type': 'null'},
                    ipc_session_id=ident, controller_boot_id=ident, worker_boot_id=ident,
                    seq={**rev, 'pattern': '^[1-9][0-9]*$'}, device_id=device_schema, body=ref(kind + 'Body'))
        if kind == 'CLOSE_GATE':
            frame['allOf'] = [{
                'if': {'properties': {'body': {'properties': {'scope': {'const': 'controller'}}}}},
                'then': {'properties': {'device_id': {'type': 'null'}}},
                'else': {'properties': {'device_id': ident}}}]
        d[kind] = frame
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'https://leafseamer.invalid/contracts/f02-f03/ipc.schema.json',
            'title': 'LeafSeamer 内部 IPC 资料，公共 draft.2 不变',
            'description': '仅结构规范；不能据此证明权限、真实屏障或持久化成立。',
            'oneOf': [ref(kind) for kind in bodies], '$defs': d}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    output = json.dumps(build(), ensure_ascii=False, indent=2) + '\n'
    path = ROOT / 'ipc.schema.json'
    if args.check:
        if path.read_text(encoding='utf-8') != output:
            raise SystemExit('IPC Schema 与人工定义源不同')
    else:
        path.write_text(output, encoding='utf-8', newline='\n')
    print('IPC Schema 生成物一致')


if __name__ == '__main__':
    main()
