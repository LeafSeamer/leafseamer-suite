-- Seamer P4独立内存实验布局；sp_plan/target为已核验P1封存计划的导入边界，尚非完整P1实现。
CREATE TABLE sp_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,plan_digest TEXT NOT NULL,
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 65536),
 plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(plan_id) REFERENCES sp_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE sp_target(
 plan_id TEXT NOT NULL REFERENCES sp_plan(plan_id),target_id TEXT NOT NULL,
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,binding_body)
) STRICT;
CREATE TABLE sp_plan_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES sp_plan(plan_id),
 validation_body BLOB NOT NULL CHECK(length(validation_body)>0)
) STRICT;
CREATE TRIGGER sp_target_frozen BEFORE INSERT ON sp_target WHEN EXISTS(SELECT 1 FROM sp_plan_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'protection_plan_frozen'); END;
CREATE TRIGGER sp_plan_seal BEFORE INSERT ON sp_plan_commit BEGIN
 SELECT CASE WHEN (SELECT target_count FROM sp_plan WHERE plan_id=NEW.plan_id)!=(SELECT count(*) FROM sp_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'protection_targets_incomplete') END;
END;
CREATE TABLE sp_observation(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,revision INTEGER NOT NULL CHECK(revision IN (1,2)),
 state TEXT NOT NULL CHECK(state IN ('applied','indeterminate')),
 binding_body BLOB NOT NULL,identity_body BLOB NOT NULL CHECK(length(identity_body)>0),
 observation_digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body)>0),
 PRIMARY KEY(plan_id,target_id,revision),
 CHECK((revision=1 AND state='applied') OR(revision=2 AND state='indeterminate')),
 FOREIGN KEY(plan_id,target_id) REFERENCES sp_target(plan_id,target_id),
 FOREIGN KEY(plan_id,target_id,revision) REFERENCES sp_observation_commit(plan_id,target_id,revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE sp_observation_commit(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,revision INTEGER NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 PRIMARY KEY(plan_id,target_id,revision),
 FOREIGN KEY(plan_id,target_id,revision) REFERENCES sp_observation(plan_id,target_id,revision)
) STRICT;
CREATE TRIGGER sp_observation_guard BEFORE INSERT ON sp_observation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sp_target t JOIN sp_plan_commit k USING(plan_id)
 WHERE t.plan_id=NEW.plan_id AND t.target_id=NEW.target_id AND t.binding_body=NEW.binding_body)
 OR EXISTS(SELECT 1 FROM sp_observation o WHERE o.plan_id=NEW.plan_id AND o.target_id=NEW.target_id AND o.identity_body!=NEW.identity_body)
 THEN RAISE(ABORT,'protection_observation_binding') END;
END;
CREATE VIEW sp_current_observation AS SELECT o.* FROM sp_observation o JOIN sp_observation_commit k USING(plan_id,target_id,revision)
 WHERE o.revision=(SELECT max(n.revision) FROM sp_observation n JOIN sp_observation_commit c USING(plan_id,target_id,revision)
 WHERE n.plan_id=o.plan_id AND n.target_id=o.target_id);
CREATE VIEW sp_observed_summary AS SELECT p.plan_id,
 CASE WHEN EXISTS(SELECT 1 FROM sp_current_observation o WHERE o.plan_id=p.plan_id AND o.state='indeterminate') THEN 'indeterminate'
 WHEN NOT EXISTS(SELECT 1 FROM sp_target t WHERE t.plan_id=p.plan_id AND NOT EXISTS(SELECT 1 FROM sp_current_observation o
 WHERE o.plan_id=t.plan_id AND o.target_id=t.target_id AND o.state='applied')) THEN 'applied' ELSE 'pending' END AS observed_state,
 p.target_count,(SELECT count(*) FROM sp_current_observation o WHERE o.plan_id=p.plan_id) AS observed_targets
 FROM sp_plan p JOIN sp_plan_commit k USING(plan_id);
CREATE TRIGGER sp_plan_u BEFORE UPDATE ON sp_plan BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_plan_d BEFORE DELETE ON sp_plan BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_target_u BEFORE UPDATE ON sp_target BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_target_d BEFORE DELETE ON sp_target BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_plan_commit_u BEFORE UPDATE ON sp_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_plan_commit_d BEFORE DELETE ON sp_plan_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_observation_u BEFORE UPDATE ON sp_observation BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_observation_d BEFORE DELETE ON sp_observation BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_observation_commit_u BEFORE UPDATE ON sp_observation_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
CREATE TRIGGER sp_observation_commit_d BEFORE DELETE ON sp_observation_commit BEGIN SELECT RAISE(ABORT,'immutable_protection_observation'); END;
