"""只在内存验证采集日志组合；BODY和监督权威均为合成前提。"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

import check_storage as base
from build_journal import build, TABLES as EXTRA

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BODY = base.BODY
u, insert, transact = base.u, base.insert, base.transact
TABLES = base.TABLES + EXTRA
INPUTS = [HERE / n for n in ('JOURNAL.md', 'journal.sql', 'build_journal.py', 'collector-storage.sql',
                            'check_journal.py', 'storage.sql', 'check_storage.py', 'CHANNEL_V02.md')]


def snapshot(db):
    return {name: db.execute(f'SELECT * FROM {name} ORDER BY rowid').fetchall() for name in TABLES}


def frame(seq, kind, poll=None, commit=None, stop=None, channel='ch1', message=None):
    return insert('tc_frame', channel, u(seq), message or f'm{seq}', kind, poll, commit, stop, BODY)


def write(seq, channel='ch1'):
    return [insert('tc_attempt', channel, u(seq), BODY), insert('tc_written', channel, u(seq), BODY)]


def reserve(name='c1', ordinal=1, size=10000, channel='ch1', binding='b1'):
    return [insert('ts_poll', 'p.'+name, binding, 'correlation.'+name, BODY),
            insert('tc_reservation', 'p.'+name, channel, binding, u(ordinal), size, BODY)]


def publication(name='c1', seq=2, revision=2, kind='publish'):
    steps = base.publication(name, revision=revision, kind=kind)
    return steps[:-1] + [frame(seq, 'REPORT_STORED', 'p.'+name, 'commit.'+name),
                        insert('tc_release', 'p.'+name, 'ch1', 'stored', 'commit.'+name, u(seq), None, BODY)] + steps[-1:]


def stop():
    steps = base.invalidation(revision=3)
    return steps[:-1] + [insert('tc_stop', 'stop1', 'ch1', 'invalidate3', BODY)] + steps[-1:]


def retired():
    return [insert('tc_retired', 'ch1', 'supervisor.fixture', BODY, u(500), BODY)]


def fixture(max_bytes=100000, max_outstanding=2, max_sources=2, max_queries=1):
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.executescript((HERE / 'collector-storage.sql').read_text(encoding='utf-8'))
    db.execute(*insert('ts_scope', 1, 'authority', 'database', 'reference-time-storage/0.1.0-draft.1'))
    db.execute(*insert('tc_policy', 1, max_sources, max_outstanding, max_bytes, 8, max_queries, BODY))
    db.execute(*insert('ts_binding', 'b1', 1, u(1), BODY))
    transact(db, base.bootstrap())
    db.execute(*insert('tc_source', 'source1', 'canonical1', BODY))
    db.execute(*insert('tc_channel', 'ch1', 'source1', 'b1', 'config1', BODY, BODY, BODY))
    return db


def run():
    checks, connections = [], []

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        compound = isinstance(expected, (dict, list, tuple, bytes))
        checks.append(dict(name=name, observed=True if compound else actual, expected=True if compound else expected))

    def fresh(**kwargs):
        db = fixture(**kwargs); connections.append(db); return db

    def sent(**kwargs):
        db = fresh(**kwargs)
        transact(db, reserve() + [frame(1, 'POLL', 'p.c1')] + write(1))
        return db

    def published(**kwargs):
        db = sent(**kwargs); transact(db, publication()); return db

    def stopped():
        db = published(); transact(db, stop()); return db

    def denied(name, db, steps):
        before = snapshot(db)
        try:
            transact(db, steps)
        except sqlite3.IntegrityError:
            check(name, 'rejected', 'rejected')
        else:
            raise AssertionError(name + ': 未拒绝')
        check(name+'全库回滚', snapshot(db), before)

    def atomic(name, factory, steps):
        for i in range(len(steps)):
            denied(f'{name}缺写{i}', factory(), steps[:i]+steps[i+1:])
            db = factory(); before = snapshot(db)
            try:
                transact(db, steps, cut=i)
            except RuntimeError as error:
                check(f'{name}故障{i}', str(error), 'synthetic_cut')
            else:
                raise AssertionError('未触发故障')
            check(f'{name}故障{i}全库回滚', snapshot(db), before)

    try:
        check('固定组合生成字节', (HERE/'collector-storage.sql').read_bytes(), build().encode('utf-8'))
        db = fresh()
        check('25表全集', sorted(x[0] for x in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")), sorted(TABLES))
        check('foreign_keys', db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        check('recursive_triggers', db.execute('PRAGMA recursive_triggers').fetchone()[0], 1)
        atomic('预约', fresh, reserve())
        for kind in ('publish', 'reject', 'failure'):
            atomic(kind, sent, publication(kind=kind))
            db = sent(); transact(db, publication(kind=kind))
            check(kind+'释放活动但保留存储', db.execute('SELECT count(*) FROM tc_active').fetchone()[0], 0)
            check(kind+'原件预算不退款', db.execute('SELECT sum(reserved_bytes) FROM tc_reservation').fetchone()[0], 10000)
        atomic('失效同时STOP', published, stop())
        db = published(); before = snapshot(db)
        check('丢回执查询原提交', db.execute("SELECT receipt_body FROM ts_commit WHERE id='commit.c1'").fetchone()[0], BODY)
        check('只查不改变状态', snapshot(db), before)
        transact(db, reserve('c2', 2)+[frame(3, 'POLL', 'p.c2')])
        denied('不能越过未写完整回执发送下一POLL', db, [insert('tc_attempt','ch1',u(3),BODY)])
        transact(db, write(2)+write(3))
        check('回执严格先于下一采样', db.execute('SELECT sequence FROM tc_written ORDER BY sequence').fetchall(), [(u(1),),(u(2),),(u(3),)])
        denied('重复网络尝试不获第二标记', db, [insert('tc_attempt','ch1',u(3),BODY)])
        denied('旧poll改sequence不能重排', db, [frame(4,'POLL','p.c1')])
        denied('poll标识不能换ordinal复活', db, reserve('c1',3))
        denied('poll ordinal不跳号', published(), reserve('c2',3))
        denied('frame sequence不跳号', sent(), [frame(3,'QUERY_POLL')])
        db = sent(); transact(db,[frame(2,'QUERY_POLL')])
        denied('查询预算无界增长拒绝', db, [frame(3,'QUERY_COMMIT')])
        denied('报告尚未提交仍占单源槽', sent(), reserve('c2',2))
        denied('活动释放不退款存储额度', published(max_bytes=10000), reserve('c2',2))
        db = fresh(); transact(db,reserve(size=1)+[frame(1,'POLL','p.c1')]+write(1))
        denied('实际原件超过预约', db, publication())
        db = fresh(); transact(db,[insert('tc_source','source2','canonical2',BODY),insert('tc_channel','ch2','source2','b1','config2',BODY,BODY,BODY)])
        transact(db,reserve())
        transact(db,reserve('c2',1,channel='ch2'))
        check('不同稳定来源可以同时预约', db.execute('SELECT count(*) FROM tc_active').fetchone()[0], 2)
        db = fresh(max_outstanding=1)
        transact(db,[insert('tc_source','source2','canonical2',BODY),insert('tc_channel','ch2','source2','b1','config2',BODY,BODY,BODY)])
        transact(db,reserve())
        denied('跨实例共享全局活动额度',db,reserve('c2',1,channel='ch2'))
        denied('换实例不绕同源存活', fresh(),[insert('tc_channel','ch2','source1','b1','config2',BODY,BODY,BODY)])
        denied('同规范摘要不建来源别名',fresh(),[insert('tc_source','alias','canonical1',BODY)])
        db=sent();wrong=publication();wrong[-3]=frame(2,'REPORT_STORED','p.c1','boot1')
        denied('回执不能绑定初始化提交',db,wrong)
        db=sent();wrong=publication();wrong[-2]=insert('tc_release','p.c1','ch1','stored','commit.c1',u(1),None,BODY)
        denied('不能把POLL帧当持久回执',db,wrong)
        db=fresh();transact(db,reserve()+[frame(1,'POLL','p.c1')])
        denied('未尝试采样不伪造采集器报告',db,publication())
        db=fresh(max_sources=1); db.execute(*insert('tc_source','source2','canonical2',BODY))
        denied('最大活动来源数',db,[insert('tc_channel','ch2','source2','b1','config2',BODY,BODY,BODY)])
        db=fresh();transact(db,[insert('tc_source','source2','canonical2',BODY),insert('tc_channel','ch2','source2','b1','config2',BODY,BODY,BODY)])
        transact(db,reserve()+[frame(1,'POLL','p.c1')]+write(1)+publication())
        denied('失效漏掉第二个channel拒绝封存',db,stop())
        steps=stop();steps.insert(-1,insert('tc_stop','stop2','ch2','invalidate3',BODY));transact(db,steps)
        check('失效捕获两个完整channel',db.execute('SELECT channel_id FROM tc_stop ORDER BY channel_id').fetchall(),[('ch1',),('ch2',)])
        db = stopped()
        denied('STOP后不再预约',db,reserve('c2',2))
        transact(db,[frame(3,'STOP',stop='stop1')]+write(2)+write(3))
        denied('ACK错已处理ordinal',db,[insert('tc_ack','stop1','ch1',u(3),u(2),u(500),BODY)])
        transact(db,[insert('tc_ack','stop1','ch1',u(3),u(1),u(500),BODY)])
        denied('原ACK不可替换',db,[('UPDATE tc_ack SET closed_tick=?',(u(600),))])
        denied('不同stop身份不能覆盖',db,[insert('tc_stop','stop2','ch1','invalidate3',BODY)])
        # 未知采样即使有STOP_ACK仍占槽，只有可信退役可关闭执行额度。
        db=published(); transact(db,reserve('c2',2)+[frame(3,'POLL','p.c2')]+write(2)+write(3))
        transact(db,stop()+[frame(4,'STOP',stop='stop1')]+write(4)+[insert('tc_ack','stop1','ch1',u(4),u(2),u(500),BODY)])
        check('STOP_ACK不释放未知活动',db.execute('SELECT poll_id FROM tc_active').fetchall(),[('p.c2',)])
        denied('没有退役证据不能释放未知',db,[insert('tc_release','p.c2','ch1','retired',None,None,'ch1',BODY)])
        transact(db,retired()+[insert('tc_release','p.c2','ch1','retired',None,None,'ch1',BODY)])
        check('退役关闭执行槽',db.execute('SELECT count(*) FROM tc_active').fetchone()[0],0)
        check('未知墓碑存储额度保留',db.execute('SELECT sum(reserved_bytes) FROM tc_reservation').fetchone()[0],20000)
        denied('退役实例不可排新帧',db,[frame(5,'QUERY_COMMIT')])
        transact(db,base.publication('c2',kind='failure'))
        check('退役后迟到失败保留历史不送旧连接',db.execute("SELECT disposition FROM ts_capture WHERE id='c2'").fetchone()[0],'failure_recorded')
        transact(db,base.bootstrap(4,'b2'))
        transact(db,[insert('tc_channel','ch2','source1','b2','config2',BODY,BODY,BODY)])
        check('可信退役后新域可注册但间隔凭据仍是假定',db.execute('SELECT count(*) FROM tc_channel').fetchone()[0],2)
        db = fresh(); transact(db,reserve()+[frame(1,'POLL','p.c1'),insert('tc_attempt','ch1',u(1),BODY)])
        check('写标记后崩溃分类为未知',db.execute('SELECT disposition FROM tc_recovery').fetchone()[0],'write_unknown')
        denied('未知帧禁止再次消费',db,[insert('tc_attempt','ch1',u(1),BODY)])
        db = fresh(); transact(db,reserve()+[frame(1,'POLL','p.c1')])
        check('未尝试旧连接也不自动重发',db.execute('SELECT disposition FROM tc_recovery').fetchone()[0],'never_attempted_old_channel_not_replayable')
        for table in EXTRA:
            db=stopped(); transact(db,[frame(3,'STOP',stop='stop1')]+write(2)+write(3)+[insert('tc_ack','stop1','ch1',u(3),u(1),u(500),BODY)]+retired())
            column=db.execute(f'PRAGMA table_info({table})').fetchone()[1]
            denied(table+'不可改',db,[(f'UPDATE {table} SET {column}={column}',())])
            denied(table+'不可删',db,[(f'DELETE FROM {table}',())])
        check('合法占位BODY不证明身份或退役真实',BODY.startswith(b'synthetic'),True)
        return dict(version='collector-journal/0.1.0-draft.1', approved=False, all_passed=True,
                    check_count=len(checks), table_count=len(TABLES), sqlite_version=sqlite3.sqlite_version,
                    checks=checks, runtime_validation=dict(ipc=0,ntp=0,real_authority=0,disk_crash=0,concurrency=0,device=0),
                    artifact_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
    finally:
        for db in connections: db.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true')
    parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    path=HERE/'journal-report.json'
    if args.check_report:
        def raw(p):
            return subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if args.staged else p.read_bytes()
        report=json.loads(raw(path))
        assert set(report['artifact_sha256'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for rel,digest in report['artifact_sha256'].items():assert hashlib.sha256(raw(ROOT/rel)).hexdigest()==digest,rel
        print(f'{len(INPUTS)}项输入绑定一致；未重跑检查')
    else:
        if args.staged:parser.error('--staged仅用于--check-report')
        report=run()
        if args.report:path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps({k:report[k] for k in ('all_passed','check_count','table_count','sqlite_version','runtime_validation')},ensure_ascii=False))
