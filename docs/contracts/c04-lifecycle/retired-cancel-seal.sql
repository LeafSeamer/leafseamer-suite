CREATE TRIGGER pd_cut_seal BEFORE INSERT ON pd_cut_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pd_cut d WHERE d.cut_id=NEW.cut_id AND d.selected_tick<=NEW.committed_tick
 AND d.prepare_head=(SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration))
 OR EXISTS(SELECT cut_id,prepare_id,exit_id,authorization_id,authorization_digest FROM pd_expected WHERE cut_id=NEW.cut_id
 EXCEPT SELECT cut_id,prepare_id,exit_id,authorization_id,authorization_digest FROM pd_member WHERE cut_id=NEW.cut_id)
 OR EXISTS(SELECT 1 FROM pd_member m JOIN ep_revocation r USING(prepare_id) JOIN ep_request_commit k USING(prepare_id)
 WHERE m.cut_id=NEW.cut_id AND (r.revoked_tick>NEW.committed_tick OR k.committed_tick>NEW.committed_tick)
 AND NOT EXISTS(SELECT 1 FROM crp_valid v WHERE v.cut_id=m.cut_id AND v.prepare_id=m.prepare_id))
 OR EXISTS(SELECT 1 FROM pd_member m WHERE m.cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM ep_revocation v WHERE v.prepare_id=m.prepare_id))
 THEN RAISE(ABORT,'prepare_cut_incomplete') END;
END;
