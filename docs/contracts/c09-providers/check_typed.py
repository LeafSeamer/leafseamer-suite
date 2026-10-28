"""固定完整模型和有条件动态批准的真实验证，不实现生产鉴权或来源事务。"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import uuid
import readset as R
import typed_validators as T
import check_readset as C

ROOT=R.ROOT;H=C.H;SUITE=C.SUITE

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

EXPECTED={
 'CapabilityView':[('/actions/0/parameters_schema_ref','schema_ref'),('/actions/0/result_schema_ref','schema_ref'),('/triggers/0/payload_schema_ref','schema_ref'),('/state_schema_ref','schema_ref')],
 'ObservationView':[('/values','qualified')],
 'DraftDefinitionView':[('/content','raw'),('/metadata','raw')],
 'PublishedDefinitionView':[('/content','raw'),('/metadata','raw')],
 'RecoveryPlanView':[]}

def source_examples(views):
    meta=dict(protocol_version=R.SELECTION['contract_id'],component_version='0.1.0',service_id='controller.synthetic',service_boot_id='boot.1',features=['controller.getMeta'],limits_profile='sim-panel',selection=copy.deepcopy(R.SELECTION))
    clock=dict(views['ClockView'],observation_id='clock.1',service_id='controller.synthetic',service_boot_id='boot.1',source_label='synthetic',source_authentication='trusted_network')
    observation={k:copy.deepcopy(v) for k,v in views['ObservationView'].items() if k not in ['projection_status','values']}
    observation.update(provider_boot_id='provider.1',device_session_id='session.1',values=copy.deepcopy(views['ObservationView']['values']['value']),clock=dict(status='unsynchronized',source_ref=None,sampled_at=None,offset_ms=None,uncertainty_ms=None,sample_age_ms=None,policy_revision='1'))
    draft={k:copy.deepcopy(views['DraftDefinitionView'][k]) for k in ['definition_id','revision','content','content_digest','selection_digest','metadata_revision','metadata']}
    draft['scope']=dict(authority_service_id='seamer.synthetic',database_instance_id='database.synthetic')
    draft['content_digest']='sha256:'+R.digest(draft['content']);draft['selection_digest']='sha256:'+R.digest(draft['content']['selections'])
    return {'baseline__Meta':meta,'time_public__S12__PublicClock':clock,'baseline__Observation':observation,'lifecycle__DraftRecord':draft}

def actual_readset(method,record,output,validators,source_guard=None,result_guard=None):
    f=C.fixture(method);_,model,parts=R.assignments(method)
    ref=dict(f['sources']['root'][0]['ref'],content_digest=R.digest(record))
    source=dict(model=model,ref=ref,value=copy.deepcopy(record))
    expected={p:[dict(model=model,ref=copy.deepcopy(ref))] for p in parts}
    # 合成宿主显式批准本次完整原件与预期派生结果，不用Schema通过代替批准。
    approved_record=copy.deepcopy(record);approved_output=copy.deepcopy(output)
    a=validators.readset(f['context'],expected,source_guard=source_guard or (lambda c,m,v:m==model and v==approved_record),
        result_guard=result_guard or (lambda c,n,v:v==approved_output),clock=lambda:f['clock'][0])
    for p,assigned in parts.items():a.provide(a.ticket(p),[source],{name:copy.deepcopy(output[name]) for name in assigned})
    return a,f['context']

def run(sdk):
    checks=[]
    def check(name,ok=True):R.need(ok,name);checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,KeyError) as e:check(name,reason is None or str(e)==reason)
        else:raise AssertionError(name+':未拒绝')
    source=json.loads((ROOT/'typed-sources.json').read_bytes());raws=H.read_fixed(sdk,source['sdk_commit'],source['inputs'])
    for p,item in source['inputs'].items():check('固定原件:'+p,H.sha(raws[p])==item['sha256'] and (item['copy'] is None or (ROOT/item['copy']).read_bytes()==raws[p]))
    model_bytes=raws['contracts/panel-wire/contract/models.schema.json'];contract=T.Contract(model_bytes,R.SELECTION)
    # 引用闭包只遍历Schema位置，const/enum中的同名数据字段不当成引用。
    models=json.loads(model_bytes)['$defs'];refs=[]
    def walk(node):
        if type(node) is not dict:return
        if '$ref' in node:refs.append(node['$ref'])
        for key in ['$defs','properties','patternProperties','dependentSchemas']:
            for child in node.get(key,{}).values():walk(child)
        for key in ['allOf','anyOf','oneOf','prefixItems']:
            for child in node.get(key,[]):walk(child)
        for key in ['items','additionalProperties','propertyNames','contains','not','if','then','else','unevaluatedItems','unevaluatedProperties']:
            if key in node:walk(node[key])
    for node in models.values():walk(node)
    check('1463模型引用保持本地完整闭包',refs and all(r.startswith('#/$defs/') and r[len('#/$defs/'):] in models for r in refs))
    denied('修改模型字节不能获得配置',lambda:T.Contract(model_bytes+b' ',R.SELECTION),'fixed_models')
    denied('旧选择不能用于当前模型',lambda:T.Contract(model_bytes,{**R.SELECTION,'contract_id':'leafseamer.api.v1.panel3'}),'selection')
    saved=R.SELECTION;changed={**saved,'contract_digest':'sha256:'+'0'*64}
    try:
        R.SELECTION=changed
        denied('仅替换选择配置不能混用旧模型',lambda:T.Contract(model_bytes,changed),'selection')
        f=C.fixture()
        denied('已构造模型也拒绝随后选择漂移',lambda:contract.readset(f['context'],f['expected']),'selection')
    finally:R.SELECTION=saved
    denied('未知模型不能回退开放值',lambda:contract.validate('unknown',{}),'model_name')
    denied('网络模型名不能加载',lambda:contract.validate('https://example.invalid/schema',{}),'model_name')
    F=load('typed_result_examples',ROOT/'typed-source/fixtures.py');views=F.examples();views['MetaView']['protocol_version']=R.SELECTION['contract_id']
    methods={};dynamic_calls=0
    for method,binding in R.BINDINGS['methods'].items():
        view=binding['variant'];methods.setdefault(view,method);seen=[]
        def approved(m,p,k,v):seen.append((p,k));return m==method
        validator=contract.bind(method,approved)
        check('当前模型完整结果:'+method,validator.result(view,views[view]))
        check('准确动态位置:'+method,seen==EXPECTED.get(view,[]));dynamic_calls+=len(seen)
        default=contract.bind(method)
        check('动态入口缺失默认拒绝:'+method,default.result(view,views[view]) is (not bool(EXPECTED.get(view,[]))))
    field_cases=0
    for view,method in methods.items():
        validator=contract.bind(method,lambda *args:True)
        for field in views[view]:
            bad=copy.deepcopy(views[view]);bad.pop(field);field_cases+=1
            check('真实结果缺字段拒绝:'+view+':'+field,not validator.result(view,bad))
        bad=dict(views[view],credentials={});check('真实结果额外原件拒绝:'+view,not validator.result(view,bad))
        for path,_ in EXPECTED.get(view,[]):
            selected=contract.bind(method,lambda m,p,k,v:p!=path)
            check('逐动态槽批准不可省略:'+view+':'+path,not selected.result(view,views[view]))
    check('真实结果181字段完整覆盖',field_cases==181 and len(methods)==23)
    check('动态批准必须明确True',not contract.bind('controller.getDeviceState',lambda *a:1).result('ObservationView',views['ObservationView']))
    wrong=C.fixture('controller.getMeta')
    denied('同形结果也不能跨方法绑定验证器',lambda:contract.bind('seamer.getMeta').readset(wrong['context'],wrong['expected']),'validator_method')
    denied('缺领域关联与批准守卫不能构造读集',lambda:contract.readset(wrong['context'],wrong['expected']),'domain_guards_required')
    def reject(label,view,mutate):
        bad=copy.deepcopy(views[view]);mutate(bad);check(label,not contract.bind(methods[view],lambda *a:True).result(view,bad))
    reject('时钟半径不足','ClockView',lambda v:v.update(error_radius_ns='1'))
    reject('未知命令不能解锁继续','CommandView',lambda v:v.update(outcome='unknown',automation_continuation='eligible'))
    reject('未知清资源无处置','CommandView',lambda v:v.update(outcome='unknown',resource_status='clear',resolution_summary=None))
    reject('预检unknown不能伪通过','PreflightView',lambda v:v['checks'][0].update(status='unknown'))
    reject('恢复修订不前进','RecoveryOperationView',lambda v:v.update(committed_run_revision=v['previous_run_revision']))
    reject('无新执行不能造新命令','RecoveryOperationView',lambda v:v['visible_new_command_ids'].append('invented'))
    reject('时间文本必须实际合法','ObservationView',lambda v:v.update(observed_at='2026-99-99T10:00:00Z'))
    recovery=copy.deepcopy(views['RecoveryPlanView']);q=copy.deepcopy(views['ObservationView']['values'])
    recovery['items'][0].update(evidence_summaries=[q,copy.deepcopy(q)],parameters_summary=copy.deepcopy(q))
    seen=[];validator=contract.bind(methods['RecoveryPlanView'],lambda m,p,k,v:seen.append((p,k)) or True)
    check('恢复嵌套动态摘要实际结构',validator.result('RecoveryPlanView',recovery))
    check('每项证据与参数都经过批准',seen==[('/items/0/evidence_summaries/0','qualified'),('/items/0/evidence_summaries/1','qualified'),('/items/0/parameters_summary','qualified')])
    check('恢复非空摘要缺批准拒绝',not contract.bind(methods['RecoveryPlanView']).result('RecoveryPlanView',recovery))
    records=source_examples(views);source_cases=0
    for model,value in records.items():
        check('实际来源模型正例:'+model,contract.validate(model,value))
        for field in value:
            bad=copy.deepcopy(value);bad.pop(field);source_cases+=1;check('实际来源模型缺字段:'+model+':'+field,not contract.validate(model,bad))
        check('实际来源模型额外字段:'+model,not contract.validate(model,dict(value,unregistered=True)))
    for method,model,view in [('controller.getMeta','baseline__Meta','MetaView'),('controller.getClock','time_public__S12__PublicClock','ClockView')]:
        validator=contract.bind(method);a,c=actual_readset(method,records[model],views[view],validator)
        check('真实Schema读集完整消费:'+view,a.consume(c,a.seal())==views[view])
        bad=copy.deepcopy(records[model]);bad.pop(next(iter(bad)))
        denied('重算摘要也不能放行非法来源:'+view,lambda:actual_readset(method,bad,views[view],validator),'source_schema')
    validator=contract.bind('controller.getMeta')
    denied('合法模型不能绕过来源守卫拒绝',lambda:actual_readset('controller.getMeta',records['baseline__Meta'],views['MetaView'],validator,source_guard=lambda *a:False),'source_schema')
    a,c=actual_readset('controller.getMeta',records['baseline__Meta'],views['MetaView'],validator,result_guard=lambda *a:False)
    denied('合法结果不能绕过领域关联拒绝',a.seal,'result_schema')
    # 固定动态提供者及全部依赖从Git物化，实际运行隔离Schema子进程。
    report_path='contracts/panel-current/report.json';raw=H.read_fixed(sdk,source['sdk_commit'],[report_path])[report_path];old_report=json.loads(raw)
    inventory=dict(old_report['inputs']);inventory[report_path]=H.sha(raw)
    fixed=H.read_fixed(sdk,source['sdk_commit'],inventory);check('动态提供者完整原件',all(H.sha(b)==inventory[p] for p,b in fixed.items()))
    directory=SUITE/'logs'/('typed-provider-'+uuid.uuid4().hex)
    for p,b in fixed.items():dest=directory/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
    sys.path.insert(0,str(directory/'contracts/panel-current'))
    P=load('provider',directory/'contracts/panel-current/provider.py');sys.modules['provider']=P
    D=load('typed_dynamic_fixture',directory/'contracts/panel-current/fixtures.py')
    observed=records['baseline__Observation'];f=D.fixture(value=observed['values'],documents={D.FORM:D.document(D.obj(program={'type':'string'}))})
    f['context'].update(method='controller.getDeviceState',slot='/values')
    authority=D.authority(f);worker_calls=0;original=P.instance
    def counted(*args):
        nonlocal worker_calls
        worker_calls+=1;return original(*args)
    P.instance=counted
    def dynamic(method,path,kind,value):
        R.need((method,path,kind)==('controller.getDeviceState','/values','qualified'),'dynamic_binding')
        token=authority.prepare(f['context'],value);return authority.consume(f['context'],token)==value
    try:
        output=copy.deepcopy(views['ObservationView']);output['values']=copy.deepcopy(f['qualified'])
        validator=contract.bind('controller.getDeviceState',dynamic)
        a,c=actual_readset('controller.getDeviceState',observed,output,validator)
        check('真实动态子进程与读集串联',a.consume(c,a.seal())==output)
        bad=copy.deepcopy(output);bad['values']['value']['program']=3
        a,c=actual_readset('controller.getDeviceState',observed,bad,validator)
        denied('静态允许动态内容但实际Schema拒绝',a.seal,'instance_invalid')
        denied('动态失败关闭整个读集',a.seal,'readset_closed')
        bad=copy.deepcopy(output);bad['values']['value']['secret']='not_allowed'
        a,c=actual_readset('controller.getDeviceState',observed,bad,validator)
        denied('动态字段权利缺失不能裁剪',a.seal,'field_denied')
        a,c=actual_readset('controller.getDeviceState',observed,output,validator);authority.revoke()
        denied('动态批准撤销拒绝封装',a.seal,'authority_stale')
    finally:P.instance=original
    check('动态实际子进程调用数',worker_calls==2)
    paths=[ROOT/name for name in ['typed_validators.py','check_typed.py','typed-sources.json','typed-source/fixtures.py','typed-source/source/legacy-cases.json','readset.py','source/bindings.json','source/selection.json','PROVIDERS.md']]+[SUITE/'docs/rebirth-c09-extension-design.md',ROOT/'check_readset.py',C.HELPER]
    return dict(format='panel-typed-provider-check/1',approved=False,runtime_ready=False,all_passed=True,cases_passed=len(checks),checks=checks,selected_models=1463,methods=35,result_variants=23,result_missing_field_cases=field_cases,source_models_tested=len(records),source_missing_field_cases=source_cases,
        explicit_synthetic_dynamic_policy=True,explicit_synthetic_domain_guards=True,validator_subprocess_calls=worker_calls,typed_readset_positive_scenarios=3,production_authorization_tests_executed=0,final_output_gate_tests_executed=0,database_tests_executed=0,network_tests_executed=0,browser_tests_executed=0,device_tests_executed=0,
        sdk_commit=source['sdk_commit'],sdk_models_sha256=H.sha(model_bytes),dynamic_provider_report_sha256=H.sha(raw),dynamic_provider_inputs=inventory,inputs={p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in paths})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sdk',type=Path,required=True);parser.add_argument('--report',action='store_true');args=parser.parse_args();r=run(args.sdk.resolve())
    if args.report:(ROOT/'typed-report.json').write_bytes(H.encode(r))
    print(json.dumps({k:v for k,v in r.items() if k not in ['checks','inputs','dynamic_provider_inputs']},ensure_ascii=False))
