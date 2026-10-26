"""运行拒绝快照的持久水位、历史重建及OPEN来源绑定验收。"""
import argparse,hashlib,json,sqlite3
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import run_snapshot_model as M
import check_open_source as T
import check_layout as L
import check_arm_storage as A
N=M.N;P=M.P;I=M.I;HERE=M.HERE;ROOT=T.ROOT
LOCAL=('run_snapshot.sql','run_snapshot_model.py','check_run_snapshot.py','RUN_SNAPSHOT.md')
def inputs():return list(dict.fromkeys(T.inputs()+L.INPUTS+[HERE/n for n in LOCAL]))
def fresh(database='database_1'):
    c=sqlite3.connect(':memory:',isolation_level=None);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');c.executescript(L.build_layout.build().decode())
    c.execute("INSERT INTO controller_scope VALUES(1,'controller',?,'controller-storage/0.1.0-draft.1')",(database,));M.install(c);return c
def integrated_fixture():
    original=A.M.preflight_step
    def preflight(db,pid,rid,targets,ctx):
        # 只为新合成场景选择初始合法身份；尚未登记或持久化任何相关目标。
        for target in targets:
            assert target['controller_scope']['database_instance_id'] in ('controller.db','controller_db')
            target['controller_scope']['database_instance_id']='controller_db'
        ctx['target_manifest_digest']=A.P.digest(A.P.canonical(targets))
        return original(db,pid,rid,targets,ctx)
    with patch.object(A.M,'preflight_step',side_effect=preflight):return T.fixture()
def protection(db,key='one',generation='1',revision='1',snapshot='1',run='run',origin='source_db'):
    steps=L.protect(key,generation=generation,revision=revision,snapshot=snapshot,run=run,origin_database=origin,targets=0)
    if db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='ce_fence'").fetchone():
        # 完整组合中的来源必须同时封存实际签发cut与准备cut；本夹具使用无关联命令的独立run。
        fid=key+'.fence';cut=key+'.preparations';raw=M.M.raw(dict(synthetic='unrelated_run_cut'));digest=M.M.F.digest(dict(synthetic='unrelated_run_cut'))
        issued=db.execute("SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue").fetchone()[0];head=db.execute("SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration").fetchone()[0]
        steps[-1:-1]=[I('ce_fence',fence_id=fid,protection_id=key,close_id=None,issued_cut_revision=issued,cut_body=raw,prepare_cut_id=cut),I('pd_cut',cut_id=cut,kind='run',control_id=None,cancel_id=None,run_id=fid,close_id=None,prepare_head=head,selected_tick=P.u(20),selector_digest=digest,selector_body=raw),I('pd_cut_commit',cut_id=cut,committed_tick=P.u(20),audit_body=raw,outbox_body=raw),I('ce_cut_commit',fence_id=fid,audit_body=raw,outbox_event_id=key+'.cut.event',outbox_body=raw)]
    N.transaction(db,lambda:[db.execute(*s) for s in steps])
def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def new():c=fresh();dbs.append(c);return c
    def fork(c):
        d=sqlite3.connect(':memory:',isolation_level=None);c.backup(d);d.execute('PRAGMA foreign_keys=ON');d.execute('PRAGMA recursive_triggers=ON');dbs.append(d);return d
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,sqlite3.Error,ValidationError) as e:
            messages=[]
            while e:
                assert isinstance(e,(ValueError,RuntimeError,sqlite3.Error,ValidationError)),type(e)
                messages.append(str(e));e=e.__cause__
            if reason:assert any(reason in m for m in messages),(name,messages)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    def state(c):return T.T.snapshot(c)
    class Omit:
        def __init__(self,c,table):self.c=c;self.table=table
        def __getattr__(self,k):return getattr(self.c,k)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' ('):return self.c.execute('SELECT 1 WHERE 0')
            return self.c.execute(sql,args)
    try:
        c=new();empty,valid,writes=M.capture(c,'empty');check('零水位空快照',valid and empty['snapshot_revision']=='0' and empty['entries']==[])
        check('沿用29表加两表',len(state(c))==31)
        denied('事务外读取拒绝',lambda:M.read(c,'empty'),'run_snapshot_transaction_required')
        protection(c);first,_,_=M.capture(c,'first');check('提交来源进入快照',first['entries'][0]['selector']['deny_through_generation']=='1' and first['snapshot_revision']=='1')
        check('旧快照历史稳定且不再当前',N.transaction(c,lambda:(M.read(c,'empty'),M.current(c,'empty')))==(empty,False))
        protection(c,'second',generation='9',revision='2',snapshot='2');second,_,_=M.capture(c,'second')
        check('同RUN只保留最新floor但水位增长',len(second['entries'])==1 and second['entries'][0]['deny_revision']=='2' and second['entries'][0]['selector']['deny_through_generation']=='9')
        check('旧水位按当时账本重建',N.transaction(c,lambda:M.read(c,'first'))==first)
        before=state(c);check('重入旧ID不刷新',M.capture(c,'first')==(first,False,[]) and state(c)==before)
        protection(c,'third',generation='10000000000000000001',revision='1',snapshot='3',run='aaa');third,_,_=M.capture(c,'third')
        check('大整数不经浮点',third['entries'][0]['selector']['deny_through_generation']=='10000000000000000001')
        check('完整排序不按插入顺序',[e['selector']['run_id'] for e in third['entries']]==['aaa','run'])
        protection(c,'other.database',revision='1',snapshot='4',run='run',origin='other_db');fourth,_,_=M.capture(c,'fourth')
        check('同run不同来源不合并',len(fourth['entries'])==3 and fourth['entries'][0]['selector']['origin_scope']['database_instance_id']=='other_db')
        denied('未来水位不可读',lambda:N.transaction(c,lambda:M.materialize(c,'5')),'run_snapshot_future')
        c=new();steps=L.protect(targets=0,origin_database='source_db');c.execute('BEGIN IMMEDIATE')
        for step in steps[:-1]:c.execute(*step)
        check('未封存来源不进入水位或正文',M.head(c)=='0' and M.materialize(c,'0')['entries']==[]);c.rollback()
        seed=new();protection(seed)
        for index in range(2):
            c=fork(seed);before=state(c);denied('逐写故障:'+str(index),lambda:M.capture(c,'cut',fail_after=index));check('逐写无残留:'+str(index),state(c)==before)
        for table in ('rs_snapshot','rs_commit'):
            c=fork(seed);before=state(c);denied('缺写:'+table,lambda:M.capture(Omit(c,table),'cut'));check('缺写无残留:'+table,state(c)==before)
        c=fork(seed);v=M.capture(c,'cut')[0];row=M.M.E.one(c,'SELECT * FROM rs_snapshot');seal=M.M.E.one(c,'SELECT * FROM rs_commit')
        for table,record in (('rs_snapshot',row),('rs_commit',seal)):
            d=fork(seed);denied('原始事务单边拒绝:'+table,lambda:N.transaction(d,lambda:d.execute(*I(table,**record))),'FOREIGN KEY constraint failed' if table=='rs_snapshot' else 'run_snapshot_seal')
        d=fork(seed);bad=dict(row,entry_count=0);denied('同水位漏成员不能封存',lambda:N.transaction(d,lambda:d.execute(*I('rs_snapshot',**bad))),'run_snapshot_frontier')
        d=fork(seed);bad=dict(row,snapshot_revision=P.u(0));denied('旧水位不能作为新捕获',lambda:N.transaction(d,lambda:d.execute(*I('rs_snapshot',**bad))),'run_snapshot_frontier')
        d=fork(seed)
        def change_between():
            d.execute(*I('rs_snapshot',**row))
            for step in L.protect('advanced',generation='2',revision='2',snapshot='2',targets=0,origin_database='source_db'):d.execute(*step)
            d.execute(*I('rs_commit',**seal))
        before=state(d);denied('写入与seal之间水位推进拒绝',lambda:N.transaction(d,change_between),'run_snapshot_seal');check('水位与快照一起回滚',state(d)==before)
        class CommitFault:
            def __init__(self,c,committed):self.c=c;self.committed=committed
            def __getattr__(self,k):return getattr(self.c,k)
            def commit(self):
                if self.committed:self.c.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation')
        for committed in (False,True):
            d=fork(seed);before=state(d);denied('提交观察故障:'+str(committed),lambda:M.capture(CommitFault(d,committed),'uncertain'))
            if committed:
                after=state(d);check('观察丢失后查原不重写',M.capture(d,'uncertain')[2]==[] and state(d)==after)
            else:check('提交前失败回滚',before==state(d))
        for table in ('rs_snapshot','rs_commit'):
            for action in ('UPDATE '+table+' SET snapshot_id=snapshot_id','DELETE FROM '+table):denied('原件不可变:'+action,lambda:c.execute(action),'immutable_run_snapshot')
        # 同数量错误正文不靠计数冒充；读原件必须重新投影历史账本。
        d=fork(seed);wrong=json.loads(row['body']);wrong['entries'][0]['selector']['run_id']='wrong';wrong=M.M.sealed(wrong,'snapshot_digest');raw=M.M.raw(wrong)
        N.transaction(d,lambda:(d.execute(*I('rs_snapshot',**dict(row,body=raw,snapshot_digest=wrong['snapshot_digest']))),d.execute(*I('rs_commit',snapshot_id='cut',audit_body=raw))))
        denied('重算摘要也不能伪造成员',lambda:N.transaction(d,lambda:M.read(d,'cut')),'run_snapshot_source')
        capacity=new()
        def fill():
            for n in range(4096):
                for step in L.protect('capacity.'+str(n),snapshot=str(n+1),run='run_'+str(n).zfill(4),origin_database='source_db',targets=0):capacity.execute(*step)
        N.transaction(capacity,fill);maximum,_,_=M.capture(capacity,'maximum');check('4096成员完整捕获',len(maximum['entries'])==4096)
        protection(capacity,'capacity.extra',snapshot='4097',run='run_extra');before=state(capacity)
        denied('4097成员拒绝而非截断',lambda:M.capture(capacity,'overflow'),'run_snapshot_capacity');check('容量拒绝无快照残留',state(capacity)==before)
        legacy=fresh('database.1');dbs.append(legacy);denied('非法初始scope不隐式归一化',lambda:M.capture(legacy,'invalid'))
        db,others,eid,cid,sid,selections=integrated_fixture();dbs.extend(others);M.install(db);protection(db,'source.protect',run='unrelated_run')
        original_counts=[db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('ci_issue','go_plan')]
        body,_,_=M.capture(db,'run.full');links=dict(T.LINKS,run_snapshot_ref='run.full')
        M.O.recover(db,'full.recovery','full.snapshot',eid,links,'22','100',T.E.ref('provider.full'),selections);T.fence(db,cid,sid)
        result=N.transaction(db,lambda:M.for_open(db,'full.recovery','full.fence','27'));check('271表真实来源接入OPEN前态',len(state(db))==271 and result['run_deny_snapshot']==body and len(body['entries'])==1)
        protection(db,'next.protect',generation='2',revision='2',snapshot='2',run='unrelated_run')
        denied('同数量新floor阻止旧OPEN来源',lambda:N.transaction(db,lambda:M.for_open(db,'full.recovery','full.fence','28')),'run_snapshot_stale')
        check('旧来源历史仍可读',N.transaction(db,lambda:M.read(db,'run.full'))==body)
        check('未新增OPEN与最终许可',original_counts==[db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('ci_issue','go_plan')] and not db.execute("SELECT 1 FROM go_plan WHERE snapshot_id='full.snapshot'").fetchone())
        for d in dbs:assert not d.in_transaction and not d.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for d in dbs:d.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'run-snapshot-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),integrated_controller_tables=271,run_snapshot_storage_verified=True,command_snapshot_storage_verified=False,full_open_verified=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.M.raw(v))
        print(json.dumps({k:x for k,x in v.items() if k not in ('checks','inputs')}))
