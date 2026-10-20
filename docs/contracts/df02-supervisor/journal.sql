-- 监督日志完整物理布局候选，非已批准生产迁移；仅由离线内存检查器加载。
-- BODY/摘要/OS证据的真实性由JOURNAL.md的可信事务提供者核验。
PRAGMA foreign_keys=ON;
PRAGMA recursive_triggers=ON;

CREATE TABLE journal_meta (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 format_version TEXT NOT NULL CHECK(format_version='supervisor-journal/0.1.0-draft.1'),
 host_installation_id TEXT NOT NULL, incarnation_id TEXT NOT NULL UNIQUE,
 storage_profile_digest TEXT NOT NULL
) STRICT;
CREATE TABLE runtime (
 supervisor_id TEXT PRIMARY KEY NOT NULL,
 singleton INTEGER NOT NULL DEFAULT 1 REFERENCES journal_meta(singleton),
 service_id TEXT NOT NULL, runtime_generation TEXT NOT NULL UNIQUE,
 domain_id TEXT NOT NULL UNIQUE, descriptor_digest TEXT NOT NULL, descriptor_jcs BLOB NOT NULL,
 protected_policy_digest TEXT NOT NULL, root_group_id TEXT NOT NULL, root_group_generation TEXT NOT NULL,
 root_backend TEXT NOT NULL CHECK(root_backend IN ('windows_job','linux_cgroup_v2','container_runtime')),
 phase TEXT NOT NULL DEFAULT 'active' CHECK(phase IN ('active','closing','retired')),
 domain_retirement_id TEXT,
 UNIQUE(supervisor_id,service_id), UNIQUE(supervisor_id,domain_id),
 FOREIGN KEY(supervisor_id,domain_retirement_id) REFERENCES retirement_evidence(supervisor_id,evidence_id),
 CHECK(phase!='retired' OR domain_retirement_id IS NOT NULL),
 CHECK(domain_retirement_id IS NULL OR phase='retired')
) STRICT;
CREATE TABLE control_scope (
 supervisor_id TEXT PRIMARY KEY NOT NULL,
 service_id TEXT NOT NULL, database_instance_id TEXT NOT NULL, scope_jcs BLOB NOT NULL,
 FOREIGN KEY(supervisor_id,service_id) REFERENCES runtime(supervisor_id,service_id)
) STRICT;
CREATE TABLE fence_snapshot (
 supervisor_id TEXT NOT NULL REFERENCES control_scope(supervisor_id),
 revision TEXT NOT NULL CHECK(length(revision) BETWEEN 1 AND 20 AND revision NOT GLOB '*[^0-9]*' AND (revision='0' OR substr(revision,1,1)!='0') AND instr(revision,char(0))=0),
 snapshot_digest TEXT NOT NULL, snapshot_jcs BLOB NOT NULL,
 item_count INTEGER NOT NULL CHECK(item_count BETWEEN 0 AND 256),
 sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0,1)),
 PRIMARY KEY(supervisor_id,revision)
) STRICT;
CREATE TABLE fence_item (
 supervisor_id TEXT NOT NULL, revision TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 0 AND 255),
 launch_id TEXT NOT NULL, intent_digest TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('allow','deny')),
 PRIMARY KEY(supervisor_id,revision,launch_id), UNIQUE(supervisor_id,revision,ordinal),
 FOREIGN KEY(supervisor_id,revision) REFERENCES fence_snapshot(supervisor_id,revision)
) STRICT;
CREATE TABLE launch_deny (
 supervisor_id TEXT NOT NULL, launch_id TEXT NOT NULL, intent_digest TEXT NOT NULL, first_revision TEXT NOT NULL,
 PRIMARY KEY(supervisor_id,launch_id),
 FOREIGN KEY(supervisor_id,first_revision,launch_id) REFERENCES fence_item(supervisor_id,revision,launch_id)
) STRICT;
CREATE TABLE current_fence (
 supervisor_id TEXT PRIMARY KEY NOT NULL REFERENCES control_scope(supervisor_id),
 revision TEXT NOT NULL,
 FOREIGN KEY(supervisor_id,revision) REFERENCES fence_snapshot(supervisor_id,revision)
) STRICT;
CREATE TABLE launch_intent (
 supervisor_id TEXT NOT NULL REFERENCES runtime(supervisor_id), launch_id TEXT NOT NULL,
 intent_digest TEXT NOT NULL, intent_jcs BLOB NOT NULL,
 member_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('core','time_provider','worker')),
 group_id TEXT NOT NULL, group_generation TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('protected_config','extension')),
 origin_binding_jcs BLOB NOT NULL,
 PRIMARY KEY(supervisor_id,launch_id), UNIQUE(supervisor_id,launch_id,intent_digest),
 UNIQUE(supervisor_id,member_id), UNIQUE(supervisor_id,group_id,group_generation),
 CHECK((role='worker')=(origin='extension')),
 FOREIGN KEY(supervisor_id,launch_id) REFERENCES launch_state(supervisor_id,launch_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE launch_state (
 supervisor_id TEXT NOT NULL, launch_id TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'registered' CHECK(state IN ('registered','creating','awaiting_bootstrap','admitted_closed','retiring','retired','rejected','indeterminate')),
 creation_attempted INTEGER NOT NULL DEFAULT 0 CHECK(creation_attempted IN (0,1)),
 attempt_marker INTEGER GENERATED ALWAYS AS(CASE WHEN creation_attempted=1 THEN 1 ELSE NULL END) STORED,
 admission_id TEXT, retirement_id TEXT,
 PRIMARY KEY(supervisor_id,launch_id), UNIQUE(supervisor_id,launch_id,creation_attempted), UNIQUE(supervisor_id,launch_id,admission_id),
 FOREIGN KEY(supervisor_id,launch_id) REFERENCES launch_intent(supervisor_id,launch_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(supervisor_id,launch_id,attempt_marker) REFERENCES creation_attempt(supervisor_id,launch_id,marker) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(supervisor_id,launch_id,admission_id) REFERENCES admission_receipt(supervisor_id,launch_id,receipt_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(supervisor_id,launch_id,retirement_id) REFERENCES retirement_target(supervisor_id,launch_id,evidence_id),
 CHECK(state NOT IN ('registered','rejected') OR creation_attempted=0),
 CHECK(state NOT IN ('creating','awaiting_bootstrap','admitted_closed','indeterminate') OR creation_attempted=1),
 CHECK(state!='admitted_closed' OR admission_id IS NOT NULL),
 CHECK(admission_id IS NULL OR creation_attempted=1),
 CHECK(state!='retired' OR retirement_id IS NOT NULL),
 CHECK(retirement_id IS NULL OR state='retired')
) STRICT;
CREATE TABLE creation_attempt (
 supervisor_id TEXT NOT NULL, launch_id TEXT NOT NULL, marker INTEGER NOT NULL DEFAULT 1 CHECK(marker=1),
 fence_revision TEXT, authorization_jcs BLOB, materialization_observation_id TEXT,
 is_recovery INTEGER NOT NULL CHECK(is_recovery IN (0,1)), recovery_policy_jcs BLOB,
 origin_tick TEXT NOT NULL CHECK(length(origin_tick) BETWEEN 1 AND 20 AND origin_tick NOT GLOB '*[^0-9]*' AND (origin_tick='0' OR substr(origin_tick,1,1)!='0') AND instr(origin_tick,char(0))=0),
 PRIMARY KEY(supervisor_id,launch_id), UNIQUE(supervisor_id,launch_id,marker),
 FOREIGN KEY(supervisor_id,launch_id,marker) REFERENCES launch_state(supervisor_id,launch_id,creation_attempted) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(supervisor_id,fence_revision) REFERENCES fence_snapshot(supervisor_id,revision),
 FOREIGN KEY(supervisor_id,launch_id,materialization_observation_id) REFERENCES os_observation(subject_supervisor_id,subject_launch_id,observation_id),
 CHECK((is_recovery=1)=(recovery_policy_jcs IS NOT NULL))
) STRICT;
CREATE VIEW recovery_attempt AS SELECT * FROM creation_attempt WHERE is_recovery=1;
CREATE TABLE bootstrap_challenge (
 supervisor_id TEXT NOT NULL, launch_id TEXT NOT NULL, bootstrap_id TEXT NOT NULL UNIQUE,
 member_boot_id TEXT NOT NULL UNIQUE, channel_binding_id TEXT NOT NULL UNIQUE,
 issued_tick TEXT NOT NULL CHECK(length(issued_tick) BETWEEN 1 AND 20 AND issued_tick NOT GLOB '*[^0-9]*' AND (issued_tick='0' OR substr(issued_tick,1,1)!='0') AND instr(issued_tick,char(0))=0),
 expires_tick TEXT NOT NULL CHECK(length(expires_tick) BETWEEN 1 AND 20 AND expires_tick NOT GLOB '*[^0-9]*' AND (expires_tick='0' OR substr(expires_tick,1,1)!='0') AND instr(expires_tick,char(0))=0),
 transcript_digest TEXT NOT NULL,
 PRIMARY KEY(supervisor_id,launch_id), UNIQUE(supervisor_id,launch_id,bootstrap_id),
 FOREIGN KEY(supervisor_id,launch_id) REFERENCES creation_attempt(supervisor_id,launch_id),
 CHECK((length(expires_tick),expires_tick COLLATE BINARY)>(length(issued_tick),issued_tick COLLATE BINARY))
) STRICT;
CREATE TABLE os_observation (
 observation_id TEXT PRIMARY KEY NOT NULL,
 subject_supervisor_id TEXT NOT NULL REFERENCES runtime(supervisor_id), subject_launch_id TEXT,
 observer_supervisor_id TEXT NOT NULL REFERENCES runtime(supervisor_id),
 kind TEXT NOT NULL CHECK(kind IN ('materialization','process_instance','group_exit','domain_exit')),
 group_id TEXT NOT NULL, group_generation TEXT NOT NULL,
 observed_tick TEXT NOT NULL CHECK(length(observed_tick) BETWEEN 1 AND 20 AND observed_tick NOT GLOB '*[^0-9]*' AND (observed_tick='0' OR substr(observed_tick,1,1)!='0') AND instr(observed_tick,char(0))=0),
 evidence_jcs BLOB NOT NULL,
 UNIQUE(subject_supervisor_id,subject_launch_id,observation_id), UNIQUE(subject_supervisor_id,observation_id),
 FOREIGN KEY(subject_supervisor_id,subject_launch_id) REFERENCES launch_intent(supervisor_id,launch_id),
 CHECK((kind='domain_exit')=(subject_launch_id IS NULL))
) STRICT;
CREATE TABLE admission_receipt (
 supervisor_id TEXT NOT NULL, launch_id TEXT NOT NULL, receipt_id TEXT NOT NULL UNIQUE, bootstrap_id TEXT NOT NULL,
 process_observation_id TEXT NOT NULL,
 admitted_tick TEXT NOT NULL CHECK(length(admitted_tick) BETWEEN 1 AND 20 AND admitted_tick NOT GLOB '*[^0-9]*' AND (admitted_tick='0' OR substr(admitted_tick,1,1)!='0') AND instr(admitted_tick,char(0))=0),
 receipt_jcs BLOB NOT NULL,
 PRIMARY KEY(supervisor_id,launch_id), UNIQUE(supervisor_id,launch_id,receipt_id),
 FOREIGN KEY(supervisor_id,launch_id,bootstrap_id) REFERENCES bootstrap_challenge(supervisor_id,launch_id,bootstrap_id),
 FOREIGN KEY(supervisor_id,launch_id,process_observation_id) REFERENCES os_observation(subject_supervisor_id,subject_launch_id,observation_id),
 FOREIGN KEY(supervisor_id,launch_id,receipt_id) REFERENCES launch_state(supervisor_id,launch_id,admission_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE retirement_evidence (
 supervisor_id TEXT NOT NULL REFERENCES runtime(supervisor_id), evidence_id TEXT NOT NULL UNIQUE,
 target_scope TEXT NOT NULL CHECK(target_scope IN ('member_group','runtime_domain')), target_launch_id TEXT,
 observer_supervisor_id TEXT NOT NULL REFERENCES runtime(supervisor_id), observation_id TEXT NOT NULL,
 result TEXT NOT NULL CHECK(result IN ('confirmed_empty','unproven')),
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 4096), evidence_jcs BLOB NOT NULL,
 sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0,1)),
 PRIMARY KEY(supervisor_id,evidence_id),
 FOREIGN KEY(supervisor_id,target_launch_id) REFERENCES launch_intent(supervisor_id,launch_id),
 FOREIGN KEY(supervisor_id,observation_id) REFERENCES os_observation(subject_supervisor_id,observation_id),
 CHECK((target_scope='member_group')=(target_launch_id IS NOT NULL))
) STRICT;
CREATE TABLE retirement_target (
 supervisor_id TEXT NOT NULL, launch_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
 PRIMARY KEY(supervisor_id,launch_id,evidence_id),
 FOREIGN KEY(supervisor_id,launch_id) REFERENCES launch_intent(supervisor_id,launch_id),
 FOREIGN KEY(supervisor_id,evidence_id) REFERENCES retirement_evidence(supervisor_id,evidence_id)
) STRICT;
CREATE INDEX launch_phase ON launch_state(supervisor_id,state);
CREATE INDEX retirement_targets_by_evidence ON retirement_target(supervisor_id,evidence_id,launch_id);
CREATE INDEX recovery_window ON creation_attempt(supervisor_id,length(origin_tick),origin_tick COLLATE BINARY) WHERE is_recovery=1;

CREATE TRIGGER runtime_new BEFORE INSERT ON runtime WHEN NEW.phase!='active' OR NEW.domain_retirement_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'initial_runtime'); END;
CREATE TRIGGER snapshot_new BEFORE INSERT ON fence_snapshot WHEN NEW.sealed!=0
BEGIN SELECT RAISE(ABORT,'snapshot_must_start_draft'); END;
CREATE TRIGGER item_draft BEFORE INSERT ON fence_item
WHEN NOT EXISTS(SELECT 1 FROM fence_snapshot WHERE supervisor_id=NEW.supervisor_id AND revision=NEW.revision AND sealed=0)
BEGIN SELECT RAISE(ABORT,'snapshot_not_draft'); END;
CREATE TRIGGER snapshot_seal BEFORE UPDATE ON fence_snapshot BEGIN
 SELECT CASE WHEN OLD.sealed!=0 OR NEW.sealed!=1 OR NEW.supervisor_id!=OLD.supervisor_id OR NEW.revision!=OLD.revision
  OR NEW.snapshot_digest!=OLD.snapshot_digest OR NEW.snapshot_jcs!=OLD.snapshot_jcs OR NEW.item_count!=OLD.item_count THEN RAISE(ABORT,'immutable_snapshot') END;
 SELECT CASE WHEN (SELECT phase FROM runtime WHERE supervisor_id=NEW.supervisor_id)!='active' THEN RAISE(ABORT,'runtime_closed') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM current_fence WHERE supervisor_id=NEW.supervisor_id AND
  (length(revision),revision COLLATE BINARY)>=(length(NEW.revision),NEW.revision COLLATE BINARY)) THEN RAISE(ABORT,'fence_not_increasing') END;
 SELECT CASE WHEN (SELECT count(*) FROM fence_item WHERE supervisor_id=NEW.supervisor_id AND revision=NEW.revision)!=NEW.item_count
  OR EXISTS(SELECT 1 FROM fence_item WHERE supervisor_id=NEW.supervisor_id AND revision=NEW.revision AND ordinal>=NEW.item_count) THEN RAISE(ABORT,'item_count') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fence_item a JOIN fence_item b ON a.supervisor_id=b.supervisor_id AND a.revision=b.revision AND a.ordinal<b.ordinal
  WHERE a.supervisor_id=NEW.supervisor_id AND a.revision=NEW.revision AND a.launch_id>=b.launch_id COLLATE BINARY) THEN RAISE(ABORT,'item_order') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM launch_intent l LEFT JOIN launch_state s USING(supervisor_id,launch_id)
  WHERE l.supervisor_id=NEW.supervisor_id AND l.role='worker' AND (s.state IS NULL OR s.state NOT IN ('retired','rejected')) AND NOT EXISTS(
   SELECT 1 FROM fence_item i WHERE i.supervisor_id=l.supervisor_id AND i.revision=NEW.revision AND i.launch_id=l.launch_id AND i.intent_digest=l.intent_digest)) THEN RAISE(ABORT,'live_coverage') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fence_item i JOIN launch_intent l USING(supervisor_id,launch_id) LEFT JOIN launch_state s USING(supervisor_id,launch_id)
  WHERE i.supervisor_id=NEW.supervisor_id AND i.revision=NEW.revision AND (l.role!='worker' OR i.intent_digest!=l.intent_digest OR (i.disposition='allow' AND s.state IN ('retiring','retired','rejected','indeterminate')))) THEN RAISE(ABORT,'known_intent') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM fence_item i JOIN launch_deny d USING(supervisor_id,launch_id)
  WHERE i.supervisor_id=NEW.supervisor_id AND i.revision=NEW.revision AND (i.disposition='allow' OR i.intent_digest!=d.intent_digest)) THEN RAISE(ABORT,'permanent_deny') END;
END;
CREATE TRIGGER deny_source BEFORE INSERT ON launch_deny WHEN NOT EXISTS(
 SELECT 1 FROM fence_item i JOIN fence_snapshot f USING(supervisor_id,revision)
 WHERE i.supervisor_id=NEW.supervisor_id AND i.revision=NEW.first_revision AND i.launch_id=NEW.launch_id AND i.intent_digest=NEW.intent_digest AND i.disposition='deny' AND f.sealed=1)
BEGIN SELECT RAISE(ABORT,'deny_source'); END;
CREATE TRIGGER snapshot_publish AFTER UPDATE OF sealed ON fence_snapshot WHEN NEW.sealed=1 BEGIN
 INSERT INTO launch_deny SELECT supervisor_id,launch_id,intent_digest,revision FROM fence_item
  WHERE supervisor_id=NEW.supervisor_id AND revision=NEW.revision AND disposition='deny' ON CONFLICT(supervisor_id,launch_id) DO NOTHING;
 INSERT INTO current_fence VALUES(NEW.supervisor_id,NEW.revision) ON CONFLICT(supervisor_id) DO UPDATE SET revision=excluded.revision;
END;
CREATE TRIGGER pointer_insert BEFORE INSERT ON current_fence WHEN NOT EXISTS(
 SELECT 1 FROM fence_snapshot WHERE supervisor_id=NEW.supervisor_id AND revision=NEW.revision AND sealed=1)
BEGIN SELECT RAISE(ABORT,'pointer_unsealed'); END;
CREATE TRIGGER pointer_update BEFORE UPDATE ON current_fence WHEN NEW.supervisor_id!=OLD.supervisor_id
 OR (length(NEW.revision),NEW.revision COLLATE BINARY)<=(length(OLD.revision),OLD.revision COLLATE BINARY)
 OR NOT EXISTS(SELECT 1 FROM fence_snapshot WHERE supervisor_id=NEW.supervisor_id AND revision=NEW.revision AND sealed=1)
BEGIN SELECT RAISE(ABORT,'pointer_not_increasing'); END;
CREATE TRIGGER register_launch BEFORE INSERT ON launch_intent BEGIN
 SELECT CASE WHEN (SELECT phase FROM runtime WHERE supervisor_id=NEW.supervisor_id)!='active' THEN RAISE(ABORT,'runtime_closed') END;
 SELECT CASE WHEN NEW.role='worker' AND NOT EXISTS(SELECT 1 FROM current_fence f JOIN fence_item i USING(supervisor_id,revision)
  WHERE i.supervisor_id=NEW.supervisor_id AND i.launch_id=NEW.launch_id AND i.intent_digest=NEW.intent_digest AND i.disposition='allow') THEN RAISE(ABORT,'no_current_allow') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM launch_deny WHERE supervisor_id=NEW.supervisor_id AND launch_id=NEW.launch_id) THEN RAISE(ABORT,'permanent_deny') END;
END;
CREATE TRIGGER state_new BEFORE INSERT ON launch_state WHEN NEW.state!='registered' OR NEW.creation_attempted!=0 OR NEW.admission_id IS NOT NULL OR NEW.retirement_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'initial_state'); END;
CREATE TRIGGER attempt_new BEFORE INSERT ON creation_attempt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM launch_state s JOIN runtime r USING(supervisor_id) WHERE s.supervisor_id=NEW.supervisor_id AND s.launch_id=NEW.launch_id AND s.state='registered' AND s.creation_attempted=0 AND r.phase='active') THEN RAISE(ABORT,'attempt_not_registered') END;
 SELECT CASE WHEN (SELECT role FROM launch_intent WHERE supervisor_id=NEW.supervisor_id AND launch_id=NEW.launch_id)='worker' AND (
  NEW.authorization_jcs IS NULL OR NEW.materialization_observation_id IS NULL OR NOT EXISTS(SELECT 1 FROM current_fence f JOIN fence_item i USING(supervisor_id,revision)
   WHERE f.supervisor_id=NEW.supervisor_id AND f.revision=NEW.fence_revision AND i.launch_id=NEW.launch_id AND i.disposition='allow')
  OR NOT EXISTS(SELECT 1 FROM os_observation WHERE observation_id=NEW.materialization_observation_id AND kind='materialization' AND observer_supervisor_id=NEW.supervisor_id)) THEN RAISE(ABORT,'attempt_authority') END;
 SELECT CASE WHEN (SELECT role FROM launch_intent WHERE supervisor_id=NEW.supervisor_id AND launch_id=NEW.launch_id)!='worker'
  AND (NEW.fence_revision IS NOT NULL OR NEW.authorization_jcs IS NOT NULL OR NEW.materialization_observation_id IS NOT NULL) THEN RAISE(ABORT,'protected_not_extension') END;
END;
CREATE TRIGGER challenge_new BEFORE INSERT ON bootstrap_challenge WHEN NOT EXISTS(
 SELECT 1 FROM launch_state WHERE supervisor_id=NEW.supervisor_id AND launch_id=NEW.launch_id AND state='awaiting_bootstrap' AND creation_attempted=1)
BEGIN SELECT RAISE(ABORT,'challenge_state'); END;
CREATE TRIGGER observation_binding BEFORE INSERT ON os_observation BEGIN
 SELECT CASE WHEN NEW.subject_launch_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM launch_intent WHERE supervisor_id=NEW.subject_supervisor_id AND launch_id=NEW.subject_launch_id AND group_id=NEW.group_id AND group_generation=NEW.group_generation) THEN RAISE(ABORT,'observation_group') END;
 SELECT CASE WHEN NEW.subject_launch_id IS NULL AND NOT EXISTS(SELECT 1 FROM runtime WHERE supervisor_id=NEW.subject_supervisor_id AND root_group_id=NEW.group_id AND root_group_generation=NEW.group_generation) THEN RAISE(ABORT,'observation_root') END;
END;
CREATE TRIGGER admission_new BEFORE INSERT ON admission_receipt BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM launch_state WHERE supervisor_id=NEW.supervisor_id AND launch_id=NEW.launch_id AND state='awaiting_bootstrap') THEN RAISE(ABORT,'admission_state') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM os_observation WHERE observation_id=NEW.process_observation_id AND kind='process_instance' AND observer_supervisor_id=NEW.supervisor_id) THEN RAISE(ABORT,'admission_observation') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM bootstrap_challenge WHERE supervisor_id=NEW.supervisor_id AND launch_id=NEW.launch_id AND bootstrap_id=NEW.bootstrap_id
  AND (length(issued_tick),issued_tick COLLATE BINARY)<=(length(NEW.admitted_tick),NEW.admitted_tick COLLATE BINARY)
  AND (length(expires_tick),expires_tick COLLATE BINARY)>(length(NEW.admitted_tick),NEW.admitted_tick COLLATE BINARY)) THEN RAISE(ABORT,'admission_window') END;
END;
CREATE TRIGGER retirement_new BEFORE INSERT ON retirement_evidence WHEN NEW.sealed!=0
BEGIN SELECT RAISE(ABORT,'retirement_must_start_draft'); END;
CREATE TRIGGER retirement_target_new BEFORE INSERT ON retirement_target WHEN NOT EXISTS(
 SELECT 1 FROM retirement_evidence WHERE supervisor_id=NEW.supervisor_id AND evidence_id=NEW.evidence_id AND sealed=0)
BEGIN SELECT RAISE(ABORT,'retirement_not_draft'); END;
CREATE TRIGGER retirement_seal BEFORE UPDATE ON retirement_evidence BEGIN
 SELECT CASE WHEN OLD.sealed!=0 OR NEW.sealed!=1 OR NEW.supervisor_id!=OLD.supervisor_id OR NEW.evidence_id!=OLD.evidence_id OR NEW.target_scope!=OLD.target_scope
  OR NEW.target_launch_id IS NOT OLD.target_launch_id OR NEW.observer_supervisor_id!=OLD.observer_supervisor_id OR NEW.observation_id!=OLD.observation_id
  OR NEW.result!=OLD.result OR NEW.target_count!=OLD.target_count OR NEW.evidence_jcs!=OLD.evidence_jcs THEN RAISE(ABORT,'immutable_retirement') END;
 SELECT CASE WHEN (SELECT count(*) FROM retirement_target WHERE supervisor_id=NEW.supervisor_id AND evidence_id=NEW.evidence_id)!=NEW.target_count THEN RAISE(ABORT,'retirement_count') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM os_observation WHERE observation_id=NEW.observation_id AND observer_supervisor_id=NEW.observer_supervisor_id AND
  ((NEW.target_scope='runtime_domain' AND kind='domain_exit') OR (NEW.target_scope='member_group' AND kind='group_exit' AND subject_launch_id=NEW.target_launch_id))) THEN RAISE(ABORT,'retirement_observation') END;
 SELECT CASE WHEN NEW.target_scope='member_group' AND (NEW.target_count!=1 OR NOT EXISTS(SELECT 1 FROM retirement_target WHERE supervisor_id=NEW.supervisor_id AND evidence_id=NEW.evidence_id AND launch_id=NEW.target_launch_id)
  OR NOT EXISTS(SELECT 1 FROM launch_state WHERE supervisor_id=NEW.supervisor_id AND launch_id=NEW.target_launch_id AND state IN ('retiring','retired','rejected'))) THEN RAISE(ABORT,'member_retirement') END;
 SELECT CASE WHEN NEW.target_scope='runtime_domain' AND ((SELECT phase FROM runtime WHERE supervisor_id=NEW.supervisor_id) NOT IN ('closing','retired')
  OR EXISTS(SELECT launch_id FROM launch_intent WHERE supervisor_id=NEW.supervisor_id EXCEPT SELECT launch_id FROM retirement_target WHERE supervisor_id=NEW.supervisor_id AND evidence_id=NEW.evidence_id)) THEN RAISE(ABORT,'domain_retirement') END;
END;
CREATE TRIGGER state_update BEFORE UPDATE ON launch_state BEGIN
 SELECT CASE WHEN NEW.supervisor_id!=OLD.supervisor_id OR NEW.launch_id!=OLD.launch_id OR NEW.creation_attempted<OLD.creation_attempted
  OR (OLD.admission_id IS NOT NULL AND NEW.admission_id IS NOT OLD.admission_id) OR (OLD.retirement_id IS NOT NULL AND NEW.retirement_id IS NOT OLD.retirement_id) THEN RAISE(ABORT,'immutable_state_identity') END;
 SELECT CASE WHEN NEW.state!=OLD.state AND NOT (
  (OLD.state='registered' AND NEW.state IN ('creating','retiring','rejected')) OR
  (OLD.state='creating' AND NEW.state IN ('awaiting_bootstrap','indeterminate','retiring')) OR
  (OLD.state='awaiting_bootstrap' AND NEW.state IN ('admitted_closed','indeterminate','retiring')) OR
  (OLD.state='admitted_closed' AND NEW.state IN ('indeterminate','retiring')) OR
  (OLD.state='indeterminate' AND NEW.state='retiring') OR (OLD.state='retiring' AND NEW.state='retired')) THEN RAISE(ABORT,'state_edge') END;
 SELECT CASE WHEN NEW.retirement_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM retirement_evidence WHERE supervisor_id=NEW.supervisor_id AND evidence_id=NEW.retirement_id AND sealed=1 AND result='confirmed_empty') THEN RAISE(ABORT,'retirement_unproven') END;
END;
CREATE TRIGGER runtime_update BEFORE UPDATE ON runtime BEGIN
 SELECT CASE WHEN NEW.supervisor_id!=OLD.supervisor_id OR NEW.singleton!=OLD.singleton OR NEW.service_id!=OLD.service_id OR NEW.runtime_generation!=OLD.runtime_generation
  OR NEW.domain_id!=OLD.domain_id OR NEW.descriptor_digest!=OLD.descriptor_digest OR NEW.descriptor_jcs!=OLD.descriptor_jcs OR NEW.protected_policy_digest!=OLD.protected_policy_digest
  OR NEW.root_group_id!=OLD.root_group_id OR NEW.root_group_generation!=OLD.root_group_generation OR NEW.root_backend!=OLD.root_backend
  OR (OLD.domain_retirement_id IS NOT NULL AND NEW.domain_retirement_id IS NOT OLD.domain_retirement_id) THEN RAISE(ABORT,'immutable_runtime') END;
 SELECT CASE WHEN NEW.phase!=OLD.phase AND NOT ((OLD.phase='active' AND NEW.phase='closing') OR (OLD.phase='closing' AND NEW.phase='retired')) THEN RAISE(ABORT,'runtime_edge') END;
 SELECT CASE WHEN NEW.phase='retired' AND (NOT EXISTS(SELECT 1 FROM retirement_evidence WHERE supervisor_id=NEW.supervisor_id AND evidence_id=NEW.domain_retirement_id AND target_scope='runtime_domain' AND sealed=1 AND result='confirmed_empty')
  OR EXISTS(SELECT 1 FROM launch_state WHERE supervisor_id=NEW.supervisor_id AND state NOT IN ('retired','rejected'))) THEN RAISE(ABORT,'domain_not_retired') END;
END;

-- 不可变证据与墓碑在活动库内不允许更新或删除，归档须离线换incarnation。
CREATE TRIGGER meta_immutable BEFORE UPDATE ON journal_meta BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER meta_keep BEFORE DELETE ON journal_meta BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER runtime_keep BEFORE DELETE ON runtime BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER scope_immutable BEFORE UPDATE ON control_scope BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER scope_keep BEFORE DELETE ON control_scope BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER snapshot_keep BEFORE DELETE ON fence_snapshot BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER item_immutable BEFORE UPDATE ON fence_item BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER item_keep BEFORE DELETE ON fence_item BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER deny_immutable BEFORE UPDATE ON launch_deny BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER deny_keep BEFORE DELETE ON launch_deny BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER pointer_keep BEFORE DELETE ON current_fence BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER intent_immutable BEFORE UPDATE ON launch_intent BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER intent_keep BEFORE DELETE ON launch_intent BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER state_keep BEFORE DELETE ON launch_state BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER attempt_immutable BEFORE UPDATE ON creation_attempt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER attempt_keep BEFORE DELETE ON creation_attempt BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER challenge_immutable BEFORE UPDATE ON bootstrap_challenge BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER challenge_keep BEFORE DELETE ON bootstrap_challenge BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER observation_immutable BEFORE UPDATE ON os_observation BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER observation_keep BEFORE DELETE ON os_observation BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER receipt_immutable BEFORE UPDATE ON admission_receipt BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER receipt_keep BEFORE DELETE ON admission_receipt BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER retirement_keep BEFORE DELETE ON retirement_evidence BEGIN SELECT RAISE(ABORT,'tombstone'); END;
CREATE TRIGGER target_immutable BEFORE UPDATE ON retirement_target BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER target_keep BEFORE DELETE ON retirement_target BEGIN SELECT RAISE(ABORT,'tombstone'); END;
