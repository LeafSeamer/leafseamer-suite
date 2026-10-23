"""生成控制屏障与生效候选；不执行迁移或设备动作。"""
import argparse
from pathlib import Path
import build_control_storage as G
import build_layout as L
HERE=Path(__file__).resolve().parent
TABLES=('cu_cut','cu_target','cu_member','cu_queued','cu_delivery','cu_coverage','cu_ack',
        'cu_authorization','cu_selection','cu_effective','cu_effective_member','cu_revocation','cu_protection')
SOURCES=G.SOURCES+[HERE/'build_control_fence.py',HERE/'control-fence.sql']

def build():
    sql=G.build().decode()
    # 只升级控制子域的精确语句，不改变历史148表生成物。
    replacements=[
     ("'cancel','expire','unknown','reject','retry','restart'))", "'cancel','expire','unknown','reject','retry','restart','effective'))",1),
     ("'unknown','reject','restart') THEN change_id", "'unknown','reject','restart','effective') THEN change_id",1),
     ("kind IN ('accept','acquire','release','unknown','reject','retry')", "kind IN ('accept','acquire','release','unknown','reject','retry','effective')",1),
     ("state IN ('pending','indeterminate','rejected')", "state IN ('pending','indeterminate','rejected','effective')",1),
     ("state='pending' AND failure_code IS NULL", "state IN ('pending','effective') AND failure_code IS NULL",1),
     ("state!='pending' AND failure_code IS NOT NULL", "state NOT IN ('pending','effective') AND failure_code IS NOT NULL",1),
     (f"s.effective_version=p.effective_version AND s.mode=p.mode AND {G.same('s.holder','p.holder')} AND", f"(c.kind='effective' OR (s.effective_version=p.effective_version AND s.mode=p.mode AND {G.same('s.holder','p.holder')})) AND",1),
     ("((c.kind IN ('acquire','release','accept') AND p.pending_operation_id", "((c.kind='effective' AND s.reserved_version=p.reserved_version AND p.pending_operation_id IS c.operation_id AND s.pending_operation_id IS NULL AND s.gate_state='protected') OR\n      (c.kind IN ('acquire','release','accept') AND p.pending_operation_id",1),
     ("c.kind IN ('unknown','reject','retry') AND NOT EXISTS", "c.kind IN ('unknown','reject','retry','effective') AND NOT EXISTS",1),
     ("((c.kind='unknown' AND e.state='indeterminate'", "((c.kind='effective' AND e.state='effective' AND e.attempt_id=p.attempt_id) OR\n      (c.kind='unknown' AND e.state='indeterminate'",1),
    ]
    for a,b,n in replacements:sql=L.replace(sql,a,b,n)
    # 原ACK中的强事实立即进入唯一普通/取消分类，采用与否不影响事实保留。
    for state in ('in_flight','not_sent'):
        old=f"OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='{state}') THEN '{state}'"
        guard=" AND NOT EXISTS(SELECT 1 FROM cu_revocation r WHERE r.kind='ack' AND r.object_id=k.barrier_id)" if state=='not_sent' else ''
        new=old.split(' THEN ')[0]+f"\n  OR EXISTS(SELECT 1 FROM cu_coverage z JOIN cu_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='{state}'{guard}) THEN '{state}'"
        sql=L.replace(sql,old,new,3)
    sql=L.replace(sql,"'validation_revocation','cancel_closure_ack'","'validation_revocation','cancel_closure_ack','control_ack','control_ack_revocation'",1)
    # 撤回时原子失效已有核销，不把该撤回永久套到后来独立取证的新核销。
    sql=L.replace(sql,"SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_invalid_release WHERE release_id=NEW.release_id)",
      "SELECT CASE WHEN NEW.source_kind!='control_ack_revocation' AND NOT EXISTS(SELECT 1 FROM cr_invalid_release WHERE release_id=NEW.release_id)",1)
    marker="   OR (NEW.source_kind='validation_revocation' AND EXISTS("
    sql=L.replace(sql,marker,"""   OR (NEW.source_kind='control_ack_revocation' AND EXISTS(SELECT 1 FROM cu_revocation v JOIN cu_coverage c ON c.barrier_id=v.object_id
    WHERE v.kind='ack' AND v.object_id=NEW.source_id AND c.disposition='not_sent' AND (EXISTS(SELECT 1 FROM cr_release_member m
     JOIN ce_settlement s USING(settlement_id) WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id AND s.kind='never_sent') OR EXISTS(SELECT 1 FROM cx_release_member m
     JOIN cf_settlement s USING(settlement_id) WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id AND s.kind='never_sent'))))
   OR (NEW.source_kind='control_ack' AND EXISTS(SELECT 1 FROM cu_ack a JOIN cu_coverage c USING(barrier_id)
    WHERE a.barrier_id=NEW.source_id AND c.disposition='in_flight' AND (EXISTS(SELECT 1 FROM cr_release_member m
     WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id) OR EXISTS(SELECT 1 FROM cx_release_member m
     WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id))))
"""+marker,1)
    extra=(HERE/'control-fence.sql').read_text(encoding='utf-8')
    sql+='\n'+extra
    # 同一组完整条件还必须在ct_commit最终封存前重核，不能依赖先前选择时的快照。
    guard=extra.split('CREATE TRIGGER cu_effective_guard BEFORE INSERT ON cu_effective BEGIN\n',1)[1].split('\nEND;',1)[0]
    guard=guard.replace('NEW.operation_id','(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id)')
    guard=guard.replace('NEW.attempt_id','(SELECT attempt_id FROM cu_effective WHERE change_id=NEW.change_id)')
    sql+="\nCREATE TRIGGER cu_effective_recheck BEFORE INSERT ON ct_commit WHEN EXISTS(SELECT 1 FROM ct_change WHERE change_id=NEW.change_id AND kind='effective') BEGIN\n"+guard+'\nEND;\n'
    for t in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {t}_{suffix} BEFORE {action} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;\n"
    for t in ('cu_target','cu_member','cu_queued'):
        sql+=f"\nCREATE TRIGGER {t}_sealed BEFORE INSERT ON {t} WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ct_commit k USING(change_id) WHERE c.operation_id=NEW.operation_id) BEGIN SELECT RAISE(ABORT,'control_cut_sealed'); END;\n"
    for t in ('cu_authorization','cu_selection','cu_effective','cu_effective_member'):
        sql+=f"\nCREATE TRIGGER {t}_sealed BEFORE INSERT ON {t} WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_effective_sealed'); END;\n"
    for table in ('ce_permit','ci_cancel_transmission'):
        # 受理控制前的老permit仍可保留；登记控制后没有ReadyCommit则不准新许可。
        sql+=f"\nCREATE TRIGGER cu_{table}_gate BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM ce_exit e JOIN ct_current_state s USING(device_id) WHERE e.exit_id=NEW.exit_id) OR EXISTS(SELECT 1 FROM ce_exit e JOIN cu_cut c USING(device_id) WHERE e.exit_id=NEW.exit_id) BEGIN SELECT RAISE(ABORT,'control_gate_not_ready'); END;\n"
    for table,permit in (('ce_transmission_commit','ce_permit'),('ci_cancel_commit','ci_cancel_transmission')):
        sql+=f"\nCREATE TRIGGER cu_{table}_gate BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {permit} p JOIN ce_exit e USING(exit_id) WHERE p.permit_id=NEW.permit_id AND (EXISTS(SELECT 1 FROM ct_current_state s WHERE s.device_id=e.device_id) OR EXISTS(SELECT 1 FROM cu_cut c WHERE c.device_id=e.device_id))) BEGIN SELECT RAISE(ABORT,'control_gate_not_ready'); END;\n"
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-control-fence.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
