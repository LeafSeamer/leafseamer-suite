"""对账候选与固定历史提交，并在隔离Python路径的临时副本中重组。"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from assemble_candidate import ROOT, OUTPUTS, assemble, decode, encode, load_source, sha, source_path, verify_outputs, walk

SUITE = ROOT.parents[2]


def git_bytes(revision, path):
    return subprocess.check_output(['git', 'show', revision + ':' + path], cwd=SUITE)


def diff_nodes(a, b, path=''):
    # 类型也须相同，避免True==1或1==1.0掩盖树变化；字节对账再检查键序/格式。
    if type(a) is not type(b):
        return [path]
    if isinstance(a, dict):
        if set(a) != set(b):
            return [path]
        return [p for k in a for p in diff_nodes(a[k], b[k], path + '/' + k.replace('~', '~0').replace('/', '~1'))]
    if isinstance(a, list):
        if len(a) != len(b):
            return [path]
        return [p for i in range(len(a)) for p in diff_nodes(a[i], b[i], path + '/' + str(i))]
    return [] if a == b else [path]


def mutants(files):
    # 每个反例修改一个独立安全/元数据边界，预期统一拒绝，绝不更新历史期待摘要。
    changes = [
        ('SE01', ['http/controller.operations.json', 'paths', '/api/v1/events'], None, 'delete'),
        ('SE02', ['http/controller.operations.json', 'paths', '/auth/sessions/refresh', 'post', 'security'], [], 'set'),
        ('SE03', ['http/controller.operations.json', 'paths', '/api/v1/meta', 'get', 'summary'], 'changed', 'set'),
        ('SE04', ['public.schema.json', '$defs', 'Revision', 'maxLength'], 19, 'set'),
        ('SE05', ['public.schema.json', '$id'], 'https://unregistered.invalid/public', 'set'),
        ('SE06', ['ipc.schema.json', 'oneOf', 0, '$ref'], 'https://unregistered.invalid/model#/x', 'set'),
        ('SE07', ['ipc.schema.json', 'oneOf', 0, '$ref'], '#/$defs/DoesNotExist', 'set'),
        ('SE08', ['route-projection.json'], files['route-projection.json'] + [files['route-projection.json'][0]], 'set'),
        ('SE09', ['http/seamer.operations.json', 'paths', '/api/v1/events', 'get', 'x-websocket-frame-schema'], '#/components/schemas/DoesNotExist', 'set'),
        ('SE10', ['http/controller.operations.json', 'paths', '/api/v1/meta', 'get', 'responses', '200', 'headers'], {'X-Unreviewed': {'schema': {'type': 'string'}}}, 'set'),
        ('SE11', ['http/controller.operations.json', 'paths', '/api/v1/events', 'get', 'parameters'], [], 'set'),
        ('SE12', ['http/controller.operations.json', 'components', 'schemas'], {}, 'set'),
        ('SE13', ['schema-registry.json', 'legacy_openapi_component_order'], list(reversed(files['schema-registry.json']['legacy_openapi_component_order'])), 'set'),
        ('SE14', ['fixtures.json', 'examples', 0, 'schema_valid'], False, 'set'),
        ('SE15', ['route-projection.json', 0, 'unconsumed_policy'], 'unexpected', 'set'),
        ('SE16', ['schema-registry.json', 'component_projection_is_public_export_approval'], True, 'set'),
    ]
    for id, path, value, op in changes:
        changed = copy.deepcopy(files)
        parent = changed
        for key in path[:-1]:
            parent = parent[key]
        if op == 'delete':
            del parent[path[-1]]
        else:
            parent[path[-1]] = value
        yield id, changed


def run():
    manifest, files = load_source(ROOT / 'source')
    out, counts = assemble(files)
    verify_outputs(manifest, out)
    comparisons = []
    for name in OUTPUTS:
        path = 'docs/contracts/draft4/' + name
        baseline = git_bytes(manifest['source_commit'], path)
        current = (SUITE / path).read_bytes()
        differences = diff_nodes(decode(baseline), out[name])
        if current != baseline or encode(out[name]) != baseline or differences:
            raise ValueError('候选与固定提交或工作区不等价: ' + name)
        comparisons.append({'file': name, 'source_commit_sha256': sha(baseline),
                            'assembled_sha256': sha(encode(out[name])), 'nodes_compared': sum(1 for _ in walk(out[name])),
                            'node_differences': differences, 'byte_equal': True})
    negative_results = []
    for id, changed in mutants(files):
        try:
            mutated, _ = assemble(changed)
            verify_outputs(manifest, mutated)
        except (ValueError, KeyError, IndexError):
            negative_results.append({'id': id, 'rejected': True})
        else:
            raise ValueError('变异未被拒绝: ' + id)
    for value in ('../escape', '/absolute', 'C:/absolute', 'http\\x', 'a//b'):
        try:
            source_path(ROOT / 'source', value)
        except ValueError:
            continue
        raise ValueError('路径未被拒绝')
    # 只复制重组器与纯数据；-I排除当前目录/PYTHONPATH，子进程仅使用Python标准库。
    generated = []
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix='.candidate-', dir=ROOT) as name:
            temp = Path(name)
            shutil.copyfile(ROOT / 'assemble_candidate.py', temp / 'assemble_candidate.py')
            shutil.copytree(ROOT / 'source', temp / 'source')
            completed = subprocess.run([sys.executable, '-I', str(temp / 'assemble_candidate.py'),
                                        '--source', str(temp / 'source'), '--output', str(temp / 'output')],
                                       cwd=temp, text=True, encoding='utf-8', capture_output=True, check=True)
            json.loads(completed.stdout)
            generated.append({file: (temp / 'output' / file).read_bytes() for file in OUTPUTS})
    for file in OUTPUTS:
        if generated[0][file] != generated[1][file] or generated[0][file] != encode(out[file]):
            raise ValueError('独立双次生成不一致')
    # 继续执行既有232例，但明确它们仍依赖历史Python，不属于已迁出的语义实现。
    prior = subprocess.run([sys.executable, str(SUITE / 'docs/contracts/draft4/validate_contracts.py')],
                           cwd=SUITE, text=True, encoding='utf-8', capture_output=True, check=True)
    prior_result = json.loads(prior.stdout)
    if prior_result.get('all_passed') is not True:
        raise ValueError('历史契约检查失败')
    paths = {'docs/contracts/df01-source/' + n for n in ('assemble_candidate.py', 'extract_candidate.py', 'check_candidate.py', 'source/source-manifest.json')}
    paths.update('docs/contracts/df01-source/source/' + item['path'] for item in manifest['files'])
    old_report_path = 'docs/contracts/draft4/validation-report.json'
    old_report = decode((SUITE / old_report_path).read_bytes())
    paths.add(old_report_path)
    for name, expected in old_report['input_sha256'].items():
        path = 'docs/' + name
        if sha((SUITE / path).read_bytes()) != expected:
            raise ValueError('历史报告输入已漂移: ' + path)
        paths.add(path)
    return {'purpose': 'draft4-source-extraction-reference', 'all_passed': True, 'authority_switched': False,
            'source_commit': manifest['source_commit'], 'comparisons': comparisons,
            'public_models': len(files['public.schema.json']['$defs']), 'ipc_messages': len(files['ipc.schema.json']['oneOf']),
            'operations': counts, 'negative_cases': negative_results, 'path_rejections': 5,
            'isolated_python_runs': 2, 'byte_equal_outputs_per_run': 6,
            'historical_validation': prior_result,
            'runtime_tests_executed': 0, 'sdk_typescript_generated': False,
            'input_sha256': {p: sha((SUITE / p).read_bytes()) for p in sorted(paths)}}


def check_report(staged):
    def read(path):
        return git_bytes('', path) if staged else (SUITE / path).read_bytes()
    report = decode(read('docs/contracts/df01-source/extraction-report.json'))
    if report.get('all_passed') is not True or not report.get('input_sha256'):
        raise ValueError('缺少已通过报告或输入声明')
    for path, expected in report['input_sha256'].items():
        source_path(SUITE, path)
        if sha(read(path)) != expected:
            raise ValueError('报告输入不一致: ' + path)
    return {'all_passed': True, 'source': 'index' if staged else 'worktree',
            'scope': '仅声明输入的字节绑定，不重跑检查', 'matched_bindings': len(report['input_sha256'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--report', action='store_true')
    group.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged仅适用于--check-report')
    result = check_report(args.staged) if args.check_report else run()
    if args.report:
        (ROOT / 'extraction-report.json').write_bytes(encode(result))
    print(json.dumps({k: v for k, v in result.items() if k not in ('input_sha256', 'comparisons', 'historical_validation')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
