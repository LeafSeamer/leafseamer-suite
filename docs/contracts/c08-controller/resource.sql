-- 在controller.sql、fence.sql、barrier-attempt.sql之后加载。
-- 资源领域候选，不是生产迁移；BODY/提供者真实性仍由可信writer验证。
CREATE TABLE cr_validation (
 validation_id TEXT PRIMARY KEY NOT NULL,
 scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
 command_id TEXT REFERENCES ce_command(command_id),
 device_id TEXT NOT NULL CHECK(length(device_id)>0),
 purpose TEXT NOT NULL CHECK(purpose IN ('hold','close','settlement','release','recovery')),
 subject_id TEXT NOT NULL CHECK(length(subject_id)>0),
 subject_digest TEXT NOT NULL CHECK(length(subject_digest)=71 AND substr(subject_digest,1,7)='sha256:'
  AND substr(subject_digest,8) NOT GLOB '*[^0-9a-f]*'),
 policy_ref TEXT NOT NULL CHECK(length(policy_ref)>0),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),
 source_body BLOB NOT NULL CHECK(length(source_body)>0),
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 CHECK((purpose='recovery' AND command_id IS NULL) OR (purpose!='recovery' AND command_id IS NOT NULL)),
 UNIQUE(validation_id,device_id)
) STRICT;
CREATE TABLE cr_validation_revocation (
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_validation(validation_id),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cr_claim (
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_command(command_id),
 release_policy_ref TEXT NOT NULL CHECK(length(release_policy_ref)>0),
 policy_body BLOB NOT NULL CHECK(length(policy_body)>0)
) STRICT;
CREATE TABLE cr_hold (
 hold_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL REFERENCES cr_claim(command_id),
 attempt_id TEXT NOT NULL UNIQUE REFERENCES ce_attempt(attempt_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 hold_digest TEXT NOT NULL,
 hold_body BLOB NOT NULL CHECK(length(hold_body)>0),
 UNIQUE(hold_id,command_id),
 FOREIGN KEY(hold_id) REFERENCES cr_hold_commit(hold_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cr_hold_commit (
 hold_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_hold(hold_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cr_hold_close (
 hold_id TEXT NOT NULL REFERENCES cr_hold_commit(hold_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 closure_digest TEXT NOT NULL,
 closure_body BLOB NOT NULL CHECK(length(closure_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(hold_id,validation_id)
) STRICT;
CREATE TABLE cr_settlement_validation (
 settlement_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_settlement(settlement_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 settlement_digest TEXT NOT NULL
) STRICT;
CREATE TABLE cr_release (
 release_id TEXT PRIMARY KEY NOT NULL,
 hold_id TEXT NOT NULL,
 command_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('never_sent','module_settled','maintenance_fenced')),
 issued_cut_revision TEXT NOT NULL CHECK(length(issued_cut_revision)=20
  AND issued_cut_revision NOT GLOB '*[^0-9]*'),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 release_digest TEXT NOT NULL,
 cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 release_body BLOB NOT NULL CHECK(length(release_body)>0),
 FOREIGN KEY(hold_id,command_id) REFERENCES cr_hold(hold_id,command_id),
 FOREIGN KEY(release_id) REFERENCES cr_release_commit(release_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cr_release_attempt (
 release_id TEXT NOT NULL REFERENCES cr_release(release_id),
 attempt_id TEXT NOT NULL REFERENCES ce_attempt(attempt_id),
 hold_id TEXT NOT NULL REFERENCES cr_hold(hold_id),
 closure_validation_id TEXT NOT NULL,
 PRIMARY KEY(release_id,attempt_id),
 FOREIGN KEY(hold_id,closure_validation_id) REFERENCES cr_hold_close(hold_id,validation_id)
) STRICT;
CREATE TABLE cr_release_member (
 release_id TEXT NOT NULL REFERENCES cr_release(release_id),
 permit_id TEXT NOT NULL REFERENCES ce_permit(permit_id),
 settlement_id TEXT NOT NULL REFERENCES cr_settlement_validation(settlement_id),
 PRIMARY KEY(release_id,permit_id)
) STRICT;
CREATE TABLE cr_release_commit (
 release_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_release(release_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
-- 失效就是本机设备保护锁存。来源记录永久保留；同release只存首次失效原因，
-- 后续原始证据仍完整留在ce_*及revocation，不被此行去重丢弃。
CREATE TABLE cr_release_invalidation (
 release_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_release_commit(release_id),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('report','barrier_ack','target_result','validation_revocation')),
 source_id TEXT NOT NULL,
 source_exit_id TEXT,
 CHECK((source_kind='target_result' AND source_exit_id IS NOT NULL)
    OR (source_kind!='target_result' AND source_exit_id IS NULL))
) STRICT;
CREATE TABLE cr_recovery (
 recovery_id TEXT PRIMARY KEY NOT NULL,
 device_id TEXT NOT NULL,
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 recovery_digest TEXT NOT NULL,
 recovery_body BLOB NOT NULL CHECK(length(recovery_body)>0),
 FOREIGN KEY(recovery_id) REFERENCES cr_recovery_commit(recovery_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cr_recovery_member (
 recovery_id TEXT NOT NULL REFERENCES cr_recovery(recovery_id),
 release_id TEXT NOT NULL REFERENCES cr_release_invalidation(release_id),
 PRIMARY KEY(recovery_id,release_id)
) STRICT;
CREATE TABLE cr_recovery_commit (
 recovery_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_recovery(recovery_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;

CREATE VIEW cr_valid_validation AS
 SELECT v.* FROM cr_validation v WHERE NOT EXISTS(
 SELECT 1 FROM cr_validation_revocation x WHERE x.validation_id=v.validation_id);
CREATE VIEW cr_release_validation AS
 SELECT release_id,validation_id FROM cr_release
 UNION SELECT release_id,closure_validation_id FROM cr_release_attempt
 UNION SELECT m.release_id,s.validation_id FROM cr_release_member m
 JOIN cr_settlement_validation s USING(settlement_id);
CREATE VIEW cr_invalid_release AS
 SELECT r.release_id FROM cr_release r JOIN cr_release_commit k USING(release_id)
 WHERE EXISTS(SELECT 1 FROM cr_release_validation p WHERE p.release_id=r.release_id
  AND NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=p.validation_id))
 OR EXISTS(SELECT 1 FROM cr_release_member m
   JOIN cr_settlement_validation sv USING(settlement_id) JOIN ce_settlement s USING(settlement_id)
   JOIN ce_current_disposition d ON d.permit_id=m.permit_id WHERE m.release_id=r.release_id
   AND (NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=sv.validation_id)
        OR (s.kind='never_sent' AND d.disposition='in_flight')));
-- 同一hold可追加新的完整释放；旧invalid记录及其设备锁存不删除。
CREATE VIEW cr_risk_hold AS
 SELECT h.*,c.device_id,c.origin FROM cr_hold h JOIN ce_command c USING(command_id)
 WHERE NOT EXISTS(SELECT 1 FROM cr_release r JOIN cr_release_commit k USING(release_id)
   WHERE r.hold_id=h.hold_id
   AND NOT EXISTS(SELECT 1 FROM cr_invalid_release x WHERE x.release_id=r.release_id)
   AND NOT EXISTS(SELECT 1 FROM cr_release_invalidation x WHERE x.release_id=r.release_id));
CREATE VIEW cr_device_protection AS
 SELECT x.release_id,h.command_id,c.device_id FROM cr_release_invalidation x
 JOIN cr_release r USING(release_id) JOIN cr_hold h USING(hold_id) JOIN ce_command c ON c.command_id=h.command_id
 WHERE NOT EXISTS(SELECT 1 FROM cr_recovery_member m JOIN cr_recovery y USING(recovery_id)
 JOIN cr_recovery_commit k USING(recovery_id) JOIN cr_valid_validation v ON v.validation_id=y.validation_id
 WHERE m.release_id=x.release_id AND y.device_id=c.device_id);

CREATE TRIGGER cr_claim_accept BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial c JOIN cr_claim p USING(command_id)
  WHERE c.key_id=NEW.key_id) THEN RAISE(ABORT,'resource_claim_required') END;
END;
CREATE TRIGGER cr_hold_guard BEFORE INSERT ON cr_hold BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_command c USING(command_id)
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE a.attempt_id=NEW.attempt_id AND c.command_id=NEW.command_id
   AND v.command_id=NEW.command_id AND v.device_id=c.device_id AND v.purpose='hold'
   AND v.subject_id=NEW.hold_id AND v.subject_digest=NEW.hold_digest)
  THEN RAISE(ABORT,'hold_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_risk_hold h JOIN ce_command c ON c.device_id=h.device_id
  WHERE c.command_id=NEW.command_id) THEN RAISE(ABORT,'resource_busy') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_device_protection p JOIN ce_command c USING(device_id)
  WHERE c.command_id=NEW.command_id) THEN RAISE(ABORT,'device_protected') END;
END;
CREATE TRIGGER cr_hold_seal BEFORE INSERT ON cr_hold_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_hold h JOIN ce_permit p USING(attempt_id)
  JOIN ce_transmission_commit t USING(permit_id) WHERE h.hold_id=NEW.hold_id)
  THEN RAISE(ABORT,'hold_without_transmission') END;
END;
CREATE TRIGGER cr_permit_guard BEFORE INSERT ON ce_permit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_hold h JOIN cr_valid_validation v USING(validation_id)
  WHERE h.attempt_id=NEW.attempt_id) THEN RAISE(ABORT,'hold_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_hold h JOIN cr_hold_close c USING(hold_id)
  WHERE h.attempt_id=NEW.attempt_id) THEN RAISE(ABORT,'hold_closed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_command c USING(command_id)
  JOIN cr_device_protection p USING(device_id) WHERE a.attempt_id=NEW.attempt_id)
  THEN RAISE(ABORT,'device_protected') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_hold h JOIN ce_command c USING(command_id)
  JOIN cr_risk_hold other ON other.device_id=c.device_id AND other.hold_id!=h.hold_id
  WHERE h.attempt_id=NEW.attempt_id) THEN RAISE(ABORT,'resource_busy') END;
END;
CREATE TRIGGER cr_close_guard BEFORE INSERT ON cr_hold_close BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_hold h JOIN ce_command c USING(command_id)
  JOIN cr_claim p USING(command_id) JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE h.hold_id=NEW.hold_id AND v.command_id=h.command_id AND v.device_id=c.device_id
   AND v.purpose='close' AND v.subject_id=h.hold_id AND v.subject_digest=NEW.closure_digest
   AND v.policy_ref=p.release_policy_ref) THEN RAISE(ABORT,'closure_binding') END;
END;
CREATE TRIGGER cr_settlement_guard BEFORE INSERT ON cr_settlement_validation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_settlement s JOIN ce_permit t USING(permit_id)
  JOIN ce_attempt a USING(attempt_id) JOIN ce_command c USING(command_id) JOIN cr_claim p USING(command_id)
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE s.settlement_id=NEW.settlement_id AND v.command_id=c.command_id AND v.device_id=c.device_id
   AND v.purpose='settlement' AND v.subject_id=s.settlement_id
   AND v.subject_digest=NEW.settlement_digest AND v.policy_ref=p.release_policy_ref)
  THEN RAISE(ABORT,'settlement_binding') END;
END;
CREATE TRIGGER cr_release_seal BEFORE INSERT ON cr_release_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_release r JOIN ce_command c USING(command_id)
  JOIN cr_claim p USING(command_id) JOIN cr_valid_validation v USING(validation_id)
  WHERE r.release_id=NEW.release_id AND v.command_id=r.command_id AND v.device_id=c.device_id
   AND v.purpose='release' AND v.subject_id=r.release_id AND v.subject_digest=r.release_digest
   AND v.policy_ref=p.release_policy_ref
   AND r.issued_cut_revision=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ce_permit))
  THEN RAISE(ABORT,'release_binding') END;
 SELECT CASE WHEN EXISTS(SELECT a.attempt_id FROM ce_attempt a JOIN cr_release r USING(command_id)
  WHERE r.release_id=NEW.release_id EXCEPT SELECT attempt_id FROM cr_release_attempt WHERE release_id=NEW.release_id)
 OR EXISTS(SELECT attempt_id FROM cr_release_attempt WHERE release_id=NEW.release_id
  EXCEPT SELECT a.attempt_id FROM ce_attempt a JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id)
  THEN RAISE(ABORT,'release_attempt_set') END;
 SELECT CASE WHEN EXISTS(SELECT t.permit_id FROM ce_permit t JOIN ce_attempt a USING(attempt_id)
  JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id
  EXCEPT SELECT permit_id FROM cr_release_member WHERE release_id=NEW.release_id)
 OR EXISTS(SELECT permit_id FROM cr_release_member WHERE release_id=NEW.release_id
  EXCEPT SELECT t.permit_id FROM ce_permit t JOIN ce_attempt a USING(attempt_id)
  JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id)
  THEN RAISE(ABORT,'release_permit_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_release_attempt a WHERE a.release_id=NEW.release_id
  AND NOT EXISTS(SELECT 1 FROM cr_hold h JOIN cr_hold_close c USING(hold_id)
   JOIN cr_valid_validation v ON v.validation_id=c.validation_id
   WHERE h.attempt_id=a.attempt_id AND h.hold_id=a.hold_id AND c.validation_id=a.closure_validation_id))
  THEN RAISE(ABORT,'future_writes_not_closed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_release_member m JOIN ce_settlement s USING(settlement_id)
  JOIN cr_settlement_validation sv USING(settlement_id) JOIN ce_current_disposition d ON d.permit_id=m.permit_id
  JOIN cr_release r USING(release_id) WHERE m.release_id=NEW.release_id AND
   (m.permit_id!=s.permit_id OR NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=sv.validation_id)
    OR (s.kind='never_sent' AND d.disposition!='not_sent')
    OR (r.kind='never_sent' AND s.kind!='never_sent')))
  THEN RAISE(ABORT,'release_member_unproven') END;
END;
CREATE TRIGGER cr_release_attempt_frozen BEFORE INSERT ON cr_release_attempt
 WHEN EXISTS(SELECT 1 FROM cr_release_commit WHERE release_id=NEW.release_id)
 BEGIN SELECT RAISE(ABORT,'release_frozen'); END;
CREATE TRIGGER cr_release_member_frozen BEFORE INSERT ON cr_release_member
 WHEN EXISTS(SELECT 1 FROM cr_release_commit WHERE release_id=NEW.release_id)
 BEGIN SELECT RAISE(ABORT,'release_frozen'); END;
-- 封存核对当时全部集合；旧attempt永久close，不能再追加其permit。
-- 后续retry须在先前attempt释放封存之后新建attempt；政策由生命周期writer另验。
CREATE TRIGGER cr_attempt_predecessor BEFORE INSERT ON ce_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_attempt a WHERE a.command_id=NEW.command_id
  AND NOT EXISTS(SELECT 1 FROM cr_hold h JOIN cr_release r USING(hold_id)
    JOIN cr_release_commit k USING(release_id) WHERE h.attempt_id=a.attempt_id
    AND NOT EXISTS(SELECT 1 FROM cr_invalid_release x WHERE x.release_id=r.release_id)
    AND NOT EXISTS(SELECT 1 FROM cr_release_invalidation x WHERE x.release_id=r.release_id)))
 THEN RAISE(ABORT,'previous_attempt_unreleased') END;
END;

CREATE TRIGGER cr_report_invalidation AFTER INSERT ON ce_report WHEN NEW.disposition='in_flight' BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT x.release_id,'report',NEW.report_id,NULL FROM cr_invalid_release x
 JOIN cr_release_member m USING(release_id) WHERE m.permit_id=NEW.permit_id;
END;
CREATE TRIGGER cr_ack_invalidation AFTER INSERT ON ce_barrier_ack BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT x.release_id,'barrier_ack',NEW.barrier_id,NULL FROM cr_invalid_release x
 JOIN cr_release_member m USING(release_id) JOIN ce_barrier_coverage b USING(permit_id)
 WHERE b.barrier_id=NEW.barrier_id AND b.disposition='in_flight';
END;
CREATE TRIGGER cr_target_invalidation AFTER INSERT ON ce_target_result BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT x.release_id,'target_result',NEW.fence_id,NEW.exit_id FROM cr_invalid_release x
 JOIN cr_release_member m USING(release_id) JOIN ce_coverage b USING(permit_id)
 WHERE b.fence_id=NEW.fence_id AND b.exit_id=NEW.exit_id AND b.disposition='in_flight';
END;
CREATE TRIGGER cr_revoke_invalidation AFTER INSERT ON cr_validation_revocation BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT x.release_id,'validation_revocation',NEW.validation_id,NULL FROM cr_invalid_release x
 JOIN cr_release_validation p USING(release_id) WHERE p.validation_id=NEW.validation_id;
END;
CREATE TRIGGER cr_invalidation_source BEFORE INSERT ON cr_release_invalidation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_invalid_release WHERE release_id=NEW.release_id)
  THEN RAISE(ABORT,'release_not_invalid') END;
 SELECT CASE WHEN NOT (
   (NEW.source_kind='report' AND EXISTS(SELECT 1 FROM ce_report p JOIN cr_release_member m USING(permit_id)
     WHERE p.report_id=NEW.source_id AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='barrier_ack' AND EXISTS(SELECT 1 FROM ce_barrier_ack a
     JOIN ce_barrier_coverage p USING(barrier_id) JOIN cr_release_member m USING(permit_id)
     WHERE a.barrier_id=NEW.source_id AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='target_result' AND EXISTS(SELECT 1 FROM ce_target_result a
     JOIN ce_coverage p USING(fence_id,exit_id) JOIN cr_release_member m USING(permit_id)
     WHERE a.fence_id=NEW.source_id AND a.exit_id=NEW.source_exit_id
      AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='validation_revocation' AND EXISTS(
     SELECT 1 FROM cr_validation_revocation p JOIN cr_release_validation r USING(validation_id)
     WHERE p.validation_id=NEW.source_id AND r.release_id=NEW.release_id)))
  THEN RAISE(ABORT,'invalidation_source') END;
END;

CREATE TRIGGER cr_recovery_seal BEFORE INSERT ON cr_recovery_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_recovery r JOIN cr_valid_validation v USING(validation_id)
  WHERE r.recovery_id=NEW.recovery_id AND v.device_id=r.device_id AND v.purpose='recovery'
   AND v.command_id IS NULL AND v.subject_id=r.recovery_id AND v.subject_digest=r.recovery_digest)
  THEN RAISE(ABORT,'recovery_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_risk_hold h JOIN cr_recovery r USING(device_id)
  WHERE r.recovery_id=NEW.recovery_id) THEN RAISE(ABORT,'recovery_resource_busy') END;
 SELECT CASE WHEN EXISTS(SELECT x.release_id FROM cr_release_invalidation x JOIN cr_release y USING(release_id)
  JOIN ce_command c USING(command_id) JOIN cr_recovery r USING(device_id)
  WHERE r.recovery_id=NEW.recovery_id EXCEPT SELECT release_id FROM cr_recovery_member WHERE recovery_id=NEW.recovery_id)
 OR EXISTS(SELECT release_id FROM cr_recovery_member WHERE recovery_id=NEW.recovery_id
  EXCEPT SELECT x.release_id FROM cr_release_invalidation x JOIN cr_release y USING(release_id)
  JOIN ce_command c USING(command_id) JOIN cr_recovery r USING(device_id) WHERE r.recovery_id=NEW.recovery_id)
  THEN RAISE(ABORT,'recovery_protection_set') END;
END;
CREATE TRIGGER cr_recovery_member_frozen BEFORE INSERT ON cr_recovery_member
 WHEN EXISTS(SELECT 1 FROM cr_recovery_commit WHERE recovery_id=NEW.recovery_id)
 BEGIN SELECT RAISE(ABORT,'recovery_frozen'); END;

CREATE TRIGGER cr_validation_u BEFORE UPDATE ON cr_validation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_validation_d BEFORE DELETE ON cr_validation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_validation_revocation_u BEFORE UPDATE ON cr_validation_revocation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_validation_revocation_d BEFORE DELETE ON cr_validation_revocation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_claim_u BEFORE UPDATE ON cr_claim BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_claim_d BEFORE DELETE ON cr_claim BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_u BEFORE UPDATE ON cr_hold BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_d BEFORE DELETE ON cr_hold BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_commit_u BEFORE UPDATE ON cr_hold_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_commit_d BEFORE DELETE ON cr_hold_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_close_u BEFORE UPDATE ON cr_hold_close BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_close_d BEFORE DELETE ON cr_hold_close BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_settlement_validation_u BEFORE UPDATE ON cr_settlement_validation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_settlement_validation_d BEFORE DELETE ON cr_settlement_validation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_u BEFORE UPDATE ON cr_release BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_d BEFORE DELETE ON cr_release BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_attempt_u BEFORE UPDATE ON cr_release_attempt BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_attempt_d BEFORE DELETE ON cr_release_attempt BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_member_u BEFORE UPDATE ON cr_release_member BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_member_d BEFORE DELETE ON cr_release_member BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_commit_u BEFORE UPDATE ON cr_release_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_commit_d BEFORE DELETE ON cr_release_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_invalidation_u BEFORE UPDATE ON cr_release_invalidation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_invalidation_d BEFORE DELETE ON cr_release_invalidation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_u BEFORE UPDATE ON cr_recovery BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_d BEFORE DELETE ON cr_recovery BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_member_u BEFORE UPDATE ON cr_recovery_member BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_member_d BEFORE DELETE ON cr_recovery_member BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_commit_u BEFORE UPDATE ON cr_recovery_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_commit_d BEFORE DELETE ON cr_recovery_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;
