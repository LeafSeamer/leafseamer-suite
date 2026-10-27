"""固定注册与持久化成果交接；与SDK行为复验、远端推送及运行验收分别记账。"""
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
DESIGNS = ('rebirth-design-closure.md', 'rebirth-readiness.md', 'rebirth-df01-sdk-freeze.md',
           'rebirth-c05-event-sync-design.md', 'rebirth-df04-storage-design.md')


def inspect_graph(base_raw, graph, mapping, policy):
    base = H.decode(base_raw)
    before, after = base['$defs'], graph['$defs']
    H.require(all(after.get(name) == value for name, value in before.items()), '原通道定义改变')
    H.require(set(after)-set(before) == {'registry__Profile', 'registry__CollectionRule', 'registry__Selector', 'registry__Window'},
              '注册定义集合改变')
    H.require(mapping['approved'] is False and mapping['runtime_ready'] is False, '注册候选被批准')
    H.require(mapping['source_graph_id'] == base['$id'] and mapping['source_graph_digest'] == H.sha(base_raw), '模型图字节绑定不符')
    H.require(mapping['collection_permissions'] == policy['collection_permissions'], '集合权限不符')
    H.require(set(mapping['collection_models']) == set(policy['collection_permissions']) and
              all(name in before for name in mapping['collection_models'].values()), '集合视图缺失')
    H.require(mapping['mandatory_unresolved'] == ['commands', 'executions', 'occurrences'] and
              mapping['silent_truncation_allowed'] is False, '未决覆盖或容量策略改变')
    return dict(prior_models=len(before), registry_models=len(after), collections=len(mapping['collection_models']))


def source_anchors(sources, sdk_url):
    anchors = {}
    for source in sources:
        H.require(source['source_repository'] == sdk_url.removesuffix('.git') and source['approved'] is False, '来源归属或批准状态改变')
        for path, checksum in source['inputs'].items():
            identity = source['source_commit'], H.path_name(path)
            H.require(identity not in anchors or anchors[identity] == checksum, '来源锚点冲突')
            anchors[identity] = checksum
    return anchors


def inspect_reports(registry, storage):
    for report in (registry, storage):
        H.require(all(value == 0 for key, value in report.items() if key.endswith('_tests_executed')), '混入未执行的运行验收')
    H.require(storage['final_release_gate_implemented'] is False, '读取切点冒充最终释放门')
    return dict(registry_cases=registry['cases_passed'], storage_cases=storage['cases_passed'],
                storage_tables=storage['tables'], sqlite_file_scenarios=storage['sqlite_file_scenarios'],
                per_write_failure_paths=storage['per_write_failure_paths'])


def local_inputs():
    paths = [p for p in ROOT.iterdir() if p.is_file() and p.name != 'report.json']
    paths += [HELPER] + [SUITE/'docs'/name for name in DESIGNS]
    reference_path = SUITE/'docs/contracts/df01/reference-report.json'
    reference = H.decode(reference_path.read_bytes())
    H.require(reference['all_passed'] is True and reference['sdk_toolchain_executed'] is False, 'DF01参考结果错误')
    paths.append(reference_path)
    for path, checksum in reference['input_sha256'].items():
        file = SUITE/'docs'/H.path_name(path)
        H.require(H.sha(file.read_bytes()) == checksum, 'DF01输入漂移')
        paths.append(file)
    return {p.relative_to(SUITE).as_posix(): H.sha(p.read_bytes()) for p in sorted(set(paths))}


def run(sdk):
    manifest = H.decode((ROOT/'manifest.json').read_bytes())
    H.require(manifest['format'] == 'sdk-scope-handoff/1', '交接格式不符')
    for repo, expected in ((sdk, manifest['sdk_repository']), (SUITE, manifest['suite_repository'])):
        H.require(H.git(repo, 'remote', 'get-url', 'origin').decode().strip() == expected, '仓库归属不符')
    packages = manifest['packages']
    H.require([p['name'] for p in packages] == ['scope-registry', 'scope-storage'] and
              manifest['sdk_main_commit'] == packages[-1]['commit'], '交接范围或提交改变')
    snapshots, reports = {}, {}
    for package in packages:
        H.require(subprocess.run(['git','merge-base','--is-ancestor',package['commit'],'main'],cwd=sdk,capture_output=True).returncode == 0,
                  'SDK main不包含交付')
        files = H.read_fixed(sdk, package['commit'], package['files'])
        snapshots[package['name']] = files
        reports[package['name']] = H.validate_package(package, files)
    H.require(subprocess.run(['git','merge-base','--is-ancestor',packages[0]['commit'],packages[1]['commit']],cwd=sdk,capture_output=True).returncode == 0,
              '交付顺序不符')
    def read(group, path): return H.decode(snapshots[group][path])
    sources = [read(p['name'], 'contracts/'+p['name']+'/sources.json') for p in packages]
    anchors = source_anchors(sources, manifest['sdk_repository'])
    declared = {(a['commit'], H.path_name(a['path'])): a['sha256'] for a in manifest['source_anchors']}
    H.require(anchors == declared and len(declared) == len(manifest['source_anchors']), '来源锚点缺失或重复')
    groups = {}
    for (commit, path), checksum in anchors.items(): groups.setdefault(commit, {})[path] = checksum
    for commit, files in groups.items():
        actual = H.read_fixed(sdk, commit, files)
        H.require(all(H.sha(actual[path]) == checksum for path, checksum in files.items()), '来源Git原件不符')
    registry_files = snapshots['scope-registry']
    base = registry_files['contracts/event-channel/preview/models.schema.json']
    graph = read('scope-registry', 'contracts/scope-registry/preview/models.schema.json')
    mapping = read('scope-registry', 'contracts/scope-registry/preview/mapping.json')
    policy = read('scope-registry', 'contracts/event-channel/preview/policy.json')
    numbers = inspect_graph(base, graph, mapping, policy)
    numbers.update(inspect_reports(reports['scope-registry'], reports['scope-storage']))
    H.require(numbers == manifest['expectations'] and reports['scope-registry']['models'] == numbers['registry_models'], '交付统计不符')
    H.require(manifest['boundaries'] == dict(stage0_complete=False, production_sdk_ready=False,
              business_implementation_started=False, runtime_protocol_frozen=False, final_release_gate_implemented=False), '阶段边界改变')
    H.require(manifest['cycle'] == dict(rounds=[dict(round=i,repository='leafseamer-sdk',commit=p['commit']) for i,p in enumerate(packages,1)] +
              [dict(round=3,repository='leafseamer-suite',commit='containing-commit')],push_order=['leafseamer-sdk','leafseamer-suite']), '周期归属不符')
    negatives = []
    def rejected(name, action):
        try: action()
        except (ValueError, KeyError): negatives.append(name)
        else: raise AssertionError(name+':应拒绝')
    first = packages[0]
    altered = dict(registry_files); altered[first['report']] += b' '
    rejected('报告原件替换', lambda:H.validate_package(first,altered))
    bad_report = copy.deepcopy(reports['scope-registry']); bad_report['cases_passed'] += 1
    altered = dict(registry_files); altered[first['report']] = H.encode(bad_report)
    bad_package = copy.deepcopy(first); bad_package['files'][first['report']] = H.sha(altered[first['report']])
    rejected('重算摘要后虚报案例', lambda:H.validate_package(bad_package,altered))
    bad_package = copy.deepcopy(first); bad_package['files'].pop(next(p for p in registry_files if p != first['report']))
    rejected('遗漏报告输入', lambda:H.validate_package(bad_package,{p:registry_files[p] for p in bad_package['files']}))
    bad = copy.deepcopy(graph); bad['$defs'][next(iter(H.decode(base)['$defs']))] = {'type':'null'}
    rejected('原通道接受集改变', lambda:inspect_graph(base,bad,mapping,policy))
    for label, field, value in [('图摘要错误','source_graph_digest','0'*64),('候选自动批准','approved',True),
                               ('遗漏未决集合','mandatory_unresolved',['commands']),('允许静默截断','silent_truncation_allowed',True),
                               ('遗漏集合视图','collection_models',{})]:
        bad = copy.deepcopy(mapping); bad[field] = value
        rejected(label, lambda bad=bad:inspect_graph(base,graph,bad,policy))
    bad = copy.deepcopy(mapping); bad['collection_permissions']['commands']['permission'] = 'status.read'
    rejected('命令读取权限降级', lambda:inspect_graph(base,graph,bad,policy))
    bad = copy.deepcopy(reports['scope-storage']); bad['final_release_gate_implemented'] = True
    rejected('writer切点伪装最终释放门', lambda:inspect_reports(reports['scope-registry'],bad))
    bad = copy.deepcopy(reports['scope-storage']); bad['process_crash_tests_executed'] = 1
    rejected('关闭重开冒充进程崩溃验收', lambda:inspect_reports(reports['scope-registry'],bad))
    for path in ('../escape','/absolute','C:/absolute','a//b','a\\b'):
        rejected('非法路径:'+path, lambda path=path:H.path_name(path))
    rejected('浮动来源提交', lambda:H.read_fixed(sdk,'main',['README.md']))
    return dict(format='sdk-scope-handoff-report/1',all_passed=True,sdk_main_commit=manifest['sdk_main_commit'],
                fixed_sdk_files=sum(len(p['files']) for p in packages),sdk_report_inputs=sum(len(r['inputs']) for r in reports.values()),
                source_anchors=len(anchors),verified_numbers=numbers,rejected_mutations=negatives,
                stage0_complete=False,runtime_tests_executed=0,device_tests_executed=0,
                scope='固定Git原件及关系核验；不重跑SDK行为用例，不证明远端推送或最终释放',input_sha256=local_inputs())


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sdk',type=Path)
    group=parser.add_mutually_exclusive_group();group.add_argument('--report',action='store_true');group.add_argument('--check-report',action='store_true')
    args=parser.parse_args()
    if args.check_report:
        if args.sdk:parser.error('--check-report不读取SDK')
        report=H.decode((ROOT/'report.json').read_bytes())
        H.require(report['all_passed'] is True and report['input_sha256']==local_inputs(),'本仓输入漂移')
        print(json.dumps(dict(all_passed=True,matched_bindings=len(report['input_sha256']))))
    else:
        if not args.sdk:parser.error('需要--sdk指定固定Git对象仓库')
        report=run(args.sdk.resolve())
        if args.report:(ROOT/'report.json').write_bytes(H.encode(report))
        print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'},ensure_ascii=False))
