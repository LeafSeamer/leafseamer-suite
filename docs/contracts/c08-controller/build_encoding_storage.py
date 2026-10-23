"""生成编码准备持久化候选；不执行产品迁移。"""
import argparse
from pathlib import Path
import build_scope_storage as S
import build_layout as L
HERE=Path(__file__).resolve().parent
TABLES=('ep_limit','ep_request','ep_request_commit','ep_send_attempt','ep_reply','ep_receive_commit','ep_revocation','ep_release')
SOURCES=S.SOURCES+[HERE/'build_encoding_storage.py',HERE/'encoding-storage.sql']

def build():
    text=S.build().decode()
    # 取消准备与通用编码登记同事务，不能绕开配对直接入旧outbox。
    text=L.replace(text,'outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0), UNIQUE(cancellation_id,primitive_id)',
      'outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0), UNIQUE(cancellation_id,primitive_id),\n FOREIGN KEY(prepare_id) REFERENCES ep_request_commit(prepare_id) DEFERRABLE INITIALLY DEFERRED',1)
    text+='\n'+(HERE/'encoding-storage.sql').read_text(encoding='utf-8')
    for table in TABLES:
        for action,suffix in [('UPDATE','u'),('DELETE','d')]:
            text+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;\n"
    return text.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    target=HERE/'controller-encoding.sql';raw=build()
    if a.check:assert target.read_bytes()==raw,'生成漂移'
    else:target.write_bytes(raw)
