"""固定内存SQL设计实验；主动故障注入不等于进程/磁盘耐久验证。"""
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent


def connect():
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.executescript((HERE/'storage-probes.sql').read_text('utf-8'))
    assert db.execute('PRAGMA foreign_keys').fetchone() == (1,)
    for s in ('s1', 's2'):
        db.execute('INSERT INTO panel_session VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (s, 'controller', 'db1', 'issuer', 'epoch', 'auth', s, '1', 'active', 1, 1, 200, 100, 'activation1'))
    add_request(db, 'r1', 's1', 'request1')
    db.execute("INSERT INTO confirmation VALUES('p1','r1','s1','offered',90,NULL)")
    return db


def add_request(db, pk, session, request_id, activation='activation1', digest='a'*64, authority='controller'):
    db.execute('INSERT INTO panel_request VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (pk, session, authority, 'db1', 'issuer', 'epoch', 'auth', session, '1', request_id,
                digest, activation, 'pending_confirmation', None))


def confirm(db, now=10, fault=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute("SELECT c.state,s.state,s.lease_tick,s.hard_tick,c.deadline_tick,r.state "
                         "FROM confirmation c JOIN panel_session s USING(session_key) "
                         "JOIN panel_request r USING(request_pk) WHERE c.preview_id='p1'").fetchone()
        if row[0] == 'consumed':
            db.execute('COMMIT')
            return 'already_accepted'
        if row[0] != 'offered' or row[1] != 'active' or row[5] != 'pending_confirmation':
            db.execute('ROLLBACK')
            return 'rejected'
        if now >= min(row[2], row[3], row[4]):
            db.execute("UPDATE confirmation SET state='expired' WHERE preview_id='p1'")
            db.execute("UPDATE panel_request SET state='rejected' WHERE request_pk='r1'")
            db.execute('COMMIT')
            return 'expired'
        db.execute("INSERT INTO admission VALUES('a1','r1','s1')")
        if fault == 'after_admission':
            raise RuntimeError('injected')
        assert db.execute("UPDATE panel_request SET state='accepted',accepted_result_ref='a1' "
                          "WHERE request_pk='r1' AND state='pending_confirmation'").rowcount == 1
        assert db.execute("UPDATE confirmation SET state='consumed',accepted_result_ref='a1' "
                          "WHERE preview_id='p1' AND state='offered'").rowcount == 1
        db.execute("INSERT INTO audit VALUES('a1','accepted','r1')")
        db.execute("INSERT INTO outbox VALUES('a1','accepted','request')")
        if fault == 'before_commit':
            raise RuntimeError('injected')
        db.execute('COMMIT')
        return 'response_lost' if fault == 'after_commit' else 'accepted'
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def cancel(db):
    db.execute('BEGIN IMMEDIATE')
    state = db.execute("SELECT state FROM confirmation WHERE preview_id='p1'").fetchone()[0]
    if state == 'offered':
        db.execute("UPDATE confirmation SET state='cancelled' WHERE preview_id='p1'")
        db.execute("UPDATE panel_request SET state='cancelled' WHERE request_pk='r1'")
        db.execute("INSERT INTO audit VALUES('cancel','cancelled','r1')")
    db.execute('COMMIT')
    return 'cancelled' if state in ('offered', 'cancelled') else 'conflict'


def close(db, fail=False):
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute("UPDATE panel_session SET state='closing',revision=revision+1 WHERE session_key='s1'")
        db.execute("UPDATE confirmation SET state='revoked' WHERE session_key='s1' AND state='offered'")
        db.execute("UPDATE panel_request SET state='rejected' WHERE session_key='s1' AND state='pending_confirmation'")
        db.execute("INSERT INTO close_operation VALUES('close1','s1',?)", ('b'*64,))
        # 两个目标由人工夹具提供；不声称完成权威目标发现。
        db.executemany("INSERT INTO close_target VALUES('close1',?,'pending')", [('local',), ('remote',)])
        db.execute("INSERT INTO audit VALUES('close1','closed','s1')")
        db.execute("INSERT INTO outbox VALUES('close1','s1','close')")
        if fail:
            raise RuntimeError('injected')
        db.execute('COMMIT')
        return 'propagating'
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def renew(db, op='renew1', digest='c'*64):
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT content_digest FROM lifecycle_operation WHERE host_operation_id=?', (op,)).fetchone()
        if row:
            db.execute('COMMIT')
            return 'replayed' if row[0] == digest else 'conflict'
        assert db.execute("UPDATE panel_session SET lease_tick=150,lease_revision=lease_revision+1 "
                          "WHERE session_key='s1' AND state='active' AND lease_revision=1").rowcount == 1
        db.execute('INSERT INTO lifecycle_operation VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   ('controller','db1','issuer','epoch','auth','gui1',op,'renew',digest,'s1',2))
        db.execute('COMMIT')
        return 'renewed'
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def snapshot(db):
    request, result = db.execute("SELECT state,accepted_result_ref FROM panel_request WHERE request_pk='r1'").fetchone()
    preview, deadline = db.execute("SELECT state,deadline_tick FROM confirmation WHERE preview_id='p1'").fetchone()
    session, lease, revision = db.execute("SELECT state,lease_tick,lease_revision FROM panel_session WHERE session_key='s1'").fetchone()
    return dict(request=request, result=result, preview=preview, deadline=deadline, session=session, lease=lease,
                lease_revision=revision, admissions=db.execute('SELECT count(*) FROM admission').fetchone()[0],
                targets=db.execute('SELECT count(*) FROM close_target').fetchone()[0],
                audit=db.execute('SELECT count(*) FROM audit').fetchone()[0],
                outbox=db.execute('SELECT count(*) FROM outbox').fetchone()[0])


def step(db, name):
    if name == 'confirm': return confirm(db)
    if name == 'confirm_deadline': return confirm(db, 90)
    if name == 'cancel': return cancel(db)
    if name == 'close': return close(db)
    if name == 'close_fail': return close(db, True)
    if name == 'renew': return renew(db)
    if name == 'renew_conflict': return renew(db, digest='d'*64)
    if name.startswith('fault_'): return confirm(db, fault=name[6:])
    if name == 'query': return db.execute("SELECT state FROM panel_request WHERE request_pk='r1'").fetchone()[0]
    if name == 'duplicate_identity':
        add_request(db, 'r2', 's1', 'request1', activation='activation2'); return 'inserted'
    if name == 'other_session_same_id':
        add_request(db, 'r2', 's2', 'request1'); return 'inserted'
    if name == 'cross_authority':
        add_request(db, 'r2', 's1', 'request2', authority='seamer'); return 'inserted'
    if name == 'cross_preview':
        add_request(db, 'r2', 's1', 'request2')
        db.execute("INSERT INTO confirmation VALUES('p2','r2','s2','offered',90,NULL)"); return 'inserted'
    if name == 'second_preview':
        db.execute("INSERT INTO confirmation VALUES('p2','r1','s1','offered',90,NULL)"); return 'inserted'
    if name == 'mutate_intent':
        db.execute("UPDATE panel_request SET intent_digest=? WHERE request_pk='r1'", ('f'*64,)); return 'updated'
    if name == 'revive':
        db.execute("UPDATE confirmation SET state='offered',accepted_result_ref=NULL WHERE preview_id='p1'"); return 'updated'
    if name == 'delete_session':
        db.execute("DELETE FROM panel_session WHERE session_key='s1'"); return 'deleted'
    if name in ('orphan_accept', 'orphan_consume'):
        db.execute('BEGIN IMMEDIATE')
        try:
            if name == 'orphan_accept':
                db.execute("UPDATE panel_request SET state='accepted',accepted_result_ref='missing' WHERE request_pk='r1'")
            else:
                db.execute("UPDATE confirmation SET state='consumed',accepted_result_ref='missing' WHERE preview_id='p1'")
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK'); raise
        return 'committed'
    raise ValueError(name)


def run(cases):
    results = []
    for case in cases:
        db = connect()
        actual = []
        try:
            for name in case['steps']:
                try:
                    actual.append(step(db, name))
                except sqlite3.IntegrityError as exc:
                    actual.append(exc.sqlite_errorname)
                except RuntimeError as exc:
                    if str(exc) != 'injected': raise
                    actual.append('rolled_back')
            state = snapshot(db)
            assert actual == case['expected'], (case['id'], actual, case['expected'])
            for key, value in case['final'].items():
                assert state[key] == value, (case['id'], key, state[key], value)
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            results.append({'id': case['id'], 'passed': True, 'outcomes': actual, 'snapshot': state})
        finally:
            db.close()
    return results
