"""局部离线SQL探针；不接受数据库路径，不连接服务或设备。"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import rfc8785

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPORT = HERE / 'reference-report.json'
INPUTS = [HERE / p for p in ('README.md', 'storage-probes.sql', 'check_storage.py')] + [
    HERE.parent / 'c09-panel-service/HTTP_STORAGE.md',
    HERE.parent / 'c09-panel-ipc/IPC_GUARD.md',
    HERE.parent / 'c09-panel/CHANNEL_V02.md']


def digest(value):
    return 'sha256:' + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def fixture():
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.executescript((HERE / 'storage-probes.sql').read_text(encoding='utf-8'))
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    with transaction(db):
        db.executemany('INSERT INTO installation VALUES (?,?)', [('install-a', 'active'), ('install-b', 'active')])
        for owner, install, kind in [('panel-a', 'install-a', 'panel'), ('panel-b', 'install-a', 'panel'),
                                     ('backend-a', 'install-a', 'background'), ('panel-other', 'install-b', 'panel')]:
            identity = rfc8785.dumps({'fixture_owner': owner}).decode()
            db.execute('INSERT INTO owner VALUES (?,?,?,?,?,?)', (owner, install, kind, identity, digest(identity), 'active'))
        for exit_id, owner, install, kind, generation in [
            ('projection-a', 'panel-a', 'install-a', 'local_projection', 'boot-a'),
            ('preview-a', 'panel-a', 'install-a', 'local_preview', 'boot-a'),
            ('queue-a', 'panel-a', 'install-a', 'local_queue', 'boot-a'),
            ('worker-old', 'panel-a', 'install-a', 'device_worker', 'old-offline-boot'),
            ('worker-current', 'panel-b', 'install-a', 'device_worker', 'current-boot'),
            ('background-a', 'backend-a', 'install-a', 'background_worker', 'background-boot'),
            ('projection-other', 'panel-other', 'install-b', 'local_projection', 'other-boot')]:
            db.execute('INSERT INTO exit_registration VALUES (?,?,?,?,?)',
                       (exit_id, owner, install, kind, rfc8785.dumps({'fixture_generation': generation}).decode()))
        db.execute("INSERT INTO subscription VALUES ('panel-a','sub-a','projection-a','local_projection','live',3,1)")
        for seq in range(1, 4):
            db.execute('INSERT INTO projection_frame VALUES (?,?,?,?,?)', ('panel-a', 'sub-a', seq, digest({'seq': seq}), 'outstanding'))
    return db


def start_capture(db, operation='close-a', install='install-a'):
    # 唯一writer内的候选步骤；不模拟浏览器或真实IPC。
    db.execute("UPDATE installation SET state='revoking' WHERE installation_id=?", (install,))
    db.execute("UPDATE owner SET state='denied' WHERE installation_id=?", (install,))
    db.execute("INSERT INTO close_batch VALUES (?,?,'building',NULL)", (operation, install))
    db.execute('INSERT INTO close_member SELECT ?,owner_id,installation_id,selector_digest FROM owner WHERE installation_id=?', (operation, install))
    db.execute("INSERT INTO close_target SELECT ?,exit_id,owner_id,installation_id,kind,generation_jcs,'pending' FROM exit_registration WHERE installation_id=?", (operation, install))
    db.execute("UPDATE subscription SET state='closing' WHERE state='live' AND owner_id IN (SELECT owner_id FROM owner WHERE installation_id=?)", (install,))
    db.execute('INSERT INTO audit VALUES (?)', (operation,))
    db.execute('INSERT INTO outbox VALUES (?)', (operation,))


def manifest(db, operation='close-a'):
    installation = db.execute('SELECT installation_id FROM close_batch WHERE operation_id=?', (operation,)).fetchone()[0]
    members = [dict(owner_id=o, selector_digest=s) for o, s in db.execute(
        'SELECT owner_id,selector_digest FROM close_member WHERE operation_id=? ORDER BY owner_id', (operation,))]
    targets = [dict(exit_id=e, owner_id=o, kind=k, generation=json.loads(g)) for e, o, k, g in db.execute(
        'SELECT exit_id,owner_id,kind,generation_jcs FROM close_target WHERE operation_id=? ORDER BY exit_id', (operation,))]
    return dict(operation_id=operation, installation_id=installation, members=members, targets=targets)


def freeze(db, operation='close-a'):
    value = digest(manifest(db, operation))
    db.execute("UPDATE close_batch SET phase='frozen',manifest_digest=? WHERE operation_id=?", (value, operation))
    return value


def capture(db):
    with transaction(db):
        start_capture(db)
        return freeze(db)


def evidence(db, exit_id, generation=None, evidence_type=None):
    row = db.execute('SELECT operation_id,exit_id,owner_id,kind,generation_jcs FROM close_target WHERE exit_id=?', (exit_id,)).fetchone()
    assert row
    op, e, owner, kind, original = row
    et = evidence_type or ('ipc_fence' if kind in ('device_worker', 'background_worker') else 'local_closed')
    db.execute('INSERT INTO close_evidence VALUES (?,?,?,?,?,?,?,?)',
               (op, e, owner, kind, generation or original, et, 'fixture-evidence:' + e, digest({'exit': e, 'kind': et})))
    # 合成证据只测试关联；未实现可信监督器和IPC coverage验证。
    db.execute("UPDATE close_target SET status='acknowledged' WHERE operation_id=? AND exit_id=?", (op, e))
    if kind == 'local_projection':
        db.execute("UPDATE subscription SET state='closed' WHERE exit_id=? AND state='closing'", (e,))
        db.execute("UPDATE projection_frame SET state='retired' WHERE owner_id=? AND subscription_id IN (SELECT subscription_id FROM subscription WHERE owner_id=? AND exit_id=?)", (owner, owner, e))


def run():
    results = []

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        results.append(dict(name=name, expected=expected, actual=actual, passed=True))

    def rejects(name, db, action, expected):
        try:
            with transaction(db):
                action()
        except sqlite3.IntegrityError as error:
            check(name, str(error), expected)
        else:
            raise AssertionError(name + ': 应拒绝却接受')

    db = fixture()
    captured = capture(db)
    check('完整捕获包含两个页面和后台', db.execute('SELECT owner_id FROM close_member ORDER BY owner_id').fetchall(),
          [('backend-a',), ('panel-a',), ('panel-b',)])
    check('包含离线出口且不含另一安装', db.execute('SELECT exit_id FROM close_target ORDER BY exit_id').fetchall(),
          [('background-a',), ('preview-a',), ('projection-a',), ('queue-a',), ('worker-current',), ('worker-old',)])
    check('冻结清单摘要绑定', captured, digest(manifest(db)))
    for name, sql, error in [
        ('撤销后注册owner拒绝', "INSERT INTO owner VALUES ('new','install-a','panel','{}','hash','active')", 'installation_denied'),
        ('撤销后注册出口拒绝', "INSERT INTO exit_registration VALUES ('late','panel-a','install-a','local_queue','{}')", 'exit_denied'),
        ('撤销后订阅拒绝', "INSERT INTO subscription VALUES ('panel-a','late','projection-a','local_projection','live',0,0)", 'subscription_denied'),
        ('撤销后释放新帧拒绝', "INSERT INTO projection_frame VALUES ('panel-a','sub-a',4,'hash','outstanding')", 'frame_denied'),
        ('拒绝重开安装', "UPDATE installation SET state='active' WHERE installation_id='install-a'", 'installation_immutable'),
        ('拒绝重开owner', "UPDATE owner SET state='active' WHERE owner_id='panel-a'", 'owner_denied'),
        ('冻结后不能删目标', "DELETE FROM close_target WHERE exit_id='worker-old'", 'capture_frozen'),
        ('冻结后不能增目标', "INSERT INTO close_target SELECT operation_id,'extra',owner_id,installation_id,kind,generation_jcs,'pending' FROM close_target LIMIT 1", 'capture_frozen'),
        ('冻结后不能删成员', "DELETE FROM close_member WHERE owner_id='panel-b'", 'capture_frozen'),
        ('不能改目标世代', "UPDATE close_target SET generation_jcs='{}' WHERE exit_id='worker-old'", 'target_immutable'),
        ('不能改manifest', "UPDATE close_batch SET manifest_digest='hash'", 'manifest_immutable'),
        ('无证据不能ack', "UPDATE close_target SET status='acknowledged' WHERE exit_id='worker-old'", 'evidence_required'),
        ('未齐不能完成', "UPDATE close_batch SET phase='acknowledged'", 'incomplete_evidence'),
        ('closing不推进消费', "UPDATE subscription SET acked=3", 'subscription_boundary'),
        ('closing不恢复live', "UPDATE subscription SET state='live'", 'subscription_boundary'),
        ('旧出口墓碑不删除', "DELETE FROM exit_registration WHERE exit_id='worker-old'", 'exit_tombstone'),
    ]:
        rejects(name, db, lambda sql=sql: db.execute(sql), error)
    rejects('新进程不能确认旧世代', db, lambda: evidence(db, 'worker-old', '{"fixture_generation":"new-boot"}'), 'FOREIGN KEY constraint failed')
    rejects('本地证据不能替代IPC', db, lambda: evidence(db, 'worker-old', evidence_type='local_closed'),
            "CHECK constraint failed: (kind IN ('device_worker','background_worker') AND evidence_type<>'local_closed')\n OR (kind IN ('local_projection','local_preview','local_queue') AND evidence_type<>'ipc_fence')")
    with transaction(db):
        for e in ('projection-a', 'preview-a', 'queue-a', 'worker-current', 'background-a'):
            evidence(db, e)
        db.execute("UPDATE close_target SET status='indeterminate' WHERE exit_id='worker-old'")
    check('退役保留未消费高水位', db.execute('SELECT state,sent,acked FROM subscription').fetchone(), ('closed', 3, 1))
    check('退役窗口释放', db.execute("SELECT count(*) FROM projection_frame WHERE state='outstanding'").fetchone()[0], 0)
    rejects('closed不接受迟到ACK', db, lambda: db.execute('UPDATE subscription SET acked=3'), 'subscription_boundary')
    rejects('indeterminate不能当完成', db, lambda: db.execute("UPDATE close_batch SET phase='acknowledged'"), 'incomplete_evidence')
    rejects('不能覆盖既有证据', db, lambda: db.execute("UPDATE close_evidence SET evidence_digest='changed'"), 'evidence_immutable')
    with transaction(db):
        evidence(db, 'worker-old', evidence_type='process_terminated')
        db.execute("UPDATE close_batch SET phase='acknowledged'")
    check('完整证据后可完成', db.execute('SELECT phase FROM close_batch').fetchone()[0], 'acknowledged')
    check('完成不重新激活安装', db.execute("SELECT state FROM installation WHERE installation_id='install-a'").fetchone()[0], 'revoking')
    check('另一安装保持原状态', db.execute("SELECT state FROM owner WHERE owner_id='panel-other'").fetchone()[0], 'active')
    db.close()

    db = fixture()
    db.execute("INSERT INTO exit_registration VALUES ('projection-second','panel-a','install-a','local_projection','{}')")
    db.execute("INSERT INTO subscription VALUES ('panel-a','sub-second','projection-second','local_projection','live',1,0)")
    db.execute("INSERT INTO projection_frame VALUES ('panel-a','sub-second',1,'hash','outstanding')")
    capture(db)
    with transaction(db):
        evidence(db, 'projection-a')
    check('同页面另一出口仍待核对', db.execute("SELECT state FROM subscription WHERE subscription_id='sub-second'").fetchone()[0], 'closing')
    check('不能代另一出口退役窗口', db.execute("SELECT state FROM projection_frame WHERE subscription_id='sub-second'").fetchone()[0], 'outstanding')
    rejects('复用订阅墓碑拒绝', db, lambda: db.execute("DELETE FROM subscription WHERE subscription_id='sub-a'"), 'subscription_tombstone')
    db.close()

    # 故意篡改捕获清单后重新计算正确摘要，独立集合约束仍必须拒绝。
    for name, mutation in [
        ('遗漏离线目标且重算摘要', "DELETE FROM close_target WHERE exit_id='worker-old'"),
        ('遗漏零出口owner且重算摘要', "DELETE FROM close_member WHERE owner_id='panel-empty'"),
        ('篡改selector且重算摘要', "DELETE FROM close_member WHERE owner_id='panel-empty'"),
        ('缺保护outbox', 'DELETE FROM outbox'),
        ('缺审计记录', 'DELETE FROM audit'),
    ]:
        db = fixture()
        db.execute("INSERT INTO owner VALUES ('panel-empty','install-a','panel','empty','original-selector','active')")
        def corrupt():
            start_capture(db)
            db.execute(mutation)
            if name.startswith('篡改'):
                db.execute("INSERT INTO close_member VALUES ('close-a','panel-empty','install-a','wrong-selector')")
            freeze(db)
        rejects(name, db, corrupt, 'incomplete_capture')
        check(name + '整事务回滚', db.execute('SELECT count(*) FROM close_batch').fetchone()[0], 0)
        db.close()

    db = fixture()
    db.execute("INSERT INTO exit_registration VALUES ('before','panel-b','install-a','local_queue','{}')")
    capture(db)
    check('注册先提交被捕获', db.execute("SELECT count(*) FROM close_target WHERE exit_id='before'").fetchone()[0], 1)
    db.close()
    db = fixture()
    def wrong_install():
        start_capture(db)
        db.execute("INSERT INTO close_member VALUES ('close-a','panel-other','install-b','hash')")
    rejects('其他安装不能混入成员', db, wrong_install, 'FOREIGN KEY constraint failed')
    try:
        with transaction(db):
            start_capture(db)
            freeze(db)
            raise RuntimeError('主动异常：提交前')
    except RuntimeError:
        pass
    check('提交前异常无半批次', (db.execute('SELECT count(*) FROM close_batch').fetchone()[0],
          db.execute("SELECT state FROM installation WHERE installation_id='install-a'").fetchone()[0]), (0, 'active'))
    capture(db)
    before = db.execute('SELECT * FROM close_batch').fetchall()
    check('响应丢失后仅查询原批次', db.execute('SELECT * FROM close_batch').fetchall(), before)
    try:
        with transaction(db):
            evidence(db, 'projection-a')
            raise RuntimeError('主动异常：ACK落库前')
    except RuntimeError:
        pass
    check('ACK事务异常不提前确认', db.execute("SELECT status FROM close_target WHERE exit_id='projection-a'").fetchone()[0], 'pending')
    check('ACK事务异常不遗留证据', db.execute('SELECT count(*) FROM close_evidence').fetchone()[0], 0)
    with transaction(db):
        evidence(db, 'projection-a')
    check('同证据重新提交后确认', db.execute("SELECT status FROM close_target WHERE exit_id='projection-a'").fetchone()[0], 'acknowledged')
    db.close()

    db = fixture()
    db.execute("INSERT INTO installation VALUES ('empty-install','active')")
    with transaction(db):
        start_capture(db, 'empty-close', 'empty-install')
        freeze(db, 'empty-close')
        db.execute("UPDATE close_batch SET phase='acknowledged' WHERE operation_id='empty-close'")
    check('完整空集可完成', db.execute("SELECT phase FROM close_batch WHERE operation_id='empty-close'").fetchone()[0], 'acknowledged')
    check('外键最终一致', db.execute('PRAGMA foreign_key_check').fetchall(), [])
    db.close()
    return dict(approved=False, runtime_approved=False, all_passed=True, checks=results,
                versions=dict(python=sys.version.split()[0], sqlite=sqlite3.sqlite_version),
                runtime_validation=dict(product_services=0, concurrency=0, disk_crash=0, browser=0, device=0, supervisor=0),
                limitations=['只用内存SQLite与串行顺序和主动异常', '身份和证据是人工夹具，未验证真实权限或监督器',
                             '未合并PS1至PS6及完整领域DDL', '计数为小整数，未验证生产U20和容量profile'])


def check_report(staged=False):
    def read(path):
        return subprocess.check_output(['git', 'show', ':' + path.relative_to(ROOT).as_posix()], cwd=ROOT) if staged else path.read_bytes()
    report = json.loads(read(REPORT))
    assert report['all_passed'] is True
    assert set(report['input_sha256']) == {p.relative_to(ROOT).as_posix() for p in INPUTS}
    for path in INPUTS:
        assert report['input_sha256'][path.relative_to(ROOT).as_posix()] == hashlib.sha256(read(path)).hexdigest(), path
    print('6份输入字节绑定一致；未重跑用例')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.check_report:
        check_report(args.staged)
    else:
        assert not args.staged
        output = run()
        output['input_sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS}
        if args.report:
            REPORT.write_bytes((json.dumps(output, ensure_ascii=False, indent=2) + '\n').encode())
        print('安装撤销与订阅SQL探针通过:', len(output['checks']))
