"""生成P3/P4状态片段Schema；不生成产品服务或更改已确认API。"""
import argparse,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
VERSION='protection-delivery/0.1.0-draft.1'
def obj(**fields):return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def schema():
    ident=dict(type='string',minLength=1,maxLength=128,pattern=r'^[A-Za-z0-9_.:-]+$(?![\s\S])')
    digest=dict(type='string',pattern=r'^sha256:[0-9a-f]{64}$(?![\s\S])')
    scope=obj(authority_service_id=ident,database_instance_id=ident)
    binding=obj(controller_scope=scope,origin_scope=scope,operation_id=ident,run_id=ident,
      deny_through_generation=dict(type='string',pattern=r'^[1-9][0-9]{0,19}$(?![\s\S])'),
      selector_digest=digest,target_set_digest=digest)
    byte_ref=obj(id=ident,bytes_digest=digest)
    observation=obj(contract_version={'const':VERSION},binding={'$ref':'#/$defs/Binding'},fence_id=ident,
      cut_ref=byte_ref,receipt_ref=byte_ref,prepare_closure_ref=obj(id=ident,digest=digest),
      status_revision={'enum':['1','2']},state={'enum':['applied','indeterminate']},
      cause=obj(kind={'enum':['initial','prepare_closure','run_barrier_ack','retirement']},object_id=ident),
      observation_digest=digest)
    branches=[]
    for revision,state,kinds in [('1','applied',['initial']),('2','indeterminate',['prepare_closure','run_barrier_ack','retirement'])]:
        branches.append({'if':{'properties':{'status_revision':{'const':revision}},'required':['status_revision']},
          'then':{'properties':{'state':{'const':state},'cause':{'properties':{'kind':{'enum':kinds}}}}}})
    observation['allOf']=branches
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
      '$id':'https://leafseamer.invalid/design/c08-controller/protection-delivery.schema.json',
      'title':VERSION,'x-approved':False,'not':{},'$defs':{'Binding':binding,'Observation':observation}}
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    target=HERE/'protection-delivery.schema.json'
    if a.check:assert target.read_bytes()==encoded(),'生成漂移'
    else:target.write_bytes(encoded())
