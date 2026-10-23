"""归并契约的离线检查；不运行服务、数据库、IPC或OBS。"""
import argparse
from copy import deepcopy as cp
import hashlib
from importlib.metadata import version
import json
import platform
import subprocess
import sys
from datetime import datetime
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec
from referencing import Registry, Resource
import rfc8785
from build_contracts import ROOT, PARENT, BASE, VERSION, IPC_VERSION, FEATURES, source

legacy=source(PARENT/'validate_contracts.py')
f4=source(PARENT/'f04-f05/validate_contracts.py')
f6=source(PARENT/'f06-f07/validate_contracts.py')


def load(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def walk(v):yield from legacy.walk(v)
def definition_digest(v):
    v=cp(v)
    for n in walk(v):
        if isinstance(n,dict) and 'step_id' in n:n.pop('independence_proof',None)
    return digest(v)


def semantics(model,v):
    # 旧窗口检查的输入未允许null；新增恢复计划允许无绝对截止。
    safe=cp(v)
    for n in walk(safe):
        if isinstance(n,dict) and n.get('not_before','absent') is None:n.pop('not_before',None);n.pop('not_after',None)
    errors=legacy.contract_errors(model,safe)
    checks={'ExecutionGuard':{'guard_id','binding','guard_digest'},'RevocationRecord':{'issuer_commit_revision','target_service_ids','receipts'},
        'AuthorizationSnapshot':{'snapshot_id','fresh_for_ms','validity'},'ClockAssessment':{'utc_lower_ms','utc_upper_ms'},
        'ScheduleGuard':{'window_enter_tick_ns','queue_deadline_tick_ns'},'EventAgeProof':{'lower_age_ms','upper_age_ms','basis'},
        'CapacityProfile':{'identity','capacity','retention'}}
    for n in walk(v):
        if not isinstance(n,dict):continue
        for name,keys in checks.items():
            if keys<=n.keys():
                err=f4.semantic_error(name,n)
                if err:errors.append(err)
        if {'event_id','payload','age_proof'}<=n.keys():
            if any(n[k]!=n['age_proof'][k] for k in ('event_id','provider_boot_id','source_sequence')):errors.append('event_age_binding')
        if {'parameters_schema','footprint','read_set'}<=n.keys():
            f=n['footprint']
            if f['action_id']!=n['action_id']:errors.append('footprint_action')
            if f['complete']:
                if n['read_set']!=f['reads'] or n['write_set']!=f['writes']:errors.append('footprint_projection')
            elif n['read_set']!='unknown' or n['write_set']!='unknown':errors.append('incomplete_footprint')
        if {'policy_id','frames','target_scene_uuid'}<=n.keys():
            if any(x['clock_domain_id']!=n['clock_domain_id'] for x in n['frames']):errors.append('obs_clock_domain')
            if f6.obs_decision(n)!='verified':errors.append('obs_bundle')
        if {'proof_id','failed_footprint','bindings_digest'}<=n.keys():
            if f6.proof_decision(n)!=n['verdict']:errors.append('proof_verdict')
            projection={k:n[k] for k in ('definition_id','definition_version','definition_digest','action_bindings','dependency_graph_digest','dsl_version','generator_version','alias_revision')}
            ordered=sorted(n['action_bindings'],key=lambda b:rfc8785.dumps(b['action_ref']))
            if ordered!=n['action_bindings'] or digest(projection)!=n['bindings_digest']:errors.append('proof_binding_digest')
            if len({rfc8785.dumps(b['action_ref']) for b in n['action_bindings']})!=len(n['action_bindings']):errors.append('duplicate_action_binding')
        if {'preview_id','preview_digest','issued_tick_ns'}<=n.keys():
            err=f6.semantic_error('RecoverySnapshot',n)
            if err:errors.append(err)
        if {'snapshot','plan','observations'}<=n.keys():
            if digest(n['plan'])!=n['snapshot']['plan_digest']:errors.append('recovery_plan_digest')
            ids=[x['step_id'] for x in n['plan']['items'] if x['decision']=='execute_new']
            if ids!=n['snapshot']['proposed_step_ids']:errors.append('recovery_plan_steps')
            if len({x['step_id'] for x in n['plan']['items']})!=len(n['plan']['items']):errors.append('recovery_duplicate_step')
        if {'decision','parameters_digest','source_execution_id'}<=n.keys():
            if (n['not_before'] is None)!=(n['not_after'] is None):errors.append('recovery_window_pair')
            if n['decision'] in ('retain_success','reconcile_commit') and not n['evidence_ids']:errors.append('recovery_missing_evidence')
        if {'committed_run_revision','previous_run_revision','targets'}<=n.keys():
            if f6.semantic_error('RecoveryOperation',n):errors.append('recovery_revision')
            if len({t['controller_id'] for t in n['targets']})!=len(n['targets']):errors.append('duplicate_target')
            if set(n['target_controller_ids'])!={t['controller_id'] for t in n['targets']}:errors.append('target_coverage')
            for t in n['targets']:
                if t['operation_id']!=n['operation_id'] or t['target_arm_generation']!=n['recovery_generation']:errors.append('recovery_target_binding')
                if t['execution_id']!=n['new_execution_id']:errors.append('recovery_execution_binding')
                if int(t['target_arm_generation'])<=int(t['baseline_arm_generation']):errors.append('recovery_generation')
        if {'command_id','attempts','admission'}<=n.keys():
            if n['admission']['command_id']!=n['command_id']:errors.append('admission_binding')
            attempts={a['attempt_id']:a for a in n['attempts']}
            evidences=n['completion_evidence']+n['resource_release_evidence'];ids=[x['evidence_id'] for x in evidences]
            if len(set(ids))!=len(ids):errors.append('duplicate_evidence')
            for ev in evidences:
                a=attempts.get(ev['attempt_id'])
                if ev['command_id']!=n['command_id'] or not a or any(ev[k]!=a[k] for k in ('worker_boot_id','device_session_id')):errors.append('evidence_attempt_binding')
                if ev.get('obs_bundle'):
                    b=ev['obs_bundle']
                    if any(b[k]!=ev[k] for k in ('command_id','attempt_id','worker_boot_id','device_session_id')):errors.append('bundle_evidence_binding')
            completion_ids=set(n['completion']['evidence_ids'])
            if not completion_ids<=set(e['evidence_id'] for e in n['completion_evidence']):errors.append('missing_completion_evidence')
            if n['target']['action_id']=='obs.program_scene.set' and n['outcome']=='succeeded':
                if not any(e['evidence_id'] in completion_ids and e.get('obs_bundle') and e['obs_bundle']['policy_id']==n['completion']['evidence_policy_id'] for e in n['completion_evidence']):errors.append('obs_completion_reference')
            if n['resource_status']=='clear' and n['effect_status']!='not_sent':
                if not set(n['resource_evidence_ids'])<=set(x['evidence_id'] for x in n['resource_release_evidence']):errors.append('missing_release_evidence')
            if n.get('resolution') and not set(n['resolution']['evidence_ids'])<=set(ids):errors.append('missing_resolution_evidence')
        if {'published','definition','independence_proofs'}<=n.keys():
            proofs={(p['proof_id'],p['proof_revision']):p for p in n['independence_proofs']}
            if len(proofs)!=len(n['independence_proofs']):errors.append('duplicate_proof')
            for node in walk(n['definition']):
                if isinstance(node,dict) and 'independence_proof' in node and n['published']:
                    r=node['independence_proof'];p=proofs.get((r['proof_id'],r['proof_revision']))
                    if not p or p['definition_id']!=n['definition_id'] or p['definition_version']!=n['definition_version']:errors.append('published_proof_binding')
                    elif p['failed_step_id']!=node['step_id'] or p['definition_digest']!=definition_digest(n['definition']):errors.append('published_proof_definition')
    return errors


def linked(kind,c):
    if kind=='recovery':
        r,p,o=c['request'],c['preview'],c['operation'];s=p['snapshot']
        if semantics('RecoveryPreview',p) or semantics('RecoveryOperation',o):return False
        if r['expected_revision']!=s['run_revision'] or r['preview_id']!=s['preview_id'] or r['preview_digest']!=s['preview_digest']:return False
        if o['run_id']!=s['run_id'] or o['preview_id']!=s['preview_id'] or o['previous_run_revision']!=s['run_revision']:return False
        if o['plan_digest']!=s['plan_digest'] or o['baseline_snapshot_digest']!=s['preview_digest']:return False
        return set(o['target_controller_ids'])==set(p['plan']['target_controller_ids'])
    if kind=='obs_candidate':
        f=c['frame'];b=f['body'];bundle=b['payload']
        if any(bundle[k]!=b[k] for k in ('command_id','attempt_id','device_session_id')) or bundle['worker_boot_id']!=f['worker_boot_id']:return False
        public=cp(bundle);public['durable']=True
        return not semantics('ObsCompletionBundle',public)
    if kind=='guard':
        i,a,d=c['install'],c['ack'],c['dispatch'];g=i['body']['guard'];p=d['body']['permit']
        if a['reply_to']!=i['message_id']:return False
        for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id'):
            if not i[k]==a[k]==d[k]==g[k]:return False
        if f4.semantic_error('ExecutionGuard',g):return False
        if any(a['body'][k]!=g[k] or p[k]!=g[k] for k in ('guard_id','guard_digest','permit_id','command_id')):return False
        if any(d['body'][k]!=g[k] for k in ('guard_id','guard_digest')):return False
        if a['body']['installed_authorization_revision']!=g['authorization_revision'] or p['authorization_revision']!=g['authorization_revision']:return False
        expected=digest({k:v for k,v in d['body']['request'].items() if k not in ('context_id','idempotency_key','correlation_id')})
        if not i['body']['content_digest']==a['body']['content_digest']==p['content_digest']==expected:return False
        if int(c['now_tick_ns'])>=int(g['authorization_deadline_tick_ns']):return False
        if g['binding']['origin']!=p['origin']:return False
        request=d['body']['request'];binding=g['binding']
        if request['device_id']!=d['device_id'] or request['origin']!=p['origin'] or request['dispatch']!=p['deadline_policy']:return False
        if request['expected_control']!={'epoch':p['control_epoch'],'version':p['control_version']}:return False
        if any(binding[k]!=p[k] for k in ('grant_revision','arm_generation')):return False
        if p['origin']=='automation' and any(binding[k]!=request['run_binding'][k] for k in ('grant_id','grant_revision','arm_generation')):return False
        if d['body']['send_window']['clock_domain_id']!=g['clock_domain_id']:return False
        now=int(c['now_tick_ns']);window=d['body']['send_window']
        if not int(window['earliest_tick_ns'])<=now<int(window['latest_tick_ns']):return False
        if g['time_required'] != (d['body']['request']['dispatch']['mode']=='scheduled'):return False
        if g['time_required']:
            sample=i['body']['clock_sample'];schedule=i['body']['schedule_guard']
            if not sample or not schedule:return False
            if sample['clock_domain_id']!=g['clock_domain_id'] or sample['clock_generation']!=g['clock_generation'] or schedule['clock_generation']!=g['clock_generation']:return False
            if not sample['policy_revision']==g['time_policy_revision']==schedule['time_policy_revision']:return False
            dispatch=d['body']['request']['dispatch']
            if any(schedule[k]!=dispatch[k] for k in ('occurrence_id','not_before','not_after')):return False
            if dispatch['clock_policy_revision']!=g['time_policy_revision']:return False
            if now>=int(schedule['queue_deadline_tick_ns']):return False
            ms=lambda t:int(datetime.fromisoformat(t).timestamp()*1000)
            timecase=dict(sample=sample,domain=g['clock_domain_id'],generation=g['clock_generation'],now_tick_ns=c['now_tick_ns'],
                latched=schedule['health_latched'],source_required=True,max_uncertainty_ms=50,
                not_before_ms=ms(schedule['not_before']),not_after_ms=ms(schedule['not_after']))
            if f4.time_decision(timecase)!='send':return False
        return True
    f,a=c['request'],c['ack'];x,y=f['body'],a['body']
    if a['reply_to']!=f['message_id']:return False
    if any(a[k]!=f[k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id')):return False
    if any(y.get(k)!=v for k,v in x.items() if k!='open_intents'):return False
    if 'target_authorization_revision' in x and y['applied_authorization_revision']!=x['target_authorization_revision']:return False
    ledger=sorted(x['open_intents'],key=lambda v:v['permit_id'])
    if digest(ledger)!=x['ledger_digest']:return False
    keys=[i['permit_id'] for i in ledger];coverage=y['coverage'];covered=[v['intent']['permit_id'] for v in coverage]
    if len(set(keys))!=len(keys) or len(set(covered))!=len(covered) or set(keys)!=set(covered):return False
    if {i['permit_id']:i for i in ledger}!={v['intent']['permit_id']:v['intent'] for v in coverage}:return False
    for field,status,key in [('invalidated_permit_ids','not_sent','permit_id'),('in_flight_command_ids','in_flight','command_id'),('unresolved_command_ids','unknown','command_id')]:
        if set(y[field])!={v['intent'][key] for v in coverage if v['disposition']==status} or len(set(y[field]))!=len(y[field]):return False
    if any(v['intent']['worker_boot_id']!=f['worker_boot_id'] and v['disposition']!='unknown' for v in coverage):return False
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
        else:
            for name in ('install','ack','dispatch','request','frame'):
                if name in c['input']:
                    errors=list(iv.iter_errors(c['input'][name]));assert not errors,(c['case_id'],name,'IPC结构无效')
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
                for content in response.get('content',{}).values():
                    model=content['schema']['$ref'].split('/')[-1]
                    assert model in models,('响应缺正例',model)
            assert '412' in op['responses']
            if r['operation_id'] in ('issueToken','issueWsTicket','introspect'):
                assert all(x['headers']['Cache-Control']['schema']=={'const':'no-store'} for x in op['responses'].values())
            if r['operation_id']=='issueWsTicket':assert op['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/WsTicketBindingResponse')
        ws=api['paths']['/api/v1/events']['get'];assert ws['security']==[{'wsTicketHeader':[]}]
        assert not any(p.get('in')=='query' for p in ws['parameters'])
        operations+=1
        assert api['components']['schemas']==json.loads(json.dumps(schema['$defs']).replace('#/$defs/','#/components/schemas/'))
    # 协议基线和旧候选仍可复现，本报告只记录归并输入，不冒充真实测试。
    dependencies=[PARENT/'build_contracts.py',PARENT/'build_examples.py',PARENT/'validate_contracts.py']
    for folder in ('f02-f03','f04-f05','f06-f07'):
        dependencies+=sorted(p for p in (PARENT/folder).iterdir() if p.suffix=='.py')
    dependencies+=[PARENT/'f04-f05/simulation-profile.json']
    files=sorted([p for p in ROOT.iterdir() if p.is_file() and p.name!='validation-report.json']+dependencies+[PARENT.parent/'rebirth-draft3-review.md'])
    report=dict(public_protocol=VERSION,ipc_protocol=IPC_VERSION,schema_definitions=len(schema['$defs']),ipc_message_types=len(kinds),
        http_operations_including_ws=operations,**counts,ipc_positive=ip,ipc_negative=ineg,linked_cases=len(cases['link_cases']),
        scope='离线结构、引用、封装、跨对象约束与人工IPC配对；无服务、数据库、真实并发或设备执行',runtime_acceptance_cases_executed=0,
        versions=dict(python=platform.python_version(),jsonschema=version('jsonschema'),openapi_spec_validator=version('openapi-spec-validator'),rfc8785=version('rfc8785')),
        input_sha256={str(p.relative_to(PARENT.parent)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},all_passed=True)
    if args.report:(ROOT/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
