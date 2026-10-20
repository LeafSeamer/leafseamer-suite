"""取消保护的合成关联与有限状态参考；无I/O、真实权威或设备发送。"""
import copy
import hashlib
import rfc8785


def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def seal(v,key):v[key]=digest({k:x for k,x in v.items() if k!=key});return v
def ref(v,id_key,digest_key,revision='1'):
    return dict(id=v[id_key],revision=revision,digest=v[digest_key])
def content_ok(v,key):return v[key]==digest({k:x for k,x in v.items() if k!=key})
def ordered(xs,key):return xs==sorted(xs,key=key) and len({key(x) for x in xs})==len(xs)


def snapshot_error(s,c):
    if not content_ok(s,'snapshot_digest'):return 'digest'
    if (s['scope'],s['device_id'])!=(c['scope'],c['device_id']):return 'owner'
    if not ordered(s['entries'],lambda x:x['parent_command_id']):return 'order'
    if s['entries']!=c['expected_entries'] or int(s['snapshot_revision'])!=c['authority_revision']:return 'incomplete'
    if int(s['snapshot_revision'])<c['installed_revision']:return 'stale'
    incoming={x['parent_command_id']:x for x in s['entries']}
    for old in c['installed_entries']:
        new=incoming.get(old['parent_command_id'])
        if not new or new['cancellation_id']!=old['cancellation_id']:return 'regression'
        if int(new['deny_revision'])<int(old['deny_revision']):return 'regression'
        if old['stage']=='all' and new['stage']!='all':return 'regression'
    return None


def cut_error(cut,c):
    if not content_ok(cut,'cut_digest'):return 'digest'
    if cut['binding']!=c['binding']:return 'binding'
    if int(cut['issued_revision'])!=c['issued_revision'] or int(cut['deny_revision'])!=c['deny_revision']:return 'cut'
    if not ordered(cut['targets'],lambda x:x['exit']['writer_exit_id']):return 'order'
    if cut['targets']!=c['expected_targets']:return 'incomplete'
    for t in cut['targets']:
        if not content_ok(t,'target_digest'):return 'target_digest'
        if t['exit']['device_id']!=c['device_id']:return 'owner'
        if not ordered(t['ordinary_attempt_ids'],lambda x:x):return 'order'
        if not ordered(t['cancel_prepare_ids'],lambda x:x):return 'order'
        if not ordered(t['ordinary_transmissions'],lambda x:x['intent']['permit_id']):return 'order'
        if not ordered(t['cancel_transmissions'],lambda x:x['permit_id']):return 'order'
        for tx in t['ordinary_transmissions']:
            i=tx['intent']
            if i['command_id']!=cut['binding']['parent_command_id']:return 'owner'
            if i['attempt_id'] not in t['ordinary_attempt_ids']:return 'attempt'
            if any(i[k]!=t['exit'][k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id',
                    'device_id','device_session_id','clock_domain_id','descriptor_digest')):return 'exit'
        for tx in t['cancel_transmissions']:
            if tx['cancellation_id']!=cut['binding']['cancellation_id'] or tx['parent_command_id']!=cut['binding']['parent_command_id']:return 'owner'
            if tx['exit']!=t['exit']:return 'exit'
        if cut['stage']=='ordinary' and (t['cancel_prepare_ids'] or t['cancel_transmissions']):return 'stage'
    previous=c['previous_cut']
    if cut['stage']=='ordinary':
        if previous is not None or cut['previous_cut_ref'] is not None:return 'stage'
    else:
        if previous is None or previous['stage']!='ordinary':return 'stage'
        if cut['previous_cut_ref']!=ref(previous,'cut_id','cut_digest'):return 'predecessor'
        new={x['exit']['writer_exit_id']:x for x in cut['targets']}
        for old in previous['targets']:
            if old['exit']['writer_exit_id'] not in new:return 'predecessor'
            t=new[old['exit']['writer_exit_id']]
            if any(t[k]!=old[k] for k in ('exit','ordinary_attempt_ids','ordinary_transmissions')):return 'predecessor'
    return None


def ack_error(request,ack,c):
    b=request['body'];a=ack['body'];t=b['target'];exit=t['exit']
    if ack['reply_to']!=request['message_id']:return 'reply'
    if any(ack[k]!=exit[k] or request[k]!=exit[k] for k in
            ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest')):return 'exit'
    if not content_ok(a,'ack_digest'):return 'digest'
    for k in ('operation_id','barrier_id','binding','stage','cut_ref','deny_revision','attempt_binding'):
        if a[k]!=b[k]:return 'binding'
    if a['target_digest']!=t['target_digest']:return 'target'
    if a['ordinary_attempt_ids']!=t['ordinary_attempt_ids'] or a['cancel_prepare_ids']!=t['cancel_prepare_ids']:return 'preparation'
    if [x['intent'] for x in a['ordinary_coverage']]!=t['ordinary_transmissions']:return 'coverage'
    if [x['intent'] for x in a['cancel_coverage']]!=t['cancel_transmissions']:return 'coverage'
    if b['attempt_binding']['target_exit_id']!=exit['writer_exit_id']:return 'exit'
    if b['attempt_binding']['cut_digest']!=b['cut_ref']['digest'] or b['attempt_binding']['cut_id']!=b['cut_ref']['id']:return 'cut'
    if not c['request_tick']<=int(a['effective_tick_ns'])<=c['received_tick']:return 'time'
    if int(a['gate_io_seq'])<=c['last_send_io_seq']:return 'gate_order'
    if b!=c['request_body']:return 'authority'
    for cov in a['ordinary_coverage']+a['cancel_coverage']:
        tx=cov['intent'];pid=tx['intent']['permit_id'] if 'intent' in tx else tx['permit_id']
        disposition=cov['disposition']
        if c['known_dispositions'].get(pid)=='in_flight' and disposition!='in_flight':return 'downgrade'
        if c['known_dispositions'].get(pid)=='unknown' and disposition=='not_sent':return 'downgrade'
        if disposition=='not_sent' and pid not in c['proven_unconsumed']:return 'no_unconsumed_proof'
    return None


def closure_error(value,cut,c):
    if not content_ok(value,'closure_digest'):return 'digest'
    if value['binding']!=cut['binding'] or value['stage']!=cut['stage'] or value['cut_ref']!=ref(cut,'cut_id','cut_digest'):return 'binding'
    if not ordered(value['targets'],lambda x:x['target_exit_id']):return 'order'
    if [(x['target_exit_id'],x['target_digest']) for x in value['targets']]!=[
            (x['exit']['writer_exit_id'],x['target_digest']) for x in cut['targets']]:return 'coverage'
    for t in value['targets']:
        source=c['target_sources'].get(t['target_exit_id'])
        if source!=t:return 'source'
    if value['provider_receipt_ref']!=c['provider_receipt_ref']:return 'provider'
    if cut['stage']=='all' and not c['cancel_issuance_closed']:return 'issuance_open'
    return None


def plan_error(plan,c):
    if not content_ok(plan,'execution_digest'):return 'digest'
    if plan!=c['approved_plan']:return 'authority'
    policy=c['policy']
    if plan['binding']!=c['binding'] or plan['policy_ref']!=ref(policy,'policy_id','policy_digest',policy['revision']):return 'binding'
    if policy['mode']!='cooperative' or plan['binding']['mode']!='cooperative':return 'unsupported'
    if plan['ordinary_closure_ref']!=c['ordinary_closure_ref'] or not c['ordinary_closure_valid']:return 'ordinary_open'
    if plan['resource_keys']!=policy['resource_keys'] or plan['protected_hold_ref']!=c['protected_hold_ref']:return 'resources'
    if plan['requester']!=c['requester'] or plan['device_id']!=c['device_id']:return 'requester'
    if c['existing_execution_id'] not in (None,plan['execution_id']):return 'one_execution'
    if not ordered(plan['resource_keys'],lambda x:x):return 'resources'
    seen=set()
    for p in plan['primitives']:
        if p['primitive_id'] in seen or not ordered(p['after'],lambda x:x) or not set(p['after'])<=seen:return 'graph'
        if not c['parameters_valid'].get(p['primitive_id'],False):return 'parameters'
        seen.add(p['primitive_id'])
    return None


def send_error(body,c):
    t=body['permit'];p=body['packet'];g=c['guard'];plan=c['plan'];policy=c['policy']
    if not c['durable_intent'] or not c['gate_open']:return 'gate'
    if body!=c['committed_dispatch']:return 'intent'
    if not c['authorization_current']:return 'authorization'
    if not c['runtime_clock_valid']:return 'runtime_clock'
    if g['time_required']!=c['approved_time_required']:return 'time_policy'
    if g['time_required'] and not c['time_qualified']:return 'time'
    if not c['ordinary_closure_valid']:return 'ordinary_open'
    if c['deny_stage']!='ordinary' or c['issuance_closed']:return 'protected'
    if c['execution_status']!='active':return 'execution'
    if not content_ok(g,'guard_digest') or not content_ok(p,'packet_digest'):return 'digest'
    if g!=c['current_guard'] or t['guard_ref']!=ref(g,'guard_id','guard_digest'):return 'guard'
    if g['requester']!=plan['requester'] or t['requester']!=plan['requester']:return 'requester'
    if t['exit']!=g['exit'] or p['exit']!=g['exit'] or g['exit']!=c['live_exit']:return 'exit'
    er=ref(plan,'execution_id','execution_digest')
    if any(x['execution_ref']!=er for x in (g,p,t)):return 'execution'
    binding=plan['binding']
    if any(x['cancellation_id']!=binding['cancellation_id'] or x['parent_command_id']!=binding['parent_command_id'] for x in (p,t)):return 'binding'
    if g['protected_hold_ref']!=plan['protected_hold_ref'] or not c['hold_valid']:return 'resources'
    if int(g['deny_revision'])!=c['deny_revision']:return 'protected'
    if p!=c['prepared_packet'] or body['prepare_id']!=c['prepare_id']:return 'packet'
    if t['packet_ref']!={k:p[k] for k in ('packet_id','packet_digest')} or t['primitive_id']!=p['primitive_id']:return 'packet'
    if p['byte_length']!=len(c['bytes']) or p['sha256']!='sha256:'+hashlib.sha256(c['bytes']).hexdigest() or p['immutable_bytes_ref']['digest']!=p['sha256']:return 'bytes'
    primitive=next((x for x in plan['primitives'] if x['primitive_id']==t['primitive_id']),None)
    if primitive is None or not set(primitive['after'])<=set(c['completed_primitives']):return 'dependencies'
    w=t['send_window']
    if w!=g['send_window'] or w['clock_domain_id']!=g['exit']['clock_domain_id'] or w['descriptor_digest']!=g['exit']['descriptor_digest']:return 'time_binding'
    if not int(w['earliest_tick_ns'])<=c['now']<int(w['latest_tick_ns']):return 'expired'
    if c['transmissions_issued']>=policy['max_transmissions'] or t['budget_receipt_ref']!=c['budget_receipt_ref']:return 'budget'
    if int(t['issued_revision'])!=c['next_issued_revision'] or int(t['ordinal'])!=c['next_ordinal']:return 'ordinal'
    if c['pending_permit'] is not None:return 'pending'
    if t['kind']=='initial':
        if t['initial_permit_id']!=t['permit_id'] or body['resend_request_id'] is not None:return 'initial'
        if t['primitive_id'] in c['initial_sent_primitives']:return 'replay'
    else:
        if not policy['allow_protocol_resend'] or c['initial_disposition']!='in_flight':return 'resend'
        if t['initial_permit_id']!=c['initial_permit_id'] or t['trigger_observation_ref']!=c['resend_observation_ref']:return 'resend'
        if body['resend_request_id']!=c['resend_request_id'] or c['packet_acknowledged']:return 'resend'
    return None


def consume(body,c,ledger):
    """模拟唯一发送出口先消费后I/O；仅计数，无真实发送。"""
    t=body['permit'];pid=t['permit_id'];d=digest(body)
    if pid in ledger:
        return 'cached' if ledger[pid]['digest']==d else 'identity_conflict'
    error=send_error(body,c)
    if error:return error
    ledger[pid]={'digest':d,'disposition':'unknown'}
    return 'consume_before_io'


def encoding_error(request,response,c):
    a,b=request['body'],response['body'];p=b['packet']
    if response['reply_to']!=request['message_id']:return 'reply'
    if a!=c['request_body'] or b['prepare_id']!=a['prepare_id']:return 'binding'
    if not c['pure_encoding_verified']:return 'encoder'
    if not content_ok(p,'packet_digest'):return 'digest'
    if p['execution_ref']!=a['execution_ref'] or p['primitive_id']!=a['primitive_id']:return 'binding'
    if p['exit']!=c['exit'] or c['now']>=int(a['expires_tick_ns']):return 'expired_or_exit'
    raw=bytes.fromhex(b['bytes_hex']);sha='sha256:'+hashlib.sha256(raw).hexdigest()
    if p['byte_length']!=len(raw) or p['sha256']!=sha or p['immutable_bytes_ref']['digest']!=sha:return 'bytes'
    if p!=c['approved_packet']:return 'profile'
    return None


def general_fence_error(request,ack,c):
    b,a=request['body'],ack['body'];txs=b['cancel_transmissions']
    if txs!=c['expected_cancel_transmissions']:return 'incomplete'
    if not ordered(txs,lambda x:x['permit_id']):return 'order'
    if b['cancel_ledger_digest']!=digest(txs) or a['cancel_ledger_digest']!=b['cancel_ledger_digest']:return 'digest'
    if [x['intent'] for x in a['cancel_coverage']]!=txs:return 'coverage'
    for tx in txs:
        if tx['exit']!=c['exit']:return 'exit'
        if request['type']=='RUN_FENCE' and tx['requester']['origin']!='automation':return 'selector'
        if tx['permit_id'] not in c['selector_matches']:return 'selector'
    for x in a['cancel_coverage']:
        pid=x['intent']['permit_id']
        if c['known_dispositions'].get(pid)=='in_flight' and x['disposition']!='in_flight':return 'downgrade'
        if c['known_dispositions'].get(pid)=='unknown' and x['disposition']=='not_sent':return 'downgrade'
        if x['disposition']=='not_sent' and pid not in c['proven_unconsumed']:return 'no_unconsumed_proof'
    return None


def query_error(query,response,c):
    if response['reply_to']!=query['message_id']:return 'reply'
    if response['body']['execution_ref']!=query['body']['execution_ref']:return 'binding'
    for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest'):
        if response[k]!=c['exit'][k] or query[k]!=c['exit'][k]:return 'exit'
    expected=c['stored_report_refs']
    b=response['body']
    if b['status']=='cache_missing':
        return None if not b['stored_report_refs'] else 'cache_missing'
    return None if b['stored_report_refs']==expected else 'reports'


def stored_error(stored,report,c):
    a,b=stored['body'],report['body']
    if any(stored[k]!=report[k] or stored[k]!=c['exit'][k] for k in
            ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest')):return 'exit'
    if a['report_id']!=b['report_id'] or a['report_digest']!=digest(b):return 'binding'
    if a['record_ref']!=c['record_ref'] or not c['committed']:return 'not_stored'
    return None


def decision_error(value,c):
    if not content_ok(value,'decision_digest'):return 'digest'
    if value['binding']!=c['binding'] or value['command_state_ref']!=c['command_state_ref']:return 'binding'
    if value['provider_receipt_ref']!=c['provider_receipt_ref'] or value['evidence_refs']!=c['evidence_refs']:return 'provider'
    if value['execution_ref']!=c['execution_ref']:return 'execution'
    if value['outcome']=='confirmed':
        if not c['all_closure_valid'] or value['all_closure_ref']!=c['all_closure_ref']:return 'closure'
        if c['binding']['mode']=='before_dispatch_only':
            if not c['all_ordinary_proven_not_sent']:return 'not_sent_unproven'
        elif not c['cancellation_effect_verified']:return 'effect'
    if value['outcome']=='too_late' and c['parent_outcome'] not in ('succeeded','failed','cancelled','not_sent'):return 'not_definite'
    if value['outcome']=='unsupported' and c['binding']['mode']!='before_dispatch_only':return 'policy'
    return None
