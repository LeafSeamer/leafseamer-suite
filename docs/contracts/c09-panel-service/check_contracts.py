"""离线校验新增HTTP契约、静态方法输入结果及局部SQLite事务。"""
import argparse
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate
from referencing import Registry, Resource

from build_contracts import HERE, PANEL, SID, CID, REGISTRY, ROUTES, build, encoded
import check_storage

ROOT = HERE.parents[2]
REPORT = HERE / 'reference-report.json'
INPUTS = [HERE / p for p in ('HTTP_STORAGE.md', 'build_contracts.py', 'check_contracts.py', 'check_storage.py',
                            'service.schema.json', 'service.openapi.json', 'storage-probes.sql', 'storage-cases.json')]
INPUTS += [PANEL / p for p in ('channel-v02.schema.json', 'method-registry-v02.json', 'channel-cases.json',
                             'method-input.schema.json', 'method-cases.json', 'result.schema.json', 'result-cases.json', 'bundle.schema.json')]
INPUTS += [HERE.parent/'df01-source/source/public.schema.json']


def load(path):
    return json.loads(path.read_text('utf-8'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(rfc8785.dumps(value))


def registry_for(schema):
    resources = {SID: Resource.from_contents(schema)}
    for p in [PANEL/n for n in ('channel-v02.schema.json', 'bundle.schema.json', 'method-input.schema.json', 'result.schema.json')]+[INPUTS[-1]]:
        data = load(p)
        resource = Resource.from_contents(data)
        resources[data['$id']] = resource
        if p.name == 'public.schema.json':
            for alias in ('https://leafseamer.invalid/design/df01-source/source/public.schema.json',
                          'https://leafseamer.invalid/contracts/panel-methods/df01-source/source/public.schema.json'):
                resources[alias] = resource
    return Registry().with_resources(resources.items())


def metadata_errors(api):
    errors = []
    expected = {'createPanelSession','getPanelSession','beginPanelHandshake','preparePanelActivation','activatePanelSession',
                'renewPanelSession','invokePanelMethod','getPanelRequest','offerPanelConfirmation','getPanelConfirmation',
                'commitPanelConfirmation','cancelPanelConfirmation','closePanelSession','getPanelSessionOperation'}
    seen = []
    for path, item in api['paths'].items():
        for verb, op in item.items():
            seen.append(op['operationId'])
            security = {'humanBearer': []}
            if verb == 'post': security['sessionCsrf'] = []
            if op.get('security') != [security]: errors.append('security')
            if not any(p['name']=='Origin' and p['in']=='header' and p.get('required') for p in op['parameters']): errors.append('origin')
            if op.get('x-automatic-write-retry') is not False: errors.append('retry')
            if op.get('x-host-only') is not True: errors.append('host')
            if verb == 'get' and 'requestBody' in op: errors.append('get_body')
            for code, response in op['responses'].items():
                if response.get('headers',{}).get('Cache-Control',{}).get('schema',{}).get('const')!='no-store': errors.append('cache')
            if not path.startswith('/api/v1/'): errors.append('path')
    if set(seen) != expected or len(seen) != 14: errors.append('coverage')
    if api.get('x-approved') is not False or api.get('x-runtime-approved') is not False: errors.append('approval')
    return errors


def session_errors(value):
    s = value['session']
    life = value['lifetime']
    errors = []
    if int(life['lease_deadline_tick']) > int(life['hard_deadline_tick']): errors.append('deadline')
    if s['state'] in ('schema_loading', 'active') and s['activation_ref'] is None: errors.append('activation')
    if s['state'] in ('created','handshaking') and s['activation_ref'] is not None: errors.append('premature_activation')
    if s['state'] in ('handshaking','schema_loading','active') and (value['handshake_id'] is None or value['channel_id'] is None): errors.append('handshake')
    if (value['handshake_id'] is None) != (value['channel_id'] is None): errors.append('partial_handshake')
    if s['activation_ref'] and s['activation_ref']['scope_revision'] != s['scope_ref']['revision']: errors.append('scope')
    for key in ('authority_service_id','database_instance_id'):
        if value['delegation_ref'][key] != s[key]: errors.append('delegation')
    return errors


def activation_errors(body, host):
    errors = []
    s = host['session']
    if s['state'] != 'schema_loading': errors.append('state')
    if body['expected_revision'] != s['revision']: errors.append('revision')
    if body['gui_instance_id'] != s['gui_instance_id']: errors.append('gui')
    if body['handshake_id'] != host['handshake_id'] or body['channel_id'] != host['channel_id']: errors.append('channel')
    if body['activation_ref'] != s['activation_ref']: errors.append('activation')
    bundle = s['activation_ref']['bundle_ref']
    if body['ready_manifest_digest'] != (bundle['manifest_digest'] if bundle else None): errors.append('ready')
    return errors


def confirmation_errors(record):
    preview, request = record['preview'], record['request']
    intent = preview['intent']
    errors = []
    if any(intent[k] != request[k] for k in ('identity','method','activation_ref')): errors.append('request_binding')
    if preview['intent_digest'] != digest(intent) or request['intent_digest'] != digest(intent): errors.append('intent_digest')
    fixed = {k:v for k,v in preview.items() if k not in ('preview_digest','state','accepted_result_ref')}
    if preview['preview_digest'] != digest(fixed): errors.append('preview_digest')
    expected = {'offered':'pending_confirmation','consumed':'accepted','cancelled':'cancelled','expired':'rejected','revoked':'rejected'}
    if request['state'] != expected[preview['state']]: errors.append('state')
    if preview['accepted_result_ref'] != request['accepted_result_ref']: errors.append('result')
    if int(preview['deadline_tick']) > int(preview['lease_deadline_at_creation']): errors.append('deadline')
    return errors


def run():
    outputs = build()
    for filename, data in outputs.items():
        assert (HERE/filename).read_bytes() == encoded(data), filename
    schema, api = outputs['service.schema.json'], outputs['service.openapi.json']
    Draft202012Validator.check_schema(schema)
    validate(api)
    assert not metadata_errors(api)
    registry = registry_for(schema)
    results = []

    def case(name, model, instance, expected):
        validator = Draft202012Validator({'$ref': SID+'#/$defs/'+model}, registry=registry, format_checker=FormatChecker())
        actual = validator.is_valid(instance)
        # 同一实例还要通过自包含OpenAPI投影，防止bundler静默改变接受集。
        root = {'components': api['components'], '$ref': '#/components/schemas/Service_'+model}
        projected = Draft202012Validator(root, format_checker=FormatChecker()).is_valid(instance)
        assert actual == projected == expected, (name, actual, projected, expected)
        results.append(dict(id=name, expected_valid=expected, passed=True))

    old = load(PANEL/'channel-cases.json')['fixtures']
    method_inputs = load(PANEL/'method-cases.json')['fixtures']
    method_results = load(PANEL/'result-cases.json')['fixtures']
    activation = dict(activation_id='activation1', registry_ref=load(PANEL/'method-registry-v02.json')['registry_ref'],
                      scope_revision=old['Session']['scope_ref']['revision'], bundle_ref=None)
    session = copy.deepcopy(old['Session'])
    session.update(state='schema_loading', activation_ref=activation)
    host = dict(session=session, lifetime=copy.deepcopy(old['Lifetime']), delegation_ref=old['DelegationRef'],
                handshake_id='handshake1', channel_id='channel1', close_operation_ref=None)
    common = dict(host_operation_id='hostop1', gui_instance_id=session['gui_instance_id'])
    objref = old['Intent']['policy_ref']
    fixtures = {
        'CreateSession': dict(**common, panel_instance_id=session['panel_instance_id'], document_generation='1',
            installation_ref=session['installation_ref'], approval_ref=session['approval_ref'], artifact_digest=session['artifact_digest'],
            mount_ref=objref, requested_scope_ref=session['scope_ref'], configuration_ref=objref),
        'Handshake': dict(**common, expected_revision='1', handshake_id='handshake1', channel_id='channel1'),
        'PrepareActivation': dict(**common, expected_revision='1', handshake_id='handshake1',
                                 expected_registry_ref=activation['registry_ref'], expected_bundle_ref=None),
        'Activate': dict(**common, expected_revision=session['revision'], handshake_id='handshake1', channel_id='channel1',
                         activation_ref=activation, ready_manifest_digest=None),
        'Renew': dict(**common, expected_lease_revision='1', activation_ref=activation),
        'CloseSession': dict(**common, reason_code='user_closed'),
        'HostSession': host,
        'ConfirmationCommit': copy.deepcopy(old['ConfirmationCommit']),
        'ConfirmationCancel': {k: v for k,v in old['ConfirmationCommit'].items() if k!='intent_digest'},
        'LifecycleReceipt': dict(**common, operation='closePanelSession', content_digest='a'*64,
            session_ref=objref, phase='propagating', targets=[dict(target_ref=objref, selector_digest='b'*64,state='pending',evidence_ref=None)]),
        'Error': dict(code='unknown_outcome', correlation_id='correlation1'),
    }
    for m in REGISTRY:
        intent = copy.deepcopy(old['Intent'])
        intent.update(method=m['method'], activation_ref=activation,
                      normalized_arguments=dict(schema_ref=m['input_schema_ref'], value=method_inputs[m['method']]))
        case('invoke:'+m['method'], 'Invocation', {'intent': intent}, True)
        case('confirm_method:'+m['method'], 'ConfirmInvocation', {'intent': intent}, m['mode']=='host_confirm')
        receipt = dict(identity=intent['identity'], intent_digest=digest(intent), method=m['method'], activation_ref=activation,
            state='accepted', reason_code='ok', accepted_result_ref=objref, projection_state='available',
            projection=dict(schema_ref=m['result_schema_ref'], value=method_results[m['result_schema_ref']['definition']]))
        case('receipt:'+m['method'], 'RequestReceipt', receipt, True)
        if m['method']=='controller.acquireControl':
            fixtures['Invocation'] = {'intent': intent}
            fixtures['ConfirmInvocation'] = {'intent': intent}
            pending = copy.deepcopy(receipt)
            pending.update(state='pending_confirmation',reason_code='needs_host_confirmation',accepted_result_ref=None,
                           projection_state='not_applicable',projection=None)
            fixtures['RequestReceipt'] = pending
            preview = copy.deepcopy(old['Preview'])
            preview.update(intent=intent, intent_digest=digest(intent), state='offered', accepted_result_ref=None)
            preview['preview_digest'] = digest({k:v for k,v in preview.items() if k not in ('preview_digest','state','accepted_result_ref')})
            fixtures['ConfirmationRecord'] = dict(preview=preview, request=pending)
    for model, value in fixtures.items():
        case('fixture:'+model, model, value, True)
        invalid = copy.deepcopy(value)
        invalid['unexpected'] = True
        case('extra:'+model, model, invalid, False)
    for name, model, path, value in [
        ('secret_header','CreateSession',['bearer'],'secret'),
        ('origin_input','CreateSession',['panel_origin'],'https://unapproved.invalid'),
        ('counter_number','Renew',['expected_lease_revision'],1),
        ('confirmed_flag','ConfirmationCommit',['confirmed'],True),
        ('accepted_without_reference','RequestReceipt',['state'],'accepted'),
        ('unknown_not_terminal','RequestReceipt',['state'],'unknown'),
        ('preview_direct_frame','Invocation',['intent','normalized_arguments','value','confirmed'],True),
        ('schema_digest','Invocation',['intent','normalized_arguments','schema_ref','schema_digest'],'0'*64),
        ('ack_without_evidence','LifecycleReceipt',['targets',0,'state'],'acknowledged'),
    ]:
        sample = copy.deepcopy(fixtures[model]); target=sample
        for segment in path[:-1]: target=target[segment]
        target[path[-1]]=value
        case(name, model, sample, False)
    # 合法静态结构仍可能承载错误权威关联；单独检查，不宣称Schema证明权限。
    semantic = []
    def semantic_case(name, function, value, expected):
        actual = not function(value)
        assert actual == expected, (name, actual)
        semantic.append(dict(id=name, expected_valid=expected, passed=True))
    semantic_case('host_valid', session_errors, host, True)
    for name, mutation in [('missing_activation',lambda x:x['session'].update(activation_ref=None)),
                           ('wrong_delegation',lambda x:x['delegation_ref'].update(database_instance_id='other')),
                           ('lease_after_hard',lambda x:x['lifetime'].update(lease_deadline_tick=str(int(x['lifetime']['hard_deadline_tick'])+1)))]:
        value=copy.deepcopy(host); mutation(value); semantic_case(name,session_errors,value,False)
    semantic_case('activate_static',lambda x:activation_errors(x,host),fixtures['Activate'],True)
    for key, value in [('handshake_id','other'),('channel_id','other'),('gui_instance_id','other'),
                       ('expected_revision','999'),('ready_manifest_digest','f'*64)]:
        body=copy.deepcopy(fixtures['Activate']);body[key]=value
        semantic_case('activation_'+key,lambda x:activation_errors(x,host),body,False)
    bundled=copy.deepcopy(host)
    bundled['session']['activation_ref']['bundle_ref']={'bundle_id':'bundle1','manifest_digest':'f'*64}
    body=copy.deepcopy(fixtures['Activate']);body.update(activation_ref=bundled['session']['activation_ref'],ready_manifest_digest='f'*64)
    semantic_case('activate_bundle',lambda x:activation_errors(x,bundled),body,True)
    semantic_case('confirmation_valid',confirmation_errors,fixtures['ConfirmationRecord'],True)
    for key, value in [('method','controller.getMeta'), ('intent_digest','f'*64), ('state','accepted')]:
        altered=copy.deepcopy(fixtures['ConfirmationRecord']);altered['request'][key]=value
        semantic_case('confirmation_'+key,confirmation_errors,altered,False)
    changed=copy.deepcopy(fixtures['ConfirmationRecord'])
    changed['preview']['intent']['identity']['database_instance_id']='other'
    changed['preview']['intent_digest']=digest(changed['preview']['intent'])
    changed['preview']['preview_digest']=digest({k:v for k,v in changed['preview'].items() if k not in ('preview_digest','state','accepted_result_ref')})
    semantic_case('rehashed_wrong_identity',confirmation_errors,changed,False)
    # 接受事实保留而展示暂不可用，是合法正例；不可用不等于未受理。
    unavailable=copy.deepcopy(receipt);unavailable.update(projection_state='unavailable',projection=None)
    case('accepted_projection_unavailable','RequestReceipt',unavailable,True)
    early_close=copy.deepcopy(host)
    early_close['session'].update(state='closing',activation_ref=None)
    early_close.update(handshake_id=None,channel_id=None)
    semantic_case('close_before_handshake',session_errors,early_close,True)
    # 元数据的正反例独立于生成器，不改变所需接口范围。
    metadata=[]
    for kind in ('csrf_or','cache','retry','origin','missing','approve'):
        changed=copy.deepcopy(api);op=changed['paths']['/api/v1/panel-sessions']['post']
        if kind=='csrf_or':op['security']=[{'humanBearer':[]},{'sessionCsrf':[]}]
        if kind=='cache':op['responses']['201']['headers']={}
        if kind=='retry':op['x-automatic-write-retry']=True
        if kind=='origin':op['parameters']=[]
        if kind=='missing':del changed['paths']['/api/v1/panel-confirmations/{preview_id}/cancel']
        if kind=='approve':changed['x-approved']=True
        assert metadata_errors(changed), kind
        metadata.append(dict(id=kind,passed=True))
    sql = check_storage.run(load(HERE/'storage-cases.json')['cases'])
    return dict(approved=False,runtime_approved=False,all_passed=True,route_count=14,
                checks={'schema_and_openapi_projection':results,'synthetic_associations':semantic,'metadata_mutations':metadata,'sqlite_probes':sql},
                versions={'python':sys.version.split()[0],'sqlite':sqlite3.sqlite_version},
                limits=['动态Schema及实际权限提供者未执行','SQL仅内存固定夹具；无真实并发、杀进程或WAL耐久验证'],
                runtime_validation={'browser':0,'authentication_provider':0,'product_services':0,'device':0,'disk_crash':0})


def bindings(staged=False):
    def read(path):
        relative=path.relative_to(ROOT).as_posix()
        return subprocess.check_output(['git','show',':'+relative],cwd=ROOT) if staged else path.read_bytes()
    report=json.loads(read(REPORT))
    expected={p.relative_to(ROOT).as_posix() for p in INPUTS}
    assert set(report['input_sha256'])==expected
    for path in INPUTS:
        assert report['input_sha256'][path.relative_to(ROOT).as_posix()]==sha(read(path)),path
    print('报告17份输入字节一致；未重跑用例')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',action='store_true')
    parser.add_argument('--check-report',action='store_true')
    parser.add_argument('--staged',action='store_true')
    args=parser.parse_args()
    if args.check_report:
        bindings(args.staged)
    else:
        assert not args.staged
        report=run()
        report['input_sha256']={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in INPUTS}
        if args.report: REPORT.write_bytes(encoded(report))
        print(json.dumps({k:len(v) for k,v in report['checks'].items()},ensure_ascii=False))
