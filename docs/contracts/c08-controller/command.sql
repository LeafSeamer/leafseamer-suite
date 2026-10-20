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
 resolved_outcome TEXT CHECK(resolved_outcome IN ('succeeded','failed','cancelled','unknown')),
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
 resolved_outcome TEXT NOT NULL CHECK(resolved_outcome IN ('succeeded','failed','cancelled','unknown')),
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
