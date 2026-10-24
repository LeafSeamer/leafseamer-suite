"""从既有命令类型图抽取原定义，生成内部固定attempt投影候选。"""
import argparse,json
from pathlib import Path
import build_command_contract as C
HERE=Path(__file__).resolve().parent
VERSION='attempt-projection/0.1.0-draft.1'
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def build():
    source=json.loads((HERE/'command-contract.schema.json').read_bytes())
    d=C.B.closure(source['$defs'],['Scope','V__S0_Id','V__S0_Ref','V__S0_AttemptView','V__S0_Digest'])
    d['Selection']=obj(kind={'enum':['pending','unknown','decision']},ref={'anyOf':[C.ref('V__S0_Ref'),{'type':'null'}]})
    d['Selection']['allOf']=[{'if':{'properties':{'kind':{'const':'pending'}}},'then':{'properties':{'ref':{'type':'null'}}},'else':{'properties':{'ref':C.ref('V__S0_Ref')}}}]
    d['OriginalRef']=obj(kind={'enum':['state','evidence','packet','exit','transmission','report','time_projection','prepared_state']},source_ref=C.ref('V__S0_Ref'))
    d['AttemptProjection']=obj(scope=C.ref('Scope'),command_id=C.ref('V__S0_Id'),state_ref=C.ref('V__S0_Ref'),
        attempts=dict(type='array',items=C.ref('V__S0_AttemptView'),maxItems=16),
        source_refs=dict(type='array',items=C.ref('OriginalRef'),maxItems=16384,uniqueItems=True),
        selections=dict(type='object',propertyNames=C.ref('V__S0_Id'),additionalProperties=C.ref('Selection'),maxProperties=16),projection_digest=C.ref('V__S0_Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/attempt-projection.schema.json',
        'title':VERSION,'x-approved':False,'x-source-contract':source['$id'],'$ref':'#/$defs/AttemptProjection','$defs':d}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'attempt-projection.schema.json';body=C.raw(build())
    if a.check:assert target.read_bytes()==body
    else:target.write_bytes(body)
