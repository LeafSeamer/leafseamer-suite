"""占用归属及逐传输主体投影的候选格式；不生成服务或迁移。"""
import argparse,json
from pathlib import Path
import build_open_lifecycle as L
HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/c08-controller/hold-ownership.schema.json'
def build():
    obj=L.obj;ref=L.ref;old=L.old;nullable=L.nullable
    d={'Principal':obj(kind={'enum':['human','service']},issuer_id=old('Id'),issuer_epoch=old('Id'),principal_id=old('Id'))}
    identity=obj(kind={'enum':['ordinary','cancel']},command_ref=old('Ref'),attempt_ref=nullable(old('Ref')),
      cancellation_ref=nullable(old('Ref')),execution_ref=nullable(old('Ref')),requester=ref('Principal'),
      origin={'enum':['manual','automation']},source_ref=old('Ref'))
    identity['allOf']=[{'if':{'properties':{'kind':{'const':'ordinary'}}},'then':{'properties':{
      'attempt_ref':old('Ref'),'cancellation_ref':{'type':'null'},'execution_ref':{'type':'null'}}},'else':{'properties':{
      'attempt_ref':{'type':'null'},'cancellation_ref':old('Ref'),'execution_ref':old('Ref')}}},
      {'if':{'properties':{'origin':{'const':'automation'}}},'then':{'properties':{'requester':{'properties':{'kind':{'const':'service'}}}}},
       'else':{'properties':{'requester':{'properties':{'kind':{'const':'human'}}}}}}]
    d['ExecutionIdentity']=identity
    d['Ownership']=obj(format_version={'const':'hold-ownership/0.1.0-draft.1'},ownership_id=old('Id'),revision={'const':'1'},
      scope=old('Scope'),device_id=old('Id'),hold_ref=old('Ref'),identity=ref('ExecutionIdentity'),
      control_authority_ref=old('Ref'),control_epoch=old('Id'),effective_version=old('Counter'),
      clock_domain_id={'type':'string','pattern':r'^clock_[0-9a-f]{64}$(?![\s\S])'},descriptor_digest=old('Digest'),
      acquired_tick_ns=old('Counter'),source_receipt_ref=old('Ref'),ownership_digest=old('Digest'))
    d['PermitAuthority']=obj(format_version={'const':'permit-authority/0.1.0-draft.1'},permit_id=old('Id'),
      issued_revision=old('Counter'),identity=ref('ExecutionIdentity'),binding=old('Binding'),
      hold_ref=old('Ref'),ownership_ref=old('Ref'),control_authority_ref=old('Ref'),control_epoch=old('Id'),
      effective_version=old('Counter'),authorization_ref=old('Ref'),guard_ref=old('Ref'),
      packet_ref=old('Ref'),ordinal=old('Counter'),selected_tick_ns=old('Counter'),expires_tick_ns=old('Counter'),
      authority_digest=old('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'title':'hold-ownership/0.1.0-draft.1',
      'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}
def encoded():return (json.dumps(build(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'hold-ownership.schema.json'
    if a.check:assert path.read_bytes()==encoded(),'生成漂移'
    else:path.write_bytes(encoded())
