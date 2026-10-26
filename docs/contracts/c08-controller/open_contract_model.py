"""当前OPEN契约的原件关联判定；上下文提供者仍须另行证明可信。"""
import copy,json
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
import build_open_contract as G
import open_plan_model as O
import open_lifecycle_model as L
import scoped_gate_model as S
SCHEMA=G.build();IPC=json.loads(G.IPC.read_bytes())
REGISTRY=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in (SCHEMA,IPC)])
def valid(name,v):return Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=REGISTRY).is_valid(v)
def proposal_ref(p):return dict(id=p['plan']['plan_id'],revision='1',digest=p['proposal_digest'])
def successor(before,after):
    a,b=before['record_ref'],after['record_ref']
    return b['id']!=a['id'] and int(a['revision'])<10**20-1 and int(b['revision'])==int(a['revision'])+1 and b['digest']!=a['digest']
def access_context(p,c):
    a=p['plan']['body']['gate_access'];s=c['scope_context']
    if s['binding']!=c['binding'] or s['control_projection']!=c['control_projection']:return 'scope_context_projection'
    if any(s[k+'_ref']!=c['eligibility_refs'][k] for k in ('authorization','resource_safety','gate_safety')):return 'scope_context_eligibility'
    if s['control_projection']['authority_ref']!=c['eligibility_refs']['control_authority']:return 'scope_context_authority'
    if s['resource_ref']!=c['state_refs']['resource']:return 'scope_context_resource'
    if a['binding']!=c['binding'] or a['control_authority_ref']!=c['eligibility_refs']['control_authority']:return 'access_projection'
    if any(a[k+'_ref']!=c['eligibility_refs'][k] for k in ('authorization','resource_safety','gate_safety')):return 'access_eligibility'
    return None
def proposal_error(p,c,now):
    if not valid('OpenProposal',p):return 'schema'
    if not O.intact(p,'proposal_digest') or p!=c['stored_proposal']:return 'proposal_source'
    plan=p['plan'];body=plan['body'];a=body['gate_access'];e=body['protection_assessment'];control=p['control_before'];gate=p['gate_before']
    if c['eligibility_refs']!=p['eligibility_refs']:return 'eligibility_changed'
    if control!=c['control_projection'] or gate!=c['gate_projection']:return 'projection_changed'
    if control['record_ref']!=plan['state_refs']['control'] or gate['record_ref']!=plan['state_refs']['gate']:return 'projection_ref'
    if control['authority_ref']!=p['eligibility_refs']['control_authority'] or plan['state_refs']['authorization']!=p['eligibility_refs']['authorization']:return 'authority_refs'
    if control['pending_operation_id'] is not None or control['gate_state']=='ready' or gate['phase']!='fenced' or gate['activation_id'] is not None:return 'pre_state'
    if (control['mode']=='automatic')!=(control['holder'] is None):return 'holder_mode'
    if (control['control_epoch'],control['effective_version'])!=(body['control_epoch'],body['control_version']):return 'control_binding'
    if gate['binding']!=plan['binding'] or any(gate[k]!=body[k] for k in ('gate_revision','gate_token','barrier_id','lease_until_tick_ns')):return 'gate_binding'
    error=access_context(p,c)
    if error:return error
    if (a['control_epoch'],a['effective_version'])!=(control['control_epoch'],control['effective_version']):return 'access_control'
    if (a['purpose']=='cancel_only')!=(plan['basis']['kind']=='scope'):return 'purpose_basis'
    if a['purpose']=='cancel_only' and plan['basis']['record_ref']!=S.eref(e):return 'assessment_basis'
    if not int(a['selected_tick_ns'])<=int(plan['selected_tick_ns'])<=now<int(plan['expires_tick_ns'])<=int(a['expires_tick_ns'])<=int(body['lease_until_tick_ns']):return 'access_plan_window'
    if e is not None and int(plan['expires_tick_ns'])>int(e['expires_tick_ns']):return 'assessment_plan_window'
    error=S.open_error(a,e,c['scope_context'],now)
    if error:return error
    if a['purpose']=='ordinary':
        error=L.safety_error(c['stored_resource_evidence'],c)
        if error:return error
    legacy=copy.deepcopy(c);legacy['resources_clear']=True
    return O.plan_error(plan,legacy,now)
def dispatch_error(d,p,c,now):
    if not valid('OpenDispatch',d):return 'schema'
    error=proposal_error(p,c,now)
    if error:return error
    legacy=copy.deepcopy(c);legacy['resources_clear']=True
    return O.dispatch_error(d,p['plan'],legacy,now)
def evidence_error(e,d,p,c,now):
    if not valid('OpenAckEvidence',e):return 'schema'
    error=dispatch_error(d,p,c,now)
    if error:return error
    legacy=copy.deepcopy(c);legacy['resources_clear']=True
    error=O.evidence_error(e,d,p['plan'],legacy,now)
    if error:return error
    return S.open_ack_error(d['frame'],e['frame'],c['scope_context'],now)
def adoption_error(t,e,d,p,c,now):
    if not valid('OpenAdoption',t):return 'schema'
    error=evidence_error(e,d,p,c,now)
    if error:return error
    if not O.intact(t,'adoption_digest') or t!=c['stored_adoption']:return 'adoption_source'
    body=p['plan']['body'];a=body['gate_access'];assessment=body['protection_assessment']
    if t['purpose']!=a['purpose'] or t['proposal_ref']!=proposal_ref(p):return 'adoption_proposal'
    if t['dispatch_ref']!=O.reference(d,'dispatch_id','dispatch_digest') or t['evidence_ref']!=O.reference(e,'evidence_id','evidence_digest'):return 'adoption_evidence'
    if t['gate_access_ref']!=S.aref(a) or t['protection_assessment_ref']!=(S.eref(assessment) if assessment else None):return 'adoption_access'
    if t['eligibility_refs']!=p['eligibility_refs']:return 'adoption_eligibility'
    before,after=p['control_before'],t['control_after'];g,h=p['gate_before'],t['gate_after']
    if L.key(before)!=L.key(after):return 'control_transfer'
    if any(g[k]!=h[k] for k in ('binding','gate_revision','gate_token','barrier_id','lease_until_tick_ns')):return 'gate_transition'
    if h['activation_id']!=t['commit_id'] or not successor(before,after) or not successor(g,h):return 'storage_successor'
    if not int(e['received_tick_ns'])<=int(t['committed_tick_ns'])<=now:return 'adoption_time'
    if not c['ack_durable'] or c['stored_evidence']!=e:return 'ack_not_durable'
    return None
def current_error(t,p,c,now):
    if not valid('OpenAdoption',t) or not valid('OpenProposal',p):return 'schema'
    if not c['adoption_committed'] or not c['ack_durable']:return 'not_committed'
    if t!=c['stored_adoption'] or p!=c['stored_proposal'] or not O.intact(t,'adoption_digest') or not O.intact(p,'proposal_digest'):return 'adoption_source'
    if t['proposal_ref']!=proposal_ref(p) or t['eligibility_refs']!=p['eligibility_refs']:return 'adoption_proposal'
    a=p['plan']['body']['gate_access']
    if t['purpose']!=a['purpose'] or t['gate_access_ref']!=S.aref(a):return 'adoption_access'
    error=committed_chain_error(t,p,c)
    if error:return error
    if c['eligibility_refs']!=t['eligibility_refs'] or c['binding']!=p['plan']['binding']:return 'eligibility_changed'
    if not all(c[k] for k in ('storage_healthy','runtime_current','basis_valid','barrier_valid','authority_current')) or c['protected']:return 'unavailable'
    if c['control_projection']!=t['control_after'] or c['gate_projection']!=t['gate_after']:return 'post_state_changed'
    if c['state_refs']['control']!=t['control_after']['record_ref'] or c['state_refs']['gate']!=t['gate_after']['record_ref'] or c['state_refs']['authorization']!=t['eligibility_refs']['authorization']:return 'post_state_refs'
    if not int(t['committed_tick_ns'])<=now<int(p['plan']['expires_tick_ns']):return 'expired'
    if any(c['snapshots'][k]!=p['plan']['body'][k] for k in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot')):return 'snapshot_changed'
    error=access_context(p,c) or S.current_error(a,c['scope_context'],now)
    if error:return error
    if a['purpose']=='ordinary':return L.safety_error(c['stored_resource_evidence'],c)
    return S.assessment_error(a,c['current_assessment'],c['scope_context'],now)

def committed_chain_error(t,p,c):
    """复核不可变采用链；不把提交前投影冒充当前投影或重新签发资格。"""
    plan=p['plan'];body=plan['body'];d=c['stored_dispatch'];e=c['stored_evidence']
    if not valid('OpenDispatch',d) or not valid('OpenAckEvidence',e):return 'chain_schema'
    if any(not O.intact(v,f) for v,f in ((plan,'plan_digest'),(d,'dispatch_digest'),(e,'evidence_digest'))):return 'chain_digest'
    pr=O.reference(plan,'plan_id','plan_digest');dr=O.reference(d,'dispatch_id','dispatch_digest');er=O.reference(e,'evidence_id','evidence_digest')
    if d['plan_ref']!=pr or e['plan_ref']!=pr or e['dispatch_ref']!=dr or t['dispatch_ref']!=dr or t['evidence_ref']!=er:return 'chain_ref'
    sent=d['frame'];ack=e['frame'];out=ack['body']
    if sent['body']!=body or any(f[k]!=plan['binding'][k] for f in (sent,ack) for k in O.FRAME_BINDING) or ack['reply_to']!=sent['message_id']:return 'chain_frame'
    if any(out[k]!=body[k] for k in ('gate_token','gate_revision')) or out['gate_access_ref']!=t['gate_access_ref']:return 'chain_echo'
    for prefix in ('run_deny','command_deny'):
        if any(out[prefix+'_snapshot_'+suffix]!=body[prefix+'_snapshot']['snapshot_'+suffix] for suffix in ('revision','digest')):return 'chain_echo'
    time=body['reference_time_snapshot']
    if out['reference_time_snapshot_ref']!=dict(id=time['snapshot_id'],revision=time['snapshot_revision'],digest=time['snapshot_digest']):return 'chain_echo'
    assessment=body['protection_assessment']
    if t['protection_assessment_ref']!=(S.eref(assessment) if assessment else None):return 'chain_assessment'
    if not int(plan['selected_tick_ns'])<=int(d['reserved_tick_ns'])<=int(e['received_tick_ns'])<=int(t['committed_tick_ns'])<int(plan['expires_tick_ns']):return 'chain_time'
    before,after=p['control_before'],t['control_after'];g,h=p['gate_before'],t['gate_after']
    if L.key(before)!=L.key(after) or h['activation_id']!=t['commit_id'] or not successor(before,after) or not successor(g,h):return 'chain_transition'
    if any(g[k]!=h[k] for k in ('binding','gate_revision','gate_token','barrier_id','lease_until_tick_ns')):return 'chain_transition'
    return None
