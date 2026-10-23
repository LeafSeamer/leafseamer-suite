-- 追加于109表来源恢复布局；本轮保留原普通触发准备守卫。
CREATE TABLE rc_limit(singleton INTEGER PRIMARY KEY CHECK(singleton=1),max_transfers INTEGER NOT NULL CHECK(max_transfers BETWEEN 1 AND 65536)) STRICT;
CREATE TABLE rc_request(
 transfer_id TEXT PRIMARY KEY NOT NULL,run_id TEXT NOT NULL REFERENCES run(run_id),generation TEXT NOT NULL,
 operation_id TEXT NOT NULL REFERENCES recovery_operation(operation_id),execution_id TEXT NOT NULL REFERENCES execution(execution_id),
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL,idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL CHECK(length(request_body) BETWEEN 1 AND 262144 AND json_valid(request_body)),
 UNIQUE(run_id,generation),UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(transfer_id) REFERENCES rc_request_commit(transfer_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(transfer_id=json_extract(request_body,'$.transfer_id') AND run_id=json_extract(request_body,'$.run_id') AND generation=json_extract(request_body,'$.generation')),
 CHECK(operation_id=json_extract(request_body,'$.recovery_operation_id') AND execution_id=json_extract(request_body,'$.recovery_execution_id')),
 CHECK(request_epoch=json_extract(request_body,'$.request_epoch') AND idempotency_key=json_extract(request_body,'$.idempotency_key') AND request_digest=json_extract(request_body,'$.request_digest')),
 CHECK(json(actor_body)=json(json_extract(request_body,'$.actor')))
) STRICT;
CREATE TABLE rc_target(
 transfer_id TEXT NOT NULL REFERENCES rc_request(transfer_id),registration_id TEXT NOT NULL REFERENCES p1_preparation(registration_id),
 target_body BLOB NOT NULL CHECK(length(target_body) BETWEEN 1 AND 262144 AND json_valid(target_body)),
 PRIMARY KEY(transfer_id,registration_id)
) STRICT;
CREATE TABLE rc_request_commit(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES rc_request(transfer_id),request_digest TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),outbox_body BLOB NOT NULL CHECK(length(outbox_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE TABLE rc_receipt(
 transfer_id TEXT NOT NULL REFERENCES rc_request_commit(transfer_id),registration_id TEXT NOT NULL,
 receipt_digest TEXT NOT NULL,receipt_body BLOB NOT NULL CHECK(length(receipt_body) BETWEEN 1 AND 16384 AND json_valid(receipt_body)),
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),
 PRIMARY KEY(transfer_id,registration_id),FOREIGN KEY(transfer_id,registration_id) REFERENCES rc_target(transfer_id,registration_id),
 CHECK(receipt_digest=json_extract(receipt_body,'$.receipt_digest'))
) STRICT;
CREATE TABLE rc_adoption(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES rc_request_commit(transfer_id),adoption_id TEXT NOT NULL UNIQUE,adoption_digest TEXT NOT NULL,
 adoption_body BLOB NOT NULL CHECK(length(adoption_body) BETWEEN 1 AND 16384 AND json_valid(adoption_body)),
 release_proof_body BLOB NOT NULL CHECK(length(release_proof_body) BETWEEN 1 AND 16384 AND json_valid(release_proof_body)),
 FOREIGN KEY(transfer_id) REFERENCES rc_adoption_commit(transfer_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(transfer_id=json_extract(adoption_body,'$.transfer_id') AND adoption_id=json_extract(adoption_body,'$.adoption_id') AND adoption_digest=json_extract(adoption_body,'$.adoption_digest'))
) STRICT;
CREATE TABLE rc_adoption_commit(
 transfer_id TEXT PRIMARY KEY NOT NULL REFERENCES rc_adoption(transfer_id),adoption_digest TEXT NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),outbox_body BLOB NOT NULL CHECK(length(outbox_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE TABLE rc_r5_link(
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES transition_commit(commit_id),transfer_id TEXT NOT NULL UNIQUE REFERENCES rc_adoption_commit(transfer_id),
 adoption_digest TEXT NOT NULL
) STRICT;
CREATE VIEW rc_recovery_current AS SELECT q.* FROM rc_request q JOIN run r USING(run_id) JOIN recovery_operation o ON o.operation_id=q.operation_id
 JOIN recovery_lock lk ON lk.operation_id=o.operation_id JOIN activation_slot sl USING(definition_id)
 WHERE r.arm_generation=q.generation AND r.active_execution_id=q.execution_id AND r.lifecycle='running'
 AND o.execution_id=q.execution_id AND o.run_id=q.run_id AND o.state IN ('running','reconciling') AND lk.release_id IS NULL
 AND sl.active_run_id=r.run_id AND NOT EXISTS(SELECT 1 FROM pause_latch l WHERE l.run_id=r.run_id AND l.cleared_start_id IS NULL)
 AND EXISTS(SELECT 1 FROM step_state st WHERE st.execution_id=q.execution_id)
 AND NOT EXISTS(SELECT 1 FROM step_state st WHERE st.execution_id=q.execution_id AND(st.state!='finished' OR st.outcome!='succeeded'))
 AND NOT EXISTS(SELECT 1 FROM p1_dependency dep JOIN ingress_source src USING(source_id) WHERE dep.run_id=r.run_id AND src.state!='synchronized')
 AND NOT EXISTS(SELECT 1 FROM p1_deny den WHERE den.run_id=r.run_id AND substr('00000000000000000000'||q.generation,-20)<=den.generation)
 AND NOT EXISTS(SELECT 1 FROM rc_target t JOIN pq_current p USING(registration_id) WHERE t.transfer_id=q.transfer_id AND p.qualification!='observed_applied');
CREATE TRIGGER rc_request_guard BEFORE INSERT ON rc_request BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_limit WHERE (SELECT count(*) FROM rc_request)<max_transfers) THEN RAISE(ABORT,'continuation_capacity') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM storage_scope s WHERE s.authority_id=json_extract(NEW.request_body,'$.origin_scope.authority_service_id') AND s.database_id=json_extract(NEW.request_body,'$.origin_scope.database_instance_id')) THEN RAISE(ABORT,'continuation_origin') END;
END;
CREATE TRIGGER rc_target_guard BEFORE INSERT ON rc_target BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM rc_request_commit WHERE transfer_id=NEW.transfer_id) THEN RAISE(ABORT,'continuation_sealed') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_request q JOIN p1_preparation p ON p.run_id=q.run_id AND p.generation=q.generation
 JOIN json_each(q.request_body,'$.targets') j WHERE q.transfer_id=NEW.transfer_id AND p.registration_id=NEW.registration_id AND p.mode='recovery'
 AND p.execution_id=q.execution_id AND p.recovery_operation_id=q.operation_id AND p.preparation_id=json_extract(NEW.target_body,'$.preparation_ref.id')
 AND p.controller_authority=json_extract(NEW.target_body,'$.controller_scope.authority_service_id') AND p.controller_database=json_extract(NEW.target_body,'$.controller_scope.database_instance_id')
 AND json(j.value)=json(NEW.target_body)) THEN RAISE(ABORT,'continuation_registration') END;
END;
CREATE TRIGGER rc_request_seal BEFORE INSERT ON rc_request_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_recovery_current q WHERE q.transfer_id=NEW.transfer_id AND q.request_digest=NEW.request_digest
 AND (SELECT count(*) FROM rc_target t WHERE t.transfer_id=q.transfer_id)=json_array_length(q.request_body,'$.targets')
 AND (SELECT count(*) FROM rc_target t WHERE t.transfer_id=q.transfer_id)=(SELECT count(*) FROM p1_preparation p WHERE p.run_id=q.run_id AND p.generation=q.generation)) THEN RAISE(ABORT,'continuation_request_seal') END;
END;
CREATE TRIGGER rc_receipt_guard BEFORE INSERT ON rc_receipt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_request q JOIN rc_target t USING(transfer_id) WHERE q.transfer_id=NEW.transfer_id AND t.registration_id=NEW.registration_id
 AND q.request_digest=json_extract(NEW.receipt_body,'$.request_digest') AND json(json_extract(t.target_body,'$.controller_scope'))=json(json_extract(NEW.receipt_body,'$.controller_scope'))
 AND json(json_extract(t.target_body,'$.preparation_ref'))=json(json_extract(NEW.receipt_body,'$.preparation_ref')))
 THEN RAISE(ABORT,'continuation_receipt') END;
END;
CREATE TRIGGER rc_adoption_seal BEFORE INSERT ON rc_adoption_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rc_adoption a JOIN rc_recovery_current q USING(transfer_id) JOIN run r USING(run_id)
 JOIN activation_slot sl USING(definition_id) JOIN recovery_operation o ON o.operation_id=q.operation_id
 WHERE a.transfer_id=NEW.transfer_id AND a.adoption_digest=NEW.adoption_digest
 AND q.request_digest=json_extract(a.adoption_body,'$.request_digest')
 AND r.revision=json_extract(a.adoption_body,'$.expected_run_revision') AND sl.revision=json_extract(a.adoption_body,'$.expected_slot_revision')
 AND o.revision=json_extract(a.adoption_body,'$.expected_operation_revision')
 AND (SELECT count(*) FROM rc_receipt z WHERE z.transfer_id=q.transfer_id)=json_array_length(q.request_body,'$.targets')
 AND json_array_length(a.adoption_body,'$.receipt_refs')=json_array_length(q.request_body,'$.targets')
 AND NOT EXISTS(SELECT 1 FROM rc_receipt z WHERE z.transfer_id=q.transfer_id AND NOT EXISTS(SELECT 1 FROM json_each(a.adoption_body,'$.receipt_refs') j
 WHERE json_extract(j.value,'$.id')=json_extract(z.receipt_body,'$.receipt_id') AND json_extract(j.value,'$.digest')=z.receipt_digest
 AND json(json_extract(j.value,'$.scope'))=json(json_extract(z.receipt_body,'$.controller_scope'))))) THEN RAISE(ABORT,'continuation_adoption_seal') END;
END;
CREATE TRIGGER rc_r5_guard BEFORE INSERT ON flow_commit_seal WHEN EXISTS(
 SELECT 1 FROM transition_commit c JOIN execution e USING(execution_id) WHERE c.commit_id=NEW.commit_id AND e.origin_kind='recovery') BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM transition_commit c JOIN rc_r5_link l USING(commit_id) JOIN rc_adoption a USING(transfer_id)
 JOIN rc_request q USING(transfer_id) JOIN recovery_lock lk ON lk.operation_id=q.operation_id JOIN external_evidence proof ON proof.evidence_id=lk.release_id
 WHERE c.commit_id=NEW.commit_id AND c.execution_id=q.execution_id AND c.run_id=q.run_id AND l.adoption_digest=a.adoption_digest
 AND proof.body=a.release_proof_body) THEN RAISE(ABORT,'continuation_r5_required') END;
END;
