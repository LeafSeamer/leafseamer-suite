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
 AND NEW.run_before!='99999999999999999999' AND NEW.run_after=__DECISION_NEXT__
 AND a.active_run_id=r.run_id AND a.version=r.version AND a.revision!='99999999999999999999'
 AND json_extract(s.body,'$.flow_version')='trigger-flow-storage/0.1.0-draft.1'
 AND json_extract(s.body,'$.run_revision') IS r.revision AND json_extract(s.body,'$.generation') IS r.arm_generation
 AND json_extract(s.body,'$.slot_revision_before') IS a.revision AND json_extract(s.body,'$.slot_revision_after') IS __SLOT_NEXT__
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
 AND (p.execution_id IS NULL OR p.execution_id=e.execution_id) AND q.qualification='observed_applied')
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
 AND NEW.run_revision_before!='99999999999999999999' AND NEW.run_revision_after=__RUN_NEXT__ AND s.revision=NEW.slot_revision
 AND ((e.kind='rule' AND b.run_id IS NULL) OR (e.kind='state_machine' AND b.state_id=e.source_state_id AND b.revision=e.source_state_revision
 AND NEW.source_state_id IS b.state_id AND NEW.source_state_revision IS b.revision AND NEW.target_state_id IS e.target_state_id
 AND NEW.source_state_revision!='99999999999999999999' AND NEW.target_state_revision=__STATE_NEXT__)))
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
