"""生成恢复后继续运行的具名候选；不升级公共协议或改变旧准备。"""
import argparse,json
from pathlib import Path
import build_arm_budget as A

HERE=Path(__file__).resolve().parent
VERSION='run-continuation/0.1.0-draft.1'

def schema():
    old=A.schema()['$defs'];ident=old['Profile']['properties']['profile_id']
    positive=old['Ref']['properties']['revision'];sha=old['Ref']['properties']['digest']
    ref={'$ref':'#/$defs/Ref'};scope={'$ref':'#/$defs/Scope'}
    arr=lambda item,n:dict(type='array',items=item,minItems=1,maxItems=n,uniqueItems=True)
    d={'Scope':old['Scope'],'Ref':old['Ref']}
    d['Device']=A.obj(device_id=ident,control_ref=ref,authorization_ref=ref,action_set_ref=ref)
    d['Target']=A.obj(controller_scope=scope,preparation_ref=ref,recovery_grant_ref=ref,
        devices=arr({'$ref':'#/$defs/Device'},256))
    common=dict(contract_version={'const':VERSION},origin_scope=scope,run_id=ident,generation=positive,
        transfer_id=ident,recovery_operation_id=ident,recovery_execution_id=ident,continuation_plan_ref=ref)
    d['Request']=A.obj(**common,request_epoch=ident,actor=A.obj(issuer_id=ident,principal_id=ident),
        idempotency_key=ident,approval_ref=ref,targets=arr({'$ref':'#/$defs/Target'},32),request_digest=sha)
    d['Receipt']=A.obj(**common,request_digest=sha,controller_scope=scope,receipt_id=ident,revision={'const':'1'},
        target_digest=sha,preparation_ref=ref,recovery_grant_ref=ref,continuation_grant_ref=ref,
        qualification_ref=ref,receipt_digest=sha)
    d['Adoption']=A.obj(**common,request_digest=sha,adoption_id=ident,revision={'const':'1'},
        expected_run_revision=positive,expected_slot_revision=positive,expected_operation_revision=positive,
        receipt_refs=arr(ref,32),release_proof_ref=ref,adoption_digest=sha)
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
        '$id':'https://leafseamer.invalid/design/c04-lifecycle/continuation.schema.json',
        'title':VERSION,'x-approved':False,'not':{},'$defs':d}

def raw():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    path=HERE/'continuation.schema.json'
    if a.check:assert path.read_bytes()==raw(),'生成漂移'
    else:path.write_bytes(raw())
