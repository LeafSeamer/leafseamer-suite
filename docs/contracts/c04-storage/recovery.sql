-- C04恢复事务布局候选，不是生产迁移。每库一个固定scope；外部引用保留完整scope。
-- SQL只验证列关系。正文/摘要、身份、时钟、完整计划和设备证据由可信writer核验。
PRAGMA foreign_keys=ON;
PRAGMA recursive_triggers=ON;

CREATE TABLE storage_scope (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 authority_id TEXT NOT NULL, database_id TEXT NOT NULL,
 format_version TEXT NOT NULL CHECK(format_version='automation-storage/0.1.0-draft.2')
) STRICT;
CREATE TABLE published_version (
 definition_id TEXT NOT NULL, version TEXT NOT NULL,
 scope_id INTEGER NOT NULL DEFAULT 1 REFERENCES storage_scope(singleton),
 artifact_digest TEXT NOT NULL, artifact_body BLOB NOT NULL,
 PRIMARY KEY(definition_id,version)
) STRICT;
CREATE TABLE run (
 run_id TEXT PRIMARY KEY NOT NULL, definition_id TEXT NOT NULL, version TEXT NOT NULL,
 revision TEXT NOT NULL CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 arm_generation TEXT NOT NULL CHECK(length(arm_generation) BETWEEN 1 AND 20 AND arm_generation NOT GLOB '*[^0-9]*' AND (arm_generation='0' OR substr(arm_generation,1,1)!='0') AND instr(arm_generation,char(0))=0),
 lifecycle TEXT NOT NULL CHECK(lifecycle IN ('disarmed','armed','running','paused','completed')),
 dispatch_eligible INTEGER NOT NULL CHECK(dispatch_eligible IN (0,1)),
 active_operation_id TEXT, active_execution_id TEXT, last_commit_id TEXT,
 UNIQUE(run_id,definition_id,version),
 FOREIGN KEY(definition_id,version) REFERENCES published_version(definition_id,version),
 FOREIGN KEY(active_operation_id,run_id) REFERENCES recovery_operation(operation_id,run_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(active_execution_id,run_id) REFERENCES execution(execution_id,run_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(last_commit_id,run_id) REFERENCES transition_commit(commit_id,run_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(dispatch_eligible=0 OR lifecycle IN ('armed','running')),
 CHECK(lifecycle!='completed' OR (active_operation_id IS NULL AND active_execution_id IS NULL AND dispatch_eligible=0))
) STRICT;
CREATE TABLE activation_slot (
 definition_id TEXT PRIMARY KEY NOT NULL, revision TEXT NOT NULL,
 active_run_id TEXT, version TEXT,
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 CHECK((active_run_id IS NULL)=(version IS NULL)),
 FOREIGN KEY(active_run_id,definition_id,version) REFERENCES run(run_id,definition_id,version)
) STRICT;
CREATE TABLE business_state (
 run_id TEXT PRIMARY KEY NOT NULL REFERENCES run(run_id), state_id TEXT NOT NULL,
 revision TEXT NOT NULL, last_commit_id TEXT,
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 FOREIGN KEY(last_commit_id,run_id,state_id,revision) REFERENCES transition_commit(commit_id,run_id,target_state_id,target_state_revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE recovery_preview (
 preview_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES run(run_id),
 run_revision TEXT NOT NULL, slot_revision TEXT NOT NULL, prior_execution_id TEXT,
 preview_digest TEXT NOT NULL, plan_digest TEXT NOT NULL, preview_body BLOB NOT NULL,
 clock_body BLOB NOT NULL, issued_tick TEXT NOT NULL, expires_tick TEXT NOT NULL,
 consumed_operation_id TEXT UNIQUE,
 CHECK(length(run_revision) BETWEEN 1 AND 20 AND run_revision NOT GLOB '*[^0-9]*' AND (run_revision='0' OR substr(run_revision,1,1)!='0') AND instr(run_revision,char(0))=0),
 CHECK(length(slot_revision) BETWEEN 1 AND 20 AND slot_revision NOT GLOB '*[^0-9]*' AND (slot_revision='0' OR substr(slot_revision,1,1)!='0') AND instr(slot_revision,char(0))=0),
 CHECK(length(issued_tick) BETWEEN 1 AND 20 AND issued_tick NOT GLOB '*[^0-9]*' AND (issued_tick='0' OR substr(issued_tick,1,1)!='0') AND instr(issued_tick,char(0))=0),
 CHECK(length(expires_tick) BETWEEN 1 AND 20 AND expires_tick NOT GLOB '*[^0-9]*' AND (expires_tick='0' OR substr(expires_tick,1,1)!='0') AND instr(expires_tick,char(0))=0),
 CHECK((length(issued_tick),issued_tick COLLATE BINARY)<(length(expires_tick),expires_tick COLLATE BINARY)),
 UNIQUE(preview_id,run_id,consumed_operation_id),
 FOREIGN KEY(prior_execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(consumed_operation_id,run_id,preview_id) REFERENCES recovery_operation(operation_id,run_id,preview_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE recovery_operation (
 operation_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES run(run_id),
 preview_id TEXT NOT NULL UNIQUE, execution_id TEXT NOT NULL UNIQUE,
 request_epoch TEXT NOT NULL, actor_identity BLOB NOT NULL, idempotency_key TEXT NOT NULL,
 operation_kind TEXT NOT NULL CHECK(operation_kind='resumeAutomationRun'),
 request_digest TEXT NOT NULL, revision TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('preparing','ready','running','reconciling','paused','indeterminate','completed')),
 mode TEXT NOT NULL CHECK(mode IN ('execute','reconcile_commit')),
 plan_digest TEXT NOT NULL, targets_digest TEXT NOT NULL, targets_body BLOB NOT NULL,
 resolved_latches_body BLOB NOT NULL, start_id TEXT,
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'R2' CHECK(tx_phase='R2'),
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 UNIQUE(request_epoch,actor_identity,operation_kind,idempotency_key),
 UNIQUE(operation_id,run_id), UNIQUE(operation_id,run_id,preview_id), UNIQUE(operation_id,run_id,execution_id), UNIQUE(operation_id,run_id,start_id),
 FOREIGN KEY(tx_id,tx_phase,operation_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id,run_id) REFERENCES recovery_lock(operation_id,run_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(preview_id,run_id,operation_id) REFERENCES recovery_preview(preview_id,run_id,consumed_operation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(execution_id,run_id,operation_id) REFERENCES execution(execution_id,run_id,recovery_operation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(start_id,operation_id,run_id,execution_id) REFERENCES execution_start(start_id,operation_id,run_id,execution_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(state NOT IN ('running','reconciling','completed') OR start_id IS NOT NULL),
 CHECK(state!='reconciling' OR mode='reconcile_commit')
) STRICT;
CREATE TABLE execution (
 execution_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES run(run_id),
 recovery_operation_id TEXT UNIQUE,
 origin_kind TEXT NOT NULL CHECK(origin_kind IN ('trigger','recovery')), trigger_decision_ref_body BLOB,
 arm_generation TEXT NOT NULL,
 binding_digest TEXT NOT NULL, plan_digest TEXT NOT NULL, binding_body BLOB NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('rule','state_machine')),
 source_state_id TEXT, source_state_revision TEXT, target_state_id TEXT,
 state TEXT NOT NULL CHECK(state IN ('prepared','running','paused','succeeded','failed','unknown')),
 start_id TEXT UNIQUE, commit_id TEXT UNIQUE,
 CHECK(length(arm_generation) BETWEEN 1 AND 20 AND arm_generation NOT GLOB '*[^0-9]*' AND (arm_generation='0' OR substr(arm_generation,1,1)!='0') AND instr(arm_generation,char(0))=0),
 CHECK((origin_kind='trigger' AND recovery_operation_id IS NULL AND trigger_decision_ref_body IS NOT NULL) OR (origin_kind='recovery' AND recovery_operation_id IS NOT NULL AND trigger_decision_ref_body IS NULL)),
 CHECK((kind='rule' AND source_state_id IS NULL AND source_state_revision IS NULL AND target_state_id IS NULL) OR (kind='state_machine' AND source_state_id IS NOT NULL AND source_state_revision IS NOT NULL AND target_state_id IS NOT NULL)),
 CHECK(source_state_revision IS NULL OR (length(source_state_revision) BETWEEN 1 AND 20 AND source_state_revision NOT GLOB '*[^0-9]*' AND (source_state_revision='0' OR substr(source_state_revision,1,1)!='0') AND instr(source_state_revision,char(0))=0)),
 CHECK((state='succeeded')=(commit_id IS NOT NULL)),
 CHECK(state!='running' OR origin_kind='trigger' OR start_id IS NOT NULL),
 CHECK(origin_kind='recovery' OR start_id IS NULL),
 UNIQUE(execution_id,run_id), UNIQUE(execution_id,run_id,recovery_operation_id), UNIQUE(execution_id,run_id,start_id), UNIQUE(execution_id,run_id,commit_id),
 FOREIGN KEY(recovery_operation_id,run_id,execution_id) REFERENCES recovery_operation(operation_id,run_id,execution_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(start_id,recovery_operation_id,run_id,execution_id) REFERENCES execution_start(start_id,operation_id,run_id,execution_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(commit_id,run_id,execution_id) REFERENCES transition_commit(commit_id,run_id,execution_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE external_evidence (
 evidence_id TEXT PRIMARY KEY NOT NULL, authority_id TEXT NOT NULL, database_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('preparation','completion','release')),
 object_id TEXT NOT NULL, revision TEXT NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL,
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 UNIQUE(authority_id,database_id,kind,object_id,revision), UNIQUE(evidence_id,kind)
) STRICT;
CREATE TABLE preparation_target (
 operation_id TEXT NOT NULL REFERENCES recovery_operation(operation_id), controller_id TEXT NOT NULL,
 target_digest TEXT NOT NULL, target_body BLOB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','applied','rejected','indeterminate')),
 receipt_id TEXT, receipt_kind TEXT NOT NULL DEFAULT 'preparation' CHECK(receipt_kind='preparation'),
 PRIMARY KEY(operation_id,controller_id),
 CHECK((state='applied')=(receipt_id IS NOT NULL)),
 FOREIGN KEY(receipt_id,receipt_kind) REFERENCES external_evidence(evidence_id,kind)
) STRICT;
CREATE TABLE recovery_lock (
 operation_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL,
 release_id TEXT, release_kind TEXT NOT NULL DEFAULT 'release' CHECK(release_kind='release'),
 UNIQUE(operation_id,run_id),
 FOREIGN KEY(operation_id,run_id) REFERENCES recovery_operation(operation_id,run_id),
 FOREIGN KEY(release_id,release_kind) REFERENCES external_evidence(evidence_id,kind)
) STRICT;
CREATE UNIQUE INDEX one_open_recovery ON recovery_lock(run_id) WHERE release_id IS NULL;
CREATE TABLE pause_latch (
 latch_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES run(run_id),
 reason TEXT NOT NULL, created_revision TEXT NOT NULL, body BLOB NOT NULL, cleared_start_id TEXT,
 CHECK(length(created_revision) BETWEEN 1 AND 20 AND created_revision NOT GLOB '*[^0-9]*' AND (created_revision='0' OR substr(created_revision,1,1)!='0') AND instr(created_revision,char(0))=0),
 FOREIGN KEY(cleared_start_id,run_id) REFERENCES execution_start(start_id,run_id)
) STRICT;
CREATE TABLE transaction_record (
 tx_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES run(run_id),
 phase TEXT NOT NULL CHECK(phase IN ('R2','R3','R4','R5','PLAN','ANCHOR','READY','SUBMISSION','ATTEMPT','ADJUDICATION','SUBMISSION_OBSERVATION','STEP_TERMINAL')),
 business_id TEXT NOT NULL, audit_body BLOB NOT NULL, event_id TEXT NOT NULL UNIQUE,
 UNIQUE(phase,business_id), UNIQUE(tx_id,event_id), UNIQUE(tx_id,phase,business_id,run_id),
 FOREIGN KEY(event_id,tx_id) REFERENCES event_outbox(event_id,tx_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE event_outbox (
 event_id TEXT PRIMARY KEY NOT NULL, tx_id TEXT NOT NULL UNIQUE,
 payload_digest TEXT NOT NULL, payload_body BLOB NOT NULL,
 UNIQUE(event_id,tx_id),
 FOREIGN KEY(tx_id,event_id) REFERENCES transaction_record(tx_id,event_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE execution_start (
 start_id TEXT PRIMARY KEY NOT NULL, operation_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL,
 execution_id TEXT NOT NULL UNIQUE, mode TEXT NOT NULL CHECK(mode IN ('execute','reconcile_commit')),
 run_revision_before TEXT NOT NULL, run_revision_after TEXT NOT NULL,
 slot_revision TEXT NOT NULL, operation_revision TEXT NOT NULL,
 start_body BLOB NOT NULL, start_digest TEXT NOT NULL, tx_id TEXT NOT NULL UNIQUE,
 tx_phase TEXT NOT NULL DEFAULT 'R4' CHECK(tx_phase='R4'),
 CHECK(length(run_revision_before) BETWEEN 1 AND 20 AND run_revision_before NOT GLOB '*[^0-9]*' AND (run_revision_before='0' OR substr(run_revision_before,1,1)!='0') AND instr(run_revision_before,char(0))=0),
 CHECK(length(run_revision_after) BETWEEN 1 AND 20 AND run_revision_after NOT GLOB '*[^0-9]*' AND (run_revision_after='0' OR substr(run_revision_after,1,1)!='0') AND instr(run_revision_after,char(0))=0),
 CHECK(length(slot_revision) BETWEEN 1 AND 20 AND slot_revision NOT GLOB '*[^0-9]*' AND (slot_revision='0' OR substr(slot_revision,1,1)!='0') AND instr(slot_revision,char(0))=0),
 CHECK(length(operation_revision) BETWEEN 1 AND 20 AND operation_revision NOT GLOB '*[^0-9]*' AND (operation_revision='0' OR substr(operation_revision,1,1)!='0') AND instr(operation_revision,char(0))=0),
 CHECK((length(run_revision_before),run_revision_before COLLATE BINARY)<(length(run_revision_after),run_revision_after COLLATE BINARY)),
 UNIQUE(start_id,run_id), UNIQUE(start_id,operation_id,run_id,execution_id),
 FOREIGN KEY(operation_id,run_id,execution_id) REFERENCES recovery_operation(operation_id,run_id,execution_id),
 FOREIGN KEY(operation_id,run_id,start_id) REFERENCES recovery_operation(operation_id,run_id,start_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(execution_id,run_id,start_id) REFERENCES execution(execution_id,run_id,start_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tx_id,tx_phase,start_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;
CREATE TABLE transition_commit (
 commit_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL, execution_id TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('rule','state_machine')),
 source_state_id TEXT, source_state_revision TEXT, target_state_id TEXT, target_state_revision TEXT,
 evidence_set_body BLOB NOT NULL, commit_body BLOB NOT NULL, commit_digest TEXT NOT NULL,
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'R5' CHECK(tx_phase='R5'),
 CHECK((kind='rule' AND source_state_id IS NULL AND source_state_revision IS NULL AND target_state_id IS NULL AND target_state_revision IS NULL) OR (kind='state_machine' AND source_state_id IS NOT NULL AND source_state_revision IS NOT NULL AND target_state_id IS NOT NULL AND target_state_revision IS NOT NULL)),
 UNIQUE(commit_id,run_id), UNIQUE(commit_id,run_id,execution_id), UNIQUE(commit_id,run_id,target_state_id,target_state_revision),
 CHECK(source_state_revision IS NULL OR (length(source_state_revision) BETWEEN 1 AND 20 AND source_state_revision NOT GLOB '*[^0-9]*' AND (source_state_revision='0' OR substr(source_state_revision,1,1)!='0') AND instr(source_state_revision,char(0))=0)),
 CHECK(target_state_revision IS NULL OR (length(target_state_revision) BETWEEN 1 AND 20 AND target_state_revision NOT GLOB '*[^0-9]*' AND (target_state_revision='0' OR substr(target_state_revision,1,1)!='0') AND instr(target_state_revision,char(0))=0)),
 FOREIGN KEY(execution_id,run_id,commit_id) REFERENCES execution(execution_id,run_id,commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tx_id,tx_phase,commit_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;

-- 不可变内容。全部主键和scope都属于受保护身份，禁止REPLACE旁路删除墓碑。
CREATE TRIGGER scope_update BEFORE UPDATE ON storage_scope BEGIN SELECT RAISE(ABORT,'immutable_scope'); END;
CREATE TRIGGER scope_delete BEFORE DELETE ON storage_scope BEGIN SELECT RAISE(ABORT,'retain_scope'); END;
CREATE TRIGGER version_update BEFORE UPDATE ON published_version BEGIN SELECT RAISE(ABORT,'immutable_artifact'); END;
CREATE TRIGGER version_delete BEFORE DELETE ON published_version BEGIN SELECT RAISE(ABORT,'retain_artifact'); END;
CREATE TRIGGER preview_update BEFORE UPDATE ON recovery_preview
WHEN NEW.preview_id IS NOT OLD.preview_id OR NEW.run_id IS NOT OLD.run_id OR NEW.run_revision IS NOT OLD.run_revision OR NEW.slot_revision IS NOT OLD.slot_revision OR NEW.prior_execution_id IS NOT OLD.prior_execution_id OR NEW.preview_digest IS NOT OLD.preview_digest OR NEW.plan_digest IS NOT OLD.plan_digest OR NEW.preview_body IS NOT OLD.preview_body OR NEW.clock_body IS NOT OLD.clock_body OR NEW.issued_tick IS NOT OLD.issued_tick OR NEW.expires_tick IS NOT OLD.expires_tick OR (OLD.consumed_operation_id IS NOT NULL AND NEW.consumed_operation_id IS NOT OLD.consumed_operation_id)
BEGIN SELECT RAISE(ABORT,'immutable_preview'); END;
CREATE TRIGGER preview_delete BEFORE DELETE ON recovery_preview BEGIN SELECT RAISE(ABORT,'retain_preview'); END;
CREATE TRIGGER run_update BEFORE UPDATE ON run
WHEN NEW.run_id IS NOT OLD.run_id OR NEW.definition_id IS NOT OLD.definition_id OR NEW.version IS NOT OLD.version OR (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY) OR (length(NEW.arm_generation),NEW.arm_generation COLLATE BINARY)<(length(OLD.arm_generation),OLD.arm_generation COLLATE BINARY) OR OLD.lifecycle='completed'
BEGIN SELECT RAISE(ABORT,'run_cas_or_identity'); END;
CREATE TRIGGER run_delete BEFORE DELETE ON run BEGIN SELECT RAISE(ABORT,'retain_run'); END;
CREATE TRIGGER slot_update BEFORE UPDATE ON activation_slot
WHEN NEW.definition_id IS NOT OLD.definition_id OR (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY) OR (OLD.active_run_id IS NOT NULL AND NEW.active_run_id IS NOT OLD.active_run_id AND NOT EXISTS(SELECT 1 FROM run WHERE run_id=OLD.active_run_id AND lifecycle='completed'))
BEGIN SELECT RAISE(ABORT,'slot_owned'); END;
CREATE TRIGGER slot_delete BEFORE DELETE ON activation_slot BEGIN SELECT RAISE(ABORT,'retain_slot'); END;
CREATE TRIGGER state_update BEFORE UPDATE ON business_state
WHEN NEW.run_id IS NOT OLD.run_id OR (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY) OR NEW.last_commit_id IS NULL OR NEW.last_commit_id IS OLD.last_commit_id
BEGIN SELECT RAISE(ABORT,'state_commit_required'); END;
CREATE TRIGGER state_delete BEFORE DELETE ON business_state BEGIN SELECT RAISE(ABORT,'retain_state'); END;
CREATE TRIGGER operation_update BEFORE UPDATE ON recovery_operation
WHEN NEW.operation_id IS NOT OLD.operation_id OR NEW.run_id IS NOT OLD.run_id OR NEW.preview_id IS NOT OLD.preview_id OR NEW.execution_id IS NOT OLD.execution_id OR NEW.request_epoch IS NOT OLD.request_epoch OR NEW.actor_identity IS NOT OLD.actor_identity OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.operation_kind IS NOT OLD.operation_kind OR NEW.request_digest IS NOT OLD.request_digest OR NEW.mode IS NOT OLD.mode OR NEW.plan_digest IS NOT OLD.plan_digest OR NEW.targets_digest IS NOT OLD.targets_digest OR NEW.targets_body IS NOT OLD.targets_body OR NEW.resolved_latches_body IS NOT OLD.resolved_latches_body OR NEW.tx_id IS NOT OLD.tx_id OR NEW.tx_phase IS NOT OLD.tx_phase OR (OLD.start_id IS NOT NULL AND NEW.start_id IS NOT OLD.start_id) OR (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY)
 OR NOT ((OLD.state='preparing' AND NEW.state IN ('ready','paused','indeterminate')) OR (OLD.state='ready' AND NEW.state IN ('running','reconciling','paused','indeterminate')) OR (OLD.state IN ('running','reconciling') AND NEW.state IN ('completed','paused','indeterminate')))
BEGIN SELECT RAISE(ABORT,'operation_transition'); END;
CREATE TRIGGER operation_delete BEFORE DELETE ON recovery_operation BEGIN SELECT RAISE(ABORT,'retain_operation'); END;
CREATE TRIGGER execution_update BEFORE UPDATE ON execution
WHEN NEW.execution_id IS NOT OLD.execution_id OR NEW.run_id IS NOT OLD.run_id OR NEW.recovery_operation_id IS NOT OLD.recovery_operation_id OR NEW.origin_kind IS NOT OLD.origin_kind OR NEW.trigger_decision_ref_body IS NOT OLD.trigger_decision_ref_body OR NEW.arm_generation IS NOT OLD.arm_generation OR NEW.binding_digest IS NOT OLD.binding_digest OR NEW.plan_digest IS NOT OLD.plan_digest OR NEW.binding_body IS NOT OLD.binding_body OR NEW.kind IS NOT OLD.kind OR NEW.source_state_id IS NOT OLD.source_state_id OR NEW.source_state_revision IS NOT OLD.source_state_revision OR NEW.target_state_id IS NOT OLD.target_state_id OR (OLD.start_id IS NOT NULL AND NEW.start_id IS NOT OLD.start_id) OR (OLD.commit_id IS NOT NULL AND NEW.commit_id IS NOT OLD.commit_id)
 OR NOT ((OLD.state='prepared' AND NEW.state IN ('running','paused','failed','unknown')) OR (OLD.state='running' AND NEW.state IN ('succeeded','paused','failed','unknown')))
BEGIN SELECT RAISE(ABORT,'execution_transition'); END;
CREATE TRIGGER execution_delete BEFORE DELETE ON execution BEGIN SELECT RAISE(ABORT,'retain_execution'); END;
CREATE TRIGGER evidence_update BEFORE UPDATE ON external_evidence BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
CREATE TRIGGER evidence_delete BEFORE DELETE ON external_evidence BEGIN SELECT RAISE(ABORT,'retain_evidence'); END;
CREATE TRIGGER target_update BEFORE UPDATE ON preparation_target
WHEN NEW.operation_id IS NOT OLD.operation_id OR NEW.controller_id IS NOT OLD.controller_id OR NEW.target_digest IS NOT OLD.target_digest OR NEW.target_body IS NOT OLD.target_body OR NEW.receipt_kind IS NOT OLD.receipt_kind OR OLD.state!='pending'
BEGIN SELECT RAISE(ABORT,'target_transition'); END;
CREATE TRIGGER target_insert BEFORE INSERT ON preparation_target
WHEN (SELECT state FROM recovery_operation WHERE operation_id=NEW.operation_id)!='preparing'
BEGIN SELECT RAISE(ABORT,'targets_frozen'); END;
CREATE TRIGGER target_delete BEFORE DELETE ON preparation_target BEGIN SELECT RAISE(ABORT,'retain_target'); END;
CREATE TRIGGER lock_update BEFORE UPDATE ON recovery_lock
WHEN NEW.operation_id IS NOT OLD.operation_id OR NEW.run_id IS NOT OLD.run_id OR NEW.release_kind IS NOT OLD.release_kind OR OLD.release_id IS NOT NULL OR NEW.release_id IS NULL
BEGIN SELECT RAISE(ABORT,'lock_release_once'); END;
CREATE TRIGGER lock_delete BEFORE DELETE ON recovery_lock BEGIN SELECT RAISE(ABORT,'retain_lock'); END;
CREATE TRIGGER latch_update BEFORE UPDATE ON pause_latch
WHEN NEW.latch_id IS NOT OLD.latch_id OR NEW.run_id IS NOT OLD.run_id OR NEW.reason IS NOT OLD.reason OR NEW.created_revision IS NOT OLD.created_revision OR NEW.body IS NOT OLD.body OR OLD.cleared_start_id IS NOT NULL OR NEW.cleared_start_id IS NULL
BEGIN SELECT RAISE(ABORT,'latch_clear_once'); END;
CREATE TRIGGER latch_delete BEFORE DELETE ON pause_latch BEGIN SELECT RAISE(ABORT,'retain_latch'); END;
CREATE TRIGGER tx_update BEFORE UPDATE ON transaction_record BEGIN SELECT RAISE(ABORT,'immutable_transaction'); END;
CREATE TRIGGER tx_delete BEFORE DELETE ON transaction_record BEGIN SELECT RAISE(ABORT,'retain_transaction'); END;
CREATE TRIGGER event_update BEFORE UPDATE ON event_outbox BEGIN SELECT RAISE(ABORT,'immutable_event'); END;
CREATE TRIGGER event_delete BEFORE DELETE ON event_outbox BEGIN SELECT RAISE(ABORT,'retain_event'); END;
CREATE TRIGGER start_update BEFORE UPDATE ON execution_start BEGIN SELECT RAISE(ABORT,'immutable_start'); END;
CREATE TRIGGER start_delete BEFORE DELETE ON execution_start BEGIN SELECT RAISE(ABORT,'retain_start'); END;
CREATE TRIGGER commit_update BEFORE UPDATE ON transition_commit BEGIN SELECT RAISE(ABORT,'immutable_commit'); END;
CREATE TRIGGER commit_delete BEFORE DELETE ON transition_commit BEGIN SELECT RAISE(ABORT,'retain_commit'); END;

-- 只供恢复分类。此视图不能授予派发资格，也不会生成设备写任务。
CREATE VIEW recovery_inventory AS
SELECT o.operation_id,o.run_id,o.execution_id,o.state,o.mode,p.preview_id,
 l.release_id,s.start_id,c.commit_id,
 CASE WHEN c.commit_id IS NOT NULL THEN 'lookup_committed'
      WHEN s.start_id IS NOT NULL THEN 'started_protect_and_reconcile'
      WHEN o.state IN ('paused','indeterminate') THEN 'protected_reconcile_targets'
      ELSE 'prepared_protect_and_reconcile' END AS restart_action
FROM recovery_operation o JOIN recovery_preview p ON p.preview_id=o.preview_id
JOIN recovery_lock l ON l.operation_id=o.operation_id
LEFT JOIN execution_start s ON s.operation_id=o.operation_id
LEFT JOIN transition_commit c ON c.execution_id=o.execution_id;
