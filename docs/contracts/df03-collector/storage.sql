-- 设计候选：只在隔离内存数据库验证，不是生产迁移。
PRAGMA foreign_keys=ON;
PRAGMA recursive_triggers=ON;
CREATE TABLE ts_scope (
 id INTEGER PRIMARY KEY CHECK(id=1), authority TEXT NOT NULL, database_id TEXT NOT NULL,
 version TEXT NOT NULL CHECK(version='reference-time-storage/0.1.0-draft.1')
) STRICT;
CREATE TABLE ts_binding (
 id TEXT PRIMARY KEY NOT NULL, scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES ts_scope(id),
 generation TEXT NOT NULL CHECK(length(generation)=20 AND generation NOT GLOB '*[^0-9]*'),
 body BLOB NOT NULL, UNIQUE(id,generation)
) STRICT;
CREATE TABLE ts_poll (
 id TEXT PRIMARY KEY NOT NULL, binding_id TEXT NOT NULL REFERENCES ts_binding(id),
 correlation_id TEXT NOT NULL UNIQUE, body BLOB NOT NULL, UNIQUE(id,binding_id)
) STRICT;
CREATE TABLE ts_commit (
 id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL CHECK(kind IN('bootstrap','publish','reject','failure','invalidate')),
 receipt_body BLOB NOT NULL,
 FOREIGN KEY(id) REFERENCES ts_seal(commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(id) REFERENCES ts_audit(commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(id) REFERENCES ts_outbox(commit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ts_capture (
 id TEXT PRIMARY KEY NOT NULL, poll_id TEXT NOT NULL UNIQUE, binding_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN('candidate','failed','indeterminate')),
 disposition TEXT NOT NULL CHECK(disposition IN('published','rejected','failure_recorded')),
 blob_count INTEGER NOT NULL CHECK(blob_count BETWEEN 0 AND 3),
 commit_id TEXT NOT NULL UNIQUE REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 body BLOB NOT NULL, UNIQUE(id,binding_id),
 FOREIGN KEY(poll_id,binding_id) REFERENCES ts_poll(id,binding_id),
 CHECK(disposition!='published' OR (status='candidate' AND blob_count=2))
) STRICT;
CREATE TABLE ts_blob (
 capture_id TEXT NOT NULL REFERENCES ts_capture(id), slot TEXT NOT NULL CHECK(slot IN('request','response','diagnostic')),
 plain_digest TEXT NOT NULL, plain_size INTEGER NOT NULL CHECK(plain_size BETWEEN 0 AND 65536),
 ciphertext BLOB NOT NULL CHECK(length(ciphertext) BETWEEN 1 AND 131072),
 body BLOB NOT NULL, PRIMARY KEY(capture_id,slot)
) STRICT;
CREATE TABLE ts_verification (
 capture_id TEXT PRIMARY KEY NOT NULL, binding_id TEXT NOT NULL, body BLOB NOT NULL,
 FOREIGN KEY(capture_id,binding_id) REFERENCES ts_capture(id,binding_id)
) STRICT;
CREATE TABLE ts_anchor (
 id TEXT PRIMARY KEY NOT NULL, capture_id TEXT NOT NULL UNIQUE, binding_id TEXT NOT NULL,
 tick TEXT NOT NULL CHECK(length(tick)=20 AND tick NOT GLOB '*[^0-9]*'), body BLOB NOT NULL,
 UNIQUE(id,binding_id), FOREIGN KEY(capture_id,binding_id) REFERENCES ts_capture(id,binding_id),
 FOREIGN KEY(capture_id) REFERENCES ts_verification(capture_id)
) STRICT;
CREATE TABLE ts_state (
 revision TEXT PRIMARY KEY NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*' AND revision!='00000000000000000000'),
 previous TEXT REFERENCES ts_state(revision), binding_id TEXT NOT NULL REFERENCES ts_binding(id),
 status TEXT NOT NULL CHECK(status IN('collecting','qualified','unavailable')),
 anchor_id TEXT, commit_id TEXT NOT NULL UNIQUE REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 body BLOB NOT NULL,
 FOREIGN KEY(anchor_id,binding_id) REFERENCES ts_anchor(id,binding_id),
 CHECK((status='qualified' AND anchor_id IS NOT NULL) OR (status!='qualified' AND anchor_id IS NULL))
) STRICT;
CREATE TABLE ts_head (
 id INTEGER PRIMARY KEY CHECK(id=1), revision TEXT NOT NULL REFERENCES ts_state(revision)
) STRICT;
CREATE TABLE ts_invalidation (
 id TEXT PRIMARY KEY NOT NULL, old_binding TEXT NOT NULL REFERENCES ts_binding(id),
 new_binding TEXT NOT NULL REFERENCES ts_binding(id),
 commit_id TEXT NOT NULL UNIQUE REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 protection_ref BLOB NOT NULL, body BLOB NOT NULL, CHECK(old_binding!=new_binding)
) STRICT;
CREATE TABLE ts_audit (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 body BLOB NOT NULL
) STRICT;
CREATE TABLE ts_outbox (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 kind TEXT NOT NULL CHECK(kind IN('notification','time_fence')), body BLOB NOT NULL
) STRICT;
CREATE TABLE ts_seal (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES ts_commit(id), body BLOB NOT NULL
) STRICT;

-- 精确后继：两段各10位，不把完整U20转换为64位整数或REAL。
CREATE TRIGGER ts_state_sequence BEFORE INSERT ON ts_state BEGIN
 SELECT CASE WHEN NEW.previous IS NULL AND (NEW.revision!='00000000000000000001' OR EXISTS(SELECT 1 FROM ts_state))
 THEN RAISE(ABORT,'initial_revision') END;
 SELECT CASE WHEN NEW.previous IS NOT NULL AND (
 NOT EXISTS(SELECT 1 FROM ts_head WHERE revision=NEW.previous) OR
 NEW.previous='99999999999999999999' OR
 NEW.revision != printf('%010d%010d',
 CAST(substr(NEW.previous,1,10) AS INTEGER)+(CAST(substr(NEW.previous,11,10) AS INTEGER)=9999999999),
 (CAST(substr(NEW.previous,11,10) AS INTEGER)+1)%10000000000))
 THEN RAISE(ABORT,'state_cas') END;
END;
CREATE TRIGGER ts_head_step BEFORE UPDATE ON ts_head BEGIN
 SELECT CASE WHEN NEW.id!=OLD.id OR NOT EXISTS(SELECT 1 FROM ts_state WHERE revision=NEW.revision AND previous=OLD.revision)
 THEN RAISE(ABORT,'head_cas') END;
END;
CREATE TRIGGER ts_poll_current BEFORE INSERT ON ts_poll BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ts_head h JOIN ts_state s ON s.revision=h.revision
 JOIN ts_seal z ON z.commit_id=s.commit_id WHERE s.binding_id=NEW.binding_id AND s.status IN('collecting','qualified'))
 THEN RAISE(ABORT,'poll_not_current') END;
END;
CREATE TRIGGER ts_seal_validate BEFORE INSERT ON ts_seal BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ts_audit WHERE commit_id=NEW.commit_id)
 OR NOT EXISTS(SELECT 1 FROM ts_outbox WHERE commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'missing_delivery') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ts_capture c WHERE c.commit_id=NEW.commit_id AND
 c.blob_count!=(SELECT count(*) FROM ts_blob b WHERE b.capture_id=c.id))
 THEN RAISE(ABORT,'blob_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ts_commit c JOIN ts_outbox o ON o.commit_id=c.id WHERE c.id=NEW.commit_id
 AND ((c.kind='invalidate')!=(o.kind='time_fence')))
 THEN RAISE(ABORT,'outbox_kind') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id) IN('bootstrap','publish','invalidate') AND
 NOT EXISTS(SELECT 1 FROM ts_state s JOIN ts_head h ON h.revision=s.revision WHERE s.commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'missing_current_state') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id) IN('reject','failure') AND
 (EXISTS(SELECT 1 FROM ts_state WHERE commit_id=NEW.commit_id) OR
 NOT EXISTS(SELECT 1 FROM ts_capture WHERE commit_id=NEW.commit_id AND
 disposition=CASE (SELECT kind FROM ts_commit WHERE id=NEW.commit_id) WHEN 'reject' THEN 'rejected' ELSE 'failure_recorded' END))
 THEN RAISE(ABORT,'failure_state') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id) IN('bootstrap','invalidate') AND
 EXISTS(SELECT 1 FROM ts_capture WHERE commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'unexpected_capture') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)='bootstrap' AND
 EXISTS(SELECT 1 FROM ts_state s LEFT JOIN ts_state p ON p.revision=s.previous WHERE s.commit_id=NEW.commit_id AND
 (s.status!='collecting' OR (s.previous IS NOT NULL AND (p.status!='unavailable' OR s.binding_id!=p.binding_id))))
 THEN RAISE(ABORT,'bootstrap_state') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)='publish' AND NOT EXISTS(
 SELECT 1 FROM ts_capture c JOIN ts_anchor a ON a.capture_id=c.id
 JOIN ts_state s ON s.commit_id=c.commit_id JOIN ts_state p ON p.revision=s.previous
 WHERE c.commit_id=NEW.commit_id AND c.disposition='published' AND c.status='candidate'
 AND s.status='qualified' AND s.anchor_id=a.id AND s.binding_id=c.binding_id AND p.binding_id=c.binding_id
 AND p.status IN('collecting','qualified') AND
 (p.anchor_id IS NULL OR a.tick>(SELECT tick FROM ts_anchor WHERE id=p.anchor_id))
 AND EXISTS(SELECT 1 FROM ts_blob WHERE capture_id=c.id AND slot='request')
 AND EXISTS(SELECT 1 FROM ts_blob WHERE capture_id=c.id AND slot='response'))
 THEN RAISE(ABORT,'publish_chain') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)!='publish' AND
 EXISTS(SELECT 1 FROM ts_capture c JOIN ts_anchor a ON a.capture_id=c.id WHERE c.commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'unexpected_anchor') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)='invalidate' AND NOT EXISTS(
 SELECT 1 FROM ts_invalidation i JOIN ts_state s ON s.commit_id=i.commit_id JOIN ts_state p ON p.revision=s.previous
 JOIN ts_binding old ON old.id=i.old_binding JOIN ts_binding next ON next.id=i.new_binding
 WHERE i.commit_id=NEW.commit_id AND p.binding_id=i.old_binding AND s.binding_id=i.new_binding
 AND s.status='unavailable' AND old.generation!='99999999999999999999'
 AND next.generation=printf('%010d%010d',CAST(substr(old.generation,1,10) AS INTEGER)+(CAST(substr(old.generation,11,10) AS INTEGER)=9999999999),
 (CAST(substr(old.generation,11,10) AS INTEGER)+1)%10000000000))
 THEN RAISE(ABORT,'invalidation_chain') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)!='invalidate' AND
 EXISTS(SELECT 1 FROM ts_invalidation WHERE commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'unexpected_invalidation') END;
END;

-- 不可变保护完整安装在本文件中，检查脚本不能补建约束。
CREATE TRIGGER ts_scope_no_update BEFORE UPDATE ON ts_scope BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_scope_no_delete BEFORE DELETE ON ts_scope BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_binding_no_update BEFORE UPDATE ON ts_binding BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_binding_no_delete BEFORE DELETE ON ts_binding BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_poll_no_update BEFORE UPDATE ON ts_poll BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_poll_no_delete BEFORE DELETE ON ts_poll BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_commit_no_update BEFORE UPDATE ON ts_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_commit_no_delete BEFORE DELETE ON ts_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_capture_no_update BEFORE UPDATE ON ts_capture BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_capture_no_delete BEFORE DELETE ON ts_capture BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_blob_no_update BEFORE UPDATE ON ts_blob BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_blob_no_delete BEFORE DELETE ON ts_blob BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_verification_no_update BEFORE UPDATE ON ts_verification BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_verification_no_delete BEFORE DELETE ON ts_verification BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_anchor_no_update BEFORE UPDATE ON ts_anchor BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_anchor_no_delete BEFORE DELETE ON ts_anchor BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_state_no_update BEFORE UPDATE ON ts_state BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_state_no_delete BEFORE DELETE ON ts_state BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_head_no_delete BEFORE DELETE ON ts_head BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_invalidation_no_update BEFORE UPDATE ON ts_invalidation BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_invalidation_no_delete BEFORE DELETE ON ts_invalidation BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_audit_no_update BEFORE UPDATE ON ts_audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_audit_no_delete BEFORE DELETE ON ts_audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_outbox_no_update BEFORE UPDATE ON ts_outbox BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_outbox_no_delete BEFORE DELETE ON ts_outbox BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_seal_no_update BEFORE UPDATE ON ts_seal BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_seal_no_delete BEFORE DELETE ON ts_seal BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_capture_closed BEFORE INSERT ON ts_capture WHEN EXISTS(SELECT 1 FROM ts_seal WHERE commit_id=NEW.commit_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_blob_closed BEFORE INSERT ON ts_blob WHEN EXISTS(SELECT 1 FROM ts_capture c JOIN ts_seal z ON z.commit_id=c.commit_id WHERE c.id=NEW.capture_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_verification_closed BEFORE INSERT ON ts_verification WHEN EXISTS(SELECT 1 FROM ts_capture c JOIN ts_seal z ON z.commit_id=c.commit_id WHERE c.id=NEW.capture_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_anchor_closed BEFORE INSERT ON ts_anchor WHEN EXISTS(SELECT 1 FROM ts_capture c JOIN ts_seal z ON z.commit_id=c.commit_id WHERE c.id=NEW.capture_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_state_closed BEFORE INSERT ON ts_state WHEN EXISTS(SELECT 1 FROM ts_seal WHERE commit_id=NEW.commit_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_invalidation_closed BEFORE INSERT ON ts_invalidation WHEN EXISTS(SELECT 1 FROM ts_seal WHERE commit_id=NEW.commit_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE VIEW ts_current AS SELECT s.* FROM ts_head h JOIN ts_state s ON s.revision=h.revision JOIN ts_seal z ON z.commit_id=s.commit_id;
