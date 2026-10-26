-- 追加到255表候选，不替代真实运行时准入或监督来源认证。
CREATE TABLE sr_adoption(
 exit_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_exit(exit_id),
 adoption_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL,
 binding_digest TEXT NOT NULL, source_bundle_digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16777216),
 FOREIGN KEY(exit_id) REFERENCES ce_retirement(exit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(exit_id) REFERENCES sr_commit(exit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE sr_commit(
 exit_id TEXT PRIMARY KEY NOT NULL REFERENCES sr_adoption(exit_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TRIGGER sr_adoption_guard BEFORE INSERT ON sr_adoption BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id)
 THEN RAISE(ABORT,'supervisor_retirement_already_recorded') END;
END;
CREATE TRIGGER sr_retirement_guard BEFORE INSERT ON ce_retirement
WHEN EXISTS(SELECT 1 FROM sr_adoption WHERE exit_id=NEW.exit_id) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sr_adoption a WHERE a.exit_id=NEW.exit_id AND a.body=NEW.supervisor_evidence_body
 AND NOT EXISTS(SELECT 1 FROM sr_commit k WHERE k.exit_id=a.exit_id)) THEN RAISE(ABORT,'supervisor_retirement_original') END;
END;
CREATE TRIGGER sr_seal_guard BEFORE INSERT ON sr_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sr_adoption a JOIN ce_retirement r USING(exit_id)
 WHERE a.exit_id=NEW.exit_id AND a.body=r.supervisor_evidence_body AND NEW.outbox_body=a.body)
 THEN RAISE(ABORT,'supervisor_retirement_incomplete') END;
END;
CREATE VIEW sr_current AS SELECT a.* FROM sr_adoption a JOIN sr_commit k USING(exit_id) JOIN ce_retirement r USING(exit_id)
 WHERE NOT EXISTS(SELECT 1 FROM cu_revocation v WHERE v.kind='retirement' AND v.object_id=a.exit_id);
-- 物理退役历史永不恢复发送，证明被撤回也不能复活旧worker。
CREATE VIEW sr_stopped_session AS SELECT DISTINCT x.session_id FROM ij_exit x JOIN sr_commit k USING(exit_id);
CREATE TRIGGER sr_no_old_write BEFORE INSERT ON ij_write_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ij_frame f JOIN sr_stopped_session s USING(session_id) WHERE f.frame_id=NEW.frame_id)
 THEN RAISE(ABORT,'supervisor_retired_session') END;
END;
CREATE TRIGGER sr_adoption_no_update BEFORE UPDATE ON sr_adoption BEGIN SELECT RAISE(ABORT,'immutable supervisor retirement'); END;
CREATE TRIGGER sr_adoption_no_delete BEFORE DELETE ON sr_adoption BEGIN SELECT RAISE(ABORT,'immutable supervisor retirement'); END;
CREATE TRIGGER sr_commit_no_update BEFORE UPDATE ON sr_commit BEGIN SELECT RAISE(ABORT,'immutable supervisor retirement'); END;
CREATE TRIGGER sr_commit_no_delete BEFORE DELETE ON sr_commit BEGIN SELECT RAISE(ABORT,'immutable supervisor retirement'); END;
