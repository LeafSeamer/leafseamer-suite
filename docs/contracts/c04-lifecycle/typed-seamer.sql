-- 类型化继续运行计划的依赖原件与执行同事务封存。
CREATE TABLE typed_execution_source(
 execution_id TEXT PRIMARY KEY NOT NULL REFERENCES execution(execution_id),
 snapshot_id TEXT NOT NULL REFERENCES ingress_snapshot(snapshot_id),
 definition_version TEXT NOT NULL,
 artifact_ref_body BLOB NOT NULL CHECK(json_valid(artifact_ref_body)),
 input_ref_body BLOB NOT NULL CHECK(json_valid(input_ref_body)),
 parameters_ref_body BLOB NOT NULL CHECK(json_valid(parameters_ref_body)),
 parameters_body BLOB NOT NULL CHECK(json_valid(parameters_body)),
 clock_body BLOB NOT NULL CHECK(json_valid(clock_body))
) STRICT;
CREATE TRIGGER typed_execution_source_update BEFORE UPDATE ON typed_execution_source BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_execution_source_delete BEFORE DELETE ON typed_execution_source BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_source_id_immutable BEFORE UPDATE OF typed_source_id ON execution
 WHEN NEW.typed_source_id IS NOT OLD.typed_source_id BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_submission_identity_immutable BEFORE UPDATE ON command_submission
 WHEN NEW.issuer_epoch IS NOT OLD.issuer_epoch OR NEW.request_key_body IS NOT OLD.request_key_body
 BEGIN SELECT RAISE(ABORT,'immutable_typed_identity'); END;
CREATE TRIGGER typed_plan_source_seal BEFORE UPDATE OF sealed ON execution_plan_set
 WHEN NEW.sealed=1 AND EXISTS(SELECT 1 FROM execution WHERE execution_id=NEW.execution_id AND typed_source_id IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM typed_execution_source s JOIN execution e USING(execution_id)
 WHERE e.execution_id=NEW.execution_id AND e.typed_source_id=s.execution_id)
 BEGIN SELECT RAISE(ABORT,'typed_source_required_at_seal'); END;
CREATE TRIGGER typed_execution_required BEFORE INSERT ON execution
 WHEN NEW.origin_kind='trigger' AND EXISTS(SELECT 1 FROM rc_request WHERE run_id=NEW.run_id AND generation=NEW.arm_generation)
 BEGIN
 SELECT CASE WHEN NEW.typed_source_id IS NOT NEW.execution_id OR NOT json_valid(NEW.binding_body)
 OR json_extract(NEW.binding_body,'$.binding_version') IS NOT 'continuation-execution/0.1.0-draft.1'
 OR json_extract(NEW.binding_body,'$.authorization_mode') IS NOT 'continuation'
 OR json_extract(NEW.binding_body,'$.execution_id') IS NOT NEW.execution_id
 OR json_extract(NEW.binding_body,'$.run_id') IS NOT NEW.run_id
 OR json_extract(NEW.binding_body,'$.arm_generation') IS NOT NEW.arm_generation
 OR json_extract(NEW.binding_body,'$.binding_digest') IS NOT NEW.binding_digest
 OR json_extract(NEW.binding_body,'$.plan_digest') IS NOT NEW.plan_digest
 OR json_extract(NEW.binding_body,'$.origin.kind') IS NOT 'trigger'
 OR json_extract(NEW.binding_body,'$.origin.decision_id') IS NOT json_extract(NEW.trigger_decision_ref_body,'$.id')
 OR json_extract(NEW.binding_body,'$.origin.decision_digest') IS NOT json_extract(NEW.trigger_decision_ref_body,'$.digest')
 OR json_type(NEW.binding_body,'$.continuations') IS NOT 'array'
 OR json_array_length(NEW.binding_body,'$.continuations')<1
 THEN RAISE(ABORT,'typed_execution_required') END;
END;
CREATE TRIGGER typed_source_binding BEFORE INSERT ON typed_execution_source BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM execution e JOIN ingress_decision d ON d.execution_id=e.execution_id
 JOIN ingress_snapshot s ON s.snapshot_id=d.snapshot_id JOIN run r ON r.run_id=e.run_id JOIN storage_scope sc ON sc.singleton=1
 WHERE e.execution_id=NEW.execution_id AND e.typed_source_id=NEW.execution_id AND NEW.snapshot_id=s.snapshot_id
 AND NEW.definition_version=r.version
 AND json_extract(e.binding_body,'$.scope.authority_service_id')=sc.authority_id
 AND json_extract(e.binding_body,'$.scope.database_instance_id')=sc.database_id
 AND json(NEW.artifact_ref_body)=json(json_extract(e.binding_body,'$.artifact_ref'))
 AND json(NEW.input_ref_body)=json(json_extract(e.binding_body,'$.input_snapshot_ref'))
 AND json_extract(NEW.input_ref_body,'$.object_id')=s.snapshot_id AND json_extract(NEW.input_ref_body,'$.digest')=s.digest
 AND json(NEW.parameters_ref_body)=json(json_extract(e.binding_body,'$.resolved_parameters_ref'))
 AND json(NEW.clock_body)=json(json_extract(e.binding_body,'$.clock')))
 THEN RAISE(ABORT,'typed_source_binding') END;
END;
CREATE TRIGGER typed_submission_body BEFORE INSERT ON command_submission BEGIN
 SELECT CASE WHEN NOT json_valid(NEW.request_body)
 OR json_extract(NEW.request_key_body,'$.issuer_id') IS NOT NEW.issuer_id
 OR json_extract(NEW.request_key_body,'$.issuer_epoch') IS NOT NEW.issuer_epoch
 OR json_extract(NEW.request_key_body,'$.principal_id') IS NOT NEW.principal_id
 OR json_extract(NEW.request_key_body,'$.request_epoch') IS NOT NEW.request_epoch
 OR json_extract(NEW.request_key_body,'$.operation_id') IS NOT NEW.operation_id
 OR json_extract(NEW.request_key_body,'$.idempotency_key') IS NOT NEW.idempotency_key
 OR json_extract(NEW.request_key_body,'$.target_scope.authority_service_id') IS NOT NEW.target_authority
 OR json_extract(NEW.request_key_body,'$.target_scope.database_instance_id') IS NOT NEW.target_database
 OR json_extract(NEW.request_body,'$.idempotency_key') IS NOT NEW.idempotency_key
 OR json_extract(NEW.request_body,'$.origin') IS NOT 'automation'
 OR json_type(NEW.request_body,'$.parameters') IS NOT 'object'
 OR json_type(NEW.request_body,'$.continuation') IS NOT NULL
 OR NOT EXISTS(SELECT 1 FROM execution e JOIN typed_execution_source src USING(execution_id)
 JOIN cn_step n USING(execution_id) WHERE e.execution_id=NEW.execution_id AND n.step_id=NEW.step_id
 AND json_extract(NEW.request_body,'$.automation_binding.execution_id')=e.execution_id
 AND json_extract(NEW.request_body,'$.automation_binding.step_id')=NEW.step_id
 AND json_extract(NEW.request_body,'$.automation_binding.execution_binding_ref.digest')=e.binding_digest
 AND json_extract(NEW.request_body,'$.automation_binding.continuation.transfer_ref.id')=n.transfer_id
 AND json_extract(NEW.request_body,'$.automation_binding.continuation.adoption_ref.digest')=n.adoption_digest
 AND json(json_extract(NEW.request_body,'$.automation_binding.continuation.grant_ref'))=json(n.grant_ref_body))
 THEN RAISE(ABORT,'typed_submission_body') END;
END;
