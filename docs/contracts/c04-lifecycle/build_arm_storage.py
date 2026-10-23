"""组合普通布防与恢复共享身份的SQLite候选；旧布局保留。"""
import argparse,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'c05-protection'))
sys.path.append(str(HERE.parent/'c08-controller'))
import build_qualification as Q
SOURCES=Q.SOURCES+[HERE/'build_arm_storage.py',HERE/'arm-storage.sql']
TABLES=('lifecycle_operation_identity','arm_capacity','arm_preflight','arm_operation','arm_budget_reservation','arm_target','arm_register_commit','arm_attempt','arm_receipt','arm_complete','arm_ready_commit')
def build():
    sql=Q.build().decode()
    replacements={
        'FOREIGN KEY(active_operation_id,run_id) REFERENCES recovery_operation(operation_id,run_id)':'FOREIGN KEY(active_operation_id,run_id) REFERENCES lifecycle_operation_identity(operation_id,run_id)',
        " recovery_operation_id TEXT,recovery_controller_id TEXT,":""" recovery_operation_id TEXT,recovery_controller_id TEXT,
 arm_operation_id TEXT REFERENCES arm_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,arm_controller_id TEXT,""",
        ' UNIQUE(recovery_operation_id,recovery_controller_id),':''' UNIQUE(recovery_operation_id,recovery_controller_id),
 UNIQUE(arm_operation_id,arm_controller_id),
 FOREIGN KEY(arm_operation_id,arm_controller_id) REFERENCES arm_target(operation_id,controller_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((mode='arm' AND arm_operation_id IS NOT NULL AND arm_controller_id IS NOT NULL) OR(mode='recovery' AND arm_operation_id IS NULL AND arm_controller_id IS NULL)),''',
        "NEW.mode='arm' AND r.lifecycle='armed'":"""NEW.mode='arm' AND r.lifecycle='disarmed' AND r.dispatch_eligible=0 AND r.active_execution_id IS NULL
 AND r.active_operation_id=NEW.arm_operation_id AND EXISTS(SELECT 1 FROM arm_operation o WHERE o.operation_id=NEW.arm_operation_id
 AND o.run_id=r.run_id AND o.generation=NEW.generation AND NOT EXISTS(SELECT 1 FROM arm_register_commit WHERE operation_id=o.operation_id))"""
    }
    for old,new in replacements.items():
        assert sql.count(old)==1,old;sql=sql.replace(old,new,1)
    extension=(HERE/'arm-storage.sql').read_text(encoding='utf-8')
    for key,value in [('__RUN_NEXT__','NEW.run_before'),('__SLOT_NEXT__','NEW.slot_before'),('__GEN_NEXT__','NEW.generation_before'),('__COMPLETE_NEXT__','NEW.revision_before'),('__RETURN_NEXT__','OLD.revision')]:
        extension=extension.replace(key,Q.R.P.successor(value))
    sql+='\n'+extension
    for table,fields in {'arm_preflight':('run_revision','slot_revision','generation_before','issued_tick','expires_tick'),
        'arm_operation':('run_before','run_after','slot_before','slot_after','generation_before','generation','now_tick'),
        'arm_complete':('generation','revision_before','revision_after','slot_revision')}.items():
        invalid=' OR '.join(f"length(NEW.{f}) NOT BETWEEN 1 AND 20 OR NEW.{f} GLOB '*[^0-9]*' OR (NEW.{f}!='0' AND substr(NEW.{f},1,1)='0') OR instr(NEW.{f},char(0))>0" for f in fields)
        sql+=f"\nCREATE TRIGGER {table}_u20 BEFORE INSERT ON {table} WHEN {invalid} BEGIN SELECT RAISE(ABORT,'arm_u20'); END;\n"
    for table in TABLES:
        for op in ('UPDATE','DELETE'):
            if table=='arm_preflight' and op=='UPDATE':continue
            sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'seamer-arm.sql'
    if a.check:assert target.read_bytes()==build(),'生成漂移'
    else:target.write_bytes(build())
