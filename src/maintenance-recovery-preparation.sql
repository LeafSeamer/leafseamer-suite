CREATE TABLE maintenance_recovery_preparation (
  restore_id TEXT PRIMARY KEY REFERENCES maintenance_recovery_approval(restore_id),
  preparation_id TEXT NOT NULL UNIQUE,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 8192),
  digest TEXT NOT NULL
) STRICT;
CREATE TABLE maintenance_recovery_preparation_attempt (
  attempt_id TEXT PRIMARY KEY,
  restore_id TEXT NOT NULL REFERENCES maintenance_recovery_preparation(restore_id),
  UNIQUE(restore_id,attempt_id)
) STRICT;
CREATE TABLE maintenance_recovery_preparation_result (
  restore_id TEXT PRIMARY KEY REFERENCES maintenance_recovery_preparation(restore_id),
  attempt_id TEXT NOT NULL UNIQUE,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 524288),
  digest TEXT NOT NULL,
  FOREIGN KEY(restore_id,attempt_id) REFERENCES maintenance_recovery_preparation_attempt(restore_id,attempt_id)
) STRICT;
CREATE TRIGGER maintenance_recovery_preparation_retired BEFORE INSERT ON maintenance_recovery_preparation
WHEN NOT EXISTS(SELECT 1 FROM maintenance_recovery_retirement WHERE restore_id=NEW.restore_id
  AND json_extract(CAST(body AS TEXT),'$.evidence.format') IN ('leafseamer-linux-native-retirement/1','leafseamer-linux-deployment-retirement/1'))
 AND NOT EXISTS(SELECT 1 FROM maintenance_recovery_windows_fence_result WHERE restore_id=NEW.restore_id)
BEGIN SELECT RAISE(ABORT,'recovery_retirement_required'); END;
CREATE TRIGGER maintenance_recovery_preparation_update BEFORE UPDATE ON maintenance_recovery_preparation BEGIN SELECT RAISE(ABORT,'immutable_recovery_preparation'); END;
CREATE TRIGGER maintenance_recovery_preparation_delete BEFORE DELETE ON maintenance_recovery_preparation BEGIN SELECT RAISE(ABORT,'immutable_recovery_preparation'); END;
CREATE TRIGGER maintenance_recovery_preparation_attempt_update BEFORE UPDATE ON maintenance_recovery_preparation_attempt BEGIN SELECT RAISE(ABORT,'immutable_recovery_preparation'); END;
CREATE TRIGGER maintenance_recovery_preparation_attempt_delete BEFORE DELETE ON maintenance_recovery_preparation_attempt BEGIN SELECT RAISE(ABORT,'immutable_recovery_preparation'); END;
CREATE TRIGGER maintenance_recovery_preparation_result_update BEFORE UPDATE ON maintenance_recovery_preparation_result BEGIN SELECT RAISE(ABORT,'immutable_recovery_preparation'); END;
CREATE TRIGGER maintenance_recovery_preparation_result_delete BEFORE DELETE ON maintenance_recovery_preparation_result BEGIN SELECT RAISE(ABORT,'immutable_recovery_preparation'); END;
