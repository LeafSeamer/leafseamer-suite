-- 只与固定207表修订版组合；所有原件解码/JCS/端点真实性由受信提供者外验。
CREATE TABLE ij_type(name TEXT PRIMARY KEY NOT NULL,direction TEXT NOT NULL CHECK(direction IN ('c2w','w2c')),
 response INTEGER NOT NULL CHECK(response IN (0,1)),protected INTEGER NOT NULL CHECK(protected IN (0,1))) STRICT;
CREATE TABLE ij_reply_type(response_type TEXT NOT NULL REFERENCES ij_type(name),request_type TEXT NOT NULL REFERENCES ij_type(name),
 PRIMARY KEY(response_type,request_type)) STRICT;
CREATE TABLE ij_session(
 session_id TEXT PRIMARY KEY NOT NULL,scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
 controller_boot_id TEXT NOT NULL,worker_boot_id TEXT NOT NULL,ipc_session_id TEXT NOT NULL,
 clock_domain_id TEXT NOT NULL,descriptor_digest TEXT NOT NULL,protocol_version TEXT NOT NULL CHECK(protocol_version='ipc/0.13.0-journal-draft.1'),
 profile_body BLOB NOT NULL CHECK(length(profile_body)>0),binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 max_frames INTEGER NOT NULL CHECK(max_frames BETWEEN 4 AND 65536),reserved_frames INTEGER NOT NULL CHECK(reserved_frames BETWEEN 1 AND max_frames-2),
 max_bytes INTEGER NOT NULL CHECK(max_bytes BETWEEN 1 AND 9007199254740991),reserved_bytes INTEGER NOT NULL CHECK(reserved_bytes BETWEEN 1 AND max_bytes-1),
 UNIQUE(controller_boot_id,worker_boot_id,ipc_session_id)
) STRICT;
CREATE TABLE ij_exit(
 exit_id TEXT PRIMARY KEY NOT NULL REFERENCES ce_exit(exit_id),session_id TEXT NOT NULL REFERENCES ij_session(session_id),
 UNIQUE(session_id,exit_id)
) STRICT;
CREATE TRIGGER ij_exit_guard BEFORE INSERT ON ij_exit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_session s JOIN ce_exit e ON e.exit_id=NEW.exit_id
 WHERE s.session_id=NEW.session_id AND s.controller_boot_id=e.controller_boot_id AND s.worker_boot_id=e.worker_boot_id
 AND s.ipc_session_id=e.ipc_session_id AND s.clock_domain_id=e.clock_domain_id AND s.descriptor_digest=e.descriptor_digest)
 OR EXISTS(SELECT 1 FROM ij_end WHERE session_id=NEW.session_id) THEN RAISE(ABORT,'journal_exit_binding') END;
END;
CREATE TABLE ij_frame(
 frame_id TEXT PRIMARY KEY NOT NULL,session_id TEXT NOT NULL REFERENCES ij_session(session_id),exit_id TEXT,device_id TEXT,
 direction TEXT NOT NULL CHECK(direction IN ('c2w','w2c')),message_type TEXT NOT NULL REFERENCES ij_type(name),
 message_id TEXT NOT NULL,seq TEXT NOT NULL CHECK(length(seq)=20 AND seq NOT GLOB '*[^0-9]*' AND seq>'00000000000000000000'),
 reply_frame_id TEXT REFERENCES ij_frame(frame_id),reply_to TEXT,
 frame_digest TEXT NOT NULL,wire_digest TEXT NOT NULL,frame_body BLOB NOT NULL CHECK(length(frame_body)>0),
 body_body BLOB NOT NULL CHECK(length(body_body)>0),
 wire_body BLOB NOT NULL CHECK(length(wire_body)>0),wire_length INTEGER NOT NULL CHECK(wire_length=length(wire_body) AND wire_length<=262148),
 observed_tick TEXT NOT NULL CHECK(length(observed_tick)=20 AND observed_tick NOT GLOB '*[^0-9]*'),
 domain_kind TEXT NOT NULL,domain_id TEXT NOT NULL,validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 CHECK((exit_id IS NULL AND device_id IS NULL) OR (exit_id IS NOT NULL AND device_id IS NOT NULL)),
 CHECK((reply_frame_id IS NULL AND reply_to IS NULL) OR (reply_frame_id IS NOT NULL AND reply_to IS NOT NULL)),
 UNIQUE(session_id,direction,seq),UNIQUE(session_id,direction,message_id),UNIQUE(domain_kind,domain_id),
 FOREIGN KEY(session_id,exit_id) REFERENCES ij_exit(session_id,exit_id),
 FOREIGN KEY(frame_id) REFERENCES ij_commit(frame_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ij_commit(
 frame_id TEXT PRIMARY KEY NOT NULL REFERENCES ij_frame(frame_id),disposition TEXT NOT NULL CHECK(disposition IN ('applied','historical','rejected')),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),effect_body BLOB NOT NULL CHECK(length(effect_body)>0)
) STRICT;
CREATE TABLE ij_write_attempt(
 frame_id TEXT PRIMARY KEY NOT NULL REFERENCES ij_commit(frame_id),attempt_id TEXT NOT NULL UNIQUE,
 attempted_tick TEXT NOT NULL CHECK(length(attempted_tick)=20 AND attempted_tick NOT GLOB '*[^0-9]*'),
 encoding_prepare_id TEXT UNIQUE REFERENCES ep_send_attempt(prepare_id) DEFERRABLE INITIALLY DEFERRED,
 current_validation_body BLOB NOT NULL CHECK(length(current_validation_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ij_end(
 end_id TEXT PRIMARY KEY NOT NULL,session_id TEXT NOT NULL UNIQUE REFERENCES ij_session(session_id),
 reason TEXT NOT NULL CHECK(reason IN ('storage_unknown','protocol_error','write_uncertain','peer_lost','shutdown','volatile_close')),
 cause_frame_id TEXT REFERENCES ij_frame(frame_id),observed_tick TEXT NOT NULL CHECK(length(observed_tick)=20 AND observed_tick NOT GLOB '*[^0-9]*'),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TABLE ij_write_result(
 frame_id TEXT PRIMARY KEY NOT NULL REFERENCES ij_write_attempt(frame_id),state TEXT NOT NULL CHECK(state IN ('written','uncertain')),
 completed_tick TEXT NOT NULL CHECK(length(completed_tick)=20 AND completed_tick NOT GLOB '*[^0-9]*'),
 written_bytes INTEGER NOT NULL CHECK(written_bytes>=0),end_id TEXT REFERENCES ij_end(end_id),
 result_body BLOB NOT NULL CHECK(length(result_body)>0),CHECK((state='written' AND end_id IS NULL) OR (state='uncertain' AND end_id IS NOT NULL))
) STRICT;
CREATE TABLE ij_rejection(
 rejection_id TEXT PRIMARY KEY NOT NULL,frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 reason TEXT NOT NULL CHECK(length(reason)>0),evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0)
) STRICT;
CREATE TABLE ij_handshake(
 handshake_id TEXT PRIMARY KEY NOT NULL,frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 kind TEXT NOT NULL CHECK(kind IN ('HELLO','HELLO_ACK')),negotiation_body BLOB NOT NULL CHECK(length(negotiation_body)>0)
) STRICT;
CREATE TABLE ij_encoding_frame(
 prepare_id TEXT PRIMARY KEY NOT NULL REFERENCES ep_request_commit(prepare_id),journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),
 request_seq TEXT NOT NULL CHECK(length(request_seq)=20 AND request_seq NOT GLOB '*[^0-9]*' AND request_seq>'00000000000000000000'),
 request_frame_digest TEXT NOT NULL,request_frame BLOB NOT NULL CHECK(length(request_frame)>0)
) STRICT;
CREATE TRIGGER ij_frame_guard BEFORE INSERT ON ij_frame BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_type WHERE name=NEW.message_type AND direction=NEW.direction)
 THEN RAISE(ABORT,'journal_direction') END;
 SELECT CASE WHEN NEW.exit_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ij_exit x JOIN ce_exit e USING(exit_id)
 WHERE x.session_id=NEW.session_id AND x.exit_id=NEW.exit_id AND e.device_id=NEW.device_id) THEN RAISE(ABORT,'journal_device') END;
 SELECT CASE WHEN (NEW.message_type IN ('HELLO','HELLO_ACK','CLOSE_GATE_ACK') AND NEW.exit_id IS NOT NULL)
 OR (NEW.message_type NOT IN ('HELLO','HELLO_ACK','CLOSE_GATE_ACK','CLOSE_GATE') AND NEW.exit_id IS NULL)
 THEN RAISE(ABORT,'journal_device_shape') END;
 SELECT CASE WHEN NEW.direction='c2w' AND EXISTS(SELECT 1 FROM ij_end WHERE session_id=NEW.session_id)
 THEN RAISE(ABORT,'journal_session_ended') END;
 SELECT CASE WHEN NEW.seq!=coalesce((SELECT CASE WHEN substr(seq,11,10)='9999999999'
 THEN printf('%010d',CAST(substr(seq,1,10) AS INTEGER)+1)||'0000000000'
 ELSE substr(seq,1,10)||printf('%010d',CAST(substr(seq,11,10) AS INTEGER)+1) END
 FROM ij_frame WHERE session_id=NEW.session_id AND direction=NEW.direction ORDER BY seq DESC LIMIT 1),'00000000000000000001')
 THEN RAISE(ABORT,'journal_sequence') END;
 SELECT CASE WHEN (NEW.seq='00000000000000000001' AND NEW.message_type!=CASE NEW.direction WHEN 'w2c' THEN 'HELLO' ELSE 'HELLO_ACK' END)
 OR (NEW.seq>'00000000000000000001' AND NOT EXISTS(SELECT 1 FROM ij_frame f JOIN ij_commit c USING(frame_id)
 WHERE f.session_id=NEW.session_id AND f.message_type='HELLO_ACK' AND c.disposition='applied'))
 THEN RAISE(ABORT,'journal_handshake') END;
 SELECT CASE WHEN (SELECT response FROM ij_type WHERE name=NEW.message_type)=0 AND NEW.reply_to IS NOT NULL
 THEN RAISE(ABORT,'journal_nonresponse') END;
 SELECT CASE WHEN (SELECT response FROM ij_type WHERE name=NEW.message_type)=1 AND NOT EXISTS(
 SELECT 1 FROM ij_frame r JOIN ij_commit c ON c.frame_id=r.frame_id JOIN ij_reply_type t ON t.request_type=r.message_type
 WHERE t.response_type=NEW.message_type AND r.frame_id=NEW.reply_frame_id AND r.message_id=NEW.reply_to
 AND r.session_id=NEW.session_id AND r.direction!=NEW.direction AND r.observed_tick<=NEW.observed_tick
 AND (r.direction='w2c' OR EXISTS(SELECT 1 FROM ij_write_attempt a WHERE a.frame_id=r.frame_id))
 AND (NEW.message_type='CLOSE_GATE_ACK' OR (r.exit_id IS NEW.exit_id AND r.device_id IS NEW.device_id)))
 THEN RAISE(ABORT,'journal_reply_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ij_session s WHERE s.session_id=NEW.session_id AND
 ((SELECT count(*) FROM ij_frame f WHERE f.session_id=s.session_id)>=s.max_frames-
 CASE (SELECT protected FROM ij_type WHERE name=NEW.message_type) WHEN 1 THEN 0 ELSE s.reserved_frames END
 OR NEW.wire_length>s.max_bytes-CASE (SELECT protected FROM ij_type WHERE name=NEW.message_type) WHEN 1 THEN 0 ELSE s.reserved_bytes END-
 coalesce((SELECT sum(f.wire_length) FROM ij_frame f WHERE f.session_id=s.session_id),0)))
 THEN RAISE(ABORT,'journal_capacity') END;
END;
CREATE TRIGGER ij_commit_guard BEFORE INSERT ON ij_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND f.observed_tick<=NEW.committed_tick
 AND NOT(f.direction='c2w' AND EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id))
 AND NOT(NEW.disposition='applied' AND EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)))
 THEN RAISE(ABORT,'journal_commit_current') END;
 -- 每个实际领域原件由生成器补精确双向关系；未迁移类型只能保存明确拒收记录。
END;
CREATE TRIGGER ij_attempt_guard BEFORE INSERT ON ij_write_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f JOIN ij_commit c USING(frame_id)
 WHERE f.frame_id=NEW.frame_id AND f.direction='c2w' AND c.disposition='applied' AND c.committed_tick<=NEW.attempted_tick
 AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)
 AND NOT EXISTS(SELECT 1 FROM ij_frame p WHERE p.session_id=f.session_id AND p.direction='c2w' AND p.seq<f.seq
 AND NOT EXISTS(SELECT 1 FROM ij_write_result r WHERE r.frame_id=p.frame_id AND r.state='written'))
 AND ((f.domain_kind='encoding_request' AND NEW.encoding_prepare_id=f.domain_id
 AND EXISTS(SELECT 1 FROM ep_send_attempt p WHERE p.prepare_id=NEW.encoding_prepare_id AND p.journal_frame_id=NEW.frame_id
 AND p.attempt_id=NEW.attempt_id AND p.attempted_tick=NEW.attempted_tick))
 OR (f.domain_kind!='encoding_request' AND NEW.encoding_prepare_id IS NULL))) THEN RAISE(ABORT,'journal_attempt_prefix') END;
END;
CREATE TRIGGER ij_attempt_domain BEFORE INSERT ON ij_write_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND
 ((f.domain_kind='open_request' AND NOT EXISTS(SELECT 1 FROM go_dispatch d JOIN go_valid_plan p USING(plan_id)
 WHERE d.journal_frame_id=f.frame_id AND NEW.attempted_tick<p.expires_tick))
 OR (f.domain_kind='renewal_request' AND NOT EXISTS(SELECT 1 FROM gf_context r WHERE r.journal_frame_id=f.frame_id
 AND NEW.attempted_tick<r.expires_tick AND (r.previous_gate_id IS NULL OR EXISTS(SELECT 1 FROM go_current_gate g WHERE g.gate_id=r.previous_gate_id))))
 OR (f.domain_kind='release_request' AND NOT EXISTS(SELECT 1 FROM er_request r WHERE r.journal_frame_id=f.frame_id
 AND NOT EXISTS(SELECT 1 FROM ep_release a WHERE a.prepare_id=r.prepare_id)
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id)))))
 THEN RAISE(ABORT,'journal_send_not_current') END;
END;
CREATE TRIGGER ij_request_current BEFORE INSERT ON ep_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_exit x WHERE x.exit_id=NEW.exit_id
 AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id)) THEN RAISE(ABORT,'journal_prepare_session') END;
END;
CREATE TRIGGER ij_result_guard BEFORE INSERT ON ij_write_result BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_write_attempt a JOIN ij_frame f USING(frame_id)
 WHERE a.frame_id=NEW.frame_id AND a.attempted_tick<=NEW.completed_tick AND NEW.written_bytes<=f.wire_length
 AND ((NEW.state='written' AND NEW.written_bytes=f.wire_length)
 OR (NEW.state='uncertain' AND EXISTS(SELECT 1 FROM ij_end e WHERE e.end_id=NEW.end_id AND e.session_id=f.session_id
 AND e.cause_frame_id=f.frame_id AND e.observed_tick<=NEW.completed_tick)))) THEN RAISE(ABORT,'journal_write_result') END;
END;
CREATE TRIGGER ij_end_guard BEFORE INSERT ON ij_end WHEN NEW.cause_frame_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.cause_frame_id AND f.session_id=NEW.session_id
 AND f.observed_tick<=NEW.observed_tick) THEN RAISE(ABORT,'journal_end_source') END;
END;
CREATE TRIGGER ij_encoding_attempt BEFORE INSERT ON ep_send_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_encoding_frame e JOIN ij_commit c ON c.frame_id=e.journal_frame_id
 WHERE e.prepare_id=NEW.prepare_id AND e.journal_frame_id=NEW.journal_frame_id AND c.disposition='applied'
 AND c.committed_tick<=NEW.attempted_tick AND e.request_frame_digest=NEW.request_frame_digest)
 THEN RAISE(ABORT,'journal_encoding_attempt') END;
END;
CREATE VIEW ij_recovery AS SELECT f.frame_id,f.session_id,f.direction,f.message_type,
 CASE WHEN c.disposition='rejected' THEN 'query_rejection_never_send'
 WHEN f.direction='w2c' THEN 'query_committed_inbox'
 WHEN e.end_id IS NOT NULL THEN 'ended_never_replay'
 WHEN r.state='written' THEN 'written_not_peer_processed'
 WHEN a.frame_id IS NOT NULL THEN 'attempted_query_or_retire'
 ELSE 'unattempted_current_session_only' END AS recovery_action
 FROM ij_frame f JOIN ij_commit c USING(frame_id) LEFT JOIN ij_write_attempt a USING(frame_id)
 LEFT JOIN ij_write_result r USING(frame_id) LEFT JOIN ij_end e USING(session_id);
