CREATE TABLE maintenance_recovery_windows_fence (
  restore_id TEXT PRIMARY KEY REFERENCES maintenance_recovery_approval(restore_id),
  retirement_id TEXT NOT NULL UNIQUE,
  approval_id TEXT NOT NULL,
  plan_digest TEXT NOT NULL,
  generation_id TEXT NOT NULL UNIQUE,
  source_digest TEXT NOT NULL,
  preflight_digest TEXT NOT NULL
) STRICT;
CREATE TABLE maintenance_recovery_windows_fence_result (
  restore_id TEXT PRIMARY KEY REFERENCES maintenance_recovery_windows_fence(restore_id),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 8192),
  digest TEXT NOT NULL
) STRICT;
CREATE TRIGGER maintenance_recovery_windows_fence_approved BEFORE INSERT ON maintenance_recovery_windows_fence
WHEN NOT EXISTS(SELECT 1 FROM maintenance_recovery_approval
  WHERE restore_id=NEW.restore_id AND approval_id=NEW.approval_id AND plan_digest=NEW.plan_digest)
BEGIN SELECT RAISE(ABORT,'recovery_retirement_not_approved'); END;
CREATE TRIGGER maintenance_recovery_windows_fence_update BEFORE UPDATE ON maintenance_recovery_windows_fence
BEGIN SELECT RAISE(ABORT,'immutable_recovery_retirement'); END;
CREATE TRIGGER maintenance_recovery_windows_fence_delete BEFORE DELETE ON maintenance_recovery_windows_fence
BEGIN SELECT RAISE(ABORT,'immutable_recovery_retirement'); END;
CREATE TRIGGER maintenance_recovery_windows_fence_result_update BEFORE UPDATE ON maintenance_recovery_windows_fence_result
BEGIN SELECT RAISE(ABORT,'immutable_recovery_retirement'); END;
CREATE TRIGGER maintenance_recovery_windows_fence_result_delete BEFORE DELETE ON maintenance_recovery_windows_fence_result
BEGIN SELECT RAISE(ABORT,'immutable_recovery_retirement'); END;
