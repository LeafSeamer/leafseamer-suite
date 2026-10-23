"""F04/F05 候选结构资料；不生成业务代码或变更既有协议。"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = 'https://leafseamer.invalid/contracts/first-loop.schema.json#/$defs/'


def obj(**p): return {'type': 'object', 'properties': p, 'required': list(p), 'additionalProperties': False}
def ref(n): return {'$ref': '#/$defs/' + n}
def base(n): return {'$ref': BASE + n}
def enum(*v): return {'enum': list(v)}
def nullable(s): return {'anyOf': [s, {'type': 'null'}]}
def arr(s, maximum=256, unique=False): return {'type': 'array', 'items': s, 'maxItems': maximum, 'uniqueItems': unique}
def integer(minimum=0, maximum=9007199254740991): return {'type': 'integer', 'minimum': minimum, 'maximum': maximum}
def when(p, then, otherwise=None):
    v = {'if': {'properties': p, 'required': list(p)}, 'then': {'properties': then}}
    if otherwise is not None: v['else'] = {'properties': otherwise}
    return v


def build():
    d = {}; ident = base('Id'); rev = base('Revision'); nil = {'type': 'null'}; stamp = base('Timestamp')
    d['AuthorizationSnapshot'] = obj(snapshot_id=ident, issuer_id=ident, issuer_epoch=ident, issuer_revision=rev,
        audience=ident, principal_kind=enum('human','service'), principal_id=ident, session_id=nullable(ident),
        credential_id=ident, subject_revision=rev, session_revision=nullable(rev), policy_revision=rev,
        permissions=arr(ident, unique=True), scope_digest=base('Digest'), challenge_id=ident,
        validity=obj(not_before=stamp, expires_at=stamp), fresh_for_ms=integer(1,60000), state=enum('active','revoked','expired'))
    d['AuthorizationSnapshot']['allOf'] = [when({'principal_kind': {'const':'human'}},
        {'session_id':ident,'session_revision':rev}, {'session_id':nil,'session_revision':nil})]
    d['AuthorizationBinding'] = obj(issuer_id=ident, issuer_epoch=ident, audience=ident, principal_kind=enum('human','service'),
        principal_id=ident, origin=enum('manual','automation'), session_id=nullable(ident), credential_id=ident,
        subject_revision=rev, session_revision=nullable(rev), policy_revision=rev, scope_digest=base('Digest'),
        grant_id=nullable(ident), grant_revision=nullable(rev), arm_generation=nullable(rev),
        extension_instance_id=nullable(ident), extension_approval_revision=nullable(rev))
    d['AuthorizationBinding']['allOf'] = [
        when({'principal_kind':{'const':'human'}}, {'session_id':ident,'session_revision':rev,'origin':{'const':'manual'}},
             {'session_id':nil,'session_revision':nil}),
        when({'origin':{'const':'automation'}}, {'principal_kind':{'const':'service'},'grant_id':ident,'grant_revision':rev,'arm_generation':rev},
             {'grant_id':nil,'grant_revision':nil,'arm_generation':nil}),
        when({'extension_instance_id':{'type':'null'}}, {'extension_approval_revision':nil}, {'extension_approval_revision':rev})]
    d['ExecutionGuard'] = obj(guard_id=ident, permit_id=ident, command_id=ident, device_id=ident,
        controller_boot_id=ident, worker_boot_id=ident, ipc_session_id=ident, binding=ref('AuthorizationBinding'),
        authorization_revision=rev, authorization_deadline_tick_ns=rev, clock_domain_id=ident,
        clock_generation=nullable(ident), time_policy_revision=nullable(rev), time_required={'type':'boolean'},
        capacity_reservation_id=ident, guard_digest=base('Digest'))
    d['ExecutionGuard']['allOf'] = [when({'time_required':{'const':True}},
        {'clock_generation':ident,'time_policy_revision':rev}, {'clock_generation':nil,'time_policy_revision':nil})]
    d['RevocationSelector'] = obj(kind=enum('session','principal','credential','grant','extension','trust'),
        issuer_id=ident, issuer_epoch=ident, target_id=ident, revision_floor=rev)
    d['RevocationReceipt'] = obj(operation_id=ident, target_service_id=ident, service_boot_id=ident, selector=ref('RevocationSelector'),
        observed_revision=rev, gate_revision=nullable(rev), state=enum('pending','applied','indeterminate'),
        barrier_id=nullable(ident), closed_subscription_ids=arr(ident,unique=True), invalidated_permit_ids=arr(ident,unique=True),
        in_flight_command_ids=arr(ident,unique=True), unresolved_command_ids=arr(ident,unique=True), durable={'type':'boolean'})
    d['RevocationReceipt']['allOf'] = [when({'state':{'const':'applied'}},
        {'barrier_id':ident,'gate_revision':rev,'durable':{'const':True}})]
    d['RevocationRecord'] = obj(operation_id=ident, selector=ref('RevocationSelector'), issuer_commit_revision=rev,
        target_service_ids={**arr(ident,unique=True),'minItems':1},state=enum('accepted','applying','applied','indeterminate'),
        receipts=arr(ref('RevocationReceipt')),reason=ident,audit_id=ident)
    d['ClockSample'] = obj(sample_id=ident, provider_id=ident, provider_boot_id=ident, host_boot_id=ident,
        clock_domain_id=ident, clock_generation=ident, policy_revision=rev, source_ref=ident,
        source_auth=enum('nts','trusted_network','unverified'), mode=enum('system_disciplined','application_offset'),
        sample_tick_ns=rev, estimated_utc_ms=integer(), uncertainty_ms=nullable(integer(0,86400000)),
        drift_bound_ppm=integer(0,10000), max_sample_age_ms=integer(1,86400000), quality=enum('synchronized','degraded','unsynchronized'))
    d['ClockAssessment'] = obj(sample_id=ident, clock_domain_id=ident, clock_generation=ident, policy_revision=rev,
        evaluated_tick_ns=rev, sample_age_ms=nullable(integer()), uncertainty_now_ms=nullable(integer()),
        utc_lower_ms=nullable(integer()),utc_upper_ms=nullable(integer()),eligible_for_absolute={'type':'boolean'},reason_code=ident)
    d['ClockAssessment']['allOf'] = [when({'eligible_for_absolute':{'const':True}},
        {k:integer() for k in ('sample_age_ms','uncertainty_now_ms','utc_lower_ms','utc_upper_ms')})]
    d['ScheduleGuard'] = obj(occurrence_id=ident, definition_version=base('Version'), clock_generation=ident,
        time_policy_revision=rev,not_before=stamp,not_after=stamp,window_enter_tick_ns=rev,queue_deadline_tick_ns=rev,
        health_latched={'type':'boolean'},block_reason=nullable(ident))
    d['ScheduleGuard']['allOf'] = [when({'health_latched':{'const':True}}, {'block_reason':ident}, {'block_reason':nil})]
    d['EventAgeProof'] = obj(event_id=ident,provider_boot_id=ident,source_sequence=rev,
        basis=enum('trusted_utc','causal_capture','unproven'),capture_sample_id=nullable(ident),
        lower_age_ms=nullable(integer()),upper_age_ms=nullable(integer()),challenge_id=nullable(ident),scope_digest=base('Digest'))
    d['EventAgeProof']['allOf'] = [
        when({'basis':{'const':'unproven'}}, {'lower_age_ms':nil,'upper_age_ms':nil}, {'lower_age_ms':integer(),'upper_age_ms':integer()}),
        when({'basis':{'const':'causal_capture'}}, {'challenge_id':ident}),
        when({'basis':{'const':'trusted_utc'}}, {'capture_sample_id':ident})]
    d['WsTicketBinding'] = obj(binding_id=ident,session_id=ident,audience=ident,origin={'type':'string','format':'uri','pattern':'^https://'},
        client_instance_id=ident,issuer_epoch=ident,scope_digest=base('Digest'),expires_at=stamp,consumed={'type':'boolean'})
    d['AdmissionDecision'] = obj(request_ref=ident,decision=enum('accepted','rejected'),reason_code=ident,
        profile_id=ident,profile_revision=rev,limited_dimension=nullable(ident),retry_after_ms=nullable(integer(0,86400000)),
        reservation_id=nullable(ident),command_id=nullable(ident))
    d['AdmissionDecision']['allOf'] = [when({'decision':{'const':'accepted'}},
        {'reservation_id':ident,'command_id':ident,'limited_dimension':nil}, {'reservation_id':nil,'command_id':nil})]
    group_fields = {
        'identity': ['access_token_ms','session_absolute_ms','recent_auth_ms','refresh_idle_ms','snapshot_fresh_ms','snapshot_refresh_ms',
                     'gate_lease_ms','gate_renew_ms','local_revoke_alarm_ms','remote_revoke_alarm_ms','ws_ticket_ms','pairing_ms','bootstrap_ms'],
        'clock': ['max_sample_age_ms','max_uncertainty_ms','drift_bound_ppm'],
        'capacity': ['http_bytes','frame_bytes','json_depth','devices','workers','command_queue','device_command_queue',
                     'writer_queue','evidence_queue','protection_queue','ipc_normal_slots','ipc_protection_slots','barrier_intents',
                     'requests_per_second','request_burst','login_per_minute','login_burst','gui_events','gui_bytes','source_events','source_bytes',
                     'min_disk_free_bytes','max_wal_bytes','max_reserved_bytes'],
        'retention': ['context_ms','terminal_detail_days','audit_days']}
    d['CapacityProfile'] = obj(profile_id=ident,revision=rev,purpose=enum('simulation','release_candidate'),
        validated_environment=nullable(ident),evidence_ref=nullable(ident),
        **{group:obj(**{k:integer(1) for k in fields}) for group,fields in group_fields.items()})
    d['CapacityProfile']['allOf'] = [when({'purpose':{'const':'release_candidate'}}, {'validated_environment':ident,'evidence_ref':ident})]
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
            '$id':'https://leafseamer.invalid/contracts/f04-f05/contracts.schema.json',
            'title':'F04/F05 候选模型库；按指定 $defs 校验，不替代公共 draft.2', '$defs':d}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    content=json.dumps(build(),ensure_ascii=False,indent=2)+'\n'; path=ROOT/'contracts.schema.json'
    if args.check:
        if path.read_text(encoding='utf-8')!=content: raise SystemExit('F04/F05 模型生成漂移')
    else: path.write_text(content,encoding='utf-8',newline='\n')
    print('F04/F05 模型生成一致')


if __name__=='__main__':main()
