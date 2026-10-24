"""同版扩展执行绑定和完整IPC，旧版本原字节不变。"""
import argparse,copy,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
VERSION='continuation-execution/0.1.0-draft.1';IPC_VERSION='ipc/0.14.0-continuation-draft.1'
FEATURE='continuation_grant_binding';SID='https://leafseamer.invalid/design/c04-lifecycle/continuation-binding.schema.json'
SOURCES=[BASE/p for p in ('c08-controller/journal-ipc.schema.json','c04-lifecycle/lifecycle.schema.json','c04-program/program.schema.json','c04-lifecycle/continuation-protocol.schema.json')]
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def ref(n):return {'$ref':'#/$defs/'+n}
def raw(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def walk(value,fn):
    if isinstance(value,list):return [walk(v,fn) for v in value]
    if not isinstance(value,dict):return copy.deepcopy(value)
    return {k:fn(v) if k=='$ref' else copy.deepcopy(v) if k in ('const','enum','examples') else walk(v,fn) for k,v in value.items()}
def add(s,**p):
    assert not set(s['properties'])&set(p);s['properties'].update(p);s['required']+=list(p)
def closure(d,roots):
    keep={}
    def use(uri):
        assert uri.startswith('#/$defs/');name=uri.split('/')[-1]
        if name not in keep:keep[name]={};keep[name]=walk(d[name],use)
        return uri
    for root in roots:use('#/$defs/'+root)
    return keep

def build():
    ipc,life,program,continuation=[json.loads(p.read_bytes()) for p in SOURCES];d=ipc['$defs']
    d['CN__Ref']=copy.deepcopy(continuation['$defs']['Ref']);d['CN__Scope']=copy.deepcopy(continuation['$defs']['Scope'])
    ident=continuation['$defs']['Request']['properties']['transfer_id']
    d['CN__ExecutionRef']=obj(kind={'const':'execution_binding'},scope=ref('CN__Scope'),object_id=ident,
        revision=continuation['$defs']['Ref']['properties']['revision'],digest=ref('S0__Digest'))
    d['CN__Selection']=obj(**{k:ref('CN__Ref') for k in ('transfer_ref','adoption_ref','receipt_ref','grant_ref','plan_ref','parent_preparation_ref')})
    d['CN__Target']=obj(controller_scope=ref('CN__Scope'),selection=ref('CN__Selection'),device_ids=dict(type='array',items=ident,minItems=1,maxItems=256,uniqueItems=True))
    for prefix,source in [('EB__',life),('PG__',program)]:
        for name,value in source['$defs'].items():
            def rename(uri):
                if uri.startswith('#'):return '#/$defs/'+prefix+uri.split('/')[-1]
                if uri.startswith(program['$id']+'#/$defs/'):return '#/$defs/PG__'+uri.split('/')[-1]
                raise ValueError('unexpected external reference')
            d[prefix+name]=walk(value,rename)
    eb=d['EB__ExecutionBinding']
    add(eb,binding_version={'const':VERSION},authorization_mode={'enum':['preparation','continuation']},
        continuations=dict(type='array',items=ref('CN__Target'),maxItems=32,uniqueItems=True))
    eb.setdefault('allOf',[]).append({'if':{'properties':{'authorization_mode':{'const':'continuation'}}},
        'then':{'properties':{'continuations':{'minItems':1},'origin':{'properties':{'kind':{'const':'trigger'}}},'arm_generation':{'pattern':'^[1-9][0-9]{0,19}(?![\\s\\S])'}}},
        'else':{'properties':{'continuations':{'maxItems':0}}}})
    ab=d['S2__AutomationOriginBinding'];add(ab,binding_version={'const':VERSION},authorization_mode={'enum':['preparation','continuation']},
        continuation={'oneOf':[ref('CN__Selection'),{'type':'null'}]})
    ab['properties']['origin_scope']=ref('CN__Scope');ab['properties']['execution_binding_ref']=ref('CN__ExecutionRef')
    for field in ('run_id','execution_id','step_id','logical_action_id'):ab['properties'][field]=copy.deepcopy(ident)
    ab.setdefault('allOf',[]).append({'if':{'properties':{'authorization_mode':{'const':'continuation'}}},
        'then':{'properties':{'continuation':ref('CN__Selection')}},'else':{'properties':{'continuation':{'type':'null'}}}})
    # 普通和重传body都沿原引用取得同一AutomationOriginBinding，无额外复制子类型。
    content=copy.deepcopy(d['S2__CommandRequest'])
    for field in ('context_id','idempotency_key','correlation_id'):content['properties'].pop(field,None)
    content['required']=[k for k in content['required'] if k not in ('context_id','idempotency_key','correlation_id')]
    d['CN__CommandContent']=content
    aliases={'ExecutionBinding':'EB__ExecutionBinding','ContinuationSelection':'CN__Selection','ContinuationTarget':'CN__Target',
        'CommandRequest':'S2__CommandRequest','CommandContent':'CN__CommandContent','AutomationOriginBinding':'S2__AutomationOriginBinding',
        'ExecutionGuard':'S2__ExecutionGuard','TransmissionPermit':'S9__TransmissionPermit','GuardAck':'S9__GUARD_ACKBody',
        'DispatchBody':'S9__DISPATCHBody','DispatchIntent':'S9__IntentRef'}
    for name,target in aliases.items():d[name]=ref(target)
    for root in ipc['oneOf']:
        f=d[root['$ref'].split('/')[-1]];assert f['properties']['ipc_version']['const']=='ipc/0.13.0-journal-draft.1'
        f['properties']['ipc_version']={'const':IPC_VERSION}
    d['S9__HELLOBody']['properties']['supported_ipc_versions']['items']={'const':IPC_VERSION}
    d['S9__HELLO_ACKBody']['properties']['selected_ipc_version']={'const':IPC_VERSION}
    for name,key in [('S9__HELLOBody','supported_features'),('S9__HELLO_ACKBody','selected_features')]:
        d[name]['properties'][key]['allOf'].append({'contains':{'const':FEATURE}})
    ipc.update({'$id':SID.replace('.schema.json','-ipc.schema.json'),'title':IPC_VERSION,'x-approved':False,'x-runtime-approved':False})
    ipc['$defs']=closure(d,[r['$ref'].split('/')[-1] for r in ipc['oneOf']])
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'title':VERSION,'x-approved':False,'not':{},'$defs':closure(d,aliases)}
    manifest=dict(contract_version=VERSION,ipc_version=IPC_VERSION,approved=False,required_feature=FEATURE,
        frame_types=sorted(d[r['$ref'].split('/')[-1]]['properties']['type']['const'] for r in ipc['oneOf']),exports=list(aliases),
        digest_projections=dict(execution_binding='exclude-top-level-binding_digest',guard='exclude-top-level-guard_digest',
            command_content='exclude-top-level-context_id-idempotency_key-correlation_id',dispatch_intent='full-automation-binding-digest-in-existing-intent-ref'),
        sql_mapping_status='pending-final-admission-and-provider-merge')
    return {'continuation-binding.schema.json':schema,'continuation-binding-ipc.schema.json':ipc,'continuation-binding-manifest.json':manifest}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,value in build().items():
        if a.check:assert (HERE/name).read_bytes()==raw(value),name
        else:(HERE/name).write_bytes(raw(value))
