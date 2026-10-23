-- ordinary/all关闭、编码准备与原ACK关联候选。由生成器组合，非生产迁移。
CREATE TABLE cc_cut (
 cut_id TEXT PRIMARY KEY NOT NULL,
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel_commit(cancellation_id),
 stage TEXT NOT NULL CHECK(stage IN ('ordinary','all')),
 previous_cut_id TEXT REFERENCES cc_cut(cut_id),
 issued_revision TEXT NOT NULL CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*'),
 cut_digest TEXT NOT NULL,
 cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 UNIQUE(cancellation_id,stage), UNIQUE(cut_id,cancellation_id),
 CHECK((stage='ordinary' AND previous_cut_id IS NULL) OR (stage='all' AND previous_cut_id IS NOT NULL)),
 FOREIGN KEY(cut_id) REFERENCES cc_cut_commit(cut_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cc_target (
 cut_id TEXT NOT NULL REFERENCES cc_cut(cut_id), exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 target_digest TEXT NOT NULL, target_body BLOB NOT NULL CHECK(length(target_body)>0),
 PRIMARY KEY(cut_id,exit_id)
) STRICT;
CREATE TABLE cc_member (
 cut_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL REFERENCES ci_issue(permit_id),
 entered_known INTEGER NOT NULL CHECK(entered_known IN (0,1)),
 PRIMARY KEY(cut_id,permit_id), UNIQUE(cut_id,exit_id,permit_id),
 FOREIGN KEY(cut_id,exit_id) REFERENCES cc_target(cut_id,exit_id)
) STRICT;
CREATE TABLE cc_cut_commit (
 cut_id TEXT PRIMARY KEY NOT NULL REFERENCES cc_cut(cut_id),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cc_attempt (
 barrier_id TEXT PRIMARY KEY NOT NULL, cut_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 2147483647),
 previous_barrier_id TEXT,
 request_digest TEXT NOT NULL, request_body BLOB NOT NULL CHECK(length(request_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 UNIQUE(cut_id,exit_id,ordinal), UNIQUE(barrier_id,cut_id,exit_id),
 CHECK((ordinal=1 AND previous_barrier_id IS NULL) OR (ordinal>1 AND previous_barrier_id IS NOT NULL)),
 FOREIGN KEY(cut_id,exit_id) REFERENCES cc_target(cut_id,exit_id),
 FOREIGN KEY(previous_barrier_id,cut_id,exit_id) REFERENCES cc_attempt(barrier_id,cut_id,exit_id)
) STRICT;
CREATE TABLE cc_failure (
 barrier_id TEXT PRIMARY KEY NOT NULL REFERENCES cc_attempt(barrier_id),
 reason TEXT NOT NULL CHECK(reason IN ('cache_miss','deadline_elapsed','channel_lost')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cc_coverage (
 barrier_id TEXT NOT NULL, cut_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK((disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR (disposition='unknown' AND proof='send_uncertain')),
 PRIMARY KEY(barrier_id,permit_id),
 FOREIGN KEY(barrier_id,cut_id,exit_id) REFERENCES cc_attempt(barrier_id,cut_id,exit_id),
 FOREIGN KEY(cut_id,exit_id,permit_id) REFERENCES cc_member(cut_id,exit_id,permit_id),
 FOREIGN KEY(barrier_id) REFERENCES cc_ack(barrier_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cc_ack (
 barrier_id TEXT PRIMARY KEY NOT NULL REFERENCES cc_attempt(barrier_id),
 ack_digest TEXT NOT NULL, ack_body BLOB NOT NULL CHECK(length(ack_body)>0),
 effective_tick TEXT NOT NULL CHECK(length(effective_tick)=20 AND effective_tick NOT GLOB '*[^0-9]*'),
 gate_io_seq TEXT NOT NULL CHECK(length(gate_io_seq)=20 AND gate_io_seq NOT GLOB '*[^0-9]*'),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cc_selection (
 closure_id TEXT NOT NULL, cut_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('worker_ack','supervisor_retired')),
 barrier_id TEXT REFERENCES cc_ack(barrier_id), retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(closure_id,exit_id),
 CHECK((kind='worker_ack' AND barrier_id IS NOT NULL AND retirement_exit_id IS NULL) OR
  (kind='supervisor_retired' AND barrier_id IS NULL AND retirement_exit_id IS exit_id)),
 FOREIGN KEY(cut_id,exit_id) REFERENCES cc_target(cut_id,exit_id),
 FOREIGN KEY(closure_id,cut_id) REFERENCES cc_closure(closure_id,cut_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(barrier_id,cut_id,exit_id) REFERENCES cc_attempt(barrier_id,cut_id,exit_id)
) STRICT;
CREATE TABLE cc_closure (
 closure_id TEXT PRIMARY KEY NOT NULL, cut_id TEXT NOT NULL REFERENCES cc_cut_commit(cut_id),
 closure_digest TEXT NOT NULL, closure_body BLOB NOT NULL CHECK(length(closure_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0), UNIQUE(closure_id,cut_id)
) STRICT;
CREATE TABLE cc_revocation (
 closure_id TEXT PRIMARY KEY NOT NULL REFERENCES cc_closure(closure_id),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cc_prepare (
 prepare_id TEXT PRIMARY KEY NOT NULL, cancellation_id TEXT NOT NULL REFERENCES cv_cancel_commit(cancellation_id),
 ordinary_closure_id TEXT NOT NULL REFERENCES cc_closure(closure_id),
 execution_id TEXT NOT NULL, execution_digest TEXT NOT NULL, primitive_id TEXT NOT NULL,
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 prepare_body BLOB NOT NULL CHECK(length(prepare_body)>0), validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0), outbox_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0), UNIQUE(cancellation_id,primitive_id)
) STRICT;
CREATE TABLE cc_cut_prepare (
 cut_id TEXT NOT NULL, exit_id TEXT NOT NULL, prepare_id TEXT NOT NULL REFERENCES cc_prepare(prepare_id),
 PRIMARY KEY(cut_id,prepare_id), UNIQUE(cut_id,exit_id,prepare_id),
 FOREIGN KEY(cut_id,exit_id) REFERENCES cc_target(cut_id,exit_id)
) STRICT;
CREATE TABLE cc_ack_prepare (
 barrier_id TEXT NOT NULL, cut_id TEXT NOT NULL, exit_id TEXT NOT NULL, prepare_id TEXT NOT NULL,
 PRIMARY KEY(barrier_id,prepare_id),
 FOREIGN KEY(barrier_id,cut_id,exit_id) REFERENCES cc_attempt(barrier_id,cut_id,exit_id),
 FOREIGN KEY(cut_id,exit_id,prepare_id) REFERENCES cc_cut_prepare(cut_id,exit_id,prepare_id),
 FOREIGN KEY(barrier_id) REFERENCES cc_ack(barrier_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cc_packet (
 packet_id TEXT PRIMARY KEY NOT NULL, prepare_id TEXT NOT NULL UNIQUE REFERENCES cc_prepare(prepare_id),
 packet_digest TEXT NOT NULL, packet_bytes BLOB NOT NULL CHECK(length(packet_bytes)>0),
 packet_body BLOB NOT NULL CHECK(length(packet_body)>0), validation_body BLOB NOT NULL CHECK(length(validation_body)>0)
) STRICT;
CREATE TABLE cc_dispatch (
 permit_id TEXT PRIMARY KEY NOT NULL REFERENCES ci_cancel_transmission(permit_id),
 packet_id TEXT NOT NULL REFERENCES cc_packet(packet_id),
 FOREIGN KEY(permit_id) REFERENCES ci_cancel_commit(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW cc_valid_closure AS
 SELECT c.* FROM cc_closure c WHERE NOT EXISTS(SELECT 1 FROM cc_revocation r WHERE r.closure_id=c.closure_id);
CREATE VIEW cc_expected_member AS
 SELECT c.cut_id,p.exit_id,p.permit_id FROM cc_cut c JOIN cv_cancel_permit v USING(cancellation_id)
 JOIN ce_permit p USING(permit_id)
 UNION SELECT c.cut_id,p.exit_id,p.permit_id FROM cc_cut c JOIN ci_cancel_transmission p USING(cancellation_id)
 WHERE c.stage='all';
CREATE VIEW cc_expected_target AS
 SELECT c.cut_id,t.exit_id FROM cc_cut c JOIN cv_cancel_target t USING(cancellation_id)
 UNION SELECT c.cut_id,e.exit_id FROM cc_cut c JOIN cv_cancel v USING(cancellation_id)
 JOIN ce_command cmd USING(command_id) JOIN ce_exit e USING(device_id) WHERE c.stage='all';
CREATE VIEW cc_expected_prepare AS
 SELECT c.cut_id,p.exit_id,p.prepare_id FROM cc_cut c JOIN cc_prepare p USING(cancellation_id) WHERE c.stage='all';
CREATE TRIGGER cc_cut_guard BEFORE INSERT ON cc_cut BEGIN
 SELECT CASE WHEN NEW.stage='ordinary' AND NOT EXISTS(SELECT 1 FROM cv_cancel
  WHERE cancellation_id=NEW.cancellation_id AND cut_revision=NEW.issued_revision AND cut_digest=NEW.cut_digest)
  THEN RAISE(ABORT,'ordinary_cut_binding') END;
 SELECT CASE WHEN NEW.stage='all' AND (NEW.issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  OR NOT EXISTS(SELECT 1 FROM cc_cut c JOIN cc_cut_commit k USING(cut_id)
   WHERE c.cut_id=NEW.previous_cut_id AND c.cancellation_id=NEW.cancellation_id AND c.stage='ordinary'))
  THEN RAISE(ABORT,'all_cut_binding') END;
END;
CREATE TRIGGER cc_cut_seal BEFORE INSERT ON cc_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_cut WHERE cut_id=NEW.cut_id AND stage='all'
  AND issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue))
  THEN RAISE(ABORT,'all_cut_changed') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM cc_expected_target WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id FROM cc_target WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT exit_id FROM cc_target WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id FROM cc_expected_target WHERE cut_id=NEW.cut_id) THEN RAISE(ABORT,'closure_target_set') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id,permit_id FROM cc_expected_member WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id,permit_id FROM cc_member WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT exit_id,permit_id FROM cc_member WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id,permit_id FROM cc_expected_member WHERE cut_id=NEW.cut_id) THEN RAISE(ABORT,'closure_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id,prepare_id FROM cc_expected_prepare WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id,prepare_id FROM cc_cut_prepare WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT exit_id,prepare_id FROM cc_cut_prepare WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id,prepare_id FROM cc_expected_prepare WHERE cut_id=NEW.cut_id) THEN RAISE(ABORT,'closure_prepare_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_member m JOIN ci_issue i USING(permit_id)
  LEFT JOIN ce_current_disposition o USING(permit_id) LEFT JOIN cf_disposition p USING(permit_id)
  WHERE m.cut_id=NEW.cut_id AND m.entered_known!=(coalesce(o.disposition,p.disposition)='in_flight'))
  THEN RAISE(ABORT,'closure_entered_snapshot') END;
 SELECT CASE WHEN EXISTS(SELECT m.exit_id,i.kind FROM cc_member m JOIN ci_issue i USING(permit_id)
  WHERE m.cut_id=NEW.cut_id GROUP BY m.exit_id,i.kind HAVING count(*)>256)
  THEN RAISE(ABORT,'closure_capacity') END;
END;
CREATE TRIGGER cc_attempt_guard BEFORE INSERT ON cc_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_cut_commit WHERE cut_id=NEW.cut_id)
  OR EXISTS(SELECT 1 FROM cc_valid_closure WHERE cut_id=NEW.cut_id)
  OR EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id) THEN RAISE(ABORT,'closure_attempt_closed') END;
 SELECT CASE WHEN NEW.ordinal!=(SELECT coalesce(max(ordinal),0)+1 FROM cc_attempt WHERE cut_id=NEW.cut_id AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'closure_attempt_ordinal') END;
 SELECT CASE WHEN NEW.ordinal>1 AND NOT EXISTS(SELECT 1 FROM cc_attempt a JOIN cc_failure f USING(barrier_id)
  WHERE a.barrier_id=NEW.previous_barrier_id AND a.cut_id=NEW.cut_id AND a.exit_id=NEW.exit_id
   AND a.ordinal=NEW.ordinal-1 AND f.reason IN ('cache_miss','deadline_elapsed')) THEN RAISE(ABORT,'closure_retry_basis') END;
END;
CREATE TRIGGER cc_failure_guard BEFORE INSERT ON cc_failure WHEN EXISTS(SELECT 1 FROM cc_ack WHERE barrier_id=NEW.barrier_id)
 BEGIN SELECT RAISE(ABORT,'closure_ack_stored'); END;
CREATE TRIGGER cc_ack_guard BEFORE INSERT ON cc_ack BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM cc_ack_prepare WHERE barrier_id=NEW.barrier_id)!=
  (SELECT count(*) FROM cc_cut_prepare m JOIN cc_attempt a USING(cut_id,exit_id) WHERE a.barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'closure_ack_prepare_incomplete') END;
 SELECT CASE WHEN (SELECT count(*) FROM cc_coverage WHERE barrier_id=NEW.barrier_id)!=
  (SELECT count(*) FROM cc_member m JOIN cc_attempt a USING(cut_id,exit_id) WHERE a.barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'closure_ack_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_coverage c JOIN cc_member m USING(cut_id,exit_id,permit_id)
  WHERE c.barrier_id=NEW.barrier_id AND m.entered_known=1 AND c.disposition!='in_flight')
  THEN RAISE(ABORT,'closure_ack_downgrade') END;
END;
CREATE TRIGGER cc_selection_guard BEFORE INSERT ON cc_selection BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_closure WHERE closure_id=NEW.closure_id)
  THEN RAISE(ABORT,'closure_selection_frozen') END;
 SELECT CASE WHEN NEW.kind='worker_ack' AND NOT EXISTS(SELECT 1 FROM cc_attempt a JOIN cc_ack k USING(barrier_id)
  WHERE a.barrier_id=NEW.barrier_id AND a.cut_id=NEW.cut_id AND a.exit_id=NEW.exit_id
   AND NOT EXISTS(SELECT 1 FROM cc_failure WHERE barrier_id=a.barrier_id)
   AND a.ordinal=(SELECT max(ordinal) FROM cc_attempt WHERE cut_id=a.cut_id AND exit_id=a.exit_id))
  THEN RAISE(ABORT,'closure_ack_not_current') END;
END;
CREATE TRIGGER cc_closure_guard BEFORE INSERT ON cc_closure BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_valid_closure WHERE cut_id=NEW.cut_id)
  THEN RAISE(ABORT,'closure_already_valid') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM cc_target WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id FROM cc_selection WHERE closure_id=NEW.closure_id AND cut_id=NEW.cut_id)
  THEN RAISE(ABORT,'closure_targets_unresolved') END;
END;
CREATE TRIGGER cc_prepare_guard BEFORE INSERT ON cc_prepare BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_valid_closure h JOIN cc_cut t USING(cut_id)
  JOIN cv_cancel c USING(cancellation_id) JOIN ce_command cmd USING(command_id) JOIN ce_exit e USING(device_id)
  WHERE h.closure_id=NEW.ordinary_closure_id AND t.stage='ordinary' AND c.cancellation_id=NEW.cancellation_id
   AND c.mode='cooperative' AND e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'cancel_prepare_closure') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_cut WHERE cancellation_id=NEW.cancellation_id AND stage='all')
  OR EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id)
  OR EXISTS(SELECT 1 FROM cv_cancel_current WHERE cancellation_id=NEW.cancellation_id AND state!='requested')
  THEN RAISE(ABORT,'cancel_prepare_closed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_prepare WHERE cancellation_id=NEW.cancellation_id
  AND (execution_id!=NEW.execution_id OR execution_digest!=NEW.execution_digest))
  THEN RAISE(ABORT,'cancel_prepare_execution_changed') END;
END;
CREATE TRIGGER cc_packet_guard BEFORE INSERT ON cc_packet BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_prepare p JOIN cc_cut c USING(cancellation_id)
  WHERE p.prepare_id=NEW.prepare_id AND c.stage='all') THEN RAISE(ABORT,'cancel_packet_closed') END;
END;
CREATE TRIGGER cc_dispatch_guard BEFORE INSERT ON ci_cancel_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_dispatch d JOIN cc_packet b USING(packet_id)
  JOIN cc_prepare p USING(prepare_id) JOIN cc_valid_closure h ON h.closure_id=p.ordinary_closure_id
  JOIN ci_cancel_transmission t ON t.permit_id=d.permit_id
  WHERE d.permit_id=NEW.permit_id AND t.cancellation_id=p.cancellation_id AND t.execution_id=p.execution_id
   AND t.execution_digest=p.execution_digest AND t.primitive_id=p.primitive_id AND t.exit_id=p.exit_id
   AND t.packet_id=b.packet_id AND t.packet_digest=b.packet_digest AND NEW.packet_bytes=b.packet_bytes)
  THEN RAISE(ABORT,'cancel_dispatch_source') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cc_cut c USING(cancellation_id)
  WHERE t.permit_id=NEW.permit_id AND c.stage='all') THEN RAISE(ABORT,'cancel_issuance_closed') END;
END;
CREATE TRIGGER cc_revision_guard BEFORE INSERT ON cv_cancel_revision WHEN NEW.future_writes='closed' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_valid_closure h JOIN cc_cut t USING(cut_id)
  WHERE h.closure_id=NEW.closure_id AND t.cancellation_id=NEW.cancellation_id AND t.stage='all')
  THEN RAISE(ABORT,'public_all_closure_required') END;
END;
CREATE TRIGGER cc_resource_guard BEFORE INSERT ON cx_closure BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel_revision r JOIN cc_valid_closure h ON h.closure_id=r.closure_id
  WHERE r.cancellation_id=NEW.cancellation_id AND r.revision=NEW.operation_revision AND h.closure_digest=NEW.closure_digest)
  THEN RAISE(ABORT,'resource_all_closure_required') END;
END;
CREATE TRIGGER cc_revoke AFTER INSERT ON cc_revocation BEGIN
 INSERT OR IGNORE INTO cr_validation_revocation
 SELECT x.validation_id,NEW.reason_body,NEW.audit_body FROM cx_closure x JOIN cv_cancel_revision r
  ON r.cancellation_id=x.cancellation_id AND r.revision=x.operation_revision WHERE r.closure_id=NEW.closure_id;
END;
