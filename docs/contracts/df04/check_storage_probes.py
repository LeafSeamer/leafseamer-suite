"""仅在内存运行DF04局部SQL约束；不接收数据库路径，不验收生产存储。"""
import hashlib
import json
from pathlib import Path
import platform
import sqlite3

ROOT = Path(__file__).resolve().parent
DDL = ROOT / 'storage-probes.sql'
checks = []


def fresh():
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.executescript(DDL.read_text(encoding='utf-8'))
    assert db.execute('PRAGMA foreign_keys').fetchone() == (1,)
    return db


def record(name, function):
    db = fresh()
    try:
        function(db)
        checks.append({'id': name, 'passed': True})
    finally:
        db.close()


def reject(db, sql, args, code):
    try:
        db.execute(sql, args)
    except sqlite3.IntegrityError as exc:
        assert exc.sqlite_errorcode == code, (exc.sqlite_errorcode, code)
    else:
        raise AssertionError('应拒绝但被接受')


def seed(db):
    db.execute("INSERT INTO probe_command VALUES ('c1','dispatching','pending','held',NULL,NULL)")
    db.execute("INSERT INTO probe_command VALUES ('c2','dispatching','pending','held',NULL,NULL)")
    db.execute("INSERT INTO probe_attempt VALUES ('a1','c1',1)")
    db.execute("INSERT INTO probe_attempt VALUES ('a2','c2',1)")


def integers(db):
    for n in ['99999999999999999999', '10', '9', '0', '9223372036854775808']:
        db.execute('INSERT INTO probe_revision VALUES (?)', (n,))
    rows = db.execute('SELECT value FROM probe_revision ORDER BY length(value),value COLLATE BINARY').fetchall()
    assert rows == [('0',), ('9',), ('10',), ('9223372036854775808',), ('99999999999999999999',)]
    assert db.execute('SELECT DISTINCT typeof(value) FROM probe_revision').fetchall() == [('text',)]


record('SP01_exact_decimal_order', integers)
for index, value in enumerate(['', '00', '01', '1\n', '1\x00x', '+1', '-0', '1e2', '100000000000000000000', '１']):
    record(f'SP02_{index+1:02d}_invalid_decimal', lambda db, v=value:
           reject(db, 'INSERT INTO probe_revision VALUES (?)', (v,), sqlite3.SQLITE_CONSTRAINT_CHECK))
record('SP03_not_null', lambda db: reject(db, 'INSERT INTO probe_revision VALUES (?)', (None,), sqlite3.SQLITE_CONSTRAINT_NOTNULL))


def coercion(db):
    db.execute('INSERT INTO probe_revision VALUES (?)', (9,))
    assert db.execute('SELECT value,typeof(value) FROM probe_revision').fetchone() == ('9', 'text')


record('SP04_strict_coercion_is_not_wire_validation', coercion)


def wrong_owner(db):
    seed(db)
    reject(db, 'INSERT INTO probe_intent VALUES (?,?,?,?)', ('i1', 'a1', 'c2', 'p1'), sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)


record('SP05_composite_owner_fk', wrong_owner)


def duplicate_permit(db):
    seed(db)
    db.execute("INSERT INTO probe_intent VALUES ('i1','a1','c1','p1')")
    reject(db, 'INSERT INTO probe_intent VALUES (?,?,?,?)', ('i2', 'a2', 'c2', 'p1'), sqlite3.SQLITE_CONSTRAINT_UNIQUE)


record('SP06_unique_permit', duplicate_permit)


def holds(db):
    seed(db)
    db.execute("INSERT INTO probe_hold VALUES ('h1','c1','d1','unresolved')")
    reject(db, 'INSERT INTO probe_hold VALUES (?,?,?,?)', ('h2', 'c2', 'd1', 'held'), sqlite3.SQLITE_CONSTRAINT_UNIQUE)
    db.execute("UPDATE probe_hold SET state='released' WHERE hold_id='h1'")
    db.execute("INSERT INTO probe_hold VALUES ('h2','c2','d1','held')")
    assert db.execute('SELECT count(*) FROM probe_hold').fetchone() == (2,)


record('SP07_partial_unique_hold_with_history', holds)


def terminal(db):
    db.execute("INSERT INTO probe_command VALUES ('u','finished','unknown','unresolved',NULL,NULL)")
    reject(db, "UPDATE probe_command SET outcome='succeeded' WHERE command_id='u'", (), sqlite3.SQLITE_CONSTRAINT_TRIGGER)
    reject(db, "UPDATE probe_command SET resource_status='clear' WHERE command_id='u'", (), sqlite3.SQLITE_CONSTRAINT_CHECK)
    db.execute("UPDATE probe_command SET resource_status='clear',release_ref='e1',resolution_ref='r1' WHERE command_id='u'")
    assert db.execute("SELECT outcome,resource_status FROM probe_command WHERE command_id='u'").fetchone() == ('unknown', 'clear')


record('SP08_terminal_immutable_release_separate', terminal)


def coverage(db):
    seed(db)
    db.execute("INSERT INTO probe_intent VALUES ('i1','a1','c1','p1')")
    db.execute("INSERT INTO probe_barrier_member VALUES ('b1','p1')")
    reject(db, 'INSERT INTO probe_coverage VALUES (?,?,?)', ('b2', 'p1', 'not_sent'), sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
    # FK允许缺覆盖，因此必须额外执行集合完整性判定。
    missing = "SELECT permit_id FROM probe_barrier_member WHERE barrier_id='b1' EXCEPT SELECT permit_id FROM probe_coverage WHERE barrier_id='b1'"
    assert db.execute(missing).fetchall() == [('p1',)]
    db.execute("INSERT INTO probe_coverage VALUES ('b1','p1','unknown')")
    assert db.execute(missing).fetchall() == []


record('SP09_coverage_fk_does_not_prove_completeness', coverage)


def recovery(db):
    db.execute("INSERT INTO probe_preview VALUES ('v1',0)")
    db.execute("INSERT INTO probe_preview VALUES ('v2',0)")
    db.execute("INSERT INTO probe_recovery VALUES ('o1','v1','run1',1)")
    reject(db, 'INSERT INTO probe_recovery VALUES (?,?,?,?)', ('o2', 'v1', 'run2', 1), sqlite3.SQLITE_CONSTRAINT_UNIQUE)
    reject(db, 'INSERT INTO probe_recovery VALUES (?,?,?,?)', ('o3', 'v2', 'run1', 1), sqlite3.SQLITE_CONSTRAINT_UNIQUE)


record('SP10_single_preview_and_active_run', recovery)


def rollback(db):
    db.execute("INSERT INTO probe_preview VALUES ('v1',0)")
    db.execute('BEGIN IMMEDIATE')
    assert db.execute("UPDATE probe_preview SET consumed=1 WHERE preview_id='v1' AND consumed=0").rowcount == 1
    db.execute("INSERT INTO probe_recovery VALUES ('o1','v1','run1',1)")
    reject(db, 'INSERT INTO probe_recovery VALUES (?,?,?,?)', ('o2', 'v1', 'run1', 1), sqlite3.SQLITE_CONSTRAINT_UNIQUE)
    assert db.in_transaction  # 语句失败不代表全部事务已回滚。
    db.execute('ROLLBACK')
    assert db.execute("SELECT consumed FROM probe_preview WHERE preview_id='v1'").fetchone() == (0,)
    assert db.execute('SELECT count(*) FROM probe_recovery').fetchone() == (0,)


record('SP11_explicit_whole_transaction_rollback', rollback)


def returning(db):
    db.execute('BEGIN IMMEDIATE')
    assert db.execute("INSERT INTO probe_preview VALUES ('v1',0) RETURNING preview_id").fetchone() == ('v1',)
    db.execute('ROLLBACK')
    assert db.execute('SELECT count(*) FROM probe_preview').fetchone() == (0,)


record('SP12_returning_is_not_commit', returning)


def event_sequence(db):
    db.execute("INSERT INTO probe_revision VALUES ('1')")
    db.execute("INSERT INTO probe_outbox VALUES ('e1','s','epoch1','1')")
    reject(db, 'INSERT INTO probe_outbox VALUES (?,?,?,?)', ('e2', 's', 'epoch1', '1'), sqlite3.SQLITE_CONSTRAINT_UNIQUE)
    db.execute("INSERT INTO probe_outbox VALUES ('e2','s','epoch2','1')")


record('SP13_stream_epoch_sequence', event_sequence)
report = {
    'purpose': 'DF04局部SQL约束参考，非生产存储验收',
    'python_version': platform.python_version(),
    'sqlite_version': sqlite3.sqlite_version,
    'database': ':memory:',
    'product_engine_qualified': False,
    'check_count': len(checks),
    'checks': checks,
    'all_passed': True,
    'runtime_validation': {'wal': 0, 'concurrency': 0, 'power_loss': 0, 'backup_restore': 0, 'devices': 0},
    'limitations': ['只覆盖局部结构，不是完整生产DDL', '未执行SDK输入或驱动绑定器', '释放证据来源未在探针实现', '参考SQLite未满足产品WAL修复门槛'],
    'input_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [DDL, Path(__file__)]},
}
(ROOT / 'reference-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'all_passed': True, 'check_count': len(checks), 'sqlite_version': sqlite3.sqlite_version, 'product_engine_qualified': False}))
