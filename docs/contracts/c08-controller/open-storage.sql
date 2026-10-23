-- 开放持久化候选。原件BODY及外部权威由可信提供者验证，不是产品迁移。
CREATE TABLE go_hazard(
 device_id TEXT NOT NULL, revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('release','validation','control','command','report','cancel_report','close','open_revocation','recovery','exit')),
 source_id TEXT NOT NULL,recovery_id TEXT REFERENCES go_recovery_commit(recovery_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((source_kind='recovery' AND recovery_id IS source_id) OR (source_kind!='recovery' AND recovery_id IS NULL)),
 PRIMARY KEY(device_id,revision), UNIQUE(device_id,source_kind,source_id)
) STRICT;
CREATE TRIGGER go_hazard_successor BEFORE INSERT ON go_hazard BEGIN
 SELECT CASE WHEN NEW.revision!=@SUCCESSOR_HAZARD@ OR NEW.revision='00000000000000000000'
 OR EXISTS(SELECT 1 FROM go_hazard WHERE device_id=NEW.device_id AND revision='99999999999999999999')
 THEN RAISE(ABORT,'hazard_successor') END;
END;
CREATE VIEW go_authority AS SELECT s.*,c.device_id FROM ct_state s JOIN ct_change c USING(change_id) JOIN ct_commit k USING(change_id)
 WHERE c.kind NOT IN ('ready','gate_protect') AND NOT EXISTS(SELECT 1 FROM ct_state n JOIN ct_change nc ON nc.change_id=n.change_id JOIN ct_commit nk ON nk.change_id=n.change_id
 WHERE nc.device_id=c.device_id AND nc.kind NOT IN ('ready','gate_protect') AND n.record_revision>s.record_revision);
CREATE TABLE go_snapshot(
 snapshot_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 authority_state_id TEXT NOT NULL REFERENCES ct_state(change_id), control_state_id TEXT NOT NULL REFERENCES ct_state(change_id),
 safety_revision TEXT NOT NULL CHECK(length(safety_revision)=20 AND safety_revision NOT GLOB '*[^0-9]*'),
 authorization_ref TEXT NOT NULL CHECK(length(authorization_ref)>0), resource_ref TEXT NOT NULL CHECK(length(resource_ref)>0),
 run_snapshot_ref TEXT NOT NULL, command_snapshot_ref TEXT NOT NULL, time_snapshot_ref TEXT NOT NULL,
 sampled_tick TEXT NOT NULL CHECK(length(sampled_tick)=20 AND sampled_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)>0),
 evidence_body BLOB NOT NULL CHECK(length(evidence_body)>0), CHECK(sampled_tick<expires_tick),
 FOREIGN KEY(snapshot_id) REFERENCES go_snapshot_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE go_hold(
 snapshot_id TEXT NOT NULL REFERENCES go_snapshot(snapshot_id), hold_id TEXT NOT NULL REFERENCES cr_hold(hold_id),
 authority_state_id TEXT NOT NULL REFERENCES ct_state(change_id), owner_ref TEXT NOT NULL CHECK(length(owner_ref)>0),
 classification TEXT NOT NULL CHECK(classification IN ('active','unknown','failed_unresolved','orphaned','proof_revoked')),
 PRIMARY KEY(snapshot_id,hold_id)
) STRICT;
CREATE TABLE go_snapshot_commit(
 snapshot_id TEXT PRIMARY KEY REFERENCES go_snapshot(snapshot_id), audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW go_current_snapshot AS SELECT s.* FROM go_snapshot s JOIN go_snapshot_commit k USING(snapshot_id)
 WHERE NOT EXISTS(SELECT 1 FROM go_snapshot n JOIN go_snapshot_commit nk ON nk.snapshot_id=n.snapshot_id WHERE n.device_id=s.device_id AND n.sampled_tick>s.sampled_tick);
CREATE VIEW go_valid_snapshot AS SELECT s.* FROM go_current_snapshot s
 JOIN go_authority a ON a.change_id=s.authority_state_id AND a.device_id=s.device_id
 JOIN ce_exit e ON e.exit_id=s.exit_id AND e.device_id=s.device_id
 WHERE a.pending_operation_id IS NULL AND NOT EXISTS(SELECT 1 FROM ce_retirement r WHERE r.exit_id=s.exit_id)
 AND s.safety_revision=coalesce((SELECT max(revision) FROM go_hazard h WHERE h.device_id=s.device_id),'00000000000000000000')
 AND NOT EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=s.device_id)
 AND NOT EXISTS(SELECT hold_id FROM cr_risk_hold h WHERE h.device_id=s.device_id EXCEPT SELECT hold_id FROM go_hold WHERE snapshot_id=s.snapshot_id)
 AND NOT EXISTS(SELECT hold_id FROM go_hold WHERE snapshot_id=s.snapshot_id EXCEPT SELECT hold_id FROM cr_risk_hold h WHERE h.device_id=s.device_id)
 AND NOT EXISTS(SELECT 1 FROM go_hold h JOIN cr_hold r USING(hold_id) LEFT JOIN cm_latest c ON c.command_id=r.command_id
 WHERE h.snapshot_id=s.snapshot_id AND (h.authority_state_id!=s.authority_state_id OR h.classification!='active' OR c.command_id IS NULL OR c.resource_status='unresolved' OR c.outcome='unknown'));
CREATE TRIGGER go_snapshot_seal BEFORE INSERT ON go_snapshot_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_snapshot s JOIN go_authority a ON a.change_id=s.authority_state_id
 JOIN ct_current_state c ON c.change_id=s.control_state_id JOIN ct_change cc ON cc.change_id=c.change_id JOIN ce_exit e ON e.exit_id=s.exit_id
 WHERE s.snapshot_id=NEW.snapshot_id AND s.device_id=a.device_id AND s.device_id=c.device_id AND s.device_id=e.device_id
 AND cc.clock_domain=e.clock_domain_id AND cc.descriptor=e.descriptor_digest AND cc.now_tick<=s.sampled_tick
 AND s.safety_revision=coalesce((SELECT max(revision) FROM go_hazard h WHERE h.device_id=s.device_id),'00000000000000000000')
 AND NOT EXISTS(SELECT 1 FROM go_current_snapshot p WHERE p.device_id=s.device_id AND p.sampled_tick>=s.sampled_tick)) THEN RAISE(ABORT,'open_snapshot_binding') END;
 SELECT CASE WHEN EXISTS(SELECT h.hold_id FROM cr_risk_hold h JOIN go_snapshot s USING(device_id) WHERE s.snapshot_id=NEW.snapshot_id
 EXCEPT SELECT hold_id FROM go_hold WHERE snapshot_id=NEW.snapshot_id)
 OR EXISTS(SELECT hold_id FROM go_hold WHERE snapshot_id=NEW.snapshot_id EXCEPT SELECT h.hold_id FROM cr_risk_hold h JOIN go_snapshot s USING(device_id) WHERE s.snapshot_id=NEW.snapshot_id)
 THEN RAISE(ABORT,'open_hold_set') END;
END;
CREATE TABLE go_gate(
 gate_id TEXT PRIMARY KEY, exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id), previous_id TEXT REFERENCES go_gate(gate_id),
 record_revision TEXT NOT NULL CHECK(length(record_revision)=20 AND record_revision NOT GLOB '*[^0-9]*'),
 gate_revision TEXT NOT NULL CHECK(length(gate_revision)=20 AND gate_revision NOT GLOB '*[^0-9]*'),
 gate_token TEXT NOT NULL CHECK(length(gate_token)>0), barrier_id TEXT NOT NULL REFERENCES cu_ack(barrier_id),
 phase TEXT NOT NULL CHECK(phase IN ('fenced','ready')), ready_id TEXT UNIQUE REFERENCES go_ready(ready_id) DEFERRABLE INITIALLY DEFERRED,
 lease_until_tick TEXT NOT NULL CHECK(length(lease_until_tick)=20 AND lease_until_tick NOT GLOB '*[^0-9]*'),
 record_digest TEXT NOT NULL CHECK(length(record_digest)>0), record_body BLOB NOT NULL CHECK(length(record_body)>0),
 UNIQUE(exit_id,record_revision), CHECK((phase='ready')=(ready_id IS NOT NULL))
) STRICT;
CREATE VIEW go_current_gate AS SELECT g.* FROM go_gate g WHERE NOT EXISTS(SELECT 1 FROM go_gate n WHERE n.exit_id=g.exit_id AND n.record_revision>g.record_revision);
CREATE TRIGGER go_gate_guard BEFORE INSERT ON go_gate BEGIN
 SELECT CASE WHEN NOT ((NEW.previous_id IS NULL AND NEW.record_revision='00000000000000000001' AND NEW.phase='fenced'
 AND NOT EXISTS(SELECT 1 FROM go_gate WHERE exit_id=NEW.exit_id)) OR EXISTS(SELECT 1 FROM go_current_gate p WHERE p.gate_id=NEW.previous_id
 AND p.exit_id=NEW.exit_id AND p.record_revision<'99999999999999999999' AND NEW.record_revision=@SUCCESSOR_GATE@
 AND NEW.record_digest!=p.record_digest AND ((NEW.phase='ready' AND p.phase='fenced' AND NEW.gate_revision=p.gate_revision
 AND NEW.gate_token=p.gate_token AND NEW.barrier_id=p.barrier_id AND NEW.lease_until_tick=p.lease_until_tick)
 OR (NEW.phase='fenced' AND NEW.gate_revision>p.gate_revision AND NEW.gate_token!=p.gate_token)))) THEN RAISE(ABORT,'open_gate_transition') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cu_ack a JOIN cu_delivery d USING(barrier_id) WHERE a.barrier_id=NEW.barrier_id AND d.exit_id=NEW.exit_id
 AND a.gate_revision<=NEW.gate_revision) THEN RAISE(ABORT,'open_gate_barrier') END;
END;
CREATE TABLE go_plan(
 plan_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES go_snapshot_commit(snapshot_id),
 before_gate_id TEXT NOT NULL UNIQUE REFERENCES go_gate(gate_id), before_control_id TEXT NOT NULL REFERENCES ct_state(change_id),
 basis_kind TEXT NOT NULL CHECK(basis_kind IN ('activation','resource_recovery','gate_recovery')),
 activation_id TEXT REFERENCES cu_effective(change_id), resource_recovery_id TEXT REFERENCES cr_recovery_commit(recovery_id),
 gate_recovery_id TEXT UNIQUE REFERENCES go_recovery_commit(recovery_id),
 selected_tick TEXT NOT NULL CHECK(length(selected_tick)=20 AND selected_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 plan_digest TEXT NOT NULL, proposal_digest TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)>0),
 CHECK(selected_tick<expires_tick),
 CHECK((basis_kind='activation' AND activation_id IS NOT NULL AND resource_recovery_id IS NULL AND gate_recovery_id IS NULL)
 OR (basis_kind='resource_recovery' AND activation_id IS NULL AND resource_recovery_id IS NOT NULL AND gate_recovery_id IS NOT NULL)
 OR (basis_kind='gate_recovery' AND activation_id IS NULL AND resource_recovery_id IS NULL AND gate_recovery_id IS NOT NULL)),
 FOREIGN KEY(plan_id) REFERENCES go_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE go_plan_commit(plan_id TEXT PRIMARY KEY REFERENCES go_plan(plan_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)) STRICT;
CREATE VIEW go_valid_plan AS SELECT p.*,s.device_id,s.exit_id,s.authority_state_id,s.safety_revision FROM go_plan p
 JOIN go_plan_commit k USING(plan_id) JOIN go_valid_snapshot s USING(snapshot_id)
 JOIN ct_current_state c ON c.change_id=p.before_control_id AND c.change_id=s.control_state_id
 JOIN go_current_gate g ON g.gate_id=p.before_gate_id AND g.exit_id=s.exit_id
 WHERE c.pending_operation_id IS NULL AND g.phase='fenced' AND c.gate_state!='ready'
 AND s.sampled_tick<=p.selected_tick AND p.expires_tick<=s.expires_tick AND p.expires_tick<=g.lease_until_tick
 AND ((p.basis_kind='activation' AND EXISTS(SELECT 1 FROM cu_valid_effective e WHERE e.change_id=p.activation_id AND e.control_state_id=c.change_id)
  AND NOT EXISTS(SELECT 1 FROM go_close x WHERE x.device_id=s.device_id)) OR
 (p.basis_kind!='activation' AND EXISTS(SELECT 1 FROM go_valid_recovery r WHERE r.recovery_id=p.gate_recovery_id AND r.snapshot_id=p.snapshot_id)
  AND (p.resource_recovery_id IS NULL OR EXISTS(SELECT 1 FROM cr_recovery r JOIN cr_valid_validation v USING(validation_id) WHERE r.recovery_id=p.resource_recovery_id AND r.device_id=s.device_id))));
CREATE TRIGGER go_plan_seal AFTER INSERT ON go_plan_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_valid_plan WHERE plan_id=NEW.plan_id) THEN RAISE(ABORT,'open_plan_invalid') END;
END;
CREATE TABLE go_dispatch(
 dispatch_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL UNIQUE REFERENCES go_plan_commit(plan_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),message_id TEXT NOT NULL,
 outbound_seq TEXT NOT NULL CHECK(length(outbound_seq)=20 AND outbound_seq NOT GLOB '*[^0-9]*'),
 reserved_tick TEXT NOT NULL CHECK(length(reserved_tick)=20 AND reserved_tick NOT GLOB '*[^0-9]*'),
 frame_digest TEXT NOT NULL, frame_body BLOB NOT NULL CHECK(length(frame_body)>0),
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(exit_id,message_id),UNIQUE(exit_id,outbound_seq)
) STRICT;
CREATE TRIGGER go_dispatch_guard BEFORE INSERT ON go_dispatch BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_valid_plan p WHERE p.plan_id=NEW.plan_id AND p.exit_id=NEW.exit_id
 AND p.selected_tick<=NEW.reserved_tick AND NEW.reserved_tick<p.expires_tick) THEN RAISE(ABORT,'open_dispatch_invalid') END;
END;
CREATE TABLE go_evidence(
 evidence_id TEXT PRIMARY KEY,dispatch_id TEXT NOT NULL UNIQUE REFERENCES go_dispatch(dispatch_id),
 exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),message_id TEXT NOT NULL,reply_to TEXT NOT NULL,
 inbound_seq TEXT NOT NULL CHECK(length(inbound_seq)=20 AND inbound_seq NOT GLOB '*[^0-9]*'),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 gate_token TEXT NOT NULL,gate_revision TEXT NOT NULL,
 run_snapshot_ref TEXT NOT NULL,command_snapshot_ref TEXT NOT NULL,time_snapshot_ref TEXT NOT NULL,
 observer_ref TEXT NOT NULL CHECK(length(observer_ref)>0),evidence_digest TEXT NOT NULL,
 frame_body BLOB NOT NULL CHECK(length(frame_body)>0),validation_body BLOB NOT NULL CHECK(length(validation_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),UNIQUE(exit_id,message_id),UNIQUE(exit_id,inbound_seq)
) STRICT;
CREATE TRIGGER go_evidence_guard BEFORE INSERT ON go_evidence BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_dispatch d JOIN go_plan p USING(plan_id) JOIN go_snapshot s USING(snapshot_id)
 JOIN go_gate g ON g.gate_id=p.before_gate_id WHERE d.dispatch_id=NEW.dispatch_id AND d.exit_id=NEW.exit_id
 AND d.message_id=NEW.reply_to AND d.reserved_tick<=NEW.received_tick AND NEW.gate_token=g.gate_token AND NEW.gate_revision=g.gate_revision
 AND NEW.run_snapshot_ref=s.run_snapshot_ref AND NEW.command_snapshot_ref=s.command_snapshot_ref AND NEW.time_snapshot_ref=s.time_snapshot_ref)
 THEN RAISE(ABORT,'open_evidence_binding') END;
END;
CREATE TABLE go_ready(
 ready_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL UNIQUE REFERENCES go_plan_commit(plan_id),
 evidence_id TEXT NOT NULL UNIQUE REFERENCES go_evidence(evidence_id),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_state(change_id),after_gate_id TEXT NOT NULL UNIQUE REFERENCES go_gate(gate_id) DEFERRABLE INITIALLY DEFERRED,
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 ready_digest TEXT NOT NULL,transition_digest TEXT NOT NULL,transition_body BLOB NOT NULL CHECK(length(transition_body)>0),
 FOREIGN KEY(change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER go_ready_pair BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_change p ON p.change_id=c.previous_id
 WHERE c.change_id=NEW.change_id AND c.kind IN ('ready','gate_protect') AND
 (c.clock_domain!=p.clock_domain OR c.descriptor!=p.descriptor OR c.now_tick<p.now_tick)) THEN RAISE(ABORT,'open_clock_order') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND c.kind='gate_protect'
 AND NOT EXISTS(SELECT 1 FROM go_close x WHERE x.protection_change_id=c.change_id AND x.device_id=c.device_id)) THEN RAISE(ABORT,'open_close_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ce_exit e USING(device_id) WHERE c.change_id=NEW.change_id AND c.kind='gate_protect'
 AND (NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=e.exit_id) OR EXISTS(SELECT 1 FROM cu_revocation v WHERE v.kind='retirement' AND v.object_id=e.exit_id))
 AND NOT EXISTS(SELECT 1 FROM go_close x WHERE x.protection_change_id=c.change_id AND x.exit_id=e.exit_id)) THEN RAISE(ABORT,'open_close_target_set') END;
 SELECT CASE WHEN (SELECT count(*) FROM go_ready WHERE change_id=NEW.change_id)!=(SELECT kind='ready' FROM ct_change WHERE change_id=NEW.change_id)
 THEN RAISE(ABORT,'open_ready_required') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_ready r WHERE r.change_id=NEW.change_id AND NOT EXISTS(
 SELECT 1 FROM go_plan p JOIN go_snapshot s USING(snapshot_id) JOIN go_valid_snapshot v USING(snapshot_id)
 JOIN ct_current_state old ON old.change_id=p.before_control_id JOIN ct_change c ON c.change_id=r.change_id
 JOIN ct_state n ON n.change_id=r.change_id JOIN go_evidence e ON e.evidence_id=r.evidence_id JOIN go_dispatch d ON d.dispatch_id=e.dispatch_id
 JOIN go_gate g ON g.gate_id=r.after_gate_id JOIN go_gate b ON b.gate_id=p.before_gate_id
 WHERE p.plan_id=r.plan_id AND d.plan_id=p.plan_id AND s.control_state_id=old.change_id AND g.ready_id=r.ready_id
 AND g.previous_id=b.gate_id AND g.phase='ready' AND g.exit_id=s.exit_id AND c.device_id=s.device_id
 AND n.record_digest!=old.record_digest AND e.received_tick<=r.committed_tick AND r.committed_tick=c.now_tick
 AND c.now_tick<p.expires_tick AND c.now_tick<v.expires_tick
 AND NOT EXISTS(SELECT 1 FROM go_gate z WHERE z.exit_id=g.exit_id AND z.record_revision>g.record_revision)
 AND ((p.basis_kind='activation' AND EXISTS(SELECT 1 FROM cu_valid_effective f WHERE f.change_id=p.activation_id AND f.control_state_id=old.change_id)
  AND NOT EXISTS(SELECT 1 FROM go_close x WHERE x.device_id=s.device_id)) OR
 (p.basis_kind!='activation' AND EXISTS(SELECT 1 FROM go_valid_recovery q WHERE q.recovery_id=p.gate_recovery_id AND q.snapshot_id=p.snapshot_id)))))
 THEN RAISE(ABORT,'open_ready_binding') END;
END;
CREATE VIEW go_ready_candidate AS SELECT r.*,s.device_id,s.exit_id,p.snapshot_id,p.expires_tick FROM go_ready r JOIN ct_commit k USING(change_id)
 JOIN go_plan p USING(plan_id) JOIN go_snapshot original USING(snapshot_id)
 JOIN go_valid_snapshot s ON s.device_id=original.device_id AND s.exit_id=original.exit_id
 AND s.authority_state_id=original.authority_state_id AND s.safety_revision=original.safety_revision
 AND s.authorization_ref=original.authorization_ref AND s.run_snapshot_ref=original.run_snapshot_ref
 AND s.command_snapshot_ref=original.command_snapshot_ref AND s.time_snapshot_ref=original.time_snapshot_ref
 JOIN ct_current_state c ON c.device_id=s.device_id AND c.gate_state='ready' AND c.pending_operation_id IS NULL
 JOIN go_current_gate g ON g.gate_id=r.after_gate_id
 WHERE NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='open_ack' AND v.object_id=r.evidence_id)
 AND NOT EXISTS(SELECT 1 FROM go_latest_close x WHERE x.device_id=s.device_id AND NOT EXISTS(
  SELECT 1 FROM go_recovery_target t JOIN go_recovery_commit rk USING(recovery_id) JOIN go_recovery rc USING(recovery_id)
  WHERE t.close_id=x.close_id AND rc.snapshot_id=original.snapshot_id AND NOT EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=t.ack_id)));
-- 这是未包含当前tick的候选视图；调用者必须重新核期限和完整发送Guard，不是发送许可。
CREATE TABLE go_close(
 close_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'),
 protection_change_id TEXT NOT NULL REFERENCES ct_change(change_id),
 gate_id TEXT REFERENCES go_gate(gate_id),reason_ref TEXT NOT NULL CHECK(length(reason_ref)>0),
 body BLOB NOT NULL CHECK(length(body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),
 UNIQUE(exit_id,revision),UNIQUE(close_id,exit_id),FOREIGN KEY(protection_change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE VIEW go_latest_close AS SELECT x.* FROM go_close x WHERE NOT EXISTS(SELECT 1 FROM go_close n WHERE n.exit_id=x.exit_id AND n.revision>x.revision);
CREATE TRIGGER go_close_binding BEFORE INSERT ON go_close BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ce_exit e JOIN ct_change c ON c.change_id=NEW.protection_change_id
 WHERE e.exit_id=NEW.exit_id AND e.device_id=NEW.device_id AND c.device_id=NEW.device_id AND c.kind='gate_protect'
 AND ((NEW.gate_id IS NULL AND NOT EXISTS(SELECT 1 FROM go_gate g WHERE g.exit_id=NEW.exit_id)) OR
 EXISTS(SELECT 1 FROM go_current_gate g WHERE g.gate_id=NEW.gate_id AND g.exit_id=NEW.exit_id))
 AND NOT EXISTS(SELECT 1 FROM ct_commit WHERE change_id=c.change_id)) OR NEW.revision!=@SUCCESSOR_CLOSE@
 THEN RAISE(ABORT,'open_close_binding') END;
END;
CREATE TABLE go_exit_obligation(
 exit_id TEXT PRIMARY KEY REFERENCES ce_exit(exit_id),close_id TEXT NOT NULL UNIQUE,
 FOREIGN KEY(close_id,exit_id) REFERENCES go_close(close_id,exit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER go_exit_registration AFTER INSERT ON ce_exit
 WHEN EXISTS(SELECT 1 FROM ct_current_state s WHERE s.device_id=NEW.device_id) BEGIN
 INSERT INTO go_exit_obligation VALUES(NEW.exit_id,'registration.'||NEW.exit_id);
END;
CREATE TABLE go_close_ack(
 ack_id TEXT PRIMARY KEY,close_id TEXT NOT NULL UNIQUE REFERENCES go_close(close_id),exit_id TEXT NOT NULL REFERENCES ce_exit(exit_id),
 evidence_digest TEXT NOT NULL,observer_ref TEXT NOT NULL CHECK(length(observer_ref)>0),
 received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 body BLOB NOT NULL CHECK(length(body)>0),validation_body BLOB NOT NULL CHECK(length(validation_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER go_close_ack_binding BEFORE INSERT ON go_close_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_close x JOIN ct_change c ON c.change_id=x.protection_change_id
 WHERE x.close_id=NEW.close_id AND x.exit_id=NEW.exit_id AND c.now_tick<=NEW.received_tick)
 THEN RAISE(ABORT,'open_close_ack_binding') END;
END;
CREATE TABLE go_recovery(
 recovery_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,snapshot_id TEXT NOT NULL UNIQUE REFERENCES go_snapshot_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED,
 now_tick TEXT NOT NULL CHECK(length(now_tick)=20 AND now_tick NOT GLOB '*[^0-9]*'),
 recovery_digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0),provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),
 FOREIGN KEY(recovery_id) REFERENCES go_recovery_commit(recovery_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE go_recovery_target(
 recovery_id TEXT NOT NULL REFERENCES go_recovery(recovery_id),close_id TEXT NOT NULL REFERENCES go_close(close_id),
 ack_id TEXT NOT NULL UNIQUE REFERENCES go_close_ack(ack_id),PRIMARY KEY(recovery_id,close_id)
) STRICT;
CREATE TABLE go_recovery_commit(
 recovery_id TEXT PRIMARY KEY REFERENCES go_recovery(recovery_id),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE VIEW go_valid_recovery AS SELECT r.* FROM go_recovery r JOIN go_recovery_commit k USING(recovery_id)
 JOIN go_valid_snapshot s USING(snapshot_id)
 WHERE NOT EXISTS(SELECT 1 FROM ce_exit e WHERE e.device_id=s.device_id
 AND (NOT EXISTS(SELECT 1 FROM ce_retirement t WHERE t.exit_id=e.exit_id) OR EXISTS(SELECT 1 FROM cu_revocation v WHERE v.kind='retirement' AND v.object_id=e.exit_id))
 AND NOT EXISTS(SELECT 1 FROM go_latest_close x WHERE x.exit_id=e.exit_id))
 AND NOT EXISTS(SELECT close_id FROM go_latest_close x WHERE x.device_id=s.device_id EXCEPT SELECT close_id FROM go_recovery_target WHERE recovery_id=r.recovery_id)
 AND NOT EXISTS(SELECT close_id FROM go_recovery_target WHERE recovery_id=r.recovery_id EXCEPT SELECT close_id FROM go_latest_close x WHERE x.device_id=s.device_id)
 AND NOT EXISTS(SELECT 1 FROM go_recovery_target t JOIN go_close_ack a USING(ack_id) WHERE t.recovery_id=r.recovery_id AND (a.close_id!=t.close_id
 OR EXISTS(SELECT 1 FROM go_revocation v WHERE v.kind='close_ack' AND v.object_id=a.ack_id)));
CREATE TRIGGER go_recovery_seal AFTER INSERT ON go_recovery_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM go_valid_recovery r JOIN go_snapshot s USING(snapshot_id) WHERE r.recovery_id=NEW.recovery_id
 AND s.device_id=r.device_id AND s.sampled_tick<=r.now_tick AND r.now_tick<s.expires_tick
 AND EXISTS(SELECT 1 FROM go_hazard h WHERE h.source_kind='recovery' AND h.recovery_id=r.recovery_id AND h.device_id=s.device_id AND h.revision=s.safety_revision)
 AND EXISTS(SELECT 1 FROM go_recovery_target t WHERE t.recovery_id=r.recovery_id))
 OR EXISTS(SELECT 1 FROM go_recovery_target t JOIN go_close x USING(close_id) JOIN go_close_ack a USING(ack_id)
 JOIN go_recovery r USING(recovery_id) JOIN go_snapshot s USING(snapshot_id) WHERE t.recovery_id=NEW.recovery_id AND (x.device_id!=s.device_id OR a.received_tick>r.now_tick))
 THEN RAISE(ABORT,'open_recovery_incomplete') END;
END;
CREATE TABLE go_revocation(
 kind TEXT NOT NULL CHECK(kind IN ('open_ack','close_ack')),object_id TEXT NOT NULL,
 reason_body BLOB NOT NULL CHECK(length(reason_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0),PRIMARY KEY(kind,object_id)
) STRICT;
CREATE TRIGGER go_revocation_binding BEFORE INSERT ON go_revocation BEGIN
 SELECT CASE WHEN (NEW.kind='open_ack' AND NOT EXISTS(SELECT 1 FROM go_evidence WHERE evidence_id=NEW.object_id))
 OR (NEW.kind='close_ack' AND NOT EXISTS(SELECT 1 FROM go_close_ack WHERE ack_id=NEW.object_id)) THEN RAISE(ABORT,'open_revocation_binding') END;
END;
