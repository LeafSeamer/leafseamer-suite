-- 布防失败退出只解除准备操作，保持paused、锁存与旧预算；不证明资源释放。
CREATE TABLE aa_stop(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_operation(operation_id),run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,slot_revision TEXT NOT NULL,
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,request_digest TEXT NOT NULL,request_body BLOB NOT NULL,
 first_plan_id TEXT NOT NULL UNIQUE REFERENCES aa_attempt(plan_id) DEFERRABLE INITIALLY DEFERRED,
 inventory_body BLOB NOT NULL CHECK(json_valid(inventory_body)),latch_id TEXT NOT NULL UNIQUE REFERENCES pause_latch(latch_id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(first_plan_id,operation_id) REFERENCES aa_attempt(plan_id,operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER aa_stop_guard BEFORE INSERT ON aa_stop WHEN NOT EXISTS(
 SELECT 1 FROM arm_operation o JOIN arm_register_commit k USING(operation_id) JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 WHERE o.operation_id=NEW.operation_id AND o.run_id=NEW.run_id AND o.generation=NEW.generation AND r.arm_generation=NEW.generation
 AND r.active_operation_id=o.operation_id AND r.active_execution_id IS NULL AND r.dispatch_eligible=0 AND r.lifecycle IN ('disarmed','paused')
 AND r.revision=NEW.revision_before AND NEW.revision_before!='99999999999999999999' AND NEW.revision_after=__NEXT__
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=NEW.slot_revision
 AND NOT EXISTS(SELECT 1 FROM arm_complete WHERE operation_id=o.operation_id))
 BEGIN SELECT RAISE(ABORT,'arm_stop_prestate'); END;
CREATE VIEW aa_expected_member AS
 SELECT a.operation_id,'preparation' AS kind,p.registration_id AS ref,hex(p.binding_body) AS body FROM aa_stop a JOIN p1_preparation p USING(run_id)
 WHERE substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION ALL SELECT a.operation_id,'execution',e.execution_id,e.binding_digest FROM aa_stop a JOIN execution e USING(run_id)
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION ALL SELECT a.operation_id,'submission',s.submission_id,hex(s.request_body) FROM aa_stop a JOIN execution e USING(run_id) JOIN command_submission s USING(execution_id)
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20);
CREATE VIEW aa_inventory_current AS SELECT a.operation_id FROM aa_stop a WHERE json_type(a.inventory_body)='array'
 AND json_array_length(a.inventory_body)=(SELECT count(*) FROM aa_expected_member m WHERE m.operation_id=a.operation_id)
 AND json_array_length(a.inventory_body)<=65536
 AND NOT EXISTS(SELECT kind,ref,body FROM aa_expected_member WHERE operation_id=a.operation_id
 EXCEPT SELECT json_extract(value,'$.kind'),json_extract(value,'$.ref'),json_extract(value,'$.body') FROM json_each(a.inventory_body));
CREATE VIEW aa_expected_target AS
 SELECT a.operation_id,p.controller_authority,p.controller_database FROM aa_stop a JOIN p1_preparation p USING(run_id)
 WHERE substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION SELECT a.operation_id,s.target_authority,s.target_database FROM aa_stop a JOIN execution e USING(run_id) JOIN command_submission s USING(execution_id)
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20);
CREATE TABLE aa_attempt(
 plan_id TEXT PRIMARY KEY NOT NULL,operation_id TEXT NOT NULL REFERENCES aa_stop(operation_id),ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 16),
 previous_plan_id TEXT REFERENCES aa_attempt(plan_id),request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL,plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL,target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),
 UNIQUE(operation_id,ordinal),UNIQUE(request_epoch,actor_body,idempotency_key),UNIQUE(plan_id,operation_id),
 CHECK((ordinal=1)=(previous_plan_id IS NULL)),
 FOREIGN KEY(plan_id) REFERENCES sp_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES aa_attempt_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER aa_attempt_guard BEFORE INSERT ON aa_attempt WHEN NOT EXISTS(
 SELECT 1 FROM aa_stop a JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id) WHERE a.operation_id=NEW.operation_id
 AND r.lifecycle='paused' AND r.dispatch_eligible=0 AND r.active_operation_id=a.operation_id AND r.active_execution_id IS NULL AND r.arm_generation=a.generation
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=a.slot_revision
 AND NOT EXISTS(SELECT 1 FROM aa_exit WHERE operation_id=a.operation_id)
 AND ((NEW.ordinal=1 AND a.first_plan_id=NEW.plan_id AND r.revision=a.revision_after
 AND NEW.request_epoch=a.request_epoch AND NEW.actor_body=a.actor_body AND NEW.idempotency_key=a.idempotency_key AND NEW.request_digest=a.request_digest AND NEW.request_body=a.request_body)
 OR EXISTS(SELECT 1 FROM aa_attempt p JOIN aa_attempt_commit c USING(plan_id) JOIN sp_observed_summary x USING(plan_id)
 WHERE p.plan_id=NEW.previous_plan_id AND p.operation_id=a.operation_id AND p.ordinal+1=NEW.ordinal AND x.observed_state='indeterminate'
 AND NOT EXISTS(SELECT 1 FROM aa_attempt n WHERE n.operation_id=a.operation_id AND n.ordinal>p.ordinal))))
 BEGIN SELECT RAISE(ABORT,'arm_stop_attempt_prestate'); END;
CREATE TRIGGER aa_register_plan AFTER INSERT ON aa_attempt BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NULL,NEW.plan_id); END;
CREATE TABLE aa_target(
 plan_id TEXT NOT NULL REFERENCES aa_attempt(plan_id),target_id TEXT NOT NULL,controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,
 binding_body BLOB NOT NULL CHECK(json_valid(binding_body)),dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,controller_authority,controller_database),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER aa_target_sealed BEFORE INSERT ON aa_target WHEN EXISTS(SELECT 1 FROM aa_attempt_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'arm_stop_targets_sealed'); END;
CREATE TABLE aa_attempt_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES aa_attempt(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER aa_attempt_seal BEFORE INSERT ON aa_attempt_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM aa_attempt t JOIN aa_stop a USING(operation_id) JOIN aa_inventory_current i USING(operation_id)
 JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id) JOIN pause_latch l ON l.latch_id=a.latch_id
 JOIN sp_plan p ON p.plan_id=t.plan_id JOIN sp_plan_commit c ON c.plan_id=t.plan_id JOIN p1_limit lim ON lim.singleton=1
 WHERE t.plan_id=NEW.plan_id AND r.active_operation_id=a.operation_id AND r.active_execution_id IS NULL AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.arm_generation=a.generation AND (t.ordinal!=1 OR r.revision=a.revision_after)
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=a.slot_revision
 AND l.run_id=r.run_id AND l.reason='arm_exit' AND l.created_revision=a.revision_after AND l.cleared_start_id IS NULL
 AND p.plan_digest=t.plan_digest AND p.plan_body=t.plan_body AND p.target_count=t.target_count
 AND t.target_count=(SELECT count(*) FROM aa_target WHERE plan_id=t.plan_id) AND t.target_count<=lim.max_targets
 AND length(a.inventory_body)+length(t.plan_body)+length(t.request_body)+coalesce((SELECT sum(length(binding_body)+length(dispatch_body)) FROM aa_target WHERE plan_id=t.plan_id),0)<=lim.max_payload_bytes)
 THEN RAISE(ABORT,'arm_stop_seal_projection') END;
 SELECT CASE WHEN EXISTS(SELECT controller_authority,controller_database FROM aa_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT e.controller_authority,e.controller_database FROM aa_expected_target e JOIN aa_attempt t USING(operation_id) WHERE t.plan_id=NEW.plan_id)
 OR EXISTS(SELECT e.controller_authority,e.controller_database FROM aa_expected_target e JOIN aa_attempt t USING(operation_id) WHERE t.plan_id=NEW.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM aa_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM aa_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM aa_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'arm_stop_target_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM aa_target x JOIN aa_attempt t USING(plan_id) JOIN aa_stop a USING(operation_id) JOIN storage_scope sc ON sc.singleton=1
 WHERE x.plan_id=NEW.plan_id AND (json_extract(x.binding_body,'$.controller_scope.authority_service_id') IS NOT x.controller_authority
 OR json_extract(x.binding_body,'$.controller_scope.database_instance_id') IS NOT x.controller_database
 OR json_extract(x.binding_body,'$.origin_scope.authority_service_id') IS NOT sc.authority_id OR json_extract(x.binding_body,'$.origin_scope.database_instance_id') IS NOT sc.database_id
 OR json_extract(x.binding_body,'$.operation_id') IS NOT x.target_id OR json_extract(x.binding_body,'$.run_id') IS NOT a.run_id
 OR json_extract(x.binding_body,'$.deny_through_generation') IS NOT a.generation OR json_extract(x.binding_body,'$.target_set_digest') IS NOT t.plan_digest))
 THEN RAISE(ABORT,'arm_stop_target_binding') END;
END;
CREATE VIEW aa_latest_attempt AS SELECT t.* FROM aa_attempt t JOIN aa_attempt_commit c USING(plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM aa_attempt n JOIN aa_attempt_commit k USING(plan_id) WHERE n.operation_id=t.operation_id AND n.ordinal>t.ordinal);
CREATE TABLE aa_exit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES aa_stop(operation_id),plan_id TEXT NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,slot_revision TEXT NOT NULL,
 FOREIGN KEY(plan_id,operation_id) REFERENCES aa_attempt(plan_id,operation_id),
 FOREIGN KEY(operation_id) REFERENCES aa_exit_commit(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER aa_exit_guard BEFORE INSERT ON aa_exit WHEN NOT EXISTS(
 SELECT 1 FROM aa_stop a JOIN aa_latest_attempt t USING(operation_id) JOIN aa_inventory_current i USING(operation_id)
 JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id) JOIN sp_observed_summary x USING(plan_id)
 WHERE a.operation_id=NEW.operation_id AND a.run_id=NEW.run_id AND a.generation=NEW.generation AND t.plan_id=NEW.plan_id
 AND x.observed_state='applied' AND r.lifecycle='paused' AND r.dispatch_eligible=0 AND r.active_operation_id=a.operation_id AND r.active_execution_id IS NULL
 AND r.arm_generation=a.generation AND r.revision=NEW.revision_before AND NEW.revision_before!='99999999999999999999' AND NEW.revision_after=__NEXT__
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=NEW.slot_revision AND s.revision=a.slot_revision)
 BEGIN SELECT RAISE(ABORT,'arm_exit_unconfirmed'); END;
CREATE TABLE aa_exit_pin(
 operation_id TEXT NOT NULL REFERENCES aa_exit(operation_id),plan_id TEXT NOT NULL,target_id TEXT NOT NULL,revision INTEGER NOT NULL CHECK(revision=1),observation_digest TEXT NOT NULL,
 PRIMARY KEY(operation_id,target_id),FOREIGN KEY(plan_id,operation_id) REFERENCES aa_attempt(plan_id,operation_id),
 FOREIGN KEY(plan_id,target_id,revision) REFERENCES sp_observation(plan_id,target_id,revision)
) STRICT;
CREATE TRIGGER aa_pin_guard BEFORE INSERT ON aa_exit_pin WHEN EXISTS(SELECT 1 FROM aa_exit_commit WHERE operation_id=NEW.operation_id)
 OR NOT EXISTS(SELECT 1 FROM aa_exit e JOIN sp_current_observation o ON o.plan_id=e.plan_id WHERE e.operation_id=NEW.operation_id AND e.plan_id=NEW.plan_id
 AND o.target_id=NEW.target_id AND o.revision=NEW.revision AND o.observation_digest=NEW.observation_digest AND o.state='applied')
 BEGIN SELECT RAISE(ABORT,'arm_exit_pin'); END;
CREATE TABLE aa_exit_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES aa_exit(operation_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER aa_exit_seal BEFORE INSERT ON aa_exit_commit WHEN NOT EXISTS(
 SELECT 1 FROM aa_exit e JOIN aa_stop a USING(operation_id) JOIN aa_inventory_current i USING(operation_id) JOIN aa_latest_attempt t USING(operation_id)
 JOIN run r ON r.run_id=e.run_id JOIN activation_slot s USING(definition_id) JOIN sp_observed_summary x ON x.plan_id=e.plan_id
 WHERE e.operation_id=NEW.operation_id AND e.plan_id=t.plan_id AND x.observed_state='applied'
 AND r.lifecycle='paused' AND r.dispatch_eligible=0 AND r.active_operation_id IS NULL AND r.active_execution_id IS NULL
 AND r.revision=e.revision_after AND r.arm_generation=e.generation AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=e.slot_revision
 AND EXISTS(SELECT 1 FROM pause_latch WHERE latch_id=a.latch_id AND cleared_start_id IS NULL)
 AND t.target_count=(SELECT count(*) FROM aa_exit_pin WHERE operation_id=e.operation_id)
 AND NOT EXISTS(SELECT target_id,revision,observation_digest FROM sp_current_observation WHERE plan_id=e.plan_id
 EXCEPT SELECT target_id,revision,observation_digest FROM aa_exit_pin WHERE operation_id=e.operation_id))
 BEGIN SELECT RAISE(ABORT,'arm_exit_final_projection'); END;
CREATE TRIGGER aa_active_arm_release BEFORE UPDATE ON run WHEN OLD.active_operation_id IS NOT NEW.active_operation_id
 AND EXISTS(SELECT 1 FROM arm_operation WHERE operation_id=OLD.active_operation_id)
 AND NOT EXISTS(SELECT 1 FROM arm_complete c WHERE c.operation_id=OLD.active_operation_id AND c.run_id=NEW.run_id AND c.revision_before=OLD.revision
 AND c.revision_after=NEW.revision AND NEW.active_operation_id IS NULL AND NOT EXISTS(SELECT 1 FROM arm_ready_commit WHERE operation_id=c.operation_id))
 AND NOT EXISTS(SELECT 1 FROM aa_exit e WHERE e.operation_id=OLD.active_operation_id AND e.run_id=NEW.run_id AND e.revision_before=OLD.revision
 AND e.revision_after=NEW.revision AND NEW.active_operation_id IS NULL AND NOT EXISTS(SELECT 1 FROM aa_exit_commit WHERE operation_id=e.operation_id))
 BEGIN SELECT RAISE(ABORT,'active_arm_requires_exit'); END;
CREATE TRIGGER aa_no_late_adoption BEFORE INSERT ON arm_receipt WHEN EXISTS(
 SELECT 1 FROM p1_preparation p JOIN aa_stop a ON a.operation_id=p.arm_operation_id WHERE p.registration_id=NEW.registration_id)
 BEGIN SELECT RAISE(ABORT,'arm_stopped_history_only'); END;
