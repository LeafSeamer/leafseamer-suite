-- 内部局部候选：加载在现有Controller候选库中，不是生产迁移或独立身份库。
CREATE TABLE authorization_use (
 use_id TEXT PRIMARY KEY NOT NULL,
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TABLE authorization_floor_event (
 event_id TEXT PRIMARY KEY NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('session','principal','credential','grant','extension','trust')),
 issuer_id TEXT NOT NULL,
 issuer_epoch TEXT NOT NULL,
 target_id TEXT NOT NULL,
 revision_floor TEXT NOT NULL CHECK(length(revision_floor)=20 AND revision_floor NOT GLOB '*[^0-9]*'),
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE INDEX authorization_floor_target ON authorization_floor_event(kind,issuer_id,issuer_epoch,target_id);
CREATE TRIGGER authorization_use_no_update BEFORE UPDATE ON authorization_use BEGIN SELECT RAISE(ABORT,'immutable authorization use'); END;
CREATE TRIGGER authorization_use_no_delete BEFORE DELETE ON authorization_use BEGIN SELECT RAISE(ABORT,'immutable authorization use'); END;
CREATE TRIGGER authorization_floor_no_update BEFORE UPDATE ON authorization_floor_event BEGIN SELECT RAISE(ABORT,'immutable authorization floor'); END;
CREATE TRIGGER authorization_floor_no_delete BEFORE DELETE ON authorization_floor_event BEGIN SELECT RAISE(ABORT,'immutable authorization floor'); END;
