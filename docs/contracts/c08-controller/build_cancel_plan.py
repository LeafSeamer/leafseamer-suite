"""组合取消图与完成证据候选，仅生成离线SQL资料。"""
import argparse
from pathlib import Path
import build_cancel_closure as G
HERE=Path(__file__).resolve().parent
TABLES=('cg_plan','cg_resource','cg_primitive','cg_dependency','cg_plan_commit','cg_result',
        'cg_result_member','cg_result_commit','cg_revocation','cg_dispatch_dependency')
SOURCES=G.SOURCES+[HERE/'build_cancel_closure.py',HERE/'cancel-plan.sql']

def build():
    sql=G.L.replace(G.build().decode(),'两阶段关闭119表候选','取消动作图129表候选',1)
    sql+='\n'+(HERE/'cancel-plan.sql').read_text(encoding='utf-8')
    for t in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {t}_{suffix} BEFORE {action} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;\n"
    for t in ('cg_resource','cg_primitive','cg_dependency'):
        sql+=f"\nCREATE TRIGGER {t}_frozen BEFORE INSERT ON {t} WHEN EXISTS(SELECT 1 FROM cg_plan_commit WHERE execution_id=NEW.execution_id) BEGIN SELECT RAISE(ABORT,'plan_frozen'); END;\n"
    sql+="\nCREATE TRIGGER cg_result_member_frozen BEFORE INSERT ON cg_result_member WHEN EXISTS(SELECT 1 FROM cg_result_commit WHERE result_id=NEW.result_id) BEGIN SELECT RAISE(ABORT,'result_frozen'); END;\n"
    sql+="\nCREATE TRIGGER cg_dispatch_dependency_frozen BEFORE INSERT ON cg_dispatch_dependency WHEN EXISTS(SELECT 1 FROM ci_cancel_commit WHERE permit_id=NEW.permit_id) BEGIN SELECT RAISE(ABORT,'dispatch_dependency_frozen'); END;\n"
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-cancel-plan.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
