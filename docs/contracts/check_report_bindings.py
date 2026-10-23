"""只读核对报告声明的输入字节；不运行验收或证明报告覆盖范围。"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
# 报告路径、摘要字段、输入路径基准均来自各报告生成器，禁止模糊搜索同名文件。
REPORTS = [
    ('docs/contracts/validation-report.json', 'artifact_sha256', 'docs/contracts'),
    ('docs/contracts/draft3/validation-report.json', 'input_sha256', 'docs'),
    ('docs/contracts/draft4/validation-report.json', 'input_sha256', 'docs'),
    ('docs/contracts/f02-f03/validation-report.json', 'input_sha256', 'docs'),
    ('docs/contracts/f04-f05/validation-report.json', 'input_sha256', 'docs'),
    ('docs/contracts/f06-f07/validation-report.json', 'input_sha256', 'docs'),
    ('docs/contracts/df01/reference-report.json', 'input_sha256', 'docs'),
    ('docs/contracts/df04/reference-report.json', 'input_sha256', 'docs/contracts/df04'),
    ('docs/contracts/df05/reference-report.json', 'artifact_sha256', 'docs/contracts/df05'),
    ('docs/contracts/df06/reference-report.json', 'artifact_sha256', 'docs/contracts/df06'),
]


def unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('重复JSON键: ' + key)
        result[key] = value
    return result


def input_path(base, name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('输入路径必须为规范仓库相对POSIX路径')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != name:
        raise ValueError('拒绝路径逃逸或非规范路径')
    return base + '/' + name


def check_report(spec, read):
    report_path, field, base = spec
    data = json.loads(read(report_path).decode('utf-8'), object_pairs_hook=unique_pairs)
    if not isinstance(data, dict) or data.get('all_passed') is not True:
        raise ValueError('报告未声明检查全部通过')
    hashes = data.get(field)
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('报告缺少非空输入摘要表')
    mismatches = []
    for name, expected in hashes.items():
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('非法SHA-256声明')
        target = input_path(base, name)
        actual = hashlib.sha256(read(target)).hexdigest()
        if actual != expected:
            mismatches.append(target)
    if mismatches:
        raise ValueError('输入字节不匹配: ' + ', '.join(mismatches))
    return len(hashes)


def worktree_read(path):
    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError('输入经链接逃出仓库')
    return target.read_bytes()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, stderr=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--staged', action='store_true', help='读取暂存区报告及输入')
    group.add_argument('--ref', help='读取指定提交中的报告及输入，例如HEAD')
    args = parser.parse_args()
    if args.staged:
        read = lambda path: git('show', ':' + path)
        source = 'index'
    elif args.ref:
        commit = git('rev-parse', '--verify', '--end-of-options', args.ref + '^{commit}').decode().strip()
        read = lambda path: git('show', commit + ':' + path)
        source = commit
    else:
        read, source = worktree_read, 'worktree'
    errors, bindings = [], 0
    for spec in REPORTS:
        try:
            bindings += check_report(spec, read)
        except (ValueError, OSError, subprocess.CalledProcessError) as error:
            errors.append({'report': spec[0], 'reason': str(error)})
    print(json.dumps({'scope': '报告所声明输入的原始字节绑定；不证明测试覆盖或执行真实性',
                      'source': source, 'reports': len(REPORTS), 'matched_bindings': bindings,
                      'all_passed': not errors, 'errors': errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
