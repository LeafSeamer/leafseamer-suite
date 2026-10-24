-- 固定修订库存；资格与JCS仍由本地writer核验，JSON非空不是权威证明。
CREATE TABLE av_snapshot(
 command_id TEXT NOT NULL,
 revision TEXT NOT NULL,
 inventory_digest TEXT NOT NULL, inventory_body BLOB NOT NULL CHECK(json_valid(inventory_body) AND length(inventory_body)<=16777216),
 selection_digest TEXT NOT NULL, selection_body BLOB NOT NULL CHECK(json_valid(selection_body)),
 projection_digest TEXT NOT NULL, projection_body BLOB NOT NULL CHECK(json_valid(projection_body)),
 provider_digest TEXT NOT NULL, provider_body BLOB NOT NULL CHECK(json_valid(provider_body)),
 CHECK(length(inventory_body)+length(selection_body)+length(projection_body)+length(provider_body)<=16777216),
 PRIMARY KEY(command_id,revision),
 FOREIGN KEY(command_id,revision) REFERENCES cm_revision(command_id,revision),
 FOREIGN KEY(command_id,revision) REFERENCES cv_record(command_id,revision),
 FOREIGN KEY(command_id,revision) REFERENCES cm_commit(command_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER av_snapshot_insert BEFORE INSERT ON av_snapshot BEGIN
 SELECT CASE WHEN json_type(NEW.inventory_body,'$.attempts') IS NOT 'array' OR json_type(NEW.inventory_body,'$.packets') IS NOT 'array'
 OR json_type(NEW.inventory_body,'$.exits') IS NOT 'array' OR json_type(NEW.inventory_body,'$.transmissions') IS NOT 'array'
 OR json_type(NEW.inventory_body,'$.reports') IS NOT 'array' OR json_type(NEW.inventory_body,'$.evidence') IS NOT 'array'
 OR json_type(NEW.inventory_body,'$.assignments') IS NOT 'array' OR json_type(NEW.inventory_body,'$.valid_decision_refs') IS NOT 'array'
 OR json_type(NEW.inventory_body,'$.time_projections') IS NOT 'array'
 THEN RAISE(ABORT,'attempt_inventory_array_types') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cm_commit WHERE command_id=NEW.command_id AND revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_frozen') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cm_revision r JOIN cv_record v USING(command_id,revision)
 WHERE r.command_id=NEW.command_id AND r.revision=NEW.revision
 AND json_extract(NEW.inventory_body,'$.command_id')=NEW.command_id
 AND json_extract(NEW.inventory_body,'$.state_ref.id')=NEW.command_id
 AND json_extract(NEW.inventory_body,'$.state_ref.revision')=ltrim(NEW.revision,'0')
 AND json_extract(NEW.inventory_body,'$.state_ref.digest')=r.state_digest
 AND json(json_extract(NEW.inventory_body,'$.state'))=json(r.state_body)
 AND json(json_extract(NEW.projection_body,'$.state_ref'))=json(json_extract(NEW.inventory_body,'$.state_ref'))
 AND json(json_extract(NEW.projection_body,'$.attempts'))=json(json_extract(v.record_body,'$.attempts'))
 AND json(json_extract(NEW.projection_body,'$.selections'))=json(NEW.selection_body)
 AND json_extract(NEW.projection_body,'$.projection_digest')=NEW.projection_digest
 AND json(json_extract(NEW.provider_body,'$.state_ref'))=json(json_extract(NEW.inventory_body,'$.state_ref')))
 THEN RAISE(ABORT,'attempt_inventory_binding') END;
END;
CREATE TRIGGER av_publish BEFORE INSERT ON cm_commit
WHEN EXISTS(SELECT 1 FROM cm_revision_attempt WHERE command_id=NEW.command_id AND revision=NEW.revision) BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM av_snapshot WHERE command_id=NEW.command_id AND revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_required') END;
 -- 封存发生在最后公开提交点：先算inventory后出现的原件也不能漏掉。
 SELECT CASE WHEN EXISTS(
  SELECT a.attempt_id FROM cm_revision_attempt a WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
  EXCEPT SELECT json_extract(j.value,'$.attempt_id') FROM av_snapshot s,json_each(s.inventory_body,'$.attempts') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
  SELECT json_extract(j.value,'$.attempt_id') FROM av_snapshot s,json_each(s.inventory_body,'$.attempts') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
  EXCEPT SELECT a.attempt_id FROM cm_revision_attempt a WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_attempt_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM av_snapshot s WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision AND
 (json_array_length(s.inventory_body,'$.attempts')!=(SELECT count(*) FROM cm_revision_attempt WHERE command_id=NEW.command_id AND revision=NEW.revision)
 OR json_array_length(s.inventory_body,'$.packets')!=(SELECT count(*) FROM ce_packet p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 OR json_array_length(s.inventory_body,'$.transmissions')!=(SELECT count(*) FROM ce_permit p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 OR json_array_length(s.inventory_body,'$.reports')!=(SELECT count(*) FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 OR json_array_length(s.inventory_body,'$.assignments')!=(SELECT count(*) FROM ep_request e JOIN cm_revision_attempt a ON a.attempt_id=e.proposed_attempt_id WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision AND e.kind='ordinary')
 OR json_array_length(s.inventory_body,'$.evidence')!=(SELECT count(*) FROM cv_record v JOIN cv_snapshot_member m USING(snapshot_id) WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision)))
 THEN RAISE(ABORT,'attempt_inventory_member_count') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM av_snapshot s,json_each(s.inventory_body,'$.attempts') j
 WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision AND NOT EXISTS(
 SELECT 1 FROM cm_attempt a JOIN cm_revision r ON r.command_id=a.command_id AND r.revision=a.prepared_revision
 WHERE a.attempt_id=json_extract(j.value,'$.attempt_id') AND a.command_id=NEW.command_id
 AND a.ordinal=json_extract(j.value,'$.ordinal') AND json(r.state_body)=json(json_extract(j.value,'$.prepared_state'))))
 THEN RAISE(ABORT,'attempt_inventory_prepared') END;
 SELECT CASE WHEN EXISTS(
 SELECT p.packet_id FROM ce_packet p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.packet_id') FROM av_snapshot s,json_each(s.inventory_body,'$.packets') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
 SELECT json_extract(j.value,'$.packet_id') FROM av_snapshot s,json_each(s.inventory_body,'$.packets') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT p.packet_id FROM ce_packet p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_packet_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM av_snapshot s,json_each(s.inventory_body,'$.packets') j
 WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision AND NOT EXISTS(SELECT 1 FROM ce_packet p
 WHERE p.packet_id=json_extract(j.value,'$.packet_id') AND json(p.packet_body)=json(j.value)))
 THEN RAISE(ABORT,'attempt_inventory_packet_body') END;
 SELECT CASE WHEN EXISTS(
 SELECT p.permit_id FROM ce_permit p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.permit_id') FROM av_snapshot s,json_each(s.inventory_body,'$.transmissions') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
 SELECT json_extract(j.value,'$.permit_id') FROM av_snapshot s,json_each(s.inventory_body,'$.transmissions') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT p.permit_id FROM ce_permit p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_permit_set') END;
 SELECT CASE WHEN EXISTS(
 SELECT r.report_id FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.report_id') FROM av_snapshot s,json_each(s.inventory_body,'$.reports') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
 SELECT json_extract(j.value,'$.report_id') FROM av_snapshot s,json_each(s.inventory_body,'$.reports') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT r.report_id FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_report_set') END;
 SELECT CASE WHEN EXISTS(
 SELECT e.prepare_id FROM ep_request e JOIN cm_revision_attempt a ON a.attempt_id=e.proposed_attempt_id
 WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision AND e.kind='ordinary'
 EXCEPT SELECT json_extract(j.value,'$.prepare_id') FROM av_snapshot s,json_each(s.inventory_body,'$.assignments') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 OR EXISTS(
 SELECT json_extract(j.value,'$.prepare_id') FROM av_snapshot s,json_each(s.inventory_body,'$.assignments') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT e.prepare_id FROM ep_request e JOIN cm_revision_attempt a ON a.attempt_id=e.proposed_attempt_id
 WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision AND e.kind='ordinary')
 THEN RAISE(ABORT,'attempt_inventory_assignment_set') END;
 SELECT CASE WHEN EXISTS(SELECT json_extract(j.value,'$.source_ref.id'),json_extract(j.value,'$.source_ref.revision')
 FROM av_snapshot s,json_each(s.inventory_body,'$.evidence') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision
 EXCEPT SELECT e.evidence_id,ltrim(e.revision,'0') FROM cv_record v JOIN cv_snapshot_member m USING(snapshot_id)
 JOIN cv_evidence e ON e.evidence_id=m.evidence_id AND e.revision=m.evidence_revision WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision)
 OR EXISTS(SELECT e.evidence_id,ltrim(e.revision,'0') FROM cv_record v JOIN cv_snapshot_member m USING(snapshot_id)
 JOIN cv_evidence e ON e.evidence_id=m.evidence_id AND e.revision=m.evidence_revision WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.source_ref.id'),json_extract(j.value,'$.source_ref.revision')
 FROM av_snapshot s,json_each(s.inventory_body,'$.evidence') j WHERE s.command_id=NEW.command_id AND s.revision=NEW.revision)
 THEN RAISE(ABORT,'attempt_inventory_evidence_set') END;
END;
CREATE TRIGGER av_snapshot_update BEFORE UPDATE ON av_snapshot BEGIN SELECT RAISE(ABORT,'immutable_attempt_inventory'); END;
CREATE TRIGGER av_snapshot_delete BEFORE DELETE ON av_snapshot BEGIN SELECT RAISE(ABORT,'immutable_attempt_inventory'); END;
