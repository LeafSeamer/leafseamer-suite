-- 追加于完整Controller准备关闭布局；不会放开命令或最终发送出口。
CREATE TABLE cr_limit(singleton INTEGER PRIMARY KEY CHECK(singleton=1),max_issues INTEGER NOT NULL CHECK(max_issues BETWEEN 1 AND 65536)) STRICT;
CREATE TABLE cr_issue(
 transfer_id TEXT PRIMARY KEY NOT NULL,prep_key TEXT NOT NULL UNIQUE REFERENCES cp_request(prep_key),
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL CHECK(length(request_body) BETWEEN 1 AND 262144 AND json_valid(request_body)),
 target_body BLOB NOT NULL CHECK(length(target_body) BETWEEN 1 AND 262144 AND json_valid(target_body)),
 receipt_id TEXT NOT NULL UNIQUE,receipt_digest TEXT NOT NULL,
 receipt_body BLOB NOT NULL CHECK(length(receipt_body) BETWEEN 1 AND 16384 AND json_valid(receipt_body)),
 grant_id TEXT NOT NULL UNIQUE,grant_body BLOB NOT NULL CHECK(length(grant_body) BETWEEN 1 AND 16384 AND json_valid(grant_body)),
 FOREIGN KEY(transfer_id) REFERENCES cr_commit(transfer_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(transfer_id=json_extract(request_body,'$.transfer_id') AND transfer_id=json_extract(receipt_body,'$.transfer_id')),
 CHECK(request_digest=json_extract(request_body,'$.request_digest') AND request_digest=json_extract(receipt_body,'$.request_digest')),
 CHECK(receipt_id=json_extract(receipt_body,'$.receipt_id') AND receipt_digest=json_extract(receipt_body,'$.receipt_digest')),
 CHECK(grant_id=json_extract(receipt_body,'$.continuation_grant_ref.id') AND grant_id=json_extract(grant_body,'$.ref.id'))
) STRICT;
CREATE TABLE cr_device(
 transfer_id TEXT NOT NULL REFERENCES cr_issue(transfer_id),device_id TEXT NOT NULL,
 control_state_id TEXT NOT NULL REFERENCES ct_state(change_id),device_body BLOB NOT NULL CHECK(json_valid(device_body)),
 PRIMARY KEY(transfer_id,device_id),CHECK(device_id=json_extract(device_body,'$.device_id'))
) STRICT;
CREATE TABLE cr_commit(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_issue(transfer_id),request_digest TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),outbox_body BLOB NOT NULL CHECK(length(outbox_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE TABLE cr_revocation(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_commit(transfer_id),proof_body BLOB NOT NULL CHECK(length(proof_body) BETWEEN 1 AND 16384),
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),outbox_body BLOB NOT NULL CHECK(length(outbox_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE VIEW cr_eligible AS SELECT i.* FROM cr_issue i JOIN cp_request p USING(prep_key) JOIN cp_current c USING(prep_key)
 WHERE c.state='applied' AND NOT EXISTS(SELECT 1 FROM cp_close x WHERE x.prep_key=p.prep_key)
 AND NOT EXISTS(SELECT 1 FROM run_deny_current d WHERE d.origin_authority=p.origin_authority AND d.origin_database=p.origin_database AND d.run_id=p.run_id AND d.generation>=p.generation)
 AND NOT EXISTS(SELECT 1 FROM cr_revocation v WHERE v.transfer_id=i.transfer_id)
 AND NOT EXISTS(SELECT 1 FROM cr_device d WHERE d.transfer_id=i.transfer_id AND NOT EXISTS(
 SELECT 1 FROM ct_current_state s WHERE s.device_id=d.device_id AND s.change_id=d.control_state_id AND s.mode='automatic' AND s.pending_operation_id IS NULL));
CREATE VIEW cr_current AS SELECT i.* FROM cr_eligible i JOIN cr_commit k USING(transfer_id);
CREATE TRIGGER cr_issue_guard BEFORE INSERT ON cr_issue BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_limit WHERE (SELECT count(*) FROM cr_issue)<max_issues) THEN RAISE(ABORT,'continuation_capacity') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cp_request p JOIN cp_grant g USING(prep_key) JOIN controller_scope s ON s.singleton=1
 WHERE p.prep_key=NEW.prep_key AND p.mode='recovery'
 AND p.origin_authority=json_extract(NEW.request_body,'$.origin_scope.authority_service_id') AND p.origin_database=json_extract(NEW.request_body,'$.origin_scope.database_instance_id')
 AND p.run_id=json_extract(NEW.request_body,'$.run_id') AND p.generation=substr('00000000000000000000'||json_extract(NEW.request_body,'$.generation'),-20)
 AND p.execution_id=json_extract(NEW.request_body,'$.recovery_execution_id') AND p.preparation_id=json_extract(NEW.target_body,'$.preparation_ref.id')
 AND p.request_digest=json_extract(NEW.target_body,'$.preparation_ref.digest') AND json_extract(NEW.target_body,'$.preparation_ref.revision')='1'
 AND g.grant_id=json_extract(NEW.target_body,'$.recovery_grant_ref.id') AND g.grant_digest=json_extract(NEW.target_body,'$.recovery_grant_ref.digest')
 AND g.grant_revision=substr('00000000000000000000'||json_extract(NEW.target_body,'$.recovery_grant_ref.revision'),-20) AND NEW.grant_id!=g.grant_id
 AND s.authority_service_id=json_extract(NEW.target_body,'$.controller_scope.authority_service_id') AND s.database_instance_id=json_extract(NEW.target_body,'$.controller_scope.database_instance_id')
 AND p.device_count=json_array_length(NEW.target_body,'$.devices')) THEN RAISE(ABORT,'continuation_parent') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM json_each(NEW.request_body,'$.targets') t WHERE json(t.value)=json(NEW.target_body)) THEN RAISE(ABORT,'continuation_target') END;
END;
CREATE TRIGGER cr_device_guard BEFORE INSERT ON cr_device BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cr_commit WHERE transfer_id=NEW.transfer_id) THEN RAISE(ABORT,'continuation_sealed') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_issue i JOIN cp_request_device p USING(prep_key) JOIN ct_current_state s ON s.device_id=p.device_id
 JOIN json_each(i.target_body,'$.devices') d WHERE i.transfer_id=NEW.transfer_id AND p.device_id=NEW.device_id
 AND s.change_id=NEW.control_state_id AND s.mode='automatic' AND s.pending_operation_id IS NULL
 AND json(d.value)=json(NEW.device_body) AND s.change_id=json_extract(d.value,'$.control_ref.id')
 AND s.record_revision=substr('00000000000000000000'||json_extract(d.value,'$.control_ref.revision'),-20)
 AND s.record_digest=json_extract(d.value,'$.control_ref.digest')) THEN RAISE(ABORT,'continuation_control') END;
END;
CREATE TRIGGER cr_seal BEFORE INSERT ON cr_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cr_eligible i WHERE i.transfer_id=NEW.transfer_id AND i.request_digest=NEW.request_digest
 AND (SELECT count(*) FROM cr_device d WHERE d.transfer_id=i.transfer_id)=json_array_length(i.target_body,'$.devices')
 AND NOT EXISTS(SELECT 1 FROM json_each(i.target_body,'$.devices') j WHERE NOT EXISTS(SELECT 1 FROM cr_device d WHERE d.transfer_id=i.transfer_id AND d.device_id=json_extract(j.value,'$.device_id'))))
 THEN RAISE(ABORT,'continuation_issue_seal') END;
END;
