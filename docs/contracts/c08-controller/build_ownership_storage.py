"""组合不可变占用归属候选；不执行产品迁移。"""
import argparse
from pathlib import Path
import build_open_storage as G
import build_control_storage as C
import build_layout as L
HERE=Path(__file__).resolve().parent
TABLES=('ow_source','ow_ownership','ow_commit','ow_revocation')
SOURCES=G.SOURCES+[HERE/'build_ownership_storage.py',HERE/'ownership-storage.sql']
def build():
    sql=G.build().decode()
    sql=L.replace(sql,'FOREIGN KEY(hold_id) REFERENCES cr_hold_commit(hold_id) DEFERRABLE INITIALLY DEFERRED',
      'FOREIGN KEY(hold_id) REFERENCES ow_commit(hold_id) DEFERRABLE INITIALLY DEFERRED,\n FOREIGN KEY(hold_id) REFERENCES cr_hold_commit(hold_id) DEFERRABLE INITIALLY DEFERRED',1)
    sql=L.replace(sql,"owner_ref TEXT NOT NULL CHECK(length(owner_ref)>0),",
      'owner_ref TEXT NOT NULL, owner_revision TEXT NOT NULL, owner_digest TEXT NOT NULL,',1)
    sql=L.replace(sql,'PRIMARY KEY(snapshot_id,hold_id)\n) STRICT;',
      'PRIMARY KEY(snapshot_id,hold_id),\n FOREIGN KEY(owner_ref,owner_revision,owner_digest) REFERENCES ow_ownership(ownership_id,revision,ownership_digest)\n) STRICT;',1)
    sql=L.replace(sql,"h.authority_state_id!=s.authority_state_id OR h.classification!='active'",
      "NOT EXISTS(SELECT 1 FROM ow_current_owner o WHERE o.ownership_id=h.owner_ref AND o.hold_id=h.hold_id) OR h.authority_state_id!=s.authority_state_id OR h.classification!='active'",1)
    sql=L.replace(sql,"'open_revocation','recovery','exit'))","'open_revocation','recovery','exit','ownership'))",1)
    sql+='\n'+(HERE/'ownership-storage.sql').read_text(encoding='utf-8')
    sql=L.replace(sql,'@OWNERSHIP_HAZARD_SUCCESSOR@',C.successor("coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=s.device_id),'00000000000000000000')"),1)
    for table in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    target=HERE/'controller-ownership.sql';data=build()
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
