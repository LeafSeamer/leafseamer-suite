"""Controller共库组合的离线约束与故障切点；不执行业务服务或设备。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import build_layout

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREP = load('preparation_reference', HERE.parent/'c04-preparation/check_storage.py')
ADM = load('admission_reference', HERE.parent/'c02-admission/check_storage.py')
INPUTS = list(build_layout.SOURCES) + [HERE/name for name in (
    'README.md','build_layout.py','controller.sql','check_layout.py')]
INPUTS += [Path(PREP.__file__),Path(ADM.__file__),
           HERE.parent/'c05-protection/protocol.schema.json']
BODY, DIGEST, insert, decimal = PREP.BODY, PREP.DIGEST, PREP.insert, PREP.decimal
TABLES = sorted((set(ADM.TABLES) | set(PREP.TABLES)) - {'ca_scope','cp_scope','cp_deny_event'}
                | {'controller_scope','run_deny_event','run_protection_request','run_protection_target',
                   'run_protection_commit','run_protection_audit','run_protection_outbox'})


def prep_steps(steps):
    # 仅替换本组合显式迁移的表身份；不改任何请求正文、字段值或预期结果。
    return [(sql.replace('INSERT INTO cp_deny_event ', 'INSERT INTO run_deny_event '), values) for sql, values in steps]


def fixture():
    db = sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA recursive_triggers=ON')
    db.executescript((HERE/'controller.sql').read_text(encoding='utf-8'))
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    return db


def protect(key='protection', generation='1', snapshot='1', revision='1', raise_deny=True,
            run='run', origin_database='source.db', operation=None, targets=2):
    steps = [insert('run_protection_request',protection_id=key,scope_id=1,
                    origin_authority='seamer',origin_database=origin_database,
                    operation_id=operation or key,run_id=run,generation=decimal(generation),
                    request_digest=DIGEST,selector_digest=DIGEST,target_set_digest=DIGEST,
                    request_body=BODY,authorization_body=BODY,registry_snapshot_body=BODY,
                    capacity_reservation_body=BODY,target_count=targets)]
    steps += [insert('run_protection_target',protection_id=key,target_id='exit.'+str(i),target_body=BODY)
              for i in range(targets)]
    if raise_deny:
        steps += [insert('run_deny_event',snapshot_revision=decimal(snapshot),origin_authority='seamer',
                         origin_database=origin_database,run_id=run,generation=decimal(generation),
                         deny_revision=decimal(revision),protection_id=key)]
    return steps + [
        insert('run_protection_audit',protection_id=key,redacted_body=BODY),
        insert('run_protection_outbox',protection_id=key,event_id='notify.'+key,payload_body=BODY),
        insert('run_protection_commit',protection_id=key,commit_ref_body=BODY)]


def snapshot(db):
    return {t:sorted(db.execute('SELECT * FROM '+t).fetchall(),key=repr) for t in TABLES}


def run():
    checks, connections = [], []

    def check(name, actual, expected):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))

    def fresh():
        db=fixture()
        connections.append(db)
        return db

    def tx(db, steps, cut=None):
        PREP.transact(db,prep_steps(steps),cut)

    def denied(name,db,steps,message=None):
        before=snapshot(db)
        try: tx(db,steps)
        except sqlite3.IntegrityError as error:
            actual=error.sqlite_errorcode if isinstance(message,int) else str(error) if message else 'constraint_rejected'
            check(name,actual,message or 'constraint_rejected')
        else: raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚',snapshot(db)==before,True)

    def floor(db,run='run',origin='source.db'):
        return db.execute('SELECT generation,deny_revision,snapshot_revision FROM run_deny_current '
                          'WHERE run_id=? AND origin_database=?',(run,origin)).fetchone()

    try:
        check('生成物精确一致',(HERE/'controller.sql').read_bytes()==build_layout.build(),True)
        db=fresh()
        check('共库29表',sorted(x[0] for x in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")),TABLES)
        check('无重复scope或旧deny表',bool(set(TABLES)&{'ca_scope','cp_scope','cp_deny_event'}),False)
        check('空快照revision为零',db.execute('SELECT revision FROM run_deny_snapshot_revision').fetchone()[0],'0'*20)
        # 先核验组合后两条既有路径仍能完整提交，不能只证明新保护表可建。
        db.execute(*ADM.namespace())
        tx(db,ADM.creation())
        tx(db,ADM.reject_existing())
        tx(db,PREP.register())
        tx(db,PREP.change())
        tx(db,PREP.close(previous='2',receipt='receipt.p'))
        tx(db,PREP.complete(previous='3',receipt='receipt.p'))
        check('共库裁决仍accepted',db.execute('SELECT decision FROM ca_adjudication').fetchone()[0],'accepted')
        check('共库准备closed保留receipt',db.execute('SELECT state,receipt_id FROM cp_current').fetchone(),
              ('closed','receipt.p'))
        check('共库全部FK',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        denied('namespace不能选择另scope',db,[PREP.mutate([ADM.namespace('other')],'ca_namespace','scope_id',2)[0]])
        wrong_scope=PREP.register('other',generation='2')
        sql,values=wrong_scope[0]
        wrong_scope[0]=(sql.replace('(prep_key,','(scope_id,prep_key,').replace('VALUES (','VALUES (?,',1),(2,*values))
        denied('准备不能选择另scope',db,wrong_scope)
        denied('scope不可改库身份',db,[("UPDATE controller_scope SET database_instance_id='other'",())],'immutable_scope')
        denied('scope不可REPLACE',db,[("INSERT OR REPLACE INTO controller_scope SELECT * FROM controller_scope",())],'immutable_scope')

        # P2登记路径：无出口也必须保留拒绝墓碑；同请求查询不分配新修订。
        for count in (0,2):
            steps=protect(targets=count)
            db=fresh();tx(db,steps)
            check('目标数'+str(count),db.execute('SELECT count(*) FROM run_protection_target').fetchone()[0],count)
            check('空或非空目标都有floor'+str(count),floor(db),(decimal('1'),decimal('1'),decimal('1')))
            before=snapshot(db)
            check('原操作可查'+str(count),db.execute("SELECT operation_id FROM run_protection_request").fetchone()[0],'protection')
            check('查原不改写'+str(count),snapshot(db)==before,True)
            denied('同operation换内部ID'+str(count),db,protect('alias',operation='protection',raise_deny=False))
            denied('晚准备被通用保护拒绝'+str(count),db,PREP.register(),'run_denied')
            for i in range(len(steps)):
                db=fresh()
                denied(f'通用保护{count}目标缺写{i}',db,steps[:i]+steps[i+1:])
                db=fresh(); before=snapshot(db)
                try: tx(db,steps,cut=i)
                except RuntimeError as error: check(f'保护故障{count}/{i}',str(error),'injected_before_commit')
                else: raise AssertionError('未注入故障')
                check(f'保护故障回滚{count}/{i}',snapshot(db)==before,True)

        # 公共保护先到，准备关闭复用其floor；反序也复用同一份权威。
        db=fresh();tx(db,PREP.register());tx(db,PREP.change())
        tx(db,protect())
        tx(db,PREP.close(previous='2',receipt='receipt.p',raise_deny=False))
        check('通用先到准备关闭不增加floor',floor(db),(decimal('1'),decimal('1'),decimal('1')))
        tx(db,PREP.complete(previous='3',receipt='receipt.p'))
        check('通用先到不丢签发历史',db.execute('SELECT count(*) FROM cp_receipt').fetchone()[0],1)
        db=fresh();tx(db,PREP.close(first=True))
        tx(db,protect(raise_deny=False))
        check('准备先到通用保护复用floor',floor(db),(decimal('1'),decimal('1'),decimal('1')))
        denied('准备关闭后仍不可签发',db,PREP.change(),'invalid_transition')

        # 两入口交替抬高：global与per-run修订不能各自从1重新分配。
        db=fresh();tx(db,protect(generation='2'))
        tx(db,PREP.close('new',first=True,generation='3',snapshot='2',deny_revision='2'))
        tx(db,protect('higher',generation='5',snapshot='3',revision='3'))
        check('两入口连续抬高floor',floor(db),(decimal('5'),decimal('3'),decimal('3')))
        tx(db,protect('lower',generation='4',raise_deny=False))
        check('更低请求不降低或增加修订',floor(db),(decimal('5'),decimal('3'),decimal('3')))
        tx(db,protect('other',run='other.run',snapshot='4'))
        check('另一run独立行修订',floor(db,'other.run'),(decimal('1'),decimal('1'),decimal('4')))
        tx(db,protect('source2',origin_database='other.db',snapshot='5'))
        check('另一origin库隔离同名run',floor(db,origin='other.db'),(decimal('1'),decimal('1'),decimal('5')))
        denied('强floor阻止旧代次新登记',db,PREP.register('late',generation='4'),'run_denied')
        tx(db,PREP.register('future',generation='6'))
        check('更高代次可登记但未签发',db.execute("SELECT state FROM cp_current WHERE prep_key='future'").fetchone()[0],'accepted')
        check('原保护操作各自保留',db.execute('SELECT count(*) FROM run_protection_request').fetchone()[0],5)

        # 从另一入口已有的floor出发注入故障，确认失败不会丢失旧权威或消耗新修订。
        for label, setup, steps in (
            ('通用接续准备',PREP.close(first=True),protect(generation='2',snapshot='2',revision='2')),
            ('准备接续通用',protect(),PREP.close('next',first=True,generation='2',snapshot='2',deny_revision='2')),
        ):
            for i in range(len(steps)):
                db=fresh();tx(db,setup)
                denied(label+'缺写'+str(i),db,steps[:i]+steps[i+1:])
                db=fresh();tx(db,setup);before=snapshot(db)
                try: tx(db,steps,cut=i)
                except RuntimeError: check(label+'故障'+str(i),snapshot(db)==before,True)
                else: raise AssertionError('未执行混合切点')
                check(label+'旧floor保留'+str(i),floor(db),(decimal('1'),decimal('1'),decimal('1')))

        # 已accepted的准备在通用保护后不可继续issue。
        db=fresh();tx(db,PREP.register());tx(db,protect())
        denied('通用保护切断旧accepted签发',db,PREP.change(),'run_denied')
        # 各类跨来源绑定篡改都必须失败，不能仅靠相同run或摘要命中。
        for label,table,field,value in (
            ('错目标计数','run_protection_request','target_count',1),
            ('错origin','run_deny_event','origin_database','alien'),
            ('错run','run_deny_event','run_id','alien'),
            ('错floor','run_deny_event','generation',decimal('2')),
            ('错来源ID','run_deny_event','protection_id','alien'),
            ('全局修订跳号','run_deny_event','snapshot_revision',decimal('2')),
            ('行修订跳号','run_deny_event','deny_revision',decimal('2')),
            ('错审计归属','run_protection_audit','protection_id','alien'),
            ('错通知归属','run_protection_outbox','protection_id','alien'),
        ):
            denied(label,fresh(),PREP.mutate(protect(),table,field,value))
        db=fresh();tx(db,PREP.close(first=True))
        denied('来源缺失不允许',db,PREP.mutate(
            PREP.mutate(protect('dual',generation='2',snapshot='2',revision='2'),
                        'run_deny_event','protection_id',None),
            'run_deny_event','generation',decimal('2')),sqlite3.SQLITE_CONSTRAINT_CHECK)
        # 明确插入两个来源，以CHECK验证排他性，而非以缺失字段碰巧失败。
        db=fresh()
        pending_close=[step for step in PREP.close(first=True,generation='2')
                       if not step[0].startswith(('INSERT INTO cp_deny_event ','INSERT INTO cp_commit '))]
        dual=protect('dual',generation='2')
        for i,(sql,values) in enumerate(dual):
            if sql.startswith('INSERT INTO run_deny_event '):
                dual[i]=(sql.replace('(snapshot_revision,','(close_id,commit_id,snapshot_revision,')
                         .replace('VALUES (','VALUES (?,?,',1),('close.p.one','closing.p.one',*values))
        denied('close与HTTP同时占来源',db,pending_close+dual,sqlite3.SQLITE_CONSTRAINT_CHECK)

        # 未提交的通用deny不能作为另一个已提交操作的保护证据。
        db=fresh();steps=protect()
        db.execute('BEGIN IMMEDIATE')
        try:
            for step in steps[:-1]: db.execute(*step)
            check('未提交拒绝不进入启动快照',db.execute('SELECT revision FROM run_deny_snapshot_revision').fetchone()[0],'0'*20)
        finally: db.execute('ROLLBACK')
        denied('没有floor不能提交复用保护',db,protect(raise_deny=False),'protection_incomplete')

        # 共库保留原子缺写保证；只断言本组合实际执行的写集。
        for label, setup, steps in (
            ('裁决', [ADM.namespace()], ADM.creation()),
            ('准备关闭', [], PREP.close(first=True)),
        ):
            for i in range(len(steps)):
                db=fresh()
                for stmt in setup: db.execute(*stmt)
                denied(label+'组合缺写'+str(i),db,steps[:i]+steps[i+1:])
        db=fresh();tx(db,protect())
        denied('保护目标冻结',db,[insert('run_protection_target',protection_id='protection',target_id='late',target_body=BODY)],'target_set_frozen')
        for table in ('run_protection_request','run_protection_target','run_protection_commit',
                      'run_protection_audit','run_protection_outbox','run_deny_event'):
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            denied(table+'不可修改',db,[(f'UPDATE {table} SET {column}={column}',())])
            denied(table+'不可删除',db,[('DELETE FROM '+table,())])
        denied('通用墓碑不可REPLACE',db,[('INSERT OR REPLACE INTO run_deny_event SELECT * FROM run_deny_event',())],'commit_frozen')
        check('BODY只是合成前提',db.execute('SELECT registry_snapshot_body FROM run_protection_request').fetchone()[0]==BODY,True)
        return checks
    finally:
        for db in connections: db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',action='store_true')
    parser.add_argument('--check-report',action='store_true')
    parser.add_argument('--staged',action='store_true')
    args=parser.parse_args()
    if args.staged and not args.check_report: parser.error('--staged需与--check-report共用')
    if args.check_report:
        read=(lambda p:subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        report=json.loads(read(HERE/'layout-report.json'))
        assert set(report['inputs'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS: assert report['inputs'][p.relative_to(ROOT).as_posix()]==hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS),source='staged' if args.staged else 'worktree')))
    else:
        checks=run()
        report=dict(scope='Controller29表组合与共享拒绝账本，非完整执行/P2/P3或运行证明',
                    all_passed=True,cases_passed=len(checks),approved=False,runtime_tests_executed=0,
                    device_tests_executed=0,sqlite_version=sqlite3.sqlite_version,checks=checks,
                    inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if args.report: (HERE/'layout-report.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')},ensure_ascii=False,indent=2))
