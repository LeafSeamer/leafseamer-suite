"""组合准备完成与当前RUN资格；仅生成设计候选，不是产品迁移。"""
import argparse
import build_run_resource as R
HERE=R.HERE;L=R.L
TABLES=('pc_binding','pc_status_event')
SOURCES=R.SOURCES+[HERE/n for n in ('build_preparation_completion.py','preparation-completion.sql')]

def build():
    sql=R.build().decode()
    sql=L.replace(sql,'  UNIQUE(prep_key,completion_id),',
      '  UNIQUE(prep_key,completion_id),\n  FOREIGN KEY(completion_id) REFERENCES pc_binding(completion_id) DEFERRABLE INITIALLY DEFERRED,',1)
    sql+='\n'+(HERE/'preparation-completion.sql').read_text(encoding='utf-8')
    for table in TABLES:
        for op,suffix in [('UPDATE','u'),('DELETE','d')]:
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_preparation_completion'); END;\n"
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    raw=build();target=HERE/'controller-preparation-completion.sql'
    if a.check:assert target.read_bytes()==raw,'生成漂移'
    else:target.write_bytes(raw)
