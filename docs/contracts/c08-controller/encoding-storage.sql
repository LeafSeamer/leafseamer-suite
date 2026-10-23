-- 与194表组合；编码请求和设备许可分开。真实鉴权/JCS/时钟/磁盘预算另验。
CREATE TABLE ep_limit(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1) REFERENCES controller_scope(singleton),
 profile_id TEXT NOT NULL, profile_revision TEXT NOT NULL, profile_digest TEXT NOT NULL,
 max_live_prepares INTEGER NOT NULL CHECK(max_live_prepares BETWEEN 1 AND 4096),
 max_live_bytes INTEGER NOT NULL CHECK(max_live_bytes BETWEEN 1 AND 9007199254740991),
 profile_body BLOB NOT NULL CHECK(length(profile_body)>0)
) STRICT;
CREATE TABLE ep_request(
 prepare_id TEXT PRIMARY KEY NOT NULL, scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES ep_limit(singleton),
 kind TEXT NOT NULL CHECK(kind IN ('ordinary','cancel')),
 command_id TEXT NOT NULL REFERENCES ce_command(command_id),
 proposed_attempt_id TEXT, cancellation_id TEXT REFERENCES cv_cancel_commit(cancellation_id),
 cancel_prepare_id TEXT REFERENCES cc_prepare(prepare_id) DEFERRABLE INITIALLY DEFERRED,
 namespace_id TEXT NOT NULL REFERENCES ca_namespace(namespace_id), request_digest TEXT NOT NULL,
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, principal_id TEXT NOT NULL,
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id), primitive_id TEXT NOT NULL,
 authorization_id TEXT NOT NULL UNIQUE, authorization_digest TEXT NOT NULL,
 authorization_body BLOB NOT NULL CHECK(length(authorization_body)>0),
 request_message_id TEXT NOT NULL, request_seq TEXT NOT NULL CHECK(length(request_seq)=20 AND request_seq NOT GLOB '*[^0-9]*' AND request_seq>'00000000000000000000'),
 request_frame_digest TEXT NOT NULL, request_frame BLOB NOT NULL CHECK(length(request_frame)>0),
 max_bytes INTEGER NOT NULL CHECK(max_bytes BETWEEN 1 AND 65536),
 created_tick TEXT NOT NULL CHECK(length(created_tick)=20 AND created_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 CHECK(created_tick<expires_tick),
 CHECK((kind='ordinary' AND proposed_attempt_id IS NOT NULL AND cancellation_id IS NULL AND cancel_prepare_id IS NULL)
  OR (kind='cancel' AND proposed_attempt_id IS NULL AND cancellation_id IS NOT NULL AND cancel_prepare_id IS NOT NULL AND cancel_prepare_id=prepare_id)),
 UNIQUE(exit_id,request_message_id), UNIQUE(exit_id,request_seq), UNIQUE(proposed_attempt_id,primitive_id),
 FOREIGN KEY(prepare_id) REFERENCES ep_request_commit(prepare_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ep_request_commit(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_request(prepare_id),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE ep_send_attempt(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_request_commit(prepare_id),
 attempt_id TEXT NOT NULL UNIQUE,
 attempted_tick TEXT NOT NULL CHECK(length(attempted_tick)=20 AND attempted_tick NOT GLOB '*[^0-9]*'),
 request_frame_digest TEXT NOT NULL, attempt_body BLOB NOT NULL CHECK(length(attempt_body)>0)
) STRICT;
CREATE TABLE ep_reply(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_send_attempt(prepare_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id), response_message_id TEXT NOT NULL,
 response_seq TEXT NOT NULL CHECK(length(response_seq)=20 AND response_seq NOT GLOB '*[^0-9]*' AND response_seq>'00000000000000000000'),
 reply_to TEXT NOT NULL, authorization_id TEXT NOT NULL, authorization_digest TEXT NOT NULL,
 response_frame_digest TEXT NOT NULL, response_frame BLOB NOT NULL CHECK(length(response_frame)>0),
 outcome TEXT NOT NULL CHECK(outcome IN ('prepared','failed','rejected')),
 packet_id TEXT UNIQUE, packet_digest TEXT, bytes_digest TEXT, packet_bytes BLOB, packet_body BLOB,
 evidence_id TEXT UNIQUE, evidence_digest TEXT, evidence_body BLOB,
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 UNIQUE(exit_id,response_message_id), UNIQUE(exit_id,response_seq),
 CHECK((outcome='prepared' AND packet_id IS NOT NULL AND packet_digest IS NOT NULL AND bytes_digest IS NOT NULL
   AND packet_bytes IS NOT NULL AND length(packet_bytes)>0 AND packet_body IS NOT NULL AND length(packet_body)>0
   AND evidence_id IS NOT NULL AND evidence_digest IS NOT NULL AND evidence_body IS NOT NULL AND length(evidence_body)>0)
 OR (outcome!='prepared' AND packet_id IS NULL AND packet_digest IS NULL AND bytes_digest IS NULL AND packet_bytes IS NULL
   AND packet_body IS NULL AND evidence_id IS NULL AND evidence_digest IS NULL AND evidence_body IS NULL)),
 FOREIGN KEY(prepare_id) REFERENCES ep_receive_commit(prepare_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ep_receive_commit(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_reply(prepare_id),
 disposition TEXT NOT NULL CHECK(disposition IN ('prepared','failed','historical')),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ep_revocation(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_request_commit(prepare_id),
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE ep_release(
 prepare_id TEXT PRIMARY KEY REFERENCES ep_revocation(prepare_id),
 basis TEXT NOT NULL CHECK(basis IN ('never_attempted','supervisor_retired')),
 retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 proof_body BLOB NOT NULL CHECK(length(proof_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK((basis='never_attempted' AND retirement_exit_id IS NULL) OR (basis='supervisor_retired' AND retirement_exit_id IS NOT NULL))
) STRICT;
CREATE VIEW ep_live_reservation AS SELECT r.prepare_id,r.scope_id,r.max_bytes FROM ep_request r
 WHERE NOT EXISTS(SELECT 1 FROM ep_release f WHERE f.prepare_id=r.prepare_id);
CREATE VIEW ep_request_source AS SELECT r.* FROM ep_request r JOIN ce_command c USING(command_id)
 JOIN ce_exit e ON e.exit_id=r.exit_id AND e.device_id=c.device_id JOIN ca_namespace n ON n.namespace_id=r.namespace_id
 WHERE n.scope_id=r.scope_id AND n.issuer_id=r.issuer_id AND n.issuer_epoch=r.issuer_epoch AND n.principal_id=r.principal_id
 AND ((r.kind='ordinary' AND EXISTS(SELECT 1 FROM ca_command_initial i JOIN ca_request_key k USING(key_id)
  WHERE i.command_id=r.command_id AND k.namespace_id=r.namespace_id AND k.request_digest=r.request_digest))
 OR (r.kind='cancel' AND EXISTS(SELECT 1 FROM cv_cancel c JOIN cv_cancel_key k USING(key_id) JOIN cc_prepare p USING(cancellation_id)
  WHERE c.cancellation_id=r.cancellation_id AND c.command_id=r.command_id AND k.namespace_id=r.namespace_id
   AND k.request_digest=r.request_digest AND p.prepare_id=r.prepare_id AND p.exit_id=r.exit_id AND p.primitive_id=r.primitive_id)));
CREATE VIEW ep_open_request AS SELECT r.* FROM ep_request_source r JOIN ep_request_commit k USING(prepare_id)
 WHERE NOT EXISTS(SELECT 1 FROM ep_revocation v WHERE v.prepare_id=r.prepare_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id)
 AND ((r.kind='ordinary' AND NOT EXISTS(SELECT 1 FROM cv_cancel c WHERE c.command_id=r.command_id))
 OR (r.kind='cancel' AND NOT EXISTS(SELECT 1 FROM cc_cut c WHERE c.cancellation_id=r.cancellation_id AND c.stage='all')));
CREATE VIEW ep_prepared_candidate AS SELECT r.*,p.packet_id,p.packet_digest,p.packet_bytes,p.packet_body,p.evidence_id,p.evidence_digest
 FROM ep_open_request r JOIN ep_reply p USING(prepare_id) JOIN ep_receive_commit k USING(prepare_id)
 WHERE k.disposition='prepared';
CREATE VIEW ep_recovery AS SELECT r.prepare_id,
 CASE WHEN f.prepare_id IS NOT NULL THEN 'released' WHEN v.prepare_id IS NOT NULL THEN 'revoked'
 WHEN p.prepare_id IS NOT NULL THEN 'query_recorded_result' WHEN a.prepare_id IS NOT NULL THEN 'query_or_retire_unknown'
 ELSE 'never_attempted_do_not_replay' END AS recovery_action
 FROM ep_request r JOIN ep_request_commit k USING(prepare_id) LEFT JOIN ep_send_attempt a USING(prepare_id)
 LEFT JOIN ep_reply p USING(prepare_id) LEFT JOIN ep_revocation v USING(prepare_id) LEFT JOIN ep_release f USING(prepare_id);
CREATE TRIGGER ep_reserve BEFORE INSERT ON ep_request BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM ep_live_reservation)>=(SELECT max_live_prepares FROM ep_limit WHERE singleton=NEW.scope_id)
 OR NEW.max_bytes>(SELECT max_live_bytes FROM ep_limit WHERE singleton=NEW.scope_id)-coalesce((SELECT sum(max_bytes) FROM ep_live_reservation),0)
 THEN RAISE(ABORT,'encoding_capacity') END;
END;
CREATE TRIGGER ep_request_seal BEFORE INSERT ON ep_request_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request_source r WHERE r.prepare_id=NEW.prepare_id
  AND r.created_tick<=NEW.committed_tick AND NEW.committed_tick<r.expires_tick
  AND NOT EXISTS(SELECT 1 FROM ce_retirement e WHERE e.exit_id=r.exit_id)
  AND ((r.kind='ordinary' AND NOT EXISTS(SELECT 1 FROM cv_cancel c WHERE c.command_id=r.command_id))
    OR (r.kind='cancel' AND NOT EXISTS(SELECT 1 FROM cc_cut c WHERE c.cancellation_id=r.cancellation_id AND c.stage='all'))))
 THEN RAISE(ABORT,'encoding_request_source') END;
END;
CREATE TRIGGER ep_attempt_guard BEFORE INSERT ON ep_send_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_open_request r JOIN ep_request_commit k USING(prepare_id)
 WHERE r.prepare_id=NEW.prepare_id AND r.request_frame_digest=NEW.request_frame_digest
 AND k.committed_tick<=NEW.attempted_tick AND NEW.attempted_tick<r.expires_tick)
 THEN RAISE(ABORT,'encoding_attempt_not_current') END;
END;
CREATE TRIGGER ep_reply_guard BEFORE INSERT ON ep_reply BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ep_send_attempt a USING(prepare_id)
  WHERE r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id AND r.request_message_id=NEW.reply_to
  AND r.authorization_id=NEW.authorization_id AND r.authorization_digest=NEW.authorization_digest
  AND a.attempted_tick<=NEW.received_tick AND (NEW.outcome!='prepared' OR length(NEW.packet_bytes)<=r.max_bytes))
 THEN RAISE(ABORT,'encoding_reply_binding') END;
END;
CREATE TRIGGER ep_receive_seal BEFORE INSERT ON ep_receive_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_reply p WHERE p.prepare_id=NEW.prepare_id AND p.received_tick<=NEW.committed_tick)
 THEN RAISE(ABORT,'encoding_receive_time') END;
 SELECT CASE WHEN NEW.disposition='prepared' AND NOT EXISTS(SELECT 1 FROM ep_reply p JOIN ep_open_request r USING(prepare_id)
 WHERE p.prepare_id=NEW.prepare_id AND p.outcome='prepared' AND NEW.committed_tick<r.expires_tick)
 THEN RAISE(ABORT,'encoding_not_adoptable') END;
 SELECT CASE WHEN NEW.disposition='failed' AND NOT EXISTS(SELECT 1 FROM ep_reply WHERE prepare_id=NEW.prepare_id AND outcome IN ('failed','rejected'))
 THEN RAISE(ABORT,'encoding_not_failed') END;
END;
CREATE TRIGGER ep_release_guard BEFORE INSERT ON ep_release BEGIN
 SELECT CASE WHEN (NEW.basis='never_attempted' AND EXISTS(SELECT 1 FROM ep_send_attempt WHERE prepare_id=NEW.prepare_id))
 OR (NEW.basis='supervisor_retired' AND NOT EXISTS(SELECT 1 FROM ep_request WHERE prepare_id=NEW.prepare_id AND exit_id=NEW.retirement_exit_id))
 THEN RAISE(ABORT,'encoding_release_proof') END;
END;
-- 普通与取消旧packet入口必须映射同一不可变编码证据；最终T2时效和完整seal仍另验。
CREATE TRIGGER ep_ordinary_packet BEFORE INSERT ON ce_packet BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_prepared_candidate p JOIN ce_attempt a ON a.attempt_id=p.proposed_attempt_id
 WHERE p.kind='ordinary' AND p.packet_id=NEW.packet_id AND p.proposed_attempt_id=NEW.attempt_id AND a.command_id=p.command_id
 AND p.exit_id=NEW.exit_id AND p.primitive_id=NEW.primitive_id AND p.packet_body=NEW.packet_body)
 THEN RAISE(ABORT,'encoding_ordinary_packet_source') END;
END;
CREATE TRIGGER ep_cancel_packet BEFORE INSERT ON cc_packet BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_prepared_candidate p WHERE p.kind='cancel' AND p.packet_id=NEW.packet_id
 AND p.prepare_id=NEW.prepare_id AND p.packet_digest=NEW.packet_digest AND p.packet_bytes=NEW.packet_bytes AND p.packet_body=NEW.packet_body)
 THEN RAISE(ABORT,'encoding_cancel_packet_source') END;
END;
