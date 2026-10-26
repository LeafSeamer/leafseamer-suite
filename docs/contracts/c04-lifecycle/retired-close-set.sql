-- 仅安装到完整退役采用候选。旧时钟域不产生新的完成tick。
CREATE VIEW rcs_stopped_worker AS
 SELECT DISTINCT e.worker_boot_id,e.clock_domain_id,e.descriptor_digest FROM ce_exit e JOIN sr_commit k USING(exit_id);
CREATE TRIGGER rcs_no_old_exit BEFORE INSERT ON ce_exit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM rcs_stopped_worker w WHERE
 (w.worker_boot_id,w.clock_domain_id,w.descriptor_digest)=(NEW.worker_boot_id,NEW.clock_domain_id,NEW.descriptor_digest))
 THEN RAISE(ABORT,'retired_worker_registration') END;
END;
CREATE TRIGGER rcs_no_old_session BEFORE INSERT ON ij_session BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM rcs_stopped_worker w WHERE
 (w.worker_boot_id,w.clock_domain_id,w.descriptor_digest)=(NEW.worker_boot_id,NEW.clock_domain_id,NEW.descriptor_digest))
 THEN RAISE(ABORT,'retired_worker_session') END;
END;
CREATE TRIGGER rcs_no_old_write BEFORE INSERT ON ij_write_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ij_frame f JOIN ij_session s USING(session_id) JOIN rcs_stopped_worker w
 ON (w.worker_boot_id,w.clock_domain_id,w.descriptor_digest)=(s.worker_boot_id,s.clock_domain_id,s.descriptor_digest)
 WHERE f.frame_id=NEW.frame_id) THEN RAISE(ABORT,'retired_worker_write') END;
END;
CREATE TRIGGER rcs_no_old_prepare BEFORE INSERT ON ep_request BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ce_exit e JOIN rcs_stopped_worker w
 ON (w.worker_boot_id,w.clock_domain_id,w.descriptor_digest)=(e.worker_boot_id,e.clock_domain_id,e.descriptor_digest)
 WHERE e.exit_id=NEW.exit_id) THEN RAISE(ABORT,'retired_worker_prepare') END;
END;
CREATE TABLE rcs_completion(
 completion_id TEXT PRIMARY KEY NOT NULL,anchor_exit_id TEXT NOT NULL REFERENCES sr_commit(exit_id),
 digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16777216),
 FOREIGN KEY(completion_id) REFERENCES rcs_commit(completion_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE rcs_target(
 completion_id TEXT NOT NULL REFERENCES rcs_completion(completion_id),exit_id TEXT NOT NULL REFERENCES sr_commit(exit_id),
 close_id TEXT NOT NULL REFERENCES go_close(close_id),adoption_digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body)>0),PRIMARY KEY(completion_id,exit_id),UNIQUE(completion_id,close_id)
) STRICT;
CREATE TABLE rcs_commit(
 completion_id TEXT PRIMARY KEY NOT NULL REFERENCES rcs_completion(completion_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE VIEW rcs_current_candidate AS SELECT c.* FROM rcs_completion c JOIN ce_exit a ON a.exit_id=c.anchor_exit_id
 WHERE NOT EXISTS(SELECT e.exit_id FROM ce_exit e WHERE
 (e.worker_boot_id,e.clock_domain_id,e.descriptor_digest)=(a.worker_boot_id,a.clock_domain_id,a.descriptor_digest)
 EXCEPT SELECT exit_id FROM rcs_target t WHERE t.completion_id=c.completion_id)
 AND NOT EXISTS(SELECT 1 FROM rcs_target t JOIN ce_exit e USING(exit_id) WHERE t.completion_id=c.completion_id AND
 ((e.worker_boot_id,e.clock_domain_id,e.descriptor_digest)!=(a.worker_boot_id,a.clock_domain_id,a.descriptor_digest)
 OR NOT EXISTS(SELECT 1 FROM sr_current r WHERE r.exit_id=t.exit_id AND r.digest=t.adoption_digest)
 OR NOT EXISTS(SELECT 1 FROM go_latest_close x JOIN pd_cut_commit k ON k.cut_id=x.prepare_cut_id WHERE x.close_id=t.close_id AND x.exit_id=t.exit_id)
 OR EXISTS(SELECT r.prepare_id FROM ep_request r WHERE r.exit_id=t.exit_id EXCEPT
 SELECT m.prepare_id FROM pd_member m JOIN go_close x ON x.prepare_cut_id=m.cut_id WHERE x.close_id=t.close_id)));
CREATE VIEW rcs_current AS SELECT c.* FROM rcs_current_candidate c JOIN rcs_commit k USING(completion_id);
CREATE VIEW retired_close_usable AS SELECT t.* FROM rcs_target t JOIN rcs_current c USING(completion_id);
CREATE TRIGGER rcs_target_guard BEFORE INSERT ON rcs_target BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM rcs_commit WHERE completion_id=NEW.completion_id)
 OR NOT EXISTS(SELECT 1 FROM rcs_completion c,json_each(CAST(c.body AS TEXT),'$.targets') j
 WHERE c.completion_id=NEW.completion_id AND json_extract(j.value,'$.binding.writer_exit_id')=NEW.exit_id
 AND json_extract(j.value,'$.close_ref.id')=NEW.close_id AND json_extract(j.value,'$.retirement_adoption_ref.digest')=NEW.adoption_digest
 AND json(j.value)=json(CAST(NEW.body AS TEXT))) THEN RAISE(ABORT,'retired_close_target_body') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_close x JOIN pd_cut d ON d.cut_id=x.prepare_cut_id
 JOIN sr_adoption a ON a.exit_id=x.exit_id JOIN ce_exit e ON e.exit_id=x.exit_id
 WHERE x.close_id=NEW.close_id AND x.exit_id=NEW.exit_id AND a.digest=NEW.adoption_digest
 AND json_extract(CAST(NEW.body AS TEXT),'$.retirement_adoption_ref.id')=a.adoption_id
 AND json_extract(CAST(NEW.body AS TEXT),'$.binding')=json_extract(CAST(a.body AS TEXT),'$.binding')
 AND json_extract(CAST(NEW.body AS TEXT),'$.runtime_binding_ref')=json_extract(CAST(a.body AS TEXT),'$.runtime_binding_ref')
 AND json_extract(CAST(NEW.body AS TEXT),'$.cut_ref.id')=d.cut_id
 AND json_extract(CAST(NEW.body AS TEXT),'$.prepare_head')=coalesce(nullif(ltrim(d.prepare_head,'0'),''),'0')
 AND json_array_length(CAST(NEW.body AS TEXT),'$.preparations')=(SELECT count(*) FROM pd_member m WHERE m.cut_id=d.cut_id)
 AND NOT EXISTS(SELECT m.prepare_id FROM pd_member m WHERE m.cut_id=d.cut_id EXCEPT
 SELECT json_extract(p.value,'$.prepare_id') FROM json_each(CAST(NEW.body AS TEXT),'$.preparations') p)
 AND NOT EXISTS(SELECT 1 FROM json_each(CAST(NEW.body AS TEXT),'$.preparations') p WHERE NOT EXISTS(
 SELECT 1 FROM pd_member m JOIN ep_revocation v USING(prepare_id) JOIN ep_request r USING(prepare_id)
 JOIN ij_encoding_frame f USING(prepare_id) WHERE m.cut_id=d.cut_id AND m.exit_id=NEW.exit_id
 AND m.prepare_id=json_extract(p.value,'$.prepare_id') AND json_extract(p.value,'$.basis')='retired'
 AND json_extract(p.value,'$.encoding_authorization_ref.id')=m.authorization_id
 AND json_extract(p.value,'$.encoding_authorization_ref.digest')=m.authorization_digest
 AND json_extract(p.value,'$.revocation_ref.id')=v.revocation_id
 AND json_extract(p.value,'$.revocation_ref.digest')=v.revocation_digest
 AND json_extract(p.value,'$.encoding_frame_ref.id')=f.journal_frame_id
 AND json_extract(p.value,'$.encoding_frame_ref.digest')=f.request_frame_digest)))
 THEN RAISE(ABORT,'retired_close_prepare_coverage') END;
END;
CREATE TRIGGER rcs_seal BEFORE INSERT ON rcs_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rcs_current_candidate c WHERE c.completion_id=NEW.completion_id
 AND c.body=NEW.outbox_body AND c.body=NEW.audit_body
 AND json_extract(CAST(c.body AS TEXT),'$.completion_id')=c.completion_id
 AND json_extract(CAST(c.body AS TEXT),'$.completion_digest')=c.digest
 AND json_array_length(CAST(c.body AS TEXT),'$.targets')=(SELECT count(*) FROM rcs_target WHERE completion_id=c.completion_id))
 THEN RAISE(ABORT,'retired_close_set_incomplete') END;
END;
CREATE TRIGGER rcs_completion_u BEFORE UPDATE ON rcs_completion BEGIN SELECT RAISE(ABORT,'immutable_retired_close'); END;
CREATE TRIGGER rcs_completion_d BEFORE DELETE ON rcs_completion BEGIN SELECT RAISE(ABORT,'immutable_retired_close'); END;
CREATE TRIGGER rcs_target_u BEFORE UPDATE ON rcs_target BEGIN SELECT RAISE(ABORT,'immutable_retired_close'); END;
CREATE TRIGGER rcs_target_d BEFORE DELETE ON rcs_target BEGIN SELECT RAISE(ABORT,'immutable_retired_close'); END;
CREATE TRIGGER rcs_commit_u BEFORE UPDATE ON rcs_commit BEGIN SELECT RAISE(ABORT,'immutable_retired_close'); END;
CREATE TRIGGER rcs_commit_d BEFORE DELETE ON rcs_commit BEGIN SELECT RAISE(ABORT,'immutable_retired_close'); END;
