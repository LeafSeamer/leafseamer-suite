CREATE TABLE gr_retired_target(
 recovery_id TEXT NOT NULL REFERENCES go_recovery(recovery_id),close_id TEXT NOT NULL REFERENCES go_close(close_id),
 completion_id TEXT NOT NULL REFERENCES rcs_commit(completion_id),exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 PRIMARY KEY(recovery_id,close_id),
 FOREIGN KEY(completion_id,exit_id) REFERENCES rcs_target(completion_id,exit_id)
) STRICT;
CREATE VIEW gr_all_target AS
 SELECT recovery_id,close_id,'worker_ack' AS kind,ack_id,NULL AS completion_id,NULL AS exit_id FROM go_recovery_target
 UNION ALL SELECT recovery_id,close_id,'supervisor_retired',NULL,completion_id,exit_id FROM gr_retired_target;
CREATE VIEW gr_valid_target AS
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
CREATE VIEW go_valid_recovery AS SELECT r.* FROM go_recovery r JOIN go_recovery_commit k USING(recovery_id)
 JOIN go_valid_snapshot s USING(snapshot_id) WHERE r.device_id=s.device_id
 AND NOT EXISTS(SELECT 1 FROM ce_exit e WHERE e.device_id=s.device_id AND NOT EXISTS(SELECT 1 FROM go_latest_close x WHERE x.exit_id=e.exit_id))
 AND NOT EXISTS(SELECT close_id FROM go_latest_close WHERE device_id=s.device_id EXCEPT SELECT close_id FROM gr_all_target WHERE recovery_id=r.recovery_id)
 AND NOT EXISTS(SELECT close_id FROM gr_all_target WHERE recovery_id=r.recovery_id EXCEPT SELECT close_id FROM go_latest_close WHERE device_id=s.device_id)
 AND NOT EXISTS(SELECT close_id,kind FROM gr_all_target WHERE recovery_id=r.recovery_id EXCEPT SELECT close_id,kind FROM gr_valid_target WHERE recovery_id=r.recovery_id);
CREATE TRIGGER go_recovery_seal AFTER INSERT ON go_recovery_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_valid_recovery r JOIN go_snapshot s USING(snapshot_id)
 WHERE r.recovery_id=NEW.recovery_id AND s.sampled_tick<=r.now_tick AND r.now_tick<s.expires_tick
 AND EXISTS(SELECT 1 FROM go_hazard h WHERE h.source_kind='recovery' AND h.recovery_id=r.recovery_id AND h.device_id=s.device_id AND h.revision=s.safety_revision)
 AND EXISTS(SELECT 1 FROM gr_all_target t WHERE t.recovery_id=r.recovery_id))
 THEN RAISE(ABORT,'recovery_close_choice_incomplete') END;
END;
CREATE TRIGGER pd_recovery_guard BEFORE INSERT ON go_recovery_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT close_id,kind FROM gr_all_target WHERE recovery_id=NEW.recovery_id
 EXCEPT SELECT close_id,kind FROM gr_valid_target WHERE recovery_id=NEW.recovery_id)
 THEN RAISE(ABORT,'recovery_close_proof_not_current') END;
END;
CREATE TRIGGER gr_retired_guard BEFORE INSERT ON gr_retired_target BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_recovery_commit WHERE recovery_id=NEW.recovery_id)
 OR EXISTS(SELECT 1 FROM go_recovery_target WHERE recovery_id=NEW.recovery_id AND close_id=NEW.close_id)
 OR NOT EXISTS(SELECT 1 FROM retired_close_usable u WHERE u.completion_id=NEW.completion_id AND u.close_id=NEW.close_id AND u.exit_id=NEW.exit_id)
 THEN RAISE(ABORT,'retired_recovery_choice') END;
END;
CREATE TRIGGER gr_ack_exclusive BEFORE INSERT ON go_recovery_target BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gr_retired_target WHERE recovery_id=NEW.recovery_id AND close_id=NEW.close_id)
 THEN RAISE(ABORT,'recovery_choice_exclusive') END;
END;
CREATE TRIGGER gr_retired_u BEFORE UPDATE ON gr_retired_target BEGIN SELECT RAISE(ABORT,'immutable_recovery_choice'); END;
CREATE TRIGGER gr_retired_d BEFORE DELETE ON gr_retired_target BEGIN SELECT RAISE(ABORT,'immutable_recovery_choice'); END;
