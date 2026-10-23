"""恢复R2新预留与R4重检候选；保留原99表产物。"""
import argparse
from pathlib import Path
import build_protection_charge as C
HERE=Path(__file__).resolve().parent
SOURCES=C.SOURCES+[HERE/'build_recovery_budget.py',HERE/'recovery-budget.sql']
DIMENSIONS=C.DIMENSIONS
def build():
    sql=C.build().decode()
    marker=' FOREIGN KEY(operation_id) REFERENCES pr_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,'
    assert sql.count(marker)==1
    sql=sql.replace(marker,marker+'\n FOREIGN KEY(operation_id) REFERENCES recovery_budget_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,',1)
    start=sql.index('CREATE TRIGGER arm_budget_guard ');end=sql.index('CREATE TABLE arm_target(',start)
    guard=sql[start:end]
    # 两类预留共计实例持有+消费；消费或applied不产生可重新出售的容量。
    shared=guard.replace('FROM arm_budget_reservation','FROM protection_budget_reservation')
    sql=sql[:start]+shared+sql[end:]
    recovery=shared.replace('arm_budget_guard','recovery_budget_guard').replace('BEFORE INSERT ON arm_budget_reservation','BEFORE INSERT ON recovery_budget_reservation')
    recovery=recovery.replace('JOIN arm_operation o ON o.operation_id=NEW.operation_id','JOIN recovery_budget_operation o ON o.operation_id=NEW.operation_id').replace("'arm_budget_","'recovery_budget_")
    sql=sql.replace('operation_id TEXT NOT NULL REFERENCES arm_budget_reservation(operation_id),ordinal','operation_id TEXT NOT NULL REFERENCES budget_account(operation_id),ordinal')
    sql=sql.replace('JOIN arm_operation o ON o.run_id=a.run_id AND o.generation=a.generation','JOIN budget_account o ON o.run_id=a.run_id AND o.generation=a.generation')
    # 只改保护消费查询，不改arm自己的原件FK和就绪流程。
    start=sql.index('CREATE VIEW pb_expected_account ')
    tail=sql[start:].replace('arm_budget_reservation b','protection_budget_reservation b').replace('JOIN arm_operation o USING(operation_id)','JOIN budget_account o USING(operation_id)')
    sql=sql[:start]+tail+'\n'+(HERE/'recovery-budget.sql').read_text(encoding='utf-8')+'\n'+recovery
    for table in ('budget_account','recovery_budget_reservation','recovery_budget_commit'):
        for op in ('UPDATE','DELETE'):
            sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_recovery_budget'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'seamer-recovery-budget.sql'
    if a.check:assert target.read_bytes()==build(),'生成漂移'
    else:target.write_bytes(build())
