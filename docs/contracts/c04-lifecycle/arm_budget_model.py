"""联接原生命周期的有限预算模型；完整可信库存与平台资格由合成上下文提供。"""
import copy,hashlib,re
import jsonschema,rfc8785
import reference_model as L
import build_arm_budget as G
MAX=10**20-1
def require(value,reason):
    if not value:raise ValueError(reason)
def validate(name,value):jsonschema.Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':G.schema()['$defs']}).validate(value)
def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def vector(**kw):return {d:str(kw.get(d,0)) for d in G.DIMENSIONS}
def arithmetic(a,b,sign=1):
    out={d:int(a[d])+sign*int(b[d]) for d in G.DIMENSIONS}
    require(all(0<=n<=MAX for n in out.values()),'budget_arithmetic');return vector(**out)
def fits(a,b):return all(int(a[d])<=int(b[d]) for d in a)
def cost(profile,forecast):
    validate('Profile',profile);validate('Shape',forecast)
    require(profile['purpose']=='simulation' or profile['validation_ref'] is not None,'unvalidated_profile')
    require(fits(forecast,profile['max_shape']),'shape_limit')
    d,r,e,p,s,t=(int(forecast[x]) for x in G.SHAPE)
    # 候选逻辑包络包含保护初写与有限状态观察；不代表物理页/WAL或实际耗时。
    rows=32+3*d+6*r+3*e+132*p+3*s+68*t
    out=vector(logical_rows=rows,logical_bytes=rows*(int(profile['max_row_bytes'])+512),
        queue_slots=2*t+p+1,work_units=rows+d+r+e+p+s+t)
    require(all(int(n)<=MAX for n in out.values()),'budget_arithmetic');return out
def ledger(profile):
    validate('Profile',profile)
    return dict(profile=copy.deepcopy(profile),profiles={digest(profile):copy.deepcopy(profile)},held=vector(),spent=vector(),tickets={},events={},releases={},request_tickets={})
def change_profile(b,profile):
    validate('Profile',profile);n=copy.deepcopy(b)
    for prior in n['profiles'].values():
        if (prior['profile_id'],prior['revision'])==(profile['profile_id'],profile['revision']):require(prior==profile,'profile_identity_conflict')
    n['profiles'][digest(profile)]=copy.deepcopy(profile);n['profile']=copy.deepcopy(profile);return n
def effective_dispatch(w):return w['run']['dispatch_eligible'] and not w.get('volatile_closed',False)
def reserve(w,request,preview,context,forecast,inventory_digest):
    """与原arm受理同一有限原子步；新容量失败不消费preflight或占槽。"""
    n=copy.deepcopy(w);b=n['protection_budget']
    key=(n['run']['scope']['authority_service_id'],n['run']['scope']['database_instance_id'],n['run']['run_id'],context['request_epoch'],context['actor'],request['context']['idempotency_key'])
    if not context['storage_healthy']:n['volatile_closed']=True;return n,'protected_uncommitted'
    # 旧幂等身份先查原，不能因新预算满额拒绝查账。
    proposed,result=L.reserve(n,'arm',request,preview,context)
    if result=='existing':
        require(key in b['request_tickets'] and b['request_tickets'][key] in b['tickets'],'missing_budget_original');return n,result
    if result!='accepted':return n,result
    for field in ('revision','arm_generation'):
        require(int(proposed['run'][field])<=MAX,'u20_exhausted')
    require(int(proposed['slot']['revision'])<=MAX,'u20_exhausted')
    require(context['inventory_verified'] and context['controller_capacity_verified'],'unqualified_inventory')
    require(inventory_digest==context['inventory_digest'],'inventory_binding')
    require(not n.get('volatile_closed',False),'volatile_closed')
    require(digest(b['profile']) in b['profiles'],'profile_not_registered')
    per=cost(b['profile'],forecast)
    require(int(forecast['runs'])>=1 and int(forecast['controller_targets'])>=len(context['required_targets'])
        and int(forecast['preparations'])>=len(context['required_targets']),'understated_targets')
    total=vector(**{k:int(v)*int(b['profile']['episodes']) for k,v in per.items()})
    require(all(int(x)<=MAX for x in total.values()),'budget_arithmetic')
    if not fits(arithmetic(arithmetic(b['held'],b['spent']),total),b['profile']['capacity']):return n,'capacity_rejected'
    op=proposed['reservation']['operation_id']
    binding=dict(scope=n['run']['scope'],run_id=n['run']['run_id'],generation=proposed['run']['arm_generation'],operation_id=op,
        artifact_digest=n['run']['artifact_ref']['digest'],inventory_digest=inventory_digest,profile_id=b['profile']['profile_id'],
        profile_revision=b['profile']['revision'],profile_digest=digest(b['profile']),forecast=copy.deepcopy(forecast))
    validate('Binding',binding)
    ident='budget.'+digest(binding).split(':',1)[1]
    require(ident not in b['tickets'] and key not in b['request_tickets'],'reservation_reuse')
    ticket=dict(reservation_id=ident,binding=binding,binding_digest=digest(binding),per_episode=per,held=total,
        spent=vector(),episodes_left=b['profile']['episodes'],state='held')
    validate('Reservation',ticket)
    proposed['protection_budget']['held']=arithmetic(b['held'],total)
    proposed['protection_budget']['tickets'][ident]=ticket
    proposed['protection_budget']['request_tickets'][key]=ident
    proposed['reservation']['budget_reservation_id']=ident
    if context.get('budget_abort',False):return n,'rolled_back'
    return proposed,'accepted'
def ready(w,receipts,context):
    n=copy.deepcopy(w);b=n['protection_budget'];ident=n['reservation']['budget_reservation_id'];ticket=b['tickets'][ident]
    require(ticket['binding']['generation']==n['run']['arm_generation'] and ticket['binding']['operation_id']==n['reservation']['operation_id'],'budget_binding')
    if ticket['binding']['profile_digest']!=digest(b['profile']):n['volatile_closed']=True;return n,'profile_changed'
    if ticket['binding']['inventory_digest']!=context['inventory_digest']:n['volatile_closed']=True;return n,'inventory_changed'
    if not context['authorized']:n['volatile_closed']=True;return n,'authorization_changed'
    if ticket['state']!='held' or int(ticket['episodes_left'])!=int(b['profile']['episodes']):n['volatile_closed']=True;return n,'budget_used_before_ready'
    if not context['controller_capacity_verified'] or not context['inventory_verified']:n['volatile_closed']=True;return n,'unqualified_inventory'
    return L.prepare(n,receipts,context)
def protect(w,use,*,storage_healthy=True,abort=False,elapsed_wait_ns='0'):
    """先安装内存关闭，再原子消费一份包络；失败不伪造持久保护成功。"""
    validate('ProtectionUse',use);n=copy.deepcopy(w);b=n['protection_budget']
    ident=use['reservation_id'];require(ident in b['tickets'],'missing_reservation');t=b['tickets'][ident]
    require(use['binding_digest']==t['binding_digest'],'budget_binding')
    original_profile=b['profiles'][t['binding']['profile_digest']]
    require(int(t['binding']['generation'])<=int(n['run']['arm_generation']),'future_generation')
    current=t['binding']['generation']==n['run']['arm_generation']
    if current:n['volatile_closed']=True
    key=(ident,use['event_id']);raw=digest(use)
    if key in b['events']:
        require(b['events'][key]['use_digest']==raw,'event_conflict');return n,'existing'
    require(t['state']!='released','released_reservation')
    if not fits(use['observed_shape'],t['binding']['forecast']):return n,'exposure_growth'
    if int(use['observed_max_row_bytes'])>int(original_profile['max_row_bytes']):return n,'row_bound'
    if not storage_healthy:return n,'protected_uncommitted'
    require(isinstance(elapsed_wait_ns,str) and re.fullmatch(r'0|[1-9][0-9]{0,19}',elapsed_wait_ns),'wait_counter')
    if int(elapsed_wait_ns)>=int(original_profile['max_queue_wait_ns']):return n,'protection_queue_expired'
    if t['episodes_left']=='0':return n,'protection_budget_exhausted'
    delta=t['per_episode'];t['held']=arithmetic(t['held'],delta,-1);t['spent']=arithmetic(t['spent'],delta)
    b['held']=arithmetic(b['held'],delta,-1);b['spent']=arithmetic(b['spent'],delta)
    t['episodes_left']=str(int(t['episodes_left'])-1);t['state']='exhausted' if t['episodes_left']=='0' else 'held'
    b['events'][key]=dict(use_digest=raw,event_digest=use['event_digest'],charge=delta)
    if current:n['run'].update(lifecycle='paused',dispatch_eligible=False)
    if abort:
        rollback=copy.deepcopy(w)
        if current:rollback['volatile_closed']=True
        return rollback,'protected_uncommitted'
    return n,'protected_committed'
def release(w,proof,*,trusted_proof=False):
    validate('ReleaseProof',proof);require(trusted_proof,'untrusted_release')
    n=copy.deepcopy(w);b=n['protection_budget'];ident=proof['reservation_id'];t=b['tickets'][ident]
    require(t['binding_digest']==proof['binding_digest'],'budget_binding')
    if ident in b['releases']:
        require(b['releases'][ident]==digest(proof),'release_conflict');return n,'existing'
    if t['binding']['generation']==n['run']['arm_generation']:
        require(not effective_dispatch(n),'still_dispatchable')
        require(n['reservation'].get('state') in ('paused','indeterminate','ready'),'active_preparation')
    b['held']=arithmetic(b['held'],t['held'],-1);t['held']=vector();t['state']='released';t['episodes_left']='0'
    b['releases'][ident]=digest(proof)
    # 已消耗存储与墓碑不退款；归档/GC的物理回收另有完整引用图流程。
    return n,'released_unused'
