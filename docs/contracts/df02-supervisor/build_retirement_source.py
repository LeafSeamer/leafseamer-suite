"""监督退役原件导出候选；不会修改已确认监督协议。"""
import argparse,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/contracts/df02-supervisor/retirement-source.schema.json'
SUP=json.loads((HERE/'supervisor.schema.json').read_bytes())['$id']
def ref(name):return {'$ref':SUP+'#/$defs/'+name}
def obj(properties):return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)
def array(items,maximum=256):return dict(type='array',items=items,maxItems=maximum)
def schema():
    ident=ref('Id');counter=ref('U20');digest=ref('Digest');domain=ref('ClockDomainRef')
    source=obj(dict(host_installation_id=ident,incarnation_id=ident,service_id=ident,database_instance_id=ident,os_provider_id=ident))
    observation=obj(dict(format_version={'const':'retirement-observation/1'},observation_id=ident,provider_id=ident,subject_domain_ref=domain,evaluator_domain_ref=domain,
        containment_ref=ref('ContainmentRef'),target_member_ids=dict(type='array',items=ident,maxItems=256,uniqueItems=True),observed_tick_ns=counter,
        launch_intake_closed={'const':True},group_owned={'const':True},members_complete={'const':True},live_process_count={'const':0},open_endpoint_count={'const':0}))
    member=obj(dict(intent={'anyOf':[ref('LaunchIntent'),ref('ExtensionLaunchIntent')]},admission_receipt={'anyOf':[ref('AdmissionReceipt'),{'type':'null'}]},state={'enum':['retired','rejected']}))
    bundle=obj(dict(format_version={'const':'retirement-source/0.1.0-draft.1'},source=source,old_descriptor=ref('ClockDomainDescriptor'),evaluator_descriptor=ref('ClockDomainDescriptor'),
        evidence=ref('RetirementEvidence'),members=array(member),observations=array(observation),journal_snapshot_digest=digest,bundle_digest=digest))
    return dict(**{'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'$defs':{'SourceIdentity':source,'Observation':observation,'Bundle':bundle},'$ref':'#/$defs/Bundle'})
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'retirement-source.schema.json'
    if a.check:assert path.read_bytes()==encoded()
    else:path.write_bytes(encoded())
