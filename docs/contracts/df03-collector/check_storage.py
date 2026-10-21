"""仅内存SQLite的时间写集检查；合成BODY不证明权威或真实加密。"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BODY = b'synthetic-body-not-a-cryptographic-proof'
TABLES = ['ts_scope', 'ts_binding', 'ts_poll', 'ts_commit', 'ts_capture', 'ts_blob',
          'ts_verification', 'ts_anchor', 'ts_state', 'ts_head', 'ts_invalidation',
          'ts_audit', 'ts_outbox', 'ts_seal']
INPUTS = [HERE / n for n in ('STORAGE.md', 'storage.sql', 'check_storage.py')]


def u(value):
    return f'{value:020d}'


def insert(table, *values):
    return f'INSERT INTO {table} VALUES ({",".join("?" for _ in values)})', values


def envelope(cid, kind):
    return [insert('ts_commit', cid, kind, BODY), insert('ts_audit', cid, BODY),
            insert('ts_outbox', cid, 'time_fence' if kind == 'invalidate' else 'notification', BODY)]


def bootstrap(revision=1, binding='b1'):
    cid = f'boot{revision}'
    steps = envelope(cid, 'bootstrap')
    steps += [insert('ts_state', u(revision), None if revision == 1 else u(revision-1), binding,
                     'collecting', None, cid, BODY)]
    steps += [insert('ts_head', 1, u(1))] if revision == 1 else [('UPDATE ts_head SET revision=?', (u(revision),))]
    return steps + [insert('ts_seal', cid, BODY)]


def publication(name='c1', revision=2, binding='b1', tick=10, kind='publish'):
    cid = 'commit.' + name
    steps = envelope(cid, kind)
    success = kind == 'publish'
    steps += [insert('ts_capture', name, 'p.' + name, binding, 'candidate' if success else 'failed',
                     'published' if success else ('rejected' if kind == 'reject' else 'failure_recorded'),
                     2 if success else 0, cid, BODY)]
    if success:
        steps += [insert('ts_blob', name, slot, 'synthetic-digest', 4, b'ciphertext-fixture', BODY)
                  for slot in ('request', 'response')]
        steps += [insert('ts_verification', name, binding, BODY),
                  insert('ts_anchor', 'a.' + name, name, binding, u(tick), BODY),
                  insert('ts_state', u(revision), u(revision-1), binding, 'qualified', 'a.' + name, cid, BODY),
                  ('UPDATE ts_head SET revision=?', (u(revision),))]
    return steps + [insert('ts_seal', cid, BODY)]


def invalidation(revision=3, old='b1', new='b2', generation=2):
    cid = f'invalidate{revision}'
    return [insert('ts_binding', new, 1, u(generation), BODY)] + envelope(cid, 'invalidate') + [
        insert('ts_invalidation', cid, old, new, cid, BODY, BODY),
        insert('ts_state', u(revision), u(revision-1), new, 'unavailable', None, cid, BODY),
        ('UPDATE ts_head SET revision=?', (u(revision),)), insert('ts_seal', cid, BODY)]


def transact(db, steps, cut=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        for i, (sql, values) in enumerate(steps):
            db.execute(sql, values)
            if cut == i:
                raise RuntimeError('synthetic_cut')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def fixture(publish=False):
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.executescript((HERE / 'storage.sql').read_text(encoding='utf-8'))
    db.execute('INSERT INTO ts_scope VALUES(1,?,?,?)',
               ('authority', 'database', 'reference-time-storage/0.1.0-draft.1'))
    db.execute(*insert('ts_binding', 'b1', 1, u(1), BODY))
    transact(db, bootstrap())
    for name in ('c1', 'c2', 'c3'):
        db.execute(*insert('ts_poll', 'p.' + name, 'b1', 'correlation.' + name, BODY))
    if publish:
        transact(db, publication())
    return db


def snapshot(db):
    return {table: sorted(db.execute('SELECT * FROM ' + table).fetchall(), key=repr) for table in TABLES}


def run():
    checks = []
    connections = []

    def fresh(publish=False):
        db = fixture(publish)
        connections.append(db)
        return db

    def check(name, actual, expected):
        if actual != expected:
            raise AssertionError(f'{name}: {actual!r} != {expected!r}')
        checks.append(dict(name=name, expected=expected, observed=actual))

    def denied(name, db, steps):
        before = snapshot(db)
        try:
            transact(db, steps)
        except sqlite3.IntegrityError:
            check(name, 'rejected', 'rejected')
        else:
            raise AssertionError(name + ': 未拒绝')
        check(name + '全部表回滚', snapshot(db) == before, True)

    try:
        db = fresh()
        check('十四表全集', sorted(r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")), sorted(TABLES))
        check('外键开启', db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        check('REPLACE删除触发开启', db.execute('PRAGMA recursive_triggers').fetchone()[0], 1)
        for kind in ('publish', 'reject', 'failure'):
            steps = publication(kind=kind)
            db = fresh()
            transact(db, steps)
            check(kind + '当前状态', db.execute('SELECT status FROM ts_current').fetchone()[0],
                  'qualified' if kind == 'publish' else 'collecting')
            check(kind + '外键完整', db.execute('PRAGMA foreign_key_check').fetchall(), [])
            for i in range(len(steps)):
                denied(kind + f'缺写{i}', fresh(), steps[:i] + steps[i+1:])
            for i in range(len(steps)):
                db = fresh()
                before = snapshot(db)
                try:
                    transact(db, steps, cut=i)
                except RuntimeError as error:
                    check(kind + f'故障{i}', str(error), 'synthetic_cut')
                else:
                    raise AssertionError('未命中故障切点')
                check(kind + f'故障{i}全部表回滚', snapshot(db) == before, True)
        steps = invalidation()
        for i in range(len(steps)):
            denied(f'失效缺写{i}', fresh(True), steps[:i] + steps[i+1:])
            db = fresh(True)
            before = snapshot(db)
            try:
                transact(db, steps, cut=i)
            except RuntimeError:
                pass
            else:
                raise AssertionError('未命中失效切点')
            check(f'失效故障{i}全部表回滚', snapshot(db) == before, True)
        db = fresh(True)
        transact(db, steps)
        check('发布后失效关闭', db.execute('SELECT status,anchor_id FROM ts_current').fetchall(), [('unavailable', None)])
        check('保护通知', db.execute("SELECT kind FROM ts_outbox WHERE commit_id='invalidate3'").fetchone()[0], 'time_fence')
        denied('失效后旧采样不得发布', db, publication('c2', revision=4, tick=20))
        denied('失效后旧Binding不得登记采样', db, [insert('ts_poll', 'new', 'b1', 'new.correlation', BODY)])
        denied('失效后不能用旧Binding启动', db, bootstrap(4, 'b1'))
        transact(db, bootstrap(4, 'b2'))
        check('新批准前提下重新collecting', db.execute('SELECT status,binding_id FROM ts_current').fetchall(), [('collecting','b2')])
        before = snapshot(db)
        receipt = db.execute("SELECT receipt_body FROM ts_commit WHERE id='commit.c1'").fetchone()
        check('提交后丢响应查原', receipt == (BODY,), True)
        check('查原不重开旧资格', snapshot(db) == before, True)
        db = fresh()
        transact(db, invalidation(2))
        denied('失效先于发布', db, publication(revision=3))
        for generation in (1, 3):
            denied('代次必须精确加一' + str(generation), fresh(True), invalidation(generation=generation))
        for tick in (9, 10):
            denied('旧样本不替换' + str(tick), fresh(True), publication('c2', revision=3, tick=tick))
        db = fresh(True)
        transact(db, publication('c2', revision=3, tick=11))
        check('较新样本发布', db.execute('SELECT anchor_id FROM ts_current').fetchone()[0], 'a.c2')
        denied('同poll第二裁决', db, [insert('ts_capture','other','p.c1','b1','failed','rejected',0,'another',BODY)])
        denied('后补blob被拒', db, [insert('ts_blob','c1','diagnostic','d',1,b'x',BODY)])
        denied('head倒退', db, [('UPDATE ts_head SET revision=?', (u(2),))])
        denied('状态跳代', fresh(), publication(revision=3))
        # 用合法其他Binding及回执结构不能绕过poll/Anchor的精确关联。
        db = fresh()
        db.execute(*insert('ts_binding','wrong',1,u(1),BODY))
        denied('合法但错误Binding', db, publication(binding='wrong'))
        for table in TABLES:
            db = fresh(True)
            if table == 'ts_invalidation':
                transact(db, invalidation())
            if table == 'ts_head':
                continue
            column = db.execute('PRAGMA table_info(' + table + ')').fetchone()[1]
            denied(table + '不可修改', db, [(f'UPDATE {table} SET {column}={column}', ())])
            denied(table + '不可删除', db, [(f'DELETE FROM {table}', ())])
        denied('不可删除head', fresh(True), [('DELETE FROM ts_head', ())])
        denied('REPLACE不能换原件', fresh(True), [('INSERT OR REPLACE INTO ts_blob VALUES(?,?,?,?,?,?)',
               ('c1','request','different',1,b'other',BODY))])
        check('合成密文合法不证明加密', fresh(True).execute('SELECT ciphertext FROM ts_blob LIMIT 1').fetchone()[0] == b'ciphertext-fixture', True)
        for kind in ('reject', 'failure'):
            db = fresh(True)
            transact(db, publication('c2', kind=kind))
            check('普通' + kind + '不清当前锚点', db.execute('SELECT anchor_id FROM ts_current').fetchone()[0], 'a.c1')
        bad = publication()
        sql, values = bad[5]
        altered = list(values)
        altered[1] = 'diagnostic'
        bad[5] = sql, tuple(altered)
        denied('数量相同不能替代response槽位', fresh(), bad)
        bad = publication()
        sql, values = bad[2]
        bad[2] = sql, (values[0], 'time_fence', values[2])
        denied('发布不得伪装TIME失效通知', fresh(), bad)
        # 高位算术只是SQL表达式探针，不冒充完整高位数据库状态。
        db = fresh()
        expression = "SELECT printf('%010d%010d',CAST(substr(?,1,10) AS INTEGER)+(CAST(substr(?,11,10) AS INTEGER)=9999999999),(CAST(substr(?,11,10) AS INTEGER)+1)%10000000000)"
        for original, expected in [('00000000009999999999','00000000010000000000'),
                                   ('9223372036854775807','09223372036854775808'),
                                   ('99999999999999999998','99999999999999999999')]:
            source = original.zfill(20)
            check('U20后继表达式' + source, db.execute(expression,(source,source,source)).fetchone()[0], expected)
        return dict(approved=False, all_passed=True, check_count=len(checks), checks=checks,
                    sqlite_version=sqlite3.sqlite_version, table_count=14,
                    runtime_validation=dict(disk_crash=0, concurrency=0, cryptography=0, ntp=0, device=0),
                    artifact_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
    finally:
        for db in connections:
            db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    path = HERE / 'storage-report.json'
    if args.check_report:
        rel = path.relative_to(ROOT).as_posix()
        raw = subprocess.check_output(['git','show',':'+rel],cwd=ROOT) if args.staged else path.read_bytes()
        report = json.loads(raw)
        assert set(report['artifact_sha256']) == {p.relative_to(ROOT).as_posix() for p in INPUTS}
        for rel, expected in report['artifact_sha256'].items():
            raw = subprocess.check_output(['git','show',':'+rel],cwd=ROOT) if args.staged else (ROOT/rel).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == expected, rel
        print('3项输入字节绑定通过；未重跑检查')
        return
    if args.staged:
        parser.error('--staged仅与--check-report组合')
    report = run()
    if args.report:
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:report[k] for k in ('all_passed','check_count','table_count','sqlite_version','runtime_validation')},ensure_ascii=False))


if __name__ == '__main__':
    main()
