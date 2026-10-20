"""安装管理候选格式唯一源；仅生成设计资料，不实现安装服务。"""
import argparse
import copy
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = 'extension-installation/0.1.0-draft.1'
SID = 'https://leafseamer.invalid/design/c09-installation/installation.schema.json'
KINDS = ['device_module', 'data_source', 'panel', 'nodecg_bridge']
PHASES = ['accepted', 'verifying', 'awaiting_approval', 'closing', 'awaiting_retirement',
          'reconciling', 'launching_closed', 'completed', 'rejected', 'failed_closed', 'indeterminate']
STATES = ['staged', 'verified', 'approved', 'installed_disabled', 'activating', 'active',
          'revoking', 'disabled', 'rejected', 'removed']
ROUTES = [
    ('post', '/extension-slots', 'createExtensionSlot', 'CreateSlot', 'SlotView', [201, 200]),
    ('post', '/extensions/stage', 'stageExtension', 'Stage', 'OperationView', [202, 200]),
    ('post', '/extensions/{installation_id}/review', 'reviewExtensionPermissions', 'Review', 'PermissionReview', [200]),
    ('post', '/extensions/{installation_id}/approve', 'approveExtension', 'Approve', 'OperationView', [202, 200]),
    ('post', '/extension-slots/{slot_id}/activate', 'activateExtension', 'Activate', 'OperationView', [202, 200]),
    ('post', '/extension-slots/{slot_id}/enable', 'enableExtension', 'Enable', 'OperationView', [202, 200]),
    ('post', '/extension-slots/{slot_id}/disable', 'disableExtension', 'Disable', 'OperationView', [202, 200]),
    ('post', '/extension-slots/{slot_id}/upgrade', 'upgradeExtension', 'Upgrade', 'OperationView', [202, 200]),
    ('post', '/extension-slots/{slot_id}/uninstall', 'uninstallExtension', 'Uninstall', 'OperationView', [202, 200]),
    ('post', '/extension-slots/{slot_id}/plan', 'planExtensionChange', 'PlanRequest', 'DependencyPlan', [200]),
    ('post', '/extension-operations/lookup', 'lookupExtensionRequest', 'LookupRequest', 'LookupResult', [200]),
    ('get', '/extension-slots/{slot_id}', 'getExtensionSlot', None, 'SlotView', [200]),
    ('get', '/extensions/{installation_id}', 'getExtensionInstallation', None, 'InstanceView', [200]),
    ('get', '/extension-operations/{operation_id}', 'getExtensionOperation', None, 'OperationView', [200]),
]


def ref(name): return {'$ref': '#/$defs/' + name}
def enum(*values): return {'enum': list(values)}
def obj(**fields): return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)
def null(value): return {'anyOf': [value, {'type': 'null'}]}
def arr(value, maximum=128, minimum=0): return dict(type='array', items=value, maxItems=maximum, minItems=minimum, uniqueItems=True)
def text(maximum=160): return dict(type='string', minLength=1, maxLength=maximum)
def const(value): return {'const': value}
def when(field, values, constraints):
    return {'if': {'properties': {field: enum(*values)}, 'required': [field]}, 'then': constraints}


def schema():
    d = {
        'Id': dict(type='string', minLength=1, maxLength=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*(?![\s\S])'),
        'U20': dict(type='string', maxLength=20, pattern=r'^(0|[1-9][0-9]*)(?![\s\S])'),
        'Digest': dict(type='string', pattern=r'^sha256:[0-9a-f]{64}(?![\s\S])'),
    }
    kinds = ['slot', 'installation', 'approval', 'review', 'configuration', 'content', 'dependency_plan',
             'installation_operation', 'intake', 'platform_profile', 'validation_policy', 'release_authorization',
             'verification', 'runtime_binding', 'deny_record', 'close_batch', 'retirement', 'reconciliation',
             'device', 'source', 'panel_session', 'definition', 'run', 'schedule', 'resource', 'command',
             'protocol_profile', 'filesystem_role', 'helper_artifact', 'secret_role', 'data_object', 'blocker_snapshot']
    for kind in kinds:
        name = ''.join(p.title() for p in kind.split('_')) + 'Ref'
        d[name] = obj(kind=const(kind), authority_service_id=ref('Id'), database_instance_id=ref('Id'),
                      object_id=ref('Id'), revision=ref('U20'), digest=ref('Digest'))
    d['Context'] = obj(**{k: ref('U20' if k == 'identity_epoch' else 'Id') for k in
        ['authority_service_id', 'database_instance_id', 'identity_issuer_id', 'identity_epoch',
         'auth_session_id', 'gui_instance_id', 'host_operation_id']})
    d['ClockRef'] = obj(clock_domain_id=ref('Id'), descriptor_digest=ref('Digest'))
    d['Lifetime'] = obj(clock=ref('ClockRef'), issued_tick=ref('U20'), deadline_tick=ref('U20'))
    permissions = {
        'device_scope': obj(devices=arr(ref('DeviceRef'), 64, 1), action_ids=arr(ref('Id'), 128), trigger_ids=arr(ref('Id'), 128)),
        'data_scope': obj(objects=arr(ref('DataObjectRef'), 128, 1), access=enum('read', 'propose')),
        'network_endpoint': obj(transport=enum('tcp', 'udp', 'https', 'wss'), host=text(253),
                                port=dict(type='integer', minimum=1, maximum=65535), profile_ref=ref('ProtocolProfileRef')),
        'secret_role': obj(role_ref=ref('SecretRoleRef'), devices=arr(ref('DeviceRef'), 64), sources=arr(ref('SourceRef'), 64)),
        'filesystem_root_role': obj(role_ref=ref('FilesystemRoleRef'), access=enum('read', 'cache_write'), quota_bytes=ref('U20')),
        'helper_artifact': obj(artifact_ref=ref('HelperArtifactRef'), launch_profile_ref=ref('ValidationPolicyRef')),
        'panel_method': obj(authority=enum('controller', 'seamer'), method_ids=arr(ref('Id'), 35, 1),
                            object_refs=arr({'oneOf': [ref('DeviceRef'), ref('DataObjectRef'), ref('RunRef')]}, 128, 1)),
        'protocol_io': obj(profile_ref=ref('ProtocolProfileRef'), endpoint_request_id=ref('Id'),
                          frame_classes=arr(enum('authentication', 'query', 'subscription', 'keepalive', 'ack', 'control'), 6, 1)),
    }
    for kind, scope in permissions.items():
        d['Permission_' + kind] = obj(request_id=ref('Id'), kind=const(kind), purpose=text(), scope=scope)
    d['Permission'] = {'oneOf': [ref('Permission_' + kind) for kind in permissions]}
    d['PermissionReview'] = obj(review_ref=ref('ReviewRef'), installation_ref=ref('InstallationRef'),
        manifest_digest=ref('Digest'), artifact_set_digest=ref('Digest'), configuration_ref=ref('ConfigurationRef'),
        requested_permissions=arr(ref('Permission')), proposed_permissions=arr(ref('Permission')),
        policy_ref=ref('ValidationPolicyRef'), content_digest=ref('Digest'))
    d['Approval'] = obj(approval_ref=ref('ApprovalRef'), installation_ref=ref('InstallationRef'),
        review_ref=ref('ReviewRef'), approved_permission_ids=arr(ref('Id')), configuration_ref=ref('ConfigurationRef'),
        manifest_digest=ref('Digest'), artifact_set_digest=ref('Digest'), platform_profile_ref=ref('PlatformProfileRef'),
        approval_operation_ref=ref('InstallationOperationRef'), revoked_by= null(ref('DenyRecordRef')))
    d['ArtifactIntakeReceipt'] = obj(host_installation_id=ref('Id'), host_trust_epoch=ref('U20'),
        import_operation_id=ref('Id'), intake_id=ref('Id'), target_authority_service_id=ref('Id'),
        manifest_digest=ref('Digest'), artifact_set_digest=ref('Digest'), package_bytes=ref('U20'),
        file_inventory_digest=ref('Digest'), dependency_lock_digest=ref('Digest'), platform_profile_ref=ref('PlatformProfileRef'),
        validation_policy_ref=ref('ValidationPolicyRef'), release_authorization_ref=ref('ReleaseAuthorizationRef'),
        verification_record_ref=ref('VerificationRef'))
    d['PlanSelection'] = obj(kind=enum('activate', 'enable', 'upgrade', 'uninstall'),
        source_installation_ref=null(ref('InstallationRef')), target_installation_ref=null(ref('InstallationRef')),
        reuse_content_ref=null(ref('ContentRef')), configuration_ref=ref('ConfigurationRef'))
    d['PlanSelection']['allOf'] = [when('kind', [kind], {'properties': {
        'source_installation_ref': ref('InstallationRef') if kind=='upgrade' else null(ref('InstallationRef')) if kind=='uninstall' else {'type':'null'},
        'target_installation_ref': ref('InstallationRef') if kind in ('activate','upgrade') else {'type':'null'},
        'reuse_content_ref': ref('ContentRef') if kind=='enable' else {'type':'null'},
    }}) for kind in ('activate','enable','upgrade','uninstall')]
    impacts = ['Device', 'Source', 'PanelSession', 'Definition', 'Run', 'Schedule', 'Resource', 'Command']
    d['Impact'] = obj(object_ref={'oneOf': [ref(k+'Ref') for k in impacts]},
        consequence=enum('close', 'pause', 'reconcile', 'preserve_history'), reason_code=enum('installation_dependency', 'unresolved_effect', 'active_runtime'))
    d['DependencyPlan'] = obj(plan_ref=ref('DependencyPlanRef'), slot_ref=ref('SlotRef'), dependency_revision=ref('U20'),
        selection=ref('PlanSelection'), configuration_digest=ref('Digest'), impacts=arr(ref('Impact'), 4096),
        platform_profile_ref=ref('PlatformProfileRef'), policy_ref=ref('ValidationPolicyRef'), lifetime=ref('Lifetime'), content_digest=ref('Digest'))
    d['SlotView'] = obj(slot_ref=ref('SlotRef'), extension_id=ref('Id'), kind=enum(*KINDS), display_name=text(),
        desired_state=enum('enabled', 'disabled', 'removed'), current_installation_ref=null(ref('InstallationRef')),
        pending_operation_ref=null(ref('InstallationOperationRef')), configuration_ref=null(ref('ConfigurationRef')), dependency_revision=ref('U20'))
    d['InstanceView'] = obj(installation_ref=ref('InstallationRef'), slot_ref=ref('SlotRef'), state=enum(*STATES),
        manifest_digest=ref('Digest'), artifact_set_digest=ref('Digest'), intake_ref=ref('IntakeRef'),
        approval_ref=null(ref('ApprovalRef')), review_ref=null(ref('ReviewRef')), deny_record_ref=null(ref('DenyRecordRef')),
        predecessor_ref=null(ref('InstallationRef')), runtime_binding_refs=arr(ref('RuntimeBindingRef'), 64))
    d['InstanceView']['allOf'] = [when('state',['revoking','disabled'], {'properties': {'deny_record_ref':ref('DenyRecordRef')}}),
        when('state',['approved','installed_disabled','activating','active'], {'properties':{'approval_ref':ref('ApprovalRef')}})]
    d['Blocker'] = obj(blocker_id=ref('Id'), code=enum('pending_exit', 'unknown_effect', 'runtime_not_retired', 'authorization_revoked',
        'artifact_unavailable', 'storage_unknown', 'capacity_protection'), object_ref={'oneOf':[ref(n+'Ref') for n in impacts]+[ref('InstallationRef')]})
    d['BlockerPage'] = obj(snapshot_ref=ref('BlockerSnapshotRef'), total=ref('U20'), offset=ref('U20'),
        items=arr(ref('Blocker'), 64), has_more=dict(type='boolean'), next_cursor=null(text(256)))
    d['BlockerPage']['allOf'] = [when('has_more',[True], {'properties':{'next_cursor':text(256),'items':{'minItems':1}}}),
                               when('has_more',[False], {'properties':{'next_cursor':{'type':'null'}}})]
    operation_kinds = ['stage','approve','activate','enable','disable','upgrade','uninstall']
    d['OperationView'] = obj(operation_ref=ref('InstallationOperationRef'), identity=ref('Context'), intent_digest=ref('Digest'),
        kind=enum(*operation_kinds), slot_ref=ref('SlotRef'), source_installation_ref=null(ref('InstallationRef')),
        target_installation_ref=null(ref('InstallationRef')), phase=enum(*PHASES),
        dependency_plan_ref=null(ref('DependencyPlanRef')), close_batch_refs=arr(ref('CloseBatchRef'), 256),
        retirement_refs=arr(ref('RetirementRef'), 256), reconciliation_refs=arr(ref('ReconciliationRef'), 256),
        result=null(enum('verified', 'approved', 'active_closed', 'disabled', 'removed', 'no_change')),
        blockers=ref('BlockerPage'), runtime_readiness=enum('not_applicable','closed','reconciliation_required','ready_for_manual'))
    d['OperationView']['allOf'] = [when('phase',['completed'], {'properties':{'result':{'type':'string'}}}),
        when('phase',[p for p in PHASES if p!='completed'], {'properties':{'result':{'type':'null'}}})]
    def request(name, **fields): d[name]=obj(context=ref('Context'), **fields)
    request('CreateSlot', extension_id=ref('Id'), kind=enum(*KINDS), display_name=text())
    request('Stage', slot_ref=ref('SlotRef'), intake_ref=ref('IntakeRef'))
    request('Review', expected_installation_revision=ref('U20'), proposed_permissions=arr(ref('Permission')), configuration_ref=ref('ConfigurationRef'))
    request('Approve', expected_installation_revision=ref('U20'), permission_review_ref=ref('ReviewRef'),
            approved_permission_ids=arr(ref('Id')), configuration_ref=ref('ConfigurationRef'))
    fields = dict(expected_slot_revision=ref('U20'))
    request('Activate', **fields, target_installation_ref=ref('InstallationRef'), approval_ref=ref('ApprovalRef'), dependency_plan_ref=ref('DependencyPlanRef'))
    request('Enable', **fields, reuse_content_ref=ref('ContentRef'), permission_review_ref=ref('ReviewRef'), configuration_ref=ref('ConfigurationRef'), dependency_plan_ref=ref('DependencyPlanRef'))
    reason=enum('operator_request','maintenance','security_response')
    request('Disable', **fields, source_installation_ref=ref('InstallationRef'), reason=reason)
    request('Upgrade', **fields, source_installation_ref=ref('InstallationRef'), target_installation_ref=ref('InstallationRef'), approval_ref=ref('ApprovalRef'), dependency_plan_ref=ref('DependencyPlanRef'))
    request('Uninstall', **fields, source_installation_ref=null(ref('InstallationRef')), dependency_plan_ref=ref('DependencyPlanRef'), reason=reason)
    request('PlanRequest', **fields, selection=ref('PlanSelection'))
    d['LookupRequest']=obj(identity=ref('Context'))
    outputs=['SlotView','OperationView','DependencyPlan','PermissionReview']
    d['LookupResult']= {'oneOf':[obj(identity=ref('Context'), intent_digest=ref('Digest'),
        result_kind=const(k), original_result=ref(k)) for k in outputs]}
    d['Error']=obj(code=enum('invalid_request','authentication_required','authority_denied','not_found_or_invisible',
        'conflict','payload_too_large','unsupported_candidate','capacity_exceeded','source_unavailable','unknown_outcome'),
        correlation_id=ref('Id'), operation_ref=null(ref('InstallationOperationRef')))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,
        'title':'安装管理候选：须选择具体defs校验', 'x-approved':False, '$defs':d, 'not':{}}


def encoded(value): return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def build():
    doc=schema()
    def project(v):
        if isinstance(v,list): return [project(x) for x in v]
        if not isinstance(v,dict): return v
        return {k: v2.replace('#/$defs/','#/components/schemas/') if k=='$ref' else
                copy.deepcopy(v2) if k in ('const','enum','default','examples') else project(v2) for k,v2 in v.items()}
    paths={}
    codes={400:['invalid_request'],401:['authentication_required'],403:['authority_denied'],404:['not_found_or_invisible'],
        409:['conflict'],413:['payload_too_large'],422:['unsupported_candidate'],429:['capacity_exceeded'],
        503:['source_unavailable','unknown_outcome']}
    for verb,path,operation,request,response,success in ROUTES:
        parameters=[dict(name='Origin',**{'in':'header'},required=True,schema=text(512))]
        parameters += [dict(name=p,**{'in':'path'},required=True,schema=project(ref('Id'))) for p in re.findall(r'\{([^}]+)\}',path)]
        if verb=='get': parameters.append(dict(name='gui_instance_id',**{'in':'query'},required=True,schema=project(ref('Id'))))
        if operation=='getExtensionOperation': parameters.append(dict(name='blockers_cursor',**{'in':'query'},required=False,schema=text(256)))
        responses={}
        for code in success+list(codes):
            s=project(ref(response)) if code in success else {'allOf':[project(ref('Error')),{'properties':{'code':enum(*codes[code])}}]}
            responses[str(code)]={'description':'可靠受理或当前授权投影；不证明设备效果',
                'headers':{'Cache-Control':{'required':True,'schema':{'type':'string','const':'no-store'}}},
                'content':{'application/json':{'schema':s}}}
        security={'humanBearer':[]}
        if verb=='post': security['sessionCsrf']=[]
        op=dict(operationId=operation,parameters=parameters,responses=responses,security=[security])
        op.update({'x-host-only':True,'x-automatic-write-retry':False,'x-authorities':['controller','seamer'],
                   'x-permission':'extension.read' if verb=='get' or request=='LookupRequest' else 'extension.manage'})
        if request: op['requestBody']={'required':True,'content':{'application/json':{'schema':project(ref(request))}}}
        paths.setdefault('/api/v1'+path,{})[verb]=op
    api={'openapi':'3.1.1','info':{'title':'LeafSeamer 扩展安装管理候选','version':VERSION},
         'x-approved':False,'x-runtime-approved':False,'paths':paths,
         'components':{'schemas':project(doc['$defs']),'securitySchemes':{'humanBearer':{'type':'http','scheme':'bearer'},
              'sessionCsrf':{'type':'apiKey','in':'header','name':'X-CSRF-Token'}}}}
    return {'installation.schema.json':doc,'installation.openapi.json':api}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,value in build().items():
        if a.check: assert (HERE/name).read_bytes()==encoded(value),name
        else: (HERE/name).write_bytes(encoded(value))
    print('安装候选生成物一致' if a.check else '已生成安装候选Schema和OpenAPI')
