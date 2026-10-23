-- Seamer：普通执行显式采用独立转交资格；原准备行不改为arm。
CREATE TABLE cn_step(
 execution_id TEXT NOT NULL,step_id TEXT NOT NULL,transfer_id TEXT NOT NULL,registration_id TEXT NOT NULL,
 device_id TEXT NOT NULL,adoption_digest TEXT NOT NULL,grant_ref_body BLOB NOT NULL CHECK(json_valid(grant_ref_body)),
 PRIMARY KEY(execution_id,step_id),FOREIGN KEY(execution_id,step_id) REFERENCES execution_step_plan(execution_id,step_id),
 FOREIGN KEY(transfer_id,registration_id) REFERENCES rc_receipt(transfer_id,registration_id),
 FOREIGN KEY(transfer_id) REFERENCES rc_adoption_commit(transfer_id)
) STRICT;
CREATE TABLE cn_withdrawal(
 transfer_id TEXT NOT NULL,registration_id TEXT NOT NULL,proof_body BLOB NOT NULL CHECK(length(proof_body) BETWEEN 1 AND 16384),
 PRIMARY KEY(transfer_id,registration_id),FOREIGN KEY(transfer_id,registration_id) REFERENCES rc_receipt(transfer_id,registration_id),
 FOREIGN KEY(registration_id) REFERENCES pq_fault(registration_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW cn_current AS SELECT q.*,t.registration_id,t.target_body,z.receipt_body,a.adoption_digest,a.adoption_body FROM rc_request q
 JOIN rc_target t USING(transfer_id) JOIN rc_receipt z USING(transfer_id,registration_id) JOIN rc_adoption a USING(transfer_id)
 JOIN rc_adoption_commit ak USING(transfer_id) JOIN rc_r5_link link USING(transfer_id) JOIN flow_commit_seal seal ON seal.commit_id=link.commit_id
 JOIN p1_preparation p USING(registration_id) JOIN pq_current pq USING(registration_id) JOIN run r ON r.run_id=q.run_id
 WHERE r.arm_generation=q.generation AND p.generation=q.generation AND pq.qualification='observed_applied'
 AND link.adoption_digest=a.adoption_digest AND NOT EXISTS(SELECT 1 FROM cn_withdrawal w WHERE w.transfer_id=q.transfer_id AND w.registration_id=t.registration_id)
 AND NOT EXISTS(SELECT 1 FROM p1_deny d WHERE d.run_id=q.run_id AND d.generation>=substr('00000000000000000000'||q.generation,-20));
CREATE TRIGGER cn_step_guard BEFORE INSERT ON cn_step BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cn_current c JOIN execution e ON e.run_id=c.run_id AND e.arm_generation=c.generation
 JOIN execution_step_plan p ON p.execution_id=e.execution_id JOIN execution_plan_set ps ON ps.execution_id=e.execution_id
 WHERE e.execution_id=NEW.execution_id AND e.origin_kind='trigger' AND e.execution_id!=c.execution_id AND p.step_id=NEW.step_id AND p.kind='action' AND ps.sealed=0
 AND c.transfer_id=NEW.transfer_id AND c.registration_id=NEW.registration_id AND c.adoption_digest=NEW.adoption_digest
 AND json(NEW.grant_ref_body)=json(json_extract(c.receipt_body,'$.continuation_grant_ref'))
 AND NEW.device_id=json_extract(p.plan_body,'$.request.device_id')
 AND NEW.transfer_id=json_extract(p.plan_body,'$.request.continuation.transfer_id') AND NEW.registration_id=json_extract(p.plan_body,'$.request.continuation.registration_id')
 AND NEW.adoption_digest=json_extract(p.plan_body,'$.request.continuation.adoption_digest')
 AND json(NEW.grant_ref_body)=json(json_extract(p.plan_body,'$.request.continuation.grant_ref'))
 AND json(json_extract(p.plan_body,'$.controller_scope'))=json(json_extract(c.target_body,'$.controller_scope'))
 AND EXISTS(SELECT 1 FROM json_each(c.target_body,'$.devices') d WHERE json_extract(d.value,'$.device_id')=NEW.device_id))
 THEN RAISE(ABORT,'continuation_step_binding') END;
END;
CREATE TRIGGER cn_attempt_guard BEFORE INSERT ON submission_attempt WHEN EXISTS(
 SELECT 1 FROM command_submission s JOIN cn_step t USING(execution_id,step_id) WHERE s.submission_id=NEW.submission_id
 AND NOT EXISTS(SELECT 1 FROM cn_current c WHERE c.transfer_id=t.transfer_id AND c.registration_id=t.registration_id AND c.adoption_digest=t.adoption_digest))
 BEGIN SELECT RAISE(ABORT,'continuation_attempt_revoked'); END;
CREATE TRIGGER cn_withdrawal_guard BEFORE INSERT ON cn_withdrawal WHEN NOT EXISTS(
 SELECT 1 FROM rc_request q JOIN rc_target t USING(transfer_id) JOIN p1_preparation p USING(registration_id)
 WHERE q.transfer_id=NEW.transfer_id AND p.registration_id=NEW.registration_id AND p.run_id=q.run_id AND p.generation=q.generation)
 BEGIN SELECT RAISE(ABORT,'continuation_withdrawal_binding'); END;
CREATE TRIGGER cn_withdrawal_seal BEFORE INSERT ON pq_commit WHEN EXISTS(
 SELECT 1 FROM pq_plan p JOIN pq_fault f USING(registration_id) JOIN rc_target t USING(registration_id)
 WHERE p.plan_id=NEW.plan_id AND f.kind='withdrawal' AND json_extract(f.evidence_body,'$.proof_ref.id')=t.transfer_id||'.revocation'
 AND NOT EXISTS(SELECT 1 FROM cn_withdrawal w WHERE w.transfer_id=t.transfer_id AND w.registration_id=t.registration_id))
 BEGIN SELECT RAISE(ABORT,'continuation_withdrawal_required'); END;
