-- DF04局部约束探针；只在 :memory: 执行，不是生产DDL或迁移。
PRAGMA foreign_keys=ON;

CREATE TABLE probe_revision (
  value TEXT COLLATE BINARY PRIMARY KEY NOT NULL,
  CHECK(length(value) BETWEEN 1 AND 20),
  CHECK(instr(value,char(0))=0),
  CHECK(value NOT GLOB '*[^0-9]*'),
  CHECK(value='0' OR substr(value,1,1) BETWEEN '1' AND '9')
) STRICT;
CREATE INDEX probe_revision_order ON probe_revision(length(value),value COLLATE BINARY);

CREATE TABLE probe_command (
  command_id TEXT PRIMARY KEY NOT NULL,
  phase TEXT NOT NULL CHECK(phase IN ('queued','dispatching','awaiting_evidence','finished')),
  outcome TEXT NOT NULL CHECK(outcome IN ('pending','succeeded','failed','unknown','cancelled','expired','blocked')),
  resource_status TEXT NOT NULL CHECK(resource_status IN ('held','clear','unresolved')),
  release_ref TEXT,
  resolution_ref TEXT,
  CHECK((phase='finished')=(outcome<>'pending')),
  CHECK(outcome<>'unknown' OR resource_status<>'held'),
  CHECK(outcome<>'unknown' OR resource_status<>'clear' OR
        (release_ref IS NOT NULL AND resolution_ref IS NOT NULL))
) STRICT;
CREATE TRIGGER probe_terminal_immutable BEFORE UPDATE OF phase,outcome ON probe_command
WHEN OLD.phase='finished' AND (NEW.phase<>OLD.phase OR NEW.outcome<>OLD.outcome)
BEGIN SELECT RAISE(ABORT,'terminal_immutable'); END;

CREATE TABLE probe_attempt (
  attempt_id TEXT PRIMARY KEY NOT NULL,
  command_id TEXT NOT NULL REFERENCES probe_command(command_id),
  attempt_no INTEGER NOT NULL CHECK(attempt_no BETWEEN 1 AND 16),
  UNIQUE(command_id,attempt_no),
  UNIQUE(attempt_id,command_id)
) STRICT;
CREATE TABLE probe_intent (
  intent_id TEXT PRIMARY KEY NOT NULL,
  attempt_id TEXT NOT NULL UNIQUE,
  command_id TEXT NOT NULL,
  permit_id TEXT NOT NULL UNIQUE,
  FOREIGN KEY(attempt_id,command_id) REFERENCES probe_attempt(attempt_id,command_id)
) STRICT;

CREATE TABLE probe_hold (
  hold_id TEXT PRIMARY KEY NOT NULL,
  command_id TEXT NOT NULL REFERENCES probe_command(command_id),
  device_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('held','unresolved','released'))
) STRICT;
CREATE UNIQUE INDEX probe_one_active_device_hold ON probe_hold(device_id)
  WHERE state IN ('held','unresolved');

CREATE TABLE probe_barrier_member (
  barrier_id TEXT NOT NULL,
  permit_id TEXT NOT NULL REFERENCES probe_intent(permit_id),
  PRIMARY KEY(barrier_id,permit_id)
) STRICT;
CREATE TABLE probe_coverage (
  barrier_id TEXT NOT NULL,
  permit_id TEXT NOT NULL,
  disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
  PRIMARY KEY(barrier_id,permit_id),
  FOREIGN KEY(barrier_id,permit_id) REFERENCES probe_barrier_member(barrier_id,permit_id)
) STRICT;

CREATE TABLE probe_preview (
  preview_id TEXT PRIMARY KEY NOT NULL,
  consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0,1))
) STRICT;
CREATE TABLE probe_recovery (
  operation_id TEXT PRIMARY KEY NOT NULL,
  preview_id TEXT NOT NULL UNIQUE REFERENCES probe_preview(preview_id),
  run_id TEXT NOT NULL,
  active INTEGER NOT NULL CHECK(active IN (0,1))
) STRICT;
CREATE UNIQUE INDEX probe_one_active_recovery ON probe_recovery(run_id) WHERE active=1;

CREATE TABLE probe_outbox (
  event_id TEXT PRIMARY KEY NOT NULL,
  stream_id TEXT NOT NULL,
  stream_epoch TEXT NOT NULL,
  sequence TEXT NOT NULL REFERENCES probe_revision(value),
  UNIQUE(stream_id,stream_epoch,sequence)
) STRICT;
