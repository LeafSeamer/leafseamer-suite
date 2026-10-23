"""生成设计候选；只写本目录的两个机器契约，不生成业务服务。"""
import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urldefrag, urljoin

HERE = Path(__file__).resolve().parent
PANEL = HERE.parent / 'c09-panel'
SID = 'https://leafseamer.invalid/design/c09-panel-service/service.schema.json'
CHANNEL = json.loads((PANEL / 'channel-v02.schema.json').read_text('utf-8'))
CID = CHANNEL['$id']
REGISTRY = json.loads((PANEL / 'method-registry-v02.json').read_text('utf-8'))['registry']['methods']
VERSION = 'panel-service/0.1.0-draft.1'


def ref(name):
    return {'$ref': '#/$defs/' + name}


def channel(name):
    return {'$ref': CID + '#/$defs/' + name}


def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


def obj(**fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def enum(*values):
    return {'enum': list(values)}


def conditional(field, value, properties):
    return {'if': {'properties': {field: {'const': value}}, 'required': [field]},
            'then': {'properties': properties}}


def typed(binding):
    return obj(schema_ref={'const': binding}, value={'$ref': binding['schema_id'] + '#/$defs/' + binding['definition']})


ROUTES = [
    ('post', '/panel-sessions', 'createPanelSession', 'CreateSession', 'HostSession', ['201', '200']),
    ('get', '/panel-sessions/{session_id}', 'getPanelSession', None, 'HostSession', ['200']),
    ('post', '/panel-sessions/{session_id}/handshake', 'beginPanelHandshake', 'Handshake', 'HostSession', ['200']),
    ('post', '/panel-sessions/{session_id}/prepare-activation', 'preparePanelActivation', 'PrepareActivation', 'HostSession', ['200']),
    ('post', '/panel-sessions/{session_id}/activate', 'activatePanelSession', 'Activate', 'HostSession', ['200']),
    ('post', '/panel-sessions/{session_id}/renew', 'renewPanelSession', 'Renew', 'HostSession', ['200']),
    ('post', '/panel-sessions/{session_id}/requests', 'invokePanelMethod', 'Invocation', 'RequestReceipt', ['200', '202']),
    ('get', '/panel-sessions/{session_id}/requests/{request_id}', 'getPanelRequest', None, 'RequestReceipt', ['200']),
    ('post', '/panel-sessions/{session_id}/confirmations', 'offerPanelConfirmation', 'ConfirmInvocation', 'ConfirmationRecord', ['201', '200']),
    ('get', '/panel-confirmations/{preview_id}', 'getPanelConfirmation', None, 'ConfirmationRecord', ['200']),
    ('post', '/panel-confirmations/{preview_id}/commit', 'commitPanelConfirmation', 'ConfirmationCommit', 'RequestReceipt', ['202', '200']),
    ('post', '/panel-confirmations/{preview_id}/cancel', 'cancelPanelConfirmation', 'ConfirmationCancel', 'RequestReceipt', ['200']),
    ('post', '/panel-sessions/{session_id}/close', 'closePanelSession', 'CloseSession', 'LifecycleReceipt', ['202', '200']),
    ('get', '/panel-session-operations/{host_operation_id}', 'getPanelSessionOperation', None, 'LifecycleReceipt', ['200']),
]
ERRORS = {'400': ['invalid_request'], '401': ['authentication_required'], '403': ['authority_denied'],
          '404': ['not_found_or_invisible'], '409': ['conflict'], '410': ['expired'],
          '413': ['payload_too_large'], '429': ['capacity_exceeded'],
          '503': ['source_unavailable', 'unknown_outcome']}


def build_schema():
    d = {name: channel(name) for name in ('Id', 'Counter', 'Digest', 'RequestIdentity', 'DelegationRef',
                                         'ActivationRef', 'ObjectRef', 'ConfirmationCommit')}
    d['CreateSession'] = obj(host_operation_id=ref('Id'), gui_instance_id=ref('Id'),
        panel_instance_id=ref('Id'), document_generation=channel('PositiveCounter'),
        installation_ref=ref('ObjectRef'), approval_ref=ref('ObjectRef'), artifact_digest=ref('Digest'),
        mount_ref=ref('ObjectRef'), requested_scope_ref=ref('ObjectRef'), configuration_ref=ref('ObjectRef'))
    common = dict(host_operation_id=ref('Id'), gui_instance_id=ref('Id'))
    d['Handshake'] = obj(**common, expected_revision=ref('Counter'), handshake_id=ref('Id'), channel_id=ref('Id'))
    d['PrepareActivation'] = obj(**common, expected_revision=ref('Counter'), handshake_id=ref('Id'),
        expected_registry_ref=channel('RevisionRef'), expected_bundle_ref=nullable(channel('BundleRef')))
    d['Activate'] = obj(**common, expected_revision=ref('Counter'), handshake_id=ref('Id'),
        channel_id=ref('Id'), activation_ref=ref('ActivationRef'), ready_manifest_digest=nullable(ref('Digest')))
    d['Renew'] = obj(**common, expected_lease_revision=ref('Counter'), activation_ref=ref('ActivationRef'))
    d['CloseSession'] = obj(**common, reason_code=enum('user_closed', 'navigation', 'channel_failed', 'host_shutdown'))
    d['HostSession'] = obj(session=channel('Session'), lifetime=channel('Lifetime'), delegation_ref=ref('DelegationRef'),
        handshake_id=nullable(ref('Id')), channel_id=nullable(ref('Id')), close_operation_ref=nullable(ref('ObjectRef')))
    intent = {'allOf': [channel('Intent')], 'properties': {'method': enum(*(m['method'] for m in REGISTRY))}}
    for m in REGISTRY:
        intent['allOf'].append(conditional('method', m['method'], {'normalized_arguments': typed(m['input_schema_ref'])}))
    d['BoundIntent'] = intent
    d['Invocation'] = obj(intent=ref('BoundIntent'))
    confirm_methods = [m['method'] for m in REGISTRY if m['mode'] == 'host_confirm']
    d['ConfirmInvocation'] = obj(intent={'allOf': [ref('BoundIntent'), {'properties': {'method': enum(*confirm_methods)}}]})
    d['ConfirmationCancel'] = obj(identity=ref('RequestIdentity'), delegation_ref=ref('DelegationRef'),
        preview_ref=ref('ObjectRef'), preview_digest=ref('Digest'))
    d['RequestReceipt'] = obj(identity=ref('RequestIdentity'), intent_digest=ref('Digest'),
        method=enum(*(m['method'] for m in REGISTRY)), activation_ref=ref('ActivationRef'),
        state=enum('accepted', 'pending_confirmation', 'rejected', 'cancelled'),
        reason_code=enum('ok', 'needs_host_confirmation', 'authority_denied', 'schema_invalid',
                         'target_changed', 'expired', 'user_cancelled', 'activation_stale'),
        accepted_result_ref=nullable(ref('ObjectRef')),
        projection_state=enum('available', 'unavailable', 'not_applicable'), projection=nullable(channel('TypedValue')))
    receipt = d['RequestReceipt']
    receipt['allOf'] = [
        conditional('state', 'accepted', {'reason_code': {'const': 'ok'}, 'accepted_result_ref': ref('ObjectRef'),
                                         'projection_state': enum('available', 'unavailable')}),
        conditional('state', 'pending_confirmation', {'reason_code': {'const': 'needs_host_confirmation'}, 'method': enum(*confirm_methods)}),
        conditional('state', 'cancelled', {'reason_code': {'const': 'user_cancelled'}}),
        conditional('state', 'rejected', {'reason_code': enum('authority_denied', 'schema_invalid', 'target_changed', 'expired', 'activation_stale')}),
        {'if': {'properties': {'state': {'not': {'const': 'accepted'}}}, 'required': ['state']},
         'then': {'properties': {'accepted_result_ref': {'type': 'null'}, 'projection': {'type': 'null'},
                                 'projection_state': {'const': 'not_applicable'}}}},
        conditional('projection_state', 'available', {'state': {'const': 'accepted'}, 'projection': channel('TypedValue')}),
        {'if': {'properties': {'projection_state': {'not': {'const': 'available'}}}, 'required': ['projection_state']},
         'then': {'properties': {'projection': {'type': 'null'}}}},
    ]
    for m in REGISTRY:
        receipt['allOf'].append({'if': {'properties': {'method': {'const': m['method']}, 'projection_state': {'const': 'available'}},
            'required': ['method', 'projection_state']}, 'then': {'properties': {'projection': typed(m['result_schema_ref'])}}})
    d['ConfirmationRecord'] = obj(preview=channel('Preview'), request=ref('RequestReceipt'))
    d['CloseTarget'] = obj(target_ref=ref('ObjectRef'), selector_digest=ref('Digest'),
        state=enum('pending', 'acknowledged', 'indeterminate'), evidence_ref=nullable(ref('ObjectRef')))
    d['CloseTarget']['allOf'] = [conditional('state', 'acknowledged', {'evidence_ref': ref('ObjectRef')}),
        {'if': {'properties': {'state': {'not': {'const': 'acknowledged'}}}, 'required': ['state']},
         'then': {'properties': {'evidence_ref': {'type': 'null'}}}}]
    d['LifecycleReceipt'] = obj(host_operation_id=ref('Id'), gui_instance_id=ref('Id'),
        operation=enum(*(r[2] for r in ROUTES if r[3] in ('CreateSession', 'Handshake', 'PrepareActivation', 'Activate', 'Renew', 'CloseSession'))),
        content_digest=ref('Digest'), session_ref=ref('ObjectRef'), phase=enum('committed', 'propagating', 'acknowledged', 'indeterminate'),
        targets={'type': 'array', 'items': ref('CloseTarget'), 'maxItems': 256})
    d['LifecycleReceipt']['allOf'] = [
        {'if': {'properties': {'operation': {'not': {'const': 'closePanelSession'}}}, 'required': ['operation']},
         'then': {'properties': {'phase': {'const': 'committed'}, 'targets': {'maxItems': 0}}}},
        conditional('operation', 'closePanelSession', {'phase': enum('propagating', 'acknowledged', 'indeterminate')})]
    d['Error'] = obj(code=enum(*(c for codes in ERRORS.values() for c in codes)), correlation_id=ref('Id'))
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SID,
            'title': VERSION, '$defs': d, 'x-approved': False, 'x-runtime-approved': False}


def build():
    schema = build_schema()
    # 已知本地资源闭包；禁止联网。只投影Schema位置，不改写const/enum中的业务数据。
    resources = {SID: ('Service', schema)}
    for namespace, path in [('Channel', PANEL/'channel-v02.schema.json'), ('Bundle', PANEL/'bundle.schema.json'),
                            ('Input', PANEL/'method-input.schema.json'), ('Result', PANEL/'result.schema.json'),
                            ('Public', HERE.parent/'df01-source/source/public.schema.json')]:
        doc = json.loads(path.read_text('utf-8'))
        resources[doc['$id']] = (namespace, doc)
        resources[urljoin(CID, path.name)] = (namespace, doc)
        if namespace == 'Public':
            resources['https://leafseamer.invalid/design/df01-source/source/public.schema.json'] = (namespace, doc)
            resources['https://leafseamer.invalid/contracts/df01-source/source/public.schema.json'] = (namespace, doc)
            resources['https://leafseamer.invalid/contracts/panel-methods/df01-source/source/public.schema.json'] = (namespace, doc)
    components = {}

    def bundle(value, base):
        if isinstance(value, list):
            return [bundle(v, base) for v in value]
        if not isinstance(value, dict):
            return value
        out = {}
        for key, v in value.items():
            if key == '$ref':
                absolute = base + v if v.startswith('#') else urljoin(base, v)
                uri, fragment = urldefrag(absolute)
                namespace, doc = resources[uri]
                if not fragment.startswith('/$defs/') or '/' in fragment[7:]:
                    raise ValueError('不支持的本地模型引用: ' + absolute)
                name = fragment[7:]
                cname = namespace + '_' + name
                if cname not in components:
                    components[cname] = {}
                    components[cname] = bundle(doc['$defs'][name], doc['$id'])
                out[key] = '#/components/schemas/' + cname
            elif key not in ('$id', '$schema'):
                out[key] = copy.deepcopy(v) if key in ('const', 'enum', 'examples', 'default') else bundle(v, base)
        return out

    def model(name):
        return bundle(ref(name), SID)

    paths = {}
    for verb, path, operation, request, response, successes in ROUTES:
        parameters = [{'in': 'header', 'name': 'Origin', 'required': True, 'schema': channel('Origin')}]
        for part in path.split('/'):
            if part.startswith('{'):
                parameters.append({'in': 'path', 'name': part[1:-1], 'required': True, 'schema': ref('Id')})
        if operation == 'getPanelSessionOperation':
            parameters.append({'in': 'query', 'name': 'gui_instance_id', 'required': True, 'schema': ref('Id')})
        for parameter in parameters:
            parameter['schema'] = bundle(parameter['schema'], SID)
        responses = {}
        for status in successes + list(ERRORS):
            body = model(response if status in successes else 'Error')
            if status in ERRORS:
                body = {'allOf': [body, {'properties': {'code': enum(*ERRORS[status])}}]}
            responses[status] = {'description': '可靠记录或当前投影；不表示设备效果' if status in successes else '有限错误，不授权自动重发',
                'headers': {'Cache-Control': {'required': True, 'schema': {'const': 'no-store', 'type': 'string'}}},
                'content': {'application/json': {'schema': body}}}
        security = {'humanBearer': []}
        if verb == 'post':
            security['sessionCsrf'] = []
        op = {'operationId': operation, 'parameters': parameters, 'security': [security], 'responses': responses,
              'x-authorities': ['controller', 'seamer'], 'x-current-object-authorization': True,
              'x-automatic-write-retry': False, 'x-host-only': True}
        if request:
            op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': model(request)}}}
        paths['/api/v1' + path] = {**paths.get('/api/v1' + path, {}), verb: op}
    api = {'openapi': '3.1.1', 'info': {'title': 'LeafSeamer 面板服务候选', 'version': VERSION},
           'x-approved': False, 'x-runtime-approved': False, 'paths': paths,
           'components': {'schemas': components, 'securitySchemes': {
               'humanBearer': {'type': 'http', 'scheme': 'bearer', 'description': '当前目标单audience的human凭据'},
               'sessionCsrf': {'type': 'apiKey', 'in': 'header', 'name': 'X-CSRF-Token', 'description': '绑定当前auth_session；与bearer同时要求'}}}}
    return {'service.schema.json': schema, 'service.openapi.json': api}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for filename, value in build().items():
        data = encoded(value)
        if args.check:
            if (HERE / filename).read_bytes() != data:
                raise SystemExit('生成漂移: ' + filename)
        else:
            (HERE / filename).write_bytes(data)
    print('面板服务两个生成物一致' if args.check else '已生成面板服务两个候选文件')
