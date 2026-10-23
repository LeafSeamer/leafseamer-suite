-- R2准备登记原子配对；真实身份、预检和正文来源仍需可信writer。
CREATE TABLE pr_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES recovery_operation(operation_id),
 run_revision TEXT NOT NULL,slot_revision TEXT NOT NULL,dependency_head INTEGER NOT NULL CHECK(dependency_head>=0),
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 65536),
 manifest_digest TEXT NOT NULL,manifest_body BLOB NOT NULL CHECK(json_valid(manifest_body)),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER pr_commit_guard BEFORE INSERT ON pr_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM recovery_operation o JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 JOIN execution e ON e.execution_id=o.execution_id JOIN recovery_preview p ON p.preview_id=o.preview_id
 WHERE o.operation_id=NEW.operation_id AND o.state='preparing' AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.active_operation_id=o.operation_id AND r.active_execution_id=o.execution_id AND r.arm_generation=e.arm_generation
 AND r.revision=NEW.run_revision AND s.revision=NEW.slot_revision AND s.active_run_id=r.run_id AND s.version=r.version
 AND p.consumed_operation_id=o.operation_id AND e.state='prepared'
 AND json_type(o.targets_body)='array' AND json_array_length(o.targets_body)=NEW.target_count
 AND NOT EXISTS(SELECT 1 FROM json_each(o.targets_body) WHERE type!='text')
 AND NEW.target_count=(SELECT count(DISTINCT value) FROM json_each(o.targets_body))
 AND NEW.target_count=(SELECT count(*) FROM preparation_target WHERE operation_id=o.operation_id)
 AND NEW.target_count=(SELECT count(*) FROM p1_preparation WHERE recovery_operation_id=o.operation_id)
 AND EXISTS(SELECT 1 FROM p1_limit WHERE singleton=1 AND NEW.target_count<=max_targets)
 AND NOT EXISTS(SELECT value FROM json_each(o.targets_body) EXCEPT SELECT controller_id FROM preparation_target WHERE operation_id=o.operation_id)
 AND NEW.dependency_head=(SELECT coalesce(max(sequence),0) FROM p1_dependency)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=r.run_id AND substr('00000000000000000000'||r.arm_generation,-20)<=d.generation)
 AND json_extract(NEW.manifest_body,'$.operation_id') IS o.operation_id
 AND json_extract(NEW.manifest_body,'$.run_id') IS o.run_id
 AND json_extract(NEW.manifest_body,'$.execution_id') IS o.execution_id
 AND json_extract(NEW.manifest_body,'$.generation') IS r.arm_generation
 AND json_type(NEW.manifest_body,'$.registrations')='array'
 AND json_array_length(NEW.manifest_body,'$.registrations')=NEW.target_count)
 THEN RAISE(ABORT,'recovery_registration_seal') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM p1_preparation p JOIN preparation_target t
 ON t.operation_id=p.recovery_operation_id AND t.controller_id=p.recovery_controller_id
 WHERE p.recovery_operation_id=NEW.operation_id AND (p.mode!='recovery' OR t.state!='pending'
 OR json_extract(t.target_body,'$.controller_id') IS NOT p.recovery_controller_id
 OR json_extract(t.target_body,'$.registration_id') IS NOT p.registration_id
 OR json_extract(t.target_body,'$.preparation_id') IS NOT p.preparation_id
 OR json_extract(t.target_body,'$.controller_scope.authority_service_id') IS NOT p.controller_authority
 OR json_extract(t.target_body,'$.controller_scope.database_instance_id') IS NOT p.controller_database
 OR CAST(json_extract(t.target_body,'$.request_body') AS BLOB) IS NOT p.request_body))
 OR EXISTS(SELECT registration_id,CAST(binding_body AS TEXT) FROM p1_preparation WHERE recovery_operation_id=NEW.operation_id
 EXCEPT SELECT json_extract(value,'$.registration_id'),json_extract(value,'$.binding') FROM json_each(NEW.manifest_body,'$.registrations'))
 OR EXISTS(SELECT json_extract(value,'$.registration_id'),json_extract(value,'$.binding') FROM json_each(NEW.manifest_body,'$.registrations')
 EXCEPT SELECT registration_id,CAST(binding_body AS TEXT) FROM p1_preparation WHERE recovery_operation_id=NEW.operation_id)
 THEN RAISE(ABORT,'recovery_registration_members') END;
END;
CREATE TRIGGER pr_target_sealed BEFORE INSERT ON preparation_target
 WHEN EXISTS(SELECT 1 FROM pr_commit WHERE operation_id=NEW.operation_id)
 BEGIN SELECT RAISE(ABORT,'recovery_registration_sealed'); END;
CREATE TRIGGER pr_registration_sealed BEFORE INSERT ON p1_preparation
 WHEN NEW.mode='recovery' AND EXISTS(SELECT 1 FROM pr_commit WHERE operation_id=NEW.recovery_operation_id)
 BEGIN SELECT RAISE(ABORT,'recovery_registration_sealed'); END;

CREATE TABLE pr_attempt(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_preparation(registration_id),
 attempt_id TEXT NOT NULL UNIQUE,request_digest TEXT NOT NULL,binding_body BLOB NOT NULL,
 runtime_body BLOB NOT NULL CHECK(length(runtime_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER pr_attempt_guard BEFORE INSERT ON pr_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pr_commit k ON k.operation_id=p.recovery_operation_id
 JOIN recovery_operation o ON o.operation_id=k.operation_id JOIN run r ON r.run_id=p.run_id
 JOIN preparation_target t ON t.operation_id=o.operation_id AND t.controller_id=p.recovery_controller_id
 WHERE p.registration_id=NEW.registration_id AND p.request_digest=NEW.request_digest AND p.binding_body=NEW.binding_body
 AND o.state='preparing' AND t.state='pending' AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.active_operation_id=o.operation_id AND r.active_execution_id=p.execution_id AND r.arm_generation=p.generation
 AND NOT EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=r.run_id AND substr('00000000000000000000'||p.generation,-20)<=d.generation)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized'))
 THEN RAISE(ABORT,'preparation_attempt_ineligible') END;
END;
CREATE TABLE pr_receipt(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES pr_attempt(registration_id),
 operation_id TEXT NOT NULL,controller_id TEXT NOT NULL,evidence_id TEXT NOT NULL UNIQUE REFERENCES external_evidence(evidence_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 FOREIGN KEY(operation_id,controller_id,evidence_id) REFERENCES preparation_target(operation_id,controller_id,receipt_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER pr_receipt_guard BEFORE INSERT ON pr_receipt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN external_evidence e ON e.evidence_id=NEW.evidence_id
 WHERE p.registration_id=NEW.registration_id AND p.recovery_operation_id=NEW.operation_id AND p.recovery_controller_id=NEW.controller_id
 AND e.kind='preparation' AND e.authority_id=p.controller_authority AND e.database_id=p.controller_database
 AND json_extract(e.body,'$.state')='applied'
 AND CAST(json_extract(e.body,'$.binding') AS BLOB)=p.binding_body
 AND json_extract(e.body,'$.applied_receipt_ref.id') IS e.object_id
 AND json_extract(e.body,'$.preparation_revision') IS e.revision
 AND json_extract(e.body,'$.observation_digest') IS e.digest)
 THEN RAISE(ABORT,'preparation_receipt_binding') END;
END;
CREATE TRIGGER pr_target_receipt BEFORE UPDATE ON preparation_target WHEN NEW.state='applied' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pr_receipt WHERE operation_id=NEW.operation_id AND controller_id=NEW.controller_id AND evidence_id=NEW.receipt_id)
 THEN RAISE(ABORT,'preparation_adoption_required') END;
END;
CREATE TRIGGER pr_target_initial BEFORE INSERT ON preparation_target WHEN NEW.state!='pending' OR NEW.receipt_id IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'preparation_initial_pending'); END;
CREATE VIEW pr_recovery_inventory AS SELECT p.registration_id,p.recovery_operation_id AS operation_id,p.run_id,p.generation,
 CASE WHEN EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=p.run_id AND substr('00000000000000000000'||p.generation,-20)<=d.generation)
 THEN 'protected_query_only' WHEN EXISTS(SELECT 1 FROM pr_receipt q WHERE q.registration_id=p.registration_id) THEN 'historical_receipt'
 WHEN EXISTS(SELECT 1 FROM pr_attempt a WHERE a.registration_id=p.registration_id) THEN 'query_only' ELSE 'unattempted' END AS classification
 FROM p1_preparation p JOIN pr_commit k ON k.operation_id=p.recovery_operation_id;
CREATE TRIGGER pr_start_source_guard BEFORE INSERT ON execution_start WHEN
 EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source s USING(source_id) WHERE d.run_id=NEW.run_id AND s.state!='synchronized')
 OR NOT EXISTS(SELECT 1 FROM pr_commit WHERE operation_id=NEW.operation_id)
 OR EXISTS(SELECT 1 FROM preparation_target t WHERE t.operation_id=NEW.operation_id AND (t.state!='applied' OR NOT EXISTS(
 SELECT 1 FROM pr_receipt q WHERE q.operation_id=t.operation_id AND q.controller_id=t.controller_id AND q.evidence_id=t.receipt_id)))
 BEGIN SELECT RAISE(ABORT,'recovery_source_unqualified'); END;
CREATE TRIGGER pr_ready_guard BEFORE UPDATE ON recovery_operation WHEN NEW.state='ready' AND (
 NOT EXISTS(SELECT 1 FROM pr_commit WHERE operation_id=NEW.operation_id)
 OR EXISTS(SELECT 1 FROM preparation_target t WHERE t.operation_id=NEW.operation_id AND (t.state!='applied' OR NOT EXISTS(
 SELECT 1 FROM pr_receipt q WHERE q.operation_id=t.operation_id AND q.controller_id=t.controller_id AND q.evidence_id=t.receipt_id))))
 BEGIN SELECT RAISE(ABORT,'recovery_preparations_incomplete'); END;
