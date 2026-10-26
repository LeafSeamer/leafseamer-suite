DROP TRIGGER ij_domain_seal;
CREATE TRIGGER ij_domain_seal BEFORE INSERT ON ij_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND ((f.domain_kind='encoding_request' AND EXISTS(SELECT 1 FROM ij_encoding_frame d WHERE d.prepare_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition='applied')) OR
 (f.domain_kind='encoding_reply' AND EXISTS(SELECT 1 FROM ep_reply d WHERE d.prepare_id=f.domain_id AND d.journal_frame_id=f.frame_id AND EXISTS(SELECT 1 FROM ep_receive_commit c WHERE c.prepare_id=d.prepare_id AND c.committed_tick=NEW.committed_tick AND NEW.disposition=CASE c.disposition WHEN 'historical' THEN 'historical' ELSE 'applied' END))) OR
 (f.domain_kind='release_request' AND EXISTS(SELECT 1 FROM er_request d WHERE d.release_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM er_request_commit c WHERE c.release_id=d.release_id AND c.committed_tick=NEW.committed_tick))) OR
 (f.domain_kind='release_ack' AND EXISTS(SELECT 1 FROM er_ack d WHERE d.ack_id=f.domain_id AND d.journal_frame_id=f.frame_id AND EXISTS(SELECT 1 FROM er_ack_commit c WHERE c.ack_id=d.ack_id AND c.committed_tick=NEW.committed_tick AND NEW.disposition=CASE c.disposition WHEN 'historical' THEN 'historical' ELSE 'applied' END))) OR
 (f.domain_kind='open_request' AND EXISTS(SELECT 1 FROM go_dispatch d WHERE d.dispatch_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition='applied')) OR
 (f.domain_kind='open_ack' AND EXISTS(SELECT 1 FROM go_evidence d WHERE d.evidence_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition IN ('applied','historical'))) OR
 (f.domain_kind='renewal_request' AND EXISTS(SELECT 1 FROM gf_request d WHERE d.request_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition='applied')) OR
 (f.domain_kind='renewal_ack' AND EXISTS(SELECT 1 FROM gf_ack d WHERE d.ack_id=f.domain_id AND d.journal_frame_id=f.frame_id AND NEW.disposition IN ('applied','historical'))) OR
 (f.domain_kind='prepare_deny_request' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM pd_deny_request d WHERE d.deny_id=f.domain_id AND d.journal_frame_id=f.frame_id)) OR
 (f.domain_kind='prepare_deny_ack' AND NEW.disposition IN ('applied','historical') AND EXISTS(SELECT 1 FROM pd_deny_ack d WHERE d.ack_id=f.domain_id AND d.journal_frame_id=f.frame_id)) OR
 (f.domain_kind='authentication_close' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM authorization_close_dispatch d WHERE d.close_id=f.domain_id AND d.frame_id=f.frame_id AND d.selected_tick=NEW.committed_tick)) OR
 (f.domain_kind='authentication_close_ack' AND EXISTS(SELECT 1 FROM authorization_close_ack a WHERE a.ack_id=f.domain_id AND a.frame_id=f.frame_id AND a.disposition=NEW.disposition AND a.received_tick=NEW.committed_tick)) OR
 (f.domain_kind='gate_close' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM gate_close_dispatch d WHERE d.close_id=f.domain_id AND d.frame_id=f.frame_id AND d.selected_tick=NEW.committed_tick)) OR
 (f.domain_kind='gate_close_ack' AND EXISTS(SELECT 1 FROM gate_close_ack a WHERE a.ack_id=f.domain_id AND a.frame_id=f.frame_id AND a.disposition=NEW.disposition AND a.received_tick=NEW.committed_tick)) OR
 (f.domain_kind='handshake' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM ij_handshake d WHERE d.handshake_id=f.domain_id AND d.frame_id=f.frame_id AND d.kind=f.message_type)) OR
 (f.domain_kind='rejection' AND f.direction='w2c' AND NEW.disposition='rejected' AND EXISTS(SELECT 1 FROM ij_rejection d WHERE d.rejection_id=f.domain_id AND d.frame_id=f.frame_id)))) THEN RAISE(ABORT,'journal_missing_domain_commit') END;
END;
DROP VIEW gr_valid_target;
CREATE VIEW gc_base_gr_valid_target AS
 SELECT t.* FROM gr_all_target t JOIN go_recovery r USING(recovery_id) JOIN go_snapshot s USING(snapshot_id)
 JOIN go_close x ON x.close_id=t.close_id JOIN ce_exit e ON e.exit_id=x.exit_id JOIN ce_exit fresh ON fresh.exit_id=s.exit_id
 WHERE x.device_id=s.device_id AND (
 (t.kind='worker_ack' AND EXISTS(SELECT 1 FROM go_close_ack a JOIN pd_close_completion p ON p.ack_id=a.ack_id
 JOIN pd_valid_closure c ON c.closure_id=p.closure_id WHERE a.ack_id=t.ack_id AND a.close_id=t.close_id AND a.exit_id=x.exit_id
 AND p.close_id=t.close_id AND c.cut_id=x.prepare_cut_id AND a.received_tick<=r.now_tick)
 AND (e.clock_domain_id,e.descriptor_digest)=(fresh.clock_domain_id,fresh.descriptor_digest)
 AND NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=t.ack_id)
 AND NOT EXISTS(SELECT 1 FROM rcs_stopped_worker w WHERE
 (w.worker_boot_id,w.clock_domain_id,w.descriptor_digest)=(e.worker_boot_id,e.clock_domain_id,e.descriptor_digest))
 AND (NOT EXISTS(SELECT 1 FROM authorization_close_dispatch d WHERE d.close_id=t.close_id)
 OR EXISTS(SELECT 1 FROM authorization_close_usable_ack a WHERE a.close_id=t.close_id AND a.adopted_ack_id=t.ack_id)))
 OR(t.kind='supervisor_retired' AND t.exit_id=x.exit_id AND EXISTS(SELECT 1 FROM retired_close_usable u
 WHERE u.completion_id=t.completion_id AND u.exit_id=t.exit_id AND u.close_id=t.close_id)));
-- 先有设备保护与完整准备cut，再预约唯一关闭帧；不表示ACK或物理关闭。
CREATE TABLE gate_close_dispatch(
 close_id TEXT PRIMARY KEY NOT NULL REFERENCES go_close(close_id),
 frame_id TEXT NOT NULL UNIQUE REFERENCES ij_commit(frame_id) DEFERRABLE INITIALLY DEFERRED,
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TRIGGER gate_close_dispatch_guard BEFORE INSERT ON gate_close_dispatch BEGIN
 SELECT CASE WHEN NOT EXISTS(
 SELECT 1 FROM go_close c JOIN ct_commit committed ON committed.change_id=c.protection_change_id
 JOIN ct_change ctl ON ctl.change_id=c.protection_change_id JOIN ce_exit e ON e.exit_id=c.exit_id
 JOIN ct_current_state state ON state.change_id=c.protection_change_id
 JOIN pd_cut_commit cut ON cut.cut_id=c.prepare_cut_id
 JOIN ij_frame f ON f.frame_id=NEW.frame_id
 JOIN ij_exit route ON route.exit_id=c.exit_id
 WHERE c.close_id=NEW.close_id AND state.gate_state='protected'
 AND (ctl.clock_domain,ctl.descriptor)=(e.clock_domain_id,e.descriptor_digest)
 AND EXISTS(SELECT 1 FROM go_latest_close latest WHERE latest.close_id=c.close_id)
 AND NOT EXISTS(SELECT 1 FROM rcs_stopped_worker w WHERE (w.worker_boot_id,w.clock_domain_id,w.descriptor_digest)=(e.worker_boot_id,e.clock_domain_id,e.descriptor_digest))
 AND route.session_id=f.session_id AND f.exit_id=c.exit_id AND f.device_id=c.device_id
 AND f.domain_kind='gate_close' AND f.domain_id=c.close_id
 AND f.direction='c2w' AND f.message_type='CLOSE_GATE'
 AND f.observed_tick=NEW.selected_tick AND cut.committed_tick<=NEW.selected_tick
 AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)
 AND NOT EXISTS(SELECT 1 FROM ij_commit k WHERE k.frame_id=f.frame_id))
 THEN RAISE(ABORT,'gate_close_dispatch_binding') END;
END;
CREATE TRIGGER gate_close_dispatch_no_update BEFORE UPDATE ON gate_close_dispatch BEGIN SELECT RAISE(ABORT,'immutable authentication close dispatch'); END;
CREATE TRIGGER gate_close_dispatch_no_delete BEFORE DELETE ON gate_close_dispatch BEGIN SELECT RAISE(ABORT,'immutable authentication close dispatch'); END;
-- 历史ACK保存原件，但不能成为当前关闭资格；ACK与准备核销保持独立。
CREATE VIEW gate_close_live_dispatch AS SELECT d.* FROM gate_close_dispatch d
 JOIN go_latest_close c USING(close_id)
 JOIN ij_frame f ON f.frame_id=d.frame_id
 WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)
 AND NOT EXISTS(SELECT 1 FROM ce_exit e JOIN rcs_stopped_worker w ON (w.worker_boot_id,w.clock_domain_id,w.descriptor_digest)=(e.worker_boot_id,e.clock_domain_id,e.descriptor_digest) WHERE e.exit_id=c.exit_id);
-- 采用入口要求当前protected；已采用证据不因正常恢复改变控制记录而自失效。
CREATE VIEW gate_close_accepting_dispatch AS SELECT d.* FROM gate_close_live_dispatch d
 JOIN go_close c USING(close_id) JOIN ct_current_state s ON s.change_id=c.protection_change_id WHERE s.gate_state='protected';
CREATE TABLE gate_close_ack(
 ack_id TEXT PRIMARY KEY NOT NULL,close_id TEXT NOT NULL UNIQUE REFERENCES gate_close_dispatch(close_id),
 frame_id TEXT NOT NULL UNIQUE REFERENCES ij_commit(frame_id) DEFERRABLE INITIALLY DEFERRED,
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 disposition TEXT NOT NULL CHECK(disposition IN ('applied','historical')),
 adopted_ack_id TEXT UNIQUE REFERENCES go_close_ack(ack_id) DEFERRABLE INITIALLY DEFERRED,
 digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216),
 CHECK((disposition='applied' AND adopted_ack_id IS ack_id) OR (disposition='historical' AND adopted_ack_id IS NULL))
) STRICT;
CREATE TRIGGER gate_close_ack_guard BEFORE INSERT ON gate_close_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gate_close_dispatch d JOIN ij_frame original ON original.frame_id=d.frame_id
 JOIN ij_write_attempt attempt ON attempt.frame_id=original.frame_id JOIN ij_frame f ON f.frame_id=NEW.frame_id
 WHERE d.close_id=NEW.close_id AND f.domain_kind='gate_close_ack' AND f.domain_id=NEW.ack_id
 AND f.direction='w2c' AND f.message_type='CLOSE_GATE_ACK' AND f.exit_id IS NULL AND f.device_id IS NULL
 AND f.session_id=original.session_id AND f.reply_frame_id=original.frame_id AND f.reply_to=original.message_id
 AND attempt.attempted_tick<=NEW.received_tick AND f.observed_tick=NEW.received_tick
 AND NEW.disposition=CASE WHEN EXISTS(SELECT 1 FROM gate_close_accepting_dispatch live WHERE live.close_id=d.close_id) THEN 'applied' ELSE 'historical' END
 AND NOT EXISTS(SELECT 1 FROM ij_commit k WHERE k.frame_id=f.frame_id)) THEN RAISE(ABORT,'gate_close_ack_binding') END;
END;
CREATE TRIGGER gate_close_ack_adoption BEFORE INSERT ON go_close_ack
WHEN EXISTS(SELECT 1 FROM gate_close_dispatch WHERE close_id=NEW.close_id) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gate_close_ack a JOIN gate_close_accepting_dispatch d USING(close_id)
 JOIN go_close c USING(close_id) WHERE a.close_id=NEW.close_id AND a.adopted_ack_id=NEW.ack_id AND a.disposition='applied'
 AND NEW.exit_id=c.exit_id AND NEW.evidence_digest=a.digest AND NEW.body=a.body AND NEW.received_tick=a.received_tick)
 THEN RAISE(ABORT,'gate_close_ack_adoption') END;
END;
CREATE VIEW gate_close_usable_ack AS SELECT a.* FROM gate_close_ack a
 JOIN gate_close_live_dispatch d USING(close_id) JOIN ij_commit k ON k.frame_id=a.frame_id
 JOIN go_close_ack adopted ON adopted.ack_id=a.adopted_ack_id
 WHERE a.disposition='applied' AND k.disposition='applied'
 AND NOT EXISTS(SELECT 1 FROM go_revocation r WHERE r.kind='close_ack' AND r.object_id=a.adopted_ack_id);
CREATE TRIGGER gate_close_completion_current BEFORE INSERT ON pd_close_completion
WHEN EXISTS(SELECT 1 FROM gate_close_dispatch WHERE close_id=NEW.close_id) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gate_close_usable_ack a WHERE a.close_id=NEW.close_id AND a.adopted_ack_id=NEW.ack_id)
 THEN RAISE(ABORT,'gate_close_ack_not_current') END;
END;
CREATE TRIGGER gate_close_recovery_current BEFORE INSERT ON go_recovery_target
WHEN EXISTS(SELECT 1 FROM gate_close_dispatch WHERE close_id=NEW.close_id) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gate_close_usable_ack a WHERE a.close_id=NEW.close_id AND a.adopted_ack_id=NEW.ack_id)
 THEN RAISE(ABORT,'gate_close_ack_not_current') END;
END;
CREATE TRIGGER gate_close_ack_no_update BEFORE UPDATE ON gate_close_ack BEGIN SELECT RAISE(ABORT,'immutable authentication close ack'); END;
CREATE TRIGGER gate_close_ack_no_delete BEFORE DELETE ON gate_close_ack BEGIN SELECT RAISE(ABORT,'immutable authentication close ack'); END;
CREATE VIEW gr_valid_target AS SELECT t.* FROM gc_base_gr_valid_target t
 WHERE NOT EXISTS(SELECT 1 FROM gate_close_dispatch d WHERE d.close_id=t.close_id)
 OR EXISTS(SELECT 1 FROM gate_close_usable_ack a WHERE a.close_id=t.close_id AND a.adopted_ack_id=t.ack_id);
CREATE TRIGGER gate_close_exclusive BEFORE INSERT ON gate_close_dispatch
 WHEN EXISTS(SELECT 1 FROM authorization_close_dispatch WHERE close_id=NEW.close_id)
 BEGIN SELECT RAISE(ABORT,'duplicate_close_protocol'); END;
CREATE TRIGGER authorization_close_exclusive BEFORE INSERT ON authorization_close_dispatch
 WHEN EXISTS(SELECT 1 FROM gate_close_dispatch WHERE close_id=NEW.close_id)
 BEGIN SELECT RAISE(ABORT,'duplicate_close_protocol'); END;
