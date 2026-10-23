"""生成准备历史与关闭资格的交付片段；不更改已批准公共API。"""
import argparse,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
VERSION='preparation-delivery/0.1.0-draft.1'
def obj(**fields):return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def nullable(value):return {'anyOf':[value,{'type':'null'}]}
def schema():
    ident=dict(type='string',minLength=1,maxLength=128,pattern=r'^[A-Za-z0-9_.:-]+$(?![\s\S])')
    digest=dict(type='string',pattern=r'^sha256:[0-9a-f]{64}$(?![\s\S])')
    counter=dict(type='string',pattern=r'^[1-9][0-9]{0,19}$(?![\s\S])')
    scope=obj(authority_service_id=ident,database_instance_id=ident)
    binding=obj(controller_scope=scope,origin_scope=scope,preparation_id=ident,run_id=ident,generation=counter,
      mode={'enum':['arm','recovery']},execution_id=nullable(ident),request_digest=digest)
    binding['allOf']=[{'if':{'properties':{'mode':{'const':'arm'}}},'then':{'properties':{'execution_id':{'type':'null'}}},'else':{'properties':{'execution_id':ident}}}]
    byte_ref=obj(id=ident,bytes_digest=digest)
    close_ref=obj(id=ident,operation_id=ident,operation_digest=digest,bytes_digest=digest)
    completion=obj(id=ident,fence_id=ident,cut_ref=byte_ref,receipt_ref=byte_ref,prepare_closure_ref=obj(id=ident,digest=digest))
    cause=obj(kind={'enum':['initial','prepare_closure','run_barrier_ack','retirement']},object_id=ident)
    observation=obj(contract_version={'const':VERSION},binding={'$ref':'#/$defs/Binding'},
      preparation_revision=counter,previous_revision=nullable(counter),state={'enum':['accepted','applied','rejected','indeterminate','closing','closed']},
      applied_receipt_ref=nullable(byte_ref),close_ref=nullable(close_ref),completion=nullable(completion),
      protection_revision={'enum':['0','1','2']},protection_state={'enum':['not_applicable','pending','applied','indeterminate']},
      cause=nullable(cause),observation_digest=digest)
    branches=[]
    for state in ('accepted','applied','rejected','indeterminate','closing','closed'):
        fields={}
        if state not in ('closing','closed'):
            fields.update(close_ref={'type':'null'},completion={'type':'null'},cause={'type':'null'},protection_revision={'const':'0'},protection_state={'const':'not_applicable'})
        elif state=='closing':
            fields.update(close_ref=close_ref,completion={'type':'null'},cause={'type':'null'},protection_revision={'const':'0'},protection_state={'const':'pending'})
        else:fields.update(close_ref=close_ref,completion=completion,cause=cause,protection_revision={'enum':['1','2']})
        if state=='applied':fields['applied_receipt_ref']=byte_ref
        if state in ('accepted','rejected','indeterminate'):fields['applied_receipt_ref']={'type':'null'}
        branches.append({'if':{'properties':{'state':{'const':state}}},'then':{'properties':fields}})
    for rev,status,kinds in [('1','applied',['initial']),('2','indeterminate',['prepare_closure','run_barrier_ack','retirement'])]:
        branches.append({'if':{'properties':{'protection_revision':{'const':rev}}},'then':{'properties':{'state':{'const':'closed'},'protection_state':{'const':status},'cause':{'properties':{'kind':{'enum':kinds}}}}}})
    observation['allOf']=branches
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
      '$id':'https://leafseamer.invalid/design/c08-controller/preparation-delivery.schema.json',
      'title':VERSION,'x-approved':False,'not':{},'$defs':{'Binding':binding,'Observation':observation}}
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    target=HERE/'preparation-delivery.schema.json'
    if a.check:assert target.read_bytes()==encoded(),'生成漂移'
    else:target.write_bytes(encoded())
