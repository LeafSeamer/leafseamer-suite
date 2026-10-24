"""当前授权使用与撤销下界的局部候选，不是身份签发服务。"""
import argparse,copy,json
from pathlib import Path
import build_final_admission as A
HERE=Path(__file__).resolve().parent
PUBLIC=HERE.parent/'df01-source/source/public.schema.json'
IPC=HERE/'continuation-binding-ipc.schema.json'
SOURCES=[Path(__file__),PUBLIC,HERE/'final-admission.schema.json',IPC]
obj=A.obj;ref=A.ref

def build():
    base=json.loads((HERE/'final-admission.schema.json').read_bytes())['$defs']
    public=json.loads(PUBLIC.read_bytes())['$defs'];d={}
    def include(name):
        if name in d:return
        d[name]=copy.deepcopy(public[name])
        def walk(v):
            if isinstance(v,dict):
                if '$ref' in v:include(v['$ref'].split('/')[-1])
                for x in v.values():walk(x)
            elif isinstance(v,list):
                for x in v:walk(x)
        walk(d[name])
    for n in ('AuthorizationSnapshot','AuthorizationBinding','RevocationSelector'):include(n)
    for n in ('Id','Counter','Digest','Ref','Scope','Binding','Principal','ExecutionIdentity'):d[n]=copy.deepcopy(base[n])
    d['Revision']=copy.deepcopy(base['Counter'])
    d['AuthorizationUse']=obj(format_version={'const':'authorization-use/1'},use_id=ref('Id'),revision={'const':'1'},
        binding=ref('Binding'),identity=ref('ExecutionIdentity'),authorization_binding=ref('AuthorizationBinding'),snapshot=ref('AuthorizationSnapshot'),
        challenge_sent_tick_ns=ref('Counter'),received_tick_ns=ref('Counter'),local_freshness_limit_ms=dict(type='integer',minimum=1,maximum=60000),
        not_before_tick_ns=ref('Counter'),authorization_before_tick_ns=ref('Counter'),
        authority_evidence_ref=ref('Ref'),scope_evidence_ref=ref('Ref'),validity_evidence_ref=ref('Ref'),use_digest=ref('Digest'))
    d['FloorEvent']=obj(event_id=ref('Id'),scope=ref('Scope'),selector=ref('RevocationSelector'),operation_ref=ref('Ref'),event_digest=ref('Digest'))
    d['ScopedRef']=obj(scope=ref('Scope'),**copy.deepcopy(d['Ref']['properties']))
    d['AuthorizationChallenge']=obj(format_version={'const':'authorization-challenge/1'},challenge_id=dict(type='string',minLength=64,maxLength=64,pattern='^[0-9a-f]{64}(?![\\s\\S])'),revision={'const':'1'},
        binding=ref('Binding'),requester=ref('Principal'),credential_id=ref('Id'),audience=ref('Id'),scope_digest=ref('Digest'),
        requested_permission={'const':'device.command'},sent_tick_ns=ref('Counter'),challenge_digest=ref('Digest'))
    d['AuthorityResponse']=obj(format_version={'const':'authorization-response/1'},response_id=ref('Id'),revision={'const':'1'},scope=ref('Scope'),
        challenge_ref=ref('Ref'),snapshot=ref('AuthorizationSnapshot'),received_tick_ns=ref('Counter'),channel_evidence_ref=ref('Ref'),response_digest=ref('Digest'))
    d['ContinuationAuthorization']=obj(format_version={'const':'continuation-authorization/1'},scope=ref('Scope'),command_ref=ref('Ref'),
        request_ref=ref('Ref'),device_id=ref('Id'),action_id=ref('Id'),capability_version=ref('Id'),transfer_ref=ref('ScopedRef'),
        grant_ref=ref('ScopedRef'),arm_generation=ref('Counter'),target_digest=ref('Digest'))
    d['CommandTarget']=obj(device_id=ref('Id'),action_id=ref('Id'),capability_version=ref('Id'))
    d['CommandScope']=obj(format_version={'const':'command-scope/1'},scope=ref('Scope'),requester=ref('Principal'),credential_id=ref('Id'),
        permissions=dict(type='array',items=ref('Id'),maxItems=256,uniqueItems=True),
        targets=dict(type='array',items=ref('CommandTarget'),maxItems=4096,uniqueItems=True))
    d['RequestContextBinding']=obj(format_version={'const':'request-context-binding/1'},context_id=ref('Id'),revision={'const':'1'},scope=ref('Scope'),
        namespace_id=ref('Id'),request_epoch=ref('Id'),requester=ref('Principal'),credential_id=ref('Id'),session_id=A.optional(ref('Id')),
        operations=dict(type='array',items=ref('Id'),minItems=1,maxItems=32,uniqueItems=True),
        original_scope_ref=ref('Ref'),issuance_evidence_ref=ref('Ref'),context_digest=ref('Digest'))
    d['RequestContextBinding']['allOf']=[{'if':{'properties':{'requester':{'properties':{'kind':{'const':'human'}}}}},
        'then':{'properties':{'session_id':ref('Id')}},'else':{'properties':{'session_id':{'type':'null'}}}}]
    d['CommandScopeProof']=obj(format_version={'const':'command-scope-proof/1'},scope=ref('Scope'),command_ref=ref('Ref'),request_ref=ref('Ref'),
        context_ref=ref('Ref'),original_scope_ref=ref('Ref'),current_scope_ref=ref('Ref'),authority_response_ref=ref('Ref'),target=ref('CommandTarget'))
    d['AuthenticationClockSample']=obj(format_version={'const':'authentication-clock-sample/1'},sample_id=ref('Id'),revision={'const':'1'},
        profile={'const':'trusted-system-interval/1'},binding=ref('Binding'),anchor_tick_ns=ref('Counter'),
        utc_lower_ns=ref('Counter'),utc_upper_ns=ref('Counter'),drift_ppb=dict(type='integer',minimum=0,maximum=1000000),
        valid_before_tick_ns=ref('Counter'),quality={'enum':['trusted','untrusted']},policy_ref=ref('Ref'),acquisition_ref=ref('Ref'))
    d['AuthenticationClockRecord']=obj(format_version={'const':'authentication-clock-record/1'},record_id=ref('Id'),revision={'const':'1'},
        sequence=ref('Counter'),sample=ref('AuthenticationClockSample'),parent_ref=A.optional(ref('Ref')),
        effective_lower_ns=ref('Counter'),effective_upper_ns=ref('Counter'),protected=dict(type='boolean'),record_digest=ref('Digest'))
    d['AuthenticationClockDomain']=obj(scope=ref('Scope'),controller_boot_id=ref('Id'),clock_domain_id=copy.deepcopy(d['Binding']['properties']['clock_domain_id']))
    d['AuthenticationClockFault']=obj(format_version={'const':'authentication-clock-fault/1'},fault_id=ref('Id'),revision={'const':'1'},domain=ref('AuthenticationClockDomain'),binding=ref('Binding'),
        reason={'enum':['invalid_sample','acquisition_failed','clock_unusable']},input_digest=A.optional(ref('Digest')),input_bytes=A.optional(ref('Counter')),fault_digest=ref('Digest'))
    d['ClockIngestResult']=obj(format_version={'const':'clock-ingest-result/1'},binding=ref('Binding'),outcome={'enum':['stored','protected']},
        record_ref=A.optional(ref('Ref')),fault_ref=A.optional(ref('Ref')))
    d['ClockIngestResult']['allOf']=[{'if':{'properties':{'outcome':{'const':'stored'}}},
        'then':{'properties':{'record_ref':ref('Ref'),'fault_ref':{'type':'null'}}},
        'else':{'properties':{'fault_ref':ref('Ref')}}}]
    d['ClockCloseBody']=obj(close_id=ref('Id'),reason={'const':'authentication_clock_untrusted'},scope={'const':'device'})
    d['ClockCloseTarget']=obj(binding=ref('Binding'),exit_source_ref=ref('Ref'),session_id=A.optional(ref('Id')),
        session_source_ref=A.optional(ref('Ref')),required_action={'enum':['close_gate','verify_termination']},close_body=A.optional(ref('ClockCloseBody')))
    d['ClockCloseTarget']['allOf']=[{'if':{'properties':{'required_action':{'const':'close_gate'}}},
        'then':{'properties':{'session_id':ref('Id'),'session_source_ref':ref('Ref'),'close_body':ref('ClockCloseBody')}},
        'else':{'properties':{'close_body':{'type':'null'}}}}]
    d['ClockClosePlan']=obj(format_version={'const':'authentication-clock-close-plan/1'},plan_id=ref('Id'),revision={'const':'1'},
        fault_ref=ref('Ref'),domain=ref('AuthenticationClockDomain'),state={'const':'planned'},
        targets=dict(type='array',minItems=1,maxItems=4096,items=ref('ClockCloseTarget')),plan_digest=ref('Digest'))
    d['ValidityComponent']=obj(kind={'enum':['credential','session','grant']},target_id=ref('Id'),source_ref=ref('Ref'),
        validity=copy.deepcopy(d['AuthorizationSnapshot']['properties']['validity']))
    d['AuthorizationValidity']=obj(format_version={'const':'authorization-validity/1'},validity_id=ref('Id'),revision={'const':'1'},
        binding=ref('Binding'),identity=ref('ExecutionIdentity'),authorization_binding=ref('AuthorizationBinding'),
        authority_response_ref=ref('Ref'),clock_ref=ref('Ref'),components=dict(type='array',minItems=1,maxItems=3,items=ref('ValidityComponent')),
        validity_digest=ref('Digest'))
    d['AuthorizationTimeCut']=obj(format_version={'const':'authorization-time-cut/1'},validity_ref=ref('Ref'),
        origin_clock_ref=ref('Ref'),current_clock_ref=ref('Ref'),not_before_tick_ns=ref('Counter'),before_tick_ns=ref('Counter'))
    d['AuthorizationCut']=obj(format_version={'const':'authorization-cut/1'},scope=ref('Scope'),use_ref=ref('Ref'),transaction_id=ref('Id'),
        selected_tick_ns=ref('Counter'),sealed_tick_ns=ref('Counter'),authority_response_ref=ref('Ref'),
        validity_cut=ref('AuthorizationTimeCut'),
        continuation_ref=A.optional(ref('Ref')),scope_proof_ref=A.optional(ref('Ref')),floor_refs=dict(type='array',maxItems=24576,items=ref('Ref')))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/final-authorization.schema.json',
        'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}

def raw(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'final-authorization.schema.json'
    if a.check:assert target.read_bytes()==raw(build())
    else:target.write_bytes(raw(build()))
