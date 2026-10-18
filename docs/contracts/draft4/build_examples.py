"""保留旧正例场景并增加人工平台反例；不是平台模拟器。"""
import argparse
import hashlib
import json
from copy import deepcopy as cp
from pathlib import Path
import rfc8785
from build_contracts import ROOT,OLD,VERSION,IPC_VERSION,FEATURES,build as contracts

def digest(v):return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def seal(v,key):v[key]=digest({k:x for k,x in v.items() if k!=key});return v
def descriptor(authority='controller-test',generation='runtime-synthetic-1'):
    v=dict(descriptor_version='clock-domain/1',domain_kind='supervised_runtime',authority_service_id=authority,runtime_generation=generation,
        supervisor_instance_id='supervisor-synthetic',clock_backend_id='windows_interrupt_precise',clock_backend_revision='adapter-synthetic-1',
        tick_unit='ns',suspend_accounting='included',namespace_identity='windows-kernel-runtime',os_boot_identity={'status':'unavailable'},
        platform_profile_id='synthetic-platform-not-approved',platform_profile_revision='1')
    h=digest(v);return dict(v,descriptor_digest=h,clock_domain_id='clock_'+h.removeprefix('sha256:'))
def domain(v):return {k:v[k] for k in ('clock_domain_id','descriptor_digest')}
DESC=descriptor();DOM=domain(DESC);OTHER=domain(descriptor(generation='other-runtime'));SEAMER=domain(descriptor('seamer-test'))
def profile():
    return seal(dict(profile_id='synthetic-time-profile',revision='1',backend='chrony',parser_profile_id='synthetic-parser',model_id='system-bound/1',
        validated_environment_ref='synthetic-environment',assumption_profile_ref='synthetic-source-assumptions',validation_report_ref='synthetic-not-runtime-approval',
        configured_source_set_digest=digest(['synthetic-source']),allowed_source_auth=['trusted_network','nts'],max_capture_span_ms=100,
        max_source_age_ms=10000,max_sample_age_ms=10000,max_uncertainty_ms=50,drift_bound_ppm=100,source_extra_bound_ns='0',read_quantization_bound_ns='0'),'profile_digest')
def pref(p):return {k:p[k] for k in ('profile_id','revision','profile_digest')}
def eref(e):return {k:e[k] for k in ('evidence_id','evidence_digest')}
def active(e):return {k:e[k] for k in ('provider_id','provider_boot_id','clock_generation','time_policy_revision','configured_source_set_digest')}
def evidence(sample,p):
    v=dict(evidence_id='time-evidence-'+sample['sample_id'],provider_id=sample['provider_id'],provider_boot_id=sample['provider_boot_id'],
        **{k:sample[k] for k in DOM},clock_generation=sample['clock_generation'],time_policy_revision=sample['policy_revision'],
        backend=p['backend'],parser_profile_id=p['parser_profile_id'],model_id=p['model_id'],profile_ref=pref(p),source_ref=sample['source_ref'],
        source_auth=sample['source_auth'],configured_source_set_digest=p['configured_source_set_digest'],source_update_id='source-update-1',
        source_age_at_capture_ns='0',source_age_basis='validated_upper_bound',capture_start_tick_ns=sample['sample_tick_ns'],capture_end_tick_ns=sample['sample_tick_ns'],
        wall_read_utc_ms=sample['estimated_utc_ms'],raw_response_digest=digest('synthetic-only'),source_state_digest=digest('synthetic-state'),
        leap_status='normal',stratum=2,system_offset_ns='0',root_delay_ns='0',root_dispersion_ns=str((sample['uncertainty_ms'] or 0)*1000000),
        source_extra_bound_ns=p['source_extra_bound_ns'],read_quantization_bound_ns=p['read_quantization_bound_ns'],drift_bound_ppm=sample['drift_bound_ppm'],
        bound_state='conditional' if sample['quality']=='synchronized' else 'unproven',uncertainty_at_capture_ms=sample['uncertainty_ms'] if sample['quality']=='synchronized' else None,reason_code='synthetic')
    return seal(v,'evidence_digest')

def upgrade(value):
    hashes={};evidence_map={};p=profile()
    def go(v):
        if isinstance(v,list):return [go(x) for x in v]
        if not isinstance(v,dict):return v
        old=cp(v);v={k:go(x) for k,x in v.items()}
        if 'protocol_version' in v:v['protocol_version']=VERSION
        if 'ipc_version' in v:v['ipc_version']=IPC_VERSION;v.update(DOM)
        if 'supported_ipc_versions' in v:v['supported_ipc_versions']=[IPC_VERSION];v['supported_features']=FEATURES;v['clock_domain_descriptor']=DESC
        if 'selected_ipc_version' in v:v['selected_ipc_version']=IPC_VERSION;v['selected_features']=FEATURES;v['clock_domain_descriptor']=DESC
        if 'clock_domain_id' in old:v.update(OTHER if old['clock_domain_id']=='other-clock' else DOM)
        if {'window_enter_tick_ns','queue_deadline_tick_ns'}<=v.keys():v.update(DOM)
        if {'preview_id','issued_tick_ns'}<=v.keys():v.update(SEAMER)
        if {'permit_id','dispatch_intent_id','command_id'}<=v.keys():v.update(DOM)
        if {'attempt_id','send_started_at'}<=v.keys() or {'evidence_id','attempt_id','durable'}<=v.keys():v.update(DOM)
        if {'evidence_id','predicate_result'}<=v.keys():v.update(DOM)
        if {'barrier_id','installed_version'}<=v.keys() or {'operation_id','effective_record_durable'}<=v.keys():v.update(DOM)
        if {'baseline_control_digest','controller_id'}<=v.keys():v.update(baseline_domain=DOM,target_domain=DOM if v['state']=='applied' else None)
        if {'event_id','basis','capture_sample_id'}<=v.keys():
            v.update(utc_basis=None,causal_basis=None)
            if v['basis']=='trusted_utc':v['utc_basis']=dict(capture_sample_ref=dict(sample_id=v['capture_sample_id'],sample_digest=digest('capture-sample')),capture_domain=DOM,capture_evidence_ref=dict(evidence_id='capture-evidence',evidence_digest=digest('capture')),
                evaluation_sample_ref=dict(sample_id='evaluation-sample',sample_digest=digest('evaluation-sample')),evaluation_domain=SEAMER,evaluation_evidence_ref=dict(evidence_id='evaluation-evidence',evidence_digest=digest('evaluation')))
            if v['basis']=='causal_capture':v['causal_basis']=dict(verifier_domain=SEAMER,challenge_sent_tick_ns='1000000',received_tick_ns=str(1000000+v['upper_age_ms']*1000000))
        if {'sample_id','sample_tick_ns','quality'}<=v.keys():
            v['mode']='system_disciplined'
            v.pop('host_boot_id',None);ev=evidence(v,p);evidence_map[v['sample_id']]=ev
            v.update(time_evidence_ref=eref(ev),time_profile_ref=pref(p))
        if {'sample_id','eligible_for_absolute'}<=v.keys():v.update(time_evidence_ref=dict(evidence_id='time-evidence-'+v['sample_id'],evidence_digest=digest('assessment-reference')),time_profile_ref=pref(p))
        if {'guard_id','time_required'}<=v.keys():
            v.update(clock_sample_ref=None,time_evidence_ref=None,time_profile_ref=None)
            if v['time_required']:v.update(clock_sample_ref=dict(sample_id='sample-placeholder',sample_digest=digest('sample')),time_evidence_ref=dict(evidence_id='evidence-placeholder',evidence_digest=digest('evidence')),time_profile_ref=pref(p))
        if {'guard','clock_sample','schedule_guard'}<=v.keys():
            v.update(time_evidence=None,time_profile=None)
            if v['guard']['time_required']:
                sample=v['clock_sample'];ev=evidence_map[sample['sample_id']];v.update(time_evidence=ev,time_profile=p)
                v['guard'].update(clock_sample_ref=dict(sample_id=sample['sample_id'],sample_digest=digest(sample)),time_evidence_ref=eref(ev),time_profile_ref=pref(p))
                original=old['guard']['guard_digest'];seal(v['guard'],'guard_digest');hashes[original]=v['guard']['guard_digest']
        for key in ('guard_digest','preview_digest'):
            if key in v and ((key=='guard_digest' and 'time_required' in v) or (key=='preview_digest' and 'issued_tick_ns' in v)):
                previous=old[key];seal(v,key);hashes[previous]=v[key]
        if 'open_intents' in v:
            previous=old['ledger_digest'];v['ledger_digest']=digest(sorted(v['open_intents'],key=lambda x:x['permit_id']));hashes[previous]=v['ledger_digest']
        return v
    result=go(value)
    def replace(v):
        if isinstance(v,list):return [replace(x) for x in v]
        if not isinstance(v,dict):return hashes.get(v,v) if isinstance(v,str) else v
        return {k:replace(x) for k,x in v.items()}
    # guard安装后的真实摘要必须优先覆盖中间计算值。
    for _ in range(3):result=replace(result)
    return result

def build():
    old=json.loads((OLD/'examples.json').read_text(encoding='utf-8'))
    cases=[upgrade(c) for c in old['examples'] if c['schema_valid'] and c['semantic_valid']]
    ipcs=[upgrade(c) for c in old['ipc_examples'] if c['valid']]
    links=[upgrade(c) for c in old['link_cases'] if c['expected']]
    e={c['model']:c['instance'] for c in cases};p=profile();sample=e['ClockSample'];ev=evidence(sample,p)
    e.update(ClockDomainRef=DOM,ClockDomainDescriptor=DESC,OsBootIdentity={'status':'unavailable'},EvidenceRef=eref(ev),ClockSampleRef=dict(sample_id=sample['sample_id'],sample_digest=digest(sample)),TimeProfileRef=pref(p),TimeBoundProfile=p,TimeBoundEvidence=ev)
    proof=next(x['instance'] for x in cases if x['model']=='EventAgeProof')
    e['UtcAgeBasis']=dict(capture_sample_ref=e['ClockSampleRef'],capture_domain=DOM,capture_evidence_ref=eref(ev),evaluation_sample_ref=e['ClockSampleRef'],evaluation_domain=DOM,evaluation_evidence_ref=eref(ev))
    e['CausalAgeBasis']=dict(verifier_domain=DOM,challenge_sent_tick_ns='1000000',received_tick_ns='2000000')
    newmodels=('ClockDomainRef','ClockDomainDescriptor','OsBootIdentity','EvidenceRef','ClockSampleRef','TimeProfileRef','TimeBoundProfile','TimeBoundEvidence','UtcAgeBasis','CausalAgeBasis')
    for m in newmodels:cases.append(dict(case_id='new-'+m,model=m,instance=e[m],schema_valid=True,semantic_valid=True))
    for m in ('ClockDomainDescriptor','TimeBoundProfile','TimeBoundEvidence','ClockSample'):
        cases.append(dict(case_id='response-'+m,model=m+'Response',instance=dict(request_id='req-synthetic',service_id='service-test',service_boot_id='boot-test',protocol_version=VERSION,data=e[m]),schema_valid=True,semantic_valid=True))
    def bad(cid,model,edit,struct=True):
        v=cp(e[model]);edit(v);cases.append(dict(case_id=cid,model=model,instance=v,schema_valid=struct,semantic_valid=False))
    bad('boot-unavailable-with-value','OsBootIdentity',lambda v:v.update(value='fake'),False)
    bad('descriptor-unknown-version','ClockDomainDescriptor',lambda v:v.update(descriptor_version='other'),False)
    bad('descriptor-mutated-runtime','ClockDomainDescriptor',lambda v:v.update(runtime_generation='reused-wrong'))
    bad('descriptor-domain-not-derived','ClockDomainDescriptor',lambda v:v.update(clock_domain_id=OTHER['clock_domain_id']))
    bad('old-host-boot-on-sample','ClockSample',lambda v:v.update(host_boot_id='fake-runtime'),False)
    bad('sample-sync-no-proof','ClockSample',lambda v:v.update(time_evidence_ref=None),False)
    bad('sample-missing-domain-digest','ClockSample',lambda v:v.pop('descriptor_digest'),False)
    bad('evidence-negative-delay','TimeBoundEvidence',lambda v:v.update(root_delay_ns='-1'),False)
    bad('evidence-utc-as-monotonic','TimeBoundEvidence',lambda v:v.update(capture_start_tick_ns='133000000000000000'))
    bad('evidence-modified-budget','TimeBoundEvidence',lambda v:v.update(uncertainty_at_capture_ms=0))
    bad('evidence-zero-underbound-rehashed','TimeBoundEvidence',lambda v:seal(v.update(root_dispersion_ns='9000000',uncertainty_at_capture_ms=0) or v,'evidence_digest'))
    bad('evidence-unproven-numeric-bound','TimeBoundEvidence',lambda v:v.update(bound_state='unproven'),False)
    bad('evidence-unproved-source-age','TimeBoundEvidence',lambda v:v.update(source_age_basis='unproven'),False)
    bad('evidence-leap-insert','TimeBoundEvidence',lambda v:v.update(leap_status='insert'),False)
    bad('profile-tampered','TimeBoundProfile',lambda v:v.update(max_source_age_ms=999999))
    bad('guard-immediate-with-proof','ExecutionGuard',lambda v:v.update(time_evidence_ref=eref(ev)),False)
    bad('recovery-no-domain','RecoverySnapshot',lambda v:v.pop('descriptor_digest'),False)
    def ipc_bad(cid,kind,edit):
        v=cp(next(c['frame'] for c in ipcs if c['frame']['type']==kind));edit(v);ipcs.append(dict(case_id=cid,frame=v,valid=False))
    ipc_bad('ipc-old-version','DISPATCH',lambda v:v.update(ipc_version='ipc/0.2.0-draft.1'))
    ipc_bad('ipc-no-domain','OPEN_GATE_ACK',lambda v:v.pop('descriptor_digest'))
    ipc_bad('ipc-no-new-feature','HELLO_ACK',lambda v:v['body'].update(selected_features=FEATURES[:-1]))
    ipc_bad('ipc-missing-bootstrap-descriptor','HELLO',lambda v:v['body'].pop('clock_domain_descriptor'))
    # 所有配对带外部可信上下文；它来自测试夹具，不是接收消息自我批准。
    for c in links:
        v=c['input'];v['trusted_domain']=SEAMER if c['kind']=='recovery' else DOM
        v['bootstrap_authenticated']=True
        v['approved_profile_digests']=[p['profile_digest']]
        if c['kind']=='guard' and v['install']['body']['guard']['time_required']:v['active_time_state']=active(v['install']['body']['time_evidence'])
        if c['kind']=='recovery':v['now_tick_ns']=v['preview']['snapshot']['issued_tick_ns']
    def linkbad(cid,base,edit):
        c=cp(next(x for x in links if x['case_id']==base));c.update(case_id=cid,expected=False);edit(c['input']);links.append(c)
    for key in ('install','ack','dispatch'):
        linkbad('wrong-domain-'+key,'guard-linked',lambda v,k=key:v[k].update(OTHER))
    linkbad('untrusted-bootstrap','guard-linked',lambda v:v.update(bootstrap_authenticated=False))
    linkbad('old-runtime-new-supervisor','guard-linked',lambda v:v.update(trusted_domain=OTHER))
    linkbad('scheduled-sample-other-domain','scheduled-guard-current',lambda v:v['install']['body']['clock_sample'].update(OTHER))
    linkbad('scheduled-window-other-domain','scheduled-guard-current',lambda v:v['dispatch']['body']['send_window'].update(OTHER))
    linkbad('scheduled-schedule-other-domain','scheduled-guard-current',lambda v:v['install']['body']['schedule_guard'].update(OTHER))
    linkbad('scheduled-profile-not-approved','scheduled-guard-current',lambda v:v.update(approved_profile_digests=[]))
    linkbad('scheduled-proof-substituted','scheduled-guard-current',lambda v:v['install']['body']['time_evidence'].update(provider_boot_id='other-provider'))
    linkbad('scheduled-sample-substituted','scheduled-guard-current',lambda v:v['install']['body']['clock_sample'].update(estimated_utc_ms=1))
    linkbad('scheduled-evidence-expired','scheduled-guard-current',lambda v:v.update(now_tick_ns='110000000000'))
    for base in ('AUTH_FENCE-complete','TIME_FENCE-complete'):
        linkbad(base+'-old-domain',base,lambda v:v['ack'].update(OTHER))
        linkbad(base+'-missing-coverage',base,lambda v:v['ack']['body'].update(coverage=[]))
    linkbad('recovery-other-runtime','recovery-linked',lambda v:v.update(trusted_domain=OTHER))
    linkbad('recovery-expired-preview','recovery-linked',lambda v:v.update(now_tick_ns=v['preview']['snapshot']['expires_tick_ns']))
    # 独立时间链允许计算验证，不调用设备。
    time=dict(sample=sample,evidence=ev,profile=p,trusted_domain=DOM,approved_profile_digests=[p['profile_digest']],active_time_state=active(ev),now_tick_ns=sample['sample_tick_ns'])
    links.append(dict(case_id='time-bound-linked',kind='time',input=time,expected=True))
    linkbad('time-profile-unapproved','time-bound-linked',lambda v:v.update(approved_profile_digests=[]))
    linkbad('time-source-identity-mismatch','time-bound-linked',lambda v:v['sample'].update(source_ref='other-source'))
    linkbad('time-age-at-limit','time-bound-linked',lambda v:v.update(now_tick_ns=str(int(v['sample']['sample_tick_ns'])+p['max_sample_age_ms']*1000000)))
    linkbad('time-source-age-at-limit','time-bound-linked',lambda v:seal(v['evidence'].update(source_age_at_capture_ns=str(p['max_source_age_ms']*1000000)) or v['evidence'],'evidence_digest'))
    def rebind_time(v):
        seal(v['evidence'],'evidence_digest');v['sample']['time_evidence_ref']=eref(v['evidence'])
    c=cp(time);c['evidence']['source_age_at_capture_ns']=str(p['max_source_age_ms']*1000000);rebind_time(c)
    links.append(dict(case_id='time-source-age-rehashed-rebound',kind='time',input=c,expected=False))
    linkbad('time-provider-restarted','time-bound-linked',lambda v:v['active_time_state'].update(provider_boot_id='new-provider-boot'))
    linkbad('time-policy-changed','time-bound-linked',lambda v:v['active_time_state'].update(time_policy_revision='99'))
    linkbad('time-tick-backwards','time-bound-linked',lambda v:v.update(now_tick_ns=str(int(v['sample']['sample_tick_ns'])-1)))
    linkbad('time-offset-needs-own-model','time-bound-linked',lambda v:v['sample'].update(mode='application_offset'))
    # 独立算术预期：100ms采集、1ns root delay、10ms离散界与100ppm，B0=111ms。
    c=cp(time);q=c['profile'];q['max_uncertainty_ms']=200;seal(q,'profile_digest')
    c.update(approved_profile_digests=[q['profile_digest']])
    s=c['sample'];t=c['evidence'];s['time_profile_ref']=pref(q);t['profile_ref']=pref(q)
    t.update(capture_start_tick_ns=str(int(t['capture_end_tick_ns'])-100000000),root_delay_ns='1',root_dispersion_ns='10000000',uncertainty_at_capture_ms=111)
    s['uncertainty_ms']=111;rebind_time(c)
    links.append(dict(case_id='time-rational-capture-bound',kind='time',input=cp(c),expected=True))
    c['now_tick_ns']=str(int(s['sample_tick_ns'])+1);w=s['estimated_utc_ms'];c['expected_interval']=[w-112,w+113]
    links.append(dict(case_id='time-outward-rounding-one-ns',kind='time',input=c,expected=True))
    def handshake():
        i=cp(next(c['frame'] for c in ipcs if c['frame']['type']=='HELLO'));a=cp(next(c['frame'] for c in ipcs if c['frame']['type']=='HELLO_ACK'));a['reply_to']=i['message_id']
        return dict(request=i,ack=a,trusted_domain=DOM,bootstrap_authenticated=True)
    links.append(dict(case_id='handshake-trusted-domain',kind='handshake',input=handshake(),expected=True))
    linkbad('handshake-self-signed-not-authorized','handshake-trusted-domain',lambda v:v.update(bootstrap_authenticated=False))
    linkbad('handshake-other-supervisor','handshake-trusted-domain',lambda v:v['ack']['body'].update(clock_domain_descriptor=descriptor(generation='other-runtime')))
    linkbad('guard-new-worker-old-permit','guard-linked',lambda v:v['dispatch'].update(worker_boot_id='new-worker'))
    # 旧域只读证据仍按内部引用链验证，不能作为当前许可。
    old_record=cp(next(c['instance'] for c in cases if c['model']=='CommandRecord' and c['instance']['attempts']))
    if old_record:
        def old_domains(v):
            if isinstance(v,dict):
                if 'clock_domain_id' in v:v.update(OTHER)
                for x in v.values():old_domains(x)
            elif isinstance(v,list):
                for x in v:old_domains(x)
        old_domains(old_record)
        cases.append(dict(case_id='historical-other-domain-readable',model='CommandRecord',instance=old_record,schema_valid=True,semantic_valid=True))
    a=cp(time);b=cp(time);b['trusted_domain']=SEAMER;b['sample'].update(SEAMER);b['evidence'].update(SEAMER)
    b['sample'].update(sample_id='evaluation-sample',estimated_utc_ms=a['sample']['estimated_utc_ms']+100)
    b['evidence'].update(evidence_id='evaluation-evidence',wall_read_utc_ms=b['sample']['estimated_utc_ms']);rebind_time(b)
    pr=cp(proof);pr.update(capture_sample_id=a['sample']['sample_id'],lower_age_ms=80,upper_age_ms=120)
    pr['utc_basis']={}
    for prefix,part in [('capture',a),('evaluation',b)]:
        pr['utc_basis'].update({prefix+'_sample_ref':dict(sample_id=part['sample']['sample_id'],sample_digest=digest(part['sample'])),prefix+'_domain':domain(part['sample']),prefix+'_evidence_ref':eref(part['evidence'])})
    links.append(dict(case_id='cross-service-utc-age',kind='age',input=dict(proof=pr,capture=a,evaluation=b),expected=True))
    linkbad('cross-service-domain-substitution','cross-service-utc-age',lambda v:v['proof']['utc_basis']['capture_domain'].update(SEAMER))
    linkbad('cross-service-age-underestimated','cross-service-utc-age',lambda v:v['proof'].update(upper_age_ms=100))
    linkbad('cross-service-stale-evaluation','cross-service-utc-age',lambda v:v['evaluation']['active_time_state'].update(clock_generation='new-generation'))
    assessment=cp(e['ClockAssessment']);s=time['sample'];w=s['estimated_utc_ms'];b=s['uncertainty_ms']
    assessment.update(sample_id=s['sample_id'],clock_generation=s['clock_generation'],policy_revision=s['policy_revision'],evaluated_tick_ns=s['sample_tick_ns'],sample_age_ms=0,
        uncertainty_now_ms=b,utc_lower_ms=w-b,utc_upper_ms=w+b,eligible_for_absolute=True,time_evidence_ref=eref(time['evidence']),time_profile_ref=pref(time['profile']))
    links.append(dict(case_id='assessment-linked-evidence',kind='assessment',input=dict(cp(time),assessment=assessment),expected=True))
    linkbad('assessment-narrowed-interval','assessment-linked-evidence',lambda v:v['assessment'].update(utc_upper_ms=v['sample']['estimated_utc_ms']))
    linkbad('assessment-other-domain','assessment-linked-evidence',lambda v:v['assessment'].update(OTHER))
    return dict(examples=cases,ipc_examples=ipcs,link_cases=links)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();data=json.dumps(build(),ensure_ascii=False,indent=2)+'\n'
    if a.check:assert (ROOT/'examples.json').read_text(encoding='utf-8')==data,'正反例漂移'
    else:(ROOT/'examples.json').write_text(data,encoding='utf-8',newline='\n')
