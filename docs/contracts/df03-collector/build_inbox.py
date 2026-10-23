"""固定27表候选投影，显式修正25表历史消息名及方向，不改旧文件。"""
import argparse
from pathlib import Path
import build_journal

HERE = Path(__file__).resolve().parent


def once(source, old, new):
    assert source.count(old) == 1, '源片段漂移：'+old
    return source.replace(old, new)


def build():
    source=build_journal.build()
    # 这两种旧SQL枚举不匹配0.2真实通道；按明确映射修复全部固定出现位置。
    assert source.count("'QUERY_POLL'")==4 and source.count("'QUERY_COMMIT'")==4
    source=source.replace("'QUERY_POLL'","'QUERY_CAPTURE'").replace("'QUERY_COMMIT'","'COMMIT_STATUS'")
    source=once(source,'max_queries INTEGER NOT NULL CHECK(max_queries BETWEEN 0 AND 1024), body BLOB NOT NULL',
                'max_queries INTEGER NOT NULL CHECK(max_queries BETWEEN 0 AND 1024), max_inbox INTEGER NOT NULL CHECK(max_inbox BETWEEN 1 AND 1048576), body BLOB NOT NULL')
    source=once(source,'PRIMARY KEY(channel_id,sequence), UNIQUE(channel_id,message_id), UNIQUE(channel_id,sequence,stop_id),',
                'reply_to TEXT,\n PRIMARY KEY(channel_id,sequence), UNIQUE(channel_id,message_id), UNIQUE(channel_id,sequence,stop_id),\n FOREIGN KEY(channel_id,reply_to) REFERENCES tc_inbox(channel_id,message_id) DEFERRABLE INITIALLY DEFERRED,')
    return source+'\n'+(HERE/'inbox.sql').read_text(encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    raw=build().encode('utf-8');path=HERE/'collector-storage-v02.sql'
    if args.check:assert path.read_bytes()==raw,'生成漂移'
    else:path.write_bytes(raw)
