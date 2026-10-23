-- 内部候选：限额为模拟普通存储分区，不向保护池借额度，也不退款。
CREATE TABLE rs_limit(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),purpose TEXT NOT NULL CHECK(purpose='simulation'),
 max_transitions INTEGER NOT NULL CHECK(max_transitions BETWEEN 3 AND 65536),
 max_deltas INTEGER NOT NULL CHECK(max_deltas BETWEEN 1 AND 4096),
 CHECK(max_deltas+2<=max_transitions)
) STRICT;
CREATE TRIGGER rs_limit_initial BEFORE INSERT ON rs_limit WHEN EXISTS(SELECT 1 FROM rs_transition)
 BEGIN SELECT RAISE(ABORT,'resync_limit_already_used'); END;
CREATE TABLE rs_transition(
 transition_id TEXT PRIMARY KEY NOT NULL,baseline_id TEXT NOT NULL REFERENCES rs_transition(transition_id),
 source_id TEXT NOT NULL REFERENCES ingress_source(source_id),fault_id TEXT NOT NULL REFERENCES p1_fault(fault_id),
 kind TEXT NOT NULL CHECK(kind IN ('baseline','delta','ready')),
 revision_before TEXT NOT NULL,revision_after TEXT NOT NULL,state_before TEXT NOT NULL,state_after TEXT NOT NULL,
 sequence_before TEXT NOT NULL,sequence_after TEXT NOT NULL,floor_before TEXT NOT NULL,floor_after TEXT NOT NULL,
 request_epoch TEXT NOT NULL,actor_body BLOB NOT NULL CHECK(length(actor_body) BETWEEN 1 AND 512),idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(length(request_digest)=71),request_body BLOB NOT NULL CHECK(json_valid(request_body) AND length(request_body)<=4096),
 UNIQUE(source_id,revision_before),UNIQUE(request_epoch,actor_body,idempotency_key),
 FOREIGN KEY(transition_id) REFERENCES rs_commit(transition_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(CAST(transition_id AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(baseline_id AS BLOB)) BETWEEN 1 AND 128),
 CHECK(length(CAST(source_id AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(fault_id AS BLOB)) BETWEEN 1 AND 128),
 CHECK(length(CAST(request_epoch AS BLOB)) BETWEEN 1 AND 128 AND length(CAST(idempotency_key AS BLOB)) BETWEEN 1 AND 128),
 CHECK((kind='baseline' AND transition_id=baseline_id AND state_before='desynchronized' AND state_after='baseline_required')
 OR(kind='delta' AND transition_id!=baseline_id AND state_before='baseline_required' AND state_after='baseline_required' AND floor_after=floor_before)
 OR(kind='ready' AND transition_id!=baseline_id AND state_before='baseline_required' AND state_after='synchronized' AND floor_after=floor_before AND sequence_after=sequence_before)),
 CHECK(length(CAST(json_array(transition_id,baseline_id,source_id,fault_id,kind,revision_before,revision_after,state_before,state_after,sequence_before,sequence_after,floor_before,floor_after,
 request_epoch,json_object('blob',lower(hex(actor_body))),idempotency_key,request_digest,json_object('blob',lower(hex(request_body)))) AS BLOB))<=16384)
) STRICT;
CREATE UNIQUE INDEX rs_one_baseline_per_fault ON rs_transition(fault_id) WHERE kind='baseline';
CREATE UNIQUE INDEX rs_one_ready_per_baseline ON rs_transition(baseline_id) WHERE kind='ready';
CREATE UNIQUE INDEX rs_delta_identity ON rs_transition(source_id,json_extract(request_body,'$.event_ref.scope.authority_service_id'),
 json_extract(request_body,'$.event_ref.scope.database_instance_id'),json_extract(request_body,'$.event_ref.id'),json_extract(request_body,'$.event_ref.revision')) WHERE kind='delta';
CREATE TRIGGER rs_transition_guard BEFORE INSERT ON rs_transition WHEN NOT EXISTS(
 SELECT 1 FROM ingress_source s JOIN sb_reservation b USING(source_id) JOIN sb_balance balance USING(source_id)
 JOIN p1_fault f ON f.fault_id=NEW.fault_id JOIN p1_plan p ON p.fault_id=f.fault_id JOIN pb_commit k ON k.plan_id=p.plan_id JOIN ib_use u ON u.plan_id=p.plan_id
 WHERE s.source_id=NEW.source_id AND f.source_id=s.source_id AND balance.episodes_left>0
 AND s.revision=NEW.revision_before AND s.state=NEW.state_before AND s.contiguous_sequence=NEW.sequence_before AND s.reject_floor=NEW.floor_before
 AND json_extract(NEW.request_body,'$.contract_version') IS 'source-resync/0.1.0-draft.1'
 AND json_extract(NEW.request_body,'$.transition_id') IS NEW.transition_id AND json_extract(NEW.request_body,'$.baseline_id') IS NEW.baseline_id
 AND json_extract(NEW.request_body,'$.source_id') IS NEW.source_id AND json_extract(NEW.request_body,'$.fault_id') IS NEW.fault_id
 AND json_extract(NEW.request_body,'$.kind') IS NEW.kind AND json_extract(NEW.request_body,'$.expected_source_revision') IS NEW.revision_before
 AND json_extract(NEW.request_body,'$.source_key_digest') IS b.source_key_digest
 AND json_extract(NEW.request_body,'$.request_epoch') IS NEW.request_epoch AND CAST(json_extract(NEW.request_body,'$.actor') AS BLOB) IS NEW.actor_body
 AND json_extract(NEW.request_body,'$.idempotency_key') IS NEW.idempotency_key
 AND NOT EXISTS(SELECT 1 FROM p1_plan n WHERE n.source_id=s.source_id AND (length(n.source_after),n.source_after COLLATE BINARY)>(length(p.source_after),p.source_after COLLATE BINARY)))
 BEGIN SELECT RAISE(ABORT,'resync_prestate_or_source'); END;
CREATE TRIGGER rs_baseline_guard BEFORE INSERT ON rs_transition WHEN NEW.kind='baseline' AND (
 NOT EXISTS(SELECT 1 FROM p1_plan WHERE fault_id=NEW.fault_id AND source_after=NEW.revision_before)
 OR json_extract(NEW.request_body,'$.watermark') IS NOT NEW.sequence_after OR NEW.floor_after!=NEW.sequence_after
 OR NEW.sequence_after='99999999999999999999'
 OR (length(NEW.sequence_after),NEW.sequence_after COLLATE BINARY)<(length(NEW.sequence_before),NEW.sequence_before COLLATE BINARY)
 OR (length(NEW.floor_after),NEW.floor_after COLLATE BINARY)<(length(NEW.floor_before),NEW.floor_before COLLATE BINARY)
 OR NOT EXISTS(SELECT 1 FROM rs_limit WHERE singleton=1 AND ((SELECT count(*) FROM rs_transition WHERE kind='baseline')+1)*(max_deltas+2)<=max_transitions))
 BEGIN SELECT RAISE(ABORT,'resync_baseline_frontier_or_capacity'); END;
CREATE TRIGGER rs_follow_guard BEFORE INSERT ON rs_transition WHEN NEW.kind IN ('delta','ready') AND NOT EXISTS(
 SELECT 1 FROM rs_transition b JOIN rs_commit k USING(transition_id) JOIN rs_limit l ON l.singleton=1
 WHERE b.transition_id=NEW.baseline_id AND b.kind='baseline' AND b.source_id=NEW.source_id AND b.fault_id=NEW.fault_id
 AND json_extract(b.request_body,'$.delivery_ref') IS json_extract(NEW.request_body,'$.delivery_ref')
 AND NOT EXISTS(SELECT 1 FROM rs_transition t WHERE t.baseline_id=b.transition_id AND t.kind='ready')
 AND ((NEW.kind='delta' AND json_extract(NEW.request_body,'$.source_sequence') IS NEW.sequence_after
 AND (SELECT count(*) FROM rs_transition t WHERE t.baseline_id=b.transition_id AND t.kind='delta')<l.max_deltas)
 OR(NEW.kind='ready' AND json_extract(NEW.request_body,'$.through_sequence') IS NEW.sequence_before
 AND EXISTS(SELECT 1 FROM rs_transition t JOIN rs_commit c USING(transition_id) WHERE t.transition_id=json_extract(NEW.request_body,'$.last_delta_id')
 AND t.baseline_id=b.transition_id AND t.kind='delta' AND t.revision_after=NEW.revision_before AND t.sequence_after=NEW.sequence_before))))
 BEGIN SELECT RAISE(ABORT,'resync_continuity_or_capacity'); END;
CREATE TRIGGER rs_source_transition BEFORE UPDATE ON ingress_source WHEN (
 NEW.state='baseline_required' OR(NEW.state='synchronized' AND OLD.state!='synchronized')
 OR NEW.reject_floor!=OLD.reject_floor OR(OLD.state!='synchronized' AND NEW.contiguous_sequence!=OLD.contiguous_sequence))
 AND NOT EXISTS(SELECT 1 FROM rs_transition t WHERE t.source_id=OLD.source_id AND t.revision_before=OLD.revision AND t.revision_after=NEW.revision
 AND t.state_before=OLD.state AND t.state_after=NEW.state AND t.sequence_before=OLD.contiguous_sequence AND t.sequence_after=NEW.contiguous_sequence
 AND t.floor_before=OLD.reject_floor AND t.floor_after=NEW.reject_floor AND NOT EXISTS(SELECT 1 FROM rs_commit k WHERE k.transition_id=t.transition_id))
 BEGIN SELECT RAISE(ABORT,'resync_transition_required'); END;
CREATE TABLE rs_commit(
 transition_id TEXT PRIMARY KEY NOT NULL REFERENCES rs_transition(transition_id),request_digest TEXT NOT NULL CHECK(length(request_digest)=71),
 audit_body BLOB NOT NULL CHECK(length(audit_body) BETWEEN 1 AND 1024),notification_body BLOB NOT NULL CHECK(length(notification_body) BETWEEN 1 AND 1024)
) STRICT;
CREATE TRIGGER rs_commit_guard BEFORE INSERT ON rs_commit WHEN NOT EXISTS(
 SELECT 1 FROM rs_transition t JOIN ingress_source s USING(source_id) WHERE t.transition_id=NEW.transition_id AND t.request_digest=NEW.request_digest
 AND s.revision=t.revision_after AND s.state=t.state_after AND s.contiguous_sequence=t.sequence_after AND s.reject_floor=t.floor_after)
 BEGIN SELECT RAISE(ABORT,'resync_commit_projection'); END;

-- 保留recovery准备的execution限制，将已有提交条件前移至完整计划封存，避免先发出部分动作。
CREATE TRIGGER rs_plan_preparation BEFORE UPDATE ON execution_plan_set WHEN NEW.sealed=1 AND EXISTS(
 SELECT 1 FROM execution_step_plan a JOIN execution e USING(execution_id) WHERE a.execution_id=NEW.execution_id AND a.kind='action'
 AND NOT EXISTS(SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id)
 WHERE p.run_id=e.run_id AND p.generation=e.arm_generation AND(p.execution_id IS NULL OR p.execution_id=e.execution_id)
 AND p.controller_authority=json_extract(a.plan_body,'$.controller_scope.authority_service_id')
 AND p.controller_database=json_extract(a.plan_body,'$.controller_scope.database_instance_id') AND q.qualification='observed_applied'))
 BEGIN SELECT RAISE(ABORT,'resync_plan_target_unprepared'); END;
-- 来源变绿不证明Controller关闭。每个来源对该run的最新P1仍须有当前applied观察。
CREATE VIEW rs_pending_protection AS SELECT r.run_id,p.source_id,p.plan_id FROM p1_run r JOIN p1_plan p USING(plan_id)
 JOIN sp_observed_summary s USING(plan_id) WHERE s.observed_state!='applied' AND NOT EXISTS(
 SELECT 1 FROM p1_run nr JOIN p1_plan np USING(plan_id) WHERE nr.run_id=r.run_id AND np.source_id=p.source_id
 AND(length(np.source_after),np.source_after COLLATE BINARY)>(length(p.source_after),p.source_after COLLATE BINARY));
CREATE TRIGGER rs_recovery_start BEFORE INSERT ON execution_start WHEN EXISTS(SELECT 1 FROM rs_pending_protection WHERE run_id=NEW.run_id)
 BEGIN SELECT RAISE(ABORT,'resync_protection_not_observed'); END;
