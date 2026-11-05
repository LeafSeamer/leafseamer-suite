CREATE TABLE trust_domain (
  trust_domain_id TEXT PRIMARY KEY,
  bootstrap_body BLOB NOT NULL CHECK(length(bootstrap_body)<=65536),
  bootstrap_digest TEXT NOT NULL
) STRICT;
CREATE TABLE trusted_metadata (
  metadata_id TEXT PRIMARY KEY,
  trust_domain_id TEXT NOT NULL REFERENCES trust_domain(trust_domain_id),
  role TEXT NOT NULL,
  epoch INTEGER NOT NULL CHECK(epoch>=0),
  version INTEGER NOT NULL CHECK(version BETWEEN 1 AND 9007199254740991),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 4194304),
  digest TEXT NOT NULL,
  CHECK((role='root' AND epoch=0) OR (role<>'root' AND epoch>0)),
  UNIQUE(trust_domain_id,role,epoch,version),
  UNIQUE(trust_domain_id,role,epoch,metadata_id)
) STRICT;
CREATE TABLE trust_root_state (
  trust_domain_id TEXT PRIMARY KEY REFERENCES trust_domain(trust_domain_id),
  root_role TEXT NOT NULL DEFAULT 'root' CHECK(root_role='root'),
  root_epoch INTEGER NOT NULL DEFAULT 0 CHECK(root_epoch=0),
  metadata_id TEXT NOT NULL,
  metadata_epoch INTEGER NOT NULL CHECK(metadata_epoch>=1),
  reset_pending INTEGER NOT NULL CHECK(reset_pending IN (0,1)),
  FOREIGN KEY(trust_domain_id,root_role,root_epoch,metadata_id) REFERENCES trusted_metadata(trust_domain_id,role,epoch,metadata_id)
) STRICT;
CREATE TABLE trust_root_transition (
  transition_id TEXT PRIMARY KEY,
  trust_domain_id TEXT NOT NULL REFERENCES trust_domain(trust_domain_id),
  previous_id TEXT NOT NULL REFERENCES trusted_metadata(metadata_id),
  metadata_id TEXT NOT NULL UNIQUE REFERENCES trusted_metadata(metadata_id),
  online_keys_changed INTEGER NOT NULL CHECK(online_keys_changed IN (0,1))
) STRICT;
CREATE TRIGGER trust_root_transition_insert BEFORE INSERT ON trust_root_transition BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM trust_root_state s JOIN trusted_metadata old ON old.metadata_id=s.metadata_id
      JOIN trusted_metadata new ON new.metadata_id=NEW.metadata_id
    WHERE s.trust_domain_id=NEW.trust_domain_id AND s.metadata_id=NEW.previous_id
      AND new.trust_domain_id=s.trust_domain_id AND new.role='root' AND new.version=old.version+1
  ) THEN RAISE(ABORT,'trust_root_transition') END;
END;
CREATE TRIGGER trust_root_transition_apply AFTER INSERT ON trust_root_transition BEGIN
  UPDATE trust_root_state SET metadata_id=NEW.metadata_id, reset_pending=max(reset_pending,NEW.online_keys_changed)
    WHERE trust_domain_id=NEW.trust_domain_id;
END;
CREATE TABLE trust_rotation (
  rotation_id TEXT PRIMARY KEY,
  trust_domain_id TEXT NOT NULL REFERENCES trust_domain(trust_domain_id),
  metadata_id TEXT NOT NULL REFERENCES trusted_metadata(metadata_id),
  previous_epoch INTEGER NOT NULL,
  next_epoch INTEGER NOT NULL CHECK(next_epoch=previous_epoch+1),
  UNIQUE(trust_domain_id,next_epoch)
) STRICT;
CREATE TRIGGER trust_rotation_insert BEFORE INSERT ON trust_rotation BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM trust_root_state WHERE trust_domain_id=NEW.trust_domain_id
    AND metadata_id=NEW.metadata_id AND metadata_epoch=NEW.previous_epoch AND reset_pending=1)
    THEN RAISE(ABORT,'trust_rotation') END;
END;
CREATE TRIGGER trust_rotation_apply AFTER INSERT ON trust_rotation BEGIN
  UPDATE trust_root_state SET metadata_epoch=NEW.next_epoch,reset_pending=0 WHERE trust_domain_id=NEW.trust_domain_id;
END;
CREATE TABLE trust_metadata_head (
  trust_domain_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role<>'root'),
  epoch INTEGER NOT NULL CHECK(epoch>0),
  metadata_id TEXT NOT NULL,
  PRIMARY KEY(trust_domain_id,role,epoch),
  FOREIGN KEY(trust_domain_id,role,epoch,metadata_id) REFERENCES trusted_metadata(trust_domain_id,role,epoch,metadata_id)
) STRICT;
CREATE TRIGGER trust_head_insert BEFORE INSERT ON trust_metadata_head BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM trust_root_state WHERE trust_domain_id=NEW.trust_domain_id
    AND metadata_epoch=NEW.epoch AND reset_pending=0) THEN RAISE(ABORT,'trust_epoch') END;
END;
CREATE TRIGGER trust_head_update BEFORE UPDATE ON trust_metadata_head BEGIN
  SELECT CASE WHEN NEW.trust_domain_id<>OLD.trust_domain_id OR NEW.role<>OLD.role OR NEW.epoch<>OLD.epoch
    OR NOT EXISTS(SELECT 1 FROM trust_root_state WHERE trust_domain_id=NEW.trust_domain_id AND metadata_epoch=NEW.epoch AND reset_pending=0)
    OR (SELECT version FROM trusted_metadata WHERE metadata_id=NEW.metadata_id)<=(SELECT version FROM trusted_metadata WHERE metadata_id=OLD.metadata_id)
    THEN RAISE(ABORT,'trust_head_rollback') END;
END;
CREATE TRIGGER trust_root_state_update BEFORE UPDATE ON trust_root_state BEGIN
  SELECT CASE WHEN NEW.trust_domain_id<>OLD.trust_domain_id OR NOT (
    (NEW.metadata_epoch=OLD.metadata_epoch AND EXISTS(SELECT 1 FROM trust_root_transition t
      WHERE t.trust_domain_id=OLD.trust_domain_id AND t.previous_id=OLD.metadata_id AND t.metadata_id=NEW.metadata_id
      AND NEW.reset_pending=max(OLD.reset_pending,t.online_keys_changed))) OR
    (NEW.metadata_id=OLD.metadata_id AND OLD.reset_pending=1 AND NEW.reset_pending=0 AND EXISTS(SELECT 1 FROM trust_rotation r
      WHERE r.trust_domain_id=OLD.trust_domain_id AND r.metadata_id=OLD.metadata_id AND r.previous_epoch=OLD.metadata_epoch AND r.next_epoch=NEW.metadata_epoch))
  ) THEN RAISE(ABORT,'trust_state_transition') END;
END;
CREATE TABLE trust_verification_session (
  session_id TEXT PRIMARY KEY,
  trust_domain_id TEXT NOT NULL REFERENCES trust_domain(trust_domain_id),
  reference_time INTEGER NOT NULL CHECK(reference_time BETWEEN -8640000000000000 AND 8640000000000000),
  context_body BLOB NOT NULL CHECK(length(context_body)<=65536),
  context_digest TEXT NOT NULL
) STRICT;
CREATE TRIGGER trust_domain_update BEFORE UPDATE ON trust_domain BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_domain_delete BEFORE DELETE ON trust_domain BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trusted_metadata_update BEFORE UPDATE ON trusted_metadata BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trusted_metadata_delete BEFORE DELETE ON trusted_metadata BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_root_transition_update BEFORE UPDATE ON trust_root_transition BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_root_transition_delete BEFORE DELETE ON trust_root_transition BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_rotation_update BEFORE UPDATE ON trust_rotation BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_rotation_delete BEFORE DELETE ON trust_rotation BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_root_state_delete BEFORE DELETE ON trust_root_state BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_head_delete BEFORE DELETE ON trust_metadata_head BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_session_update BEFORE UPDATE ON trust_verification_session BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_session_delete BEFORE DELETE ON trust_verification_session BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;

CREATE TABLE trust_download_attempt (
  download_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES trust_verification_session(session_id),
  target_path TEXT NOT NULL,
  package_bytes INTEGER NOT NULL CHECK(package_bytes BETWEEN 0 AND 536870912),
  package_digest TEXT NOT NULL,
  target_body BLOB NOT NULL CHECK(length(target_body)<=4194304),
  target_digest TEXT NOT NULL,
  metadata_body BLOB NOT NULL CHECK(length(metadata_body)<=4194304),
  metadata_digest TEXT NOT NULL,
  UNIQUE(download_id,package_bytes,package_digest)
) STRICT;
CREATE TABLE trust_download_receipt (
  download_id TEXT PRIMARY KEY,
  package_bytes INTEGER NOT NULL,
  package_digest TEXT NOT NULL,
  FOREIGN KEY(download_id,package_bytes,package_digest) REFERENCES trust_download_attempt(download_id,package_bytes,package_digest)
) STRICT;
CREATE TRIGGER trust_download_attempt_update BEFORE UPDATE ON trust_download_attempt BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_download_attempt_delete BEFORE DELETE ON trust_download_attempt BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_download_receipt_update BEFORE UPDATE ON trust_download_receipt BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_download_receipt_delete BEFORE DELETE ON trust_download_receipt BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;

CREATE TABLE trust_release_document (
  document_id TEXT PRIMARY KEY,
  download_id TEXT NOT NULL REFERENCES trust_download_receipt(download_id),
  kind TEXT NOT NULL CHECK(kind IN ('release','revocations')),
  decoder_id TEXT NOT NULL,
  decoder_digest TEXT NOT NULL,
  package_bytes INTEGER NOT NULL CHECK(package_bytes BETWEEN 1 AND 4194304),
  package_digest TEXT NOT NULL,
  body BLOB NOT NULL CHECK(length(body)=package_bytes),
  UNIQUE(download_id,kind,decoder_digest),
  FOREIGN KEY(download_id,package_bytes,package_digest) REFERENCES trust_download_attempt(download_id,package_bytes,package_digest)
) STRICT;
CREATE TRIGGER trust_release_document_update BEFORE UPDATE ON trust_release_document BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_release_document_delete BEFORE DELETE ON trust_release_document BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;

CREATE TABLE trust_revocation_policy (
  trust_domain_id TEXT PRIMARY KEY REFERENCES trust_domain(trust_domain_id),
  target_path TEXT NOT NULL,
  approval_reference TEXT NOT NULL
) STRICT;
CREATE TABLE trust_revocation_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  trust_domain_id TEXT NOT NULL REFERENCES trust_revocation_policy(trust_domain_id),
  revision TEXT NOT NULL CHECK(length(revision) BETWEEN 1 AND 20 AND length(CAST(revision AS BLOB))=length(revision)
    AND revision NOT GLOB '*[^0-9]*' AND substr(revision,1,1) BETWEEN '1' AND '9'),
  document_id TEXT NOT NULL REFERENCES trust_release_document(document_id),
  document_digest TEXT NOT NULL,
  UNIQUE(trust_domain_id,revision),
  UNIQUE(trust_domain_id,snapshot_id,document_digest)
) STRICT;
CREATE TABLE trust_revocation_record (
  trust_domain_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('release_id','manifest_digest','artifact_digest')),
  value TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  document_digest TEXT NOT NULL,
  PRIMARY KEY(trust_domain_id,kind,value),
  FOREIGN KEY(trust_domain_id,snapshot_id,document_digest) REFERENCES trust_revocation_snapshot(trust_domain_id,snapshot_id,document_digest)
) STRICT;
CREATE TABLE trust_revocation_adoption (
  adoption_id TEXT PRIMARY KEY,
  trust_domain_id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES trust_verification_session(session_id),
  document_id TEXT NOT NULL REFERENCES trust_release_document(document_id),
  snapshot_id TEXT NOT NULL,
  document_digest TEXT NOT NULL,
  metadata_epoch INTEGER NOT NULL,
  UNIQUE(session_id,document_id),
  FOREIGN KEY(trust_domain_id,snapshot_id,document_digest) REFERENCES trust_revocation_snapshot(trust_domain_id,snapshot_id,document_digest)
) STRICT;
CREATE TRIGGER trust_revocation_snapshot_insert BEFORE INSERT ON trust_revocation_snapshot BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM trust_release_document d JOIN trust_download_attempt a USING(download_id)
    JOIN trust_verification_session s USING(session_id) JOIN trust_revocation_policy p USING(trust_domain_id)
    WHERE d.document_id=NEW.document_id AND d.kind='revocations' AND d.package_digest=NEW.document_digest
      AND s.trust_domain_id=NEW.trust_domain_id AND a.target_path=p.target_path
      AND json_extract(CAST(d.body AS TEXT),'$.revision')=NEW.revision
  ) THEN RAISE(ABORT,'trust_revocation_binding') END;
  SELECT CASE WHEN EXISTS (SELECT 1 FROM trust_revocation_snapshot WHERE trust_domain_id=NEW.trust_domain_id
    AND (length(revision)>length(NEW.revision) OR (length(revision)=length(NEW.revision) AND revision>=NEW.revision)))
    THEN RAISE(ABORT,'trust_revocation_rollback') END;
END;
CREATE TRIGGER trust_revocation_snapshot_records AFTER INSERT ON trust_revocation_snapshot BEGIN
  INSERT INTO trust_revocation_record
    SELECT NEW.trust_domain_id,'release_id',j.value,NEW.snapshot_id,NEW.document_digest
    FROM trust_release_document d,json_each(CAST(d.body AS TEXT),'$.revoked_release_ids') j WHERE d.document_id=NEW.document_id
    ON CONFLICT(trust_domain_id,kind,value) DO NOTHING;
  INSERT INTO trust_revocation_record
    SELECT NEW.trust_domain_id,'manifest_digest',j.value,NEW.snapshot_id,NEW.document_digest
    FROM trust_release_document d,json_each(CAST(d.body AS TEXT),'$.revoked_manifest_digests') j WHERE d.document_id=NEW.document_id
    ON CONFLICT(trust_domain_id,kind,value) DO NOTHING;
  INSERT INTO trust_revocation_record
    SELECT NEW.trust_domain_id,'artifact_digest',j.value,NEW.snapshot_id,NEW.document_digest
    FROM trust_release_document d,json_each(CAST(d.body AS TEXT),'$.revoked_artifact_digests') j WHERE d.document_id=NEW.document_id
    ON CONFLICT(trust_domain_id,kind,value) DO NOTHING;
END;
CREATE TRIGGER trust_revocation_adoption_insert BEFORE INSERT ON trust_revocation_adoption BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM trust_release_document d JOIN trust_download_attempt a USING(download_id)
    JOIN trust_verification_session s USING(session_id) JOIN trust_revocation_policy p USING(trust_domain_id)
    JOIN trust_root_state r USING(trust_domain_id) JOIN trust_revocation_snapshot v ON v.snapshot_id=NEW.snapshot_id
    WHERE d.document_id=NEW.document_id AND d.kind='revocations' AND d.package_digest=NEW.document_digest
      AND s.session_id=NEW.session_id AND s.trust_domain_id=NEW.trust_domain_id AND a.target_path=p.target_path
      AND r.reset_pending=0 AND r.metadata_epoch=NEW.metadata_epoch
      AND json_extract(CAST(d.body AS TEXT),'$.revision')=v.revision
      AND NOT EXISTS (SELECT 1 FROM trust_revocation_snapshot x WHERE x.trust_domain_id=NEW.trust_domain_id
        AND (length(x.revision)>length(v.revision) OR (length(x.revision)=length(v.revision) AND x.revision>v.revision)))
  ) THEN RAISE(ABORT,'trust_revocation_binding') END;
END;
CREATE TRIGGER trust_revocation_policy_update BEFORE UPDATE ON trust_revocation_policy BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_revocation_policy_delete BEFORE DELETE ON trust_revocation_policy BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_revocation_snapshot_update BEFORE UPDATE ON trust_revocation_snapshot BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_revocation_snapshot_delete BEFORE DELETE ON trust_revocation_snapshot BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_revocation_record_update BEFORE UPDATE ON trust_revocation_record BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_revocation_record_delete BEFORE DELETE ON trust_revocation_record BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_revocation_adoption_update BEFORE UPDATE ON trust_revocation_adoption BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_revocation_adoption_delete BEFORE DELETE ON trust_revocation_adoption BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;

CREATE TABLE trust_release_approval (
  approval_id TEXT PRIMARY KEY,
  trust_domain_id TEXT NOT NULL REFERENCES trust_domain(trust_domain_id),
  release_id TEXT NOT NULL,
  release_sequence TEXT NOT NULL CHECK(length(release_sequence) BETWEEN 1 AND 20 AND length(CAST(release_sequence AS BLOB))=length(release_sequence)
    AND release_sequence NOT GLOB '*[^0-9]*' AND substr(release_sequence,1,1) BETWEEN '1' AND '9'),
  channel TEXT NOT NULL CHECK(channel IN ('preview','stable')),
  target_profile_id TEXT NOT NULL,
  document_id TEXT NOT NULL REFERENCES trust_release_document(document_id),
  document_digest TEXT NOT NULL,
  UNIQUE(trust_domain_id,release_id),
  UNIQUE(trust_domain_id,channel,target_profile_id,release_sequence)
) STRICT;
CREATE TABLE trust_release_authorization (
  authorization_id TEXT PRIMARY KEY,
  approval_id TEXT NOT NULL REFERENCES trust_release_approval(approval_id),
  session_id TEXT NOT NULL REFERENCES trust_verification_session(session_id),
  release_document_id TEXT NOT NULL REFERENCES trust_release_document(document_id),
  package_download_id TEXT NOT NULL REFERENCES trust_download_receipt(download_id),
  revocation_adoption_id TEXT NOT NULL REFERENCES trust_revocation_adoption(adoption_id),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 65536),
  body_digest TEXT NOT NULL,
  metadata_epoch INTEGER NOT NULL,
  UNIQUE(session_id,release_document_id,package_download_id)
) STRICT;
CREATE TRIGGER trust_release_approval_insert BEFORE INSERT ON trust_release_approval BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM trust_release_document d JOIN trust_download_attempt a USING(download_id) JOIN trust_verification_session s USING(session_id)
    WHERE d.document_id=NEW.document_id AND d.kind='release' AND d.package_digest=NEW.document_digest AND s.trust_domain_id=NEW.trust_domain_id
      AND json_extract(CAST(d.body AS TEXT),'$.release_id')=NEW.release_id
      AND json_extract(CAST(d.body AS TEXT),'$.release_sequence')=NEW.release_sequence
      AND json_extract(CAST(d.body AS TEXT),'$.channel')=NEW.channel
      AND json_extract(CAST(d.body AS TEXT),'$.target_profile_id')=NEW.target_profile_id
  ) THEN RAISE(ABORT,'trust_release_binding') END;
  SELECT CASE WHEN EXISTS (SELECT 1 FROM trust_release_approval WHERE trust_domain_id=NEW.trust_domain_id AND channel=NEW.channel AND target_profile_id=NEW.target_profile_id
    AND (length(release_sequence)>length(NEW.release_sequence) OR (length(release_sequence)=length(NEW.release_sequence) AND release_sequence>=NEW.release_sequence)))
    THEN RAISE(ABORT,'trust_release_rollback') END;
END;
CREATE TRIGGER trust_release_authorization_insert BEFORE INSERT ON trust_release_authorization BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM trust_release_approval p JOIN trust_release_document d ON d.document_id=NEW.release_document_id
      JOIN trust_download_attempt m ON m.download_id=d.download_id JOIN trust_download_attempt a ON a.download_id=NEW.package_download_id
      JOIN trust_verification_session s ON s.session_id=NEW.session_id JOIN trust_revocation_adoption r ON r.adoption_id=NEW.revocation_adoption_id
      JOIN trust_root_state t ON t.trust_domain_id=s.trust_domain_id
    WHERE p.approval_id=NEW.approval_id AND p.trust_domain_id=s.trust_domain_id AND p.document_digest=d.package_digest AND d.kind='release'
      AND m.session_id=s.session_id AND a.session_id=s.session_id AND r.session_id=s.session_id
      AND r.trust_domain_id=s.trust_domain_id AND r.metadata_epoch=NEW.metadata_epoch AND t.metadata_epoch=NEW.metadata_epoch AND t.reset_pending=0
      AND json_extract(CAST(NEW.body AS TEXT),'$.release_id')=p.release_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.release_sequence')=p.release_sequence
      AND json_extract(CAST(NEW.body AS TEXT),'$.trust_domain_id')=s.trust_domain_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.approval_id')=p.approval_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.session_id')=s.session_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.release_document_id')=d.document_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.package_download_id')=a.download_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.revocation_adoption_id')=r.adoption_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.channel')=p.channel
      AND json_extract(CAST(NEW.body AS TEXT),'$.target_profile_id')=p.target_profile_id
      AND json_extract(CAST(NEW.body AS TEXT),'$.metadata_epoch')=NEW.metadata_epoch
      AND json_extract(CAST(NEW.body AS TEXT),'$.release_manifest_digest')=p.document_digest
      AND json_extract(CAST(NEW.body AS TEXT),'$.package_digest')=a.package_digest
      AND json_extract(CAST(NEW.body AS TEXT),'$.package_bytes')=CAST(a.package_bytes AS TEXT)
      AND json_extract(CAST(NEW.body AS TEXT),'$.expected_manifest_digest')=json_extract(CAST(a.target_body AS TEXT),'$.custom.leafseamer.extension_manifest_digest')
      AND json_extract(CAST(NEW.body AS TEXT),'$.artifact_id')=json_extract(CAST(a.target_body AS TEXT),'$.custom.leafseamer.artifact_id')
      AND json_extract(CAST(NEW.body AS TEXT),'$.deployment_profile_id')=json_extract(CAST(a.target_body AS TEXT),'$.custom.leafseamer.deployment_profile_id')
  ) THEN RAISE(ABORT,'trust_authorization_binding') END;
END;
CREATE TRIGGER trust_release_approval_update BEFORE UPDATE ON trust_release_approval BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_release_approval_delete BEFORE DELETE ON trust_release_approval BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_release_authorization_update BEFORE UPDATE ON trust_release_authorization BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
CREATE TRIGGER trust_release_authorization_delete BEFORE DELETE ON trust_release_authorization BEGIN SELECT RAISE(ABORT,'immutable_trust'); END;
