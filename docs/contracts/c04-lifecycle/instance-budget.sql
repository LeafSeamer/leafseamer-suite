-- 固定实例来源保护区；只有显式验证的来源故障使用此账户，不替任何run代付。
CREATE TABLE ib_pool(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),authority_id TEXT NOT NULL,database_id TEXT NOT NULL,
 arm_profile_digest TEXT NOT NULL REFERENCES arm_capacity(profile_digest),profile_digest TEXT NOT NULL,profile_body BLOB NOT NULL CHECK(json_valid(profile_body)),
 episodes INTEGER NOT NULL CHECK(episodes BETWEEN 1 AND 65536),per_source_episodes INTEGER NOT NULL CHECK(per_source_episodes BETWEEN 1 AND episodes),
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 total_logical_rows INTEGER NOT NULL CHECK(total_logical_rows BETWEEN 1 AND 1000000000000),total_logical_bytes INTEGER NOT NULL CHECK(total_logical_bytes BETWEEN 1 AND 1000000000000),
 total_queue_slots INTEGER NOT NULL CHECK(total_queue_slots BETWEEN 1 AND 1000000000000),total_work_units INTEGER NOT NULL CHECK(total_work_units BETWEEN 1 AND 1000000000000),
 max_row_bytes INTEGER NOT NULL CHECK(max_row_bytes BETWEEN 1 AND 1048576),max_queue_wait_ns TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK(length(max_queue_wait_ns) BETWEEN 1 AND 20 AND max_queue_wait_ns NOT GLOB '*[^0-9]*' AND substr(max_queue_wait_ns,1,1)!='0' AND instr(max_queue_wait_ns,char(0))=0)
) STRICT;
CREATE TRIGGER ib_pool_binding BEFORE INSERT ON ib_pool WHEN NOT EXISTS(
 SELECT 1 FROM storage_scope sc WHERE sc.authority_id=NEW.authority_id AND sc.database_id=NEW.database_id
 AND json_extract(NEW.profile_body,'$.scope.authority_service_id') IS sc.authority_id
 AND json_extract(NEW.profile_body,'$.scope.database_instance_id') IS sc.database_id
 AND json_extract(NEW.profile_body,'$.arm_profile_digest') IS NEW.arm_profile_digest
 AND json_extract(NEW.profile_body,'$.contract_version')='source-instance-budget/0.1.0-draft.1'
 AND json_extract(NEW.profile_body,'$.purpose')='simulation'
 AND json_extract(NEW.profile_body,'$.episodes') IS CAST(NEW.episodes AS TEXT)
 AND json_extract(NEW.profile_body,'$.per_source_episodes') IS CAST(NEW.per_source_episodes AS TEXT)
 AND json_extract(NEW.profile_body,'$.max_row_bytes') IS CAST(NEW.max_row_bytes AS TEXT)
 AND json_extract(NEW.profile_body,'$.max_queue_wait_ns') IS NEW.max_queue_wait_ns)
 OR EXISTS(SELECT 1 FROM protection_plan_registry) OR EXISTS(SELECT 1 FROM lifecycle_operation_identity)
 BEGIN SELECT RAISE(ABORT,'instance_budget_bootstrap_binding'); END;
CREATE TABLE ib_use(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_plan(plan_id),pool_id INTEGER NOT NULL REFERENCES ib_pool(singleton),source_id TEXT NOT NULL REFERENCES ingress_source(source_id),
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 65536),source_ordinal INTEGER NOT NULL CHECK(source_ordinal BETWEEN 1 AND 65536),
 profile_digest TEXT NOT NULL,fault_digest TEXT NOT NULL,plan_digest TEXT NOT NULL,
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 observed_rows INTEGER NOT NULL CHECK(observed_rows>0),observed_bytes INTEGER NOT NULL CHECK(observed_bytes>0),observed_max_row_bytes INTEGER NOT NULL CHECK(observed_max_row_bytes>0),
 elapsed_wait_ns TEXT NOT NULL,measurement_body BLOB NOT NULL CHECK(length(measurement_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(pool_id,ordinal),UNIQUE(pool_id,source_id,source_ordinal),
 FOREIGN KEY(plan_id) REFERENCES pb_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(elapsed_wait_ns) BETWEEN 1 AND 20 AND elapsed_wait_ns NOT GLOB '*[^0-9]*' AND(elapsed_wait_ns='0' OR substr(elapsed_wait_ns,1,1)!='0') AND instr(elapsed_wait_ns,char(0))=0)
) STRICT;
CREATE TRIGGER ib_use_guard BEFORE INSERT ON ib_use WHEN NOT EXISTS(
 SELECT 1 FROM p1_plan q JOIN p1_fault f ON f.fault_id=q.fault_id JOIN p1_commit k ON k.plan_id=q.plan_id
 JOIN protection_plan_registry r ON r.source_plan=q.plan_id JOIN sp_plan_commit sk ON sk.plan_id=q.plan_id JOIN ib_pool p ON p.singleton=NEW.pool_id
 WHERE q.plan_id=NEW.plan_id AND q.source_id=NEW.source_id AND f.source_id=NEW.source_id
 AND f.fault_digest=NEW.fault_digest AND q.plan_digest=NEW.plan_digest AND p.profile_digest=NEW.profile_digest
 AND NEW.ordinal=1+(SELECT count(*) FROM ib_use WHERE pool_id=p.singleton) AND NEW.ordinal<=p.episodes
 AND NEW.source_ordinal=1+(SELECT count(*) FROM ib_use WHERE pool_id=p.singleton AND source_id=NEW.source_id) AND NEW.source_ordinal<=p.per_source_episodes
 AND NEW.observed_rows<=NEW.logical_rows AND NEW.observed_bytes<=NEW.logical_bytes AND NEW.observed_max_row_bytes<=p.max_row_bytes
 AND (length(NEW.elapsed_wait_ns),NEW.elapsed_wait_ns COLLATE BINARY)<(length(p.max_queue_wait_ns),p.max_queue_wait_ns COLLATE BINARY))
 OR EXISTS(SELECT 1 FROM pb_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'instance_charge_binding_or_capacity'); END;
CREATE TRIGGER ib_source_complete BEFORE INSERT ON pb_commit WHEN
 EXISTS(SELECT 1 FROM p1_plan WHERE plan_id=NEW.plan_id) AND NOT EXISTS(SELECT 1 FROM ib_use WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'instance_charge_required'); END;
