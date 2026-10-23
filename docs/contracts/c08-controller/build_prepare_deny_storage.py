"""把DENY与准备全集直接配对既有关闭事务，生成新的设计候选。"""
import argparse
import build_ipc_journal_storage as J
import build_layout as L
HERE=J.HERE
TABLES=('pd_registration','pd_cut','pd_member','pd_cut_commit','pd_deny_request','pd_deny_ack',
        'pd_ack_revocation','pd_closure','pd_coverage','pd_closure_commit','pd_close_completion')
SOURCES=J.SOURCES+[HERE/'build_prepare_deny_storage.py',HERE/'prepare-deny-storage.sql']

def build():
    sql=J.build().decode()
    sql=L.replace(sql,'UNIQUE(proposed_attempt_id,primitive_id),',
      'UNIQUE(proposed_attempt_id,primitive_id),\n FOREIGN KEY(prepare_id) REFERENCES pd_registration(prepare_id) DEFERRABLE INITIALLY DEFERRED,',1)
    for table in ('cu_cut','cc_cut','ce_fence','go_close'):
        space=' ' if table in ('cc_cut','ce_fence') else ''
        sql=L.replace(sql,f'CREATE TABLE {table}{space}(\n',f'CREATE TABLE {table}{space}(\n prepare_cut_id TEXT NOT NULL UNIQUE REFERENCES pd_cut(cut_id) DEFERRABLE INITIALLY DEFERRED,\n',1)
    for table in ('cu_effective','cc_closure','ce_application'):
        space='' if table=='cu_effective' else ' '
        sql=L.replace(sql,f'CREATE TABLE {table}{space}(\n',f'CREATE TABLE {table}{space}(\n prepare_closure_id TEXT NOT NULL REFERENCES pd_closure_commit(closure_id),\n',1)
    marker="(f.domain_kind='handshake' AND NEW.disposition='applied'"
    additions="(f.domain_kind='prepare_deny_request' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM pd_deny_request d WHERE d.deny_id=f.domain_id AND d.journal_frame_id=f.frame_id)) OR\n (f.domain_kind='prepare_deny_ack' AND NEW.disposition IN ('applied','historical') AND EXISTS(SELECT 1 FROM pd_deny_ack d WHERE d.ack_id=f.domain_id AND d.journal_frame_id=f.frame_id)) OR\n "
    sql=L.replace(sql,marker,additions+marker,1)
    fragment=(HERE/'prepare-deny-storage.sql').read_text(encoding='utf-8')
    for column in ('selected_tick','committed_tick','effective_tick','received_tick'):
        fragment=fragment.replace(column+' TEXT NOT NULL,',column+f" TEXT NOT NULL CHECK(length({column})=20 AND {column} NOT GLOB '*[^0-9]*'),")
    sql+='\n'+fragment
    for table,column,kind,oldkey in [('cu_cut','control_id','control','operation_id'),('cc_cut','cancel_id','cancel','cut_id'),('ce_fence','run_id','run','fence_id'),('go_close','close_id','close','close_id')]:
        # 原领域seal不能早于准备集合seal；生成器仅搬运固定关系，不从命名推导语义。
        if table in ('cu_cut','go_close'):
            source='ct_commit';where=f"o.{'change_id' if table=='cu_cut' else 'protection_change_id'}=NEW.change_id"
        else:source='cc_cut_commit' if table=='cc_cut' else 'ce_cut_commit';where=f'o.{oldkey}=NEW.{oldkey}'
        sql+=f"\nCREATE TRIGGER pd_seal_{table} BEFORE INSERT ON {source} BEGIN\n SELECT CASE WHEN EXISTS(SELECT 1 FROM {table} o WHERE {where} AND NOT EXISTS(SELECT 1 FROM pd_cut c JOIN pd_cut_commit k USING(cut_id) WHERE c.cut_id=o.prepare_cut_id AND c.{column}=o.{oldkey} AND c.kind='{kind}' AND c.prepare_head=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration))) THEN RAISE(ABORT,'prepare_cut_required') END;\nEND;\n"
    for table,cuttable,key in [('cu_effective','cu_cut','operation_id'),('cc_closure','cc_cut','cut_id'),('ce_application','ce_fence','fence_id')]:
        sql+=f"\nCREATE TRIGGER pd_apply_{table} BEFORE INSERT ON {table} BEGIN\n SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM {cuttable} c JOIN pd_valid_closure p ON p.cut_id=c.prepare_cut_id WHERE c.{key}=NEW.{key} AND p.closure_id=NEW.prepare_closure_id) THEN RAISE(ABORT,'prepare_closure_required') END;\nEND;\n"
    for view in ('cu_valid_effective','cc_valid_closure'):
        sql=L.replace(sql,f'CREATE VIEW {view} AS',f'CREATE VIEW pd_base_{view} AS',1)
        sql+=f"\nCREATE VIEW {view} AS SELECT b.* FROM pd_base_{view} b JOIN pd_valid_closure p ON p.closure_id=b.prepare_closure_id;\n"
    sql=L.replace(sql,'CREATE VIEW go_valid_recovery AS','CREATE VIEW pd_base_go_valid_recovery AS',1)
    sql+="""
CREATE VIEW go_valid_recovery AS SELECT r.* FROM pd_base_go_valid_recovery r
 WHERE NOT EXISTS(SELECT 1 FROM go_recovery_target t WHERE t.recovery_id=r.recovery_id
 AND NOT EXISTS(SELECT 1 FROM pd_close_completion c JOIN pd_valid_closure p USING(closure_id) WHERE c.close_id=t.close_id AND c.ack_id=t.ack_id));
CREATE VIEW pd_valid_application AS SELECT a.* FROM ce_application a JOIN pd_valid_closure p ON p.closure_id=a.prepare_closure_id;
"""
    sql=L.replace(sql,'CREATE VIEW go_ready_candidate AS','CREATE VIEW pd_base_go_ready_candidate AS',1)
    sql+="""
CREATE VIEW go_ready_candidate AS SELECT c.* FROM pd_base_go_ready_candidate c JOIN go_plan p USING(plan_id)
 WHERE p.gate_recovery_id IS NULL OR EXISTS(SELECT 1 FROM go_valid_recovery r WHERE r.recovery_id=p.gate_recovery_id);
"""
    sql+="""
CREATE TRIGGER pd_final_control BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_effective e JOIN ct_change h USING(change_id) WHERE e.change_id=NEW.change_id
 AND NOT EXISTS(SELECT 1 FROM pd_valid_closure p WHERE p.closure_id=e.prepare_closure_id AND p.committed_tick<=h.now_tick))
 THEN RAISE(ABORT,'prepare_control_final_seal') END;
END;
CREATE TRIGGER pd_recovery_guard BEFORE INSERT ON go_recovery_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_recovery_target t WHERE t.recovery_id=NEW.recovery_id
 AND NOT EXISTS(SELECT 1 FROM pd_close_completion c JOIN pd_valid_closure p USING(closure_id)
 WHERE c.close_id=t.close_id AND c.ack_id=t.ack_id)) THEN RAISE(ABORT,'prepare_close_not_complete') END;
END;
CREATE TRIGGER pd_send_guard BEFORE INSERT ON ij_write_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pd_deny_request r JOIN ce_retirement e USING(exit_id) WHERE r.journal_frame_id=NEW.frame_id)
 THEN RAISE(ABORT,'prepare_deny_retired') END;
END;
"""
    for table in TABLES:
        for op,suffix in [('UPDATE','u'),('DELETE','d')]:
            sql+=f"CREATE TRIGGER {table}_{suffix} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;\n"
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    raw=build();target=HERE/'controller-prepare-deny.sql'
    if a.check:assert target.read_bytes()==raw,'生成漂移'
    else:target.write_bytes(raw)
