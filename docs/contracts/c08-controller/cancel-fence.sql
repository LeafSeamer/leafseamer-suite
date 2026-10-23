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
   WHERE c.permit_id=p.permit_id AND c.disposition='in_flight') THEN 'in_flight'
 WHEN EXISTS(SELECT 1 FROM cf_report r WHERE r.permit_id=p.permit_id AND r.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cf_barrier_coverage c JOIN ce_barrier_ack a USING(barrier_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent')
  OR EXISTS(SELECT 1 FROM cf_target_coverage c JOIN ce_target_result r USING(fence_id,exit_id)
   WHERE c.permit_id=p.permit_id AND c.disposition='not_sent') THEN 'not_sent'
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
