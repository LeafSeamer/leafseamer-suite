-- 先有设备保护与完整准备cut，再预约唯一关闭帧；不表示ACK或物理关闭。
CREATE TABLE authorization_close_dispatch(
 close_id TEXT PRIMARY KEY NOT NULL REFERENCES go_close(close_id),
 protection_id TEXT NOT NULL REFERENCES authorization_clock_protection(protection_id),
 frame_id TEXT NOT NULL UNIQUE REFERENCES ij_commit(frame_id) DEFERRABLE INITIALLY DEFERRED,
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TRIGGER authorization_close_dispatch_guard BEFORE INSERT ON authorization_close_dispatch BEGIN
 SELECT CASE WHEN NOT EXISTS(
 SELECT 1 FROM go_close c JOIN ct_commit committed ON committed.change_id=c.protection_change_id
 JOIN ct_current_state state ON state.change_id=c.protection_change_id
 JOIN pd_cut_commit cut ON cut.cut_id=c.prepare_cut_id
 JOIN authorization_clock_protection p ON p.protection_id=NEW.protection_id
 JOIN json_each(p.body,'$.exits') member
 JOIN ij_frame f ON f.frame_id=NEW.frame_id
 JOIN ij_exit route ON route.exit_id=c.exit_id
 WHERE c.close_id=NEW.close_id AND state.gate_state='protected'
 AND json_extract(member.value,'$.close_id')=c.close_id
 AND json_extract(member.value,'$.target.binding.writer_exit_id')=c.exit_id
 AND json_extract(member.value,'$.target.required_action')='close_gate'
 AND json_extract(member.value,'$.target.session_id')=f.session_id
 AND route.session_id=f.session_id AND f.exit_id=c.exit_id AND f.device_id=c.device_id
 AND f.domain_kind='authentication_close' AND f.domain_id=c.close_id
 AND f.direction='c2w' AND f.message_type='CLOSE_GATE'
 AND f.observed_tick=NEW.selected_tick AND cut.committed_tick<=NEW.selected_tick
 AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)
 AND NOT EXISTS(SELECT 1 FROM ij_commit k WHERE k.frame_id=f.frame_id))
 THEN RAISE(ABORT,'authentication_close_dispatch_binding') END;
END;
CREATE TRIGGER authorization_close_dispatch_no_update BEFORE UPDATE ON authorization_close_dispatch BEGIN SELECT RAISE(ABORT,'immutable authentication close dispatch'); END;
CREATE TRIGGER authorization_close_dispatch_no_delete BEFORE DELETE ON authorization_close_dispatch BEGIN SELECT RAISE(ABORT,'immutable authentication close dispatch'); END;
