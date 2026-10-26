"""跨域取消准备核销、历史保留与开放资格失效的离线验收。"""
import argparse,copy,hashlib,json,sqlite3
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import check_prepared_cancel as T
import retired_cancel_model as R
C=R.C;N=R.N;S=T.S;F=T.F;HERE=R.G.HERE;ROOT=T.ROOT
LOCAL=('build_retired_cancel.py','retired-cancel.schema.json','retired-cancel-seal.sql','retired-cancel.sql','retired_cancel_model.py','check_retired_cancel.py','RETIRED_CANCEL.md')
def inputs():return list(dict.fromkeys(T.inputs()+[HERE/n for n in LOCAL]))
def state(db):return {name:sorted([tuple(r) for r in db.execute('SELECT * FROM '+name)],key=repr) for name, in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")}
def fixture(ordinary=True):
    def old(c):
        T.accept(c)
        if ordinary:C.capture(c,'cancel','ordinary','ordinary',prepare_context=T.context(c))
    db,others,eid,cid,sid,selections=F.fixture(old);R.install(db)
    refs={m['prepare_id']:'healthy.retired' for m in R.rows(db,'SELECT prepare_id FROM ep_request')}
    return db,others,dict(eid=eid,cid=cid,sid=sid,selections=selections,refs=refs,context=T.context(db,'12'))
def recovery(db,v):
    S.install(db);S.R.install(db);T.U.protection(db,'source.protect',run='unrelated_run');S.R.capture(db,'run.full');S.capture(db,'command.full',F.DEVICES[0])
    links=dict(F.O.LINKS,run_snapshot_ref='run.full',command_snapshot_ref='command.full')
    S.R.O.recover(db,'full.recovery','full.snapshot',v['eid'],links,'22','100',F.O.E.ref('provider.full'),v['selections']);F.O.fence(db,v['cid'],v['sid'])
def run():
    checks=[];connections=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def clone(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');connections.append(c);return c
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,sqlite3.Error,ValidationError) as e:
            chain=[]
            while e:chain.append(str(e));e=e.__cause__
            if reason:assert any(reason in s for s in chain),(name,chain)
            check(name)
        else:raise AssertionError('应拒绝:'+name)
    def capture(c,**kw):return R.capture(c,'cancel','all','all',kw.pop('refs',v['refs']),kw.pop('ctx',v['context']),**kw)
    class Omit:
        def __init__(self,db,index):self.db=db;self.index=index;self.count=0
        def __getattr__(self,k):return getattr(self.db,k)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '):
                n=self.count;self.count+=1
                if n==self.index:return self.db.execute('SELECT 1 WHERE 0')
            return self.db.execute(sql,args)
    try:
        db,others,v=fixture();connections.extend(others);connections.append(db);seed=clone(db);before_rev=R.rows(db,'SELECT * FROM ep_revocation');before_release=R.rows(db,'SELECT * FROM ep_release')
        cut,writes=capture(db);source=N.transaction(db,lambda:R.read(db,cut,live=True))
        check('跨域all保留ordinary前驱',cut['previous_cut_ref']['id']=='ordinary' and len(source['retirements'])==1)
        check('新域较小tick仍核销旧域准备',int(v['context']['selected_tick_ns'])<int(before_rev[0]['revoked_tick']) and R.rows(db,'SELECT * FROM ep_revocation')==before_rev)
        check('退役核销不释放编码缓存',R.rows(db,'SELECT * FROM ep_release')==before_release)
        check('显式退役成员与原子seal',writes==['cc_cut','cc_target','cc_target','pd_cut','pd_member','crp_member','pd_cut_commit','cc_cut_commit'])
        snapshot=state(db);check('同ID查原不追加写入',capture(db)==(cut,[]) and state(db)==snapshot)
        denied('重入不得改上下文',lambda:capture(db,ctx=dict(v['context'],selected_tick_ns='13')),'retired_cancel_replay_conflict')
        denied('重入不得改证明引用',lambda:capture(db,refs={next(iter(v['refs'])):'wrong'}),'retired_cancel_replay_conflict')
        denied('旧同域入口不能隐式重入跨域cut',lambda:C.capture(db,'cancel','all','all',prepare_context=v['context']),'cancel_cut_retirement_context_required')
        for i in range(len(writes)):
            c=clone(seed);before=state(c);denied('逐写故障:'+str(i),lambda:capture(c,fail_after=i),'injected');check('逐写回滚:'+str(i),state(c)==before)
            c=clone(seed);before=state(c);denied('漏写:'+str(i),lambda:capture(Omit(c,i)));check('漏写回滚:'+str(i),state(c)==before)
        c=clone(seed);before=state(c);denied('新域大tick不能替代缺失退役成员',lambda:capture(Omit(c,5),ctx=dict(v['context'],selected_tick_ns='1000')),'retired_cancel_incomplete');check('大tick漏证明仍全回滚',state(c)==before)
        class CommitFault:
            def __init__(self,db,committed):self.db=db;self.committed=committed
            def __getattr__(self,k):return getattr(self.db,k)
            def commit(self):
                if self.committed:self.db.commit()
                raise sqlite3.OperationalError('synthetic_commit_observation')
        for done in (False,True):
            c=clone(seed);before=state(c);denied('提交观察故障:'+str(done),lambda:capture(CommitFault(c,done)))
            check('提交观察原子结果:'+str(done),capture(c)[1]==[] if done else state(c)==before)
        for name,refs in [('缺证明',{}),('不存在完成',{'prepare_typed':'missing'}),('多余成员',dict(v['refs'],other='healthy.retired'))]:
            c=clone(seed);before=state(c);denied(name,lambda:capture(c,refs=refs));check(name+'无残留',state(c)==before)
        c=clone(seed);X=R.X;X.R.revoke(c,'exit_dev_1',dict(reason='synthetic_withdrawal'));before=state(c)
        denied('签发前撤回拒绝',lambda:capture(c),'retired_cancel_not_current');check('撤回拒绝不改历史',state(c)==before)
        class RevokeBeforeSeal:
            def __init__(self,db):self.db=db
            def __getattr__(self,k):return getattr(self.db,k)
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO pd_cut_commit '):
                    b=R.raw(dict(reason='synthetic_revoke_in_writer'));self.db.execute(*R.I('cu_revocation',kind='retirement',object_id='exit_dev_1',reason_body=b,audit_body=b))
                return self.db.execute(sql,args)
        c=clone(seed);before=state(c);denied('seal重读撤回来源',lambda:capture(RevokeBeforeSeal(c)));check('同事务撤回故障整体回滚',state(c)==before)
        for name,sample in [('RetiredCancelSource',source),('RetiredCancelMember',source['retirements'][0])]:
            for k in sample:
                bad=copy.deepcopy(sample);del bad[k];denied('Schema必填:'+name+':'+k,lambda:R.validate(name,bad))
            denied('Schema额外字段:'+name,lambda:R.validate(name,dict(sample,extra=True)))
        member={k:source['retirements'][0][k] for k in ('prepare_id','exit_id','authorization_id','authorization_digest')}
        for name,selection in [('未来观察',dict(source['selection'],selected_tick_ns='0')),('错误评估域',dict(source['selection'],clock_domain_id='clock_'+'0'*64)),('错误评估描述',dict(source['selection'],descriptor_digest=R.digest('wrong')))]:
            denied(name,lambda:N.transaction(db,lambda:R.proof(db,member,selection,'healthy.retired',live=True)))
        denied('同数量错误授权',lambda:N.transaction(db,lambda:R.proof(db,dict(member,authorization_digest=R.digest('wrong')),source['selection'],'healthy.retired',live=True)),'retired_cancel_authorization')
        for operation in ('UPDATE crp_member SET completion_id=completion_id','DELETE FROM crp_member'):
            denied('证明不可变:'+operation,lambda:db.execute(operation),'immutable_retired_cancel')
        # 隔离损坏证明行；保持数量和seal正文，读回仍须比对原件。
        c=clone(db);c.execute('DROP TRIGGER crp_u');c.execute("UPDATE crp_member SET body=?,audit_body=?",(R.raw(dict(wrong=True)),R.raw(dict(wrong=True))))
        denied('损坏证明正文拒绝',lambda:N.transaction(c,lambda:C.read_cut(c,'all')),'retired_cancel_proof_original')
        c=clone(db)
        for table in ('pd_cut','pd_cut_commit','crp_member'):
            for t in c.execute("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name=? AND sql LIKE '%BEFORE UPDATE%'",(table,)).fetchall():c.execute('DROP TRIGGER '+t[0])
        bad=copy.deepcopy(source);bad['retirements'][0]['adoption_ref']['digest']=R.digest('wrong');encoded=R.raw(bad);pid=R.one(c,"SELECT prepare_cut_id FROM cc_cut WHERE cut_id='all'")['prepare_cut_id']
        c.execute('UPDATE pd_cut SET selector_body=?,selector_digest=? WHERE cut_id=?',(encoded,R.digest(bad),pid));c.execute('UPDATE pd_cut_commit SET audit_body=?,outbox_body=? WHERE cut_id=?',(encoded,encoded,pid));b=R.raw(bad['retirements'][0]);c.execute('UPDATE crp_member SET body=?,audit_body=?',(b,b))
        denied('重算摘要和seal仍拒绝错采用原件',lambda:N.transaction(c,lambda:C.read_cut(c,'all')),'retired_cancel_proof_binding')
        first,others,firstv=fixture(ordinary=False);connections.extend(others);connections.append(first)
        ordinary,_=R.capture(first,'cancel','ordinary','ordinary',firstv['refs'],firstv['context']);check('受理后先退役仍能封存ordinary',ordinary['stage']=='ordinary' and ordinary['previous_cut_ref'] is None and N.transaction(first,lambda:R.read(first,ordinary,live=True))['retirements'])
        recovery(db,v);sources=N.transaction(db,lambda:S.for_open(db,'full.recovery','full.fence','27'))
        check('276表恢复链双非空拒绝来源',len(state(db))==276 and len(sources['run_deny_snapshot']['entries'])==len(sources['command_deny_snapshot']['entries'])==1)
        check('未创建最终OPEN计划',not db.execute("SELECT 1 FROM go_plan WHERE snapshot_id='full.snapshot'").fetchone())
        X.R.revoke(db,'exit_dev_1',dict(reason='synthetic_after_cut'))
        check('撤回仍可读取历史切点与拒绝快照',N.transaction(db,lambda:C.read_cut(db,'all'))==cut and N.transaction(db,lambda:S.read(db,'command.full'))==sources['command_deny_snapshot'])
        check('撤回后的同ID重入不复活',capture(db)==(cut,[]))
        denied('撤回阻止当前准备资格',lambda:N.transaction(db,lambda:R.read(db,cut,live=True)),'retired_cancel_not_current')
        denied('撤回阻止恢复OPEN前态',lambda:N.transaction(db,lambda:S.for_open(db,'full.recovery','full.fence','27')))
        # 独立负例：即使上游前态被固定为曾经有效，命令来源也必须重查自己的退役资格。
        with patch.object(S.R,'for_open',return_value=copy.deepcopy(sources)):
            denied('命令侧不依赖上游替代退役资格检查',lambda:N.transaction(db,lambda:S.for_open(db,'full.recovery','full.fence','27')),'retired_cancel_not_current')
        for c in connections:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        return checks
    finally:
        for c in connections:c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'retired-cancel-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();v=dict(all_passed=True,approved=False,cases_passed=len(checks),integrated_controller_tables=276,cross_domain_cancel_preparation_verified=True,integrated_nonempty_open_sources_verified=True,full_open_verified=False,provider_authenticity_verified=False,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(R.raw(v))
        print(json.dumps({k:v for k,v in v.items() if k not in ('checks','inputs')}))
