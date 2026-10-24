"""由实际Seamer请求进入独立Controller受理及查原；仅合成证据与内存SQLite。"""
import argparse,copy,hashlib,json,sqlite3
from pathlib import Path
from jsonschema.exceptions import ValidationError
import check_atomic_ingress as A
import typed_controller_model as M
import build_typed_controller as G
X=A.X;I=X.I;C=X.C;R=X.R;P=X.P;SC=X.SC;AT=X.AT;HERE=G.HERE;ROOT=X.ROOT

def fixture(*,sql_factory=A.G.build,include_context=False,record_attempts=True):
    d,q,cds,ctx=X.fixture(sql_factory=sql_factory,controller_factory=G.build,expected_control=dict(epoch='control.epoch',version='2'))
    ns=ctx['command_namespace'];owner={k:ns[k] for k in M.OWNER}
    for cd,cc in cds.values():
        SC.execute(cd,[I('ca_namespace',namespace_id='typed_namespace',scope_id=1,**owner,owner_evidence_id='synthetic_owner',owner_evidence_body=M.raw(dict(synthetic=True)))])
    A.M.receive_event(d,X.T.W.event(12),ctx);ex=X.T.active(d);C.tx(d,lambda:X.T.F.anchor_steps(d,ex,ctx))
    requests=[]
    for step in ['step.0','step.1']:
        C.tx(d,lambda step=step:X.T.F.ready_steps(d,ex,step,ctx));X.M.submit(d,ex,step,ctx)
        sid=X.T.F.step(d,ex,step)['submission_id']
        if record_attempts:X.T.F.attempt(d,sid,ctx)
        s=R.one(d,'command_submission','submission_id',sid);request=json.loads(s['request_body']);key=json.loads(s['request_key_body']);cd,cc=cds[(s['target_authority'],s['target_database'])]
        e=R.one(d,'execution','execution_id',ex);q,adoption,receipts=X.M.originals(d,e['run_id'],e['arm_generation'])
        auth=dict(authenticated=True,permissions=dict(submit=True,reject=True,lookup=True),historical_owner_verified=True,read_scope_verified=True,target_scope=key['target_scope'],owner=owner,
          storage_readable=True,capacity_reserved=True,namespace_writable=True,principal_kind='service',peer_kind='seamer',origin_scope=q['origin_scope'],context_id=request['context_id'],response_authorized=True,
          actor={k:owner[k] for k in ('issuer_id','issuer_epoch','principal_id')},rejection_evidence=dict(synthetic=True,permission='reject'))
        provider=dict(execution=json.loads(e['binding_body']),adoption=adoption,receipts=receipts,plan=json.loads(R.one(d,'execution_plan_set','execution_id',ex)['plan_body']),definition_version='1',
          policies=dict(release_ref='synthetic_release',release=dict(synthetic=True),completion_ref='synthetic_completion',completion=dict(synthetic=True)),
          capacity=dict(profile=dict(synthetic=True),dimensions=dict(synthetic=True)),initial_state_evidence=dict(provider_ref='synthetic_state',synthetic=True))
        provider.update({k:True for k in ('authorization_current','control_current','source_current','time_current','budget_current','adoption_current','r5_committed','execution_original_verified','plan_original_verified')})
        requests.append((cd,dict(key=key,request_digest=s['request_digest']),request,auth,provider))
    return (d,cds,requests,ctx) if include_context else (d,cds,requests)

def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def fresh():
        d,cds,requests=fixture();dbs.extend([d]+[x[0] for x in cds.values()]);return requests
    def denied(n,db,fn,reason=None):
        before=SC.snapshot(db)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError) as err:
            if reason:assert reason in str(err),(n,str(err))
            check(n,SC.snapshot(db)==before and not db.in_transaction);return
        raise AssertionError(n)
    try:
        check('生成布局一致',(HERE/'controller-typed.sql').read_bytes()==G.build())
        requests=fresh();cd,identity,request,auth,provider=requests[0];key=identity['key']
        check('Controller237表',len(SC.snapshot(cd))==237)
        check('未找到不等于拒收',M.lookup(cd,identity,auth)==dict(state='not_found',adjudication=None))
        check('存储不可读返回不确定',M.lookup(cd,identity,dict(auth,storage_readable=False))==dict(state='indeterminate',adjudication=None))
        for action in ('lookup','submit','reject'):
            wrong=copy.deepcopy(auth);wrong['permissions'][action]=False
            fn=(lambda:M.lookup(cd,identity,wrong)) if action=='lookup' else (lambda:M.decide(cd,identity,request if action=='submit' else M.B.content(request),wrong,provider,operation=None if action=='submit' else 'reject_op'))
            denied('当前权限拒绝'+action,cd,fn,'authority')
        for field in M.OWNER:
            wrong=copy.deepcopy(identity);wrong['key'][field]='other'
            denied('历史身份拒绝'+field,cd,lambda wrong=wrong:M.lookup(cd,wrong,auth),'historical_owner')
        wrong=copy.deepcopy(auth);wrong['origin_scope']=dict(authority_service_id='other',database_instance_id='db')
        denied('服务来源不可借用',cd,lambda:M.decide(cd,identity,request,wrong,provider),'service_origin_scope')
        for flag in ('authorization_current','control_current','source_current','time_current','budget_current','adoption_current','r5_committed','execution_original_verified','plan_original_verified'):
            p=dict(provider,**{flag:False});denied('新受理门槛'+flag,cd,lambda p=p:M.decide(cd,identity,request,auth,p),flag)
        p=copy.deepcopy(provider);p['adoption']['adoption_digest']=M.digest('wrong')
        denied('采用原件摘要不可伪造',cd,lambda:M.decide(cd,identity,request,auth,p),'adoption_digest')
        wrong=copy.deepcopy(request);wrong['parameters']['value']=99
        denied('摘要错误拒绝',cd,lambda:M.decide(cd,identity,wrong,auth,provider),'request_digest')
        wi=dict(identity,request_digest=M.digest(M.B.content(wrong)))
        denied('重新摘要仍不匹配固定计划',cd,lambda:M.decide(cd,wi,wrong,auth,provider),'fixed_command')
        content=M.B.content(request);ns=M.authorize(cd,key,auth,'submit')
        writes=AT.planned(cd,lambda:M.creation_steps(cd,identity,content,ns,request,provider)[0])
        for i in range(len(writes)):
            denied('受理写后异常'+str(i),cd,lambda i=i:M.decide(cd,identity,request,auth,provider,fail_after=i),'injected')
            denied('受理缺写'+str(i),cd,lambda i=i:SC.execute(cd,writes[:i]+writes[i+1:]))
        badkey=copy.deepcopy(key);badkey['issuer_epoch']='other'
        denied('SQL错epoch',cd,lambda:SC.execute(cd,SC.mutate(writes,'ca_request_key',dict(request_key_body=M.raw(badkey)))),'typed_request_key')
        denied('SQL运输字段不能进入内容',cd,lambda:SC.execute(cd,SC.mutate(writes,'ca_request_key',dict(content_body=M.raw(request)))),'typed_request_key')
        first=M.decide(cd,identity,request,auth,provider);M.S.validate('RequestAdjudication',first)
        check('完整请求本地受理',first['decision']=='accepted')
        initial=R.one(cd,'ca_command_initial','command_id',first['command_ref']['object_id']);commit=R.one(cd,'ca_commit','commit_id',first['commit_ref']['object_id'])
        check('命令Ref绑定实际初始原件',first['command_ref']['digest']==initial['command_digest']==M.digest(json.loads(initial['command_body'])))
        check('提交Ref绑定实际创建正文',first['commit_ref']['digest']==M.digest(json.loads(commit['commit_body'])))
        for table,column in [('ca_request_key','content_body'),('ca_adjudication','adjudication_body'),('typed_command_source','execution_body')]:
            denied('已封存原件不可改'+table,cd,lambda table=table,column=column:SC.execute(cd,[(f'UPDATE {table} SET {column}=?',(b'{}',))]),'immutable')
        keyrow=R.one(cd,'ca_request_key','key_id',M.uid('key',key));check('原始运输正文与内容分开保存',keyrow['transport_body']==M.raw(request) and keyrow['content_body']==M.raw(content) and keyrow['request_digest']==M.digest(content))
        check('查原返回持久裁决',M.lookup(cd,identity,auth)['adjudication']==first)
        denied('查原响应阶段失权',cd,lambda:M.lookup(cd,identity,dict(auth,response_authorized=False)),'response_authority')
        before=SC.snapshot(cd);replay=dict(request,correlation_id='new_correlation')
        check('同内容重试零写并保留首次运输',M.decide(cd,identity,replay,dict(auth,namespace_writable=False),None)==first and SC.snapshot(cd)==before)
        denied('同键异内容不能二次受理',cd,lambda:M.decide(cd,wi,wrong,auth,provider),'identity_conflict')
        denied('接受后拒收也须保护容量',cd,lambda:M.decide(cd,identity,content,dict(auth,capacity_reserved=False),operation='reject_capacity'),'capacity')
        check('接受后拒收返回原裁决不取消',M.decide(cd,identity,content,auth,operation='reject_accepted')==first)
        before=SC.snapshot(cd);check('同拒收操作幂等零写',M.decide(cd,identity,content,auth,operation='reject_accepted')==first and SC.snapshot(cd)==before)
        sc,si,sr,sa,sp=requests[1];second=M.decide(sc,si,sr,sa,sp)
        check('另一Controller独立完整受理',second['decision']=='accepted' and second['identity']['key']['target_scope']!=key['target_scope'])
        # 撤销后禁止新命令；历史裁决仍可在当前读取权限下查询。
        transfer=request['automation_binding']['continuation']['transfer_ref']['id']
        SC.execute(cd,[I('cr_revocation',transfer_id=transfer,proof_body=M.raw(dict(synthetic=True)),audit_body=b'{}',outbox_body=b'{}')])
        before=SC.snapshot(cd);check('撤权后查原零写',M.decide(cd,identity,request,auth,None)==first and SC.snapshot(cd)==before)
        newer=copy.deepcopy(identity);newer['key']['idempotency_key']='new_key';newreq=dict(request,idempotency_key='new_key')
        denied('撤权后新受理拒绝',cd,lambda:M.decide(cd,newer,newreq,auth,provider))
        denied('撤权后原命令不能建attempt',cd,lambda:SC.execute(cd,[I('ce_attempt',attempt_id='attempt_new',command_id=first['command_ref']['object_id'],authorization_body=b'{}',attempt_body=b'{}')]),'continuation_command_revoked')
        rejected=fresh()[0];rd,ri,rr,ra,rp=rejected;rc=M.B.content(rr)
        SC.execute(rd,[I('ca_namespace_closure',namespace_id='typed_namespace',protection_operation_id='closed',closure_body=b'{}')])
        denied('关闭命名空间拒绝新受理',rd,lambda:M.decide(rd,ri,rr,ra,rp),'namespace_closed')
        for i in range(6):denied('墓碑写后故障'+str(i),rd,lambda i=i:M.decide(rd,ri,rc,ra,operation='reject_new',fail_after=i),'injected')
        tomb=M.decide(rd,ri,rc,ra,operation='reject_new');check('关闭后永久墓碑仍可写',tomb['decision']=='rejected' and tomb['command_ref'] is None)
        before=SC.snapshot(rd);check('迟到提交只返回墓碑',M.decide(rd,ri,rr,ra,None)==tomb and SC.snapshot(rd)==before)
        other=copy.deepcopy(ri);other['key']['idempotency_key']='other'
        denied('拒收操作不能重绑其他键',rd,lambda:M.decide(rd,other,rc,ra,operation='reject_new'),'rejection_conflict')
        rotated=copy.deepcopy(ri);rotated['key']['issuer_epoch']='issuer-2';rotated_auth=copy.deepcopy(ra)
        rotated_auth['owner']['issuer_epoch']='issuer-2';rotated_auth['actor']['issuer_epoch']='issuer-2'
        SC.execute(rd,[I('ca_namespace',namespace_id='rotated_namespace',scope_id=1,**rotated_auth['owner'],owner_evidence_id='rotated_owner',owner_evidence_body=b'{}')])
        second_tomb=M.decide(rd,rotated,rc,rotated_auth,operation='reject_new')
        check('新issuer代次同幂等键为独立身份',second_tomb!=tomb and rd.execute('SELECT count(*) FROM ca_request_key').fetchone()[0]==2)
        check('旧代次墓碑未改',M.lookup(rd,ri,ra)['adjudication']==tomb)
        ld,li,lr,la,lp=fresh()[0]
        try:M.decide(ld,li,lr,dict(la,response_authorized=False),lp)
        except ValueError as err:check('提交后失去响应权限不返回正文','response_authority' in str(err))
        else:raise AssertionError('response_authority')
        check('响应失败后仍能查原且只一个命令',M.lookup(ld,li,la)['state']=='found' and ld.execute('SELECT count(*) FROM ca_adjudication').fetchone()[0]==1)
        for n,db in enumerate(dbs):check('组合库外键完整'+str(n),not db.execute('PRAGMA foreign_key_check').fetchone())
        return checks
    finally:
        for db in dbs:db.close()

def inputs():
    return list(dict.fromkeys(A.inputs()+G.SOURCES+[HERE/n for n in ('atomic-ingress-report.json','typed_controller_model.py','check_typed_controller.py','controller-typed.sql','TYPED_CONTROLLER.md')]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};path=HERE/'typed-controller-report.json'
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=121,controller_tables=237,final_admission_seal=False,public_command_record_typed=False,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(X.M.S.G.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
