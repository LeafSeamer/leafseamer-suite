"""固定发布原件与动态校验的合成串联；不接入生产权威或发送。"""
import copy
import importlib.util
from importlib.metadata import version
import json
from pathlib import Path
import sys
import sqlite3


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(root):
    publication = root / 'contracts/publication-source'
    dynamic = root / 'contracts/panel-dynamic'
    sys.path.insert(0, str(publication))
    import store as S
    PF = load('publication_fixture', publication / 'fixtures.py')
    sys.path.insert(0, str(dynamic))
    import provider as P
    F = load('dynamic_fixture', dynamic / 'fixtures.py')
    checks = []

    def check(name, value):
        if not value:
            raise AssertionError(name)
        checks.append(dict(name=name, passed=True))

    def denied(name, reason, fn):
        try:
            fn()
        except ValueError as error:
            check(name, str(error) == reason)
        else:
            raise AssertionError(name + ':未拒绝')

    calls = 0
    original = P.instance

    def instance(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    P.instance = instance
    db = S.connect()
    try:
        frozen = PF.example()
        db.execute('BEGIN IMMEDIATE')
        check('事务追加原件', S.append(db, frozen) == 'inserted')
        db.execute('COMMIT')
        record = S.read(db, frozen['published'])
        check('按完整发布身份读取', record == frozen)
        latest = copy.deepcopy(frozen['source'])
        latest['metadata_revision'] = '12'
        latest['metadata']['name'] = '后来修改的名称'
        latest['content']['program']['groups'][0]['steps'][0]['delay_ms'] = 10
        check('新草稿不替换冻结内容', S.read(db, frozen['published'])['source'] != latest)
        value = {k: record['source'][k] for k in ['content', 'metadata']}
        defs = copy.deepcopy(S.SCHEMA['$defs'])
        # 本探针专用批准文档收紧开放layout，不能冒充生产模板批准。
        defs['lifecycle__DefinitionMetadata']['properties']['layout'] = F.obj(position=F.obj(x={'type': 'integer'}, y={'type': 'integer'}))
        defs['Value'] = F.obj(content={'$ref': '#/$defs/lifecycle__DraftContent'}, metadata={'$ref': '#/$defs/lifecycle__DefinitionMetadata'})
        doc = {'$schema': P.B.DIALECT, '$id': F.FORM, '$defs': defs}
        patterns = set()

        def visit(node):
            if not isinstance(node, dict):
                return
            if 'pattern' in node:
                patterns.add(node['pattern'])
            for key in P.B.MAP & node.keys():
                for child in node[key].values():
                    visit(child)
            for key in P.B.ARRAY & node.keys():
                for child in node[key]:
                    visit(child)
            for key in P.B.SINGLE & node.keys():
                visit(node[key])

        visit(doc)
        fixture = F.fixture(value=value, documents={F.FORM: doc}, profile=P.profile(patterns=patterns))
        fixture['manifest']['exports'][0]['purpose'] = 'definition'
        fixture['manifest'].pop('manifest_digest')
        fixture['manifest']['manifest_digest'] = P.digest(fixture['manifest'])
        context = fixture['context']
        method_input = dict(definition_id=frozen['published']['definition_id'], expected_draft_revision=frozen['source']['revision'],
                            expected_content_digest=frozen['source']['content_digest'], expected_selection_digest=frozen['source']['selection_digest'])
        P.shape('panel3__Input_seamer_publishDefinition', method_input)
        context.update(method='seamer.publishDefinition', slot='/publication-source', purpose='definition', input_digest=P.digest(method_input))
        context['activation_ref']['bundle_ref']['manifest_digest'] = fixture['manifest']['manifest_digest']
        # epoch由本合成宿主给出，原件格式不提供它；这不是生产来源认证。
        context['source_ref'].update(**frozen['published']['scope'], entity_kind='publication_source', entity_id='definition.3', revision='1', content_digest=frozen['record_digest'].removeprefix('sha256:'))
        authority = F.authority(fixture)
        candidate = authority.prepare(context, fixture['qualified'])
        fixture['qualified']['value']['metadata']['name'] = '调用者后改'
        output = authority.consume(context, candidate)
        check('实际子进程校验冻结内容与元数据', output['value'] == {k: frozen['source'][k] for k in ['content', 'metadata']})
        denied('消费候选不可重放', 'candidate_binding', lambda: authority.consume(context, candidate))
        fixture['qualified'] = copy.deepcopy(output)
        for field in ['content', 'metadata']:
            bad = copy.deepcopy(output)
            bad['value'].pop(field)
            denied('缺少' + field + '拒绝', 'instance_invalid', lambda bad=bad: authority.prepare(context, bad))
        bad = copy.deepcopy(output)
        bad['value']['metadata']['layout']['position']['x'] = '错误类型'
        denied('嵌套元数据类型拒绝', 'instance_invalid', lambda: authority.prepare(context, bad))
        limited = copy.deepcopy(fixture)
        limited['paths'].remove('/metadata/name')
        denied('缺少叶字段权限拒绝', 'field_denied', lambda: F.authority(limited).prepare(context, output))
        wrong = copy.deepcopy(output)
        wrong['schema_ref']['schema_digest'] = '0' * 64
        denied('错整文档摘要拒绝', 'export_binding', lambda: authority.prepare(context, wrong))
        other = copy.deepcopy(context)
        other['source_ref']['revision'] = '2'
        denied('错来源上下文拒绝', 'authority_stale', lambda: authority.prepare(other, output))
        candidate = authority.prepare(context, output)
        authority.revoke()
        denied('撤权后拒绝消费', 'authority_stale', lambda: authority.consume(context, candidate))
        wrong = copy.deepcopy(frozen['published'])
        wrong['published_by'] = 'other.publisher'
        denied('错完整发布对象拒绝', 'published_binding', lambda: S.read(db, wrong))
        db.execute('BEGIN IMMEDIATE')
        new = copy.deepcopy(frozen['published'])
        new['definition_version'] = '4'
        new['artifact_ref']['object_id'] = 'artifact.other'
        S.append(db, S.freeze(new, frozen['source']))
        db.execute('ROLLBACK')
        denied('回滚原件不可读取', 'source_unavailable', lambda: S.read(db, new))
        check('失败不改变已提交原件', S.read(db, frozen['published']) == frozen)
        check('真实校验调用数', calls == 5)
        return dict(all_passed=True, cases_passed=len(checks), checks=checks, validator_subprocess_calls=calls,
                    tools={name: version(name) for name in ['jsonschema', 'referencing', 'rfc8785']}, sqlite_version=sqlite3.sqlite_version,
                    sqlite_memory_scenarios=1, synthetic_host=True, production_authority_tests_executed=0,
                    production_publication_tests_executed=0, production_projection_tests_executed=0,
                    final_output_gate_tests_executed=0, worker_memory_limit_tests_executed=0,
                    network_tests_executed=0, browser_tests_executed=0, device_tests_executed=0)
    finally:
        db.close()
        P.instance = original


if __name__ == '__main__':
    print(json.dumps(run(Path(sys.argv[1]).resolve()), ensure_ascii=False))
