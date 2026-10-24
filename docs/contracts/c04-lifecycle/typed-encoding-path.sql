-- 类型化普通编码候选：保持取消旧路径；来源失效后不能开始或采用普通编码。
CREATE VIEW ep_open_request AS SELECT b.* FROM te_base_ep_open_request b
 WHERE b.kind!='ordinary' OR NOT EXISTS(SELECT 1 FROM cn_command n WHERE n.command_id=b.command_id)
 OR EXISTS(SELECT 1 FROM cn_live_command n WHERE n.command_id=b.command_id);
CREATE TRIGGER te_request_current BEFORE INSERT ON ep_request WHEN NEW.kind='ordinary' BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cn_command WHERE command_id=NEW.command_id)
 AND NOT EXISTS(SELECT 1 FROM cn_live_command WHERE command_id=NEW.command_id)
 THEN RAISE(ABORT,'typed_encoding_origin_revoked') END;
 SELECT CASE WHEN json_valid(NEW.authorization_body)=0 THEN RAISE(ABORT,'typed_encoding_authorization_json') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_exit e JOIN controller_scope s ON s.singleton=1 WHERE e.exit_id=NEW.exit_id
 AND json_extract(NEW.authorization_body,'$.format_version') IS 'encoding-authorization/0.1.0-draft.1'
 AND json_extract(NEW.authorization_body,'$.authorization_id') IS NEW.authorization_id
 AND json_extract(NEW.authorization_body,'$.authorization_digest') IS NEW.authorization_digest
 AND json_extract(NEW.authorization_body,'$.target.kind') IS 'ordinary'
 AND json_extract(NEW.authorization_body,'$.target.command_ref.id') IS NEW.command_id
 AND json_extract(NEW.authorization_body,'$.target.proposed_attempt_id') IS NEW.proposed_attempt_id
 AND json_extract(NEW.authorization_body,'$.content_digest') IS NEW.request_digest
 AND json_extract(NEW.authorization_body,'$.binding.scope.authority_service_id') IS s.authority_service_id
 AND json_extract(NEW.authorization_body,'$.binding.scope.database_instance_id') IS s.database_instance_id
 AND json_extract(NEW.authorization_body,'$.binding.writer_exit_id') IS e.exit_id
 AND json_extract(NEW.authorization_body,'$.binding.device_id') IS e.device_id
 AND json_extract(NEW.authorization_body,'$.binding.device_session_id') IS e.device_session_id
 AND json_extract(NEW.authorization_body,'$.binding.worker_boot_id') IS e.worker_boot_id
 AND json_extract(NEW.authorization_body,'$.binding.controller_boot_id') IS e.controller_boot_id
 AND json_extract(NEW.authorization_body,'$.binding.ipc_session_id') IS e.ipc_session_id
 AND json_extract(NEW.authorization_body,'$.binding.clock_domain_id') IS e.clock_domain_id
 AND json_extract(NEW.authorization_body,'$.binding.descriptor_digest') IS e.descriptor_digest
 AND json_extract(NEW.authorization_body,'$.requester.issuer_id') IS NEW.issuer_id
 AND json_extract(NEW.authorization_body,'$.requester.issuer_epoch') IS NEW.issuer_epoch
 AND json_extract(NEW.authorization_body,'$.requester.principal_id') IS NEW.principal_id
 AND json_extract(NEW.authorization_body,'$.primitive_id') IS NEW.primitive_id
 AND json_extract(NEW.authorization_body,'$.encoding_reservation_ref.id') IS NEW.reservation_id
 AND substr('00000000000000000000'||json_extract(NEW.authorization_body,'$.encoding_reservation_ref.revision'),-20) IS NEW.reservation_revision
 AND json_extract(NEW.authorization_body,'$.encoding_reservation_ref.digest') IS NEW.reservation_digest
 AND json_extract(NEW.authorization_body,'$.max_bytes') IS NEW.max_bytes
 AND substr('00000000000000000000'||json_extract(NEW.authorization_body,'$.created_tick_ns'),-20) IS NEW.created_tick
 AND substr('00000000000000000000'||json_extract(NEW.authorization_body,'$.expires_tick_ns'),-20) IS NEW.expires_tick)
 THEN RAISE(ABORT,'typed_encoding_authorization_columns') END;
END;
CREATE TRIGGER te_request_seal BEFORE INSERT ON ep_request_commit WHEN EXISTS(
 SELECT 1 FROM ep_request r JOIN cn_command n USING(command_id) WHERE r.prepare_id=NEW.prepare_id AND r.kind='ordinary'
 AND NOT EXISTS(SELECT 1 FROM cn_live_command c WHERE c.command_id=r.command_id))
 BEGIN SELECT RAISE(ABORT,'typed_encoding_origin_revoked'); END;
CREATE TRIGGER te_reply_packet BEFORE INSERT ON ep_reply WHEN NEW.outcome='prepared' AND EXISTS(
 SELECT 1 FROM ep_request r WHERE r.prepare_id=NEW.prepare_id AND r.kind='ordinary') BEGIN
 SELECT CASE WHEN json_valid(NEW.packet_body)=0 THEN RAISE(ABORT,'typed_packet_json') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ce_exit e USING(exit_id) WHERE r.prepare_id=NEW.prepare_id
 AND json_extract(NEW.packet_body,'$.packet_id') IS NEW.packet_id
 AND json_extract(NEW.packet_body,'$.packet_digest') IS NEW.packet_digest
 AND json_extract(NEW.packet_body,'$.command_id') IS r.command_id
 AND json_extract(NEW.packet_body,'$.attempt_id') IS r.proposed_attempt_id
 AND json_extract(NEW.packet_body,'$.primitive_id') IS r.primitive_id
 AND json_extract(NEW.packet_body,'$.writer_exit_id') IS e.exit_id
 AND json_extract(NEW.packet_body,'$.device_session_id') IS e.device_session_id
 AND json_extract(NEW.packet_body,'$.byte_length') IS length(NEW.packet_bytes)
 AND json_extract(NEW.packet_body,'$.sha256') IS NEW.bytes_digest
 AND json_extract(NEW.packet_body,'$.immutable_bytes_ref.digest') IS NEW.bytes_digest)
 THEN RAISE(ABORT,'typed_packet_columns') END;
END;
