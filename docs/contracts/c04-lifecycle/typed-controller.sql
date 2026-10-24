-- 全新干净库的受理边界；JSON路径仅负责列对账，Schema/JCS及提供者真实性由可信writer核验。
CREATE TABLE typed_command_source(
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_command(command_id),
 execution_body BLOB NOT NULL CHECK(json_valid(execution_body)),
 adoption_body BLOB NOT NULL CHECK(json_valid(adoption_body)),
 evidence_body BLOB NOT NULL CHECK(json_valid(evidence_body))
) STRICT;
CREATE TRIGGER typed_command_source_u BEFORE UPDATE ON typed_command_source BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_command_source_d BEFORE DELETE ON typed_command_source BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_key_guard BEFORE INSERT ON ca_request_key BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_namespace n JOIN controller_scope s ON s.singleton=1 WHERE n.namespace_id=NEW.namespace_id
 AND n.issuer_id=json_extract(NEW.request_key_body,'$.issuer_id') AND n.issuer_epoch=json_extract(NEW.request_key_body,'$.issuer_epoch')
 AND n.principal_id=json_extract(NEW.request_key_body,'$.principal_id') AND n.request_epoch=json_extract(NEW.request_key_body,'$.request_epoch')
 AND s.authority_service_id=json_extract(NEW.request_key_body,'$.target_scope.authority_service_id')
 AND s.database_instance_id=json_extract(NEW.request_key_body,'$.target_scope.database_instance_id')
 AND NEW.operation_id=json_extract(NEW.request_key_body,'$.operation_id') AND NEW.idempotency_key=json_extract(NEW.request_key_body,'$.idempotency_key')
 AND NEW.device_id=json_extract(NEW.content_body,'$.device_id') AND json_type(NEW.content_body,'$.parameters')='object'
 AND json_type(NEW.content_body,'$.context_id') IS NULL AND json_type(NEW.content_body,'$.idempotency_key') IS NULL
 AND json_type(NEW.content_body,'$.correlation_id') IS NULL AND json_type(NEW.content_body,'$.continuation') IS NULL)
 THEN RAISE(ABORT,'typed_request_key') END;
END;
CREATE TRIGGER typed_adjudication_guard BEFORE INSERT ON ca_adjudication BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_request_key k WHERE k.key_id=NEW.key_id
 AND json(json_extract(NEW.adjudication_body,'$.identity.key'))=json(k.request_key_body)
 AND json_extract(NEW.adjudication_body,'$.identity.request_digest')=k.request_digest
 AND json_extract(NEW.adjudication_body,'$.adjudication_id')=NEW.adjudication_id
 AND json_extract(NEW.adjudication_body,'$.adjudication_digest')=NEW.adjudication_digest
 AND json_extract(NEW.adjudication_body,'$.decision')=NEW.decision
 AND json_extract(NEW.adjudication_body,'$.command_ref.object_id') IS NEW.command_id
 AND json_extract(NEW.adjudication_body,'$.commit_ref.object_id')=NEW.commit_id)
 THEN RAISE(ABORT,'typed_adjudication') END;
END;
CREATE TRIGGER typed_controller_seal BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_request_key k JOIN ca_command_initial i USING(key_id)
 JOIN ce_command e USING(command_id) JOIN typed_command_source t USING(command_id) JOIN cn_command n USING(command_id)
 WHERE k.key_id=NEW.key_id AND k.transport_body IS NOT NULL
 AND json_remove(k.transport_body,'$.context_id','$.idempotency_key','$.correlation_id')=json(k.content_body)
 AND json_extract(k.transport_body,'$.idempotency_key')=k.idempotency_key
 AND e.origin='automation' AND json(e.binding_body)=json(json_extract(k.content_body,'$.automation_binding'))
 AND json(n.binding_body)=json(e.binding_body)
 AND json_extract(e.binding_body,'$.execution_id')=json_extract(t.execution_body,'$.execution_id')
 AND json_extract(e.binding_body,'$.execution_binding_ref.digest')=json_extract(t.execution_body,'$.binding_digest')
 AND n.adoption_digest=json_extract(t.adoption_body,'$.adoption_digest'))
 THEN RAISE(ABORT,'typed_admission_seal') END;
END;
