"""TIME持久投影候选；固定引用IPC0.8，不修改设备线协议。"""
import argparse
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
IPC=HERE.parent/'df03-service/ipc.schema.json'
SID='https://leafseamer.org/contracts/time-fence-registry/0.1.0-draft.1/schema.json'


def obj(**properties):return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)
def ref(name):return {'$ref':'#/$defs/'+name}
def nullable(value):return {'anyOf':[value,{'type':'null'}]}
def array(value,limit):return dict(type='array',items=value,maxItems=limit)
def enum(*values):return {'enum':list(values)}


def build():
    ipc=json.loads(IPC.read_bytes());uri=ipc['$id']
    d={name:{'$ref':uri+'#/$defs/S11__'+name} for name in ('Ref','Domain','Binding','Invalidation')}
    d.update(Id=dict(type='string',minLength=1,maxLength=128,pattern=r'^[A-Za-z0-9_.:-]+$(?![\s\S])'),
             Counter=dict(type='string',pattern=r'^(0|[1-9][0-9]{0,19})$(?![\s\S])'),
             Positive=dict(type='string',pattern=r'^[1-9][0-9]{0,19}$(?![\s\S])'),
             Digest=dict(type='string',pattern=r'^sha256:[0-9a-f]{64}$(?![\s\S])'))
    d['Exit']=obj(exit_id=ref('Id'),clock_domain_id=ref('Id'),descriptor_digest=ref('Digest'),retired={'type':'boolean'})
    d['Issue']=obj(permit_id=ref('Id'),kind=enum('ordinary','cancel'),issued_revision=ref('Positive'),exit_id=ref('Id'),
        packet_ref=ref('Ref'),transmission_ref=ref('Ref'),initial_permit_id=ref('Id'),business_anchor_id=nullable(ref('Id')),
        time_required={'type':'boolean'},time_binding=nullable(ref('Binding')),
        disposition=enum('not_sent','in_flight','unknown'),resolution=enum('unresolved','never_sent','effect_resolved'))
    d['Issue']['allOf']=[
        {'if':{'properties':{'time_required':{'const':True}}},'then':{'properties':{'time_binding':ref('Binding')}},
         'else':{'properties':{'time_binding':{'type':'null'}}}},
        {'if':{'properties':{'kind':{'const':'ordinary'}}},'then':{'properties':{'business_anchor_id':ref('Id')}},
         'else':{'properties':{'business_anchor_id':{'type':'null'}}}}]
    d['Registry']=obj(registry_id=ref('Id'),revision=ref('Positive'),authority_service_id=ref('Id'),
        database_instance_id=ref('Id'),issued_head=ref('Counter'),exits=array(ref('Exit'),1024),
        issues=array(ref('Issue'),65536),registry_digest=ref('Digest'))
    d['Target']=obj(exit_id=ref('Id'),business_anchor_ids=array(ref('Id'),256),
        ordinary_permit_ids=array(ref('Id'),256),cancel_permit_ids=array(ref('Id'),256))
    d['Cut']=obj(cut_id=ref('Id'),revision={'const':'1'},operation_ref=ref('Ref'),invalidation=ref('Invalidation'),
        registry_ref=ref('Ref'),issued_cut_revision=ref('Counter'),targets=array(ref('Target'),256),cut_digest=ref('Digest'))
    d['Attempt']=obj(barrier_id=ref('Id'),cut_ref=ref('Ref'),exit_id=ref('Id'),ordinal=ref('Positive'),
        previous_barrier_id=nullable(ref('Id')))
    d['Coverage']=obj(permit_id=ref('Id'),disposition=enum('not_sent','in_flight','unknown'),
        proof=enum('never_received','discarded_unconsumed','transport_entered','send_uncertain'))
    d['BusinessCoverage']=obj(permit_id=ref('Id'),disposition=enum('not_sent','in_flight','unknown'))
    d['Ack']=obj(ack_id=ref('Id'),revision={'const':'1'},attempt_ref=ref('Ref'),invalidation_ref=ref('Ref'),
        minimum_time_generation=ref('Positive'),effective_tick_ns=ref('Counter'),
        ordinary_coverage=array(ref('Coverage'),256),cancel_coverage=array(ref('Coverage'),
        256),business_coverage=array(ref('BusinessCoverage'),256),ack_digest=ref('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,
            'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}


def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    path=HERE/'registry.schema.json';raw=encoded(build())
    if args.check:assert path.read_bytes()==raw,'生成漂移'
    else:path.write_bytes(raw)
