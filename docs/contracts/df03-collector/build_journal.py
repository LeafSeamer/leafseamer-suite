"""固定十四表与采集日志组合；不加载实际数据库，不改变旧SQL源。"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLES = ['tc_policy', 'tc_source', 'tc_channel', 'tc_reservation', 'tc_frame', 'tc_attempt',
          'tc_written', 'tc_stop', 'tc_ack', 'tc_retired', 'tc_release']


def build():
    source = (HERE / 'storage.sql').read_text(encoding='utf-8')
    before = 'correlation_id TEXT NOT NULL UNIQUE, body BLOB NOT NULL, UNIQUE(id,binding_id)'
    after = before + ',\n FOREIGN KEY(id) REFERENCES tc_reservation(poll_id) DEFERRABLE INITIALLY DEFERRED'
    assert source.count(before) == 1, '固定来源发生漂移'
    source = source.replace(before, after)
    source += '\n' + (HERE / 'journal.sql').read_text(encoding='utf-8')
    for table in TABLES:
        for operation in ('UPDATE', 'DELETE'):
            source += f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END;\n"
    return source


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    output = HERE / 'collector-storage.sql'
    raw = build().encode('utf-8')
    if args.check:
        assert output.read_bytes() == raw, '生成物漂移'
    else:
        output.write_bytes(raw)
