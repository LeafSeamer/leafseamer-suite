"""仅在内存执行固定恢复事务和故障切点；不接受数据库/网络/设备参数。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUTS = [HERE / x for x in ('README.md', 'recovery.sql', 'check_recovery.py')]
INPUTS += [ROOT / 'docs' / x for x in ('rebirth-df04-storage-design.md', 'rebirth-c04-automation-design.md')]
REPORT = HERE / 'recovery-report.json'
MAX_U20 = 10**20 - 1


class Rejected(Exception):
    pass


class Injected(Exception):
    pass


def inc(value):
    if type(value) is not str or re.fullmatch(r'0|[1-9][0-9]{0,19}', value) is None:
        raise Rejected('u20_lexeme')
    result = int(value) + 1
    if result > MAX_U20:
        raise Rejected('u20_overflow')
    return str(result)


def require(ok, reason):
    if not ok:
        raise Rejected(reason)


def row(db, table, key, value):
    # table/key仅由本文件常量传入，不接收外部输入。
    result = db.execute(f'SELECT * FROM {table} WHERE {key}=?', (value,)).fetchone()
    require(result is not None, 'missing_fixture')
    return dict(result)


def new_db(kind='state_machine', mode='execute'):
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript((HERE / 'recovery.sql').read_text(encoding='utf-8'))
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert db.execute('PRAGMA recursive_triggers').fetchone()[0] == 1
    db.execute('BEGIN IMMEDIATE')
    db.execute('INSERT INTO storage_scope VALUES(1,?,?,?)', ('seamer', 'database', 'automation-storage/0.1.0-draft.2'))
    db.execute('INSERT INTO published_version VALUES(?,?,?,?,?)', ('definition', '1', 1, 'artifact', b'fixture-artifact'))
    db.execute('INSERT INTO run VALUES(?,?,?,?,?,?,?,?,?,?)', ('run', 'definition', '1', '1', '1', 'paused', 0, None, 'old-execution', None))
    source = (None, None, None) if kind == 'rule' else ('off', '1', 'on')
    db.execute('INSERT INTO execution VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('old-execution', 'run', None, 'trigger', b'fixture-trigger-decision-ref', '1', 'old-binding', 'old-plan', b'fixture-old-binding', kind, *source, 'unknown', None, None))
    db.execute('INSERT INTO activation_slot VALUES(?,?,?,?)', ('definition', '1', 'run', '1'))
    if kind == 'state_machine':
        db.execute('INSERT INTO business_state VALUES(?,?,?,?)', ('run', 'off', '1', None))
    db.execute('INSERT INTO recovery_preview VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', ('preview', 'run', '1', '1', 'old-execution', 'preview-digest', 'plan', b'fixture-preview', b'clock-domain-1', '100', '200', None))
    for latch in ('latch-a', 'latch-b'):
        db.execute('INSERT INTO pause_latch VALUES(?,?,?,?,?,?)', (latch, 'run', 'same_reason', '1', b'fixture-latch', None))
    db.commit()
    return db, {'kind': kind, 'mode': mode, 'authorized': True, 'storage_healthy': True,
                'scope': ('seamer', 'database'), 'clock': b'clock-domain-1', 'now': 150,
                'current_gates': True, 'complete_plan': True, 'old_resources_clear': True,
                'required_evidence': True, 'no_unresolved': True, 'release_evidence_valid': True, 'plan_has_device_write': mode == 'execute',
                'expected_targets': ['controller-a', 'controller-b'], 'resolved_latches': ['latch-a', 'latch-b']}


class Tx:
    def __init__(self, db, cut):
        self.db, self.cut, self.count = db, cut, 0

    def execute(self, sql, args=()):
        result = self.db.execute(sql, args)
        self.count += 1
        if self.count == self.cut:
            raise Injected(f'after_statement_{self.cut}')
        return result


def transact(db, body, context, cut=None):
    require(context['authorized'], 'forbidden')
    require(context['storage_healthy'], 'protected')
    require(tuple(db.execute('SELECT authority_id,database_id FROM storage_scope').fetchone()) == context['scope'], 'scope')
    db.execute('BEGIN IMMEDIATE')
    tx = Tx(db, cut)
    try:
        value = body(db, tx, context)
        if cut == 'before_commit':
            raise Injected('before_commit')
        db.commit()
        return value, tx.count
    except Exception:
        # 仅此内存试验用显式回滚；不概括生产IOERR/COMMIT未知的行为。
        db.rollback()
        raise


def receipt(tx, phase, business):
    identity = phase + '-' + business
    tx.execute('INSERT INTO transaction_record VALUES(?,?,?,?,?,?)', (identity, 'run', phase, business, b'fixture-redacted-audit', 'event-' + identity))
    tx.execute('INSERT INTO event_outbox VALUES(?,?,?,?)', ('event-' + identity, identity, 'payload', b'fixture-notification'))
    return identity


def reserve(db, tx, ctx):
    prior = db.execute('SELECT * FROM recovery_operation WHERE request_epoch=? AND actor_identity=? AND operation_kind=? AND idempotency_key=?', ('epoch', b'actor', 'resumeAutomationRun', 'key')).fetchone()
    if prior:
        require(prior['request_digest'] == ctx.get('request_digest', 'request'), 'identity_conflict')
        return 'existing'
    run = row(db, 'run', 'run_id', 'run'); slot = row(db, 'activation_slot', 'definition_id', 'definition')
    preview = row(db, 'recovery_preview', 'preview_id', 'preview')
    require(run['lifecycle'] == 'paused' and run['active_operation_id'] is None, 'run_state')
    require(run['revision'] == preview['run_revision'] and slot['revision'] == preview['slot_revision'], 'cas')
    require(slot['active_run_id'] == 'run' and slot['version'] == run['version'], 'slot')
    require(preview['consumed_operation_id'] is None, 'consumed')
    require(run['active_execution_id'] == preview['prior_execution_id'], 'prior_execution')
    require(ctx['clock'] == preview['clock_body'] and int(preview['issued_tick']) <= ctx['now'] < int(preview['expires_tick']), 'preview_time')
    require(ctx['current_gates'] and ctx['complete_plan'] and ctx['old_resources_clear'], 'protected')
    require(not db.execute('SELECT 1 FROM recovery_lock WHERE run_id=? AND release_id IS NULL', ('run',)).fetchone(), 'recovery_busy')
    generation, revision = inc(run['arm_generation']), inc(run['revision'])
    txid = receipt(tx, 'R2', 'operation')
    tx.execute('INSERT INTO recovery_operation VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               ('operation', 'run', 'preview', 'execution', 'epoch', b'actor', 'key', 'resumeAutomationRun', ctx.get('request_digest', 'request'), '1', 'preparing', ctx['mode'], 'plan', 'targets', json.dumps(ctx['expected_targets']).encode(), json.dumps(ctx['resolved_latches']).encode(), None, txid, 'R2'))
    source = (None, None, None) if ctx['kind'] == 'rule' else ('off', '1', 'on')
    tx.execute('INSERT INTO execution VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('execution', 'run', 'operation', 'recovery', None, generation, 'binding', 'plan', b'fixture-binding', ctx['kind'], *source, 'prepared', None, None))
    tx.execute('INSERT INTO recovery_lock VALUES(?,?,?,?)', ('operation', 'run', None, 'release'))
    for controller in ctx['expected_targets']:
        tx.execute('INSERT INTO preparation_target VALUES(?,?,?,?,?,?,?)', ('operation', controller, 'target-' + controller, b'fixture-target', 'pending', None, 'preparation'))
    count = tx.execute('UPDATE recovery_preview SET consumed_operation_id=? WHERE preview_id=? AND consumed_operation_id IS NULL', ('operation', 'preview')).rowcount
    require(count == 1, 'consumed')
    count = tx.execute('UPDATE run SET revision=?,arm_generation=?,active_operation_id=?,active_execution_id=? WHERE run_id=? AND revision=?', (revision, generation, 'operation', 'execution', 'run', preview['run_revision'])).rowcount
    require(count == 1, 'cas')
    count = tx.execute('UPDATE activation_slot SET revision=? WHERE definition_id=? AND revision=?', (inc(slot['revision']), 'definition', preview['slot_revision'])).rowcount
    require(count == 1, 'cas')
    return 'accepted'


def evidence(tx, identity, kind, authority='controller-a'):
    tx.execute('INSERT INTO external_evidence VALUES(?,?,?,?,?,?,?,?)', (identity, authority, 'remote-database', kind, identity, '1', 'evidence-digest', b'fixture-not-real-evidence'))


def prepare(db, tx, ctx):
    op = row(db, 'recovery_operation', 'operation_id', 'operation')
    require(op['state'] == 'preparing', 'operation_state')
    require(ctx['current_gates'], 'protected')
    targets = [r[0] for r in db.execute('SELECT controller_id FROM preparation_target WHERE operation_id=? ORDER BY controller_id', ('operation',))]
    require(targets == sorted(json.loads(op['targets_body'])) == sorted(ctx['expected_targets']), 'target_coverage')
    # 夹具授予完整可信回执；真实提供者、grant及来源必须在产品中另行验证。
    for controller in targets:
        evidence(tx, 'receipt-' + controller, 'preparation', controller)
        tx.execute('UPDATE preparation_target SET state=?,receipt_id=? WHERE operation_id=? AND controller_id=?', ('applied', 'receipt-' + controller, 'operation', controller))
    tx.execute('UPDATE recovery_operation SET state=?,revision=? WHERE operation_id=? AND revision=?', ('ready', inc(op['revision']), 'operation', op['revision']))
    receipt(tx, 'R3', 'operation')
    return 'ready_paused'


def start(db, tx, ctx):
    if db.execute('SELECT 1 FROM execution_start WHERE start_id=?', ('start',)).fetchone():
        return 'existing'
    run = row(db, 'run', 'run_id', 'run'); op = row(db, 'recovery_operation', 'operation_id', 'operation')
    slot = row(db, 'activation_slot', 'definition_id', 'definition')
    require(run['lifecycle'] == 'paused' and op['state'] == 'ready', 'operation_state')
    require(run['active_operation_id'] == op['operation_id'] and run['active_execution_id'] == op['execution_id'] and slot['active_run_id'] == run['run_id'], 'active_binding')
    require(ctx['current_gates'] and ctx['complete_plan'] and ctx['old_resources_clear'], 'protected')
    targets = db.execute('SELECT controller_id,state,receipt_id FROM preparation_target WHERE operation_id=? ORDER BY controller_id', ('operation',)).fetchall()
    require([r[0] for r in targets] == sorted(json.loads(op['targets_body'])) == sorted(ctx['expected_targets']) and all(r[1] == 'applied' and r[2] is not None for r in targets), 'target_coverage')
    latches = [r[0] for r in db.execute('SELECT latch_id FROM pause_latch WHERE run_id=? AND cleared_start_id IS NULL ORDER BY latch_id', ('run',))]
    require(latches == sorted(json.loads(op['resolved_latches_body'])) == sorted(ctx['resolved_latches']), 'new_latch')
    require(not (op['mode'] == 'reconcile_commit' and ctx['plan_has_device_write']), 'write_forbidden')
    txid = receipt(tx, 'R4', 'start')
    tx.execute('INSERT INTO execution_start VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', ('start', 'operation', 'run', 'execution', op['mode'], run['revision'], inc(run['revision']), slot['revision'], op['revision'], b'fixture-start', 'start-digest', txid, 'R4'))
    for latch in latches:
        tx.execute('UPDATE pause_latch SET cleared_start_id=? WHERE latch_id=? AND cleared_start_id IS NULL', ('start', latch))
    tx.execute('UPDATE recovery_operation SET state=?,revision=?,start_id=? WHERE operation_id=? AND revision=?', ('running' if op['mode'] == 'execute' else 'reconciling', inc(op['revision']), 'start', 'operation', op['revision']))
    tx.execute('UPDATE execution SET state=?,start_id=? WHERE execution_id=?', ('running', 'start', 'execution'))
    count = tx.execute('UPDATE run SET lifecycle=?,revision=?,dispatch_eligible=?,active_operation_id=NULL WHERE run_id=? AND revision=?', ('running', inc(run['revision']), int(op['mode'] == 'execute'), 'run', run['revision'])).rowcount
    require(count == 1, 'cas')
    return 'started'


def finish(db, tx, ctx):
    if db.execute('SELECT 1 FROM transition_commit WHERE execution_id=?', ('execution',)).fetchone():
        return 'existing'
    run = row(db, 'run', 'run_id', 'run'); op = row(db, 'recovery_operation', 'operation_id', 'operation')
    execution = row(db, 'execution', 'execution_id', 'execution')
    require(run['lifecycle'] == 'running' and run['active_execution_id'] == 'execution' and execution['state'] == 'running', 'execution_state')
    require(op['state'] in ('running', 'reconciling') and run['arm_generation'] == execution['arm_generation'], 'binding')
    require(ctx['current_gates'] and ctx['required_evidence'] and ctx['no_unresolved'] and ctx['release_evidence_valid'], 'protected')
    require(not db.execute('SELECT 1 FROM pause_latch WHERE run_id=? AND cleared_start_id IS NULL', ('run',)).fetchone(), 'new_latch')
    state = db.execute('SELECT * FROM business_state WHERE run_id=?', ('run',)).fetchone()
    if execution['kind'] == 'state_machine':
        require(state and state['state_id'] == execution['source_state_id'] and state['revision'] == execution['source_state_revision'], 'source_state')
        values = (state['state_id'], state['revision'], execution['target_state_id'], inc(state['revision']))
    else:
        require(state is None, 'rule_has_state')
        values = (None, None, None, None)
    txid = receipt(tx, 'R5', 'commit')
    tx.execute('INSERT INTO transition_commit VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', ('commit', 'run', 'execution', execution['kind'], *values, b'fixture-all-required-evidence', b'fixture-commit', 'commit-digest', txid, 'R5'))
    tx.execute('UPDATE execution SET state=?,commit_id=? WHERE execution_id=? AND state=?', ('succeeded', 'commit', 'execution', 'running'))
    if state:
        count = tx.execute('UPDATE business_state SET state_id=?,revision=?,last_commit_id=? WHERE run_id=? AND state_id=? AND revision=?', (values[2], values[3], 'commit', 'run', values[0], values[1])).rowcount
        require(count == 1, 'source_state')
    tx.execute('UPDATE run SET lifecycle=?,revision=?,active_execution_id=NULL,dispatch_eligible=1,last_commit_id=? WHERE run_id=? AND revision=?', ('armed', inc(run['revision']), 'commit', 'run', run['revision']))
    tx.execute('UPDATE recovery_operation SET state=?,revision=? WHERE operation_id=? AND revision=?', ('completed', inc(op['revision']), 'operation', op['revision']))
    evidence(tx, 'release', 'release')
    tx.execute('UPDATE recovery_lock SET release_id=? WHERE operation_id=?', ('release', 'operation'))
    return 'committed'


def snapshot(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {t: sorted([tuple(r) for r in db.execute(f'SELECT * FROM {t}')], key=repr) for t in tables}


def fixture(stage=0, kind='state_machine', mode='execute'):
    db, ctx = new_db(kind, mode)
    for action in (reserve, prepare, start, finish)[:stage]:
        transact(db, action, ctx)
    return db, ctx


def recovery_errors(db):
    """局部恢复关联核验；刻意不把FK检查当作全领域检查。"""
    errors = []
    if db.execute('PRAGMA foreign_key_check').fetchall():
        errors.append('fk')
    for op in db.execute('SELECT * FROM recovery_operation'):
        run = row(db, 'run', 'run_id', op['run_id'])
        ex = row(db, 'execution', 'execution_id', op['execution_id'])
        if op['state'] in ('running', 'reconciling'):
            if run['active_execution_id'] != ex['execution_id'] or run['lifecycle'] != 'running' or run['active_operation_id'] is not None:
                errors.append('started_run_projection')
            if op['mode'] == 'reconcile_commit' and run['dispatch_eligible']:
                errors.append('reconcile_dispatch')
        if op['state'] == 'completed':
            if ex['state'] != 'succeeded' or ex['commit_id'] is None:
                errors.append('completion_projection')
        if ex['commit_id']:
            c = row(db, 'transition_commit', 'commit_id', ex['commit_id'])
            if c['kind'] != ex['kind'] or c['source_state_id'] != ex['source_state_id'] or c['source_state_revision'] != ex['source_state_revision'] or c['target_state_id'] != ex['target_state_id']:
                errors.append('commit_binding')
            if run['last_commit_id'] == c['commit_id'] and c['kind'] == 'state_machine':
                state = row(db, 'business_state', 'run_id', run['run_id'])
                if (state['state_id'], state['revision'], state['last_commit_id']) != (c['target_state_id'], c['target_state_revision'], c['commit_id']):
                    errors.append('business_state_projection')
    return sorted(set(errors))


def run_checks():
    results = []
    def expect(name, actual, expected):
        if actual != expected:
            raise AssertionError(f'{name}: {actual!r} != {expected!r}')
        results.append({'case': name, 'passed': True, 'observed': actual})
    def denied(name, stage, sql, params=(), expected='SQLITE_CONSTRAINT_TRIGGER'):
        db, _ = fixture(stage); before = snapshot(db)
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute(sql, params); db.commit()
        except sqlite3.IntegrityError as error:
            actual = error.sqlite_errorname; db.rollback()
        else:
            actual = 'accepted'
        expect(name, actual, expected)
        expect(name + '_unchanged', snapshot(db) == before, True)
        db.close()
    def rejected(name, stage, action, change, reason):
        db, ctx = fixture(stage); change(db, ctx); before = snapshot(db)
        try:
            transact(db, action, ctx)
        except Rejected as error:
            actual = str(error)
        else:
            actual = 'accepted'
        expect(name, actual, reason)
        expect(name + '_unchanged', snapshot(db) == before, True)
        db.close()

    for kind in ('state_machine', 'rule'):
        for mode in ('execute', 'reconcile_commit'):
            db, ctx = fixture(0, kind, mode)
            for stage, action, expected in ((1, reserve, 'accepted'), (2, prepare, 'ready_paused'), (3, start, 'started'), (4, finish, 'committed')):
                expect(f'{kind}_{mode}_{action.__name__}', transact(db, action, ctx)[0], expected)
                expect(f'{kind}_{mode}_audit_{stage}', recovery_errors(db), [])
                if stage == 2:
                    expect(f'{kind}_{mode}_R3_still_paused', row(db, 'run', 'run_id', 'run')['lifecycle'], 'paused')
                if stage == 3:
                    expect(f'{kind}_{mode}_dispatch', row(db, 'run', 'run_id', 'run')['dispatch_eligible'], int(mode == 'execute'))
            expect(f'{kind}_{mode}_state_rows', db.execute('SELECT COUNT(*) FROM business_state').fetchone()[0], int(kind == 'state_machine'))
            expect(f'{kind}_{mode}_events', db.execute('SELECT COUNT(*) FROM event_outbox').fetchone()[0], 4)
            expect(f'{kind}_{mode}_old_unknown_preserved', row(db, 'execution', 'execution_id', 'old-execution')['state'], 'unknown')
            before = snapshot(db)
            expect(f'{kind}_{mode}_lost_response_lookup', transact(db, finish, ctx)[0], 'existing')
            expect(f'{kind}_{mode}_lookup_unchanged', snapshot(db) == before, True)
            expect(f'{kind}_{mode}_restart', db.execute('SELECT restart_action FROM recovery_inventory').fetchone()[0], 'lookup_committed')
            db.close()

    # 独立正常执行取得切点数量；每个写语句后及COMMIT前主动中断，比较全部表。
    for stage, action in enumerate((reserve, prepare, start, finish)):
        db, ctx = fixture(stage); _, count = transact(db, action, ctx); db.close()
        for cut in [*range(1, count + 1), 'before_commit']:
            db, ctx = fixture(stage); before = snapshot(db)
            try:
                transact(db, action, ctx, cut)
            except Injected:
                outcome = 'rolled_back'
            else:
                outcome = 'not_injected'
            expect(f'{action.__name__}_cut_{cut}', (outcome, snapshot(db) == before), ('rolled_back', True))
            db.close()

    # 把独立正常事务的部分行提交到相同前态，不主动抛异常，观察延迟FK在COMMIT拒绝。
    for name, stage, copied_tables in (
        ('R2_orphan_operation', 0, ('transaction_record', 'event_outbox', 'recovery_operation')),
        ('R4_orphan_start', 2, ('transaction_record', 'event_outbox', 'execution_start')),
        ('R5_orphan_commit', 3, ('transaction_record', 'event_outbox', 'transition_commit')),
    ):
        db, ctx = fixture(stage); source, _ = fixture(stage + 1); before = snapshot(db)
        db.execute('BEGIN IMMEDIATE')
        try:
            for table in copied_tables:
                prior = set(before[table])
                for value in source.execute(f'SELECT * FROM {table}'):
                    values = tuple(value)
                    if values not in prior:
                        db.execute(f'INSERT INTO {table} VALUES({",".join("?" for _ in values)})', values)
            db.commit()
        except sqlite3.IntegrityError as error:
            actual = error.sqlite_errorname; db.rollback()
        else:
            actual = 'accepted'
        expect(name, actual, 'SQLITE_CONSTRAINT_FOREIGNKEY')
        expect(name + '_unchanged', snapshot(db) == before, True)
        db.close(); source.close()

    for stage, action in ((1, reserve), (3, start)):
        db, ctx = fixture(stage); before = snapshot(db); ctx['now'] = 999
        expect(action.__name__ + '_same_identity_no_reexecute', transact(db, action, ctx)[0], 'existing')
        expect(action.__name__ + '_same_identity_all_tables_unchanged', snapshot(db) == before, True)
        db.close()

    for stage, action in ((0, reserve), (2, start), (3, finish)):
        rejected(f'{action.__name__}_forbidden', stage, action, lambda d,c: c.update(authorized=False), 'forbidden')
        rejected(f'{action.__name__}_storage', stage, action, lambda d,c: c.update(storage_healthy=False), 'protected')
        rejected(f'{action.__name__}_wrong_scope', stage, action, lambda d,c: c.update(scope=('other', 'database')), 'scope')
        rejected(f'{action.__name__}_gate', stage, action, lambda d,c: c.update(current_gates=False), 'protected')
    rejected('preview_expiry_equal', 0, reserve, lambda d,c: c.update(now=200), 'preview_time')
    rejected('preview_future', 0, reserve, lambda d,c: c.update(now=99), 'preview_time')
    rejected('preview_clock_domain', 0, reserve, lambda d,c: c.update(clock=b'other-domain'), 'preview_time')
    rejected('reserve_old_revision', 0, reserve, lambda d,c: d.execute("UPDATE run SET revision='2'"), 'cas')
    rejected('same_identity_changed_content', 1, reserve, lambda d,c: c.update(request_digest='changed'), 'identity_conflict')
    rejected('R3_reduced_targets', 1, prepare, lambda d,c: c.update(expected_targets=['controller-a']), 'target_coverage')
    rejected('R4_reduced_targets', 2, start, lambda d,c: c.update(expected_targets=['controller-a']), 'target_coverage')
    rejected('R4_before_ready', 1, start, lambda d,c: None, 'operation_state')
    rejected('R4_new_same_reason_latch', 2, start, lambda d,c: d.execute("INSERT INTO pause_latch VALUES('late','run','same_reason','2',X'00',NULL)"), 'new_latch')
    rejected('R5_missing_required_evidence', 3, finish, lambda d,c: c.update(required_evidence=False), 'protected')
    rejected('R5_unresolved', 3, finish, lambda d,c: c.update(no_unresolved=False), 'protected')
    rejected('R5_no_lock_release_evidence', 3, finish, lambda d,c: c.update(release_evidence_valid=False), 'protected')
    rejected('R5_new_latch', 3, finish, lambda d,c: d.execute("INSERT INTO pause_latch VALUES('late','run','takeover','3',X'00',NULL)"), 'new_latch')
    rejected('R5_generation_changed', 3, finish, lambda d,c: d.execute("UPDATE run SET revision='4',arm_generation='3'"), 'binding')
    db, ctx = fixture(2, mode='reconcile_commit'); ctx['plan_has_device_write'] = True
    try: transact(db, start, ctx)
    except Rejected as error: expect('reconcile_no_new_write', str(error), 'write_forbidden')
    else: raise AssertionError('reconcile写未拒绝')
    db.close()

    denied('immutable_scope', 0, "UPDATE storage_scope SET database_id='other'")
    denied('immutable_artifact', 0, "UPDATE published_version SET artifact_body=X'00'")
    denied('immutable_preview', 0, "UPDATE recovery_preview SET plan_digest='other'")
    denied('consume_without_operation', 0, "UPDATE recovery_preview SET consumed_operation_id='missing'", expected='SQLITE_CONSTRAINT_FOREIGNKEY')
    denied('clear_consumption', 1, 'UPDATE recovery_preview SET consumed_operation_id=NULL')
    denied('slot_release_paused', 1, "UPDATE activation_slot SET revision='3',active_run_id=NULL,version=NULL")
    denied('slot_wrong_version', 0, "UPDATE activation_slot SET revision='2',version='2'", expected='SQLITE_CONSTRAINT_FOREIGNKEY')
    denied('slot_no_version', 0, "UPDATE activation_slot SET revision='2',version=NULL", expected='SQLITE_CONSTRAINT_CHECK')
    denied('active_execution_missing', 1, "UPDATE run SET revision='3',active_execution_id='missing'", expected='SQLITE_CONSTRAINT_FOREIGNKEY')
    denied('operation_request_changed', 1, "UPDATE recovery_operation SET request_digest='other',revision='2',state='ready'")
    denied('drop_unresolved_lock', 1, 'DELETE FROM recovery_lock')
    denied('fake_release_kind', 2, "UPDATE recovery_lock SET release_id='receipt-controller-a'", expected='SQLITE_CONSTRAINT_FOREIGNKEY')
    denied('unpaired_start', 2, "UPDATE recovery_operation SET revision='3',state='running',start_id='missing'", expected='SQLITE_CONSTRAINT_FOREIGNKEY')
    denied('terminal_reopened', 4, "UPDATE execution SET state='running',commit_id=NULL WHERE execution_id='execution'")
    denied('old_unknown_reopened', 1, "UPDATE execution SET state='prepared' WHERE execution_id='old-execution'")
    denied('immutable_start', 3, "UPDATE execution_start SET start_digest='other'")
    denied('immutable_commit', 4, "UPDATE transition_commit SET target_state_id='other'")
    denied('immutable_evidence', 2, "UPDATE external_evidence SET body=X'00'")
    denied('immutable_event', 4, "UPDATE event_outbox SET payload_body=X'00'")
    denied('immutable_request_result', 4, "UPDATE transaction_record SET business_id='other'")
    denied('latch_cleared_again', 3, 'UPDATE pause_latch SET cleared_start_id=NULL')
    denied('release_reopened', 4, 'UPDATE recovery_lock SET release_id=NULL')
    denied('state_without_commit', 0, "UPDATE business_state SET state_id='on',revision='2'")
    denied('state_wrong_commit_projection', 4, "UPDATE business_state SET state_id='off',revision='3',last_commit_id='missing'", expected='SQLITE_CONSTRAINT_FOREIGNKEY')
    denied('event_without_transaction', 0, "INSERT INTO event_outbox VALUES('event','missing','digest',X'00')", expected='SQLITE_CONSTRAINT_FOREIGNKEY')
    denied('transaction_without_event', 0, "INSERT INTO transaction_record VALUES('tx','run','R2','operation',X'00','missing')", expected='SQLITE_CONSTRAINT_FOREIGNKEY')
    denied('new_target_after_ready', 2, "INSERT INTO preparation_target VALUES('operation','late','digest',X'00','pending',NULL,'preparation')")
    denied('replace_must_not_delete_tombstone', 4, "INSERT OR REPLACE INTO event_outbox VALUES('event-R5-commit','R5-commit','digest',X'00')")

    for value in ('', '01', '-0', '-1', '+1', '1e2', '1\n', '1\x00', '１', '100000000000000000000'):
        denied('bad_u20_' + repr(value), 0, "INSERT INTO run VALUES('second','definition','1',?,'1','paused',0,NULL,NULL,NULL)", (value,), expected='SQLITE_CONSTRAINT_CHECK')
    for value, expected in (('9', '10'), ('9223372036854775807', '9223372036854775808'), ('99999999999999999998', '99999999999999999999')):
        expect('exact_increment_' + value, inc(value), expected)
        db, _ = fixture(0)
        db.execute('UPDATE run SET revision=?', (value,))
        db.execute('UPDATE run SET revision=?', (expected,))
        expect('sql_u20_exact_storage_' + value, tuple(db.execute('SELECT revision,typeof(revision) FROM run').fetchone()), (expected, 'text'))
        db.close()
    try: inc(str(MAX_U20))
    except Rejected as error: expect('overflow', str(error), 'u20_overflow')
    else: raise AssertionError('溢出未拒绝')

    # 重要限制反证：关系正确仍可能遗漏run投影。FK通过，但恢复核验必须保护。
    db, ctx = fixture(3)
    db.execute("UPDATE run SET revision='4',lifecycle='paused',dispatch_eligible=0")
    expect('fk_cannot_prove_whole_transaction_semantics', db.execute('PRAGMA foreign_key_check').fetchall(), [])
    expect('detect_wrong_run_projection', recovery_errors(db), ['started_run_projection'])
    db.close()
    # FK容许跳修订及STRICT的无损类型转换；入口必须补词法和精确+1验证。
    db, _ = fixture(0)
    db.execute("UPDATE run SET revision='3'")
    expect('sql_monotonic_not_exact_successor', row(db, 'run', 'run_id', 'run')['revision'], '3')
    db.execute("INSERT INTO run VALUES('typed','definition','1',9,'1','paused',0,NULL,NULL,NULL)")
    expect('strict_can_coerce_integer_to_text', row(db, 'run', 'run_id', 'typed')['revision'], '9')
    db.close()
    # operation=paused不释放锁，迟到回执不能重启。
    db, ctx = fixture(1)
    db.execute("UPDATE recovery_operation SET revision='2',state='paused'")
    expect('paused_lock_held', db.execute('SELECT COUNT(*) FROM recovery_lock WHERE release_id IS NULL').fetchone()[0], 1)
    try: transact(db, prepare, ctx)
    except Rejected as error: expect('late_prepare_no_restart', str(error), 'operation_state')
    else: raise AssertionError('迟到准备重启')
    expect('restart_never_dispatch', db.execute('SELECT restart_action FROM recovery_inventory').fetchone()[0], 'protected_reconcile_targets')
    before = snapshot(db)
    db.execute('BEGIN IMMEDIATE')
    try:
        p = row(db, 'recovery_preview', 'preview_id', 'preview')
        p.update(preview_id='second-preview', consumed_operation_id='second-operation')
        o = row(db, 'recovery_operation', 'operation_id', 'operation')
        o.update(operation_id='second-operation', preview_id='second-preview', execution_id='second-execution', idempotency_key='second-key', state='preparing', tx_id='R2-second-operation')
        e = row(db, 'execution', 'execution_id', 'execution')
        e.update(execution_id='second-execution', recovery_operation_id='second-operation')
        receipt(Tx(db, None), 'R2', 'second-operation')
        for table, value in (('recovery_preview', p), ('recovery_operation', o), ('execution', e)):
            db.execute(f'INSERT INTO {table} VALUES({",".join("?" for _ in value)})', tuple(value.values()))
        db.execute("INSERT INTO recovery_lock VALUES('second-operation','run',NULL,'release')")
        db.commit()
    except sqlite3.IntegrityError as error:
        actual = error.sqlite_errorname; db.rollback()
    else:
        actual = 'accepted'
    expect('paused_operation_still_blocks_new_recovery', actual, 'SQLITE_CONSTRAINT_UNIQUE')
    expect('second_recovery_rollback_all_tables', snapshot(db) == before, True)
    db.close()
    return results


def hashes(staged=False):
    result = {}
    for path in INPUTS:
        relative = path.relative_to(ROOT).as_posix()
        data = subprocess.check_output(['git', 'show', ':' + relative], cwd=ROOT) if staged else path.read_bytes()
        result[relative] = hashlib.sha256(data).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged仅用于--check-report')
    if args.check_report:
        data = subprocess.check_output(['git', 'show', ':' + REPORT.relative_to(ROOT).as_posix()], cwd=ROOT) if args.staged else REPORT.read_bytes()
        assert json.loads(data)['artifact_sha256'] == hashes(args.staged), '报告输入字节不匹配'
        print(json.dumps({'input_bindings': len(INPUTS), 'matched': True})); return
    results = run_checks()
    report = {'format': 'automation-recovery-storage-reference/1', 'approved': False,
              'python': sys.version.split()[0], 'sqlite': sqlite3.sqlite_version,
              'checks_passed': len(results), 'all_passed': True, 'cases': results,
              'runtime_validation': {'production_writer': 0, 'concurrent_connections': 0, 'disk_crash': 0, 'ipc': 0, 'devices': 0},
              'artifact_sha256': hashes()}
    if args.report:
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('cases', 'artifact_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
