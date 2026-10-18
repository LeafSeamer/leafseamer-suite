"""F01—F07 归并生成器，仅生成版本化协议资料。"""
import argparse
import copy
import importlib.util
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PARENT=ROOT.parent
VERSION='1.0.0-draft.3'
IPC_VERSION='ipc/0.2.0-draft.1'
BASE='https://leafseamer.invalid/contracts/draft3/first-loop.schema.json'
OLD='https://leafseamer.invalid/contracts/first-loop.schema.json#/$defs/'
FEATURES=['execution_guard','scoped_authorization_fence','clock_generation_guard','typed_obs_evidence','recovery_single_consume']


def source(path):
    spec=importlib.util.spec_from_file_location('source_'+path.parent.name+'_'+path.stem,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def ref(n):return {'$ref':'#/$defs/'+n}
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def enum(*v):return {'enum':list(v)}
def nullable(s):return {'anyOf':[s,{'type':'null'}]}
def arr(s,n=256,minimum=0):return dict(type='array',items=s,maxItems=n,minItems=minimum,uniqueItems=True)
def condition(fields,then,otherwise=None):
    s={'if':{'properties':fields,'required':list(fields)},'then':then}
    if otherwise is not None:s['else']=otherwise
    return s
def add(d,n,**fields):d[n]['properties'].update(fields);d[n]['required']+=list(fields)
def localize(value):return json.loads(json.dumps(value).replace(OLD,'#/$defs/'))


def build():
    old=source(PARENT/'build_contracts.py').build()
    schema=copy.deepcopy(old['first-loop.schema.json']);d=schema['$defs']
    for path in ('f04-f05/build_contracts.py','f06-f07/build_contracts.py'):
        extra=localize(source(PARENT/path).build()['$defs'])
        assert not set(extra)&set(d)
        d.update(extra)
    I,R,H,T=map(ref,('Id','Revision','Digest','Timestamp'));nil={'type':'null'};B={'type':'boolean'}
    schema.update({'$id':BASE,'title':'LeafSeamer F01—F07 归并 draft.3','description':'已确认设计的预发布归并；非运行证明。'})
    # 旧协议常量只在传输版本位置改变，能力版本独立。
    for n in list(d):
        if n=='Meta' or n.endswith('Response'):d[n]['properties']['protocol_version']={'const':VERSION}
    d['PrincipalRef']=obj(issuer_id=I,issuer_epoch=I,principal_id=I)
    d['SubjectRecord']=obj(local_subject_id=I,principal=ref('PrincipalRef'))
    for n in ('Actor','Session','RequestIdentity','RequestContext','RunGrant'):
        add(d,n,issuer_id=I,issuer_epoch=I)
    add(d,'Actor',local_subject_id=I)
    # 控制holder/转交target保持服务本地不可复用subject ID，查询映射完整身份。
    add(d,'SceneRef',collection_generation=R,binding_revision=R)
    d['EffectFootprint']['properties']['action_id']=d['EffectFootprint']['properties'].pop('action_ref')
    d['EffectFootprint']['required'].remove('action_ref');d['EffectFootprint']['required'].append('action_id')
    add(d,'ActionDescriptor',footprint=ref('EffectFootprint'))
    add(d,'EventEnvelope',age_proof=ref('EventAgeProof'))
    add(d,'DispatchPermit',guard_id=I,guard_digest=H)
    for name in ('ObsEvidenceFrame','ObsCompletionBundle'):add(d,name,clock_domain_id=I)
    d['ResourceReleaseEvidence']=obj(evidence_id=I,command_id=I,attempt_id=I,worker_boot_id=I,device_session_id=I,
        policy_id=I,kind=enum('module_settled','maintenance_fenced','never_sent'),durable={'const':True})
    # 未知原终态不能改写；仅追加核对结果及独立释放证明后清资源。
    for rule in d['CommandRecord']['allOf']:
        if rule['if']['properties'].get('outcome')=={'const':'unknown'}:
            rule['then']['properties']['resource_status']=enum('unresolved','clear')
    d['CommandRecord']['allOf'].append(condition({'outcome':{'const':'unknown'},'resource_status':{'const':'clear'}},
        {'required':['resolution'],'properties':{'resource_evidence_ids':{'minItems':1}}}))
    d['ObsCompletionBundle']['properties']['durable']={'const':True}
    add(d,'CompletionEvidence',obs_bundle=nullable(ref('ObsCompletionBundle')))
    add(d,'CommandRecord',completion_evidence=arr(ref('CompletionEvidence')),resource_release_evidence=arr(ref('ResourceReleaseEvidence')),
        admission=ref('AdmissionDecision'))
    d['CommandRecord']['allOf'].append({'properties':{'admission':{'properties':{'decision':{'const':'accepted'}}}}})
    d['CommandRecord']['allOf'].append(condition({'target':{'properties':{'action_id':{'const':'obs.program_scene.set'}}},'outcome':{'const':'succeeded'}},
        {'properties':{'completion_evidence':{'minItems':1,'contains':{'properties':{'obs_bundle':{'type':'object'}},'required':['obs_bundle']}}}}))
    # 声明中的 proof 是权威引用，证明本身只出现在发布记录及只读查询。
    d['ProofRef']=obj(proof_id=I,proof_revision=R)
    d['StepDefinition']['properties'].pop('independence_proof_revision')
    d['StepDefinition']['properties']['independence_proof']=ref('ProofRef')
    d['StepDefinition']['allOf'][0]['then']['required']=['independence_proof']
    add(d,'DefinitionRecord',independence_proofs=arr(ref('IndependenceProof')))
    d['ProofActionBinding']=obj(action_ref=ref('ActionRef'),manifest_digest=H,module_artifact_digest=H,
        semantics_revision=R,parameters_schema_digest=H,catalog_revision=R,controller_id=I,control_epoch=I)
    add(d,'IndependenceProof',definition_id=I,definition_version=ref('Version'),action_bindings=arr(ref('ProofActionBinding'),256,1),dependency_graph_digest=H,dsl_version=I,alias_revision=R)
    d['RecoveryPlanItem']=obj(step_id=I,source_execution_id=I,source_command_id=nullable(I),
        decision=enum('retain_success','execute_new','reconcile_commit','stop'),reason=I,
        parameters_digest=H,evidence_ids=arr(I),max_queue_ms=ref('Duration'),evidence_timeout_ms=ref('Duration'),
        not_before=nullable(T),not_after=nullable(T))
    d['RecoveryPlan']=obj(items=arr(ref('RecoveryPlanItem')),resource_keys=arr({'type':'string','maxLength':512}),target_controller_ids=arr(I,256,1))
    d['RecoveryPreview']=obj(snapshot=ref('RecoverySnapshot'),plan=ref('RecoveryPlan'),observations=arr(ref('Observation')))
    d['RecoveryTarget']=obj(controller_id=I,operation_id=I,execution_id=I,baseline_control_digest=H,target_control_digest=H,
        baseline_arm_generation=R,target_arm_generation=R,grant_id=I,grant_revision=R,
        state=enum('pending','applied','revoking','revoked','indeterminate'),receipt_id=nullable(I),durable=B)
    d['RecoveryTarget']['allOf']=[condition({'state':{'const':'applied'}},{'properties':{'receipt_id':I,'durable':{'const':True}}})]
    add(d,'RecoveryOperation',plan_digest=H,baseline_snapshot_digest=H,target_controller_ids=arr(I,256,1),targets=arr(ref('RecoveryTarget')))
    d['RecoveryOperation']['allOf']=[condition({'state':enum('ready','running','completed')},
        {'properties':{'targets':{'minItems':1,'items':{'properties':{'state':{'const':'applied'},'durable':{'const':True}}}}}})]
    # 身份、时间及容量 API 的具体封闭输入/输出。
    secret={'type':'string','minLength':16,'maxLength':4096,'writeOnly':True}
    identity=dict(context_id=I,idempotency_key=I)
    d['BootstrapRequest']=obj(bootstrap_token=secret,login={'type':'string','minLength':1,'maxLength':128},password=secret,
        mode=enum('standalone','suite_issuer'))
    d['LoginRequest']=obj(login={'type':'string','minLength':1,'maxLength':128},password=secret)
    d['RefreshRequest']=obj(client_instance_id=I)
    d['TokenRequest']=obj(audience=I,requested_scopes=arr(I,64,1),extension_instance_id=nullable(I))
    d['TokenResult']=obj(access_token={'type':'string','minLength':16,'maxLength':4096},token_type={'const':'Bearer'},
        expires_in=ref('Duration'),audience=I)
    d['IntrospectRequest']=obj(token=secret,audience=I,challenge_id=I,required_revision=R)
    d['IntrospectResult']=obj(active=B,snapshot=nullable(ref('AuthorizationSnapshot')))
    d['IntrospectResult']['allOf']=[condition({'active':{'const':True}},{'properties':{'snapshot':{'allOf':[ref('AuthorizationSnapshot'),{'properties':{'state':{'const':'active'}}}]}}},{'properties':{'snapshot':nil}})]
    d['RevocationRequest']=obj(**identity,selector=ref('RevocationSelector'),expected_revision=R,reason=I)
    d['WsTicketRequest']=obj(**identity,origin=d['WsTicketBinding']['properties']['origin'],
        subscription_scope=arr(I,64,1),client_instance_id=I)
    d['WsTicketResult']=obj(ticket={'type':'string','minLength':16,'maxLength':4096,'pattern':'^[A-Za-z0-9_-]+$'},binding=ref('WsTicketBinding'))
    d['CapacityStatus']=obj(profile_id=I,profile_revision=R,pressure=enum('normal','limited','protected'),
        usage=arr(obj(dimension=I,used={'type':'integer','minimum':0},limit={'type':'integer','minimum':1})),reasons=arr(I))
    d['CapacityUpdate']=obj(**identity,expected_revision=R,profile=ref('CapacityProfile'))
    d['CapacityUpdate']['properties']['profile']={'allOf':[ref('CapacityProfile'),{'properties':{'purpose':{'const':'release_candidate'}}}]}
    d['EvidencePage']=obj(items=arr(ref('CompletionEvidence')),resource_releases=arr(ref('ResourceReleaseEvidence')),next_cursor=nullable(I))
    codes=['PRECONDITION_CHANGED','PREVIEW_CONSUMED','PREVIEW_EXPIRED','PROOF_STALE','CATALOG_STALE','GUARD_MISSING','TICKET_INVALID']
    d['ErrorCode']['enum']+=codes
    add(d,'Error',existing_operation_id=nullable(I))
    # 同样的响应封装；组件文档各自自包含。
    for model in ('SubjectRecord','AuthorizationSnapshot','ClockAssessment','RevocationRecord','WsTicketResult','WsTicketBinding',
                  'CapacityStatus','RecoveryOperation','CatalogBinding','EvidencePage','IndependenceProof','TokenResult','IntrospectResult'):
        d[model+'Response']=obj(request_id=I,service_id=I,service_boot_id=I,protocol_version={'const':VERSION},data=ref(model))
    routes=copy.deepcopy(old['routes.json'])
    for r in routes:
        r['security']='bearer'
        if r['operation_id']=='resumeRun':r['response']='RecoveryOperationResponse'
    def route(service,method,path,name,req,res,status='200',permission='status.read',security='bearer'):
        routes.append(dict(service=service,method=method,path=path,operation_id=name,request=req,response=res,status=status,permission=permission,security=security))
    for path,name,req,res,status,sec in [
        ('/auth/bootstrap','bootstrap','BootstrapRequest','SessionResponse','201','bootstrap'),
        ('/auth/sessions','login','LoginRequest','SessionResponse','201','login'),
        ('/auth/sessions/refresh','refreshSession','RefreshRequest','SessionResponse','200','cookie'),
        ('/auth/service-tokens','issueToken','TokenRequest','TokenResultResponse','201','cookie'),
        ('/internal/auth/introspect','introspect','IntrospectRequest','IntrospectResultResponse','200','mtls')]:
        route('controller','post',path,name,req,res,status,'auth.'+name,sec)
    for path,name,req,res,status in [
        ('/api/v1/auth/revocations','revokeAuthorization','RevocationRequest','RevocationRecordResponse','202'),
        ('/api/v1/ws-tickets','issueWsTicket','WsTicketRequest','WsTicketResultResponse','201')]:
        route('common','post',path,name,req,res,status,'auth.manage' if 'revocations' in path else 'subscription.create')
    for path,name,res,perm in [
        ('/api/v1/auth/revocations/{operation_id}','getRevocation','RevocationRecordResponse','auth.read'),
        ('/api/v1/clock-assessment','getClockAssessment','ClockAssessmentResponse','status.read'),
        ('/api/v1/capacity','getCapacity','CapacityStatusResponse','status.read'),
        ('/api/v1/subjects/{subject_id}','getSubject','SubjectRecordResponse','identity.read')]:
        route('common','get',path,name,None,res,permission=perm)
    route('common','put','/api/v1/capacity/profile','setCapacity','CapacityUpdate','MutationReceiptResponse','202','capacity.manage')
    route('controller','get','/api/v1/devices/{device_id}/scene-catalog','getSceneCatalog',None,'CatalogBindingResponse',permission='device.read')
    route('controller','get','/api/v1/commands/{command_id}/evidence','getCommandEvidence',None,'EvidencePageResponse',permission='command.read')
    route('seamer','get','/api/v1/recovery-operations/{operation_id}','getRecoveryOperation',None,'RecoveryOperationResponse',permission='run.read')
    route('seamer','get','/api/v1/definitions/{definition_id}/proofs/{proof_id}','getIndependenceProof',None,'IndependenceProofResponse',permission='definition.read')
    out={'first-loop.schema.json':schema,'routes.json':routes}
    for service in ('controller','seamer'):
        api=copy.deepcopy(old[service+'.openapi.json']);api['info']['version']=VERSION
        api['components']['schemas']=json.loads(json.dumps(d).replace('#/$defs/','#/components/schemas/'))
        api['components']['securitySchemes']={
            'bearerAuth':{'type':'http','scheme':'bearer','description':'短期不透明定向访问令牌；每次受理与最终派发复核。'},
            'sessionCookie':{'type':'apiKey','in':'cookie','name':'leafseamer_session'},
            'csrfHeader':{'type':'apiKey','in':'header','name':'X-CSRF-Token'},
            'serviceMtls':{'type':'mutualTLS'},
            'wsTicketHeader':{'type':'apiKey','in':'header','name':'Sec-WebSocket-Protocol','description':'leafseamer.v1, leafseamer.ticket.<单次票据>；服务端只回显leafseamer.v1，禁止日志记录票据。'}}
        api['paths']={}
        def media(n):return {'application/json':{'schema':{'$ref':'#/components/schemas/'+n}}}
        for r in routes:
            if r['service'] not in ('common',service):continue
            security={'bearer':[{'bearerAuth':[]}],'cookie':[{'sessionCookie':[],'csrfHeader':[]}],
                'mtls':[{'serviceMtls':[]}],'bootstrap':[],'login':[]}[r['security']]
            op={'operationId':r['operation_id'],'summary':r['operation_id'],'x-permission':r['permission'],'security':security,
                'responses':{r['status']:{'description':'可靠受理，非设备执行或屏障完成' if r['status']=='202' else '结果','content':media(r['response'])}}}
            params=[{'name':p,'in':'path','required':True,'schema':{'$ref':'#/components/schemas/Id'}} for p in re.findall(r'{(\w+)}',r['path'])]
            if r['operation_id'] in ('listDevices','getSnapshot','getCommandEvidence'):params.append({'name':'cursor','in':'query','schema':{'$ref':'#/components/schemas/Id'}})
            if r['security'] in ('cookie','login','bootstrap'):
                params.append({'name':'Origin','in':'header','required':True,'schema':{'type':'string','format':'uri'}})
                op['x-origin-policy']='精确同站来源白名单；非浏览器Origin不替代认证。'
            if params:op['parameters']=params
            if r['request']:op['requestBody']={'required':True,'content':media(r['request'])}
            if r['request'] and r['status'] in ('201','202') and r['security'] not in ('login','bootstrap','cookie'):
                op['responses']['200']={'description':'原请求身份的既有结果，仍检查当前读取权限','content':media(r['response'])}
            if r['operation_id']=='issueWsTicket':
                op['responses']['200']={'description':'已签发操作的非秘密绑定状态；票据只在首次201返回，丢失后须新授权请求，不能重发旧票据。','content':media('WsTicketBindingResponse')}
            if r['operation_id'] in ('login','bootstrap','refreshSession'):
                op['responses'][r['status']]['headers']={'Set-Cookie':{'description':'Secure; HttpOnly; SameSite=Strict; Path=/auth；单次轮换。', 'schema':{'type':'string'}},
                    'X-CSRF-Token':{'description':'会话绑定随机CSRF令牌，只经可信来源暴露。','schema':{'type':'string'}},
                    'Cache-Control':{'schema':{'const':'no-store'}}}
            for status in ('400','401','403','404','409','410','412','413','422','429','503'):
                op['responses'][status]={'description':'拒绝不授权重投；先核对既有身份','content':media('ErrorResponse')}
            if r['operation_id'] in ('issueToken','issueWsTicket','introspect'):
                for response in op['responses'].values():response.setdefault('headers',{})['Cache-Control']={'schema':{'const':'no-store'}}
            api['paths'].setdefault(r['path'],{})[r['method']]=op
        api['paths']['/api/v1/events']={'get':{'operationId':'openEvents','security':[{'wsTicketHeader':[]}],
            'parameters':[{'name':'Origin','in':'header','required':True,'schema':{'type':'string','format':'uri'}}],
            'x-ticket-binding-schema':'#/components/schemas/WsTicketBinding','x-websocket-frame-schema':'#/components/schemas/WsFrame',
            'x-offered-subprotocols':['leafseamer.v1','leafseamer.ticket.<base64url>'],
            'responses':{'101':{'description':'消费单次票据并重新鉴权后升级','headers':{'Sec-WebSocket-Protocol':{'schema':{'const':'leafseamer.v1'}}}},
                '401':{'description':'票据无效或过期','content':media('ErrorResponse')},'403':{'description':'来源或范围拒绝','content':media('ErrorResponse')}}}}
        out[service+'.openapi.json']=api
    out['ipc.schema.json']=ipc(d)
    return out


def ipc(public):
    s=source(PARENT/'f02-f03/build_ipc.py').build()
    s=json.loads(json.dumps(s).replace(OLD,BASE+'#/$defs/').replace('ipc/0.1.0-draft.1',IPC_VERSION))
    s['$id']='https://leafseamer.invalid/contracts/draft3/ipc.schema.json';s['title']='LeafSeamer 内部IPC 0.2.0-draft.1'
    d=s['$defs'];I={'$ref':BASE+'#/$defs/Id'};R={'$ref':BASE+'#/$defs/Revision'};H={'$ref':BASE+'#/$defs/Digest'}
    def p(n):return {'$ref':BASE+'#/$defs/'+n}
    add(d,'IntentRef',guard_id=I,guard_digest=H)
    add(d,'HELLOBody',supported_features=arr(I,32,1))
    add(d,'HELLO_ACKBody',selected_features=arr(I,32,1))
    d['HELLO_ACKBody']['properties']['selected_features']['allOf']=[{'contains':{'const':feature}} for feature in FEATURES]
    add(d,'DISPATCHBody',guard_id=I,guard_digest=H)
    guard_body=obj(guard=p('ExecutionGuard'),content_digest=H,clock_sample=nullable(p('ClockSample')),schedule_guard=nullable(p('ScheduleGuard')))
    guard_body['allOf']=[condition({'guard':{'properties':{'time_required':{'const':True}}}},
        {'properties':{'clock_sample':p('ClockSample'),'schedule_guard':p('ScheduleGuard')}},
        {'properties':{'clock_sample':{'type':'null'},'schedule_guard':{'type':'null'}}})]
    auth=obj(operation_id=I,barrier_id=I,selector=p('RevocationSelector'),target_authorization_revision=R,
        issued_cut_revision=R,ledger_digest=H,open_intents=arr(ref('IntentRef')))
    time=obj(operation_id=I,barrier_id=I,clock_domain_id=I,time_policy_revision=R,old_clock_generation=I,new_clock_generation=I,
        issued_cut_revision=R,ledger_digest=H,open_intents=arr(ref('IntentRef')))
    def ack(body):
        v=copy.deepcopy(body);v['properties'].pop('open_intents');v['required'].remove('open_intents')
        v['properties'].update(coverage=arr(ref('Coverage')),invalidated_permit_ids=arr(I),in_flight_command_ids=arr(I),
            unresolved_command_ids=arr(I),all_write_exits_fenced={'const':True})
        v['required']=list(v['properties']);return v
    bodies={'GUARD_INSTALL':guard_body,'GUARD_ACK':obj(guard_id=I,guard_digest=H,content_digest=H,permit_id=I,command_id=I,installed_authorization_revision=R,state={'const':'installed'}),
        'AUTH_FENCE':auth,'AUTH_FENCE_ACK':ack(auth),'TIME_FENCE':time,'TIME_FENCE_ACK':ack(time)}
    bodies['AUTH_FENCE_ACK']['properties']['applied_authorization_revision']=R;bodies['AUTH_FENCE_ACK']['required'].append('applied_authorization_revision')
    for kind,body in bodies.items():
        d[kind+'Body']=body
        d[kind]=obj(ipc_version={'const':IPC_VERSION},type={'const':kind},message_id=I,reply_to=I if kind.endswith('_ACK') else {'type':'null'},
            ipc_session_id=I,controller_boot_id=I,worker_boot_id=I,seq={'type':'string','pattern':'^[1-9][0-9]*$','maxLength':20},device_id=I,body=ref(kind+'Body'))
        s['oneOf'].append(ref(kind))
    candidate=copy.deepcopy(public['ObsCompletionBundle']);candidate['properties']['durable']={'const':False}
    candidate=json.loads(json.dumps(candidate).replace('#/$defs/',BASE+'#/$defs/'))
    d['ObsCompletionCandidate']=candidate
    body=d['EVIDENCE_CANDIDATEBody'];body['properties']['evidence_kind']['enum'].append('obs_completion')
    body['properties']['payload']={'oneOf':[p('Payload'),ref('ObsCompletionCandidate')]}
    # Payload可接受任意有限JSON，与typed bundle重叠；使用条件定向，而非重叠oneOf。
    body['properties']['payload']={}
    body['allOf']=[condition({'evidence_kind':{'const':'obs_completion'}},{'properties':{'payload':ref('ObsCompletionCandidate')}},
        {'properties':{'payload':p('Payload')}})]
    return s


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    for name,value in build().items():
        data=json.dumps(value,ensure_ascii=False,indent=2)+'\n';path=ROOT/name
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8')!=data:raise SystemExit('生成物漂移：'+name)
        else:path.write_text(data,encoding='utf-8',newline='\n')
