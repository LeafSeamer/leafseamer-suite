"""27表入站事务离线检查，身份/正文解析为合成前提，不启动任何服务。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

import check_journal as old
from build_inbox import build

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BODY=old.BODY
u,insert,transact=old.u,old.insert,old.transact
TABLES=old.TABLES+['tc_inbox','tc_inbox_seal']
INPUTS=[HERE/n for n in ('INBOX.md','inbox.sql','build_inbox.py','check_inbox.py','collector-storage-v02.sql',
                        'channel-v02.schema.json','journal.sql','build_journal.py','check_journal.py','storage.sql','check_storage.py')]
INCOMING={'HELLO':None,'CONFIG_ACK':'CONFIGURE','POLL_ACK':'POLL','CAPTURE_REPORT':None,
          'CAPTURE_STATUS':'QUERY_CAPTURE','QUERY_COMMIT':None,'STOP_ACK':'STOP'}
OUTGOING={'ACCEPT':{'HELLO'},'CONFIGURE':set(),'POLL':set(),'REPORT_STORED':{'CAPTURE_REPORT','CAPTURE_STATUS'},
          'QUERY_CAPTURE':set(),'COMMIT_STATUS':{'QUERY_COMMIT'},'STOP':set()}


def snapshot(db):return {t:db.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall() for t in TABLES}


def outbound(seq,kind,poll=None,commit=None,stop=None,reply=None):
    _,values=old.frame(seq,kind,poll,commit,stop)
    return insert('tc_frame',*values,reply)


def incoming(seq,kind,effect='observation',reply=None,capture=None,stop=None,response=None,body=BODY):
    return insert('tc_inbox','ch1',u(seq),f'i{seq}',kind,reply,effect,capture,stop,None if response is None else u(response),body,BODY)


def seal(seq):return insert('tc_inbox_seal','ch1',u(seq),BODY)


def fixture(max_inbox=32,max_queries=8):
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.executescript((HERE/'collector-storage-v02.sql').read_text(encoding='utf-8'))
    db.execute(*insert('ts_scope',1,'authority','database','reference-time-storage/0.1.0-draft.1'))
    db.execute(*insert('tc_policy',1,2,2,100000,8,max_queries,max_inbox,BODY))
    db.execute(*insert('ts_binding','b1',1,u(1),BODY));transact(db,old.base.bootstrap())
    db.execute(*insert('tc_source','source1','canonical1',BODY))
    db.execute(*insert('tc_channel','ch1','source1','b1','config1',BODY,BODY,BODY))
    transact(db,[incoming(1,'HELLO'),seal(1),outbound(1,'ACCEPT',reply='i1')]+old.write(1))
    transact(db,[outbound(2,'CONFIGURE')]+old.write(2)+[incoming(2,'CONFIG_ACK',reply='m2'),seal(2)])
    return db


def capture_steps(seq=4,kind='CAPTURE_REPORT',reply=None,outseq=4):
    steps=old.publication(seq=outseq)
    # 原25表函数给出固定写集；仅补本版本入站原子归属和回复身份。
    steps[-3]=outbound(outseq,'REPORT_STORED','p.c1','commit.c1',reply=f'i{seq}')
    return [incoming(seq,kind,'capture_new',reply=reply,capture='c1')]+steps+[seal(seq)]


def duplicate(db,seq,message,raw,current_peer=True):
    if not current_peer:return 'authority'
    row=db.execute('SELECT message_id,body FROM tc_inbox WHERE channel_id=? AND sequence=?',('ch1',u(seq))).fetchone()
    if row is None:return 'not_found_no_retry_permission'
    if row!=(message,raw):return 'identity_conflict'
    result=db.execute('SELECT result_body FROM tc_inbox_seal WHERE channel_id=? AND sequence=?',('ch1',u(seq))).fetchone()
    return 'fixed_history' if result else 'uncommitted_not_visible'


def run():
    checks=[];connections=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        complex_value=isinstance(expected,(dict,list,tuple,set,bytes))
        checks.append(dict(name=name,expected=True if complex_value else expected,observed=True if complex_value else actual))
    def fresh(**kwargs):
        db=fixture(**kwargs);connections.append(db);return db
    def sent(**kwargs):
        db=fresh(**kwargs);transact(db,old.reserve()+[outbound(3,'POLL','p.c1')]+old.write(3)+[incoming(3,'POLL_ACK',reply='m3'),seal(3)]);return db
    def published(**kwargs):
        db=sent(**kwargs);transact(db,capture_steps());return db
    def stopped(**kwargs):
        db=published(**kwargs);transact(db,old.stop()+old.write(4)+[outbound(5,'STOP',stop='stop1')]+old.write(5));return db
    def denied(name,db,steps):
        before=snapshot(db)
        try:transact(db,steps)
        except sqlite3.IntegrityError:check(name,'rejected','rejected')
        else:raise AssertionError(name+':未拒绝')
        check(name+'全库回滚',snapshot(db),before)
    def atomic(name,factory,steps):
        for i in range(len(steps)):
            denied(f'{name}缺写{i}',factory(),steps[:i]+steps[i+1:])
            db=factory();before=snapshot(db)
            try:transact(db,steps,cut=i)
            except RuntimeError as error:check(f'{name}故障{i}',str(error),'synthetic_cut')
            else:raise AssertionError('未命中故障')
            check(f'{name}故障{i}全库回滚',snapshot(db),before)
    try:
        check('生成字节',(HERE/'collector-storage-v02.sql').read_bytes(),build().encode())
        db=fresh();check('27表集合',sorted(r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")),sorted(TABLES))
        schema=json.loads((HERE/'channel-v02.schema.json').read_bytes())
        models={}
        for item in schema['oneOf']:
            model=schema['$defs'][item['$ref'].split('/')[-1]];models[model['properties']['type']['const']]=model
        check('十四消息无遗漏',set(models),set(INCOMING)|set(OUTGOING))
        for name,model in models.items():
            check(name+'方向',model['properties']['direction']['const'],'collector_to_core' if name in INCOMING else 'core_to_collector')
            required_reply=bool(INCOMING.get(name)) if name in INCOMING else bool(OUTGOING[name])
            check(name+'回复是否必需',model['properties']['reply_to'].get('type')!='null',required_reply)
        for table,expected in [('tc_frame',set(OUTGOING)),('tc_inbox',set(INCOMING))]:
            sql=db.execute('SELECT sql FROM sqlite_schema WHERE name=?',(table,)).fetchone()[0]
            choices=set(re.findall("'([^']+)'",re.search(r'kind TEXT NOT NULL CHECK\(kind IN\(([^)]*)\)\)',sql).group(1)))
            check(table+'枚举严格等于协议方向集合',choices,expected)
        denied('拒旧错误QUERY_POLL',db,[outbound(3,'QUERY_POLL')])
        denied('拒核心发送QUERY_COMMIT',db,[outbound(3,'QUERY_COMMIT')])
        atomic('Capture与入站同事务',sent,capture_steps())
        stopsteps=[incoming(5,'STOP_ACK','stop_new',reply='m5',stop='stop1'),insert('tc_ack','stop1','ch1',u(5),u(1),u(500),BODY),seal(5)]
        atomic('STOP_ACK与入站同事务',stopped,stopsteps)
        querysteps=[incoming(5,'QUERY_COMMIT','query',response=5),outbound(5,'COMMIT_STATUS',reply='i5'),seal(5)]
        atomic('QUERY_COMMIT与固定应答同事务',published,querysteps)
        db=published();before=snapshot(db)
        check('提交后丢反馈只读原结果',duplicate(db,4,'i4',BODY),'fixed_history')
        check('原结果查询不重新发布',snapshot(db),before)
        check('已存在也先验当前peer',duplicate(db,4,'i4',BODY,False),'authority')
        check('同序号异消息拒绝',duplicate(db,4,'changed',BODY),'identity_conflict')
        check('同身份异字节拒绝',duplicate(db,4,'i4',b'changed'),'identity_conflict')
        check('未找到不是重发授权',duplicate(db,9,'i9',BODY),'not_found_no_retry_permission')
        transact(db,[incoming(5,'CAPTURE_REPORT','capture_existing',capture='c1'),seal(5)])
        check('新序号相同Capture只存历史指向',db.execute('SELECT count(*) FROM ts_capture').fetchone()[0],1)
        check('新序号重复不多发持久回执',db.execute("SELECT count(*) FROM tc_frame WHERE kind='REPORT_STORED'").fetchone()[0],1)
        denied('序号缺口不能接纳',published(),[incoming(6,'CAPTURE_REPORT','capture_existing',capture='c1'),seal(6)])
        denied('message_id不能跨序号复用',published(),[("INSERT INTO tc_inbox SELECT channel_id,?,message_id,kind,reply_to,'capture_existing',capture_id,stop_id,response_sequence,body,verification_body FROM tc_inbox WHERE sequence=?",(u(5),u(4))),seal(5)])
        denied('相同Capture不能声明新效果',published(),[incoming(5,'CAPTURE_REPORT','capture_new',capture='c1'),seal(5)])
        denied('无原效果不得声称existing',sent(),[incoming(4,'CAPTURE_REPORT','capture_existing',capture='missing'),seal(4)])
        denied('POLL_ACK不准回复CONFIGURE',fresh(),[incoming(3,'POLL_ACK',reply='m2'),seal(3)])
        db=fresh();transact(db,old.reserve()+[outbound(3,'POLL','p.c1')])
        denied('未尝试请求不接受回复',db,[incoming(3,'POLL_ACK',reply='m3'),seal(3)])
        denied('主动报告不夹reply_to',sent(),[incoming(4,'CAPTURE_REPORT','capture_new',reply='m3',capture='c1')])
        denied('STOP_ACK不能作为普通观察跳过效果',stopped(),[incoming(5,'STOP_ACK',reply='m5'),seal(5)])
        db=stopped();transact(db,stopsteps)
        transact(db,[incoming(6,'STOP_ACK','stop_existing',reply='m5',stop='stop1'),seal(6)])
        check('重复ACK不重写原闭闸tick',db.execute('SELECT closed_tick FROM tc_ack').fetchone()[0],u(500))
        db=sent();transact(db,[outbound(4,'QUERY_CAPTURE')]+old.write(4))
        transact(db,capture_steps(4,'CAPTURE_STATUS','m4',5))
        check('查询首次找回Capture同样原子提交',db.execute('SELECT count(*) FROM ts_capture').fetchone()[0],1)
        db=sent();transact(db,[outbound(4,'QUERY_CAPTURE')]+old.write(4)+[incoming(4,'CAPTURE_STATUS',reply='m4'),seal(4)])
        check('cache_missing观察不释放额度',db.execute('SELECT count(*) FROM tc_active').fetchone()[0],1)
        db=stopped(max_inbox=4)
        denied('普通入站满额不增长',db,[incoming(5,'CAPTURE_REPORT','capture_existing',capture='c1'),seal(5)])
        transact(db,stopsteps)
        check('首个STOP_ACK保留独立槽',db.execute('SELECT count(*) FROM tc_inbox').fetchone()[0],5)
        denied('不同序号重复STOP_ACK仍受预算',db,[incoming(6,'STOP_ACK','stop_existing',reply='m5',stop='stop1'),seal(6)])
        for table in ('tc_inbox','tc_inbox_seal'):
            denied(table+'不可改',published(),[(f'UPDATE {table} SET sequence=sequence',())])
            denied(table+'不可删',published(),[(f'DELETE FROM {table}',())])
        check('合成正文可通过不代表完成解码',BODY.startswith(b'synthetic'),True)
        return dict(version='collector-inbox/0.1.0-draft.1',approved=False,all_passed=True,check_count=len(checks),table_count=len(TABLES),
                    sqlite_version=sqlite3.sqlite_version,checks=checks,
                    runtime_validation=dict(ipc=0,ntp=0,authority=0,strict_decoder=0,concurrency=0,disk_crash=0,device=0),
                    artifact_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
    finally:
        for db in connections:db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    path=HERE/'inbox-report.json'
    if args.check_report:
        def raw(p):return subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if args.staged else p.read_bytes()
        report=json.loads(raw(path));assert set(report['artifact_sha256'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for rel,digest in report['artifact_sha256'].items():assert hashlib.sha256(raw(ROOT/rel)).hexdigest()==digest,rel
        print(f'{len(INPUTS)}项输入绑定一致；未重跑检查')
    else:
        if args.staged:parser.error('--staged仅用于--check-report')
        report=run()
        if args.report:path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps({k:report[k] for k in ('all_passed','check_count','table_count','runtime_validation')},ensure_ascii=False))
