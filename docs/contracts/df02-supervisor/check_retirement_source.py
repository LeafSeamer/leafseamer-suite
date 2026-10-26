"""完整监督BODY和两个时钟域的快照读取实验；不执行真实OS观察。"""
import argparse,copy,hashlib,json,sqlite3
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import retirement_source_model as M
import check_contracts as C
import check_journal as J
HERE=M.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(J.INPUTS+C.INPUTS+M.FILES+[HERE/n for n in ('build_retirement_source.py','retirement-source.schema.json','retirement_source_model.py','check_retirement_source.py','RETIREMENT_SOURCE.md')]))
def fixture(domain=False,mutate=None,empty=False):
    db=sqlite3.connect(':memory:',isolation_level=None);db.executescript((HERE/'journal.sql').read_text('utf-8'));f=C.fixtures();intents={};receipts={}
    descriptors={}
    for sid in ('old','new'):
        d=copy.deepcopy(f['assignment']['clock_domain_descriptor']);d.update(supervisor_instance_id=sid,runtime_generation='gen.'+sid)
        h=M.digest({k:v for k,v in d.items() if k not in ('clock_domain_id','descriptor_digest')});d.update(clock_domain_id='clock_'+h[7:],descriptor_digest=h)
        if mutate:mutate('descriptor',d)
        descriptors[sid]=d
    source=dict(host_installation_id='host.test',incarnation_id='incarnation.test',service_id=f['scope']['service_id'],database_instance_id=f['scope']['database_instance_id'],os_provider_id='synthetic.os.provider')
    db.execute('INSERT INTO journal_meta VALUES(1,?,?,?,?)',('supervisor-journal/0.1.0-draft.1',source['host_installation_id'],source['incarnation_id'],M.digest('storage')))
    for sid,d in descriptors.items():
        db.execute('INSERT INTO runtime(supervisor_id,service_id,runtime_generation,domain_id,descriptor_digest,descriptor_jcs,protected_policy_digest,root_group_id,root_group_generation,root_backend) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (sid,source['service_id'],d['runtime_generation'],d['clock_domain_id'],d['descriptor_digest'],M.raw(d),M.digest('policy'),'root.'+sid,'root.gen.'+sid,'windows_job'))
        scope=dict(service_id=source['service_id'],database_instance_id=source['database_instance_id'],supervisor_instance_id=sid,domain_ref=M.domain(d))
        db.execute('INSERT INTO control_scope VALUES(?,?,?,?)',(sid,source['service_id'],source['database_instance_id'],M.raw(scope)))
    names=() if empty and domain else ('one','two') if domain else ('one',)
    for name in names:
        v=copy.deepcopy(f['intent']);v.update(launch_id=name,supervisor_instance_id='old',runtime_generation='gen.old',member_id='member.'+name,containment_ref=dict(group_id='group.'+name,generation='group.gen.'+name,backend='windows_job'));intents[name]=v
    with J.tx(db):
        J.snapshot(db,'1',[(name,M.digest(v),'allow') for name,v in intents.items()])
        for name,v in intents.items():
            body=copy.deepcopy(v)
            if mutate:mutate('intent',body)
            db.execute('INSERT INTO launch_intent VALUES(?,?,?,?,?,?,?,?,?,?)',('old',name,M.digest(v),M.raw(body),v['member_id'],'worker',v['containment_ref']['group_id'],v['containment_ref']['generation'],'extension',M.raw(v['extension_binding'])))
            db.execute("INSERT INTO launch_state(supervisor_id,launch_id) VALUES('old',?)",(name,));J.attempt(db,name);J.awaiting(db,name)
            receipt=copy.deepcopy(f['receipt']);receipt.update(launch_id=name,launch_intent_digest=M.digest(v),member_id=v['member_id'],member_boot_id='boot.old.'+name,bootstrap_id='bootstrap.old.'+name,channel_binding_id='channel.old.'+name,receipt_id='receipt.old.'+name,
                domain_ref=M.domain(descriptors['old']),containment_ref=v['containment_ref'],os_observation_ref='process.old.'+name,admitted_tick_ns='15')
            if mutate:mutate('receipt',receipt)
            receipts[name]=receipt
            db.execute('INSERT INTO admission_receipt VALUES(?,?,?,?,?,?,?)',('old',name,'receipt.old.'+name,'bootstrap.old.'+name,'process.old.'+name,'15',M.raw(receipt)))
            db.execute("UPDATE launch_state SET state='admitted_closed',admission_id=? WHERE supervisor_id='old' AND launch_id=?",('receipt.old.'+name,name))
            db.execute("UPDATE launch_state SET state='retiring' WHERE supervisor_id='old' AND launch_id=?",(name,))
        if domain:db.execute("UPDATE runtime SET phase='closing' WHERE supervisor_id='old'")
    containment=dict(group_id='root.old',generation='root.gen.old',backend='windows_job') if domain else intents['one']['containment_ref']
    mids=sorted(v['member_id'] for v in intents.values());evidence_id='retirement.complete';oid='exit.complete'
    observation=dict(format_version='retirement-observation/1',observation_id=oid,provider_id=source['os_provider_id'],subject_domain_ref=M.domain(descriptors['old']),evaluator_domain_ref=M.domain(descriptors['new']),containment_ref=containment,
        target_member_ids=mids,observed_tick_ns='2',launch_intake_closed=True,group_owned=True,members_complete=True,live_process_count=0,open_endpoint_count=0)
    evidence=dict(evidence_id=evidence_id,service_id=source['service_id'],old_domain_ref=M.domain(descriptors['old']),target_scope='runtime_domain' if domain else 'member_group',target_member_ids=mids,containment_ref=containment,launch_intake_closed=True,
        os_observation_refs=[oid],result='confirmed_empty',evaluator_domain_ref=M.domain(descriptors['new']),observed_tick_ns='2')
    if mutate:mutate('observation',observation);mutate('evidence',evidence)
    with J.tx(db):
        db.execute('INSERT INTO os_observation VALUES(?,?,?,?,?,?,?,?,?)',(oid,'old',None if domain else 'one','new','domain_exit' if domain else 'group_exit',containment['group_id'],containment['generation'],'2',M.raw(observation)))
        db.execute('INSERT INTO retirement_evidence(supervisor_id,evidence_id,target_scope,target_launch_id,observer_supervisor_id,observation_id,result,target_count,evidence_jcs) VALUES(?,?,?,?,?,?,?,?,?)',('old',evidence_id,'runtime_domain' if domain else 'member_group',None if domain else 'one','new',oid,'confirmed_empty',len(names),M.raw(evidence)))
        for name in names:db.execute("INSERT INTO retirement_target VALUES('old',?,?)",(name,evidence_id))
        db.execute("UPDATE retirement_evidence SET sealed=1 WHERE supervisor_id='old' AND evidence_id=?",(evidence_id,))
        for name in names:db.execute("UPDATE launch_state SET state='retired',retirement_id=? WHERE supervisor_id='old' AND launch_id=?",(evidence_id,name))
        if domain:db.execute("UPDATE runtime SET phase='retired',domain_retirement_id=? WHERE supervisor_id='old'",(evidence_id,))
    return db,source,M.domain(descriptors['new'])
def run():
    checks=[];connections=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def fresh(**kwargs):
        db,s,d=fixture(**kwargs);connections.append(db);return db,s,d
    def capture(c,s,d,tick='3'):return M.capture(c,'old','retirement.complete',s,d,tick)
    def snapshot(c):return '\n'.join(c.iterdump())
    def denied(n,fn):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error):check(n)
        else:raise AssertionError('应拒绝:'+n)
    try:
        for domain in (False,True):
            db,s,d=fresh(domain=domain);before=snapshot(db);bundle=capture(db,s,d)
            check('真实15表:'+str(domain),db.execute("SELECT count(*) FROM sqlite_schema WHERE type='table'").fetchone()[0]==15)
            check('完整覆盖:'+str(domain),len(bundle['members'])==(2 if domain else 1) and all(x['admission_receipt'] is not None for x in bundle['members']))
            check('跨域tick2不与旧域15比较:'+str(domain),bundle['evidence']['observed_tick_ns']=='2' and all(x['admission_receipt']['admitted_tick_ns']=='15' for x in bundle['members']))
            check('规范摘要:'+str(domain),bundle['bundle_digest']==M.digest({k:v for k,v in bundle.items() if k!='bundle_digest'}))
            check('只读快照不修改来源:'+str(domain),snapshot(db)==before and not db.in_transaction)
            check('同来源重复稳定:'+str(domain),capture(db,s,d)==bundle)
            for field in s:
                bad=dict(s);bad[field]='wrong';denied('来源身份拒绝:'+str(domain)+field,lambda:capture(db,bad,d))
            denied('未来观察拒绝:'+str(domain),lambda:capture(db,s,d,'1'))
            denied('不得用旧域评价新观察:'+str(domain),lambda:capture(db,s,bundle['evidence']['old_domain_ref']))
        mutations=[('evidence',k,v) for k,v in [('target_member_ids',[]),('launch_intake_closed',False),('result','unproven'),('os_observation_refs',['wrong']),('observed_tick_ns','1')]]
        mutations += [('observation',k,v) for k,v in [('provider_id','wrong'),('live_process_count',1),('open_endpoint_count',1),('members_complete',False),('group_owned',False),('launch_intake_closed',False),('target_member_ids',[]),('observed_tick_ns','1')]]
        mutations += [('receipt',k,v) for k,v in [('member_boot_id','wrong'),('launch_intent_digest',M.digest('wrong')),('channel_binding_id','wrong'),('os_observation_ref','wrong'),('admitted_tick_ns','20')]]
        mutations += [('intent','device_ids',['wrong.device']),('descriptor','namespace_identity','wrong.namespace')]
        for section,key,value in mutations:
            def mutate(kind,v):
                if kind==section:v[key]=value
            db,s,d=fresh(mutate=mutate);before=snapshot(db);denied('BODY关系拒绝:'+section+'.'+key,lambda:capture(db,s,d));check('错误读取无写入:'+section+'.'+key,snapshot(db)==before and not db.in_transaction)
        db,s,d=fresh(domain=True,empty=True);bundle=capture(db,s,d)
        check('已确认空域允许零成员证明',bundle['members']==[] and bundle['evidence']['target_member_ids']==[])
        db,s,d=fresh(domain=True)
        with patch.object(M,'MAX_MEMBERS',1):denied('容量不足不截断',lambda:capture(db,s,d))
        with patch.object(M,'MAX_BUNDLE',1):denied('导出正文超限拒绝',lambda:capture(db,s,d))
        denied('非规范JSON拒绝',lambda:M.document(b'{ "x":1}'));denied('重复键拒绝',lambda:M.document(b'{"x":1,"x":1}'))
        db.execute('BEGIN');denied('外部未提交事务不能导出',lambda:capture(db,s,d));check('不接管外部事务',db.in_transaction);db.rollback()
        class CommitFault:
            def __getattr__(self,k):return getattr(db,k)
            def commit(self):raise sqlite3.OperationalError('synthetic_read_commit_failure')
        before=snapshot(db);denied('读取提交失败不交付证明',lambda:capture(CommitFault(),s,d));check('读取失败回滚',snapshot(db)==before and not db.in_transaction)
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'retirement-source-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),supervisor_tables=15,full_body_binding_verified=True,controller_retirement_adoption_verified=False,os_authenticity_verified=False,ipc_io_executed=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
