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
