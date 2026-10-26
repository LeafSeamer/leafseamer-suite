-- 局部候选仅在既有撤销账本为空时安装；不是生产数据迁移。
CREATE TABLE authorization_revocation_order (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id TEXT NOT NULL UNIQUE REFERENCES authorization_floor_event(event_id),
 CHECK(sequence>0)
) STRICT;
CREATE TRIGGER authorization_floor_order AFTER INSERT ON authorization_floor_event BEGIN
 INSERT INTO authorization_revocation_order(event_id) VALUES(NEW.event_id);
END;
CREATE TRIGGER authorization_order_no_update BEFORE UPDATE ON authorization_revocation_order BEGIN SELECT RAISE(ABORT,'immutable revocation order'); END;
CREATE TRIGGER authorization_order_no_delete BEFORE DELETE ON authorization_revocation_order BEGIN SELECT RAISE(ABORT,'immutable revocation order'); END;
CREATE TABLE authorization_revocation_snapshot (
 snapshot_id TEXT PRIMARY KEY NOT NULL,
 use_id TEXT NOT NULL REFERENCES authorization_use(use_id),
 last_sequence INTEGER REFERENCES authorization_revocation_order(sequence),
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TRIGGER authorization_revocation_snapshot_no_update BEFORE UPDATE ON authorization_revocation_snapshot BEGIN SELECT RAISE(ABORT,'immutable revocation snapshot'); END;
CREATE TRIGGER authorization_revocation_snapshot_no_delete BEFORE DELETE ON authorization_revocation_snapshot BEGIN SELECT RAISE(ABORT,'immutable revocation snapshot'); END;
