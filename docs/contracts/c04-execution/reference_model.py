"""执行候选的纯合成判定；事务、身份、设备与时钟来源均不在本模型实现。"""
import copy
import hashlib
import rfc8785
from fractions import Fraction

MAX_U20 = 10 ** 20 - 1


def digest(value): return 'sha256:' + hashlib.sha256(rfc8785.dumps(value)).hexdigest()
def seal(value, field): value[field] = digest({k: v for k, v in value.items() if k != field}); return value
def tick(value):
    n = int(value)
    if not 0 <= n <= MAX_U20: raise ValueError('u20_overflow')
    return str(n)


def semantic_error(model, v):
    fields = {'PauseLatch': 'latch_digest', 'ExecutionStart': 'start_digest', 'StepPlan': 'plan_digest',
        'CommandSubmission': 'submission_digest', 'DelayRecord': 'delay_digest', 'EdgeSample': 'sample_digest',
        'EdgeDecision': 'decision_digest', 'BudgetCharge': 'charge_digest', 'WindowTranslation': 'translation_digest',
        'ExecutionRuntimePolicy': 'policy_digest', 'ExecutionAnchor': 'anchor_digest', 'StepReady': 'ready_digest'}
    if model in fields:
        field = fields[model]
        if v[field] != digest({k: x for k, x in v.items() if k != field}): return 'digest'
    if model == 'ExecutionStart':
        if int(v['run_revision_after']) != int(v['run_revision_before']) + 1: return 'start_revision'
        if len({r['object_id'] for r in v['cleared_latch_refs']}) != len(v['cleared_latch_refs']): return 'duplicate_latch'
    if model == 'StepPlan':
        p = v['payload']
        if p['kind'] in ('retain_success', 'reconcile_commit') and not p['evidence_refs']: return 'evidence_required'
        if p['kind'] in ('delay', 'reconcile_commit') and not v['required']: return 'required'
        if p['kind'] == 'reconcile_commit' and v['phase'] != 'commit': return 'commit_phase'
    if model == 'StepRecord':
        terminal = v['state'] in ('finished', 'retained', 'cancelled', 'indeterminate')
        if terminal == (v['outcome'] == 'pending'): return 'step_outcome'
        if v['state'] == 'retained' and (v['outcome'] != 'succeeded' or not v['command_ref'] or not v['evidence_refs']): return 'retain_evidence'
        if v['state'] == 'cancelled' and v['outcome'] != 'cancelled': return 'cancel_outcome'
        if v['result_ref'] is not None and (v['outcome'] != 'succeeded' or not v['evidence_refs']): return 'result_evidence'
    if model == 'CommandSubmission':
        if (v['attempt_clock'] is None) != (v['attempt_tick_ns'] is None): return 'attempt_pair'
        if (v['state'] == 'planned') != (v['attempt_tick_ns'] is None): return 'attempt_marker'
        if (v['state'] == 'accepted') != (v['command_ref'] is not None): return 'command_pair'
        if v['command_ref'] and v['command_ref']['scope'] != v['identity']['target_scope']: return 'command_scope'
        if (v['state'] in ('accepted', 'rejected')) != (v['adjudication_ref'] is not None): return 'adjudication_pair'
        if v['adjudication_ref'] and v['adjudication_ref']['scope'] != v['identity']['target_scope']: return 'adjudication_scope'
    if model == 'DelayRecord':
        due = int(v['anchor_tick_ns']) + v['policy']['delay_ms'] * 1000000
        end = due + v['policy']['max_lateness_ms'] * 1000000
        if end > MAX_U20 or int(v['due_tick_ns']) != due or int(v['deadline_tick_ns']) != end: return 'delay_arithmetic'
        expected = 'execution_anchor' if v['policy']['anchor_kind'] == 'execution_admitted' else 'step_ready'
        if v['anchor_ref']['kind'] != expected: return 'anchor_kind'
    if model == 'WindowTranslation':
        try: bounds = translated_bounds(v)
        except ValueError: return 'window_invalid'
        if bounds != (v['target_not_before_tick_ns'], v['target_deadline_tick_ns']): return 'window_arithmetic'
    if model == 'EdgePolicy':
        enter, reset = int(v['enter_raw']), int(v['reset_raw'])
        if (v['direction'] == 'rising' and reset >= enter) or (v['direction'] == 'falling' and reset <= enter): return 'hysteresis'
    if model == 'EdgeState':
        if (v['phase'] == 'tracking') != (v['candidate_since_tick_ns'] is not None): return 'tracking_anchor'
        if len({x is None for x in (v['last_sequence'], v['last_sample_digest'], v['last_sample_tick_ns'])}) != 1: return 'last_sample_pair'
        if v['candidate_since_tick_ns'] is not None and (v['last_sample_tick_ns'] is None or int(v['candidate_since_tick_ns']) > int(v['last_sample_tick_ns'])): return 'future_anchor'
    if model == 'BudgetCharge':
        if (v['key']['unit'] == 'execution') != (v['step_id'] is None): return 'budget_unit'
    if model == 'BudgetPolicy' and v['policy_ref']['digest'] != digest({k: v[k] for k in ('window_ms', 'limit', 'max_live_charges')}): return 'limit_digest'
    if model == 'ExecutionRuntimePolicy':
        for collection, key in (('delay_policies', 'step_id'), ('edge_policies', 'binding_id')):
            if len({x[key] for x in v[collection]}) != len(v[collection]): return 'duplicate_policy'
        if len({digest(p['key']) for p in v['budget_policies']}) != len(v['budget_policies']): return 'duplicate_budget'
        if any(semantic_error('EdgePolicy', x['policy']) for x in v['edge_policies']): return 'edge_policy'
        if any(semantic_error('BudgetPolicy', x) for x in v['budget_policies']): return 'budget_policy'
    return None


def start_recovery(world, candidate, context):
    """模拟R4一个Seamer原子事务；当前权威和完整计划来自人工context。"""
    w = copy.deepcopy(world)
    if not context['storage_healthy'] or w.get('volatile_closed', False):
        w['volatile_closed'] = True; w['run']['dispatch_eligible'] = False
        return w, 'protected'
    if not context['authorized']: return w, 'forbidden'
    if semantic_error('ExecutionStart', candidate): return w, 'invalid'
    if candidate['start_id'] in w['starts']:
        return w, 'existing' if w['starts'][candidate['start_id']] == candidate else 'identity_conflict'
    run, op = w['run'], w['operation']
    expected = dict(scope=run['scope'], run_id=run['run_id'], operation_id=op['operation_id'],
        run_revision_before=run['revision'], slot_revision=w['slot_revision'], expected_operation_revision=op['revision'],
        execution_binding_ref=op['execution_binding_ref'], plan_ref=op['plan_ref'], prepared_targets_digest=op['prepared_targets_digest'],
        cleared_latch_refs=op['resolved_latch_refs'], clock=context['clock'], mode=op['mode'])
    if any(candidate[k] != x for k, x in expected.items()): return w, 'binding'
    if run['active_operation_id'] != op['operation_id'] or run['active_execution_id'] != op['execution_id'] or run['lifecycle'] != 'paused' or op['state'] != 'ready': return w, 'state'
    if run['pause_latch_refs'] != op['resolved_latch_refs']: return w, 'new_latch'
    if not all(context[k] for k in ('slot_owned', 'baseline_current', 'targets_applied', 'old_resources_clear', 'plan_complete', 'gates_valid', 'budget_valid', 'schedule_valid')):
        if context['abort_before_commit']: return w, 'rolled_back'
        op.update(state='paused', revision=tick(int(op['revision']) + 1))
        run.update(revision=tick(int(run['revision']) + 1), dispatch_eligible=False)
        return w, 'protected'
    if candidate['start_tick_ns'] != tick(context['now']): return w, 'clock'
    if op['mode'] == 'reconcile_commit' and context['plan_has_device_write']: return w, 'write_forbidden'
    if context['abort_before_commit']: return w, 'rolled_back'
    w['starts'][candidate['start_id']] = copy.deepcopy(candidate)
    run.update(lifecycle='running', revision=candidate['run_revision_after'], active_operation_id=None,
        pause_latch_refs=[], dispatch_eligible=op['mode'] == 'execute')
    op.update(state='running' if op['mode'] == 'execute' else 'reconciling', revision=tick(int(op['revision']) + 1))
    return w, 'started'


def dispatch_once(submission, context):
    """只生成持久发送标记；returned call_once不执行任何I/O。"""
    result = copy.deepcopy(submission)
    if semantic_error('CommandSubmission', result): return result, 'invalid'
    if not context['authorized'] or not context['storage_healthy']: return result, 'protected'
    if result['state'] != 'planned': return result, 'query_only'
    if not all(context[k] for k in ('gates_valid', 'step_ready', 'parameters_valid', 'budget_valid', 'schedule_valid', 'execution_current')): return result, 'protected'
    if context['abort_before_commit']: return result, 'rolled_back'
    result.update(state='attempt_recorded', attempt_clock=copy.deepcopy(context['clock']), attempt_tick_ns=tick(context['now']))
    return seal(result, 'submission_digest'), 'call_once'


def resolve_submission(submission, response, context):
    result = copy.deepcopy(submission)
    if not context['authorized'] or not context['storage_healthy']: return result, 'protected'
    if result['state'] in ('accepted', 'rejected'): return result, 'terminal'
    if result['state'] not in ('attempt_recorded', 'indeterminate'): return result, 'not_attempted'
    if not context['response_trusted'] or response['identity'] != result['identity']: return result, 'response_binding'
    if response['result'] == 'accepted' or (response['result'] == 'rejected_final' and context['rejection_durable']):
        receipt = response.get('adjudication_ref')
        if not receipt or receipt['scope'] != result['identity']['target_scope']: return result, 'response_receipt'
        result['adjudication_ref'] = copy.deepcopy(receipt)
    if response['result'] == 'accepted':
        if response['command_ref']['scope'] != result['identity']['target_scope']: return copy.deepcopy(submission), 'response_scope'
        result.update(state='accepted', command_ref=copy.deepcopy(response['command_ref']))
    elif response['result'] == 'rejected_final' and context['rejection_durable']:
        result['state'] = 'rejected'
    else:
        result['state'] = 'indeterminate'  # not_found也不证明迟到请求永远不受理。
    return seal(result, 'submission_digest'), result['state']


def delay_status(record, context):
    if semantic_error('DelayRecord', record): return 'invalid'
    if record['state'] != 'waiting': return 'terminal_' + record['state']
    if record['clock'] != context['clock'] or not context['gates_valid'] or context['restarted']: return 'cancelled'
    now = context['now']
    if now < int(record['anchor_tick_ns']): return 'cancelled'
    if now < int(record['due_tick_ns']): return 'waiting'
    if now >= int(record['deadline_tick_ns']): return 'expired'
    return 'elapsed'


def delay_binding_error(record, execution_anchor, step_ready):
    for model, value in [('DelayRecord', record), ('ExecutionAnchor', execution_anchor)]:
        if semantic_error(model, value): return 'invalid'
    if any(record[k] != execution_anchor[k] for k in ('scope', 'execution_id', 'clock')): return 'execution_anchor'
    er = record['execution_anchor_ref']
    if er['scope'] != record['scope'] or er['digest'] != execution_anchor['anchor_digest'] or er['object_id'] != execution_anchor['anchor_id'] or er['revision'] != execution_anchor['revision']: return 'execution_anchor_digest'
    if record['policy']['anchor_kind'] == 'execution_admitted':
        if record['anchor_ref'] != record['execution_anchor_ref'] or record['anchor_tick_ns'] != execution_anchor['anchor_tick_ns']: return 'anchor_binding'
    else:
        if step_ready is None or semantic_error('StepReady', step_ready): return 'ready_invalid'
        if any(record[k] != step_ready[k] for k in ('scope', 'execution_id', 'step_id', 'clock')): return 'ready_binding'
        ar = record['anchor_ref']
        if ar['scope'] != record['scope'] or ar['digest'] != step_ready['ready_digest'] or ar['object_id'] != step_ready['ready_id'] or ar['revision'] != step_ready['revision'] or record['anchor_tick_ns'] != step_ready['ready_tick_ns']: return 'ready_digest'
        if int(step_ready['ready_tick_ns']) < int(execution_anchor['anchor_tick_ns']): return 'ready_before_execution'
    return None


def translated_bounds(v):
    """条件速率界下的保守区间；不证明sample确实发生在challenge往返之间。"""
    p, q, sample = (int(v[k]) for k in ('target_challenge_sent_tick_ns', 'target_response_received_tick_ns', 'source_sample_tick_ns'))
    due, end = int(v['source_due_tick_ns']), int(v['source_deadline_tick_ns'])
    rs, rt = Fraction(v['source_rate_error_ppm'], 1000000), Fraction(v['target_rate_error_ppm'], 1000000)
    if not 0 <= p <= q or not 0 <= rs < 1 or not 0 <= rt < 1 or due >= end or end <= sample: raise ValueError('window_invalid')
    later = max(0, due - sample) * (1 + rt) / (1 - rs)
    sooner = (end - sample) * (1 - rt) / (1 + rs)
    lower = q + (-(-later.numerator // later.denominator))
    upper = p + sooner.numerator // sooner.denominator
    if lower >= upper: raise ValueError('empty_window')
    return tick(lower), tick(upper)


def translated_gate(v, context):
    if semantic_error('WindowTranslation', v): return 'invalid'
    if not context['challenge_trusted'] or not context['rate_profiles_approved'] or not context['binding_current']: return 'protected'
    if v['target_clock'] != context['clock']: return 'clock_domain'
    if context['now'] < int(v['target_not_before_tick_ns']): return 'waiting'
    if context['now'] >= int(v['target_deadline_tick_ns']): return 'expired'
    return 'eligible'


def edge_step(state, policy, sample, context):
    """模拟单一顺序sample的检测状态；不是采样器或连续信号证明。"""
    s = copy.deepcopy(state)
    if semantic_error('EdgeState', s) or semantic_error('EdgePolicy', policy) or semantic_error('EdgeSample', sample): return s, 'invalid_record'
    if s['binding']['policy_ref']['digest'] != digest(policy): return s, 'policy_binding'
    if sample['binding'] != s['binding'] or sample['binding']['clock'] != context['clock']: return s, 'source_binding'
    if s['last_sequence'] is not None and int(sample['sequence']) <= int(s['last_sequence']):
        if sample['sequence'] == s['last_sequence'] and sample['sample_digest'] != s['last_sample_digest']: return s, 'sequence_conflict'
        return s, 'duplicate_or_old'
    gap = policy['max_sample_gap_ms'] * 1000000; t = int(sample['sample_tick_ns']); previous = s['last_sample_tick_ns']
    invalid = not context['sample_trusted'] or sample['unit'] != policy['unit'] or not 0 <= context['now'] - t < gap
    invalid |= previous is not None and (t < int(previous) or t - int(previous) > gap)
    baseline = sample['delivery'] != 'live'
    s.update(last_sequence=sample['sequence'], last_sample_digest=sample['sample_digest'], last_sample_tick_ns=sample['sample_tick_ns'], revision=tick(int(s['revision']) + 1))
    if invalid or baseline:
        s.update(phase='needs_reset', candidate_since_tick_ns=None)
        return s, 'invalid' if invalid else 'baseline'
    value = int(sample['raw']); rising = policy['direction'] == 'rising'
    reset = value <= int(policy['reset_raw']) if rising else value >= int(policy['reset_raw'])
    enter = value >= int(policy['enter_raw']) if rising else value <= int(policy['enter_raw'])
    if reset:
        s.update(phase='armed', candidate_since_tick_ns=None); return s, 'reset_observed'
    if s['phase'] == 'needs_reset': return s, 'idle'
    if not enter:
        s.update(phase='armed', candidate_since_tick_ns=None); return s, 'idle'
    if s['phase'] != 'tracking': s.update(phase='tracking', candidate_since_tick_ns=sample['sample_tick_ns'])
    if t - int(s['candidate_since_tick_ns']) < policy['stable_for_ms'] * 1000000: return s, 'tracking'
    s.update(phase='needs_reset', candidate_since_tick_ns=None)
    return s, 'suppressed_busy' if context['busy'] else ('edge' if context['armed'] else 'suppressed_inactive')


def charge_budget(ledger, policy, charge, context):
    """滚动计数合成账本；跨服务预算及真实持久化不在本模型实现。"""
    w = copy.deepcopy(ledger)
    if not context['authorized'] or not context['storage_healthy']: return w, 'protected'
    if semantic_error('BudgetCharge', charge) or semantic_error('BudgetPolicy', policy): return w, 'invalid'
    if charge['key'] != policy['key'] or w['key'] != policy['key'] or charge['policy_ref'] != policy['policy_ref'] or w['policy_ref'] != policy['policy_ref']: return w, 'policy_binding'
    if charge['charge_id'] in w['charges']:
        return w, 'existing' if w['charges'][charge['charge_id']] == charge else 'identity_conflict'
    if w['blocked']: return w, 'latched'
    if charge['clock'] != w['clock'] or charge['clock'] != context['clock']: return w, 'clock_domain'
    if context['now'] < int(w['last_tick_ns']) or charge['charged_tick_ns'] != tick(context['now']): return w, 'clock'
    active = [c for c in w['charges'].values() if int(c['charged_tick_ns']) > context['now'] - policy['window_ms'] * 1000000]
    if len(active) >= policy['max_live_charges'] or sum(c['amount'] for c in active) + charge['amount'] > policy['limit']:
        if context['abort_before_commit']: return w, 'rolled_back'
        w['blocked'] = True; return w, 'exceeded'
    if context['abort_before_commit']: return w, 'rolled_back'
    w['last_tick_ns'] = tick(context['now']); w['charges'][charge['charge_id']] = copy.deepcopy(charge)
    return w, 'charged'
