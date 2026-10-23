"""限定取消闸的唯一候选定义和完整IPC投影；不改旧协议或发送实现。"""
import argparse, copy, json
from pathlib import Path
import build_open_plan as P
import build_hold_ownership as H
HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/c08-controller/scoped-gate.schema.json'
IID='https://leafseamer.invalid/design/c08-controller/scoped-gate-ipc.schema.json'
VERSION='ipc/0.9.0-scoped-gate-draft.1'
FEATURES=['scoped_gate_access','immutable_hold_ownership']
obj=P.obj;ref=P.ref
def null(v):return {'anyOf':[v,{'type':'null'}]}
def rename(value, convert):
    if isinstance(value,list):return [rename(x,convert) for x in value]
    if not isinstance(value,dict):return value
    return {k:convert(v) if k=='$ref' else copy.deepcopy(v) if k in ('const','enum','default','examples') else rename(v,convert) for k,v in value.items()}
def schema():
    d={n:copy.deepcopy(P.build()['$defs'][n]) for n in ('Id','Counter','Digest','Ref','Scope','Binding')}
    for n in ('Principal','ExecutionIdentity'):
        d[n]=rename(H.build()['$defs'][n],lambda v:'#/$defs/'+v.split('/')[-1])
    d['ProtectionScope']=obj(identity=ref('ExecutionIdentity'),policy_ref=ref('Ref'),ordinary_closure_ref=ref('Ref'),
        hold_ref=ref('Ref'),ownership_ref=ref('Ref'))
    d['ProtectionScope']['properties']['identity']['allOf']=[{'properties':{'kind':{'const':'cancel'}}}]
    d['Risk']=obj(hold_ref=ref('Ref'),ownership_ref=ref('Ref'),command_ref=ref('Ref'),execution_ref=null(ref('Ref')),
        classification={'enum':['active','unknown','unresolved','stale']})
    common=dict(binding=ref('Binding'),control_authority_ref=ref('Ref'),control_epoch=ref('Id'),effective_version=ref('Counter'),
        authorization_ref=ref('Ref'),resource_safety_ref=ref('Ref'),gate_safety_ref=ref('Ref'))
    d['ProtectionAssessment']=obj(format_version={'const':'protection-assessment/0.1.0-draft.1'},assessment_id=ref('Id'),revision={'const':'1'},
        **copy.deepcopy(common),protection=ref('ProtectionScope'),resource_ref=ref('Ref'),risks={'type':'array','items':ref('Risk'),'minItems':1,'maxItems':256},
        sampled_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter'),provider_receipt_ref=ref('Ref'),assessment_digest=ref('Digest'))
    d['GateAccess']=obj(format_version={'const':'gate-access/0.1.0-draft.1'},access_id=ref('Id'),revision={'const':'1'},
        purpose={'enum':['ordinary','cancel_only']},**copy.deepcopy(common),protection=null(ref('ProtectionScope')),
        initial_assessment_ref=null(ref('Ref')),selected_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter'),access_digest=ref('Digest'))
    d['GateAccess']['allOf']=[{'if':{'properties':{'purpose':{'const':'ordinary'}}},'then':{'properties':{
        'protection':{'type':'null'},'initial_assessment_ref':{'type':'null'}}},'else':{'properties':{
        'protection':ref('ProtectionScope'),'initial_assessment_ref':ref('Ref')}}}]
    # 子投影只检查新增范围；不重复定义完整传输/预算/设备参数。
    d['GateUse']=obj(permit_id=ref('Id'),kind={'enum':['ordinary','cancel']},gate_access_ref=ref('Ref'),
        identity=ref('ExecutionIdentity'),ownership_ref=ref('Ref'),guard_ref=ref('Ref'),protection_assessment_ref=null(ref('Ref')),
        selected_tick_ns=ref('Counter'),expires_tick_ns=ref('Counter'))
    d['GateUse']['allOf']=[{'if':{'properties':{'kind':{'const':'ordinary'}}},'then':{'properties':{
        'identity':{'properties':{'kind':{'const':'ordinary'}}},'protection_assessment_ref':{'type':'null'}}},'else':{'properties':{
        'identity':{'properties':{'kind':{'const':'cancel'}}},'protection_assessment_ref':ref('Ref')}}}]
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}
def add(d,n,**fields):
    node=d[n];assert not set(fields)&set(node['properties']),n
    node['properties'].update(copy.deepcopy(fields));node['required']+=list(fields)
def ipc(local):
    s=json.loads(P.IPC.read_bytes());s['$id']=IID;s['title']=VERSION;s['x-approved']=False;s['x-runtime-approved']=False
    d=s['$defs'];r=lambda n:ref('SG__'+n)
    for n,v in local['$defs'].items():d['SG__'+n]=rename(v,lambda u:'#/$defs/SG__'+u.split('/')[-1])
    for branch in s['oneOf']:
        d[branch['$ref'].split('/')[-1]]['properties']['ipc_version']={'const':VERSION}
    d['S9__HELLOBody']['properties']['supported_ipc_versions']['items']={'const':VERSION}
    d['S9__HELLO_ACKBody']['properties']['selected_ipc_version']={'const':VERSION}
    for n,k in [('S9__HELLOBody','supported_features'),('S9__HELLO_ACKBody','selected_features')]:
        d[n]['properties'][k]['allOf'] += [{'contains':{'const':f}} for f in FEATURES]
    add(d,'S9__OPEN_GATEBody',gate_access=r('GateAccess'),protection_assessment=null(r('ProtectionAssessment')))
    d['S9__OPEN_GATEBody'].setdefault('allOf',[]).append({'if':{'properties':{'gate_access':{'properties':{'purpose':{'const':'ordinary'}}}}},
        'then':{'properties':{'protection_assessment':{'type':'null'}}},'else':{'properties':{'protection_assessment':r('ProtectionAssessment')}}})
    add(d,'S9__OPEN_GATE_ACKBody',gate_access_ref=r('Ref'))
    for n in ('S2__ExecutionGuard','S9__TransmissionPermit','S9__GUARD_ACKBody'):
        add(d,n,gate_access_ref=r('Ref'),ownership_ref=r('Ref'))
    for n in ('S8__Guard','S8__Transmission','S8__CANCEL_GUARD_ACKBody'):
        add(d,n,gate_access_ref=r('Ref'),ownership_ref=r('Ref'),protection_assessment_ref=r('Ref'))
    add(d,'S8__CANCEL_GUARDBody',protection_assessment=r('ProtectionAssessment'))
    return s
def build():
    s=schema();return {'scoped-gate.schema.json':s,'scoped-gate-ipc.schema.json':ipc(s)}
def encoded(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,value in build().items():
        path=HERE/name
        if a.check:assert path.read_bytes()==encoded(value),'生成漂移:'+name
        else:path.write_bytes(encoded(value))
