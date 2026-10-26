"""固定Git对象交接核验；不执行SDK历史行为用例、网络推送或运行服务。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import rfc8785

ROOT = Path(__file__).resolve().parent
SUITE = ROOT.parents[2]


def require(ok, message):
    if not ok: raise ValueError(message)


def unique(items):
    value = {}
    for key, item in items:
        require(key not in value, '重复JSON键'); value[key] = item
    return value


def decode(raw):
    return json.loads(raw.decode('utf8'), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非有限JSON数值')))


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def path_name(name):
    p = PurePosixPath(name)
    require(bool(name) and '\\' not in name and ':' not in name and not p.is_absolute() and
            '..' not in p.parts and p.as_posix() == name, '非规范相对路径')
    return name


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo)


def read_fixed(repo, commit, names):
    require(re.fullmatch('[0-9a-f]{40}', commit), '必须固定完整提交')
    names = list(names)
    require(len(names) == len(set(names)), '重复固定路径')
    query = ''.join(commit + ':' + path_name(name) + '\n' for name in names)
    raw = subprocess.run(['git', 'cat-file', '--batch'], cwd=repo, input=query.encode(),
                         capture_output=True, check=True).stdout
    result = {}; offset = 0
    for name in names:
        end = raw.index(b'\n', offset); header = raw[offset:end].split()
        require(len(header) == 3 and header[1] == b'blob', '固定原件不是blob: ' + name)
        size = int(header[2]); result[name] = raw[end+1:end+1+size]
        require(len(result[name]) == size and raw[end+1+size:end+2+size] == b'\n', 'Git输出不完整')
        offset = end + 2 + size
    require(offset == len(raw), 'Git输出有尾随内容')
    return result


def validate_package(package, files):
    require(package['report'] in package['files'] and set(files) == set(package['files']), '交付集合缺项')
    for path, checksum in package['files'].items():
        require(sha(files[path]) == checksum, '固定文件摘要不符: ' + path)
    report = decode(files[package['report']])
    require(report['all_passed'] is True and report['approved'] is False and report['runtime_ready'] is False, '报告资格错误')
    require(report['cases_passed'] == len(report['checks']) and all(c['passed'] is True for c in report['checks']), '案例集合不完整')
    expected = dict(report['inputs']); expected[package['report']] = sha(files[package['report']])
    require(expected == package['files'], '报告输入与交付集合不一致')
    require(report['runtime_tests_executed'] == report['device_tests_executed'] == 0, '不得以离线交接宣称运行验收')
    return report


def validate_selection(files, expected):
    prefix = 'contracts/negotiation/'
    manifest = decode(files[prefix + 'preview/manifest.json'])
    selection = decode(files[prefix + 'preview/selection.json'])
    names = {'models.schema.json', 'controller.openapi.json', 'seamer.openapi.json', 'worker-ipc.schema.json',
             'worker-messages.json', 'routing.json', 'policy.json', 'PROTOCOL.md'}
    require(manifest['approved'] is False and set(manifest['artifacts']) == names, '规范产物集合或批准状态改变')
    require(manifest['artifact_digest_algorithm'] == 'sha256-bytes' and
            manifest['selection_digest_algorithm'] == 'sha256-jcs-manifest', '摘要算法不符')
    for name, checksum in manifest['artifacts'].items():
        path = prefix + ('' if name in ('policy.json', 'PROTOCOL.md') else 'preview/') + name
        require(sha(files[path]) == checksum, '规范产物摘要不符')
    require(selection == expected and selection['contract_id'] == manifest['contract_id'] and
            selection['contract_digest'] == 'sha256:' + sha(rfc8785.dumps(manifest)), '选择与清单不匹配')
    return selection


def numbers(reports, snapshots):
    read = lambda package, file: decode(snapshots[package]['contracts/' + package + '/' + file])
    im = read('integration', 'preview/models.schema.json')['$defs']
    nm = read('negotiation', 'preview/models.schema.json')['$defs']
    routing = read('negotiation', 'preview/routing.json')
    changed = {name for name in im if im[name] != nm[name]}
    require(changed == set(routing['changed_definitions']) and len(changed) == len(routing['changed_definitions']), '模型变化清单有遗漏或重复')
    require(all(im[n] == nm[n] for n in im if n.startswith('command__')), 'worker共用模型接受集改变')
    def operation_count(package, role):
        suffix = '.preview.openapi.json' if package == 'integration' else '.openapi.json'
        return sum(len(v) for v in read(package, 'preview/' + role + suffix)['paths'].values())
    return dict(integration_models=len(im), command_models=sum(n.startswith('command__') for n in im),
        integration_http_operations=sum(operation_count('integration', r) for r in ('controller', 'seamer')),
        integration_worker_types=len(read('integration', 'preview/worker-ipc.schema.json')['oneOf']),
        integration_cases=reports['integration']['cases_passed'], negotiation_models=len(nm),
        negotiation_http_operations=sum(operation_count('negotiation', r) for r in ('controller', 'seamer')),
        controller_operations=operation_count('negotiation', 'controller'), seamer_operations=operation_count('negotiation', 'seamer'),
        ordinary_http_operations=sum(x['transport'] == 'http' for x in routing['operations']),
        ws_operations=sum(x['transport'] == 'websocket' for x in routing['operations']), discovery_operations=routing['discovery_operations'],
        changed_definitions=len(changed), baseline_protocol_definitions=sum('protocol_version' in nm[n].get('properties', {}) for n in changed),
        negotiation_cases=reports['negotiation']['cases_passed'])


def local_inputs():
    paths = [p for p in ROOT.iterdir() if p.is_file() and p.name != 'report.json']
    paths += [SUITE / 'docs' / p for p in ('rebirth-df01-sdk-freeze.md', 'rebirth-design-closure.md', 'rebirth-readiness.md', 'rebirth-c12-deployment-design.md',
                                         'contracts/df01/reference-report.json')]
    reference = decode((SUITE / 'docs/contracts/df01/reference-report.json').read_bytes())
    require(reference['all_passed'] is True and reference['sdk_toolchain_executed'] is False, 'DF01参考结果或边界不符')
    for path, checksum in reference['input_sha256'].items():
        p = SUITE / 'docs' / path_name(path)
        require(sha(p.read_bytes()) == checksum, 'DF01参考输入漂移')
        paths.append(p)
    return {p.relative_to(SUITE).as_posix(): sha(p.read_bytes()) for p in sorted(set(paths))}


def run(sdk):
    manifest = decode((ROOT / 'manifest.json').read_bytes())
    require(manifest['format'] == 'sdk-transport-handoff/1', '交接格式不符')
    for repo, expected in ((sdk, manifest['sdk_repository']), (SUITE, manifest['suite_repository'])):
        require(git(repo, 'remote', 'get-url', 'origin').decode().strip() == expected, '仓库归属不符')
    packages = manifest['packages']
    require([p['name'] for p in packages] == ['integration', 'negotiation'] and
            manifest['sdk_main_commit'] == packages[1]['commit'], '交付包或消费提交不符')
    snapshots = {}; reports = {}
    for package in packages:
        require(subprocess.run(['git', 'merge-base', '--is-ancestor', package['commit'], 'main'], cwd=sdk,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0, 'SDK main不包含交付')
        files = read_fixed(sdk, package['commit'], package['files'])
        reports[package['name']] = validate_package(package, files); snapshots[package['name']] = files
    require(subprocess.run(['git', 'merge-base', '--is-ancestor', packages[0]['commit'], packages[1]['commit']], cwd=sdk,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0, 'SDK交付顺序不符')
    read = lambda group, file: decode(snapshots[group]['contracts/' + group + '/' + file])
    ir, provenance, nr = read('integration', 'sources.json'), read('integration', 'source/frames-provenance.json'), read('negotiation', 'sources.json')
    require(ir['source_repository'] == provenance['source_repository'] == manifest['suite_repository'].removesuffix('.git') and
            nr['source_repository'] == manifest['sdk_repository'].removesuffix('.git'), '来源归属错误')
    expected_anchors = {}
    def anchor(repository, commit, path, checksum):
        key = repository, commit, path_name(path)
        require(key not in expected_anchors or expected_anchors[key] == checksum, '来源锚点冲突')
        expected_anchors[key] = checksum
    for item in ir['source_files'].values(): anchor('suite', ir['source_commit'], item['source_path'], item['sha256'])
    for path, checksum in provenance['source_inputs'].items(): anchor('suite', provenance['source_commit'], path, checksum)
    for path, checksum in ir['base_inputs'].items(): anchor('sdk', ir['base_sdk_commit'], path, checksum)
    for path, checksum in nr['inputs'].items(): anchor('sdk', nr['source_commit'], path, checksum)
    actual = {(a['repository'], a['commit'], a['path']): a['sha256'] for a in manifest['source_anchors']}
    require(actual == expected_anchors and len(actual) == len(manifest['source_anchors']), '来源锚点遗漏或重复')
    groups = {}
    for (repository, commit, path), checksum in actual.items(): groups.setdefault((repository, commit), {})[path] = checksum
    for (repository, commit), paths in groups.items():
        source = read_fixed({'sdk': sdk, 'suite': SUITE}[repository], commit, paths)
        require(all(sha(source[p]) == h for p, h in paths.items()), '固定来源原件不符')
    counts = numbers(reports, snapshots)
    require(counts == manifest['expectations'], '交付数量与真实原件不一致')
    selection = validate_selection(snapshots['negotiation'], manifest['selection'])
    require(reports['negotiation']['browser_tests_executed'] == reports['negotiation']['concurrent_ticket_tests_executed'] == 0,
            '不能把串行关系模型标为浏览器或并发验收')
    require(manifest['boundaries'] == dict(stage0_complete=False, production_sdk_ready=False,
            business_implementation_started=False, runtime_protocol_frozen=False), '交接擅自改变阶段边界')
    cycle = manifest['cycle']
    require(cycle == dict(rounds=[dict(round=i, repository='leafseamer-sdk', commit=p['commit']) for i,p in enumerate(packages,1)] +
        [dict(round=3, repository='leafseamer-suite', commit='containing-commit')], push_order=['leafseamer-sdk','leafseamer-suite']), '周期归属或推送顺序改变')
    negatives = []
    def rejected(name, action):
        try: action()
        except (ValueError, KeyError): negatives.append(name)
        else: raise AssertionError(name + ':应拒绝')
    first = packages[0]; original = snapshots['integration']
    bad = dict(original); bad[first['report']] += b' '
    rejected('报告原件被改写', lambda: validate_package(first, bad))
    p = copy.deepcopy(first); p['files'].pop(next(k for k in p['files'] if k != p['report']))
    rejected('交付遗漏输入', lambda: validate_package(p, {k: original[k] for k in p['files']}))
    changed = decode(original[first['report']]); changed['cases_passed'] += 1
    altered = dict(original); altered[first['report']] = encode(changed)
    p = copy.deepcopy(first); p['files'][first['report']] = sha(altered[first['report']])
    rejected('重算报告摘要仍拒绝案例数量伪标', lambda: validate_package(p, altered))
    rejected('伪造选择摘要', lambda: validate_selection(snapshots['negotiation'], dict(selection, contract_digest='sha256:'+'0'*64)))
    altered = dict(snapshots['negotiation']); key = 'contracts/negotiation/PROTOCOL.md'; altered[key] += b' '
    rejected('规范字节替换不得保留选择', lambda: validate_selection(altered, selection))
    for name in ('../escape', '/absolute', 'C:/absolute', 'a//b', 'a\\b'):
        rejected('非法路径:' + name, lambda name=name: path_name(name))
    rejected('浮动提交不作来源', lambda: read_fixed(sdk, 'main', ['README.md']))
    return dict(format='sdk-transport-handoff-report/1', all_passed=True, sdk_main_commit=manifest['sdk_main_commit'],
        fixed_sdk_files=sum(len(p['files']) for p in packages), sdk_report_inputs=sum(len(r['inputs']) for r in reports.values()),
        source_anchors=len(actual), source_anchors_by_repository={r:sum(k[0]==r for k in actual) for r in ('sdk','suite')},
        verified_numbers=counts, selection=selection, rejected_mutations=negatives, stage0_complete=False,
        scope='固定Git对象、来源和输入绑定；不重跑SDK历史用例，不证明远端推送或运行服务', input_sha256=local_inputs())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--sdk', type=Path)
    group=parser.add_mutually_exclusive_group(); group.add_argument('--report',action='store_true'); group.add_argument('--check-report',action='store_true')
    args=parser.parse_args()
    if args.check_report:
        if args.sdk: parser.error('--check-report不读取SDK')
        report=decode((ROOT/'report.json').read_bytes());require(report['input_sha256']==local_inputs(),'本仓报告输入漂移')
        print(json.dumps(dict(all_passed=True,matched_bindings=len(report['input_sha256']),scope='仅本仓输入绑定')))
    else:
        if not args.sdk: parser.error('固定提交核验需要--sdk')
        report=run(args.sdk.resolve())
        if args.report:(ROOT/'report.json').write_bytes(encode(report))
        print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'},ensure_ascii=False))
