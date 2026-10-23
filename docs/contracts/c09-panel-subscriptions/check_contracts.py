"""候选结构、OpenAPI投影和合成订阅关联检查；无网络或产品运行。"""
import argparse
import copy
import hashlib
import json
import subprocess
import sys

import rfc8785
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from referencing import Registry, Resource

from build_contracts import HERE, PANEL, SID, CID, VERSION, METHODS, SUBSCRIBABLE, PREFIX, ROUTES, build, encoded, resources_for

ROOT = HERE.parents[2]
REPORT = HERE / 'reference-report.json'
INPUTS = [HERE / p for p in ('HTTP_SUBSCRIPTIONS.md', 'build_contracts.py', 'check_contracts.py',
                            'subscriptions.schema.json', 'subscriptions.openapi.json')]
INPUTS += [PANEL / p for p in ('channel-v02.schema.json', 'method-registry-v02.json', 'channel-v02-cases.json',
                             'method-input.schema.json', 'method-cases.json', 'result.schema.json', 'result-cases.json', 'bundle.schema.json')]
INPUTS += [HERE.parent / 'df01-source/source/public.schema.json', HERE.parent / 'c09-panel-storage/README.md']
MAPPING = {m['method']: m for m in SUBSCRIBABLE}


def load(path):
    return json.loads(path.read_text('utf-8'))


def digest(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def reference(kind, entity):
    return dict(authority_service_id='authority.1', database_instance_id='database.1', entity_kind=kind,
                entity_id=entity, entity_epoch='epoch.1', revision='1', content_digest='a' * 64)


def fixtures(method='controller.getControl'):
    channel_cases = load(PANEL / 'channel-v02-cases.json')
    ctx = channel_cases['context']
    identity = dict(authority_service_id='authority.1', database_instance_id='database.1', issuer_id='issuer.1',
                    issuer_epoch='issuer-epoch.1', auth_session_id='auth.1', panel_session_id='session.1',
                    document_generation='1', subscription_id='sub.1')
    m = MAPPING[method]
    intent = dict(identity=identity, activation_ref=ctx['activation_ref'], method=method, target_handle='target.1', resource_ref=None,
                  arguments=dict(schema_ref=m['input_schema_ref'], value=load(PANEL / 'method-cases.json')['fixtures'][method]))
    delegation = dict(authority_service_id='authority.1', database_instance_id='database.1', delegation_id='delegation.1', revision='1')
    create = dict(gui_instance_id='gui.1', delegation_ref=delegation, intent=intent)
    record = dict(identity=identity, intent_digest=digest(intent), activation_ref=ctx['activation_ref'], method=method,
                  mode=m['subscription_mode'], state='live' if m['subscription_mode'] == 'projection' else 'invalidated',
                  revision='1', published_sequence='1', acknowledged_sequence='0', last_ack=None, close_operation_ref=None)
    envelope = dict(protocol_version=VERSION, identity=identity, activation_ref=ctx['activation_ref'],
                    projection_exit_ref=reference('panel_projection_exit', 'exit.1'), source_projection_ref=reference('filtered_projection', 'source.1'),
                    projection_sequence='1', method=method, kind='baseline' if m['subscription_mode'] == 'projection' else 'invalidated',
                    reason_code='ok', value=None)
    if m['subscription_mode'] == 'projection':
        envelope['value'] = dict(schema_ref=m['result_schema_ref'], value=load(PANEL / 'result-cases.json')['fixtures'][m['result_schema_ref']['definition']])
    stored = dict(envelope=envelope, envelope_digest=digest(envelope))
    frame = copy.deepcopy(channel_cases['frames']['baseline'])
    frame.update({key: envelope[key] for key in ('activation_ref', 'method', 'projection_sequence', 'kind', 'reason_code', 'value')})
    ack = copy.deepcopy(channel_cases['frames']['projection-ack'])
    ack['projection_digest'] = digest(frame)
    request = dict(gui_instance_id='gui.1', delegation_ref=delegation, identity=identity,
                   envelope_digest=stored['envelope_digest'], frame=frame, panel_ack=ack)
    context = dict(active=True, authorized=True, approval_active=True, lease_valid=True, host_authenticated=True,
                   gui_instance_id='gui.1', delegation_ref=delegation, public_binding=ctx['public_binding'],
                   owner_identity={k: v for k, v in identity.items() if k != 'subscription_id'},
                   activation_ref=ctx['activation_ref'], service_family=method.split('.')[0],
                   target_handle='target.1', resource_ref=None, allowed_methods=[method])
    batch = dict(identity=identity, activation_ref=ctx['activation_ref'], after_sequence='0', published_sequence='1', has_more=False, frames=[stored])
    # 经JSON往返消除生成时的共享引用，待测消息不能同时改写权威快照。
    return json.loads(json.dumps(dict(create=create, record=record, store={'1': stored}, ack=request,
                                     batch=batch, context=context)))


def allowed(context):
    return all(context[k] for k in ('active', 'authorized', 'approval_active', 'lease_valid', 'host_authenticated'))


def credentials(request, context):
    return request['gui_instance_id'] == context['gui_instance_id'] and request['delegation_ref'] == context['delegation_ref']


def owner_bound(identity, context):
    return {k: v for k, v in identity.items() if k != 'subscription_id'} == context['owner_identity']


def current_binding(record, context):
    return (owner_bound(record['identity'], context) and record['activation_ref'] == context['activation_ref']
            and record['method'] in context['allowed_methods'] and record['method'].split('.')[0] == context['service_family'])


def create_decision(request, context, existing=None):
    intent = request['intent']
    if not allowed(context) or not credentials(request, context):
        return 'denied'
    if {k: v for k, v in intent['identity'].items() if k != 'subscription_id'} != context['owner_identity']:
        return 'identity'
    if existing:
        return 'existing' if intent['identity'] == existing['identity'] and digest(intent) == existing['intent_digest'] else 'conflict'
    if intent['activation_ref'] != context['activation_ref']:
        return 'activation'
    if intent['method'] not in context['allowed_methods'] or intent['method'].split('.')[0] != context['service_family']:
        return 'method'
    if intent['target_handle'] != context['target_handle'] or intent['resource_ref'] != context['resource_ref']:
        return 'target'
    return 'new'


def close_decision(request, record, context):
    # 关闭无需仍有读取投影的租约/批准；仍要求当前认证及原owner权限。
    if not context['host_authenticated'] or not context['authorized'] or not credentials(request, context):
        return 'denied'
    if not owner_bound(request['identity'], context) or request['identity'] != record['identity']:
        return 'identity'
    if request['activation_ref'] != record['activation_ref']:
        return 'activation'
    return 'existing' if record['close_operation_ref'] else 'close'


def record_errors(record):
    errors = []
    p, a = int(record['published_sequence']), int(record['acknowledged_sequence'])
    if a > p:
        errors.append('high_water')
    if record['last_ack'] and int(record['last_ack']['projection_sequence']) != a:
        errors.append('last_ack')
    if record['state'] in ('live', 'invalidated') and p == 0:
        errors.append('no_baseline')
    return errors


def batch_errors(batch, record, store, context, limit=8):
    errors = []
    if not allowed(context) or not current_binding(record, context) or record['state'] not in ('pending', 'live', 'invalidated'):
        errors.append('closed')
    for key in ('identity', 'activation_ref', 'published_sequence'):
        if batch[key] != record[key]:
            errors.append(key)
    after, high = int(batch['after_sequence']), int(record['published_sequence'])
    if batch['after_sequence'] != record['acknowledged_sequence'] or not 1 <= limit <= 8:
        errors.append('cursor')
    expected = [str(n) for n in range(after + 1, min(after + limit, high) + 1)]
    if [f['envelope']['projection_sequence'] for f in batch['frames']] != expected:
        errors.append('prefix')
    for f in batch['frames']:
        e = f['envelope']
        if f['envelope_digest'] != digest(e) or store.get(e['projection_sequence']) != f:
            errors.append('original')
        if e['identity'] != record['identity'] or e['activation_ref'] != record['activation_ref'] or e['method'] != record['method']:
            errors.append('binding')
    if batch['has_more'] != (after + len(batch['frames']) < high):
        errors.append('has_more')
    return errors


def ack_decision(request, record, store, context):
    if not allowed(context) or not credentials(request, context) or not current_binding(record, context) or record['state'] not in ('live', 'invalidated'):
        return 'denied'
    if request['identity'] != record['identity']:
        return 'identity'
    frame, ack = request['frame'], request['panel_ack']
    for item in (frame, ack):
        if item['public_binding'] != context['public_binding'] or item['activation_ref'] != record['activation_ref'] or item['subscription_id'] != record['identity']['subscription_id']:
            return 'binding'
    if frame['projection_sequence'] != ack['projection_sequence'] or digest(frame) != ack['projection_digest']:
        return 'frame_digest'
    seq, consumed, published = int(ack['projection_sequence']), int(record['acknowledged_sequence']), int(record['published_sequence'])
    if seq < consumed:
        return 'stale'
    if seq == consumed:
        last = record['last_ack']
        return 'duplicate' if last and last['envelope_digest'] == request['envelope_digest'] and last['frame_digest'] == digest(frame) else 'conflict'
    if seq > published or seq - consumed > 32:
        return 'range'
    if any(str(n) not in store for n in range(consumed + 1, seq + 1)):
        return 'missing_prefix'
    original = store[str(seq)]
    envelope = original['envelope']
    if digest(envelope) != original['envelope_digest'] or request['envelope_digest'] != original['envelope_digest']:
        return 'envelope_digest'
    if envelope['identity'] != record['identity'] or envelope['activation_ref'] != record['activation_ref'] or envelope['method'] != record['method']:
        return 'original_binding'
    for key in ('activation_ref', 'method', 'projection_sequence', 'kind', 'reason_code', 'value'):
        if frame[key] != envelope[key]:
            return 'content'
    return 'advance'


def metadata_errors(api):
    errors = []
    expected = {'createPanelSubscription', 'getPanelSubscription', 'getPanelProjectionFrames', 'acknowledgePanelProjection', 'closePanelSubscription'}
    seen = []
    for path, item in api['paths'].items():
        for verb, op in item.items():
            seen.append(op['operationId'])
            security = {'humanBearer': []}
            if verb == 'post':
                security['sessionCsrf'] = []
            if op.get('security') != [security]:
                errors.append('security')
            if not any(p['in'] == 'header' and p['name'] == 'Origin' and p.get('required') for p in op['parameters']):
                errors.append('origin')
            if op.get('x-host-only') is not True or op.get('x-automatic-write-retry') is not False:
                errors.append('host_retry')
            if verb == 'get' and 'requestBody' in op:
                errors.append('get_body')
            if verb == 'get' and not any(p['in'] == 'query' and p['name'] == 'gui_instance_id' and p.get('required') for p in op['parameters']):
                errors.append('gui_query')
            for response in op['responses'].values():
                if response.get('headers', {}).get('Cache-Control', {}).get('schema', {}).get('const') != 'no-store':
                    errors.append('cache')
    if set(seen) != expected or len(seen) != 5:
        errors.append('coverage')
    return errors


def run():
    generated = build()
    for name, value in generated.items():
        assert (HERE / name).read_bytes() == encoded(value), name
    main, api = generated['subscriptions.schema.json'], generated['subscriptions.openapi.json']
    Draft202012Validator.check_schema(main)
    validate(api)
    registry = Registry().with_resources((uri, Resource.from_contents(doc)) for uri, (_, doc) in resources_for(main).items())
    results = []

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        results.append(dict(name=name, actual=actual, expected=expected, passed=True))

    def structure(name, model, value, expected):
        v = Draft202012Validator({'$ref': SID + '#/$defs/' + model}, registry=registry)
        projected = Draft202012Validator({'$ref': '#/components/schemas/Subscription_' + model, 'components': api['components']})
        actual = v.is_valid(value)
        check(name, actual, expected)
        assert projected.is_valid(value) == actual, ('OpenAPI接受集不同', name)

    check('五接口元数据', metadata_errors(api), [])
    check('19个可订阅方法', len(SUBSCRIBABLE), 19)
    check('两种失效通知', sorted(m['method'] for m in SUBSCRIBABLE if m['subscription_mode'] == 'invalidation'),
          ['controller.getCommandEvidence', 'controller.listDevices'])
    for m in SUBSCRIBABLE:
        f = fixtures(m['method'])
        for model, key in [('CreateSubscription', 'create'), ('SubscriptionRecord', 'record'), ('ProjectionBatch', 'batch'), ('AcknowledgeProjection', 'ack')]:
            structure(model + ':' + m['method'], model, f[key], True)
        check('合法受理:' + m['method'], create_decision(f['create'], f['context']), 'new')
        check('合法前缀:' + m['method'], batch_errors(f['batch'], f['record'], f['store'], f['context']), [])
        check('合法消费:' + m['method'], ack_decision(f['ack'], f['record'], f['store'], f['context']), 'advance')
    base = fixtures()
    for m in METHODS:
        if m['subscription_mode'] == 'none':
            altered = copy.deepcopy(base['create'])
            altered['intent']['method'] = m['method']
            structure('禁止订阅:' + m['method'], 'CreateSubscription', altered, False)
    for name, model, key, mutate in [
        ('额外字段', 'CreateSubscription', 'create', lambda v: v.update(token='not-a-secret')),
        ('空身份', 'CreateSubscription', 'create', lambda v: v['intent']['identity'].update(auth_session_id=None)),
        ('错误静态参数', 'CreateSubscription', 'create', lambda v: v['intent']['arguments'].update(value={'device_id': 7})),
        ('计数尾换行', 'ProjectionBatch', 'batch', lambda v: v.update(after_sequence='0\n')),
        ('超过批大小', 'ProjectionBatch', 'batch', lambda v: v.update(frames=v['frames'] * 9)),
        ('普通transport ACK', 'AcknowledgeProjection', 'ack', lambda v: v['panel_ack'].update(type='panel.ack')),
        ('错误模式', 'SubscriptionRecord', 'record', lambda v: v.update(mode='invalidation')),
        ('关闭缺操作引用', 'SubscriptionRecord', 'record', lambda v: v.update(state='closed')),
        ('已消费缺last_ack', 'SubscriptionRecord', 'record', lambda v: v.update(acknowledged_sequence='1')),
        ('首包不能update', 'ProjectionBatch', 'batch', lambda v: v['frames'][0]['envelope'].update(kind='update')),
        ('首包不能无类型内容', 'ProjectionBatch', 'batch', lambda v: v['frames'][0]['envelope'].update(value=None)),
    ]:
        value = copy.deepcopy(base[key]); mutate(value)
        structure(name, model, value, False)
    close = dict(gui_instance_id='gui.1', delegation_ref=base['create']['delegation_ref'], identity=base['record']['identity'],
                 activation_ref=base['record']['activation_ref'], reason_code='user_closed')
    structure('关闭输入', 'CloseSubscription', close, True)
    check('合法关闭', close_decision(close, base['record'], base['context']), 'close')
    expired = copy.deepcopy(base['context']); expired.update(lease_valid=False, approval_active=False, active=False)
    check('租约过期仍能关闭原订阅', close_decision(close, base['record'], expired), 'close')
    wrong = copy.deepcopy(close); wrong['identity']['auth_session_id'] = 'other'
    check('关闭不能跨原owner', close_decision(wrong, base['record'], base['context']), 'identity')
    check('原内容重复创建', create_decision(base['create'], base['context'], base['record']), 'existing')
    f = copy.deepcopy(base); f['create']['intent']['activation_ref']['activation_id'] = 'new-activation'
    check('原ID改激活', create_decision(f['create'], f['context'], f['record']), 'conflict')
    f = copy.deepcopy(base); f['record']['state'] = 'closed'; f['record']['close_operation_ref'] = reference('close', 'close.1')
    check('同ID不复活closed', create_decision(f['create'], f['context'], f['record']), 'existing')
    check('重复关闭复用原操作', close_decision(close, f['record'], f['context']), 'existing')
    for name, edit, result in [
        ('受理跨服务', lambda f: f['context'].update(service_family='seamer'), 'method'),
        ('受理错目标', lambda f: f['create']['intent'].update(target_handle='other'), 'target'),
        ('受理错激活', lambda f: f['create']['intent']['activation_ref'].update(activation_id='other'), 'activation'),
        ('受理错身份', lambda f: f['create']['intent']['identity'].update(issuer_epoch='other'), 'identity'),
    ]:
        f = copy.deepcopy(base); edit(f)
        check(name, create_decision(f['create'], f['context']), result)
    for name, edit, expected in [
        ('跨authority', lambda f: f['ack']['identity'].update(authority_service_id='other'), 'identity'),
        ('换页面且重算帧摘要', lambda f: f['ack']['frame']['public_binding'].update(panel_instance_id='other'), 'binding'),
        ('改值且重算帧摘要', lambda f: f['ack']['frame']['value']['value'].update(revision='99'), 'content'),
        ('替换包摘要', lambda f: f['ack'].update(envelope_digest='b' * 64), 'envelope_digest'),
        ('另一GUI', lambda f: f['ack'].update(gui_instance_id='other'), 'denied'),
        ('另一委托', lambda f: f['ack']['delegation_ref'].update(revision='2'), 'denied'),
        ('撤权', lambda f: f['context'].update(authorized=False), 'denied'),
        ('租约失效', lambda f: f['context'].update(lease_valid=False), 'denied'),
        ('挂载关闭', lambda f: f['context'].update(active=False), 'denied'),
        ('订阅关闭', lambda f: f['record'].update(state='closed'), 'denied'),
        ('订阅失步', lambda f: f['record'].update(state='gap'), 'denied'),
        ('缺原包', lambda f: f['store'].clear(), 'missing_prefix'),
    ]:
        f = copy.deepcopy(base); edit(f)
        f['ack']['panel_ack']['projection_digest'] = digest(f['ack']['frame'])
        check(name, ack_decision(f['ack'], f['record'], f['store'], f['context']), expected)
    f = copy.deepcopy(base); f['ack']['panel_ack']['projection_digest'] = 'b' * 64
    check('完整帧摘要错误', ack_decision(f['ack'], f['record'], f['store'], f['context']), 'frame_digest')
    f = copy.deepcopy(base)
    f['ack']['identity']['authority_service_id'] = 'other'; f['record']['identity']['authority_service_id'] = 'other'
    check('请求回执同时换身份仍拒绝', ack_decision(f['ack'], f['record'], f['store'], f['context']), 'denied')
    for name, edit in [
        ('遗漏包', lambda f: f['batch']['frames'].clear()),
        ('重复包', lambda f: f['batch']['frames'].append(copy.deepcopy(f['batch']['frames'][0]))),
        ('超前cursor', lambda f: f['batch'].update(after_sequence='1')),
        ('错误has_more', lambda f: f['batch'].update(has_more=True)),
        ('改出口重算摘要', lambda f: f['batch']['frames'][0]['envelope']['projection_exit_ref'].update(entity_id='other')),
        ('改来源重算摘要', lambda f: f['batch']['frames'][0]['envelope']['source_projection_ref'].update(entity_id='other')),
        ('失权仍返回包', lambda f: f['context'].update(authorized=False)),
    ]:
        f = copy.deepcopy(base); edit(f)
        for item in f['batch']['frames']:
            item['envelope_digest'] = digest(item['envelope'])
        check(name, bool(batch_errors(f['batch'], f['record'], f['store'], f['context'])), True)
    # 两帧累计ACK及重复消费，先显式构造权威发布记录，不调用判定器生成预期。
    f = copy.deepcopy(base)
    e = copy.deepcopy(f['store']['1']['envelope']); e.update(projection_sequence='2', kind='update')
    f['store']['2'] = dict(envelope=e, envelope_digest=digest(e))
    f['record']['published_sequence'] = '2'
    f['ack']['envelope_digest'] = digest(e)
    f['ack']['frame'].update(projection_sequence='2', kind='update', channel_sequence='3')
    f['ack']['panel_ack'].update(projection_sequence='2', channel_sequence='4', projection_digest=digest(f['ack']['frame']))
    check('连续两帧累计消费', ack_decision(f['ack'], f['record'], f['store'], f['context']), 'advance')
    missing = copy.deepcopy(f); del missing['store']['1']
    check('累计消费不能跳过缺包', ack_decision(missing['ack'], missing['record'], missing['store'], missing['context']), 'missing_prefix')
    f['record'].update(acknowledged_sequence='2', last_ack=dict(projection_sequence='2', envelope_digest=digest(e),
        frame_digest=digest(f['ack']['frame']), ack_ref=reference('projection_ack', 'ack.2')))
    f['store'].clear()
    check('最新ACK重复不需要旧大帧', ack_decision(f['ack'], f['record'], f['store'], f['context']), 'duplicate')
    check('旧ACK不再增加额度', ack_decision(base['ack'], f['record'], f['store'], f['context']), 'stale')
    f['ack']['frame']['channel_sequence'] = '5'; f['ack']['panel_ack']['projection_digest'] = digest(f['ack']['frame'])
    check('同序号重包装拒绝', ack_decision(f['ack'], f['record'], f['store'], f['context']), 'conflict')
    structure('已确认record', 'SubscriptionRecord', f['record'], True)
    check('已确认高水位一致', record_errors(f['record']), [])
    f['record']['acknowledged_sequence'] = '3'
    check('消费越发布高水位', bool(record_errors(f['record'])), True)
    pending = copy.deepcopy(base); pending['record'].update(state='pending', published_sequence='0')
    pending['batch'].update(published_sequence='0', frames=[])
    structure('pending空批次', 'ProjectionBatch', pending['batch'], True)
    check('pending不制造baseline', batch_errors(pending['batch'], pending['record'], {}, pending['context']), [])
    partial = copy.deepcopy(base); partial['record']['published_sequence'] = '2'; partial['batch'].update(published_sequence='2', has_more=True)
    check('limit一项正确前缀', batch_errors(partial['batch'], partial['record'], partial['store'], partial['context'], 1), [])
    invalidated = fixtures('controller.listDevices'); invalidated['batch']['frames'][0]['envelope']['value'] = base['ack']['frame']['value']
    structure('失效通知不得夹页面内容', 'ProjectionBatch', invalidated['batch'], False)
    for name, mutation in [('无CSRF', lambda a: a['paths'][PREFIX]['post'].update(security=[{'humanBearer': []}])),
                           ('写自动重试', lambda a: a['paths'][PREFIX]['post'].update({'x-automatic-write-retry': True})),
                           ('GET带body', lambda a: a['paths'][PREFIX + '/{subscription_id}']['get'].update(requestBody={})),
                           ('缺GUI关联', lambda a: a['paths'][PREFIX + '/{subscription_id}']['get'].update(parameters=[p for p in a['paths'][PREFIX + '/{subscription_id}']['get']['parameters'] if p['name']!='gui_instance_id'])),
                           ('缺Origin', lambda a: a['paths'][PREFIX]['post'].update(parameters=[]))]:
        a = copy.deepcopy(api); mutation(a)
        check(name, bool(metadata_errors(a)), True)
    return dict(approved=False, runtime_approved=False, all_passed=True, http_operations=5,
                structure_projection_comparison=True, checks=results, versions=dict(python=sys.version.split()[0]),
                runtime_validation=dict(http_services=0, browser=0, authorization=0, database=0, device=0),
                limitations=['权限和原包均为合成快照', '宿主全通道顺序和物理消费未取证',
                             '未执行动态Bundle二次校验及实际投影提供者', '累计消费为有限顺序，不证明SQLite或网络竞争'])


def check_report(staged=False):
    def read(path):
        return subprocess.check_output(['git', 'show', ':' + path.relative_to(ROOT).as_posix()], cwd=ROOT) if staged else path.read_bytes()
    report = json.loads(read(REPORT))
    assert report['all_passed'] is True
    assert set(report['input_sha256']) == {p.relative_to(ROOT).as_posix() for p in INPUTS}
    for path in INPUTS:
        assert report['input_sha256'][path.relative_to(ROOT).as_posix()] == hashlib.sha256(read(path)).hexdigest(), path
    print('15份输入字节绑定一致；未重跑用例')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true'); parser.add_argument('--check-report', action='store_true'); parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.check_report:
        check_report(args.staged)
    else:
        assert not args.staged
        report = run()
        report['input_sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS}
        if args.report:
            REPORT.write_bytes(encoded(report))
        print('订阅HTTP参考检查通过:', len(report['checks']))
