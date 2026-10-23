"""控制权与转交候选唯一局部源；生成离线格式，不生成产品服务。"""
import argparse,copy,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
VERSION='control-authority/0.1.0-draft.1'
SID='https://leafseamer.invalid/design/c08-controller/control-authority.schema.json'
def ref(n):return {'$ref':'#/$defs/'+n}
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def nullable(v):return {'anyOf':[v,{'type':'null'}]}
def when(k,v,p):return {'if':{'properties':{k:{'const':v}},'required':[k]},'then':{'properties':p}}
ROUTES=[
 ('get','/devices/{device_id}/control','getControl',None,'ControlRecord'),
 ('get','/control-operations/{operation_id}','getControlOperation',None,'ControlOperation'),
 ('post','/devices/{device_id}/control/acquire','acquireControl','AcquireRequest','RequestReceipt'),
 ('post','/devices/{device_id}/control/release','releaseControl','ReleaseRequest','RequestReceipt'),
 ('post','/devices/{device_id}/control/transfers','offerTransfer','OfferRequest','RequestReceipt'),
 ('post','/devices/{device_id}/control/transfers/{transfer_id}/accept','acceptTransfer','AcceptRequest','RequestReceipt'),
 ('get','/devices/{device_id}/control/transfers/{transfer_id}','getTransfer',None,'TransferOffer'),
 ('post','/devices/{device_id}/control/transfers/{transfer_id}/cancel','cancelTransfer','CancelRequest','RequestReceipt'),
 ('post','/control-requests/lookup','lookupControlRequest','LookupRequest','LookupResult')]
PERMISSIONS=dict(getControl='control.read',getControlOperation='control.read',acquireControl='control.acquire',
 releaseControl='control.release',offerTransfer='control.transfer',acceptTransfer='control.accept',
 getTransfer='control.read',cancelTransfer='control.transfer',lookupControlRequest='control.read')
def schema():
 d={
  'Id':dict(type='string',minLength=1,maxLength=128,pattern=r'^[A-Za-z0-9_.:-]+$(?![\s\S])'),
  'U20':dict(type='string',pattern=r'^(0|[1-9][0-9]{0,19})$(?![\s\S])'),
  'Digest':dict(type='string',pattern=r'^sha256:[0-9a-f]{64}$(?![\s\S])'),
  'Principal':obj(issuer_id=ref('Id'),issuer_epoch=ref('Id'),principal_id=ref('Id')),
  'Scope':obj(authority_service_id=ref('Id'),database_instance_id=ref('Id')),
  'Ref':obj(id=ref('Id'),revision=ref('U20'),digest=ref('Digest')),
  'ControlVersion':obj(epoch=ref('Id'),version=ref('U20')),
  'Reason':dict(type='string',maxLength=1024),
 }
 d['Lifetime']=obj(clock_domain_id=ref('Id'),descriptor_digest=ref('Digest'),issued_tick_ns=ref('U20'),expires_tick_ns=ref('U20'))
 d['Target']=obj(version=ref('U20'),mode={'enum':['manual','automatic']},holder=nullable(ref('Principal')))
 d['Target']['allOf']=[when('mode','manual',{'holder':ref('Principal')}),when('mode','automatic',{'holder':{'type':'null'}})]
 d['RequestKey']=obj(target_scope=ref('Scope'),issuer_id=ref('Id'),issuer_epoch=ref('Id'),principal_id=ref('Id'),
  request_epoch=ref('Id'),operation_id={'enum':[r[2] for r in ROUTES if r[0]=='post' and r[2]!='lookupControlRequest']},idempotency_key=ref('Id'))
 d['Identity']=obj(key=ref('RequestKey'),request_digest=ref('Digest'))
 d['RequestReceipt']=obj(identity=ref('Identity'),result_kind={'enum':['control_operation','transfer_offer']},initial_result_ref=ref('Ref'))
 d['LookupRequest']=obj(key=ref('RequestKey'),request_digest=ref('Digest'))
 d['LookupResult']=obj(status={'enum':['found','not_found']},receipt=nullable(ref('RequestReceipt')))
 d['LookupResult']['allOf']=[when('status','found',{'receipt':ref('RequestReceipt')}),when('status','not_found',{'receipt':{'type':'null'}})]
 base=dict(context_id=ref('Id'),idempotency_key=ref('Id'),expected_control=ref('ControlVersion'),reason=ref('Reason'))
 d['AcquireRequest']=obj(**base,force={'type':'boolean','default':False})
 d['AcquireRequest']['required'].remove('force')
 d['ReleaseRequest']=obj(**base)
 d['OfferRequest']=obj(**base,target_principal=ref('Principal'),offer_ttl_ms=dict(type='integer',minimum=1,maximum=86400000))
 d['AcceptRequest']=obj(**base)
 d['CancelRequest']=obj(context_id=ref('Id'),idempotency_key=ref('Id'),expected_offer=ref('Ref'),reason=ref('Reason'))
 d['PendingChange']=obj(operation_id=ref('Id'),target=ref('Target'),requested_by=ref('Principal'),reason=ref('Reason'))
 d['ControlRecord']=obj(record_id=ref('Id'),scope=ref('Scope'),device_id=ref('Id'),revision=ref('U20'),control_epoch=ref('Id'),
  effective_version=ref('U20'),reserved_version=ref('U20'),holder=nullable(ref('Principal')),mode={'enum':['manual','automatic']},
  pending_change=nullable(ref('PendingChange')),gate_state={'enum':['ready','fencing','protected']},
  in_flight_command_ids=dict(type='array',items=ref('Id'),uniqueItems=True,maxItems=256),
  unresolved_command_ids=dict(type='array',items=ref('Id'),uniqueItems=True,maxItems=256),record_digest=ref('Digest'))
 d['ControlRecord']['allOf']=[when('mode','manual',{'holder':ref('Principal')}),when('mode','automatic',{'holder':{'type':'null'}}),
  when('gate_state','ready',{'pending_change':{'type':'null'}}),when('gate_state','fencing',{'pending_change':ref('PendingChange')})]
 d['ControlOperation']=obj(operation_id=ref('Id'),scope=ref('Scope'),device_id=ref('Id'),revision=ref('U20'),identity=ref('Identity'),
  kind={'enum':['acquire','release','transfer']},requester=ref('Principal'),expected_control=ref('ControlVersion'),target=ref('Target'),
  state={'enum':['pending','effective','rejected','indeterminate']},barrier_selection_ref=nullable(ref('Ref')),
  effective_control_ref=nullable(ref('Ref')),failure_code=nullable(ref('Id')),operation_digest=ref('Digest'))
 d['ControlOperation']['allOf']=[when('state','effective',{'barrier_selection_ref':ref('Ref'),'effective_control_ref':ref('Ref'),'failure_code':{'type':'null'}})]
 d['ControlOperation']['allOf'] += [when('kind','release',{'target':{'properties':{'mode':{'const':'automatic'}}}})]
 for kind in ('acquire','transfer'):
  d['ControlOperation']['allOf'].append(when('kind',kind,{'target':{'properties':{'mode':{'const':'manual'}}}}))
 d['ControlOperation']['allOf'].append(when('state','pending',{'failure_code':{'type':'null'}}))
 for state in ('pending','rejected','indeterminate'):
  d['ControlOperation']['allOf'].append(when('state',state,{'effective_control_ref':{'type':'null'}}))
 for state in ('rejected','indeterminate'):
  d['ControlOperation']['allOf'].append(when('state',state,{'failure_code':ref('Id')}))
 d['TransferOffer']=obj(transfer_id=ref('Id'),scope=ref('Scope'),device_id=ref('Id'),revision=ref('U20'),
  from_principal=ref('Principal'),target_principal=ref('Principal'),expected_control=ref('ControlVersion'),lifetime=ref('Lifetime'),
  reason=ref('Reason'),state={'enum':['offered','accepted','expired','cancelled']},accepted_operation_id=nullable(ref('Id')),
  closed_reason=nullable(ref('Id')),offer_digest=ref('Digest'))
 d['TransferOffer']['allOf']=[when('state','accepted',{'accepted_operation_id':ref('Id'),'closed_reason':{'type':'null'}})]
 d['TransferOffer']['allOf'].append(when('state','offered',{'closed_reason':{'type':'null'}}))
 for state in ('offered','expired','cancelled'):
  d['TransferOffer']['allOf'].append(when('state',state,{'accepted_operation_id':{'type':'null'}}))
 for state in ('expired','cancelled'):
  d['TransferOffer']['allOf'].append(when('state',state,{'closed_reason':ref('Id')}))
 d['Error']=obj(code=ref('Id'),message=dict(type='string',maxLength=1024),retry_instruction={'const':'query_original'})
 return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'title':VERSION,'x-approved':False,'not':{},'$defs':d}
def build():
 s=schema()
 def project(v):
  if isinstance(v,list):return [project(x) for x in v]
  if not isinstance(v,dict):return v
  return {k:('#/components/schemas/'+x[len('#/$defs/'):] if k=='$ref' else project(x)) for k,x in v.items()}
 api={'openapi':'3.1.1','info':{'title':'LeafSeamer control authority candidate','version':VERSION},'servers':[{'url':'/api/v1'}],
  'x-approved':False,'paths':{},'components':{'schemas':project(s['$defs']),'securitySchemes':{
   'humanBearer':{'type':'http','scheme':'bearer'},'csrf':{'type':'apiKey','in':'header','name':'X-CSRF-Token'}}}}
 for method,path,name,request,response in ROUTES:
  params=[{'name':'X-LeafSeamer-Contract','in':'header','required':True,'schema':{'const':VERSION}}]
  import re
  params += [{'name':p,'in':'path','required':True,'schema':project(ref('Id'))} for p in re.findall(r'\{([^}]+)\}',path)]
  def result(model):return {'description':'候选结果；受理不等于生效或ready','headers':{'Cache-Control':{'schema':{'const':'no-store'}}},
   'content':{'application/json':{'schema':project(ref(model))}}}
  responses={'200':result(response)}
  if method=='post' and name!='lookupControlRequest':responses['202']=result(response)
  responses.update({str(code):result('Error') for code in (400,401,403,404,409,429,503)})
  op={'operationId':name,'parameters':params,'security':[{'humanBearer':[],**({'csrf':[]} if method=='post' else {})}],
      'responses':responses,'x-permission':PERMISSIONS[name],'x-principal-profiles':['human'],
      'x-required-guards':['current_subject','current_object_authorization']+(['trusted_origin'] if method=='post' else [])}
  if request:op['requestBody']={'required':True,'content':{'application/json':{'schema':project(ref(request))}}}
  if name=='acquireControl':op['x-force-permission']='control.emergency'
  api['paths'].setdefault(path,{})[method]=op
 return {'control-authority.schema.json':s,'control-authority.openapi.json':api}
def encoded():return {k:(json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode() for k,v in build().items()}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
 for name,data in encoded().items():
  if a.check:assert (HERE/name).read_bytes()==data,'生成漂移:'+name
  else:(HERE/name).write_bytes(data)
