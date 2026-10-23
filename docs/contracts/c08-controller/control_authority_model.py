"""控制权候选的有限原子副本模型；没有HTTP、SQLite、IPC或真实身份。"""
import copy
import hashlib
import rfc8785

MAX=10**20-1
class Rejected(Exception):pass
class Injected(Exception):pass
def digest(x):return 'sha256:'+hashlib.sha256(rfc8785.dumps(x)).hexdigest()
def sealed(x,field):
 x[field]=digest({k:v for k,v in x.items() if k!=field});return x
def ref(x,id_field,digest_field):return dict(id=x[id_field],revision=x['revision'],digest=x[digest_field])
def version(r):return dict(epoch=r['control_epoch'],version=r['effective_version'])
def bump(r,field):
 if int(r[field])>=MAX:raise Rejected('counter_exhausted')
 r[field]=str(int(r[field])+1)
def require(value,reason):
 if not value:raise Rejected(reason)
def touch_record(r):bump(r,'revision');sealed(r,'record_digest')
def touch_offer(o):bump(o,'revision');sealed(o,'offer_digest')
def touch_operation(o):bump(o,'revision');sealed(o,'operation_digest')
def transact(store,action,fault_at=None):
 work=copy.deepcopy(store);steps=[]
 def checkpoint(label):
  steps.append(label)
  if fault_at==label:raise Injected(label)
 result=action(work,checkpoint)
 if work['record']!=store['record']:
  r=work['record'];require(r['revision'] not in work['control_history'],'revision_reuse')
  work['control_history'][r['revision']]=copy.deepcopy(r);checkpoint('history')
 work['journal'].append({'steps':steps,'result':copy.deepcopy(result)})
 checkpoint('commit')
 return work,result

def invoke(store,method,body,context,transfer_id=None,fault_at=None):
 """调用者先验证Schema；context为合成可信上下文，完整权威不在本函数取得。"""
 c=context;r=store['record'];actor=c['actor']
 require(c['authenticated'] and c['human'] and c['read_allowed'],'identity')
 require(c['scope']==r['scope'] and c['device_id']==r['device_id'],'scope')
 require(c['origin_valid'] and c['csrf_valid'],'request_origin')
 normalized=copy.deepcopy(body);normalized.pop('context_id');key=normalized.pop('idempotency_key')
 if method=='acquireControl':normalized.setdefault('force',False)
 content=dict(operation_id=method,scope=r['scope'],device_id=r['device_id'],transfer_id=transfer_id,input=normalized)
 identity=dict(key=dict(target_scope=r['scope'],**actor,request_epoch=c['request_epoch'],operation_id=method,idempotency_key=key),request_digest=digest(content))
 k=digest(identity['key'])
 if k in store['requests']:
  receipt=store['requests'][k]
  require(receipt['identity']==identity,'identity_conflict')
  return copy.deepcopy(store),copy.deepcopy(receipt)
 require(c['write_allowed'] and c['origin_valid'] and c['csrf_valid'] and c['namespace_open'] and c['context_current'],'permission')
 require(c['storage_healthy'] and c['domain_current'],'unavailable')
 def action(w,step):
  r=w['record'];offer=None
  if method=='cancelTransfer':
   require(transfer_id in w['offers'],'not_found');offer=w['offers'][transfer_id]
   require(offer['from_principal']==actor,'not_offer_owner')
   require(body['expected_offer']==ref(offer,'transfer_id','offer_digest'),'offer_cas')
   require(offer['state']=='offered','offer_consumed')
   offer['state']='cancelled';offer['closed_reason']='cancelled_by_owner';touch_offer(offer);step('offer')
   result_kind='transfer_offer';result_ref=ref(offer,'transfer_id','offer_digest')
  else:
   require(body['expected_control']==version(r),'control_cas')
   require(r['pending_change'] is None,'control_busy')
   if method=='offerTransfer':
    require(r['mode']=='manual' and r['holder']==actor,'not_holder')
    target=body['target_principal'];require(target!=actor and c['target_authorized'],'target')
    now=c['now'];expiry=now+body['offer_ttl_ms']*1000000;require(expiry<=MAX,'counter_exhausted')
    offer=sealed(dict(transfer_id='transfer.'+k[7:31],scope=r['scope'],device_id=r['device_id'],revision='1',
     from_principal=actor,target_principal=target,expected_control=version(r),lifetime=dict(**c['domain'],issued_tick_ns=str(now),expires_tick_ns=str(expiry)),
     reason=body['reason'],state='offered',accepted_operation_id=None,closed_reason=None),'offer_digest')
    w['offers'][offer['transfer_id']]=offer;step('offer')
    result_kind='transfer_offer';result_ref=ref(offer,'transfer_id','offer_digest')
   else:
    if method=='acceptTransfer':
     require(transfer_id in w['offers'],'not_found');offer=w['offers'][transfer_id]
     require(offer['state']=='offered','offer_consumed')
     require(offer['scope']==r['scope'] and offer['device_id']==r['device_id'],'offer_scope')
     require(offer['target_principal']==actor,'not_target')
     require(offer['expected_control']==version(r) and offer['from_principal']==r['holder'],'offer_control')
     require(c['from_authorized'] and c['target_authorized'],'transfer_permission')
     lifetime=offer['lifetime'];require(all(lifetime[n]==v for n,v in c['domain'].items()),'offer_clock')
     require(int(lifetime['issued_tick_ns'])<=c['now']<int(lifetime['expires_tick_ns']),'offer_expired')
     kind='transfer';holder=actor
    elif method=='releaseControl':
     require(r['mode']=='manual' and r['holder']==actor,'not_holder');kind='release';holder=None
    elif method=='acquireControl':
     require(r['holder']!=actor,'already_holder')
     if normalized['force']:require(c['force_allowed'] and bool(body['reason'].strip()),'force_required')
     if r['mode']=='manual':require(normalized['force'] and c['force_allowed'] and bool(body['reason'].strip()),'force_required')
     require(c['target_authorized'],'target');kind='acquire';holder=actor
    else:raise Rejected('operation')
    bump(r,'reserved_version');step('reserve')
    oid='control.'+k[7:31];target=dict(version=r['reserved_version'],mode='manual' if holder else 'automatic',holder=holder)
    op=sealed(dict(operation_id=oid,scope=r['scope'],device_id=r['device_id'],revision='1',identity=identity,kind=kind,requester=actor,
     expected_control=version(r),target=target,state='pending',barrier_selection_ref=None,effective_control_ref=None,failure_code=None),'operation_digest')
    w['operations'][oid]=op;w['latest_attempt'][oid]=oid+'.attempt.1';w['attempt_history'].append(oid+'.attempt.1');step('operation')
    r['pending_change']=dict(operation_id=oid,target=target,requested_by=actor,reason=body['reason']);r['gate_state']='fencing';touch_record(r);step('pending')
    if offer is not None:
     offer['state']='accepted';offer['accepted_operation_id']=oid;touch_offer(offer);step('offer')
    # 这里只登记待落实写集边界，不伪造真实queued/cut/coverage。
    w['barrier_intents'].append(oid);step('barrier_intent')
    result_kind='control_operation';result_ref=ref(op,'operation_id','operation_digest')
  receipt=dict(identity=identity,result_kind=result_kind,initial_result_ref=result_ref)
  w['requests'][k]=receipt;step('receipt');w['audit'].append(k);step('audit');w['outbox'].append(k);step('outbox')
  return receipt
 return transact(store,action,fault_at)

def settle(store,oid,context,*,uncertain=False,reject=False,fault_at=None):
 def action(w,step):
  op=w['operations'][oid];r=w['record']
  require(context['storage_healthy'],'unavailable')
  require(op['state'] in ('pending','indeterminate'),'terminal')
  require(r['pending_change'] is not None and r['pending_change']['operation_id']==oid,'pending_owner')
  require(op['expected_control']==version(r),'control_cas')
  if uncertain:
   op['state']='indeterminate';op['failure_code']='barrier_unconfirmed';r['gate_state']='protected'
  elif reject:
   require(context['rejection_verified'],'rejection_unverified')
   op['state']='rejected';op['failure_code']='target_authorization_revoked';r['pending_change']=None;r['gate_state']='protected'
  else:
   require(context['target_authorized'] and context['authorized_principal']==(op['target']['holder'] or op['requester']),'unavailable')
   b=context['barrier'];require(context['barrier_verified'],'barrier_unverified')
   require(b['operation_id']==oid and b['scope']==r['scope'] and b['device_id']==r['device_id'] and
    b['control_epoch']==r['control_epoch'] and b['target_version']==op['target']['version'] and
    b['attempt_id']==w['latest_attempt'][oid],'barrier_binding')
   r['effective_version']=op['target']['version'];r['holder']=op['target']['holder'];r['mode']=op['target']['mode']
   r['pending_change']=None;r['gate_state']='protected';op['state']='effective';op['failure_code']=None;op['barrier_selection_ref']=b['selection_ref']
  touch_record(r);step('control')
  if op['state']=='effective':op['effective_control_ref']=ref(r,'record_id','record_digest')
  touch_operation(op);step('result');w['audit'].append(oid);step('audit');w['outbox'].append(oid);step('outbox')
  return copy.deepcopy(op)
 return transact(store,action,fault_at)

def new_attempt(store,oid,attempt_id):
 w=copy.deepcopy(store);op=w['operations'][oid]
 require(op['state']=='indeterminate' and w['record']['pending_change']['operation_id']==oid,'not_recoverable')
 require(attempt_id not in w['attempt_history'],'attempt_reuse')
 # 真实实现还需旧出口退役和完整新尝试记录；本函数仅改变合成当前选择。
 w['latest_attempt'][oid]=attempt_id;w['attempt_history'].append(attempt_id);return w

def expire_offers(store,domain,now):
 w=copy.deepcopy(store)
 for o in w['offers'].values():
  if o['state']!='offered':continue
  same=all(o['lifetime'][k]==v for k,v in domain.items())
  if not same or now>=int(o['lifetime']['expires_tick_ns']):
   o['state']='expired';o['closed_reason']='ttl_elapsed' if same else 'clock_domain_changed';touch_offer(o)
 return w

def restart(store,domain,now):
 w=expire_offers(store,domain,now);r=w['record'];r['gate_state']='protected';touch_record(r)
 w['control_history'][r['revision']]=copy.deepcopy(r)
 return w
