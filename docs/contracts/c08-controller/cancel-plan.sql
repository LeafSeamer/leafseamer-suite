-- 取消动作图与完成原件候选。须经生成器与119表组合；不是生产迁移。
CREATE TABLE cg_plan (
 execution_id TEXT PRIMARY KEY NOT NULL,
 cancellation_id TEXT NOT NULL UNIQUE REFERENCES cv_cancel_commit(cancellation_id),
 ordinary_closure_id TEXT NOT NULL REFERENCES cc_closure(closure_id),
 execution_digest TEXT NOT NULL,
 policy_ref_body BLOB NOT NULL CHECK(length(policy_ref_body)>0),
 protected_hold_ref_body BLOB NOT NULL CHECK(length(protected_hold_ref_body)>0),
 resource_count INTEGER NOT NULL CHECK(resource_count BETWEEN 1 AND 256),
 primitive_count INTEGER NOT NULL CHECK(primitive_count BETWEEN 1 AND 256),
 dependency_count INTEGER NOT NULL CHECK(dependency_count BETWEEN 0 AND 32640),
 plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(execution_id) REFERENCES cg_plan_commit(execution_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cg_resource (
 execution_id TEXT NOT NULL REFERENCES cg_plan(execution_id), resource_key TEXT NOT NULL,
 PRIMARY KEY(execution_id,resource_key)
) STRICT;
CREATE TABLE cg_primitive (
 execution_id TEXT NOT NULL REFERENCES cg_plan(execution_id), primitive_id TEXT NOT NULL,
 position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 256),
 action_ref_body BLOB NOT NULL CHECK(length(action_ref_body)>0),
 parameters_schema_ref_body BLOB NOT NULL CHECK(length(parameters_schema_ref_body)>0),
 parameters_body BLOB NOT NULL CHECK(length(parameters_body)>0),
 completion_policy_ref_body BLOB NOT NULL CHECK(length(completion_policy_ref_body)>0),
 PRIMARY KEY(execution_id,primitive_id), UNIQUE(execution_id,position)
) STRICT;
CREATE TABLE cg_dependency (
 execution_id TEXT NOT NULL, primitive_id TEXT NOT NULL, predecessor_id TEXT NOT NULL,
 PRIMARY KEY(execution_id,primitive_id,predecessor_id),
 FOREIGN KEY(execution_id,primitive_id) REFERENCES cg_primitive(execution_id,primitive_id),
 FOREIGN KEY(execution_id,predecessor_id) REFERENCES cg_primitive(execution_id,primitive_id)
) STRICT;
CREATE TABLE cg_plan_commit (
 execution_id TEXT PRIMARY KEY NOT NULL REFERENCES cg_plan(execution_id),
 provider_ref_body BLOB NOT NULL CHECK(length(provider_ref_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cg_result (
 result_id TEXT PRIMARY KEY NOT NULL, execution_id TEXT NOT NULL, primitive_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('succeeded','failed','unknown')),
 evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('protocol_effect','verified_safe_state','definite_failure','indeterminate')),
 evidence_digest TEXT NOT NULL, evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 completion_policy_ref_body BLOB NOT NULL CHECK(length(completion_policy_ref_body)>0),
 issued_revision TEXT NOT NULL CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*'),
 UNIQUE(execution_id,primitive_id), UNIQUE(result_id,execution_id,primitive_id),
 CHECK((disposition='succeeded' AND evidence_kind IN ('protocol_effect','verified_safe_state')) OR
  (disposition='failed' AND evidence_kind='definite_failure') OR (disposition='unknown' AND evidence_kind='indeterminate')),
 FOREIGN KEY(execution_id,primitive_id) REFERENCES cg_primitive(execution_id,primitive_id),
 FOREIGN KEY(result_id) REFERENCES cg_result_commit(result_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cg_result_member (
 result_id TEXT NOT NULL REFERENCES cg_result(result_id), permit_id TEXT NOT NULL REFERENCES ci_cancel_commit(permit_id),
 PRIMARY KEY(result_id,permit_id)
) STRICT;
CREATE TABLE cg_result_commit (
 result_id TEXT PRIMARY KEY NOT NULL REFERENCES cg_result(result_id),
 provider_ref_body BLOB NOT NULL CHECK(length(provider_ref_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cg_revocation (
 result_id TEXT PRIMARY KEY NOT NULL REFERENCES cg_result_commit(result_id),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cg_dispatch_dependency (
 permit_id TEXT NOT NULL REFERENCES ci_cancel_transmission(permit_id),
 execution_id TEXT NOT NULL, primitive_id TEXT NOT NULL, predecessor_id TEXT NOT NULL, result_id TEXT NOT NULL,
 PRIMARY KEY(permit_id,predecessor_id),
 FOREIGN KEY(execution_id,primitive_id,predecessor_id) REFERENCES cg_dependency(execution_id,primitive_id,predecessor_id),
 FOREIGN KEY(result_id,execution_id,predecessor_id) REFERENCES cg_result(result_id,execution_id,primitive_id),
 FOREIGN KEY(permit_id) REFERENCES ci_cancel_commit(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW cg_stopped AS
 SELECT r.execution_id,r.result_id,'result' source_kind FROM cg_result r
 JOIN cg_result_commit k USING(result_id) WHERE r.disposition!='succeeded'
 UNION ALL SELECT r.execution_id,r.result_id,'revocation' FROM cg_result r JOIN cg_revocation v USING(result_id);
CREATE VIEW cg_valid_success AS SELECT r.* FROM cg_result r JOIN cg_result_commit k USING(result_id)
 WHERE r.disposition='succeeded' AND NOT EXISTS(SELECT 1 FROM cg_revocation v WHERE v.result_id=r.result_id);
CREATE TRIGGER cg_plan_guard BEFORE INSERT ON cg_plan BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel c JOIN cc_cut t USING(cancellation_id)
  JOIN cc_valid_closure h USING(cut_id) WHERE c.cancellation_id=NEW.cancellation_id
  AND c.mode='cooperative' AND t.stage='ordinary' AND h.closure_id=NEW.ordinary_closure_id)
  OR EXISTS(SELECT 1 FROM cc_cut WHERE cancellation_id=NEW.cancellation_id AND stage='all')
  OR EXISTS(SELECT 1 FROM cv_cancel_current WHERE cancellation_id=NEW.cancellation_id AND state!='requested')
  THEN RAISE(ABORT,'plan_not_admissible') END;
END;
CREATE TRIGGER cg_dependency_guard BEFORE INSERT ON cg_dependency BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_primitive p JOIN cg_primitive q USING(execution_id)
  WHERE p.execution_id=NEW.execution_id AND p.primitive_id=NEW.primitive_id
   AND q.primitive_id=NEW.predecessor_id AND q.position<p.position)
  THEN RAISE(ABORT,'plan_not_dag') END;
END;
CREATE TRIGGER cg_plan_seal BEFORE INSERT ON cg_plan_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p WHERE p.execution_id=NEW.execution_id
  AND p.resource_count=(SELECT count(*) FROM cg_resource WHERE execution_id=p.execution_id)
  AND p.primitive_count=(SELECT count(*) FROM cg_primitive WHERE execution_id=p.execution_id)
  AND p.primitive_count=(SELECT max(position) FROM cg_primitive WHERE execution_id=p.execution_id)
  AND p.dependency_count=(SELECT count(*) FROM cg_dependency WHERE execution_id=p.execution_id))
  THEN RAISE(ABORT,'plan_projection_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_plan p WHERE p.execution_id=NEW.execution_id AND
  (NOT EXISTS(SELECT 1 FROM cc_valid_closure WHERE closure_id=p.ordinary_closure_id) OR
   EXISTS(SELECT 1 FROM cc_cut WHERE cancellation_id=p.cancellation_id AND stage='all')))
  THEN RAISE(ABORT,'plan_not_admissible') END;
END;
CREATE TRIGGER cg_prepare_guard BEFORE INSERT ON cc_prepare BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cg_plan_commit k USING(execution_id)
  JOIN cg_primitive a USING(execution_id) WHERE p.execution_id=NEW.execution_id AND
  p.cancellation_id=NEW.cancellation_id AND p.execution_digest=NEW.execution_digest AND
  p.ordinary_closure_id=NEW.ordinary_closure_id AND a.primitive_id=NEW.primitive_id)
  THEN RAISE(ABORT,'prepare_plan_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_stopped WHERE execution_id=NEW.execution_id)
  THEN RAISE(ABORT,'cancel_plan_stopped') END;
END;
CREATE TRIGGER cg_result_guard BEFORE INSERT ON cg_result BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_primitive p JOIN cg_plan_commit k USING(execution_id)
  WHERE p.execution_id=NEW.execution_id AND p.primitive_id=NEW.primitive_id AND
  p.completion_policy_ref_body=NEW.completion_policy_ref_body)
  THEN RAISE(ABORT,'result_policy_binding') END;
 SELECT CASE WHEN NEW.issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  THEN RAISE(ABORT,'result_watermark') END;
END;
CREATE TRIGGER cg_result_seal BEFORE INSERT ON cg_result_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT t.permit_id FROM ci_cancel_transmission t JOIN cg_result r
  ON r.execution_id=t.execution_id AND r.primitive_id=t.primitive_id WHERE r.result_id=NEW.result_id
  EXCEPT SELECT permit_id FROM cg_result_member WHERE result_id=NEW.result_id)
  OR EXISTS(SELECT permit_id FROM cg_result_member WHERE result_id=NEW.result_id
   EXCEPT SELECT t.permit_id FROM ci_cancel_transmission t JOIN cg_result r
   ON r.execution_id=t.execution_id AND r.primitive_id=t.primitive_id WHERE r.result_id=NEW.result_id)
  THEN RAISE(ABORT,'result_transmission_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_result WHERE result_id=NEW.result_id AND disposition='succeeded')
  AND NOT EXISTS(SELECT 1 FROM cg_result_member WHERE result_id=NEW.result_id)
  THEN RAISE(ABORT,'success_without_transmission') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_result WHERE result_id=NEW.result_id AND
  issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue))
  THEN RAISE(ABORT,'result_watermark') END;
END;
CREATE TRIGGER cg_send_guard BEFORE INSERT ON ci_cancel_transmission BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cg_plan_commit k USING(execution_id)
  JOIN cg_primitive a USING(execution_id) WHERE p.execution_id=NEW.execution_id AND
  p.cancellation_id=NEW.cancellation_id AND p.execution_digest=NEW.execution_digest AND a.primitive_id=NEW.primitive_id)
  THEN RAISE(ABORT,'send_plan_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_result WHERE execution_id=NEW.execution_id AND primitive_id=NEW.primitive_id)
  OR EXISTS(SELECT 1 FROM cg_stopped WHERE execution_id=NEW.execution_id)
  THEN RAISE(ABORT,'cancel_plan_stopped') END;
END;
CREATE TRIGGER cg_dispatch_guard BEFORE INSERT ON ci_cancel_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cg_stopped s USING(execution_id)
  WHERE t.permit_id=NEW.permit_id)
  OR EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cg_result r USING(execution_id,primitive_id)
   WHERE t.permit_id=NEW.permit_id)
  THEN RAISE(ABORT,'cancel_plan_stopped') END;
 SELECT CASE WHEN EXISTS(SELECT d.predecessor_id FROM ci_cancel_transmission t
  JOIN cg_dependency d USING(execution_id,primitive_id) WHERE t.permit_id=NEW.permit_id
  EXCEPT SELECT predecessor_id FROM cg_dispatch_dependency WHERE permit_id=NEW.permit_id)
  OR EXISTS(SELECT 1 FROM cg_dispatch_dependency d JOIN ci_cancel_transmission t USING(permit_id)
   LEFT JOIN cg_valid_success r ON r.result_id=d.result_id WHERE d.permit_id=NEW.permit_id AND
   (d.execution_id!=t.execution_id OR d.primitive_id!=t.primitive_id OR r.result_id IS NULL))
  THEN RAISE(ABORT,'dependency_not_satisfied') END;
END;
