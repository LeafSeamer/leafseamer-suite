-- 命令拒绝快照只封存既有来源；不授予开放或发送权限。
CREATE VIEW ds_frontier AS
 SELECT h.device_id,h.revision,count(e.command_id) AS entry_count,
 coalesce(sum(e.event_kind='accepted'),0) AS pending_count
 FROM cd_head h LEFT JOIN cd_event e ON e.device_id=h.device_id
 AND NOT EXISTS(SELECT 1 FROM cd_event n WHERE n.device_id=e.device_id
 AND n.command_id=e.command_id AND n.snapshot_revision>e.snapshot_revision)
 GROUP BY h.device_id,h.revision;
CREATE TABLE ds_snapshot(
 snapshot_id TEXT PRIMARY KEY NOT NULL,device_id TEXT NOT NULL,
 snapshot_revision TEXT NOT NULL CHECK(length(snapshot_revision)=20 AND snapshot_revision NOT GLOB '*[^0-9]*'),
 entry_count INTEGER NOT NULL CHECK(entry_count BETWEEN 0 AND 4096),
 snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=71 AND substr(snapshot_digest,1,7)='sha256:'),
 body BLOB NOT NULL CHECK(length(body)>0 AND length(body)<=16777216),
 FOREIGN KEY(snapshot_id) REFERENCES ds_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ds_commit(
 snapshot_id TEXT PRIMARY KEY NOT NULL REFERENCES ds_snapshot(snapshot_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
CREATE TRIGGER ds_snapshot_guard BEFORE INSERT ON ds_snapshot BEGIN
 SELECT CASE WHEN NEW.snapshot_revision!=coalesce((SELECT revision FROM ds_frontier WHERE device_id=NEW.device_id),'00000000000000000000')
 OR NEW.entry_count!=coalesce((SELECT entry_count FROM ds_frontier WHERE device_id=NEW.device_id),0)
 OR coalesce((SELECT pending_count FROM ds_frontier WHERE device_id=NEW.device_id),0)!=0
 THEN RAISE(ABORT,'command_snapshot_frontier') END;
END;
CREATE TRIGGER ds_commit_guard BEFORE INSERT ON ds_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ds_snapshot s WHERE s.snapshot_id=NEW.snapshot_id AND s.body=NEW.audit_body
 AND s.snapshot_revision=coalesce((SELECT revision FROM ds_frontier WHERE device_id=s.device_id),'00000000000000000000')
 AND s.entry_count=coalesce((SELECT entry_count FROM ds_frontier WHERE device_id=s.device_id),0)
 AND coalesce((SELECT pending_count FROM ds_frontier WHERE device_id=s.device_id),0)=0)
 THEN RAISE(ABORT,'command_snapshot_seal') END;
END;
CREATE TRIGGER ds_snapshot_u BEFORE UPDATE ON ds_snapshot BEGIN SELECT RAISE(ABORT,'immutable_command_snapshot'); END;
CREATE TRIGGER ds_snapshot_d BEFORE DELETE ON ds_snapshot BEGIN SELECT RAISE(ABORT,'immutable_command_snapshot'); END;
CREATE TRIGGER ds_commit_u BEFORE UPDATE ON ds_commit BEGIN SELECT RAISE(ABORT,'immutable_command_snapshot'); END;
CREATE TRIGGER ds_commit_d BEFORE DELETE ON ds_commit BEGIN SELECT RAISE(ABORT,'immutable_command_snapshot'); END;
