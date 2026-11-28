CREATE TABLE maintenance_backup_plan (
  plan_id TEXT PRIMARY KEY,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 1048576),
  digest TEXT NOT NULL
) STRICT;

CREATE TABLE maintenance_backup_operation (
  operation_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES maintenance_backup_plan(plan_id),
  request_key BLOB NOT NULL UNIQUE CHECK(length(request_key) BETWEEN 1 AND 4096),
  request_digest TEXT NOT NULL
) STRICT;

CREATE TABLE maintenance_backup_event (
  operation_id TEXT NOT NULL REFERENCES maintenance_backup_operation(operation_id),
  revision INTEGER NOT NULL CHECK(revision > 0),
  phase TEXT NOT NULL CHECK(phase IN ('awaiting_local_approval','queued','running','failed','cancelled','indeterminate')),
  step TEXT NOT NULL CHECK(step IN ('pending','snapshotting','snapshots_staged','stopped')),
  runtime_id TEXT,
  cancel_requested INTEGER NOT NULL CHECK(cancel_requested IN (0,1)),
  detail BLOB NOT NULL CHECK(length(detail) BETWEEN 1 AND 4096),
  detail_digest TEXT NOT NULL,
  PRIMARY KEY(operation_id, revision),
  CHECK((phase IN ('awaiting_local_approval','queued') AND step='pending' AND runtime_id IS NULL AND cancel_requested=0) OR
        (phase='running' AND runtime_id IS NOT NULL AND step IN ('snapshotting','snapshots_staged')) OR
        (phase='indeterminate' AND step='stopped' AND runtime_id IS NOT NULL) OR
        (phase IN ('failed','cancelled') AND step='stopped'))
) STRICT, WITHOUT ROWID;

CREATE VIEW maintenance_backup_current AS
  SELECT e.* FROM maintenance_backup_event e
  WHERE e.revision=(SELECT max(p.revision) FROM maintenance_backup_event p WHERE p.operation_id=e.operation_id);

CREATE TABLE maintenance_backup_target (
  operation_id TEXT NOT NULL REFERENCES maintenance_backup_operation(operation_id),
  target_index INTEGER NOT NULL CHECK(target_index BETWEEN 0 AND 255),
  backup_operation_id TEXT NOT NULL UNIQUE,
  PRIMARY KEY(operation_id, target_index)
) STRICT, WITHOUT ROWID;

CREATE TABLE maintenance_backup_snapshot (
  backup_operation_id TEXT PRIMARY KEY REFERENCES maintenance_backup_target(backup_operation_id),
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 4096),
  digest TEXT NOT NULL
) STRICT;

CREATE TRIGGER maintenance_backup_event_revision BEFORE INSERT ON maintenance_backup_event
WHEN NEW.revision<>coalesce((SELECT revision+1 FROM maintenance_backup_current WHERE operation_id=NEW.operation_id),1)
BEGIN SELECT RAISE(ABORT,'maintenance_backup_revision'); END;

CREATE TRIGGER maintenance_backup_event_transition BEFORE INSERT ON maintenance_backup_event
WHEN (NEW.revision=1 AND NEW.phase NOT IN ('awaiting_local_approval','queued')) OR
     (NEW.revision>1 AND NOT EXISTS (
       SELECT 1 FROM maintenance_backup_current e WHERE e.operation_id=NEW.operation_id AND (
         (e.phase='awaiting_local_approval' AND NEW.phase IN ('queued','cancelled')) OR
         (e.phase='queued' AND NEW.phase IN ('running','cancelled')) OR
         (e.phase='running' AND e.step='snapshotting' AND e.runtime_id=NEW.runtime_id AND
          NEW.phase IN ('running','failed','cancelled','indeterminate')) OR
         (e.phase='running' AND e.step='snapshots_staged' AND NEW.phase='cancelled')
       )))
BEGIN SELECT RAISE(ABORT,'maintenance_backup_transition'); END;

CREATE TRIGGER maintenance_backup_complete_targets BEFORE INSERT ON maintenance_backup_event
WHEN NEW.step='snapshots_staged' AND EXISTS (
  SELECT 1 FROM maintenance_backup_target t LEFT JOIN maintenance_backup_snapshot s USING(backup_operation_id)
  WHERE t.operation_id=NEW.operation_id AND s.backup_operation_id IS NULL)
BEGIN SELECT RAISE(ABORT,'maintenance_backup_target_missing'); END;

CREATE TRIGGER maintenance_backup_plan_update BEFORE UPDATE ON maintenance_backup_plan BEGIN SELECT RAISE(ABORT,'immutable_backup_plan'); END;
CREATE TRIGGER maintenance_backup_plan_delete BEFORE DELETE ON maintenance_backup_plan BEGIN SELECT RAISE(ABORT,'immutable_backup_plan'); END;
CREATE TRIGGER maintenance_backup_operation_update BEFORE UPDATE ON maintenance_backup_operation BEGIN SELECT RAISE(ABORT,'immutable_backup_operation'); END;
CREATE TRIGGER maintenance_backup_operation_delete BEFORE DELETE ON maintenance_backup_operation BEGIN SELECT RAISE(ABORT,'immutable_backup_operation'); END;
CREATE TRIGGER maintenance_backup_event_update BEFORE UPDATE ON maintenance_backup_event BEGIN SELECT RAISE(ABORT,'immutable_backup_event'); END;
CREATE TRIGGER maintenance_backup_event_delete BEFORE DELETE ON maintenance_backup_event BEGIN SELECT RAISE(ABORT,'immutable_backup_event'); END;
CREATE TRIGGER maintenance_backup_target_update BEFORE UPDATE ON maintenance_backup_target BEGIN SELECT RAISE(ABORT,'immutable_backup_target'); END;
CREATE TRIGGER maintenance_backup_target_delete BEFORE DELETE ON maintenance_backup_target BEGIN SELECT RAISE(ABORT,'immutable_backup_target'); END;
CREATE TRIGGER maintenance_backup_snapshot_update BEFORE UPDATE ON maintenance_backup_snapshot BEGIN SELECT RAISE(ABORT,'immutable_backup_snapshot'); END;
CREATE TRIGGER maintenance_backup_snapshot_delete BEFORE DELETE ON maintenance_backup_snapshot BEGIN SELECT RAISE(ABORT,'immutable_backup_snapshot'); END;
