"""命令快照封存与历史水位验收；完整运行域接线保持未完成。"""
import argparse,copy,hashlib,json,sqlite3,tempfile
from pathlib import Path
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import command_snapshot_model as M
import check_cancel_source as T
import check_run_snapshot as U
C=M.C;D=M.D;N=M.N;P=M.P;I=M.I;HERE=M.HERE;ROOT=T.ROOT
LOCAL=('command_snapshot.sql','command_snapshot_model.py','check_command_snapshot.py','COMMAND_SNAPSHOT.md')
def inputs():return list(dict.fromkeys(T.inputs()+U.inputs()+[HERE/n for n in LOCAL]))
def fixture(level='ordinary'):
    db,context=T.fixture(level);M.install(db);return db,context

def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def new(level='ordinary'):
        db,context=fixture(level);dbs.append(db);return db,context
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,sqlite3.Error,ValidationError) as e:
            messages=[]
            while e:
                assert isinstance(e,(ValueError,RuntimeError,sqlite3.Error,ValidationError)),type(e)
                messages.append(str(e));e=e.__cause__
            if reason:assert any(reason in text for text in messages),(name,messages)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    def state(db):return T.X.F.snapshot(db)
    def get(db,sid):return N.transaction(db,lambda:M.read(db,sid))
    class Omit:
        def __init__(self,db,table):self.db=db;self.table=table
        def __getattr__(self,key):return getattr(self.db,key)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' ('):return self.db.execute('SELECT 1 WHERE 0')
            return self.db.execute(sql,args)
    class CommitFault:
        def __init__(self,db,committed):self.db=db;self.committed=committed
        def __getattr__(self,key):return getattr(self.db,key)
        def commit(self):
            if self.committed:self.db.commit()
            raise sqlite3.OperationalError('synthetic_commit_observation')
    try:
        d,_=new('dispatched');empty,valid,_=M.capture(d,'empty','dev_1')
        check('零水位无取消可封存',valid and empty['entries']==[] and empty['snapshot_revision']=='0')
        pending,_=new('accepted');before=state(pending)
        denied('已受理未完成cut不得封存为空',lambda:M.capture(pending,'pending','dev_1'),'command_deny_cut_pending')
        check('pending拒绝无残留',state(pending)==before)
        seed,ctx=new();ordinary,valid,writes=M.capture(seed,'ordinary.snapshot','dev_1')
        check('123表非空原件持久封存',len(state(seed))==123 and valid and ordinary['entries'][0]['cut_ref']==C.reference('ordinary',ctx['cut']['cut_digest']))
        check('两表原子写集',writes==['ds_snapshot','ds_commit'])
        denied('事务外不查原',lambda:M.read(seed,'ordinary.snapshot'),'command_snapshot_transaction_required')
        check('同ID查原不重写',M.capture(seed,'ordinary.snapshot','dev_1')==(ordinary,True,[]))
        denied('同ID不能切换设备',lambda:M.capture(seed,'ordinary.snapshot','another_device'),'command_snapshot_replay_conflict')
        other,valid,_=M.capture(seed,'other.snapshot','another_device');check('另设备独立零水位',valid and other['entries']==[])
        d,_=new('sent');first,_,_=M.capture(d,'first','dev_1');all_cut,_=C.capture(d,'cancel','all','all');last,_,_=M.capture(d,'last','dev_1')
        check('同数量阶段推进水位失效',len(first['entries'])==len(last['entries'])==1 and first['snapshot_revision']=='2' and last['snapshot_revision']=='3' and not N.transaction(d,lambda:M.current(d,'first')))
        check('新水位使用完整all引用',last['entries'][0]['cut_ref']==C.reference('all',all_cut['cut_digest']) and last['entries'][0]['stage']=='all')
        before=state(d);check('历史查原保持ordinary',get(d,'first')==first and M.capture(d,'first','dev_1')==(first,False,[]) and state(d)==before)
        for index in range(2):
            x,_=new();before=state(x);denied('逐写故障:'+str(index),lambda:M.capture(x,'fault','dev_1',index),'injected');check('逐写回滚:'+str(index),state(x)==before)
        for table in ('ds_snapshot','ds_commit'):
            x,_=new();before=state(x);denied('缺写:'+table,lambda:M.capture(Omit(x,table),'missing','dev_1'));check('缺写回滚:'+table,state(x)==before)
        row=C.one(seed,'SELECT * FROM ds_snapshot WHERE snapshot_id=\'ordinary.snapshot\'');seal=C.one(seed,'SELECT * FROM ds_commit WHERE snapshot_id=\'ordinary.snapshot\'')
        for table,record in (('ds_snapshot',row),('ds_commit',seal)):
            x,_=new();denied('原始SQL不能单边提交:'+table,lambda:N.transaction(x,lambda:x.execute(*I(table,**record))))
            for action in ('UPDATE '+table+' SET snapshot_id=snapshot_id','DELETE FROM '+table):denied('不可变:'+action,lambda action=action:seed.execute(action),'immutable_command_snapshot')
            denied('REPLACE不能覆盖:'+table,lambda table=table,record=record:seed.execute(*((lambda s:(s[0].replace('INSERT INTO','INSERT OR REPLACE INTO'),s[1]))(I(table,**record)))),'immutable_command_snapshot')
        for label,changes in [('漏成员',dict(entry_count=0)),('旧水位',dict(snapshot_revision=P.u(0))),('超容量',dict(entry_count=4097)),('空正文',dict(body=b'')),('正文过大',dict(body=b'x'*16777217))]:
            x,_=new();denied('SQL新捕获拒绝:'+label,lambda changes=changes:N.transaction(x,lambda:x.execute(*I('ds_snapshot',**dict(row,**changes)))))
        denied('SQL拒绝pending',lambda:N.transaction(pending,lambda:pending.execute(*I('ds_snapshot',**dict(row,snapshot_revision=P.u(1))))),'command_snapshot_frontier')
        x,_=new('sent');before=state(x)
        def advance_between():
            x.execute(*I('ds_snapshot',**row))
            # 同事务模拟cut封存推进；使用实际写集而非篡改水位。
            for sql,args in all_steps:x.execute(sql,args)
            x.execute(*I('ds_commit',**seal))
        # 从未提交写入轨迹取同一候选的完整all写集，避免复制已封存表行绕过守卫。
        recorder,_=new('sent');all_steps=[]
        class Record:
            def __getattr__(self,key):return getattr(recorder,key)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '):all_steps.append((sql,args))
                return recorder.execute(sql,args)
        C.capture(Record(),'cancel','all','all')
        denied('插入到seal间推进拒绝',lambda:N.transaction(x,advance_between),'command_snapshot_seal');check('中途推进整事务回滚',state(x)==before)
        for committed in (False,True):
            x,_=new();before=state(x);denied('提交观察失效:'+str(committed),lambda:M.capture(CommitFault(x,committed),'uncertain','dev_1'))
            if committed:
                after=state(x);check('观察丢失后按同ID查原',M.capture(x,'uncertain','dev_1')[2]==[] and state(x)==after)
            else:check('提交前异常全回滚',state(x)==before)
        for label,change in [('成员',lambda b:b['entries'][0].update(parent_command_id='wrong')),('切点摘要',lambda b:b['entries'][0]['cut_ref'].update(digest=C.digest('wrong'))),('scope',lambda b:b['scope'].update(database_instance_id='wrong'))]:
            x,_=new();body=json.loads(row['body']);change(body);body=C.M.sealed(body,'snapshot_digest');raw=C.raw(body)
            N.transaction(x,lambda:(x.execute(*I('ds_snapshot',**dict(row,body=raw,snapshot_digest=body['snapshot_digest']))),x.execute(*I('ds_commit',snapshot_id=row['snapshot_id'],audit_body=raw))))
            denied('重算摘要不能伪造:'+label,lambda:get(x,row['snapshot_id']),'command_snapshot_source')
        # 这里只验证组合函数的精确绑定，不能替代真实恢复链正例。
        base=dict(binding=dict(scope=ordinary['scope'],device_id='dev_1'),originals=dict(resource=dict(command_snapshot_id='ordinary.snapshot')))
        with patch.object(M.R,'for_open',side_effect=lambda *a:copy.deepcopy(base)):
            result=N.transaction(seed,lambda:M.for_open(seed,'r','f','27'));check('局部OPEN来源读取指定快照',result['command_deny_snapshot']==ordinary)
            base['binding']['device_id']='another_device';denied('OPEN错设备拒绝',lambda:N.transaction(seed,lambda:M.for_open(seed,'r','f','27')),'command_snapshot_binding')
            base['binding']['device_id']='dev_1';base['binding']['scope']=dict(ordinary['scope'],database_instance_id='other');denied('OPEN错scope拒绝',lambda:N.transaction(seed,lambda:M.for_open(seed,'r','f','27')),'command_snapshot_binding')
            base['binding']['scope']=ordinary['scope'];base['originals']['resource']['command_snapshot_id']='first';denied('OPEN旧水位拒绝',lambda:N.transaction(d,lambda:M.for_open(d,'r','f','27')),'command_snapshot_stale')
        with tempfile.TemporaryDirectory(prefix='leafseamer-command-snapshot-') as tmp:
            for mode in ('DELETE','WAL'):
                path=Path(tmp)/(mode+'.sqlite');disk=sqlite3.connect(path,isolation_level=None,timeout=0);pending.backup(disk)
                peer=sqlite3.connect(path,isolation_level=None,timeout=0)
                try:
                    for conn in (disk,peer):conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA recursive_triggers=ON')
                    assert disk.execute('PRAGMA journal_mode='+mode).fetchone()[0].upper()==mode
                    C.capture(disk,'cancel','ordinary','ordinary');original,_,_=M.capture(disk,'disk','dev_1')
                    disk.execute('BEGIN IMMEDIATE');denied(mode+'并发writer排他',lambda:M.capture(peer,'contended','dev_1'),'database is locked');disk.rollback()
                    check(mode+'第二连接可查持久原件',get(peer,'disk')==original)
                    if mode=='WAL':
                        peer.execute('BEGIN');check('WAL旧事务原水位有效',M.current(peer,'disk'))
                        C.capture(disk,'cancel','all','all');check('WAL旧读视图只证明旧时点',M.current(peer,'disk'));peer.rollback()
                        check('WAL新写事务拒绝旧水位',not N.transaction(peer,lambda:M.current(peer,'disk')))
                finally:peer.close();disk.close()
                reopened=sqlite3.connect(path,isolation_level=None)
                try:check(mode+'关闭重开保留历史',get(reopened,'disk')==original)
                finally:reopened.close()
        full,others,*_=U.integrated_fixture();dbs.extend(others);D.install(full);C.install(full);M.R.install(full);M.install(full)
        check('完整布局安装275表及准备登记守卫',len(state(full))==275 and full.execute("SELECT 1 FROM sqlite_schema WHERE name='cs_socket_prepare_guard'").fetchone() is not None)
        denied('旧恢复标识不静默改写',lambda:M.capture(full,'legacy','dev.1'))
        denied('SQL准备后不得补socket',lambda:full.execute(*I('cs_socket',exit_id='exit_dev_1',socket_instance_id='new_socket',registration_digest=C.digest('test'),body=b'{}',audit_body=b'{}')),'cancel_socket_registered_too_late')
        for db in dbs:assert not db.in_transaction and not db.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for db in dbs:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'command-snapshot-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),command_snapshot_storage_verified=True,local_open_binding_verified=True,integrated_controller_tables=275,integrated_nonempty_open_verified=False,full_open_verified=False,actual_process_crash_tested=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(C.raw(v))
        print(json.dumps({k:v for k,v in v.items() if k not in ('checks','inputs')}))
