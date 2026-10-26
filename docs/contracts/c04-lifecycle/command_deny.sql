-- 命令拒绝水位候选：事件在原受理／cut提交语句内自动追加，不替代完整关闭原件。
CREATE TABLE cd_event(
 device_id TEXT NOT NULL,
 snapshot_revision TEXT NOT NULL CHECK(length(snapshot_revision)=20 AND snapshot_revision NOT GLOB '*[^0-9]*' AND snapshot_revision>'00000000000000000000'),
 cancellation_id TEXT NOT NULL REFERENCES cv_cancel_commit(cancellation_id),
 command_id TEXT NOT NULL REFERENCES ce_command(command_id),
 event_kind TEXT NOT NULL CHECK(event_kind IN ('accepted','ordinary','all')),
 deny_revision TEXT NOT NULL CHECK(deny_revision IN ('00000000000000000001','00000000000000000002')),
 cut_id TEXT UNIQUE REFERENCES cc_cut_commit(cut_id),
 PRIMARY KEY(device_id,snapshot_revision), UNIQUE(cancellation_id,event_kind),
 CHECK((event_kind='accepted' AND cut_id IS NULL) OR (event_kind!='accepted' AND cut_id IS NOT NULL)),
 CHECK((event_kind='all' AND deny_revision='00000000000000000002') OR (event_kind!='all' AND deny_revision='00000000000000000001'))
) STRICT;
CREATE VIEW cd_expected AS
 SELECT cmd.device_id,c.cancellation_id,c.command_id,'accepted' AS event_kind,NULL AS cut_id
 FROM cv_cancel c JOIN cv_cancel_commit k USING(cancellation_id)
 JOIN cv_cancel_deny d USING(cancellation_id,command_id) JOIN ce_command cmd USING(command_id)
 UNION ALL
 SELECT cmd.device_id,c.cancellation_id,c.command_id,t.stage,t.cut_id
 FROM cc_cut t JOIN cc_cut_commit k USING(cut_id) JOIN cv_cancel c USING(cancellation_id)
 JOIN ce_command cmd USING(command_id);
CREATE VIEW cd_head AS
 SELECT d.device_id,coalesce(max(e.snapshot_revision),'00000000000000000000') AS revision
 FROM (SELECT DISTINCT device_id FROM ce_command) d LEFT JOIN cd_event e USING(device_id) GROUP BY d.device_id;
-- 两段十位整数避免 SQLite 的有符号64位边界及 REAL 精度损失；溢出为21位并拒绝。
CREATE VIEW cd_next AS
 SELECT device_id,printf('%010d%010d',CAST(substr(revision,1,10) AS INTEGER)+(substr(revision,11,10)='9999999999'),
 (CAST(substr(revision,11,10) AS INTEGER)+1)%10000000000) AS revision FROM cd_head;
CREATE TRIGGER cd_event_guard BEFORE INSERT ON cd_event BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cd_expected s WHERE s.device_id=NEW.device_id
 AND s.cancellation_id=NEW.cancellation_id AND s.command_id=NEW.command_id
 AND s.event_kind=NEW.event_kind AND s.cut_id IS NEW.cut_id) THEN RAISE(ABORT,'command_deny_source') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cd_next n WHERE n.device_id=NEW.device_id
 AND n.revision=NEW.snapshot_revision AND length(n.revision)=20) THEN RAISE(ABORT,'command_deny_successor') END;
 SELECT CASE WHEN NEW.event_kind='ordinary' AND NOT EXISTS(SELECT 1 FROM cd_event
 WHERE cancellation_id=NEW.cancellation_id AND event_kind='accepted') THEN RAISE(ABORT,'command_deny_accept_required') END;
 SELECT CASE WHEN NEW.event_kind='all' AND NOT EXISTS(SELECT 1 FROM cd_event e JOIN cc_cut t ON t.previous_cut_id=e.cut_id
 WHERE t.cut_id=NEW.cut_id AND e.cancellation_id=NEW.cancellation_id AND e.event_kind='ordinary') THEN RAISE(ABORT,'command_deny_ordinary_required') END;
END;
CREATE TRIGGER cd_accept AFTER INSERT ON cv_cancel_commit BEGIN
 INSERT INTO cd_event SELECT s.device_id,n.revision,s.cancellation_id,s.command_id,s.event_kind,'00000000000000000001',s.cut_id
 FROM cd_expected s JOIN cd_next n USING(device_id) WHERE s.cancellation_id=NEW.cancellation_id AND s.event_kind='accepted';
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cd_event WHERE cancellation_id=NEW.cancellation_id AND event_kind='accepted')
 THEN RAISE(ABORT,'command_deny_source_missing') END;
END;
CREATE TRIGGER cd_cut AFTER INSERT ON cc_cut_commit BEGIN
 INSERT INTO cd_event SELECT s.device_id,n.revision,s.cancellation_id,s.command_id,s.event_kind,
 CASE s.event_kind WHEN 'all' THEN '00000000000000000002' ELSE '00000000000000000001' END,s.cut_id
 FROM cd_expected s JOIN cd_next n USING(device_id) WHERE s.cut_id=NEW.cut_id;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cd_event WHERE cut_id=NEW.cut_id) THEN RAISE(ABORT,'command_deny_source_missing') END;
END;
CREATE TRIGGER cd_event_u BEFORE UPDATE ON cd_event BEGIN SELECT RAISE(ABORT,'immutable_command_deny'); END;
CREATE TRIGGER cd_event_d BEFORE DELETE ON cd_event BEGIN SELECT RAISE(ABORT,'immutable_command_deny'); END;
