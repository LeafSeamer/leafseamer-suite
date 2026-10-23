"""生成普通触发到R5的组合约束，保留先前90表基线。"""
import argparse
from pathlib import Path
import build_arm_exit as A
HERE=Path(__file__).resolve().parent
SOURCES=A.SOURCES+[HERE/'build_trigger_flow.py',HERE/'trigger-flow.sql']
VERSION='trigger-flow-storage/0.1.0-draft.1'
def build():
    sql=A.build().decode();marker=" tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'R5' CHECK(tx_phase='R5'),"
    assert sql.count(marker)==1
    sql=sql.replace(marker,marker+"\n run_revision_before TEXT NOT NULL,run_revision_after TEXT NOT NULL,slot_revision TEXT NOT NULL,\n FOREIGN KEY(commit_id) REFERENCES flow_commit_seal(commit_id) DEFERRABLE INITIALLY DEFERRED,",1)
    extension=(HERE/'trigger-flow.sql').read_text(encoding='utf-8')
    for marker,expr in {'__RUN_NEXT__':'NEW.run_revision_before','__STATE_NEXT__':'NEW.source_state_revision',
        '__DECISION_NEXT__':'NEW.run_before','__SLOT_NEXT__':"json_extract(s.body,'$.slot_revision_before')"}.items():extension=extension.replace(marker,A.A.Q.R.P.successor(expr))
    sql+='\n'+extension
    fields=('run_revision_before','run_revision_after','slot_revision')
    invalid=' OR '.join(f"length(NEW.{f}) NOT BETWEEN 1 AND 20 OR NEW.{f} GLOB '*[^0-9]*' OR (NEW.{f}!='0' AND substr(NEW.{f},1,1)='0') OR instr(NEW.{f},char(0))>0" for f in fields)
    sql+=f"\nCREATE TRIGGER flow_commit_u20 BEFORE INSERT ON transition_commit WHEN {invalid} BEGIN SELECT RAISE(ABORT,'flow_commit_u20'); END;\n"
    for table in ('step_ready','command_submission'):
        extra=' AND r.dispatch_eligible=1' if table=='command_submission' else ''
        sql+=f"\nCREATE TRIGGER flow_gate_{table} BEFORE INSERT ON {table} WHEN NOT EXISTS(SELECT 1 FROM flow_active_execution e JOIN run r USING(run_id) WHERE e.execution_id=NEW.execution_id{extra}) BEGIN SELECT RAISE(ABORT,'flow_execution_inactive'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'seamer-trigger-flow.sql'
    if a.check:assert target.read_bytes()==build(),'生成漂移'
    else:target.write_bytes(build())
