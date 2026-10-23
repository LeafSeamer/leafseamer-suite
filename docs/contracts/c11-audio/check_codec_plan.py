"""只读校验DM3编码审阅计划；不解析RCP报文、不授权或连接设备。"""
import copy
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def plan_errors(plan, schema, inventory, inventory_hash):
    if not Draft202012Validator(schema).is_valid(plan):
        return {'schema'}
    errors = set()
    if plan['source_inventory_sha256'] != inventory_hash:
        errors.add('source_digest')
    sources = {e['index']: e for e in inventory['entries']}
    if len(sources) != inventory['entry_count']:
        raise ValueError('来源目录身份不唯一或计数不符')
    ids, seen = set(), set()
    projections = {
        'integer_decimal': ('raw_integer', 'unqualified'),
        'text_bytes_candidate': ('unresolved', 'not_applicable'),
        'binary_unresolved': ('unresolved', 'not_applicable'),
        'secret_ref_candidate': ('secret_ref_only', 'not_applicable'),
        'text_or_enum_unresolved': ('unresolved', 'not_applicable'),
        'scene_absolute': ('scene_reference', 'not_applicable'),
        'scene_relative': ('direction', 'not_applicable'),
        'meter_hex_candidate': ('raw_meter', 'unqualified'),
    }
    kinds = {
        'integer_decimal': ('prminfo', 'integer'),
        'text_bytes_candidate': ('prminfo', 'binary'),
        'binary_unresolved': ('prminfo', 'binary'),
        'secret_ref_candidate': ('prminfo', 'binary'),
        'text_or_enum_unresolved': ('prminfo', 'string'),
        'scene_absolute': ('scninfo', 'integer'),
        'scene_relative': ('scninfo', 'none'),
        'meter_hex_candidate': ('mtrinfo', 'mtr'),
    }
    for group in plan['groups']:
        if group['id'] in ids:
            errors.add('duplicate_group')
        ids.add(group['id'])
        family = group['family']
        if (group['value_projection'], group['units']) != projections[family]:
            errors.add('family_projection')
        for index in group['source_indices']:
            if index in seen:
                errors.add('duplicate_source')
            seen.add(index)
            source = sources.get(index)
            if source is None:
                errors.add('unknown_source')
                continue
            if (source['action'], source['value_type']) != kinds[family]:
                errors.add('family_source')
            # 固定来源119为明确审阅过的秘密项，不能靠运行时路径猜敏感性。
            if index == 119:
                if (family, group['value_projection'], group['redaction']) != (
                    'secret_ref_candidate', 'secret_ref_only', 'no_value_capture'
                ):
                    errors.add('secret_projection')
            elif family == 'secret_ref_candidate' or group['redaction'] != 'standard':
                errors.add('secret_projection')
            # 这些条目已逐一审阅为Name候选；binary的其他项不自动当文本。
            names = {5, 30, 48, 67, 91, 107, 118}
            if (index in names) != (family == 'text_bytes_candidate'):
                errors.add('family_source')
    if seen != set(sources):
        errors.add('coverage')
    return errors


def main():
    schema = load('dm3-codec-plan.schema.json')
    inventory = load('dm3-legacy-catalog.json')
    plan = load('dm3-codec-plan.json')
    cases = load('dm3-codec-cases.json')['cases']
    inventory_hash = hashlib.sha256((ROOT / 'dm3-legacy-catalog.json').read_bytes()).hexdigest()
    Draft202012Validator.check_schema(schema)
    ids = set()
    for case in cases:
        assert case['id'] not in ids
        ids.add(case['id'])
        candidate = copy.deepcopy(plan)
        for path, value in case['set']:
            target = candidate
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
        actual = plan_errors(candidate, schema, inventory, inventory_hash)
        assert (not actual) == case['valid'], (case['id'], actual)
        if not case['valid']:
            assert case['error'] in actual, (case['id'], actual)
    assert not plan_errors(plan, schema, inventory, inventory_hash)
    print(json.dumps({'scope': '审阅计划结构与来源覆盖，非RCP编码或运行验收',
                      'source_entries': len(inventory['entries']),
                      'review_groups': len(plan['groups']), 'cases_passed': len(cases),
                      'runtime_approved': False, 'rcp_parser_cases_executed': 0,
                      'device_tests_executed': 0}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
