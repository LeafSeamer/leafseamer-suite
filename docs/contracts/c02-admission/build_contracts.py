"""生成命令裁决三接口候选；固定本地引用，不实现受理服务。"""
import argparse
import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SID = 'https://leafseamer.invalid/design/c02-admission/admission.schema.json'
VERSION = 'command-admission/0.1.0-draft.1'
SOURCES = [BASE / p for p in ('c05-protection/protocol.schema.json',
    'c05-protection/protection.schema.json', 'df01-source/source/public.schema.json')]
EXCLUDED = ('context_id', 'idempotency_key', 'correlation_id')


def ref(n):
    return {'$ref': '#/$defs/' + n}


def obj(**p):
    return dict(type='object', properties=p, required=list(p), additionalProperties=False)


def nullable(v):
    return {'anyOf': [v, {'type': 'null'}]}


def encoded(v):
    return (json.dumps(v, ensure_ascii=False, indent=2) + '\n').encode()


def absolute(v, base):
    if isinstance(v, list):
        return [absolute(x, base) for x in v]
    if not isinstance(v, dict):
        return copy.deepcopy(v)
    return {k: base + x if k == '$ref' and x.startswith('#') else
            copy.deepcopy(x) if k in ('const', 'enum', 'default', 'examples') else absolute(x, base)
            for k, x in v.items()}


def build():
    sources = [json.loads(p.read_bytes()) for p in SOURCES]
    protocol = sources[0]
    ext = lambda n: {'$ref': protocol['$id'] + '#/$defs/' + n}
    d = {n: ext(n) for n in ('Id', 'Scope', 'Digest', 'Counter', 'CommandRequest')}
    content = absolute(protocol['$defs']['CommandRequest'], protocol['$id'])
    for field in EXCLUDED:
        content['properties'].pop(field, None)
    content['required'] = [k for k in content['required'] if k not in EXCLUDED]
    d['CommandContent'] = content
    d['RequestKey'] = obj(target_scope=ref('Scope'), issuer_id=ref('Id'), issuer_epoch=ref('Id'),
        principal_id=ref('Id'), request_epoch=ref('Id'), operation_id={'const': 'createCommand'},
        idempotency_key=ref('Id'))
    d['RequestIdentity'] = obj(key=ref('RequestKey'), request_digest=ref('Digest'))
    for name, kind in [('CommandRef', 'command'), ('CommitRef', 'controller_commit')]:
        d[name] = obj(kind={'const': kind}, scope=ref('Scope'), object_id=ref('Id'),
                      revision=ref('Counter'), digest=ref('Digest'))
    d['RequestAdjudication'] = obj(contract_version={'const': VERSION}, adjudication_id=ref('Id'),
        revision={'const': '1'}, identity=ref('RequestIdentity'), decision={'enum': ['accepted', 'rejected']},
        command_ref=nullable(ref('CommandRef')), commit_ref=ref('CommitRef'),
        adjudication_digest=ref('Digest'))
    d['RequestAdjudication']['allOf'] = [{
        'if': {'properties': {'decision': {'const': 'accepted'}}, 'required': ['decision']},
        'then': {'properties': {'command_ref': ref('CommandRef')}},
        'else': {'properties': {'command_ref': {'type': 'null'}}}}]
    d['LookupResult'] = {'oneOf': [
        obj(state={'const': 'found'}, adjudication=ref('RequestAdjudication')),
        obj(state={'enum': ['not_found', 'indeterminate']}, adjudication={'type': 'null'})]}
    d['RejectRequest'] = obj(rejection_operation_id=ref('Id'), identity=ref('RequestIdentity'),
                             content=ref('CommandContent'))
    d['Error'] = obj(code={'enum': ['invalid', 'unauthenticated', 'forbidden', 'conflict',
                                   'capacity', 'unavailable', 'version']}, request_id=ref('Id'))
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SID,
              'title': VERSION, 'not': {}, 'x-approved': False, '$defs': d}
    resources = {x['$id']: (f'S{i}', x) for i, x in enumerate([schema] + sources)}
    components = {}

    def project(v, base):
        if isinstance(v, list):
            return [project(x, base) for x in v]
        if not isinstance(v, dict):
            return copy.deepcopy(v)
        out = {}
        for k, x in v.items():
            if k == '$ref':
                uri, name = (base + x if x.startswith('#') else x).split('#/$defs/')
                prefix, source = resources[uri]
                assert '/' not in name
                key = prefix + '_' + name
                if key not in components:
                    components[key] = {}
                    components[key] = project(source['$defs'][name], uri)
                out[k] = '#/components/schemas/' + key
            elif k not in ('$schema', '$id'):
                out[k] = copy.deepcopy(x) if k in ('const', 'enum', 'examples', 'default') else project(x, base)
        return out

    media = lambda n: {'application/json': {'schema': project(ref(n), SID)}}
    routes = [
        ('', 'submitCommand', 'CommandRequest', 'RequestAdjudication', 'device.command',
         ('200', '202'), 'never-auto-retry', ['human_manual', 'seamer_automation']),
        ('/lookup', 'lookupCommandAdmission', 'RequestIdentity', 'LookupResult', 'command.read',
         ('200',), 'read-only', ['human_own_namespace', 'seamer_own_namespace']),
        ('/reject', 'rejectCommandAdmission', 'RejectRequest', 'RequestAdjudication', 'command.cancel',
         ('200',), 'same-identity-monotonic-denial-only', ['human_own_namespace', 'seamer_own_automation'])]
    paths = {}
    for suffix, operation, request, response, permission, codes, retry, profiles in routes:
        responses = {c: dict(description='持久裁决或查询；不表示设备完成或停止', content=media(response)) for c in codes}
        for c in ('400', '401', '403', '409', '413', '422', '429', '503'):
            responses[c] = dict(description='无永久裁决保证；不授权动作重发', content=media('Error'))
        for v in responses.values():
            v['headers'] = {'Cache-Control': {'schema': {'const': 'no-store'}}}
        paths['/api/v1/commands' + suffix] = {'post': dict(operationId=operation,
            security=[{'bearerAuth': []}], parameters=[dict(name='X-LeafSeamer-Contract',
                **{'in': 'header'}, required=True, schema={'const': VERSION})],
            requestBody=dict(required=True, content=media(request)), responses=responses,
            **{'x-required-permission': permission, 'x-subject-profiles': profiles,
               'x-retry-policy': retry, 'x-original-operation-id': 'createCommand'})}
    api = dict(openapi='3.1.1', info=dict(title='命令受理与永久拒收候选', version=VERSION),
        paths=paths, components=dict(schemas=components, securitySchemes={
            'bearerAuth': dict(type='http', scheme='bearer')}))
    return {'admission.schema.json': schema, 'admission.openapi.json': api}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, value in build().items():
        if args.check:
            assert (HERE / name).read_bytes() == encoded(value), name
        else:
            (HERE / name).write_bytes(encoded(value))
