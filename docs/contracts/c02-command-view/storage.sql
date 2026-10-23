-- 在Controller77表之后加载；14表公开修订/取消候选，不是生产迁移。
-- 一个writer；foreign_keys与recursive_triggers必须在事务外开启。
CREATE TABLE cv_metadata (
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ca_command_initial(command_id),
 initial_revision TEXT NOT NULL CHECK(initial_revision='00000000000000000001'),
 metadata_digest TEXT NOT NULL CHECK(length(metadata_digest)=71 AND substr(metadata_digest,1,7)='sha256:'
  AND substr(metadata_digest,8) NOT GLOB '*[^0-9a-f]*'),
 metadata_body BLOB NOT NULL CHECK(length(metadata_body)>0),
 UNIQUE(command_id,metadata_digest),
 FOREIGN KEY(command_id,initial_revision) REFERENCES cv_record(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_evidence (
 evidence_id TEXT NOT NULL,
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'
  AND revision>'00000000000000000000'),
 command_id TEXT NOT NULL REFERENCES cv_metadata(command_id),
 first_state_revision TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('observation','decision','release','resolution','invalidation')),
 source_digest TEXT NOT NULL CHECK(length(source_digest)=71 AND substr(source_digest,1,7)='sha256:'
  AND substr(source_digest,8) NOT GLOB '*[^0-9a-f]*'),
 view_digest TEXT NOT NULL CHECK(length(view_digest)=71 AND substr(view_digest,1,7)='sha256:'
  AND substr(view_digest,8) NOT GLOB '*[^0-9a-f]*'),
 source_body BLOB NOT NULL CHECK(length(source_body)>0),
 view_body BLOB NOT NULL CHECK(length(view_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 decision_id TEXT REFERENCES cm_decision(evidence_id),
 release_id TEXT REFERENCES cr_release_commit(release_id),
 resolution_id TEXT REFERENCES cm_resolution(resolution_id),
 subject_id TEXT, subject_revision TEXT,
 protection_ref_body BLOB,
 PRIMARY KEY(evidence_id,revision),
 CHECK(substr(evidence_id,1,length(kind)+1)=kind||'.'),
 CHECK((kind='decision')=(decision_id IS NOT NULL)),
 CHECK((kind='release')=(release_id IS NOT NULL)),
 CHECK((kind='resolution')=(resolution_id IS NOT NULL)),
 CHECK(decision_id IS NULL OR decision_id=evidence_id),
 CHECK(release_id IS NULL OR release_id=evidence_id),
 CHECK(resolution_id IS NULL OR resolution_id=evidence_id),
 CHECK(kind='resolution' OR revision='00000000000000000001'),
 CHECK((kind='invalidation' AND subject_id IS NOT NULL AND subject_revision IS NOT NULL
   AND protection_ref_body IS NOT NULL AND length(protection_ref_body)>0)
  OR (kind!='invalidation' AND subject_id IS NULL AND subject_revision IS NULL AND protection_ref_body IS NULL)),
 FOREIGN KEY(subject_id,subject_revision) REFERENCES cv_evidence(evidence_id,revision),
 FOREIGN KEY(command_id,first_state_revision) REFERENCES cm_commit(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_snapshot (
 snapshot_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL,
 state_revision TEXT NOT NULL,
 state_digest TEXT NOT NULL,
 total TEXT NOT NULL CHECK(length(total)=20 AND total NOT GLOB '*[^0-9]*'),
 snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=71 AND substr(snapshot_digest,1,7)='sha256:'
  AND substr(snapshot_digest,8) NOT GLOB '*[^0-9a-f]*'),
 manifest_body BLOB NOT NULL CHECK(length(manifest_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 UNIQUE(command_id,state_revision), UNIQUE(snapshot_id,command_id,state_revision),
 FOREIGN KEY(command_id,state_revision) REFERENCES cv_record(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_snapshot_member (
 snapshot_id TEXT NOT NULL REFERENCES cv_snapshot(snapshot_id),
 ordinal TEXT NOT NULL CHECK(length(ordinal)=20 AND ordinal NOT GLOB '*[^0-9]*'),
 evidence_id TEXT NOT NULL,
 evidence_revision TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,ordinal), UNIQUE(snapshot_id,evidence_id,evidence_revision),
 FOREIGN KEY(evidence_id,evidence_revision) REFERENCES cv_evidence(evidence_id,revision)
) STRICT;
CREATE TABLE cv_record (
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 state_digest TEXT NOT NULL,
 metadata_digest TEXT NOT NULL,
 snapshot_id TEXT NOT NULL,
 cancellation_id TEXT, cancellation_revision TEXT,
 record_digest TEXT NOT NULL CHECK(length(record_digest)=71 AND substr(record_digest,1,7)='sha256:'
  AND substr(record_digest,8) NOT GLOB '*[^0-9a-f]*'),
 record_body BLOB NOT NULL CHECK(length(record_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 PRIMARY KEY(command_id,revision),
 CHECK((cancellation_id IS NULL)=(cancellation_revision IS NULL)),
 FOREIGN KEY(command_id,revision) REFERENCES cm_commit(command_id,revision) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(command_id,metadata_digest) REFERENCES cv_metadata(command_id,metadata_digest),
 FOREIGN KEY(snapshot_id,command_id,revision) REFERENCES cv_snapshot(snapshot_id,command_id,state_revision),
 FOREIGN KEY(cancellation_id,cancellation_revision,command_id)
  REFERENCES cv_cancel_revision(cancellation_id,revision,command_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_cancel_key (
 key_id TEXT PRIMARY KEY NOT NULL,
 namespace_id TEXT NOT NULL REFERENCES ca_namespace(namespace_id),
 operation_id TEXT NOT NULL CHECK(operation_id='cancelCommand'),
 idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)>0),
 request_digest TEXT NOT NULL CHECK(length(request_digest)=71 AND substr(request_digest,1,7)='sha256:'
  AND substr(request_digest,8) NOT GLOB '*[^0-9a-f]*'),
 content_body BLOB NOT NULL CHECK(length(content_body)>0),
 authorization_body BLOB NOT NULL CHECK(length(authorization_body)>0),
 UNIQUE(namespace_id,operation_id,idempotency_key),
 FOREIGN KEY(key_id) REFERENCES cv_cancel(key_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_cancel (
 cancellation_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL UNIQUE REFERENCES cm_policy(command_id),
 key_id TEXT NOT NULL UNIQUE REFERENCES cv_cancel_key(key_id),
 mode TEXT NOT NULL CHECK(mode IN ('before_dispatch_only','cooperative')),
 accepted_revision TEXT NOT NULL,
 accepted_state_digest TEXT NOT NULL,
 initial_revision TEXT NOT NULL CHECK(initial_revision='00000000000000000001'),
 cut_revision TEXT NOT NULL CHECK(length(cut_revision)=20 AND cut_revision NOT GLOB '*[^0-9]*'),
 cut_digest TEXT NOT NULL CHECK(length(cut_digest)=71 AND substr(cut_digest,1,7)='sha256:'
  AND substr(cut_digest,8) NOT GLOB '*[^0-9a-f]*'),
 cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 policy_body BLOB NOT NULL CHECK(length(policy_body)>0),
 UNIQUE(cancellation_id,command_id),
 FOREIGN KEY(command_id,accepted_revision) REFERENCES cm_commit(command_id,revision),
 FOREIGN KEY(cancellation_id,initial_revision,command_id)
  REFERENCES cv_cancel_revision(cancellation_id,revision,command_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancellation_id) REFERENCES cv_cancel_receipt(cancellation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancellation_id,command_id) REFERENCES cv_cancel_deny(cancellation_id,command_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancellation_id) REFERENCES cv_cancel_commit(cancellation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_cancel_revision (
 cancellation_id TEXT NOT NULL,
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'
  AND revision>'00000000000000000000'),
 command_id TEXT NOT NULL,
 state_revision TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('requested','confirmed','unsupported','failed','indeterminate','too_late')),
 future_writes TEXT NOT NULL CHECK(future_writes IN ('pending','closed','indeterminate')),
 closure_validation_body BLOB,
 result_validation_body BLOB,
 operation_digest TEXT NOT NULL CHECK(length(operation_digest)=71 AND substr(operation_digest,1,7)='sha256:'
  AND substr(operation_digest,8) NOT GLOB '*[^0-9a-f]*'),
 operation_body BLOB NOT NULL CHECK(length(operation_body)>0),
 PRIMARY KEY(cancellation_id,revision), UNIQUE(cancellation_id,revision,command_id), UNIQUE(command_id,state_revision),
 CHECK((future_writes='closed' AND closure_validation_body IS NOT NULL AND length(closure_validation_body)>0)
  OR (future_writes!='closed' AND closure_validation_body IS NULL)),
 CHECK(state!='confirmed' OR future_writes='closed'),
 CHECK(state NOT IN ('confirmed','unsupported','failed','too_late')
  OR (result_validation_body IS NOT NULL AND length(result_validation_body)>0)),
 FOREIGN KEY(cancellation_id,command_id) REFERENCES cv_cancel(cancellation_id,command_id),
 FOREIGN KEY(command_id,state_revision) REFERENCES cm_commit(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_cancel_receipt (
 cancellation_id TEXT PRIMARY KEY NOT NULL REFERENCES cv_cancel(cancellation_id),
 initial_revision TEXT NOT NULL CHECK(initial_revision='00000000000000000001'),
 initial_operation_digest TEXT NOT NULL,
 receipt_digest TEXT NOT NULL CHECK(length(receipt_digest)=71 AND substr(receipt_digest,1,7)='sha256:'
  AND substr(receipt_digest,8) NOT GLOB '*[^0-9a-f]*'),
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 FOREIGN KEY(cancellation_id,initial_revision) REFERENCES cv_cancel_revision(cancellation_id,revision)
) STRICT;
CREATE TABLE cv_cancel_deny (
 command_id TEXT PRIMARY KEY NOT NULL,
 cancellation_id TEXT NOT NULL UNIQUE,
 UNIQUE(cancellation_id,command_id),
 FOREIGN KEY(cancellation_id,command_id) REFERENCES cv_cancel(cancellation_id,command_id)
) STRICT;
CREATE TABLE cv_cancel_attempt (
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel(cancellation_id),
 attempt_id TEXT NOT NULL REFERENCES ce_attempt(attempt_id),
 PRIMARY KEY(cancellation_id,attempt_id)
) STRICT;
CREATE TABLE cv_cancel_target (
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel(cancellation_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 PRIMARY KEY(cancellation_id,exit_id)
) STRICT;
CREATE TABLE cv_cancel_permit (
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel(cancellation_id),
 permit_id TEXT NOT NULL REFERENCES ce_permit(permit_id),
 PRIMARY KEY(cancellation_id,permit_id)
) STRICT;
CREATE TABLE cv_cancel_commit (
 cancellation_id TEXT PRIMARY KEY NOT NULL REFERENCES cv_cancel(cancellation_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;

CREATE VIEW cv_history AS
 SELECT p.* FROM cv_record p JOIN cm_commit c USING(command_id,revision);
CREATE VIEW cv_current AS
 SELECT p.* FROM cv_history p JOIN cm_current s USING(command_id,revision);
CREATE VIEW cv_cancel_current AS
 SELECT c.* FROM cv_cancel_revision c JOIN cm_commit m ON m.command_id=c.command_id AND m.revision=c.state_revision
 JOIN cv_cancel_commit k USING(cancellation_id)
 WHERE NOT EXISTS(SELECT 1 FROM cv_cancel_revision n JOIN cm_commit nm ON nm.command_id=n.command_id
  AND nm.revision=n.state_revision WHERE n.cancellation_id=c.cancellation_id AND n.revision>c.revision);

CREATE TRIGGER cv_evidence_guard BEFORE INSERT ON cv_evidence BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.first_state_revision)
  THEN RAISE(ABORT,'evidence_revision_frozen') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_evidence WHERE evidence_id=NEW.evidence_id
  AND (command_id!=NEW.command_id OR kind!=NEW.kind)) THEN RAISE(ABORT,'evidence_identity_owner') END;
 SELECT CASE WHEN NEW.kind='decision' AND NOT EXISTS(SELECT 1 FROM cm_decision
  WHERE evidence_id=NEW.decision_id AND command_id=NEW.command_id AND evidence_digest=NEW.source_digest)
  THEN RAISE(ABORT,'decision_source') END;
 SELECT CASE WHEN NEW.kind='release' AND NOT EXISTS(SELECT 1 FROM cr_release
  WHERE release_id=NEW.release_id AND command_id=NEW.command_id AND release_digest=NEW.source_digest)
  THEN RAISE(ABORT,'release_source') END;
 SELECT CASE WHEN NEW.kind='resolution' AND NOT EXISTS(SELECT 1 FROM cm_resolution
  WHERE resolution_id=NEW.resolution_id AND command_id=NEW.command_id AND resolution_digest=NEW.source_digest
   AND revision=NEW.revision)
  THEN RAISE(ABORT,'resolution_source') END;
 SELECT CASE WHEN NEW.kind='invalidation' AND NOT EXISTS(SELECT 1 FROM cv_evidence
  WHERE evidence_id=NEW.subject_id AND revision=NEW.subject_revision AND command_id=NEW.command_id)
  THEN RAISE(ABORT,'invalidation_owner') END;
END;
CREATE TRIGGER cv_record_guard BEFORE INSERT ON cv_record BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.revision)
  THEN RAISE(ABORT,'public_revision_frozen') END;
END;
CREATE TRIGGER cv_member_guard BEFORE INSERT ON cv_snapshot_member BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_snapshot s JOIN cm_commit c
  ON c.command_id=s.command_id AND c.revision=s.state_revision WHERE s.snapshot_id=NEW.snapshot_id)
  THEN RAISE(ABORT,'snapshot_frozen') END;
END;
CREATE TRIGGER cv_publish AFTER INSERT ON cm_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_record p JOIN cv_snapshot s USING(snapshot_id)
  JOIN cm_revision r ON r.command_id=p.command_id AND r.revision=p.revision
  WHERE p.command_id=NEW.command_id AND p.revision=NEW.revision
   AND p.state_digest=r.state_digest AND s.state_digest=r.state_digest)
  THEN RAISE(ABORT,'complete_public_revision_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_snapshot s WHERE s.command_id=NEW.command_id
  AND s.state_revision=NEW.revision AND s.total!=printf('%020d',
   (SELECT count(*) FROM cv_snapshot_member m WHERE m.snapshot_id=s.snapshot_id)))
  THEN RAISE(ABORT,'snapshot_count') END;
 -- 完整历史成员双向差集；不能只核count而遗漏或替换证据。
 SELECT CASE WHEN EXISTS(
  SELECT evidence_id,revision FROM cv_evidence WHERE command_id=NEW.command_id AND first_state_revision<=NEW.revision
  EXCEPT SELECT m.evidence_id,m.evidence_revision FROM cv_snapshot_member m JOIN cv_snapshot s USING(snapshot_id)
   WHERE s.command_id=NEW.command_id AND s.state_revision=NEW.revision)
 OR EXISTS(
  SELECT m.evidence_id,m.evidence_revision FROM cv_snapshot_member m JOIN cv_snapshot s USING(snapshot_id)
   WHERE s.command_id=NEW.command_id AND s.state_revision=NEW.revision
  EXCEPT SELECT evidence_id,revision FROM cv_evidence WHERE command_id=NEW.command_id AND first_state_revision<=NEW.revision)
  THEN RAISE(ABORT,'snapshot_members') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM
  (SELECT evidence_id,revision,printf('%020d',row_number() OVER(ORDER BY evidence_id,revision,kind)-1) ordinal
   FROM cv_evidence WHERE command_id=NEW.command_id AND first_state_revision<=NEW.revision) e
  JOIN cv_snapshot s ON s.command_id=NEW.command_id AND s.state_revision=NEW.revision
  JOIN cv_snapshot_member m ON m.snapshot_id=s.snapshot_id AND m.evidence_id=e.evidence_id
   AND m.evidence_revision=e.revision WHERE m.ordinal!=e.ordinal)
  THEN RAISE(ABORT,'snapshot_order') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_record p WHERE p.command_id=NEW.command_id AND p.revision=NEW.revision
  AND (p.cancellation_id IS NOT (SELECT c.cancellation_id FROM cv_cancel_revision c
     WHERE c.command_id=NEW.command_id AND c.state_revision<=NEW.revision ORDER BY c.revision DESC LIMIT 1)
   OR p.cancellation_revision IS NOT (SELECT c.revision FROM cv_cancel_revision c
     WHERE c.command_id=NEW.command_id AND c.state_revision<=NEW.revision ORDER BY c.revision DESC LIMIT 1)))
  THEN RAISE(ABORT,'cancel_projection') END;
END;
CREATE TRIGGER cv_cancel_admit BEFORE INSERT ON cv_cancel BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_latest WHERE command_id=NEW.command_id
  AND revision=NEW.accepted_revision AND state_digest=NEW.accepted_state_digest)
  THEN RAISE(ABORT,'cancel_cas') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_cancel_key k JOIN ca_namespace_closure c USING(namespace_id)
  WHERE k.key_id=NEW.key_id) THEN RAISE(ABORT,'cancel_namespace_closed') END;
 SELECT CASE WHEN NEW.cut_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ce_permit)
  THEN RAISE(ABORT,'cancel_cut_highwater') END;
END;
CREATE TRIGGER cv_cancel_progress BEFORE INSERT ON cv_cancel_revision BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.state_revision)
  THEN RAISE(ABORT,'cancel_state_frozen') END;
 SELECT CASE WHEN NEW.revision!=(SELECT printf('%010d%010d',
  CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
  (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
  FROM (SELECT coalesce(max(revision),'00000000000000000000') v FROM cv_cancel_revision
    WHERE cancellation_id=NEW.cancellation_id)) THEN RAISE(ABORT,'cancel_successor') END;
 SELECT CASE WHEN NEW.revision!='00000000000000000001' AND NOT EXISTS(
  SELECT 1 FROM cv_cancel_current old WHERE old.cancellation_id=NEW.cancellation_id
   AND old.revision=(SELECT max(revision) FROM cv_cancel_revision WHERE cancellation_id=NEW.cancellation_id))
  THEN RAISE(ABORT,'cancel_previous_uncommitted') END;
 SELECT CASE WHEN NEW.revision='00000000000000000001' AND (NEW.state!='requested' OR NEW.future_writes!='pending'
  OR NEW.state_revision!=(SELECT printf('%010d%010d',
    CAST(substr(accepted_revision,1,10) AS INTEGER)+(substr(accepted_revision,11,10)='9999999999'),
    (CAST(substr(accepted_revision,11,10) AS INTEGER)+1)%10000000000)
   FROM cv_cancel WHERE cancellation_id=NEW.cancellation_id))
  THEN RAISE(ABORT,'cancel_initial') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_cancel_current old WHERE old.cancellation_id=NEW.cancellation_id
  AND (NEW.state_revision<=old.state_revision
   OR (old.state IN ('confirmed','unsupported','failed','too_late') AND NEW.state!=old.state)
   OR (old.state='indeterminate' AND NEW.state='requested')
   OR (old.future_writes='closed' AND NEW.future_writes!='closed')))
  THEN RAISE(ABORT,'cancel_regression') END;
END;
CREATE TRIGGER cv_cancel_seal BEFORE INSERT ON cv_cancel_commit BEGIN
 SELECT CASE WHEN (SELECT cut_revision FROM cv_cancel WHERE cancellation_id=NEW.cancellation_id)
  !=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ce_permit)
  THEN RAISE(ABORT,'cancel_cut_changed') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel c JOIN cv_cancel_revision r
  ON r.cancellation_id=c.cancellation_id AND r.revision=c.initial_revision
  JOIN cv_cancel_receipt p ON p.cancellation_id=c.cancellation_id
  JOIN cm_commit m ON m.command_id=c.command_id AND m.revision=r.state_revision
  WHERE c.cancellation_id=NEW.cancellation_id AND p.initial_operation_digest=r.operation_digest)
  THEN RAISE(ABORT,'cancel_receipt_pair') END;
 SELECT CASE WHEN EXISTS(
  SELECT a.attempt_id FROM ce_attempt a JOIN cv_cancel c USING(command_id) WHERE c.cancellation_id=NEW.cancellation_id
  EXCEPT SELECT attempt_id FROM cv_cancel_attempt WHERE cancellation_id=NEW.cancellation_id)
 OR EXISTS(SELECT attempt_id FROM cv_cancel_attempt WHERE cancellation_id=NEW.cancellation_id
  EXCEPT SELECT a.attempt_id FROM ce_attempt a JOIN cv_cancel c USING(command_id) WHERE c.cancellation_id=NEW.cancellation_id)
  THEN RAISE(ABORT,'cancel_attempt_set') END;
 SELECT CASE WHEN EXISTS(
  SELECT e.exit_id FROM ce_exit e JOIN ce_command cmd USING(device_id) JOIN cv_cancel c USING(command_id)
   WHERE c.cancellation_id=NEW.cancellation_id
  EXCEPT SELECT exit_id FROM cv_cancel_target WHERE cancellation_id=NEW.cancellation_id)
 OR EXISTS(SELECT exit_id FROM cv_cancel_target WHERE cancellation_id=NEW.cancellation_id
  EXCEPT SELECT e.exit_id FROM ce_exit e JOIN ce_command cmd USING(device_id) JOIN cv_cancel c USING(command_id)
   WHERE c.cancellation_id=NEW.cancellation_id) THEN RAISE(ABORT,'cancel_exit_set') END;
 SELECT CASE WHEN EXISTS(
  SELECT p.permit_id FROM ce_permit p JOIN ce_attempt a USING(attempt_id) JOIN cv_cancel c USING(command_id)
   WHERE c.cancellation_id=NEW.cancellation_id
  EXCEPT SELECT permit_id FROM cv_cancel_permit WHERE cancellation_id=NEW.cancellation_id)
 OR EXISTS(SELECT permit_id FROM cv_cancel_permit WHERE cancellation_id=NEW.cancellation_id
  EXCEPT SELECT p.permit_id FROM ce_permit p JOIN ce_attempt a USING(attempt_id) JOIN cv_cancel c USING(command_id)
   WHERE c.cancellation_id=NEW.cancellation_id) THEN RAISE(ABORT,'cancel_permit_set') END;
END;
CREATE TRIGGER cv_cancel_attempt_frozen BEFORE INSERT ON cv_cancel_attempt
 WHEN EXISTS(SELECT 1 FROM cv_cancel_commit WHERE cancellation_id=NEW.cancellation_id)
 BEGIN SELECT RAISE(ABORT,'cancel_cut_frozen'); END;
CREATE TRIGGER cv_cancel_target_frozen BEFORE INSERT ON cv_cancel_target
 WHEN EXISTS(SELECT 1 FROM cv_cancel_commit WHERE cancellation_id=NEW.cancellation_id)
 BEGIN SELECT RAISE(ABORT,'cancel_cut_frozen'); END;
CREATE TRIGGER cv_cancel_permit_frozen BEFORE INSERT ON cv_cancel_permit
 WHEN EXISTS(SELECT 1 FROM cv_cancel_commit WHERE cancellation_id=NEW.cancellation_id)
 BEGIN SELECT RAISE(ABORT,'cancel_cut_frozen'); END;
CREATE TRIGGER cv_no_attempt BEFORE INSERT ON cm_attempt
 WHEN EXISTS(SELECT 1 FROM cv_cancel_deny WHERE command_id=NEW.command_id)
 BEGIN SELECT RAISE(ABORT,'command_cancelled'); END;
CREATE TRIGGER cv_no_hold BEFORE INSERT ON cr_hold
 WHEN EXISTS(SELECT 1 FROM cv_cancel_deny WHERE command_id=NEW.command_id)
 BEGIN SELECT RAISE(ABORT,'command_cancelled'); END;
CREATE TRIGGER cv_no_permit BEFORE INSERT ON ce_permit
 WHEN EXISTS(SELECT 1 FROM cv_cancel_deny d JOIN ce_attempt a USING(command_id) WHERE a.attempt_id=NEW.attempt_id)
 BEGIN SELECT RAISE(ABORT,'command_cancelled'); END;

CREATE TRIGGER cv_metadata_u BEFORE UPDATE ON cv_metadata BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_metadata_d BEFORE DELETE ON cv_metadata BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_evidence_u BEFORE UPDATE ON cv_evidence BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_evidence_d BEFORE DELETE ON cv_evidence BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_snapshot_u BEFORE UPDATE ON cv_snapshot BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_snapshot_d BEFORE DELETE ON cv_snapshot BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_snapshot_member_u BEFORE UPDATE ON cv_snapshot_member BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_snapshot_member_d BEFORE DELETE ON cv_snapshot_member BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_record_u BEFORE UPDATE ON cv_record BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_record_d BEFORE DELETE ON cv_record BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_key_u BEFORE UPDATE ON cv_cancel_key BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_key_d BEFORE DELETE ON cv_cancel_key BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_u BEFORE UPDATE ON cv_cancel BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_d BEFORE DELETE ON cv_cancel BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_revision_u BEFORE UPDATE ON cv_cancel_revision BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_revision_d BEFORE DELETE ON cv_cancel_revision BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_receipt_u BEFORE UPDATE ON cv_cancel_receipt BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_receipt_d BEFORE DELETE ON cv_cancel_receipt BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_deny_u BEFORE UPDATE ON cv_cancel_deny BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_deny_d BEFORE DELETE ON cv_cancel_deny BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_attempt_u BEFORE UPDATE ON cv_cancel_attempt BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_attempt_d BEFORE DELETE ON cv_cancel_attempt BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_target_u BEFORE UPDATE ON cv_cancel_target BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_target_d BEFORE DELETE ON cv_cancel_target BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_permit_u BEFORE UPDATE ON cv_cancel_permit BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_permit_d BEFORE DELETE ON cv_cancel_permit BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_commit_u BEFORE UPDATE ON cv_cancel_commit BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_commit_d BEFORE DELETE ON cv_cancel_commit BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
