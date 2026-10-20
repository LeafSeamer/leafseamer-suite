"""命令终态及资源裁决的局部机器契约；不替换旧公共CommandRecord。"""
import argparse
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/c08-controller/lifecycle.schema.json'
VERSION='controller-lifecycle/0.1.0-draft.1'

def obj(**fields):
    return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def ref(name):return {'$ref':'#/$defs/'+name}
def enum(*values):return {'enum':list(values)}
def nullable(value):return {'anyOf':[value,{'type':'null'}]}
def arr(value,minimum=0):return dict(type='array',items=value,minItems=minimum,maxItems=256)
def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()

def build():
    d={}
    d['Id']=dict(type='string',minLength=1,maxLength=256,pattern='^[A-Za-z0-9._:/-]+$(?![\\s\\S])')
    d['Counter']=dict(type='string',pattern='^(0|[1-9][0-9]{0,19})$(?![\\s\\S])')
    d['PositiveCounter']=dict(type='string',pattern='^[1-9][0-9]{0,19}$(?![\\s\\S])')
    d['Digest']=dict(type='string',pattern='^sha256:[0-9a-f]{64}$(?![\\s\\S])')
    d['Ref']=obj(id=ref('Id'),revision=ref('PositiveCounter'),digest=ref('Digest'))
    d['PacketRef']=obj(packet_id=ref('Id'),packet_digest=ref('Digest'))
    d['Scope']=obj(authority_service_id=ref('Id'),database_instance_id=ref('Id'))
    d['CompletionLevel']=enum('sent','acknowledged','effect_verified')
    d['Effect']=enum('not_sent','possible','acknowledged','verified','partial')
    d['Policy']=obj(command_id=ref('Id'),scope=ref('Scope'),device_id=ref('Id'),
        admission_ref=ref('Ref'),required_completion=ref('CompletionLevel'),
        completion_policy_ref=ref('Ref'),release_policy_ref=ref('Ref'),
        retry_policy_ref=nullable(ref('Ref')),max_attempts=dict(type='integer',minimum=1,maximum=16),
        original_deadline_ref=ref('Ref'),conflict_scope={'const':'whole_device'})
    d['Policy']['allOf']=[{'if':{'properties':{'retry_policy_ref':{'type':'null'}}},
                          'then':{'properties':{'max_attempts':{'const':1}}}}]
    d['State']=obj(command_id=ref('Id'),scope=ref('Scope'),revision=ref('PositiveCounter'),
        phase=enum('queued','dispatching','awaiting_evidence','finished'),
        outcome=enum('pending','succeeded','failed','unknown','cancelled','expired','blocked'),
        effect_status=ref('Effect'),resource_status=enum('held','clear','unresolved'),
        automation_continuation=enum('eligible','paused_latched'),reason_code=nullable(ref('Id')),
        terminal_revision=nullable(ref('PositiveCounter')),resolution_ref=nullable(ref('Ref')),
        completion_evidence_refs=arr(ref('Ref')),resource_evidence_refs=arr(ref('Ref')),
        attempt_ids=arr(ref('Id')))
    d['State']['allOf']=[
        {'if':{'properties':{'phase':{'const':'finished'}}},
         'then':{'properties':{'outcome':{'not':{'const':'pending'}},'terminal_revision':ref('PositiveCounter')}},
         'else':{'properties':{'outcome':{'const':'pending'},'terminal_revision':{'type':'null'},'resolution_ref':{'type':'null'}}}},
        {'if':{'properties':{'outcome':enum('failed','unknown','cancelled','expired','blocked')}},
         'then':{'properties':{'reason_code':ref('Id')}}},
        {'if':{'properties':{'outcome':enum('unknown','blocked','expired')}},
         'then':{'properties':{'automation_continuation':{'const':'paused_latched'}}}},
        {'if':{'properties':{'outcome':{'const':'unknown'}}},
         'then':{'properties':{'effect_status':{'not':{'const':'not_sent'}}}}},
        {'if':{'properties':{'outcome':{'const':'unknown'},'resource_status':{'const':'clear'}}},
         'then':{'properties':{'resolution_ref':ref('Ref'),'resource_evidence_refs':arr(ref('Ref'),1)}}}]
    d['Transmission']=obj(permit_id=ref('Id'),transmission_id=ref('Id'),attempt_id=ref('Id'),
        packet_ref=ref('PacketRef'),exit_ref=ref('Ref'),issued_revision=ref('PositiveCounter'),
        disposition=enum('not_sent','in_flight','unknown'),
        settlement_kind=nullable(enum('never_sent','effect_resolved')),settlement_ref=nullable(ref('Ref')))
    d['Transmission']['allOf']=[{'if':{'properties':{'settlement_kind':{'type':'null'}}},
        'then':{'properties':{'settlement_ref':{'type':'null'}}},
        'else':{'properties':{'settlement_ref':ref('Ref')}}}]
    d['ResourceCut']=obj(cut_id=ref('Id'),command_id=ref('Id'),scope=ref('Scope'),
        device_id=ref('Id'),hold_id=ref('Id'),issued_cut_revision=ref('Counter'),
        attempt_ids=arr(ref('Id')),transmissions=arr(ref('Transmission')),
        cut_digest=ref('Digest'))
    d['ReleaseEvidence']=obj(evidence_id=ref('Id'),command_id=ref('Id'),scope=ref('Scope'),
        device_id=ref('Id'),hold_id=ref('Id'),cut_ref=ref('Ref'),
        kind=enum('never_sent','module_settled','maintenance_fenced'),
        policy_ref=ref('Ref'),future_writes_closed_ref=ref('Ref'),
        settlement_proof_ref=nullable(ref('Ref')),evidence_digest=ref('Digest'))
    d['ReleaseEvidence']['allOf']=[{'if':{'properties':{'kind':{'const':'never_sent'}}},
        'then':{'properties':{'settlement_proof_ref':{'type':'null'}}},
        'else':{'properties':{'settlement_proof_ref':ref('Ref')}}}]
    # 提供者回执是内部可信存储对象；公共或worker提交同形JSON不取得权威。
    d['ProviderReceipt']=obj(receipt_id=ref('Id'),scope=ref('Scope'),command_id=ref('Id'),
        subject_digest=ref('Digest'),policy_ref=ref('Ref'),
        verdict=enum('accepted','rejected','indeterminate'),
        claims=arr(enum('future_writes_closed','module_settled','maintenance_settled',
                       'never_sent','completion_sent','completion_acknowledged','completion_verified',
                       'failure_confirmed','safe_failure','cancellation_confirmed','resolution_supported'),1),
        source_refs=arr(ref('Ref'),1),record_revision=ref('PositiveCounter'))
    d['DecisionEvidence']=obj(evidence_id=ref('Id'),command_id=ref('Id'),scope=ref('Scope'),
        kind=enum('completion','failure','cancellation','resolution'),
        policy_ref=ref('Ref'),retry_policy_ref=nullable(ref('Ref')),attempt_ids=arr(ref('Id')),
        achieved=nullable(ref('CompletionLevel')),effect_status=ref('Effect'),
        resolved_outcome=nullable(enum('succeeded','failed','cancelled','not_sent')),
        evidence_digest=ref('Digest'))
    d['DecisionEvidence']['allOf']=[
        {'if':{'properties':{'kind':{'const':'completion'}}},
         'then':{'properties':{'achieved':ref('CompletionLevel')}},
         'else':{'properties':{'achieved':{'type':'null'}}}},
        {'if':{'properties':{'kind':{'const':'resolution'}}},
         'then':{'properties':{'resolved_outcome':enum('succeeded','failed','cancelled','not_sent')}},
         'else':{'properties':{'resolved_outcome':{'type':'null'}}}}]
    d['Resolution']=obj(resolution_id=ref('Id'),command_id=ref('Id'),scope=ref('Scope'),
        original_terminal_revision=ref('PositiveCounter'),revision=ref('PositiveCounter'),
        resolved_outcome=enum('succeeded','failed','cancelled','not_sent'),
        evidence_refs=arr(ref('Ref'),1),resolver_ref=ref('Ref'),resolution_digest=ref('Digest'))
    d['Transition']=obj(operation_id=ref('Id'),expected_state_ref=ref('Ref'),
        kind=enum('dispatch','transport','complete','fail','timeout','cancel','block','expire',
                  'retry','reconcile','release','protect'),
        after=ref('State'),decision_evidence=nullable(ref('DecisionEvidence')),
        release_evidence=nullable(ref('ReleaseEvidence')),resolution=nullable(ref('Resolution')),
        audit_ref=ref('Ref'),outbox_ref=ref('Ref'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,
            'title':VERSION,'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    data=encoded(build());path=HERE/'lifecycle.schema.json'
    if args.check:assert path.read_bytes()==data
    else:path.write_bytes(data)
