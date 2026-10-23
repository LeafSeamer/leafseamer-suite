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
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
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
  THEN RAISE(ABORT,'cancel_resource_coverage_not_merged') END;
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
-- 迁移阻断项：旧RUN结果及资源释放尚无取消coverage/FK，不能把新水位当完整覆盖。
CREATE TRIGGER ci_run_coverage_pending BEFORE INSERT ON ce_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission p JOIN ce_selector s
  ON (p.origin_authority,p.origin_database,p.run_id)=(s.origin_authority,s.origin_database,s.run_id)
  WHERE s.fence_id=NEW.fence_id AND p.origin='automation' AND p.generation<=s.generation)
  THEN RAISE(ABORT,'cancel_run_coverage_not_merged') END;
END;
CREATE TRIGGER ci_release_coverage_pending BEFORE INSERT ON cr_release BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission p JOIN cv_cancel c USING(cancellation_id)
  WHERE c.command_id=NEW.command_id) THEN RAISE(ABORT,'cancel_resource_coverage_not_merged') END;
END;
