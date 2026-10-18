"""离线结构与有限判定器。没有 OBS、HTTP、SQLite、进程或真实并发执行。"""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT=Path(__file__).resolve().parent


def load(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()


def obs_decision(v):
    frames=v['frames']
    if [x['kind'] for x in frames]!=['set_send','set_ack','query_send','query_result']:return 'kind'
    anchors=('command_id','attempt_id','worker_boot_id','device_session_id','collection_generation','catalog_revision')
    if len({x['evidence_id'] for x in frames})!=4 or any(x[k]!=v[k] for x in frames for k in anchors):return 'identity'
    seq=[int(x['io_seq']) for x in frames];ticks=[int(x['tick_ns']) for x in frames]
    if any(a>=b for a,b in zip(seq,seq[1:])) or any(a>b for a,b in zip(ticks,ticks[1:])):return 'order'
    if v['set_request_id']==v['query_request_id'] or any(x['protocol_request_id']!=v['set_request_id' if i<2 else 'query_request_id'] for i,x in enumerate(frames)):return 'request'
    if frames[1]['success'] is not True:return 'ack'
    if frames[3]['success'] is not True or frames[3]['scene_uuid']!=v['target_scene_uuid'] or frames[0]['scene_uuid']!=v['target_scene_uuid']:return 'predicate'
    if frames[0]['success'] is not None or frames[2]['success'] is not None or frames[1]['scene_uuid'] is not None or frames[2]['scene_uuid'] is not None:return 'frame_shape'
    now=int(v['evaluation_tick_ns'])
    if now>=int(v['deadline_tick_ns']):return 'deadline'
    if not 0<=now-ticks[-1]<v['max_query_age_ms']*1000000:return 'age'
    if not v['catalog_current'] or not v['fixture_current']:return 'generation'
    if not v['durable']:return 'durability'
    return 'verified'


def overlaps(a,b):return a==b or a.startswith(b+'/') or b.startswith(a+'/')


def proof_decision(v):
    f=v['failed_footprint']
    if not v['graph_complete'] or not f['complete']:return 'unknown'
    if v['control_dependency']:return 'dependent'
    affected=f['writes']+f['failure_writes']+f['resources']
    downstream=v['successor_reads']+v['successor_writes']+v['successor_resources']
    if any(overlaps(a,b) for a in affected for b in downstream):return 'dependent'
    return 'independent'


def can_continue(c,safe_classes):
    return (c['context']=='simple_sequence' and not c['required'] and c['outcome']=='failed' and
        c['failure_class'] in safe_classes and c['resource_status']=='clear' and c['release_proved'] and
        c['proof_current'] and c['proof_verdict']=='independent' and c['gates_valid'])


def semantic_error(model,v):
    if model=='CatalogBinding':
        for k in ('scene_id','obs_scene_uuid'):
            if len({x[k] for x in v['entries']})!=len(v['entries']):return 'catalog_identity'
    if model=='RecoverySnapshot':
        if v['preview_digest']!=digest({k:x for k,x in v.items() if k!='preview_digest'}):return 'preview_digest'
        if int(v['issued_tick_ns'])>=int(v['expires_tick_ns']):return 'preview_window'
    if model=='RecoveryOperation' and int(v['committed_run_revision'])!=int(v['previous_run_revision'])+1:return 'revision_advance'
    if model=='ObsCompletionBundle':
        result=obs_decision(v)
        if result!='verified':return result
    if model=='IndependenceProof' and v['verdict']!=proof_decision(v):return 'proof_verdict'
    return None


def consume_sequence(c):
    """将事务视为原子步的串行交错模型；不证明数据库真的具有这些约束。"""
    s=c['snapshot'];ctx=dict(c['current']);records={};consumed=False;outputs=[];executions=0
    for a in c['actions']:
        if not a['authorized']:result='forbidden'
        elif not a['storage_healthy']:result='protected'
        elif a['key'] in records:result='existing' if records[a['key']]==a['request_digest'] else 'request_conflict'
        elif semantic_error('RecoverySnapshot',s):result='invalid_snapshot'
        elif consumed or ctx['run_revision']!=s['run_revision']:result='conflict'
        elif any(ctx[k]!=s[k] for k in ctx if k!='run_revision'):result='stale'
        elif not int(s['issued_tick_ns'])<=int(a['now_tick_ns'])<int(s['expires_tick_ns']):result='expired'
        elif s['unresolved_command_ids']:result='unresolved'
        else:
            result='accepted';consumed=True;records[a['key']]=a['request_digest'];executions+=1
            ctx['run_revision']=str(int(ctx['run_revision'])+1)
        outputs.append(result)
    assert executions<=1,'一个预览不得产生多个恢复执行'
    return outputs


def main():
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');args=p.parse_args()
    for source in ('build_contracts.py','build_cases.py'):
        subprocess.run([sys.executable,str(ROOT/source),'--check'],check=True)
    schema=load(ROOT/'contracts.schema.json');public=load(ROOT.parent/'first-loop.schema.json')
    Draft202012Validator.check_schema(schema)
    registry=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in (schema,public)])
    def refs(node):
        if isinstance(node,dict):
            if '$ref' in node:registry.resolver(schema['$id']).lookup(node['$ref'])
            for v in node.values():refs(v)
        elif isinstance(node,list):
            for v in node:refs(v)
    refs(schema)
    def validator(model):return Draft202012Validator(dict(schema,**{'$ref':'#/$defs/'+model}),registry=registry,format_checker=FormatChecker())
    cases=load(ROOT/'cases.json');seen=set();models=set();positive=negative=semantic_negative=0
    for group in cases.values():
        for c in group:
            assert c['case_id'] not in seen,c['case_id'];seen.add(c['case_id'])
    for c in cases['examples']:
        errors=list(validator(c['model']).iter_errors(c['instance']))
        assert (not errors)==c['schema_valid'],(c['case_id'],[e.message for e in errors][:2])
        if errors:negative+=1;continue
        error=semantic_error(c['model'],c['instance'])
        assert error==c['semantic_error'],(c['case_id'],error)
        if error:semantic_negative+=1
        else:positive+=1;models.add(c['model'])
    assert models==set(schema['$defs']),'每个候选模型须有正例'
    for c in cases['obs_cases']:
        validator('ObsCompletionBundle').validate(c['bundle'])
        assert obs_decision(c['bundle'])==c['expected'],(c['case_id'],obs_decision(c['bundle']))
    for c in cases['proof_cases']:
        validator('IndependenceProof').validate(c['proof'])
        # 判定器重算结论，不能相信自报 verdict。
        assert proof_decision(c['proof'])==c['expected'],c['case_id']
    for c in cases['continue_cases']:assert can_continue(c['input'],c['safe_failure_classes'])==c['expected'],c['case_id']
    for c in cases['recovery_cases']:
        validator('RecoverySnapshot').validate(c['snapshot'])
        assert consume_sequence(c)==c['expected'],(c['case_id'],consume_sequence(c))
    files=sorted([x for x in ROOT.iterdir() if x.is_file() and x.name!='validation-report.json']+
        [ROOT.parent/'first-loop.schema.json',ROOT.parent.parent/'rebirth-f06-f07-design.md'])
    report=dict(contract='f06-f07/0.1.0-draft.1',scope='候选结构、有限证据／依赖判定及事务串行交错模型；不是真实并发或设备测试',
        schema_definitions=len(schema['$defs']),positive_examples=positive,structural_negative_examples=negative,
        semantic_negative_examples=semantic_negative,obs_cases=len(cases['obs_cases']),proof_cases=len(cases['proof_cases']),
        continue_cases=len(cases['continue_cases']),recovery_cases=len(cases['recovery_cases']),
        runtime_acceptance_cases_executed=0,all_passed=True,
        versions=dict(python=platform.python_version(),jsonschema=version('jsonschema'),rfc8785=version('rfc8785')),
        input_sha256={str(x.relative_to(ROOT.parent.parent)).replace('\\','/'):hashlib.sha256(x.read_bytes()).hexdigest() for x in files})
    if args.report:(ROOT/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
