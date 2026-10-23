"""组合固定的Controller存储候选；不是通用SQL重写器或生产迁移。"""
import argparse
from pathlib import Path
import re
import sqlite3

HERE = Path(__file__).resolve().parent
SOURCES = [
    HERE / 'common.sql',
    HERE.parent / 'c02-admission/admission.sql',
    HERE.parent / 'c04-preparation/preparation.sql',
]


def remove(sql, kind, name):
    # 只处理受版本管理的固定定义；必须精确命中一次，布局变化不可静默跳过。
    parts, pending, count = [], '', 0
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            if re.search(rf'^CREATE {kind} {name}\b', pending, flags=re.M):
                count += 1
            else:
                parts.append(pending)
            pending = ''
    assert not pending.strip() or pending.lstrip().startswith('--'), '未完成SQL语句'
    assert count == 1, (kind, name, count)
    return ''.join(parts) + pending


def replace(sql, old, new, count):
    assert sql.count(old) == count, (old, sql.count(old), count)
    return sql.replace(old, new)


def build():
    common, admission, preparation = [p.read_text(encoding='utf-8') for p in SOURCES]
    admission = remove(admission, 'TABLE', 'ca_scope')
    for name in ('ca_scope_no_update', 'ca_scope_no_delete'):
        admission = remove(admission, 'TRIGGER', name)
    admission = replace(admission, 'REFERENCES ca_scope(singleton)', 'REFERENCES controller_scope(singleton)', 1)
    preparation = remove(preparation, 'TABLE', 'cp_scope')
    preparation = remove(preparation, 'TABLE', 'cp_deny_event')
    preparation = remove(preparation, 'VIEW', 'cp_deny_current')
    for name in ('cp_scope_u', 'cp_scope_d', 'cp_deny_guard', 'cp_deny_event_u', 'cp_deny_event_d'):
        preparation = remove(preparation, 'TRIGGER', name)
    preparation = replace(preparation, 'REFERENCES cp_scope(singleton)', 'REFERENCES controller_scope(singleton)', 1)
    preparation = replace(preparation, 'cp_deny_event', 'run_deny_event', 1)
    preparation = replace(preparation, 'cp_deny_current', 'run_deny_current', 1)
    preparation = replace(preparation,
        'EXISTS(SELECT 1 FROM cp_commit dc WHERE dc.commit_id=d.commit_id)',
        'EXISTS(SELECT 1 FROM run_deny_committed dc WHERE dc.snapshot_revision=d.snapshot_revision)', 1)
    result = ('-- 生成自common.sql及两个固定子域；请修改源文件并重新生成。\n'
              '-- controller-storage/0.1.0-draft.1；待审阅，非生产迁移。\n'
              + common + '\n' + admission + '\n' + preparation)
    for retired in ('ca_scope', 'cp_scope', 'cp_deny_event', 'cp_deny_current'):
        assert retired not in result, retired
    return result.encode('utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    data = build()
    target = HERE / 'controller.sql'
    if args.check:
        assert target.read_bytes() == data, '生成物漂移'
    else:
        target.write_bytes(data)
