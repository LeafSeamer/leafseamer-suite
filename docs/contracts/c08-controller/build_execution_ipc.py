"""从固定IPC0.5生成逐传输与屏障尝试候选；不修改旧协议，不实现设备服务。"""
import argparse
import copy
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
OLD=BASE/'c05-protection/ipc-v05.schema.json'
PROTOCOL=BASE/'c05-protection/protocol.schema.json'
IID='https://leafseamer.invalid/design/c08-controller/execution-ipc.schema.json'
VERSION='ipc/0.6.0-transmission-draft.1'
FEATURES=('per_transmission_permit','complete_transmission_fence','barrier_attempt_history')
FENCES=('FENCE','AUTH_FENCE','TIME_FENCE','RUN_FENCE')
NEW_FRAMES=('ENCODE_PACKET','PACKET_ENCODING_FAILED','PREPARE_PACKET','PREPARE_PACKET_REJECTED','RESEND_REQUEST','RESEND_DISPATCH',
            'RESEND_REJECTED','BARRIER_UNAVAILABLE','BARRIER_STORED')


def obj(**p): return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def ref(n): return {'$ref':'#/$defs/'+n}
def nullable(s): return {'anyOf':[s,{'type':'null'}]}
def arr(s): return dict(type='array',items=s,maxItems=256)
def add(s,**fields):
    assert not set(fields)&set(s['properties'])
    s['properties'].update(fields);s['required']+=list(fields)
def encoded(v): return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()


def build():
    ipc=json.loads(OLD.read_bytes());p=json.loads(PROTOCOL.read_bytes())
    ipc.update({'$id':IID,'title':VERSION,'x-approved':False,'x-runtime-approved':False})
    d=ipc['$defs']
    public='https://leafseamer.invalid/contracts/draft4/first-loop.schema.json'
    external=lambda n:{'$ref':public+'#/$defs/'+n}
    d['Counter']={'type':'string','pattern':'^(0|[1-9][0-9]{0,19})$(?![\\s\\S])'}
    d['PositiveCounter']={'type':'string','pattern':'^[1-9][0-9]{0,19}$(?![\\s\\S])'}
    d['Id']=copy.deepcopy(p['$defs']['Id'])
    d['Digest']=copy.deepcopy(p['$defs']['Digest'])
    d['ContentRef']=obj(object_id=ref('Id'),digest=ref('Digest'))
    d['PacketRef']=obj(packet_id=ref('Id'),packet_digest=ref('Digest'))
    d['TransportPacket']=obj(packet_id=ref('Id'),packet_digest=ref('Digest'),
        command_id=ref('Id'),attempt_id=ref('Id'),primitive_id=ref('Id'),
        writer_exit_id=ref('Id'),device_session_id=ref('Id'),socket_instance_id=ref('Id'),
        protocol_session=nullable(ref('Id')),wire_packet_id=nullable(ref('Counter')),
        tracking_ids=arr(ref('Id')),immutable_bytes_ref=ref('ContentRef'),
        byte_length={'type':'integer','minimum':1,'maximum':65536},sha256=ref('Digest'),
        transport_profile_ref=ref('ContentRef'),primitive_plan_ref=ref('ContentRef'))
    d['BarrierAttemptBinding']=obj(cut_id=ref('Id'),cut_digest=ref('Digest'),target_exit_id=ref('Id'),
        attempt_ordinal=ref('PositiveCounter'),previous_barrier_id=nullable(ref('Id')))
    d['BarrierAttemptBinding']['allOf']=[{
        'if':{'properties':{'attempt_ordinal':{'const':'1'}}},
        'then':{'properties':{'previous_barrier_id':{'type':'null'}}},
        'else':{'properties':{'previous_barrier_id':ref('Id')}}}]
    d['TransmissionRef']=obj(transmission_id=ref('Id'),packet_ref=ref('PacketRef'),
        primitive_id=ref('Id'),intent=ref('IntentRef'),ordinal=ref('Counter'),
        kind={'enum':['initial','protocol_resend']},cause={'enum':['dispatch','timeout','peer_request']},
        trigger_observation_ref=nullable(ref('ContentRef')),parent_dispatch_intent_id=ref('Id'),
        initial_permit_id=ref('Id'),issued_revision=ref('PositiveCounter'),send_window=ref('SendWindow'))
    d['TransmissionRef']['allOf']=[{
        'if':{'properties':{'kind':{'const':'initial'}}},
        'then':{'properties':{'ordinal':{'const':'0'},'cause':{'const':'dispatch'},
                              'trigger_observation_ref':{'type':'null'}}},
        'else':{'properties':{'ordinal':ref('PositiveCounter'),'cause':{'enum':['timeout','peer_request']},
                              'trigger_observation_ref':ref('ContentRef')}}}]
    d['TransmissionCoverage']=copy.deepcopy(d['Coverage'])
    d['TransmissionCoverage']['properties']['intent']=ref('TransmissionRef')
    d['TransmissionPermit']=copy.deepcopy(p['$defs']['DispatchPermit'])
    add(d['TransmissionPermit'],transmission=ref('TransmissionRef'),budget_revision=ref('PositiveCounter'))
    add(d['DISPATCHBody'],prepare_id=ref('Id'),packet=ref('TransportPacket'),resend_request_id={'type':'null'})
    d['DISPATCHBody']['properties']['permit']=ref('TransmissionPermit')
    d['DISPATCHBody'].setdefault('allOf',[]).append({
        'properties':{'permit':{'properties':{'transmission':{'properties':{'kind':{'const':'initial'}}}}}}})
    add(d['SEND_REPORTBody'],transmission_id=ref('Id'),packet_ref=ref('PacketRef'),ordinal=ref('Counter'),
        gate_io_seq=ref('PositiveCounter'),transport_entered_tick_ns=nullable(ref('Counter')),
        socket_callback_observation_ref=nullable(ref('ContentRef')))
    d['SEND_REPORTBody']['allOf'].append({
        'if':{'properties':{'disposition':{'const':'in_flight'}}},
        'then':{'properties':{'transport_entered_tick_ns':ref('Counter')}},
        'else':{'properties':{'transport_entered_tick_ns':{'type':'null'}}}})
    for name in FENCES:
        body=d[name+'Body']
        add(body,attempt_binding=ref('BarrierAttemptBinding'),transmission_ledger_digest=ref('Digest'),
            open_transmission_intents=arr(ref('TransmissionRef')))
        ack=d[name+'_ACKBody']
        add(ack,attempt_binding=ref('BarrierAttemptBinding'),transmission_ledger_digest=ref('Digest'),
            transmission_coverage=arr(ref('TransmissionCoverage')),effective_tick_ns=ref('Counter'))
    d['RUN_FENCEBody']['allOf'].append({'properties':{'open_transmission_intents':{'items':{
        'properties':{'intent':{'properties':{'origin':{'const':'automation'}}}}}}}})
    d['RUN_FENCE_ACKBody']['allOf'].append({'properties':{'transmission_coverage':{'items':{
        'properties':{'intent':{'properties':{'intent':{'properties':{'origin':{'const':'automation'}}}}}}}}}})
    add(d['QUERY_BARRIERBody'],attempt_binding=ref('BarrierAttemptBinding'))
    d['ENCODE_PACKETBody']=obj(prepare_id=ref('Id'),command_id=ref('Id'),attempt_id=ref('Id'),
        primitive_id=ref('Id'),device_session_id=ref('Id'),
        request={'$ref':p['$id']+'#/$defs/CommandRequest'},
        primitive_plan_ref=ref('ContentRef'),transport_profile_ref=ref('ContentRef'),
        guard_id=ref('Id'),guard_digest=ref('Digest'),expires_tick_ns=ref('Counter'))
    d['PACKET_ENCODING_FAILEDBody']=obj(prepare_id=ref('Id'),
        reason={'enum':['binding','profile','capacity','expired','session_changed','unavailable']})
    d['PREPARE_PACKETBody']=obj(prepare_id=ref('Id'),packet=ref('TransportPacket'),
        bytes_hex={'type':'string','minLength':2,'maxLength':131072,'pattern':'^(?:[0-9a-f]{2})+$(?![\\s\\S])'})
    d['PREPARE_PACKET_REJECTEDBody']=obj(prepare_id=ref('Id'),packet_ref=ref('PacketRef'),
        reason={'enum':['binding','guard','profile','capacity','expired','protected','unavailable']})
    d['RESEND_REQUESTBody']=obj(request_id=ref('Id'),packet_ref=ref('PacketRef'),
        cause={'enum':['timeout','peer_request']},observation_ref=ref('ContentRef'))
    d['RESEND_DISPATCHBody']=copy.deepcopy(d['DISPATCHBody'])
    d['RESEND_DISPATCHBody']['properties']['resend_request_id']=ref('Id')
    d['RESEND_DISPATCHBody']['allOf']=[{
        'properties':{'permit':{'properties':{'transmission':{'properties':{'kind':{'const':'protocol_resend'}}}}}}}]
    d['RESEND_REJECTEDBody']=obj(request_id=ref('Id'),packet_ref=ref('PacketRef'),
        reason={'enum':['binding','acknowledged','pending_permit','budget','expired','protected','unavailable']})
    d['BARRIER_UNAVAILABLEBody']=obj(operation_id=ref('Id'),barrier_id=ref('Id'),
        attempt_binding=ref('BarrierAttemptBinding'),reason={'enum':['cache_miss','unknown_barrier']})
    d['BARRIER_STOREDBody']=obj(operation_id=ref('Id'),barrier_id=ref('Id'),
        attempt_binding=ref('BarrierAttemptBinding'),ack_digest=ref('Digest'),record_revision=ref('PositiveCounter'))
    d['PacketAckObservation']=obj(observation_id=ref('Id'),writer_exit_id=ref('Id'),
        device_session_id=ref('Id'),socket_instance_id=ref('Id'),protocol_session=ref('Id'),
        receive_io_seq=ref('PositiveCounter'),raw_ack_ref=ref('ContentRef'),wire_ack_id=ref('Counter'),
        covered_packet_refs=arr(ref('PacketRef')))
    d['EVIDENCE_CANDIDATEBody']['properties']['evidence_kind']['enum'].append('packet_ack')
    d['EVIDENCE_CANDIDATEBody']['allOf'].append({
        'if':{'properties':{'evidence_kind':{'const':'packet_ack'}}},
        'then':{'properties':{'payload':ref('PacketAckObservation')}}})
    # 信封结构沿用；新增响应reply_to必须非空，非响应为null。
    for name in NEW_FRAMES:
        response=name in ('PREPARE_PACKET','PACKET_ENCODING_FAILED','PREPARE_PACKET_REJECTED',
                          'RESEND_DISPATCH','RESEND_REJECTED','BARRIER_UNAVAILABLE')
        frame=copy.deepcopy(d['FENCE_ACK'] if response else d['FENCE'])
        frame['properties']['type']={'const':name}
        frame['properties']['body']=ref(name+'Body')
        d[name]=frame;ipc['oneOf'].append(ref(name))
    for branch in ipc['oneOf']:
        d[branch['$ref'].split('/')[-1]]['properties']['ipc_version']={'const':VERSION}
    d['HELLOBody']['properties']['supported_ipc_versions']['items']={'const':VERSION}
    d['HELLO_ACKBody']['properties']['selected_ipc_version']={'const':VERSION}
    for name,field in [('HELLOBody','supported_features'),('HELLO_ACKBody','selected_features')]:
        d[name]['properties'][field]['allOf'] += [{'contains':{'const':x}} for x in FEATURES]
    return ipc


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    path=HERE/'execution-ipc.schema.json';data=encoded(build())
    if args.check: assert path.read_bytes()==data
    else: path.write_bytes(data)
