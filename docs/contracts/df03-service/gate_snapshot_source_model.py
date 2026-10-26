"""从已封存时间State确定性重建拒绝下界；离线候选，不签发UTC或OPEN资格。"""
import copy
import importlib.util
import json
from pathlib import Path
from jsonschema import Draft202012Validator
_spec = importlib.util.spec_from_file_location('gate_snapshot_service_reference', Path(__file__).with_name('reference_model.py'))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

T = S.T
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REFERENCE = json.loads((BASE/'df03-reference/reference.schema.json').read_bytes())
IPC = json.loads((BASE/'c04-lifecycle/continuation-binding-ipc.schema.json').read_bytes())
SHARED = ('authority_service_id', 'database_instance_id', 'clock_domain_id', 'descriptor_digest')


def need(value, reason):
    if not value:
        raise ValueError(reason)


def validate(name, value):
    Draft202012Validator({'$defs': REFERENCE['$defs'], '$ref': '#/$defs/'+name}).validate(value)


def raw(value):
    return T.rfc8785.dumps(value)


def original(data, name, digest=None):
    need(isinstance(data, bytes) and len(data) <= 65536, 'time_original_capacity')
    value = json.loads(data)
    validate(name, value)
    # 已持久原件必须恰为规范字节；重复键、额外空白及非规范数字不能混入。
    need(raw(value) == data, 'time_original_canonical')
    if digest:
        need(T.intact(value, digest), 'time_original_digest')
    return value


def one(db, sql, args=()):
    cursor = db.execute(sql, args)
    rows = cursor.fetchall()
    need(len(rows) == 1, 'time_source_cardinality')
    return dict(zip((c[0] for c in cursor.description), rows[0]))


def source(db, revision):
    """查历史原件，不据此声称该原件当前有效。事务由调用者拥有。"""
    need(db.in_transaction, 'time_source_transaction')
    validate('Positive', revision)
    row = one(db, 'SELECT s.*,c.kind FROM ts_state s JOIN ts_commit c ON c.id=s.commit_id '
        'JOIN ts_seal z ON z.commit_id=c.id JOIN ts_audit a ON a.commit_id=c.id '
        'JOIN ts_outbox o ON o.commit_id=c.id WHERE s.revision=?', (revision.zfill(20),))
    state = original(row['body'], 'AuthorityState', 'state_digest')
    b = one(db, 'SELECT * FROM ts_binding WHERE id=?', (row['binding_id'],))
    binding = original(b['body'], 'Binding')
    scope = one(db, 'SELECT * FROM ts_scope WHERE id=?', (b['scope_id'],))
    need(state['revision'] == revision and state['binding'] == binding and state['status'] == row['status'], 'time_state_columns')
    need(binding['time_generation'].zfill(20) == b['generation'], 'time_generation_columns')
    need((binding['domain']['authority_service_id'], binding['domain']['database_instance_id']) ==
         (scope['authority'], scope['database_id']), 'time_scope')
    need(row['kind'] == {'collecting':'bootstrap', 'qualified':'publish', 'unavailable':'invalidate'}.get(state['status']), 'time_state_commit_kind')
    if state['status'] == 'qualified':
        a = one(db, 'SELECT * FROM ts_anchor WHERE id=? AND binding_id=?', (row['anchor_id'], b['id']))
        anchor = original(a['body'], 'Anchor', 'anchor_digest')
        need(anchor['binding'] == binding and anchor['anchor_id'] == a['id'] and
             anchor['anchor_tick_ns'].zfill(20) == a['tick'] and
             state['current_anchor_ref'] == T.object_ref(anchor, 'anchor_id', 'anchor_digest'), 'time_anchor_columns')
    else:
        need(row['anchor_id'] is None and state['current_anchor_ref'] is None, 'time_unqualified_anchor')
    if state['status'] == 'unavailable':
        i = one(db, 'SELECT * FROM ts_invalidation WHERE commit_id=?', (row['commit_id'],))
        invalidation = original(i['body'], 'Invalidation', 'invalidation_digest')
        old = one(db, 'SELECT * FROM ts_binding WHERE id=?', (i['old_binding'],))
        old_binding = original(old['body'], 'Binding')
        need(invalidation['invalidation_id'] == i['id'] and i['new_binding'] == b['id'] and
             invalidation['old_binding'] == old_binding and old_binding['time_generation'].zfill(20) == old['generation'] and
             int(invalidation['next_time_generation']) == int(old_binding['time_generation'])+1 == int(binding['time_generation']) and
             state['invalidation_ref'] == T.object_ref(invalidation, 'invalidation_id', 'invalidation_digest'), 'time_invalidation_columns')
    return state


def derive(state):
    validate('AuthorityState', state)
    need(T.intact(state, 'state_digest'), 'time_state_digest')
    state_ref = T.object_ref(state, 'state_id', 'state_digest')
    domain = state['binding']['domain']
    identity = dict(format_version='time-floor-source/1', domain=domain, state_ref=state_ref)
    result = T.seal(dict(snapshot_id='time-snapshot.'+T.digest(identity).split(':')[1],
        domain=copy.deepcopy(domain), snapshot_revision=state['revision'],
        minimum_time_generation=state['binding']['time_generation'], state_ref=state_ref), 'snapshot_digest')
    Draft202012Validator({'$defs': IPC['$defs'], '$ref': '#/$defs/S12__GateSnapshot'}).validate(result)
    return result


def current(db, expected_provider_domain):
    validate('Domain', expected_provider_domain)
    need(db.in_transaction, 'time_source_transaction')
    revision = str(int(one(db, 'SELECT revision FROM ts_head WHERE id=1')['revision']))
    state = source(db, revision)
    need(state['binding']['domain'] == expected_provider_domain, 'time_provider_domain')
    return derive(state)


def for_open(db, snapshot, expected_provider_domain, exit_binding, retained=None):
    """仅时间来源子判定；调用者还须重读真实监督、授权及所有OPEN资格。"""
    candidate = current(db, expected_provider_domain)
    need(candidate == snapshot, 'time_snapshot_stale_or_forged')
    # Provider和worker不是同一个进程；只比较共同命名空间及完整共享时钟身份。
    need(all(exit_binding.get(k) == candidate['domain'][k] for k in SHARED), 'time_exit_clock')
    if retained is not None:
        need(S.install_floor(candidate, copy.deepcopy(retained), candidate) in ('installed', 'duplicate'), 'time_retained_floor')
    return copy.deepcopy(candidate)
