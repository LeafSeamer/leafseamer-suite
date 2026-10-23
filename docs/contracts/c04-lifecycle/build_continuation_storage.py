"""以既有109/230表完整布局组合转交候选，不修改旧生成产物。"""
import argparse,sqlite3,sys
from pathlib import Path
import build_source_resync as S
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'c08-controller'))
import build_prepare_deny_storage as C
import build_continuation as CONTRACT
CT=('cr_limit','cr_issue','cr_device','cr_commit','cr_revocation')
ST=('rc_limit','rc_request','rc_target','rc_request_commit','rc_receipt','rc_adoption','rc_adoption_commit','rc_r5_link')
SOURCES=list(dict.fromkeys(S.SOURCES+C.SOURCES+[HERE/n for n in
    ('build_continuation_storage.py','build_continuation.py','continuation-controller.sql','continuation-seamer.sql')]))

def append(base,file,tables):
    sql=base.decode()+'\n'+(HERE/file).read_text(encoding='utf-8')
    for t in tables:
        for op in ('UPDATE','DELETE'):
            sql+=f"\nCREATE TRIGGER {t}_{op.lower()} BEFORE {op} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;\n"
    objects=[('cr_issue','request_body','Request'),('cr_issue','receipt_body','Receipt')] if 'cr_issue' in tables else [
        ('rc_request','request_body','Request'),('rc_receipt','receipt_body','Receipt'),('rc_adoption','adoption_body','Adoption')]
    for table,column,kind in objects:
        # 只补SQL必填/类型门槛；完整Schema、JCS及摘要仍由writer验证。
        predicates=[]
        for field,shape in CONTRACT.schema()['$defs'][kind]['properties'].items():
            expected='array' if shape.get('type')=='array' else 'object' if shape.get('type')=='object' or '$ref' in shape else 'text'
            predicates.append(f"json_type(NEW.{column},'$.{field}') IS NOT '{expected}'")
        sql+=f"\nCREATE TRIGGER {table}_{column}_shape BEFORE INSERT ON {table} WHEN {' OR '.join(predicates)} BEGIN SELECT RAISE(ABORT,'continuation_body_shape'); END;\n"
    if 'cr_issue' in tables:
        fields=('contract_version','origin_scope','run_id','generation','transfer_id','recovery_operation_id','recovery_execution_id','continuation_plan_ref')
        tests=[f"json_extract(NEW.receipt_body,'$.{f}') IS NOT json_extract(NEW.request_body,'$.{f}')" for f in fields]
        tests += [f"json_extract(NEW.receipt_body,'$.{f}') IS NOT json_extract(NEW.target_body,'$.{f}')" for f in ('controller_scope','preparation_ref','recovery_grant_ref')]
        tests += ["json_extract(NEW.receipt_body,'$.continuation_grant_ref') IS NOT json_extract(NEW.grant_body,'$.ref')",
            "json_extract(NEW.grant_body,'$.request_digest') IS NOT NEW.request_digest",
            "json_extract(NEW.grant_body,'$.target_digest') IS NOT json_extract(NEW.receipt_body,'$.target_digest')",
            "json_extract(NEW.grant_body,'$.parent_preparation_ref') IS NOT json_extract(NEW.target_body,'$.preparation_ref')",
            "json_extract(NEW.grant_body,'$.plan_ref') IS NOT json_extract(NEW.request_body,'$.continuation_plan_ref')",
            "json_extract(NEW.grant_body,'$.scope') IS NOT 'run_generation'","json_extract(NEW.grant_body,'$.activation') IS NOT 'adoption_and_r5'"]
        sql+=f"\nCREATE TRIGGER cr_issue_bodies BEFORE INSERT ON cr_issue WHEN {' OR '.join(tests)} BEGIN SELECT RAISE(ABORT,'continuation_bodies'); END;\n"
    else:
        fields=('contract_version','origin_scope','run_id','generation','transfer_id','recovery_operation_id','recovery_execution_id','continuation_plan_ref','request_digest')
        for table,column in [('rc_receipt','receipt_body'),('rc_adoption','adoption_body')]:
            tests=[f"json_extract(NEW.{column},'$.{f}') IS NOT json_extract(q.request_body,'$.{f}')" for f in fields]
            sql+=f"\nCREATE TRIGGER {table}_binding BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM rc_request q WHERE q.transfer_id=NEW.transfer_id AND({' OR '.join(tests)})) BEGIN SELECT RAISE(ABORT,'continuation_request_binding'); END;\n"
    return sql.encode()

def controller_sql():return append(C.build(),'continuation-controller.sql',CT)
def seamer_sql():return append(S.build(),'continuation-seamer.sql',ST)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.parse_args()
    for name,build in [('seamer',seamer_sql),('controller',controller_sql)]:
        db=sqlite3.connect(':memory:');db.executescript(build().decode())
        print(name,len(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()));db.close()
