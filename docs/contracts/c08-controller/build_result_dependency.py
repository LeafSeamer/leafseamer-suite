"""生成132表来源依赖组合；不执行业务迁移。"""
import argparse
from pathlib import Path
import build_protected_hold as G
HERE=Path(__file__).resolve().parent
TABLES=('cd_manifest','cd_result_source','cd_manifest_commit')
SOURCES=G.SOURCES+[HERE/'build_protected_hold.py',HERE/'result-dependency.sql']

def build():
    sql=G.L.replace(G.build().decode(),'独立保护占用129表候选','结果依赖132表候选',1)
    sql=G.L.replace(sql,' UNIQUE(validation_id,device_id)\n',
      ' UNIQUE(validation_id,device_id),\n FOREIGN KEY(validation_id) REFERENCES cd_manifest(validation_id) DEFERRABLE INITIALLY DEFERRED\n',1)
    sql+='\n'+(HERE/'result-dependency.sql').read_text(encoding='utf-8')
    for table in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;\n"
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-result-dependency.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
