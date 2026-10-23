"""生成恢复准备与R2原子配对的66表候选；不修改旧候选或执行产品迁移。"""
import argparse
from pathlib import Path
import build_storage as P
HERE=Path(__file__).resolve().parent
SOURCES=P.SOURCES+[HERE/'build_registration.py',HERE/'registration.sql']


def build():
    sql=P.build().decode()
    changes={
      ' PRIMARY KEY(operation_id,controller_id),':''' PRIMARY KEY(operation_id,controller_id),
 UNIQUE(operation_id,controller_id,receipt_id),
 FOREIGN KEY(operation_id,controller_id) REFERENCES p1_preparation(recovery_operation_id,recovery_controller_id) DEFERRABLE INITIALLY DEFERRED,''',
      " UNIQUE(request_epoch,actor_identity,operation_kind,idempotency_key),":''' UNIQUE(request_epoch,actor_identity,operation_kind,idempotency_key),
 FOREIGN KEY(operation_id) REFERENCES pr_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,''',
      ' UNIQUE(controller_authority,controller_database,preparation_id),':''' UNIQUE(controller_authority,controller_database,preparation_id),
 UNIQUE(recovery_operation_id,recovery_controller_id),'''
    }
    for old,new in changes.items():
        assert sql.count(old)==1,old
        sql=sql.replace(old,new,1)
    sql+='\n'+(HERE/'registration.sql').read_text(encoding='utf-8')
    for table in ('pr_commit','pr_attempt','pr_receipt'):
        for op,suffix in [('UPDATE','u'),('DELETE','d')]:
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_preparation_registration'); END;\n"
    return sql.encode()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    target=HERE/'seamer-registration.sql';raw=build()
    if a.check:assert target.read_bytes()==raw,'生成漂移'
    else:target.write_bytes(raw)
