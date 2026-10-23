-- 准备资格失效独立于事件来源故障；共享保护接收器，不伪造ingress_source状态。
CREATE TABLE protection_plan_registry(
 plan_id TEXT PRIMARY KEY NOT NULL,source_plan TEXT UNIQUE REFERENCES p1_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 preparation_plan TEXT UNIQUE REFERENCES pq_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((source_plan=plan_id AND preparation_plan IS NULL) OR(preparation_plan=plan_id AND source_plan IS NULL)),
 CHECK((source_plan IS NULL)!=(preparation_plan IS NULL))
) STRICT;
CREATE TRIGGER pq_register_source AFTER INSERT ON p1_plan BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NEW.plan_id,NULL); END;
CREATE TABLE pq_observation(
 registration_id TEXT NOT NULL REFERENCES p1_preparation(registration_id),revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 4),
 protection_revision INTEGER NOT NULL CHECK(protection_revision BETWEEN 0 AND 2),
 state TEXT NOT NULL CHECK(state IN ('accepted','applied','rejected','indeterminate','closing','closed')),
 binding_body BLOB NOT NULL,observation_digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16384),
 fault_registration TEXT GENERATED ALWAYS AS(CASE WHEN state NOT IN ('accepted','applied') THEN registration_id ELSE NULL END) STORED
 REFERENCES pq_fault(registration_id) DEFERRABLE INITIALLY DEFERRED,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0),
 PRIMARY KEY(registration_id,revision,protection_revision)
) STRICT;
CREATE TRIGGER pq_observation_guard BEFORE INSERT ON pq_observation WHEN NOT EXISTS(
 SELECT 1 FROM p1_preparation p WHERE p.registration_id=NEW.registration_id AND p.binding_body=NEW.binding_body
 AND CAST(json_extract(NEW.body,'$.binding') AS BLOB)=p.binding_body
 AND json_extract(NEW.body,'$.state') IS NEW.state AND json_extract(NEW.body,'$.preparation_revision') IS CAST(NEW.revision AS TEXT)
 AND json_extract(NEW.body,'$.protection_revision') IS CAST(NEW.protection_revision AS TEXT)
 AND json_extract(NEW.body,'$.observation_digest') IS NEW.observation_digest)
 BEGIN SELECT RAISE(ABORT,'qualification_observation_binding'); END;
CREATE TABLE pq_fault(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_preparation(registration_id),
 kind TEXT NOT NULL CHECK(kind IN ('conflict','unavailable','withdrawal')),
 evidence_digest TEXT NOT NULL,evidence_body BLOB NOT NULL CHECK(length(evidence_body) BETWEEN 1 AND 16384),
 plan_id TEXT NOT NULL UNIQUE REFERENCES pq_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(registration_id,plan_id)
) STRICT;
CREATE TRIGGER pq_fault_guard BEFORE INSERT ON pq_fault WHEN NOT EXISTS(
 SELECT 1 FROM p1_preparation p WHERE p.registration_id=NEW.registration_id AND CAST(json_extract(NEW.evidence_body,'$.binding') AS BLOB)=p.binding_body)
 BEGIN SELECT RAISE(ABORT,'qualification_fault_binding'); END;
CREATE TABLE pq_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,registration_id TEXT NOT NULL UNIQUE,run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 current_generation TEXT NOT NULL,revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,lifecycle_before TEXT NOT NULL,
 preparation_head INTEGER NOT NULL CHECK(preparation_head>=0),target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 65536),
 latch_id TEXT UNIQUE REFERENCES pause_latch(latch_id) DEFERRABLE INITIALLY DEFERRED,
 members_body BLOB NOT NULL CHECK(json_valid(members_body)),plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(registration_id,plan_id) REFERENCES pq_fault(registration_id,plan_id),
 FOREIGN KEY(plan_id) REFERENCES pq_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER pq_plan_guard BEFORE INSERT ON pq_plan BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM run r JOIN p1_preparation p ON p.run_id=r.run_id WHERE p.registration_id=NEW.registration_id
 AND p.run_id=NEW.run_id AND p.generation=NEW.generation AND r.arm_generation=NEW.current_generation
 AND (length(NEW.generation),NEW.generation COLLATE BINARY)<=(length(r.arm_generation),r.arm_generation COLLATE BINARY)
 AND r.revision=NEW.revision_before AND r.lifecycle=NEW.lifecycle_before)
 OR (NEW.current_generation=NEW.generation AND NEW.latch_id IS NULL)
 OR (NEW.current_generation!=NEW.generation AND NEW.latch_id IS NOT NULL)
 OR ((NEW.current_generation!=NEW.generation OR NEW.lifecycle_before='completed') AND NEW.revision_after!=NEW.revision_before)
 OR (NEW.current_generation=NEW.generation AND NEW.lifecycle_before!='completed' AND (NEW.revision_before='99999999999999999999' OR NEW.revision_after!=__REV_NEXT__))
 THEN RAISE(ABORT,'qualification_plan_prestate') END;
END;
CREATE TRIGGER pq_register_plan AFTER INSERT ON pq_plan BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NEW.plan_id); END;
CREATE TABLE pq_target(
 plan_id TEXT NOT NULL REFERENCES pq_plan(plan_id),target_id TEXT NOT NULL,controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,
 binding_body BLOB NOT NULL,dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,controller_authority,controller_database),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER pq_target_guard BEFORE INSERT ON pq_target BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pq_commit WHERE plan_id=NEW.plan_id) OR NOT EXISTS(
 SELECT 1 FROM pq_plan p JOIN storage_scope s ON s.singleton=1 WHERE p.plan_id=NEW.plan_id
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.run_id') IS p.run_id AND json_extract(NEW.binding_body,'$.deny_through_generation') IS p.generation
 AND json_extract(NEW.binding_body,'$.operation_id') IS NEW.target_id
 AND json_extract(NEW.binding_body,'$.target_set_digest') IS p.plan_digest)
 THEN RAISE(ABORT,'qualification_target_binding') END;
END;
CREATE VIEW pq_expected_preparation AS SELECT q.plan_id,p.registration_id,p.controller_authority,p.controller_database
 FROM pq_plan q JOIN p1_preparation p USING(run_id) WHERE (length(p.generation),p.generation COLLATE BINARY)<=(length(q.generation),q.generation COLLATE BINARY);
CREATE VIEW pq_expected_submission AS SELECT q.plan_id,s.submission_id,s.target_authority AS controller_authority,s.target_database AS controller_database
 FROM pq_plan q JOIN command_submission s USING(run_id) JOIN execution e USING(execution_id)
 WHERE (length(e.arm_generation),e.arm_generation COLLATE BINARY)<=(length(q.generation),q.generation COLLATE BINARY);
CREATE VIEW pq_expected_execution AS SELECT q.plan_id,e.execution_id,e.binding_digest FROM pq_plan q JOIN execution e USING(run_id)
 WHERE (length(e.arm_generation),e.arm_generation COLLATE BINARY)<=(length(q.generation),q.generation COLLATE BINARY);
CREATE VIEW pq_expected_target AS SELECT plan_id,controller_authority,controller_database FROM pq_expected_preparation
 UNION SELECT plan_id,controller_authority,controller_database FROM pq_expected_submission;
CREATE TABLE pq_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES pq_plan(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER pq_commit_guard BEFORE INSERT ON pq_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pq_plan p JOIN run r USING(run_id) JOIN p1_limit l ON l.singleton=1
 WHERE p.plan_id=NEW.plan_id AND r.revision=p.revision_after AND r.arm_generation=p.current_generation
 AND p.preparation_head=(SELECT coalesce(max(sequence),0) FROM p1_preparation)
 AND ((p.current_generation!=p.generation AND r.lifecycle=p.lifecycle_before) OR(p.current_generation=p.generation
 AND r.lifecycle=CASE WHEN p.lifecycle_before='completed' THEN 'completed' ELSE 'paused' END AND r.dispatch_eligible=0
 AND EXISTS(SELECT 1 FROM pause_latch x WHERE x.latch_id=p.latch_id AND x.run_id=p.run_id AND x.reason='preparation_qualification'
 AND x.created_revision=p.revision_after AND x.cleared_start_id IS NULL)))
 AND p.target_count=(SELECT count(*) FROM pq_target WHERE plan_id=p.plan_id) AND p.target_count<=l.max_targets
 AND (SELECT count(*) FROM pq_plan)<=l.max_preparations
 AND length(p.members_body)+length(p.plan_body)+length(NEW.audit_body)+length(NEW.notification_body)
 +coalesce((SELECT sum(length(binding_body)+length(dispatch_body)) FROM pq_target WHERE plan_id=p.plan_id),0)<=l.max_payload_bytes
 AND json_type(p.members_body,'$.preparations')='array' AND json_type(p.members_body,'$.submissions')='array' AND json_type(p.members_body,'$.executions')='array'
 AND json_array_length(p.members_body,'$.preparations')=(SELECT count(*) FROM pq_expected_preparation WHERE plan_id=p.plan_id)
 AND json_array_length(p.members_body,'$.submissions')=(SELECT count(*) FROM pq_expected_submission WHERE plan_id=p.plan_id)
 AND json_array_length(p.members_body,'$.executions')=(SELECT count(*) FROM pq_expected_execution WHERE plan_id=p.plan_id))
 THEN RAISE(ABORT,'qualification_seal_projection_or_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT controller_authority,controller_database FROM pq_expected_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM pq_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT controller_authority,controller_database FROM pq_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM pq_expected_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT registration_id FROM pq_expected_preparation WHERE plan_id=NEW.plan_id
 EXCEPT SELECT value FROM pq_plan p,json_each(p.members_body,'$.preparations') WHERE p.plan_id=NEW.plan_id)
 OR EXISTS(SELECT submission_id FROM pq_expected_submission WHERE plan_id=NEW.plan_id
 EXCEPT SELECT value FROM pq_plan p,json_each(p.members_body,'$.submissions') WHERE p.plan_id=NEW.plan_id)
 OR EXISTS(SELECT execution_id,binding_digest FROM pq_expected_execution WHERE plan_id=NEW.plan_id
 EXCEPT SELECT json_extract(value,'$.execution_id'),json_extract(value,'$.binding_digest') FROM pq_plan p,json_each(p.members_body,'$.executions') WHERE p.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'qualification_complete_set') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sp_plan s JOIN sp_plan_commit c USING(plan_id) JOIN pq_plan p USING(plan_id)
 WHERE s.plan_id=NEW.plan_id AND s.target_count=p.target_count AND s.plan_digest=p.plan_digest AND s.plan_body=p.plan_body)
 OR EXISTS(SELECT target_id,binding_body FROM pq_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM pq_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'qualification_receiver_plan') END;
END;
CREATE VIEW pq_latest AS SELECT o.* FROM pq_observation o WHERE NOT EXISTS(SELECT 1 FROM pq_observation n
 WHERE n.registration_id=o.registration_id AND (n.revision>o.revision OR(n.revision=o.revision AND n.protection_revision>o.protection_revision)));
CREATE VIEW pq_current AS SELECT p.registration_id,p.run_id,p.generation,o.revision,o.protection_revision,
 CASE WHEN EXISTS(SELECT 1 FROM pq_fault f WHERE f.registration_id=p.registration_id) THEN 'invalidated'
 WHEN o.state='applied' THEN 'observed_applied' ELSE 'pending' END AS qualification FROM p1_preparation p LEFT JOIN pq_latest o USING(registration_id);
CREATE VIEW pq_pending_protection AS SELECT t.* FROM pq_target t JOIN pq_commit c USING(plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=t.plan_id AND o.target_id=t.target_id AND o.state='applied');
