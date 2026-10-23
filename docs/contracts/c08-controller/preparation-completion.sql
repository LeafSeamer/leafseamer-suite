-- 准备closed的历史与当前保护资格分离；只在235表组合候选之后加载。
CREATE TABLE pc_binding(
 completion_id TEXT PRIMARY KEY NOT NULL REFERENCES cp_completion(completion_id),
 fence_id TEXT NOT NULL REFERENCES ce_application(fence_id),
 receipt_id TEXT NOT NULL REFERENCES ce_application(receipt_id),
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 binding_body BLOB NOT NULL CHECK(length(binding_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE VIEW pc_qualified_binding AS SELECT b.* FROM pc_binding b
 JOIN cp_completion c USING(completion_id) JOIN ce_fence f ON f.fence_id=b.fence_id AND f.close_id=c.close_id
 JOIN pd_valid_application a ON a.fence_id=b.fence_id AND a.receipt_id=b.receipt_id AND a.receipt_body=b.receipt_body
 JOIN ra_current_status s ON s.fence_id=a.fence_id AND s.state='applied';
CREATE TRIGGER pc_binding_guard BEFORE INSERT ON pc_binding BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cp_completion c JOIN cp_event e ON e.event_id=c.event_id
 JOIN ce_fence f ON f.close_id=c.close_id JOIN pd_valid_application a ON a.fence_id=f.fence_id
 JOIN ra_current_status s ON s.fence_id=f.fence_id AND s.state='applied'
 WHERE c.completion_id=NEW.completion_id AND f.fence_id=NEW.fence_id
 AND a.receipt_id=NEW.receipt_id AND a.receipt_body=NEW.receipt_body
 AND NOT EXISTS(SELECT 1 FROM cp_commit k WHERE k.commit_id=e.commit_id))
 THEN RAISE(ABORT,'preparation_completion_source') END;
END;
CREATE TRIGGER pc_completion_seal BEFORE INSERT ON cp_commit WHEN NEW.kind='complete' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cp_event e JOIN pc_qualified_binding b USING(completion_id)
 WHERE e.event_id=NEW.event_id AND e.prep_key=NEW.prep_key AND e.commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'preparation_completion_not_current') END;
END;
CREATE TABLE pc_status_event(
 completion_id TEXT NOT NULL REFERENCES pc_binding(completion_id),
 revision INTEGER NOT NULL CHECK(revision IN (1,2)),
 state TEXT NOT NULL CHECK(state IN ('applied','indeterminate')),
 fence_id TEXT NOT NULL,
 run_status_revision INTEGER NOT NULL CHECK(run_status_revision IN (1,2)),
 PRIMARY KEY(completion_id,revision),
 FOREIGN KEY(fence_id,run_status_revision) REFERENCES ra_status_event(fence_id,revision),
 CHECK((revision=1 AND state='applied' AND run_status_revision=1)
 OR(revision=2 AND state='indeterminate' AND run_status_revision=2))
) STRICT;
CREATE TRIGGER pc_status_guard BEFORE INSERT ON pc_status_event BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pc_binding b JOIN cp_completion c USING(completion_id)
 JOIN cp_event e ON e.event_id=c.event_id JOIN cp_commit k ON k.commit_id=e.commit_id AND k.kind='complete'
 JOIN ra_status_event s ON s.fence_id=b.fence_id AND s.revision=NEW.run_status_revision AND s.state=NEW.state
 WHERE b.completion_id=NEW.completion_id AND b.fence_id=NEW.fence_id)
 OR (NEW.revision=1 AND NOT EXISTS(SELECT 1 FROM pc_qualified_binding b WHERE b.completion_id=NEW.completion_id))
 OR (NEW.revision=2 AND (NOT EXISTS(SELECT 1 FROM pc_status_event e WHERE e.completion_id=NEW.completion_id AND e.revision=1)
 OR EXISTS(SELECT 1 FROM pc_qualified_binding b WHERE b.completion_id=NEW.completion_id)))
 THEN RAISE(ABORT,'preparation_status_source') END;
END;
-- 此事件本身是可重读的投递事实；审计、原件与失效原因均通过不可变FK追溯。
CREATE TRIGGER pc_completed AFTER INSERT ON cp_commit WHEN NEW.kind='complete' BEGIN
 INSERT INTO pc_status_event SELECT b.completion_id,1,'applied',b.fence_id,1
 FROM cp_event e JOIN pc_binding b USING(completion_id) WHERE e.event_id=NEW.event_id;
END;
CREATE TRIGGER pc_invalidated AFTER INSERT ON ra_status_event WHEN NEW.revision=2 BEGIN
 INSERT INTO pc_status_event SELECT b.completion_id,2,'indeterminate',b.fence_id,2
 FROM pc_binding b JOIN pc_status_event s USING(completion_id)
 WHERE b.fence_id=NEW.fence_id AND s.revision=1
 AND NOT EXISTS(SELECT 1 FROM pc_status_event n WHERE n.completion_id=b.completion_id AND n.revision=2);
END;
CREATE VIEW pc_valid_completion AS SELECT b.* FROM pc_qualified_binding b JOIN cp_completion c USING(completion_id)
 JOIN cp_event e ON e.event_id=c.event_id JOIN cp_commit k ON k.commit_id=e.commit_id AND k.kind='complete'
 JOIN pc_status_event s USING(completion_id) WHERE s.revision=1
 AND NOT EXISTS(SELECT 1 FROM pc_status_event n WHERE n.completion_id=b.completion_id AND n.revision=2);
CREATE VIEW pc_current AS SELECT e.*,s.revision AS protection_revision,
 CASE WHEN e.state='closing' THEN 'pending' WHEN e.state!='closed' THEN 'not_applicable'
 WHEN v.completion_id IS NOT NULL THEN 'applied'
 WHEN s.revision=2 AND NOT EXISTS(SELECT 1 FROM pc_qualified_binding b WHERE b.completion_id=e.completion_id) THEN 'indeterminate'
 ELSE 'unconfirmed' END AS protection_state
 FROM cp_current e LEFT JOIN pc_valid_completion v USING(completion_id)
 LEFT JOIN pc_status_event s ON s.completion_id=e.completion_id
 AND s.revision=(SELECT max(n.revision) FROM pc_status_event n WHERE n.completion_id=e.completion_id);
-- 风险按关闭RUN完整来源与代次选择；只报告，不把关闭等同于释放或恢复。
CREATE VIEW pc_run_risk AS SELECT DISTINCT b.completion_id,h.hold_id,h.command_id,h.device_id
 FROM pc_binding b JOIN cp_completion c USING(completion_id) JOIN cp_event e ON e.event_id=c.event_id
 JOIN cp_commit k ON k.commit_id=e.commit_id JOIN ce_selector s ON s.fence_id=b.fence_id
 JOIN ce_run_command r ON (r.origin_authority,r.origin_database,r.run_id)=(s.origin_authority,s.origin_database,s.run_id)
 AND r.generation<=s.generation JOIN cr_risk_hold h ON h.command_id=r.command_id;
