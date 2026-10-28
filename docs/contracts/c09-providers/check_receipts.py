"""固定服务回执到有限host.result投影；账本与当前读权由显式合成来源提供。"""
import argparse
import copy
import json
from pathlib import Path
import threading
import readset as R
import coordinator as G
import delivery as D
import receipt_delivery as Q
import typed_validators as V
import check_readset as C

ROOT=R.ROOT;SUITE=C.SUITE;H=C.H
REJECTED=['authority_denied','schema_invalid','target_changed','expired','activation_stale']
CONFIRM={'controller.acceptTransfer','controller.acquireControl','controller.offerTransfer','controller.releaseControl','controller.revokeRunGrant','seamer.armRun','seamer.publishDefinition','seamer.resumeRun'}


def run(sdk):
    checks=[]
    def check(name,ok=True):R.need(ok,name);checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,KeyError,TypeError) as e:check(name,reason is None or str(e)==reason)
        else:raise AssertionError(name+':未拒绝')
    source=json.loads((ROOT/'delivery-sources.json').read_bytes());raws=H.read_fixed(sdk,source['sdk_commit'],source['inputs'])
    check('固定35方法原件',all(H.sha(b)==source['inputs'][p] for p,b in raws.items()))
    typed=json.loads((ROOT/'typed-sources.json').read_bytes());mp='contracts/panel-wire/contract/models.schema.json';model=H.read_fixed(sdk,typed['sdk_commit'],[mp])[mp]
    contract=V.Contract(model,R.SELECTION);cases={c['method']:c for c in json.loads(raws['contracts/panel-http/panel-cases.json'])['cases']}
    semantic=json.loads((ROOT/'receipt-sources.json').read_bytes());fixed=H.read_fixed(sdk,semantic['sdk_commit'],semantic['inputs'])
    check('固定受理与投影分离规范',semantic['sdk_commit']==source['sdk_commit'] and all(H.sha(b)==semantic['inputs'][p] for p,b in fixed.items()))
    check('14种有限原因全部有明确分支',set(REJECTED)|Q.UNAVAILABLE_REASONS|{'ok','needs_host_confirmation','user_cancelled'}==set(contract._defs['panel__Channel_Reason']['enum']))
    def fixture(method='controller.getMeta'):
        case=copy.deepcopy(cases[method]);intent=case['request']['intent'];identity=copy.deepcopy(intent['identity']);context=C.fixture(method)['context'];clock=[1000000000]
        binding=dict(panel_session_id=identity['panel_session_id'],panel_instance_id='panel.synthetic',document_generation=identity['document_generation'],channel_id='channel.synthetic',protocol_version='panel-channel/0.3.0-draft.1')
        request=dict(protocol_version=binding['protocol_version'],type='panel.request',public_binding=binding,channel_sequence='3',request_id=identity['request_id'],method=method,target_handle='target.synthetic',resource_ref=None,payload=copy.deepcopy(intent['normalized_arguments']),activation_ref=copy.deepcopy(intent['activation_ref']))
        context.update(request_id=request['request_id'],public_binding_digest=R.digest(binding),activation_digest=R.digest(request['activation_ref']),input_digest=R.digest(request['payload']['value']),scope={k:identity[k] for k in ['authority_service_id','database_instance_id']})
        receipt=copy.deepcopy(case['unavailable']);receipt['intent_digest']=R.digest(intent);record=dict(invocation=case['request'],observation=dict(kind='receipt',receipt=receipt))
        owner=G.Coordinator();session=owner.register(lambda:None);ledger=owner.register(lambda:None);projection=owner.register(lambda:None);payloads=[]
        class Sink:
            def write_once(self,payload):payloads.append(payload);return len(payload)
        delivery=D.Delivery(owner,contract,[session],{k:context[k] for k in D.SESSION_KEYS},binding,request['activation_ref'],Sink(),next_sequence='7')
        f=dict(owner=owner,session=session,ledger=ledger,projection=projection,delivery=delivery,context=context,request=request,identity=identity,record=record,clock=clock,payloads=payloads,case=case)
        def reader(c,r):
            R.need(R.bounded(c)==R.bounded(context) and R.bounded(r)==R.bounded(request),'synthetic_journal_binding');return copy.deepcopy(record)
        def enqueue(custom=None,**limits):return Q.enqueue_status(delivery,[session,ledger],context,request,identity,custom or reader,clock=lambda:clock[0],**limits)
        def release(ticket):return delivery.release(ticket,lambda _:copy.deepcopy(context))
        f.update(enqueue=enqueue,release=release);return f
    def state(f,value,reason=None):
        receipt=f['record']['observation']['receipt'];receipt.update(state=value,reason_code=reason or {'accepted':'ok','pending_confirmation':'needs_host_confirmation','cancelled':'user_cancelled','rejected':'authority_denied'}[value],projection=None,projection_state='unavailable' if value=='accepted' else 'not_applicable',accepted_result_ref=copy.deepcopy(f['case']['unavailable']['accepted_result_ref']) if value=='accepted' else None)
    def frame(f):return json.loads(f['payloads'][-1])
    for method in cases:
        for status,reason in [('accepted','ok'),('cancelled','user_cancelled')]+[('rejected',r) for r in REJECTED]:
            f=fixture(method);state(f,status,reason);ticket=f['enqueue']();check('结果未在入队时发送:'+method+':'+status+':'+reason,f['delivery'].state()['sent_sequence'] is None and not f['payloads'])
            f['release'](ticket);out=frame(f)
            check('完整状态帧:'+method+':'+status+':'+reason,contract.validate('panel__Channel_Result',out) and out['status']==status and out['reason_code']==reason and out['result'] is None and out['projection_state']==('unavailable' if status=='accepted' else 'not_applicable'))
            check('回执身份和结果引用不泄漏:'+method+':'+status+':'+reason,set(out)==set(contract._defs['panel__Channel_Result']['required']) and not any(k in out for k in ['identity','intent_digest','accepted_result_ref','invocation']))
            f['owner'].close()
        f=fixture(method);state(f,'pending_confirmation')
        if method in CONFIRM:
            f['release'](f['enqueue']());check('确认方法保留待确认:'+method,frame(f)['status']=='pending_confirmation')
        else:denied('普通方法不能冒充待确认:'+method,f['enqueue'],'receipt_schema')
        f['owner'].close()
    for reason in sorted(Q.UNAVAILABLE_REASONS):
        f=fixture();f['record']['observation']=dict(kind='unavailable',reason_code=reason);f['release'](f['enqueue']())
        check('宿主不可用不是未受理:'+reason,frame(f)['status']=='unavailable' and frame(f)['projection_state']=='not_applicable' and frame(f)['result'] is None);f['owner'].close()
    for field in ['authority_service_id','database_instance_id','issuer_id','issuer_epoch','auth_session_id','panel_session_id','document_generation','request_id']:
        f=fixture();i=f['record']['invocation']['intent'];i['identity'][field]='2' if field=='document_generation' else 'other.synthetic'
        receipt=f['record']['observation']['receipt'];receipt['identity']=copy.deepcopy(i['identity']);receipt['intent_digest']=R.digest(i)
        denied('重新计算摘要也不能跨完整身份:'+field,f['enqueue']);f['owner'].close()
    for field in ['intent_digest','method','activation_ref','identity','accepted_result_ref']:
        f=fixture();r=f['record']['observation']['receipt']
        if field=='intent_digest':r[field]='0'*64
        elif field=='method':r[field]='seamer.getMeta'
        elif field=='activation_ref':r[field]['activation_id']='other.synthetic'
        elif field=='identity':r[field]['issuer_epoch']='other.synthetic'
        else:r[field]['database_instance_id']='other.synthetic'
        denied('错绑回执拒绝:'+field,f['enqueue']);f['owner'].close()
    for field in ['normalized_arguments','activation_ref','delegation_ref','target_ref']:
        f=fixture();i=f['record']['invocation']['intent']
        if field=='normalized_arguments':i[field]['schema_ref']['schema_digest']='0'*64
        elif field=='activation_ref':i[field]['activation_id']='other.synthetic'
        else:i[field]['database_instance_id']='other.synthetic'
        f['record']['observation']['receipt']['intent_digest']=R.digest(i)
        denied('原意图变异拒绝:'+field,f['enqueue']);f['owner'].close()
    f=fixture();f['record']['invocation']['intent']['target_ref']=None;f['record']['observation']['receipt']['intent_digest']=R.digest(f['record']['invocation']['intent'])
    f['release'](f['enqueue']());check('合法空目标不制造虚拟对象',frame(f)['status']=='accepted');f['owner'].close()
    f=fixture();r=f['record']['observation']['receipt'];r.update(projection_state='available',projection=copy.deepcopy(f['case']['response']['projection']))
    denied('原始回执投影不能绕过读集',f['enqueue'],'projection_requires_readset');f['owner'].close()
    for status,reason in [('accepted','unknown_outcome'),('cancelled','authority_denied'),('rejected','user_cancelled'),('pending_confirmation','ok')]:
        f=fixture('controller.acquireControl');state(f,status,reason);denied('状态原因不能混编:'+status,f['enqueue'],'receipt_schema');f['owner'].close()
    for observation in [dict(kind='unavailable',reason_code='ok'),dict(kind='unavailable',reason_code='unknown_outcome',details='private'),dict(kind='receipt',receipt={},trace='private')]:
        f=fixture();f['record']['observation']=observation;denied('有限观察不接收额外细节:'+str(len(checks)),f['enqueue']);f['owner'].close()
    def unavailable(c,r):raise ValueError('journal_unreadable')
    f=fixture();denied('异常不能自动伪造未知回执',lambda:f['enqueue'](unavailable),'journal_unreadable');check('异常没有隐式发送',not f['payloads']);f['owner'].close()
    # 失效的是投影来源时，独立且仍有当前读权的账本可以返回已受理事实。
    f=fixture();f['owner'].revoke(f['projection']);f['release'](f['enqueue']());check('投影不可用仍保留已受理',frame(f)['status']=='accepted' and frame(f)['projection_state']=='unavailable')
    ticket=f['enqueue']();f['owner'].revoke(f['ledger']);denied('账本读权撤销也必须关门',lambda:f['release'](ticket),'output_closed');f['owner'].close()
    for earlier,later in [('accepted','rejected'),('accepted','cancelled'),('rejected','accepted'),('cancelled','accepted'),('cancelled','pending_confirmation')]:
        f=fixture('controller.acquireControl');state(f,earlier);f['release'](f['enqueue']());state(f,later)
        denied('已知状态不能倒退:'+earlier+':'+later,f['enqueue'],'outcome_regression');f['owner'].close()
    for later in ['accepted','cancelled','rejected']:
        f=fixture('controller.acquireControl');state(f,'pending_confirmation');f['release'](f['enqueue']());state(f,later);f['release'](f['enqueue']());check('待确认可取得权威终态:'+later,frame(f)['status']==later);f['owner'].close()
    f=fixture();f['release'](f['enqueue']());f['record']['observation']=dict(kind='unavailable',reason_code='unknown_outcome')
    denied('已知受理不能被未知观察覆盖',f['enqueue'],'accepted_receipt_required');check('客户端已知受理没有被新的模糊状态覆盖',len(f['payloads'])==1 and frame(f)['status']=='accepted');f['owner'].close()
    f=fixture();f['release'](f['enqueue']());f['record']['observation']['receipt']['accepted_result_ref']['revision']='2'
    denied('同意图受理结果引用不可替换',f['enqueue'],'accepted_result_changed');f['owner'].close()
    for field in ['target_ref','policy_ref','delegation_ref','capability_ref','identity']:
        f=fixture();f['release'](f['enqueue']());intent=f['record']['invocation']['intent']
        if field=='capability_ref':intent[field]=copy.deepcopy(intent['policy_ref'])
        elif field=='identity':
            intent[field]['issuer_epoch']='other.synthetic';f['identity']['issuer_epoch']='other.synthetic';f['record']['observation']['receipt']['identity']=copy.deepcopy(intent[field])
        else:intent[field]['revision']='2'
        f['record']['observation']['receipt']['intent_digest']=R.digest(intent)
        denied('同原请求重新计算摘要也不能换原意图:'+field,f['enqueue'],'original_intent_changed');f['owner'].close()
    # 与完整投影共用状态登记，两个入口之间也不能改写终态。
    def available(f):
        out=copy.deepcopy(f['case']['response']['projection']['value']);c=f['context'];model='baseline__Meta'
        record=dict(protocol_version=R.SELECTION['contract_id'],component_version=out['component_version'],service_id='authority.fixture',service_boot_id='boot.synthetic',features=out['panel_features'],limits_profile=out['limits_profile_ref'],selection=R.SELECTION)
        ref=dict(c['scope'],entity_kind='meta',entity_id='meta.synthetic',entity_epoch='epoch.synthetic',revision='1',content_digest=R.digest(record));_,_,parts=R.assignments(c['method']);item=dict(model=model,ref=ref,value=record);expected={p:[dict(model=model,ref=ref)] for p in parts}
        a=f['owner'].begin([f['session'],f['projection']],lambda:R.ReadSet(c,expected,lambda m,v:m==model and contract.validate(m,v) and v==record,lambda n,v:contract.bind(c['method']).result(n,v) and v==out,clock=lambda:f['clock'][0]))
        for p,fields in parts.items():a.provide(a.ticket(p),[item],{k:out[k] for k in fields})
        return f['delivery'].enqueue(a,a.seal(),c,f['request'],lambda cc,rr:cc==c and rr==f['request'])
    f=fixture();f['release'](available(f));state(f,'cancelled');denied('完整投影后不能发取消回执',f['enqueue'],'outcome_regression');f['owner'].close()
    f=fixture();state(f,'rejected');f['release'](f['enqueue']());denied('拒绝后不能换完整投影称受理',lambda:available(f),'outcome_regression');f['owner'].close()
    f=fixture();f['release'](f['enqueue']());f['release'](available(f));check('已受理无投影可重新读取完整投影',frame(f)['projection_state']=='available');f['owner'].close()
    for delta,label in [(2000000000,'截止等号'),(-1,'时钟倒退')]:
        f=fixture()
        def late(c,r):f['clock'][0]+=delta;return f['record']
        denied('账本读取期间'+label,lambda:f['enqueue'](late),'status_expired');f['owner'].close()
    f=fixture();ticket=f['enqueue']();f['clock'][0]+=2000000000;denied('排队不刷新原截止',lambda:f['release'](ticket),'output_expired');f['owner'].close()
    f=fixture();entered=threading.Event();resume=threading.Event();out=[]
    def slow(c,r):entered.set();R.need(resume.wait(10),'thread_timeout');return f['record']
    def work():
        try:out.append(('ok',f['enqueue'](slow)))
        except BaseException as e:out.append(('error',str(e)))
    thread=threading.Thread(target=work);thread.start()
    try:
        R.need(entered.wait(10),'thread_timeout');denied('同通道不并行分配序号',f['enqueue'],'output_preparing');f['owner'].revoke(f['ledger'])
    finally:resume.set()
    thread.join(15);check('慢账本读取中撤权先完成',not thread.is_alive() and out==[('error','output_closed')] and not f['payloads']);f['owner'].close()
    paths=[ROOT/n for n in ['receipt_delivery.py','check_receipts.py','receipt-sources.json','RECEIPTS.md','delivery.py','delivery-sources.json','typed-sources.json','typed_validators.py','coordinator.py','readset.py','check_readset.py','source/bindings.json','source/selection.json','DELIVERY.md','PROVIDERS.md']]+[C.HELPER,SUITE/'docs/rebirth-c09-extension-design.md']
    return dict(format='panel-receipt-delivery-check/1',approved=False,runtime_ready=False,all_passed=True,cases_passed=len(checks),checks=checks,methods=35,confirmation_methods=8,statuses=5,explicit_synthetic_journal_and_authorization=True,real_thread_scenarios=1,
        production_authorization_tests_executed=0,production_output_gate_tests_executed=0,database_tests_executed=0,network_tests_executed=0,browser_tests_executed=0,device_tests_executed=0,domain_operation_submissions=0,
        sdk_commit=source['sdk_commit'],fixed_sdk_inputs={**source['inputs'],**semantic['inputs'],mp:H.sha(model)},inputs={p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in paths})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sdk',type=Path,required=True);parser.add_argument('--report',action='store_true');args=parser.parse_args();r=run(args.sdk.resolve())
    if args.report:(ROOT/'receipt-report.json').write_bytes(H.encode(r))
    print(json.dumps({k:v for k,v in r.items() if k not in ['checks','inputs','fixed_sdk_inputs']},ensure_ascii=False))
