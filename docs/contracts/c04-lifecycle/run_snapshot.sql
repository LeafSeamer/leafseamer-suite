-- 运行拒绝快照来源；复用已提交账本，不创建另一套拒绝权威。
CREATE TABLE rs_snapshot(
 snapshot_id TEXT PRIMARY KEY,
 snapshot_revision TEXT NOT NULL CHECK(length(snapshot_revision)=20 AND snapshot_revision NOT GLOB '*[^0-9]*'),
 entry_count INTEGER NOT NULL CHECK(entry_count BETWEEN 0 AND 4096),
 snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=71 AND substr(snapshot_digest,1,7)='sha256:'),
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216),
 FOREIGN KEY(snapshot_id) REFERENCES rs_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE rs_commit(
 snapshot_id TEXT PRIMARY KEY REFERENCES rs_snapshot(snapshot_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER rs_snapshot_guard BEFORE INSERT ON rs_snapshot BEGIN
 SELECT CASE WHEN NEW.snapshot_revision!=(SELECT revision FROM run_deny_snapshot_revision)
 OR NEW.entry_count!=(SELECT count(*) FROM run_deny_current)
 THEN RAISE(ABORT,'run_snapshot_frontier') END;
END;
CREATE TRIGGER rs_commit_guard BEFORE INSERT ON rs_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rs_snapshot s WHERE s.snapshot_id=NEW.snapshot_id
 AND s.snapshot_revision=(SELECT revision FROM run_deny_snapshot_revision)
 AND s.entry_count=(SELECT count(*) FROM run_deny_current) AND NEW.audit_body=s.body)
 THEN RAISE(ABORT,'run_snapshot_seal') END;
END;
CREATE VIEW rs_current AS SELECT s.* FROM rs_snapshot s JOIN rs_commit c USING(snapshot_id)
 WHERE s.snapshot_revision=(SELECT revision FROM run_deny_snapshot_revision);
CREATE TRIGGER rs_snapshot_u BEFORE UPDATE ON rs_snapshot BEGIN SELECT RAISE(ABORT,'immutable_run_snapshot'); END;
CREATE TRIGGER rs_snapshot_d BEFORE DELETE ON rs_snapshot BEGIN SELECT RAISE(ABORT,'immutable_run_snapshot'); END;
CREATE TRIGGER rs_commit_u BEFORE UPDATE ON rs_commit BEGIN SELECT RAISE(ABORT,'immutable_run_snapshot'); END;
CREATE TRIGGER rs_commit_d BEFORE DELETE ON rs_commit BEGIN SELECT RAISE(ABORT,'immutable_run_snapshot'); END;
