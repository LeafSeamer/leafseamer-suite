"""生成C04生命周期候选Schema与HTTP；仅设计资料，不实现服务。"""
import argparse
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = 'automation-lifecycle/0.1.0-draft.1'
SID = 'https://leafseamer.invalid/design/c04-lifecycle/lifecycle.schema.json'
PROGRAM = 'https://leafseamer.invalid/design/c04-program/program.schema.json'


def ref(name): return {'$ref': '#/$defs/' + name}
def p_ref(name): return {'$ref': PROGRAM + '#/$defs/' + name}
def obj(**fields): return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)
def arr(item, maximum=4096, minimum=0): return dict(type='array', items=item, minItems=minimum, maxItems=maximum)
def enum(*values): return {'enum': list(values)}
def const(value): return {'const': value}
def null(value): return {'anyOf': [value, {'type': 'null'}]}
def text(maximum=256): return dict(type='string', maxLength=maximum)


def models():
    d = {name: p_ref(name) for name in ('Id', 'Revision', 'Digest')}
    ident, rev, digest = ref('Id'), ref('Revision'), ref('Digest')
    d['Scope'] = obj(authority_service_id=ident, database_instance_id=ident)
    d['Context'] = obj(context_id=ident, idempotency_key=ident)
    d['ClockRef'] = obj(clock_domain_id=dict(type='string', pattern=r'^clock_[0-9a-f]{64}$(?![\s\S])'), descriptor_digest=digest)
    kinds = ['artifact', 'source_registration', 'inbox', 'observation', 'age_evidence', 'input_snapshot', 'grant',
             'barrier', 'completion_evidence', 'policy', 'proof', 'resolved_parameters', 'command', 'preparation_receipt']
    for kind in kinds:
        d[kind.title().replace('_', '') + 'Ref'] = obj(kind=const(kind), scope=ref('Scope'), object_id=ident, revision=rev, digest=digest)
    d['DefinitionMetadata'] = obj(name=dict(type='string', minLength=1, maxLength=128), description=text(4096), layout={'type': 'object'})
    d['BindingSelection'] = obj(binding_id=ident, kind=enum('input', 'action'), content_ref=p_ref('ContentRef'))
    d['DraftContent'] = obj(program=p_ref('Program'), selections=arr(ref('BindingSelection')), policy_ref=ref('PolicyRef'))
    d['DraftRecord'] = obj(scope=ref('Scope'), definition_id=ident, revision=rev, content=ref('DraftContent'), content_digest=digest, selection_digest=digest,
        metadata_revision=rev, metadata=ref('DefinitionMetadata'))
    d['PublishedVersion'] = obj(scope=ref('Scope'), definition_id=ident, definition_version=rev, source_draft_revision=rev,
        artifact_ref=ref('ArtifactRef'), program_digest=digest, bindings_digest=digest, published_by=ident)
    d['ActivationSlot'] = obj(scope=ref('Scope'), definition_id=ident, revision=rev, active_run_id=null(ident), definition_version=null(rev))
    d['BusinessState'] = obj(state_id=ident, revision=rev)
    d['RunRecord'] = obj(scope=ref('Scope'), run_id=ident, definition_id=ident, definition_version=rev, artifact_ref=ref('ArtifactRef'),
        revision=rev, lifecycle=enum('disarmed', 'armed', 'running', 'paused', 'completed'), business_state=null(ref('BusinessState')),
        arm_generation=rev, last_receive_seq=rev, active_execution_id=null(ident), active_operation_id=null(ident),
        last_execution_id=null(ident), pause_latches=arr(ident, 256), dispatch_eligible={'type': 'boolean'})
    d['DependencyBaseline'] = obj(run_revision=rev, slot_revision=rev, artifact_ref=ref('ArtifactRef'), arm_generation=rev,
        bindings_digest=digest, authorization_digest=digest, control_digest=digest, source_digest=digest, evidence_digest=digest,
        policy_ref=ref('PolicyRef'), business_state=null(ref('BusinessState')))
    d['TargetCheck'] = obj(controller_id=ident, device_ids=arr(ident), grant_ref=null(ref('GrantRef')),
        status=enum('passed', 'failed', 'unknown'), reason_code=ident)
    d['Preflight'] = obj(scope=ref('Scope'), preflight_id=ident, run_id=ident, purpose=const('arm'),
        baseline=ref('DependencyBaseline'), clock=ref('ClockRef'), issued_tick_ns=rev, expires_tick_ns=rev,
        checks=arr(ref('TargetCheck'), 256), passed={'type': 'boolean'}, preflight_digest=digest)
    d['PreparationTarget'] = obj(controller_id=ident, device_ids=arr(ident),
        baseline_grant_ref=null(ref('GrantRef')), target_grant_ref=null(ref('GrantRef')),
        state=enum('pending', 'applied', 'closing', 'closed', 'unknown'), receipt_ref=null(ref('PreparationReceiptRef')),
        barrier_ref=null(ref('BarrierRef')))
    d['LifecycleOperation'] = obj(scope=ref('Scope'), operation_id=ident, run_id=ident,
        kind=enum('arm', 'pause', 'disarm', 'retire', 'resume'), request_digest=digest,
        baseline=ref('DependencyBaseline'), committed_run_revision=rev, committed_slot_revision=rev,
        target_arm_generation=rev, state=enum('reserved', 'preparing', 'ready', 'running', 'reconciling', 'completed', 'paused', 'indeterminate'),
        execution_id=null(ident), consumed_preflight_id=null(ident), consumed_preview_id=null(ident),
        targets=arr(ref('PreparationTarget'), 256), locally_closed={'type': 'boolean'}, protection_complete={'type': 'boolean'})
    d['SourceObservation'] = obj(binding_id=ident, registration_ref=ref('SourceRegistrationRef'),
        observation_ref=ref('ObservationRef'), age_evidence_ref=ref('AgeEvidenceRef'), status=enum('available', 'missing_field', 'unavailable'))
    d['TransitionEvaluation'] = obj(transition_id=ident, priority=dict(type='integer', minimum=-2147483648, maximum=2147483647),
        result=enum('true', 'false', 'unknown'))
    d['EvaluationSnapshot'] = obj(scope=ref('Scope'), snapshot_id=ident, run_id=ident, run_revision=rev,
        artifact_ref=ref('ArtifactRef'), inbox_ref=ref('InboxRef'), receive_seq=rev, source_state=null(ref('BusinessState')),
        clock=ref('ClockRef'), observations=arr(ref('SourceObservation')), input_snapshot_ref=ref('InputSnapshotRef'),
        rule_result=null(enum('true', 'false', 'unknown')), transitions=arr(ref('TransitionEvaluation'), 256), snapshot_digest=digest)
    d['TriggerDecision'] = obj(scope=ref('Scope'), decision_id=ident, run_id=ident, run_revision_before=rev, definition_version=rev,
        artifact_ref=ref('ArtifactRef'), inbox_ref=ref('InboxRef'), receive_seq=rev, snapshot_id=null(ident), snapshot_digest=null(digest),
        result=enum('accepted', 'no_match', 'suppressed_busy', 'suppressed_inactive', 'suppressed_obsolete', 'evaluation_unknown', 'ambiguous', 'protected'),
        reason_code=ident, selected_transition_id=null(ident), execution_id=null(ident), decision_digest=digest)
    d['ExecutionOrigin'] = {'oneOf': [obj(kind=const('trigger'), decision_id=ident, decision_digest=digest),
        obj(kind=const('recovery'), operation_id=ident, preview_id=ident, preview_digest=digest, prior_execution_id=null(ident))]}
    d['ExecutionBinding'] = obj(scope=ref('Scope'), execution_id=ident, run_id=ident, artifact_ref=ref('ArtifactRef'),
        origin=ref('ExecutionOrigin'), arm_generation=rev, source_state=null(ref('BusinessState')), target_state_id=null(ident),
        input_snapshot_ref=ref('InputSnapshotRef'), resolved_parameters_ref=ref('ResolvedParametersRef'),
        grants=arr(ref('GrantRef'), 256), clock=ref('ClockRef'), plan_digest=digest, binding_digest=digest)
    d['ExecutionRecord'] = obj(binding=ref('ExecutionBinding'), revision=rev,
        phase=enum('reserved', 'validating', 'exit', 'transition', 'enter', 'sequence', 'commit', 'reconciling', 'finished'),
        outcome=enum('pending', 'succeeded', 'completed_with_failures', 'failed', 'unknown', 'blocked'),
        unresolved_command_refs=arr(ref('CommandRef')), completion_evidence_refs=arr(ref('CompletionEvidenceRef')),
        state_commit_event_id=null(ident))
    d['RecoveryPlanItem'] = obj(step_id=ident, disposition=enum('retain_success', 'execute_new', 'reconcile_commit'),
        previous_command_ref=null(ref('CommandRef')), evidence_refs=arr(ref('CompletionEvidenceRef')),
        parameters_ref=null(ref('ResolvedParametersRef')))
    d['RecoveryPreview'] = obj(scope=ref('Scope'), preview_id=ident, run_id=ident, prior_execution_id=null(ident),
        baseline=ref('DependencyBaseline'), clock=ref('ClockRef'), request_epoch=ident,
        issued_tick_ns=rev, expires_tick_ns=rev, trigger_decision_id=null(ident),
        plan=arr(ref('RecoveryPlanItem')), unresolved_command_refs=arr(ref('CommandRef')), preview_digest=digest)
    # 请求只携带选择和CAS，不接收客户端伪造的编译产物、ready或grant状态。
    ctx = dict(context=ref('Context'))
    d['CreateDefinition'] = obj(**ctx, content=ref('DraftContent'), metadata=ref('DefinitionMetadata'))
    d['UpdateDraft'] = obj(**ctx, expected_draft_revision=rev, content=ref('DraftContent'))
    d['UpdateMetadata'] = obj(**ctx, expected_metadata_revision=rev, metadata=ref('DefinitionMetadata'))
    d['Publish'] = obj(**ctx, expected_draft_revision=rev, expected_content_digest=digest, expected_selection_digest=digest)
    d['CreateRun'] = obj(**ctx, definition_id=ident, definition_version=rev, expected_artifact_ref=ref('ArtifactRef'))
    d['InspectRun'] = obj(**ctx, expected_run_revision=rev, expected_slot_revision=rev)
    d['Arm'] = obj(**ctx, expected_run_revision=rev, expected_slot_revision=rev, preflight_id=ident, preflight_digest=digest)
    d['ProtectRun'] = obj(**ctx, expected_run_revision=rev, reason_code=ident)
    d['Resume'] = obj(**ctx, expected_run_revision=rev, expected_slot_revision=rev, preview_id=ident, preview_digest=digest)
    d['Lookup'] = obj(context_id=ident, idempotency_key=ident, operation_id=ident)
    d['LookupResult'] = obj(operation_id=ident, request_digest=digest,
        result={'oneOf': [obj(kind=const(name), value=ref(name)) for name in
            ('DraftRecord', 'PublishedVersion', 'RunRecord', 'Preflight', 'RecoveryPreview', 'LifecycleOperation')]})
    d['Error'] = obj(code=ident, correlation_id=ident, diagnostics=arr(p_ref('CompileDiagnostic'), 64))
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SID,
            'title': 'C04生命周期候选，尚未批准', 'not': {}, '$defs': d}


ROUTES = [
    ('post', '/api/v1/definitions', 'createDefinition', 'CreateDefinition', 'DraftRecord', 201, 'definition.edit', 'both'),
    ('get', '/api/v1/definitions/{definition_id}/draft', 'getDraft', None, 'DraftRecord', 200, 'definition.read', 'both'),
    ('put', '/api/v1/definitions/{definition_id}/draft', 'updateDraft', 'UpdateDraft', 'DraftRecord', 200, 'definition.edit', 'both'),
    ('put', '/api/v1/definitions/{definition_id}/metadata', 'updateDefinitionMetadata', 'UpdateMetadata', 'DraftRecord', 200, 'definition.edit', 'both'),
    ('post', '/api/v1/definitions/{definition_id}/publish', 'publishDefinition', 'Publish', 'PublishedVersion', 201, 'definition.publish', 'human'),
    ('get', '/api/v1/definitions/{definition_id}/versions/{definition_version}', 'getDefinitionVersion', None, 'PublishedVersion', 200, 'definition.read', 'both'),
    ('get', '/api/v1/definitions/{definition_id}/versions/{definition_version}/program', 'getCompiledProgram', None, 'Program_CompiledProgram', 200, 'definition.read', 'both'),
    ('get', '/api/v1/definitions/{definition_id}/versions/{definition_version}/artifact', 'getPublishedArtifact', None, 'Program_PublishedArtifact', 200, 'definition.read', 'both'),
    ('get', '/api/v1/definitions/{definition_id}/proofs/{proof_id}', 'getIndependenceProof', None, 'Program_IndependenceProof', 200, 'definition.read', 'both'),
    ('get', '/api/v1/definitions/{definition_id}/activation-slot', 'getActivationSlot', None, 'ActivationSlot', 200, 'run.read', 'both'),
    ('post', '/api/v1/runs', 'createRun', 'CreateRun', 'RunRecord', 201, 'run.manage', 'both'),
    ('get', '/api/v1/runs/{run_id}', 'getRun', None, 'RunRecord', 200, 'run.read', 'both'),
    ('post', '/api/v1/runs/{run_id}/preflight', 'preflightRun', 'InspectRun', 'Preflight', 200, 'run.read', 'both'),
    ('post', '/api/v1/runs/{run_id}/arm', 'armRun', 'Arm', 'LifecycleOperation', 202, 'run.arm', 'human'),
    ('post', '/api/v1/runs/{run_id}/pause', 'pauseRun', 'ProtectRun', 'LifecycleOperation', 202, 'run.pause', 'both'),
    ('post', '/api/v1/runs/{run_id}/disarm', 'disarmRun', 'ProtectRun', 'LifecycleOperation', 202, 'run.disarm', 'human'),
    ('post', '/api/v1/runs/{run_id}/retire', 'retireRun', 'ProtectRun', 'LifecycleOperation', 202, 'run.retire', 'human'),
    ('post', '/api/v1/runs/{run_id}/recovery-preview', 'previewRecovery', 'InspectRun', 'RecoveryPreview', 200, 'run.read', 'both'),
    ('post', '/api/v1/runs/{run_id}/resume', 'resumeRun', 'Resume', 'LifecycleOperation', 202, 'run.resume', 'human'),
    ('get', '/api/v1/run-operations/{operation_id}', 'getRunOperation', None, 'LifecycleOperation', 200, 'run.read', 'both'),
    ('get', '/api/v1/recovery-operations/{operation_id}', 'getRecoveryOperation', None, 'LifecycleOperation', 200, 'run.read', 'both'),
    ('get', '/api/v1/runs/{run_id}/executions/{execution_id}', 'getExecution', None, 'ExecutionRecord', 200, 'run.read', 'both'),
    ('get', '/api/v1/runs/{run_id}/decisions/{decision_id}', 'getTriggerDecision', None, 'TriggerDecision', 200, 'run.read', 'both'),
    ('post', '/api/v1/automation-requests/lookup', 'lookupAutomationRequest', 'Lookup', 'LookupResult', 200, 'request.read', 'both')]


def build():
    schema = models(); d = copy.deepcopy(schema['$defs'])
    program = json.loads((ROOT.parent / 'c04-program/program.schema.json').read_bytes())
    # 仅固定两资源，跳过实例const/enum/default/examples，绝不联网取引用。
    def inline(value):
        if isinstance(value, list): return [inline(x) for x in value]
        if not isinstance(value, dict): return value
        out = {}
        for key, v in value.items():
            if key == '$ref':
                resource, name = v.split('#/$defs/')
                if resource in ('', SID): out[key] = '#/$defs/' + name
                else:
                    assert resource == PROGRAM, v
                    target = 'Program_' + name; out[key] = '#/$defs/' + target
                    if target not in d:
                        d[target] = {}
                        def program_refs(x):
                            if isinstance(x, list): return [program_refs(a) for a in x]
                            if not isinstance(x, dict): return x
                            return {k: PROGRAM + a if k == '$ref' and a.startswith('#/') else
                                copy.deepcopy(a) if k in ('const', 'enum', 'default', 'examples') else program_refs(a) for k, a in x.items()}
                        d[target] = inline(program_refs(program['$defs'][name]))
            else: out[key] = copy.deepcopy(v) if key in ('const', 'enum', 'default', 'examples') else inline(v)
        return out
    for name, value in list(d.items()): d[name] = inline(value)
    for name in ('IndependenceProof', 'CompiledProgram', 'PublishedArtifact'): inline(p_ref(name))
    def project(value):
        if isinstance(value, list): return [project(x) for x in value]
        if not isinstance(value, dict): return value
        return {k: v.replace('#/$defs/', '#/components/schemas/') if k == '$ref' else
            copy.deepcopy(v) if k in ('const', 'enum', 'default', 'examples') else project(v) for k, v in value.items()}
    paths = {}
    for method, path, operation, request, response, status, permission, subjects in ROUTES:
        security = [{'humanSession': [], **({'csrf': []} if method != 'get' else {})}]
        if subjects == 'both': security.append({'serviceToken': []})
        parameters = [dict(name='X-LeafSeamer-Contract', **{'in': 'header'}, required=True, schema=const(VERSION))]
        parameters += [dict(name=n, **{'in': 'path'}, required=True, schema={'$ref': '#/components/schemas/' +
            ('Revision' if n == 'definition_version' else 'Id')}) for n in re.findall(r'\{([^}]+)\}', path)]
        if operation == 'getIndependenceProof':
            parameters.append(dict(name='revision', **{'in': 'query'}, required=True, schema={'$ref': '#/components/schemas/Revision'}))
        op = dict(operationId=operation, security=security, parameters=parameters,
            **{'x-permission': permission, 'x-subject-kinds': ['human', 'service'] if subjects == 'both' else ['human'],
               'x-no-automatic-write-retry': method != 'get'}, responses={})
        if request: op['requestBody'] = dict(required=True, content={'application/json': {'schema': {'$ref': '#/components/schemas/' + request}}})
        for code, model in [(status, response)] + [(c, 'Error') for c in (400, 401, 403, 404, 409, 412, 413, 422, 429, 503)]:
            op['responses'][str(code)] = dict(description='可靠受理，非设备完成' if code == 202 else '操作结果或明确拒绝；错误不授权重发',
                headers={'Cache-Control': {'schema': const('no-store')}}, content={'application/json': {'schema': {'$ref': '#/components/schemas/' + model}}})
        paths.setdefault(path, {})[method] = op
    api = dict(openapi='3.1.1', info=dict(title='Seamer自动化生命周期候选', version=VERSION), paths=paths,
        components=dict(schemas=project(d), securitySchemes=dict(humanSession=dict(type='http', scheme='bearer'),
            serviceToken=dict(type='http', scheme='bearer'), csrf=dict(type='apiKey', **{'in': 'header'}, name='X-CSRF-Token'))))
    return {'lifecycle.schema.json': schema, 'lifecycle.openapi.json': api}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--check', action='store_true'); a = p.parse_args()
    for name, value in build().items():
        data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if a.check: assert (ROOT / name).read_bytes() == data, name
        else: (ROOT / name).write_bytes(data)
