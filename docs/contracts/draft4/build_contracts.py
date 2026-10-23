"""NF01—NF03 契约归并，只生成设计资料，不启动业务服务。"""
import argparse
import json
from copy import deepcopy as cp
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PARENT=ROOT.parent
OLD=PARENT/'draft3'
VERSION='1.0.0-draft.4'
IPC_VERSION='ipc/0.3.0-draft.1'
BASE='https://leafseamer.invalid/contracts/draft4/first-loop.schema.json'
FEATURES=['execution_guard','scoped_authorization_fence','clock_generation_guard','typed_obs_evidence','recovery_single_consume','supervised_runtime_domain','time_bound_evidence']
def ref(n):return {'$ref':'#/$defs/'+n}
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def enum(*v):return {'enum':list(v)}
def nullable(s):return {'anyOf':[s,{'type':'null'}]}
def arr(s,n=256,minimum=0):return dict(type='array',items=s,maxItems=n,minItems=minimum,uniqueItems=True)
def condition(fields,then,otherwise=None):
    s={'if':{'properties':fields,'required':list(fields)},'then':then}
    if otherwise is not None:s['else']=otherwise
    return s
def add(d,n,**fields):
    d[n]['properties'].update(fields)
    d[n]['required']=list(dict.fromkeys(d[n]['required']+list(fields)))
def load(name):
    return json.loads((OLD/name).read_text(encoding='utf-8').replace('1.0.0-draft.3',VERSION).replace('ipc/0.2.0-draft.1',IPC_VERSION).replace('/contracts/draft3/','/contracts/draft4/'))

def build():
    s=load('first-loop.schema.json');d=s['$defs'];I,R,H=map(ref,('Id','Revision','Digest'))
    N={'type':'integer','minimum':0,'maximum':86400000};P={'type':'integer','minimum':1,'maximum':86400000}
    NS={'type':'string','pattern':'^(0|[1-9][0-9]*)$','maxLength':24}
    SNS={'type':'string','pattern':'^-?(0|[1-9][0-9]*)$','maxLength':25}
    DOMAIN={'type':'string','pattern':'^clock_[0-9a-f]{64}$'}
    domain=dict(clock_domain_id=DOMAIN,descriptor_digest=H)
    d['ClockDomainRef']=obj(**domain)
    d['EvidenceRef']=obj(evidence_id=I,evidence_digest=H)
    d['ClockSampleRef']=obj(sample_id=I,sample_digest=H)
    d['TimeProfileRef']=obj(profile_id=I,revision=R,profile_digest=H)
    d['OsBootIdentity']={'oneOf':[obj(status={'const':'unavailable'}),obj(status={'const':'verified'},source=I,value=I,evidence_ref=I)]}
    d['ClockDomainDescriptor']=obj(descriptor_version={'const':'clock-domain/1'},domain_kind={'const':'supervised_runtime'},
        authority_service_id=I,runtime_generation=I,supervisor_instance_id=I,clock_backend_id=enum('windows_interrupt_precise','linux_boottime'),
        clock_backend_revision=I,tick_unit={'const':'ns'},suspend_accounting={'const':'included'},namespace_identity=I,
        os_boot_identity=ref('OsBootIdentity'),platform_profile_id=I,platform_profile_revision=R,**domain)
    d['TimeBoundProfile']=obj(profile_id=I,revision=R,backend=enum('chrony','w32time'),parser_profile_id=I,
        model_id={'const':'system-bound/1'},validated_environment_ref=I,assumption_profile_ref=I,validation_report_ref=I,
        configured_source_set_digest=H,allowed_source_auth=arr(enum('nts','trusted_network','unverified'),3,1),
        max_capture_span_ms=P,max_source_age_ms=P,max_sample_age_ms=P,max_uncertainty_ms=P,
        drift_bound_ppm={'type':'integer','minimum':0,'maximum':10000},source_extra_bound_ns=NS,read_quantization_bound_ns=NS,profile_digest=H)
    d['TimeBoundEvidence']=obj(evidence_id=I,evidence_digest=H,provider_id=I,provider_boot_id=I,**domain,
        clock_generation=I,time_policy_revision=R,backend=enum('chrony','w32time'),parser_profile_id=I,model_id={'const':'system-bound/1'},
        profile_ref=ref('TimeProfileRef'),source_ref=I,source_auth=enum('nts','trusted_network','unverified'),configured_source_set_digest=H,
        source_update_id=I,source_age_at_capture_ns=nullable(NS),source_age_basis=enum('validated_upper_bound','unproven'),
        capture_start_tick_ns=NS,capture_end_tick_ns=NS,wall_read_utc_ms={'type':'integer','minimum':0,'maximum':9007199254740991},
        raw_response_digest=H,source_state_digest=H,leap_status=enum('normal','insert','delete','unsynchronized'),
        stratum={'type':'integer','minimum':0,'maximum':16},system_offset_ns=nullable(SNS),root_delay_ns=nullable(NS),root_dispersion_ns=nullable(NS),
        source_extra_bound_ns=nullable(NS),read_quantization_bound_ns=nullable(NS),drift_bound_ppm={'type':'integer','minimum':0,'maximum':10000},
        bound_state=enum('conditional','unproven'),uncertainty_at_capture_ms=nullable(N),reason_code=I)
    d['TimeBoundEvidence']['allOf']=[condition({'bound_state':{'const':'conditional'}},{'properties':dict(
        source_age_at_capture_ns=NS,source_age_basis={'const':'validated_upper_bound'},system_offset_ns=SNS,root_delay_ns=NS,root_dispersion_ns=NS,
        source_extra_bound_ns=NS,read_quantization_bound_ns=NS,uncertainty_at_capture_ms=N,leap_status={'const':'normal'},stratum={'type':'integer','minimum':1,'maximum':15})},
        {'properties':{'uncertainty_at_capture_ms':{'type':'null'}}})]
    # 所有既有tick消费者都显式绑定域；历史证据的域不要求等于当前域。
    for name in ('ExecutionGuard','ClockSample','ClockAssessment','ScheduleGuard','ObsEvidenceFrame','ObsCompletionBundle','RecoverySnapshot',
                 'DispatchPermit','Attempt','CompletionEvidence','ResourceReleaseEvidence','BarrierAck','ControlOperation'):
        add(d,name,**domain)
    d['ClockSample']['properties'].pop('host_boot_id');d['ClockSample']['required'].remove('host_boot_id')
    add(d,'ClockSample',time_evidence_ref=nullable(ref('EvidenceRef')),time_profile_ref=nullable(ref('TimeProfileRef')))
    d['ClockSample'].setdefault('allOf',[]).append(condition({'quality':{'const':'synchronized'}},{'properties':{
        'time_evidence_ref':ref('EvidenceRef'),'time_profile_ref':ref('TimeProfileRef'),'uncertainty_ms':N}}))
    add(d,'ClockAssessment',time_evidence_ref=nullable(ref('EvidenceRef')),time_profile_ref=nullable(ref('TimeProfileRef')))
    d['ClockAssessment']['allOf'].append(condition({'eligible_for_absolute':{'const':True}},{'properties':{
        'time_evidence_ref':ref('EvidenceRef'),'time_profile_ref':ref('TimeProfileRef')}}))
    add(d,'ExecutionGuard',clock_sample_ref=nullable(ref('ClockSampleRef')),time_evidence_ref=nullable(ref('EvidenceRef')),time_profile_ref=nullable(ref('TimeProfileRef')))
    guarded={k:ref(v) for k,v in [('clock_sample_ref','ClockSampleRef'),('time_evidence_ref','EvidenceRef'),('time_profile_ref','TimeProfileRef')]}
    d['ExecutionGuard']['allOf'].append(condition({'time_required':{'const':True}},{'properties':guarded},{'properties':{k:{'type':'null'} for k in guarded}}))
    add(d,'RecoveryTarget',baseline_domain=ref('ClockDomainRef'),target_domain=nullable(ref('ClockDomainRef')))
    d['RecoveryTarget']['allOf'].append(condition({'state':{'const':'applied'}},{'properties':{'target_domain':ref('ClockDomainRef')}}))
    # UTC年龄证明明确双方样本；causal只在验证器域内比较challenge期限。
    d['UtcAgeBasis']=obj(capture_sample_ref=ref('ClockSampleRef'),capture_domain=ref('ClockDomainRef'),
        capture_evidence_ref=ref('EvidenceRef'),evaluation_sample_ref=ref('ClockSampleRef'),evaluation_domain=ref('ClockDomainRef'),evaluation_evidence_ref=ref('EvidenceRef'))
    d['CausalAgeBasis']=obj(verifier_domain=ref('ClockDomainRef'),challenge_sent_tick_ns=NS,received_tick_ns=NS)
    add(d,'EventAgeProof',utc_basis=nullable(ref('UtcAgeBasis')),causal_basis=nullable(ref('CausalAgeBasis')))
    for basis,u,c in [('trusted_utc',ref('UtcAgeBasis'),{'type':'null'}),('causal_capture',{'type':'null'},ref('CausalAgeBasis')),('unproven',{'type':'null'},{'type':'null'})]:
        d['EventAgeProof']['allOf'].append(condition({'basis':{'const':basis}},{'properties':{'utc_basis':u,'causal_basis':c}}))
    d['ErrorCode']['enum']+=['CLOCK_DOMAIN_MISMATCH','TIME_EVIDENCE_INVALID','TIME_PROFILE_UNAPPROVED']
    s['title']='LeafSeamer NF01—NF03 归并 draft.4'
    routes=load('routes.json')
    for model,path in [('ClockDomainDescriptor','/internal/clock-domain'),('TimeBoundEvidence','/internal/time-evidence/{evidence_id}'),
                       ('TimeBoundProfile','/internal/time-profiles/{profile_id}/{revision}'),('ClockSample','/internal/clock-samples/{sample_id}')]:
        response=model+'Response';d[response]=obj(request_id=I,service_id=I,service_boot_id=I,protocol_version={'const':VERSION},data=ref(model))
        routes.append(dict(service='common',method='get',path=path,operation_id='get'+model,request=None,response=response,status='200',permission='clock.internal.read',security='mtls'))
    out={'first-loop.schema.json':s,'routes.json':routes}
    for service in ('controller','seamer'):
        api=load(service+'.openapi.json');api['components']['schemas']=json.loads(json.dumps(d).replace('#/$defs/','#/components/schemas/'))
        for r in routes[-4:]:
            op=dict(operationId=r['operation_id'],summary='内部受限时钟证据查询',security=[{'serviceMtls':[]}],**{'x-permission':r['permission'],'x-internal-only':True},responses={})
            import re
            params=[dict(name=x,**{'in':'path'},required=True,schema={'$ref':'#/components/schemas/'+('Revision' if x=='revision' else 'Id')}) for x in re.findall(r'{(\w+)}',r['path'])]
            if params:op['parameters']=params
            for status in ('200','401','403','404','412','503'):
                op['responses'][status]=dict(description='仅配对授权服务；摘要不证明授权',headers={'Cache-Control':{'schema':{'const':'no-store'}}},content={'application/json':{'schema':{'$ref':'#/components/schemas/'+(r['response'] if status=='200' else 'ErrorResponse')}}})
            api['paths'][r['path']]={'get':op}
        out[service+'.openapi.json']=api
    ipc=load('ipc.schema.json');di=ipc['$defs'];ipc['title']='LeafSeamer IPC 0.3.0-draft.1'
    ext=lambda n:{'$ref':BASE+'#/$defs/'+n}
    domains=dict(clock_domain_id=DOMAIN,descriptor_digest=ext('Digest'))
    for n,v in di.items():
        if 'clock_domain_id' in v.get('properties',{}):add(di,n,**domains)
    add(di,'IntentRef',**domains)
    for r in ipc['oneOf']:add(di,r['$ref'].split('/')[-1],**domains)
    for n in ('HELLOBody','HELLO_ACKBody'):add(di,n,clock_domain_descriptor=ext('ClockDomainDescriptor'))
    di['HELLO_ACKBody']['properties']['selected_features']['allOf']=[{'contains':{'const':f}} for f in FEATURES]
    add(di,'GUARD_INSTALLBody',time_evidence=nullable(ext('TimeBoundEvidence')),time_profile=nullable(ext('TimeBoundProfile')))
    di['GUARD_INSTALLBody']['allOf'].append(condition({'guard':{'properties':{'time_required':{'const':True}}}},
        {'properties':{'time_evidence':ext('TimeBoundEvidence'),'time_profile':ext('TimeBoundProfile')}},
        {'properties':{'time_evidence':{'type':'null'},'time_profile':{'type':'null'}}}))
    out['ipc.schema.json']=ipc
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    for name,v in build().items():
        data=json.dumps(v,ensure_ascii=False,indent=2)+'\n';path=ROOT/name
        if args.check:assert path.read_text(encoding='utf-8')==data,('生成漂移',name)
        else:path.write_text(data,encoding='utf-8',newline='\n')
