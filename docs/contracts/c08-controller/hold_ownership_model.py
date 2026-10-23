"""占用原件与当前主体的合成关联判定；必须先按对应Schema验证。"""
import open_plan_model as O

def identity_error(identity,context):
    expected=context['executions'].get(identity['source_ref']['id'])
    if expected is None or identity!=expected:return 'execution_source'
    # 取消的source是取消请求及其唯一Plan，不从父命令actor派生。
    if identity['origin']=='manual' and identity['requester']['kind']!='human':return 'principal_kind'
    if identity['origin']=='automation' and identity['requester']['kind']!='service':return 'principal_kind'
    return None

def ownership_error(value,context):
    if not O.intact(value,'ownership_digest'):return 'ownership_digest'
    stored=context['ownerships'].get(value['hold_ref']['id'])
    if stored!=value:return 'ownership_source'
    receipt=context['ownership_receipts'].get(value['source_receipt_ref']['id'])
    expected={k:value[k] for k in ('scope','device_id','hold_ref','identity','control_authority_ref','control_epoch',
      'effective_version','clock_domain_id','descriptor_digest','acquired_tick_ns')}
    if receipt is None or receipt['ref']!=value['source_receipt_ref'] or receipt['content']!=expected:return 'ownership_receipt'
    if value['scope']!=context['binding']['scope'] or value['device_id']!=context['binding']['device_id']:return 'ownership_scope'
    return identity_error(value['identity'],context)

def authority_error(identity,ownership,context):
    control=context['control_projection']
    if control['pending_operation_id'] is not None:return 'pending_control'
    if (ownership['control_authority_ref'],ownership['control_epoch'],ownership['effective_version'])!=(
        control['authority_ref'],control['control_epoch'],control['effective_version']):return 'ownership_control'
    if ownership['identity']!=identity:return 'ownership_execution'
    if identity['origin']=='manual':
        principal={k:identity['requester'][k] for k in ('issuer_id','issuer_epoch','principal_id')}
        if control['mode']!='manual' or control['holder']!=principal:return 'manual_holder'
    elif control['mode']!='automatic' or control['holder'] is not None:return 'automation_mode'
    return None

def resources_error(observations,context):
    # 完整集合、异常分类及安全代次仍由开放模型负责，此处增加其缺少的不可变来源关联。
    ids=[x['hold_ref']['id'] for x in observations]
    if len(set(ids))!=len(ids) or set(ids)!=set(context['risk_hold_ids']):return 'ownership_hold_set'
    for observation in observations:
        owner=context['ownerships'].get(observation['hold_ref']['id'])
        if owner is None:return 'ownership_missing'
        error=ownership_error(owner,context)
        if error:return error
        if observation['hold_ref']!=owner['hold_ref'] or observation['owner_ref']!=O.reference(owner,'ownership_id','ownership_digest'):
            return 'ownership_observation'
        if observation['control_authority_ref']!=owner['control_authority_ref']:return 'ownership_relabelled'
        error=authority_error(owner['identity'],owner,context)
        if error:return error
    return None

def permit_error(permit,context,now):
    if not O.intact(permit,'authority_digest'):return 'permit_digest'
    if permit['binding']!=context['binding']:return 'permit_binding'
    error=identity_error(permit['identity'],context)
    if error:return error
    owner=context['ownerships'].get(permit['hold_ref']['id'])
    if owner is None:return 'ownership_missing'
    error=ownership_error(owner,context)
    if error:return error
    if permit['hold_ref']!=owner['hold_ref'] or permit['ownership_ref']!=O.reference(owner,'ownership_id','ownership_digest'):
        return 'permit_owner'
    error=authority_error(permit['identity'],owner,context)
    if error:return error
    control=context['control_projection']
    if (permit['control_authority_ref'],permit['control_epoch'],permit['effective_version'])!=(
        control['authority_ref'],control['control_epoch'],control['effective_version']):return 'permit_control'
    if permit['authorization_ref']!=context['authorization_ref']:return 'permit_authorization'
    # 原Guard及Packet必须由精确提供者给出，不能用任意非空BODY代替关联。
    expected={k:permit[k] for k in ('permit_id','issued_revision','identity','binding','hold_ref','ownership_ref',
      'control_authority_ref','control_epoch','effective_version','authorization_ref','packet_ref','ordinal','selected_tick_ns','expires_tick_ns')}
    guard=context['guard_receipts'].get(permit['guard_ref']['id'])
    if guard is None or guard['ref']!=permit['guard_ref'] or guard['content']!=expected:return 'permit_guard'
    if (owner['clock_domain_id'],owner['descriptor_digest'])!=(permit['binding']['clock_domain_id'],permit['binding']['descriptor_digest']):return 'ownership_clock'
    if not int(owner['acquired_tick_ns'])<=int(permit['selected_tick_ns'])<=now<int(permit['expires_tick_ns']):return 'permit_expired'
    if permit['expires_tick_ns']!=context['send_window_end']:return 'permit_window'
    # 这里只证明主体/原件投影，None绝不代表完整发送通过。
    return None
