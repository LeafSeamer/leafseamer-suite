-- 在既有recovery.sql和dispatch.sql之后加载的设计候选，不是生产迁移。
-- U20精确+1、正文Schema/JCS、身份与完整匹配索引来源由writer另验。
CREATE TABLE ingress_storage_profile (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 version TEXT NOT NULL CHECK(version='ingress-storage/0.1.0-draft.1')
) STRICT;
CREATE TABLE ingest_epoch (
 epoch TEXT PRIMARY KEY NOT NULL, state TEXT NOT NULL CHECK(state IN ('open','closed')),
 last_sequence TEXT NOT NULL CHECK(length(last_sequence) BETWEEN 1 AND 20 AND last_sequence NOT GLOB '*[^0-9]*' AND (last_sequence='0' OR substr(last_sequence,1,1)!='0') AND instr(last_sequence,char(0))=0)
) STRICT;
CREATE UNIQUE INDEX one_open_ingest_epoch ON ingest_epoch(state) WHERE state='open';
CREATE TABLE ingress_source (
 source_id TEXT PRIMARY KEY NOT NULL, source_key BLOB NOT NULL UNIQUE,
 revision TEXT NOT NULL, contiguous_sequence TEXT NOT NULL, reject_floor TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('synchronized','desynchronized','quarantined','closed','baseline_required')),
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 CHECK(length(contiguous_sequence) BETWEEN 1 AND 20 AND contiguous_sequence NOT GLOB '*[^0-9]*' AND (contiguous_sequence='0' OR substr(contiguous_sequence,1,1)!='0') AND instr(contiguous_sequence,char(0))=0),
 CHECK(length(reject_floor) BETWEEN 1 AND 20 AND reject_floor NOT GLOB '*[^0-9]*' AND (reject_floor='0' OR substr(reject_floor,1,1)!='0') AND instr(reject_floor,char(0))=0)
) STRICT;
CREATE TABLE ingress_registry (
 source_id TEXT PRIMARY KEY NOT NULL REFERENCES ingress_source(source_id), revision TEXT NOT NULL,
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0)
) STRICT;
CREATE TABLE ingress_listener (
 source_id TEXT NOT NULL REFERENCES ingress_registry(source_id), run_id TEXT NOT NULL REFERENCES run(run_id),
 artifact_digest TEXT NOT NULL, binding_body BLOB NOT NULL, PRIMARY KEY(source_id,run_id)
) STRICT;
CREATE TABLE ingress_inbox (
 inbox_id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES ingress_source(source_id),
 event_id TEXT NOT NULL, source_sequence TEXT NOT NULL, origin_digest TEXT NOT NULL, content_body BLOB NOT NULL,
 first_observation_body BLOB NOT NULL, observed_only INTEGER NOT NULL CHECK(observed_only IN (0,1)),
 commit_id TEXT UNIQUE,
 CHECK(length(source_sequence) BETWEEN 1 AND 20 AND source_sequence NOT GLOB '*[^0-9]*' AND substr(source_sequence,1,1)!='0' AND instr(source_sequence,char(0))=0),
 UNIQUE(source_id,event_id), UNIQUE(source_id,source_sequence), UNIQUE(inbox_id,commit_id),
 FOREIGN KEY(commit_id,inbox_id) REFERENCES ingress_commit(commit_id,inbox_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_commit (
 commit_id TEXT PRIMARY KEY NOT NULL, inbox_id TEXT NOT NULL UNIQUE,
 epoch TEXT NOT NULL REFERENCES ingest_epoch(epoch), receive_sequence TEXT NOT NULL,
 registry_revision TEXT NOT NULL, source_revision_before TEXT NOT NULL, source_revision_after TEXT NOT NULL,
 expected_targets INTEGER NOT NULL CHECK(expected_targets BETWEEN 0 AND 256),
 decision_set_digest TEXT NOT NULL, body BLOB NOT NULL, notification_id TEXT NOT NULL UNIQUE,
 sealed INTEGER NOT NULL CHECK(sealed IN (0,1)), required_seal INTEGER NOT NULL DEFAULT 1 CHECK(required_seal=1),
 CHECK(length(receive_sequence) BETWEEN 1 AND 20 AND receive_sequence NOT GLOB '*[^0-9]*' AND substr(receive_sequence,1,1)!='0' AND instr(receive_sequence,char(0))=0),
 CHECK(length(registry_revision) BETWEEN 1 AND 20 AND registry_revision NOT GLOB '*[^0-9]*' AND (registry_revision='0' OR substr(registry_revision,1,1)!='0') AND instr(registry_revision,char(0))=0),
 CHECK(length(source_revision_before) BETWEEN 1 AND 20 AND source_revision_before NOT GLOB '*[^0-9]*' AND (source_revision_before='0' OR substr(source_revision_before,1,1)!='0') AND instr(source_revision_before,char(0))=0),
 CHECK(length(source_revision_after) BETWEEN 1 AND 20 AND source_revision_after NOT GLOB '*[^0-9]*' AND (source_revision_after='0' OR substr(source_revision_after,1,1)!='0') AND instr(source_revision_after,char(0))=0),
 UNIQUE(epoch,receive_sequence), UNIQUE(commit_id,inbox_id), UNIQUE(commit_id,sealed), UNIQUE(commit_id,notification_id),
 FOREIGN KEY(inbox_id,commit_id) REFERENCES ingress_inbox(inbox_id,commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(commit_id,required_seal) REFERENCES ingress_commit(commit_id,sealed) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(notification_id,commit_id) REFERENCES ingress_notification(notification_id,commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(commit_id) REFERENCES ingress_charge(commit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_target (
 commit_id TEXT NOT NULL REFERENCES ingress_commit(commit_id), run_id TEXT NOT NULL REFERENCES run(run_id),
 artifact_digest TEXT NOT NULL, binding_body BLOB NOT NULL, decision_id TEXT NOT NULL UNIQUE,
 PRIMARY KEY(commit_id,run_id), UNIQUE(commit_id,run_id,decision_id),
 FOREIGN KEY(decision_id,commit_id,run_id) REFERENCES ingress_decision(decision_id,commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_snapshot (
 snapshot_id TEXT PRIMARY KEY NOT NULL, commit_id TEXT NOT NULL, run_id TEXT NOT NULL,
 digest TEXT NOT NULL, body BLOB NOT NULL, UNIQUE(snapshot_id,commit_id,run_id), UNIQUE(commit_id,run_id),
 FOREIGN KEY(commit_id,run_id) REFERENCES ingress_target(commit_id,run_id),
 FOREIGN KEY(snapshot_id,commit_id,run_id) REFERENCES ingress_decision(snapshot_id,commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_decision (
 decision_id TEXT PRIMARY KEY NOT NULL, commit_id TEXT NOT NULL, run_id TEXT NOT NULL, inbox_id TEXT NOT NULL,
 result TEXT NOT NULL CHECK(result IN ('accepted','no_match','suppressed_busy','suppressed_inactive','suppressed_obsolete','evaluation_unknown','ambiguous','protected')),
 snapshot_id TEXT, execution_id TEXT UNIQUE, digest TEXT NOT NULL, body BLOB NOT NULL,
 run_before TEXT NOT NULL, run_after TEXT NOT NULL, progress_before TEXT NOT NULL, progress_after TEXT NOT NULL,
 CHECK(length(run_before) BETWEEN 1 AND 20 AND run_before NOT GLOB '*[^0-9]*' AND (run_before='0' OR substr(run_before,1,1)!='0') AND instr(run_before,char(0))=0),
 CHECK(length(run_after) BETWEEN 1 AND 20 AND run_after NOT GLOB '*[^0-9]*' AND (run_after='0' OR substr(run_after,1,1)!='0') AND instr(run_after,char(0))=0),
 CHECK(length(progress_before) BETWEEN 1 AND 20 AND progress_before NOT GLOB '*[^0-9]*' AND (progress_before='0' OR substr(progress_before,1,1)!='0') AND instr(progress_before,char(0))=0),
 CHECK(length(progress_after) BETWEEN 1 AND 20 AND progress_after NOT GLOB '*[^0-9]*' AND (progress_after='0' OR substr(progress_after,1,1)!='0') AND instr(progress_after,char(0))=0),
 UNIQUE(run_id,inbox_id), UNIQUE(decision_id,commit_id,run_id), UNIQUE(commit_id,run_id), UNIQUE(decision_id,run_id,execution_id),
 UNIQUE(snapshot_id,commit_id,run_id),
 CHECK((result='accepted')=(execution_id IS NOT NULL)),
 CHECK(result NOT IN ('accepted','no_match','evaluation_unknown','ambiguous') OR snapshot_id IS NOT NULL),
 FOREIGN KEY(commit_id,inbox_id) REFERENCES ingress_commit(commit_id,inbox_id),
 FOREIGN KEY(commit_id,run_id,decision_id) REFERENCES ingress_target(commit_id,run_id,decision_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(snapshot_id,commit_id,run_id) REFERENCES ingress_snapshot(snapshot_id,commit_id,run_id),
 FOREIGN KEY(execution_id,run_id,decision_id) REFERENCES ingress_execution(execution_id,run_id,decision_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(commit_id,run_id) REFERENCES ingress_run_audit(commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_execution (
 execution_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL, decision_id TEXT NOT NULL UNIQUE,
 UNIQUE(execution_id,run_id,decision_id),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(decision_id,run_id,execution_id) REFERENCES ingress_decision(decision_id,run_id,execution_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE run_ingest_progress (
 run_id TEXT PRIMARY KEY NOT NULL REFERENCES run(run_id), revision TEXT NOT NULL,
 epoch TEXT NOT NULL REFERENCES ingest_epoch(epoch), last_sequence TEXT NOT NULL, baseline_body BLOB NOT NULL, last_commit_id TEXT,
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 CHECK(length(last_sequence) BETWEEN 1 AND 20 AND last_sequence NOT GLOB '*[^0-9]*' AND (last_sequence='0' OR substr(last_sequence,1,1)!='0') AND instr(last_sequence,char(0))=0),
 FOREIGN KEY(last_commit_id,run_id) REFERENCES ingress_decision(commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_notification (
 notification_id TEXT PRIMARY KEY NOT NULL, commit_id TEXT NOT NULL UNIQUE, payload_body BLOB NOT NULL,
 UNIQUE(notification_id,commit_id),
 FOREIGN KEY(commit_id,notification_id) REFERENCES ingress_commit(commit_id,notification_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_run_audit (
 commit_id TEXT NOT NULL, run_id TEXT NOT NULL, phase TEXT NOT NULL CHECK(phase='INGRESS_RUN'),
 audit_body BLOB NOT NULL, event_body BLOB NOT NULL, PRIMARY KEY(commit_id,run_id),
 FOREIGN KEY(commit_id,run_id) REFERENCES ingress_decision(commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_charge (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES ingress_commit(commit_id),
 profile_body BLOB NOT NULL, charge_body BLOB NOT NULL
) STRICT;

CREATE TRIGGER epoch_update BEFORE UPDATE ON ingest_epoch
WHEN NEW.epoch IS NOT OLD.epoch OR OLD.state='closed' OR
 (length(NEW.last_sequence),NEW.last_sequence COLLATE BINARY)<(length(OLD.last_sequence),OLD.last_sequence COLLATE BINARY)
BEGIN SELECT RAISE(ABORT,'epoch_monotonic'); END;
CREATE TRIGGER epoch_delete BEFORE DELETE ON ingest_epoch BEGIN SELECT RAISE(ABORT,'retain_epoch'); END;
CREATE TRIGGER source_update BEFORE UPDATE ON ingress_source
WHEN NEW.source_id IS NOT OLD.source_id OR NEW.source_key IS NOT OLD.source_key OR OLD.state='closed' OR
 (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY) OR
 (length(NEW.contiguous_sequence),NEW.contiguous_sequence COLLATE BINARY)<(length(OLD.contiguous_sequence),OLD.contiguous_sequence COLLATE BINARY) OR
 (length(NEW.reject_floor),NEW.reject_floor COLLATE BINARY)<(length(OLD.reject_floor),OLD.reject_floor COLLATE BINARY)
BEGIN SELECT RAISE(ABORT,'source_monotonic'); END;
CREATE TRIGGER source_delete BEFORE DELETE ON ingress_source BEGIN SELECT RAISE(ABORT,'retain_source'); END;
CREATE TRIGGER inbox_update BEFORE UPDATE ON ingress_inbox
WHEN NEW.inbox_id IS NOT OLD.inbox_id OR NEW.source_id IS NOT OLD.source_id OR NEW.event_id IS NOT OLD.event_id OR
 NEW.source_sequence IS NOT OLD.source_sequence OR NEW.origin_digest IS NOT OLD.origin_digest OR
 NEW.content_body IS NOT OLD.content_body OR NEW.first_observation_body IS NOT OLD.first_observation_body OR
 NEW.observed_only<OLD.observed_only OR OLD.commit_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'inbox_immutable'); END;
CREATE TRIGGER inbox_delete BEFORE DELETE ON ingress_inbox BEGIN SELECT RAISE(ABORT,'retain_inbox'); END;
CREATE TRIGGER ingress_commit_insert BEFORE INSERT ON ingress_commit
WHEN NEW.sealed!=0 OR NOT EXISTS(SELECT 1 FROM ingest_epoch WHERE epoch=NEW.epoch AND state='open'
 AND (length(last_sequence),last_sequence COLLATE BINARY)<(length(NEW.receive_sequence),NEW.receive_sequence COLLATE BINARY))
 OR NOT EXISTS(SELECT 1 FROM ingress_inbox i JOIN ingress_source s USING(source_id) JOIN ingress_registry r USING(source_id)
 WHERE i.inbox_id=NEW.inbox_id AND s.revision=NEW.source_revision_before AND r.revision=NEW.registry_revision)
BEGIN SELECT RAISE(ABORT,'ingress_initial'); END;
CREATE TRIGGER ingress_commit_seal BEFORE UPDATE ON ingress_commit
BEGIN
 SELECT CASE WHEN OLD.sealed!=0 OR NEW.sealed!=1 OR NEW.commit_id IS NOT OLD.commit_id OR NEW.inbox_id IS NOT OLD.inbox_id OR
 NEW.epoch IS NOT OLD.epoch OR NEW.receive_sequence IS NOT OLD.receive_sequence OR NEW.registry_revision IS NOT OLD.registry_revision OR
 NEW.source_revision_before IS NOT OLD.source_revision_before OR NEW.source_revision_after IS NOT OLD.source_revision_after OR
 NEW.expected_targets IS NOT OLD.expected_targets OR NEW.decision_set_digest IS NOT OLD.decision_set_digest OR
 NEW.body IS NOT OLD.body OR NEW.notification_id IS NOT OLD.notification_id OR NEW.required_seal IS NOT OLD.required_seal
 THEN RAISE(ABORT,'seal_once') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingest_epoch WHERE epoch=NEW.epoch AND state='open' AND last_sequence=NEW.receive_sequence)
 THEN RAISE(ABORT,'epoch_watermark') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingress_inbox i JOIN ingress_source s USING(source_id)
 JOIN ingress_registry r USING(source_id) WHERE i.inbox_id=NEW.inbox_id AND i.commit_id=NEW.commit_id
 AND s.revision=NEW.source_revision_after AND s.contiguous_sequence=i.source_sequence AND r.revision=NEW.registry_revision)
 THEN RAISE(ABORT,'source_projection') END;
 SELECT CASE WHEN NEW.expected_targets!=(SELECT count(*) FROM ingress_target WHERE commit_id=NEW.commit_id)
 OR EXISTS(SELECT l.run_id,l.artifact_digest,l.binding_body FROM ingress_listener l JOIN ingress_inbox i USING(source_id) WHERE i.inbox_id=NEW.inbox_id
 EXCEPT SELECT run_id,artifact_digest,binding_body FROM ingress_target WHERE commit_id=NEW.commit_id)
 OR EXISTS(SELECT run_id,artifact_digest,binding_body FROM ingress_target WHERE commit_id=NEW.commit_id
 EXCEPT SELECT l.run_id,l.artifact_digest,l.binding_body FROM ingress_listener l JOIN ingress_inbox i USING(source_id) WHERE i.inbox_id=NEW.inbox_id)
 THEN RAISE(ABORT,'whole_match_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_target t LEFT JOIN ingress_decision d
 ON d.decision_id=t.decision_id AND d.run_id=t.run_id AND d.commit_id=t.commit_id WHERE t.commit_id=NEW.commit_id AND d.decision_id IS NULL)
 THEN RAISE(ABORT,'decision_coverage') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_snapshot s LEFT JOIN ingress_decision d
 ON d.snapshot_id=s.snapshot_id AND d.commit_id=s.commit_id AND d.run_id=s.run_id
 WHERE s.commit_id=NEW.commit_id AND d.decision_id IS NULL)
 THEN RAISE(ABORT,'snapshot_coverage') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingress_notification WHERE commit_id=NEW.commit_id AND notification_id=NEW.notification_id)
 OR NOT EXISTS(SELECT 1 FROM ingress_charge WHERE commit_id=NEW.commit_id)
 OR EXISTS(SELECT 1 FROM ingress_decision d LEFT JOIN ingress_run_audit a USING(commit_id,run_id)
 WHERE d.commit_id=NEW.commit_id AND a.run_id IS NULL)
 THEN RAISE(ABORT,'ingress_receipt_coverage') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_decision d LEFT JOIN run_ingest_progress p USING(run_id) JOIN run r USING(run_id)
 WHERE d.commit_id=NEW.commit_id AND (p.run_id IS NULL OR p.last_commit_id IS NOT NEW.commit_id OR p.epoch IS NOT NEW.epoch
 OR p.last_sequence IS NOT NEW.receive_sequence OR p.revision IS NOT d.progress_after OR r.revision IS NOT d.run_after))
 THEN RAISE(ABORT,'run_progress_projection') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_decision d JOIN ingress_inbox i USING(inbox_id) WHERE d.commit_id=NEW.commit_id AND i.observed_only=1 AND d.result='accepted')
 THEN RAISE(ABORT,'observed_only') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_decision d JOIN run r USING(run_id)
 LEFT JOIN execution e ON e.execution_id=d.execution_id LEFT JOIN execution_plan_set p ON p.execution_id=e.execution_id
 LEFT JOIN activation_slot a ON a.definition_id=r.definition_id
 WHERE d.commit_id=NEW.commit_id AND d.result='accepted' AND
 (e.execution_id IS NULL OR e.run_id IS NOT d.run_id OR e.origin_kind!='trigger' OR e.state!='running' OR p.sealed IS NOT 1
 OR r.active_execution_id IS NOT e.execution_id OR r.lifecycle!='running' OR a.active_run_id IS NOT r.run_id OR a.version IS NOT r.version))
 THEN RAISE(ABORT,'accepted_projection') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_decision d JOIN run r USING(run_id) WHERE d.commit_id=NEW.commit_id
 AND d.result IN ('protected','evaluation_unknown','ambiguous') AND (r.lifecycle!='paused' OR r.dispatch_eligible!=0))
 THEN RAISE(ABORT,'protected_projection') END;
END;
CREATE TRIGGER ingress_target_insert BEFORE INSERT ON ingress_target WHEN (SELECT sealed FROM ingress_commit WHERE commit_id=NEW.commit_id)!=0
BEGIN SELECT RAISE(ABORT,'sealed_targets'); END;
CREATE TRIGGER snapshot_insert BEFORE INSERT ON ingress_snapshot WHEN (SELECT sealed FROM ingress_commit WHERE commit_id=NEW.commit_id)!=0
BEGIN SELECT RAISE(ABORT,'sealed_snapshots'); END;
CREATE TRIGGER decision_insert BEFORE INSERT ON ingress_decision WHEN (SELECT sealed FROM ingress_commit WHERE commit_id=NEW.commit_id)!=0
BEGIN SELECT RAISE(ABORT,'sealed_decisions'); END;
CREATE TRIGGER decision_prestate BEFORE INSERT ON ingress_decision
WHEN NOT EXISTS(SELECT 1 FROM run r JOIN run_ingest_progress p USING(run_id)
 WHERE r.run_id=NEW.run_id AND r.revision=NEW.run_before AND p.revision=NEW.progress_before)
 OR (NEW.result='accepted' AND NOT EXISTS(SELECT 1 FROM run WHERE run_id=NEW.run_id AND lifecycle='armed'
 AND dispatch_eligible=1 AND active_execution_id IS NULL AND active_operation_id IS NULL))
BEGIN SELECT RAISE(ABORT,'decision_prestate'); END;
CREATE TRIGGER trigger_execution_requires_origin BEFORE INSERT ON execution
WHEN NEW.origin_kind='trigger' AND NOT EXISTS(SELECT 1 FROM ingress_execution WHERE execution_id=NEW.execution_id AND run_id=NEW.run_id)
BEGIN SELECT RAISE(ABORT,'trigger_origin_required'); END;
CREATE TRIGGER progress_update BEFORE UPDATE ON run_ingest_progress
WHEN NEW.run_id IS NOT OLD.run_id OR (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY) OR
 (NEW.epoch=OLD.epoch AND (length(NEW.last_sequence),NEW.last_sequence COLLATE BINARY)<(length(OLD.last_sequence),OLD.last_sequence COLLATE BINARY)) OR
 (NEW.epoch!=OLD.epoch AND (NEW.baseline_body IS OLD.baseline_body OR NEW.last_commit_id IS NOT NULL OR
 NOT EXISTS(SELECT 1 FROM run WHERE run_id=NEW.run_id AND lifecycle IN ('paused','disarmed') AND dispatch_eligible=0))) OR
 NOT EXISTS(SELECT 1 FROM ingest_epoch WHERE epoch=NEW.epoch AND state='open')
BEGIN SELECT RAISE(ABORT,'progress_epoch'); END;

CREATE TRIGGER commit_update_forbidden_delete BEFORE DELETE ON ingress_commit BEGIN SELECT RAISE(ABORT,'retain_commit'); END;
CREATE TRIGGER target_immutable BEFORE UPDATE ON ingress_target BEGIN SELECT RAISE(ABORT,'immutable_target'); END;
CREATE TRIGGER target_retain BEFORE DELETE ON ingress_target BEGIN SELECT RAISE(ABORT,'retain_target'); END;
CREATE TRIGGER snapshot_immutable BEFORE UPDATE ON ingress_snapshot BEGIN SELECT RAISE(ABORT,'immutable_snapshot'); END;
CREATE TRIGGER snapshot_retain BEFORE DELETE ON ingress_snapshot BEGIN SELECT RAISE(ABORT,'retain_snapshot'); END;
CREATE TRIGGER decision_immutable BEFORE UPDATE ON ingress_decision BEGIN SELECT RAISE(ABORT,'immutable_decision'); END;
CREATE TRIGGER decision_retain BEFORE DELETE ON ingress_decision BEGIN SELECT RAISE(ABORT,'retain_decision'); END;
CREATE TRIGGER origin_immutable BEFORE UPDATE ON ingress_execution BEGIN SELECT RAISE(ABORT,'immutable_origin'); END;
CREATE TRIGGER origin_retain BEFORE DELETE ON ingress_execution BEGIN SELECT RAISE(ABORT,'retain_origin'); END;
CREATE TRIGGER notification_immutable BEFORE UPDATE ON ingress_notification BEGIN SELECT RAISE(ABORT,'immutable_notification'); END;
CREATE TRIGGER notification_retain BEFORE DELETE ON ingress_notification BEGIN SELECT RAISE(ABORT,'retain_notification'); END;
CREATE TRIGGER audit_immutable BEFORE UPDATE ON ingress_run_audit BEGIN SELECT RAISE(ABORT,'immutable_audit'); END;
CREATE TRIGGER audit_retain BEFORE DELETE ON ingress_run_audit BEGIN SELECT RAISE(ABORT,'retain_audit'); END;
CREATE TRIGGER charge_immutable BEFORE UPDATE ON ingress_charge BEGIN SELECT RAISE(ABORT,'immutable_charge'); END;
CREATE TRIGGER charge_retain BEFORE DELETE ON ingress_charge BEGIN SELECT RAISE(ABORT,'retain_charge'); END;
CREATE TRIGGER progress_retain BEFORE DELETE ON run_ingest_progress BEGIN SELECT RAISE(ABORT,'retain_progress'); END;
