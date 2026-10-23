-- 在230表候选之后加载；Controller P3当前资格与不可变通知，不是生产迁移。
CREATE TABLE ra_barrier_revocation(
 barrier_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_barrier_ack(barrier_id),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW ra_qualified_cut AS SELECT f.fence_id FROM ce_fence f JOIN ce_cut_commit k USING(fence_id)
 WHERE NOT EXISTS(SELECT 1 FROM ce_target t WHERE t.fence_id=f.fence_id AND NOT EXISTS(
 SELECT 1 FROM ce_target_result r JOIN ce_result_binding b USING(fence_id,exit_id)
 WHERE r.fence_id=t.fence_id AND r.exit_id=t.exit_id AND r.evidence_kind=b.kind AND
 ((b.kind='worker_ack' AND EXISTS(SELECT 1 FROM ce_barrier_ack a WHERE a.barrier_id=b.barrier_id)
 AND NOT EXISTS(SELECT 1 FROM ra_barrier_revocation v WHERE v.barrier_id=b.barrier_id))
 OR(b.kind='supervisor_retired' AND EXISTS(SELECT 1 FROM ce_retirement e WHERE e.exit_id=b.exit_id)
 AND NOT EXISTS(SELECT 1 FROM cu_revocation v WHERE v.kind='retirement' AND v.object_id=b.exit_id)))));
DROP VIEW pd_valid_application;
CREATE VIEW pd_valid_application AS SELECT a.* FROM ce_application a
 JOIN pd_valid_closure p ON p.closure_id=a.prepare_closure_id JOIN ra_qualified_cut q USING(fence_id);
CREATE TRIGGER ra_application_guard BEFORE INSERT ON ce_application BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ra_qualified_cut WHERE fence_id=NEW.fence_id)
 THEN RAISE(ABORT,'run_application_evidence_invalid') END;
END;
CREATE VIEW ra_invalid_evidence AS
 SELECT a.fence_id,'prepare_closure' AS kind,a.prepare_closure_id AS object_id FROM ce_application a
 WHERE NOT EXISTS(SELECT 1 FROM pd_valid_closure p WHERE p.closure_id=a.prepare_closure_id)
 UNION
 SELECT a.fence_id,'run_barrier_ack',b.barrier_id FROM ce_application a JOIN ce_result_binding b USING(fence_id)
 JOIN ra_barrier_revocation v USING(barrier_id) WHERE b.kind='worker_ack'
 UNION
 SELECT a.fence_id,'retirement',b.exit_id FROM ce_application a JOIN ce_result_binding b USING(fence_id)
 JOIN cu_revocation v ON v.kind='retirement' AND v.object_id=b.exit_id WHERE b.kind='supervisor_retired';
CREATE TABLE ra_status_event(
 fence_id TEXT NOT NULL REFERENCES ce_application(fence_id),
 revision INTEGER NOT NULL CHECK(revision IN (1,2)),
 state TEXT NOT NULL CHECK(state IN ('applied','indeterminate')),
 cause_kind TEXT NOT NULL CHECK(cause_kind IN ('initial','prepare_closure','run_barrier_ack','retirement')),
 cause_id TEXT NOT NULL,
 PRIMARY KEY(fence_id,revision),
 CHECK((revision=1 AND state='applied' AND cause_kind='initial' AND cause_id=fence_id)
 OR(revision=2 AND state='indeterminate' AND cause_kind!='initial'))
) STRICT;
CREATE TRIGGER ra_event_guard BEFORE INSERT ON ra_status_event BEGIN
 SELECT CASE WHEN (NEW.revision=1 AND NOT EXISTS(SELECT 1 FROM pd_valid_application WHERE fence_id=NEW.fence_id))
 OR(NEW.revision=2 AND (NOT EXISTS(SELECT 1 FROM ra_status_event WHERE fence_id=NEW.fence_id AND revision=1)
 OR NOT EXISTS(SELECT 1 FROM ra_invalid_evidence e WHERE e.fence_id=NEW.fence_id AND e.kind=NEW.cause_kind AND e.object_id=NEW.cause_id)))
 THEN RAISE(ABORT,'run_status_source') END;
END;
CREATE TRIGGER ra_initial AFTER INSERT ON ce_application BEGIN
 INSERT INTO ra_status_event VALUES(NEW.fence_id,1,'applied','initial',NEW.fence_id);
END;
CREATE TRIGGER ra_prepare_invalid AFTER INSERT ON pd_ack_revocation BEGIN
 INSERT INTO ra_status_event SELECT a.fence_id,2,'indeterminate','prepare_closure',a.prepare_closure_id
 FROM ce_application a WHERE NOT EXISTS(SELECT 1 FROM pd_valid_closure p WHERE p.closure_id=a.prepare_closure_id)
 AND NOT EXISTS(SELECT 1 FROM ra_status_event e WHERE e.fence_id=a.fence_id AND e.revision=2);
END;
CREATE TRIGGER ra_retirement_invalid AFTER INSERT ON cu_revocation WHEN NEW.kind='retirement' BEGIN
 INSERT INTO ra_status_event SELECT a.fence_id,2,'indeterminate',
 CASE WHEN NOT EXISTS(SELECT 1 FROM pd_valid_closure p WHERE p.closure_id=a.prepare_closure_id) THEN 'prepare_closure' ELSE 'retirement' END,
 CASE WHEN NOT EXISTS(SELECT 1 FROM pd_valid_closure p WHERE p.closure_id=a.prepare_closure_id) THEN a.prepare_closure_id ELSE NEW.object_id END
 FROM ce_application a WHERE NOT EXISTS(SELECT 1 FROM pd_valid_application p WHERE p.fence_id=a.fence_id)
 AND NOT EXISTS(SELECT 1 FROM ra_status_event e WHERE e.fence_id=a.fence_id AND e.revision=2);
END;
CREATE TRIGGER ra_barrier_invalid AFTER INSERT ON ra_barrier_revocation BEGIN
 INSERT INTO ra_status_event SELECT a.fence_id,2,'indeterminate','run_barrier_ack',NEW.barrier_id
 FROM ce_application a JOIN ce_result_binding b USING(fence_id) WHERE b.barrier_id=NEW.barrier_id
 AND NOT EXISTS(SELECT 1 FROM ra_status_event e WHERE e.fence_id=a.fence_id AND e.revision=2);
END;
CREATE VIEW ra_current_status AS SELECT a.fence_id,a.receipt_id,a.prepare_closure_id,e.revision,e.state,e.cause_kind,e.cause_id
 FROM ce_application a JOIN ra_status_event e USING(fence_id)
 WHERE e.revision=(SELECT max(n.revision) FROM ra_status_event n WHERE n.fence_id=a.fence_id)
 AND ((e.state='applied' AND EXISTS(SELECT 1 FROM pd_valid_application p WHERE p.fence_id=a.fence_id))
 OR(e.state='indeterminate' AND NOT EXISTS(SELECT 1 FROM pd_valid_application p WHERE p.fence_id=a.fence_id)));
CREATE TRIGGER ra_barrier_revocation_u BEFORE UPDATE ON ra_barrier_revocation BEGIN SELECT RAISE(ABORT,'immutable_run_delivery'); END;
CREATE TRIGGER ra_barrier_revocation_d BEFORE DELETE ON ra_barrier_revocation BEGIN SELECT RAISE(ABORT,'immutable_run_delivery'); END;
CREATE TRIGGER ra_status_event_u BEFORE UPDATE ON ra_status_event BEGIN SELECT RAISE(ABORT,'immutable_run_delivery'); END;
CREATE TRIGGER ra_status_event_d BEFORE DELETE ON ra_status_event BEGIN SELECT RAISE(ABORT,'immutable_run_delivery'); END;
