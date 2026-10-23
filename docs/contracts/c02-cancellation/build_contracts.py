"""取消保护候选生成器；不修改旧协议，不实现设备发送。"""
import argparse
import copy
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
OLD=BASE/'c08-controller/execution-ipc.schema.json'
CID='https://leafseamer.invalid/design/c02-cancellation/cancellation.schema.json'
IID='https://leafseamer.invalid/design/c02-cancellation/ipc.schema.json'
VERSION='ipc/0.7.0-cancellation-draft.1'
FEATURES=('command_cancel_deny','separate_cancel_execution','complete_cancel_transmission_fence')
FENCES=('FENCE','AUTH_FENCE','TIME_FENCE','RUN_FENCE')
RESPONSES={'CANCEL_FENCE_ACK','CANCEL_GUARD_ACK','PREPARE_CANCEL_PACKET',
           'CANCEL_ENCODING_FAILED','CANCEL_PREPARE_REJECTED','CANCEL_RESEND_REJECTED','CANCEL_EXECUTION_STATUS'}
NEW_FRAMES=('CANCEL_FENCE','CANCEL_FENCE_ACK','CANCEL_GUARD','CANCEL_GUARD_ACK',
 'ENCODE_CANCEL_PACKET','PREPARE_CANCEL_PACKET','CANCEL_ENCODING_FAILED','CANCEL_PREPARE_REJECTED',
 'DISPATCH_CANCEL','CANCEL_RESEND_REQUEST','CANCEL_RESEND_REJECTED','CANCEL_SEND_REPORT',
 'CANCEL_REPORT_STORED','CANCEL_EVIDENCE_CANDIDATE','QUERY_CANCEL_EXECUTION','CANCEL_EXECUTION_STATUS')


def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def ref(n):return {'$ref':'#/$defs/'+n}
def arr(s,max_items=256):return dict(type='array',items=s,maxItems=max_items)
def nullable(s):return {'anyOf':[s,{'type':'null'}]}
def enum(*v):return {'enum':list(v)}
def ext(uri,n):return {'$ref':uri+'#/$defs/'+n}
def encoded(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def add(s,**fields):
    assert not set(fields)&set(s['properties'])
    s['properties'].update(fields);s['required']+=list(fields)


def models():
    old=json.loads(OLD.read_bytes());oid=old['$id']
    public='https://leafseamer.invalid/contracts/draft4/first-loop.schema.json'
    lifecycle='https://leafseamer.invalid/design/c08-controller/lifecycle.schema.json'
    view='https://leafseamer.invalid/design/c02-command-view/command.schema.json'
    d={n:copy.deepcopy(old['$defs'][n]) for n in ('Counter','PositiveCounter','Id','Digest')}
    for n in ('SendWindow','TransmissionRef','TransmissionCoverage','BarrierAttemptBinding','ContentRef','PacketRef'):
        d[n]=ext(oid,n)
    d['Ref']=ext(lifecycle,'Ref')
    d['Scope']=ext(lifecycle,'Scope')
    d['CancelIdentity']=ext(view,'CancelIdentity')
    d['Exit']=obj(writer_exit_id=ref('Id'),controller_boot_id=ref('Id'),worker_boot_id=ref('Id'),
        ipc_session_id=ref('Id'),device_id=ref('Id'),device_session_id=ref('Id'),socket_instance_id=ref('Id'),
        clock_domain_id={'type':'string','pattern':'^clock_[0-9a-f]{64}$(?![\\s\\S])'},descriptor_digest=ref('Digest'))
    d['CancellationBinding']=obj(scope=ref('Scope'),cancellation_id=ref('Id'),parent_command_id=ref('Id'),
        initial_operation_ref=ref('Ref'),identity=ref('CancelIdentity'),mode=enum('before_dispatch_only','cooperative'),
        policy_ref=ref('Ref'))
    d['DenyEntry']=obj(cancellation_id=ref('Id'),parent_command_id=ref('Id'),stage=enum('ordinary','all'),
        deny_revision=ref('PositiveCounter'),cut_ref=ref('Ref'))
    d['DenySnapshot']=obj(scope=ref('Scope'),device_id=ref('Id'),snapshot_revision=ref('Counter'),
        entries=arr(ref('DenyEntry'),4096),snapshot_digest=ref('Digest'))
    d['Requester']=obj(actor_ref=ref('Ref'),authorization_ref=ref('Ref'),origin=enum('manual','automation'),
        admission_origin=enum('panel','non_panel'),panel_binding_ref=nullable(ref('Ref')),
        automation_binding_ref=nullable(ref('Ref')))
    d['Requester']['allOf']=[
        {'if':{'properties':{'origin':{'const':'automation'}}},
         'then':{'properties':{'automation_binding_ref':ref('Ref'),'admission_origin':{'const':'non_panel'}}},
         'else':{'properties':{'automation_binding_ref':{'type':'null'}}}},
        {'if':{'properties':{'admission_origin':{'const':'panel'}}},
         'then':{'properties':{'panel_binding_ref':ref('Ref'),'origin':{'const':'manual'}}},
         'else':{'properties':{'panel_binding_ref':{'type':'null'}}}}]
    d['Policy']=obj(policy_id=ref('Id'),revision=ref('PositiveCounter'),mode=enum('before_dispatch_only','cooperative'),
        procedure_ref=nullable(ref('Ref')),completion_policy_ref=ref('Ref'),release_policy_ref=ref('Ref'),
        resource_keys={**arr(ref('Id')),'minItems':1,'uniqueItems':True},max_transmissions={'type':'integer','minimum':1,'maximum':256},
        allow_protocol_resend={'type':'boolean'},application_attempts={'const':1},policy_digest=ref('Digest'))
    d['Policy']['allOf']=[{'if':{'properties':{'mode':{'const':'cooperative'}}},
        'then':{'properties':{'procedure_ref':ref('Ref')}},
        'else':{'properties':{'procedure_ref':{'type':'null'},'allow_protocol_resend':{'const':False}}}}]
    d['Primitive']=obj(primitive_id=ref('Id'),action_ref=ref('Ref'),parameters_schema_ref=ref('Ref'),
        parameters={'type':'object'},after=arr(ref('Id')),completion_policy_ref=ref('Ref'))
    d['ExecutionPlan']=obj(execution_id=ref('Id'),binding=ref('CancellationBinding'),requester=ref('Requester'),
        device_id=ref('Id'),ordinary_closure_ref=ref('Ref'),policy_ref=ref('Ref'),
        protected_hold_ref=ref('Ref'),resource_keys={**arr(ref('Id')),'minItems':1,'uniqueItems':True},
        primitives={**arr(ref('Primitive')),'minItems':1},execution_digest=ref('Digest'))
    d['ExecutionPlan']['properties']['binding']={'allOf':[ref('CancellationBinding'),
        {'properties':{'mode':{'const':'cooperative'}}}]}
    d['Guard']=obj(guard_id=ref('Id'),execution_ref=ref('Ref'),requester=ref('Requester'),exit=ref('Exit'),
        control_epoch=ref('Id'),control_version=ref('PositiveCounter'),gate_revision=ref('PositiveCounter'),
        authorization_revision=ref('PositiveCounter'),time_required={'type':'boolean'},
        time_evidence_ref=nullable(ref('Ref')),
        time_policy_ref=nullable(ref('Ref')),guard_provider_ref=ref('Ref'),protected_hold_ref=ref('Ref'),
        deny_revision=ref('PositiveCounter'),send_window=ref('SendWindow'),guard_digest=ref('Digest'))
    d['Guard']['allOf']=[{'if':{'properties':{'time_required':{'const':True}}},
        'then':{'properties':{'time_evidence_ref':ref('Ref'),'time_policy_ref':ref('Ref')}},
        'else':{'properties':{'time_evidence_ref':{'type':'null'},'time_policy_ref':{'type':'null'}}}}]
    d['Packet']=obj(packet_id=ref('Id'),execution_ref=ref('Ref'),cancellation_id=ref('Id'),
        parent_command_id=ref('Id'),primitive_id=ref('Id'),exit=ref('Exit'),
        protocol_session=nullable(ref('Id')),wire_packet_id=nullable(ref('Counter')),
        tracking_ids=arr(ref('Id')),immutable_bytes_ref=ref('ContentRef'),
        byte_length={'type':'integer','minimum':1,'maximum':65536},sha256=ref('Digest'),
        transport_profile_ref=ref('Ref'),packet_digest=ref('Digest'))
    d['Transmission']=obj(permit_id=ref('Id'),transmission_id=ref('Id'),execution_ref=ref('Ref'),
        cancellation_id=ref('Id'),parent_command_id=ref('Id'),primitive_id=ref('Id'),
        packet_ref=ref('PacketRef'),exit=ref('Exit'),requester=ref('Requester'),guard_ref=ref('Ref'),
        ordinal=ref('Counter'),initial_permit_id=ref('Id'),issued_revision=ref('PositiveCounter'),
        kind=enum('initial','protocol_resend'),trigger_observation_ref=nullable(ref('Ref')),
        budget_receipt_ref=ref('Ref'),send_window=ref('SendWindow'))
    d['Transmission']['allOf']=[{'if':{'properties':{'kind':{'const':'initial'}}},
        'then':{'properties':{'ordinal':{'const':'0'},'trigger_observation_ref':{'type':'null'}}},
        'else':{'properties':{'ordinal':ref('PositiveCounter'),'trigger_observation_ref':ref('Ref')}}}]
    d['CancelCoverage']=copy.deepcopy(old['$defs']['Coverage'])
    d['CancelCoverage']['properties']['intent']=ref('Transmission')
    d['CutTarget']=obj(exit=ref('Exit'),ordinary_attempt_ids=arr(ref('Id')),
        ordinary_transmissions=arr(ref('TransmissionRef')),cancel_prepare_ids=arr(ref('Id')),
        cancel_transmissions=arr(ref('Transmission')),target_digest=ref('Digest'))
    d['Cut']=obj(cut_id=ref('Id'),binding=ref('CancellationBinding'),stage=enum('ordinary','all'),
        previous_cut_ref=nullable(ref('Ref')),issued_revision=ref('Counter'),deny_revision=ref('PositiveCounter'),
        targets=arr(ref('CutTarget')),cut_digest=ref('Digest'))
    d['Cut']['allOf']=[{'if':{'properties':{'stage':{'const':'ordinary'}}},
        'then':{'properties':{'previous_cut_ref':{'type':'null'},'targets':{'items':{'properties':{
            'cancel_prepare_ids':{'maxItems':0},'cancel_transmissions':{'maxItems':0}}}}}},
        'else':{'properties':{'previous_cut_ref':ref('Ref')}}}]
    d['TargetClosure']=obj(target_exit_id=ref('Id'),target_digest=ref('Digest'),
        kind=enum('barrier_ack','supervisor_retired'),source_ref=ref('Ref'),validation_ref=ref('Ref'))
    d['ClosureEvidence']=obj(closure_id=ref('Id'),revision=ref('PositiveCounter'),binding=ref('CancellationBinding'),
        stage=enum('ordinary','all'),cut_ref=ref('Ref'),targets=arr(ref('TargetClosure')),
        provider_receipt_ref=ref('Ref'),closure_digest=ref('Digest'))
    d['DecisionEvidence']=obj(decision_id=ref('Id'),revision=ref('PositiveCounter'),
        binding=ref('CancellationBinding'),command_state_ref=ref('Ref'),all_closure_ref=nullable(ref('Ref')),
        execution_ref=nullable(ref('Ref')),outcome=enum('confirmed','unsupported','failed','indeterminate','too_late'),
        evidence_refs=arr(ref('Ref')),provider_receipt_ref=ref('Ref'),decision_digest=ref('Digest'))
    d['DecisionEvidence']['allOf']=[{'if':{'properties':{'outcome':{'const':'confirmed'}}},
        'then':{'properties':{'all_closure_ref':ref('Ref')}}}]
    d['CANCEL_FENCEBody']=obj(operation_id=ref('Id'),barrier_id=ref('Id'),binding=ref('CancellationBinding'),
        stage=enum('ordinary','all'),cut_ref=ref('Ref'),deny_revision=ref('PositiveCounter'),
        target=ref('CutTarget'),attempt_binding=ref('BarrierAttemptBinding'))
    d['CANCEL_FENCE_ACKBody']=obj(operation_id=ref('Id'),barrier_id=ref('Id'),binding=ref('CancellationBinding'),
        stage=enum('ordinary','all'),cut_ref=ref('Ref'),deny_revision=ref('PositiveCounter'),
        target_digest=ref('Digest'),attempt_binding=ref('BarrierAttemptBinding'),
        ordinary_attempt_ids=arr(ref('Id')),cancel_prepare_ids=arr(ref('Id')),
        ordinary_coverage=arr(ref('TransmissionCoverage')),cancel_coverage=arr(ref('CancelCoverage')),
        effective_tick_ns=ref('Counter'),gate_io_seq=ref('PositiveCounter'),ack_digest=ref('Digest'))
    d['CANCEL_GUARDBody']=obj(plan=ref('ExecutionPlan'),guard=ref('Guard'))
    d['CANCEL_GUARD_ACKBody']=obj(execution_ref=ref('Ref'),guard_ref=ref('Ref'),status=enum('installed','rejected'))
    d['ENCODE_CANCEL_PACKETBody']=obj(prepare_id=ref('Id'),execution_ref=ref('Ref'),
        primitive_id=ref('Id'),guard_ref=ref('Ref'),expires_tick_ns=ref('Counter'))
    d['PREPARE_CANCEL_PACKETBody']=obj(prepare_id=ref('Id'),packet=ref('Packet'),
        bytes_hex={'type':'string','pattern':'^(?:[0-9a-f]{2})+$(?![\\s\\S])','maxLength':131072})
    for n in ('CANCEL_ENCODING_FAILED','CANCEL_PREPARE_REJECTED'):
        d[n+'Body']=obj(prepare_id=ref('Id'),execution_ref=ref('Ref'),
            reason=enum('binding','expired','capacity','protected','unavailable','profile'))
    d['DISPATCH_CANCELBody']=obj(prepare_id=ref('Id'),packet=ref('Packet'),permit=ref('Transmission'),
        resend_request_id=nullable(ref('Id')))
    d['DISPATCH_CANCELBody']['allOf']=[{'if':{'properties':{'permit':{'properties':{'kind':{'const':'initial'}}}}},
        'then':{'properties':{'resend_request_id':{'type':'null'}}},
        'else':{'properties':{'resend_request_id':ref('Id')}}}]
    d['CANCEL_RESEND_REQUESTBody']=obj(request_id=ref('Id'),execution_ref=ref('Ref'),packet_ref=ref('PacketRef'),
        cause=enum('timeout','peer_request'),observation_ref=ref('Ref'))
    d['CANCEL_RESEND_REJECTEDBody']=obj(request_id=ref('Id'),execution_ref=ref('Ref'),
        reason=enum('protected','expired','budget','binding','unavailable','already_pending'))
    d['CANCEL_SEND_REPORTBody']=obj(report_id=ref('Id'),transmission=ref('Transmission'),
        disposition=enum('not_sent','in_flight','unknown'),gate_io_seq=ref('PositiveCounter'),
        transport_entered_tick_ns=nullable(ref('Counter')),observation_ref=ref('Ref'))
    d['CANCEL_SEND_REPORTBody']['allOf']=[{'if':{'properties':{'disposition':{'const':'in_flight'}}},
        'then':{'properties':{'transport_entered_tick_ns':ref('Counter')}},
        'else':{'properties':{'transport_entered_tick_ns':{'type':'null'}}}}]
    d['CANCEL_REPORT_STOREDBody']=obj(report_id=ref('Id'),report_digest=ref('Digest'),record_ref=ref('Ref'))
    d['CANCEL_EVIDENCE_CANDIDATEBody']=obj(report_id=ref('Id'),execution_ref=ref('Ref'),primitive_id=ref('Id'),
        packet_refs=arr(ref('PacketRef')),evidence_schema_ref=ref('Ref'),payload={'type':'object'})
    d['QUERY_CANCEL_EXECUTIONBody']=obj(execution_ref=ref('Ref'))
    d['CANCEL_EXECUTION_STATUSBody']=obj(execution_ref=ref('Ref'),status=enum('known','cache_missing'),
        stored_report_refs=arr(ref('Ref')))
    d['CANCEL_EXECUTION_STATUSBody']['allOf']=[{'if':{'properties':{'status':{'const':'cache_missing'}}},
        'then':{'properties':{'stored_report_refs':{'maxItems':0}}}}]
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':CID,
        'title':'command-cancellation/0.1.0-draft.1','x-approved':False,'x-runtime-approved':False,
        'not':{},'$defs':d}


def build():
    schema=models();ipc=json.loads(OLD.read_bytes())
    ipc.update({'$id':IID,'title':VERSION,'x-approved':False,'x-runtime-approved':False})
    d=ipc['$defs']
    add(d['OPEN_GATEBody'],command_deny_snapshot=ext(CID,'DenySnapshot'))
    add(d['OPEN_GATE_ACKBody'],command_deny_snapshot_revision=ext(CID,'Counter'),
        command_deny_snapshot_digest=ext(CID,'Digest'))
    for n in FENCES:
        add(d[n+'Body'],cancel_transmissions=arr(ext(CID,'Transmission')),cancel_ledger_digest=ext(CID,'Digest'))
        add(d[n+'_ACKBody'],cancel_coverage=arr(ext(CID,'CancelCoverage')),cancel_ledger_digest=ext(CID,'Digest'))
    for n in NEW_FRAMES:
        frame=copy.deepcopy(d['FENCE_ACK' if n in RESPONSES else 'FENCE'])
        frame['properties']['type']={'const':n};frame['properties']['body']=ext(CID,n+'Body')
        d[n]=frame;ipc['oneOf'].append({'$ref':'#/$defs/'+n})
    for branch in ipc['oneOf']:
        d[branch['$ref'].split('/')[-1]]['properties']['ipc_version']={'const':VERSION}
    d['HELLOBody']['properties']['supported_ipc_versions']['items']={'const':VERSION}
    d['HELLO_ACKBody']['properties']['selected_ipc_version']={'const':VERSION}
    for n,f in [('HELLOBody','supported_features'),('HELLO_ACKBody','selected_features')]:
        d[n]['properties'][f]['allOf'] += [{'contains':{'const':x}} for x in FEATURES]
    return {'cancellation.schema.json':schema,'ipc.schema.json':ipc}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for n,s in build().items():
        if a.check:assert (HERE/n).read_bytes()==encoded(s),n
        else:(HERE/n).write_bytes(encoded(s))
