"""时间提供者准入原件候选；不改既有监督协议。"""
import argparse,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/contracts/df02-supervisor/time-provider-source.schema.json'
SUP=json.loads((HERE/'supervisor.schema.json').read_bytes())['$id']
SRC=json.loads((HERE/'retirement-source.schema.json').read_bytes())['$id']
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def schema():
    r=lambda n:{'$ref':SUP+'#/$defs/'+n}
    observation=obj(format_version={'const':'process-admission-observation/1'},observation_id=r('Id'),provider_id=r('Id'),
        domain_ref=r('ClockDomainRef'),member_id=r('Id'),member_boot_id=r('Id'),channel_binding_id=r('Id'),
        containment_ref=r('ContainmentRef'),artifact_manifest_ref=r('RuntimeManifestRef'),observed_tick_ns=r('U20'),
        process_instance_ref=obj(id=r('Id'),revision={'const':'1'},digest=r('Digest')),group_owned={'const':True},artifact_matches={'const':True},channel_exclusive={'const':True})
    body=obj(format_version={'const':'time-provider-runtime/0.1.0-draft.1'},binding_id=r('Id'),revision={'const':'1'},
        source={'$ref':SRC+'#/$defs/SourceIdentity'},descriptor=r('ClockDomainDescriptor'),intent=r('ProtectedLaunchIntent'),
        admission_receipt=r('AdmissionReceipt'),process_observation={'$ref':'#/$defs/ProcessObservation'},binding_digest=r('Digest'))
    body['properties']['intent']={'allOf':[r('ProtectedLaunchIntent'),{'properties':{'role':{'const':'time_provider'}}}]}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,
        '$defs':{'ProcessObservation':observation,'ProviderRuntime':body},'$ref':'#/$defs/ProviderRuntime'}
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'time-provider-source.schema.json'
    if a.check:assert path.read_bytes()==encoded()
    else:path.write_bytes(encoded())
