"""只在明确新grant关联成立时扩展两个准备守卫，保持旧execution约束。"""
import argparse,sqlite3
from pathlib import Path
import build_continuation_storage as B
HERE=Path(__file__).resolve().parent
SOURCES=B.SOURCES+[HERE/n for n in ('build_continuation_trigger.py','continuation-trigger.sql','continuation-command.sql')]

def append(sql,file,tables):
    sql+='\n'+(HERE/file).read_text(encoding='utf-8')
    for table in tables:
        for op in ('UPDATE','DELETE'):sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_continuation_link'); END;\n"
    return sql.encode()

def amend(sql,name,new_condition):
    parts=[];pending='';count=0
    old='p.execution_id IS NULL OR p.execution_id=e.execution_id'
    for line in sql.splitlines(keepends=True):
        pending+=line
        if sqlite3.complete_statement(pending):
            if 'CREATE TRIGGER '+name+' ' in pending:
                assert pending.count(old)==1;pending=pending.replace(old,old+' OR '+new_condition);count+=1
            parts.append(pending);pending=''
    assert count==1;return ''.join(parts)+pending

def seamer_sql():
    sql=B.seamer_sql().decode()
    for trigger,step in [('rs_plan_preparation','a.step_id'),('flow_submission_target','NEW.step_id')]:
        condition=f"EXISTS(SELECT 1 FROM cn_step n JOIN cn_current c USING(transfer_id,registration_id) WHERE n.execution_id=e.execution_id AND n.step_id={step} AND n.registration_id=p.registration_id AND n.adoption_digest=c.adoption_digest)"
        sql=amend(sql,trigger,condition)
    return append(sql,'continuation-trigger.sql',('cn_step','cn_withdrawal'))

def controller_sql():return append(B.controller_sql().decode(),'continuation-command.sql',('cn_command',))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.parse_args()
    for name,fn in [('seamer',seamer_sql),('controller',controller_sql)]:
        db=sqlite3.connect(':memory:');db.executescript(fn().decode());print(name,len(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()));db.close()
