CREATE TABLE sa_observation(
 observation_id TEXT PRIMARY KEY NOT NULL,submission_id TEXT NOT NULL REFERENCES command_submission(submission_id),
 attempt_id TEXT NOT NULL REFERENCES submission_attempt(attempt_id),observation_digest TEXT NOT NULL,
 observation_body BLOB NOT NULL CHECK(json_valid(observation_body)),evidence_body BLOB NOT NULL CHECK(json_valid(evidence_body)),
 result TEXT NOT NULL CHECK(result IN ('accepted','rejected','uncertain')),
 submission_before TEXT NOT NULL,submission_after TEXT NOT NULL,
 step_revision_before TEXT NOT NULL,step_revision_after TEXT NOT NULL,
 step_state_before TEXT NOT NULL,step_state_after TEXT NOT NULL,step_outcome_before TEXT NOT NULL,step_outcome_after TEXT NOT NULL,
 adjudication_id TEXT REFERENCES submission_adjudication(adjudication_id) DEFERRABLE INITIALLY DEFERRED,
 terminal_id TEXT REFERENCES step_terminal(terminal_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(observation_id) REFERENCES sa_commit(observation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE sa_commit(
 observation_id TEXT PRIMARY KEY NOT NULL REFERENCES sa_observation(observation_id),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0),notification_body BLOB NOT NULL CHECK(length(notification_body)>0)
) STRICT;
CREATE TRIGGER sa_prestate BEFORE INSERT ON sa_observation BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM command_submission s JOIN step_state t USING(execution_id,step_id)
 WHERE s.submission_id=NEW.submission_id AND s.attempt_id=NEW.attempt_id AND s.state=NEW.submission_before AND s.state!='planned'
 AND t.revision=NEW.step_revision_before AND t.state=NEW.step_state_before AND t.outcome=NEW.step_outcome_before
 AND json_extract(NEW.observation_body,'$.submission_id')=s.submission_id
 AND json(json_extract(NEW.observation_body,'$.identity.key'))=json(s.request_key_body)
 AND json_extract(NEW.observation_body,'$.identity.request_digest')=s.request_digest)
 THEN RAISE(ABORT,'observation_prestate') END;
END;
CREATE TRIGGER sa_adjudication BEFORE INSERT ON submission_adjudication BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM command_submission s JOIN sa_observation o ON o.submission_id=s.submission_id
 WHERE s.submission_id=NEW.submission_id AND o.observation_id=NEW.observation_id AND o.adjudication_id=NEW.adjudication_id
 AND json(NEW.receipt_body)=json(json_extract(o.observation_body,'$.result.adjudication'))
 AND json(json_extract(NEW.receipt_body,'$.identity.key'))=json(s.request_key_body)
 AND json_extract(NEW.receipt_body,'$.identity.request_digest')=s.request_digest
 AND json_extract(NEW.receipt_body,'$.decision')=NEW.outcome
 AND json_extract(NEW.receipt_ref_body,'$.kind')='request_adjudication'
 AND json_extract(NEW.receipt_ref_body,'$.object_id')=json_extract(NEW.receipt_body,'$.adjudication_id')
 AND json_extract(NEW.receipt_ref_body,'$.digest')=json_extract(NEW.receipt_body,'$.adjudication_digest')
 AND json_extract(NEW.receipt_ref_body,'$.scope.authority_service_id')=s.target_authority
 AND json_extract(NEW.receipt_ref_body,'$.scope.database_instance_id')=s.target_database
 AND (NEW.outcome='rejected' OR json(NEW.command_ref_body)=json(json_extract(NEW.receipt_body,'$.command_ref'))))
 THEN RAISE(ABORT,'typed_adjudication_binding') END;
END;
CREATE UNIQUE INDEX sa_remote_identity ON submission_adjudication(target_authority,target_database,json_extract(receipt_body,'$.adjudication_id'));
CREATE TRIGGER sa_final BEFORE INSERT ON sa_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sa_observation o JOIN command_submission s USING(submission_id) JOIN step_state t USING(execution_id,step_id)
 WHERE o.observation_id=NEW.observation_id AND s.state=o.submission_after AND s.adjudication_id IS o.adjudication_id
 AND t.revision=o.step_revision_after AND t.state=o.step_state_after AND t.outcome=o.step_outcome_after AND t.terminal_id IS o.terminal_id
 AND NOT EXISTS(SELECT 1 FROM step_terminal z WHERE z.terminal_id=o.terminal_id AND z.protection_plan_id IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM sf_commit b WHERE b.plan_id=z.protection_plan_id)))
 THEN RAISE(ABORT,'observation_final') END;
END;
CREATE TRIGGER sa_observation_u BEFORE UPDATE ON sa_observation BEGIN SELECT RAISE(ABORT,'immutable_observation'); END;
CREATE TRIGGER sa_observation_d BEFORE DELETE ON sa_observation BEGIN SELECT RAISE(ABORT,'retain_observation'); END;
CREATE TRIGGER sa_commit_u BEFORE UPDATE ON sa_commit BEGIN SELECT RAISE(ABORT,'immutable_observation_commit'); END;
CREATE TRIGGER sa_commit_d BEFORE DELETE ON sa_commit BEGIN SELECT RAISE(ABORT,'retain_observation_commit'); END;
