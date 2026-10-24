"""继续运行授权在执行绑定、请求、Guard、许可与Intent之间的关系子检查。"""
import copy,json
from jsonschema import Draft202012Validator
import build_continuation_binding as G
import continuation_protocol_model as P
C=P.C;M=P.M;T=P.T;need=M.require
SCHEMA=G.build()['continuation-binding.schema.json']
def validate(name,value):Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']}).validate(value)
def content(request):return {k:v for k,v in request.items() if k not in ('context_id','idempotency_key','correlation_id')}
def eref(e):return dict(kind='execution_binding',scope=e['scope'],object_id=e['execution_id'],revision='1',digest=e['binding_digest'])
def selection(q,a,r,t):
    return dict(transfer_ref=P.request_ref(q),adoption_ref=P.adoption_ref(a),receipt_ref=M.receipt_ref(r),
        grant_ref=r['continuation_grant_ref'],plan_ref=q['continuation_plan_ref'],parent_preparation_ref=t['preparation_ref'])
def targets(q,a,receipts):
    M.request_shape(q);M.validate('Adoption',a);M.common(a,q)
    need(a['receipt_refs']==[M.receipt_ref(r) for r in receipts],'receipt_set')
    need([r['controller_scope'] for r in receipts]==[t['controller_scope'] for t in q['targets']],'full_target_set')
    out=[]
    for t,r in zip(q['targets'],receipts):
        P.validate_record('Controller',dict(protocol_version=P.G.VERSION,request=q,receipt=r,qualification='not_asserted'))
        out.append(dict(controller_scope=t['controller_scope'],selection=selection(q,a,r,t),device_ids=[v['device_id'] for v in t['devices']]))
    return out
def execution(base,q,a,receipts):
    value=copy.deepcopy(base);items=targets(q,a,receipts)
    value.update(binding_version=G.VERSION,authorization_mode='continuation',continuations=items,
        grants=[P.public_ref(x['selection']['grant_ref'],'grant') for x in items])
    value=M.seal(value,'binding_digest');validate_execution(value,q,a,receipts);return value
def validate_execution(e,q,a,receipts):
    validate('ExecutionBinding',e);need(e['binding_digest']==M.digest({k:v for k,v in e.items() if k!='binding_digest'}),'execution_digest')
    need(e['authorization_mode']=='continuation' and e['scope']==q['origin_scope'] and e['run_id']==q['run_id'] and e['arm_generation']==q['generation'],'execution_scope')
    need(e['execution_id']!=q['recovery_execution_id'] and e['origin']['kind']=='trigger','new_execution')
    expected=targets(q,a,receipts);need(e['continuations']==expected,'execution_targets')
    need(e['grants']==[P.public_ref(x['selection']['grant_ref'],'grant') for x in expected],'execution_grants')
def validate_chain(e,request,guard,permit,intent,ack,authority):
    for name,value in [('CommandRequest',request),('ExecutionGuard',guard),('TransmissionPermit',permit),('DispatchIntent',intent),('GuardAck',ack)]:validate(name,value)
    q,a,receipts=authority['request'],authority['adoption'],authority['receipts'];validate_execution(e,q,a,receipts)
    need(e==authority['execution_binding'],'execution_original')
    ab=request['automation_binding'];need(ab is not None and ab['authorization_mode']=='continuation','continuation_required')
    need(guard['automation_binding']==permit['automation_binding']==intent['automation_binding']==ab,'chain_binding')
    need(ab['execution_binding_ref']==eref(e) and ab['origin_scope']==e['scope'] and ab['run_id']==e['run_id']
        and ab['arm_generation']==e['arm_generation'] and ab['execution_id']==e['execution_id'],'execution_reference')
    candidates=[x for x in e['continuations'] if x['controller_scope']==authority['controller_scope']];need(len(candidates)==1,'target_controller')
    selected=candidates[0];need(ab['continuation']==selected['selection'] and request['device_id'] in selected['device_ids'],'selected_target')
    step=authority['step'];need((ab['step_id'],ab['logical_action_id'],ab['definition_version'])==(step['step_id'],step['logical_action_id'],step['definition_version']),'step_original')
    need({k:request[k] for k in ('device_id','action_id','capability_version','parameters')}=={k:step[k] for k in ('device_id','action_id','capability_version','parameters')},'step_parameters')
    grant=selected['selection']['grant_ref'];rb=request['run_binding']
    need(rb==dict(run_id=e['run_id'],definition_version=ab['definition_version'],grant_id=grant['id'],grant_revision=grant['revision'],
        arm_generation=e['arm_generation'],step_id=ab['step_id'],logical_action_id=ab['logical_action_id']),'run_binding')
    auth=guard['binding'];need(auth['grant_id']==grant['id'] and auth['grant_revision']==permit['grant_revision']==grant['revision']
        and auth['arm_generation']==permit['arm_generation']==e['arm_generation'],'grant_revision')
    need(all(auth[k]==authority['principal'][k] for k in ('issuer_id','issuer_epoch','principal_id','audience')),'principal_original')
    need(permit['origin']==request['origin']==auth['origin']==intent['origin']=='automation','origin')
    need(guard['guard_digest']==M.digest({k:v for k,v in guard.items() if k!='guard_digest'}),'guard_digest')
    need(permit['content_digest']==ack['content_digest']==M.digest(content(request))==authority['request_digest'],'content_digest')
    need(permit['guard_id']==intent['guard_id']==ack['guard_id']==guard['guard_id'] and permit['guard_digest']==intent['guard_digest']==ack['guard_digest']==guard['guard_digest'],'guard_original')
    need(permit['transmission']['intent']==intent,'transmission_intent')
    for key in ('permit_id','command_id','attempt_id','dispatch_intent_id','controller_boot_id','worker_boot_id','device_session_id','clock_domain_id','descriptor_digest'):
        need(permit[key]==intent[key],'intent_'+key)
    for key in ('permit_id','command_id','controller_boot_id','worker_boot_id','clock_domain_id','descriptor_digest'):need(guard[key]==permit[key],'guard_'+key)
    need(guard['device_id']==intent['device_id']==request['device_id'] and guard['ipc_session_id']==intent['ipc_session_id'],'device_session')
    need(ack['permit_id']==permit['permit_id'] and ack['command_id']==permit['command_id'],'ack_permit')
    need(ack['automation_binding_digest']==intent['automation_binding_digest']==M.digest(ab),'binding_echo')
    for k in ('authorization_current','control_current','source_current','time_current','budget_current','adoption_current','r5_committed','grant_current'):
        need(authority[k],k)
    # 此函数只证明授权链子域；成功不解除Controller最终AdmissionSeal的其他阻断。
    return 'binding_valid'

def validate_resend(previous,current):
    validate_chain(*previous);validate_chain(*current)
    e,r,g,p,i,ack,a=previous;ne,nr,ng,np,ni,nack,na=current
    need(ne==e and content(nr)==content(r),'resend_original_content')
    need(np['permit_id']!=p['permit_id'] and ng['guard_id']!=g['guard_id'],'resend_fresh_authority')
    for key in ('command_id','attempt_id','dispatch_intent_id','device_session_id','worker_boot_id','controller_boot_id'):
        need(np[key]==p[key],'resend_'+key)
    old,new=p['transmission'],np['transmission']
    need(new['kind']=='protocol_resend' and new['ordinal']==str(int(old['ordinal'])+1),'resend_ordinal')
    need(int(new['issued_revision'])>int(old['issued_revision']),'resend_issue_order')
    for key in ('packet_ref','primitive_id','parent_dispatch_intent_id','initial_permit_id'):need(new[key]==old[key],'resend_'+key)
    return 'resend_binding_valid'
