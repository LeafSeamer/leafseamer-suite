-- RUN证据到同一资源验证权威的来源关系；不得单独加载。
CREATE TABLE rr_manifest(
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_validation(validation_id),
 source_count INTEGER NOT NULL CHECK(source_count BETWEEN 0 AND 256),
 manifest_digest TEXT NOT NULL,manifest_body BLOB NOT NULL CHECK(length(manifest_body)>0),
 FOREIGN KEY(validation_id) REFERENCES rr_manifest_commit(validation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE rr_source(
 validation_id TEXT NOT NULL REFERENCES rr_manifest(validation_id),
 kind TEXT NOT NULL CHECK(kind IN ('run_ack','run_application')),
 source_id TEXT NOT NULL,fence_id TEXT NOT NULL REFERENCES ce_cut_commit(fence_id),
 source_body BLOB NOT NULL CHECK(length(source_body)>0),
 PRIMARY KEY(validation_id,kind,source_id)
) STRICT;
CREATE TABLE rr_manifest_commit(
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES rr_manifest(validation_id),
 manifest_digest TEXT NOT NULL,provider_ref TEXT NOT NULL,
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW rr_valid_source AS SELECT s.* FROM rr_source s JOIN cr_validation v USING(validation_id)
 JOIN ce_selector f USING(fence_id)
 WHERE (v.command_id IS NULL OR EXISTS(SELECT 1 FROM ce_run_command c WHERE c.command_id=v.command_id
 AND (c.origin_authority,c.origin_database,c.run_id)=(f.origin_authority,f.origin_database,f.run_id) AND c.generation<=f.generation))
 AND ((s.kind='run_ack' AND EXISTS(SELECT 1 FROM ce_barrier_ack a JOIN ce_barrier_attempt b USING(barrier_id)
 JOIN ce_result_binding r USING(barrier_id) JOIN ce_target_result t ON (t.fence_id,t.exit_id)=(r.fence_id,r.exit_id)
 JOIN ce_exit e ON e.exit_id=b.exit_id WHERE a.barrier_id=s.source_id AND b.fence_id=s.fence_id
 AND r.kind='worker_ack' AND t.evidence_kind='worker_ack' AND e.device_id=v.device_id AND a.ack_body=s.source_body
 AND NOT EXISTS(SELECT 1 FROM ra_barrier_revocation x WHERE x.barrier_id=a.barrier_id)))
 OR(s.kind='run_application' AND EXISTS(SELECT 1 FROM pd_valid_application a JOIN ce_target t USING(fence_id)
 JOIN ce_exit e USING(exit_id) WHERE a.fence_id=s.fence_id AND a.receipt_id=s.source_id
 AND a.receipt_body=s.source_body AND e.device_id=v.device_id)));
CREATE TRIGGER rr_source_frozen BEFORE INSERT ON rr_source WHEN EXISTS(SELECT 1 FROM rr_manifest_commit WHERE validation_id=NEW.validation_id)
 BEGIN SELECT RAISE(ABORT,'run_resource_manifest_frozen'); END;
CREATE TRIGGER rr_manifest_seal BEFORE INSERT ON rr_manifest_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rr_manifest m JOIN cr_validation v USING(validation_id)
 WHERE m.validation_id=NEW.validation_id AND m.manifest_digest=NEW.manifest_digest AND v.provider_ref=NEW.provider_ref
 AND v.receipt_body=NEW.receipt_body AND m.source_count=(SELECT count(*) FROM rr_source s WHERE s.validation_id=m.validation_id))
 OR EXISTS(SELECT kind,source_id FROM rr_source WHERE validation_id=NEW.validation_id
 EXCEPT SELECT kind,source_id FROM rr_valid_source WHERE validation_id=NEW.validation_id)
 OR EXISTS(SELECT 1 FROM cr_validation_revocation WHERE validation_id=NEW.validation_id)
 THEN RAISE(ABORT,'run_resource_source_invalid') END;
END;
CREATE VIEW rr_affected_validation AS SELECT s.validation_id,s.kind,s.source_id,s.fence_id FROM rr_source s
 JOIN rr_manifest_commit k USING(validation_id);
CREATE VIEW cr_valid_validation AS SELECT v.* FROM rr_base_valid_validation v JOIN rr_manifest_commit k USING(validation_id)
 WHERE NOT EXISTS(SELECT kind,source_id FROM rr_source WHERE validation_id=v.validation_id
 EXCEPT SELECT kind,source_id FROM rr_valid_source WHERE validation_id=v.validation_id);
CREATE TRIGGER rr_ack_revoke AFTER INSERT ON ra_barrier_revocation BEGIN
 INSERT INTO cr_validation_revocation SELECT DISTINCT s.validation_id,NEW.reason_body,NEW.audit_body
 FROM rr_affected_validation s WHERE s.kind='run_ack' AND s.source_id=NEW.barrier_id
 AND NOT EXISTS(SELECT 1 FROM cr_validation_revocation x WHERE x.validation_id=s.validation_id);
END;
CREATE TRIGGER rr_application_revoke AFTER INSERT ON ra_status_event WHEN NEW.revision=2 BEGIN
 INSERT INTO cr_validation_revocation SELECT DISTINCT s.validation_id,
 CAST(json_object('kind','run_application_invalidated','fence_id',NEW.fence_id,'status_revision','2','cause_kind',NEW.cause_kind,'cause_id',NEW.cause_id) AS BLOB),
 CAST(json_object('kind','run_application_dependency_revoked','validation_id',s.validation_id,'fence_id',NEW.fence_id,'status_revision','2') AS BLOB)
 FROM rr_affected_validation s JOIN ce_application a USING(fence_id)
 WHERE s.kind='run_application' AND s.fence_id=NEW.fence_id AND s.source_id=a.receipt_id
 AND NOT EXISTS(SELECT 1 FROM cr_validation_revocation x WHERE x.validation_id=s.validation_id);
END;
-- 监督退役证明撤回后，不得让旧物理退出行继续省略关闭目标或充当恢复证据。
CREATE VIEW rr_valid_retirement AS SELECT e.* FROM ce_retirement e WHERE NOT EXISTS(
 SELECT 1 FROM cu_revocation r WHERE r.kind='retirement' AND r.object_id=e.exit_id);
DROP VIEW ro_valid_recovery_target;
CREATE VIEW ro_valid_recovery_target AS SELECT r.* FROM ro_recovery_target r WHERE
 (r.retirement_exit_id IS NOT NULL AND EXISTS(SELECT 1 FROM rr_valid_retirement e WHERE e.exit_id=r.retirement_exit_id))
 OR EXISTS(SELECT 1 FROM ro_valid_ack a WHERE a.ack_id=r.ack_id AND a.release_id=r.release_id AND a.exit_id=r.exit_id);
DROP VIEW ro_pending;
CREATE VIEW ro_pending AS SELECT t.*,i.device_id FROM ro_target t JOIN ro_incident i USING(release_id)
 WHERE EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id)
 AND NOT EXISTS(SELECT 1 FROM rr_valid_retirement r WHERE r.exit_id=t.exit_id)
 AND NOT EXISTS(SELECT 1 FROM ro_valid_ack a WHERE a.release_id=t.release_id AND a.exit_id=t.exit_id
 AND NOT EXISTS(SELECT 1 FROM ro_recovery_target used JOIN cr_recovery_commit k USING(recovery_id) WHERE used.ack_id=a.ack_id));
DROP TRIGGER ro_capture;
CREATE TRIGGER ro_capture AFTER INSERT ON cr_release_invalidation BEGIN
 INSERT INTO ro_incident SELECT NEW.release_id,c.device_id,
 (SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)
 FROM cr_release r JOIN ce_command c USING(command_id) WHERE r.release_id=NEW.release_id;
 INSERT INTO ro_target(release_id,exit_id) SELECT i.release_id,e.exit_id FROM ce_exit e JOIN ro_incident i USING(device_id)
 WHERE i.device_id=(SELECT device_id FROM ro_incident WHERE release_id=NEW.release_id)
 AND NOT EXISTS(SELECT 1 FROM ro_target t WHERE t.release_id=i.release_id AND t.exit_id=e.exit_id);
END;
DROP TRIGGER ro_revoke_capture;
CREATE TRIGGER ro_revoke_capture AFTER INSERT ON cr_validation_revocation BEGIN
 INSERT INTO ro_target(release_id,exit_id) SELECT i.release_id,e.exit_id FROM ro_incident i JOIN ce_exit e USING(device_id)
 WHERE EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id)
 AND NOT EXISTS(SELECT 1 FROM ro_target t WHERE t.release_id=i.release_id AND t.exit_id=e.exit_id);
END;
CREATE TRIGGER rr_retirement_capture AFTER INSERT ON cu_revocation WHEN NEW.kind='retirement' BEGIN
 INSERT INTO ro_target(release_id,exit_id) SELECT i.release_id,e.exit_id FROM ro_incident i JOIN ce_exit e USING(device_id)
 WHERE EXISTS(SELECT 1 FROM cr_device_protection p WHERE p.device_id=i.device_id)
 AND NOT EXISTS(SELECT 1 FROM ro_target t WHERE t.release_id=i.release_id AND t.exit_id=e.exit_id);
END;
