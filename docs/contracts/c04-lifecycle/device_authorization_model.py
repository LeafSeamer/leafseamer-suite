"""设备授权状态的纯转换模型；原件提供者、SQLite和OPEN执行均不在此处。"""
import copy
from jsonschema import Draft202012Validator
import build_device_authorization as B
import open_authorization_requirement as R
MAX=10**20-1
def need(value,reason):
    if not value:raise ValueError(reason)
def validate(name,value):Draft202012Validator({'$defs':B.build()['$defs'],'$ref':'#/$defs/'+name}).validate(value)
def seal(value,field):
    result=copy.deepcopy(value);result[field]=R.digest({k:v for k,v in result.items() if k!=field});return result
def reference(value,kind):return dict(id=value[kind+'_id'],revision=value['revision'],digest=value[kind+'_digest'])
def state_id(context,revision):return 'device_auth_'+R.digest(dict(scope=context['scope'],device_id=context['device_id']))[7:]+'_r'+revision
def state(value):
    validate('State',value);need(seal(value,'state_digest')==value,'state_digest');need(0<int(value['revision'])<=MAX,'state_revision')
    c=value['context'];need(value['state_id']==state_id(c,value['revision']),'state_identity')
    parent=value['parent_ref']
    need(parent is None if value['revision']=='1' else parent is not None and parent['id']==state_id(c,str(int(value['revision'])-1)) and int(parent['revision'])+1==int(value['revision']),'state_parent')
    need(value['reasons']==sorted(value['reasons']),'state_reason_order')
    if value['status']=='policy_selected':
        need(c['evaluator_lineage']['principal_kind']=='service','evaluator_service')
        if c['purpose']=='cancel_only':need(c['cancel_scope_ref'] is not None and c['cancel_lineage_ref'] is not None,'cancel_scope')
        elif c['mode']=='manual':
            h=c['holder_lineage'];need(h is not None and h['principal_kind']=='human' and h['principal']==c['holder'],'holder_lineage')
        else:need(c['holder_lineage'] is None,'automatic_holder_lineage')
def transition(previous,context,status,reasons,*,recovery_ref=None):
    validate('Context',context);reasons=sorted(reasons)
    if previous is None:
        need(status=='protected' and recovery_ref is None,'initial_protected');revision='1';parent=None
    else:
        state(previous);old=previous['context']
        need((old['scope'],old['device_id'])==(context['scope'],context['device_id']),'state_target')
        if (old,previous['status'],previous['reasons'])==(context,status,reasons):
            need(recovery_ref in (None,previous['recovery_ref']),'recovery_replay_conflict');return copy.deepcopy(previous)
        need(int(previous['revision'])<MAX,'state_revision_exhausted');revision=str(int(previous['revision'])+1);parent=reference(previous,'state')
        if previous['status']=='policy_selected':need(status=='protected' and recovery_ref is None,'semantic_change_requires_protection')
        if status=='policy_selected':need(previous['status']=='protected' and recovery_ref is not None,'recovery_required')
    if status=='protected':need(recovery_ref is None,'protected_no_recovery_claim')
    result=seal(dict(format_version='device-authorization-state/0.1.0-draft.1',state_id=state_id(context,revision),
        revision=revision,context=copy.deepcopy(context),status=status,reasons=reasons,parent_ref=parent,recovery_ref=recovery_ref),'state_digest')
    state(result);return result
def revalidate(previous,context,value,binding,now):
    state(previous);validate('RecoveryAuthorization',value);validate('Binding',binding);validate('Counter',now)
    need(seal(value,'authorization_digest')==value,'revalidation_digest')
    need(previous['status']=='protected' and value['protected_state_ref']==reference(previous,'state'),'revalidation_state')
    need(value['binding']==binding and binding['scope']==context['scope'] and binding['device_id']==context['device_id'],'revalidation_binding')
    need(value['control_authority_ref']==context['control_authority_ref']==previous['context']['control_authority_ref'],'revalidation_authority')
    need(value['proposed_context_digest']==R.digest(context),'revalidation_context')
    need(int(value['issued_tick_ns'])<=int(now)<int(value['expires_tick_ns']),'revalidation_window')
    need(value['evidence_refs']==sorted(value['evidence_refs'],key=lambda x:(x['id'],int(x['revision']),x['digest'])),'revalidation_evidence_order')
    return transition(previous,context,'policy_selected',[],recovery_ref=reference(value,'authorization'))
def evidence(current,value,now):
    state(current);validate('Evidence',value);need(seal(value,'evidence_digest')==value,'evidence_digest')
    need(current['status']=='policy_selected','state_protected');q=value['requirement'];R.validate_requirement(q,now);c=current['context']
    need(value['context_digest']==R.digest(c),'evidence_context')
    need(value['state_ref']==q['authorization_state_ref']==reference(current,'state'),'evidence_state')
    need(q['binding']['scope']==c['scope'] and q['binding']['device_id']==c['device_id'] and q['control_authority_ref']==c['control_authority_ref'],'evidence_target')
    need((q['control_mode'],q['holder'],q['purpose'])==(c['mode'],c['holder'],c['purpose']),'evidence_control')
    need(q['evaluator']['policy_ref']==c['evaluator_policy_ref'],'evidence_policy')
    refs={'evaluator':q['evaluator']['authority_response_ref']}
    if q['purpose']=='cancel_only':
        need(q['cancel_evidence']['protection_scope_ref']==c['cancel_scope_ref'],'evidence_cancel_scope');refs['cancel']=q['cancel_evidence']['cancel_authorization_ref']
    elif q['control_mode']=='manual':
        h=q['holder_evidence'];lineage=c['holder_lineage']
        need((h['principal'],h['session_id'],h['credential_id'])==(lineage['principal'],lineage['session_id'],lineage['credential_id']),'evidence_holder')
        refs['holder']=h['response_ref']
    windows=value['windows'];need([w['role'] for w in windows]==sorted(refs),'evidence_window_roles')
    for w in windows:
        need(w['evidence_ref']==refs[w['role']],'evidence_window_source')
        need(int(w['not_before_tick_ns'])<=int(q['selected_tick_ns'])<=int(now)<int(q['expires_tick_ns'])<=int(w['before_tick_ns']),'evidence_window')
    # 这里只证明合成上下文关系，不返回ready或任何发送许可。
def renewal(current,previous,next_value,now):
    evidence(current,previous,now);evidence(current,next_value,now)
    need(previous['requirement']['binding']==next_value['requirement']['binding'],'renewal_binding')
    need(previous['requirement']['evaluator']['runtime_ref']==next_value['requirement']['evaluator']['runtime_ref'],'renewal_runtime')
    if previous['requirement']['requirement_id']==next_value['requirement']['requirement_id']:need(previous['requirement']==next_value['requirement'],'renewal_requirement_identity')
    if previous['evidence_id']==next_value['evidence_id']:need(previous==next_value,'renewal_identity_conflict')
