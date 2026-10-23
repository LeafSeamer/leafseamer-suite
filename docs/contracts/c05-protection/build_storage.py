"""组合Seamer来源保护与两类P4接收；设计候选，不执行生产迁移。"""
import argparse
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
TABLES=('p1_limit','p1_dependency','p1_preparation','p1_fault','p1_plan','p1_run','p1_dependency_member',
 'p1_execution_pin','p1_controller','p1_preparation_member','p1_submission_member','p1_commit')
SOURCES=[BASE/'c04-storage/recovery.sql',BASE/'c04-storage/dispatch.sql',BASE/'c05-ingress/ingress.sql',
 BASE/'c08-controller/protection-receiver.sql',BASE/'c08-controller/preparation-receiver.sql',HERE/'build_storage.py',HERE/'storage.sql']
def successor(expr):
    pad=f"substr('00000000000000000000'||{expr},-20)"
    return f"ltrim(printf('%010d%010d',CAST(substr({pad},1,10) AS INTEGER)+(substr({pad},11,10)='9999999999'),(CAST(substr({pad},11,10) AS INTEGER)+1)%10000000000),'0')"
def extension():
    sql='\n'.join(p.read_text(encoding='utf-8') for p in SOURCES[2:5])
    for prefix in ('sp','po'):
        marker=f' FOREIGN KEY(plan_id) REFERENCES {prefix}_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED'
        assert sql.count(marker)==1
        sql=sql.replace(marker,' FOREIGN KEY(plan_id) REFERENCES p1_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,\n'+marker,1)
    fragment=(HERE/'storage.sql').read_text(encoding='utf-8')
    for marker,expr in {'__SOURCE_NEXT__':'NEW.source_before','__RUN_NEXT__':'NEW.revision_before'}.items():fragment=fragment.replace(marker,successor(expr))
    sql+='\n'+fragment
    for table in TABLES+('po_plan','po_target','po_plan_commit','po_observation','po_observation_commit','po_conflict'):
        for op,suffix in [('UPDATE','u'),('DELETE','d')]:
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;\n"
    for table in ('p1_run','p1_dependency_member','p1_execution_pin','p1_controller','p1_preparation_member','p1_submission_member'):
        sql+=f"\nCREATE TRIGGER {table}_sealed BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM p1_commit WHERE plan_id=NEW.plan_id) BEGIN SELECT RAISE(ABORT,'source_plan_sealed'); END;\n"
    return sql.encode()
def build():return ('\n'.join(p.read_text(encoding='utf-8') for p in SOURCES[:2])+'\n').encode()+extension()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    target=HERE/'seamer-protection.sql';raw=build()
    if a.check:assert target.read_bytes()==raw,'生成漂移'
    else:target.write_bytes(raw)
