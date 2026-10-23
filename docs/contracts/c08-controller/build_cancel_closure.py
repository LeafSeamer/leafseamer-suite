"""组合两阶段关闭候选；只生成设计SQL，不执行迁移。"""
import argparse
from pathlib import Path
import build_cancel_resource as G
HERE=Path(__file__).resolve().parent
L=G.G.G.L
TABLES=('cc_cut','cc_target','cc_member','cc_cut_commit','cc_attempt','cc_failure','cc_coverage',
        'cc_ack','cc_selection','cc_closure','cc_revocation','cc_prepare','cc_cut_prepare','cc_ack_prepare','cc_packet','cc_dispatch')
SOURCES=G.SOURCES+[HERE/'build_cancel_resource.py',HERE/'cancel-closure.sql']

def build():
    sql=G.build().decode()
    sql=L.replace(sql,'取消资源核销103表候选','两阶段关闭119表候选',1)
    sql=L.replace(sql,' closure_validation_body BLOB,',
        " closure_id TEXT REFERENCES cc_closure(closure_id),\n closure_validation_body BLOB,",1)
    sql=L.replace(sql," CHECK(state!='confirmed' OR future_writes='closed'),",
        " CHECK((future_writes='closed')=(closure_id IS NOT NULL)),\n CHECK(state!='confirmed' OR future_writes='closed'),",1)
    sql=L.replace(sql,' outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)\n) STRICT;\nCREATE TRIGGER ci_issue_guard',
        ' outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),\n FOREIGN KEY(permit_id) REFERENCES cc_dispatch(permit_id) DEFERRABLE INITIALLY DEFERRED\n) STRICT;\nCREATE TRIGGER ci_issue_guard',1)
    # 两类报告视图都吸收原ACK强事实，无须等到该尝试被采用。
    for old in ("WHERE c.permit_id=p.permit_id AND c.disposition='in_flight') THEN 'in_flight'",
                "WHERE c.permit_id=p.permit_id AND c.disposition='not_sent') THEN 'not_sent'"):
        state='in_flight' if 'in_flight' in old else 'not_sent'
        replacement=old.split(" THEN ")[0]+f"\n  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='{state}') THEN '{state}'"
        sql=L.replace(sql,old,replacement,3)
    sql=L.replace(sql,"'report','cancel_report','barrier_ack','target_result','validation_revocation'",
        "'report','cancel_report','barrier_ack','target_result','validation_revocation','cancel_closure_ack'",1)
    marker="   OR (NEW.source_kind='validation_revocation' AND EXISTS("
    sql=L.replace(sql,marker,"""   OR (NEW.source_kind='cancel_closure_ack' AND EXISTS(SELECT 1 FROM cc_ack a JOIN cc_coverage c USING(barrier_id)
    WHERE a.barrier_id=NEW.source_id AND c.disposition='in_flight' AND (EXISTS(SELECT 1 FROM cr_release_member m
     WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id) OR EXISTS(SELECT 1 FROM cx_release_member m
     WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id))))
"""+marker,1)
    sql+='\n'+(HERE/'cancel-closure.sql').read_text(encoding='utf-8')
    sql+='''
CREATE TRIGGER cc_ack_invalidation AFTER INSERT ON cc_ack BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT r.release_id,'cancel_closure_ack',NEW.barrier_id,NULL FROM cr_invalid_release r
 JOIN (SELECT release_id,permit_id FROM cr_release_member UNION SELECT release_id,permit_id FROM cx_release_member) m USING(release_id)
 JOIN cc_coverage c USING(permit_id) WHERE c.barrier_id=NEW.barrier_id AND c.disposition='in_flight';
END;
DROP VIEW cv_current;
CREATE VIEW cv_current AS SELECT p.* FROM cv_history p JOIN cm_current s USING(command_id,revision)
 WHERE NOT EXISTS(SELECT 1 FROM cv_cancel_revision r JOIN cc_revocation v USING(closure_id)
  WHERE r.cancellation_id=p.cancellation_id AND r.revision=p.cancellation_revision);
'''
    for t in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {t}_{suffix} BEFORE {action} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;\n"
    for t in ('cc_target','cc_member','cc_cut_prepare'):
        sql+=f"\nCREATE TRIGGER {t}_frozen BEFORE INSERT ON {t} WHEN EXISTS(SELECT 1 FROM cc_cut_commit WHERE cut_id=NEW.cut_id) BEGIN SELECT RAISE(ABORT,'closure_cut_frozen'); END;\n"
    sql+="\nCREATE TRIGGER cc_coverage_frozen BEFORE INSERT ON cc_coverage WHEN EXISTS(SELECT 1 FROM cc_ack WHERE barrier_id=NEW.barrier_id) BEGIN SELECT RAISE(ABORT,'closure_ack_frozen'); END;\n"
    sql+="\nCREATE TRIGGER cc_ack_prepare_frozen BEFORE INSERT ON cc_ack_prepare WHEN EXISTS(SELECT 1 FROM cc_ack WHERE barrier_id=NEW.barrier_id) BEGIN SELECT RAISE(ABORT,'closure_ack_frozen'); END;\n"
    sql+="\nCREATE TRIGGER cc_ack_pending_run BEFORE INSERT ON cc_ack WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-cancel-closure.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
