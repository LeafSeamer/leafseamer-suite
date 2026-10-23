"""从固定源生成完整候选IPC及新增绑定模型；不改旧文件。"""
import argparse
import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent/'df01-source/source'
PANEL = HERE.parent/'c09-panel'
PUBLIC = json.loads((SOURCE/'public.schema.json').read_text('utf-8'))
OLD_IPC = json.loads((SOURCE/'ipc.schema.json').read_text('utf-8'))
CHANNEL = json.loads((PANEL/'channel-v02.schema.json').read_text('utf-8'))
BID = 'https://leafseamer.invalid/design/c09-panel-ipc/binding.schema.json'
IID = 'https://leafseamer.invalid/design/c09-panel-ipc/ipc.schema.json'
VERSION = 'ipc/0.4.0-panel-draft.1'
FEATURES = ('panel_execution_binding','panel_scoped_fence')


def ref(name):
    return {'$ref': '#/$defs/'+name}


def public(name):
    return {'$ref': PUBLIC['$id']+'#/$defs/'+name}


def channel(name):
    return {'$ref': CHANNEL['$id']+'#/$defs/'+name}


def nullable(value):
    return {'anyOf': [value, {'type':'null'}]}


def obj(**fields):
    return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}


def rewrite(node, references, version=False):
    if isinstance(node,list): return [rewrite(n,references,version) for n in node]
    if not isinstance(node,dict): return node
    out={}
    for key,value in node.items():
        if key=='$ref': out[key]=references.get(value,value)
        elif key in ('const','enum','default','examples'):
            out[key] = VERSION if version and key=='const' and value=='ipc/0.3.0-draft.1' else copy.deepcopy(value)
        else: out[key]=rewrite(value,references,version)
    return out


def inherit_public(name):
    references={'#/$defs/'+n:PUBLIC['$id']+'#/$defs/'+n for n in PUBLIC['$defs']}
    return rewrite(PUBLIC['$defs'][name],references)


def add_source_binding(model, binding_schema, binding_name):
    model['properties'].update(admission_origin={'enum':['panel','non_panel']}, **{binding_name:nullable(binding_schema)})
    model['required'].extend(['admission_origin',binding_name])
    model.setdefault('allOf',[]).append({
        'if':{'properties':{'admission_origin':{'const':'panel'}},'required':['admission_origin']},
        'then':{'properties':{binding_name:binding_schema}},
        'else':{'properties':{binding_name:{'type':'null'}}}})


def build():
    binding=obj(context=channel('Guard'),principal_id=channel('Id'),extension_instance_id=channel('Id'),
                artifact_digest=channel('Digest'),scope_ref=channel('ObjectRef'),policy_ref=channel('ObjectRef'),
                lease_revision=channel('Counter'),lifetime=channel('Lifetime'))
    identity={name:channel('PositiveCounter' if name=='document_generation' else 'Id') for name in (
        'authority_service_id','database_instance_id','issuer_id','issuer_epoch','auth_session_id','panel_session_id','document_generation')}
    session_selector=obj(kind={'const':'panel_session'},**identity)
    delegation_selector=obj(kind={'const':'panel_delegation'},**identity,delegation_id=channel('Id'),revision_floor=channel('Counter'))
    selector={'oneOf':[public('RevocationSelector'),ref('PanelSessionSelector'),ref('PanelDelegationSelector')]}
    guard=inherit_public('ExecutionGuard')
    add_source_binding(guard,ref('PanelExecutionBinding'),'panel_binding')
    guard['allOf'].append({'if':{'properties':{'admission_origin':{'const':'panel'}},'required':['admission_origin']},
        'then':{'properties':{'binding':{'properties':{
            'principal_kind':{'const':'human'},'origin':{'const':'manual'},
            'extension_instance_id':public('Id'),'extension_approval_revision':public('Revision')}}}}})
    permit=inherit_public('DispatchPermit')
    add_source_binding(permit,public('Digest'),'panel_binding_digest')
    permit['allOf'].append({'if':{'properties':{'admission_origin':{'const':'panel'}},'required':['admission_origin']},
                           'then':{'properties':{'origin':{'const':'manual'}}}})
    models={'PanelExecutionBinding':binding,'PanelSessionSelector':session_selector,'PanelDelegationSelector':delegation_selector,
            'RevocationSelector':selector,'ExecutionGuard':guard,'DispatchPermit':permit}
    bs={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':BID,
        'title':'面板执行绑定与精确selector候选','x-approved':False,'x-runtime-approved':False,'$defs':models}
    references={PUBLIC['$id']+'#/$defs/'+n:BID+'#/$defs/'+n for n in ('ExecutionGuard','DispatchPermit','RevocationSelector')}
    ipc=rewrite(OLD_IPC,references,True)
    ipc.update({'$id':IID,'x-approved':False,'x-runtime-approved':False})
    d=ipc['$defs']
    for name in ('controller_boot_id','ipc_session_id','device_id'):
        d['IntentRef']['properties'][name]=public('Id')
        d['IntentRef']['required'].append(name)
    add_source_binding(d['IntentRef'],public('Digest'),'panel_binding_digest')
    for name in ('AUTH_FENCEBody','AUTH_FENCE_ACKBody'):
        d[name]['properties']['selector_digest']=public('Digest')
        d[name]['required'].append('selector_digest')
    d['GUARD_ACKBody']['properties']['panel_binding_digest']=nullable(public('Digest'))
    d['GUARD_ACKBody']['required'].append('panel_binding_digest')
    for name,field in [('HELLOBody','supported_features'),('HELLO_ACKBody','selected_features')]:
        d[name]['properties'][field].setdefault('allOf',[]).extend({'contains':{'const':feature}} for feature in FEATURES)
    return {'binding.schema.json':bs,'ipc.schema.json':ipc}


def encoded(value):
    return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for filename,value in build().items():
        if args.check:
            assert (HERE/filename).read_bytes()==encoded(value),filename
        else: (HERE/filename).write_bytes(encoded(value))
    print('候选IPC与绑定生成物一致' if args.check else '已生成候选IPC与绑定模型')
