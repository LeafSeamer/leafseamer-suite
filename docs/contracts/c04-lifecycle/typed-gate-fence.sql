-- 安装后新增换闸请求必须拥有完整原件；旧请求留作兼容历史。
CREATE TABLE tf_origin(
 request_id TEXT PRIMARY KEY REFERENCES gf_request(request_id) DEFERRABLE INITIALLY DEFERRED,
 close_id TEXT NOT NULL REFERENCES go_close(close_id),closure_id TEXT NOT NULL REFERENCES pd_closure(closure_id),
 digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0)
) STRICT;
ALTER TABLE gf_request ADD COLUMN original_id TEXT REFERENCES tf_origin(request_id) DEFERRABLE INITIALLY DEFERRED;
CREATE TRIGGER tf_request_required BEFORE INSERT ON gf_request
 WHEN NEW.original_id IS NOT NEW.request_id BEGIN SELECT RAISE(ABORT,'typed_fence_origin_required'); END;
CREATE VIEW tf_current_origin AS SELECT o.request_id FROM tf_origin o JOIN gf_request r USING(request_id)
 JOIN pd_close_completion c ON c.close_id=o.close_id AND c.closure_id=o.closure_id AND c.ack_id=r.close_ack_id
 JOIN pd_valid_closure p ON p.closure_id=c.closure_id
 WHERE EXISTS(SELECT 1 FROM gate_close_usable_ack a WHERE a.close_id=o.close_id AND a.adopted_ack_id=r.close_ack_id)
 OR EXISTS(SELECT 1 FROM authorization_close_usable_ack a WHERE a.close_id=o.close_id AND a.adopted_ack_id=r.close_ack_id);
CREATE TRIGGER tf_origin_guard AFTER INSERT ON tf_origin BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tf_current_origin WHERE request_id=NEW.request_id)
 THEN RAISE(ABORT,'typed_fence_close_not_current') END;
END;
CREATE TRIGGER tf_attempt_guard BEFORE INSERT ON ij_write_attempt
 WHEN EXISTS(SELECT 1 FROM gf_request r WHERE r.journal_frame_id=NEW.frame_id AND r.original_id IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM gf_request r JOIN tf_current_origin o USING(request_id) WHERE r.journal_frame_id=NEW.frame_id)
 BEGIN SELECT RAISE(ABORT,'typed_fence_close_not_current'); END;
CREATE TRIGGER tf_ack_attempt BEFORE INSERT ON gf_ack
 WHEN EXISTS(SELECT 1 FROM gf_request WHERE request_id=NEW.request_id AND original_id IS NOT NULL) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_request r JOIN ij_write_attempt w ON w.frame_id=r.journal_frame_id
 WHERE r.request_id=NEW.request_id AND w.attempted_tick<=NEW.effective_tick)
 THEN RAISE(ABORT,'typed_fence_ack_before_attempt') END;
END;
CREATE TRIGGER tf_commit_current BEFORE INSERT ON gf_commit
 WHEN EXISTS(SELECT 1 FROM gf_request WHERE request_id=NEW.request_id AND original_id IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM tf_current_origin WHERE request_id=NEW.request_id)
 BEGIN SELECT RAISE(ABORT,'typed_fence_close_not_current'); END;
DROP VIEW gf_valid_fence;
CREATE VIEW gf_valid_fence AS SELECT b.* FROM ij_base_gf_valid_fence b JOIN ij_exit x ON x.exit_id=b.exit_id
 JOIN gf_request r USING(request_id)
 WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id)
 AND (r.original_id IS NULL OR EXISTS(SELECT 1 FROM tf_current_origin o WHERE o.request_id=r.request_id));
CREATE TRIGGER tf_origin_u BEFORE UPDATE ON tf_origin BEGIN SELECT RAISE(ABORT,'immutable_typed_fence'); END;
CREATE TRIGGER tf_origin_d BEFORE DELETE ON tf_origin BEGIN SELECT RAISE(ABORT,'immutable_typed_fence'); END;
