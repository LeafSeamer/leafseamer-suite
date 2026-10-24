"""完整初始记录、排队终态与权限隔离；内存SQLite，不运行服务和设备。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_adjudication_receive as AR
import typed_command_view_model as M
G=M.G;TC=AR.TC;SC=TC.SC;R=M.R;P=M.P;I=M.I;HERE=G.HERE;ROOT=TC.ROOT

def fixture():
    d,cds,items,c=TC.fixture(controller_factory=G.build,include_context=True)
    for cd,identity,request,auth,provider in items:
        actor={k:identity['key'][k] for k in ('principal_id','issuer_id','issuer_epoch')}
        actor.update(session_id='synthetic.service.session',authorization_revision='1',local_subject_id='synthetic.subject')
        provider['public_view']=dict(actor=actor,actor_verified=True,accepted_time_verified=True,deadline_verified=True,accepted_at='2026-10-24T00:00:00.000Z',
            original_deadline=dict(dispatch=copy.deepcopy(request['dispatch']),clock_domain_id='synthetic.clock',descriptor_digest=M.digest('synthetic.clock'),anchor_tick='1000000',deadline_tick='2000000'))
    return d,cds,items,c
def reader(item,kind='service'):
    cd,identity,request,auth,provider=item
    return dict(authenticated=True,authorization_current=True,response_authorized=True,storage_readable=True,permissions=['command.read'],subject_kind=kind,
        scope=identity['key']['target_scope'],allowed_devices=[request['device_id']],paired=True,service_scope=auth['origin_scope'])
def stop_proof(v):return dict(trusted_provider=True,future_writes_closed=True,state_ref=v['state_ref'],scope=v['scope'],original_deadline_ref=v['policy']['original_deadline_ref'],deadline_elapsed=True,provider_ref='synthetic.supervisor')

def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def fresh():
        d,cds,items,c=fixture();dbs.extend([d]+[x[0] for x in cds.values()]);return items
    def denied(n,d,fn,reason=None):
        before=SC.snapshot(d)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError) as err:
            if reason:assert reason in str(err),(n,str(err))
            check(n,SC.snapshot(d)==before and not d.in_transaction);return
        raise AssertionError(n)
    try:
        check('组合DDL可重现',(HERE/'controller-command-view.sql').read_bytes()==G.build())
        items=fresh();cd,identity,request,auth,provider=items[0]
        check('保持237表',len(SC.snapshot(cd))==237)
        ns=M.C.authorize(cd,identity['key'],auth,'submit')
        writes=TC.AT.planned(cd,lambda:M.C.creation_steps(cd,identity,M.C.B.content(request),ns,request,provider,initial_factory=M.initial_rows)[0])
        for i in range(len(writes)):
            denied('完整记录受理写后异常'+str(i),cd,lambda i=i:M.decide(cd,identity,request,auth,provider,fail_after=i),'injected')
            denied('完整记录受理漏写'+str(i),cd,lambda i=i:SC.execute(cd,writes[:i]+writes[i+1:]))
        denied('旧简化投影不可进入新布局',cd,lambda:M.C.decide(cd,identity,request,auth,provider),'typed_state_columns')
        for field in ('actor_verified','accepted_time_verified','deadline_verified'):
            wrong=copy.deepcopy(provider);wrong['public_view'][field]=False
            denied('公开元数据证据'+field,cd,lambda wrong=wrong:M.decide(cd,identity,request,auth,wrong),'public_metadata_provider')
        wrong=copy.deepcopy(provider);wrong['public_view']['actor']['issuer_epoch']='other'
        denied('原actor不能重绑',cd,lambda:M.decide(cd,identity,request,auth,wrong),'public_actor_owner')
        wrong=copy.deepcopy(provider);wrong['public_view']['accepted_at']='not-a-time'
        denied('接收时间结构无效',cd,lambda:M.decide(cd,identity,request,auth,wrong))
        wrong=copy.deepcopy(provider);wrong['public_view']['original_deadline']['dispatch']={'mode':'immediate','max_queue_ms':1}
        denied('原deadline不得借新排期',cd,lambda:M.decide(cd,identity,request,auth,wrong),'original_deadline_binding')
        denied('SQL状态正文不匹配',cd,lambda:SC.execute(cd,SC.mutate(writes,'cm_revision',dict(state_body=b'{}'))),'typed_state_columns')
        denied('SQL公开正文缺字段',cd,lambda:SC.execute(cd,SC.mutate(writes,'cv_record',dict(record_body=b'{}'))),'typed_public_record')
        for item in items:
            d,identity,request,auth,provider=item;a=M.decide(*item);command=a['command_ref']['object_id'];rc=reader(item)
            before=SC.snapshot(d);result=M.read(d,command,rc);v=result['record'];M.validate('CommandRead',result)
            check('完整公开记录Schema'+command,result['view']=='current' and SC.snapshot(d)==before)
            check('原受理引用与公开修订摘要分开'+command,v['initial_command_ref']==a['command_ref'] and v['record_digest']!=a['command_ref']['digest'])
            check('受理仅queued无完成'+command,v['state']['outcome']=='pending' and v['completion']['achieved'] is None and v['attempts']==[])
            check('固定原actor和时间'+command,v['actor']==provider['public_view']['actor'] and v['accepted_at']==provider['public_view']['accepted_at'])
            h=M.read(d,command,reader(item,'human'),'1');check('当前有权人员可读历史'+command,h==dict(view='historical',record=v))
            transfer=request['automation_binding']['continuation']['transfer_ref']['id']
            SC.execute(d,[I('cr_revocation',transfer_id=transfer,proof_body=b'{"synthetic":true}',audit_body=b'{}',outbox_body=b'{}')])
            check('grant撤回不删除历史且读仍需当前权'+command,M.read(d,command,rc,'1')==h)
            for field in ('authenticated','authorization_current','response_authorized','storage_readable','paired'):
                denied('读取资格'+field+command,d,lambda field=field:M.read(d,command,dict(rc,**{field:False})))
            denied('无读取权限'+command,d,lambda:M.read(d,command,dict(rc,permissions=[])),'read_authority')
            denied('其他设备权限'+command,d,lambda:M.read(d,command,dict(reader(item,'human'),allowed_devices=[])),'device_scope')
            denied('其他Seamer来源'+command,d,lambda:M.read(d,command,dict(rc,service_scope=dict(authority_service_id='other',database_instance_id='db'))),'service_origin')
            denied('其他目标库'+command,d,lambda:M.read(d,command,dict(rc,scope=dict(authority_service_id='other',database_instance_id='db'))),'read_authority')
            denied('非法修订词法'+command,d,lambda:M.read(d,command,rc,'01'),'revision_format')
            denied('不存在历史修订'+command,d,lambda:M.read(d,command,rc,'9'),'not_found')
            # 读取者不向writer正在进行的事务泄露尚未提交的候选。
            d.execute('BEGIN')
            try:
                try:M.read(d,command,rc)
                except ValueError as err:check('拒绝事务内响应'+command,'read_requires_committed_snapshot' in str(err))
                else:raise AssertionError('transaction read')
            finally:d.rollback()
            # 模拟本地风险视图暂时遮蔽；不将该实验视作真实release撤回链验证。
            d.execute('BEGIN');d.execute('DROP VIEW cv_current');d.execute('CREATE VIEW cv_current AS SELECT * FROM cv_history WHERE 0');d.commit()
            denied('current遮蔽不能回退max修订'+command,d,lambda:M.read(d,command,rc),'state_projection_pending')
            check('遮蔽仍可明确历史读取'+command,M.read(d,command,rc,'1')==h)
            d.execute('DROP VIEW cv_current');d.execute('CREATE VIEW cv_current AS SELECT p.* FROM cv_history p JOIN cm_current s USING(command_id,revision)')
            # 新终态完整记录同事务；原初始ref和旧公开正文不改。
            proof=stop_proof(v);kind='block' if item is items[0] else 'expire'
            steps=TC.AT.planned(d,lambda:M.stop_steps(d,command,kind,v['state_ref'],proof))
            for n in range(len(steps)):
                denied('终态漏写'+str(n)+command,d,lambda n=n:SC.execute(d,steps[:n]+steps[n+1:]))
                denied('终态写后异常'+str(n)+command,d,lambda n=n:M.C.T.apply(d,lambda:M.stop_steps(d,command,kind,v['state_ref'],proof),fail_after=n),'injected')
            denied('缺未来写关闭证明'+command,d,lambda:M.C.T.apply(d,lambda:M.stop_steps(d,command,kind,v['state_ref'],dict(proof,future_writes_closed=False))),'stop_provider')
            denied('错原截止依据'+command,d,lambda:M.C.T.apply(d,lambda:M.stop_steps(d,command,kind,v['state_ref'],dict(proof,original_deadline_ref=M.ref('wrong',{})))),'stop_original_binding')
            if kind=='expire':denied('未到原截止不能过期',d,lambda:M.C.T.apply(d,lambda:M.stop_steps(d,command,kind,v['state_ref'],dict(proof,deadline_elapsed=False))),'deadline_unproven')
            M.C.T.apply(d,lambda:M.stop_steps(d,command,kind,v['state_ref'],proof));current=M.read(d,command,rc)['record']
            check('完整终态不伪造成功'+command,current['revision']=='2' and current['state']['outcome']==('blocked' if kind=='block' else 'expired') and current['state']['automation_continuation']=='paused_latched' and current['completion']['achieved'] is None)
            check('历史初始记录不可变'+command,M.read(d,command,rc,'1')==h and current['initial_command_ref']==v['initial_command_ref'])
            check('历史策略及原deadline不刷新'+command,current['policy']==v['policy'] and current['dispatch']==v['dispatch'])
            denied('终态不可再阻断或复活'+command,d,lambda:M.C.T.apply(d,lambda:M.stop_steps(d,command,'block',current['state_ref'],stop_proof(current))),'stop_prestate')
            for table,column in [('cv_record','record_body'),('cv_metadata','metadata_body'),('cm_policy','policy_body')]:
                denied('公开原件不可更新'+table+command,d,lambda table=table,column=column:SC.execute(d,[(f'UPDATE {table} SET {column}=?',(b'{}',))]))
        # 永久拒收仍不生成命令公开记录。
        item=fresh()[0];d,i,q,a,p=item;reject=M.decide(d,i,M.C.B.content(q),a,operation='reject_original')
        check('墓碑没有伪命令记录',reject['decision']=='rejected' and d.execute('SELECT count(*) FROM cv_record').fetchone()[0]==0)
        for idx,d in enumerate(dbs):check('外键完整'+str(idx),not d.execute('PRAGMA foreign_key_check').fetchone())
        return checks
    finally:
        for d in dbs:d.close()

def inputs():
    return list(dict.fromkeys(AR.inputs()+G.SOURCES+[HERE/n for n in ('adjudication-receive-report.json','controller-command-view.sql','typed_command_view_model.py','check_typed_command_view.py','TYPED_COMMAND_VIEW.md','attempt_projection_model.py','build_attempt_projection.py','attempt-projection.schema.json','command_evidence_model.py')]+[HERE.parent/'c02-command-view/reference_model.py']))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};path=HERE/'typed-command-view-report.json'
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=237,production_clearance=False,all_lifecycle_writers_typed=False,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(G.C.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
