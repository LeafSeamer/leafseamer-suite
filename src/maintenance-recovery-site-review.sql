CREATE TABLE maintenance_recovery_site_review (
  review_id TEXT PRIMARY KEY,
  restore_id TEXT NOT NULL REFERENCES maintenance_recovery_preparation_result(restore_id),
  revision INTEGER NOT NULL CHECK(revision>=1),
  previous_digest TEXT,
  body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 524288),
  digest TEXT NOT NULL,
  UNIQUE(restore_id,revision), UNIQUE(restore_id,digest),
  FOREIGN KEY(restore_id,previous_digest) REFERENCES maintenance_recovery_site_review(restore_id,digest)
) STRICT;
CREATE TRIGGER maintenance_recovery_site_review_sequence BEFORE INSERT ON maintenance_recovery_site_review
WHEN NEW.revision!=COALESCE((SELECT max(revision) FROM maintenance_recovery_site_review WHERE restore_id=NEW.restore_id),0)+1
 OR NEW.previous_digest IS NOT (SELECT digest FROM maintenance_recovery_site_review WHERE restore_id=NEW.restore_id ORDER BY revision DESC LIMIT 1)
BEGIN SELECT RAISE(ABORT,'recovery_site_review_conflict'); END;
CREATE TRIGGER maintenance_recovery_site_review_update BEFORE UPDATE ON maintenance_recovery_site_review
BEGIN SELECT RAISE(ABORT,'immutable_recovery_site_review'); END;
CREATE TRIGGER maintenance_recovery_site_review_delete BEFORE DELETE ON maintenance_recovery_site_review
BEGIN SELECT RAISE(ABORT,'immutable_recovery_site_review'); END;
