"""独立人工编排的快照／边界向量；不是服务或故障测试实现。"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import rfc8785

ROOT=Path(__file__).resolve().parent
DIGEST='sha256:'+'2'*64


def build():
    profile=json.loads((ROOT/'simulation-profile.json').read_text(encoding='utf-8'))
    snapshot=dict(snapshot_id='snapshot-demo',issuer_id='issuer-demo',issuer_epoch='issuer-epoch',issuer_revision='9',audience='controller-a',
        principal_kind='human',principal_id='human-a',session_id='session-a',credential_id='credential-a',subject_revision='3',
        session_revision='2',policy_revision='4',permissions=['device.command'],scope_digest=DIGEST,challenge_id='challenge-a',
        validity=dict(not_before='2026-10-17T00:00:00.000Z',expires_at='2026-10-17T01:00:00.000Z'),fresh_for_ms=2000,state='active')
    binding={k:snapshot[k] for k in ('issuer_id','issuer_epoch','audience','principal_kind','principal_id','session_id','credential_id',
                                    'subject_revision','session_revision','policy_revision','scope_digest')}
    binding.update(origin='manual',grant_id=None,grant_revision=None,arm_generation=None,extension_instance_id=None,extension_approval_revision=None)
    service=dict(binding,principal_kind='service',principal_id='service-a',session_id=None,session_revision=None,credential_id='svc-credential',
                 origin='automation',grant_id='grant-a',grant_revision='3',arm_generation='5')
    guard=dict(guard_id='guard-a',permit_id='permit-a',command_id='command-a',device_id='device-a',controller_boot_id='cb-a',worker_boot_id='wb-a',
        ipc_session_id='ipc-a',binding=binding,authorization_revision='9',authorization_deadline_tick_ns='2000000000',clock_domain_id='clock-a',
        clock_generation=None,time_policy_revision=None,time_required=False,capacity_reservation_id='reserve-a')
    guard['guard_digest']='sha256:'+hashlib.sha256(rfc8785.dumps(guard)).hexdigest()
    selector=dict(kind='session',issuer_id='issuer-demo',issuer_epoch='issuer-epoch',target_id='session-a',revision_floor='3')
    receipt=dict(operation_id='revoke-a',target_service_id='controller-a',service_boot_id='cb-a',selector=deepcopy(selector),observed_revision='10',gate_revision='5',state='applied',
        barrier_id='auth-barrier-a',closed_subscription_ids=['sub-a'],invalidated_permit_ids=['permit-a'],in_flight_command_ids=[],
        unresolved_command_ids=[],durable=True)
    record=dict(operation_id='revoke-a',selector=selector,issuer_commit_revision='10',target_service_ids=['controller-a'],state='applied',
        receipts=[receipt],reason='logout',audit_id='audit-a')
    sample=dict(sample_id='sample-a',provider_id='clock-provider',provider_boot_id='provider-boot',host_boot_id='host-boot',clock_domain_id='clock-a',
        clock_generation='generation-a',policy_revision='2',source_ref='source-demo',source_auth='trusted_network',mode='application_offset',
        sample_tick_ns='1000000000',estimated_utc_ms=100000,uncertainty_ms=10,drift_bound_ppm=100,max_sample_age_ms=10000,quality='synchronized')
    assessment=dict(sample_id='sample-a',clock_domain_id='clock-a',clock_generation='generation-a',policy_revision='2',evaluated_tick_ns='2000000000',
        sample_age_ms=1000,uncertainty_now_ms=11,utc_lower_ms=100989,utc_upper_ms=101011,eligible_for_absolute=True,reason_code='CLOCK_ELIGIBLE')
    models={
        'AuthorizationSnapshot':snapshot,'AuthorizationBinding':binding,'ExecutionGuard':guard,'RevocationSelector':selector,
        'RevocationReceipt':receipt,'RevocationRecord':record,'ClockSample':sample,'ClockAssessment':assessment,
        'ScheduleGuard':dict(occurrence_id='occurrence-a',definition_version='1.0.0-draft.2',clock_generation='generation-a',time_policy_revision='2',
            not_before='2026-10-17T00:00:00.000Z',not_after='2026-10-17T00:00:01.000Z',window_enter_tick_ns='2000000000',queue_deadline_tick_ns='3000000000',health_latched=False,block_reason=None),
        'EventAgeProof':dict(event_id='event-a',provider_boot_id='provider-boot',source_sequence='1',basis='trusted_utc',capture_sample_id='sample-a',
            lower_age_ms=0,upper_age_ms=22,challenge_id=None,scope_digest=DIGEST),
        'WsTicketBinding':dict(binding_id='ticket-binding-a',session_id='session-a',audience='controller-a',origin='https://gui.example.invalid',
            client_instance_id='client-a',issuer_epoch='issuer-epoch',scope_digest=DIGEST,expires_at='2026-10-17T00:00:10.000Z',consumed=False),
        'AdmissionDecision':dict(request_ref='request-a',decision='accepted',reason_code='ACCEPTED',profile_id='sim-f04-f05-v1',profile_revision='1',
            limited_dimension=None,retry_after_ms=None,reservation_id='reserve-a',command_id='command-a'),
        'CapacityProfile':profile}
    examples=[dict(case_id='MODEL-'+name,model=name,schema_valid=True,semantic_error=None,instance=value) for name,value in models.items()]
    examples.append(dict(case_id='MODEL-service-binding',model='AuthorizationBinding',schema_valid=True,semantic_error=None,instance=service))
    def bad(name, model, change, schema_valid=False, semantic_error=None):
        value=deepcopy(models[model]);change(value)
        examples.append(dict(case_id=name,model=model,schema_valid=schema_valid,semantic_error=semantic_error,instance=value))
    bad('BAD-human-session','AuthorizationSnapshot',lambda v:v.update(session_id=None))
    bad('BAD-human-automation','AuthorizationBinding',lambda v:v.update(origin='automation'))
    bad('BAD-extension-pair','AuthorizationBinding',lambda v:v.update(extension_instance_id='ext-a'))
    bad('BAD-time-generation','ExecutionGuard',lambda v:v.update(time_required=True))
    bad('BAD-fake-durable','RevocationReceipt',lambda v:v.update(durable=False))
    bad('BAD-clock-null','ClockAssessment',lambda v:v.update(uncertainty_now_ms=None))
    bad('BAD-release-unmeasured','CapacityProfile',lambda v:v.update(purpose='release_candidate'))
    bad('BAD-admission-no-reservation','AdmissionDecision',lambda v:v.update(reservation_id=None))
    bad('BAD-ws-secret-field','WsTicketBinding',lambda v:v.update(access_token='synthetic-forbidden-field'))
    bad('BAD-causal-proof','EventAgeProof',lambda v:v.update(basis='causal_capture'))
    bad('BAD-time-backwards','ScheduleGuard',lambda v:v.update(not_after='2026-10-16T23:59:00.000Z'),True,'window_order')
    bad('BAD-window-enter-after-deadline','ScheduleGuard',lambda v:v.update(window_enter_tick_ns='3000000000'),True,'monotonic_window_order')
    bad('BAD-snapshot-time','AuthorizationSnapshot',lambda v:v['validity'].update(expires_at=v['validity']['not_before']),True,'validity_order')
    bad('BAD-clock-order','ClockAssessment',lambda v:v.update(utc_lower_ms=200000),True,'interval_order')
    bad('BAD-age-order','EventAgeProof',lambda v:v.update(lower_age_ms=23),True,'age_order')
    bad('BAD-incomplete-targets','RevocationRecord',lambda v:v['target_service_ids'].append('controller-b'),True,'target_coverage')
    bad('BAD-duplicate-receipt','RevocationRecord',lambda v:v['receipts'].append(deepcopy(v['receipts'][0])),True,'duplicate_receipt')
    bad('BAD-old-receipt','RevocationRecord',lambda v:v['receipts'][0].update(observed_revision='9'),True,'stale_receipt')
    bad('BAD-other-selector','RevocationRecord',lambda v:v['receipts'][0]['selector'].update(target_id='session-b'),True,'selector_binding')
    bad('BAD-other-operation','RevocationRecord',lambda v:v['receipts'][0].update(operation_id='revoke-other'),True,'operation_binding')
    bad('BAD-pending-target','RevocationRecord',lambda v:v['receipts'][0].update(state='pending'),True,'not_applied')
    bad('BAD-guard-content','ExecutionGuard',lambda v:v.update(permit_id='permit-b'),True,'guard_digest')
    bad('BAD-refresh-budget','CapacityProfile',lambda v:v['identity'].update(snapshot_refresh_ms=2000),True,'refresh_budget')

    scopes=[]
    def scope(name, subject, sel, denied): scopes.append(dict(case_id=name,binding=deepcopy(subject),selector=deepcopy(sel),denied=denied))
    scope('SCOPE-session-human',binding,selector,True)
    scope('SCOPE-session-not-organization',service,selector,False)
    scope('SCOPE-other-session',dict(binding,session_id='session-b'),selector,False)
    scope('SCOPE-new-session-revision',dict(binding,session_revision='3'),selector,False)
    scope('SCOPE-other-epoch',dict(binding,issuer_epoch='epoch-other'),selector,False)
    scope('SCOPE-disabled-human-not-service',service,dict(selector,kind='principal',target_id='human-a',revision_floor='4'),False)
    scope('SCOPE-disabled-human',binding,dict(selector,kind='principal',target_id='human-a',revision_floor='4'),True)
    scope('SCOPE-service-grant',service,dict(selector,kind='grant',target_id='grant-a',revision_floor='4'),True)
    scope('SCOPE-rotated-credential-old-grant',dict(service,credential_id='svc-new'),dict(selector,kind='grant',target_id='grant-a',revision_floor='4'),True)
    scope('SCOPE-credential',binding,dict(selector,kind='credential',target_id='credential-a'),True)
    scope('SCOPE-trust',service,dict(selector,kind='trust',target_id='issuer-demo'),True)
    scope('SCOPE-extension',dict(binding,extension_instance_id='ext-a',extension_approval_revision='2'),dict(selector,kind='extension',target_id='ext-a'),True)

    freshness=[dict(case_id=name,started_ms=start,received_ms=received,now_ms=now,fresh_ms=2000,policy_ms=2000,expected=expected)
        for name,start,received,now,expected in [
            ('FRESH-normal',1000,1100,1500,True),('FRESH-deadline-equal',1000,1100,3000,False),
            ('FRESH-delayed-response',1000,3100,3100,False),('FRESH-time-reversed',1000,900,1200,False)]]

    times=[]
    def timecase(name, change, now, before, after, expected, latch=False, domain='clock-a', generation='generation-a', source_required=False):
        s=deepcopy(sample);change(s)
        times.append(dict(case_id=name,sample=s,now_tick_ns=str(now),domain=domain,generation=generation,
            max_uncertainty_ms=50,source_required=source_required,not_before_ms=before,not_after_ms=after,latched=latch,expected=expected))
    nothing=lambda s:None
    timecase('TIME-in-window',nothing,2000000000,100980,101020,'send')
    timecase('TIME-start-overlap',nothing,2000000000,101000,101100,'wait')
    timecase('TIME-end-equal',nothing,2000000000,100980,101011,'expired')
    timecase('TIME-freshness-equal',nothing,11000000000,100000,200000,'untrusted')
    timecase('TIME-missing-bound',lambda s:s.update(uncertainty_ms=None),2000000000,100000,200000,'untrusted')
    timecase('TIME-degraded',lambda s:s.update(quality='degraded'),2000000000,100000,200000,'untrusted')
    timecase('TIME-generation',nothing,2000000000,100000,200000,'untrusted',generation='generation-new')
    timecase('TIME-other-domain',nothing,2000000000,100000,200000,'untrusted',domain='clock-other')
    timecase('TIME-tick-backwards',nothing,999999999,100000,200000,'untrusted')
    timecase('TIME-uncertainty-equal',lambda s:s.update(uncertainty_ms=49),2000000000,100000,200000,'send')
    timecase('TIME-uncertainty-over',lambda s:s.update(uncertainty_ms=50),2000000000,100000,200000,'untrusted')
    timecase('TIME-recovered-latched',nothing,2000000000,100000,200000,'blocked',latch=True)
    timecase('TIME-unverified-source',lambda s:s.update(source_auth='unverified'),2000000000,100000,200000,'untrusted',source_required=True)
    timecase('TIME-fraction-outward',lambda s:s.update(uncertainty_ms=0,drift_bound_ppm=0),1000500000,100000,100001,'expired')

    ages=[dict(case_id=name,source=source,receiver=receiver,max_age_ms=limit,expected=expected)
        for name,source,receiver,limit,expected in [
            ('AGE-normal',[100,110],[115,125],30,'fresh'),('AGE-received-is-not-new',[100,110],[1000,1010],30,'stale'),
            ('AGE-future',[130,140],[110,120],30,'invalid'),('AGE-overlap',[100,120],[110,130],30,'fresh')]]
    capacities=[]
    def capacity(name, change, expected):
        c=dict(kind='command',already_accepted=False,storage_healthy=True,ordinary_used=31,ordinary_limit=32,
               protection_used=0,protection_limit=16,evidence_free=1,profile_shrink=False)
        change(c);capacities.append(dict(case_id=name,input=c,expected=expected))
    capacity('CAP-normal',lambda c:None,'admit')
    capacity('CAP-full',lambda c:c.update(ordinary_used=32),'reject')
    capacity('CAP-requery-full',lambda c:c.update(ordinary_used=32,already_accepted=True),'query_existing')
    capacity('CAP-protect-reserved',lambda c:c.update(ordinary_used=32,kind='protection'),'apply_protection')
    capacity('CAP-protect-no-db',lambda c:c.update(kind='protection',storage_healthy=False),'apply_protection')
    capacity('CAP-no-result-room',lambda c:c.update(evidence_free=0),'protect')
    capacity('CAP-critical-store',lambda c:c.update(storage_healthy=False),'protect')
    capacity('CAP-protection-full',lambda c:c.update(kind='protection',protection_used=16),'local_protect_no_ack')
    capacity('CAP-lower-limit',lambda c:c.update(ordinary_limit=16,profile_shrink=True),'reject')
    return dict(examples=examples,scope_cases=scopes,freshness_cases=freshness,time_cases=times,event_age_cases=ages,capacity_cases=capacities)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    text=json.dumps(build(),ensure_ascii=False,indent=2)+'\n';path=ROOT/'cases.json'
    if args.check:
        if path.read_text(encoding='utf-8')!=text:raise SystemExit('F04/F05 人工案例生成漂移')
    else:path.write_text(text,encoding='utf-8',newline='\n')
    print('F04/F05 人工案例一致')


if __name__=='__main__':main()
