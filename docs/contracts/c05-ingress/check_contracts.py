"""离线候选检查；权威、时效、AST结果为明确的人工前提，非服务实现。"""
import argparse
import copy
import hashlib
import json
import platform
import sqlite3
import subprocess
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from openapi_spec_validator import validate_spec
from build_contracts import HERE, SID, VERSION, DF06, ROUTES, build, encoded
import check_storage

ROOT = HERE.parents[2]
REPORT = HERE/'reference-report.json'
INPUTS = [HERE/p for p in ('README.md','build_contracts.py','check_contracts.py','check_storage.py',
                           'ingress.sql','ingress.schema.json','ingress.openapi.json')]
INPUTS += [DF06, *check_storage.SQL[:2]]
INPUTS += [ROOT/'docs'/p for p in ('rebirth-c05-event-sync-design.md','rebirth-c04-automation-design.md','rebirth-df04-storage-design.md')]
SCOPE = dict(authority_service_id='seamer',database_instance_id='db')


def sha(v): return hashlib.sha256(v).hexdigest()
def digest(v): return 'sha256:'+sha(rfc8785.dumps(v))
def seal(v, key): v[key]=digest({k:x for k,x in v.items() if k!=key}); return v
def reference(kind, ident, revision='1', hash_value=None):
    return dict(kind=kind,scope=copy.deepcopy(SCOPE),object_id=ident,revision=revision,
                digest=hash_value or digest({'synthetic':ident}))
def inc(v):
    n=int(v)+1
    if n>=10**20: raise ValueError('U20_exhausted')
    return str(n)


def choose(rule_result, transitions):
    """仅三值结果裁决；不是AST解释器。"""
    if rule_result is not None:
        return {'true':('accepted',None),'false':('no_match',None),'unknown':('evaluation_unknown',None)}[rule_result]
    true=[v for v in transitions if v['result']=='true']
    unknown=[v for v in transitions if v['result']=='unknown']
    if not true: return ('evaluation_unknown' if unknown else 'no_match',None)
    priority=max(v['priority'] for v in true)
    if any(v['priority']>=priority for v in unknown): return ('evaluation_unknown',None)
    best=[v for v in true if v['priority']==priority]
    return ('ambiguous',None) if len(best)>1 else ('accepted',best[0]['transition_id'])


def fixture():
    binding=dict(registration_id='registration',revision='1',owner_service_id='controller',
        database_instance_id='controller_db',provider_id='provider',provider_boot_id='boot',
        device_id='device',trigger_id='trigger',capability_version='1.0.0',
        capture_policy_id='policy',capture_policy_revision='1',delivery_semantics='discrete')
    origin=dict(source_key=dict(**SCOPE,registration_id='registration',source_stream_id='stream',source_epoch='source_epoch'),
        binding_ref=binding,event_id='event',source_sequence='1',
        payload=dict(schema_ref=reference('payload_schema','payload'),value={'value':True}))
    inbox=dict(scope=copy.deepcopy(SCOPE),inbox_id='inbox',revision='1',origin=origin,origin_digest=digest(origin),
        first_observation=dict(clock_ref=reference('clock','clock'),receive_tick_ns='9007199254740993',
        delivery_binding_ref=reference('delivery','delivery'),age_evidence_ref=reference('age_evidence','age')))
    cursor=dict(scope=copy.deepcopy(SCOPE),ingest_epoch='epoch',receive_sequence='9007199254740993')
    target=dict(run_id='run',definition_id='definition',definition_version='1',
        artifact_ref=reference('artifact','artifact'),trigger_binding_ref=reference('trigger_binding','trigger_binding'))
    match=dict(scope=copy.deepcopy(SCOPE),match_set_id='match',source_key=copy.deepcopy(origin['source_key']),
        registry_revision='1',targets=[target])
    snap=dict(scope=copy.deepcopy(SCOPE),snapshot_id='snapshot',run_id='run',run_revision_before='2',
        ingest_revision_before='4',slot_revision='1',artifact_ref=copy.deepcopy(target['artifact_ref']),
        source_revision_refs=[reference('source_revision','source_revision')],
        observation_refs=[reference('observation','observation')],input_snapshot_ref=reference('input_snapshot','input'),
        business_state_ref=reference('business_state','state'),rule_result=None,
        transitions=[dict(transition_id='high',priority=2,result='true'),dict(transition_id='low',priority=1,result='unknown')],
        receive_cursor=copy.deepcopy(cursor))
    decision=dict(scope=copy.deepcopy(SCOPE),decision_id='decision',run_id='run',definition_version='1',
        artifact_ref=copy.deepcopy(target['artifact_ref']),receive_cursor=copy.deepcopy(cursor),
        run_revision_before='2',run_revision_after='3',ingest_revision_before='4',ingest_revision_after='5',
        result='accepted',reason_code='eligible',selected_transition_id='high',execution_id='execution')
    execution=dict(scope=copy.deepcopy(SCOPE),run_id='run',execution_id='execution',
        artifact_ref=copy.deepcopy(target['artifact_ref']),receive_cursor=copy.deepcopy(cursor),
        execution_binding_ref=reference('execution_binding','binding'),plan_ref=reference('execution_plan','plan'),
        expected_steps='1',sealed=True)
    commit=dict(scope=copy.deepcopy(SCOPE),commit_id='commit',receive_cursor=copy.deepcopy(cursor),
        source_revision_before='8',source_revision_after='9',trigger_disposition='eligible_decision_recorded',notification_id='notification')
    batch=dict(contract_version=VERSION,inbox=inbox,match_set=match,snapshots=[snap],decisions=[decision],executions=[execution],commit=commit)
    reseal(batch)
    context=dict(scope=copy.deepcopy(SCOPE),source_key=copy.deepcopy(origin['source_key']),binding=copy.deepcopy(binding),
        origin=copy.deepcopy(origin),first_observation=copy.deepcopy(inbox['first_observation']),
        targets=copy.deepcopy(match['targets']),registry_revision='1',epoch='epoch',last_sequence='9007199254740992',
        source_revision='8',source_sequence='0',observed_only=False,run_revision={'run':'2'},ingest_revision={'run':'4'},
        evaluations={'run':copy.deepcopy(snap)},schemas={digest({'synthetic':'payload'}):
            dict(type='object',properties={'value':{'type':'boolean'}},required=['value'],additionalProperties=False)})
    return batch,context


def reseal(b):
    """人工夹具重新封摘要；不生成测试预期，也不批准内容或权威。"""
    i,m,c=b['inbox'],b['match_set'],b['commit']
    i['origin_digest']=digest(i['origin']); seal(i,'content_digest')
    m['targets_digest']=digest(m['targets'])
    ir=reference('inbox',i['inbox_id'],i['revision'],i['content_digest'])
    mr=reference('match_set',m['match_set_id'],m['registry_revision'],digest(m))
    for s in b['snapshots']:
        s['inbox_ref']=copy.deepcopy(ir); s['match_set_ref']=copy.deepcopy(mr); seal(s,'snapshot_digest')
    for d in b['decisions']:
        d['inbox_ref']=copy.deepcopy(ir); d['match_set_ref']=copy.deepcopy(mr)
        snapshots=[s for s in b['snapshots'] if s['run_id']==d['run_id']]
        d['snapshot_ref']=reference('evaluation_snapshot',snapshots[0]['snapshot_id'],'1',snapshots[0]['snapshot_digest']) if snapshots else None
        seal(d,'decision_digest')
    for e in b['executions']:
        d=next(d for d in b['decisions'] if d['execution_id']==e['execution_id'])
        e['decision_ref']=reference('trigger_decision',d['decision_id'],'1',d['decision_digest'])
    c['inbox_ref']=ir; c['match_set_ref']=mr
    c['decision_refs']=[{k:d[k] for k in ('run_id','decision_id','decision_digest')} for d in b['decisions']]
    c['decision_set_digest']=digest(c['decision_refs']); seal(c,'commit_digest')


def batch_error(b,ctx):
    """限定语义检查：正文结构由调用者先校验；授权和来源年龄取证尚未实现。"""
    i,m,c=b['inbox'],b['match_set'],b['commit']
    objects=[i,m,c,*b['snapshots'],*b['decisions'],*b['executions']]
    if any(x['scope']!=ctx['scope'] for x in objects): return 'scope'
    if i['origin']!=ctx['origin'] or i['origin']['source_key']!=ctx['source_key'] or i['origin']['binding_ref']!=ctx['binding']: return 'source'
    if i['first_observation']!=ctx['first_observation']: return 'first_observation'
    payload=i['origin']['payload']; sr=payload['schema_ref']
    if sr['kind']!='payload_schema' or sr['scope']!=ctx['scope'] or sr['digest'] not in ctx['schemas']: return 'payload_schema'
    if not Draft202012Validator(ctx['schemas'][sr['digest']]).is_valid(payload['value']): return 'payload_value'
    if i['origin']['source_sequence']!=inc(ctx['source_sequence']): return 'source_sequence'
    cursor=c['receive_cursor']
    if cursor['scope']!=ctx['scope'] or cursor['ingest_epoch']!=ctx['epoch'] or cursor['receive_sequence']!=inc(ctx['last_sequence']): return 'cursor'
    if c['source_revision_before']!=ctx['source_revision'] or c['source_revision_after']!=inc(ctx['source_revision']): return 'source_revision'
    if m['targets']!=ctx['targets'] or m['registry_revision']!=ctx['registry_revision'] or m['source_key']!=ctx['source_key']: return 'match_set'
    runs=[x['run_id'] for x in m['targets']]
    if runs!=sorted(set(runs)) or [d['run_id'] for d in b['decisions']]!=runs: return 'decision_coverage'
    if len({x['decision_id'] for x in b['decisions']})!=len(runs): return 'decision_identity'
    if len({s['run_id'] for s in b['snapshots']})!=len(b['snapshots']): return 'snapshot_duplicate'
    snapshots={s['run_id']:s for s in b['snapshots']}
    if set(snapshots)-set(runs): return 'snapshot_extra'
    for d,t in zip(b['decisions'],m['targets']):
        rid=d['run_id']; changed=d['result'] in ('accepted','protected','evaluation_unknown','ambiguous')
        if d['receive_cursor']!=cursor or d['artifact_ref']!=t['artifact_ref'] or d['definition_version']!=t['definition_version']: return 'decision_binding'
        if d['run_revision_before']!=ctx['run_revision'][rid] or d['ingest_revision_before']!=ctx['ingest_revision'][rid]: return 'revision_before'
        if d['run_revision_after']!=(inc(d['run_revision_before']) if changed else d['run_revision_before']) or d['ingest_revision_after']!=inc(d['ingest_revision_before']): return 'revision_after'
        if (d['execution_id'] is not None)!=(d['result']=='accepted'): return 'execution_presence'
        if ctx['observed_only'] and d['result']=='accepted': return 'observed_only'
        if d['result'] in ('accepted','no_match','evaluation_unknown','ambiguous'):
            if rid not in snapshots: return 'snapshot_missing'
            s=snapshots[rid]; trusted=ctx['evaluations'][rid]
            for k in ('run_revision_before','ingest_revision_before','slot_revision','artifact_ref','source_revision_refs',
                      'observation_refs','input_snapshot_ref','business_state_ref','rule_result','transitions'):
                if s[k]!=trusted[k]: return 'evaluation_context'
            if s['receive_cursor']!=cursor: return 'snapshot_cursor'
            if s['rule_result'] is not None and s['transitions']: return 'mixed_evaluation'
            if len({v['transition_id'] for v in s['transitions']})!=len(s['transitions']): return 'transition_duplicate'
            if choose(s['rule_result'],s['transitions'])!=(d['result'],d['selected_transition_id']): return 'selection'
        elif d['selected_transition_id'] is not None: return 'selection'
    expected=[d['execution_id'] for d in b['decisions'] if d['result']=='accepted']
    if [e['execution_id'] for e in b['executions']]!=expected: return 'execution_coverage'
    for e in b['executions']:
        d=next(d for d in b['decisions'] if d['execution_id']==e['execution_id'])
        if e['run_id']!=d['run_id'] or e['receive_cursor']!=cursor or e['artifact_ref']!=d['artifact_ref']: return 'execution_binding'
        if e['plan_ref']['kind']!='execution_plan' or e['execution_binding_ref']['kind']!='execution_binding': return 'execution_ref_kind'
        if e['plan_ref']['scope']!=ctx['scope'] or e['execution_binding_ref']['scope']!=ctx['scope']: return 'execution_ref_scope'
    eligible=any(d['result'] in ('accepted','no_match','evaluation_unknown','ambiguous') for d in b['decisions'])
    disposition='eligible_decision_recorded' if eligible else ('suppressed' if b['decisions'] else 'observed_only')
    if c['trigger_disposition']!=disposition: return 'disposition'
    canonical=copy.deepcopy(b); reseal(canonical)
    if canonical!=b: return 'digest_or_ref'
    return None


def run():
    build(check=True)
    schema=json.loads((HERE/'ingress.schema.json').read_bytes())
    api=json.loads((HERE/'ingress.openapi.json').read_bytes())
    Draft202012Validator.check_schema(schema); validate_spec(api)
    registry=Registry().with_resource(SID,Resource.from_contents(schema))
    def valid(model,v):
        return Draft202012Validator({'$ref':SID+'#/$defs/'+model},registry=registry).is_valid(v)
    def projected(model,v):
        return Draft202012Validator({'$ref':'#/components/schemas/'+model,'components':api['components']}).is_valid(v)
    records=[]
    def expect(name,ok):
        assert ok,name
        records.append(dict(id=name,passed=True))
    batch,ctx=fixture()
    expect('结构-完整批次',valid('CommittedBatch',batch))
    expect('关联-完整批次',batch_error(batch,ctx) is None)
    samples=dict(CommittedBatch=batch,SubmitEvent=dict(contract_version=VERSION,origin=batch['inbox']['origin'],
        origin_digest=batch['inbox']['origin_digest'],delivery_binding_ref=reference('delivery','delivery'),
        age_evidence_ref=reference('age_evidence','age')),
        LookupEvent=dict(contract_version=VERSION,source_key=ctx['source_key'],event_id='event',origin_digest=batch['inbox']['origin_digest']),
        ProviderReceipt=dict(contract_version=VERSION,receipt_id='receipt',receipt_revision='1',source_key=ctx['source_key'],
            event_id='event',origin_digest=batch['inbox']['origin_digest'],ingest_state='committed',duplicate=False),
        LookupResult=dict(state='not_found',receipt=None),Error=dict(code='unavailable',request_id='request'))
    for model,value in samples.items():
        expect('结构-'+model,valid(model,value) and projected(model,value))
        for field in value:
            bad=copy.deepcopy(value); del bad[field]
            expect('缺字段-'+model+'-'+field,not valid(model,bad) and not projected(model,bad))
        bad=copy.deepcopy(value);bad['unexpected']=True
        expect('额外字段-'+model,not valid(model,bad) and not projected(model,bad))
    for bad in ('01','-1','1\n','1\x00','100000000000000000000',9007199254740993):
        expect('U20反例-'+repr(bad),not valid('Counter',bad))
    expect('U20精确大整数',inc('9007199254740992')=='9007199254740993')
    try: inc('99999999999999999999'); raise AssertionError('回绕')
    except ValueError: expect('U20上限关闭',True)
    for state in ('committed','indeterminate','historically_closed'):
        v=dict(state=state,receipt=samples['ProviderReceipt'] if state=='committed' else None)
        expect('查原状态-'+state,valid('LookupResult',v))
    for field in ('run_id','decision_refs','decision_set_digest','receive_cursor','receive_sequence'):
        v=copy.deepcopy(samples['ProviderReceipt']);v[field]='hidden'
        expect('provider禁止内部字段-'+field,not valid('ProviderReceipt',v))
    v=copy.deepcopy(samples['SubmitEvent']);v['live']=True
    expect('provider不得自报live',not valid('SubmitEvent',v))
    # 以下全部重算摘要，防止把摘要一致误认作来源/集合/前态正确。
    changes=[
        ('来源世代',lambda b:b['inbox']['origin']['source_key'].update(source_epoch='other')),
        ('首次观察延寿',lambda b:b['inbox']['first_observation'].update(receive_tick_ns='9007199254740994')),
        ('跨epoch',lambda b:b['commit']['receive_cursor'].update(ingest_epoch='other')),
        ('游标重复',lambda b:b['commit']['receive_cursor'].update(receive_sequence='9007199254740992')),
        ('来源修订跳跃',lambda b:b['commit'].update(source_revision_after='10')),
        ('相同count换run',lambda b:b['match_set']['targets'][0].update(run_id='other')),
        ('registry修订',lambda b:b['match_set'].update(registry_revision='2')),
        ('转换同count换unknown',lambda b:b['snapshots'][0]['transitions'][1].update(transition_id='other')),
        ('删unknown',lambda b:b['snapshots'][0]['transitions'].pop()),
        ('快照前态',lambda b:b['snapshots'][0].update(slot_revision='2')),
        ('决定多一项',lambda b:b['decisions'].append(copy.deepcopy(b['decisions'][0]))),
        ('决定少一项',lambda b:(b['decisions'].clear(),b['executions'].clear())),
        ('进度未增',lambda b:b['decisions'][0].update(ingest_revision_after='4')),
        ('run修订未增',lambda b:b['decisions'][0].update(run_revision_after='2')),
        ('选错转换',lambda b:b['decisions'][0].update(selected_transition_id='low')),
        ('遗漏执行',lambda b:b['executions'].clear()),
        ('执行错误run',lambda b:b['executions'][0].update(run_id='other')),
        ('执行错误引用kind',lambda b:b['executions'][0]['plan_ref'].update(kind='other')),
        ('公开汇总错',lambda b:b['commit'].update(trigger_disposition='suppressed')),
    ]
    for name,change in changes:
        v=copy.deepcopy(batch);change(v);reseal(v)
        expect('重算摘要仍拒绝-'+name,valid('CommittedBatch',v) and batch_error(v,ctx) is not None)
    v=copy.deepcopy(batch);v['inbox']['origin']['payload']['value']={'value':'wrong'}
    reseal(v);c=copy.deepcopy(ctx);c['origin']=copy.deepcopy(v['inbox']['origin'])
    expect('动态值二次校验',valid('CommittedBatch',v) and batch_error(v,c)=='payload_value')
    c=copy.deepcopy(ctx);c['observed_only']=True
    expect('来源锁存禁止执行',batch_error(batch,c)=='observed_only')
    for results, expected in [
        ([(2,'true'),(1,'unknown')],('accepted','t0')),
        ([(2,'true'),(2,'unknown')],('evaluation_unknown',None)),
        ([(2,'true'),(3,'unknown')],('evaluation_unknown',None)),
        ([(2,'true'),(2,'true')],('ambiguous',None)),
        ([(1,'false')],('no_match',None)), ([(1,'unknown')],('evaluation_unknown',None))]:
        ts=[dict(transition_id='t'+str(n),priority=p,result=r) for n,(p,r) in enumerate(results)]
        expect('三值-'+str(results),choose(None,ts)==expected)
    for method,path,op,req,res,codes,role in ROUTES:
        record=api['paths'][path][method]
        expect('HTTP身份-'+op,record['security']==([{'ProviderBearer':[]}] if role=='provider' else [{'InternalMTLS':[]}]))
        expect('HTTP版本-'+op,record['parameters'][0]['required'] and record['parameters'][0]['schema']=={'const':VERSION})
        expect('HTTP不缓存-'+op,all(v['headers']['Cache-Control']['schema']=={'const':'no-store'} for v in record['responses'].values()))
    # 从provider响应根走引用闭包，不能通过共享components误用内部模型。
    seen=set()
    def walk(v):
        if isinstance(v,list):
            for x in v:walk(x)
        elif isinstance(v,dict):
            if '$ref' in v:
                name=v['$ref'].rsplit('/',1)[1]
                if name not in seen: seen.add(name);walk(api['components']['schemas'][name])
            for k,x in v.items():
                if k not in ('$ref','const','enum','examples','default'):walk(x)
    for model in ('ProviderReceipt','LookupResult','Error'):walk({'$ref':'#/components/schemas/'+model})
    expect('provider响应闭包隔离',not seen & {'ReceiveCursor','IngressCommit','TriggerDecision','MatchSet','CommittedBatch'})
    sql_results=check_storage.run()
    return dict(all_passed=True,runtime_approved=False,checks=len(records)+len(sql_results),
        contract_checks=len(records),sqlite_checks=len(sql_results),results=records+sql_results,
        tools=dict(python=platform.python_version(),sqlite_reference=sqlite3.sqlite_version),
        runtime_validation=dict(product_services=0,authentication=0,device=0,concurrency=0,disk_crash=0),
        limitations=['权威索引、授权、年龄和AST结果为人工前提','仅连续规范事件及部分pending锁存；完整保护和GC事务未实现',
                    'SQL BODY为占位，不与JSON夹具构成端到端writer；预算仅存储占位','参考SQLite非产品批准引擎'],
        input_sha256={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in INPUTS})


def bindings(staged=False):
    def read(p):
        return subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else p.read_bytes()
    report=json.loads(read(REPORT))
    assert report['all_passed'] is True
    assert set(report['input_sha256'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
    for p in INPUTS: assert sha(read(p))==report['input_sha256'][p.relative_to(ROOT).as_posix()],p
    print('报告字节绑定通过:',len(INPUTS),'；未重跑用例')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true')
    args=p.parse_args()
    if args.check_report: bindings(args.staged)
    else:
        report=run()
        if args.report: REPORT.write_bytes(encoded(report))
        print('摄取候选离线检查通过:',report['checks'])
