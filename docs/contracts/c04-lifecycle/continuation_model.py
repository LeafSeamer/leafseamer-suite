"""继续运行契约的纯函数关系判定；不是SQL writer、鉴权实现或发送出口。"""
import hashlib
import rfc8785
from jsonschema import Draft202012Validator
import build_continuation as G

COMMON=('contract_version','origin_scope','run_id','generation','transfer_id',
        'recovery_operation_id','recovery_execution_id','continuation_plan_ref')
LIMITS={'Request':262144,'Receipt':16384,'Adoption':16384}

def digest(value):return 'sha256:'+hashlib.sha256(rfc8785.dumps(value)).hexdigest()
def seal(value,key):return dict(value,**{key:digest({k:v for k,v in value.items() if k!=key})})
def scope_key(value):return (value['authority_service_id'],value['database_instance_id'])
def ref_key(value):return (scope_key(value['scope']),value['id'],value['revision'])
def require(value,reason):
    if not value:raise ValueError(reason)

def validate(name,value):
    s=G.schema();Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':s['$defs']}).validate(value)
    require(len(rfc8785.dumps(value))<=LIMITS[name],'body_capacity')
    key={'Request':'request_digest','Receipt':'receipt_digest','Adoption':'adoption_digest'}[name]
    require(value[key]==digest({k:v for k,v in value.items() if k!=key}),'digest')

def request_shape(q):
    validate('Request',q)
    keys=[scope_key(t['controller_scope']) for t in q['targets']]
    require(keys==sorted(set(keys)),'target_order_unique')
    require(sum(len(t['devices']) for t in q['targets'])<=256,'device_capacity')
    for t in q['targets']:
        ids=[x['device_id'] for x in t['devices']]
        require(ids==sorted(set(ids)),'device_order_unique')
        require(t['preparation_ref']['scope']==t['controller_scope'] and
                t['recovery_grant_ref']['scope']==t['controller_scope'],'parent_scope')
        for device in t['devices']:
            require(all(device[k]['scope']==t['controller_scope'] for k in
                    ('control_ref','authorization_ref','action_set_ref')),'device_ref_scope')
    require(q['approval_ref']['scope']==q['origin_scope'] and
            q['continuation_plan_ref']['scope']==q['origin_scope'],'origin_ref_scope')

def approval_subject(q):
    # 审批绑定除自身Ref和封装摘要外的全部请求，避免循环摘要。
    return digest({k:v for k,v in q.items() if k not in ('approval_ref','request_digest')})

def common(value,q):
    require(all(value[k]==q[k] for k in COMMON),'common_binding')
    require(value['request_digest']==q['request_digest'],'request_binding')

def request_eligible(q,seamer):
    request_shape(q)
    require(seamer['read_authorized'] and seamer['write_authorized'],'authority')
    require({k:q[k] for k in ('origin_scope','run_id','generation','recovery_operation_id','recovery_execution_id',
            'continuation_plan_ref')}==seamer['binding'],'run_binding')
    require(q['targets']==seamer['required_targets'],'full_target_set')
    require(q['approval_ref']==seamer['approval_ref'] and seamer['approval_subject']==approval_subject(q)
            and seamer['approval_current'] and seamer['approval_human'],'approval')
    require(seamer['run_state']=='running' and seamer['operation_state'] in ('running','reconciling')
            and seamer['execution_state']=='running','recovery_state')
    require(seamer['recovery_steps_complete'] and seamer['recovery_resources_clear']
            and seamer['recovery_lock_held'],'recovery_evidence')
    require(seamer['source_current'] and seamer['time_current'] and seamer['budget_reserved']
            and not seamer['pause_latched'],'current_gates')

def controller_eligible(q,target,c):
    require(c['scope']==target['controller_scope'],'controller_scope')
    require(c['origin_scope']==q['origin_scope'] and c['run_id']==q['run_id'] and
            c['generation']==q['generation'] and c['recovery_execution_id']==q['recovery_execution_id'],'parent_binding')
    require(c['preparation_ref']==target['preparation_ref'] and c['recovery_grant_ref']==target['recovery_grant_ref']
            and c['mode']=='recovery','parent_binding')
    require(c['devices']==target['devices'],'device_authority')
    require(c['preparation_state']=='applied' and int(c['deny_through_generation'])<int(q['generation'])
            and not c['closed'],'preparation_denied')
    require(c['authorization_current'] and c['automatic_control'] and not c['pending_takeover']
            and c['runtime_current'] and c['time_current'] and c['capacity_reserved'],'controller_gates')
    require(c['plan_ref']==q['continuation_plan_ref'] and c['plan_verified'],'plan_authority')

def receipt_eligible(q,r,c):
    request_shape(q);validate('Receipt',r);common(r,q)
    ts=[t for t in q['targets'] if t['controller_scope']==r['controller_scope']]
    require(len(ts)==1,'unexpected_controller');t=ts[0];controller_eligible(q,t,c)
    require(r['preparation_ref']==t['preparation_ref'] and r['recovery_grant_ref']==t['recovery_grant_ref']
            and r['target_digest']==digest(t),'target_binding')
    # 原件由可信Controller提供者解析；摘要相同、请求字段相同均不能替代当前资格。
    require(r==c['durable_receipt'],'receipt_original')
    require(r['continuation_grant_ref']['scope']==c['scope'] and r['qualification_ref']['scope']==c['scope'],
            'issuer_scope')
    require(ref_key(r['continuation_grant_ref'])!=ref_key(r['recovery_grant_ref']),'distinct_grant')
    grant=c['grant'];require(grant['ref']==r['continuation_grant_ref'] and grant['scope']=='run_generation'
        and grant['request_digest']==q['request_digest'] and grant['target_digest']==r['target_digest']
        and grant['plan_ref']==q['continuation_plan_ref'] and grant['parent_preparation_ref']==t['preparation_ref']
        and grant['activation']=='adoption_and_r5','grant_binding')
    require(c['qualification_ref']==r['qualification_ref'],'qualification_binding')

def receipt_ref(r):return dict(scope=r['controller_scope'],id=r['receipt_id'],revision=r['revision'],digest=r['receipt_digest'])

def adoption_eligible(q,a,receipts,seamer,controllers):
    request_eligible(q,seamer);validate('Adoption',a);common(a,q)
    require([scope_key(r['controller_scope']) for r in receipts]==[scope_key(t['controller_scope']) for t in q['targets']],
            'receipt_set')
    require(a['receipt_refs']==[receipt_ref(r) for r in receipts],'receipt_refs')
    for r in receipts:
        key=scope_key(r['controller_scope']);require(key in controllers,'missing_controller')
        receipt_eligible(q,r,controllers[key])
    require(all(a['expected_'+k+'_revision']==seamer[k+'_revision'] for k in ('run','slot','operation')),'adoption_cas')
    proof=seamer['release_proof']
    require(proof['ref']==a['release_proof_ref'] and proof['operation_id']==q['recovery_operation_id']
            and proof['execution_id']==q['recovery_execution_id'] and proof['request_digest']==q['request_digest']
            and proof['receipt_refs']==a['receipt_refs'] and proof['resources_clear']
            and proof['retained_parent_refs']==[t['preparation_ref'] for t in q['targets']],'release_proof')

def command_eligible(q,a,receipts,controller,command,seamer):
    # R5和adoption原件须由受信提供者查得；本函数不实施网络鉴权、SQL或唯一发送出口。
    request_shape(q);validate('Adoption',a);common(a,q)
    require(seamer['adopted']==a and seamer['adopted_request']==q and seamer['r5_adoption_digest']==a['adoption_digest'],
            'adoption_not_committed')
    require(command['origin_scope']==q['origin_scope'] and command['run_id']==q['run_id'] and
            command['generation']==q['generation'],'command_binding')
    require(seamer['armed_generation']==q['generation'] and seamer['execution_current'] and
            seamer['plan_current'] and seamer['source_current'] and seamer['time_current'] and
            not seamer['pause_latched'],'execution_current')
    require(command['plan_ref']==q['continuation_plan_ref'] and command['execution_id']!=q['recovery_execution_id']
            and command['step_verified'],'command_plan')
    selected=[r for r in receipts if r['controller_scope']==controller['scope']]
    require(len(selected)==1,'receipt_set');r=selected[0];receipt_eligible(q,r,controller)
    require(receipt_ref(r) in a['receipt_refs'] and command['continuation_grant_ref']==r['continuation_grant_ref']
            and command['adoption_digest']==a['adoption_digest'],'command_grant')
    devices=[t for t in q['targets'] if t['controller_scope']==controller['scope']][0]['devices']
    require(command['device_id'] in [d['device_id'] for d in devices],'command_device')
    require(command['action_verified'] and command['parameters_verified'] and command['final_exit_verified'],
            'final_exit')

def issue_decision(q,target,c,original,read_authorized):
    """签发前决策：已有原件只查原，无原件才检查新签发资格；不创建grant。"""
    request_shape(q);require(read_authorized,'read_authority')
    if original is not None:
        require(original['request']==q,'identity_conflict')
        return 'existing'
    require(target in q['targets'],'unexpected_target')
    controller_eligible(q,target,c)
    require(c['write_authorized'] and c['approval_verified'] and c['approval_ref']==q['approval_ref']
            and c['approval_subject']==approval_subject(q),'issue_authority')
    require(c['same_generation_transfer_id'] in (None,q['transfer_id']),'generation_identity')
    return 'eligible'
