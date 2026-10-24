"""242表初始化、提交观察及真实SQLite锁竞争；不声称最终签发正向链通过。"""
import argparse,copy,hashlib,json,sqlite3,tempfile
from pathlib import Path
from jsonschema.exceptions import ValidationError
import check_typed_command_view as V
import check_final_admission as T
import final_admission_storage_model as M
G=M.G;F=M.F;HERE=G.HERE;ROOT=HERE.parents[2];clone=copy.deepcopy
def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def rejected(n,db,fn,reason=None):
        before=V.SC.snapshot(db)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,sqlite3.OperationalError,ValidationError) as error:
            if reason:assert reason in str(error),(n,str(error))
            check(n,V.SC.snapshot(db)==before and not db.in_transaction);return
        raise AssertionError(n)
    def execute(db,steps):
        db.execute('BEGIN IMMEDIATE')
        try:
            for sql,args in steps:db.execute(sql,args)
            db.commit()
        except BaseException:db.rollback();raise
    try:
        check('布局字节可重现',(HERE/'controller-final-admission.sql').read_bytes()==G.build())
        d,cds,items,c=V.fixture(controller_factory=G.build);dbs=[d]+[x[0] for x in cds.values()]
        db,identity,request,auth,provider=items[0];ad=V.M.decide(*items[0]);command=ad['command_ref']['object_id'];view=V.M.read(db,command,V.reader(items[0]))['record']
        check('完整242表初始化',len(V.SC.snapshot(db))==242)
        # 对原组合中四个阻断逐字对账；不能以触发器同名但正文放宽蒙混。
        baseline=sqlite3.connect(':memory:');baseline.executescript(G.B.build().decode());dbs.append(baseline)
        gates=('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')
        for n in gates:check('原最终阻断原样保留'+n,db.execute('SELECT sql FROM sqlite_schema WHERE name=?',(n,)).fetchone()[0]==baseline.execute('SELECT sql FROM sqlite_schema WHERE name=?',(n,)).fetchone()[0])
        fks=db.execute('PRAGMA foreign_key_list(ci_issue)').fetchall();seal_fk=[r for r in fks if r[2]=='fa_seal']
        check('全局issue反向绑定完整三元组',{(r[3],r[4]) for r in seal_fk}=={(k,k) for k in ('permit_id','issued_revision','kind')})
        check('issue反向关系延迟到COMMIT','REFERENCES fa_seal(permit_id,issued_revision,kind) DEFERRABLE INITIALLY DEFERRED' in G.build().decode())
        for kind in ('ordinary','cancel'):
            s,originals,cut=T.fixture(kind);writes=M.planned(s,originals,cut)
            check('完整写集角色数量'+kind,len(writes)==(19 if kind=='ordinary' else 22))
            check('严格大整数保存'+kind,M.u(s['issued_revision'])=='00009007199254740993' and '00009007199254740993' in writes[0][1])
        def candidate(name):
            s,_,_=T.fixture();s.update(seal_id='seal.'+name,permit_id='permit.'+name,transaction_id='tx.'+name,command_state_ref=clone(view['state_ref']))
            s['binding']['scope']=clone(view['scope']);s['binding']['device_id']=view['target']['device_id']
            s['identity']['command_ref']=dict(id=command,revision='1',digest=ad['command_ref']['digest'])
            return F.seal(s)
        observer=T.ref('synthetic.local.writer');s=candidate('rollback')
        rejected('观察写后异常整笔回滚',db,lambda:M.observe(db,s,'obs.failed','53',observer,fail_after_write=True),'injected')
        o=M.observe(db,s,'obs.rollback','53',observer)
        check('查无完整组后持久禁止重签',o['outcome']=='rolled_back' and db.execute('SELECT count(*) FROM fa_observation').fetchone()[0]==1)
        before=V.SC.snapshot(db);check('观察重试返回原件不延长时间',M.observe(db,s,'obs.rollback','99',observer)==o and V.SC.snapshot(db)==before)
        rejected('同观察身份不能更换观察者',db,lambda:M.observe(db,s,'obs.rollback','53',T.ref('other')),'observation_owner')
        changed=F.seal(dict(s,transmission_id='changed'))
        rejected('同观察身份不能换内容',db,lambda:M.observe(db,changed,'obs.rollback','53',observer),'observation_id_conflict')
        rejected('新观察身份也不能重标事务',db,lambda:M.observe(db,changed,'obs.changed','53',observer),'final_observation_identity_conflict')
        unknown=candidate('unknown');first=M.observe(db,unknown,'obs.unknown','53',observer,lookup=False)
        check('未作提交裁决保持unknown',first['outcome']=='unknown')
        second=M.observe(db,unknown,'obs.resolved','54',observer)
        check('新观察可核对但不改历史unknown',second['outcome']=='rolled_back' and json.loads(db.execute('SELECT observation_body FROM fa_observation WHERE observation_id=?',('obs.unknown',)).fetchone()[0])==first)
        # 有墓碑即拒绝新seal；即使其领域原件尚不存在，也必须先命中禁止重签。
        def seal_row(s):
            return M.insert('fa_seal',transaction_id=s['transaction_id'],seal_id=s['seal_id'],permit_id=s['permit_id'],issued_revision=M.u(s['issued_revision']),kind='ordinary',
                command_id=command,state_revision=M.u(s['command_state_ref']['revision']),exit_id=s['binding']['writer_exit_id'],hold_id=s['hold_ref']['id'],ownership_id='missing.owner',before_snapshot_id='missing.before',after_snapshot_id='missing.after',ordinary_id=s['permit_id'],cancel_id=None,
                selected_tick=M.u(s['selected_tick_ns']),sealed_tick=M.u(s['sealed_tick_ns']),not_before_tick=M.u(s['send_window']['not_before_tick_ns']),before_tick=M.u(s['send_window']['before_tick_ns']),seal_digest=s['seal_digest'],seal_body=M.raw(s))
        for old in (s,unknown):rejected('已观察候选不得后补签发'+old['transaction_id'],db,lambda old=old:execute(db,[seal_row(old)]),'observed_transaction_not_reissuable')
        for field in ('transaction_id','permit_id','seal_id'):
            other=candidate('collision.'+field);other[field]=s[field];other=F.seal(other)
            rejected('任一身份复用都禁止签发'+field,db,lambda other=other:execute(db,[seal_row(other)]),'observed_transaction_not_reissuable')
        missing=candidate('unissued')
        rejected('合法列投影也不能缺领域父项',db,lambda:execute(db,[seal_row(missing)]),'FOREIGN KEY')
        rejected('提交标记不能单独存在',db,lambda:execute(db,[M.finish(missing,'53',{},'outbox.unissued',{})]),'final_commit_binding')
        rejected('来源查询禁止事务外调用',db,lambda:M._original(db,missing),'observation_transaction_required')
        source=T.fixture()[1]['origin'];orphan=M.insert('fa_input',seal_id=missing['seal_id'],role='origin',projection_id=source['ref']['id'],projection_revision=source['ref']['revision'],projection_digest=source['ref']['digest'],source_id=source['source_ref']['id'],source_revision=source['source_ref']['revision'],source_digest=source['source_ref']['digest'],body=M.raw(source))
        rejected('投影原件不能孤立提交',db,lambda:execute(db,[orphan]),'final_input_binding')
        fake=T.observation(s,'committed');fake['observation_id']='obs.fake';fake=F.seal(fake,'observation_digest')
        row=M.insert('fa_observation',observation_id=fake['observation_id'],transaction_id=s['transaction_id'],seal_id=s['seal_id'],permit_id=s['permit_id'],seal_digest=s['seal_digest'],outcome='committed',observed_tick=M.u('53'),candidate_body=M.raw(s),observation_body=M.raw(fake))
        rejected('原件缺失不能自报committed',db,lambda:execute(db,[row]),'final_commit_unproven')
        for action in ('UPDATE fa_observation SET outcome=\'unknown\'','DELETE FROM fa_observation'):
            rejected('观察不可变'+action,db,lambda action=action:execute(db,[(action,())]),'immutable_final_admission')
        existing=db.execute('SELECT * FROM fa_observation WHERE observation_id=?',('obs.rollback',));cols=[x[0] for x in existing.description];stored=dict(zip(cols,existing.fetchone()));ins=M.insert('fa_observation',**stored)
        rejected('观察不能REPLACE覆盖',db,lambda:execute(db,[(ins[0].replace('INSERT INTO','INSERT OR REPLACE INTO'),ins[1])]),'immutable_final_admission')
        wrong=clone(s);wrong['binding']['scope']['database_instance_id']='other';wrong=F.seal(wrong)
        rejected('不能查询另一数据库的提交',db,lambda:M.observe(db,wrong,'obs.scope','53',observer),'seal_scope')
        rejected('观察时间早于封存拒绝',db,lambda:M.observe(db,candidate('early'),'obs.early','51',observer),'observation_order')
        # 两个实际SQLite连接竞争同一磁盘库，不用布尔标志伪装writer活性。
        temp_root=ROOT/'logs';temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='final-admission-lock-',dir=temp_root) as temp:
            path=Path(temp)/'reference.sqlite';a=sqlite3.connect(path,isolation_level=None,timeout=0);b=sqlite3.connect(path,isolation_level=None,timeout=0)
            try:
                db.backup(a)
                for connection in (a,b):connection.execute('PRAGMA foreign_keys=ON');connection.execute('PRAGMA recursive_triggers=ON')
                check('锁测试启用WAL',a.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal')
                a.execute('BEGIN IMMEDIATE');busy=candidate('busy')
                rejected('另一writer未结束时不能断言回滚',b,lambda:M.observe(b,busy,'obs.busy','53',observer),'locked')
                a.rollback();obs=M.observe(b,busy,'obs.busy','54',observer)
                check('writer释放后同一观察正常查原',obs['outcome']=='rolled_back')
            finally:
                if a.in_transaction:a.rollback()
                a.close();b.close()
        for i,connection in enumerate(dbs):check('外键完整'+str(i),not connection.execute('PRAGMA foreign_key_check').fetchone())
        check('没有借观察生成真实许可',db.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==0)
        return checks
    finally:
        for db in dbs:db.close()
def inputs():return list(dict.fromkeys(V.inputs()+G.SOURCES+T.inputs()+[HERE/n for n in ('final_admission_storage_model.py','check_final_admission_storage.py','controller-final-admission.sql','FINAL_ADMISSION_STORAGE.md')]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'final-admission-storage-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=242,production_clearance=False,sql_positive_issue_path_executed=False,sqlite_connection_lock_test_executed=True,disk_crash_tests_executed=0,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(T.G.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
