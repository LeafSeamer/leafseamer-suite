-- 普通布防保持disarmed直到全目标准备完成。此布局不承担真实提供者与物理磁盘证明。
CREATE TABLE lifecycle_operation_identity(
 operation_id TEXT PRIMARY KEY NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),kind TEXT NOT NULL CHECK(kind IN ('arm','recovery')),
 arm_id TEXT UNIQUE REFERENCES arm_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 recovery_id TEXT UNIQUE REFERENCES recovery_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(operation_id,run_id),
 CHECK((kind='arm' AND arm_id IS operation_id AND recovery_id IS NULL) OR(kind='recovery' AND recovery_id IS operation_id AND arm_id IS NULL))
) STRICT;
CREATE TRIGGER arm_identity_guard BEFORE INSERT ON lifecycle_operation_identity WHEN NOT EXISTS(
 SELECT 1 FROM arm_operation WHERE operation_id=NEW.arm_id AND run_id=NEW.run_id) AND NOT EXISTS(
 SELECT 1 FROM recovery_operation WHERE operation_id=NEW.recovery_id AND run_id=NEW.run_id)
 BEGIN SELECT RAISE(ABORT,'operation_identity_binding'); END;
CREATE TRIGGER arm_register_recovery AFTER INSERT ON recovery_operation BEGIN
 INSERT INTO lifecycle_operation_identity VALUES(NEW.operation_id,NEW.run_id,'recovery',NULL,NEW.operation_id); END;
CREATE TABLE arm_capacity(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),profile_digest TEXT NOT NULL UNIQUE,profile_body BLOB NOT NULL,
 max_operations INTEGER NOT NULL CHECK(max_operations BETWEEN 1 AND 1000000),
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000)
) STRICT;
CREATE TABLE arm_preflight(
 preflight_id TEXT PRIMARY KEY NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),run_revision TEXT NOT NULL,slot_revision TEXT NOT NULL,generation_before TEXT NOT NULL,
 artifact_digest TEXT NOT NULL,dependency_head INTEGER NOT NULL,source_body BLOB NOT NULL,targets_body BLOB NOT NULL,
 clock_body BLOB NOT NULL,issued_tick TEXT NOT NULL,expires_tick TEXT NOT NULL,preflight_digest TEXT NOT NULL,consumed_operation_id TEXT UNIQUE,
 UNIQUE(preflight_id,run_id,consumed_operation_id),
 FOREIGN KEY(consumed_operation_id,run_id,preflight_id) REFERENCES arm_operation(operation_id,run_id,preflight_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((length(issued_tick),issued_tick COLLATE BINARY)<(length(expires_tick),expires_tick COLLATE BINARY))
) STRICT;
CREATE TRIGGER arm_preflight_update BEFORE UPDATE ON arm_preflight WHEN
 NEW.preflight_id IS NOT OLD.preflight_id OR NEW.run_id IS NOT OLD.run_id OR NEW.run_revision IS NOT OLD.run_revision OR NEW.slot_revision IS NOT OLD.slot_revision
 OR NEW.generation_before IS NOT OLD.generation_before OR NEW.artifact_digest IS NOT OLD.artifact_digest OR NEW.dependency_head IS NOT OLD.dependency_head
 OR NEW.source_body IS NOT OLD.source_body OR NEW.targets_body IS NOT OLD.targets_body OR NEW.clock_body IS NOT OLD.clock_body
 OR NEW.issued_tick IS NOT OLD.issued_tick OR NEW.expires_tick IS NOT OLD.expires_tick OR NEW.preflight_digest IS NOT OLD.preflight_digest
 OR OLD.consumed_operation_id IS NOT NULL OR NEW.consumed_operation_id IS NULL
 BEGIN SELECT RAISE(ABORT,'immutable_arm_preflight'); END;
CREATE TABLE arm_operation(
 operation_id TEXT PRIMARY KEY NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),preflight_id TEXT NOT NULL UNIQUE,
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,request_digest TEXT NOT NULL,request_body BLOB NOT NULL,
 run_before TEXT NOT NULL,run_after TEXT NOT NULL,slot_before TEXT NOT NULL,slot_after TEXT NOT NULL,generation_before TEXT NOT NULL,generation TEXT NOT NULL,
 clock_body BLOB NOT NULL,now_tick TEXT NOT NULL,target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),
 UNIQUE(operation_id,run_id,preflight_id),UNIQUE(operation_id,run_id),UNIQUE(run_id,generation),UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(preflight_id,run_id,operation_id) REFERENCES arm_preflight(preflight_id,run_id,consumed_operation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id) REFERENCES arm_register_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id) REFERENCES arm_budget_reservation(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER arm_operation_guard BEFORE INSERT ON arm_operation WHEN NOT EXISTS(
 SELECT 1 FROM run r JOIN activation_slot s USING(definition_id) JOIN published_version v USING(definition_id,version)
 JOIN arm_preflight p ON p.preflight_id=NEW.preflight_id WHERE r.run_id=NEW.run_id AND p.run_id=r.run_id
 AND r.lifecycle='disarmed' AND r.dispatch_eligible=0 AND r.active_operation_id IS NULL AND r.active_execution_id IS NULL
 AND (s.active_run_id IS NULL OR(s.active_run_id=r.run_id AND s.version=r.version))
 AND r.revision=NEW.run_before AND r.revision=p.run_revision AND s.revision=NEW.slot_before AND s.revision=p.slot_revision
 AND r.arm_generation=NEW.generation_before AND r.arm_generation=p.generation_before AND p.artifact_digest=v.artifact_digest
 AND NEW.run_before!='99999999999999999999' AND NEW.slot_before!='99999999999999999999' AND NEW.generation_before!='99999999999999999999'
 AND NEW.run_after=__RUN_NEXT__ AND NEW.slot_after=__SLOT_NEXT__ AND NEW.generation=__GEN_NEXT__
 AND p.consumed_operation_id IS NULL AND NEW.clock_body=p.clock_body
 AND (length(NEW.now_tick),NEW.now_tick COLLATE BINARY)>=(length(p.issued_tick),p.issued_tick COLLATE BINARY)
 AND (length(NEW.now_tick),NEW.now_tick COLLATE BINARY)<(length(p.expires_tick),p.expires_tick COLLATE BINARY)
 AND json_type(p.targets_body)='array' AND json_array_length(p.targets_body)=NEW.target_count
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL))
 BEGIN SELECT RAISE(ABORT,'arm_prestate'); END;
CREATE TRIGGER arm_register_identity AFTER INSERT ON arm_operation BEGIN
 INSERT INTO lifecycle_operation_identity VALUES(NEW.operation_id,NEW.run_id,'arm',NEW.operation_id,NULL); END;
CREATE TABLE arm_budget_reservation(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_operation(operation_id),profile_digest TEXT NOT NULL REFERENCES arm_capacity(profile_digest),
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 budget_body BLOB NOT NULL CHECK(length(budget_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER arm_budget_guard BEFORE INSERT ON arm_budget_reservation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM arm_capacity c JOIN arm_operation o ON o.operation_id=NEW.operation_id JOIN storage_scope sc ON sc.singleton=1
 WHERE c.profile_digest=NEW.profile_digest AND (SELECT count(*) FROM arm_budget_reservation)<c.max_operations
 AND NEW.logical_rows+coalesce((SELECT sum(logical_rows) FROM arm_budget_reservation),0)<=c.logical_rows
 AND NEW.logical_bytes+coalesce((SELECT sum(logical_bytes) FROM arm_budget_reservation),0)<=c.logical_bytes
 AND NEW.queue_slots+coalesce((SELECT sum(queue_slots) FROM arm_budget_reservation),0)<=c.queue_slots
 AND NEW.work_units+coalesce((SELECT sum(work_units) FROM arm_budget_reservation),0)<=c.work_units
 AND json_extract(NEW.budget_body,'$.binding.operation_id') IS o.operation_id AND json_extract(NEW.budget_body,'$.binding.run_id') IS o.run_id
 AND json_extract(NEW.budget_body,'$.binding.generation') IS o.generation AND json_extract(NEW.budget_body,'$.binding.profile_digest') IS c.profile_digest
 AND json_extract(NEW.budget_body,'$.binding.scope.authority_service_id') IS sc.authority_id
 AND json_extract(NEW.budget_body,'$.binding.scope.database_instance_id') IS sc.database_id
 AND json_extract(NEW.budget_body,'$.state')='held'
 AND json_extract(NEW.budget_body,'$.held.logical_rows') IS CAST(NEW.logical_rows AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.logical_bytes') IS CAST(NEW.logical_bytes AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.queue_slots') IS CAST(NEW.queue_slots AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.work_units') IS CAST(NEW.work_units AS TEXT)) THEN RAISE(ABORT,'arm_budget_binding_or_capacity') END;
 SELECT CASE WHEN (SELECT count(*) FROM json_each(NEW.budget_body,'$.binding.forecast'))!=6 OR EXISTS(
 SELECT 1 FROM json_each(NEW.budget_body,'$.binding.forecast') f JOIN arm_capacity c ON c.profile_digest=NEW.profile_digest
 WHERE f.key NOT IN ('dependencies','runs','executions','preparations','submissions','controller_targets') OR f.type!='text'
 OR f.value!=CAST(CAST(f.value AS INTEGER) AS TEXT) OR CAST(f.value AS INTEGER) NOT BETWEEN 0 AND 65536
 OR CAST(f.value AS INTEGER)>CAST(json_extract(c.profile_body,'$.max_shape.'||f.key) AS INTEGER))
 THEN RAISE(ABORT,'arm_budget_shape') END;
 SELECT CASE WHEN NOT EXISTS(WITH x AS(SELECT
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.dependencies') AS INTEGER) AS d,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.runs') AS INTEGER) AS r,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.executions') AS INTEGER) AS e,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.preparations') AS INTEGER) AS p,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.submissions') AS INTEGER) AS s,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.controller_targets') AS INTEGER) AS t,
 CAST(json_extract(profile_body,'$.episodes') AS INTEGER) AS n,CAST(json_extract(profile_body,'$.max_row_bytes') AS INTEGER) AS m
 FROM arm_capacity WHERE profile_digest=NEW.profile_digest), y AS(SELECT *,32+3*d+6*r+3*e+132*p+3*s+68*t AS rows FROM x)
 SELECT 1 FROM y WHERE r>=1 AND n BETWEEN 1 AND 1024 AND m BETWEEN 1 AND 1048576
 AND NEW.logical_rows=rows*n AND NEW.logical_bytes=rows*(m+512)*n AND NEW.queue_slots=(2*t+p+1)*n AND NEW.work_units=(rows+d+r+e+p+s+t)*n
 AND json_extract(NEW.budget_body,'$.episodes_left') IS CAST(n AS TEXT)
 AND json_extract(NEW.budget_body,'$.spent.logical_rows')='0' AND json_extract(NEW.budget_body,'$.spent.logical_bytes')='0'
 AND json_extract(NEW.budget_body,'$.spent.queue_slots')='0' AND json_extract(NEW.budget_body,'$.spent.work_units')='0')
 THEN RAISE(ABORT,'arm_budget_cost') END;
END;
CREATE TABLE arm_target(
 operation_id TEXT NOT NULL REFERENCES arm_operation(operation_id),controller_id TEXT NOT NULL,registration_id TEXT NOT NULL UNIQUE,
 target_body BLOB NOT NULL,PRIMARY KEY(operation_id,controller_id),
 FOREIGN KEY(registration_id) REFERENCES p1_preparation(registration_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id,controller_id) REFERENCES p1_preparation(arm_operation_id,arm_controller_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER arm_target_guard BEFORE INSERT ON arm_target WHEN EXISTS(SELECT 1 FROM arm_register_commit WHERE operation_id=NEW.operation_id)
 BEGIN SELECT RAISE(ABORT,'arm_targets_sealed'); END;
CREATE TABLE arm_register_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_operation(operation_id),manifest_body BLOB NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE VIEW arm_sources_current AS SELECT o.operation_id FROM arm_operation o JOIN arm_preflight p USING(preflight_id)
 WHERE p.dependency_head=(SELECT coalesce(max(sequence),0) FROM p1_dependency)
 AND json_type(p.source_body)='array' AND json_array_length(p.source_body)=(SELECT count(DISTINCT source_id) FROM p1_dependency WHERE run_id=o.run_id)
 AND NOT EXISTS(SELECT source_id,revision,state FROM ingress_source WHERE source_id IN (SELECT source_id FROM p1_dependency WHERE run_id=o.run_id)
 EXCEPT SELECT json_extract(value,'$.source_id'),json_extract(value,'$.revision'),json_extract(value,'$.state') FROM json_each(p.source_body))
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source s USING(source_id) WHERE d.run_id=o.run_id AND s.state!='synchronized');
CREATE TRIGGER arm_register_guard BEFORE INSERT ON arm_register_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM arm_operation o JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 JOIN arm_preflight f USING(preflight_id) JOIN arm_budget_reservation b USING(operation_id) JOIN arm_sources_current c USING(operation_id)
 WHERE o.operation_id=NEW.operation_id AND r.lifecycle='disarmed' AND r.dispatch_eligible=0 AND r.active_operation_id=o.operation_id
 AND r.active_execution_id IS NULL AND r.revision=o.run_after AND r.arm_generation=o.generation
 AND s.revision=o.slot_after AND s.active_run_id=r.run_id AND s.version=r.version AND f.consumed_operation_id=o.operation_id
 AND o.target_count=(SELECT count(*) FROM arm_target WHERE operation_id=o.operation_id)
 AND o.target_count=(SELECT count(*) FROM p1_preparation WHERE arm_operation_id=o.operation_id)
 AND json_type(NEW.manifest_body)='array' AND json_array_length(NEW.manifest_body)=o.target_count
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.preparations') AS INTEGER)>=(SELECT count(*) FROM p1_preparation WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.dependencies') AS INTEGER)>=(SELECT count(*) FROM p1_dependency WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.executions') AS INTEGER)>=(SELECT count(*) FROM execution WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.submissions') AS INTEGER)>=(SELECT count(*) FROM command_submission WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.controller_targets') AS INTEGER)>=(SELECT count(*) FROM (
 SELECT controller_authority,controller_database FROM p1_preparation WHERE run_id=o.run_id
 UNION SELECT target_authority,target_database FROM command_submission WHERE run_id=o.run_id))
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||o.generation,-20)<=generation)
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL)) THEN RAISE(ABORT,'arm_register_projection') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM arm_target t JOIN p1_preparation p ON p.registration_id=t.registration_id
 WHERE t.operation_id=NEW.operation_id AND (p.arm_operation_id!=t.operation_id OR p.arm_controller_id!=t.controller_id
 OR p.mode!='arm' OR p.execution_id IS NOT NULL OR json_extract(t.target_body,'$.registration_id') IS NOT p.registration_id
 OR json_extract(t.target_body,'$.preparation_id') IS NOT p.preparation_id OR json_extract(t.target_body,'$.controller_id') IS NOT t.controller_id
 OR json_extract(t.target_body,'$.controller_scope.authority_service_id') IS NOT p.controller_authority
 OR json_extract(t.target_body,'$.controller_scope.database_instance_id') IS NOT p.controller_database
 OR CAST(json_extract(t.target_body,'$.request_body') AS BLOB) IS NOT p.request_body))
 OR EXISTS(SELECT CAST(t.target_body AS TEXT) FROM arm_target t WHERE t.operation_id=NEW.operation_id
 EXCEPT SELECT value FROM arm_operation o JOIN arm_preflight f USING(preflight_id),json_each(f.targets_body) WHERE o.operation_id=NEW.operation_id)
 OR EXISTS(SELECT registration_id,CAST(binding_body AS TEXT) FROM p1_preparation WHERE arm_operation_id=NEW.operation_id
 EXCEPT SELECT json_extract(value,'$.registration_id'),json_extract(value,'$.binding') FROM json_each(NEW.manifest_body))
 THEN RAISE(ABORT,'arm_register_members') END;
END;
CREATE VIEW arm_pending_eligible AS SELECT o.* FROM arm_operation o JOIN arm_register_commit k USING(operation_id)
 JOIN arm_budget_reservation b USING(operation_id) JOIN arm_sources_current sc USING(operation_id)
 JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 WHERE r.lifecycle='disarmed' AND r.dispatch_eligible=0 AND r.active_execution_id IS NULL AND r.active_operation_id=o.operation_id
 AND r.arm_generation=o.generation AND r.revision=o.run_after AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=o.slot_after
 AND NOT EXISTS(SELECT 1 FROM arm_complete WHERE operation_id=o.operation_id)
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||o.generation,-20)<=generation)
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL);
CREATE TABLE arm_attempt(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_preparation(registration_id),attempt_id TEXT NOT NULL UNIQUE,
 binding_body BLOB NOT NULL,runtime_body BLOB NOT NULL CHECK(length(runtime_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER arm_attempt_guard BEFORE INSERT ON arm_attempt WHEN NOT EXISTS(
 SELECT 1 FROM p1_preparation p JOIN arm_pending_eligible o ON o.operation_id=p.arm_operation_id JOIN pq_current q USING(registration_id)
 WHERE p.registration_id=NEW.registration_id AND p.binding_body=NEW.binding_body AND q.qualification!='invalidated')
 BEGIN SELECT RAISE(ABORT,'arm_attempt_ineligible'); END;
CREATE TABLE arm_receipt(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_attempt(registration_id),evidence_id TEXT NOT NULL UNIQUE REFERENCES external_evidence(evidence_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER arm_receipt_guard BEFORE INSERT ON arm_receipt WHEN NOT EXISTS(
 SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) JOIN external_evidence e ON e.evidence_id=NEW.evidence_id
 WHERE p.registration_id=NEW.registration_id AND p.mode='arm' AND q.qualification='observed_applied' AND e.kind='preparation'
 AND p.controller_authority=e.authority_id AND p.controller_database=e.database_id AND json_extract(e.body,'$.state')='applied'
 AND CAST(json_extract(e.body,'$.binding') AS BLOB)=p.binding_body AND json_extract(e.body,'$.applied_receipt_ref.id') IS e.object_id
 AND json_extract(e.body,'$.preparation_revision') IS e.revision AND json_extract(e.body,'$.observation_digest') IS e.digest)
 BEGIN SELECT RAISE(ABORT,'arm_receipt_binding'); END;
CREATE TABLE arm_complete(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_operation(operation_id),run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,slot_revision TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0),
 FOREIGN KEY(operation_id) REFERENCES arm_ready_commit(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER arm_complete_guard BEFORE INSERT ON arm_complete WHEN NOT EXISTS(
 SELECT 1 FROM arm_pending_eligible o WHERE o.operation_id=NEW.operation_id AND o.run_id=NEW.run_id AND o.generation=NEW.generation
 AND o.run_after=NEW.revision_before AND o.slot_after=NEW.slot_revision AND NEW.revision_before!='99999999999999999999' AND NEW.revision_after=__COMPLETE_NEXT__
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.arm_operation_id=o.operation_id
 AND (q.qualification!='observed_applied' OR NOT EXISTS(SELECT 1 FROM arm_receipt WHERE registration_id=p.registration_id))))
 BEGIN SELECT RAISE(ABORT,'arm_complete_unqualified'); END;
CREATE TABLE arm_ready_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_complete(operation_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER arm_ready_guard BEFORE INSERT ON arm_ready_commit WHEN NOT EXISTS(
 SELECT 1 FROM arm_complete c JOIN run r USING(run_id) JOIN arm_sources_current sc USING(operation_id)
 JOIN activation_slot s USING(definition_id) WHERE c.operation_id=NEW.operation_id
 AND r.revision=c.revision_after AND r.arm_generation=c.generation AND r.lifecycle='armed' AND r.dispatch_eligible=1
 AND r.active_operation_id IS NULL AND r.active_execution_id IS NULL
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=c.slot_revision
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||c.generation,-20)<=generation)
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.arm_operation_id=c.operation_id AND q.qualification!='observed_applied'))
 BEGIN SELECT RAISE(ABORT,'arm_ready_projection'); END;
CREATE TRIGGER arm_run_initial BEFORE INSERT ON run WHEN NEW.lifecycle!='disarmed' OR NEW.dispatch_eligible!=0 OR NEW.arm_generation!='0'
 OR NEW.active_operation_id IS NOT NULL OR NEW.active_execution_id IS NOT NULL OR NEW.last_commit_id IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'run_initial_disarmed'); END;
CREATE TRIGGER arm_run_open BEFORE UPDATE ON run WHEN NEW.dispatch_eligible=1 AND (OLD.dispatch_eligible=0 OR OLD.lifecycle='disarmed')
 AND NOT EXISTS(SELECT 1 FROM arm_complete c WHERE c.run_id=NEW.run_id AND c.operation_id=OLD.active_operation_id AND c.generation=NEW.arm_generation
 AND c.revision_before=OLD.revision AND c.revision_after=NEW.revision AND NEW.lifecycle='armed' AND NOT EXISTS(SELECT 1 FROM arm_ready_commit WHERE operation_id=c.operation_id))
 AND NOT EXISTS(SELECT 1 FROM execution_start st WHERE st.run_id=NEW.run_id AND st.execution_id=NEW.active_execution_id
 AND st.operation_id=OLD.active_operation_id AND st.run_revision_before=OLD.revision AND st.run_revision_after=NEW.revision AND NEW.lifecycle='running')
 AND NOT EXISTS(SELECT 1 FROM transition_commit c JOIN execution e USING(execution_id,run_id)
 WHERE c.run_id=NEW.run_id AND c.commit_id=NEW.last_commit_id AND NEW.last_commit_id IS NOT OLD.last_commit_id
 AND OLD.lifecycle='running' AND OLD.active_execution_id=c.execution_id AND OLD.active_operation_id IS NULL
 AND e.commit_id=c.commit_id AND e.state='succeeded' AND e.arm_generation=OLD.arm_generation AND e.arm_generation=NEW.arm_generation
 AND NEW.active_execution_id IS NULL AND NEW.active_operation_id IS NULL AND NEW.lifecycle='armed'
 AND OLD.revision!='99999999999999999999' AND NEW.revision=__RETURN_NEXT__)
 BEGIN SELECT RAISE(ABORT,'dispatch_open_requires_commit'); END;
CREATE TRIGGER arm_run_armed BEFORE UPDATE ON run WHEN NEW.lifecycle='armed' AND OLD.lifecycle!='armed'
 AND NOT EXISTS(SELECT 1 FROM arm_complete c WHERE c.run_id=NEW.run_id AND c.operation_id=OLD.active_operation_id
 AND c.generation=NEW.arm_generation AND c.revision_before=OLD.revision AND c.revision_after=NEW.revision
 AND NOT EXISTS(SELECT 1 FROM arm_ready_commit WHERE operation_id=c.operation_id))
 AND NOT EXISTS(SELECT 1 FROM transition_commit c JOIN execution e USING(execution_id,run_id)
 WHERE c.run_id=NEW.run_id AND c.commit_id=NEW.last_commit_id AND NEW.last_commit_id IS NOT OLD.last_commit_id
 AND OLD.lifecycle='running' AND OLD.active_execution_id=c.execution_id AND OLD.active_operation_id IS NULL
 AND e.commit_id=c.commit_id AND e.state='succeeded' AND e.arm_generation=OLD.arm_generation AND e.arm_generation=NEW.arm_generation
 AND NEW.active_execution_id IS NULL AND NEW.active_operation_id IS NULL
 AND OLD.revision!='99999999999999999999' AND NEW.revision=__RETURN_NEXT__)
 BEGIN SELECT RAISE(ABORT,'armed_requires_completion'); END;
