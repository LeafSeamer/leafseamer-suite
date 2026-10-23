"""生成开放持久化候选；只输出设计SQL，不执行产品迁移。"""
import argparse
from pathlib import Path
import build_control_fence as G
import build_control_storage as C
import build_layout as L
HERE=Path(__file__).resolve().parent
SOURCES=G.SOURCES+[HERE/'build_open_storage.py',HERE/'open-storage.sql']
TABLES=('go_hazard','go_snapshot','go_hold','go_snapshot_commit','go_gate','go_plan','go_plan_commit',
 'go_dispatch','go_evidence','go_ready','go_close','go_close_ack','go_recovery','go_recovery_target','go_recovery_commit','go_revocation','go_exit_obligation')
def build():
    sql=G.build().decode()
    replacements=[
      ("'retry','restart','effective'))","'retry','restart','effective','ready','gate_protect'))",1),
      ("'reject','restart','effective') THEN change_id","'reject','restart','effective','ready','gate_protect') THEN change_id",1),
      ("gate_state IN ('protected','fencing')","gate_state IN ('protected','fencing','ready')",1),
      ("((c.kind='effective' AND s.reserved_version", "((c.kind='ready' AND s.reserved_version=p.reserved_version AND p.pending_operation_id IS NULL AND s.pending_operation_id IS NULL AND s.gate_state='ready') OR\n      (c.kind='gate_protect' AND s.reserved_version=p.reserved_version AND s.pending_operation_id IS p.pending_operation_id AND s.gate_state='protected') OR\n      (c.kind='effective' AND s.reserved_version",1),
    ]
    for a,b,n in replacements:sql=L.replace(sql,a,b,n)
    sql+='\n'+(HERE/'open-storage.sql').read_text(encoding='utf-8')
    sql=sql.replace('@SUCCESSOR_GATE@',C.successor('p.record_revision'))
    sql=sql.replace('@SUCCESSOR_HAZARD@',C.successor("coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=NEW.device_id),'00000000000000000000')"))
    sql=sql.replace('@SUCCESSOR_CLOSE@',C.successor("coalesce((SELECT max(revision) FROM go_close WHERE exit_id=NEW.exit_id),'00000000000000000000')"))
    # 实际来源同事务锁存，恢复或删除当前风险不能复活旧cut。
    hooks=[
      ('cr_release_invalidation','release','NEW.release_id',"SELECT c.device_id FROM cr_release r JOIN ce_command c USING(command_id) WHERE r.release_id=NEW.release_id"),
      ('cr_validation_revocation','validation','NEW.validation_id',"SELECT device_id FROM cr_validation WHERE validation_id=NEW.validation_id"),
      ('cu_revocation','control','NEW.kind||\':\'||NEW.object_id',"SELECT DISTINCT c.device_id FROM cu_selection s JOIN cu_effective f USING(change_id) JOIN ct_change c USING(change_id) WHERE (NEW.kind='ack' AND s.barrier_id=NEW.object_id) OR (NEW.kind='retirement' AND s.retirement_exit_id=NEW.object_id)"),
      ('cm_commit','command','NEW.operation_id',"SELECT c.device_id FROM cm_revision r JOIN ce_command c USING(command_id) WHERE r.operation_id=NEW.operation_id AND (r.resource_status='unresolved' OR r.outcome='unknown')"),
      ('ce_report','report','NEW.report_id',"SELECT e.device_id FROM ce_permit p JOIN ce_exit e USING(exit_id) WHERE p.permit_id=NEW.permit_id AND NEW.disposition='unknown'"),
      ('cf_report','cancel_report','NEW.report_id',"SELECT e.device_id FROM ci_cancel_transmission p JOIN ce_exit e USING(exit_id) WHERE p.permit_id=NEW.permit_id AND NEW.disposition='unknown'"),
      ('go_close','close','NEW.close_id',"SELECT NEW.device_id AS device_id"),
      ('go_revocation','open_revocation',"NEW.kind||':'||NEW.object_id","SELECT s.device_id FROM go_evidence e JOIN go_dispatch d USING(dispatch_id) JOIN go_plan p USING(plan_id) JOIN go_snapshot s USING(snapshot_id) WHERE NEW.kind='open_ack' AND e.evidence_id=NEW.object_id UNION SELECT x.device_id FROM go_close_ack a JOIN go_close x USING(close_id) WHERE NEW.kind='close_ack' AND a.ack_id=NEW.object_id"),
      ('go_recovery','recovery','NEW.recovery_id',"SELECT NEW.device_id AS device_id"),
      ('ce_exit','exit','NEW.exit_id',"SELECT NEW.device_id AS device_id"),
    ]
    for table,kind,identity,devices in hooks:
        successor=C.successor("coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000')")
        recovery='NEW.recovery_id' if kind=='recovery' else 'NULL'
        sql+=f"\nCREATE TRIGGER go_{table}_hazard AFTER INSERT ON {table} BEGIN\n INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'{kind}',{identity},{successor},{recovery} FROM ({devices}) d;\nEND;\n"
    sources={
      'release':"SELECT c.device_id FROM cr_release_invalidation x JOIN cr_release r USING(release_id) JOIN ce_command c USING(command_id) WHERE x.release_id=NEW.source_id",
      'validation':"SELECT v.device_id FROM cr_validation_revocation x JOIN cr_validation v USING(validation_id) WHERE x.validation_id=NEW.source_id",
      'control':"SELECT DISTINCT c.device_id FROM cu_revocation x JOIN cu_selection s ON (x.kind='ack' AND x.object_id=s.barrier_id) OR (x.kind='retirement' AND x.object_id=s.retirement_exit_id) JOIN cu_effective f USING(change_id) JOIN ct_change c USING(change_id) WHERE x.kind||':'||x.object_id=NEW.source_id",
      'command':"SELECT c.device_id FROM cm_revision r JOIN cm_commit k USING(operation_id) JOIN ce_command c USING(command_id) WHERE r.operation_id=NEW.source_id AND (r.resource_status='unresolved' OR r.outcome='unknown')",
      'report':"SELECT e.device_id FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN ce_exit e ON e.exit_id=p.exit_id WHERE r.report_id=NEW.source_id AND r.disposition='unknown'",
      'cancel_report':"SELECT e.device_id FROM cf_report r JOIN ci_cancel_transmission p USING(permit_id) JOIN ce_exit e ON e.exit_id=p.exit_id WHERE r.report_id=NEW.source_id AND r.disposition='unknown'",
      'close':"SELECT device_id FROM go_close WHERE close_id=NEW.source_id",
      'open_revocation':"SELECT s.device_id FROM go_revocation x JOIN go_evidence e ON x.kind='open_ack' AND x.object_id=e.evidence_id JOIN go_dispatch d USING(dispatch_id) JOIN go_plan p USING(plan_id) JOIN go_snapshot s USING(snapshot_id) WHERE x.kind||':'||x.object_id=NEW.source_id UNION SELECT c.device_id FROM go_revocation x JOIN go_close_ack a ON x.kind='close_ack' AND x.object_id=a.ack_id JOIN go_close c USING(close_id) WHERE x.kind||':'||x.object_id=NEW.source_id",
      'recovery':"SELECT device_id FROM go_recovery WHERE recovery_id=NEW.source_id",
      'exit':"SELECT device_id FROM ce_exit WHERE exit_id=NEW.source_id",
    }
    for kind,query in sources.items():
        sql+=f"\nCREATE TRIGGER go_hazard_{kind}_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='{kind}' AND NOT EXISTS(SELECT 1 FROM ({query}) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;\n"
    for table in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;\n"
    for table,key,seal in [('go_hold','snapshot_id','go_snapshot_commit'),('go_recovery_target','recovery_id','go_recovery_commit')]:
        sql+=f"\nCREATE TRIGGER {table}_sealed BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {seal} WHERE {key}=NEW.{key}) BEGIN SELECT RAISE(ABORT,'open_members_sealed'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'controller-open.sql';data=build()
    if a.check:assert path.read_bytes()==data,'生成漂移'
    else:path.write_bytes(data)
