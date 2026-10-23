-- 限定取消范围附属设计：原件真实性与完整授权仍由可信提供者外验。
CREATE TABLE gs_policy(
 policy_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES cg_plan_commit(execution_id),
 policy_ref_body BLOB NOT NULL CHECK(length(policy_ref_body)>0),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 FOREIGN KEY(policy_id) REFERENCES gs_policy_commit(policy_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE gs_parent_class(
 policy_id TEXT NOT NULL REFERENCES gs_policy(policy_id),classification TEXT NOT NULL CHECK(classification IN ('active','unknown','unresolved')),
 PRIMARY KEY(policy_id,classification)
) STRICT;
CREATE TABLE gs_policy_commit(policy_id TEXT PRIMARY KEY REFERENCES gs_policy(policy_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)) STRICT;
CREATE TRIGGER gs_policy_seal BEFORE INSERT ON gs_policy_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gs_policy p JOIN cg_plan g USING(execution_id)
 WHERE p.policy_id=NEW.policy_id AND p.policy_ref_body=g.policy_ref_body) THEN RAISE(ABORT,'scope_policy_binding') END;
END;
CREATE TRIGGER gs_policy_members BEFORE INSERT ON gs_parent_class WHEN EXISTS(SELECT 1 FROM gs_policy_commit WHERE policy_id=NEW.policy_id)
 BEGIN SELECT RAISE(ABORT,'scope_policy_sealed'); END;
CREATE TABLE gs_assessment(
 assessment_id TEXT PRIMARY KEY,revision TEXT NOT NULL CHECK(revision='00000000000000000001'),
 assessment_digest TEXT NOT NULL CHECK(length(assessment_digest)=71 AND substr(assessment_digest,1,7)='sha256:' AND substr(assessment_digest,8) NOT GLOB '*[^0-9a-f]*'),
 snapshot_id TEXT NOT NULL UNIQUE REFERENCES go_snapshot_commit(snapshot_id),policy_id TEXT NOT NULL REFERENCES gs_policy_commit(policy_id),
 ownership_id TEXT NOT NULL REFERENCES ow_commit(ownership_id),
 resource_safety_id TEXT NOT NULL CHECK(length(resource_safety_id)>0),resource_safety_revision TEXT NOT NULL CHECK(length(resource_safety_revision)=20 AND resource_safety_revision NOT GLOB '*[^0-9]*'),
 resource_safety_digest TEXT NOT NULL CHECK(length(resource_safety_digest)=71 AND substr(resource_safety_digest,1,7)='sha256:' AND substr(resource_safety_digest,8) NOT GLOB '*[^0-9a-f]*'),
 gate_safety_id TEXT NOT NULL CHECK(length(gate_safety_id)>0),gate_safety_revision TEXT NOT NULL CHECK(length(gate_safety_revision)=20 AND gate_safety_revision NOT GLOB '*[^0-9]*'),
 gate_safety_digest TEXT NOT NULL CHECK(length(gate_safety_digest)=71 AND substr(gate_safety_digest,1,7)='sha256:' AND substr(gate_safety_digest,8) NOT GLOB '*[^0-9a-f]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),body BLOB NOT NULL CHECK(length(body)>0),
 UNIQUE(assessment_id,revision,assessment_digest),
 FOREIGN KEY(assessment_id) REFERENCES gs_assessment_commit(assessment_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE gs_assessment_commit(assessment_id TEXT PRIMARY KEY REFERENCES gs_assessment(assessment_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)) STRICT;
-- 不借用普通go_valid_snapshot：父unknown可共存，自身取消hold必须当前active。
CREATE VIEW gs_current_assessment AS SELECT a.*,s.device_id,s.exit_id,s.authority_state_id,s.control_state_id,
 s.safety_revision,s.authorization_ref,s.run_snapshot_ref,s.command_snapshot_ref,s.time_snapshot_ref,s.sampled_tick,s.expires_tick,
 p.execution_id,p.expires_tick AS policy_expires_tick,g.cancellation_id,g.ordinary_closure_id,o.command_id,o.hold_id
 FROM gs_assessment a JOIN gs_assessment_commit ak USING(assessment_id) JOIN gs_policy p USING(policy_id)
 JOIN gs_policy_commit pk USING(policy_id) JOIN cg_plan g USING(execution_id)
 JOIN go_current_snapshot s USING(snapshot_id) JOIN go_authority au ON au.change_id=s.authority_state_id AND au.device_id=s.device_id
 JOIN ct_current_state c ON c.device_id=s.device_id JOIN ct_change t ON t.change_id=c.change_id
 JOIN ce_exit e ON e.exit_id=s.exit_id AND e.device_id=s.device_id
 JOIN ow_current_owner o ON o.ownership_id=a.ownership_id AND o.execution_id=g.execution_id AND o.hold_id=g.protected_hold_id
 JOIN cv_cancel_current v ON v.cancellation_id=g.cancellation_id
 JOIN cc_valid_closure cl ON cl.closure_id=g.ordinary_closure_id JOIN cc_cut cut ON cut.cut_id=cl.cut_id
 WHERE c.pending_operation_id IS NULL AND au.pending_operation_id IS NULL AND v.state='requested'
 AND o.kind='cancel' AND o.device_id=s.device_id AND cut.stage='ordinary' AND cut.cancellation_id=g.cancellation_id
 AND e.clock_domain_id=t.clock_domain AND e.descriptor_digest=t.descriptor
 AND NOT EXISTS(SELECT 1 FROM ce_retirement WHERE exit_id=e.exit_id)
 AND NOT EXISTS(SELECT 1 FROM cr_device_protection WHERE device_id=s.device_id)
 AND NOT EXISTS(SELECT 1 FROM cg_stopped WHERE execution_id=g.execution_id)
 AND NOT EXISTS(SELECT 1 FROM cc_cut WHERE cancellation_id=g.cancellation_id AND stage='all')
 AND NOT EXISTS(SELECT 1 FROM gs_revocation r WHERE (r.kind='policy' AND r.object_id=a.policy_id) OR (r.kind='assessment' AND r.object_id=a.assessment_id))
 AND s.safety_revision=coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=s.device_id),'00000000000000000000')
 AND (SELECT count(*) FROM go_hold WHERE snapshot_id=s.snapshot_id) BETWEEN 1 AND 256
 AND EXISTS(SELECT 1 FROM go_hold h WHERE h.snapshot_id=s.snapshot_id AND h.hold_id=o.hold_id AND h.classification='active' AND h.owner_ref=a.ownership_id)
 AND NOT EXISTS(SELECT hold_id FROM cr_risk_hold WHERE device_id=s.device_id EXCEPT SELECT hold_id FROM go_hold WHERE snapshot_id=s.snapshot_id)
 AND NOT EXISTS(SELECT hold_id FROM go_hold WHERE snapshot_id=s.snapshot_id EXCEPT SELECT hold_id FROM cr_risk_hold WHERE device_id=s.device_id)
 AND NOT EXISTS(SELECT 1 FROM ow_risk_projection h JOIN ow_record r ON r.ownership_id=h.owner_ref
 LEFT JOIN cm_latest m ON m.command_id=r.command_id WHERE h.snapshot_id=s.snapshot_id AND h.hold_id!=o.hold_id AND
 (r.kind!='ordinary' OR r.command_id!=o.command_id OR EXISTS(SELECT 1 FROM ow_revocation WHERE source_id=r.source_id)
 OR m.command_id IS NULL OR h.classification!=CASE WHEN m.outcome='unknown' THEN 'unknown' WHEN m.resource_status='unresolved' THEN 'unresolved' ELSE 'active' END
 OR NOT EXISTS(SELECT 1 FROM gs_parent_class k WHERE k.policy_id=p.policy_id AND k.classification=h.classification)));
CREATE TRIGGER gs_assessment_seal AFTER INSERT ON gs_assessment_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gs_current_assessment WHERE assessment_id=NEW.assessment_id) THEN RAISE(ABORT,'scope_assessment_invalid') END;
END;
CREATE TABLE gs_access(
 access_id TEXT PRIMARY KEY,revision TEXT NOT NULL CHECK(revision='00000000000000000001'),
 access_digest TEXT NOT NULL CHECK(length(access_digest)=71 AND substr(access_digest,1,7)='sha256:' AND substr(access_digest,8) NOT GLOB '*[^0-9a-f]*'),
 plan_id TEXT NOT NULL UNIQUE REFERENCES go_plan(plan_id),initial_assessment_id TEXT NOT NULL REFERENCES gs_assessment_commit(assessment_id),
 body BLOB NOT NULL CHECK(length(body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(access_id,revision,access_digest)
) STRICT;
-- 当前评估可更新，但初始原件的撤回、两独立安全Ref与Scope必须一直匹配。
CREATE VIEW gs_access_basis AS SELECT x.*,a.device_id,a.exit_id,a.authority_state_id,a.safety_revision,a.control_state_id,
 a.assessment_id AS current_assessment_id,a.sampled_tick,a.expires_tick AS assessment_expires_tick,a.policy_expires_tick,
 a.authorization_ref,a.run_snapshot_ref,a.command_snapshot_ref,a.time_snapshot_ref
 FROM gs_access x JOIN go_plan p USING(plan_id) JOIN gs_assessment original ON original.assessment_id=x.initial_assessment_id
 JOIN go_snapshot os ON os.snapshot_id=original.snapshot_id
 JOIN gs_current_assessment a ON a.policy_id=original.policy_id AND a.ownership_id=original.ownership_id
 AND a.device_id=os.device_id AND a.exit_id=os.exit_id AND a.authority_state_id=os.authority_state_id
 AND a.safety_revision=os.safety_revision AND a.authorization_ref=os.authorization_ref
 AND a.run_snapshot_ref=os.run_snapshot_ref AND a.command_snapshot_ref=os.command_snapshot_ref AND a.time_snapshot_ref=os.time_snapshot_ref
 AND a.resource_safety_id=original.resource_safety_id AND a.resource_safety_revision=original.resource_safety_revision AND a.resource_safety_digest=original.resource_safety_digest
 AND a.gate_safety_id=original.gate_safety_id AND a.gate_safety_revision=original.gate_safety_revision AND a.gate_safety_digest=original.gate_safety_digest
 WHERE p.basis_kind='scope' AND p.scope_assessment_id=x.initial_assessment_id AND p.snapshot_id=original.snapshot_id
 AND os.sampled_tick<=p.selected_tick AND p.selected_tick<os.expires_tick AND p.expires_tick<=a.policy_expires_tick
 AND NOT EXISTS(SELECT 1 FROM gs_revocation r WHERE (r.kind='access' AND r.object_id=x.access_id) OR (r.kind='assessment' AND r.object_id=x.initial_assessment_id));
CREATE VIEW gs_scope_plan AS SELECT p.*,a.device_id,a.exit_id,a.authority_state_id,a.safety_revision FROM go_plan p
 JOIN go_plan_commit k USING(plan_id) JOIN gs_access_basis a USING(plan_id)
 JOIN ct_current_state c ON c.change_id=p.before_control_id AND c.change_id=a.control_state_id
 JOIN go_current_gate g ON g.gate_id=p.before_gate_id AND g.exit_id=a.exit_id
 WHERE g.phase='fenced' AND c.pending_operation_id IS NULL AND c.gate_state!='ready'
 AND a.current_assessment_id=p.scope_assessment_id AND p.expires_tick<=g.lease_until_tick
 AND ((g.renewal_id IS NOT NULL AND EXISTS(SELECT 1 FROM gf_valid_fence f WHERE f.request_id=g.renewal_id)) OR
 (g.control_barrier_id IS NOT NULL AND EXISTS(SELECT 1 FROM cu_valid_effective e WHERE e.control_state_id=c.change_id)
 AND NOT EXISTS(SELECT 1 FROM go_close WHERE device_id=a.device_id)));
CREATE VIEW go_valid_plan AS SELECT * FROM go_ordinary_plan UNION ALL SELECT * FROM gs_scope_plan;
CREATE TRIGGER gs_dispatch_time BEFORE INSERT ON go_dispatch WHEN EXISTS(SELECT 1 FROM go_plan WHERE plan_id=NEW.plan_id AND basis_kind='scope') BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gs_access_basis WHERE plan_id=NEW.plan_id AND NEW.reserved_tick<assessment_expires_tick)
 THEN RAISE(ABORT,'scope_dispatch_expired') END;
END;
CREATE TRIGGER gs_access_seal AFTER INSERT ON go_plan_commit WHEN EXISTS(SELECT 1 FROM go_plan WHERE plan_id=NEW.plan_id AND basis_kind='scope') BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM gs_access WHERE plan_id=NEW.plan_id)!=1 THEN RAISE(ABORT,'scope_access_required') END;
END;
CREATE TRIGGER gs_access_closed BEFORE INSERT ON gs_access WHEN EXISTS(SELECT 1 FROM go_plan_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'scope_access_sealed'); END;
CREATE TRIGGER gs_evidence_guard BEFORE INSERT ON go_evidence BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_dispatch d JOIN go_plan p USING(plan_id) WHERE d.dispatch_id=NEW.dispatch_id AND
 ((p.basis_kind!='scope' AND NEW.scope_access_id IS NULL AND NEW.scope_access_revision IS NULL AND NEW.scope_access_digest IS NULL) OR
 (p.basis_kind='scope' AND EXISTS(SELECT 1 FROM gs_access a WHERE a.plan_id=p.plan_id AND a.access_id=NEW.scope_access_id
 AND a.revision=NEW.scope_access_revision AND a.access_digest=NEW.scope_access_digest)))) THEN RAISE(ABORT,'scope_ack_binding') END;
END;
CREATE TABLE gs_scope_commit(
 commit_id TEXT PRIMARY KEY,access_id TEXT NOT NULL UNIQUE REFERENCES gs_access(access_id),evidence_id TEXT NOT NULL UNIQUE REFERENCES go_evidence(evidence_id),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_state(change_id),after_gate_id TEXT NOT NULL UNIQUE REFERENCES go_gate(gate_id) DEFERRABLE INITIALLY DEFERRED,
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 commit_digest TEXT NOT NULL CHECK(length(commit_digest)>0),body BLOB NOT NULL CHECK(length(body)>0),
 FOREIGN KEY(change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER gs_commit_pair BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM gs_scope_commit WHERE change_id=NEW.change_id)!=(SELECT kind='scope_commit' FROM ct_change WHERE change_id=NEW.change_id)
 THEN RAISE(ABORT,'scope_commit_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gs_scope_commit k WHERE k.change_id=NEW.change_id AND NOT EXISTS(
 SELECT 1 FROM gs_access_basis a JOIN go_plan p USING(plan_id) JOIN go_plan_commit pk USING(plan_id)
 JOIN ct_current_state old ON old.change_id=p.before_control_id JOIN ct_change c ON c.change_id=k.change_id JOIN ct_state n ON n.change_id=c.change_id
 JOIN go_evidence e ON e.evidence_id=k.evidence_id JOIN go_dispatch d ON d.dispatch_id=e.dispatch_id
 JOIN go_gate b ON b.gate_id=p.before_gate_id JOIN go_current_gate g ON g.gate_id=k.after_gate_id
 WHERE a.access_id=k.access_id AND a.current_assessment_id=p.scope_assessment_id AND a.control_state_id=old.change_id
 AND e.scope_access_id=a.access_id AND d.plan_id=p.plan_id AND g.previous_id=b.gate_id AND g.phase='scoped' AND g.scope_commit_id=k.commit_id
 AND g.exit_id=a.exit_id AND c.device_id=a.device_id AND n.record_digest!=old.record_digest AND n.gate_state='protected'
 AND e.received_tick<=k.committed_tick AND k.committed_tick=c.now_tick AND c.now_tick<p.expires_tick AND c.now_tick<a.assessment_expires_tick
 AND p.expires_tick<=g.lease_until_tick AND NOT EXISTS(SELECT 1 FROM go_revocation r WHERE r.kind='open_ack' AND r.object_id=e.evidence_id)
 AND ((g.renewal_id IS NOT NULL AND EXISTS(SELECT 1 FROM gf_valid_fence f WHERE f.request_id=g.renewal_id)) OR
 (g.control_barrier_id IS NOT NULL AND EXISTS(SELECT 1 FROM cu_valid_effective f WHERE f.control_state_id=old.change_id)
 AND NOT EXISTS(SELECT 1 FROM go_close WHERE device_id=a.device_id))))) THEN RAISE(ABORT,'scope_commit_binding') END;
END;
CREATE VIEW gs_scope_candidate AS SELECT k.*,a.current_assessment_id,p.expires_tick,a.assessment_expires_tick,a.device_id,a.exit_id
 FROM gs_scope_commit k JOIN ct_commit ck USING(change_id) JOIN gs_access_basis a USING(access_id) JOIN go_plan p USING(plan_id)
 JOIN ct_current_state c ON c.device_id=a.device_id JOIN go_current_gate g ON g.gate_id=k.after_gate_id AND g.scope_commit_id=k.commit_id
 WHERE c.gate_state='protected' AND c.pending_operation_id IS NULL
 AND NOT EXISTS(SELECT 1 FROM go_revocation r WHERE r.kind='open_ack' AND r.object_id=k.evidence_id)
 AND ((g.renewal_id IS NOT NULL AND EXISTS(SELECT 1 FROM gf_valid_fence f WHERE f.request_id=g.renewal_id)) OR
 (g.control_barrier_id IS NOT NULL AND EXISTS(SELECT 1 FROM cu_valid_effective f WHERE f.control_state_id=a.authority_state_id)
 AND NOT EXISTS(SELECT 1 FROM go_close WHERE device_id=a.device_id)));
-- 本视图不含实时now，也不替代完整Guard和AdmissionSeal。
CREATE TABLE gs_revocation(kind TEXT NOT NULL CHECK(kind IN ('policy','assessment','access')),object_id TEXT NOT NULL,
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),PRIMARY KEY(kind,object_id)) STRICT;
CREATE VIEW gs_revocation_device AS SELECT r.kind,r.object_id,s.device_id FROM gs_revocation r JOIN gs_assessment a
 ON (r.kind='assessment' AND r.object_id=a.assessment_id) OR (r.kind='policy' AND r.object_id=a.policy_id)
 JOIN go_snapshot s USING(snapshot_id)
 UNION SELECT r.kind,r.object_id,s.device_id FROM gs_revocation r JOIN gs_access x ON r.kind='access' AND r.object_id=x.access_id
 JOIN gs_assessment a ON a.assessment_id=x.initial_assessment_id JOIN go_snapshot s USING(snapshot_id)
 UNION SELECT r.kind,r.object_id,c.device_id FROM gs_revocation r JOIN gs_policy p ON r.kind='policy' AND r.object_id=p.policy_id
 JOIN cg_plan g USING(execution_id) JOIN cv_cancel x USING(cancellation_id) JOIN ce_command c ON c.command_id=x.command_id;
CREATE TRIGGER gs_revocation_guard AFTER INSERT ON gs_revocation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gs_revocation_device WHERE kind=NEW.kind AND object_id=NEW.object_id) THEN RAISE(ABORT,'scope_revocation_source') END;
 INSERT INTO go_hazard(device_id,revision,source_kind,source_id)
 SELECT d.device_id,@GS_SUCCESSOR@,'scope',NEW.kind||':'||NEW.object_id FROM gs_revocation_device d WHERE d.kind=NEW.kind AND d.object_id=NEW.object_id;
END;
CREATE TRIGGER gs_hazard_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='scope' AND NOT EXISTS(
 SELECT 1 FROM gs_revocation_device WHERE kind||':'||object_id=NEW.source_id AND device_id=NEW.device_id)
 BEGIN SELECT RAISE(ABORT,'hazard_source'); END;
