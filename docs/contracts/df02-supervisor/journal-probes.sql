-- 局部内存约束探针，不是生产迁移，不含启动秘密或业务数据库。
PRAGMA foreign_keys=ON;
CREATE TABLE run (
  supervisor_id TEXT PRIMARY KEY NOT NULL,
  domain_json BLOB NOT NULL,
  intake_closed INTEGER NOT NULL DEFAULT 1 CHECK(intake_closed IN (0,1))
) STRICT;
CREATE TABLE launch (
  supervisor_id TEXT NOT NULL REFERENCES run(supervisor_id),
  launch_id TEXT NOT NULL,
  intent_digest TEXT NOT NULL,
  intent_json BLOB NOT NULL,
  member_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  group_generation TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('registered','creating','awaiting_bootstrap','admitted_closed','retiring','retired','rejected','indeterminate')),
  creation_attempted INTEGER NOT NULL CHECK(creation_attempted IN (0,1)),
  bootstrap_id TEXT UNIQUE,
  proof_consumed INTEGER NOT NULL DEFAULT 0 CHECK(proof_consumed IN (0,1)),
  admission_json BLOB,
  retirement_json BLOB,
  PRIMARY KEY(supervisor_id,launch_id),
  UNIQUE(supervisor_id,member_id),
  UNIQUE(supervisor_id,group_id,group_generation),
  CHECK(state NOT IN ('registered','rejected') OR creation_attempted=0),
  CHECK(state NOT IN ('creating','awaiting_bootstrap','admitted_closed','indeterminate') OR creation_attempted=1),
  CHECK(state!='admitted_closed' OR (proof_consumed=1 AND admission_json IS NOT NULL)),
  CHECK(state!='retired' OR retirement_json IS NOT NULL),
  CHECK(proof_consumed=0 OR (creation_attempted=1 AND bootstrap_id IS NOT NULL)),
  CHECK(admission_json IS NULL OR proof_consumed=1)
) STRICT;
CREATE TRIGGER immutable_launch BEFORE UPDATE ON launch
WHEN NEW.supervisor_id!=OLD.supervisor_id OR NEW.launch_id!=OLD.launch_id OR NEW.intent_digest!=OLD.intent_digest
  OR NEW.intent_json!=OLD.intent_json OR NEW.member_id!=OLD.member_id OR NEW.group_id!=OLD.group_id OR NEW.group_generation!=OLD.group_generation
  OR NEW.creation_attempted<OLD.creation_attempted OR NEW.proof_consumed<OLD.proof_consumed
  OR (OLD.bootstrap_id IS NOT NULL AND NEW.bootstrap_id IS NOT OLD.bootstrap_id)
  OR (OLD.admission_json IS NOT NULL AND NEW.admission_json IS NOT OLD.admission_json)
  OR (OLD.retirement_json IS NOT NULL AND NEW.retirement_json IS NOT OLD.retirement_json)
BEGIN SELECT RAISE(ABORT,'immutable_launch'); END;
CREATE TRIGGER state_edges BEFORE UPDATE OF state ON launch
WHEN NEW.state!=OLD.state AND NOT (
 (OLD.state='registered' AND NEW.state IN ('creating','rejected','retiring')) OR
 (OLD.state='creating' AND NEW.state IN ('awaiting_bootstrap','indeterminate','retiring')) OR
 (OLD.state='awaiting_bootstrap' AND NEW.state IN ('admitted_closed','indeterminate','retiring')) OR
 (OLD.state='admitted_closed' AND NEW.state IN ('indeterminate','retiring')) OR
 (OLD.state='indeterminate' AND NEW.state='retiring') OR
 (OLD.state='retiring' AND NEW.state='retired'))
BEGIN SELECT RAISE(ABORT,'state_edge'); END;
CREATE TRIGGER no_launch_delete BEFORE DELETE ON launch BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TABLE recovery_attempt (
  supervisor_id TEXT NOT NULL,
  launch_id TEXT NOT NULL,
  policy_json BLOB NOT NULL,
  origin_domain_json BLOB NOT NULL,
  origin_tick TEXT NOT NULL CHECK(length(origin_tick) BETWEEN 1 AND 20 AND origin_tick NOT GLOB '*[^0-9]*' AND (origin_tick='0' OR substr(origin_tick,1,1)!='0')),
  PRIMARY KEY(supervisor_id,launch_id),
  FOREIGN KEY(supervisor_id,launch_id) REFERENCES launch(supervisor_id,launch_id)
) STRICT;
CREATE TRIGGER no_attempt_update BEFORE UPDATE ON recovery_attempt BEGIN SELECT RAISE(ABORT,'immutable_attempt'); END;
CREATE TRIGGER no_attempt_delete BEFORE DELETE ON recovery_attempt BEGIN SELECT RAISE(ABORT,'immutable_attempt'); END;
