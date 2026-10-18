"""校验DF01局部设计元数据；不实现或运行严格JSON解码器。"""
import copy
import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent


def metadata_errors(value, schema):
    if not Draft202012Validator(schema).is_valid(value):
        return {'schema'}
    errors = set()
    profiles = [p['profile_id'] for p in value['profiles']]
    if len(profiles) != len(set(profiles)):
        errors.add('duplicate_profile')
    for p in value['profiles']:
        if not p['max_key_utf8_bytes'] <= p['max_string_utf8_bytes'] <= p['max_message_bytes']:
            errors.add('budget_order')
    operations = set()
    for op in value['http']:
        key = (op['service'], op['operation_id'])
        if key in operations:
            errors.add('duplicate_operation')
        operations.add(key)
        if op['source_path'] != 'http/' + op['service'] + '.operations.json':
            errors.add('service_source')
        for ref in (op['request_profile'], op['response_profile']):
            if ref is not None and ref not in profiles:
                errors.add('unknown_profile')
    upgrades = set()
    for ws in value['websocket']:
        key = (ws['service'], ws['upgrade_operation_id'])
        if key not in operations:
            errors.add('unknown_upgrade')
        if key in upgrades:
            errors.add('duplicate_upgrade')
        upgrades.add(key)
        if ws['profile_ref'] not in profiles:
            errors.add('unknown_profile')
    return errors


def check():
    schema = json.loads((ROOT/'decoder-design.schema.json').read_text(encoding='utf-8'))
    cases = json.loads((ROOT/'decoder-design-cases.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    ids = set()
    for case in cases['metadata_cases']:
        assert case['id'] not in ids
        ids.add(case['id'])
        value = copy.deepcopy(cases['base'])
        for path, replacement in case['set']:
            target = value
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = replacement
        actual = metadata_errors(value, schema)
        assert (not actual) == case['valid'], (case['id'], actual)
        if not case['valid']:
            assert case['error'] in actual, (case['id'], actual)
    # 这里只检查原始夹具的唯一性、承载和预期标签，不运行候选扫描器。
    for case in cases['raw_cases_planned']:
        assert case['id'] not in ids
        ids.add(case['id'])
        assert ('raw' in case) != ('raw_hex' in case)
        raw = bytes.fromhex(case['raw_hex']) if 'raw_hex' in case else case['raw'].encode('utf-8')
        assert raw and type(case['accept']) is bool
        assert case['accept'] or case.get('reason')
        if case['root'] == 'schema':
            Draft202012Validator.check_schema(case['test_schema'])
    return {'metadata_cases_passed': len(cases['metadata_cases']),
            'raw_fixture_descriptions_checked': len(cases['raw_cases_planned']),
            'raw_decoder_cases_executed': 0, 'sdk_parser_implemented': False,
            'openapi_source_links_resolved': False}


if __name__ == '__main__':
    print(json.dumps(check(), ensure_ascii=False, indent=2))
