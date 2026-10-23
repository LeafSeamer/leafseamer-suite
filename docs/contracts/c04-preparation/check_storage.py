"""准备存储的内存参考检查；不接收数据库路径，不执行服务、设备或生产迁移。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUTS = [HERE / name for name in ('STORAGE.md', 'preparation.sql', 'check_storage.py', 'preparation.schema.json')]
TABLES = ('cp_scope', 'cp_request', 'cp_request_device', 'cp_event', 'cp_grant',
          'cp_receipt', 'cp_close', 'cp_protection', 'cp_protection_target',
          'cp_completion', 'cp_deny_event', 'cp_commit', 'cp_audit', 'cp_notification')
BODY = b'{"fixture":true}'
DIGEST = 'sha256:' + 'a' * 64


def decimal(value):
    value = str(value)
    if not value.isascii() or not value.isdecimal() or str(int(value)) != value or not 0 < int(value) < 10**20:
        raise ValueError('U20')
    return value.zfill(20)


def insert(table, **values):
    return (f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))


def fixture():
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA recursive_triggers=ON')
    db.executescript((HERE / 'preparation.sql').read_text(encoding='utf-8'))
    db.execute("INSERT INTO cp_scope VALUES(1,'controller','db.1')")
    return db


def request(key, commit, generation='1', preparation=None, run='run'):
    return [
        insert('cp_request', prep_key=key, origin_authority='seamer', origin_database='source.db',
               preparation_id=preparation or key, run_id=run, generation=decimal(generation),
               mode='arm', execution_id=None, request_digest=DIGEST, request_body=BODY,
               device_count=2, initial_commit=commit),
        insert('cp_request_device', prep_key=key, device_id='dev.1', expected_control_body=BODY),
        insert('cp_request_device', prep_key=key, device_id='dev.2', expected_control_body=BODY)]


def event(key, commit, state, revision, previous=None, receipt=None, completion=None):
    return insert('cp_event', event_id='event.' + commit, prep_key=key, revision=decimal(revision),
                  previous_revision=decimal(previous) if previous else None, state=state,
                  receipt_id=receipt, completion_id=completion, commit_id=commit)


def finish(key, commit, kind, close=None):
    return [
        insert('cp_audit', commit_id=commit, prep_key=key, redacted_body=BODY),
        insert('cp_notification', commit_id=commit, prep_key=key, event_id='notify.'+commit, payload_body=BODY),
        insert('cp_commit', commit_id=commit, prep_key=key, kind=kind,
               event_id=None if kind == 'close_noop' else 'event.'+commit, close_id=close)]


def register(key='p', generation='1', preparation=None, run='run'):
    commit = 'register.'+key
    return request(key, commit, generation, preparation, run) + [
        event(key, commit, 'accepted', '1')] + finish(key, commit, 'register')


def change(key='p', state='applied'):
    commit = state+'.'+key
    receipt = 'receipt.'+key if state == 'applied' else None
    steps = [event(key, commit, state, '2', '1', receipt)]
    if state == 'applied':
        steps += [
            insert('cp_grant', prep_key=key, grant_id='grant.'+key, receipt_id=receipt,
                   grant_revision=decimal('1'), grant_digest=DIGEST, grant_body=BODY),
            insert('cp_receipt', prep_key=key, receipt_id=receipt, request_digest=DIGEST,
                   grant_id='grant.'+key, receipt_digest=DIGEST, receipt_body=BODY, event_id='event.'+commit)]
    return steps + finish(key, commit, {'applied':'issue', 'rejected':'reject', 'indeterminate':'uncertain'}[state])


def close(key='p', previous='1', receipt=None, first=False, noop=False, suffix='one',
          generation='1', snapshot='1', deny_revision='1', raise_deny=True, preparation=None, run='run'):
    cid, commit = 'close.'+key+'.'+suffix, 'closing.'+key+'.'+suffix
    steps = request(key, commit, generation, preparation, run) if first else []
    if not noop:
        steps += [event(key, commit, 'closing', '1' if first else str(int(previous)+1),
                        None if first else previous, receipt)]
    steps += [
        insert('cp_close', close_id=cid, prep_key=key, operation_id='op.'+suffix,
               operation_digest=DIGEST, request_digest=DIGEST, request_body=BODY,
               authorization_body=BODY, commit_id=commit),
        insert('cp_protection', close_id=cid, prep_key=key, target_count=2, intent_body=BODY),
        insert('cp_protection_target', close_id=cid, target_id='old.exit', target_body=BODY),
        insert('cp_protection_target', close_id=cid, target_id='current.exit', target_body=BODY)]
    if raise_deny:
        steps += [insert('cp_deny_event', snapshot_revision=decimal(snapshot), origin_authority='seamer',
                         origin_database='source.db', run_id=run, generation=decimal(generation),
                         deny_revision=decimal(deny_revision), close_id=cid, commit_id=commit)]
    return steps + finish(key, commit, 'close_noop' if noop else 'close', cid)


def complete(key='p', previous='2', receipt=None, close_suffix='one'):
    commit, evidence = 'complete.'+key, 'evidence.'+key
    return [
        event(key, commit, 'closed', str(int(previous)+1), previous, receipt, evidence),
        insert('cp_completion', completion_id=evidence, prep_key=key, close_id='close.'+key+'.'+close_suffix,
               protection_ref_body=BODY, evidence_body=BODY, event_id='event.'+commit)
    ] + finish(key, commit, 'complete')


def transact(db, steps, cut=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        for i, step in enumerate(steps):
            db.execute(*step)
            if i == cut:
                raise RuntimeError('injected_before_commit')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def snapshot(db):
    return {t: sorted(db.execute('SELECT * FROM '+t).fetchall(), key=repr) for t in TABLES}


def mutate(steps, table, field, value):
    result = list(steps)
    for i, (sql, values) in enumerate(result):
        if sql.startswith('INSERT INTO '+table+' '):
            fields = sql[sql.index('(')+1:sql.index(')')].split(',')
            values = list(values)
            values[fields.index(field)] = value
            result[i] = sql, tuple(values)
            return result
    raise AssertionError(table)


def run():
    checks, connections = [], []

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(name=name, expected=expected, observed=actual))

    def fresh(stage=None):
        db = fixture()
        connections.append(db)
        if stage:
            transact(db, register())
        if stage in ('applied','rejected','indeterminate'):
            transact(db, change(state=stage))
        if stage == 'closing':
            transact(db, close())
        return db

    def denied(name, db, steps, error=None):
        before = snapshot(db)
        try:
            transact(db, steps)
        except sqlite3.IntegrityError as exc:
            check(name, str(exc) if error else 'constraint_rejected', error or 'constraint_rejected')
        else:
            raise AssertionError(name+': 必须拒绝')
        check(name+'全表回滚', snapshot(db) == before, True)

    def current(db):
        return db.execute('SELECT state,revision,receipt_id FROM cp_current WHERE prep_key=?', ('p',)).fetchone()

    try:
        db = fresh()
        check('完整14表', sorted(x[0] for x in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")), sorted(TABLES))
        check('外键开启', db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        check('递归触发开启', db.execute('PRAGMA recursive_triggers').fetchone()[0], 1)
        scenarios = [
            ('登记', None, register()),
            ('签发', 'accepted', change()),
            ('拒绝', 'accepted', change(state='rejected')),
            ('不确定', 'accepted', change(state='indeterminate')),
            ('关闭先到', None, close(first=True)),
            ('关闭已受理', 'accepted', close()),
            ('关闭已签发', 'applied', close(previous='2', receipt='receipt.p')),
            ('关闭完成', 'closing', complete()),
            ('关闭重复操作独立记账', 'closing', close(noop=True, suffix='two', raise_deny=False))]
        for label, stage, steps in scenarios:
            db = fresh(stage)
            transact(db, steps)
            check(label+'完整外键', db.execute('PRAGMA foreign_key_check').fetchall(), [])
            original = snapshot(db)
            # 提交后丢失回执时只读取持久状态，不再执行变更。
            check(label+'查原可见', current(db) is not None, True)
            check(label+'查原不变更', snapshot(db) == original, True)
            for i in range(len(steps)):
                db = fresh(stage)
                denied(f'{label}缺写{i}', db, steps[:i]+steps[i+1:])
                db = fresh(stage)
                before = snapshot(db)
                try:
                    transact(db, steps, cut=i)
                except RuntimeError as exc:
                    check(f'{label}故障{i}', str(exc), 'injected_before_commit')
                else:
                    raise AssertionError('未执行故障切点')
                check(f'{label}回滚{i}', snapshot(db) == before, True)

        db = fresh()
        transact(db, close(first=True))
        check('关闭先到状态', current(db), ('closing',decimal('1'),None))
        denied('后到签发', db, change(), 'invalid_transition')
        denied('换内部key重放prepare', db, register('alias', preparation='p'))
        denied('换准备ID绕过同run代次', db, register('alias'))
        transact(db, complete(previous='1'))
        check('关闭先到最终不含grant', db.execute('SELECT count(*) FROM cp_grant').fetchone()[0], 0)

        db = fresh('applied')
        original_receipt = db.execute('SELECT * FROM cp_receipt').fetchall()
        transact(db, close(previous='2', receipt='receipt.p'))
        transact(db, complete(previous='3', receipt='receipt.p'))
        check('签发先到保留回执', db.execute('SELECT * FROM cp_receipt').fetchall() == original_receipt, True)
        check('最终closed保留引用', current(db), ('closed',decimal('4'),'receipt.p'))
        transact(db, close(noop=True, suffix='two', raise_deny=False))
        check('已关闭重复独立操作不增状态修订', current(db)[1], decimal('4'))
        check('相同floor不增快照修订', db.execute('SELECT count(*) FROM cp_deny_event').fetchone()[0], 1)
        denied('同close_operation换内部id', db,
               mutate(close(noop=True, suffix='three', raise_deny=False), 'cp_close', 'operation_id', 'op.two'))
        denied('closed不可复活', db, [event('p','revive','applied','5','4','receipt.p')], 'invalid_transition')
        for stage in ('rejected','indeterminate'):
            db = fresh(stage)
            transact(db, close(noop=stage=='rejected', previous='2'))
            check(stage+'关闭后的状态', current(db)[0], 'rejected' if stage=='rejected' else 'closing')
            denied(stage+'不能补签', db, change())
        db = fresh('applied')
        denied('关闭不能丢弃历史回执', db, close(previous='2'), 'invalid_transition')
        denied('签发重复不能替换原件', db, change())

        db = fresh('closing')
        transact(db, register('new', generation='2'))
        transact(db, change('new'))
        transact(db, close('new',previous='2',receipt='receipt.new',generation='2',snapshot='2',deny_revision='2'))
        check('run拒绝下界升高', db.execute('SELECT generation,deny_revision,snapshot_revision FROM cp_deny_current').fetchall(),
              [(decimal('2'),decimal('2'),decimal('2'))])
        transact(db, close('other',first=True,run='other.run',snapshot='3'))
        check('另run独立行修订共享全局修订', db.execute(
              "SELECT deny_revision,snapshot_revision FROM cp_deny_current WHERE run_id='other.run'").fetchone(),
              (decimal('1'),decimal('3')))
        denied('低代次新签发被更强floor拦截', db,
               register('old',generation='1',run='run'))
        # 用尚未占用的低代次隔离deny门控，不能把唯一键冲突冒充floor验证。
        db = fresh()
        transact(db, close('high', first=True, generation='3'))
        denied('未占用低代次也不能登记', db, register('low', generation='2'), 'run_denied')
        db = fresh()
        transact(db, register('low', generation='2'))
        transact(db, close('high', first=True, generation='3'))
        denied('高代次关闭阻止旧accepted签发', db, change('low'), 'run_denied')
        transact(db, close('low', generation='2', raise_deny=False))
        check('较低代次关闭复用更强拒绝', db.execute('SELECT count(*) FROM cp_deny_event').fetchone()[0], 1)
        check('较低代次独立关闭已提交', db.execute('SELECT count(*) FROM cp_close').fetchone()[0], 2)
        # 已提交记录可查；未提交签发事件不能通过公开当前视图提前泄露。
        db = fresh('accepted')
        db.execute('BEGIN IMMEDIATE')
        try:
            for step in change()[:-1]:
                db.execute(*step)
            check('提交前当前视图仍accepted', current(db)[0], 'accepted')
        finally:
            db.execute('ROLLBACK')

        # 针对完整写集的错误关联，不只依赖缺写失败。
        for label, stage, steps in (
            ('签发错请求摘要','accepted',mutate(change(),'cp_receipt','request_digest','sha256:'+'b'*64)),
            ('签发错grant','accepted',mutate(change(),'cp_receipt','grant_id','alien')),
            ('receipt错事件','accepted',mutate(change(),'cp_receipt','event_id','alien')),
            ('保护目标数错误','accepted',mutate(close(),'cp_protection','target_count',1)),
            ('关闭错run','accepted',mutate(close(),'cp_deny_event','run_id','alien')),
            ('快照跳号','accepted',mutate(close(),'cp_deny_event','snapshot_revision',decimal('2'))),
            ('行修订跳号','accepted',mutate(close(),'cp_deny_event','deny_revision',decimal('2'))),
            ('状态修订跳号','accepted',mutate(change(),'cp_event','revision',decimal('3'))),
            ('complete错close','closing',mutate(complete(),'cp_completion','close_id','alien')),
            ('审计错准备','accepted',mutate(change(),'cp_audit','prep_key','alien')),
            ('accepted不能noop关闭','accepted',close(noop=True)),
            ('请求设备数错误',None,mutate(register(),'cp_request','device_count',1)),
            ('arm不能偷带execution',None,mutate(register(),'cp_request','execution_id','other')),
            ('recovery不能遗漏execution',None,mutate(register(),'cp_request','mode','recovery')),
            ('关闭错原请求摘要','accepted',mutate(close(),'cp_close','request_digest','sha256:'+'b'*64)),
        ):
            denied(label, fresh(stage), steps)

        db = fresh('closing')
        denied('冻结设备集',db,[insert('cp_request_device',prep_key='p',device_id='dev.extra',expected_control_body=BODY)],'device_set_frozen')
        denied('冻结出口集',db,[insert('cp_protection_target',close_id='close.p.one',target_id='extra',target_body=BODY)],'target_set_frozen')
        db = fresh('applied')
        transact(db,close(previous='2',receipt='receipt.p'))
        transact(db,complete(previous='3',receipt='receipt.p'))
        for table in TABLES:
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            denied(table+'禁止改写',db,[(f'UPDATE {table} SET {column}={column}',())],'immutable')
            denied(table+'禁止删除',db,[('DELETE FROM '+table,())],'immutable')
        denied('REPLACE不能替换墓碑',db,[('INSERT OR REPLACE INTO cp_request SELECT * FROM cp_request',())],'immutable')
        check('恢复分类不自动发命令',db.execute('SELECT disposition FROM cp_recovery').fetchone()[0],'retain_terminal')
        for stage, disposition in [('accepted','close_without_issuing'),('applied','history_and_close'),
                                   ('indeterminate','close_and_reconcile'),('closing','resume_same_protection')]:
            check(stage+'恢复分类',fresh(stage).execute('SELECT disposition FROM cp_recovery').fetchone()[0],disposition)
        # 独立表达式边界探针使用SQL中相同的两段算法；不是伪造十亿次状态转换。
        sql = """SELECT printf('%010d%010d',CAST(substr(?1,1,10) AS INTEGER)+(substr(?1,11,10)='9999999999'),
                       (CAST(substr(?1,11,10) AS INTEGER)+1)%10000000000)"""
        for value, expected in [('9','10'),('9999999999','10000000000'),
                                ('9223372036854775807','9223372036854775808'),
                                ('99999999999999999998','99999999999999999999')]:
            check('两段后继'+value, db.execute(sql,(decimal(value),)).fetchone()[0],decimal(expected))
        exhausted = db.execute(sql,(decimal('99999999999999999999'),)).fetchone()[0]
        check('耗尽不回绕',exhausted,'100000000000000000000')
        denied('21位修订拒绝',fresh(),mutate(register(),'cp_event','revision',exhausted))
        for value in ('01','1\n','-1','0','١','100000000000000000000'):
            try: decimal(value)
            except ValueError: check('wire计数拒绝'+repr(value),'rejected','rejected')
            else: raise AssertionError(value)
        check('合成BODY通过不证明JSON或权威',db.execute('SELECT request_body FROM cp_request').fetchone()[0]==BODY,True)
        return checks
    finally:
        for db in connections:
            db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report',action='store_true')
    parser.add_argument('--check-report',action='store_true')
    parser.add_argument('--staged',action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged只能与--check-report共用')
    if args.check_report:
        read = (lambda p: subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        report = json.loads(read(HERE/'storage-report.json'))
        assert set(report['inputs']) == {p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS:
            assert report['inputs'][p.relative_to(ROOT).as_posix()] == hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS),source='staged' if args.staged else 'worktree')))
    else:
        results = run()
        report = dict(scope='准备子域内存SQL及串行故障切点，非运行或生产迁移',
                      all_passed=True,cases_passed=len(results),runtime_approved=False,
                      runtime_tests_executed=0,device_tests_executed=0,sqlite_version=sqlite3.sqlite_version,
                      checks=results,inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if args.report:
            (HERE/'storage-report.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')},ensure_ascii=False,indent=2))
