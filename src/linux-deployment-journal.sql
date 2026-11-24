CREATE TABLE linux_deployment_identity (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  body TEXT NOT NULL
) STRICT;
CREATE TRIGGER linux_deployment_identity_update BEFORE UPDATE ON linux_deployment_identity
BEGIN SELECT RAISE(ABORT,'linux_deployment_identity_immutable'); END;
CREATE TRIGGER linux_deployment_identity_delete BEFORE DELETE ON linux_deployment_identity
BEGIN SELECT RAISE(ABORT,'linux_deployment_identity_immutable'); END;

CREATE TABLE linux_deployment_event (
  serial INTEGER PRIMARY KEY,
  generation_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 4),
  phase TEXT NOT NULL CHECK(phase IN ('launching','running','closing','retired','indeterminate')),
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 32768),
  digest TEXT NOT NULL,
  UNIQUE(generation_id,revision)
) STRICT;
CREATE TRIGGER linux_deployment_event_update BEFORE UPDATE ON linux_deployment_event
BEGIN SELECT RAISE(ABORT,'linux_deployment_event_immutable'); END;
CREATE TRIGGER linux_deployment_event_delete BEFORE DELETE ON linux_deployment_event
BEGIN SELECT RAISE(ABORT,'linux_deployment_event_immutable'); END;
CREATE TRIGGER linux_deployment_event_transition BEFORE INSERT ON linux_deployment_event
WHEN NOT (
  (NEW.revision=1 AND NEW.phase='launching' AND
    coalesce((SELECT phase FROM linux_deployment_event ORDER BY serial DESC LIMIT 1),'retired')='retired')
  OR EXISTS (
    SELECT 1 FROM linux_deployment_event p
    WHERE p.serial=(SELECT max(serial) FROM linux_deployment_event)
      AND p.generation_id=NEW.generation_id AND p.revision+1=NEW.revision
      AND ((p.phase='launching' AND NEW.phase='running')
        OR (p.phase='running' AND NEW.phase='closing')
        OR (p.phase='closing' AND NEW.phase IN ('retired','indeterminate')))
  )
)
BEGIN SELECT RAISE(ABORT,'linux_deployment_transition'); END;
