CREATE TABLE installation_deployment_selection (
  digest TEXT PRIMARY KEY,
  generation TEXT NOT NULL UNIQUE,
  generation_id TEXT NOT NULL UNIQUE,
  previous_digest TEXT UNIQUE REFERENCES installation_deployment_selection(digest),
  activation_id TEXT UNIQUE,
  restore_id TEXT UNIQUE,
  review_digest TEXT,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 524288),
  CHECK((previous_digest IS NULL AND activation_id IS NULL AND restore_id IS NULL AND review_digest IS NULL) OR
    (previous_digest IS NOT NULL AND activation_id IS NOT NULL AND restore_id IS NOT NULL AND review_digest IS NOT NULL)),
  FOREIGN KEY(restore_id,review_digest) REFERENCES maintenance_recovery_site_review(restore_id,digest)
) STRICT;

CREATE TABLE installation_active_deployment (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  selection_digest TEXT NOT NULL REFERENCES installation_deployment_selection(digest)
) STRICT;

CREATE TRIGGER installation_deployment_selection_update BEFORE UPDATE ON installation_deployment_selection
BEGIN SELECT RAISE(ABORT,'immutable_deployment_selection'); END;
CREATE TRIGGER installation_deployment_selection_delete BEFORE DELETE ON installation_deployment_selection
BEGIN SELECT RAISE(ABORT,'immutable_deployment_selection'); END;
CREATE TRIGGER installation_active_deployment_insert BEFORE INSERT ON installation_active_deployment
WHEN (SELECT previous_digest FROM installation_deployment_selection WHERE digest=NEW.selection_digest) IS NOT NULL
BEGIN SELECT RAISE(ABORT,'deployment_selection_conflict'); END;
CREATE TRIGGER installation_active_deployment_update BEFORE UPDATE ON installation_active_deployment
WHEN (SELECT previous_digest FROM installation_deployment_selection WHERE digest=NEW.selection_digest) IS NOT OLD.selection_digest
BEGIN SELECT RAISE(ABORT,'deployment_selection_conflict'); END;
CREATE TRIGGER installation_active_deployment_delete BEFORE DELETE ON installation_active_deployment
BEGIN SELECT RAISE(ABORT,'immutable_deployment_pointer'); END;
