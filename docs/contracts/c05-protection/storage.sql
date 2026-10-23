-- P1持久集合与P4实际计划引用；来源绑定语义/认证仍由可信提供者负责。
CREATE TABLE p1_limit(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),profile_body BLOB NOT NULL CHECK(length(profile_body)>0),
 max_dependencies INTEGER NOT NULL CHECK(max_dependencies>0),max_preparations INTEGER NOT NULL CHECK(max_preparations>0),
 max_plans INTEGER NOT NULL CHECK(max_plans>0),max_runs INTEGER NOT NULL CHECK(max_runs BETWEEN 1 AND 4096),
 max_targets INTEGER NOT NULL CHECK(max_targets BETWEEN 1 AND 65536),max_payload_bytes INTEGER NOT NULL CHECK(max_payload_bytes>0)
) STRICT;
CREATE TABLE p1_dependency(
 dependency_id TEXT PRIMARY KEY NOT NULL,sequence INTEGER NOT NULL UNIQUE CHECK(sequence>0),
 source_id TEXT NOT NULL REFERENCES ingress_source(source_id),run_id TEXT NOT NULL REFERENCES run(run_id),
 owner_kind TEXT NOT NULL CHECK(owner_kind IN ('run','execution','recovery')),owner_ref TEXT NOT NULL,
 execution_id TEXT,recovery_id TEXT,artifact_digest TEXT NOT NULL,binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 UNIQUE(source_id,run_id,owner_kind,owner_ref),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(recovery_id,run_id) REFERENCES recovery_operation(operation_id,run_id),
 CHECK((owner_kind='run' AND owner_ref=run_id AND execution_id IS NULL AND recovery_id IS NULL)
 OR(owner_kind='execution' AND owner_ref=execution_id AND execution_id IS NOT NULL AND recovery_id IS NULL)
 OR(owner_kind='recovery' AND owner_ref=recovery_id AND recovery_id IS NOT NULL AND execution_id IS NULL))
) STRICT;
CREATE TRIGGER p1_dependency_guard BEFORE INSERT ON p1_dependency BEGIN
 SELECT CASE WHEN NEW.sequence!=(SELECT coalesce(max(sequence),0)+1 FROM p1_dependency)
 OR NOT EXISTS(SELECT 1 FROM p1_limit WHERE singleton=1 AND (SELECT count(*) FROM p1_dependency)<max_dependencies)
 OR NOT EXISTS(SELECT 1 FROM run r JOIN published_version p USING(definition_id,version) WHERE r.run_id=NEW.run_id AND p.artifact_digest=NEW.artifact_digest)
 THEN RAISE(ABORT,'source_dependency_registration') END;
END;
CREATE TABLE p1_preparation(
 registration_id TEXT PRIMARY KEY NOT NULL,sequence INTEGER NOT NULL UNIQUE CHECK(sequence>0),
 run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,preparation_id TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('arm','recovery')),execution_id TEXT,request_digest TEXT NOT NULL,
 recovery_operation_id TEXT,recovery_controller_id TEXT,
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),request_body BLOB NOT NULL CHECK(length(request_body)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(controller_authority,controller_database,preparation_id),
 UNIQUE(run_id,generation,controller_authority,controller_database),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(recovery_operation_id,recovery_controller_id) REFERENCES preparation_target(operation_id,controller_id),
 FOREIGN KEY(recovery_operation_id,run_id,execution_id) REFERENCES recovery_operation(operation_id,run_id,execution_id),
 CHECK((mode='arm' AND execution_id IS NULL) OR(mode='recovery' AND execution_id IS NOT NULL)),
 CHECK((mode='arm' AND recovery_operation_id IS NULL AND recovery_controller_id IS NULL)
 OR(mode='recovery' AND recovery_operation_id IS NOT NULL AND recovery_controller_id IS NOT NULL)),
 CHECK(length(generation) BETWEEN 1 AND 20 AND generation NOT GLOB '*[^0-9]*' AND substr(generation,1,1)!='0' AND instr(generation,char(0))=0)
) STRICT;
CREATE TRIGGER p1_preparation_guard BEFORE INSERT ON p1_preparation BEGIN
 SELECT CASE WHEN NEW.sequence!=(SELECT coalesce(max(sequence),0)+1 FROM p1_preparation)
 OR NOT EXISTS(SELECT 1 FROM p1_limit WHERE singleton=1 AND (SELECT count(*) FROM p1_preparation)<max_preparations)
 OR NOT EXISTS(SELECT 1 FROM run r WHERE r.run_id=NEW.run_id AND r.arm_generation=NEW.generation
 AND ((NEW.mode='arm' AND r.lifecycle='armed') OR(NEW.mode='recovery' AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.active_operation_id=NEW.recovery_operation_id AND r.active_execution_id=NEW.execution_id
 AND EXISTS(SELECT 1 FROM recovery_operation o JOIN execution e ON e.execution_id=o.execution_id JOIN preparation_target t USING(operation_id)
 WHERE o.operation_id=NEW.recovery_operation_id AND o.run_id=r.run_id AND o.state='preparing'
 AND e.arm_generation=NEW.generation AND e.state='prepared' AND t.controller_id=NEW.recovery_controller_id AND t.state='pending'))))
 OR EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=NEW.run_id AND substr('00000000000000000000'||NEW.generation,-20)<=d.generation)
 OR NOT EXISTS(SELECT 1 FROM storage_scope s WHERE s.singleton=1
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.preparation_id') IS NEW.preparation_id
 AND json_extract(NEW.binding_body,'$.run_id') IS NEW.run_id
 AND json_extract(NEW.binding_body,'$.generation') IS NEW.generation
 AND json_extract(NEW.binding_body,'$.mode') IS NEW.mode
 AND json_extract(NEW.binding_body,'$.execution_id') IS NEW.execution_id
 AND json_extract(NEW.binding_body,'$.request_digest') IS NEW.request_digest)
 THEN RAISE(ABORT,'preparation_registration') END;
END;
CREATE TABLE p1_fault(
 fault_id TEXT PRIMARY KEY NOT NULL,source_id TEXT NOT NULL REFERENCES ingress_source(source_id),
 detector_domain TEXT NOT NULL,detector_sequence TEXT NOT NULL,reason TEXT NOT NULL,
 fault_digest TEXT NOT NULL,fault_body BLOB NOT NULL CHECK(length(fault_body)>0),
 plan_id TEXT NOT NULL UNIQUE REFERENCES p1_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(detector_domain,detector_sequence),UNIQUE(fault_id,source_id,plan_id)
) STRICT;
CREATE TABLE p1_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,fault_id TEXT NOT NULL UNIQUE,source_id TEXT NOT NULL,
 dependency_head INTEGER NOT NULL CHECK(dependency_head>=0),preparation_head INTEGER NOT NULL CHECK(preparation_head>=0),
 source_before TEXT NOT NULL,source_after TEXT NOT NULL,source_state_before TEXT NOT NULL,source_state_after TEXT NOT NULL,
 source_sequence TEXT NOT NULL,reject_floor TEXT NOT NULL,
 run_count INTEGER NOT NULL CHECK(run_count BETWEEN 0 AND 4096),target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 65536),
 preparation_count INTEGER NOT NULL CHECK(preparation_count>=0),preparation_plan_id TEXT,
 plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(fault_id,source_id,plan_id) REFERENCES p1_fault(fault_id,source_id,plan_id),
 FOREIGN KEY(plan_id) REFERENCES p1_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(preparation_plan_id) REFERENCES po_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((preparation_count=0 AND preparation_plan_id IS NULL) OR(preparation_count>0 AND preparation_plan_id=plan_id))
) STRICT;
CREATE TRIGGER p1_plan_guard BEFORE INSERT ON p1_plan BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingress_source s WHERE s.source_id=NEW.source_id
 AND s.revision=NEW.source_before AND s.state=NEW.source_state_before AND s.contiguous_sequence=NEW.source_sequence AND s.reject_floor=NEW.reject_floor)
 OR (NEW.source_state_before='closed' AND (NEW.source_after!=NEW.source_before OR NEW.source_state_after!='closed'))
 OR (NEW.source_state_before!='closed' AND (NEW.source_before='99999999999999999999' OR NEW.source_after!=__SOURCE_NEXT__
 OR NEW.source_state_after NOT IN ('desynchronized','quarantined') OR(NEW.source_state_before='quarantined' AND NEW.source_state_after!='quarantined')))
 THEN RAISE(ABORT,'protection_source_prestate') END;
END;
CREATE TABLE p1_run(
 plan_id TEXT NOT NULL REFERENCES p1_plan(plan_id),run_id TEXT NOT NULL REFERENCES run(run_id),
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,generation TEXT NOT NULL,lifecycle_before TEXT NOT NULL,
 latch_id TEXT NOT NULL UNIQUE REFERENCES pause_latch(latch_id) DEFERRABLE INITIALLY DEFERRED,
 PRIMARY KEY(plan_id,run_id)
) STRICT;
CREATE TRIGGER p1_run_guard BEFORE INSERT ON p1_run BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM run r WHERE r.run_id=NEW.run_id AND r.revision=NEW.revision_before
 AND r.arm_generation=NEW.generation AND r.lifecycle=NEW.lifecycle_before)
 OR EXISTS(SELECT 1 FROM execution e WHERE e.run_id=NEW.run_id AND (length(e.arm_generation),e.arm_generation COLLATE BINARY)>(length(NEW.generation),NEW.generation COLLATE BINARY))
 OR (NEW.lifecycle_before='completed' AND NEW.revision_after!=NEW.revision_before)
 OR (NEW.lifecycle_before!='completed' AND (NEW.revision_before='99999999999999999999' OR NEW.revision_after!=__RUN_NEXT__))
 THEN RAISE(ABORT,'protection_run_prestate') END;
END;
CREATE TABLE p1_dependency_member(
 plan_id TEXT NOT NULL REFERENCES p1_plan(plan_id),dependency_id TEXT NOT NULL REFERENCES p1_dependency(dependency_id),
 PRIMARY KEY(plan_id,dependency_id)
) STRICT;
CREATE TABLE p1_execution_pin(
 plan_id TEXT NOT NULL,run_id TEXT NOT NULL,execution_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
 PRIMARY KEY(plan_id,execution_id),FOREIGN KEY(plan_id,run_id) REFERENCES p1_run(plan_id,run_id),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id)
) STRICT;
CREATE TABLE p1_controller(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,run_id TEXT NOT NULL,
 controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,operation_id TEXT NOT NULL,
 selector_digest TEXT NOT NULL,target_set_digest TEXT NOT NULL,binding_body BLOB NOT NULL,
 dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,run_id,controller_authority,controller_database),
 UNIQUE(controller_authority,controller_database,operation_id),
 FOREIGN KEY(plan_id,run_id) REFERENCES p1_run(plan_id,run_id),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER p1_controller_guard BEFORE INSERT ON p1_controller BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM p1_run r JOIN storage_scope s ON s.singleton=1 WHERE r.plan_id=NEW.plan_id AND r.run_id=NEW.run_id
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.operation_id') IS NEW.operation_id AND json_extract(NEW.binding_body,'$.run_id') IS NEW.run_id
 AND json_extract(NEW.binding_body,'$.deny_through_generation') IS r.generation
 AND json_extract(NEW.binding_body,'$.selector_digest') IS NEW.selector_digest AND json_extract(NEW.binding_body,'$.target_set_digest') IS NEW.target_set_digest)
 THEN RAISE(ABORT,'protection_controller_binding') END;
END;
CREATE TABLE p1_preparation_member(
 plan_id TEXT NOT NULL,registration_id TEXT NOT NULL REFERENCES p1_preparation(registration_id),target_id TEXT NOT NULL,
 PRIMARY KEY(plan_id,registration_id),FOREIGN KEY(plan_id,target_id) REFERENCES p1_controller(plan_id,target_id)
) STRICT;
CREATE TABLE p1_submission_member(
 plan_id TEXT NOT NULL,submission_id TEXT NOT NULL REFERENCES command_submission(submission_id),target_id TEXT NOT NULL,
 PRIMARY KEY(plan_id,submission_id),FOREIGN KEY(plan_id,target_id) REFERENCES p1_controller(plan_id,target_id)
) STRICT;
CREATE VIEW p1_expected_run AS SELECT DISTINCT p.plan_id,d.run_id FROM p1_plan p JOIN p1_dependency d USING(source_id);
CREATE VIEW p1_expected_preparation AS SELECT r.plan_id,p.registration_id,p.run_id,p.controller_authority,p.controller_database
 FROM p1_run r JOIN p1_preparation p USING(run_id) WHERE (length(p.generation),p.generation COLLATE BINARY)<=(length(r.generation),r.generation COLLATE BINARY);
CREATE VIEW p1_expected_submission AS SELECT r.plan_id,s.submission_id,s.run_id,s.target_authority AS controller_authority,s.target_database AS controller_database
 FROM p1_run r JOIN command_submission s USING(run_id) JOIN execution e ON e.execution_id=s.execution_id
 WHERE (length(e.arm_generation),e.arm_generation COLLATE BINARY)<=(length(r.generation),r.generation COLLATE BINARY);
CREATE VIEW p1_expected_controller AS SELECT plan_id,run_id,controller_authority,controller_database FROM p1_expected_preparation
 UNION SELECT plan_id,run_id,controller_authority,controller_database FROM p1_expected_submission;
CREATE TABLE p1_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_plan(plan_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER p1_seal BEFORE INSERT ON p1_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM p1_plan p JOIN ingress_source s USING(source_id) JOIN p1_limit l ON l.singleton=1
 WHERE p.plan_id=NEW.plan_id AND s.revision=p.source_after AND s.state=p.source_state_after
 AND s.contiguous_sequence=p.source_sequence AND s.reject_floor=p.reject_floor
 AND p.dependency_head=(SELECT coalesce(max(sequence),0) FROM p1_dependency)
 AND p.preparation_head=(SELECT coalesce(max(sequence),0) FROM p1_preparation)
 AND p.run_count=(SELECT count(*) FROM p1_run WHERE plan_id=p.plan_id) AND p.run_count<=l.max_runs
 AND p.target_count=(SELECT count(*) FROM p1_controller WHERE plan_id=p.plan_id) AND p.target_count<=l.max_targets
 AND p.preparation_count=(SELECT count(*) FROM p1_preparation_member WHERE plan_id=p.plan_id)
 AND (SELECT count(*) FROM p1_plan)<=l.max_plans
 AND length(p.plan_body)+(SELECT length(fault_body) FROM p1_fault WHERE fault_id=p.fault_id)
 +coalesce((SELECT sum(length(binding_body)+length(dispatch_body)+length(audit_body)) FROM p1_controller WHERE plan_id=p.plan_id),0)
 +length(NEW.audit_body)+length(NEW.notification_body)<=l.max_payload_bytes)
 THEN RAISE(ABORT,'protection_seal_prestate_or_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT run_id FROM p1_expected_run WHERE plan_id=NEW.plan_id EXCEPT SELECT run_id FROM p1_run WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT run_id FROM p1_run WHERE plan_id=NEW.plan_id EXCEPT SELECT run_id FROM p1_expected_run WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT d.dependency_id FROM p1_dependency d JOIN p1_plan p USING(source_id) WHERE p.plan_id=NEW.plan_id EXCEPT SELECT dependency_id FROM p1_dependency_member WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT dependency_id FROM p1_dependency_member WHERE plan_id=NEW.plan_id EXCEPT SELECT d.dependency_id FROM p1_dependency d JOIN p1_plan p USING(source_id) WHERE p.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_dependency_set') END;
 SELECT CASE WHEN EXISTS(SELECT r.run_id,e.execution_id,e.binding_digest FROM p1_run r JOIN execution e USING(run_id) WHERE r.plan_id=NEW.plan_id
 EXCEPT SELECT run_id,execution_id,binding_digest FROM p1_execution_pin WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT run_id,execution_id,binding_digest FROM p1_execution_pin WHERE plan_id=NEW.plan_id
 EXCEPT SELECT r.run_id,e.execution_id,e.binding_digest FROM p1_run r JOIN execution e USING(run_id) WHERE r.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_execution_set') END;
 SELECT CASE WHEN EXISTS(SELECT run_id,controller_authority,controller_database FROM p1_expected_controller WHERE plan_id=NEW.plan_id
 EXCEPT SELECT run_id,controller_authority,controller_database FROM p1_controller WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT run_id,controller_authority,controller_database FROM p1_controller WHERE plan_id=NEW.plan_id
 EXCEPT SELECT run_id,controller_authority,controller_database FROM p1_expected_controller WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_controller_set') END;
 SELECT CASE WHEN EXISTS(SELECT registration_id FROM p1_expected_preparation WHERE plan_id=NEW.plan_id EXCEPT SELECT registration_id FROM p1_preparation_member WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT registration_id FROM p1_preparation_member WHERE plan_id=NEW.plan_id EXCEPT SELECT registration_id FROM p1_expected_preparation WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT 1 FROM p1_preparation_member m JOIN p1_preparation r USING(registration_id) JOIN p1_controller c USING(plan_id,target_id)
 WHERE m.plan_id=NEW.plan_id AND (r.run_id,r.controller_authority,r.controller_database)!=(c.run_id,c.controller_authority,c.controller_database))
 OR EXISTS(SELECT submission_id FROM p1_expected_submission WHERE plan_id=NEW.plan_id EXCEPT SELECT submission_id FROM p1_submission_member WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT submission_id FROM p1_submission_member WHERE plan_id=NEW.plan_id EXCEPT SELECT submission_id FROM p1_expected_submission WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT 1 FROM p1_submission_member m JOIN command_submission r USING(submission_id) JOIN p1_controller c USING(plan_id,target_id)
 WHERE m.plan_id=NEW.plan_id AND (r.run_id,r.target_authority,r.target_database)!=(c.run_id,c.controller_authority,c.controller_database))
 OR EXISTS(SELECT 1 FROM p1_run r JOIN recovery_operation o USING(run_id) JOIN preparation_target t ON t.operation_id=o.operation_id
 WHERE r.plan_id=NEW.plan_id AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN p1_preparation_member m USING(registration_id)
 WHERE m.plan_id=r.plan_id AND p.recovery_operation_id=t.operation_id AND p.recovery_controller_id=t.controller_id))
 THEN RAISE(ABORT,'protection_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM p1_run t JOIN run r USING(run_id) LEFT JOIN pause_latch l ON l.latch_id=t.latch_id
 WHERE t.plan_id=NEW.plan_id AND (r.revision!=t.revision_after OR r.arm_generation!=t.generation OR r.dispatch_eligible!=0
 OR r.lifecycle!=CASE WHEN t.lifecycle_before='completed' THEN 'completed' ELSE 'paused' END
 OR l.latch_id IS NULL OR l.run_id!=r.run_id OR l.created_revision!=t.revision_after OR l.reason!='source_fault' OR l.cleared_start_id IS NOT NULL))
 THEN RAISE(ABORT,'protection_pause_projection') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sp_plan p JOIN sp_plan_commit k USING(plan_id) JOIN p1_plan s USING(plan_id)
 WHERE p.plan_id=NEW.plan_id AND p.target_count=s.target_count AND p.plan_digest=s.plan_digest AND p.plan_body=s.plan_body)
 OR EXISTS(SELECT target_id,binding_body FROM p1_controller WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM p1_controller WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT 1 FROM p1_plan p WHERE p.plan_id=NEW.plan_id AND p.preparation_count>0 AND NOT EXISTS(
 SELECT 1 FROM po_plan q JOIN po_plan_commit k USING(plan_id) WHERE q.plan_id=p.plan_id AND q.target_count=p.preparation_count))
 OR EXISTS(SELECT m.registration_id,r.binding_body FROM p1_preparation_member m JOIN p1_preparation r USING(registration_id) WHERE m.plan_id=NEW.plan_id
 EXCEPT SELECT target_id,binding_body FROM po_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM po_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT m.registration_id,r.binding_body FROM p1_preparation_member m JOIN p1_preparation r USING(registration_id) WHERE m.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_receiver_plan') END;
END;
CREATE VIEW p1_deny AS SELECT r.run_id,max(substr('00000000000000000000'||r.generation,-20)) AS generation
 FROM p1_run r JOIN p1_commit k USING(plan_id) GROUP BY r.run_id;
CREATE VIEW p1_pending_dispatch AS SELECT c.* FROM p1_controller c JOIN p1_commit k USING(plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=c.plan_id AND o.target_id=c.target_id AND o.state='applied');
CREATE TRIGGER p1_preparation_plan_guard BEFORE INSERT ON po_plan WHEN NOT EXISTS(
 SELECT 1 FROM p1_plan p WHERE p.plan_id=NEW.plan_id AND p.preparation_plan_id=NEW.plan_id AND p.preparation_count=NEW.target_count
 AND NOT EXISTS(SELECT 1 FROM p1_commit k WHERE k.plan_id=p.plan_id))
 BEGIN SELECT RAISE(ABORT,'unplanned_preparation_observation'); END;
CREATE TRIGGER p1_deny_ready BEFORE INSERT ON step_ready WHEN EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id)
 WHERE e.execution_id=NEW.execution_id AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'source_generation_denied'); END;
CREATE TRIGGER p1_deny_submission BEFORE INSERT ON command_submission WHEN EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id)
 WHERE e.execution_id=NEW.execution_id AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'source_generation_denied'); END;
CREATE TRIGGER p1_deny_attempt BEFORE INSERT ON submission_attempt WHEN EXISTS(SELECT 1 FROM command_submission s JOIN execution e USING(execution_id) JOIN p1_deny d ON d.run_id=e.run_id
 WHERE s.submission_id=NEW.submission_id AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'source_generation_denied'); END;
CREATE TRIGGER p1_deny_start BEFORE INSERT ON execution_start WHEN EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id)
 WHERE e.execution_id=NEW.execution_id AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'source_generation_denied'); END;
