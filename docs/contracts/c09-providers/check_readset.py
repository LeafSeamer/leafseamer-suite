"""完整分派覆盖与合成提供者读集故障检查；不冒充领域适配器验收。"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
from jsonschema import Draft202012Validator
import readset as R

ROOT=R.ROOT;SUITE=ROOT.parents[2]
HELPER=ROOT.parent/'sdk-transport-handoff/check_handoff.py'
spec=importlib.util.spec_from_file_location('provider_source_helpers',HELPER);H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
INPUTS=[ROOT/'readset.py',ROOT/'check_readset.py',ROOT/'PROVIDERS.md',ROOT/'sources.json',ROOT/'source/bindings.json',ROOT/'source/selection.json',SUITE/'docs/rebirth-c09-extension-design.md',ROOT.parent/'c09-panel/README.md',HELPER]

def fixture(method='controller.getMeta'):
    variant,model,parts=R.assignments(method);sources={};fields={};registry={};now=[1000000000]
    for provider,assigned in parts.items():
        value={'synthetic_provider':provider};fields[provider]={}
        for name,rule in assigned.items():
            leaf='synthetic.'+name;fields[provider][name]=leaf
            if provider=='root':
                cursor=value;path=rule['path'].split('.')
                for segment in path[:-1]:cursor=cursor.setdefault(segment,{})
                cursor[path[-1]]=leaf
        sid=model if provider=='root' else 'synthetic__'+provider
        ref=dict(authority_service_id='controller.synthetic',database_instance_id='database.synthetic',entity_kind='synthetic_source',entity_id=provider,entity_epoch='epoch.1',revision='1',content_digest=R.digest(value))
        sources[provider]=[dict(model=sid,ref=ref,value=value)];registry[sid]=Draft202012Validator({'const':copy.deepcopy(value)})
    context=dict(selection=copy.deepcopy(R.SELECTION),authority=R.BINDINGS['methods'][method]['authority'],method=method,request_id='request.synthetic',input_digest='7'*64,public_binding_digest='1'*64,activation_digest='2'*64,installation_digest='8'*64,approval_digest='9'*64,authorization_digest='3'*64,scope=dict(authority_service_id='controller.synthetic',database_instance_id='database.synthetic'))
    output={k:v for p in fields.values() for k,v in p.items()}
    expected={p:[{k:copy.deepcopy(v) for k,v in s.items() if k!='value'} for s in items] for p,items in sources.items()}
    def source_validator(name,value):return name in registry and registry[name].is_valid(value)
    def result_validator(name,value):return name==variant and Draft202012Validator({'const':output}).is_valid(value)
    def create(**kwargs):return R.ReadSet(context,expected,kwargs.pop('source_validator',source_validator),kwargs.pop('result_validator',result_validator),clock=lambda:now[0],**kwargs)
    return dict(context=context,sources=sources,expected=expected,fields=fields,output=output,create=create,clock=now,source_validator=source_validator,result_validator=result_validator)

def complete(f,a):
    for provider in f['fields']:a.provide(a.ticket(provider),f['sources'][provider],f['fields'][provider])
    return a.seal()

def run(sdk):
    checks=[]
    def check(name,ok=True):R.need(ok,name);checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,TypeError) as e:check(name,reason is None or str(e)==reason)
        else:raise AssertionError(name+':未拒绝')
    source=json.loads((ROOT/'sources.json').read_bytes());raws=H.read_fixed(sdk,source['sdk_commit'],list(source['inputs'])+['contracts/panel-wire/contract/models.schema.json'])
    for path,item in source['inputs'].items():check('固定Git来源:'+path,H.sha(raws[path])==item['sha256'] and raws[path]==(ROOT/item['copy']).read_bytes())
    model_raw=raws['contracts/panel-wire/contract/models.schema.json'];models=json.loads(model_raw)['$defs']
    check('当前选择固定panel4',R.SELECTION['contract_id']=='leafseamer.api.v1.panel4')
    check('来源清单14职责',len(R.BINDINGS['providers'])==14)
    covered=set();variants=set();count=0
    for method in R.BINDINGS['methods']:
        f=fixture(method);a=f['create']();token=complete(f,a)
        check('完整方法读集:'+method,a.consume(f['context'],token)==f['output'])
        denied('方法候选单次:'+method,lambda:a.consume(f['context'],token),'readset_closed')
        covered.update(set(a.parts)-{'root'});variant,model,parts=R.assignments(method)
        check('当前模型与输出字段:'+method,model in models and set(R.BINDINGS['plans'][variant]['fields'])==set(models['panel3__Result_'+variant]['properties']))
        if variant not in variants:count+=sum(len(x) for x in parts.values());variants.add(variant)
    check('全部14提供者均实际参与合成读集',covered==set(R.BINDINGS['providers']))
    check('全部35方法23变体181顶层字段',len(R.BINDINGS['methods'])==35 and len(variants)==23 and count==181)
    # 每一提供者均验证字段缺失、多字段、原件替换、模型、引用与来源集合错误。
    owners={}
    for method in R.BINDINGS['methods']:
        for provider in R.assignments(method)[2]:owners.setdefault(provider,method)
    for provider,method in owners.items():
        for kind in ['missing_field','extra_field','changed_value','changed_ref','changed_model','missing_source','extra_source']:
            f=fixture(method);a=f['create']();ticket=a.ticket(provider);sources=copy.deepcopy(f['sources'][provider]);fields=copy.deepcopy(f['fields'][provider])
            if kind=='missing_field':fields.pop(next(iter(fields)))
            elif kind=='extra_field':fields['not_registered']='x'
            elif kind=='changed_value':sources[0]['value']['synthetic_provider']='other'
            elif kind=='changed_ref':sources[0]['ref']['revision']='2'
            elif kind=='changed_model':sources[0]['model']='other'
            elif kind=='missing_source':sources=[]
            elif kind=='extra_source':sources.append(copy.deepcopy(sources[0]))
            denied(provider+':'+kind,lambda:a.provide(ticket,sources,fields))
            denied(provider+':错误关闭完整读集:'+kind,a.seal,'readset_closed')
    f=fixture();a=f['create']();ticket=a.ticket('root');a.provide(ticket,f['sources']['root'],f['fields']['root'])
    denied('部分结果不能封装',a.seal,'incomplete_readset');a.fail(a.ticket('session'))
    denied('单提供者失败不能返回部分结果',a.seal,'readset_closed')
    f=fixture();a=f['create']();b=f['create']();ticket=a.ticket('root')
    denied('跨读集ticket拒绝',lambda:b.provide(ticket,f['sources']['root'],f['fields']['root']),'provider_ticket')
    denied('自报JSONticket拒绝',lambda:a.provide({'provider':'root'},f['sources']['root'],f['fields']['root']),'provider_ticket')
    denied('同提供者不能重复签ticket',lambda:a.ticket('root'),'provider_ticket')
    a.provide(ticket,f['sources']['root'],f['fields']['root'])
    denied('ticket不能重复使用',lambda:a.provide(ticket,f['sources']['root'],f['fields']['root']),'provider_ticket')
    f=fixture();a=f['create']();wrong=copy.deepcopy(f['fields']['root']);wrong['component_version']='wrong'
    denied('直接字段必须取精确原件路径',lambda:a.provide(a.ticket('root'),f['sources']['root'],wrong),'direct_source_value')
    f=fixture();a=f['create'](source_validator=lambda *args:False)
    denied('真实来源Schema接口拒绝',lambda:a.provide(a.ticket('root'),f['sources']['root'],f['fields']['root']),'source_schema')
    f=fixture();a=f['create'](result_validator=lambda *args:False)
    denied('最终结果Schema接口拒绝',lambda:complete(f,a),'result_schema')
    for label,mutate in [('authorization',lambda c:c.update(authorization_digest='4'*64)),('activation',lambda c:c.update(activation_digest='5'*64)),('navigation',lambda c:c.update(public_binding_digest='6'*64)),('request',lambda c:c.update(request_id='other')),('input',lambda c:c.update(input_digest='0'*64)),('installation',lambda c:c.update(installation_digest='0'*64)),('approval',lambda c:c.update(approval_digest='0'*64))]:
        f=fixture();a=f['create']();token=complete(f,a);c=copy.deepcopy(f['context']);mutate(c)
        denied('消费复核:'+label,lambda:a.consume(c,token),'context_changed')
    for stage in ['ticket','provide','seal','consume']:
        f=fixture();a=f['create'](ttl_ms=1)
        if stage=='ticket':call=lambda:a.ticket('root')
        elif stage=='provide':ticket=a.ticket('root');call=lambda:a.provide(ticket,f['sources']['root'],f['fields']['root'])
        elif stage=='seal':
            for p in f['fields']:a.provide(a.ticket(p),f['sources'][p],f['fields'][p])
            call=a.seal
        else:token=complete(f,a);call=lambda:a.consume(f['context'],token)
        f['clock'][0]+=1000000;denied('截止等号拒绝:'+stage,call,'readset_expired')
    f=fixture();a=f['create']();f['clock'][0]-=1;denied('同域时钟倒退关闭',lambda:a.ticket('root'),'readset_expired')
    f=fixture();a=f['create']();token=complete(f,a);a.invalidate();denied('封装后撤权拒消费',lambda:a.consume(f['context'],token),'readset_closed')
    f=fixture();a=f['create']();token=complete(f,a);other=f['create']();complete(f,other)
    denied('候选不能跨读集',lambda:other.consume(f['context'],token),'candidate_binding')
    f=fixture();snapshot=copy.deepcopy(f['context']);a=f['create']();token=complete(f,a)
    f['context']['request_id']='later';f['sources']['root'][0]['value']['component_version']='later';f['fields']['root']['component_version']='later'
    check('宿主后改输入不替换已封装值',a.consume(snapshot,token)==f['output'])
    f=fixture();a=f['create']();f['expected']['root'][0]['ref']['revision']='99'
    check('宿主后改计划不替换构造时快照',a.consume(f['context'],complete(f,a))==f['output'])
    f=fixture();f['context']['authority']='seamer';denied('角色不能跨方法权威',f['create'],'method_authority')
    f=fixture();a=f['create']();ticket=a.ticket('session');f['clock'][0]+=2000000000
    denied('迟到失败回执不复活读集',lambda:a.fail(ticket),'readset_expired')
    for label,mutate in [('missing_provider',lambda f:f['expected'].pop('session')),('foreign_scope',lambda f:f['expected']['root'][0]['ref'].update(database_instance_id='other')),('duplicate_source',lambda f:f['expected']['session'].append(copy.deepcopy(f['expected']['session'][0]))),('wrong_root_model',lambda f:f['expected']['root'][0].update(model='other'))]:
        f=fixture();mutate(f);denied('读取计划拒绝:'+label,f['create'])
    for value in [float('nan'),9007199254740992,'x'*262145]:denied('有限JSON预算:'+str(type(value)),lambda value=value:R.bounded(value))
    # 验证在锁外执行，撤权不等待慢适配器；两阶段返回都必须复核。
    for phase in ['source','result']:
        f=fixture();started=threading.Event();resume=threading.Event();out=[]
        def delayed(*args):started.set();R.need(resume.wait(5),'test_timeout');return True
        a=f['create'](**{('source_validator' if phase=='source' else 'result_validator'):delayed})
        if phase=='source':ticket=a.ticket('root');call=lambda:a.provide(ticket,f['sources']['root'],f['fields']['root'])
        else:
            for p in f['fields']:a.provide(a.ticket(p),f['sources'][p],f['fields'][p])
            call=a.seal
        def pending():
            try:call();out.append('unexpected_success')
            except R.Unavailable as e:out.append(str(e))
        thread=threading.Thread(target=pending);thread.start()
        try:R.need(started.wait(5),'thread_start');a.invalidate()
        finally:resume.set();thread.join(10)
        check('在途校验撤权:'+phase,not thread.is_alive() and out==['readset_closed'])
    inputs={p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in INPUTS}
    return dict(format='panel-provider-readset-check/1',approved=False,runtime_ready=False,all_passed=True,cases_passed=len(checks),checks=checks,
        methods=35,variants=23,top_level_fields=181,providers=14,concurrency_revocation_scenarios=2,synthetic_source_and_result_schemas=True,
        domain_adapter_tests_executed=0,production_authorization_tests_executed=0,final_output_gate_tests_executed=0,database_tests_executed=0,network_tests_executed=0,browser_tests_executed=0,device_tests_executed=0,
        sdk_commit=source['sdk_commit'],sdk_models_sha256=H.sha(model_raw),inputs=inputs)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sdk',type=Path,required=True);parser.add_argument('--report',action='store_true');args=parser.parse_args();r=run(args.sdk.resolve())
    if args.report:(ROOT/'report.json').write_bytes(H.encode(r))
    print(json.dumps({k:v for k,v in r.items() if k not in ['checks','inputs']},ensure_ascii=False))
