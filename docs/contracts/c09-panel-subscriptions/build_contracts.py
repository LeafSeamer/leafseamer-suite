"""生成订阅候选Schema及五个HTTP操作；不是业务服务。"""
import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urldefrag, urljoin

HERE = Path(__file__).resolve().parent
PANEL = HERE.parent / 'c09-panel'
SID = 'https://leafseamer.invalid/design/c09-panel-subscriptions/subscriptions.schema.json'
VERSION = 'panel-subscriptions/0.1.0-draft.1'
CHANNEL = json.loads((PANEL / 'channel-v02.schema.json').read_text('utf-8'))
CID = CHANNEL['$id']
METHODS = json.loads((PANEL / 'method-registry-v02.json').read_text('utf-8'))['registry']['methods']
SUBSCRIBABLE = [m for m in METHODS if m['subscription_mode'] != 'none']
PREFIX = '/api/v1/panel-sessions/{session_id}/subscriptions'
ROUTES = [
    ('post', '', 'createPanelSubscription', 'CreateSubscription', 'SubscriptionRecord', ['201', '200']),
    ('get', '/{subscription_id}', 'getPanelSubscription', None, 'SubscriptionRecord', ['200']),
    ('get', '/{subscription_id}/frames', 'getPanelProjectionFrames', None, 'ProjectionBatch', ['200']),
    ('post', '/{subscription_id}/ack', 'acknowledgePanelProjection', 'AcknowledgeProjection', 'SubscriptionRecord', ['200']),
    ('post', '/{subscription_id}/close', 'closePanelSubscription', 'CloseSubscription', 'SubscriptionRecord', ['202', '200']),
]
ERRORS = {'400': ['invalid_request'], '401': ['authentication_required'], '403': ['authority_denied'],
          '404': ['not_found_or_invisible'], '409': ['conflict'], '410': ['expired'],
          '413': ['payload_too_large'], '429': ['capacity_exceeded'], '503': ['source_unavailable', 'unknown_outcome']}


def ref(name):
    return {'$ref': '#/$defs/' + name}


def channel(name):
    return {'$ref': CID + '#/$defs/' + name}


def obj(**fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def nullable(value):
    return {'anyOf': [value, {'type': 'null'}]}


def enum(*values):
    return {'enum': list(values)}


def typed(binding):
    return obj(schema_ref={'const': binding}, value={'$ref': binding['schema_id'] + '#/$defs/' + binding['definition']})


def condition(field, value, fields):
    return {'if': {'properties': {field: {'const': value}}, 'required': [field]}, 'then': {'properties': fields}}


def schema():
    d = {n: channel(n) for n in ('Id', 'Counter', 'PositiveCounter', 'Digest', 'ActivationRef', 'DelegationRef', 'ObjectRef')}
    identity = copy.deepcopy(CHANNEL['$defs']['RequestIdentity'])
    identity['properties'].pop('request_id')
    identity['required'].remove('request_id')
    identity['properties']['subscription_id'] = ref('Id')
    identity['required'].append('subscription_id')
    d['SubscriptionIdentity'] = identity
    d['SubscriptionIntent'] = obj(identity=ref('SubscriptionIdentity'), activation_ref=ref('ActivationRef'),
        method=enum(*(m['method'] for m in SUBSCRIBABLE)), target_handle=ref('Id'), resource_ref=nullable(ref('ObjectRef')),
        arguments=channel('TypedValue'))
    d['SubscriptionIntent']['allOf'] = [condition('method', m['method'], {'arguments': typed(m['input_schema_ref'])}) for m in SUBSCRIBABLE]
    d['CreateSubscription'] = obj(gui_instance_id=ref('Id'), delegation_ref=ref('DelegationRef'), intent=ref('SubscriptionIntent'))
    d['LastAck'] = obj(projection_sequence=ref('PositiveCounter'), envelope_digest=ref('Digest'), frame_digest=ref('Digest'), ack_ref=ref('ObjectRef'))
    d['SubscriptionRecord'] = obj(identity=ref('SubscriptionIdentity'), intent_digest=ref('Digest'), activation_ref=ref('ActivationRef'),
        method=enum(*(m['method'] for m in SUBSCRIBABLE)), mode=enum('projection', 'invalidation'),
        state=enum('pending', 'live', 'invalidated', 'gap', 'closing', 'closed'), revision=ref('Counter'),
        published_sequence=ref('Counter'), acknowledged_sequence=ref('Counter'),
        last_ack=nullable(ref('LastAck')), close_operation_ref=nullable(ref('ObjectRef')))
    d['SubscriptionRecord']['allOf'] = [condition('method', m['method'], {'mode': {'const': m['subscription_mode']}}) for m in SUBSCRIBABLE]
    d['SubscriptionRecord']['allOf'] += [
        {'if': {'properties': {'state': {'enum': ['closing', 'closed']}}, 'required': ['state']},
         'then': {'properties': {'close_operation_ref': ref('ObjectRef')}}},
        condition('acknowledged_sequence', '0', {'last_ack': {'type': 'null'}}),
        {'if': {'properties': {'acknowledged_sequence': {'not': {'const': '0'}}}, 'required': ['acknowledged_sequence']},
         'then': {'properties': {'last_ack': ref('LastAck')}}},
        condition('state', 'pending', {'published_sequence': {'const': '0'}, 'acknowledged_sequence': {'const': '0'}}),
        condition('state', 'live', {'mode': {'const': 'projection'}}),
        condition('state', 'invalidated', {'mode': {'const': 'invalidation'}}),
    ]
    d['ProjectionEnvelope'] = obj(protocol_version={'const': VERSION}, identity=ref('SubscriptionIdentity'),
        activation_ref=ref('ActivationRef'), projection_exit_ref=ref('ObjectRef'), source_projection_ref=ref('ObjectRef'),
        projection_sequence=ref('PositiveCounter'), method=enum(*(m['method'] for m in SUBSCRIBABLE)),
        kind=enum('baseline', 'update', 'invalidated'), reason_code={'const': 'ok'}, value=nullable(channel('TypedValue')))
    d['ProjectionEnvelope']['allOf'] = []
    for m in SUBSCRIBABLE:
        fields = {'kind': enum('baseline', 'update'), 'value': typed(m['result_schema_ref'])} if m['subscription_mode'] == 'projection' else {'kind': {'const': 'invalidated'}, 'value': {'type': 'null'}}
        d['ProjectionEnvelope']['allOf'].append(condition('method', m['method'], fields))
    d['ProjectionEnvelope']['allOf'].append(condition('kind', 'baseline', {'projection_sequence': {'const': '1'}}))
    d['ProjectionEnvelope']['allOf'].append(condition('kind', 'update', {'projection_sequence': {'not': {'const': '1'}}}))
    d['EnvelopeRecord'] = obj(envelope=ref('ProjectionEnvelope'), envelope_digest=ref('Digest'))
    d['ProjectionBatch'] = obj(identity=ref('SubscriptionIdentity'), activation_ref=ref('ActivationRef'),
        after_sequence=ref('Counter'), published_sequence=ref('Counter'), has_more={'type': 'boolean'},
        frames={'type': 'array', 'items': ref('EnvelopeRecord'), 'maxItems': 8})
    d['AcknowledgeProjection'] = obj(gui_instance_id=ref('Id'), delegation_ref=ref('DelegationRef'),
        identity=ref('SubscriptionIdentity'), envelope_digest=ref('Digest'), frame=channel('Projection'), panel_ack=channel('ProjectionAck'))
    d['CloseSubscription'] = obj(gui_instance_id=ref('Id'), delegation_ref=ref('DelegationRef'),
        identity=ref('SubscriptionIdentity'), activation_ref=ref('ActivationRef'),
        reason_code=enum('user_closed', 'channel_failed', 'host_shutdown'))
    d['Error'] = obj(code=enum(*(c for codes in ERRORS.values() for c in codes)), correlation_id=ref('Id'))
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SID, 'title': VERSION,
            'x-approved': False, 'x-runtime-approved': False, '$defs': d}


def resources_for(main):
    resources = {SID: ('Subscription', main)}
    for prefix, path in [('Channel', PANEL / 'channel-v02.schema.json'), ('Bundle', PANEL / 'bundle.schema.json'),
                         ('Input', PANEL / 'method-input.schema.json'), ('Result', PANEL / 'result.schema.json'),
                         ('Public', HERE.parent / 'df01-source/source/public.schema.json')]:
        doc = json.loads(path.read_text('utf-8'))
        resources[doc['$id']] = (prefix, doc)
        resources[urljoin(CID, path.name)] = (prefix, doc)
        if prefix == 'Public':
            for alias in ('https://leafseamer.invalid/design/df01-source/source/public.schema.json',
                          'https://leafseamer.invalid/contracts/panel-methods/df01-source/source/public.schema.json'):
                resources[alias] = (prefix, doc)
    return resources


def build():
    main = schema()
    resources = resources_for(main)
    components = {}

    def inline(value, base):
        if isinstance(value, list):
            return [inline(v, base) for v in value]
        if not isinstance(value, dict):
            return value
        out = {}
        for key, v in value.items():
            if key == '$ref':
                uri, fragment = urldefrag(urljoin(base, v))
                namespace, doc = resources[uri]
                if not fragment.startswith('/$defs/') or '/' in fragment[7:]:
                    raise ValueError('非受支持的本地引用: ' + v)
                name = fragment[7:]
                target = namespace + '_' + name
                if target not in components:
                    components[target] = {}
                    components[target] = inline(doc['$defs'][name], doc['$id'])
                out[key] = '#/components/schemas/' + target
            elif key not in ('$id', '$schema'):
                out[key] = copy.deepcopy(v) if key in ('const', 'enum', 'default', 'examples') else inline(v, base)
        return out

    paths = {}
    for verb, suffix, operation, request, response, successes in ROUTES:
        path = PREFIX + suffix
        parameters = [{'in': 'header', 'name': 'Origin', 'required': True, 'schema': inline(channel('Origin'), SID)}]
        for token in path.split('/'):
            if token.startswith('{'):
                parameters.append({'in': 'path', 'name': token[1:-1], 'required': True, 'schema': inline(ref('Id'), SID)})
        if verb == 'get':
            parameters.append({'in': 'query', 'name': 'gui_instance_id', 'required': True, 'schema': inline(ref('Id'), SID)})
        if operation == 'getPanelProjectionFrames':
            parameters += [{'in': 'query', 'name': 'after_sequence', 'required': True, 'schema': inline(ref('Counter'), SID)},
                           {'in': 'query', 'name': 'limit', 'required': True, 'schema': {'type': 'integer', 'minimum': 1, 'maximum': 8}}]
        responses = {}
        for code in successes + list(ERRORS):
            body = inline(ref(response if code in successes else 'Error'), SID)
            if code in ERRORS:
                body = {'allOf': [body, {'properties': {'code': enum(*ERRORS[code])}}]}
            responses[code] = {'description': '当前可靠记录；不表示设备或页面效果',
                'headers': {'Cache-Control': {'required': True, 'schema': {'type': 'string', 'const': 'no-store'}}},
                'content': {'application/json': {'schema': body}}}
        security = {'humanBearer': []}
        if verb == 'post':
            security['sessionCsrf'] = []
        value = {'operationId': operation, 'parameters': parameters, 'security': [security], 'responses': responses,
                 'x-host-only': True, 'x-automatic-write-retry': False, 'x-authorities': ['controller', 'seamer']}
        if request:
            value['requestBody'] = {'required': True, 'content': {'application/json': {'schema': inline(ref(request), SID)}}}
        paths.setdefault(path, {})[verb] = value
    api = {'openapi': '3.1.1', 'info': {'title': 'LeafSeamer 面板订阅候选', 'version': VERSION},
           'x-approved': False, 'x-runtime-approved': False, 'paths': paths,
           'components': {'schemas': components, 'securitySchemes': {'humanBearer': {'type': 'http', 'scheme': 'bearer'},
              'sessionCsrf': {'type': 'apiKey', 'in': 'header', 'name': 'X-CSRF-Token'}}}}
    return {'subscriptions.schema.json': main, 'subscriptions.openapi.json': api}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, value in build().items():
        if args.check:
            assert (HERE / name).read_bytes() == encoded(value), name
        else:
            (HERE / name).write_bytes(encoded(value))
    print('订阅两个生成物一致' if args.check else '已生成订阅两个候选文件')
