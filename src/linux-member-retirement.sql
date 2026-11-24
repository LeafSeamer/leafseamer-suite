CREATE TABLE linux_member_retirement (
  launch_id TEXT NOT NULL,
  source_revision INTEGER NOT NULL CHECK(source_revision BETWEEN 2 AND 4),
  revision INTEGER NOT NULL CHECK(revision IN (1,2)),
  phase TEXT NOT NULL CHECK((revision=1 AND phase='closing') OR (revision=2 AND phase='retired')),
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 8192),
  digest TEXT NOT NULL,
  PRIMARY KEY(launch_id,revision),
  FOREIGN KEY(launch_id,source_revision) REFERENCES linux_member_event(launch_id,revision)
) STRICT;
CREATE TRIGGER linux_member_retirement_update BEFORE UPDATE ON linux_member_retirement
BEGIN SELECT RAISE(ABORT,'linux_member_retirement_immutable'); END;
CREATE TRIGGER linux_member_retirement_delete BEFORE DELETE ON linux_member_retirement
BEGIN SELECT RAISE(ABORT,'linux_member_retirement_immutable'); END;
CREATE TRIGGER linux_member_retirement_transition BEFORE INSERT ON linux_member_retirement
WHEN NEW.source_revision IS NOT (SELECT max(revision) FROM linux_member_event WHERE launch_id=NEW.launch_id)
 OR (NEW.revision=2 AND NOT EXISTS (
   SELECT 1 FROM linux_member_retirement p WHERE p.launch_id=NEW.launch_id AND p.source_revision=NEW.source_revision
     AND p.revision=1 AND p.phase='closing'))
BEGIN SELECT RAISE(ABORT,'linux_member_retirement_transition'); END;

DROP TRIGGER linux_member_event_transition;
CREATE TRIGGER linux_member_event_transition BEFORE INSERT ON linux_member_event
WHEN NOT (
  (NEW.revision=1 AND NEW.phase='reserved' AND NOT EXISTS (
    SELECT 1 FROM linux_member_event e WHERE e.role=NEW.role AND e.revision=1
      AND (json_extract(e.body,'$.intent.generation_id') IS json_extract(NEW.body,'$.intent.generation_id')
        OR NOT EXISTS (SELECT 1 FROM linux_member_retirement p WHERE p.launch_id=e.launch_id AND p.phase='retired'))))
  OR EXISTS (
    SELECT 1 FROM linux_member_event p
    WHERE p.launch_id=NEW.launch_id AND p.role=NEW.role AND p.revision=NEW.revision-1
      AND NOT EXISTS (SELECT 1 FROM linux_member_retirement r WHERE r.launch_id=p.launch_id)
      AND ((p.phase='reserved' AND NEW.phase='created_closed')
        OR (p.phase='created_closed' AND NEW.phase='release_requested')
        OR (p.phase='release_requested' AND NEW.phase='executed_closed')))
)
BEGIN SELECT RAISE(ABORT,'linux_member_transition'); END;
