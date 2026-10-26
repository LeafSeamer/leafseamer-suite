-- 历史ACK保存原件，但不能成为当前关闭资格；ACK与准备核销保持独立。
CREATE VIEW authorization_close_live_dispatch AS SELECT d.* FROM authorization_close_dispatch d
 JOIN go_latest_close c USING(close_id)
 JOIN ij_frame f ON f.frame_id=d.frame_id
 WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id);
-- 采用入口要求当前protected；已采用证据不因正常恢复改变控制记录而自失效。
CREATE VIEW authorization_close_accepting_dispatch AS SELECT d.* FROM authorization_close_live_dispatch d
 JOIN go_close c USING(close_id) JOIN ct_current_state s ON s.change_id=c.protection_change_id WHERE s.gate_state='protected';
CREATE TABLE authorization_close_ack(
 ack_id TEXT PRIMARY KEY NOT NULL,close_id TEXT NOT NULL UNIQUE REFERENCES authorization_close_dispatch(close_id),
 frame_id TEXT NOT NULL UNIQUE REFERENCES ij_commit(frame_id) DEFERRABLE INITIALLY DEFERRED,
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 disposition TEXT NOT NULL CHECK(disposition IN ('applied','historical')),
 adopted_ack_id TEXT UNIQUE REFERENCES go_close_ack(ack_id) DEFERRABLE INITIALLY DEFERRED,
 digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216),
 CHECK((disposition='applied' AND adopted_ack_id IS ack_id) OR (disposition='historical' AND adopted_ack_id IS NULL))
) STRICT;
CREATE TRIGGER authorization_close_ack_guard BEFORE INSERT ON authorization_close_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM authorization_close_dispatch d JOIN ij_frame original ON original.frame_id=d.frame_id
 JOIN ij_write_attempt attempt ON attempt.frame_id=original.frame_id JOIN ij_frame f ON f.frame_id=NEW.frame_id
 WHERE d.close_id=NEW.close_id AND f.domain_kind='authentication_close_ack' AND f.domain_id=NEW.ack_id
 AND f.direction='w2c' AND f.message_type='CLOSE_GATE_ACK' AND f.exit_id IS NULL AND f.device_id IS NULL
 AND f.session_id=original.session_id AND f.reply_frame_id=original.frame_id AND f.reply_to=original.message_id
 AND attempt.attempted_tick<=NEW.received_tick AND f.observed_tick=NEW.received_tick
 AND NEW.disposition=CASE WHEN EXISTS(SELECT 1 FROM authorization_close_accepting_dispatch live WHERE live.close_id=d.close_id) THEN 'applied' ELSE 'historical' END
 AND NOT EXISTS(SELECT 1 FROM ij_commit k WHERE k.frame_id=f.frame_id)) THEN RAISE(ABORT,'authentication_close_ack_binding') END;
END;
CREATE TRIGGER authorization_close_ack_adoption BEFORE INSERT ON go_close_ack
WHEN EXISTS(SELECT 1 FROM authorization_close_dispatch WHERE close_id=NEW.close_id) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM authorization_close_ack a JOIN authorization_close_accepting_dispatch d USING(close_id)
 JOIN go_close c USING(close_id) WHERE a.close_id=NEW.close_id AND a.adopted_ack_id=NEW.ack_id AND a.disposition='applied'
 AND NEW.exit_id=c.exit_id AND NEW.evidence_digest=a.digest AND NEW.body=a.body AND NEW.received_tick=a.received_tick)
 THEN RAISE(ABORT,'authentication_close_ack_adoption') END;
END;
CREATE VIEW authorization_close_usable_ack AS SELECT a.* FROM authorization_close_ack a
 JOIN authorization_close_live_dispatch d USING(close_id) JOIN ij_commit k ON k.frame_id=a.frame_id
 JOIN go_close_ack adopted ON adopted.ack_id=a.adopted_ack_id
 WHERE a.disposition='applied' AND k.disposition='applied'
 AND NOT EXISTS(SELECT 1 FROM go_revocation r WHERE r.kind='close_ack' AND r.object_id=a.adopted_ack_id);
CREATE TRIGGER authorization_close_completion_current BEFORE INSERT ON pd_close_completion
WHEN EXISTS(SELECT 1 FROM authorization_close_dispatch WHERE close_id=NEW.close_id) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM authorization_close_usable_ack a WHERE a.close_id=NEW.close_id AND a.adopted_ack_id=NEW.ack_id)
 THEN RAISE(ABORT,'authentication_close_ack_not_current') END;
END;
CREATE TRIGGER authorization_close_recovery_current BEFORE INSERT ON go_recovery_target
WHEN EXISTS(SELECT 1 FROM authorization_close_dispatch WHERE close_id=NEW.close_id) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM authorization_close_usable_ack a WHERE a.close_id=NEW.close_id AND a.adopted_ack_id=NEW.ack_id)
 THEN RAISE(ABORT,'authentication_close_ack_not_current') END;
END;
CREATE VIEW go_valid_recovery AS SELECT r.* FROM authorization_base_go_valid_recovery r
 WHERE NOT EXISTS(SELECT 1 FROM go_recovery_target t JOIN authorization_close_dispatch d USING(close_id)
 WHERE t.recovery_id=r.recovery_id AND NOT EXISTS(SELECT 1 FROM authorization_close_usable_ack a WHERE a.close_id=t.close_id AND a.adopted_ack_id=t.ack_id));
CREATE TRIGGER authorization_close_ack_no_update BEFORE UPDATE ON authorization_close_ack BEGIN SELECT RAISE(ABORT,'immutable authentication close ack'); END;
CREATE TRIGGER authorization_close_ack_no_delete BEFORE DELETE ON authorization_close_ack BEGIN SELECT RAISE(ABORT,'immutable authentication close ack'); END;
