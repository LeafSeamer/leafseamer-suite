-- 最终封存物理候选；来源真实性/JCS仍须本地writer核验，四个临时发送阻断保持。
CREATE TABLE fa_seal(
 transaction_id TEXT PRIMARY KEY NOT NULL, seal_id TEXT NOT NULL UNIQUE,
 permit_id TEXT NOT NULL UNIQUE, issued_revision TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('ordinary','cancel')),
 command_id TEXT NOT NULL, state_revision TEXT NOT NULL,
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),hold_id TEXT NOT NULL REFERENCES cr_hold_commit(hold_id) DEFERRABLE INITIALLY DEFERRED,
 ownership_id TEXT NOT NULL REFERENCES ow_commit(ownership_id) DEFERRABLE INITIALLY DEFERRED,
 before_snapshot_id TEXT NOT NULL REFERENCES go_snapshot_commit(snapshot_id),
 after_snapshot_id TEXT NOT NULL REFERENCES go_snapshot_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED,
 ordinary_id TEXT, cancel_id TEXT,
 selected_tick TEXT NOT NULL, sealed_tick TEXT NOT NULL, not_before_tick TEXT NOT NULL, before_tick TEXT NOT NULL,
 seal_digest TEXT NOT NULL, seal_body BLOB NOT NULL CHECK(json_valid(seal_body) AND length(seal_body)<=1048576),
 CHECK(length(issued_revision)=20 AND issued_revision NOT GLOB '*[^0-9]*' AND issued_revision>'00000000000000000000'),
 CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 CHECK(length(sealed_tick)=20 AND sealed_tick NOT GLOB '*[^0-9]*'),
 CHECK(length(not_before_tick)=20 AND not_before_tick NOT GLOB '*[^0-9]*'),
 CHECK(length(before_tick)=20 AND before_tick NOT GLOB '*[^0-9]*'),
 CHECK(selected_tick<=sealed_tick AND sealed_tick<before_tick AND not_before_tick<before_tick),
 CHECK((kind='ordinary' AND ordinary_id IS permit_id AND cancel_id IS NULL) OR (kind='cancel' AND cancel_id IS permit_id AND ordinary_id IS NULL)),
 UNIQUE(permit_id,issued_revision,kind),UNIQUE(seal_id,permit_id),
 FOREIGN KEY(command_id,state_revision) REFERENCES cm_revision(command_id,revision),
 FOREIGN KEY(permit_id,issued_revision,kind) REFERENCES ci_issue(permit_id,issued_revision,kind) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(ordinary_id) REFERENCES ce_transmission_commit(permit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cancel_id) REFERENCES ci_cancel_commit(permit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(seal_id) REFERENCES fa_commit(seal_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE fa_input(
 seal_id TEXT NOT NULL REFERENCES fa_seal(seal_id), role TEXT NOT NULL CHECK(role IN ('origin','capability','encoding','authorization','control','gate_commit','gate_access','ownership','permit_authority','guard','budget','time','resource_before','resource_after','resource_safety','gate_safety','run_deny','command_deny','ordinary_closure','protection_assessment','primitive_dependency')),
 projection_id TEXT NOT NULL,projection_revision TEXT NOT NULL,projection_digest TEXT NOT NULL,
 source_id TEXT NOT NULL,source_revision TEXT NOT NULL,source_digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(json_valid(body) AND length(body)<=16777216),
 PRIMARY KEY(seal_id,role),UNIQUE(seal_id,projection_id)
) STRICT;
CREATE TABLE fa_commit(
 seal_id TEXT PRIMARY KEY NOT NULL,permit_id TEXT NOT NULL UNIQUE,
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(json_valid(audit_body)),outbox_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(json_valid(outbox_body)),
 FOREIGN KEY(seal_id,permit_id) REFERENCES fa_seal(seal_id,permit_id)
) STRICT;
-- 故意不FK至fa_seal：rolled_back/unknown可发生在没有持久seal时；从不充当许可。
CREATE TABLE fa_observation(
 observation_id TEXT PRIMARY KEY NOT NULL,transaction_id TEXT NOT NULL,seal_id TEXT NOT NULL,permit_id TEXT NOT NULL,
 seal_digest TEXT NOT NULL,outcome TEXT NOT NULL CHECK(outcome IN ('committed','rolled_back','unknown')),
 observed_tick TEXT NOT NULL CHECK(length(observed_tick)=20 AND observed_tick NOT GLOB '*[^0-9]*'),
 candidate_body BLOB NOT NULL CHECK(json_valid(candidate_body) AND length(candidate_body)<=1048576),
 observation_body BLOB NOT NULL CHECK(json_valid(observation_body) AND length(observation_body)<=1048576)
) STRICT;
CREATE INDEX fa_observation_transaction ON fa_observation(transaction_id);
CREATE INDEX fa_observation_permit ON fa_observation(permit_id);
CREATE INDEX fa_observation_seal ON fa_observation(seal_id);
CREATE TRIGGER fa_seal_insert BEFORE INSERT ON fa_seal BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_observation WHERE transaction_id=NEW.transaction_id OR permit_id=NEW.permit_id OR seal_id=NEW.seal_id)
 THEN RAISE(ABORT,'observed_transaction_not_reissuable') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controller_scope c JOIN cm_revision r ON r.command_id=NEW.command_id AND r.revision=NEW.state_revision
 WHERE json_extract(NEW.seal_body,'$.binding.scope.authority_service_id')=c.authority_service_id
 AND json_extract(NEW.seal_body,'$.binding.scope.database_instance_id')=c.database_instance_id
 AND json_extract(NEW.seal_body,'$.transaction_id')=NEW.transaction_id AND json_extract(NEW.seal_body,'$.seal_id')=NEW.seal_id
 AND json_extract(NEW.seal_body,'$.permit_id')=NEW.permit_id AND json_extract(NEW.seal_body,'$.seal_digest')=NEW.seal_digest
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.issued_revision'),-20)=NEW.issued_revision
 AND json_extract(NEW.seal_body,'$.identity.kind')=NEW.kind AND json_extract(NEW.seal_body,'$.identity.command_ref.id')=NEW.command_id
 AND json_extract(NEW.seal_body,'$.command_state_ref.id')=NEW.command_id
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.command_state_ref.revision'),-20)=NEW.state_revision
 AND json_extract(NEW.seal_body,'$.command_state_ref.digest')=r.state_digest
 AND json_extract(NEW.seal_body,'$.binding.writer_exit_id')=NEW.exit_id AND json_extract(NEW.seal_body,'$.hold_ref.id')=NEW.hold_id
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.selected_tick_ns'),-20)=NEW.selected_tick
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.sealed_tick_ns'),-20)=NEW.sealed_tick
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.send_window.not_before_tick_ns'),-20)=NEW.not_before_tick
 AND substr('00000000000000000000'||json_extract(NEW.seal_body,'$.send_window.before_tick_ns'),-20)=NEW.before_tick)
 THEN RAISE(ABORT,'final_seal_columns') END;
END;
CREATE TRIGGER fa_input_insert BEFORE INSERT ON fa_input BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_commit WHERE seal_id=NEW.seal_id) THEN RAISE(ABORT,'final_inputs_frozen') END;
 SELECT CASE WHEN NEW.role IN ('ordinary_closure','protection_assessment','primitive_dependency') AND EXISTS(SELECT 1 FROM fa_seal WHERE seal_id=NEW.seal_id AND kind='ordinary') THEN RAISE(ABORT,'final_role_kind') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal s WHERE s.seal_id=NEW.seal_id
 AND json_type(s.seal_body,'$.inputs.'||NEW.role)='object'
 AND json_extract(s.seal_body,'$.inputs.'||NEW.role||'.id')=NEW.projection_id
 AND json_extract(s.seal_body,'$.inputs.'||NEW.role||'.revision')=NEW.projection_revision
 AND json_extract(s.seal_body,'$.inputs.'||NEW.role||'.digest')=NEW.projection_digest
 AND json_extract(NEW.body,'$.role')=NEW.role AND json_extract(NEW.body,'$.transaction_id')=s.transaction_id
 AND json_extract(NEW.body,'$.ref.id')=NEW.projection_id AND json_extract(NEW.body,'$.ref.revision')=NEW.projection_revision
 AND json_extract(NEW.body,'$.ref.digest')=NEW.projection_digest
 AND json_extract(NEW.body,'$.source_ref.id')=NEW.source_id AND json_extract(NEW.body,'$.source_ref.revision')=NEW.source_revision
 AND json_extract(NEW.body,'$.source_ref.digest')=NEW.source_digest
 AND json(json_extract(NEW.body,'$.scope'))=json(json_extract(s.seal_body,'$.binding.scope'))
 AND json(json_extract(NEW.body,'$.body.binding'))=json(json_extract(s.seal_body,'$.binding'))
 AND json(json_extract(NEW.body,'$.body.identity'))=json(json_extract(s.seal_body,'$.identity')))
 THEN RAISE(ABORT,'final_input_binding') END;
END;
CREATE TRIGGER fa_commit_insert BEFORE INSERT ON fa_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal WHERE seal_id=NEW.seal_id AND permit_id=NEW.permit_id AND sealed_tick<=NEW.committed_tick AND NEW.committed_tick<before_tick)
 THEN RAISE(ABORT,'final_commit_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_seal s WHERE s.seal_id=NEW.seal_id AND
 ((SELECT count(*) FROM fa_input WHERE seal_id=s.seal_id)!=CASE s.kind WHEN 'ordinary' THEN 18 ELSE 21 END
 OR (SELECT count(*) FROM json_each(s.seal_body,'$.inputs') WHERE type='object')!=CASE s.kind WHEN 'ordinary' THEN 18 ELSE 21 END
 OR EXISTS(SELECT key FROM json_each(s.seal_body,'$.inputs') WHERE type='object' EXCEPT SELECT role FROM fa_input WHERE seal_id=s.seal_id)
 OR EXISTS(SELECT role FROM fa_input WHERE seal_id=s.seal_id EXCEPT SELECT key FROM json_each(s.seal_body,'$.inputs') WHERE type='object')))
 THEN RAISE(ABORT,'final_input_set') END;
 SELECT CASE WHEN (SELECT coalesce(sum(length(body)),0) FROM fa_input WHERE seal_id=NEW.seal_id)>16777216 THEN RAISE(ABORT,'final_bundle_capacity') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal s JOIN fa_input o ON o.seal_id=s.seal_id AND o.role='ownership'
 JOIN fa_input b ON b.seal_id=s.seal_id AND b.role='resource_before' JOIN fa_input a ON a.seal_id=s.seal_id AND a.role='resource_after'
 WHERE s.seal_id=NEW.seal_id AND o.source_id=s.ownership_id AND b.source_id=s.before_snapshot_id AND a.source_id=s.after_snapshot_id)
 THEN RAISE(ABORT,'final_storage_sources') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal s JOIN ci_issue i USING(permit_id,issued_revision,kind)
 WHERE s.seal_id=NEW.seal_id AND ((s.kind='ordinary' AND EXISTS(SELECT 1 FROM ce_transmission_commit WHERE permit_id=s.permit_id))
 OR (s.kind='cancel' AND EXISTS(SELECT 1 FROM ci_cancel_commit WHERE permit_id=s.permit_id))))
 THEN RAISE(ABORT,'final_domain_commit') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM fa_seal s JOIN ce_exit e ON e.exit_id=s.exit_id
 JOIN cr_hold h ON h.hold_id=s.hold_id JOIN ow_ownership o ON o.ownership_id=s.ownership_id AND o.hold_id=s.hold_id
 JOIN go_snapshot b ON b.snapshot_id=s.before_snapshot_id JOIN go_snapshot a ON a.snapshot_id=s.after_snapshot_id
 WHERE s.seal_id=NEW.seal_id AND h.command_id=s.command_id AND e.device_id=b.device_id AND e.device_id=a.device_id
 AND e.exit_id=b.exit_id AND e.exit_id=a.exit_id
 AND ((s.kind='ordinary' AND EXISTS(SELECT 1 FROM ce_permit p JOIN ce_attempt t USING(attempt_id)
 WHERE p.permit_id=s.permit_id AND p.exit_id=s.exit_id AND p.issued_revision=s.issued_revision
 AND t.command_id=s.command_id AND h.attempt_id=p.attempt_id
 AND p.attempt_id=json_extract(s.seal_body,'$.identity.attempt_ref.id') AND p.packet_id=json_extract(s.seal_body,'$.packet_ref.packet_id')))
 OR (s.kind='cancel' AND EXISTS(SELECT 1 FROM ci_cancel_transmission p WHERE p.permit_id=s.permit_id
 AND p.exit_id=s.exit_id AND p.issued_revision=s.issued_revision AND p.execution_id=h.cancel_execution_id
 AND p.execution_id=json_extract(s.seal_body,'$.identity.execution_ref.id') AND p.cancellation_id=json_extract(s.seal_body,'$.identity.cancellation_ref.id')
 AND p.packet_id=json_extract(s.seal_body,'$.packet_ref.packet_id')))))
 THEN RAISE(ABORT,'final_domain_anchors') END;
END;
CREATE TRIGGER fa_observation_insert BEFORE INSERT ON fa_observation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controller_scope c WHERE
 json_extract(NEW.candidate_body,'$.binding.scope.authority_service_id')=c.authority_service_id
 AND json_extract(NEW.candidate_body,'$.binding.scope.database_instance_id')=c.database_instance_id
 AND json_extract(NEW.candidate_body,'$.transaction_id')=NEW.transaction_id AND json_extract(NEW.candidate_body,'$.seal_id')=NEW.seal_id
 AND json_extract(NEW.candidate_body,'$.permit_id')=NEW.permit_id AND json_extract(NEW.candidate_body,'$.seal_digest')=NEW.seal_digest
 AND json_extract(NEW.observation_body,'$.observation_id')=NEW.observation_id AND json_extract(NEW.observation_body,'$.transaction_id')=NEW.transaction_id
 AND json_extract(NEW.observation_body,'$.permit_id')=NEW.permit_id AND json_extract(NEW.observation_body,'$.outcome')=NEW.outcome
 AND json_extract(NEW.observation_body,'$.seal_ref.id')=NEW.seal_id AND json_extract(NEW.observation_body,'$.seal_ref.revision')='1'
 AND json_extract(NEW.observation_body,'$.seal_ref.digest')=NEW.seal_digest
 AND substr('00000000000000000000'||json_extract(NEW.observation_body,'$.observed_tick_ns'),-20)=NEW.observed_tick
 AND json(json_extract(NEW.observation_body,'$.scope'))=json(json_extract(NEW.candidate_body,'$.binding.scope')))
 THEN RAISE(ABORT,'final_observation_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_observation WHERE (transaction_id=NEW.transaction_id OR permit_id=NEW.permit_id OR seal_id=NEW.seal_id)
 AND (transaction_id!=NEW.transaction_id OR permit_id!=NEW.permit_id OR seal_id!=NEW.seal_id OR candidate_body!=NEW.candidate_body))
 THEN RAISE(ABORT,'final_observation_identity_conflict') END;
 SELECT CASE WHEN NEW.outcome='committed' AND NOT EXISTS(SELECT 1 FROM fa_seal s JOIN fa_commit k USING(seal_id,permit_id)
 WHERE s.transaction_id=NEW.transaction_id AND s.seal_id=NEW.seal_id AND s.permit_id=NEW.permit_id AND s.seal_body=NEW.candidate_body)
 THEN RAISE(ABORT,'final_commit_unproven') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fa_seal WHERE transaction_id=NEW.transaction_id OR permit_id=NEW.permit_id OR seal_id=NEW.seal_id)
 AND (NEW.outcome='rolled_back' OR NOT EXISTS(SELECT 1 FROM fa_seal WHERE transaction_id=NEW.transaction_id AND seal_id=NEW.seal_id AND permit_id=NEW.permit_id AND seal_body=NEW.candidate_body))
 THEN RAISE(ABORT,'final_observation_contradiction') END;
END;
