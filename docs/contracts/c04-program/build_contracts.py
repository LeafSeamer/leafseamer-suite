"""生成自动化程序与依赖证明候选资料；不生成或运行服务。"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = 'automation-program/0.1.0-draft.1'


def obj(**fields):
    return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)


def ref(name): return {'$ref': '#/$defs/' + name}
def enum(*values): return {'enum': list(values)}
def arr(item, maximum=4096, minimum=0, unique=False):
    return dict(type='array', items=item, maxItems=maximum, minItems=minimum, uniqueItems=unique)
def nullable(item): return {'anyOf': [item, {'type': 'null'}]}


def build():
    ident = dict(type='string', minLength=1, maxLength=128, pattern=r'^[A-Za-z0-9_.:-]+$(?![\s\S])')
    digest = dict(type='string', pattern=r'^sha256:[0-9a-f]{64}$(?![\s\S])')
    revision = dict(type='string', pattern=r'^(0|[1-9][0-9]{0,19})$(?![\s\S])')
    pointer = dict(type='string', maxLength=1024, pattern=r'^(?:/(?:[^~/]|~[01])*)*$(?![\s\S])')
    resource = dict(type='string', minLength=1, maxLength=512,
                    pattern=r'^[A-Za-z0-9_:-]+(?:/[A-Za-z0-9_:-]+)*$(?![\s\S])')
    resources = arr(resource, 256, unique=True)
    ids = arr(ident, unique=True)
    d = dict(Id=ident, Digest=digest, Revision=revision, Pointer=pointer, Resource=resource)
    d['ContentRef'] = obj(id=ident, revision=revision, digest=digest)
    d['TypeSpec'] = obj(kind=enum('boolean', 'null', 'string', 'binary64', 'integer_string', 'json'),
                        unit=nullable(ident))
    d['Literal'] = obj(kind={'const': 'literal'}, value={})
    d['Reference'] = obj(kind={'const': 'ref'}, source=enum('event', 'observation', 'machine', 'step_result'),
                         binding_id=ident, pointer=pointer)
    d['Value'] = {'oneOf': [ref('Literal'), ref('Reference')]}
    d['Condition'] = {'oneOf': [
        obj(kind={'const': 'literal'}, value={'type': 'boolean'}),
        obj(kind={'const': 'compare'}, operator=enum('eq', 'ne', 'lt', 'lte', 'gt', 'gte'),
            value_type=ref('TypeSpec'), left=ref('Value'), right=ref('Value')),
        obj(kind=enum('all', 'any'), items=arr(ref('Condition'), 256, 1)),
        obj(kind={'const': 'not'}, item=ref('Condition')),
        obj(kind=enum('exists', 'is_null'), value=ref('Reference'))]}
    d['Projection'] = obj(pointer=pointer, value_type=ref('TypeSpec'), reads=resources)
    d['InputBinding'] = obj(binding_id=ident, source=enum('event', 'observation', 'machine', 'step_result'),
        authority_id=ident, registration_ref=ref('ContentRef'), schema_ref=ref('ContentRef'),
        producer_step_id=nullable(ident), projections=arr(ref('Projection'), 256, 1))
    d['Footprint'] = obj(complete={'type': 'boolean'}, evidence_ref=ref('ContentRef'),
        reads=resources, writes=resources, failure_writes=resources, resources=resources,
        preconditions=resources, target_constraints=resources, safe_failure_classes=arr(ident, 64, unique=True))
    d['ParameterSlot'] = obj(pointer=pointer, value_type=ref('TypeSpec'))
    d['ActionBinding'] = obj(binding_id=ident, authority_id=ident, controller_id=ident,
        device_id=ident, provider_id=ident, capability_id=ident, registration_ref=ref('ContentRef'),
        catalog_ref=ref('ContentRef'), module_ref=ref('ContentRef'), parameter_schema_ref=ref('ContentRef'),
        result_schema_ref=ref('ContentRef'), parameter_slots=arr(ref('ParameterSlot'), 256), footprint=ref('Footprint'))
    d['ParameterBinding'] = obj(target_pointer=pointer, value=ref('Value'))
    common = dict(step_id=ident, depends_on=ids, required={'type': 'boolean'},
                  failure_policy=enum('stop', 'continue_if_independent'))
    d['ActionStep'] = obj(**common, kind={'const': 'action'}, action_binding_id=ident,
        parameters={'type': 'object'}, parameter_bindings=arr(ref('ParameterBinding'), 256), guard=ref('Condition'))
    d['DelayStep'] = obj(step_id=ident, depends_on=ids, required={'const': True},
        failure_policy={'const': 'stop'}, kind={'const': 'delay'},
        delay_ms=dict(type='integer', minimum=0, maximum=86400000),
        max_lateness_ms=dict(type='integer', minimum=1, maximum=60000))
    d['Step'] = {'oneOf': [ref('ActionStep'), ref('DelayStep')]}
    d['Group'] = obj(mode=enum('sequence', 'parallel'), steps=arr(ref('Step'), 64, 1))
    d['Rule'] = obj(kind={'const': 'rule'}, trigger_binding_id=ident,
                    condition=ref('Condition'), groups=arr(ref('Group'), 64, 1))
    d['Transition'] = obj(transition_id=ident, from_state=ident, to_state=ident,
        priority=dict(type='integer', minimum=-2147483648, maximum=2147483647),
        trigger_binding_id=ident, condition=ref('Condition'),
        exit=arr(ref('Step'), 64), transition=arr(ref('Step'), 64), enter=arr(ref('Step'), 64))
    d['StateMachine'] = obj(kind={'const': 'state_machine'}, states=arr(ident, 256, 1, True),
        initial_state=ident, transitions=arr(ref('Transition'), 256, 1))
    d['Program'] = {'oneOf': [ref('Rule'), ref('StateMachine')]}
    d['AliasTable'] = obj(ref=ref('ContentRef'), entries=arr(obj(logical=resource, physical=resource), 256))
    d['Edge'] = obj(from_step_id=ident, to_step_id=ident,
                    edge_kind=enum('sequence', 'requires_success', 'data', 'guard', 'resource'))
    d['Graph'] = obj(graph_version={'const': 'automation-graph/1'}, nodes=ids,
                     edges=arr(ref('Edge'), 131072, unique=True), alias_table_ref=ref('ContentRef'))
    d['CompiledProgram'] = obj(dsl_version={'const': VERSION}, compiler_version=ident,
        definition_id=ident, definition_version=revision, policy_ref=ref('ContentRef'),
        program=ref('Program'), input_bindings=arr(ref('InputBinding')), action_bindings=arr(ref('ActionBinding')),
        alias_table=ref('AliasTable'), graph_digest=digest)
    d['IndependenceProof'] = obj(proof_version={'const': VERSION}, generator_version=ident,
        program_digest=digest, bindings_digest=digest, graph_digest=digest,
        failed_step_id=ident, successor_step_ids=ids,
        footprint_binding_digests=arr(digest, unique=True), verdict=enum('independent', 'dependent', 'unknown'))
    d['PublishedArtifact'] = obj(artifact_version={'const': VERSION}, artifact_id=ident,
        program_digest=digest, bindings_digest=digest, proof_refs=arr(ref('ContentRef')),
        publisher_ref=ref('ContentRef'), review_ref=ref('ContentRef'), manifest_digest=digest)
    d['CompileDiagnostic'] = obj(code=ident, definition_path=pointer, related_paths=arr(pointer, 256),
        budget=nullable(obj(kind=ident, limit=dict(type='integer', minimum=0), observed=dict(type='integer', minimum=0))))
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'https://leafseamer.invalid/design/c04-program/program.schema.json',
            'title': 'C04 程序与证明候选，尚未批准', 'not': {}, '$defs': d}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--check', action='store_true'); a = p.parse_args()
    raw = (json.dumps(build(), ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    target = ROOT / 'program.schema.json'
    if a.check:
        if target.read_bytes() != raw: raise SystemExit('Schema生成字节漂移')
    else: target.write_bytes(raw)


if __name__ == '__main__': main()
