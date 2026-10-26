"""核验SDK固定提交与Suite交接资料；不执行服务、设备或远端发布。"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parent
SUITE = ROOT.parents[2]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def decode(raw):
    def unique(items):
        obj = {}
        for key, value in items:
            require(key not in obj, '重复JSON键')
            obj[key] = value
        return obj
    return json.loads(raw.decode('utf8'), object_pairs_hook=unique)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def path_name(name):
    path = PurePosixPath(name)
    require(bool(name) and '\\' not in name and ':' not in name and not path.is_absolute() and
            '..' not in path.parts and path.as_posix() == name, '非规范相对路径')
    return name


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo)


def at(repo, commit, path):
    require(re.fullmatch('[0-9a-f]{40}', commit), '必须固定完整提交')
    return git(repo, 'show', commit + ':' + path_name(path))


def validate_package(package, read):
    require(len(package['files']) > 1 and package['report'] in package['files'], '交付集合缺报告')
    for path, digest in package['files'].items():
        require(sha(read(path)) == digest, 'SDK固定提交文件摘要不符: ' + path)
    report = decode(read(package['report']))
    require(report['all_passed'] is True, 'SDK报告未通过')
    expected = {package['input_prefix'] + path: digest for path, digest in report['input_sha256'].items()}
    expected[package['report']] = sha(read(package['report']))
    require(expected == package['files'], 'SDK报告与交付清单不完整匹配')
    return report


def validate_numbers(expect, baseline, composition, inventory, source):
    historical = baseline['upstream']['historical_validation']
    counts = {authority: sum(op['authority'] == authority for op in inventory['operations'])
              for authority in ('controller', 'seamer')}
    actual = dict(baseline_outputs=baseline['byte_equal_outputs'], baseline_models=baseline['public_models'],
        baseline_ipc=baseline['ipc_message_types'], historical_cases=sum(historical[k] for k in
          ('positive', 'structural_negative', 'semantic_negative', 'ipc_positive', 'ipc_negative', 'linked_cases')),
        composition_cases=composition['cases'], models=len(source['definitions']),
        source_documents=inventory['source_documents'], source_operations=inventory['source_operation_declarations'],
        authority_operations=inventory['authority_operation_declarations'], selected_operations=len(inventory['operations']),
        controller_operations=counts['controller'], seamer_operations=counts['seamer'],
        replacements=sum(bool(op['replaced_sources']) for op in inventory['operations']), retirements=len(inventory['retired']))
    require(actual == expect and inventory['selected_operations'] == len(inventory['operations']), '交接统计与原件不符')
    require(composition['cases'] == len(composition['case_results']), 'SDK案例集合不完整')
    return actual


def run(sdk):
    manifest = decode((ROOT / 'manifest.json').read_bytes())
    require(manifest['format'] == 'leafseamer-sdk-handoff/1', '交接格式不符')
    require(git(sdk, 'remote', 'get-url', 'origin').decode().strip() == manifest['sdk_repository'], 'SDK仓库归属不符')
    packages = manifest['packages']
    require([p['name'] for p in packages] == ['draft4', 'composition'], '交付包集合不符')
    require(manifest['sdk_main_commit'] == packages[1]['commit'], '消费提交与归并包不一致')
    loaded = {}; snapshots = {}
    for package in packages:
        commit = package['commit']
        require(subprocess.run(['git', 'merge-base', '--is-ancestor', commit, 'main'], cwd=sdk,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0, 'SDK main不包含交付提交')
        cache = {path: at(sdk, commit, path) for path in package['files']}
        loaded[package['name']] = validate_package(package, cache.__getitem__)
        snapshots[package['name']] = cache
    require(subprocess.run(['git', 'merge-base', '--is-ancestor', packages[0]['commit'], packages[1]['commit']],
                           cwd=sdk, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0, '交付历史顺序错误')
    baseline, composition = loaded['draft4'], loaded['composition']
    first, second = snapshots['draft4'], snapshots['composition']
    migration = decode(first['contracts/draft4/migration.json'])
    original = decode(first['contracts/draft4/source/source-manifest.json'])
    policy = decode(second['contracts/composition/policy.json'])
    source = decode(second['contracts/composition/source.json'])
    inventory = decode(second['contracts/composition/preview/inventory.json'])
    expected_anchors = {}
    def anchor(commit, path, digest):
        k = commit, path_name(path)
        require(k not in expected_anchors or expected_anchors[k] == digest, '源锚点矛盾')
        expected_anchors[k] = digest
    for item in migration['files']:
        anchor(migration['source_commit'], item['source_path'], item['sha256'])
    anchor(migration['source_commit'], 'LICENSE', migration['source_license_sha256'])
    anchor(migration['source_commit'], migration['derived_checker_source']['path'], migration['derived_checker_source']['sha256'])
    for name, digest in original['expected_outputs'].items():
        anchor(original['source_commit'], original['source_directory'] + '/' + name, digest)
    for item in policy['imports']:
        anchor(policy['provenance']['commit'], item['path'], item['sha256'])
    for path, digest in baseline['upstream']['historical_input_sha256'].items():
        anchor(baseline['upstream']['source_commit'], path, digest)
    actual_anchors = {(x['commit'], x['path']): x['sha256'] for x in manifest['suite_source_anchors']}
    require(actual_anchors == expected_anchors and len(actual_anchors) == len(manifest['suite_source_anchors']), '源锚点遗漏或重复')
    for (commit, path), digest in actual_anchors.items():
        require(sha(at(SUITE, commit, path)) == digest, 'Suite固定来源不符: ' + path)
    require(baseline['runtime_acceptance_cases_executed'] == composition['runtime_acceptance_executed'] == 0 and
            composition['approved'] is False and inventory['runtime_ready'] is False and inventory['approved'] is False,
            '离线资料不得升级运行资格')
    require(manifest['boundaries'] == dict(stage0_complete=False, production_sdk_ready=False,
            business_implementation_started=False, runtime_protocol_frozen=False, runtime_acceptance_executed=0), '阶段边界改变')
    numbers = validate_numbers(manifest['expectations'], baseline, composition, inventory, source)
    cycle = manifest['cycle']
    require(cycle['push_order'] == ['leafseamer-sdk', 'leafseamer-suite'] and len(cycle['rounds']) == 3, '周期交付顺序不符')
    for index, package in enumerate(packages, 1):
        require(cycle['rounds'][index-1] == dict(round=index, repository='leafseamer-sdk', commit=package['commit']), '周期提交归属不符')
    require(cycle['rounds'][2] == dict(round=3, repository='leafseamer-suite', commit='containing-commit'), 'Suite周期归属不符')
    # 证明核验器对文件篡改、缺项、统计伪标和非固定路径失效，不改真实材料。
    negative = []
    def rejected(name, action):
        try:
            action()
        except (ValueError, KeyError):
            negative.append(name)
        else:
            raise ValueError('负例未拒绝: ' + name)
    rejected('SDK报告原件篡改', lambda: validate_package(packages[0], lambda p: first[p] + b' ' if p == packages[0]['report'] else first[p]))
    changed = dict(packages[0], files=dict(packages[0]['files']))
    changed['files'].pop(next(p for p in changed['files'] if p != changed['report']))
    rejected('交付清单遗漏报告输入', lambda: validate_package(changed, first.__getitem__))
    rejected('操作数量伪标', lambda: validate_numbers(dict(manifest['expectations'], selected_operations=178), baseline, composition, inventory, source))
    for name in ('../escape', '/absolute', 'C:/absolute', 'a//b', 'a\\b'):
        rejected('非规范路径:' + name, lambda name=name: path_name(name))
    rejected('非固定提交', lambda: at(sdk, 'main', 'README.md'))
    paths = {p.relative_to(SUITE).as_posix() for p in ROOT.iterdir() if p.is_file() and p.name != 'report.json'}
    paths.update('docs/' + p for p in ('rebirth-df01-sdk-freeze.md', 'rebirth-design-closure.md',
                                      'rebirth-readiness.md', 'contracts/df01-source/README.md', 'contracts/df01/reference-report.json'))
    reference = decode((SUITE / 'docs/contracts/df01/reference-report.json').read_bytes())
    require(reference['all_passed'] is True, 'DF01参考报告未通过')
    for path, digest in reference['input_sha256'].items():
        name = 'docs/' + path_name(path)
        require(sha((SUITE / name).read_bytes()) == digest, 'DF01参考输入漂移')
        paths.add(name)
    return dict(format='leafseamer-sdk-handoff-report/1', all_passed=True, sdk_main_commit=manifest['sdk_main_commit'],
                sdk_fixed_files=sum(len(p['files']) for p in packages), sdk_report_inputs=sum(len(r['input_sha256']) for r in loaded.values()),
                suite_fixed_source_anchors=len(actual_anchors), verified_numbers=numbers, rejected_mutations=negative,
                scope='固定Git对象及报告绑定检查；不重跑SDK历史验收，不证明远端推送或运行服务',
                stage0_complete=False, input_sha256={p: sha((SUITE / p).read_bytes()) for p in sorted(paths)})


def check_report():
    report = decode((ROOT / 'report.json').read_bytes())
    require(report['all_passed'] is True and report['input_sha256'], '缺少有效报告')
    for path, digest in report['input_sha256'].items():
        require(sha((SUITE / path_name(path)).read_bytes()) == digest, '交接报告输入漂移: ' + path)
    return dict(all_passed=True, matched_bindings=len(report['input_sha256']), scope='仅核本仓输入绑定')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path)
    group = parser.add_mutually_exclusive_group(); group.add_argument('--report', action='store_true'); group.add_argument('--check-report', action='store_true')
    args = parser.parse_args()
    if args.check_report and args.sdk: parser.error('--check-report不读取SDK')
    if not args.check_report and not args.sdk: parser.error('固定提交核验需要--sdk')
    result = check_report() if args.check_report else run(args.sdk.resolve())
    if args.report: (ROOT / 'report.json').write_bytes(encode(result))
    print(json.dumps({k:v for k,v in result.items() if k != 'input_sha256'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
