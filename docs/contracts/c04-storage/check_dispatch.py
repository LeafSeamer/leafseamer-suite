"""执行层内存SQLite参考检查；不发送命令，不接受外部数据库或设备地址。"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import check_recovery as core

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPORT = HERE / 'dispatch-report.json'
INPUTS = [HERE / n for n in ('DISPATCH.md', 'dispatch.sql', 'check_dispatch.py', 'recovery.sql', 'check_recovery.py')]
INPUTS += [HERE.parent / 'c04-execution/execution.schema.json', ROOT / 'docs/rebirth-c04-automation-design.md', ROOT / 'docs/rebirth-df04-storage-design.md']


def blob(value):
    # 合成夹具序列化，不声称这是生产JCS或摘要算法。
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def put(tx, table, **values):
    # 表与列都在本文件静态指定；不接收外部SQL标识符。
    return tx.execute(f'INSERT INTO {table}({",".join(values)}) VALUES({",".join("?" for _ in values)})', tuple(values.values()))


def step(db):
    return dict(db.execute("SELECT * FROM step_state WHERE execution_id='execution' AND step_id='step'").fetchone())


def gates(db, ctx, writing=False):
    r = core.row(db, 'run', 'run_id', 'run')
    e = core.row(db, 'execution', 'execution_id', 'execution')
    core.require(r['active_execution_id'] == e['execution_id'] and r['lifecycle'] == 'running' and e['state'] == 'running' and r['arm_generation'] == e['arm_generation'], 'execution_current')
    core.require(ctx['current_gates'] and ctx['runtime_current'], 'protected')
    core.require(not db.execute("SELECT 1 FROM pause_latch WHERE run_id='run' AND cleared_start_id IS NULL").fetchone(), 'latch')
    if writing:
        core.require(r['dispatch_eligible'] == 1 and ctx['parameters_verified'] and ctx['budget_valid'] and ctx['window_valid'], 'write_gate')


def plan(db, tx, ctx):
    core.require(ctx['whole_plan_verified'], 'plan_unqualified')
    txid = core.receipt(tx, 'PLAN', 'execution')
    put(tx, 'execution_plan_set', execution_id='execution', run_id='run', expected_steps=1, plan_digest='plan', plan_body=b'fixture-complete-plan', sealed=0, tx_id=txid)
    put(tx, 'execution_step_plan', execution_id='execution', step_id='step', kind=ctx['step_kind'], ordinal=0, required=1, plan_digest='step-plan', plan_body=b'fixture-step-plan')
    put(tx, 'step_state', execution_id='execution', step_id='step', revision='1', state='waiting', outcome='pending')
    tx.execute("UPDATE execution_plan_set SET sealed=1 WHERE execution_id='execution'")
    return 'sealed'


def anchor(db, tx, ctx):
    if db.execute("SELECT 1 FROM execution_anchor WHERE execution_id='execution'").fetchone():
        return 'existing'
    gates(db, ctx)
    core.require(ctx['origin_commit_observed'], 'origin_commit_unconfirmed')
    e = core.row(db, 'execution', 'execution_id', 'execution')
    txid = core.receipt(tx, 'ANCHOR', 'anchor')
    put(tx, 'execution_anchor', anchor_id='anchor', execution_id='execution', run_id='run', origin_kind=e['origin_kind'],
        start_id=e['start_id'], trigger_decision_ref_body=e['trigger_decision_ref_body'], clock_body=ctx['clock'], tick_ns=str(ctx['now']),
        anchor_digest='anchor-digest', anchor_body=b'fixture-anchor', tx_id=txid)
    return 'anchored'


def ready(db, tx, ctx):
    if db.execute("SELECT 1 FROM step_ready WHERE execution_id='execution' AND step_id='step'").fetchone():
        return 'existing'
    gates(db, ctx)
    core.require(ctx['dependencies_verified'], 'dependencies')
    s = step(db); core.require(s['state'] == 'waiting', 'step_state')
    txid = core.receipt(tx, 'READY', 'ready')
    put(tx, 'step_ready', ready_id='ready', execution_id='execution', step_id='step', run_id='run', plan_digest='step-plan', anchor_id='anchor', clock_body=ctx['clock'], tick_ns=str(ctx['now']), dependencies_digest='dependencies', dependencies_body=b'fixture-dependencies', ready_digest='ready-digest', ready_body=b'fixture-ready', tx_id=txid)
    core.require(tx.execute("UPDATE step_state SET ready_id='ready',state='ready',revision=? WHERE execution_id='execution' AND step_id='step' AND revision=?", (core.inc(s['revision']), s['revision'])).rowcount == 1, 'cas')
    return 'ready'


def identity(ctx):
    return dict(target_authority='controller', target_database='controller-db', issuer_id='issuer', principal_id='principal', request_epoch='epoch', operation_id='createCommand', idempotency_key=ctx.get('key', 'key'), request_digest=ctx.get('request_digest', 'request-digest'))


def submit(db, tx, ctx):
    prior = db.execute("SELECT * FROM command_submission WHERE submission_id='submission'").fetchone()
    wanted = identity(ctx)
    if prior:
        core.require(all(prior[k] == v for k,v in wanted.items()), 'identity_conflict')
        return 'existing'
    gates(db, ctx, writing=True)
    core.require(ctx['step_kind']=='action', 'not_action')
    s = step(db); core.require(s['state'] == 'ready', 'step_state')
    txid = core.receipt(tx, 'SUBMISSION', 'submission')
    put(tx, 'command_submission', submission_id='submission', execution_id='execution', step_id='step', run_id='run', **wanted,
        request_body=b'fixture-request-without-token-or-context', parameters_ref_body=b'fixture-parameters-ref', state='planned', tx_id=txid)
    tx.execute("UPDATE step_state SET revision=?,state='submission_pending',submission_id='submission' WHERE execution_id='execution' AND step_id='step'", (core.inc(s['revision']),))
    return 'planned_no_send'


def attempt(db, tx, ctx):
    s = core.row(db, 'command_submission', 'submission_id', 'submission')
    if s['state'] != 'planned':
        return 'query_only'
    gates(db, ctx, writing=True)
    core.require(step(db)['state'] == 'submission_pending', 'step_state')
    a = core.row(db, 'execution_anchor', 'anchor_id', 'anchor')
    core.require(a['clock_body'] == ctx['clock'], 'clock_domain')
    txid = core.receipt(tx, 'ATTEMPT', 'attempt')
    put(tx, 'submission_attempt', attempt_id='attempt', submission_id='submission', run_id='run', runtime_binding_ref_body=b'fixture-runtime-ref', clock_body=ctx['clock'], tick_ns=str(ctx['now']), attempt_body=b'fixture-attempt', tx_id=txid)
    tx.execute("UPDATE command_submission SET state='attempt_recorded',attempt_id='attempt' WHERE submission_id='submission' AND state='planned'")
    # transact确认COMMIT后才返回此标记；它不调用I/O，重开账本不会再次生成此值。
    return 'live_path_call_once'


def response(ctx, result='accepted'):
    scope = dict(authority_service_id='controller', database_instance_id='controller-db')
    return dict(identity=identity(ctx), result=result, durable=True, trusted=True,
                receipt_ref=dict(scope=dict(scope), object_id='remote-adjudication', revision='1', digest='receipt'),
                command_ref=dict(scope=dict(scope), object_id='remote-command', revision='1', digest='command') if result == 'accepted' else None)


def adjudicate(db, tx, ctx):
    incoming = ctx['response']; s = core.row(db, 'command_submission', 'submission_id', 'submission')
    core.require(incoming['trusted'] and incoming['identity'] == {k:s[k] for k in identity(ctx)}, 'response_binding')
    if s['state'] in ('accepted', 'rejected'):
        saved = core.row(db, 'submission_adjudication', 'adjudication_id', s['adjudication_id'])
        core.require(saved['receipt_body'] == blob(incoming), 'terminal_conflict')
        return 'existing'
    core.require(s['state'] in ('attempt_recorded', 'indeterminate'), 'not_attempted')
    if incoming['result'] not in ('accepted', 'rejected_final') or not incoming['durable']:
        core.receipt(tx, 'SUBMISSION_OBSERVATION', ctx.get('query_id', 'query-1'))
        tx.execute("UPDATE command_submission SET state='indeterminate' WHERE submission_id='submission'")
        return 'query_only'
    scope = dict(authority_service_id=s['target_authority'], database_instance_id=s['target_database'])
    core.require(incoming['receipt_ref'] is not None and incoming['receipt_ref']['scope'] == scope, 'receipt_scope')
    if incoming['result'] == 'accepted':
        core.require(incoming['command_ref'] is not None and incoming['command_ref']['scope'] == scope, 'command_scope')
    else:
        core.require(incoming['command_ref'] is None, 'rejection_command')
    outcome = 'accepted' if incoming['result'] == 'accepted' else 'rejected'
    txid = core.receipt(tx, 'ADJUDICATION', 'adjudication')
    put(tx, 'submission_adjudication', adjudication_id='adjudication', submission_id='submission', run_id='run', target_authority=s['target_authority'], target_database=s['target_database'], request_digest=s['request_digest'], outcome=outcome,
        command_ref_body=blob(incoming['command_ref']) if outcome == 'accepted' else None, receipt_ref_body=blob(incoming['receipt_ref']), receipt_body=blob(incoming), tx_id=txid)
    tx.execute("UPDATE command_submission SET state=?,adjudication_id='adjudication' WHERE submission_id='submission'", (outcome,))
    # 迟到受理可以补原身份归属，但不能把已经unknown的步骤改回pending或成功。
    st = step(db)
    if outcome == 'accepted' and st['outcome'] == 'pending':
        tx.execute("UPDATE step_state SET state='accepted',revision=? WHERE execution_id='execution' AND step_id='step'", (core.inc(st['revision']),))
    return outcome


def terminal(db, tx, ctx):
    st = step(db); outcome = ctx.get('outcome', 'succeeded')
    if st['outcome'] != 'pending':
        core.require(st['outcome'] == outcome, 'terminal_conflict')
        return 'existing'
    core.require(ctx['terminal_evidence_verified'], 'terminal_evidence')
    if outcome == 'succeeded':
        core.require(ctx['completion_verified'], 'completion_evidence')
        if ctx['step_kind'] == 'action':
            a = db.execute("SELECT * FROM submission_adjudication WHERE submission_id='submission'").fetchone()
            core.require(a is not None and a['outcome'] == 'accepted' and a['command_ref_body'] == blob(ctx['completion_command_ref']), 'completion_command')
    txid = core.receipt(tx, 'STEP_TERMINAL', 'terminal')
    put(tx, 'step_terminal', terminal_id='terminal', execution_id='execution', step_id='step', run_id='run', outcome=outcome,
        evidence_body=b'fixture-qualified-terminal-evidence', result_ref_body=b'fixture-validated-result-ref' if outcome == 'succeeded' else None, tx_id=txid)
    state = 'indeterminate' if outcome == 'unknown' else 'cancelled' if outcome == 'cancelled' else 'retained' if ctx['step_kind'] == 'retain_success' and outcome == 'succeeded' else 'finished'
    tx.execute("UPDATE step_state SET state=?,outcome=?,terminal_id='terminal',revision=? WHERE execution_id='execution' AND step_id='step'", (state, outcome, core.inc(st['revision'])))
    return outcome


def fixture(stage=0, kind='action', mode='execute', origin='recovery'):
    if origin == 'recovery':
        db, ctx = core.fixture(2, mode=mode)
    else:
        db=sqlite3.connect(':memory:',isolation_level=None);db.row_factory=sqlite3.Row
        db.executescript((HERE/'recovery.sql').read_text(encoding='utf-8'))
        seed=core.Tx(db,None)
        put(seed,'storage_scope',singleton=1,authority_id='seamer',database_id='database',format_version='automation-storage/0.1.0-draft.2')
        put(seed,'published_version',definition_id='definition',version='1',artifact_digest='artifact',artifact_body=b'fixture-artifact')
        put(seed,'run',run_id='run',definition_id='definition',version='1',revision='1',arm_generation='2',lifecycle='armed',dispatch_eligible=1)
        put(seed,'activation_slot',definition_id='definition',revision='1',active_run_id='run',version='1')
        put(seed,'business_state',run_id='run',state_id='off',revision='1')
        put(core.Tx(db, None), 'execution', execution_id='execution', run_id='run', origin_kind='trigger', trigger_decision_ref_body=b'fixture-trigger-ref', arm_generation='2', binding_digest='binding', plan_digest='plan', binding_body=b'fixture-binding', kind='state_machine', source_state_id='off', source_state_revision='1', target_state_id='on', state='prepared')
        ctx=dict(authorized=True,storage_healthy=True,scope=('seamer','database'),clock=b'clock-domain-1',current_gates=True)
    db.executescript((HERE / 'dispatch.sql').read_text(encoding='utf-8'))
    ctx.update(step_kind=kind, whole_plan_verified=True, dependencies_verified=True, parameters_verified=True,
               budget_valid=True, window_valid=True, runtime_current=True, origin_commit_observed=True,
               terminal_evidence_verified=True, completion_verified=True)
    core.transact(db, plan, ctx)
    if origin == 'recovery':
        core.transact(db, core.start, ctx)
    else:
        # 合成普通受理前态，不声称实现TriggerDecision和源事件的原子受理。
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE execution SET state='running' WHERE execution_id='execution'")
        db.execute("UPDATE run SET active_execution_id='execution',revision='2',arm_generation='2',lifecycle='running',dispatch_eligible=1")
        db.commit()
    ctx['now'] = 1000
    ctx['response'] = response(ctx)
    ctx['completion_command_ref'] = ctx['response']['command_ref']
    for action in (anchor, ready, submit, attempt, adjudicate, terminal)[:stage]:
        core.transact(db, action, ctx)
    return db, ctx


def run_checks():
    results = []
    def expect(name, actual, expected):
        if actual != expected: raise AssertionError(f'{name}: {actual!r} != {expected!r}')
        results.append(dict(case=name, passed=True, observed=actual))
    def reject(name, stage, action, change, reason):
        db, ctx = fixture(stage); change(db, ctx); before = core.snapshot(db)
        try: core.transact(db, action, ctx)
        except core.Rejected as error: actual = str(error)
        else: actual = 'accepted'
        expect(name, actual, reason); expect(name + '_unchanged', core.snapshot(db) == before, True); db.close()
    def sql_reject(name, stage, statement, params=(), reason='SQLITE_CONSTRAINT_TRIGGER'):
        db, _ = fixture(stage); before = core.snapshot(db); db.execute('BEGIN IMMEDIATE')
        try: db.execute(statement, params); db.commit()
        except sqlite3.IntegrityError as error: actual = error.sqlite_errorname; db.rollback()
        else: actual = 'accepted'
        expect(name, actual, reason); expect(name + '_unchanged', core.snapshot(db) == before, True); db.close()

    db, ctx = fixture(0)
    expect('table_count', len(core.snapshot(db)), 25)
    for action, expected in ((anchor,'anchored'),(ready,'ready'),(submit,'planned_no_send'),(attempt,'live_path_call_once'),(adjudicate,'accepted'),(terminal,'succeeded')):
        expect(action.__name__, core.transact(db, action, ctx)[0], expected)
    expect('R5_after_evidence', core.transact(db, core.finish, ctx)[0], 'committed')
    expect('old_unknown_preserved', core.row(db,'execution','execution_id','old-execution')['state'], 'unknown')
    expect('integrity', db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
    expect('foreign_keys', db.execute('PRAGMA foreign_key_check').fetchall(), [])
    db.close()
    db,ctx=fixture(5)
    db.execute("UPDATE step_state SET state='awaiting_evidence',revision=?",(core.inc(step(db)['revision']),))
    expect('accepted_can_await_evidence',step(db)['state'],'awaiting_evidence')
    expect('awaiting_evidence_can_finish',core.transact(db,terminal,ctx)[0],'succeeded')
    expect('awaiting_path_R5',core.transact(db,core.finish,ctx)[0],'committed');db.close()
    db,ctx=fixture(5);ctx['outcome']='cancelled'
    expect('qualified_cancel_after_acceptance',core.transact(db,terminal,ctx)[0],'cancelled')
    expect('cancel_preserves_accepted_submission',core.row(db,'command_submission','submission_id','submission')['state'],'accepted')
    before=core.snapshot(db)
    try:core.transact(db,core.finish,ctx)
    except sqlite3.IntegrityError as error:expect('cancel_not_business_success',error.sqlite_errorname,'SQLITE_CONSTRAINT_TRIGGER')
    else:raise AssertionError('取消被当业务成功')
    expect('cancel_R5_rollback',core.snapshot(db)==before,True);db.close()
    db,ctx=fixture(6,origin='trigger')
    expect('normal_trigger_anchor',tuple(db.execute('SELECT origin_kind,start_id FROM execution_anchor').fetchone()),('trigger',None))
    expect('normal_trigger_origin_bound',db.execute('SELECT trigger_decision_ref_body FROM execution_anchor').fetchone()[0]==b'fixture-trigger-ref',True)
    expect('normal_trigger_step_complete',step(db)['outcome'],'succeeded')
    expect('normal_trigger_no_fake_recovery',db.execute('SELECT COUNT(*) FROM recovery_operation').fetchone()[0],0)
    db.close()
    for stage, action in enumerate((anchor, ready, submit, attempt, adjudicate, terminal)):
        db, ctx = fixture(stage); _, count = core.transact(db, action, ctx); db.close()
        for cut in [*range(1,count+1), 'before_commit']:
            db, ctx = fixture(stage); before = core.snapshot(db)
            try: core.transact(db, action, ctx, cut)
            except core.Injected: outcome='rolled_back'
            else: outcome='not_injected'
            expect(f'{action.__name__}_cut_{cut}', (outcome, core.snapshot(db)==before), ('rolled_back',True)); db.close()
    for stage, action in ((1,anchor),(2,ready),(3,submit),(5,adjudicate),(6,terminal)):
        db, ctx = fixture(stage); before=core.snapshot(db); ctx['now']=99999
        expect(f'{action.__name__}_repeat', core.transact(db,action,ctx)[0], 'existing')
        expect(f'{action.__name__}_repeat_unchanged', core.snapshot(db)==before, True); db.close()
    for name,stage,table in (('ready',1,'step_ready'),('submission',2,'command_submission'),('attempt',3,'submission_attempt'),('adjudication',4,'submission_adjudication'),('terminal',5,'step_terminal')):
        db,ctx=fixture(stage);source,_=fixture(stage+1);before=core.snapshot(db);db.execute('BEGIN IMMEDIATE')
        try:
            for t in ('transaction_record','event_outbox',table):
                prior=set(before[t])
                for r in source.execute(f'SELECT * FROM {t}'):
                    if tuple(r) not in prior:db.execute(f'INSERT INTO {t} VALUES({",".join("?" for _ in r)})',tuple(r))
            db.commit()
        except sqlite3.IntegrityError as error:actual=error.sqlite_errorname;db.rollback()
        else:actual='accepted'
        expect('orphan_'+name,actual,'SQLITE_CONSTRAINT_FOREIGNKEY')
        expect('orphan_'+name+'_rollback',core.snapshot(db)==before,True)
        source.close();db.close()
    for stage, action in ((0,anchor),(1,ready),(2,submit),(3,attempt)):
        for key, reason in (('authorized','forbidden'),('storage_healthy','protected'),('current_gates','protected'),('runtime_current','protected')):
            reject(action.__name__+'_'+key,stage,action,lambda d,c,k=key:c.update({k:False}),reason)
    reject('anchor_before_origin_commit',0,anchor,lambda d,c:c.update(origin_commit_observed=False),'origin_commit_unconfirmed')
    reject('ready_dependencies_unknown',1,ready,lambda d,c:c.update(dependencies_verified=False),'dependencies')
    reject('submission_identity_changed',3,submit,lambda d,c:c.update(request_digest='other'),'identity_conflict')
    for key in ('parameters_verified','budget_valid','window_valid'):
        reject('attempt_'+key,3,attempt,lambda d,c,k=key:c.update({k:False}),'write_gate')
    reject('attempt_changed_clock',3,attempt,lambda d,c:c.update(clock=b'new-domain'),'clock_domain')
    reject('attempt_after_pause',3,attempt,lambda d,c:d.execute("UPDATE run SET revision='4',lifecycle='paused',dispatch_eligible=0"),'execution_current')
    reject('attempt_new_latch',3,attempt,lambda d,c:d.execute("INSERT INTO pause_latch VALUES('late','run','takeover','3',X'00',NULL)"),'latch')
    reject('reply_untrusted',4,adjudicate,lambda d,c:c['response'].update(trusted=False),'response_binding')
    reject('reply_wrong_identity',4,adjudicate,lambda d,c:c['response']['identity'].update(principal_id='other'),'response_binding')
    reject('reply_wrong_receipt_scope',4,adjudicate,lambda d,c:c['response']['receipt_ref']['scope'].update(database_instance_id='other'),'receipt_scope')
    reject('reply_wrong_command_scope',4,adjudicate,lambda d,c:c['response']['command_ref']['scope'].update(authority_service_id='other'),'command_scope')
    reject('complete_without_evidence',5,terminal,lambda d,c:c.update(completion_verified=False),'completion_evidence')
    reject('cancel_request_not_terminal_evidence',5,terminal,lambda d,c:c.update(outcome='cancelled',terminal_evidence_verified=False),'terminal_evidence')
    reject('complete_wrong_command',5,terminal,lambda d,c:c.update(completion_command_ref={'other':'command'}),'completion_command')

    for result in ('not_found','timeout','temporary_rejection','rejected_final'):
        db,ctx=fixture(4); ctx['response']=response(ctx,result)
        if result=='rejected_final':ctx['response']['durable']=False
        expect('nonfinal_'+result,core.transact(db,adjudicate,ctx)[0],'query_only')
        before=core.snapshot(db)
        expect('no_resend_'+result,core.transact(db,attempt,ctx)[0],'query_only')
        expect('no_new_marker_'+result,core.snapshot(db)==before,True)
        expect('restart_'+result,db.execute('SELECT restart_action FROM submission_recovery').fetchone()[0],'query_original_identity_only')
        db.close()
    db,ctx=fixture(4);ctx['response']=response(ctx,'rejected_final')
    expect('durable_rejection',core.transact(db,adjudicate,ctx)[0],'rejected')
    expect('rejected_no_command',db.execute('SELECT command_ref_body FROM submission_adjudication').fetchone()[0],None)
    expect('rejected_no_resend',core.transact(db,attempt,ctx)[0],'query_only');db.close()
    db,ctx=fixture(4);ctx['outcome']='unknown'
    expect('unknown_step_terminal',core.transact(db,terminal,ctx)[0],'unknown')
    expect('late_accept_recorded',core.transact(db,adjudicate,ctx)[0],'accepted')
    expect('late_accept_does_not_reopen_step',(step(db)['state'],step(db)['outcome']),('indeterminate','unknown'))
    ctx['outcome']='succeeded'
    try:core.transact(db,terminal,ctx)
    except core.Rejected as error:expect('unknown_never_rewritten',str(error),'terminal_conflict')
    else:raise AssertionError('unknown被重写')
    db.close()
    db,ctx=fixture(4);before=core.snapshot(db)
    expect('crash_after_marker_before_call',core.transact(db,attempt,ctx)[0],'query_only')
    expect('crash_lookup_no_writes',core.snapshot(db)==before,True);db.close()

    for table, stage, statement in (
        ('anchor',1,"UPDATE execution_anchor SET tick_ns='2000'"),
        ('plan',0,"UPDATE execution_step_plan SET plan_digest='other'"),
        ('ready',2,"UPDATE step_ready SET tick_ns='2000'"),
        ('parameters',3,"UPDATE command_submission SET parameters_ref_body=X'00'"),
        ('identity',3,"UPDATE command_submission SET idempotency_key='new'"),
        ('attempt',4,"DELETE FROM submission_attempt"),
        ('marker_reset',4,"UPDATE command_submission SET state='planned',attempt_id=NULL"),
        ('adjudication',5,"UPDATE submission_adjudication SET receipt_body=X'00'"),
        ('terminal',6,"UPDATE step_terminal SET outcome='failed'"),
        ('step_reopen',6,"UPDATE step_state SET revision='9',state='ready',outcome='pending',terminal_id=NULL"),
        ('accepted_rewrite',5,"UPDATE command_submission SET state='indeterminate',adjudication_id=NULL"),
    ):sql_reject('immutable_'+table,stage,statement)
    sql_reject('marker_without_attempt',3,"UPDATE command_submission SET state='attempt_recorded',attempt_id='missing'",reason='SQLITE_CONSTRAINT_FOREIGNKEY')
    sql_reject('accepted_without_receipt',4,"UPDATE command_submission SET state='accepted'",reason='SQLITE_CONSTRAINT_CHECK')
    sql_reject('step_cannot_invent_acceptance',3,"UPDATE step_state SET state='accepted',revision='4'")
    sql_reject('attempted_is_not_accepted',4,"UPDATE step_state SET state='accepted',revision='4'")
    sql_reject('ready_without_record',0,"UPDATE step_state SET revision='2',state='ready',ready_id='missing'",reason='SQLITE_CONSTRAINT_FOREIGNKEY')
    sql_reject('step_terminal_without_record',2,"UPDATE step_state SET revision='3',state='indeterminate',outcome='unknown',terminal_id='missing'",reason='SQLITE_CONSTRAINT_FOREIGNKEY')
    for value in ('01','1\n','1\x00','100000000000000000000'):
        sql_reject('revision_lexeme_'+repr(value),0,"UPDATE step_state SET revision=?,state='cancelled',outcome='cancelled',terminal_id='missing'",(value,),reason='SQLITE_CONSTRAINT_CHECK')
    db,ctx=fixture(5);before=core.snapshot(db)
    try:core.transact(db,core.finish,ctx)
    except sqlite3.IntegrityError as error:expect('R5_ACK_is_not_completion',error.sqlite_errorname,'SQLITE_CONSTRAINT_TRIGGER')
    else:raise AssertionError('ACK被当完成')
    expect('R5_pending_rollback_all_tables',core.snapshot(db)==before,True);db.close()
    for kind in ('delay','retain_success','reconcile_commit'):
        db,ctx=fixture(2,kind=kind)
        try:core.transact(db,submit,ctx)
        except core.Rejected as error:expect(kind+'_no_submission',str(error),'not_action')
        else:raise AssertionError('非动作生成提交')
        db.close()
    try:fixture(0,mode='reconcile_commit')
    except sqlite3.IntegrityError as error:expect('reconcile_plan_rejects_action',error.sqlite_errorname,'SQLITE_CONSTRAINT_TRIGGER')
    else:raise AssertionError('核对计划包含新动作')
    db,ctx=fixture(2,kind='reconcile_commit',mode='reconcile_commit')
    expect('reconcile_step_evidence',core.transact(db,terminal,ctx)[0],'succeeded')
    expect('reconcile_R5',core.transact(db,core.finish,ctx)[0],'committed')
    expect('reconcile_zero_submissions',db.execute('SELECT COUNT(*) FROM command_submission').fetchone()[0],0);db.close()
    return results


def hashes(staged=False):
    out={}
    for p in INPUTS:
        rel=p.relative_to(ROOT).as_posix()
        data=subprocess.check_output(['git','show',':'+rel],cwd=ROOT) if staged else p.read_bytes()
        out[rel]=hashlib.sha256(data).hexdigest()
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');args=p.parse_args()
    if args.staged and not args.check_report:p.error('--staged仅用于--check-report')
    if args.check_report:
        raw=subprocess.check_output(['git','show',':'+REPORT.relative_to(ROOT).as_posix()],cwd=ROOT) if args.staged else REPORT.read_bytes()
        assert json.loads(raw)['artifact_sha256']==hashes(args.staged),'报告输入字节不匹配'
        print(json.dumps({'bindings':len(INPUTS),'matched':True}));return
    results=run_checks()
    data=dict(format='automation-dispatch-storage-reference/1',approved=False,checks_passed=len(results),all_passed=True,
        versions=dict(python=sys.version.split()[0],sqlite=sqlite3.sqlite_version),cases=results,artifact_sha256=hashes(),
        runtime_validation=dict(http=0,ipc=0,network_sends=0,production_writer=0,concurrency=0,disk_crash=0,devices=0))
    if args.report:REPORT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in data.items() if k not in ('cases','artifact_sha256')},ensure_ascii=False))


if __name__=='__main__':main()
