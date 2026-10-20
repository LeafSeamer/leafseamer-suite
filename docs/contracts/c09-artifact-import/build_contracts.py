"""生成扩展包与本机导入IPC设计候选，不导入文件或运行扩展。"""
import argparse
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/c09-artifact-import/artifact.schema.json'
IID='https://leafseamer.invalid/design/c09-artifact-import/ipc.schema.json'
INSTALL=json.loads((HERE.parent/'c09-installation/installation.schema.json').read_bytes())['$id']
VERSION='extension-artifact/0.1.0-draft.1'
IPC_VERSION='extension-import/0.1.0-draft.1'


def ref(n): return {'$ref':'#/$defs/'+n}
def installation(n): return {'$ref':INSTALL+'#/$defs/'+n}
def obj(**p): return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def enum(*v): return {'enum':list(v)}
def array(v,maximum=128,minimum=0): return dict(type='array',items=v,maxItems=maximum,minItems=minimum,uniqueItems=True)
def nullable(v): return {'anyOf':[v,{'type':'null'}]}
def constant(v): return {'const':v}
def text(maximum=160): return dict(type='string',minLength=1,maxLength=maximum)
def encoded(v): return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def build():
    d={n:installation(n) for n in ('Id','U20','Digest','ClockRef','Permission','ArtifactIntakeReceipt')}
    roles={'device':'DeviceRef','source':'SourceRef','data_object':'DataObjectRef','secret_role':'SecretRoleRef',
           'filesystem_role':'FilesystemRoleRef','helper_artifact':'HelperArtifactRef','protocol_profile':'ProtocolProfileRef',
           'validation_policy':'ValidationPolicyRef','run':'RunRef'}
    role_names=list(roles)+['endpoint']
    d['RoleDeclaration']=obj(role_id=ref('Id'),kind=enum(*role_names),minimum=dict(type='integer',minimum=1,maximum=64),
                              maximum=dict(type='integer',minimum=1,maximum=64),purpose=text())
    for kind,target in roles.items():
        d['Binding_'+kind]=obj(role_id=ref('Id'),kind=constant(kind),values=array(installation(target),64,1),
                                configuration_ref=installation('ConfigurationRef'))
    d['Binding_endpoint']=obj(role_id=ref('Id'),kind=constant('endpoint'),
        values=array(obj(host=text(253),port=dict(type='integer',minimum=1,maximum=65535)),1,1),configuration_ref=installation('ConfigurationRef'))
    d['RoleBinding']={'oneOf':[ref('Binding_'+k) for k in role_names]}
    scopes={
        'device_scope':obj(device_role=ref('Id'),action_ids=array(ref('Id')),trigger_ids=array(ref('Id'))),
        'data_scope':obj(data_role=ref('Id'),access=enum('read','propose')),
        'network_endpoint':obj(endpoint_role=ref('Id'),protocol_profile_role=ref('Id'),transport=enum('tcp','udp','https','wss'),
            min_port=dict(type='integer',minimum=1,maximum=65535),max_port=dict(type='integer',minimum=1,maximum=65535)),
        'secret_role':obj(secret_role=ref('Id'),device_role=nullable(ref('Id')),source_role=nullable(ref('Id'))),
        'filesystem_root_role':obj(filesystem_role=ref('Id'),access=enum('read','cache_write'),quota_bytes=ref('U20')),
        'helper_artifact':obj(helper_role=ref('Id'),launch_policy_role=ref('Id'),helper_file_id=ref('Id')),
        'panel_method':obj(authority=enum('controller','seamer'),method_ids=array(ref('Id'),35,1),object_roles=array(ref('Id'),128,1)),
        'protocol_io':obj(protocol_profile_role=ref('Id'),endpoint_request_id=ref('Id'),
            frame_classes=array(enum('authentication','query','subscription','keepalive','ack','control'),6,1)),
    }
    for kind,scope in scopes.items(): d['Template_'+kind]=obj(request_id=ref('Id'),kind=constant(kind),purpose=text(),scope=scope)
    d['PermissionTemplate']={'oneOf':[ref('Template_'+k) for k in scopes]}
    d['FileEntry']=obj(file_id=ref('Id'),path=text(240),size_bytes=ref('U20'),digest=ref('Digest'),
        role=enum('module','native_helper','panel','schema','license','dependency_lock','resource','policy'),executable=dict(type='boolean'))
    d['FileInventory']=obj(inventory_version=constant('extension-files/1'),files=array(ref('FileEntry'),65536,1))
    d['Entrypoint']=obj(entry_id=ref('Id'),kind=enum('worker','panel','helper'),file_id=ref('Id'),
        loader=enum('node_module','native_binary','static_document'),io_policy_file_id=nullable(ref('Id')))
    d['Manifest']=obj(manifest_version=constant(VERSION),extension_id=ref('Id'),extension_version=text(80),
        kind=enum('device_module','data_source','panel','nodecg_bridge'),publisher_id=ref('Id'),source_revision=ref('Id'),
        inventory_digest=ref('Digest'),dependency_lock_file_id=ref('Id'),license_file_ids=array(ref('Id'),64,1),
        capability_template_file_ids=array(ref('Id'),64),configuration_schema_file_id=ref('Id'),
        platforms=array(enum('windows-x64','linux-x64'),2,1),api_versions=array(text(80),16,1),ipc_versions=array(text(80),16),
        required_features=array(ref('Id')),entrypoints=array(ref('Entrypoint'),32,1),roles=array(ref('RoleDeclaration')),
        permission_templates=array(ref('PermissionTemplate')))
    d['RoleResolution']=obj(resolution_id=ref('Id'),authority_service_id=ref('Id'),database_instance_id=ref('Id'),installation_id=ref('Id'),
        manifest_digest=ref('Digest'),artifact_set_digest=ref('Digest'),configuration_ref=installation('ConfigurationRef'),
        bindings=array(ref('RoleBinding')),permissions=array(ref('Permission')),resolution_digest=ref('Digest'))
    d['ResolvedReview']=obj(resolution_id=ref('Id'),resolution_digest=ref('Digest'),review=installation('PermissionReview'))
    d['ImportIdentity']=obj(host_installation_id=ref('Id'),client_registration_id=ref('Id'),import_request_id=ref('Id'))
    d['ImportBegin']=obj(identity=ref('ImportIdentity'),target_authority_service_id=ref('Id'),source_attachment_id=ref('Id'),
        package_digest=ref('Digest'),package_bytes=ref('U20'),expected_manifest_digest=ref('Digest'),host_trust_epoch=ref('U20'),
        release_authorization_ref=installation('ReleaseAuthorizationRef'),validation_policy_ref=installation('ValidationPolicyRef'))
    d['ImportStatus']=obj(identity=ref('ImportIdentity'),intent_digest=ref('Digest'),operation_id=ref('Id'),
        state=enum('accepted','copying','validating','sealing','sealed','cancelled','rejected','indeterminate'),
        target_authority_service_id=ref('Id'),package_digest=ref('Digest'),receipt=nullable(ref('ArtifactIntakeReceipt')),
        reason_code=nullable(enum('operator_cancelled','content_mismatch','invalid_archive','trust_denied','capacity','storage_unknown','source_unavailable')))
    d['ImportStatus']['allOf']=[{'if':{'properties':{'state':constant('sealed')}},'then':{'properties':{'receipt':ref('ArtifactIntakeReceipt'),'reason_code':{'type':'null'}}},
        'else':{'properties':{'receipt':{'type':'null'}}}},
        {'if':{'properties':{'state':enum('accepted','copying','validating','sealing')}},'then':{'properties':{'reason_code':{'type':'null'}}}},
        {'if':{'properties':{'state':constant('cancelled')}},'then':{'properties':{'reason_code':constant('operator_cancelled')}}},
        {'if':{'properties':{'state':constant('indeterminate')}},'then':{'properties':{'reason_code':constant('storage_unknown')}}},
        {'if':{'properties':{'state':constant('rejected')}},'then':{'properties':{'reason_code':enum('content_mismatch','invalid_archive','trust_denied','capacity','source_unavailable')}}}]
    d['IntakeQuery']=obj(intake_id=ref('Id'),target_authority_service_id=ref('Id'))
    d['IntakeResult']=obj(intake_id=ref('Id'),status=enum('available','unavailable'),receipt=nullable(ref('ArtifactIntakeReceipt')))
    d['IntakeResult']['allOf']=[{'if':{'properties':{'status':constant('available')}},'then':{'properties':{'receipt':ref('ArtifactIntakeReceipt')}},'else':{'properties':{'receipt':{'type':'null'}}}}]
    d['VerifyMaterialization']=obj(intake_id=ref('Id'),target_authority_service_id=ref('Id'),manifest_digest=ref('Digest'),artifact_set_digest=ref('Digest'),
        host_trust_epoch=ref('U20'),challenge_id=ref('Id'),launch_intent_digest=ref('Digest'))
    d['MaterializationResult']=obj(request=ref('VerifyMaterialization'),result=enum('verified','mismatch','unavailable'),
        evidence_id=nullable(ref('Id')),observer_domain=ref('ClockRef'),observed_tick=ref('U20'))
    d['MaterializationResult']['allOf']=[{'if':{'properties':{'result':constant('verified')}},'then':{'properties':{'evidence_id':ref('Id')}},'else':{'properties':{'evidence_id':{'type':'null'}}}}]
    d['Error']=obj(code=enum('invalid_request','unauthorized_peer','identity_conflict','not_found_or_invisible','capacity','unknown_outcome'),
                   operation_id=nullable(ref('Id')))
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'$defs':d,'not':{}}
    payloads={'IMPORT_BEGIN':'ImportBegin','IMPORT_QUERY':'ImportIdentity','IMPORT_CANCEL':'ImportIdentity','IMPORT_STATUS':'ImportStatus',
        'INTAKE_QUERY':'IntakeQuery','INTAKE_RESULT':'IntakeResult','VERIFY_MATERIALIZATION':'VerifyMaterialization','MATERIALIZATION_RESULT':'MaterializationResult','ERROR':'Error'}
    messages=[]
    for name,model in payloads.items():
        messages.append(obj(ipc_version=constant(IPC_VERSION),type=constant(name),channel_id=installation('Id'),
            sequence=installation('U20'),message_id=installation('Id'),reply_to=installation('Id') if name in ('IMPORT_STATUS','INTAKE_RESULT','MATERIALIZATION_RESULT','ERROR') else {'type':'null'},
            payload={'$ref':SID+'#/$defs/'+model}))
    ipc={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':IID,'x-approved':False,'oneOf':messages}
    return {'artifact.schema.json':schema,'ipc.schema.json':ipc}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,value in build().items():
        if a.check: assert (HERE/name).read_bytes()==encoded(value),name
        else: (HERE/name).write_bytes(encoded(value))
    print('扩展包与导入IPC候选生成物一致' if a.check else '已生成扩展包与导入IPC候选')
