"""准备契约离线参考；信任、提交及当前门控均为人工夹具，无服务或设备I/O。"""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from openapi_spec_validator import validate as validate_openapi
from build_contracts import HERE, SOURCES, SID, VERSION, build, encoded

ROOT = HERE.parents[2]
REPORT = HERE / 'reference-report.json'
INPUTS = [HERE / n for n in ('README.md', 'build_contracts.py', 'check_contracts.py',
                             'preparation.schema.json', 'preparation.openapi.json')] + SOURCES
GRANT_FIELDS = ('principal_id', 'device_actions', 'parameter_constraints', 'validity')
RUN_FIELDS = ('origin_scope', 'run_id', 'definition_version', 'arm_generation')


def digest(v):
    return 'sha256:' + hashlib.sha256(rfc8785.dumps(v)).hexdigest()


def seal(v):
    v['receipt_digest'] = digest({k: x for k, x in v.items() if k != 'receipt_digest'})
    return v


def key(q):
    return q['controller_scope'], q['origin_scope'], q['preparation_id']


def set_error(q):
    actions = q['grant_intent']['device_actions']
    keys = [(a['device_id'], a['action_id'], a['capability_version']) for a in actions]
    devices = [x['device_id'] for x in q['controls']]
    if keys != sorted(set(keys)) or devices != sorted(set(devices)):
        return 'canonical_set'
    if set(devices) != {k[0] for k in keys}:
        return 'device_coverage'
    for field in ('operation_ref', 'plan_ref', 'artifact_ref'):
        if q[field]['scope'] != q['origin_scope']:
            return 'source_ref'
    if q['operation_ref']['object_id'] != q['operation_id']:
        return 'operation_ref'
    if q['baseline_grant_ref'] and q['baseline_grant_ref']['scope'] != q['controller_scope']:
        return 'baseline_scope'
    return None


def request_error(q, c, existing=None):
    if not c['authenticated'] or not c['prepare_permission'] or not c['read_permission']:
        return 'forbidden'
    if q['origin_scope'] != c['origin_scope'] or q['controller_scope'] != c['controller_scope']:
        return 'scope'
    if existing:
        if key(q) != key(existing['request']):
            return 'lookup_binding'
        return 'conflict' if digest(q) != existing['request_digest'] else None
    if set_error(q):
        return set_error(q)
    if q != c['approved_request']:
        return 'authority_binding'
    if not c['current_gates'] or not c['capacity_reserved']:
        return 'protected'
    if int(q['arm_generation']) <= c['deny_floor']:
        return 'denied_generation'
    if c['generation_preparation_id'] not in (None, q['preparation_id']):
        return 'generation_owned'
    return None


def receipt_error(q, r, c):
    if r['preparation_id'] != q['preparation_id'] or r['controller_scope'] != q['controller_scope'] \
            or r['request_digest'] != digest(q):
        return 'receipt_binding'
    if seal(copy.deepcopy(r)) != r:
        return 'receipt_digest'
    g, gr = r['grant'], r['grant_ref']
    if any(g[k] != q[k] for k in RUN_FIELDS) or any(g[k] != q['grant_intent'][k] for k in GRANT_FIELDS):
        return 'grant_binding'
    if g['state'] != 'active' or g['issuer_id'] != c['issuer_id'] or g['issuer_epoch'] != c['issuer_epoch']:
        return 'issuer'
    if gr != dict(kind='grant', scope=q['controller_scope'], object_id=g['grant_id'],
                  revision=g['revision'], digest=digest(g)):
        return 'grant_ref'
    if r['commit_ref']['scope'] != q['controller_scope'] or not c['trusted_durable_commit']:
        return 'commit'
    # 摘要和字段不证明签发：显式核对合成权威记录，不把请求自证当事实。
    if r != c['authoritative_receipt']:
        return 'authority_receipt'
    return None


def bind_receipt(q, r, c, prior=None, failed=False):
    error = receipt_error(q, r, c)
    if error:
        return error
    if failed or not c['current_gates'] or c['operation_terminal'] \
            or c['current_operation_id'] != q['operation_id'] \
            or c['current_generation'] != q['arm_generation'] \
            or c['current_baseline'] != {k: q[k] for k in ('authorization_digest', 'source_digest', 'controls')}:
        return 'history_only_close_required'
    if prior is not None and prior != r:
        return 'immutable_receipt'
    return 'existing' if prior is not None else 'bound'


def close_error(close, c, existing=None):
    q = close['request']
    if not c['authenticated'] or not c['protect_permission']:
        return 'forbidden'
    if q['origin_scope'] != c['origin_scope'] or q['controller_scope'] != c['controller_scope']:
        return 'scope'
    if close['request_digest'] != digest(q):
        return 'request_digest'
    if existing and (key(q) != key(existing['request']) or close['request_digest'] != existing['request_digest']):
        return 'conflict'
    if c.get('prior_close') and close['close_operation_id'] == c['prior_close']['close_operation_id'] \
            and close != c['prior_close']:
        return 'close_conflict'
    return None


def lookup_result(lookup, c, existing=None):
    if not c['authenticated'] or not c['read_permission']:
        return 'forbidden'
    if lookup['origin_scope'] != c['origin_scope'] or lookup['controller_scope'] != c['controller_scope']:
        return 'scope'
    if not c['lookup_complete']:
        return 'indeterminate'
    if existing is None:
        return 'not_found'
    if key(lookup) != key(existing['request']) or lookup['request_digest'] != existing['request_digest']:
        return 'conflict'
    return 'found'


def command_error(q, r, binding, grant_ref, c):
    if receipt_error(q, r, c):
        return 'preparation_receipt'
    if c['preparation_state'] != 'applied' or not c['current_gates']:
        return 'protected'
    if int(binding['arm_generation']) <= c['deny_floor']:
        return 'denied_generation'
    if any(binding[k] != q[k] for k in RUN_FIELDS):
        return 'run_binding'
    if q['mode'] == 'recovery' and binding['execution_id'] != q['execution_id']:
        return 'execution_binding'
    if binding != c['authoritative_command_binding']:
        return 'execution_authority'
    if grant_ref != r['grant_ref'] or grant_ref not in c['execution_grants']:
        return 'execution_grant'
    if not c['step_parameters_match']:
        return 'plan'
    return None


def transition(before, after):
    edges = {'accepted': {'applied', 'rejected', 'indeterminate', 'closing'},
             'applied': {'closing'}, 'indeterminate': {'closing'}, 'closing': {'closed'},
             'rejected': set(), 'closed': set()}
    if before == after:
        return None
    if before['request'] != after['request'] or before['request_digest'] != after['request_digest']:
        return 'immutable_request'
    if after['state'] not in edges[before['state']] or int(after['revision']) != int(before['revision']) + 1:
        return 'transition'
    if before['applied_receipt'] is not None and before['applied_receipt'] != after['applied_receipt']:
        return 'immutable_receipt'
    return None


def fixture(mode='recovery'):
    scope = lambda name: dict(authority_service_id=name, database_instance_id=name + '_db')
    origin, controller = scope('seamer'), scope('controller')
    reference = lambda kind, name, s=origin: dict(kind=kind, scope=copy.deepcopy(s), object_id=name,
                                                revision='1', digest=digest(name))
    intent = dict(principal_id='service', device_actions=[
        dict(device_id='obs', action_id='obs.program_scene.set', capability_version='1.0.0')],
        parameter_constraints=[], validity=dict(not_before='2026-10-20T00:00:00.000Z',
        not_after='2026-10-20T01:00:00.000Z', authorization_policy_revision='1'))
    q = dict(contract_version=VERSION, operation_id='operation', preparation_id='preparation',
        controller_scope=controller, origin_scope=origin, run_id='run', definition_version='1',
        arm_generation='2', mode=mode, execution_id=None if mode == 'arm' else 'execution',
        operation_ref=reference('lifecycle_operation', 'operation'),
        plan_ref=reference('arm_plan' if mode == 'arm' else 'recovery_plan', 'plan'),
        artifact_ref=reference('artifact', 'artifact'), approval_ref=reference('approval', 'approval'),
        authorization_digest=digest('authorization'), source_digest=digest('source'),
        controls=[dict(device_id='obs', expected_control=dict(epoch='control_epoch', version='2'))],
        baseline_grant_ref=None, grant_intent=intent)
    g = dict(grant_id='grant', revision='1', **{k: copy.deepcopy(q[k]) for k in RUN_FIELDS},
             **copy.deepcopy(intent), state='active', issuer_id='issuer', issuer_epoch='issuer_epoch')
    gr = dict(kind='grant', scope=controller, object_id='grant', revision='1', digest=digest(g))
    r = seal(dict(receipt_id='receipt', revision='1', controller_scope=controller,
        preparation_id='preparation', request_digest=digest(q), grant=g, grant_ref=gr,
        commit_ref=reference('controller_commit', 'commit', controller)))
    record = dict(request=q, request_digest=digest(q), revision='2', state='applied',
                  applied_receipt=r, protection_ref=None)
    binding = {**{k: copy.deepcopy(q[k]) for k in RUN_FIELDS}, 'execution_id': 'execution',
        'execution_binding_ref': reference('execution_binding', 'execution'),
        'step_id': 'step', 'logical_action_id': 'logical'}
    c = dict(authenticated=True, prepare_permission=True, read_permission=True, protect_permission=True,
        origin_scope=origin, controller_scope=controller, approved_request=q, current_gates=True,
        capacity_reserved=True, deny_floor=1, generation_preparation_id=None, issuer_id='issuer',
        issuer_epoch='issuer_epoch', trusted_durable_commit=True, authoritative_receipt=r,
        preparation_state='applied', authoritative_command_binding=binding, execution_grants=[gr],
        step_parameters_match=True, current_operation_id='operation', current_generation='2',
        operation_terminal=False, lookup_complete=True,
        current_baseline={k: copy.deepcopy(q[k]) for k in ('authorization_digest', 'source_digest', 'controls')})
    # 序列化隔离消息与权威夹具，防止共享引用使变异自证。
    return tuple(json.loads(json.dumps(x)) for x in (q, r, record, binding, c))


def run():
    outputs = build()
    for name, value in outputs.items():
        assert (HERE / name).read_bytes() == encoded(value), name
    schema = outputs['preparation.schema.json']
    docs = [schema] + [json.loads(p.read_bytes()) for p in SOURCES]
    registry = Registry().with_resources((d['$id'], Resource.from_contents(d)) for d in docs)
    for d in docs:
        Draft202012Validator.check_schema(d)
    api = outputs['preparation.openapi.json']
    validate_openapi(api)
    results = []
    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        results.append(dict(id=name, passed=True))
    def shape(name, value):
        return Draft202012Validator({'$ref': SID + '#/$defs/' + name},
            registry=registry, format_checker=FormatChecker()).is_valid(value)
    q, r, record, binding, c = fixture()
    close = dict(contract_version=VERSION, close_operation_id='close', request=q, request_digest=digest(q))
    lookup = dict(contract_version=VERSION, controller_scope=q['controller_scope'],
                  origin_scope=q['origin_scope'], preparation_id=q['preparation_id'], request_digest=digest(q))
    fixtures = {'PrepareRequest': q, 'PreparationReceipt': r, 'PreparationRecord': record,
                'PreparationLookup': lookup, 'PreparationClose': close,
                'PreparationLookupResult': dict(state='found', record=record)}
    for name, value in fixtures.items():
        check(name + '正例', shape(name, value), True)
        bad = copy.deepcopy(value); bad['unexpected'] = True
        check(name + '额外字段拒绝', shape(name, bad), False)
    qa, ra, _, ba, ca = fixture('arm')
    check('arm无执行正例', shape('PrepareRequest', qa), True)
    for mode, value in [('arm带执行', qa | {'execution_id': 'execution'}),
                        ('恢复缺执行', q | {'execution_id': None}),
                        ('零代次', q | {'arm_generation': '0'}),
                        ('旧语义版本', q | {'definition_version': '1.0.0'}),
                        ('尾换行计数', q | {'definition_version': '1\n'}),
                        ('前导零代次', q | {'arm_generation': '02'}),
                        ('旧协议', q | {'contract_version': '1.0.0-draft.4'}),
                        ('零设备', q | {'controls': []}),
                        ('设备超限', q | {'controls': q['controls'] * 257})]:
        check(mode, shape('PrepareRequest', value), False)
    check('新准备准入', request_error(q, c), None)
    check('准备查原正例', lookup_result(lookup, c, record), 'found')
    check('查无不等于允许重发', lookup_result(lookup, c), 'not_found')
    check('存储查询不可靠', lookup_result(lookup, c | {'lookup_complete': False}), 'indeterminate')
    check('查询仍先鉴权', lookup_result(lookup, c | {'authenticated': False}, record), 'forbidden')
    check('查询错请求摘要', lookup_result(lookup | {'request_digest': digest('other')}, c, record), 'conflict')
    check('原件查询不重新签发', request_error(q, c | {'current_gates': False}, record), None)
    check('查原仍先鉴权', request_error(q, c | {'authenticated': False}, record), 'forbidden')
    check('同身份异正文', request_error(q | {'operation_id': 'other'}, c, record), 'conflict')
    for field in ('controller_scope', 'origin_scope'):
        bad = copy.deepcopy(q); bad[field]['database_instance_id'] = 'other'
        check('请求错域' + field, request_error(bad, c), 'scope')
    for field in ('authorization_digest', 'source_digest'):
        check('新请求权威错配' + field, request_error(q | {field: digest('other')}, c), 'authority_binding')
    check('保护下界等号拒绝', request_error(q, c | {'deny_floor': 2}), 'denied_generation')
    check('容量未预留', request_error(q, c | {'capacity_reserved': False}), 'protected')
    check('换ID绕同代准备', request_error(q, c | {'generation_preparation_id': 'other'}), 'generation_owned')
    bad = copy.deepcopy(q); bad['controls'].append(copy.deepcopy(bad['controls'][0]))
    check('重复目标', request_error(bad, c), 'canonical_set')
    bad = copy.deepcopy(q); bad['controls'][0]['device_id'] = 'other'
    check('目标集合缺项', request_error(bad, c), 'device_coverage')
    bad = copy.deepcopy(q); bad['operation_ref']['object_id'] = 'other'
    check('操作引用错配', request_error(bad, c), 'operation_ref')
    check('回执关联正例', receipt_error(q, r, c), None)
    check('首次精确绑定', bind_receipt(q, r, c), 'bound')
    check('重复回执只查原', bind_receipt(q, r, c, r), 'existing')
    check('超时后迟到回执', bind_receipt(q, r, c, failed=True), 'history_only_close_required')
    for name, change in [('准备期间接管', {'current_gates': False}),
                         ('旧操作回执', {'current_operation_id': 'other'}),
                         ('旧代次回执', {'current_generation': '3'}),
                         ('操作已终止', {'operation_terminal': True}),
                         ('独立基线变化', {'current_baseline': {}})]:
        check(name, bind_receipt(q, r, c | change), 'history_only_close_required')
    for field in RUN_FIELDS + GRANT_FIELDS:
        bad = copy.deepcopy(r)
        if field in RUN_FIELDS:
            bad['grant'][field] = {'authority_service_id': 'other', 'database_instance_id': 'other'} \
                if field == 'origin_scope' else '9'
        elif field == 'principal_id':
            bad['grant'][field] = 'other'
        elif field == 'validity':
            bad['grant'][field]['not_after'] = '2026-10-21T01:00:00.000Z'
        else:
            bad['grant'][field] = [{'extra': True}]
        bad['grant_ref']['digest'] = digest(bad['grant']); seal(bad)
        check('重算摘要仍拒grant错配_' + field, receipt_error(q, bad, c), 'grant_binding')
    bad = copy.deepcopy(r); bad['grant']['issuer_epoch'] = 'other'
    bad['grant_ref']['digest'] = digest(bad['grant']); seal(bad)
    check('签发域错配', receipt_error(q, bad, c), 'issuer')
    bad = copy.deepcopy(r); bad['grant_ref']['revision'] = '2'; seal(bad)
    check('grant引用错配', receipt_error(q, bad, c), 'grant_ref')
    check('未可靠落盘', receipt_error(q, r, c | {'trusted_durable_commit': False}), 'commit')
    bad = copy.deepcopy(r); bad['receipt_id'] = 'forged'; seal(bad)
    check('自洽摘要非真实签发', receipt_error(q, bad, c), 'authority_receipt')
    check('既有绑定不可替换', bind_receipt(q, r, c, r | {'receipt_id': 'other'}), 'immutable_receipt')
    check('close先到不要求grant', close_error(close, c | {'prepare_permission': False, 'current_gates': False}), None)
    check('close仍需保护权', close_error(close, c | {'protect_permission': False}), 'forbidden')
    check('close原请求摘要错误', close_error(close | {'request_digest': digest('wrong')}, c), 'request_digest')
    bad = copy.deepcopy(close); bad['request']['operation_id'] = 'other'; bad['request_digest'] = digest(bad['request'])
    check('close不改原准备', close_error(bad, c, record), 'conflict')
    check('close同键异正文', close_error(bad, c | {'prior_close': close}), 'close_conflict')
    check('新关闭身份可指同一准备', close_error(close | {'close_operation_id': 'second'}, c | {'prior_close': close}, record), None)
    closing = copy.deepcopy(record); closing.update(state='closing', revision='3')
    closed = copy.deepcopy(closing); closed.update(state='closed', revision='4', protection_ref=dict(
        kind='run_protection', scope=q['controller_scope'], object_id='protection', revision='1', digest=digest('p')))
    check('applied进入closing', transition(record, closing), None)
    check('closing保留历史回执', transition(closing, closed), None)
    check('closed结构', shape('PreparationRecord', closed), True)
    check('关闭无持久回执拒绝', shape('PreparationRecord', closed | {'protection_ref': None}), False)
    check('applied无回执拒绝', shape('PreparationRecord', record | {'applied_receipt': None}), False)
    check('closed不得复活', transition(closed, record | {'revision': '5'}), 'transition')
    check('修订不可跳跃', transition(record, closing | {'revision': '4'}), 'transition')
    check('关闭不可删除历史回执', transition(record, closing | {'applied_receipt': None}), 'immutable_receipt')
    check('迟到prepare只返回关闭原件', request_error(q, c | {'current_gates': False}, closed), None)
    check('关闭后命令拒绝', command_error(q, r, binding, r['grant_ref'], c | {'preparation_state': 'closed'}), 'protected')
    check('恢复执行关联正例', command_error(q, r, binding, r['grant_ref'], c), None)
    check('arm执行仍验权威', command_error(qa, ra, ba, ra['grant_ref'], ca), None)
    check('恢复不能借其他执行', command_error(q, r, binding | {'execution_id': 'other'}, r['grant_ref'], c), 'execution_binding')
    check('arm不接受任意执行', command_error(qa, ra, ba | {'execution_id': 'other'}, ra['grant_ref'], ca), 'execution_authority')
    check('最终执行缺grant', command_error(q, r, binding, r['grant_ref'], c | {'execution_grants': []}), 'execution_grant')
    check('步骤参数不符', command_error(q, r, binding, r['grant_ref'], c | {'step_parameters_match': False}), 'plan')
    check('命令最终下界拒绝', command_error(q, r, binding, r['grant_ref'], c | {'deny_floor': 2}), 'denied_generation')
    bad = copy.deepcopy(r); bad['preparation_id'] = 'other'; seal(bad)
    check('命令不得借另一准备回执', command_error(q, bad, binding, r['grant_ref'], c), 'preparation_receipt')
    # OpenAPI闭包接受集对照及明确认证/版本/缓存声明，不代表实际中间件。
    for path, item in api['paths'].items():
        op = item['post']
        check(path + '认证', op['security'], [{'InternalMTLS': []}])
        check(path + '版本', op['parameters'][0]['schema'], {'const': VERSION})
        check(path + '缓存', all(v['headers']['Cache-Control']['schema'] == {'const': 'no-store'}
                                for v in op['responses'].values()), True)
        root = op['requestBody']['content']['application/json']['schema']
        projected = {'$schema': schema['$schema'], 'components': api['components'], **root}
        validator = Draft202012Validator(projected, format_checker=FormatChecker())
        value = {'prepareAutomation': q, 'lookupPreparation': lookup, 'closePreparation': close}[op['operationId']]
        check(path + '投影正例', validator.is_valid(value), True)
        check(path + '投影反例', validator.is_valid(value | {'unexpected': True}), False)
    return dict(all_passed=True, approved=False, checks=len(results), results=results,
        limitations=['权威与持久提交为人工夹具', '串行快照不执行writer或故障恢复',
                     '未迁移公共命令全部路由或实现SDK', '未验证动态参数授权和真实签发者'],
        runtime_validation=dict(http=0, identity_provider=0, sqlite=0, concurrency=0, device=0))


def hashes(staged=False):
    result = {}
    for p in INPUTS:
        name = p.relative_to(ROOT).as_posix()
        raw = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT) if staged else p.read_bytes()
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.check_report:
        raw = subprocess.check_output(['git', 'show', ':' + REPORT.relative_to(ROOT).as_posix()], cwd=ROOT) \
            if args.staged else REPORT.read_bytes()
        assert json.loads(raw)['input_sha256'] == hashes(args.staged)
        print('8份输入字节绑定通过；未重跑检查')
    else:
        result = run()
        result['input_sha256'] = hashes()
        if args.report:
            REPORT.write_bytes(encoded(result))
        print(json.dumps({k: result[k] for k in ('all_passed', 'approved', 'checks')}))
