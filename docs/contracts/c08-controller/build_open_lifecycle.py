"""开放提交前后资格候选；保留旧四对象格式，显式生成0.2语义对象。"""
import argparse,json
from pathlib import Path
import build_open_plan as O
HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/c08-controller/open-lifecycle.schema.json'
def ref(n):return {'$ref':'#/$defs/'+n}
def old(n):return {'$ref':O.SID+'#/$defs/'+n}
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def nullable(s):return {'anyOf':[s,{'type':'null'}]}
def build():
    d={
      'EligibilityRefs':obj(control_authority=old('Ref'),resource_safety=old('Ref'),authorization=old('Ref')),
      'Holder':obj(issuer_id=old('Id'),issuer_epoch=old('Id'),principal_id=old('Id')),
      'ControlProjection':obj(record_ref=old('Ref'),authority_ref=old('Ref'),control_epoch=old('Id'),
          effective_version=old('Counter'),mode={'enum':['automatic','manual']},holder=nullable(ref('Holder')),
          pending_operation_id=nullable(old('Id')),gate_state={'enum':['protected','fencing','ready']}),
      'GateProjection':obj(record_ref=old('Ref'),binding=old('Binding'),gate_revision=old('Counter'),gate_token=old('Id'),
          barrier_id=old('Id'),phase={'enum':['fenced','protected','ready']},ready_activation_id=nullable(old('Id')),
          lease_until_tick_ns=old('Counter')),
    }
    d['OpenPlanV02']=obj(format_version={'const':'gate-open-plan/0.2.0-draft.1'},
        plan=old('OpenPlan'),eligibility_refs=ref('EligibilityRefs'),control_before=ref('ControlProjection'),gate_before=ref('GateProjection'),
        proposal_digest=old('Digest'))
    d['ReadyTransition']=obj(format_version={'const':'gate-ready-transition/0.2.0-draft.1'},
        ready=old('ReadyCommit'),proposal_ref=old('Ref'),control_after=ref('ControlProjection'),gate_after=ref('GateProjection'),
        eligibility_refs=ref('EligibilityRefs'),transition_digest=old('Digest'))
    d['HoldObservation']=obj(hold_ref=old('Ref'),owner_ref=old('Ref'),control_authority_ref=old('Ref'),
        state={'enum':['active','unknown','failed_unresolved','orphaned','proof_revoked']})
    d['ResourceSafetyEvidence']=obj(evidence_id=old('Id'),revision={'const':'1'},device_id=old('Id'),
        observed_resource_ref=old('Ref'),resource_safety_ref=old('Ref'),control_authority_ref=old('Ref'),
        holds=dict(type='array',items=ref('HoldObservation'),maxItems=65536),
        provider_receipt_ref=old('Ref'),evidence_digest=old('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'title':'gate-open-lifecycle/0.2.0-draft.1',
        'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}
def encoded():return (json.dumps(build(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'open-lifecycle.schema.json'
    if a.check:assert path.read_bytes()==encoded(),'生成漂移'
    else:path.write_bytes(encoded())
