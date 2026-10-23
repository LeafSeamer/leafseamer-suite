-- 取消资源核销候选；与99表组合，所有BODY权威仍由可信提供者验证。
CREATE TABLE cx_closure (
 cancellation_id TEXT NOT NULL,
 operation_revision TEXT NOT NULL,
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_validation(validation_id),
 closure_digest TEXT NOT NULL,
 closure_body BLOB NOT NULL CHECK(length(closure_body)>0),
 UNIQUE(cancellation_id,validation_id),
 FOREIGN KEY(cancellation_id,operation_revision) REFERENCES cv_cancel_revision(cancellation_id,revision)
) STRICT;
CREATE TABLE cx_settlement (
 settlement_id TEXT PRIMARY KEY NOT NULL REFERENCES cf_settlement(settlement_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 settlement_digest TEXT NOT NULL
) STRICT;
CREATE TABLE cx_release_cancel (
 release_id TEXT NOT NULL REFERENCES cr_release(release_id),
 cancellation_id TEXT NOT NULL,
 closure_validation_id TEXT NOT NULL,
 PRIMARY KEY(release_id,cancellation_id),
 FOREIGN KEY(cancellation_id,closure_validation_id) REFERENCES cx_closure(cancellation_id,validation_id)
) STRICT;
CREATE TABLE cx_release_member (
 release_id TEXT NOT NULL REFERENCES cr_release(release_id),
 permit_id TEXT NOT NULL REFERENCES ci_cancel_transmission(permit_id),
 settlement_id TEXT NOT NULL REFERENCES cx_settlement(settlement_id),
 PRIMARY KEY(release_id,permit_id)
) STRICT;
DROP VIEW cr_release_validation;
CREATE VIEW cr_release_validation AS
 SELECT release_id,validation_id FROM cr_release
 UNION SELECT release_id,closure_validation_id FROM cr_release_attempt
 UNION SELECT m.release_id,s.validation_id FROM cr_release_member m JOIN cr_settlement_validation s USING(settlement_id)
 UNION SELECT release_id,closure_validation_id FROM cx_release_cancel
 UNION SELECT m.release_id,s.validation_id FROM cx_release_member m JOIN cx_settlement s USING(settlement_id);
DROP VIEW cr_invalid_release;
CREATE VIEW cr_invalid_release AS
 SELECT r.release_id FROM cr_release r JOIN cr_release_commit k USING(release_id)
 WHERE EXISTS(SELECT 1 FROM cr_release_validation p WHERE p.release_id=r.release_id
  AND NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=p.validation_id))
 OR EXISTS(SELECT 1 FROM cr_release_member m JOIN cr_settlement_validation sv USING(settlement_id)
  JOIN ce_settlement s USING(settlement_id) JOIN ce_current_disposition d ON d.permit_id=m.permit_id
  WHERE m.release_id=r.release_id AND (NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=sv.validation_id)
   OR (s.kind='never_sent' AND d.disposition='in_flight')))
 OR EXISTS(SELECT 1 FROM cx_release_member m JOIN cf_settlement s USING(settlement_id)
  JOIN cf_disposition d ON d.permit_id=m.permit_id WHERE m.release_id=r.release_id
   AND s.kind='never_sent' AND d.disposition='in_flight');
CREATE TRIGGER cx_closure_guard BEFORE INSERT ON cx_closure BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel c JOIN cv_cancel_revision r USING(cancellation_id)
  JOIN cm_commit k ON k.command_id=r.command_id AND k.revision=r.state_revision
  JOIN ce_command cmd ON cmd.command_id=c.command_id JOIN cr_claim policy ON policy.command_id=c.command_id
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE c.cancellation_id=NEW.cancellation_id AND r.revision=NEW.operation_revision AND r.future_writes='closed'
   AND v.command_id=c.command_id AND v.device_id=cmd.device_id AND v.purpose='close'
   AND v.subject_id=c.cancellation_id AND v.subject_digest=NEW.closure_digest AND v.policy_ref=policy.release_policy_ref)
  THEN RAISE(ABORT,'cancel_all_closure_binding') END;
END;
CREATE TRIGGER cx_settlement_guard BEFORE INSERT ON cx_settlement BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cf_settlement s JOIN ci_cancel_transmission p USING(permit_id)
  JOIN cv_cancel c USING(cancellation_id) JOIN ce_command cmd USING(command_id) JOIN cr_claim policy USING(command_id)
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE s.settlement_id=NEW.settlement_id AND v.command_id=c.command_id AND v.device_id=cmd.device_id
   AND v.purpose='settlement' AND v.subject_id=s.settlement_id AND v.subject_digest=NEW.settlement_digest
   AND v.policy_ref=policy.release_policy_ref) THEN RAISE(ABORT,'cancel_settlement_binding') END;
END;
CREATE TRIGGER cx_release_guard BEFORE INSERT ON cr_release_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT c.cancellation_id FROM cv_cancel c JOIN cr_release r USING(command_id)
  WHERE r.release_id=NEW.release_id EXCEPT SELECT cancellation_id FROM cx_release_cancel WHERE release_id=NEW.release_id)
 OR EXISTS(SELECT cancellation_id FROM cx_release_cancel WHERE release_id=NEW.release_id
  EXCEPT SELECT c.cancellation_id FROM cv_cancel c JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id)
  THEN RAISE(ABORT,'cancel_release_closure_set') END;
 SELECT CASE WHEN EXISTS(SELECT p.permit_id FROM ci_cancel_transmission p JOIN cv_cancel c USING(cancellation_id)
  JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id
  EXCEPT SELECT permit_id FROM cx_release_member WHERE release_id=NEW.release_id)
 OR EXISTS(SELECT permit_id FROM cx_release_member WHERE release_id=NEW.release_id
  EXCEPT SELECT p.permit_id FROM ci_cancel_transmission p JOIN cv_cancel c USING(cancellation_id)
  JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id)
  THEN RAISE(ABORT,'cancel_release_permit_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cx_release_cancel x WHERE x.release_id=NEW.release_id
  AND NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=x.closure_validation_id))
  THEN RAISE(ABORT,'cancel_closure_revoked') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cx_release_member m JOIN cf_settlement s USING(settlement_id)
  JOIN cx_settlement sv USING(settlement_id) JOIN cf_disposition d ON d.permit_id=m.permit_id
  JOIN cr_release r USING(release_id) WHERE m.release_id=NEW.release_id AND
   (s.permit_id!=m.permit_id OR NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=sv.validation_id)
    OR (s.kind='never_sent' AND d.disposition!='not_sent') OR (r.kind='never_sent' AND s.kind!='never_sent')))
  THEN RAISE(ABORT,'cancel_release_member_unproven') END;
END;
CREATE TRIGGER cx_report_invalidation AFTER INSERT ON cf_report WHEN NEW.disposition='in_flight' BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT x.release_id,'cancel_report',NEW.report_id,NULL FROM cr_invalid_release x
 JOIN cx_release_member m USING(release_id) WHERE m.permit_id=NEW.permit_id;
END;
CREATE TRIGGER cx_ack_invalidation AFTER INSERT ON ce_barrier_ack BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT x.release_id,'barrier_ack',NEW.barrier_id,NULL FROM cr_invalid_release x
 JOIN cx_release_member m USING(release_id) JOIN cf_barrier_coverage b USING(permit_id)
 WHERE b.barrier_id=NEW.barrier_id AND b.disposition='in_flight';
END;
CREATE TRIGGER cx_target_invalidation AFTER INSERT ON ce_target_result BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT x.release_id,'target_result',NEW.fence_id,NEW.exit_id FROM cr_invalid_release x
 JOIN cx_release_member m USING(release_id) JOIN cf_target_coverage b USING(permit_id)
 WHERE b.fence_id=NEW.fence_id AND b.exit_id=NEW.exit_id AND b.disposition='in_flight';
END;
