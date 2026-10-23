"""离线结构和有限边界计算，不实现认证、NTP 客户端、限流器或设备执行。"""
import argparse
from datetime import datetime
from fractions import Fraction
import hashlib
from importlib.metadata import version
import json
from math import ceil, floor
from pathlib import Path
import platform
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
import rfc8785

ROOT=Path(__file__).resolve().parent


def load(p):return json.loads(p.read_text(encoding='utf-8'))
def timestamp(v):return datetime.fromisoformat(v.replace('Z','+00:00'))


def semantic_error(model,v):
    if model=='AuthorizationSnapshot' and timestamp(v['validity']['not_before'])>=timestamp(v['validity']['expires_at']):return 'validity_order'
    if model=='ScheduleGuard' and timestamp(v['not_before'])>=timestamp(v['not_after']):return 'window_order'
    if model=='ScheduleGuard' and int(v['window_enter_tick_ns'])>=int(v['queue_deadline_tick_ns']):return 'monotonic_window_order'
    if model=='ClockAssessment' and v['utc_lower_ms'] is not None and v['utc_upper_ms'] is not None and v['utc_lower_ms']>v['utc_upper_ms']:return 'interval_order'
    if model=='EventAgeProof' and v['lower_age_ms'] is not None and v['upper_age_ms'] is not None and v['lower_age_ms']>v['upper_age_ms']:return 'age_order'
    if model=='ExecutionGuard':
        body={k:x for k,x in v.items() if k!='guard_digest'}
        if v['guard_digest']!='sha256:'+hashlib.sha256(rfc8785.dumps(body)).hexdigest():return 'guard_digest'
    if model=='CapacityProfile':
        i=v['identity']
        if not (i['snapshot_refresh_ms']<i['snapshot_fresh_ms'] and i['gate_renew_ms']<i['gate_lease_ms']<=i['snapshot_fresh_ms']):return 'refresh_budget'
    if model=='RevocationRecord':
        ids=[r['target_service_id'] for r in v['receipts']]
        if len(set(ids))!=len(ids):return 'duplicate_receipt'
        if not set(ids)<=set(v['target_service_ids']):return 'target_coverage'
        if v['state']=='applied' and set(ids)!=set(v['target_service_ids']):return 'target_coverage'
        for r in v['receipts']:
            if r['operation_id']!=v['operation_id']:return 'operation_binding'
            if r['selector']!=v['selector']:return 'selector_binding'
            if int(r['observed_revision'])<int(v['issuer_commit_revision']):return 'stale_receipt'
            if v['state']=='applied' and (r['state']!='applied' or not r['durable']):return 'not_applied'
    return None


def denied(binding, selector):
    if any(binding[k]!=selector[k] for k in ('issuer_id','issuer_epoch')):return False
    kind=selector['kind'];target=selector['target_id']
    if kind=='trust':return target==binding['issuer_id']
    fields={'session':('session_id','session_revision'),'principal':('principal_id','subject_revision'),
            'grant':('grant_id','grant_revision'),'extension':('extension_instance_id','extension_approval_revision')}
    if kind=='credential':return target==binding['credential_id']
    identity,revision=fields[kind]
    return binding[identity]==target and binding[revision] is not None and int(binding[revision])<int(selector['revision_floor'])


def fresh(c):
    return c['started_ms']<=c['received_ms']<=c['now_ms']<c['started_ms']+min(c['fresh_ms'],c['policy_ms'])


def time_decision(c):
    if c['latched']:return 'blocked'
    s=c['sample'];now=int(c['now_tick_ns']);sample=int(s['sample_tick_ns'])
    if (c['domain']!=s['clock_domain_id'] or c['generation']!=s['clock_generation'] or now<sample or
        s['quality']!='synchronized' or s['uncertainty_ms'] is None or
        (c['source_required'] and s['source_auth']=='unverified')):return 'untrusted'
    elapsed=Fraction(now-sample,1000000)
    uncertainty=s['uncertainty_ms']+ceil(s['drift_bound_ppm']*elapsed/1000000)
    if elapsed>=s['max_sample_age_ms'] or uncertainty>c['max_uncertainty_ms']:return 'untrusted'
    lower=floor(s['estimated_utc_ms']+elapsed-uncertainty)
    upper=ceil(s['estimated_utc_ms']+elapsed+uncertainty)
    if upper>=c['not_after_ms']:return 'expired'
    if lower<c['not_before_ms']:return 'wait'
    return 'send'


def age_decision(c):
    ls,us=c['source'];lr,ur=c['receiver']
    if ls>us or lr>ur or ls>ur:return 'invalid'
    return 'fresh' if max(0,ur-ls)<=c['max_age_ms'] else 'stale'


def capacity_decision(c):
    # 该有限决策表假定调用者鉴权已成功；不代表 P0 可绕过鉴权或事务。
    if c['kind']=='protection':
        return 'apply_protection' if c['protection_used']<c['protection_limit'] else 'local_protect_no_ack'
    if not c['storage_healthy']:return 'protect'
    if c['already_accepted']:return 'query_existing'
    if c['evidence_free']<=0:return 'protect'
    if c['ordinary_used']>=c['ordinary_limit']:return 'reject'
    return 'admit'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');args=parser.parse_args()
    for source in ('build_contracts.py','build_cases.py'):
        subprocess.run([sys.executable,str(ROOT/source),'--check'],check=True)
    schema=load(ROOT/'contracts.schema.json');public=load(ROOT.parent/'first-loop.schema.json')
    Draft202012Validator.check_schema(schema)
    registry=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in (schema,public)])
    def check_refs(node):
        if isinstance(node,dict):
            if '$ref' in node:registry.resolver(schema['$id']).lookup(node['$ref'])
            for child in node.values():check_refs(child)
        elif isinstance(node,list):
            for child in node:check_refs(child)
    check_refs(schema)
    def validator(model):return Draft202012Validator(dict(schema,**{'$ref':'#/$defs/'+model}),registry=registry,format_checker=FormatChecker())
    profile=load(ROOT/'simulation-profile.json');validator('CapacityProfile').validate(profile)
    assert profile['purpose']=='simulation' and profile['validated_environment'] is None
    assert semantic_error('CapacityProfile',profile) is None
    # 与上一轮已同意实验编码限额保持一致，而非静默提高它们。
    caps=profile['capacity']
    assert (caps['frame_bytes'],caps['ipc_normal_slots'],caps['ipc_protection_slots'],caps['barrier_intents'])==(262144,64,4,256)
    cases=load(ROOT/'cases.json');seen=set();positive=negative=semantic_negative=0;models=set()
    for group in cases.values():
        for c in group:
            assert c['case_id'] not in seen,c['case_id'];seen.add(c['case_id'])
    for c in cases['examples']:
        errors=list(validator(c['model']).iter_errors(c['instance']))
        assert (not errors)==c['schema_valid'],(c['case_id'],[e.message for e in errors][:2])
        if errors:negative+=1;continue
        result=semantic_error(c['model'],c['instance'])
        assert result==c['semantic_error'],(c['case_id'],result)
        if result:semantic_negative+=1
        else:positive+=1;models.add(c['model'])
    assert models==set(schema['$defs']),'缺少模型正例'
    for c in cases['scope_cases']:
        validator('AuthorizationBinding').validate(c['binding']);validator('RevocationSelector').validate(c['selector'])
        assert denied(c['binding'],c['selector'])==c['denied'],c['case_id']
    for c in cases['freshness_cases']:assert fresh(c)==c['expected'],c['case_id']
    for c in cases['time_cases']:
        validator('ClockSample').validate(c['sample'])
        assert time_decision(c)==c['expected'],(c['case_id'],time_decision(c))
    for c in cases['event_age_cases']:assert age_decision(c)==c['expected'],c['case_id']
    for c in cases['capacity_cases']:assert capacity_decision(c['input'])==c['expected'],c['case_id']
    files=sorted([p for p in ROOT.iterdir() if p.is_file() and p.name!='validation-report.json']+
                 [ROOT.parent/'first-loop.schema.json',ROOT.parent.parent/'rebirth-f04-f05-design.md'])
    report=dict(scope='离线候选模型、有限授权范围／时间／容量向量；不包含认证、IPC、NTP、并发压力或设备运行验收',
        contract='f04-f05/0.1.0-draft.1',schema_definitions=len(schema['$defs']),positive_examples=positive,
        structural_negative_examples=negative,semantic_negative_examples=semantic_negative,
        scope_cases=len(cases['scope_cases']),freshness_cases=len(cases['freshness_cases']),time_cases=len(cases['time_cases']),
        event_age_cases=len(cases['event_age_cases']),capacity_cases=len(cases['capacity_cases']),runtime_acceptance_cases_executed=0,
        versions={'python':platform.python_version(),'jsonschema':version('jsonschema'),'rfc8785':version('rfc8785')},
        input_sha256={str(p.relative_to(ROOT.parent.parent)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},all_passed=True)
    if args.report:(ROOT/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
