-- 两种操作共享预算身份，原件分别保留，不把恢复伪装成普通布防。
CREATE VIEW recovery_budget_operation AS SELECT o.operation_id,o.run_id,e.arm_generation AS generation
 FROM recovery_operation o JOIN execution e ON e.execution_id=o.execution_id;
CREATE TABLE recovery_budget_reservation(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES recovery_operation(operation_id),profile_digest TEXT NOT NULL REFERENCES arm_capacity(profile_digest),
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 preview_digest TEXT NOT NULL,manifest_digest TEXT NOT NULL,request_digest TEXT NOT NULL,
 budget_body BLOB NOT NULL CHECK(json_valid(budget_body)),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 FOREIGN KEY(operation_id) REFERENCES recovery_budget_commit(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW protection_budget_reservation AS
 SELECT b.*,o.run_id,o.generation,'arm' AS kind FROM arm_budget_reservation b JOIN arm_operation o USING(operation_id)
 UNION ALL SELECT b.operation_id,b.profile_digest,b.logical_rows,b.logical_bytes,b.queue_slots,b.work_units,b.budget_body,b.audit_body,
 o.run_id,o.generation,'recovery' FROM recovery_budget_reservation b JOIN recovery_budget_operation o USING(operation_id);
CREATE TABLE budget_account(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES lifecycle_operation_identity(operation_id),
 run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('arm','recovery')),
 UNIQUE(run_id,generation)
) STRICT;
CREATE TRIGGER budget_account_guard BEFORE INSERT ON budget_account WHEN NOT EXISTS(
 SELECT 1 FROM protection_budget_reservation b JOIN lifecycle_operation_identity i USING(operation_id)
 WHERE b.operation_id=NEW.operation_id AND b.run_id=NEW.run_id AND b.generation=NEW.generation AND b.kind=NEW.kind
 AND i.run_id=b.run_id AND i.kind=b.kind)
 BEGIN SELECT RAISE(ABORT,'budget_account_original'); END;
CREATE TRIGGER budget_account_arm AFTER INSERT ON arm_budget_reservation BEGIN
 INSERT INTO budget_account SELECT operation_id,run_id,generation,'arm' FROM arm_operation WHERE operation_id=NEW.operation_id; END;
CREATE TRIGGER budget_account_recovery AFTER INSERT ON recovery_budget_reservation BEGIN
 INSERT INTO budget_account SELECT operation_id,run_id,generation,'recovery' FROM recovery_budget_operation WHERE operation_id=NEW.operation_id; END;
CREATE VIEW recovery_budget_fit AS SELECT b.operation_id FROM recovery_budget_reservation b JOIN recovery_budget_operation o USING(operation_id)
 WHERE CAST(json_extract(b.budget_body,'$.binding.forecast.dependencies') AS INTEGER)>=(SELECT count(*) FROM p1_dependency WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.executions') AS INTEGER)>=(SELECT count(*) FROM execution WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.preparations') AS INTEGER)>=(SELECT count(*) FROM p1_preparation WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.submissions') AS INTEGER)>=(SELECT count(*) FROM command_submission WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.controller_targets') AS INTEGER)>=(SELECT count(*) FROM (
 SELECT controller_authority,controller_database FROM p1_preparation WHERE run_id=o.run_id
 UNION SELECT target_authority,target_database FROM command_submission WHERE run_id=o.run_id));
CREATE TABLE recovery_budget_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES recovery_budget_reservation(operation_id),
 binding_digest TEXT NOT NULL,preview_digest TEXT NOT NULL,manifest_digest TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER recovery_budget_commit_guard BEFORE INSERT ON recovery_budget_commit WHEN NOT EXISTS(
 SELECT 1 FROM recovery_budget_reservation b JOIN recovery_operation o USING(operation_id) JOIN pr_commit k USING(operation_id)
 JOIN budget_account a USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest
 JOIN recovery_preview p ON p.preview_id=o.preview_id JOIN execution e ON e.execution_id=o.execution_id
 JOIN run r ON r.run_id=o.run_id JOIN activation_slot s USING(definition_id) JOIN published_version v ON v.definition_id=r.definition_id AND v.version=r.version
 JOIN recovery_budget_fit f USING(operation_id)
 WHERE o.operation_id=NEW.operation_id AND o.state='preparing' AND o.revision='1' AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.active_operation_id=o.operation_id AND r.active_execution_id=o.execution_id AND e.state='prepared' AND r.arm_generation=e.arm_generation
 AND a.run_id=r.run_id AND a.generation=e.arm_generation AND a.kind='recovery'
 AND r.revision=k.run_revision AND s.revision=k.slot_revision AND s.active_run_id=r.run_id AND s.version=r.version
 AND p.consumed_operation_id=o.operation_id AND b.preview_digest=p.preview_digest AND NEW.preview_digest=p.preview_digest
 AND b.manifest_digest=k.manifest_digest AND NEW.manifest_digest=k.manifest_digest AND b.request_digest=o.request_digest
 AND NEW.binding_digest IS json_extract(b.budget_body,'$.binding_digest')
 AND json_extract(b.budget_body,'$.binding.artifact_digest') IS v.artifact_digest
 AND json_extract(b.budget_body,'$.binding.profile_id') IS json_extract(c.profile_body,'$.profile_id')
 AND json_extract(b.budget_body,'$.binding.profile_revision') IS json_extract(c.profile_body,'$.revision')
 AND k.dependency_head=(SELECT coalesce(max(sequence),0) FROM p1_dependency)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||r.arm_generation,-20)<=generation)
 AND NOT EXISTS(SELECT 1 FROM pb_use WHERE operation_id=o.operation_id))
 BEGIN SELECT RAISE(ABORT,'recovery_budget_seal'); END;
CREATE TRIGGER recovery_start_budget BEFORE INSERT ON execution_start WHEN NOT EXISTS(
 SELECT 1 FROM recovery_budget_commit k JOIN recovery_budget_reservation b USING(operation_id)
 JOIN budget_account a USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest JOIN recovery_budget_fit f USING(operation_id)
 WHERE k.operation_id=NEW.operation_id AND a.run_id=NEW.run_id AND a.kind='recovery'
 AND NOT EXISTS(SELECT 1 FROM pb_use WHERE operation_id=NEW.operation_id))
 BEGIN SELECT RAISE(ABORT,'recovery_start_budget_unavailable'); END;
