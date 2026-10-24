-- 内部局部候选：加载在现有Controller候选库中，不是生产迁移或独立身份库。
CREATE TABLE authorization_use (
 use_id TEXT PRIMARY KEY NOT NULL,
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TABLE authorization_floor_event (
 event_id TEXT PRIMARY KEY NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('session','principal','credential','grant','extension','trust')),
 issuer_id TEXT NOT NULL,
 issuer_epoch TEXT NOT NULL,
 target_id TEXT NOT NULL,
 revision_floor TEXT NOT NULL CHECK(length(revision_floor)=20 AND revision_floor NOT GLOB '*[^0-9]*'),
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE INDEX authorization_floor_target ON authorization_floor_event(kind,issuer_id,issuer_epoch,target_id);
CREATE TRIGGER authorization_use_no_update BEFORE UPDATE ON authorization_use BEGIN SELECT RAISE(ABORT,'immutable authorization use'); END;
CREATE TRIGGER authorization_use_no_delete BEFORE DELETE ON authorization_use BEGIN SELECT RAISE(ABORT,'immutable authorization use'); END;
CREATE TRIGGER authorization_floor_no_update BEFORE UPDATE ON authorization_floor_event BEGIN SELECT RAISE(ABORT,'immutable authorization floor'); END;
CREATE TRIGGER authorization_floor_no_delete BEFORE DELETE ON authorization_floor_event BEGIN SELECT RAISE(ABORT,'immutable authorization floor'); END;
CREATE TABLE authorization_challenge (
 challenge_id TEXT PRIMARY KEY NOT NULL,
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TABLE authorization_response (
 response_id TEXT PRIMARY KEY NOT NULL,
 challenge_id TEXT NOT NULL UNIQUE REFERENCES authorization_challenge(challenge_id),
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TRIGGER authorization_challenge_no_update BEFORE UPDATE ON authorization_challenge BEGIN SELECT RAISE(ABORT,'immutable authorization challenge'); END;
CREATE TRIGGER authorization_challenge_no_delete BEFORE DELETE ON authorization_challenge BEGIN SELECT RAISE(ABORT,'immutable authorization challenge'); END;
CREATE TRIGGER authorization_response_no_update BEFORE UPDATE ON authorization_response BEGIN SELECT RAISE(ABORT,'immutable authorization response'); END;
CREATE TRIGGER authorization_response_no_delete BEFORE DELETE ON authorization_response BEGIN SELECT RAISE(ABORT,'immutable authorization response'); END;
CREATE TABLE authorization_command_scope (
 scope_id TEXT PRIMARY KEY NOT NULL,
 digest TEXT NOT NULL UNIQUE,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TABLE authorization_context (
 context_id TEXT PRIMARY KEY NOT NULL,
 namespace_id TEXT NOT NULL REFERENCES ca_namespace(namespace_id),
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TRIGGER authorization_scope_no_update BEFORE UPDATE ON authorization_command_scope BEGIN SELECT RAISE(ABORT,'immutable authorization scope'); END;
CREATE TRIGGER authorization_scope_no_delete BEFORE DELETE ON authorization_command_scope BEGIN SELECT RAISE(ABORT,'immutable authorization scope'); END;
CREATE TRIGGER authorization_context_no_update BEFORE UPDATE ON authorization_context BEGIN SELECT RAISE(ABORT,'immutable authorization context'); END;
CREATE TRIGGER authorization_context_no_delete BEFORE DELETE ON authorization_context BEGIN SELECT RAISE(ABORT,'immutable authorization context'); END;
-- 新提交必须引用此前登记的相同namespace/context；拒收墓碑无transport时沿原规则处理。
CREATE TRIGGER authorization_context_before_request BEFORE INSERT ON ca_request_key
WHEN NEW.transport_body IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM authorization_context c WHERE c.namespace_id=NEW.namespace_id
 AND c.context_id=json_extract(NEW.transport_body,'$.context_id'))
BEGIN SELECT RAISE(ABORT,'request_context_not_registered'); END;
CREATE TRIGGER authorization_target_before_request BEFORE INSERT ON ca_request_key
WHEN NEW.transport_body IS NOT NULL
 AND EXISTS(SELECT 1 FROM authorization_context c WHERE c.context_id=json_extract(NEW.transport_body,'$.context_id'))
 AND NOT EXISTS(
 SELECT 1 FROM authorization_context c JOIN authorization_command_scope s
 ON s.scope_id=json_extract(c.body,'$.original_scope_ref.id') AND s.digest=json_extract(c.body,'$.original_scope_ref.digest')
 WHERE c.namespace_id=NEW.namespace_id AND c.context_id=json_extract(NEW.transport_body,'$.context_id')
 AND EXISTS(SELECT 1 FROM json_each(c.body,'$.operations') WHERE value=NEW.operation_id)
 AND EXISTS(SELECT 1 FROM json_each(s.body,'$.permissions') WHERE value='device.command')
 AND EXISTS(SELECT 1 FROM json_each(s.body,'$.targets') t
 WHERE json_extract(t.value,'$.device_id')=json_extract(NEW.content_body,'$.device_id')
 AND json_extract(t.value,'$.action_id')=json_extract(NEW.content_body,'$.action_id')
 AND json_extract(t.value,'$.capability_version')=json_extract(NEW.content_body,'$.capability_version')))
BEGIN SELECT RAISE(ABORT,'request_context_scope_rejected'); END;
CREATE TABLE authorization_clock_record (
 record_id TEXT PRIMARY KEY NOT NULL,
 binding_digest TEXT NOT NULL,
 sequence TEXT NOT NULL CHECK(length(sequence)=20 AND sequence NOT GLOB '*[^0-9]*'),
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216),
 UNIQUE(binding_digest,sequence)
) STRICT;
CREATE TABLE authorization_validity (
 validity_id TEXT PRIMARY KEY NOT NULL,
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TRIGGER authorization_clock_no_update BEFORE UPDATE ON authorization_clock_record BEGIN SELECT RAISE(ABORT,'immutable authorization clock'); END;
CREATE TRIGGER authorization_clock_no_delete BEFORE DELETE ON authorization_clock_record BEGIN SELECT RAISE(ABORT,'immutable authorization clock'); END;
CREATE TRIGGER authorization_validity_no_update BEFORE UPDATE ON authorization_validity BEGIN SELECT RAISE(ABORT,'immutable authorization validity'); END;
CREATE TRIGGER authorization_validity_no_delete BEFORE DELETE ON authorization_validity BEGIN SELECT RAISE(ABORT,'immutable authorization validity'); END;
-- 每个Controller认证时钟域只保留首次故障，换设备或worker不能清锁。
CREATE TABLE authorization_clock_fault (
 domain_digest TEXT PRIMARY KEY NOT NULL,
 fault_id TEXT UNIQUE NOT NULL,
 digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TRIGGER authorization_clock_fault_no_update BEFORE UPDATE ON authorization_clock_fault BEGIN SELECT RAISE(ABORT,'immutable authentication clock fault'); END;
CREATE TRIGGER authorization_clock_fault_no_delete BEFORE DELETE ON authorization_clock_fault BEGIN SELECT RAISE(ABORT,'immutable authentication clock fault'); END;
