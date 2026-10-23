"""离线验证协议资料和人工模型轨迹；不是Controller／Seamer实现或设备测试。"""
from pathlib import Path
from datetime import datetime
from copy import deepcopy
from importlib.metadata import version
import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec
import rfc8785

ROOT=Path(__file__).resolve().parent

def strict_loads(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('重复JSON键')
            result[key]=value
        return result
    def bad_constant(value):raise ValueError('非有限JSON数值：'+value)
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=bad_constant)
    # JCS还检查孤立代理字符和不可安全表达的整数。
    rfc8785.dumps(value)
    return value

def load(name):return strict_loads((ROOT/name).read_text(encoding='utf-8'))

def walk(value):
    yield value
    if isinstance(value,dict):
        for child in value.values():yield from walk(child)
    elif isinstance(value,list):
        for child in value:yield from walk(child)

def contract_errors(model,value):
    """仅检查可由本份JSON独立证明的约束；不伪造鉴权／时序／网络证据。"""
    errors=[]
    for node in walk(value):
        if not isinstance(node,dict):continue
        if 'not_before' in node and 'not_after' in node:
            if node['not_before']>=node['not_after']:errors.append('非空时间窗口反转')
        if {'context_id','issued_at','expires_at','ttl_ms'}<=node.keys():
            delta=(datetime.fromisoformat(node['expires_at'])-datetime.fromisoformat(node['issued_at'])).total_seconds()*1000
            if delta<=0 or abs(delta-node['ttl_ms'])>0.001:errors.append('上下文有效期不一致')
        if {'schema_id','digest','dialect','document'}<=node.keys():
            document=node['document']
            try:Draft202012Validator.check_schema(document)
            except Exception:errors.append('内嵌Schema不是合法2020-12')
            if node['digest']!='sha256:'+hashlib.sha256(rfc8785.dumps(document)).hexdigest():errors.append('内嵌Schema摘要不匹配')
            for part in walk(document):
                if isinstance(part,dict):
                    for key in ('$ref','$dynamicRef'):
                        if key in part and not part[key].startswith('#'):errors.append('内嵌Schema禁止外部引用')
        if {'action_id','completion','parameters_schema'}<=node.keys():
            if node['completion']['default'] not in node['completion']['supported']:errors.append('默认完成等级未声明支持')
        if {'state','barrier_ack','expected_control','target','effective_record_durable'}<=node.keys():
            if int(node['target']['version'])<=int(node['expected_control']['version']):errors.append('控制版本未增加')
            if node['state']=='effective':
                ack=node['barrier_ack']
                matches={'operation_id':node['operation_id'],'device_id':node['device_id'],'barrier_id':node['barrier_id'],'controller_boot_id':node['controller_boot_id'],'worker_boot_id':node['worker_boot_id'],
                    'control_epoch':node['expected_control']['epoch'],'installed_version':node['target']['version']}
                if any(ack[k]!=v for k,v in matches.items()):errors.append('屏障证据身份不匹配')
                if set(ack['in_flight_command_ids'])!=set(node['in_flight_snapshot']):errors.append('生效记录丢失在途')
                if set(ack['unresolved_command_ids'])!=set(node['unresolved_snapshot']):errors.append('生效记录丢失未知结果')
        if {'effective_version','pending_change','control_epoch'}<=node.keys() and node['pending_change']:
            if int(node['pending_change']['target_version'])<=int(node['effective_version']):errors.append('待生效版本未增加')
        if node.get('kind')=='state_machine':
            states=node['states']
            if len(states)!=len(set(states)):errors.append('状态ID重复')
            if node['initial_state'] not in states:errors.append('初始状态引用无效')
            for transition in node['transitions']:
                if transition['from_state'] not in states or transition['to_state'] not in states:errors.append('转换状态引用无效')
        if {'phase','outcome','attempts','retry_policy'}<=node.keys():
            attempts=node['attempts']
            if len({x['attempt_id'] for x in attempts})!=len(attempts):errors.append('尝试ID重复')
            if node['phase']=='queued' and attempts:
                if not node['retry_policy'] or attempts[-1]['outcome']!='failed':errors.append('无合法重试策略回到排队')
            if node['outcome']=='succeeded' and not attempts:errors.append('成功没有尝试记录')
            if node['effect_status']=='verified' and node['completion']['achieved']!='effect_verified':errors.append('效果已核实缺完成证据等级')
    return errors

def validate_trace(case):
    if case['kind']=='barrier':
        pending=False;acked=False;saved=False;sent=set();ack=None
        for step in case['steps']:
            event=step['event']
            if event=='pending_saved':
                if pending:return False
                pending=True
                if step['version']!='9':return False
            elif event=='send_old':
                if acked:return False
                sent.add(step['command'])
            elif event=='fence_ack':
                if not pending or step['version']!='9' or step['worker']!='w1' or step['barrier']!='b1' or set(step['in_flight'])!=sent:return False
                acked=True;ack=step
            elif event=='effective_saved':
                if not acked or any(step[k]!=ack[k] for k in ('version','worker','barrier','in_flight')):return False
                saved=True
            elif event=='report_effective':
                if not saved:return False
            elif event in ('timeout','remain_protected'):
                if not pending:return False
            else:return False
        return True
    guards=set(case['guards']);steps=case['steps']
    if not steps or steps[0]!='queued':return False
    edges={
        ('queued','dispatching'):{'intent_durable'},('dispatching','awaiting_evidence'):{'permit_consumed'},
        ('awaiting_evidence','finished:succeeded'):{'completion_durable'},('awaiting_evidence','queued'):{'retry_safe_failure','retry_budget'},
        ('queued','finished:cancelled'):{'not_sent_proven'},('dispatching','finished:cancelled'):{'not_sent_proven'},
        ('dispatching','finished:unknown'):{'paused_latched'},('awaiting_evidence','finished:unknown'):{'paused_latched'},
        ('finished:unknown','resolution'):{'paused_latched'}}
    return all((a,b) in edges and edges[a,b]<=guards for a,b in zip(steps,steps[1:]))

def check_refs(document,prefix):
    for part in walk(document):
        if isinstance(part,dict) and '$ref' in part:
            reference=part['$ref']
            if not reference.startswith(prefix):raise AssertionError('意外外部引用：'+reference)
            current=document
            for bit in reference[2:].split('/'):
                current=current[bit.replace('~1','/').replace('~0','~')]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');args=parser.parse_args()
    subprocess.run([sys.executable,str(ROOT/'build_contracts.py'),'--check'],check=True)
    subprocess.run([sys.executable,str(ROOT/'build_examples.py'),'--check'],check=True)
    schema=load('first-loop.schema.json');Draft202012Validator.check_schema(schema);check_refs(schema,'#/$defs/')
    checker=FormatChecker();positive=negative=semantic_negative=0;models=set();all_cases=load('examples.json')
    seen=set()
    for case in all_cases:
        if case['case_id'] in seen:raise AssertionError('用例ID重复')
        seen.add(case['case_id'])
        test=dict(schema,**{'$ref':'#/$defs/'+case['model']})
        errors=list(Draft202012Validator(test,format_checker=checker).iter_errors(case['instance']))
        if (not errors)!=case['schema_valid']:
            raise AssertionError(case['case_id']+' Schema结果错误：'+str([x.message for x in errors][:3]))
        semantic=contract_errors(case['model'],case['instance']) if not errors else ['结构无效']
        if (not semantic)!=case['contract_valid']:raise AssertionError(case['case_id']+' 语义结果错误：'+str(semantic))
        if case['contract_valid']:positive+=1;models.add(case['model'])
        elif case['schema_valid']:semantic_negative+=1
        else:negative+=1
    api_ops=0
    for name in ('controller.openapi.json','seamer.openapi.json'):
        api=load(name);validate_spec(api);check_refs(api,'#/components/schemas/')
        expected=json.loads(json.dumps(schema['$defs']).replace('#/$defs/','#/components/schemas/'))
        assert api['components']['schemas']==expected,'OpenAPI与公共Schema漂移'
        ids=[]
        for path,methods in api['paths'].items():
            for method,operation in methods.items():
                api_ops+=1;ids.append(operation['operationId'])
                assert 'responses' in operation
                declared={x['name'] for x in operation.get('parameters',[]) if x['in']=='path'}
                assert declared==set(re.findall(r'{(\w+)}',path))
                assert operation.get('security',api.get('security')),'API不能匿名写入'
                for part in walk(operation):
                    if isinstance(part,dict) and 'schema' in part and isinstance(part['schema'],dict):
                        model=part['schema'].get('$ref','').split('/')[-1]
                        if model and model!='Id':assert model in models,'缺少端点模型正例：'+model
                # 按实际OpenAPI方言再验证端点请求／响应正例，而非只检查独立Schema。
                for part in walk(operation):
                    if isinstance(part,dict) and 'content' in part:
                        spec=part['content'].get('application/json',{}).get('schema')
                        if spec:
                            model=spec['$ref'].split('/')[-1]
                            instance=next(c['instance'] for c in all_cases if c['model']==model and c['contract_valid'])
                            Draft202012Validator({'$schema':schema['$schema'],'components':api['components'],'$ref':spec['$ref']},format_checker=checker).validate(instance)
        assert len(ids)==len(set(ids)),'重复operationId'
    trace_cases=load('boundary-traces.json')
    for case in trace_cases:
        assert validate_trace(case)==case['valid'],case['case_id']+' 轨迹结果错误'
    vectors=load('canonical-vectors.json')
    for vector in vectors:assert rfc8785.dumps(vector['input']).decode('utf-8')==vector['canonical'],vector['case_id']
    identities=load('identity-vectors.json')
    for vector in identities:
        body=deepcopy(vector['body'])
        for key in ('context_id','idempotency_key','correlation_id'):body.pop(key,None)
        if vector['operation']=='acquireControl':body.setdefault('force',False)
        assert rfc8785.dumps(body).decode('utf-8')==vector['canonical'],vector['case_id']
    capability_cases=load('capability-cases.json')
    for case in capability_cases:
        Draft202012Validator.check_schema(case['schema'])
        assert Draft202012Validator(case['schema'],format_checker=checker).is_valid(case['parameters'])==case['valid'],case['case_id']
    wire=load('invalid-wire.json')
    for case in wire:
        try:strict_loads(case['raw'])
        except (ValueError,rfc8785.CanonicalizationError):continue
        raise AssertionError('未拒绝非法原始JSON：'+case['case_id'])
    # 第二种语言检查固定向量；仅覆盖这些向量，不宣称完整JCS实现验证。
    subprocess.run(['node',str(ROOT/'validate_vectors.cjs')],check=True)
    evidence_files=sorted(p for p in ROOT.iterdir() if p.suffix in ('.json','.py','.cjs') and p.name!='validation-report.json')
    report={'scope':'离线契约／静态模型校验；不是服务、设备、IPC或并发运行验证','schema_definitions':len(schema['$defs']),
        'openapi_documents':2,'http_operations_including_ws_upgrade':api_ops,'positive_examples':positive,'structural_negative_examples':negative,
        'semantic_negative_examples':semantic_negative,'boundary_traces':len(trace_cases),'canonical_vectors_python_and_node':len(vectors),'identity_vectors_python_and_node':len(identities),'capability_parameter_cases':len(capability_cases),'invalid_wire_examples':len(wire),
        'versions':{name:version(name) for name in ['jsonschema','openapi-spec-validator','rfc8785']},
        'runtimes':{'python':platform.python_version(),'node':subprocess.check_output(['node','--version'],text=True).strip()},
        'artifact_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence_files},'all_passed':True}
    if args.report:(ROOT/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
