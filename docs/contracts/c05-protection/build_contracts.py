"""来源保护局部格式源；不替换公共SDK或设备IPC联合，不实现服务。"""
import argparse
import copy
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
INGRESS=HERE.parent/'c05-ingress/ingress.schema.json'
SID='https://leafseamer.invalid/design/c05-protection/protection.schema.json'
VERSION='source-protection/0.1.0-draft.1'


def ref(n): return {'$ref':'#/$defs/'+n}
def obj(**p): return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def enum(*v): return {'enum':list(v)}
def const(v): return {'const':v}
def nullable(v): return {'anyOf':[v,{'type':'null'}]}
def arr(v,n=4096): return dict(type='array',items=v,maxItems=n)


def build():
    old=json.loads(INGRESS.read_bytes())
    d={n:copy.deepcopy(old['$defs'][n]) for n in ('Id','Counter','PositiveCounter','Digest','Scope','Ref','SourceKey')}
    ident,rev,dg=ref('Id'),ref('Counter'),ref('Digest')
    d['SourceState']=enum('baseline_required','synchronized','desynchronized','quarantined','closed')
    d['Gap']={'oneOf':[obj(kind=const('known'),first=ref('PositiveCounter'),last=ref('PositiveCounter')),
                       obj(kind=enum('unknown','none'))]}
    d['SourceFault']=obj(scope=ref('Scope'),fault_id=ident,detector_domain_ref=ref('Ref'),detector_sequence=rev,
        source_key=ref('SourceKey'),reason=enum('sequence_gap','content_conflict','source_changed','capture_lost',
            'admission_rollback','age_invalid','storage_failure','capacity_exhausted','source_closed'),
        source_revision_at_detection=rev,observed_event_ref=nullable(ref('Ref')),gap=ref('Gap'),
        evidence_refs=arr(ref('Ref')),fault_digest=dg)
    d['RunGenerationSelector']=obj(kind=const('run_generation'),origin_scope=ref('Scope'),run_id=ident,deny_through_generation=rev)
    d['AutomationOriginBinding']=obj(origin_scope=ref('Scope'),run_id=ident,definition_version=ref('PositiveCounter'),
        arm_generation=rev,execution_id=ident,execution_binding_ref=ref('Ref'),step_id=ident,logical_action_id=ident)
    d['OriginExtension']=obj(origin=enum('manual','automation'),automation_binding=nullable(ref('AutomationOriginBinding')),
        automation_binding_digest=nullable(dg))
    d['OriginExtension']['allOf']=[{'if':{'properties':{'origin':const('automation')},'required':['origin']},
        'then':{'properties':{'automation_binding':ref('AutomationOriginBinding'),'automation_binding_digest':dg}},
        'else':{'properties':{'automation_binding':{'type':'null'},'automation_binding_digest':{'type':'null'}}}}]
    d['ControllerTarget']=obj(target_id=ident,controller_scope=ref('Scope'),selector=ref('RunGenerationSelector'),
        selector_digest=dg,preparation_refs=arr(ref('Ref')),submission_refs=arr(ref('Ref')),target_digest=dg)
    d['RunProtectionTarget']=obj(target_id=ident,run_id=ident,run_revision_before=rev,run_revision_after=rev,
        arm_generation=rev,dependency_refs=arr(ref('Ref')),execution_refs=arr(ref('Ref')),latch_id=ident,
        controllers=arr(ref('ControllerTarget'),256))
    d['SourceProtectionPlan']=obj(scope=ref('Scope'),protection_id=ident,fault_ref=ref('Ref'),
        dependency_index_revision=rev,source_state_before=ref('SourceState'),source_state_after=ref('SourceState'),
        source_revision_before=rev,source_revision_after=rev,targets=arr(ref('RunProtectionTarget')),
        targets_digest=dg,plan_digest=dg)
    d['SourcePauseLatch']=obj(scope=ref('Scope'),latch_id=ident,run_id=ident,protection_ref=ref('Ref'),
        source_key=ref('SourceKey'),blocked_through_generation=rev,created_run_revision=rev,latch_digest=dg)
    d['SourceProtectionRecord']=obj(plan_ref=ref('Ref'),revision=rev,local_state=const('committed'),
        remote_state=enum('pending','applying','applied','indeterminate'),receipt_refs=arr(ref('Ref')),
        unresolved_target_ids=arr(ident))
    d['ControllerRunFenceReceipt']=obj(controller_scope=ref('Scope'),operation_id=ident,selector=ref('RunGenerationSelector'),
        selector_digest=dg,cut_revision=rev,target_set_digest=dg,barrier_ref=ref('Ref'),
        applied_deny_through_generation=rev,coverage_ref=ref('Ref'),status=enum('applied','indeterminate'),receipt_digest=dg)
    d['ControllerProtectionRecord']=obj(controller_scope=ref('Scope'),operation_id=ident,selector=ref('RunGenerationSelector'),
        selector_digest=dg,target_set_digest=dg,revision=rev,state=enum('accepted','fencing','applied','indeterminate'),
        receipt_ref=nullable(ref('Ref')))
    d['ControllerProtectionRecord']['allOf']=[{'if':{'properties':{'state':const('applied')},'required':['state']},
        'then':{'properties':{'receipt_ref':ref('Ref')}}}]
    d['SourceRebaselineReceipt']=obj(source_key=ref('SourceKey'),old_source_revision=rev,new_source_revision=rev,
        baseline_ref=ref('Ref'),baseline_sequence=rev,reject_floor=rev,unresolved_gap_refs=arr(ref('Ref')),
        protection_refs=arr(ref('Ref')),receipt_digest=dg)
    d['SourcePauseResolution']=obj(latch_ref=ref('Ref'),rebaseline_ref=ref('Ref'),fence_receipt_refs=arr(ref('Ref')),
        resource_resolution_refs=arr(ref('Ref')),new_arm_generation=rev,preflight_ref=ref('Ref'),resolution_digest=dg)
    d['ProtectionRequest']=obj(contract_version=const(VERSION),operation_id=ident,controller_scope=ref('Scope'),
        selector=ref('RunGenerationSelector'),selector_digest=dg,target_set_digest=dg,basis=enum('durable_protection','emergency_fault'),
        protection_ref=nullable(ref('Ref')),detector_domain_ref=ref('Ref'))
    d['ProtectionRequest']['allOf']=[{'if':{'properties':{'basis':const('durable_protection')},'required':['basis']},
        'then':{'properties':{'protection_ref':ref('Ref')}},
        'else':{'properties':{'protection_ref':{'type':'null'}}}}]
    # 完整发送世代和原始守卫摘要的局部投影；不是旧IntentRef的悄悄替换。
    d['RunIntent']=obj(permit_id=ident,command_id=ident,attempt_id=ident,dispatch_intent_id=ident,
        controller_boot_id=ident,worker_boot_id=ident,device_session_id=ident,ipc_session_id=ident,device_id=ident,
        guard_id=ident,guard_digest=dg,clock_domain_id=dict(type='string',pattern=r'^clock_[0-9a-f]{64}(?![\s\S])'),descriptor_digest=dg,
        automation_binding=ref('AutomationOriginBinding'),automation_binding_digest=dg)
    d['RunCoverage']=obj(intent=ref('RunIntent'),disposition=enum('not_sent','in_flight','unknown'),
        proof=enum('never_received','discarded_unconsumed','transport_entered','send_uncertain'))
    d['RunCoverage']['allOf']=[
        {'if':{'properties':{'disposition':const(k)},'required':['disposition']},
         'then':{'properties':{'proof':enum(*v)}}}
        for k,v in [('not_sent',['never_received','discarded_unconsumed']),
                    ('in_flight',['transport_entered']),('unknown',['send_uncertain'])]]
    d['RunFenceBody']=obj(operation_id=ident,barrier_id=ident,controller_scope=ref('Scope'),
        selector=ref('RunGenerationSelector'),selector_digest=dg,issued_cut_revision=rev,
        target_deny_revision=rev,ledger_digest=dg,open_intents=arr(ref('RunIntent')))
    d['RunFenceAckBody']=obj(operation_id=ident,barrier_id=ident,controller_scope=ref('Scope'),
        selector=ref('RunGenerationSelector'),selector_digest=dg,issued_cut_revision=rev,
        target_deny_revision=rev,ledger_digest=dg,coverage=arr(ref('RunCoverage')),all_write_exits_fenced=const(True))
    s={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,
       'title':VERSION+' 局部候选，须选择具名模型','not':{},'$defs':d}
    body={'$schema':s['$schema'],'$id':SID.replace('protection.schema','run-fence.schema'),
        'title':'仅RUN_FENCE两种正文的设计包络，非完整设备IPC',
        'oneOf':[obj(protocol=const('run-fence-body/0.1.0-draft.1'),type=const(t),
                    body={'$ref':SID+'#/$defs/'+n})
                 for t,n in [('RUN_FENCE','RunFenceBody'),('RUN_FENCE_ACK','RunFenceAckBody')]]}
    return {'protection.schema.json':s,'run-fence.schema.json':body}


def encoded(v): return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    for name,data in build().items():
        if args.check: assert (HERE/name).read_bytes()==encoded(data),name
        else:(HERE/name).write_bytes(encoded(data))
