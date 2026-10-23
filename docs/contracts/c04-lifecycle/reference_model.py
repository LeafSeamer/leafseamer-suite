"""C04候选关联与有限原子步模型；权威均为夹具，不实现HTTP或数据库。"""
import copy
import hashlib
import rfc8785
from build_contracts import VERSION


def digest(value): return 'sha256:' + hashlib.sha256(rfc8785.dumps(value)).hexdigest()
def without(value, key): return {k: v for k, v in value.items() if k != key}
def increment(value): return str(int(value) + 1)


def semantic_error(model, v):
    if model == 'ActivationSlot' and ((v['active_run_id'] is None) != (v['definition_version'] is None)): return 'slot_pair'
    if model == 'RunRecord':
        if v['dispatch_eligible'] and (v['lifecycle'] not in ('armed', 'running') or v['pause_latches'] or v['active_operation_id']): return 'run_gate'
        if v['lifecycle'] == 'running' and v['active_execution_id'] is None: return 'execution_required'
        if v['lifecycle'] == 'armed' and (v['active_execution_id'] is not None or v['active_operation_id'] is not None): return 'armed_busy'
        if v['lifecycle'] == 'completed' and (v['active_execution_id'] is not None or v['active_operation_id'] is not None): return 'completed_busy'
    if model in ('Preflight', 'RecoveryPreview'):
        field = 'preflight_digest' if model == 'Preflight' else 'preview_digest'
        if v[field] != digest(without(v, field)): return 'digest'
        if int(v['issued_tick_ns']) >= int(v['expires_tick_ns']): return 'lifetime'
        if model == 'Preflight':
            ids = [t['controller_id'] for t in v['checks']]
            if len(ids) != len(set(ids)): return 'duplicate_target'
            if v['passed'] and any(t['status'] != 'passed' for t in v['checks']): return 'preflight_checks'
        else:
            ids = [s['step_id'] for s in v['plan']]
            if len(ids) != len(set(ids)): return 'duplicate_step'
            for step in v['plan']:
                if step['disposition'] == 'retain_success' and (not step['previous_command_ref'] or not step['evidence_refs'] or step['parameters_ref'] is not None): return 'retain_evidence'
                if step['disposition'] == 'execute_new' and step['parameters_ref'] is None: return 'parameters_required'
                if step['disposition'] == 'reconcile_commit' and (not step['evidence_refs'] or step['parameters_ref'] is not None): return 'reconcile_evidence'
            if any(s['disposition'] == 'reconcile_commit' for s in v['plan']) and any(s['disposition'] == 'execute_new' for s in v['plan']): return 'reconcile_mixed_write'
    if model == 'EvaluationSnapshot':
        if v['rule_result'] is not None and v['transitions']: return 'evaluation_kind'
        if v['snapshot_digest'] != digest(without(v, 'snapshot_digest')): return 'digest'
        for collection, field in ((v['transitions'], 'transition_id'), (v['observations'], 'binding_id')):
            if len({x[field] for x in collection}) != len(collection): return 'duplicate_evaluation'
    if model == 'TriggerDecision':
        if v['decision_digest'] != digest(without(v, 'decision_digest')): return 'digest'
        if (v['result'] == 'accepted') != (v['execution_id'] is not None): return 'decision_execution'
        if (v['snapshot_id'] is None) != (v['snapshot_digest'] is None): return 'snapshot_pair'
        if v['result'] in ('accepted', 'no_match', 'evaluation_unknown', 'ambiguous') and v['snapshot_id'] is None: return 'snapshot_required'
        if v['result'] != 'accepted' and v['selected_transition_id'] is not None: return 'selection_without_execution'
    if model == 'ExecutionBinding' and v['binding_digest'] != digest(without(v, 'binding_digest')): return 'digest'
    if model == 'ExecutionRecord':
        if v['phase'] == 'finished' and v['outcome'] == 'pending': return 'finished_pending'
        if v['state_commit_event_id'] is not None and v['outcome'] not in ('succeeded', 'completed_with_failures'): return 'commit_outcome'
    if model == 'LifecycleOperation':
        if int(v['committed_run_revision']) != int(v['baseline']['run_revision']) + 1: return 'run_revision'
        slot_delta = 1 if v['kind'] in ('arm', 'resume') else 0
        if int(v['committed_slot_revision']) != int(v['baseline']['slot_revision']) + slot_delta: return 'slot_revision'
        expected = int(v['baseline']['arm_generation']) + (1 if v['kind'] in ('arm', 'resume') else 0)
        if int(v['target_arm_generation']) != expected: return 'arm_generation'
        if (v['kind'] == 'arm') != (v['consumed_preflight_id'] is not None): return 'preflight_consumption'
        if (v['kind'] == 'resume') != (v['consumed_preview_id'] is not None): return 'preview_consumption'
        if (v['kind'] == 'resume') != (v['execution_id'] is not None): return 'recovery_execution'
        if len({t['controller_id'] for t in v['targets']}) != len(v['targets']): return 'duplicate_target'
        if v['state'] == 'ready' and (v['kind'] not in ('arm', 'resume') or any(t['state'] != 'applied' or t['receipt_ref'] is None for t in v['targets'])): return 'ready_targets'
        if v['protection_complete'] and (not v['locally_closed'] or any(t['state'] != 'closed' or t['barrier_ref'] is None for t in v['targets'])): return 'barrier_incomplete'
    return None


def choose(rule_result, transitions):
    if rule_result is not None:
        return ('accepted', None) if rule_result == 'true' else ('no_match' if rule_result == 'false' else 'evaluation_unknown', None)
    true = [t for t in transitions if t['result'] == 'true']
    unknown = [t for t in transitions if t['result'] == 'unknown']
    if not true: return ('evaluation_unknown' if unknown else 'no_match', None)
    highest = max(t['priority'] for t in true)
    if any(t['priority'] >= highest for t in unknown): return 'evaluation_unknown', None
    winners = [t for t in true if t['priority'] == highest]
    return ('ambiguous', None) if len(winners) != 1 else ('accepted', winners[0]['transition_id'])


def trigger_binding_error(snapshot, decision, execution, definition_version, transition_targets):
    for model, record in [('EvaluationSnapshot', snapshot), ('TriggerDecision', decision), ('ExecutionBinding', execution)]:
        if semantic_error(model, record): return 'record_invalid'
    if decision['result'] != 'accepted' or choose(snapshot['rule_result'], snapshot['transitions']) != ('accepted', decision['selected_transition_id']): return 'selection'
    if any(snapshot[k] != decision[k] or snapshot[k] != execution[k] for k in ('scope', 'run_id', 'artifact_ref')): return 'execution_scope'
    if any(snapshot[k] != decision[k] for k in ('snapshot_id', 'snapshot_digest', 'inbox_ref', 'receive_seq')): return 'decision_snapshot'
    if decision['run_revision_before'] != snapshot['run_revision'] or decision['definition_version'] != definition_version: return 'decision_version'
    if decision['execution_id'] != execution['execution_id']: return 'execution_identity'
    if execution['origin'] != dict(kind='trigger', decision_id=decision['decision_id'], decision_digest=decision['decision_digest']): return 'execution_origin'
    if execution['source_state'] != snapshot['source_state'] or execution['clock'] != snapshot['clock'] or execution['input_snapshot_ref'] != snapshot['input_snapshot_ref']: return 'execution_snapshot'
    selected = decision['selected_transition_id']
    if selected is None:
        if execution['target_state_id'] is not None: return 'target_state'
    elif selected not in transition_targets or transition_targets[selected] != execution['target_state_id']: return 'target_state'
    return None


def baseline(world):
    result = copy.deepcopy(world['dependencies'])
    result.update(run_revision=world['run']['revision'], slot_revision=world['slot']['revision'],
        artifact_ref=world['run']['artifact_ref'], arm_generation=world['run']['arm_generation'], business_state=world['run']['business_state'])
    return result


def reserve(world, kind, request, preview, context):
    """一次调用假设一个原子事务；返回新快照。未模拟SQL锁、网络或崩溃耐久。"""
    w = copy.deepcopy(world); run, slot = w['run'], w['slot']
    if not context['authorized']: return w, 'forbidden'
    if not context['storage_healthy']: return w, 'protected'
    if run['scope'] != slot['scope'] or run['definition_id'] != slot['definition_id']: return w, 'slot_binding'
    key = (context['request_epoch'], context['actor'], kind, request['context']['idempotency_key'])
    identity = digest(dict(contract_version=VERSION, kind=kind, scope=run['scope'], run_id=run['run_id'], parameters=without(request, 'context')))
    if key in w['requests']: return w, 'existing' if w['requests'][key] == identity else 'request_conflict'
    if context['subject_kind'] != 'human': return w, 'forbidden'
    if run['revision'] != request['expected_run_revision'] or slot['revision'] != request['expected_slot_revision']: return w, 'conflict'
    if slot['active_run_id'] not in (None, run['run_id']): return w, 'slot_owned'
    if slot['active_run_id'] == run['run_id'] and slot['definition_version'] != run['definition_version']: return w, 'slot_binding'
    if run['active_operation_id'] is not None: return w, 'operation_busy'
    if (kind == 'arm' and (run['lifecycle'] != 'disarmed' or run['active_execution_id'] is not None or run['pause_latches'])) or (kind == 'resume' and run['lifecycle'] != 'paused'): return w, 'lifecycle'
    model = 'Preflight' if kind == 'arm' else 'RecoveryPreview'
    field, digest_field = ('preflight_id', 'preflight_digest') if kind == 'arm' else ('preview_id', 'preview_digest')
    if semantic_error(model, preview): return w, 'invalid_preview'
    if preview[field] != request[field] or preview[digest_field] != request[digest_field]: return w, 'preview_binding'
    if preview['scope'] != run['scope'] or preview['run_id'] != run['run_id']: return w, 'preview_binding'
    if preview['baseline'] != baseline(w) or preview['clock'] != context['clock']: return w, 'stale'
    if not int(preview['issued_tick_ns']) <= context['now'] < int(preview['expires_tick_ns']): return w, 'expired'
    if (model, preview[field]) in w['consumed']: return w, 'consumed'
    if kind == 'arm':
        actual = {t['controller_id']: sorted(t['device_ids']) for t in preview['checks']}
        if not preview['passed'] or actual != context['required_targets']: return w, 'target_coverage'
    else:
        if preview['request_epoch'] != context['request_epoch']: return w, 'stale'
        if preview['unresolved_command_refs'] or context['unresolved']: return w, 'unresolved'
        if preview['prior_execution_id'] != run['active_execution_id'] or not context['recovery_plan_approved']: return w, 'recovery_binding'
    if not context['gates_valid']: return w, 'protected'
    if context['abort_before_commit']: return copy.deepcopy(world), 'rolled_back'
    op = 'operation_' + str(len(w['requests']) + 1)
    w['requests'][key] = identity; w['consumed'].add((model, preview[field]))
    run['revision'] = increment(run['revision']); slot['revision'] = increment(slot['revision'])
    run['arm_generation'] = increment(run['arm_generation']); run['active_operation_id'] = op; run['dispatch_eligible'] = False
    slot.update(active_run_id=run['run_id'], definition_version=run['definition_version'])
    if kind == 'resume':
        run['active_execution_id'] = 'recovery_' + op; w['new_executions'].append(run['active_execution_id'])
    w['reservation'] = dict(kind=kind, operation_id=op, run_revision=run['revision'], slot_revision=slot['revision'],
        arm_generation=run['arm_generation'], execution_id=run['active_execution_id'], baseline=copy.deepcopy(preview['baseline']),
        expected_targets=copy.deepcopy(context['required_targets']), expected_grants=copy.deepcopy(context['target_grants']), context_clock=copy.deepcopy(context['clock']))
    return w, 'accepted'


def prepare(world, receipts, context):
    w = copy.deepcopy(world); run, slot, reservation = w['run'], w['slot'], w['reservation']
    if reservation.get('state') in ('paused', 'indeterminate', 'ready'): return w, 'operation_terminal'
    if not context['storage_healthy'] or w.get('volatile_closed', False):
        w['volatile_closed'] = True; run['dispatch_eligible'] = False
        return w, 'protected'
    def fail(reason, uncertain=False):
        reservation['state'] = 'indeterminate' if uncertain else 'paused'
        run.update(lifecycle='paused', dispatch_eligible=False)
        run['pause_latches'].append(reason); run['revision'] = increment(run['revision'])
        return w, reason
    if run['scope'] != slot['scope'] or slot['active_run_id'] != run['run_id'] or slot['definition_id'] != run['definition_id'] or slot['definition_version'] != run['definition_version']: return w, 'slot_binding'
    if any(run[k] != reservation[x] for k, x in [('revision', 'run_revision'), ('arm_generation', 'arm_generation'),
        ('active_operation_id', 'operation_id'), ('active_execution_id', 'execution_id')]) or slot['revision'] != reservation['slot_revision']:
        return w, 'stale'
    if not context['gates_valid'] or context['clock'] != reservation['context_clock']: return fail('protected')
    # 新代次是本操作预期变化；其它来源/目录/权限变化不得被吸收。
    before, current = reservation['baseline'], baseline(w)
    if any(before[k] != current[k] for k in before if k not in ('run_revision', 'slot_revision', 'arm_generation')): return fail('stale')
    if len({r['controller_id'] for r in receipts}) != len(receipts): return fail('duplicate_target')
    if {r['controller_id']: sorted(r['device_ids']) for r in receipts} != reservation['expected_targets']: return fail('target_coverage', True)
    for r in receipts:
        if r['operation_id'] != reservation['operation_id'] or r['execution_id'] != reservation['execution_id'] or r['arm_generation'] != reservation['arm_generation']: return fail('receipt_binding')
        if r['target_grant_ref'] != reservation['expected_grants'].get(r['controller_id']): return fail('grant_binding')
        if r['state'] != 'applied' or not r['trusted'] or not r['durable']: return fail('target_unready', True)
    if reservation['kind'] == 'arm':
        run.update(lifecycle='armed', active_operation_id=None, dispatch_eligible=True)
        run['revision'] = increment(run['revision'])
    # 恢复ready仍paused；实际R4开始另有事务，不在此参考子模型执行。
    w['reservation']['state'] = 'ready'
    return w, 'ready'


def trigger(world, snapshot, context):
    w = copy.deepcopy(world); run, slot = w['run'], w['slot']
    if not context['authorized']: return w, 'forbidden'
    if not context['storage_healthy']: return w, 'protected_uncommitted'
    event = snapshot['inbox_ref']; key = (run['scope']['authority_service_id'], run['scope']['database_instance_id'], run['run_id'], event['scope']['authority_service_id'], event['scope']['database_instance_id'], event['object_id'], event['revision'])
    if key in w['decisions']:
        saved = w['decisions'][key]
        return w, 'existing_' + saved['result'] if saved['inbox_ref'] == event and saved['receive_seq'] == snapshot['receive_seq'] else 'event_conflict'
    if semantic_error('EvaluationSnapshot', snapshot): return w, 'invalid_snapshot'
    if snapshot['scope'] != run['scope'] or snapshot['run_id'] != run['run_id'] or snapshot['artifact_ref'] != run['artifact_ref']: return w, 'snapshot_binding'
    if int(snapshot['receive_seq']) <= int(run['last_receive_seq']): result, selected = 'suppressed_obsolete', None
    elif run['active_execution_id'] or run['active_operation_id']: result, selected = 'suppressed_busy', None
    elif run['lifecycle'] != 'armed': result, selected = 'suppressed_inactive', None
    elif not run['dispatch_eligible'] or run['pause_latches']: result, selected = 'protected', None
    elif snapshot['run_revision'] != run['revision'] or snapshot['source_state'] != run['business_state']: return w, 'conflict'
    elif snapshot['clock'] != context['clock'] or not context['gates_valid']: result, selected = 'protected', None
    elif slot['active_run_id'] != run['run_id'] or slot['definition_version'] != run['definition_version']: return w, 'slot_binding'
    else: result, selected = choose(snapshot['rule_result'], snapshot['transitions'])
    if context['abort_before_commit']: return copy.deepcopy(world), 'rolled_back'
    w['decisions'][key] = dict(result=result, selected=selected, inbox_ref=copy.deepcopy(event), receive_seq=snapshot['receive_seq'])
    run['last_receive_seq'] = str(max(int(run['last_receive_seq']), int(snapshot['receive_seq'])))
    if result == 'accepted':
        execution = 'execution_' + str(len(w['decisions'])); run.update(lifecycle='running', active_execution_id=execution)
        run['revision'] = increment(run['revision']); slot['revision'] = increment(slot['revision']); w['new_executions'].append(execution)
    elif result in ('protected', 'evaluation_unknown', 'ambiguous'):
        run.update(lifecycle='paused', dispatch_eligible=False); run['pause_latches'].append(result); run['revision'] = increment(run['revision'])
    return w, result


def commit_state(world, execution_id, source_state, target_state_id, context):
    w = copy.deepcopy(world); run = w['run']
    if not context['authorized']: return w, 'forbidden'
    if not context['storage_healthy']: return w, 'protected'
    if execution_id in w['commits']: return w, 'existing'
    if run['active_execution_id'] != execution_id or run['business_state'] != source_state: return w, 'conflict'
    if run['artifact_ref'] != context['expected_artifact_ref'] or run['arm_generation'] != context['expected_arm_generation']: return w, 'stale'
    if w['slot']['active_run_id'] != run['run_id'] or w['slot']['definition_version'] != run['definition_version']: return w, 'slot_binding'
    if run['pause_latches'] or run['lifecycle'] != 'running' or not context['gates_valid'] or not context['all_required_evidence'] or context['unresolved']: return w, 'protected'
    if context['abort_before_commit']: return copy.deepcopy(world), 'rolled_back'
    if source_state is not None:
        run['business_state'] = dict(state_id=target_state_id, revision=increment(source_state['revision']))
    elif target_state_id is not None: return w, 'state_kind'
    event = 'completed_' + execution_id
    run.update(lifecycle='armed', active_execution_id=None, last_execution_id=execution_id)
    run['revision'] = increment(run['revision']); w['commits'][execution_id] = event; w['outbox'].append(event)
    return w, 'committed'
