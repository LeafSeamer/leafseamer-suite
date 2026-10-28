"""完整结果帧、局部出口与失效检查；使用固定方法样例及显式合成批准。"""
import argparse
import copy
import json
from pathlib import Path
import socket
import threading
import readset as R
import coordinator as G
import delivery as D
import typed_validators as V
import check_readset as C

ROOT=R.ROOT;H=C.H;SUITE=C.SUITE


class Sink:
    def __init__(self,behavior=None):self.payloads=[];self.behavior=behavior
    def write_once(self,payload):
        self.payloads.append(payload)
        return len(payload) if self.behavior is None else self.behavior(payload)


def run(sdk):
    checks=[];threads=0
    def check(name,ok=True):R.need(ok,name);checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,KeyError) as e:check(name,reason is None or str(e)==reason)
        else:raise AssertionError(name+':未拒绝')
    source=json.loads((ROOT/'delivery-sources.json').read_bytes());fixed=H.read_fixed(sdk,source['sdk_commit'],source['inputs'])
    check('固定方法样例原件',all(H.sha(b)==source['inputs'][p] for p,b in fixed.items()))
    typed=json.loads((ROOT/'typed-sources.json').read_bytes());model_path='contracts/panel-wire/contract/models.schema.json'
    model=H.read_fixed(sdk,typed['sdk_commit'],[model_path])[model_path];contract=V.Contract(model,R.SELECTION)
    cases={c['method']:c for c in json.loads(fixed['contracts/panel-http/panel-cases.json'])['cases']}
    check('固定样例覆盖35方法',set(cases)==set(R.BINDINGS['methods']))
    def fixture(method='controller.getMeta',sink=None,**limits):
        base=C.fixture(method);intent=cases[method]['request']['intent'];output=copy.deepcopy(cases[method]['response']['projection']['value'])
        binding=dict(panel_session_id='session.synthetic',panel_instance_id='panel.synthetic',document_generation='1',channel_id='channel.synthetic',protocol_version='panel-channel/0.3.0-draft.1')
        activation=copy.deepcopy(intent['activation_ref']);request=dict(protocol_version=binding['protocol_version'],type='panel.request',public_binding=binding,channel_sequence='3',request_id='request.synthetic',method=method,target_handle='target.synthetic',resource_ref=None,payload=copy.deepcopy(intent['normalized_arguments']),activation_ref=activation)
        context=base['context'];context.update(public_binding_digest=R.digest(binding),activation_digest=R.digest(activation),input_digest=R.digest(request['payload']['value']))
        owner=G.Coordinator();dep=owner.register(lambda:None);source_dep=owner.register(lambda:None);sink=sink or Sink()
        channel=D.Delivery(owner,contract,[dep],{k:context[k] for k in D.SESSION_KEYS},binding,activation,sink,next_sequence=limits.pop('next_sequence','7'),**limits)
        _,model_name,parts=R.assignments(method);record={}
        for field,rule in parts['root'].items():
            cursor=record;segments=rule['path'].split('.')
            for segment in segments[:-1]:cursor=cursor.setdefault(segment,{})
            cursor[segments[-1]]=copy.deepcopy(output[field])
        if model_name=='baseline__Meta':record=dict(protocol_version=R.SELECTION['contract_id'],component_version=output['component_version'],service_id='controller.synthetic',service_boot_id='boot.synthetic',features=output['panel_features'],limits_profile=output['limits_profile_ref'],selection=R.SELECTION)
        ref=dict(base['sources']['root'][0]['ref'],content_digest=R.digest(record));item=dict(model=model_name,ref=ref,value=record)
        expected={p:[dict(model=model_name,ref=ref)] for p in parts}
        selected=contract.bind(method,lambda m,p,k,v:m==method and any(p==slot and k==kind and R.bounded(v)==R.bounded(value) for slot,kind,value in V.dynamic_slots(R.assignments(method)[0],output)))
        def fresh(request_id=None):
            c=copy.deepcopy(context);req=copy.deepcopy(request)
            if request_id is not None:c['request_id']=request_id;req['request_id']=request_id
            def source_guard(m,v):return m==model_name and R.bounded(v)==R.bounded(record) and (model_name!='baseline__Meta' or contract.validate(m,v))
            def result_guard(n,v):return selected.result(n,v) and R.bounded(v)==R.bounded(output)
            a=owner.begin([dep,source_dep],lambda:R.ReadSet(c,expected,source_guard,result_guard,clock=lambda:base['clock'][0]))
            for p,fields in parts.items():a.provide(a.ticket(p),[item],{k:copy.deepcopy(output[k]) for k in fields})
            return a,a.seal(),c,req
        def enqueue(values=None,guard=None):
            a,token,c,req=values or fresh()
            approved=copy.deepcopy(req);approved_context=copy.deepcopy(c)
            return channel.enqueue(a,token,c,req,guard or (lambda cc,rr:R.bounded(rr)==R.bounded(approved) and cc==approved_context))
        return dict(owner=owner,dep=dep,source_dep=source_dep,channel=channel,clock=base['clock'],context=context,request=request,output=output,sink=sink,fresh=fresh,enqueue=enqueue)
    for method in cases:
        f=fixture(method);ticket=f['enqueue']();check('完整帧入队不等于交付:'+method,f['channel'].state()['sent_sequence'] is None and not f['sink'].payloads)
        result=f['channel'].release(ticket,lambda digest:copy.deepcopy(f['context']));frame=json.loads(f['sink'].payloads[0])
        check('完整方法结果帧:'+method,result['status']=='handed_off' and contract.validate('panel__Channel_Result',frame) and frame['result']['value']==f['output'] and frame['channel_sequence']=='7')
        check('只保留有限公开字段:'+method,set(frame)==set(contract._defs['panel__Channel_Result']['required']))
        denied('释放票据不可重放:'+method,lambda:f['channel'].release(ticket,lambda _:f['context']),'output_head');f['owner'].close()
    f=fixture();a=f['fresh']();ticket=f['enqueue'](a);f['owner'].revoke(f['source_dep'])
    denied('来源依赖撤销清空已消费队列',lambda:f['channel'].release(ticket,lambda _:f['context']),'output_closed');check('撤销前未发送任何字节',not f['sink'].payloads and f['channel'].state()['queued']==0)
    denied('已入队读集不能再次消费',lambda:a[0].consume(a[2],a[1]),'managed_read_closed')
    for change in ['public_binding_digest','activation_digest','authorization_digest','installation_digest','approval_digest','input_digest']:
        f=fixture();a,token,c,req=f['fresh']();c[change]='0'*64
        denied('上下文变化不能入队:'+change,lambda:f['enqueue']((a,token,c,req)))
        check('错上下文无字节:'+change,not f['sink'].payloads);f['owner'].close()
    for change in ['method','request_id','target_handle','public_binding','activation_ref','payload']:
        f=fixture();a,token,c,req=f['fresh']();approved=copy.deepcopy(req)
        if change=='method':req[change]='seamer.getMeta'
        elif change in ['request_id','target_handle']:req[change]='other.synthetic'
        elif change=='public_binding':req[change]['document_generation']='2'
        elif change=='activation_ref':req[change]['activation_id']='other.synthetic'
        else:req[change]['schema_ref']['schema_digest']='0'*64
        denied('原请求变异拒绝:'+change,lambda:f['enqueue']((a,token,c,req),lambda cc,rr:rr==approved));f['owner'].close()
    f=fixture()
    values=f['fresh']();denied('缺受理守卫不能入队',lambda:f['channel'].enqueue(*values,None),'acceptance_guard')
    denied('受理守卫须明确True',lambda:f['enqueue'](values,lambda *a:1),'request_not_accepted');f['owner'].close()
    f=fixture();first=f['enqueue']();second=f['enqueue']();denied('只能释放队首',lambda:f['channel'].release(second,lambda _:f['context']),'output_head')
    check('原请求查询可使用新读集重新投影',f['channel'].release(first,lambda _:f['context'])['channel_sequence']=='7' and f['channel'].release(second,lambda _:f['context'])['channel_sequence']=='8');f['owner'].close()
    f=fixture();values=f['fresh']();original=copy.deepcopy(f['output']);f['output']['component_version']='changed'
    ticket=f['enqueue'](values);f['channel'].release(ticket,lambda _:f['context'])
    check('封装后外部修改不改变队列原件',json.loads(f['sink'].payloads[0])['result']['value']==original)
    f['channel'].close()
    denied('同公共通道关闭后也不能另起序号',lambda:D.Delivery(f['owner'],contract,[f['dep']],{k:f['context'][k] for k in D.SESSION_KEYS},f['request']['public_binding'],f['request']['activation_ref'],Sink(),next_sequence='1'),'output_channel_reused');f['owner'].close()
    f=fixture();values=f['fresh']();other=fixture()
    denied('跨协调器读集不能交付',lambda:other['enqueue'](values),'managed_read_closed');values[0].close();f['owner'].close();other['owner'].close()
    f=fixture();first=f['enqueue']();a,token,c,req=f['fresh']();req['target_handle']='replacement.synthetic'
    denied('同请求ID不能换原请求内容',lambda:f['enqueue']((a,token,c,req)),'result_identity');f['owner'].close()
    f=fixture(max_items=1);f['enqueue']();denied('有界队列不丢旧帧后继续',f['enqueue'],'output_capacity');check('容量失败关闭通道',f['channel'].state()['closed']);f['owner'].close()
    f=fixture(max_bytes=1);denied('总字节预算独立生效',f['enqueue'],'output_capacity');f['owner'].close()
    # 用实际完整信封长度定位64KiB边界；动态值长度在本检查由合成批准允许。
    f=fixture('controller.getDeviceState');f['output']['values']['value']['program']='';ticket=f['enqueue']();f['channel'].release(ticket,lambda _:f['context']);overhead=len(f['sink'].payloads[0]);f['owner'].close()
    for extra in [0,1]:
        f=fixture('controller.getDeviceState');f['output']['values']['value']['program']='x'*(65536-overhead+extra)
        if extra:denied('完整帧超64KiB不裁剪',f['enqueue'],'value_budget')
        else:
            ticket=f['enqueue']();f['channel'].release(ticket,lambda _:f['context']);check('完整帧64KiB等号可交付',len(f['sink'].payloads[0])==65536)
        f['owner'].close()
    for delta,label in [(2000000000,'截止等号'),(-1,'时钟倒退')]:
        f=fixture();ticket=f['enqueue']();f['clock'][0]+=delta
        denied(label+'不交付',lambda:f['channel'].release(ticket,lambda _:f['context']),'output_expired');check(label+'无字节',not f['sink'].payloads);f['owner'].close()
    f=fixture();ticket=f['enqueue']();bad=dict(f['context'],authorization_digest='0'*64)
    denied('释放前重新读取当前资格',lambda:f['channel'].release(ticket,lambda _:bad),'current_context_changed');f['owner'].close()
    def blocked(payload):raise BlockingIOError()
    f=fixture(sink=Sink(blocked));ticket=f['enqueue']();check('明确零字节阻塞保留队首',f['channel'].release(ticket,lambda _:f['context'])['status']=='would_block' and f['channel'].state()['sent_sequence'] is None)
    f['owner'].revoke(f['dep']);denied('阻塞后撤权不能重试旧字节',lambda:f['channel'].release(ticket,lambda _:f['context']),'output_closed')
    def error(payload):raise RuntimeError('synthetic')
    def uncertain(payload):
        e=BlockingIOError();e.characters_written=1;raise e
    for label,behavior,status in [('零返回',lambda b:0,'partial_closed'),('部分返回',lambda b:1,'partial_closed'),('异常',error,'indeterminate'),('阻塞但有字节',uncertain,'indeterminate'),('布尔返回',lambda b:True,'indeterminate'),('越界返回',lambda b:len(b)+1,'indeterminate')]:
        f=fixture(sink=Sink(behavior));ticket=f['enqueue']();result=f['channel'].release(ticket,lambda _:f['context'])
        check('出口故障关闭:'+label,result['status']==status and f['channel'].state()==dict(closed=True,queued=0,queued_bytes=0,sent_sequence=None));f['owner'].close()
    f=fixture(next_sequence=str(D.MAX_SEQUENCE));ticket=f['enqueue']();check('最后合法序号可交付',f['channel'].release(ticket,lambda _:f['context'])['channel_sequence']==str(D.MAX_SEQUENCE))
    denied('序号溢出关闭',f['enqueue']);f['owner'].close()
    # 实际socket完整交付与实际缓冲阻塞；接收字节按固定完整模型验证。
    def local_pair():
        listener=socket.socket();listener.settimeout(3);left=socket.socket();left.settimeout(3)
        try:
            listener.bind(('127.0.0.1',0));listener.listen(1);left.connect(listener.getsockname());right,_=listener.accept();return left,right
        except BaseException:left.close();raise
        finally:listener.close()
    for saturated in [False,True]:
        left,right=local_pair();right.settimeout(2)
        try:
            sink=D.SocketSink(left)
            if saturated:
                left.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,4096)
                for attempt in range(1024):
                    try:left.send(b'x'*4096)
                    except BlockingIOError:break
                else:raise AssertionError('socket_saturation_budget')
            f=fixture(sink=sink);ticket=f['enqueue']();result=f['channel'].release(ticket,lambda _:f['context'])
            if saturated:check('实际socket缓冲满拒绝释放',result['status']=='would_block' and f['channel'].state()['queued']==1)
            else:
                raw=b''
                while len(raw)<result['bytes_accepted']:raw+=right.recv(result['bytes_accepted']-len(raw))
                check('实际socket收到完整合法结果帧',contract.validate('panel__Channel_Result',json.loads(raw)) and H.sha(raw)==result['payload_digest'])
            f['owner'].close()
        finally:left.close();right.close()
    def start(fn):
        out=[]
        def work():
            try:out.append(('ok',fn()))
            except BaseException as e:out.append(('error',str(e)))
        thread=threading.Thread(target=work);thread.start();return thread,out
    def wait(event):R.need(event.wait(10),'thread_event_timeout')
    for phase in ['enqueue','release']:
        f=fixture();entered=threading.Event();resume=threading.Event()
        def slow(*args):entered.set();wait(resume);return True if phase=='enqueue' else copy.deepcopy(f['context'])
        if phase=='enqueue':job=start(lambda:f['enqueue'](guard=slow))
        else:ticket=f['enqueue']();job=start(lambda:f['channel'].release(ticket,slow))
        try:wait(entered);f['owner'].revoke(f['source_dep']);check('慢阶段撤权先完成:'+phase,f['channel'].state()['closed'])
        finally:resume.set()
        job[0].join(15);check('迟到阶段不能交付:'+phase,not job[0].is_alive() and job[1]==[('error','output_closed')] and not f['sink'].payloads);threads+=1;f['owner'].close()
    # 在可信出口内的并发撤权只能排在已开始的这次交付之后。
    entered=threading.Event();resume=threading.Event();started=threading.Event()
    def slow_sink(payload):entered.set();wait(resume);return len(payload)
    f=fixture(sink=Sink(slow_sink));ticket=f['enqueue']();sender=start(lambda:f['channel'].release(ticket,lambda _:f['context']));revoker=None
    try:
        wait(entered)
        def revoke():started.set();return f['owner'].revoke(f['dep'])
        revoker=start(revoke);wait(started)
    finally:resume.set()
    sender[0].join(15);revoker[0].join(15)
    check('交付与撤权实际线程排序',not sender[0].is_alive() and not revoker[0].is_alive() and sender[1][0][1]['status']=='handed_off' and revoker[1]==[('ok',True)] and f['channel'].state()['closed']);threads+=1;f['owner'].close()
    paths=[ROOT/n for n in ['delivery.py','check_delivery.py','delivery-sources.json','coordinator.py','readset.py','typed_validators.py','typed-sources.json','check_readset.py','source/bindings.json','source/selection.json','PROVIDERS.md','DELIVERY.md']]+[C.HELPER,SUITE/'docs/rebirth-c09-extension-design.md']
    return dict(format='panel-result-delivery-check/1',approved=False,runtime_ready=False,all_passed=True,cases_passed=len(checks),checks=checks,methods=35,thread_scenarios=threads,local_socket_scenarios=2,synthetic_source_models_except_meta=True,explicit_synthetic_domain_and_acceptance_guards=True,
        production_authorization_tests_executed=0,production_output_gate_tests_executed=0,browser_port_tests_executed=0,http_ws_tls_tests_executed=0,database_tests_executed=0,device_tests_executed=0,
        sdk_commit=source['sdk_commit'],fixed_sdk_inputs={**source['inputs'],model_path:H.sha(model)},inputs={p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in paths})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sdk',type=Path,required=True);parser.add_argument('--report',action='store_true');args=parser.parse_args();r=run(args.sdk.resolve())
    if args.report:(ROOT/'delivery-report.json').write_bytes(H.encode(r))
    print(json.dumps({k:v for k,v in r.items() if k not in ['checks','inputs','fixed_sdk_inputs']},ensure_ascii=False))
