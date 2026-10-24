-- 237表保持同一布局；只允许完整公共对象进入新候选的cm/cv正文。
CREATE TRIGGER tv_state BEFORE INSERT ON cm_revision BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controller_scope s WHERE s.singleton=1
 AND json_extract(NEW.state_body,'$.command_id')=NEW.command_id
 AND json_extract(NEW.state_body,'$.scope.authority_service_id')=s.authority_service_id
 AND json_extract(NEW.state_body,'$.scope.database_instance_id')=s.database_instance_id
 AND json_extract(NEW.state_body,'$.revision')=ltrim(NEW.revision,'0')
 AND json_extract(NEW.state_body,'$.phase')=NEW.phase AND json_extract(NEW.state_body,'$.outcome')=NEW.outcome
 AND json_extract(NEW.state_body,'$.effect_status')=NEW.effect_status AND json_extract(NEW.state_body,'$.resource_status')=NEW.resource_status
 AND json_extract(NEW.state_body,'$.automation_continuation')=CASE NEW.paused_latched WHEN 1 THEN 'paused_latched' ELSE 'eligible' END
 AND json_extract(NEW.state_body,'$.terminal_revision') IS ltrim(NEW.terminal_revision,'0')
 AND json_extract(NEW.state_body,'$.resolution_ref.id') IS NEW.resolution_id
 AND json_type(NEW.state_body,'$.attempt_ids')='array' AND json_type(NEW.state_body,'$.completion_evidence_refs')='array'
 AND json_type(NEW.state_body,'$.resource_evidence_refs')='array') THEN RAISE(ABORT,'typed_state_columns') END;
END;
CREATE TRIGGER tv_metadata BEFORE INSERT ON cv_metadata BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ca_command_initial i JOIN ca_request_key k USING(key_id) WHERE i.command_id=NEW.command_id
 AND json_extract(NEW.metadata_body,'$.command_id')=NEW.command_id
 AND json(json_extract(NEW.metadata_body,'$.request_identity.key'))=json(k.request_key_body)
 AND json_extract(NEW.metadata_body,'$.request_identity.request_digest')=k.request_digest
 AND json_extract(NEW.metadata_body,'$.initial_command_ref.digest')=i.command_digest
 AND json_extract(NEW.metadata_body,'$.initial_command_ref.object_id')=i.command_id
 AND json_extract(NEW.metadata_body,'$.actor.principal_id')=json_extract(k.request_key_body,'$.principal_id')
 AND json_extract(NEW.metadata_body,'$.actor.issuer_id')=json_extract(k.request_key_body,'$.issuer_id')
 AND json_extract(NEW.metadata_body,'$.actor.issuer_epoch')=json_extract(k.request_key_body,'$.issuer_epoch')
 AND json_extract(NEW.metadata_body,'$.target.device_id')=k.device_id
 AND json_extract(NEW.metadata_body,'$.target.action_id')=json_extract(k.content_body,'$.action_id')
 AND json_extract(NEW.metadata_body,'$.target.capability_version')=json_extract(k.content_body,'$.capability_version')
 AND json_extract(NEW.metadata_body,'$.origin')=json_extract(k.content_body,'$.origin')
 AND json(json_extract(NEW.metadata_body,'$.automation_binding')) IS json(json_extract(k.content_body,'$.automation_binding'))
 AND json(json_extract(NEW.metadata_body,'$.run_binding')) IS json(json_extract(k.content_body,'$.run_binding'))
 AND json(json_extract(NEW.metadata_body,'$.dispatch'))=json(json_extract(k.content_body,'$.dispatch'))
 AND json(json_extract(NEW.metadata_body,'$.control_binding'))=json(json_extract(k.content_body,'$.expected_control')))
 THEN RAISE(ABORT,'typed_metadata_binding') END;
END;
CREATE TRIGGER tv_publish BEFORE INSERT ON cm_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cv_record v JOIN cm_revision r USING(command_id,revision)
 JOIN cv_metadata m USING(command_id) JOIN cm_policy p USING(command_id) JOIN cv_snapshot s USING(snapshot_id)
 WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision
 AND json_extract(v.record_body,'$.command_id')=v.command_id AND json_extract(v.record_body,'$.revision')=ltrim(v.revision,'0')
 AND json_extract(v.record_body,'$.record_digest')=v.record_digest
 AND json(json_extract(v.record_body,'$.state'))=json(r.state_body)
 AND json_extract(v.record_body,'$.state_ref.id')=v.command_id AND json_extract(v.record_body,'$.state_ref.revision')=ltrim(v.revision,'0')
 AND json_extract(v.record_body,'$.state_ref.digest')=r.state_digest
 AND json(json_extract(v.record_body,'$.policy'))=json(p.policy_body)
 AND json_remove(v.record_body,'$.revision','$.state_ref','$.state','$.completion','$.attempts','$.cancellation','$.evidence_index','$.record_digest','$.policy')=json(m.metadata_body)
 AND json_extract(v.record_body,'$.evidence_index.snapshot_ref.id')=s.snapshot_id
 AND json_extract(v.record_body,'$.evidence_index.snapshot_ref.digest')=s.snapshot_digest
 AND json_extract(v.record_body,'$.evidence_index.total')=CASE s.total WHEN '00000000000000000000' THEN '0' ELSE ltrim(s.total,'0') END
 AND json(json_extract(v.record_body,'$.evidence_index.state_ref'))=json(json_extract(v.record_body,'$.state_ref'))
 AND json_extract(v.record_body,'$.completion.required')=p.required_completion
 AND json(json_extract(v.record_body,'$.completion.policy_ref'))=json(json_extract(p.policy_body,'$.completion_policy_ref'))
 AND json(json_extract(v.record_body,'$.completion.evidence_refs'))=json(json_extract(r.state_body,'$.completion_evidence_refs')))
 THEN RAISE(ABORT,'typed_public_record') END;
 SELECT CASE WHEN EXISTS(SELECT a.attempt_id FROM cm_revision_attempt a WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision
 EXCEPT SELECT json_extract(j.value,'$.attempt_id') FROM cv_record v,json_each(v.record_body,'$.attempts') j WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision)
 OR EXISTS(SELECT json_extract(j.value,'$.attempt_id') FROM cv_record v,json_each(v.record_body,'$.attempts') j WHERE v.command_id=NEW.command_id AND v.revision=NEW.revision
 EXCEPT SELECT a.attempt_id FROM cm_revision_attempt a WHERE a.command_id=NEW.command_id AND a.revision=NEW.revision)
 THEN RAISE(ABORT,'typed_public_attempts') END;
END;
