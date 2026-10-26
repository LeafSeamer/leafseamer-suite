-- 取消切点的显式跨域退役证明；不扩展其他类别切点，不重写旧tick。
CREATE TABLE crp_member(
 cut_id TEXT NOT NULL,prepare_id TEXT NOT NULL,completion_id TEXT NOT NULL REFERENCES rcs_commit(completion_id),
 exit_id TEXT NOT NULL REFERENCES sr_commit(exit_id),body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16384),
 audit_body BLOB NOT NULL CHECK(audit_body=body),PRIMARY KEY(cut_id,prepare_id),
 FOREIGN KEY(cut_id,prepare_id) REFERENCES pd_member(cut_id,prepare_id),
 FOREIGN KEY(cut_id) REFERENCES pd_cut_commit(cut_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW crp_valid AS SELECT p.* FROM crp_member p JOIN pd_cut d USING(cut_id)
 JOIN pd_member m USING(cut_id,prepare_id) JOIN ce_exit e ON e.exit_id=m.exit_id
 JOIN rcs_current c ON c.completion_id=p.completion_id JOIN rcs_target t ON t.completion_id=c.completion_id AND t.exit_id=e.exit_id
 JOIN sr_adoption a ON a.exit_id=e.exit_id JOIN ep_revocation r USING(prepare_id)
 WHERE d.kind='cancel' AND p.exit_id=e.exit_id
 AND json_extract(CAST(d.selector_body AS TEXT),'$.format_version')='retired-cancel-source/0.1.0-draft.1'
 AND json_extract(CAST(d.selector_body AS TEXT),'$.selection.clock_domain_id')!=e.clock_domain_id
 AND json_extract(CAST(a.body AS TEXT),'$.source_bundle.evaluator_descriptor.clock_domain_id')=json_extract(CAST(d.selector_body AS TEXT),'$.selection.clock_domain_id')
 AND json_extract(CAST(a.body AS TEXT),'$.source_bundle.evaluator_descriptor.descriptor_digest')=json_extract(CAST(d.selector_body AS TEXT),'$.selection.descriptor_digest')
 AND json_type(CAST(a.body AS TEXT),'$.source_bundle.evidence.observed_tick_ns')='text'
 AND (length(CAST(json_extract(CAST(a.body AS TEXT),'$.source_bundle.evidence.observed_tick_ns') AS TEXT))<length(coalesce(nullif(ltrim(d.selected_tick,'0'),''),'0'))
 OR (length(CAST(json_extract(CAST(a.body AS TEXT),'$.source_bundle.evidence.observed_tick_ns') AS TEXT))=length(coalesce(nullif(ltrim(d.selected_tick,'0'),''),'0')) AND CAST(json_extract(CAST(a.body AS TEXT),'$.source_bundle.evidence.observed_tick_ns') AS TEXT)<=coalesce(nullif(ltrim(d.selected_tick,'0'),''),'0')))
 AND json_extract(CAST(p.body AS TEXT),'$.prepare_id')=m.prepare_id AND json_extract(CAST(p.body AS TEXT),'$.exit_id')=e.exit_id
 AND json_extract(CAST(p.body AS TEXT),'$.authorization_id')=m.authorization_id AND json_extract(CAST(p.body AS TEXT),'$.authorization_digest')=m.authorization_digest
 AND json_extract(CAST(p.body AS TEXT),'$.completion_ref.id')=c.completion_id AND json_extract(CAST(p.body AS TEXT),'$.completion_ref.digest')=c.digest
 AND json_extract(CAST(p.body AS TEXT),'$.adoption_ref.id')=a.adoption_id AND json_extract(CAST(p.body AS TEXT),'$.adoption_ref.digest')=a.digest
 AND json_extract(CAST(p.body AS TEXT),'$.revocation_ref.id')=r.revocation_id AND json_extract(CAST(p.body AS TEXT),'$.revocation_ref.digest')=r.revocation_digest
 AND EXISTS(SELECT 1 FROM json_each(CAST(d.selector_body AS TEXT),'$.retirements') j WHERE json(j.value)=json(CAST(p.body AS TEXT)))
 AND EXISTS(SELECT 1 FROM json_each(CAST(t.body AS TEXT),'$.preparations') j WHERE json_extract(j.value,'$.prepare_id')=m.prepare_id
 AND json_extract(j.value,'$.encoding_authorization_ref.id')=m.authorization_id AND json_extract(j.value,'$.encoding_authorization_ref.digest')=m.authorization_digest
 AND json_extract(j.value,'$.revocation_ref.id')=r.revocation_id AND json_extract(j.value,'$.revocation_ref.digest')=r.revocation_digest);
CREATE TRIGGER crp_insert BEFORE INSERT ON crp_member BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pd_cut_commit WHERE cut_id=NEW.cut_id) THEN RAISE(ABORT,'retired_cancel_frozen') END;
END;
CREATE TRIGGER crp_seal BEFORE INSERT ON pd_cut_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM crp_member p WHERE p.cut_id=NEW.cut_id AND NOT EXISTS(SELECT 1 FROM crp_valid v WHERE v.cut_id=p.cut_id AND v.prepare_id=p.prepare_id))
 OR EXISTS(SELECT 1 FROM pd_cut d WHERE d.cut_id=NEW.cut_id AND json_extract(CAST(d.selector_body AS TEXT),'$.format_version')='retired-cancel-source/0.1.0-draft.1'
 AND (json_array_length(CAST(d.selector_body AS TEXT),'$.retirements')!=(SELECT count(*) FROM crp_member p WHERE p.cut_id=d.cut_id)
 OR EXISTS(SELECT 1 FROM pd_member m JOIN ce_exit e USING(exit_id) WHERE m.cut_id=d.cut_id
 AND (e.clock_domain_id!=json_extract(CAST(d.selector_body AS TEXT),'$.selection.clock_domain_id') OR e.descriptor_digest!=json_extract(CAST(d.selector_body AS TEXT),'$.selection.descriptor_digest'))
 AND NOT EXISTS(SELECT 1 FROM crp_valid p WHERE p.cut_id=d.cut_id AND p.prepare_id=m.prepare_id))))
 THEN RAISE(ABORT,'retired_cancel_incomplete') END;
END;
CREATE TRIGGER crp_u BEFORE UPDATE ON crp_member BEGIN SELECT RAISE(ABORT,'immutable_retired_cancel'); END;
CREATE TRIGGER crp_d BEFORE DELETE ON crp_member BEGIN SELECT RAISE(ABORT,'immutable_retired_cancel'); END;
