-- 原出口socket身份来源候选；不证明OS或线路真实性。
CREATE TABLE cs_socket(
 exit_id TEXT PRIMARY KEY REFERENCES ce_exit(exit_id),
 socket_instance_id TEXT NOT NULL UNIQUE,
 registration_digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216),
 audit_body BLOB NOT NULL CHECK(audit_body=body)
) STRICT;
CREATE TRIGGER cs_socket_guard BEFORE INSERT ON cs_socket BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_packet WHERE exit_id=NEW.exit_id)
 OR EXISTS(SELECT 1 FROM cc_prepare WHERE exit_id=NEW.exit_id)
 OR EXISTS(SELECT 1 FROM cv_cancel_target WHERE exit_id=NEW.exit_id)
 THEN RAISE(ABORT,'cancel_socket_registered_too_late') END;
END;
CREATE TRIGGER cs_socket_u BEFORE UPDATE ON cs_socket BEGIN SELECT RAISE(ABORT,'immutable_cancel_socket'); END;
CREATE TRIGGER cs_socket_d BEFORE DELETE ON cs_socket BEGIN SELECT RAISE(ABORT,'immutable_cancel_socket'); END;
