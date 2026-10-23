-- 设计候选：只在隔离内存数据库验证，不是生产迁移。
PRAGMA foreign_keys=ON;
PRAGMA recursive_triggers=ON;
CREATE TABLE ts_scope (
 id INTEGER PRIMARY KEY CHECK(id=1), authority TEXT NOT NULL, database_id TEXT NOT NULL,
 version TEXT NOT NULL CHECK(version='reference-time-storage/0.1.0-draft.1')
) STRICT;
CREATE TABLE ts_binding (
 id TEXT PRIMARY KEY NOT NULL, scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES ts_scope(id),
 generation TEXT NOT NULL CHECK(length(generation)=20 AND generation NOT GLOB '*[^0-9]*'),
 body BLOB NOT NULL, UNIQUE(id,generation)
) STRICT;
CREATE TABLE ts_poll (
 id TEXT PRIMARY KEY NOT NULL, binding_id TEXT NOT NULL REFERENCES ts_binding(id),
 correlation_id TEXT NOT NULL UNIQUE, body BLOB NOT NULL, UNIQUE(id,binding_id),
 FOREIGN KEY(id) REFERENCES tc_reservation(poll_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ts_commit (
 id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL CHECK(kind IN('bootstrap','publish','reject','failure','invalidate')),
 receipt_body BLOB NOT NULL,
 FOREIGN KEY(id) REFERENCES ts_seal(commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(id) REFERENCES ts_audit(commit_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(id) REFERENCES ts_outbox(commit_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE ts_capture (
 id TEXT PRIMARY KEY NOT NULL, poll_id TEXT NOT NULL UNIQUE, binding_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN('candidate','failed','indeterminate')),
 disposition TEXT NOT NULL CHECK(disposition IN('published','rejected','failure_recorded')),
 blob_count INTEGER NOT NULL CHECK(blob_count BETWEEN 0 AND 3),
 commit_id TEXT NOT NULL UNIQUE REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 body BLOB NOT NULL, UNIQUE(id,binding_id),
 FOREIGN KEY(poll_id,binding_id) REFERENCES ts_poll(id,binding_id),
 CHECK(disposition!='published' OR (status='candidate' AND blob_count=2))
) STRICT;
CREATE TABLE ts_blob (
 capture_id TEXT NOT NULL REFERENCES ts_capture(id), slot TEXT NOT NULL CHECK(slot IN('request','response','diagnostic')),
 plain_digest TEXT NOT NULL, plain_size INTEGER NOT NULL CHECK(plain_size BETWEEN 0 AND 65536),
 ciphertext BLOB NOT NULL CHECK(length(ciphertext) BETWEEN 1 AND 131072),
 body BLOB NOT NULL, PRIMARY KEY(capture_id,slot)
) STRICT;
CREATE TABLE ts_verification (
 capture_id TEXT PRIMARY KEY NOT NULL, binding_id TEXT NOT NULL, body BLOB NOT NULL,
 FOREIGN KEY(capture_id,binding_id) REFERENCES ts_capture(id,binding_id)
) STRICT;
CREATE TABLE ts_anchor (
 id TEXT PRIMARY KEY NOT NULL, capture_id TEXT NOT NULL UNIQUE, binding_id TEXT NOT NULL,
 tick TEXT NOT NULL CHECK(length(tick)=20 AND tick NOT GLOB '*[^0-9]*'), body BLOB NOT NULL,
 UNIQUE(id,binding_id), FOREIGN KEY(capture_id,binding_id) REFERENCES ts_capture(id,binding_id),
 FOREIGN KEY(capture_id) REFERENCES ts_verification(capture_id)
) STRICT;
CREATE TABLE ts_state (
 revision TEXT PRIMARY KEY NOT NULL CHECK(length(revision)=20 AND revision NOT GLOB '*[^0-9]*' AND revision!='00000000000000000000'),
 previous TEXT REFERENCES ts_state(revision), binding_id TEXT NOT NULL REFERENCES ts_binding(id),
 status TEXT NOT NULL CHECK(status IN('collecting','qualified','unavailable')),
 anchor_id TEXT, commit_id TEXT NOT NULL UNIQUE REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 body BLOB NOT NULL,
 FOREIGN KEY(anchor_id,binding_id) REFERENCES ts_anchor(id,binding_id),
 CHECK((status='qualified' AND anchor_id IS NOT NULL) OR (status!='qualified' AND anchor_id IS NULL))
) STRICT;
CREATE TABLE ts_head (
 id INTEGER PRIMARY KEY CHECK(id=1), revision TEXT NOT NULL REFERENCES ts_state(revision)
) STRICT;
CREATE TABLE ts_invalidation (
 id TEXT PRIMARY KEY NOT NULL, old_binding TEXT NOT NULL REFERENCES ts_binding(id),
 new_binding TEXT NOT NULL REFERENCES ts_binding(id),
 commit_id TEXT NOT NULL UNIQUE REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 protection_ref BLOB NOT NULL, body BLOB NOT NULL, CHECK(old_binding!=new_binding)
) STRICT;
CREATE TABLE ts_audit (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 body BLOB NOT NULL
) STRICT;
CREATE TABLE ts_outbox (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES ts_commit(id) DEFERRABLE INITIALLY DEFERRED,
 kind TEXT NOT NULL CHECK(kind IN('notification','time_fence')), body BLOB NOT NULL
) STRICT;
CREATE TABLE ts_seal (
 commit_id TEXT PRIMARY KEY NOT NULL REFERENCES ts_commit(id), body BLOB NOT NULL
) STRICT;

-- 精确后继：两段各10位，不把完整U20转换为64位整数或REAL。
CREATE TRIGGER ts_state_sequence BEFORE INSERT ON ts_state BEGIN
 SELECT CASE WHEN NEW.previous IS NULL AND (NEW.revision!='00000000000000000001' OR EXISTS(SELECT 1 FROM ts_state))
 THEN RAISE(ABORT,'initial_revision') END;
 SELECT CASE WHEN NEW.previous IS NOT NULL AND (
 NOT EXISTS(SELECT 1 FROM ts_head WHERE revision=NEW.previous) OR
 NEW.previous='99999999999999999999' OR
 NEW.revision != printf('%010d%010d',
 CAST(substr(NEW.previous,1,10) AS INTEGER)+(CAST(substr(NEW.previous,11,10) AS INTEGER)=9999999999),
 (CAST(substr(NEW.previous,11,10) AS INTEGER)+1)%10000000000))
 THEN RAISE(ABORT,'state_cas') END;
END;
CREATE TRIGGER ts_head_step BEFORE UPDATE ON ts_head BEGIN
 SELECT CASE WHEN NEW.id!=OLD.id OR NOT EXISTS(SELECT 1 FROM ts_state WHERE revision=NEW.revision AND previous=OLD.revision)
 THEN RAISE(ABORT,'head_cas') END;
END;
CREATE TRIGGER ts_poll_current BEFORE INSERT ON ts_poll BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ts_head h JOIN ts_state s ON s.revision=h.revision
 JOIN ts_seal z ON z.commit_id=s.commit_id WHERE s.binding_id=NEW.binding_id AND s.status IN('collecting','qualified'))
 THEN RAISE(ABORT,'poll_not_current') END;
END;
CREATE TRIGGER ts_seal_validate BEFORE INSERT ON ts_seal BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ts_audit WHERE commit_id=NEW.commit_id)
 OR NOT EXISTS(SELECT 1 FROM ts_outbox WHERE commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'missing_delivery') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ts_capture c WHERE c.commit_id=NEW.commit_id AND
 c.blob_count!=(SELECT count(*) FROM ts_blob b WHERE b.capture_id=c.id))
 THEN RAISE(ABORT,'blob_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ts_commit c JOIN ts_outbox o ON o.commit_id=c.id WHERE c.id=NEW.commit_id
 AND ((c.kind='invalidate')!=(o.kind='time_fence')))
 THEN RAISE(ABORT,'outbox_kind') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id) IN('bootstrap','publish','invalidate') AND
 NOT EXISTS(SELECT 1 FROM ts_state s JOIN ts_head h ON h.revision=s.revision WHERE s.commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'missing_current_state') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id) IN('reject','failure') AND
 (EXISTS(SELECT 1 FROM ts_state WHERE commit_id=NEW.commit_id) OR
 NOT EXISTS(SELECT 1 FROM ts_capture WHERE commit_id=NEW.commit_id AND
 disposition=CASE (SELECT kind FROM ts_commit WHERE id=NEW.commit_id) WHEN 'reject' THEN 'rejected' ELSE 'failure_recorded' END))
 THEN RAISE(ABORT,'failure_state') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id) IN('bootstrap','invalidate') AND
 EXISTS(SELECT 1 FROM ts_capture WHERE commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'unexpected_capture') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)='bootstrap' AND
 EXISTS(SELECT 1 FROM ts_state s LEFT JOIN ts_state p ON p.revision=s.previous WHERE s.commit_id=NEW.commit_id AND
 (s.status!='collecting' OR (s.previous IS NOT NULL AND (p.status!='unavailable' OR s.binding_id!=p.binding_id))))
 THEN RAISE(ABORT,'bootstrap_state') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)='publish' AND NOT EXISTS(
 SELECT 1 FROM ts_capture c JOIN ts_anchor a ON a.capture_id=c.id
 JOIN ts_state s ON s.commit_id=c.commit_id JOIN ts_state p ON p.revision=s.previous
 WHERE c.commit_id=NEW.commit_id AND c.disposition='published' AND c.status='candidate'
 AND s.status='qualified' AND s.anchor_id=a.id AND s.binding_id=c.binding_id AND p.binding_id=c.binding_id
 AND p.status IN('collecting','qualified') AND
 (p.anchor_id IS NULL OR a.tick>(SELECT tick FROM ts_anchor WHERE id=p.anchor_id))
 AND EXISTS(SELECT 1 FROM ts_blob WHERE capture_id=c.id AND slot='request')
 AND EXISTS(SELECT 1 FROM ts_blob WHERE capture_id=c.id AND slot='response'))
 THEN RAISE(ABORT,'publish_chain') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)!='publish' AND
 EXISTS(SELECT 1 FROM ts_capture c JOIN ts_anchor a ON a.capture_id=c.id WHERE c.commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'unexpected_anchor') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)='invalidate' AND NOT EXISTS(
 SELECT 1 FROM ts_invalidation i JOIN ts_state s ON s.commit_id=i.commit_id JOIN ts_state p ON p.revision=s.previous
 JOIN ts_binding old ON old.id=i.old_binding JOIN ts_binding next ON next.id=i.new_binding
 WHERE i.commit_id=NEW.commit_id AND p.binding_id=i.old_binding AND s.binding_id=i.new_binding
 AND s.status='unavailable' AND old.generation!='99999999999999999999'
 AND next.generation=printf('%010d%010d',CAST(substr(old.generation,1,10) AS INTEGER)+(CAST(substr(old.generation,11,10) AS INTEGER)=9999999999),
 (CAST(substr(old.generation,11,10) AS INTEGER)+1)%10000000000))
 THEN RAISE(ABORT,'invalidation_chain') END;
 SELECT CASE WHEN (SELECT kind FROM ts_commit WHERE id=NEW.commit_id)!='invalidate' AND
 EXISTS(SELECT 1 FROM ts_invalidation WHERE commit_id=NEW.commit_id)
 THEN RAISE(ABORT,'unexpected_invalidation') END;
END;

-- 不可变保护完整安装在本文件中，检查脚本不能补建约束。
CREATE TRIGGER ts_scope_no_update BEFORE UPDATE ON ts_scope BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_scope_no_delete BEFORE DELETE ON ts_scope BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_binding_no_update BEFORE UPDATE ON ts_binding BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_binding_no_delete BEFORE DELETE ON ts_binding BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_poll_no_update BEFORE UPDATE ON ts_poll BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_poll_no_delete BEFORE DELETE ON ts_poll BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_commit_no_update BEFORE UPDATE ON ts_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_commit_no_delete BEFORE DELETE ON ts_commit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_capture_no_update BEFORE UPDATE ON ts_capture BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_capture_no_delete BEFORE DELETE ON ts_capture BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_blob_no_update BEFORE UPDATE ON ts_blob BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_blob_no_delete BEFORE DELETE ON ts_blob BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_verification_no_update BEFORE UPDATE ON ts_verification BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_verification_no_delete BEFORE DELETE ON ts_verification BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_anchor_no_update BEFORE UPDATE ON ts_anchor BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_anchor_no_delete BEFORE DELETE ON ts_anchor BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_state_no_update BEFORE UPDATE ON ts_state BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_state_no_delete BEFORE DELETE ON ts_state BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_head_no_delete BEFORE DELETE ON ts_head BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_invalidation_no_update BEFORE UPDATE ON ts_invalidation BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_invalidation_no_delete BEFORE DELETE ON ts_invalidation BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_audit_no_update BEFORE UPDATE ON ts_audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_audit_no_delete BEFORE DELETE ON ts_audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_outbox_no_update BEFORE UPDATE ON ts_outbox BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_outbox_no_delete BEFORE DELETE ON ts_outbox BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_seal_no_update BEFORE UPDATE ON ts_seal BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_seal_no_delete BEFORE DELETE ON ts_seal BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER ts_capture_closed BEFORE INSERT ON ts_capture WHEN EXISTS(SELECT 1 FROM ts_seal WHERE commit_id=NEW.commit_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_blob_closed BEFORE INSERT ON ts_blob WHEN EXISTS(SELECT 1 FROM ts_capture c JOIN ts_seal z ON z.commit_id=c.commit_id WHERE c.id=NEW.capture_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_verification_closed BEFORE INSERT ON ts_verification WHEN EXISTS(SELECT 1 FROM ts_capture c JOIN ts_seal z ON z.commit_id=c.commit_id WHERE c.id=NEW.capture_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_anchor_closed BEFORE INSERT ON ts_anchor WHEN EXISTS(SELECT 1 FROM ts_capture c JOIN ts_seal z ON z.commit_id=c.commit_id WHERE c.id=NEW.capture_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_state_closed BEFORE INSERT ON ts_state WHEN EXISTS(SELECT 1 FROM ts_seal WHERE commit_id=NEW.commit_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE TRIGGER ts_invalidation_closed BEFORE INSERT ON ts_invalidation WHEN EXISTS(SELECT 1 FROM ts_seal WHERE commit_id=NEW.commit_id) BEGIN SELECT RAISE(ABORT,'sealed'); END;
CREATE VIEW ts_current AS SELECT s.* FROM ts_head h JOIN ts_state s ON s.revision=h.revision JOIN ts_seal z ON z.commit_id=s.commit_id;

-- 设计候选附属布局，必须由build_journal.py与十四表时间源组合；非生产迁移。
CREATE TABLE tc_policy (
 id INTEGER PRIMARY KEY CHECK(id=1), max_sources INTEGER NOT NULL CHECK(max_sources BETWEEN 1 AND 1024),
 max_outstanding INTEGER NOT NULL CHECK(max_outstanding BETWEEN 1 AND 65536),
 max_reserved_bytes INTEGER NOT NULL CHECK(max_reserved_bytes BETWEEN 1 AND 1099511627776),
 max_channels INTEGER NOT NULL CHECK(max_channels BETWEEN 1 AND 65536),
 max_queries INTEGER NOT NULL CHECK(max_queries BETWEEN 0 AND 1024), max_inbox INTEGER NOT NULL CHECK(max_inbox BETWEEN 1 AND 1048576), body BLOB NOT NULL
) STRICT;
CREATE TABLE tc_source (
 id TEXT PRIMARY KEY NOT NULL, canonical_digest TEXT NOT NULL UNIQUE, body BLOB NOT NULL
) STRICT;
CREATE TABLE tc_channel (
 id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES tc_source(id),
 binding_id TEXT NOT NULL REFERENCES ts_binding(id), config_id TEXT NOT NULL UNIQUE,
 runtime_ref BLOB NOT NULL, interval_receipt BLOB NOT NULL, body BLOB NOT NULL,
 UNIQUE(id,binding_id)
) STRICT;
CREATE TABLE tc_reservation (
 poll_id TEXT PRIMARY KEY NOT NULL, channel_id TEXT NOT NULL, binding_id TEXT NOT NULL,
 ordinal TEXT NOT NULL CHECK(length(ordinal)=20 AND ordinal NOT GLOB '*[^0-9]*' AND ordinal!='00000000000000000000'),
 reserved_bytes INTEGER NOT NULL CHECK(reserved_bytes BETWEEN 1 AND 2147483647), body BLOB NOT NULL,
 UNIQUE(channel_id,ordinal), UNIQUE(poll_id,channel_id),
 FOREIGN KEY(poll_id,binding_id) REFERENCES ts_poll(id,binding_id),
 FOREIGN KEY(channel_id,binding_id) REFERENCES tc_channel(id,binding_id)
) STRICT;
CREATE TABLE tc_frame (
 channel_id TEXT NOT NULL REFERENCES tc_channel(id),
 sequence TEXT NOT NULL CHECK(length(sequence)=20 AND sequence NOT GLOB '*[^0-9]*' AND sequence!='00000000000000000000'),
 message_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN('ACCEPT','CONFIGURE','POLL','REPORT_STORED','QUERY_CAPTURE','COMMIT_STATUS','STOP')),
 poll_id TEXT, receipt_commit TEXT REFERENCES ts_commit(id), stop_id TEXT REFERENCES tc_stop(id),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 65536),
 reply_to TEXT,
 PRIMARY KEY(channel_id,sequence), UNIQUE(channel_id,message_id), UNIQUE(channel_id,sequence,stop_id),
 FOREIGN KEY(channel_id,reply_to) REFERENCES tc_inbox(channel_id,message_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(poll_id,channel_id) REFERENCES tc_reservation(poll_id,channel_id),
 CHECK((kind='POLL' AND poll_id IS NOT NULL AND receipt_commit IS NULL AND stop_id IS NULL) OR
 (kind='REPORT_STORED' AND poll_id IS NOT NULL AND receipt_commit IS NOT NULL AND stop_id IS NULL) OR
 (kind='STOP' AND poll_id IS NULL AND receipt_commit IS NULL AND stop_id IS NOT NULL) OR
 (kind IN('ACCEPT','CONFIGURE','QUERY_CAPTURE','COMMIT_STATUS') AND poll_id IS NULL AND receipt_commit IS NULL AND stop_id IS NULL))
) STRICT;
CREATE UNIQUE INDEX tc_one_poll_frame ON tc_frame(poll_id) WHERE kind='POLL';
CREATE UNIQUE INDEX tc_one_receipt_frame ON tc_frame(poll_id) WHERE kind='REPORT_STORED';
CREATE UNIQUE INDEX tc_one_stop_frame ON tc_frame(stop_id) WHERE kind='STOP';
CREATE UNIQUE INDEX tc_one_setup_frame ON tc_frame(channel_id,kind) WHERE kind IN('ACCEPT','CONFIGURE');
CREATE TABLE tc_attempt (
 channel_id TEXT NOT NULL, sequence TEXT NOT NULL, body BLOB NOT NULL,
 PRIMARY KEY(channel_id,sequence), FOREIGN KEY(channel_id,sequence) REFERENCES tc_frame(channel_id,sequence)
) STRICT;
CREATE TABLE tc_written (
 channel_id TEXT NOT NULL, sequence TEXT NOT NULL, body BLOB NOT NULL,
 PRIMARY KEY(channel_id,sequence), FOREIGN KEY(channel_id,sequence) REFERENCES tc_attempt(channel_id,sequence)
) STRICT;
CREATE TABLE tc_stop (
 id TEXT PRIMARY KEY NOT NULL, channel_id TEXT NOT NULL UNIQUE REFERENCES tc_channel(id),
 invalidation_commit TEXT NOT NULL REFERENCES ts_invalidation(commit_id), body BLOB NOT NULL,
 UNIQUE(id,channel_id)
) STRICT;
CREATE TABLE tc_ack (
 stop_id TEXT PRIMARY KEY NOT NULL, channel_id TEXT NOT NULL, received_through TEXT NOT NULL,
 last_poll_ordinal TEXT NOT NULL CHECK(length(last_poll_ordinal)=20 AND last_poll_ordinal NOT GLOB '*[^0-9]*'),
 closed_tick TEXT NOT NULL CHECK(length(closed_tick)=20 AND closed_tick NOT GLOB '*[^0-9]*'), body BLOB NOT NULL,
 FOREIGN KEY(stop_id,channel_id) REFERENCES tc_stop(id,channel_id),
 FOREIGN KEY(channel_id,received_through,stop_id) REFERENCES tc_frame(channel_id,sequence,stop_id),
 FOREIGN KEY(channel_id,received_through) REFERENCES tc_attempt(channel_id,sequence)
) STRICT;
CREATE TABLE tc_retired (
 channel_id TEXT PRIMARY KEY NOT NULL REFERENCES tc_stop(channel_id), supervisor_receipt_id TEXT NOT NULL UNIQUE,
 receiving_domain BLOB NOT NULL, received_tick TEXT NOT NULL CHECK(length(received_tick)=20 AND received_tick NOT GLOB '*[^0-9]*'),
 body BLOB NOT NULL
) STRICT;
CREATE TABLE tc_release (
 poll_id TEXT PRIMARY KEY NOT NULL, channel_id TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(reason IN('stored','retired')),
 capture_commit TEXT REFERENCES ts_commit(id), receipt_sequence TEXT,
 retired_channel TEXT REFERENCES tc_retired(channel_id), body BLOB NOT NULL,
 FOREIGN KEY(poll_id,channel_id) REFERENCES tc_reservation(poll_id,channel_id),
 FOREIGN KEY(channel_id,receipt_sequence) REFERENCES tc_frame(channel_id,sequence),
 CHECK((reason='stored' AND capture_commit IS NOT NULL AND receipt_sequence IS NOT NULL AND retired_channel IS NULL) OR
 (reason='retired' AND capture_commit IS NULL AND receipt_sequence IS NULL AND retired_channel=channel_id AND retired_channel IS NOT NULL))
) STRICT;

CREATE VIEW tc_active AS SELECT r.*,c.source_id FROM tc_reservation r JOIN tc_channel c ON c.id=r.channel_id
 WHERE NOT EXISTS(SELECT 1 FROM tc_release x WHERE x.poll_id=r.poll_id);
CREATE VIEW tc_recovery AS SELECT f.channel_id,f.sequence,f.kind,
 CASE WHEN w.sequence IS NOT NULL THEN 'submitted_not_peer_ack'
 WHEN a.sequence IS NOT NULL THEN 'write_unknown'
 ELSE 'never_attempted_old_channel_not_replayable' END AS disposition
 FROM tc_frame f LEFT JOIN tc_attempt a USING(channel_id,sequence) LEFT JOIN tc_written w USING(channel_id,sequence);
-- 是逻辑证据计费，不是SQLite页/索引/WAL文件长度。固定行附加预算由profile提供者另验。
CREATE VIEW tc_capture_bytes AS SELECT c.id,c.poll_id,c.commit_id,
 length(c.body)+length(k.receipt_body)+length(au.body)+length(o.body)+
 coalesce((SELECT sum(length(ciphertext)+length(body)) FROM ts_blob WHERE capture_id=c.id),0)+
 coalesce((SELECT sum(length(body)) FROM ts_verification WHERE capture_id=c.id),0)+
 coalesce((SELECT sum(length(body)) FROM ts_anchor WHERE capture_id=c.id),0)+
 coalesce((SELECT sum(length(body)) FROM ts_state WHERE commit_id=c.commit_id),0) AS bytes
 FROM ts_capture c JOIN ts_commit k ON k.id=c.commit_id JOIN ts_audit au ON au.commit_id=k.id JOIN ts_outbox o ON o.commit_id=k.id;

CREATE TRIGGER tc_channel_admit BEFORE INSERT ON tc_channel BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tc_policy) OR
 (SELECT count(*) FROM tc_channel)>=(SELECT max_channels FROM tc_policy)
 THEN RAISE(ABORT,'channel_budget') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ts_current WHERE binding_id=NEW.binding_id AND status='collecting')
 THEN RAISE(ABORT,'channel_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM tc_channel c WHERE c.source_id=NEW.source_id AND
 NOT EXISTS(SELECT 1 FROM tc_retired r WHERE r.channel_id=c.id))
 THEN RAISE(ABORT,'source_instance_live') END;
 SELECT CASE WHEN (SELECT count(*) FROM tc_channel c WHERE NOT EXISTS(SELECT 1 FROM tc_retired r WHERE r.channel_id=c.id))
 >=(SELECT max_sources FROM tc_policy) THEN RAISE(ABORT,'source_capacity') END;
END;
CREATE TRIGGER tc_reserve BEFORE INSERT ON tc_reservation BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM tc_stop WHERE channel_id=NEW.channel_id) OR
 EXISTS(SELECT 1 FROM tc_retired WHERE channel_id=NEW.channel_id)
 THEN RAISE(ABORT,'channel_closed') END;
 SELECT CASE WHEN (SELECT count(*) FROM tc_active)>=(SELECT max_outstanding FROM tc_policy) OR
 EXISTS(SELECT 1 FROM tc_active a JOIN tc_channel c ON c.id=NEW.channel_id WHERE a.source_id=c.source_id)
 THEN RAISE(ABORT,'active_capacity') END;
 SELECT CASE WHEN NEW.reserved_bytes+coalesce((SELECT sum(reserved_bytes) FROM tc_reservation),0)>
 (SELECT max_reserved_bytes FROM tc_policy) THEN RAISE(ABORT,'retained_capacity') END;
 SELECT CASE WHEN coalesce((SELECT max(ordinal) FROM tc_reservation WHERE channel_id=NEW.channel_id),'00000000000000000000')='99999999999999999999'
 OR NEW.ordinal!=printf('%010d%010d',
 CAST(substr(coalesce((SELECT max(ordinal) FROM tc_reservation WHERE channel_id=NEW.channel_id),'00000000000000000000'),1,10) AS INTEGER)+
 (CAST(substr(coalesce((SELECT max(ordinal) FROM tc_reservation WHERE channel_id=NEW.channel_id),'00000000000000000000'),11,10) AS INTEGER)=9999999999),
 (CAST(substr(coalesce((SELECT max(ordinal) FROM tc_reservation WHERE channel_id=NEW.channel_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000)
 THEN RAISE(ABORT,'poll_ordinal') END;
END;
CREATE TRIGGER tc_frame_order BEFORE INSERT ON tc_frame BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM tc_retired WHERE channel_id=NEW.channel_id) THEN RAISE(ABORT,'retired') END;
 SELECT CASE WHEN coalesce((SELECT max(sequence) FROM tc_frame WHERE channel_id=NEW.channel_id),'00000000000000000000')='99999999999999999999'
 OR NEW.sequence!=printf('%010d%010d',
 CAST(substr(coalesce((SELECT max(sequence) FROM tc_frame WHERE channel_id=NEW.channel_id),'00000000000000000000'),1,10) AS INTEGER)+
 (CAST(substr(coalesce((SELECT max(sequence) FROM tc_frame WHERE channel_id=NEW.channel_id),'00000000000000000000'),11,10) AS INTEGER)=9999999999),
 (CAST(substr(coalesce((SELECT max(sequence) FROM tc_frame WHERE channel_id=NEW.channel_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000)
 THEN RAISE(ABORT,'frame_sequence') END;
 SELECT CASE WHEN NEW.kind IN('QUERY_CAPTURE','COMMIT_STATUS') AND
 (SELECT count(*) FROM tc_frame WHERE channel_id=NEW.channel_id AND kind IN('QUERY_CAPTURE','COMMIT_STATUS'))>=(SELECT max_queries FROM tc_policy)
 THEN RAISE(ABORT,'query_budget') END;
 SELECT CASE WHEN NEW.kind='POLL' AND (EXISTS(SELECT 1 FROM tc_stop WHERE channel_id=NEW.channel_id) OR
 EXISTS(SELECT 1 FROM tc_release WHERE poll_id=NEW.poll_id)) THEN RAISE(ABORT,'poll_closed') END;
 SELECT CASE WHEN NEW.kind='POLL' AND EXISTS(
 SELECT 1 FROM tc_reservation old JOIN tc_reservation now ON now.poll_id=NEW.poll_id
 WHERE old.channel_id=now.channel_id AND old.ordinal<now.ordinal AND NOT EXISTS(
 SELECT 1 FROM tc_release x JOIN tc_frame f ON f.channel_id=x.channel_id AND f.sequence=x.receipt_sequence
 WHERE x.poll_id=old.poll_id AND x.reason='stored' AND f.kind='REPORT_STORED' AND f.sequence<NEW.sequence))
 THEN RAISE(ABORT,'receipt_before_next_poll') END;
 SELECT CASE WHEN NEW.kind='REPORT_STORED' AND NOT EXISTS(SELECT 1 FROM ts_capture c
 WHERE c.poll_id=NEW.poll_id AND c.commit_id=NEW.receipt_commit) THEN RAISE(ABORT,'receipt_binding') END;
 SELECT CASE WHEN NEW.kind='STOP' AND NOT EXISTS(SELECT 1 FROM tc_stop WHERE id=NEW.stop_id AND channel_id=NEW.channel_id)
 THEN RAISE(ABORT,'stop_binding') END;
END;
CREATE TRIGGER tc_attempt_order BEFORE INSERT ON tc_attempt BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM tc_retired WHERE channel_id=NEW.channel_id) THEN RAISE(ABORT,'retired') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM tc_frame f WHERE f.channel_id=NEW.channel_id AND f.sequence<NEW.sequence
 AND NOT EXISTS(SELECT 1 FROM tc_written w WHERE w.channel_id=f.channel_id AND w.sequence=f.sequence))
 THEN RAISE(ABORT,'incomplete_prefix') END;
END;
CREATE TRIGGER tc_stop_bind BEFORE INSERT ON tc_stop BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tc_channel c JOIN ts_invalidation i ON i.old_binding=c.binding_id
 WHERE c.id=NEW.channel_id AND i.commit_id=NEW.invalidation_commit)
 OR EXISTS(SELECT 1 FROM ts_seal WHERE commit_id=NEW.invalidation_commit)
 THEN RAISE(ABORT,'stop_invalidation') END;
END;
CREATE TRIGGER tc_ack_bind BEFORE INSERT ON tc_ack BEGIN
 SELECT CASE WHEN NEW.last_poll_ordinal!=coalesce((SELECT max(r.ordinal) FROM tc_frame f JOIN tc_reservation r ON r.poll_id=f.poll_id
 WHERE f.channel_id=NEW.channel_id AND f.kind='POLL' AND f.sequence<NEW.received_through),'00000000000000000000')
 THEN RAISE(ABORT,'ack_ordinal') END;
END;
CREATE TRIGGER tc_release_bind BEFORE INSERT ON tc_release WHEN NEW.reason='stored' BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ts_seal WHERE commit_id=NEW.capture_commit) OR NOT EXISTS(
 SELECT 1 FROM ts_capture c JOIN tc_frame f ON f.poll_id=c.poll_id AND f.receipt_commit=c.commit_id
 WHERE c.poll_id=NEW.poll_id AND c.commit_id=NEW.capture_commit AND f.channel_id=NEW.channel_id
 AND f.sequence=NEW.receipt_sequence AND f.kind='REPORT_STORED' AND EXISTS(
 SELECT 1 FROM tc_frame p JOIN tc_attempt a ON a.channel_id=p.channel_id AND a.sequence=p.sequence
 WHERE p.kind='POLL' AND p.poll_id=NEW.poll_id))
 THEN RAISE(ABORT,'release_receipt') END;
END;
CREATE TRIGGER tc_seal_complete BEFORE INSERT ON ts_seal BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ts_capture c WHERE c.commit_id=NEW.commit_id AND NOT EXISTS(
 SELECT 1 FROM tc_release r WHERE r.poll_id=c.poll_id AND
 ((r.capture_commit=c.commit_id AND r.reason='stored') OR (r.reason='retired' AND c.disposition!='published'))))
 THEN RAISE(ABORT,'missing_release') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM tc_capture_bytes c JOIN tc_reservation r ON r.poll_id=c.poll_id
 WHERE c.commit_id=NEW.commit_id AND c.bytes+length(NEW.body)>r.reserved_bytes)
 THEN RAISE(ABORT,'actual_bytes_exceed_reservation') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ts_invalidation i JOIN tc_channel c ON c.binding_id=i.old_binding
 WHERE i.commit_id=NEW.commit_id AND NOT EXISTS(SELECT 1 FROM tc_retired WHERE channel_id=c.id)
 AND NOT EXISTS(SELECT 1 FROM tc_stop WHERE channel_id=c.id AND invalidation_commit=i.commit_id))
 THEN RAISE(ABORT,'missing_stop') END;
END;
-- 所有附属记录追加后不可修改或删除；完整不可变触发器由build_journal.py投影。
CREATE TRIGGER tc_policy_no_update BEFORE UPDATE ON tc_policy BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_policy_no_delete BEFORE DELETE ON tc_policy BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_source_no_update BEFORE UPDATE ON tc_source BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_source_no_delete BEFORE DELETE ON tc_source BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_channel_no_update BEFORE UPDATE ON tc_channel BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_channel_no_delete BEFORE DELETE ON tc_channel BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_reservation_no_update BEFORE UPDATE ON tc_reservation BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_reservation_no_delete BEFORE DELETE ON tc_reservation BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_frame_no_update BEFORE UPDATE ON tc_frame BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_frame_no_delete BEFORE DELETE ON tc_frame BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_attempt_no_update BEFORE UPDATE ON tc_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_attempt_no_delete BEFORE DELETE ON tc_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_written_no_update BEFORE UPDATE ON tc_written BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_written_no_delete BEFORE DELETE ON tc_written BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_stop_no_update BEFORE UPDATE ON tc_stop BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_stop_no_delete BEFORE DELETE ON tc_stop BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_ack_no_update BEFORE UPDATE ON tc_ack BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_ack_no_delete BEFORE DELETE ON tc_ack BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_retired_no_update BEFORE UPDATE ON tc_retired BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_retired_no_delete BEFORE DELETE ON tc_retired BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_release_no_update BEFORE UPDATE ON tc_release BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_release_no_delete BEFORE DELETE ON tc_release BEGIN SELECT RAISE(ABORT,'immutable'); END;

-- 采集器入站附属设计，须由build_inbox.py与25表源组合；非产品迁移。
CREATE TABLE tc_inbox (
 channel_id TEXT NOT NULL REFERENCES tc_channel(id),
 sequence TEXT NOT NULL CHECK(length(sequence)=20 AND sequence NOT GLOB '*[^0-9]*' AND sequence!='00000000000000000000'),
 message_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN('HELLO','CONFIG_ACK','POLL_ACK','CAPTURE_REPORT','CAPTURE_STATUS','QUERY_COMMIT','STOP_ACK')),
 reply_to TEXT,
 effect TEXT NOT NULL CHECK(effect IN('observation','capture_new','capture_existing','stop_new','stop_existing','query')),
 capture_id TEXT REFERENCES ts_capture(id) DEFERRABLE INITIALLY DEFERRED,
 stop_id TEXT REFERENCES tc_ack(stop_id) DEFERRABLE INITIALLY DEFERRED,
 response_sequence TEXT,
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 65536),
 verification_body BLOB NOT NULL,
 PRIMARY KEY(channel_id,sequence), UNIQUE(channel_id,message_id),
 FOREIGN KEY(channel_id,sequence) REFERENCES tc_inbox_seal(channel_id,sequence) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(channel_id,reply_to) REFERENCES tc_frame(channel_id,message_id),
 FOREIGN KEY(channel_id,response_sequence) REFERENCES tc_frame(channel_id,sequence) DEFERRABLE INITIALLY DEFERRED,
 CHECK((kind IN('HELLO','CAPTURE_REPORT','QUERY_COMMIT') AND reply_to IS NULL) OR
 (kind IN('CONFIG_ACK','POLL_ACK','CAPTURE_STATUS','STOP_ACK') AND reply_to IS NOT NULL)),
 CHECK((effect='observation' AND kind IN('HELLO','CONFIG_ACK','POLL_ACK','CAPTURE_STATUS') AND capture_id IS NULL AND stop_id IS NULL AND response_sequence IS NULL) OR
 (effect IN('capture_new','capture_existing') AND kind IN('CAPTURE_REPORT','CAPTURE_STATUS') AND capture_id IS NOT NULL AND stop_id IS NULL AND response_sequence IS NULL) OR
 (effect IN('stop_new','stop_existing') AND kind='STOP_ACK' AND capture_id IS NULL AND stop_id IS NOT NULL AND response_sequence IS NULL) OR
 (effect='query' AND kind='QUERY_COMMIT' AND capture_id IS NULL AND stop_id IS NULL AND response_sequence IS NOT NULL))
) STRICT;
CREATE UNIQUE INDEX tc_one_capture_origin ON tc_inbox(capture_id) WHERE effect='capture_new';
CREATE UNIQUE INDEX tc_one_ack_origin ON tc_inbox(stop_id) WHERE effect='stop_new';
CREATE UNIQUE INDEX tc_one_hello ON tc_inbox(channel_id) WHERE kind='HELLO';
CREATE TABLE tc_inbox_seal (
 channel_id TEXT NOT NULL, sequence TEXT NOT NULL, result_body BLOB NOT NULL,
 PRIMARY KEY(channel_id,sequence),
 FOREIGN KEY(channel_id,sequence) REFERENCES tc_inbox(channel_id,sequence)
) STRICT;
CREATE TRIGGER tc_inbox_sequence BEFORE INSERT ON tc_inbox BEGIN
 SELECT CASE WHEN coalesce((SELECT max(sequence) FROM tc_inbox WHERE channel_id=NEW.channel_id),'00000000000000000000')='99999999999999999999' OR
 NEW.sequence!=printf('%010d%010d',
 CAST(substr(coalesce((SELECT max(sequence) FROM tc_inbox WHERE channel_id=NEW.channel_id),'00000000000000000000'),1,10) AS INTEGER)+
 (CAST(substr(coalesce((SELECT max(sequence) FROM tc_inbox WHERE channel_id=NEW.channel_id),'00000000000000000000'),11,10) AS INTEGER)=9999999999),
 (CAST(substr(coalesce((SELECT max(sequence) FROM tc_inbox WHERE channel_id=NEW.channel_id),'00000000000000000000'),11,10) AS INTEGER)+1)%10000000000)
 THEN RAISE(ABORT,'inbox_sequence') END;
 SELECT CASE WHEN (NEW.sequence='00000000000000000001')!=(NEW.kind='HELLO') THEN RAISE(ABORT,'hello_first') END;
 -- 一个首次STOP_ACK使用独立保留槽；后续不同序号重复ACK仍计普通预算。
 SELECT CASE WHEN NEW.effect!='stop_new' AND
 (SELECT count(*) FROM tc_inbox WHERE channel_id=NEW.channel_id AND effect!='stop_new')>=(SELECT max_inbox FROM tc_policy)
 THEN RAISE(ABORT,'inbox_capacity') END;
 SELECT CASE WHEN NEW.reply_to IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM tc_frame f JOIN tc_attempt a ON a.channel_id=f.channel_id AND a.sequence=f.sequence
 WHERE f.channel_id=NEW.channel_id AND f.message_id=NEW.reply_to AND f.kind=CASE NEW.kind
 WHEN 'CONFIG_ACK' THEN 'CONFIGURE' WHEN 'POLL_ACK' THEN 'POLL' WHEN 'CAPTURE_STATUS' THEN 'QUERY_CAPTURE' WHEN 'STOP_ACK' THEN 'STOP' END)
 THEN RAISE(ABORT,'inbox_reply') END;
 SELECT CASE WHEN NEW.effect='capture_existing' AND NOT EXISTS(
 SELECT 1 FROM tc_inbox i JOIN tc_inbox_seal z USING(channel_id,sequence)
 WHERE i.channel_id=NEW.channel_id AND i.capture_id=NEW.capture_id AND i.effect='capture_new')
 THEN RAISE(ABORT,'capture_not_committed') END;
 SELECT CASE WHEN NEW.effect='stop_existing' AND NOT EXISTS(
 SELECT 1 FROM tc_inbox i JOIN tc_inbox_seal z USING(channel_id,sequence)
 WHERE i.channel_id=NEW.channel_id AND i.stop_id=NEW.stop_id AND i.effect='stop_new')
 THEN RAISE(ABORT,'ack_not_committed') END;
END;
CREATE TRIGGER tc_outbound_reply BEFORE INSERT ON tc_frame BEGIN
 SELECT CASE WHEN (NEW.kind IN('ACCEPT','REPORT_STORED','COMMIT_STATUS'))!=(NEW.reply_to IS NOT NULL)
 THEN RAISE(ABORT,'outbound_reply_shape') END;
 SELECT CASE WHEN NEW.reply_to IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM tc_inbox i WHERE i.channel_id=NEW.channel_id AND i.message_id=NEW.reply_to AND
 ((NEW.kind='ACCEPT' AND i.kind='HELLO') OR
 (NEW.kind='REPORT_STORED' AND i.kind IN('CAPTURE_REPORT','CAPTURE_STATUS') AND i.effect='capture_new' AND EXISTS(
 SELECT 1 FROM ts_capture c WHERE c.id=i.capture_id AND c.commit_id=NEW.receipt_commit AND c.poll_id=NEW.poll_id)) OR
 (NEW.kind='COMMIT_STATUS' AND i.kind='QUERY_COMMIT' AND i.response_sequence=NEW.sequence)))
 THEN RAISE(ABORT,'outbound_reply_binding') END;
END;
CREATE TRIGGER tc_capture_origin BEFORE INSERT ON ts_capture BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tc_inbox i JOIN tc_reservation r ON r.poll_id=NEW.poll_id
 WHERE i.capture_id=NEW.id AND i.effect='capture_new' AND i.channel_id=r.channel_id AND
 NOT EXISTS(SELECT 1 FROM tc_inbox_seal z WHERE z.channel_id=i.channel_id AND z.sequence=i.sequence))
 THEN RAISE(ABORT,'capture_without_inbox') END;
END;
CREATE TRIGGER tc_ack_origin BEFORE INSERT ON tc_ack BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM tc_inbox i JOIN tc_frame f ON f.channel_id=i.channel_id AND f.message_id=i.reply_to
 WHERE i.stop_id=NEW.stop_id AND i.channel_id=NEW.channel_id AND i.effect='stop_new'
 AND f.stop_id=NEW.stop_id AND f.sequence=NEW.received_through AND
 NOT EXISTS(SELECT 1 FROM tc_inbox_seal z WHERE z.channel_id=i.channel_id AND z.sequence=i.sequence))
 THEN RAISE(ABORT,'ack_without_inbox') END;
END;
CREATE TRIGGER tc_inbox_seal_validate BEFORE INSERT ON tc_inbox_seal BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM tc_inbox i WHERE i.channel_id=NEW.channel_id AND i.sequence=NEW.sequence AND
 ((i.effect IN('capture_new','capture_existing') AND NOT EXISTS(
 SELECT 1 FROM ts_capture c JOIN ts_seal s ON s.commit_id=c.commit_id WHERE c.id=i.capture_id)) OR
 (i.effect IN('stop_new','stop_existing') AND NOT EXISTS(SELECT 1 FROM tc_ack a WHERE a.stop_id=i.stop_id AND a.channel_id=i.channel_id)) OR
 (i.effect='query' AND NOT EXISTS(SELECT 1 FROM tc_frame f WHERE f.channel_id=i.channel_id AND f.sequence=i.response_sequence
 AND f.kind='COMMIT_STATUS' AND f.reply_to=i.message_id))))
 THEN RAISE(ABORT,'inbox_effect_missing') END;
END;
CREATE TRIGGER tc_inbox_no_update BEFORE UPDATE ON tc_inbox BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_inbox_no_delete BEFORE DELETE ON tc_inbox BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_inbox_seal_no_update BEFORE UPDATE ON tc_inbox_seal BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER tc_inbox_seal_no_delete BEFORE DELETE ON tc_inbox_seal BEGIN SELECT RAISE(ABORT,'immutable'); END;
