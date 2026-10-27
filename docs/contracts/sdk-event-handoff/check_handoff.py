"""固定快照投影与订阅通道交接；不执行真实服务或宣称运行资格。"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
SUITE = ROOT.parents[2]
HELPER = ROOT.parent / 'sdk-transport-handoff/check_handoff.py'
spec = importlib.util.spec_from_file_location('transport_handoff', HELPER)
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


def inspect_graph(projection, channel, api, policy):
    p, c = projection['$defs'], channel['$defs']
    H.require(all(name in c and c[name] == value for name, value in p.items()), '快照图漂移')
    H.require(api['x-approved'] is False and api['x-advertisable'] is False, '候选被批准或广告')
    H.require(policy['approved'] is False and policy['runtime_ready'] is False and
              policy['requires_new_full_contract_selection'] is True, '通道被误当旧组合')
    actual = []
    for path, item in api['paths'].items():
        for method, operation in item.items():
            H.require(method in ('get', 'post', 'delete'), '未知操作')
            profile = 'service' if path.startswith('/internal/') else 'human'
            actual.append(dict(profile=profile, method=method, path=path, operation_id=operation['operationId']))
            if profile == 'service':
                security = [{'serviceMtls': []}]
            elif path == '/api/v1/events':
                security = [{'wsTicketHeader': []}]
            else:
                security = [{'humanBearer': [], **({'csrfHeader': []} if method != 'get' else {})}]
            H.require(operation['security'] == security, '人员与服务认证边界漂移')
    key = lambda value: (value['path'], value['method'])
    H.require(sorted(actual, key=key) == sorted(policy['operations'], key=key), '操作映射缺失或重复')
    H.require(len({v['operation_id'] for v in actual}) == len(actual), '操作身份重复')
    return dict(projection_models=len(p), channel_models=len(c), operations=len(actual),
                human_operations=sum(v['profile'] == 'human' for v in actual),
                service_operations=sum(v['profile'] == 'service' for v in actual))


def source_anchors(sources):
    anchors = {}
    def add(repo, commit, path, checksum):
        key = (repo, commit, H.path_name(path))
        H.require(key not in anchors or anchors[key] == checksum, '来源锚点冲突')
        anchors[key] = checksum
    for name, source in sources.items():
        H.require(source['suite_repository'] == 'https://github.com/LeafSeamer/leafseamer-suite' and
                  source['approved'] is False, '来源归属或批准状态改变')
        if name == 'event-projection':
            for file in source['source_files'].values():
                add('suite', source['suite_commit'], file['path'], file['sha256'])
        else:
            add('suite', source['suite_commit'], source['source_path'], source['source_sha256'])
        for path, checksum in source['inputs'].items():
            add('sdk', source['sdk_commit'], path, checksum)
    return anchors


def local_inputs():
    paths = [p for p in ROOT.iterdir() if p.is_file() and p.name != 'report.json']
    paths += [HELPER, SUITE / 'docs/rebirth-design-closure.md', SUITE / 'docs/rebirth-readiness.md',
              SUITE / 'docs/rebirth-df01-sdk-freeze.md', SUITE / 'docs/rebirth-c05-event-sync-design.md']
    reference_path = SUITE / 'docs/contracts/df01/reference-report.json'
    reference = H.decode(reference_path.read_bytes())
    H.require(reference['all_passed'] is True and reference['sdk_toolchain_executed'] is False,
              'DF01参考结果或边界错误')
    paths.append(reference_path)
    for path, checksum in reference['input_sha256'].items():
        source = SUITE / 'docs' / H.path_name(path)
        H.require(H.sha(source.read_bytes()) == checksum, 'DF01输入漂移')
        paths.append(source)
    return {p.relative_to(SUITE).as_posix(): H.sha(p.read_bytes()) for p in sorted(set(paths))}


def run(sdk):
    manifest = H.decode((ROOT / 'manifest.json').read_bytes())
    H.require(manifest['format'] == 'sdk-event-handoff/1', '交接格式不符')
    for repo, url in ((sdk, manifest['sdk_repository']), (SUITE, manifest['suite_repository'])):
        H.require(H.git(repo, 'remote', 'get-url', 'origin').decode().strip() == url, '仓库归属不符')
    packages = manifest['packages']
    H.require([p['name'] for p in packages] == ['event-projection', 'event-channel'], '交接范围改变')
    H.require(manifest['sdk_main_commit'] == packages[-1]['commit'], 'SDK消费提交不符')
    snapshots, reports = {}, {}
    for package in packages:
        H.require(subprocess.run(['git', 'merge-base', '--is-ancestor', package['commit'], 'main'], cwd=sdk,
                  capture_output=True).returncode == 0, 'SDK main缺少交付')
        files = H.read_fixed(sdk, package['commit'], package['files'])
        report = H.validate_package(package, files)
        H.require(all(value == 0 for key, value in report.items() if key.endswith('_tests_executed')),
                  '不得将离线检查标作真实运行')
        snapshots[package['name']], reports[package['name']] = files, report
    H.require(subprocess.run(['git', 'merge-base', '--is-ancestor', packages[0]['commit'], packages[1]['commit']],
              cwd=sdk, capture_output=True).returncode == 0, '提交顺序不符')
    def read(group, file):
        return H.decode(snapshots[group]['contracts/' + group + '/' + file])
    anchors = source_anchors({name: read(name, 'sources.json') for name in snapshots})
    declared = {(a['repository'], a['commit'], a['path']): a['sha256'] for a in manifest['source_anchors']}
    H.require(declared == anchors and len(declared) == len(manifest['source_anchors']), '来源清单缺失或重复')
    groups = {}
    for (repo, commit, path), checksum in anchors.items():
        groups.setdefault((repo, commit), {})[path] = checksum
    for (repo, commit), files in groups.items():
        actual = H.read_fixed({'sdk': sdk, 'suite': SUITE}[repo], commit, files)
        H.require(all(H.sha(actual[p]) == h for p, h in files.items()), '来源Git原件不符')
    projection = read('event-projection', 'preview/models.schema.json')
    channel = read('event-channel', 'preview/models.schema.json')
    api = read('event-channel', 'preview/subscriptions.openapi.json')
    policy = read('event-channel', 'preview/policy.json')
    numbers = inspect_graph(projection, channel, api, policy)
    numbers.update(projection_cases=reports['event-projection']['cases_passed'],
                   channel_cases=reports['event-channel']['cases_passed'])
    H.require(numbers == manifest['expectations'], '交付统计不符')
    H.require(numbers['projection_models'] == reports['event-projection']['models'] and
              numbers['channel_models'] == reports['event-channel']['models'] and
              numbers['operations'] == reports['event-channel']['operations'], '来源报告数量不符')
    H.require(manifest['boundaries'] == dict(stage0_complete=False, production_sdk_ready=False,
              business_implementation_started=False, runtime_protocol_frozen=False), '交接改变阶段边界')
    H.require(manifest['cycle'] == dict(rounds=[dict(round=i, repository='leafseamer-sdk', commit=p['commit'])
              for i, p in enumerate(packages, 1)] + [dict(round=3, repository='leafseamer-suite', commit='containing-commit')],
              push_order=['leafseamer-sdk', 'leafseamer-suite']), '周期归属错误')
    negatives = []
    def rejected(name, action):
        try:
            action()
        except (ValueError, KeyError):
            negatives.append(name)
        else:
            raise AssertionError(name + ': 应拒绝')
    first, original = packages[0], snapshots['event-projection']
    altered = dict(original); altered[first['report']] += b' '
    rejected('报告原件改变', lambda: H.validate_package(first, altered))
    changed = H.decode(original[first['report']]); changed['cases_passed'] += 1
    altered = dict(original); altered[first['report']] = H.encode(changed)
    altered_package = copy.deepcopy(first); altered_package['files'][first['report']] = H.sha(altered[first['report']])
    rejected('重算摘要后的虚报数量', lambda: H.validate_package(altered_package, altered))
    altered_package = copy.deepcopy(first); altered_package['files'].pop(next(p for p in original if p != first['report']))
    rejected('遗漏报告输入', lambda: H.validate_package(altered_package, {p: original[p] for p in altered_package['files']}))
    bad = copy.deepcopy(channel); bad['$defs'][next(iter(projection['$defs']))] = {'type': 'null'}
    rejected('快照模型接受集漂移', lambda: inspect_graph(projection, bad, api, policy))
    bad_api = copy.deepcopy(api); bad_api['x-advertisable'] = True
    rejected('候选自动广告', lambda: inspect_graph(projection, channel, bad_api, policy))
    bad_api = copy.deepcopy(api); bad_api['paths']['/internal/subscriptions']['post']['security'] = [{'humanBearer': []}]
    rejected('服务入口改用人员凭据', lambda: inspect_graph(projection, channel, bad_api, policy))
    bad_policy = copy.deepcopy(policy); bad_policy['operations'].pop()
    rejected('遗漏路由映射', lambda: inspect_graph(projection, channel, api, bad_policy))
    bad_policy = copy.deepcopy(policy); bad_policy['requires_new_full_contract_selection'] = False
    rejected('新帧冒充原选择', lambda: inspect_graph(projection, channel, api, bad_policy))
    for path in ('../escape', '/absolute', 'C:/absolute', 'a//b', 'a\\b'):
        rejected('非法路径:' + path, lambda path=path: H.path_name(path))
    rejected('浮动来源提交', lambda: H.read_fixed(sdk, 'main', ['README.md']))
    return dict(format='sdk-event-handoff-report/1', all_passed=True, sdk_main_commit=manifest['sdk_main_commit'],
                fixed_sdk_files=sum(len(p['files']) for p in packages), sdk_report_inputs=sum(len(r['inputs']) for r in reports.values()),
                source_anchors=len(anchors), verified_numbers=numbers, rejected_mutations=negatives,
                stage0_complete=False, runtime_tests_executed=0, device_tests_executed=0,
                scope='固定Git对象及输入关系核验；不重跑SDK行为用例，不证明远端推送', input_sha256=local_inputs())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--report', action='store_true'); group.add_argument('--check-report', action='store_true')
    args = parser.parse_args()
    if args.check_report:
        if args.sdk: parser.error('--check-report不读取SDK')
        report = H.decode((ROOT / 'report.json').read_bytes())
        H.require(report['all_passed'] is True and report['input_sha256'] == local_inputs(), '本仓输入漂移')
        print(json.dumps(dict(all_passed=True, matched_bindings=len(report['input_sha256']))))
    else:
        if not args.sdk: parser.error('需要--sdk指定固定Git对象仓库')
        report = run(args.sdk.resolve())
        if args.report: (ROOT / 'report.json').write_bytes(H.encode(report))
        print(json.dumps({k: v for k, v in report.items() if k != 'input_sha256'}, ensure_ascii=False))
