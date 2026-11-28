CREATE TABLE maintenance_restore_intent (
  restore_id TEXT PRIMARY KEY,
  archive_id TEXT NOT NULL REFERENCES maintenance_backup_publication_result(operation_id),
  runtime_id TEXT NOT NULL,
  expected_generation TEXT NOT NULL,
  source_digest TEXT NOT NULL
) STRICT;

CREATE TABLE maintenance_restore_result (
  restore_id TEXT PRIMARY KEY REFERENCES maintenance_restore_intent(restore_id),
  state TEXT NOT NULL CHECK(state IN ('isolated_validated','failed','indeterminate')),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 4096),
  digest TEXT NOT NULL
) STRICT;

CREATE TRIGGER maintenance_restore_published BEFORE INSERT ON maintenance_restore_intent
WHEN NOT EXISTS (SELECT 1 FROM maintenance_backup_publication_result
  WHERE operation_id=NEW.archive_id AND state='published' AND digest=NEW.source_digest)
BEGIN SELECT RAISE(ABORT,'restore_archive_unpublished'); END;

CREATE TRIGGER maintenance_restore_intent_update BEFORE UPDATE ON maintenance_restore_intent BEGIN SELECT RAISE(ABORT,'immutable_restore'); END;
CREATE TRIGGER maintenance_restore_intent_delete BEFORE DELETE ON maintenance_restore_intent BEGIN SELECT RAISE(ABORT,'immutable_restore'); END;
CREATE TRIGGER maintenance_restore_result_update BEFORE UPDATE ON maintenance_restore_result BEGIN SELECT RAISE(ABORT,'immutable_restore'); END;
CREATE TRIGGER maintenance_restore_result_delete BEFORE DELETE ON maintenance_restore_result BEGIN SELECT RAISE(ABORT,'immutable_restore'); END;
