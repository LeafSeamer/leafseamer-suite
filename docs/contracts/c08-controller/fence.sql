-- 在controller.sql之后加载。执行登记与运行保护附属候选，非产品迁移。
CREATE TABLE ce_command (
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ca_command_initial(command_id),
 device_id TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('manual','automation')),
 prep_key TEXT, receipt_id TEXT,
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 CHECK((origin='manual' AND prep_key IS NULL AND receipt_id IS NULL)
    OR (origin='automation' AND prep_key IS NOT NULL AND receipt_id IS NOT NULL)),
 FOREIGN KEY(prep_key,receipt_id) REFERENCES cp_receipt(prep_key,receipt_id),
 FOREIGN KEY(prep_key,device_id) REFERENCES cp_request_device(prep_key,device_id)
) STRICT;
CREATE TABLE ce_exit (
 exit_id TEXT PRIMARY KEY NOT NULL,
 device_id TEXT NOT NULL,
 controller_boot_id TEXT NOT NULL, worker_boot_id TEXT NOT NULL,
 ipc_session_id TEXT NOT NULL, device_session_id TEXT NOT NULL,
 clock_domain_id TEXT NOT NULL, descriptor_digest TEXT NOT NULL,
 runtime_binding_body BLOB NOT NULL CHECK(length(runtime_binding_body)>0),
 UNIQUE(controller_boot_id,worker_boot_id,ipc_session_id,device_session_id,device_id),
 CHECK(length(exit_id)>0 AND length(device_id)>0 AND length(controller_boot_id)>0
  AND length(worker_boot_id)>0 AND length(ipc_session_id)>0 AND length(device_session_id)>0
  AND length(clock_domain_id)>0 AND length(descriptor_digest)>0)
) STRICT;
CREATE TABLE ce_attempt (
 attempt_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL REFERENCES ce_command(command_id),
 authorization_body BLOB NOT NULL CHECK(length(authorization_body)>0),
 attempt_body BLOB NOT NULL CHECK(length(attempt_body)>0)
) STRICT;
CREATE TABLE ce_packet (
 packet_id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES ce_attempt(attempt_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 primitive_id TEXT NOT NULL CHECK(length(primitive_id)>0),
 packet_body BLOB NOT NULL CHECK(length(packet_body)>0),
 UNIQUE(attempt_id,primitive_id), UNIQUE(packet_id,attempt_id,exit_id)
) STRICT;
CREATE TABLE ce_permit (
 permit_id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES ce_attempt(attempt_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 issued_revision TEXT NOT NULL UNIQUE CHECK(length(issued_revision)=20
  AND issued_revision NOT GLOB '*[^0-9]*' AND issued_revision>'00000000000000000000'),
 packet_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 0 AND 2147483647),
 kind TEXT NOT NULL CHECK(kind IN ('initial','protocol_resend')),
 parent_permit_id TEXT,
 permit_body BLOB NOT NULL CHECK(length(permit_body)>0),
 CHECK((ordinal=0 AND kind='initial' AND parent_permit_id IS NULL)
    OR (ordinal>0 AND kind='protocol_resend' AND parent_permit_id IS NOT NULL)),
 UNIQUE(packet_id,ordinal), UNIQUE(permit_id,packet_id), UNIQUE(permit_id,exit_id),
 FOREIGN KEY(packet_id,attempt_id,exit_id) REFERENCES ce_packet(packet_id,attempt_id,exit_id),
 FOREIGN KEY(parent_permit_id,packet_id) REFERENCES ce_permit(permit_id,packet_id),
 FOREIGN KEY(permit_id) REFERENCES ce_transmission_commit(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ce_transmission_commit (
 permit_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_permit(permit_id),
 guard_body BLOB NOT NULL CHECK(length(guard_body)>0),
 budget_charge_body BLOB NOT NULL CHECK(length(budget_charge_body)>0),
 dispatch_intent_body BLOB NOT NULL CHECK(length(dispatch_intent_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ce_report (
 report_id TEXT PRIMARY KEY NOT NULL,
 permit_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK(
  (disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR
  (disposition='unknown' AND proof='send_uncertain')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 UNIQUE(report_id,permit_id),
 FOREIGN KEY(permit_id,exit_id) REFERENCES ce_permit(permit_id,exit_id)
) STRICT;
CREATE TABLE ce_settlement (
 settlement_id TEXT PRIMARY KEY NOT NULL,
 permit_id TEXT NOT NULL REFERENCES ce_permit(permit_id),
 kind TEXT NOT NULL CHECK(kind IN ('never_sent','effect_resolved')),
 report_id TEXT,
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 CHECK((kind='never_sent' AND report_id IS NOT NULL)
    OR (kind='effect_resolved' AND report_id IS NULL)),
 FOREIGN KEY(report_id,permit_id) REFERENCES ce_report(report_id,permit_id)
) STRICT;
CREATE TABLE ce_retirement (
 exit_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_exit(exit_id),
 supervisor_evidence_body BLOB NOT NULL CHECK(length(supervisor_evidence_body)>0)
) STRICT;

CREATE VIEW ce_run_command AS
 SELECT c.*,p.origin_authority,p.origin_database,p.run_id,p.generation
 FROM ce_command c JOIN cp_request p USING(prep_key);
-- 可靠未发核销被迟到的transport证据推翻时，重新列为未决；不覆写旧核销记录。
CREATE VIEW ce_open_permit AS
 SELECT p.*,a.command_id,c.device_id,c.origin_authority,c.origin_database,c.run_id,c.generation
 FROM ce_permit p JOIN ce_attempt a USING(attempt_id)
 JOIN ce_run_command c USING(command_id)
 WHERE NOT EXISTS(SELECT 1 FROM ce_settlement s WHERE s.permit_id=p.permit_id
  AND (s.kind='effect_resolved' OR NOT EXISTS(
    SELECT 1 FROM ce_current_disposition r WHERE r.permit_id=p.permit_id AND r.disposition='in_flight')));

CREATE TABLE ce_fence (
 fence_id TEXT PRIMARY KEY NOT NULL,
 protection_id TEXT UNIQUE REFERENCES run_protection_request(protection_id),
 close_id TEXT UNIQUE REFERENCES cp_close(close_id),
 issued_cut_revision TEXT NOT NULL CHECK(length(issued_cut_revision)=20
  AND issued_cut_revision NOT GLOB '*[^0-9]*'),
 cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 CHECK((protection_id IS NOT NULL AND close_id IS NULL)
    OR (protection_id IS NULL AND close_id IS NOT NULL)),
 FOREIGN KEY(fence_id) REFERENCES ce_cut_commit(fence_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ce_target (
 fence_id TEXT NOT NULL REFERENCES ce_fence(fence_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 ledger_digest TEXT NOT NULL, target_body BLOB NOT NULL CHECK(length(target_body)>0),
 PRIMARY KEY(fence_id,exit_id)
) STRICT;
CREATE TABLE ce_item (
 fence_id TEXT NOT NULL, permit_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 entered_known INTEGER NOT NULL CHECK(entered_known IN (0,1)),
 PRIMARY KEY(fence_id,permit_id),
 UNIQUE(fence_id,permit_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target(fence_id,exit_id),
 FOREIGN KEY(permit_id,exit_id) REFERENCES ce_permit(permit_id,exit_id)
) STRICT;
CREATE TABLE ce_queued (
 fence_id TEXT NOT NULL REFERENCES ce_fence(fence_id),
 command_id TEXT NOT NULL UNIQUE REFERENCES ce_command(command_id),
 reason TEXT NOT NULL CHECK(reason='run_generation_denied'),
 PRIMARY KEY(fence_id,command_id)
) STRICT;
CREATE TABLE ce_cut_commit (
 fence_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_fence(fence_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_event_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE ce_target_result (
 fence_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('worker_ack','supervisor_retired')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(fence_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target(fence_id,exit_id)
) STRICT;
CREATE TABLE ce_coverage (
 fence_id TEXT NOT NULL, permit_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK(
  (disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR
  (disposition='unknown' AND proof='send_uncertain')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 PRIMARY KEY(fence_id,permit_id),
 FOREIGN KEY(fence_id,permit_id,exit_id) REFERENCES ce_item(fence_id,permit_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target_result(fence_id,exit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ce_application (
 fence_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_cut_commit(fence_id),
 receipt_id TEXT NOT NULL UNIQUE,
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_event_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;

CREATE VIEW ce_selector AS
 SELECT f.fence_id,r.origin_authority,r.origin_database,r.run_id,r.generation
 FROM ce_fence f JOIN run_protection_request r USING(protection_id)
 UNION ALL
 SELECT f.fence_id,r.origin_authority,r.origin_database,r.run_id,r.generation
 FROM ce_fence f JOIN cp_close c USING(close_id) JOIN cp_request r USING(prep_key);
CREATE VIEW ce_expected_item AS
 SELECT s.fence_id,p.permit_id,p.exit_id FROM ce_selector s JOIN ce_open_permit p
 ON (p.origin_authority,p.origin_database,p.run_id)=(s.origin_authority,s.origin_database,s.run_id)
 AND p.generation<=s.generation;
CREATE VIEW ce_expected_target AS
 SELECT DISTINCT s.fence_id,e.exit_id FROM ce_selector s
 JOIN cp_request p ON (p.origin_authority,p.origin_database,p.run_id)=
  (s.origin_authority,s.origin_database,s.run_id) AND p.generation<=s.generation
 JOIN cp_request_device d USING(prep_key) JOIN ce_exit e ON e.device_id=d.device_id
 WHERE NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id)
 UNION
 SELECT fence_id,exit_id FROM ce_expected_item;
CREATE VIEW ce_expected_queued AS
 SELECT s.fence_id,c.command_id FROM ce_selector s JOIN ce_run_command c
 ON (c.origin_authority,c.origin_database,c.run_id)=(s.origin_authority,s.origin_database,s.run_id)
 AND c.generation<=s.generation
 WHERE NOT EXISTS(SELECT 1 FROM ce_attempt a WHERE a.command_id=c.command_id)
 AND NOT EXISTS(SELECT 1 FROM ce_queued q JOIN ce_cut_commit k USING(fence_id)
                WHERE q.command_id=c.command_id);
CREATE VIEW ce_source_target AS
 SELECT f.fence_id,t.target_id FROM ce_fence f JOIN run_protection_target t USING(protection_id)
 UNION ALL
 SELECT f.fence_id,t.target_id FROM ce_fence f JOIN cp_protection_target t USING(close_id);
CREATE VIEW ce_pending_cut AS
 SELECT f.fence_id FROM ce_fence f JOIN ce_cut_commit k USING(fence_id)
 WHERE NOT EXISTS(SELECT 1 FROM run_protection_commit c WHERE c.protection_id=f.protection_id)
 AND NOT EXISTS(SELECT 1 FROM cp_close c JOIN cp_commit k ON k.commit_id=c.commit_id WHERE c.close_id=f.close_id);
CREATE VIEW ce_current_disposition AS
 SELECT p.permit_id,
 CASE WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='in_flight')
   OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
             WHERE c.permit_id=p.permit_id AND c.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
   OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
             WHERE c.permit_id=p.permit_id AND c.disposition='not_sent') THEN 'not_sent'
 ELSE 'unknown' END AS disposition
 FROM ce_permit p;

CREATE TRIGGER ce_command_guard BEFORE INSERT ON ce_command BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial c JOIN ca_request_key k USING(key_id)
  WHERE c.command_id=NEW.command_id AND k.device_id=NEW.device_id)
  THEN RAISE(ABORT,'command_device_binding') END;
 SELECT CASE WHEN NEW.origin='automation' AND NOT EXISTS(
  SELECT 1 FROM cp_current p WHERE p.prep_key=NEW.prep_key AND p.state='applied'
   AND p.receipt_id=NEW.receipt_id) THEN RAISE(ABORT,'preparation_not_applied') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cp_request p JOIN run_deny_event d
  ON (d.origin_authority,d.origin_database,d.run_id)=(p.origin_authority,p.origin_database,p.run_id)
  AND d.generation>=p.generation WHERE p.prep_key=NEW.prep_key) THEN RAISE(ABORT,'run_denied') END;
END;
CREATE TRIGGER ce_accept_projection BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial c JOIN ce_command e USING(command_id)
  WHERE c.key_id=NEW.key_id) THEN RAISE(ABORT,'execution_projection_required') END;
END;
CREATE TRIGGER ce_attempt_guard BEFORE INSERT ON ce_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_queued WHERE command_id=NEW.command_id)
  OR EXISTS(SELECT 1 FROM ce_run_command c JOIN run_deny_event d
   ON (d.origin_authority,d.origin_database,d.run_id)=(c.origin_authority,c.origin_database,c.run_id)
   AND d.generation>=c.generation WHERE c.command_id=NEW.command_id)
  THEN RAISE(ABORT,'run_denied') END;
END;
CREATE TRIGGER ce_permit_guard BEFORE INSERT ON ce_permit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_command c USING(command_id)
  JOIN ce_exit e ON e.device_id=c.device_id WHERE a.attempt_id=NEW.attempt_id AND e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'permit_exit_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'exit_retired') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_run_command c USING(command_id)
  JOIN run_deny_event d ON (d.origin_authority,d.origin_database,d.run_id)=
  (c.origin_authority,c.origin_database,c.run_id) AND d.generation>=c.generation
  WHERE a.attempt_id=NEW.attempt_id) THEN RAISE(ABORT,'run_denied') END;
 SELECT CASE WHEN NEW.ordinal!=(SELECT coalesce(max(ordinal),-1)+1 FROM ce_permit WHERE packet_id=NEW.packet_id)
  THEN RAISE(ABORT,'ordinal_successor') END;
 SELECT CASE WHEN NEW.ordinal>0 AND NOT EXISTS(SELECT 1 FROM ce_permit
  WHERE permit_id=NEW.parent_permit_id AND ordinal=0 AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'resend_parent') END;
 SELECT CASE WHEN NEW.issued_revision!=(SELECT printf('%010d%010d',
  CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
  (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
  FROM (SELECT coalesce(max(issued_revision),'00000000000000000000') v FROM ce_permit))
  THEN RAISE(ABORT,'issued_successor') END;
END;
CREATE TRIGGER ce_settlement_guard BEFORE INSERT ON ce_settlement WHEN NEW.kind='never_sent' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_report WHERE report_id=NEW.report_id
  AND permit_id=NEW.permit_id AND disposition='not_sent')
  OR EXISTS(SELECT 1 FROM ce_current_disposition WHERE permit_id=NEW.permit_id AND disposition='in_flight')
  THEN RAISE(ABORT,'not_sent_unproven') END;
END;
CREATE TRIGGER ce_cut_guard BEFORE INSERT ON ce_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_fence f WHERE f.fence_id=NEW.fence_id AND
  (EXISTS(SELECT 1 FROM run_protection_commit WHERE protection_id=f.protection_id)
   OR EXISTS(SELECT 1 FROM cp_close c JOIN cp_commit k ON k.commit_id=c.commit_id WHERE c.close_id=f.close_id)))
  THEN RAISE(ABORT,'cut_must_share_source_transaction') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_fence WHERE fence_id=NEW.fence_id
  AND issued_cut_revision=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ce_permit))
  THEN RAISE(ABORT,'cut_revision') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM ce_expected_target WHERE fence_id=NEW.fence_id
  EXCEPT SELECT exit_id FROM ce_target WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT exit_id FROM ce_target WHERE fence_id=NEW.fence_id
  EXCEPT SELECT exit_id FROM ce_expected_target WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'target_set_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT permit_id,exit_id FROM ce_expected_item WHERE fence_id=NEW.fence_id
  EXCEPT SELECT permit_id,exit_id FROM ce_item WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT permit_id,exit_id FROM ce_item WHERE fence_id=NEW.fence_id
  EXCEPT SELECT permit_id,exit_id FROM ce_expected_item WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'intent_set_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT command_id FROM ce_expected_queued WHERE fence_id=NEW.fence_id
  EXCEPT SELECT command_id FROM ce_queued WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT command_id FROM ce_queued WHERE fence_id=NEW.fence_id
  EXCEPT SELECT command_id FROM ce_expected_queued WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'queued_set_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_item i WHERE i.fence_id=NEW.fence_id AND
  i.entered_known!=EXISTS(SELECT 1 FROM ce_current_disposition d WHERE d.permit_id=i.permit_id
                        AND d.disposition='in_flight'))
  THEN RAISE(ABORT,'entered_snapshot') END;
 SELECT CASE WHEN (SELECT count(*) FROM ce_target WHERE fence_id=NEW.fence_id)>256
  OR EXISTS(SELECT exit_id FROM ce_item WHERE fence_id=NEW.fence_id GROUP BY exit_id HAVING count(*)>256)
  THEN RAISE(ABORT,'fence_capacity') END;
 -- 旧P2容器必须逐出口一致；HTTP ControllerTarget摘要不是此出口集合。
 SELECT CASE WHEN EXISTS(
  SELECT t.exit_id FROM ce_target t WHERE t.fence_id=NEW.fence_id
  EXCEPT SELECT target_id FROM ce_source_target WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT target_id FROM ce_source_target WHERE fence_id=NEW.fence_id
  EXCEPT SELECT exit_id FROM ce_target WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'source_targets') END;
END;
CREATE TRIGGER ce_protection_cut BEFORE INSERT ON run_protection_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_fence f JOIN ce_cut_commit c USING(fence_id)
  WHERE f.protection_id=NEW.protection_id) THEN RAISE(ABORT,'cut_required') END;
END;
CREATE TRIGGER ce_close_cut BEFORE INSERT ON cp_commit WHEN NEW.close_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_fence f JOIN ce_cut_commit c USING(fence_id)
  WHERE f.close_id=NEW.close_id) THEN RAISE(ABORT,'cut_required') END;
END;
CREATE TRIGGER ce_application_guard BEFORE INSERT ON ce_application BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_pending_cut WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'cut_uncommitted') END;
 SELECT CASE WHEN (SELECT count(*) FROM ce_target_result WHERE fence_id=NEW.fence_id)!=
                  (SELECT count(*) FROM ce_target WHERE fence_id=NEW.fence_id)
  OR (SELECT count(*) FROM ce_coverage WHERE fence_id=NEW.fence_id)!=
     (SELECT count(*) FROM ce_item WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'coverage_incomplete') END;
END;
CREATE TRIGGER ce_result_guard BEFORE INSERT ON ce_target_result BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id)
  OR EXISTS(SELECT 1 FROM ce_pending_cut WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'cut_uncommitted') END;
 SELECT CASE WHEN (SELECT count(*) FROM ce_coverage WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)!=
                  (SELECT count(*) FROM ce_item WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'coverage_incomplete') END;
 SELECT CASE WHEN NEW.evidence_kind='supervisor_retired'
  AND NOT EXISTS(SELECT 1 FROM ce_retirement e WHERE e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'retirement_unproven') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_item i USING(fence_id,permit_id,exit_id)
  WHERE c.fence_id=NEW.fence_id AND c.exit_id=NEW.exit_id AND
  ((i.entered_known=1 AND c.disposition!='in_flight')
   OR (NEW.evidence_kind='supervisor_retired' AND c.disposition='not_sent')))
  THEN RAISE(ABORT,'coverage_downgrade') END;
END;
CREATE TRIGGER ce_target_frozen BEFORE INSERT ON ce_target WHEN EXISTS(
 SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id) BEGIN SELECT RAISE(ABORT,'cut_frozen'); END;
CREATE TRIGGER ce_item_frozen BEFORE INSERT ON ce_item WHEN EXISTS(
 SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id) BEGIN SELECT RAISE(ABORT,'cut_frozen'); END;
CREATE TRIGGER ce_queued_frozen BEFORE INSERT ON ce_queued WHEN EXISTS(
 SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id) BEGIN SELECT RAISE(ABORT,'cut_frozen'); END;
CREATE TRIGGER ce_result_frozen BEFORE INSERT ON ce_target_result WHEN EXISTS(
 SELECT 1 FROM ce_application WHERE fence_id=NEW.fence_id) BEGIN SELECT RAISE(ABORT,'application_frozen'); END;
CREATE TRIGGER ce_coverage_frozen BEFORE INSERT ON ce_coverage WHEN EXISTS(
 SELECT 1 FROM ce_target_result WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
 BEGIN SELECT RAISE(ABORT,'coverage_frozen'); END;

-- seal后至来源commit之间禁止改动登记事实；保护与切点仍必须同一事务提交。
CREATE TRIGGER ce_command_cut BEFORE INSERT ON ce_command WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_exit_cut BEFORE INSERT ON ce_exit WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_attempt_cut BEFORE INSERT ON ce_attempt WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_permit_cut BEFORE INSERT ON ce_permit WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_packet_cut BEFORE INSERT ON ce_packet WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_report_cut BEFORE INSERT ON ce_report WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_settlement_cut BEFORE INSERT ON ce_settlement WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_retirement_cut BEFORE INSERT ON ce_retirement WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_preparation_cut BEFORE INSERT ON cp_request WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_preparation_device_cut BEFORE INSERT ON cp_request_device WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;

CREATE TRIGGER ce_command_u BEFORE UPDATE ON ce_command BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_command_d BEFORE DELETE ON ce_command BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_exit_u BEFORE UPDATE ON ce_exit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_exit_d BEFORE DELETE ON ce_exit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_attempt_u BEFORE UPDATE ON ce_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_attempt_d BEFORE DELETE ON ce_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_packet_u BEFORE UPDATE ON ce_packet BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_packet_d BEFORE DELETE ON ce_packet BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_transmission_u BEFORE UPDATE ON ce_transmission_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_transmission_d BEFORE DELETE ON ce_transmission_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_permit_u BEFORE UPDATE ON ce_permit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_permit_d BEFORE DELETE ON ce_permit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_report_u BEFORE UPDATE ON ce_report BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_report_d BEFORE DELETE ON ce_report BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_settlement_u BEFORE UPDATE ON ce_settlement BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_settlement_d BEFORE DELETE ON ce_settlement BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_retirement_u BEFORE UPDATE ON ce_retirement BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_retirement_d BEFORE DELETE ON ce_retirement BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_fence_u BEFORE UPDATE ON ce_fence BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_fence_d BEFORE DELETE ON ce_fence BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_target_u BEFORE UPDATE ON ce_target BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_target_d BEFORE DELETE ON ce_target BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_item_u BEFORE UPDATE ON ce_item BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_item_d BEFORE DELETE ON ce_item BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_queued_u BEFORE UPDATE ON ce_queued BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_queued_d BEFORE DELETE ON ce_queued BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_cut_u BEFORE UPDATE ON ce_cut_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_cut_d BEFORE DELETE ON ce_cut_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_result_u BEFORE UPDATE ON ce_target_result BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_result_d BEFORE DELETE ON ce_target_result BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_coverage_u BEFORE UPDATE ON ce_coverage BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_coverage_d BEFORE DELETE ON ce_coverage BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_application_u BEFORE UPDATE ON ce_application BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_application_d BEFORE DELETE ON ce_application BEGIN SELECT RAISE(ABORT,'immutable'); END;
