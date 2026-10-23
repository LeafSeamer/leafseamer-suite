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
