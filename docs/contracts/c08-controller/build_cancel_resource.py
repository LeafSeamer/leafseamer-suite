"""固定组合取消资源核销；不修改旧候选或运行数据库迁移。"""
import argparse
from pathlib import Path
import build_cancel_fence as G
HERE=Path(__file__).resolve().parent
TABLES=('cx_closure','cx_settlement','cx_release_cancel','cx_release_member')
SOURCES=G.SOURCES+[HERE/'build_cancel_fence.py',HERE/'cancel-resource.sql']
def build():
    sql=G.G.L.remove(G.build().decode(),'TRIGGER','ci_release_coverage_pending')
    sql=G.G.L.replace(sql,'RUN取消覆盖99表候选','取消资源核销103表候选',1)
    sql=G.G.L.replace(sql,"THEN RAISE(ABORT,'cancel_resource_coverage_not_merged') END;",
        "THEN RAISE(ABORT,'cancel_after_release') END;",1)
    sql=G.G.L.replace(sql,"source_kind IN ('report','barrier_ack','target_result','validation_revocation')",
        "source_kind IN ('report','cancel_report','barrier_ack','target_result','validation_revocation')",1)
    old="   OR (NEW.source_kind='validation_revocation' AND EXISTS("
    new="""   OR (NEW.source_kind='cancel_report' AND EXISTS(SELECT 1 FROM cf_report p JOIN cx_release_member m USING(permit_id)
     WHERE p.report_id=NEW.source_id AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='barrier_ack' AND EXISTS(SELECT 1 FROM ce_barrier_ack a JOIN cf_barrier_coverage p USING(barrier_id)
     JOIN cx_release_member m USING(permit_id) WHERE a.barrier_id=NEW.source_id AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='target_result' AND EXISTS(SELECT 1 FROM ce_target_result a JOIN cf_target_coverage p USING(fence_id,exit_id)
     JOIN cx_release_member m USING(permit_id) WHERE a.fence_id=NEW.source_id AND a.exit_id=NEW.source_exit_id
      AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
"""+old
    sql=G.G.L.replace(sql,old,new,1)+'\n'+(HERE/'cancel-resource.sql').read_text(encoding='utf-8')
    for t in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {t}_{suffix} BEFORE {action} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;\n"
    for t in ('cx_release_cancel','cx_release_member'):
        sql+=f"\nCREATE TRIGGER {t}_frozen BEFORE INSERT ON {t} WHEN EXISTS(SELECT 1 FROM cr_release_commit WHERE release_id=NEW.release_id) BEGIN SELECT RAISE(ABORT,'release_frozen'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-cancel-resource.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
