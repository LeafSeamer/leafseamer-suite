"""跨原件绑定检查，返回值不授最终发送资格；真实提供者和SQL写集仍须实现。"""
import hashlib
import rfc8785
from jsonschema import Draft202012Validator
import build_final_admission as G
SCHEMA=G.build()
def need(v,reason):
    if not v:raise ValueError(reason)
def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def seal(v,key='seal_digest'):return dict(v,**{key:digest({k:x for k,x in v.items() if k!=key})})
def validate(name,v):Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']}).validate(v)
def reference(v):return dict(id=v['seal_id'],revision=v['revision'],digest=v['seal_digest'])
def projection_digest(v):return digest({k:x for k,x in v.items() if k!='ref'})

def verify(v,originals,cut):
    """originals由本地可信解析器按完整Ref取得；本检查不证明解析器真实性或授权决策。"""
    validate('Seal',v);need(seal(v)==v,'seal_digest')
    binding=v['binding'];identity=v['identity'];refs=v['inputs'];kind=identity['kind']
    required=set(G.COMMON)|(set(G.CANCEL) if kind=='cancel' else set())
    need(set(originals)==required,'original_roles')
    selected=int(v['selected_tick_ns']);now=int(v['sealed_tick_ns']);window=v['send_window']
    need(cut['transaction_id']==v['transaction_id'] and cut['binding']==binding,'transaction_binding')
    need(cut['command_state_ref']==v['command_state_ref'] and cut['identity']==identity,'command_prestate')
    need(selected==cut['selected_tick_ns'] and now==cut['sealed_tick_ns'] and selected<=now,'sampling_order')
    need(int(v['issued_revision'])==cut['previous_issue_revision']+1,'global_issue_successor')
    need(v['issued_revision']!='0','issue_zero')
    for role in required:
        source=originals[role]
        validate('Original_'+role,source)
        need(source['ref']==refs[role],'original_ref_'+role)
        need(source['scope']==binding['scope'],'original_scope_'+role)
        need(source['transaction_id']==v['transaction_id'],'original_cut_'+role)
        need(source['ref']['digest']==projection_digest(source),'original_digest_'+role)
        need(source['body']['binding']==binding and source['body']['identity']==identity,'projection_subject_'+role)
        # 投影Ref包括原source_ref和读取事务，不重定义原领域self-digest。
        need(source['source_ref'] is not None,'source_missing_'+role)
        validate('Ref',source['source_ref'])
    body=lambda role:originals[role]['body']
    origin=body('origin');need(origin['identity']==identity and origin['command_state_ref']==v['command_state_ref'],'origin_subject')
    owner=body('ownership');pa=body('permit_authority');access=body('gate_access');encoding=body('encoding')
    need(owner['identity']==identity and owner['hold_ref']==v['hold_ref'],'ownership_subject')
    need(owner['binding']==binding,'ownership_binding')
    need(pa['binding']==access['binding']==encoding['binding']==binding,'permit_binding')
    need(pa['identity']==identity and pa['hold_ref']==v['hold_ref'],'permit_subject')
    for name in ('permit_id','issued_revision','ordinal','transmission_id'):
        need(pa[name]==v[name],'permit_'+name)
    for field,role in (('ownership_ref','ownership'),('control_authority_ref','control'),('authorization_ref','authorization'),('guard_ref','guard')):
        need(pa[field]==originals[role]['source_ref'],'permit_'+field)
    need(pa['packet_ref']==v['encoding_packet_ref']==encoding['packet_record_ref'],'encoding_packet_record')
    need(encoding['packet_ref']==v['packet_ref'] and encoding['identity']==identity,'encoding_subject')
    need(body('capability')['encoding_source_ref']==originals['encoding']['source_ref'],'capability_encoding')
    need(body('control')['pending_operation_id'] is None,'pending_control')
    control=body('control')
    need(owner['control_authority_ref']==pa['control_authority_ref']==access['control_authority_ref']==originals['control']['source_ref'],'control_original')
    need(owner['control_epoch']==pa['control_epoch']==access['control_epoch']==control['control_epoch'],'control_epoch')
    need(owner['effective_version']==pa['effective_version']==access['effective_version']==control['effective_version'],'control_version')
    if identity['origin']=='manual':
        need(control['mode']=='manual' and control['holder']==identity['requester'],'manual_holder')
    else:need(control['mode']=='automatic' and control['holder'] is None,'automatic_control')
    for name in ('authorization','resource_safety','gate_safety'):
        need(access[name+'_ref']==originals[name]['source_ref'],'access_'+name)
    need(body('gate_commit')['access_ref']==originals['gate_access']['source_ref'],'gate_commit_access')
    need(access['purpose']==('ordinary' if kind=='ordinary' else 'cancel_only'),'gate_purpose')
    before=body('resource_before');after=body('resource_after')
    need(before['binding']==after['binding']==binding,'resource_binding')
    def inventory(r):
        rows=r['holds'];need(len(rows)<=65536 and len({x['hold_ref']['id'] for x in rows})==len(rows),'resource_duplicate')
        return {x['hold_ref']['id']:x for x in rows}
    old=inventory(before);new=inventory(after);hid=v['hold_ref']['id']
    if v['hold_transition']=='create':
        need(kind=='ordinary' and v['transmission_kind']=='initial' and hid not in old,'hold_create_kind')
        need(set(new)==set(old)|{hid} and all(new[k]==x for k,x in old.items()),'resource_create_delta')
        need(originals['resource_before']['source_ref']!=originals['resource_after']['source_ref'],'resource_snapshot_identity')
    else:need(old==new and hid in old,'resource_reuse_delta')
    need(new[hid]==dict(hold_ref=v['hold_ref'],ownership_ref=originals['ownership']['source_ref'],classification='active'),'resource_owner')
    need(before['resource_safety_ref']==after['resource_safety_ref']==originals['resource_safety']['source_ref'],'resource_safety_change')
    guard=body('guard');budget=body('budget');time=body('time')
    for role,b in (('guard',guard),('budget',budget),('time',time)):
        need(b['binding']==binding and b['permit_id']==v['permit_id'] and b['issued_revision']==v['issued_revision'],'issue_binding_'+role)
    need(guard['identity']==identity and guard['packet_ref']==v['packet_ref'],'guard_subject')
    need(guard['gate_access_ref']==originals['gate_access']['source_ref'] and guard['ownership_ref']==originals['ownership']['source_ref'],'guard_authority')
    need(budget['charge_kind']=='new_transmission' and budget['charged_permit_id']==v['permit_id'],'fresh_budget_charge')
    need(time['identity']==identity and time['clock_domain_id']==binding['clock_domain_id'] and time['descriptor_digest']==binding['descriptor_digest'],'time_subject')
    lower=max(int(body(r)['not_before_tick_ns']) for r in ('authorization','gate_access','guard','budget','time'))
    upper=min(int(body(r)['before_tick_ns']) for r in ('authorization','gate_access','guard','budget','time'))
    for role in ('authorization','gate_access','budget'):
        need(int(body(role)['not_before_tick_ns'])<=now<int(body(role)['before_tick_ns']),'current_validity_'+role)
    need(window==dict(not_before_tick_ns=str(lower),before_tick_ns=str(upper)) and lower<upper and selected<=now<upper,'window_intersection')
    # 允许在not_before之前封存；最终入流和worker写必须另查当前时刻。
    need(int(encoding['received_tick_ns'])<=selected<=now<int(encoding['expires_tick_ns']),'encoding_ttl')
    for role in ('run_deny','command_deny'):
        need(body(role)['binding']==binding and body(role)['identity']==identity,'deny_subject_'+role)
    if kind=='cancel':
        need(access['restricted_identity']==identity,'cancel_access_subject')
        need(body('ordinary_closure')['identity']==identity and body('ordinary_closure')['stage']=='ordinary','cancel_closure')
        assessment=body('protection_assessment');dependency=body('primitive_dependency')
        need(assessment['identity']==identity and assessment['resource_ref']==originals['resource_after']['source_ref'],'cancel_assessment')
        need(dependency['execution_ref']==identity['execution_ref'] and dependency['transmission_id']==v['transmission_id'],'cancel_dependency')
        need(guard['protection_assessment_ref']==originals['protection_assessment']['source_ref'],'cancel_guard_assessment')
    else:need(access['restricted_identity'] is None and guard['protection_assessment_ref'] is None,'ordinary_scope')
    if v['transmission_kind']=='protocol_resend':
        prior=cut['previous_permit'];validate('Seal',prior);need(prior==seal(prior),'prior_digest')
        need(v['previous_permit_ref']==reference(prior),'resend_previous')
        for name in ('binding','identity','packet_ref','encoding_packet_ref','hold_ref'):
            need(v[name]==prior[name],'resend_fixed_'+name)
        need(v['permit_id']!=prior['permit_id'] and v['transmission_id']!=prior['transmission_id'] and int(v['ordinal'])==int(prior['ordinal'])+1,'resend_ordinal')
        need(int(v['issued_revision'])>int(prior['issued_revision']),'resend_issue')
        for role in ('guard','budget','permit_authority'):
            need(originals[role]['source_ref']['id']!=cut['previous_sources'][role]['id'],'resend_fresh_'+role)
    return 'cross_object_binding_valid'

def observe(v,o):
    validate('Seal',v);validate('CommitObservation',o)
    need(seal(v)==v and seal(o,'observation_digest')==o,'observation_digest')
    need(o['seal_ref']==reference(v) and o['transaction_id']==v['transaction_id'] and o['scope']==v['binding']['scope'] and o['permit_id']==v['permit_id'],'observation_binding')
    need(int(o['observed_tick_ns'])>=int(v['sealed_tick_ns']),'observation_order')
    return {'committed':'committed_requires_recheck','rolled_back':'no_issue','unknown':'quarantine_lookup_only'}[o['outcome']]
