"""已有授权使用原件的撤销切点候选；不定义新的授权签发方式。"""
import argparse,copy,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE/'final-authorization.schema.json'
SID='https://leafseamer.invalid/contracts/c04-lifecycle/revocation-source.schema.json'
def obj(**fields):return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def ref(n):return {'$ref':'#/$defs/'+n}
def null(v):return {'anyOf':[v,{'type':'null'}]}
def build():
    source=json.loads(BASE.read_bytes())['$defs'];d={}
    def include(n):
        if n in d:return
        d[n]=copy.deepcopy(source[n])
        def visit(v):
            if isinstance(v,dict):
                if '$ref' in v:include(v['$ref'].split('/')[-1])
                for item in v.values():visit(item)
            elif isinstance(v,list):
                for item in v:visit(item)
        visit(d[n])
    for n in ('Ref','Binding','AuthorizationBinding'):include(n)
    d['Dependency']=obj(kind={'enum':['principal','session','credential','grant','extension','trust']},target_id=null(ref('Id')),revision=null(ref('Counter')))
    d['Member']=obj(sequence=ref('Counter'),event_ref=ref('Ref'),denial={'enum':[None,'below_floor','credential_revoked','issuer_epoch_revoked']})
    d['Snapshot']=obj(format_version={'const':'authorization-revocation-source/0.1.0-draft.1'},snapshot_id=ref('Id'),revision={'const':'1'},
        source_use_ref=ref('Ref'),binding=ref('Binding'),authorization_binding=ref('AuthorizationBinding'),
        dependencies=dict(type='array',minItems=3,maxItems=6,items=ref('Dependency')),
        observed_through=ref('Counter'),members=dict(type='array',maxItems=24576,items=ref('Member')),
        observed_floor_result={'enum':['denied','no_matching_denial']},snapshot_digest=ref('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}
def encoded():return (json.dumps(build(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'revocation-source.schema.json'
    if a.check:assert path.read_bytes()==encoded();print('schema_current=true')
    else:path.write_bytes(encoded())
