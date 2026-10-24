"""以独立封存原件替换可变自引用封存外键，保留原事务终态约束。"""
import argparse
from pathlib import Path
import build_typed_seamer as B
HERE=Path(__file__).resolve().parent
SOURCES=B.SOURCES+[Path(__file__),HERE/'atomic-ingress.sql']
def build():
    old='FOREIGN KEY(commit_id,required_seal) REFERENCES ingress_commit(commit_id,sealed) DEFERRABLE INITIALLY DEFERRED'
    new='FOREIGN KEY(commit_id,required_seal) REFERENCES ingress_commit_seal(commit_id,sealed) DEFERRABLE INITIALLY DEFERRED'
    sql=B.amend(B.build().decode(),'CREATE TABLE ingress_commit (',[(old,new)])
    return (sql+'\n'+(HERE/'atomic-ingress.sql').read_text(encoding='utf-8')).encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'seamer-atomic-ingress.sql'
    if a.check:assert path.read_bytes()==build()
    else:path.write_bytes(build())
