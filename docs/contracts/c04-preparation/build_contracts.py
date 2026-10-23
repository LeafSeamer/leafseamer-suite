"""生成准备接口候选；固定本地Schema闭包，不实现业务服务。"""
import argparse
import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SID = 'https://leafseamer.invalid/design/c04-preparation/preparation.schema.json'
VERSION = 'automation-preparation/0.1.0-draft.1'
SOURCES = [BASE / p for p in (
    'c05-protection/protocol.schema.json', 'c05-protection/protection.schema.json',
    'df01-source/source/public.schema.json')]


def obj(**p):
    return dict(type='object', properties=p, required=list(p), additionalProperties=False)


def ref(n):
    return {'$ref': '#/$defs/' + n}


def null(v):
    return {'anyOf': [v, {'type': 'null'}]}


def arr(v, maximum=256):
    return dict(type='array', items=v, minItems=1, maxItems=maximum)


def encoded(v):
    return (json.dumps(v, ensure_ascii=False, indent=2) + '\n').encode()


def build():
    sources = [json.loads(p.read_bytes()) for p in SOURCES]
    protocol, _, public = sources
    ext = lambda n: {'$ref': protocol['$id'] + '#/$defs/' + n}
    pub = lambda n: {'$ref': public['$id'] + '#/$defs/' + n}
    d = {n: ext(n) for n in ('Id', 'Scope', 'Counter', 'PositiveCounter', 'Digest', 'RunGrant')}
    for name, kind in [('OperationRef', 'lifecycle_operation'), ('ArtifactRef', 'artifact'),
                       ('ApprovalRef', 'approval'), ('GrantRef', 'grant'),
                       ('CommitRef', 'controller_commit'), ('ProtectionRef', 'run_protection')]:
        d[name] = obj(kind={'const': kind}, scope=ref('Scope'), object_id=ref('Id'),
                      revision=ref('Counter'), digest=ref('Digest'))
    d['PlanRef'] = obj(kind={'enum': ['arm_plan', 'recovery_plan']}, scope=ref('Scope'),
                       object_id=ref('Id'), revision=ref('Counter'), digest=ref('Digest'))
    d['GrantIntent'] = obj(principal_id=ref('Id'), device_actions=arr(pub('DeviceActionScope')),
        parameter_constraints=dict(type='array', items=pub('Predicate'), maxItems=64),
        validity=pub('Validity'))
    d['ControlExpectation'] = obj(device_id=ref('Id'), expected_control=pub('ControlVersion'))
    d['PrepareRequest'] = obj(contract_version={'const': VERSION}, operation_id=ref('Id'),
        preparation_id=ref('Id'), controller_scope=ref('Scope'), origin_scope=ref('Scope'),
        run_id=ref('Id'), definition_version=ref('PositiveCounter'), arm_generation=ref('PositiveCounter'),
        mode={'enum': ['arm', 'recovery']}, execution_id=null(ref('Id')),
        operation_ref=ref('OperationRef'), plan_ref=ref('PlanRef'), artifact_ref=ref('ArtifactRef'),
        approval_ref=ref('ApprovalRef'), authorization_digest=ref('Digest'), source_digest=ref('Digest'),
        controls=arr(ref('ControlExpectation')), baseline_grant_ref=null(ref('GrantRef')),
        grant_intent=ref('GrantIntent'))
    d['PrepareRequest']['allOf'] = [{
        'if': {'properties': {'mode': {'const': 'arm'}}, 'required': ['mode']},
        'then': {'properties': {'execution_id': {'type': 'null'},
                               'plan_ref': {'properties': {'kind': {'const': 'arm_plan'}}}}},
        'else': {'properties': {'execution_id': ref('Id'),
                               'plan_ref': {'properties': {'kind': {'const': 'recovery_plan'}}}}}}]
    d['PreparationReceipt'] = obj(receipt_id=ref('Id'), revision=ref('PositiveCounter'),
        controller_scope=ref('Scope'), preparation_id=ref('Id'), request_digest=ref('Digest'),
        grant=ref('RunGrant'), grant_ref=ref('GrantRef'), commit_ref=ref('CommitRef'),
        receipt_digest=ref('Digest'))
    d['PreparationRecord'] = obj(request=ref('PrepareRequest'), request_digest=ref('Digest'),
        revision=ref('PositiveCounter'), state={'enum': [
            'accepted', 'applied', 'rejected', 'indeterminate', 'closing', 'closed']},
        applied_receipt=null(ref('PreparationReceipt')), protection_ref=null(ref('ProtectionRef')))
    d['PreparationRecord']['allOf'] = [
        {'if': {'properties': {'state': {'const': 'applied'}}, 'required': ['state']},
         'then': {'properties': {'applied_receipt': ref('PreparationReceipt')}}},
        {'if': {'properties': {'state': {'enum': ['accepted', 'rejected']}}, 'required': ['state']},
         'then': {'properties': {'applied_receipt': {'type': 'null'}}}},
        {'if': {'properties': {'state': {'const': 'closed'}}, 'required': ['state']},
         'then': {'properties': {'protection_ref': ref('ProtectionRef')}}}]
    d['PreparationLookup'] = obj(contract_version={'const': VERSION}, controller_scope=ref('Scope'),
        origin_scope=ref('Scope'), preparation_id=ref('Id'), request_digest=ref('Digest'))
    d['PreparationLookupResult'] = {'oneOf': [
        obj(state={'const': 'found'}, record=ref('PreparationRecord')),
        obj(state={'enum': ['not_found', 'indeterminate']}, record={'type': 'null'})]}
    d['PreparationClose'] = obj(contract_version={'const': VERSION}, close_operation_id=ref('Id'),
        request=ref('PrepareRequest'), request_digest=ref('Digest'))
    d['PreparationError'] = obj(code={'enum': [
        'invalid', 'unauthenticated', 'forbidden', 'conflict', 'capacity', 'unavailable', 'version']},
        request_id=ref('Id'))
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SID,
              'title': VERSION, 'not': {}, 'x-approved': False, '$defs': d}
    resources = {s['$id']: (f'S{i}', s) for i, s in enumerate([schema] + sources)}
    components = {}

    def project(v, base):
        if isinstance(v, list):
            return [project(x, base) for x in v]
        if not isinstance(v, dict):
            return copy.deepcopy(v)
        out = {}
        for k, x in v.items():
            if k == '$ref':
                uri = base + x if x.startswith('#') else x
                resource, name = uri.split('#/$defs/')
                prefix, source = resources[resource]
                assert '/' not in name
                key = prefix + '_' + name
                if key not in components:
                    components[key] = {}
                    components[key] = project(source['$defs'][name], resource)
                out[k] = '#/components/schemas/' + key
            elif k not in ('$schema', '$id'):
                out[k] = copy.deepcopy(x) if k in ('const', 'enum', 'default', 'examples') else project(x, base)
        return out

    content = lambda n: {'application/json': {'schema': project(ref(n), SID)}}
    paths = {}
    routes = [
        ('', 'prepareAutomation', 'PrepareRequest', 'PreparationRecord', 'automation.prepare', ('200', '202')),
        ('/lookup', 'lookupPreparation', 'PreparationLookup', 'PreparationLookupResult',
         'automation.prepare.read', ('200',)),
        ('/close', 'closePreparation', 'PreparationClose', 'PreparationRecord',
         'automation.protect', ('200', '202'))]
    for suffix, operation, request, response, permission, codes in routes:
        responses = {c: dict(description='可靠记录或原件；不表示设备执行或资源清理',
                            content=content(response)) for c in codes}
        for c in ('400', '401', '403', '409', '413', '422', '429', '503'):
            responses[c] = dict(description='拒绝或未知；不授权重做准备或设备动作',
                                content=content('PreparationError'))
        for v in responses.values():
            v['headers'] = {'Cache-Control': {'schema': {'const': 'no-store'}}}
        paths['/internal/automation/preparations' + suffix] = {'post': dict(
            operationId=operation, security=[{'InternalMTLS': []}],
            parameters=[dict(name='X-LeafSeamer-Contract', **{'in': 'header'},
                             required=True, schema={'const': VERSION})],
            requestBody=dict(required=True, content=content(request)), responses=responses,
            **{'x-required-permission': permission, 'x-required-origin-ownership': True,
               'x-retry-policy': {'': 'lookup-only-after-uncertainty', '/lookup': 'read-only',
                                  '/close': 'same-identity-monotonic-denial-only'}[suffix]})}
    api = dict(openapi='3.1.1', info=dict(title='自动化准备内部接口候选', version=VERSION),
        paths=paths, components=dict(schemas=components, securitySchemes={'InternalMTLS': dict(type='mutualTLS')}))
    return {'preparation.schema.json': schema, 'preparation.openapi.json': api}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, value in build().items():
        if args.check:
            assert (HERE / name).read_bytes() == encoded(value), name
        else:
            (HERE / name).write_bytes(encoded(value))
