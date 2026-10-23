"""两阶段开放资格及资源分类参考模型；当前原件和提供者均由合成上下文给定。"""
import copy
import open_plan_model as O

def key(control):
    return {k:control[k] for k in ('authority_ref','control_epoch','effective_version','mode','holder','pending_operation_id')}

def safety_error(evidence,context):
    if not O.intact(evidence,'evidence_digest'):return 'resource_digest'
    if evidence!=context['stored_resource_evidence'] or evidence['provider_receipt_ref']!=context['resource_provider_receipt_ref']:
        return 'resource_provider'
    if evidence['device_id']!=context['binding']['device_id'] or evidence['observed_resource_ref']!=context['state_refs']['resource']:
        return 'resource_snapshot'
    if evidence['resource_safety_ref']!=context['eligibility_refs']['resource_safety'] or evidence['control_authority_ref']!=context['eligibility_refs']['control_authority']:
        return 'resource_generation'
    holds=evidence['holds'];expected=context['current_holds']
    ids=[h['hold_ref']['id'] for h in holds]
    if len(ids)!=len(set(ids)) or sorted(holds,key=lambda h:h['hold_ref']['id'])!=sorted(expected,key=lambda h:h['hold_ref']['id']):
        return 'resource_hold_set'
    if any(h['state']!='active' or h['control_authority_ref']!=evidence['control_authority_ref'] for h in holds):return 'resource_blocked'
    return None

def proposal_error(proposal,context,now):
    if not O.intact(proposal,'proposal_digest'):return 'proposal_digest'
    if proposal!=context['stored_proposal']:return 'stored_proposal'
    if proposal['eligibility_refs']!=context['eligibility_refs']:return 'eligibility_changed'
    p=proposal['plan'];c=proposal['control_before'];g=proposal['gate_before']
    if c!=context['control_projection'] or g!=context['gate_projection']:return 'projection_changed'
    if c['record_ref']!=p['state_refs']['control'] or g['record_ref']!=p['state_refs']['gate']:return 'pre_state_refs'
    if c['authority_ref']!=proposal['eligibility_refs']['control_authority'] or p['state_refs']['authorization']!=proposal['eligibility_refs']['authorization']:
        return 'authority_refs'
    if c['pending_operation_id'] is not None or c['gate_state']=='ready' or g['phase']!='fenced' or g['ready_activation_id'] is not None:return 'pre_state'
    if (c['mode']=='automatic')!=(c['holder'] is None):return 'holder_mode'
    b=p['body']
    if (c['control_epoch'],c['effective_version'])!=(b['control_epoch'],b['control_version']):return 'control_binding'
    if g['binding']!=p['binding'] or any(g[x]!=b[x] for x in ('gate_revision','gate_token','barrier_id','lease_until_tick_ns')):return 'gate_binding'
    error=safety_error(context['stored_resource_evidence'],context)
    if error:return error
    old=copy.deepcopy(context);old['resources_clear']=True
    return O.plan_error(p,old,now)

def transition_error(transition,evidence,dispatch,proposal,context,now):
    error=proposal_error(proposal,context,now)
    if error:return error
    if not O.intact(transition,'transition_digest'):return 'transition_digest'
    # Proposal与Plan共用id/revision，但Ref必须绑定新包络摘要，不能借旧Plan摘要。
    expected=dict(id=proposal['plan']['plan_id'],revision='1',digest=proposal['proposal_digest'])
    if transition['proposal_ref']!=expected:return 'proposal_ref'
    if transition['eligibility_refs']!=proposal['eligibility_refs']:return 'transition_eligibility'
    before_c=proposal['control_before'];before_g=proposal['gate_before'];after_c=transition['control_after'];after_g=transition['gate_after']
    if key(after_c)!=key(before_c) or after_c['gate_state']!='ready':return 'control_transition'
    if any(after_g[k]!=before_g[k] for k in ('binding','gate_revision','gate_token','barrier_id','lease_until_tick_ns')):
        return 'gate_transition'
    if after_g['phase']!='ready' or after_g['ready_activation_id']!=transition['ready']['ready_id']:return 'gate_activation'
    for before,after in ((before_c,after_c),(before_g,after_g)):
        a,b=before['record_ref'],after['record_ref']
        if b['id']!=a['id'] or int(a['revision'])>=10**20-1 or int(b['revision'])!=int(a['revision'])+1 or b['digest']==a['digest']:
            return 'projection_successor'
    old=copy.deepcopy(context);old['resources_clear']=True
    old['stored_ready']=transition['ready']
    # 这里只核验待提交完整写集；真实COMMIT另由publish负责，不伪造durable批准。
    old['ready_transaction_committed']=True
    error=O.ready_error(transition['ready'],evidence,dispatch,proposal['plan'],old,now)
    if error:return error
    if transition!=context['stored_transition']:return 'stored_transition'
    return None

def current_error(transition,proposal,context,now):
    if not context['ready_transaction_committed'] or not context['ack_durable']:return 'not_committed'
    if transition!=context['stored_transition'] or proposal!=context['stored_proposal']:return 'stored_transition'
    if not O.intact(transition,'transition_digest') or not O.intact(proposal,'proposal_digest'):return 'digest'
    if not all(context[k] for k in ('storage_healthy','runtime_current','authority_current','basis_valid','barrier_valid')) or context['protected']:
        return 'unavailable'
    if context['binding']!=proposal['plan']['binding']:return 'binding'
    if context['eligibility_refs']!=transition['eligibility_refs']:return 'eligibility_changed'
    if (context['state_refs']['control']!=context['control_projection']['record_ref'] or
        context['state_refs']['gate']!=context['gate_projection']['record_ref'] or
        context['state_refs']['authorization']!=context['eligibility_refs']['authorization']):return 'current_refs'
    original=transition['control_after']['record_ref'];current=context['control_projection']['record_ref']
    if (current['id']!=original['id'] or int(current['revision'])<int(original['revision']) or
        (current['revision']==original['revision'] and current!=original)):return 'control_history'
    if key(context['control_projection'])!=key(transition['control_after']):return 'control_changed'
    if context['control_projection']['gate_state']!='ready':return 'control_not_ready'
    if context['gate_projection']!=transition['gate_after']:return 'gate_changed'
    if not int(transition['ready']['committed_tick_ns'])<=now<int(proposal['plan']['expires_tick_ns']):return 'expired'
    for name in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot'):
        if context['snapshots'][name]!=proposal['plan']['body'][name]:return 'snapshot_changed'
    # 当前资源全量证据会随正常分配更新；安全代次不变不等于免除当前全集核验。
    return safety_error(context['stored_resource_evidence'],context)

def publish(transition,evidence,dispatch,proposal,context,now,commit_result='committed',fault=None,visible_tick=None):
    error=transition_error(transition,evidence,dispatch,proposal,context,now)
    if error:return copy.deepcopy(context),error
    if commit_result!='committed':
        result=copy.deepcopy(context);result['ready_transaction_committed']=False;result['protected']=True
        return result,'commit_uncertain' if commit_result=='unknown' else 'commit_failed'
    result=copy.deepcopy(context)
    updates=[('control_projection',transition['control_after']),('gate_projection',transition['gate_after']),
             ('ready_transaction_committed',True)]
    for n,(k,v) in enumerate(updates):
        result[k]=copy.deepcopy(v)
        if fault==n:return copy.deepcopy(context),'rollback'
    result['state_refs']['control']=copy.deepcopy(transition['control_after']['record_ref'])
    result['state_refs']['gate']=copy.deepcopy(transition['gate_after']['record_ref'])
    if visible_tick is not None and visible_tick<now:
        result['protected']=True
        return result,'clock_regressed'
    return result,current_error(transition,proposal,result,now if visible_tick is None else visible_tick)
