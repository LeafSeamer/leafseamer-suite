-- 追加到collector-storage-v02；离线设计候选，不是生产迁移。
CREATE TABLE tp_runtime (
 id TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 262144)
) STRICT;
CREATE TABLE tp_adoption (
 channel_id TEXT PRIMARY KEY NOT NULL, runtime_id TEXT NOT NULL UNIQUE REFERENCES tp_runtime(id),
 binding_id TEXT NOT NULL UNIQUE REFERENCES ts_binding(id), bootstrap_commit TEXT NOT NULL UNIQUE,
 id TEXT NOT NULL UNIQUE, body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 262144),
 audit_body BLOB NOT NULL, outbox_body BLOB NOT NULL,
 FOREIGN KEY(channel_id,binding_id) REFERENCES tc_channel(id,binding_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(bootstrap_commit) REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(body=audit_body AND body=outbox_body)
) STRICT;
CREATE TABLE tp_revocation (
 channel_id TEXT PRIMARY KEY NOT NULL REFERENCES tp_adoption(channel_id),
 invalidation_commit TEXT NOT NULL UNIQUE REFERENCES ts_invalidation(commit_id) DEFERRABLE INITIALLY DEFERRED,
 stop_id TEXT NOT NULL UNIQUE, body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 262144),
 FOREIGN KEY(stop_id,channel_id) REFERENCES tc_stop(id,channel_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER tp_channel_bound BEFORE INSERT ON tc_channel BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tp_adoption a WHERE a.channel_id=NEW.id AND a.binding_id=NEW.binding_id)
 THEN RAISE(ABORT,'provider_adoption_required') END;
END;
CREATE TRIGGER tp_bootstrap_bound BEFORE INSERT ON ts_state WHEN NEW.status='collecting' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tp_adoption a WHERE a.binding_id=NEW.binding_id AND a.bootstrap_commit=NEW.commit_id)
 THEN RAISE(ABORT,'provider_bootstrap_required') END;
END;
CREATE TRIGGER tp_revocation_bound BEFORE INSERT ON tp_revocation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tp_adoption a JOIN ts_invalidation i ON i.old_binding=a.binding_id
 WHERE a.channel_id=NEW.channel_id AND i.commit_id=NEW.invalidation_commit)
 THEN RAISE(ABORT,'provider_revocation_binding') END;
END;
CREATE TRIGGER tp_stop_bound BEFORE INSERT ON tc_stop BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tp_revocation r WHERE r.channel_id=NEW.channel_id
 AND r.invalidation_commit=NEW.invalidation_commit AND r.stop_id=NEW.id)
 THEN RAISE(ABORT,'provider_revocation_required') END;
END;
CREATE TRIGGER tp_runtime_no_update BEFORE UPDATE ON tp_runtime BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tp_runtime_no_delete BEFORE DELETE ON tp_runtime BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tp_adoption_no_update BEFORE UPDATE ON tp_adoption BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tp_adoption_no_delete BEFORE DELETE ON tp_adoption BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tp_revocation_no_update BEFORE UPDATE ON tp_revocation BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tp_revocation_no_delete BEFORE DELETE ON tp_revocation BEGIN SELECT RAISE(ABORT,'immutable'); END;
