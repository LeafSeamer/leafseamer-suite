-- 局部内存设计探针；ID和世代文本为合成夹具，不是生产DDL或认证。
PRAGMA foreign_keys=ON;
CREATE TABLE installation (
 installation_id TEXT PRIMARY KEY NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('active','revoking'))
) STRICT;
CREATE TABLE owner (
 owner_id TEXT PRIMARY KEY NOT NULL,
 installation_id TEXT NOT NULL REFERENCES installation(installation_id),
 kind TEXT NOT NULL CHECK(kind IN ('panel','background')),
 identity_jcs TEXT NOT NULL, selector_digest TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('active','denied')),
 UNIQUE(owner_id,installation_id), UNIQUE(installation_id,kind,identity_jcs)
) STRICT;
CREATE INDEX owner_installation ON owner(installation_id);
CREATE TABLE exit_registration (
 exit_id TEXT PRIMARY KEY NOT NULL, owner_id TEXT NOT NULL, installation_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('local_projection','local_preview','local_queue','device_worker','background_worker')),
 generation_jcs TEXT NOT NULL,
 FOREIGN KEY(owner_id,installation_id) REFERENCES owner(owner_id,installation_id),
 UNIQUE(exit_id,owner_id,installation_id,kind,generation_jcs), UNIQUE(exit_id,owner_id,kind)
) STRICT;
CREATE INDEX exit_owner ON exit_registration(owner_id,installation_id);
CREATE TABLE subscription (
 owner_id TEXT NOT NULL, subscription_id TEXT NOT NULL, exit_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='local_projection'),
 state TEXT NOT NULL CHECK(state IN ('live','closing','closed','gap')),
 sent INTEGER NOT NULL CHECK(sent>=0), acked INTEGER NOT NULL CHECK(acked>=0 AND acked<=sent),
 PRIMARY KEY(owner_id,subscription_id),
 FOREIGN KEY(exit_id,owner_id,kind) REFERENCES exit_registration(exit_id,owner_id,kind)
) STRICT;
CREATE INDEX subscription_owner_state ON subscription(owner_id,state);
CREATE TABLE projection_frame (
 owner_id TEXT NOT NULL, subscription_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence>0),
 frame_digest TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('outstanding','retired')),
 PRIMARY KEY(owner_id,subscription_id,sequence),
 FOREIGN KEY(owner_id,subscription_id) REFERENCES subscription(owner_id,subscription_id)
) STRICT;
CREATE TABLE close_batch (
 operation_id TEXT PRIMARY KEY NOT NULL,
 installation_id TEXT NOT NULL UNIQUE REFERENCES installation(installation_id),
 phase TEXT NOT NULL CHECK(phase IN ('building','frozen','acknowledged')),
 manifest_digest TEXT,
 CHECK((phase='building' AND manifest_digest IS NULL) OR (phase<>'building' AND manifest_digest IS NOT NULL)),
 UNIQUE(operation_id,installation_id)
) STRICT;
CREATE TABLE close_member (
 operation_id TEXT NOT NULL, owner_id TEXT NOT NULL, installation_id TEXT NOT NULL,
 selector_digest TEXT NOT NULL,
 PRIMARY KEY(operation_id,owner_id), UNIQUE(operation_id,owner_id,installation_id),
 FOREIGN KEY(operation_id,installation_id) REFERENCES close_batch(operation_id,installation_id),
 FOREIGN KEY(owner_id,installation_id) REFERENCES owner(owner_id,installation_id)
) STRICT;
CREATE TABLE close_target (
 operation_id TEXT NOT NULL, exit_id TEXT NOT NULL, owner_id TEXT NOT NULL, installation_id TEXT NOT NULL,
 kind TEXT NOT NULL, generation_jcs TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','indeterminate','acknowledged')),
 PRIMARY KEY(operation_id,exit_id),
 UNIQUE(operation_id,exit_id,owner_id,kind,generation_jcs),
 FOREIGN KEY(operation_id,owner_id,installation_id) REFERENCES close_member(operation_id,owner_id,installation_id),
 FOREIGN KEY(exit_id,owner_id,installation_id,kind,generation_jcs)
 REFERENCES exit_registration(exit_id,owner_id,installation_id,kind,generation_jcs)
) STRICT;
CREATE INDEX close_target_pending ON close_target(operation_id,status);
CREATE TABLE close_evidence (
 operation_id TEXT NOT NULL, exit_id TEXT NOT NULL, owner_id TEXT NOT NULL,
 kind TEXT NOT NULL, generation_jcs TEXT NOT NULL,
 evidence_type TEXT NOT NULL CHECK(evidence_type IN ('local_closed','ipc_fence','process_terminated')),
 evidence_ref TEXT NOT NULL, evidence_digest TEXT NOT NULL,
 PRIMARY KEY(operation_id,exit_id),
 CHECK((kind IN ('device_worker','background_worker') AND evidence_type<>'local_closed')
 OR (kind IN ('local_projection','local_preview','local_queue') AND evidence_type<>'ipc_fence')),
 FOREIGN KEY(operation_id,exit_id,owner_id,kind,generation_jcs)
 REFERENCES close_target(operation_id,exit_id,owner_id,kind,generation_jcs)
) STRICT;
CREATE TABLE audit (operation_id TEXT PRIMARY KEY NOT NULL REFERENCES close_batch(operation_id)) STRICT;
CREATE TABLE outbox (operation_id TEXT PRIMARY KEY NOT NULL REFERENCES close_batch(operation_id)) STRICT;

CREATE TRIGGER installation_no_reopen BEFORE UPDATE ON installation
 WHEN OLD.state='revoking' OR NEW.installation_id<>OLD.installation_id
 BEGIN SELECT RAISE(ABORT,'installation_immutable'); END;
CREATE TRIGGER owner_admission BEFORE INSERT ON owner
 WHEN NOT EXISTS(SELECT 1 FROM installation WHERE installation_id=NEW.installation_id AND state='active')
 BEGIN SELECT RAISE(ABORT,'installation_denied'); END;
CREATE TRIGGER owner_binding BEFORE UPDATE OF owner_id,installation_id,kind,identity_jcs,selector_digest ON owner
 BEGIN SELECT RAISE(ABORT,'owner_binding_immutable'); END;
CREATE TRIGGER owner_no_reopen BEFORE UPDATE OF state ON owner
 WHEN OLD.state='denied' AND NEW.state<>'denied'
 BEGIN SELECT RAISE(ABORT,'owner_denied'); END;
CREATE TRIGGER owner_no_delete BEFORE DELETE ON owner BEGIN SELECT RAISE(ABORT,'owner_tombstone'); END;
CREATE TRIGGER exit_admission BEFORE INSERT ON exit_registration
 WHEN NOT EXISTS(SELECT 1 FROM owner o JOIN installation i USING(installation_id)
 WHERE o.owner_id=NEW.owner_id AND o.installation_id=NEW.installation_id AND o.state='active' AND i.state='active')
 BEGIN SELECT RAISE(ABORT,'exit_denied'); END;
CREATE TRIGGER exit_no_update BEFORE UPDATE ON exit_registration BEGIN SELECT RAISE(ABORT,'exit_immutable'); END;
CREATE TRIGGER exit_no_delete BEFORE DELETE ON exit_registration BEGIN SELECT RAISE(ABORT,'exit_tombstone'); END;
CREATE TRIGGER subscription_admission BEFORE INSERT ON subscription
 WHEN NOT EXISTS(SELECT 1 FROM owner o JOIN installation i USING(installation_id)
 WHERE o.owner_id=NEW.owner_id AND o.state='active' AND i.state='active')
 BEGIN SELECT RAISE(ABORT,'subscription_denied'); END;
CREATE TRIGGER subscription_binding BEFORE UPDATE OF owner_id,subscription_id,exit_id,kind ON subscription
 BEGIN SELECT RAISE(ABORT,'subscription_immutable'); END;
CREATE TRIGGER subscription_monotonic BEFORE UPDATE ON subscription
 WHEN NEW.sent<OLD.sent OR NEW.acked<OLD.acked
 OR (OLD.state<>'live' AND (NEW.sent<>OLD.sent OR NEW.acked<>OLD.acked))
 OR (OLD.state IN ('closed','gap'))
 OR (OLD.state='closing' AND NEW.state<>'closed')
 OR (NEW.state<>'live' AND (NEW.sent<>OLD.sent OR NEW.acked<>OLD.acked))
 BEGIN SELECT RAISE(ABORT,'subscription_boundary'); END;
CREATE TRIGGER subscription_no_delete BEFORE DELETE ON subscription BEGIN SELECT RAISE(ABORT,'subscription_tombstone'); END;
CREATE TRIGGER frame_admission BEFORE INSERT ON projection_frame
 WHEN NOT EXISTS(SELECT 1 FROM subscription s JOIN owner o USING(owner_id) JOIN installation i USING(installation_id)
 WHERE s.owner_id=NEW.owner_id AND s.subscription_id=NEW.subscription_id AND s.state='live' AND o.state='active' AND i.state='active')
 BEGIN SELECT RAISE(ABORT,'frame_denied'); END;
CREATE TRIGGER frame_binding BEFORE UPDATE OF owner_id,subscription_id,sequence,frame_digest ON projection_frame
 BEGIN SELECT RAISE(ABORT,'frame_immutable'); END;
CREATE TRIGGER frame_no_reopen BEFORE UPDATE OF state ON projection_frame
 WHEN OLD.state='retired' BEGIN SELECT RAISE(ABORT,'frame_retired'); END;

CREATE TRIGGER member_insert BEFORE INSERT ON close_member
 WHEN (SELECT phase FROM close_batch WHERE operation_id=NEW.operation_id)<>'building'
 BEGIN SELECT RAISE(ABORT,'capture_frozen'); END;
CREATE TRIGGER member_update BEFORE UPDATE ON close_member BEGIN SELECT RAISE(ABORT,'member_immutable'); END;
CREATE TRIGGER member_delete BEFORE DELETE ON close_member
 WHEN (SELECT phase FROM close_batch WHERE operation_id=OLD.operation_id)<>'building'
 BEGIN SELECT RAISE(ABORT,'capture_frozen'); END;
CREATE TRIGGER target_insert BEFORE INSERT ON close_target
 WHEN (SELECT phase FROM close_batch WHERE operation_id=NEW.operation_id)<>'building' OR NEW.status<>'pending'
 BEGIN SELECT RAISE(ABORT,'capture_frozen'); END;
CREATE TRIGGER target_binding BEFORE UPDATE OF operation_id,exit_id,owner_id,installation_id,kind,generation_jcs ON close_target
 BEGIN SELECT RAISE(ABORT,'target_immutable'); END;
CREATE TRIGGER target_delete BEFORE DELETE ON close_target
 WHEN (SELECT phase FROM close_batch WHERE operation_id=OLD.operation_id)<>'building'
 BEGIN SELECT RAISE(ABORT,'capture_frozen'); END;
CREATE TRIGGER target_status BEFORE UPDATE OF status ON close_target
 WHEN OLD.status='acknowledged' OR (OLD.status='indeterminate' AND NEW.status='pending')
 OR (SELECT phase FROM close_batch WHERE operation_id=OLD.operation_id)<>'frozen'
 OR (NEW.status='acknowledged' AND NOT EXISTS(SELECT 1 FROM close_evidence e
 WHERE e.operation_id=NEW.operation_id AND e.exit_id=NEW.exit_id))
 BEGIN SELECT RAISE(ABORT,'evidence_required'); END;
CREATE TRIGGER evidence_insert BEFORE INSERT ON close_evidence
 WHEN (SELECT phase FROM close_batch WHERE operation_id=NEW.operation_id)<>'frozen'
 BEGIN SELECT RAISE(ABORT,'evidence_phase'); END;
CREATE TRIGGER evidence_update BEFORE UPDATE ON close_evidence BEGIN SELECT RAISE(ABORT,'evidence_immutable'); END;
CREATE TRIGGER evidence_delete BEFORE DELETE ON close_evidence BEGIN SELECT RAISE(ABORT,'evidence_immutable'); END;
CREATE TRIGGER batch_insert BEFORE INSERT ON close_batch
 WHEN NEW.phase<>'building' OR (SELECT state FROM installation WHERE installation_id=NEW.installation_id)<>'revoking'
 BEGIN SELECT RAISE(ABORT,'deny_before_capture'); END;
CREATE TRIGGER batch_binding BEFORE UPDATE OF operation_id,installation_id ON close_batch BEGIN SELECT RAISE(ABORT,'batch_immutable'); END;
CREATE TRIGGER batch_digest BEFORE UPDATE OF manifest_digest ON close_batch
 WHEN OLD.phase<>'building' BEGIN SELECT RAISE(ABORT,'manifest_immutable'); END;
CREATE TRIGGER batch_freeze BEFORE UPDATE OF phase ON close_batch
 WHEN OLD.phase='building' AND (
 NEW.phase<>'frozen'
 OR EXISTS(SELECT 1 FROM owner WHERE installation_id=OLD.installation_id AND state<>'denied')
 OR EXISTS(SELECT owner_id,selector_digest FROM owner WHERE installation_id=OLD.installation_id
 EXCEPT SELECT owner_id,selector_digest FROM close_member WHERE operation_id=OLD.operation_id)
 OR EXISTS(SELECT owner_id,selector_digest FROM close_member WHERE operation_id=OLD.operation_id
 EXCEPT SELECT owner_id,selector_digest FROM owner WHERE installation_id=OLD.installation_id)
 OR EXISTS(SELECT exit_id FROM exit_registration WHERE installation_id=OLD.installation_id
 EXCEPT SELECT exit_id FROM close_target WHERE operation_id=OLD.operation_id)
 OR EXISTS(SELECT exit_id FROM close_target WHERE operation_id=OLD.operation_id
 EXCEPT SELECT exit_id FROM exit_registration WHERE installation_id=OLD.installation_id)
 OR EXISTS(SELECT 1 FROM subscription s JOIN owner o USING(owner_id) WHERE o.installation_id=OLD.installation_id AND s.state='live')
 OR NOT EXISTS(SELECT 1 FROM audit WHERE operation_id=OLD.operation_id)
 OR NOT EXISTS(SELECT 1 FROM outbox WHERE operation_id=OLD.operation_id))
 BEGIN SELECT RAISE(ABORT,'incomplete_capture'); END;
CREATE TRIGGER batch_complete BEFORE UPDATE OF phase ON close_batch
 WHEN OLD.phase<>'building' AND (OLD.phase<>'frozen' OR NEW.phase<>'acknowledged'
 OR EXISTS(SELECT 1 FROM close_target WHERE operation_id=OLD.operation_id AND status<>'acknowledged'))
 BEGIN SELECT RAISE(ABORT,'incomplete_evidence'); END;
CREATE TRIGGER batch_delete BEFORE DELETE ON close_batch BEGIN SELECT RAISE(ABORT,'batch_tombstone'); END;
