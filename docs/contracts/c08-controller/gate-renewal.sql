-- 独立换闸证据；只建立fenced，不授予普通或取消执行资格。
CREATE TABLE gf_request(
 request_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 previous_gate_id TEXT REFERENCES go_gate(gate_id),authority_state_id TEXT NOT NULL REFERENCES ct_state(change_id),
 control_state_id TEXT NOT NULL REFERENCES ct_state(change_id),close_ack_id TEXT NOT NULL REFERENCES go_close_ack(ack_id),
 safety_revision TEXT NOT NULL CHECK(length(safety_revision)=20 AND safety_revision NOT GLOB '*[^0-9]*'),
 target_revision TEXT NOT NULL CHECK(length(target_revision)=20 AND target_revision NOT GLOB '*[^0-9]*' AND target_revision>'00000000000000000000'),
 gate_token TEXT NOT NULL CHECK(length(gate_token)>0),message_id TEXT NOT NULL,
 outbound_seq TEXT NOT NULL CHECK(length(outbound_seq)=20 AND outbound_seq NOT GLOB '*[^0-9]*' AND outbound_seq>'00000000000000000000'),
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 lease_until_tick TEXT NOT NULL CHECK(length(lease_until_tick)=20 AND lease_until_tick NOT GLOB '*[^0-9]*'),
 request_digest TEXT NOT NULL CHECK(length(request_digest)=71 AND substr(request_digest,1,7)='sha256:'),
 body BLOB NOT NULL CHECK(length(body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 CHECK(selected_tick<expires_tick AND expires_tick<=lease_until_tick),UNIQUE(exit_id,message_id),UNIQUE(exit_id,outbound_seq),UNIQUE(close_ack_id),
 UNIQUE(exit_id,target_revision),UNIQUE(exit_id,gate_token)
) STRICT;
CREATE TABLE gf_ack(
 ack_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE REFERENCES gf_request(request_id),exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 message_id TEXT NOT NULL,reply_to TEXT NOT NULL,inbound_seq TEXT NOT NULL CHECK(length(inbound_seq)=20 AND inbound_seq NOT GLOB '*[^0-9]*' AND inbound_seq>'00000000000000000000'),
 request_digest TEXT NOT NULL,gate_revision TEXT NOT NULL,gate_token TEXT NOT NULL,
 effective_tick TEXT NOT NULL CHECK(length(effective_tick)=20 AND effective_tick NOT GLOB '*[^0-9]*'),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 evidence_digest TEXT NOT NULL,observer_ref TEXT NOT NULL CHECK(length(observer_ref)>0),
 body BLOB NOT NULL CHECK(length(body)>0),validation_body BLOB NOT NULL CHECK(length(validation_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(exit_id,message_id),UNIQUE(exit_id,inbound_seq)
) STRICT;
CREATE TABLE gf_commit(
 request_id TEXT PRIMARY KEY REFERENCES gf_request(request_id),ack_id TEXT NOT NULL UNIQUE REFERENCES gf_ack(ack_id),
 gate_id TEXT NOT NULL UNIQUE REFERENCES go_gate(gate_id),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE gf_revocation(
 ack_id TEXT PRIMARY KEY REFERENCES gf_ack(ack_id),reason_body BLOB NOT NULL CHECK(length(reason_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW gf_context AS SELECT r.* FROM gf_request r
 JOIN go_authority a ON a.change_id=r.authority_state_id AND a.device_id=r.device_id
 JOIN ct_current_state c ON c.change_id=r.control_state_id AND c.device_id=r.device_id
 JOIN ce_exit e ON e.exit_id=r.exit_id AND e.device_id=r.device_id
 JOIN ct_change cc ON cc.change_id=c.change_id
 JOIN go_close_ack k ON k.ack_id=r.close_ack_id AND k.exit_id=r.exit_id
 JOIN go_latest_close x ON x.close_id=k.close_id AND x.exit_id=r.exit_id AND x.gate_id IS r.previous_gate_id
 WHERE c.pending_operation_id IS NULL AND c.gate_state!='ready'
 AND cc.clock_domain=e.clock_domain_id AND cc.descriptor=e.descriptor_digest
 AND cc.now_tick<=r.selected_tick AND k.received_tick<=r.selected_tick
 AND r.safety_revision=coalesce((SELECT max(revision) FROM go_hazard h WHERE h.device_id=r.device_id),'00000000000000000000')
 AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id)
 AND NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=k.ack_id);
CREATE TRIGGER gf_request_guard AFTER INSERT ON gf_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_context WHERE request_id=NEW.request_id)
 OR EXISTS(SELECT 1 FROM gf_request r WHERE r.exit_id=NEW.exit_id AND r.request_id!=NEW.request_id AND r.target_revision>=NEW.target_revision)
 OR EXISTS(SELECT 1 FROM go_gate g WHERE g.exit_id=NEW.exit_id AND g.gate_token=NEW.gate_token)
 OR NOT ((NEW.previous_gate_id IS NULL AND NOT EXISTS(SELECT 1 FROM go_gate WHERE exit_id=NEW.exit_id)) OR
 EXISTS(SELECT 1 FROM go_current_gate g WHERE g.gate_id=NEW.previous_gate_id AND g.exit_id=NEW.exit_id
 AND NEW.target_revision>g.gate_revision AND NEW.gate_token!=g.gate_token))
 THEN RAISE(ABORT,'gate_fence_request') END;
END;
CREATE TRIGGER gf_ack_guard BEFORE INSERT ON gf_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_request r WHERE r.request_id=NEW.request_id AND r.exit_id=NEW.exit_id
 AND r.message_id=NEW.reply_to AND r.request_digest=NEW.request_digest AND r.target_revision=NEW.gate_revision AND r.gate_token=NEW.gate_token
 AND r.selected_tick<=NEW.effective_tick AND NEW.effective_tick<=NEW.received_tick)
 THEN RAISE(ABORT,'gate_fence_ack') END;
END;
CREATE TRIGGER gf_gate_guard BEFORE INSERT ON go_gate WHEN NEW.renewal_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_request r WHERE r.request_id=NEW.renewal_id AND r.exit_id=NEW.exit_id
 AND r.target_revision=NEW.gate_revision AND r.gate_token=NEW.gate_token AND r.lease_until_tick=NEW.lease_until_tick
 AND (NEW.phase='ready' OR (r.previous_gate_id IS NEW.previous_id AND EXISTS(SELECT 1 FROM gf_context c WHERE c.request_id=r.request_id))))
 THEN RAISE(ABORT,'gate_fence_projection') END;
END;
CREATE TRIGGER gf_commit_guard AFTER INSERT ON gf_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gf_context r JOIN gf_ack a USING(request_id) JOIN go_current_gate g ON g.gate_id=NEW.gate_id
 WHERE r.request_id=NEW.request_id AND a.ack_id=NEW.ack_id AND g.renewal_id=r.request_id AND g.phase='fenced'
 AND g.previous_id IS r.previous_gate_id AND g.exit_id=r.exit_id AND a.received_tick<=NEW.committed_tick AND NEW.committed_tick<r.expires_tick
 AND NOT EXISTS(SELECT 1 FROM gf_revocation v WHERE v.ack_id=a.ack_id))
 THEN RAISE(ABORT,'gate_fence_commit') END;
END;
CREATE VIEW gf_valid_fence AS SELECT k.*,r.exit_id,r.device_id FROM gf_commit k JOIN gf_request r USING(request_id)
 JOIN go_authority a ON a.change_id=r.authority_state_id AND a.device_id=r.device_id
 JOIN ct_current_state c ON c.device_id=r.device_id JOIN go_close_ack ca ON ca.ack_id=r.close_ack_id
 JOIN go_latest_close x ON x.close_id=ca.close_id AND x.exit_id=r.exit_id
 WHERE c.pending_operation_id IS NULL AND NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=r.exit_id)
 AND NOT EXISTS(SELECT 1 FROM gf_revocation v WHERE v.ack_id=k.ack_id)
 AND NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=ca.ack_id);
CREATE TRIGGER gf_revoke_hazard AFTER INSERT ON gf_revocation BEGIN
 INSERT INTO go_hazard(device_id,revision,source_kind,source_id)
 SELECT r.device_id,@GF_SUCCESSOR@,'gate_fence',NEW.ack_id FROM gf_ack a JOIN gf_request r USING(request_id) WHERE a.ack_id=NEW.ack_id;
END;
CREATE TRIGGER gf_hazard_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='gate_fence' AND NOT EXISTS(
 SELECT 1 FROM gf_revocation v JOIN gf_ack a USING(ack_id) JOIN gf_request r USING(request_id) WHERE v.ack_id=NEW.source_id AND r.device_id=NEW.device_id)
 BEGIN SELECT RAISE(ABORT,'hazard_source'); END;
