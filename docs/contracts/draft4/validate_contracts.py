"""draft.4 离线契约判定；可信上下文为人工夹具，不是运行认证。"""
import argparse
from copy import deepcopy as cp
from datetime import datetime
from fractions import Fraction
import hashlib
import importlib.util
from importlib.metadata import version
import json
from math import ceil, floor
import platform
import subprocess
import sys
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec
from referencing import Registry, Resource
import rfc8785
import build_contracts as current
from build_contracts import ROOT, PARENT, OLD, VERSION, IPC_VERSION

def source(path):
    spec=importlib.util.spec_from_file_location('source_'+path.parent.name+'_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

# 旧判定器按原模块环境装载，避免其生成器误指向当前版。
sys.modules['build_contracts']=source(OLD/'build_contracts.py')
try:previous=source(OLD/'validate_contracts.py')
finally:sys.modules['build_contracts']=current
load=previous.load
walk=previous.walk
digest=previous.digest
DOMAIN=('clock_domain_id','descriptor_digest')
def domain(v):return {k:v[k] for k in DOMAIN}
def same(*values):return all(domain(v)==domain(values[0]) for v in values)
def unsigned(v,key):return {k:x for k,x in v.items() if k!=key}
def profile_ref(v):return {k:v[k] for k in ('profile_id','revision','profile_digest')}
def evidence_ref(v):return {k:v[k] for k in ('evidence_id','evidence_digest')}
def sample_ref(v):return dict(sample_id=v['sample_id'],sample_digest=digest(v))

def initial_bound(e):
    span=int(e['capture_end_tick_ns'])-int(e['capture_start_tick_ns'])
    b=abs(int(e['system_offset_ns']))+int(e['root_dispersion_ns'])+Fraction(int(e['root_delay_ns']),2)
    return ceil((b+int(e['source_extra_bound_ns'])+int(e['read_quantization_bound_ns'])+span*(1+Fraction(e['drift_bound_ppm'],1000000)))/1000000)

def semantics(model,v):
    errors=previous.semantics(model,v)
    for n in walk(v):
        if not isinstance(n,dict):continue
        if 'descriptor_version' in n:
            h=digest({k:x for k,x in n.items() if k not in DOMAIN})
            if n['descriptor_digest']!=h or n['clock_domain_id']!='clock_'+h[7:]:errors.append('descriptor_digest')
        if {'profile_digest','model_id','validation_report_ref'}<=n.keys():
            if digest(unsigned(n,'profile_digest'))!=n['profile_digest']:errors.append('profile_digest')
        if {'evidence_digest','capture_end_tick_ns'}<=n.keys():
            if digest(unsigned(n,'evidence_digest'))!=n['evidence_digest']:errors.append('time_evidence_digest')
            if int(n['capture_start_tick_ns'])>int(n['capture_end_tick_ns']):errors.append('capture_order')
            if n['bound_state']=='conditional' and n['uncertainty_at_capture_ms']!=initial_bound(n):errors.append('time_bound')
        if {'all_write_exits_fenced','barrier_id'}<=n.keys() and not n['all_write_exits_fenced']:errors.append('barrier_fenced')
        if n.get('barrier_ack') and not same(n,n['barrier_ack']):errors.append('barrier_domain')
        if {'frames','policy_id'}<=n.keys():
            if any(not same(n,f) for f in n['frames']):errors.append('obs_descriptor')
        if {'command_id','attempts','admission'}<=n.keys():
            attempts={a['attempt_id']:a for a in n['attempts']}
            for e in n['completion_evidence']+n['resource_release_evidence']:
                if e['attempt_id'] in attempts and not same(e,attempts[e['attempt_id']]):errors.append('attempt_domain')
                if e.get('obs_bundle') and not same(e,e['obs_bundle']):errors.append('bundle_domain')
        if {'basis','capture_sample_id','event_id'}<=n.keys():
            if n['basis']=='trusted_utc' and n['utc_basis']['capture_sample_ref']['sample_id']!=n['capture_sample_id']:errors.append('age_sample_binding')
            if n['basis']=='causal_capture':
                b=n['causal_basis'];elapsed=int(b['received_tick_ns'])-int(b['challenge_sent_tick_ns'])
                if elapsed<0 or n['upper_age_ms']<ceil(Fraction(elapsed,1000000)):errors.append('causal_age_bound')
    return errors

def time_interval(c):
    """只有完整链、外部批准与所有新鲜度边界成立才返回UTC区间。"""
    s,e,p=c['sample'],c['evidence'],c['profile']
    if any(semantics(n,v) for n,v in [('ClockSample',s),('TimeBoundEvidence',e),('TimeBoundProfile',p)]):return None
    if not same(s,e,c['trusted_domain']):return None
    state=c['active_time_state']
    if any(e[k]!=state[k] for k in state):return None
    if p['profile_digest'] not in c['approved_profile_digests']:return None
    if s['quality']!='synchronized' or e['bound_state']!='conditional' or s['mode']!='system_disciplined':return None
    if s['time_evidence_ref']!=evidence_ref(e) or s['time_profile_ref']!=profile_ref(p) or e['profile_ref']!=profile_ref(p):return None
    if any(s[k]!=e[k] for k in ('provider_id','provider_boot_id','clock_generation','source_ref','source_auth','drift_bound_ppm')):return None
    if s['policy_revision']!=e['time_policy_revision'] or s['sample_tick_ns']!=e['capture_end_tick_ns'] or s['estimated_utc_ms']!=e['wall_read_utc_ms']:return None
    if s['uncertainty_ms']!=e['uncertainty_at_capture_ms'] or s['max_sample_age_ms']!=p['max_sample_age_ms']:return None
    if any(e[k]!=p[k] for k in ('backend','parser_profile_id','model_id','configured_source_set_digest','drift_bound_ppm','source_extra_bound_ns','read_quantization_bound_ns')):return None
    if e['source_auth'] not in p['allowed_source_auth'] or e['source_auth']=='unverified':return None
    span=int(e['capture_end_tick_ns'])-int(e['capture_start_tick_ns'])
    if not 0<=span<=p['max_capture_span_ms']*1000000:return None
    elapsed_ns=int(c['now_tick_ns'])-int(s['sample_tick_ns'])
    if not 0<=elapsed_ns<p['max_sample_age_ms']*1000000:return None
    # 源年龄在采集开始处取上界，再累加采集跨度及后续外推时间，禁止接收时刻刷新。
    if int(e['source_age_at_capture_ns'])+span+elapsed_ns>=p['max_source_age_ms']*1000000:return None
    elapsed=Fraction(elapsed_ns,1000000)
    b=initial_bound(e)+ceil(Fraction(p['drift_bound_ppm'],1000000)*elapsed)
    if b>p['max_uncertainty_ms']:return None
    center=s['estimated_utc_ms']+elapsed
    return floor(center-b),ceil(center+b)

def linked(kind,c):
    if kind=='assessment':
        v=c['assessment'];s=c['sample'];interval=time_interval(c)
        if interval is None or not same(v,s) or semantics('ClockAssessment',v):return False
        if v['sample_id']!=s['sample_id'] or v['clock_generation']!=s['clock_generation'] or v['policy_revision']!=s['policy_revision']:return False
        if v['time_evidence_ref']!=s['time_evidence_ref'] or v['time_profile_ref']!=s['time_profile_ref'] or v['evaluated_tick_ns']!=c['now_tick_ns']:return False
        elapsed=Fraction(int(c['now_tick_ns'])-int(s['sample_tick_ns']),1000000)
        return v['eligible_for_absolute'] and (v['utc_lower_ms'],v['utc_upper_ms'])==interval and v['sample_age_ms']==ceil(elapsed) and v['uncertainty_now_ms']==initial_bound(c['evidence'])+ceil(Fraction(s['drift_bound_ppm'],1000000)*elapsed)
    if kind=='age':
        proof=c['proof'];a=c['capture'];b=c['evaluation'];basis=proof['utc_basis']
        ia=time_interval(a);ib=time_interval(b)
        if semantics('EventAgeProof',proof) or ia is None or ib is None:return False
        for prefix,part in [('capture',a),('evaluation',b)]:
            if basis[prefix+'_sample_ref']!=sample_ref(part['sample']) or basis[prefix+'_evidence_ref']!=evidence_ref(part['evidence']) or not same(basis[prefix+'_domain'],part['sample']):return False
        if ib[1]<ia[0]:return False
        return proof['lower_age_ms']==max(0,ib[0]-ia[1]) and proof['upper_age_ms']==ib[1]-ia[0]
    if kind=='time':
        interval=time_interval(c)
        if interval is not None and 'expected_interval' in c and list(interval)!=c['expected_interval']:return False
        return interval is not None
    if not c.get('bootstrap_authenticated'):return False
    if kind=='handshake':
        i,a=c['request'],c['ack']
        if a['reply_to']!=i['message_id']:return False
        if any(i[k]!=a[k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id')):return False
        for f in (i,a):
            d=f['body']['clock_domain_descriptor']
            if semantics('ClockDomainDescriptor',d) or not same(f,d,c['trusted_domain']):return False
        return True
    if not previous.linked(kind,c):return False
    if kind=='recovery':
        s=c['preview']['snapshot']
        return not semantics('RecoveryPreview',c['preview']) and same(s,c['trusted_domain']) and int(s['issued_tick_ns'])<=int(c['now_tick_ns'])<int(s['expires_tick_ns'])
    frames=[c[k] for k in ('install','ack','dispatch','request','frame') if k in c]
    if any(not same(f,c['trusted_domain']) for f in frames):return False
    if kind=='guard':
        i,a,d=c['install'],c['ack'],c['dispatch'];g=i['body']['guard'];p=d['body']['permit'];w=d['body']['send_window']
        if not same(i,g,p,w):return False
        if g['time_required']:
            b=i['body'];s=b['clock_sample'];sg=b['schedule_guard'];e=b['time_evidence'];profile=b['time_profile']
            if not same(g,s,sg,e):return False
            if g['clock_sample_ref']!=sample_ref(s) or g['time_evidence_ref']!=evidence_ref(e) or g['time_profile_ref']!=profile_ref(profile):return False
            interval=time_interval(dict(c,sample=s,evidence=e,profile=profile))
            if interval is None:return False
            ms=lambda t:int(datetime.fromisoformat(t).timestamp()*1000)
            if interval[0]<ms(sg['not_before']) or interval[1]>=ms(sg['not_after']):return False
        return True
    if kind=='obs_candidate':
        b=c['frame']['body']['payload']
        # 迟到旧域证据可读；当前IPC只能承载本次会话声明的域。
        return same(c['frame'],b) and not semantics('ObsCompletionBundle',dict(b,durable=True))
    for f in frames:
        b=f['body']
        if 'clock_domain_id' in b and not same(f,b):return False
    # 历史intent允许旧域，但只能unknown；当前not_sent/in_flight必须同域。
    for item in c['ack']['body']['coverage']:
        if item['disposition']!='unknown' and not same(item['intent'],c['trusted_domain']):return False
    return True

def main():
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');args=p.parse_args()
    for name in ('build_contracts.py','build_examples.py'):subprocess.run([sys.executable,str(ROOT/name),'--check'],check=True)
    schema=load(ROOT/'first-loop.schema.json');ipc=load(ROOT/'ipc.schema.json')
    registry=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in (schema,ipc)])
    for s in (schema,ipc):
        Draft202012Validator.check_schema(s)
        for node in walk(s):
            if isinstance(node,dict) and '$ref' in node:registry.resolver(s['$id']).lookup(node['$ref'])
    def validator(model):return Draft202012Validator(dict(schema,**{'$ref':'#/$defs/'+model}),registry=registry,format_checker=FormatChecker())
    iv=Draft202012Validator(ipc,registry=registry,format_checker=FormatChecker())
    cases=load(ROOT/'examples.json');models=set();counts=dict(positive=0,structural_negative=0,semantic_negative=0)
    seen=set()
    for c in cases['examples']:
        assert c['case_id'] not in seen,c['case_id'];seen.add(c['case_id'])
        errors=list(validator(c['model']).iter_errors(c['instance']))
        assert (not errors)==c['schema_valid'],(c['case_id'],[e.message for e in errors][:2])
        if errors:counts['structural_negative']+=1;continue
        errors=semantics(c['model'],c['instance'])
        assert (not errors)==c['semantic_valid'],(c['case_id'],errors)
        counts['semantic_negative' if errors else 'positive']+=1
        if not errors:models.add(c['model'])
    kinds=set();ip=ineg=0
    for c in cases['ipc_examples']:
        errors=list(iv.iter_errors(c['frame']))
        assert (not errors)==c['valid'],(c['case_id'],[e.message for e in errors][:1])
        if errors:ineg+=1
        else:ip+=1;kinds.add(c['frame']['type'])
    assert kinds=={r['$ref'].split('/')[-1] for r in ipc['oneOf']}
    for c in cases['link_cases']:
        if c['kind']=='recovery':
            for key,model in [('request','ResumeRequest'),('preview','RecoveryPreview'),('operation','RecoveryOperation')]:validator(model).validate(c['input'][key])
        elif c['kind']=='age':
            validator('EventAgeProof').validate(c['input']['proof'])
            for part in ('capture','evaluation'):
                for key,model in [('sample','ClockSample'),('evidence','TimeBoundEvidence'),('profile','TimeBoundProfile')]:validator(model).validate(c['input'][part][key])
        elif c['kind'] in ('time','assessment'):
            for key,model in [('sample','ClockSample'),('evidence','TimeBoundEvidence'),('profile','TimeBoundProfile')]:validator(model).validate(c['input'][key])
            if c['kind']=='assessment':validator('ClockAssessment').validate(c['input']['assessment'])
        else:
            for name in ('install','ack','dispatch','request','frame'):
                if name in c['input']:
                    errors=list(iv.iter_errors(c['input'][name]));assert not errors,(c['case_id'],name,'IPC结构无效',errors[0].message[:200] if errors else '')
        assert linked(c['kind'],c['input'])==c['expected'],c['case_id']
    routes=load(ROOT/'routes.json');operations=0
    for service in ('controller','seamer'):
        api=load(ROOT/(service+'.openapi.json'));validate_spec(api)
        for r in routes:
            if r['service'] not in ('common',service):continue
            op=api['paths'][r['path']][r['method']];operations+=1
            assert op['operationId']==r['operation_id']
            for model in (r['request'],r['response']):
                if model:assert model in models,('端点类型缺正例',model)
            for response in op['responses'].values():
                for content in response.get('content',{}).values():assert content['schema']['$ref'].split('/')[-1] in models
            assert '412' in op['responses']
            if r['path'].startswith('/internal/clock') or r['path'].startswith('/internal/time'):
                assert op['security']==[{'serviceMtls':[]}] and op['x-internal-only'] and op['x-permission']=='clock.internal.read'
                assert all(x['headers']['Cache-Control']['schema']=={'const':'no-store'} for x in op['responses'].values())
        ws=api['paths']['/api/v1/events']['get'];assert ws['security']==[{'wsTicketHeader':[]}]
        assert not any(p.get('in')=='query' for p in ws['parameters']);operations+=1
        assert api['components']['schemas']==json.loads(json.dumps(schema['$defs']).replace('#/$defs/','#/components/schemas/'))
        # 公开响应的引用图不得可达内部原始描述符/证据；列入components本身不代表路由暴露。
        sensitive={'ClockDomainDescriptor','TimeBoundEvidence','TimeBoundProfile','ClockSample','OsBootIdentity'}
        def reachable(model,seen):
            if model in seen:return
            seen.add(model)
            for node in walk(api['components']['schemas'][model]):
                if isinstance(node,dict) and '$ref' in node:reachable(node['$ref'].split('/')[-1],seen)
        for path,methods in api['paths'].items():
            if path.startswith('/internal/'):continue
            for op in methods.values():
                if not isinstance(op,dict):continue
                for response in op.get('responses',{}).values():
                    for content in response.get('content',{}).values():
                        model=content.get('schema',{}).get('$ref')
                        if model:
                            reached=set();reachable(model.split('/')[-1],reached);assert not reached&sensitive,(path,reached&sensitive)
    dependencies=[PARENT/'build_contracts.py',PARENT/'build_examples.py',PARENT/'validate_contracts.py']
    for folder in ('f02-f03','f04-f05','f06-f07'):
        dependencies+=sorted(p for p in (PARENT/folder).iterdir() if p.suffix=='.py')
    dependencies+=[PARENT/'f04-f05/simulation-profile.json']
    dependencies+=sorted(p for p in OLD.iterdir() if p.suffix in ('.py','.json') and p.name!='validation-report.json')
    files=sorted([p for p in ROOT.iterdir() if p.is_file() and p.name!='validation-report.json']+dependencies+[PARENT.parent/'rebirth-draft4-review.md'])
    report=dict(public_protocol=VERSION,ipc_protocol=IPC_VERSION,schema_definitions=len(schema['$defs']),ipc_message_types=len(kinds),
        http_operations_including_ws=operations,**counts,ipc_positive=ip,ipc_negative=ineg,linked_cases=len(cases['link_cases']),
        scope='离线结构、摘要、条件时间区间及人工授权上下文配对；无平台、服务、数据库、IPC或设备执行',runtime_acceptance_cases_executed=0,
        versions=dict(python=platform.python_version(),jsonschema=version('jsonschema'),openapi_spec_validator=version('openapi-spec-validator'),rfc8785=version('rfc8785')),
        input_sha256={str(p.relative_to(PARENT.parent)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},all_passed=True)
    if args.report:(ROOT/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
