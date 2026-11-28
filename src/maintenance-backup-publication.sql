CREATE TABLE maintenance_backup_publication_intent (
  operation_id TEXT PRIMARY KEY REFERENCES maintenance_backup_operation(operation_id),
  source_revision INTEGER NOT NULL CHECK(source_revision > 0),
  runtime_id TEXT NOT NULL,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 8192),
  digest TEXT NOT NULL
) STRICT;

CREATE TABLE maintenance_backup_publication_cancel (
  operation_id TEXT PRIMARY KEY REFERENCES maintenance_backup_publication_intent(operation_id)
) STRICT;

CREATE TABLE maintenance_backup_publication_result (
  operation_id TEXT PRIMARY KEY REFERENCES maintenance_backup_publication_intent(operation_id),
  state TEXT NOT NULL CHECK(state IN ('published','failed','cancelled','indeterminate')),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 4096),
  digest TEXT NOT NULL
) STRICT;

CREATE TRIGGER maintenance_backup_publication_claim BEFORE INSERT ON maintenance_backup_publication_intent
WHEN NOT EXISTS (
  SELECT 1 FROM maintenance_backup_current c WHERE c.operation_id=NEW.operation_id AND c.revision=NEW.source_revision
    AND c.phase='running' AND c.step='snapshots_staged' AND c.cancel_requested=0)
BEGIN SELECT RAISE(ABORT,'backup_publication_revision'); END;

CREATE TRIGGER maintenance_backup_publication_freeze BEFORE INSERT ON maintenance_backup_event
WHEN EXISTS (SELECT 1 FROM maintenance_backup_publication_intent WHERE operation_id=NEW.operation_id)
BEGIN SELECT RAISE(ABORT,'backup_publication_claimed'); END;

CREATE TRIGGER maintenance_backup_publication_cancel_late BEFORE INSERT ON maintenance_backup_publication_cancel
WHEN EXISTS (SELECT 1 FROM maintenance_backup_publication_result WHERE operation_id=NEW.operation_id)
BEGIN SELECT RAISE(ABORT,'backup_publication_finished'); END;

CREATE TRIGGER maintenance_backup_publication_cancel_result BEFORE INSERT ON maintenance_backup_publication_result
WHEN NEW.state<>'indeterminate' AND
     (NEW.state='cancelled')<>EXISTS (SELECT 1 FROM maintenance_backup_publication_cancel WHERE operation_id=NEW.operation_id)
BEGIN SELECT RAISE(ABORT,'backup_publication_cancelled'); END;

CREATE TRIGGER maintenance_backup_publication_intent_update BEFORE UPDATE ON maintenance_backup_publication_intent BEGIN SELECT RAISE(ABORT,'immutable_backup_publication'); END;
CREATE TRIGGER maintenance_backup_publication_intent_delete BEFORE DELETE ON maintenance_backup_publication_intent BEGIN SELECT RAISE(ABORT,'immutable_backup_publication'); END;
CREATE TRIGGER maintenance_backup_publication_cancel_update BEFORE UPDATE ON maintenance_backup_publication_cancel BEGIN SELECT RAISE(ABORT,'immutable_backup_publication'); END;
CREATE TRIGGER maintenance_backup_publication_cancel_delete BEFORE DELETE ON maintenance_backup_publication_cancel BEGIN SELECT RAISE(ABORT,'immutable_backup_publication'); END;
CREATE TRIGGER maintenance_backup_publication_result_update BEFORE UPDATE ON maintenance_backup_publication_result BEGIN SELECT RAISE(ABORT,'immutable_backup_publication'); END;
CREATE TRIGGER maintenance_backup_publication_result_delete BEFORE DELETE ON maintenance_backup_publication_result BEGIN SELECT RAISE(ABORT,'immutable_backup_publication'); END;
