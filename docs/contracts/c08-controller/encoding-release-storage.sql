-- 与编码202表按固定替换组合；SQL约束投影，原件/JCS/真实消费者由可信提供者验证。
CREATE TABLE er_request(
 release_id TEXT PRIMARY KEY NOT NULL, release_revision TEXT NOT NULL CHECK(release_revision='00000000000000000001'),
 release_digest TEXT NOT NULL, prepare_id TEXT NOT NULL UNIQUE REFERENCES ep_revocation(prepare_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 authorization_id TEXT NOT NULL, authorization_digest TEXT NOT NULL,
 encode_message_id TEXT NOT NULL, encode_frame_digest TEXT NOT NULL,
 revocation_id TEXT NOT NULL, revocation_revision TEXT NOT NULL, revocation_digest TEXT NOT NULL,
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 message_id TEXT NOT NULL, outbound_seq TEXT NOT NULL CHECK(length(outbound_seq)=20 AND outbound_seq NOT GLOB '*[^0-9]*' AND outbound_seq>'00000000000000000000'),
 frame_digest TEXT NOT NULL, frame_body BLOB NOT NULL CHECK(length(frame_body)>0), body BLOB NOT NULL CHECK(length(body)>0),
 UNIQUE(exit_id,message_id), UNIQUE(exit_id,outbound_seq), UNIQUE(release_id,prepare_id),
 FOREIGN KEY(release_id) REFERENCES er_request_commit(release_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE er_request_commit(
 release_id TEXT PRIMARY KEY NOT NULL REFERENCES er_request(release_id),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE er_ack(
 ack_id TEXT PRIMARY KEY NOT NULL, release_id TEXT NOT NULL UNIQUE REFERENCES er_request_commit(release_id),
 prepare_id TEXT NOT NULL, exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 release_revision TEXT NOT NULL, release_digest TEXT NOT NULL,
 message_id TEXT NOT NULL, inbound_seq TEXT NOT NULL CHECK(length(inbound_seq)=20 AND inbound_seq NOT GLOB '*[^0-9]*' AND inbound_seq>'00000000000000000000'),
 reply_to TEXT NOT NULL, release_frame_digest TEXT NOT NULL,
 disposed_tick TEXT NOT NULL CHECK(length(disposed_tick)=20 AND disposed_tick NOT GLOB '*[^0-9]*'),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 state TEXT NOT NULL CHECK(state='released'), encoder_quiescent INTEGER NOT NULL CHECK(encoder_quiescent=1),
 consumers_quiescent INTEGER NOT NULL CHECK(consumers_quiescent=1), cache_empty INTEGER NOT NULL CHECK(cache_empty=1),
 frame_digest TEXT NOT NULL, frame_body BLOB NOT NULL CHECK(length(frame_body)>0),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 UNIQUE(exit_id,message_id), UNIQUE(exit_id,inbound_seq), UNIQUE(ack_id,prepare_id),
 FOREIGN KEY(release_id,prepare_id) REFERENCES er_request(release_id,prepare_id),
 FOREIGN KEY(ack_id) REFERENCES er_ack_commit(ack_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE er_adoption(
 adoption_id TEXT PRIMARY KEY NOT NULL, adoption_revision TEXT NOT NULL CHECK(adoption_revision='00000000000000000001'),
 adoption_digest TEXT NOT NULL, prepare_id TEXT NOT NULL UNIQUE,
 ack_id TEXT NOT NULL UNIQUE, release_id TEXT NOT NULL,
 reservation_id TEXT NOT NULL, reservation_revision TEXT NOT NULL, reservation_digest TEXT NOT NULL,
 reserved_bytes INTEGER NOT NULL CHECK(reserved_bytes BETWEEN 1 AND 65536),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 body BLOB NOT NULL CHECK(length(body)>0), audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(prepare_id,adoption_id),
 FOREIGN KEY(ack_id,prepare_id) REFERENCES er_ack(ack_id,prepare_id),
 FOREIGN KEY(release_id,prepare_id) REFERENCES er_request(release_id,prepare_id),
 FOREIGN KEY(prepare_id,adoption_id) REFERENCES ep_release(prepare_id,worker_adoption_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE er_ack_commit(
 ack_id TEXT PRIMARY KEY NOT NULL REFERENCES er_ack(ack_id),
 disposition TEXT NOT NULL CHECK(disposition IN ('released','historical')),
 adoption_id TEXT UNIQUE REFERENCES er_adoption(adoption_id) DEFERRABLE INITIALLY DEFERRED,
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK((disposition='released' AND adoption_id IS NOT NULL) OR (disposition='historical' AND adoption_id IS NULL))
) STRICT;
CREATE TRIGGER er_revocation_guard BEFORE INSERT ON ep_revocation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request_commit WHERE prepare_id=NEW.prepare_id AND committed_tick<=NEW.revoked_tick)
 THEN RAISE(ABORT,'encoding_revocation_time') END;
END;
CREATE TRIGGER er_request_guard BEFORE INSERT ON er_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ep_request_commit c USING(prepare_id)
 JOIN ep_send_attempt s USING(prepare_id) JOIN ep_revocation v USING(prepare_id)
 WHERE r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id
 AND r.authorization_id=NEW.authorization_id AND r.authorization_digest=NEW.authorization_digest
 AND r.request_message_id=NEW.encode_message_id AND r.request_frame_digest=NEW.encode_frame_digest
 AND v.revocation_id=NEW.revocation_id AND v.revocation_revision=NEW.revocation_revision AND v.revocation_digest=NEW.revocation_digest
 AND v.revoked_tick<=NEW.selected_tick AND s.attempted_tick<=NEW.selected_tick
 AND NOT EXISTS(SELECT 1 FROM ep_release f WHERE f.prepare_id=r.prepare_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id))
 THEN RAISE(ABORT,'encoding_release_request_source') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ep_request WHERE exit_id=NEW.exit_id AND (request_message_id=NEW.message_id OR request_seq=NEW.outbound_seq))
 THEN RAISE(ABORT,'encoding_release_outbound_collision') END;
END;
CREATE TRIGGER er_request_seal BEFORE INSERT ON er_request_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_request r WHERE r.release_id=NEW.release_id
 AND r.selected_tick<=NEW.committed_tick AND r.frame_body=NEW.outbox_body
 AND NOT EXISTS(SELECT 1 FROM ep_release f WHERE f.prepare_id=r.prepare_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id))
 THEN RAISE(ABORT,'encoding_release_request_seal') END;
END;
CREATE TRIGGER er_ack_guard BEFORE INSERT ON er_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_request r JOIN er_request_commit c USING(release_id)
 WHERE r.release_id=NEW.release_id AND r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id
 AND r.release_revision=NEW.release_revision AND r.release_digest=NEW.release_digest
 AND r.message_id=NEW.reply_to AND r.frame_digest=NEW.release_frame_digest
 AND r.selected_tick<=NEW.disposed_tick AND c.committed_tick<=NEW.disposed_tick AND NEW.disposed_tick<=NEW.received_tick)
 THEN RAISE(ABORT,'encoding_release_ack_source') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ep_reply WHERE exit_id=NEW.exit_id AND (response_message_id=NEW.message_id OR response_seq=NEW.inbound_seq))
 THEN RAISE(ABORT,'encoding_release_inbound_collision') END;
END;
CREATE TRIGGER er_adoption_guard BEFORE INSERT ON er_adoption BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_ack a JOIN er_request q USING(release_id) JOIN ep_request r ON r.prepare_id=a.prepare_id
 WHERE a.ack_id=NEW.ack_id AND a.prepare_id=NEW.prepare_id AND a.release_id=NEW.release_id
 AND r.reservation_id=NEW.reservation_id AND r.reservation_revision=NEW.reservation_revision AND r.reservation_digest=NEW.reservation_digest
 AND r.max_bytes=NEW.reserved_bytes AND a.received_tick=NEW.received_tick AND NEW.received_tick<=NEW.committed_tick
 AND NOT EXISTS(SELECT 1 FROM ep_release f WHERE f.prepare_id=r.prepare_id))
 THEN RAISE(ABORT,'encoding_release_adoption_source') END;
END;
CREATE TRIGGER er_ack_seal BEFORE INSERT ON er_ack_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_ack a JOIN ep_release f USING(prepare_id)
 WHERE a.ack_id=NEW.ack_id AND a.received_tick<=NEW.committed_tick AND
 ((NEW.disposition='released' AND f.basis='worker_released' AND f.worker_adoption_id=NEW.adoption_id
 AND EXISTS(SELECT 1 FROM er_adoption d WHERE d.adoption_id=NEW.adoption_id AND d.ack_id=NEW.ack_id AND d.committed_tick=NEW.committed_tick))
 OR (NEW.disposition='historical' AND f.basis='supervisor_retired' AND f.retirement_exit_id=a.exit_id)))
 THEN RAISE(ABORT,'encoding_release_ack_seal') END;
END;
CREATE TRIGGER er_worker_refund BEFORE INSERT ON ep_release WHEN NEW.basis='worker_released' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM er_adoption d JOIN er_ack a USING(ack_id)
 WHERE d.adoption_id=NEW.worker_adoption_id AND d.prepare_id=NEW.prepare_id AND a.prepare_id=NEW.prepare_id)
 THEN RAISE(ABORT,'encoding_release_refund_source') END;
END;
-- 序号冲突在编码/释放两方向子域内双向拒绝；完整50帧共享日志仍需单独归并。
CREATE TRIGGER er_encoding_outbound BEFORE INSERT ON ep_request BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM er_request WHERE exit_id=NEW.exit_id AND (message_id=NEW.request_message_id OR outbound_seq=NEW.request_seq))
 THEN RAISE(ABORT,'encoding_release_outbound_collision') END;
 SELECT CASE WHEN (SELECT count(*) FROM ep_request WHERE exit_id=NEW.exit_id)>=(SELECT max_metadata_prepares FROM ep_limit WHERE singleton=NEW.scope_id)
 THEN RAISE(ABORT,'encoding_metadata_capacity') END;
END;
CREATE TRIGGER er_encoding_inbound BEFORE INSERT ON ep_reply BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM er_ack WHERE exit_id=NEW.exit_id AND (message_id=NEW.response_message_id OR inbound_seq=NEW.response_seq))
 THEN RAISE(ABORT,'encoding_release_inbound_collision') END;
END;
-- 旧packet仍可作为历史保留，但所有新许可（含协议重传）和最后提交重核永久撤回。
CREATE VIEW er_packet_revoked AS SELECT p.packet_id FROM ep_reply p JOIN ep_revocation r USING(prepare_id);
CREATE TRIGGER er_ordinary_issue BEFORE INSERT ON ce_permit WHEN EXISTS(SELECT 1 FROM er_packet_revoked WHERE packet_id=NEW.packet_id)
 BEGIN SELECT RAISE(ABORT,'encoding_prepare_revoked'); END;
CREATE TRIGGER er_cancel_issue BEFORE INSERT ON ci_cancel_transmission WHEN EXISTS(SELECT 1 FROM er_packet_revoked WHERE packet_id=NEW.packet_id)
 BEGIN SELECT RAISE(ABORT,'encoding_prepare_revoked'); END;
CREATE TRIGGER er_ordinary_commit BEFORE INSERT ON ce_transmission_commit WHEN EXISTS(SELECT 1 FROM ce_permit p JOIN er_packet_revoked r USING(packet_id) WHERE p.permit_id=NEW.permit_id)
 BEGIN SELECT RAISE(ABORT,'encoding_prepare_revoked'); END;
CREATE TRIGGER er_cancel_commit BEFORE INSERT ON ci_cancel_commit WHEN EXISTS(SELECT 1 FROM ci_cancel_transmission p JOIN er_packet_revoked r USING(packet_id) WHERE p.permit_id=NEW.permit_id)
 BEGIN SELECT RAISE(ABORT,'encoding_prepare_revoked'); END;
CREATE VIEW er_recovery AS SELECT q.release_id,q.prepare_id,q.exit_id,q.message_id,q.frame_digest,q.frame_body,
 CASE WHEN a.ack_id IS NOT NULL THEN 'query_recorded_ack' WHEN f.prepare_id IS NOT NULL THEN 'query_recorded_release'
 WHEN t.exit_id IS NOT NULL THEN 'retired_requires_refund_commit' ELSE 'same_session_query_or_repeat_original' END AS recovery_action
 FROM er_request q JOIN er_request_commit c USING(release_id) LEFT JOIN er_ack a USING(release_id)
 LEFT JOIN er_ack_commit k USING(ack_id) LEFT JOIN ep_release f ON f.prepare_id=q.prepare_id
 LEFT JOIN ce_retirement t ON t.exit_id=q.exit_id;
