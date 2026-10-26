CREATE TABLE xdp_protection(
 protection_id TEXT PRIMARY KEY NOT NULL REFERENCES authorization_clock_protection(protection_id),
 digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16777216),
 FOREIGN KEY(protection_id) REFERENCES xdp_commit(protection_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE xdp_retired(
 protection_id TEXT NOT NULL REFERENCES xdp_protection(protection_id),exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 completion_id TEXT NOT NULL REFERENCES rcs_commit(completion_id),close_id TEXT NOT NULL REFERENCES go_close(close_id),
 PRIMARY KEY(protection_id,exit_id)
) STRICT;
CREATE TABLE xdp_commit(
 protection_id TEXT PRIMARY KEY NOT NULL REFERENCES xdp_protection(protection_id),
 audit_body BLOB NOT NULL,outbox_body BLOB NOT NULL
) STRICT;
CREATE VIEW xdp_target AS
 SELECT p.protection_id,json_extract(t.value,'$.target.binding.writer_exit_id') exit_id,json_extract(t.value,'$.close_id') close_id,'active' kind,NULL completion_id
 FROM xdp_protection p JOIN authorization_clock_protection a USING(protection_id),json_each(CAST(a.body AS TEXT),'$.exits') t
 UNION ALL SELECT protection_id,exit_id,close_id,'retired',completion_id FROM xdp_retired;
CREATE VIEW xdp_usable AS SELECT p.* FROM xdp_protection p JOIN xdp_commit k USING(protection_id) JOIN authorization_clock_protection a USING(protection_id)
 WHERE NOT EXISTS(SELECT 1 FROM xdp_retired r WHERE r.protection_id=p.protection_id AND NOT EXISTS(
 SELECT 1 FROM retired_close_usable v WHERE v.completion_id=r.completion_id AND v.exit_id=r.exit_id AND v.close_id=r.close_id))
 AND NOT EXISTS(SELECT 1 FROM xdp_target t WHERE t.protection_id=p.protection_id AND NOT EXISTS(
 SELECT 1 FROM go_latest_close c WHERE c.exit_id=t.exit_id AND c.close_id=t.close_id))
 AND NOT EXISTS(SELECT 1 FROM json_each(CAST(a.body AS TEXT),'$.devices') d WHERE NOT EXISTS(
 SELECT 1 FROM ct_current_state s WHERE s.device_id=json_extract(d.value,'$.device_id') AND s.change_id=json_extract(d.value,'$.after_control_ref.id') AND s.gate_state='protected'));
CREATE TRIGGER xdp_body_guard BEFORE INSERT ON xdp_protection BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM authorization_clock_protection a WHERE a.protection_id=NEW.protection_id
 AND json_extract(CAST(NEW.body AS TEXT),'$.protection_id')=NEW.protection_id
 AND json_extract(CAST(NEW.body AS TEXT),'$.protection_digest')=NEW.digest
 AND json_extract(CAST(NEW.body AS TEXT),'$.active_protection')=CAST(a.body AS TEXT))
 THEN RAISE(ABORT,'domain_protection_body_binding') END;
END;
CREATE TRIGGER xdp_no_cross_domain_close BEFORE INSERT ON go_close BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ce_exit e ON e.exit_id=NEW.exit_id
 WHERE c.change_id=NEW.protection_change_id AND (c.clock_domain,c.descriptor)!=(e.clock_domain_id,e.descriptor_digest))
 THEN RAISE(ABORT,'cross_domain_close_requires_retirement') END;
END;
CREATE TRIGGER xdp_retired_guard BEFORE INSERT ON xdp_retired BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM xdp_commit WHERE protection_id=NEW.protection_id)
 OR NOT EXISTS(SELECT 1 FROM retired_close_usable v WHERE v.completion_id=NEW.completion_id AND v.exit_id=NEW.exit_id AND v.close_id=NEW.close_id)
 THEN RAISE(ABORT,'domain_protection_retired_binding') END;
END;
CREATE TRIGGER xdp_seal BEFORE INSERT ON xdp_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM xdp_protection p WHERE p.protection_id=NEW.protection_id AND p.body=NEW.audit_body AND p.body=NEW.outbox_body)
 OR EXISTS(SELECT 1 FROM xdp_protection p WHERE p.protection_id=NEW.protection_id AND json_array_length(CAST(p.body AS TEXT),'$.retired')!=(SELECT count(*) FROM xdp_retired r WHERE r.protection_id=p.protection_id))
 OR NOT EXISTS(SELECT 1 FROM xdp_retired WHERE protection_id=NEW.protection_id)
 OR EXISTS(SELECT exit_id FROM xdp_target WHERE protection_id=NEW.protection_id GROUP BY exit_id HAVING count(*)!=1)
 OR EXISTS(SELECT 1 FROM xdp_protection p JOIN authorization_clock_protection a USING(protection_id),json_each(CAST(a.body AS TEXT),'$.devices') d
 JOIN ce_exit e ON e.device_id=json_extract(d.value,'$.device_id') WHERE p.protection_id=NEW.protection_id
 AND NOT EXISTS(SELECT 1 FROM xdp_target t WHERE t.protection_id=p.protection_id AND t.exit_id=e.exit_id))
 OR EXISTS(SELECT 1 FROM xdp_target t JOIN ce_exit e USING(exit_id) JOIN authorization_clock_protection a ON a.protection_id=t.protection_id
 WHERE t.protection_id=NEW.protection_id AND (NOT EXISTS(SELECT 1 FROM json_each(CAST(a.body AS TEXT),'$.devices') d WHERE json_extract(d.value,'$.device_id')=e.device_id)
 OR NOT EXISTS(SELECT 1 FROM go_latest_close c WHERE c.exit_id=t.exit_id AND c.close_id=t.close_id)))
 OR EXISTS(SELECT 1 FROM xdp_retired r WHERE r.protection_id=NEW.protection_id AND NOT EXISTS(
 SELECT 1 FROM retired_close_usable v WHERE v.completion_id=r.completion_id AND v.exit_id=r.exit_id AND v.close_id=r.close_id))
 THEN RAISE(ABORT,'domain_protection_complete_set') END;
END;
CREATE TRIGGER xdp_p_u BEFORE UPDATE ON xdp_protection BEGIN SELECT RAISE(ABORT,'immutable_domain_protection'); END;
CREATE TRIGGER xdp_p_d BEFORE DELETE ON xdp_protection BEGIN SELECT RAISE(ABORT,'immutable_domain_protection'); END;
CREATE TRIGGER xdp_r_u BEFORE UPDATE ON xdp_retired BEGIN SELECT RAISE(ABORT,'immutable_domain_protection'); END;
CREATE TRIGGER xdp_r_d BEFORE DELETE ON xdp_retired BEGIN SELECT RAISE(ABORT,'immutable_domain_protection'); END;
CREATE TRIGGER xdp_k_u BEFORE UPDATE ON xdp_commit BEGIN SELECT RAISE(ABORT,'immutable_domain_protection'); END;
CREATE TRIGGER xdp_k_d BEFORE DELETE ON xdp_commit BEGIN SELECT RAISE(ABORT,'immutable_domain_protection'); END;
