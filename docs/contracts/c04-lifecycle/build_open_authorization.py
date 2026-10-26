"""开闸授权取证需求的局部定义；需求清单不签发授权或发送许可。"""
import argparse,copy,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'c08-controller/open-contract.schema.json'
SID='https://leafseamer.invalid/contracts/c04-lifecycle/open-authorization.schema.json'
def obj(**fields):return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def ref(name):return {'$ref':'#/$defs/'+name}
def nullable(value):return {'anyOf':[value,{'type':'null'}]}
def build():
    source=json.loads(BASE.read_bytes())['$defs']
    d={n:copy.deepcopy(source[n]) for n in ('Id','Counter','Digest','Scope','Ref','Binding')}
    d['Principal']=obj(issuer_id=ref('Id'),issuer_epoch=ref('Id'),principal_id=ref('Id'))
    d['HumanEvidence']=obj(principal=ref('Principal'),session_id=ref('Id'),credential_id=ref('Id'),
        challenge_ref=ref('Ref'),response_ref=ref('Ref'),scope_proof_ref=ref('Ref'),validity_ref=ref('Ref'))
    d['EvaluatorEvidence']=obj(runtime_ref=ref('Ref'),policy_ref=ref('Ref'),authority_response_ref=ref('Ref'),
        scope_proof_ref=ref('Ref'),validity_ref=ref('Ref'))
    d['CancelEvidence']=obj(protection_scope_ref=ref('Ref'),assessment_ref=ref('Ref'),
        cancel_authorization_ref=ref('Ref'),ownership_ref=ref('Ref'))
    d['Requirement']=obj(format_version={'const':'open-authorization-requirement/0.1.0-draft.1'},
        requirement_id=ref('Id'),revision={'const':'1'},binding=ref('Binding'),
        purpose={'enum':['ordinary','cancel_only']},control_mode={'enum':['manual','automatic']},
        control_state_ref=ref('Ref'),control_authority_ref=ref('Ref'),holder=nullable(ref('Principal')),
        evaluator=ref('EvaluatorEvidence'),holder_evidence=nullable(ref('HumanEvidence')),cancel_evidence=nullable(ref('CancelEvidence')),
        authorization_state_ref=ref('Ref'),revocation_cut_ref=ref('Ref'),
        selected_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter'),requirement_digest=ref('Digest'))
    d['Requirement']['allOf']=[
        {'if':{'properties':{'control_mode':{'const':'manual'}}},'then':{'properties':{'holder':ref('Principal')}},'else':{'properties':{'holder':{'type':'null'}}}},
        {'if':{'properties':{'purpose':{'const':'cancel_only'}}},'then':{'properties':{'cancel_evidence':ref('CancelEvidence'),'holder_evidence':{'type':'null'}}},
         'else':{'properties':{'cancel_evidence':{'type':'null'}},'allOf':[
             {'if':{'properties':{'control_mode':{'const':'manual'}}},'then':{'properties':{'holder_evidence':ref('HumanEvidence')}},'else':{'properties':{'holder_evidence':{'type':'null'}}}}]}}]
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}
def encoded():return (json.dumps(build(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'open-authorization.schema.json'
    if a.check:assert target.read_bytes()==encoded();print('schema_current=true')
    else:target.write_bytes(encoded())
