"""最终来源正文的内部存储候选；不改变公开HTTP/IPC版本。"""
import argparse,copy,json
from pathlib import Path
import build_final_admission as A
HERE=Path(__file__).resolve().parent
OWNER=HERE.parent/'c08-controller/hold-ownership.schema.json'
SOURCES=[Path(__file__),HERE/'final-admission.schema.json',OWNER]
SID='https://leafseamer.invalid/design/c04-lifecycle/final-source-bodies.schema.json'
obj=A.obj;ref=A.ref;optional=A.optional

def local(v):
    if isinstance(v,list):return [local(x) for x in v]
    if not isinstance(v,dict):return v
    return {k:'#/$defs/'+x.split('/')[-1] if k=='$ref' else local(x) for k,x in v.items()}

def build():
    base=json.loads((HERE/'final-admission.schema.json').read_bytes())['$defs']
    d={n:copy.deepcopy(base[n]) for n in ('Id','Counter','Digest','Ref','Scope','Binding','Principal','ExecutionIdentity')}
    d['Ownership']=local(json.loads(OWNER.read_bytes())['$defs']['Ownership'])
    content={k:copy.deepcopy(v) for k,v in d['Ownership']['properties'].items() if k in ('scope','device_id','hold_ref','identity','control_authority_ref','control_epoch','effective_version','clock_domain_id','descriptor_digest','acquired_tick_ns')}
    d['OwnershipContent']=obj(**content)
    d['OwnershipReceipt']=obj(format_version={'const':'ownership-source/1'},source_id=ref('Id'),revision={'const':'1'},
        provider_id=ref('Id'),sampled_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter'),content=ref('OwnershipContent'),receipt_digest=ref('Digest'))
    d['ControlStorageRecord']=obj(format_version={'const':'control-storage-body/1'},change_id=ref('Id'),revision=ref('Counter'),scope=ref('Scope'),device_id=ref('Id'),
        change_kind=ref('Id'),control_epoch=ref('Id'),effective_version=ref('Counter'),reserved_version=ref('Counter'),mode={'enum':['automatic','manual']},
        holder=optional(ref('Principal')),pending_operation_id=optional(ref('Id')),gate_state={'enum':['protected','fencing','ready']},
        clock_domain_id=d['Binding']['properties']['clock_domain_id'],descriptor_digest=ref('Digest'),observed_tick_ns=ref('Counter'),record_digest=ref('Digest'))
    d['ControlStorageRecord']['allOf']=[{'if':{'properties':{'mode':{'const':'automatic'}}},'then':{'properties':{'holder':{'type':'null'}}},
        'else':{'properties':{'holder':{'allOf':[ref('Principal'),{'properties':{'kind':{'const':'human'}}}]}}}}]
    d['SafetyHead']=obj(source_kind=ref('Id'),source_id=ref('Id'),recovery_id=optional(ref('Id')))
    d['ResourceSafetyCut']=obj(format_version={'const':'resource-safety-cut/1'},scope=ref('Scope'),device_id=ref('Id'),revision=ref('Counter'),head=optional(ref('SafetyHead')),cut_digest=ref('Digest'))
    d['HoldObservation']=obj(hold_ref=ref('Ref'),owner_ref=ref('Ref'),control_authority_ref=ref('Ref'),state={'enum':['active','unknown','failed_unresolved','orphaned','proof_revoked']})
    d['ResourceSnapshotRecord']=obj(format_version={'const':'resource-snapshot-body/1'},snapshot_id=ref('Id'),revision={'const':'1'},binding=ref('Binding'),
        control_authority_ref=ref('Ref'),control_state_ref=ref('Ref'),resource_safety_ref=ref('Ref'),authorization_id=ref('Id'),resource_id=ref('Id'),
        run_snapshot_id=ref('Id'),command_snapshot_id=ref('Id'),time_snapshot_id=ref('Id'),sampled_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter'),
        provider_id=ref('Id'),holds=dict(type='array',maxItems=65536,items=ref('HoldObservation')),evidence_digest=ref('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}

def raw(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args();target=HERE/'final-source-bodies.schema.json'
    if args.check:assert target.read_bytes()==raw(build())
    else:target.write_bytes(raw(build()))
