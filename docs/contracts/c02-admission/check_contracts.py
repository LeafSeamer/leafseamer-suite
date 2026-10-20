"""命令裁决离线参考：合成权威与内存串行账本，不执行真实鉴权、SQL或设备。"""
import argparse
import copy
import hashlib
import json
import subprocess
import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from openapi_spec_validator import validate as validate_openapi
from build_contracts import HERE, SOURCES, SID, VERSION, EXCLUDED, build, encoded

ROOT = HERE.parents[2]
REPORT = HERE / 'reference-report.json'
INPUTS = [HERE / n for n in ('README.md', 'build_contracts.py', 'check_contracts.py',
                             'admission.schema.json', 'admission.openapi.json')] + SOURCES


def digest(v):
    return 'sha256:' + hashlib.sha256(rfc8785.dumps(v)).hexdigest()


def content(q):
    return {k: copy.deepcopy(v) for k, v in q.items() if k not in EXCLUDED}


def seal(a):
    a['adjudication_digest'] = digest({k: v for k, v in a.items() if k != 'adjudication_digest'})
    return a


def key_string(identity):
    return rfc8785.dumps(identity['key']).decode()


def authorized(identity, c, action):
    if not c['authenticated'] or not c['permissions'][action] or not c['read_scope_verified']:
        return 'forbidden'
    if identity['key'] != c['original_key']:
        return 'namespace'
    if not c['historical_owner_verified'] or not c['panel_delegation_valid']:
        return 'forbidden'
    return None


def lookup(ledger, identity, c):
    error = authorized(identity, c, 'lookup')
    if error:
        return error, None
    if not c['storage_readable']:
        return 'indeterminate', None
    record = ledger.get(key_string(identity))
    if record is None:
        return 'not_found', None
    if record['identity'] != identity:
        return 'conflict', None
    return 'found', copy.deepcopy(record)


def decide(ledger, identity, body, action, c, operations=None, rejection_id=None):
    """一次调用假设writer串行及原子提交；返回副本，不是生产事务实现。"""
    original = copy.deepcopy(ledger)
    ops = copy.deepcopy(operations or {})
    error = authorized(identity, c, action)
    if error:
        return original, ops, error, None
    if identity['request_digest'] != digest(body):
        return original, ops, 'request_digest', None
    if c['principal_kind'] == 'human':
        if body['origin'] != 'manual':
            return original, ops, 'subject_origin', None
    elif c['peer_kind'] != 'seamer' or body['origin'] != 'automation':
        return original, ops, 'subject_origin', None
    if not c['storage_readable']:
        return original, ops, 'indeterminate', None
    op_key = (c['current_actor'], rejection_id)
    op_digest = digest(dict(identity=identity, content=body))
    if action == 'reject' and op_key in ops and ops[op_key]['request_digest'] != op_digest:
        return original, ops, 'rejection_conflict', None
    k = key_string(identity)
    prior = original.get(k)
    if prior and prior['identity'] != identity:
        return original, ops, 'conflict', None
    if action == 'reject' and op_key in ops:
        if prior is None or ops[op_key]['adjudication_digest'] != prior['adjudication_digest']:
            return original, ops, 'indeterminate', None
        return original, ops, 'existing', copy.deepcopy(prior)
    if prior and action == 'submit':
        return original, ops, 'existing', copy.deepcopy(prior)
    if action == 'submit' and (not c['namespace_writable'] or not c['current_execution_gates']):
        return original, ops, 'protected', None
    if not c['capacity_reserved']:
        return original, ops, 'capacity', None
    record = prior
    if record is None:
        target = identity['key']['target_scope']
        ref = lambda kind, name: dict(kind=kind, scope=copy.deepcopy(target), object_id=name,
                                      revision='1', digest=digest(name))
        record = seal(dict(contract_version=VERSION, adjudication_id='adjudication', revision='1',
            identity=copy.deepcopy(identity), decision='accepted' if action == 'submit' else 'rejected',
            command_ref=ref('command', 'command') if action == 'submit' else None,
            commit_ref=ref('controller_commit', 'commit')))
    if not c['commit_ok']:
        return original, ops, 'unavailable', None
    updated = copy.deepcopy(original)
    updated[k] = copy.deepcopy(record)
    if action == 'reject':
        ops[op_key] = dict(request_digest=op_digest, adjudication_digest=record['adjudication_digest'])
    if c['response_lost']:
        return updated, ops, 'indeterminate', None
    return updated, ops, 'existing' if prior else record['decision'], copy.deepcopy(record)


def evidence_error(identity, record, c):
    if record['identity'] != identity:
        return 'identity'
    if seal(copy.deepcopy(record)) != record:
        return 'digest'
    scope = identity['key']['target_scope']
    if record['commit_ref']['scope'] != scope or \
            (record['command_ref'] is not None and record['command_ref']['scope'] != scope):
        return 'scope'
    if not c['durable_provider_verified'] or record != c['authoritative_adjudication']:
        return 'authority'
    return None


def fixture(automation=False):
    scope = dict(authority_service_id='controller', database_instance_id='controller_db')
    key = dict(target_scope=scope, issuer_id='issuer', issuer_epoch='issuer_epoch',
               principal_id='subject', request_epoch='request_epoch', operation_id='createCommand',
               idempotency_key='key')
    q = dict(context_id='context', idempotency_key='key', device_id='obs', action_id='custom.set',
        capability_version='1.0.0', parameters=dict(context_id='business_value', proof='retained'),
        expected_control=dict(epoch='control_epoch', version='2'), origin='manual',
        required_completion='sent', preconditions=[], dispatch=dict(mode='immediate', max_queue_ms=1000),
        evidence_timeout_ms=1000, correlation_id='correlation', automation_binding=None)
    if automation:
        origin = dict(authority_service_id='seamer', database_instance_id='seamer_db')
        q['origin'] = 'automation'
        q['run_binding'] = dict(run_id='run', definition_version='1', grant_id='grant',
            grant_revision='1', arm_generation='2', step_id='step', logical_action_id='logical')
        q['automation_binding'] = dict(origin_scope=origin, run_id='run', definition_version='1',
            arm_generation='2', execution_id='execution', step_id='step', logical_action_id='logical',
            execution_binding_ref=dict(kind='execution_binding', scope=origin, object_id='execution',
                                       revision='1', digest=digest('execution')))
    identity = dict(key=key, request_digest=digest(content(q)))
    c = dict(authenticated=True, permissions=dict(submit=True, reject=True, lookup=True),
        read_scope_verified=True, original_key=key, historical_owner_verified=True,
        panel_delegation_valid=True, storage_readable=True, current_actor='actor',
        principal_kind='service' if automation else 'human', peer_kind='seamer',
        namespace_writable=True, current_execution_gates=True, capacity_reserved=True,
        commit_ok=True, response_lost=False, durable_provider_verified=True)
    return tuple(json.loads(json.dumps(x)) for x in (q, identity, c))


def run():
    outputs = build()
    for name, value in outputs.items():
        assert (HERE / name).read_bytes() == encoded(value), name
    schema, api = outputs['admission.schema.json'], outputs['admission.openapi.json']
    docs = [schema] + [json.loads(p.read_bytes()) for p in SOURCES]
    registry = Registry().with_resources((d['$id'], Resource.from_contents(d)) for d in docs)
    for d in docs:
        Draft202012Validator.check_schema(d)
    validate_openapi(api)
    results = []
    def check(name, value, expected):
        assert value == expected, (name, value, expected)
        results.append(dict(id=name, passed=True))
    def shape(name, value):
        return Draft202012Validator({'$ref': SID + '#/$defs/' + name},
            registry=registry, format_checker=FormatChecker()).is_valid(value)
    q, identity, c = fixture()
    body = content(q)
    accepted, _, state, record = decide({}, identity, body, 'submit', c)
    rejected, ops, rejected_state, tombstone = decide({}, identity, body, 'reject', c, rejection_id='reject')
    reject_request = dict(rejection_operation_id='reject', identity=identity, content=body)
    fixtures = dict(CommandRequest=q, CommandContent=body, RequestIdentity=identity,
        RequestAdjudication=record, RejectRequest=reject_request,
        LookupResult=dict(state='found', adjudication=record))
    for name, value in fixtures.items():
        check(name + '正例', shape(name, value), True)
        check(name + '额外字段', shape(name, value | {'unexpected': True}), False)
    check('接受一次', state, 'accepted')
    check('拒收一次', rejected_state, 'rejected')
    check('墓碑结构', shape('RequestAdjudication', tombstone), True)
    check('accepted不可空命令', shape('RequestAdjudication', record | {'command_ref': None}), False)
    check('rejected不可带命令', shape('RequestAdjudication', tombstone | {'command_ref': record['command_ref']}), False)
    check('裁决版本不可混投', shape('RequestAdjudication', record | {'contract_version': '1.0.0-draft.4'}), False)
    check('裁决修订不可更新', shape('RequestAdjudication', record | {'revision': '2'}), False)
    bad_identity = copy.deepcopy(identity); del bad_identity['key']['issuer_epoch']
    check('旧身份缺签发代次拒绝', shape('RequestIdentity', bad_identity), False)
    bad_identity = copy.deepcopy(identity); bad_identity['key']['operation_id'] = 'submitCommand'
    check('HTTP名称不可冒持久操作名', shape('RequestIdentity', bad_identity), False)
    check('found必须有裁决', shape('LookupResult', dict(state='found', adjudication=None)), False)
    check('未知不能附伪裁决', shape('LookupResult', dict(state='indeterminate', adjudication=record)), False)
    for field in EXCLUDED:
        check('Content不接受运输字段_' + field, shape('CommandContent', body | {field: 'transport'}), False)
        changed = copy.deepcopy(q); changed[field] = 'transport'
        check('顶层字段不改变摘要_' + field, digest(content(changed)), identity['request_digest'])
    changed = copy.deepcopy(q); changed['parameters']['context_id'] = 'different'
    check('嵌套同名字段保留', digest(content(changed)) != identity['request_digest'], True)
    changed = copy.deepcopy(q); changed['parameters']['proof'] = 'different'
    check('业务proof参与摘要', digest(content(changed)) != identity['request_digest'], True)
    qa, ia, ca = fixture(True)
    check('自动化提交结构', shape('CommandRequest', qa), True)
    check('自动化来源不可剥离', shape('CommandRequest', qa | {'automation_binding': None}), False)
    check('人工不可带自动化来源', shape('CommandRequest', q | {'automation_binding': qa['automation_binding']}), False)
    check('组织自动化正例', decide({}, ia, content(qa), 'submit', ca)[2], 'accepted')
    check('service不能冒人工', decide({}, identity, body, 'submit', c | {'principal_kind': 'service'})[2], 'subject_origin')
    check('human不能冒自动化', decide({}, ia, content(qa), 'submit', ca | {'principal_kind': 'human'})[2], 'subject_origin')
    check('provider不能冒Seamer', decide({}, ia, content(qa), 'submit', ca | {'peer_kind': 'provider'})[2], 'subject_origin')
    # 两种明确顺序；真实并发、数据库线性化和掉电另验。
    after, _, state, same = decide(accepted, identity, body, 'reject', c, rejection_id='reject')
    check('受理先到只返回原accepted', (state, same, after), ('existing', record, accepted))
    after, _, state, same = decide(rejected, identity, body, 'submit', c)
    check('拒收先到迟到命令不创建', (state, same, after), ('existing', tombstone, rejected))
    check('原件查原', lookup(accepted, identity, c), ('found', record))
    check('未找到不是永久拒收', lookup({}, identity, c), ('not_found', None))
    check('存储不可读不报未找到', lookup({}, identity, c | {'storage_readable': False}), ('indeterminate', None))
    mutated = copy.deepcopy(body); mutated['parameters']['proof'] = 'new'
    changed_identity = identity | {'request_digest': digest(mutated)}
    check('同key换digest仍冲突', decide(accepted, changed_identity, mutated, 'submit', c)[2], 'conflict')
    check('查询错摘要冲突', lookup(accepted, changed_identity, c), ('conflict', None))
    check('拒收错摘要保留原件', decide(accepted, changed_identity, mutated, 'reject', c, rejection_id='reject')[2], 'conflict')
    check('拒收摘要不可自报', decide({}, identity, mutated, 'reject', c, rejection_id='reject')[2], 'request_digest')
    for field in ('issuer_epoch', 'issuer_id', 'principal_id', 'request_epoch', 'operation_id'):
        bad = copy.deepcopy(identity); bad['key'][field] = 'other'
        check('错命名空间_' + field, lookup(accepted, bad, c), ('namespace', None))
    bad = copy.deepcopy(identity); bad['key']['target_scope']['database_instance_id'] = 'other'
    check('Controller换库拒旧身份', lookup(accepted, bad, c), ('namespace', None))
    check('重复返回仍需当前权限', lookup(accepted, identity, c | {'read_scope_verified': False}), ('forbidden', None))
    check('历史同名不证明归属', lookup(accepted, identity, c | {'historical_owner_verified': False}), ('forbidden', None))
    check('面板委托越界', decide({}, identity, body, 'reject', c | {'panel_delegation_valid': False}, rejection_id='reject')[2], 'forbidden')
    check('旧动作资格失效可拒收', decide({}, identity, body, 'reject', c | {'current_execution_gates': False}, rejection_id='reject')[2], 'rejected')
    check('旧动作资格失效不可新受理', decide({}, identity, body, 'submit', c | {'current_execution_gates': False})[2], 'protected')
    check('命名空间退休不再新受理', decide({}, identity, body, 'submit', c | {'namespace_writable': False})[2], 'protected')
    check('容量不足不删墓碑', decide(rejected, identity, body, 'submit', c | {'capacity_reserved': False})[0], rejected)
    check('新拒收容量不足不伪提交', decide({}, identity, body, 'reject', c | {'capacity_reserved': False}, rejection_id='reject')[2], 'capacity')
    check('同拒收操作不得换内容', decide(rejected, changed_identity, mutated, 'reject', c, ops, 'reject')[2], 'rejection_conflict')
    check('重复拒收不重新消耗容量', decide(rejected, identity, body, 'reject',
          c | {'capacity_reserved': False}, ops, 'reject')[3], tombstone)
    check('拒收结果缺裁决不重建', decide({}, identity, body, 'reject', c, ops, 'reject')[2], 'indeterminate')
    check('独立拒收仍返回原墓碑', decide(rejected, identity, body, 'reject', c, ops, 'another')[3], tombstone)
    for action in ('submit', 'reject'):
        ledger, _, state, value = decide({}, identity, body, action, c | {'commit_ok': False}, rejection_id='reject')
        check(action + '提交前失败', (ledger, state, value), ({}, 'unavailable', None))
        ledger, _, state, value = decide({}, identity, body, action, c | {'response_lost': True}, rejection_id='reject')
        check(action + '响应丢失不伪成功', (state, value), ('indeterminate', None))
        check(action + '提交后查原', lookup(ledger, identity, c)[1]['decision'], 'accepted' if action == 'submit' else 'rejected')
    authority = c | {'authoritative_adjudication': record}
    check('裁决证据关联', evidence_error(identity, record, authority), None)
    bad = copy.deepcopy(record); bad['command_ref']['object_id'] = 'forged'; seal(bad)
    check('重算摘要不能伪CommandRef', evidence_error(identity, bad, authority), 'authority')
    bad = copy.deepcopy(record); bad['commit_ref']['object_id'] = 'forged'; seal(bad)
    check('重算摘要不能伪commit', evidence_error(identity, bad, authority), 'authority')
    bad = copy.deepcopy(record); bad['command_ref']['scope']['database_instance_id'] = 'other'; seal(bad)
    check('命令证据错Controller库', evidence_error(identity, bad, authority), 'scope')
    check('没有持久权威不收裁决', evidence_error(identity, record, authority | {'durable_provider_verified': False}), 'authority')
    check('HTTP操作到持久操作显式映射', api['paths']['/api/v1/commands']['post']['x-original-operation-id'], 'createCommand')
    for path, item in api['paths'].items():
        op = item['post']
        check(path + '认证', op['security'], [{'bearerAuth': []}])
        check(path + '版本', op['parameters'][0]['schema'], {'const': VERSION})
        check(path + '禁止缓存', all(v['headers']['Cache-Control']['schema'] == {'const': 'no-store'}
                                   for v in op['responses'].values()), True)
        node = {'$schema': schema['$schema'], 'components': api['components'],
                **op['requestBody']['content']['application/json']['schema']}
        validator = Draft202012Validator(node, format_checker=FormatChecker())
        sample = {'submitCommand': q, 'lookupCommandAdmission': identity,
                  'rejectCommandAdmission': reject_request}[op['operationId']]
        check(path + '投影正例', validator.is_valid(sample), True)
        check(path + '投影反例', validator.is_valid(sample | {'unexpected': True}), False)
    return dict(all_passed=True, approved=False, checks=len(results), results=results,
        limitations=['权威命名空间、归属和门控为人工夹具', '字典原子步仅表示两个串行顺序',
                     '提交前故障与响应丢失为人工切点，不证明真实WAL或网络',
                     '未执行参数二次校验、准备提供者、完整SQL与公共其他路由'],
        runtime_validation=dict(http=0, authentication=0, sqlite=0, concurrency=0, device=0))


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
        print('8份输入字节绑定一致；未重跑检查')
    else:
        result = run()
        result['input_sha256'] = hashes()
        if args.report:
            REPORT.write_bytes(encoded(result))
        print(json.dumps({k: result[k] for k in ('all_passed', 'approved', 'checks')}))
