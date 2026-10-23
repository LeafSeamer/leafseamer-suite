"""为全部已登记保护计划添加按run/代次的预留消费约束。"""
import argparse
from pathlib import Path
import build_protection_retry as R
HERE=Path(__file__).resolve().parent
SOURCES=R.SOURCES+[HERE/'build_protection_charge.py',HERE/'protection-charge.sql']
DIMENSIONS=('logical_rows','logical_bytes','queue_slots','work_units')
def build():
    sql=R.build().decode();old=' CHECK(coalesce(source_plan,preparation_plan,arm_exit_plan,failure_plan,retry_plan)=plan_id)'
    assert sql.count(old)==1;sql=sql.replace(old,old+',\n FOREIGN KEY(plan_id) REFERENCES pb_commit(plan_id) DEFERRABLE INITIALLY DEFERRED',1)
    sql+='\n'+(HERE/'protection-charge.sql').read_text(encoding='utf-8')
    for table in ('pb_use','pb_commit'):
        for op in ('UPDATE','DELETE'):sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_protection_charge'); END;\n"
    spent=','.join(f'coalesce(sum(u.{d}),0) AS spent_{d},b.{d}-coalesce(sum(u.{d}),0) AS held_{d}' for d in DIMENSIONS)
    sql+=f"\nCREATE VIEW pb_balance AS SELECT b.operation_id,o.run_id,o.generation,CAST(json_extract(c.profile_body,'$.episodes') AS INTEGER)-count(u.plan_id) AS episodes_left,{spent} FROM arm_budget_reservation b JOIN arm_operation o USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest LEFT JOIN pb_use u USING(operation_id) GROUP BY b.operation_id;\n"
    guard=' AND '.join(f'NEW.{d}=b.{d}/CAST(json_extract(c.profile_body,\'$.episodes\') AS INTEGER)' for d in DIMENSIONS)
    sql+=f"\nCREATE TRIGGER pb_cost BEFORE INSERT ON pb_use WHEN NOT EXISTS(SELECT 1 FROM arm_budget_reservation b JOIN arm_capacity c ON c.profile_digest=b.profile_digest WHERE b.operation_id=NEW.operation_id AND {guard}) BEGIN SELECT RAISE(ABORT,'protection_charge_vector'); END;\n"
    stale=' OR '.join(f"json_extract(u.shape_body,'$.{d}') IS NOT CAST(s.{d} AS TEXT)" for d in ('dependencies','runs','executions','preparations','submissions','controller_targets'))
    sql+=f"\nCREATE TRIGGER pb_shape_final BEFORE INSERT ON pb_commit WHEN EXISTS(SELECT 1 FROM pb_use u JOIN pb_shape s USING(plan_id,run_id,generation) WHERE u.plan_id=NEW.plan_id AND ({stale})) BEGIN SELECT RAISE(ABORT,'protection_charge_final_shape'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'seamer-protection-charge.sql'
    if a.check:assert target.read_bytes()==build(),'生成漂移'
    else:target.write_bytes(build())
