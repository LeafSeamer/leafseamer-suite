-- 控制屏障161表候选；生效与开放分开，不能作为生产迁移。
CREATE TABLE cu_cut(
 operation_id TEXT PRIMARY KEY REFERENCES ct_operation(operation_id),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_change(change_id), device_id TEXT NOT NULL,
 issued_revision TEXT NOT NULL CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*'),
 cut_digest TEXT NOT NULL, cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cu_target(
 operation_id TEXT NOT NULL REFERENCES cu_cut(operation_id), exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 PRIMARY KEY(operation_id,exit_id)
) STRICT;
CREATE TABLE cu_member(
 operation_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL REFERENCES ci_issue(permit_id),
 entered_known INTEGER NOT NULL CHECK(entered_known IN (0,1)),
 PRIMARY KEY(operation_id,permit_id), UNIQUE(operation_id,exit_id,permit_id),
 FOREIGN KEY(operation_id,exit_id) REFERENCES cu_target(operation_id,exit_id)
) STRICT;
CREATE TABLE cu_queued(
 operation_id TEXT NOT NULL REFERENCES cu_cut(operation_id), command_id TEXT NOT NULL UNIQUE,
 before_revision TEXT NOT NULL, blocked_revision TEXT NOT NULL,
 PRIMARY KEY(operation_id,command_id),
 FOREIGN KEY(command_id,before_revision) REFERENCES cm_revision(command_id,revision),
 FOREIGN KEY(command_id,blocked_revision) REFERENCES cm_revision(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_delivery(
 barrier_id TEXT PRIMARY KEY CHECK(length(barrier_id)>0), attempt_id TEXT NOT NULL REFERENCES ct_attempt(attempt_id),
 operation_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 target_gate_revision TEXT NOT NULL CHECK(length(target_gate_revision)=20 AND target_gate_revision NOT GLOB '*[^0-9]*'),
 request_digest TEXT NOT NULL, request_body BLOB NOT NULL CHECK(length(request_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 UNIQUE(attempt_id,exit_id), UNIQUE(barrier_id,operation_id,exit_id),
 FOREIGN KEY(attempt_id,operation_id) REFERENCES ct_attempt(attempt_id,operation_id),
 FOREIGN KEY(operation_id,exit_id) REFERENCES cu_target(operation_id,exit_id)
) STRICT;
CREATE TABLE cu_coverage(
 barrier_id TEXT NOT NULL, operation_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK((disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
   (disposition='in_flight' AND proof='transport_entered') OR (disposition='unknown' AND proof='send_uncertain')),
 PRIMARY KEY(barrier_id,permit_id),
 FOREIGN KEY(barrier_id,operation_id,exit_id) REFERENCES cu_delivery(barrier_id,operation_id,exit_id),
 FOREIGN KEY(operation_id,exit_id,permit_id) REFERENCES cu_member(operation_id,exit_id,permit_id),
 FOREIGN KEY(barrier_id) REFERENCES cu_ack(barrier_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_ack(
 barrier_id TEXT PRIMARY KEY REFERENCES cu_delivery(barrier_id),
 control_epoch TEXT NOT NULL, installed_version TEXT NOT NULL, gate_revision TEXT NOT NULL,
 issued_revision TEXT NOT NULL, cut_digest TEXT NOT NULL,
 effective_tick TEXT NOT NULL CHECK(length(effective_tick)=20 AND effective_tick NOT GLOB '*[^0-9]*'),
 ack_digest TEXT NOT NULL, ack_body BLOB NOT NULL CHECK(length(ack_body)>0),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cu_authorization(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id), operation_id TEXT NOT NULL REFERENCES ct_operation(operation_id),
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, principal_id TEXT NOT NULL,
 clock_domain TEXT NOT NULL, descriptor TEXT NOT NULL,
 issued_tick TEXT NOT NULL CHECK(length(issued_tick)=20 AND issued_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), snapshot_digest TEXT NOT NULL,
 snapshot_body BLOB NOT NULL CHECK(length(snapshot_body)>0), CHECK(issued_tick<expires_tick),
 FOREIGN KEY(change_id) REFERENCES cu_effective(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_selection(
 change_id TEXT NOT NULL REFERENCES ct_change(change_id), operation_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 barrier_id TEXT REFERENCES cu_ack(barrier_id), retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 PRIMARY KEY(change_id,exit_id),
 CHECK((barrier_id IS NOT NULL AND retirement_exit_id IS NULL) OR (barrier_id IS NULL AND retirement_exit_id IS exit_id)),
 FOREIGN KEY(operation_id,exit_id) REFERENCES cu_target(operation_id,exit_id),
 FOREIGN KEY(change_id) REFERENCES cu_effective(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_effective(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id), operation_id TEXT NOT NULL UNIQUE REFERENCES cu_cut(operation_id),
 attempt_id TEXT NOT NULL REFERENCES ct_attempt(attempt_id),
 control_state_id TEXT NOT NULL REFERENCES ct_state(change_id),
 selection_digest TEXT NOT NULL, selection_body BLOB NOT NULL CHECK(length(selection_body)>0),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 FOREIGN KEY(change_id) REFERENCES cu_authorization(change_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(control_state_id IS change_id)
) STRICT;
CREATE TABLE cu_effective_member(
 change_id TEXT NOT NULL REFERENCES ct_change(change_id), permit_id TEXT NOT NULL REFERENCES ci_issue(permit_id),
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 PRIMARY KEY(change_id,permit_id),
 FOREIGN KEY(change_id) REFERENCES cu_effective(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_revocation(
 kind TEXT NOT NULL CHECK(kind IN ('ack','retirement')), object_id TEXT NOT NULL,
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(kind,object_id)
) STRICT;
CREATE TABLE cu_protection(
 kind TEXT NOT NULL, object_id TEXT NOT NULL, device_id TEXT NOT NULL, exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 PRIMARY KEY(kind,object_id,exit_id), FOREIGN KEY(kind,object_id) REFERENCES cu_revocation(kind,object_id)
) STRICT;
-- 只有当前仍可靠且已封存的资源核销可以省略历史许可，撤回或迟到强事实使其重新纳入。
CREATE VIEW cu_issue AS
 SELECT i.*,e.device_id,p.exit_id,a.command_id FROM ci_issue i JOIN ce_permit p USING(permit_id)
 JOIN ce_attempt a USING(attempt_id) JOIN ce_exit e USING(exit_id)
 UNION ALL SELECT i.*,e.device_id,p.exit_id,c.command_id FROM ci_issue i JOIN ci_cancel_transmission p USING(permit_id)
 JOIN cv_cancel c USING(cancellation_id) JOIN ce_exit e USING(exit_id);
CREATE VIEW cu_open_issue AS SELECT p.* FROM cu_issue p WHERE NOT EXISTS(
 SELECT 1 FROM (SELECT release_id,permit_id FROM cr_release_member UNION SELECT release_id,permit_id FROM cx_release_member) m
 JOIN cr_release_commit k USING(release_id) WHERE m.permit_id=p.permit_id
 AND NOT EXISTS(SELECT 1 FROM cr_invalid_release x WHERE x.release_id=m.release_id)
 AND NOT EXISTS(SELECT 1 FROM cr_release_invalidation x WHERE x.release_id=m.release_id));
CREATE VIEW cu_expected_member AS SELECT c.operation_id,p.exit_id,p.permit_id FROM cu_cut c JOIN cu_open_issue p USING(device_id);
CREATE VIEW cu_expected_target AS
 SELECT c.operation_id,e.exit_id FROM cu_cut c JOIN ce_exit e USING(device_id);
CREATE VIEW cu_current_disposition AS
 SELECT permit_id,disposition FROM ce_current_disposition UNION ALL SELECT permit_id,disposition FROM cf_disposition;
CREATE VIEW cu_valid_effective AS SELECT e.* FROM cu_effective e JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM cu_selection s JOIN cu_revocation r
 ON (r.kind='ack' AND r.object_id=s.barrier_id) OR (r.kind='retirement' AND r.object_id=s.retirement_exit_id)
 WHERE s.change_id=e.change_id);
CREATE TRIGGER cu_cut_binding BEFORE INSERT ON cu_cut BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_operation o JOIN ct_change c USING(change_id)
  WHERE o.operation_id=NEW.operation_id AND c.change_id=NEW.change_id AND c.device_id=NEW.device_id
  AND c.kind IN ('accept','acquire','release') AND NOT EXISTS(SELECT 1 FROM ct_commit WHERE change_id=c.change_id))
  OR NEW.issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  THEN RAISE(ABORT,'control_cut_binding') END;
END;
CREATE TRIGGER cu_control_seal BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND
  (SELECT count(*) FROM cu_cut WHERE change_id=c.change_id)!=(c.kind IN ('accept','acquire','release')))
  THEN RAISE(ABORT,'control_cut_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_cut WHERE change_id=NEW.change_id
  AND issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue))
  THEN RAISE(ABORT,'control_cut_watermark') END;
 SELECT CASE WHEN EXISTS(SELECT operation_id,exit_id FROM cu_expected_target WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id)
  EXCEPT SELECT operation_id,exit_id FROM cu_target WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id))
 OR EXISTS(SELECT operation_id,exit_id FROM cu_target WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id)
  EXCEPT SELECT operation_id,exit_id FROM cu_expected_target WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id))
  THEN RAISE(ABORT,'control_target_set') END;
 SELECT CASE WHEN EXISTS(SELECT operation_id,exit_id,permit_id FROM cu_expected_member WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id)
  EXCEPT SELECT operation_id,exit_id,permit_id FROM cu_member WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id))
 OR EXISTS(SELECT operation_id,exit_id,permit_id FROM cu_member WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id)
  EXCEPT SELECT operation_id,exit_id,permit_id FROM cu_expected_member WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id))
  THEN RAISE(ABORT,'control_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_member m JOIN cu_cut c USING(operation_id) JOIN cu_current_disposition d USING(permit_id)
  WHERE c.change_id=NEW.change_id AND m.entered_known!=(d.disposition='in_flight')) THEN RAISE(ABORT,'control_entered_snapshot') END;
 SELECT CASE WHEN EXISTS(SELECT m.exit_id,i.kind FROM cu_member m JOIN cu_cut c USING(operation_id) JOIN ci_issue i USING(permit_id)
  WHERE c.change_id=NEW.change_id GROUP BY m.operation_id,m.exit_id,i.kind HAVING count(*)>256) THEN RAISE(ABORT,'control_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ce_command x USING(device_id) JOIN cm_latest r USING(command_id)
  WHERE c.change_id=NEW.change_id AND r.phase='queued' AND NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_permit p USING(attempt_id) WHERE a.command_id=x.command_id))
  THEN RAISE(ABORT,'control_queued_not_blocked') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_queued q JOIN cu_cut c USING(operation_id) JOIN cm_revision old ON old.command_id=q.command_id AND old.revision=q.before_revision
  WHERE c.change_id=NEW.change_id AND (old.phase!='queued' OR EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_permit p USING(attempt_id) WHERE a.command_id=q.command_id)
   OR NOT EXISTS(SELECT 1 FROM ce_command x JOIN cm_latest n USING(command_id) WHERE x.command_id=q.command_id AND x.device_id=c.device_id
    AND n.revision=q.blocked_revision AND n.previous_revision=q.before_revision AND n.kind='block' AND n.phase='finished' AND n.outcome='blocked' AND n.effect_status='not_sent' AND n.paused_latched=1)))
  THEN RAISE(ABORT,'control_queued_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_attempt a JOIN cu_target t USING(operation_id) WHERE a.change_id=NEW.change_id
  AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=t.exit_id)
  AND NOT EXISTS(SELECT 1 FROM cu_delivery d WHERE d.attempt_id=a.attempt_id AND d.exit_id=t.exit_id)) THEN RAISE(ABORT,'control_delivery_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND
  (SELECT count(*) FROM cu_effective WHERE change_id=c.change_id)!=(c.kind='effective')) THEN RAISE(ABORT,'control_effective_required') END;
END;
CREATE TRIGGER cu_queued_capture BEFORE INSERT ON cu_queued BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_latest r JOIN ce_command c USING(command_id) JOIN cu_cut t ON t.device_id=c.device_id
  WHERE r.command_id=NEW.command_id AND r.revision=NEW.before_revision AND r.phase='queued' AND t.operation_id=NEW.operation_id)
  THEN RAISE(ABORT,'control_queued_capture') END;
END;
-- 直接从受理writer的同一数据库前态冻结queued集合，不能由调用方省略成员。
CREATE TRIGGER cu_capture_queue AFTER INSERT ON cu_cut BEGIN
 INSERT INTO cu_queued SELECT NEW.operation_id,r.command_id,r.revision,
  printf('%010d%010d',CAST(substr(r.revision,1,10) AS INTEGER)+(substr(r.revision,11,10)='9999999999'),(CAST(substr(r.revision,11,10) AS INTEGER)+1)%10000000000)
 FROM cm_latest r JOIN ce_command c USING(command_id) WHERE c.device_id=NEW.device_id AND r.phase='queued'
 AND NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_permit p USING(attempt_id) WHERE a.command_id=r.command_id);
END;
CREATE TRIGGER cu_delivery_guard BEFORE INSERT ON cu_delivery BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_attempt a JOIN ct_commit k USING(change_id) WHERE a.attempt_id=NEW.attempt_id)
  OR EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id) THEN RAISE(ABORT,'control_delivery_frozen') END;
END;
CREATE TRIGGER cu_coverage_frozen BEFORE INSERT ON cu_coverage WHEN EXISTS(SELECT 1 FROM cu_ack WHERE barrier_id=NEW.barrier_id)
 BEGIN SELECT RAISE(ABORT,'control_ack_frozen'); END;
CREATE TRIGGER cu_ack_guard BEFORE INSERT ON cu_ack BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_pending_cut) THEN RAISE(ABORT,'pending_cut') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cu_delivery d JOIN ct_attempt a USING(attempt_id) JOIN ct_commit k ON k.change_id=a.change_id
  JOIN ct_operation o ON o.operation_id=d.operation_id JOIN ct_state s ON s.change_id=o.expected_state_id JOIN cu_cut c ON c.operation_id=o.operation_id
  WHERE d.barrier_id=NEW.barrier_id AND s.control_epoch=NEW.control_epoch AND o.target_version=NEW.installed_version
   AND d.target_gate_revision=NEW.gate_revision AND c.issued_revision=NEW.issued_revision AND c.cut_digest=NEW.cut_digest)
  THEN RAISE(ABORT,'control_ack_binding') END;
 SELECT CASE WHEN (SELECT count(*) FROM cu_coverage WHERE barrier_id=NEW.barrier_id)!=(SELECT count(*) FROM cu_member m JOIN cu_delivery d USING(operation_id,exit_id) WHERE d.barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'control_ack_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_coverage x JOIN cu_member m USING(operation_id,exit_id,permit_id)
  WHERE x.barrier_id=NEW.barrier_id AND m.entered_known=1 AND x.disposition!='in_flight') THEN RAISE(ABORT,'control_ack_downgrade') END;
END;
CREATE TRIGGER cu_ack_invalidation AFTER INSERT ON cu_ack BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT r.release_id,'control_ack',NEW.barrier_id,NULL FROM cr_invalid_release r
 JOIN (SELECT release_id,permit_id FROM cr_release_member UNION SELECT release_id,permit_id FROM cx_release_member) m USING(release_id)
 JOIN cu_coverage c USING(permit_id) WHERE c.barrier_id=NEW.barrier_id AND c.disposition='in_flight';
END;
CREATE TRIGGER cu_effective_guard BEFORE INSERT ON cu_effective BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ce_exit e USING(device_id)
  WHERE c.operation_id=NEW.operation_id AND NOT EXISTS(SELECT 1 FROM cu_target t WHERE t.operation_id=c.operation_id AND t.exit_id=e.exit_id)
   AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id AND NOT EXISTS(SELECT 1 FROM cu_revocation x WHERE x.kind='retirement' AND x.object_id=r.exit_id)))
  THEN RAISE(ABORT,'control_unfenced_new_exit') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_change c JOIN ct_operation o USING(operation_id)
  JOIN ct_current_operation p USING(operation_id) JOIN ct_current_state old ON old.device_id=c.device_id
  JOIN ct_state s ON s.change_id=c.change_id JOIN ct_state expected ON expected.change_id=o.expected_state_id
  JOIN ct_operation_event n ON n.change_id=c.change_id
  WHERE c.change_id=NEW.change_id AND c.kind='effective' AND c.operation_id=NEW.operation_id AND p.attempt_id=NEW.attempt_id
   AND old.pending_operation_id=o.operation_id AND p.state IN ('pending','indeterminate') AND n.state='effective'
   AND old.control_epoch=expected.control_epoch AND old.effective_version=expected.effective_version
   AND old.holder_issuer IS expected.holder_issuer AND old.holder_epoch IS expected.holder_epoch AND old.holder_id IS expected.holder_id
   AND s.effective_version=o.target_version AND s.mode=CASE o.kind WHEN 'release' THEN 'automatic' ELSE 'manual' END
   AND s.holder_issuer IS o.target_issuer AND s.holder_epoch IS o.target_epoch AND s.holder_id IS o.target_id)
  THEN RAISE(ABORT,'control_effective_binding') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cu_authorization a JOIN ct_change c USING(change_id) JOIN ct_operation o ON o.operation_id=a.operation_id
  WHERE a.change_id=NEW.change_id AND a.operation_id=NEW.operation_id AND a.clock_domain=c.clock_domain AND a.descriptor=c.descriptor AND a.issued_tick<=c.now_tick AND c.now_tick<a.expires_tick
   AND a.issuer_id=CASE o.kind WHEN 'release' THEN o.requester_issuer ELSE o.target_issuer END
   AND a.issuer_epoch=CASE o.kind WHEN 'release' THEN o.requester_epoch ELSE o.target_epoch END
   AND a.principal_id=CASE o.kind WHEN 'release' THEN o.requester_id ELSE o.target_id END)
  THEN RAISE(ABORT,'control_effective_authorization') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM cu_target WHERE operation_id=NEW.operation_id EXCEPT SELECT exit_id FROM cu_selection WHERE change_id=NEW.change_id AND operation_id=NEW.operation_id)
  OR EXISTS(SELECT exit_id FROM cu_selection WHERE change_id=NEW.change_id EXCEPT SELECT exit_id FROM cu_target WHERE operation_id=NEW.operation_id)
  THEN RAISE(ABORT,'control_selection_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_selection s WHERE s.change_id=NEW.change_id AND
  (s.operation_id!=NEW.operation_id OR
   (s.barrier_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cu_delivery d JOIN cu_ack k USING(barrier_id)
    WHERE d.barrier_id=s.barrier_id AND d.attempt_id=NEW.attempt_id AND d.operation_id=NEW.operation_id AND d.exit_id=s.exit_id
     AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=s.exit_id))) OR
   EXISTS(SELECT 1 FROM cu_revocation r WHERE (r.kind='ack' AND r.object_id=s.barrier_id) OR (r.kind='retirement' AND r.object_id=s.retirement_exit_id))))
  THEN RAISE(ABORT,'control_selection_invalid') END;
 SELECT CASE WHEN EXISTS(SELECT permit_id FROM cu_member WHERE operation_id=NEW.operation_id EXCEPT SELECT permit_id FROM cu_effective_member WHERE change_id=NEW.change_id)
  OR EXISTS(SELECT permit_id FROM cu_effective_member WHERE change_id=NEW.change_id EXCEPT SELECT permit_id FROM cu_member WHERE operation_id=NEW.operation_id)
  THEN RAISE(ABORT,'control_effective_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_effective_member x JOIN cu_member m USING(permit_id)
  JOIN cu_selection s ON s.change_id=x.change_id AND s.exit_id=m.exit_id
  JOIN cu_current_disposition d ON d.permit_id=m.permit_id LEFT JOIN cu_coverage v ON v.barrier_id=s.barrier_id AND v.permit_id=x.permit_id
  WHERE x.change_id=NEW.change_id AND m.operation_id=NEW.operation_id AND x.disposition!=CASE
   WHEN d.disposition='in_flight' THEN 'in_flight' WHEN s.retirement_exit_id IS NOT NULL THEN 'unknown' ELSE v.disposition END)
  THEN RAISE(ABORT,'control_effective_classification') END;
END;
CREATE TRIGGER cu_revocation_guard BEFORE INSERT ON cu_revocation BEGIN
 SELECT CASE WHEN (NEW.kind='ack' AND NOT EXISTS(SELECT 1 FROM cu_ack WHERE barrier_id=NEW.object_id)) OR
  (NEW.kind='retirement' AND NOT EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.object_id)) THEN RAISE(ABORT,'control_revocation_source') END;
END;
CREATE TRIGGER cu_revocation_close AFTER INSERT ON cu_revocation BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT m.release_id,'control_ack_revocation',NEW.object_id,NULL
 FROM (SELECT r.release_id,r.permit_id FROM cr_release_member r JOIN ce_settlement s USING(settlement_id) WHERE s.kind='never_sent'
  UNION SELECT r.release_id,r.permit_id FROM cx_release_member r JOIN cf_settlement s USING(settlement_id) WHERE s.kind='never_sent') m
 JOIN cr_release_commit k USING(release_id) JOIN cu_coverage c USING(permit_id)
 WHERE NEW.kind='ack' AND c.barrier_id=NEW.object_id AND c.disposition='not_sent';
 INSERT INTO cu_protection SELECT DISTINCT NEW.kind,NEW.object_id,c.device_id,e.exit_id FROM cu_selection s
 JOIN cu_effective f USING(change_id) JOIN ct_commit k USING(change_id) JOIN cu_cut c ON c.operation_id=f.operation_id JOIN ce_exit e ON e.device_id=c.device_id
 WHERE ((NEW.kind='ack' AND s.barrier_id=NEW.object_id) OR (NEW.kind='retirement' AND s.retirement_exit_id=NEW.object_id))
 AND (NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id) OR EXISTS(
  SELECT 1 FROM cu_revocation r WHERE r.kind='retirement' AND r.object_id=e.exit_id));
END;
CREATE TRIGGER cu_new_exit_close AFTER INSERT ON ce_exit BEGIN
 INSERT OR IGNORE INTO cu_protection SELECT r.kind,r.object_id,NEW.device_id,NEW.exit_id FROM cu_revocation r
 JOIN cu_selection s ON (r.kind='ack' AND r.object_id=s.barrier_id) OR (r.kind='retirement' AND r.object_id=s.retirement_exit_id)
 JOIN cu_effective f USING(change_id) JOIN ct_commit k USING(change_id) JOIN cu_cut c ON c.operation_id=f.operation_id WHERE c.device_id=NEW.device_id;
END;
