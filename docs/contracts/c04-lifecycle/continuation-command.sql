-- Controller：新普通命令沿原准备归属，同时明确引用新grant和Seamer采用。
CREATE TABLE cn_command(
 command_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_command(command_id),transfer_id TEXT NOT NULL REFERENCES cr_commit(transfer_id),
 execution_id TEXT NOT NULL,step_id TEXT NOT NULL,submission_id TEXT NOT NULL,request_digest TEXT NOT NULL,
 adoption_digest TEXT NOT NULL,grant_ref_body BLOB NOT NULL CHECK(length(grant_ref_body) BETWEEN 1 AND 16384 AND json_valid(grant_ref_body)),
 binding_body BLOB NOT NULL CHECK(length(binding_body) BETWEEN 1 AND 16384 AND json_valid(binding_body)),
 UNIQUE(transfer_id,execution_id,step_id)
) STRICT;
CREATE VIEW cn_live_command AS SELECT n.* FROM cn_command n JOIN cr_current c USING(transfer_id) JOIN ce_command e USING(command_id)
 WHERE e.prep_key=c.prep_key AND json(n.grant_ref_body)=json(json_extract(c.receipt_body,'$.continuation_grant_ref'));
CREATE TRIGGER cn_command_guard BEFORE INSERT ON cn_command BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_current c JOIN cp_request p USING(prep_key) JOIN ce_command e ON e.prep_key=c.prep_key
 JOIN ca_command_initial i ON i.command_id=e.command_id JOIN ca_request_key k ON k.key_id=i.key_id
 WHERE e.command_id=NEW.command_id AND c.transfer_id=NEW.transfer_id AND e.origin='automation'
 AND e.device_id=k.device_id AND k.device_id=json_extract(k.content_body,'$.device_id')
 AND NEW.execution_id!=p.execution_id AND NEW.execution_id=json_extract(e.binding_body,'$.execution_id')
 AND NEW.step_id=json_extract(e.binding_body,'$.step_id') AND NEW.submission_id=json_extract(e.binding_body,'$.submission_id')
 AND NEW.request_digest=k.request_digest AND NEW.adoption_digest=json_extract(k.content_body,'$.continuation.adoption_digest')
 AND NEW.transfer_id=json_extract(k.content_body,'$.continuation.transfer_id')
 AND json(NEW.grant_ref_body)=json(json_extract(c.receipt_body,'$.continuation_grant_ref'))
 AND json(NEW.grant_ref_body)=json(json_extract(k.content_body,'$.continuation.grant_ref'))
 AND EXISTS(SELECT 1 FROM cr_device d WHERE d.transfer_id=c.transfer_id AND d.device_id=e.device_id))
 THEN RAISE(ABORT,'continuation_command_binding') END;
END;
CREATE TRIGGER cn_accept_guard BEFORE INSERT ON ca_commit WHEN NEW.kind='accept' BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ca_command_initial i JOIN ce_command e USING(command_id) JOIN cp_request p USING(prep_key) JOIN ca_request_key k ON k.key_id=i.key_id
 WHERE i.key_id=NEW.key_id AND e.origin='automation' AND p.mode='recovery' AND (json_extract(e.binding_body,'$.execution_id') IS NOT p.execution_id OR json_type(k.content_body,'$.continuation') IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM cn_live_command n WHERE n.command_id=e.command_id)) THEN RAISE(ABORT,'continuation_admission_required') END;
END;
CREATE TRIGGER cn_controller_attempt BEFORE INSERT ON ce_attempt WHEN EXISTS(SELECT 1 FROM cn_command WHERE command_id=NEW.command_id)
 AND NOT EXISTS(SELECT 1 FROM cn_live_command WHERE command_id=NEW.command_id) BEGIN SELECT RAISE(ABORT,'continuation_command_revoked'); END;
CREATE TRIGGER cn_controller_send BEFORE INSERT ON ce_transmission_commit WHEN EXISTS(
 SELECT 1 FROM ce_permit p JOIN ce_attempt a USING(attempt_id) JOIN cn_command n USING(command_id) WHERE p.permit_id=NEW.permit_id
 AND NOT EXISTS(SELECT 1 FROM cn_live_command live WHERE live.command_id=n.command_id)) BEGIN SELECT RAISE(ABORT,'continuation_command_revoked'); END;
