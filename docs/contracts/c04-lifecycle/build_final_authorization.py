"""当前授权使用与撤销下界的局部候选，不是身份签发服务。"""
import argparse,copy,json
from pathlib import Path
import build_final_admission as A
HERE=Path(__file__).resolve().parent
PUBLIC=HERE.parent/'df01-source/source/public.schema.json'
SOURCES=[Path(__file__),PUBLIC,HERE/'final-admission.schema.json']
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
    d['AuthorizationCut']=obj(format_version={'const':'authorization-cut/1'},scope=ref('Scope'),use_ref=ref('Ref'),transaction_id=ref('Id'),
        selected_tick_ns=ref('Counter'),sealed_tick_ns=ref('Counter'),authority_response_ref=ref('Ref'),
        continuation_ref=A.optional(ref('Ref')),floor_refs=dict(type='array',maxItems=24576,items=ref('Ref')))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/final-authorization.schema.json',
        'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}

def raw(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'final-authorization.schema.json'
    if a.check:assert target.read_bytes()==raw(build())
    else:target.write_bytes(raw(build()))
