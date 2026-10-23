"""复用资源权威组合取消独立hold；仅生成设计SQL。"""
import argparse
from pathlib import Path
import build_cancel_plan as G
HERE=Path(__file__).resolve().parent
L=G.G.L
SOURCES=G.SOURCES+[HERE/'build_cancel_plan.py',HERE/'protected-hold.sql']

def build():
    sql=G.build().decode()
    sql=L.replace(sql,'取消动作图129表候选','独立保护占用129表候选',1)
    sql=L.replace(sql,' attempt_id TEXT NOT NULL UNIQUE REFERENCES ce_attempt(attempt_id),',
        ' attempt_id TEXT UNIQUE REFERENCES ce_attempt(attempt_id),\n cancel_execution_id TEXT UNIQUE REFERENCES cg_plan(execution_id),\n cancel_release_policy_ref TEXT CHECK(cancel_release_policy_ref IS NULL OR length(cancel_release_policy_ref)>0),',1)
    sql=L.replace(sql,' UNIQUE(hold_id,command_id),',
        " CHECK((attempt_id IS NOT NULL AND cancel_execution_id IS NULL AND cancel_release_policy_ref IS NULL) OR\n  (attempt_id IS NULL AND cancel_execution_id IS NOT NULL AND cancel_release_policy_ref IS NOT NULL)),\n UNIQUE(hold_id,command_id),",1)
    sql=L.replace(sql,' release_digest TEXT NOT NULL,\n cut_body',
        ' release_digest TEXT NOT NULL,\n cancel_validation_id TEXT UNIQUE REFERENCES cr_validation(validation_id),\n cut_body',1)
    for name in ('cr_hold_guard','cm_hold_state'):
        sql=L.replace(sql,f'CREATE TRIGGER {name} BEFORE INSERT ON cr_hold BEGIN',
            f'CREATE TRIGGER {name} BEFORE INSERT ON cr_hold WHEN NEW.attempt_id IS NOT NULL BEGIN',1)
    for name in ('cr_hold_seal','cm_hold_binding'):
        sql=L.replace(sql,f'CREATE TRIGGER {name} BEFORE INSERT ON cr_hold_commit BEGIN',
            f'CREATE TRIGGER {name} BEFORE INSERT ON cr_hold_commit WHEN EXISTS(SELECT 1 FROM cr_hold WHERE hold_id=NEW.hold_id AND attempt_id IS NOT NULL) BEGIN',1)
    sql=L.replace(sql,'CREATE TRIGGER cv_no_hold BEFORE INSERT ON cr_hold\n WHEN EXISTS',
        'CREATE TRIGGER cv_no_hold BEFORE INSERT ON cr_hold\n WHEN NEW.attempt_id IS NOT NULL AND EXISTS',1)
    sql=L.replace(sql,' protected_hold_ref_body BLOB NOT NULL CHECK(length(protected_hold_ref_body)>0),',
        ' protected_hold_ref_body BLOB NOT NULL CHECK(length(protected_hold_ref_body)>0),\n protected_hold_id TEXT NOT NULL UNIQUE REFERENCES cr_hold(hold_id) DEFERRABLE INITIALLY DEFERRED,\n protected_hold_digest TEXT NOT NULL,',1)
    sql+='\n'+(HERE/'protected-hold.sql').read_text(encoding='utf-8')
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-protected-hold.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
