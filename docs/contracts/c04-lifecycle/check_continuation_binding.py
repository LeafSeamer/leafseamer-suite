"""新绑定及完整IPC结构、授权链正反例；不开放真实最终发送。"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import continuation_binding_model as M
import check_continuation_protocol as P
import check_ipc_journal as J
T=P.T;G=M.G;C=M.C;Q=M.M;clone=copy.deepcopy
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
LOCAL=('build_continuation_binding.py','continuation_binding_model.py','check_continuation_binding.py','CONTINUATION_BINDING.md',*G.build())

def upgraded(old):
    frames=clone(old)
    def visit(v):
        if isinstance(v,list):
            for x in v:visit(x)
        elif isinstance(v,dict):
            if set(v)=={'origin_scope','run_id','definition_version','arm_generation','execution_id','execution_binding_ref','step_id','logical_action_id'}:
                v.update(binding_version=G.VERSION,authorization_mode='preparation',continuation=None)
                v['execution_binding_ref']['kind']='execution_binding'
            for x in v.values():visit(x)
    for name,f in frames.items():
        visit(f);f['ipc_version']=G.IPC_VERSION
        if name=='HELLO':f['body']['supported_ipc_versions']=[G.IPC_VERSION];f['body']['supported_features'].append(G.FEATURE)
        if name=='HELLO_ACK':f['body']['selected_ipc_version']=G.IPC_VERSION;f['body']['selected_features'].append(G.FEATURE)
    return frames

def fixture(frames):
    sd,q,s,cds,ctx=T.fixture();ex=T.start(sd,ctx);sub=T.submitted(sd,ex,'step.0',ctx)
    a=json.loads(M.P.R.one(sd,'rc_adoption','transfer_id',q['transfer_id'])['adoption_body'])
    rs=[json.loads(x[0]) for x in sd.execute('SELECT receipt_body FROM rc_receipt ORDER BY registration_id')]
    rs.sort(key=lambda r:Q.scope_key(r['controller_scope']))
    target=q['targets'][0]['controller_scope'];sel=M.selection(q,a,rs[0],q['targets'][0]);body=clone(frames['DISPATCH']['body'])
    guard=clone(frames['GUARD_INSTALL']['body']['guard']);clock={k:guard[k] for k in ('clock_domain_id','descriptor_digest')}
    def r(kind):return dict(kind=kind,scope=q['origin_scope'],object_id=kind,revision='1',digest=Q.digest(kind))
    # 类型化执行正文的其他字段仍由合成提供者给出，不能冒充已有简化binding_body的完整等价迁移。
    base=dict(scope=q['origin_scope'],execution_id=ex,run_id=q['run_id'],artifact_ref=r('artifact'),
        origin=dict(kind='trigger',decision_id='decision',decision_digest=Q.digest('decision')),arm_generation=q['generation'],source_state=None,target_state_id=None,
        input_snapshot_ref=r('input_snapshot'),resolved_parameters_ref=r('resolved_parameters'),grants=[],clock=clock,plan_digest=q['continuation_plan_ref']['digest'],binding_digest=Q.digest('pending'))
    eb=M.execution(base,q,a,rs)
    ab=dict(origin_scope=q['origin_scope'],run_id=q['run_id'],definition_version='1',arm_generation=q['generation'],execution_id=ex,
        execution_binding_ref=M.eref(eb),step_id='step.0',logical_action_id='action.0',binding_version=G.VERSION,authorization_mode='continuation',continuation=sel)
    req=body['request'];req.update(origin='automation',device_id='dev.1',action_id='synthetic.set',parameters=dict(value=0),automation_binding=clone(ab),
        run_binding=dict(run_id=q['run_id'],definition_version='1',grant_id=sel['grant_ref']['id'],grant_revision=sel['grant_ref']['revision'],arm_generation=q['generation'],step_id='step.0',logical_action_id='action.0'))
    principal=dict(issuer_id=target['authority_service_id'],issuer_epoch='issuer.1',principal_id='seamer-service',audience=target['authority_service_id'])
    guard.update(device_id=req['device_id'],automation_binding=clone(ab));guard['binding'].update(**principal,principal_kind='service',origin='automation',session_id=None,session_revision=None,
        grant_id=sel['grant_ref']['id'],grant_revision=sel['grant_ref']['revision'],arm_generation=q['generation'],extension_instance_id=None,extension_approval_revision=None)
    guard=Q.seal(guard,'guard_digest');permit=body['permit'];permit.update(origin='automation',grant_revision=sel['grant_ref']['revision'],arm_generation=q['generation'],
        automation_binding=clone(ab),guard_digest=guard['guard_digest'],content_digest=Q.digest(M.content(req)))
    intent=permit['transmission']['intent'];intent.update(origin='automation',device_id=req['device_id'],automation_binding=clone(ab),automation_binding_digest=Q.digest(ab),guard_digest=guard['guard_digest'])
    body['guard_digest']=guard['guard_digest'];ack=clone(frames['GUARD_ACK']['body']);ack.update(automation_binding_digest=Q.digest(ab),guard_digest=guard['guard_digest'],content_digest=permit['content_digest'])
    authority=dict(request=q,adoption=a,receipts=rs,execution_binding=clone(eb),controller_scope=target,principal=principal,request_digest=permit['content_digest'],
        step=dict(step_id='step.0',logical_action_id='action.0',definition_version='1',**{k:req[k] for k in ('device_id','action_id','capability_version','parameters')}),
        authorization_current=True,control_current=True,source_current=True,time_current=True,budget_current=True,adoption_current=True,r5_committed=True,
        grant_current=bool(next(iter(cds.values()))[0].execute('SELECT 1 FROM cr_current').fetchone()))
    # 各输入和可信提供者分开持有；反例不能经共享dict同时修改被测输入及权威预期。
    return sd,cds,sub,[clone(x) for x in (eb,req,guard,permit,intent,ack,authority)],body

def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def denied(n,fn):
        try:fn()
        except (ValueError,ValidationError):check(n);return
        raise AssertionError(n+':应拒绝')
    try:
        outputs=G.build();old,context,inherited=J.fixtures();frames=upgraded(old)
        ipc=outputs['continuation-binding-ipc.schema.json'];validator=Draft202012Validator(ipc)
        for name,value in outputs.items():
            check('生成一致'+name,(HERE/name).read_bytes()==G.raw(value))
            if name.endswith('.schema.json'):Draft202012Validator.check_schema(value);check('Schema有效'+name)
        check('全部52帧保留',len(frames)==len(ipc['oneOf'])==52)
        for name,f in frames.items():
            validator.validate(f);check('升级帧结构'+name)
            denied('旧版本不能混投'+name,lambda f=f:validator.validate(dict(f,ipc_version='ipc/0.13.0-journal-draft.1')))
        for name,key in [('HELLO','supported_features'),('HELLO_ACK','selected_features')]:
            bad=clone(frames[name]);bad['body'][key].remove(G.FEATURE);denied('握手缺能力'+name,lambda bad=bad:validator.validate(bad))
        sd,cds,sub,values,body=fixture(frames);dbs=[sd]+[x[0] for x in cds.values()]
        eb,req,g,p,i,ack,a=values;check('完整授权链正例',M.validate_chain(*values)=='binding_valid')
        retry=[clone(x) for x in values];rp=retry[3];rg=retry[2]
        rg.update(guard_id='guard-resend',permit_id='resend-permit');retry[2]=rg=Q.seal(rg,'guard_digest')
        rp.update(permit_id='resend-permit',guard_id=rg['guard_id'],guard_digest=rg['guard_digest'],budget_revision='2')
        rp['transmission']=clone(frames['RESEND_DISPATCH']['body']['permit']['transmission'])
        ri=clone(i);ri.update(permit_id=rp['permit_id'],guard_id=rg['guard_id'],guard_digest=rg['guard_digest'])
        rp['transmission']['intent']=ri;retry[4]=clone(ri)
        retry[5].update(permit_id=rp['permit_id'],guard_id=rg['guard_id'],guard_digest=rg['guard_digest'])
        check('重传新许可和新Guard',M.validate_resend(values,retry)=='resend_binding_valid')
        resend=clone(frames['RESEND_DISPATCH']);resend['body'].update(permit=rp,request=retry[1],guard_id=rg['guard_id'],guard_digest=rg['guard_digest']);resend['device_id']=req['device_id']
        validator.validate(resend);check('重传完整帧承载新绑定')
        for field,value in [('ordinal','0'),('issued_revision','1'),('initial_permit_id','other')]:
            bad=clone(retry);bad[3]['transmission'][field]=value
            denied('重传来源错配'+field,lambda bad=bad:M.validate_resend(values,bad))
        for name,value in [('ExecutionBinding',eb),('CommandRequest',req),('ExecutionGuard',g),('TransmissionPermit',p),('DispatchIntent',i),('GuardAck',ack)]:
            M.validate(name,value);check('具名导出'+name)
        check('执行正文不含提交身份', 'submission_id' not in json.dumps(eb) and sub not in json.dumps(eb))
        selected=M.P.command_binding(sd,sub)
        check('六类引用对应实际SQL原件',all(req['automation_binding']['continuation'][k]==selected[k] for k in ('transfer_ref','adoption_ref','receipt_ref','grant_ref','plan_ref')))
        f=clone(frames['DISPATCH']);f['body']=clone(body);f['device_id']=req['device_id'];validator.validate(f);check('普通派发携新绑定')
        for field in ('binding_version','authorization_mode','continuation'):
            bad=clone(req);bad['automation_binding'].pop(field)
            denied('旧自动化绑定不能降级'+field,lambda bad=bad:M.validate('CommandRequest',bad))
        manual=clone(req);manual.update(origin='manual',automation_binding=None);manual.pop('run_binding');M.validate('CommandRequest',manual);check('手动形状仍可用')
        bad=clone(manual);bad['automation_binding']=req['automation_binding'];denied('手动不能夹带转交',lambda:M.validate('CommandRequest',bad))
        for field,value in [('authorization_mode','preparation'),('continuation',None)]:
            bad=clone(req);bad['automation_binding'][field]=value;denied('模式分支错配'+field,lambda bad=bad:M.validate('CommandRequest',bad))
        for field,value in [('origin',dict(kind='recovery',operation_id='op',preview_id='pv',preview_digest=Q.digest('pv'),prior_execution_id=None)),
            ('continuations',[]),('continuations',eb['continuations'][:1]),('grants',eb['grants'][:1])]:
            bad=Q.seal(dict(eb,**{field:value}),'binding_digest');denied('执行清单错配'+field+str(len(str(value))),lambda bad=bad:M.validate_execution(bad,a['request'],a['adoption'],a['receipts']))
        for key in req['automation_binding']['continuation']:
            v=clone(values);v[1]['automation_binding']['continuation'][key]['digest']=Q.digest('forged')
            denied('选择引用错配'+key,lambda v=v:M.validate_chain(*v))
        for index in (2,3,4):
            v=clone(values);v[index]['automation_binding']['continuation']['grant_ref']['digest']=Q.digest('wrong')
            if index==2:v[index]=Q.seal(v[index],'guard_digest')
            denied('链中副本错配'+str(index),lambda v=v:M.validate_chain(*v))
        for index,key in [(3,'grant_revision'),(4,'permit_id'),(5,'automation_binding_digest'),(5,'permit_id')]:
            v=clone(values);v[index][key]=Q.digest('wrong') if key.endswith('digest') else '999'
            denied('许可ACK错配'+str(index)+key,lambda v=v:M.validate_chain(*v))
        v=clone(values);v[1]['parameters']['value']=99;v[3]['content_digest']=v[5]['content_digest']=Q.digest(M.content(v[1]));v[6]['request_digest']=v[3]['content_digest']
        denied('参数重摘要仍须固定步骤',lambda:M.validate_chain(*v))
        v=clone(values);v[2]['binding']['issuer_epoch']='other';v[2]=Q.seal(v[2],'guard_digest');denied('同名服务换epoch',lambda:M.validate_chain(*v))
        for field in ('authorization_current','control_current','source_current','time_current','budget_current','adoption_current','r5_committed','grant_current'):
            v=clone(values);v[6][field]=False;denied('当前门槛'+field,lambda v=v:M.validate_chain(*v))
        cd=next(iter(cds.values()))[0];T.SC.execute(cd,[T.I('cr_revocation',transfer_id=a['request']['transfer_id'],proof_body=T.AT.B,audit_body=T.AT.B,outbox_body=T.AT.B)])
        v=clone(values);v[6]['grant_current']=bool(cd.execute('SELECT 1 FROM cr_current').fetchone());denied('实际Controller撤回使链失效',lambda:M.validate_chain(*v))
        for field in ('context_id','idempotency_key','correlation_id'):
            modified=dict(req,**{field:'transport-change'});check('只排顶层运输字段'+field,Q.digest(M.content(modified))==Q.digest(M.content(req)))
        modified=clone(req);modified['parameters']['context_id']='business';check('嵌套同名字段参与摘要',Q.digest(M.content(modified))!=Q.digest(M.content(req)))
        for index,db in enumerate(dbs):check('外键完整'+str(index),not db.execute('PRAGMA foreign_key_check').fetchall())
        return checks,list(dict.fromkeys(P.INPUTS+inherited+G.SOURCES+[HERE/n for n in LOCAL]))
    finally:
        for db in dbs:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    path=HERE/'continuation-binding-report.json'
    if a.check_report:
        report=json.loads(path.read_bytes());inherited=J.fixtures()[2]
        inputs=list(dict.fromkeys(P.INPUTS+inherited+G.SOURCES+[HERE/n for n in LOCAL]))
        assert report['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
        print(json.dumps(dict(all_passed=True,matched_bindings=len(report['inputs']))))
    else:
        checks,inputs=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),ipc_frame_types=52,final_admission_tests_executed=0,
            runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
        if a.report:path.write_bytes(G.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
