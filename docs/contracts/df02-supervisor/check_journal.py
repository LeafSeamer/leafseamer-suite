"""完整监督日志布局的内存事务验证；无数据库路径参数，不启动真实进程。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
REPORT=HERE/'journal-report.json'
INPUTS=[HERE/n for n in ('JOURNAL.md','journal.sql','check_journal.py','supervisor.schema.json')]
INPUTS += [ROOT/'docs/rebirth-df04-storage-design.md']
TABLES={'journal_meta','runtime','control_scope','fence_snapshot','fence_item','launch_deny','current_fence','launch_intent','launch_state','creation_attempt','bootstrap_challenge','os_observation','admission_receipt','retirement_evidence','retirement_target'}
def encoded(v): return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()


@contextmanager
def tx(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except Exception:
        if db.in_transaction: db.execute('ROLLBACK')
        raise


def fixture():
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.executescript((HERE/'journal.sql').read_text(encoding='utf-8'))
    db.execute("INSERT INTO journal_meta VALUES(1,'supervisor-journal/0.1.0-draft.1','host.test','incarnation.test','storage.hash')")
    for sup in ('old','new'):
        db.execute('INSERT INTO runtime(supervisor_id,service_id,runtime_generation,domain_id,descriptor_digest,descriptor_jcs,protected_policy_digest,root_group_id,root_group_generation,root_backend) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (sup,'service.test','gen.'+sup,'domain.'+sup,'descriptor.hash',b'{}','policy.hash','root.'+sup,'root.gen.'+sup,'windows_job'))
        db.execute('INSERT INTO control_scope VALUES(?,?,?,?)',(sup,'service.test','database.test',b'{}'))
    return db


def snapshot(db,revision,items,sup='old',seal=True,count=None):
    db.execute('INSERT INTO fence_snapshot(supervisor_id,revision,snapshot_digest,snapshot_jcs,item_count) VALUES(?,?,?,?,?)',(sup,revision,'snapshot.'+revision,b'{}',len(items) if count is None else count))
    for ordinal,(launch,digest,decision) in enumerate(items):
        db.execute('INSERT INTO fence_item VALUES(?,?,?,?,?,?)',(sup,revision,ordinal,launch,digest,decision))
    if seal: db.execute('UPDATE fence_snapshot SET sealed=1 WHERE supervisor_id=? AND revision=?',(sup,revision))


def register(db,launch='one',sup='old',role='worker',intent_digest=None):
    db.execute('INSERT INTO launch_intent VALUES(?,?,?,?,?,?,?,?,?,?)',(sup,launch,intent_digest or 'hash.'+launch,b'{}','member.'+launch,role,'group.'+launch,'group.gen.'+launch,'extension' if role=='worker' else 'protected_config',b'{}'))
    db.execute('INSERT INTO launch_state(supervisor_id,launch_id) VALUES(?,?)',(sup,launch))


def observation(db,oid,kind,launch='one',subject='old',observer='old',tick='15'):
    group=('root.'+subject,'root.gen.'+subject) if launch is None else ('group.'+launch,'group.gen.'+launch)
    db.execute('INSERT INTO os_observation VALUES(?,?,?,?,?,?,?,?,?)',(oid,subject,launch,observer,kind,*group,tick,b'{}'))


def attempt(db,launch='one',sup='old',revision='1',recovery=True,protected=False,update=True):
    obs=None
    if not protected:
        obs='material.'+sup+'.'+launch;observation(db,obs,'materialization',launch,sup,sup,'10')
    db.execute('INSERT INTO creation_attempt(supervisor_id,launch_id,fence_revision,authorization_jcs,materialization_observation_id,is_recovery,recovery_policy_jcs,origin_tick) VALUES(?,?,?,?,?,?,?,?)',
        (sup,launch,None if protected else revision,None if protected else b'{}',obs,int(recovery),b'{}' if recovery else None,'10'))
    if update: db.execute("UPDATE launch_state SET state='creating',creation_attempted=1 WHERE supervisor_id=? AND launch_id=? AND state='registered' AND creation_attempted=0",(sup,launch))


def awaiting(db,launch='one',sup='old'):
    db.execute("UPDATE launch_state SET state='awaiting_bootstrap' WHERE supervisor_id=? AND launch_id=?",(sup,launch))
    db.execute('INSERT INTO bootstrap_challenge VALUES(?,?,?,?,?,?,?,?)',(sup,launch,'bootstrap.'+sup+'.'+launch,'boot.'+sup+'.'+launch,'channel.'+sup+'.'+launch,'10','20','transcript.hash'))
    observation(db,'process.'+sup+'.'+launch,'process_instance',launch,sup,sup)


def admit(db,launch='one',sup='old',tick='15',observation_id=None,update=True):
    db.execute('INSERT INTO admission_receipt VALUES(?,?,?,?,?,?,?)',(sup,launch,'receipt.'+sup+'.'+launch,'bootstrap.'+sup+'.'+launch,observation_id or 'process.'+sup+'.'+launch,tick,b'{}'))
    if update: db.execute("UPDATE launch_state SET state='admitted_closed',admission_id=? WHERE supervisor_id=? AND launch_id=?",('receipt.'+sup+'.'+launch,sup,launch))


def retire_evidence(db,eid='retirement.test',launch='one',members=None,result='confirmed_empty',seal=True):
    domain=launch is None
    members=([launch] if not domain else [r[0] for r in db.execute("SELECT launch_id FROM launch_intent WHERE supervisor_id='old'")]) if members is None else members
    oid='exit.'+eid
    observation(db,oid,'domain_exit' if domain else 'group_exit',launch,observer='new',tick='2')
    db.execute('INSERT INTO retirement_evidence(supervisor_id,evidence_id,target_scope,target_launch_id,observer_supervisor_id,observation_id,result,target_count,evidence_jcs) VALUES(?,?,?,?,?,?,?,?,?)',
        ('old',eid,'runtime_domain' if domain else 'member_group',launch,'new',oid,result,len(members),b'{}'))
    for m in members:db.execute('INSERT INTO retirement_target VALUES(?,?,?)',('old',m,eid))
    if seal:db.execute('UPDATE retirement_evidence SET sealed=1 WHERE evidence_id=?',(eid,))


def ready(stage='registered'):
    db=fixture()
    with tx(db):snapshot(db,'1',[('one','hash.one','allow')]);register(db)
    if stage!='registered':
        with tx(db):attempt(db)
    if stage in ('awaiting_bootstrap','admitted_closed'):
        with tx(db):awaiting(db)
    if stage=='admitted_closed':
        with tx(db):admit(db)
    return db


def run():
    checks=[];connections=[]
    def keep(db):connections.append(db);return db
    def check(name,observed,expected):
        assert observed==expected,(name,observed,expected)
        checks.append(dict(name=name,expected=expected,observed=observed))
    def reject(name,db,action,expected):
        try:
            with tx(db):action()
        except sqlite3.IntegrityError as e:check(name,str(e),expected)
        else:raise AssertionError(name+':未拒绝')
    db=keep(ready())
    check('完整15表',set(r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")),TABLES)
    check('FK已启用',db.execute('PRAGMA foreign_keys').fetchone()[0],1)
    check('REPLACE删除触发已启用',db.execute('PRAGMA recursive_triggers').fetchone()[0],1)
    with tx(db):register(db,'core',role='core');attempt(db,'core',protected=True,recovery=False)
    check('保护配置启动计数',db.execute("SELECT creation_attempted FROM launch_state WHERE launch_id='core'").fetchone()[0],1)
    reject('fence不能接管core分支',db,lambda:snapshot(db,'2',[('core','hash.core','deny'),('one','hash.one','allow')]),'known_intent')
    for name,items,error in [('遗漏registered',[],'live_coverage'),('同ID换摘要',[('one','different','deny')],'live_coverage'),('重复身份',[('one','hash.one','allow'),('one','hash.one','deny')],'UNIQUE constraint failed: fence_item.supervisor_id, fence_item.revision, fence_item.launch_id'),
        ('乱序',[('two','hash.two','allow'),('one','hash.one','allow')],'item_order')]:reject(name,db,lambda items=items:snapshot(db,'2',items),error)
    reject('声明数量不符',db,lambda:snapshot(db,'2',[('one','hash.one','allow')],count=2),'item_count')
    reject('不以字符串排序revision',db,lambda:snapshot(db,'0',[('one','hash.one','allow')]),'fence_not_increasing')
    with tx(db):snapshot(db,'10',[('one','hash.one','allow')])
    check('十进制10大于1',db.execute("SELECT revision FROM current_fence WHERE supervisor_id='old'").fetchone()[0],'10')
    reject('十进制9小于10',db,lambda:snapshot(db,'9',[('one','hash.one','allow')]),'fence_not_increasing')
    for value in ('01','1\n','1\x00','-1','100000000000000000000'):
        try:
            with tx(db):snapshot(db,value,[('one','hash.one','allow')])
        except sqlite3.IntegrityError as e:check('U20拒绝:'+repr(value),e.sqlite_errorcode,sqlite3.SQLITE_CONSTRAINT_CHECK)
        else:raise AssertionError(value)
    reject('冻结后追加',db,lambda:db.execute("INSERT INTO fence_item VALUES('old','10',1,'two','hash.two','allow')"),'snapshot_not_draft')
    reject('手动回退当前指针',db,lambda:db.execute("UPDATE current_fence SET revision='1' WHERE supervisor_id='old'"),'pointer_not_increasing')
    reject('伪造deny来源',db,lambda:db.execute("INSERT INTO launch_deny VALUES('old','one','hash.one','10')"),'deny_source')
    with tx(db):snapshot(db,'11',[('one','hash.one','deny'),('two','hash.two','deny')])
    check('deny和指针同发布',db.execute("SELECT launch_id FROM launch_deny WHERE supervisor_id='old' ORDER BY launch_id").fetchall(),[('one',),('two',)])
    reject('永久deny不复活',db,lambda:snapshot(db,'12',[('one','hash.one','allow')]),'permanent_deny')
    reject('未知deny换摘要',db,lambda:snapshot(db,'12',[('one','hash.one','deny'),('two','other','deny')]),'permanent_deny')
    reject('deny后创建',db,lambda:attempt(db,revision='11'),'attempt_authority')
    reject('deny目标不能REGISTER',db,lambda:register(db,'two'),'no_current_allow')
    # 原事务回滚后指针和新deny都不能留下；主动故障不冒充真实掉电。
    db=keep(ready())
    try:
        with tx(db):snapshot(db,'2',[('one','hash.one','deny')]);raise RuntimeError('cut.after.seal')
    except RuntimeError:pass
    check('fence提交前故障还原指针',db.execute("SELECT revision FROM current_fence WHERE supervisor_id='old'").fetchone()[0],'1')
    check('fence提交前故障不留deny',db.execute('SELECT count(*) FROM launch_deny').fetchone()[0],0)
    reject('孤立intent不能提交',db,lambda:db.execute("INSERT INTO launch_intent VALUES('old','core2','hash.core2',?,'member.core2','core','group.core2','group.gen.core2','protected_config',?)",(b'{}',b'{}')),'FOREIGN KEY constraint failed')
    reject('孤立state不能提交',db,lambda:db.execute("INSERT INTO launch_state(supervisor_id,launch_id) VALUES('old','ghost')"),'FOREIGN KEY constraint failed')
    def incomplete_registration():
        snapshot(db,'2',[('one','hash.one','allow'),('two','hash.two','allow')])
        db.execute("INSERT INTO launch_intent VALUES('old','two','hash.two',?,'member.two','worker','group.two','group.gen.two','extension',?)",(b'{}',b'{}'))
        snapshot(db,'3',[('one','hash.one','allow')])
    reject('未配state的intent也不能遗漏',db,incomplete_registration,'live_coverage')
    reject('孤立attempt不能提交',db,lambda:attempt(db,update=False),'FOREIGN KEY constraint failed')
    check('孤立attempt整体回滚',db.execute('SELECT count(*) FROM creation_attempt').fetchone()[0],0)
    reject('只有attempt标志不能提交',db,lambda:db.execute("UPDATE launch_state SET state='creating',creation_attempted=1 WHERE launch_id='one'"),'FOREIGN KEY constraint failed')
    with tx(db):attempt(db)
    check('attempt与预算同提交',db.execute('SELECT count(*) FROM recovery_attempt').fetchone()[0],1)
    reject('重复创建尝试',db,lambda:attempt(db,protected=True),'attempt_not_registered')
    reject('清除attempt',db,lambda:db.execute("UPDATE launch_state SET state='registered',creation_attempted=0 WHERE launch_id='one'"),'immutable_state_identity')
    reject('已尝试拒绝不能变未创建',db,lambda:db.execute("UPDATE launch_state SET state='rejected' WHERE launch_id='one'"),'state_edge')
    with tx(db):awaiting(db)
    reject('receipt不可单独提交',db,lambda:admit(db,update=False),'FOREIGN KEY constraint failed')
    check('receipt未提交不消费',db.execute('SELECT count(*) FROM admission_receipt').fetchone()[0],0)
    reject('只有准入状态不能提交',db,lambda:db.execute("UPDATE launch_state SET state='admitted_closed',admission_id='fake' WHERE launch_id='one'"),'FOREIGN KEY constraint failed')
    reject('到期等号拒绝',db,lambda:admit(db,tick='20'),'admission_window')
    reject('早于原起点拒绝',db,lambda:admit(db,tick='9'),'admission_window')
    reject('物化观测不能证进程身份',db,lambda:admit(db,observation_id='material.old.one'),'admission_observation')
    with tx(db):admit(db)
    check('准入与receipt同提交',db.execute("SELECT state,admission_id FROM launch_state WHERE launch_id='one'").fetchone(),('admitted_closed','receipt.old.one'))
    reject('重复消费proof',db,lambda:admit(db),'admission_state')
    # 两个目标及新观察域；不对两个域的tick做大小比较。
    with tx(db):
        snapshot(db,'2',[('one','hash.one','allow'),('two','hash.two','allow')]);register(db,'two');attempt(db,'two',revision='2')
    with tx(db):db.execute("UPDATE launch_state SET state='retiring' WHERE launch_id='one'")
    reject('同组观测不能换目标',db,lambda:retire_evidence(db,members=['two']),'member_retirement')
    with tx(db):retire_evidence(db,eid='unproven',result='unproven')
    reject('unproven不能退休',db,lambda:db.execute("UPDATE launch_state SET state='retired',retirement_id='unproven' WHERE launch_id='one'"),'retirement_unproven')
    with tx(db):retire_evidence(db)
    with tx(db):db.execute("UPDATE launch_state SET state='retired',retirement_id='retirement.test' WHERE launch_id='one'")
    check('新观察域tick2可证旧域退出',db.execute("SELECT observed_tick FROM os_observation WHERE observation_id='exit.retirement.test'").fetchone()[0],'2')
    reject('退休仍不能重建',db,lambda:db.execute("UPDATE launch_state SET state='creating' WHERE launch_id='one'"),'state_edge')
    with tx(db):snapshot(db,'3',[('two','hash.two','deny')])
    check('终态可退出现行集合且历史保留',db.execute("SELECT count(*) FROM launch_intent WHERE launch_id='one'").fetchone()[0],1)
    reject('域未关闭不能证空',db,lambda:retire_evidence(db,eid='domain',launch=None),'domain_retirement')
    with tx(db):db.execute("UPDATE runtime SET phase='closing' WHERE supervisor_id='old'")
    reject('关闭域拒绝新REGISTER',db,lambda:register(db,'core3',role='core'),'runtime_closed')
    reject('域证明遗漏已退出成员',db,lambda:retire_evidence(db,eid='domain',launch=None,members=['two']),'domain_retirement')
    with tx(db):retire_evidence(db,eid='domain',launch=None)
    reject('仍有非终态不能登记域退休',db,lambda:db.execute("UPDATE runtime SET phase='retired',domain_retirement_id='domain' WHERE supervisor_id='old'"),'domain_not_retired')
    with tx(db):
        db.execute("UPDATE launch_state SET state='retiring' WHERE launch_id='two'")
        db.execute("UPDATE launch_state SET state='retired',retirement_id='domain' WHERE launch_id='two'")
        db.execute("UPDATE runtime SET phase='retired',domain_retirement_id='domain' WHERE supervisor_id='old'")
    check('全域最终登记',db.execute("SELECT phase FROM runtime WHERE supervisor_id='old'").fetchone()[0],'retired')
    reject('域不复活',db,lambda:db.execute("UPDATE runtime SET phase='active' WHERE supervisor_id='old'"),'runtime_edge')
    check('旧恢复计数未清',db.execute('SELECT count(*) FROM recovery_attempt').fetchone()[0],2)
    # 修改/删除证据或用REPLACE覆盖，均需被不可变边界拒绝。
    immutable={'journal_meta':'host_installation_id','control_scope':'database_instance_id','fence_item':'intent_digest','launch_deny':'intent_digest','launch_intent':'intent_digest',
        'creation_attempt':'origin_tick','bootstrap_challenge':'transcript_digest','os_observation':'evidence_jcs','admission_receipt':'receipt_jcs','retirement_target':'evidence_id'}
    for table,column in immutable.items():reject('不可变:'+table,db,lambda table=table,column=column:db.execute(f'UPDATE {table} SET {column}={column}'),'immutable')
    for table in sorted(TABLES):
        assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]>0,table
        reject('不可删除:'+table,db,lambda table=table:db.execute('DELETE FROM '+table),'tombstone')
    reject('运行域原绑定不能修改',db,lambda:db.execute("UPDATE runtime SET root_backend='container_runtime' WHERE supervisor_id='old'"),'immutable_runtime')
    reject('封存快照不可改写',db,lambda:db.execute("UPDATE fence_snapshot SET snapshot_digest='other' WHERE supervisor_id='old' AND revision='3'"),'immutable_snapshot')
    reject('封存退出证据不可改写',db,lambda:db.execute("UPDATE retirement_evidence SET result='confirmed_empty' WHERE evidence_id='unproven'"),'immutable_retirement')
    reject('REPLACE不绕墓碑',db,lambda:db.execute("INSERT OR REPLACE INTO journal_meta VALUES(1,'supervisor-journal/0.1.0-draft.1','other','other','other')"),'tombstone')
    check('全部连接外键一致',[c.execute('PRAGMA foreign_key_check').fetchall() for c in connections],[[] for c in connections])
    for c in connections:c.close()
    for row in checks:
        for key in ('expected','observed'):
            if isinstance(row[key],set):row[key]=sorted(row[key])
    return dict(all_passed=True,approved=False,runtime_approved=False,checks=checks,sqlite_version=sqlite3.sqlite_version,
        runtime_validation=dict(supervisor=0,ipc=0,filesystem_durability=0,device=0),
        limitations=['只运行内存SQLite；主动异常及串行顺序不证明真实崩溃并发','BODY和digest用合成占位，不在SQL内执行Schema/JCS/HMAC或OS权威提供者','没有执行实际journal初始化、升级、归档或磁盘恢复','冻结候选不是已发布生产迁移或完整业务DDL'])


def hashes(staged=False):
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else p.read_bytes()).hexdigest() for p in INPUTS}


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group();g.add_argument('--report',action='store_true');g.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged只用于绑定检查')
    if a.check_report:
        r=json.loads(subprocess.check_output(['git','show',':'+REPORT.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else REPORT.read_bytes())
        assert r['all_passed'] and not r['approved'] and not r['runtime_approved'];assert r['input_sha256']==hashes(a.staged)
        print('监督日志5输入字节绑定一致，未重跑检查')
    else:
        r=run();r['input_sha256']=hashes()
        if a.report:REPORT.write_bytes(encoded(r))
        print('监督日志内存参考通过:',len(r['checks']))
