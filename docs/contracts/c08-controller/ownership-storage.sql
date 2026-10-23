-- 不可变占用归属附属候选；由生成器与178表组合，不是产品迁移。
CREATE TABLE ow_source(
 source_id TEXT PRIMARY KEY, scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
 source_revision TEXT NOT NULL CHECK(source_revision='00000000000000000001'),
 source_digest TEXT NOT NULL CHECK(length(source_digest)=71 AND substr(source_digest,1,7)='sha256:' AND substr(source_digest,8) NOT GLOB '*[^0-9a-f]*'),
 hold_id TEXT NOT NULL UNIQUE REFERENCES cr_hold(hold_id) DEFERRABLE INITIALLY DEFERRED,
 hold_digest TEXT NOT NULL, command_id TEXT NOT NULL REFERENCES ce_command(command_id), device_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('ordinary','cancel')),
 attempt_id TEXT REFERENCES ce_attempt(attempt_id), cancellation_id TEXT REFERENCES cv_cancel(cancellation_id),
 execution_id TEXT REFERENCES cg_plan(execution_id) DEFERRABLE INITIALLY DEFERRED,
 command_key_id TEXT REFERENCES ca_request_key(key_id), cancel_key_id TEXT REFERENCES cv_cancel_key(key_id),
 namespace_id TEXT NOT NULL REFERENCES ca_namespace(namespace_id), request_digest TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('manual','automation')), principal_kind TEXT NOT NULL CHECK(principal_kind IN ('human','service')),
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, principal_id TEXT NOT NULL,
 authority_state_id TEXT NOT NULL REFERENCES ct_state(change_id), control_epoch TEXT NOT NULL,
 effective_version TEXT NOT NULL CHECK(length(effective_version)=20 AND effective_version NOT GLOB '*[^0-9]*'),
 clock_domain TEXT NOT NULL, descriptor TEXT NOT NULL,
 sampled_tick TEXT NOT NULL CHECK(length(sampled_tick)=20 AND sampled_tick NOT GLOB '*[^0-9]*'),
 acquired_tick TEXT NOT NULL CHECK(length(acquired_tick)=20 AND acquired_tick NOT GLOB '*[^0-9]*'),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick)=20 AND expires_tick NOT GLOB '*[^0-9]*'),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 CHECK(sampled_tick<=acquired_tick AND acquired_tick<expires_tick),
 CHECK((origin='manual' AND principal_kind='human') OR (origin='automation' AND principal_kind='service')),
 CHECK((kind='ordinary' AND attempt_id IS NOT NULL AND command_key_id IS NOT NULL AND cancellation_id IS NULL AND execution_id IS NULL AND cancel_key_id IS NULL)
 OR (kind='cancel' AND attempt_id IS NULL AND command_key_id IS NULL AND cancellation_id IS NOT NULL AND execution_id IS NOT NULL AND cancel_key_id IS NOT NULL)),
 FOREIGN KEY(source_id) REFERENCES ow_ownership(source_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ow_ownership(
 ownership_id TEXT PRIMARY KEY, revision TEXT NOT NULL CHECK(revision='00000000000000000001'),
 hold_id TEXT NOT NULL UNIQUE REFERENCES cr_hold(hold_id), source_id TEXT NOT NULL UNIQUE REFERENCES ow_source(source_id),
 ownership_digest TEXT NOT NULL CHECK(length(ownership_digest)=71 AND substr(ownership_digest,1,7)='sha256:' AND substr(ownership_digest,8) NOT GLOB '*[^0-9a-f]*'),
 ownership_body BLOB NOT NULL CHECK(length(ownership_body)>0),
 UNIQUE(ownership_id,revision,ownership_digest),
 FOREIGN KEY(ownership_id) REFERENCES ow_commit(ownership_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ow_commit(
 ownership_id TEXT PRIMARY KEY REFERENCES ow_ownership(ownership_id),
 hold_id TEXT NOT NULL UNIQUE REFERENCES cr_hold_commit(hold_id),
 committed_tick TEXT NOT NULL CHECK(length(committed_tick)=20 AND committed_tick NOT GLOB '*[^0-9]*'),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0), outbox_id TEXT NOT NULL UNIQUE,
 outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
CREATE TABLE ow_revocation(
 source_id TEXT PRIMARY KEY REFERENCES ow_source(source_id),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0), reason_body BLOB NOT NULL CHECK(length(reason_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0), outbox_id TEXT NOT NULL UNIQUE, outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0)
) STRICT;
-- 真实请求来源；取消不从父命令namespace或origin推导Requester。
CREATE VIEW ow_request_source AS SELECT s.* FROM ow_source s JOIN ce_command c USING(command_id)
 JOIN ca_namespace n ON n.namespace_id=s.namespace_id
 WHERE s.scope_id=n.scope_id AND s.device_id=c.device_id
 AND s.issuer_id=n.issuer_id AND s.issuer_epoch=n.issuer_epoch AND s.principal_id=n.principal_id
 AND ((s.kind='ordinary' AND s.origin=c.origin AND EXISTS(
 SELECT 1 FROM ce_attempt a JOIN ca_command_initial i USING(command_id) JOIN ca_request_key k ON k.key_id=i.key_id
 WHERE a.attempt_id=s.attempt_id AND a.command_id=s.command_id AND k.key_id=s.command_key_id
 AND k.namespace_id=s.namespace_id AND k.request_digest=s.request_digest AND k.device_id=s.device_id))
 OR (s.kind='cancel' AND EXISTS(SELECT 1 FROM cv_cancel x JOIN cv_cancel_key k USING(key_id) JOIN cg_plan p USING(cancellation_id)
 WHERE x.cancellation_id=s.cancellation_id AND x.command_id=s.command_id AND p.execution_id=s.execution_id
 AND k.key_id=s.cancel_key_id AND k.namespace_id=s.namespace_id AND k.request_digest=s.request_digest)));
CREATE VIEW ow_current_source AS SELECT s.* FROM ow_request_source s
 JOIN go_authority a ON a.change_id=s.authority_state_id AND a.device_id=s.device_id
 JOIN ct_current_state c ON c.device_id=s.device_id JOIN ct_change t ON t.change_id=c.change_id
 WHERE a.pending_operation_id IS NULL AND c.pending_operation_id IS NULL
 AND s.control_epoch=a.control_epoch AND s.effective_version=a.effective_version
 AND s.clock_domain=t.clock_domain AND s.descriptor=t.descriptor
 AND NOT EXISTS(SELECT 1 FROM ow_revocation r WHERE r.source_id=s.source_id)
 AND ((s.origin='manual' AND a.mode='manual' AND s.issuer_id=a.holder_issuer AND s.issuer_epoch=a.holder_epoch AND s.principal_id=a.holder_id)
 OR (s.origin='automation' AND a.mode='automatic' AND a.holder_id IS NULL));
CREATE TRIGGER ow_seal BEFORE INSERT ON ow_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ow_ownership o JOIN ow_current_source s USING(source_id)
 JOIN cr_hold h ON h.hold_id=o.hold_id JOIN cr_hold_commit k ON k.hold_id=h.hold_id
 JOIN ct_current_state c ON c.device_id=s.device_id JOIN ct_change t ON t.change_id=c.change_id
 WHERE o.ownership_id=NEW.ownership_id AND o.hold_id=NEW.hold_id AND s.hold_id=o.hold_id
 AND h.hold_digest=s.hold_digest AND h.command_id=s.command_id AND h.attempt_id IS s.attempt_id AND h.cancel_execution_id IS s.execution_id
 AND t.now_tick<=NEW.committed_tick AND s.acquired_tick<=NEW.committed_tick AND NEW.committed_tick<s.expires_tick)
 THEN RAISE(ABORT,'ownership_source_or_authority') END;
END;
CREATE VIEW ow_record AS SELECT o.ownership_id,o.revision,o.ownership_digest,o.ownership_body,s.* FROM ow_ownership o
 JOIN ow_source s USING(source_id) JOIN ow_commit k ON k.ownership_id=o.ownership_id;
-- 仅当前主体来源资格；不含实时tick、完整Guard、GateAccess或资源可发送性。
CREATE VIEW ow_current_owner AS SELECT o.ownership_id,o.revision,o.ownership_digest,s.* FROM ow_ownership o
 JOIN ow_current_source s USING(source_id) JOIN ow_commit k ON k.ownership_id=o.ownership_id;
CREATE TRIGGER ow_snapshot_source BEFORE INSERT ON go_snapshot_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_hold h LEFT JOIN ow_record o ON o.ownership_id=h.owner_ref
 WHERE h.snapshot_id=NEW.snapshot_id AND (o.ownership_id IS NULL OR h.owner_revision!=o.revision
 OR h.owner_digest!=o.ownership_digest OR h.hold_id!=o.hold_id OR h.authority_state_id!=o.authority_state_id))
 THEN RAISE(ABORT,'ownership_snapshot_binding') END;
END;
-- 词表映射，不宣称自行证明异常原因或采样新鲜度。
CREATE VIEW ow_risk_projection AS SELECT h.snapshot_id,h.hold_id,h.owner_ref,h.owner_revision,h.owner_digest,h.authority_state_id,
 CASE h.classification WHEN 'active' THEN 'active' WHEN 'unknown' THEN 'unknown'
 WHEN 'failed_unresolved' THEN 'unresolved' WHEN 'orphaned' THEN 'stale' WHEN 'proof_revoked' THEN 'stale' END AS classification
 FROM go_hold h;
CREATE TRIGGER ow_revoke_hazard AFTER INSERT ON ow_revocation BEGIN
 INSERT INTO go_hazard(device_id,revision,source_kind,source_id,recovery_id)
 SELECT s.device_id,@OWNERSHIP_HAZARD_SUCCESSOR@,'ownership',NEW.source_id,NULL FROM ow_source s WHERE s.source_id=NEW.source_id;
END;
CREATE TRIGGER ow_hazard_source BEFORE INSERT ON go_hazard WHEN NEW.source_kind='ownership'
 AND NOT EXISTS(SELECT 1 FROM ow_revocation r JOIN ow_source s USING(source_id) WHERE r.source_id=NEW.source_id AND s.device_id=NEW.device_id)
 BEGIN SELECT RAISE(ABORT,'hazard_source'); END;
