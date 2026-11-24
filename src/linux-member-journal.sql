CREATE TABLE linux_member_identity (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  body TEXT NOT NULL
) STRICT;
CREATE TRIGGER linux_member_identity_update BEFORE UPDATE ON linux_member_identity
BEGIN SELECT RAISE(ABORT,'linux_member_identity_immutable'); END;
CREATE TRIGGER linux_member_identity_delete BEFORE DELETE ON linux_member_identity
BEGIN SELECT RAISE(ABORT,'linux_member_identity_immutable'); END;

CREATE TABLE linux_member_event (
  launch_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('controller','seamer')),
  revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 4),
  phase TEXT NOT NULL CHECK(phase IN ('reserved','created_closed','release_requested','executed_closed')),
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 32768),
  digest TEXT NOT NULL,
  PRIMARY KEY(launch_id,revision)
) STRICT;
CREATE TRIGGER linux_member_event_update BEFORE UPDATE ON linux_member_event
BEGIN SELECT RAISE(ABORT,'linux_member_event_immutable'); END;
CREATE TRIGGER linux_member_event_delete BEFORE DELETE ON linux_member_event
BEGIN SELECT RAISE(ABORT,'linux_member_event_immutable'); END;
CREATE TRIGGER linux_member_event_transition BEFORE INSERT ON linux_member_event
WHEN NOT (
  (NEW.revision=1 AND NEW.phase='reserved' AND
    NOT EXISTS (SELECT 1 FROM linux_member_event WHERE role=NEW.role))
  OR EXISTS (
    SELECT 1 FROM linux_member_event AS p
    WHERE p.launch_id=NEW.launch_id AND p.role=NEW.role AND p.revision=NEW.revision-1
      AND ((p.phase='reserved' AND NEW.phase='created_closed')
        OR (p.phase='created_closed' AND NEW.phase='release_requested')
        OR (p.phase='release_requested' AND NEW.phase='executed_closed')))
)
BEGIN SELECT RAISE(ABORT,'linux_member_transition'); END;
