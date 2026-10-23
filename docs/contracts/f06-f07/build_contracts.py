"""生成 F06/F07 候选 Schema；只用于协议资料，不是运行服务。"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC = 'https://leafseamer.invalid/contracts/first-loop.schema.json#/$defs/'


def obj(**fields):
    return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)


def ref(name): return {'$ref': '#/$defs/' + name}
def base(name): return {'$ref': PUBLIC + name}
def enum(*values): return {'enum': list(values)}
def arr(item, maximum=256): return dict(type='array', items=item, maxItems=maximum, uniqueItems=True)
def nullable(value): return {'anyOf': [value, {'type': 'null'}]}


def build():
    ident, rev, digest = base('Id'), base('Revision'), base('Digest')
    boolean = {'type': 'boolean'}
    key = {'type': 'string', 'minLength': 1, 'maxLength': 512, 'pattern': r'^[a-zA-Z0-9_.:-]+(/[a-zA-Z0-9_.:-]+)*$'}
    keys = arr(key)
    anchors = dict(command_id=ident, attempt_id=ident, worker_boot_id=ident, device_session_id=ident,
                   collection_generation=rev, catalog_revision=rev)
    d = {}
    d['CatalogBinding'] = obj(device_id=ident, device_session_id=ident, collection_ref=ident,
        collection_generation=rev, catalog_revision=rev, binding_revision=rev,
        status=enum('unconfirmed', 'ready', 'changing', 'stale'),
        entries=arr(obj(scene_id=ident, obs_scene_uuid={'type':'string','format':'uuid'},
                        display_name={'type':'string','minLength':1,'maxLength':1024})))
    d['ObsEvidenceFrame'] = obj(evidence_id=ident, **anchors, protocol_request_id=ident,
        kind=enum('set_send','set_ack','query_send','query_result'), io_seq=rev, tick_ns=rev,
        success=nullable(boolean), scene_uuid=nullable({'type':'string','format':'uuid'}))
    d['ObsCompletionBundle'] = obj(policy_id={'const':'obs.program_scene.cut.v1'}, **anchors,
        target_scene_uuid={'type':'string','format':'uuid'}, set_request_id=ident, query_request_id=ident,
        frames=dict(type='array',items=ref('ObsEvidenceFrame'),minItems=4,maxItems=4),
        evaluation_tick_ns=rev, deadline_tick_ns=rev,
        max_query_age_ms={'type':'integer','minimum':1,'maximum':60000},
        catalog_current=boolean, fixture_current=boolean, durable=boolean)
    d['EffectFootprint'] = obj(action_ref=ident, manifest_digest=digest, semantics_revision=rev,
        complete=boolean, reads=keys, writes=keys, failure_writes=keys, resources=keys,
        safe_failure_classes=arr(ident))
    d['IndependenceProof'] = obj(proof_id=ident, proof_revision=rev, generator_version=ident,
        definition_digest=digest, bindings_digest=digest, failed_step_id=ident,
        successor_step_ids=arr(ident), failed_footprint=ref('EffectFootprint'),
        successor_reads=keys, successor_writes=keys, successor_resources=keys,
        graph_complete=boolean, control_dependency=boolean, verdict=enum('independent','dependent','unknown'))
    d['RecoverySnapshot'] = obj(preview_id=ident, preview_digest=digest, run_id=ident, run_revision=rev,
        service_boot_id=ident, request_epoch=ident, definition_digest=digest, plan_digest=digest,
        authorization_digest=digest, control_digest=digest, proof_bindings_digest=digest,
        evidence_digest=digest, arm_generation=rev, issued_tick_ns=rev, expires_tick_ns=rev,
        unresolved_command_ids=arr(ident), proposed_step_ids=arr(ident))
    d['RecoveryOperation'] = obj(operation_id=ident, run_id=ident, preview_id=ident, request_digest=digest,
        previous_run_revision=rev, committed_run_revision=rev, recovery_generation=rev,
        state=enum('reserved','preparing','ready','running','completed','paused','indeterminate'),
        new_execution_id=ident, new_command_ids=arr(ident), consumed={'const':True})
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
        '$id':'https://leafseamer.invalid/contracts/f06-f07/contracts.schema.json',
        'title':'F06/F07 候选资料 f06-f07/0.1.0-draft.1', '$defs':d}


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    content=json.dumps(build(),ensure_ascii=False,indent=2)+'\n';path=ROOT/'contracts.schema.json'
    if args.check:
        if path.read_text(encoding='utf-8') != content: raise SystemExit('Schema 生成漂移')
    else:path.write_text(content,encoding='utf-8',newline='\n')
