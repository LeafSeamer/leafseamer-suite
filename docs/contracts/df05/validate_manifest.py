"""DF05 离线格式与关联参考检查；不加载制品、不联网、不验证发布授权。"""
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('重复 JSON 键')
        result[key] = value
    return result


def load(name):
    raw = (ROOT / name).read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('参考输入超过 4 MiB')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def contract_errors(value):
    errors = []
    files = {item['path']: item for item in value['artifacts']}
    seen = set()
    for item in value['artifacts']:
        path = item['path']
        folded = path.lower()
        if folded in seen:
            errors.append('路径碰撞')
        seen.add(folded)
        for segment in path.split('/'):
            stem = segment.split('.')[0].lower()
            if segment.endswith('.') or re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])', stem):
                errors.append('平台保留路径')
        native = item['role'] == 'native_addon'
        if native != (item['abi']['kind'] != 'none'):
            errors.append('ABI 与文件角色不符')

    def need(path, roles=None):
        item = files.get(path)
        if item is None or (roles is not None and item['role'] not in roles):
            errors.append('文件引用缺失或角色不符: ' + str(path))

    need(value['runtime']['artifact_path'], {'runtime'})
    need(value['build']['toolchain_manifest_path'], {'build_metadata'})
    need(value['target']['tested_environment_ref'], {'report'})
    for capability in value['capabilities'].values():
        need(capability['report_path'], {'report'})
    for name, role in [('sbom_path', 'sbom'), ('license_bundle_path', 'license'),
                       ('acceptance_path', 'report'), ('provenance_path', 'provenance')]:
        need(value['reports'][name], {role})
    for dependency in value['dynamic_dependencies']:
        if dependency['kind'] == 'bundled':
            need(dependency['artifact_path'])
        else:
            need(dependency['environment_report_path'], {'report'})
    target = value['target']
    if (target['os'] == 'windows') != (target['libc'] is None):
        errors.append('OS 与 libc 不符')
    if target['container_image_digest'] is not None and target['os'] != 'linux':
        errors.append('首期无 Windows 容器 profile')
    for db in value['db_compatibility'].values():
        if not set(db['write_schema_revisions']) <= set(db['read_schema_revisions']):
            errors.append('可写修订必须可读')
    reproducibility = value['reproducibility']
    verified = reproducibility['status'] == 'verified'
    if verified != (reproducibility['report_path'] is not None):
        errors.append('复现状态与报告不符')
    if reproducibility['report_path'] is not None:
        need(reproducibility['report_path'], {'report'})
    if value['channel'] == 'stable' and not verified:
        errors.append('未复现候选不能标 stable')
    return errors


def main():
    schema = load('release-manifest.schema.json')
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    fixtures = load('examples.json')
    assert fixtures['purpose'] == 'synthetic-only-no-payload-no-signatures'
    results = []
    for case in fixtures['cases']:
        value = copy.deepcopy(fixtures['base'])
        for change in case['changes']:
            parent = value
            for part in change['path'][:-1]:
                parent = parent[part]
            if change['op'] == 'delete':
                del parent[change['path'][-1]]
            elif change['op'] == 'set':
                parent[change['path'][-1]] = change['value']
            else:
                raise ValueError('未知夹具操作')
        schema_valid = validator.is_valid(value)
        contract_valid = schema_valid and not contract_errors(value)
        assert schema_valid == case['schema_valid'], case['id'] + ': Schema 预期不符'
        assert contract_valid == case['contract_valid'], case['id'] + ': 关联预期不符'
        results.append({'id': case['id'], 'schema_valid': schema_valid,
                        'contract_valid': contract_valid, 'passed': True})
    report = {
        'purpose': 'synthetic-schema-and-reference-only', 'all_passed': True,
        'case_count': len(results), 'release_authorized': False,
        'tool_versions': {'python': platform.python_version(), **{
            name: importlib.metadata.version(name) for name in [
                'jsonschema', 'rfc3339-validator', 'attrs', 'jsonschema-specifications',
                'referencing', 'rpds-py', 'six']}},
        'artifact_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                            for name in ['release-manifest.schema.json', 'examples.json', 'validate_manifest.py']},
        'runtime_validation': {'tuf_client': 0, 'signatures': 0, 'artifact_bytes': 0,
                               'native_loading': 0, 'installation': 0, 'crash_recovery': 0},
        'cases': results,
    }
    (ROOT / 'reference-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'all_passed': True, 'case_count': len(results), 'release_authorized': False}))


if __name__ == '__main__':
    main()
