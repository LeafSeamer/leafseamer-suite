"""有限快照参考判定，不执行提供者、数据库事务、设备发送或自动化恢复。"""
import copy
import hashlib
import rfc8785

def digest(value):return 'sha256:'+hashlib.sha256(rfc8785.dumps(value)).hexdigest()
def sealed(value,key):
    return value.get(key)==digest({k:v for k,v in value.items() if k!=key})
def seal(value,key):
    value[key]=digest({k:v for k,v in value.items() if k!=key});return value
def state_ref(value):
    return dict(id=value['command_id'],revision=value['revision'],digest=digest(value))
def evidence_ref(value):
    return dict(id=value['evidence_id'],revision='1',digest=value['evidence_digest'])
def resolution_ref(value):
    return dict(id=value['resolution_id'],revision=value['revision'],digest=value['resolution_digest'])

def provider_error(evidence,claims,c):
    # 该映射由可信提供者存储读取；不从调用方payload或自报durable字段构造。
    record=c['provider_receipts'].get(evidence['evidence_digest'])
    if record is None:return 'provider_missing'
    if record['verdict']!='accepted':return 'provider_unconfirmed'
    if record['scope']!=c['policy']['scope'] or record['command_id']!=c['policy']['command_id'] \
       or record['subject_digest']!=evidence['evidence_digest'] \
       or record['policy_ref']!=evidence['policy_ref']:return 'provider_binding'
    if not set(claims)<=set(record['claims']):return 'provider_claims'
    return None

def decision_error(e,kind,c):
    p=c['policy']
    if e is None or e['kind']!=kind:return 'decision_required'
    if not sealed(e,'evidence_digest'):return 'decision_digest'
    if e['scope']!=p['scope'] or e['command_id']!=p['command_id'] \
       or e['policy_ref']!=p['completion_policy_ref'] \
       or e['attempt_ids']!=c['attempt_ids']:return 'decision_binding'
    if kind=='completion' and e['effect_status']!={'sent':'possible','acknowledged':'acknowledged',
                                                  'effect_verified':'verified'}.get(e['achieved']):
        return 'completion_effect'
    claims={'completion':['completion_'+{'sent':'sent','acknowledged':'acknowledged',
                                      'effect_verified':'verified'}.get(e['achieved'],'missing')],
            'failure':['failure_confirmed'],'cancellation':['cancellation_confirmed'],
            'resolution':['resolution_supported']}[kind]
    return provider_error(e,claims,c)

def cut_error(c):
    p,cut=c['policy'],c['cut']
    if not sealed(cut,'cut_digest') or cut!=c['authoritative_cut']:return 'cut_binding'
    if (cut['command_id'],cut['scope'],cut['device_id'],cut['attempt_ids'])!=(
        p['command_id'],p['scope'],p['device_id'],c['attempt_ids']):return 'cut_owner'
    ts=cut['transmissions']
    ids=[x['permit_id'] for x in ts]
    if ids!=sorted(set(ids)) or len({x['transmission_id'] for x in ts})!=len(ts):return 'cut_identity'
    if any(t['attempt_id'] not in cut['attempt_ids'] or
           int(t['issued_revision'])>int(cut['issued_cut_revision']) for t in ts):return 'cut_member'
    return None

def release_error(e,c):
    err=cut_error(c)
    if err:return err
    p,cut=c['policy'],c['cut'];ts=cut['transmissions']
    if not sealed(e,'evidence_digest'):return 'release_digest'
    expected_ref=dict(id=cut['cut_id'],revision=c['cut_record_revision'],digest=cut['cut_digest'])
    if (e['command_id'],e['scope'],e['device_id'],e['hold_id'],e['cut_ref'],e['policy_ref'])!=(
        p['command_id'],p['scope'],p['device_id'],cut['hold_id'],expected_ref,p['release_policy_ref']):
        return 'release_binding'
    if e['future_writes_closed_ref']!=c['future_writes_closed_ref']:return 'future_writes'
    # 仅端点退役、socket ACK或当前值相同没有上述提供者的完整断言。
    claims=['future_writes_closed']
    if e['kind']=='never_sent':
        if any(t['disposition']!='not_sent' or t['settlement_kind']!='never_sent' for t in ts):
            return 'not_sent_unproven'
        claims+=['never_sent']
    else:
        if e['settlement_proof_ref']!=c['settlement_proof_ref']:return 'settlement_binding'
        if any(t['settlement_kind'] is None or
               (t['settlement_kind']=='never_sent' and t['disposition']!='not_sent') for t in ts):
            return 'unsettled_transmission'
        claims+=['module_settled' if e['kind']=='module_settled' else 'maintenance_settled']
    return provider_error(e,claims,c)

def resolution_error(r,e,before,c):
    if r is None or before['phase']!='finished':return 'resolution_requires_terminal'
    if not sealed(r,'resolution_digest'):return 'resolution_digest'
    if (r['command_id'],r['scope'],r['original_terminal_revision'])!=(
        before['command_id'],before['scope'],before['terminal_revision']):return 'resolution_binding'
    if int(r['revision'])!=c['next_resolution_revision']:return 'resolution_revision'
    err=decision_error(e,'resolution',c)
    if err:return err
    if r['resolved_outcome']!=e['resolved_outcome'] or r['evidence_refs']!=[evidence_ref(e)]:
        return 'resolution_evidence'
    if r['resolver_ref']!=c['resolver_ref']:return 'resolver_binding'
    return None

def transition_error(before,t,c):
    a,k,p=t['after'],t['kind'],c['policy']
    if before!=c['current_state'] or t['expected_state_ref']!=state_ref(before):return 'state_cas'
    err=cut_error(c)
    if err:return err
    if (a['command_id'],a['scope'])!=(before['command_id'],before['scope']) \
       or (a['command_id'],a['scope'])!=(p['command_id'],p['scope']):return 'state_owner'
    if int(a['revision'])!=int(before['revision'])+1 or int(a['revision'])>=10**20:return 'state_revision'
    if a['attempt_ids']!=c['attempt_ids'] or len(set(a['attempt_ids']))!=len(a['attempt_ids']) \
       or len(a['attempt_ids'])>p['max_attempts']:return 'attempt_set'
    e=t['decision_evidence'];release=t['release_evidence'];resolution=t['resolution']
    if before['phase']=='finished':
        if (a['phase'],a['outcome'],a['terminal_revision'])!=(
            before['phase'],before['outcome'],before['terminal_revision']):return 'terminal_immutable'
        if k not in ('reconcile','release','protect'):return 'terminal_operation'
    elif a['phase']=='finished':
        if a['terminal_revision']!=a['revision']:return 'terminal_revision'
    elif a['terminal_revision'] is not None:return 'nonterminal_revision'
    if before['automation_continuation']=='paused_latched' and a['automation_continuation']!='paused_latched':
        return 'latch_immutable'
    if k in ('timeout','block','expire','protect') and a['automation_continuation']!='paused_latched':
        return 'latch_required'
    phase,outcome=a['phase'],a['outcome']
    if k=='dispatch':
        if before['phase']!='queued' or (phase,outcome)!=('dispatching','pending'):return 'dispatch_state'
        if before['automation_continuation']=='paused_latched' or c['device_blockers'] \
           or not c['dispatch_committed'] or c['now_tick']>=c['original_deadline_tick']:return 'dispatch_gate'
    elif k=='transport':
        if before['phase']!='dispatching' or (phase,outcome)!=('awaiting_evidence','pending'):return 'transport_state'
        if not any(x['disposition']=='in_flight' for x in c['cut']['transmissions']):return 'transport_unproven'
    elif k in ('complete','fail','cancel'):
        target={'complete':'succeeded','fail':'failed','cancel':'cancelled'}[k]
        if before['phase']=='finished' or (phase,outcome)!=('finished',target):return 'finish_state'
        if k in ('complete','fail') and before['phase'] not in ('dispatching','awaiting_evidence'):
            return 'finish_state'
        if k=='cancel' and not c['cut']['transmissions'] and before['phase']=='queued':
            if not c['queued_cancel_committed']:return 'queued_cancel_unproven'
        else:
            err=decision_error(e,{'complete':'completion','fail':'failure','cancel':'cancellation'}[k],c)
            if err:return err
        if k=='complete':
            ranks={'sent':0,'acknowledged':1,'effect_verified':2}
            if e['achieved'] not in ranks or ranks[e['achieved']]<ranks[p['required_completion']]:
                return 'completion_level'
    elif k in ('block','expire'):
        if before['phase']=='finished' or (phase,outcome)!=('finished',{'block':'blocked','expire':'expired'}[k]):
            return 'stop_state'
        current=c['attempt_ids'][-1] if c['attempt_ids'] else None
        if any(x['disposition']!='not_sent' for x in c['cut']['transmissions']
               if x['attempt_id']==current):return 'stop_uncertain'
        if not c['current_attempt_closed']:return 'stop_unfenced'
        if k=='expire' and c['now_tick']<c['original_deadline_tick']:return 'not_expired'
    elif k=='timeout':
        if before['phase'] not in ('dispatching','awaiting_evidence') or (phase,outcome)!=('finished','unknown'):
            return 'timeout_state'
        if c['now_tick']<c['evidence_deadline_tick']:return 'not_timed_out'
    elif k=='retry':
        if before['phase']!='awaiting_evidence' or (phase,outcome)!=('queued','pending'):return 'retry_state'
        err=decision_error(e,'failure',c)
        if err:return err
        err=provider_error(e,['safe_failure'],c)
        if err:return err
        if e['retry_policy_ref']!=p['retry_policy_ref']:return 'retry_policy_binding'
        if p['retry_policy_ref'] is None or p['retry_policy_ref']!=c['approved_retry_policy_ref'] \
           or len(a['attempt_ids'])>=p['max_attempts'] or not c['retry_error_allowed'] \
           or not c['retry_budget_remaining'] or c['now_tick']>=c['original_deadline_tick'] \
           or before['automation_continuation']=='paused_latched':return 'retry_forbidden'
        if release is None:return 'retry_release_required'
    elif k=='reconcile':
        err=resolution_error(resolution,e,before,c)
        if err:return err
    elif k=='release':
        if before['phase']!='finished' or release is None:return 'release_state'
    elif k=='protect':
        if (phase,outcome)!=(before['phase'],before['outcome']):return 'protect_state'
    else:return 'unknown_transition'
    if resolution is not None:
        if k!='reconcile':return 'unexpected_resolution'
        if a['resolution_ref']!=resolution_ref(resolution):return 'resolution_reference'
    elif a['resolution_ref']!=before['resolution_ref']:return 'resolution_rewrite'
    if release is not None:
        err=release_error(release,c)
        if err:return err
        if a['resource_evidence_refs']!=before['resource_evidence_refs']+[evidence_ref(release)]:
            return 'release_reference'
    elif a['resource_evidence_refs']!=before['resource_evidence_refs']:return 'resource_evidence_rewrite'
    # 清理证据不等于推进结果；从未有活跃hold的纯queued取消无需虚构释放证据。
    previous_release=c['persisted_release_evidence']
    previous_clear=previous_release is not None and release_error(previous_release,c) is None \
        and evidence_ref(previous_release) in before['resource_evidence_refs']
    resource='clear' if release is not None or (
        not c['has_hold'] and not c['cut']['transmissions']) or previous_clear else (
        'unresolved' if phase=='finished' or k=='protect' else 'held')
    if a['resource_status']!=resource:return 'resource_projection'
    if outcome=='unknown' and resource=='clear' and a['resolution_ref'] is None:return 'unknown_clear_without_resolution'
    # effect是保守历史汇总；partial和verified不按简单“越大越强”排序。
    effects={before['effect_status']}|set(c['historical_effects'])
    if before['effect_status']=='possible' and k in ('block','expire','cancel') \
       and c['current_attempt_closed'] and all(x['disposition']=='not_sent' for x in c['cut']['transmissions']):
        effects.discard('possible');effects|=set(c['historical_effects'])
        effects.add('not_sent')
    if e is not None:
        if k not in ('complete','fail','cancel','retry','reconcile'):return 'unexpected_decision'
        effects.add(e['effect_status'])
    if any(x['disposition']!='not_sent' for x in c['cut']['transmissions']) or k=='dispatch':
        effects.add('possible')
    effect=next(v for v in ('partial','verified','acknowledged','possible','not_sent') if v in effects)
    if a['effect_status']!=effect:return 'effect_projection'
    completion_refs=before['completion_evidence_refs']+([evidence_ref(e)] if k=='complete' else [])
    if a['completion_evidence_refs']!=completion_refs:return 'completion_reference'
    return None

def hold_blockers(holds,transmissions):
    """已知迟到in_flight推翻never_sent核销；明确effect_resolved仍是独立模块证明。"""
    result=[]
    for hold in holds:
        pending=[t for t in transmissions if t['command_id']==hold['command_id'] and (
            t['settlement_kind'] is None or
            t['settlement_kind']=='never_sent' and t['disposition']=='in_flight')]
        if not hold['release_recorded'] or pending:result.append(copy.deepcopy(hold))
    return result
