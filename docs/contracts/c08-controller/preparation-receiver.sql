-- 独立准备观察库：P1计划导入仍是可信边界，不把观察结果当发送或恢复授权。
CREATE TABLE po_plan(
 plan_id TEXT PRIMARY KEY NOT NULL,plan_digest TEXT NOT NULL,
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 1 AND 65536),
 plan_body BLOB NOT NULL CHECK(length(plan_body)>0),
 FOREIGN KEY(plan_id) REFERENCES po_plan_commit(plan_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE po_target(
 plan_id TEXT NOT NULL REFERENCES po_plan(plan_id),target_id TEXT NOT NULL,
 binding_body BLOB NOT NULL CHECK(length(binding_body) BETWEEN 1 AND 16384),
 PRIMARY KEY(plan_id,target_id),UNIQUE(plan_id,binding_body)
) STRICT;
CREATE TABLE po_plan_commit(
 plan_id TEXT PRIMARY KEY NOT NULL REFERENCES po_plan(plan_id),validation_body BLOB NOT NULL CHECK(length(validation_body)>0)
) STRICT;
CREATE TRIGGER po_target_frozen BEFORE INSERT ON po_target WHEN EXISTS(SELECT 1 FROM po_plan_commit WHERE plan_id=NEW.plan_id)
 BEGIN SELECT RAISE(ABORT,'preparation_plan_frozen'); END;
CREATE TRIGGER po_plan_seal BEFORE INSERT ON po_plan_commit BEGIN
 SELECT CASE WHEN (SELECT target_count FROM po_plan WHERE plan_id=NEW.plan_id)!=(SELECT count(*) FROM po_target WHERE plan_id=NEW.plan_id)
 THEN RAISE(ABORT,'preparation_targets_incomplete') END;
END;
CREATE TABLE po_observation(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,
 preparation_revision TEXT NOT NULL CHECK(preparation_revision IN ('00000000000000000001','00000000000000000002','00000000000000000003','00000000000000000004')),
 protection_revision INTEGER NOT NULL CHECK(protection_revision IN (0,1,2)),
 state TEXT NOT NULL CHECK(state IN ('accepted','applied','rejected','indeterminate','closing','closed')),
 protection_state TEXT NOT NULL CHECK(protection_state IN ('not_applicable','pending','applied','indeterminate')),
 binding_body BLOB NOT NULL,observation_digest TEXT NOT NULL,body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16384),
 PRIMARY KEY(plan_id,target_id,preparation_revision,protection_revision),
 CHECK((state IN ('accepted','applied','rejected','indeterminate') AND protection_state='not_applicable' AND protection_revision=0)
 OR(state='closing' AND protection_state='pending' AND protection_revision=0)
 OR(state='closed' AND ((protection_state='applied' AND protection_revision=1) OR(protection_state='indeterminate' AND protection_revision=2)))),
 FOREIGN KEY(plan_id,target_id) REFERENCES po_target(plan_id,target_id),
 FOREIGN KEY(plan_id,target_id,preparation_revision,protection_revision) REFERENCES po_observation_commit(plan_id,target_id,preparation_revision,protection_revision) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE po_observation_commit(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,preparation_revision TEXT NOT NULL,protection_revision INTEGER NOT NULL,
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 PRIMARY KEY(plan_id,target_id,preparation_revision,protection_revision),
 FOREIGN KEY(plan_id,target_id,preparation_revision,protection_revision) REFERENCES po_observation(plan_id,target_id,preparation_revision,protection_revision)
) STRICT;
CREATE TRIGGER po_observation_guard BEFORE INSERT ON po_observation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM po_target t JOIN po_plan_commit k USING(plan_id)
 WHERE t.plan_id=NEW.plan_id AND t.target_id=NEW.target_id AND t.binding_body=NEW.binding_body)
 THEN RAISE(ABORT,'preparation_observation_binding') END;
END;
CREATE TABLE po_conflict(
 plan_id TEXT NOT NULL,target_id TEXT NOT NULL,observation_digest TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('same_revision_conflict','history_conflict','receipt_conflict','completion_conflict')),
 binding_body BLOB NOT NULL,body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16384),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),outbox_body BLOB NOT NULL CHECK(length(outbox_body)>0),
 PRIMARY KEY(plan_id,target_id),
 FOREIGN KEY(plan_id,target_id) REFERENCES po_target(plan_id,target_id)
) STRICT;
CREATE TRIGGER po_conflict_guard BEFORE INSERT ON po_conflict BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM po_target t JOIN po_plan_commit k USING(plan_id)
 WHERE t.plan_id=NEW.plan_id AND t.target_id=NEW.target_id AND t.binding_body=NEW.binding_body)
 THEN RAISE(ABORT,'preparation_conflict_binding') END;
END;
CREATE VIEW po_current_observation AS SELECT o.* FROM po_observation o JOIN po_observation_commit k
 USING(plan_id,target_id,preparation_revision,protection_revision)
 WHERE NOT EXISTS(SELECT 1 FROM po_observation n JOIN po_observation_commit c
 USING(plan_id,target_id,preparation_revision,protection_revision)
 WHERE n.plan_id=o.plan_id AND n.target_id=o.target_id AND
 (n.preparation_revision>o.preparation_revision OR(n.preparation_revision=o.preparation_revision AND n.protection_revision>o.protection_revision)));
CREATE VIEW po_target_status AS SELECT t.plan_id,t.target_id,o.preparation_revision,o.protection_revision,o.state,
 CASE WHEN EXISTS(SELECT 1 FROM po_conflict c WHERE c.plan_id=t.plan_id AND c.target_id=t.target_id) THEN 'unconfirmed'
 WHEN o.state='closed' THEN o.protection_state ELSE 'pending' END AS observed_closure_state
 FROM po_target t JOIN po_plan_commit k USING(plan_id) LEFT JOIN po_current_observation o USING(plan_id,target_id);
CREATE VIEW po_closure_summary AS SELECT p.plan_id,p.target_count,
 (SELECT count(*) FROM po_current_observation o WHERE o.plan_id=p.plan_id) AS observed_targets,
 CASE WHEN EXISTS(SELECT 1 FROM po_target_status s WHERE s.plan_id=p.plan_id AND s.observed_closure_state='unconfirmed') THEN 'unconfirmed'
 WHEN EXISTS(SELECT 1 FROM po_target_status s WHERE s.plan_id=p.plan_id AND s.observed_closure_state='indeterminate') THEN 'indeterminate'
 WHEN EXISTS(SELECT 1 FROM po_target_status s WHERE s.plan_id=p.plan_id AND s.observed_closure_state!='applied') THEN 'pending'
 ELSE 'applied' END AS observed_state FROM po_plan p JOIN po_plan_commit k USING(plan_id);
