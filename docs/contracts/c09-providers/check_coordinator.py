"""本地失效协调的故障与线程检查；权威事件入口由合成宿主显式触发。"""
import argparse
import copy
import json
from pathlib import Path
import sys
import threading
import uuid
import coordinator as G
import readset as R
import check_readset as C
import check_typed as T

ROOT=R.ROOT;SUITE=C.SUITE;H=C.H


def run(sdk):
    checks=[];thread_scenarios=0
    def check(name,ok=True):R.need(ok,name);checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,TypeError) as e:check(name,reason is None or str(e)==reason)
        else:raise AssertionError(name+':未拒绝')
    def start(fn):
        result=[]
        def target():
            try:result.append(('ok',fn()))
            except BaseException as e:result.append(('error',str(e)))
        thread=threading.Thread(target=target);thread.start();return thread,result
    def joined(job):
        job[0].join(15);R.need(not job[0].is_alive(),'thread_timeout');return job[1][0]
    def wait(event):R.need(event.wait(10),'event_timeout')
    def setup(**limits):
        gate=G.Coordinator(**limits);cleanup=[];dep=gate.register(lambda:cleanup.append('revoked'))
        return gate,dep,cleanup
    for method in R.BINDINGS['methods']:
        gate,dep,cleanup=setup();f=C.fixture(method);a=gate.begin([dep],f['create']);token=C.complete(f,a)
        check('协调后完整消费:'+method,a.consume(f['context'],token)==f['output'])
        denied('协调候选不能重复:'+method,lambda:a.consume(f['context'],token),'managed_read_closed')
        gate.close();check('结束权威清理:'+method,cleanup==['revoked'])
    gate,dep,cleanup=setup();other=G.Coordinator();foreign=other.register(lambda:None);f=C.fixture()
    for name,deps in [('空依赖',[]),('重复依赖',[dep,dep]),('JSON依赖',[{}]),('过多依赖',[dep]*17)]:
        denied(name,lambda:gate.begin(deps,f['create']),'dependency_set')
    denied('跨协调器依赖',lambda:gate.begin([foreign],f['create']),'dependency_stale')
    denied('同形未签发依赖',lambda:gate.begin([G.Dependency(gate)],f['create']),'dependency_stale')
    denied('跨协调器撤销',lambda:gate.revoke(foreign),'dependency_owner')
    denied('缺实际清理接口',lambda:gate.register(None),'dependency_revoker')
    denied('无效构造器',lambda:gate.begin([dep],None),'read_builder')
    denied('构造返回非读集',lambda:gate.begin([dep],lambda:{}),'read_builder_result')
    for key in ['max_reads','max_dependencies']:
        denied('容量不能用布尔:'+key,lambda:G.Coordinator(**{key:True}))
    # 相同依赖的读取和封装都关闭，独立依赖仍可正常完成。
    dep2=gate.register(lambda:None);a=gate.begin([dep],f['create']);b=gate.begin([dep,dep2],f['create']);c=gate.begin([dep2],f['create'])
    ta=C.complete(f,a);tb=b.ticket('root');check('首次撤权',gate.revoke(dep));check('重复撤权幂等',not gate.revoke(dep) and cleanup==['revoked'])
    denied('封装后撤权拒绝消费',lambda:a.consume(f['context'],ta),'managed_read_closed')
    denied('读取中撤权拒绝迟到提交',lambda:b.provide(tb,f['sources']['root'],f['fields']['root']),'managed_read_closed')
    denied('撤销依赖不能复活',lambda:gate.begin([dep],f['create']),'dependency_stale')
    check('无关依赖保持可用',c.consume(f['context'],C.complete(f,c))==f['output']);gate.close();other.close()
    gate,dep,_=setup(max_reads=1,max_dependencies=1);a=gate.begin([dep],f['create'])
    denied('读取容量强制上限',lambda:gate.begin([dep],f['create']),'read_budget')
    denied('依赖容量强制上限',lambda:gate.register(lambda:None),'dependency_budget')
    a.close();a.close();a=gate.begin([dep],f['create']);a.close();check('显式关闭释放容量')
    def broken():raise ValueError('builder_failed')
    denied('构造失败不吞异常',lambda:gate.begin([dep],broken),'builder_failed')
    a=gate.begin([dep],f['create']);denied('不完整封装关闭托管读取',a.seal,'incomplete_readset')
    a=gate.begin([dep],f['create']);token=C.complete(f,a);wrong=dict(f['context'],input_digest='0'*64)
    denied('上下文变化拒绝交付',lambda:a.consume(wrong,token),'context_changed')
    a=gate.begin([dep],f['create']);token=C.complete(f,a);f['clock'][0]+=2000000000
    denied('截止等号拒绝交付',lambda:a.consume(f['context'],token),'readset_expired');gate.close();f=C.fixture()
    gate,dep,_=setup();raw=f['create']();a=gate.begin([dep],lambda:raw)
    denied('底层读集不能重复托管',lambda:gate.begin([dep],lambda:raw),'read_builder_fresh')
    check('拒绝复用不破坏原读取',a.consume(f['context'],C.complete(f,a))==f['output'])
    raw=f['create']();raw.ticket('root')
    denied('已使用读集不能登记',lambda:gate.begin([dep],lambda:raw),'read_builder_fresh')
    gate.close();denied('关闭后不能登记',lambda:gate.register(lambda:None),'coordinator_closed')
    denied('关闭后不能开始',lambda:gate.begin([dep],f['create']),'coordinator_closed')
    gate=G.Coordinator();done=[]
    def failing():done.append('failed');raise RuntimeError('private detail')
    dep=gate.register(failing);a=gate.begin([dep],f['create']);token=C.complete(f,a)
    denied('清理异常有限化',lambda:gate.revoke(dep),'dependency_cleanup')
    denied('清理异常不能恢复读取',lambda:a.consume(f['context'],token),'managed_read_closed')
    gate.register(failing);gate.register(lambda:done.append('last'))
    denied('整体关闭继续执行剩余清理',gate.close,'dependency_cleanup');check('每个清理只执行一次',done==['failed','failed','last']);gate.close()
    # 构造取消之后仍保留在途名额，不能用撤权循环绕过容量。
    gate,dep,_=setup(max_reads=1);entered=threading.Event();release=threading.Event()
    def building():entered.set();wait(release);return f['create']()
    job=start(lambda:gate.begin([dep],building))
    try:
        wait(entered);gate.revoke(dep);fresh=gate.register(lambda:None)
        denied('被撤销的在途构造仍占容量',lambda:gate.begin([fresh],f['create']),'read_budget')
    finally:release.set()
    check('撤权不等待构造且迟到构造拒绝',joined(job)==('error','dependency_stale'));thread_scenarios+=1
    gate.begin([fresh],f['create']).close();gate.close()
    for phase in ['source','result']:
        gate,dep,_=setup();entered=threading.Event();release=threading.Event();f=C.fixture()
        original=f[phase+'_validator']
        def slow(*args):entered.set();wait(release);return original(*args)
        a=gate.begin([dep],lambda:f['create'](**{phase+'_validator':slow}))
        if phase=='source':job=start(lambda:a.provide(a.ticket('root'),f['sources']['root'],f['fields']['root']))
        else:
            for p in f['fields']:a.provide(a.ticket(p),f['sources'][p],f['fields'][p])
            job=start(a.seal)
        try:wait(entered);check('慢校验中撤权先完成:'+phase,gate.revoke(dep))
        finally:release.set()
        check('迟到校验不能恢复读取:'+phase,joined(job)==('error','readset_closed'));thread_scenarios+=1;gate.close()
    # 外部清理故意停住，本地消费已关闭；清理中依赖继续占容量。
    gate=G.Coordinator(max_dependencies=1);entered=threading.Event();release=threading.Event()
    def slow_cleanup():entered.set();wait(release)
    dep=gate.register(slow_cleanup);a=gate.begin([dep],f['create']);token=C.complete(f,a);job=start(lambda:gate.revoke(dep))
    try:
        wait(entered);denied('外部清理未完成也不能消费',lambda:a.consume(f['context'],token),'managed_read_closed')
        denied('清理中依赖继续占容量',lambda:gate.register(lambda:None),'dependency_budget')
    finally:release.set()
    check('慢清理完成',joined(job)==('ok',True));thread_scenarios+=1;gate.close()
    # 消费已经取得串行锁时先完成；随后撤权不声称追回已经返回的本地值。
    gate,dep,_=setup();entered=threading.Event();release=threading.Event();armed=[False];started=threading.Event()
    def clock():
        if armed[0]:entered.set();wait(release)
        return f['clock'][0]
    a=gate.begin([dep],lambda:R.ReadSet(f['context'],f['expected'],f['source_validator'],f['result_validator'],clock=clock));token=C.complete(f,a);armed[0]=True
    consumer=start(lambda:a.consume(f['context'],token));revoker=None
    try:
        wait(entered)
        def revoke():started.set();return gate.revoke(dep)
        revoker=start(revoke);wait(started)
    finally:release.set()
    check('消费先取得串行边界可返回一次',joined(consumer)==('ok',f['output']))
    check('后续撤权完成',joined(revoker)==('ok',True));thread_scenarios+=1;gate.close()
    gate,dep,_=setup();a=gate.begin([dep],f['create']);token=C.complete(f,a);barrier=threading.Barrier(8)
    def racing():barrier.wait(10);return a.consume(f['context'],token)
    jobs=[start(racing) for _ in range(8)];results=[joined(j) for j in jobs]
    check('八线程只交付一次',results.count(('ok',f['output']))==1 and results.count(('error','managed_read_closed'))==7);thread_scenarios+=1;gate.close()
    # 实际固定SDK动态权威：绑定本地上下文摘要，运行Schema子进程，再通过登记的撤销入口失效。
    source=json.loads((ROOT/'typed-sources.json').read_bytes());report_path='contracts/panel-current/report.json'
    raw=H.read_fixed(sdk,source['sdk_commit'],[report_path])[report_path];inventory=dict(json.loads(raw)['inputs']);inventory[report_path]=H.sha(raw)
    fixed=H.read_fixed(sdk,source['sdk_commit'],inventory);check('动态依赖全部固定Git字节',all(H.sha(b)==inventory[p] for p,b in fixed.items()))
    directory=SUITE/'logs'/('coordinated-provider-'+uuid.uuid4().hex)
    for p,b in fixed.items():dest=directory/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
    sys.path.insert(0,str(directory/'contracts/panel-current'));P=T.load('provider',directory/'contracts/panel-current/provider.py');sys.modules['provider']=P
    D=T.load('coordinated_dynamic_fixture',directory/'contracts/panel-current/fixtures.py')
    F=T.load('coordinated_views',ROOT/'typed-source/fixtures.py');views=F.examples();observed=T.source_examples(views)['baseline__Observation']
    contract=T.T.Contract(fixed['contracts/panel-wire/contract/models.schema.json'],R.SELECTION);worker_calls=0;original=P.instance
    def counted(*args):
        nonlocal worker_calls
        worker_calls+=1;return original(*args)
    P.instance=counted
    def real():
        fixture=D.fixture(value=observed['values'],documents={D.FORM:D.document(D.obj(program={'type':'string'}))})
        context=fixture['context'];context.update(method='controller.getDeviceState',slot='/values');context['source_ref']['content_digest']=R.digest(observed)
        authority=D.authority(fixture);f=C.fixture(context['method']);f['context'].update(input_digest=context['input_digest'],scope={k:context['source_ref'][k] for k in ['authority_service_id','database_instance_id']})
        for target,key in [('public_binding_digest','public_binding'),('activation_digest','activation_ref'),('installation_digest','installation_ref'),('approval_digest','approval_ref'),('authorization_digest','authorization_ref')]:f['context'][target]=R.digest(context[key])
        output=copy.deepcopy(views['ObservationView']);output['values']=copy.deepcopy(fixture['qualified']);_,model,parts=R.assignments(context['method'])
        item=dict(model=model,ref=copy.deepcopy(context['source_ref']),value=copy.deepcopy(observed));expected={p:[dict(model=model,ref=item['ref'])] for p in parts}
        def dynamic(method,path,kind,value):
            R.need((method,path,kind)==(context['method'],context['slot'],'qualified'),'dynamic_binding')
            return authority.consume(context,authority.prepare(context,value))==value
        validators=contract.bind(context['method'],dynamic)
        def build():return validators.readset(f['context'],expected,source_guard=lambda c,m,v:m==model and v==observed and R.digest(v)==context['source_ref']['content_digest'],result_guard=lambda c,n,v:v==output,clock=lambda:f['clock'][0])
        def fill(a):
            for p,fields in parts.items():a.provide(a.ticket(p),[item],{k:copy.deepcopy(output[k]) for k in fields})
            return a.seal()
        return authority,context,f['context'],output,build,fill
    try:
        authority,context,current,output,build,fill=real();a=build();token=fill(a);authority.revoke()
        check('基础读集本身没有外部权威事件订阅',a.consume(current,token)==output)
        authority,context,current,output,build,fill=real();gate=G.Coordinator();dep=gate.register(authority.revoke);a=gate.begin([dep],build);token=fill(a)
        check('实际动态值经过协调后完整交付',a.consume(current,token)==output);gate.close()
        authority,context,current,output,build,fill=real();gate=G.Coordinator();dep=gate.register(authority.revoke);a=gate.begin([dep],build);token=fill(a)
        gate.revoke(dep)
        denied('实际动态权威封装后撤权拒绝交付',lambda:a.consume(current,token),'managed_read_closed')
        denied('实际SDK权威也已完成撤销',lambda:authority.prepare(context,output['values']),'authority_stale');gate.close()
    finally:P.instance=original
    check('实际Schema子进程数',worker_calls==3)
    paths=[ROOT/n for n in ['coordinator.py','check_coordinator.py','readset.py','check_readset.py','typed_validators.py','check_typed.py','typed-sources.json','typed-source/fixtures.py','typed-source/source/legacy-cases.json','source/bindings.json','source/selection.json','PROVIDERS.md']]+[SUITE/'docs/rebirth-c09-extension-design.md',C.HELPER]
    return dict(format='panel-provider-coordinator-check/1',approved=False,runtime_ready=False,all_passed=True,cases_passed=len(checks),checks=checks,methods=35,thread_scenarios=thread_scenarios,validator_subprocess_calls=worker_calls,actual_dynamic_post_seal_revocation_scenarios=1,
        explicit_synthetic_domain_guards=True,authority_event_listener_tests_executed=0,production_authorization_tests_executed=0,final_output_gate_tests_executed=0,database_tests_executed=0,network_tests_executed=0,browser_tests_executed=0,device_tests_executed=0,
        sdk_commit=source['sdk_commit'],dynamic_provider_report_sha256=H.sha(raw),dynamic_provider_inputs=inventory,inputs={p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in paths})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sdk',type=Path,required=True);parser.add_argument('--report',action='store_true');args=parser.parse_args();r=run(args.sdk.resolve())
    if args.report:(ROOT/'coordinator-report.json').write_bytes(H.encode(r))
    print(json.dumps({k:v for k,v in r.items() if k not in ['checks','inputs','dynamic_provider_inputs']},ensure_ascii=False))
