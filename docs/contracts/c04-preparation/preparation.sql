-- 准备/关闭子域设计参考；非生产迁移。连接须开启FK与recursive_triggers。
CREATE TABLE cp_scope (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  authority TEXT NOT NULL CHECK(length(authority)>0),
  database_id TEXT NOT NULL CHECK(length(database_id)>0)
) STRICT;
CREATE TABLE cp_request (
  prep_key TEXT PRIMARY KEY NOT NULL,
  scope_id INTEGER NOT NULL DEFAULT 1 REFERENCES cp_scope(singleton),
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
CREATE TABLE cp_deny_event (
  snapshot_revision TEXT PRIMARY KEY NOT NULL CHECK(length(snapshot_revision)=20 AND snapshot_revision NOT GLOB '*[^0-9]*' AND snapshot_revision>'00000000000000000000'),
  origin_authority TEXT NOT NULL, origin_database TEXT NOT NULL, run_id TEXT NOT NULL,
  generation TEXT NOT NULL CHECK(length(generation)=20 AND generation NOT GLOB '*[^0-9]*' AND generation>'00000000000000000000'),
  deny_revision TEXT NOT NULL CHECK(length(deny_revision)=20 AND deny_revision NOT GLOB '*[^0-9]*' AND deny_revision>'00000000000000000000'),
  close_id TEXT NOT NULL UNIQUE REFERENCES cp_close(close_id),
  commit_id TEXT NOT NULL REFERENCES cp_commit(commit_id) DEFERRABLE INITIALLY DEFERRED,
  UNIQUE(origin_authority,origin_database,run_id,deny_revision)
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
CREATE VIEW cp_deny_current AS
 SELECT d.* FROM cp_deny_event d JOIN cp_commit c ON c.commit_id=d.commit_id
 WHERE NOT EXISTS(SELECT 1 FROM cp_deny_event n JOIN cp_commit nc ON nc.commit_id=n.commit_id
   WHERE (n.origin_authority,n.origin_database,n.run_id)=(d.origin_authority,d.origin_database,d.run_id)
     AND n.generation>d.generation);
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
   SELECT 1 FROM cp_request r JOIN cp_deny_current d
    ON (r.origin_authority,r.origin_database,r.run_id)=(d.origin_authority,d.origin_database,d.run_id)
   WHERE r.prep_key=NEW.prep_key AND r.generation<=d.generation
 ) THEN RAISE(ABORT,'run_denied') END;
END;
CREATE TRIGGER cp_deny_guard BEFORE INSERT ON cp_deny_event BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cp_commit WHERE commit_id=NEW.commit_id) THEN RAISE(ABORT,'commit_frozen') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cp_close c JOIN cp_request r ON r.prep_key=c.prep_key
   WHERE c.close_id=NEW.close_id AND c.commit_id=NEW.commit_id
     AND (r.origin_authority,r.origin_database,r.run_id,r.generation)=
         (NEW.origin_authority,NEW.origin_database,NEW.run_id,NEW.generation))
   THEN RAISE(ABORT,'deny_binding') END;
 SELECT CASE WHEN NEW.snapshot_revision!=(
   SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
                 (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
   FROM (SELECT coalesce(max(snapshot_revision),'00000000000000000000') v FROM cp_deny_event))
   THEN RAISE(ABORT,'snapshot_successor') END;
 SELECT CASE WHEN NEW.deny_revision!=(
   SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
                 (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
   FROM (SELECT coalesce(max(deny_revision),'00000000000000000000') v FROM cp_deny_event
     WHERE (origin_authority,origin_database,run_id)=(NEW.origin_authority,NEW.origin_database,NEW.run_id)))
   THEN RAISE(ABORT,'deny_successor') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cp_deny_event
   WHERE (origin_authority,origin_database,run_id)=(NEW.origin_authority,NEW.origin_database,NEW.run_id)
     AND generation>=NEW.generation) THEN RAISE(ABORT,'deny_not_increased') END;
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
    AND EXISTS(SELECT 1 FROM cp_deny_event d
      WHERE (d.origin_authority,d.origin_database,d.run_id)=(r.origin_authority,r.origin_database,r.run_id)
        AND d.generation>=r.generation AND (d.commit_id=NEW.commit_id OR EXISTS(SELECT 1 FROM cp_commit dc WHERE dc.commit_id=d.commit_id))))
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

-- 墓碑、历史事实与通知均不原地修改或删除，包括REPLACE的隐式删除。
CREATE TRIGGER cp_scope_u BEFORE UPDATE ON cp_scope BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_scope_d BEFORE DELETE ON cp_scope BEGIN SELECT RAISE(ABORT,'immutable'); END;
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
CREATE TRIGGER cp_deny_event_u BEFORE UPDATE ON cp_deny_event BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_deny_event_d BEFORE DELETE ON cp_deny_event BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_commit_u BEFORE UPDATE ON cp_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_commit_d BEFORE DELETE ON cp_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_audit_u BEFORE UPDATE ON cp_audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_audit_d BEFORE DELETE ON cp_audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_notification_u BEFORE UPDATE ON cp_notification BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER cp_notification_d BEFORE DELETE ON cp_notification BEGIN SELECT RAISE(ABORT,'immutable'); END;
