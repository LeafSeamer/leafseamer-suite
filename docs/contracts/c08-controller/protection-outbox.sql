-- 资源失效通知与CLOSE_GATE投递候选。逻辑正文不可变，发送记录不证明对端已关闭。
CREATE TABLE ro_incident (
 release_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_release_invalidation(release_id),
 device_id TEXT NOT NULL,
 issued_revision TEXT NOT NULL CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*')
) STRICT;
CREATE TABLE ro_target (
 release_id TEXT NOT NULL REFERENCES ro_incident(release_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 intent_id TEXT NOT NULL UNIQUE DEFAULT ('resource.'||lower(hex(randomblob(16)))),
 PRIMARY KEY(release_id,exit_id)
) STRICT;
CREATE TABLE ro_attempt (
 attempt_id TEXT PRIMARY KEY NOT NULL,
 close_id TEXT NOT NULL UNIQUE DEFAULT ('close.'||lower(hex(randomblob(16)))),
 release_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 2147483647),
 message_body BLOB NOT NULL CHECK(length(message_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(release_id,exit_id,ordinal), UNIQUE(attempt_id,release_id,exit_id),
 FOREIGN KEY(release_id,exit_id) REFERENCES ro_target(release_id,exit_id)
) STRICT;
CREATE TABLE ro_ack (
 ack_id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL UNIQUE REFERENCES ro_attempt(attempt_id),
 validation_id TEXT NOT NULL UNIQUE REFERENCES cr_validation(validation_id),
 ack_digest TEXT NOT NULL, ack_body BLOB NOT NULL CHECK(length(ack_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ro_recovery_target (
 recovery_id TEXT NOT NULL REFERENCES cr_recovery(recovery_id),
 release_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 ack_id TEXT REFERENCES ro_ack(ack_id), retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 PRIMARY KEY(recovery_id,release_id,exit_id),
 CHECK((ack_id IS NOT NULL AND retirement_exit_id IS NULL) OR (ack_id IS NULL AND retirement_exit_id IS exit_id)),
 FOREIGN KEY(release_id,exit_id) REFERENCES ro_target(release_id,exit_id),
 FOREIGN KEY(recovery_id) REFERENCES cr_recovery_commit(recovery_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW ro_valid_ack AS
 SELECT a.*,p.release_id,p.exit_id FROM ro_ack a JOIN ro_attempt p USING(attempt_id)
 JOIN cr_valid_validation v USING(validation_id)
 WHERE NOT EXISTS(SELECT 1 FROM ro_attempt newer WHERE newer.release_id=p.release_id
  AND newer.exit_id=p.exit_id AND newer.ordinal>p.ordinal);
CREATE VIEW ro_valid_recovery_target AS
 SELECT r.* FROM ro_recovery_target r WHERE r.retirement_exit_id IS NOT NULL OR EXISTS(
  SELECT 1 FROM ro_valid_ack a WHERE a.ack_id=r.ack_id AND a.release_id=r.release_id AND a.exit_id=r.exit_id);
DROP VIEW cr_device_protection;
CREATE VIEW cr_device_protection AS
 SELECT x.release_id,h.command_id,c.device_id FROM cr_release_invalidation x
 JOIN cr_release r USING(release_id) JOIN cr_hold h USING(hold_id) JOIN ce_command c ON c.command_id=h.command_id
 WHERE NOT EXISTS(SELECT 1 FROM cr_recovery_member m JOIN cr_recovery y USING(recovery_id)
 JOIN cr_recovery_commit k USING(recovery_id) JOIN cr_valid_validation v ON v.validation_id=y.validation_id
 WHERE m.release_id=x.release_id AND y.device_id=c.device_id AND NOT EXISTS(
  SELECT 1 FROM ro_target t WHERE t.release_id=x.release_id AND NOT EXISTS(
   SELECT 1 FROM ro_valid_recovery_target p WHERE p.recovery_id=y.recovery_id
    AND p.release_id=t.release_id AND p.exit_id=t.exit_id)));
CREATE VIEW ro_pending AS
 SELECT t.*,i.device_id FROM ro_target t JOIN ro_incident i USING(release_id)
 WHERE EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=t.exit_id)
 AND NOT EXISTS(SELECT 1 FROM ro_valid_ack a WHERE a.release_id=t.release_id AND a.exit_id=t.exit_id
  AND NOT EXISTS(SELECT 1 FROM ro_recovery_target used JOIN cr_recovery_commit k USING(recovery_id)
   WHERE used.ack_id=a.ack_id));
CREATE TRIGGER ro_capture AFTER INSERT ON cr_release_invalidation BEGIN
 INSERT INTO ro_incident SELECT NEW.release_id,c.device_id,
  (SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
 FROM cr_release r JOIN ce_command c USING(command_id) WHERE r.release_id=NEW.release_id;
 INSERT OR IGNORE INTO ro_target(release_id,exit_id) SELECT i.release_id,e.exit_id FROM ce_exit e
 JOIN ro_incident i USING(device_id) WHERE i.device_id=(SELECT device_id FROM ro_incident WHERE release_id=NEW.release_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id);
END;
CREATE TRIGGER ro_new_exit AFTER INSERT ON ce_exit BEGIN
 INSERT INTO ro_target(release_id,exit_id) SELECT i.release_id,NEW.exit_id FROM ro_incident i
 WHERE i.device_id=NEW.device_id AND EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id);
END;
-- 旧恢复或ACK验证撤回后，为此时已存在的新出口补持久关闭请求。
CREATE TRIGGER ro_revoke_capture AFTER INSERT ON cr_validation_revocation BEGIN
 INSERT OR IGNORE INTO ro_target(release_id,exit_id)
 SELECT i.release_id,e.exit_id FROM ro_incident i JOIN ce_exit e USING(device_id)
 WHERE EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=e.exit_id);
END;
CREATE TRIGGER ro_target_guard BEFORE INSERT ON ro_target BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ro_incident i JOIN ce_exit e USING(device_id)
  WHERE i.release_id=NEW.release_id AND e.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'protection_exit_binding') END;
END;
CREATE TRIGGER ro_incident_guard BEFORE INSERT ON ro_incident BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_release r JOIN ce_command c USING(command_id)
  WHERE r.release_id=NEW.release_id AND c.device_id=NEW.device_id)
  OR NEW.issued_revision!=(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
  THEN RAISE(ABORT,'incident_binding') END;
END;
CREATE TRIGGER ro_attempt_guard BEFORE INSERT ON ro_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ro_pending p WHERE p.release_id=NEW.release_id AND p.exit_id=NEW.exit_id)
  THEN RAISE(ABORT,'close_not_pending') END;
 SELECT CASE WHEN NEW.ordinal!=(SELECT coalesce(max(ordinal),0)+1 FROM ro_attempt
  WHERE release_id=NEW.release_id AND exit_id=NEW.exit_id) THEN RAISE(ABORT,'close_attempt_successor') END;
END;
CREATE TRIGGER ro_ack_guard BEFORE INSERT ON ro_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ro_attempt p JOIN ro_target t USING(release_id,exit_id)
  JOIN ro_incident i USING(release_id) JOIN cr_release r USING(release_id)
  JOIN cr_valid_validation v ON v.validation_id=NEW.validation_id
  WHERE p.attempt_id=NEW.attempt_id AND v.purpose='close' AND v.subject_id=p.close_id
   AND v.subject_digest=NEW.ack_digest AND v.device_id=i.device_id AND v.command_id=r.command_id
   AND v.policy_ref='resource-close/1') THEN RAISE(ABORT,'close_ack_binding') END;
END;
CREATE TRIGGER ro_recovery_seal BEFORE INSERT ON cr_recovery_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT t.release_id,t.exit_id FROM ro_target t JOIN ro_incident i USING(release_id)
  JOIN cr_recovery r USING(device_id) WHERE r.recovery_id=NEW.recovery_id
  EXCEPT SELECT release_id,exit_id FROM ro_recovery_target WHERE recovery_id=NEW.recovery_id)
 OR EXISTS(SELECT release_id,exit_id FROM ro_recovery_target WHERE recovery_id=NEW.recovery_id
  EXCEPT SELECT t.release_id,t.exit_id FROM ro_target t JOIN ro_incident i USING(release_id)
  JOIN cr_recovery r USING(device_id) WHERE r.recovery_id=NEW.recovery_id)
 THEN RAISE(ABORT,'recovery_close_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ro_recovery_target t
  JOIN ro_recovery_target used ON used.ack_id=t.ack_id
  JOIN cr_recovery_commit k ON k.recovery_id=used.recovery_id
  WHERE t.recovery_id=NEW.recovery_id)
 THEN RAISE(ABORT,'recovery_close_consumed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ro_recovery_target t WHERE t.recovery_id=NEW.recovery_id
  AND NOT EXISTS(SELECT 1 FROM ro_valid_recovery_target v WHERE v.recovery_id=t.recovery_id
   AND v.release_id=t.release_id AND v.exit_id=t.exit_id)) THEN RAISE(ABORT,'recovery_close_invalid') END;
END;
CREATE TRIGGER ro_recovery_frozen BEFORE INSERT ON ro_recovery_target
 WHEN EXISTS(SELECT 1 FROM cr_recovery_commit WHERE recovery_id=NEW.recovery_id)
 BEGIN SELECT RAISE(ABORT,'recovery_frozen'); END;
