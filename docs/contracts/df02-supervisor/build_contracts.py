"""监督器局部候选唯一定义源；只生成资料，不启动进程或切换SDK权威。"""
import argparse
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/df02-supervisor/supervisor.schema.json'
INSTALL='https://leafseamer.invalid/design/c09-installation/installation-v02.schema.json'
PUBLIC=json.loads((HERE.parent/'draft4/first-loop.schema.json').read_bytes())['$id']
VERSION='supervisor-control/0.1.0-draft.1'
BOOT='bootstrap/0.1.0-draft.1'
def ref(n): return {'$ref':'#/$defs/'+n}
def ext(resource,n): return {'$ref':resource+'#/$defs/'+n}
def obj(**fields): return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def arr(item,limit=256): return dict(type='array',items=item,maxItems=limit,uniqueItems=True)
def const(v): return {'const':v}
def enum(*v): return {'enum':list(v)}
def nullable(v): return {'anyOf':[v,{'type':'null'}]}
def encoded(v): return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()


def build():
    d={n:ext(INSTALL,n) for n in ('Id','U20','Digest','RuntimeManifestRef','ContainmentRef','ExtensionLaunchIntent','LaunchAuthorization')}
    d.update({n:ext(PUBLIC,n) for n in ('ClockDomainRef','ClockDomainDescriptor')})
    # 32字节编码最后字符有16种合法低位形式；解码及往返仍须语义检查。
    d['Secret32']=dict(type='string',pattern='^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$(?![\\s\\S])')
    d['ProtectedLaunchIntent']=obj(launch_id=ref('Id'),service_id=ref('Id'),supervisor_instance_id=ref('Id'),runtime_generation=ref('Id'),member_id=ref('Id'),
        role=enum('core','time_provider'),artifact_manifest_ref=ref('RuntimeManifestRef'),containment_ref=ref('ContainmentRef'),device_ids=arr(ref('Id'),0),policy_revision=ref('U20'))
    d['LaunchIntent']={'oneOf':[ref('ExtensionLaunchIntent'),ref('ProtectedLaunchIntent')]}
    d['Scope']=obj(service_id=ref('Id'),database_instance_id=ref('Id'),supervisor_instance_id=ref('Id'),domain_ref=ref('ClockDomainRef'))
    d['LaunchKey']=obj(launch_id=ref('Id'),launch_intent_digest=ref('Digest'))
    d['FenceItem']=obj(launch_id=ref('Id'),launch_intent_digest=ref('Digest'),disposition=enum('allow','deny'))
    d['FenceSnapshot']=obj(scope=ref('Scope'),revision=ref('U20'),items=arr(ref('FenceItem')),digest=ref('Digest'))
    d['FenceResult']=obj(revision=ref('U20'),snapshot_digest=ref('Digest'),journal_committed=const(True))
    d['Register']=obj(intent=ref('ExtensionLaunchIntent'),authorization=ref('LaunchAuthorization'))
    d['Create']=obj(key=ref('LaunchKey'),authorization=ref('LaunchAuthorization'),materialization_evidence_id=ref('Id'),materialization_challenge_id=ref('Id'))
    common=dict(bootstrap_version=const(BOOT),bootstrap_id=ref('Id'),launch_id=ref('Id'),launch_intent_digest=ref('Digest'),member_id=ref('Id'),member_boot_id=ref('Id'),
        role=enum('core','worker','time_provider'),artifact_manifest_ref=ref('RuntimeManifestRef'),channel_binding_id=ref('Id'),challenge_id=ref('Id'))
    d['BootstrapAssignment']=obj(**common,clock_domain_descriptor=ref('ClockDomainDescriptor'),challenge_nonce=ref('Secret32'),issued_tick_ns=ref('U20'),expires_tick_ns=ref('U20'),secret=ref('Secret32'))
    d['BootstrapProof']=obj(**common,clock_domain_id=ref('Id'),descriptor_digest=ref('Digest'),proof=ref('Secret32'))
    receipt={k:v for k,v in common.items() if k not in ('bootstrap_version','challenge_id')}
    d['AdmissionReceipt']=obj(**receipt,receipt_id=ref('Id'),domain_ref=ref('ClockDomainRef'),containment_ref=ref('ContainmentRef'),os_observation_ref=ref('Id'),admitted_tick_ns=ref('U20'),gate_state=const('closed'))
    d['RetirementEvidence']=obj(evidence_id=ref('Id'),service_id=ref('Id'),old_domain_ref=ref('ClockDomainRef'),target_scope=enum('member_group','runtime_domain'),
        target_member_ids=arr(ref('Id')),containment_ref=ref('ContainmentRef'),launch_intake_closed=dict(type='boolean'),os_observation_refs=arr(ref('Id')),
        result=enum('confirmed_empty','unproven'),evaluator_domain_ref=ref('ClockDomainRef'),observed_tick_ns=ref('U20'))
    d['JournalView']=obj(key=ref('LaunchKey'),supervisor_instance_id=ref('Id'),state=enum('registered','creating','awaiting_bootstrap','admitted_closed','retiring','retired','rejected','indeterminate'),
        creation_attempted=dict(type='boolean'),admission_receipt=nullable(ref('AdmissionReceipt')),retirement_evidence=nullable(ref('RetirementEvidence')),gate_state=const('closed'))
    d['LaunchResult']=obj(key=ref('LaunchKey'),record=nullable(ref('JournalView')))
    d['RetireRequest']=obj(key=ref('LaunchKey'),containment_ref=ref('ContainmentRef'),reason=enum('revoked','shutdown','bootstrap_failed','recovery'))
    d['Error']=obj(code=enum('identity_conflict','stale_fence','unauthorized','invalid_binding','expired','capacity','journal_unavailable','indeterminate','not_found'),retry_action=const('query_only'))
    requests={'FENCE_PUT':'FenceSnapshot','LAUNCH_REGISTER':'Register','LAUNCH_CREATE':'Create','LAUNCH_QUERY':'LaunchKey','RETIRE_REQUEST':'RetireRequest'}
    responses={'FENCE_RESULT':'FenceResult','LAUNCH_RESULT':'LaunchResult','RETIRE_RESULT':'RetirementEvidence','ERROR':'Error'}
    frames=[]
    for name,model in (requests|responses).items():
        frame=obj(version=const(VERSION),type=const(name),scope=ref('Scope'),channel_id=ref('Id'),sequence=ref('U20'),message_id=ref('Id'),
            reply_to={'type':'null'} if name in requests else ref('Id'),payload=ref(model))
        d[name]=frame;frames.append(ref(name))
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'$defs':d,'oneOf':frames}
    bootframes=[]
    for name,model in {'ASSIGNMENT':'BootstrapAssignment','PROOF':'BootstrapProof','ADMISSION':'AdmissionReceipt','REJECT':'Error'}.items():
        bootframes.append(obj(version=const(BOOT),type=const(name),payload=ext(SID,model)))
    boot={'$schema':schema['$schema'],'$id':SID.replace('supervisor.schema','bootstrap.schema'),'oneOf':bootframes}
    return {'supervisor.schema.json':schema,'bootstrap.schema.json':boot}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,value in build().items():
        if a.check: assert (HERE/name).read_bytes()==encoded(value),name
        else: (HERE/name).write_bytes(encoded(value))
    print('监督器候选生成物一致' if a.check else '已生成监督器候选')
