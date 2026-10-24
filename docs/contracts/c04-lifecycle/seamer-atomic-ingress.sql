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
 FOREIGN KEY(active_operation_id,run_id) REFERENCES lifecycle_operation_identity(operation_id,run_id) DEFERRABLE INITIALLY DEFERRED,
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
 FOREIGN KEY(operation_id) REFERENCES pr_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id) REFERENCES recovery_budget_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,
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
 typed_source_id TEXT REFERENCES typed_execution_source(execution_id) DEFERRABLE INITIALLY DEFERRED,
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
 UNIQUE(operation_id,controller_id,receipt_id),
 FOREIGN KEY(operation_id,controller_id) REFERENCES p1_preparation(recovery_operation_id,recovery_controller_id) DEFERRABLE INITIALLY DEFERRED,
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
 run_revision_before TEXT NOT NULL,run_revision_after TEXT NOT NULL,slot_revision TEXT NOT NULL,
 FOREIGN KEY(commit_id) REFERENCES flow_commit_seal(commit_id) DEFERRABLE INITIALLY DEFERRED,
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

-- automation-storage/0.1.0-draft.2的执行层，加载在recovery.sql之后；仅设计候选。
-- 完整BODY、Schema/JCS、当前授权/时钟/预算和远端证据必须由可信writer验证。
CREATE TABLE execution_plan_set (
 execution_id TEXT PRIMARY KEY NOT NULL REFERENCES execution(execution_id), run_id TEXT NOT NULL,
 expected_steps INTEGER NOT NULL CHECK(expected_steps BETWEEN 0 AND 4096),
 plan_digest TEXT NOT NULL, plan_body BLOB NOT NULL, sealed INTEGER NOT NULL CHECK(sealed IN (0,1)),
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'PLAN' CHECK(tx_phase='PLAN'),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(tx_id,tx_phase,execution_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;
CREATE TABLE execution_step_plan (
 execution_id TEXT NOT NULL REFERENCES execution_plan_set(execution_id), step_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('action','delay','retain_success','reconcile_commit')),
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 0 AND 4095), required INTEGER NOT NULL CHECK(required IN (0,1)),
 plan_digest TEXT NOT NULL, plan_body BLOB NOT NULL,
 PRIMARY KEY(execution_id,step_id), UNIQUE(execution_id,step_id,kind), UNIQUE(execution_id,step_id,plan_digest)
) STRICT;
CREATE TABLE execution_anchor (
 anchor_id TEXT PRIMARY KEY NOT NULL, execution_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL,
 origin_kind TEXT NOT NULL CHECK(origin_kind IN ('trigger','recovery')),
 start_id TEXT, trigger_decision_ref_body BLOB,
 clock_body BLOB NOT NULL, tick_ns TEXT NOT NULL, anchor_digest TEXT NOT NULL, anchor_body BLOB NOT NULL,
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'ANCHOR' CHECK(tx_phase='ANCHOR'),
 CHECK((origin_kind='trigger' AND start_id IS NULL AND trigger_decision_ref_body IS NOT NULL) OR (origin_kind='recovery' AND start_id IS NOT NULL AND trigger_decision_ref_body IS NULL)),
 CHECK(length(tick_ns) BETWEEN 1 AND 20 AND tick_ns NOT GLOB '*[^0-9]*' AND (tick_ns='0' OR substr(tick_ns,1,1)!='0') AND instr(tick_ns,char(0))=0),
 UNIQUE(anchor_id,execution_id,clock_body),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(start_id,run_id) REFERENCES execution_start(start_id,run_id),
 FOREIGN KEY(tx_id,tx_phase,anchor_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;
CREATE TABLE step_ready (
 ready_id TEXT PRIMARY KEY NOT NULL, execution_id TEXT NOT NULL, step_id TEXT NOT NULL, run_id TEXT NOT NULL,
 plan_digest TEXT NOT NULL, anchor_id TEXT NOT NULL, clock_body BLOB NOT NULL, tick_ns TEXT NOT NULL,
 dependencies_digest TEXT NOT NULL, dependencies_body BLOB NOT NULL, ready_digest TEXT NOT NULL, ready_body BLOB NOT NULL,
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'READY' CHECK(tx_phase='READY'),
 CHECK(length(tick_ns) BETWEEN 1 AND 20 AND tick_ns NOT GLOB '*[^0-9]*' AND (tick_ns='0' OR substr(tick_ns,1,1)!='0') AND instr(tick_ns,char(0))=0),
 UNIQUE(execution_id,step_id), UNIQUE(ready_id,execution_id,step_id),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(execution_id,step_id,plan_digest) REFERENCES execution_step_plan(execution_id,step_id,plan_digest),
 FOREIGN KEY(anchor_id,execution_id,clock_body) REFERENCES execution_anchor(anchor_id,execution_id,clock_body),
 FOREIGN KEY(execution_id,step_id,ready_id) REFERENCES step_state(execution_id,step_id,ready_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tx_id,tx_phase,ready_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;
CREATE TABLE step_state (
 execution_id TEXT NOT NULL, step_id TEXT NOT NULL, revision TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('waiting','ready','submission_pending','accepted','awaiting_evidence','finished','retained','cancelled','indeterminate')),
 outcome TEXT NOT NULL CHECK(outcome IN ('pending','succeeded','failed','unknown','blocked','expired','cancelled')),
 ready_id TEXT, submission_id TEXT UNIQUE, terminal_id TEXT UNIQUE,
 PRIMARY KEY(execution_id,step_id), UNIQUE(execution_id,step_id,ready_id), UNIQUE(execution_id,step_id,submission_id), UNIQUE(execution_id,step_id,terminal_id,outcome),
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 CHECK((state IN ('finished','retained','cancelled','indeterminate'))=(outcome!='pending')),
 CHECK((terminal_id IS NOT NULL)=(outcome!='pending')),
 CHECK(state='waiting' OR state IN ('cancelled','indeterminate','finished') OR ready_id IS NOT NULL),
 CHECK(state NOT IN ('submission_pending','accepted','awaiting_evidence') OR submission_id IS NOT NULL),
 CHECK(state!='retained' OR outcome='succeeded'), CHECK(state!='cancelled' OR outcome='cancelled'),
 FOREIGN KEY(execution_id,step_id) REFERENCES execution_step_plan(execution_id,step_id),
 FOREIGN KEY(ready_id,execution_id,step_id) REFERENCES step_ready(ready_id,execution_id,step_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(submission_id,execution_id,step_id) REFERENCES command_submission(submission_id,execution_id,step_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(terminal_id,execution_id,step_id,outcome) REFERENCES step_terminal(terminal_id,execution_id,step_id,outcome) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE command_submission (
 submission_id TEXT PRIMARY KEY NOT NULL, execution_id TEXT NOT NULL, step_id TEXT NOT NULL, run_id TEXT NOT NULL,
 step_kind TEXT NOT NULL DEFAULT 'action' CHECK(step_kind='action'),
 target_authority TEXT NOT NULL, target_database TEXT NOT NULL, issuer_epoch TEXT NOT NULL,request_key_body BLOB NOT NULL CHECK(json_valid(request_key_body)), issuer_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 request_epoch TEXT NOT NULL, operation_id TEXT NOT NULL CHECK(operation_id='createCommand'), idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL, request_body BLOB NOT NULL, parameters_ref_body BLOB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('planned','attempt_recorded','indeterminate','accepted','rejected')),
 attempt_id TEXT UNIQUE, adjudication_id TEXT UNIQUE,
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'SUBMISSION' CHECK(tx_phase='SUBMISSION'),
 UNIQUE(execution_id,step_id), UNIQUE(submission_id,execution_id,step_id), UNIQUE(submission_id,attempt_id), UNIQUE(submission_id,run_id),
 UNIQUE(target_authority,target_database,issuer_id,issuer_epoch,principal_id,request_epoch,operation_id,idempotency_key),
 UNIQUE(submission_id,target_authority,target_database,request_digest), UNIQUE(submission_id,adjudication_id,state),
 CHECK((state='planned')=(attempt_id IS NULL)),
 CHECK((state IN ('accepted','rejected'))=(adjudication_id IS NOT NULL)),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(execution_id,step_id,step_kind) REFERENCES execution_step_plan(execution_id,step_id,kind),
 FOREIGN KEY(execution_id,step_id,submission_id) REFERENCES step_state(execution_id,step_id,submission_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(attempt_id,submission_id) REFERENCES submission_attempt(attempt_id,submission_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(adjudication_id,submission_id,state) REFERENCES submission_adjudication(adjudication_id,submission_id,outcome) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tx_id,tx_phase,submission_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;
CREATE TABLE submission_attempt (
 attempt_id TEXT PRIMARY KEY NOT NULL, submission_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL,
 runtime_binding_ref_body BLOB NOT NULL, clock_body BLOB NOT NULL, tick_ns TEXT NOT NULL,
 attempt_body BLOB NOT NULL, tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'ATTEMPT' CHECK(tx_phase='ATTEMPT'),
 CHECK(length(tick_ns) BETWEEN 1 AND 20 AND tick_ns NOT GLOB '*[^0-9]*' AND (tick_ns='0' OR substr(tick_ns,1,1)!='0') AND instr(tick_ns,char(0))=0),
 UNIQUE(attempt_id,submission_id),
 FOREIGN KEY(submission_id,run_id) REFERENCES command_submission(submission_id,run_id),
 FOREIGN KEY(submission_id,attempt_id) REFERENCES command_submission(submission_id,attempt_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tx_id,tx_phase,attempt_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;
CREATE TABLE submission_adjudication (
 adjudication_id TEXT PRIMARY KEY NOT NULL, submission_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL,
 target_authority TEXT NOT NULL, target_database TEXT NOT NULL, request_digest TEXT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('accepted','rejected')), command_ref_body BLOB,
 receipt_ref_body BLOB NOT NULL, receipt_body BLOB NOT NULL,
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'ADJUDICATION' CHECK(tx_phase='ADJUDICATION'),
 CHECK((outcome='accepted')=(command_ref_body IS NOT NULL)),
 UNIQUE(adjudication_id,submission_id,outcome),
 FOREIGN KEY(submission_id,run_id) REFERENCES command_submission(submission_id,run_id),
 FOREIGN KEY(submission_id,target_authority,target_database,request_digest) REFERENCES command_submission(submission_id,target_authority,target_database,request_digest),
 FOREIGN KEY(submission_id,adjudication_id,outcome) REFERENCES command_submission(submission_id,adjudication_id,state) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tx_id,tx_phase,adjudication_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;
CREATE TABLE step_terminal (
 terminal_id TEXT PRIMARY KEY NOT NULL, execution_id TEXT NOT NULL, step_id TEXT NOT NULL, run_id TEXT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('succeeded','failed','unknown','blocked','expired','cancelled')),
 evidence_body BLOB NOT NULL, result_ref_body BLOB,
 protection_plan_id TEXT UNIQUE REFERENCES sf_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'STEP_TERMINAL' CHECK(tx_phase='STEP_TERMINAL'),
 UNIQUE(execution_id,step_id), UNIQUE(terminal_id,execution_id,step_id,outcome),
 CHECK(result_ref_body IS NULL OR outcome='succeeded'),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(execution_id,step_id,terminal_id,outcome) REFERENCES step_state(execution_id,step_id,terminal_id,outcome) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tx_id,tx_phase,terminal_id,run_id) REFERENCES transaction_record(tx_id,phase,business_id,run_id)
) STRICT;

CREATE TRIGGER plan_set_insert BEFORE INSERT ON execution_plan_set WHEN NEW.sealed!=0 OR NOT EXISTS(SELECT 1 FROM execution WHERE execution_id=NEW.execution_id AND plan_digest=NEW.plan_digest)
BEGIN SELECT RAISE(ABORT,'plan_requires_seal'); END;
CREATE TRIGGER plan_set_update BEFORE UPDATE ON execution_plan_set
WHEN OLD.sealed!=0 OR NEW.sealed!=1 OR NEW.execution_id IS NOT OLD.execution_id OR NEW.run_id IS NOT OLD.run_id OR NEW.expected_steps IS NOT OLD.expected_steps OR NEW.plan_digest IS NOT OLD.plan_digest OR NEW.plan_body IS NOT OLD.plan_body OR NEW.tx_id IS NOT OLD.tx_id OR NEW.tx_phase IS NOT OLD.tx_phase
 OR (SELECT COUNT(*) FROM execution_step_plan WHERE execution_id=OLD.execution_id)!=NEW.expected_steps
 OR (SELECT COUNT(*) FROM step_state WHERE execution_id=OLD.execution_id)!=NEW.expected_steps
 OR (EXISTS(SELECT 1 FROM execution e JOIN recovery_operation o ON o.operation_id=e.recovery_operation_id WHERE e.execution_id=NEW.execution_id AND o.mode='reconcile_commit') AND EXISTS(SELECT 1 FROM execution_step_plan WHERE execution_id=NEW.execution_id AND kind='action'))
BEGIN SELECT RAISE(ABORT,'plan_seal_coverage'); END;
CREATE TRIGGER plan_set_delete BEFORE DELETE ON execution_plan_set BEGIN SELECT RAISE(ABORT,'retain_plan'); END;
CREATE TRIGGER start_requires_plan BEFORE INSERT ON execution_start
WHEN NOT EXISTS(SELECT 1 FROM execution_plan_set WHERE execution_id=NEW.execution_id AND sealed=1)
BEGIN SELECT RAISE(ABORT,'start_plan_unsealed'); END;
CREATE TRIGGER running_requires_plan BEFORE UPDATE ON execution
WHEN NEW.state='running' AND NOT EXISTS(SELECT 1 FROM execution_plan_set WHERE execution_id=NEW.execution_id AND sealed=1)
BEGIN SELECT RAISE(ABORT,'running_plan_unsealed'); END;
CREATE TRIGGER step_plan_insert BEFORE INSERT ON execution_step_plan
WHEN COALESCE((SELECT sealed FROM execution_plan_set WHERE execution_id=NEW.execution_id),1)!=0
BEGIN SELECT RAISE(ABORT,'plan_sealed'); END;
CREATE TRIGGER step_plan_update BEFORE UPDATE ON execution_step_plan BEGIN SELECT RAISE(ABORT,'immutable_step_plan'); END;
CREATE TRIGGER step_plan_delete BEFORE DELETE ON execution_step_plan BEGIN SELECT RAISE(ABORT,'retain_step_plan'); END;
CREATE TRIGGER anchor_insert BEFORE INSERT ON execution_anchor
WHEN NOT EXISTS(SELECT 1 FROM execution e JOIN execution_plan_set p USING(execution_id) WHERE e.execution_id=NEW.execution_id AND p.sealed=1 AND e.state='running' AND e.origin_kind=NEW.origin_kind AND e.start_id IS NEW.start_id AND e.trigger_decision_ref_body IS NEW.trigger_decision_ref_body)
BEGIN SELECT RAISE(ABORT,'anchor_origin'); END;
CREATE TRIGGER anchor_update BEFORE UPDATE ON execution_anchor BEGIN SELECT RAISE(ABORT,'immutable_anchor'); END;
CREATE TRIGGER anchor_delete BEFORE DELETE ON execution_anchor BEGIN SELECT RAISE(ABORT,'retain_anchor'); END;
CREATE TRIGGER ready_insert BEFORE INSERT ON step_ready
WHEN EXISTS(SELECT 1 FROM execution_anchor a WHERE a.anchor_id=NEW.anchor_id AND (length(NEW.tick_ns),NEW.tick_ns COLLATE BINARY)<(length(a.tick_ns),a.tick_ns COLLATE BINARY))
BEGIN SELECT RAISE(ABORT,'ready_before_anchor'); END;
CREATE TRIGGER ready_update BEFORE UPDATE ON step_ready BEGIN SELECT RAISE(ABORT,'immutable_ready'); END;
CREATE TRIGGER ready_delete BEFORE DELETE ON step_ready BEGIN SELECT RAISE(ABORT,'retain_ready'); END;
CREATE TRIGGER step_state_insert BEFORE INSERT ON step_state
WHEN NEW.state!='waiting' OR NEW.outcome!='pending' OR NEW.ready_id IS NOT NULL OR NEW.submission_id IS NOT NULL OR NEW.terminal_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'step_initial_state'); END;
CREATE TRIGGER step_acceptance_binding BEFORE UPDATE ON step_state
WHEN NEW.state IN ('accepted','awaiting_evidence') AND NOT EXISTS(
 SELECT 1 FROM command_submission s WHERE s.submission_id=NEW.submission_id
 AND s.execution_id=NEW.execution_id AND s.step_id=NEW.step_id AND s.state='accepted')
BEGIN SELECT RAISE(ABORT,'step_not_accepted'); END;
CREATE TRIGGER step_state_update BEFORE UPDATE ON step_state
WHEN NEW.execution_id IS NOT OLD.execution_id OR NEW.step_id IS NOT OLD.step_id
 OR (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY)
 OR (OLD.ready_id IS NOT NULL AND NEW.ready_id IS NOT OLD.ready_id)
 OR (OLD.submission_id IS NOT NULL AND NEW.submission_id IS NOT OLD.submission_id)
 OR OLD.outcome!='pending'
 OR NOT ((OLD.state='waiting' AND NEW.state IN ('ready','finished','retained','cancelled','indeterminate'))
      OR (OLD.state='ready' AND NEW.state IN ('submission_pending','finished','retained','cancelled','indeterminate'))
      OR (OLD.state='submission_pending' AND NEW.state IN ('accepted','finished','cancelled','indeterminate'))
      OR (OLD.state='accepted' AND NEW.state IN ('awaiting_evidence','finished','cancelled','indeterminate'))
      OR (OLD.state='awaiting_evidence' AND NEW.state IN ('finished','cancelled','indeterminate')))
BEGIN SELECT RAISE(ABORT,'step_transition'); END;
CREATE TRIGGER step_state_delete BEFORE DELETE ON step_state BEGIN SELECT RAISE(ABORT,'retain_step'); END;
CREATE TRIGGER submission_insert BEFORE INSERT ON command_submission
WHEN NEW.state!='planned' OR NEW.attempt_id IS NOT NULL OR NEW.adjudication_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'submission_initial_state'); END;
CREATE TRIGGER submission_update BEFORE UPDATE ON command_submission
WHEN NEW.submission_id IS NOT OLD.submission_id OR NEW.execution_id IS NOT OLD.execution_id OR NEW.step_id IS NOT OLD.step_id OR NEW.run_id IS NOT OLD.run_id OR NEW.step_kind IS NOT OLD.step_kind
 OR NEW.target_authority IS NOT OLD.target_authority OR NEW.target_database IS NOT OLD.target_database OR NEW.issuer_id IS NOT OLD.issuer_id OR NEW.principal_id IS NOT OLD.principal_id OR NEW.request_epoch IS NOT OLD.request_epoch OR NEW.operation_id IS NOT OLD.operation_id OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.request_digest IS NOT OLD.request_digest OR NEW.request_body IS NOT OLD.request_body OR NEW.parameters_ref_body IS NOT OLD.parameters_ref_body OR NEW.tx_id IS NOT OLD.tx_id OR NEW.tx_phase IS NOT OLD.tx_phase
 OR (OLD.attempt_id IS NOT NULL AND NEW.attempt_id IS NOT OLD.attempt_id)
 OR NOT ((OLD.state='planned' AND NEW.state='attempt_recorded') OR (OLD.state IN ('attempt_recorded','indeterminate') AND NEW.state IN ('indeterminate','accepted','rejected')))
BEGIN SELECT RAISE(ABORT,'submission_transition'); END;
CREATE TRIGGER submission_delete BEFORE DELETE ON command_submission BEGIN SELECT RAISE(ABORT,'retain_submission'); END;
CREATE TRIGGER attempt_binding BEFORE INSERT ON submission_attempt
WHEN NOT EXISTS(SELECT 1 FROM command_submission s JOIN step_ready r USING(execution_id,step_id)
 WHERE s.submission_id=NEW.submission_id AND s.run_id=NEW.run_id AND r.clock_body=NEW.clock_body
 AND (length(NEW.tick_ns),NEW.tick_ns COLLATE BINARY)>=(length(r.tick_ns),r.tick_ns COLLATE BINARY))
BEGIN SELECT RAISE(ABORT,'attempt_ready_binding'); END;
CREATE TRIGGER attempt_update BEFORE UPDATE ON submission_attempt BEGIN SELECT RAISE(ABORT,'immutable_attempt'); END;
CREATE TRIGGER attempt_delete BEFORE DELETE ON submission_attempt BEGIN SELECT RAISE(ABORT,'retain_attempt'); END;
CREATE TRIGGER adjudication_update BEFORE UPDATE ON submission_adjudication BEGIN SELECT RAISE(ABORT,'immutable_adjudication'); END;
CREATE TRIGGER adjudication_delete BEFORE DELETE ON submission_adjudication BEGIN SELECT RAISE(ABORT,'retain_adjudication'); END;
CREATE TRIGGER terminal_success_binding BEFORE INSERT ON step_terminal
WHEN NEW.outcome='succeeded' AND EXISTS(SELECT 1 FROM execution_step_plan WHERE execution_id=NEW.execution_id AND step_id=NEW.step_id AND kind='action')
 AND NOT EXISTS(SELECT 1 FROM command_submission WHERE execution_id=NEW.execution_id AND step_id=NEW.step_id AND state='accepted')
BEGIN SELECT RAISE(ABORT,'action_not_accepted'); END;
CREATE TRIGGER step_terminal_update BEFORE UPDATE ON step_terminal BEGIN SELECT RAISE(ABORT,'immutable_step_terminal'); END;
CREATE TRIGGER step_terminal_delete BEFORE DELETE ON step_terminal BEGIN SELECT RAISE(ABORT,'retain_step_terminal'); END;

CREATE TRIGGER commit_requires_completed_steps BEFORE INSERT ON transition_commit
WHEN NOT EXISTS(SELECT 1 FROM execution_plan_set WHERE execution_id=NEW.execution_id AND sealed=1)
 OR EXISTS(SELECT 1 FROM execution_step_plan p JOIN step_state s USING(execution_id,step_id) WHERE p.execution_id=NEW.execution_id AND (s.outcome NOT IN ('succeeded','failed') OR (p.required=1 AND s.outcome!='succeeded')))
BEGIN SELECT RAISE(ABORT,'steps_not_committable'); END;

CREATE VIEW submission_recovery AS
SELECT s.submission_id,s.execution_id,s.step_id,s.state,a.attempt_id,j.adjudication_id,j.command_ref_body,
 CASE WHEN s.state='planned' THEN 'fresh_gates_required'
      WHEN s.state='accepted' THEN 'observe_original_command'
      WHEN s.state='rejected' THEN 'retain_final_rejection'
      ELSE 'query_original_identity_only' END AS restart_action
FROM command_submission s LEFT JOIN submission_attempt a USING(submission_id)
LEFT JOIN submission_adjudication j USING(submission_id);

-- 在既有recovery.sql和dispatch.sql之后加载的设计候选，不是生产迁移。
-- U20精确+1、正文Schema/JCS、身份与完整匹配索引来源由writer另验。
CREATE TABLE ingress_storage_profile (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 version TEXT NOT NULL CHECK(version='ingress-storage/0.1.0-draft.1')
) STRICT;
CREATE TABLE ingest_epoch (
 epoch TEXT PRIMARY KEY NOT NULL, state TEXT NOT NULL CHECK(state IN ('open','closed')),
 last_sequence TEXT NOT NULL CHECK(length(last_sequence) BETWEEN 1 AND 20 AND last_sequence NOT GLOB '*[^0-9]*' AND (last_sequence='0' OR substr(last_sequence,1,1)!='0') AND instr(last_sequence,char(0))=0)
) STRICT;
CREATE UNIQUE INDEX one_open_ingest_epoch ON ingest_epoch(state) WHERE state='open';
CREATE TABLE ingress_source (
 source_id TEXT PRIMARY KEY NOT NULL, source_key BLOB NOT NULL UNIQUE,
 revision TEXT NOT NULL, contiguous_sequence TEXT NOT NULL, reject_floor TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('synchronized','desynchronized','quarantined','closed','baseline_required')),
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 CHECK(length(contiguous_sequence) BETWEEN 1 AND 20 AND contiguous_sequence NOT GLOB '*[^0-9]*' AND (contiguous_sequence='0' OR substr(contiguous_sequence,1,1)!='0') AND instr(contiguous_sequence,char(0))=0),
 CHECK(length(reject_floor) BETWEEN 1 AND 20 AND reject_floor NOT GLOB '*[^0-9]*' AND (reject_floor='0' OR substr(reject_floor,1,1)!='0') AND instr(reject_floor,char(0))=0)
) STRICT;
CREATE TABLE ingress_registry (
 source_id TEXT PRIMARY KEY NOT NULL REFERENCES ingress_source(source_id), revision TEXT NOT NULL,
 FOREIGN KEY(source_id) REFERENCES sb_commit(source_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0)
) STRICT;
CREATE TABLE ingress_listener (
 source_id TEXT NOT NULL REFERENCES ingress_registry(source_id), run_id TEXT NOT NULL REFERENCES run(run_id),
 artifact_digest TEXT NOT NULL, binding_body BLOB NOT NULL, PRIMARY KEY(source_id,run_id)
) STRICT;
CREATE TABLE ingress_inbox (
 inbox_id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES ingress_source(source_id),
 event_id TEXT NOT NULL, source_sequence TEXT NOT NULL, origin_digest TEXT NOT NULL, content_body BLOB NOT NULL,
 first_observation_body BLOB NOT NULL, observed_only INTEGER NOT NULL CHECK(observed_only IN (0,1)),
 commit_id TEXT UNIQUE,
 CHECK(length(source_sequence) BETWEEN 1 AND 20 AND source_sequence NOT GLOB '*[^0-9]*' AND substr(source_sequence,1,1)!='0' AND instr(source_sequence,char(0))=0),
 UNIQUE(source_id,event_id), UNIQUE(source_id,source_sequence), UNIQUE(inbox_id,commit_id),
 FOREIGN KEY(commit_id,inbox_id) REFERENCES ingress_commit(commit_id,inbox_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_commit (
 commit_id TEXT PRIMARY KEY NOT NULL, inbox_id TEXT NOT NULL UNIQUE,
 epoch TEXT NOT NULL REFERENCES ingest_epoch(epoch), receive_sequence TEXT NOT NULL,
 registry_revision TEXT NOT NULL, source_revision_before TEXT NOT NULL, source_revision_after TEXT NOT NULL,
 expected_targets INTEGER NOT NULL CHECK(expected_targets BETWEEN 0 AND 256),
 decision_set_digest TEXT NOT NULL, body BLOB NOT NULL, notification_id TEXT NOT NULL UNIQUE,
 sealed INTEGER NOT NULL CHECK(sealed IN (0,1)), required_seal INTEGER NOT NULL DEFAULT 1 CHECK(required_seal=1),
 CHECK(length(receive_sequence) BETWEEN 1 AND 20 AND receive_sequence NOT GLOB '*[^0-9]*' AND substr(receive_sequence,1,1)!='0' AND instr(receive_sequence,char(0))=0),
 CHECK(length(registry_revision) BETWEEN 1 AND 20 AND registry_revision NOT GLOB '*[^0-9]*' AND (registry_revision='0' OR substr(registry_revision,1,1)!='0') AND instr(registry_revision,char(0))=0),
 CHECK(length(source_revision_before) BETWEEN 1 AND 20 AND source_revision_before NOT GLOB '*[^0-9]*' AND (source_revision_before='0' OR substr(source_revision_before,1,1)!='0') AND instr(source_revision_before,char(0))=0),
 CHECK(length(source_revision_after) BETWEEN 1 AND 20 AND source_revision_after NOT GLOB '*[^0-9]*' AND (source_revision_after='0' OR substr(source_revision_after,1,1)!='0') AND instr(source_revision_after,char(0))=0),
 UNIQUE(epoch,receive_sequence), UNIQUE(commit_id,inbox_id), UNIQUE(commit_id,sealed), UNIQUE(commit_id,notification_id),
 FOREIGN KEY(inbox_id,commit_id) REFERENCES ingress_inbox(inbox_id,commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(commit_id,required_seal) REFERENCES ingress_commit_seal(commit_id,sealed) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(notification_id,commit_id) REFERENCES ingress_notification(notification_id,commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(commit_id) REFERENCES ingress_charge(commit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_target (
 commit_id TEXT NOT NULL REFERENCES ingress_commit(commit_id), run_id TEXT NOT NULL REFERENCES run(run_id),
 artifact_digest TEXT NOT NULL, binding_body BLOB NOT NULL, decision_id TEXT NOT NULL UNIQUE,
 PRIMARY KEY(commit_id,run_id), UNIQUE(commit_id,run_id,decision_id),
 FOREIGN KEY(decision_id,commit_id,run_id) REFERENCES ingress_decision(decision_id,commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_snapshot (
 snapshot_id TEXT PRIMARY KEY NOT NULL, commit_id TEXT NOT NULL, run_id TEXT NOT NULL,
 digest TEXT NOT NULL, body BLOB NOT NULL, UNIQUE(snapshot_id,commit_id,run_id), UNIQUE(commit_id,run_id),
 FOREIGN KEY(commit_id,run_id) REFERENCES ingress_target(commit_id,run_id),
 FOREIGN KEY(snapshot_id,commit_id,run_id) REFERENCES ingress_decision(snapshot_id,commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_decision (
 decision_id TEXT PRIMARY KEY NOT NULL, commit_id TEXT NOT NULL, run_id TEXT NOT NULL, inbox_id TEXT NOT NULL,
 result TEXT NOT NULL CHECK(result IN ('accepted','no_match','suppressed_busy','suppressed_inactive','suppressed_obsolete','evaluation_unknown','ambiguous','protected')),
 snapshot_id TEXT, execution_id TEXT UNIQUE, digest TEXT NOT NULL, body BLOB NOT NULL,
 run_before TEXT NOT NULL, run_after TEXT NOT NULL, progress_before TEXT NOT NULL, progress_after TEXT NOT NULL,
 CHECK(length(run_before) BETWEEN 1 AND 20 AND run_before NOT GLOB '*[^0-9]*' AND (run_before='0' OR substr(run_before,1,1)!='0') AND instr(run_before,char(0))=0),
 CHECK(length(run_after) BETWEEN 1 AND 20 AND run_after NOT GLOB '*[^0-9]*' AND (run_after='0' OR substr(run_after,1,1)!='0') AND instr(run_after,char(0))=0),
 CHECK(length(progress_before) BETWEEN 1 AND 20 AND progress_before NOT GLOB '*[^0-9]*' AND (progress_before='0' OR substr(progress_before,1,1)!='0') AND instr(progress_before,char(0))=0),
 CHECK(length(progress_after) BETWEEN 1 AND 20 AND progress_after NOT GLOB '*[^0-9]*' AND (progress_after='0' OR substr(progress_after,1,1)!='0') AND instr(progress_after,char(0))=0),
 UNIQUE(run_id,inbox_id), UNIQUE(decision_id,commit_id,run_id), UNIQUE(commit_id,run_id), UNIQUE(decision_id,run_id,execution_id),
 UNIQUE(snapshot_id,commit_id,run_id),
 CHECK((result='accepted')=(execution_id IS NOT NULL)),
 CHECK(result NOT IN ('accepted','no_match','evaluation_unknown','ambiguous') OR snapshot_id IS NOT NULL),
 FOREIGN KEY(commit_id,inbox_id) REFERENCES ingress_commit(commit_id,inbox_id),
 FOREIGN KEY(commit_id,run_id,decision_id) REFERENCES ingress_target(commit_id,run_id,decision_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(snapshot_id,commit_id,run_id) REFERENCES ingress_snapshot(snapshot_id,commit_id,run_id),
 FOREIGN KEY(execution_id,run_id,decision_id) REFERENCES ingress_execution(execution_id,run_id,decision_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(commit_id,run_id) REFERENCES ingress_run_audit(commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_execution (
 execution_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL, decision_id TEXT NOT NULL UNIQUE,
 UNIQUE(execution_id,run_id,decision_id),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(decision_id,run_id,execution_id) REFERENCES ingress_decision(decision_id,run_id,execution_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE run_ingest_progress (
 run_id TEXT PRIMARY KEY NOT NULL REFERENCES run(run_id), revision TEXT NOT NULL,
 epoch TEXT NOT NULL REFERENCES ingest_epoch(epoch), last_sequence TEXT NOT NULL, baseline_body BLOB NOT NULL, last_commit_id TEXT,
 CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 CHECK(length(last_sequence) BETWEEN 1 AND 20 AND last_sequence NOT GLOB '*[^0-9]*' AND (last_sequence='0' OR substr(last_sequence,1,1)!='0') AND instr(last_sequence,char(0))=0),
 FOREIGN KEY(last_commit_id,run_id) REFERENCES ingress_decision(commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_notification (
 notification_id TEXT PRIMARY KEY NOT NULL, commit_id TEXT NOT NULL UNIQUE, payload_body BLOB NOT NULL,
 UNIQUE(notification_id,commit_id),
 FOREIGN KEY(commit_id,notification_id) REFERENCES ingress_commit(commit_id,notification_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_run_audit (
 commit_id TEXT NOT NULL, run_id TEXT NOT NULL, phase TEXT NOT NULL CHECK(phase='INGRESS_RUN'),
 audit_body BLOB NOT NULL, event_body BLOB NOT NULL, PRIMARY KEY(commit_id,run_id),
 FOREIGN KEY(commit_id,run_id) REFERENCES ingress_decision(commit_id,run_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ingress_charge (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES ingress_commit(commit_id),
 profile_body BLOB NOT NULL, charge_body BLOB NOT NULL
) STRICT;

CREATE TRIGGER epoch_update BEFORE UPDATE ON ingest_epoch
WHEN NEW.epoch IS NOT OLD.epoch OR OLD.state='closed' OR
 (length(NEW.last_sequence),NEW.last_sequence COLLATE BINARY)<(length(OLD.last_sequence),OLD.last_sequence COLLATE BINARY)
BEGIN SELECT RAISE(ABORT,'epoch_monotonic'); END;
CREATE TRIGGER epoch_delete BEFORE DELETE ON ingest_epoch BEGIN SELECT RAISE(ABORT,'retain_epoch'); END;
CREATE TRIGGER source_update BEFORE UPDATE ON ingress_source
WHEN NEW.source_id IS NOT OLD.source_id OR NEW.source_key IS NOT OLD.source_key OR OLD.state='closed' OR
 (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY) OR
 (length(NEW.contiguous_sequence),NEW.contiguous_sequence COLLATE BINARY)<(length(OLD.contiguous_sequence),OLD.contiguous_sequence COLLATE BINARY) OR
 (length(NEW.reject_floor),NEW.reject_floor COLLATE BINARY)<(length(OLD.reject_floor),OLD.reject_floor COLLATE BINARY)
BEGIN SELECT RAISE(ABORT,'source_monotonic'); END;
CREATE TRIGGER source_delete BEFORE DELETE ON ingress_source BEGIN SELECT RAISE(ABORT,'retain_source'); END;
CREATE TRIGGER inbox_update BEFORE UPDATE ON ingress_inbox
WHEN NEW.inbox_id IS NOT OLD.inbox_id OR NEW.source_id IS NOT OLD.source_id OR NEW.event_id IS NOT OLD.event_id OR
 NEW.source_sequence IS NOT OLD.source_sequence OR NEW.origin_digest IS NOT OLD.origin_digest OR
 NEW.content_body IS NOT OLD.content_body OR NEW.first_observation_body IS NOT OLD.first_observation_body OR
 NEW.observed_only<OLD.observed_only OR OLD.commit_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'inbox_immutable'); END;
CREATE TRIGGER inbox_delete BEFORE DELETE ON ingress_inbox BEGIN SELECT RAISE(ABORT,'retain_inbox'); END;
CREATE TRIGGER ingress_commit_insert BEFORE INSERT ON ingress_commit
WHEN NEW.sealed!=0 OR NOT EXISTS(SELECT 1 FROM ingest_epoch WHERE epoch=NEW.epoch AND state='open'
 AND (length(last_sequence),last_sequence COLLATE BINARY)<(length(NEW.receive_sequence),NEW.receive_sequence COLLATE BINARY))
 OR NOT EXISTS(SELECT 1 FROM ingress_inbox i JOIN ingress_source s USING(source_id) JOIN ingress_registry r USING(source_id)
 WHERE i.inbox_id=NEW.inbox_id AND s.revision=NEW.source_revision_before AND r.revision=NEW.registry_revision)
BEGIN SELECT RAISE(ABORT,'ingress_initial'); END;
CREATE TRIGGER ingress_commit_seal BEFORE UPDATE ON ingress_commit
BEGIN
 SELECT CASE WHEN OLD.sealed!=0 OR NEW.sealed!=1 OR NEW.commit_id IS NOT OLD.commit_id OR NEW.inbox_id IS NOT OLD.inbox_id OR
 NEW.epoch IS NOT OLD.epoch OR NEW.receive_sequence IS NOT OLD.receive_sequence OR NEW.registry_revision IS NOT OLD.registry_revision OR
 NEW.source_revision_before IS NOT OLD.source_revision_before OR NEW.source_revision_after IS NOT OLD.source_revision_after OR
 NEW.expected_targets IS NOT OLD.expected_targets OR NEW.decision_set_digest IS NOT OLD.decision_set_digest OR
 NEW.body IS NOT OLD.body OR NEW.notification_id IS NOT OLD.notification_id OR NEW.required_seal IS NOT OLD.required_seal
 THEN RAISE(ABORT,'seal_once') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingest_epoch WHERE epoch=NEW.epoch AND state='open' AND last_sequence=NEW.receive_sequence)
 THEN RAISE(ABORT,'epoch_watermark') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingress_inbox i JOIN ingress_source s USING(source_id)
 JOIN ingress_registry r USING(source_id) WHERE i.inbox_id=NEW.inbox_id AND i.commit_id=NEW.commit_id
 AND s.revision=NEW.source_revision_after AND s.contiguous_sequence=i.source_sequence AND r.revision=NEW.registry_revision)
 THEN RAISE(ABORT,'source_projection') END;
 SELECT CASE WHEN NEW.expected_targets!=(SELECT count(*) FROM ingress_target WHERE commit_id=NEW.commit_id)
 OR EXISTS(SELECT l.run_id,l.artifact_digest,l.binding_body FROM ingress_listener l JOIN ingress_inbox i USING(source_id) WHERE i.inbox_id=NEW.inbox_id
 EXCEPT SELECT run_id,artifact_digest,binding_body FROM ingress_target WHERE commit_id=NEW.commit_id)
 OR EXISTS(SELECT run_id,artifact_digest,binding_body FROM ingress_target WHERE commit_id=NEW.commit_id
 EXCEPT SELECT l.run_id,l.artifact_digest,l.binding_body FROM ingress_listener l JOIN ingress_inbox i USING(source_id) WHERE i.inbox_id=NEW.inbox_id)
 THEN RAISE(ABORT,'whole_match_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_target t LEFT JOIN ingress_decision d
 ON d.decision_id=t.decision_id AND d.run_id=t.run_id AND d.commit_id=t.commit_id WHERE t.commit_id=NEW.commit_id AND d.decision_id IS NULL)
 THEN RAISE(ABORT,'decision_coverage') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_snapshot s LEFT JOIN ingress_decision d
 ON d.snapshot_id=s.snapshot_id AND d.commit_id=s.commit_id AND d.run_id=s.run_id
 WHERE s.commit_id=NEW.commit_id AND d.decision_id IS NULL)
 THEN RAISE(ABORT,'snapshot_coverage') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingress_notification WHERE commit_id=NEW.commit_id AND notification_id=NEW.notification_id)
 OR NOT EXISTS(SELECT 1 FROM ingress_charge WHERE commit_id=NEW.commit_id)
 OR EXISTS(SELECT 1 FROM ingress_decision d LEFT JOIN ingress_run_audit a USING(commit_id,run_id)
 WHERE d.commit_id=NEW.commit_id AND a.run_id IS NULL)
 THEN RAISE(ABORT,'ingress_receipt_coverage') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_decision d LEFT JOIN run_ingest_progress p USING(run_id) JOIN run r USING(run_id)
 WHERE d.commit_id=NEW.commit_id AND (p.run_id IS NULL OR p.last_commit_id IS NOT NEW.commit_id OR p.epoch IS NOT NEW.epoch
 OR p.last_sequence IS NOT NEW.receive_sequence OR p.revision IS NOT d.progress_after OR r.revision IS NOT d.run_after))
 THEN RAISE(ABORT,'run_progress_projection') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_decision d JOIN ingress_inbox i USING(inbox_id) WHERE d.commit_id=NEW.commit_id AND i.observed_only=1 AND d.result='accepted')
 THEN RAISE(ABORT,'observed_only') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_decision d JOIN run r USING(run_id)
 LEFT JOIN execution e ON e.execution_id=d.execution_id LEFT JOIN execution_plan_set p ON p.execution_id=e.execution_id
 LEFT JOIN activation_slot a ON a.definition_id=r.definition_id
 WHERE d.commit_id=NEW.commit_id AND d.result='accepted' AND
 (e.execution_id IS NULL OR e.run_id IS NOT d.run_id OR e.origin_kind!='trigger' OR e.state!='running' OR p.sealed IS NOT 1
 OR r.active_execution_id IS NOT e.execution_id OR r.lifecycle!='running' OR a.active_run_id IS NOT r.run_id OR a.version IS NOT r.version))
 THEN RAISE(ABORT,'accepted_projection') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ingress_decision d JOIN run r USING(run_id) WHERE d.commit_id=NEW.commit_id
 AND d.result IN ('protected','evaluation_unknown','ambiguous') AND (r.lifecycle!='paused' OR r.dispatch_eligible!=0))
 THEN RAISE(ABORT,'protected_projection') END;
END;
CREATE TRIGGER ingress_target_insert BEFORE INSERT ON ingress_target WHEN (SELECT sealed FROM ingress_commit WHERE commit_id=NEW.commit_id)!=0
BEGIN SELECT RAISE(ABORT,'sealed_targets'); END;
CREATE TRIGGER snapshot_insert BEFORE INSERT ON ingress_snapshot WHEN (SELECT sealed FROM ingress_commit WHERE commit_id=NEW.commit_id)!=0
BEGIN SELECT RAISE(ABORT,'sealed_snapshots'); END;
CREATE TRIGGER decision_insert BEFORE INSERT ON ingress_decision WHEN (SELECT sealed FROM ingress_commit WHERE commit_id=NEW.commit_id)!=0
BEGIN SELECT RAISE(ABORT,'sealed_decisions'); END;
CREATE TRIGGER decision_prestate BEFORE INSERT ON ingress_decision
WHEN NOT EXISTS(SELECT 1 FROM run r JOIN run_ingest_progress p USING(run_id)
 WHERE r.run_id=NEW.run_id AND r.revision=NEW.run_before AND p.revision=NEW.progress_before)
 OR (NEW.result='accepted' AND NOT EXISTS(SELECT 1 FROM run WHERE run_id=NEW.run_id AND lifecycle='armed'
 AND dispatch_eligible=1 AND active_execution_id IS NULL AND active_operation_id IS NULL))
BEGIN SELECT RAISE(ABORT,'decision_prestate'); END;
CREATE TRIGGER trigger_execution_requires_origin BEFORE INSERT ON execution
WHEN NEW.origin_kind='trigger' AND NOT EXISTS(SELECT 1 FROM ingress_execution WHERE execution_id=NEW.execution_id AND run_id=NEW.run_id)
BEGIN SELECT RAISE(ABORT,'trigger_origin_required'); END;
CREATE TRIGGER progress_update BEFORE UPDATE ON run_ingest_progress
WHEN NEW.run_id IS NOT OLD.run_id OR (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY) OR
 (NEW.epoch=OLD.epoch AND (length(NEW.last_sequence),NEW.last_sequence COLLATE BINARY)<(length(OLD.last_sequence),OLD.last_sequence COLLATE BINARY)) OR
 (NEW.epoch!=OLD.epoch AND (NEW.baseline_body IS OLD.baseline_body OR NEW.last_commit_id IS NOT NULL OR
 NOT EXISTS(SELECT 1 FROM run WHERE run_id=NEW.run_id AND lifecycle IN ('paused','disarmed') AND dispatch_eligible=0))) OR
 NOT EXISTS(SELECT 1 FROM ingest_epoch WHERE epoch=NEW.epoch AND state='open')
BEGIN SELECT RAISE(ABORT,'progress_epoch'); END;

CREATE TRIGGER commit_update_forbidden_delete BEFORE DELETE ON ingress_commit BEGIN SELECT RAISE(ABORT,'retain_commit'); END;
CREATE TRIGGER target_immutable BEFORE UPDATE ON ingress_target BEGIN SELECT RAISE(ABORT,'immutable_target'); END;
CREATE TRIGGER target_retain BEFORE DELETE ON ingress_target BEGIN SELECT RAISE(ABORT,'retain_target'); END;
CREATE TRIGGER snapshot_immutable BEFORE UPDATE ON ingress_snapshot BEGIN SELECT RAISE(ABORT,'immutable_snapshot'); END;
CREATE TRIGGER snapshot_retain BEFORE DELETE ON ingress_snapshot BEGIN SELECT RAISE(ABORT,'retain_snapshot'); END;
CREATE TRIGGER decision_immutable BEFORE UPDATE ON ingress_decision BEGIN SELECT RAISE(ABORT,'immutable_decision'); END;
CREATE TRIGGER decision_retain BEFORE DELETE ON ingress_decision BEGIN SELECT RAISE(ABORT,'retain_decision'); END;
CREATE TRIGGER origin_immutable BEFORE UPDATE ON ingress_execution BEGIN SELECT RAISE(ABORT,'immutable_origin'); END;
CREATE TRIGGER origin_retain BEFORE DELETE ON ingress_execution BEGIN SELECT RAISE(ABORT,'retain_origin'); END;
CREATE TRIGGER notification_immutable BEFORE UPDATE ON ingress_notification BEGIN SELECT RAISE(ABORT,'immutable_notification'); END;
CREATE TRIGGER notification_retain BEFORE DELETE ON ingress_notification BEGIN SELECT RAISE(ABORT,'retain_notification'); END;
CREATE TRIGGER audit_immutable BEFORE UPDATE ON ingress_run_audit BEGIN SELECT RAISE(ABORT,'immutable_audit'); END;
CREATE TRIGGER audit_retain BEFORE DELETE ON ingress_run_audit BEGIN SELECT RAISE(ABORT,'retain_audit'); END;
CREATE TRIGGER charge_immutable BEFORE UPDATE ON ingress_charge BEGIN SELECT RAISE(ABORT,'immutable_charge'); END;
CREATE TRIGGER charge_retain BEFORE DELETE ON ingress_charge BEGIN SELECT RAISE(ABORT,'retain_charge'); END;
CREATE TRIGGER progress_retain BEFORE DELETE ON run_ingest_progress BEGIN SELECT RAISE(ABORT,'retain_progress'); END;

-- Seamer P4独立内存实验布局；sp_plan/target为已核验P1封存计划的导入边界，尚非完整P1实现。
CREATE TABLE sp_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,plan_digest TEXT NOT NULL,
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 65536),
 plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(plan_id) REFERENCES protection_plan_registry(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE sp_target(
 plan_id TEXT NOT NULL REFERENCES sp_plan(plan_id),target_id TEXT NOT NULL,
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,binding_body)
) STRICT;
CREATE TABLE sp_plan_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES sp_plan(plan_id),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0)
) STRICT;
CREATE TRIGGER sp_target_frozen BEFORE INSERT ON sp_target WHEN EXISTS(SELECT 1 FROM sp_plan_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'protection_plan_frozen'); END;
CREATE TRIGGER sp_plan_seal BEFORE INSERT ON sp_plan_commit BEGIN
 SELECT CASE WHEN (SELECT target_count FROM sp_plan WHERE plan_id=NEW.plan_id)!=(SELECT count(*) FROM sp_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_targets_incomplete') END;
END;
CREATE TABLE sp_observation(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,revision INTEGER NOT NULL CHECK(revision IN (1,2)),
 state TEXT NOT NULL CHECK(state IN ('applied','indeterminate')),
 binding_body BLOB NOT NULL,identity_body BLOB NOT NULL CHECK(length(identity_body)>0),
 observation_digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0),
 PRIMARY KEY(plan_id,target_id,revision),
 CHECK((revision=1 AND state='applied') OR(revision=2 AND state='indeterminate')),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id),
 FOREIGN KEY(plan_id,target_id,revision) REFERENCES sp_observation_commit(plan_id,target_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE sp_observation_commit(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,revision INTEGER NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 PRIMARY KEY(plan_id,target_id,revision),
 FOREIGN KEY(plan_id,target_id,revision) REFERENCES sp_observation(plan_id,target_id,revision)
) STRICT;
CREATE TRIGGER sp_observation_guard BEFORE INSERT ON sp_observation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sp_target t JOIN sp_plan_commit k USING(plan_id)
 WHERE t.plan_id=NEW.plan_id AND t.target_id=NEW.target_id AND t.binding_body=NEW.binding_body)
 OR EXISTS(SELECT 1 FROM sp_observation o WHERE o.plan_id=NEW.plan_id AND o.target_id=NEW.target_id AND o.identity_body!=NEW.identity_body)
 THEN RAISE(ABORT,'protection_observation_binding') END;
END;
CREATE VIEW sp_current_observation AS SELECT o.* FROM sp_observation o JOIN sp_observation_commit k USING(plan_id,target_id,revision)
 WHERE o.revision=(SELECT max(n.revision) FROM sp_observation n JOIN sp_observation_commit c USING(plan_id,target_id,revision)
 WHERE n.plan_id=o.plan_id AND n.target_id=o.target_id);
CREATE VIEW sp_observed_summary AS SELECT p.plan_id,
 CASE WHEN EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=p.plan_id AND o.state='indeterminate') THEN 'indeterminate'
 WHEN NOT EXISTS(SELECT 1 FROM sp_target t WHERE t.plan_id=p.plan_id AND NOT EXISTS(SELECT 1 FROM sp_current_observation o
 WHERE o.plan_id=t.plan_id AND o.target_id=t.target_id AND o.state='applied')) THEN 'applied' ELSE 'pending' END AS observed_state,
 p.target_count,(SELECT count(*) FROM sp_current_observation o WHERE o.plan_id=p.plan_id) AS observed_targets
 FROM sp_plan p JOIN sp_plan_commit k USING(plan_id);
CREATE TRIGGER sp_plan_u BEFORE UPDATE ON sp_plan BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_plan_d BEFORE DELETE ON sp_plan BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_target_u BEFORE UPDATE ON sp_target BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_target_d BEFORE DELETE ON sp_target BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_plan_commit_u BEFORE UPDATE ON sp_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_plan_commit_d BEFORE DELETE ON sp_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_observation_u BEFORE UPDATE ON sp_observation BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_observation_d BEFORE DELETE ON sp_observation BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_observation_commit_u BEFORE UPDATE ON sp_observation_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_observation_commit_d BEFORE DELETE ON sp_observation_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;

-- 独立准备观察库：P1计划导入仍是可信边界，不把观察结果当发送或恢复授权。
CREATE TABLE po_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,plan_digest TEXT NOT NULL,
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 1 AND 65536),
 plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(plan_id) REFERENCES p1_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES po_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE po_target(
 plan_id TEXT NOT NULL REFERENCES po_plan(plan_id),target_id TEXT NOT NULL,
 binding_body BLOB NOT NULL CHECK(length(binding_body) BETWEEN 1 AND 16384),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,binding_body)
) STRICT;
CREATE TABLE po_plan_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES po_plan(plan_id),validation_body BLOB NOT NULL CHECK(length(validation_body)>0)
) STRICT;
CREATE TRIGGER po_target_frozen BEFORE INSERT ON po_target WHEN EXISTS(SELECT 1 FROM po_plan_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'preparation_plan_frozen'); END;
CREATE TRIGGER po_plan_seal BEFORE INSERT ON po_plan_commit BEGIN
 SELECT CASE WHEN (SELECT target_count FROM po_plan WHERE plan_id=NEW.plan_id)!=(SELECT count(*) FROM po_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'preparation_targets_incomplete') END;
END;
CREATE TABLE po_observation(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,
 preparation_revision TEXT NOT NULL CHECK(preparation_revision IN ('00000000000000000001','00000000000000000002','00000000000000000003','00000000000000000004')),
 protection_revision INTEGER NOT NULL CHECK(protection_revision IN (0,1,2)),
 state TEXT NOT NULL CHECK(state IN ('accepted','applied','rejected','indeterminate','closing','closed')),
 protection_state TEXT NOT NULL CHECK(protection_state IN ('not_applicable','pending','applied','indeterminate')),
 binding_body BLOB NOT NULL,observation_digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16384),
 PRIMARY KEY(plan_id,target_id,preparation_revision,protection_revision),
 CHECK((state IN ('accepted','applied','rejected','indeterminate') AND protection_state='not_applicable' AND protection_revision=0)
 OR(state='closing' AND protection_state='pending' AND protection_revision=0)
 OR(state='closed' AND ((protection_state='applied' AND protection_revision=1) OR(protection_state='indeterminate' AND protection_revision=2)))),
 FOREIGN KEY(plan_id,target_id) REFERENCES po_target(plan_id,target_id),
 FOREIGN KEY(plan_id,target_id,preparation_revision,protection_revision) REFERENCES po_observation_commit(plan_id,target_id,preparation_revision,protection_revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE po_observation_commit(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,preparation_revision TEXT NOT NULL,protection_revision INTEGER NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 PRIMARY KEY(plan_id,target_id,preparation_revision,protection_revision),
 FOREIGN KEY(plan_id,target_id,preparation_revision,protection_revision) REFERENCES po_observation(plan_id,target_id,preparation_revision,protection_revision)
) STRICT;
CREATE TRIGGER po_observation_guard BEFORE INSERT ON po_observation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM po_target t JOIN po_plan_commit k USING(plan_id)
 WHERE t.plan_id=NEW.plan_id AND t.target_id=NEW.target_id AND t.binding_body=NEW.binding_body)
 THEN RAISE(ABORT,'preparation_observation_binding') END;
END;
CREATE TABLE po_conflict(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,observation_digest TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('same_revision_conflict','history_conflict','receipt_conflict','completion_conflict')),
 binding_body BLOB NOT NULL,body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16384),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 PRIMARY KEY(plan_id,target_id),
 FOREIGN KEY(plan_id,target_id) REFERENCES po_target(plan_id,target_id)
) STRICT;
CREATE TRIGGER po_conflict_guard BEFORE INSERT ON po_conflict BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM po_target t JOIN po_plan_commit k USING(plan_id)
 WHERE t.plan_id=NEW.plan_id AND t.target_id=NEW.target_id AND t.binding_body=NEW.binding_body)
 THEN RAISE(ABORT,'preparation_conflict_binding') END;
END;
CREATE VIEW po_current_observation AS SELECT o.* FROM po_observation o JOIN po_observation_commit k
 USING(plan_id,target_id,preparation_revision,protection_revision)
 WHERE NOT EXISTS(SELECT 1 FROM po_observation n JOIN po_observation_commit c
 USING(plan_id,target_id,preparation_revision,protection_revision)
 WHERE n.plan_id=o.plan_id AND n.target_id=o.target_id AND
 (n.preparation_revision>o.preparation_revision OR(n.preparation_revision=o.preparation_revision AND n.protection_revision>o.protection_revision)));
CREATE VIEW po_target_status AS SELECT t.plan_id,t.target_id,o.preparation_revision,o.protection_revision,o.state,
 CASE WHEN EXISTS(SELECT 1 FROM po_conflict c WHERE c.plan_id=t.plan_id AND c.target_id=t.target_id) THEN 'unconfirmed'
 WHEN o.state='closed' THEN o.protection_state ELSE 'pending' END AS observed_closure_state
 FROM po_target t JOIN po_plan_commit k USING(plan_id) LEFT JOIN po_current_observation o USING(plan_id,target_id);
CREATE VIEW po_closure_summary AS SELECT p.plan_id,p.target_count,
 (SELECT count(*) FROM po_current_observation o WHERE o.plan_id=p.plan_id) AS observed_targets,
 CASE WHEN EXISTS(SELECT 1 FROM po_target_status s WHERE s.plan_id=p.plan_id AND s.observed_closure_state='unconfirmed') THEN 'unconfirmed'
 WHEN EXISTS(SELECT 1 FROM po_target_status s WHERE s.plan_id=p.plan_id AND s.observed_closure_state='indeterminate') THEN 'indeterminate'
 WHEN EXISTS(SELECT 1 FROM po_target_status s WHERE s.plan_id=p.plan_id AND s.observed_closure_state!='applied') THEN 'pending'
 ELSE 'applied' END AS observed_state FROM po_plan p JOIN po_plan_commit k USING(plan_id);

-- P1持久集合与P4实际计划引用；来源绑定语义/认证仍由可信提供者负责。
CREATE TABLE p1_limit(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),profile_body BLOB NOT NULL CHECK(length(profile_body)>0),
 max_dependencies INTEGER NOT NULL CHECK(max_dependencies>0),max_preparations INTEGER NOT NULL CHECK(max_preparations>0),
 max_plans INTEGER NOT NULL CHECK(max_plans>0),max_runs INTEGER NOT NULL CHECK(max_runs BETWEEN 1 AND 4096),
 max_targets INTEGER NOT NULL CHECK(max_targets BETWEEN 1 AND 65536),max_payload_bytes INTEGER NOT NULL CHECK(max_payload_bytes>0)
) STRICT;
CREATE TABLE p1_dependency(
 dependency_id TEXT PRIMARY KEY NOT NULL,sequence INTEGER NOT NULL UNIQUE CHECK(sequence>0),
 source_id TEXT NOT NULL REFERENCES ingress_source(source_id),run_id TEXT NOT NULL REFERENCES run(run_id),
 owner_kind TEXT NOT NULL CHECK(owner_kind IN ('run','execution','recovery')),owner_ref TEXT NOT NULL,
 execution_id TEXT,recovery_id TEXT,artifact_digest TEXT NOT NULL,binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 UNIQUE(source_id,run_id,owner_kind,owner_ref),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(recovery_id,run_id) REFERENCES recovery_operation(operation_id,run_id),
 CHECK((owner_kind='run' AND owner_ref=run_id AND execution_id IS NULL AND recovery_id IS NULL)
 OR(owner_kind='execution' AND owner_ref=execution_id AND execution_id IS NOT NULL AND recovery_id IS NULL)
 OR(owner_kind='recovery' AND owner_ref=recovery_id AND recovery_id IS NOT NULL AND execution_id IS NULL))
) STRICT;
CREATE TRIGGER p1_dependency_guard BEFORE INSERT ON p1_dependency BEGIN
 SELECT CASE WHEN NEW.sequence!=(SELECT coalesce(max(sequence),0)+1 FROM p1_dependency)
 OR NOT EXISTS(SELECT 1 FROM p1_limit WHERE singleton=1 AND (SELECT count(*) FROM p1_dependency)<max_dependencies)
 OR NOT EXISTS(SELECT 1 FROM run r JOIN published_version p USING(definition_id,version) WHERE r.run_id=NEW.run_id AND p.artifact_digest=NEW.artifact_digest)
 THEN RAISE(ABORT,'source_dependency_registration') END;
END;
CREATE TABLE p1_preparation(
 registration_id TEXT PRIMARY KEY NOT NULL,sequence INTEGER NOT NULL UNIQUE CHECK(sequence>0),
 run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,preparation_id TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('arm','recovery')),execution_id TEXT,request_digest TEXT NOT NULL,
 recovery_operation_id TEXT,recovery_controller_id TEXT,
 arm_operation_id TEXT REFERENCES arm_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,arm_controller_id TEXT,
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),request_body BLOB NOT NULL CHECK(length(request_body)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(controller_authority,controller_database,preparation_id),
 UNIQUE(recovery_operation_id,recovery_controller_id),
 UNIQUE(arm_operation_id,arm_controller_id),
 FOREIGN KEY(arm_operation_id,arm_controller_id) REFERENCES arm_target(operation_id,controller_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((mode='arm' AND arm_operation_id IS NOT NULL AND arm_controller_id IS NOT NULL) OR(mode='recovery' AND arm_operation_id IS NULL AND arm_controller_id IS NULL)),
 UNIQUE(run_id,generation,controller_authority,controller_database),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id),
 FOREIGN KEY(recovery_operation_id,recovery_controller_id) REFERENCES preparation_target(operation_id,controller_id),
 FOREIGN KEY(recovery_operation_id,run_id,execution_id) REFERENCES recovery_operation(operation_id,run_id,execution_id),
 CHECK((mode='arm' AND execution_id IS NULL) OR(mode='recovery' AND execution_id IS NOT NULL)),
 CHECK((mode='arm' AND recovery_operation_id IS NULL AND recovery_controller_id IS NULL)
 OR(mode='recovery' AND recovery_operation_id IS NOT NULL AND recovery_controller_id IS NOT NULL)),
 CHECK(length(generation) BETWEEN 1 AND 20 AND generation NOT GLOB '*[^0-9]*' AND substr(generation,1,1)!='0' AND instr(generation,char(0))=0)
) STRICT;
CREATE TRIGGER p1_preparation_guard BEFORE INSERT ON p1_preparation BEGIN
 SELECT CASE WHEN NEW.sequence!=(SELECT coalesce(max(sequence),0)+1 FROM p1_preparation)
 OR NOT EXISTS(SELECT 1 FROM p1_limit WHERE singleton=1 AND (SELECT count(*) FROM p1_preparation)<max_preparations)
 OR NOT EXISTS(SELECT 1 FROM run r WHERE r.run_id=NEW.run_id AND r.arm_generation=NEW.generation
 AND ((NEW.mode='arm' AND r.lifecycle='disarmed' AND r.dispatch_eligible=0 AND r.active_execution_id IS NULL
 AND r.active_operation_id=NEW.arm_operation_id AND EXISTS(SELECT 1 FROM arm_operation o WHERE o.operation_id=NEW.arm_operation_id
 AND o.run_id=r.run_id AND o.generation=NEW.generation AND NOT EXISTS(SELECT 1 FROM arm_register_commit WHERE operation_id=o.operation_id))) OR(NEW.mode='recovery' AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.active_operation_id=NEW.recovery_operation_id AND r.active_execution_id=NEW.execution_id
 AND EXISTS(SELECT 1 FROM recovery_operation o JOIN execution e ON e.execution_id=o.execution_id JOIN preparation_target t USING(operation_id)
 WHERE o.operation_id=NEW.recovery_operation_id AND o.run_id=r.run_id AND o.state='preparing'
 AND e.arm_generation=NEW.generation AND e.state='prepared' AND t.controller_id=NEW.recovery_controller_id AND t.state='pending'))))
 OR EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=NEW.run_id AND substr('00000000000000000000'||NEW.generation,-20)<=d.generation)
 OR NOT EXISTS(SELECT 1 FROM storage_scope s WHERE s.singleton=1
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.preparation_id') IS NEW.preparation_id
 AND json_extract(NEW.binding_body,'$.run_id') IS NEW.run_id
 AND json_extract(NEW.binding_body,'$.generation') IS NEW.generation
 AND json_extract(NEW.binding_body,'$.mode') IS NEW.mode
 AND json_extract(NEW.binding_body,'$.execution_id') IS NEW.execution_id
 AND json_extract(NEW.binding_body,'$.request_digest') IS NEW.request_digest)
 THEN RAISE(ABORT,'preparation_registration') END;
END;
CREATE TABLE p1_fault(
 fault_id TEXT PRIMARY KEY NOT NULL,source_id TEXT NOT NULL REFERENCES ingress_source(source_id),
 detector_domain TEXT NOT NULL,detector_sequence TEXT NOT NULL,reason TEXT NOT NULL,
 fault_digest TEXT NOT NULL,fault_body BLOB NOT NULL CHECK(length(fault_body)>0),
 plan_id TEXT NOT NULL UNIQUE REFERENCES p1_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(detector_domain,detector_sequence),UNIQUE(fault_id,source_id,plan_id)
) STRICT;
CREATE TABLE p1_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,fault_id TEXT NOT NULL UNIQUE,source_id TEXT NOT NULL,
 dependency_head INTEGER NOT NULL CHECK(dependency_head>=0),preparation_head INTEGER NOT NULL CHECK(preparation_head>=0),
 source_before TEXT NOT NULL,source_after TEXT NOT NULL,source_state_before TEXT NOT NULL,source_state_after TEXT NOT NULL,
 source_sequence TEXT NOT NULL,reject_floor TEXT NOT NULL,
 run_count INTEGER NOT NULL CHECK(run_count BETWEEN 0 AND 4096),target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 65536),
 preparation_count INTEGER NOT NULL CHECK(preparation_count>=0),preparation_plan_id TEXT,
 plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(fault_id,source_id,plan_id) REFERENCES p1_fault(fault_id,source_id,plan_id),
 FOREIGN KEY(plan_id) REFERENCES p1_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(preparation_plan_id) REFERENCES po_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((preparation_count=0 AND preparation_plan_id IS NULL) OR(preparation_count>0 AND preparation_plan_id=plan_id))
) STRICT;
CREATE TRIGGER p1_plan_guard BEFORE INSERT ON p1_plan BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingress_source s WHERE s.source_id=NEW.source_id
 AND s.revision=NEW.source_before AND s.state=NEW.source_state_before AND s.contiguous_sequence=NEW.source_sequence AND s.reject_floor=NEW.reject_floor)
 OR (NEW.source_state_before='closed' AND (NEW.source_after!=NEW.source_before OR NEW.source_state_after!='closed'))
 OR (NEW.source_state_before!='closed' AND (NEW.source_before='99999999999999999999' OR NEW.source_after!=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.source_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.source_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.source_before,-20),11,10) AS INTEGER)+1)%10000000000),'0')
 OR NEW.source_state_after NOT IN ('desynchronized','quarantined') OR(NEW.source_state_before='quarantined' AND NEW.source_state_after!='quarantined')))
 THEN RAISE(ABORT,'protection_source_prestate') END;
END;
CREATE TABLE p1_run(
 plan_id TEXT NOT NULL REFERENCES p1_plan(plan_id),run_id TEXT NOT NULL REFERENCES run(run_id),
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,generation TEXT NOT NULL,lifecycle_before TEXT NOT NULL,
 latch_id TEXT NOT NULL UNIQUE REFERENCES pause_latch(latch_id) DEFERRABLE INITIALLY DEFERRED,
 PRIMARY KEY(plan_id,run_id)
) STRICT;
CREATE TRIGGER p1_run_guard BEFORE INSERT ON p1_run BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM run r WHERE r.run_id=NEW.run_id AND r.revision=NEW.revision_before
 AND r.arm_generation=NEW.generation AND r.lifecycle=NEW.lifecycle_before)
 OR EXISTS(SELECT 1 FROM execution e WHERE e.run_id=NEW.run_id AND (length(e.arm_generation),e.arm_generation COLLATE BINARY)>(length(NEW.generation),NEW.generation COLLATE BINARY))
 OR (NEW.lifecycle_before='completed' AND NEW.revision_after!=NEW.revision_before)
 OR (NEW.lifecycle_before!='completed' AND (NEW.revision_before='99999999999999999999' OR NEW.revision_after!=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10) AS INTEGER)+1)%10000000000),'0')))
 THEN RAISE(ABORT,'protection_run_prestate') END;
END;
CREATE TABLE p1_dependency_member(
 plan_id TEXT NOT NULL REFERENCES p1_plan(plan_id),dependency_id TEXT NOT NULL REFERENCES p1_dependency(dependency_id),
 PRIMARY KEY(plan_id,dependency_id)
) STRICT;
CREATE TABLE p1_execution_pin(
 plan_id TEXT NOT NULL,run_id TEXT NOT NULL,execution_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
 PRIMARY KEY(plan_id,execution_id),FOREIGN KEY(plan_id,run_id) REFERENCES p1_run(plan_id,run_id),
 FOREIGN KEY(execution_id,run_id) REFERENCES execution(execution_id,run_id)
) STRICT;
CREATE TABLE p1_controller(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,run_id TEXT NOT NULL,
 controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,operation_id TEXT NOT NULL,
 selector_digest TEXT NOT NULL,target_set_digest TEXT NOT NULL,binding_body BLOB NOT NULL,
 dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,run_id,controller_authority,controller_database),
 UNIQUE(controller_authority,controller_database,operation_id),
 FOREIGN KEY(plan_id,run_id) REFERENCES p1_run(plan_id,run_id),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER p1_controller_guard BEFORE INSERT ON p1_controller BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM p1_run r JOIN storage_scope s ON s.singleton=1 WHERE r.plan_id=NEW.plan_id AND r.run_id=NEW.run_id
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.operation_id') IS NEW.operation_id AND json_extract(NEW.binding_body,'$.run_id') IS NEW.run_id
 AND json_extract(NEW.binding_body,'$.deny_through_generation') IS r.generation
 AND json_extract(NEW.binding_body,'$.selector_digest') IS NEW.selector_digest AND json_extract(NEW.binding_body,'$.target_set_digest') IS NEW.target_set_digest)
 THEN RAISE(ABORT,'protection_controller_binding') END;
END;
CREATE TABLE p1_preparation_member(
 plan_id TEXT NOT NULL,registration_id TEXT NOT NULL REFERENCES p1_preparation(registration_id),target_id TEXT NOT NULL,
 PRIMARY KEY(plan_id,registration_id),FOREIGN KEY(plan_id,target_id) REFERENCES p1_controller(plan_id,target_id)
) STRICT;
CREATE TABLE p1_submission_member(
 plan_id TEXT NOT NULL,submission_id TEXT NOT NULL REFERENCES command_submission(submission_id),target_id TEXT NOT NULL,
 PRIMARY KEY(plan_id,submission_id),FOREIGN KEY(plan_id,target_id) REFERENCES p1_controller(plan_id,target_id)
) STRICT;
CREATE VIEW p1_expected_run AS SELECT DISTINCT p.plan_id,d.run_id FROM p1_plan p JOIN p1_dependency d USING(source_id);
CREATE VIEW p1_expected_preparation AS SELECT r.plan_id,p.registration_id,p.run_id,p.controller_authority,p.controller_database
 FROM p1_run r JOIN p1_preparation p USING(run_id) WHERE (length(p.generation),p.generation COLLATE BINARY)<=(length(r.generation),r.generation COLLATE BINARY);
CREATE VIEW p1_expected_submission AS SELECT r.plan_id,s.submission_id,s.run_id,s.target_authority AS controller_authority,s.target_database AS controller_database
 FROM p1_run r JOIN command_submission s USING(run_id) JOIN execution e ON e.execution_id=s.execution_id
 WHERE (length(e.arm_generation),e.arm_generation COLLATE BINARY)<=(length(r.generation),r.generation COLLATE BINARY);
CREATE VIEW p1_expected_controller AS SELECT plan_id,run_id,controller_authority,controller_database FROM p1_expected_preparation
 UNION SELECT plan_id,run_id,controller_authority,controller_database FROM p1_expected_submission;
CREATE TABLE p1_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_plan(plan_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER p1_seal BEFORE INSERT ON p1_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM p1_plan p JOIN ingress_source s USING(source_id) JOIN p1_limit l ON l.singleton=1
 WHERE p.plan_id=NEW.plan_id AND s.revision=p.source_after AND s.state=p.source_state_after
 AND s.contiguous_sequence=p.source_sequence AND s.reject_floor=p.reject_floor
 AND p.dependency_head=(SELECT coalesce(max(sequence),0) FROM p1_dependency)
 AND p.preparation_head=(SELECT coalesce(max(sequence),0) FROM p1_preparation)
 AND p.run_count=(SELECT count(*) FROM p1_run WHERE plan_id=p.plan_id) AND p.run_count<=l.max_runs
 AND p.target_count=(SELECT count(*) FROM p1_controller WHERE plan_id=p.plan_id) AND p.target_count<=l.max_targets
 AND p.preparation_count=(SELECT count(*) FROM p1_preparation_member WHERE plan_id=p.plan_id)
 AND (SELECT count(*) FROM p1_plan)<=l.max_plans
 AND length(p.plan_body)+(SELECT length(fault_body) FROM p1_fault WHERE fault_id=p.fault_id)
 +coalesce((SELECT sum(length(binding_body)+length(dispatch_body)+length(audit_body)) FROM p1_controller WHERE plan_id=p.plan_id),0)
 +length(NEW.audit_body)+length(NEW.notification_body)<=l.max_payload_bytes)
 THEN RAISE(ABORT,'protection_seal_prestate_or_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT run_id FROM p1_expected_run WHERE plan_id=NEW.plan_id EXCEPT SELECT run_id FROM p1_run WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT run_id FROM p1_run WHERE plan_id=NEW.plan_id EXCEPT SELECT run_id FROM p1_expected_run WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT d.dependency_id FROM p1_dependency d JOIN p1_plan p USING(source_id) WHERE p.plan_id=NEW.plan_id EXCEPT SELECT dependency_id FROM p1_dependency_member WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT dependency_id FROM p1_dependency_member WHERE plan_id=NEW.plan_id EXCEPT SELECT d.dependency_id FROM p1_dependency d JOIN p1_plan p USING(source_id) WHERE p.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_dependency_set') END;
 SELECT CASE WHEN EXISTS(SELECT r.run_id,e.execution_id,e.binding_digest FROM p1_run r JOIN execution e USING(run_id) WHERE r.plan_id=NEW.plan_id
 EXCEPT SELECT run_id,execution_id,binding_digest FROM p1_execution_pin WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT run_id,execution_id,binding_digest FROM p1_execution_pin WHERE plan_id=NEW.plan_id
 EXCEPT SELECT r.run_id,e.execution_id,e.binding_digest FROM p1_run r JOIN execution e USING(run_id) WHERE r.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_execution_set') END;
 SELECT CASE WHEN EXISTS(SELECT run_id,controller_authority,controller_database FROM p1_expected_controller WHERE plan_id=NEW.plan_id
 EXCEPT SELECT run_id,controller_authority,controller_database FROM p1_controller WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT run_id,controller_authority,controller_database FROM p1_controller WHERE plan_id=NEW.plan_id
 EXCEPT SELECT run_id,controller_authority,controller_database FROM p1_expected_controller WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_controller_set') END;
 SELECT CASE WHEN EXISTS(SELECT registration_id FROM p1_expected_preparation WHERE plan_id=NEW.plan_id EXCEPT SELECT registration_id FROM p1_preparation_member WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT registration_id FROM p1_preparation_member WHERE plan_id=NEW.plan_id EXCEPT SELECT registration_id FROM p1_expected_preparation WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT 1 FROM p1_preparation_member m JOIN p1_preparation r USING(registration_id) JOIN p1_controller c USING(plan_id,target_id)
 WHERE m.plan_id=NEW.plan_id AND (r.run_id,r.controller_authority,r.controller_database)!=(c.run_id,c.controller_authority,c.controller_database))
 OR EXISTS(SELECT submission_id FROM p1_expected_submission WHERE plan_id=NEW.plan_id EXCEPT SELECT submission_id FROM p1_submission_member WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT submission_id FROM p1_submission_member WHERE plan_id=NEW.plan_id EXCEPT SELECT submission_id FROM p1_expected_submission WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT 1 FROM p1_submission_member m JOIN command_submission r USING(submission_id) JOIN p1_controller c USING(plan_id,target_id)
 WHERE m.plan_id=NEW.plan_id AND (r.run_id,r.target_authority,r.target_database)!=(c.run_id,c.controller_authority,c.controller_database))
 OR EXISTS(SELECT 1 FROM p1_run r JOIN recovery_operation o USING(run_id) JOIN preparation_target t ON t.operation_id=o.operation_id
 WHERE r.plan_id=NEW.plan_id AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN p1_preparation_member m USING(registration_id)
 WHERE m.plan_id=r.plan_id AND p.recovery_operation_id=t.operation_id AND p.recovery_controller_id=t.controller_id))
 THEN RAISE(ABORT,'protection_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM p1_run t JOIN run r USING(run_id) LEFT JOIN pause_latch l ON l.latch_id=t.latch_id
 WHERE t.plan_id=NEW.plan_id AND (r.revision!=t.revision_after OR r.arm_generation!=t.generation OR r.dispatch_eligible!=0
 OR r.lifecycle!=CASE WHEN t.lifecycle_before='completed' THEN 'completed' ELSE 'paused' END
 OR l.latch_id IS NULL OR l.run_id!=r.run_id OR l.created_revision!=t.revision_after OR l.reason!='source_fault' OR l.cleared_start_id IS NOT NULL))
 THEN RAISE(ABORT,'protection_pause_projection') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sp_plan p JOIN sp_plan_commit k USING(plan_id) JOIN p1_plan s USING(plan_id)
 WHERE p.plan_id=NEW.plan_id AND p.target_count=s.target_count AND p.plan_digest=s.plan_digest AND p.plan_body=s.plan_body)
 OR EXISTS(SELECT target_id,binding_body FROM p1_controller WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM p1_controller WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT 1 FROM p1_plan p WHERE p.plan_id=NEW.plan_id AND p.preparation_count>0 AND NOT EXISTS(
 SELECT 1 FROM po_plan q JOIN po_plan_commit k USING(plan_id) WHERE q.plan_id=p.plan_id AND q.target_count=p.preparation_count))
 OR EXISTS(SELECT m.registration_id,r.binding_body FROM p1_preparation_member m JOIN p1_preparation r USING(registration_id) WHERE m.plan_id=NEW.plan_id
 EXCEPT SELECT target_id,binding_body FROM po_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM po_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT m.registration_id,r.binding_body FROM p1_preparation_member m JOIN p1_preparation r USING(registration_id) WHERE m.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_receiver_plan') END;
END;
CREATE VIEW p1_deny AS SELECT run_id,max(generation) AS generation FROM (
 SELECT r.run_id,substr('00000000000000000000'||r.generation,-20) AS generation FROM p1_run r JOIN p1_commit k USING(plan_id)
 UNION ALL SELECT p.run_id,substr('00000000000000000000'||p.generation,-20) FROM pq_plan p JOIN pq_commit k USING(plan_id)
 UNION ALL SELECT run_id,substr('00000000000000000000'||generation,-20) FROM aa_stop
 UNION ALL SELECT p.run_id,substr('00000000000000000000'||p.generation,-20) FROM sf_plan p JOIN sf_commit c USING(plan_id)) GROUP BY run_id;
CREATE VIEW p1_pending_dispatch AS SELECT c.* FROM p1_controller c JOIN p1_commit k USING(plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=c.plan_id AND o.target_id=c.target_id AND o.state='applied');
CREATE TRIGGER p1_preparation_plan_guard BEFORE INSERT ON po_plan WHEN NOT EXISTS(
 SELECT 1 FROM p1_plan p WHERE p.plan_id=NEW.plan_id AND p.preparation_plan_id=NEW.plan_id AND p.preparation_count=NEW.target_count
 AND NOT EXISTS(SELECT 1 FROM p1_commit k WHERE k.plan_id=p.plan_id))
 BEGIN SELECT RAISE(ABORT,'unplanned_preparation_observation'); END;
CREATE TRIGGER p1_deny_ready BEFORE INSERT ON step_ready WHEN EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id)
 WHERE e.execution_id=NEW.execution_id AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'source_generation_denied'); END;
CREATE TRIGGER p1_deny_submission BEFORE INSERT ON command_submission WHEN EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id)
 WHERE e.execution_id=NEW.execution_id AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'source_generation_denied'); END;
CREATE TRIGGER p1_deny_attempt BEFORE INSERT ON submission_attempt WHEN EXISTS(SELECT 1 FROM command_submission s JOIN execution e USING(execution_id) JOIN p1_deny d ON d.run_id=e.run_id
 WHERE s.submission_id=NEW.submission_id AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'source_generation_denied'); END;
CREATE TRIGGER p1_deny_start BEFORE INSERT ON execution_start WHEN EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id)
 WHERE e.execution_id=NEW.execution_id AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'source_generation_denied'); END;

CREATE TRIGGER p1_limit_u BEFORE UPDATE ON p1_limit BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_limit_d BEFORE DELETE ON p1_limit BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_dependency_u BEFORE UPDATE ON p1_dependency BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_dependency_d BEFORE DELETE ON p1_dependency BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_preparation_u BEFORE UPDATE ON p1_preparation BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_preparation_d BEFORE DELETE ON p1_preparation BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_fault_u BEFORE UPDATE ON p1_fault BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_fault_d BEFORE DELETE ON p1_fault BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_plan_u BEFORE UPDATE ON p1_plan BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_plan_d BEFORE DELETE ON p1_plan BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_run_u BEFORE UPDATE ON p1_run BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_run_d BEFORE DELETE ON p1_run BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_dependency_member_u BEFORE UPDATE ON p1_dependency_member BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_dependency_member_d BEFORE DELETE ON p1_dependency_member BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_execution_pin_u BEFORE UPDATE ON p1_execution_pin BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_execution_pin_d BEFORE DELETE ON p1_execution_pin BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_controller_u BEFORE UPDATE ON p1_controller BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_controller_d BEFORE DELETE ON p1_controller BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_preparation_member_u BEFORE UPDATE ON p1_preparation_member BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_preparation_member_d BEFORE DELETE ON p1_preparation_member BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_submission_member_u BEFORE UPDATE ON p1_submission_member BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_submission_member_d BEFORE DELETE ON p1_submission_member BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_commit_u BEFORE UPDATE ON p1_commit BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_commit_d BEFORE DELETE ON p1_commit BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_plan_u BEFORE UPDATE ON po_plan BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_plan_d BEFORE DELETE ON po_plan BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_target_u BEFORE UPDATE ON po_target BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_target_d BEFORE DELETE ON po_target BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_plan_commit_u BEFORE UPDATE ON po_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_plan_commit_d BEFORE DELETE ON po_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_observation_u BEFORE UPDATE ON po_observation BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_observation_d BEFORE DELETE ON po_observation BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_observation_commit_u BEFORE UPDATE ON po_observation_commit BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_observation_commit_d BEFORE DELETE ON po_observation_commit BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_conflict_u BEFORE UPDATE ON po_conflict BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER po_conflict_d BEFORE DELETE ON po_conflict BEGIN SELECT RAISE(ABORT,'immutable_source_protection'); END;

CREATE TRIGGER p1_run_sealed BEFORE INSERT ON p1_run WHEN EXISTS(SELECT 1 FROM p1_commit WHERE plan_id=NEW.plan_id) BEGIN SELECT RAISE(ABORT,'source_plan_sealed'); END;

CREATE TRIGGER p1_dependency_member_sealed BEFORE INSERT ON p1_dependency_member WHEN EXISTS(SELECT 1 FROM p1_commit WHERE plan_id=NEW.plan_id) BEGIN SELECT RAISE(ABORT,'source_plan_sealed'); END;

CREATE TRIGGER p1_execution_pin_sealed BEFORE INSERT ON p1_execution_pin WHEN EXISTS(SELECT 1 FROM p1_commit WHERE plan_id=NEW.plan_id) BEGIN SELECT RAISE(ABORT,'source_plan_sealed'); END;

CREATE TRIGGER p1_controller_sealed BEFORE INSERT ON p1_controller WHEN EXISTS(SELECT 1 FROM p1_commit WHERE plan_id=NEW.plan_id) BEGIN SELECT RAISE(ABORT,'source_plan_sealed'); END;

CREATE TRIGGER p1_preparation_member_sealed BEFORE INSERT ON p1_preparation_member WHEN EXISTS(SELECT 1 FROM p1_commit WHERE plan_id=NEW.plan_id) BEGIN SELECT RAISE(ABORT,'source_plan_sealed'); END;

CREATE TRIGGER p1_submission_member_sealed BEFORE INSERT ON p1_submission_member WHEN EXISTS(SELECT 1 FROM p1_commit WHERE plan_id=NEW.plan_id) BEGIN SELECT RAISE(ABORT,'source_plan_sealed'); END;

-- R2准备登记原子配对；真实身份、预检和正文来源仍需可信writer。
CREATE TABLE pr_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES recovery_operation(operation_id),
 run_revision TEXT NOT NULL,slot_revision TEXT NOT NULL,dependency_head INTEGER NOT NULL CHECK(dependency_head>=0),
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 65536),
 manifest_digest TEXT NOT NULL,manifest_body BLOB NOT NULL CHECK(json_valid(manifest_body)),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER pr_commit_guard BEFORE INSERT ON pr_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM recovery_operation o JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 JOIN execution e ON e.execution_id=o.execution_id JOIN recovery_preview p ON p.preview_id=o.preview_id
 WHERE o.operation_id=NEW.operation_id AND o.state='preparing' AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.active_operation_id=o.operation_id AND r.active_execution_id=o.execution_id AND r.arm_generation=e.arm_generation
 AND r.revision=NEW.run_revision AND s.revision=NEW.slot_revision AND s.active_run_id=r.run_id AND s.version=r.version
 AND p.consumed_operation_id=o.operation_id AND e.state='prepared'
 AND json_type(o.targets_body)='array' AND json_array_length(o.targets_body)=NEW.target_count
 AND NOT EXISTS(SELECT 1 FROM json_each(o.targets_body) WHERE type!='text')
 AND NEW.target_count=(SELECT count(DISTINCT value) FROM json_each(o.targets_body))
 AND NEW.target_count=(SELECT count(*) FROM preparation_target WHERE operation_id=o.operation_id)
 AND NEW.target_count=(SELECT count(*) FROM p1_preparation WHERE recovery_operation_id=o.operation_id)
 AND EXISTS(SELECT 1 FROM p1_limit WHERE singleton=1 AND NEW.target_count<=max_targets)
 AND NOT EXISTS(SELECT value FROM json_each(o.targets_body) EXCEPT SELECT controller_id FROM preparation_target WHERE operation_id=o.operation_id)
 AND NEW.dependency_head=(SELECT coalesce(max(sequence),0) FROM p1_dependency)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=r.run_id AND substr('00000000000000000000'||r.arm_generation,-20)<=d.generation)
 AND json_extract(NEW.manifest_body,'$.operation_id') IS o.operation_id
 AND json_extract(NEW.manifest_body,'$.run_id') IS o.run_id
 AND json_extract(NEW.manifest_body,'$.execution_id') IS o.execution_id
 AND json_extract(NEW.manifest_body,'$.generation') IS r.arm_generation
 AND json_type(NEW.manifest_body,'$.registrations')='array'
 AND json_array_length(NEW.manifest_body,'$.registrations')=NEW.target_count)
 THEN RAISE(ABORT,'recovery_registration_seal') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM p1_preparation p JOIN preparation_target t
 ON t.operation_id=p.recovery_operation_id AND t.controller_id=p.recovery_controller_id
 WHERE p.recovery_operation_id=NEW.operation_id AND (p.mode!='recovery' OR t.state!='pending'
 OR json_extract(t.target_body,'$.controller_id') IS NOT p.recovery_controller_id
 OR json_extract(t.target_body,'$.registration_id') IS NOT p.registration_id
 OR json_extract(t.target_body,'$.preparation_id') IS NOT p.preparation_id
 OR json_extract(t.target_body,'$.controller_scope.authority_service_id') IS NOT p.controller_authority
 OR json_extract(t.target_body,'$.controller_scope.database_instance_id') IS NOT p.controller_database
 OR CAST(json_extract(t.target_body,'$.request_body') AS BLOB) IS NOT p.request_body))
 OR EXISTS(SELECT registration_id,CAST(binding_body AS TEXT) FROM p1_preparation WHERE recovery_operation_id=NEW.operation_id
 EXCEPT SELECT json_extract(value,'$.registration_id'),json_extract(value,'$.binding') FROM json_each(NEW.manifest_body,'$.registrations'))
 OR EXISTS(SELECT json_extract(value,'$.registration_id'),json_extract(value,'$.binding') FROM json_each(NEW.manifest_body,'$.registrations')
 EXCEPT SELECT registration_id,CAST(binding_body AS TEXT) FROM p1_preparation WHERE recovery_operation_id=NEW.operation_id)
 THEN RAISE(ABORT,'recovery_registration_members') END;
END;
CREATE TRIGGER pr_target_sealed BEFORE INSERT ON preparation_target
 WHEN EXISTS(SELECT 1 FROM pr_commit WHERE operation_id=NEW.operation_id)
 BEGIN SELECT RAISE(ABORT,'recovery_registration_sealed'); END;
CREATE TRIGGER pr_registration_sealed BEFORE INSERT ON p1_preparation
 WHEN NEW.mode='recovery' AND EXISTS(SELECT 1 FROM pr_commit WHERE operation_id=NEW.recovery_operation_id)
 BEGIN SELECT RAISE(ABORT,'recovery_registration_sealed'); END;

CREATE TABLE pr_attempt(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_preparation(registration_id),
 attempt_id TEXT NOT NULL UNIQUE,request_digest TEXT NOT NULL,binding_body BLOB NOT NULL,
 runtime_body BLOB NOT NULL CHECK(length(runtime_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER pr_attempt_guard BEFORE INSERT ON pr_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pr_commit k ON k.operation_id=p.recovery_operation_id
 JOIN recovery_operation o ON o.operation_id=k.operation_id JOIN run r ON r.run_id=p.run_id
 JOIN preparation_target t ON t.operation_id=o.operation_id AND t.controller_id=p.recovery_controller_id
 WHERE p.registration_id=NEW.registration_id AND p.request_digest=NEW.request_digest AND p.binding_body=NEW.binding_body
 AND o.state='preparing' AND t.state='pending' AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.active_operation_id=o.operation_id AND r.active_execution_id=p.execution_id AND r.arm_generation=p.generation
 AND NOT EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=r.run_id AND substr('00000000000000000000'||p.generation,-20)<=d.generation)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized'))
 THEN RAISE(ABORT,'preparation_attempt_ineligible') END;
END;
CREATE TABLE pr_receipt(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES pr_attempt(registration_id),
 operation_id TEXT NOT NULL,controller_id TEXT NOT NULL,evidence_id TEXT NOT NULL UNIQUE REFERENCES external_evidence(evidence_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 FOREIGN KEY(operation_id,controller_id,evidence_id) REFERENCES preparation_target(operation_id,controller_id,receipt_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER pr_receipt_guard BEFORE INSERT ON pr_receipt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN external_evidence e ON e.evidence_id=NEW.evidence_id
 WHERE p.registration_id=NEW.registration_id AND p.recovery_operation_id=NEW.operation_id AND p.recovery_controller_id=NEW.controller_id
 AND e.kind='preparation' AND e.authority_id=p.controller_authority AND e.database_id=p.controller_database
 AND json_extract(e.body,'$.state')='applied'
 AND CAST(json_extract(e.body,'$.binding') AS BLOB)=p.binding_body
 AND json_extract(e.body,'$.applied_receipt_ref.id') IS e.object_id
 AND json_extract(e.body,'$.preparation_revision') IS e.revision
 AND json_extract(e.body,'$.observation_digest') IS e.digest)
 THEN RAISE(ABORT,'preparation_receipt_binding') END;
END;
CREATE TRIGGER pr_target_receipt BEFORE UPDATE ON preparation_target WHEN NEW.state='applied' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pr_receipt WHERE operation_id=NEW.operation_id AND controller_id=NEW.controller_id AND evidence_id=NEW.receipt_id)
 THEN RAISE(ABORT,'preparation_adoption_required') END;
END;
CREATE TRIGGER pr_target_initial BEFORE INSERT ON preparation_target WHEN NEW.state!='pending' OR NEW.receipt_id IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'preparation_initial_pending'); END;
CREATE VIEW pr_recovery_inventory AS SELECT p.registration_id,p.recovery_operation_id AS operation_id,p.run_id,p.generation,
 CASE WHEN EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=p.run_id AND substr('00000000000000000000'||p.generation,-20)<=d.generation)
 THEN 'protected_query_only' WHEN EXISTS(SELECT 1 FROM pr_receipt q WHERE q.registration_id=p.registration_id) THEN 'historical_receipt'
 WHEN EXISTS(SELECT 1 FROM pr_attempt a WHERE a.registration_id=p.registration_id) THEN 'query_only' ELSE 'unattempted' END AS classification
 FROM p1_preparation p JOIN pr_commit k ON k.operation_id=p.recovery_operation_id;
CREATE TRIGGER pr_start_source_guard BEFORE INSERT ON execution_start WHEN
 EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source s USING(source_id) WHERE d.run_id=NEW.run_id AND s.state!='synchronized')
 OR NOT EXISTS(SELECT 1 FROM pr_commit WHERE operation_id=NEW.operation_id)
 OR EXISTS(SELECT 1 FROM preparation_target t WHERE t.operation_id=NEW.operation_id AND (t.state!='applied' OR NOT EXISTS(
 SELECT 1 FROM pr_receipt q WHERE q.operation_id=t.operation_id AND q.controller_id=t.controller_id AND q.evidence_id=t.receipt_id)))
 BEGIN SELECT RAISE(ABORT,'recovery_source_unqualified'); END;
CREATE TRIGGER pr_ready_guard BEFORE UPDATE ON recovery_operation WHEN NEW.state='ready' AND (
 NOT EXISTS(SELECT 1 FROM pr_commit WHERE operation_id=NEW.operation_id)
 OR EXISTS(SELECT 1 FROM preparation_target t WHERE t.operation_id=NEW.operation_id AND (t.state!='applied' OR NOT EXISTS(
 SELECT 1 FROM pr_receipt q WHERE q.operation_id=t.operation_id AND q.controller_id=t.controller_id AND q.evidence_id=t.receipt_id))))
 BEGIN SELECT RAISE(ABORT,'recovery_preparations_incomplete'); END;

CREATE TRIGGER pr_commit_u BEFORE UPDATE ON pr_commit BEGIN SELECT RAISE(ABORT,'immutable_preparation_registration'); END;

CREATE TRIGGER pr_commit_d BEFORE DELETE ON pr_commit BEGIN SELECT RAISE(ABORT,'immutable_preparation_registration'); END;

CREATE TRIGGER pr_attempt_u BEFORE UPDATE ON pr_attempt BEGIN SELECT RAISE(ABORT,'immutable_preparation_registration'); END;

CREATE TRIGGER pr_attempt_d BEFORE DELETE ON pr_attempt BEGIN SELECT RAISE(ABORT,'immutable_preparation_registration'); END;

CREATE TRIGGER pr_receipt_u BEFORE UPDATE ON pr_receipt BEGIN SELECT RAISE(ABORT,'immutable_preparation_registration'); END;

CREATE TRIGGER pr_receipt_d BEFORE DELETE ON pr_receipt BEGIN SELECT RAISE(ABORT,'immutable_preparation_registration'); END;

-- 准备资格失效独立于事件来源故障；共享保护接收器，不伪造ingress_source状态。
CREATE TABLE protection_plan_registry(
 plan_id TEXT PRIMARY KEY NOT NULL,source_plan TEXT UNIQUE REFERENCES p1_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 preparation_plan TEXT UNIQUE REFERENCES pq_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 arm_exit_plan TEXT UNIQUE REFERENCES aa_attempt(plan_id) DEFERRABLE INITIALLY DEFERRED,
 failure_plan TEXT UNIQUE REFERENCES sf_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 retry_plan TEXT UNIQUE REFERENCES sr_attempt(plan_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((source_plan IS NOT NULL)+(preparation_plan IS NOT NULL)+(arm_exit_plan IS NOT NULL)+(failure_plan IS NOT NULL)+(retry_plan IS NOT NULL)=1),
 CHECK(coalesce(source_plan,preparation_plan,arm_exit_plan,failure_plan,retry_plan)=plan_id),
 FOREIGN KEY(plan_id) REFERENCES pb_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER pq_register_source AFTER INSERT ON p1_plan BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NEW.plan_id,NULL,NULL,NULL,NULL); END;
CREATE TABLE pq_observation(
 registration_id TEXT NOT NULL REFERENCES p1_preparation(registration_id),revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 4),
 protection_revision INTEGER NOT NULL CHECK(protection_revision BETWEEN 0 AND 2),
 state TEXT NOT NULL CHECK(state IN ('accepted','applied','rejected','indeterminate','closing','closed')),
 binding_body BLOB NOT NULL,observation_digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16384),
 fault_registration TEXT GENERATED ALWAYS AS(CASE WHEN state NOT IN ('accepted','applied') THEN registration_id ELSE NULL END) STORED
 REFERENCES pq_fault(registration_id) DEFERRABLE INITIALLY DEFERRED,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0),
 PRIMARY KEY(registration_id,revision,protection_revision)
) STRICT;
CREATE TRIGGER pq_observation_guard BEFORE INSERT ON pq_observation WHEN NOT EXISTS(
 SELECT 1 FROM p1_preparation p WHERE p.registration_id=NEW.registration_id AND p.binding_body=NEW.binding_body
 AND CAST(json_extract(NEW.body,'$.binding') AS BLOB)=p.binding_body
 AND json_extract(NEW.body,'$.state') IS NEW.state AND json_extract(NEW.body,'$.preparation_revision') IS CAST(NEW.revision AS TEXT)
 AND json_extract(NEW.body,'$.protection_revision') IS CAST(NEW.protection_revision AS TEXT)
 AND json_extract(NEW.body,'$.observation_digest') IS NEW.observation_digest)
 BEGIN SELECT RAISE(ABORT,'qualification_observation_binding'); END;
CREATE TABLE pq_fault(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_preparation(registration_id),
 kind TEXT NOT NULL CHECK(kind IN ('conflict','unavailable','withdrawal')),
 evidence_digest TEXT NOT NULL,evidence_body BLOB NOT NULL CHECK(length(evidence_body) BETWEEN 1 AND 16384),
 plan_id TEXT NOT NULL UNIQUE REFERENCES pq_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(registration_id,plan_id)
) STRICT;
CREATE TRIGGER pq_fault_guard BEFORE INSERT ON pq_fault WHEN NOT EXISTS(
 SELECT 1 FROM p1_preparation p WHERE p.registration_id=NEW.registration_id AND CAST(json_extract(NEW.evidence_body,'$.binding') AS BLOB)=p.binding_body)
 BEGIN SELECT RAISE(ABORT,'qualification_fault_binding'); END;
CREATE TABLE pq_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,registration_id TEXT NOT NULL UNIQUE,run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 current_generation TEXT NOT NULL,revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,lifecycle_before TEXT NOT NULL,
 preparation_head INTEGER NOT NULL CHECK(preparation_head>=0),target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 65536),
 latch_id TEXT UNIQUE REFERENCES pause_latch(latch_id) DEFERRABLE INITIALLY DEFERRED,
 members_body BLOB NOT NULL CHECK(json_valid(members_body)),plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(registration_id,plan_id) REFERENCES pq_fault(registration_id,plan_id),
 FOREIGN KEY(plan_id) REFERENCES pq_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER pq_plan_guard BEFORE INSERT ON pq_plan BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM run r JOIN p1_preparation p ON p.run_id=r.run_id WHERE p.registration_id=NEW.registration_id
 AND p.run_id=NEW.run_id AND p.generation=NEW.generation AND r.arm_generation=NEW.current_generation
 AND (length(NEW.generation),NEW.generation COLLATE BINARY)<=(length(r.arm_generation),r.arm_generation COLLATE BINARY)
 AND r.revision=NEW.revision_before AND r.lifecycle=NEW.lifecycle_before)
 OR (NEW.current_generation=NEW.generation AND NEW.latch_id IS NULL)
 OR (NEW.current_generation!=NEW.generation AND NEW.latch_id IS NOT NULL)
 OR ((NEW.current_generation!=NEW.generation OR NEW.lifecycle_before='completed') AND NEW.revision_after!=NEW.revision_before)
 OR (NEW.current_generation=NEW.generation AND NEW.lifecycle_before!='completed' AND (NEW.revision_before='99999999999999999999' OR NEW.revision_after!=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10) AS INTEGER)+1)%10000000000),'0')))
 THEN RAISE(ABORT,'qualification_plan_prestate') END;
END;
CREATE TRIGGER pq_register_plan AFTER INSERT ON pq_plan BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NEW.plan_id,NULL,NULL,NULL); END;
CREATE TABLE pq_target(
 plan_id TEXT NOT NULL REFERENCES pq_plan(plan_id),target_id TEXT NOT NULL,controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,
 binding_body BLOB NOT NULL,dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,controller_authority,controller_database),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER pq_target_guard BEFORE INSERT ON pq_target BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pq_commit WHERE plan_id=NEW.plan_id) OR NOT EXISTS(
 SELECT 1 FROM pq_plan p JOIN storage_scope s ON s.singleton=1 WHERE p.plan_id=NEW.plan_id
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.run_id') IS p.run_id AND json_extract(NEW.binding_body,'$.deny_through_generation') IS p.generation
 AND json_extract(NEW.binding_body,'$.operation_id') IS NEW.target_id
 AND json_extract(NEW.binding_body,'$.target_set_digest') IS p.plan_digest)
 THEN RAISE(ABORT,'qualification_target_binding') END;
END;
CREATE VIEW pq_expected_preparation AS SELECT q.plan_id,p.registration_id,p.controller_authority,p.controller_database
 FROM pq_plan q JOIN p1_preparation p USING(run_id) WHERE (length(p.generation),p.generation COLLATE BINARY)<=(length(q.generation),q.generation COLLATE BINARY);
CREATE VIEW pq_expected_submission AS SELECT q.plan_id,s.submission_id,s.target_authority AS controller_authority,s.target_database AS controller_database
 FROM pq_plan q JOIN command_submission s USING(run_id) JOIN execution e USING(execution_id)
 WHERE (length(e.arm_generation),e.arm_generation COLLATE BINARY)<=(length(q.generation),q.generation COLLATE BINARY);
CREATE VIEW pq_expected_execution AS SELECT q.plan_id,e.execution_id,e.binding_digest FROM pq_plan q JOIN execution e USING(run_id)
 WHERE (length(e.arm_generation),e.arm_generation COLLATE BINARY)<=(length(q.generation),q.generation COLLATE BINARY);
CREATE VIEW pq_expected_target AS SELECT plan_id,controller_authority,controller_database FROM pq_expected_preparation
 UNION SELECT plan_id,controller_authority,controller_database FROM pq_expected_submission;
CREATE TABLE pq_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES pq_plan(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER pq_commit_guard BEFORE INSERT ON pq_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pq_plan p JOIN run r USING(run_id) JOIN p1_limit l ON l.singleton=1
 WHERE p.plan_id=NEW.plan_id AND r.revision=p.revision_after AND r.arm_generation=p.current_generation
 AND p.preparation_head=(SELECT coalesce(max(sequence),0) FROM p1_preparation)
 AND ((p.current_generation!=p.generation AND r.lifecycle=p.lifecycle_before) OR(p.current_generation=p.generation
 AND r.lifecycle=CASE WHEN p.lifecycle_before='completed' THEN 'completed' ELSE 'paused' END AND r.dispatch_eligible=0
 AND EXISTS(SELECT 1 FROM pause_latch x WHERE x.latch_id=p.latch_id AND x.run_id=p.run_id AND x.reason='preparation_qualification'
 AND x.created_revision=p.revision_after AND x.cleared_start_id IS NULL)))
 AND p.target_count=(SELECT count(*) FROM pq_target WHERE plan_id=p.plan_id) AND p.target_count<=l.max_targets
 AND (SELECT count(*) FROM pq_plan)<=l.max_preparations
 AND length(p.members_body)+length(p.plan_body)+length(NEW.audit_body)+length(NEW.notification_body)
 +coalesce((SELECT sum(length(binding_body)+length(dispatch_body)) FROM pq_target WHERE plan_id=p.plan_id),0)<=l.max_payload_bytes
 AND json_type(p.members_body,'$.preparations')='array' AND json_type(p.members_body,'$.submissions')='array' AND json_type(p.members_body,'$.executions')='array'
 AND json_array_length(p.members_body,'$.preparations')=(SELECT count(*) FROM pq_expected_preparation WHERE plan_id=p.plan_id)
 AND json_array_length(p.members_body,'$.submissions')=(SELECT count(*) FROM pq_expected_submission WHERE plan_id=p.plan_id)
 AND json_array_length(p.members_body,'$.executions')=(SELECT count(*) FROM pq_expected_execution WHERE plan_id=p.plan_id))
 THEN RAISE(ABORT,'qualification_seal_projection_or_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT controller_authority,controller_database FROM pq_expected_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM pq_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT controller_authority,controller_database FROM pq_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM pq_expected_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT registration_id FROM pq_expected_preparation WHERE plan_id=NEW.plan_id
 EXCEPT SELECT value FROM pq_plan p,json_each(p.members_body,'$.preparations') WHERE p.plan_id=NEW.plan_id)
 OR EXISTS(SELECT submission_id FROM pq_expected_submission WHERE plan_id=NEW.plan_id
 EXCEPT SELECT value FROM pq_plan p,json_each(p.members_body,'$.submissions') WHERE p.plan_id=NEW.plan_id)
 OR EXISTS(SELECT execution_id,binding_digest FROM pq_expected_execution WHERE plan_id=NEW.plan_id
 EXCEPT SELECT json_extract(value,'$.execution_id'),json_extract(value,'$.binding_digest') FROM pq_plan p,json_each(p.members_body,'$.executions') WHERE p.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'qualification_complete_set') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sp_plan s JOIN sp_plan_commit c USING(plan_id) JOIN pq_plan p USING(plan_id)
 WHERE s.plan_id=NEW.plan_id AND s.target_count=p.target_count AND s.plan_digest=p.plan_digest AND s.plan_body=p.plan_body)
 OR EXISTS(SELECT target_id,binding_body FROM pq_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM pq_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'qualification_receiver_plan') END;
END;
CREATE VIEW pq_latest AS SELECT o.* FROM pq_observation o WHERE NOT EXISTS(SELECT 1 FROM pq_observation n
 WHERE n.registration_id=o.registration_id AND (n.revision>o.revision OR(n.revision=o.revision AND n.protection_revision>o.protection_revision)));
CREATE VIEW pq_current AS SELECT p.registration_id,p.run_id,p.generation,o.revision,o.protection_revision,
 CASE WHEN EXISTS(SELECT 1 FROM pq_fault f WHERE f.registration_id=p.registration_id) THEN 'invalidated'
 WHEN o.state='applied' THEN 'observed_applied' ELSE 'pending' END AS qualification FROM p1_preparation p LEFT JOIN pq_latest o USING(registration_id);
CREATE VIEW pq_pending_protection AS SELECT t.* FROM pq_target t JOIN pq_commit c USING(plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=t.plan_id AND o.target_id=t.target_id AND o.state='applied');

CREATE TRIGGER protection_plan_registry_u BEFORE UPDATE ON protection_plan_registry BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER protection_plan_registry_d BEFORE DELETE ON protection_plan_registry BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_observation_u BEFORE UPDATE ON pq_observation BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_observation_d BEFORE DELETE ON pq_observation BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_fault_u BEFORE UPDATE ON pq_fault BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_fault_d BEFORE DELETE ON pq_fault BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_plan_u BEFORE UPDATE ON pq_plan BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_plan_d BEFORE DELETE ON pq_plan BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_target_u BEFORE UPDATE ON pq_target BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_target_d BEFORE DELETE ON pq_target BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_commit_u BEFORE UPDATE ON pq_commit BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_commit_d BEFORE DELETE ON pq_commit BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;

CREATE TRIGGER pq_gate_execution_start BEFORE INSERT ON execution_start WHEN EXISTS(
 SELECT 1 FROM execution e JOIN p1_preparation p ON p.run_id=e.run_id AND p.generation=e.arm_generation
 JOIN pq_current q USING(registration_id) WHERE e.execution_id=NEW.execution_id AND q.qualification!='observed_applied')
 OR EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id) WHERE e.execution_id=NEW.execution_id
 AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;

CREATE TRIGGER pq_gate_step_ready BEFORE INSERT ON step_ready WHEN EXISTS(
 SELECT 1 FROM execution e JOIN p1_preparation p ON p.run_id=e.run_id AND p.generation=e.arm_generation
 JOIN pq_current q USING(registration_id) WHERE e.execution_id=NEW.execution_id AND q.qualification!='observed_applied')
 OR EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id) WHERE e.execution_id=NEW.execution_id
 AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;

CREATE TRIGGER pq_gate_command_submission BEFORE INSERT ON command_submission WHEN EXISTS(
 SELECT 1 FROM execution e JOIN p1_preparation p ON p.run_id=e.run_id AND p.generation=e.arm_generation
 JOIN pq_current q USING(registration_id) WHERE e.execution_id=NEW.execution_id AND q.qualification!='observed_applied')
 OR EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id) WHERE e.execution_id=NEW.execution_id
 AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;

CREATE TRIGGER pq_gate_transition_commit BEFORE INSERT ON transition_commit WHEN EXISTS(
 SELECT 1 FROM execution e JOIN p1_preparation p ON p.run_id=e.run_id AND p.generation=e.arm_generation
 JOIN pq_current q USING(registration_id) WHERE e.execution_id=NEW.execution_id AND q.qualification!='observed_applied')
 OR EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id) WHERE e.execution_id=NEW.execution_id
 AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;
CREATE TRIGGER pq_gate_attempt BEFORE INSERT ON submission_attempt WHEN EXISTS(
 SELECT 1 FROM command_submission s JOIN execution e USING(execution_id) JOIN p1_preparation p ON p.run_id=e.run_id AND p.generation=e.arm_generation
 JOIN pq_current q USING(registration_id) WHERE s.submission_id=NEW.submission_id AND q.qualification!='observed_applied')
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;
CREATE TRIGGER pq_gate_ready BEFORE UPDATE ON recovery_operation WHEN NEW.state='ready' AND EXISTS(
 SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.recovery_operation_id=NEW.operation_id AND q.qualification!='observed_applied')
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;
CREATE TRIGGER pq_gate_adoption BEFORE INSERT ON pr_receipt WHEN NOT EXISTS(
 SELECT 1 FROM pq_current q WHERE q.registration_id=NEW.registration_id AND q.qualification='observed_applied')
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;

-- 普通布防保持disarmed直到全目标准备完成。此布局不承担真实提供者与物理磁盘证明。
CREATE TABLE lifecycle_operation_identity(
 operation_id TEXT PRIMARY KEY NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),kind TEXT NOT NULL CHECK(kind IN ('arm','recovery')),
 arm_id TEXT UNIQUE REFERENCES arm_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 recovery_id TEXT UNIQUE REFERENCES recovery_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(operation_id,run_id),
 CHECK((kind='arm' AND arm_id IS operation_id AND recovery_id IS NULL) OR(kind='recovery' AND recovery_id IS operation_id AND arm_id IS NULL))
) STRICT;
CREATE TRIGGER arm_identity_guard BEFORE INSERT ON lifecycle_operation_identity WHEN NOT EXISTS(
 SELECT 1 FROM arm_operation WHERE operation_id=NEW.arm_id AND run_id=NEW.run_id) AND NOT EXISTS(
 SELECT 1 FROM recovery_operation WHERE operation_id=NEW.recovery_id AND run_id=NEW.run_id)
 BEGIN SELECT RAISE(ABORT,'operation_identity_binding'); END;
CREATE TRIGGER arm_register_recovery AFTER INSERT ON recovery_operation BEGIN
 INSERT INTO lifecycle_operation_identity VALUES(NEW.operation_id,NEW.run_id,'recovery',NULL,NEW.operation_id); END;
CREATE TABLE arm_capacity(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),profile_digest TEXT NOT NULL UNIQUE,profile_body BLOB NOT NULL,
 max_operations INTEGER NOT NULL CHECK(max_operations BETWEEN 1 AND 1000000),
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000)
) STRICT;
CREATE TABLE arm_preflight(
 preflight_id TEXT PRIMARY KEY NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),run_revision TEXT NOT NULL,slot_revision TEXT NOT NULL,generation_before TEXT NOT NULL,
 artifact_digest TEXT NOT NULL,dependency_head INTEGER NOT NULL,source_body BLOB NOT NULL,targets_body BLOB NOT NULL,
 clock_body BLOB NOT NULL,issued_tick TEXT NOT NULL,expires_tick TEXT NOT NULL,preflight_digest TEXT NOT NULL,consumed_operation_id TEXT UNIQUE,
 UNIQUE(preflight_id,run_id,consumed_operation_id),
 FOREIGN KEY(consumed_operation_id,run_id,preflight_id) REFERENCES arm_operation(operation_id,run_id,preflight_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((length(issued_tick),issued_tick COLLATE BINARY)<(length(expires_tick),expires_tick COLLATE BINARY))
) STRICT;
CREATE TRIGGER arm_preflight_update BEFORE UPDATE ON arm_preflight WHEN
 NEW.preflight_id IS NOT OLD.preflight_id OR NEW.run_id IS NOT OLD.run_id OR NEW.run_revision IS NOT OLD.run_revision OR NEW.slot_revision IS NOT OLD.slot_revision
 OR NEW.generation_before IS NOT OLD.generation_before OR NEW.artifact_digest IS NOT OLD.artifact_digest OR NEW.dependency_head IS NOT OLD.dependency_head
 OR NEW.source_body IS NOT OLD.source_body OR NEW.targets_body IS NOT OLD.targets_body OR NEW.clock_body IS NOT OLD.clock_body
 OR NEW.issued_tick IS NOT OLD.issued_tick OR NEW.expires_tick IS NOT OLD.expires_tick OR NEW.preflight_digest IS NOT OLD.preflight_digest
 OR OLD.consumed_operation_id IS NOT NULL OR NEW.consumed_operation_id IS NULL
 BEGIN SELECT RAISE(ABORT,'immutable_arm_preflight'); END;
CREATE TABLE arm_operation(
 operation_id TEXT PRIMARY KEY NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),preflight_id TEXT NOT NULL UNIQUE,
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,request_digest TEXT NOT NULL,request_body BLOB NOT NULL,
 run_before TEXT NOT NULL,run_after TEXT NOT NULL,slot_before TEXT NOT NULL,slot_after TEXT NOT NULL,generation_before TEXT NOT NULL,generation TEXT NOT NULL,
 clock_body BLOB NOT NULL,now_tick TEXT NOT NULL,target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),
 UNIQUE(operation_id,run_id,preflight_id),UNIQUE(operation_id,run_id),UNIQUE(run_id,generation),UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(preflight_id,run_id,operation_id) REFERENCES arm_preflight(preflight_id,run_id,consumed_operation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id) REFERENCES arm_register_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id) REFERENCES arm_budget_reservation(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER arm_operation_guard BEFORE INSERT ON arm_operation WHEN NOT EXISTS(
 SELECT 1 FROM run r JOIN activation_slot s USING(definition_id) JOIN published_version v USING(definition_id,version)
 JOIN arm_preflight p ON p.preflight_id=NEW.preflight_id WHERE r.run_id=NEW.run_id AND p.run_id=r.run_id
 AND r.lifecycle='disarmed' AND r.dispatch_eligible=0 AND r.active_operation_id IS NULL AND r.active_execution_id IS NULL
 AND (s.active_run_id IS NULL OR(s.active_run_id=r.run_id AND s.version=r.version))
 AND r.revision=NEW.run_before AND r.revision=p.run_revision AND s.revision=NEW.slot_before AND s.revision=p.slot_revision
 AND r.arm_generation=NEW.generation_before AND r.arm_generation=p.generation_before AND p.artifact_digest=v.artifact_digest
 AND NEW.run_before!='99999999999999999999' AND NEW.slot_before!='99999999999999999999' AND NEW.generation_before!='99999999999999999999'
 AND NEW.run_after=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.run_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.run_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.run_before,-20),11,10) AS INTEGER)+1)%10000000000),'0') AND NEW.slot_after=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.slot_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.slot_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.slot_before,-20),11,10) AS INTEGER)+1)%10000000000),'0') AND NEW.generation=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.generation_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.generation_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.generation_before,-20),11,10) AS INTEGER)+1)%10000000000),'0')
 AND p.consumed_operation_id IS NULL AND NEW.clock_body=p.clock_body
 AND (length(NEW.now_tick),NEW.now_tick COLLATE BINARY)>=(length(p.issued_tick),p.issued_tick COLLATE BINARY)
 AND (length(NEW.now_tick),NEW.now_tick COLLATE BINARY)<(length(p.expires_tick),p.expires_tick COLLATE BINARY)
 AND json_type(p.targets_body)='array' AND json_array_length(p.targets_body)=NEW.target_count
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL))
 BEGIN SELECT RAISE(ABORT,'arm_prestate'); END;
CREATE TRIGGER arm_register_identity AFTER INSERT ON arm_operation BEGIN
 INSERT INTO lifecycle_operation_identity VALUES(NEW.operation_id,NEW.run_id,'arm',NEW.operation_id,NULL); END;
CREATE TABLE arm_budget_reservation(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_operation(operation_id),profile_digest TEXT NOT NULL REFERENCES arm_capacity(profile_digest),
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 budget_body BLOB NOT NULL CHECK(length(budget_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER arm_budget_guard BEFORE INSERT ON arm_budget_reservation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM arm_capacity c JOIN arm_operation o ON o.operation_id=NEW.operation_id JOIN storage_scope sc ON sc.singleton=1
 WHERE c.profile_digest=NEW.profile_digest AND (SELECT count(*) FROM protection_budget_reservation)<c.max_operations
 AND NEW.logical_rows+coalesce((SELECT sum(logical_rows) FROM protection_budget_reservation),0)<=c.logical_rows
 AND NEW.logical_bytes+coalesce((SELECT sum(logical_bytes) FROM protection_budget_reservation),0)<=c.logical_bytes
 AND NEW.queue_slots+coalesce((SELECT sum(queue_slots) FROM protection_budget_reservation),0)<=c.queue_slots
 AND NEW.work_units+coalesce((SELECT sum(work_units) FROM protection_budget_reservation),0)<=c.work_units
 AND json_extract(NEW.budget_body,'$.binding.operation_id') IS o.operation_id AND json_extract(NEW.budget_body,'$.binding.run_id') IS o.run_id
 AND json_extract(NEW.budget_body,'$.binding.generation') IS o.generation AND json_extract(NEW.budget_body,'$.binding.profile_digest') IS c.profile_digest
 AND json_extract(NEW.budget_body,'$.binding.scope.authority_service_id') IS sc.authority_id
 AND json_extract(NEW.budget_body,'$.binding.scope.database_instance_id') IS sc.database_id
 AND json_extract(NEW.budget_body,'$.state')='held'
 AND json_extract(NEW.budget_body,'$.held.logical_rows') IS CAST(NEW.logical_rows AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.logical_bytes') IS CAST(NEW.logical_bytes AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.queue_slots') IS CAST(NEW.queue_slots AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.work_units') IS CAST(NEW.work_units AS TEXT)) THEN RAISE(ABORT,'arm_budget_binding_or_capacity') END;
 SELECT CASE WHEN (SELECT count(*) FROM json_each(NEW.budget_body,'$.binding.forecast'))!=6 OR EXISTS(
 SELECT 1 FROM json_each(NEW.budget_body,'$.binding.forecast') f JOIN arm_capacity c ON c.profile_digest=NEW.profile_digest
 WHERE f.key NOT IN ('dependencies','runs','executions','preparations','submissions','controller_targets') OR f.type!='text'
 OR f.value!=CAST(CAST(f.value AS INTEGER) AS TEXT) OR CAST(f.value AS INTEGER) NOT BETWEEN 0 AND 65536
 OR CAST(f.value AS INTEGER)>CAST(json_extract(c.profile_body,'$.max_shape.'||f.key) AS INTEGER))
 THEN RAISE(ABORT,'arm_budget_shape') END;
 SELECT CASE WHEN NOT EXISTS(WITH x AS(SELECT
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.dependencies') AS INTEGER) AS d,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.runs') AS INTEGER) AS r,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.executions') AS INTEGER) AS e,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.preparations') AS INTEGER) AS p,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.submissions') AS INTEGER) AS s,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.controller_targets') AS INTEGER) AS t,
 CAST(json_extract(profile_body,'$.episodes') AS INTEGER) AS n,CAST(json_extract(profile_body,'$.max_row_bytes') AS INTEGER) AS m
 FROM arm_capacity WHERE profile_digest=NEW.profile_digest), y AS(SELECT *,32+3*d+6*r+3*e+132*p+3*s+68*t AS rows FROM x)
 SELECT 1 FROM y WHERE r>=1 AND n BETWEEN 1 AND 1024 AND m BETWEEN 1 AND 1048576
 AND NEW.logical_rows=rows*n AND NEW.logical_bytes=rows*(m+512)*n AND NEW.queue_slots=(2*t+p+1)*n AND NEW.work_units=(rows+d+r+e+p+s+t)*n
 AND json_extract(NEW.budget_body,'$.episodes_left') IS CAST(n AS TEXT)
 AND json_extract(NEW.budget_body,'$.spent.logical_rows')='0' AND json_extract(NEW.budget_body,'$.spent.logical_bytes')='0'
 AND json_extract(NEW.budget_body,'$.spent.queue_slots')='0' AND json_extract(NEW.budget_body,'$.spent.work_units')='0')
 THEN RAISE(ABORT,'arm_budget_cost') END;
END;
CREATE TABLE arm_target(
 operation_id TEXT NOT NULL REFERENCES arm_operation(operation_id),controller_id TEXT NOT NULL,registration_id TEXT NOT NULL UNIQUE,
 target_body BLOB NOT NULL,PRIMARY KEY(operation_id,controller_id),
 FOREIGN KEY(registration_id) REFERENCES p1_preparation(registration_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(operation_id,controller_id) REFERENCES p1_preparation(arm_operation_id,arm_controller_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER arm_target_guard BEFORE INSERT ON arm_target WHEN EXISTS(SELECT 1 FROM arm_register_commit WHERE operation_id=NEW.operation_id)
 BEGIN SELECT RAISE(ABORT,'arm_targets_sealed'); END;
CREATE TABLE arm_register_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_operation(operation_id),manifest_body BLOB NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE VIEW arm_sources_current AS SELECT o.operation_id FROM arm_operation o JOIN arm_preflight p USING(preflight_id)
 WHERE p.dependency_head=(SELECT coalesce(max(sequence),0) FROM p1_dependency)
 AND json_type(p.source_body)='array' AND json_array_length(p.source_body)=(SELECT count(DISTINCT source_id) FROM p1_dependency WHERE run_id=o.run_id)
 AND NOT EXISTS(SELECT source_id,revision,state FROM ingress_source WHERE source_id IN (SELECT source_id FROM p1_dependency WHERE run_id=o.run_id)
 EXCEPT SELECT json_extract(value,'$.source_id'),json_extract(value,'$.revision'),json_extract(value,'$.state') FROM json_each(p.source_body))
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source s USING(source_id) WHERE d.run_id=o.run_id AND s.state!='synchronized');
CREATE TRIGGER arm_register_guard BEFORE INSERT ON arm_register_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM arm_operation o JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 JOIN arm_preflight f USING(preflight_id) JOIN arm_budget_reservation b USING(operation_id) JOIN arm_sources_current c USING(operation_id)
 WHERE o.operation_id=NEW.operation_id AND r.lifecycle='disarmed' AND r.dispatch_eligible=0 AND r.active_operation_id=o.operation_id
 AND r.active_execution_id IS NULL AND r.revision=o.run_after AND r.arm_generation=o.generation
 AND s.revision=o.slot_after AND s.active_run_id=r.run_id AND s.version=r.version AND f.consumed_operation_id=o.operation_id
 AND o.target_count=(SELECT count(*) FROM arm_target WHERE operation_id=o.operation_id)
 AND o.target_count=(SELECT count(*) FROM p1_preparation WHERE arm_operation_id=o.operation_id)
 AND json_type(NEW.manifest_body)='array' AND json_array_length(NEW.manifest_body)=o.target_count
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.preparations') AS INTEGER)>=(SELECT count(*) FROM p1_preparation WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.dependencies') AS INTEGER)>=(SELECT count(*) FROM p1_dependency WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.executions') AS INTEGER)>=(SELECT count(*) FROM execution WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.submissions') AS INTEGER)>=(SELECT count(*) FROM command_submission WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.controller_targets') AS INTEGER)>=(SELECT count(*) FROM (
 SELECT controller_authority,controller_database FROM p1_preparation WHERE run_id=o.run_id
 UNION SELECT target_authority,target_database FROM command_submission WHERE run_id=o.run_id))
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||o.generation,-20)<=generation)
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL)) THEN RAISE(ABORT,'arm_register_projection') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM arm_target t JOIN p1_preparation p ON p.registration_id=t.registration_id
 WHERE t.operation_id=NEW.operation_id AND (p.arm_operation_id!=t.operation_id OR p.arm_controller_id!=t.controller_id
 OR p.mode!='arm' OR p.execution_id IS NOT NULL OR json_extract(t.target_body,'$.registration_id') IS NOT p.registration_id
 OR json_extract(t.target_body,'$.preparation_id') IS NOT p.preparation_id OR json_extract(t.target_body,'$.controller_id') IS NOT t.controller_id
 OR json_extract(t.target_body,'$.controller_scope.authority_service_id') IS NOT p.controller_authority
 OR json_extract(t.target_body,'$.controller_scope.database_instance_id') IS NOT p.controller_database
 OR CAST(json_extract(t.target_body,'$.request_body') AS BLOB) IS NOT p.request_body))
 OR EXISTS(SELECT CAST(t.target_body AS TEXT) FROM arm_target t WHERE t.operation_id=NEW.operation_id
 EXCEPT SELECT value FROM arm_operation o JOIN arm_preflight f USING(preflight_id),json_each(f.targets_body) WHERE o.operation_id=NEW.operation_id)
 OR EXISTS(SELECT registration_id,CAST(binding_body AS TEXT) FROM p1_preparation WHERE arm_operation_id=NEW.operation_id
 EXCEPT SELECT json_extract(value,'$.registration_id'),json_extract(value,'$.binding') FROM json_each(NEW.manifest_body))
 THEN RAISE(ABORT,'arm_register_members') END;
END;
CREATE VIEW arm_pending_eligible AS SELECT o.* FROM arm_operation o JOIN arm_register_commit k USING(operation_id)
 JOIN arm_budget_reservation b USING(operation_id) JOIN arm_sources_current sc USING(operation_id)
 JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 WHERE r.lifecycle='disarmed' AND r.dispatch_eligible=0 AND r.active_execution_id IS NULL AND r.active_operation_id=o.operation_id
 AND r.arm_generation=o.generation AND r.revision=o.run_after AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=o.slot_after
 AND NOT EXISTS(SELECT 1 FROM arm_complete WHERE operation_id=o.operation_id)
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||o.generation,-20)<=generation)
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL);
CREATE TABLE arm_attempt(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_preparation(registration_id),attempt_id TEXT NOT NULL UNIQUE,
 binding_body BLOB NOT NULL,runtime_body BLOB NOT NULL CHECK(length(runtime_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER arm_attempt_guard BEFORE INSERT ON arm_attempt WHEN NOT EXISTS(
 SELECT 1 FROM p1_preparation p JOIN arm_pending_eligible o ON o.operation_id=p.arm_operation_id JOIN pq_current q USING(registration_id)
 WHERE p.registration_id=NEW.registration_id AND p.binding_body=NEW.binding_body AND q.qualification!='invalidated')
 BEGIN SELECT RAISE(ABORT,'arm_attempt_ineligible'); END;
CREATE TABLE arm_receipt(
 registration_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_attempt(registration_id),evidence_id TEXT NOT NULL UNIQUE REFERENCES external_evidence(evidence_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER arm_receipt_guard BEFORE INSERT ON arm_receipt WHEN NOT EXISTS(
 SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) JOIN external_evidence e ON e.evidence_id=NEW.evidence_id
 WHERE p.registration_id=NEW.registration_id AND p.mode='arm' AND q.qualification='observed_applied' AND e.kind='preparation'
 AND p.controller_authority=e.authority_id AND p.controller_database=e.database_id AND json_extract(e.body,'$.state')='applied'
 AND CAST(json_extract(e.body,'$.binding') AS BLOB)=p.binding_body AND json_extract(e.body,'$.applied_receipt_ref.id') IS e.object_id
 AND json_extract(e.body,'$.preparation_revision') IS e.revision AND json_extract(e.body,'$.observation_digest') IS e.digest)
 BEGIN SELECT RAISE(ABORT,'arm_receipt_binding'); END;
CREATE TABLE arm_complete(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_operation(operation_id),run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,slot_revision TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0),
 FOREIGN KEY(operation_id) REFERENCES arm_ready_commit(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER arm_complete_guard BEFORE INSERT ON arm_complete WHEN NOT EXISTS(
 SELECT 1 FROM arm_pending_eligible o WHERE o.operation_id=NEW.operation_id AND o.run_id=NEW.run_id AND o.generation=NEW.generation
 AND o.run_after=NEW.revision_before AND o.slot_after=NEW.slot_revision AND NEW.revision_before!='99999999999999999999' AND NEW.revision_after=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10) AS INTEGER)+1)%10000000000),'0')
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.arm_operation_id=o.operation_id
 AND (q.qualification!='observed_applied' OR NOT EXISTS(SELECT 1 FROM arm_receipt WHERE registration_id=p.registration_id))))
 BEGIN SELECT RAISE(ABORT,'arm_complete_unqualified'); END;
CREATE TABLE arm_ready_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_complete(operation_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER arm_ready_guard BEFORE INSERT ON arm_ready_commit WHEN NOT EXISTS(
 SELECT 1 FROM arm_complete c JOIN run r USING(run_id) JOIN arm_sources_current sc USING(operation_id)
 JOIN activation_slot s USING(definition_id) WHERE c.operation_id=NEW.operation_id
 AND r.revision=c.revision_after AND r.arm_generation=c.generation AND r.lifecycle='armed' AND r.dispatch_eligible=1
 AND r.active_operation_id IS NULL AND r.active_execution_id IS NULL
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=c.slot_revision
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||c.generation,-20)<=generation)
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.arm_operation_id=c.operation_id AND q.qualification!='observed_applied'))
 BEGIN SELECT RAISE(ABORT,'arm_ready_projection'); END;
CREATE TRIGGER arm_run_initial BEFORE INSERT ON run WHEN NEW.lifecycle!='disarmed' OR NEW.dispatch_eligible!=0 OR NEW.arm_generation!='0'
 OR NEW.active_operation_id IS NOT NULL OR NEW.active_execution_id IS NOT NULL OR NEW.last_commit_id IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'run_initial_disarmed'); END;
CREATE TRIGGER arm_run_open BEFORE UPDATE ON run WHEN NEW.dispatch_eligible=1 AND (OLD.dispatch_eligible=0 OR OLD.lifecycle='disarmed')
 AND NOT EXISTS(SELECT 1 FROM arm_complete c WHERE c.run_id=NEW.run_id AND c.operation_id=OLD.active_operation_id AND c.generation=NEW.arm_generation
 AND c.revision_before=OLD.revision AND c.revision_after=NEW.revision AND NEW.lifecycle='armed' AND NOT EXISTS(SELECT 1 FROM arm_ready_commit WHERE operation_id=c.operation_id))
 AND NOT EXISTS(SELECT 1 FROM execution_start st WHERE st.run_id=NEW.run_id AND st.execution_id=NEW.active_execution_id
 AND st.operation_id=OLD.active_operation_id AND st.run_revision_before=OLD.revision AND st.run_revision_after=NEW.revision AND NEW.lifecycle='running')
 AND NOT EXISTS(SELECT 1 FROM transition_commit c JOIN execution e USING(execution_id,run_id)
 WHERE c.run_id=NEW.run_id AND c.commit_id=NEW.last_commit_id AND NEW.last_commit_id IS NOT OLD.last_commit_id
 AND OLD.lifecycle='running' AND OLD.active_execution_id=c.execution_id AND OLD.active_operation_id IS NULL
 AND e.commit_id=c.commit_id AND e.state='succeeded' AND e.arm_generation=OLD.arm_generation AND e.arm_generation=NEW.arm_generation
 AND NEW.active_execution_id IS NULL AND NEW.active_operation_id IS NULL AND NEW.lifecycle='armed'
 AND OLD.revision!='99999999999999999999' AND NEW.revision=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||OLD.revision,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||OLD.revision,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||OLD.revision,-20),11,10) AS INTEGER)+1)%10000000000),'0'))
 BEGIN SELECT RAISE(ABORT,'dispatch_open_requires_commit'); END;
CREATE TRIGGER arm_run_armed BEFORE UPDATE ON run WHEN NEW.lifecycle='armed' AND OLD.lifecycle!='armed'
 AND NOT EXISTS(SELECT 1 FROM arm_complete c WHERE c.run_id=NEW.run_id AND c.operation_id=OLD.active_operation_id
 AND c.generation=NEW.arm_generation AND c.revision_before=OLD.revision AND c.revision_after=NEW.revision
 AND NOT EXISTS(SELECT 1 FROM arm_ready_commit WHERE operation_id=c.operation_id))
 AND NOT EXISTS(SELECT 1 FROM transition_commit c JOIN execution e USING(execution_id,run_id)
 WHERE c.run_id=NEW.run_id AND c.commit_id=NEW.last_commit_id AND NEW.last_commit_id IS NOT OLD.last_commit_id
 AND OLD.lifecycle='running' AND OLD.active_execution_id=c.execution_id AND OLD.active_operation_id IS NULL
 AND e.commit_id=c.commit_id AND e.state='succeeded' AND e.arm_generation=OLD.arm_generation AND e.arm_generation=NEW.arm_generation
 AND NEW.active_execution_id IS NULL AND NEW.active_operation_id IS NULL
 AND OLD.revision!='99999999999999999999' AND NEW.revision=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||OLD.revision,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||OLD.revision,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||OLD.revision,-20),11,10) AS INTEGER)+1)%10000000000),'0'))
 BEGIN SELECT RAISE(ABORT,'armed_requires_completion'); END;

CREATE TRIGGER arm_preflight_u20 BEFORE INSERT ON arm_preflight WHEN length(NEW.run_revision) NOT BETWEEN 1 AND 20 OR NEW.run_revision GLOB '*[^0-9]*' OR (NEW.run_revision!='0' AND substr(NEW.run_revision,1,1)='0') OR instr(NEW.run_revision,char(0))>0 OR length(NEW.slot_revision) NOT BETWEEN 1 AND 20 OR NEW.slot_revision GLOB '*[^0-9]*' OR (NEW.slot_revision!='0' AND substr(NEW.slot_revision,1,1)='0') OR instr(NEW.slot_revision,char(0))>0 OR length(NEW.generation_before) NOT BETWEEN 1 AND 20 OR NEW.generation_before GLOB '*[^0-9]*' OR (NEW.generation_before!='0' AND substr(NEW.generation_before,1,1)='0') OR instr(NEW.generation_before,char(0))>0 OR length(NEW.issued_tick) NOT BETWEEN 1 AND 20 OR NEW.issued_tick GLOB '*[^0-9]*' OR (NEW.issued_tick!='0' AND substr(NEW.issued_tick,1,1)='0') OR instr(NEW.issued_tick,char(0))>0 OR length(NEW.expires_tick) NOT BETWEEN 1 AND 20 OR NEW.expires_tick GLOB '*[^0-9]*' OR (NEW.expires_tick!='0' AND substr(NEW.expires_tick,1,1)='0') OR instr(NEW.expires_tick,char(0))>0 BEGIN SELECT RAISE(ABORT,'arm_u20'); END;

CREATE TRIGGER arm_operation_u20 BEFORE INSERT ON arm_operation WHEN length(NEW.run_before) NOT BETWEEN 1 AND 20 OR NEW.run_before GLOB '*[^0-9]*' OR (NEW.run_before!='0' AND substr(NEW.run_before,1,1)='0') OR instr(NEW.run_before,char(0))>0 OR length(NEW.run_after) NOT BETWEEN 1 AND 20 OR NEW.run_after GLOB '*[^0-9]*' OR (NEW.run_after!='0' AND substr(NEW.run_after,1,1)='0') OR instr(NEW.run_after,char(0))>0 OR length(NEW.slot_before) NOT BETWEEN 1 AND 20 OR NEW.slot_before GLOB '*[^0-9]*' OR (NEW.slot_before!='0' AND substr(NEW.slot_before,1,1)='0') OR instr(NEW.slot_before,char(0))>0 OR length(NEW.slot_after) NOT BETWEEN 1 AND 20 OR NEW.slot_after GLOB '*[^0-9]*' OR (NEW.slot_after!='0' AND substr(NEW.slot_after,1,1)='0') OR instr(NEW.slot_after,char(0))>0 OR length(NEW.generation_before) NOT BETWEEN 1 AND 20 OR NEW.generation_before GLOB '*[^0-9]*' OR (NEW.generation_before!='0' AND substr(NEW.generation_before,1,1)='0') OR instr(NEW.generation_before,char(0))>0 OR length(NEW.generation) NOT BETWEEN 1 AND 20 OR NEW.generation GLOB '*[^0-9]*' OR (NEW.generation!='0' AND substr(NEW.generation,1,1)='0') OR instr(NEW.generation,char(0))>0 OR length(NEW.now_tick) NOT BETWEEN 1 AND 20 OR NEW.now_tick GLOB '*[^0-9]*' OR (NEW.now_tick!='0' AND substr(NEW.now_tick,1,1)='0') OR instr(NEW.now_tick,char(0))>0 BEGIN SELECT RAISE(ABORT,'arm_u20'); END;

CREATE TRIGGER arm_complete_u20 BEFORE INSERT ON arm_complete WHEN length(NEW.generation) NOT BETWEEN 1 AND 20 OR NEW.generation GLOB '*[^0-9]*' OR (NEW.generation!='0' AND substr(NEW.generation,1,1)='0') OR instr(NEW.generation,char(0))>0 OR length(NEW.revision_before) NOT BETWEEN 1 AND 20 OR NEW.revision_before GLOB '*[^0-9]*' OR (NEW.revision_before!='0' AND substr(NEW.revision_before,1,1)='0') OR instr(NEW.revision_before,char(0))>0 OR length(NEW.revision_after) NOT BETWEEN 1 AND 20 OR NEW.revision_after GLOB '*[^0-9]*' OR (NEW.revision_after!='0' AND substr(NEW.revision_after,1,1)='0') OR instr(NEW.revision_after,char(0))>0 OR length(NEW.slot_revision) NOT BETWEEN 1 AND 20 OR NEW.slot_revision GLOB '*[^0-9]*' OR (NEW.slot_revision!='0' AND substr(NEW.slot_revision,1,1)='0') OR instr(NEW.slot_revision,char(0))>0 BEGIN SELECT RAISE(ABORT,'arm_u20'); END;

CREATE TRIGGER lifecycle_operation_identity_update BEFORE UPDATE ON lifecycle_operation_identity BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER lifecycle_operation_identity_delete BEFORE DELETE ON lifecycle_operation_identity BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_capacity_update BEFORE UPDATE ON arm_capacity BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_capacity_delete BEFORE DELETE ON arm_capacity BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_preflight_delete BEFORE DELETE ON arm_preflight BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_operation_update BEFORE UPDATE ON arm_operation BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_operation_delete BEFORE DELETE ON arm_operation BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_budget_reservation_update BEFORE UPDATE ON arm_budget_reservation BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_budget_reservation_delete BEFORE DELETE ON arm_budget_reservation BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_target_update BEFORE UPDATE ON arm_target BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_target_delete BEFORE DELETE ON arm_target BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_register_commit_update BEFORE UPDATE ON arm_register_commit BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_register_commit_delete BEFORE DELETE ON arm_register_commit BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_attempt_update BEFORE UPDATE ON arm_attempt BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_attempt_delete BEFORE DELETE ON arm_attempt BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_receipt_update BEFORE UPDATE ON arm_receipt BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_receipt_delete BEFORE DELETE ON arm_receipt BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_complete_update BEFORE UPDATE ON arm_complete BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_complete_delete BEFORE DELETE ON arm_complete BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_ready_commit_update BEFORE UPDATE ON arm_ready_commit BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

CREATE TRIGGER arm_ready_commit_delete BEFORE DELETE ON arm_ready_commit BEGIN SELECT RAISE(ABORT,'immutable_arm_fact'); END;

-- 布防失败退出只解除准备操作，保持paused、锁存与旧预算；不证明资源释放。
CREATE TABLE aa_stop(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES arm_operation(operation_id),run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,slot_revision TEXT NOT NULL,
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,request_digest TEXT NOT NULL,request_body BLOB NOT NULL,
 first_plan_id TEXT NOT NULL UNIQUE REFERENCES aa_attempt(plan_id) DEFERRABLE INITIALLY DEFERRED,
 inventory_body BLOB NOT NULL CHECK(json_valid(inventory_body)),latch_id TEXT NOT NULL UNIQUE REFERENCES pause_latch(latch_id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(first_plan_id,operation_id) REFERENCES aa_attempt(plan_id,operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER aa_stop_guard BEFORE INSERT ON aa_stop WHEN NOT EXISTS(
 SELECT 1 FROM arm_operation o JOIN arm_register_commit k USING(operation_id) JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 WHERE o.operation_id=NEW.operation_id AND o.run_id=NEW.run_id AND o.generation=NEW.generation AND r.arm_generation=NEW.generation
 AND r.active_operation_id=o.operation_id AND r.active_execution_id IS NULL AND r.dispatch_eligible=0 AND r.lifecycle IN ('disarmed','paused')
 AND r.revision=NEW.revision_before AND NEW.revision_before!='99999999999999999999' AND NEW.revision_after=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10) AS INTEGER)+1)%10000000000),'0')
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=NEW.slot_revision
 AND NOT EXISTS(SELECT 1 FROM arm_complete WHERE operation_id=o.operation_id))
 BEGIN SELECT RAISE(ABORT,'arm_stop_prestate'); END;
CREATE VIEW aa_expected_member AS
 SELECT a.operation_id,'preparation' AS kind,p.registration_id AS ref,hex(p.binding_body) AS body FROM aa_stop a JOIN p1_preparation p USING(run_id)
 WHERE substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION ALL SELECT a.operation_id,'execution',e.execution_id,e.binding_digest FROM aa_stop a JOIN execution e USING(run_id)
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION ALL SELECT a.operation_id,'submission',s.submission_id,hex(s.request_body) FROM aa_stop a JOIN execution e USING(run_id) JOIN command_submission s USING(execution_id)
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20);
CREATE VIEW aa_inventory_current AS SELECT a.operation_id FROM aa_stop a WHERE json_type(a.inventory_body)='array'
 AND json_array_length(a.inventory_body)=(SELECT count(*) FROM aa_expected_member m WHERE m.operation_id=a.operation_id)
 AND json_array_length(a.inventory_body)<=65536
 AND NOT EXISTS(SELECT kind,ref,body FROM aa_expected_member WHERE operation_id=a.operation_id
 EXCEPT SELECT json_extract(value,'$.kind'),json_extract(value,'$.ref'),json_extract(value,'$.body') FROM json_each(a.inventory_body));
CREATE VIEW aa_expected_target AS
 SELECT a.operation_id,p.controller_authority,p.controller_database FROM aa_stop a JOIN p1_preparation p USING(run_id)
 WHERE substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION SELECT a.operation_id,s.target_authority,s.target_database FROM aa_stop a JOIN execution e USING(run_id) JOIN command_submission s USING(execution_id)
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20);
CREATE TABLE aa_attempt(
 plan_id TEXT PRIMARY KEY NOT NULL,operation_id TEXT NOT NULL REFERENCES aa_stop(operation_id),ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 16),
 previous_plan_id TEXT REFERENCES aa_attempt(plan_id),request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL,plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL,target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),
 UNIQUE(operation_id,ordinal),UNIQUE(request_epoch,actor_body,idempotency_key),UNIQUE(plan_id,operation_id),
 CHECK((ordinal=1)=(previous_plan_id IS NULL)),
 FOREIGN KEY(plan_id) REFERENCES sp_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES aa_attempt_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER aa_attempt_guard BEFORE INSERT ON aa_attempt WHEN NOT EXISTS(
 SELECT 1 FROM aa_stop a JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id) WHERE a.operation_id=NEW.operation_id
 AND r.lifecycle='paused' AND r.dispatch_eligible=0 AND r.active_operation_id=a.operation_id AND r.active_execution_id IS NULL AND r.arm_generation=a.generation
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=a.slot_revision
 AND NOT EXISTS(SELECT 1 FROM aa_exit WHERE operation_id=a.operation_id)
 AND ((NEW.ordinal=1 AND a.first_plan_id=NEW.plan_id AND r.revision=a.revision_after
 AND NEW.request_epoch=a.request_epoch AND NEW.actor_body=a.actor_body AND NEW.idempotency_key=a.idempotency_key AND NEW.request_digest=a.request_digest AND NEW.request_body=a.request_body)
 OR EXISTS(SELECT 1 FROM aa_attempt p JOIN aa_attempt_commit c USING(plan_id) JOIN sp_observed_summary x USING(plan_id)
 WHERE p.plan_id=NEW.previous_plan_id AND p.operation_id=a.operation_id AND p.ordinal+1=NEW.ordinal AND x.observed_state='indeterminate'
 AND NOT EXISTS(SELECT 1 FROM aa_attempt n WHERE n.operation_id=a.operation_id AND n.ordinal>p.ordinal))))
 BEGIN SELECT RAISE(ABORT,'arm_stop_attempt_prestate'); END;
CREATE TRIGGER aa_register_plan AFTER INSERT ON aa_attempt BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NULL,NEW.plan_id,NULL,NULL); END;
CREATE TABLE aa_target(
 plan_id TEXT NOT NULL REFERENCES aa_attempt(plan_id),target_id TEXT NOT NULL,controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,
 binding_body BLOB NOT NULL CHECK(json_valid(binding_body)),dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,controller_authority,controller_database),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER aa_target_sealed BEFORE INSERT ON aa_target WHEN EXISTS(SELECT 1 FROM aa_attempt_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'arm_stop_targets_sealed'); END;
CREATE TABLE aa_attempt_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES aa_attempt(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER aa_attempt_seal BEFORE INSERT ON aa_attempt_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM aa_attempt t JOIN aa_stop a USING(operation_id) JOIN aa_inventory_current i USING(operation_id)
 JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id) JOIN pause_latch l ON l.latch_id=a.latch_id
 JOIN sp_plan p ON p.plan_id=t.plan_id JOIN sp_plan_commit c ON c.plan_id=t.plan_id JOIN p1_limit lim ON lim.singleton=1
 WHERE t.plan_id=NEW.plan_id AND r.active_operation_id=a.operation_id AND r.active_execution_id IS NULL AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.arm_generation=a.generation AND (t.ordinal!=1 OR r.revision=a.revision_after)
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=a.slot_revision
 AND l.run_id=r.run_id AND l.reason='arm_exit' AND l.created_revision=a.revision_after AND l.cleared_start_id IS NULL
 AND p.plan_digest=t.plan_digest AND p.plan_body=t.plan_body AND p.target_count=t.target_count
 AND t.target_count=(SELECT count(*) FROM aa_target WHERE plan_id=t.plan_id) AND t.target_count<=lim.max_targets
 AND length(a.inventory_body)+length(t.plan_body)+length(t.request_body)+coalesce((SELECT sum(length(binding_body)+length(dispatch_body)) FROM aa_target WHERE plan_id=t.plan_id),0)<=lim.max_payload_bytes)
 THEN RAISE(ABORT,'arm_stop_seal_projection') END;
 SELECT CASE WHEN EXISTS(SELECT controller_authority,controller_database FROM aa_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT e.controller_authority,e.controller_database FROM aa_expected_target e JOIN aa_attempt t USING(operation_id) WHERE t.plan_id=NEW.plan_id)
 OR EXISTS(SELECT e.controller_authority,e.controller_database FROM aa_expected_target e JOIN aa_attempt t USING(operation_id) WHERE t.plan_id=NEW.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM aa_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM aa_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM aa_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'arm_stop_target_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM aa_target x JOIN aa_attempt t USING(plan_id) JOIN aa_stop a USING(operation_id) JOIN storage_scope sc ON sc.singleton=1
 WHERE x.plan_id=NEW.plan_id AND (json_extract(x.binding_body,'$.controller_scope.authority_service_id') IS NOT x.controller_authority
 OR json_extract(x.binding_body,'$.controller_scope.database_instance_id') IS NOT x.controller_database
 OR json_extract(x.binding_body,'$.origin_scope.authority_service_id') IS NOT sc.authority_id OR json_extract(x.binding_body,'$.origin_scope.database_instance_id') IS NOT sc.database_id
 OR json_extract(x.binding_body,'$.operation_id') IS NOT x.target_id OR json_extract(x.binding_body,'$.run_id') IS NOT a.run_id
 OR json_extract(x.binding_body,'$.deny_through_generation') IS NOT a.generation OR json_extract(x.binding_body,'$.target_set_digest') IS NOT t.plan_digest))
 THEN RAISE(ABORT,'arm_stop_target_binding') END;
END;
CREATE VIEW aa_latest_attempt AS SELECT t.* FROM aa_attempt t JOIN aa_attempt_commit c USING(plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM aa_attempt n JOIN aa_attempt_commit k USING(plan_id) WHERE n.operation_id=t.operation_id AND n.ordinal>t.ordinal);
CREATE TABLE aa_exit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES aa_stop(operation_id),plan_id TEXT NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,slot_revision TEXT NOT NULL,
 FOREIGN KEY(plan_id,operation_id) REFERENCES aa_attempt(plan_id,operation_id),
 FOREIGN KEY(operation_id) REFERENCES aa_exit_commit(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER aa_exit_guard BEFORE INSERT ON aa_exit WHEN NOT EXISTS(
 SELECT 1 FROM aa_stop a JOIN aa_latest_attempt t USING(operation_id) JOIN aa_inventory_current i USING(operation_id)
 JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id) JOIN sp_observed_summary x USING(plan_id)
 WHERE a.operation_id=NEW.operation_id AND a.run_id=NEW.run_id AND a.generation=NEW.generation AND t.plan_id=NEW.plan_id
 AND x.observed_state='applied' AND r.lifecycle='paused' AND r.dispatch_eligible=0 AND r.active_operation_id=a.operation_id AND r.active_execution_id IS NULL
 AND r.arm_generation=a.generation AND r.revision=NEW.revision_before AND NEW.revision_before!='99999999999999999999' AND NEW.revision_after=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10) AS INTEGER)+1)%10000000000),'0')
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=NEW.slot_revision AND s.revision=a.slot_revision)
 BEGIN SELECT RAISE(ABORT,'arm_exit_unconfirmed'); END;
CREATE TABLE aa_exit_pin(
 operation_id TEXT NOT NULL REFERENCES aa_exit(operation_id),plan_id TEXT NOT NULL,target_id TEXT NOT NULL,revision INTEGER NOT NULL CHECK(revision=1),observation_digest TEXT NOT NULL,
 PRIMARY KEY(operation_id,target_id),FOREIGN KEY(plan_id,operation_id) REFERENCES aa_attempt(plan_id,operation_id),
 FOREIGN KEY(plan_id,target_id,revision) REFERENCES sp_observation(plan_id,target_id,revision)
) STRICT;
CREATE TRIGGER aa_pin_guard BEFORE INSERT ON aa_exit_pin WHEN EXISTS(SELECT 1 FROM aa_exit_commit WHERE operation_id=NEW.operation_id)
 OR NOT EXISTS(SELECT 1 FROM aa_exit e JOIN sp_current_observation o ON o.plan_id=e.plan_id WHERE e.operation_id=NEW.operation_id AND e.plan_id=NEW.plan_id
 AND o.target_id=NEW.target_id AND o.revision=NEW.revision AND o.observation_digest=NEW.observation_digest AND o.state='applied')
 BEGIN SELECT RAISE(ABORT,'arm_exit_pin'); END;
CREATE TABLE aa_exit_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES aa_exit(operation_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER aa_exit_seal BEFORE INSERT ON aa_exit_commit WHEN NOT EXISTS(
 SELECT 1 FROM aa_exit e JOIN aa_stop a USING(operation_id) JOIN aa_inventory_current i USING(operation_id) JOIN aa_latest_attempt t USING(operation_id)
 JOIN run r ON r.run_id=e.run_id JOIN activation_slot s USING(definition_id) JOIN sp_observed_summary x ON x.plan_id=e.plan_id
 WHERE e.operation_id=NEW.operation_id AND e.plan_id=t.plan_id AND x.observed_state='applied'
 AND r.lifecycle='paused' AND r.dispatch_eligible=0 AND r.active_operation_id IS NULL AND r.active_execution_id IS NULL
 AND r.revision=e.revision_after AND r.arm_generation=e.generation AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=e.slot_revision
 AND EXISTS(SELECT 1 FROM pause_latch WHERE latch_id=a.latch_id AND cleared_start_id IS NULL)
 AND t.target_count=(SELECT count(*) FROM aa_exit_pin WHERE operation_id=e.operation_id)
 AND NOT EXISTS(SELECT target_id,revision,observation_digest FROM sp_current_observation WHERE plan_id=e.plan_id
 EXCEPT SELECT target_id,revision,observation_digest FROM aa_exit_pin WHERE operation_id=e.operation_id))
 BEGIN SELECT RAISE(ABORT,'arm_exit_final_projection'); END;
CREATE TRIGGER aa_active_arm_release BEFORE UPDATE ON run WHEN OLD.active_operation_id IS NOT NEW.active_operation_id
 AND EXISTS(SELECT 1 FROM arm_operation WHERE operation_id=OLD.active_operation_id)
 AND NOT EXISTS(SELECT 1 FROM arm_complete c WHERE c.operation_id=OLD.active_operation_id AND c.run_id=NEW.run_id AND c.revision_before=OLD.revision
 AND c.revision_after=NEW.revision AND NEW.active_operation_id IS NULL AND NOT EXISTS(SELECT 1 FROM arm_ready_commit WHERE operation_id=c.operation_id))
 AND NOT EXISTS(SELECT 1 FROM aa_exit e WHERE e.operation_id=OLD.active_operation_id AND e.run_id=NEW.run_id AND e.revision_before=OLD.revision
 AND e.revision_after=NEW.revision AND NEW.active_operation_id IS NULL AND NOT EXISTS(SELECT 1 FROM aa_exit_commit WHERE operation_id=e.operation_id))
 BEGIN SELECT RAISE(ABORT,'active_arm_requires_exit'); END;
CREATE TRIGGER aa_no_late_adoption BEFORE INSERT ON arm_receipt WHEN EXISTS(
 SELECT 1 FROM p1_preparation p JOIN aa_stop a ON a.operation_id=p.arm_operation_id WHERE p.registration_id=NEW.registration_id)
 BEGIN SELECT RAISE(ABORT,'arm_stopped_history_only'); END;

CREATE TRIGGER aa_stop_update BEFORE UPDATE ON aa_stop BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_stop_delete BEFORE DELETE ON aa_stop BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_attempt_update BEFORE UPDATE ON aa_attempt BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_attempt_delete BEFORE DELETE ON aa_attempt BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_target_update BEFORE UPDATE ON aa_target BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_target_delete BEFORE DELETE ON aa_target BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_attempt_commit_update BEFORE UPDATE ON aa_attempt_commit BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_attempt_commit_delete BEFORE DELETE ON aa_attempt_commit BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_exit_update BEFORE UPDATE ON aa_exit BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_exit_delete BEFORE DELETE ON aa_exit BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_exit_pin_update BEFORE UPDATE ON aa_exit_pin BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_exit_pin_delete BEFORE DELETE ON aa_exit_pin BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_exit_commit_update BEFORE UPDATE ON aa_exit_commit BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_exit_commit_delete BEFORE DELETE ON aa_exit_commit BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;

CREATE TRIGGER aa_stop_u20 BEFORE INSERT ON aa_stop WHEN length(NEW.generation) NOT BETWEEN 1 AND 20 OR NEW.generation GLOB '*[^0-9]*' OR (NEW.generation!='0' AND substr(NEW.generation,1,1)='0') OR instr(NEW.generation,char(0))>0 OR length(NEW.revision_before) NOT BETWEEN 1 AND 20 OR NEW.revision_before GLOB '*[^0-9]*' OR (NEW.revision_before!='0' AND substr(NEW.revision_before,1,1)='0') OR instr(NEW.revision_before,char(0))>0 OR length(NEW.revision_after) NOT BETWEEN 1 AND 20 OR NEW.revision_after GLOB '*[^0-9]*' OR (NEW.revision_after!='0' AND substr(NEW.revision_after,1,1)='0') OR instr(NEW.revision_after,char(0))>0 OR length(NEW.slot_revision) NOT BETWEEN 1 AND 20 OR NEW.slot_revision GLOB '*[^0-9]*' OR (NEW.slot_revision!='0' AND substr(NEW.slot_revision,1,1)='0') OR instr(NEW.slot_revision,char(0))>0 BEGIN SELECT RAISE(ABORT,'arm_exit_u20'); END;

CREATE TRIGGER aa_exit_u20 BEFORE INSERT ON aa_exit WHEN length(NEW.generation) NOT BETWEEN 1 AND 20 OR NEW.generation GLOB '*[^0-9]*' OR (NEW.generation!='0' AND substr(NEW.generation,1,1)='0') OR instr(NEW.generation,char(0))>0 OR length(NEW.revision_before) NOT BETWEEN 1 AND 20 OR NEW.revision_before GLOB '*[^0-9]*' OR (NEW.revision_before!='0' AND substr(NEW.revision_before,1,1)='0') OR instr(NEW.revision_before,char(0))>0 OR length(NEW.revision_after) NOT BETWEEN 1 AND 20 OR NEW.revision_after GLOB '*[^0-9]*' OR (NEW.revision_after!='0' AND substr(NEW.revision_after,1,1)='0') OR instr(NEW.revision_after,char(0))>0 OR length(NEW.slot_revision) NOT BETWEEN 1 AND 20 OR NEW.slot_revision GLOB '*[^0-9]*' OR (NEW.slot_revision!='0' AND substr(NEW.slot_revision,1,1)='0') OR instr(NEW.slot_revision,char(0))>0 BEGIN SELECT RAISE(ABORT,'arm_exit_u20'); END;

-- 当前槽/运行/准备与普通触发、动作及R5同版联接。可信证据和真实I/O仍由外部提供者负责。
CREATE VIEW flow_active_execution AS SELECT e.* FROM execution e JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 WHERE e.state='running' AND r.lifecycle='running' AND r.active_execution_id=e.execution_id AND r.active_operation_id IS NULL
 AND r.arm_generation=e.arm_generation AND s.active_run_id=r.run_id AND s.version=r.version
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.run_id=r.run_id AND p.generation=r.arm_generation AND q.qualification!='observed_applied')
 AND NOT EXISTS(SELECT 1 FROM step_state st JOIN execution_step_plan p USING(execution_id,step_id) WHERE st.execution_id=e.execution_id
 AND (st.outcome IN ('unknown','blocked','expired','cancelled') OR(p.required=1 AND st.outcome='failed')))
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||e.arm_generation,-20)<=generation);
CREATE TRIGGER flow_decision_prestate BEFORE INSERT ON ingress_decision WHEN NEW.result='accepted' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ingress_snapshot s JOIN run r USING(run_id) JOIN activation_slot a USING(definition_id)
 WHERE s.snapshot_id=NEW.snapshot_id AND s.run_id=NEW.run_id AND r.lifecycle='armed' AND r.dispatch_eligible=1
 AND r.active_execution_id IS NULL AND r.active_operation_id IS NULL AND r.revision=NEW.run_before
 AND NEW.run_before!='99999999999999999999' AND NEW.run_after=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.run_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.run_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.run_before,-20),11,10) AS INTEGER)+1)%10000000000),'0')
 AND a.active_run_id=r.run_id AND a.version=r.version AND a.revision!='99999999999999999999'
 AND json_extract(s.body,'$.flow_version')='trigger-flow-storage/0.1.0-draft.1'
 AND json_extract(s.body,'$.run_revision') IS r.revision AND json_extract(s.body,'$.generation') IS r.arm_generation
 AND json_extract(s.body,'$.slot_revision_before') IS a.revision AND json_extract(s.body,'$.slot_revision_after') IS ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||json_extract(s.body,'$.slot_revision_before'),-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||json_extract(s.body,'$.slot_revision_before'),-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||json_extract(s.body,'$.slot_revision_before'),-20),11,10) AS INTEGER)+1)%10000000000),'0')
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.run_id=r.run_id AND p.generation=r.arm_generation AND q.qualification!='observed_applied')
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||r.arm_generation,-20)<=generation))
 THEN RAISE(ABORT,'flow_trigger_prestate') END;
END;
CREATE TRIGGER flow_ingress_final BEFORE UPDATE ON ingress_commit WHEN NEW.sealed=1 AND EXISTS(
 SELECT 1 FROM ingress_decision d JOIN ingress_snapshot x ON x.snapshot_id=d.snapshot_id JOIN run r ON r.run_id=d.run_id JOIN activation_slot s USING(definition_id)
 JOIN execution e ON e.execution_id=d.execution_id WHERE d.commit_id=NEW.commit_id AND d.result='accepted'
 AND (s.revision IS NOT json_extract(x.body,'$.slot_revision_after') OR e.arm_generation IS NOT r.arm_generation
 OR NOT EXISTS(SELECT 1 FROM flow_active_execution WHERE execution_id=e.execution_id)
 OR NOT EXISTS(SELECT 1 FROM execution_plan_set p JOIN transaction_record tx ON tx.tx_id=p.tx_id
 JOIN event_outbox n ON n.tx_id=tx.tx_id AND n.event_id=tx.event_id WHERE p.execution_id=e.execution_id AND tx.phase='PLAN' AND tx.business_id=e.execution_id)))
 BEGIN SELECT RAISE(ABORT,'flow_trigger_final'); END;
CREATE TRIGGER flow_submission_target BEFORE INSERT ON command_submission WHEN NOT EXISTS(
 SELECT 1 FROM execution e JOIN p1_preparation p ON p.run_id=e.run_id AND p.generation=e.arm_generation JOIN pq_current q USING(registration_id)
 WHERE e.execution_id=NEW.execution_id AND p.controller_authority=NEW.target_authority AND p.controller_database=NEW.target_database
 AND (p.execution_id IS NULL OR p.execution_id=e.execution_id OR EXISTS(SELECT 1 FROM cn_step n JOIN cn_current c USING(transfer_id,registration_id) WHERE n.execution_id=e.execution_id AND n.step_id=NEW.step_id AND n.registration_id=p.registration_id AND n.adoption_digest=c.adoption_digest)) AND q.qualification='observed_applied')
 BEGIN SELECT RAISE(ABORT,'flow_target_unprepared'); END;
CREATE TRIGGER flow_attempt_gate BEFORE INSERT ON submission_attempt WHEN NOT EXISTS(
 SELECT 1 FROM command_submission c JOIN flow_active_execution e USING(execution_id) JOIN run r ON r.run_id=e.run_id
 WHERE c.submission_id=NEW.submission_id AND r.dispatch_eligible=1)
 BEGIN SELECT RAISE(ABORT,'flow_attempt_inactive'); END;
CREATE TABLE flow_commit_seal(
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES transition_commit(commit_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER flow_commit_prestate BEFORE INSERT ON transition_commit WHEN NOT EXISTS(
 SELECT 1 FROM flow_active_execution e JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id) LEFT JOIN business_state b USING(run_id)
 WHERE e.execution_id=NEW.execution_id AND e.run_id=NEW.run_id AND e.kind=NEW.kind AND r.revision=NEW.run_revision_before
 AND NEW.run_revision_before!='99999999999999999999' AND NEW.run_revision_after=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.run_revision_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.run_revision_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.run_revision_before,-20),11,10) AS INTEGER)+1)%10000000000),'0') AND s.revision=NEW.slot_revision
 AND ((e.kind='rule' AND b.run_id IS NULL) OR (e.kind='state_machine' AND b.state_id=e.source_state_id AND b.revision=e.source_state_revision
 AND NEW.source_state_id IS b.state_id AND NEW.source_state_revision IS b.revision AND NEW.target_state_id IS e.target_state_id
 AND NEW.source_state_revision!='99999999999999999999' AND NEW.target_state_revision=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.source_state_revision,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.source_state_revision,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.source_state_revision,-20),11,10) AS INTEGER)+1)%10000000000),'0'))))
 BEGIN SELECT RAISE(ABORT,'flow_commit_prestate'); END;
CREATE TRIGGER flow_commit_final BEFORE INSERT ON flow_commit_seal WHEN NOT EXISTS(
 SELECT 1 FROM transition_commit c JOIN execution e USING(execution_id,run_id) JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 LEFT JOIN business_state b USING(run_id) JOIN transaction_record tx ON tx.tx_id=c.tx_id
 JOIN event_outbox n ON n.tx_id=tx.tx_id AND n.event_id=tx.event_id WHERE c.commit_id=NEW.commit_id AND tx.phase='R5' AND tx.business_id=c.commit_id
 AND e.state='succeeded' AND e.commit_id=c.commit_id
 AND (e.origin_kind='trigger' OR EXISTS(SELECT 1 FROM recovery_operation ro JOIN recovery_lock lk USING(operation_id)
 WHERE ro.operation_id=e.recovery_operation_id AND ro.state='completed' AND lk.release_id IS NOT NULL))
 AND r.lifecycle='armed' AND r.dispatch_eligible=1 AND r.active_operation_id IS NULL AND r.active_execution_id IS NULL
 AND r.last_commit_id=c.commit_id AND r.revision=c.run_revision_after AND r.arm_generation=e.arm_generation
 AND s.active_run_id=r.run_id AND s.version=r.version AND s.revision=c.slot_revision
 AND ((c.kind='rule' AND b.run_id IS NULL) OR(c.kind='state_machine' AND b.state_id=c.target_state_id AND b.revision=c.target_state_revision AND b.last_commit_id=c.commit_id))
 AND NOT EXISTS(SELECT 1 FROM pause_latch WHERE run_id=r.run_id AND cleared_start_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.run_id=r.run_id AND p.generation=r.arm_generation AND q.qualification!='observed_applied')
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||r.arm_generation,-20)<=generation))
 BEGIN SELECT RAISE(ABORT,'flow_commit_final'); END;
CREATE TRIGGER flow_seal_update BEFORE UPDATE ON flow_commit_seal BEGIN SELECT RAISE(ABORT,'immutable_flow_seal'); END;
CREATE TRIGGER flow_seal_delete BEFORE DELETE ON flow_commit_seal BEGIN SELECT RAISE(ABORT,'immutable_flow_seal'); END;

CREATE TRIGGER flow_commit_u20 BEFORE INSERT ON transition_commit WHEN length(NEW.run_revision_before) NOT BETWEEN 1 AND 20 OR NEW.run_revision_before GLOB '*[^0-9]*' OR (NEW.run_revision_before!='0' AND substr(NEW.run_revision_before,1,1)='0') OR instr(NEW.run_revision_before,char(0))>0 OR length(NEW.run_revision_after) NOT BETWEEN 1 AND 20 OR NEW.run_revision_after GLOB '*[^0-9]*' OR (NEW.run_revision_after!='0' AND substr(NEW.run_revision_after,1,1)='0') OR instr(NEW.run_revision_after,char(0))>0 OR length(NEW.slot_revision) NOT BETWEEN 1 AND 20 OR NEW.slot_revision GLOB '*[^0-9]*' OR (NEW.slot_revision!='0' AND substr(NEW.slot_revision,1,1)='0') OR instr(NEW.slot_revision,char(0))>0 BEGIN SELECT RAISE(ABORT,'flow_commit_u20'); END;

CREATE TRIGGER flow_gate_step_ready BEFORE INSERT ON step_ready WHEN NOT EXISTS(SELECT 1 FROM flow_active_execution e JOIN run r USING(run_id) WHERE e.execution_id=NEW.execution_id) BEGIN SELECT RAISE(ABORT,'flow_execution_inactive'); END;

CREATE TRIGGER flow_gate_command_submission BEFORE INSERT ON command_submission WHEN NOT EXISTS(SELECT 1 FROM flow_active_execution e JOIN run r USING(run_id) WHERE e.execution_id=NEW.execution_id AND r.dispatch_eligible=1) BEGIN SELECT RAISE(ABORT,'flow_execution_inactive'); END;

-- 需要停止的动作终态必须与完整独立保护计划同事务，不伪造来源或准备失效。
CREATE TABLE sf_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,terminal_id TEXT NOT NULL UNIQUE REFERENCES step_terminal(terminal_id) DEFERRABLE INITIALLY DEFERRED,
 execution_id TEXT NOT NULL REFERENCES execution(execution_id),execution_state_before TEXT NOT NULL,step_id TEXT NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 current_generation TEXT NOT NULL,revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,lifecycle_before TEXT NOT NULL,dispatch_before INTEGER NOT NULL,
 active_execution_before TEXT,active_operation_before TEXT,slot_revision TEXT NOT NULL,slot_run TEXT,slot_version TEXT,
 affects_current INTEGER NOT NULL CHECK(affects_current IN (0,1)),latch_id TEXT UNIQUE REFERENCES pause_latch(latch_id) DEFERRABLE INITIALLY DEFERRED,
 outcome TEXT NOT NULL CHECK(outcome IN ('failed','unknown','blocked','expired','cancelled')),
 preparation_head INTEGER NOT NULL CHECK(preparation_head>=0),target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),
 inventory_body BLOB NOT NULL CHECK(json_valid(inventory_body)),plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(plan_id) REFERENCES sf_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER sf_prestate BEFORE INSERT ON sf_plan WHEN NOT EXISTS(
 SELECT 1 FROM execution e JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 JOIN step_state st USING(execution_id) JOIN execution_step_plan p USING(execution_id,step_id)
 WHERE e.execution_id=NEW.execution_id AND e.state=NEW.execution_state_before AND st.step_id=NEW.step_id AND st.outcome='pending' AND e.run_id=NEW.run_id
 AND (NEW.outcome!='failed' OR p.required=1) AND e.arm_generation=NEW.generation AND r.arm_generation=NEW.current_generation
 AND substr('00000000000000000000'||NEW.generation,-20)<=substr('00000000000000000000'||NEW.current_generation,-20)
 AND r.revision=NEW.revision_before AND r.lifecycle=NEW.lifecycle_before AND r.dispatch_eligible=NEW.dispatch_before
 AND r.active_execution_id IS NEW.active_execution_before AND r.active_operation_id IS NEW.active_operation_before
 AND s.revision=NEW.slot_revision AND s.active_run_id IS NEW.slot_run AND s.version IS NEW.slot_version
 AND NEW.affects_current=(r.active_execution_id IS e.execution_id AND r.arm_generation=e.arm_generation AND r.lifecycle!='completed')
 AND ((NEW.affects_current=1 AND NEW.latch_id IS NOT NULL AND NEW.revision_before!='99999999999999999999' AND NEW.revision_after=ltrim(printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),1,10) AS INTEGER)+(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10)='9999999999'),(CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10) AS INTEGER)+1)%10000000000),'0'))
 OR(NEW.affects_current=0 AND NEW.latch_id IS NULL AND NEW.revision_after=NEW.revision_before)))
 BEGIN SELECT RAISE(ABORT,'failure_prestate'); END;
CREATE TRIGGER sf_register AFTER INSERT ON sf_plan BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NULL,NULL,NEW.plan_id,NULL); END;
CREATE TRIGGER sf_terminal BEFORE INSERT ON step_terminal BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM execution_step_plan p WHERE p.execution_id=NEW.execution_id AND p.step_id=NEW.step_id
 AND (NEW.outcome IN ('unknown','blocked','expired','cancelled') OR(NEW.outcome='failed' AND p.required=1)))
 THEN CASE WHEN NOT EXISTS(SELECT 1 FROM sf_plan p WHERE p.plan_id=NEW.protection_plan_id AND p.terminal_id=NEW.terminal_id
 AND p.execution_id=NEW.execution_id AND p.step_id=NEW.step_id AND p.run_id=NEW.run_id AND p.outcome=NEW.outcome)
 THEN RAISE(ABORT,'failure_plan_required') END
 ELSE CASE WHEN NEW.protection_plan_id IS NOT NULL THEN RAISE(ABORT,'unexpected_failure_plan') END END;
END;
CREATE VIEW sf_expected_member AS
 SELECT a.plan_id,'preparation' AS kind,p.registration_id AS ref,hex(p.binding_body) AS body FROM sf_plan a JOIN p1_preparation p USING(run_id)
 WHERE substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION ALL SELECT a.plan_id,'execution',e.execution_id,e.binding_digest FROM sf_plan a JOIN execution e USING(run_id)
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION ALL SELECT a.plan_id,'submission',s.submission_id,hex(s.request_body) FROM sf_plan a JOIN execution e USING(run_id) JOIN command_submission s ON s.execution_id=e.execution_id
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20);
CREATE VIEW sf_expected_target AS
 SELECT a.plan_id,p.controller_authority,p.controller_database FROM sf_plan a JOIN p1_preparation p USING(run_id)
 WHERE substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION SELECT a.plan_id,s.target_authority,s.target_database FROM sf_plan a JOIN execution e USING(run_id) JOIN command_submission s ON s.execution_id=e.execution_id
 WHERE substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20);
CREATE TABLE sf_target(
 plan_id TEXT NOT NULL REFERENCES sf_plan(plan_id),target_id TEXT NOT NULL,controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,
 binding_body BLOB NOT NULL,dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,controller_authority,controller_database),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER sf_target_guard BEFORE INSERT ON sf_target WHEN EXISTS(SELECT 1 FROM sf_commit WHERE plan_id=NEW.plan_id) OR NOT EXISTS(
 SELECT 1 FROM sf_plan p JOIN storage_scope s ON s.singleton=1 WHERE p.plan_id=NEW.plan_id
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.run_id') IS p.run_id AND json_extract(NEW.binding_body,'$.deny_through_generation') IS p.generation
 AND json_extract(NEW.binding_body,'$.operation_id') IS NEW.target_id AND json_extract(NEW.binding_body,'$.target_set_digest') IS p.plan_digest
 AND json_extract(NEW.dispatch_body,'$.kind')='protect_registered_run' AND CAST(json_extract(NEW.dispatch_body,'$.binding') AS BLOB)=NEW.binding_body)
 BEGIN SELECT RAISE(ABORT,'failure_target_binding'); END;
CREATE TABLE sf_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES sf_plan(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER sf_commit_guard BEFORE INSERT ON sf_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sf_plan p JOIN run r USING(run_id) JOIN activation_slot s USING(definition_id)
 JOIN step_terminal t ON t.terminal_id=p.terminal_id JOIN execution e ON e.execution_id=p.execution_id
 JOIN step_state st ON st.execution_id=p.execution_id AND st.step_id=p.step_id JOIN p1_limit l ON l.singleton=1
 JOIN transaction_record tx ON tx.tx_id=t.tx_id JOIN event_outbox n ON n.tx_id=tx.tx_id AND n.event_id=tx.event_id
 WHERE p.plan_id=NEW.plan_id AND t.protection_plan_id=p.plan_id AND st.terminal_id=t.terminal_id AND st.outcome=p.outcome
 AND tx.phase='STEP_TERMINAL' AND tx.business_id=t.terminal_id AND tx.run_id=p.run_id
 AND r.revision=p.revision_after AND r.arm_generation=p.current_generation AND r.active_execution_id IS p.active_execution_before AND r.active_operation_id IS p.active_operation_before
 AND s.revision=p.slot_revision AND s.active_run_id IS p.slot_run AND s.version IS p.slot_version
 AND ((p.affects_current=0 AND r.lifecycle=p.lifecycle_before AND r.dispatch_eligible=p.dispatch_before)
 OR(p.affects_current=1 AND r.lifecycle='paused' AND r.dispatch_eligible=0 AND e.state=CASE WHEN p.execution_state_before IN ('prepared','running','paused') THEN CASE p.outcome WHEN 'unknown' THEN 'unknown' WHEN 'failed' THEN 'failed' ELSE 'paused' END ELSE p.execution_state_before END
 AND EXISTS(SELECT 1 FROM pause_latch x WHERE x.latch_id=p.latch_id AND x.run_id=p.run_id AND x.created_revision=p.revision_after AND x.reason='step_terminal_failure' AND x.cleared_start_id IS NULL)))
 AND p.preparation_head=(SELECT coalesce(max(sequence),0) FROM p1_preparation)
 AND p.target_count=(SELECT count(*) FROM sf_target WHERE plan_id=p.plan_id) AND p.target_count<=l.max_targets
 AND (SELECT count(*) FROM sf_plan)<=l.max_plans AND json_type(p.inventory_body)='array'
 AND json_array_length(p.inventory_body)=(SELECT count(*) FROM sf_expected_member WHERE plan_id=p.plan_id) AND json_array_length(p.inventory_body)<=65536
 AND length(p.inventory_body)+length(p.plan_body)+length(NEW.audit_body)+length(NEW.notification_body)
 +coalesce((SELECT sum(length(binding_body)+length(dispatch_body)) FROM sf_target WHERE plan_id=p.plan_id),0)<=l.max_payload_bytes)
 THEN RAISE(ABORT,'failure_final_projection_or_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT kind,ref,body FROM sf_expected_member WHERE plan_id=NEW.plan_id
 EXCEPT SELECT json_extract(value,'$.kind'),json_extract(value,'$.ref'),json_extract(value,'$.body') FROM sf_plan p,json_each(p.inventory_body) WHERE p.plan_id=NEW.plan_id)
 OR EXISTS(SELECT controller_authority,controller_database FROM sf_expected_target WHERE plan_id=NEW.plan_id EXCEPT SELECT controller_authority,controller_database FROM sf_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT controller_authority,controller_database FROM sf_target WHERE plan_id=NEW.plan_id EXCEPT SELECT controller_authority,controller_database FROM sf_expected_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'failure_complete_inventory') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sf_plan p JOIN sp_plan s USING(plan_id) JOIN sp_plan_commit c USING(plan_id)
 WHERE p.plan_id=NEW.plan_id AND s.plan_body=p.plan_body AND s.plan_digest=p.plan_digest AND s.target_count=p.target_count)
 OR EXISTS(SELECT target_id,binding_body FROM sf_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sf_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'failure_receiver_plan') END;
END;
CREATE VIEW sf_pending_dispatch AS SELECT t.* FROM sf_target t JOIN sf_commit c USING(plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=t.plan_id AND o.target_id=t.target_id AND o.state='applied');

CREATE TRIGGER sf_plan_update BEFORE UPDATE ON sf_plan BEGIN SELECT RAISE(ABORT,'immutable_failure_protection'); END;

CREATE TRIGGER sf_plan_delete BEFORE DELETE ON sf_plan BEGIN SELECT RAISE(ABORT,'immutable_failure_protection'); END;

CREATE TRIGGER sf_target_update BEFORE UPDATE ON sf_target BEGIN SELECT RAISE(ABORT,'immutable_failure_protection'); END;

CREATE TRIGGER sf_target_delete BEFORE DELETE ON sf_target BEGIN SELECT RAISE(ABORT,'immutable_failure_protection'); END;

CREATE TRIGGER sf_commit_update BEFORE UPDATE ON sf_commit BEGIN SELECT RAISE(ABORT,'immutable_failure_protection'); END;

CREATE TRIGGER sf_commit_delete BEFORE DELETE ON sf_commit BEGIN SELECT RAISE(ABORT,'immutable_failure_protection'); END;

CREATE TRIGGER sf_plan_u20 BEFORE INSERT ON sf_plan WHEN length(NEW.generation) NOT BETWEEN 1 AND 20 OR NEW.generation GLOB '*[^0-9]*' OR (NEW.generation!='0' AND substr(NEW.generation,1,1)='0') OR instr(NEW.generation,char(0))>0 OR length(NEW.current_generation) NOT BETWEEN 1 AND 20 OR NEW.current_generation GLOB '*[^0-9]*' OR (NEW.current_generation!='0' AND substr(NEW.current_generation,1,1)='0') OR instr(NEW.current_generation,char(0))>0 OR length(NEW.revision_before) NOT BETWEEN 1 AND 20 OR NEW.revision_before GLOB '*[^0-9]*' OR (NEW.revision_before!='0' AND substr(NEW.revision_before,1,1)='0') OR instr(NEW.revision_before,char(0))>0 OR length(NEW.revision_after) NOT BETWEEN 1 AND 20 OR NEW.revision_after GLOB '*[^0-9]*' OR (NEW.revision_after!='0' AND substr(NEW.revision_after,1,1)='0') OR instr(NEW.revision_after,char(0))>0 OR length(NEW.slot_revision) NOT BETWEEN 1 AND 20 OR NEW.slot_revision GLOB '*[^0-9]*' OR (NEW.slot_revision!='0' AND substr(NEW.slot_revision,1,1)='0') OR instr(NEW.slot_revision,char(0))>0 BEGIN SELECT RAISE(ABORT,'failure_u20'); END;

-- 重新关闭只基于最新失效尝试；原始终态及旧代次选择器不变，不重投动作。
CREATE TABLE sr_attempt(
 plan_id TEXT PRIMARY KEY NOT NULL,root_plan_id TEXT NOT NULL REFERENCES sf_commit(plan_id),attempt_index INTEGER NOT NULL CHECK(attempt_index BETWEEN 1 AND 16),
 previous_plan_id TEXT NOT NULL REFERENCES sp_plan_commit(plan_id),request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL CHECK(length(request_body)>0),plan_digest TEXT NOT NULL,plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 256),UNIQUE(root_plan_id,attempt_index),UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(plan_id) REFERENCES sr_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW sr_attempts AS SELECT p.plan_id AS root_plan_id,p.plan_id,0 AS attempt_index FROM sf_plan p JOIN sf_commit c USING(plan_id)
 UNION ALL SELECT a.root_plan_id,a.plan_id,a.attempt_index FROM sr_attempt a JOIN sr_commit c USING(plan_id);
CREATE VIEW sr_latest AS SELECT a.* FROM sr_attempts a WHERE NOT EXISTS(SELECT 1 FROM sr_attempts b WHERE b.root_plan_id=a.root_plan_id AND b.attempt_index>a.attempt_index);
CREATE VIEW sr_inventory_current AS SELECT p.plan_id FROM sf_plan p WHERE
 json_array_length(p.inventory_body)=(SELECT count(*) FROM sf_expected_member m WHERE m.plan_id=p.plan_id)
 AND NOT EXISTS(SELECT kind,ref,body FROM sf_expected_member WHERE plan_id=p.plan_id
 EXCEPT SELECT json_extract(value,'$.kind'),json_extract(value,'$.ref'),json_extract(value,'$.body') FROM json_each(p.inventory_body))
 AND NOT EXISTS(SELECT controller_authority,controller_database FROM sf_expected_target WHERE plan_id=p.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM sf_target WHERE plan_id=p.plan_id)
 AND NOT EXISTS(SELECT controller_authority,controller_database FROM sf_target WHERE plan_id=p.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM sf_expected_target WHERE plan_id=p.plan_id);
CREATE TRIGGER sr_prestate BEFORE INSERT ON sr_attempt WHEN NOT EXISTS(
 SELECT 1 FROM sr_latest a JOIN sp_observed_summary o USING(plan_id) JOIN sr_inventory_current i ON i.plan_id=a.root_plan_id
 WHERE a.root_plan_id=NEW.root_plan_id AND a.plan_id=NEW.previous_plan_id AND a.attempt_index+1=NEW.attempt_index AND o.observed_state='indeterminate')
 BEGIN SELECT RAISE(ABORT,'retry_requires_latest_invalidated'); END;
CREATE TRIGGER sr_register AFTER INSERT ON sr_attempt BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NULL,NULL,NULL,NEW.plan_id); END;
CREATE TABLE sr_target(
 plan_id TEXT NOT NULL REFERENCES sr_attempt(plan_id),target_id TEXT NOT NULL,controller_authority TEXT NOT NULL,controller_database TEXT NOT NULL,
 binding_body BLOB NOT NULL,dispatch_body BLOB NOT NULL CHECK(length(dispatch_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,controller_authority,controller_database),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER sr_target_guard BEFORE INSERT ON sr_target WHEN EXISTS(SELECT 1 FROM sr_commit WHERE plan_id=NEW.plan_id) OR NOT EXISTS(
 SELECT 1 FROM sr_attempt a JOIN sf_plan p ON p.plan_id=a.root_plan_id JOIN storage_scope s ON s.singleton=1 WHERE a.plan_id=NEW.plan_id
 AND json_extract(NEW.binding_body,'$.controller_scope.authority_service_id') IS NEW.controller_authority
 AND json_extract(NEW.binding_body,'$.controller_scope.database_instance_id') IS NEW.controller_database
 AND json_extract(NEW.binding_body,'$.origin_scope.authority_service_id') IS s.authority_id
 AND json_extract(NEW.binding_body,'$.origin_scope.database_instance_id') IS s.database_id
 AND json_extract(NEW.binding_body,'$.run_id') IS p.run_id AND json_extract(NEW.binding_body,'$.deny_through_generation') IS p.generation
 AND json_extract(NEW.binding_body,'$.operation_id') IS NEW.target_id AND json_extract(NEW.binding_body,'$.target_set_digest') IS a.plan_digest
 AND json_extract(NEW.dispatch_body,'$.kind')='protect_registered_run' AND CAST(json_extract(NEW.dispatch_body,'$.binding') AS BLOB)=NEW.binding_body)
 BEGIN SELECT RAISE(ABORT,'retry_target_binding'); END;
CREATE TABLE sr_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES sr_attempt(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER sr_commit_guard BEFORE INSERT ON sr_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sr_attempt a JOIN sr_latest p ON p.root_plan_id=a.root_plan_id JOIN sp_observed_summary o ON o.plan_id=p.plan_id
 JOIN sr_inventory_current i ON i.plan_id=a.root_plan_id JOIN p1_limit l ON l.singleton=1
 WHERE a.plan_id=NEW.plan_id AND p.plan_id=a.previous_plan_id AND p.attempt_index+1=a.attempt_index AND o.observed_state='indeterminate'
 AND a.target_count=(SELECT count(*) FROM sr_target WHERE plan_id=a.plan_id) AND a.target_count<=l.max_targets
 AND length(a.request_body)+length(a.plan_body)+length(NEW.audit_body)+length(NEW.notification_body)
 +coalesce((SELECT sum(length(binding_body)+length(dispatch_body)) FROM sr_target WHERE plan_id=a.plan_id),0)<=l.max_payload_bytes)
 THEN RAISE(ABORT,'retry_final_prestate_or_capacity') END;
 SELECT CASE WHEN EXISTS(SELECT t.controller_authority,t.controller_database FROM sf_target t JOIN sr_attempt a ON a.root_plan_id=t.plan_id WHERE a.plan_id=NEW.plan_id
 EXCEPT SELECT controller_authority,controller_database FROM sr_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT controller_authority,controller_database FROM sr_target WHERE plan_id=NEW.plan_id
 EXCEPT SELECT t.controller_authority,t.controller_database FROM sf_target t JOIN sr_attempt a ON a.root_plan_id=t.plan_id WHERE a.plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'retry_complete_target_set') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sr_attempt a JOIN sp_plan s USING(plan_id) JOIN sp_plan_commit c USING(plan_id)
 WHERE a.plan_id=NEW.plan_id AND s.plan_body=a.plan_body AND s.plan_digest=a.plan_digest AND s.target_count=a.target_count)
 OR EXISTS(SELECT target_id,binding_body FROM sr_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT target_id,binding_body FROM sp_target WHERE plan_id=NEW.plan_id EXCEPT SELECT target_id,binding_body FROM sr_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'retry_receiver_plan') END;
END;
CREATE VIEW sr_all_targets AS SELECT t.plan_id AS root_plan_id,t.* FROM sf_target t JOIN sf_commit c USING(plan_id)
 UNION ALL SELECT a.root_plan_id,t.* FROM sr_target t JOIN sr_attempt a USING(plan_id) JOIN sr_commit c USING(plan_id);
DROP VIEW sf_pending_dispatch;
CREATE VIEW sf_pending_dispatch AS SELECT t.* FROM sr_all_targets t JOIN sr_latest l USING(root_plan_id,plan_id)
 WHERE NOT EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=t.plan_id AND o.target_id=t.target_id AND o.state='applied');

CREATE TRIGGER sr_attempt_update BEFORE UPDATE ON sr_attempt BEGIN SELECT RAISE(ABORT,'immutable_protection_retry'); END;

CREATE TRIGGER sr_attempt_delete BEFORE DELETE ON sr_attempt BEGIN SELECT RAISE(ABORT,'immutable_protection_retry'); END;

CREATE TRIGGER sr_target_update BEFORE UPDATE ON sr_target BEGIN SELECT RAISE(ABORT,'immutable_protection_retry'); END;

CREATE TRIGGER sr_target_delete BEFORE DELETE ON sr_target BEGIN SELECT RAISE(ABORT,'immutable_protection_retry'); END;

CREATE TRIGGER sr_commit_update BEFORE UPDATE ON sr_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_retry'); END;

CREATE TRIGGER sr_commit_delete BEFORE DELETE ON sr_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_retry'); END;

-- 一个共享消费账本覆盖五类保护来源；原预留原件不改写、不退款。
CREATE VIEW pb_expected_account AS
 SELECT p.plan_id,r.run_id,r.generation FROM protection_plan_registry p JOIN p1_run r ON r.plan_id=p.source_plan
 UNION SELECT p.plan_id,q.run_id,q.generation FROM protection_plan_registry p JOIN pq_plan q ON q.plan_id=p.preparation_plan
 UNION SELECT p.plan_id,s.run_id,s.generation FROM protection_plan_registry p JOIN aa_attempt a ON a.plan_id=p.arm_exit_plan JOIN aa_stop s USING(operation_id)
 UNION SELECT p.plan_id,s.run_id,s.generation FROM protection_plan_registry p JOIN sf_plan s ON s.plan_id=p.failure_plan
 UNION SELECT p.plan_id,s.run_id,s.generation FROM protection_plan_registry p JOIN sr_attempt a ON a.plan_id=p.retry_plan JOIN sf_plan s ON s.plan_id=a.root_plan_id;
CREATE VIEW pb_shape AS SELECT a.plan_id,a.run_id,a.generation,
 (SELECT count(*) FROM p1_dependency WHERE run_id=a.run_id) AS dependencies,1 AS runs,
 (SELECT count(*) FROM execution WHERE run_id=a.run_id AND substr('00000000000000000000'||arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS executions,
 (SELECT count(*) FROM p1_preparation WHERE run_id=a.run_id AND substr('00000000000000000000'||generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS preparations,
 (SELECT count(*) FROM command_submission s JOIN execution e USING(execution_id) WHERE s.run_id=a.run_id AND substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS submissions,
 (SELECT count(*) FROM(SELECT p.controller_authority,p.controller_database FROM p1_preparation p WHERE p.run_id=a.run_id AND substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION SELECT s.target_authority,s.target_database FROM command_submission s JOIN execution e USING(execution_id) WHERE s.run_id=a.run_id AND substr('00000000000000000000'||e.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20))) AS controller_targets
 FROM pb_expected_account a;
CREATE TABLE pb_use(
 plan_id TEXT NOT NULL REFERENCES protection_plan_registry(plan_id),run_id TEXT NOT NULL,generation TEXT NOT NULL,
 operation_id TEXT NOT NULL REFERENCES budget_account(operation_id),ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 1024),
 binding_digest TEXT NOT NULL,profile_digest TEXT NOT NULL,plan_digest TEXT NOT NULL,
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 shape_body BLOB NOT NULL CHECK(json_valid(shape_body)),observed_rows INTEGER NOT NULL CHECK(observed_rows>0),observed_bytes INTEGER NOT NULL CHECK(observed_bytes>0),
 observed_max_row_bytes INTEGER NOT NULL CHECK(observed_max_row_bytes>0),elapsed_wait_ns TEXT NOT NULL,
 measurement_body BLOB NOT NULL CHECK(length(measurement_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 PRIMARY KEY(plan_id,run_id,generation),UNIQUE(operation_id,ordinal),UNIQUE(plan_id,operation_id),
 FOREIGN KEY(plan_id) REFERENCES pb_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(elapsed_wait_ns) BETWEEN 1 AND 20 AND elapsed_wait_ns NOT GLOB '*[^0-9]*'
 AND(elapsed_wait_ns='0' OR substr(elapsed_wait_ns,1,1)!='0') AND instr(elapsed_wait_ns,char(0))=0)
) STRICT;
CREATE TRIGGER pb_use_guard BEFORE INSERT ON pb_use WHEN NOT EXISTS(
 SELECT 1 FROM pb_expected_account a JOIN budget_account o ON o.run_id=a.run_id AND o.generation=a.generation
 JOIN protection_budget_reservation b USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest JOIN sp_plan s ON s.plan_id=a.plan_id
 JOIN sp_plan_commit sk ON sk.plan_id=s.plan_id WHERE a.plan_id=NEW.plan_id AND a.run_id=NEW.run_id AND a.generation=NEW.generation
 AND o.operation_id=NEW.operation_id AND b.profile_digest=NEW.profile_digest AND s.plan_digest=NEW.plan_digest
 AND json_extract(b.budget_body,'$.binding_digest') IS NEW.binding_digest
 AND NEW.ordinal=1+(SELECT count(*) FROM pb_use WHERE operation_id=o.operation_id)
 AND NEW.ordinal<=CAST(json_extract(c.profile_body,'$.episodes') AS INTEGER)
 AND NEW.observed_rows<=NEW.logical_rows AND NEW.observed_bytes<=NEW.logical_bytes
 AND NEW.observed_max_row_bytes<=CAST(json_extract(c.profile_body,'$.max_row_bytes') AS INTEGER)
 AND (length(NEW.elapsed_wait_ns),NEW.elapsed_wait_ns COLLATE BINARY)<(length(json_extract(c.profile_body,'$.max_queue_wait_ns')),json_extract(c.profile_body,'$.max_queue_wait_ns') COLLATE BINARY))
 OR EXISTS(SELECT 1 FROM pb_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'protection_charge_binding_or_capacity'); END;
CREATE TRIGGER pb_shape_guard BEFORE INSERT ON pb_use WHEN NOT EXISTS(
 SELECT 1 FROM pb_shape s JOIN protection_budget_reservation b ON b.operation_id=NEW.operation_id
 WHERE s.plan_id=NEW.plan_id AND s.run_id=NEW.run_id AND s.generation=NEW.generation
 AND json_extract(NEW.shape_body,'$.dependencies') IS CAST(s.dependencies AS TEXT) AND s.dependencies<=CAST(json_extract(b.budget_body,'$.binding.forecast.dependencies') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.runs') IS '1' AND 1<=CAST(json_extract(b.budget_body,'$.binding.forecast.runs') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.executions') IS CAST(s.executions AS TEXT) AND s.executions<=CAST(json_extract(b.budget_body,'$.binding.forecast.executions') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.preparations') IS CAST(s.preparations AS TEXT) AND s.preparations<=CAST(json_extract(b.budget_body,'$.binding.forecast.preparations') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.submissions') IS CAST(s.submissions AS TEXT) AND s.submissions<=CAST(json_extract(b.budget_body,'$.binding.forecast.submissions') AS INTEGER)
 AND json_extract(NEW.shape_body,'$.controller_targets') IS CAST(s.controller_targets AS TEXT) AND s.controller_targets<=CAST(json_extract(b.budget_body,'$.binding.forecast.controller_targets') AS INTEGER)
 AND (SELECT count(*) FROM json_each(NEW.shape_body))=6)
 BEGIN SELECT RAISE(ABORT,'protection_charge_shape'); END;
CREATE TABLE pb_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES protection_plan_registry(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER pb_commit_guard BEFORE INSERT ON pb_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT run_id,generation FROM pb_expected_account WHERE plan_id=NEW.plan_id EXCEPT SELECT run_id,generation FROM pb_use WHERE plan_id=NEW.plan_id)
 OR EXISTS(SELECT run_id,generation FROM pb_use WHERE plan_id=NEW.plan_id EXCEPT SELECT run_id,generation FROM pb_expected_account WHERE plan_id=NEW.plan_id)
 OR NOT EXISTS(SELECT 1 FROM sp_plan_commit WHERE plan_id=NEW.plan_id)
 OR (NOT EXISTS(SELECT 1 FROM pb_expected_account WHERE plan_id=NEW.plan_id) AND NOT EXISTS(SELECT 1 FROM p1_plan WHERE plan_id=NEW.plan_id))
 THEN RAISE(ABORT,'protection_charge_complete_set') END;
END;

CREATE TRIGGER pb_use_update BEFORE UPDATE ON pb_use BEGIN SELECT RAISE(ABORT,'immutable_protection_charge'); END;

CREATE TRIGGER pb_use_delete BEFORE DELETE ON pb_use BEGIN SELECT RAISE(ABORT,'immutable_protection_charge'); END;

CREATE TRIGGER pb_commit_update BEFORE UPDATE ON pb_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_charge'); END;

CREATE TRIGGER pb_commit_delete BEFORE DELETE ON pb_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_charge'); END;

CREATE VIEW pb_balance AS SELECT b.operation_id,o.run_id,o.generation,CAST(json_extract(c.profile_body,'$.episodes') AS INTEGER)-count(u.plan_id) AS episodes_left,coalesce(sum(u.logical_rows),0) AS spent_logical_rows,b.logical_rows-coalesce(sum(u.logical_rows),0) AS held_logical_rows,coalesce(sum(u.logical_bytes),0) AS spent_logical_bytes,b.logical_bytes-coalesce(sum(u.logical_bytes),0) AS held_logical_bytes,coalesce(sum(u.queue_slots),0) AS spent_queue_slots,b.queue_slots-coalesce(sum(u.queue_slots),0) AS held_queue_slots,coalesce(sum(u.work_units),0) AS spent_work_units,b.work_units-coalesce(sum(u.work_units),0) AS held_work_units FROM protection_budget_reservation b JOIN budget_account o USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest LEFT JOIN pb_use u USING(operation_id) GROUP BY b.operation_id;

CREATE TRIGGER pb_cost BEFORE INSERT ON pb_use WHEN NOT EXISTS(SELECT 1 FROM protection_budget_reservation b JOIN arm_capacity c ON c.profile_digest=b.profile_digest WHERE b.operation_id=NEW.operation_id AND NEW.logical_rows=b.logical_rows/CAST(json_extract(c.profile_body,'$.episodes') AS INTEGER) AND NEW.logical_bytes=b.logical_bytes/CAST(json_extract(c.profile_body,'$.episodes') AS INTEGER) AND NEW.queue_slots=b.queue_slots/CAST(json_extract(c.profile_body,'$.episodes') AS INTEGER) AND NEW.work_units=b.work_units/CAST(json_extract(c.profile_body,'$.episodes') AS INTEGER)) BEGIN SELECT RAISE(ABORT,'protection_charge_vector'); END;

CREATE TRIGGER pb_shape_final BEFORE INSERT ON pb_commit WHEN EXISTS(SELECT 1 FROM pb_use u JOIN pb_shape s USING(plan_id,run_id,generation) WHERE u.plan_id=NEW.plan_id AND (json_extract(u.shape_body,'$.dependencies') IS NOT CAST(s.dependencies AS TEXT) OR json_extract(u.shape_body,'$.runs') IS NOT CAST(s.runs AS TEXT) OR json_extract(u.shape_body,'$.executions') IS NOT CAST(s.executions AS TEXT) OR json_extract(u.shape_body,'$.preparations') IS NOT CAST(s.preparations AS TEXT) OR json_extract(u.shape_body,'$.submissions') IS NOT CAST(s.submissions AS TEXT) OR json_extract(u.shape_body,'$.controller_targets') IS NOT CAST(s.controller_targets AS TEXT))) BEGIN SELECT RAISE(ABORT,'protection_charge_final_shape'); END;

-- 两种操作共享预算身份，原件分别保留，不把恢复伪装成普通布防。
CREATE VIEW recovery_budget_operation AS SELECT o.operation_id,o.run_id,e.arm_generation AS generation
 FROM recovery_operation o JOIN execution e ON e.execution_id=o.execution_id;
CREATE TABLE recovery_budget_reservation(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES recovery_operation(operation_id),profile_digest TEXT NOT NULL REFERENCES arm_capacity(profile_digest),
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 preview_digest TEXT NOT NULL,manifest_digest TEXT NOT NULL,request_digest TEXT NOT NULL,
 budget_body BLOB NOT NULL CHECK(json_valid(budget_body)),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 FOREIGN KEY(operation_id) REFERENCES recovery_budget_commit(operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW protection_budget_reservation AS
 SELECT b.*,o.run_id,o.generation,'arm' AS kind FROM arm_budget_reservation b JOIN arm_operation o USING(operation_id)
 UNION ALL SELECT b.operation_id,b.profile_digest,b.logical_rows,b.logical_bytes,b.queue_slots,b.work_units,b.budget_body,b.audit_body,
 o.run_id,o.generation,'recovery' FROM recovery_budget_reservation b JOIN recovery_budget_operation o USING(operation_id);
CREATE TABLE budget_account(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES lifecycle_operation_identity(operation_id),
 run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('arm','recovery')),
 UNIQUE(run_id,generation)
) STRICT;
CREATE TRIGGER budget_account_guard BEFORE INSERT ON budget_account WHEN NOT EXISTS(
 SELECT 1 FROM protection_budget_reservation b JOIN lifecycle_operation_identity i USING(operation_id)
 WHERE b.operation_id=NEW.operation_id AND b.run_id=NEW.run_id AND b.generation=NEW.generation AND b.kind=NEW.kind
 AND i.run_id=b.run_id AND i.kind=b.kind)
 BEGIN SELECT RAISE(ABORT,'budget_account_original'); END;
CREATE TRIGGER budget_account_arm AFTER INSERT ON arm_budget_reservation BEGIN
 INSERT INTO budget_account SELECT operation_id,run_id,generation,'arm' FROM arm_operation WHERE operation_id=NEW.operation_id; END;
CREATE TRIGGER budget_account_recovery AFTER INSERT ON recovery_budget_reservation BEGIN
 INSERT INTO budget_account SELECT operation_id,run_id,generation,'recovery' FROM recovery_budget_operation WHERE operation_id=NEW.operation_id; END;
CREATE VIEW recovery_budget_fit AS SELECT b.operation_id FROM recovery_budget_reservation b JOIN recovery_budget_operation o USING(operation_id)
 WHERE CAST(json_extract(b.budget_body,'$.binding.forecast.dependencies') AS INTEGER)>=(SELECT count(*) FROM p1_dependency WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.executions') AS INTEGER)>=(SELECT count(*) FROM execution WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.preparations') AS INTEGER)>=(SELECT count(*) FROM p1_preparation WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.submissions') AS INTEGER)>=(SELECT count(*) FROM command_submission WHERE run_id=o.run_id)
 AND CAST(json_extract(b.budget_body,'$.binding.forecast.controller_targets') AS INTEGER)>=(SELECT count(*) FROM (
 SELECT controller_authority,controller_database FROM p1_preparation WHERE run_id=o.run_id
 UNION SELECT target_authority,target_database FROM command_submission WHERE run_id=o.run_id));
CREATE TABLE recovery_budget_commit(
 operation_id TEXT PRIMARY KEY NOT NULL REFERENCES recovery_budget_reservation(operation_id),
 binding_digest TEXT NOT NULL,preview_digest TEXT NOT NULL,manifest_digest TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER recovery_budget_commit_guard BEFORE INSERT ON recovery_budget_commit WHEN NOT EXISTS(
 SELECT 1 FROM recovery_budget_reservation b JOIN recovery_operation o USING(operation_id) JOIN pr_commit k USING(operation_id)
 JOIN budget_account a USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest
 JOIN recovery_preview p ON p.preview_id=o.preview_id JOIN execution e ON e.execution_id=o.execution_id
 JOIN run r ON r.run_id=o.run_id JOIN activation_slot s USING(definition_id) JOIN published_version v ON v.definition_id=r.definition_id AND v.version=r.version
 JOIN recovery_budget_fit f USING(operation_id)
 WHERE o.operation_id=NEW.operation_id AND o.state='preparing' AND o.revision='1' AND r.lifecycle='paused' AND r.dispatch_eligible=0
 AND r.active_operation_id=o.operation_id AND r.active_execution_id=o.execution_id AND e.state='prepared' AND r.arm_generation=e.arm_generation
 AND a.run_id=r.run_id AND a.generation=e.arm_generation AND a.kind='recovery'
 AND r.revision=k.run_revision AND s.revision=k.slot_revision AND s.active_run_id=r.run_id AND s.version=r.version
 AND p.consumed_operation_id=o.operation_id AND b.preview_digest=p.preview_digest AND NEW.preview_digest=p.preview_digest
 AND b.manifest_digest=k.manifest_digest AND NEW.manifest_digest=k.manifest_digest AND b.request_digest=o.request_digest
 AND NEW.binding_digest IS json_extract(b.budget_body,'$.binding_digest')
 AND json_extract(b.budget_body,'$.binding.artifact_digest') IS v.artifact_digest
 AND json_extract(b.budget_body,'$.binding.profile_id') IS json_extract(c.profile_body,'$.profile_id')
 AND json_extract(b.budget_body,'$.binding.profile_revision') IS json_extract(c.profile_body,'$.revision')
 AND k.dependency_head=(SELECT coalesce(max(sequence),0) FROM p1_dependency)
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d JOIN ingress_source src USING(source_id) WHERE d.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_deny WHERE run_id=r.run_id AND substr('00000000000000000000'||r.arm_generation,-20)<=generation)
 AND NOT EXISTS(SELECT 1 FROM pb_use WHERE operation_id=o.operation_id))
 BEGIN SELECT RAISE(ABORT,'recovery_budget_seal'); END;
CREATE TRIGGER recovery_start_budget BEFORE INSERT ON execution_start WHEN NOT EXISTS(
 SELECT 1 FROM recovery_budget_commit k JOIN recovery_budget_reservation b USING(operation_id)
 JOIN budget_account a USING(operation_id) JOIN arm_capacity c ON c.profile_digest=b.profile_digest JOIN recovery_budget_fit f USING(operation_id)
 WHERE k.operation_id=NEW.operation_id AND a.run_id=NEW.run_id AND a.kind='recovery'
 AND NOT EXISTS(SELECT 1 FROM pb_use WHERE operation_id=NEW.operation_id))
 BEGIN SELECT RAISE(ABORT,'recovery_start_budget_unavailable'); END;

CREATE TRIGGER recovery_budget_guard BEFORE INSERT ON recovery_budget_reservation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM arm_capacity c JOIN recovery_budget_operation o ON o.operation_id=NEW.operation_id JOIN storage_scope sc ON sc.singleton=1
 WHERE c.profile_digest=NEW.profile_digest AND (SELECT count(*) FROM protection_budget_reservation)<c.max_operations
 AND NEW.logical_rows+coalesce((SELECT sum(logical_rows) FROM protection_budget_reservation),0)<=c.logical_rows
 AND NEW.logical_bytes+coalesce((SELECT sum(logical_bytes) FROM protection_budget_reservation),0)<=c.logical_bytes
 AND NEW.queue_slots+coalesce((SELECT sum(queue_slots) FROM protection_budget_reservation),0)<=c.queue_slots
 AND NEW.work_units+coalesce((SELECT sum(work_units) FROM protection_budget_reservation),0)<=c.work_units
 AND json_extract(NEW.budget_body,'$.binding.operation_id') IS o.operation_id AND json_extract(NEW.budget_body,'$.binding.run_id') IS o.run_id
 AND json_extract(NEW.budget_body,'$.binding.generation') IS o.generation AND json_extract(NEW.budget_body,'$.binding.profile_digest') IS c.profile_digest
 AND json_extract(NEW.budget_body,'$.binding.scope.authority_service_id') IS sc.authority_id
 AND json_extract(NEW.budget_body,'$.binding.scope.database_instance_id') IS sc.database_id
 AND json_extract(NEW.budget_body,'$.state')='held'
 AND json_extract(NEW.budget_body,'$.held.logical_rows') IS CAST(NEW.logical_rows AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.logical_bytes') IS CAST(NEW.logical_bytes AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.queue_slots') IS CAST(NEW.queue_slots AS TEXT)
 AND json_extract(NEW.budget_body,'$.held.work_units') IS CAST(NEW.work_units AS TEXT)) THEN RAISE(ABORT,'recovery_budget_binding_or_capacity') END;
 SELECT CASE WHEN (SELECT count(*) FROM json_each(NEW.budget_body,'$.binding.forecast'))!=6 OR EXISTS(
 SELECT 1 FROM json_each(NEW.budget_body,'$.binding.forecast') f JOIN arm_capacity c ON c.profile_digest=NEW.profile_digest
 WHERE f.key NOT IN ('dependencies','runs','executions','preparations','submissions','controller_targets') OR f.type!='text'
 OR f.value!=CAST(CAST(f.value AS INTEGER) AS TEXT) OR CAST(f.value AS INTEGER) NOT BETWEEN 0 AND 65536
 OR CAST(f.value AS INTEGER)>CAST(json_extract(c.profile_body,'$.max_shape.'||f.key) AS INTEGER))
 THEN RAISE(ABORT,'recovery_budget_shape') END;
 SELECT CASE WHEN NOT EXISTS(WITH x AS(SELECT
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.dependencies') AS INTEGER) AS d,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.runs') AS INTEGER) AS r,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.executions') AS INTEGER) AS e,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.preparations') AS INTEGER) AS p,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.submissions') AS INTEGER) AS s,
 CAST(json_extract(NEW.budget_body,'$.binding.forecast.controller_targets') AS INTEGER) AS t,
 CAST(json_extract(profile_body,'$.episodes') AS INTEGER) AS n,CAST(json_extract(profile_body,'$.max_row_bytes') AS INTEGER) AS m
 FROM arm_capacity WHERE profile_digest=NEW.profile_digest), y AS(SELECT *,32+3*d+6*r+3*e+132*p+3*s+68*t AS rows FROM x)
 SELECT 1 FROM y WHERE r>=1 AND n BETWEEN 1 AND 1024 AND m BETWEEN 1 AND 1048576
 AND NEW.logical_rows=rows*n AND NEW.logical_bytes=rows*(m+512)*n AND NEW.queue_slots=(2*t+p+1)*n AND NEW.work_units=(rows+d+r+e+p+s+t)*n
 AND json_extract(NEW.budget_body,'$.episodes_left') IS CAST(n AS TEXT)
 AND json_extract(NEW.budget_body,'$.spent.logical_rows')='0' AND json_extract(NEW.budget_body,'$.spent.logical_bytes')='0'
 AND json_extract(NEW.budget_body,'$.spent.queue_slots')='0' AND json_extract(NEW.budget_body,'$.spent.work_units')='0')
 THEN RAISE(ABORT,'recovery_budget_cost') END;
END;

CREATE TRIGGER budget_account_update BEFORE UPDATE ON budget_account BEGIN SELECT RAISE(ABORT,'immutable_recovery_budget'); END;

CREATE TRIGGER budget_account_delete BEFORE DELETE ON budget_account BEGIN SELECT RAISE(ABORT,'immutable_recovery_budget'); END;

CREATE TRIGGER recovery_budget_reservation_update BEFORE UPDATE ON recovery_budget_reservation BEGIN SELECT RAISE(ABORT,'immutable_recovery_budget'); END;

CREATE TRIGGER recovery_budget_reservation_delete BEFORE DELETE ON recovery_budget_reservation BEGIN SELECT RAISE(ABORT,'immutable_recovery_budget'); END;

CREATE TRIGGER recovery_budget_commit_update BEFORE UPDATE ON recovery_budget_commit BEGIN SELECT RAISE(ABORT,'immutable_recovery_budget'); END;

CREATE TRIGGER recovery_budget_commit_delete BEFORE DELETE ON recovery_budget_commit BEGIN SELECT RAISE(ABORT,'immutable_recovery_budget'); END;

-- 固定实例来源保护区；只有显式验证的来源故障使用此账户，不替任何run代付。
CREATE TABLE ib_pool(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),authority_id TEXT NOT NULL,database_id TEXT NOT NULL,
 arm_profile_digest TEXT NOT NULL REFERENCES arm_capacity(profile_digest),profile_digest TEXT NOT NULL,profile_body BLOB NOT NULL CHECK(json_valid(profile_body)),
 episodes INTEGER NOT NULL CHECK(episodes BETWEEN 1 AND 65536),per_source_episodes INTEGER NOT NULL CHECK(per_source_episodes BETWEEN 1 AND episodes),
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 total_logical_rows INTEGER NOT NULL CHECK(total_logical_rows BETWEEN 1 AND 1000000000000),total_logical_bytes INTEGER NOT NULL CHECK(total_logical_bytes BETWEEN 1 AND 1000000000000),
 total_queue_slots INTEGER NOT NULL CHECK(total_queue_slots BETWEEN 1 AND 1000000000000),total_work_units INTEGER NOT NULL CHECK(total_work_units BETWEEN 1 AND 1000000000000),
 max_row_bytes INTEGER NOT NULL CHECK(max_row_bytes BETWEEN 1 AND 1048576),max_queue_wait_ns TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK(length(max_queue_wait_ns) BETWEEN 1 AND 20 AND max_queue_wait_ns NOT GLOB '*[^0-9]*' AND substr(max_queue_wait_ns,1,1)!='0' AND instr(max_queue_wait_ns,char(0))=0)
) STRICT;
CREATE TRIGGER ib_pool_binding BEFORE INSERT ON ib_pool WHEN NOT EXISTS(
 SELECT 1 FROM storage_scope sc WHERE sc.authority_id=NEW.authority_id AND sc.database_id=NEW.database_id
 AND json_extract(NEW.profile_body,'$.scope.authority_service_id') IS sc.authority_id
 AND json_extract(NEW.profile_body,'$.scope.database_instance_id') IS sc.database_id
 AND json_extract(NEW.profile_body,'$.arm_profile_digest') IS NEW.arm_profile_digest
 AND json_extract(NEW.profile_body,'$.contract_version')='source-instance-budget/0.1.0-draft.1'
 AND json_extract(NEW.profile_body,'$.purpose')='simulation'
 AND json_extract(NEW.profile_body,'$.episodes') IS CAST(NEW.episodes AS TEXT)
 AND json_extract(NEW.profile_body,'$.per_source_episodes') IS CAST(NEW.per_source_episodes AS TEXT)
 AND json_extract(NEW.profile_body,'$.max_row_bytes') IS CAST(NEW.max_row_bytes AS TEXT)
 AND json_extract(NEW.profile_body,'$.max_queue_wait_ns') IS NEW.max_queue_wait_ns)
 OR EXISTS(SELECT 1 FROM protection_plan_registry) OR EXISTS(SELECT 1 FROM lifecycle_operation_identity)
 BEGIN SELECT RAISE(ABORT,'instance_budget_bootstrap_binding'); END;
CREATE TABLE ib_use(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES p1_plan(plan_id),pool_id INTEGER NOT NULL REFERENCES ib_pool(singleton),source_id TEXT NOT NULL REFERENCES sb_reservation(source_id),
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 65536),source_ordinal INTEGER NOT NULL CHECK(source_ordinal BETWEEN 1 AND 65536),
 profile_digest TEXT NOT NULL,fault_digest TEXT NOT NULL,plan_digest TEXT NOT NULL,
 logical_rows INTEGER NOT NULL CHECK(logical_rows BETWEEN 1 AND 1000000000000),logical_bytes INTEGER NOT NULL CHECK(logical_bytes BETWEEN 1 AND 1000000000000),
 queue_slots INTEGER NOT NULL CHECK(queue_slots BETWEEN 1 AND 1000000000000),work_units INTEGER NOT NULL CHECK(work_units BETWEEN 1 AND 1000000000000),
 observed_rows INTEGER NOT NULL CHECK(observed_rows>0),observed_bytes INTEGER NOT NULL CHECK(observed_bytes>0),observed_max_row_bytes INTEGER NOT NULL CHECK(observed_max_row_bytes>0),
 elapsed_wait_ns TEXT NOT NULL,measurement_body BLOB NOT NULL CHECK(length(measurement_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(pool_id,ordinal),UNIQUE(pool_id,source_id,source_ordinal),
 FOREIGN KEY(plan_id) REFERENCES pb_commit(plan_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(elapsed_wait_ns) BETWEEN 1 AND 20 AND elapsed_wait_ns NOT GLOB '*[^0-9]*' AND(elapsed_wait_ns='0' OR substr(elapsed_wait_ns,1,1)!='0') AND instr(elapsed_wait_ns,char(0))=0)
) STRICT;
CREATE TRIGGER ib_use_guard BEFORE INSERT ON ib_use WHEN NOT EXISTS(
 SELECT 1 FROM p1_plan q JOIN p1_fault f ON f.fault_id=q.fault_id JOIN p1_commit k ON k.plan_id=q.plan_id
 JOIN protection_plan_registry r ON r.source_plan=q.plan_id JOIN sp_plan_commit sk ON sk.plan_id=q.plan_id JOIN ib_pool p ON p.singleton=NEW.pool_id
 WHERE q.plan_id=NEW.plan_id AND q.source_id=NEW.source_id AND f.source_id=NEW.source_id
 AND f.fault_digest=NEW.fault_digest AND q.plan_digest=NEW.plan_digest AND p.profile_digest=NEW.profile_digest
 AND NEW.ordinal=1+(SELECT count(*) FROM ib_use WHERE pool_id=p.singleton) AND NEW.ordinal<=p.episodes
 AND NEW.source_ordinal=1+(SELECT count(*) FROM ib_use WHERE pool_id=p.singleton AND source_id=NEW.source_id) AND NEW.source_ordinal<=p.per_source_episodes
 AND NEW.observed_rows<=NEW.logical_rows AND NEW.observed_bytes<=NEW.logical_bytes AND NEW.observed_max_row_bytes<=p.max_row_bytes
 AND (length(NEW.elapsed_wait_ns),NEW.elapsed_wait_ns COLLATE BINARY)<(length(p.max_queue_wait_ns),p.max_queue_wait_ns COLLATE BINARY))
 OR EXISTS(SELECT 1 FROM pb_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'instance_charge_binding_or_capacity'); END;
CREATE TRIGGER ib_source_complete BEFORE INSERT ON pb_commit WHEN
 EXISTS(SELECT 1 FROM p1_plan WHERE plan_id=NEW.plan_id) AND NOT EXISTS(SELECT 1 FROM ib_use WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'instance_charge_required'); END;

CREATE TRIGGER ib_partition BEFORE INSERT ON ib_pool WHEN NOT EXISTS(SELECT 1 FROM arm_capacity c WHERE c.profile_digest=NEW.arm_profile_digest AND NEW.total_logical_rows=c.logical_rows+NEW.logical_rows*NEW.episodes AND json_extract(NEW.profile_body,'$.total_capacity.logical_rows') IS CAST(NEW.total_logical_rows AS TEXT) AND json_extract(NEW.profile_body,'$.per_episode.logical_rows') IS CAST(NEW.logical_rows AS TEXT) AND NEW.total_logical_bytes=c.logical_bytes+NEW.logical_bytes*NEW.episodes AND json_extract(NEW.profile_body,'$.total_capacity.logical_bytes') IS CAST(NEW.total_logical_bytes AS TEXT) AND json_extract(NEW.profile_body,'$.per_episode.logical_bytes') IS CAST(NEW.logical_bytes AS TEXT) AND NEW.total_queue_slots=c.queue_slots+NEW.queue_slots*NEW.episodes AND json_extract(NEW.profile_body,'$.total_capacity.queue_slots') IS CAST(NEW.total_queue_slots AS TEXT) AND json_extract(NEW.profile_body,'$.per_episode.queue_slots') IS CAST(NEW.queue_slots AS TEXT) AND NEW.total_work_units=c.work_units+NEW.work_units*NEW.episodes AND json_extract(NEW.profile_body,'$.total_capacity.work_units') IS CAST(NEW.total_work_units AS TEXT) AND json_extract(NEW.profile_body,'$.per_episode.work_units') IS CAST(NEW.work_units AS TEXT)) BEGIN SELECT RAISE(ABORT,'instance_budget_partition'); END;

CREATE TRIGGER ib_vector BEFORE INSERT ON ib_use WHEN NOT EXISTS(SELECT 1 FROM ib_pool p WHERE p.singleton=NEW.pool_id AND NEW.logical_rows=p.logical_rows AND NEW.logical_bytes=p.logical_bytes AND NEW.queue_slots=p.queue_slots AND NEW.work_units=p.work_units) BEGIN SELECT RAISE(ABORT,'instance_charge_vector'); END;

CREATE VIEW ib_balance AS SELECT p.singleton,p.episodes-count(u.plan_id) AS episodes_left,p.logical_rows*count(u.plan_id) AS spent_logical_rows,p.logical_rows*(p.episodes-count(u.plan_id)) AS held_logical_rows,p.logical_bytes*count(u.plan_id) AS spent_logical_bytes,p.logical_bytes*(p.episodes-count(u.plan_id)) AS held_logical_bytes,p.queue_slots*count(u.plan_id) AS spent_queue_slots,p.queue_slots*(p.episodes-count(u.plan_id)) AS held_queue_slots,p.work_units*count(u.plan_id) AS spent_work_units,p.work_units*(p.episodes-count(u.plan_id)) AS held_work_units FROM ib_pool p LEFT JOIN ib_use u ON u.pool_id=p.singleton GROUP BY p.singleton;

CREATE TRIGGER ib_pool_update BEFORE UPDATE ON ib_pool BEGIN SELECT RAISE(ABORT,'immutable_instance_budget'); END;

CREATE TRIGGER ib_pool_delete BEFORE DELETE ON ib_pool BEGIN SELECT RAISE(ABORT,'immutable_instance_budget'); END;

CREATE TRIGGER ib_use_update BEFORE UPDATE ON ib_use BEGIN SELECT RAISE(ABORT,'immutable_instance_budget'); END;

CREATE TRIGGER ib_use_delete BEFORE DELETE ON ib_use BEGIN SELECT RAISE(ABORT,'immutable_instance_budget'); END;

CREATE TRIGGER ib_arm_operation_admission BEFORE INSERT ON arm_operation WHEN NOT EXISTS(SELECT 1 FROM ib_balance b JOIN ib_pool p USING(singleton) WHERE b.episodes_left>0
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d WHERE d.run_id=NEW.run_id
 AND (SELECT count(*) FROM ib_use u WHERE u.source_id=d.source_id)>=p.per_source_episodes)) BEGIN SELECT RAISE(ABORT,'instance_budget_unavailable'); END;

CREATE TRIGGER ib_recovery_operation_admission BEFORE INSERT ON recovery_operation WHEN NOT EXISTS(SELECT 1 FROM ib_balance b JOIN ib_pool p USING(singleton) WHERE b.episodes_left>0
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d WHERE d.run_id=NEW.run_id
 AND (SELECT count(*) FROM ib_use u WHERE u.source_id=d.source_id)>=p.per_source_episodes)) BEGIN SELECT RAISE(ABORT,'instance_budget_unavailable'); END;

CREATE TRIGGER ib_execution_start_admission BEFORE INSERT ON execution_start WHEN NOT EXISTS(SELECT 1 FROM ib_balance b JOIN ib_pool p USING(singleton) WHERE b.episodes_left>0
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d WHERE d.run_id=NEW.run_id
 AND (SELECT count(*) FROM ib_use u WHERE u.source_id=d.source_id)>=p.per_source_episodes)) BEGIN SELECT RAISE(ABORT,'instance_budget_unavailable'); END;

CREATE TRIGGER ib_arm_ready_commit_admission BEFORE INSERT ON arm_ready_commit WHEN NOT EXISTS(SELECT 1 FROM ib_balance b JOIN ib_pool p USING(singleton) WHERE b.episodes_left>0
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d WHERE d.run_id=(SELECT run_id FROM arm_operation WHERE operation_id=NEW.operation_id)
 AND (SELECT count(*) FROM ib_use u WHERE u.source_id=d.source_id)>=p.per_source_episodes)) BEGIN SELECT RAISE(ABORT,'instance_budget_unavailable'); END;

-- source对象可为待启用配置；注册、依赖及正式摄取必须有封存的独享保护额度。
CREATE TABLE sb_reservation(
 source_id TEXT PRIMARY KEY NOT NULL REFERENCES ingress_source(source_id),reservation_id TEXT NOT NULL UNIQUE,
 pool_id INTEGER NOT NULL REFERENCES ib_pool(singleton),profile_digest TEXT NOT NULL,
 source_revision TEXT NOT NULL,source_key_digest TEXT NOT NULL,episodes INTEGER NOT NULL CHECK(episodes BETWEEN 1 AND 65536),
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL CHECK(length(actor_body) BETWEEN 1 AND 512),idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL CHECK(json_valid(request_body) AND length(request_body)<=4096),
 UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(source_id) REFERENCES sb_commit(source_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(CAST(source_id AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(reservation_id AS BLOB)) BETWEEN 1 AND 128),
 CHECK(length(CAST(request_epoch AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(idempotency_key AS BLOB)) BETWEEN 1 AND 128),
 CHECK(length(profile_digest)=71 AND length(source_key_digest)=71 AND length(request_digest)=71),
 CHECK(length(source_revision) BETWEEN 1 AND 20 AND source_revision NOT GLOB '*[^0-9]*' AND(source_revision='0' OR substr(source_revision,1,1)!='0') AND instr(source_revision,char(0))=0),
 CHECK(length(CAST(json_array(source_id,reservation_id,pool_id,profile_digest,source_revision,source_key_digest,episodes,request_epoch,
 json_object('blob',lower(hex(actor_body))),idempotency_key,request_digest,json_object('blob',lower(hex(request_body)))) AS BLOB))<=8192)
) STRICT;
CREATE TRIGGER sb_reservation_guard BEFORE INSERT ON sb_reservation WHEN NOT EXISTS(
 SELECT 1 FROM ingress_source s JOIN ib_pool p ON p.singleton=NEW.pool_id WHERE s.source_id=NEW.source_id AND s.state='synchronized'
 AND s.revision=NEW.source_revision AND p.profile_digest=NEW.profile_digest AND NEW.episodes<=p.per_source_episodes
 AND NEW.episodes+coalesce((SELECT sum(episodes) FROM sb_reservation),0)<=p.episodes
 AND json_extract(NEW.request_body,'$.contract_version')='source-budget-admission/0.1.0-draft.1'
 AND json_extract(NEW.request_body,'$.source_id') IS NEW.source_id AND json_extract(NEW.request_body,'$.expected_source_revision') IS NEW.source_revision
 AND json_extract(NEW.request_body,'$.source_key_digest') IS NEW.source_key_digest AND json_extract(NEW.request_body,'$.pool_profile_digest') IS NEW.profile_digest
 AND json_extract(NEW.request_body,'$.episodes') IS CAST(NEW.episodes AS TEXT)
 AND json_extract(NEW.request_body,'$.request_epoch') IS NEW.request_epoch AND CAST(json_extract(NEW.request_body,'$.actor') AS BLOB) IS NEW.actor_body
 AND json_extract(NEW.request_body,'$.idempotency_key') IS NEW.idempotency_key)
 OR EXISTS(SELECT 1 FROM ingress_registry WHERE source_id=NEW.source_id)
 BEGIN SELECT RAISE(ABORT,'source_budget_admission_binding_or_capacity'); END;
CREATE TABLE sb_commit(
 source_id TEXT PRIMARY KEY NOT NULL REFERENCES sb_reservation(source_id),reservation_id TEXT NOT NULL UNIQUE,
 request_digest TEXT NOT NULL,registry_revision TEXT NOT NULL CHECK(registry_revision='1'),
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),notification_body BLOB NOT NULL CHECK(length(notification_body) BETWEEN 1 AND 1024),
 FOREIGN KEY(source_id) REFERENCES ingress_registry(source_id),
 CHECK(length(CAST(source_id AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(reservation_id AS BLOB)) BETWEEN 1 AND 128 AND length(request_digest)=71),
 CHECK(length(CAST(json_array(source_id,reservation_id,request_digest,registry_revision,json_object('blob',lower(hex(audit_body))),json_object('blob',lower(hex(notification_body)))) AS BLOB))<=4096)
) STRICT;
CREATE TRIGGER sb_commit_guard BEFORE INSERT ON sb_commit WHEN NOT EXISTS(
 SELECT 1 FROM sb_reservation b JOIN ingress_source s USING(source_id) JOIN ingress_registry r USING(source_id) JOIN ib_pool p ON p.singleton=b.pool_id
 WHERE b.source_id=NEW.source_id AND b.reservation_id=NEW.reservation_id AND b.request_digest=NEW.request_digest
 AND r.revision=NEW.registry_revision AND s.revision=b.source_revision AND s.state='synchronized' AND p.profile_digest=b.profile_digest
 AND NOT EXISTS(SELECT 1 FROM ib_use WHERE source_id=b.source_id))
 BEGIN SELECT RAISE(ABORT,'source_budget_admission_seal'); END;
CREATE VIEW sb_balance AS SELECT b.source_id,b.reservation_id,b.episodes-count(u.plan_id) AS episodes_left,count(u.plan_id) AS episodes_spent
 FROM sb_reservation b JOIN sb_commit k USING(source_id) LEFT JOIN ib_use u USING(source_id) GROUP BY b.source_id;
CREATE VIEW sb_unallocated AS SELECT p.singleton,p.episodes-coalesce(sum(b.episodes),0) AS unallocated_episodes
 FROM ib_pool p LEFT JOIN sb_reservation b ON b.pool_id=p.singleton GROUP BY p.singleton;
CREATE VIEW sb_run_eligible AS SELECT r.run_id FROM run r WHERE NOT EXISTS(
 SELECT 1 FROM p1_dependency d WHERE d.run_id=r.run_id AND NOT EXISTS(SELECT 1 FROM sb_balance b WHERE b.source_id=d.source_id AND b.episodes_left>0));
CREATE TRIGGER sb_use_guard BEFORE INSERT ON ib_use WHEN NOT EXISTS(
 SELECT 1 FROM sb_reservation b JOIN sb_commit k USING(source_id) WHERE b.source_id=NEW.source_id AND b.pool_id=NEW.pool_id
 AND b.profile_digest=NEW.profile_digest AND NEW.source_ordinal<=b.episodes
 -- 来源准入三行的固定上界也占本份包络，不能把预留元数据当免费。
 AND NEW.observed_rows+3<=NEW.logical_rows AND NEW.observed_bytes+14336<=NEW.logical_bytes)
 BEGIN SELECT RAISE(ABORT,'source_budget_not_reserved_or_exhausted'); END;
CREATE TRIGGER sb_ingress_guard BEFORE INSERT ON ingress_commit WHEN NOT EXISTS(
 SELECT 1 FROM ingress_inbox i JOIN sb_balance b USING(source_id) WHERE i.inbox_id=NEW.inbox_id AND b.episodes_left>0)
 BEGIN SELECT RAISE(ABORT,'source_budget_ingress_unavailable'); END;

CREATE TRIGGER sb_reservation_update BEFORE UPDATE ON sb_reservation BEGIN SELECT RAISE(ABORT,'immutable_source_budget'); END;

CREATE TRIGGER sb_reservation_delete BEFORE DELETE ON sb_reservation BEGIN SELECT RAISE(ABORT,'immutable_source_budget'); END;

CREATE TRIGGER sb_commit_update BEFORE UPDATE ON sb_commit BEGIN SELECT RAISE(ABORT,'immutable_source_budget'); END;

CREATE TRIGGER sb_commit_delete BEFORE DELETE ON sb_commit BEGIN SELECT RAISE(ABORT,'immutable_source_budget'); END;

CREATE TRIGGER sb_arm_operation_admission BEFORE INSERT ON arm_operation WHEN NOT EXISTS(SELECT 1 FROM sb_run_eligible WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'source_budget_run_unavailable'); END;

CREATE TRIGGER sb_recovery_operation_admission BEFORE INSERT ON recovery_operation WHEN NOT EXISTS(SELECT 1 FROM sb_run_eligible WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'source_budget_run_unavailable'); END;

CREATE TRIGGER sb_execution_start_admission BEFORE INSERT ON execution_start WHEN NOT EXISTS(SELECT 1 FROM sb_run_eligible WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'source_budget_run_unavailable'); END;

CREATE TRIGGER sb_arm_ready_commit_admission BEFORE INSERT ON arm_ready_commit WHEN NOT EXISTS(SELECT 1 FROM sb_run_eligible WHERE run_id=(SELECT run_id FROM arm_operation WHERE operation_id=NEW.operation_id)) BEGIN SELECT RAISE(ABORT,'source_budget_run_unavailable'); END;

CREATE TRIGGER sb_step_ready_admission BEFORE INSERT ON step_ready WHEN NOT EXISTS(SELECT 1 FROM sb_run_eligible WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'source_budget_run_unavailable'); END;

CREATE TRIGGER sb_command_submission_admission BEFORE INSERT ON command_submission WHEN NOT EXISTS(SELECT 1 FROM sb_run_eligible WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'source_budget_run_unavailable'); END;

CREATE TRIGGER sb_submission_attempt_admission BEFORE INSERT ON submission_attempt WHEN NOT EXISTS(SELECT 1 FROM sb_run_eligible WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'source_budget_run_unavailable'); END;

CREATE TRIGGER sb_ingress_listener_admission BEFORE INSERT ON ingress_listener WHEN NOT EXISTS(SELECT 1 FROM sb_balance WHERE source_id=NEW.source_id AND episodes_left>0) BEGIN SELECT RAISE(ABORT,'source_budget_unavailable'); END;

CREATE TRIGGER sb_p1_dependency_admission BEFORE INSERT ON p1_dependency WHEN NOT EXISTS(SELECT 1 FROM sb_balance WHERE source_id=NEW.source_id AND episodes_left>0) BEGIN SELECT RAISE(ABORT,'source_budget_unavailable'); END;

-- 保护库存的上包络：动作计划先占位，实际submission用同execution/step替换占位而不重复计数。
CREATE VIEW wb_command_slot AS
 SELECT p.execution_id,p.step_id,e.run_id,e.arm_generation,
 json_extract(p.plan_body,'$.controller_scope.authority_service_id') AS authority,
 json_extract(p.plan_body,'$.controller_scope.database_instance_id') AS database_id
 FROM execution_step_plan p JOIN execution e USING(execution_id) WHERE p.kind='action'
 UNION
 SELECT s.execution_id,s.step_id,s.run_id,e.arm_generation,s.target_authority,s.target_database
 FROM command_submission s JOIN execution e USING(execution_id);
CREATE VIEW wb_shape AS SELECT a.operation_id,a.run_id,a.generation,
 (SELECT count(*) FROM p1_dependency WHERE run_id=a.run_id) AS dependencies,1 AS runs,
 (SELECT count(*) FROM execution WHERE run_id=a.run_id AND substr('00000000000000000000'||arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS executions,
 (SELECT count(*) FROM p1_preparation WHERE run_id=a.run_id AND substr('00000000000000000000'||generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS preparations,
 (SELECT count(*) FROM wb_command_slot WHERE run_id=a.run_id AND substr('00000000000000000000'||arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20)) AS submissions,
 (SELECT count(*) FROM(SELECT p.controller_authority,p.controller_database FROM p1_preparation p WHERE p.run_id=a.run_id AND substr('00000000000000000000'||p.generation,-20)<=substr('00000000000000000000'||a.generation,-20)
 UNION SELECT s.authority,s.database_id FROM wb_command_slot s WHERE s.run_id=a.run_id AND substr('00000000000000000000'||s.arm_generation,-20)<=substr('00000000000000000000'||a.generation,-20))) AS controller_targets
 FROM budget_account a;
CREATE VIEW wb_current_account AS SELECT r.run_id,p.operation_id,p.generation FROM run r JOIN pb_balance p
 ON p.run_id=r.run_id AND p.generation=r.arm_generation WHERE p.episodes_left>0;

-- R2在新预算之前登记execution；仅精确未封存R2允许暂时缺账户，旧反向延迟FK仍要求最后seal。
CREATE TRIGGER wb_execution_account BEFORE INSERT ON execution WHEN NOT EXISTS(
 SELECT 1 FROM wb_current_account a WHERE a.run_id=NEW.run_id AND a.generation=NEW.arm_generation)
 AND NOT EXISTS(SELECT 1 FROM recovery_operation o JOIN run r USING(run_id) WHERE NEW.origin_kind='recovery'
 AND o.operation_id=NEW.recovery_operation_id AND o.execution_id=NEW.execution_id AND o.run_id=NEW.run_id AND o.state='preparing' AND o.revision='1'
 AND NOT EXISTS(SELECT 1 FROM recovery_budget_commit k WHERE k.operation_id=o.operation_id)
 AND r.lifecycle='paused' AND NEW.arm_generation!=r.arm_generation)
 BEGIN SELECT RAISE(ABORT,'workload_account_required'); END;
CREATE TRIGGER wb_preparation_account BEFORE INSERT ON p1_preparation WHEN NOT EXISTS(
 SELECT 1 FROM wb_current_account a WHERE a.run_id=NEW.run_id AND a.generation=NEW.generation)
 AND NOT EXISTS(SELECT 1 FROM recovery_operation o JOIN execution e ON e.execution_id=o.execution_id JOIN run r ON r.run_id=o.run_id
 WHERE NEW.mode='recovery' AND o.operation_id=NEW.recovery_operation_id AND o.execution_id=NEW.execution_id AND o.run_id=NEW.run_id
 AND o.state='preparing' AND o.revision='1' AND r.active_operation_id=o.operation_id AND r.lifecycle='paused'
 AND e.arm_generation=NEW.generation AND r.arm_generation=NEW.generation
 AND NOT EXISTS(SELECT 1 FROM recovery_budget_commit k WHERE k.operation_id=o.operation_id))
 BEGIN SELECT RAISE(ABORT,'workload_preparation_account_required'); END;
CREATE TRIGGER wb_dependency_account BEFORE INSERT ON p1_dependency WHEN NOT EXISTS(
 SELECT 1 FROM wb_current_account WHERE run_id=NEW.run_id)
 AND NOT EXISTS(SELECT 1 FROM run WHERE run_id=NEW.run_id AND arm_generation='0' AND lifecycle='disarmed')
 BEGIN SELECT RAISE(ABORT,'workload_dependency_account_required'); END;

CREATE TRIGGER wb_action_scope BEFORE INSERT ON execution_step_plan WHEN NEW.kind='action' AND (
 NOT json_valid(NEW.plan_body) OR json_type(NEW.plan_body,'$.controller_scope.authority_service_id') IS NOT 'text'
 OR json_type(NEW.plan_body,'$.controller_scope.database_instance_id') IS NOT 'text'
 OR length(json_extract(NEW.plan_body,'$.controller_scope.authority_service_id'))=0
 OR length(json_extract(NEW.plan_body,'$.controller_scope.database_instance_id'))=0)
 BEGIN SELECT RAISE(ABORT,'workload_action_scope_required'); END;
CREATE TRIGGER wb_plan_admission BEFORE UPDATE ON execution_plan_set WHEN NEW.sealed=1 AND (
 NOT EXISTS(SELECT 1 FROM execution e JOIN wb_current_account a ON a.run_id=e.run_id AND a.generation=e.arm_generation WHERE e.execution_id=NEW.execution_id)
 OR EXISTS(SELECT 1 FROM wb_overflow WHERE run_id=NEW.run_id))
 BEGIN SELECT RAISE(ABORT,'workload_plan_unavailable'); END;
CREATE TRIGGER wb_plan_account BEFORE INSERT ON execution_plan_set WHEN NOT EXISTS(
 SELECT 1 FROM execution e JOIN wb_current_account a ON a.run_id=e.run_id AND a.generation=e.arm_generation WHERE e.execution_id=NEW.execution_id)
 BEGIN SELECT RAISE(ABORT,'workload_plan_account_required'); END;
CREATE TRIGGER wb_submission_slot BEFORE INSERT ON command_submission WHEN NOT EXISTS(
 SELECT 1 FROM execution_step_plan p JOIN execution e USING(execution_id) JOIN wb_current_account a ON a.run_id=e.run_id AND a.generation=e.arm_generation
 WHERE p.execution_id=NEW.execution_id AND p.step_id=NEW.step_id AND p.kind='action' AND e.run_id=NEW.run_id
 AND json_extract(p.plan_body,'$.controller_scope.authority_service_id') IS NEW.target_authority
 AND json_extract(p.plan_body,'$.controller_scope.database_instance_id') IS NEW.target_database)
 BEGIN SELECT RAISE(ABORT,'workload_submission_slot_mismatch'); END;

CREATE VIEW wb_overflow AS SELECT s.* FROM wb_shape s JOIN protection_budget_reservation b USING(operation_id) JOIN pb_balance p USING(operation_id) WHERE p.episodes_left>0 AND (s.dependencies>CAST(json_extract(b.budget_body,'$.binding.forecast.dependencies') AS INTEGER) OR s.runs>CAST(json_extract(b.budget_body,'$.binding.forecast.runs') AS INTEGER) OR s.executions>CAST(json_extract(b.budget_body,'$.binding.forecast.executions') AS INTEGER) OR s.preparations>CAST(json_extract(b.budget_body,'$.binding.forecast.preparations') AS INTEGER) OR s.submissions>CAST(json_extract(b.budget_body,'$.binding.forecast.submissions') AS INTEGER) OR s.controller_targets>CAST(json_extract(b.budget_body,'$.binding.forecast.controller_targets') AS INTEGER));

CREATE TRIGGER wb_execution_growth AFTER INSERT ON execution WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'workload_budget_exceeded'); END;

CREATE TRIGGER wb_p1_preparation_growth AFTER INSERT ON p1_preparation WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'workload_budget_exceeded'); END;

CREATE TRIGGER wb_p1_dependency_growth AFTER INSERT ON p1_dependency WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'workload_budget_exceeded'); END;

CREATE TRIGGER wb_command_submission_growth AFTER INSERT ON command_submission WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE run_id=NEW.run_id) BEGIN SELECT RAISE(ABORT,'workload_budget_exceeded'); END;

CREATE TRIGGER wb_execution_step_plan_growth AFTER INSERT ON execution_step_plan WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE run_id=(SELECT run_id FROM execution WHERE execution_id=NEW.execution_id)) BEGIN SELECT RAISE(ABORT,'workload_budget_exceeded'); END;

CREATE TRIGGER wb_arm_register_commit_fit BEFORE INSERT ON arm_register_commit WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE operation_id=NEW.operation_id) BEGIN SELECT RAISE(ABORT,'workload_budget_seal'); END;

CREATE TRIGGER wb_recovery_budget_commit_fit BEFORE INSERT ON recovery_budget_commit WHEN EXISTS(SELECT 1 FROM wb_overflow WHERE operation_id=NEW.operation_id) BEGIN SELECT RAISE(ABORT,'workload_budget_seal'); END;

-- 内部候选：限额为模拟普通存储分区，不向保护池借额度，也不退款。
CREATE TABLE rs_limit(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),purpose TEXT NOT NULL CHECK(purpose='simulation'),
 max_transitions INTEGER NOT NULL CHECK(max_transitions BETWEEN 3 AND 65536),
 max_deltas INTEGER NOT NULL CHECK(max_deltas BETWEEN 1 AND 4096),
 CHECK(max_deltas+2<=max_transitions)
) STRICT;
CREATE TRIGGER rs_limit_initial BEFORE INSERT ON rs_limit WHEN EXISTS(SELECT 1 FROM rs_transition)
 BEGIN SELECT RAISE(ABORT,'resync_limit_already_used'); END;
CREATE TABLE rs_transition(
 transition_id TEXT PRIMARY KEY NOT NULL,baseline_id TEXT NOT NULL REFERENCES rs_transition(transition_id),
 source_id TEXT NOT NULL REFERENCES ingress_source(source_id),fault_id TEXT NOT NULL REFERENCES p1_fault(fault_id),
 kind TEXT NOT NULL CHECK(kind IN ('baseline','delta','ready')),
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,state_before TEXT NOT NULL,state_after TEXT NOT NULL,
 sequence_before TEXT NOT NULL,sequence_after TEXT NOT NULL,floor_before TEXT NOT NULL,floor_after TEXT NOT NULL,
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL CHECK(length(actor_body) BETWEEN 1 AND 512),idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(length(request_digest)=71),request_body BLOB NOT NULL CHECK(json_valid(request_body) AND length(request_body)<=4096),
 UNIQUE(source_id,revision_before),UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(transition_id) REFERENCES rs_commit(transition_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(CAST(transition_id AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(baseline_id AS BLOB)) BETWEEN 1 AND 128),
 CHECK(length(CAST(source_id AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(fault_id AS BLOB)) BETWEEN 1 AND 128),
 CHECK(length(CAST(request_epoch AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(idempotency_key AS BLOB)) BETWEEN 1 AND 128),
 CHECK((kind='baseline' AND transition_id=baseline_id AND state_before='desynchronized' AND state_after='baseline_required')
 OR(kind='delta' AND transition_id!=baseline_id AND state_before='baseline_required' AND state_after='baseline_required' AND floor_after=floor_before)
 OR(kind='ready' AND transition_id!=baseline_id AND state_before='baseline_required' AND state_after='synchronized' AND floor_after=floor_before AND sequence_after=sequence_before)),
 CHECK(length(CAST(json_array(transition_id,baseline_id,source_id,fault_id,kind,revision_before,revision_after,state_before,state_after,sequence_before,sequence_after,floor_before,floor_after,
 request_epoch,json_object('blob',lower(hex(actor_body))),idempotency_key,request_digest,json_object('blob',lower(hex(request_body)))) AS BLOB))<=16384)
) STRICT;
CREATE UNIQUE INDEX rs_one_baseline_per_fault ON rs_transition(fault_id) WHERE kind='baseline';
CREATE UNIQUE INDEX rs_one_ready_per_baseline ON rs_transition(baseline_id) WHERE kind='ready';
CREATE UNIQUE INDEX rs_delta_identity ON rs_transition(source_id,json_extract(request_body,'$.event_ref.scope.authority_service_id'),
 json_extract(request_body,'$.event_ref.scope.database_instance_id'),json_extract(request_body,'$.event_ref.id'),json_extract(request_body,'$.event_ref.revision')) WHERE kind='delta';
CREATE TRIGGER rs_transition_guard BEFORE INSERT ON rs_transition WHEN NOT EXISTS(
 SELECT 1 FROM ingress_source s JOIN sb_reservation b USING(source_id) JOIN sb_balance balance USING(source_id)
 JOIN p1_fault f ON f.fault_id=NEW.fault_id JOIN p1_plan p ON p.fault_id=f.fault_id JOIN pb_commit k ON k.plan_id=p.plan_id JOIN ib_use u ON u.plan_id=p.plan_id
 WHERE s.source_id=NEW.source_id AND f.source_id=s.source_id AND balance.episodes_left>0
 AND s.revision=NEW.revision_before AND s.state=NEW.state_before AND s.contiguous_sequence=NEW.sequence_before AND s.reject_floor=NEW.floor_before
 AND json_extract(NEW.request_body,'$.contract_version') IS 'source-resync/0.1.0-draft.1'
 AND json_extract(NEW.request_body,'$.transition_id') IS NEW.transition_id AND json_extract(NEW.request_body,'$.baseline_id') IS NEW.baseline_id
 AND json_extract(NEW.request_body,'$.source_id') IS NEW.source_id AND json_extract(NEW.request_body,'$.fault_id') IS NEW.fault_id
 AND json_extract(NEW.request_body,'$.kind') IS NEW.kind AND json_extract(NEW.request_body,'$.expected_source_revision') IS NEW.revision_before
 AND json_extract(NEW.request_body,'$.source_key_digest') IS b.source_key_digest
 AND json_extract(NEW.request_body,'$.request_epoch') IS NEW.request_epoch AND CAST(json_extract(NEW.request_body,'$.actor') AS BLOB) IS NEW.actor_body
 AND json_extract(NEW.request_body,'$.idempotency_key') IS NEW.idempotency_key
 AND NOT EXISTS(SELECT 1 FROM p1_plan n WHERE n.source_id=s.source_id AND (length(n.source_after),n.source_after COLLATE BINARY)>(length(p.source_after),p.source_after COLLATE BINARY)))
 BEGIN SELECT RAISE(ABORT,'resync_prestate_or_source'); END;
CREATE TRIGGER rs_baseline_guard BEFORE INSERT ON rs_transition WHEN NEW.kind='baseline' AND (
 NOT EXISTS(SELECT 1 FROM p1_plan WHERE fault_id=NEW.fault_id AND source_after=NEW.revision_before)
 OR json_extract(NEW.request_body,'$.watermark') IS NOT NEW.sequence_after OR NEW.floor_after!=NEW.sequence_after
 OR NEW.sequence_after='99999999999999999999'
 OR (length(NEW.sequence_after),NEW.sequence_after COLLATE BINARY)<(length(NEW.sequence_before),NEW.sequence_before COLLATE BINARY)
 OR (length(NEW.floor_after),NEW.floor_after COLLATE BINARY)<(length(NEW.floor_before),NEW.floor_before COLLATE BINARY)
 OR NOT EXISTS(SELECT 1 FROM rs_limit WHERE singleton=1 AND ((SELECT count(*) FROM rs_transition WHERE kind='baseline')+1)*(max_deltas+2)<=max_transitions))
 BEGIN SELECT RAISE(ABORT,'resync_baseline_frontier_or_capacity'); END;
CREATE TRIGGER rs_follow_guard BEFORE INSERT ON rs_transition WHEN NEW.kind IN ('delta','ready') AND NOT EXISTS(
 SELECT 1 FROM rs_transition b JOIN rs_commit k USING(transition_id) JOIN rs_limit l ON l.singleton=1
 WHERE b.transition_id=NEW.baseline_id AND b.kind='baseline' AND b.source_id=NEW.source_id AND b.fault_id=NEW.fault_id
 AND json_extract(b.request_body,'$.delivery_ref') IS json_extract(NEW.request_body,'$.delivery_ref')
 AND NOT EXISTS(SELECT 1 FROM rs_transition t WHERE t.baseline_id=b.transition_id AND t.kind='ready')
 AND ((NEW.kind='delta' AND json_extract(NEW.request_body,'$.source_sequence') IS NEW.sequence_after
 AND (SELECT count(*) FROM rs_transition t WHERE t.baseline_id=b.transition_id AND t.kind='delta')<l.max_deltas)
 OR(NEW.kind='ready' AND json_extract(NEW.request_body,'$.through_sequence') IS NEW.sequence_before
 AND EXISTS(SELECT 1 FROM rs_transition t JOIN rs_commit c USING(transition_id) WHERE t.transition_id=json_extract(NEW.request_body,'$.last_delta_id')
 AND t.baseline_id=b.transition_id AND t.kind='delta' AND t.revision_after=NEW.revision_before AND t.sequence_after=NEW.sequence_before))))
 BEGIN SELECT RAISE(ABORT,'resync_continuity_or_capacity'); END;
CREATE TRIGGER rs_source_transition BEFORE UPDATE ON ingress_source WHEN (
 NEW.state='baseline_required' OR(NEW.state='synchronized' AND OLD.state!='synchronized')
 OR NEW.reject_floor!=OLD.reject_floor OR(OLD.state!='synchronized' AND NEW.contiguous_sequence!=OLD.contiguous_sequence))
 AND NOT EXISTS(SELECT 1 FROM rs_transition t WHERE t.source_id=OLD.source_id AND t.revision_before=OLD.revision AND t.revision_after=NEW.revision
 AND t.state_before=OLD.state AND t.state_after=NEW.state AND t.sequence_before=OLD.contiguous_sequence AND t.sequence_after=NEW.contiguous_sequence
 AND t.floor_before=OLD.reject_floor AND t.floor_after=NEW.reject_floor AND NOT EXISTS(SELECT 1 FROM rs_commit k WHERE k.transition_id=t.transition_id))
 BEGIN SELECT RAISE(ABORT,'resync_transition_required'); END;
CREATE TABLE rs_commit(
 transition_id TEXT PRIMARY KEY NOT NULL REFERENCES rs_transition(transition_id),request_digest TEXT NOT NULL CHECK(length(request_digest)=71),
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),notification_body BLOB NOT NULL CHECK(length(notification_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE TRIGGER rs_commit_guard BEFORE INSERT ON rs_commit WHEN NOT EXISTS(
 SELECT 1 FROM rs_transition t JOIN ingress_source s USING(source_id) WHERE t.transition_id=NEW.transition_id AND t.request_digest=NEW.request_digest
 AND s.revision=t.revision_after AND s.state=t.state_after AND s.contiguous_sequence=t.sequence_after AND s.reject_floor=t.floor_after)
 BEGIN SELECT RAISE(ABORT,'resync_commit_projection'); END;

-- 保留recovery准备的execution限制，将已有提交条件前移至完整计划封存，避免先发出部分动作。
CREATE TRIGGER rs_plan_preparation BEFORE UPDATE ON execution_plan_set WHEN NEW.sealed=1 AND EXISTS(
 SELECT 1 FROM execution_step_plan a JOIN execution e USING(execution_id) WHERE a.execution_id=NEW.execution_id AND a.kind='action'
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id)
 WHERE p.run_id=e.run_id AND p.generation=e.arm_generation AND(p.execution_id IS NULL OR p.execution_id=e.execution_id OR EXISTS(SELECT 1 FROM cn_step n JOIN cn_current c USING(transfer_id,registration_id) WHERE n.execution_id=e.execution_id AND n.step_id=a.step_id AND n.registration_id=p.registration_id AND n.adoption_digest=c.adoption_digest))
 AND p.controller_authority=json_extract(a.plan_body,'$.controller_scope.authority_service_id')
 AND p.controller_database=json_extract(a.plan_body,'$.controller_scope.database_instance_id') AND q.qualification='observed_applied'))
 BEGIN SELECT RAISE(ABORT,'resync_plan_target_unprepared'); END;
-- 来源变绿不证明Controller关闭。每个来源对该run的最新P1仍须有当前applied观察。
CREATE VIEW rs_pending_protection AS SELECT r.run_id,p.source_id,p.plan_id FROM p1_run r JOIN p1_plan p USING(plan_id)
 JOIN sp_observed_summary s USING(plan_id) WHERE s.observed_state!='applied' AND NOT EXISTS(
 SELECT 1 FROM p1_run nr JOIN p1_plan np USING(plan_id) WHERE nr.run_id=r.run_id AND np.source_id=p.source_id
 AND(length(np.source_after),np.source_after COLLATE BINARY)>(length(p.source_after),p.source_after COLLATE BINARY));
CREATE TRIGGER rs_recovery_start BEFORE INSERT ON execution_start WHEN EXISTS(SELECT 1 FROM rs_pending_protection WHERE run_id=NEW.run_id)
 BEGIN SELECT RAISE(ABORT,'resync_protection_not_observed'); END;

CREATE TRIGGER rs_limit_update BEFORE UPDATE ON rs_limit BEGIN SELECT RAISE(ABORT,'immutable_source_resync'); END;

CREATE TRIGGER rs_limit_delete BEFORE DELETE ON rs_limit BEGIN SELECT RAISE(ABORT,'immutable_source_resync'); END;

CREATE TRIGGER rs_transition_update BEFORE UPDATE ON rs_transition BEGIN SELECT RAISE(ABORT,'immutable_source_resync'); END;

CREATE TRIGGER rs_transition_delete BEFORE DELETE ON rs_transition BEGIN SELECT RAISE(ABORT,'immutable_source_resync'); END;

CREATE TRIGGER rs_commit_update BEFORE UPDATE ON rs_commit BEGIN SELECT RAISE(ABORT,'immutable_source_resync'); END;

CREATE TRIGGER rs_commit_delete BEFORE DELETE ON rs_commit BEGIN SELECT RAISE(ABORT,'immutable_source_resync'); END;

CREATE TRIGGER rs_u20 BEFORE INSERT ON rs_transition WHEN length(NEW.revision_before) NOT BETWEEN 1 AND 20 OR NEW.revision_before GLOB '*[^0-9]*' OR(NEW.revision_before!='0' AND substr(NEW.revision_before,1,1)='0') OR instr(NEW.revision_before,char(0))>0 OR length(NEW.revision_after) NOT BETWEEN 1 AND 20 OR NEW.revision_after GLOB '*[^0-9]*' OR(NEW.revision_after!='0' AND substr(NEW.revision_after,1,1)='0') OR instr(NEW.revision_after,char(0))>0 OR length(NEW.sequence_before) NOT BETWEEN 1 AND 20 OR NEW.sequence_before GLOB '*[^0-9]*' OR(NEW.sequence_before!='0' AND substr(NEW.sequence_before,1,1)='0') OR instr(NEW.sequence_before,char(0))>0 OR length(NEW.sequence_after) NOT BETWEEN 1 AND 20 OR NEW.sequence_after GLOB '*[^0-9]*' OR(NEW.sequence_after!='0' AND substr(NEW.sequence_after,1,1)='0') OR instr(NEW.sequence_after,char(0))>0 OR length(NEW.floor_before) NOT BETWEEN 1 AND 20 OR NEW.floor_before GLOB '*[^0-9]*' OR(NEW.floor_before!='0' AND substr(NEW.floor_before,1,1)='0') OR instr(NEW.floor_before,char(0))>0 OR length(NEW.floor_after) NOT BETWEEN 1 AND 20 OR NEW.floor_after GLOB '*[^0-9]*' OR(NEW.floor_after!='0' AND substr(NEW.floor_after,1,1)='0') OR instr(NEW.floor_after,char(0))>0 BEGIN SELECT RAISE(ABORT,'resync_u20'); END;

CREATE TRIGGER rs_successor BEFORE INSERT ON rs_transition WHEN NOT (substr('00000000000000000000'||NEW.revision_before,-20)!='99999999999999999999' AND substr('00000000000000000000'||NEW.revision_after,-20)=printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),1,10) AS INTEGER)+(CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10) AS INTEGER)=9999999999),(CAST(substr(substr('00000000000000000000'||NEW.revision_before,-20),11,10) AS INTEGER)+1)%10000000000)) OR(NEW.kind='delta' AND NOT (substr('00000000000000000000'||NEW.sequence_before,-20)!='99999999999999999999' AND substr('00000000000000000000'||NEW.sequence_after,-20)=printf('%010d%010d',CAST(substr(substr('00000000000000000000'||NEW.sequence_before,-20),1,10) AS INTEGER)+(CAST(substr(substr('00000000000000000000'||NEW.sequence_before,-20),11,10) AS INTEGER)=9999999999),(CAST(substr(substr('00000000000000000000'||NEW.sequence_before,-20),11,10) AS INTEGER)+1)%10000000000))) BEGIN SELECT RAISE(ABORT,'resync_successor'); END;

CREATE TRIGGER rs_baseline_refs BEFORE INSERT ON rs_transition WHEN NEW.kind='baseline' AND (json_type(NEW.request_body,'$.delivery_ref.scope.authority_service_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.scope.authority_service_id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.scope.database_instance_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.scope.database_instance_id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.revision') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.revision'))=0 OR json_type(NEW.request_body,'$.delivery_ref.digest') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.digest'))=0 OR json_type(NEW.request_body,'$.snapshot_ref.scope.authority_service_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.snapshot_ref.scope.authority_service_id'))=0 OR json_type(NEW.request_body,'$.snapshot_ref.scope.database_instance_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.snapshot_ref.scope.database_instance_id'))=0 OR json_type(NEW.request_body,'$.snapshot_ref.id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.snapshot_ref.id'))=0 OR json_type(NEW.request_body,'$.snapshot_ref.revision') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.snapshot_ref.revision'))=0 OR json_type(NEW.request_body,'$.snapshot_ref.digest') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.snapshot_ref.digest'))=0) BEGIN SELECT RAISE(ABORT,'resync_reference_required'); END;

CREATE TRIGGER rs_delta_refs BEFORE INSERT ON rs_transition WHEN NEW.kind='delta' AND (json_type(NEW.request_body,'$.delivery_ref.scope.authority_service_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.scope.authority_service_id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.scope.database_instance_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.scope.database_instance_id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.revision') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.revision'))=0 OR json_type(NEW.request_body,'$.delivery_ref.digest') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.digest'))=0 OR json_type(NEW.request_body,'$.event_ref.scope.authority_service_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.event_ref.scope.authority_service_id'))=0 OR json_type(NEW.request_body,'$.event_ref.scope.database_instance_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.event_ref.scope.database_instance_id'))=0 OR json_type(NEW.request_body,'$.event_ref.id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.event_ref.id'))=0 OR json_type(NEW.request_body,'$.event_ref.revision') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.event_ref.revision'))=0 OR json_type(NEW.request_body,'$.event_ref.digest') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.event_ref.digest'))=0) BEGIN SELECT RAISE(ABORT,'resync_reference_required'); END;

CREATE TRIGGER rs_ready_refs BEFORE INSERT ON rs_transition WHEN NEW.kind='ready' AND (json_type(NEW.request_body,'$.delivery_ref.scope.authority_service_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.scope.authority_service_id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.scope.database_instance_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.scope.database_instance_id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.id'))=0 OR json_type(NEW.request_body,'$.delivery_ref.revision') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.revision'))=0 OR json_type(NEW.request_body,'$.delivery_ref.digest') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.delivery_ref.digest'))=0 OR json_type(NEW.request_body,'$.checkpoint_ref.scope.authority_service_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.checkpoint_ref.scope.authority_service_id'))=0 OR json_type(NEW.request_body,'$.checkpoint_ref.scope.database_instance_id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.checkpoint_ref.scope.database_instance_id'))=0 OR json_type(NEW.request_body,'$.checkpoint_ref.id') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.checkpoint_ref.id'))=0 OR json_type(NEW.request_body,'$.checkpoint_ref.revision') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.checkpoint_ref.revision'))=0 OR json_type(NEW.request_body,'$.checkpoint_ref.digest') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.checkpoint_ref.digest'))=0) BEGIN SELECT RAISE(ABORT,'resync_reference_required'); END;

-- 追加于109表来源恢复布局；本轮保留原普通触发准备守卫。
CREATE TABLE rc_limit(singleton INTEGER PRIMARY KEY CHECK(singleton=1),max_transfers INTEGER NOT NULL CHECK(max_transfers BETWEEN 1 AND 65536)) STRICT;
CREATE TABLE rc_request(
 transfer_id TEXT PRIMARY KEY NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 operation_id TEXT NOT NULL REFERENCES recovery_operation(operation_id),execution_id TEXT NOT NULL REFERENCES execution(execution_id),
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL CHECK(length(request_body) BETWEEN 1 AND 262144 AND json_valid(request_body)),
 UNIQUE(run_id,generation),UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(transfer_id) REFERENCES rc_request_commit(transfer_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(transfer_id=json_extract(request_body,'$.transfer_id') AND run_id=json_extract(request_body,'$.run_id') AND generation=json_extract(request_body,'$.generation')),
 CHECK(operation_id=json_extract(request_body,'$.recovery_operation_id') AND execution_id=json_extract(request_body,'$.recovery_execution_id')),
 CHECK(request_epoch=json_extract(request_body,'$.request_epoch') AND idempotency_key=json_extract(request_body,'$.idempotency_key') AND request_digest=json_extract(request_body,'$.request_digest')),
 CHECK(json(actor_body)=json(json_extract(request_body,'$.actor')))
) STRICT;
CREATE TABLE rc_target(
 transfer_id TEXT NOT NULL REFERENCES rc_request(transfer_id),registration_id TEXT NOT NULL REFERENCES p1_preparation(registration_id),
 target_body BLOB NOT NULL CHECK(length(target_body) BETWEEN 1 AND 262144 AND json_valid(target_body)),
 PRIMARY KEY(transfer_id,registration_id)
) STRICT;
CREATE TABLE rc_request_commit(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES rc_request(transfer_id),request_digest TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),outbox_body BLOB NOT NULL CHECK(length(outbox_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE TABLE rc_receipt(
 transfer_id TEXT NOT NULL REFERENCES rc_request_commit(transfer_id),registration_id TEXT NOT NULL,
 receipt_digest TEXT NOT NULL,receipt_body BLOB NOT NULL CHECK(length(receipt_body) BETWEEN 1 AND 16384 AND json_valid(receipt_body)),
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),
 PRIMARY KEY(transfer_id,registration_id),FOREIGN KEY(transfer_id,registration_id) REFERENCES rc_target(transfer_id,registration_id),
 CHECK(receipt_digest=json_extract(receipt_body,'$.receipt_digest'))
) STRICT;
CREATE TABLE rc_adoption(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES rc_request_commit(transfer_id),adoption_id TEXT NOT NULL UNIQUE,adoption_digest TEXT NOT NULL,
 adoption_body BLOB NOT NULL CHECK(length(adoption_body) BETWEEN 1 AND 16384 AND json_valid(adoption_body)),
 release_proof_body BLOB NOT NULL CHECK(length(release_proof_body) BETWEEN 1 AND 16384 AND json_valid(release_proof_body)),
 FOREIGN KEY(transfer_id) REFERENCES rc_adoption_commit(transfer_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(transfer_id=json_extract(adoption_body,'$.transfer_id') AND adoption_id=json_extract(adoption_body,'$.adoption_id') AND adoption_digest=json_extract(adoption_body,'$.adoption_digest'))
) STRICT;
CREATE TABLE rc_adoption_commit(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES rc_adoption(transfer_id),adoption_digest TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),outbox_body BLOB NOT NULL CHECK(length(outbox_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE TABLE rc_r5_link(
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES transition_commit(commit_id),transfer_id TEXT NOT NULL UNIQUE REFERENCES rc_adoption_commit(transfer_id),
 adoption_digest TEXT NOT NULL
) STRICT;
CREATE VIEW rc_recovery_current AS SELECT q.* FROM rc_request q JOIN run r USING(run_id) JOIN recovery_operation o ON o.operation_id=q.operation_id
 JOIN recovery_lock lk ON lk.operation_id=o.operation_id JOIN activation_slot sl USING(definition_id)
 WHERE r.arm_generation=q.generation AND r.active_execution_id=q.execution_id AND r.lifecycle='running'
 AND o.execution_id=q.execution_id AND o.run_id=q.run_id AND o.state IN ('running','reconciling') AND lk.release_id IS NULL
 AND sl.active_run_id=r.run_id AND NOT EXISTS(SELECT 1 FROM pause_latch l WHERE l.run_id=r.run_id AND l.cleared_start_id IS NULL)
 AND EXISTS(SELECT 1 FROM step_state st WHERE st.execution_id=q.execution_id)
 AND NOT EXISTS(SELECT 1 FROM step_state st WHERE st.execution_id=q.execution_id AND(st.state!='finished' OR st.outcome!='succeeded'))
 AND NOT EXISTS(SELECT 1 FROM p1_dependency dep JOIN ingress_source src USING(source_id) WHERE dep.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_deny den WHERE den.run_id=r.run_id AND substr('00000000000000000000'||q.generation,-20)<=den.generation)
 AND NOT EXISTS(SELECT 1 FROM rc_target t JOIN pq_current p USING(registration_id) WHERE t.transfer_id=q.transfer_id AND p.qualification!='observed_applied');
CREATE TRIGGER rc_request_guard BEFORE INSERT ON rc_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_limit WHERE (SELECT count(*) FROM rc_request)<max_transfers) THEN RAISE(ABORT,'continuation_capacity') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM storage_scope s WHERE s.authority_id=json_extract(NEW.request_body,'$.origin_scope.authority_service_id') AND s.database_id=json_extract(NEW.request_body,'$.origin_scope.database_instance_id')) THEN RAISE(ABORT,'continuation_origin') END;
END;
CREATE TRIGGER rc_target_guard BEFORE INSERT ON rc_target BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM rc_request_commit WHERE transfer_id=NEW.transfer_id) THEN RAISE(ABORT,'continuation_sealed') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_request q JOIN p1_preparation p ON p.run_id=q.run_id AND p.generation=q.generation
 JOIN json_each(q.request_body,'$.targets') j WHERE q.transfer_id=NEW.transfer_id AND p.registration_id=NEW.registration_id AND p.mode='recovery'
 AND p.execution_id=q.execution_id AND p.recovery_operation_id=q.operation_id AND p.preparation_id=json_extract(NEW.target_body,'$.preparation_ref.id')
 AND p.controller_authority=json_extract(NEW.target_body,'$.controller_scope.authority_service_id') AND p.controller_database=json_extract(NEW.target_body,'$.controller_scope.database_instance_id')
 AND json(j.value)=json(NEW.target_body)) THEN RAISE(ABORT,'continuation_registration') END;
END;
CREATE TRIGGER rc_request_seal BEFORE INSERT ON rc_request_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_recovery_current q WHERE q.transfer_id=NEW.transfer_id AND q.request_digest=NEW.request_digest
 AND (SELECT count(*) FROM rc_target t WHERE t.transfer_id=q.transfer_id)=json_array_length(q.request_body,'$.targets')
 AND (SELECT count(*) FROM rc_target t WHERE t.transfer_id=q.transfer_id)=(SELECT count(*) FROM p1_preparation p WHERE p.run_id=q.run_id AND p.generation=q.generation)) THEN RAISE(ABORT,'continuation_request_seal') END;
END;
CREATE TRIGGER rc_receipt_guard BEFORE INSERT ON rc_receipt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_request q JOIN rc_target t USING(transfer_id) WHERE q.transfer_id=NEW.transfer_id AND t.registration_id=NEW.registration_id
 AND q.request_digest=json_extract(NEW.receipt_body,'$.request_digest') AND json(json_extract(t.target_body,'$.controller_scope'))=json(json_extract(NEW.receipt_body,'$.controller_scope'))
 AND json(json_extract(t.target_body,'$.preparation_ref'))=json(json_extract(NEW.receipt_body,'$.preparation_ref')))
 THEN RAISE(ABORT,'continuation_receipt') END;
END;
CREATE TRIGGER rc_adoption_seal BEFORE INSERT ON rc_adoption_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_adoption a JOIN rc_recovery_current q USING(transfer_id) JOIN run r USING(run_id)
 JOIN activation_slot sl USING(definition_id) JOIN recovery_operation o ON o.operation_id=q.operation_id
 WHERE a.transfer_id=NEW.transfer_id AND a.adoption_digest=NEW.adoption_digest
 AND q.request_digest=json_extract(a.adoption_body,'$.request_digest')
 AND r.revision=json_extract(a.adoption_body,'$.expected_run_revision') AND sl.revision=json_extract(a.adoption_body,'$.expected_slot_revision')
 AND o.revision=json_extract(a.adoption_body,'$.expected_operation_revision')
 AND (SELECT count(*) FROM rc_receipt z WHERE z.transfer_id=q.transfer_id)=json_array_length(q.request_body,'$.targets')
 AND json_array_length(a.adoption_body,'$.receipt_refs')=json_array_length(q.request_body,'$.targets')
 AND NOT EXISTS(SELECT 1 FROM rc_receipt z WHERE z.transfer_id=q.transfer_id AND NOT EXISTS(SELECT 1 FROM json_each(a.adoption_body,'$.receipt_refs') j
 WHERE json_extract(j.value,'$.id')=json_extract(z.receipt_body,'$.receipt_id') AND json_extract(j.value,'$.digest')=z.receipt_digest
 AND json(json_extract(j.value,'$.scope'))=json(json_extract(z.receipt_body,'$.controller_scope'))))) THEN RAISE(ABORT,'continuation_adoption_seal') END;
END;
CREATE TRIGGER rc_r5_guard BEFORE INSERT ON flow_commit_seal WHEN EXISTS(
 SELECT 1 FROM transition_commit c JOIN execution e USING(execution_id) WHERE c.commit_id=NEW.commit_id AND e.origin_kind='recovery') BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM transition_commit c JOIN rc_r5_link l USING(commit_id) JOIN rc_adoption a USING(transfer_id)
 JOIN rc_request q USING(transfer_id) JOIN recovery_lock lk ON lk.operation_id=q.operation_id JOIN external_evidence proof ON proof.evidence_id=lk.release_id
 WHERE c.commit_id=NEW.commit_id AND c.execution_id=q.execution_id AND c.run_id=q.run_id AND l.adoption_digest=a.adoption_digest
 AND proof.body=a.release_proof_body) THEN RAISE(ABORT,'continuation_r5_required') END;
END;

CREATE TRIGGER rc_limit_update BEFORE UPDATE ON rc_limit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_limit_delete BEFORE DELETE ON rc_limit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_request_update BEFORE UPDATE ON rc_request BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_request_delete BEFORE DELETE ON rc_request BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_target_update BEFORE UPDATE ON rc_target BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_target_delete BEFORE DELETE ON rc_target BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_request_commit_update BEFORE UPDATE ON rc_request_commit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_request_commit_delete BEFORE DELETE ON rc_request_commit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_receipt_update BEFORE UPDATE ON rc_receipt BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_receipt_delete BEFORE DELETE ON rc_receipt BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_adoption_update BEFORE UPDATE ON rc_adoption BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_adoption_delete BEFORE DELETE ON rc_adoption BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_adoption_commit_update BEFORE UPDATE ON rc_adoption_commit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_adoption_commit_delete BEFORE DELETE ON rc_adoption_commit BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_r5_link_update BEFORE UPDATE ON rc_r5_link BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_r5_link_delete BEFORE DELETE ON rc_r5_link BEGIN SELECT RAISE(ABORT,'immutable_continuation'); END;

CREATE TRIGGER rc_request_request_body_shape BEFORE INSERT ON rc_request WHEN json_type(NEW.request_body,'$.contract_version') IS NOT 'text' OR json_type(NEW.request_body,'$.origin_scope') IS NOT 'object' OR json_type(NEW.request_body,'$.run_id') IS NOT 'text' OR json_type(NEW.request_body,'$.generation') IS NOT 'text' OR json_type(NEW.request_body,'$.transfer_id') IS NOT 'text' OR json_type(NEW.request_body,'$.recovery_operation_id') IS NOT 'text' OR json_type(NEW.request_body,'$.recovery_execution_id') IS NOT 'text' OR json_type(NEW.request_body,'$.continuation_plan_ref') IS NOT 'object' OR json_type(NEW.request_body,'$.request_epoch') IS NOT 'text' OR json_type(NEW.request_body,'$.actor') IS NOT 'object' OR json_type(NEW.request_body,'$.idempotency_key') IS NOT 'text' OR json_type(NEW.request_body,'$.approval_ref') IS NOT 'object' OR json_type(NEW.request_body,'$.targets') IS NOT 'array' OR json_type(NEW.request_body,'$.request_digest') IS NOT 'text' BEGIN SELECT RAISE(ABORT,'continuation_body_shape'); END;

CREATE TRIGGER rc_receipt_receipt_body_shape BEFORE INSERT ON rc_receipt WHEN json_type(NEW.receipt_body,'$.contract_version') IS NOT 'text' OR json_type(NEW.receipt_body,'$.origin_scope') IS NOT 'object' OR json_type(NEW.receipt_body,'$.run_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.generation') IS NOT 'text' OR json_type(NEW.receipt_body,'$.transfer_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.recovery_operation_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.recovery_execution_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.continuation_plan_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.request_digest') IS NOT 'text' OR json_type(NEW.receipt_body,'$.controller_scope') IS NOT 'object' OR json_type(NEW.receipt_body,'$.receipt_id') IS NOT 'text' OR json_type(NEW.receipt_body,'$.revision') IS NOT 'text' OR json_type(NEW.receipt_body,'$.target_digest') IS NOT 'text' OR json_type(NEW.receipt_body,'$.preparation_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.recovery_grant_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.continuation_grant_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.qualification_ref') IS NOT 'object' OR json_type(NEW.receipt_body,'$.receipt_digest') IS NOT 'text' BEGIN SELECT RAISE(ABORT,'continuation_body_shape'); END;

CREATE TRIGGER rc_adoption_adoption_body_shape BEFORE INSERT ON rc_adoption WHEN json_type(NEW.adoption_body,'$.contract_version') IS NOT 'text' OR json_type(NEW.adoption_body,'$.origin_scope') IS NOT 'object' OR json_type(NEW.adoption_body,'$.run_id') IS NOT 'text' OR json_type(NEW.adoption_body,'$.generation') IS NOT 'text' OR json_type(NEW.adoption_body,'$.transfer_id') IS NOT 'text' OR json_type(NEW.adoption_body,'$.recovery_operation_id') IS NOT 'text' OR json_type(NEW.adoption_body,'$.recovery_execution_id') IS NOT 'text' OR json_type(NEW.adoption_body,'$.continuation_plan_ref') IS NOT 'object' OR json_type(NEW.adoption_body,'$.request_digest') IS NOT 'text' OR json_type(NEW.adoption_body,'$.adoption_id') IS NOT 'text' OR json_type(NEW.adoption_body,'$.revision') IS NOT 'text' OR json_type(NEW.adoption_body,'$.expected_run_revision') IS NOT 'text' OR json_type(NEW.adoption_body,'$.expected_slot_revision') IS NOT 'text' OR json_type(NEW.adoption_body,'$.expected_operation_revision') IS NOT 'text' OR json_type(NEW.adoption_body,'$.receipt_refs') IS NOT 'array' OR json_type(NEW.adoption_body,'$.release_proof_ref') IS NOT 'object' OR json_type(NEW.adoption_body,'$.adoption_digest') IS NOT 'text' BEGIN SELECT RAISE(ABORT,'continuation_body_shape'); END;

CREATE TRIGGER rc_receipt_binding BEFORE INSERT ON rc_receipt WHEN EXISTS(SELECT 1 FROM rc_request q WHERE q.transfer_id=NEW.transfer_id AND(json_extract(NEW.receipt_body,'$.contract_version') IS NOT json_extract(q.request_body,'$.contract_version') OR json_extract(NEW.receipt_body,'$.origin_scope') IS NOT json_extract(q.request_body,'$.origin_scope') OR json_extract(NEW.receipt_body,'$.run_id') IS NOT json_extract(q.request_body,'$.run_id') OR json_extract(NEW.receipt_body,'$.generation') IS NOT json_extract(q.request_body,'$.generation') OR json_extract(NEW.receipt_body,'$.transfer_id') IS NOT json_extract(q.request_body,'$.transfer_id') OR json_extract(NEW.receipt_body,'$.recovery_operation_id') IS NOT json_extract(q.request_body,'$.recovery_operation_id') OR json_extract(NEW.receipt_body,'$.recovery_execution_id') IS NOT json_extract(q.request_body,'$.recovery_execution_id') OR json_extract(NEW.receipt_body,'$.continuation_plan_ref') IS NOT json_extract(q.request_body,'$.continuation_plan_ref') OR json_extract(NEW.receipt_body,'$.request_digest') IS NOT json_extract(q.request_body,'$.request_digest'))) BEGIN SELECT RAISE(ABORT,'continuation_request_binding'); END;

CREATE TRIGGER rc_adoption_binding BEFORE INSERT ON rc_adoption WHEN EXISTS(SELECT 1 FROM rc_request q WHERE q.transfer_id=NEW.transfer_id AND(json_extract(NEW.adoption_body,'$.contract_version') IS NOT json_extract(q.request_body,'$.contract_version') OR json_extract(NEW.adoption_body,'$.origin_scope') IS NOT json_extract(q.request_body,'$.origin_scope') OR json_extract(NEW.adoption_body,'$.run_id') IS NOT json_extract(q.request_body,'$.run_id') OR json_extract(NEW.adoption_body,'$.generation') IS NOT json_extract(q.request_body,'$.generation') OR json_extract(NEW.adoption_body,'$.transfer_id') IS NOT json_extract(q.request_body,'$.transfer_id') OR json_extract(NEW.adoption_body,'$.recovery_operation_id') IS NOT json_extract(q.request_body,'$.recovery_operation_id') OR json_extract(NEW.adoption_body,'$.recovery_execution_id') IS NOT json_extract(q.request_body,'$.recovery_execution_id') OR json_extract(NEW.adoption_body,'$.continuation_plan_ref') IS NOT json_extract(q.request_body,'$.continuation_plan_ref') OR json_extract(NEW.adoption_body,'$.request_digest') IS NOT json_extract(q.request_body,'$.request_digest'))) BEGIN SELECT RAISE(ABORT,'continuation_request_binding'); END;

-- Seamer：普通执行显式采用独立转交资格；原准备行不改为arm。
CREATE TABLE cn_step(
 execution_id TEXT NOT NULL,step_id TEXT NOT NULL,transfer_id TEXT NOT NULL,registration_id TEXT NOT NULL,
 device_id TEXT NOT NULL,adoption_digest TEXT NOT NULL,grant_ref_body BLOB NOT NULL CHECK(json_valid(grant_ref_body)),
 PRIMARY KEY(execution_id,step_id),FOREIGN KEY(execution_id,step_id) REFERENCES execution_step_plan(execution_id,step_id),
 FOREIGN KEY(transfer_id,registration_id) REFERENCES rc_receipt(transfer_id,registration_id),
 FOREIGN KEY(transfer_id) REFERENCES rc_adoption_commit(transfer_id)
) STRICT;
CREATE TABLE cn_withdrawal(
 transfer_id TEXT NOT NULL,registration_id TEXT NOT NULL,proof_body BLOB NOT NULL CHECK(length(proof_body) BETWEEN 1 AND 16384),
 PRIMARY KEY(transfer_id,registration_id),FOREIGN KEY(transfer_id,registration_id) REFERENCES rc_receipt(transfer_id,registration_id),
 FOREIGN KEY(registration_id) REFERENCES pq_fault(registration_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW cn_current AS SELECT q.*,t.registration_id,t.target_body,z.receipt_body,a.adoption_digest,a.adoption_body FROM rc_request q
 JOIN rc_target t USING(transfer_id) JOIN rc_receipt z USING(transfer_id,registration_id) JOIN rc_adoption a USING(transfer_id)
 JOIN rc_adoption_commit ak USING(transfer_id) JOIN rc_r5_link link USING(transfer_id) JOIN flow_commit_seal seal ON seal.commit_id=link.commit_id
 JOIN p1_preparation p USING(registration_id) JOIN pq_current pq USING(registration_id) JOIN run r ON r.run_id=q.run_id
 WHERE r.arm_generation=q.generation AND p.generation=q.generation AND pq.qualification='observed_applied'
 AND link.adoption_digest=a.adoption_digest AND NOT EXISTS(SELECT 1 FROM cn_withdrawal w WHERE w.transfer_id=q.transfer_id AND w.registration_id=t.registration_id)
 AND NOT EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=q.run_id AND d.generation>=substr('00000000000000000000'||q.generation,-20));
CREATE TRIGGER cn_step_guard BEFORE INSERT ON cn_step BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cn_current c JOIN execution e ON e.run_id=c.run_id AND e.arm_generation=c.generation
 JOIN execution_step_plan p ON p.execution_id=e.execution_id JOIN execution_plan_set ps ON ps.execution_id=e.execution_id
 WHERE e.execution_id=NEW.execution_id AND e.origin_kind='trigger' AND e.execution_id!=c.execution_id AND p.step_id=NEW.step_id AND p.kind='action' AND ps.sealed=0
 AND c.transfer_id=NEW.transfer_id AND c.registration_id=NEW.registration_id AND c.adoption_digest=NEW.adoption_digest
 AND json(NEW.grant_ref_body)=json(json_extract(c.receipt_body,'$.continuation_grant_ref'))
 AND NEW.device_id=json_extract(p.plan_body,'$.request.device_id')
 AND NEW.transfer_id=json_extract(p.plan_body,'$.request.continuation.transfer_id') AND NEW.registration_id=json_extract(p.plan_body,'$.request.continuation.registration_id')
 AND NEW.adoption_digest=json_extract(p.plan_body,'$.request.continuation.adoption_digest')
 AND json(NEW.grant_ref_body)=json(json_extract(p.plan_body,'$.request.continuation.grant_ref'))
 AND json(json_extract(p.plan_body,'$.controller_scope'))=json(json_extract(c.target_body,'$.controller_scope'))
 AND EXISTS(SELECT 1 FROM json_each(c.target_body,'$.devices') d WHERE json_extract(d.value,'$.device_id')=NEW.device_id))
 THEN RAISE(ABORT,'continuation_step_binding') END;
END;
CREATE TRIGGER cn_attempt_guard BEFORE INSERT ON submission_attempt WHEN EXISTS(
 SELECT 1 FROM command_submission s JOIN cn_step t USING(execution_id,step_id) WHERE s.submission_id=NEW.submission_id
 AND NOT EXISTS(SELECT 1 FROM cn_current c WHERE c.transfer_id=t.transfer_id AND c.registration_id=t.registration_id AND c.adoption_digest=t.adoption_digest))
 BEGIN SELECT RAISE(ABORT,'continuation_attempt_revoked'); END;
CREATE TRIGGER cn_withdrawal_guard BEFORE INSERT ON cn_withdrawal WHEN NOT EXISTS(
 SELECT 1 FROM rc_request q JOIN rc_target t USING(transfer_id) JOIN p1_preparation p USING(registration_id)
 WHERE q.transfer_id=NEW.transfer_id AND p.registration_id=NEW.registration_id AND p.run_id=q.run_id AND p.generation=q.generation)
 BEGIN SELECT RAISE(ABORT,'continuation_withdrawal_binding'); END;
CREATE TRIGGER cn_withdrawal_seal BEFORE INSERT ON pq_commit WHEN EXISTS(
 SELECT 1 FROM pq_plan p JOIN pq_fault f USING(registration_id) JOIN rc_target t USING(registration_id)
 WHERE p.plan_id=NEW.plan_id AND f.kind='withdrawal' AND json_extract(f.evidence_body,'$.proof_ref.id')=t.transfer_id||'.revocation'
 AND NOT EXISTS(SELECT 1 FROM cn_withdrawal w WHERE w.transfer_id=t.transfer_id AND w.registration_id=t.registration_id))
 BEGIN SELECT RAISE(ABORT,'continuation_withdrawal_required'); END;

CREATE TRIGGER cn_step_update BEFORE UPDATE ON cn_step BEGIN SELECT RAISE(ABORT,'immutable_continuation_link'); END;

CREATE TRIGGER cn_step_delete BEFORE DELETE ON cn_step BEGIN SELECT RAISE(ABORT,'immutable_continuation_link'); END;

CREATE TRIGGER cn_withdrawal_update BEFORE UPDATE ON cn_withdrawal BEGIN SELECT RAISE(ABORT,'immutable_continuation_link'); END;

CREATE TRIGGER cn_withdrawal_delete BEFORE DELETE ON cn_withdrawal BEGIN SELECT RAISE(ABORT,'immutable_continuation_link'); END;

-- 类型化继续运行计划的依赖原件与执行同事务封存。
CREATE TABLE typed_execution_source(
 execution_id TEXT PRIMARY KEY NOT NULL REFERENCES execution(execution_id),
 snapshot_id TEXT NOT NULL REFERENCES ingress_snapshot(snapshot_id),
 definition_version TEXT NOT NULL,
 artifact_ref_body BLOB NOT NULL CHECK(json_valid(artifact_ref_body)),
 input_ref_body BLOB NOT NULL CHECK(json_valid(input_ref_body)),
 parameters_ref_body BLOB NOT NULL CHECK(json_valid(parameters_ref_body)),
 parameters_body BLOB NOT NULL CHECK(json_valid(parameters_body)),
 clock_body BLOB NOT NULL CHECK(json_valid(clock_body))
) STRICT;
CREATE TRIGGER typed_execution_source_update BEFORE UPDATE ON typed_execution_source BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_execution_source_delete BEFORE DELETE ON typed_execution_source BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_source_id_immutable BEFORE UPDATE OF typed_source_id ON execution
 WHEN NEW.typed_source_id IS NOT OLD.typed_source_id BEGIN SELECT RAISE(ABORT,'immutable_typed_source'); END;
CREATE TRIGGER typed_submission_identity_immutable BEFORE UPDATE ON command_submission
 WHEN NEW.issuer_epoch IS NOT OLD.issuer_epoch OR NEW.request_key_body IS NOT OLD.request_key_body
 BEGIN SELECT RAISE(ABORT,'immutable_typed_identity'); END;
CREATE TRIGGER typed_plan_source_seal BEFORE UPDATE OF sealed ON execution_plan_set
 WHEN NEW.sealed=1 AND EXISTS(SELECT 1 FROM execution WHERE execution_id=NEW.execution_id AND typed_source_id IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM typed_execution_source s JOIN execution e USING(execution_id)
 WHERE e.execution_id=NEW.execution_id AND e.typed_source_id=s.execution_id)
 BEGIN SELECT RAISE(ABORT,'typed_source_required_at_seal'); END;
CREATE TRIGGER typed_execution_required BEFORE INSERT ON execution
 WHEN NEW.origin_kind='trigger' AND EXISTS(SELECT 1 FROM rc_request WHERE run_id=NEW.run_id AND generation=NEW.arm_generation)
 BEGIN
 SELECT CASE WHEN NEW.typed_source_id IS NOT NEW.execution_id OR NOT json_valid(NEW.binding_body)
 OR json_extract(NEW.binding_body,'$.binding_version') IS NOT 'continuation-execution/0.1.0-draft.1'
 OR json_extract(NEW.binding_body,'$.authorization_mode') IS NOT 'continuation'
 OR json_extract(NEW.binding_body,'$.execution_id') IS NOT NEW.execution_id
 OR json_extract(NEW.binding_body,'$.run_id') IS NOT NEW.run_id
 OR json_extract(NEW.binding_body,'$.arm_generation') IS NOT NEW.arm_generation
 OR json_extract(NEW.binding_body,'$.binding_digest') IS NOT NEW.binding_digest
 OR json_extract(NEW.binding_body,'$.plan_digest') IS NOT NEW.plan_digest
 OR json_extract(NEW.binding_body,'$.origin.kind') IS NOT 'trigger'
 OR json_extract(NEW.binding_body,'$.origin.decision_id') IS NOT json_extract(NEW.trigger_decision_ref_body,'$.id')
 OR json_extract(NEW.binding_body,'$.origin.decision_digest') IS NOT json_extract(NEW.trigger_decision_ref_body,'$.digest')
 OR json_type(NEW.binding_body,'$.continuations') IS NOT 'array'
 OR json_array_length(NEW.binding_body,'$.continuations')<1
 THEN RAISE(ABORT,'typed_execution_required') END;
END;
CREATE TRIGGER typed_source_binding BEFORE INSERT ON typed_execution_source BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM execution e JOIN ingress_decision d ON d.execution_id=e.execution_id
 JOIN ingress_snapshot s ON s.snapshot_id=d.snapshot_id JOIN run r ON r.run_id=e.run_id JOIN storage_scope sc ON sc.singleton=1
 WHERE e.execution_id=NEW.execution_id AND e.typed_source_id=NEW.execution_id AND NEW.snapshot_id=s.snapshot_id
 AND NEW.definition_version=r.version
 AND json_extract(e.binding_body,'$.scope.authority_service_id')=sc.authority_id
 AND json_extract(e.binding_body,'$.scope.database_instance_id')=sc.database_id
 AND json(NEW.artifact_ref_body)=json(json_extract(e.binding_body,'$.artifact_ref'))
 AND json(NEW.input_ref_body)=json(json_extract(e.binding_body,'$.input_snapshot_ref'))
 AND json_extract(NEW.input_ref_body,'$.object_id')=s.snapshot_id AND json_extract(NEW.input_ref_body,'$.digest')=s.digest
 AND json(NEW.parameters_ref_body)=json(json_extract(e.binding_body,'$.resolved_parameters_ref'))
 AND json(NEW.clock_body)=json(json_extract(e.binding_body,'$.clock')))
 THEN RAISE(ABORT,'typed_source_binding') END;
END;
CREATE TRIGGER typed_submission_body BEFORE INSERT ON command_submission BEGIN
 SELECT CASE WHEN NOT json_valid(NEW.request_body)
 OR json_extract(NEW.request_key_body,'$.issuer_id') IS NOT NEW.issuer_id
 OR json_extract(NEW.request_key_body,'$.issuer_epoch') IS NOT NEW.issuer_epoch
 OR json_extract(NEW.request_key_body,'$.principal_id') IS NOT NEW.principal_id
 OR json_extract(NEW.request_key_body,'$.request_epoch') IS NOT NEW.request_epoch
 OR json_extract(NEW.request_key_body,'$.operation_id') IS NOT NEW.operation_id
 OR json_extract(NEW.request_key_body,'$.idempotency_key') IS NOT NEW.idempotency_key
 OR json_extract(NEW.request_key_body,'$.target_scope.authority_service_id') IS NOT NEW.target_authority
 OR json_extract(NEW.request_key_body,'$.target_scope.database_instance_id') IS NOT NEW.target_database
 OR json_extract(NEW.request_body,'$.idempotency_key') IS NOT NEW.idempotency_key
 OR json_extract(NEW.request_body,'$.origin') IS NOT 'automation'
 OR json_type(NEW.request_body,'$.parameters') IS NOT 'object'
 OR json_type(NEW.request_body,'$.continuation') IS NOT NULL
 OR NOT EXISTS(SELECT 1 FROM execution e JOIN typed_execution_source src USING(execution_id)
 JOIN cn_step n USING(execution_id) WHERE e.execution_id=NEW.execution_id AND n.step_id=NEW.step_id
 AND json_extract(NEW.request_body,'$.automation_binding.execution_id')=e.execution_id
 AND json_extract(NEW.request_body,'$.automation_binding.step_id')=NEW.step_id
 AND json_extract(NEW.request_body,'$.automation_binding.execution_binding_ref.digest')=e.binding_digest
 AND json_extract(NEW.request_body,'$.automation_binding.continuation.transfer_ref.id')=n.transfer_id
 AND json_extract(NEW.request_body,'$.automation_binding.continuation.adoption_ref.digest')=n.adoption_digest
 AND json(json_extract(NEW.request_body,'$.automation_binding.continuation.grant_ref'))=json(n.grant_ref_body))
 THEN RAISE(ABORT,'typed_submission_body') END;
END;

-- 独立、不可变封存行；两向延迟外键要求同事务中既有原件又有sealed=1的父记录。
CREATE TABLE ingress_commit_seal(
 commit_id TEXT PRIMARY KEY NOT NULL,
 sealed INTEGER NOT NULL DEFAULT 1 CHECK(sealed=1),
 UNIQUE(commit_id,sealed),
 FOREIGN KEY(commit_id,sealed) REFERENCES ingress_commit(commit_id,sealed) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER ingress_commit_seal_update BEFORE UPDATE ON ingress_commit_seal BEGIN SELECT RAISE(ABORT,'immutable_ingress_seal'); END;
CREATE TRIGGER ingress_commit_seal_delete BEFORE DELETE ON ingress_commit_seal BEGIN SELECT RAISE(ABORT,'immutable_ingress_seal'); END;
