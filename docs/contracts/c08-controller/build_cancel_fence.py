"""固定94表加RUN取消覆盖，保留旧候选；不运行产品迁移。"""
import argparse
from pathlib import Path
import build_issue_ledger as G
HERE=Path(__file__).resolve().parent
SOURCES=G.SOURCES+[HERE/'build_issue_ledger.py',HERE/'build_layout.py',HERE/'cancel-fence.sql']
TABLES=('cf_report','cf_settlement','cf_run_item','cf_barrier_coverage','cf_target_coverage')
def build():
    sql=G.L.remove(G.build().decode(),'TRIGGER','ci_run_coverage_pending')
    sql=G.L.replace(sql,'共享签发94表候选','RUN取消覆盖99表候选',1)
    sql+='\n'+(HERE/'cancel-fence.sql').read_text(encoding='utf-8')
    for table in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;\n"
    # 封存至来源提交的同一事务窗口内不能改变已捕获事实。
    for table in ('cf_report','cf_settlement','cf_barrier_coverage','cf_target_coverage'):
        sql+=f"\nCREATE TRIGGER {table}_cut BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;\n"
    sql+="\nCREATE TRIGGER cf_ack_cut BEFORE INSERT ON ce_barrier_ack WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-cancel-fence.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
