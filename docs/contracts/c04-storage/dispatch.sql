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
