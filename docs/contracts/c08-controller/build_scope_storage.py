"""生成限定取消范围持久候选；不执行产品迁移或设备操作。"""
import argparse
from pathlib import Path
import build_gate_renewal as G
import build_layout as L
import build_control_storage as C
HERE=Path(__file__).resolve().parent
TABLES=('gs_policy','gs_parent_class','gs_policy_commit','gs_assessment','gs_assessment_commit','gs_access','gs_scope_commit','gs_revocation')
SOURCES=G.SOURCES+[HERE/'build_scope_storage.py',HERE/'scope-storage.sql']

def build():
    v=G.sql().decode()
    changes=[
      ("'effective','ready','gate_protect'))","'effective','ready','gate_protect','scope_commit'))",1),
      ("'effective','ready','gate_protect') THEN change_id","'effective','ready','gate_protect','scope_commit') THEN change_id",1),
      ("((c.kind='ready' AND s.reserved_version", "((c.kind='scope_commit' AND s.reserved_version=p.reserved_version AND p.pending_operation_id IS NULL AND s.pending_operation_id IS NULL AND s.gate_state='protected') OR\n      (c.kind='ready' AND s.reserved_version",1),
      ("NOT IN ('ready','gate_protect')","NOT IN ('ready','gate_protect','scope_commit')",2),
      ("c.kind IN ('ready','gate_protect') AND","c.kind IN ('ready','gate_protect','scope_commit') AND",1),
      ("phase IN ('fenced','ready')","phase IN ('fenced','ready','scoped')",1),
      ("ready_id TEXT UNIQUE REFERENCES go_ready(ready_id) DEFERRABLE INITIALLY DEFERRED,", "ready_id TEXT UNIQUE REFERENCES go_ready(ready_id) DEFERRABLE INITIALLY DEFERRED,\n scope_commit_id TEXT UNIQUE REFERENCES gs_scope_commit(commit_id) DEFERRABLE INITIALLY DEFERRED,",1),
      ("CHECK((phase='ready')=(ready_id IS NOT NULL)),", "CHECK((phase='ready')=(ready_id IS NOT NULL)), CHECK((phase='scoped')=(scope_commit_id IS NOT NULL)),",1),
      ("NEW.phase='ready' AND p.phase='fenced'","NEW.phase IN ('ready','scoped') AND p.phase='fenced'",1),
      ("NEW.phase='ready' OR (r.previous_gate_id", "NEW.phase IN ('ready','scoped') OR (r.previous_gate_id",1),
      ("basis_kind IN ('activation','resource_recovery','gate_recovery')","basis_kind IN ('activation','resource_recovery','gate_recovery','scope')",1),
      ("activation_id TEXT REFERENCES cu_effective(change_id)","scope_assessment_id TEXT REFERENCES gs_assessment_commit(assessment_id),\n activation_id TEXT REFERENCES cu_effective(change_id)",1),
      ("CHECK((basis_kind='activation'", "CHECK((basis_kind='scope')=(scope_assessment_id IS NOT NULL)),\n CHECK((basis_kind='scope' AND activation_id IS NULL AND resource_recovery_id IS NULL AND gate_recovery_id IS NULL) OR (basis_kind='activation'",1),
      ('CREATE VIEW go_valid_plan AS','CREATE VIEW go_ordinary_plan AS',1),
      ('observer_ref TEXT NOT NULL CHECK(length(observer_ref)>0),evidence_digest TEXT NOT NULL,', 'scope_access_id TEXT REFERENCES gs_access(access_id), scope_access_revision TEXT, scope_access_digest TEXT,\n observer_ref TEXT NOT NULL CHECK(length(observer_ref)>0),evidence_digest TEXT NOT NULL,',1),
      ("'ownership','gate_fence'))","'ownership','gate_fence','scope'))",1),
    ]
    for a,b,n in changes:v=L.replace(v,a,b,n)
    v+='\n'+(HERE/'scope-storage.sql').read_text(encoding='utf-8')
    v=L.replace(v,'@GS_SUCCESSOR@',C.successor("coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=d.device_id),'00000000000000000000')"),1)
    for t in TABLES:
        for action,suffix in [('UPDATE','u'),('DELETE','d')]:
            v+=f"\nCREATE TRIGGER {t}_{suffix} BEFORE {action} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;\n"
    return v.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    target=HERE/'controller-scope.sql';data=build()
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
