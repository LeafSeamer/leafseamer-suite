"""生成仅编码授权及完整IPC候选；不安装依赖、不调用设备或修改旧契约。"""
import argparse, copy, json
from pathlib import Path
import build_scoped_gate as S
HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/c08-controller/encoding-authority.schema.json'
IID='https://leafseamer.invalid/design/c08-controller/encoding-authority-ipc.schema.json'
VERSION='ipc/0.11.0-encoding-authority-draft.1'
FEATURE='encoding_authority_before_issue'
BASE=HERE/'gate-renewal-ipc.schema.json'
obj=S.obj;ref=S.ref;nullable=S.null

def schema():
    prior=S.schema()['$defs']
    d={n:copy.deepcopy(prior[n]) for n in ('Id','Counter','Digest','Ref','Scope','Binding','Principal')}
    d['Target']=obj(kind={'enum':['ordinary','cancel']},command_ref=ref('Ref'),
      proposed_attempt_id=nullable(ref('Id')),cancellation_ref=nullable(ref('Ref')),execution_ref=nullable(ref('Ref')))
    d['Target']['allOf']=[{'if':{'properties':{'kind':{'const':'ordinary'}}},'then':{'properties':{
      'proposed_attempt_id':ref('Id'),'cancellation_ref':{'type':'null'},'execution_ref':{'type':'null'}}},'else':{'properties':{
      'proposed_attempt_id':{'type':'null'},'cancellation_ref':ref('Ref'),'execution_ref':ref('Ref')}}}]
    d['EncodingAuthorization']=obj(format_version={'const':'encoding-authorization/0.1.0-draft.1'},
      authorization_id=ref('Id'),revision={'const':'1'},binding=ref('Binding'),target=ref('Target'),requester=ref('Principal'),
      admission_source_ref=ref('Ref'),authorization_snapshot_ref=ref('Ref'),capability_ref=ref('Ref'),
      primitive_id=ref('Id'),primitive_plan_ref=ref('Ref'),transport_profile_ref=ref('Ref'),
      content_digest=ref('Digest'),encoding_reservation_ref=ref('Ref'),max_bytes={'type':'integer','minimum':1,'maximum':65536},
      created_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter'),authorization_digest=ref('Digest'))
    d['EncodingEvidence']=obj(evidence_id=ref('Id'),revision={'const':'1'},authorization_ref=ref('Ref'),
      binding=ref('Binding'),prepare_id=ref('Id'),request_message_id=ref('Id'),response_message_id=ref('Id'),
      request_digest=ref('Digest'),response_digest=ref('Digest'),
      packet_ref=obj(packet_id=ref('Id'),packet_digest=ref('Digest')),bytes_digest=ref('Digest'),
      byte_length={'type':'integer','minimum':1,'maximum':65536},received_tick_ns=ref('Counter'),evidence_digest=ref('Digest'))
    # 仅为顺序检查的持久提交投影；不是新的完整AdmissionSeal或线上消息。
    d['FinalizationLink']=obj(permit_id=ref('Id'),issued_revision=ref('Counter'),binding=ref('Binding'),
      encoding_evidence_ref=ref('Ref'),admission_seal_ref=ref('Ref'),guard_ref=ref('Ref'),
      gate_access_ref=ref('Ref'),ownership_ref=ref('Ref'),budget_charge_ref=ref('Ref'),
      control_authority_ref=ref('Ref'),authorization_ref=ref('Ref'),resource_safety_ref=ref('Ref'),gate_safety_ref=ref('Ref'),
      packet_ref=obj(packet_id=ref('Id'),packet_digest=ref('Digest')),
      committed_tick_ns=ref('Counter'),send_not_before_tick_ns=ref('Counter'),send_before_tick_ns=ref('Counter'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,
      'x-runtime-approved':False,'not':{},'$defs':d}

def ipc(local):
    s=json.loads(BASE.read_bytes());s.update({'$id':IID,'title':VERSION})
    d=s['$defs'];r=lambda n:ref('EA__'+n)
    for n,v in local['$defs'].items():
        if n!='FinalizationLink':d['EA__'+n]=S.rename(v,lambda u:'#/$defs/EA__'+u.split('/')[-1])
    for n,removed in [('S9__ENCODE_PACKETBody',('guard_id','guard_digest')),('S8__ENCODE_CANCEL_PACKETBody',('guard_ref',))]:
        for k in removed:del d[n]['properties'][k];d[n]['required'].remove(k)
        S.add(d,n,encoding_authorization=r('EncodingAuthorization'))
    for n in ('S9__PREPARE_PACKETBody','S9__PACKET_ENCODING_FAILEDBody','S9__PREPARE_PACKET_REJECTEDBody',
              'S8__PREPARE_CANCEL_PACKETBody','S8__CANCEL_ENCODING_FAILEDBody'):
        S.add(d,n,encoding_authorization_ref=r('Ref'))
    for branch in s['oneOf']:d[branch['$ref'].split('/')[-1]]['properties']['ipc_version']={'const':VERSION}
    d['S9__HELLOBody']['properties']['supported_ipc_versions']['items']={'const':VERSION}
    d['S9__HELLO_ACKBody']['properties']['selected_ipc_version']={'const':VERSION}
    for n,k in [('S9__HELLOBody','supported_features'),('S9__HELLO_ACKBody','selected_features')]:
        d[n]['properties'][k]['allOf'].append({'contains':{'const':FEATURE}})
    return s

def build():
    s=schema();return {'encoding-authority.schema.json':s,'encoding-authority-ipc.schema.json':ipc(s)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for n,v in build().items():
        raw=S.encoded(v);path=HERE/n
        if a.check:assert path.read_bytes()==raw,'生成漂移:'+n
        else:path.write_bytes(raw)
