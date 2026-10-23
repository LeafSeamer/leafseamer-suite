-- 需要停止的动作终态必须与完整独立保护计划同事务，不伪造来源或准备失效。
CREATE TABLE sf_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,terminal_id TEXT NOT NULL UNIQUE REFERENCES step_terminal(terminal_id) DEFERRABLE INITIALLY DEFERRED,
 execution_id TEXT NOT NULL REFERENCES execution(execution_id),execution_state_before TEXT NOT NULL,step_id TEXT NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 current_generation TEXT NOT NULL,revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,lifecycle_before TEXT NOT NULL,dispatch_before INTEGER NOT NULL,
 active_execution_before TEXT,active_operation_before TEXT,slot_revision TEXT NOT NULL,slot_run TEXT,slot_version TEXT,
 affects_current INTEGER NOT NULL CHECK(affects_current IN (0,1)),latch_id TEXT UNIQUE REFERENCES pause_latch(latch_id) DEFERRABLE INITIALLY DEFERRED,
 outcome TEXT NOT NULL CHECK(outcome IN ('failed','unknown','blocked','expired','cancelled')),
 preparation_head INTEGER NOT NULL CHECK(preparation_head>=0),target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),
 inventory_body BLOB NOT NULL CHECK(json_valid(inventory_body)),plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(plan_id) REFERENCES sf_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER sf_prestate BEFORE INSERT ON sf_plan WHEN NOT EXISTS(
 SELECT 1 FROM execution e JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 JOIN step_state st USING(execution_id) JOIN execution_step_plan p USING(execution_id,step_id)
 WHERE e.execution_id=NEW.execution_id AND e.state=NEW.execution_state_before AND st.step_id=NEW.step_id AND st.outcome='pending' AND e.run_id=NEW.run_id
 AND (NEW.outcome!='failed' OR p.required=1) AND e.arm_generation=NEW.generation AND r.arm_generation=NEW.current_generation
 AND substr('00000000000000000000'||NEW.generation,-20)<=substr('00000000000000000000'||NEW.current_generation,-20)
 AND r.revision=NEW.revision_before AND r.lifecycle=NEW.lifecycle_before AND r.dispatch_eligible=NEW.dispatch_before
 AND r.active_execution_id IS NEW.active_execution_before AND r.active_operation_id IS NEW.active_operation_before
 AND s.revision=NEW.slot_revision AND s.active_run_id IS NEW.slot_run AND s.version IS NEW.slot_version
 AND NEW.affects_current=(r.active_execution_id IS e.execution_id AND r.arm_generation=e.arm_generation AND r.lifecycle!='completed')
 AND ((NEW.affects_current=1 AND NEW.latch_id IS NOT NULL AND NEW.revision_before!='99999999999999999999' AND NEW.revision_after=__NEXT__)
 OR(NEW.affects_current=0 AND NEW.latch_id IS NULL AND NEW.revision_after=NEW.revision_before)))
 BEGIN SELECT RAISE(ABORT,'failure_prestate'); END;
CREATE TRIGGER sf_register AFTER INSERT ON sf_plan BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NULL,NULL,NEW.plan_id); END;
CREATE TRIGGER sf_terminal BEFORE INSERT ON step_terminal BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM execution_step_plan p WHERE p.execution_id=NEW.execution_id AND p.step_id=NEW.step_id
 AND (NEW.outcome IN ('unknown','blocked','expired','cancelled') OR(NEW.outcome='failed' AND p.required=1)))
 THEN CASE WHEN NOT EXISTS(SELECT 1 FROM sf_plan p WHERE p.plan_id=NEW.protection_plan_id AND p.terminal_id=NEW.terminal_id
 AND p.execution_id=NEW.execution_id AND p.step_id=NEW.step_id AND p.run_id=NEW.run_id AND p.outcome=NEW.outcome)
 THEN RAISE(ABORT,'failure_plan_required') END
 ELSE CASE WHEN NEW.protection_plan_id IS NOT NULL THEN RAISE(ABORT,'unexpected_failure_plan') END END;
END;
CREATE VIEW sf_expected_member AS
 SELECT a.plan_id,'preparation' AS kind,p.registration_id AS ref,hex(p.binding_body) AS body FROM sf_plan a JOIN p1_preparation p USING(run_id)
 WHERE substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION ALL SELECT a.plan_id,'execution',e.execution_id,e.binding_digest FROM sf_plan a JOIN execution e USING(run_id)
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION ALL SELECT a.plan_id,'submission',s.submission_id,hex(s.request_body) FROM sf_plan a JOIN execution e USING(run_id) JOIN command_submission s ON s.execution_id=e.execution_id
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20);
CREATE VIEW sf_expected_target AS
 SELECT a.plan_id,p.controller_authority,p.controller_database FROM sf_plan a JOIN p1_preparation p USING(run_id)
 WHERE substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION SELECT a.plan_id,s.target_authority,s.target_database FROM sf_plan a JOIN execution e USING(run_id) JOIN command_submission s ON s.execution_id=e.execution_id
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20);
CREATE TABLE sf_target(
 plan_id TEXT NOT NULL REFERENCES sf_plan(plan_id),target_id TEXT NOT NULL,controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,
 binding_body BLOB NOT NULL,dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,controller_authority,controller_database),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER sf_target_guard BEFORE INSERT ON sf_target WHEN EXISTS(SELECT 1 FROM sf_commit WHERE plan_id=NEW.plan_id) OR NOT EXISTS(
 SELECT 1 FROM sf_plan p JOIN storage_scope s ON s.singleton=1 WHERE p.plan_id=NEW.plan_id
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.run_id') IS p.run_id AND json_extract(NEW.binding_body,'$.deny_through_generation') IS p.generation
 AND json_extract(NEW.binding_body,'$.operation_id') IS NEW.target_id AND json_extract(NEW.binding_body,'$.target_set_digest') IS p.plan_digest
 AND json_extract(NEW.dispatch_body,'$.kind')='protect_registered_run' AND CAST(json_extract(NEW.dispatch_body,'$.binding') AS BLOB)=NEW.binding_body)
 BEGIN SELECT RAISE(ABORT,'failure_target_binding'); END;
CREATE TABLE sf_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES sf_plan(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER sf_commit_guard BEFORE INSERT ON sf_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sf_plan p JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 JOIN step_terminal t ON t.terminal_id=p.terminal_id JOIN execution e ON e.execution_id=p.execution_id
 JOIN step_state st ON st.execution_id=p.execution_id AND st.step_id=p.step_id JOIN p1_limit l ON l.singleton=1
 JOIN transaction_record tx ON tx.tx_id=t.tx_id JOIN event_outbox n ON n.tx_id=tx.tx_id AND n.event_id=tx.event_id
 WHERE p.plan_id=NEW.plan_id AND t.protection_plan_id=p.plan_id AND st.terminal_id=t.terminal_id AND st.outcome=p.outcome
 AND tx.phase='STEP_TERMINAL' AND tx.business_id=t.terminal_id AND tx.run_id=p.run_id
 AND r.revision=p.revision_after AND r.arm_generation=p.current_generation AND r.active_execution_id IS p.active_execution_before AND r.active_operation_id IS p.active_operation_before
 AND s.revision=p.slot_revision AND s.active_run_id IS p.slot_run AND s.version IS p.slot_version
 AND ((p.affects_current=0 AND r.lifecycle=p.lifecycle_before AND r.dispatch_eligible=p.dispatch_before)
 OR(p.affects_current=1 AND r.lifecycle='paused' AND r.dispatch_eligible=0 AND e.state=CASE WHEN p.execution_state_before IN ('prepared','running','paused') THEN CASE p.outcome WHEN 'unknown' THEN 'unknown' WHEN 'failed' THEN 'failed' ELSE 'paused' END ELSE p.execution_state_before END
 AND EXISTS(SELECT 1 FROM pause_latch x WHERE x.latch_id=p.latch_id AND x.run_id=p.run_id AND x.created_revision=p.revision_after AND x.reason='step_terminal_failure' AND x.cleared_start_id IS NULL)))
 AND p.preparation_head=(SELECT coalesce(max(sequence),0) FROM p1_preparation)
 AND p.target_count=(SELECT count(*) FROM sf_target WHERE plan_id=p.plan_id) AND p.target_count<=l.max_targets
 AND (SELECT count(*) FROM sf_plan)<=l.max_plans AND json_type(p.inventory_body)='array'
 AND json_array_length(p.inventory_body)=(SELECT count(*) FROM sf_expected_member WHERE plan_id=p.plan_id) AND json_array_length(p.inventory_body)<=65536
 AND length(p.inventory_body)+length(p.plan_body)+length(NEW.audit_body)+length(NEW.notification_body)
 +coalesce((SELECT sum(length(binding_body)+length(dispatch_body)) FROM sf_target WHERE plan_id=p.plan_id),0)<=l.max_payload_bytes)
 THEN RAISE(ABORT,'failure_final_projection_or_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT kind,ref,body FROM sf_expected_member WHERE plan_id=NEW.plan_id
 EXCEPT SELECT json_extract(value,'$.kind'),json_extract(value,'$.ref'),json_extract(value,'$.body') FROM sf_plan p,json_each(p.inventory_body) WHERE p.plan_id=NEW.plan_id)
 OR EXISTS(SELECT controller_authority,controller_database FROM sf_expected_target WHERE plan_id=NEW.plan_id EXCEPT SELECT controller_authority,controller_database FROM sf_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT controller_authority,controller_database FROM sf_target WHERE plan_id=NEW.plan_id EXCEPT SELECT controller_authority,controller_database FROM sf_expected_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'failure_complete_inventory') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sf_plan p JOIN sp_plan s USING(plan_id) JOIN sp_plan_commit c USING(plan_id)
 WHERE p.plan_id=NEW.plan_id AND s.plan_body=p.plan_body AND s.plan_digest=p.plan_digest AND s.target_count=p.target_count)
 OR EXISTS(SELECT target_id,binding_body FROM sf_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sf_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'failure_receiver_plan') END;
END;
CREATE VIEW sf_pending_dispatch AS SELECT t.* FROM sf_target t JOIN sf_commit c USING(plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=t.plan_id AND o.target_id=t.target_id AND o.state='applied');
