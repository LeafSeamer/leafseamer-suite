-- 扩展同一cr_hold资源权威，不建立第二套风险/释放/恢复状态机。
DROP VIEW cr_release_validation;
CREATE VIEW cr_release_validation AS
 SELECT release_id,validation_id FROM cr_release
 UNION SELECT release_id,cancel_validation_id FROM cr_release WHERE cancel_validation_id IS NOT NULL
 UNION SELECT release_id,closure_validation_id FROM cr_release_attempt
 UNION SELECT m.release_id,s.validation_id FROM cr_release_member m JOIN cr_settlement_validation s USING(settlement_id)
 UNION SELECT release_id,closure_validation_id FROM cx_release_cancel
 UNION SELECT m.release_id,s.validation_id FROM cx_release_member m JOIN cx_settlement s USING(settlement_id);
CREATE TRIGGER ch_hold_guard BEFORE INSERT ON cr_hold WHEN NEW.cancel_execution_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  JOIN cc_valid_closure h ON h.closure_id=p.ordinary_closure_id
  WHERE p.execution_id=NEW.cancel_execution_id AND p.protected_hold_id=NEW.hold_id
   AND p.protected_hold_digest=NEW.hold_digest AND c.command_id=NEW.command_id
   AND v.command_id=NEW.command_id AND v.device_id=cmd.device_id AND v.purpose='hold'
   AND v.subject_id=NEW.hold_id AND v.subject_digest=NEW.hold_digest AND v.policy_ref=NEW.cancel_release_policy_ref)
  THEN RAISE(ABORT,'protected_hold_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_risk_hold h JOIN ce_command c USING(device_id)
  WHERE c.command_id=NEW.command_id AND h.command_id!=NEW.command_id)
  THEN RAISE(ABORT,'resource_busy') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_device_protection p JOIN ce_command c USING(device_id)
  WHERE c.command_id=NEW.command_id) THEN RAISE(ABORT,'device_protected') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_command c JOIN ce_command other USING(device_id)
  JOIN cm_latest r ON r.command_id=other.command_id WHERE c.command_id=NEW.command_id
   AND other.command_id!=NEW.command_id AND r.resource_status!='clear'
   AND EXISTS(SELECT 1 FROM cr_hold h WHERE h.command_id=other.command_id))
  THEN RAISE(ABORT,'command_resource_unresolved') END;
END;
CREATE TRIGGER ch_plan_seal BEFORE INSERT ON cg_plan_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cr_hold h ON h.hold_id=p.protected_hold_id
  WHERE p.execution_id=NEW.execution_id AND h.cancel_execution_id=p.execution_id AND h.attempt_id IS NULL
   AND h.hold_digest=p.protected_hold_digest)
  THEN RAISE(ABORT,'protected_hold_required') END;
END;
CREATE TRIGGER ch_hold_seal BEFORE INSERT ON cr_hold_commit WHEN EXISTS(
 SELECT 1 FROM cr_hold WHERE hold_id=NEW.hold_id AND cancel_execution_id IS NOT NULL) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_hold h JOIN cg_plan_commit p ON p.execution_id=h.cancel_execution_id
  WHERE h.hold_id=NEW.hold_id) THEN RAISE(ABORT,'protected_plan_unsealed') END;
END;
CREATE TRIGGER ch_cancel_permit BEFORE INSERT ON ci_cancel_transmission BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cg_plan p JOIN cr_hold h ON h.hold_id=p.protected_hold_id
  JOIN cr_hold_commit k USING(hold_id) JOIN cr_valid_validation v USING(validation_id)
  WHERE p.execution_id=NEW.execution_id AND h.cancel_execution_id=p.execution_id
   AND h.hold_digest=p.protected_hold_digest AND NOT EXISTS(SELECT 1 FROM cr_hold_close WHERE hold_id=h.hold_id)
   AND NOT EXISTS(SELECT 1 FROM cr_release WHERE hold_id=h.hold_id))
  THEN RAISE(ABORT,'protected_hold_unavailable') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_plan p JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_device_protection x USING(device_id)
  WHERE p.execution_id=NEW.execution_id) THEN RAISE(ABORT,'device_protected') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cg_plan p JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_risk_hold h USING(device_id)
  WHERE p.execution_id=NEW.execution_id AND h.command_id!=c.command_id)
  THEN RAISE(ABORT,'resource_busy') END;
END;
-- 最终发送提交复核：许可预写后撤回准入原件不能绕过。
CREATE TRIGGER ch_cancel_commit BEFORE INSERT ON ci_cancel_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cg_plan p USING(execution_id)
  JOIN cr_hold h ON h.hold_id=p.protected_hold_id WHERE t.permit_id=NEW.permit_id AND
   (NOT EXISTS(SELECT 1 FROM cr_valid_validation v WHERE v.validation_id=h.validation_id)
    OR EXISTS(SELECT 1 FROM cr_release WHERE hold_id=h.hold_id)
    OR EXISTS(SELECT 1 FROM cr_hold_close WHERE hold_id=h.hold_id)))
  THEN RAISE(ABORT,'protected_hold_unavailable') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_device_protection x USING(device_id) WHERE t.permit_id=NEW.permit_id)
  THEN RAISE(ABORT,'device_protected') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission t JOIN cv_cancel c USING(cancellation_id)
  JOIN ce_command cmd USING(command_id) JOIN cr_risk_hold h USING(device_id)
  WHERE t.permit_id=NEW.permit_id AND h.command_id!=c.command_id)
  THEN RAISE(ABORT,'resource_busy') END;
END;
CREATE TRIGGER ch_release_seal BEFORE INSERT ON cr_release_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_release r JOIN cr_hold h USING(hold_id)
  WHERE r.release_id=NEW.release_id AND ((h.cancel_execution_id IS NULL AND r.cancel_validation_id IS NOT NULL)
   OR (h.cancel_execution_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cr_valid_validation v
     JOIN ce_command cmd ON cmd.command_id=h.command_id WHERE v.validation_id=r.cancel_validation_id
      AND v.command_id=h.command_id AND v.device_id=cmd.device_id AND v.purpose='release'
      AND v.subject_id=r.release_id AND v.subject_digest=r.release_digest AND v.policy_ref=h.cancel_release_policy_ref))))
  THEN RAISE(ABORT,'protected_release_policy') END;
END;
