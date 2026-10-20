"""摄取候选的唯一格式源；只生成设计资料，不创建服务或数据库。"""
import argparse
import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = 'event-ingress/0.1.0-draft.1'
SID = 'https://leafseamer.invalid/design/c05-ingress/ingress.schema.json'
DF06 = HERE.parent / 'df06/internal-trust.schema.json'


def ref(name): return {'$ref': '#/$defs/' + name}
def obj(**props): return dict(type='object', properties=props, required=list(props), additionalProperties=False)
def arr(item, limit=256): return dict(type='array', items=item, maxItems=limit)
def enum(*values): return {'enum': list(values)}
def nullable(value): return {'anyOf': [value, {'type': 'null'}]}
def const(value): return {'const': value}


def schema():
    ident = dict(type='string', pattern=r'^[A-Za-z0-9_-]{1,128}(?![\s\S])')
    counter = dict(type='string', pattern=r'^(0|[1-9][0-9]{0,19})(?![\s\S])')
    positive = dict(type='string', pattern=r'^[1-9][0-9]{0,19}(?![\s\S])')
    digest = dict(type='string', pattern=r'^sha256:[0-9a-f]{64}(?![\s\S])')
    d = dict(Id=ident, Counter=counter, PositiveCounter=positive, Digest=digest)
    d['Scope'] = obj(authority_service_id=ident, database_instance_id=ident)
    d['Ref'] = obj(kind=ident, scope=ref('Scope'), object_id=ident, revision=counter, digest=digest)
    d['SourceBindingRef'] = copy.deepcopy(json.loads(DF06.read_text('utf-8'))['$defs']['SourceBindingRef'])
    d['SourceKey'] = obj(authority_service_id=ident, database_instance_id=ident, registration_id=ident,
                         source_stream_id=ident, source_epoch=ident)
    d['ReceiveCursor'] = obj(scope=ref('Scope'), ingest_epoch=ident, receive_sequence=counter)
    d['QualifiedValue'] = obj(schema_ref=ref('Ref'), value={})
    d['Origin'] = obj(source_key=ref('SourceKey'), binding_ref=ref('SourceBindingRef'), event_id=ident,
                      source_sequence=positive, payload=ref('QualifiedValue'))
    d['SubmitEvent'] = obj(contract_version=const(VERSION), origin=ref('Origin'), origin_digest=digest,
                           delivery_binding_ref=ref('Ref'), age_evidence_ref=ref('Ref'))
    d['LookupEvent'] = obj(contract_version=const(VERSION), source_key=ref('SourceKey'), event_id=ident,
                           origin_digest=digest)
    d['ProviderReceipt'] = obj(contract_version=const(VERSION), receipt_id=ident, receipt_revision=positive,
        source_key=ref('SourceKey'), event_id=ident, origin_digest=digest, ingest_state=const('committed'), duplicate={'type': 'boolean'})
    # 来源调用者不能由类型闭包获得内部run、全局游标或决定数量。
    d['LookupResult'] = {'oneOf': [
        obj(state=const('committed'), receipt=ref('ProviderReceipt')),
        obj(state=enum('not_found', 'historically_closed', 'indeterminate'), receipt={'type': 'null'})]}
    d['Error'] = obj(code=enum('forbidden', 'invalid', 'conflict', 'closed', 'capacity', 'unavailable', 'version'),
                      request_id=ident)
    d['FirstObservation'] = obj(clock_ref=ref('Ref'), receive_tick_ns=counter, delivery_binding_ref=ref('Ref'), age_evidence_ref=ref('Ref'))
    d['InboxContent'] = obj(scope=ref('Scope'), inbox_id=ident, revision=positive, origin=ref('Origin'),
        origin_digest=digest, first_observation=ref('FirstObservation'), content_digest=digest)
    d['MatchTarget'] = obj(run_id=ident, definition_id=ident, definition_version=positive,
        artifact_ref=ref('Ref'), trigger_binding_ref=ref('Ref'))
    d['MatchSet'] = obj(scope=ref('Scope'), match_set_id=ident, source_key=ref('SourceKey'),
        registry_revision=counter, targets=arr(ref('MatchTarget')), targets_digest=digest)
    d['RunProgress'] = obj(scope=ref('Scope'), run_id=ident, ingest_revision=counter,
        last_receive_cursor=ref('ReceiveCursor'), baseline_ref=ref('Ref'))
    d['TransitionEvaluation'] = obj(transition_id=ident, priority=dict(type='integer', minimum=-2147483648, maximum=2147483647),
        result=enum('true', 'false', 'unknown'))
    d['EvaluationSnapshot'] = obj(scope=ref('Scope'), snapshot_id=ident, run_id=ident,
        run_revision_before=counter, ingest_revision_before=counter, slot_revision=counter, artifact_ref=ref('Ref'),
        inbox_ref=ref('Ref'), match_set_ref=ref('Ref'), receive_cursor=ref('ReceiveCursor'),
        source_revision_refs=arr(ref('Ref')), observation_refs=arr(ref('Ref')), input_snapshot_ref=ref('Ref'),
        business_state_ref=nullable(ref('Ref')), rule_result=nullable(enum('true', 'false', 'unknown')),
        transitions=arr(ref('TransitionEvaluation')), snapshot_digest=digest)
    d['TriggerDecision'] = obj(scope=ref('Scope'), decision_id=ident, run_id=ident,
        definition_version=positive, artifact_ref=ref('Ref'), inbox_ref=ref('Ref'), match_set_ref=ref('Ref'),
        receive_cursor=ref('ReceiveCursor'), run_revision_before=counter, run_revision_after=counter,
        ingest_revision_before=counter, ingest_revision_after=counter,
        result=enum('accepted', 'no_match', 'suppressed_busy', 'suppressed_inactive', 'suppressed_obsolete',
                    'evaluation_unknown', 'ambiguous', 'protected'),
        reason_code=ident, snapshot_ref=nullable(ref('Ref')), selected_transition_id=nullable(ident),
        execution_id=nullable(ident), decision_digest=digest)
    d['ExecutionPlanBinding'] = obj(scope=ref('Scope'), run_id=ident, execution_id=ident,
        decision_ref=ref('Ref'), artifact_ref=ref('Ref'), receive_cursor=ref('ReceiveCursor'),
        execution_binding_ref=ref('Ref'), plan_ref=ref('Ref'), expected_steps=counter, sealed=const(True))
    d['DecisionRef'] = obj(run_id=ident, decision_id=ident, decision_digest=digest)
    d['IngressCommit'] = obj(scope=ref('Scope'), commit_id=ident, inbox_ref=ref('Ref'), receive_cursor=ref('ReceiveCursor'),
        source_revision_before=counter, source_revision_after=counter, match_set_ref=ref('Ref'),
        decision_refs=arr(ref('DecisionRef')), decision_set_digest=digest,
        trigger_disposition=enum('eligible_decision_recorded', 'observed_only', 'suppressed', 'rejected'),
        notification_id=ident, commit_digest=digest)
    d['CommittedBatch'] = obj(contract_version=const(VERSION), inbox=ref('InboxContent'), match_set=ref('MatchSet'),
        snapshots=arr(ref('EvaluationSnapshot')), decisions=arr(ref('TriggerDecision')),
        executions=arr(ref('ExecutionPlanBinding')), commit=ref('IngressCommit'))
    d['DesignProfile'] = obj(profile_id=ident, purpose=const('simulation'), runtime_approved=const(False),
        max_target_runs=dict(type='integer', minimum=1, maximum=256), max_total_ast_nodes=positive,
        max_total_plan_steps=positive, max_total_snapshot_bytes=positive, max_total_outbox_bytes=positive,
        writer_deadline_ms=positive)
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SID,
            'title': VERSION + ' 候选；根禁止直接校验，须选择具名defs', 'not': {}, '$defs': d}


ROUTES = [
    ('post', '/api/v1/providers/{provider_id}/events', 'submitProviderEvent', 'SubmitEvent', 'ProviderReceipt', ['200', '202'], 'provider'),
    ('post', '/api/v1/providers/{provider_id}/events/lookup', 'lookupProviderEvent', 'LookupEvent', 'LookupResult', ['200'], 'provider'),
    ('get', '/internal/ingress/commits/{commit_id}', 'readIngressCommit', None, 'CommittedBatch', ['200'], 'internal'),
]


def openapi(source):
    components = {}
    def project(value):
        if isinstance(value, list): return [project(x) for x in value]
        if not isinstance(value, dict): return value
        out = {}
        for key, v in value.items():
            if key == '$ref':
                assert v.startswith('#/$defs/') and '/' not in v[8:]
                name = v[8:]
                if name not in components:
                    components[name] = {}
                    components[name] = project(source['$defs'][name])
                out[key] = '#/components/schemas/' + name
            elif key not in ('$id', '$schema'):
                out[key] = copy.deepcopy(v) if key in ('const', 'enum', 'examples', 'default') else project(v)
        return out
    def content(model): return {'application/json': {'schema': project(ref(model))}}
    paths = {}
    for method, path, op, request, response, success, role in ROUTES:
        parameters = [dict(name='X-LeafSeamer-Contract', **{'in': 'header'}, required=True, schema=const(VERSION))]
        name = 'provider_id' if role == 'provider' else 'commit_id'
        parameters.append(dict(name=name, **{'in': 'path'}, required=True, schema=project(ref('Id'))))
        responses = {code: {'description': '已可靠提交或查原；不表示动作成功', 'content': content(response)} for code in success}
        for code in ('400', '401', '403', '404', '409', '410', '412', '413', '422', '429', '503'):
            responses[code] = {'description': '拒绝或状态不可确认；不授权自动重发', 'content': content('Error')}
        for value in responses.values():
            value['headers'] = {'Cache-Control': {'schema': const('no-store'), 'description': '不可缓存'}}
        record = dict(operationId=op, parameters=parameters, responses=responses,
            security=[{'ProviderBearer': []}] if role == 'provider' else [{'InternalMTLS': []}],
            **{'x-required-permission': 'source.event.submit' if op == 'submitProviderEvent' else
               'source.event.read' if role == 'provider' else 'ingress.internal.read',
               'x-no-automatic-write-retry': True})
        if request: record['requestBody'] = dict(required=True, content=content(request))
        paths.setdefault(path, {})[method] = record
    return dict(openapi='3.1.1', info=dict(title='Seamer规范摄取候选', version=VERSION), paths=paths,
        components=dict(schemas=components, securitySchemes={
            'ProviderBearer': dict(type='http', scheme='bearer'),
            'InternalMTLS': dict(type='mutualTLS')}))


def encoded(value): return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def build(check=False):
    s = schema()
    for name, body in [('ingress.schema.json', s), ('ingress.openapi.json', openapi(s))]:
        path = HERE / name; data = encoded(body)
        if check:
            if path.read_bytes() != data: raise AssertionError('生成漂移: ' + name)
        else: path.write_bytes(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true')
    build(parser.parse_args().check)
