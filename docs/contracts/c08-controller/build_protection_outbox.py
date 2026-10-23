"""生成资源失效关闭通知137表候选；不执行迁移。"""
import argparse
from pathlib import Path
import build_result_dependency as G
HERE=Path(__file__).resolve().parent
TABLES=('ro_incident','ro_target','ro_attempt','ro_ack','ro_recovery_target')
SOURCES=G.SOURCES+[HERE/'build_result_dependency.py',HERE/'protection-outbox.sql']
def build():
    sql=G.G.L.replace(G.build().decode(),'结果依赖132表候选','资源保护通知137表候选',1)
    sql=G.G.L.replace(sql,' source_exit_id TEXT,',
        ' source_exit_id TEXT,\n FOREIGN KEY(release_id) REFERENCES ro_incident(release_id) DEFERRABLE INITIALLY DEFERRED,',1)
    sql+='\n'+(HERE/'protection-outbox.sql').read_text(encoding='utf-8')
    for t in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {t}_{suffix} BEFORE {action} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-protection-outbox.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
