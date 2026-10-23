"""开放计划原件关联参考判定；可信上下文为人工夹具，不提供真实授权。"""
import hashlib
import rfc8785


def digest(value):
    return 'sha256:'+hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def seal(value, field):
    value[field]=digest({k:v for k,v in value.items() if k!=field})
    return value


def intact(value, field):
    return value[field]==digest({k:v for k,v in value.items() if k!=field})


def reference(value, identity, field):
    return dict(id=value[identity],revision=value['revision'],digest=value[field])


FRAME_BINDING=('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest')


def plan_error(plan, context, now):
    if not intact(plan,'plan_digest'):return 'digest'
    if plan!=context['stored_plan']:return 'stored_plan'
    if plan['binding']!=context['binding']:return 'binding'
    if plan['state_refs']!=context['state_refs'] or plan['basis']!=context['basis']:return 'state_changed'
    if any(not context[k] for k in ('storage_healthy','runtime_current','basis_valid','barrier_valid','resources_clear','authority_current')):
        return 'unavailable'
    if context['protected']:return 'protected'
    body=plan['body'];binding=plan['binding'];scope=binding['scope']
    if any(body[k]!=binding[k] for k in ('device_session_id','clock_domain_id','descriptor_digest')):return 'body_binding'
    if any(body[k]!=context['control'][k] for k in ('control_epoch','control_version','gate_revision','authorization_revision','gate_token','barrier_id')):
        return 'control_binding'
    if not int(plan['selected_tick_ns'])<=now<int(plan['expires_tick_ns'])<=int(body['lease_until_tick_ns']):return 'expired'
    if int(body['lease_until_tick_ns'])>int(context['max_lease_tick_ns']):return 'lease_limit'
    for key in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot'):
        if not intact(body[key],'snapshot_digest'):return 'snapshot_digest'
        if body[key]!=context['snapshots'][key]:return 'snapshot_changed'
    run,command,time=(body[k] for k in ('run_deny_snapshot','command_deny_snapshot','reference_time_snapshot'))
    if run['controller_scope']!=scope or command['scope']!=scope or command['device_id']!=binding['device_id']:return 'snapshot_scope'
    domain=time['domain']
    if any(domain[k]!=scope[k] for k in scope) or any(domain[k]!=binding[k] for k in ('clock_domain_id','descriptor_digest')):
        return 'time_domain'
    return None


def dispatch_error(dispatch, plan, context, now):
    error=plan_error(plan,context,now)
    if error:return error
    if not intact(dispatch,'dispatch_digest'):return 'digest'
    if dispatch!=context['stored_dispatch']:return 'stored_dispatch'
    if dispatch['plan_ref']!=reference(plan,'plan_id','plan_digest'):return 'plan_ref'
    frame=dispatch['frame']
    if any(frame[k]!=plan['binding'][k] for k in FRAME_BINDING) or frame['body']!=plan['body']:return 'frame_binding'
    if frame['message_id']!=context['outbound_message_id'] or frame['seq']!=context['outbound_seq']:return 'outbound_identity'
    if not int(plan['selected_tick_ns'])<=int(dispatch['reserved_tick_ns'])<=now:return 'dispatch_time'
    return None


def evidence_error(evidence, dispatch, plan, context, now):
    error=dispatch_error(dispatch,plan,context,now)
    if error:return error
    if not intact(evidence,'evidence_digest'):return 'digest'
    if evidence['plan_ref']!=dispatch['plan_ref'] or evidence['dispatch_ref']!=reference(dispatch,'dispatch_id','dispatch_digest'):
        return 'evidence_ref'
    if (evidence['observer_receipt_ref']!=context['observer_receipt_ref'] or evidence['frame']!=context['received_ack'] or
        evidence['received_tick_ns']!=context['observer_received_tick_ns'] or not context['observer_verified']):
        return 'observer'
    frame=evidence['frame'];body=frame['body'];sent=dispatch['frame'];original=plan['body']
    if any(frame[k]!=plan['binding'][k] for k in FRAME_BINDING) or frame['reply_to']!=sent['message_id']:return 'ack_binding'
    if frame['seq']!=context['inbound_seq'] or frame['message_id']!=context['inbound_message_id']:return 'inbound_identity'
    if any(body[k]!=original[k] for k in ('gate_token','gate_revision')):return 'ack_gate'
    for prefix in ('run_deny','command_deny'):
        for suffix in ('revision','digest'):
            if body[prefix+'_snapshot_'+suffix]!=original[prefix+'_snapshot']['snapshot_'+suffix]:return 'ack_snapshot'
    time=original['reference_time_snapshot']
    if body['reference_time_snapshot_ref']!=dict(id=time['snapshot_id'],revision=time['snapshot_revision'],digest=time['snapshot_digest']):return 'ack_snapshot'
    if not int(dispatch['reserved_tick_ns'])<=int(evidence['received_tick_ns'])<=now:return 'ack_time'
    return None


def ready_error(ready, evidence, dispatch, plan, context, now):
    error=evidence_error(evidence,dispatch,plan,context,now)
    if error:return error
    if not intact(ready,'ready_digest'):return 'digest'
    if ready['plan_ref']!=dispatch['plan_ref'] or ready['dispatch_ref']!=evidence['dispatch_ref'] or ready['evidence_ref']!=reference(evidence,'evidence_id','evidence_digest'):
        return 'ready_ref'
    if ready['state_refs']!=plan['state_refs']:return 'ready_state'
    if not int(evidence['received_tick_ns'])<=int(ready['committed_tick_ns'])<=now:return 'ready_time'
    if (not context['ack_durable'] or not context['ready_transaction_committed'] or
        context['stored_evidence']!=evidence or context['stored_ready']!=ready):return 'not_committed'
    return None
