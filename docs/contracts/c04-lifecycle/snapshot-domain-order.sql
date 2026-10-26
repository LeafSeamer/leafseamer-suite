CREATE TABLE gso_order(
 snapshot_id TEXT PRIMARY KEY NOT NULL REFERENCES go_snapshot(snapshot_id),device_id TEXT NOT NULL,
 ordinal TEXT NOT NULL CHECK(length(ordinal)=20 AND ordinal NOT GLOB '*[^0-9]*' AND ordinal>'00000000000000000000'),
 clock_domain_id TEXT NOT NULL,descriptor_digest TEXT NOT NULL,UNIQUE(device_id,ordinal),
 FOREIGN KEY(snapshot_id) REFERENCES go_snapshot_commit(snapshot_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE gso_transition(
 change_id TEXT PRIMARY KEY NOT NULL REFERENCES ct_change(change_id),digest TEXT NOT NULL,
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 16777216),
 FOREIGN KEY(change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
-- BACKFILL_BOUNDARY
DROP VIEW go_current_snapshot;
CREATE VIEW go_current_snapshot AS SELECT s.* FROM go_snapshot s JOIN go_snapshot_commit k USING(snapshot_id)
 JOIN gso_order o USING(snapshot_id) JOIN ct_current_change c ON c.device_id=s.device_id
 WHERE (o.clock_domain_id,o.descriptor_digest)=(c.clock_domain,c.descriptor)
 AND NOT EXISTS(SELECT 1 FROM gso_order n JOIN go_snapshot_commit nk ON nk.snapshot_id=n.snapshot_id
 WHERE n.device_id=s.device_id AND n.ordinal>o.ordinal);
CREATE TRIGGER gso_order_guard BEFORE INSERT ON gso_order BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM go_snapshot_commit WHERE snapshot_id=NEW.snapshot_id)
 OR NOT EXISTS(SELECT 1 FROM go_snapshot s JOIN ce_exit e ON e.exit_id=s.exit_id WHERE s.snapshot_id=NEW.snapshot_id
 AND s.device_id=NEW.device_id AND e.clock_domain_id=NEW.clock_domain_id AND e.descriptor_digest=NEW.descriptor_digest)
 OR EXISTS(SELECT 1 FROM gso_order WHERE device_id=NEW.device_id AND ordinal='99999999999999999999')
 OR NEW.ordinal!=(SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),(CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
 FROM(SELECT coalesce(max(ordinal),'00000000000000000000') v FROM gso_order WHERE device_id=NEW.device_id))
 THEN RAISE(ABORT,'snapshot_order_binding') END;
END;
CREATE TRIGGER gso_snapshot_order AFTER INSERT ON go_snapshot BEGIN
 INSERT INTO gso_order(snapshot_id,device_id,ordinal,clock_domain_id,descriptor_digest)
 SELECT NEW.snapshot_id,NEW.device_id,
 (SELECT printf('%010d%010d',CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),(CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
 FROM(SELECT coalesce(max(ordinal),'00000000000000000000') v FROM gso_order WHERE device_id=NEW.device_id)),
 e.clock_domain_id,e.descriptor_digest FROM ce_exit e WHERE e.exit_id=NEW.exit_id;
END;
CREATE TRIGGER gso_snapshot_seal BEFORE INSERT ON go_snapshot_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gso_order o JOIN go_snapshot s USING(snapshot_id) JOIN ce_exit e ON e.exit_id=s.exit_id
 WHERE o.snapshot_id=NEW.snapshot_id AND o.device_id=s.device_id AND (o.clock_domain_id,o.descriptor_digest)=(e.clock_domain_id,e.descriptor_digest))
 THEN RAISE(ABORT,'snapshot_order_missing') END;
END;
CREATE TRIGGER gso_domain_change BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_change p ON p.change_id=c.previous_id WHERE c.change_id=NEW.change_id
 AND (c.clock_domain,c.descriptor)!=(p.clock_domain,p.descriptor) AND
 (c.kind!='restart' OR NOT EXISTS(SELECT 1 FROM gso_transition t WHERE t.change_id=c.change_id)
 OR EXISTS(SELECT 1 FROM ct_change old JOIN ct_commit k ON k.change_id=old.change_id
 WHERE old.device_id=c.device_id AND (old.clock_domain,old.descriptor)=(c.clock_domain,c.descriptor))))
 THEN RAISE(ABORT,'protected_domain_transition_required') END;
END;
CREATE TRIGGER gso_transition_guard BEFORE INSERT ON gso_transition BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id)
 OR NOT EXISTS(SELECT 1 FROM ct_change c JOIN ct_change p ON p.change_id=c.previous_id JOIN ct_state s ON s.change_id=c.change_id
 WHERE c.change_id=NEW.change_id AND c.kind='restart' AND s.gate_state='protected'
 AND (c.clock_domain,c.descriptor)!=(p.clock_domain,p.descriptor)
 AND json_extract(CAST(NEW.body AS TEXT),'$.transition_id')=NEW.change_id
 AND json_extract(CAST(NEW.body AS TEXT),'$.transition_digest')=NEW.digest
 AND json_extract(CAST(NEW.body AS TEXT),'$.new_clock_descriptor.clock_domain_id')=c.clock_domain
 AND json_extract(CAST(NEW.body AS TEXT),'$.new_clock_descriptor.descriptor_digest')=c.descriptor)
 THEN RAISE(ABORT,'domain_transition_binding') END;
END;
CREATE TRIGGER gso_order_u BEFORE UPDATE ON gso_order BEGIN SELECT RAISE(ABORT,'immutable_snapshot_order'); END;
CREATE TRIGGER gso_order_d BEFORE DELETE ON gso_order BEGIN SELECT RAISE(ABORT,'immutable_snapshot_order'); END;
CREATE TRIGGER gso_transition_u BEFORE UPDATE ON gso_transition BEGIN SELECT RAISE(ABORT,'immutable_domain_transition'); END;
CREATE TRIGGER gso_transition_d BEFORE DELETE ON gso_transition BEGIN SELECT RAISE(ABORT,'immutable_domain_transition'); END;
