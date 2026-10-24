"""将最终封存附加到完整Controller布局；不删除四个临时最终签发阻断。"""
import argparse
from pathlib import Path
import build_attempt_inventory as B
HERE=Path(__file__).resolve().parent
SOURCES=list(dict.fromkeys(B.SOURCES+[Path(__file__),HERE/'final-admission-storage.sql']))
def build():
    sql=B.build().decode()
    old=' UNIQUE(permit_id,issued_revision,kind),\n FOREIGN KEY(ordinary_id) REFERENCES ce_permit(permit_id) DEFERRABLE INITIALLY DEFERRED,'
    new=' UNIQUE(permit_id,issued_revision,kind),\n FOREIGN KEY(permit_id,issued_revision,kind) REFERENCES fa_seal(permit_id,issued_revision,kind) DEFERRABLE INITIALLY DEFERRED,\n FOREIGN KEY(ordinary_id) REFERENCES ce_permit(permit_id) DEFERRABLE INITIALLY DEFERRED,'
    assert sql.count(old)==1,'issue_anchor_drift';sql=sql.replace(old,new)
    sql+='\n'+(HERE/'final-admission-storage.sql').read_text(encoding='utf8')
    for table in ('fa_seal','fa_input','fa_commit','fa_observation'):
        for action in ('UPDATE','DELETE'):
            sql+=f"\nCREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'controller-final-admission.sql'
    if a.check:assert target.read_bytes()==build()
    else:target.write_bytes(build())
