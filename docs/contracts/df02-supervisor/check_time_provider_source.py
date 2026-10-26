"""完整时间提供者准入原件的离线监督日志检查；不创建真实进程。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_retirement_source as F
import time_provider_source_model as M
G=M.G;HERE=G.HERE;ROOT=HERE.parents[2]
LOCAL=('build_time_provider_source.py','time-provider-source.schema.json','time_provider_source_model.py','check_time_provider_source.py','TIME_PROVIDER_SOURCE.md')
def inputs():return list(dict.fromkeys(F.INPUTS+[HERE/n for n in LOCAL]+[HERE.parent/'df03-reference/reference.schema.json']))


def fixture(mutate=None):
    db,source,domain=F.fixture(domain=True,empty=True)
    try:
        _,descriptor=M.S.runtime(db,'new');f=F.C.fixtures();intent=copy.deepcopy(f['intent']);intent.pop('extension_binding')
        intent.update(launch_id='time',supervisor_instance_id='new',runtime_generation=descriptor['runtime_generation'],member_id='time.member',role='time_provider',device_ids=[],containment_ref=dict(group_id='group.time',generation='group.gen.time',backend='windows_job'))
        if mutate:mutate('intent',intent)
        digest=M.digest(intent);policy=M.one(db,"SELECT protected_policy_digest FROM runtime WHERE supervisor_id='new'")['protected_policy_digest']
        receipt=copy.deepcopy(f['receipt']);receipt.update(launch_id='time',launch_intent_digest=digest,member_id=intent['member_id'],member_boot_id='boot.time',bootstrap_id='bootstrap.time',channel_binding_id='channel.time',receipt_id='receipt.time',role=intent['role'],domain_ref=domain,containment_ref=intent['containment_ref'],os_observation_ref='process.time')
        observation=dict(format_version='process-admission-observation/1',observation_id='process.time',provider_id=source['os_provider_id'],domain_ref=domain,member_id='time.member',member_boot_id='boot.time',channel_binding_id='channel.time',containment_ref=intent['containment_ref'],artifact_manifest_ref=intent['artifact_manifest_ref'],observed_tick_ns='15',process_instance_ref=dict(id='synthetic.process',revision='1',digest=M.digest('synthetic.process')),group_owned=True,artifact_matches=True,channel_exclusive=True)
        origin=dict(protected_policy_digest=policy,intent_digest=digest)
        for name,v in (('receipt',receipt),('observation',observation),('origin',origin)):
            if mutate:mutate(name,v)
        with F.J.tx(db):
            db.execute('INSERT INTO launch_intent VALUES(?,?,?,?,?,?,?,?,?,?)',('new','time',digest,M.raw(intent),intent['member_id'],intent['role'],'group.time','group.gen.time','protected_config',M.raw(origin)))
            db.execute("INSERT INTO launch_state(supervisor_id,launch_id) VALUES('new','time')")
            F.J.attempt(db,'time','new',protected=True,recovery=False)
            db.execute("UPDATE launch_state SET state='awaiting_bootstrap' WHERE supervisor_id='new' AND launch_id='time'")
            db.execute('INSERT INTO bootstrap_challenge VALUES(?,?,?,?,?,?,?,?)',('new','time','bootstrap.time','boot.time','channel.time','10','20',M.digest('synthetic.transcript')))
            db.execute('INSERT INTO os_observation VALUES(?,?,?,?,?,?,?,?,?)',('process.time','new','time','new','process_instance','group.time','group.gen.time','15',M.raw(observation)))
            db.execute('INSERT INTO admission_receipt VALUES(?,?,?,?,?,?,?)',('new','time','receipt.time','bootstrap.time','process.time','15',M.raw(receipt)))
            db.execute("UPDATE launch_state SET state='admitted_closed',admission_id='receipt.time' WHERE supervisor_id='new' AND launch_id='time'")
        return db,source
    except BaseException:db.close();raise


def run():
    checks=[];connections=[]
    def check(name,v=True):assert v,name;checks.append(dict(name=name,passed=True))
    def fresh(mutate=None):
        db,source=fixture(mutate);connections.append(db);return db,source
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error) as error:
            if reason:assert reason in str(error),(name,str(error))
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    def capture(db,source):return M.capture(db,'new','time',source)
    try:
        check('生成Schema一致',(HERE/'time-provider-source.schema.json').read_bytes()==G.encoded())
        db,source=fresh();before=list(db.iterdump());binding=capture(db,source)
        check('时间提供者完整原件',binding['intent']['role']=='time_provider' and binding['intent']['device_ids']==[])
        check('同身份确定性查原',capture(db,source)==binding)
        check('读取无写入',list(db.iterdump())==before)
        domain=dict(authority_service_id=source['service_id'],database_instance_id=source['database_instance_id'],provider_id='time.member',provider_boot_id='boot.time',runtime_binding_ref=M.reference(binding),clock_generation='1',**M.S.domain(binding['descriptor']))
        check('时间Domain绑定完整准入',M.verify_domain(binding,domain))
        for field in ('authority_service_id','database_instance_id','provider_id','provider_boot_id','runtime_binding_ref','clock_domain_id','descriptor_digest'):
            bad=copy.deepcopy(domain)
            if field=='runtime_binding_ref':bad[field]['id']='worker.runtime'
            elif field=='clock_domain_id':bad[field]='clock_'+'0'*64
            elif field=='descriptor_digest':bad[field]=M.digest('other')
            else:bad[field]='other'
            denied('错域:'+field,lambda bad=bad:M.verify_domain(binding,bad),'provider_time_domain')
        denied('非法时间代次拒绝',lambda:M.verify_domain(binding,dict(domain,clock_generation='gen.new')))
        for field in ('host_installation_id','incarnation_id','service_id','database_instance_id','os_provider_id'):
            denied('错可信源:'+field,lambda field=field:capture(db,dict(source,**{field:'other'})))
        for kind,field,value,reason in (
            ('intent','role','core','provider_role'),('intent','device_ids',['device'],'maxItems'),
            ('intent','runtime_generation','other','provider_intent'),
            ('receipt','member_boot_id','other','provider_bootstrap'),('receipt','channel_binding_id','other','provider_bootstrap'),
            ('receipt','launch_intent_digest',M.digest('other'),'provider_admission'),
            ('receipt','role','worker','provider_admission'),
            ('receipt','artifact_manifest_ref',dict(manifest_id='other',revision='1',digest=M.digest('other')),'provider_admission'),
            ('origin','protected_policy_digest',M.digest('other'),'provider_protected_origin'),
            ('observation','provider_id','other','provider_process_observation'),
            ('observation','member_boot_id','other','provider_process_observation'),
            ('observation','channel_binding_id','other','provider_process_observation'),
            ('observation','observed_tick_ns','21','provider_process_observation')):
            def mutate(k,v,kind=kind,field=field,value=value):
                if k==kind:v[field]=value
            bad,s=fresh(mutate);denied(kind+':'+field,lambda bad=bad,s=s:capture(bad,s),None if reason=='maxItems' else reason)
            check(kind+':'+field+'读取失败清理事务',not bad.in_transaction)
        bad,s=fresh();bad.execute("UPDATE launch_state SET state='retiring' WHERE supervisor_id='new' AND launch_id='time'")
        denied('成员已开始退役',lambda:capture(bad,s),'provider_member_closed')
        bad,s=fresh();bad.execute("UPDATE runtime SET phase='closing' WHERE supervisor_id='new'")
        denied('监督域已关闭',lambda:capture(bad,s),'provider_runtime_closed')
        db.execute('BEGIN');denied('不接管外部事务',lambda:capture(db,source),'provider_source_nested_transaction');check('外部事务保留',db.in_transaction);db.rollback()
        class CommitFault:
            def __getattr__(self,k):return getattr(db,k)
            def commit(self):raise sqlite3.OperationalError('synthetic_read_commit_failure')
        denied('读取提交失败不交付',lambda:capture(CommitFault(),source),'synthetic_read_commit_failure');check('提交失败回滚',not db.in_transaction)
        c,s=fresh();original=capture(c,s)
        class RetireAfterRead:
            def __getattr__(self,k):return getattr(c,k)
            def commit(self):
                c.commit()
                c.execute("UPDATE launch_state SET state='retiring' WHERE supervisor_id='new' AND launch_id='time'")
        check('读完成后退役仍可能收到旧候选',capture(RetireAfterRead(),s)==original)
        check('候选返回时成员已退役中',c.execute("SELECT state FROM launch_state WHERE supervisor_id='new' AND launch_id='time'").fetchone()[0]=='retiring')
        denied('下一次当前读取拒绝旧成员',lambda:capture(c,s),'provider_member_closed')
        check('完整外键',all(not d.execute('PRAGMA foreign_key_check').fetchone() for d in connections))
        return dict(all_passed=True,approved=False,cases_passed=len(checks),checks=checks,supervisor_tables=15,
            provider_admission_source_verified=True,current_os_liveness_verified=False,controller_atomic_adoption_verified=False,
            full_open_verified=False,device_tests_executed=0,inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()})
    finally:
        for d in connections:d.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'time-provider-source-report.json'
    if a.check_report:
        r=json.loads(path.read_bytes());assert r['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};print(json.dumps(dict(bindings_valid=True,input_count=len(r['inputs']),rerun=False)))
    else:
        r=run()
        if a.report:path.write_bytes(M.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
