"""从局部纯数据候选源重组历史draft.4；不导入Suite生成器或实现产品SDK。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
OUTPUTS = ('first-loop.schema.json', 'ipc.schema.json', 'controller.openapi.json',
           'seamer.openapi.json', 'routes.json', 'examples.json')
METHODS = {'get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'}
SECURITY = {'bearer': [{'bearerAuth': []}], 'cookie': [{'sessionCookie': [], 'csrfHeader': []}],
            'mtls': [{'serviceMtls': []}], 'bootstrap': [], 'login': []}


def unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('重复JSON键')
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非法JSON数值')))


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_path(root, name):
    p = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts or p.as_posix() != name:
        raise ValueError('非法源路径')
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('源文件经链接越界')
    return target


def load_source(root):
    manifest = decode((root / 'source-manifest.json').read_bytes())
    fields = {'purpose', 'authority_switched', 'source_repository', 'source_commit', 'source_directory',
              'public_protocol', 'ipc_protocol', 'license_provenance_paths', 'files', 'expected_outputs', 'not_extracted'}
    if set(manifest) != fields:
        raise ValueError('未消费或缺失的manifest字段')
    if manifest['purpose'] != 'draft4-equivalence-candidate' or manifest['authority_switched'] is not False:
        raise ValueError('候选用途或权威状态不符')
    files = {}
    folded = set()
    for item in manifest['files']:
        if set(item) != {'path', 'sha256'}:
            raise ValueError('文件记录字段不符')
        name = item['path']
        if name.casefold() in folded:
            raise ValueError('重复或大小写冲突路径')
        folded.add(name.casefold())
        raw = source_path(root, name).read_bytes()
        if sha(raw) != item['sha256']:
            raise ValueError('源文件摘要不符: ' + name)
        files[name] = decode(raw)
    required = {'public.schema.json', 'ipc.schema.json', 'fixtures.json', 'route-projection.json',
                'schema-registry.json', 'http/controller.operations.json', 'http/seamer.operations.json'}
    if set(files) != required or set(manifest['expected_outputs']) != set(OUTPUTS):
        raise ValueError('候选文件集合不完整或含意外文件')
    return manifest, files


def pointer(value, fragment):
    if fragment == '':
        return value
    if not fragment.startswith('/'):
        raise ValueError('候选只允许JSON Pointer引用')
    for token in fragment[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def walk(value, path=''):
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, path + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from walk(item, path + '/' + str(i))


def rewrite_refs(value):
    # 只改Schema的引用关键字，不全局替换description/example中的文本。
    if isinstance(value, list):
        return [rewrite_refs(v) for v in value]
    if isinstance(value, dict):
        return {k: (v.replace('#/$defs/', '#/components/schemas/', 1)
                    if k == '$ref' and isinstance(v, str) and v.startswith('#/$defs/')
                    else rewrite_refs(v)) for k, v in value.items()}
    return value


def check_refs(document, registry):
    count = 0
    for _, node in walk(document):
        if not isinstance(node, dict) or '$ref' not in node:
            continue
        value = node['$ref']
        if not isinstance(value, str) or '#' not in value:
            raise ValueError('未注册引用')
        base, fragment = value.split('#', 1)
        target = document if not base else registry.get(base)
        if target is None:
            raise ValueError('禁止网络或未知源引用')
        try:
            pointer(target, fragment)
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise ValueError('引用目标不存在') from e
        count += 1
    return count


def schema_name(body):
    if body is None:
        return None
    value = body['content']['application/json']['schema']
    prefix = '#/components/schemas/'
    if set(value) != {'$ref'} or not value['$ref'].startswith(prefix):
        raise ValueError('旧routes投影只支持当前具名根；不得猜测复杂Schema')
    return value['$ref'][len(prefix):]


def assemble(files):
    public, ipc = files['public.schema.json'], files['ipc.schema.json']
    registry_data = files['schema-registry.json']
    if set(registry_data) != {'ids', 'legacy_openapi_component_order', 'component_projection_is_public_export_approval'} or registry_data['component_projection_is_public_export_approval'] is not False:
        raise ValueError('历史components不构成公开导出批准')
    expected_registry = {public['$id']: 'public.schema.json', ipc['$id']: 'ipc.schema.json'}
    if registry_data['ids'] != expected_registry:
        raise ValueError('Schema注册表与源$id不一致')
    names = registry_data['legacy_openapi_component_order']
    if names != list(public['$defs']):
        raise ValueError('历史模型投影漏项、重复或乱序')
    registry = {k: files[v] for k, v in expected_registry.items()}
    check_refs(public, registry)
    check_refs(ipc, registry)
    out = {'first-loop.schema.json': copy.deepcopy(public), 'ipc.schema.json': copy.deepcopy(ipc)}
    for service in ('controller', 'seamer'):
        api = copy.deepcopy(files['http/' + service + '.operations.json'])
        if 'schemas' in api['components']:
            raise ValueError('HTTP骨架不得手写第二份模型')
        api['components']['schemas'] = {name: rewrite_refs(public['$defs'][name]) for name in names}
        check_refs(api, registry)
        out[service + '.openapi.json'] = api
    routes, seen = [], set()
    for recipe in files['route-projection.json']:
        if set(recipe) != {'service', 'method', 'path', 'primary_success_status', 'legacy_security_label'}:
            raise ValueError('未消费或缺失的route投影字段')
        service, method, path = recipe['service'], recipe['method'], recipe['path']
        if service not in ('common', 'controller', 'seamer') or method not in METHODS:
            raise ValueError('非法历史route投影')
        services = ('controller', 'seamer') if service == 'common' else (service,)
        derived = []
        for current in services:
            key = current, path, method
            if key in seen:
                raise ValueError('重复操作投影')
            seen.add(key)
            api = out[current + '.openapi.json']
            op = api['paths'][path][method]
            security = recipe['legacy_security_label']
            if security not in SECURITY or op.get('security', api.get('security')) != SECURITY[security]:
                raise ValueError('投影安全类别与真实声明不符')
            status = recipe['primary_success_status']
            derived.append({'service': service, 'method': method, 'path': path, 'operation_id': op['operationId'],
                            'request': schema_name(op.get('requestBody')), 'response': schema_name(op['responses'][status]),
                            'status': status, 'permission': op['x-permission'], 'security': security})
        if any(r != derived[0] for r in derived[1:]):
            raise ValueError('共用操作投影不一致')
        routes.append(derived[0])
    # routes没有WS；它们必须独立存在，且x-*字段照原骨架保存。
    counts = {}
    for service in ('controller', 'seamer'):
        api = out[service + '.openapi.json']
        normal, websocket, ids = 0, 0, set()
        for path, item in api['paths'].items():
            for method, op in item.items():
                if method not in METHODS:
                    continue
                if op['operationId'] in ids:
                    raise ValueError('同服务operationId重复')
                ids.add(op['operationId'])
                if '101' in op['responses']:
                    websocket += 1
                    for field in ('x-ticket-binding-schema', 'x-websocket-frame-schema'):
                        value = op[field]
                        pointer(api, value[1:])
                    if op['security'] != [{'wsTicketHeader': []}]:
                        raise ValueError('WS票据安全声明改变')
                else:
                    normal += 1
                    if (service, path, method) not in seen:
                        raise ValueError('普通操作没有历史route投影')
        if websocket != 1:
            raise ValueError('历史每服务必须保留一个WS入口')
        counts[service] = {'http': normal, 'websocket': websocket}
    out['routes.json'] = routes
    out['examples.json'] = copy.deepcopy(files['fixtures.json'])
    return out, counts


def verify_outputs(manifest, out):
    if set(out) != set(OUTPUTS):
        raise ValueError('生成输出集合改变')
    for name, value in out.items():
        if sha(encode(value)) != manifest['expected_outputs'][name]:
            raise ValueError('历史输出字节不等价: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'source')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    manifest, files = load_source(args.source)
    out, counts = assemble(files)
    verify_outputs(manifest, out)
    if args.output:
        # 新目录限定，拒绝覆盖任何既有目录；失败前已完成全部检查。
        args.output.mkdir(parents=False, exist_ok=False)
        for name in OUTPUTS:
            (args.output / name).write_bytes(encode(out[name]))
    print(json.dumps({'scope': '候选纯数据独立重组，不运行语义判定器或生成产品SDK',
                      'byte_equal_outputs': len(out), 'models': len(out['first-loop.schema.json']['$defs']),
                      'ipc_messages': len(out['ipc.schema.json']['oneOf']), 'operations': counts,
                      'authority_switched': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
