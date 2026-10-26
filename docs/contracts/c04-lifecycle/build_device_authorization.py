"""设备授权语义状态与短期取证分离的候选格式，不修改批准协议。"""
import argparse,copy,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE/'open-authorization.schema.json'
SID='https://leafseamer.invalid/contracts/c04-lifecycle/device-authorization.schema.json'
def obj(**fields):return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def ref(n):return {'$ref':'#/$defs/'+n}
def nullable(v):return {'anyOf':[v,{'type':'null'}]}
def build():
    d=copy.deepcopy(json.loads(BASE.read_bytes())['$defs'])
    d['CredentialLineage']=obj(principal=ref('Principal'),principal_kind={'enum':['human','service']},credential_id=ref('Id'),
        session_id=nullable(ref('Id')),subject_revision=ref('Counter'),session_revision=nullable(ref('Counter')),policy_revision=ref('Counter'),scope_digest=ref('Digest'))
    d['CredentialLineage']['allOf']=[{'if':{'properties':{'principal_kind':{'const':'human'}}},'then':{'properties':{'session_id':ref('Id'),'session_revision':ref('Counter')}},'else':{'properties':{'session_id':{'type':'null'},'session_revision':{'type':'null'}}}}]
    d['Context']=obj(scope=ref('Scope'),device_id=ref('Id'),control_authority_ref=ref('Ref'),control_epoch=ref('Id'),control_version=ref('Counter'),
        mode={'enum':['manual','automatic']},holder=nullable(ref('Principal')),purpose={'enum':['ordinary','cancel_only']},
        evaluator_lineage=nullable(ref('CredentialLineage')),evaluator_policy_ref=nullable(ref('Ref')),device_scope_ref=nullable(ref('Ref')),
        holder_lineage=nullable(ref('CredentialLineage')),cancel_scope_ref=nullable(ref('Ref')),cancel_lineage_ref=nullable(ref('Ref')))
    d['Context']['allOf']=[
        {'if':{'properties':{'mode':{'const':'manual'}}},'then':{'properties':{'holder':ref('Principal')}},'else':{'properties':{'holder':{'type':'null'}}}},
        {'if':{'properties':{'purpose':{'const':'cancel_only'}}},'then':{'properties':{'holder_lineage':{'type':'null'}}},'else':{'properties':{'cancel_scope_ref':{'type':'null'},'cancel_lineage_ref':{'type':'null'}}}}]
    d['State']=obj(format_version={'const':'device-authorization-state/0.1.0-draft.1'},state_id=ref('Id'),revision=ref('Counter'),context=ref('Context'),
        status={'enum':['protected','policy_selected']},reasons=dict(type='array',maxItems=12,uniqueItems=True,items={'enum':['initial','revoked','scope_changed','policy_denied','control_changed','runtime_changed','evidence_expired','authentication_clock_untrusted','storage_fault','source_unavailable','credential_changed','cancel_scope_changed']}),
        parent_ref=nullable(ref('Ref')),recovery_ref=nullable(ref('Ref')),state_digest=ref('Digest'))
    d['State']['allOf']=[{'if':{'properties':{'status':{'const':'policy_selected'}}},'then':{'properties':{'reasons':{'maxItems':0},'recovery_ref':ref('Ref'),'context':{'properties':{'evaluator_lineage':ref('CredentialLineage'),'evaluator_policy_ref':ref('Ref'),'device_scope_ref':ref('Ref')}}}},'else':{'properties':{'reasons':{'minItems':1}}}}]
    d['Window']=obj(role={'enum':['evaluator','holder','cancel']},evidence_ref=ref('Ref'),not_before_tick_ns=ref('Counter'),before_tick_ns=ref('Counter'))
    d['RecoveryAuthorization']=obj(format_version={'const':'device-recovery-authorization/0.1.0-draft.1'},authorization_id=ref('Id'),revision={'const':'1'},
        operation_id=ref('Id'),request_receipt_ref=ref('Ref'),binding=ref('Binding'),protected_state_ref=ref('Ref'),control_authority_ref=ref('Ref'),
        requester=ref('Principal'),requester_kind={'enum':['human','service']},purpose={'const':'revalidate_device_authorization'},proposed_context_digest=ref('Digest'),
        evidence_refs=dict(type='array',minItems=1,maxItems=16,uniqueItems=True,items=ref('Ref')),issued_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter'),authorization_digest=ref('Digest'))
    d['Evidence']=obj(format_version={'const':'device-authorization-evidence/0.1.0-draft.1'},evidence_id=ref('Id'),revision={'const':'1'},state_ref=ref('Ref'),
        requirement=ref('Requirement'),context_digest=ref('Digest'),windows=dict(type='array',minItems=1,maxItems=3,items=ref('Window')),evidence_digest=ref('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}
def encoded():return (json.dumps(build(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'device-authorization.schema.json'
    if a.check:assert path.read_bytes()==encoded();print('schema_current=true')
    else:path.write_bytes(encoded())
