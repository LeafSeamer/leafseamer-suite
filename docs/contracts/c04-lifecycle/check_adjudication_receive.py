"""完整裁决接收、迟到结果和保护预算的内存SQLite验收。"""
import argparse,copy,hashlib,json,sqlite3
from unittest.mock import patch
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import check_typed_controller as TC
import adjudication_receive_model as M
import check_arm_budget as AB
G=M.G;CM=TC.M;SC=TC.SC;R=M.R;P=M.P;HERE=G.HERE;ROOT=TC.ROOT

def observation(db,item,source='lookup',result=None,oid='observation.1'):
    cd,identity,request,auth,provider=item
    s=P.rows(db,'SELECT * FROM command_submission WHERE request_key_body=?',(M.raw(identity['key']),))[0]
    if source in ('create_response','lookup') and result is None:result=CM.lookup(cd,identity,auth)
    o=dict(observation_id=oid,submission_id=s['submission_id'],source=source,identity=copy.deepcopy(identity),result=result)
    a=result['adjudication'] if result and result['state']=='found' else None
    evidence=dict(trusted_provider=True,provider_ref='synthetic_controller_observer',identity=copy.deepcopy(identity),attempt_id=s['attempt_id'],
        observation_digest=M.digest(o),authenticated=True,controller_scope=identity['key']['target_scope'],
        durable_record_verified=bool(a),record_digest=a['adjudication_digest'] if a else None)
    return o,evidence

def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fresh(large_profile=True,record_attempts=True):
        profile=AB.profile()
        if large_profile:profile.update(profile_id='sim-typed-receive',max_row_bytes='131072')
        # 初始化前提供不同的合成配置，全部预留摘要重新生成；不改已持久预算或任何守卫。
        with patch.object(AB,'profile',return_value=profile):
            d,cds,items,ctx=TC.fixture(sql_factory=G.build,include_context=True,record_attempts=record_attempts)
        dbs.extend([d]+[x[0] for x in cds.values()]);ctx['observer_authorized']=True
        return d,items,ctx
    def denied(name,d,fn,reason=None):
        before=SC.snapshot(d)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError) as err:
            if reason:assert reason in str(err),(name,str(err))
            check(name,SC.snapshot(d)==before and not d.in_transaction);return
        raise AssertionError(name)
    def state(d,o):
        s=R.one(d,'command_submission','submission_id',o['submission_id'])
        return s,M.F.F.step(d,s['execution_id'],s['step_id'])
    def accept(item):return CM.decide(*item)
    def reject(item):
        cd,identity,request,auth,provider=item
        return CM.decide(cd,identity,CM.B.content(request),auth,operation='reject_original')
    def replay_writes(d,o,e,c,label):
        before=SC.snapshot(d);writes=M.receive(d,o,e,c,preview=True)
        check(label+'预览回滚',SC.snapshot(d)==before)
        for i in range(len(writes)):
            denied(label+'写后故障'+str(i),d,lambda i=i:M.receive(d,o,e,c,fail_after=i),'injected')
            denied(label+'漏写'+str(i),d,lambda i=i:SC.execute(d,writes[:i]+writes[i+1:]))
        return writes
    try:
        check('组合DDL可重现',(HERE/'seamer-adjudication-receive.sql').read_bytes()==G.build())
        check('Schema可重现',(HERE/'adjudication-receive.schema.json').read_bytes()==G.C.raw(G.schema()))
        Draft202012Validator.check_schema(G.schema())
        narrow,ni,nc=fresh(large_profile=False);no,ne=observation(narrow,ni[0])
        denied('旧16KiB包络拒绝完整保护',narrow,lambda:M.receive(narrow,no,ne,nc),'protection_charge_binding_or_capacity')
        planned,pi,pc=fresh(record_attempts=False);po,pe=observation(planned,pi[0])
        denied('无attempt不能登记运输观察',planned,lambda:M.receive(planned,po,pe,pc),'attempt_original')
        d,items,c=fresh();check('Seamer123表',len(SC.snapshot(d))==123)
        for idx,item in enumerate(items):
            a=accept(item);o,e=observation(d,item,source='create_response',oid='accepted.'+str(idx))
            if idx==0:
                replay_writes(d,o,e,c,'受理')
                for key in ('trusted_provider','authenticated','durable_record_verified'):
                    denied('提供者拒绝'+key,d,lambda key=key:M.receive(d,o,dict(e,**{key:False}),c))
                denied('观察者当前失权',d,lambda:M.receive(d,o,e,dict(c,observer_authorized=False)),'observer_authority')
                for key,val in [('attempt_id','wrong'),('record_digest',M.digest('wrong')),('observation_digest',M.digest('wrong'))]:
                    denied('证据错绑'+key,d,lambda key=key,val=val:M.receive(d,o,dict(e,**{key:val}),c))
                for key in ('issuer_epoch','idempotency_key'):
                    wrong=copy.deepcopy(o);wrong['identity']['key'][key]='wrong'
                    denied('请求身份错绑'+key,d,lambda wrong=wrong:M.receive(d,wrong,dict(e,observation_digest=M.digest(wrong)),c),'observation_identity')
                wrong=copy.deepcopy(o);wrong['result']['adjudication']['commit_ref']['scope']['database_instance_id']='wrong'
                wa=wrong['result']['adjudication'];wa['adjudication_digest']=M.digest({k:v for k,v in wa.items() if k!='adjudication_digest'})
                denied('重摘要跨Controller引用',d,lambda:M.receive(d,wrong,dict(e,record_digest=wa['adjudication_digest'],observation_digest=M.digest(wrong)),c),'adjudication_scope_revision')
                wrong=copy.deepcopy(o);wrong['result']['adjudication']['adjudication_digest']=M.digest('wrong')
                denied('不匹配裁决正文',d,lambda:M.receive(d,wrong,dict(e,record_digest=M.digest('wrong'),observation_digest=M.digest(wrong)),c),'adjudication_digest')
            check('完整接受落库'+str(idx),M.receive(d,o,e,c)=='recorded')
            s,st=state(d,o);stored=R.one(d,'submission_adjudication','submission_id',s['submission_id'])
            check('完整原件与引用保持'+str(idx),json.loads(stored['receipt_body'])==a and json.loads(stored['command_ref_body'])==a['command_ref'])
            check('受理不是完成'+str(idx),s['state']=='accepted' and st['state']=='accepted' and st['outcome']=='pending')
            before=SC.snapshot(d);check('同观察零写'+str(idx),M.receive(d,o,e,c)=='existing' and SC.snapshot(d)==before)
            wrong=dict(o,source='lookup')
            denied('同观察身份异正文'+str(idx),d,lambda:M.receive(d,wrong,dict(e,observation_digest=M.digest(wrong)),c),'observation_conflict')
        check('双受理没有业务提交',d.execute('SELECT count(*) FROM step_terminal WHERE execution_id=?',(s['execution_id'],)).fetchone()[0]==0)
        o,e=observation(d,items[0],source='transport_timeout',oid='late.timeout')
        M.receive(d,o,e,c);s,st=state(d,o)
        check('迟到超时不降级已受理',s['state']=='accepted' and st['outcome']=='pending' and st['state']=='accepted')
        o,e=observation(d,items[0],oid='repeat.found');M.receive(d,o,e,c)
        check('新观察不重复持久裁决',d.execute('SELECT count(*) FROM submission_adjudication').fetchone()[0]==2)
        wrong=copy.deepcopy(o);wrong['observation_id']='conflicting.receipt';a=wrong['result']['adjudication'];a['adjudication_id']='other'
        a['adjudication_digest']=M.digest({k:v for k,v in a.items() if k!='adjudication_digest'})
        denied('同请求异裁决拒绝',d,lambda:M.receive(d,wrong,dict(e,observation_digest=M.digest(wrong),record_digest=a['adjudication_digest']),c),'adjudication_conflict')
        for source in ('lookup','transport_timeout','transport_error','indeterminate','reject'):
            d,items,c=fresh();item=items[0]
            if source=='reject':reject(item)
            o,e=observation(d,item,source=source if source in ('lookup','transport_timeout','transport_error') else 'lookup',
                result=dict(state='indeterminate',adjudication=None) if source=='indeterminate' else None)
            if source in ('lookup','reject'):replay_writes(d,o,e,c,source)
            before=M.IB.C.snapshot(d);check(source+'事务提交',M.receive(d,o,e,c)=='recorded')
            s,st=state(d,o);run=R.one(d,'run','run_id',s['run_id'])
            check(source+'结果边界',s['state']==('rejected' if source=='reject' else 'indeterminate') and st['outcome']==('failed' if source=='reject' else 'unknown'))
            check(source+'暂停保留活动执行',run['lifecycle']=='paused' and run['dispatch_eligible']==0 and run['active_execution_id']==s['execution_id'])
            check(source+'完整双目标保护',d.execute('SELECT count(*) FROM sf_target').fetchone()[0]==2 and c['protection_confirmation']=='durable')
            uses=P.rows(d,'SELECT * FROM pb_use WHERE plan_id=?',(st['terminal_id']+'.protection',))
            check(source+'保护账户消费',bool(uses))
            measurement=json.loads(uses[0]['measurement_body']);after=M.IB.C.snapshot(d)
            changed=[(t,b) for t in after for b in after[t]-before.get(t,set()) if t not in ('pb_use','pb_commit')]
            nseal=len(after['pb_commit']-before['pb_commit']);nuse=len(after['pb_use']-before['pb_use'])
            check(source+'封存与观察纳入实测',measurement['changed_tables']['sa_commit']==1 and measurement['changed_tables']['sa_observation']==1)
            check(source+'计量与实际差集一致',measurement['rows']==len(changed)+nuse+nseal and measurement['bytes']==sum(len(b) for _,b in changed)+8192*nuse+4096*nseal)
            snapshot=SC.snapshot(d);check(source+'重复观察零写',M.receive(d,o,e,c)=='existing' and SC.snapshot(d)==snapshot)
            if source!='reject':
                terminal=copy.deepcopy(st);budget=after['pb_use'];original_run=copy.deepcopy(run)
                if source=='transport_error':reject(item)
                else:accept(item)
                late,le=observation(d,item,oid='late.found');M.receive(d,late,le,c);s,st=state(d,late)
                check(source+'迟到裁决只补历史',st==terminal and R.one(d,'run','run_id',s['run_id'])==original_run and M.IB.C.snapshot(d)['pb_use']==budget)
                check(source+'迟到原件落库',s['state']==('rejected' if source=='transport_error' else 'accepted'))
            denied(source+'禁止R5',d,lambda:TC.X.T.F.finish(d,s['execution_id'],c))
            if source=='lookup':
                accept(items[1]);other,oe=observation(d,items[1],oid='parallel.accepted');M.receive(d,other,oe,c)
                check('并行动作迟到受理不解除暂停',state(d,other)[1]['state']=='accepted' and R.one(d,'run','run_id',s['run_id'])['lifecycle']=='paused')
        d,items,c=fresh();o,e=observation(d,items[0])
        for flag in ('trusted_system_closer','volatile_close_verified','clock_wait_verified'):
            denied('保护证据不足'+flag,d,lambda flag=flag:M.receive(d,o,e,dict(c,**{flag:False})))
        c['protection_confirmation']='durable'
        denied('早期异常确认重置',d,lambda:M.receive(d,o,e,c,fail_after=0),'injected')
        check('失败不能保留旧durable',c['protection_confirmation']=='unconfirmed')
        M.receive(d,o,e,dict(c,authorized=False));check('人员失权不阻可信系统保护',state(d,o)[1]['outcome']=='unknown')
        for table in ('sa_observation','sa_commit'):
            for action in ('DELETE FROM '+table,'UPDATE '+table+' SET observation_id=observation_id'):
                denied('观察不可变'+action,d,lambda action=action:SC.execute(d,[(action,())]))
        for source,result in [('create_response',dict(state='not_found',adjudication=None)),('lookup',None),('transport_timeout',dict(state='not_found',adjudication=None))]:
            wrong=dict(o,source=source,result=result)
            check('Schema拒绝错误结果'+source,not Draft202012Validator(G.schema()).is_valid(wrong))
        for i,db in enumerate(dbs):check('外键完整'+str(i),not db.execute('PRAGMA foreign_key_check').fetchone())
        return checks
    finally:
        for db in dbs:db.close()

def inputs():
    names=['typed-controller-report.json','adjudication-receive.schema.json','adjudication-receive.sql','seamer-adjudication-receive.sql','adjudication_receive_model.py','check_adjudication_receive.py','ADJUDICATION_RECEIVE.md']
    return list(dict.fromkeys(TC.inputs()+G.SOURCES+[HERE/n for n in names]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};path=HERE/'adjudication-receive-report.json'
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=123,controller_tables=237,production_clearance=False,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(G.C.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
