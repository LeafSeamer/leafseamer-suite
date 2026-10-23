-- Controller共库设计参考；只能与本目录生成的裁决/准备投影一起加载。
CREATE TABLE controller_scope (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  authority_service_id TEXT NOT NULL CHECK(length(authority_service_id)>0),
  database_instance_id TEXT NOT NULL CHECK(length(database_instance_id)>0),
  layout_version TEXT NOT NULL CHECK(layout_version='controller-storage/0.1.0-draft.1')
) STRICT;
CREATE TABLE run_protection_request (
  protection_id TEXT PRIMARY KEY NOT NULL,
  scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
  origin_authority TEXT NOT NULL, origin_database TEXT NOT NULL,
  operation_id TEXT NOT NULL, run_id TEXT NOT NULL,
  generation TEXT NOT NULL CHECK(length(generation)=20 AND generation NOT GLOB '*[^0-9]*' AND generation>'00000000000000000000'),
  request_digest TEXT NOT NULL, selector_digest TEXT NOT NULL, target_set_digest TEXT NOT NULL,
  request_body BLOB NOT NULL CHECK(length(request_body)>0),
  authorization_body BLOB NOT NULL CHECK(length(authorization_body)>0),
  registry_snapshot_body BLOB NOT NULL CHECK(length(registry_snapshot_body)>0),
  capacity_reservation_body BLOB NOT NULL CHECK(length(capacity_reservation_body)>0),
  target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),
  UNIQUE(origin_authority,origin_database,operation_id),
  FOREIGN KEY(protection_id) REFERENCES run_protection_commit(protection_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE run_protection_target (
  protection_id TEXT NOT NULL REFERENCES run_protection_request(protection_id),
  target_id TEXT NOT NULL, target_body BLOB NOT NULL CHECK(length(target_body)>0),
  PRIMARY KEY(protection_id,target_id)
) STRICT;
CREATE TABLE run_protection_commit (
  protection_id TEXT PRIMARY KEY NOT NULL REFERENCES run_protection_request(protection_id),
  commit_ref_body BLOB NOT NULL CHECK(length(commit_ref_body)>0),
  FOREIGN KEY(protection_id) REFERENCES run_protection_audit(protection_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(protection_id) REFERENCES run_protection_outbox(protection_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE run_protection_audit (
  protection_id TEXT PRIMARY KEY NOT NULL,
  redacted_body BLOB NOT NULL CHECK(length(redacted_body)>0),
  FOREIGN KEY(protection_id) REFERENCES run_protection_commit(protection_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE run_protection_outbox (
  protection_id TEXT PRIMARY KEY NOT NULL, event_id TEXT NOT NULL UNIQUE,
  payload_body BLOB NOT NULL CHECK(length(payload_body)>0),
  FOREIGN KEY(protection_id) REFERENCES run_protection_commit(protection_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

-- 两种合法来源互斥；prepare close无须伪造HTTP ProtectionRequest。
CREATE TABLE run_deny_event (
  snapshot_revision TEXT PRIMARY KEY NOT NULL CHECK(length(snapshot_revision)=20 AND snapshot_revision NOT GLOB '*[^0-9]*' AND snapshot_revision>'00000000000000000000'),
  origin_authority TEXT NOT NULL, origin_database TEXT NOT NULL, run_id TEXT NOT NULL,
  generation TEXT NOT NULL CHECK(length(generation)=20 AND generation NOT GLOB '*[^0-9]*' AND generation>'00000000000000000000'),
  deny_revision TEXT NOT NULL CHECK(length(deny_revision)=20 AND deny_revision NOT GLOB '*[^0-9]*' AND deny_revision>'00000000000000000000'),
  close_id TEXT UNIQUE REFERENCES cp_close(close_id),
  commit_id TEXT REFERENCES cp_commit(commit_id) DEFERRABLE INITIALLY DEFERRED,
  protection_id TEXT UNIQUE REFERENCES run_protection_request(protection_id),
  CHECK((close_id IS NOT NULL AND commit_id IS NOT NULL AND protection_id IS NULL)
     OR (close_id IS NULL AND commit_id IS NULL AND protection_id IS NOT NULL)),
  UNIQUE(origin_authority,origin_database,run_id,deny_revision)
) STRICT;
CREATE VIEW run_deny_committed AS
 SELECT d.* FROM run_deny_event d WHERE
  EXISTS(SELECT 1 FROM cp_commit c WHERE c.commit_id=d.commit_id)
  OR EXISTS(SELECT 1 FROM run_protection_commit c WHERE c.protection_id=d.protection_id);
CREATE VIEW run_deny_current AS
 SELECT d.* FROM run_deny_committed d WHERE NOT EXISTS(
  SELECT 1 FROM run_deny_committed n
  WHERE (n.origin_authority,n.origin_database,n.run_id)=(d.origin_authority,d.origin_database,d.run_id)
    AND n.generation>d.generation);
-- 空账本revision为0，线上快照另由SDK计算完整排序正文和摘要。
CREATE VIEW run_deny_snapshot_revision AS
 SELECT coalesce(max(snapshot_revision),'00000000000000000000') AS revision FROM run_deny_committed;

CREATE TRIGGER run_deny_guard BEFORE INSERT ON run_deny_event BEGIN
 SELECT CASE WHEN (NEW.commit_id IS NOT NULL AND EXISTS(SELECT 1 FROM cp_commit WHERE commit_id=NEW.commit_id))
   OR (NEW.protection_id IS NOT NULL AND EXISTS(SELECT 1 FROM run_protection_commit WHERE protection_id=NEW.protection_id))
   THEN RAISE(ABORT,'commit_frozen') END;
 SELECT CASE WHEN NEW.close_id IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM cp_close c JOIN cp_request r ON r.prep_key=c.prep_key
   WHERE c.close_id=NEW.close_id AND c.commit_id=NEW.commit_id
    AND (r.origin_authority,r.origin_database,r.run_id,r.generation)=
        (NEW.origin_authority,NEW.origin_database,NEW.run_id,NEW.generation))
   THEN RAISE(ABORT,'deny_binding') END;
 SELECT CASE WHEN NEW.protection_id IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM run_protection_request r WHERE r.protection_id=NEW.protection_id
    AND (r.origin_authority,r.origin_database,r.run_id,r.generation)=
        (NEW.origin_authority,NEW.origin_database,NEW.run_id,NEW.generation))
   THEN RAISE(ABORT,'deny_binding') END;
 SELECT CASE WHEN NEW.snapshot_revision!=(
   SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
                 (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
   FROM (SELECT coalesce(max(snapshot_revision),'00000000000000000000') v FROM run_deny_event))
   THEN RAISE(ABORT,'snapshot_successor') END;
 SELECT CASE WHEN NEW.deny_revision!=(
   SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
                 (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
   FROM (SELECT coalesce(max(deny_revision),'00000000000000000000') v FROM run_deny_event
     WHERE (origin_authority,origin_database,run_id)=(NEW.origin_authority,NEW.origin_database,NEW.run_id)))
   THEN RAISE(ABORT,'deny_successor') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM run_deny_event
   WHERE (origin_authority,origin_database,run_id)=(NEW.origin_authority,NEW.origin_database,NEW.run_id)
     AND generation>=NEW.generation) THEN RAISE(ABORT,'deny_not_increased') END;
END;
CREATE TRIGGER run_protection_commit_guard BEFORE INSERT ON run_protection_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(
   SELECT 1 FROM run_protection_request r WHERE r.protection_id=NEW.protection_id
    AND r.target_count=(SELECT count(*) FROM run_protection_target t WHERE t.protection_id=r.protection_id)
    AND EXISTS(SELECT 1 FROM run_deny_event d
      WHERE (d.origin_authority,d.origin_database,d.run_id)=(r.origin_authority,r.origin_database,r.run_id)
        AND d.generation>=r.generation AND
        (d.protection_id=NEW.protection_id OR EXISTS(
          SELECT 1 FROM run_deny_committed c WHERE c.snapshot_revision=d.snapshot_revision))))
   THEN RAISE(ABORT,'protection_incomplete') END;
END;
CREATE TRIGGER run_protection_targets_frozen BEFORE INSERT ON run_protection_target
 WHEN EXISTS(SELECT 1 FROM run_protection_commit WHERE protection_id=NEW.protection_id)
 BEGIN SELECT RAISE(ABORT,'target_set_frozen'); END;
CREATE TRIGGER controller_scope_u BEFORE UPDATE ON controller_scope BEGIN SELECT RAISE(ABORT,'immutable_scope'); END;
CREATE TRIGGER controller_scope_d BEFORE DELETE ON controller_scope BEGIN SELECT RAISE(ABORT,'immutable_scope'); END;
CREATE TRIGGER run_deny_u BEFORE UPDATE ON run_deny_event BEGIN SELECT RAISE(ABORT,'immutable_deny'); END;
CREATE TRIGGER run_deny_d BEFORE DELETE ON run_deny_event BEGIN SELECT RAISE(ABORT,'immutable_deny'); END;
CREATE TRIGGER run_protection_request_u BEFORE UPDATE ON run_protection_request BEGIN SELECT RAISE(ABORT,'immutable_protection'); END;
CREATE TRIGGER run_protection_request_d BEFORE DELETE ON run_protection_request BEGIN SELECT RAISE(ABORT,'immutable_protection'); END;
CREATE TRIGGER run_protection_target_u BEFORE UPDATE ON run_protection_target BEGIN SELECT RAISE(ABORT,'immutable_target'); END;
CREATE TRIGGER run_protection_target_d BEFORE DELETE ON run_protection_target BEGIN SELECT RAISE(ABORT,'immutable_target'); END;
CREATE TRIGGER run_protection_commit_u BEFORE UPDATE ON run_protection_commit BEGIN SELECT RAISE(ABORT,'immutable_commit'); END;
CREATE TRIGGER run_protection_commit_d BEFORE DELETE ON run_protection_commit BEGIN SELECT RAISE(ABORT,'immutable_commit'); END;
CREATE TRIGGER run_protection_audit_u BEFORE UPDATE ON run_protection_audit BEGIN SELECT RAISE(ABORT,'immutable_audit'); END;
CREATE TRIGGER run_protection_audit_d BEFORE DELETE ON run_protection_audit BEGIN SELECT RAISE(ABORT,'immutable_audit'); END;
CREATE TRIGGER run_protection_outbox_u BEFORE UPDATE ON run_protection_outbox BEGIN SELECT RAISE(ABORT,'immutable_outbox'); END;
CREATE TRIGGER run_protection_outbox_d BEFORE DELETE ON run_protection_outbox BEGIN SELECT RAISE(ABORT,'immutable_outbox'); END;
