CREATE TABLE maintenance_recovery_plan (
  restore_id TEXT PRIMARY KEY REFERENCES maintenance_restore_result(restore_id),
  plan_id TEXT NOT NULL UNIQUE,
  isolation_digest TEXT NOT NULL,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 524288),
  digest TEXT NOT NULL,
  UNIQUE(restore_id,digest)
) STRICT;

CREATE TABLE maintenance_recovery_approval (
  restore_id TEXT PRIMARY KEY,
  plan_digest TEXT NOT NULL,
  approval_id TEXT NOT NULL UNIQUE,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 4096),
  digest TEXT NOT NULL,
  FOREIGN KEY(restore_id,plan_digest) REFERENCES maintenance_recovery_plan(restore_id,digest)
) STRICT;

CREATE TRIGGER maintenance_recovery_isolated BEFORE INSERT ON maintenance_recovery_plan
WHEN NOT EXISTS(SELECT 1 FROM maintenance_restore_result
  WHERE restore_id=NEW.restore_id AND digest=NEW.isolation_digest AND state='isolated_validated')
BEGIN SELECT RAISE(ABORT,'recovery_plan_not_isolated'); END;

CREATE TRIGGER maintenance_recovery_plan_update BEFORE UPDATE ON maintenance_recovery_plan BEGIN SELECT RAISE(ABORT,'immutable_recovery_plan'); END;
CREATE TRIGGER maintenance_recovery_plan_delete BEFORE DELETE ON maintenance_recovery_plan BEGIN SELECT RAISE(ABORT,'immutable_recovery_plan'); END;
CREATE TRIGGER maintenance_recovery_approval_update BEFORE UPDATE ON maintenance_recovery_approval BEGIN SELECT RAISE(ABORT,'immutable_recovery_approval'); END;
CREATE TRIGGER maintenance_recovery_approval_delete BEFORE DELETE ON maintenance_recovery_approval BEGIN SELECT RAISE(ABORT,'immutable_recovery_approval'); END;
