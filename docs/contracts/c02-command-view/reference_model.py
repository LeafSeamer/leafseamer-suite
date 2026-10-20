"""只在人工权威快照上判定；无HTTP、签名、数据库、IPC或设备操作。"""
import copy
import hashlib
import rfc8785


def digest(value):
    return 'sha256:'+hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def seal(value, key):
    value[key]=digest({k:v for k,v in value.items() if k!=key})
    return value


def valid_digest(value, key):
    return value[key]==digest({k:v for k,v in value.items() if k!=key})


def state_ref(state):
    return dict(id=state['command_id'],revision=state['revision'],digest=digest(state))


def authorize(c, permission):
    # c来自可信提供者夹具，不是HTTP请求字段。
    if not c['authenticated']:
        return 'unauthenticated'
    if permission not in c['permissions']:
        return 'forbidden'
    if c['subject_kind']=='human':
        return None if c['device_id'] in c['allowed_devices'] else 'forbidden'
    if c['subject_kind']=='service' and c['paired'] and c['origin']=='automation' \
       and c['service_id']==c['originating_service_id']:
        return None
    return 'forbidden'


def record_error(v, c):
    s=v['state']
    if v['scope']!=c['scope'] or s['scope']!=v['scope'] or v['command_id']!=c['command_id'] \
       or s['command_id']!=v['command_id'] or v['revision']!=s['revision']:
        return 'record_owner'
    if not valid_digest(v,'record_digest') or v['state_ref']!=state_ref(s):
        return 'record_digest'
    if s!=c['state'] or v['policy']!=c['policy']:
        return 'authoritative_state'
    if v['initial_command_ref']!=c['initial_command_ref'] or v['request_identity']!=c['request_identity']:
        return 'admission_binding'
    if v['initial_command_ref']['revision']!='1' or v['initial_command_ref']['scope']!=v['scope'] \
       or v['initial_command_ref']['object_id']!=v['command_id']:
        return 'initial_ref'
    for k in ('target','actor','origin','run_binding','automation_binding','accepted_at','dispatch','control_binding'):
        if v[k]!=c['immutable'][k]:
            return 'immutable_metadata'
    p=v['policy']
    if p['command_id']!=v['command_id'] or p['scope']!=v['scope'] or p['device_id']!=v['target']['device_id']:
        return 'policy_owner'
    if [a['attempt_id'] for a in v['attempts']]!=s['attempt_ids'] \
       or [a['ordinal'] for a in v['attempts']]!=list(range(1,len(v['attempts'])+1)) \
       or v['attempts']!=c['attempts']:
        return 'attempt_set'
    if len(v['attempts'])>p['max_attempts']:
        return 'attempt_budget'
    if s['phase']=='finished' and (s['resource_status']=='held' or int(s['terminal_revision'])>int(s['revision'])):
        return 'terminal_binding'
    if s['phase'] in ('dispatching','awaiting_evidence') and not v['attempts']:
        return 'attempt_required'
    completion=v['completion']
    if completion['required']!=p['required_completion'] or completion['policy_ref']!=p['completion_policy_ref'] \
       or completion['evidence_refs']!=s['completion_evidence_refs'] or completion!=c['completion']:
        return 'completion_binding'
    levels=['sent','acknowledged','effect_verified']
    if s['outcome']=='succeeded' and (completion['achieved'] not in levels or not completion['evidence_refs']
       or levels.index(completion['achieved'])<levels.index(completion['required'])):
        return 'completion_level'
    if v['cancellation']!=c['cancellation']:
        return 'cancellation_binding'
    if v['evidence_index']!=c['evidence_index'] or v['evidence_index']['state_ref']!=v['state_ref']:
        return 'evidence_snapshot'
    return None


def read_command(v, c, historical=False):
    error=authorize(c,'command.read')
    if error:
        return error,None
    if not historical and not c['current_publishable']:
        return 'state_projection_pending',None
    error=record_error(v,c)
    if error:
        return 'unavailable',None
    return None,dict(view='historical' if historical else 'current',record=copy.deepcopy(v))


def cancel_identity(request, c):
    context=c['context']
    key=dict(target_scope=c['scope'],issuer_id=context['issuer_id'],issuer_epoch=context['issuer_epoch'],
        principal_id=context['principal_id'],request_epoch=context['context_epoch'],
        operation_id='cancelCommand',idempotency_key=request['idempotency_key'])
    content=dict(scope=c['scope'],command_id=c['command_id'],expected_state_ref=request['expected_state_ref'],
                 reason=request['reason'])
    return dict(key=key,request_digest=digest(content))


def namespace_matches(key,c):
    return key['target_scope']==c['scope'] and \
        [key[k] for k in ('issuer_id','issuer_epoch','principal_id','request_epoch')] in c['owned_namespaces']


def cancel_step(request, c, ledger):
    """字典赋值仅模拟一个原子步骤；没有实际取消或屏障。"""
    error=authorize(c,'command.cancel')
    if error:
        return error,None
    if c['subject_kind']=='human' and not c['csrf_valid']:
        return 'forbidden',None
    if request['context_id']!=c['context']['context_id'] or not c['namespace_owned']:
        return 'forbidden',None
    identity=cancel_identity(request,c)
    if not namespace_matches(identity['key'],c):
        return 'forbidden',None
    key=rfc8785.dumps(identity['key'])
    if key in ledger:
        previous=ledger[key]
        if previous['identity']!=identity:
            return 'identity_conflict',None
        return 'existing',copy.deepcopy(previous)
    if not c['context_live']:
        return 'context_expired',None
    if request['expected_state_ref']!=state_ref(c['state']):
        return 'state_conflict',None
    if any(v['command_id']==c['command_id'] and v['scope']==c['scope'] for v in ledger.values()):
        return 'cancellation_exists',None
    if not c['capacity_available']:
        return 'capacity',None
    if not c['storage_available']:
        return 'unavailable',None
    operation=seal(dict(cancellation_id=c['new_cancellation_id'],scope=c['scope'],command_id=c['command_id'],
        revision='1',identity=identity,state='requested',mode=c['cancel_mode'],future_writes='pending',
        command_state_ref=c['observed_state_ref'],evidence_refs=[],reason_code=None,operation_digest=''),'operation_digest')
    receipt=seal(dict(identity=identity,command_id=c['command_id'],scope=c['scope'],
        cancellation_id=c['new_cancellation_id'],
        initial_operation_ref=dict(id=operation['cancellation_id'],revision='1',digest=operation['operation_digest']),
        accepted_state_ref=request['expected_state_ref'],receipt_digest=''), 'receipt_digest')
    ledger[key]=copy.deepcopy(receipt)
    return 'accepted',receipt


def cancellation_error(v,c):
    if v['command_id']!=c['command_id'] or v['scope']!=c['scope']:
        return 'cancel_owner'
    if not valid_digest(v,'operation_digest') or v['identity']!=c['identity']:
        return 'cancel_binding'
    before,after=c['before_state'],c['after_state']
    if v['command_state_ref']!=state_ref(after):
        return 'cancel_state_ref'
    if before['phase']=='finished' and any(before[k]!=after[k] for k in ('phase','outcome','terminal_revision')):
        return 'terminal_immutable'
    if before['automation_continuation']=='paused_latched' and after['automation_continuation']!='paused_latched':
        return 'latch_immutable'
    if v['future_writes']=='closed' and not c['closure_proven']:
        return 'closure_unproven'
    if v['state']=='confirmed' and (not c['cancellation_proven'] or v['future_writes']!='closed'):
        return 'cancellation_unproven'
    if v['state']=='too_late' and not c['prior_completion_proven']:
        return 'completion_unproven'
    if after['resource_status']=='clear' and not c['resource_clear_proven']:
        return 'release_unproven'
    old=c['previous_operation']
    if old:
        if any(v[k]!=old[k] for k in ('cancellation_id','identity','scope','command_id','mode')) \
           or int(v['revision'])!=int(old['revision'])+1:
            return 'cancel_successor'
        if old['state'] in ('confirmed','unsupported','failed','too_late') and v['state']!=old['state']:
            return 'cancel_final'
        if old['state']=='indeterminate' and v['state']=='requested':
            return 'cancel_reopen'
        if old['future_writes']=='closed' and v['future_writes']!='closed':
            return 'closure_rewrite'
    return None


def lookup_cancel(identity,c,ledger):
    error=authorize(c,'command.read')
    if error:
        return error,None
    if not c['namespace_owned'] or not namespace_matches(identity['key'],c):
        return 'forbidden',None
    if not c['storage_available']:
        return None,dict(state='indeterminate',receipt=None)
    previous=ledger.get(rfc8785.dumps(identity['key']))
    if previous is None:
        return None,dict(state='not_found',receipt=None)
    if previous['command_id']!=c['command_id']:
        return 'not_found',None
    if previous['identity']!=identity:
        return 'identity_conflict',None
    return None,dict(state='found',receipt=copy.deepcopy(previous))


def evidence_error(v,c):
    if v['scope']!=c['scope'] or v['command_id']!=c['command_id']:
        return 'evidence_owner'
    if not valid_digest(v,'view_digest'):
        return 'evidence_digest'
    body=v['body']
    if body['command_id']!=v['command_id'] or ('scope' in body and body['scope']!=v['scope']):
        return 'evidence_body_owner'
    field={'observation':'evidence_id','decision':'evidence_id','release':'evidence_id',
           'resolution':'resolution_id','invalidation':'invalidation_id'}[v['kind']]
    if body[field]!=v['source_ref']['id']:
        return 'evidence_body_identity'
    digest_field={'decision':'evidence_digest','release':'evidence_digest','resolution':'resolution_digest'}.get(v['kind'])
    expected=body[digest_field] if digest_field else digest(body)
    if expected!=v['source_ref']['digest'] or (digest_field and not valid_digest(body,digest_field)):
        return 'evidence_body_digest'
    key=(v['kind'],v['source_ref']['id'],v['source_ref']['revision'])
    if key not in c['evidence'] or v!=c['evidence'][key]:
        return 'evidence_source'
    return None


def page_error(page,c):
    error=authorize(c,'command.evidence.read')
    if error:
        return error
    if page['scope']!=c['scope'] or page['command_id']!=c['command_id'] \
       or page['snapshot_ref']!=c['snapshot_ref'] or page['state_ref']!=c['snapshot_state_ref']:
        return 'snapshot_binding'
    if not valid_digest(page,'page_digest'):
        return 'page_digest'
    if not c['cursor_bound']:
        return 'cursor_binding'
    if c['cursor_expired']:
        return 'snapshot_gone'
    offset=int(page['offset'])
    expected=c['ordered_evidence'][offset:offset+c['limit']]
    if offset!=c['expected_offset'] or offset>len(c['ordered_evidence']) \
       or int(page['total'])!=len(c['ordered_evidence']) or page['items']!=expected:
        return 'page_members'
    for value in page['items']:
        error=evidence_error(value,c)
        if error:
            return error
    if (page['next_cursor'] is not None)!=(offset+len(expected)<len(c['ordered_evidence'])):
        return 'page_continuation'
    return None
