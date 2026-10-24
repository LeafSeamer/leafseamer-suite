"""对齐当前编码消息版本并收紧类型化编码来源；保留旧候选字节。"""
import argparse
import build_final_admission_storage as B
HERE=B.HERE
SOURCES=list(dict.fromkeys(B.SOURCES+[HERE/'build_typed_encoding_path.py',HERE/'typed-encoding-path.sql']))

def build():
    sql=B.build().decode();old="protocol_version='ipc/0.13.0-journal-draft.1'"
    assert sql.count(old)==1,'journal_version_anchor'
    sql=sql.replace(old,"protocol_version='ipc/0.14.0-continuation-draft.1'")
    old='CREATE VIEW ep_open_request AS SELECT b.* FROM ij_base_ep_open_request b'
    assert sql.count(old)==1,'encoding_view_anchor'
    sql=sql.replace(old,'CREATE VIEW te_base_ep_open_request AS SELECT b.* FROM ij_base_ep_open_request b')
    return (sql+'\n'+(HERE/'typed-encoding-path.sql').read_text(encoding='utf8')).encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'controller-typed-encoding.sql'
    if a.check:assert target.read_bytes()==build()
    else:target.write_bytes(build())
