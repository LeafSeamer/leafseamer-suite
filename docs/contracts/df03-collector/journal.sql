-- 设计候选附属布局，必须由build_journal.py与十四表时间源组合；非生产迁移。
CREATE TABLE tc_policy (
 id INTEGER PRIMARY KEY CHECK(id=1), max_sources INTEGER NOT NULL CHECK(max_sources BETWEEN 1 AND 1024),
 max_outstanding INTEGER NOT NULL CHECK(max_outstanding BETWEEN 1 AND 65536),
 max_reserved_bytes INTEGER NOT NULL CHECK(max_reserved_bytes BETWEEN 1 AND 1099511627776),
 max_channels INTEGER NOT NULL CHECK(max_channels BETWEEN 1 AND 65536),
 max_queries INTEGER NOT NULL CHECK(max_queries BETWEEN 0 AND 1024), body BLOB NOT NULL
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
 kind TEXT NOT NULL CHECK(kind IN('ACCEPT','CONFIGURE','POLL','REPORT_STORED','QUERY_POLL','QUERY_COMMIT','STOP')),
 poll_id TEXT, receipt_commit TEXT REFERENCES ts_commit(id), stop_id TEXT REFERENCES tc_stop(id),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 65536),
 PRIMARY KEY(channel_id,sequence), UNIQUE(channel_id,message_id), UNIQUE(channel_id,sequence,stop_id),
 FOREIGN KEY(poll_id,channel_id) REFERENCES tc_reservation(poll_id,channel_id),
 CHECK((kind='POLL' AND poll_id IS NOT NULL AND receipt_commit IS NULL AND stop_id IS NULL) OR
 (kind='REPORT_STORED' AND poll_id IS NOT NULL AND receipt_commit IS NOT NULL AND stop_id IS NULL) OR
 (kind='STOP' AND poll_id IS NULL AND receipt_commit IS NULL AND stop_id IS NOT NULL) OR
 (kind IN('ACCEPT','CONFIGURE','QUERY_POLL','QUERY_COMMIT') AND poll_id IS NULL AND receipt_commit IS NULL AND stop_id IS NULL))
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
 SELECT CASE WHEN NEW.kind IN('QUERY_POLL','QUERY_COMMIT') AND
 (SELECT count(*) FROM tc_frame WHERE channel_id=NEW.channel_id AND kind IN('QUERY_POLL','QUERY_COMMIT'))>=(SELECT max_queries FROM tc_policy)
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
