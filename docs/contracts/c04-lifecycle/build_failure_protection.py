"""组合动作终态与独立保护账本；旧91表候选保持独立。"""
import argparse
from pathlib import Path
import build_trigger_flow as F
HERE=Path(__file__).resolve().parent
SOURCES=F.SOURCES+[HERE/'build_failure_protection.py',HERE/'failure-protection.sql']
def build():
    sql=F.build().decode()
    changes={
      " CHECK((source_plan IS NOT NULL)+(preparation_plan IS NOT NULL)+(arm_exit_plan IS NOT NULL)=1),\n CHECK(coalesce(source_plan,preparation_plan,arm_exit_plan)=plan_id)":
      " failure_plan TEXT UNIQUE REFERENCES sf_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,\n CHECK((source_plan IS NOT NULL)+(preparation_plan IS NOT NULL)+(arm_exit_plan IS NOT NULL)+(failure_plan IS NOT NULL)=1),\n CHECK(coalesce(source_plan,preparation_plan,arm_exit_plan,failure_plan)=plan_id)",
      "VALUES(NEW.plan_id,NEW.plan_id,NULL,NULL)":"VALUES(NEW.plan_id,NEW.plan_id,NULL,NULL,NULL)",
      "VALUES(NEW.plan_id,NULL,NEW.plan_id,NULL)":"VALUES(NEW.plan_id,NULL,NEW.plan_id,NULL,NULL)",
      "VALUES(NEW.plan_id,NULL,NULL,NEW.plan_id)":"VALUES(NEW.plan_id,NULL,NULL,NEW.plan_id,NULL)",
      "FROM aa_stop) GROUP BY run_id;":"FROM aa_stop\n UNION ALL SELECT p.run_id,substr('00000000000000000000'||p.generation,-20) FROM sf_plan p JOIN sf_commit c USING(plan_id)) GROUP BY run_id;",
      " tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'STEP_TERMINAL' CHECK(tx_phase='STEP_TERMINAL'),":
      " protection_plan_id TEXT UNIQUE REFERENCES sf_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,\n tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'STEP_TERMINAL' CHECK(tx_phase='STEP_TERMINAL'),"
    }
    for old,new in changes.items():assert sql.count(old)==1,old;sql=sql.replace(old,new,1)
    sql+='\n'+(HERE/'failure-protection.sql').read_text(encoding='utf-8').replace('__NEXT__',F.A.A.Q.R.P.successor('NEW.revision_before'))
    for table in ('sf_plan','sf_target','sf_commit'):
        for op in ('UPDATE','DELETE'):sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_failure_protection'); END;\n"
    fields=('generation','current_generation','revision_before','revision_after','slot_revision')
    invalid=' OR '.join(f"length(NEW.{f}) NOT BETWEEN 1 AND 20 OR NEW.{f} GLOB '*[^0-9]*' OR (NEW.{f}!='0' AND substr(NEW.{f},1,1)='0') OR instr(NEW.{f},char(0))>0" for f in fields)
    sql+=f"\nCREATE TRIGGER sf_plan_u20 BEFORE INSERT ON sf_plan WHEN {invalid} BEGIN SELECT RAISE(ABORT,'failure_u20'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'seamer-failure-protection.sql'
    if a.check:assert target.read_bytes()==build(),'生成漂移'
    else:target.write_bytes(build())
