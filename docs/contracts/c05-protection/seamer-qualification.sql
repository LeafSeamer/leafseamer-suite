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
 FOREIGN KEY(operation_id) REFERENCES pr_commit(operation_id) DEFERRABLE INITIALLY DEFERRED,
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
 target_authority TEXT NOT NULL, target_database TEXT NOT NULL, issuer_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 request_epoch TEXT NOT NULL, operation_id TEXT NOT NULL CHECK(operation_id='createCommand'), idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL, request_body BLOB NOT NULL, parameters_ref_body BLOB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('planned','attempt_recorded','indeterminate','accepted','rejected')),
 attempt_id TEXT UNIQUE, adjudication_id TEXT UNIQUE,
 tx_id TEXT NOT NULL UNIQUE, tx_phase TEXT NOT NULL DEFAULT 'SUBMISSION' CHECK(tx_phase='SUBMISSION'),
 UNIQUE(execution_id,step_id), UNIQUE(submission_id,execution_id,step_id), UNIQUE(submission_id,attempt_id), UNIQUE(submission_id,run_id),
 UNIQUE(target_authority,target_database,issuer_id,principal_id,request_epoch,operation_id,idempotency_key),
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
 FOREIGN KEY(commit_id,required_seal) REFERENCES ingress_commit(commit_id,sealed) DEFERRABLE INITIALLY DEFERRED,
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
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),request_body BLOB NOT NULL CHECK(length(request_body)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(controller_authority,controller_database,preparation_id),
 UNIQUE(recovery_operation_id,recovery_controller_id),
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
 AND ((NEW.mode='arm' AND r.lifecycle='armed') OR(NEW.mode='recovery' AND r.lifecycle='paused' AND r.dispatch_eligible=0
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
 UNION ALL SELECT p.run_id,substr('00000000000000000000'||p.generation,-20) FROM pq_plan p JOIN pq_commit k USING(plan_id)) GROUP BY run_id;
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
 CHECK((source_plan=plan_id AND preparation_plan IS NULL) OR(preparation_plan=plan_id AND source_plan IS NULL)),
 CHECK((source_plan IS NULL)!=(preparation_plan IS NULL))
) STRICT;
CREATE TRIGGER pq_register_source AFTER INSERT ON p1_plan BEGIN
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NEW.plan_id,NULL); END;
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
 INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NEW.plan_id); END;
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
