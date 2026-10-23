"""控制受理与转交的内存SQLite约束检查；不是服务实现或磁盘耐久测试。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_control_storage as G

HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(G.SOURCES+[HERE/n for n in ('CONTROL_STORAGE.md','CONTROL_AUTHORITY.md',
 'control-authority.schema.json','controller-control.sql','check_control_storage.py')]))
BODY=b'{"fixture":true}';DIGEST='sha256:'+'a'*64
def u(n):
    assert type(n) is int and 0<=n<10**20
    return str(n).zfill(20)
def p(prefix,name):return {prefix+'_'+k:v for k,v in zip(('issuer','epoch','id'),('issuer','epoch',name) if name else (None,None,None))}
def row(table,**values):return table,values
def execute(db,step):
    table,v=step;db.execute('INSERT INTO '+table+'('+','.join(v)+') VALUES('+','.join('?' for _ in v)+')',tuple(v.values()))
def tx(db,steps,fault=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        for n,step in enumerate(steps):
            execute(db,step)
            if fault==n:raise RuntimeError('injected')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
def snapshot(db):
    names=[x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {t:sorted(db.execute('SELECT * FROM '+t).fetchall(),key=repr) for t in names}
def one(db,sql,args=()):
    cur=db.execute(sql,args);value=cur.fetchone()
    return dict(zip([x[0] for x in cur.description],value)) if value else None
def current(db):return one(db,"SELECT * FROM ct_current_state WHERE device_id='device'")
def change(db,cid,kind,op=None,offer=None,actor='alice',now=10,domain='domain',descriptor='descriptor'):
    previous=one(db,"SELECT * FROM ct_current_change WHERE device_id='device'")
    stateful=kind in ('bootstrap','accept','acquire','release','unknown','reject','restart')
    requested=kind in ('offer','accept','acquire','release','cancel')
    return [row('ct_change',change_id=cid,scope_id=1,device_id='device',sequence=u(int(previous['sequence'])+1 if previous else 1),
        previous_id=previous['change_id'] if previous else None,kind=kind,state_id=cid if stateful else None,
        operation_id=op,offer_id=offer,request_id=cid if requested else None,clock_domain=domain,descriptor=descriptor,now_tick=u(now))]
def finish(steps,actor='alice'):
    c=steps[0][1];cid=c['change_id']
    if c['request_id']:
        result=next(v for t,v in steps if t==('ct_operation_event' if c['kind'] in ('acquire','release','accept') else 'ct_offer_event'))
        steps+=[row('ct_request',change_id=cid,**p('actor',actor),request_epoch='request.epoch',
         api_operation={'offer':'offerTransfer','accept':'acceptTransfer','acquire':'acquireControl','release':'releaseControl','cancel':'cancelTransfer'}[c['kind']],
         idempotency_key=cid,request_digest=DIGEST,request_body=BODY,
         result_kind='control_operation' if 'operation_id' in result else 'transfer_offer',
         initial_result_id=result.get('operation_id',result.get('offer_id')),initial_result_revision=result['revision'],initial_result_digest=result['result_digest'])]
    return steps+[row('ct_audit',change_id=cid,body=BODY),row('ct_outbox',change_id=cid,event_id='event.'+cid,body=BODY),row('ct_commit',change_id=cid)]
def state(old,cid,**changes):
    value={k:v for k,v in old.items() if k!='device_id'};value.update(change_id=cid,record_revision=u(int(old['record_revision'])+1));value.update(changes)
    return row('ct_state',**value)
def bootstrap(db,holder='alice',reserved=3):
    return finish(change(db,'base','bootstrap')+[row('ct_state',change_id='base',record_revision=u(1),control_epoch='control.epoch',
     effective_version=u(2),reserved_version=u(reserved),mode='manual' if holder else 'automatic',**p('holder',holder),pending_operation_id=None,
     gate_state='protected',record_digest=DIGEST,record_body=BODY)])
def offer(db,cid='offer',target='bob'):
    s=current(db)
    return finish(change(db,cid,'offer',offer=cid)+[row('ct_offer',offer_id=cid,change_id=cid,**p('sender','alice'),**p('target',target),
     expected_state_id=s['change_id'],clock_domain='domain',descriptor='descriptor',issued_tick=u(10),expires_tick=u(20),reason='交班'),
     row('ct_offer_event',change_id=cid,offer_id=cid,revision=u(1),state='offered',accepted_operation_id=None,result_digest=DIGEST,result_body=BODY)])
def start(db,cid='accept',kind='accept',actor='bob',oid='op',offer_id='offer',now=15,domain='domain'):
    s=current(db);target=None if kind=='release' else actor
    steps=change(db,cid,kind,op=oid,offer=offer_id if kind=='accept' else None,now=now,domain=domain)
    steps+=[row('ct_operation',operation_id=oid,change_id=cid,kind='transfer' if kind=='accept' else kind,
        **p('requester',actor),**p('target',target),expected_state_id=s['change_id'],target_version=u(int(s['reserved_version'])+1),
        offer_id=offer_id if kind=='accept' else None,force=int(kind=='acquire'),reason='人工操作'),
        row('ct_attempt',attempt_id=oid+'.attempt.1',operation_id=oid,change_id=cid,ordinal=u(1)),
        row('ct_operation_event',change_id=cid,operation_id=oid,revision=u(1),state='pending',attempt_id=oid+'.attempt.1',failure_code=None,result_digest=DIGEST,result_body=BODY),
        state(s,cid,reserved_version=u(int(s['reserved_version'])+1),pending_operation_id=oid,gate_state='fencing')]
    if kind=='accept':steps+=[row('ct_offer_event',change_id=cid,offer_id=offer_id,revision=u(2),state='accepted',accepted_operation_id=oid,result_digest=DIGEST,result_body=BODY)]
    return finish(steps,actor)
def settle(db,kind='unknown',cid=None,oid='op'):
    cid=cid or kind;s=current(db);e=one(db,'SELECT * FROM ct_current_operation WHERE operation_id=?',(oid,))
    steps=change(db,cid,kind,op=oid)
    aid=e['attempt_id']
    if kind=='retry':
        a=one(db,'SELECT * FROM ct_attempt WHERE attempt_id=?',(aid,));aid=oid+'.attempt.'+str(int(a['ordinal'])+1)
        steps+=[row('ct_attempt',attempt_id=aid,operation_id=oid,change_id=cid,ordinal=u(int(a['ordinal'])+1))]
    steps+=[row('ct_operation_event',change_id=cid,operation_id=oid,revision=u(int(e['revision'])+1),state='rejected' if kind=='reject' else 'indeterminate',
        attempt_id=aid,failure_code='target_authorization_revoked' if kind=='reject' else 'barrier_unconfirmed',result_digest=DIGEST,result_body=BODY)]
    if kind!='retry':steps+=[state(s,cid,pending_operation_id=None if kind=='reject' else oid,gate_state='protected')]
    return finish(steps)
def close_offer(db,kind='cancel',cid=None,actor='alice',now=20,domain='domain'):
    cid=cid or kind
    return finish(change(db,cid,kind,offer='offer',now=now,domain=domain)+[row('ct_offer_event',change_id=cid,offer_id='offer',revision=u(2),
     state='cancelled' if kind=='cancel' else 'expired',accepted_operation_id=None,result_digest=DIGEST,result_body=BODY)],actor)
def restart(db):return finish(change(db,'restart','restart')+[state(current(db),'restart',gate_state='protected')])
def mutate(steps,table,**changes):
    steps=copy.deepcopy(steps);next(v for t,v in steps if t==table).update(changes);return steps

def run():
    assert (HERE/'controller-control.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        try:json.dumps([actual,expected])
        except TypeError:actual,expected=True,True
        checks.append(dict(name=name,expected=expected,observed=actual))
    def fresh(stage='base',holder='alice',reserved=3):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        if stage=='empty':return db
        tx(db,bootstrap(db,holder,reserved))
        if stage=='base':return db
        tx(db,offer(db))
        if stage=='offered':return db
        tx(db,start(db))
        if stage=='pending':return db
        tx(db,settle(db))
        if stage=='unknown':return db
        tx(db,settle(db,'reject'));return db
    def denied(name,db,steps,error=None):
        before=snapshot(db)
        try:tx(db,steps)
        except sqlite3.IntegrityError as exc:check(name,str(exc) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 必须拒绝')
        check(name+'全库回滚',snapshot(db)==before)
    try:
        db=fresh();check('148表共用单一scope',len(snapshot(db)),148)
        old=current(db);tx(db,offer(db));check('邀请不改控制记录',current(db),old)
        tx(db,start(db));check('接受预留新版本且旧持有人不变',tuple(current(db)[k] for k in ('effective_version','reserved_version','holder_id','pending_operation_id','gate_state')),(u(2),u(4),'alice','op','fencing'))
        check('邀请接受绑定操作',db.execute("SELECT state,accepted_operation_id FROM ct_current_offer").fetchone(),('accepted','op'))
        receipt=db.execute('SELECT * FROM ct_request WHERE change_id=\'accept\'').fetchone()
        tx(db,settle(db));tx(db,settle(db,'retry'))
        check('未知恢复保持原预留版本',current(db)['reserved_version'],u(4))
        check('重取证保留未知状态并换唯一尝试',db.execute('SELECT state,attempt_id FROM ct_current_operation').fetchone(),('indeterminate','op.attempt.2'))
        tx(db,settle(db,'reject'));check('拒绝清槽不退款不换持有人',tuple(current(db)[k] for k in ('reserved_version','holder_id','pending_operation_id','gate_state')),(u(4),'alice',None,'protected'))
        tx(db,start(db,cid='take2',kind='acquire',oid='op2',actor='charlie'))
        check('下一操作不复用旧版本',current(db)['reserved_version'],u(5))
        check('原回执在后续修订中不变',db.execute('SELECT * FROM ct_request WHERE change_id=\'accept\'').fetchone(),receipt)
        check('全部控制历史保留',db.execute('SELECT count(*) FROM ct_state').fetchone()[0],5)
        for label,stage,maker in [('初始化','empty',bootstrap),('邀请','base',offer),('接受','offered',start),
             ('接管','base',lambda d:start(d,kind='acquire')),('释放','base',lambda d:start(d,kind='release',actor='alice')),
             ('未知','pending',settle),('拒绝','unknown',lambda d:settle(d,'reject')),('重取证','unknown',lambda d:settle(d,'retry')),
             ('取消邀请','offered',close_offer),('过期','offered',lambda d:close_offer(d,'expire')),('重启','pending',restart)]:
            d=fresh(stage);steps=maker(d);tx(d,steps);check(label+'完整写集可提交',True)
            for n in range(len(steps)):
                d=fresh(stage);steps=maker(d);denied(label+'缺写'+str(n),d,steps[:n]+steps[n+1:])
                d=fresh(stage);steps=maker(d);before=snapshot(d)
                try:tx(d,steps,n)
                except RuntimeError:check(label+'写后异常'+str(n),snapshot(d)==before)
                else:raise AssertionError('没有注入异常')
        for table,field,value,label in [('ct_request','actor_issuer','other','同名跨issuer接受'),('ct_request','actor_epoch','new','同名跨issuer代次'),
          ('ct_request','initial_result_id','other','初始结果身份'),('ct_request','initial_result_revision',u(2),'初始结果修订'),
          ('ct_request','initial_result_digest','wrong','初始结果摘要'),('ct_request','api_operation','acquireControl','操作命名空间'),
          ('ct_state','reserved_version',u(3),'目标版本退款'),('ct_state','reserved_version',u(5),'跳号预留'),
          ('ct_state','holder_id','bob','屏障前更换持有人'),('ct_state','control_epoch','new','普通操作偷换epoch'),
          ('ct_state','pending_operation_id',None,'缺pending归属'),('ct_state','gate_state','protected','受理未进入fencing'),
          ('ct_state','effective_version',u(4),'屏障前变effective'),('ct_offer_event','accepted_operation_id',None,'邀请接受无操作'),
          ('ct_offer_event','accepted_operation_id','other','邀请接受换操作'),('ct_operation','target_id','mallory','操作目标与接受者不同'),
          ('ct_operation','expected_state_id','missing','期望历史不存在'),('ct_change','device_id','other','跨设备邀请'),
          ('ct_change','now_tick',u(20),'期限等号'),('ct_change','now_tick',u(9),'期限之前'),
          ('ct_change','clock_domain','new','换域接受'),('ct_change','descriptor','new','换descriptor接受')]:
            d=fresh('offered');denied(label,d,mutate(start(d),table,**{field:value}))
        d=fresh('pending');denied('未决阻止紧急接管',d,start(d,'emergency','acquire',oid='op2',actor='charlie'))
        d=fresh('unknown');denied('未知仍占未决槽',d,start(d,'take','acquire',oid='op2',actor='charlie'))
        d=fresh('rejected');denied('拒绝终态不可恢复',d,settle(d,'retry'))
        d=fresh('pending');denied('pending不能重建尝试',d,settle(d,'retry'))
        d=fresh('unknown');steps=settle(d,'retry');denied('重用尝试身份',d,mutate(steps,'ct_attempt',attempt_id='op.attempt.1'))
        d=fresh('offered');denied('邀请不能提前过期',d,close_offer(d,'expire',now=19))
        d=fresh('offered');tx(d,close_offer(d,'expire',now=1,domain='new'));check('换域终结邀请不释放持有人',current(d)['holder_id'],'alice')
        d=fresh('offered');denied('非发起人取消',d,close_offer(d,actor='bob'))
        d=fresh('offered');tx(d,close_offer(d));denied('取消邀请不复活',d,start(d))
        d=fresh('pending');denied('accepted邀请不再过期',d,close_offer(d,'expire',now=30))
        d=fresh('offered');tx(d,start(d));denied('另一请求键不能再接受',d,start(d,'accept.again',oid='op2'))
        d=fresh('offered');left=start(d);right=start(d,'competitor',oid='op2');tx(d,left)
        denied('同前态双接受封存只一方获胜',d,right,'UNIQUE constraint failed: ct_change.device_id, ct_change.sequence')
        d=fresh('offered');left=start(d);right=start(d,'emergency','acquire',oid='op2',actor='charlie');tx(d,right)
        denied('紧急接管先封存则旧接受CAS失败',d,left,'UNIQUE constraint failed: ct_change.device_id, ct_change.sequence')
        d=fresh('offered');steps=start(d)
        # 新尝试必须属于同一操作；即使同时改引用也不能跨操作借用。
        bad=mutate(steps,'ct_attempt',operation_id='other')
        denied('尝试与操作归属不可拆开',d,bad)
        d=fresh('offered');tx(d,start(d));before=snapshot(d)
        try:execute(d,row('ct_offer',offer_id='late',change_id='accept',**p('sender','alice'),**p('target','bob'),
            expected_state_id='base',clock_domain='domain',descriptor='descriptor',issued_tick=u(10),expires_tick=u(20),reason='追加'))
        except sqlite3.IntegrityError as exc:check('封存后不增补成员',str(exc),'control_already_sealed')
        else:raise AssertionError('封存后成员可追加')
        check('封存后追加无影响',snapshot(d)==before)
        d=fresh('offered');before=current(d);tx(d,restart(d));tx(d,start(d));check('同版本普通重启不改变邀请预期',current(d)['effective_version'],before['effective_version'])
        d=fresh('base',holder=None);tx(d,start(d,kind='acquire'));check('automatic可受理人工接管',current(d)['pending_operation_id'],'op')
        d=fresh();denied('已有持有人禁止普通抢占',d,mutate(start(d,kind='acquire'),'ct_operation',force=0))
        d=fresh();denied('原持有人不重复接管自己',d,start(d,kind='acquire',actor='alice'))
        d=fresh();denied('非持有人释放',d,start(d,kind='release',actor='bob'))
        d=fresh();tx(d,start(d,kind='release',actor='alice'));check('释放受理仍保留旧holder',current(d)['holder_id'],'alice')
        for value in (9999999999,2**63-1,10**20-2):
            d=fresh(reserved=value);tx(d,start(d,kind='acquire'));check('真实存储U20后继'+str(value),current(d)['reserved_version'],u(value+1))
        d=fresh(reserved=10**20-1);steps=start(fresh(),kind='acquire');denied('U20耗尽拒绝回绕',d,steps)
        for value in ('1','0000000000000000000x','100000000000000000000'):
            d=fresh();denied('计数词法拒绝'+value,d,mutate(start(d,kind='acquire'),'ct_state',reserved_version=value))
        d=fresh('offered');steps=start(d);tx(d,steps)
        d.execute('BEGIN IMMEDIATE')
        try:
            execute(d,steps[-1]);raise AssertionError('重复封存应拒绝')
        except sqlite3.IntegrityError:d.execute('ROLLBACK');check('重复封存拒绝',True)
        for t in G.TABLES:
            for verb in ('UPDATE','DELETE'):
                before=snapshot(d)
                try:d.execute(('UPDATE '+t+' SET change_id=change_id') if verb=='UPDATE' else 'DELETE FROM '+t)
                except sqlite3.IntegrityError as exc:check(t+verb,str(exc),'immutable_control_history')
                else:raise AssertionError(t+'历史可以篡改')
                check(t+verb+'未变化',snapshot(d)==before)
        # 相同key不同内容不能取得第二裁决；同键查原必须由已鉴权的服务路径执行。
        d=fresh('offered');tx(d,close_offer(d));steps=offer(d,'offer2')
        denied('同RequestKey不同摘要仍冲突',d,mutate(steps,'ct_request',idempotency_key='offer',request_digest='different'))
        d=fresh();before=snapshot(d);steps=offer(d);d.execute('BEGIN IMMEDIATE')
        for step in steps[:-1]:execute(d,step)
        check('未封存邀请不进入当前视图',d.execute('SELECT count(*) FROM ct_current_offer').fetchone()[0],0)
        try:d.execute('COMMIT')
        except sqlite3.IntegrityError:d.execute('ROLLBACK');check('漏封存COMMIT拒绝并回滚',snapshot(d)==before)
        else:raise AssertionError('漏封存竟能提交')
        d=fresh('pending');steps=settle(d);denied('禁止用占位证据标effective',d,mutate(steps,'ct_operation_event',state='effective'))
        d=fresh();denied('没有开放证明不能标ready',d,mutate(restart(d),'ct_state',gate_state='ready'))
        check('合成BODY可通过仅为外部取证边界',True)
        for db in connections:
            assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('全部内存库完整性',True)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    if args.staged and not args.check_report:parser.error('--staged需配合--check-report')
    if args.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        data=json.loads(read(HERE/'control-storage-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='148表控制受理转交候选',
         runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
         sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if args.report:(HERE/'control-storage-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
