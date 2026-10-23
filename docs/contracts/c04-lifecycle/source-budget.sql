-- source对象可为待启用配置；注册、依赖及正式摄取必须有封存的独享保护额度。
CREATE TABLE sb_reservation(
 source_id TEXT PRIMARY KEY NOT NULL REFERENCES ingress_source(source_id),reservation_id TEXT NOT NULL UNIQUE,
 pool_id INTEGER NOT NULL REFERENCES ib_pool(singleton),profile_digest TEXT NOT NULL,
 source_revision TEXT NOT NULL,source_key_digest TEXT NOT NULL,episodes INTEGER NOT NULL CHECK(episodes BETWEEN 1 AND 65536),
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL CHECK(length(actor_body) BETWEEN 1 AND 512),idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,request_body BLOB NOT NULL CHECK(json_valid(request_body) AND length(request_body)<=4096),
 UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(source_id) REFERENCES sb_commit(source_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(CAST(source_id AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(reservation_id AS BLOB)) BETWEEN 1 AND 128),
 CHECK(length(CAST(request_epoch AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(idempotency_key AS BLOB)) BETWEEN 1 AND 128),
 CHECK(length(profile_digest)=71 AND length(source_key_digest)=71 AND length(request_digest)=71),
 CHECK(length(source_revision) BETWEEN 1 AND 20 AND source_revision NOT GLOB '*[^0-9]*' AND(source_revision='0' OR substr(source_revision,1,1)!='0') AND instr(source_revision,char(0))=0),
 CHECK(length(CAST(json_array(source_id,reservation_id,pool_id,profile_digest,source_revision,source_key_digest,episodes,request_epoch,
 json_object('blob',lower(hex(actor_body))),idempotency_key,request_digest,json_object('blob',lower(hex(request_body)))) AS BLOB))<=8192)
) STRICT;
CREATE TRIGGER sb_reservation_guard BEFORE INSERT ON sb_reservation WHEN NOT EXISTS(
 SELECT 1 FROM ingress_source s JOIN ib_pool p ON p.singleton=NEW.pool_id WHERE s.source_id=NEW.source_id AND s.state='synchronized'
 AND s.revision=NEW.source_revision AND p.profile_digest=NEW.profile_digest AND NEW.episodes<=p.per_source_episodes
 AND NEW.episodes+coalesce((SELECT sum(episodes) FROM sb_reservation),0)<=p.episodes
 AND json_extract(NEW.request_body,'$.contract_version')='source-budget-admission/0.1.0-draft.1'
 AND json_extract(NEW.request_body,'$.source_id') IS NEW.source_id AND json_extract(NEW.request_body,'$.expected_source_revision') IS NEW.source_revision
 AND json_extract(NEW.request_body,'$.source_key_digest') IS NEW.source_key_digest AND json_extract(NEW.request_body,'$.pool_profile_digest') IS NEW.profile_digest
 AND json_extract(NEW.request_body,'$.episodes') IS CAST(NEW.episodes AS TEXT)
 AND json_extract(NEW.request_body,'$.request_epoch') IS NEW.request_epoch AND CAST(json_extract(NEW.request_body,'$.actor') AS BLOB) IS NEW.actor_body
 AND json_extract(NEW.request_body,'$.idempotency_key') IS NEW.idempotency_key)
 OR EXISTS(SELECT 1 FROM ingress_registry WHERE source_id=NEW.source_id)
 BEGIN SELECT RAISE(ABORT,'source_budget_admission_binding_or_capacity'); END;
CREATE TABLE sb_commit(
 source_id TEXT PRIMARY KEY NOT NULL REFERENCES sb_reservation(source_id),reservation_id TEXT NOT NULL UNIQUE,
 request_digest TEXT NOT NULL,registry_revision TEXT NOT NULL CHECK(registry_revision='1'),
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),notification_body BLOB NOT NULL CHECK(length(notification_body) BETWEEN 1 AND 1024),
 FOREIGN KEY(source_id) REFERENCES ingress_registry(source_id),
 CHECK(length(CAST(source_id AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(reservation_id AS BLOB)) BETWEEN 1 AND 128 AND length(request_digest)=71),
 CHECK(length(CAST(json_array(source_id,reservation_id,request_digest,registry_revision,json_object('blob',lower(hex(audit_body))),json_object('blob',lower(hex(notification_body)))) AS BLOB))<=4096)
) STRICT;
CREATE TRIGGER sb_commit_guard BEFORE INSERT ON sb_commit WHEN NOT EXISTS(
 SELECT 1 FROM sb_reservation b JOIN ingress_source s USING(source_id) JOIN ingress_registry r USING(source_id) JOIN ib_pool p ON p.singleton=b.pool_id
 WHERE b.source_id=NEW.source_id AND b.reservation_id=NEW.reservation_id AND b.request_digest=NEW.request_digest
 AND r.revision=NEW.registry_revision AND s.revision=b.source_revision AND s.state='synchronized' AND p.profile_digest=b.profile_digest
 AND NOT EXISTS(SELECT 1 FROM ib_use WHERE source_id=b.source_id))
 BEGIN SELECT RAISE(ABORT,'source_budget_admission_seal'); END;
CREATE VIEW sb_balance AS SELECT b.source_id,b.reservation_id,b.episodes-count(u.plan_id) AS episodes_left,count(u.plan_id) AS episodes_spent
 FROM sb_reservation b JOIN sb_commit k USING(source_id) LEFT JOIN ib_use u USING(source_id) GROUP BY b.source_id;
CREATE VIEW sb_unallocated AS SELECT p.singleton,p.episodes-coalesce(sum(b.episodes),0) AS unallocated_episodes
 FROM ib_pool p LEFT JOIN sb_reservation b ON b.pool_id=p.singleton GROUP BY p.singleton;
CREATE VIEW sb_run_eligible AS SELECT r.run_id FROM run r WHERE NOT EXISTS(
 SELECT 1 FROM p1_dependency d WHERE d.run_id=r.run_id AND NOT EXISTS(SELECT 1 FROM sb_balance b WHERE b.source_id=d.source_id AND b.episodes_left>0));
CREATE TRIGGER sb_use_guard BEFORE INSERT ON ib_use WHEN NOT EXISTS(
 SELECT 1 FROM sb_reservation b JOIN sb_commit k USING(source_id) WHERE b.source_id=NEW.source_id AND b.pool_id=NEW.pool_id
 AND b.profile_digest=NEW.profile_digest AND NEW.source_ordinal<=b.episodes
 -- 来源准入三行的固定上界也占本份包络，不能把预留元数据当免费。
 AND NEW.observed_rows+3<=NEW.logical_rows AND NEW.observed_bytes+14336<=NEW.logical_bytes)
 BEGIN SELECT RAISE(ABORT,'source_budget_not_reserved_or_exhausted'); END;
CREATE TRIGGER sb_ingress_guard BEFORE INSERT ON ingress_commit WHEN NOT EXISTS(
 SELECT 1 FROM ingress_inbox i JOIN sb_balance b USING(source_id) WHERE i.inbox_id=NEW.inbox_id AND b.episodes_left>0)
 BEGIN SELECT RAISE(ABORT,'source_budget_ingress_unavailable'); END;
