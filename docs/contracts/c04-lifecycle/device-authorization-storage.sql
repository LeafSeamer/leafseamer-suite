-- 离线候选子域；外部身份、控制权及关闭原件仍由受信适配器提供。
CREATE TABLE da_state (
 state_id TEXT PRIMARY KEY NOT NULL, authority_id TEXT NOT NULL, database_id TEXT NOT NULL, device_id TEXT NOT NULL,
 revision TEXT NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*'),
 parent_id TEXT REFERENCES da_state(state_id), status TEXT NOT NULL CHECK(status IN ('protected','policy_selected')),
 recovery_id TEXT, commit_id TEXT NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216),
 UNIQUE(authority_id,database_id,device_id,revision), UNIQUE(state_id,authority_id,database_id,device_id),
 CHECK((status='protected' AND recovery_id IS NULL) OR (status='policy_selected' AND recovery_id IS NOT NULL)),
 FOREIGN KEY(recovery_id,state_id) REFERENCES da_consumption(authorization_id,state_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(commit_id) REFERENCES da_commit(commit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE da_revalidation (
 authorization_id TEXT PRIMARY KEY NOT NULL, protected_state_id TEXT NOT NULL REFERENCES da_state(state_id),
 digest TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216)
) STRICT;
CREATE TABLE da_consumption (
 authorization_id TEXT PRIMARY KEY NOT NULL REFERENCES da_revalidation(authorization_id),
 state_id TEXT NOT NULL UNIQUE REFERENCES da_state(state_id), UNIQUE(authorization_id,state_id)
) STRICT;
CREATE TABLE da_evidence (
 evidence_id TEXT PRIMARY KEY NOT NULL, state_id TEXT NOT NULL REFERENCES da_state(state_id),
 commit_id TEXT NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216),
 UNIQUE(evidence_id,state_id), FOREIGN KEY(commit_id) REFERENCES da_commit(commit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE da_head (
 authority_id TEXT NOT NULL,database_id TEXT NOT NULL,device_id TEXT NOT NULL,state_id TEXT NOT NULL,evidence_id TEXT,
 generation TEXT NOT NULL CHECK(length(generation)=20 AND generation NOT GLOB '*[^0-9]*'),commit_id TEXT NOT NULL,
 PRIMARY KEY(authority_id,database_id,device_id),
 FOREIGN KEY(state_id,authority_id,database_id,device_id) REFERENCES da_state(state_id,authority_id,database_id,device_id),
 FOREIGN KEY(evidence_id,state_id) REFERENCES da_evidence(evidence_id,state_id),
 FOREIGN KEY(commit_id,state_id,generation) REFERENCES da_commit(commit_id,state_id,generation) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE da_commit (
 commit_id TEXT PRIMARY KEY NOT NULL,parent_id TEXT REFERENCES da_commit(commit_id),kind TEXT NOT NULL CHECK(kind IN ('initialize','revalidate','protect','select')),
 state_id TEXT NOT NULL REFERENCES da_state(state_id),evidence_id TEXT REFERENCES da_evidence(evidence_id),generation TEXT NOT NULL,
 digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216), UNIQUE(commit_id,state_id,generation),
 FOREIGN KEY(commit_id) REFERENCES da_seal(commit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE da_audit (commit_id TEXT PRIMARY KEY NOT NULL REFERENCES da_commit(commit_id),body BLOB NOT NULL) STRICT;
CREATE TABLE da_outbox (commit_id TEXT PRIMARY KEY NOT NULL REFERENCES da_commit(commit_id),body BLOB NOT NULL) STRICT;
CREATE TABLE da_seal (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES da_commit(commit_id),body BLOB NOT NULL,
 FOREIGN KEY(commit_id) REFERENCES da_audit(commit_id),FOREIGN KEY(commit_id) REFERENCES da_outbox(commit_id)
) STRICT;
CREATE TRIGGER da_head_initial BEFORE INSERT ON da_head WHEN (SELECT status FROM da_state WHERE state_id=NEW.state_id)!='protected'
 OR (SELECT revision FROM da_state WHERE state_id=NEW.state_id)!='00000000000000000001' OR NEW.evidence_id IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'initial authorization must be protected'); END;
CREATE TRIGGER da_head_step BEFORE UPDATE ON da_head WHEN NEW.authority_id!=OLD.authority_id OR NEW.database_id!=OLD.database_id OR NEW.device_id!=OLD.device_id
 OR NEW.generation<=OLD.generation OR (NEW.state_id=OLD.state_id AND (NEW.evidence_id IS NULL OR NEW.evidence_id IS OLD.evidence_id))
 OR (NEW.state_id!=OLD.state_id AND ((SELECT parent_id FROM da_state WHERE state_id=NEW.state_id) IS NOT OLD.state_id OR NEW.evidence_id IS NOT NULL))
 OR (NEW.evidence_id IS NOT NULL AND (SELECT status FROM da_state WHERE state_id=NEW.state_id)!='policy_selected')
 BEGIN SELECT RAISE(ABORT,'invalid authorization head step'); END;
CREATE TRIGGER da_head_no_delete BEFORE DELETE ON da_head BEGIN SELECT RAISE(ABORT,'authorization head retained'); END;
CREATE TRIGGER da_state_no_update BEFORE UPDATE ON da_state BEGIN SELECT RAISE(ABORT,'immutable state'); END;
CREATE TRIGGER da_state_no_delete BEFORE DELETE ON da_state BEGIN SELECT RAISE(ABORT,'immutable state'); END;
CREATE TRIGGER da_revalidation_no_update BEFORE UPDATE ON da_revalidation BEGIN SELECT RAISE(ABORT,'immutable revalidation'); END;
CREATE TRIGGER da_revalidation_no_delete BEFORE DELETE ON da_revalidation BEGIN SELECT RAISE(ABORT,'immutable revalidation'); END;
CREATE TRIGGER da_consumption_no_update BEFORE UPDATE ON da_consumption BEGIN SELECT RAISE(ABORT,'immutable consumption'); END;
CREATE TRIGGER da_consumption_no_delete BEFORE DELETE ON da_consumption BEGIN SELECT RAISE(ABORT,'immutable consumption'); END;
CREATE TRIGGER da_evidence_no_update BEFORE UPDATE ON da_evidence BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
CREATE TRIGGER da_evidence_no_delete BEFORE DELETE ON da_evidence BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
CREATE TRIGGER da_commit_no_update BEFORE UPDATE ON da_commit BEGIN SELECT RAISE(ABORT,'immutable commit'); END;
CREATE TRIGGER da_commit_no_delete BEFORE DELETE ON da_commit BEGIN SELECT RAISE(ABORT,'immutable commit'); END;
CREATE TRIGGER da_audit_no_update BEFORE UPDATE ON da_audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
CREATE TRIGGER da_audit_no_delete BEFORE DELETE ON da_audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
CREATE TRIGGER da_outbox_no_update BEFORE UPDATE ON da_outbox BEGIN SELECT RAISE(ABORT,'immutable outbox'); END;
CREATE TRIGGER da_outbox_no_delete BEFORE DELETE ON da_outbox BEGIN SELECT RAISE(ABORT,'immutable outbox'); END;
CREATE TRIGGER da_seal_no_update BEFORE UPDATE ON da_seal BEGIN SELECT RAISE(ABORT,'immutable seal'); END;
CREATE TRIGGER da_seal_no_delete BEFORE DELETE ON da_seal BEGIN SELECT RAISE(ABORT,'immutable seal'); END;
