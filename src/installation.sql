CREATE TABLE installation_identity (
  singleton INTEGER PRIMARY KEY CHECK (singleton=1),
  host_installation_id TEXT NOT NULL UNIQUE,
  authority_service_id TEXT NOT NULL UNIQUE,
  database_instance_id TEXT NOT NULL UNIQUE,
  installation_epoch TEXT NOT NULL,
  directory_identity TEXT NOT NULL,
  schema_digest TEXT NOT NULL
) STRICT;
CREATE TRIGGER installation_identity_update BEFORE UPDATE ON installation_identity BEGIN SELECT RAISE(ABORT,'immutable_identity'); END;
CREATE TRIGGER installation_identity_delete BEFORE DELETE ON installation_identity BEGIN SELECT RAISE(ABORT,'immutable_identity'); END;

CREATE TABLE installation_client_registration (
  client_registration_id TEXT PRIMARY KEY,
  policy_body BLOB NOT NULL CHECK(length(policy_body) BETWEEN 1 AND 65536),
  policy_digest TEXT NOT NULL
) STRICT;
CREATE TABLE installation_client_revocation (
  client_registration_id TEXT PRIMARY KEY REFERENCES installation_client_registration(client_registration_id),
  operation_id TEXT NOT NULL UNIQUE
) STRICT;
CREATE TRIGGER installation_client_registration_update BEFORE UPDATE ON installation_client_registration BEGIN SELECT RAISE(ABORT,'immutable_client'); END;
CREATE TRIGGER installation_client_registration_delete BEFORE DELETE ON installation_client_registration BEGIN SELECT RAISE(ABORT,'immutable_client'); END;
CREATE TRIGGER installation_client_revocation_update BEFORE UPDATE ON installation_client_revocation BEGIN SELECT RAISE(ABORT,'immutable_client'); END;
CREATE TRIGGER installation_client_revocation_delete BEFORE DELETE ON installation_client_revocation BEGIN SELECT RAISE(ABORT,'immutable_client'); END;

CREATE TABLE installation_validation_policy (
  policy_id TEXT PRIMARY KEY,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 65536),
  body_digest TEXT NOT NULL
) STRICT;
CREATE TABLE installation_validation_policy_revocation (
  policy_id TEXT PRIMARY KEY REFERENCES installation_validation_policy(policy_id),
  operation_id TEXT NOT NULL UNIQUE
) STRICT;
CREATE TRIGGER installation_validation_policy_update BEFORE UPDATE ON installation_validation_policy BEGIN SELECT RAISE(ABORT,'immutable_validation_policy'); END;
CREATE TRIGGER installation_validation_policy_delete BEFORE DELETE ON installation_validation_policy BEGIN SELECT RAISE(ABORT,'immutable_validation_policy'); END;
CREATE TRIGGER installation_validation_policy_revocation_update BEFORE UPDATE ON installation_validation_policy_revocation BEGIN SELECT RAISE(ABORT,'immutable_validation_policy'); END;
CREATE TRIGGER installation_validation_policy_revocation_delete BEFORE DELETE ON installation_validation_policy_revocation BEGIN SELECT RAISE(ABORT,'immutable_validation_policy'); END;

CREATE TABLE installation_platform_qualification (
  profile_id TEXT PRIMARY KEY,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 65536),
  body_digest TEXT NOT NULL
) STRICT;
CREATE TABLE installation_platform_qualification_revocation (
  profile_id TEXT PRIMARY KEY REFERENCES installation_platform_qualification(profile_id),
  operation_id TEXT NOT NULL UNIQUE
) STRICT;
CREATE TRIGGER installation_platform_qualification_update BEFORE UPDATE ON installation_platform_qualification BEGIN SELECT RAISE(ABORT,'immutable_platform_qualification'); END;
CREATE TRIGGER installation_platform_qualification_delete BEFORE DELETE ON installation_platform_qualification BEGIN SELECT RAISE(ABORT,'immutable_platform_qualification'); END;
CREATE TRIGGER installation_platform_qualification_revocation_update BEFORE UPDATE ON installation_platform_qualification_revocation BEGIN SELECT RAISE(ABORT,'immutable_platform_qualification'); END;
CREATE TRIGGER installation_platform_qualification_revocation_delete BEFORE DELETE ON installation_platform_qualification_revocation BEGIN SELECT RAISE(ABORT,'immutable_platform_qualification'); END;

CREATE TABLE import_operation (
  operation_id TEXT PRIMARY KEY,
  host_installation_id TEXT NOT NULL REFERENCES installation_identity(host_installation_id),
  client_registration_id TEXT NOT NULL,
  import_request_id TEXT NOT NULL,
  target_authority_service_id TEXT NOT NULL,
  intent_digest TEXT NOT NULL,
  intent_body BLOB NOT NULL CHECK(length(intent_body)<=65536),
  release_authorization_id TEXT GENERATED ALWAYS AS (json_extract(CAST(intent_body AS TEXT),'$.release_authorization_ref.object_id')) VIRTUAL NOT NULL REFERENCES trust_release_authorization(authorization_id),
  validation_policy_id TEXT GENERATED ALWAYS AS (json_extract(CAST(intent_body AS TEXT),'$.validation_policy_ref.object_id')) VIRTUAL NOT NULL REFERENCES installation_validation_policy(policy_id),
  UNIQUE(host_installation_id,client_registration_id,import_request_id),
  FOREIGN KEY(operation_id) REFERENCES import_current(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER import_operation_update BEFORE UPDATE ON import_operation BEGIN SELECT RAISE(ABORT,'immutable_import'); END;
CREATE TRIGGER import_operation_delete BEFORE DELETE ON import_operation BEGIN SELECT RAISE(ABORT,'immutable_import'); END;
CREATE TRIGGER import_operation_policy BEFORE INSERT ON import_operation BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM installation_validation_policy p,installation_identity i
    WHERE p.policy_id=NEW.validation_policy_id
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.validation_policy_ref.kind')='validation_policy'
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.validation_policy_ref.authority_service_id')=i.authority_service_id
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.validation_policy_ref.database_instance_id')=i.database_instance_id
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.validation_policy_ref.revision')='1'
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.validation_policy_ref.digest')=p.body_digest
  ) THEN RAISE(ABORT,'import_validation_policy_binding') END;
END;
CREATE TRIGGER import_operation_release BEFORE INSERT ON import_operation BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM trust_release_authorization a,installation_identity i
    WHERE a.authorization_id=NEW.release_authorization_id
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.release_authorization_ref.kind')='release_authorization'
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.release_authorization_ref.authority_service_id')=i.authority_service_id
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.release_authorization_ref.database_instance_id')=i.database_instance_id
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.release_authorization_ref.revision')='1'
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.release_authorization_ref.digest')=a.body_digest
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.package_digest')=json_extract(CAST(a.body AS TEXT),'$.package_digest')
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.package_bytes')=json_extract(CAST(a.body AS TEXT),'$.package_bytes')
      AND json_extract(CAST(NEW.intent_body AS TEXT),'$.expected_manifest_digest')=json_extract(CAST(a.body AS TEXT),'$.expected_manifest_digest')
  ) THEN RAISE(ABORT,'import_release_binding') END;
END;

CREATE TABLE import_event (
  operation_id TEXT NOT NULL REFERENCES import_operation(operation_id),
  revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 1056),
  event_id TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL CHECK(state IN ('accepted','copying','validating','sealing','sealed','indeterminate','cancelled','rejected')),
  reason_code TEXT,
  detail_body BLOB NOT NULL CHECK(length(detail_body)<=4096),
  detail_digest TEXT NOT NULL,
  copy_operation_id TEXT GENERATED ALWAYS AS (CASE WHEN state='copying' THEN operation_id END) VIRTUAL,
  copy_revision INTEGER GENERATED ALWAYS AS (CASE WHEN state='copying' THEN revision END) VIRTUAL,
  validated_operation_id TEXT GENERATED ALWAYS AS (CASE WHEN state='validating' THEN operation_id END) VIRTUAL,
  validated_revision INTEGER GENERATED ALWAYS AS (CASE WHEN state='validating' THEN revision END) VIRTUAL,
  sealing_operation_id TEXT GENERATED ALWAYS AS (CASE WHEN state='sealing' THEN operation_id END) VIRTUAL,
  sealing_revision INTEGER GENERATED ALWAYS AS (CASE WHEN state='sealing' THEN revision END) VIRTUAL,
  sealed_operation_id TEXT GENERATED ALWAYS AS (CASE WHEN state='sealed' THEN operation_id END) VIRTUAL,
  sealed_revision INTEGER GENERATED ALWAYS AS (CASE WHEN state='sealed' THEN revision END) VIRTUAL,
  PRIMARY KEY(operation_id,revision),
  FOREIGN KEY(copy_operation_id,copy_revision) REFERENCES import_copy_attempt(operation_id,revision) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(validated_operation_id,validated_revision) REFERENCES import_copy_receipt(operation_id,result_revision) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(sealing_operation_id,sealing_revision) REFERENCES import_sealing_attempt(operation_id,revision) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(sealed_operation_id,sealed_revision) REFERENCES artifact_intake(operation_id,sealed_revision) DEFERRABLE INITIALLY DEFERRED,
  CHECK ((state IN ('accepted','copying','validating','sealing','sealed') AND reason_code IS NULL) OR
    (reason_code IS NOT NULL AND ((state='cancelled' AND reason_code='operator_cancelled') OR
    (state='indeterminate' AND reason_code='storage_unknown') OR
    (state='rejected' AND reason_code IN ('content_mismatch','invalid_archive','trust_denied','capacity','source_unavailable')))))
) STRICT;
CREATE TABLE import_current (
  operation_id TEXT PRIMARY KEY REFERENCES import_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
  revision INTEGER NOT NULL,
  FOREIGN KEY(operation_id,revision) REFERENCES import_event(operation_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER import_event_insert BEFORE INSERT ON import_event BEGIN
  SELECT CASE WHEN NEW.revision=1 AND (NEW.state<>'accepted' OR EXISTS(SELECT 1 FROM import_current WHERE operation_id=NEW.operation_id))
    THEN RAISE(ABORT,'import_initial_state') END;
  SELECT CASE WHEN NEW.revision>1 AND NOT EXISTS (
    SELECT 1 FROM import_current c JOIN import_event e USING(operation_id,revision)
    WHERE c.operation_id=NEW.operation_id AND c.revision+1=NEW.revision AND (
      (e.state='accepted' AND NEW.state IN ('copying','cancelled','rejected','indeterminate')) OR
      (e.state='copying' AND NEW.state IN ('copying','validating','cancelled','rejected','indeterminate')) OR
      (e.state='validating' AND NEW.state IN ('sealing','cancelled','rejected','indeterminate')) OR
      (e.state='sealing' AND NEW.state IN ('sealing','sealed','cancelled','rejected','indeterminate'))))
    THEN RAISE(ABORT,'import_state_transition') END;
END;
CREATE TRIGGER import_event_update BEFORE UPDATE ON import_event BEGIN SELECT RAISE(ABORT,'immutable_import_event'); END;
CREATE TRIGGER import_event_delete BEFORE DELETE ON import_event BEGIN SELECT RAISE(ABORT,'immutable_import_event'); END;
CREATE TRIGGER import_current_insert BEFORE INSERT ON import_current WHEN NEW.revision<>1 BEGIN SELECT RAISE(ABORT,'import_initial_revision'); END;
CREATE TRIGGER import_current_update BEFORE UPDATE ON import_current WHEN NEW.operation_id<>OLD.operation_id OR NEW.revision<>OLD.revision+1
BEGIN SELECT RAISE(ABORT,'import_revision'); END;
CREATE TRIGGER import_current_delete BEFORE DELETE ON import_current BEGIN SELECT RAISE(ABORT,'immutable_import_current'); END;
CREATE TRIGGER import_event_adopt AFTER INSERT ON import_event BEGIN
  INSERT INTO import_current(operation_id,revision) SELECT NEW.operation_id,1 WHERE NEW.revision=1;
  UPDATE import_current SET revision=NEW.revision WHERE operation_id=NEW.operation_id AND NEW.revision>1;
END;

CREATE TABLE import_copy_attempt (
  operation_id TEXT NOT NULL REFERENCES import_operation(operation_id),
  revision INTEGER NOT NULL,
  spool_id TEXT NOT NULL UNIQUE,
  PRIMARY KEY(operation_id,revision),
  FOREIGN KEY(operation_id,revision) REFERENCES import_event(operation_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER import_copy_attempt_insert BEFORE INSERT ON import_copy_attempt WHEN NOT EXISTS (
  SELECT 1 FROM import_event WHERE operation_id=NEW.operation_id AND revision=NEW.revision AND state='copying')
BEGIN SELECT RAISE(ABORT,'import_copy_state'); END;
CREATE TRIGGER import_copy_attempt_update BEFORE UPDATE ON import_copy_attempt BEGIN SELECT RAISE(ABORT,'immutable_copy_attempt'); END;
CREATE TRIGGER import_copy_attempt_delete BEFORE DELETE ON import_copy_attempt BEGIN SELECT RAISE(ABORT,'immutable_copy_attempt'); END;
CREATE TABLE import_copy_receipt (
  operation_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  result_revision INTEGER NOT NULL,
  package_digest TEXT NOT NULL,
  package_bytes TEXT NOT NULL,
  PRIMARY KEY(operation_id,revision),
  UNIQUE(operation_id,result_revision),
  FOREIGN KEY(operation_id,revision) REFERENCES import_copy_attempt(operation_id,revision),
  FOREIGN KEY(operation_id,result_revision) REFERENCES import_event(operation_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER import_copy_receipt_insert BEFORE INSERT ON import_copy_receipt WHEN NEW.result_revision<>NEW.revision+1 OR NOT EXISTS (
  SELECT 1 FROM import_event WHERE operation_id=NEW.operation_id AND revision=NEW.result_revision AND state='validating')
BEGIN SELECT RAISE(ABORT,'import_copy_result_state'); END;
CREATE TRIGGER import_copy_receipt_update BEFORE UPDATE ON import_copy_receipt BEGIN SELECT RAISE(ABORT,'immutable_copy_receipt'); END;
CREATE TRIGGER import_copy_receipt_delete BEFORE DELETE ON import_copy_receipt BEGIN SELECT RAISE(ABORT,'immutable_copy_receipt'); END;

CREATE TABLE import_validation_attempt (
  validation_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  copy_revision INTEGER NOT NULL,
  UNIQUE(validation_id,operation_id,copy_revision),
  FOREIGN KEY(operation_id,copy_revision) REFERENCES import_copy_receipt(operation_id,result_revision)
) STRICT;
CREATE TRIGGER import_validation_attempt_insert BEFORE INSERT ON import_validation_attempt WHEN NOT EXISTS (
  SELECT 1 FROM import_current c JOIN import_event e USING(operation_id,revision)
  WHERE c.operation_id=NEW.operation_id AND c.revision=NEW.copy_revision AND e.state='validating')
BEGIN SELECT RAISE(ABORT,'import_validation_state'); END;
CREATE TRIGGER import_validation_attempt_update BEFORE UPDATE ON import_validation_attempt BEGIN SELECT RAISE(ABORT,'immutable_validation_attempt'); END;
CREATE TRIGGER import_validation_attempt_delete BEFORE DELETE ON import_validation_attempt BEGIN SELECT RAISE(ABORT,'immutable_validation_attempt'); END;
CREATE TABLE import_validation_result (
  validation_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  copy_revision INTEGER NOT NULL,
  report_body BLOB NOT NULL CHECK(length(report_body)<=12582912),
  report_digest TEXT NOT NULL,
  UNIQUE(operation_id,copy_revision),
  UNIQUE(validation_id,operation_id,copy_revision),
  FOREIGN KEY(validation_id,operation_id,copy_revision) REFERENCES import_validation_attempt(validation_id,operation_id,copy_revision)
) STRICT;
CREATE TRIGGER import_validation_result_insert BEFORE INSERT ON import_validation_result WHEN NOT EXISTS (
  SELECT 1 FROM import_current c JOIN import_event e USING(operation_id,revision)
  WHERE c.operation_id=NEW.operation_id AND c.revision=NEW.copy_revision AND e.state='validating')
BEGIN SELECT RAISE(ABORT,'import_validation_state'); END;
CREATE TRIGGER import_validation_result_update BEFORE UPDATE ON import_validation_result BEGIN SELECT RAISE(ABORT,'immutable_validation_result'); END;
CREATE TRIGGER import_validation_result_delete BEFORE DELETE ON import_validation_result BEGIN SELECT RAISE(ABORT,'immutable_validation_result'); END;

CREATE TABLE import_preparation_attempt (
  preparation_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  copy_revision INTEGER NOT NULL,
  validation_id TEXT NOT NULL,
  policy_body BLOB NOT NULL CHECK(length(policy_body) BETWEEN 1 AND 65536),
  policy_digest TEXT NOT NULL,
  release_authorization_id TEXT GENERATED ALWAYS AS (json_extract(CAST(policy_body AS TEXT),'$.release_authorization_ref.object_id')) VIRTUAL NOT NULL REFERENCES trust_release_authorization(authorization_id),
  FOREIGN KEY(validation_id,operation_id,copy_revision) REFERENCES import_validation_result(validation_id,operation_id,copy_revision)
) STRICT;
CREATE TRIGGER import_preparation_attempt_insert BEFORE INSERT ON import_preparation_attempt BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM import_current c JOIN import_event e USING(operation_id,revision)
    WHERE c.operation_id=NEW.operation_id AND c.revision=NEW.copy_revision AND e.state='validating') THEN RAISE(ABORT,'preparation_state') END;
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM trust_release_authorization a,installation_identity i
    WHERE a.authorization_id=NEW.release_authorization_id
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.kind')='release_authorization'
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.authority_service_id')=i.authority_service_id
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.database_instance_id')=i.database_instance_id
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.revision')='1'
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.digest')=a.body_digest) THEN RAISE(ABORT,'preparation_release') END;
END;
CREATE TRIGGER import_preparation_attempt_update BEFORE UPDATE ON import_preparation_attempt BEGIN SELECT RAISE(ABORT,'immutable_preparation_attempt'); END;
CREATE TRIGGER import_preparation_attempt_delete BEFORE DELETE ON import_preparation_attempt BEGIN SELECT RAISE(ABORT,'immutable_preparation_attempt'); END;
CREATE TABLE import_preparation_result (
  preparation_id TEXT PRIMARY KEY REFERENCES import_preparation_attempt(preparation_id),
  status TEXT NOT NULL CHECK(status IN ('prepared','failed','obsolete')),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 65536),
  body_digest TEXT NOT NULL
) STRICT;
CREATE TRIGGER import_preparation_result_insert BEFORE INSERT ON import_preparation_result WHEN NEW.status='prepared' BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM import_preparation_attempt a JOIN import_current c USING(operation_id) JOIN import_event e USING(operation_id,revision)
    WHERE a.preparation_id=NEW.preparation_id AND c.revision=a.copy_revision AND e.state='validating'
      AND json_extract(CAST(NEW.body AS TEXT),'$.content_directory')=a.preparation_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.sealed')=0
      AND json_extract(CAST(NEW.body AS TEXT),'$.directory_durability')='unqualified'
      AND json_extract(CAST(NEW.body AS TEXT),'$.file_flush_completed')=1) THEN RAISE(ABORT,'preparation_result_state') END;
END;
CREATE TRIGGER import_preparation_result_update BEFORE UPDATE ON import_preparation_result BEGIN SELECT RAISE(ABORT,'immutable_preparation_result'); END;
CREATE TRIGGER import_preparation_result_delete BEFORE DELETE ON import_preparation_result BEGIN SELECT RAISE(ABORT,'immutable_preparation_result'); END;
