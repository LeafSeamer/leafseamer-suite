-- 生成物：资源保护通知137表候选，禁止部署；请修改唯一源并重新生成。
-- 生成自common.sql及两个固定子域；请修改源文件并重新生成。
-- controller-storage/0.1.0-draft.1；待审阅，非生产迁移。
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


CREATE TABLE ca_namespace (
  namespace_id TEXT PRIMARY KEY NOT NULL,
  scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
  issuer_id TEXT NOT NULL,
  issuer_epoch TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  request_epoch TEXT NOT NULL,
  owner_evidence_id TEXT NOT NULL,
  owner_evidence_body BLOB NOT NULL CHECK(length(owner_evidence_body)>0),
  UNIQUE(issuer_id,issuer_epoch,principal_id,request_epoch),
  CHECK(length(namespace_id)>0 AND length(issuer_id)>0 AND length(issuer_epoch)>0
    AND length(principal_id)>0 AND length(request_epoch)>0 AND length(owner_evidence_id)>0)
) STRICT;

-- 只关闭新受理；仍保留查原和当前有权主体的永久拒收。
CREATE TABLE ca_namespace_closure (
  namespace_id TEXT PRIMARY KEY NOT NULL REFERENCES ca_namespace(namespace_id),
  protection_operation_id TEXT NOT NULL CHECK(length(protection_operation_id)>0),
  closure_body BLOB NOT NULL CHECK(length(closure_body)>0)
) STRICT;

CREATE TABLE ca_request_key (
  key_id TEXT PRIMARY KEY NOT NULL CHECK(length(key_id)>0),
  namespace_id TEXT NOT NULL REFERENCES ca_namespace(namespace_id),
  operation_id TEXT NOT NULL CHECK(operation_id='createCommand'),
  idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)>0),
  request_digest TEXT NOT NULL CHECK(length(request_digest)=71
    AND substr(request_digest,1,7)='sha256:'
    AND substr(request_digest,8) NOT GLOB '*[^0-9a-f]*'),
  device_id TEXT NOT NULL CHECK(length(device_id)>0),
  content_body BLOB NOT NULL CHECK(json_valid(content_body)),
  request_key_body BLOB NOT NULL CHECK(json_valid(request_key_body)),
  transport_body BLOB CHECK(transport_body IS NULL OR json_valid(transport_body)),
  UNIQUE(namespace_id,operation_id,idempotency_key),
  FOREIGN KEY(key_id) REFERENCES ca_adjudication(key_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE ca_adjudication (
  key_id TEXT PRIMARY KEY NOT NULL REFERENCES ca_request_key(key_id),
  adjudication_id TEXT NOT NULL UNIQUE CHECK(length(adjudication_id)>0),
  revision TEXT NOT NULL CHECK(revision='1'),
  decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected')),
  command_id TEXT,
  commit_id TEXT NOT NULL UNIQUE,
  commit_kind TEXT NOT NULL,
  adjudication_digest TEXT NOT NULL CHECK(length(adjudication_digest)=71
    AND substr(adjudication_digest,1,7)='sha256:'
    AND substr(adjudication_digest,8) NOT GLOB '*[^0-9a-f]*'),
  adjudication_body BLOB NOT NULL CHECK(length(adjudication_body)>0),
  CHECK((decision='accepted' AND command_id IS NOT NULL AND commit_kind='accept')
     OR (decision='rejected' AND command_id IS NULL AND commit_kind='reject_new')),
  UNIQUE(key_id,decision),
  UNIQUE(key_id,commit_id),
  FOREIGN KEY(key_id,command_id) REFERENCES ca_command_initial(key_id,command_id)
    DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(commit_id,key_id,commit_kind) REFERENCES ca_commit(commit_id,key_id,kind)
    DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE ca_command_initial (
  command_id TEXT PRIMARY KEY NOT NULL CHECK(length(command_id)>0),
  key_id TEXT NOT NULL UNIQUE,
  decision TEXT NOT NULL CHECK(decision='accepted'),
  revision TEXT NOT NULL CHECK(revision='1'),
  command_digest TEXT NOT NULL CHECK(length(command_digest)=71
    AND substr(command_digest,1,7)='sha256:'
    AND substr(command_digest,8) NOT GLOB '*[^0-9a-f]*'),
  command_body BLOB NOT NULL CHECK(length(command_body)>0),
  admission_binding_body BLOB NOT NULL CHECK(length(admission_binding_body)>0),
  UNIQUE(key_id,command_id),
  FOREIGN KEY(key_id,decision) REFERENCES ca_adjudication(key_id,decision)
    DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(key_id) REFERENCES ca_reservation(key_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

-- 准入容量事实，不是设备活跃hold，也不充当可重传派发队列。
CREATE TABLE ca_reservation (
  key_id TEXT PRIMARY KEY NOT NULL,
  command_id TEXT NOT NULL UNIQUE,
  capacity_profile_ref_body BLOB NOT NULL CHECK(length(capacity_profile_ref_body)>0),
  dimensions_body BLOB NOT NULL CHECK(length(dimensions_body)>0),
  FOREIGN KEY(key_id,command_id) REFERENCES ca_command_initial(key_id,command_id)
    DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE ca_commit (
  commit_id TEXT PRIMARY KEY NOT NULL CHECK(length(commit_id)>0),
  key_id TEXT NOT NULL REFERENCES ca_request_key(key_id) DEFERRABLE INITIALLY DEFERRED,
  kind TEXT NOT NULL CHECK(kind IN ('accept','reject_new','reject_existing')),
  creation_key_id TEXT,
  rejection_id TEXT,
  commit_body BLOB NOT NULL CHECK(length(commit_body)>0),
  CHECK((kind='accept' AND creation_key_id IS NOT NULL AND creation_key_id=key_id AND rejection_id IS NULL)
     OR (kind='reject_new' AND creation_key_id IS NOT NULL AND creation_key_id=key_id AND rejection_id IS NOT NULL)
     OR (kind='reject_existing' AND creation_key_id IS NULL AND rejection_id IS NOT NULL)),
  UNIQUE(commit_id,key_id,kind),
  UNIQUE(commit_id,key_id,rejection_id),
  FOREIGN KEY(creation_key_id,commit_id) REFERENCES ca_adjudication(key_id,commit_id)
    DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(rejection_id,commit_id,key_id) REFERENCES ca_rejection(rejection_id,commit_id,key_id)
    DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(commit_id,key_id,kind) REFERENCES ca_audit(commit_id,key_id,kind)
    DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(commit_id,key_id,kind) REFERENCES ca_notification(commit_id,key_id,kind)
    DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE ca_rejection (
  rejection_id TEXT PRIMARY KEY NOT NULL CHECK(length(rejection_id)>0),
  actor_issuer_id TEXT NOT NULL CHECK(length(actor_issuer_id)>0),
  actor_issuer_epoch TEXT NOT NULL CHECK(length(actor_issuer_epoch)>0),
  actor_principal_id TEXT NOT NULL CHECK(length(actor_principal_id)>0),
  rejection_operation_id TEXT NOT NULL CHECK(length(rejection_operation_id)>0),
  operation_digest TEXT NOT NULL CHECK(length(operation_digest)=71
    AND substr(operation_digest,1,7)='sha256:'
    AND substr(operation_digest,8) NOT GLOB '*[^0-9a-f]*'),
  key_id TEXT NOT NULL REFERENCES ca_adjudication(key_id) DEFERRABLE INITIALLY DEFERRED,
  commit_id TEXT NOT NULL UNIQUE,
  request_body BLOB NOT NULL CHECK(length(request_body)>0),
  authorization_evidence_body BLOB NOT NULL CHECK(length(authorization_evidence_body)>0),
  UNIQUE(actor_issuer_id,actor_issuer_epoch,actor_principal_id,rejection_operation_id),
  UNIQUE(rejection_id,commit_id,key_id),
  FOREIGN KEY(commit_id,key_id,rejection_id) REFERENCES ca_commit(commit_id,key_id,rejection_id)
    DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE ca_audit (
  commit_id TEXT PRIMARY KEY NOT NULL,
  key_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  redacted_body BLOB NOT NULL CHECK(length(redacted_body)>0),
  UNIQUE(commit_id,key_id,kind),
  FOREIGN KEY(commit_id,key_id,kind) REFERENCES ca_commit(commit_id,key_id,kind)
    DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE ca_notification (
  commit_id TEXT PRIMARY KEY NOT NULL,
  key_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  event_id TEXT NOT NULL UNIQUE CHECK(length(event_id)>0),
  payload_body BLOB NOT NULL CHECK(length(payload_body)>0),
  UNIQUE(commit_id,key_id,kind),
  FOREIGN KEY(commit_id,key_id,kind) REFERENCES ca_commit(commit_id,key_id,kind)
    DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX ca_key_device ON ca_request_key(device_id,key_id);
CREATE INDEX ca_rejection_target ON ca_rejection(key_id,rejection_id);

CREATE TRIGGER ca_closed_namespace BEFORE INSERT ON ca_adjudication
WHEN NEW.decision='accepted' AND EXISTS(
  SELECT 1 FROM ca_request_key k JOIN ca_namespace_closure c USING(namespace_id)
  WHERE k.key_id=NEW.key_id)
BEGIN SELECT RAISE(ABORT,'namespace_closed'); END;
CREATE TRIGGER ca_namespace_no_update BEFORE UPDATE ON ca_namespace
BEGIN SELECT RAISE(ABORT,'immutable_namespace'); END;
CREATE TRIGGER ca_namespace_no_delete BEFORE DELETE ON ca_namespace
BEGIN SELECT RAISE(ABORT,'immutable_namespace'); END;
CREATE TRIGGER ca_closure_no_update BEFORE UPDATE ON ca_namespace_closure
BEGIN SELECT RAISE(ABORT,'permanent_closure'); END;
CREATE TRIGGER ca_closure_no_delete BEFORE DELETE ON ca_namespace_closure
BEGIN SELECT RAISE(ABORT,'permanent_closure'); END;
CREATE TRIGGER ca_key_no_update BEFORE UPDATE ON ca_request_key
BEGIN SELECT RAISE(ABORT,'immutable_request'); END;
CREATE TRIGGER ca_key_no_delete BEFORE DELETE ON ca_request_key
BEGIN SELECT RAISE(ABORT,'immutable_request'); END;
CREATE TRIGGER ca_adjudication_no_update BEFORE UPDATE ON ca_adjudication
BEGIN SELECT RAISE(ABORT,'immutable_adjudication'); END;
CREATE TRIGGER ca_adjudication_no_delete BEFORE DELETE ON ca_adjudication
BEGIN SELECT RAISE(ABORT,'immutable_adjudication'); END;
CREATE TRIGGER ca_initial_no_update BEFORE UPDATE ON ca_command_initial
BEGIN SELECT RAISE(ABORT,'immutable_initial'); END;
CREATE TRIGGER ca_initial_no_delete BEFORE DELETE ON ca_command_initial
BEGIN SELECT RAISE(ABORT,'immutable_initial'); END;
CREATE TRIGGER ca_reservation_no_update BEFORE UPDATE ON ca_reservation
BEGIN SELECT RAISE(ABORT,'immutable_reservation'); END;
CREATE TRIGGER ca_reservation_no_delete BEFORE DELETE ON ca_reservation
BEGIN SELECT RAISE(ABORT,'immutable_reservation'); END;
CREATE TRIGGER ca_commit_no_update BEFORE UPDATE ON ca_commit
BEGIN SELECT RAISE(ABORT,'immutable_commit'); END;
CREATE TRIGGER ca_commit_no_delete BEFORE DELETE ON ca_commit
BEGIN SELECT RAISE(ABORT,'immutable_commit'); END;
CREATE TRIGGER ca_rejection_no_update BEFORE UPDATE ON ca_rejection
BEGIN SELECT RAISE(ABORT,'immutable_rejection'); END;
CREATE TRIGGER ca_rejection_no_delete BEFORE DELETE ON ca_rejection
BEGIN SELECT RAISE(ABORT,'immutable_rejection'); END;
CREATE TRIGGER ca_audit_no_update BEFORE UPDATE ON ca_audit
BEGIN SELECT RAISE(ABORT,'immutable_audit'); END;
CREATE TRIGGER ca_audit_no_delete BEFORE DELETE ON ca_audit
BEGIN SELECT RAISE(ABORT,'immutable_audit'); END;
CREATE TRIGGER ca_notification_no_update BEFORE UPDATE ON ca_notification
BEGIN SELECT RAISE(ABORT,'immutable_notification'); END;
CREATE TRIGGER ca_notification_no_delete BEFORE DELETE ON ca_notification
BEGIN SELECT RAISE(ABORT,'immutable_notification'); END;

CREATE TABLE cp_request (
  prep_key TEXT PRIMARY KEY NOT NULL,
  scope_id INTEGER NOT NULL DEFAULT 1 REFERENCES controller_scope(singleton),
  origin_authority TEXT NOT NULL, origin_database TEXT NOT NULL,
  preparation_id TEXT NOT NULL, run_id TEXT NOT NULL,
  generation TEXT NOT NULL CHECK(length(generation)=20 AND generation NOT GLOB '*[^0-9]*' AND generation>'00000000000000000000'),
  mode TEXT NOT NULL CHECK(mode IN ('arm','recovery')),
  execution_id TEXT,
  request_digest TEXT NOT NULL CHECK(length(request_digest)=71 AND substr(request_digest,1,7)='sha256:' AND substr(request_digest,8) NOT GLOB '*[^0-9a-f]*'),
  request_body BLOB NOT NULL CHECK(length(request_body)>0),
  device_count INTEGER NOT NULL CHECK(device_count BETWEEN 1 AND 256),
  initial_commit TEXT NOT NULL,
  CHECK((mode='arm' AND execution_id IS NULL) OR (mode='recovery' AND execution_id IS NOT NULL)),
  UNIQUE(origin_authority,origin_database,preparation_id),
  UNIQUE(origin_authority,origin_database,run_id,generation),
  UNIQUE(prep_key,request_digest),
  FOREIGN KEY(initial_commit,prep_key) REFERENCES cp_commit(commit_id,prep_key) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_request_device (
  prep_key TEXT NOT NULL REFERENCES cp_request(prep_key),
  device_id TEXT NOT NULL CHECK(length(device_id)>0),
  expected_control_body BLOB NOT NULL CHECK(length(expected_control_body)>0),
  PRIMARY KEY(prep_key,device_id)
) STRICT;
CREATE TABLE cp_event (
  event_id TEXT PRIMARY KEY NOT NULL,
  prep_key TEXT NOT NULL REFERENCES cp_request(prep_key),
  revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*' AND revision>'00000000000000000000'),
  previous_revision TEXT,
  state TEXT NOT NULL CHECK(state IN ('accepted','applied','rejected','indeterminate','closing','closed')),
  receipt_id TEXT, completion_id TEXT, commit_id TEXT NOT NULL UNIQUE,
  UNIQUE(prep_key,revision), UNIQUE(prep_key,event_id), UNIQUE(commit_id,prep_key,event_id),
  CHECK(state NOT IN ('accepted','rejected') OR receipt_id IS NULL),
  CHECK(state!='applied' OR receipt_id IS NOT NULL),
  CHECK((state='closed')=(completion_id IS NOT NULL)),
  FOREIGN KEY(prep_key,previous_revision) REFERENCES cp_event(prep_key,revision),
  FOREIGN KEY(prep_key,receipt_id) REFERENCES cp_receipt(prep_key,receipt_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(prep_key,completion_id) REFERENCES cp_completion(prep_key,completion_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(commit_id,prep_key,event_id) REFERENCES cp_commit(commit_id,prep_key,event_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_grant (
  prep_key TEXT PRIMARY KEY NOT NULL REFERENCES cp_request(prep_key),
  grant_id TEXT NOT NULL UNIQUE, receipt_id TEXT NOT NULL UNIQUE,
  grant_revision TEXT NOT NULL CHECK(length(grant_revision)=20 AND grant_revision NOT GLOB '*[^0-9]*' AND grant_revision>'00000000000000000000'),
  grant_digest TEXT NOT NULL, grant_body BLOB NOT NULL CHECK(length(grant_body)>0),
  UNIQUE(prep_key,grant_id),
  FOREIGN KEY(prep_key,receipt_id) REFERENCES cp_receipt(prep_key,receipt_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_receipt (
  prep_key TEXT PRIMARY KEY NOT NULL, receipt_id TEXT NOT NULL UNIQUE,
  request_digest TEXT NOT NULL, grant_id TEXT NOT NULL,
  receipt_digest TEXT NOT NULL, receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
  event_id TEXT NOT NULL UNIQUE,
  UNIQUE(prep_key,receipt_id),
  FOREIGN KEY(prep_key,request_digest) REFERENCES cp_request(prep_key,request_digest),
  FOREIGN KEY(prep_key,grant_id) REFERENCES cp_grant(prep_key,grant_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(prep_key,event_id) REFERENCES cp_event(prep_key,event_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_close (
  close_id TEXT PRIMARY KEY NOT NULL, prep_key TEXT NOT NULL,
  operation_id TEXT NOT NULL, operation_digest TEXT NOT NULL,
  request_digest TEXT NOT NULL, request_body BLOB NOT NULL CHECK(length(request_body)>0),
  authorization_body BLOB NOT NULL CHECK(length(authorization_body)>0),
  commit_id TEXT NOT NULL UNIQUE,
  UNIQUE(prep_key,operation_id), UNIQUE(prep_key,close_id),
  FOREIGN KEY(prep_key,request_digest) REFERENCES cp_request(prep_key,request_digest),
  FOREIGN KEY(close_id,prep_key) REFERENCES cp_protection(close_id,prep_key) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(commit_id,prep_key,close_id) REFERENCES cp_commit(commit_id,prep_key,close_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_protection (
  close_id TEXT PRIMARY KEY NOT NULL REFERENCES cp_close(close_id) DEFERRABLE INITIALLY DEFERRED,
  prep_key TEXT NOT NULL, target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),
  intent_body BLOB NOT NULL CHECK(length(intent_body)>0),
  UNIQUE(close_id,prep_key),
  FOREIGN KEY(prep_key,close_id) REFERENCES cp_close(prep_key,close_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_protection_target (
  close_id TEXT NOT NULL REFERENCES cp_protection(close_id),
  target_id TEXT NOT NULL, target_body BLOB NOT NULL CHECK(length(target_body)>0),
  PRIMARY KEY(close_id,target_id)
) STRICT;
CREATE TABLE cp_completion (
  completion_id TEXT PRIMARY KEY NOT NULL, prep_key TEXT NOT NULL, close_id TEXT NOT NULL,
  protection_ref_body BLOB NOT NULL CHECK(length(protection_ref_body)>0),
  evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
  event_id TEXT NOT NULL UNIQUE,
  UNIQUE(prep_key,completion_id),
  FOREIGN KEY(close_id,prep_key) REFERENCES cp_protection(close_id,prep_key),
  FOREIGN KEY(prep_key,event_id) REFERENCES cp_event(prep_key,event_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_commit (
  commit_id TEXT PRIMARY KEY NOT NULL, prep_key TEXT NOT NULL REFERENCES cp_request(prep_key),
  kind TEXT NOT NULL CHECK(kind IN ('register','issue','reject','uncertain','close','close_noop','complete')),
  event_id TEXT UNIQUE, close_id TEXT UNIQUE,
  UNIQUE(commit_id,prep_key), UNIQUE(commit_id,prep_key,event_id), UNIQUE(commit_id,prep_key,close_id),
  CHECK((kind='close_noop')=(event_id IS NULL)),
  CHECK((kind IN ('close','close_noop'))=(close_id IS NOT NULL)),
  FOREIGN KEY(prep_key,event_id) REFERENCES cp_event(prep_key,event_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(prep_key,close_id) REFERENCES cp_close(prep_key,close_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(commit_id,prep_key) REFERENCES cp_audit(commit_id,prep_key) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(commit_id,prep_key) REFERENCES cp_notification(commit_id,prep_key) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_audit (
  commit_id TEXT PRIMARY KEY NOT NULL, prep_key TEXT NOT NULL,
  redacted_body BLOB NOT NULL CHECK(length(redacted_body)>0),
  UNIQUE(commit_id,prep_key),
  FOREIGN KEY(commit_id,prep_key) REFERENCES cp_commit(commit_id,prep_key) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cp_notification (
  commit_id TEXT PRIMARY KEY NOT NULL, prep_key TEXT NOT NULL, event_id TEXT NOT NULL UNIQUE,
  payload_body BLOB NOT NULL CHECK(length(payload_body)>0),
  UNIQUE(commit_id,prep_key),
  FOREIGN KEY(commit_id,prep_key) REFERENCES cp_commit(commit_id,prep_key) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE VIEW cp_current AS
 SELECT e.* FROM cp_event e JOIN cp_commit c ON c.commit_id=e.commit_id
 WHERE NOT EXISTS(SELECT 1 FROM cp_event n JOIN cp_commit nc ON nc.commit_id=n.commit_id
                  WHERE n.prep_key=e.prep_key AND n.revision>e.revision);
CREATE VIEW cp_recovery AS SELECT prep_key,state,receipt_id,
 CASE state WHEN 'accepted' THEN 'close_without_issuing' WHEN 'applied' THEN 'history_and_close'
 WHEN 'indeterminate' THEN 'close_and_reconcile' WHEN 'closing' THEN 'resume_same_protection'
 ELSE 'retain_terminal' END AS disposition FROM cp_current;

CREATE TRIGGER cp_event_guard BEFORE INSERT ON cp_event BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cp_commit WHERE commit_id=NEW.commit_id) THEN RAISE(ABORT,'commit_frozen') END;
 SELECT CASE WHEN NEW.previous_revision IS NULL AND
   (NEW.revision!='00000000000000000001' OR NEW.state NOT IN ('accepted','closing') OR NEW.receipt_id IS NOT NULL
    OR EXISTS(SELECT 1 FROM cp_event WHERE prep_key=NEW.prep_key))
   THEN RAISE(ABORT,'invalid_initial') END;
 SELECT CASE WHEN NEW.previous_revision IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM cp_current e WHERE e.prep_key=NEW.prep_key AND e.revision=NEW.previous_revision
    AND NEW.revision=printf('%010d%010d',CAST(substr(e.revision,1,10) AS INTEGER)+(substr(e.revision,11,10)='9999999999'),
                           (CAST(substr(e.revision,11,10) AS INTEGER)+1)%10000000000)
    AND ((e.state='accepted' AND NEW.state IN ('applied','rejected','indeterminate','closing'))
      OR (e.state IN ('applied','indeterminate') AND NEW.state='closing')
      OR (e.state='closing' AND NEW.state='closed'))
    AND (NEW.receipt_id IS e.receipt_id OR (e.state='accepted' AND NEW.state='applied'))
 ) THEN RAISE(ABORT,'invalid_transition') END;
 SELECT CASE WHEN NEW.state IN ('accepted','applied') AND EXISTS(
   SELECT 1 FROM cp_request r JOIN run_deny_current d
    ON (r.origin_authority,r.origin_database,r.run_id)=(d.origin_authority,d.origin_database,d.run_id)
   WHERE r.prep_key=NEW.prep_key AND r.generation<=d.generation
 ) THEN RAISE(ABORT,'run_denied') END;
END;
CREATE TRIGGER cp_commit_guard BEFORE INSERT ON cp_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cp_request r WHERE r.prep_key=NEW.prep_key
    AND r.device_count=(SELECT count(*) FROM cp_request_device d WHERE d.prep_key=r.prep_key))
   THEN RAISE(ABORT,'device_set_incomplete') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cp_commit WHERE prep_key=NEW.prep_key) AND
   (NEW.kind NOT IN ('register','close') OR NOT EXISTS(
    SELECT 1 FROM cp_request r JOIN cp_event e ON e.prep_key=r.prep_key
    WHERE r.prep_key=NEW.prep_key AND r.initial_commit=NEW.commit_id
      AND e.event_id=NEW.event_id AND e.previous_revision IS NULL))
   THEN RAISE(ABORT,'initial_commit') END;
 SELECT CASE WHEN NEW.event_id IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM cp_event e WHERE e.event_id=NEW.event_id AND e.prep_key=NEW.prep_key AND e.commit_id=NEW.commit_id
    AND e.state=CASE NEW.kind WHEN 'register' THEN 'accepted' WHEN 'issue' THEN 'applied'
      WHEN 'reject' THEN 'rejected' WHEN 'uncertain' THEN 'indeterminate' WHEN 'close' THEN 'closing' WHEN 'complete' THEN 'closed' END)
   THEN RAISE(ABORT,'event_binding') END;
 SELECT CASE WHEN NEW.kind='issue' AND NOT EXISTS(
   SELECT 1 FROM cp_event e JOIN cp_receipt r ON r.prep_key=e.prep_key AND r.receipt_id=e.receipt_id
   JOIN cp_grant g ON g.prep_key=r.prep_key AND g.grant_id=r.grant_id AND g.receipt_id=r.receipt_id
   WHERE e.event_id=NEW.event_id AND r.event_id=e.event_id)
   THEN RAISE(ABORT,'issuance_incomplete') END;
 SELECT CASE WHEN NEW.kind='complete' AND NOT EXISTS(
   SELECT 1 FROM cp_event e JOIN cp_completion p ON p.prep_key=e.prep_key AND p.completion_id=e.completion_id
   WHERE e.event_id=NEW.event_id AND p.event_id=e.event_id)
   THEN RAISE(ABORT,'completion_incomplete') END;
 SELECT CASE WHEN NEW.kind='close_noop' AND NOT EXISTS(
   SELECT 1 FROM cp_current WHERE prep_key=NEW.prep_key AND state IN ('closing','closed','rejected'))
   THEN RAISE(ABORT,'close_requires_transition') END;
 SELECT CASE WHEN NEW.kind IN ('close','close_noop') AND NOT EXISTS(
   SELECT 1 FROM cp_close c JOIN cp_protection p ON p.close_id=c.close_id AND p.prep_key=c.prep_key
    JOIN cp_request r ON r.prep_key=c.prep_key
   WHERE c.close_id=NEW.close_id AND c.commit_id=NEW.commit_id AND c.prep_key=NEW.prep_key
    AND p.target_count=(SELECT count(*) FROM cp_protection_target t WHERE t.close_id=c.close_id)
    AND EXISTS(SELECT 1 FROM run_deny_event d
      WHERE (d.origin_authority,d.origin_database,d.run_id)=(r.origin_authority,r.origin_database,r.run_id)
        AND d.generation>=r.generation AND (d.commit_id=NEW.commit_id OR EXISTS(SELECT 1 FROM run_deny_committed dc WHERE dc.snapshot_revision=d.snapshot_revision))))
   THEN RAISE(ABORT,'protection_incomplete') END;
END;
CREATE TRIGGER cp_device_frozen BEFORE INSERT ON cp_request_device
 WHEN EXISTS(SELECT 1 FROM cp_request r JOIN cp_commit c ON c.commit_id=r.initial_commit WHERE r.prep_key=NEW.prep_key)
 BEGIN SELECT RAISE(ABORT,'device_set_frozen'); END;
CREATE TRIGGER cp_target_frozen BEFORE INSERT ON cp_protection_target
 WHEN EXISTS(SELECT 1 FROM cp_close x JOIN cp_commit c ON c.commit_id=x.commit_id WHERE x.close_id=NEW.close_id)
 BEGIN SELECT RAISE(ABORT,'target_set_frozen'); END;
CREATE TRIGGER cp_receipt_guard BEFORE INSERT ON cp_receipt
 WHEN NOT EXISTS(SELECT 1 FROM cp_event e WHERE e.event_id=NEW.event_id AND e.prep_key=NEW.prep_key
   AND e.state='applied' AND e.receipt_id=NEW.receipt_id AND NOT EXISTS(SELECT 1 FROM cp_commit c WHERE c.commit_id=e.commit_id))
 BEGIN SELECT RAISE(ABORT,'receipt_binding'); END;
CREATE TRIGGER cp_completion_guard BEFORE INSERT ON cp_completion
 WHEN NOT EXISTS(SELECT 1 FROM cp_event e WHERE e.event_id=NEW.event_id AND e.prep_key=NEW.prep_key
   AND e.state='closed' AND e.completion_id=NEW.completion_id AND NOT EXISTS(SELECT 1 FROM cp_commit c WHERE c.commit_id=e.commit_id))
 BEGIN SELECT RAISE(ABORT,'completion_binding'); END;
CREATE TRIGGER cp_request_u BEFORE UPDATE ON cp_request BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_request_d BEFORE DELETE ON cp_request BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_request_device_u BEFORE UPDATE ON cp_request_device BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_request_device_d BEFORE DELETE ON cp_request_device BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_event_u BEFORE UPDATE ON cp_event BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_event_d BEFORE DELETE ON cp_event BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_grant_u BEFORE UPDATE ON cp_grant BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_grant_d BEFORE DELETE ON cp_grant BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_receipt_u BEFORE UPDATE ON cp_receipt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_receipt_d BEFORE DELETE ON cp_receipt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_close_u BEFORE UPDATE ON cp_close BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_close_d BEFORE DELETE ON cp_close BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_protection_u BEFORE UPDATE ON cp_protection BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_protection_d BEFORE DELETE ON cp_protection BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_protection_target_u BEFORE UPDATE ON cp_protection_target BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_protection_target_d BEFORE DELETE ON cp_protection_target BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_completion_u BEFORE UPDATE ON cp_completion BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_completion_d BEFORE DELETE ON cp_completion BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_commit_u BEFORE UPDATE ON cp_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_commit_d BEFORE DELETE ON cp_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_audit_u BEFORE UPDATE ON cp_audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_audit_d BEFORE DELETE ON cp_audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_notification_u BEFORE UPDATE ON cp_notification BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_notification_d BEFORE DELETE ON cp_notification BEGIN SELECT RAISE(ABORT,'immutable'); END;

-- 在controller.sql之后加载。执行登记与运行保护附属候选，非产品迁移。
CREATE TABLE ce_command (
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ca_command_initial(command_id),
 device_id TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('manual','automation')),
 prep_key TEXT, receipt_id TEXT,
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 CHECK((origin='manual' AND prep_key IS NULL AND receipt_id IS NULL)
    OR (origin='automation' AND prep_key IS NOT NULL AND receipt_id IS NOT NULL)),
 FOREIGN KEY(prep_key,receipt_id) REFERENCES cp_receipt(prep_key,receipt_id),
 FOREIGN KEY(prep_key,device_id) REFERENCES cp_request_device(prep_key,device_id)
) STRICT;
CREATE TABLE ce_exit (
 exit_id TEXT PRIMARY KEY NOT NULL,
 device_id TEXT NOT NULL,
 controller_boot_id TEXT NOT NULL, worker_boot_id TEXT NOT NULL,
 ipc_session_id TEXT NOT NULL, device_session_id TEXT NOT NULL,
 clock_domain_id TEXT NOT NULL, descriptor_digest TEXT NOT NULL,
 runtime_binding_body BLOB NOT NULL CHECK(length(runtime_binding_body)>0),
 UNIQUE(controller_boot_id,worker_boot_id,ipc_session_id,device_session_id,device_id),
 CHECK(length(exit_id)>0 AND length(device_id)>0 AND length(controller_boot_id)>0
  AND length(worker_boot_id)>0 AND length(ipc_session_id)>0 AND length(device_session_id)>0
  AND length(clock_domain_id)>0 AND length(descriptor_digest)>0)
) STRICT;
CREATE TABLE ce_attempt (
 attempt_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL REFERENCES ce_command(command_id),
 authorization_body BLOB NOT NULL CHECK(length(authorization_body)>0),
 attempt_body BLOB NOT NULL CHECK(length(attempt_body)>0)
) STRICT;
CREATE TABLE ce_packet (
 packet_id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES ce_attempt(attempt_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 primitive_id TEXT NOT NULL CHECK(length(primitive_id)>0),
 packet_body BLOB NOT NULL CHECK(length(packet_body)>0),
 UNIQUE(attempt_id,primitive_id), UNIQUE(packet_id,attempt_id,exit_id)
) STRICT;
CREATE TABLE ce_permit (
 permit_id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES ce_attempt(attempt_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 issued_revision TEXT NOT NULL UNIQUE CHECK(length(issued_revision)=20
  AND issued_revision NOT GLOB '*[^0-9]*' AND issued_revision>'00000000000000000000'),
 packet_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 0 AND 2147483647),
 kind TEXT NOT NULL CHECK(kind IN ('initial','protocol_resend')),
 parent_permit_id TEXT,
 permit_body BLOB NOT NULL CHECK(length(permit_body)>0),
 issue_kind TEXT NOT NULL DEFAULT 'ordinary' CHECK(issue_kind='ordinary'),
 FOREIGN KEY(permit_id,issued_revision,issue_kind) REFERENCES ci_issue(permit_id,issued_revision,kind) DEFERRABLE INITIALLY DEFERRED,
 CHECK((ordinal=0 AND kind='initial' AND parent_permit_id IS NULL)
    OR (ordinal>0 AND kind='protocol_resend' AND parent_permit_id IS NOT NULL)),
 UNIQUE(packet_id,ordinal), UNIQUE(permit_id,packet_id), UNIQUE(permit_id,exit_id),
 FOREIGN KEY(packet_id,attempt_id,exit_id) REFERENCES ce_packet(packet_id,attempt_id,exit_id),
 FOREIGN KEY(parent_permit_id,packet_id) REFERENCES ce_permit(permit_id,packet_id),
 FOREIGN KEY(permit_id) REFERENCES ce_transmission_commit(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ce_transmission_commit (
 permit_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_permit(permit_id),
 guard_body BLOB NOT NULL CHECK(length(guard_body)>0),
 budget_charge_body BLOB NOT NULL CHECK(length(budget_charge_body)>0),
 dispatch_intent_body BLOB NOT NULL CHECK(length(dispatch_intent_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ce_report (
 report_id TEXT PRIMARY KEY NOT NULL,
 permit_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK(
  (disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR
  (disposition='unknown' AND proof='send_uncertain')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 UNIQUE(report_id,permit_id),
 FOREIGN KEY(permit_id,exit_id) REFERENCES ce_permit(permit_id,exit_id)
) STRICT;
CREATE TABLE ce_settlement (
 settlement_id TEXT PRIMARY KEY NOT NULL,
 permit_id TEXT NOT NULL REFERENCES ce_permit(permit_id),
 kind TEXT NOT NULL CHECK(kind IN ('never_sent','effect_resolved')),
 report_id TEXT,
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 CHECK((kind='never_sent' AND report_id IS NOT NULL)
    OR (kind='effect_resolved' AND report_id IS NULL)),
 FOREIGN KEY(report_id,permit_id) REFERENCES ce_report(report_id,permit_id)
) STRICT;
CREATE TABLE ce_retirement (
 exit_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_exit(exit_id),
 supervisor_evidence_body BLOB NOT NULL CHECK(length(supervisor_evidence_body)>0)
) STRICT;

CREATE VIEW ce_run_command AS
 SELECT c.*,p.origin_authority,p.origin_database,p.run_id,p.generation
 FROM ce_command c JOIN cp_request p USING(prep_key);
-- 可靠未发核销被迟到的transport证据推翻时，重新列为未决；不覆写旧核销记录。
CREATE VIEW ce_open_permit AS
 SELECT p.*,a.command_id,c.device_id,c.origin_authority,c.origin_database,c.run_id,c.generation
 FROM ce_permit p JOIN ce_attempt a USING(attempt_id)
 JOIN ce_run_command c USING(command_id)
 WHERE NOT EXISTS(SELECT 1 FROM ce_settlement s WHERE s.permit_id=p.permit_id
  AND (s.kind='effect_resolved' OR NOT EXISTS(
    SELECT 1 FROM ce_current_disposition r WHERE r.permit_id=p.permit_id AND r.disposition='in_flight')));

CREATE TABLE ce_fence (
 prepare_cut_id TEXT NOT NULL UNIQUE REFERENCES pd_cut(cut_id) DEFERRABLE INITIALLY DEFERRED,
 fence_id TEXT PRIMARY KEY NOT NULL,
 protection_id TEXT UNIQUE REFERENCES run_protection_request(protection_id),
 close_id TEXT UNIQUE REFERENCES cp_close(close_id),
 issued_cut_revision TEXT NOT NULL CHECK(length(issued_cut_revision)=20
  AND issued_cut_revision NOT GLOB '*[^0-9]*'),
 cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 CHECK((protection_id IS NOT NULL AND close_id IS NULL)
    OR (protection_id IS NULL AND close_id IS NOT NULL)),
 FOREIGN KEY(fence_id) REFERENCES ce_cut_commit(fence_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ce_target (
 fence_id TEXT NOT NULL REFERENCES ce_fence(fence_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 ledger_digest TEXT NOT NULL, target_body BLOB NOT NULL CHECK(length(target_body)>0),
 PRIMARY KEY(fence_id,exit_id)
) STRICT;
CREATE TABLE ce_item (
 fence_id TEXT NOT NULL, permit_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 entered_known INTEGER NOT NULL CHECK(entered_known IN (0,1)),
 PRIMARY KEY(fence_id,permit_id),
 UNIQUE(fence_id,permit_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target(fence_id,exit_id),
 FOREIGN KEY(permit_id,exit_id) REFERENCES ce_permit(permit_id,exit_id)
) STRICT;
CREATE TABLE ce_queued (
 fence_id TEXT NOT NULL REFERENCES ce_fence(fence_id),
 command_id TEXT NOT NULL UNIQUE REFERENCES ce_command(command_id),
 reason TEXT NOT NULL CHECK(reason='run_generation_denied'),
 PRIMARY KEY(fence_id,command_id)
) STRICT;
CREATE TABLE ce_cut_commit (
 fence_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_fence(fence_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_event_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE ce_target_result (
 fence_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('worker_ack','supervisor_retired')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(fence_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target(fence_id,exit_id)
) STRICT;
CREATE TABLE ce_coverage (
 fence_id TEXT NOT NULL, permit_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK(
  (disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR
  (disposition='unknown' AND proof='send_uncertain')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 PRIMARY KEY(fence_id,permit_id),
 FOREIGN KEY(fence_id,permit_id,exit_id) REFERENCES ce_item(fence_id,permit_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target_result(fence_id,exit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ce_application (
 prepare_closure_id TEXT NOT NULL REFERENCES pd_closure_commit(closure_id),
 fence_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_cut_commit(fence_id),
 receipt_id TEXT NOT NULL UNIQUE,
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_event_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;

CREATE VIEW ce_selector AS
 SELECT f.fence_id,r.origin_authority,r.origin_database,r.run_id,r.generation
 FROM ce_fence f JOIN run_protection_request r USING(protection_id)
 UNION ALL
 SELECT f.fence_id,r.origin_authority,r.origin_database,r.run_id,r.generation
 FROM ce_fence f JOIN cp_close c USING(close_id) JOIN cp_request r USING(prep_key);
CREATE VIEW ce_expected_item AS
 SELECT s.fence_id,p.permit_id,p.exit_id FROM ce_selector s JOIN ce_open_permit p
 ON (p.origin_authority,p.origin_database,p.run_id)=(s.origin_authority,s.origin_database,s.run_id)
 AND p.generation<=s.generation;
CREATE VIEW ce_expected_target AS
 SELECT DISTINCT s.fence_id,e.exit_id FROM ce_selector s
 JOIN cp_request p ON (p.origin_authority,p.origin_database,p.run_id)=
  (s.origin_authority,s.origin_database,s.run_id) AND p.generation<=s.generation
 JOIN cp_request_device d USING(prep_key) JOIN ce_exit e ON e.device_id=d.device_id
 WHERE NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id)
 UNION
 SELECT fence_id,exit_id FROM ce_expected_item;
CREATE VIEW ce_expected_queued AS
 SELECT s.fence_id,c.command_id FROM ce_selector s JOIN ce_run_command c
 ON (c.origin_authority,c.origin_database,c.run_id)=(s.origin_authority,s.origin_database,s.run_id)
 AND c.generation<=s.generation
 WHERE NOT EXISTS(SELECT 1 FROM ce_attempt a WHERE a.command_id=c.command_id)
 AND NOT EXISTS(SELECT 1 FROM ce_queued q JOIN ce_cut_commit k USING(fence_id)
                WHERE q.command_id=c.command_id);
CREATE VIEW ce_source_target AS
 SELECT f.fence_id,t.target_id FROM ce_fence f JOIN run_protection_target t USING(protection_id)
 UNION ALL
 SELECT f.fence_id,t.target_id FROM ce_fence f JOIN cp_protection_target t USING(close_id);
CREATE VIEW ce_pending_cut AS
 SELECT f.fence_id FROM ce_fence f JOIN ce_cut_commit k USING(fence_id)
 WHERE NOT EXISTS(SELECT 1 FROM run_protection_commit c WHERE c.protection_id=f.protection_id)
 AND NOT EXISTS(SELECT 1 FROM cp_close c JOIN cp_commit k ON k.commit_id=c.commit_id WHERE c.close_id=f.close_id);
CREATE VIEW ce_current_disposition AS
 SELECT p.permit_id,
 CASE WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='in_flight')
   OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
             WHERE c.permit_id=p.permit_id AND c.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM cu_coverage z JOIN cu_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
   OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
             WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cu_coverage z JOIN cu_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent' AND NOT EXISTS(SELECT 1 FROM cu_revocation r WHERE r.kind='ack' AND r.object_id=k.barrier_id)) THEN 'not_sent'
 ELSE 'unknown' END AS disposition
 FROM ce_permit p;

CREATE TRIGGER ce_command_guard BEFORE INSERT ON ce_command BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial c JOIN ca_request_key k USING(key_id)
  WHERE c.command_id=NEW.command_id AND k.device_id=NEW.device_id)
  THEN RAISE(ABORT,'command_device_binding') END;
 SELECT CASE WHEN NEW.origin='automation' AND NOT EXISTS(
  SELECT 1 FROM cp_current p WHERE p.prep_key=NEW.prep_key AND p.state='applied'
   AND p.receipt_id=NEW.receipt_id) THEN RAISE(ABORT,'preparation_not_applied') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cp_request p JOIN run_deny_event d
  ON (d.origin_authority,d.origin_database,d.run_id)=(p.origin_authority,p.origin_database,p.run_id)
  AND d.generation>=p.generation WHERE p.prep_key=NEW.prep_key) THEN RAISE(ABORT,'run_denied') END;
END;
CREATE TRIGGER ce_accept_projection BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial c JOIN ce_command e USING(command_id)
  WHERE c.key_id=NEW.key_id) THEN RAISE(ABORT,'execution_projection_required') END;
END;
CREATE TRIGGER ce_attempt_guard BEFORE INSERT ON ce_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_queued WHERE command_id=NEW.command_id)
  OR EXISTS(SELECT 1 FROM ce_run_command c JOIN run_deny_event d
   ON (d.origin_authority,d.origin_database,d.run_id)=(c.origin_authority,c.origin_database,c.run_id)
   AND d.generation>=c.generation WHERE c.command_id=NEW.command_id)
  THEN RAISE(ABORT,'run_denied') END;
END;
CREATE TRIGGER ce_permit_guard BEFORE INSERT ON ce_permit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_command c USING(command_id)
  JOIN ce_exit e ON e.device_id=c.device_id WHERE a.attempt_id=NEW.attempt_id AND e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'permit_exit_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'exit_retired') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_run_command c USING(command_id)
  JOIN run_deny_event d ON (d.origin_authority,d.origin_database,d.run_id)=
  (c.origin_authority,c.origin_database,c.run_id) AND d.generation>=c.generation
  WHERE a.attempt_id=NEW.attempt_id) THEN RAISE(ABORT,'run_denied') END;
 SELECT CASE WHEN NEW.ordinal!=(SELECT coalesce(max(ordinal),-1)+1 FROM ce_permit WHERE packet_id=NEW.packet_id)
  THEN RAISE(ABORT,'ordinal_successor') END;
 SELECT CASE WHEN NEW.ordinal>0 AND NOT EXISTS(SELECT 1 FROM ce_permit
  WHERE permit_id=NEW.parent_permit_id AND ordinal=0 AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'resend_parent') END;
END;
CREATE TRIGGER ce_settlement_guard BEFORE INSERT ON ce_settlement WHEN NEW.kind='never_sent' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_report WHERE report_id=NEW.report_id
  AND permit_id=NEW.permit_id AND disposition='not_sent')
  OR EXISTS(SELECT 1 FROM ce_current_disposition WHERE permit_id=NEW.permit_id AND disposition='in_flight')
  THEN RAISE(ABORT,'not_sent_unproven') END;
END;
CREATE TRIGGER ce_cut_guard BEFORE INSERT ON ce_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_fence f WHERE f.fence_id=NEW.fence_id AND
  (EXISTS(SELECT 1 FROM run_protection_commit WHERE protection_id=f.protection_id)
   OR EXISTS(SELECT 1 FROM cp_close c JOIN cp_commit k ON k.commit_id=c.commit_id WHERE c.close_id=f.close_id)))
  THEN RAISE(ABORT,'cut_must_share_source_transaction') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_fence WHERE fence_id=NEW.fence_id
  AND issued_cut_revision=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue))
  THEN RAISE(ABORT,'cut_revision') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM ce_expected_target WHERE fence_id=NEW.fence_id
  EXCEPT SELECT exit_id FROM ce_target WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT exit_id FROM ce_target WHERE fence_id=NEW.fence_id
  EXCEPT SELECT exit_id FROM ce_expected_target WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'target_set_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT permit_id,exit_id FROM ce_expected_item WHERE fence_id=NEW.fence_id
  EXCEPT SELECT permit_id,exit_id FROM ce_item WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT permit_id,exit_id FROM ce_item WHERE fence_id=NEW.fence_id
  EXCEPT SELECT permit_id,exit_id FROM ce_expected_item WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'intent_set_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT command_id FROM ce_expected_queued WHERE fence_id=NEW.fence_id
  EXCEPT SELECT command_id FROM ce_queued WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT command_id FROM ce_queued WHERE fence_id=NEW.fence_id
  EXCEPT SELECT command_id FROM ce_expected_queued WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'queued_set_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_item i WHERE i.fence_id=NEW.fence_id AND
  i.entered_known!=EXISTS(SELECT 1 FROM ce_current_disposition d WHERE d.permit_id=i.permit_id
                        AND d.disposition='in_flight'))
  THEN RAISE(ABORT,'entered_snapshot') END;
 SELECT CASE WHEN (SELECT count(*) FROM ce_target WHERE fence_id=NEW.fence_id)>256
  OR EXISTS(SELECT exit_id FROM ce_item WHERE fence_id=NEW.fence_id GROUP BY exit_id HAVING count(*)>256)
  THEN RAISE(ABORT,'fence_capacity') END;
 -- 旧P2容器必须逐出口一致；HTTP ControllerTarget摘要不是此出口集合。
 SELECT CASE WHEN EXISTS(
  SELECT t.exit_id FROM ce_target t WHERE t.fence_id=NEW.fence_id
  EXCEPT SELECT target_id FROM ce_source_target WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT target_id FROM ce_source_target WHERE fence_id=NEW.fence_id
  EXCEPT SELECT exit_id FROM ce_target WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'source_targets') END;
END;
CREATE TRIGGER ce_protection_cut BEFORE INSERT ON run_protection_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_fence f JOIN ce_cut_commit c USING(fence_id)
  WHERE f.protection_id=NEW.protection_id) THEN RAISE(ABORT,'cut_required') END;
END;
CREATE TRIGGER ce_close_cut BEFORE INSERT ON cp_commit WHEN NEW.close_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_fence f JOIN ce_cut_commit c USING(fence_id)
  WHERE f.close_id=NEW.close_id) THEN RAISE(ABORT,'cut_required') END;
END;
CREATE TRIGGER ce_application_guard BEFORE INSERT ON ce_application BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_pending_cut WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'cut_uncommitted') END;
 SELECT CASE WHEN (SELECT count(*) FROM ce_target_result WHERE fence_id=NEW.fence_id)!=
                  (SELECT count(*) FROM ce_target WHERE fence_id=NEW.fence_id)
  OR (SELECT count(*) FROM ce_coverage WHERE fence_id=NEW.fence_id)!=
     (SELECT count(*) FROM ce_item WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'coverage_incomplete') END;
END;
CREATE TRIGGER ce_result_guard BEFORE INSERT ON ce_target_result BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id)
  OR EXISTS(SELECT 1 FROM ce_pending_cut WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'cut_uncommitted') END;
 SELECT CASE WHEN (SELECT count(*) FROM ce_coverage WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)!=
                  (SELECT count(*) FROM ce_item WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'coverage_incomplete') END;
 SELECT CASE WHEN NEW.evidence_kind='supervisor_retired'
  AND NOT EXISTS(SELECT 1 FROM ce_retirement e WHERE e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'retirement_unproven') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_item i USING(fence_id,permit_id,exit_id)
  WHERE c.fence_id=NEW.fence_id AND c.exit_id=NEW.exit_id AND
  ((i.entered_known=1 AND c.disposition!='in_flight')
   OR (NEW.evidence_kind='supervisor_retired' AND c.disposition='not_sent')))
  THEN RAISE(ABORT,'coverage_downgrade') END;
END;
CREATE TRIGGER ce_target_frozen BEFORE INSERT ON ce_target WHEN EXISTS(
 SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id) BEGIN SELECT RAISE(ABORT,'cut_frozen'); END;
CREATE TRIGGER ce_item_frozen BEFORE INSERT ON ce_item WHEN EXISTS(
 SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id) BEGIN SELECT RAISE(ABORT,'cut_frozen'); END;
CREATE TRIGGER ce_queued_frozen BEFORE INSERT ON ce_queued WHEN EXISTS(
 SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id) BEGIN SELECT RAISE(ABORT,'cut_frozen'); END;
CREATE TRIGGER ce_result_frozen BEFORE INSERT ON ce_target_result WHEN EXISTS(
 SELECT 1 FROM ce_application WHERE fence_id=NEW.fence_id) BEGIN SELECT RAISE(ABORT,'application_frozen'); END;
CREATE TRIGGER ce_coverage_frozen BEFORE INSERT ON ce_coverage WHEN EXISTS(
 SELECT 1 FROM ce_target_result WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
 BEGIN SELECT RAISE(ABORT,'coverage_frozen'); END;

-- seal后至来源commit之间禁止改动登记事实；保护与切点仍必须同一事务提交。
CREATE TRIGGER ce_command_cut BEFORE INSERT ON ce_command WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_exit_cut BEFORE INSERT ON ce_exit WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_attempt_cut BEFORE INSERT ON ce_attempt WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_permit_cut BEFORE INSERT ON ce_permit WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_packet_cut BEFORE INSERT ON ce_packet WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_report_cut BEFORE INSERT ON ce_report WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_settlement_cut BEFORE INSERT ON ce_settlement WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_retirement_cut BEFORE INSERT ON ce_retirement WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_preparation_cut BEFORE INSERT ON cp_request WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;
CREATE TRIGGER ce_preparation_device_cut BEFORE INSERT ON cp_request_device WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
 BEGIN SELECT RAISE(ABORT,'pending_cut'); END;

CREATE TRIGGER ce_command_u BEFORE UPDATE ON ce_command BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_command_d BEFORE DELETE ON ce_command BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_exit_u BEFORE UPDATE ON ce_exit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_exit_d BEFORE DELETE ON ce_exit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_attempt_u BEFORE UPDATE ON ce_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_attempt_d BEFORE DELETE ON ce_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_packet_u BEFORE UPDATE ON ce_packet BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_packet_d BEFORE DELETE ON ce_packet BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_transmission_u BEFORE UPDATE ON ce_transmission_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_transmission_d BEFORE DELETE ON ce_transmission_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_permit_u BEFORE UPDATE ON ce_permit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_permit_d BEFORE DELETE ON ce_permit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_report_u BEFORE UPDATE ON ce_report BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_report_d BEFORE DELETE ON ce_report BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_settlement_u BEFORE UPDATE ON ce_settlement BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_settlement_d BEFORE DELETE ON ce_settlement BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_retirement_u BEFORE UPDATE ON ce_retirement BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_retirement_d BEFORE DELETE ON ce_retirement BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_fence_u BEFORE UPDATE ON ce_fence BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_fence_d BEFORE DELETE ON ce_fence BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_target_u BEFORE UPDATE ON ce_target BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_target_d BEFORE DELETE ON ce_target BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_item_u BEFORE UPDATE ON ce_item BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_item_d BEFORE DELETE ON ce_item BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_queued_u BEFORE UPDATE ON ce_queued BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_queued_d BEFORE DELETE ON ce_queued BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_cut_u BEFORE UPDATE ON ce_cut_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_cut_d BEFORE DELETE ON ce_cut_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_result_u BEFORE UPDATE ON ce_target_result BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_result_d BEFORE DELETE ON ce_target_result BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_coverage_u BEFORE UPDATE ON ce_coverage BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_coverage_d BEFORE DELETE ON ce_coverage BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_application_u BEFORE UPDATE ON ce_application BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_application_d BEFORE DELETE ON ce_application BEGIN SELECT RAISE(ABORT,'immutable'); END;

-- 在controller.sql、fence.sql之后加载；只为运行来源保护补尝试历史，不是产品迁移。
CREATE TABLE ce_barrier_attempt (
 barrier_id TEXT PRIMARY KEY NOT NULL,
 fence_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 ordinal TEXT NOT NULL CHECK(length(ordinal)=20 AND ordinal NOT GLOB '*[^0-9]*'
  AND ordinal>'00000000000000000000'),
 previous_barrier_id TEXT,
 request_digest TEXT NOT NULL,
 request_body BLOB NOT NULL CHECK(length(request_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_event_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 UNIQUE(fence_id,exit_id,ordinal), UNIQUE(barrier_id,fence_id,exit_id),
 CHECK((ordinal='00000000000000000001' AND previous_barrier_id IS NULL)
    OR (ordinal>'00000000000000000001' AND previous_barrier_id IS NOT NULL)),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target(fence_id,exit_id),
 FOREIGN KEY(previous_barrier_id,fence_id,exit_id)
  REFERENCES ce_barrier_attempt(barrier_id,fence_id,exit_id)
) STRICT;
CREATE TABLE ce_barrier_failure (
 barrier_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_barrier_attempt(barrier_id),
 reason TEXT NOT NULL CHECK(reason IN ('cache_miss','deadline_elapsed','channel_lost')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ce_barrier_coverage (
 barrier_id TEXT NOT NULL, fence_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK(
  (disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR
  (disposition='unknown' AND proof='send_uncertain')),
 PRIMARY KEY(barrier_id,permit_id),
 FOREIGN KEY(barrier_id,fence_id,exit_id) REFERENCES ce_barrier_attempt(barrier_id,fence_id,exit_id),
 FOREIGN KEY(fence_id,permit_id,exit_id) REFERENCES ce_item(fence_id,permit_id,exit_id),
 FOREIGN KEY(barrier_id) REFERENCES ce_barrier_ack(barrier_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ce_barrier_ack (
 barrier_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_barrier_attempt(barrier_id),
 effective_tick TEXT NOT NULL CHECK(length(effective_tick)=20 AND effective_tick NOT GLOB '*[^0-9]*'),
 ack_digest TEXT NOT NULL,
 ack_body BLOB NOT NULL CHECK(length(ack_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ce_result_binding (
 fence_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 barrier_id TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('worker_ack','supervisor_retired')),
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 PRIMARY KEY(fence_id,exit_id),
 CHECK((kind='worker_ack' AND barrier_id IS NOT NULL)
    OR (kind='supervisor_retired' AND barrier_id IS NULL)),
 FOREIGN KEY(barrier_id,fence_id,exit_id) REFERENCES ce_barrier_attempt(barrier_id,fence_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target_result(fence_id,exit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TRIGGER ce_barrier_attempt_guard BEFORE INSERT ON ce_barrier_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id)
  OR EXISTS(SELECT 1 FROM ce_pending_cut WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'cut_uncommitted') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_target_result WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'target_already_applied') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'exit_retired') END;
 SELECT CASE WHEN NEW.ordinal!=(SELECT printf('%010d%010d',
  CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
  (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
  FROM (SELECT coalesce(max(ordinal),'00000000000000000000') v FROM ce_barrier_attempt
        WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id))
  THEN RAISE(ABORT,'barrier_ordinal') END;
 SELECT CASE WHEN NEW.previous_barrier_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM ce_barrier_attempt a JOIN ce_barrier_failure f USING(barrier_id)
  WHERE a.barrier_id=NEW.previous_barrier_id AND a.fence_id=NEW.fence_id AND a.exit_id=NEW.exit_id
   AND a.ordinal=(SELECT max(ordinal) FROM ce_barrier_attempt WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
   AND f.reason IN ('cache_miss','deadline_elapsed'))
  THEN RAISE(ABORT,'retry_basis') END;
END;
CREATE TRIGGER ce_barrier_failure_guard BEFORE INSERT ON ce_barrier_failure BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_barrier_ack WHERE barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'ack_already_stored') END;
END;
CREATE TRIGGER ce_barrier_ack_guard BEFORE INSERT ON ce_barrier_ack BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM ce_barrier_coverage WHERE barrier_id=NEW.barrier_id)!=
  (SELECT count(*) FROM ce_item i JOIN ce_barrier_attempt a USING(fence_id,exit_id) WHERE a.barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'barrier_coverage_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_barrier_coverage c JOIN ce_item i USING(fence_id,exit_id,permit_id)
  WHERE c.barrier_id=NEW.barrier_id AND i.entered_known=1 AND c.disposition!='in_flight')
  THEN RAISE(ABORT,'barrier_coverage_downgrade') END;
END;
CREATE TRIGGER ce_barrier_coverage_frozen BEFORE INSERT ON ce_barrier_coverage
 WHEN EXISTS(SELECT 1 FROM ce_barrier_ack WHERE barrier_id=NEW.barrier_id)
 BEGIN SELECT RAISE(ABORT,'barrier_ack_frozen'); END;
CREATE TRIGGER ce_result_binding_guard BEFORE INSERT ON ce_result_binding BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_target_result WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'target_already_applied') END;
 SELECT CASE WHEN NEW.kind='worker_ack' AND NOT EXISTS(
  SELECT 1 FROM ce_barrier_attempt a JOIN ce_barrier_ack k USING(barrier_id)
  WHERE a.barrier_id=NEW.barrier_id AND a.fence_id=NEW.fence_id AND a.exit_id=NEW.exit_id
   AND NOT EXISTS(SELECT 1 FROM ce_barrier_failure WHERE barrier_id=a.barrier_id)
   AND a.ordinal=(SELECT max(ordinal) FROM ce_barrier_attempt WHERE fence_id=a.fence_id AND exit_id=a.exit_id))
  THEN RAISE(ABORT,'ack_not_current') END;
 SELECT CASE WHEN NEW.kind='supervisor_retired'
  AND NOT EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'retirement_unproven') END;
END;
CREATE TRIGGER ce_result_requires_binding BEFORE INSERT ON ce_target_result BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_result_binding WHERE fence_id=NEW.fence_id
  AND exit_id=NEW.exit_id AND kind=NEW.evidence_kind) THEN RAISE(ABORT,'result_binding_required') END;
 SELECT CASE WHEN NEW.evidence_kind='worker_ack' AND (
 EXISTS(SELECT permit_id,disposition,proof FROM ce_coverage WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id
  EXCEPT SELECT c.permit_id,c.disposition,c.proof FROM ce_barrier_coverage c JOIN ce_result_binding b USING(barrier_id)
  WHERE b.fence_id=NEW.fence_id AND b.exit_id=NEW.exit_id)
 OR EXISTS(SELECT c.permit_id,c.disposition,c.proof FROM ce_barrier_coverage c JOIN ce_result_binding b USING(barrier_id)
  WHERE b.fence_id=NEW.fence_id AND b.exit_id=NEW.exit_id
  EXCEPT SELECT permit_id,disposition,proof FROM ce_coverage WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id))
  THEN RAISE(ABORT,'selected_coverage_mismatch') END;
END;
-- 不等最终选择才保留已收到的强证据；含被放弃尝试的迟到ACK。
DROP VIEW ce_current_disposition;
CREATE VIEW ce_current_disposition AS
 SELECT p.permit_id,
 CASE WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM ce_barrier_coverage c JOIN ce_barrier_ack a USING(barrier_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM cu_coverage z JOIN cu_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cu_coverage z JOIN cu_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent' AND NOT EXISTS(SELECT 1 FROM cu_revocation r WHERE r.kind='ack' AND r.object_id=k.barrier_id)) THEN 'not_sent'
 ELSE 'unknown' END AS disposition FROM ce_permit p;

CREATE TRIGGER ce_barrier_attempt_u BEFORE UPDATE ON ce_barrier_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_barrier_attempt_d BEFORE DELETE ON ce_barrier_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_barrier_failure_u BEFORE UPDATE ON ce_barrier_failure BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_barrier_failure_d BEFORE DELETE ON ce_barrier_failure BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_barrier_coverage_u BEFORE UPDATE ON ce_barrier_coverage BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_barrier_coverage_d BEFORE DELETE ON ce_barrier_coverage BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_barrier_ack_u BEFORE UPDATE ON ce_barrier_ack BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_barrier_ack_d BEFORE DELETE ON ce_barrier_ack BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_result_binding_u BEFORE UPDATE ON ce_result_binding BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ce_result_binding_d BEFORE DELETE ON ce_result_binding BEGIN SELECT RAISE(ABORT,'immutable'); END;

-- 在controller.sql、fence.sql、barrier-attempt.sql之后加载。
-- 资源领域候选，不是生产迁移；BODY/提供者真实性仍由可信writer验证。
CREATE TABLE cr_validation (
 validation_id TEXT PRIMARY KEY NOT NULL,
 scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
 command_id TEXT REFERENCES ce_command(command_id),
 device_id TEXT NOT NULL CHECK(length(device_id)>0),
 purpose TEXT NOT NULL CHECK(purpose IN ('hold','close','settlement','release','recovery')),
 subject_id TEXT NOT NULL CHECK(length(subject_id)>0),
 subject_digest TEXT NOT NULL CHECK(length(subject_digest)=71 AND substr(subject_digest,1,7)='sha256:'
  AND substr(subject_digest,8) NOT GLOB '*[^0-9a-f]*'),
 policy_ref TEXT NOT NULL CHECK(length(policy_ref)>0),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),
 source_body BLOB NOT NULL CHECK(length(source_body)>0),
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 CHECK((purpose='recovery' AND command_id IS NULL) OR (purpose!='recovery' AND command_id IS NOT NULL)),
 UNIQUE(validation_id,device_id),
 FOREIGN KEY(validation_id) REFERENCES cd_manifest(validation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cr_validation_revocation (
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_validation(validation_id),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cr_claim (
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_command(command_id),
 release_policy_ref TEXT NOT NULL CHECK(length(release_policy_ref)>0),
 policy_body BLOB NOT NULL CHECK(length(policy_body)>0)
) STRICT;
CREATE TABLE cr_hold (
 hold_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL REFERENCES cr_claim(command_id),
 attempt_id TEXT UNIQUE REFERENCES ce_attempt(attempt_id),
 cancel_execution_id TEXT UNIQUE REFERENCES cg_plan(execution_id),
 cancel_release_policy_ref TEXT CHECK(cancel_release_policy_ref IS NULL OR length(cancel_release_policy_ref)>0),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 hold_digest TEXT NOT NULL,
 hold_body BLOB NOT NULL CHECK(length(hold_body)>0),
 CHECK((attempt_id IS NOT NULL AND cancel_execution_id IS NULL AND cancel_release_policy_ref IS NULL) OR
  (attempt_id IS NULL AND cancel_execution_id IS NOT NULL AND cancel_release_policy_ref IS NOT NULL)),
 UNIQUE(hold_id,command_id),
 FOREIGN KEY(hold_id) REFERENCES ow_commit(hold_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(hold_id) REFERENCES cr_hold_commit(hold_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cr_hold_commit (
 hold_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_hold(hold_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cr_hold_close (
 hold_id TEXT NOT NULL REFERENCES cr_hold_commit(hold_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 closure_digest TEXT NOT NULL,
 closure_body BLOB NOT NULL CHECK(length(closure_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(hold_id,validation_id)
) STRICT;
CREATE TABLE cr_settlement_validation (
 settlement_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_settlement(settlement_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 settlement_digest TEXT NOT NULL
) STRICT;
CREATE TABLE cr_release (
 release_id TEXT PRIMARY KEY NOT NULL,
 hold_id TEXT NOT NULL,
 command_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('never_sent','module_settled','maintenance_fenced')),
 issued_cut_revision TEXT NOT NULL CHECK(length(issued_cut_revision)=20
  AND issued_cut_revision NOT GLOB '*[^0-9]*'),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 release_digest TEXT NOT NULL,
 cancel_validation_id TEXT UNIQUE REFERENCES cr_validation(validation_id),
 cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 release_body BLOB NOT NULL CHECK(length(release_body)>0),
 FOREIGN KEY(hold_id,command_id) REFERENCES cr_hold(hold_id,command_id),
 FOREIGN KEY(release_id) REFERENCES cr_release_commit(release_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cr_release_attempt (
 release_id TEXT NOT NULL REFERENCES cr_release(release_id),
 attempt_id TEXT NOT NULL REFERENCES ce_attempt(attempt_id),
 hold_id TEXT NOT NULL REFERENCES cr_hold(hold_id),
 closure_validation_id TEXT NOT NULL,
 PRIMARY KEY(release_id,attempt_id),
 FOREIGN KEY(hold_id,closure_validation_id) REFERENCES cr_hold_close(hold_id,validation_id)
) STRICT;
CREATE TABLE cr_release_member (
 release_id TEXT NOT NULL REFERENCES cr_release(release_id),
 permit_id TEXT NOT NULL REFERENCES ce_permit(permit_id),
 settlement_id TEXT NOT NULL REFERENCES cr_settlement_validation(settlement_id),
 PRIMARY KEY(release_id,permit_id)
) STRICT;
CREATE TABLE cr_release_commit (
 release_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_release(release_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
-- 失效就是本机设备保护锁存。来源记录永久保留；同release只存首次失效原因，
-- 后续原始证据仍完整留在ce_*及revocation，不被此行去重丢弃。
CREATE TABLE cr_release_invalidation (
 release_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_release_commit(release_id),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('report','cancel_report','barrier_ack','target_result','validation_revocation','cancel_closure_ack','control_ack','control_ack_revocation')),
 source_id TEXT NOT NULL,
 source_exit_id TEXT,
 FOREIGN KEY(release_id) REFERENCES ro_incident(release_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((source_kind='target_result' AND source_exit_id IS NOT NULL)
    OR (source_kind!='target_result' AND source_exit_id IS NULL))
) STRICT;
CREATE TABLE cr_recovery (
 recovery_id TEXT PRIMARY KEY NOT NULL,
 device_id TEXT NOT NULL,
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 recovery_digest TEXT NOT NULL,
 recovery_body BLOB NOT NULL CHECK(length(recovery_body)>0),
 FOREIGN KEY(recovery_id) REFERENCES cr_recovery_commit(recovery_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cr_recovery_member (
 recovery_id TEXT NOT NULL REFERENCES cr_recovery(recovery_id),
 release_id TEXT NOT NULL REFERENCES cr_release_invalidation(release_id),
 PRIMARY KEY(recovery_id,release_id)
) STRICT;
CREATE TABLE cr_recovery_commit (
 recovery_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_recovery(recovery_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;

CREATE VIEW cr_valid_validation AS
 SELECT v.* FROM cr_validation v WHERE NOT EXISTS(
 SELECT 1 FROM cr_validation_revocation x WHERE x.validation_id=v.validation_id);
CREATE VIEW cr_release_validation AS
 SELECT release_id,validation_id FROM cr_release
 UNION SELECT release_id,closure_validation_id FROM cr_release_attempt
 UNION SELECT m.release_id,s.validation_id FROM cr_release_member m
 JOIN cr_settlement_validation s USING(settlement_id);
CREATE VIEW cr_invalid_release AS
 SELECT r.release_id FROM cr_release r JOIN cr_release_commit k USING(release_id)
 WHERE EXISTS(SELECT 1 FROM cr_release_validation p WHERE p.release_id=r.release_id
  AND NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=p.validation_id))
 OR EXISTS(SELECT 1 FROM cr_release_member m
   JOIN cr_settlement_validation sv USING(settlement_id) JOIN ce_settlement s USING(settlement_id)
   JOIN ce_current_disposition d ON d.permit_id=m.permit_id WHERE m.release_id=r.release_id
   AND (NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=sv.validation_id)
        OR (s.kind='never_sent' AND d.disposition='in_flight')));
-- 同一hold可追加新的完整释放；旧invalid记录及其设备锁存不删除。
CREATE VIEW cr_risk_hold AS
 SELECT h.*,c.device_id,c.origin FROM cr_hold h JOIN ce_command c USING(command_id)
 WHERE NOT EXISTS(SELECT 1 FROM cr_release r JOIN cr_release_commit k USING(release_id)
   WHERE r.hold_id=h.hold_id
   AND NOT EXISTS(SELECT 1 FROM cr_invalid_release x WHERE x.release_id=r.release_id)
   AND NOT EXISTS(SELECT 1 FROM cr_release_invalidation x WHERE x.release_id=r.release_id));
CREATE VIEW cr_device_protection AS
 SELECT x.release_id,h.command_id,c.device_id FROM cr_release_invalidation x
 JOIN cr_release r USING(release_id) JOIN cr_hold h USING(hold_id) JOIN ce_command c ON c.command_id=h.command_id
 WHERE NOT EXISTS(SELECT 1 FROM cr_recovery_member m JOIN cr_recovery y USING(recovery_id)
 JOIN cr_recovery_commit k USING(recovery_id) JOIN cr_valid_validation v ON v.validation_id=y.validation_id
 WHERE m.release_id=x.release_id AND y.device_id=c.device_id);

CREATE TRIGGER cr_claim_accept BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial c JOIN cr_claim p USING(command_id)
  WHERE c.key_id=NEW.key_id) THEN RAISE(ABORT,'resource_claim_required') END;
END;
CREATE TRIGGER cr_hold_guard BEFORE INSERT ON cr_hold WHEN NEW.attempt_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_command c USING(command_id)
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE a.attempt_id=NEW.attempt_id AND c.command_id=NEW.command_id
   AND v.command_id=NEW.command_id AND v.device_id=c.device_id AND v.purpose='hold'
   AND v.subject_id=NEW.hold_id AND v.subject_digest=NEW.hold_digest)
  THEN RAISE(ABORT,'hold_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_risk_hold h JOIN ce_command c ON c.device_id=h.device_id
  WHERE c.command_id=NEW.command_id) THEN RAISE(ABORT,'resource_busy') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_device_protection p JOIN ce_command c USING(device_id)
  WHERE c.command_id=NEW.command_id) THEN RAISE(ABORT,'device_protected') END;
END;
CREATE TRIGGER cr_hold_seal BEFORE INSERT ON cr_hold_commit WHEN EXISTS(SELECT 1 FROM cr_hold WHERE hold_id=NEW.hold_id AND attempt_id IS NOT NULL) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_hold h JOIN ce_permit p USING(attempt_id)
  JOIN ce_transmission_commit t USING(permit_id) WHERE h.hold_id=NEW.hold_id)
  THEN RAISE(ABORT,'hold_without_transmission') END;
END;
CREATE TRIGGER cr_permit_guard BEFORE INSERT ON ce_permit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_hold h JOIN cr_valid_validation v USING(validation_id)
  WHERE h.attempt_id=NEW.attempt_id) THEN RAISE(ABORT,'hold_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_hold h JOIN cr_hold_close c USING(hold_id)
  WHERE h.attempt_id=NEW.attempt_id) THEN RAISE(ABORT,'hold_closed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_command c USING(command_id)
  JOIN cr_device_protection p USING(device_id) WHERE a.attempt_id=NEW.attempt_id)
  THEN RAISE(ABORT,'device_protected') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_hold h JOIN ce_command c USING(command_id)
  JOIN cr_risk_hold other ON other.device_id=c.device_id AND other.hold_id!=h.hold_id
  WHERE h.attempt_id=NEW.attempt_id) THEN RAISE(ABORT,'resource_busy') END;
END;
CREATE TRIGGER cr_close_guard BEFORE INSERT ON cr_hold_close BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_hold h JOIN ce_command c USING(command_id)
  JOIN cr_claim p USING(command_id) JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE h.hold_id=NEW.hold_id AND v.command_id=h.command_id AND v.device_id=c.device_id
   AND v.purpose='close' AND v.subject_id=h.hold_id AND v.subject_digest=NEW.closure_digest
   AND v.policy_ref=p.release_policy_ref) THEN RAISE(ABORT,'closure_binding') END;
END;
CREATE TRIGGER cr_settlement_guard BEFORE INSERT ON cr_settlement_validation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_settlement s JOIN ce_permit t USING(permit_id)
  JOIN ce_attempt a USING(attempt_id) JOIN ce_command c USING(command_id) JOIN cr_claim p USING(command_id)
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE s.settlement_id=NEW.settlement_id AND v.command_id=c.command_id AND v.device_id=c.device_id
   AND v.purpose='settlement' AND v.subject_id=s.settlement_id
   AND v.subject_digest=NEW.settlement_digest AND v.policy_ref=p.release_policy_ref)
  THEN RAISE(ABORT,'settlement_binding') END;
END;
CREATE TRIGGER cr_release_seal BEFORE INSERT ON cr_release_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_release r JOIN ce_command c USING(command_id)
  JOIN cr_claim p USING(command_id) JOIN cr_valid_validation v USING(validation_id)
  WHERE r.release_id=NEW.release_id AND v.command_id=r.command_id AND v.device_id=c.device_id
   AND v.purpose='release' AND v.subject_id=r.release_id AND v.subject_digest=r.release_digest
   AND v.policy_ref=p.release_policy_ref
   AND r.issued_cut_revision=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue))
  THEN RAISE(ABORT,'release_binding') END;
 SELECT CASE WHEN EXISTS(SELECT a.attempt_id FROM ce_attempt a JOIN cr_release r USING(command_id)
  WHERE r.release_id=NEW.release_id EXCEPT SELECT attempt_id FROM cr_release_attempt WHERE release_id=NEW.release_id)
 OR EXISTS(SELECT attempt_id FROM cr_release_attempt WHERE release_id=NEW.release_id
  EXCEPT SELECT a.attempt_id FROM ce_attempt a JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id)
  THEN RAISE(ABORT,'release_attempt_set') END;
 SELECT CASE WHEN EXISTS(SELECT t.permit_id FROM ce_permit t JOIN ce_attempt a USING(attempt_id)
  JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id
  EXCEPT SELECT permit_id FROM cr_release_member WHERE release_id=NEW.release_id)
 OR EXISTS(SELECT permit_id FROM cr_release_member WHERE release_id=NEW.release_id
  EXCEPT SELECT t.permit_id FROM ce_permit t JOIN ce_attempt a USING(attempt_id)
  JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id)
  THEN RAISE(ABORT,'release_permit_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_release_attempt a WHERE a.release_id=NEW.release_id
  AND NOT EXISTS(SELECT 1 FROM cr_hold h JOIN cr_hold_close c USING(hold_id)
   JOIN cr_valid_validation v ON v.validation_id=c.validation_id
   WHERE h.attempt_id=a.attempt_id AND h.hold_id=a.hold_id AND c.validation_id=a.closure_validation_id))
  THEN RAISE(ABORT,'future_writes_not_closed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_release_member m JOIN ce_settlement s USING(settlement_id)
  JOIN cr_settlement_validation sv USING(settlement_id) JOIN ce_current_disposition d ON d.permit_id=m.permit_id
  JOIN cr_release r USING(release_id) WHERE m.release_id=NEW.release_id AND
   (m.permit_id!=s.permit_id OR NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=sv.validation_id)
    OR (s.kind='never_sent' AND d.disposition!='not_sent')
    OR (r.kind='never_sent' AND s.kind!='never_sent')))
  THEN RAISE(ABORT,'release_member_unproven') END;
END;
CREATE TRIGGER cr_release_attempt_frozen BEFORE INSERT ON cr_release_attempt
 WHEN EXISTS(SELECT 1 FROM cr_release_commit WHERE release_id=NEW.release_id)
 BEGIN SELECT RAISE(ABORT,'release_frozen'); END;
CREATE TRIGGER cr_release_member_frozen BEFORE INSERT ON cr_release_member
 WHEN EXISTS(SELECT 1 FROM cr_release_commit WHERE release_id=NEW.release_id)
 BEGIN SELECT RAISE(ABORT,'release_frozen'); END;
-- 封存核对当时全部集合；旧attempt永久close，不能再追加其permit。
-- 后续retry须在先前attempt释放封存之后新建attempt；政策由生命周期writer另验。
CREATE TRIGGER cr_attempt_predecessor BEFORE INSERT ON ce_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_attempt a WHERE a.command_id=NEW.command_id
  AND NOT EXISTS(SELECT 1 FROM cr_hold h JOIN cr_release r USING(hold_id)
    JOIN cr_release_commit k USING(release_id) WHERE h.attempt_id=a.attempt_id
    AND NOT EXISTS(SELECT 1 FROM cr_invalid_release x WHERE x.release_id=r.release_id)
    AND NOT EXISTS(SELECT 1 FROM cr_release_invalidation x WHERE x.release_id=r.release_id)))
 THEN RAISE(ABORT,'previous_attempt_unreleased') END;
END;

CREATE TRIGGER cr_report_invalidation AFTER INSERT ON ce_report WHEN NEW.disposition='in_flight' BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT x.release_id,'report',NEW.report_id,NULL FROM cr_invalid_release x
 JOIN cr_release_member m USING(release_id) WHERE m.permit_id=NEW.permit_id;
END;
CREATE TRIGGER cr_ack_invalidation AFTER INSERT ON ce_barrier_ack BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT x.release_id,'barrier_ack',NEW.barrier_id,NULL FROM cr_invalid_release x
 JOIN cr_release_member m USING(release_id) JOIN ce_barrier_coverage b USING(permit_id)
 WHERE b.barrier_id=NEW.barrier_id AND b.disposition='in_flight';
END;
CREATE TRIGGER cr_target_invalidation AFTER INSERT ON ce_target_result BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT x.release_id,'target_result',NEW.fence_id,NEW.exit_id FROM cr_invalid_release x
 JOIN cr_release_member m USING(release_id) JOIN ce_coverage b USING(permit_id)
 WHERE b.fence_id=NEW.fence_id AND b.exit_id=NEW.exit_id AND b.disposition='in_flight';
END;
CREATE TRIGGER cr_revoke_invalidation AFTER INSERT ON cr_validation_revocation BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT x.release_id,'validation_revocation',NEW.validation_id,NULL FROM cr_invalid_release x
 JOIN cr_release_validation p USING(release_id) WHERE p.validation_id=NEW.validation_id;
END;
CREATE TRIGGER cr_invalidation_source BEFORE INSERT ON cr_release_invalidation BEGIN
 SELECT CASE WHEN NEW.source_kind!='control_ack_revocation' AND NOT EXISTS(SELECT 1 FROM cr_invalid_release WHERE release_id=NEW.release_id)
  THEN RAISE(ABORT,'release_not_invalid') END;
 SELECT CASE WHEN NOT (
   (NEW.source_kind='report' AND EXISTS(SELECT 1 FROM ce_report p JOIN cr_release_member m USING(permit_id)
     WHERE p.report_id=NEW.source_id AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='barrier_ack' AND EXISTS(SELECT 1 FROM ce_barrier_ack a
     JOIN ce_barrier_coverage p USING(barrier_id) JOIN cr_release_member m USING(permit_id)
     WHERE a.barrier_id=NEW.source_id AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='target_result' AND EXISTS(SELECT 1 FROM ce_target_result a
     JOIN ce_coverage p USING(fence_id,exit_id) JOIN cr_release_member m USING(permit_id)
     WHERE a.fence_id=NEW.source_id AND a.exit_id=NEW.source_exit_id
      AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='cancel_report' AND EXISTS(SELECT 1 FROM cf_report p JOIN cx_release_member m USING(permit_id)
     WHERE p.report_id=NEW.source_id AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='barrier_ack' AND EXISTS(SELECT 1 FROM ce_barrier_ack a JOIN cf_barrier_coverage p USING(barrier_id)
     JOIN cx_release_member m USING(permit_id) WHERE a.barrier_id=NEW.source_id AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='target_result' AND EXISTS(SELECT 1 FROM ce_target_result a JOIN cf_target_coverage p USING(fence_id,exit_id)
     JOIN cx_release_member m USING(permit_id) WHERE a.fence_id=NEW.source_id AND a.exit_id=NEW.source_exit_id
      AND m.release_id=NEW.release_id AND p.disposition='in_flight'))
   OR (NEW.source_kind='cancel_closure_ack' AND EXISTS(SELECT 1 FROM cc_ack a JOIN cc_coverage c USING(barrier_id)
    WHERE a.barrier_id=NEW.source_id AND c.disposition='in_flight' AND (EXISTS(SELECT 1 FROM cr_release_member m
     WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id) OR EXISTS(SELECT 1 FROM cx_release_member m
     WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id))))
   OR (NEW.source_kind='control_ack_revocation' AND EXISTS(SELECT 1 FROM cu_revocation v JOIN cu_coverage c ON c.barrier_id=v.object_id
    WHERE v.kind='ack' AND v.object_id=NEW.source_id AND c.disposition='not_sent' AND (EXISTS(SELECT 1 FROM cr_release_member m
     JOIN ce_settlement s USING(settlement_id) WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id AND s.kind='never_sent') OR EXISTS(SELECT 1 FROM cx_release_member m
     JOIN cf_settlement s USING(settlement_id) WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id AND s.kind='never_sent'))))
   OR (NEW.source_kind='control_ack' AND EXISTS(SELECT 1 FROM cu_ack a JOIN cu_coverage c USING(barrier_id)
    WHERE a.barrier_id=NEW.source_id AND c.disposition='in_flight' AND (EXISTS(SELECT 1 FROM cr_release_member m
     WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id) OR EXISTS(SELECT 1 FROM cx_release_member m
     WHERE m.release_id=NEW.release_id AND m.permit_id=c.permit_id))))
   OR (NEW.source_kind='validation_revocation' AND EXISTS(
     SELECT 1 FROM cr_validation_revocation p JOIN cr_release_validation r USING(validation_id)
     WHERE p.validation_id=NEW.source_id AND r.release_id=NEW.release_id)))
  THEN RAISE(ABORT,'invalidation_source') END;
END;

CREATE TRIGGER cr_recovery_seal BEFORE INSERT ON cr_recovery_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_recovery r JOIN cr_valid_validation v USING(validation_id)
  WHERE r.recovery_id=NEW.recovery_id AND v.device_id=r.device_id AND v.purpose='recovery'
   AND v.command_id IS NULL AND v.subject_id=r.recovery_id AND v.subject_digest=r.recovery_digest)
  THEN RAISE(ABORT,'recovery_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_risk_hold h JOIN cr_recovery r USING(device_id)
  WHERE r.recovery_id=NEW.recovery_id) THEN RAISE(ABORT,'recovery_resource_busy') END;
 SELECT CASE WHEN EXISTS(SELECT x.release_id FROM cr_release_invalidation x JOIN cr_release y USING(release_id)
  JOIN ce_command c USING(command_id) JOIN cr_recovery r USING(device_id)
  WHERE r.recovery_id=NEW.recovery_id EXCEPT SELECT release_id FROM cr_recovery_member WHERE recovery_id=NEW.recovery_id)
 OR EXISTS(SELECT release_id FROM cr_recovery_member WHERE recovery_id=NEW.recovery_id
  EXCEPT SELECT x.release_id FROM cr_release_invalidation x JOIN cr_release y USING(release_id)
  JOIN ce_command c USING(command_id) JOIN cr_recovery r USING(device_id) WHERE r.recovery_id=NEW.recovery_id)
  THEN RAISE(ABORT,'recovery_protection_set') END;
END;
CREATE TRIGGER cr_recovery_member_frozen BEFORE INSERT ON cr_recovery_member
 WHEN EXISTS(SELECT 1 FROM cr_recovery_commit WHERE recovery_id=NEW.recovery_id)
 BEGIN SELECT RAISE(ABORT,'recovery_frozen'); END;

CREATE TRIGGER cr_validation_u BEFORE UPDATE ON cr_validation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_validation_d BEFORE DELETE ON cr_validation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_validation_revocation_u BEFORE UPDATE ON cr_validation_revocation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_validation_revocation_d BEFORE DELETE ON cr_validation_revocation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_claim_u BEFORE UPDATE ON cr_claim BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_claim_d BEFORE DELETE ON cr_claim BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_u BEFORE UPDATE ON cr_hold BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_d BEFORE DELETE ON cr_hold BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_commit_u BEFORE UPDATE ON cr_hold_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_commit_d BEFORE DELETE ON cr_hold_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_close_u BEFORE UPDATE ON cr_hold_close BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_hold_close_d BEFORE DELETE ON cr_hold_close BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_settlement_validation_u BEFORE UPDATE ON cr_settlement_validation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_settlement_validation_d BEFORE DELETE ON cr_settlement_validation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_u BEFORE UPDATE ON cr_release BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_d BEFORE DELETE ON cr_release BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_attempt_u BEFORE UPDATE ON cr_release_attempt BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_attempt_d BEFORE DELETE ON cr_release_attempt BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_member_u BEFORE UPDATE ON cr_release_member BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_member_d BEFORE DELETE ON cr_release_member BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_commit_u BEFORE UPDATE ON cr_release_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_commit_d BEFORE DELETE ON cr_release_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_invalidation_u BEFORE UPDATE ON cr_release_invalidation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_release_invalidation_d BEFORE DELETE ON cr_release_invalidation BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_u BEFORE UPDATE ON cr_recovery BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_d BEFORE DELETE ON cr_recovery BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_member_u BEFORE UPDATE ON cr_recovery_member BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_member_d BEFORE DELETE ON cr_recovery_member BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_commit_u BEFORE UPDATE ON cr_recovery_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

CREATE TRIGGER cr_recovery_commit_d BEFORE DELETE ON cr_recovery_commit BEGIN SELECT RAISE(ABORT,'immutable_resource'); END;

-- 66表资源组合之后加载。命令修订候选，非生产迁移。
CREATE TABLE cm_policy (
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_claim(command_id),
 required_completion TEXT NOT NULL CHECK(required_completion IN ('sent','acknowledged','effect_verified')),
 completion_policy_ref TEXT NOT NULL CHECK(length(completion_policy_ref)>0),
 retry_policy_ref TEXT,
 max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 16),
 original_deadline_body BLOB NOT NULL CHECK(length(original_deadline_body)>0),
 policy_body BLOB NOT NULL CHECK(length(policy_body)>0),
 CHECK(retry_policy_ref IS NOT NULL OR max_attempts=1)
) STRICT;
CREATE TABLE cm_validation (
 validation_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL REFERENCES cm_policy(command_id),
 purpose TEXT NOT NULL CHECK(purpose IN ('transition','completion','failure','cancellation','resolution')),
 subject_id TEXT NOT NULL CHECK(length(subject_id)>0),
 subject_digest TEXT NOT NULL CHECK(length(subject_digest)=71 AND substr(subject_digest,1,7)='sha256:'
  AND substr(subject_digest,8) NOT GLOB '*[^0-9a-f]*'),
 policy_ref TEXT NOT NULL CHECK(length(policy_ref)>0),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),
 source_body BLOB NOT NULL CHECK(length(source_body)>0),
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0)
) STRICT;
CREATE TABLE cm_decision (
 evidence_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL REFERENCES cm_policy(command_id),
 kind TEXT NOT NULL CHECK(kind IN ('completion','failure','cancellation','resolution')),
 achieved TEXT CHECK(achieved IN ('sent','acknowledged','effect_verified')),
 effect_status TEXT NOT NULL CHECK(effect_status IN ('not_sent','possible','acknowledged','verified','partial')),
 retry_policy_ref TEXT,
 resolved_outcome TEXT CHECK(resolved_outcome IN ('succeeded','failed','cancelled','not_sent')),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cm_validation(validation_id),
 evidence_digest TEXT NOT NULL,
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 CHECK((kind='completion' AND achieved IS NOT NULL) OR (kind!='completion' AND achieved IS NULL)),
 CHECK((kind='resolution' AND resolved_outcome IS NOT NULL) OR (kind!='resolution' AND resolved_outcome IS NULL)),
 UNIQUE(evidence_id,command_id)
) STRICT;
CREATE TABLE cm_attempt (
 attempt_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_attempt(attempt_id) DEFERRABLE INITIALLY DEFERRED,
 command_id TEXT NOT NULL REFERENCES cm_policy(command_id),
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 16),
 prepared_revision TEXT NOT NULL,
 UNIQUE(command_id,ordinal),
 FOREIGN KEY(command_id,prepared_revision) REFERENCES cm_revision(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cm_revision (
 command_id TEXT NOT NULL REFERENCES cm_policy(command_id),
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'
  AND revision>'00000000000000000000'),
 operation_id TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('initial','prepare','dispatch','transport','complete','fail',
  'timeout','cancel','block','expire','retry','reconcile','release','protect','observe')),
 previous_revision TEXT,
 previous_digest TEXT,
 transition_digest TEXT NOT NULL CHECK(length(transition_digest)=71 AND substr(transition_digest,1,7)='sha256:'
  AND substr(transition_digest,8) NOT GLOB '*[^0-9a-f]*'),
 state_digest TEXT NOT NULL CHECK(length(state_digest)=71 AND substr(state_digest,1,7)='sha256:'
  AND substr(state_digest,8) NOT GLOB '*[^0-9a-f]*'),
 phase TEXT NOT NULL CHECK(phase IN ('queued','dispatching','awaiting_evidence','finished')),
 outcome TEXT NOT NULL CHECK(outcome IN ('pending','succeeded','failed','cancelled','blocked','expired','unknown')),
 effect_status TEXT NOT NULL CHECK(effect_status IN ('not_sent','possible','acknowledged','verified','partial')),
 resource_status TEXT NOT NULL CHECK(resource_status IN ('clear','held','unresolved')),
 paused_latched INTEGER NOT NULL CHECK(paused_latched IN (0,1)),
 terminal_revision TEXT,
 resolution_id TEXT,
 decision_id TEXT,
 validation_id TEXT NOT NULL UNIQUE REFERENCES cm_validation(validation_id),
 state_body BLOB NOT NULL CHECK(length(state_body)>0),
 PRIMARY KEY(command_id,revision),
 UNIQUE(command_id,revision,operation_id),
 FOREIGN KEY(command_id,previous_revision) REFERENCES cm_revision(command_id,revision),
 FOREIGN KEY(decision_id,command_id) REFERENCES cm_decision(evidence_id,command_id),
 FOREIGN KEY(resolution_id,command_id) REFERENCES cm_resolution(resolution_id,command_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id) REFERENCES cm_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((kind='initial' AND previous_revision IS NULL AND previous_digest IS NULL)
    OR (kind!='initial' AND previous_revision IS NOT NULL AND previous_digest IS NOT NULL)),
 CHECK((phase='finished' AND outcome!='pending' AND terminal_revision IS NOT NULL)
    OR (phase!='finished' AND outcome='pending' AND terminal_revision IS NULL)),
 CHECK(outcome NOT IN ('unknown','blocked','expired') OR paused_latched=1),
 CHECK(phase!='finished' OR resource_status!='held'),
 CHECK(outcome!='unknown' OR effect_status!='not_sent'),
 CHECK(outcome!='unknown' OR resource_status!='clear' OR resolution_id IS NOT NULL)
) STRICT;
CREATE TABLE cm_revision_attempt (
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES cm_attempt(attempt_id),
 PRIMARY KEY(command_id,revision,attempt_id),
 FOREIGN KEY(command_id,revision) REFERENCES cm_revision(command_id,revision)
) STRICT;
CREATE TABLE cm_revision_release (
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 release_id TEXT NOT NULL REFERENCES cr_release_commit(release_id),
 PRIMARY KEY(command_id,revision,release_id),
 FOREIGN KEY(command_id,revision) REFERENCES cm_revision(command_id,revision)
) STRICT;
CREATE TABLE cm_resolution (
 resolution_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL REFERENCES cm_policy(command_id),
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'
  AND revision>'00000000000000000000'),
 original_terminal_revision TEXT NOT NULL,
 published_revision TEXT NOT NULL,
 resolved_outcome TEXT NOT NULL CHECK(resolved_outcome IN ('succeeded','failed','cancelled','not_sent')),
 decision_id TEXT NOT NULL,
 resolver_ref TEXT NOT NULL CHECK(length(resolver_ref)>0),
 resolution_digest TEXT NOT NULL,
 resolution_body BLOB NOT NULL CHECK(length(resolution_body)>0),
 UNIQUE(resolution_id,command_id), UNIQUE(command_id,revision),
 FOREIGN KEY(decision_id,command_id) REFERENCES cm_decision(evidence_id,command_id),
 FOREIGN KEY(command_id,published_revision) REFERENCES cm_revision(command_id,revision) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(command_id,original_terminal_revision) REFERENCES cm_revision(command_id,revision)
) STRICT;
CREATE TABLE cm_report_receipt (
 worker_boot_id TEXT NOT NULL,
 ipc_session_id TEXT NOT NULL,
 worker_report_id TEXT NOT NULL,
 stored_report_id TEXT NOT NULL UNIQUE,
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 report_digest TEXT NOT NULL CHECK(length(report_digest)=71 AND substr(report_digest,1,7)='sha256:'
  AND substr(report_digest,8) NOT GLOB '*[^0-9a-f]*'),
 PRIMARY KEY(worker_boot_id,ipc_session_id,worker_report_id),
 FOREIGN KEY(stored_report_id) REFERENCES ce_report(report_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(command_id,revision) REFERENCES cm_revision(command_id,revision) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(worker_boot_id)>0 AND length(ipc_session_id)>0 AND length(worker_report_id)>0)
) STRICT;
CREATE TABLE cm_commit (
 operation_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 UNIQUE(command_id,revision),
 FOREIGN KEY(command_id,revision,operation_id) REFERENCES cm_revision(command_id,revision,operation_id)
) STRICT;

CREATE VIEW cm_latest AS
 SELECT r.* FROM cm_revision r JOIN cm_commit k USING(command_id,revision,operation_id)
 WHERE NOT EXISTS(SELECT 1 FROM cm_revision newer JOIN cm_commit nk
  ON nk.operation_id=newer.operation_id WHERE newer.command_id=r.command_id AND newer.revision>r.revision);
-- 迟到屏障或证明撤回可先持久保护；旧不可变State不能继续作为当前clear发布。
-- writer补protect/observe后才重新开放当前投影，历史快照仍可审计查询。
CREATE VIEW cm_current AS
 SELECT r.* FROM cm_latest r WHERE
  (r.resource_status!='clear' OR NOT EXISTS(SELECT 1 FROM cr_risk_hold h WHERE h.command_id=r.command_id))
  AND (r.paused_latched=1 OR NOT EXISTS(SELECT 1 FROM cr_device_protection p JOIN ce_command c USING(device_id)
    WHERE c.command_id=r.command_id));

CREATE TRIGGER cm_accept BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial c JOIN cm_latest r USING(command_id)
  WHERE c.key_id=NEW.key_id AND r.revision='00000000000000000001' AND r.kind='initial')
  THEN RAISE(ABORT,'initial_state_required') END;
END;
CREATE TRIGGER cm_decision_guard BEFORE INSERT ON cm_decision BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_validation v JOIN cm_policy p USING(command_id)
  WHERE v.validation_id=NEW.validation_id AND v.command_id=NEW.command_id AND v.purpose=NEW.kind
   AND v.subject_id=NEW.evidence_id AND v.subject_digest=NEW.evidence_digest
   AND v.policy_ref=p.completion_policy_ref) THEN RAISE(ABORT,'decision_provider_binding') END;
 SELECT CASE WHEN NEW.kind='completion' AND NEW.effect_status!=CASE NEW.achieved
  WHEN 'sent' THEN 'possible' WHEN 'acknowledged' THEN 'acknowledged' ELSE 'verified' END
  THEN RAISE(ABORT,'completion_effect') END;
END;
CREATE TRIGGER cm_attempt_register AFTER INSERT ON ce_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_attempt WHERE attempt_id=NEW.attempt_id
  AND command_id=NEW.command_id) THEN RAISE(ABORT,'attempt_revision_required') END;
END;
CREATE TRIGGER cm_attempt_guard BEFORE INSERT ON cm_attempt BEGIN
 SELECT CASE WHEN NEW.ordinal!=(SELECT count(*)+1 FROM cm_attempt WHERE command_id=NEW.command_id)
  OR NEW.ordinal>(SELECT max_attempts FROM cm_policy WHERE command_id=NEW.command_id)
  THEN RAISE(ABORT,'attempt_budget') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_latest r WHERE r.command_id=NEW.command_id
  AND r.phase='queued' AND r.paused_latched=0 AND (NEW.ordinal=1 OR r.kind='retry'))
  THEN RAISE(ABORT,'attempt_state') END;
END;
CREATE TRIGGER cm_revision_guard BEFORE INSERT ON cm_revision BEGIN
 SELECT CASE WHEN NEW.revision!=(SELECT printf('%010d%010d',
  CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
  (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
  FROM (SELECT coalesce(max(revision),'00000000000000000000') v FROM cm_revision WHERE command_id=NEW.command_id))
  THEN RAISE(ABORT,'state_successor') END;
 SELECT CASE WHEN NEW.kind='initial' AND (NEW.revision!='00000000000000000001' OR
  NEW.phase!='queued' OR NEW.outcome!='pending' OR NEW.effect_status!='not_sent' OR
  NEW.resource_status!='clear' OR NEW.paused_latched!=0 OR NEW.resolution_id IS NOT NULL)
  THEN RAISE(ABORT,'initial_state') END;
 SELECT CASE WHEN NEW.kind!='initial' AND NOT EXISTS(SELECT 1 FROM cm_latest r
  WHERE r.command_id=NEW.command_id AND r.revision=NEW.previous_revision AND r.state_digest=NEW.previous_digest)
  THEN RAISE(ABORT,'state_cas') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_latest r WHERE r.command_id=NEW.command_id
  AND r.phase='finished' AND (NEW.phase!=r.phase OR NEW.outcome!=r.outcome OR
   NEW.terminal_revision IS NOT r.terminal_revision OR NEW.kind NOT IN ('reconcile','release','protect','observe')))
  THEN RAISE(ABORT,'terminal_immutable') END;
 SELECT CASE WHEN NEW.phase='finished' AND NOT EXISTS(SELECT 1 FROM cm_latest r
  WHERE r.command_id=NEW.command_id AND r.phase='finished') AND NEW.terminal_revision!=NEW.revision
  THEN RAISE(ABORT,'terminal_revision') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_latest r WHERE r.command_id=NEW.command_id
  AND r.paused_latched=1 AND NEW.paused_latched=0) THEN RAISE(ABORT,'latch_immutable') END;
 SELECT CASE WHEN NEW.kind IN ('timeout','block','expire','protect') AND NEW.paused_latched!=1
  THEN RAISE(ABORT,'latch_required') END;
 SELECT CASE WHEN NEW.kind!='reconcile' AND NEW.resolution_id IS NOT
  (SELECT resolution_id FROM cm_latest WHERE command_id=NEW.command_id)
  THEN RAISE(ABORT,'resolution_rewrite') END;
END;
CREATE TRIGGER cm_commit_guard BEFORE INSERT ON cm_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_revision r JOIN cm_validation v USING(validation_id)
  JOIN cm_policy p ON p.command_id=r.command_id WHERE r.operation_id=NEW.operation_id
   AND v.command_id=r.command_id AND v.purpose='transition' AND v.subject_id=r.operation_id
   AND v.subject_digest=r.transition_digest AND v.policy_ref=p.completion_policy_ref)
  THEN RAISE(ABORT,'transition_provider_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r JOIN ce_command c USING(command_id)
  JOIN cr_device_protection p USING(device_id) WHERE r.operation_id=NEW.operation_id AND r.paused_latched!=1)
  THEN RAISE(ABORT,'device_latch_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r JOIN cm_latest old USING(command_id)
  WHERE r.operation_id=NEW.operation_id AND
   ((old.effect_status='partial' AND r.effect_status!='partial')
    OR (old.effect_status='verified' AND r.effect_status NOT IN ('partial','verified'))
    OR (old.effect_status='acknowledged' AND r.effect_status NOT IN ('partial','verified','acknowledged'))
    OR (old.effect_status='possible' AND r.effect_status='not_sent' AND
      (r.kind NOT IN ('cancel','block','expire') OR EXISTS(SELECT 1 FROM ce_permit p
       JOIN ce_attempt a USING(attempt_id) JOIN ce_current_disposition d USING(permit_id)
       WHERE a.command_id=r.command_id AND d.disposition!='not_sent')))))
  THEN RAISE(ABORT,'effect_downgrade') END;
 SELECT CASE WHEN EXISTS(SELECT attempt_id FROM cm_attempt WHERE command_id=NEW.command_id
  EXCEPT SELECT attempt_id FROM cm_revision_attempt WHERE command_id=NEW.command_id AND revision=NEW.revision)
 OR EXISTS(SELECT attempt_id FROM cm_revision_attempt WHERE command_id=NEW.command_id AND revision=NEW.revision
  EXCEPT SELECT attempt_id FROM cm_attempt WHERE command_id=NEW.command_id)
  THEN RAISE(ABORT,'state_attempt_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_dispatch_binding b WHERE b.command_id=NEW.command_id
  AND b.revision=NEW.revision AND NOT EXISTS(SELECT 1 FROM cm_revision r JOIN cr_hold h
   ON h.hold_id=b.hold_id JOIN cm_attempt a ON a.attempt_id=h.attempt_id
   WHERE r.operation_id=NEW.operation_id AND r.kind='dispatch' AND h.command_id=r.command_id
    AND a.ordinal=(SELECT max(ordinal) FROM cm_attempt WHERE command_id=r.command_id)))
  THEN RAISE(ABORT,'dispatch_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_resolution z WHERE z.command_id=NEW.command_id
  AND z.published_revision=NEW.revision AND NOT EXISTS(SELECT 1 FROM cm_revision r
    WHERE r.operation_id=NEW.operation_id AND r.kind='reconcile' AND r.resolution_id=z.resolution_id
     AND r.decision_id=z.decision_id)) THEN RAISE(ABORT,'resolution_pair') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_attempt a WHERE a.command_id=NEW.command_id AND a.prepared_revision=NEW.revision
  AND NOT EXISTS(SELECT 1 FROM cm_revision r WHERE r.command_id=a.command_id AND r.revision=a.prepared_revision
    AND r.kind='prepare')) THEN RAISE(ABORT,'prepare_revision') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision_release x JOIN cr_release r USING(release_id)
  WHERE x.command_id=NEW.command_id AND x.revision=NEW.revision AND r.command_id!=NEW.command_id)
  THEN RAISE(ABORT,'release_owner') END;
 SELECT CASE WHEN EXISTS(SELECT release_id FROM cm_revision_release x JOIN cm_latest r USING(command_id,revision)
  WHERE x.command_id=NEW.command_id EXCEPT SELECT release_id FROM cm_revision_release
  WHERE command_id=NEW.command_id AND revision=NEW.revision) THEN RAISE(ABORT,'release_history_lost') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r WHERE r.operation_id=NEW.operation_id AND r.resource_status='clear'
  AND (EXISTS(SELECT 1 FROM cr_risk_hold h WHERE h.command_id=r.command_id)
   OR EXISTS(SELECT 1 FROM cr_hold h WHERE h.command_id=r.command_id AND NOT EXISTS(
    SELECT 1 FROM cm_revision_release x JOIN cr_release y USING(release_id)
    WHERE x.command_id=r.command_id AND x.revision=r.revision AND y.hold_id=h.hold_id
    AND NOT EXISTS(SELECT 1 FROM cr_invalid_release z WHERE z.release_id=y.release_id)
    AND NOT EXISTS(SELECT 1 FROM cr_release_invalidation z WHERE z.release_id=y.release_id)))))
  THEN RAISE(ABORT,'resource_not_clear') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r WHERE r.operation_id=NEW.operation_id
  AND r.resource_status='held' AND NOT EXISTS(SELECT 1 FROM cr_risk_hold h WHERE h.command_id=r.command_id))
  THEN RAISE(ABORT,'hold_unproven') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r WHERE r.operation_id=NEW.operation_id AND r.kind IN ('complete','fail','retry')
  AND NOT EXISTS(SELECT 1 FROM cm_decision d WHERE d.evidence_id=r.decision_id AND d.command_id=r.command_id
   AND d.kind=CASE r.kind WHEN 'complete' THEN 'completion' ELSE 'failure' END))
  THEN RAISE(ABORT,'decision_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r WHERE r.operation_id=NEW.operation_id
  AND r.kind='cancel' AND EXISTS(SELECT 1 FROM ce_permit p JOIN ce_attempt a USING(attempt_id)
    WHERE a.command_id=r.command_id) AND NOT EXISTS(SELECT 1 FROM cm_decision d
     WHERE d.evidence_id=r.decision_id AND d.kind='cancellation' AND d.command_id=r.command_id))
  THEN RAISE(ABORT,'cancellation_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r JOIN cm_attempt a USING(command_id)
  WHERE r.operation_id=NEW.operation_id AND r.kind IN ('block','expire')
   AND a.ordinal=(SELECT max(ordinal) FROM cm_attempt WHERE command_id=r.command_id)
   AND (EXISTS(SELECT 1 FROM ce_permit p JOIN ce_current_disposition d USING(permit_id)
       WHERE p.attempt_id=a.attempt_id AND d.disposition!='not_sent')
     OR EXISTS(SELECT 1 FROM cr_hold h WHERE h.attempt_id=a.attempt_id AND NOT EXISTS(
       SELECT 1 FROM cr_hold_close c JOIN cr_valid_validation v USING(validation_id) WHERE c.hold_id=h.hold_id))))
  THEN RAISE(ABORT,'stop_unfenced_or_uncertain') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r JOIN cm_decision d ON d.evidence_id=r.decision_id
  JOIN cm_policy p ON p.command_id=r.command_id WHERE r.operation_id=NEW.operation_id AND r.kind='complete'
  AND (CASE d.achieved WHEN 'sent' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END)<
      (CASE p.required_completion WHEN 'sent' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END))
  THEN RAISE(ABORT,'completion_level') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r JOIN cm_policy p USING(command_id)
  WHERE r.operation_id=NEW.operation_id AND r.kind='retry' AND
   (p.retry_policy_ref IS NULL OR r.paused_latched=1 OR r.resource_status!='clear'
    OR (SELECT count(*) FROM cm_attempt a WHERE a.command_id=r.command_id)>=p.max_attempts
    OR NOT EXISTS(SELECT 1 FROM cm_decision d WHERE d.evidence_id=r.decision_id
      AND d.retry_policy_ref=p.retry_policy_ref))) THEN RAISE(ABORT,'retry_forbidden') END;
 -- 保守结构约束；精确时钟、safe_failure、取消与全部效果仍由transition提供者核验。
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_revision r LEFT JOIN cm_latest old ON old.command_id=r.command_id
  WHERE r.operation_id=NEW.operation_id AND NOT(
   r.kind='initial'
   OR (r.kind='prepare' AND old.phase='queued' AND old.paused_latched=0
     AND r.phase='queued' AND r.outcome='pending' AND EXISTS(SELECT 1 FROM cm_attempt a
       WHERE a.command_id=r.command_id AND a.prepared_revision=r.revision))
   OR (r.kind='dispatch' AND old.phase='queued' AND old.paused_latched=0 AND r.phase='dispatching'
     AND r.resource_status='held' AND EXISTS(SELECT 1 FROM cm_dispatch_binding b
       JOIN cr_hold h USING(hold_id) JOIN cr_hold_commit k USING(hold_id)
       WHERE b.command_id=r.command_id AND b.revision=r.revision))
   OR (r.kind='transport' AND old.phase='dispatching' AND r.phase='awaiting_evidence'
     AND EXISTS(SELECT 1 FROM ce_current_disposition d JOIN ce_permit p USING(permit_id)
       JOIN ce_attempt a USING(attempt_id) JOIN cm_attempt ca USING(attempt_id)
       WHERE a.command_id=r.command_id AND d.disposition='in_flight'
        AND ca.ordinal=(SELECT max(ordinal) FROM cm_attempt WHERE command_id=r.command_id)))
   OR (r.kind IN ('complete','fail','timeout') AND old.phase IN ('dispatching','awaiting_evidence')
     AND r.phase='finished' AND r.outcome=CASE r.kind WHEN 'complete' THEN 'succeeded' WHEN 'fail' THEN 'failed' ELSE 'unknown' END)
   OR (r.kind IN ('cancel','block','expire') AND old.phase!='finished' AND r.phase='finished'
     AND r.outcome=CASE r.kind WHEN 'cancel' THEN 'cancelled' WHEN 'block' THEN 'blocked' ELSE 'expired' END)
   OR (r.kind='retry' AND old.phase='awaiting_evidence' AND r.phase='queued')
   OR (r.kind='reconcile' AND old.phase='finished' AND EXISTS(SELECT 1 FROM cm_resolution z
     WHERE z.resolution_id=r.resolution_id AND z.command_id=r.command_id AND z.published_revision=r.revision))
   OR (r.kind='release' AND old.phase='finished' AND r.resource_status='clear')
   OR (r.kind IN ('protect','observe') AND r.phase=old.phase AND r.outcome=old.outcome)))
  THEN RAISE(ABORT,'invalid_transition') END;
END;
CREATE TABLE cm_dispatch_binding (
 hold_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_hold(hold_id),
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 UNIQUE(command_id,revision),
 FOREIGN KEY(command_id,revision) REFERENCES cm_revision(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER cm_hold_binding BEFORE INSERT ON cr_hold_commit WHEN EXISTS(SELECT 1 FROM cr_hold WHERE hold_id=NEW.hold_id AND attempt_id IS NOT NULL) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_dispatch_binding b JOIN cr_hold h USING(hold_id)
  WHERE b.hold_id=NEW.hold_id AND b.command_id=h.command_id)
  THEN RAISE(ABORT,'dispatch_revision_required') END;
END;
CREATE TRIGGER cm_hold_state BEFORE INSERT ON cr_hold WHEN NEW.attempt_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_current r WHERE r.command_id=NEW.command_id
  AND r.phase='queued' AND r.paused_latched=0 AND r.resource_status='clear')
  THEN RAISE(ABORT,'hold_state') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_command c JOIN ce_command other USING(device_id)
  JOIN cm_latest r ON r.command_id=other.command_id
  WHERE c.command_id=NEW.command_id AND other.command_id!=NEW.command_id AND r.resource_status!='clear'
  AND EXISTS(SELECT 1 FROM cr_hold h WHERE h.command_id=other.command_id))
  THEN RAISE(ABORT,'command_resource_unresolved') END;
END;
CREATE TRIGGER cm_permit_state BEFORE INSERT ON ce_permit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN cm_latest r USING(command_id)
  WHERE a.attempt_id=NEW.attempt_id AND r.paused_latched=0
   AND (r.phase IN ('dispatching','awaiting_evidence') OR
     (r.phase='queued' AND EXISTS(SELECT 1 FROM cr_hold h JOIN cm_dispatch_binding b USING(hold_id)
      WHERE h.attempt_id=a.attempt_id AND NOT EXISTS(SELECT 1 FROM cm_commit k
        WHERE k.command_id=b.command_id AND k.revision=b.revision)))))
  THEN RAISE(ABORT,'permit_command_state') END;
END;
CREATE TRIGGER cm_resolution_guard BEFORE INSERT ON cm_resolution BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.published_revision)
  THEN RAISE(ABORT,'state_frozen') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_latest r JOIN cm_decision d ON d.evidence_id=NEW.decision_id
  WHERE r.command_id=NEW.command_id AND r.phase='finished' AND r.terminal_revision=NEW.original_terminal_revision
   AND d.command_id=r.command_id AND d.kind='resolution' AND d.resolved_outcome=NEW.resolved_outcome)
  THEN RAISE(ABORT,'resolution_binding') END;
 SELECT CASE WHEN NEW.revision!=(SELECT printf('%010d%010d',
  CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
  (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
  FROM (SELECT coalesce(max(revision),'00000000000000000000') v FROM cm_resolution WHERE command_id=NEW.command_id))
  THEN RAISE(ABORT,'resolution_successor') END;
END;
CREATE TRIGGER cm_report_guard AFTER INSERT ON ce_report BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_report_receipt r JOIN ce_exit e
  ON e.worker_boot_id=r.worker_boot_id AND e.ipc_session_id=r.ipc_session_id
  JOIN ce_permit p ON p.exit_id=e.exit_id JOIN ce_attempt a USING(attempt_id)
  WHERE r.stored_report_id=NEW.report_id AND p.permit_id=NEW.permit_id AND e.exit_id=NEW.exit_id
   AND r.command_id=a.command_id AND NOT EXISTS(SELECT 1 FROM cm_commit c
     WHERE c.command_id=r.command_id AND c.revision=r.revision))
  THEN RAISE(ABORT,'report_receipt_binding') END;
END;
CREATE TRIGGER cm_attempt_link_guard BEFORE INSERT ON cm_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.prepared_revision)
  THEN RAISE(ABORT,'state_frozen') END;
END;
CREATE TRIGGER cm_dispatch_link_guard BEFORE INSERT ON cm_dispatch_binding BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.revision)
  THEN RAISE(ABORT,'state_frozen') END;
END;
CREATE TRIGGER cm_revision_attempt_frozen BEFORE INSERT ON cm_revision_attempt
 WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.revision)
 BEGIN SELECT RAISE(ABORT,'state_frozen'); END;
CREATE TRIGGER cm_revision_release_frozen BEFORE INSERT ON cm_revision_release
 WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.revision)
 BEGIN SELECT RAISE(ABORT,'state_frozen'); END;

CREATE TRIGGER cm_policy_u BEFORE UPDATE ON cm_policy BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_policy_d BEFORE DELETE ON cm_policy BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_validation_u BEFORE UPDATE ON cm_validation BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_validation_d BEFORE DELETE ON cm_validation BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_decision_u BEFORE UPDATE ON cm_decision BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_decision_d BEFORE DELETE ON cm_decision BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_attempt_u BEFORE UPDATE ON cm_attempt BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_attempt_d BEFORE DELETE ON cm_attempt BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_revision_u BEFORE UPDATE ON cm_revision BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_revision_d BEFORE DELETE ON cm_revision BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_revision_attempt_u BEFORE UPDATE ON cm_revision_attempt BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_revision_attempt_d BEFORE DELETE ON cm_revision_attempt BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_revision_release_u BEFORE UPDATE ON cm_revision_release BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_revision_release_d BEFORE DELETE ON cm_revision_release BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_resolution_u BEFORE UPDATE ON cm_resolution BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_resolution_d BEFORE DELETE ON cm_resolution BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_report_receipt_u BEFORE UPDATE ON cm_report_receipt BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_report_receipt_d BEFORE DELETE ON cm_report_receipt BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_commit_u BEFORE UPDATE ON cm_commit BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_commit_d BEFORE DELETE ON cm_commit BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_dispatch_binding_u BEFORE UPDATE ON cm_dispatch_binding BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

CREATE TRIGGER cm_dispatch_binding_d BEFORE DELETE ON cm_dispatch_binding BEGIN SELECT RAISE(ABORT,'immutable_command'); END;

-- 在Controller77表之后加载；14表公开修订/取消候选，不是生产迁移。
-- 一个writer；foreign_keys与recursive_triggers必须在事务外开启。
CREATE TABLE cv_metadata (
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ca_command_initial(command_id),
 initial_revision TEXT NOT NULL CHECK(initial_revision='00000000000000000001'),
 metadata_digest TEXT NOT NULL CHECK(length(metadata_digest)=71 AND substr(metadata_digest,1,7)='sha256:'
  AND substr(metadata_digest,8) NOT GLOB '*[^0-9a-f]*'),
 metadata_body BLOB NOT NULL CHECK(length(metadata_body)>0),
 UNIQUE(command_id,metadata_digest),
 FOREIGN KEY(command_id,initial_revision) REFERENCES cv_record(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_evidence (
 evidence_id TEXT NOT NULL,
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'
  AND revision>'00000000000000000000'),
 command_id TEXT NOT NULL REFERENCES cv_metadata(command_id),
 first_state_revision TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('observation','decision','release','resolution','invalidation')),
 source_digest TEXT NOT NULL CHECK(length(source_digest)=71 AND substr(source_digest,1,7)='sha256:'
  AND substr(source_digest,8) NOT GLOB '*[^0-9a-f]*'),
 view_digest TEXT NOT NULL CHECK(length(view_digest)=71 AND substr(view_digest,1,7)='sha256:'
  AND substr(view_digest,8) NOT GLOB '*[^0-9a-f]*'),
 source_body BLOB NOT NULL CHECK(length(source_body)>0),
 view_body BLOB NOT NULL CHECK(length(view_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 decision_id TEXT REFERENCES cm_decision(evidence_id),
 release_id TEXT REFERENCES cr_release_commit(release_id),
 resolution_id TEXT REFERENCES cm_resolution(resolution_id),
 subject_id TEXT, subject_revision TEXT,
 protection_ref_body BLOB,
 PRIMARY KEY(evidence_id,revision),
 CHECK(substr(evidence_id,1,length(kind)+1)=kind||'.'),
 CHECK((kind='decision')=(decision_id IS NOT NULL)),
 CHECK((kind='release')=(release_id IS NOT NULL)),
 CHECK((kind='resolution')=(resolution_id IS NOT NULL)),
 CHECK(decision_id IS NULL OR decision_id=evidence_id),
 CHECK(release_id IS NULL OR release_id=evidence_id),
 CHECK(resolution_id IS NULL OR resolution_id=evidence_id),
 CHECK(kind='resolution' OR revision='00000000000000000001'),
 CHECK((kind='invalidation' AND subject_id IS NOT NULL AND subject_revision IS NOT NULL
   AND protection_ref_body IS NOT NULL AND length(protection_ref_body)>0)
  OR (kind!='invalidation' AND subject_id IS NULL AND subject_revision IS NULL AND protection_ref_body IS NULL)),
 FOREIGN KEY(subject_id,subject_revision) REFERENCES cv_evidence(evidence_id,revision),
 FOREIGN KEY(command_id,first_state_revision) REFERENCES cm_commit(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_snapshot (
 snapshot_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL,
 state_revision TEXT NOT NULL,
 state_digest TEXT NOT NULL,
 total TEXT NOT NULL CHECK(length(total)=20 AND total NOT GLOB '*[^0-9]*'),
 snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=71 AND substr(snapshot_digest,1,7)='sha256:'
  AND substr(snapshot_digest,8) NOT GLOB '*[^0-9a-f]*'),
 manifest_body BLOB NOT NULL CHECK(length(manifest_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 UNIQUE(command_id,state_revision), UNIQUE(snapshot_id,command_id,state_revision),
 FOREIGN KEY(command_id,state_revision) REFERENCES cv_record(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_snapshot_member (
 snapshot_id TEXT NOT NULL REFERENCES cv_snapshot(snapshot_id),
 ordinal TEXT NOT NULL CHECK(length(ordinal)=20 AND ordinal NOT GLOB '*[^0-9]*'),
 evidence_id TEXT NOT NULL,
 evidence_revision TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,ordinal), UNIQUE(snapshot_id,evidence_id,evidence_revision),
 FOREIGN KEY(evidence_id,evidence_revision) REFERENCES cv_evidence(evidence_id,revision)
) STRICT;
CREATE TABLE cv_record (
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 state_digest TEXT NOT NULL,
 metadata_digest TEXT NOT NULL,
 snapshot_id TEXT NOT NULL,
 cancellation_id TEXT, cancellation_revision TEXT,
 record_digest TEXT NOT NULL CHECK(length(record_digest)=71 AND substr(record_digest,1,7)='sha256:'
  AND substr(record_digest,8) NOT GLOB '*[^0-9a-f]*'),
 record_body BLOB NOT NULL CHECK(length(record_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 PRIMARY KEY(command_id,revision),
 CHECK((cancellation_id IS NULL)=(cancellation_revision IS NULL)),
 FOREIGN KEY(command_id,revision) REFERENCES cm_commit(command_id,revision) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(command_id,metadata_digest) REFERENCES cv_metadata(command_id,metadata_digest),
 FOREIGN KEY(snapshot_id,command_id,revision) REFERENCES cv_snapshot(snapshot_id,command_id,state_revision),
 FOREIGN KEY(cancellation_id,cancellation_revision,command_id)
  REFERENCES cv_cancel_revision(cancellation_id,revision,command_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_cancel_key (
 key_id TEXT PRIMARY KEY NOT NULL,
 namespace_id TEXT NOT NULL REFERENCES ca_namespace(namespace_id),
 operation_id TEXT NOT NULL CHECK(operation_id='cancelCommand'),
 idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)>0),
 request_digest TEXT NOT NULL CHECK(length(request_digest)=71 AND substr(request_digest,1,7)='sha256:'
  AND substr(request_digest,8) NOT GLOB '*[^0-9a-f]*'),
 content_body BLOB NOT NULL CHECK(length(content_body)>0),
 authorization_body BLOB NOT NULL CHECK(length(authorization_body)>0),
 UNIQUE(namespace_id,operation_id,idempotency_key),
 FOREIGN KEY(key_id) REFERENCES cv_cancel(key_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_cancel (
 cancellation_id TEXT PRIMARY KEY NOT NULL,
 command_id TEXT NOT NULL UNIQUE REFERENCES cm_policy(command_id),
 key_id TEXT NOT NULL UNIQUE REFERENCES cv_cancel_key(key_id),
 mode TEXT NOT NULL CHECK(mode IN ('before_dispatch_only','cooperative')),
 accepted_revision TEXT NOT NULL,
 accepted_state_digest TEXT NOT NULL,
 initial_revision TEXT NOT NULL CHECK(initial_revision='00000000000000000001'),
 cut_revision TEXT NOT NULL CHECK(length(cut_revision)=20 AND cut_revision NOT GLOB '*[^0-9]*'),
 cut_digest TEXT NOT NULL CHECK(length(cut_digest)=71 AND substr(cut_digest,1,7)='sha256:'
  AND substr(cut_digest,8) NOT GLOB '*[^0-9a-f]*'),
 cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 policy_body BLOB NOT NULL CHECK(length(policy_body)>0),
 UNIQUE(cancellation_id,command_id),
 FOREIGN KEY(command_id,accepted_revision) REFERENCES cm_commit(command_id,revision),
 FOREIGN KEY(cancellation_id,initial_revision,command_id)
  REFERENCES cv_cancel_revision(cancellation_id,revision,command_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancellation_id) REFERENCES cv_cancel_receipt(cancellation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancellation_id,command_id) REFERENCES cv_cancel_deny(cancellation_id,command_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancellation_id) REFERENCES cv_cancel_commit(cancellation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_cancel_revision (
 cancellation_id TEXT NOT NULL,
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'
  AND revision>'00000000000000000000'),
 command_id TEXT NOT NULL,
 state_revision TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('requested','confirmed','unsupported','failed','indeterminate','too_late')),
 future_writes TEXT NOT NULL CHECK(future_writes IN ('pending','closed','indeterminate')),
 closure_id TEXT REFERENCES cc_closure(closure_id),
 closure_validation_body BLOB,
 result_validation_body BLOB,
 operation_digest TEXT NOT NULL CHECK(length(operation_digest)=71 AND substr(operation_digest,1,7)='sha256:'
  AND substr(operation_digest,8) NOT GLOB '*[^0-9a-f]*'),
 operation_body BLOB NOT NULL CHECK(length(operation_body)>0),
 PRIMARY KEY(cancellation_id,revision), UNIQUE(cancellation_id,revision,command_id), UNIQUE(command_id,state_revision),
 CHECK((future_writes='closed' AND closure_validation_body IS NOT NULL AND length(closure_validation_body)>0)
  OR (future_writes!='closed' AND closure_validation_body IS NULL)),
 CHECK((future_writes='closed')=(closure_id IS NOT NULL)),
 CHECK(state!='confirmed' OR future_writes='closed'),
 CHECK(state NOT IN ('confirmed','unsupported','failed','too_late')
  OR (result_validation_body IS NOT NULL AND length(result_validation_body)>0)),
 FOREIGN KEY(cancellation_id,command_id) REFERENCES cv_cancel(cancellation_id,command_id),
 FOREIGN KEY(command_id,state_revision) REFERENCES cm_commit(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cv_cancel_receipt (
 cancellation_id TEXT PRIMARY KEY NOT NULL REFERENCES cv_cancel(cancellation_id),
 initial_revision TEXT NOT NULL CHECK(initial_revision='00000000000000000001'),
 initial_operation_digest TEXT NOT NULL,
 receipt_digest TEXT NOT NULL CHECK(length(receipt_digest)=71 AND substr(receipt_digest,1,7)='sha256:'
  AND substr(receipt_digest,8) NOT GLOB '*[^0-9a-f]*'),
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 FOREIGN KEY(cancellation_id,initial_revision) REFERENCES cv_cancel_revision(cancellation_id,revision)
) STRICT;
CREATE TABLE cv_cancel_deny (
 command_id TEXT PRIMARY KEY NOT NULL,
 cancellation_id TEXT NOT NULL UNIQUE,
 UNIQUE(cancellation_id,command_id),
 FOREIGN KEY(cancellation_id,command_id) REFERENCES cv_cancel(cancellation_id,command_id)
) STRICT;
CREATE TABLE cv_cancel_attempt (
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel(cancellation_id),
 attempt_id TEXT NOT NULL REFERENCES ce_attempt(attempt_id),
 PRIMARY KEY(cancellation_id,attempt_id)
) STRICT;
CREATE TABLE cv_cancel_target (
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel(cancellation_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 PRIMARY KEY(cancellation_id,exit_id)
) STRICT;
CREATE TABLE cv_cancel_permit (
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel(cancellation_id),
 permit_id TEXT NOT NULL REFERENCES ce_permit(permit_id),
 PRIMARY KEY(cancellation_id,permit_id)
) STRICT;
CREATE TABLE cv_cancel_commit (
 cancellation_id TEXT PRIMARY KEY NOT NULL REFERENCES cv_cancel(cancellation_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE CHECK(length(outbox_id)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;

CREATE VIEW cv_history AS
 SELECT p.* FROM cv_record p JOIN cm_commit c USING(command_id,revision);
CREATE VIEW cv_current AS
 SELECT p.* FROM cv_history p JOIN cm_current s USING(command_id,revision);
CREATE VIEW cv_cancel_current AS
 SELECT c.* FROM cv_cancel_revision c JOIN cm_commit m ON m.command_id=c.command_id AND m.revision=c.state_revision
 JOIN cv_cancel_commit k USING(cancellation_id)
 WHERE NOT EXISTS(SELECT 1 FROM cv_cancel_revision n JOIN cm_commit nm ON nm.command_id=n.command_id
  AND nm.revision=n.state_revision WHERE n.cancellation_id=c.cancellation_id AND n.revision>c.revision);

CREATE TRIGGER cv_evidence_guard BEFORE INSERT ON cv_evidence BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.first_state_revision)
  THEN RAISE(ABORT,'evidence_revision_frozen') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_evidence WHERE evidence_id=NEW.evidence_id
  AND (command_id!=NEW.command_id OR kind!=NEW.kind)) THEN RAISE(ABORT,'evidence_identity_owner') END;
 SELECT CASE WHEN NEW.kind='decision' AND NOT EXISTS(SELECT 1 FROM cm_decision
  WHERE evidence_id=NEW.decision_id AND command_id=NEW.command_id AND evidence_digest=NEW.source_digest)
  THEN RAISE(ABORT,'decision_source') END;
 SELECT CASE WHEN NEW.kind='release' AND NOT EXISTS(SELECT 1 FROM cr_release
  WHERE release_id=NEW.release_id AND command_id=NEW.command_id AND release_digest=NEW.source_digest)
  THEN RAISE(ABORT,'release_source') END;
 SELECT CASE WHEN NEW.kind='resolution' AND NOT EXISTS(SELECT 1 FROM cm_resolution
  WHERE resolution_id=NEW.resolution_id AND command_id=NEW.command_id AND resolution_digest=NEW.source_digest
   AND revision=NEW.revision)
  THEN RAISE(ABORT,'resolution_source') END;
 SELECT CASE WHEN NEW.kind='invalidation' AND NOT EXISTS(SELECT 1 FROM cv_evidence
  WHERE evidence_id=NEW.subject_id AND revision=NEW.subject_revision AND command_id=NEW.command_id)
  THEN RAISE(ABORT,'invalidation_owner') END;
END;
CREATE TRIGGER cv_record_guard BEFORE INSERT ON cv_record BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.revision)
  THEN RAISE(ABORT,'public_revision_frozen') END;
END;
CREATE TRIGGER cv_member_guard BEFORE INSERT ON cv_snapshot_member BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_snapshot s JOIN cm_commit c
  ON c.command_id=s.command_id AND c.revision=s.state_revision WHERE s.snapshot_id=NEW.snapshot_id)
  THEN RAISE(ABORT,'snapshot_frozen') END;
END;
CREATE TRIGGER cv_publish AFTER INSERT ON cm_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_record p JOIN cv_snapshot s USING(snapshot_id)
  JOIN cm_revision r ON r.command_id=p.command_id AND r.revision=p.revision
  WHERE p.command_id=NEW.command_id AND p.revision=NEW.revision
   AND p.state_digest=r.state_digest AND s.state_digest=r.state_digest)
  THEN RAISE(ABORT,'complete_public_revision_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_snapshot s WHERE s.command_id=NEW.command_id
  AND s.state_revision=NEW.revision AND s.total!=printf('%020d',
   (SELECT count(*) FROM cv_snapshot_member m WHERE m.snapshot_id=s.snapshot_id)))
  THEN RAISE(ABORT,'snapshot_count') END;
 -- 完整历史成员双向差集；不能只核count而遗漏或替换证据。
 SELECT CASE WHEN EXISTS(
  SELECT evidence_id,revision FROM cv_evidence WHERE command_id=NEW.command_id AND first_state_revision<=NEW.revision
  EXCEPT SELECT m.evidence_id,m.evidence_revision FROM cv_snapshot_member m JOIN cv_snapshot s USING(snapshot_id)
   WHERE s.command_id=NEW.command_id AND s.state_revision=NEW.revision)
 OR EXISTS(
  SELECT m.evidence_id,m.evidence_revision FROM cv_snapshot_member m JOIN cv_snapshot s USING(snapshot_id)
   WHERE s.command_id=NEW.command_id AND s.state_revision=NEW.revision
  EXCEPT SELECT evidence_id,revision FROM cv_evidence WHERE command_id=NEW.command_id AND first_state_revision<=NEW.revision)
  THEN RAISE(ABORT,'snapshot_members') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM
  (SELECT evidence_id,revision,printf('%020d',row_number() OVER(ORDER BY evidence_id,revision,kind)-1) ordinal
   FROM cv_evidence WHERE command_id=NEW.command_id AND first_state_revision<=NEW.revision) e
  JOIN cv_snapshot s ON s.command_id=NEW.command_id AND s.state_revision=NEW.revision
  JOIN cv_snapshot_member m ON m.snapshot_id=s.snapshot_id AND m.evidence_id=e.evidence_id
   AND m.evidence_revision=e.revision WHERE m.ordinal!=e.ordinal)
  THEN RAISE(ABORT,'snapshot_order') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_record p WHERE p.command_id=NEW.command_id AND p.revision=NEW.revision
  AND (p.cancellation_id IS NOT (SELECT c.cancellation_id FROM cv_cancel_revision c
     WHERE c.command_id=NEW.command_id AND c.state_revision<=NEW.revision ORDER BY c.revision DESC LIMIT 1)
   OR p.cancellation_revision IS NOT (SELECT c.revision FROM cv_cancel_revision c
     WHERE c.command_id=NEW.command_id AND c.state_revision<=NEW.revision ORDER BY c.revision DESC LIMIT 1)))
  THEN RAISE(ABORT,'cancel_projection') END;
END;
CREATE TRIGGER cv_cancel_admit BEFORE INSERT ON cv_cancel BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_latest WHERE command_id=NEW.command_id
  AND revision=NEW.accepted_revision AND state_digest=NEW.accepted_state_digest)
  THEN RAISE(ABORT,'cancel_cas') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_cancel_key k JOIN ca_namespace_closure c USING(namespace_id)
  WHERE k.key_id=NEW.key_id) THEN RAISE(ABORT,'cancel_namespace_closed') END;
 SELECT CASE WHEN NEW.cut_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  THEN RAISE(ABORT,'cancel_cut_highwater') END;
END;
CREATE TRIGGER cv_cancel_progress BEFORE INSERT ON cv_cancel_revision BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.state_revision)
  THEN RAISE(ABORT,'cancel_state_frozen') END;
 SELECT CASE WHEN NEW.revision!=(SELECT printf('%010d%010d',
  CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
  (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
  FROM (SELECT coalesce(max(revision),'00000000000000000000') v FROM cv_cancel_revision
    WHERE cancellation_id=NEW.cancellation_id)) THEN RAISE(ABORT,'cancel_successor') END;
 SELECT CASE WHEN NEW.revision!='00000000000000000001' AND NOT EXISTS(
  SELECT 1 FROM cv_cancel_current old WHERE old.cancellation_id=NEW.cancellation_id
   AND old.revision=(SELECT max(revision) FROM cv_cancel_revision WHERE cancellation_id=NEW.cancellation_id))
  THEN RAISE(ABORT,'cancel_previous_uncommitted') END;
 SELECT CASE WHEN NEW.revision='00000000000000000001' AND (NEW.state!='requested' OR NEW.future_writes!='pending'
  OR NEW.state_revision!=(SELECT printf('%010d%010d',
    CAST(substr(accepted_revision,1,10) AS INTEGER)+(substr(accepted_revision,11,10)='9999999999'),
    (CAST(substr(accepted_revision,11,10) AS INTEGER)+1)%10000000000)
   FROM cv_cancel WHERE cancellation_id=NEW.cancellation_id))
  THEN RAISE(ABORT,'cancel_initial') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_cancel_current old WHERE old.cancellation_id=NEW.cancellation_id
  AND (NEW.state_revision<=old.state_revision
   OR (old.state IN ('confirmed','unsupported','failed','too_late') AND NEW.state!=old.state)
   OR (old.state='indeterminate' AND NEW.state='requested')
   OR (old.future_writes='closed' AND NEW.future_writes!='closed')))
  THEN RAISE(ABORT,'cancel_regression') END;
END;
CREATE TRIGGER cv_cancel_seal BEFORE INSERT ON cv_cancel_commit BEGIN
 SELECT CASE WHEN (SELECT cut_revision FROM cv_cancel WHERE cancellation_id=NEW.cancellation_id)
  !=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  THEN RAISE(ABORT,'cancel_cut_changed') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel c JOIN cv_cancel_revision r
  ON r.cancellation_id=c.cancellation_id AND r.revision=c.initial_revision
  JOIN cv_cancel_receipt p ON p.cancellation_id=c.cancellation_id
  JOIN cm_commit m ON m.command_id=c.command_id AND m.revision=r.state_revision
  WHERE c.cancellation_id=NEW.cancellation_id AND p.initial_operation_digest=r.operation_digest)
  THEN RAISE(ABORT,'cancel_receipt_pair') END;
 SELECT CASE WHEN EXISTS(
  SELECT a.attempt_id FROM ce_attempt a JOIN cv_cancel c USING(command_id) WHERE c.cancellation_id=NEW.cancellation_id
  EXCEPT SELECT attempt_id FROM cv_cancel_attempt WHERE cancellation_id=NEW.cancellation_id)
 OR EXISTS(SELECT attempt_id FROM cv_cancel_attempt WHERE cancellation_id=NEW.cancellation_id
  EXCEPT SELECT a.attempt_id FROM ce_attempt a JOIN cv_cancel c USING(command_id) WHERE c.cancellation_id=NEW.cancellation_id)
  THEN RAISE(ABORT,'cancel_attempt_set') END;
 SELECT CASE WHEN EXISTS(
  SELECT e.exit_id FROM ce_exit e JOIN ce_command cmd USING(device_id) JOIN cv_cancel c USING(command_id)
   WHERE c.cancellation_id=NEW.cancellation_id
  EXCEPT SELECT exit_id FROM cv_cancel_target WHERE cancellation_id=NEW.cancellation_id)
 OR EXISTS(SELECT exit_id FROM cv_cancel_target WHERE cancellation_id=NEW.cancellation_id
  EXCEPT SELECT e.exit_id FROM ce_exit e JOIN ce_command cmd USING(device_id) JOIN cv_cancel c USING(command_id)
   WHERE c.cancellation_id=NEW.cancellation_id) THEN RAISE(ABORT,'cancel_exit_set') END;
 SELECT CASE WHEN EXISTS(
  SELECT p.permit_id FROM ce_permit p JOIN ce_attempt a USING(attempt_id) JOIN cv_cancel c USING(command_id)
   WHERE c.cancellation_id=NEW.cancellation_id
  EXCEPT SELECT permit_id FROM cv_cancel_permit WHERE cancellation_id=NEW.cancellation_id)
 OR EXISTS(SELECT permit_id FROM cv_cancel_permit WHERE cancellation_id=NEW.cancellation_id
  EXCEPT SELECT p.permit_id FROM ce_permit p JOIN ce_attempt a USING(attempt_id) JOIN cv_cancel c USING(command_id)
   WHERE c.cancellation_id=NEW.cancellation_id) THEN RAISE(ABORT,'cancel_permit_set') END;
END;
CREATE TRIGGER cv_cancel_attempt_frozen BEFORE INSERT ON cv_cancel_attempt
 WHEN EXISTS(SELECT 1 FROM cv_cancel_commit WHERE cancellation_id=NEW.cancellation_id)
 BEGIN SELECT RAISE(ABORT,'cancel_cut_frozen'); END;
CREATE TRIGGER cv_cancel_target_frozen BEFORE INSERT ON cv_cancel_target
 WHEN EXISTS(SELECT 1 FROM cv_cancel_commit WHERE cancellation_id=NEW.cancellation_id)
 BEGIN SELECT RAISE(ABORT,'cancel_cut_frozen'); END;
CREATE TRIGGER cv_cancel_permit_frozen BEFORE INSERT ON cv_cancel_permit
 WHEN EXISTS(SELECT 1 FROM cv_cancel_commit WHERE cancellation_id=NEW.cancellation_id)
 BEGIN SELECT RAISE(ABORT,'cancel_cut_frozen'); END;
CREATE TRIGGER cv_no_attempt BEFORE INSERT ON cm_attempt
 WHEN EXISTS(SELECT 1 FROM cv_cancel_deny WHERE command_id=NEW.command_id)
 BEGIN SELECT RAISE(ABORT,'command_cancelled'); END;
CREATE TRIGGER cv_no_hold BEFORE INSERT ON cr_hold
 WHEN NEW.attempt_id IS NOT NULL AND EXISTS(SELECT 1 FROM cv_cancel_deny WHERE command_id=NEW.command_id)
 BEGIN SELECT RAISE(ABORT,'command_cancelled'); END;
CREATE TRIGGER cv_no_permit BEFORE INSERT ON ce_permit
 WHEN EXISTS(SELECT 1 FROM cv_cancel_deny d JOIN ce_attempt a USING(command_id) WHERE a.attempt_id=NEW.attempt_id)
 BEGIN SELECT RAISE(ABORT,'command_cancelled'); END;

CREATE TRIGGER cv_metadata_u BEFORE UPDATE ON cv_metadata BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_metadata_d BEFORE DELETE ON cv_metadata BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_evidence_u BEFORE UPDATE ON cv_evidence BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_evidence_d BEFORE DELETE ON cv_evidence BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_snapshot_u BEFORE UPDATE ON cv_snapshot BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_snapshot_d BEFORE DELETE ON cv_snapshot BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_snapshot_member_u BEFORE UPDATE ON cv_snapshot_member BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_snapshot_member_d BEFORE DELETE ON cv_snapshot_member BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_record_u BEFORE UPDATE ON cv_record BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_record_d BEFORE DELETE ON cv_record BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_key_u BEFORE UPDATE ON cv_cancel_key BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_key_d BEFORE DELETE ON cv_cancel_key BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_u BEFORE UPDATE ON cv_cancel BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_d BEFORE DELETE ON cv_cancel BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_revision_u BEFORE UPDATE ON cv_cancel_revision BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_revision_d BEFORE DELETE ON cv_cancel_revision BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_receipt_u BEFORE UPDATE ON cv_cancel_receipt BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_receipt_d BEFORE DELETE ON cv_cancel_receipt BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_deny_u BEFORE UPDATE ON cv_cancel_deny BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_deny_d BEFORE DELETE ON cv_cancel_deny BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_attempt_u BEFORE UPDATE ON cv_cancel_attempt BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_attempt_d BEFORE DELETE ON cv_cancel_attempt BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_target_u BEFORE UPDATE ON cv_cancel_target BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_target_d BEFORE DELETE ON cv_cancel_target BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_permit_u BEFORE UPDATE ON cv_cancel_permit BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_permit_d BEFORE DELETE ON cv_cancel_permit BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_commit_u BEFORE UPDATE ON cv_cancel_commit BEGIN SELECT RAISE(ABORT,'immutable_public'); END;
CREATE TRIGGER cv_cancel_commit_d BEFORE DELETE ON cv_cancel_commit BEGIN SELECT RAISE(ABORT,'immutable_public'); END;

-- 共享签发索引候选，必须由build_issue_ledger.py与91表一起组合；非生产迁移。
CREATE TABLE ci_issue (
 permit_id TEXT PRIMARY KEY NOT NULL,
 issued_revision TEXT NOT NULL UNIQUE CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*' AND issued_revision>'00000000000000000000'),
 kind TEXT NOT NULL CHECK(kind IN ('ordinary','cancel')),
 ordinary_id TEXT UNIQUE,
 cancel_id TEXT UNIQUE,
 CHECK((kind='ordinary' AND ordinary_id IS permit_id AND cancel_id IS NULL) OR
       (kind='cancel' AND cancel_id IS permit_id AND ordinary_id IS NULL)),
 UNIQUE(permit_id,issued_revision,kind),
 FOREIGN KEY(permit_id,issued_revision,kind) REFERENCES fa_seal(permit_id,issued_revision,kind) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(ordinary_id) REFERENCES ce_permit(permit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancel_id) REFERENCES ci_cancel_transmission(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ci_cancel_transmission (
 permit_id TEXT PRIMARY KEY NOT NULL,
 issued_revision TEXT NOT NULL UNIQUE,
 issue_kind TEXT NOT NULL CHECK(issue_kind='cancel'),
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel(cancellation_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 execution_id TEXT NOT NULL,
 execution_digest TEXT NOT NULL CHECK(length(execution_digest)=71 AND substr(execution_digest,1,7)='sha256:' AND substr(execution_digest,8) NOT GLOB '*[^0-9a-f]*'),
 primitive_id TEXT NOT NULL,
 packet_id TEXT NOT NULL,
 packet_digest TEXT NOT NULL CHECK(length(packet_digest)=71 AND substr(packet_digest,1,7)='sha256:' AND substr(packet_digest,8) NOT GLOB '*[^0-9a-f]*'),
 ordinal INTEGER NOT NULL CHECK(ordinal>=0 AND ordinal<=2147483647),
 initial_permit_id TEXT,
 origin TEXT NOT NULL CHECK(origin IN ('manual','automation')),
 origin_authority TEXT,
 origin_database TEXT,
 run_id TEXT,
 generation TEXT CHECK(generation IS NULL OR (length(generation)=20 AND generation NOT GLOB '*[^0-9]*' AND generation>'00000000000000000000')),
 time_required INTEGER NOT NULL CHECK(time_required IN (0,1)),
 time_binding_body BLOB,
 transmission_body BLOB NOT NULL CHECK(length(transmission_body)>0),
 CHECK((origin='manual' AND origin_authority IS NULL AND origin_database IS NULL AND run_id IS NULL AND generation IS NULL) OR
       (origin='automation' AND origin_authority IS NOT NULL AND origin_database IS NOT NULL AND run_id IS NOT NULL AND generation IS NOT NULL)),
 CHECK((time_required=0 AND time_binding_body IS NULL) OR (time_required=1 AND time_binding_body IS NOT NULL AND length(time_binding_body)>0)),
 CHECK((ordinal=0 AND initial_permit_id IS NULL) OR (ordinal>0 AND initial_permit_id IS NOT NULL)),
 UNIQUE(cancellation_id,primitive_id,ordinal),
 FOREIGN KEY(permit_id,issued_revision,issue_kind) REFERENCES ci_issue(permit_id,issued_revision,kind) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(initial_permit_id) REFERENCES ci_cancel_transmission(permit_id),
 FOREIGN KEY(permit_id) REFERENCES ci_cancel_commit(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ci_cancel_commit (
 permit_id TEXT PRIMARY KEY NOT NULL REFERENCES ci_cancel_transmission(permit_id),
 ordinary_closure_body BLOB NOT NULL CHECK(length(ordinary_closure_body)>0),
 execution_validation_body BLOB NOT NULL CHECK(length(execution_validation_body)>0),
 guard_body BLOB NOT NULL CHECK(length(guard_body)>0),
 budget_charge_body BLOB NOT NULL CHECK(length(budget_charge_body)>0),
 packet_bytes BLOB NOT NULL CHECK(length(packet_bytes)>0),
 dispatch_intent_body BLOB NOT NULL CHECK(length(dispatch_intent_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 FOREIGN KEY(permit_id) REFERENCES cc_dispatch(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER ci_issue_guard BEFORE INSERT ON ci_issue BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_issue WHERE issued_revision='99999999999999999999')
  THEN RAISE(ABORT,'issue_exhausted') END;
 SELECT CASE WHEN NEW.issued_revision!=(SELECT printf('%010d%010d',
  CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
  (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
  FROM (SELECT coalesce(max(issued_revision),'00000000000000000000') v FROM ci_issue))
  THEN RAISE(ABORT,'issued_successor') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_pending_cut)
  THEN RAISE(ABORT,'pending_cut') END;
END;
CREATE TRIGGER ci_ordinary_pair BEFORE INSERT ON ce_permit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ci_issue WHERE permit_id=NEW.permit_id
  AND issued_revision=NEW.issued_revision AND kind='ordinary')
  THEN RAISE(ABORT,'ordinary_issue_pair') END;
END;
CREATE TRIGGER ci_cancel_guard BEFORE INSERT ON ci_cancel_transmission BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ci_issue WHERE permit_id=NEW.permit_id
  AND issued_revision=NEW.issued_revision AND kind='cancel')
  THEN RAISE(ABORT,'cancel_issue_pair') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel c JOIN cv_cancel_commit k USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN ce_exit e ON e.device_id=cmd.device_id
  WHERE c.cancellation_id=NEW.cancellation_id AND c.mode='cooperative' AND e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'cancel_execution_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'exit_retired') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_cancel c JOIN cr_release r USING(command_id)
  WHERE c.cancellation_id=NEW.cancellation_id)
  THEN RAISE(ABORT,'cancel_after_release') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cv_cancel_current WHERE cancellation_id=NEW.cancellation_id
  AND (future_writes='closed' OR state IN ('confirmed','unsupported','failed','too_late','indeterminate')))
  THEN RAISE(ABORT,'cancel_execution_closed') END;
 SELECT CASE WHEN NEW.origin='automation' AND EXISTS(SELECT 1 FROM run_deny_event d
  WHERE (d.origin_authority,d.origin_database,d.run_id)=(NEW.origin_authority,NEW.origin_database,NEW.run_id)
   AND d.generation>=NEW.generation) THEN RAISE(ABORT,'run_denied') END;
 SELECT CASE WHEN NEW.ordinal!=(SELECT coalesce(max(ordinal),-1)+1 FROM ci_cancel_transmission
  WHERE cancellation_id=NEW.cancellation_id AND primitive_id=NEW.primitive_id)
  THEN RAISE(ABORT,'cancel_ordinal') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission p WHERE p.cancellation_id=NEW.cancellation_id
  AND (p.execution_id!=NEW.execution_id OR p.execution_digest!=NEW.execution_digest OR p.origin!=NEW.origin
   OR p.origin_authority IS NOT NEW.origin_authority OR p.origin_database IS NOT NEW.origin_database
   OR p.run_id IS NOT NEW.run_id OR p.generation IS NOT NEW.generation))
  THEN RAISE(ABORT,'cancel_execution_changed') END;
 SELECT CASE WHEN NEW.ordinal>0 AND NOT EXISTS(SELECT 1 FROM ci_cancel_transmission p
  JOIN ci_cancel_commit k USING(permit_id) WHERE p.permit_id=NEW.initial_permit_id AND p.ordinal=0
   AND p.cancellation_id=NEW.cancellation_id AND p.primitive_id=NEW.primitive_id AND p.exit_id=NEW.exit_id
   AND p.packet_id=NEW.packet_id AND p.packet_digest=NEW.packet_digest AND p.time_required=NEW.time_required)
  THEN RAISE(ABORT,'cancel_initial_binding') END;
END;
CREATE TRIGGER ci_cancel_bytes BEFORE INSERT ON ci_cancel_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission p
  JOIN ci_cancel_commit initial ON initial.permit_id=p.initial_permit_id
  WHERE p.permit_id=NEW.permit_id AND initial.packet_bytes!=NEW.packet_bytes)
  THEN RAISE(ABORT,'cancel_bytes_changed') END;
END;

CREATE TRIGGER ci_issue_u BEFORE UPDATE ON ci_issue BEGIN SELECT RAISE(ABORT,'immutable_issue'); END;

CREATE TRIGGER ci_issue_d BEFORE DELETE ON ci_issue BEGIN SELECT RAISE(ABORT,'immutable_issue'); END;

CREATE TRIGGER ci_cancel_transmission_u BEFORE UPDATE ON ci_cancel_transmission BEGIN SELECT RAISE(ABORT,'immutable_issue'); END;

CREATE TRIGGER ci_cancel_transmission_d BEFORE DELETE ON ci_cancel_transmission BEGIN SELECT RAISE(ABORT,'immutable_issue'); END;

CREATE TRIGGER ci_cancel_commit_u BEFORE UPDATE ON ci_cancel_commit BEGIN SELECT RAISE(ABORT,'immutable_issue'); END;

CREATE TRIGGER ci_cancel_commit_d BEFORE DELETE ON ci_cancel_commit BEGIN SELECT RAISE(ABORT,'immutable_issue'); END;

-- RUN取消覆盖附属候选；与共享签发94表组合，不是生产迁移。
CREATE UNIQUE INDEX cf_cancel_exit ON ci_cancel_transmission(permit_id,exit_id);
CREATE TABLE cf_report (
 report_id TEXT PRIMARY KEY NOT NULL,
 permit_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 worker_report_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK((disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR (disposition='unknown' AND proof='send_uncertain')),
 source_digest TEXT NOT NULL CHECK(length(source_digest)=71 AND substr(source_digest,1,7)='sha256:' AND substr(source_digest,8) NOT GLOB '*[^0-9a-f]*'),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(exit_id,worker_report_id), UNIQUE(report_id,permit_id),
 FOREIGN KEY(permit_id,exit_id) REFERENCES ci_cancel_transmission(permit_id,exit_id)
) STRICT;
CREATE TABLE cf_settlement (
 settlement_id TEXT PRIMARY KEY NOT NULL,
 permit_id TEXT NOT NULL REFERENCES ci_cancel_transmission(permit_id),
 kind TEXT NOT NULL CHECK(kind IN ('never_sent','effect_resolved')),
 report_id TEXT,
 barrier_id TEXT,
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK((kind='effect_resolved' AND report_id IS NULL AND barrier_id IS NULL) OR
  (kind='never_sent' AND ((report_id IS NOT NULL AND barrier_id IS NULL) OR
                        (report_id IS NULL AND barrier_id IS NOT NULL)))),
 FOREIGN KEY(report_id,permit_id) REFERENCES cf_report(report_id,permit_id),
 FOREIGN KEY(barrier_id,permit_id) REFERENCES cf_barrier_coverage(barrier_id,permit_id)
) STRICT;
CREATE TABLE cf_run_item (
 fence_id TEXT NOT NULL,
 permit_id TEXT NOT NULL,
 exit_id TEXT NOT NULL,
 entered_known INTEGER NOT NULL CHECK(entered_known IN (0,1)),
 PRIMARY KEY(fence_id,permit_id), UNIQUE(fence_id,permit_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target(fence_id,exit_id),
 FOREIGN KEY(permit_id,exit_id) REFERENCES ci_cancel_transmission(permit_id,exit_id),
 FOREIGN KEY(fence_id) REFERENCES ce_cut_commit(fence_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cf_barrier_coverage (
 barrier_id TEXT NOT NULL, fence_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK((disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR (disposition='unknown' AND proof='send_uncertain')),
 PRIMARY KEY(barrier_id,permit_id),
 FOREIGN KEY(barrier_id,fence_id,exit_id) REFERENCES ce_barrier_attempt(barrier_id,fence_id,exit_id),
 FOREIGN KEY(fence_id,permit_id,exit_id) REFERENCES cf_run_item(fence_id,permit_id,exit_id),
 FOREIGN KEY(barrier_id) REFERENCES ce_barrier_ack(barrier_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cf_target_coverage (
 fence_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK((disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR (disposition='unknown' AND proof='send_uncertain')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 PRIMARY KEY(fence_id,permit_id),
 FOREIGN KEY(fence_id,permit_id,exit_id) REFERENCES cf_run_item(fence_id,permit_id,exit_id),
 FOREIGN KEY(fence_id,exit_id) REFERENCES ce_target_result(fence_id,exit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW cf_disposition AS
 SELECT p.permit_id,
 CASE WHEN EXISTS(SELECT 1 FROM cf_report r WHERE r.permit_id=p.permit_id AND r.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM cf_barrier_coverage c JOIN ce_barrier_ack a USING(barrier_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM cf_target_coverage c JOIN ce_target_result r USING(fence_id,exit_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight')
  OR EXISTS(SELECT 1 FROM cu_coverage z JOIN cu_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM cf_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cf_barrier_coverage c JOIN ce_barrier_ack a USING(barrier_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cf_target_coverage c JOIN ce_target_result r USING(fence_id,exit_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cu_coverage z JOIN cu_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent' AND NOT EXISTS(SELECT 1 FROM cu_revocation r WHERE r.kind='ack' AND r.object_id=k.barrier_id)) THEN 'not_sent'
 ELSE 'unknown' END disposition FROM ci_cancel_transmission p;
CREATE VIEW cf_open_permit AS
 SELECT p.*,d.disposition FROM ci_cancel_transmission p JOIN cf_disposition d USING(permit_id)
 WHERE NOT EXISTS(SELECT 1 FROM cf_settlement s WHERE s.permit_id=p.permit_id
  AND (s.kind='effect_resolved' OR (s.kind='never_sent' AND d.disposition='not_sent')));
CREATE VIEW cf_expected_item AS
 SELECT s.fence_id,p.permit_id,p.exit_id FROM ce_selector s JOIN cf_open_permit p
 ON (p.origin_authority,p.origin_database,p.run_id)=(s.origin_authority,s.origin_database,s.run_id)
 AND p.generation<=s.generation WHERE p.origin='automation';
DROP VIEW ce_expected_target;
CREATE VIEW ce_expected_target AS
 SELECT DISTINCT s.fence_id,e.exit_id FROM ce_selector s
 JOIN cp_request p ON (p.origin_authority,p.origin_database,p.run_id)=
  (s.origin_authority,s.origin_database,s.run_id) AND p.generation<=s.generation
 JOIN cp_request_device d USING(prep_key) JOIN ce_exit e ON e.device_id=d.device_id
 WHERE NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id)
 UNION SELECT fence_id,exit_id FROM ce_expected_item
 UNION SELECT fence_id,exit_id FROM cf_expected_item;
CREATE TRIGGER cf_settlement_guard BEFORE INSERT ON cf_settlement WHEN NEW.kind='never_sent' BEGIN
 SELECT CASE WHEN (SELECT disposition FROM cf_disposition WHERE permit_id=NEW.permit_id)!='not_sent'
  OR NOT (EXISTS(SELECT 1 FROM cf_report WHERE report_id=NEW.report_id AND permit_id=NEW.permit_id AND disposition='not_sent')
    OR EXISTS(SELECT 1 FROM cf_barrier_coverage c JOIN ce_barrier_ack a USING(barrier_id)
     WHERE c.barrier_id=NEW.barrier_id AND c.permit_id=NEW.permit_id AND c.disposition='not_sent'))
  THEN RAISE(ABORT,'cancel_never_sent_unproven') END;
END;
CREATE TRIGGER cf_cut_guard BEFORE INSERT ON ce_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT permit_id,exit_id FROM cf_expected_item WHERE fence_id=NEW.fence_id
  EXCEPT SELECT permit_id,exit_id FROM cf_run_item WHERE fence_id=NEW.fence_id)
 OR EXISTS(SELECT permit_id,exit_id FROM cf_run_item WHERE fence_id=NEW.fence_id
  EXCEPT SELECT permit_id,exit_id FROM cf_expected_item WHERE fence_id=NEW.fence_id)
  THEN RAISE(ABORT,'cancel_cut_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cf_run_item i JOIN cf_disposition d USING(permit_id)
  WHERE i.fence_id=NEW.fence_id AND i.entered_known!=(d.disposition='in_flight'))
  THEN RAISE(ABORT,'cancel_entered_snapshot') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM cf_run_item WHERE fence_id=NEW.fence_id
  GROUP BY exit_id HAVING count(*)>256) THEN RAISE(ABORT,'cancel_fence_capacity') END;
END;
CREATE TRIGGER cf_ack_guard BEFORE INSERT ON ce_barrier_ack BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM cf_barrier_coverage WHERE barrier_id=NEW.barrier_id)!=
  (SELECT count(*) FROM cf_run_item i JOIN ce_barrier_attempt a USING(fence_id,exit_id) WHERE a.barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'cancel_ack_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cf_barrier_coverage c JOIN cf_run_item i USING(fence_id,exit_id,permit_id)
  WHERE c.barrier_id=NEW.barrier_id AND i.entered_known=1 AND c.disposition!='in_flight')
  THEN RAISE(ABORT,'cancel_ack_downgrade') END;
END;
CREATE TRIGGER cf_result_guard BEFORE INSERT ON ce_target_result BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM cf_target_coverage WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)!=
  (SELECT count(*) FROM cf_run_item WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'cancel_result_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cf_target_coverage c JOIN cf_run_item i USING(fence_id,exit_id,permit_id)
  WHERE c.fence_id=NEW.fence_id AND c.exit_id=NEW.exit_id AND
   ((i.entered_known=1 AND c.disposition!='in_flight') OR (NEW.evidence_kind='supervisor_retired' AND c.disposition='not_sent')))
  THEN RAISE(ABORT,'cancel_result_downgrade') END;
 SELECT CASE WHEN NEW.evidence_kind='worker_ack' AND (
 EXISTS(SELECT permit_id,disposition,proof FROM cf_target_coverage WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id
  EXCEPT SELECT c.permit_id,c.disposition,c.proof FROM cf_barrier_coverage c JOIN ce_result_binding b USING(barrier_id)
  WHERE b.fence_id=NEW.fence_id AND b.exit_id=NEW.exit_id)
 OR EXISTS(SELECT c.permit_id,c.disposition,c.proof FROM cf_barrier_coverage c JOIN ce_result_binding b USING(barrier_id)
  WHERE b.fence_id=NEW.fence_id AND b.exit_id=NEW.exit_id
  EXCEPT SELECT permit_id,disposition,proof FROM cf_target_coverage WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id))
  THEN RAISE(ABORT,'cancel_selected_mismatch') END;
END;
CREATE TRIGGER cf_item_frozen BEFORE INSERT ON cf_run_item
 WHEN EXISTS(SELECT 1 FROM ce_cut_commit WHERE fence_id=NEW.fence_id)
 BEGIN SELECT RAISE(ABORT,'cancel_cut_frozen'); END;
CREATE TRIGGER cf_ack_frozen BEFORE INSERT ON cf_barrier_coverage
 WHEN EXISTS(SELECT 1 FROM ce_barrier_ack WHERE barrier_id=NEW.barrier_id)
 BEGIN SELECT RAISE(ABORT,'cancel_ack_frozen'); END;
CREATE TRIGGER cf_result_frozen BEFORE INSERT ON cf_target_coverage
 WHEN EXISTS(SELECT 1 FROM ce_target_result WHERE fence_id=NEW.fence_id AND exit_id=NEW.exit_id)
 BEGIN SELECT RAISE(ABORT,'cancel_result_frozen'); END;

CREATE TRIGGER cf_report_u BEFORE UPDATE ON cf_report BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_report_d BEFORE DELETE ON cf_report BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_settlement_u BEFORE UPDATE ON cf_settlement BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_settlement_d BEFORE DELETE ON cf_settlement BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_run_item_u BEFORE UPDATE ON cf_run_item BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_run_item_d BEFORE DELETE ON cf_run_item BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_barrier_coverage_u BEFORE UPDATE ON cf_barrier_coverage BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_barrier_coverage_d BEFORE DELETE ON cf_barrier_coverage BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_target_coverage_u BEFORE UPDATE ON cf_target_coverage BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_target_coverage_d BEFORE DELETE ON cf_target_coverage BEGIN SELECT RAISE(ABORT,'immutable_cancel_fence'); END;

CREATE TRIGGER cf_report_cut BEFORE INSERT ON cf_report WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;

CREATE TRIGGER cf_settlement_cut BEFORE INSERT ON cf_settlement WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;

CREATE TRIGGER cf_barrier_coverage_cut BEFORE INSERT ON cf_barrier_coverage WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;

CREATE TRIGGER cf_target_coverage_cut BEFORE INSERT ON cf_target_coverage WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;

CREATE TRIGGER cf_ack_cut BEFORE INSERT ON ce_barrier_ack WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;

-- 取消资源核销候选；与99表组合，所有BODY权威仍由可信提供者验证。
CREATE TABLE cx_closure (
 cancellation_id TEXT NOT NULL,
 operation_revision TEXT NOT NULL,
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_validation(validation_id),
 closure_digest TEXT NOT NULL,
 closure_body BLOB NOT NULL CHECK(length(closure_body)>0),
 UNIQUE(cancellation_id,validation_id),
 FOREIGN KEY(cancellation_id,operation_revision) REFERENCES cv_cancel_revision(cancellation_id,revision)
) STRICT;
CREATE TABLE cx_settlement (
 settlement_id TEXT PRIMARY KEY NOT NULL REFERENCES cf_settlement(settlement_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 settlement_digest TEXT NOT NULL
) STRICT;
CREATE TABLE cx_release_cancel (
 release_id TEXT NOT NULL REFERENCES cr_release(release_id),
 cancellation_id TEXT NOT NULL,
 closure_validation_id TEXT NOT NULL,
 PRIMARY KEY(release_id,cancellation_id),
 FOREIGN KEY(cancellation_id,closure_validation_id) REFERENCES cx_closure(cancellation_id,validation_id)
) STRICT;
CREATE TABLE cx_release_member (
 release_id TEXT NOT NULL REFERENCES cr_release(release_id),
 permit_id TEXT NOT NULL REFERENCES ci_cancel_transmission(permit_id),
 settlement_id TEXT NOT NULL REFERENCES cx_settlement(settlement_id),
 PRIMARY KEY(release_id,permit_id)
) STRICT;
DROP VIEW cr_release_validation;
CREATE VIEW cr_release_validation AS
 SELECT release_id,validation_id FROM cr_release
 UNION SELECT release_id,closure_validation_id FROM cr_release_attempt
 UNION SELECT m.release_id,s.validation_id FROM cr_release_member m JOIN cr_settlement_validation s USING(settlement_id)
 UNION SELECT release_id,closure_validation_id FROM cx_release_cancel
 UNION SELECT m.release_id,s.validation_id FROM cx_release_member m JOIN cx_settlement s USING(settlement_id);
DROP VIEW cr_invalid_release;
CREATE VIEW cr_invalid_release AS
 SELECT r.release_id FROM cr_release r JOIN cr_release_commit k USING(release_id)
 WHERE EXISTS(SELECT 1 FROM cr_release_validation p WHERE p.release_id=r.release_id
  AND NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=p.validation_id))
 OR EXISTS(SELECT 1 FROM cr_release_member m JOIN cr_settlement_validation sv USING(settlement_id)
  JOIN ce_settlement s USING(settlement_id) JOIN ce_current_disposition d ON d.permit_id=m.permit_id
  WHERE m.release_id=r.release_id AND (NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=sv.validation_id)
   OR (s.kind='never_sent' AND d.disposition='in_flight')))
 OR EXISTS(SELECT 1 FROM cx_release_member m JOIN cf_settlement s USING(settlement_id)
  JOIN cf_disposition d ON d.permit_id=m.permit_id WHERE m.release_id=r.release_id
   AND s.kind='never_sent' AND d.disposition='in_flight');
CREATE TRIGGER cx_closure_guard BEFORE INSERT ON cx_closure BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel c JOIN cv_cancel_revision r USING(cancellation_id)
  JOIN cm_commit k ON k.command_id=r.command_id AND k.revision=r.state_revision
  JOIN ce_command cmd ON cmd.command_id=c.command_id JOIN cr_claim policy ON policy.command_id=c.command_id
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE c.cancellation_id=NEW.cancellation_id AND r.revision=NEW.operation_revision AND r.future_writes='closed'
   AND v.command_id=c.command_id AND v.device_id=cmd.device_id AND v.purpose='close'
   AND v.subject_id=c.cancellation_id AND v.subject_digest=NEW.closure_digest AND v.policy_ref=policy.release_policy_ref)
  THEN RAISE(ABORT,'cancel_all_closure_binding') END;
END;
CREATE TRIGGER cx_settlement_guard BEFORE INSERT ON cx_settlement BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cf_settlement s JOIN ci_cancel_transmission p USING(permit_id)
  JOIN cv_cancel c USING(cancellation_id) JOIN ce_command cmd USING(command_id) JOIN cr_claim policy USING(command_id)
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE s.settlement_id=NEW.settlement_id AND v.command_id=c.command_id AND v.device_id=cmd.device_id
   AND v.purpose='settlement' AND v.subject_id=s.settlement_id AND v.subject_digest=NEW.settlement_digest
   AND v.policy_ref=policy.release_policy_ref) THEN RAISE(ABORT,'cancel_settlement_binding') END;
END;
CREATE TRIGGER cx_release_guard BEFORE INSERT ON cr_release_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT c.cancellation_id FROM cv_cancel c JOIN cr_release r USING(command_id)
  WHERE r.release_id=NEW.release_id EXCEPT SELECT cancellation_id FROM cx_release_cancel WHERE release_id=NEW.release_id)
 OR EXISTS(SELECT cancellation_id FROM cx_release_cancel WHERE release_id=NEW.release_id
  EXCEPT SELECT c.cancellation_id FROM cv_cancel c JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id)
  THEN RAISE(ABORT,'cancel_release_closure_set') END;
 SELECT CASE WHEN EXISTS(SELECT p.permit_id FROM ci_cancel_transmission p JOIN cv_cancel c USING(cancellation_id)
  JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id
  EXCEPT SELECT permit_id FROM cx_release_member WHERE release_id=NEW.release_id)
 OR EXISTS(SELECT permit_id FROM cx_release_member WHERE release_id=NEW.release_id
  EXCEPT SELECT p.permit_id FROM ci_cancel_transmission p JOIN cv_cancel c USING(cancellation_id)
  JOIN cr_release r USING(command_id) WHERE r.release_id=NEW.release_id)
  THEN RAISE(ABORT,'cancel_release_permit_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cx_release_cancel x WHERE x.release_id=NEW.release_id
  AND NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=x.closure_validation_id))
  THEN RAISE(ABORT,'cancel_closure_revoked') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cx_release_member m JOIN cf_settlement s USING(settlement_id)
  JOIN cx_settlement sv USING(settlement_id) JOIN cf_disposition d ON d.permit_id=m.permit_id
  JOIN cr_release r USING(release_id) WHERE m.release_id=NEW.release_id AND
   (s.permit_id!=m.permit_id OR NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=sv.validation_id)
    OR (s.kind='never_sent' AND d.disposition!='not_sent') OR (r.kind='never_sent' AND s.kind!='never_sent')))
  THEN RAISE(ABORT,'cancel_release_member_unproven') END;
END;
CREATE TRIGGER cx_report_invalidation AFTER INSERT ON cf_report WHEN NEW.disposition='in_flight' BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT x.release_id,'cancel_report',NEW.report_id,NULL FROM cr_invalid_release x
 JOIN cx_release_member m USING(release_id) WHERE m.permit_id=NEW.permit_id;
END;
CREATE TRIGGER cx_ack_invalidation AFTER INSERT ON ce_barrier_ack BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT x.release_id,'barrier_ack',NEW.barrier_id,NULL FROM cr_invalid_release x
 JOIN cx_release_member m USING(release_id) JOIN cf_barrier_coverage b USING(permit_id)
 WHERE b.barrier_id=NEW.barrier_id AND b.disposition='in_flight';
END;
CREATE TRIGGER cx_target_invalidation AFTER INSERT ON ce_target_result BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT x.release_id,'target_result',NEW.fence_id,NEW.exit_id FROM cr_invalid_release x
 JOIN cx_release_member m USING(release_id) JOIN cf_target_coverage b USING(permit_id)
 WHERE b.fence_id=NEW.fence_id AND b.exit_id=NEW.exit_id AND b.disposition='in_flight';
END;

CREATE TRIGGER cx_closure_u BEFORE UPDATE ON cx_closure BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;

CREATE TRIGGER cx_closure_d BEFORE DELETE ON cx_closure BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;

CREATE TRIGGER cx_settlement_u BEFORE UPDATE ON cx_settlement BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;

CREATE TRIGGER cx_settlement_d BEFORE DELETE ON cx_settlement BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;

CREATE TRIGGER cx_release_cancel_u BEFORE UPDATE ON cx_release_cancel BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;

CREATE TRIGGER cx_release_cancel_d BEFORE DELETE ON cx_release_cancel BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;

CREATE TRIGGER cx_release_member_u BEFORE UPDATE ON cx_release_member BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;

CREATE TRIGGER cx_release_member_d BEFORE DELETE ON cx_release_member BEGIN SELECT RAISE(ABORT,'immutable_cancel_resource'); END;

CREATE TRIGGER cx_release_cancel_frozen BEFORE INSERT ON cx_release_cancel WHEN EXISTS(SELECT 1 FROM cr_release_commit WHERE release_id=NEW.release_id) BEGIN SELECT RAISE(ABORT,'release_frozen'); END;

CREATE TRIGGER cx_release_member_frozen BEFORE INSERT ON cx_release_member WHEN EXISTS(SELECT 1 FROM cr_release_commit WHERE release_id=NEW.release_id) BEGIN SELECT RAISE(ABORT,'release_frozen'); END;

-- ordinary/all关闭、编码准备与原ACK关联候选。由生成器组合，非生产迁移。
CREATE TABLE cc_cut (
 prepare_cut_id TEXT NOT NULL UNIQUE REFERENCES pd_cut(cut_id) DEFERRABLE INITIALLY DEFERRED,
 cut_id TEXT PRIMARY KEY NOT NULL,
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel_commit(cancellation_id),
 stage TEXT NOT NULL CHECK(stage IN ('ordinary','all')),
 previous_cut_id TEXT REFERENCES cc_cut(cut_id),
 issued_revision TEXT NOT NULL CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*'),
 cut_digest TEXT NOT NULL,
 cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 UNIQUE(cancellation_id,stage), UNIQUE(cut_id,cancellation_id),
 CHECK((stage='ordinary' AND previous_cut_id IS NULL) OR (stage='all' AND previous_cut_id IS NOT NULL)),
 FOREIGN KEY(cut_id) REFERENCES cc_cut_commit(cut_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cc_target (
 cut_id TEXT NOT NULL REFERENCES cc_cut(cut_id), exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 target_digest TEXT NOT NULL, target_body BLOB NOT NULL CHECK(length(target_body)>0),
 PRIMARY KEY(cut_id,exit_id)
) STRICT;
CREATE TABLE cc_member (
 cut_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL REFERENCES ci_issue(permit_id),
 entered_known INTEGER NOT NULL CHECK(entered_known IN (0,1)),
 PRIMARY KEY(cut_id,permit_id), UNIQUE(cut_id,exit_id,permit_id),
 FOREIGN KEY(cut_id,exit_id) REFERENCES cc_target(cut_id,exit_id)
) STRICT;
CREATE TABLE cc_cut_commit (
 cut_id TEXT PRIMARY KEY NOT NULL REFERENCES cc_cut(cut_id),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cc_attempt (
 barrier_id TEXT PRIMARY KEY NOT NULL, cut_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 2147483647),
 previous_barrier_id TEXT,
 request_digest TEXT NOT NULL, request_body BLOB NOT NULL CHECK(length(request_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 UNIQUE(cut_id,exit_id,ordinal), UNIQUE(barrier_id,cut_id,exit_id),
 CHECK((ordinal=1 AND previous_barrier_id IS NULL) OR (ordinal>1 AND previous_barrier_id IS NOT NULL)),
 FOREIGN KEY(cut_id,exit_id) REFERENCES cc_target(cut_id,exit_id),
 FOREIGN KEY(previous_barrier_id,cut_id,exit_id) REFERENCES cc_attempt(barrier_id,cut_id,exit_id)
) STRICT;
CREATE TABLE cc_failure (
 barrier_id TEXT PRIMARY KEY NOT NULL REFERENCES cc_attempt(barrier_id),
 reason TEXT NOT NULL CHECK(reason IN ('cache_miss','deadline_elapsed','channel_lost')),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cc_coverage (
 barrier_id TEXT NOT NULL, cut_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK((disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
  (disposition='in_flight' AND proof='transport_entered') OR (disposition='unknown' AND proof='send_uncertain')),
 PRIMARY KEY(barrier_id,permit_id),
 FOREIGN KEY(barrier_id,cut_id,exit_id) REFERENCES cc_attempt(barrier_id,cut_id,exit_id),
 FOREIGN KEY(cut_id,exit_id,permit_id) REFERENCES cc_member(cut_id,exit_id,permit_id),
 FOREIGN KEY(barrier_id) REFERENCES cc_ack(barrier_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cc_ack (
 barrier_id TEXT PRIMARY KEY NOT NULL REFERENCES cc_attempt(barrier_id),
 ack_digest TEXT NOT NULL, ack_body BLOB NOT NULL CHECK(length(ack_body)>0),
 effective_tick TEXT NOT NULL CHECK(length(effective_tick)=20 AND effective_tick NOT GLOB '*[^0-9]*'),
 gate_io_seq TEXT NOT NULL CHECK(length(gate_io_seq)=20 AND gate_io_seq NOT GLOB '*[^0-9]*'),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cc_selection (
 closure_id TEXT NOT NULL, cut_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('worker_ack','supervisor_retired')),
 barrier_id TEXT REFERENCES cc_ack(barrier_id), retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(closure_id,exit_id),
 CHECK((kind='worker_ack' AND barrier_id IS NOT NULL AND retirement_exit_id IS NULL) OR
  (kind='supervisor_retired' AND barrier_id IS NULL AND retirement_exit_id IS exit_id)),
 FOREIGN KEY(cut_id,exit_id) REFERENCES cc_target(cut_id,exit_id),
 FOREIGN KEY(closure_id,cut_id) REFERENCES cc_closure(closure_id,cut_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(barrier_id,cut_id,exit_id) REFERENCES cc_attempt(barrier_id,cut_id,exit_id)
) STRICT;
CREATE TABLE cc_closure (
 prepare_closure_id TEXT NOT NULL REFERENCES pd_closure_commit(closure_id),
 closure_id TEXT PRIMARY KEY NOT NULL, cut_id TEXT NOT NULL REFERENCES cc_cut_commit(cut_id),
 closure_digest TEXT NOT NULL, closure_body BLOB NOT NULL CHECK(length(closure_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0), UNIQUE(closure_id,cut_id)
) STRICT;
CREATE TABLE cc_revocation (
 closure_id TEXT PRIMARY KEY NOT NULL REFERENCES cc_closure(closure_id),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cc_prepare (
 prepare_id TEXT PRIMARY KEY NOT NULL, cancellation_id TEXT NOT NULL REFERENCES cv_cancel_commit(cancellation_id),
 ordinary_closure_id TEXT NOT NULL REFERENCES cc_closure(closure_id),
 execution_id TEXT NOT NULL, execution_digest TEXT NOT NULL, primitive_id TEXT NOT NULL,
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 prepare_body BLOB NOT NULL CHECK(length(prepare_body)>0), validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0), outbox_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0), UNIQUE(cancellation_id,primitive_id),
 FOREIGN KEY(prepare_id) REFERENCES ep_request_commit(prepare_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cc_cut_prepare (
 cut_id TEXT NOT NULL, exit_id TEXT NOT NULL, prepare_id TEXT NOT NULL REFERENCES cc_prepare(prepare_id),
 PRIMARY KEY(cut_id,prepare_id), UNIQUE(cut_id,exit_id,prepare_id),
 FOREIGN KEY(cut_id,exit_id) REFERENCES cc_target(cut_id,exit_id)
) STRICT;
CREATE TABLE cc_ack_prepare (
 barrier_id TEXT NOT NULL, cut_id TEXT NOT NULL, exit_id TEXT NOT NULL, prepare_id TEXT NOT NULL,
 PRIMARY KEY(barrier_id,prepare_id),
 FOREIGN KEY(barrier_id,cut_id,exit_id) REFERENCES cc_attempt(barrier_id,cut_id,exit_id),
 FOREIGN KEY(cut_id,exit_id,prepare_id) REFERENCES cc_cut_prepare(cut_id,exit_id,prepare_id),
 FOREIGN KEY(barrier_id) REFERENCES cc_ack(barrier_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cc_packet (
 packet_id TEXT PRIMARY KEY NOT NULL, prepare_id TEXT NOT NULL UNIQUE REFERENCES cc_prepare(prepare_id),
 packet_digest TEXT NOT NULL, packet_bytes BLOB NOT NULL CHECK(length(packet_bytes)>0),
 packet_body BLOB NOT NULL CHECK(length(packet_body)>0), validation_body BLOB NOT NULL CHECK(length(validation_body)>0)
) STRICT;
CREATE TABLE cc_dispatch (
 permit_id TEXT PRIMARY KEY NOT NULL REFERENCES ci_cancel_transmission(permit_id),
 packet_id TEXT NOT NULL REFERENCES cc_packet(packet_id),
 FOREIGN KEY(permit_id) REFERENCES ci_cancel_commit(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW pd_base_cc_valid_closure AS
 SELECT c.* FROM cc_closure c WHERE NOT EXISTS(SELECT 1 FROM cc_revocation r WHERE r.closure_id=c.closure_id);
CREATE VIEW cc_expected_member AS
 SELECT c.cut_id,p.exit_id,p.permit_id FROM cc_cut c JOIN cv_cancel_permit v USING(cancellation_id)
 JOIN ce_permit p USING(permit_id)
 UNION SELECT c.cut_id,p.exit_id,p.permit_id FROM cc_cut c JOIN ci_cancel_transmission p USING(cancellation_id)
 WHERE c.stage='all';
CREATE VIEW cc_expected_target AS
 SELECT c.cut_id,t.exit_id FROM cc_cut c JOIN cv_cancel_target t USING(cancellation_id)
 UNION SELECT c.cut_id,e.exit_id FROM cc_cut c JOIN cv_cancel v USING(cancellation_id)
 JOIN ce_command cmd USING(command_id) JOIN ce_exit e USING(device_id) WHERE c.stage='all';
CREATE VIEW cc_expected_prepare AS
 SELECT c.cut_id,p.exit_id,p.prepare_id FROM cc_cut c JOIN cc_prepare p USING(cancellation_id) WHERE c.stage='all';
CREATE TRIGGER cc_cut_guard BEFORE INSERT ON cc_cut BEGIN
 SELECT CASE WHEN NEW.stage='ordinary' AND NOT EXISTS(SELECT 1 FROM cv_cancel
  WHERE cancellation_id=NEW.cancellation_id AND cut_revision=NEW.issued_revision AND cut_digest=NEW.cut_digest)
  THEN RAISE(ABORT,'ordinary_cut_binding') END;
 SELECT CASE WHEN NEW.stage='all' AND (NEW.issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  OR NOT EXISTS(SELECT 1 FROM cc_cut c JOIN cc_cut_commit k USING(cut_id)
   WHERE c.cut_id=NEW.previous_cut_id AND c.cancellation_id=NEW.cancellation_id AND c.stage='ordinary'))
  THEN RAISE(ABORT,'all_cut_binding') END;
END;
CREATE TRIGGER cc_cut_seal BEFORE INSERT ON cc_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_cut WHERE cut_id=NEW.cut_id AND stage='all'
  AND issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue))
  THEN RAISE(ABORT,'all_cut_changed') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM cc_expected_target WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id FROM cc_target WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT exit_id FROM cc_target WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id FROM cc_expected_target WHERE cut_id=NEW.cut_id) THEN RAISE(ABORT,'closure_target_set') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id,permit_id FROM cc_expected_member WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id,permit_id FROM cc_member WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT exit_id,permit_id FROM cc_member WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id,permit_id FROM cc_expected_member WHERE cut_id=NEW.cut_id) THEN RAISE(ABORT,'closure_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id,prepare_id FROM cc_expected_prepare WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id,prepare_id FROM cc_cut_prepare WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT exit_id,prepare_id FROM cc_cut_prepare WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id,prepare_id FROM cc_expected_prepare WHERE cut_id=NEW.cut_id) THEN RAISE(ABORT,'closure_prepare_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_member m JOIN ci_issue i USING(permit_id)
  LEFT JOIN ce_current_disposition o USING(permit_id) LEFT JOIN cf_disposition p USING(permit_id)
  WHERE m.cut_id=NEW.cut_id AND m.entered_known!=(coalesce(o.disposition,p.disposition)='in_flight'))
  THEN RAISE(ABORT,'closure_entered_snapshot') END;
 SELECT CASE WHEN EXISTS(SELECT m.exit_id,i.kind FROM cc_member m JOIN ci_issue i USING(permit_id)
  WHERE m.cut_id=NEW.cut_id GROUP BY m.exit_id,i.kind HAVING count(*)>256)
  THEN RAISE(ABORT,'closure_capacity') END;
END;
CREATE TRIGGER cc_attempt_guard BEFORE INSERT ON cc_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_cut_commit WHERE cut_id=NEW.cut_id)
  OR EXISTS(SELECT 1 FROM cc_valid_closure WHERE cut_id=NEW.cut_id)
  OR EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id) THEN RAISE(ABORT,'closure_attempt_closed') END;
 SELECT CASE WHEN NEW.ordinal!=(SELECT coalesce(max(ordinal),0)+1 FROM cc_attempt WHERE cut_id=NEW.cut_id AND exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'closure_attempt_ordinal') END;
 SELECT CASE WHEN NEW.ordinal>1 AND NOT EXISTS(SELECT 1 FROM cc_attempt a JOIN cc_failure f USING(barrier_id)
  WHERE a.barrier_id=NEW.previous_barrier_id AND a.cut_id=NEW.cut_id AND a.exit_id=NEW.exit_id
   AND a.ordinal=NEW.ordinal-1 AND f.reason IN ('cache_miss','deadline_elapsed')) THEN RAISE(ABORT,'closure_retry_basis') END;
END;
CREATE TRIGGER cc_failure_guard BEFORE INSERT ON cc_failure WHEN EXISTS(SELECT 1 FROM cc_ack WHERE barrier_id=NEW.barrier_id)
 BEGIN SELECT RAISE(ABORT,'closure_ack_stored'); END;
CREATE TRIGGER cc_ack_guard BEFORE INSERT ON cc_ack BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM cc_ack_prepare WHERE barrier_id=NEW.barrier_id)!=
  (SELECT count(*) FROM cc_cut_prepare m JOIN cc_attempt a USING(cut_id,exit_id) WHERE a.barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'closure_ack_prepare_incomplete') END;
 SELECT CASE WHEN (SELECT count(*) FROM cc_coverage WHERE barrier_id=NEW.barrier_id)!=
  (SELECT count(*) FROM cc_member m JOIN cc_attempt a USING(cut_id,exit_id) WHERE a.barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'closure_ack_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_coverage c JOIN cc_member m USING(cut_id,exit_id,permit_id)
  WHERE c.barrier_id=NEW.barrier_id AND m.entered_known=1 AND c.disposition!='in_flight')
  THEN RAISE(ABORT,'closure_ack_downgrade') END;
END;
CREATE TRIGGER cc_selection_guard BEFORE INSERT ON cc_selection BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_closure WHERE closure_id=NEW.closure_id)
  THEN RAISE(ABORT,'closure_selection_frozen') END;
 SELECT CASE WHEN NEW.kind='worker_ack' AND NOT EXISTS(SELECT 1 FROM cc_attempt a JOIN cc_ack k USING(barrier_id)
  WHERE a.barrier_id=NEW.barrier_id AND a.cut_id=NEW.cut_id AND a.exit_id=NEW.exit_id
   AND NOT EXISTS(SELECT 1 FROM cc_failure WHERE barrier_id=a.barrier_id)
   AND a.ordinal=(SELECT max(ordinal) FROM cc_attempt WHERE cut_id=a.cut_id AND exit_id=a.exit_id))
  THEN RAISE(ABORT,'closure_ack_not_current') END;
END;
CREATE TRIGGER cc_closure_guard BEFORE INSERT ON cc_closure BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_valid_closure WHERE cut_id=NEW.cut_id)
  THEN RAISE(ABORT,'closure_already_valid') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM cc_target WHERE cut_id=NEW.cut_id
  EXCEPT SELECT exit_id FROM cc_selection WHERE closure_id=NEW.closure_id AND cut_id=NEW.cut_id)
  THEN RAISE(ABORT,'closure_targets_unresolved') END;
END;
CREATE TRIGGER cc_prepare_guard BEFORE INSERT ON cc_prepare BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_valid_closure h JOIN cc_cut t USING(cut_id)
  JOIN cv_cancel c USING(cancellation_id) JOIN ce_command cmd USING(command_id) JOIN ce_exit e USING(device_id)
  WHERE h.closure_id=NEW.ordinary_closure_id AND t.stage='ordinary' AND c.cancellation_id=NEW.cancellation_id
   AND c.mode='cooperative' AND e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'cancel_prepare_closure') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_cut WHERE cancellation_id=NEW.cancellation_id AND stage='all')
  OR EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id)
  OR EXISTS(SELECT 1 FROM cv_cancel_current WHERE cancellation_id=NEW.cancellation_id AND state!='requested')
  THEN RAISE(ABORT,'cancel_prepare_closed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_prepare WHERE cancellation_id=NEW.cancellation_id
  AND (execution_id!=NEW.execution_id OR execution_digest!=NEW.execution_digest))
  THEN RAISE(ABORT,'cancel_prepare_execution_changed') END;
END;
CREATE TRIGGER cc_packet_guard BEFORE INSERT ON cc_packet BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_prepare p JOIN cc_cut c USING(cancellation_id)
  WHERE p.prepare_id=NEW.prepare_id AND c.stage='all') THEN RAISE(ABORT,'cancel_packet_closed') END;
END;
CREATE TRIGGER cc_dispatch_guard BEFORE INSERT ON ci_cancel_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_dispatch d JOIN cc_packet b USING(packet_id)
  JOIN cc_prepare p USING(prepare_id) JOIN cc_valid_closure h ON h.closure_id=p.ordinary_closure_id
  JOIN ci_cancel_transmission t ON t.permit_id=d.permit_id
  WHERE d.permit_id=NEW.permit_id AND t.cancellation_id=p.cancellation_id AND t.execution_id=p.execution_id
   AND t.execution_digest=p.execution_digest AND t.primitive_id=p.primitive_id AND t.exit_id=p.exit_id
   AND t.packet_id=b.packet_id AND t.packet_digest=b.packet_digest AND NEW.packet_bytes=b.packet_bytes)
  THEN RAISE(ABORT,'cancel_dispatch_source') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cc_cut c USING(cancellation_id)
  WHERE t.permit_id=NEW.permit_id AND c.stage='all') THEN RAISE(ABORT,'cancel_issuance_closed') END;
END;
CREATE TRIGGER cc_revision_guard BEFORE INSERT ON cv_cancel_revision WHEN NEW.future_writes='closed' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_valid_closure h JOIN cc_cut t USING(cut_id)
  WHERE h.closure_id=NEW.closure_id AND t.cancellation_id=NEW.cancellation_id AND t.stage='all')
  THEN RAISE(ABORT,'public_all_closure_required') END;
END;
CREATE TRIGGER cc_resource_guard BEFORE INSERT ON cx_closure BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel_revision r JOIN cc_valid_closure h ON h.closure_id=r.closure_id
  WHERE r.cancellation_id=NEW.cancellation_id AND r.revision=NEW.operation_revision AND h.closure_digest=NEW.closure_digest)
  THEN RAISE(ABORT,'resource_all_closure_required') END;
END;
CREATE TRIGGER cc_revoke AFTER INSERT ON cc_revocation BEGIN
 INSERT OR IGNORE INTO cr_validation_revocation
 SELECT x.validation_id,NEW.reason_body,NEW.audit_body FROM cx_closure x JOIN cv_cancel_revision r
  ON r.cancellation_id=x.cancellation_id AND r.revision=x.operation_revision WHERE r.closure_id=NEW.closure_id;
END;

CREATE TRIGGER cc_ack_invalidation AFTER INSERT ON cc_ack BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT r.release_id,'cancel_closure_ack',NEW.barrier_id,NULL FROM cr_invalid_release r
 JOIN (SELECT release_id,permit_id FROM cr_release_member UNION SELECT release_id,permit_id FROM cx_release_member) m USING(release_id)
 JOIN cc_coverage c USING(permit_id) WHERE c.barrier_id=NEW.barrier_id AND c.disposition='in_flight';
END;
DROP VIEW cv_current;
CREATE VIEW cv_current AS SELECT p.* FROM cv_history p JOIN cm_current s USING(command_id,revision)
 WHERE NOT EXISTS(SELECT 1 FROM cv_cancel_revision r JOIN cc_revocation v USING(closure_id)
  WHERE r.cancellation_id=p.cancellation_id AND r.revision=p.cancellation_revision);

CREATE TRIGGER cc_cut_u BEFORE UPDATE ON cc_cut BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_cut_d BEFORE DELETE ON cc_cut BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_target_u BEFORE UPDATE ON cc_target BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_target_d BEFORE DELETE ON cc_target BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_member_u BEFORE UPDATE ON cc_member BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_member_d BEFORE DELETE ON cc_member BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_cut_commit_u BEFORE UPDATE ON cc_cut_commit BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_cut_commit_d BEFORE DELETE ON cc_cut_commit BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_attempt_u BEFORE UPDATE ON cc_attempt BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_attempt_d BEFORE DELETE ON cc_attempt BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_failure_u BEFORE UPDATE ON cc_failure BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_failure_d BEFORE DELETE ON cc_failure BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_coverage_u BEFORE UPDATE ON cc_coverage BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_coverage_d BEFORE DELETE ON cc_coverage BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_ack_u BEFORE UPDATE ON cc_ack BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_ack_d BEFORE DELETE ON cc_ack BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_selection_u BEFORE UPDATE ON cc_selection BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_selection_d BEFORE DELETE ON cc_selection BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_closure_u BEFORE UPDATE ON cc_closure BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_closure_d BEFORE DELETE ON cc_closure BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_revocation_u BEFORE UPDATE ON cc_revocation BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_revocation_d BEFORE DELETE ON cc_revocation BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_prepare_u BEFORE UPDATE ON cc_prepare BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_prepare_d BEFORE DELETE ON cc_prepare BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_cut_prepare_u BEFORE UPDATE ON cc_cut_prepare BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_cut_prepare_d BEFORE DELETE ON cc_cut_prepare BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_ack_prepare_u BEFORE UPDATE ON cc_ack_prepare BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_ack_prepare_d BEFORE DELETE ON cc_ack_prepare BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_packet_u BEFORE UPDATE ON cc_packet BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_packet_d BEFORE DELETE ON cc_packet BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_dispatch_u BEFORE UPDATE ON cc_dispatch BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_dispatch_d BEFORE DELETE ON cc_dispatch BEGIN SELECT RAISE(ABORT,'immutable_cancel_closure'); END;

CREATE TRIGGER cc_target_frozen BEFORE INSERT ON cc_target WHEN EXISTS(SELECT 1 FROM cc_cut_commit WHERE cut_id=NEW.cut_id) BEGIN SELECT RAISE(ABORT,'closure_cut_frozen'); END;

CREATE TRIGGER cc_member_frozen BEFORE INSERT ON cc_member WHEN EXISTS(SELECT 1 FROM cc_cut_commit WHERE cut_id=NEW.cut_id) BEGIN SELECT RAISE(ABORT,'closure_cut_frozen'); END;

CREATE TRIGGER cc_cut_prepare_frozen BEFORE INSERT ON cc_cut_prepare WHEN EXISTS(SELECT 1 FROM cc_cut_commit WHERE cut_id=NEW.cut_id) BEGIN SELECT RAISE(ABORT,'closure_cut_frozen'); END;

CREATE TRIGGER cc_coverage_frozen BEFORE INSERT ON cc_coverage WHEN EXISTS(SELECT 1 FROM cc_ack WHERE barrier_id=NEW.barrier_id) BEGIN SELECT RAISE(ABORT,'closure_ack_frozen'); END;

CREATE TRIGGER cc_ack_prepare_frozen BEFORE INSERT ON cc_ack_prepare WHEN EXISTS(SELECT 1 FROM cc_ack WHERE barrier_id=NEW.barrier_id) BEGIN SELECT RAISE(ABORT,'closure_ack_frozen'); END;

CREATE TRIGGER cc_ack_pending_run BEFORE INSERT ON cc_ack WHEN EXISTS(SELECT 1 FROM ce_pending_cut) BEGIN SELECT RAISE(ABORT,'pending_cut'); END;

-- 取消动作图与完成原件候选。须经生成器与119表组合；不是生产迁移。
CREATE TABLE cg_plan (
 execution_id TEXT PRIMARY KEY NOT NULL,
 cancellation_id TEXT NOT NULL UNIQUE REFERENCES cv_cancel_commit(cancellation_id),
 ordinary_closure_id TEXT NOT NULL REFERENCES cc_closure(closure_id),
 execution_digest TEXT NOT NULL,
 policy_ref_body BLOB NOT NULL CHECK(length(policy_ref_body)>0),
 protected_hold_ref_body BLOB NOT NULL CHECK(length(protected_hold_ref_body)>0),
 protected_hold_id TEXT NOT NULL UNIQUE REFERENCES cr_hold(hold_id) DEFERRABLE INITIALLY DEFERRED,
 protected_hold_digest TEXT NOT NULL,
 resource_count INTEGER NOT NULL CHECK(resource_count BETWEEN 1 AND 256),
 primitive_count INTEGER NOT NULL CHECK(primitive_count BETWEEN 1 AND 256),
 dependency_count INTEGER NOT NULL CHECK(dependency_count BETWEEN 0 AND 32640),
 plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(execution_id) REFERENCES cg_plan_commit(execution_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cg_resource (
 execution_id TEXT NOT NULL REFERENCES cg_plan(execution_id), resource_key TEXT NOT NULL,
 PRIMARY KEY(execution_id,resource_key)
) STRICT;
CREATE TABLE cg_primitive (
 execution_id TEXT NOT NULL REFERENCES cg_plan(execution_id), primitive_id TEXT NOT NULL,
 position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 256),
 action_ref_body BLOB NOT NULL CHECK(length(action_ref_body)>0),
 parameters_schema_ref_body BLOB NOT NULL CHECK(length(parameters_schema_ref_body)>0),
 parameters_body BLOB NOT NULL CHECK(length(parameters_body)>0),
 completion_policy_ref_body BLOB NOT NULL CHECK(length(completion_policy_ref_body)>0),
 PRIMARY KEY(execution_id,primitive_id), UNIQUE(execution_id,position)
) STRICT;
CREATE TABLE cg_dependency (
 execution_id TEXT NOT NULL, primitive_id TEXT NOT NULL, predecessor_id TEXT NOT NULL,
 PRIMARY KEY(execution_id,primitive_id,predecessor_id),
 FOREIGN KEY(execution_id,primitive_id) REFERENCES cg_primitive(execution_id,primitive_id),
 FOREIGN KEY(execution_id,predecessor_id) REFERENCES cg_primitive(execution_id,primitive_id)
) STRICT;
CREATE TABLE cg_plan_commit (
 execution_id TEXT PRIMARY KEY NOT NULL REFERENCES cg_plan(execution_id),
 provider_ref_body BLOB NOT NULL CHECK(length(provider_ref_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cg_result (
 result_id TEXT PRIMARY KEY NOT NULL, execution_id TEXT NOT NULL, primitive_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('succeeded','failed','unknown')),
 evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('protocol_effect','verified_safe_state','definite_failure','indeterminate')),
 evidence_digest TEXT NOT NULL, evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),
 completion_policy_ref_body BLOB NOT NULL CHECK(length(completion_policy_ref_body)>0),
 issued_revision TEXT NOT NULL CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*'),
 UNIQUE(execution_id,primitive_id), UNIQUE(result_id,execution_id,primitive_id),
 CHECK((disposition='succeeded' AND evidence_kind IN ('protocol_effect','verified_safe_state')) OR
  (disposition='failed' AND evidence_kind='definite_failure') OR (disposition='unknown' AND evidence_kind='indeterminate')),
 FOREIGN KEY(execution_id,primitive_id) REFERENCES cg_primitive(execution_id,primitive_id),
 FOREIGN KEY(result_id) REFERENCES cg_result_commit(result_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cg_result_member (
 result_id TEXT NOT NULL REFERENCES cg_result(result_id), permit_id TEXT NOT NULL REFERENCES ci_cancel_commit(permit_id),
 PRIMARY KEY(result_id,permit_id)
) STRICT;
CREATE TABLE cg_result_commit (
 result_id TEXT PRIMARY KEY NOT NULL REFERENCES cg_result(result_id),
 provider_ref_body BLOB NOT NULL CHECK(length(provider_ref_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cg_revocation (
 result_id TEXT PRIMARY KEY NOT NULL REFERENCES cg_result_commit(result_id),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE cg_dispatch_dependency (
 permit_id TEXT NOT NULL REFERENCES ci_cancel_transmission(permit_id),
 execution_id TEXT NOT NULL, primitive_id TEXT NOT NULL, predecessor_id TEXT NOT NULL, result_id TEXT NOT NULL,
 PRIMARY KEY(permit_id,predecessor_id),
 FOREIGN KEY(execution_id,primitive_id,predecessor_id) REFERENCES cg_dependency(execution_id,primitive_id,predecessor_id),
 FOREIGN KEY(result_id,execution_id,predecessor_id) REFERENCES cg_result(result_id,execution_id,primitive_id),
 FOREIGN KEY(permit_id) REFERENCES ci_cancel_commit(permit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW cg_stopped AS
 SELECT r.execution_id,r.result_id,'result' source_kind FROM cg_result r
 JOIN cg_result_commit k USING(result_id) WHERE r.disposition!='succeeded'
 UNION ALL SELECT r.execution_id,r.result_id,'revocation' FROM cg_result r JOIN cg_revocation v USING(result_id);
CREATE VIEW cg_valid_success AS SELECT r.* FROM cg_result r JOIN cg_result_commit k USING(result_id)
 WHERE r.disposition='succeeded' AND NOT EXISTS(SELECT 1 FROM cg_revocation v WHERE v.result_id=r.result_id);
CREATE TRIGGER cg_plan_guard BEFORE INSERT ON cg_plan BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_cancel c JOIN cc_cut t USING(cancellation_id)
  JOIN cc_valid_closure h USING(cut_id) WHERE c.cancellation_id=NEW.cancellation_id
  AND c.mode='cooperative' AND t.stage='ordinary' AND h.closure_id=NEW.ordinary_closure_id)
  OR EXISTS(SELECT 1 FROM cc_cut WHERE cancellation_id=NEW.cancellation_id AND stage='all')
  OR EXISTS(SELECT 1 FROM cv_cancel_current WHERE cancellation_id=NEW.cancellation_id AND state!='requested')
  THEN RAISE(ABORT,'plan_not_admissible') END;
END;
CREATE TRIGGER cg_dependency_guard BEFORE INSERT ON cg_dependency BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_primitive p JOIN cg_primitive q USING(execution_id)
  WHERE p.execution_id=NEW.execution_id AND p.primitive_id=NEW.primitive_id
   AND q.primitive_id=NEW.predecessor_id AND q.position<p.position)
  THEN RAISE(ABORT,'plan_not_dag') END;
END;
CREATE TRIGGER cg_plan_seal BEFORE INSERT ON cg_plan_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p WHERE p.execution_id=NEW.execution_id
  AND p.resource_count=(SELECT count(*) FROM cg_resource WHERE execution_id=p.execution_id)
  AND p.primitive_count=(SELECT count(*) FROM cg_primitive WHERE execution_id=p.execution_id)
  AND p.primitive_count=(SELECT max(position) FROM cg_primitive WHERE execution_id=p.execution_id)
  AND p.dependency_count=(SELECT count(*) FROM cg_dependency WHERE execution_id=p.execution_id))
  THEN RAISE(ABORT,'plan_projection_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_plan p WHERE p.execution_id=NEW.execution_id AND
  (NOT EXISTS(SELECT 1 FROM cc_valid_closure WHERE closure_id=p.ordinary_closure_id) OR
   EXISTS(SELECT 1 FROM cc_cut WHERE cancellation_id=p.cancellation_id AND stage='all')))
  THEN RAISE(ABORT,'plan_not_admissible') END;
END;
CREATE TRIGGER cg_prepare_guard BEFORE INSERT ON cc_prepare BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cg_plan_commit k USING(execution_id)
  JOIN cg_primitive a USING(execution_id) WHERE p.execution_id=NEW.execution_id AND
  p.cancellation_id=NEW.cancellation_id AND p.execution_digest=NEW.execution_digest AND
  p.ordinary_closure_id=NEW.ordinary_closure_id AND a.primitive_id=NEW.primitive_id)
  THEN RAISE(ABORT,'prepare_plan_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_stopped WHERE execution_id=NEW.execution_id)
  THEN RAISE(ABORT,'cancel_plan_stopped') END;
END;
CREATE TRIGGER cg_result_guard BEFORE INSERT ON cg_result BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_primitive p JOIN cg_plan_commit k USING(execution_id)
  WHERE p.execution_id=NEW.execution_id AND p.primitive_id=NEW.primitive_id AND
  p.completion_policy_ref_body=NEW.completion_policy_ref_body)
  THEN RAISE(ABORT,'result_policy_binding') END;
 SELECT CASE WHEN NEW.issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  THEN RAISE(ABORT,'result_watermark') END;
END;
CREATE TRIGGER cg_result_seal BEFORE INSERT ON cg_result_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT t.permit_id FROM ci_cancel_transmission t JOIN cg_result r
  ON r.execution_id=t.execution_id AND r.primitive_id=t.primitive_id WHERE r.result_id=NEW.result_id
  EXCEPT SELECT permit_id FROM cg_result_member WHERE result_id=NEW.result_id)
  OR EXISTS(SELECT permit_id FROM cg_result_member WHERE result_id=NEW.result_id
   EXCEPT SELECT t.permit_id FROM ci_cancel_transmission t JOIN cg_result r
   ON r.execution_id=t.execution_id AND r.primitive_id=t.primitive_id WHERE r.result_id=NEW.result_id)
  THEN RAISE(ABORT,'result_transmission_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_result WHERE result_id=NEW.result_id AND disposition='succeeded')
  AND NOT EXISTS(SELECT 1 FROM cg_result_member WHERE result_id=NEW.result_id)
  THEN RAISE(ABORT,'success_without_transmission') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_result WHERE result_id=NEW.result_id AND
  issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue))
  THEN RAISE(ABORT,'result_watermark') END;
END;
CREATE TRIGGER cg_send_guard BEFORE INSERT ON ci_cancel_transmission BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cg_plan_commit k USING(execution_id)
  JOIN cg_primitive a USING(execution_id) WHERE p.execution_id=NEW.execution_id AND
  p.cancellation_id=NEW.cancellation_id AND p.execution_digest=NEW.execution_digest AND a.primitive_id=NEW.primitive_id)
  THEN RAISE(ABORT,'send_plan_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_result WHERE execution_id=NEW.execution_id AND primitive_id=NEW.primitive_id)
  OR EXISTS(SELECT 1 FROM cg_stopped WHERE execution_id=NEW.execution_id)
  THEN RAISE(ABORT,'cancel_plan_stopped') END;
END;
CREATE TRIGGER cg_dispatch_guard BEFORE INSERT ON ci_cancel_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cg_stopped s USING(execution_id)
  WHERE t.permit_id=NEW.permit_id)
  OR EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cg_result r USING(execution_id,primitive_id)
   WHERE t.permit_id=NEW.permit_id)
  THEN RAISE(ABORT,'cancel_plan_stopped') END;
 SELECT CASE WHEN EXISTS(SELECT d.predecessor_id FROM ci_cancel_transmission t
  JOIN cg_dependency d USING(execution_id,primitive_id) WHERE t.permit_id=NEW.permit_id
  EXCEPT SELECT predecessor_id FROM cg_dispatch_dependency WHERE permit_id=NEW.permit_id)
  OR EXISTS(SELECT 1 FROM cg_dispatch_dependency d JOIN ci_cancel_transmission t USING(permit_id)
   LEFT JOIN cg_valid_success r ON r.result_id=d.result_id WHERE d.permit_id=NEW.permit_id AND
   (d.execution_id!=t.execution_id OR d.primitive_id!=t.primitive_id OR r.result_id IS NULL))
  THEN RAISE(ABORT,'dependency_not_satisfied') END;
END;

CREATE TRIGGER cg_plan_u BEFORE UPDATE ON cg_plan BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_plan_d BEFORE DELETE ON cg_plan BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_resource_u BEFORE UPDATE ON cg_resource BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_resource_d BEFORE DELETE ON cg_resource BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_primitive_u BEFORE UPDATE ON cg_primitive BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_primitive_d BEFORE DELETE ON cg_primitive BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_dependency_u BEFORE UPDATE ON cg_dependency BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_dependency_d BEFORE DELETE ON cg_dependency BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_plan_commit_u BEFORE UPDATE ON cg_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_plan_commit_d BEFORE DELETE ON cg_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_result_u BEFORE UPDATE ON cg_result BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_result_d BEFORE DELETE ON cg_result BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_result_member_u BEFORE UPDATE ON cg_result_member BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_result_member_d BEFORE DELETE ON cg_result_member BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_result_commit_u BEFORE UPDATE ON cg_result_commit BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_result_commit_d BEFORE DELETE ON cg_result_commit BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_revocation_u BEFORE UPDATE ON cg_revocation BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_revocation_d BEFORE DELETE ON cg_revocation BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_dispatch_dependency_u BEFORE UPDATE ON cg_dispatch_dependency BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_dispatch_dependency_d BEFORE DELETE ON cg_dispatch_dependency BEGIN SELECT RAISE(ABORT,'immutable_cancel_plan'); END;

CREATE TRIGGER cg_resource_frozen BEFORE INSERT ON cg_resource WHEN EXISTS(SELECT 1 FROM cg_plan_commit WHERE execution_id=NEW.execution_id) BEGIN SELECT RAISE(ABORT,'plan_frozen'); END;

CREATE TRIGGER cg_primitive_frozen BEFORE INSERT ON cg_primitive WHEN EXISTS(SELECT 1 FROM cg_plan_commit WHERE execution_id=NEW.execution_id) BEGIN SELECT RAISE(ABORT,'plan_frozen'); END;

CREATE TRIGGER cg_dependency_frozen BEFORE INSERT ON cg_dependency WHEN EXISTS(SELECT 1 FROM cg_plan_commit WHERE execution_id=NEW.execution_id) BEGIN SELECT RAISE(ABORT,'plan_frozen'); END;

CREATE TRIGGER cg_result_member_frozen BEFORE INSERT ON cg_result_member WHEN EXISTS(SELECT 1 FROM cg_result_commit WHERE result_id=NEW.result_id) BEGIN SELECT RAISE(ABORT,'result_frozen'); END;

CREATE TRIGGER cg_dispatch_dependency_frozen BEFORE INSERT ON cg_dispatch_dependency WHEN EXISTS(SELECT 1 FROM ci_cancel_commit WHERE permit_id=NEW.permit_id) BEGIN SELECT RAISE(ABORT,'dispatch_dependency_frozen'); END;

-- 扩展同一cr_hold资源权威，不建立第二套风险/释放/恢复状态机。
DROP VIEW cr_release_validation;
CREATE VIEW cr_release_validation AS
 SELECT release_id,validation_id FROM cr_release
 UNION SELECT release_id,cancel_validation_id FROM cr_release WHERE cancel_validation_id IS NOT NULL
 UNION SELECT release_id,closure_validation_id FROM cr_release_attempt
 UNION SELECT m.release_id,s.validation_id FROM cr_release_member m JOIN cr_settlement_validation s USING(settlement_id)
 UNION SELECT release_id,closure_validation_id FROM cx_release_cancel
 UNION SELECT m.release_id,s.validation_id FROM cx_release_member m JOIN cx_settlement s USING(settlement_id);
CREATE TRIGGER ch_hold_guard BEFORE INSERT ON cr_hold WHEN NEW.cancel_execution_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  JOIN cc_valid_closure h ON h.closure_id=p.ordinary_closure_id
  WHERE p.execution_id=NEW.cancel_execution_id AND p.protected_hold_id=NEW.hold_id
   AND p.protected_hold_digest=NEW.hold_digest AND c.command_id=NEW.command_id
   AND v.command_id=NEW.command_id AND v.device_id=cmd.device_id AND v.purpose='hold'
   AND v.subject_id=NEW.hold_id AND v.subject_digest=NEW.hold_digest AND v.policy_ref=NEW.cancel_release_policy_ref)
  THEN RAISE(ABORT,'protected_hold_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_risk_hold h JOIN ce_command c USING(device_id)
  WHERE c.command_id=NEW.command_id AND h.command_id!=NEW.command_id)
  THEN RAISE(ABORT,'resource_busy') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_device_protection p JOIN ce_command c USING(device_id)
  WHERE c.command_id=NEW.command_id) THEN RAISE(ABORT,'device_protected') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_command c JOIN ce_command other USING(device_id)
  JOIN cm_latest r ON r.command_id=other.command_id WHERE c.command_id=NEW.command_id
   AND other.command_id!=NEW.command_id AND r.resource_status!='clear'
   AND EXISTS(SELECT 1 FROM cr_hold h WHERE h.command_id=other.command_id))
  THEN RAISE(ABORT,'command_resource_unresolved') END;
END;
CREATE TRIGGER ch_plan_seal BEFORE INSERT ON cg_plan_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cr_hold h ON h.hold_id=p.protected_hold_id
  WHERE p.execution_id=NEW.execution_id AND h.cancel_execution_id=p.execution_id AND h.attempt_id IS NULL
   AND h.hold_digest=p.protected_hold_digest)
  THEN RAISE(ABORT,'protected_hold_required') END;
END;
CREATE TRIGGER ch_hold_seal BEFORE INSERT ON cr_hold_commit WHEN EXISTS(
 SELECT 1 FROM cr_hold WHERE hold_id=NEW.hold_id AND cancel_execution_id IS NOT NULL) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_hold h JOIN cg_plan_commit p ON p.execution_id=h.cancel_execution_id
  WHERE h.hold_id=NEW.hold_id) THEN RAISE(ABORT,'protected_plan_unsealed') END;
END;
CREATE TRIGGER ch_cancel_permit BEFORE INSERT ON ci_cancel_transmission BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cr_hold h ON h.hold_id=p.protected_hold_id
  JOIN cr_hold_commit k USING(hold_id) JOIN cr_valid_validation v USING(validation_id)
  WHERE p.execution_id=NEW.execution_id AND h.cancel_execution_id=p.execution_id
   AND h.hold_digest=p.protected_hold_digest AND NOT EXISTS(SELECT 1 FROM cr_hold_close WHERE hold_id=h.hold_id)
   AND NOT EXISTS(SELECT 1 FROM cr_release WHERE hold_id=h.hold_id))
  THEN RAISE(ABORT,'protected_hold_unavailable') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_plan p JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_device_protection x USING(device_id)
  WHERE p.execution_id=NEW.execution_id) THEN RAISE(ABORT,'device_protected') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_plan p JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_risk_hold h USING(device_id)
  WHERE p.execution_id=NEW.execution_id AND h.command_id!=c.command_id)
  THEN RAISE(ABORT,'resource_busy') END;
END;
-- 最终发送提交复核：许可预写后撤回准入原件不能绕过。
CREATE TRIGGER ch_cancel_commit BEFORE INSERT ON ci_cancel_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cg_plan p USING(execution_id)
  JOIN cr_hold h ON h.hold_id=p.protected_hold_id WHERE t.permit_id=NEW.permit_id AND
   (NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=h.validation_id)
    OR EXISTS(SELECT 1 FROM cr_release WHERE hold_id=h.hold_id)
    OR EXISTS(SELECT 1 FROM cr_hold_close WHERE hold_id=h.hold_id)))
  THEN RAISE(ABORT,'protected_hold_unavailable') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_device_protection x USING(device_id) WHERE t.permit_id=NEW.permit_id)
  THEN RAISE(ABORT,'device_protected') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_risk_hold h USING(device_id)
  WHERE t.permit_id=NEW.permit_id AND h.command_id!=c.command_id)
  THEN RAISE(ABORT,'resource_busy') END;
END;
CREATE TRIGGER ch_release_seal BEFORE INSERT ON cr_release_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_release r JOIN cr_hold h USING(hold_id)
  WHERE r.release_id=NEW.release_id AND ((h.cancel_execution_id IS NULL AND r.cancel_validation_id IS NOT NULL)
   OR (h.cancel_execution_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cr_valid_validation v
     JOIN ce_command cmd ON cmd.command_id=h.command_id WHERE v.validation_id=r.cancel_validation_id
      AND v.command_id=h.command_id AND v.device_id=cmd.device_id AND v.purpose='release'
      AND v.subject_id=r.release_id AND v.subject_digest=r.release_digest AND v.policy_ref=h.cancel_release_policy_ref))))
  THEN RAISE(ABORT,'protected_release_policy') END;
END;

-- 资源验证的完整直接来源与取消结果祖先；须与独立占用129表组合。
CREATE TABLE cd_manifest (
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_validation(validation_id),
 basis TEXT NOT NULL CHECK(basis IN ('independent','cancel_result')),
 source_count INTEGER NOT NULL CHECK(source_count BETWEEN 0 AND 256),
 manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=71 AND substr(manifest_digest,1,7)='sha256:'
  AND substr(manifest_digest,8) NOT GLOB '*[^0-9a-f]*'),
 manifest_body BLOB NOT NULL CHECK(length(manifest_body)>0),
 CHECK((basis='independent' AND source_count=0) OR (basis='cancel_result' AND source_count>0)),
 FOREIGN KEY(validation_id) REFERENCES cd_manifest_commit(validation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cd_result_source (
 validation_id TEXT NOT NULL REFERENCES cd_manifest(validation_id),
 result_id TEXT NOT NULL REFERENCES cg_result_commit(result_id),
 result_digest TEXT NOT NULL,
 PRIMARY KEY(validation_id,result_id)
) STRICT;
CREATE TABLE cd_manifest_commit (
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cd_manifest(validation_id),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),
 manifest_digest TEXT NOT NULL,
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
-- 只走实际传输采用的结果，不把计划上的未执行边当作事实依赖。
CREATE VIEW cd_result_ancestor AS
 WITH RECURSIVE ancestry(root_result_id,result_id) AS (
  SELECT result_id,result_id FROM cg_result_commit
  UNION
  SELECT a.root_result_id,d.result_id FROM ancestry a
   JOIN cg_result_member m ON m.result_id=a.result_id
   JOIN cg_dispatch_dependency d ON d.permit_id=m.permit_id
 ) SELECT root_result_id,result_id FROM ancestry;
CREATE VIEW cd_affected_validation AS
 SELECT DISTINCT s.validation_id,a.result_id FROM cd_result_source s
 JOIN cd_result_ancestor a ON a.root_result_id=s.result_id;
DROP VIEW cr_valid_validation;
CREATE VIEW cr_valid_validation AS
 SELECT v.* FROM cr_validation v JOIN cd_manifest_commit k USING(validation_id)
 WHERE NOT EXISTS(SELECT 1 FROM cr_validation_revocation r WHERE r.validation_id=v.validation_id)
 AND NOT EXISTS(SELECT 1 FROM cd_affected_validation a JOIN cg_revocation r USING(result_id)
  WHERE a.validation_id=v.validation_id);
CREATE TRIGGER cd_source_frozen BEFORE INSERT ON cd_result_source
 WHEN EXISTS(SELECT 1 FROM cd_manifest_commit WHERE validation_id=NEW.validation_id)
 BEGIN SELECT RAISE(ABORT,'dependency_manifest_frozen'); END;
CREATE TRIGGER cd_manifest_seal BEFORE INSERT ON cd_manifest_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cd_manifest m JOIN cr_validation v USING(validation_id)
  WHERE m.validation_id=NEW.validation_id AND m.manifest_digest=NEW.manifest_digest
   AND v.provider_ref=NEW.provider_ref AND v.receipt_body=NEW.receipt_body
   AND m.source_count=(SELECT count(*) FROM cd_result_source WHERE validation_id=m.validation_id))
  THEN RAISE(ABORT,'dependency_manifest_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cd_result_source s JOIN cr_validation v USING(validation_id)
  LEFT JOIN cg_valid_success r ON r.result_id=s.result_id
  LEFT JOIN cg_plan p ON p.execution_id=r.execution_id
  LEFT JOIN cv_cancel c ON c.cancellation_id=p.cancellation_id
  LEFT JOIN ce_command cmd ON cmd.command_id=c.command_id
  WHERE s.validation_id=NEW.validation_id AND (r.result_id IS NULL OR s.result_digest!=r.evidence_digest
   OR cmd.device_id!=v.device_id OR (v.command_id IS NOT NULL AND c.command_id!=v.command_id)))
  THEN RAISE(ABORT,'dependency_result_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cd_affected_validation a JOIN cg_revocation r USING(result_id)
  WHERE a.validation_id=NEW.validation_id)
  OR EXISTS(SELECT 1 FROM cr_validation_revocation WHERE validation_id=NEW.validation_id)
  THEN RAISE(ABORT,'dependency_revoked') END;
END;
-- 撤回记录、全部验证失效、既有释放失效和本机保护在同一SQLite事务中。
-- 祖先通过视图一次求闭包；原资源触发链仍须启用recursive_triggers。
CREATE TRIGGER cd_result_revoke AFTER INSERT ON cg_revocation BEGIN
 INSERT OR IGNORE INTO cr_validation_revocation(validation_id,reason_body,audit_body)
 SELECT DISTINCT a.validation_id,NEW.reason_body,NEW.audit_body FROM cd_affected_validation a
 JOIN cd_manifest_commit k USING(validation_id) WHERE a.result_id=NEW.result_id;
END;

CREATE TRIGGER cd_manifest_u BEFORE UPDATE ON cd_manifest BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;

CREATE TRIGGER cd_manifest_d BEFORE DELETE ON cd_manifest BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;

CREATE TRIGGER cd_result_source_u BEFORE UPDATE ON cd_result_source BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;

CREATE TRIGGER cd_result_source_d BEFORE DELETE ON cd_result_source BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;

CREATE TRIGGER cd_manifest_commit_u BEFORE UPDATE ON cd_manifest_commit BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;

CREATE TRIGGER cd_manifest_commit_d BEFORE DELETE ON cd_manifest_commit BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;

-- 资源失效通知与CLOSE_GATE投递候选。逻辑正文不可变，发送记录不证明对端已关闭。
CREATE TABLE ro_incident (
 release_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_release_invalidation(release_id),
 device_id TEXT NOT NULL,
 issued_revision TEXT NOT NULL CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*')
) STRICT;
CREATE TABLE ro_target (
 release_id TEXT NOT NULL REFERENCES ro_incident(release_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 intent_id TEXT NOT NULL UNIQUE DEFAULT ('resource.'||lower(hex(randomblob(16)))),
 PRIMARY KEY(release_id,exit_id)
) STRICT;
CREATE TABLE ro_attempt (
 attempt_id TEXT PRIMARY KEY NOT NULL,
 close_id TEXT NOT NULL UNIQUE DEFAULT ('close.'||lower(hex(randomblob(16)))),
 release_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 2147483647),
 message_body BLOB NOT NULL CHECK(length(message_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(release_id,exit_id,ordinal), UNIQUE(attempt_id,release_id,exit_id),
 FOREIGN KEY(release_id,exit_id) REFERENCES ro_target(release_id,exit_id)
) STRICT;
CREATE TABLE ro_ack (
 ack_id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL UNIQUE REFERENCES ro_attempt(attempt_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 ack_digest TEXT NOT NULL, ack_body BLOB NOT NULL CHECK(length(ack_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ro_recovery_target (
 recovery_id TEXT NOT NULL REFERENCES cr_recovery(recovery_id),
 release_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 ack_id TEXT REFERENCES ro_ack(ack_id), retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 PRIMARY KEY(recovery_id,release_id,exit_id),
 CHECK((ack_id IS NOT NULL AND retirement_exit_id IS NULL) OR (ack_id IS NULL AND retirement_exit_id IS exit_id)),
 FOREIGN KEY(release_id,exit_id) REFERENCES ro_target(release_id,exit_id),
 FOREIGN KEY(recovery_id) REFERENCES cr_recovery_commit(recovery_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW ro_valid_ack AS
 SELECT a.*,p.release_id,p.exit_id FROM ro_ack a JOIN ro_attempt p USING(attempt_id)
 JOIN cr_valid_validation v USING(validation_id)
 WHERE NOT EXISTS(SELECT 1 FROM ro_attempt newer WHERE newer.release_id=p.release_id
  AND newer.exit_id=p.exit_id AND newer.ordinal>p.ordinal);
CREATE VIEW ro_valid_recovery_target AS
 SELECT r.* FROM ro_recovery_target r WHERE r.retirement_exit_id IS NOT NULL OR EXISTS(
  SELECT 1 FROM ro_valid_ack a WHERE a.ack_id=r.ack_id AND a.release_id=r.release_id AND a.exit_id=r.exit_id);
DROP VIEW cr_device_protection;
CREATE VIEW cr_device_protection AS
 SELECT x.release_id,h.command_id,c.device_id FROM cr_release_invalidation x
 JOIN cr_release r USING(release_id) JOIN cr_hold h USING(hold_id) JOIN ce_command c ON c.command_id=h.command_id
 WHERE NOT EXISTS(SELECT 1 FROM cr_recovery_member m JOIN cr_recovery y USING(recovery_id)
 JOIN cr_recovery_commit k USING(recovery_id) JOIN cr_valid_validation v ON v.validation_id=y.validation_id
 WHERE m.release_id=x.release_id AND y.device_id=c.device_id AND NOT EXISTS(
  SELECT 1 FROM ro_target t WHERE t.release_id=x.release_id AND NOT EXISTS(
   SELECT 1 FROM ro_valid_recovery_target p WHERE p.recovery_id=y.recovery_id
    AND p.release_id=t.release_id AND p.exit_id=t.exit_id)));
CREATE VIEW ro_pending AS
 SELECT t.*,i.device_id FROM ro_target t JOIN ro_incident i USING(release_id)
 WHERE EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=t.exit_id)
 AND NOT EXISTS(SELECT 1 FROM ro_valid_ack a WHERE a.release_id=t.release_id AND a.exit_id=t.exit_id
  AND NOT EXISTS(SELECT 1 FROM ro_recovery_target used JOIN cr_recovery_commit k USING(recovery_id)
   WHERE used.ack_id=a.ack_id));
CREATE TRIGGER ro_capture AFTER INSERT ON cr_release_invalidation BEGIN
 INSERT INTO ro_incident SELECT NEW.release_id,c.device_id,
  (SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
 FROM cr_release r JOIN ce_command c USING(command_id) WHERE r.release_id=NEW.release_id;
 INSERT OR IGNORE INTO ro_target(release_id,exit_id) SELECT i.release_id,e.exit_id FROM ce_exit e
 JOIN ro_incident i USING(device_id) WHERE i.device_id=(SELECT device_id FROM ro_incident WHERE release_id=NEW.release_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id);
END;
CREATE TRIGGER ro_new_exit AFTER INSERT ON ce_exit BEGIN
 INSERT INTO ro_target(release_id,exit_id) SELECT i.release_id,NEW.exit_id FROM ro_incident i
 WHERE i.device_id=NEW.device_id AND EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id);
END;
-- 旧恢复或ACK验证撤回后，为此时已存在的新出口补持久关闭请求。
CREATE TRIGGER ro_revoke_capture AFTER INSERT ON cr_validation_revocation BEGIN
 INSERT OR IGNORE INTO ro_target(release_id,exit_id)
 SELECT i.release_id,e.exit_id FROM ro_incident i JOIN ce_exit e USING(device_id)
 WHERE EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id);
END;
CREATE TRIGGER ro_target_guard BEFORE INSERT ON ro_target BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ro_incident i JOIN ce_exit e USING(device_id)
  WHERE i.release_id=NEW.release_id AND e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'protection_exit_binding') END;
END;
CREATE TRIGGER ro_incident_guard BEFORE INSERT ON ro_incident BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_release r JOIN ce_command c USING(command_id)
  WHERE r.release_id=NEW.release_id AND c.device_id=NEW.device_id)
  OR NEW.issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  THEN RAISE(ABORT,'incident_binding') END;
END;
CREATE TRIGGER ro_attempt_guard BEFORE INSERT ON ro_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ro_pending p WHERE p.release_id=NEW.release_id AND p.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'close_not_pending') END;
 SELECT CASE WHEN NEW.ordinal!=(SELECT coalesce(max(ordinal),0)+1 FROM ro_attempt
  WHERE release_id=NEW.release_id AND exit_id=NEW.exit_id) THEN RAISE(ABORT,'close_attempt_successor') END;
END;
CREATE TRIGGER ro_ack_guard BEFORE INSERT ON ro_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ro_attempt p JOIN ro_target t USING(release_id,exit_id)
  JOIN ro_incident i USING(release_id) JOIN cr_release r USING(release_id)
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE p.attempt_id=NEW.attempt_id AND v.purpose='close' AND v.subject_id=p.close_id
   AND v.subject_digest=NEW.ack_digest AND v.device_id=i.device_id AND v.command_id=r.command_id
   AND v.policy_ref='resource-close/1') THEN RAISE(ABORT,'close_ack_binding') END;
END;
CREATE TRIGGER ro_recovery_seal BEFORE INSERT ON cr_recovery_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT t.release_id,t.exit_id FROM ro_target t JOIN ro_incident i USING(release_id)
  JOIN cr_recovery r USING(device_id) WHERE r.recovery_id=NEW.recovery_id
  EXCEPT SELECT release_id,exit_id FROM ro_recovery_target WHERE recovery_id=NEW.recovery_id)
 OR EXISTS(SELECT release_id,exit_id FROM ro_recovery_target WHERE recovery_id=NEW.recovery_id
  EXCEPT SELECT t.release_id,t.exit_id FROM ro_target t JOIN ro_incident i USING(release_id)
  JOIN cr_recovery r USING(device_id) WHERE r.recovery_id=NEW.recovery_id)
 THEN RAISE(ABORT,'recovery_close_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ro_recovery_target t
  JOIN ro_recovery_target used ON used.ack_id=t.ack_id
  JOIN cr_recovery_commit k ON k.recovery_id=used.recovery_id
  WHERE t.recovery_id=NEW.recovery_id)
 THEN RAISE(ABORT,'recovery_close_consumed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ro_recovery_target t WHERE t.recovery_id=NEW.recovery_id
  AND NOT EXISTS(SELECT 1 FROM ro_valid_recovery_target v WHERE v.recovery_id=t.recovery_id
   AND v.release_id=t.release_id AND v.exit_id=t.exit_id)) THEN RAISE(ABORT,'recovery_close_invalid') END;
END;
CREATE TRIGGER ro_recovery_frozen BEFORE INSERT ON ro_recovery_target
 WHEN EXISTS(SELECT 1 FROM cr_recovery_commit WHERE recovery_id=NEW.recovery_id)
 BEGIN SELECT RAISE(ABORT,'recovery_frozen'); END;

CREATE TRIGGER ro_incident_u BEFORE UPDATE ON ro_incident BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_incident_d BEFORE DELETE ON ro_incident BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_target_u BEFORE UPDATE ON ro_target BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_target_d BEFORE DELETE ON ro_target BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_attempt_u BEFORE UPDATE ON ro_attempt BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_attempt_d BEFORE DELETE ON ro_attempt BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_ack_u BEFORE UPDATE ON ro_ack BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_ack_d BEFORE DELETE ON ro_ack BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_recovery_target_u BEFORE UPDATE ON ro_recovery_target BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

CREATE TRIGGER ro_recovery_target_d BEFORE DELETE ON ro_recovery_target BEGIN SELECT RAISE(ABORT,'immutable_resource_close'); END;

-- 控制受理148表候选；effective及ready尚未归并，不可部署。
CREATE TABLE ct_change(
 change_id TEXT PRIMARY KEY CHECK(length(change_id)>0),
 scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
 device_id TEXT NOT NULL CHECK(length(device_id)>0),
 sequence TEXT NOT NULL CHECK(length(sequence)=20 AND sequence NOT GLOB '*[^0-9]*'), previous_id TEXT REFERENCES ct_change(change_id),
 kind TEXT NOT NULL CHECK(kind IN ('bootstrap','offer','accept','acquire','release','cancel','expire','unknown','reject','retry','restart','effective','ready','gate_protect','scope_commit')),
 state_id TEXT REFERENCES ct_state(change_id) DEFERRABLE INITIALLY DEFERRED,
 operation_id TEXT REFERENCES ct_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 offer_id TEXT REFERENCES ct_offer(offer_id) DEFERRABLE INITIALLY DEFERRED,
 request_id TEXT REFERENCES ct_request(change_id) DEFERRABLE INITIALLY DEFERRED,
 clock_domain TEXT NOT NULL CHECK(length(clock_domain)>0),
 descriptor TEXT NOT NULL CHECK(length(descriptor)>0), now_tick TEXT NOT NULL CHECK(length(now_tick)=20 AND now_tick NOT GLOB '*[^0-9]*'),
 UNIQUE(device_id,sequence),
 FOREIGN KEY(change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(state_id IS CASE WHEN kind IN ('bootstrap','accept','acquire','release','unknown','reject','restart','effective','ready','gate_protect','scope_commit') THEN change_id END),
 CHECK(request_id IS CASE WHEN kind IN ('offer','accept','acquire','release','cancel') THEN change_id END),
 CHECK((operation_id IS NOT NULL)=(kind IN ('accept','acquire','release','unknown','reject','retry','effective'))),
 CHECK((offer_id IS NOT NULL)=(kind IN ('offer','accept','cancel','expire')))
) STRICT;
CREATE TABLE ct_state(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 record_revision TEXT NOT NULL CHECK(length(record_revision)=20 AND record_revision NOT GLOB '*[^0-9]*'), control_epoch TEXT NOT NULL CHECK(length(control_epoch)>0),
 effective_version TEXT NOT NULL CHECK(length(effective_version)=20 AND effective_version NOT GLOB '*[^0-9]*'), reserved_version TEXT NOT NULL CHECK(length(reserved_version)=20 AND reserved_version NOT GLOB '*[^0-9]*'),
 mode TEXT NOT NULL CHECK(mode IN ('automatic','manual')), holder_issuer TEXT CHECK(holder_issuer IS NULL OR length(holder_issuer)>0),
holder_epoch TEXT CHECK(holder_epoch IS NULL OR length(holder_epoch)>0),
holder_id TEXT CHECK(holder_id IS NULL OR length(holder_id)>0),
 pending_operation_id TEXT REFERENCES ct_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 gate_state TEXT NOT NULL CHECK(gate_state IN ('protected','fencing','ready')),
 record_digest TEXT NOT NULL CHECK(length(record_digest)>0),
 record_body BLOB NOT NULL CHECK(length(record_body)>0),
 CHECK(effective_version<=reserved_version),
 CHECK((mode='automatic' AND holder_issuer IS NULL AND holder_epoch IS NULL AND holder_id IS NULL) OR
       (mode='manual' AND holder_issuer IS NOT NULL AND holder_epoch IS NOT NULL AND holder_id IS NOT NULL))
) STRICT;
CREATE TABLE ct_operation(
 operation_id TEXT PRIMARY KEY CHECK(length(operation_id)>0),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_change(change_id),
 kind TEXT NOT NULL CHECK(kind IN ('acquire','release','transfer')),
 requester_issuer TEXT NOT NULL CHECK(requester_issuer IS NULL OR length(requester_issuer)>0),
requester_epoch TEXT NOT NULL CHECK(requester_epoch IS NULL OR length(requester_epoch)>0),
requester_id TEXT NOT NULL CHECK(requester_id IS NULL OR length(requester_id)>0), target_issuer TEXT CHECK(target_issuer IS NULL OR length(target_issuer)>0),
target_epoch TEXT CHECK(target_epoch IS NULL OR length(target_epoch)>0),
target_id TEXT CHECK(target_id IS NULL OR length(target_id)>0),
 expected_state_id TEXT NOT NULL REFERENCES ct_state(change_id), target_version TEXT NOT NULL CHECK(length(target_version)=20 AND target_version NOT GLOB '*[^0-9]*'),
 offer_id TEXT UNIQUE REFERENCES ct_offer(offer_id),
 force INTEGER NOT NULL CHECK(force IN (0,1)), reason TEXT NOT NULL CHECK(length(trim(reason))>0),
 CHECK((kind='release' AND target_issuer IS NULL AND target_epoch IS NULL AND target_id IS NULL) OR
       (kind!='release' AND target_issuer IS NOT NULL AND target_epoch IS NOT NULL AND target_id IS NOT NULL)),
 CHECK((offer_id IS NOT NULL)=(kind='transfer'))
) STRICT;
CREATE TABLE ct_attempt(
 attempt_id TEXT PRIMARY KEY CHECK(length(attempt_id)>0),
 operation_id TEXT NOT NULL REFERENCES ct_operation(operation_id),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_change(change_id), ordinal TEXT NOT NULL CHECK(length(ordinal)=20 AND ordinal NOT GLOB '*[^0-9]*'),
 UNIQUE(operation_id,ordinal), UNIQUE(attempt_id,operation_id)
) STRICT;
CREATE TABLE ct_operation_event(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 operation_id TEXT NOT NULL REFERENCES ct_operation(operation_id), revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'),
 state TEXT NOT NULL CHECK(state IN ('pending','indeterminate','rejected','effective')),
 attempt_id TEXT NOT NULL, failure_code TEXT,
 result_digest TEXT NOT NULL CHECK(length(result_digest)>0), result_body BLOB NOT NULL CHECK(length(result_body)>0),
 UNIQUE(operation_id,revision),
 FOREIGN KEY(attempt_id,operation_id) REFERENCES ct_attempt(attempt_id,operation_id),
 CHECK((state IN ('pending','effective') AND failure_code IS NULL) OR (state NOT IN ('pending','effective') AND failure_code IS NOT NULL AND length(failure_code)>0))
) STRICT;
CREATE TABLE ct_offer(
 offer_id TEXT PRIMARY KEY CHECK(length(offer_id)>0),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_change(change_id),
 sender_issuer TEXT NOT NULL CHECK(sender_issuer IS NULL OR length(sender_issuer)>0),
sender_epoch TEXT NOT NULL CHECK(sender_epoch IS NULL OR length(sender_epoch)>0),
sender_id TEXT NOT NULL CHECK(sender_id IS NULL OR length(sender_id)>0), target_issuer TEXT NOT NULL CHECK(target_issuer IS NULL OR length(target_issuer)>0),
target_epoch TEXT NOT NULL CHECK(target_epoch IS NULL OR length(target_epoch)>0),
target_id TEXT NOT NULL CHECK(target_id IS NULL OR length(target_id)>0),
 expected_state_id TEXT NOT NULL REFERENCES ct_state(change_id),
 clock_domain TEXT NOT NULL CHECK(length(clock_domain)>0), descriptor TEXT NOT NULL CHECK(length(descriptor)>0),
 issued_tick TEXT NOT NULL CHECK(length(issued_tick)=20 AND issued_tick NOT GLOB '*[^0-9]*'), expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'), reason TEXT NOT NULL CHECK(length(trim(reason))>0),
 CHECK(issued_tick<expires_tick), CHECK(NOT(sender_issuer IS target_issuer AND sender_epoch IS target_epoch AND sender_id IS target_id))
) STRICT;
CREATE TABLE ct_offer_event(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 offer_id TEXT NOT NULL REFERENCES ct_offer(offer_id), revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'),
 state TEXT NOT NULL CHECK(state IN ('offered','accepted','expired','cancelled')),
 accepted_operation_id TEXT UNIQUE REFERENCES ct_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 result_digest TEXT NOT NULL CHECK(length(result_digest)>0), result_body BLOB NOT NULL CHECK(length(result_body)>0),
 UNIQUE(offer_id,revision), CHECK((accepted_operation_id IS NOT NULL)=(state='accepted'))
) STRICT;
CREATE TABLE ct_request(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id), actor_issuer TEXT NOT NULL CHECK(actor_issuer IS NULL OR length(actor_issuer)>0),
actor_epoch TEXT NOT NULL CHECK(actor_epoch IS NULL OR length(actor_epoch)>0),
actor_id TEXT NOT NULL CHECK(actor_id IS NULL OR length(actor_id)>0),
 request_epoch TEXT NOT NULL CHECK(length(request_epoch)>0),
 api_operation TEXT NOT NULL CHECK(api_operation IN ('offerTransfer','acceptTransfer','acquireControl','releaseControl','cancelTransfer')),
 idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)>0),
 request_digest TEXT NOT NULL CHECK(length(request_digest)>0), request_body BLOB NOT NULL CHECK(length(request_body)>0),
 result_kind TEXT NOT NULL CHECK(result_kind IN ('control_operation','transfer_offer')),
 initial_result_id TEXT NOT NULL CHECK(length(initial_result_id)>0),
 initial_result_revision TEXT NOT NULL CHECK(length(initial_result_revision)=20 AND initial_result_revision NOT GLOB '*[^0-9]*'),
 initial_result_digest TEXT NOT NULL CHECK(length(initial_result_digest)>0),
 UNIQUE(actor_issuer,actor_epoch,actor_id,request_epoch,api_operation,idempotency_key)
) STRICT;
CREATE TABLE ct_audit(change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 body BLOB NOT NULL CHECK(length(body)>0)) STRICT;
CREATE TABLE ct_outbox(change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 event_id TEXT NOT NULL UNIQUE CHECK(length(event_id)>0), body BLOB NOT NULL CHECK(length(body)>0)) STRICT;
CREATE TABLE ct_commit(change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 FOREIGN KEY(change_id) REFERENCES ct_audit(change_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(change_id) REFERENCES ct_outbox(change_id) DEFERRABLE INITIALLY DEFERRED) STRICT;
CREATE VIEW ct_current_change AS SELECT c.* FROM ct_change c JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM ct_change n JOIN ct_commit nk ON nk.change_id=n.change_id WHERE n.device_id=c.device_id AND n.sequence>c.sequence);
CREATE VIEW ct_current_state AS SELECT s.*,c.device_id FROM ct_state s JOIN ct_change c USING(change_id) JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM ct_state n JOIN ct_change nc ON nc.change_id=n.change_id JOIN ct_commit nk ON nk.change_id=n.change_id
 WHERE nc.device_id=c.device_id AND n.record_revision>s.record_revision);
CREATE VIEW ct_current_operation AS SELECT e.* FROM ct_operation_event e JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM ct_operation_event n JOIN ct_commit nk ON nk.change_id=n.change_id WHERE n.operation_id=e.operation_id AND n.revision>e.revision);
CREATE VIEW ct_current_offer AS SELECT e.* FROM ct_offer_event e JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM ct_offer_event n JOIN ct_commit nk ON nk.change_id=n.change_id WHERE n.offer_id=e.offer_id AND n.revision>e.revision);
CREATE TRIGGER ct_seal BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND
  ((c.kind='bootstrap' AND c.previous_id IS NULL AND c.sequence='00000000000000000001' AND NOT EXISTS(SELECT 1 FROM ct_current_change p WHERE p.device_id=c.device_id)) OR
   (c.kind!='bootstrap' AND EXISTS(SELECT 1 FROM ct_current_change p WHERE p.change_id=c.previous_id AND p.device_id=c.device_id AND p.sequence<'99999999999999999999' AND c.sequence=printf('%010d%010d',CAST(substr(p.sequence,1,10) AS INTEGER)+(substr(p.sequence,11,10)='9999999999'),(CAST(substr(p.sequence,11,10) AS INTEGER)+1)%10000000000))))) THEN RAISE(ABORT,'control_change_cas') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_audit a JOIN ct_outbox o USING(change_id) WHERE a.change_id=NEW.change_id) THEN RAISE(ABORT,'control_commit_pair') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND
  ((SELECT count(*) FROM ct_state WHERE change_id=c.change_id)!=(c.state_id IS NOT NULL) OR
   (SELECT count(*) FROM ct_request WHERE change_id=c.change_id)!=(c.request_id IS NOT NULL) OR
   (SELECT count(*) FROM ct_operation_event WHERE change_id=c.change_id)!=(c.operation_id IS NOT NULL) OR
   (SELECT count(*) FROM ct_operation WHERE change_id=c.change_id)!=(c.kind IN ('acquire','release','accept')) OR
   (SELECT count(*) FROM ct_attempt WHERE change_id=c.change_id)!=(c.kind IN ('acquire','release','accept','retry')) OR
   (SELECT count(*) FROM ct_offer WHERE change_id=c.change_id)!=(c.kind='offer') OR
   (SELECT count(*) FROM ct_offer_event WHERE change_id=c.change_id)!=(c.offer_id IS NOT NULL))) THEN RAISE(ABORT,'control_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_request q USING(change_id) WHERE c.change_id=NEW.change_id AND
  (q.api_operation!=CASE c.kind WHEN 'offer' THEN 'offerTransfer' WHEN 'accept' THEN 'acceptTransfer' WHEN 'acquire' THEN 'acquireControl' WHEN 'release' THEN 'releaseControl' WHEN 'cancel' THEN 'cancelTransfer' END OR
   NOT ((q.result_kind='control_operation' AND EXISTS(SELECT 1 FROM ct_operation_event e WHERE e.change_id=c.change_id AND e.operation_id=q.initial_result_id AND e.revision=q.initial_result_revision AND e.result_digest=q.initial_result_digest)) OR
        (q.result_kind='transfer_offer' AND EXISTS(SELECT 1 FROM ct_offer_event e WHERE e.change_id=c.change_id AND e.offer_id=q.initial_result_id AND e.revision=q.initial_result_revision AND e.result_digest=q.initial_result_digest))) OR
   (q.result_kind='control_operation')!=(c.kind IN ('acquire','release','accept')))) THEN RAISE(ABORT,'control_receipt_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_state s USING(change_id) WHERE c.change_id=NEW.change_id AND
  ((c.kind='bootstrap' AND (s.record_revision!='00000000000000000001' OR s.pending_operation_id IS NOT NULL OR s.gate_state!='protected')) OR
   (c.kind!='bootstrap' AND NOT EXISTS(SELECT 1 FROM ct_current_state p WHERE p.device_id=c.device_id AND p.record_revision<'99999999999999999999' AND
     s.record_revision=printf('%010d%010d',CAST(substr(p.record_revision,1,10) AS INTEGER)+(substr(p.record_revision,11,10)='9999999999'),(CAST(substr(p.record_revision,11,10) AS INTEGER)+1)%10000000000) AND s.control_epoch=p.control_epoch AND (c.kind='effective' OR (s.effective_version=p.effective_version AND s.mode=p.mode AND s.holder_issuer IS p.holder_issuer AND s.holder_epoch IS p.holder_epoch AND s.holder_id IS p.holder_id)) AND
     ((c.kind='scope_commit' AND s.reserved_version=p.reserved_version AND p.pending_operation_id IS NULL AND s.pending_operation_id IS NULL AND s.gate_state='protected') OR
      (c.kind='ready' AND s.reserved_version=p.reserved_version AND p.pending_operation_id IS NULL AND s.pending_operation_id IS NULL AND s.gate_state='ready') OR
      (c.kind='gate_protect' AND s.reserved_version=p.reserved_version AND s.pending_operation_id IS p.pending_operation_id AND s.gate_state='protected') OR
      (c.kind='effective' AND s.reserved_version=p.reserved_version AND p.pending_operation_id IS c.operation_id AND s.pending_operation_id IS NULL AND s.gate_state='protected') OR
      (c.kind IN ('acquire','release','accept') AND p.pending_operation_id IS NULL AND p.reserved_version<'99999999999999999999' AND s.reserved_version=printf('%010d%010d',CAST(substr(p.reserved_version,1,10) AS INTEGER)+(substr(p.reserved_version,11,10)='9999999999'),(CAST(substr(p.reserved_version,11,10) AS INTEGER)+1)%10000000000) AND s.pending_operation_id IS c.operation_id AND s.gate_state='fencing') OR
      (c.kind IN ('unknown','reject') AND p.pending_operation_id IS c.operation_id AND s.reserved_version=p.reserved_version AND s.pending_operation_id IS CASE WHEN c.kind='unknown' THEN c.operation_id END AND s.gate_state='protected') OR
      (c.kind='restart' AND s.reserved_version=p.reserved_version AND s.pending_operation_id IS p.pending_operation_id AND s.gate_state='protected')))))) THEN RAISE(ABORT,'control_state_transition') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_operation o ON o.change_id=c.change_id JOIN ct_request q ON q.change_id=c.change_id
  WHERE c.change_id=NEW.change_id AND (o.operation_id IS NOT c.operation_id OR o.kind!=CASE c.kind WHEN 'accept' THEN 'transfer' ELSE c.kind END OR NOT(o.requester_issuer IS q.actor_issuer AND o.requester_epoch IS q.actor_epoch AND o.requester_id IS q.actor_id) OR
  NOT EXISTS(SELECT 1 FROM ct_current_state p JOIN ct_state s ON s.change_id=c.change_id WHERE p.device_id=c.device_id AND o.expected_state_id=p.change_id AND o.target_version=s.reserved_version AND
   ((c.kind='release' AND p.mode='manual' AND o.requester_issuer IS p.holder_issuer AND o.requester_epoch IS p.holder_epoch AND o.requester_id IS p.holder_id AND o.force=0) OR
    (c.kind IN ('acquire','accept') AND o.target_issuer IS o.requester_issuer AND o.target_epoch IS o.requester_epoch AND o.target_id IS o.requester_id AND NOT(o.requester_issuer IS p.holder_issuer AND o.requester_epoch IS p.holder_epoch AND o.requester_id IS p.holder_id) AND
      (c.kind='accept' OR p.mode='automatic' OR o.force=1)))) OR (c.kind='accept' AND (o.offer_id IS NOT c.offer_id OR o.force!=0)))) THEN RAISE(ABORT,'control_operation_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_operation_event e USING(change_id) JOIN ct_operation o ON o.operation_id=e.operation_id
  JOIN ct_change oc ON oc.change_id=o.change_id WHERE c.change_id=NEW.change_id AND
  (e.operation_id IS NOT c.operation_id OR oc.device_id!=c.device_id OR
   (c.kind IN ('acquire','release','accept') AND (e.revision!='00000000000000000001' OR e.state!='pending')) OR
   (c.kind IN ('unknown','reject','retry','effective') AND NOT EXISTS(SELECT 1 FROM ct_current_operation p JOIN ct_current_state s ON s.device_id=c.device_id
     WHERE p.operation_id=e.operation_id AND p.state IN ('pending','indeterminate') AND s.pending_operation_id IS e.operation_id AND p.revision<'99999999999999999999' AND e.revision=printf('%010d%010d',CAST(substr(p.revision,1,10) AS INTEGER)+(substr(p.revision,11,10)='9999999999'),(CAST(substr(p.revision,11,10) AS INTEGER)+1)%10000000000) AND
     ((c.kind='effective' AND e.state='effective' AND e.attempt_id=p.attempt_id) OR
      (c.kind='unknown' AND e.state='indeterminate' AND e.attempt_id=p.attempt_id) OR
      (c.kind='reject' AND e.state='rejected' AND e.attempt_id=p.attempt_id) OR
      (c.kind='retry' AND p.state='indeterminate' AND e.state='indeterminate' AND e.attempt_id!=p.attempt_id)))) OR
   (c.kind IN ('acquire','release','accept','retry') AND NOT EXISTS(SELECT 1 FROM ct_attempt a WHERE a.change_id=c.change_id AND a.attempt_id=e.attempt_id AND a.operation_id=e.operation_id)) OR
   (c.kind IN ('unknown','reject') AND EXISTS(SELECT 1 FROM ct_attempt a WHERE a.change_id=c.change_id)))) THEN RAISE(ABORT,'control_operation_transition') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_attempt a JOIN ct_change c USING(change_id) WHERE c.change_id=NEW.change_id AND
  (a.operation_id IS NOT c.operation_id OR
   (c.kind!='retry' AND a.ordinal!='00000000000000000001') OR
   (c.kind='retry' AND NOT EXISTS(SELECT 1 FROM ct_attempt p JOIN ct_current_operation e ON e.attempt_id=p.attempt_id WHERE e.operation_id=a.operation_id AND p.ordinal<'99999999999999999999' AND a.ordinal=printf('%010d%010d',CAST(substr(p.ordinal,1,10) AS INTEGER)+(substr(p.ordinal,11,10)='9999999999'),(CAST(substr(p.ordinal,11,10) AS INTEGER)+1)%10000000000))))) THEN RAISE(ABORT,'control_attempt_successor') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_offer o JOIN ct_change c USING(change_id) JOIN ct_request q USING(change_id)
  WHERE c.change_id=NEW.change_id AND (o.offer_id IS NOT c.offer_id OR NOT(o.sender_issuer IS q.actor_issuer AND o.sender_epoch IS q.actor_epoch AND o.sender_id IS q.actor_id) OR o.clock_domain!=c.clock_domain OR o.descriptor!=c.descriptor OR o.issued_tick!=c.now_tick OR
   NOT EXISTS(SELECT 1 FROM ct_current_state s WHERE s.device_id=c.device_id AND s.change_id=o.expected_state_id AND s.mode='manual' AND s.pending_operation_id IS NULL AND o.sender_issuer IS s.holder_issuer AND o.sender_epoch IS s.holder_epoch AND o.sender_id IS s.holder_id))) THEN RAISE(ABORT,'control_offer_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_offer_event e JOIN ct_change c USING(change_id) JOIN ct_offer o ON o.offer_id=e.offer_id JOIN ct_change oc ON oc.change_id=o.change_id
  WHERE c.change_id=NEW.change_id AND (e.offer_id IS NOT c.offer_id OR oc.device_id!=c.device_id OR
   (c.kind='offer' AND (e.state!='offered' OR e.revision!='00000000000000000001')) OR
   (c.kind!='offer' AND NOT EXISTS(SELECT 1 FROM ct_current_offer p WHERE p.offer_id=e.offer_id AND p.state='offered' AND p.revision<'99999999999999999999' AND e.revision=printf('%010d%010d',CAST(substr(p.revision,1,10) AS INTEGER)+(substr(p.revision,11,10)='9999999999'),(CAST(substr(p.revision,11,10) AS INTEGER)+1)%10000000000))) OR
   (c.kind='accept' AND (e.state!='accepted' OR e.accepted_operation_id IS NOT c.operation_id OR o.clock_domain!=c.clock_domain OR o.descriptor!=c.descriptor OR c.now_tick<o.issued_tick OR c.now_tick>=o.expires_tick OR
     NOT EXISTS(SELECT 1 FROM ct_request q JOIN ct_current_state s ON s.device_id=c.device_id JOIN ct_state old ON old.change_id=o.expected_state_id
      WHERE q.change_id=c.change_id AND o.target_issuer IS q.actor_issuer AND o.target_epoch IS q.actor_epoch AND o.target_id IS q.actor_id AND o.sender_issuer IS s.holder_issuer AND o.sender_epoch IS s.holder_epoch AND o.sender_id IS s.holder_id AND s.control_epoch=old.control_epoch AND s.effective_version=old.effective_version))) OR
   (c.kind='cancel' AND (e.state!='cancelled' OR NOT EXISTS(SELECT 1 FROM ct_request q WHERE q.change_id=c.change_id AND q.actor_issuer IS o.sender_issuer AND q.actor_epoch IS o.sender_epoch AND q.actor_id IS o.sender_id))) OR
   (c.kind='expire' AND (e.state!='expired' OR (c.clock_domain=o.clock_domain AND c.descriptor=o.descriptor AND c.now_tick<o.expires_tick))))) THEN RAISE(ABORT,'control_offer_transition') END;
END;

CREATE TRIGGER ct_change_u BEFORE UPDATE ON ct_change BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_change_d BEFORE DELETE ON ct_change BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_state_u BEFORE UPDATE ON ct_state BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_state_d BEFORE DELETE ON ct_state BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_state_sealed BEFORE INSERT ON ct_state WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_operation_u BEFORE UPDATE ON ct_operation BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_operation_d BEFORE DELETE ON ct_operation BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_operation_sealed BEFORE INSERT ON ct_operation WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_operation_event_u BEFORE UPDATE ON ct_operation_event BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_operation_event_d BEFORE DELETE ON ct_operation_event BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_operation_event_sealed BEFORE INSERT ON ct_operation_event WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_attempt_u BEFORE UPDATE ON ct_attempt BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_attempt_d BEFORE DELETE ON ct_attempt BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_attempt_sealed BEFORE INSERT ON ct_attempt WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_offer_u BEFORE UPDATE ON ct_offer BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_offer_d BEFORE DELETE ON ct_offer BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_offer_sealed BEFORE INSERT ON ct_offer WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_offer_event_u BEFORE UPDATE ON ct_offer_event BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_offer_event_d BEFORE DELETE ON ct_offer_event BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_offer_event_sealed BEFORE INSERT ON ct_offer_event WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_request_u BEFORE UPDATE ON ct_request BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_request_d BEFORE DELETE ON ct_request BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_request_sealed BEFORE INSERT ON ct_request WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_audit_u BEFORE UPDATE ON ct_audit BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_audit_d BEFORE DELETE ON ct_audit BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_audit_sealed BEFORE INSERT ON ct_audit WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_outbox_u BEFORE UPDATE ON ct_outbox BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_outbox_d BEFORE DELETE ON ct_outbox BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_outbox_sealed BEFORE INSERT ON ct_outbox WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;

CREATE TRIGGER ct_commit_u BEFORE UPDATE ON ct_commit BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

CREATE TRIGGER ct_commit_d BEFORE DELETE ON ct_commit BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;

-- 控制屏障161表候选；生效与开放分开，不能作为生产迁移。
CREATE TABLE cu_cut(
 prepare_cut_id TEXT NOT NULL UNIQUE REFERENCES pd_cut(cut_id) DEFERRABLE INITIALLY DEFERRED,
 operation_id TEXT PRIMARY KEY REFERENCES ct_operation(operation_id),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_change(change_id), device_id TEXT NOT NULL,
 issued_revision TEXT NOT NULL CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*'),
 cut_digest TEXT NOT NULL, cut_body BLOB NOT NULL CHECK(length(cut_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cu_target(
 operation_id TEXT NOT NULL REFERENCES cu_cut(operation_id), exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 PRIMARY KEY(operation_id,exit_id)
) STRICT;
CREATE TABLE cu_member(
 operation_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL REFERENCES ci_issue(permit_id),
 entered_known INTEGER NOT NULL CHECK(entered_known IN (0,1)),
 PRIMARY KEY(operation_id,permit_id), UNIQUE(operation_id,exit_id,permit_id),
 FOREIGN KEY(operation_id,exit_id) REFERENCES cu_target(operation_id,exit_id)
) STRICT;
CREATE TABLE cu_queued(
 operation_id TEXT NOT NULL REFERENCES cu_cut(operation_id), command_id TEXT NOT NULL UNIQUE,
 before_revision TEXT NOT NULL, blocked_revision TEXT NOT NULL,
 PRIMARY KEY(operation_id,command_id),
 FOREIGN KEY(command_id,before_revision) REFERENCES cm_revision(command_id,revision),
 FOREIGN KEY(command_id,blocked_revision) REFERENCES cm_revision(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_delivery(
 barrier_id TEXT PRIMARY KEY CHECK(length(barrier_id)>0), attempt_id TEXT NOT NULL REFERENCES ct_attempt(attempt_id),
 operation_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 target_gate_revision TEXT NOT NULL CHECK(length(target_gate_revision)=20 AND target_gate_revision NOT GLOB '*[^0-9]*'),
 request_digest TEXT NOT NULL, request_body BLOB NOT NULL CHECK(length(request_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 UNIQUE(attempt_id,exit_id), UNIQUE(barrier_id,operation_id,exit_id),
 FOREIGN KEY(attempt_id,operation_id) REFERENCES ct_attempt(attempt_id,operation_id),
 FOREIGN KEY(operation_id,exit_id) REFERENCES cu_target(operation_id,exit_id)
) STRICT;
CREATE TABLE cu_coverage(
 barrier_id TEXT NOT NULL, operation_id TEXT NOT NULL, exit_id TEXT NOT NULL, permit_id TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 proof TEXT NOT NULL CHECK((disposition='not_sent' AND proof IN ('never_received','discarded_unconsumed')) OR
   (disposition='in_flight' AND proof='transport_entered') OR (disposition='unknown' AND proof='send_uncertain')),
 PRIMARY KEY(barrier_id,permit_id),
 FOREIGN KEY(barrier_id,operation_id,exit_id) REFERENCES cu_delivery(barrier_id,operation_id,exit_id),
 FOREIGN KEY(operation_id,exit_id,permit_id) REFERENCES cu_member(operation_id,exit_id,permit_id),
 FOREIGN KEY(barrier_id) REFERENCES cu_ack(barrier_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_ack(
 barrier_id TEXT PRIMARY KEY REFERENCES cu_delivery(barrier_id),
 control_epoch TEXT NOT NULL, installed_version TEXT NOT NULL, gate_revision TEXT NOT NULL,
 issued_revision TEXT NOT NULL, cut_digest TEXT NOT NULL,
 effective_tick TEXT NOT NULL CHECK(length(effective_tick)=20 AND effective_tick NOT GLOB '*[^0-9]*'),
 ack_digest TEXT NOT NULL, ack_body BLOB NOT NULL CHECK(length(ack_body)>0),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE cu_authorization(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id), operation_id TEXT NOT NULL REFERENCES ct_operation(operation_id),
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, principal_id TEXT NOT NULL,
 clock_domain TEXT NOT NULL, descriptor TEXT NOT NULL,
 issued_tick TEXT NOT NULL CHECK(length(issued_tick)=20 AND issued_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), snapshot_digest TEXT NOT NULL,
 snapshot_body BLOB NOT NULL CHECK(length(snapshot_body)>0), CHECK(issued_tick<expires_tick),
 FOREIGN KEY(change_id) REFERENCES cu_effective(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_selection(
 change_id TEXT NOT NULL REFERENCES ct_change(change_id), operation_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 barrier_id TEXT REFERENCES cu_ack(barrier_id), retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 PRIMARY KEY(change_id,exit_id),
 CHECK((barrier_id IS NOT NULL AND retirement_exit_id IS NULL) OR (barrier_id IS NULL AND retirement_exit_id IS exit_id)),
 FOREIGN KEY(operation_id,exit_id) REFERENCES cu_target(operation_id,exit_id),
 FOREIGN KEY(change_id) REFERENCES cu_effective(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_effective(
 prepare_closure_id TEXT NOT NULL REFERENCES pd_closure_commit(closure_id),
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id), operation_id TEXT NOT NULL UNIQUE REFERENCES cu_cut(operation_id),
 attempt_id TEXT NOT NULL REFERENCES ct_attempt(attempt_id),
 control_state_id TEXT NOT NULL REFERENCES ct_state(change_id),
 selection_digest TEXT NOT NULL, selection_body BLOB NOT NULL CHECK(length(selection_body)>0),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 FOREIGN KEY(change_id) REFERENCES cu_authorization(change_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(control_state_id IS change_id)
) STRICT;
CREATE TABLE cu_effective_member(
 change_id TEXT NOT NULL REFERENCES ct_change(change_id), permit_id TEXT NOT NULL REFERENCES ci_issue(permit_id),
 disposition TEXT NOT NULL CHECK(disposition IN ('not_sent','in_flight','unknown')),
 PRIMARY KEY(change_id,permit_id),
 FOREIGN KEY(change_id) REFERENCES cu_effective(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cu_revocation(
 kind TEXT NOT NULL CHECK(kind IN ('ack','retirement')), object_id TEXT NOT NULL,
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(kind,object_id)
) STRICT;
CREATE TABLE cu_protection(
 kind TEXT NOT NULL, object_id TEXT NOT NULL, device_id TEXT NOT NULL, exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 PRIMARY KEY(kind,object_id,exit_id), FOREIGN KEY(kind,object_id) REFERENCES cu_revocation(kind,object_id)
) STRICT;
-- 只有当前仍可靠且已封存的资源核销可以省略历史许可，撤回或迟到强事实使其重新纳入。
CREATE VIEW cu_issue AS
 SELECT i.*,e.device_id,p.exit_id,a.command_id FROM ci_issue i JOIN ce_permit p USING(permit_id)
 JOIN ce_attempt a USING(attempt_id) JOIN ce_exit e USING(exit_id)
 UNION ALL SELECT i.*,e.device_id,p.exit_id,c.command_id FROM ci_issue i JOIN ci_cancel_transmission p USING(permit_id)
 JOIN cv_cancel c USING(cancellation_id) JOIN ce_exit e USING(exit_id);
CREATE VIEW cu_open_issue AS SELECT p.* FROM cu_issue p WHERE NOT EXISTS(
 SELECT 1 FROM (SELECT release_id,permit_id FROM cr_release_member UNION SELECT release_id,permit_id FROM cx_release_member) m
 JOIN cr_release_commit k USING(release_id) WHERE m.permit_id=p.permit_id
 AND NOT EXISTS(SELECT 1 FROM cr_invalid_release x WHERE x.release_id=m.release_id)
 AND NOT EXISTS(SELECT 1 FROM cr_release_invalidation x WHERE x.release_id=m.release_id));
CREATE VIEW cu_expected_member AS SELECT c.operation_id,p.exit_id,p.permit_id FROM cu_cut c JOIN cu_open_issue p USING(device_id);
CREATE VIEW cu_expected_target AS
 SELECT c.operation_id,e.exit_id FROM cu_cut c JOIN ce_exit e USING(device_id);
CREATE VIEW cu_current_disposition AS
 SELECT permit_id,disposition FROM ce_current_disposition UNION ALL SELECT permit_id,disposition FROM cf_disposition;
CREATE VIEW pd_base_cu_valid_effective AS SELECT e.* FROM cu_effective e JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM cu_selection s JOIN cu_revocation r
 ON (r.kind='ack' AND r.object_id=s.barrier_id) OR (r.kind='retirement' AND r.object_id=s.retirement_exit_id)
 WHERE s.change_id=e.change_id);
CREATE TRIGGER cu_cut_binding BEFORE INSERT ON cu_cut BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_operation o JOIN ct_change c USING(change_id)
  WHERE o.operation_id=NEW.operation_id AND c.change_id=NEW.change_id AND c.device_id=NEW.device_id
  AND c.kind IN ('accept','acquire','release') AND NOT EXISTS(SELECT 1 FROM ct_commit WHERE change_id=c.change_id))
  OR NEW.issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  THEN RAISE(ABORT,'control_cut_binding') END;
END;
CREATE TRIGGER cu_control_seal BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND
  (SELECT count(*) FROM cu_cut WHERE change_id=c.change_id)!=(c.kind IN ('accept','acquire','release')))
  THEN RAISE(ABORT,'control_cut_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_cut WHERE change_id=NEW.change_id
  AND issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue))
  THEN RAISE(ABORT,'control_cut_watermark') END;
 SELECT CASE WHEN EXISTS(SELECT operation_id,exit_id FROM cu_expected_target WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id)
  EXCEPT SELECT operation_id,exit_id FROM cu_target WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id))
 OR EXISTS(SELECT operation_id,exit_id FROM cu_target WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id)
  EXCEPT SELECT operation_id,exit_id FROM cu_expected_target WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id))
  THEN RAISE(ABORT,'control_target_set') END;
 SELECT CASE WHEN EXISTS(SELECT operation_id,exit_id,permit_id FROM cu_expected_member WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id)
  EXCEPT SELECT operation_id,exit_id,permit_id FROM cu_member WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id))
 OR EXISTS(SELECT operation_id,exit_id,permit_id FROM cu_member WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id)
  EXCEPT SELECT operation_id,exit_id,permit_id FROM cu_expected_member WHERE operation_id IN (SELECT operation_id FROM cu_cut WHERE change_id=NEW.change_id))
  THEN RAISE(ABORT,'control_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_member m JOIN cu_cut c USING(operation_id) JOIN cu_current_disposition d USING(permit_id)
  WHERE c.change_id=NEW.change_id AND m.entered_known!=(d.disposition='in_flight')) THEN RAISE(ABORT,'control_entered_snapshot') END;
 SELECT CASE WHEN EXISTS(SELECT m.exit_id,i.kind FROM cu_member m JOIN cu_cut c USING(operation_id) JOIN ci_issue i USING(permit_id)
  WHERE c.change_id=NEW.change_id GROUP BY m.operation_id,m.exit_id,i.kind HAVING count(*)>256) THEN RAISE(ABORT,'control_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ce_command x USING(device_id) JOIN cm_latest r USING(command_id)
  WHERE c.change_id=NEW.change_id AND r.phase='queued' AND NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_permit p USING(attempt_id) WHERE a.command_id=x.command_id))
  THEN RAISE(ABORT,'control_queued_not_blocked') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_queued q JOIN cu_cut c USING(operation_id) JOIN cm_revision old ON old.command_id=q.command_id AND old.revision=q.before_revision
  WHERE c.change_id=NEW.change_id AND (old.phase!='queued' OR EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_permit p USING(attempt_id) WHERE a.command_id=q.command_id)
   OR NOT EXISTS(SELECT 1 FROM ce_command x JOIN cm_latest n USING(command_id) WHERE x.command_id=q.command_id AND x.device_id=c.device_id
    AND n.revision=q.blocked_revision AND n.previous_revision=q.before_revision AND n.kind='block' AND n.phase='finished' AND n.outcome='blocked' AND n.effect_status='not_sent' AND n.paused_latched=1)))
  THEN RAISE(ABORT,'control_queued_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_attempt a JOIN cu_target t USING(operation_id) WHERE a.change_id=NEW.change_id
  AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=t.exit_id)
  AND NOT EXISTS(SELECT 1 FROM cu_delivery d WHERE d.attempt_id=a.attempt_id AND d.exit_id=t.exit_id)) THEN RAISE(ABORT,'control_delivery_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND
  (SELECT count(*) FROM cu_effective WHERE change_id=c.change_id)!=(c.kind='effective')) THEN RAISE(ABORT,'control_effective_required') END;
END;
CREATE TRIGGER cu_queued_capture BEFORE INSERT ON cu_queued BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_latest r JOIN ce_command c USING(command_id) JOIN cu_cut t ON t.device_id=c.device_id
  WHERE r.command_id=NEW.command_id AND r.revision=NEW.before_revision AND r.phase='queued' AND t.operation_id=NEW.operation_id)
  THEN RAISE(ABORT,'control_queued_capture') END;
END;
-- 直接从受理writer的同一数据库前态冻结queued集合，不能由调用方省略成员。
CREATE TRIGGER cu_capture_queue AFTER INSERT ON cu_cut BEGIN
 INSERT INTO cu_queued SELECT NEW.operation_id,r.command_id,r.revision,
  printf('%010d%010d',CAST(substr(r.revision,1,10) AS INTEGER)+(substr(r.revision,11,10)='9999999999'),(CAST(substr(r.revision,11,10) AS INTEGER)+1)%10000000000)
 FROM cm_latest r JOIN ce_command c USING(command_id) WHERE c.device_id=NEW.device_id AND r.phase='queued'
 AND NOT EXISTS(SELECT 1 FROM ce_attempt a JOIN ce_permit p USING(attempt_id) WHERE a.command_id=r.command_id);
END;
CREATE TRIGGER cu_delivery_guard BEFORE INSERT ON cu_delivery BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_attempt a JOIN ct_commit k USING(change_id) WHERE a.attempt_id=NEW.attempt_id)
  OR EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.exit_id) THEN RAISE(ABORT,'control_delivery_frozen') END;
END;
CREATE TRIGGER cu_coverage_frozen BEFORE INSERT ON cu_coverage WHEN EXISTS(SELECT 1 FROM cu_ack WHERE barrier_id=NEW.barrier_id)
 BEGIN SELECT RAISE(ABORT,'control_ack_frozen'); END;
CREATE TRIGGER cu_ack_guard BEFORE INSERT ON cu_ack BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_pending_cut) THEN RAISE(ABORT,'pending_cut') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cu_delivery d JOIN ct_attempt a USING(attempt_id) JOIN ct_commit k ON k.change_id=a.change_id
  JOIN ct_operation o ON o.operation_id=d.operation_id JOIN ct_state s ON s.change_id=o.expected_state_id JOIN cu_cut c ON c.operation_id=o.operation_id
  WHERE d.barrier_id=NEW.barrier_id AND s.control_epoch=NEW.control_epoch AND o.target_version=NEW.installed_version
   AND d.target_gate_revision=NEW.gate_revision AND c.issued_revision=NEW.issued_revision AND c.cut_digest=NEW.cut_digest)
  THEN RAISE(ABORT,'control_ack_binding') END;
 SELECT CASE WHEN (SELECT count(*) FROM cu_coverage WHERE barrier_id=NEW.barrier_id)!=(SELECT count(*) FROM cu_member m JOIN cu_delivery d USING(operation_id,exit_id) WHERE d.barrier_id=NEW.barrier_id)
  THEN RAISE(ABORT,'control_ack_incomplete') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_coverage x JOIN cu_member m USING(operation_id,exit_id,permit_id)
  WHERE x.barrier_id=NEW.barrier_id AND m.entered_known=1 AND x.disposition!='in_flight') THEN RAISE(ABORT,'control_ack_downgrade') END;
END;
CREATE TRIGGER cu_ack_invalidation AFTER INSERT ON cu_ack BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT r.release_id,'control_ack',NEW.barrier_id,NULL FROM cr_invalid_release r
 JOIN (SELECT release_id,permit_id FROM cr_release_member UNION SELECT release_id,permit_id FROM cx_release_member) m USING(release_id)
 JOIN cu_coverage c USING(permit_id) WHERE c.barrier_id=NEW.barrier_id AND c.disposition='in_flight';
END;
CREATE TRIGGER cu_effective_guard BEFORE INSERT ON cu_effective BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ce_exit e USING(device_id)
  WHERE c.operation_id=NEW.operation_id AND NOT EXISTS(SELECT 1 FROM cu_target t WHERE t.operation_id=c.operation_id AND t.exit_id=e.exit_id)
   AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id AND NOT EXISTS(SELECT 1 FROM cu_revocation x WHERE x.kind='retirement' AND x.object_id=r.exit_id)))
  THEN RAISE(ABORT,'control_unfenced_new_exit') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_change c JOIN ct_operation o USING(operation_id)
  JOIN ct_current_operation p USING(operation_id) JOIN ct_current_state old ON old.device_id=c.device_id
  JOIN ct_state s ON s.change_id=c.change_id JOIN ct_state expected ON expected.change_id=o.expected_state_id
  JOIN ct_operation_event n ON n.change_id=c.change_id
  WHERE c.change_id=NEW.change_id AND c.kind='effective' AND c.operation_id=NEW.operation_id AND p.attempt_id=NEW.attempt_id
   AND old.pending_operation_id=o.operation_id AND p.state IN ('pending','indeterminate') AND n.state='effective'
   AND old.control_epoch=expected.control_epoch AND old.effective_version=expected.effective_version
   AND old.holder_issuer IS expected.holder_issuer AND old.holder_epoch IS expected.holder_epoch AND old.holder_id IS expected.holder_id
   AND s.effective_version=o.target_version AND s.mode=CASE o.kind WHEN 'release' THEN 'automatic' ELSE 'manual' END
   AND s.holder_issuer IS o.target_issuer AND s.holder_epoch IS o.target_epoch AND s.holder_id IS o.target_id)
  THEN RAISE(ABORT,'control_effective_binding') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cu_authorization a JOIN ct_change c USING(change_id) JOIN ct_operation o ON o.operation_id=a.operation_id
  WHERE a.change_id=NEW.change_id AND a.operation_id=NEW.operation_id AND a.clock_domain=c.clock_domain AND a.descriptor=c.descriptor AND a.issued_tick<=c.now_tick AND c.now_tick<a.expires_tick
   AND a.issuer_id=CASE o.kind WHEN 'release' THEN o.requester_issuer ELSE o.target_issuer END
   AND a.issuer_epoch=CASE o.kind WHEN 'release' THEN o.requester_epoch ELSE o.target_epoch END
   AND a.principal_id=CASE o.kind WHEN 'release' THEN o.requester_id ELSE o.target_id END)
  THEN RAISE(ABORT,'control_effective_authorization') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM cu_target WHERE operation_id=NEW.operation_id EXCEPT SELECT exit_id FROM cu_selection WHERE change_id=NEW.change_id AND operation_id=NEW.operation_id)
  OR EXISTS(SELECT exit_id FROM cu_selection WHERE change_id=NEW.change_id EXCEPT SELECT exit_id FROM cu_target WHERE operation_id=NEW.operation_id)
  THEN RAISE(ABORT,'control_selection_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_selection s WHERE s.change_id=NEW.change_id AND
  (s.operation_id!=NEW.operation_id OR
   (s.barrier_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cu_delivery d JOIN cu_ack k USING(barrier_id)
    WHERE d.barrier_id=s.barrier_id AND d.attempt_id=NEW.attempt_id AND d.operation_id=NEW.operation_id AND d.exit_id=s.exit_id
     AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=s.exit_id))) OR
   EXISTS(SELECT 1 FROM cu_revocation r WHERE (r.kind='ack' AND r.object_id=s.barrier_id) OR (r.kind='retirement' AND r.object_id=s.retirement_exit_id))))
  THEN RAISE(ABORT,'control_selection_invalid') END;
 SELECT CASE WHEN EXISTS(SELECT permit_id FROM cu_member WHERE operation_id=NEW.operation_id EXCEPT SELECT permit_id FROM cu_effective_member WHERE change_id=NEW.change_id)
  OR EXISTS(SELECT permit_id FROM cu_effective_member WHERE change_id=NEW.change_id EXCEPT SELECT permit_id FROM cu_member WHERE operation_id=NEW.operation_id)
  THEN RAISE(ABORT,'control_effective_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_effective_member x JOIN cu_member m USING(permit_id)
  JOIN cu_selection s ON s.change_id=x.change_id AND s.exit_id=m.exit_id
  JOIN cu_current_disposition d ON d.permit_id=m.permit_id LEFT JOIN cu_coverage v ON v.barrier_id=s.barrier_id AND v.permit_id=x.permit_id
  WHERE x.change_id=NEW.change_id AND m.operation_id=NEW.operation_id AND x.disposition!=CASE
   WHEN d.disposition='in_flight' THEN 'in_flight' WHEN s.retirement_exit_id IS NOT NULL THEN 'unknown' ELSE v.disposition END)
  THEN RAISE(ABORT,'control_effective_classification') END;
END;
CREATE TRIGGER cu_revocation_guard BEFORE INSERT ON cu_revocation BEGIN
 SELECT CASE WHEN (NEW.kind='ack' AND NOT EXISTS(SELECT 1 FROM cu_ack WHERE barrier_id=NEW.object_id)) OR
  (NEW.kind='retirement' AND NOT EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=NEW.object_id)) THEN RAISE(ABORT,'control_revocation_source') END;
END;
CREATE TRIGGER cu_revocation_close AFTER INSERT ON cu_revocation BEGIN
 INSERT OR IGNORE INTO cr_release_invalidation
 SELECT DISTINCT m.release_id,'control_ack_revocation',NEW.object_id,NULL
 FROM (SELECT r.release_id,r.permit_id FROM cr_release_member r JOIN ce_settlement s USING(settlement_id) WHERE s.kind='never_sent'
  UNION SELECT r.release_id,r.permit_id FROM cx_release_member r JOIN cf_settlement s USING(settlement_id) WHERE s.kind='never_sent') m
 JOIN cr_release_commit k USING(release_id) JOIN cu_coverage c USING(permit_id)
 WHERE NEW.kind='ack' AND c.barrier_id=NEW.object_id AND c.disposition='not_sent';
 INSERT INTO cu_protection SELECT DISTINCT NEW.kind,NEW.object_id,c.device_id,e.exit_id FROM cu_selection s
 JOIN cu_effective f USING(change_id) JOIN ct_commit k USING(change_id) JOIN cu_cut c ON c.operation_id=f.operation_id JOIN ce_exit e ON e.device_id=c.device_id
 WHERE ((NEW.kind='ack' AND s.barrier_id=NEW.object_id) OR (NEW.kind='retirement' AND s.retirement_exit_id=NEW.object_id))
 AND (NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id) OR EXISTS(
  SELECT 1 FROM cu_revocation r WHERE r.kind='retirement' AND r.object_id=e.exit_id));
END;
CREATE TRIGGER cu_new_exit_close AFTER INSERT ON ce_exit BEGIN
 INSERT OR IGNORE INTO cu_protection SELECT r.kind,r.object_id,NEW.device_id,NEW.exit_id FROM cu_revocation r
 JOIN cu_selection s ON (r.kind='ack' AND r.object_id=s.barrier_id) OR (r.kind='retirement' AND r.object_id=s.retirement_exit_id)
 JOIN cu_effective f USING(change_id) JOIN ct_commit k USING(change_id) JOIN cu_cut c ON c.operation_id=f.operation_id WHERE c.device_id=NEW.device_id;
END;

CREATE TRIGGER cu_effective_recheck BEFORE INSERT ON ct_commit WHEN EXISTS(SELECT 1 FROM ct_change WHERE change_id=NEW.change_id AND kind='effective') BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ce_exit e USING(device_id)
  WHERE c.operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id) AND NOT EXISTS(SELECT 1 FROM cu_target t WHERE t.operation_id=c.operation_id AND t.exit_id=e.exit_id)
   AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id AND NOT EXISTS(SELECT 1 FROM cu_revocation x WHERE x.kind='retirement' AND x.object_id=r.exit_id)))
  THEN RAISE(ABORT,'control_unfenced_new_exit') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_change c JOIN ct_operation o USING(operation_id)
  JOIN ct_current_operation p USING(operation_id) JOIN ct_current_state old ON old.device_id=c.device_id
  JOIN ct_state s ON s.change_id=c.change_id JOIN ct_state expected ON expected.change_id=o.expected_state_id
  JOIN ct_operation_event n ON n.change_id=c.change_id
  WHERE c.change_id=NEW.change_id AND c.kind='effective' AND c.operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id) AND p.attempt_id=(SELECT attempt_id FROM cu_effective WHERE change_id=NEW.change_id)
   AND old.pending_operation_id=o.operation_id AND p.state IN ('pending','indeterminate') AND n.state='effective'
   AND old.control_epoch=expected.control_epoch AND old.effective_version=expected.effective_version
   AND old.holder_issuer IS expected.holder_issuer AND old.holder_epoch IS expected.holder_epoch AND old.holder_id IS expected.holder_id
   AND s.effective_version=o.target_version AND s.mode=CASE o.kind WHEN 'release' THEN 'automatic' ELSE 'manual' END
   AND s.holder_issuer IS o.target_issuer AND s.holder_epoch IS o.target_epoch AND s.holder_id IS o.target_id)
  THEN RAISE(ABORT,'control_effective_binding') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cu_authorization a JOIN ct_change c USING(change_id) JOIN ct_operation o ON o.operation_id=a.operation_id
  WHERE a.change_id=NEW.change_id AND a.operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id) AND a.clock_domain=c.clock_domain AND a.descriptor=c.descriptor AND a.issued_tick<=c.now_tick AND c.now_tick<a.expires_tick
   AND a.issuer_id=CASE o.kind WHEN 'release' THEN o.requester_issuer ELSE o.target_issuer END
   AND a.issuer_epoch=CASE o.kind WHEN 'release' THEN o.requester_epoch ELSE o.target_epoch END
   AND a.principal_id=CASE o.kind WHEN 'release' THEN o.requester_id ELSE o.target_id END)
  THEN RAISE(ABORT,'control_effective_authorization') END;
 SELECT CASE WHEN EXISTS(SELECT exit_id FROM cu_target WHERE operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id) EXCEPT SELECT exit_id FROM cu_selection WHERE change_id=NEW.change_id AND operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id))
  OR EXISTS(SELECT exit_id FROM cu_selection WHERE change_id=NEW.change_id EXCEPT SELECT exit_id FROM cu_target WHERE operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id))
  THEN RAISE(ABORT,'control_selection_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_selection s WHERE s.change_id=NEW.change_id AND
  (s.operation_id!=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id) OR
   (s.barrier_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cu_delivery d JOIN cu_ack k USING(barrier_id)
    WHERE d.barrier_id=s.barrier_id AND d.attempt_id=(SELECT attempt_id FROM cu_effective WHERE change_id=NEW.change_id) AND d.operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id) AND d.exit_id=s.exit_id
     AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=s.exit_id))) OR
   EXISTS(SELECT 1 FROM cu_revocation r WHERE (r.kind='ack' AND r.object_id=s.barrier_id) OR (r.kind='retirement' AND r.object_id=s.retirement_exit_id))))
  THEN RAISE(ABORT,'control_selection_invalid') END;
 SELECT CASE WHEN EXISTS(SELECT permit_id FROM cu_member WHERE operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id) EXCEPT SELECT permit_id FROM cu_effective_member WHERE change_id=NEW.change_id)
  OR EXISTS(SELECT permit_id FROM cu_effective_member WHERE change_id=NEW.change_id EXCEPT SELECT permit_id FROM cu_member WHERE operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id))
  THEN RAISE(ABORT,'control_effective_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_effective_member x JOIN cu_member m USING(permit_id)
  JOIN cu_selection s ON s.change_id=x.change_id AND s.exit_id=m.exit_id
  JOIN cu_current_disposition d ON d.permit_id=m.permit_id LEFT JOIN cu_coverage v ON v.barrier_id=s.barrier_id AND v.permit_id=x.permit_id
  WHERE x.change_id=NEW.change_id AND m.operation_id=(SELECT operation_id FROM cu_effective WHERE change_id=NEW.change_id) AND x.disposition!=CASE
   WHEN d.disposition='in_flight' THEN 'in_flight' WHEN s.retirement_exit_id IS NOT NULL THEN 'unknown' ELSE v.disposition END)
  THEN RAISE(ABORT,'control_effective_classification') END;
END;

CREATE TRIGGER cu_cut_u BEFORE UPDATE ON cu_cut BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_cut_d BEFORE DELETE ON cu_cut BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_target_u BEFORE UPDATE ON cu_target BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_target_d BEFORE DELETE ON cu_target BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_member_u BEFORE UPDATE ON cu_member BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_member_d BEFORE DELETE ON cu_member BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_queued_u BEFORE UPDATE ON cu_queued BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_queued_d BEFORE DELETE ON cu_queued BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_delivery_u BEFORE UPDATE ON cu_delivery BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_delivery_d BEFORE DELETE ON cu_delivery BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_coverage_u BEFORE UPDATE ON cu_coverage BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_coverage_d BEFORE DELETE ON cu_coverage BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_ack_u BEFORE UPDATE ON cu_ack BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_ack_d BEFORE DELETE ON cu_ack BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_authorization_u BEFORE UPDATE ON cu_authorization BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_authorization_d BEFORE DELETE ON cu_authorization BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_selection_u BEFORE UPDATE ON cu_selection BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_selection_d BEFORE DELETE ON cu_selection BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_effective_u BEFORE UPDATE ON cu_effective BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_effective_d BEFORE DELETE ON cu_effective BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_effective_member_u BEFORE UPDATE ON cu_effective_member BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_effective_member_d BEFORE DELETE ON cu_effective_member BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_revocation_u BEFORE UPDATE ON cu_revocation BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_revocation_d BEFORE DELETE ON cu_revocation BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_protection_u BEFORE UPDATE ON cu_protection BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_protection_d BEFORE DELETE ON cu_protection BEGIN SELECT RAISE(ABORT,'immutable_control_fence'); END;

CREATE TRIGGER cu_target_sealed BEFORE INSERT ON cu_target WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ct_commit k USING(change_id) WHERE c.operation_id=NEW.operation_id) BEGIN SELECT RAISE(ABORT,'control_cut_sealed'); END;

CREATE TRIGGER cu_member_sealed BEFORE INSERT ON cu_member WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ct_commit k USING(change_id) WHERE c.operation_id=NEW.operation_id) BEGIN SELECT RAISE(ABORT,'control_cut_sealed'); END;

CREATE TRIGGER cu_queued_sealed BEFORE INSERT ON cu_queued WHEN EXISTS(SELECT 1 FROM cu_cut c JOIN ct_commit k USING(change_id) WHERE c.operation_id=NEW.operation_id) BEGIN SELECT RAISE(ABORT,'control_cut_sealed'); END;

CREATE TRIGGER cu_authorization_sealed BEFORE INSERT ON cu_authorization WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_effective_sealed'); END;

CREATE TRIGGER cu_selection_sealed BEFORE INSERT ON cu_selection WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_effective_sealed'); END;

CREATE TRIGGER cu_effective_sealed BEFORE INSERT ON cu_effective WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_effective_sealed'); END;

CREATE TRIGGER cu_effective_member_sealed BEFORE INSERT ON cu_effective_member WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_effective_sealed'); END;

CREATE TRIGGER cu_ce_permit_gate BEFORE INSERT ON ce_permit WHEN EXISTS(SELECT 1 FROM ce_exit e JOIN ct_current_state s USING(device_id) WHERE e.exit_id=NEW.exit_id) OR EXISTS(SELECT 1 FROM ce_exit e JOIN cu_cut c USING(device_id) WHERE e.exit_id=NEW.exit_id) BEGIN SELECT RAISE(ABORT,'control_gate_not_ready'); END;

CREATE TRIGGER cu_ci_cancel_transmission_gate BEFORE INSERT ON ci_cancel_transmission WHEN EXISTS(SELECT 1 FROM ce_exit e JOIN ct_current_state s USING(device_id) WHERE e.exit_id=NEW.exit_id) OR EXISTS(SELECT 1 FROM ce_exit e JOIN cu_cut c USING(device_id) WHERE e.exit_id=NEW.exit_id) BEGIN SELECT RAISE(ABORT,'control_gate_not_ready'); END;

CREATE TRIGGER cu_ce_transmission_commit_gate BEFORE INSERT ON ce_transmission_commit WHEN EXISTS(SELECT 1 FROM ce_permit p JOIN ce_exit e USING(exit_id) WHERE p.permit_id=NEW.permit_id AND (EXISTS(SELECT 1 FROM ct_current_state s WHERE s.device_id=e.device_id) OR EXISTS(SELECT 1 FROM cu_cut c WHERE c.device_id=e.device_id))) BEGIN SELECT RAISE(ABORT,'control_gate_not_ready'); END;

CREATE TRIGGER cu_ci_cancel_commit_gate BEFORE INSERT ON ci_cancel_commit WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission p JOIN ce_exit e USING(exit_id) WHERE p.permit_id=NEW.permit_id AND (EXISTS(SELECT 1 FROM ct_current_state s WHERE s.device_id=e.device_id) OR EXISTS(SELECT 1 FROM cu_cut c WHERE c.device_id=e.device_id))) BEGIN SELECT RAISE(ABORT,'control_gate_not_ready'); END;

-- 开放持久化候选。原件BODY及外部权威由可信提供者验证，不是产品迁移。
CREATE TABLE go_hazard(
 device_id TEXT NOT NULL, revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('release','validation','control','command','report','cancel_report','close','open_revocation','recovery','exit','ownership','gate_fence','scope')),
 source_id TEXT NOT NULL,recovery_id TEXT REFERENCES go_recovery_commit(recovery_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((source_kind='recovery' AND recovery_id IS source_id) OR (source_kind!='recovery' AND recovery_id IS NULL)),
 PRIMARY KEY(device_id,revision), UNIQUE(device_id,source_kind,source_id)
) STRICT;
CREATE TRIGGER go_hazard_successor BEFORE INSERT ON go_hazard BEGIN
 SELECT CASE WHEN NEW.revision!=printf('%010d%010d',CAST(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=NEW.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=NEW.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=NEW.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000) OR NEW.revision='00000000000000000000'
 OR EXISTS(SELECT 1 FROM go_hazard WHERE device_id=NEW.device_id AND revision='99999999999999999999')
 THEN RAISE(ABORT,'hazard_successor') END;
END;
CREATE VIEW go_authority AS SELECT s.*,c.device_id FROM ct_state s JOIN ct_change c USING(change_id) JOIN ct_commit k USING(change_id)
 WHERE c.kind NOT IN ('ready','gate_protect','scope_commit') AND NOT EXISTS(SELECT 1 FROM ct_state n JOIN ct_change nc ON nc.change_id=n.change_id JOIN ct_commit nk ON nk.change_id=n.change_id
 WHERE nc.device_id=c.device_id AND nc.kind NOT IN ('ready','gate_protect','scope_commit') AND n.record_revision>s.record_revision);
CREATE TABLE go_snapshot(
 snapshot_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 authority_state_id TEXT NOT NULL REFERENCES ct_state(change_id), control_state_id TEXT NOT NULL REFERENCES ct_state(change_id),
 safety_revision TEXT NOT NULL CHECK(length(safety_revision)=20 AND safety_revision NOT GLOB '*[^0-9]*'),
 authorization_ref TEXT NOT NULL CHECK(length(authorization_ref)>0), resource_ref TEXT NOT NULL CHECK(length(resource_ref)>0),
 run_snapshot_ref TEXT NOT NULL, command_snapshot_ref TEXT NOT NULL, time_snapshot_ref TEXT NOT NULL,
 sampled_tick TEXT NOT NULL CHECK(length(sampled_tick)=20 AND sampled_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)>0),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0), CHECK(sampled_tick<expires_tick),
 FOREIGN KEY(snapshot_id) REFERENCES go_snapshot_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE go_hold(
 snapshot_id TEXT NOT NULL REFERENCES go_snapshot(snapshot_id), hold_id TEXT NOT NULL REFERENCES cr_hold(hold_id),
 authority_state_id TEXT NOT NULL REFERENCES ct_state(change_id), owner_ref TEXT NOT NULL, owner_revision TEXT NOT NULL, owner_digest TEXT NOT NULL,
 classification TEXT NOT NULL CHECK(classification IN ('active','unknown','failed_unresolved','orphaned','proof_revoked')),
 PRIMARY KEY(snapshot_id,hold_id),
 FOREIGN KEY(owner_ref,owner_revision,owner_digest) REFERENCES ow_ownership(ownership_id,revision,ownership_digest)
) STRICT;
CREATE TABLE go_snapshot_commit(
 snapshot_id TEXT PRIMARY KEY REFERENCES go_snapshot(snapshot_id), audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW go_current_snapshot AS SELECT s.* FROM go_snapshot s JOIN go_snapshot_commit k USING(snapshot_id)
 WHERE NOT EXISTS(SELECT 1 FROM go_snapshot n JOIN go_snapshot_commit nk ON nk.snapshot_id=n.snapshot_id WHERE n.device_id=s.device_id AND n.sampled_tick>s.sampled_tick);
CREATE VIEW go_valid_snapshot AS SELECT s.* FROM go_current_snapshot s
 JOIN go_authority a ON a.change_id=s.authority_state_id AND a.device_id=s.device_id
 JOIN ce_exit e ON e.exit_id=s.exit_id AND e.device_id=s.device_id
 WHERE a.pending_operation_id IS NULL AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=s.exit_id)
 AND s.safety_revision=coalesce((SELECT max(revision) FROM go_hazard h WHERE h.device_id=s.device_id),'00000000000000000000')
 AND NOT EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=s.device_id)
 AND NOT EXISTS(SELECT hold_id FROM cr_risk_hold h WHERE h.device_id=s.device_id EXCEPT SELECT hold_id FROM go_hold WHERE snapshot_id=s.snapshot_id)
 AND NOT EXISTS(SELECT hold_id FROM go_hold WHERE snapshot_id=s.snapshot_id EXCEPT SELECT hold_id FROM cr_risk_hold h WHERE h.device_id=s.device_id)
 AND NOT EXISTS(SELECT 1 FROM go_hold h JOIN cr_hold r USING(hold_id) LEFT JOIN cm_latest c ON c.command_id=r.command_id
 WHERE h.snapshot_id=s.snapshot_id AND (NOT EXISTS(SELECT 1 FROM ow_current_owner o WHERE o.ownership_id=h.owner_ref AND o.hold_id=h.hold_id) OR h.authority_state_id!=s.authority_state_id OR h.classification!='active' OR c.command_id IS NULL OR c.resource_status='unresolved' OR c.outcome='unknown'));
CREATE TRIGGER go_snapshot_seal BEFORE INSERT ON go_snapshot_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_snapshot s JOIN go_authority a ON a.change_id=s.authority_state_id
 JOIN ct_current_state c ON c.change_id=s.control_state_id JOIN ct_change cc ON cc.change_id=c.change_id JOIN ce_exit e ON e.exit_id=s.exit_id
 WHERE s.snapshot_id=NEW.snapshot_id AND s.device_id=a.device_id AND s.device_id=c.device_id AND s.device_id=e.device_id
 AND cc.clock_domain=e.clock_domain_id AND cc.descriptor=e.descriptor_digest AND cc.now_tick<=s.sampled_tick
 AND s.safety_revision=coalesce((SELECT max(revision) FROM go_hazard h WHERE h.device_id=s.device_id),'00000000000000000000')
 AND NOT EXISTS(SELECT 1 FROM go_current_snapshot p WHERE p.device_id=s.device_id AND p.sampled_tick>=s.sampled_tick)) THEN RAISE(ABORT,'open_snapshot_binding') END;
 SELECT CASE WHEN EXISTS(SELECT h.hold_id FROM cr_risk_hold h JOIN go_snapshot s USING(device_id) WHERE s.snapshot_id=NEW.snapshot_id
 EXCEPT SELECT hold_id FROM go_hold WHERE snapshot_id=NEW.snapshot_id)
 OR EXISTS(SELECT hold_id FROM go_hold WHERE snapshot_id=NEW.snapshot_id EXCEPT SELECT h.hold_id FROM cr_risk_hold h JOIN go_snapshot s USING(device_id) WHERE s.snapshot_id=NEW.snapshot_id)
 THEN RAISE(ABORT,'open_hold_set') END;
END;
CREATE TABLE go_gate(
 gate_id TEXT PRIMARY KEY, exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id), previous_id TEXT REFERENCES go_gate(gate_id),
 record_revision TEXT NOT NULL CHECK(length(record_revision)=20 AND record_revision NOT GLOB '*[^0-9]*'),
 gate_revision TEXT NOT NULL CHECK(length(gate_revision)=20 AND gate_revision NOT GLOB '*[^0-9]*'),
 gate_token TEXT NOT NULL CHECK(length(gate_token)>0), barrier_id TEXT NOT NULL, control_barrier_id TEXT REFERENCES cu_ack(barrier_id),
 renewal_id TEXT REFERENCES gf_commit(request_id) DEFERRABLE INITIALLY DEFERRED,
 phase TEXT NOT NULL CHECK(phase IN ('fenced','ready','scoped')), ready_id TEXT UNIQUE REFERENCES go_ready(ready_id) DEFERRABLE INITIALLY DEFERRED,
 scope_commit_id TEXT UNIQUE REFERENCES gs_scope_commit(commit_id) DEFERRABLE INITIALLY DEFERRED,
 lease_until_tick TEXT NOT NULL CHECK(length(lease_until_tick)=20 AND lease_until_tick NOT GLOB '*[^0-9]*'),
 record_digest TEXT NOT NULL CHECK(length(record_digest)>0), record_body BLOB NOT NULL CHECK(length(record_body)>0),
 UNIQUE(exit_id,record_revision), CHECK((phase='ready')=(ready_id IS NOT NULL)), CHECK((phase='scoped')=(scope_commit_id IS NOT NULL)),
 CHECK((control_barrier_id IS barrier_id AND renewal_id IS NULL) OR (renewal_id IS barrier_id AND control_barrier_id IS NULL))
) STRICT;
CREATE VIEW go_current_gate AS SELECT g.* FROM go_gate g WHERE NOT EXISTS(SELECT 1 FROM go_gate n WHERE n.exit_id=g.exit_id AND n.record_revision>g.record_revision);
CREATE TRIGGER go_gate_guard BEFORE INSERT ON go_gate BEGIN
 SELECT CASE WHEN NOT ((NEW.previous_id IS NULL AND NEW.record_revision='00000000000000000001' AND NEW.phase='fenced'
 AND NOT EXISTS(SELECT 1 FROM go_gate WHERE exit_id=NEW.exit_id)) OR EXISTS(SELECT 1 FROM go_current_gate p WHERE p.gate_id=NEW.previous_id
 AND p.exit_id=NEW.exit_id AND p.record_revision<'99999999999999999999' AND NEW.record_revision=printf('%010d%010d',CAST(substr(p.record_revision,1,10) AS INTEGER)+(substr(p.record_revision,11,10)='9999999999'),(CAST(substr(p.record_revision,11,10) AS INTEGER)+1)%10000000000)
 AND NEW.record_digest!=p.record_digest AND ((NEW.phase IN ('ready','scoped') AND p.phase='fenced' AND NEW.gate_revision=p.gate_revision
 AND NEW.gate_token=p.gate_token AND NEW.barrier_id=p.barrier_id AND NEW.lease_until_tick=p.lease_until_tick)
 OR (NEW.phase='fenced' AND NEW.gate_revision>p.gate_revision AND NEW.gate_token!=p.gate_token)))) THEN RAISE(ABORT,'open_gate_transition') END;
 SELECT CASE WHEN NEW.control_barrier_id IS NOT NULL AND (NOT EXISTS(
 SELECT 1 FROM cu_ack a JOIN cu_delivery d USING(barrier_id) WHERE a.barrier_id=NEW.control_barrier_id
 AND d.exit_id=NEW.exit_id AND a.gate_revision=NEW.gate_revision)
 OR (NEW.phase='fenced' AND EXISTS(SELECT 1 FROM go_gate p WHERE p.phase='fenced' AND p.control_barrier_id=NEW.control_barrier_id)))
 THEN RAISE(ABORT,'open_gate_barrier') END;
END;
CREATE TABLE go_plan(
 plan_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES go_snapshot_commit(snapshot_id),
 before_gate_id TEXT NOT NULL UNIQUE REFERENCES go_gate(gate_id), before_control_id TEXT NOT NULL REFERENCES ct_state(change_id),
 basis_kind TEXT NOT NULL CHECK(basis_kind IN ('activation','resource_recovery','gate_recovery','scope')),
 scope_assessment_id TEXT REFERENCES gs_assessment_commit(assessment_id),
 activation_id TEXT REFERENCES cu_effective(change_id), resource_recovery_id TEXT REFERENCES cr_recovery_commit(recovery_id),
 gate_recovery_id TEXT UNIQUE REFERENCES go_recovery_commit(recovery_id),
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 plan_digest TEXT NOT NULL, proposal_digest TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)>0),
 CHECK(selected_tick<expires_tick),
 CHECK((basis_kind='scope')=(scope_assessment_id IS NOT NULL)),
 CHECK((basis_kind='scope' AND activation_id IS NULL AND resource_recovery_id IS NULL AND gate_recovery_id IS NULL) OR (basis_kind='activation' AND activation_id IS NOT NULL AND resource_recovery_id IS NULL AND gate_recovery_id IS NULL)
 OR (basis_kind='resource_recovery' AND activation_id IS NULL AND resource_recovery_id IS NOT NULL AND gate_recovery_id IS NOT NULL)
 OR (basis_kind='gate_recovery' AND activation_id IS NULL AND resource_recovery_id IS NULL AND gate_recovery_id IS NOT NULL)),
 FOREIGN KEY(plan_id) REFERENCES go_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE go_plan_commit(plan_id TEXT PRIMARY KEY REFERENCES go_plan(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)) STRICT;
CREATE VIEW go_ordinary_plan AS SELECT p.*,s.device_id,s.exit_id,s.authority_state_id,s.safety_revision FROM go_plan p
 JOIN go_plan_commit k USING(plan_id) JOIN go_valid_snapshot s USING(snapshot_id)
 JOIN ct_current_state c ON c.change_id=p.before_control_id AND c.change_id=s.control_state_id
 JOIN go_current_gate g ON g.gate_id=p.before_gate_id AND g.exit_id=s.exit_id
 WHERE (g.renewal_id IS NULL OR EXISTS(SELECT 1 FROM gf_valid_fence f WHERE f.request_id=g.renewal_id)) AND c.pending_operation_id IS NULL AND g.phase='fenced' AND c.gate_state!='ready'
 AND s.sampled_tick<=p.selected_tick AND p.expires_tick<=s.expires_tick AND p.expires_tick<=g.lease_until_tick
 AND ((p.basis_kind='activation' AND EXISTS(SELECT 1 FROM cu_valid_effective e WHERE e.change_id=p.activation_id AND e.control_state_id=c.change_id)
  AND NOT EXISTS(SELECT 1 FROM go_close x WHERE x.device_id=s.device_id)) OR
 (p.basis_kind!='activation' AND EXISTS(SELECT 1 FROM go_valid_recovery r WHERE r.recovery_id=p.gate_recovery_id AND r.snapshot_id=p.snapshot_id)
  AND (p.resource_recovery_id IS NULL OR EXISTS(SELECT 1 FROM cr_recovery r JOIN cr_valid_validation v USING(validation_id) WHERE r.recovery_id=p.resource_recovery_id AND r.device_id=s.device_id))));
CREATE TRIGGER go_plan_seal AFTER INSERT ON go_plan_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_valid_plan WHERE plan_id=NEW.plan_id) THEN RAISE(ABORT,'open_plan_invalid') END;
END;
CREATE TABLE go_dispatch(
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 dispatch_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL UNIQUE REFERENCES go_plan_commit(plan_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),message_id TEXT NOT NULL,
 outbound_seq TEXT NOT NULL CHECK(length(outbound_seq)=20 AND outbound_seq NOT GLOB '*[^0-9]*'),
 reserved_tick TEXT NOT NULL CHECK(length(reserved_tick)=20 AND reserved_tick NOT GLOB '*[^0-9]*'),
 frame_digest TEXT NOT NULL, frame_body BLOB NOT NULL CHECK(length(frame_body)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(exit_id,message_id),UNIQUE(exit_id,outbound_seq)
) STRICT;
CREATE TRIGGER go_dispatch_guard BEFORE INSERT ON go_dispatch BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_valid_plan p WHERE p.plan_id=NEW.plan_id AND p.exit_id=NEW.exit_id
 AND p.selected_tick<=NEW.reserved_tick AND NEW.reserved_tick<p.expires_tick) THEN RAISE(ABORT,'open_dispatch_invalid') END;
END;
CREATE TABLE go_evidence(
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 evidence_id TEXT PRIMARY KEY,dispatch_id TEXT NOT NULL UNIQUE REFERENCES go_dispatch(dispatch_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),message_id TEXT NOT NULL,reply_to TEXT NOT NULL,
 inbound_seq TEXT NOT NULL CHECK(length(inbound_seq)=20 AND inbound_seq NOT GLOB '*[^0-9]*'),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 gate_token TEXT NOT NULL,gate_revision TEXT NOT NULL,
 run_snapshot_ref TEXT NOT NULL,command_snapshot_ref TEXT NOT NULL,time_snapshot_ref TEXT NOT NULL,
 scope_access_id TEXT REFERENCES gs_access(access_id), scope_access_revision TEXT, scope_access_digest TEXT,
 observer_ref TEXT NOT NULL CHECK(length(observer_ref)>0),evidence_digest TEXT NOT NULL,
 frame_body BLOB NOT NULL CHECK(length(frame_body)>0),validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),UNIQUE(exit_id,message_id),UNIQUE(exit_id,inbound_seq)
) STRICT;
CREATE TRIGGER go_evidence_guard BEFORE INSERT ON go_evidence BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_dispatch d JOIN go_plan p USING(plan_id) JOIN go_snapshot s USING(snapshot_id)
 JOIN go_gate g ON g.gate_id=p.before_gate_id WHERE d.dispatch_id=NEW.dispatch_id AND d.exit_id=NEW.exit_id
 AND d.message_id=NEW.reply_to AND d.reserved_tick<=NEW.received_tick AND NEW.gate_token=g.gate_token AND NEW.gate_revision=g.gate_revision
 AND NEW.run_snapshot_ref=s.run_snapshot_ref AND NEW.command_snapshot_ref=s.command_snapshot_ref AND NEW.time_snapshot_ref=s.time_snapshot_ref)
 THEN RAISE(ABORT,'open_evidence_binding') END;
END;
CREATE TABLE go_ready(
 ready_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL UNIQUE REFERENCES go_plan_commit(plan_id),
 evidence_id TEXT NOT NULL UNIQUE REFERENCES go_evidence(evidence_id),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_state(change_id),after_gate_id TEXT NOT NULL UNIQUE REFERENCES go_gate(gate_id) DEFERRABLE INITIALLY DEFERRED,
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 ready_digest TEXT NOT NULL,transition_digest TEXT NOT NULL,transition_body BLOB NOT NULL CHECK(length(transition_body)>0),
 FOREIGN KEY(change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER go_ready_pair BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_change p ON p.change_id=c.previous_id
 WHERE c.change_id=NEW.change_id AND c.kind IN ('ready','gate_protect','scope_commit') AND
 (c.clock_domain!=p.clock_domain OR c.descriptor!=p.descriptor OR c.now_tick<p.now_tick)) THEN RAISE(ABORT,'open_clock_order') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND c.kind='gate_protect'
 AND NOT EXISTS(SELECT 1 FROM go_close x WHERE x.protection_change_id=c.change_id AND x.device_id=c.device_id)) THEN RAISE(ABORT,'open_close_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ce_exit e USING(device_id) WHERE c.change_id=NEW.change_id AND c.kind='gate_protect'
 AND (NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=e.exit_id) OR EXISTS(SELECT 1 FROM cu_revocation v WHERE v.kind='retirement' AND v.object_id=e.exit_id))
 AND NOT EXISTS(SELECT 1 FROM go_close x WHERE x.protection_change_id=c.change_id AND x.exit_id=e.exit_id)) THEN RAISE(ABORT,'open_close_target_set') END;
 SELECT CASE WHEN (SELECT count(*) FROM go_ready WHERE change_id=NEW.change_id)!=(SELECT kind='ready' FROM ct_change WHERE change_id=NEW.change_id)
 THEN RAISE(ABORT,'open_ready_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_ready r WHERE r.change_id=NEW.change_id AND NOT EXISTS(
 SELECT 1 FROM go_plan p JOIN go_snapshot s USING(snapshot_id) JOIN go_valid_snapshot v USING(snapshot_id)
 JOIN ct_current_state old ON old.change_id=p.before_control_id JOIN ct_change c ON c.change_id=r.change_id
 JOIN ct_state n ON n.change_id=r.change_id JOIN go_evidence e ON e.evidence_id=r.evidence_id JOIN go_dispatch d ON d.dispatch_id=e.dispatch_id
 JOIN go_gate g ON g.gate_id=r.after_gate_id JOIN go_gate b ON b.gate_id=p.before_gate_id
 WHERE p.plan_id=r.plan_id AND d.plan_id=p.plan_id AND s.control_state_id=old.change_id AND g.ready_id=r.ready_id
 AND g.previous_id=b.gate_id AND g.phase='ready' AND g.exit_id=s.exit_id AND c.device_id=s.device_id
 AND n.record_digest!=old.record_digest AND e.received_tick<=r.committed_tick AND r.committed_tick=c.now_tick
 AND c.now_tick<p.expires_tick AND c.now_tick<v.expires_tick
 AND NOT EXISTS(SELECT 1 FROM go_gate z WHERE z.exit_id=g.exit_id AND z.record_revision>g.record_revision)
 AND ((p.basis_kind='activation' AND EXISTS(SELECT 1 FROM cu_valid_effective f WHERE f.change_id=p.activation_id AND f.control_state_id=old.change_id)
  AND NOT EXISTS(SELECT 1 FROM go_close x WHERE x.device_id=s.device_id)) OR
 (p.basis_kind!='activation' AND EXISTS(SELECT 1 FROM go_valid_recovery q WHERE q.recovery_id=p.gate_recovery_id AND q.snapshot_id=p.snapshot_id)))))
 THEN RAISE(ABORT,'open_ready_binding') END;
END;
CREATE VIEW ij_base_go_ready_candidate AS SELECT r.*,s.device_id,s.exit_id,p.snapshot_id,p.expires_tick FROM go_ready r JOIN ct_commit k USING(change_id)
 JOIN go_plan p USING(plan_id) JOIN go_snapshot original USING(snapshot_id)
 JOIN go_valid_snapshot s ON s.device_id=original.device_id AND s.exit_id=original.exit_id
 AND s.authority_state_id=original.authority_state_id AND s.safety_revision=original.safety_revision
 AND s.authorization_ref=original.authorization_ref AND s.run_snapshot_ref=original.run_snapshot_ref
 AND s.command_snapshot_ref=original.command_snapshot_ref AND s.time_snapshot_ref=original.time_snapshot_ref
 JOIN ct_current_state c ON c.device_id=s.device_id AND c.gate_state='ready' AND c.pending_operation_id IS NULL
 JOIN go_current_gate g ON g.gate_id=r.after_gate_id
 WHERE NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='open_ack' AND v.object_id=r.evidence_id)
 AND NOT EXISTS(SELECT 1 FROM go_latest_close x WHERE x.device_id=s.device_id AND NOT EXISTS(
  SELECT 1 FROM go_recovery_target t JOIN go_recovery_commit rk USING(recovery_id) JOIN go_recovery rc USING(recovery_id)
  WHERE t.close_id=x.close_id AND rc.snapshot_id=original.snapshot_id AND NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=t.ack_id)));
-- 这是未包含当前tick的候选视图；调用者必须重新核期限和完整发送Guard，不是发送许可。
CREATE TABLE go_close(
 prepare_cut_id TEXT NOT NULL UNIQUE REFERENCES pd_cut(cut_id) DEFERRABLE INITIALLY DEFERRED,
 close_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'),
 protection_change_id TEXT NOT NULL REFERENCES ct_change(change_id),
 gate_id TEXT REFERENCES go_gate(gate_id),reason_ref TEXT NOT NULL CHECK(length(reason_ref)>0),
 body BLOB NOT NULL CHECK(length(body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(exit_id,revision),UNIQUE(close_id,exit_id),FOREIGN KEY(protection_change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW go_latest_close AS SELECT x.* FROM go_close x WHERE NOT EXISTS(SELECT 1 FROM go_close n WHERE n.exit_id=x.exit_id AND n.revision>x.revision);
CREATE TRIGGER go_close_binding BEFORE INSERT ON go_close BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_exit e JOIN ct_change c ON c.change_id=NEW.protection_change_id
 WHERE e.exit_id=NEW.exit_id AND e.device_id=NEW.device_id AND c.device_id=NEW.device_id AND c.kind='gate_protect'
 AND ((NEW.gate_id IS NULL AND NOT EXISTS(SELECT 1 FROM go_gate g WHERE g.exit_id=NEW.exit_id)) OR
 EXISTS(SELECT 1 FROM go_current_gate g WHERE g.gate_id=NEW.gate_id AND g.exit_id=NEW.exit_id))
 AND NOT EXISTS(SELECT 1 FROM ct_commit WHERE change_id=c.change_id)) OR NEW.revision!=printf('%010d%010d',CAST(substr(coalesce((SELECT max(revision) FROM go_close WHERE exit_id=NEW.exit_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(revision) FROM go_close WHERE exit_id=NEW.exit_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(revision) FROM go_close WHERE exit_id=NEW.exit_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000)
 THEN RAISE(ABORT,'open_close_binding') END;
END;
CREATE TABLE go_exit_obligation(
 exit_id TEXT PRIMARY KEY REFERENCES ce_exit(exit_id),close_id TEXT NOT NULL UNIQUE,
 FOREIGN KEY(close_id,exit_id) REFERENCES go_close(close_id,exit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER go_exit_registration AFTER INSERT ON ce_exit
 WHEN EXISTS(SELECT 1 FROM ct_current_state s WHERE s.device_id=NEW.device_id) BEGIN
 INSERT INTO go_exit_obligation VALUES(NEW.exit_id,'registration.'||NEW.exit_id);
END;
CREATE TABLE go_close_ack(
 ack_id TEXT PRIMARY KEY,close_id TEXT NOT NULL UNIQUE REFERENCES go_close(close_id),exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 evidence_digest TEXT NOT NULL,observer_ref TEXT NOT NULL CHECK(length(observer_ref)>0),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 body BLOB NOT NULL CHECK(length(body)>0),validation_body BLOB NOT NULL CHECK(length(validation_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER go_close_ack_binding BEFORE INSERT ON go_close_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_close x JOIN ct_change c ON c.change_id=x.protection_change_id
 WHERE x.close_id=NEW.close_id AND x.exit_id=NEW.exit_id AND c.now_tick<=NEW.received_tick)
 THEN RAISE(ABORT,'open_close_ack_binding') END;
END;
CREATE TABLE go_recovery(
 recovery_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,snapshot_id TEXT NOT NULL UNIQUE REFERENCES go_snapshot_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED,
 now_tick TEXT NOT NULL CHECK(length(now_tick)=20 AND now_tick NOT GLOB '*[^0-9]*'),
 recovery_digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0),provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),
 FOREIGN KEY(recovery_id) REFERENCES go_recovery_commit(recovery_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE go_recovery_target(
 recovery_id TEXT NOT NULL REFERENCES go_recovery(recovery_id),close_id TEXT NOT NULL REFERENCES go_close(close_id),
 ack_id TEXT NOT NULL UNIQUE REFERENCES go_close_ack(ack_id),PRIMARY KEY(recovery_id,close_id)
) STRICT;
CREATE TABLE go_recovery_commit(
 recovery_id TEXT PRIMARY KEY REFERENCES go_recovery(recovery_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE VIEW pd_base_go_valid_recovery AS SELECT r.* FROM go_recovery r JOIN go_recovery_commit k USING(recovery_id)
 JOIN go_valid_snapshot s USING(snapshot_id)
 WHERE NOT EXISTS(SELECT 1 FROM ce_exit e WHERE e.device_id=s.device_id
 AND (NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=e.exit_id) OR EXISTS(SELECT 1 FROM cu_revocation v WHERE v.kind='retirement' AND v.object_id=e.exit_id))
 AND NOT EXISTS(SELECT 1 FROM go_latest_close x WHERE x.exit_id=e.exit_id))
 AND NOT EXISTS(SELECT close_id FROM go_latest_close x WHERE x.device_id=s.device_id EXCEPT SELECT close_id FROM go_recovery_target WHERE recovery_id=r.recovery_id)
 AND NOT EXISTS(SELECT close_id FROM go_recovery_target WHERE recovery_id=r.recovery_id EXCEPT SELECT close_id FROM go_latest_close x WHERE x.device_id=s.device_id)
 AND NOT EXISTS(SELECT 1 FROM go_recovery_target t JOIN go_close_ack a USING(ack_id) WHERE t.recovery_id=r.recovery_id AND (a.close_id!=t.close_id
 OR EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=a.ack_id)));
CREATE TRIGGER go_recovery_seal AFTER INSERT ON go_recovery_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_valid_recovery r JOIN go_snapshot s USING(snapshot_id) WHERE r.recovery_id=NEW.recovery_id
 AND s.device_id=r.device_id AND s.sampled_tick<=r.now_tick AND r.now_tick<s.expires_tick
 AND EXISTS(SELECT 1 FROM go_hazard h WHERE h.source_kind='recovery' AND h.recovery_id=r.recovery_id AND h.device_id=s.device_id AND h.revision=s.safety_revision)
 AND EXISTS(SELECT 1 FROM go_recovery_target t WHERE t.recovery_id=r.recovery_id))
 OR EXISTS(SELECT 1 FROM go_recovery_target t JOIN go_close x USING(close_id) JOIN go_close_ack a USING(ack_id)
 JOIN go_recovery r USING(recovery_id) JOIN go_snapshot s USING(snapshot_id) WHERE t.recovery_id=NEW.recovery_id AND (x.device_id!=s.device_id OR a.received_tick>r.now_tick))
 THEN RAISE(ABORT,'open_recovery_incomplete') END;
END;
CREATE TABLE go_revocation(
 kind TEXT NOT NULL CHECK(kind IN ('open_ack','close_ack')),object_id TEXT NOT NULL,
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),PRIMARY KEY(kind,object_id)
) STRICT;
CREATE TRIGGER go_revocation_binding BEFORE INSERT ON go_revocation BEGIN
 SELECT CASE WHEN (NEW.kind='open_ack' AND NOT EXISTS(SELECT 1 FROM go_evidence WHERE evidence_id=NEW.object_id))
 OR (NEW.kind='close_ack' AND NOT EXISTS(SELECT 1 FROM go_close_ack WHERE ack_id=NEW.object_id)) THEN RAISE(ABORT,'open_revocation_binding') END;
END;

CREATE TRIGGER go_cr_release_invalidation_hazard AFTER INSERT ON cr_release_invalidation BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'release',NEW.release_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT c.device_id FROM cr_release r JOIN ce_command c USING(command_id) WHERE r.release_id=NEW.release_id) d;
END;

CREATE TRIGGER go_cr_validation_revocation_hazard AFTER INSERT ON cr_validation_revocation BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'validation',NEW.validation_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT device_id FROM cr_validation WHERE validation_id=NEW.validation_id) d;
END;

CREATE TRIGGER go_cu_revocation_hazard AFTER INSERT ON cu_revocation BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'control',NEW.kind||':'||NEW.object_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT DISTINCT c.device_id FROM cu_selection s JOIN cu_effective f USING(change_id) JOIN ct_change c USING(change_id) WHERE (NEW.kind='ack' AND s.barrier_id=NEW.object_id) OR (NEW.kind='retirement' AND s.retirement_exit_id=NEW.object_id)) d;
END;

CREATE TRIGGER go_cm_commit_hazard AFTER INSERT ON cm_commit BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'command',NEW.operation_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT c.device_id FROM cm_revision r JOIN ce_command c USING(command_id) WHERE r.operation_id=NEW.operation_id AND (r.resource_status='unresolved' OR r.outcome='unknown')) d;
END;

CREATE TRIGGER go_ce_report_hazard AFTER INSERT ON ce_report BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'report',NEW.report_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT e.device_id FROM ce_permit p JOIN ce_exit e USING(exit_id) WHERE p.permit_id=NEW.permit_id AND NEW.disposition='unknown') d;
END;

CREATE TRIGGER go_cf_report_hazard AFTER INSERT ON cf_report BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'cancel_report',NEW.report_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT e.device_id FROM ci_cancel_transmission p JOIN ce_exit e USING(exit_id) WHERE p.permit_id=NEW.permit_id AND NEW.disposition='unknown') d;
END;

CREATE TRIGGER go_go_close_hazard AFTER INSERT ON go_close BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'close',NEW.close_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT NEW.device_id AS device_id) d;
END;

CREATE TRIGGER go_go_revocation_hazard AFTER INSERT ON go_revocation BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'open_revocation',NEW.kind||':'||NEW.object_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT s.device_id FROM go_evidence e JOIN go_dispatch d USING(dispatch_id) JOIN go_plan p USING(plan_id) JOIN go_snapshot s USING(snapshot_id) WHERE NEW.kind='open_ack' AND e.evidence_id=NEW.object_id UNION SELECT x.device_id FROM go_close_ack a JOIN go_close x USING(close_id) WHERE NEW.kind='close_ack' AND a.ack_id=NEW.object_id) d;
END;

CREATE TRIGGER go_go_recovery_hazard AFTER INSERT ON go_recovery BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'recovery',NEW.recovery_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NEW.recovery_id FROM (SELECT NEW.device_id AS device_id) d;
END;

CREATE TRIGGER go_ce_exit_hazard AFTER INSERT ON ce_exit BEGIN
 INSERT INTO go_hazard(device_id,source_kind,source_id,revision,recovery_id) SELECT device_id,'exit',NEW.exit_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(h.revision) FROM go_hazard h WHERE h.device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),NULL FROM (SELECT NEW.device_id AS device_id) d;
END;

CREATE TRIGGER go_hazard_release_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='release' AND NOT EXISTS(SELECT 1 FROM (SELECT c.device_id FROM cr_release_invalidation x JOIN cr_release r USING(release_id) JOIN ce_command c USING(command_id) WHERE x.release_id=NEW.source_id) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_validation_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='validation' AND NOT EXISTS(SELECT 1 FROM (SELECT v.device_id FROM cr_validation_revocation x JOIN cr_validation v USING(validation_id) WHERE x.validation_id=NEW.source_id) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_control_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='control' AND NOT EXISTS(SELECT 1 FROM (SELECT DISTINCT c.device_id FROM cu_revocation x JOIN cu_selection s ON (x.kind='ack' AND x.object_id=s.barrier_id) OR (x.kind='retirement' AND x.object_id=s.retirement_exit_id) JOIN cu_effective f USING(change_id) JOIN ct_change c USING(change_id) WHERE x.kind||':'||x.object_id=NEW.source_id) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_command_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='command' AND NOT EXISTS(SELECT 1 FROM (SELECT c.device_id FROM cm_revision r JOIN cm_commit k USING(operation_id) JOIN ce_command c USING(command_id) WHERE r.operation_id=NEW.source_id AND (r.resource_status='unresolved' OR r.outcome='unknown')) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_report_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='report' AND NOT EXISTS(SELECT 1 FROM (SELECT e.device_id FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN ce_exit e ON e.exit_id=p.exit_id WHERE r.report_id=NEW.source_id AND r.disposition='unknown') d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_cancel_report_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='cancel_report' AND NOT EXISTS(SELECT 1 FROM (SELECT e.device_id FROM cf_report r JOIN ci_cancel_transmission p USING(permit_id) JOIN ce_exit e ON e.exit_id=p.exit_id WHERE r.report_id=NEW.source_id AND r.disposition='unknown') d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_close_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='close' AND NOT EXISTS(SELECT 1 FROM (SELECT device_id FROM go_close WHERE close_id=NEW.source_id) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_open_revocation_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='open_revocation' AND NOT EXISTS(SELECT 1 FROM (SELECT s.device_id FROM go_revocation x JOIN go_evidence e ON x.kind='open_ack' AND x.object_id=e.evidence_id JOIN go_dispatch d USING(dispatch_id) JOIN go_plan p USING(plan_id) JOIN go_snapshot s USING(snapshot_id) WHERE x.kind||':'||x.object_id=NEW.source_id UNION SELECT c.device_id FROM go_revocation x JOIN go_close_ack a ON x.kind='close_ack' AND x.object_id=a.ack_id JOIN go_close c USING(close_id) WHERE x.kind||':'||x.object_id=NEW.source_id) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_recovery_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='recovery' AND NOT EXISTS(SELECT 1 FROM (SELECT device_id FROM go_recovery WHERE recovery_id=NEW.source_id) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_exit_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='exit' AND NOT EXISTS(SELECT 1 FROM (SELECT device_id FROM ce_exit WHERE exit_id=NEW.source_id) d WHERE d.device_id=NEW.device_id) BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER go_hazard_u BEFORE UPDATE ON go_hazard BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_hazard_d BEFORE DELETE ON go_hazard BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_snapshot_u BEFORE UPDATE ON go_snapshot BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_snapshot_d BEFORE DELETE ON go_snapshot BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_hold_u BEFORE UPDATE ON go_hold BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_hold_d BEFORE DELETE ON go_hold BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_snapshot_commit_u BEFORE UPDATE ON go_snapshot_commit BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_snapshot_commit_d BEFORE DELETE ON go_snapshot_commit BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_gate_u BEFORE UPDATE ON go_gate BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_gate_d BEFORE DELETE ON go_gate BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_plan_u BEFORE UPDATE ON go_plan BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_plan_d BEFORE DELETE ON go_plan BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_plan_commit_u BEFORE UPDATE ON go_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_plan_commit_d BEFORE DELETE ON go_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_dispatch_u BEFORE UPDATE ON go_dispatch BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_dispatch_d BEFORE DELETE ON go_dispatch BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_evidence_u BEFORE UPDATE ON go_evidence BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_evidence_d BEFORE DELETE ON go_evidence BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_ready_u BEFORE UPDATE ON go_ready BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_ready_d BEFORE DELETE ON go_ready BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_close_u BEFORE UPDATE ON go_close BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_close_d BEFORE DELETE ON go_close BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_close_ack_u BEFORE UPDATE ON go_close_ack BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_close_ack_d BEFORE DELETE ON go_close_ack BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_recovery_u BEFORE UPDATE ON go_recovery BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_recovery_d BEFORE DELETE ON go_recovery BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_recovery_target_u BEFORE UPDATE ON go_recovery_target BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_recovery_target_d BEFORE DELETE ON go_recovery_target BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_recovery_commit_u BEFORE UPDATE ON go_recovery_commit BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_recovery_commit_d BEFORE DELETE ON go_recovery_commit BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_revocation_u BEFORE UPDATE ON go_revocation BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_revocation_d BEFORE DELETE ON go_revocation BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_exit_obligation_u BEFORE UPDATE ON go_exit_obligation BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_exit_obligation_d BEFORE DELETE ON go_exit_obligation BEGIN SELECT RAISE(ABORT,'immutable_open_storage'); END;

CREATE TRIGGER go_hold_sealed BEFORE INSERT ON go_hold WHEN EXISTS(SELECT 1 FROM go_snapshot_commit WHERE snapshot_id=NEW.snapshot_id) BEGIN SELECT RAISE(ABORT,'open_members_sealed'); END;

CREATE TRIGGER go_recovery_target_sealed BEFORE INSERT ON go_recovery_target WHEN EXISTS(SELECT 1 FROM go_recovery_commit WHERE recovery_id=NEW.recovery_id) BEGIN SELECT RAISE(ABORT,'open_members_sealed'); END;

-- 不可变占用归属附属候选；由生成器与178表组合，不是产品迁移。
CREATE TABLE ow_source(
 source_id TEXT PRIMARY KEY, scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
 source_revision TEXT NOT NULL CHECK(source_revision='00000000000000000001'),
 source_digest TEXT NOT NULL CHECK(length(source_digest)=71 AND substr(source_digest,1,7)='sha256:' AND substr(source_digest,8) NOT GLOB '*[^0-9a-f]*'),
 hold_id TEXT NOT NULL UNIQUE REFERENCES cr_hold(hold_id) DEFERRABLE INITIALLY DEFERRED,
 hold_digest TEXT NOT NULL, command_id TEXT NOT NULL REFERENCES ce_command(command_id), device_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('ordinary','cancel')),
 attempt_id TEXT REFERENCES ce_attempt(attempt_id), cancellation_id TEXT REFERENCES cv_cancel(cancellation_id),
 execution_id TEXT REFERENCES cg_plan(execution_id) DEFERRABLE INITIALLY DEFERRED,
 command_key_id TEXT REFERENCES ca_request_key(key_id), cancel_key_id TEXT REFERENCES cv_cancel_key(key_id),
 namespace_id TEXT NOT NULL REFERENCES ca_namespace(namespace_id), request_digest TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('manual','automation')), principal_kind TEXT NOT NULL CHECK(principal_kind IN ('human','service')),
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, principal_id TEXT NOT NULL,
 authority_state_id TEXT NOT NULL REFERENCES ct_state(change_id), control_epoch TEXT NOT NULL,
 effective_version TEXT NOT NULL CHECK(length(effective_version)=20 AND effective_version NOT GLOB '*[^0-9]*'),
 clock_domain TEXT NOT NULL, descriptor TEXT NOT NULL,
 sampled_tick TEXT NOT NULL CHECK(length(sampled_tick)=20 AND sampled_tick NOT GLOB '*[^0-9]*'),
 acquired_tick TEXT NOT NULL CHECK(length(acquired_tick)=20 AND acquired_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 CHECK(sampled_tick<=acquired_tick AND acquired_tick<expires_tick),
 CHECK((origin='manual' AND principal_kind='human') OR (origin='automation' AND principal_kind='service')),
 CHECK((kind='ordinary' AND attempt_id IS NOT NULL AND command_key_id IS NOT NULL AND cancellation_id IS NULL AND execution_id IS NULL AND cancel_key_id IS NULL)
 OR (kind='cancel' AND attempt_id IS NULL AND command_key_id IS NULL AND cancellation_id IS NOT NULL AND execution_id IS NOT NULL AND cancel_key_id IS NOT NULL)),
 FOREIGN KEY(source_id) REFERENCES ow_ownership(source_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ow_ownership(
 ownership_id TEXT PRIMARY KEY, revision TEXT NOT NULL CHECK(revision='00000000000000000001'),
 hold_id TEXT NOT NULL UNIQUE REFERENCES cr_hold(hold_id), source_id TEXT NOT NULL UNIQUE REFERENCES ow_source(source_id),
 ownership_digest TEXT NOT NULL CHECK(length(ownership_digest)=71 AND substr(ownership_digest,1,7)='sha256:' AND substr(ownership_digest,8) NOT GLOB '*[^0-9a-f]*'),
 ownership_body BLOB NOT NULL CHECK(length(ownership_body)>0),
 UNIQUE(ownership_id,revision,ownership_digest),
 FOREIGN KEY(ownership_id) REFERENCES ow_commit(ownership_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ow_commit(
 ownership_id TEXT PRIMARY KEY REFERENCES ow_ownership(ownership_id),
 hold_id TEXT NOT NULL UNIQUE REFERENCES cr_hold_commit(hold_id),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0), outbox_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE ow_revocation(
 source_id TEXT PRIMARY KEY REFERENCES ow_source(source_id),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), reason_body BLOB NOT NULL CHECK(length(reason_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0), outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
-- 真实请求来源；取消不从父命令namespace或origin推导Requester。
CREATE VIEW ow_request_source AS SELECT s.* FROM ow_source s JOIN ce_command c USING(command_id)
 JOIN ca_namespace n ON n.namespace_id=s.namespace_id
 WHERE s.scope_id=n.scope_id AND s.device_id=c.device_id
 AND s.issuer_id=n.issuer_id AND s.issuer_epoch=n.issuer_epoch AND s.principal_id=n.principal_id
 AND ((s.kind='ordinary' AND s.origin=c.origin AND EXISTS(
 SELECT 1 FROM ce_attempt a JOIN ca_command_initial i USING(command_id) JOIN ca_request_key k ON k.key_id=i.key_id
 WHERE a.attempt_id=s.attempt_id AND a.command_id=s.command_id AND k.key_id=s.command_key_id
 AND k.namespace_id=s.namespace_id AND k.request_digest=s.request_digest AND k.device_id=s.device_id))
 OR (s.kind='cancel' AND EXISTS(SELECT 1 FROM cv_cancel x JOIN cv_cancel_key k USING(key_id) JOIN cg_plan p USING(cancellation_id)
 WHERE x.cancellation_id=s.cancellation_id AND x.command_id=s.command_id AND p.execution_id=s.execution_id
 AND k.key_id=s.cancel_key_id AND k.namespace_id=s.namespace_id AND k.request_digest=s.request_digest)));
CREATE VIEW ow_current_source AS SELECT s.* FROM ow_request_source s
 JOIN go_authority a ON a.change_id=s.authority_state_id AND a.device_id=s.device_id
 JOIN ct_current_state c ON c.device_id=s.device_id JOIN ct_change t ON t.change_id=c.change_id
 WHERE a.pending_operation_id IS NULL AND c.pending_operation_id IS NULL
 AND s.control_epoch=a.control_epoch AND s.effective_version=a.effective_version
 AND s.clock_domain=t.clock_domain AND s.descriptor=t.descriptor
 AND NOT EXISTS(SELECT 1 FROM ow_revocation r WHERE r.source_id=s.source_id)
 AND ((s.origin='manual' AND a.mode='manual' AND s.issuer_id=a.holder_issuer AND s.issuer_epoch=a.holder_epoch AND s.principal_id=a.holder_id)
 OR (s.origin='automation' AND a.mode='automatic' AND a.holder_id IS NULL));
CREATE TRIGGER ow_seal BEFORE INSERT ON ow_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ow_ownership o JOIN ow_current_source s USING(source_id)
 JOIN cr_hold h ON h.hold_id=o.hold_id JOIN cr_hold_commit k ON k.hold_id=h.hold_id
 JOIN ct_current_state c ON c.device_id=s.device_id JOIN ct_change t ON t.change_id=c.change_id
 WHERE o.ownership_id=NEW.ownership_id AND o.hold_id=NEW.hold_id AND s.hold_id=o.hold_id
 AND h.hold_digest=s.hold_digest AND h.command_id=s.command_id AND h.attempt_id IS s.attempt_id AND h.cancel_execution_id IS s.execution_id
 AND t.now_tick<=NEW.committed_tick AND s.acquired_tick<=NEW.committed_tick AND NEW.committed_tick<s.expires_tick)
 THEN RAISE(ABORT,'ownership_source_or_authority') END;
END;
CREATE VIEW ow_record AS SELECT o.ownership_id,o.revision,o.ownership_digest,o.ownership_body,s.* FROM ow_ownership o
 JOIN ow_source s USING(source_id) JOIN ow_commit k ON k.ownership_id=o.ownership_id;
-- 仅当前主体来源资格；不含实时tick、完整Guard、GateAccess或资源可发送性。
CREATE VIEW ow_current_owner AS SELECT o.ownership_id,o.revision,o.ownership_digest,s.* FROM ow_ownership o
 JOIN ow_current_source s USING(source_id) JOIN ow_commit k ON k.ownership_id=o.ownership_id;
CREATE TRIGGER ow_snapshot_source BEFORE INSERT ON go_snapshot_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_hold h LEFT JOIN ow_record o ON o.ownership_id=h.owner_ref
 WHERE h.snapshot_id=NEW.snapshot_id AND (o.ownership_id IS NULL OR h.owner_revision!=o.revision
 OR h.owner_digest!=o.ownership_digest OR h.hold_id!=o.hold_id OR h.authority_state_id!=o.authority_state_id))
 THEN RAISE(ABORT,'ownership_snapshot_binding') END;
END;
-- 词表映射，不宣称自行证明异常原因或采样新鲜度。
CREATE VIEW ow_risk_projection AS SELECT h.snapshot_id,h.hold_id,h.owner_ref,h.owner_revision,h.owner_digest,h.authority_state_id,
 CASE h.classification WHEN 'active' THEN 'active' WHEN 'unknown' THEN 'unknown'
 WHEN 'failed_unresolved' THEN 'unresolved' WHEN 'orphaned' THEN 'stale' WHEN 'proof_revoked' THEN 'stale' END AS classification
 FROM go_hold h;
CREATE TRIGGER ow_revoke_hazard AFTER INSERT ON ow_revocation BEGIN
 INSERT INTO go_hazard(device_id,revision,source_kind,source_id,recovery_id)
 SELECT s.device_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=s.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=s.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=s.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),'ownership',NEW.source_id,NULL FROM ow_source s WHERE s.source_id=NEW.source_id;
END;
CREATE TRIGGER ow_hazard_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='ownership'
 AND NOT EXISTS(SELECT 1 FROM ow_revocation r JOIN ow_source s USING(source_id) WHERE r.source_id=NEW.source_id AND s.device_id=NEW.device_id)
 BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER ow_source_u BEFORE UPDATE ON ow_source BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;

CREATE TRIGGER ow_source_d BEFORE DELETE ON ow_source BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;

CREATE TRIGGER ow_ownership_u BEFORE UPDATE ON ow_ownership BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;

CREATE TRIGGER ow_ownership_d BEFORE DELETE ON ow_ownership BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;

CREATE TRIGGER ow_commit_u BEFORE UPDATE ON ow_commit BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;

CREATE TRIGGER ow_commit_d BEFORE DELETE ON ow_commit BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;

CREATE TRIGGER ow_revocation_u BEFORE UPDATE ON ow_revocation BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;

CREATE TRIGGER ow_revocation_d BEFORE DELETE ON ow_revocation BEGIN SELECT RAISE(ABORT,'immutable_ownership'); END;

-- 独立换闸证据；只建立fenced，不授予普通或取消执行资格。
CREATE TABLE gf_request(
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 request_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 previous_gate_id TEXT REFERENCES go_gate(gate_id),authority_state_id TEXT NOT NULL REFERENCES ct_state(change_id),
 control_state_id TEXT NOT NULL REFERENCES ct_state(change_id),close_ack_id TEXT NOT NULL REFERENCES go_close_ack(ack_id),
 safety_revision TEXT NOT NULL CHECK(length(safety_revision)=20 AND safety_revision NOT GLOB '*[^0-9]*'),
 target_revision TEXT NOT NULL CHECK(length(target_revision)=20 AND target_revision NOT GLOB '*[^0-9]*' AND target_revision>'00000000000000000000'),
 gate_token TEXT NOT NULL CHECK(length(gate_token)>0),message_id TEXT NOT NULL,
 outbound_seq TEXT NOT NULL CHECK(length(outbound_seq)=20 AND outbound_seq NOT GLOB '*[^0-9]*' AND outbound_seq>'00000000000000000000'),
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 lease_until_tick TEXT NOT NULL CHECK(length(lease_until_tick)=20 AND lease_until_tick NOT GLOB '*[^0-9]*'),
 request_digest TEXT NOT NULL CHECK(length(request_digest)=71 AND substr(request_digest,1,7)='sha256:'),
 body BLOB NOT NULL CHECK(length(body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK(selected_tick<expires_tick AND expires_tick<=lease_until_tick),UNIQUE(exit_id,message_id),UNIQUE(exit_id,outbound_seq),UNIQUE(close_ack_id),
 UNIQUE(exit_id,target_revision),UNIQUE(exit_id,gate_token)
) STRICT;
CREATE TABLE gf_ack(
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 ack_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE REFERENCES gf_request(request_id),exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 message_id TEXT NOT NULL,reply_to TEXT NOT NULL,inbound_seq TEXT NOT NULL CHECK(length(inbound_seq)=20 AND inbound_seq NOT GLOB '*[^0-9]*' AND inbound_seq>'00000000000000000000'),
 request_digest TEXT NOT NULL,gate_revision TEXT NOT NULL,gate_token TEXT NOT NULL,
 effective_tick TEXT NOT NULL CHECK(length(effective_tick)=20 AND effective_tick NOT GLOB '*[^0-9]*'),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 evidence_digest TEXT NOT NULL,observer_ref TEXT NOT NULL CHECK(length(observer_ref)>0),
 body BLOB NOT NULL CHECK(length(body)>0),validation_body BLOB NOT NULL CHECK(length(validation_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(exit_id,message_id),UNIQUE(exit_id,inbound_seq)
) STRICT;
CREATE TABLE gf_commit(
 request_id TEXT PRIMARY KEY REFERENCES gf_request(request_id),ack_id TEXT NOT NULL UNIQUE REFERENCES gf_ack(ack_id),
 gate_id TEXT NOT NULL UNIQUE REFERENCES go_gate(gate_id),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE gf_revocation(
 ack_id TEXT PRIMARY KEY REFERENCES gf_ack(ack_id),reason_body BLOB NOT NULL CHECK(length(reason_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW gf_context AS SELECT r.* FROM gf_request r
 JOIN go_authority a ON a.change_id=r.authority_state_id AND a.device_id=r.device_id
 JOIN ct_current_state c ON c.change_id=r.control_state_id AND c.device_id=r.device_id
 JOIN ce_exit e ON e.exit_id=r.exit_id AND e.device_id=r.device_id
 JOIN ct_change cc ON cc.change_id=c.change_id
 JOIN go_close_ack k ON k.ack_id=r.close_ack_id AND k.exit_id=r.exit_id
 JOIN go_latest_close x ON x.close_id=k.close_id AND x.exit_id=r.exit_id AND x.gate_id IS r.previous_gate_id
 WHERE c.pending_operation_id IS NULL AND c.gate_state!='ready'
 AND cc.clock_domain=e.clock_domain_id AND cc.descriptor=e.descriptor_digest
 AND cc.now_tick<=r.selected_tick AND k.received_tick<=r.selected_tick
 AND r.safety_revision=coalesce((SELECT max(revision) FROM go_hazard h WHERE h.device_id=r.device_id),'00000000000000000000')
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id)
 AND NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=k.ack_id);
CREATE TRIGGER gf_request_guard AFTER INSERT ON gf_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_context WHERE request_id=NEW.request_id)
 OR EXISTS(SELECT 1 FROM gf_request r WHERE r.exit_id=NEW.exit_id AND r.request_id!=NEW.request_id AND r.target_revision>=NEW.target_revision)
 OR EXISTS(SELECT 1 FROM go_gate g WHERE g.exit_id=NEW.exit_id AND g.gate_token=NEW.gate_token)
 OR NOT ((NEW.previous_gate_id IS NULL AND NOT EXISTS(SELECT 1 FROM go_gate WHERE exit_id=NEW.exit_id)) OR
 EXISTS(SELECT 1 FROM go_current_gate g WHERE g.gate_id=NEW.previous_gate_id AND g.exit_id=NEW.exit_id
 AND NEW.target_revision>g.gate_revision AND NEW.gate_token!=g.gate_token))
 THEN RAISE(ABORT,'gate_fence_request') END;
END;
CREATE TRIGGER gf_ack_guard BEFORE INSERT ON gf_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_request r WHERE r.request_id=NEW.request_id AND r.exit_id=NEW.exit_id
 AND r.message_id=NEW.reply_to AND r.request_digest=NEW.request_digest AND r.target_revision=NEW.gate_revision AND r.gate_token=NEW.gate_token
 AND r.selected_tick<=NEW.effective_tick AND NEW.effective_tick<=NEW.received_tick)
 THEN RAISE(ABORT,'gate_fence_ack') END;
END;
CREATE TRIGGER gf_gate_guard BEFORE INSERT ON go_gate WHEN NEW.renewal_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_request r WHERE r.request_id=NEW.renewal_id AND r.exit_id=NEW.exit_id
 AND r.target_revision=NEW.gate_revision AND r.gate_token=NEW.gate_token AND r.lease_until_tick=NEW.lease_until_tick
 AND (NEW.phase IN ('ready','scoped') OR (r.previous_gate_id IS NEW.previous_id AND EXISTS(SELECT 1 FROM gf_context c WHERE c.request_id=r.request_id))))
 THEN RAISE(ABORT,'gate_fence_projection') END;
END;
CREATE TRIGGER gf_commit_guard AFTER INSERT ON gf_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_context r JOIN gf_ack a USING(request_id) JOIN go_current_gate g ON g.gate_id=NEW.gate_id
 WHERE r.request_id=NEW.request_id AND a.ack_id=NEW.ack_id AND g.renewal_id=r.request_id AND g.phase='fenced'
 AND g.previous_id IS r.previous_gate_id AND g.exit_id=r.exit_id AND a.received_tick<=NEW.committed_tick AND NEW.committed_tick<r.expires_tick
 AND NOT EXISTS(SELECT 1 FROM gf_revocation v WHERE v.ack_id=a.ack_id))
 THEN RAISE(ABORT,'gate_fence_commit') END;
END;
CREATE VIEW ij_base_gf_valid_fence AS SELECT k.*,r.exit_id,r.device_id FROM gf_commit k JOIN gf_request r USING(request_id)
 JOIN go_authority a ON a.change_id=r.authority_state_id AND a.device_id=r.device_id
 JOIN ct_current_state c ON c.device_id=r.device_id JOIN go_close_ack ca ON ca.ack_id=r.close_ack_id
 JOIN go_latest_close x ON x.close_id=ca.close_id AND x.exit_id=r.exit_id
 WHERE c.pending_operation_id IS NULL AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id)
 AND NOT EXISTS(SELECT 1 FROM gf_revocation v WHERE v.ack_id=k.ack_id)
 AND NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=ca.ack_id);
CREATE TRIGGER gf_revoke_hazard AFTER INSERT ON gf_revocation BEGIN
 INSERT INTO go_hazard(device_id,revision,source_kind,source_id)
 SELECT r.device_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=r.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=r.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=r.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),'gate_fence',NEW.ack_id FROM gf_ack a JOIN gf_request r USING(request_id) WHERE a.ack_id=NEW.ack_id;
END;
CREATE TRIGGER gf_hazard_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='gate_fence' AND NOT EXISTS(
 SELECT 1 FROM gf_revocation v JOIN gf_ack a USING(ack_id) JOIN gf_request r USING(request_id) WHERE v.ack_id=NEW.source_id AND r.device_id=NEW.device_id)
 BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER gf_request_u BEFORE UPDATE ON gf_request BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;

CREATE TRIGGER gf_request_d BEFORE DELETE ON gf_request BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;

CREATE TRIGGER gf_ack_u BEFORE UPDATE ON gf_ack BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;

CREATE TRIGGER gf_ack_d BEFORE DELETE ON gf_ack BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;

CREATE TRIGGER gf_commit_u BEFORE UPDATE ON gf_commit BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;

CREATE TRIGGER gf_commit_d BEFORE DELETE ON gf_commit BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;

CREATE TRIGGER gf_revocation_u BEFORE UPDATE ON gf_revocation BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;

CREATE TRIGGER gf_revocation_d BEFORE DELETE ON gf_revocation BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;

-- 限定取消范围附属设计：原件真实性与完整授权仍由可信提供者外验。
CREATE TABLE gs_policy(
 policy_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES cg_plan_commit(execution_id),
 policy_ref_body BLOB NOT NULL CHECK(length(policy_ref_body)>0),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 FOREIGN KEY(policy_id) REFERENCES gs_policy_commit(policy_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE gs_parent_class(
 policy_id TEXT NOT NULL REFERENCES gs_policy(policy_id),classification TEXT NOT NULL CHECK(classification IN ('active','unknown','unresolved')),
 PRIMARY KEY(policy_id,classification)
) STRICT;
CREATE TABLE gs_policy_commit(policy_id TEXT PRIMARY KEY REFERENCES gs_policy(policy_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)) STRICT;
CREATE TRIGGER gs_policy_seal BEFORE INSERT ON gs_policy_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gs_policy p JOIN cg_plan g USING(execution_id)
 WHERE p.policy_id=NEW.policy_id AND p.policy_ref_body=g.policy_ref_body) THEN RAISE(ABORT,'scope_policy_binding') END;
END;
CREATE TRIGGER gs_policy_members BEFORE INSERT ON gs_parent_class WHEN EXISTS(SELECT 1 FROM gs_policy_commit WHERE policy_id=NEW.policy_id)
 BEGIN SELECT RAISE(ABORT,'scope_policy_sealed'); END;
CREATE TABLE gs_assessment(
 assessment_id TEXT PRIMARY KEY,revision TEXT NOT NULL CHECK(revision='00000000000000000001'),
 assessment_digest TEXT NOT NULL CHECK(length(assessment_digest)=71 AND substr(assessment_digest,1,7)='sha256:' AND substr(assessment_digest,8) NOT GLOB '*[^0-9a-f]*'),
 snapshot_id TEXT NOT NULL UNIQUE REFERENCES go_snapshot_commit(snapshot_id),policy_id TEXT NOT NULL REFERENCES gs_policy_commit(policy_id),
 ownership_id TEXT NOT NULL REFERENCES ow_commit(ownership_id),
 resource_safety_id TEXT NOT NULL CHECK(length(resource_safety_id)>0),resource_safety_revision TEXT NOT NULL CHECK(length(resource_safety_revision)=20 AND resource_safety_revision NOT GLOB '*[^0-9]*'),
 resource_safety_digest TEXT NOT NULL CHECK(length(resource_safety_digest)=71 AND substr(resource_safety_digest,1,7)='sha256:' AND substr(resource_safety_digest,8) NOT GLOB '*[^0-9a-f]*'),
 gate_safety_id TEXT NOT NULL CHECK(length(gate_safety_id)>0),gate_safety_revision TEXT NOT NULL CHECK(length(gate_safety_revision)=20 AND gate_safety_revision NOT GLOB '*[^0-9]*'),
 gate_safety_digest TEXT NOT NULL CHECK(length(gate_safety_digest)=71 AND substr(gate_safety_digest,1,7)='sha256:' AND substr(gate_safety_digest,8) NOT GLOB '*[^0-9a-f]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),body BLOB NOT NULL CHECK(length(body)>0),
 UNIQUE(assessment_id,revision,assessment_digest),
 FOREIGN KEY(assessment_id) REFERENCES gs_assessment_commit(assessment_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE gs_assessment_commit(assessment_id TEXT PRIMARY KEY REFERENCES gs_assessment(assessment_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)) STRICT;
-- 不借用普通go_valid_snapshot：父unknown可共存，自身取消hold必须当前active。
CREATE VIEW gs_current_assessment AS SELECT a.*,s.device_id,s.exit_id,s.authority_state_id,s.control_state_id,
 s.safety_revision,s.authorization_ref,s.run_snapshot_ref,s.command_snapshot_ref,s.time_snapshot_ref,s.sampled_tick,s.expires_tick,
 p.execution_id,p.expires_tick AS policy_expires_tick,g.cancellation_id,g.ordinary_closure_id,o.command_id,o.hold_id
 FROM gs_assessment a JOIN gs_assessment_commit ak USING(assessment_id) JOIN gs_policy p USING(policy_id)
 JOIN gs_policy_commit pk USING(policy_id) JOIN cg_plan g USING(execution_id)
 JOIN go_current_snapshot s USING(snapshot_id) JOIN go_authority au ON au.change_id=s.authority_state_id AND au.device_id=s.device_id
 JOIN ct_current_state c ON c.device_id=s.device_id JOIN ct_change t ON t.change_id=c.change_id
 JOIN ce_exit e ON e.exit_id=s.exit_id AND e.device_id=s.device_id
 JOIN ow_current_owner o ON o.ownership_id=a.ownership_id AND o.execution_id=g.execution_id AND o.hold_id=g.protected_hold_id
 JOIN cv_cancel_current v ON v.cancellation_id=g.cancellation_id
 JOIN cc_valid_closure cl ON cl.closure_id=g.ordinary_closure_id JOIN cc_cut cut ON cut.cut_id=cl.cut_id
 WHERE c.pending_operation_id IS NULL AND au.pending_operation_id IS NULL AND v.state='requested'
 AND o.kind='cancel' AND o.device_id=s.device_id AND cut.stage='ordinary' AND cut.cancellation_id=g.cancellation_id
 AND e.clock_domain_id=t.clock_domain AND e.descriptor_digest=t.descriptor
 AND NOT EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=e.exit_id)
 AND NOT EXISTS(SELECT 1 FROM cr_device_protection WHERE device_id=s.device_id)
 AND NOT EXISTS(SELECT 1 FROM cg_stopped WHERE execution_id=g.execution_id)
 AND NOT EXISTS(SELECT 1 FROM cc_cut WHERE cancellation_id=g.cancellation_id AND stage='all')
 AND NOT EXISTS(SELECT 1 FROM gs_revocation r WHERE (r.kind='policy' AND r.object_id=a.policy_id) OR (r.kind='assessment' AND r.object_id=a.assessment_id))
 AND s.safety_revision=coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=s.device_id),'00000000000000000000')
 AND (SELECT count(*) FROM go_hold WHERE snapshot_id=s.snapshot_id) BETWEEN 1 AND 256
 AND EXISTS(SELECT 1 FROM go_hold h WHERE h.snapshot_id=s.snapshot_id AND h.hold_id=o.hold_id AND h.classification='active' AND h.owner_ref=a.ownership_id)
 AND NOT EXISTS(SELECT hold_id FROM cr_risk_hold WHERE device_id=s.device_id EXCEPT SELECT hold_id FROM go_hold WHERE snapshot_id=s.snapshot_id)
 AND NOT EXISTS(SELECT hold_id FROM go_hold WHERE snapshot_id=s.snapshot_id EXCEPT SELECT hold_id FROM cr_risk_hold WHERE device_id=s.device_id)
 AND NOT EXISTS(SELECT 1 FROM ow_risk_projection h JOIN ow_record r ON r.ownership_id=h.owner_ref
 LEFT JOIN cm_latest m ON m.command_id=r.command_id WHERE h.snapshot_id=s.snapshot_id AND h.hold_id!=o.hold_id AND
 (r.kind!='ordinary' OR r.command_id!=o.command_id OR EXISTS(SELECT 1 FROM ow_revocation WHERE source_id=r.source_id)
 OR m.command_id IS NULL OR h.classification!=CASE WHEN m.outcome='unknown' THEN 'unknown' WHEN m.resource_status='unresolved' THEN 'unresolved' ELSE 'active' END
 OR NOT EXISTS(SELECT 1 FROM gs_parent_class k WHERE k.policy_id=p.policy_id AND k.classification=h.classification)));
CREATE TRIGGER gs_assessment_seal AFTER INSERT ON gs_assessment_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gs_current_assessment WHERE assessment_id=NEW.assessment_id) THEN RAISE(ABORT,'scope_assessment_invalid') END;
END;
CREATE TABLE gs_access(
 access_id TEXT PRIMARY KEY,revision TEXT NOT NULL CHECK(revision='00000000000000000001'),
 access_digest TEXT NOT NULL CHECK(length(access_digest)=71 AND substr(access_digest,1,7)='sha256:' AND substr(access_digest,8) NOT GLOB '*[^0-9a-f]*'),
 plan_id TEXT NOT NULL UNIQUE REFERENCES go_plan(plan_id),initial_assessment_id TEXT NOT NULL REFERENCES gs_assessment_commit(assessment_id),
 body BLOB NOT NULL CHECK(length(body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(access_id,revision,access_digest)
) STRICT;
-- 当前评估可更新，但初始原件的撤回、两独立安全Ref与Scope必须一直匹配。
CREATE VIEW gs_access_basis AS SELECT x.*,a.device_id,a.exit_id,a.authority_state_id,a.safety_revision,a.control_state_id,
 a.assessment_id AS current_assessment_id,a.sampled_tick,a.expires_tick AS assessment_expires_tick,a.policy_expires_tick,
 a.authorization_ref,a.run_snapshot_ref,a.command_snapshot_ref,a.time_snapshot_ref
 FROM gs_access x JOIN go_plan p USING(plan_id) JOIN gs_assessment original ON original.assessment_id=x.initial_assessment_id
 JOIN go_snapshot os ON os.snapshot_id=original.snapshot_id
 JOIN gs_current_assessment a ON a.policy_id=original.policy_id AND a.ownership_id=original.ownership_id
 AND a.device_id=os.device_id AND a.exit_id=os.exit_id AND a.authority_state_id=os.authority_state_id
 AND a.safety_revision=os.safety_revision AND a.authorization_ref=os.authorization_ref
 AND a.run_snapshot_ref=os.run_snapshot_ref AND a.command_snapshot_ref=os.command_snapshot_ref AND a.time_snapshot_ref=os.time_snapshot_ref
 AND a.resource_safety_id=original.resource_safety_id AND a.resource_safety_revision=original.resource_safety_revision AND a.resource_safety_digest=original.resource_safety_digest
 AND a.gate_safety_id=original.gate_safety_id AND a.gate_safety_revision=original.gate_safety_revision AND a.gate_safety_digest=original.gate_safety_digest
 WHERE p.basis_kind='scope' AND p.scope_assessment_id=x.initial_assessment_id AND p.snapshot_id=original.snapshot_id
 AND os.sampled_tick<=p.selected_tick AND p.selected_tick<os.expires_tick AND p.expires_tick<=a.policy_expires_tick
 AND NOT EXISTS(SELECT 1 FROM gs_revocation r WHERE (r.kind='access' AND r.object_id=x.access_id) OR (r.kind='assessment' AND r.object_id=x.initial_assessment_id));
CREATE VIEW gs_scope_plan AS SELECT p.*,a.device_id,a.exit_id,a.authority_state_id,a.safety_revision FROM go_plan p
 JOIN go_plan_commit k USING(plan_id) JOIN gs_access_basis a USING(plan_id)
 JOIN ct_current_state c ON c.change_id=p.before_control_id AND c.change_id=a.control_state_id
 JOIN go_current_gate g ON g.gate_id=p.before_gate_id AND g.exit_id=a.exit_id
 WHERE g.phase='fenced' AND c.pending_operation_id IS NULL AND c.gate_state!='ready'
 AND a.current_assessment_id=p.scope_assessment_id AND p.expires_tick<=g.lease_until_tick
 AND ((g.renewal_id IS NOT NULL AND EXISTS(SELECT 1 FROM gf_valid_fence f WHERE f.request_id=g.renewal_id)) OR
 (g.control_barrier_id IS NOT NULL AND EXISTS(SELECT 1 FROM cu_valid_effective e WHERE e.control_state_id=c.change_id)
 AND NOT EXISTS(SELECT 1 FROM go_close WHERE device_id=a.device_id)));
CREATE VIEW go_valid_plan AS SELECT * FROM go_ordinary_plan UNION ALL SELECT * FROM gs_scope_plan;
CREATE TRIGGER gs_dispatch_time BEFORE INSERT ON go_dispatch WHEN EXISTS(SELECT 1 FROM go_plan WHERE plan_id=NEW.plan_id AND basis_kind='scope') BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gs_access_basis WHERE plan_id=NEW.plan_id AND NEW.reserved_tick<assessment_expires_tick)
 THEN RAISE(ABORT,'scope_dispatch_expired') END;
END;
CREATE TRIGGER gs_access_seal AFTER INSERT ON go_plan_commit WHEN EXISTS(SELECT 1 FROM go_plan WHERE plan_id=NEW.plan_id AND basis_kind='scope') BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM gs_access WHERE plan_id=NEW.plan_id)!=1 THEN RAISE(ABORT,'scope_access_required') END;
END;
CREATE TRIGGER gs_access_closed BEFORE INSERT ON gs_access WHEN EXISTS(SELECT 1 FROM go_plan_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'scope_access_sealed'); END;
CREATE TRIGGER gs_evidence_guard BEFORE INSERT ON go_evidence BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_dispatch d JOIN go_plan p USING(plan_id) WHERE d.dispatch_id=NEW.dispatch_id AND
 ((p.basis_kind!='scope' AND NEW.scope_access_id IS NULL AND NEW.scope_access_revision IS NULL AND NEW.scope_access_digest IS NULL) OR
 (p.basis_kind='scope' AND EXISTS(SELECT 1 FROM gs_access a WHERE a.plan_id=p.plan_id AND a.access_id=NEW.scope_access_id
 AND a.revision=NEW.scope_access_revision AND a.access_digest=NEW.scope_access_digest)))) THEN RAISE(ABORT,'scope_ack_binding') END;
END;
CREATE TABLE gs_scope_commit(
 commit_id TEXT PRIMARY KEY,access_id TEXT NOT NULL UNIQUE REFERENCES gs_access(access_id),evidence_id TEXT NOT NULL UNIQUE REFERENCES go_evidence(evidence_id),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_state(change_id),after_gate_id TEXT NOT NULL UNIQUE REFERENCES go_gate(gate_id) DEFERRABLE INITIALLY DEFERRED,
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 commit_digest TEXT NOT NULL CHECK(length(commit_digest)>0),body BLOB NOT NULL CHECK(length(body)>0),
 FOREIGN KEY(change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER gs_commit_pair BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM gs_scope_commit WHERE change_id=NEW.change_id)!=(SELECT kind='scope_commit' FROM ct_change WHERE change_id=NEW.change_id)
 THEN RAISE(ABORT,'scope_commit_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gs_scope_commit k WHERE k.change_id=NEW.change_id AND NOT EXISTS(
 SELECT 1 FROM gs_access_basis a JOIN go_plan p USING(plan_id) JOIN go_plan_commit pk USING(plan_id)
 JOIN ct_current_state old ON old.change_id=p.before_control_id JOIN ct_change c ON c.change_id=k.change_id JOIN ct_state n ON n.change_id=c.change_id
 JOIN go_evidence e ON e.evidence_id=k.evidence_id JOIN go_dispatch d ON d.dispatch_id=e.dispatch_id
 JOIN go_gate b ON b.gate_id=p.before_gate_id JOIN go_current_gate g ON g.gate_id=k.after_gate_id
 WHERE a.access_id=k.access_id AND a.current_assessment_id=p.scope_assessment_id AND a.control_state_id=old.change_id
 AND e.scope_access_id=a.access_id AND d.plan_id=p.plan_id AND g.previous_id=b.gate_id AND g.phase='scoped' AND g.scope_commit_id=k.commit_id
 AND g.exit_id=a.exit_id AND c.device_id=a.device_id AND n.record_digest!=old.record_digest AND n.gate_state='protected'
 AND e.received_tick<=k.committed_tick AND k.committed_tick=c.now_tick AND c.now_tick<p.expires_tick AND c.now_tick<a.assessment_expires_tick
 AND p.expires_tick<=g.lease_until_tick AND NOT EXISTS(SELECT 1 FROM go_revocation r WHERE r.kind='open_ack' AND r.object_id=e.evidence_id)
 AND ((g.renewal_id IS NOT NULL AND EXISTS(SELECT 1 FROM gf_valid_fence f WHERE f.request_id=g.renewal_id)) OR
 (g.control_barrier_id IS NOT NULL AND EXISTS(SELECT 1 FROM cu_valid_effective f WHERE f.control_state_id=old.change_id)
 AND NOT EXISTS(SELECT 1 FROM go_close WHERE device_id=a.device_id))))) THEN RAISE(ABORT,'scope_commit_binding') END;
END;
CREATE VIEW ij_base_gs_scope_candidate AS SELECT k.*,a.current_assessment_id,p.expires_tick,a.assessment_expires_tick,a.device_id,a.exit_id
 FROM gs_scope_commit k JOIN ct_commit ck USING(change_id) JOIN gs_access_basis a USING(access_id) JOIN go_plan p USING(plan_id)
 JOIN ct_current_state c ON c.device_id=a.device_id JOIN go_current_gate g ON g.gate_id=k.after_gate_id AND g.scope_commit_id=k.commit_id
 WHERE c.gate_state='protected' AND c.pending_operation_id IS NULL
 AND NOT EXISTS(SELECT 1 FROM go_revocation r WHERE r.kind='open_ack' AND r.object_id=k.evidence_id)
 AND ((g.renewal_id IS NOT NULL AND EXISTS(SELECT 1 FROM gf_valid_fence f WHERE f.request_id=g.renewal_id)) OR
 (g.control_barrier_id IS NOT NULL AND EXISTS(SELECT 1 FROM cu_valid_effective f WHERE f.control_state_id=a.authority_state_id)
 AND NOT EXISTS(SELECT 1 FROM go_close WHERE device_id=a.device_id)));
-- 本视图不含实时now，也不替代完整Guard和AdmissionSeal。
CREATE TABLE gs_revocation(kind TEXT NOT NULL CHECK(kind IN ('policy','assessment','access')),object_id TEXT NOT NULL,
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),PRIMARY KEY(kind,object_id)) STRICT;
CREATE VIEW gs_revocation_device AS SELECT r.kind,r.object_id,s.device_id FROM gs_revocation r JOIN gs_assessment a
 ON (r.kind='assessment' AND r.object_id=a.assessment_id) OR (r.kind='policy' AND r.object_id=a.policy_id)
 JOIN go_snapshot s USING(snapshot_id)
 UNION SELECT r.kind,r.object_id,s.device_id FROM gs_revocation r JOIN gs_access x ON r.kind='access' AND r.object_id=x.access_id
 JOIN gs_assessment a ON a.assessment_id=x.initial_assessment_id JOIN go_snapshot s USING(snapshot_id)
 UNION SELECT r.kind,r.object_id,c.device_id FROM gs_revocation r JOIN gs_policy p ON r.kind='policy' AND r.object_id=p.policy_id
 JOIN cg_plan g USING(execution_id) JOIN cv_cancel x USING(cancellation_id) JOIN ce_command c ON c.command_id=x.command_id;
CREATE TRIGGER gs_revocation_guard AFTER INSERT ON gs_revocation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gs_revocation_device WHERE kind=NEW.kind AND object_id=NEW.object_id) THEN RAISE(ABORT,'scope_revocation_source') END;
 INSERT INTO go_hazard(device_id,revision,source_kind,source_id)
 SELECT d.device_id,printf('%010d%010d',CAST(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=d.device_id),'00000000000000000000'),1,10) AS INTEGER)+(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=d.device_id),'00000000000000000000'),11,10)='9999999999'),(CAST(substr(coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=d.device_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000),'scope',NEW.kind||':'||NEW.object_id FROM gs_revocation_device d WHERE d.kind=NEW.kind AND d.object_id=NEW.object_id;
END;
CREATE TRIGGER gs_hazard_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='scope' AND NOT EXISTS(
 SELECT 1 FROM gs_revocation_device WHERE kind||':'||object_id=NEW.source_id AND device_id=NEW.device_id)
 BEGIN SELECT RAISE(ABORT,'hazard_source'); END;

CREATE TRIGGER gs_policy_u BEFORE UPDATE ON gs_policy BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_policy_d BEFORE DELETE ON gs_policy BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_parent_class_u BEFORE UPDATE ON gs_parent_class BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_parent_class_d BEFORE DELETE ON gs_parent_class BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_policy_commit_u BEFORE UPDATE ON gs_policy_commit BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_policy_commit_d BEFORE DELETE ON gs_policy_commit BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_assessment_u BEFORE UPDATE ON gs_assessment BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_assessment_d BEFORE DELETE ON gs_assessment BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_assessment_commit_u BEFORE UPDATE ON gs_assessment_commit BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_assessment_commit_d BEFORE DELETE ON gs_assessment_commit BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_access_u BEFORE UPDATE ON gs_access BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_access_d BEFORE DELETE ON gs_access BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_scope_commit_u BEFORE UPDATE ON gs_scope_commit BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_scope_commit_d BEFORE DELETE ON gs_scope_commit BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_revocation_u BEFORE UPDATE ON gs_revocation BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

CREATE TRIGGER gs_revocation_d BEFORE DELETE ON gs_revocation BEGIN SELECT RAISE(ABORT,'immutable_scope_storage'); END;

-- 与194表组合；编码请求和设备许可分开。真实鉴权/JCS/时钟/磁盘预算另验。
CREATE TABLE ep_limit(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1) REFERENCES controller_scope(singleton),
 profile_id TEXT NOT NULL, profile_revision TEXT NOT NULL, profile_digest TEXT NOT NULL,
 max_live_prepares INTEGER NOT NULL CHECK(max_live_prepares BETWEEN 1 AND 4096),
 max_metadata_prepares INTEGER NOT NULL CHECK(max_metadata_prepares BETWEEN 1 AND 65536),
 max_live_bytes INTEGER NOT NULL CHECK(max_live_bytes BETWEEN 1 AND 9007199254740991),
 profile_body BLOB NOT NULL CHECK(length(profile_body)>0)
) STRICT;
CREATE TABLE ep_request(
 prepare_id TEXT PRIMARY KEY NOT NULL, scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES ep_limit(singleton),
 kind TEXT NOT NULL CHECK(kind IN ('ordinary','cancel')),
 command_id TEXT NOT NULL REFERENCES ce_command(command_id),
 proposed_attempt_id TEXT, cancellation_id TEXT REFERENCES cv_cancel_commit(cancellation_id),
 cancel_prepare_id TEXT REFERENCES cc_prepare(prepare_id) DEFERRABLE INITIALLY DEFERRED,
 namespace_id TEXT NOT NULL REFERENCES ca_namespace(namespace_id), request_digest TEXT NOT NULL,
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, principal_id TEXT NOT NULL,
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id), primitive_id TEXT NOT NULL,
 reservation_id TEXT NOT NULL UNIQUE, reservation_revision TEXT NOT NULL CHECK(reservation_revision='00000000000000000001'), reservation_digest TEXT NOT NULL,
 authorization_id TEXT NOT NULL UNIQUE, authorization_digest TEXT NOT NULL,
 authorization_body BLOB NOT NULL CHECK(length(authorization_body)>0),
 request_message_id TEXT NOT NULL,
 max_bytes INTEGER NOT NULL CHECK(max_bytes BETWEEN 1 AND 65536),
 created_tick TEXT NOT NULL CHECK(length(created_tick)=20 AND created_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 CHECK(created_tick<expires_tick),
 CHECK((kind='ordinary' AND proposed_attempt_id IS NOT NULL AND cancellation_id IS NULL AND cancel_prepare_id IS NULL)
  OR (kind='cancel' AND proposed_attempt_id IS NULL AND cancellation_id IS NOT NULL AND cancel_prepare_id IS NOT NULL AND cancel_prepare_id=prepare_id)),
 UNIQUE(exit_id,request_message_id), UNIQUE(proposed_attempt_id,primitive_id),
 FOREIGN KEY(prepare_id) REFERENCES pd_registration(prepare_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(prepare_id) REFERENCES ep_request_commit(prepare_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ep_request_commit(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_request(prepare_id),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE ep_send_attempt(
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_write_attempt(frame_id) DEFERRABLE INITIALLY DEFERRED,
 prepare_id TEXT PRIMARY KEY REFERENCES ep_request_commit(prepare_id),
 attempt_id TEXT NOT NULL UNIQUE,
 attempted_tick TEXT NOT NULL CHECK(length(attempted_tick)=20 AND attempted_tick NOT GLOB '*[^0-9]*'),
 request_frame_digest TEXT NOT NULL, attempt_body BLOB NOT NULL CHECK(length(attempt_body)>0)
) STRICT;
CREATE TABLE ep_reply(
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 prepare_id TEXT PRIMARY KEY REFERENCES ep_send_attempt(prepare_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id), response_message_id TEXT NOT NULL,
 response_seq TEXT NOT NULL CHECK(length(response_seq)=20 AND response_seq NOT GLOB '*[^0-9]*' AND response_seq>'00000000000000000000'),
 reply_to TEXT NOT NULL, authorization_id TEXT NOT NULL, authorization_digest TEXT NOT NULL,
 response_frame_digest TEXT NOT NULL, response_frame BLOB NOT NULL CHECK(length(response_frame)>0),
 outcome TEXT NOT NULL CHECK(outcome IN ('prepared','failed','rejected')),
 packet_id TEXT UNIQUE, packet_digest TEXT, bytes_digest TEXT, packet_bytes BLOB, packet_body BLOB,
 evidence_id TEXT UNIQUE, evidence_digest TEXT, evidence_body BLOB,
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 UNIQUE(exit_id,response_message_id), UNIQUE(exit_id,response_seq),
 CHECK((outcome='prepared' AND packet_id IS NOT NULL AND packet_digest IS NOT NULL AND bytes_digest IS NOT NULL
   AND packet_bytes IS NOT NULL AND length(packet_bytes)>0 AND packet_body IS NOT NULL AND length(packet_body)>0
   AND evidence_id IS NOT NULL AND evidence_digest IS NOT NULL AND evidence_body IS NOT NULL AND length(evidence_body)>0)
 OR (outcome!='prepared' AND packet_id IS NULL AND packet_digest IS NULL AND bytes_digest IS NULL AND packet_bytes IS NULL
   AND packet_body IS NULL AND evidence_id IS NULL AND evidence_digest IS NULL AND evidence_body IS NULL)),
 FOREIGN KEY(prepare_id) REFERENCES ep_receive_commit(prepare_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ep_receive_commit(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_reply(prepare_id),
 disposition TEXT NOT NULL CHECK(disposition IN ('prepared','failed','historical')),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ep_revocation(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_request_commit(prepare_id),
 revocation_id TEXT NOT NULL UNIQUE, revocation_revision TEXT NOT NULL CHECK(revocation_revision='00000000000000000001'), revocation_digest TEXT NOT NULL,
 revoked_tick TEXT NOT NULL CHECK(length(revoked_tick)=20 AND revoked_tick NOT GLOB '*[^0-9]*'),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE ep_release(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_revocation(prepare_id),
 basis TEXT NOT NULL CHECK(basis IN ('never_attempted','supervisor_retired','worker_released')),
 worker_adoption_id TEXT UNIQUE,
 retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 proof_body BLOB NOT NULL CHECK(length(proof_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK((basis='never_attempted' AND retirement_exit_id IS NULL AND worker_adoption_id IS NULL) OR (basis='supervisor_retired' AND retirement_exit_id IS NOT NULL AND worker_adoption_id IS NULL) OR (basis='worker_released' AND retirement_exit_id IS NULL AND worker_adoption_id IS NOT NULL)),
 UNIQUE(prepare_id,worker_adoption_id),
 FOREIGN KEY(prepare_id,worker_adoption_id) REFERENCES er_adoption(prepare_id,adoption_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW ep_live_reservation AS SELECT r.prepare_id,r.scope_id,r.max_bytes FROM ep_request r
 WHERE NOT EXISTS(SELECT 1 FROM ep_release f WHERE f.prepare_id=r.prepare_id);
CREATE VIEW ep_request_source AS SELECT r.* FROM ep_request r JOIN ce_command c USING(command_id)
 JOIN ce_exit e ON e.exit_id=r.exit_id AND e.device_id=c.device_id JOIN ca_namespace n ON n.namespace_id=r.namespace_id
 WHERE n.scope_id=r.scope_id AND n.issuer_id=r.issuer_id AND n.issuer_epoch=r.issuer_epoch AND n.principal_id=r.principal_id
 AND ((r.kind='ordinary' AND EXISTS(SELECT 1 FROM ca_command_initial i JOIN ca_request_key k USING(key_id)
  WHERE i.command_id=r.command_id AND k.namespace_id=r.namespace_id AND k.request_digest=r.request_digest))
 OR (r.kind='cancel' AND EXISTS(SELECT 1 FROM cv_cancel c JOIN cv_cancel_key k USING(key_id) JOIN cc_prepare p USING(cancellation_id)
  WHERE c.cancellation_id=r.cancellation_id AND c.command_id=r.command_id AND k.namespace_id=r.namespace_id
   AND k.request_digest=r.request_digest AND p.prepare_id=r.prepare_id AND p.exit_id=r.exit_id AND p.primitive_id=r.primitive_id)));
CREATE VIEW ij_base_ep_open_request AS SELECT r.* FROM ep_request_source r JOIN ep_request_commit k USING(prepare_id)
 WHERE NOT EXISTS(SELECT 1 FROM ep_revocation v WHERE v.prepare_id=r.prepare_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id)
 AND ((r.kind='ordinary' AND NOT EXISTS(SELECT 1 FROM cv_cancel c WHERE c.command_id=r.command_id))
 OR (r.kind='cancel' AND NOT EXISTS(SELECT 1 FROM cc_cut c WHERE c.cancellation_id=r.cancellation_id AND c.stage='all')));
CREATE VIEW ep_prepared_candidate AS SELECT r.*,p.packet_id,p.packet_digest,p.packet_bytes,p.packet_body,p.evidence_id,p.evidence_digest
 FROM ep_open_request r JOIN ep_reply p USING(prepare_id) JOIN ep_receive_commit k USING(prepare_id)
 WHERE k.disposition='prepared';
CREATE VIEW ep_recovery AS SELECT r.prepare_id,
 CASE WHEN f.prepare_id IS NOT NULL THEN 'released' WHEN v.prepare_id IS NOT NULL THEN 'revoked'
 WHEN p.prepare_id IS NOT NULL THEN 'query_recorded_result' WHEN a.prepare_id IS NOT NULL THEN 'query_or_retire_unknown'
 ELSE 'never_attempted_do_not_replay' END AS recovery_action
 FROM ep_request r JOIN ep_request_commit k USING(prepare_id) LEFT JOIN ep_send_attempt a USING(prepare_id)
 LEFT JOIN ep_reply p USING(prepare_id) LEFT JOIN ep_revocation v USING(prepare_id) LEFT JOIN ep_release f USING(prepare_id);
CREATE TRIGGER ep_reserve BEFORE INSERT ON ep_request BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM ep_live_reservation)>=(SELECT max_live_prepares FROM ep_limit WHERE singleton=NEW.scope_id)
 OR NEW.max_bytes>(SELECT max_live_bytes FROM ep_limit WHERE singleton=NEW.scope_id)-coalesce((SELECT sum(max_bytes) FROM ep_live_reservation),0)
 THEN RAISE(ABORT,'encoding_capacity') END;
END;
CREATE TRIGGER ep_request_seal BEFORE INSERT ON ep_request_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request_source r WHERE r.prepare_id=NEW.prepare_id
  AND r.created_tick<=NEW.committed_tick AND NEW.committed_tick<r.expires_tick
  AND NOT EXISTS(SELECT 1 FROM ce_retirement e WHERE e.exit_id=r.exit_id)
  AND ((r.kind='ordinary' AND NOT EXISTS(SELECT 1 FROM cv_cancel c WHERE c.command_id=r.command_id))
    OR (r.kind='cancel' AND NOT EXISTS(SELECT 1 FROM cc_cut c WHERE c.cancellation_id=r.cancellation_id AND c.stage='all'))))
 THEN RAISE(ABORT,'encoding_request_source') END;
END;
CREATE TRIGGER ep_attempt_guard BEFORE INSERT ON ep_send_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_open_request r JOIN ep_request_commit k USING(prepare_id) JOIN ij_encoding_frame j USING(prepare_id)
 WHERE r.prepare_id=NEW.prepare_id AND j.request_frame_digest=NEW.request_frame_digest
 AND k.committed_tick<=NEW.attempted_tick AND NEW.attempted_tick<r.expires_tick)
 THEN RAISE(ABORT,'encoding_attempt_not_current') END;
END;
CREATE TRIGGER ep_reply_guard BEFORE INSERT ON ep_reply BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ep_send_attempt a USING(prepare_id)
  WHERE r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id AND r.request_message_id=NEW.reply_to
  AND r.authorization_id=NEW.authorization_id AND r.authorization_digest=NEW.authorization_digest
  AND a.attempted_tick<=NEW.received_tick AND (NEW.outcome!='prepared' OR length(NEW.packet_bytes)<=r.max_bytes))
 THEN RAISE(ABORT,'encoding_reply_binding') END;
END;
CREATE TRIGGER ep_receive_seal BEFORE INSERT ON ep_receive_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_reply p WHERE p.prepare_id=NEW.prepare_id AND p.received_tick<=NEW.committed_tick)
 THEN RAISE(ABORT,'encoding_receive_time') END;
 SELECT CASE WHEN NEW.disposition='prepared' AND NOT EXISTS(SELECT 1 FROM ep_reply p JOIN ep_open_request r USING(prepare_id)
 WHERE p.prepare_id=NEW.prepare_id AND p.outcome='prepared' AND NEW.committed_tick<r.expires_tick)
 THEN RAISE(ABORT,'encoding_not_adoptable') END;
 SELECT CASE WHEN NEW.disposition='failed' AND NOT EXISTS(SELECT 1 FROM ep_reply WHERE prepare_id=NEW.prepare_id AND outcome IN ('failed','rejected'))
 THEN RAISE(ABORT,'encoding_not_failed') END;
END;
CREATE TRIGGER ep_release_guard BEFORE INSERT ON ep_release BEGIN
 SELECT CASE WHEN (NEW.basis='never_attempted' AND EXISTS(SELECT 1 FROM ep_send_attempt WHERE prepare_id=NEW.prepare_id))
 OR (NEW.basis='supervisor_retired' AND NOT EXISTS(SELECT 1 FROM ep_request WHERE prepare_id=NEW.prepare_id AND exit_id=NEW.retirement_exit_id))
 THEN RAISE(ABORT,'encoding_release_proof') END;
END;
-- 普通与取消旧packet入口必须映射同一不可变编码证据；最终T2时效和完整seal仍另验。
CREATE TRIGGER ep_ordinary_packet BEFORE INSERT ON ce_packet BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_prepared_candidate p JOIN ce_attempt a ON a.attempt_id=p.proposed_attempt_id
 WHERE p.kind='ordinary' AND p.packet_id=NEW.packet_id AND p.proposed_attempt_id=NEW.attempt_id AND a.command_id=p.command_id
 AND p.exit_id=NEW.exit_id AND p.primitive_id=NEW.primitive_id AND p.packet_body=NEW.packet_body)
 THEN RAISE(ABORT,'encoding_ordinary_packet_source') END;
END;
CREATE TRIGGER ep_cancel_packet BEFORE INSERT ON cc_packet BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_prepared_candidate p WHERE p.kind='cancel' AND p.packet_id=NEW.packet_id
 AND p.prepare_id=NEW.prepare_id AND p.packet_digest=NEW.packet_digest AND p.packet_bytes=NEW.packet_bytes AND p.packet_body=NEW.packet_body)
 THEN RAISE(ABORT,'encoding_cancel_packet_source') END;
END;

CREATE TRIGGER ep_limit_u BEFORE UPDATE ON ep_limit BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_limit_d BEFORE DELETE ON ep_limit BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_request_u BEFORE UPDATE ON ep_request BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_request_d BEFORE DELETE ON ep_request BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_request_commit_u BEFORE UPDATE ON ep_request_commit BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_request_commit_d BEFORE DELETE ON ep_request_commit BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_send_attempt_u BEFORE UPDATE ON ep_send_attempt BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_send_attempt_d BEFORE DELETE ON ep_send_attempt BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_reply_u BEFORE UPDATE ON ep_reply BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_reply_d BEFORE DELETE ON ep_reply BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_receive_commit_u BEFORE UPDATE ON ep_receive_commit BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_receive_commit_d BEFORE DELETE ON ep_receive_commit BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_revocation_u BEFORE UPDATE ON ep_revocation BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_revocation_d BEFORE DELETE ON ep_revocation BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_release_u BEFORE UPDATE ON ep_release BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

CREATE TRIGGER ep_release_d BEFORE DELETE ON ep_release BEGIN SELECT RAISE(ABORT,'immutable_encoding'); END;

-- 与编码202表按固定替换组合；SQL约束投影，原件/JCS/真实消费者由可信提供者验证。
CREATE TABLE er_request(
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 release_id TEXT PRIMARY KEY NOT NULL, release_revision TEXT NOT NULL CHECK(release_revision='00000000000000000001'),
 release_digest TEXT NOT NULL, prepare_id TEXT NOT NULL UNIQUE REFERENCES ep_revocation(prepare_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 authorization_id TEXT NOT NULL, authorization_digest TEXT NOT NULL,
 encode_message_id TEXT NOT NULL, encode_frame_digest TEXT NOT NULL,
 revocation_id TEXT NOT NULL, revocation_revision TEXT NOT NULL, revocation_digest TEXT NOT NULL,
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 message_id TEXT NOT NULL, outbound_seq TEXT NOT NULL CHECK(length(outbound_seq)=20 AND outbound_seq NOT GLOB '*[^0-9]*' AND outbound_seq>'00000000000000000000'),
 frame_digest TEXT NOT NULL, frame_body BLOB NOT NULL CHECK(length(frame_body)>0), body BLOB NOT NULL CHECK(length(body)>0),
 UNIQUE(exit_id,message_id), UNIQUE(exit_id,outbound_seq), UNIQUE(release_id,prepare_id),
 FOREIGN KEY(release_id) REFERENCES er_request_commit(release_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE er_request_commit(
 release_id TEXT PRIMARY KEY NOT NULL REFERENCES er_request(release_id),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE er_ack(
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 ack_id TEXT PRIMARY KEY NOT NULL, release_id TEXT NOT NULL UNIQUE REFERENCES er_request_commit(release_id),
 prepare_id TEXT NOT NULL, exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 release_revision TEXT NOT NULL, release_digest TEXT NOT NULL,
 message_id TEXT NOT NULL, inbound_seq TEXT NOT NULL CHECK(length(inbound_seq)=20 AND inbound_seq NOT GLOB '*[^0-9]*' AND inbound_seq>'00000000000000000000'),
 reply_to TEXT NOT NULL, release_frame_digest TEXT NOT NULL,
 disposed_tick TEXT NOT NULL CHECK(length(disposed_tick)=20 AND disposed_tick NOT GLOB '*[^0-9]*'),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 state TEXT NOT NULL CHECK(state='released'), encoder_quiescent INTEGER NOT NULL CHECK(encoder_quiescent=1),
 consumers_quiescent INTEGER NOT NULL CHECK(consumers_quiescent=1), cache_empty INTEGER NOT NULL CHECK(cache_empty=1),
 frame_digest TEXT NOT NULL, frame_body BLOB NOT NULL CHECK(length(frame_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 UNIQUE(exit_id,message_id), UNIQUE(exit_id,inbound_seq), UNIQUE(ack_id,prepare_id),
 FOREIGN KEY(release_id,prepare_id) REFERENCES er_request(release_id,prepare_id),
 FOREIGN KEY(ack_id) REFERENCES er_ack_commit(ack_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE er_adoption(
 adoption_id TEXT PRIMARY KEY NOT NULL, adoption_revision TEXT NOT NULL CHECK(adoption_revision='00000000000000000001'),
 adoption_digest TEXT NOT NULL, prepare_id TEXT NOT NULL UNIQUE,
 ack_id TEXT NOT NULL UNIQUE, release_id TEXT NOT NULL,
 reservation_id TEXT NOT NULL, reservation_revision TEXT NOT NULL, reservation_digest TEXT NOT NULL,
 reserved_bytes INTEGER NOT NULL CHECK(reserved_bytes BETWEEN 1 AND 65536),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 body BLOB NOT NULL CHECK(length(body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(prepare_id,adoption_id),
 FOREIGN KEY(ack_id,prepare_id) REFERENCES er_ack(ack_id,prepare_id),
 FOREIGN KEY(release_id,prepare_id) REFERENCES er_request(release_id,prepare_id),
 FOREIGN KEY(prepare_id,adoption_id) REFERENCES ep_release(prepare_id,worker_adoption_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE er_ack_commit(
 ack_id TEXT PRIMARY KEY NOT NULL REFERENCES er_ack(ack_id),
 disposition TEXT NOT NULL CHECK(disposition IN ('released','historical')),
 adoption_id TEXT UNIQUE REFERENCES er_adoption(adoption_id) DEFERRABLE INITIALLY DEFERRED,
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK((disposition='released' AND adoption_id IS NOT NULL) OR (disposition='historical' AND adoption_id IS NULL))
) STRICT;
CREATE TRIGGER er_revocation_guard BEFORE INSERT ON ep_revocation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request_commit WHERE prepare_id=NEW.prepare_id AND committed_tick<=NEW.revoked_tick)
 THEN RAISE(ABORT,'encoding_revocation_time') END;
END;
CREATE TRIGGER er_request_guard BEFORE INSERT ON er_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ep_request_commit c USING(prepare_id)
 JOIN ep_send_attempt s USING(prepare_id) JOIN ep_revocation v USING(prepare_id) JOIN ij_encoding_frame j USING(prepare_id)
 WHERE r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id
 AND r.authorization_id=NEW.authorization_id AND r.authorization_digest=NEW.authorization_digest
 AND r.request_message_id=NEW.encode_message_id AND j.request_frame_digest=NEW.encode_frame_digest
 AND v.revocation_id=NEW.revocation_id AND v.revocation_revision=NEW.revocation_revision AND v.revocation_digest=NEW.revocation_digest
 AND v.revoked_tick<=NEW.selected_tick AND s.attempted_tick<=NEW.selected_tick
 AND NOT EXISTS(SELECT 1 FROM ep_release f WHERE f.prepare_id=r.prepare_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id))
 THEN RAISE(ABORT,'encoding_release_request_source') END;
END;
CREATE TRIGGER er_request_seal BEFORE INSERT ON er_request_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_request r WHERE r.release_id=NEW.release_id
 AND r.selected_tick<=NEW.committed_tick AND r.frame_body=NEW.outbox_body
 AND NOT EXISTS(SELECT 1 FROM ep_release f WHERE f.prepare_id=r.prepare_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id))
 THEN RAISE(ABORT,'encoding_release_request_seal') END;
END;
CREATE TRIGGER er_ack_guard BEFORE INSERT ON er_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_request r JOIN er_request_commit c USING(release_id)
 WHERE r.release_id=NEW.release_id AND r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id
 AND r.release_revision=NEW.release_revision AND r.release_digest=NEW.release_digest
 AND r.message_id=NEW.reply_to AND r.frame_digest=NEW.release_frame_digest
 AND r.selected_tick<=NEW.disposed_tick AND c.committed_tick<=NEW.disposed_tick AND NEW.disposed_tick<=NEW.received_tick)
 THEN RAISE(ABORT,'encoding_release_ack_source') END;
END;
CREATE TRIGGER er_adoption_guard BEFORE INSERT ON er_adoption BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_ack a JOIN er_request q USING(release_id) JOIN ep_request r ON r.prepare_id=a.prepare_id
 WHERE a.ack_id=NEW.ack_id AND a.prepare_id=NEW.prepare_id AND a.release_id=NEW.release_id
 AND r.reservation_id=NEW.reservation_id AND r.reservation_revision=NEW.reservation_revision AND r.reservation_digest=NEW.reservation_digest
 AND r.max_bytes=NEW.reserved_bytes AND a.received_tick=NEW.received_tick AND NEW.received_tick<=NEW.committed_tick
 AND NOT EXISTS(SELECT 1 FROM ep_release f WHERE f.prepare_id=r.prepare_id))
 THEN RAISE(ABORT,'encoding_release_adoption_source') END;
END;
CREATE TRIGGER er_ack_seal BEFORE INSERT ON er_ack_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_ack a JOIN ep_release f USING(prepare_id)
 WHERE a.ack_id=NEW.ack_id AND a.received_tick<=NEW.committed_tick AND
 ((NEW.disposition='released' AND f.basis='worker_released' AND f.worker_adoption_id=NEW.adoption_id
 AND EXISTS(SELECT 1 FROM er_adoption d WHERE d.adoption_id=NEW.adoption_id AND d.ack_id=NEW.ack_id AND d.committed_tick=NEW.committed_tick))
 OR (NEW.disposition='historical' AND f.basis='supervisor_retired' AND f.retirement_exit_id=a.exit_id)))
 THEN RAISE(ABORT,'encoding_release_ack_seal') END;
END;
CREATE TRIGGER er_worker_refund BEFORE INSERT ON ep_release WHEN NEW.basis='worker_released' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_adoption d JOIN er_ack a USING(ack_id)
 WHERE d.adoption_id=NEW.worker_adoption_id AND d.prepare_id=NEW.prepare_id AND a.prepare_id=NEW.prepare_id)
 THEN RAISE(ABORT,'encoding_release_refund_source') END;
END;
-- 旧packet仍可作为历史保留，但所有新许可（含协议重传）和最后提交重核永久撤回。
CREATE VIEW er_packet_revoked AS SELECT p.packet_id FROM ep_reply p JOIN ep_revocation r USING(prepare_id);
CREATE TRIGGER er_ordinary_issue BEFORE INSERT ON ce_permit WHEN EXISTS(SELECT 1 FROM er_packet_revoked WHERE packet_id=NEW.packet_id)
 BEGIN SELECT RAISE(ABORT,'encoding_prepare_revoked'); END;
CREATE TRIGGER er_cancel_issue BEFORE INSERT ON ci_cancel_transmission WHEN EXISTS(SELECT 1 FROM er_packet_revoked WHERE packet_id=NEW.packet_id)
 BEGIN SELECT RAISE(ABORT,'encoding_prepare_revoked'); END;
CREATE TRIGGER er_ordinary_commit BEFORE INSERT ON ce_transmission_commit WHEN EXISTS(SELECT 1 FROM ce_permit p JOIN er_packet_revoked r USING(packet_id) WHERE p.permit_id=NEW.permit_id)
 BEGIN SELECT RAISE(ABORT,'encoding_prepare_revoked'); END;
CREATE TRIGGER er_cancel_commit BEFORE INSERT ON ci_cancel_commit WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission p JOIN er_packet_revoked r USING(packet_id) WHERE p.permit_id=NEW.permit_id)
 BEGIN SELECT RAISE(ABORT,'encoding_prepare_revoked'); END;
CREATE VIEW er_recovery AS SELECT q.release_id,q.prepare_id,q.exit_id,q.message_id,q.frame_digest,q.frame_body,
 CASE WHEN a.ack_id IS NOT NULL THEN 'query_recorded_ack' WHEN f.prepare_id IS NOT NULL THEN 'query_recorded_release'
 WHEN t.exit_id IS NOT NULL THEN 'retired_requires_refund_commit' ELSE 'same_session_query_or_repeat_original' END AS recovery_action
 FROM er_request q JOIN er_request_commit c USING(release_id) LEFT JOIN er_ack a USING(release_id)
 LEFT JOIN er_ack_commit k USING(ack_id) LEFT JOIN ep_release f ON f.prepare_id=q.prepare_id
 LEFT JOIN ce_retirement t ON t.exit_id=q.exit_id;

CREATE TRIGGER er_request_u BEFORE UPDATE ON er_request BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_request_d BEFORE DELETE ON er_request BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_request_commit_u BEFORE UPDATE ON er_request_commit BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_request_commit_d BEFORE DELETE ON er_request_commit BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_ack_u BEFORE UPDATE ON er_ack BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_ack_d BEFORE DELETE ON er_ack BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_adoption_u BEFORE UPDATE ON er_adoption BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_adoption_d BEFORE DELETE ON er_adoption BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_ack_commit_u BEFORE UPDATE ON er_ack_commit BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

CREATE TRIGGER er_ack_commit_d BEFORE DELETE ON er_ack_commit BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;

-- 只与固定207表修订版组合；所有原件解码/JCS/端点真实性由受信提供者外验。
CREATE TABLE ij_type(name TEXT PRIMARY KEY NOT NULL,direction TEXT NOT NULL CHECK(direction IN ('c2w','w2c')),
 response INTEGER NOT NULL CHECK(response IN (0,1)),protected INTEGER NOT NULL CHECK(protected IN (0,1))) STRICT;
CREATE TABLE ij_reply_type(response_type TEXT NOT NULL REFERENCES ij_type(name),request_type TEXT NOT NULL REFERENCES ij_type(name),
 PRIMARY KEY(response_type,request_type)) STRICT;
CREATE TABLE ij_session(
 session_id TEXT PRIMARY KEY NOT NULL,scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
 controller_boot_id TEXT NOT NULL,worker_boot_id TEXT NOT NULL,ipc_session_id TEXT NOT NULL,
 clock_domain_id TEXT NOT NULL,descriptor_digest TEXT NOT NULL,protocol_version TEXT NOT NULL CHECK(protocol_version='ipc/0.13.0-journal-draft.1'),
 profile_body BLOB NOT NULL CHECK(length(profile_body)>0),binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 max_frames INTEGER NOT NULL CHECK(max_frames BETWEEN 4 AND 65536),reserved_frames INTEGER NOT NULL CHECK(reserved_frames BETWEEN 1 AND max_frames-2),
 max_bytes INTEGER NOT NULL CHECK(max_bytes BETWEEN 1 AND 9007199254740991),reserved_bytes INTEGER NOT NULL CHECK(reserved_bytes BETWEEN 1 AND max_bytes-1),
 UNIQUE(controller_boot_id,worker_boot_id,ipc_session_id)
) STRICT;
CREATE TABLE ij_exit(
 exit_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_exit(exit_id),session_id TEXT NOT NULL REFERENCES ij_session(session_id),
 UNIQUE(session_id,exit_id)
) STRICT;
CREATE TRIGGER ij_exit_guard BEFORE INSERT ON ij_exit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_session s JOIN ce_exit e ON e.exit_id=NEW.exit_id
 WHERE s.session_id=NEW.session_id AND s.controller_boot_id=e.controller_boot_id AND s.worker_boot_id=e.worker_boot_id
 AND s.ipc_session_id=e.ipc_session_id AND s.clock_domain_id=e.clock_domain_id AND s.descriptor_digest=e.descriptor_digest)
 OR EXISTS(SELECT 1 FROM ij_end WHERE session_id=NEW.session_id) THEN RAISE(ABORT,'journal_exit_binding') END;
END;
CREATE TABLE ij_frame(
 frame_id TEXT PRIMARY KEY NOT NULL,session_id TEXT NOT NULL REFERENCES ij_session(session_id),exit_id TEXT,device_id TEXT,
 direction TEXT NOT NULL CHECK(direction IN ('c2w','w2c')),message_type TEXT NOT NULL REFERENCES ij_type(name),
 message_id TEXT NOT NULL,seq TEXT NOT NULL CHECK(length(seq)=20 AND seq NOT GLOB '*[^0-9]*' AND seq>'00000000000000000000'),
 reply_frame_id TEXT REFERENCES ij_frame(frame_id),reply_to TEXT,
 frame_digest TEXT NOT NULL,wire_digest TEXT NOT NULL,frame_body BLOB NOT NULL CHECK(length(frame_body)>0),
 body_body BLOB NOT NULL CHECK(length(body_body)>0),
 wire_body BLOB NOT NULL CHECK(length(wire_body)>0),wire_length INTEGER NOT NULL CHECK(wire_length=length(wire_body) AND wire_length<=262148),
 observed_tick TEXT NOT NULL CHECK(length(observed_tick)=20 AND observed_tick NOT GLOB '*[^0-9]*'),
 domain_kind TEXT NOT NULL,domain_id TEXT NOT NULL,validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 CHECK((exit_id IS NULL AND device_id IS NULL) OR (exit_id IS NOT NULL AND device_id IS NOT NULL)),
 CHECK((reply_frame_id IS NULL AND reply_to IS NULL) OR (reply_frame_id IS NOT NULL AND reply_to IS NOT NULL)),
 UNIQUE(session_id,direction,seq),UNIQUE(session_id,direction,message_id),UNIQUE(domain_kind,domain_id),
 FOREIGN KEY(session_id,exit_id) REFERENCES ij_exit(session_id,exit_id),
 FOREIGN KEY(frame_id) REFERENCES ij_commit(frame_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ij_commit(
 frame_id TEXT PRIMARY KEY NOT NULL REFERENCES ij_frame(frame_id),disposition TEXT NOT NULL CHECK(disposition IN ('applied','historical','rejected')),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),effect_body BLOB NOT NULL CHECK(length(effect_body)>0)
) STRICT;
CREATE TABLE ij_write_attempt(
 frame_id TEXT PRIMARY KEY NOT NULL REFERENCES ij_commit(frame_id),attempt_id TEXT NOT NULL UNIQUE,
 attempted_tick TEXT NOT NULL CHECK(length(attempted_tick)=20 AND attempted_tick NOT GLOB '*[^0-9]*'),
 encoding_prepare_id TEXT UNIQUE REFERENCES ep_send_attempt(prepare_id) DEFERRABLE INITIALLY DEFERRED,
 current_validation_body BLOB NOT NULL CHECK(length(current_validation_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ij_end(
 end_id TEXT PRIMARY KEY NOT NULL,session_id TEXT NOT NULL UNIQUE REFERENCES ij_session(session_id),
 reason TEXT NOT NULL CHECK(reason IN ('storage_unknown','protocol_error','write_uncertain','peer_lost','shutdown','volatile_close')),
 cause_frame_id TEXT REFERENCES ij_frame(frame_id),observed_tick TEXT NOT NULL CHECK(length(observed_tick)=20 AND observed_tick NOT GLOB '*[^0-9]*'),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ij_write_result(
 frame_id TEXT PRIMARY KEY NOT NULL REFERENCES ij_write_attempt(frame_id),state TEXT NOT NULL CHECK(state IN ('written','uncertain')),
 completed_tick TEXT NOT NULL CHECK(length(completed_tick)=20 AND completed_tick NOT GLOB '*[^0-9]*'),
 written_bytes INTEGER NOT NULL CHECK(written_bytes>=0),end_id TEXT REFERENCES ij_end(end_id),
 result_body BLOB NOT NULL CHECK(length(result_body)>0),CHECK((state='written' AND end_id IS NULL) OR (state='uncertain' AND end_id IS NOT NULL))
) STRICT;
CREATE TABLE ij_rejection(
 rejection_id TEXT PRIMARY KEY NOT NULL,frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 reason TEXT NOT NULL CHECK(length(reason)>0),evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0)
) STRICT;
CREATE TABLE ij_handshake(
 handshake_id TEXT PRIMARY KEY NOT NULL,frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 kind TEXT NOT NULL CHECK(kind IN ('HELLO','HELLO_ACK')),negotiation_body BLOB NOT NULL CHECK(length(negotiation_body)>0)
) STRICT;
CREATE TABLE ij_encoding_frame(
 prepare_id TEXT PRIMARY KEY NOT NULL REFERENCES ep_request_commit(prepare_id),journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 request_seq TEXT NOT NULL CHECK(length(request_seq)=20 AND request_seq NOT GLOB '*[^0-9]*' AND request_seq>'00000000000000000000'),
 request_frame_digest TEXT NOT NULL,request_frame BLOB NOT NULL CHECK(length(request_frame)>0)
) STRICT;
CREATE TRIGGER ij_frame_guard BEFORE INSERT ON ij_frame BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_type WHERE name=NEW.message_type AND direction=NEW.direction)
 THEN RAISE(ABORT,'journal_direction') END;
 SELECT CASE WHEN NEW.exit_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ij_exit x JOIN ce_exit e USING(exit_id)
 WHERE x.session_id=NEW.session_id AND x.exit_id=NEW.exit_id AND e.device_id=NEW.device_id) THEN RAISE(ABORT,'journal_device') END;
 SELECT CASE WHEN (NEW.message_type IN ('HELLO','HELLO_ACK','CLOSE_GATE_ACK') AND NEW.exit_id IS NOT NULL)
 OR (NEW.message_type NOT IN ('HELLO','HELLO_ACK','CLOSE_GATE_ACK','CLOSE_GATE') AND NEW.exit_id IS NULL)
 THEN RAISE(ABORT,'journal_device_shape') END;
 SELECT CASE WHEN NEW.direction='c2w' AND EXISTS(SELECT 1 FROM ij_end WHERE session_id=NEW.session_id)
 THEN RAISE(ABORT,'journal_session_ended') END;
 SELECT CASE WHEN NEW.seq!=coalesce((SELECT CASE WHEN substr(seq,11,10)='9999999999'
 THEN printf('%010d',CAST(substr(seq,1,10) AS INTEGER)+1)||'0000000000'
 ELSE substr(seq,1,10)||printf('%010d',CAST(substr(seq,11,10) AS INTEGER)+1) END
 FROM ij_frame WHERE session_id=NEW.session_id AND direction=NEW.direction ORDER BY seq DESC LIMIT 1),'00000000000000000001')
 THEN RAISE(ABORT,'journal_sequence') END;
 SELECT CASE WHEN (NEW.seq='00000000000000000001' AND NEW.message_type!=CASE NEW.direction WHEN 'w2c' THEN 'HELLO' ELSE 'HELLO_ACK' END)
 OR (NEW.seq>'00000000000000000001' AND NOT EXISTS(SELECT 1 FROM ij_frame f JOIN ij_commit c USING(frame_id)
 WHERE f.session_id=NEW.session_id AND f.message_type='HELLO_ACK' AND c.disposition='applied'))
 THEN RAISE(ABORT,'journal_handshake') END;
 SELECT CASE WHEN (SELECT response FROM ij_type WHERE name=NEW.message_type)=0 AND NEW.reply_to IS NOT NULL
 THEN RAISE(ABORT,'journal_nonresponse') END;
 SELECT CASE WHEN (SELECT response FROM ij_type WHERE name=NEW.message_type)=1 AND NOT EXISTS(
 SELECT 1 FROM ij_frame r JOIN ij_commit c ON c.frame_id=r.frame_id JOIN ij_reply_type t ON t.request_type=r.message_type
 WHERE t.response_type=NEW.message_type AND r.frame_id=NEW.reply_frame_id AND r.message_id=NEW.reply_to
 AND r.session_id=NEW.session_id AND r.direction!=NEW.direction AND r.observed_tick<=NEW.observed_tick
 AND (r.direction='w2c' OR EXISTS(SELECT 1 FROM ij_write_attempt a WHERE a.frame_id=r.frame_id))
 AND (NEW.message_type='CLOSE_GATE_ACK' OR (r.exit_id IS NEW.exit_id AND r.device_id IS NEW.device_id)))
 THEN RAISE(ABORT,'journal_reply_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ij_session s WHERE s.session_id=NEW.session_id AND
 ((SELECT count(*) FROM ij_frame f WHERE f.session_id=s.session_id)>=s.max_frames-
 CASE (SELECT protected FROM ij_type WHERE name=NEW.message_type) WHEN 1 THEN 0 ELSE s.reserved_frames END
 OR NEW.wire_length>s.max_bytes-CASE (SELECT protected FROM ij_type WHERE name=NEW.message_type) WHEN 1 THEN 0 ELSE s.reserved_bytes END-
 coalesce((SELECT sum(f.wire_length) FROM ij_frame f WHERE f.session_id=s.session_id),0)))
 THEN RAISE(ABORT,'journal_capacity') END;
END;
CREATE TRIGGER ij_commit_guard BEFORE INSERT ON ij_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND f.observed_tick<=NEW.committed_tick
 AND NOT(f.direction='c2w' AND EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id))
 AND NOT(NEW.disposition='applied' AND EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)))
 THEN RAISE(ABORT,'journal_commit_current') END;
 -- 每个实际领域原件由生成器补精确双向关系；未迁移类型只能保存明确拒收记录。
END;
CREATE TRIGGER ij_attempt_guard BEFORE INSERT ON ij_write_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f JOIN ij_commit c USING(frame_id)
 WHERE f.frame_id=NEW.frame_id AND f.direction='c2w' AND c.disposition='applied' AND c.committed_tick<=NEW.attempted_tick
 AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)
 AND NOT EXISTS(SELECT 1 FROM ij_frame p WHERE p.session_id=f.session_id AND p.direction='c2w' AND p.seq<f.seq
 AND NOT EXISTS(SELECT 1 FROM ij_write_result r WHERE r.frame_id=p.frame_id AND r.state='written'))
 AND ((f.domain_kind='encoding_request' AND NEW.encoding_prepare_id=f.domain_id
 AND EXISTS(SELECT 1 FROM ep_send_attempt p WHERE p.prepare_id=NEW.encoding_prepare_id AND p.journal_frame_id=NEW.frame_id
 AND p.attempt_id=NEW.attempt_id AND p.attempted_tick=NEW.attempted_tick))
 OR (f.domain_kind!='encoding_request' AND NEW.encoding_prepare_id IS NULL))) THEN RAISE(ABORT,'journal_attempt_prefix') END;
END;
CREATE TRIGGER ij_attempt_domain BEFORE INSERT ON ij_write_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND
 ((f.domain_kind='open_request' AND NOT EXISTS(SELECT 1 FROM go_dispatch d JOIN go_valid_plan p USING(plan_id)
 WHERE d.journal_frame_id=f.frame_id AND NEW.attempted_tick<p.expires_tick))
 OR (f.domain_kind='renewal_request' AND NOT EXISTS(SELECT 1 FROM gf_context r WHERE r.journal_frame_id=f.frame_id
 AND NEW.attempted_tick<r.expires_tick AND (r.previous_gate_id IS NULL OR EXISTS(SELECT 1 FROM go_current_gate g WHERE g.gate_id=r.previous_gate_id))))
 OR (f.domain_kind='release_request' AND NOT EXISTS(SELECT 1 FROM er_request r WHERE r.journal_frame_id=f.frame_id
 AND NOT EXISTS(SELECT 1 FROM ep_release a WHERE a.prepare_id=r.prepare_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id)))))
 THEN RAISE(ABORT,'journal_send_not_current') END;
END;
CREATE TRIGGER ij_request_current BEFORE INSERT ON ep_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_exit x WHERE x.exit_id=NEW.exit_id
 AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id)) THEN RAISE(ABORT,'journal_prepare_session') END;
END;
CREATE TRIGGER ij_result_guard BEFORE INSERT ON ij_write_result BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_write_attempt a JOIN ij_frame f USING(frame_id)
 WHERE a.frame_id=NEW.frame_id AND a.attempted_tick<=NEW.completed_tick AND NEW.written_bytes<=f.wire_length
 AND ((NEW.state='written' AND NEW.written_bytes=f.wire_length)
 OR (NEW.state='uncertain' AND EXISTS(SELECT 1 FROM ij_end e WHERE e.end_id=NEW.end_id AND e.session_id=f.session_id
 AND e.cause_frame_id=f.frame_id AND e.observed_tick<=NEW.completed_tick)))) THEN RAISE(ABORT,'journal_write_result') END;
END;
CREATE TRIGGER ij_end_guard BEFORE INSERT ON ij_end WHEN NEW.cause_frame_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.cause_frame_id AND f.session_id=NEW.session_id
 AND f.observed_tick<=NEW.observed_tick) THEN RAISE(ABORT,'journal_end_source') END;
END;
CREATE TRIGGER ij_encoding_attempt BEFORE INSERT ON ep_send_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_encoding_frame e JOIN ij_commit c ON c.frame_id=e.journal_frame_id
 WHERE e.prepare_id=NEW.prepare_id AND e.journal_frame_id=NEW.journal_frame_id AND c.disposition='applied'
 AND c.committed_tick<=NEW.attempted_tick AND e.request_frame_digest=NEW.request_frame_digest)
 THEN RAISE(ABORT,'journal_encoding_attempt') END;
END;
CREATE VIEW ij_recovery AS SELECT f.frame_id,f.session_id,f.direction,f.message_type,
 CASE WHEN c.disposition='rejected' THEN 'query_rejection_never_send'
 WHEN f.direction='w2c' THEN 'query_committed_inbox'
 WHEN e.end_id IS NOT NULL THEN 'ended_never_replay'
 WHEN r.state='written' THEN 'written_not_peer_processed'
 WHEN a.frame_id IS NOT NULL THEN 'attempted_query_or_retire'
 ELSE 'unattempted_current_session_only' END AS recovery_action
 FROM ij_frame f JOIN ij_commit c USING(frame_id) LEFT JOIN ij_write_attempt a USING(frame_id)
 LEFT JOIN ij_write_result r USING(frame_id) LEFT JOIN ij_end e USING(session_id);

CREATE TRIGGER ij_metadata_guard BEFORE INSERT ON ep_request BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM ep_request WHERE exit_id=NEW.exit_id)>=(SELECT max_metadata_prepares FROM ep_limit WHERE singleton=NEW.scope_id) THEN RAISE(ABORT,'encoding_metadata_capacity') END;
END;

CREATE TRIGGER ij_bind_ij_encoding_frame BEFORE INSERT ON ij_encoding_frame BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND f.domain_kind='encoding_request' AND f.domain_id=NEW.prepare_id AND f.direction='c2w' AND f.message_type IN ('ENCODE_PACKET','ENCODE_CANCEL_PACKET') AND f.seq=NEW.request_seq AND EXISTS(SELECT 1 FROM ep_open_request r JOIN ep_request_commit k USING(prepare_id) WHERE r.prepare_id=NEW.prepare_id AND r.exit_id=f.exit_id AND r.request_message_id=f.message_id AND k.committed_tick<=f.observed_tick AND f.observed_tick<r.expires_tick AND f.message_type=CASE r.kind WHEN 'ordinary' THEN 'ENCODE_PACKET' ELSE 'ENCODE_CANCEL_PACKET' END) AND f.frame_body=NEW.request_frame AND f.frame_digest=NEW.request_frame_digest AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_bind_ep_reply BEFORE INSERT ON ep_reply BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND f.domain_kind='encoding_reply' AND f.domain_id=NEW.prepare_id AND f.direction='w2c' AND f.message_type IN ('PREPARE_PACKET','PACKET_ENCODING_FAILED','PREPARE_CANCEL_PACKET','CANCEL_ENCODING_FAILED') AND f.seq=NEW.response_seq AND f.exit_id=NEW.exit_id AND f.message_id=NEW.response_message_id AND f.reply_to=NEW.reply_to AND f.frame_body=NEW.response_frame AND f.frame_digest=NEW.response_frame_digest AND f.observed_tick=NEW.received_tick AND EXISTS(SELECT 1 FROM ep_request r WHERE r.prepare_id=NEW.prepare_id AND NEW.outcome IN ('prepared','failed') AND f.message_type=CASE WHEN r.kind='ordinary' AND NEW.outcome='prepared' THEN 'PREPARE_PACKET' WHEN r.kind='ordinary' THEN 'PACKET_ENCODING_FAILED' WHEN NEW.outcome='prepared' THEN 'PREPARE_CANCEL_PACKET' ELSE 'CANCEL_ENCODING_FAILED' END) AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_bind_er_request BEFORE INSERT ON er_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND f.domain_kind='release_request' AND f.domain_id=NEW.release_id AND f.direction='c2w' AND f.message_type IN ('RELEASE_ENCODING') AND f.seq=NEW.outbound_seq AND f.exit_id=NEW.exit_id AND f.message_id=NEW.message_id AND f.frame_body=NEW.frame_body AND f.frame_digest=NEW.frame_digest AND f.observed_tick=NEW.selected_tick AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_bind_er_ack BEFORE INSERT ON er_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND f.domain_kind='release_ack' AND f.domain_id=NEW.ack_id AND f.direction='w2c' AND f.message_type IN ('RELEASE_ENCODING_ACK') AND f.seq=NEW.inbound_seq AND f.exit_id=NEW.exit_id AND f.message_id=NEW.message_id AND f.reply_to=NEW.reply_to AND f.frame_body=NEW.frame_body AND f.frame_digest=NEW.frame_digest AND f.observed_tick=NEW.received_tick AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_bind_go_dispatch BEFORE INSERT ON go_dispatch BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND f.domain_kind='open_request' AND f.domain_id=NEW.dispatch_id AND f.direction='c2w' AND f.message_type IN ('OPEN_GATE') AND f.seq=NEW.outbound_seq AND f.exit_id=NEW.exit_id AND f.message_id=NEW.message_id AND f.frame_body=NEW.frame_body AND f.frame_digest=NEW.frame_digest AND f.observed_tick=NEW.reserved_tick AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_bind_go_evidence BEFORE INSERT ON go_evidence BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND f.domain_kind='open_ack' AND f.domain_id=NEW.evidence_id AND f.direction='w2c' AND f.message_type IN ('OPEN_GATE_ACK') AND f.seq=NEW.inbound_seq AND f.exit_id=NEW.exit_id AND f.message_id=NEW.message_id AND f.reply_to=NEW.reply_to AND f.frame_body=NEW.frame_body AND f.observed_tick=NEW.received_tick AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_bind_gf_request BEFORE INSERT ON gf_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND f.domain_kind='renewal_request' AND f.domain_id=NEW.request_id AND f.direction='c2w' AND f.message_type IN ('GATE_FENCE') AND f.seq=NEW.outbound_seq AND f.exit_id=NEW.exit_id AND f.message_id=NEW.message_id AND f.body_body=NEW.body AND f.observed_tick=NEW.selected_tick AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_bind_gf_ack BEFORE INSERT ON gf_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND f.domain_kind='renewal_ack' AND f.domain_id=NEW.ack_id AND f.direction='w2c' AND f.message_type IN ('GATE_FENCE_ACK') AND f.seq=NEW.inbound_seq AND f.exit_id=NEW.exit_id AND f.message_id=NEW.message_id AND f.reply_to=NEW.reply_to AND f.body_body=NEW.body AND f.observed_tick=NEW.received_tick AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_domain_seal BEFORE INSERT ON ij_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND ((f.domain_kind='encoding_request' AND EXISTS(SELECT 1 FROM ij_encoding_frame d WHERE d.prepare_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition='applied')) OR
 (f.domain_kind='encoding_reply' AND EXISTS(SELECT 1 FROM ep_reply d WHERE d.prepare_id=f.domain_id AND d.journal_frame_id=f.frame_id AND EXISTS(SELECT 1 FROM ep_receive_commit c WHERE c.prepare_id=d.prepare_id AND c.committed_tick=NEW.committed_tick AND NEW.disposition=CASE c.disposition WHEN 'historical' THEN 'historical' ELSE 'applied' END))) OR
 (f.domain_kind='release_request' AND EXISTS(SELECT 1 FROM er_request d WHERE d.release_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM er_request_commit c WHERE c.release_id=d.release_id AND c.committed_tick=NEW.committed_tick))) OR
 (f.domain_kind='release_ack' AND EXISTS(SELECT 1 FROM er_ack d WHERE d.ack_id=f.domain_id AND d.journal_frame_id=f.frame_id AND EXISTS(SELECT 1 FROM er_ack_commit c WHERE c.ack_id=d.ack_id AND c.committed_tick=NEW.committed_tick AND NEW.disposition=CASE c.disposition WHEN 'historical' THEN 'historical' ELSE 'applied' END))) OR
 (f.domain_kind='open_request' AND EXISTS(SELECT 1 FROM go_dispatch d WHERE d.dispatch_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition='applied')) OR
 (f.domain_kind='open_ack' AND EXISTS(SELECT 1 FROM go_evidence d WHERE d.evidence_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition IN ('applied','historical'))) OR
 (f.domain_kind='renewal_request' AND EXISTS(SELECT 1 FROM gf_request d WHERE d.request_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition='applied')) OR
 (f.domain_kind='renewal_ack' AND EXISTS(SELECT 1 FROM gf_ack d WHERE d.ack_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition IN ('applied','historical'))) OR
 (f.domain_kind='prepare_deny_request' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM pd_deny_request d WHERE d.deny_id=f.domain_id AND d.journal_frame_id=f.frame_id)) OR
 (f.domain_kind='prepare_deny_ack' AND NEW.disposition IN ('applied','historical') AND EXISTS(SELECT 1 FROM pd_deny_ack d WHERE d.ack_id=f.domain_id AND d.journal_frame_id=f.frame_id)) OR
 (f.domain_kind='handshake' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM ij_handshake d WHERE d.handshake_id=f.domain_id AND d.frame_id=f.frame_id AND d.kind=f.message_type)) OR
 (f.domain_kind='rejection' AND f.direction='w2c' AND NEW.disposition='rejected' AND EXISTS(SELECT 1 FROM ij_rejection d WHERE d.rejection_id=f.domain_id AND d.frame_id=f.frame_id)))) THEN RAISE(ABORT,'journal_missing_domain_commit') END;
END;

CREATE TRIGGER ij_bind_ij_handshake BEFORE INSERT ON ij_handshake BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND f.domain_kind='handshake' AND f.domain_id=NEW.handshake_id AND f.message_type=NEW.kind AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_bind_ij_rejection BEFORE INSERT ON ij_rejection BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND f.domain_kind='rejection' AND f.domain_id=NEW.rejection_id AND f.direction='w2c' AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;
END;

CREATE TRIGGER ij_current_go_ready BEFORE INSERT ON go_ready BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_evidence a JOIN ij_frame f ON f.frame_id=a.journal_frame_id JOIN ij_commit c USING(frame_id) WHERE a.evidence_id=NEW.evidence_id AND c.disposition='applied' AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)) THEN RAISE(ABORT,'journal_adoption_not_current') END;
END;

CREATE TRIGGER ij_current_gs_scope_commit BEFORE INSERT ON gs_scope_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_evidence a JOIN ij_frame f ON f.frame_id=a.journal_frame_id JOIN ij_commit c USING(frame_id) WHERE a.evidence_id=NEW.evidence_id AND c.disposition='applied' AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)) THEN RAISE(ABORT,'journal_adoption_not_current') END;
END;

CREATE TRIGGER ij_current_gf_commit BEFORE INSERT ON gf_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_ack a JOIN ij_frame f ON f.frame_id=a.journal_frame_id JOIN ij_commit c USING(frame_id) WHERE a.ack_id=NEW.ack_id AND c.disposition='applied' AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)) THEN RAISE(ABORT,'journal_adoption_not_current') END;
END;

CREATE VIEW pd_base_go_ready_candidate AS SELECT b.* FROM ij_base_go_ready_candidate b JOIN ij_exit x ON x.exit_id=b.exit_id WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id);

CREATE VIEW gs_scope_candidate AS SELECT b.* FROM ij_base_gs_scope_candidate b JOIN ij_exit x ON x.exit_id=b.exit_id WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id);

CREATE VIEW gf_valid_fence AS SELECT b.* FROM ij_base_gf_valid_fence b JOIN ij_exit x ON x.exit_id=b.exit_id WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id);

CREATE VIEW ep_open_request AS SELECT b.* FROM ij_base_ep_open_request b JOIN ij_exit x ON x.exit_id=b.exit_id WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id);
INSERT INTO ij_type VALUES('HELLO_ACK','c2w',1,1);
INSERT INTO ij_type VALUES('OPEN_GATE','c2w',0,0);
INSERT INTO ij_type VALUES('DISPATCH','c2w',0,0);
INSERT INTO ij_type VALUES('REPORT_STORED','c2w',0,1);
INSERT INTO ij_type VALUES('FENCE','c2w',0,1);
INSERT INTO ij_type VALUES('QUERY_BARRIER','c2w',0,1);
INSERT INTO ij_type VALUES('CLOSE_GATE','c2w',0,1);
INSERT INTO ij_type VALUES('GUARD_INSTALL','c2w',0,0);
INSERT INTO ij_type VALUES('AUTH_FENCE','c2w',0,1);
INSERT INTO ij_type VALUES('TIME_FENCE','c2w',0,1);
INSERT INTO ij_type VALUES('RUN_FENCE','c2w',0,1);
INSERT INTO ij_type VALUES('ENCODE_PACKET','c2w',0,0);
INSERT INTO ij_type VALUES('PREPARE_PACKET_REJECTED','c2w',1,0);
INSERT INTO ij_type VALUES('RESEND_DISPATCH','c2w',1,0);
INSERT INTO ij_type VALUES('RESEND_REJECTED','c2w',1,0);
INSERT INTO ij_type VALUES('BARRIER_STORED','c2w',0,1);
INSERT INTO ij_type VALUES('CANCEL_FENCE','c2w',0,1);
INSERT INTO ij_type VALUES('CANCEL_GUARD','c2w',0,0);
INSERT INTO ij_type VALUES('ENCODE_CANCEL_PACKET','c2w',0,0);
INSERT INTO ij_type VALUES('CANCEL_PREPARE_REJECTED','c2w',1,0);
INSERT INTO ij_type VALUES('DISPATCH_CANCEL','c2w',0,0);
INSERT INTO ij_type VALUES('CANCEL_RESEND_REJECTED','c2w',1,0);
INSERT INTO ij_type VALUES('CANCEL_REPORT_STORED','c2w',0,1);
INSERT INTO ij_type VALUES('QUERY_CANCEL_EXECUTION','c2w',0,0);
INSERT INTO ij_type VALUES('GATE_FENCE','c2w',0,0);
INSERT INTO ij_type VALUES('RELEASE_ENCODING','c2w',0,1);
INSERT INTO ij_type VALUES('DENY_ENCODING','c2w',0,1);
INSERT INTO ij_type VALUES('HELLO','w2c',0,1);
INSERT INTO ij_type VALUES('OPEN_GATE_ACK','w2c',1,0);
INSERT INTO ij_type VALUES('SEND_REPORT','w2c',0,1);
INSERT INTO ij_type VALUES('EVIDENCE_CANDIDATE','w2c',0,0);
INSERT INTO ij_type VALUES('FENCE_ACK','w2c',1,1);
INSERT INTO ij_type VALUES('CLOSE_GATE_ACK','w2c',1,1);
INSERT INTO ij_type VALUES('GUARD_ACK','w2c',1,0);
INSERT INTO ij_type VALUES('AUTH_FENCE_ACK','w2c',1,1);
INSERT INTO ij_type VALUES('TIME_FENCE_ACK','w2c',1,1);
INSERT INTO ij_type VALUES('RUN_FENCE_ACK','w2c',1,1);
INSERT INTO ij_type VALUES('PACKET_ENCODING_FAILED','w2c',1,0);
INSERT INTO ij_type VALUES('PREPARE_PACKET','w2c',1,0);
INSERT INTO ij_type VALUES('RESEND_REQUEST','w2c',0,0);
INSERT INTO ij_type VALUES('BARRIER_UNAVAILABLE','w2c',1,1);
INSERT INTO ij_type VALUES('CANCEL_FENCE_ACK','w2c',1,1);
INSERT INTO ij_type VALUES('CANCEL_GUARD_ACK','w2c',1,0);
INSERT INTO ij_type VALUES('PREPARE_CANCEL_PACKET','w2c',1,0);
INSERT INTO ij_type VALUES('CANCEL_ENCODING_FAILED','w2c',1,0);
INSERT INTO ij_type VALUES('CANCEL_RESEND_REQUEST','w2c',0,0);
INSERT INTO ij_type VALUES('CANCEL_SEND_REPORT','w2c',0,1);
INSERT INTO ij_type VALUES('CANCEL_EVIDENCE_CANDIDATE','w2c',0,0);
INSERT INTO ij_type VALUES('CANCEL_EXECUTION_STATUS','w2c',1,0);
INSERT INTO ij_type VALUES('GATE_FENCE_ACK','w2c',1,0);
INSERT INTO ij_type VALUES('RELEASE_ENCODING_ACK','w2c',1,1);
INSERT INTO ij_type VALUES('DENY_ENCODING_ACK','w2c',1,1);
INSERT INTO ij_reply_type VALUES('HELLO_ACK','HELLO');
INSERT INTO ij_reply_type VALUES('OPEN_GATE_ACK','OPEN_GATE');
INSERT INTO ij_reply_type VALUES('FENCE_ACK','FENCE');
INSERT INTO ij_reply_type VALUES('FENCE_ACK','QUERY_BARRIER');
INSERT INTO ij_reply_type VALUES('CLOSE_GATE_ACK','CLOSE_GATE');
INSERT INTO ij_reply_type VALUES('GUARD_ACK','GUARD_INSTALL');
INSERT INTO ij_reply_type VALUES('AUTH_FENCE_ACK','AUTH_FENCE');
INSERT INTO ij_reply_type VALUES('AUTH_FENCE_ACK','QUERY_BARRIER');
INSERT INTO ij_reply_type VALUES('TIME_FENCE_ACK','TIME_FENCE');
INSERT INTO ij_reply_type VALUES('TIME_FENCE_ACK','QUERY_BARRIER');
INSERT INTO ij_reply_type VALUES('RUN_FENCE_ACK','RUN_FENCE');
INSERT INTO ij_reply_type VALUES('RUN_FENCE_ACK','QUERY_BARRIER');
INSERT INTO ij_reply_type VALUES('PREPARE_PACKET','ENCODE_PACKET');
INSERT INTO ij_reply_type VALUES('PACKET_ENCODING_FAILED','ENCODE_PACKET');
INSERT INTO ij_reply_type VALUES('PREPARE_PACKET_REJECTED','PREPARE_PACKET');
INSERT INTO ij_reply_type VALUES('RESEND_DISPATCH','RESEND_REQUEST');
INSERT INTO ij_reply_type VALUES('RESEND_REJECTED','RESEND_REQUEST');
INSERT INTO ij_reply_type VALUES('BARRIER_UNAVAILABLE','QUERY_BARRIER');
INSERT INTO ij_reply_type VALUES('CANCEL_FENCE_ACK','CANCEL_FENCE');
INSERT INTO ij_reply_type VALUES('CANCEL_FENCE_ACK','QUERY_BARRIER');
INSERT INTO ij_reply_type VALUES('CANCEL_GUARD_ACK','CANCEL_GUARD');
INSERT INTO ij_reply_type VALUES('PREPARE_CANCEL_PACKET','ENCODE_CANCEL_PACKET');
INSERT INTO ij_reply_type VALUES('CANCEL_ENCODING_FAILED','ENCODE_CANCEL_PACKET');
INSERT INTO ij_reply_type VALUES('CANCEL_PREPARE_REJECTED','PREPARE_CANCEL_PACKET');
INSERT INTO ij_reply_type VALUES('CANCEL_RESEND_REJECTED','CANCEL_RESEND_REQUEST');
INSERT INTO ij_reply_type VALUES('CANCEL_EXECUTION_STATUS','QUERY_CANCEL_EXECUTION');
INSERT INTO ij_reply_type VALUES('GATE_FENCE_ACK','GATE_FENCE');
INSERT INTO ij_reply_type VALUES('RELEASE_ENCODING_ACK','RELEASE_ENCODING');
INSERT INTO ij_reply_type VALUES('DENY_ENCODING_ACK','DENY_ENCODING');
CREATE TRIGGER ij_type_u BEFORE UPDATE ON ij_type BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_type_d BEFORE DELETE ON ij_type BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_reply_type_u BEFORE UPDATE ON ij_reply_type BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_reply_type_d BEFORE DELETE ON ij_reply_type BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_session_u BEFORE UPDATE ON ij_session BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_session_d BEFORE DELETE ON ij_session BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_exit_u BEFORE UPDATE ON ij_exit BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_exit_d BEFORE DELETE ON ij_exit BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_frame_u BEFORE UPDATE ON ij_frame BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_frame_d BEFORE DELETE ON ij_frame BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_commit_u BEFORE UPDATE ON ij_commit BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_commit_d BEFORE DELETE ON ij_commit BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_write_attempt_u BEFORE UPDATE ON ij_write_attempt BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_write_attempt_d BEFORE DELETE ON ij_write_attempt BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_end_u BEFORE UPDATE ON ij_end BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_end_d BEFORE DELETE ON ij_end BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_write_result_u BEFORE UPDATE ON ij_write_result BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_write_result_d BEFORE DELETE ON ij_write_result BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_rejection_u BEFORE UPDATE ON ij_rejection BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_rejection_d BEFORE DELETE ON ij_rejection BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_handshake_u BEFORE UPDATE ON ij_handshake BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_handshake_d BEFORE DELETE ON ij_handshake BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_encoding_frame_u BEFORE UPDATE ON ij_encoding_frame BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_encoding_frame_d BEFORE DELETE ON ij_encoding_frame BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;
CREATE TRIGGER ij_type_i BEFORE INSERT ON ij_type BEGIN SELECT RAISE(ABORT,'immutable_journal_policy'); END;
CREATE TRIGGER ij_reply_type_i BEFORE INSERT ON ij_reply_type BEGIN SELECT RAISE(ABORT,'immutable_journal_policy'); END;

-- 准备拒绝与完整集合的同库候选；与共享日志组合，外部原件可信性另验。
CREATE TABLE pd_registration(
 prepare_id TEXT PRIMARY KEY NOT NULL REFERENCES ep_request(prepare_id),
 sequence TEXT NOT NULL UNIQUE CHECK(length(sequence)=20 AND sequence NOT GLOB '*[^0-9]*' AND sequence>'00000000000000000000'),
 origin TEXT NOT NULL CHECK(origin IN ('manual','automation')),prep_key TEXT,receipt_id TEXT,
 control_epoch TEXT NOT NULL,effective_version TEXT NOT NULL,provenance_body BLOB NOT NULL CHECK(length(provenance_body)>0),
 CHECK((origin='manual' AND prep_key IS NULL AND receipt_id IS NULL) OR (origin='automation' AND prep_key IS NOT NULL AND receipt_id IS NOT NULL)),
 FOREIGN KEY(prep_key,receipt_id) REFERENCES cp_receipt(prep_key,receipt_id)
) STRICT;
CREATE VIEW pd_source AS SELECT r.*,g.sequence,g.origin,g.prep_key,g.receipt_id,g.control_epoch,g.effective_version,
 e.device_id,p.origin_authority,p.origin_database,p.run_id,p.generation
 FROM ep_request r JOIN pd_registration g USING(prepare_id) JOIN ce_exit e USING(exit_id) LEFT JOIN cp_request p USING(prep_key);
CREATE TABLE pd_cut(
 cut_id TEXT PRIMARY KEY NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('control','cancel','run','close')),
 control_id TEXT UNIQUE REFERENCES cu_cut(operation_id),cancel_id TEXT UNIQUE REFERENCES cc_cut(cut_id),
 run_id TEXT UNIQUE REFERENCES ce_fence(fence_id),close_id TEXT UNIQUE REFERENCES go_close(close_id),
 prepare_head TEXT NOT NULL CHECK(length(prepare_head)=20 AND prepare_head NOT GLOB '*[^0-9]*'),
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 selector_digest TEXT NOT NULL,selector_body BLOB NOT NULL CHECK(length(selector_body)>0),
 CHECK((kind='control' AND control_id IS NOT NULL AND cancel_id IS NULL AND run_id IS NULL AND close_id IS NULL)
 OR(kind='cancel' AND control_id IS NULL AND cancel_id IS NOT NULL AND run_id IS NULL AND close_id IS NULL)
 OR(kind='run' AND control_id IS NULL AND cancel_id IS NULL AND run_id IS NOT NULL AND close_id IS NULL)
 OR(kind='close' AND control_id IS NULL AND cancel_id IS NULL AND run_id IS NULL AND close_id IS NOT NULL)),
 FOREIGN KEY(cut_id) REFERENCES pd_cut_commit(cut_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE pd_member(
 cut_id TEXT NOT NULL REFERENCES pd_cut(cut_id),prepare_id TEXT NOT NULL REFERENCES ep_request(prepare_id),
 exit_id TEXT NOT NULL,authorization_id TEXT NOT NULL,authorization_digest TEXT NOT NULL,
 PRIMARY KEY(cut_id,prepare_id),
 FOREIGN KEY(prepare_id) REFERENCES ep_revocation(prepare_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE pd_cut_commit(
 cut_id TEXT PRIMARY KEY NOT NULL REFERENCES pd_cut(cut_id),committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE VIEW pd_expected AS
 SELECT d.cut_id,s.prepare_id,s.exit_id,s.authorization_id,s.authorization_digest FROM pd_cut d JOIN cu_cut c ON c.operation_id=d.control_id
 JOIN pd_source s ON s.device_id=c.device_id AND s.sequence<=d.prepare_head
 UNION ALL
 SELECT d.cut_id,s.prepare_id,s.exit_id,s.authorization_id,s.authorization_digest FROM pd_cut d JOIN cc_cut c ON c.cut_id=d.cancel_id
 JOIN cv_cancel v USING(cancellation_id) JOIN pd_source s ON s.command_id=v.command_id AND s.sequence<=d.prepare_head AND (c.stage='all' OR s.kind='ordinary')
 UNION ALL
 SELECT d.cut_id,s.prepare_id,s.exit_id,s.authorization_id,s.authorization_digest FROM pd_cut d JOIN ce_selector c ON c.fence_id=d.run_id
 JOIN pd_source s ON (s.origin_authority,s.origin_database,s.run_id)=(c.origin_authority,c.origin_database,c.run_id)
 AND s.origin='automation' AND s.generation<=c.generation AND s.sequence<=d.prepare_head
 UNION ALL
 SELECT d.cut_id,s.prepare_id,s.exit_id,s.authorization_id,s.authorization_digest FROM pd_cut d JOIN go_close c ON c.close_id=d.close_id
 JOIN pd_source s ON s.exit_id=c.exit_id AND s.sequence<=d.prepare_head;
CREATE TRIGGER pd_register_guard BEFORE INSERT ON pd_registration BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM ep_request)>(SELECT max_metadata_prepares FROM ep_limit WHERE singleton=1)
 THEN RAISE(ABORT,'prepare_total_metadata_capacity') END;
 SELECT CASE WHEN NEW.sequence!=(SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),(CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
 FROM(SELECT coalesce(max(sequence),'00000000000000000000') v FROM pd_registration)) THEN RAISE(ABORT,'prepare_registry_sequence') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ce_command c USING(command_id) JOIN ce_exit e ON e.exit_id=r.exit_id JOIN ct_current_state s ON s.device_id=e.device_id
 WHERE r.prepare_id=NEW.prepare_id AND NOT EXISTS(SELECT 1 FROM ep_request_commit k WHERE k.prepare_id=r.prepare_id)
 AND NEW.control_epoch=s.control_epoch AND NEW.effective_version=s.effective_version AND s.pending_operation_id IS NULL
 AND (r.kind='cancel' OR (NEW.origin=c.origin AND NEW.prep_key IS c.prep_key AND NEW.receipt_id IS c.receipt_id))
 AND NOT EXISTS(SELECT 1 FROM ep_request prior JOIN pd_registration p USING(prepare_id) WHERE r.kind='cancel' AND prior.cancellation_id=r.cancellation_id
 AND NOT(p.origin=NEW.origin AND p.prep_key IS NEW.prep_key AND p.receipt_id IS NEW.receipt_id))
 AND (NEW.origin='manual' OR EXISTS(SELECT 1 FROM cp_request_device p WHERE p.prep_key=NEW.prep_key AND p.device_id=e.device_id)))
 THEN RAISE(ABORT,'prepare_registry_source') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ep_request r JOIN ce_exit e USING(exit_id) JOIN cu_cut c USING(device_id)
 JOIN ct_operation o USING(operation_id) JOIN ct_state old ON old.change_id=o.expected_state_id
 WHERE r.prepare_id=NEW.prepare_id AND NEW.control_epoch=old.control_epoch AND NEW.effective_version<o.target_version)
 THEN RAISE(ABORT,'prepare_control_denied') END;
 SELECT CASE WHEN NEW.origin='automation' AND EXISTS(SELECT 1 FROM cp_request p JOIN run_deny_event d
 ON (d.origin_authority,d.origin_database,d.run_id)=(p.origin_authority,p.origin_database,p.run_id)
 WHERE p.prep_key=NEW.prep_key AND d.generation>=p.generation) THEN RAISE(ABORT,'prepare_run_denied') END;
END;
CREATE TRIGGER pd_cut_guard BEFORE INSERT ON pd_cut BEGIN
 SELECT CASE WHEN NEW.prepare_head!=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration)
 OR EXISTS(SELECT 1 FROM ep_request r WHERE NOT EXISTS(SELECT 1 FROM pd_registration p WHERE p.prepare_id=r.prepare_id))
 OR NOT((NEW.kind='control' AND EXISTS(SELECT 1 FROM cu_cut c JOIN ct_change h USING(change_id) WHERE c.operation_id=NEW.control_id AND c.prepare_cut_id=NEW.cut_id AND h.now_tick=NEW.selected_tick AND NOT EXISTS(SELECT 1 FROM ct_commit k WHERE k.change_id=c.change_id)))
 OR(NEW.kind='cancel' AND EXISTS(SELECT 1 FROM cc_cut c WHERE c.cut_id=NEW.cancel_id AND c.prepare_cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM cc_cut_commit k WHERE k.cut_id=c.cut_id)))
 OR(NEW.kind='run' AND EXISTS(SELECT 1 FROM ce_fence c WHERE c.fence_id=NEW.run_id AND c.prepare_cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM ce_cut_commit k WHERE k.fence_id=c.fence_id)))
 OR(NEW.kind='close' AND EXISTS(SELECT 1 FROM go_close c JOIN ct_change h ON h.change_id=c.protection_change_id WHERE c.close_id=NEW.close_id AND c.prepare_cut_id=NEW.cut_id AND h.now_tick=NEW.selected_tick AND NOT EXISTS(SELECT 1 FROM ct_commit k WHERE k.change_id=h.change_id))))
 THEN RAISE(ABORT,'prepare_cut_source') END;
END;
CREATE TRIGGER pd_member_guard BEFORE INSERT ON pd_member BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pd_cut_commit WHERE cut_id=NEW.cut_id)
 OR NOT EXISTS(SELECT 1 FROM pd_expected p WHERE p.cut_id=NEW.cut_id AND p.prepare_id=NEW.prepare_id AND p.exit_id=NEW.exit_id
 AND p.authorization_id=NEW.authorization_id AND p.authorization_digest=NEW.authorization_digest) THEN RAISE(ABORT,'prepare_member_binding') END;
END;
CREATE TRIGGER pd_cut_seal BEFORE INSERT ON pd_cut_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pd_cut d WHERE d.cut_id=NEW.cut_id AND d.selected_tick<=NEW.committed_tick
 AND d.prepare_head=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration))
 OR EXISTS(SELECT cut_id,prepare_id,exit_id,authorization_id,authorization_digest FROM pd_expected WHERE cut_id=NEW.cut_id
 EXCEPT SELECT cut_id,prepare_id,exit_id,authorization_id,authorization_digest FROM pd_member WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT 1 FROM pd_member m JOIN ep_revocation r USING(prepare_id) JOIN ep_request_commit k USING(prepare_id)
 WHERE m.cut_id=NEW.cut_id AND (r.revoked_tick>NEW.committed_tick OR k.committed_tick>NEW.committed_tick))
 OR EXISTS(SELECT 1 FROM pd_member m WHERE m.cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM ep_revocation v WHERE v.prepare_id=m.prepare_id))
 THEN RAISE(ABORT,'prepare_cut_incomplete') END;
END;
CREATE TABLE pd_deny_request(
 deny_id TEXT PRIMARY KEY NOT NULL,prepare_id TEXT NOT NULL UNIQUE REFERENCES ep_revocation(prepare_id),
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),revision TEXT NOT NULL CHECK(revision='00000000000000000001'),request_digest TEXT NOT NULL,
 exit_id TEXT NOT NULL,authorization_id TEXT NOT NULL,authorization_digest TEXT NOT NULL,
 encode_message_id TEXT NOT NULL,encode_frame_digest TEXT NOT NULL,
 revocation_id TEXT NOT NULL,revocation_revision TEXT NOT NULL,revocation_digest TEXT NOT NULL,
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),frame_body BLOB NOT NULL CHECK(length(frame_body)>0),body BLOB NOT NULL CHECK(length(body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER pd_request_guard BEFORE INSERT ON pd_deny_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ij_encoding_frame j USING(prepare_id) JOIN ep_revocation v USING(prepare_id)
 JOIN ij_frame f ON f.frame_id=NEW.journal_frame_id
 WHERE r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id AND r.authorization_id=NEW.authorization_id AND r.authorization_digest=NEW.authorization_digest
 AND r.request_message_id=NEW.encode_message_id AND j.request_frame_digest=NEW.encode_frame_digest
 AND v.revocation_id=NEW.revocation_id AND v.revocation_revision=NEW.revocation_revision AND v.revocation_digest=NEW.revocation_digest AND v.revoked_tick<=NEW.selected_tick
 AND f.domain_kind='prepare_deny_request' AND f.domain_id=NEW.deny_id AND f.message_type='DENY_ENCODING' AND f.direction='c2w' AND f.exit_id=NEW.exit_id
 AND f.frame_body=NEW.frame_body AND f.body_body=NEW.body AND f.observed_tick=NEW.selected_tick
 AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'prepare_deny_source') END;
END;
CREATE TABLE pd_deny_ack(
 ack_id TEXT PRIMARY KEY NOT NULL,deny_id TEXT NOT NULL UNIQUE REFERENCES pd_deny_request(deny_id),prepare_id TEXT NOT NULL,
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),exit_id TEXT NOT NULL,
 deny_revision TEXT NOT NULL,deny_digest TEXT NOT NULL,deny_message_id TEXT NOT NULL,deny_frame_digest TEXT NOT NULL,
 effective_tick TEXT NOT NULL CHECK(length(effective_tick)=20 AND effective_tick NOT GLOB '*[^0-9]*'),received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),future_use_denied INTEGER NOT NULL CHECK(future_use_denied=1),
 frame_body BLOB NOT NULL CHECK(length(frame_body)>0),validation_body BLOB NOT NULL CHECK(length(validation_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER pd_ack_guard BEFORE INSERT ON pd_deny_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pd_deny_request r JOIN ij_frame original ON original.frame_id=r.journal_frame_id
 JOIN ij_commit c ON c.frame_id=original.frame_id JOIN ij_write_attempt a ON a.frame_id=original.frame_id JOIN ij_frame f ON f.frame_id=NEW.journal_frame_id
 WHERE r.deny_id=NEW.deny_id AND r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id AND r.revision=NEW.deny_revision AND r.request_digest=NEW.deny_digest
 AND original.message_id=NEW.deny_message_id AND original.frame_digest=NEW.deny_frame_digest AND r.selected_tick<=NEW.effective_tick AND a.attempted_tick<=NEW.effective_tick
 AND NEW.effective_tick<=NEW.received_tick AND f.observed_tick=NEW.received_tick AND f.reply_frame_id=original.frame_id AND f.exit_id=NEW.exit_id
 AND f.message_type='DENY_ENCODING_ACK' AND f.domain_kind='prepare_deny_ack' AND f.domain_id=NEW.ack_id AND f.frame_body=NEW.frame_body
 AND NOT EXISTS(SELECT 1 FROM ij_commit k WHERE k.frame_id=f.frame_id)) THEN RAISE(ABORT,'prepare_deny_ack_source') END;
END;
CREATE TABLE pd_ack_revocation(
 ack_id TEXT PRIMARY KEY NOT NULL REFERENCES pd_deny_ack(ack_id),reason_body BLOB NOT NULL CHECK(length(reason_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE pd_closure(
 closure_id TEXT PRIMARY KEY NOT NULL,cut_id TEXT NOT NULL REFERENCES pd_cut_commit(cut_id),revision TEXT NOT NULL CHECK(revision='00000000000000000001'),
 closure_digest TEXT NOT NULL,committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),body BLOB NOT NULL CHECK(length(body)>0),
 UNIQUE(closure_id,cut_id),FOREIGN KEY(closure_id) REFERENCES pd_closure_commit(closure_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE pd_coverage(
 closure_id TEXT NOT NULL,cut_id TEXT NOT NULL,prepare_id TEXT NOT NULL,
 basis TEXT NOT NULL CHECK(basis IN ('never_attempted','released','retired','deny_ack')),
 ack_id TEXT REFERENCES pd_deny_ack(ack_id),retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 proof_body BLOB NOT NULL CHECK(length(proof_body)>0),PRIMARY KEY(closure_id,prepare_id),
 CHECK((basis='deny_ack' AND ack_id IS NOT NULL AND retirement_exit_id IS NULL)
 OR(basis='retired' AND ack_id IS NULL AND retirement_exit_id IS NOT NULL)
 OR(basis IN ('never_attempted','released') AND ack_id IS NULL AND retirement_exit_id IS NULL)),
 FOREIGN KEY(cut_id,prepare_id) REFERENCES pd_member(cut_id,prepare_id),
 FOREIGN KEY(closure_id,cut_id) REFERENCES pd_closure(closure_id,cut_id)
) STRICT;
CREATE TABLE pd_closure_commit(
 closure_id TEXT PRIMARY KEY NOT NULL REFERENCES pd_closure(closure_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE pd_close_completion(
 close_id TEXT PRIMARY KEY NOT NULL REFERENCES go_close(close_id),ack_id TEXT NOT NULL UNIQUE REFERENCES go_close_ack(ack_id),
 closure_id TEXT NOT NULL REFERENCES pd_closure_commit(closure_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW pd_valid_proof AS SELECT p.* FROM pd_coverage p JOIN pd_member m ON (m.cut_id,m.prepare_id)=(p.cut_id,p.prepare_id)
 JOIN pd_closure d USING(closure_id) JOIN ep_revocation v ON v.prepare_id=p.prepare_id
 WHERE v.revoked_tick<=d.committed_tick AND
 ((p.basis='never_attempted' AND NOT EXISTS(SELECT 1 FROM ep_send_attempt a WHERE a.prepare_id=p.prepare_id))
 OR(p.basis='released' AND EXISTS(SELECT 1 FROM ep_release r JOIN er_adoption a ON a.adoption_id=r.worker_adoption_id JOIN er_ack_commit k ON k.adoption_id=a.adoption_id
 WHERE r.prepare_id=p.prepare_id AND r.basis='worker_released' AND a.committed_tick<=d.committed_tick))
 OR(p.basis='retired' AND p.retirement_exit_id=m.exit_id AND NOT EXISTS(SELECT 1 FROM cu_revocation r WHERE r.kind='retirement' AND r.object_id=p.retirement_exit_id))
 OR(p.basis='deny_ack' AND EXISTS(SELECT 1 FROM pd_deny_ack a JOIN ij_commit k ON k.frame_id=a.journal_frame_id
 WHERE a.ack_id=p.ack_id AND a.prepare_id=p.prepare_id AND a.exit_id=m.exit_id AND k.disposition='applied' AND k.committed_tick<=d.committed_tick
 AND NOT EXISTS(SELECT 1 FROM pd_ack_revocation r WHERE r.ack_id=a.ack_id))));
CREATE VIEW pd_valid_closure AS SELECT c.* FROM pd_closure c JOIN pd_closure_commit k USING(closure_id)
 WHERE NOT EXISTS(SELECT 1 FROM pd_member m WHERE m.cut_id=c.cut_id AND NOT EXISTS(SELECT 1 FROM pd_valid_proof p WHERE p.closure_id=c.closure_id AND p.prepare_id=m.prepare_id));
CREATE TRIGGER pd_coverage_guard BEFORE INSERT ON pd_coverage BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pd_closure_commit WHERE closure_id=NEW.closure_id) THEN RAISE(ABORT,'prepare_closure_frozen') END;
END;
CREATE TRIGGER pd_closure_seal BEFORE INSERT ON pd_closure_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pd_closure c JOIN pd_cut_commit k USING(cut_id) WHERE c.closure_id=NEW.closure_id AND k.committed_tick<=c.committed_tick)
 OR EXISTS(SELECT m.prepare_id FROM pd_member m JOIN pd_closure c USING(cut_id) WHERE c.closure_id=NEW.closure_id
 EXCEPT SELECT prepare_id FROM pd_valid_proof WHERE closure_id=NEW.closure_id) THEN RAISE(ABORT,'prepare_closure_incomplete') END;
END;
CREATE TRIGGER pd_close_complete_guard BEFORE INSERT ON pd_close_completion BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_close c JOIN go_close_ack a USING(close_id) JOIN pd_valid_closure p ON p.cut_id=c.prepare_cut_id
 WHERE c.close_id=NEW.close_id AND a.ack_id=NEW.ack_id AND p.closure_id=NEW.closure_id) THEN RAISE(ABORT,'prepare_close_completion') END;
END;

CREATE TRIGGER pd_seal_cu_cut BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_cut o WHERE o.change_id=NEW.change_id AND NOT EXISTS(SELECT 1 FROM pd_cut c JOIN pd_cut_commit k USING(cut_id) WHERE c.cut_id=o.prepare_cut_id AND c.control_id=o.operation_id AND c.kind='control' AND c.prepare_head=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration))) THEN RAISE(ABORT,'prepare_cut_required') END;
END;

CREATE TRIGGER pd_seal_cc_cut BEFORE INSERT ON cc_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cc_cut o WHERE o.cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM pd_cut c JOIN pd_cut_commit k USING(cut_id) WHERE c.cut_id=o.prepare_cut_id AND c.cancel_id=o.cut_id AND c.kind='cancel' AND c.prepare_head=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration))) THEN RAISE(ABORT,'prepare_cut_required') END;
END;

CREATE TRIGGER pd_seal_ce_fence BEFORE INSERT ON ce_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_fence o WHERE o.fence_id=NEW.fence_id AND NOT EXISTS(SELECT 1 FROM pd_cut c JOIN pd_cut_commit k USING(cut_id) WHERE c.cut_id=o.prepare_cut_id AND c.run_id=o.fence_id AND c.kind='run' AND c.prepare_head=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration))) THEN RAISE(ABORT,'prepare_cut_required') END;
END;

CREATE TRIGGER pd_seal_go_close BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_close o WHERE o.protection_change_id=NEW.change_id AND NOT EXISTS(SELECT 1 FROM pd_cut c JOIN pd_cut_commit k USING(cut_id) WHERE c.cut_id=o.prepare_cut_id AND c.close_id=o.close_id AND c.kind='close' AND c.prepare_head=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration))) THEN RAISE(ABORT,'prepare_cut_required') END;
END;

CREATE TRIGGER pd_apply_cu_effective BEFORE INSERT ON cu_effective BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cu_cut c JOIN pd_valid_closure p ON p.cut_id=c.prepare_cut_id WHERE c.operation_id=NEW.operation_id AND p.closure_id=NEW.prepare_closure_id) THEN RAISE(ABORT,'prepare_closure_required') END;
END;

CREATE TRIGGER pd_apply_cc_closure BEFORE INSERT ON cc_closure BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cc_cut c JOIN pd_valid_closure p ON p.cut_id=c.prepare_cut_id WHERE c.cut_id=NEW.cut_id AND p.closure_id=NEW.prepare_closure_id) THEN RAISE(ABORT,'prepare_closure_required') END;
END;

CREATE TRIGGER pd_apply_ce_application BEFORE INSERT ON ce_application BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_fence c JOIN pd_valid_closure p ON p.cut_id=c.prepare_cut_id WHERE c.fence_id=NEW.fence_id AND p.closure_id=NEW.prepare_closure_id) THEN RAISE(ABORT,'prepare_closure_required') END;
END;

CREATE VIEW cu_valid_effective AS SELECT b.* FROM pd_base_cu_valid_effective b JOIN pd_valid_closure p ON p.closure_id=b.prepare_closure_id;

CREATE VIEW cc_valid_closure AS SELECT b.* FROM pd_base_cc_valid_closure b JOIN pd_valid_closure p ON p.closure_id=b.prepare_closure_id;

CREATE VIEW go_valid_recovery AS SELECT r.* FROM pd_base_go_valid_recovery r
 WHERE NOT EXISTS(SELECT 1 FROM go_recovery_target t WHERE t.recovery_id=r.recovery_id
 AND NOT EXISTS(SELECT 1 FROM pd_close_completion c JOIN pd_valid_closure p USING(closure_id) WHERE c.close_id=t.close_id AND c.ack_id=t.ack_id));
CREATE VIEW pd_valid_application AS SELECT a.* FROM ce_application a JOIN pd_valid_closure p ON p.closure_id=a.prepare_closure_id;

CREATE VIEW go_ready_candidate AS SELECT c.* FROM pd_base_go_ready_candidate c JOIN go_plan p USING(plan_id)
 WHERE p.gate_recovery_id IS NULL OR EXISTS(SELECT 1 FROM go_valid_recovery r WHERE r.recovery_id=p.gate_recovery_id);

CREATE TRIGGER pd_final_control BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cu_effective e JOIN ct_change h USING(change_id) WHERE e.change_id=NEW.change_id
 AND NOT EXISTS(SELECT 1 FROM pd_valid_closure p WHERE p.closure_id=e.prepare_closure_id AND p.committed_tick<=h.now_tick))
 THEN RAISE(ABORT,'prepare_control_final_seal') END;
END;
CREATE TRIGGER pd_recovery_guard BEFORE INSERT ON go_recovery_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_recovery_target t WHERE t.recovery_id=NEW.recovery_id
 AND NOT EXISTS(SELECT 1 FROM pd_close_completion c JOIN pd_valid_closure p USING(closure_id)
 WHERE c.close_id=t.close_id AND c.ack_id=t.ack_id)) THEN RAISE(ABORT,'prepare_close_not_complete') END;
END;
CREATE TRIGGER pd_send_guard BEFORE INSERT ON ij_write_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pd_deny_request r JOIN ce_retirement e USING(exit_id) WHERE r.journal_frame_id=NEW.frame_id)
 THEN RAISE(ABORT,'prepare_deny_retired') END;
END;
CREATE TRIGGER pd_registration_u BEFORE UPDATE ON pd_registration BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_registration_d BEFORE DELETE ON pd_registration BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_cut_u BEFORE UPDATE ON pd_cut BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_cut_d BEFORE DELETE ON pd_cut BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_member_u BEFORE UPDATE ON pd_member BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_member_d BEFORE DELETE ON pd_member BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_cut_commit_u BEFORE UPDATE ON pd_cut_commit BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_cut_commit_d BEFORE DELETE ON pd_cut_commit BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_deny_request_u BEFORE UPDATE ON pd_deny_request BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_deny_request_d BEFORE DELETE ON pd_deny_request BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_deny_ack_u BEFORE UPDATE ON pd_deny_ack BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_deny_ack_d BEFORE DELETE ON pd_deny_ack BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_ack_revocation_u BEFORE UPDATE ON pd_ack_revocation BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_ack_revocation_d BEFORE DELETE ON pd_ack_revocation BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_closure_u BEFORE UPDATE ON pd_closure BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_closure_d BEFORE DELETE ON pd_closure BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_coverage_u BEFORE UPDATE ON pd_coverage BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_coverage_d BEFORE DELETE ON pd_coverage BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_closure_commit_u BEFORE UPDATE ON pd_closure_commit BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_closure_commit_d BEFORE DELETE ON pd_closure_commit BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_close_completion_u BEFORE UPDATE ON pd_close_completion BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;
CREATE TRIGGER pd_close_completion_d BEFORE DELETE ON pd_close_completion BEGIN SELECT RAISE(ABORT,'immutable_prepare_deny'); END;

-- 追加于完整Controller准备关闭布局；不会放开命令或最终发送出口。
CREATE TABLE cr_limit(singleton INTEGER PRIMARY KEY CHECK(singleton=1),max_issues INTEGER NOT NULL CHECK(max_issues BETWEEN 1 AND 65536)) STRICT;
CREATE TABLE cr_issue(
 transfer_id TEXT PRIMARY KEY NOT NULL,prep_key TEXT NOT NULL UNIQUE REFERENCES cp_request(prep_key),
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL CHECK(length(request_body) BETWEEN 1 AND 262144 AND json_valid(request_body)),
 target_body BLOB NOT NULL CHECK(length(target_body) BETWEEN 1 AND 262144 AND json_valid(target_body)),
 receipt_id TEXT NOT NULL UNIQUE,receipt_digest TEXT NOT NULL,
 receipt_body BLOB NOT NULL CHECK(length(receipt_body) BETWEEN 1 AND 16384 AND json_valid(receipt_body)),
 grant_id TEXT NOT NULL UNIQUE,grant_body BLOB NOT NULL CHECK(length(grant_body) BETWEEN 1 AND 16384 AND json_valid(grant_body)),
 FOREIGN KEY(transfer_id) REFERENCES cr_commit(transfer_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(transfer_id=json_extract(request_body,'$.transfer_id') AND transfer_id=json_extract(receipt_body,'$.transfer_id')),
 CHECK(request_digest=json_extract(request_body,'$.request_digest') AND request_digest=json_extract(receipt_body,'$.request_digest')),
 CHECK(receipt_id=json_extract(receipt_body,'$.receipt_id') AND receipt_digest=json_extract(receipt_body,'$.receipt_digest')),
 CHECK(grant_id=json_extract(receipt_body,'$.continuation_grant_ref.id') AND grant_id=json_extract(grant_body,'$.ref.id'))
) STRICT;
CREATE TABLE cr_device(
 transfer_id TEXT NOT NULL REFERENCES cr_issue(transfer_id),device_id TEXT NOT NULL,
 control_state_id TEXT NOT NULL REFERENCES ct_state(change_id),device_body BLOB NOT NULL CHECK(json_valid(device_body)),
 PRIMARY KEY(transfer_id,device_id),CHECK(device_id=json_extract(device_body,'$.device_id'))
) STRICT;
CREATE TABLE cr_commit(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_issue(transfer_id),request_digest TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),outbox_body BLOB NOT NULL CHECK(length(outbox_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE TABLE cr_revocation(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_commit(transfer_id),proof_body BLOB NOT NULL CHECK(length(proof_body) BETWEEN 1 AND 16384),
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),outbox_body BLOB NOT NULL CHECK(length(outbox_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE VIEW cr_eligible AS SELECT i.* FROM cr_issue i JOIN cp_request p USING(prep_key) JOIN cp_current c USING(prep_key)
 WHERE c.state='applied' AND NOT EXISTS(SELECT 1 FROM cp_close x WHERE x.prep_key=p.prep_key)
 AND NOT EXISTS(SELECT 1 FROM run_deny_current d WHERE d.origin_authority=p.origin_authority AND d.origin_database=p.origin_database AND d.run_id=p.run_id AND d.generation>=p.generation)
 AND NOT EXISTS(SELECT 1 FROM cr_revocation v WHERE v.transfer_id=i.transfer_id)
 AND NOT EXISTS(SELECT 1 FROM cr_device d WHERE d.transfer_id=i.transfer_id AND NOT EXISTS(
 SELECT 1 FROM ct_current_state s WHERE s.device_id=d.device_id AND s.change_id=d.control_state_id AND s.mode='automatic' AND s.pending_operation_id IS NULL));
CREATE VIEW cr_current AS SELECT i.* FROM cr_eligible i JOIN cr_commit k USING(transfer_id);
CREATE TRIGGER cr_issue_guard BEFORE INSERT ON cr_issue BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_limit WHERE (SELECT count(*) FROM cr_issue)<max_issues) THEN RAISE(ABORT,'continuation_capacity') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cp_request p JOIN cp_grant g USING(prep_key) JOIN controller_scope s ON s.singleton=1
 WHERE p.prep_key=NEW.prep_key AND p.mode='recovery'
 AND p.origin_authority=json_extract(NEW.request_body,'$.origin_scope.authority_service_id') AND p.origin_database=json_extract(NEW.request_body,'$.origin_scope.database_instance_id')
 AND p.run_id=json_extract(NEW.request_body,'$.run_id') AND p.generation=substr('00000000000000000000'||json_extract(NEW.request_body,'$.generation'),-20)
 AND p.execution_id=json_extract(NEW.request_body,'$.recovery_execution_id') AND p.preparation_id=json_extract(NEW.target_body,'$.preparation_ref.id')
 AND p.request_digest=json_extract(NEW.target_body,'$.preparation_ref.digest') AND json_extract(NEW.target_body,'$.preparation_ref.revision')='1'
 AND g.grant_id=json_extract(NEW.target_body,'$.recovery_grant_ref.id') AND g.grant_digest=json_extract(NEW.target_body,'$.recovery_grant_ref.digest')
 AND g.grant_revision=substr('00000000000000000000'||json_extract(NEW.target_body,'$.recovery_grant_ref.revision'),-20) AND NEW.grant_id!=g.grant_id
 AND s.authority_service_id=json_extract(NEW.target_body,'$.controller_scope.authority_service_id') AND s.database_instance_id=json_extract(NEW.target_body,'$.controller_scope.database_instance_id')
 AND p.device_count=json_array_length(NEW.target_body,'$.devices')) THEN RAISE(ABORT,'continuation_parent') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM json_each(NEW.request_body,'$.targets') t WHERE json(t.value)=json(NEW.target_body)) THEN RAISE(ABORT,'continuation_target') END;
END;
CREATE TRIGGER cr_device_guard BEFORE INSERT ON cr_device BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_commit WHERE transfer_id=NEW.transfer_id) THEN RAISE(ABORT,'continuation_sealed') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_issue i JOIN cp_request_device p USING(prep_key) JOIN ct_current_state s ON s.device_id=p.device_id
 JOIN json_each(i.target_body,'$.devices') d WHERE i.transfer_id=NEW.transfer_id AND p.device_id=NEW.device_id
 AND s.change_id=NEW.control_state_id AND s.mode='automatic' AND s.pending_operation_id IS NULL
 AND json(d.value)=json(NEW.device_body) AND s.change_id=json_extract(d.value,'$.control_ref.id')
 AND s.record_revision=substr('00000000000000000000'||json_extract(d.value,'$.control_ref.revision'),-20)
 AND s.record_digest=json_extract(d.value,'$.control_ref.digest')) THEN RAISE(ABORT,'continuation_control') END;
END;
CREATE TRIGGER cr_seal BEFORE INSERT ON cr_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_eligible i WHERE i.transfer_id=NEW.transfer_id AND i.request_digest=NEW.request_digest
 AND (SELECT count(*) FROM cr_device d WHERE d.transfer_id=i.transfer_id)=json_array_length(i.target_body,'$.devices')
 AND NOT EXISTS(SELECT 1 FROM json_each(i.target_body,'$.devices') j WHERE NOT EXISTS(SELECT 1 FROM cr_device d WHERE d.transfer_id=i.transfer_id AND d.device_id=json_extract(j.value,'$.device_id'))))
 THEN RAISE(ABORT,'continuation_issue_seal') END;
END;

CREATE TRIGGER cr_limit_update BEFORE UPDATE ON cr_limit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_limit_delete BEFORE DELETE ON cr_limit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_issue_update BEFORE UPDATE ON cr_issue BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_issue_delete BEFORE DELETE ON cr_issue BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_device_update BEFORE UPDATE ON cr_device BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_device_delete BEFORE DELETE ON cr_device BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_commit_update BEFORE UPDATE ON cr_commit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_commit_delete BEFORE DELETE ON cr_commit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_revocation_update BEFORE UPDATE ON cr_revocation BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_revocation_delete BEFORE DELETE ON cr_revocation BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER cr_issue_request_body_shape BEFORE INSERT ON cr_issue WHEN json_type(NEW.request_body,'$.contract_version') IS NOT 'text' OR json_type(NEW.request_body,'$.origin_scope') IS NOT 'object' OR json_type(NEW.request_body,'$.run_id') IS NOT 'text' OR json_type(NEW.request_body,'$.generation') IS NOT 'text' OR json_type(NEW.request_body,'$.transfer_id') IS NOT 'text' OR json_type(NEW.request_body,'$.recovery_operation_id') IS NOT 'text' OR json_type(NEW.request_body,'$.recovery_execution_id') IS NOT 'text' OR json_type(NEW.request_body,'$.continuation_plan_ref') IS NOT 'object' OR json_type(NEW.request_body,'$.request_epoch') IS NOT 'text' OR json_type(NEW.request_body,'$.actor') IS NOT 'object' OR json_type(NEW.request_body,'$.idempotency_key') IS NOT 'text' OR json_type(NEW.request_body,'$.approval_ref') IS NOT 'object' OR json_type(NEW.request_body,'$.targets') IS NOT 'array' OR json_type(NEW.request_body,'$.request_digest') IS NOT 'text' BEGIN SELECT RAISE(ABORT,'continuation_body_shape'); END;

CREATE TRIGGER cr_issue_receipt_body_shape BEFORE INSERT ON cr_issue WHEN json_type(NEW.receipt_body,'$.contract_version') IS NOT 'text' OR json_type(NEW.receipt_body,'$.origin_scope') IS NOT 'object' OR json_type(NEW.receipt_body,'$.run_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.generation') IS NOT 'text' OR json_type(NEW.receipt_body,'$.transfer_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.recovery_operation_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.recovery_execution_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.continuation_plan_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.request_digest') IS NOT 'text' OR json_type(NEW.receipt_body,'$.controller_scope') IS NOT 'object' OR json_type(NEW.receipt_body,'$.receipt_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.revision') IS NOT 'text' OR json_type(NEW.receipt_body,'$.target_digest') IS NOT 'text' OR json_type(NEW.receipt_body,'$.preparation_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.recovery_grant_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.continuation_grant_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.qualification_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.receipt_digest') IS NOT 'text' BEGIN SELECT RAISE(ABORT,'continuation_body_shape'); END;

CREATE TRIGGER cr_issue_bodies BEFORE INSERT ON cr_issue WHEN json_extract(NEW.receipt_body,'$.contract_version') IS NOT json_extract(NEW.request_body,'$.contract_version') OR json_extract(NEW.receipt_body,'$.origin_scope') IS NOT json_extract(NEW.request_body,'$.origin_scope') OR json_extract(NEW.receipt_body,'$.run_id') IS NOT json_extract(NEW.request_body,'$.run_id') OR json_extract(NEW.receipt_body,'$.generation') IS NOT json_extract(NEW.request_body,'$.generation') OR json_extract(NEW.receipt_body,'$.transfer_id') IS NOT json_extract(NEW.request_body,'$.transfer_id') OR json_extract(NEW.receipt_body,'$.recovery_operation_id') IS NOT json_extract(NEW.request_body,'$.recovery_operation_id') OR json_extract(NEW.receipt_body,'$.recovery_execution_id') IS NOT json_extract(NEW.request_body,'$.recovery_execution_id') OR json_extract(NEW.receipt_body,'$.continuation_plan_ref') IS NOT json_extract(NEW.request_body,'$.continuation_plan_ref') OR json_extract(NEW.receipt_body,'$.controller_scope') IS NOT json_extract(NEW.target_body,'$.controller_scope') OR json_extract(NEW.receipt_body,'$.preparation_ref') IS NOT json_extract(NEW.target_body,'$.preparation_ref') OR json_extract(NEW.receipt_body,'$.recovery_grant_ref') IS NOT json_extract(NEW.target_body,'$.recovery_grant_ref') OR json_extract(NEW.receipt_body,'$.continuation_grant_ref') IS NOT json_extract(NEW.grant_body,'$.ref') OR json_extract(NEW.grant_body,'$.request_digest') IS NOT NEW.request_digest OR json_extract(NEW.grant_body,'$.target_digest') IS NOT json_extract(NEW.receipt_body,'$.target_digest') OR json_extract(NEW.grant_body,'$.parent_preparation_ref') IS NOT json_extract(NEW.target_body,'$.preparation_ref') OR json_extract(NEW.grant_body,'$.plan_ref') IS NOT json_extract(NEW.request_body,'$.continuation_plan_ref') OR json_extract(NEW.grant_body,'$.scope') IS NOT 'run_generation' OR json_extract(NEW.grant_body,'$.activation') IS NOT 'adoption_and_r5' BEGIN SELECT RAISE(ABORT,'continuation_bodies'); END;

-- Controller：新普通命令沿原准备归属，同时明确引用新grant和Seamer采用。
CREATE TABLE cn_command(
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_command(command_id),transfer_id TEXT NOT NULL REFERENCES cr_commit(transfer_id),
 execution_id TEXT NOT NULL,step_id TEXT NOT NULL,request_digest TEXT NOT NULL,
 adoption_digest TEXT NOT NULL,grant_ref_body BLOB NOT NULL CHECK(length(grant_ref_body) BETWEEN 1 AND 16384 AND json_valid(grant_ref_body)),
 binding_body BLOB NOT NULL CHECK(length(binding_body) BETWEEN 1 AND 16384 AND json_valid(binding_body)),
 UNIQUE(transfer_id,execution_id,step_id)
) STRICT;
CREATE VIEW cn_live_command AS SELECT n.* FROM cn_command n JOIN cr_current c USING(transfer_id) JOIN ce_command e USING(command_id)
 WHERE e.prep_key=c.prep_key AND json(n.grant_ref_body)=json(json_extract(c.receipt_body,'$.continuation_grant_ref'));
CREATE TRIGGER cn_command_guard BEFORE INSERT ON cn_command BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_current c JOIN cp_request p USING(prep_key) JOIN ce_command e ON e.prep_key=c.prep_key
 JOIN ca_command_initial i ON i.command_id=e.command_id JOIN ca_request_key k ON k.key_id=i.key_id
 WHERE e.command_id=NEW.command_id AND c.transfer_id=NEW.transfer_id AND e.origin='automation'
 AND e.device_id=k.device_id AND k.device_id=json_extract(k.content_body,'$.device_id')
 AND NEW.execution_id!=p.execution_id AND NEW.execution_id=json_extract(e.binding_body,'$.execution_id')
 AND NEW.step_id=json_extract(e.binding_body,'$.step_id')
 AND NEW.request_digest=k.request_digest AND NEW.adoption_digest=json_extract(k.content_body,'$.automation_binding.continuation.adoption_ref.digest')
 AND NEW.transfer_id=json_extract(k.content_body,'$.automation_binding.continuation.transfer_ref.id')
 AND json(NEW.grant_ref_body)=json(json_extract(c.receipt_body,'$.continuation_grant_ref'))
 AND json(NEW.grant_ref_body)=json(json_extract(k.content_body,'$.automation_binding.continuation.grant_ref'))
 AND EXISTS(SELECT 1 FROM cr_device d WHERE d.transfer_id=c.transfer_id AND d.device_id=e.device_id))
 THEN RAISE(ABORT,'continuation_command_binding') END;
END;
CREATE TRIGGER cn_accept_guard BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ca_command_initial i JOIN ce_command e USING(command_id) JOIN cp_request p USING(prep_key) JOIN ca_request_key k ON k.key_id=i.key_id
 WHERE i.key_id=NEW.key_id AND e.origin='automation' AND p.mode='recovery' AND (json_extract(e.binding_body,'$.execution_id') IS NOT p.execution_id OR json_type(k.content_body,'$.automation_binding.continuation') IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM cn_live_command n WHERE n.command_id=e.command_id)) THEN RAISE(ABORT,'continuation_admission_required') END;
END;
CREATE TRIGGER cn_controller_attempt BEFORE INSERT ON ce_attempt WHEN EXISTS(SELECT 1 FROM cn_command WHERE command_id=NEW.command_id)
 AND NOT EXISTS(SELECT 1 FROM cn_live_command WHERE command_id=NEW.command_id) BEGIN SELECT RAISE(ABORT,'continuation_command_revoked'); END;
CREATE TRIGGER cn_controller_send BEFORE INSERT ON ce_transmission_commit WHEN EXISTS(
 SELECT 1 FROM ce_permit p JOIN ce_attempt a USING(attempt_id) JOIN cn_command n USING(command_id) WHERE p.permit_id=NEW.permit_id
 AND NOT EXISTS(SELECT 1 FROM cn_live_command live WHERE live.command_id=n.command_id)) BEGIN SELECT RAISE(ABORT,'continuation_command_revoked'); END;

CREATE TRIGGER cn_command_update BEFORE UPDATE ON cn_command BEGIN SELECT RAISE(ABORT,'immutable_continuation_link'); END;

CREATE TRIGGER cn_command_delete BEFORE DELETE ON cn_command BEGIN SELECT RAISE(ABORT,'immutable_continuation_link'); END;

-- 全新干净库的受理边界；JSON路径仅负责列对账，Schema/JCS及提供者真实性由可信writer核验。
CREATE TABLE typed_command_source(
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_command(command_id),
 execution_body BLOB NOT NULL CHECK(json_valid(execution_body)),
 adoption_body BLOB NOT NULL CHECK(json_valid(adoption_body)),
 evidence_body BLOB NOT NULL CHECK(json_valid(evidence_body))
) STRICT;
CREATE TRIGGER typed_command_source_u BEFORE UPDATE ON typed_command_source BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_command_source_d BEFORE DELETE ON typed_command_source BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_key_guard BEFORE INSERT ON ca_request_key BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_namespace n JOIN controller_scope s ON s.singleton=1 WHERE n.namespace_id=NEW.namespace_id
 AND n.issuer_id=json_extract(NEW.request_key_body,'$.issuer_id') AND n.issuer_epoch=json_extract(NEW.request_key_body,'$.issuer_epoch')
 AND n.principal_id=json_extract(NEW.request_key_body,'$.principal_id') AND n.request_epoch=json_extract(NEW.request_key_body,'$.request_epoch')
 AND s.authority_service_id=json_extract(NEW.request_key_body,'$.target_scope.authority_service_id')
 AND s.database_instance_id=json_extract(NEW.request_key_body,'$.target_scope.database_instance_id')
 AND NEW.operation_id=json_extract(NEW.request_key_body,'$.operation_id') AND NEW.idempotency_key=json_extract(NEW.request_key_body,'$.idempotency_key')
 AND NEW.device_id=json_extract(NEW.content_body,'$.device_id') AND json_type(NEW.content_body,'$.parameters')='object'
 AND json_type(NEW.content_body,'$.context_id') IS NULL AND json_type(NEW.content_body,'$.idempotency_key') IS NULL
 AND json_type(NEW.content_body,'$.correlation_id') IS NULL AND json_type(NEW.content_body,'$.continuation') IS NULL)
 THEN RAISE(ABORT,'typed_request_key') END;
END;
CREATE TRIGGER typed_adjudication_guard BEFORE INSERT ON ca_adjudication BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_request_key k WHERE k.key_id=NEW.key_id
 AND json(json_extract(NEW.adjudication_body,'$.identity.key'))=json(k.request_key_body)
 AND json_extract(NEW.adjudication_body,'$.identity.request_digest')=k.request_digest
 AND json_extract(NEW.adjudication_body,'$.adjudication_id')=NEW.adjudication_id
 AND json_extract(NEW.adjudication_body,'$.adjudication_digest')=NEW.adjudication_digest
 AND json_extract(NEW.adjudication_body,'$.decision')=NEW.decision
 AND json_extract(NEW.adjudication_body,'$.command_ref.object_id') IS NEW.command_id
 AND json_extract(NEW.adjudication_body,'$.commit_ref.object_id')=NEW.commit_id)
 THEN RAISE(ABORT,'typed_adjudication') END;
END;
CREATE TRIGGER typed_controller_seal BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_request_key k JOIN ca_command_initial i USING(key_id)
 JOIN ce_command e USING(command_id) JOIN typed_command_source t USING(command_id) JOIN cn_command n USING(command_id)
 WHERE k.key_id=NEW.key_id AND k.transport_body IS NOT NULL
 AND json_remove(k.transport_body,'$.context_id','$.idempotency_key','$.correlation_id')=json(k.content_body)
 AND json_extract(k.transport_body,'$.idempotency_key')=k.idempotency_key
 AND e.origin='automation' AND json(e.binding_body)=json(json_extract(k.content_body,'$.automation_binding'))
 AND json(n.binding_body)=json(e.binding_body)
 AND json_extract(e.binding_body,'$.execution_id')=json_extract(t.execution_body,'$.execution_id')
 AND json_extract(e.binding_body,'$.execution_binding_ref.digest')=json_extract(t.execution_body,'$.binding_digest')
 AND n.adoption_digest=json_extract(t.adoption_body,'$.adoption_digest'))
 THEN RAISE(ABORT,'typed_admission_seal') END;
END;

-- 237表保持同一布局；只允许完整公共对象进入新候选的cm/cv正文。
CREATE TRIGGER tv_state BEFORE INSERT ON cm_revision BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controller_scope s WHERE s.singleton=1
 AND json_extract(NEW.state_body,'$.command_id')=NEW.command_id
 AND json_extract(NEW.state_body,'$.scope.authority_service_id')=s.authority_service_id
 AND json_extract(NEW.state_body,'$.scope.database_instance_id')=s.database_instance_id
 AND json_extract(NEW.state_body,'$.revision')=ltrim(NEW.revision,'0')
 AND json_extract(NEW.state_body,'$.phase')=NEW.phase AND json_extract(NEW.state_body,'$.outcome')=NEW.outcome
 AND json_extract(NEW.state_body,'$.effect_status')=NEW.effect_status AND json_extract(NEW.state_body,'$.resource_status')=NEW.resource_status
 AND json_extract(NEW.state_body,'$.automation_continuation')=CASE NEW.paused_latched WHEN 1 THEN 'paused_latched' ELSE 'eligible' END
 AND json_extract(NEW.state_body,'$.terminal_revision') IS ltrim(NEW.terminal_revision,'0')
 AND json_extract(NEW.state_body,'$.resolution_ref.id') IS NEW.resolution_id
 AND json_type(NEW.state_body,'$.attempt_ids')='array' AND json_type(NEW.state_body,'$.completion_evidence_refs')='array'
 AND json_type(NEW.state_body,'$.resource_evidence_refs')='array') THEN RAISE(ABORT,'typed_state_columns') END;
END;
CREATE TRIGGER tv_metadata BEFORE INSERT ON cv_metadata BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial i JOIN ca_request_key k USING(key_id) WHERE i.command_id=NEW.command_id
 AND json_extract(NEW.metadata_body,'$.command_id')=NEW.command_id
 AND json(json_extract(NEW.metadata_body,'$.request_identity.key'))=json(k.request_key_body)
 AND json_extract(NEW.metadata_body,'$.request_identity.request_digest')=k.request_digest
 AND json_extract(NEW.metadata_body,'$.initial_command_ref.digest')=i.command_digest
 AND json_extract(NEW.metadata_body,'$.initial_command_ref.object_id')=i.command_id
 AND json_extract(NEW.metadata_body,'$.actor.principal_id')=json_extract(k.request_key_body,'$.principal_id')
 AND json_extract(NEW.metadata_body,'$.actor.issuer_id')=json_extract(k.request_key_body,'$.issuer_id')
 AND json_extract(NEW.metadata_body,'$.actor.issuer_epoch')=json_extract(k.request_key_body,'$.issuer_epoch')
 AND json_extract(NEW.metadata_body,'$.target.device_id')=k.device_id
 AND json_extract(NEW.metadata_body,'$.target.action_id')=json_extract(k.content_body,'$.action_id')
 AND json_extract(NEW.metadata_body,'$.target.capability_version')=json_extract(k.content_body,'$.capability_version')
 AND json_extract(NEW.metadata_body,'$.origin')=json_extract(k.content_body,'$.origin')
 AND json(json_extract(NEW.metadata_body,'$.automation_binding')) IS json(json_extract(k.content_body,'$.automation_binding'))
 AND json(json_extract(NEW.metadata_body,'$.run_binding')) IS json(json_extract(k.content_body,'$.run_binding'))
 AND json(json_extract(NEW.metadata_body,'$.dispatch'))=json(json_extract(k.content_body,'$.dispatch'))
 AND json(json_extract(NEW.metadata_body,'$.control_binding'))=json(json_extract(k.content_body,'$.expected_control')))
 THEN RAISE(ABORT,'typed_metadata_binding') END;
END;
CREATE TRIGGER tv_publish BEFORE INSERT ON cm_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_record v JOIN cm_revision r USING(command_id,revision)
 JOIN cv_metadata m USING(command_id) JOIN cm_policy p USING(command_id) JOIN cv_snapshot s USING(snapshot_id)
 WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision
 AND json_extract(v.record_body,'$.command_id')=v.command_id AND json_extract(v.record_body,'$.revision')=ltrim(v.revision,'0')
 AND json_extract(v.record_body,'$.record_digest')=v.record_digest
 AND json(json_extract(v.record_body,'$.state'))=json(r.state_body)
 AND json_extract(v.record_body,'$.state_ref.id')=v.command_id AND json_extract(v.record_body,'$.state_ref.revision')=ltrim(v.revision,'0')
 AND json_extract(v.record_body,'$.state_ref.digest')=r.state_digest
 AND json(json_extract(v.record_body,'$.policy'))=json(p.policy_body)
 AND json_remove(v.record_body,'$.revision','$.state_ref','$.state','$.completion','$.attempts','$.cancellation','$.evidence_index','$.record_digest','$.policy')=json(m.metadata_body)
 AND json_extract(v.record_body,'$.evidence_index.snapshot_ref.id')=s.snapshot_id
 AND json_extract(v.record_body,'$.evidence_index.snapshot_ref.digest')=s.snapshot_digest
 AND json_extract(v.record_body,'$.evidence_index.total')=CASE s.total WHEN '00000000000000000000' THEN '0' ELSE ltrim(s.total,'0') END
 AND json(json_extract(v.record_body,'$.evidence_index.state_ref'))=json(json_extract(v.record_body,'$.state_ref'))
 AND json_extract(v.record_body,'$.completion.required')=p.required_completion
 AND json(json_extract(v.record_body,'$.completion.policy_ref'))=json(json_extract(p.policy_body,'$.completion_policy_ref'))
 AND json(json_extract(v.record_body,'$.completion.evidence_refs'))=json(json_extract(r.state_body,'$.completion_evidence_refs')))
 THEN RAISE(ABORT,'typed_public_record') END;
 SELECT CASE WHEN EXISTS(SELECT a.attempt_id FROM cm_revision_attempt a WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.attempt_id') FROM cv_record v,json_each(v.record_body,'$.attempts') j WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision)
 OR EXISTS(SELECT json_extract(j.value,'$.attempt_id') FROM cv_record v,json_each(v.record_body,'$.attempts') j WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision
 EXCEPT SELECT a.attempt_id FROM cm_revision_attempt a WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'typed_public_attempts') END;
END;

-- 固定修订库存；资格与JCS仍由本地writer核验，JSON非空不是权威证明。
CREATE TABLE av_snapshot(
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 inventory_digest TEXT NOT NULL, inventory_body BLOB NOT NULL CHECK(json_valid(inventory_body) AND length(inventory_body)<=16777216),
 selection_digest TEXT NOT NULL, selection_body BLOB NOT NULL CHECK(json_valid(selection_body)),
 projection_digest TEXT NOT NULL, projection_body BLOB NOT NULL CHECK(json_valid(projection_body)),
 provider_digest TEXT NOT NULL, provider_body BLOB NOT NULL CHECK(json_valid(provider_body)),
 CHECK(length(inventory_body)+length(selection_body)+length(projection_body)+length(provider_body)<=16777216),
 PRIMARY KEY(command_id,revision),
 FOREIGN KEY(command_id,revision) REFERENCES cm_revision(command_id,revision),
 FOREIGN KEY(command_id,revision) REFERENCES cv_record(command_id,revision),
 FOREIGN KEY(command_id,revision) REFERENCES cm_commit(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER av_snapshot_insert BEFORE INSERT ON av_snapshot BEGIN
 SELECT CASE WHEN json_type(NEW.inventory_body,'$.attempts') IS NOT 'array' OR json_type(NEW.inventory_body,'$.packets') IS NOT 'array'
 OR json_type(NEW.inventory_body,'$.exits') IS NOT 'array' OR json_type(NEW.inventory_body,'$.transmissions') IS NOT 'array'
 OR json_type(NEW.inventory_body,'$.reports') IS NOT 'array' OR json_type(NEW.inventory_body,'$.evidence') IS NOT 'array'
 OR json_type(NEW.inventory_body,'$.assignments') IS NOT 'array' OR json_type(NEW.inventory_body,'$.valid_decision_refs') IS NOT 'array'
 OR json_type(NEW.inventory_body,'$.time_projections') IS NOT 'array'
 THEN RAISE(ABORT,'attempt_inventory_array_types') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_frozen') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_revision r JOIN cv_record v USING(command_id,revision)
 WHERE r.command_id=NEW.command_id AND r.revision=NEW.revision
 AND json_extract(NEW.inventory_body,'$.command_id')=NEW.command_id
 AND json_extract(NEW.inventory_body,'$.state_ref.id')=NEW.command_id
 AND json_extract(NEW.inventory_body,'$.state_ref.revision')=ltrim(NEW.revision,'0')
 AND json_extract(NEW.inventory_body,'$.state_ref.digest')=r.state_digest
 AND json(json_extract(NEW.inventory_body,'$.state'))=json(r.state_body)
 AND json(json_extract(NEW.projection_body,'$.state_ref'))=json(json_extract(NEW.inventory_body,'$.state_ref'))
 AND json(json_extract(NEW.projection_body,'$.attempts'))=json(json_extract(v.record_body,'$.attempts'))
 AND json(json_extract(NEW.projection_body,'$.selections'))=json(NEW.selection_body)
 AND json_extract(NEW.projection_body,'$.projection_digest')=NEW.projection_digest
 AND json(json_extract(NEW.provider_body,'$.state_ref'))=json(json_extract(NEW.inventory_body,'$.state_ref')))
 THEN RAISE(ABORT,'attempt_inventory_binding') END;
END;
CREATE TRIGGER av_publish BEFORE INSERT ON cm_commit
WHEN EXISTS(SELECT 1 FROM cm_revision_attempt WHERE command_id=NEW.command_id AND revision=NEW.revision) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM av_snapshot WHERE command_id=NEW.command_id AND revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_required') END;
 -- 封存发生在最后公开提交点：先算inventory后出现的原件也不能漏掉。
 SELECT CASE WHEN EXISTS(
  SELECT a.attempt_id FROM cm_revision_attempt a WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
  EXCEPT SELECT json_extract(j.value,'$.attempt_id') FROM av_snapshot s,json_each(s.inventory_body,'$.attempts') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
  SELECT json_extract(j.value,'$.attempt_id') FROM av_snapshot s,json_each(s.inventory_body,'$.attempts') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
  EXCEPT SELECT a.attempt_id FROM cm_revision_attempt a WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_attempt_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM av_snapshot s WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision AND
 (json_array_length(s.inventory_body,'$.attempts')!=(SELECT count(*) FROM cm_revision_attempt WHERE command_id=NEW.command_id AND revision=NEW.revision)
 OR json_array_length(s.inventory_body,'$.packets')!=(SELECT count(*) FROM ce_packet p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 OR json_array_length(s.inventory_body,'$.transmissions')!=(SELECT count(*) FROM ce_permit p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 OR json_array_length(s.inventory_body,'$.reports')!=(SELECT count(*) FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 OR json_array_length(s.inventory_body,'$.assignments')!=(SELECT count(*) FROM ep_request e JOIN cm_revision_attempt a ON a.attempt_id=e.proposed_attempt_id WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision AND e.kind='ordinary')
 OR json_array_length(s.inventory_body,'$.evidence')!=(SELECT count(*) FROM cv_record v JOIN cv_snapshot_member m USING(snapshot_id) WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision)))
 THEN RAISE(ABORT,'attempt_inventory_member_count') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM av_snapshot s,json_each(s.inventory_body,'$.attempts') j
 WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision AND NOT EXISTS(
 SELECT 1 FROM cm_attempt a JOIN cm_revision r ON r.command_id=a.command_id AND r.revision=a.prepared_revision
 WHERE a.attempt_id=json_extract(j.value,'$.attempt_id') AND a.command_id=NEW.command_id
 AND a.ordinal=json_extract(j.value,'$.ordinal') AND json(r.state_body)=json(json_extract(j.value,'$.prepared_state'))))
 THEN RAISE(ABORT,'attempt_inventory_prepared') END;
 SELECT CASE WHEN EXISTS(
 SELECT p.packet_id FROM ce_packet p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.packet_id') FROM av_snapshot s,json_each(s.inventory_body,'$.packets') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
 SELECT json_extract(j.value,'$.packet_id') FROM av_snapshot s,json_each(s.inventory_body,'$.packets') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT p.packet_id FROM ce_packet p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_packet_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM av_snapshot s,json_each(s.inventory_body,'$.packets') j
 WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision AND NOT EXISTS(SELECT 1 FROM ce_packet p
 WHERE p.packet_id=json_extract(j.value,'$.packet_id') AND json(p.packet_body)=json(j.value)))
 THEN RAISE(ABORT,'attempt_inventory_packet_body') END;
 SELECT CASE WHEN EXISTS(
 SELECT p.permit_id FROM ce_permit p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.permit_id') FROM av_snapshot s,json_each(s.inventory_body,'$.transmissions') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
 SELECT json_extract(j.value,'$.permit_id') FROM av_snapshot s,json_each(s.inventory_body,'$.transmissions') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT p.permit_id FROM ce_permit p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_permit_set') END;
 SELECT CASE WHEN EXISTS(
 SELECT r.report_id FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.report_id') FROM av_snapshot s,json_each(s.inventory_body,'$.reports') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
 SELECT json_extract(j.value,'$.report_id') FROM av_snapshot s,json_each(s.inventory_body,'$.reports') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT r.report_id FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_report_set') END;
 SELECT CASE WHEN EXISTS(
 SELECT e.prepare_id FROM ep_request e JOIN cm_revision_attempt a ON a.attempt_id=e.proposed_attempt_id
 WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision AND e.kind='ordinary'
 EXCEPT SELECT json_extract(j.value,'$.prepare_id') FROM av_snapshot s,json_each(s.inventory_body,'$.assignments') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
 SELECT json_extract(j.value,'$.prepare_id') FROM av_snapshot s,json_each(s.inventory_body,'$.assignments') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT e.prepare_id FROM ep_request e JOIN cm_revision_attempt a ON a.attempt_id=e.proposed_attempt_id
 WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision AND e.kind='ordinary')
 THEN RAISE(ABORT,'attempt_inventory_assignment_set') END;
 SELECT CASE WHEN EXISTS(SELECT json_extract(j.value,'$.source_ref.id'),json_extract(j.value,'$.source_ref.revision')
 FROM av_snapshot s,json_each(s.inventory_body,'$.evidence') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT e.evidence_id,ltrim(e.revision,'0') FROM cv_record v JOIN cv_snapshot_member m USING(snapshot_id)
 JOIN cv_evidence e ON e.evidence_id=m.evidence_id AND e.revision=m.evidence_revision WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision)
 OR EXISTS(SELECT e.evidence_id,ltrim(e.revision,'0') FROM cv_record v JOIN cv_snapshot_member m USING(snapshot_id)
 JOIN cv_evidence e ON e.evidence_id=m.evidence_id AND e.revision=m.evidence_revision WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.source_ref.id'),json_extract(j.value,'$.source_ref.revision')
 FROM av_snapshot s,json_each(s.inventory_body,'$.evidence') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_evidence_set') END;
END;
CREATE TRIGGER av_snapshot_update BEFORE UPDATE ON av_snapshot BEGIN SELECT RAISE(ABORT,'immutable_attempt_inventory'); END;
CREATE TRIGGER av_snapshot_delete BEFORE DELETE ON av_snapshot BEGIN SELECT RAISE(ABORT,'immutable_attempt_inventory'); END;

-- 最终封存物理候选；来源真实性/JCS仍须本地writer核验，四个临时发送阻断保持。
CREATE TABLE fa_seal(
 transaction_id TEXT PRIMARY KEY NOT NULL, seal_id TEXT NOT NULL UNIQUE,
 permit_id TEXT NOT NULL UNIQUE, issued_revision TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('ordinary','cancel')),
 command_id TEXT NOT NULL, state_revision TEXT NOT NULL,
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),hold_id TEXT NOT NULL REFERENCES cr_hold_commit(hold_id) DEFERRABLE INITIALLY DEFERRED,
 ownership_id TEXT NOT NULL REFERENCES ow_commit(ownership_id) DEFERRABLE INITIALLY DEFERRED,
 before_snapshot_id TEXT NOT NULL REFERENCES go_snapshot_commit(snapshot_id),
 after_snapshot_id TEXT NOT NULL REFERENCES go_snapshot_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED,
 ordinary_id TEXT, cancel_id TEXT,
 selected_tick TEXT NOT NULL, sealed_tick TEXT NOT NULL, not_before_tick TEXT NOT NULL, before_tick TEXT NOT NULL,
 seal_digest TEXT NOT NULL, seal_body BLOB NOT NULL CHECK(json_valid(seal_body) AND length(seal_body)<=1048576),
 CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*' AND issued_revision>'00000000000000000000'),
 CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 CHECK(length(sealed_tick)=20 AND sealed_tick NOT GLOB '*[^0-9]*'),
 CHECK(length(not_before_tick)=20 AND not_before_tick NOT GLOB '*[^0-9]*'),
 CHECK(length(before_tick)=20 AND before_tick NOT GLOB '*[^0-9]*'),
 CHECK(selected_tick<=sealed_tick AND sealed_tick<before_tick AND not_before_tick<before_tick),
 CHECK((kind='ordinary' AND ordinary_id IS permit_id AND cancel_id IS NULL) OR (kind='cancel' AND cancel_id IS permit_id AND ordinary_id IS NULL)),
 UNIQUE(permit_id,issued_revision,kind),UNIQUE(seal_id,permit_id),
 FOREIGN KEY(command_id,state_revision) REFERENCES cm_revision(command_id,revision),
 FOREIGN KEY(permit_id,issued_revision,kind) REFERENCES ci_issue(permit_id,issued_revision,kind) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(ordinary_id) REFERENCES ce_transmission_commit(permit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancel_id) REFERENCES ci_cancel_commit(permit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(seal_id) REFERENCES fa_commit(seal_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE fa_input(
 seal_id TEXT NOT NULL REFERENCES fa_seal(seal_id), role TEXT NOT NULL CHECK(role IN ('origin','capability','encoding','authorization','control','gate_commit','gate_access','ownership','permit_authority','guard','budget','time','resource_before','resource_after','resource_safety','gate_safety','run_deny','command_deny','ordinary_closure','protection_assessment','primitive_dependency')),
 projection_id TEXT NOT NULL,projection_revision TEXT NOT NULL,projection_digest TEXT NOT NULL,
 source_id TEXT NOT NULL,source_revision TEXT NOT NULL,source_digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(json_valid(body) AND length(body)<=16777216),
 PRIMARY KEY(seal_id,role),UNIQUE(seal_id,projection_id)
) STRICT;
CREATE TABLE fa_commit(
 seal_id TEXT PRIMARY KEY NOT NULL,permit_id TEXT NOT NULL UNIQUE,
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(json_valid(audit_body)),outbox_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(json_valid(outbox_body)),
 FOREIGN KEY(seal_id,permit_id) REFERENCES fa_seal(seal_id,permit_id)
) STRICT;
-- 故意不FK至fa_seal：rolled_back/unknown可发生在没有持久seal时；从不充当许可。
CREATE TABLE fa_observation(
 observation_id TEXT PRIMARY KEY NOT NULL,transaction_id TEXT NOT NULL,seal_id TEXT NOT NULL,permit_id TEXT NOT NULL,
 seal_digest TEXT NOT NULL,outcome TEXT NOT NULL CHECK(outcome IN ('committed','rolled_back','unknown')),
 observed_tick TEXT NOT NULL CHECK(length(observed_tick)=20 AND observed_tick NOT GLOB '*[^0-9]*'),
 candidate_body BLOB NOT NULL CHECK(json_valid(candidate_body) AND length(candidate_body)<=1048576),
 observation_body BLOB NOT NULL CHECK(json_valid(observation_body) AND length(observation_body)<=1048576)
) STRICT;
CREATE INDEX fa_observation_transaction ON fa_observation(transaction_id);
CREATE INDEX fa_observation_permit ON fa_observation(permit_id);
CREATE INDEX fa_observation_seal ON fa_observation(seal_id);
CREATE TRIGGER fa_seal_insert BEFORE INSERT ON fa_seal BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_observation WHERE transaction_id=NEW.transaction_id OR permit_id=NEW.permit_id OR seal_id=NEW.seal_id)
 THEN RAISE(ABORT,'observed_transaction_not_reissuable') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controller_scope c JOIN cm_revision r ON r.command_id=NEW.command_id AND r.revision=NEW.state_revision
 WHERE json_extract(NEW.seal_body,'$.binding.scope.authority_service_id')=c.authority_service_id
 AND json_extract(NEW.seal_body,'$.binding.scope.database_instance_id')=c.database_instance_id
 AND json_extract(NEW.seal_body,'$.transaction_id')=NEW.transaction_id AND json_extract(NEW.seal_body,'$.seal_id')=NEW.seal_id
 AND json_extract(NEW.seal_body,'$.permit_id')=NEW.permit_id AND json_extract(NEW.seal_body,'$.seal_digest')=NEW.seal_digest
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.issued_revision'),-20)=NEW.issued_revision
 AND json_extract(NEW.seal_body,'$.identity.kind')=NEW.kind AND json_extract(NEW.seal_body,'$.identity.command_ref.id')=NEW.command_id
 AND json_extract(NEW.seal_body,'$.command_state_ref.id')=NEW.command_id
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.command_state_ref.revision'),-20)=NEW.state_revision
 AND json_extract(NEW.seal_body,'$.command_state_ref.digest')=r.state_digest
 AND json_extract(NEW.seal_body,'$.binding.writer_exit_id')=NEW.exit_id AND json_extract(NEW.seal_body,'$.hold_ref.id')=NEW.hold_id
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.selected_tick_ns'),-20)=NEW.selected_tick
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.sealed_tick_ns'),-20)=NEW.sealed_tick
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.send_window.not_before_tick_ns'),-20)=NEW.not_before_tick
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.send_window.before_tick_ns'),-20)=NEW.before_tick)
 THEN RAISE(ABORT,'final_seal_columns') END;
END;
CREATE TRIGGER fa_input_insert BEFORE INSERT ON fa_input BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_commit WHERE seal_id=NEW.seal_id) THEN RAISE(ABORT,'final_inputs_frozen') END;
 SELECT CASE WHEN NEW.role IN ('ordinary_closure','protection_assessment','primitive_dependency') AND EXISTS(SELECT 1 FROM fa_seal WHERE seal_id=NEW.seal_id AND kind='ordinary') THEN RAISE(ABORT,'final_role_kind') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal s WHERE s.seal_id=NEW.seal_id
 AND json_type(s.seal_body,'$.inputs.'||NEW.role)='object'
 AND json_extract(s.seal_body,'$.inputs.'||NEW.role||'.id')=NEW.projection_id
 AND json_extract(s.seal_body,'$.inputs.'||NEW.role||'.revision')=NEW.projection_revision
 AND json_extract(s.seal_body,'$.inputs.'||NEW.role||'.digest')=NEW.projection_digest
 AND json_extract(NEW.body,'$.role')=NEW.role AND json_extract(NEW.body,'$.transaction_id')=s.transaction_id
 AND json_extract(NEW.body,'$.ref.id')=NEW.projection_id AND json_extract(NEW.body,'$.ref.revision')=NEW.projection_revision
 AND json_extract(NEW.body,'$.ref.digest')=NEW.projection_digest
 AND json_extract(NEW.body,'$.source_ref.id')=NEW.source_id AND json_extract(NEW.body,'$.source_ref.revision')=NEW.source_revision
 AND json_extract(NEW.body,'$.source_ref.digest')=NEW.source_digest
 AND json(json_extract(NEW.body,'$.scope'))=json(json_extract(s.seal_body,'$.binding.scope'))
 AND json(json_extract(NEW.body,'$.body.binding'))=json(json_extract(s.seal_body,'$.binding'))
 AND json(json_extract(NEW.body,'$.body.identity'))=json(json_extract(s.seal_body,'$.identity')))
 THEN RAISE(ABORT,'final_input_binding') END;
END;
CREATE TRIGGER fa_commit_insert BEFORE INSERT ON fa_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal WHERE seal_id=NEW.seal_id AND permit_id=NEW.permit_id AND sealed_tick<=NEW.committed_tick AND NEW.committed_tick<before_tick)
 THEN RAISE(ABORT,'final_commit_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_seal s WHERE s.seal_id=NEW.seal_id AND
 ((SELECT count(*) FROM fa_input WHERE seal_id=s.seal_id)!=CASE s.kind WHEN 'ordinary' THEN 18 ELSE 21 END
 OR (SELECT count(*) FROM json_each(s.seal_body,'$.inputs') WHERE type='object')!=CASE s.kind WHEN 'ordinary' THEN 18 ELSE 21 END
 OR EXISTS(SELECT key FROM json_each(s.seal_body,'$.inputs') WHERE type='object' EXCEPT SELECT role FROM fa_input WHERE seal_id=s.seal_id)
 OR EXISTS(SELECT role FROM fa_input WHERE seal_id=s.seal_id EXCEPT SELECT key FROM json_each(s.seal_body,'$.inputs') WHERE type='object')))
 THEN RAISE(ABORT,'final_input_set') END;
 SELECT CASE WHEN (SELECT coalesce(sum(length(body)),0) FROM fa_input WHERE seal_id=NEW.seal_id)>16777216 THEN RAISE(ABORT,'final_bundle_capacity') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal s JOIN fa_input o ON o.seal_id=s.seal_id AND o.role='ownership'
 JOIN fa_input b ON b.seal_id=s.seal_id AND b.role='resource_before' JOIN fa_input a ON a.seal_id=s.seal_id AND a.role='resource_after'
 WHERE s.seal_id=NEW.seal_id AND o.source_id=s.ownership_id AND b.source_id=s.before_snapshot_id AND a.source_id=s.after_snapshot_id)
 THEN RAISE(ABORT,'final_storage_sources') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal s JOIN ci_issue i USING(permit_id,issued_revision,kind)
 WHERE s.seal_id=NEW.seal_id AND ((s.kind='ordinary' AND EXISTS(SELECT 1 FROM ce_transmission_commit WHERE permit_id=s.permit_id))
 OR (s.kind='cancel' AND EXISTS(SELECT 1 FROM ci_cancel_commit WHERE permit_id=s.permit_id))))
 THEN RAISE(ABORT,'final_domain_commit') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal s JOIN ce_exit e ON e.exit_id=s.exit_id
 JOIN cr_hold h ON h.hold_id=s.hold_id JOIN ow_ownership o ON o.ownership_id=s.ownership_id AND o.hold_id=s.hold_id
 JOIN go_snapshot b ON b.snapshot_id=s.before_snapshot_id JOIN go_snapshot a ON a.snapshot_id=s.after_snapshot_id
 WHERE s.seal_id=NEW.seal_id AND h.command_id=s.command_id AND e.device_id=b.device_id AND e.device_id=a.device_id
 AND e.exit_id=b.exit_id AND e.exit_id=a.exit_id
 AND ((s.kind='ordinary' AND EXISTS(SELECT 1 FROM ce_permit p JOIN ce_attempt t USING(attempt_id)
 WHERE p.permit_id=s.permit_id AND p.exit_id=s.exit_id AND p.issued_revision=s.issued_revision
 AND t.command_id=s.command_id AND h.attempt_id=p.attempt_id
 AND p.attempt_id=json_extract(s.seal_body,'$.identity.attempt_ref.id') AND p.packet_id=json_extract(s.seal_body,'$.packet_ref.packet_id')))
 OR (s.kind='cancel' AND EXISTS(SELECT 1 FROM ci_cancel_transmission p WHERE p.permit_id=s.permit_id
 AND p.exit_id=s.exit_id AND p.issued_revision=s.issued_revision AND p.execution_id=h.cancel_execution_id
 AND p.execution_id=json_extract(s.seal_body,'$.identity.execution_ref.id') AND p.cancellation_id=json_extract(s.seal_body,'$.identity.cancellation_ref.id')
 AND p.packet_id=json_extract(s.seal_body,'$.packet_ref.packet_id')))))
 THEN RAISE(ABORT,'final_domain_anchors') END;
END;
CREATE TRIGGER fa_observation_insert BEFORE INSERT ON fa_observation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controller_scope c WHERE
 json_extract(NEW.candidate_body,'$.binding.scope.authority_service_id')=c.authority_service_id
 AND json_extract(NEW.candidate_body,'$.binding.scope.database_instance_id')=c.database_instance_id
 AND json_extract(NEW.candidate_body,'$.transaction_id')=NEW.transaction_id AND json_extract(NEW.candidate_body,'$.seal_id')=NEW.seal_id
 AND json_extract(NEW.candidate_body,'$.permit_id')=NEW.permit_id AND json_extract(NEW.candidate_body,'$.seal_digest')=NEW.seal_digest
 AND json_extract(NEW.observation_body,'$.observation_id')=NEW.observation_id AND json_extract(NEW.observation_body,'$.transaction_id')=NEW.transaction_id
 AND json_extract(NEW.observation_body,'$.permit_id')=NEW.permit_id AND json_extract(NEW.observation_body,'$.outcome')=NEW.outcome
 AND json_extract(NEW.observation_body,'$.seal_ref.id')=NEW.seal_id AND json_extract(NEW.observation_body,'$.seal_ref.revision')='1'
 AND json_extract(NEW.observation_body,'$.seal_ref.digest')=NEW.seal_digest
 AND substr('00000000000000000000'||json_extract(NEW.observation_body,'$.observed_tick_ns'),-20)=NEW.observed_tick
 AND json(json_extract(NEW.observation_body,'$.scope'))=json(json_extract(NEW.candidate_body,'$.binding.scope')))
 THEN RAISE(ABORT,'final_observation_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_observation WHERE (transaction_id=NEW.transaction_id OR permit_id=NEW.permit_id OR seal_id=NEW.seal_id)
 AND (transaction_id!=NEW.transaction_id OR permit_id!=NEW.permit_id OR seal_id!=NEW.seal_id OR candidate_body!=NEW.candidate_body))
 THEN RAISE(ABORT,'final_observation_identity_conflict') END;
 SELECT CASE WHEN NEW.outcome='committed' AND NOT EXISTS(SELECT 1 FROM fa_seal s JOIN fa_commit k USING(seal_id,permit_id)
 WHERE s.transaction_id=NEW.transaction_id AND s.seal_id=NEW.seal_id AND s.permit_id=NEW.permit_id AND s.seal_body=NEW.candidate_body)
 THEN RAISE(ABORT,'final_commit_unproven') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_seal WHERE transaction_id=NEW.transaction_id OR permit_id=NEW.permit_id OR seal_id=NEW.seal_id)
 AND (NEW.outcome='rolled_back' OR NOT EXISTS(SELECT 1 FROM fa_seal WHERE transaction_id=NEW.transaction_id AND seal_id=NEW.seal_id AND permit_id=NEW.permit_id AND seal_body=NEW.candidate_body))
 THEN RAISE(ABORT,'final_observation_contradiction') END;
END;

CREATE TRIGGER fa_seal_update BEFORE UPDATE ON fa_seal BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;

CREATE TRIGGER fa_seal_delete BEFORE DELETE ON fa_seal BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;

CREATE TRIGGER fa_input_update BEFORE UPDATE ON fa_input BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;

CREATE TRIGGER fa_input_delete BEFORE DELETE ON fa_input BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;

CREATE TRIGGER fa_commit_update BEFORE UPDATE ON fa_commit BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;

CREATE TRIGGER fa_commit_delete BEFORE DELETE ON fa_commit BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;

CREATE TRIGGER fa_observation_update BEFORE UPDATE ON fa_observation BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;

CREATE TRIGGER fa_observation_delete BEFORE DELETE ON fa_observation BEGIN SELECT RAISE(ABORT,'immutable_final_admission'); END;
