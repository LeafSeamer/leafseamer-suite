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
   WHERE c.permit_id=p.permit_id AND c.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM ce_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM ce_coverage c JOIN ce_target_result a USING(fence_id,exit_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent') THEN 'not_sent'
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
