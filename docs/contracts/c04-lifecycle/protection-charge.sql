-- 一个共享消费账本覆盖五类保护来源；原预留原件不改写、不退款。
CREATE VIEW pb_expected_account AS
 SELECT p.plan_id,r.run_id,r.generation FROM protection_plan_registry p JOIN p1_run r ON r.plan_id=p.source_plan
 UNION SELECT p.plan_id,q.run_id,q.generation FROM protection_plan_registry p JOIN pq_plan q ON q.plan_id=p.preparation_plan
 UNION SELECT p.plan_id,s.run_id,s.generation FROM protection_plan_registry p JOIN aa_attempt a ON a.plan_id=p.arm_exit_plan JOIN aa_stop s USING(operation_id)
 UNION SELECT p.plan_id,s.run_id,s.generation FROM protection_plan_registry p JOIN sf_plan s ON s.plan_id=p.failure_plan
 UNION SELECT p.plan_id,s.run_id,s.generation FROM protection_plan_registry p JOIN sr_attempt a ON a.plan_id=p.retry_plan JOIN sf_plan s ON s.plan_id=a.root_plan_id;
CREATE VIEW pb_shape AS SELECT a.plan_id,a.run_id,a.generation,
 (SELECT count(*) FROM p1_dependency WHERE run_id=a.run_id) AS dependencies,1 AS runs,
 (SELECT count(*) FROM execution WHERE run_id=a.run_id AND substr('00000000000000000000'||arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS executions,
 (SELECT count(*) FROM p1_preparation WHERE run_id=a.run_id AND substr('00000000000000000000'||generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS preparations,
 (SELECT count(*) FROM command_submission s JOIN execution e USING(execution_id) WHERE s.run_id=a.run_id AND substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS submissions,
 (SELECT count(*) FROM(SELECT p.controller_authority,p.controller_database FROM p1_preparation p WHERE p.run_id=a.run_id AND substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION SELECT s.target_authority,s.target_database FROM command_submission s JOIN execution e USING(execution_id) WHERE s.run_id=a.run_id AND substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20))) AS controller_targets
 FROM pb_expected_account a;
CREATE TABLE pb_use(
 plan_id TEXT NOT NULL REFERENCES protection_plan_registry(plan_id),run_id TEXT NOT NULL,generation TEXT NOT NULL,
 operation_id TEXT NOT NULL REFERENCES arm_budget_reservation(operation_id),ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 1024),
 binding_digest TEXT NOT NULL,profile_digest TEXT NOT NULL,plan_digest TEXT NOT NULL,
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 shape_body BLOB NOT NULL CHECK(json_valid(shape_body)),observed_rows INTEGER NOT NULL CHECK(observed_rows>0),observed_bytes INTEGER NOT NULL CHECK(observed_bytes>0),
 observed_max_row_bytes INTEGER NOT NULL CHECK(observed_max_row_bytes>0),elapsed_wait_ns TEXT NOT NULL,
 measurement_body BLOB NOT NULL CHECK(length(measurement_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(plan_id,run_id,generation),UNIQUE(operation_id,ordinal),UNIQUE(plan_id,operation_id),
 FOREIGN KEY(plan_id) REFERENCES pb_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(elapsed_wait_ns) BETWEEN 1 AND 20 AND elapsed_wait_ns NOT GLOB '*[^0-9]*'
 AND(elapsed_wait_ns='0' OR substr(elapsed_wait_ns,1,1)!='0') AND instr(elapsed_wait_ns,char(0))=0)
) STRICT;
CREATE TRIGGER pb_use_guard BEFORE INSERT ON pb_use WHEN NOT EXISTS(
 SELECT 1 FROM pb_expected_account a JOIN arm_operation o ON o.run_id=a.run_id AND o.generation=a.generation
 JOIN arm_budget_reservation b USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest JOIN sp_plan s ON s.plan_id=a.plan_id
 JOIN sp_plan_commit sk ON sk.plan_id=s.plan_id WHERE a.plan_id=NEW.plan_id AND a.run_id=NEW.run_id AND a.generation=NEW.generation
 AND o.operation_id=NEW.operation_id AND b.profile_digest=NEW.profile_digest AND s.plan_digest=NEW.plan_digest
 AND json_extract(b.budget_body,'$.binding_digest') IS NEW.binding_digest
 AND NEW.ordinal=1+(SELECT count(*) FROM pb_use WHERE operation_id=o.operation_id)
 AND NEW.ordinal<=CAST(json_extract(c.profile_body,'$.episodes') AS INTEGER)
 AND NEW.observed_rows<=NEW.logical_rows AND NEW.observed_bytes<=NEW.logical_bytes
 AND NEW.observed_max_row_bytes<=CAST(json_extract(c.profile_body,'$.max_row_bytes') AS INTEGER)
 AND (length(NEW.elapsed_wait_ns),NEW.elapsed_wait_ns COLLATE BINARY)<(length(json_extract(c.profile_body,'$.max_queue_wait_ns')),json_extract(c.profile_body,'$.max_queue_wait_ns') COLLATE BINARY))
 OR EXISTS(SELECT 1 FROM pb_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'protection_charge_binding_or_capacity'); END;
CREATE TRIGGER pb_shape_guard BEFORE INSERT ON pb_use WHEN NOT EXISTS(
 SELECT 1 FROM pb_shape s JOIN arm_budget_reservation b ON b.operation_id=NEW.operation_id
 WHERE s.plan_id=NEW.plan_id AND s.run_id=NEW.run_id AND s.generation=NEW.generation
 AND json_extract(NEW.shape_body,'$.dependencies') IS CAST(s.dependencies AS TEXT) AND s.dependencies<=CAST(json_extract(b.budget_body,'$.binding.forecast.dependencies') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.runs') IS '1' AND 1<=CAST(json_extract(b.budget_body,'$.binding.forecast.runs') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.executions') IS CAST(s.executions AS TEXT) AND s.executions<=CAST(json_extract(b.budget_body,'$.binding.forecast.executions') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.preparations') IS CAST(s.preparations AS TEXT) AND s.preparations<=CAST(json_extract(b.budget_body,'$.binding.forecast.preparations') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.submissions') IS CAST(s.submissions AS TEXT) AND s.submissions<=CAST(json_extract(b.budget_body,'$.binding.forecast.submissions') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.controller_targets') IS CAST(s.controller_targets AS TEXT) AND s.controller_targets<=CAST(json_extract(b.budget_body,'$.binding.forecast.controller_targets') AS INTEGER)
 AND (SELECT count(*) FROM json_each(NEW.shape_body))=6)
 BEGIN SELECT RAISE(ABORT,'protection_charge_shape'); END;
CREATE TABLE pb_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES protection_plan_registry(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER pb_commit_guard BEFORE INSERT ON pb_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT run_id,generation FROM pb_expected_account WHERE plan_id=NEW.plan_id EXCEPT SELECT run_id,generation FROM pb_use WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT run_id,generation FROM pb_use WHERE plan_id=NEW.plan_id EXCEPT SELECT run_id,generation FROM pb_expected_account WHERE plan_id=NEW.plan_id)
 OR NOT EXISTS(SELECT 1 FROM sp_plan_commit WHERE plan_id=NEW.plan_id)
 OR NOT EXISTS(SELECT 1 FROM pb_expected_account WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_charge_complete_set') END;
END;
