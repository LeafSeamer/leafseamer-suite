"""生成安装0.2候选；保留0.1原字节，显式归并角色解析及扩展启动绑定。"""
import argparse
import copy
import json
from pathlib import Path
import build_contracts as old

HERE=Path(__file__).resolve().parent
SID='https://leafseamer.invalid/design/c09-installation/installation-v02.schema.json'
VERSION='extension-installation/0.2.0-draft.1'
ref,obj,arr,null,const,enum,text=old.ref,old.obj,old.arr,old.null,old.const,old.enum,old.text
encoded=old.encoded


def add(model,**fields):
    model['properties'].update(fields);model['required']+=list(fields)


def build():
    base=old.build();schema=copy.deepcopy(base['installation.schema.json']);d=schema['$defs'];schema['$id']=SID
    artifact=json.loads((HERE.parent/'c09-artifact-import/artifact.schema.json').read_bytes())
    # 仅收集固定两个资源的具名闭包，实例const/enum不递归改写。
    def inline(v):
        if isinstance(v,list): return [inline(x) for x in v]
        if not isinstance(v,dict): return v
        out={}
        for k,x in v.items():
            if k=='$ref':
                resource,name=x.split('#/$defs/')
                if resource==old.SID: out[k]='#/$defs/'+name
                else:
                    assert resource in ('',artifact['$id']),x
                    target='Artifact_'+name;out[k]='#/$defs/'+target
                    if target not in d:
                        d[target]={};d[target]=inline(artifact['$defs'][name])
            else: out[k]=copy.deepcopy(x) if k in ('const','enum','default','examples') else inline(x)
        return out
    d['RoleResolution']=inline(artifact['$defs']['RoleResolution'])
    d['RoleBinding']=inline(artifact['$defs']['RoleBinding'])
    for kind in ('role_resolution','launch_authorization'):
        name=''.join(p.title() for p in kind.split('_'))+'Ref'
        d[name]=copy.deepcopy(d['ReviewRef']);d[name]['properties']['kind']=const(kind)
    d['ResolutionView']=obj(resolution_ref=ref('RoleResolutionRef'),record=ref('RoleResolution'))
    d['ResolveRoles']=obj(context=ref('Context'),expected_installation_revision=ref('U20'),configuration_ref=ref('ConfigurationRef'),bindings=arr(ref('RoleBinding')))
    add(d['PermissionReview'],role_resolution_ref=ref('RoleResolutionRef'))
    add(d['Review'],role_resolution_ref=ref('RoleResolutionRef'))
    add(d['Approval'],role_resolution_ref=ref('RoleResolutionRef'),permissions_digest=ref('Digest'))
    add(d['InstanceView'],role_resolution_ref=null(ref('RoleResolutionRef')))
    d['StageSource']={'oneOf':[obj(kind=const('intake'),intake_ref=ref('IntakeRef')),obj(kind=const('retained'),content_ref=ref('ContentRef'))]}
    d['Stage']=obj(context=ref('Context'),slot_ref=ref('SlotRef'),expected_slot_revision=ref('U20'),source=ref('StageSource'))
    d['Enable']=copy.deepcopy(d['Activate'])
    # 新实例先stage；enable计划与activate一样选择已批准的新target，不在执行中偷偷分配。
    d['PlanSelection']['allOf']=[old.when('kind',[k],{'properties':{
        'source_installation_ref':ref('InstallationRef') if k=='upgrade' else null(ref('InstallationRef')) if k=='uninstall' else {'type':'null'},
        'target_installation_ref':ref('InstallationRef') if k in ('activate','enable','upgrade') else {'type':'null'},
        'reuse_content_ref':{'type':'null'}}}) for k in ('activate','enable','upgrade','uninstall')]
    d['LookupResult']['oneOf'].append(obj(identity=ref('Context'),intent_digest=ref('Digest'),result_kind=const('ResolutionView'),original_result=ref('ResolutionView')))
    d['RuntimeManifestRef']=obj(manifest_id=ref('Id'),revision=ref('U20'),digest=ref('Digest'))
    d['ContainmentRef']=obj(group_id=ref('Id'),generation=ref('Id'),backend=enum('windows_job','linux_cgroup_v2','container_runtime'))
    d['ExtensionLaunchBinding']=obj(installation_ref=ref('InstallationRef'),approval_ref=ref('ApprovalRef'),review_ref=ref('ReviewRef'),role_resolution_ref=ref('RoleResolutionRef'),
        configuration_ref=ref('ConfigurationRef'),intake_ref=ref('IntakeRef'),platform_profile_ref=ref('PlatformProfileRef'),host_installation_id=ref('Id'),host_trust_epoch=ref('U20'),
        manifest_digest=ref('Digest'),artifact_set_digest=ref('Digest'),entry_id=ref('Id'),permissions_digest=ref('Digest'))
    d['ExtensionLaunchIntent']=obj(launch_id=ref('Id'),service_id=ref('Id'),supervisor_instance_id=ref('Id'),runtime_generation=ref('Id'),member_id=ref('Id'),role=const('worker'),
        artifact_manifest_ref=ref('RuntimeManifestRef'),containment_ref=ref('ContainmentRef'),device_ids=arr(ref('Id'),64),policy_revision=ref('U20'),extension_binding=ref('ExtensionLaunchBinding'))
    d['LaunchAuthorization']=obj(authorization_ref=ref('LaunchAuthorizationRef'),launch_id=ref('Id'),launch_intent_digest=ref('Digest'),installation_ref=ref('InstallationRef'),
        approval_ref=ref('ApprovalRef'),role_resolution_ref=ref('RoleResolutionRef'),permissions_digest=ref('Digest'),supervisor_instance_id=ref('Id'),fence_revision=ref('U20'),lifetime=ref('Lifetime'))
    d['LaunchRecord']=obj(launch_id=ref('Id'),launch_intent_digest=ref('Digest'),supervisor_instance_id=ref('Id'),
        state=enum('registered','creating','awaiting_bootstrap','admitted_closed','retiring','retired','rejected','indeterminate'),creation_attempted=dict(type='boolean'),
        runtime_binding_ref=null(ref('RuntimeBindingRef')),retirement_ref=null(ref('RetirementRef')),gate_state=const('closed'))
    api=copy.deepcopy(base['installation.openapi.json']);api['info']['version']=VERSION
    path='/api/v1/extensions/{installation_id}/resolve'
    operation=copy.deepcopy(api['paths']['/api/v1/extensions/{installation_id}/review']['post'])
    operation['operationId']='resolveExtensionRoles'
    operation['requestBody']['content']['application/json']['schema']={'$ref':'#/components/schemas/ResolveRoles'}
    operation['responses']['200']['content']['application/json']['schema']={'$ref':'#/components/schemas/ResolutionView'}
    api['paths'][path]={'post':operation}
    def project(v):
        if isinstance(v,list): return [project(x) for x in v]
        if not isinstance(v,dict): return v
        return {k:x.replace('#/$defs/','#/components/schemas/') if k=='$ref' else copy.deepcopy(x) if k in ('const','enum','default','examples') else project(x) for k,x in v.items()}
    # 运行域对象仅为内部候选，不向管理HTTP发布整个内部模型表。
    internal={'ExtensionLaunchIntent','ExtensionLaunchBinding','LaunchAuthorization','LaunchAuthorizationRef','LaunchRecord','RuntimeManifestRef','ContainmentRef'}
    api['components']['schemas']=project({k:v for k,v in d.items() if k not in internal})
    for route in api['paths'].values():
        for op in route.values(): op['parameters'].append(dict(name='X-LeafSeamer-Contract',**{'in':'header'},required=True,schema=const(VERSION)))
    return {'installation-v02.schema.json':schema,'installation-v02.openapi.json':api}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,value in build().items():
        if a.check: assert (HERE/name).read_bytes()==encoded(value),name
        else: (HERE/name).write_bytes(encoded(value))
    print('安装0.2生成物一致' if a.check else '已生成安装0.2候选')
