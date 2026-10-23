-- 生成物：两阶段关闭119表候选，禁止部署；请修改唯一源并重新生成。
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
  content_body BLOB NOT NULL CHECK(length(content_body)>0),
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
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
   OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
             WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent') THEN 'not_sent'
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
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent') THEN 'not_sent'
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
 UNIQUE(validation_id,device_id)
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
 attempt_id TEXT NOT NULL UNIQUE REFERENCES ce_attempt(attempt_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 hold_digest TEXT NOT NULL,
 hold_body BLOB NOT NULL CHECK(length(hold_body)>0),
 UNIQUE(hold_id,command_id),
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
 source_kind TEXT NOT NULL CHECK(source_kind IN ('report','cancel_report','barrier_ack','target_result','validation_revocation','cancel_closure_ack')),
 source_id TEXT NOT NULL,
 source_exit_id TEXT,
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
CREATE TRIGGER cr_hold_guard BEFORE INSERT ON cr_hold BEGIN
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
CREATE TRIGGER cr_hold_seal BEFORE INSERT ON cr_hold_commit BEGIN
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
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_invalid_release WHERE release_id=NEW.release_id)
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
CREATE TRIGGER cm_hold_binding BEFORE INSERT ON cr_hold_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_dispatch_binding b JOIN cr_hold h USING(hold_id)
  WHERE b.hold_id=NEW.hold_id AND b.command_id=h.command_id)
  THEN RAISE(ABORT,'dispatch_revision_required') END;
END;
CREATE TRIGGER cm_hold_state BEFORE INSERT ON cr_hold BEGIN
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
 WHEN EXISTS(SELECT 1 FROM cv_cancel_deny WHERE command_id=NEW.command_id)
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
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM cf_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cf_barrier_coverage c JOIN ce_barrier_ack a USING(barrier_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cf_target_coverage c JOIN ce_target_result r USING(fence_id,exit_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cc_coverage z JOIN cc_ack k USING(barrier_id) WHERE z.permit_id=p.permit_id AND z.disposition='not_sent') THEN 'not_sent'
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
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0), UNIQUE(cancellation_id,primitive_id)
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
CREATE VIEW cc_valid_closure AS
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
