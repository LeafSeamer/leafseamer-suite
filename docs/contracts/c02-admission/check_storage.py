"""仅在内存执行裁决子域SQL；不实现HTTP、鉴权或设备派发。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUTS = [HERE / n for n in (
    'STORAGE.md', 'admission.sql', 'check_storage.py', 'admission.schema.json')]
TABLES = ('ca_scope', 'ca_namespace', 'ca_namespace_closure', 'ca_request_key',
          'ca_adjudication', 'ca_command_initial', 'ca_reservation', 'ca_commit',
          'ca_rejection', 'ca_audit', 'ca_notification')
DIGEST = 'sha256:' + 'a' * 64
BODY = b'{"fixture":true}'


def statement(table, **values):
    # 表/列只来自本文件的固定调用，不接收外部SQL或数据库路径。
    return (f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
            tuple(values.values()))


def namespace(name='ns', epoch='issuer.1'):
    return statement('ca_namespace', namespace_id=name, scope_id=1, issuer_id='issuer',
                     issuer_epoch=epoch, principal_id='person', request_epoch='requests.1',
                     owner_evidence_id='owner.' + name, owner_evidence_body=BODY)


def fixture():
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA recursive_triggers=ON')
    db.executescript((HERE / 'admission.sql').read_text(encoding='utf-8'))
    db.execute("INSERT INTO ca_scope VALUES(1,'controller','database.1',"
               "'command-admission/0.1.0-draft.1')")
    db.execute(*namespace())
    return db


def creation(decision='accepted', key='one', ns='ns', idem='request.1'):
    commit, command = 'commit.' + key, 'command.' + key
    kind = 'accept' if decision == 'accepted' else 'reject_new'
    rid = None if decision == 'accepted' else 'reject.' + key
    steps = [
        statement('ca_request_key', key_id=key, namespace_id=ns, operation_id='createCommand',
                  idempotency_key=idem, request_digest=DIGEST, device_id='device', content_body=BODY),
        statement('ca_adjudication', key_id=key, adjudication_id='adjudication.' + key,
                  revision='1', decision=decision, command_id=command if decision == 'accepted' else None,
                  commit_id=commit, commit_kind=kind, adjudication_digest=DIGEST, adjudication_body=BODY)]
    if decision == 'accepted':
        steps += [
            statement('ca_command_initial', command_id=command, key_id=key, decision=decision,
                      revision='1', command_digest=DIGEST, command_body=BODY, admission_binding_body=BODY),
            statement('ca_reservation', key_id=key, command_id=command,
                      capacity_profile_ref_body=BODY, dimensions_body=BODY)]
    steps += commit_steps(commit, key, kind, key, rid)
    if rid is not None:
        steps.append(rejection(rid, commit, key, 'reject.op.' + key))
    return steps


def rejection(rid, commit, key, operation):
    return statement('ca_rejection', rejection_id=rid, actor_issuer_id='issuer',
                     actor_issuer_epoch='issuer.1', actor_principal_id='person',
                     rejection_operation_id=operation, operation_digest=DIGEST, key_id=key,
                     commit_id=commit, request_body=BODY, authorization_evidence_body=BODY)


def commit_steps(commit, key, kind, creation_key, rid):
    return [
        statement('ca_commit', commit_id=commit, key_id=key, kind=kind,
                  creation_key_id=creation_key, rejection_id=rid, commit_body=BODY),
        statement('ca_audit', commit_id=commit, key_id=key, kind=kind, redacted_body=BODY),
        statement('ca_notification', commit_id=commit, key_id=key, kind=kind,
                  event_id='event.' + commit, payload_body=BODY)]


def reject_existing(key='one', operation='retry.1', suffix=None):
    rid, commit = 'reject.' + (suffix or operation), 'commit.' + (suffix or operation)
    return commit_steps(commit, key, 'reject_existing', None, rid) + [
        rejection(rid, commit, key, operation)]


def transact(db, steps, cut=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        for index, step in enumerate(steps):
            db.execute(*step)
            if index == cut:
                raise RuntimeError('injected_before_commit')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def snapshot(db):
    return {t: sorted(db.execute('SELECT * FROM ' + t).fetchall(), key=repr) for t in TABLES}


def run():
    checks = []
    connections = []

    def fresh(decision=None):
        db = fixture()
        connections.append(db)
        if decision:
            transact(db, creation(decision))
        return db

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append({'name': name, 'expected': expected, 'observed': actual})

    def denied(name, db, steps, code, message=None):
        before = snapshot(db)
        try:
            transact(db, steps)
        except sqlite3.IntegrityError as error:
            check(name, error.sqlite_errorcode, code)
            if message:
                check(name + '错误', str(error), message)
        else:
            raise AssertionError(name + ': 应拒绝')
        check(name + '全表回滚', snapshot(db) == before, True)

    try:
        db = fresh()
        check('完整11表', sorted(r[0] for r in db.execute(
            "SELECT name FROM sqlite_schema WHERE type='table'")), sorted(TABLES))
        check('外键开启', db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        check('REPLACE删除触发开启', db.execute('PRAGMA recursive_triggers').fetchone()[0], 1)
        for decision in ('accepted', 'rejected'):
            db = fresh(decision)
            check(decision + '裁决', db.execute(
                'SELECT decision,revision FROM ca_adjudication').fetchall(), [(decision, '1')])
            check(decision + '命令数', db.execute('SELECT count(*) FROM ca_command_initial').fetchone()[0],
                  1 if decision == 'accepted' else 0)
            check(decision + '完整关联', db.execute('PRAGMA foreign_key_check').fetchall(), [])
            # 相反裁决不能使用新key_id绕过同namespace操作幂等键。
            denied(decision + '先到后相反裁决', db,
                   creation('rejected' if decision == 'accepted' else 'accepted', 'other'),
                   sqlite3.SQLITE_CONSTRAINT_UNIQUE)
            original = db.execute('SELECT * FROM ca_adjudication').fetchall()
            transact(db, reject_existing())
            check(decision + '拒收操作不改原裁决', db.execute(
                'SELECT * FROM ca_adjudication').fetchall() == original, True)
            check(decision + '拒收独立通知', db.execute(
                'SELECT count(*) FROM ca_notification').fetchone()[0], 2)
            denied(decision + '重复拒收不新增', db, reject_existing(),
                   sqlite3.SQLITE_CONSTRAINT_UNIQUE)
            check(decision + '提交后查原', db.execute(
                'SELECT a.decision,a.command_id FROM ca_request_key k '
                'JOIN ca_adjudication a USING(key_id) JOIN ca_namespace n USING(namespace_id) '
                'WHERE n.issuer_id=? AND n.issuer_epoch=? AND n.principal_id=? '
                'AND n.request_epoch=? AND k.operation_id=? AND k.idempotency_key=?',
                ('issuer', 'issuer.1', 'person', 'requests.1', 'createCommand', 'request.1')).fetchall(),
                [(decision, 'command.one' if decision == 'accepted' else None)])

        # 单步缺失及逐写异常均必须不能留下半个裁决。
        for decision in ('accepted', 'rejected'):
            steps = creation(decision)
            for index in range(len(steps)):
                db = fresh()
                denied(f'{decision}缺写{index}', db, steps[:index] + steps[index+1:],
                       sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
                db = fresh()
                before = snapshot(db)
                try:
                    transact(db, steps, cut=index)
                except RuntimeError as error:
                    check(f'{decision}主动异常{index}', str(error), 'injected_before_commit')
                else:
                    raise AssertionError('未注入异常')
                check(f'{decision}异常全表回滚{index}', snapshot(db) == before, True)
        for index in range(len(reject_existing())):
            db = fresh('accepted')
            steps = reject_existing()
            denied(f'已受理后拒收缺写{index}', db, steps[:index] + steps[index+1:],
                   sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)

        db = fresh('accepted')
        transact(db, creation(key='two', idem='request.2'))
        transact(db, reject_existing())
        denied('同拒收操作换目标和内部ID', db,
               reject_existing(key='two', suffix='changed'),
               sqlite3.SQLITE_CONSTRAINT_UNIQUE)
        for label, table, old, new in (
            ('初始命令错配', 'ca_adjudication', 'command.one', 'command.other'),
            ('容量预留错配', 'ca_reservation', 'command.one', 'command.other'),
            ('审计错key', 'ca_audit', 'one', 'other'),
            ('通知错key', 'ca_notification', 'one', 'other'),
            ('通知错kind', 'ca_notification', 'accept', 'reject_new'),
        ):
            db = fresh()
            steps = creation()
            for i, (sql, values) in enumerate(steps):
                if sql.startswith('INSERT INTO ' + table + ' '):
                    assert old in values
                    steps[i] = (sql, tuple(new if v == old else v for v in values))
            denied(label, db, steps, sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)

        db = fresh('accepted')
        db.execute(*namespace('other.ns', 'issuer.2'))
        transact(db, creation(key='two', ns='other.ns'))
        check('issuer换代允许不同身份但不覆盖旧件', db.execute(
            'SELECT count(*) FROM ca_adjudication').fetchone()[0], 2)
        denied('同namespace不能换内部ID', db, [namespace('alias')],
               sqlite3.SQLITE_CONSTRAINT_UNIQUE)
        # 只测试SQL关联，不将新epoch视为实际签发或自动化批准。
        db = fresh()
        db.execute(*statement('ca_namespace_closure', namespace_id='ns',
                              protection_operation_id='close', closure_body=BODY))
        denied('关闭后不新受理', db, creation(), sqlite3.SQLITE_CONSTRAINT_TRIGGER, 'namespace_closed')
        transact(db, creation('rejected'))
        check('关闭后可永久拒收', db.execute('SELECT decision FROM ca_adjudication').fetchone()[0], 'rejected')
        denied('不能重开namespace', db, [('DELETE FROM ca_namespace_closure', ())],
               sqlite3.SQLITE_CONSTRAINT_TRIGGER, 'permanent_closure')
        denied('不能更换库身份', db, [("UPDATE ca_scope SET database_instance_id='new'", ())],
               sqlite3.SQLITE_CONSTRAINT_TRIGGER, 'immutable_scope')

        for table, reason in (
            ('ca_request_key', 'immutable_request'), ('ca_adjudication', 'immutable_adjudication'),
            ('ca_command_initial', 'immutable_initial'), ('ca_reservation', 'immutable_reservation'),
            ('ca_commit', 'immutable_commit'), ('ca_audit', 'immutable_audit'),
            ('ca_notification', 'immutable_notification')):
            db = fresh('accepted')
            column = db.execute('PRAGMA table_info(' + table + ')').fetchone()[1]
            for action in ('DELETE FROM ' + table, f'UPDATE {table} SET {column}={column}'):
                denied(table + action.split()[0], db, [(action, ())],
                       sqlite3.SQLITE_CONSTRAINT_TRIGGER, reason)
        db = fresh('rejected')
        denied('拒收操作不可删除', db, [('DELETE FROM ca_rejection', ())],
               sqlite3.SQLITE_CONSTRAINT_TRIGGER, 'immutable_rejection')
        denied('REPLACE不能复活墓碑', db, [
            ("INSERT OR REPLACE INTO ca_adjudication SELECT * FROM ca_adjudication", ())],
            sqlite3.SQLITE_CONSTRAINT_TRIGGER, 'immutable_adjudication')
        # 异内容必须返回冲突；SQL层不允许第二原件，HTTP错误映射另验。
        db = fresh('accepted')
        changed = creation('accepted', 'changed')
        sql, values = changed[0]
        changed[0] = (sql, tuple('sha256:' + 'b'*64 if v == DIGEST else v for v in values))
        denied('摘要不同仍冲突同键', db, changed, sqlite3.SQLITE_CONSTRAINT_UNIQUE)
        # 合成BODY被接收是明确限制反证：SQL不证明JCS/投影/授权。
        check('BODY未被SQL解释的限制', db.execute(
            'SELECT content_body FROM ca_request_key').fetchone()[0] == BODY, True)
        return checks
    finally:
        for db in connections:
            db.close()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged只能与--check-report共用')
    if args.check_report:
        read = (lambda p: subprocess.check_output(
            ['git', 'show', ':' + p.relative_to(ROOT).as_posix()], cwd=ROOT)) if args.staged else Path.read_bytes
        report = json.loads(read(HERE / 'storage-report.json'))
        expected = {p.relative_to(ROOT).as_posix() for p in INPUTS}
        assert set(report['inputs']) == expected
        for p in INPUTS:
            assert hashlib.sha256(read(p)).hexdigest() == report['inputs'][p.relative_to(ROOT).as_posix()]
        print('4份输入字节绑定通过；未重跑SQL')
    else:
        checks = run()
        report = dict(version='command-admission-storage/0.1.0-draft.1',
                      approved=False, all_passed=True, sqlite_version=sqlite3.sqlite_version,
                      check_count=len(checks), checks=checks,
                      limitations=['仅内存SQLite', '主动异常与串行步骤不是掉电或并发',
                                   'BODY和权威为合成占位', '不执行HTTP鉴权或设备'],
                      inputs={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in INPUTS})
        if args.report:
            (HERE / 'storage-report.json').write_bytes(encoded(report))
        print(json.dumps({'检查数':len(checks), '全部通过':True, 'SQLite':sqlite3.sqlite_version}, ensure_ascii=False))
