"""生成来源启用的独享份额预留及106表候选。"""
import argparse,json
from pathlib import Path
import build_instance_budget as B
HERE=Path(__file__).resolve().parent
VERSION='source-budget-admission/0.1.0-draft.1'
SOURCES=B.SOURCES+[HERE/'build_source_budget.py',HERE/'source-budget.sql']
def schema():
    old=B.A.schema()['$defs'];ident=old['Profile']['properties']['profile_id'];positive=old['Profile']['properties']['episodes'];sha=old['Binding']['properties']['profile_digest']
    d={'Admission':B.A.obj(contract_version={'const':VERSION},source_id=ident,expected_source_revision=old['Vector']['properties']['logical_rows'],source_key_digest=sha,
        pool_profile_digest=sha,episodes=positive,request_epoch=ident,actor=B.A.obj(principal_id=ident),idempotency_key=ident)}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/source-budget.schema.json','title':VERSION,'x-approved':False,'not':{},'$defs':d}
def schema_bytes():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
def build():
    sql=B.build().decode();marker='CREATE TABLE ingress_registry (\n source_id TEXT PRIMARY KEY NOT NULL REFERENCES ingress_source(source_id), revision TEXT NOT NULL,'
    assert sql.count(marker)==1
    sql=sql.replace(marker,marker+'\n FOREIGN KEY(source_id) REFERENCES sb_commit(source_id) DEFERRABLE INITIALLY DEFERRED,',1)
    start=sql.index('CREATE TABLE ib_use(');end=sql.index(') STRICT;',start)
    part=sql[start:end].replace('source_id TEXT NOT NULL REFERENCES ingress_source(source_id)','source_id TEXT NOT NULL REFERENCES sb_reservation(source_id)')
    sql=sql[:start]+part+sql[end:]+'\n'+(HERE/'source-budget.sql').read_text(encoding='utf-8')
    for table in ('sb_reservation','sb_commit'):
        for op in ('UPDATE','DELETE'):sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_source_budget'); END;\n"
    for table,run in (('arm_operation','NEW.run_id'),('recovery_operation','NEW.run_id'),('execution_start','NEW.run_id'),
        ('arm_ready_commit','(SELECT run_id FROM arm_operation WHERE operation_id=NEW.operation_id)'),
        ('step_ready','NEW.run_id'),('command_submission','NEW.run_id'),('submission_attempt','NEW.run_id')):
        sql+=f"\nCREATE TRIGGER sb_{table}_admission BEFORE INSERT ON {table} WHEN NOT EXISTS(SELECT 1 FROM sb_run_eligible WHERE run_id={run}) BEGIN SELECT RAISE(ABORT,'source_budget_run_unavailable'); END;\n"
    for table in ('ingress_listener','p1_dependency'):
        sql+=f"\nCREATE TRIGGER sb_{table}_admission BEFORE INSERT ON {table} WHEN NOT EXISTS(SELECT 1 FROM sb_balance WHERE source_id=NEW.source_id AND episodes_left>0) BEGIN SELECT RAISE(ABORT,'source_budget_unavailable'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for path,raw in [(HERE/'seamer-source-budget.sql',build()),(HERE/'source-budget.schema.json',schema_bytes())]:
        if a.check:assert path.read_bytes()==raw,'生成漂移'
        else:path.write_bytes(raw)
