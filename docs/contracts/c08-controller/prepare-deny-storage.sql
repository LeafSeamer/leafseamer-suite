-- 准备拒绝与完整集合的同库候选；与共享日志组合，外部原件可信性另验。
CREATE TABLE pd_registration(
 prepare_id TEXT PRIMARY KEY NOT NULL REFERENCES ep_request(prepare_id),
 sequence TEXT NOT NULL UNIQUE CHECK(length(sequence)=20 AND sequence NOT GLOB '*[^0-9]*' AND sequence>'00000000000000000000'),
 origin TEXT NOT NULL CHECK(origin IN ('manual','automation')),prep_key TEXT,receipt_id TEXT,
 control_epoch TEXT NOT NULL,effective_version TEXT NOT NULL,provenance_body BLOB NOT NULL CHECK(length(provenance_body)>0),
 CHECK((origin='manual' AND prep_key IS NULL AND receipt_id IS NULL) OR (origin='automation' AND prep_key IS NOT NULL AND receipt_id IS NOT NULL)),
 FOREIGN KEY(prep_key,receipt_id) REFERENCES cp_receipt(prep_key,receipt_id)
) STRICT;
CREATE VIEW pd_source AS SELECT r.*,g.sequence,g.origin,g.prep_key,g.receipt_id,g.control_epoch,g.effective_version,
 e.device_id,p.origin_authority,p.origin_database,p.run_id,p.generation
 FROM ep_request r JOIN pd_registration g USING(prepare_id) JOIN ce_exit e USING(exit_id) LEFT JOIN cp_request p USING(prep_key);
CREATE TABLE pd_cut(
 cut_id TEXT PRIMARY KEY NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('control','cancel','run','close')),
 control_id TEXT UNIQUE REFERENCES cu_cut(operation_id),cancel_id TEXT UNIQUE REFERENCES cc_cut(cut_id),
 run_id TEXT UNIQUE REFERENCES ce_fence(fence_id),close_id TEXT UNIQUE REFERENCES go_close(close_id),
 prepare_head TEXT NOT NULL CHECK(length(prepare_head)=20 AND prepare_head NOT GLOB '*[^0-9]*'),
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 selector_digest TEXT NOT NULL,selector_body BLOB NOT NULL CHECK(length(selector_body)>0),
 CHECK((kind='control' AND control_id IS NOT NULL AND cancel_id IS NULL AND run_id IS NULL AND close_id IS NULL)
 OR(kind='cancel' AND control_id IS NULL AND cancel_id IS NOT NULL AND run_id IS NULL AND close_id IS NULL)
 OR(kind='run' AND control_id IS NULL AND cancel_id IS NULL AND run_id IS NOT NULL AND close_id IS NULL)
 OR(kind='close' AND control_id IS NULL AND cancel_id IS NULL AND run_id IS NULL AND close_id IS NOT NULL)),
 FOREIGN KEY(cut_id) REFERENCES pd_cut_commit(cut_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE pd_member(
 cut_id TEXT NOT NULL REFERENCES pd_cut(cut_id),prepare_id TEXT NOT NULL REFERENCES ep_request(prepare_id),
 exit_id TEXT NOT NULL,authorization_id TEXT NOT NULL,authorization_digest TEXT NOT NULL,
 PRIMARY KEY(cut_id,prepare_id),
 FOREIGN KEY(prepare_id) REFERENCES ep_revocation(prepare_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE pd_cut_commit(
 cut_id TEXT PRIMARY KEY NOT NULL REFERENCES pd_cut(cut_id),committed_tick TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE VIEW pd_expected AS
 SELECT d.cut_id,s.prepare_id,s.exit_id,s.authorization_id,s.authorization_digest FROM pd_cut d JOIN cu_cut c ON c.operation_id=d.control_id
 JOIN pd_source s ON s.device_id=c.device_id AND s.sequence<=d.prepare_head
 UNION ALL
 SELECT d.cut_id,s.prepare_id,s.exit_id,s.authorization_id,s.authorization_digest FROM pd_cut d JOIN cc_cut c ON c.cut_id=d.cancel_id
 JOIN cv_cancel v USING(cancellation_id) JOIN pd_source s ON s.command_id=v.command_id AND s.sequence<=d.prepare_head AND (c.stage='all' OR s.kind='ordinary')
 UNION ALL
 SELECT d.cut_id,s.prepare_id,s.exit_id,s.authorization_id,s.authorization_digest FROM pd_cut d JOIN ce_selector c ON c.fence_id=d.run_id
 JOIN pd_source s ON (s.origin_authority,s.origin_database,s.run_id)=(c.origin_authority,c.origin_database,c.run_id)
 AND s.origin='automation' AND s.generation<=c.generation AND s.sequence<=d.prepare_head
 UNION ALL
 SELECT d.cut_id,s.prepare_id,s.exit_id,s.authorization_id,s.authorization_digest FROM pd_cut d JOIN go_close c ON c.close_id=d.close_id
 JOIN pd_source s ON s.exit_id=c.exit_id AND s.sequence<=d.prepare_head;
CREATE TRIGGER pd_register_guard BEFORE INSERT ON pd_registration BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM ep_request)>(SELECT max_metadata_prepares FROM ep_limit WHERE singleton=1)
 THEN RAISE(ABORT,'prepare_total_metadata_capacity') END;
 SELECT CASE WHEN NEW.sequence!=(SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),(CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
 FROM(SELECT coalesce(max(sequence),'00000000000000000000') v FROM pd_registration)) THEN RAISE(ABORT,'prepare_registry_sequence') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ce_command c USING(command_id) JOIN ce_exit e ON e.exit_id=r.exit_id JOIN ct_current_state s ON s.device_id=e.device_id
 WHERE r.prepare_id=NEW.prepare_id AND NOT EXISTS(SELECT 1 FROM ep_request_commit k WHERE k.prepare_id=r.prepare_id)
 AND NEW.control_epoch=s.control_epoch AND NEW.effective_version=s.effective_version AND s.pending_operation_id IS NULL
 AND (r.kind='cancel' OR (NEW.origin=c.origin AND NEW.prep_key IS c.prep_key AND NEW.receipt_id IS c.receipt_id))
 AND NOT EXISTS(SELECT 1 FROM ep_request prior JOIN pd_registration p USING(prepare_id) WHERE r.kind='cancel' AND prior.cancellation_id=r.cancellation_id
 AND NOT(p.origin=NEW.origin AND p.prep_key IS NEW.prep_key AND p.receipt_id IS NEW.receipt_id))
 AND (NEW.origin='manual' OR EXISTS(SELECT 1 FROM cp_request_device p WHERE p.prep_key=NEW.prep_key AND p.device_id=e.device_id)))
 THEN RAISE(ABORT,'prepare_registry_source') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ep_request r JOIN ce_exit e USING(exit_id) JOIN cu_cut c USING(device_id)
 JOIN ct_operation o USING(operation_id) JOIN ct_state old ON old.change_id=o.expected_state_id
 WHERE r.prepare_id=NEW.prepare_id AND NEW.control_epoch=old.control_epoch AND NEW.effective_version<o.target_version)
 THEN RAISE(ABORT,'prepare_control_denied') END;
 SELECT CASE WHEN NEW.origin='automation' AND EXISTS(SELECT 1 FROM cp_request p JOIN run_deny_event d
 ON (d.origin_authority,d.origin_database,d.run_id)=(p.origin_authority,p.origin_database,p.run_id)
 WHERE p.prep_key=NEW.prep_key AND d.generation>=p.generation) THEN RAISE(ABORT,'prepare_run_denied') END;
END;
CREATE TRIGGER pd_cut_guard BEFORE INSERT ON pd_cut BEGIN
 SELECT CASE WHEN NEW.prepare_head!=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration)
 OR EXISTS(SELECT 1 FROM ep_request r WHERE NOT EXISTS(SELECT 1 FROM pd_registration p WHERE p.prepare_id=r.prepare_id))
 OR NOT((NEW.kind='control' AND EXISTS(SELECT 1 FROM cu_cut c JOIN ct_change h USING(change_id) WHERE c.operation_id=NEW.control_id AND c.prepare_cut_id=NEW.cut_id AND h.now_tick=NEW.selected_tick AND NOT EXISTS(SELECT 1 FROM ct_commit k WHERE k.change_id=c.change_id)))
 OR(NEW.kind='cancel' AND EXISTS(SELECT 1 FROM cc_cut c WHERE c.cut_id=NEW.cancel_id AND c.prepare_cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM cc_cut_commit k WHERE k.cut_id=c.cut_id)))
 OR(NEW.kind='run' AND EXISTS(SELECT 1 FROM ce_fence c WHERE c.fence_id=NEW.run_id AND c.prepare_cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM ce_cut_commit k WHERE k.fence_id=c.fence_id)))
 OR(NEW.kind='close' AND EXISTS(SELECT 1 FROM go_close c JOIN ct_change h ON h.change_id=c.protection_change_id WHERE c.close_id=NEW.close_id AND c.prepare_cut_id=NEW.cut_id AND h.now_tick=NEW.selected_tick AND NOT EXISTS(SELECT 1 FROM ct_commit k WHERE k.change_id=h.change_id))))
 THEN RAISE(ABORT,'prepare_cut_source') END;
END;
CREATE TRIGGER pd_member_guard BEFORE INSERT ON pd_member BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pd_cut_commit WHERE cut_id=NEW.cut_id)
 OR NOT EXISTS(SELECT 1 FROM pd_expected p WHERE p.cut_id=NEW.cut_id AND p.prepare_id=NEW.prepare_id AND p.exit_id=NEW.exit_id
 AND p.authorization_id=NEW.authorization_id AND p.authorization_digest=NEW.authorization_digest) THEN RAISE(ABORT,'prepare_member_binding') END;
END;
CREATE TRIGGER pd_cut_seal BEFORE INSERT ON pd_cut_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pd_cut d WHERE d.cut_id=NEW.cut_id AND d.selected_tick<=NEW.committed_tick
 AND d.prepare_head=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration))
 OR EXISTS(SELECT cut_id,prepare_id,exit_id,authorization_id,authorization_digest FROM pd_expected WHERE cut_id=NEW.cut_id
 EXCEPT SELECT cut_id,prepare_id,exit_id,authorization_id,authorization_digest FROM pd_member WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT 1 FROM pd_member m JOIN ep_revocation r USING(prepare_id) JOIN ep_request_commit k USING(prepare_id)
 WHERE m.cut_id=NEW.cut_id AND (r.revoked_tick>NEW.committed_tick OR k.committed_tick>NEW.committed_tick))
 OR EXISTS(SELECT 1 FROM pd_member m WHERE m.cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM ep_revocation v WHERE v.prepare_id=m.prepare_id))
 THEN RAISE(ABORT,'prepare_cut_incomplete') END;
END;
CREATE TABLE pd_deny_request(
 deny_id TEXT PRIMARY KEY NOT NULL,prepare_id TEXT NOT NULL UNIQUE REFERENCES ep_revocation(prepare_id),
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),revision TEXT NOT NULL CHECK(revision='00000000000000000001'),request_digest TEXT NOT NULL,
 exit_id TEXT NOT NULL,authorization_id TEXT NOT NULL,authorization_digest TEXT NOT NULL,
 encode_message_id TEXT NOT NULL,encode_frame_digest TEXT NOT NULL,
 revocation_id TEXT NOT NULL,revocation_revision TEXT NOT NULL,revocation_digest TEXT NOT NULL,
 selected_tick TEXT NOT NULL,frame_body BLOB NOT NULL CHECK(length(frame_body)>0),body BLOB NOT NULL CHECK(length(body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER pd_request_guard BEFORE INSERT ON pd_deny_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ep_request r JOIN ij_encoding_frame j USING(prepare_id) JOIN ep_revocation v USING(prepare_id)
 JOIN ij_frame f ON f.frame_id=NEW.journal_frame_id
 WHERE r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id AND r.authorization_id=NEW.authorization_id AND r.authorization_digest=NEW.authorization_digest
 AND r.request_message_id=NEW.encode_message_id AND j.request_frame_digest=NEW.encode_frame_digest
 AND v.revocation_id=NEW.revocation_id AND v.revocation_revision=NEW.revocation_revision AND v.revocation_digest=NEW.revocation_digest AND v.revoked_tick<=NEW.selected_tick
 AND f.domain_kind='prepare_deny_request' AND f.domain_id=NEW.deny_id AND f.message_type='DENY_ENCODING' AND f.direction='c2w' AND f.exit_id=NEW.exit_id
 AND f.frame_body=NEW.frame_body AND f.body_body=NEW.body AND f.observed_tick=NEW.selected_tick
 AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'prepare_deny_source') END;
END;
CREATE TABLE pd_deny_ack(
 ack_id TEXT PRIMARY KEY NOT NULL,deny_id TEXT NOT NULL UNIQUE REFERENCES pd_deny_request(deny_id),prepare_id TEXT NOT NULL,
 journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),exit_id TEXT NOT NULL,
 deny_revision TEXT NOT NULL,deny_digest TEXT NOT NULL,deny_message_id TEXT NOT NULL,deny_frame_digest TEXT NOT NULL,
 effective_tick TEXT NOT NULL,received_tick TEXT NOT NULL,future_use_denied INTEGER NOT NULL CHECK(future_use_denied=1),
 frame_body BLOB NOT NULL CHECK(length(frame_body)>0),validation_body BLOB NOT NULL CHECK(length(validation_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER pd_ack_guard BEFORE INSERT ON pd_deny_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pd_deny_request r JOIN ij_frame original ON original.frame_id=r.journal_frame_id
 JOIN ij_commit c ON c.frame_id=original.frame_id JOIN ij_write_attempt a ON a.frame_id=original.frame_id JOIN ij_frame f ON f.frame_id=NEW.journal_frame_id
 WHERE r.deny_id=NEW.deny_id AND r.prepare_id=NEW.prepare_id AND r.exit_id=NEW.exit_id AND r.revision=NEW.deny_revision AND r.request_digest=NEW.deny_digest
 AND original.message_id=NEW.deny_message_id AND original.frame_digest=NEW.deny_frame_digest AND r.selected_tick<=NEW.effective_tick AND a.attempted_tick<=NEW.effective_tick
 AND NEW.effective_tick<=NEW.received_tick AND f.observed_tick=NEW.received_tick AND f.reply_frame_id=original.frame_id AND f.exit_id=NEW.exit_id
 AND f.message_type='DENY_ENCODING_ACK' AND f.domain_kind='prepare_deny_ack' AND f.domain_id=NEW.ack_id AND f.frame_body=NEW.frame_body
 AND NOT EXISTS(SELECT 1 FROM ij_commit k WHERE k.frame_id=f.frame_id)) THEN RAISE(ABORT,'prepare_deny_ack_source') END;
END;
CREATE TABLE pd_ack_revocation(
 ack_id TEXT PRIMARY KEY NOT NULL REFERENCES pd_deny_ack(ack_id),reason_body BLOB NOT NULL CHECK(length(reason_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE pd_closure(
 closure_id TEXT PRIMARY KEY NOT NULL,cut_id TEXT NOT NULL REFERENCES pd_cut_commit(cut_id),revision TEXT NOT NULL CHECK(revision='00000000000000000001'),
 closure_digest TEXT NOT NULL,committed_tick TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0),
 UNIQUE(closure_id,cut_id),FOREIGN KEY(closure_id) REFERENCES pd_closure_commit(closure_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE pd_coverage(
 closure_id TEXT NOT NULL,cut_id TEXT NOT NULL,prepare_id TEXT NOT NULL,
 basis TEXT NOT NULL CHECK(basis IN ('never_attempted','released','retired','deny_ack')),
 ack_id TEXT REFERENCES pd_deny_ack(ack_id),retirement_exit_id TEXT REFERENCES ce_retirement(exit_id),
 proof_body BLOB NOT NULL CHECK(length(proof_body)>0),PRIMARY KEY(closure_id,prepare_id),
 CHECK((basis='deny_ack' AND ack_id IS NOT NULL AND retirement_exit_id IS NULL)
 OR(basis='retired' AND ack_id IS NULL AND retirement_exit_id IS NOT NULL)
 OR(basis IN ('never_attempted','released') AND ack_id IS NULL AND retirement_exit_id IS NULL)),
 FOREIGN KEY(cut_id,prepare_id) REFERENCES pd_member(cut_id,prepare_id),
 FOREIGN KEY(closure_id,cut_id) REFERENCES pd_closure(closure_id,cut_id)
) STRICT;
CREATE TABLE pd_closure_commit(
 closure_id TEXT PRIMARY KEY NOT NULL REFERENCES pd_closure(closure_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE pd_close_completion(
 close_id TEXT PRIMARY KEY NOT NULL REFERENCES go_close(close_id),ack_id TEXT NOT NULL UNIQUE REFERENCES go_close_ack(ack_id),
 closure_id TEXT NOT NULL REFERENCES pd_closure_commit(closure_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW pd_valid_proof AS SELECT p.* FROM pd_coverage p JOIN pd_member m ON (m.cut_id,m.prepare_id)=(p.cut_id,p.prepare_id)
 JOIN pd_closure d USING(closure_id) JOIN ep_revocation v ON v.prepare_id=p.prepare_id
 WHERE v.revoked_tick<=d.committed_tick AND
 ((p.basis='never_attempted' AND NOT EXISTS(SELECT 1 FROM ep_send_attempt a WHERE a.prepare_id=p.prepare_id))
 OR(p.basis='released' AND EXISTS(SELECT 1 FROM ep_release r JOIN er_adoption a ON a.adoption_id=r.worker_adoption_id JOIN er_ack_commit k ON k.adoption_id=a.adoption_id
 WHERE r.prepare_id=p.prepare_id AND r.basis='worker_released' AND a.committed_tick<=d.committed_tick))
 OR(p.basis='retired' AND p.retirement_exit_id=m.exit_id AND NOT EXISTS(SELECT 1 FROM cu_revocation r WHERE r.kind='retirement' AND r.object_id=p.retirement_exit_id))
 OR(p.basis='deny_ack' AND EXISTS(SELECT 1 FROM pd_deny_ack a JOIN ij_commit k ON k.frame_id=a.journal_frame_id
 WHERE a.ack_id=p.ack_id AND a.prepare_id=p.prepare_id AND a.exit_id=m.exit_id AND k.disposition='applied' AND k.committed_tick<=d.committed_tick
 AND NOT EXISTS(SELECT 1 FROM pd_ack_revocation r WHERE r.ack_id=a.ack_id))));
CREATE VIEW pd_valid_closure AS SELECT c.* FROM pd_closure c JOIN pd_closure_commit k USING(closure_id)
 WHERE NOT EXISTS(SELECT 1 FROM pd_member m WHERE m.cut_id=c.cut_id AND NOT EXISTS(SELECT 1 FROM pd_valid_proof p WHERE p.closure_id=c.closure_id AND p.prepare_id=m.prepare_id));
CREATE TRIGGER pd_coverage_guard BEFORE INSERT ON pd_coverage BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pd_closure_commit WHERE closure_id=NEW.closure_id) THEN RAISE(ABORT,'prepare_closure_frozen') END;
END;
CREATE TRIGGER pd_closure_seal BEFORE INSERT ON pd_closure_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pd_closure c JOIN pd_cut_commit k USING(cut_id) WHERE c.closure_id=NEW.closure_id AND k.committed_tick<=c.committed_tick)
 OR EXISTS(SELECT m.prepare_id FROM pd_member m JOIN pd_closure c USING(cut_id) WHERE c.closure_id=NEW.closure_id
 EXCEPT SELECT prepare_id FROM pd_valid_proof WHERE closure_id=NEW.closure_id) THEN RAISE(ABORT,'prepare_closure_incomplete') END;
END;
CREATE TRIGGER pd_close_complete_guard BEFORE INSERT ON pd_close_completion BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_close c JOIN go_close_ack a USING(close_id) JOIN pd_valid_closure p ON p.cut_id=c.prepare_cut_id
 WHERE c.close_id=NEW.close_id AND a.ack_id=NEW.ack_id AND p.closure_id=NEW.closure_id) THEN RAISE(ABORT,'prepare_close_completion') END;
END;
