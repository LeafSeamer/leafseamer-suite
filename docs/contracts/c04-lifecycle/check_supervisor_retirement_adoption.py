"""完整启动绑定在登记时写入，退役采用与撤回的跨库离线实验。"""
import argparse,copy,hashlib,importlib.util,json,sqlite3,sys
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import check_authorization_close_ack as Q
import supervisor_retirement_adoption_model as R
N=R.N;M=R.M;P=R.P;D=N.D;A=N.A;E=N.E;T=Q.T;HERE=R.HERE;ROOT=HERE.parents[2]
def source_fixture_module():
    # 旧检查器使用通用模块名；隔离加载并恢复宿主模块表，避免串用同名夹具。
    folder=HERE.parent/'df02-supervisor';names=('build_contracts','check_contracts','check_journal');saved={n:sys.modules.pop(n,None) for n in names};sys.path.insert(0,str(folder))
    try:
        spec=importlib.util.spec_from_file_location('retirement_source_fixture',folder/'check_retirement_source.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    finally:
        sys.path.remove(str(folder))
        for n,v in saved.items():
            sys.modules.pop(n,None)
            if v is not None:sys.modules[n]=v
F=source_fixture_module()
def inputs():return list(dict.fromkeys(Q.inputs()+F.INPUTS+[R.G.SOURCE,R.G.SUP,R.G.ENC]+[HERE/n for n in ('close_evidence_model.py','build_supervisor_retirement_adoption.py','supervisor-retirement-adoption.schema.json','supervisor-retirement-adoption.sql','supervisor_retirement_adoption_model.py','check_supervisor_retirement_adoption.py','SUPERVISOR_RETIREMENT_ADOPTION.md')]))
def fixture(worker_devices=None):
    execute=E.O.execute;CS=T.T.T.T.CS;control_execute=CS.C.execute;sources={};connections=[]
    def source(db,device):
        scope=M.E.A.scope(db);key=(scope['authority_service_id'],scope['database_instance_id'],'shared' if worker_devices else device)
        if key not in sources:
            original=F.C.fixtures
            def customized():
                f=original();f['scope'].update(service_id=scope['authority_service_id'],database_instance_id=scope['database_instance_id']);f['assignment']['clock_domain_descriptor']['authority_service_id']=scope['authority_service_id'];f['intent'].update(service_id=scope['authority_service_id'],device_ids=worker_devices or [device]);return f
            with patch.object(F.C,'fixtures',side_effect=customized):sd,identity,domain=F.fixture()
            connections.append(sd);bundle=R.S.capture(sd,'old','retirement.complete',identity,domain,'3');sources[key]=(sd,identity,domain,bundle)
        return sources[key]
    def transformed(db,steps):
        out=[]
        for sql,args in steps:
            if sql.startswith(('INSERT INTO ct_change','INSERT INTO ce_exit')):
                fields=[s.strip() for s in sql.split('(',1)[1].split(')',1)[0].split(',')];row=dict(zip(fields,args));sd,identity,domain,bundle=source(db,row['device_id']);old=bundle['old_descriptor']
                if sql.startswith('INSERT INTO ct_change'):row.update(clock_domain=old['clock_domain_id'],descriptor=old['descriptor_digest'])
                else:
                    member=bundle['members'][0];row.update(clock_domain_id=old['clock_domain_id'],descriptor_digest=old['descriptor_digest'],worker_boot_id=member['admission_receipt']['member_boot_id'])
                    binding=dict(scope=M.E.A.scope(db),writer_exit_id=row['exit_id'],**{k:row[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_session_id','device_id','clock_domain_id','descriptor_digest')})
                    value=M.sealed(dict(format_version='runtime-exit-binding/0.1.0-draft.1',binding_id=row['exit_id']+'.runtime',revision='1',binding=binding,source=identity,intent=member['intent'],admission_receipt=member['admission_receipt'],authorization_evidence_ref=E.ref('synthetic.start.authorization')),'binding_digest');R.validate('RuntimeExitBinding',value);row['runtime_binding_body']=M.raw(value)
                sql,args=E.I('ct_change' if sql.startswith('INSERT INTO ct_change') else 'ce_exit',**row)
            out.append((sql,args))
        return out
    def full_runtime(db,steps,fail_after=None):return execute(db,transformed(db,steps),fail_after)
    def initial_runtime(db,steps,*args,**kw):return control_execute(db,transformed(db,steps),*args,**kw)
    with patch.object(E.O,'execute',side_effect=full_runtime),patch.object(CS.C,'execute',side_effect=initial_runtime):db,other,command,auth,pid,provider,response=T.fixture()
    connections.extend([db]+other);D.install(db);A.install(db);R.install(db)
    binding=provider['binding'];eid=binding['writer_exit_id'];scope=binding['scope'];sd,identity,domain,bundle=sources[(scope['authority_service_id'],scope['database_instance_id'],'shared' if worker_devices else binding['device_id'])]
    fault=D.C.I.ingest(db,binding,b'{');plan=D.C.prepare(db,binding,fault['fault_ref']);state=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(binding['device_id'],))
    timing=dict(device_id=binding['device_id'],clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns='200',source_ref=T.T.V.ref('synthetic.retirement.tick'))
    protection,_=P.apply(db,D.C.pref(plan),[timing]);cid=protection['exits'][0]['close_id'];D.queue(db,D.pref(protection),cid,'201')
    return db,connections,sd,domain,eid,cid
def run():
    checks=[];connections=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def snapshot(c):return T.T.T.V.SC.snapshot(c)
    def fork(c):
        x=sqlite3.connect(':memory:',isolation_level=None);c.backup(x);x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON');connections.append(x);return x
    def denied(n,fn):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error,D.C.I.ClockIngressStop):check(n)
        else:raise AssertionError('应拒绝:'+n)
    try:
        db,other,sd,domain,eid,cid=fixture();connections.extend(other);base=fork(db);original_source='\n'.join(sd.iterdump());initial=snapshot(db)
        def adopt(c,**kw):return R.adopt(c,eid,sd,'old','retirement.complete',domain,'3',**kw)
        value,valid,writes=adopt(db)
        check('257表实际组合',len(snapshot(db))==257)
        check('采用与退役及seal同事务',valid and writes==['sr_adoption','ce_retirement','sr_commit'] and R.read(db,eid)==value)
        check('监督来源无写入','\n'.join(sd.iterdump())==original_source)
        check('已登记启动身份精确关联',value['runtime_binding_ref']['digest']==R.runtime(db,eid)[0]['binding_digest'])
        check('真实ce退役保存完整原件',M.document(db.execute('SELECT supervisor_evidence_body FROM ce_retirement WHERE exit_id=?',(eid,)).fetchone()[0])==value)
        before=snapshot(db);check('重试只查原',adopt(db)==(value,True,[]) and snapshot(db)==before)
        denied('退役会话禁止未尝试关闭帧入流',lambda:D.begin_write(db,cid,'202'))
        check('退役未生成准备完成',not db.execute('SELECT 1 FROM pd_close_completion WHERE close_id=?',(cid,)).fetchone())
        check('未退款或签发许可',db.execute('SELECT count(*) FROM ep_release').fetchone()[0]==base.execute('SELECT count(*) FROM ep_release').fetchone()[0] and not db.execute('SELECT 1 FROM ci_issue').fetchone())
        device=value['binding']['device_id'];check('持有人和保护态不变',tuple(db.execute('SELECT gate_state,holder_id FROM ct_current_state WHERE device_id=?',(device,)).fetchone())==tuple(base.execute('SELECT gate_state,holder_id FROM ct_current_state WHERE device_id=?',(device,)).fetchone()))
        for i in range(len(writes)):
            x=fork(base);before=snapshot(x);denied('逐写异常:'+str(i),lambda:R.adopt(x,eid,sd,'old','retirement.complete',domain,'3',fail_after=i));check('逐写全库回滚:'+str(i),snapshot(x)==before)
        class Omit:
            def __init__(self,c,table):self.c=c;self.table=table;self.hit=0
            def __getattr__(self,k):return getattr(self.c,k)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO '+self.table+' ('):self.hit+=1;return self.c.execute('SELECT 1 WHERE 0')
                return self.c.execute(sql,args)
        for table in writes:
            x=fork(base);before=snapshot(x);proxy=Omit(x,table);denied('缺写:'+table,lambda:adopt(proxy));check('缺写命中并回滚:'+table,proxy.hit>0 and snapshot(x)==before)
        class CommitFault:
            def __init__(self,c,committed):self.c=c;self.committed=committed
            def __getattr__(self,k):return getattr(self.c,k)
            def commit(self):
                if self.committed:self.c.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation_failure')
        for committed in (False,True):
            x=fork(base);before=snapshot(x);denied('提交观察故障:'+str(committed),lambda:adopt(CommitFault(x,committed)))
            if committed:
                stable=snapshot(x);check('已提交查原',adopt(x)==(value,True,[]) and snapshot(x)==stable)
            else:check('未提交整体回滚',snapshot(x)==before)
        binding,e=R.runtime(db,eid)
        # 不改写不可变出口，直接验证完整来件与已登记身份的匹配函数。
        for name,change in [('启动代次',lambda b:b['members'][0]['admission_receipt'].update(member_boot_id='wrong')),('设备集合',lambda b:b['members'][0]['intent'].update(device_ids=['wrong'])),('来源身份',lambda b:b['source'].update(incarnation_id='wrong')),('缺成员',lambda b:b.update(members=[])),('状态',lambda b:b['members'][0].update(state='rejected'))]:
            b=copy.deepcopy(value['source_bundle']);change(b);b['bundle_digest']=R.S.digest({k:v for k,v in b.items() if k!='bundle_digest'});denied('重算摘要也拒绝:'+name,lambda:R.bound_bundle(binding,b))
        denied('错误评价域不得采用',lambda:R.adopt(fork(base),eid,sd,'old','retirement.complete',value['source_bundle']['evidence']['old_domain_ref'],'3'))
        source_before='\n'.join(sd.iterdump());sd.execute("UPDATE runtime SET phase='closing' WHERE supervisor_id='old'")
        check('监督后续关闭不使历史采用冲突',adopt(db)==(value,True,[]) and '\n'.join(sd.iterdump())!=source_before)
        class UnavailableSource:
            def __getattr__(self,k):raise AssertionError('重复查原不得访问监督来源')
        check('来源暂不可读仍可查本地原件',R.adopt(db,eid,UnavailableSource(),'old','retirement.complete',domain,'999')==(value,True,[]))
        denied('重复查原不能换证据ID',lambda:R.adopt(db,eid,UnavailableSource(),'old','other',domain,'999'))
        denied('重复查原不能换监督身份',lambda:R.adopt(db,eid,UnavailableSource(),'other','retirement.complete',domain,'999'))
        db.execute('BEGIN');denied('外部事务不能采用',lambda:adopt(db));check('不接管调用方事务',db.in_transaction);db.rollback()
        legacy,legacy_other,cmd,auth,lpid,provider,response=T.fixture();connections.extend([legacy]+legacy_other)
        denied('旧占位启动绑定不能用于退役',lambda:R.runtime(legacy,provider['binding']['writer_exit_id']))
        check('撤回证明成功',R.revoke(db,eid,{'reason':'synthetic evidence withdrawal'})=='revoked' and not R.current(db,eid))
        before=snapshot(db);check('撤回后重复采用不复活',adopt(db)==(value,False,[]) and snapshot(db)==before)
        denied('撤回后旧会话仍不能发送',lambda:D.begin_write(db,cid,'203'))
        check('重复撤回查原',R.revoke(db,eid,{'reason':'synthetic evidence withdrawal'})=='lookup_only')
        denied('重复撤回不能换原因',lambda:R.revoke(db,eid,{'reason':'changed'}))
        for table in ('sr_adoption','sr_commit'):
            for sql in ('DELETE FROM '+table,'UPDATE '+table+' SET exit_id=exit_id'):denied('原件不可变:'+sql,lambda sql=sql:T.tx(db,lambda:db.execute(sql)))
        check('四个最终阻断保留',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'supervisor-retirement-adoption-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=257,supervisor_tables=15,retirement_adoption_verified=True,revocation_keeps_old_session_stopped=True,runtime_admission_authenticity_verified=False,os_authenticity_verified=False,alternative_close_completion_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
