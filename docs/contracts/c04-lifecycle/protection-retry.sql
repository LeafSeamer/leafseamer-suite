-- 重新关闭只基于最新失效尝试；原始终态及旧代次选择器不变，不重投动作。
CREATE TABLE sr_attempt(
 plan_id TEXT PRIMARY KEY NOT NULL,root_plan_id TEXT NOT NULL REFERENCES sf_commit(plan_id),attempt_index INTEGER NOT NULL CHECK(attempt_index BETWEEN 1 AND 16),
 previous_plan_id TEXT NOT NULL REFERENCES sp_plan_commit(plan_id),request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL CHECK(length(request_body)>0),plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),UNIQUE(root_plan_id,attempt_index),UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(plan_id) REFERENCES sr_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW sr_attempts AS SELECT p.plan_id AS root_plan_id,p.plan_id,0 AS attempt_index FROM sf_plan p JOIN sf_commit c USING(plan_id)
 UNION ALL SELECT a.root_plan_id,a.plan_id,a.attempt_index FROM sr_attempt a JOIN sr_commit c USING(plan_id);
CREATE VIEW sr_latest AS SELECT a.* FROM sr_attempts a WHERE NOT EXISTS(SELECT 1 FROM sr_attempts b WHERE b.root_plan_id=a.root_plan_id AND b.attempt_index>a.attempt_index);
CREATE VIEW sr_inventory_current AS SELECT p.plan_id FROM sf_plan p WHERE
 json_array_length(p.inventory_body)=(SELECT count(*) FROM sf_expected_member m WHERE m.plan_id=p.plan_id)
 AND NOT EXISTS(SELECT kind,ref,body FROM sf_expected_member WHERE plan_id=p.plan_id
 EXCEPT SELECT json_extract(value,'$.kind'),json_extract(value,'$.ref'),json_extract(value,'$.body') FROM json_each(p.inventory_body))
 AND NOT EXISTS(SELECT controller_authority,controller_database FROM sf_expected_target WHERE plan_id=p.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM sf_target WHERE plan_id=p.plan_id)
 AND NOT EXISTS(SELECT controller_authority,controller_database FROM sf_target WHERE plan_id=p.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM sf_expected_target WHERE plan_id=p.plan_id);
CREATE TRIGGER sr_prestate BEFORE INSERT ON sr_attempt WHEN NOT EXISTS(
 SELECT 1 FROM sr_latest a JOIN sp_observed_summary o USING(plan_id) JOIN sr_inventory_current i ON i.plan_id=a.root_plan_id
 WHERE a.root_plan_id=NEW.root_plan_id AND a.plan_id=NEW.previous_plan_id AND a.attempt_index+1=NEW.attempt_index AND o.observed_state='indeterminate')
 BEGIN SELECT RAISE(ABORT,'retry_requires_latest_invalidated'); END;
CREATE TRIGGER sr_register AFTER INSERT ON sr_attempt BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NULL,NULL,NULL,NEW.plan_id); END;
CREATE TABLE sr_target(
 plan_id TEXT NOT NULL REFERENCES sr_attempt(plan_id),target_id TEXT NOT NULL,controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,
 binding_body BLOB NOT NULL,dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,controller_authority,controller_database),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER sr_target_guard BEFORE INSERT ON sr_target WHEN EXISTS(SELECT 1 FROM sr_commit WHERE plan_id=NEW.plan_id) OR NOT EXISTS(
 SELECT 1 FROM sr_attempt a JOIN sf_plan p ON p.plan_id=a.root_plan_id JOIN storage_scope s ON s.singleton=1 WHERE a.plan_id=NEW.plan_id
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.run_id') IS p.run_id AND json_extract(NEW.binding_body,'$.deny_through_generation') IS p.generation
 AND json_extract(NEW.binding_body,'$.operation_id') IS NEW.target_id AND json_extract(NEW.binding_body,'$.target_set_digest') IS a.plan_digest
 AND json_extract(NEW.dispatch_body,'$.kind')='protect_registered_run' AND CAST(json_extract(NEW.dispatch_body,'$.binding') AS BLOB)=NEW.binding_body)
 BEGIN SELECT RAISE(ABORT,'retry_target_binding'); END;
CREATE TABLE sr_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES sr_attempt(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER sr_commit_guard BEFORE INSERT ON sr_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sr_attempt a JOIN sr_latest p ON p.root_plan_id=a.root_plan_id JOIN sp_observed_summary o ON o.plan_id=p.plan_id
 JOIN sr_inventory_current i ON i.plan_id=a.root_plan_id JOIN p1_limit l ON l.singleton=1
 WHERE a.plan_id=NEW.plan_id AND p.plan_id=a.previous_plan_id AND p.attempt_index+1=a.attempt_index AND o.observed_state='indeterminate'
 AND a.target_count=(SELECT count(*) FROM sr_target WHERE plan_id=a.plan_id) AND a.target_count<=l.max_targets
 AND length(a.request_body)+length(a.plan_body)+length(NEW.audit_body)+length(NEW.notification_body)
 +coalesce((SELECT sum(length(binding_body)+length(dispatch_body)) FROM sr_target WHERE plan_id=a.plan_id),0)<=l.max_payload_bytes)
 THEN RAISE(ABORT,'retry_final_prestate_or_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT t.controller_authority,t.controller_database FROM sf_target t JOIN sr_attempt a ON a.root_plan_id=t.plan_id WHERE a.plan_id=NEW.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM sr_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT controller_authority,controller_database FROM sr_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT t.controller_authority,t.controller_database FROM sf_target t JOIN sr_attempt a ON a.root_plan_id=t.plan_id WHERE a.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'retry_complete_target_set') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sr_attempt a JOIN sp_plan s USING(plan_id) JOIN sp_plan_commit c USING(plan_id)
 WHERE a.plan_id=NEW.plan_id AND s.plan_body=a.plan_body AND s.plan_digest=a.plan_digest AND s.target_count=a.target_count)
 OR EXISTS(SELECT target_id,binding_body FROM sr_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sr_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'retry_receiver_plan') END;
END;
CREATE VIEW sr_all_targets AS SELECT t.plan_id AS root_plan_id,t.* FROM sf_target t JOIN sf_commit c USING(plan_id)
 UNION ALL SELECT a.root_plan_id,t.* FROM sr_target t JOIN sr_attempt a USING(plan_id) JOIN sr_commit c USING(plan_id);
DROP VIEW sf_pending_dispatch;
CREATE VIEW sf_pending_dispatch AS SELECT t.* FROM sr_all_targets t JOIN sr_latest l USING(root_plan_id,plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=t.plan_id AND o.target_id=t.target_id AND o.state='applied');
