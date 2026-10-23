"""从既有局部源生成完整窗口／RPC／Bundle／投影通道候选；不切换SDK权威。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import rfc8785

ROOT = Path(__file__).resolve().parent
VERSION = 'panel-channel/0.2.0-draft.1'
SCHEMA_ID = 'https://leafseamer.invalid/design/c09-panel/channel-v02.schema.json'
NONE = {'seamer.preflightRun', 'seamer.previewRecovery'}
INVALIDATION = {'controller.listDevices', 'controller.getCommandEvidence'}


def load(name): return json.loads((ROOT / name).read_bytes())
def digest(value): return hashlib.sha256(rfc8785.dumps(value)).hexdigest()
def ref(name): return {'$ref': '#/$defs/' + name}
def obj(properties): return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
def nullable(value): return {'anyOf': [value, {'type': 'null'}]}
def encoded(value): return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def build():
    schema = load('channel.schema.json'); bundle = load('bundle.schema.json')
    inputs = load('method-input.schema.json'); results = load('result.schema.json')
    methods = load('method-bindings.json')['methods']
    schema['$id'] = SCHEMA_ID; schema['title'] = '面板channel0.2合并候选；身份来源与运行实现另验'
    d = schema['$defs']
    # 只改确切协议常量，不对文档、实例字符串或任意相似版本作替换。
    for model in d.values():
        value = model.get('properties', {}).get('protocol_version')
        if value is not None:
            assert value == {'const': 'panel-channel/0.1.0-draft.1'}
            value['const'] = VERSION
    d['Id'] = copy.deepcopy(bundle['$defs']['Id'])
    d['RevisionRef'] = copy.deepcopy(bundle['$defs']['RevisionRef'])
    d['BundleRef'] = obj({'bundle_id': ref('Id'), 'manifest_digest': ref('Digest')})
    d['ActivationRef'] = obj({'activation_id': ref('Id'), 'registry_ref': ref('RevisionRef'),
                              'scope_revision': ref('Counter'), 'bundle_ref': nullable(ref('BundleRef'))})
    d['Method']['enum'] = sorted(methods)
    def add(model, name, value):
        assert name not in d[model]['properties']
        d[model]['properties'][name] = value; d[model]['required'].append(name)
    add('MethodDescriptor', 'subscription_mode', {'enum': ['none', 'projection', 'invalidation']})
    add('PortOffer', 'registry_ref', ref('RevisionRef'))
    for model in ('Active', 'Request', 'Query', 'Result', 'Intent', 'Guard'):
        add(model, 'activation_ref', ref('ActivationRef'))
    add('Session', 'activation_ref', nullable(ref('ActivationRef')))
    d['Session']['properties']['state']['enum'].insert(2, 'schema_loading')
    add('Result', 'method', ref('Method'))
    d['Reason'] = {'enum': ['ok', 'needs_host_confirmation', 'user_cancelled', 'authority_denied',
                           'activation_stale', 'schema_invalid', 'target_changed', 'conflict',
                           'not_found_or_invisible', 'source_unavailable', 'capacity_exceeded',
                           'expired', 'unknown_outcome', 'protocol_error']}
    d['Result']['properties']['reason_code'] = ref('Reason')
    d['Request']['allOf'] = []; d['Result']['allOf'] = []
    rows = []
    for method, row in sorted(methods.items()):
        input_ref = {'schema_id': inputs['$id'], 'definition': row['input_definition'], 'schema_digest': digest(inputs)}
        result_ref = {'schema_id': results['$id'], 'definition': row['result_view'], 'schema_digest': digest(results)}
        mode = 'none' if row['mode'] != 'panel_read' or method in NONE else 'invalidation' if method in INVALIDATION else 'projection'
        rows.append({'method': method, 'mode': row['mode'], 'input_schema_ref': input_ref,
                     'result_schema_ref': result_ref, 'subscription_mode': mode})
        condition = {'properties': {'method': {'const': method}}, 'required': ['method']}
        payload = obj({'schema_ref': {'const': input_ref}, 'value': {'$ref': inputs['$id'] + '#/$defs/' + row['input_definition']}})
        result = obj({'schema_ref': {'const': result_ref}, 'value': {'$ref': results['$id'] + '#/$defs/' + row['result_view']}})
        d['Request']['allOf'].append({'if': condition, 'then': {'properties': {'payload': payload}}})
        d['Result']['allOf'].append({'if': {'properties': {'method': {'const': method}, 'status': {'const': 'accepted'}},
                                          'required': ['method', 'status']}, 'then': {'properties': {'result': result}}})
    d['Result']['allOf'].append({'if': {'properties': {'status': {'not': {'const': 'accepted'}}}, 'required': ['status']},
                                'then': {'properties': {'result': {'type': 'null'}}}})
    registry = {'format_version': 'panel-method-registry/0.2.0-draft.1', 'revision': '1', 'methods': rows}
    registry_ref = {'revision': registry['revision'], 'digest': digest(registry)}
    registry_file = {'approved': False, 'runtime_approved': False, 'authority_switched': False,
                     'registry_ref': registry_ref, 'registry': registry}
    # Bundle四帧保持独立源引用，不能复制后让两份定义独立漂移。
    for name, original in [('BundleOffer', 'Offer'), ('BundleChunk', 'Chunk'), ('BundleReady', 'Ready'), ('BundleRevoke', 'Revoke')]:
        d[name] = {'$ref': bundle['$id'] + '#/$defs/' + original}
    base = {'protocol_version': {'const': VERSION}, 'public_binding': ref('PublicBinding'),
            'channel_sequence': ref('PositiveCounter'), 'activation_ref': ref('ActivationRef')}
    subscribe = copy.deepcopy(d['Request'])
    subscribe['properties']['type'] = {'const': 'panel.subscribe'}
    del subscribe['properties']['request_id']; subscribe['required'].remove('request_id')
    subscribe['properties']['subscription_id'] = ref('Id'); subscribe['required'].append('subscription_id')
    subscribe['properties']['method'] = {'enum': [r['method'] for r in rows if r['subscription_mode'] != 'none']}
    d['Subscribe'] = subscribe
    d['Unsubscribe'] = obj({**base, 'type': {'const': 'panel.unsubscribe'}, 'subscription_id': ref('Id')})
    d['ProjectionAck'] = obj({**base, 'type': {'const': 'panel.projection_ack'}, 'subscription_id': ref('Id'),
                              'projection_sequence': ref('PositiveCounter'), 'projection_digest': ref('Digest')})
    d['Projection'] = obj({**base, 'type': {'const': 'host.projection'}, 'subscription_id': ref('Id'),
                           'method': ref('Method'), 'projection_sequence': ref('PositiveCounter'),
                           'kind': {'enum': ['baseline', 'update', 'invalidated', 'gap', 'closed']},
                           'reason_code': ref('Reason'), 'value': nullable(ref('TypedValue'))})
    d['Projection']['allOf'] = []
    for row in rows:
        if row['subscription_mode'] == 'projection':
            result_ref = row['result_schema_ref']
            condition = {'properties': {'method': {'const': row['method']}, 'kind': {'enum': ['baseline', 'update']}},
                         'required': ['method', 'kind']}
            typed = obj({'schema_ref': {'const': result_ref}, 'value': {'$ref': results['$id'] + '#/$defs/' + result_ref['definition']}})
            d['Projection']['allOf'].append({'if': condition, 'then': {'properties': {'value': typed}}})
    d['Projection']['allOf'].extend([
        {'if': {'properties': {'kind': {'enum': ['invalidated', 'gap', 'closed']}}, 'required': ['kind']}, 'then': {'properties': {'value': {'type': 'null'}}}},
        {'if': {'properties': {'kind': {'enum': ['baseline', 'update']}}, 'required': ['kind']}, 'then': {'properties': {'method': {'enum': [r['method'] for r in rows if r['subscription_mode'] == 'projection']}}}},
        {'if': {'properties': {'kind': {'const': 'invalidated'}}, 'required': ['kind']}, 'then': {'properties': {'method': {'enum': sorted(INVALIDATION)}}}}])
    d['PanelFrame']['oneOf'].extend(ref(n) for n in ('BundleReady', 'Subscribe', 'Unsubscribe', 'ProjectionAck'))
    d['HostFrame']['oneOf'].extend(ref(n) for n in ('BundleOffer', 'BundleChunk', 'BundleRevoke', 'Projection'))
    return {'channel-v02.schema.json': schema, 'method-registry-v02.json': registry_file}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--check', action='store_true'); args = p.parse_args()
    for name, value in build().items():
        raw = encoded(value)
        if args.check: assert (ROOT / name).read_bytes() == raw, '生成漂移：' + name
        else: (ROOT / name).write_bytes(raw)
    print('channel0.2候选生成对账通过' if args.check else 'channel0.2候选已生成')


if __name__ == '__main__': main()
