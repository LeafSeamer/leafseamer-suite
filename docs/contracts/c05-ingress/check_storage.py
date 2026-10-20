"""只在固定内存库核验摄取写集。BODY为合成占位，不执行产品writer。"""
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
SQL = [HERE.parent/'c04-storage/recovery.sql', HERE.parent/'c04-storage/dispatch.sql', HERE/'ingress.sql']


def database(results=()):
    db = sqlite3.connect(':memory:', isolation_level=None)
    for path in SQL:
        db.executescript(path.read_text('utf-8'))
    db.execute("INSERT INTO storage_scope VALUES(1,'seamer','db','automation-storage/0.1.0-draft.2')")
    db.execute("INSERT INTO ingress_storage_profile VALUES(1,'ingress-storage/0.1.0-draft.1')")
    db.execute("INSERT INTO ingest_epoch VALUES('epoch','open','0')")
    db.execute("INSERT INTO ingress_source VALUES('source',?,'0','0','0','synchronized')", (b'synthetic-source',))
    db.execute("INSERT INTO ingress_registry VALUES('source','1')")
    for n, result in enumerate(results):
        rid, definition = f'r{n}', f'd{n}'
        db.execute("INSERT INTO published_version VALUES(?,'1',1,'artifact',?)", (definition, b'synthetic-artifact'))
        # busy只是被测决定类别；没有伪造已存在execution，不能算busy门控的运行证据。
        db.execute("INSERT INTO run VALUES(?,?,'1','1','1','armed',1,NULL,NULL,NULL)", (rid, definition))
        db.execute("INSERT INTO activation_slot VALUES(?,'1',?,'1')", (definition, rid))
        db.execute("INSERT INTO ingress_listener VALUES('source',?,'artifact',?)", (rid, b'synthetic-binding'))
        db.execute("INSERT INTO run_ingest_progress VALUES(?,'0','epoch','0',?,NULL)", (rid, b'synthetic-baseline'))
    return db


def snapshot(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {t: sorted(db.execute('SELECT * FROM "'+t+'"'), key=repr) for t in tables}


class Injected(Exception):
    pass


class Transaction:
    def __init__(self, db, cut=None):
        self.db, self.cut, self.count = db, cut, 0

    def execute(self, sql, args=()):
        self.db.execute(sql, args)
        self.count += 1
        if self.count == self.cut:
            raise Injected(self.count)


def inbox(db, observed=False):
    db.execute("INSERT INTO ingress_inbox VALUES('inbox','source','event','1','origin',?,?,?,NULL)",
               (b'synthetic-content', b'synthetic-first-observation', int(observed)))


def write_batch(db, results=(), *, cut=None, pending=False, observed=False, omit=None):
    """确定性参考写集；只有本函数允许的合成输入，故意不承担来源鉴权或AST求值。"""
    tx = Transaction(db, cut)
    db.execute('BEGIN IMMEDIATE')
    try:
        if not pending:
            tx.execute("INSERT INTO ingress_inbox VALUES('inbox','source','event','1','origin',?,?,?,NULL)",
                       (b'synthetic-content', b'synthetic-first-observation', int(observed)))
        tx.execute("""INSERT INTO ingress_commit
            (commit_id,inbox_id,epoch,receive_sequence,registry_revision,source_revision_before,source_revision_after,
             expected_targets,decision_set_digest,body,notification_id,sealed)
            VALUES('commit','inbox','epoch','1','1','0','1',?,'set',?,'notification',0)""",
                   (len(results), b'synthetic-commit'))
        for n, result in enumerate(results):
            rid, did, sid, eid = f'r{n}', f'decision{n}', f'snapshot{n}', f'execution{n}'
            accepted = result == 'accepted'
            has_snapshot = result in ('accepted', 'no_match', 'evaluation_unknown', 'ambiguous')
            changed = accepted or result in ('protected', 'evaluation_unknown', 'ambiguous')
            tx.execute("INSERT INTO ingress_target VALUES('commit',?,'artifact',?,?)", (rid, b'synthetic-binding', did))
            if has_snapshot:
                tx.execute("INSERT INTO ingress_snapshot VALUES(?,'commit',?,'snapshot',?)", (sid, rid, b'synthetic-snapshot'))
            tx.execute("""INSERT INTO ingress_decision VALUES(?,'commit',?,'inbox',?,?,?,'decision',?,'1',?,'0','1')""",
                       (did, rid, result, sid if has_snapshot else None, eid if accepted else None,
                        b'synthetic-decision', '2' if changed else '1'))
            if accepted:
                tx.execute("INSERT INTO ingress_execution VALUES(?,?,?)", (eid, rid, did))
                tx.execute("""INSERT INTO execution VALUES(?,?,NULL,'trigger',?,'1','binding','plan',?,
                           'rule',NULL,NULL,NULL,'prepared',NULL,NULL)""", (eid, rid, did.encode(), b'synthetic-binding'))
                tx.execute("INSERT INTO transaction_record VALUES(?,?,'PLAN',?,?,?)",
                           ('plan-tx'+rid, rid, eid, b'synthetic-audit', 'plan-event'+rid))
                tx.execute("INSERT INTO event_outbox VALUES(?,?,'payload',?)",
                           ('plan-event'+rid, 'plan-tx'+rid, b'synthetic-notification'))
                tx.execute("INSERT INTO execution_plan_set VALUES(?,?,1,'plan',?,0,?,'PLAN')",
                           (eid, rid, b'synthetic-plan', 'plan-tx'+rid))
                tx.execute("INSERT INTO execution_step_plan VALUES(?,'step','action',0,1,'step-plan',?)",
                           (eid, b'synthetic-step'))
                tx.execute("INSERT INTO step_state(execution_id,step_id,revision,state,outcome) VALUES(?,'step','0','waiting','pending')", (eid,))
                tx.execute("UPDATE execution_plan_set SET sealed=1 WHERE execution_id=?", (eid,))
                tx.execute("UPDATE execution SET state='running' WHERE execution_id=?", (eid,))
                tx.execute("UPDATE run SET revision='2',lifecycle='running',active_execution_id=? WHERE run_id=?", (eid, rid))
            elif changed:
                tx.execute("UPDATE run SET revision='2',lifecycle='paused',dispatch_eligible=0 WHERE run_id=?", (rid,))
            if omit != 'progress':
                tx.execute("UPDATE run_ingest_progress SET revision='1',last_sequence='1',last_commit_id='commit' WHERE run_id=?", (rid,))
            if omit != 'audit':
                tx.execute("INSERT INTO ingress_run_audit VALUES('commit',?,'INGRESS_RUN',?,?)", (rid, b'synthetic-audit', b'synthetic-event'))
        tx.execute("UPDATE ingress_source SET revision='1',contiguous_sequence='1' WHERE source_id='source'")
        tx.execute("UPDATE ingest_epoch SET last_sequence='1' WHERE epoch='epoch'")
        tx.execute("UPDATE ingress_inbox SET commit_id='commit' WHERE inbox_id='inbox'")
        if omit != 'notification':
            tx.execute("INSERT INTO ingress_notification VALUES('notification','commit',?)", (b'synthetic-notification',))
        if omit != 'charge':
            tx.execute("INSERT INTO ingress_charge VALUES('commit',?,?)", (b'simulation-profile', b'synthetic-charge'))
        if omit != 'seal':
            tx.execute("UPDATE ingress_commit SET sealed=1 WHERE commit_id='commit'")
        # COMMIT之前的切点也包含在最后一条UPDATE后的主动异常中。
        db.execute('COMMIT')
        return tx.count
    except Exception:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def run():
    records = []
    def expect(name, ok):
        assert ok, name
        records.append(dict(id=name, passed=True))

    def rejected(name, db, action):
        before = snapshot(db)
        db.execute('BEGIN IMMEDIATE')
        error = None
        try:
            action()
            db.execute('COMMIT')
        except sqlite3.IntegrityError as e:
            error = e.sqlite_errorname
        finally:
            if db.in_transaction:
                db.execute('ROLLBACK')
        expect(name, error is not None and before == snapshot(db))

    for results in [(), ('accepted','suppressed_busy','no_match'), ('accepted','accepted'),
                    ('evaluation_unknown','ambiguous','protected'), ('suppressed_inactive','suppressed_obsolete')]:
        db = database(results)
        count = write_batch(db, results)
        expect('SQL-positive-'+str(results), db.execute('SELECT count(*) FROM ingress_decision').fetchone()[0] == len(results)
               and db.execute('SELECT count(*) FROM execution').fetchone()[0] == results.count('accepted')
               and not db.execute('PRAGMA foreign_key_check').fetchall())
        expect('SQL-no-anchor-before-separate-transaction-'+str(results),
               db.execute('SELECT count(*) FROM execution_anchor').fetchone()[0] == 0)
        if results in ((), ('accepted','accepted')):
            for cut in range(1, count+1):
                trial = database(results); before = snapshot(trial)
                try:
                    write_batch(trial, results, cut=cut)
                    raise AssertionError('缺少注入异常')
                except Injected:
                    expect(f'SQL-rollback-{len(results)}-{cut}', snapshot(trial) == before)
                finally:
                    trial.close()
        db.close()

    for omission in ('seal','notification','charge','audit','progress'):
        db = database(('accepted',)); before = snapshot(db)
        try:
            write_batch(db, ('accepted',), omit=omission)
            raise AssertionError(omission)
        except sqlite3.IntegrityError:
            expect('SQL-missing-'+omission, snapshot(db) == before)
        db.close()

    db = database(('no_match',)); inbox(db)
    first = db.execute('SELECT first_observation_body FROM ingress_inbox').fetchone()
    write_batch(db, ('no_match',), pending=True)
    expect('SQL-pending-first-observation', db.execute('SELECT first_observation_body FROM ingress_inbox').fetchone() == first)
    before = snapshot(db)
    for _ in range(2):
        row = db.execute("SELECT commit_id FROM ingress_inbox WHERE source_id='source' AND event_id='event' AND origin_digest='origin'").fetchone()
        expect('SQL-lookup-'+str(_), row == ('commit',) and snapshot(db) == before)
    # 提交之后的注册不能追补原决定；查询原批次的成员仍固定。
    db.execute("INSERT INTO published_version VALUES('late','1',1,'artifact',x'01')")
    db.execute("INSERT INTO run VALUES('late','late','1','1','1','armed',1,NULL,NULL,NULL)")
    db.execute("INSERT INTO ingress_listener VALUES('source','late','artifact',x'01')")
    expect('SQL-late-listener-does-not-rewrite-original',
           db.execute("SELECT run_id FROM ingress_target WHERE commit_id='commit'").fetchall()==[('r0',)])
    for table, update in [
        ('ingress_commit',"sealed=0"), ('ingress_target',"artifact_digest='changed'"),
        ('ingress_snapshot',"body=x'01'"), ('ingress_decision',"result='protected'"),
        ('ingress_notification',"payload_body=x'01'"), ('ingress_run_audit',"audit_body=x'01'"),
        ('ingress_charge',"charge_body=x'01'"), ('ingress_inbox',"first_observation_body=x'01'")]:
        rejected('SQL-immutable-'+table, db, lambda t=table,u=update: db.execute(f'UPDATE {t} SET {u}'))
        rejected('SQL-retain-'+table, db, lambda t=table: db.execute(f'DELETE FROM {t}'))
    for bad in ('01','-1','1\n','1\x00','100000000000000000000'):
        rejected('SQL-U20-'+repr(bad), db, lambda b=bad: db.execute('UPDATE ingest_epoch SET last_sequence=?',(b,)))
    rejected('SQL-second-open-epoch', db, lambda: db.execute("INSERT INTO ingest_epoch VALUES('new','open','0')"))
    rejected('SQL-cross-epoch-progress', db, lambda: db.execute("UPDATE run_ingest_progress SET revision='2',epoch='missing',last_sequence='0'"))
    rejected('SQL-identity-content-overwrite', db, lambda: db.execute("UPDATE ingress_inbox SET origin_digest='changed'"))
    rejected('SQL-source-sequence-reuse', db, lambda: db.execute(
        "INSERT INTO ingress_inbox VALUES('other','source','other-event','1','other',x'01',x'01',0,NULL)"))
    db.close()

    # 普通受理完成后，旧执行层仍能另开事务保存原decision引用的锚。
    db=database(('accepted',));write_batch(db,('accepted',))
    db.execute('BEGIN IMMEDIATE')
    db.execute("INSERT INTO transaction_record VALUES('anchor_tx','r0','ANCHOR','anchor',x'01','anchor_event')")
    db.execute("INSERT INTO event_outbox VALUES('anchor_event','anchor_tx','digest',x'01')")
    db.execute("""INSERT INTO execution_anchor VALUES('anchor','execution0','r0','trigger',NULL,?,
                  x'01','9007199254740993','digest',x'01','anchor_tx','ANCHOR')""",(b'decision0',))
    db.execute('COMMIT')
    expect('SQL-separate-anchor-transaction',not db.execute('PRAGMA foreign_key_check').fetchall())
    db.close()

    db=database(('accepted',)); inbox(db, observed=True); before=snapshot(db)
    try:
        write_batch(db, ('accepted',), pending=True)
        raise AssertionError('observed-only')
    except sqlite3.IntegrityError:
        expect('SQL-observed-only-no-execution', snapshot(db)==before)
    rejected('SQL-observed-only-no-upgrade', db, lambda: db.execute('UPDATE ingress_inbox SET observed_only=0'))
    db.close()

    # 相同数量但不同权威绑定不能封存；变更发生在同一writer里，非真实线程竞争。
    db=database(('no_match',))
    db.execute("UPDATE ingress_listener SET binding_body=x'01'")
    before=snapshot(db)
    try:
        write_batch(db, ('no_match',))
        raise AssertionError('matched-set')
    except sqlite3.IntegrityError:
        expect('SQL-same-count-wrong-binding', snapshot(db)==before)
    db.close()
    return records


if __name__=='__main__':
    print('内存SQL检查通过:',len(run()))
