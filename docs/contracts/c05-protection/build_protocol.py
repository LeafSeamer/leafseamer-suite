"""生成来源保护HTTP与21帧IPC归并候选；仅读固定Schema，不实现业务服务。"""
import argparse
import copy
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
FILES={
    'public':BASE/'df01-source/source/public.schema.json',
    'panel':BASE/'c09-panel-ipc/binding.schema.json',
    'ipc':BASE/'c09-panel-ipc/ipc.schema.json',
    'protection':HERE/'protection.schema.json',
}
PID='https://leafseamer.invalid/design/c05-protection/protocol.schema.json'
IID='https://leafseamer.invalid/design/c05-protection/ipc-v05.schema.json'
VERSION='protection-service/0.2.0-draft.1'
IPC_VERSION='ipc/0.5.0-automation-draft.1'
FEATURES=('automation_origin_binding','run_generation_fence','run_deny_snapshot')


def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def ref(n):return {'$ref':PID+'#/$defs/'+n}
def nullable(v):return {'anyOf':[v,{'type':'null'}]}
def arr(v,n=256):return dict(type='array',items=v,maxItems=n)
def encoded(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()


def rewrite(v,refs,local=None):
    """固定Schema闭包中的引用替换；不触碰实例常量、样例和默认值。"""
    if isinstance(v,list):return [rewrite(x,refs,local) for x in v]
    if not isinstance(v,dict):return copy.deepcopy(v)
    out={}
    for k,x in v.items():
        if k=='$ref':
            absolute=(local+x if local and x.startswith('#') else x)
            out[k]=refs.get(absolute,absolute)
        elif k in ('const','enum','examples','default'):out[k]=copy.deepcopy(x)
        else:out[k]=rewrite(x,refs,local)
    return out


def fields(s,**p):
    s['properties'].update(p)
    s['required']+=list(p)


def origin_constraint(s,condition):
    s.setdefault('allOf',[]).append({
        'if':condition,
        'then':{'properties':{'automation_binding':ref('AutomationOriginBinding')}},
        'else':{'properties':{'automation_binding':{'type':'null'}}}})


def build():
    src={k:json.loads(p.read_bytes()) for k,p in FILES.items()}
    ids={k:v['$id'] for k,v in src.items()}
    pub=lambda n:{'$ref':ids['public']+'#/$defs/'+n}
    prot=lambda n:{'$ref':ids['protection']+'#/$defs/'+n}
    d={}
    for n in ('Scope','Id','Counter','PositiveCounter','Digest','Ref','AutomationOriginBinding','RunGenerationSelector'):
        d[n]=rewrite(src['protection']['$defs'][n],{},ids['protection'])
    for n in ('RunBinding','RunGrant','CommandRequest'):
        d[n]=rewrite(src['public']['$defs'][n],{ids['public']+'#/$defs/RunBinding':ref('RunBinding')['$ref']},ids['public'])
    for n in ('RunBinding','RunGrant'):
        d[n]['properties']['definition_version']=ref('PositiveCounter')
        d[n]['properties']['arm_generation']=ref('Counter')
    d['RunBinding']['properties']['grant_revision']=ref('Counter')
    d['RunGrant']['properties']['revision']=ref('Counter')
    fields(d['RunGrant'],origin_scope=ref('Scope'))
    fields(d['CommandRequest'],automation_binding=nullable(ref('AutomationOriginBinding')))
    auto={'properties':{'origin':{'const':'automation'}},'required':['origin']}
    origin_constraint(d['CommandRequest'],auto)
    for n in ('ExecutionGuard','DispatchPermit'):
        d[n]=rewrite(src['panel']['$defs'][n],{},ids['panel'])
        fields(d[n],automation_binding=nullable(ref('AutomationOriginBinding')))
        cond=auto if n=='DispatchPermit' else {'properties':{'binding':auto},'required':['binding']}
        origin_constraint(d[n],cond)
    # 摘要以完整Guard为准；Permit同时带完整来源以便独立选择器判断。
    d['ExecutionGuard']['allOf'].append({
        'if':{'properties':{'binding':auto},'required':['binding']},
        'then':{'properties':{'binding':{'properties':{'principal_kind':{'const':'service'}}},
                              'admission_origin':{'const':'non_panel'}}}})
    d['DispatchPermit']['allOf'].append({'if':auto,'then':{'properties':{'admission_origin':{'const':'non_panel'}}}})
    d['RunDenyEntry']=obj(selector=ref('RunGenerationSelector'),deny_revision=ref('Counter'))
    d['RunDenySnapshot']=obj(controller_scope=ref('Scope'),snapshot_revision=ref('Counter'),
        entries=arr(ref('RunDenyEntry'),4096),snapshot_digest=ref('Digest'))
    d['ProtectionRequest']=rewrite(src['protection']['$defs']['ProtectionRequest'],{},ids['protection'])
    d['ProtectionRequest']['properties']['contract_version']={'const':VERSION}
    d['ControllerProtectionRecord']=prot('ControllerProtectionRecord')
    d['ProtectionLookup']=obj(contract_version={'const':VERSION},controller_scope=ref('Scope'),origin_scope=ref('Scope'),
        operation_id=ref('Id'),selector_digest=ref('Digest'),target_set_digest=ref('Digest'))
    d['ProtectionLookupResult']={'oneOf':[
        obj(state={'const':'found'},record=ref('ControllerProtectionRecord')),
        obj(state={'enum':['not_found','indeterminate']},record={'type':'null'})]}
    d['ProtectionError']=obj(code={'enum':['invalid','unauthenticated','forbidden','conflict','capacity','unavailable','version']},
        request_id=ref('Id'))
    ps={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':PID,'title':VERSION,
        'not':{},'x-approved':False,'x-runtime-approved':False,'$defs':d}
    refs={ids['panel']+'#/$defs/'+n:ref(n)['$ref'] for n in ('ExecutionGuard','DispatchPermit')}
    refs[ids['public']+'#/$defs/CommandRequest']=ref('CommandRequest')['$ref']
    ipc=rewrite(src['ipc'],refs)
    ipc.update({'$id':IID,'title':IPC_VERSION})
    di=ipc['$defs']
    for n in [r['$ref'].split('/')[-1] for r in ipc['oneOf']]:
        di[n]['properties']['ipc_version']={'const':IPC_VERSION}
    di['HELLOBody']['properties']['supported_ipc_versions']['items']={'const':IPC_VERSION}
    di['HELLO_ACKBody']['properties']['selected_ipc_version']={'const':IPC_VERSION}
    for n,f in [('HELLOBody','supported_features'),('HELLO_ACKBody','selected_features')]:
        di[n]['properties'][f].setdefault('allOf',[]).extend({'contains':{'const':x}} for x in FEATURES)
    fields(di['IntentRef'],origin={'enum':['manual','automation']},automation_binding=nullable(ref('AutomationOriginBinding')),
        automation_binding_digest=nullable(ref('Digest')))
    origin_constraint(di['IntentRef'],auto)
    di['IntentRef']['allOf'].append({'if':auto,
        'then':{'properties':{'automation_binding_digest':ref('Digest'),'admission_origin':{'const':'non_panel'}}},
        'else':{'properties':{'automation_binding_digest':{'type':'null'}}}})
    fields(di['GUARD_ACKBody'],automation_binding_digest=nullable(ref('Digest')))
    fields(di['OPEN_GATEBody'],run_deny_snapshot=ref('RunDenySnapshot'))
    fields(di['OPEN_GATE_ACKBody'],run_deny_snapshot_revision=ref('Counter'),run_deny_snapshot_digest=ref('Digest'))
    for name,old in [('RUN_FENCE','AUTH_FENCE'),('RUN_FENCE_ACK','AUTH_FENCE_ACK')]:
        frame=copy.deepcopy(di[old]);frame['properties']['type']={'const':name}
        frame['properties']['body']={'$ref':'#/$defs/'+name+'Body'}
        di[name]=frame;ipc['oneOf'].append({'$ref':'#/$defs/'+name})
    for n,source in [('RUN_FENCEBody','RunFenceBody'),('RUN_FENCE_ACKBody','RunFenceAckBody')]:
        di[n]=rewrite(src['protection']['$defs'][source],{},ids['protection'])
        field='open_intents' if n=='RUN_FENCEBody' else 'coverage'
        item={'$ref':'#/$defs/IntentRef'} if field=='open_intents' else {'$ref':'#/$defs/Coverage'}
        di[n]['properties'][field]=arr(item)
        item_cond={'properties':{'origin':{'const':'automation'}}}
        if field=='coverage':item_cond={'properties':{'intent':item_cond}}
        di[n].setdefault('allOf',[]).append({'properties':{field:{'items':item_cond}}})
    # HTTP只投影两个保护操作的可达闭包，不导出设备控制或面板内部模型。
    resources={x['$id']:x for x in src.values()};resources[PID]=ps
    components={}
    def project(v,current):
        if isinstance(v,list):return [project(x,current) for x in v]
        if not isinstance(v,dict):return copy.deepcopy(v)
        out={}
        for k,x in v.items():
            if k=='$ref':
                absolute=current+x if x.startswith('#') else x
                base,name=absolute.split('#/$defs/')
                assert base in resources and '/' not in name
                prefix='Protection' if base==ids['protection'] else 'Protocol'
                key=prefix+'_'+name
                if key not in components:
                    components[key]={}
                    components[key]=project(resources[base]['$defs'][name],base)
                out[k]='#/components/schemas/'+key
            elif k not in ('$id','$schema'):
                out[k]=copy.deepcopy(x) if k in ('const','enum','default','examples') else project(x,current)
        return out
    content=lambda name:{'application/json':{'schema':project(ref(name),PID)}}
    paths={}
    for path,op,req,res,codes in [
        ('/internal/automation/protections','protectRunGeneration','ProtectionRequest','ControllerProtectionRecord',('200','202')),
        ('/internal/automation/protections/lookup','lookupRunProtection','ProtectionLookup','ProtectionLookupResult',('200',))]:
        responses={c:dict(description='原持久操作或查询结果；不表示资源已清理',content=content(res)) for c in codes}
        for code in ('400','401','403','409','413','422','429','503'):
            responses[code]=dict(description='拒绝或不可确认；不授权设备重试',content=content('ProtectionError'))
        for response in responses.values():
            response['headers']={'Cache-Control':dict(description='禁止缓存',schema={'const':'no-store'})}
        paths[path]={'post':dict(operationId=op,security=[{'InternalMTLS':[]}],
            parameters=[dict(name='X-LeafSeamer-Contract',**{'in':'header'},required=True,schema={'const':VERSION})],
            requestBody=dict(required=True,content=content(req)),responses=responses,
            **{'x-required-permission':'automation.protect','x-required-origin-ownership':True,
               'x-retry-policy':'same-identity-monotonic-denial-only' if op=='protectRunGeneration' else 'read-only-lookup'})}
    api=dict(openapi='3.1.1',info=dict(title='运行代次保护内部接口候选',version=VERSION),paths=paths,
        components=dict(schemas=components,securitySchemes={'InternalMTLS':dict(type='mutualTLS')}))
    return {'protocol.schema.json':ps,'ipc-v05.schema.json':ipc,'protection.openapi.json':api}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,v in build().items():
        if a.check:assert (HERE/name).read_bytes()==encoded(v),name
        else:(HERE/name).write_bytes(encoded(v))
