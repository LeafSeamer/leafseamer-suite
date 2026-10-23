"""生成普通布防与保护预算具名候选；不是公共API版本升级。"""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
VERSION='arm-protection-budget/0.1.0-draft.1'
DIMENSIONS=('logical_rows','logical_bytes','queue_slots','work_units')
SHAPE=('dependencies','runs','executions','preparations','submissions','controller_targets')
def obj(**fields):return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def schema():
    u=dict(type='string',pattern=r'^(0|[1-9][0-9]{0,19})(?![\s\S])');positive=dict(type='string',pattern=r'^[1-9][0-9]{0,19}(?![\s\S])')
    ident=dict(type='string',minLength=1,maxLength=128,pattern=r'^[A-Za-z0-9_.:-]+(?![\s\S])')
    sha=dict(type='string',pattern=r'^sha256:[0-9a-f]{64}(?![\s\S])')
    ref=obj(authority_service_id=ident,database_instance_id=ident)
    d={'Vector':obj(**{n:u for n in DIMENSIONS}),'Shape':obj(**{n:u for n in SHAPE}),
       'Scope':ref,'Ref':obj(scope=ref,id=ident,revision=positive,digest=sha)}
    d['Profile']=obj(contract_version={'const':VERSION},profile_id=ident,revision=positive,purpose={'enum':['simulation','release_candidate']},
        capacity={'$ref':'#/$defs/Vector'},max_shape={'$ref':'#/$defs/Shape'},max_row_bytes=positive,episodes=positive,
        max_queue_wait_ns=positive,validation_ref={'oneOf':[{'$ref':'#/$defs/Ref'},{'type':'null'}]})
    d['Binding']=obj(scope=ref,run_id=ident,generation=positive,operation_id=ident,artifact_digest=sha,
        inventory_digest=sha,profile_id=ident,profile_revision=positive,profile_digest=sha,forecast={'$ref':'#/$defs/Shape'})
    d['Reservation']=obj(reservation_id=ident,binding={'$ref':'#/$defs/Binding'},binding_digest=sha,
        per_episode={'$ref':'#/$defs/Vector'},held={'$ref':'#/$defs/Vector'},spent={'$ref':'#/$defs/Vector'},
        episodes_left=u,state={'enum':['held','exhausted','released']})
    d['ProtectionUse']=obj(reservation_id=ident,event_id=ident,event_digest=sha,kind={'enum':['source','preparation','control','authorization','time','storage']},
        binding_digest=sha,observed_shape={'$ref':'#/$defs/Shape'},observed_max_row_bytes=u)
    d['ReleaseProof']=obj(reservation_id=ident,binding_digest=sha,proof_ref={'$ref':'#/$defs/Ref'},
        generation_closed={'const':True},all_targets_accounted={'const':True},no_unresolved_references={'const':True},archive_durable={'const':True})
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/arm-budget.schema.json',
        'title':VERSION,'x-approved':False,'not':{},'$defs':d}
def raw():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=ROOT/'arm-budget.schema.json'
    if a.check:assert target.read_bytes()==raw(),'生成漂移'
    else:target.write_bytes(raw())
