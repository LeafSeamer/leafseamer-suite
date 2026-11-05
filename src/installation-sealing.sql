CREATE TABLE installation_trust_epoch (
  epoch INTEGER PRIMARY KEY CHECK(epoch BETWEEN 1 AND 9007199254740991),
  operation_id TEXT NOT NULL UNIQUE,
  previous_epoch INTEGER REFERENCES installation_trust_epoch(epoch),
  CHECK((epoch=1 AND previous_epoch IS NULL) OR (epoch>1 AND previous_epoch=epoch-1))
) STRICT;
INSERT INTO installation_trust_epoch VALUES (1,'initial',NULL);
CREATE TRIGGER installation_trust_epoch_insert BEFORE INSERT ON installation_trust_epoch WHEN NEW.epoch<>(SELECT max(epoch)+1 FROM installation_trust_epoch)
BEGIN SELECT RAISE(ABORT,'trust_epoch_sequence'); END;
CREATE TRIGGER installation_trust_epoch_update BEFORE UPDATE ON installation_trust_epoch BEGIN SELECT RAISE(ABORT,'immutable_trust_epoch'); END;
CREATE TRIGGER installation_trust_epoch_delete BEFORE DELETE ON installation_trust_epoch BEGIN SELECT RAISE(ABORT,'immutable_trust_epoch'); END;

CREATE TABLE import_sealing_attempt (
  seal_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL REFERENCES import_operation(operation_id),
  revision INTEGER NOT NULL,
  preparation_id TEXT NOT NULL REFERENCES import_preparation_result(preparation_id),
  policy_body BLOB NOT NULL CHECK(length(policy_body) BETWEEN 1 AND 8192),
  policy_digest TEXT NOT NULL,
  verification_id TEXT NOT NULL UNIQUE,
  intake_id TEXT NOT NULL UNIQUE,
  platform_profile_id TEXT GENERATED ALWAYS AS (json_extract(CAST(policy_body AS TEXT),'$.platform_profile_ref.object_id')) VIRTUAL NOT NULL REFERENCES installation_platform_qualification(profile_id),
  release_authorization_id TEXT GENERATED ALWAYS AS (json_extract(CAST(policy_body AS TEXT),'$.release_authorization_ref.object_id')) VIRTUAL NOT NULL REFERENCES trust_release_authorization(authorization_id),
  UNIQUE(operation_id,revision),
  FOREIGN KEY(operation_id,revision) REFERENCES import_event(operation_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER import_sealing_attempt_insert BEFORE INSERT ON import_sealing_attempt BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM import_current c JOIN import_event e USING(operation_id,revision)
    JOIN import_preparation_attempt a ON a.operation_id=c.operation_id JOIN import_preparation_result r USING(preparation_id)
    WHERE c.operation_id=NEW.operation_id AND c.revision=NEW.revision AND e.state='sealing'
      AND a.preparation_id=NEW.preparation_id AND r.status='prepared') THEN RAISE(ABORT,'sealing_state') END;
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM installation_platform_qualification p,trust_release_authorization a,installation_identity i
    WHERE p.profile_id=NEW.platform_profile_id AND a.authorization_id=NEW.release_authorization_id
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.platform_profile_ref.kind')='platform_profile'
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.platform_profile_ref.authority_service_id')=i.authority_service_id
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.platform_profile_ref.database_instance_id')=i.database_instance_id
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.platform_profile_ref.revision')='1'
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.platform_profile_ref.digest')=p.body_digest
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.kind')='release_authorization'
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.authority_service_id')=i.authority_service_id
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.database_instance_id')=i.database_instance_id
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.revision')='1'
      AND json_extract(CAST(NEW.policy_body AS TEXT),'$.release_authorization_ref.digest')=a.body_digest)
    THEN RAISE(ABORT,'sealing_policy_binding') END;
END;
CREATE TRIGGER import_sealing_attempt_update BEFORE UPDATE ON import_sealing_attempt BEGIN SELECT RAISE(ABORT,'immutable_sealing'); END;
CREATE TRIGGER import_sealing_attempt_delete BEFORE DELETE ON import_sealing_attempt BEGIN SELECT RAISE(ABORT,'immutable_sealing'); END;

CREATE TABLE import_seal_verification (
  verification_id TEXT PRIMARY KEY,
  seal_id TEXT NOT NULL UNIQUE REFERENCES import_sealing_attempt(seal_id),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 65536),
  body_digest TEXT NOT NULL
) STRICT;
CREATE TRIGGER import_seal_verification_insert BEFORE INSERT ON import_seal_verification WHEN NOT EXISTS (
  SELECT 1 FROM import_sealing_attempt a JOIN import_current c USING(operation_id) JOIN import_event e USING(operation_id,revision)
  WHERE a.seal_id=NEW.seal_id AND a.verification_id=NEW.verification_id AND a.revision=c.revision AND e.state='sealing')
BEGIN SELECT RAISE(ABORT,'sealing_verification_state'); END;
CREATE TRIGGER import_seal_verification_update BEFORE UPDATE ON import_seal_verification BEGIN SELECT RAISE(ABORT,'immutable_sealing'); END;
CREATE TRIGGER import_seal_verification_delete BEFORE DELETE ON import_seal_verification BEGIN SELECT RAISE(ABORT,'immutable_sealing'); END;

CREATE TABLE artifact_intake (
  intake_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL UNIQUE REFERENCES import_operation(operation_id),
  sealed_revision INTEGER NOT NULL,
  verification_id TEXT NOT NULL UNIQUE REFERENCES import_seal_verification(verification_id),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 8192),
  body_digest TEXT NOT NULL,
  UNIQUE(operation_id,sealed_revision),
  FOREIGN KEY(operation_id,sealed_revision) REFERENCES import_event(operation_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER artifact_intake_insert BEFORE INSERT ON artifact_intake BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM import_seal_verification v JOIN import_sealing_attempt a USING(seal_id)
    JOIN import_current c USING(operation_id) JOIN import_event e ON e.operation_id=c.operation_id AND e.revision=c.revision
    JOIN import_operation o ON o.operation_id=a.operation_id
    JOIN import_preparation_attempt p ON p.preparation_id=a.preparation_id
    JOIN import_validation_result r ON r.validation_id=p.validation_id
    CROSS JOIN installation_identity i
    WHERE v.verification_id=NEW.verification_id AND a.intake_id=NEW.intake_id AND a.operation_id=NEW.operation_id
      AND NEW.sealed_revision=a.revision+1 AND c.revision=NEW.sealed_revision AND e.state='sealed'
      AND json_extract(CAST(NEW.body AS TEXT),'$.intake_id')=NEW.intake_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.import_operation_id')=NEW.operation_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.host_installation_id')=i.host_installation_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.host_trust_epoch')=CAST((SELECT max(epoch) FROM installation_trust_epoch) AS TEXT)
      AND json_extract(CAST(NEW.body AS TEXT),'$.host_trust_epoch')=json_extract(CAST(o.intent_body AS TEXT),'$.host_trust_epoch')
      AND json_extract(CAST(NEW.body AS TEXT),'$.target_authority_service_id')=o.target_authority_service_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.package_bytes')=json_extract(CAST(o.intent_body AS TEXT),'$.package_bytes')
      AND json_extract(CAST(NEW.body AS TEXT),'$.manifest_digest')=json_extract(CAST(r.report_body AS TEXT),'$.manifest_digest')
      AND json_extract(CAST(NEW.body AS TEXT),'$.artifact_set_digest')=json_extract(CAST(r.report_body AS TEXT),'$.artifact_set_digest')
      AND json_extract(CAST(NEW.body AS TEXT),'$.file_inventory_digest')=json_extract(CAST(r.report_body AS TEXT),'$.file_inventory_digest')
      AND json_extract(CAST(NEW.body AS TEXT),'$.dependency_lock_digest')=json_extract(CAST(r.report_body AS TEXT),'$.dependency_lock_digest')
      AND json_extract(CAST(NEW.body AS TEXT),'$.platform_profile_ref')=json_extract(CAST(a.policy_body AS TEXT),'$.platform_profile_ref')
      AND json_extract(CAST(NEW.body AS TEXT),'$.release_authorization_ref')=json_extract(CAST(a.policy_body AS TEXT),'$.release_authorization_ref')
      AND json_extract(CAST(NEW.body AS TEXT),'$.validation_policy_ref')=json_extract(CAST(o.intent_body AS TEXT),'$.validation_policy_ref')
      AND json_extract(CAST(NEW.body AS TEXT),'$.verification_record_ref.kind')='verification'
      AND json_extract(CAST(NEW.body AS TEXT),'$.verification_record_ref.authority_service_id')=i.authority_service_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.verification_record_ref.database_instance_id')=i.database_instance_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.verification_record_ref.revision')='1'
      AND json_extract(CAST(NEW.body AS TEXT),'$.verification_record_ref.object_id')=v.verification_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.verification_record_ref.digest')=v.body_digest)
    THEN RAISE(ABORT,'intake_binding') END;
END;
CREATE TRIGGER artifact_intake_update BEFORE UPDATE ON artifact_intake BEGIN SELECT RAISE(ABORT,'immutable_intake'); END;
CREATE TRIGGER artifact_intake_delete BEFORE DELETE ON artifact_intake BEGIN SELECT RAISE(ABORT,'immutable_intake'); END;
