"""在来源独享预算候选上增加持续增长与完整动作计划准入。"""
import argparse
from pathlib import Path
import build_source_budget as B
HERE=Path(__file__).resolve().parent
SOURCES=B.SOURCES+[HERE/'build_workload_budget.py',HERE/'workload-budget.sql']
DIMENSIONS=('dependencies','runs','executions','preparations','submissions','controller_targets')

def build():
    sql=B.build().decode()+'\n'+(HERE/'workload-budget.sql').read_text(encoding='utf-8')
    limits=' OR '.join(f"s.{d}>CAST(json_extract(b.budget_body,'$.binding.forecast.{d}') AS INTEGER)" for d in DIMENSIONS)
    sql+=f"\nCREATE VIEW wb_overflow AS SELECT s.* FROM wb_shape s JOIN protection_budget_reservation b USING(operation_id) JOIN pb_balance p USING(operation_id) WHERE p.episodes_left>0 AND ({limits});\n"
    # AFTER检查包括NEW在内的完整库存，RAISE回滚当前语句；writer回滚整个事务。
    for table,run in (('execution','NEW.run_id'),('p1_preparation','NEW.run_id'),('p1_dependency','NEW.run_id'),
        ('command_submission','NEW.run_id'),('execution_step_plan','(SELECT run_id FROM execution WHERE execution_id=NEW.execution_id)')):
        sql+=f"\nCREATE TRIGGER wb_{table}_growth AFTER INSERT ON {table} WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE run_id={run}) BEGIN SELECT RAISE(ABORT,'workload_budget_exceeded'); END;\n"
    for table in ('arm_register_commit','recovery_budget_commit'):
        sql+=f"\nCREATE TRIGGER wb_{table}_fit BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE operation_id=NEW.operation_id) BEGIN SELECT RAISE(ABORT,'workload_budget_seal'); END;\n"
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'seamer-workload-budget.sql'
    if a.check:assert target.read_bytes()==build(),'生成漂移'
    else:target.write_bytes(build())
