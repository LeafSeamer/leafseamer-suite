"""最终准入封存字段候选；不改变既有IPC、SQL守卫或签发实现。"""
import argparse,copy,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/c04-lifecycle/final-admission.schema.json'
VERSION='final-admission/0.1.0-draft.1'
BASE=HERE.parent/'c08-controller/scoped-gate.schema.json'
SOURCES=[Path(__file__),BASE]
# 每项都是具名业务原件，不能以一个all_verified布尔值代替。
COMMON=('origin','capability','encoding','authorization','control','gate_commit','gate_access',
        'ownership','permit_authority','guard','budget','time','resource_before','resource_after',
        'resource_safety','gate_safety','run_deny','command_deny')
CANCEL=('ordinary_closure','protection_assessment','primitive_dependency')
def ref(n):return {'$ref':'#/$defs/'+n}
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def optional(v):return {'anyOf':[v,{'type':'null'}]}
def build():
    old=json.loads(BASE.read_bytes())['$defs']
    d={n:copy.deepcopy(old[n]) for n in ('Id','Counter','Digest','Ref','Scope','Binding','Principal','ExecutionIdentity')}
    d['Inputs']=obj(**{n:ref('Ref') for n in COMMON},**{n:optional(ref('Ref')) for n in CANCEL})
    d['Window']=obj(not_before_tick_ns=ref('Counter'),before_tick_ns=ref('Counter'))
    fields={
      'origin':dict(command_state_ref=ref('Ref')),
      'capability':dict(encoding_source_ref=ref('Ref')),
      'encoding':dict(packet_record_ref=ref('Ref'),packet_ref=obj(packet_id=ref('Id'),packet_digest=ref('Digest')),received_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter')),
      'authorization':dict(not_before_tick_ns=ref('Counter'),before_tick_ns=ref('Counter')),
      'control':dict(pending_operation_id=optional(ref('Id')),control_epoch=ref('Id'),effective_version=ref('Counter'),mode={'enum':['automatic','manual']},holder=optional(ref('Principal'))),
      'gate_commit':dict(access_ref=ref('Ref')),
      'gate_access':dict(purpose={'enum':['ordinary','cancel_only']},restricted_identity=optional(ref('ExecutionIdentity')),control_authority_ref=ref('Ref'),control_epoch=ref('Id'),effective_version=ref('Counter'),authorization_ref=ref('Ref'),resource_safety_ref=ref('Ref'),gate_safety_ref=ref('Ref'),not_before_tick_ns=ref('Counter'),before_tick_ns=ref('Counter')),
      'ownership':dict(hold_ref=ref('Ref'),control_authority_ref=ref('Ref'),control_epoch=ref('Id'),effective_version=ref('Counter')),
      'permit_authority':dict(hold_ref=ref('Ref'),permit_id=ref('Id'),issued_revision=ref('Counter'),ordinal=ref('Counter'),transmission_id=ref('Id'),ownership_ref=ref('Ref'),control_authority_ref=ref('Ref'),authorization_ref=ref('Ref'),guard_ref=ref('Ref'),packet_ref=ref('Ref'),control_epoch=ref('Id'),effective_version=ref('Counter')),
      'guard':dict(permit_id=ref('Id'),issued_revision=ref('Counter'),packet_ref=obj(packet_id=ref('Id'),packet_digest=ref('Digest')),gate_access_ref=ref('Ref'),ownership_ref=ref('Ref'),protection_assessment_ref=optional(ref('Ref')),not_before_tick_ns=ref('Counter'),before_tick_ns=ref('Counter')),
      'budget':dict(permit_id=ref('Id'),issued_revision=ref('Counter'),charge_kind={'const':'new_transmission'},charged_permit_id=ref('Id'),not_before_tick_ns=ref('Counter'),before_tick_ns=ref('Counter')),
      'time':dict(permit_id=ref('Id'),issued_revision=ref('Counter'),clock_domain_id=d['Binding']['properties']['clock_domain_id'],descriptor_digest=ref('Digest'),not_before_tick_ns=ref('Counter'),before_tick_ns=ref('Counter')),
      'resource_before':dict(resource_safety_ref=ref('Ref'),holds={'type':'array','maxItems':65536,'items':obj(hold_ref=ref('Ref'),ownership_ref=ref('Ref'),classification={'enum':['active','unknown','unresolved','stale']})}),
      'resource_safety':{},'gate_safety':{},'run_deny':{},'command_deny':{},
      'ordinary_closure':dict(stage={'const':'ordinary'}),
      'protection_assessment':dict(resource_ref=ref('Ref')),
      'primitive_dependency':dict(execution_ref=ref('Ref'),transmission_id=ref('Id'))}
    fields['resource_after']=copy.deepcopy(fields['resource_before'])
    for role,props in fields.items():
        # 这是供本地投影器实现的归一化字段，不能冒充原领域完整正文。
        d['Projection_'+role]=obj(binding=ref('Binding'),identity=ref('ExecutionIdentity'),**props)
        d['Original_'+role]=obj(role={'const':role},ref=ref('Ref'),source_ref=ref('Ref'),scope=ref('Scope'),transaction_id=ref('Id'),body=ref('Projection_'+role))
    d['Seal']=obj(format_version={'const':VERSION},seal_id=ref('Id'),revision={'const':'1'},transaction_id=ref('Id'),
        binding=ref('Binding'),identity=ref('ExecutionIdentity'),command_state_ref=ref('Ref'),
        permit_id=ref('Id'),transmission_id=ref('Id'),issued_revision=ref('Counter'),ordinal=ref('Counter'),
        transmission_kind={'enum':['initial','protocol_resend']},previous_permit_ref=optional(ref('Ref')),
        packet_ref=obj(packet_id=ref('Id'),packet_digest=ref('Digest')),encoding_packet_ref=ref('Ref'),
        hold_ref=ref('Ref'),hold_transition={'enum':['create','reuse']},inputs=ref('Inputs'),
        selected_tick_ns=ref('Counter'),sealed_tick_ns=ref('Counter'),send_window=ref('Window'),seal_digest=ref('Digest'))
    d['Seal']['allOf']=[
      {'if':{'properties':{'identity':{'properties':{'kind':{'const':'ordinary'}}}}},
       'then':{'properties':{'inputs':{'properties':{n:{'type':'null'} for n in CANCEL}}}},
       'else':{'properties':{'inputs':{'properties':{n:ref('Ref') for n in CANCEL}},'hold_transition':{'const':'reuse'}}}},
      {'if':{'properties':{'transmission_kind':{'const':'initial'}}},
       'then':{'properties':{'ordinal':{'const':'0'},'previous_permit_ref':{'type':'null'}}},
       'else':{'properties':{'previous_permit_ref':ref('Ref'),'hold_transition':{'const':'reuse'}}}}]
    # 提交结果只向seal引用；seal不包含自己的提交见证或未来Guard ACK。
    d['CommitObservation']=obj(observation_id=ref('Id'),transaction_id=ref('Id'),scope=ref('Scope'),
        seal_ref=ref('Ref'),permit_id=ref('Id'),outcome={'enum':['committed','rolled_back','unknown']},
        observed_tick_ns=ref('Counter'),observer_ref=ref('Ref'),observation_digest=ref('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'title':VERSION,
        'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}
def raw(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'final-admission.schema.json'
    if a.check:assert target.read_bytes()==raw(build())
    else:target.write_bytes(raw(build()))
