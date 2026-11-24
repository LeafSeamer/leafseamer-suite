CREATE TABLE linux_deployment_reference_launch (
  generation_id TEXT NOT NULL,
  role TEXT NOT NULL,
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 32768),
  digest TEXT NOT NULL,
  PRIMARY KEY(generation_id,role),
  FOREIGN KEY(generation_id,role) REFERENCES linux_deployment_admission(generation_id,role)
) STRICT;
CREATE TABLE linux_deployment_reference_admission (
  generation_id TEXT NOT NULL,
  role TEXT NOT NULL,
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 32768),
  digest TEXT NOT NULL,
  PRIMARY KEY(generation_id,role),
  FOREIGN KEY(generation_id,role) REFERENCES linux_deployment_reference_launch(generation_id,role)
) STRICT;
CREATE TRIGGER linux_deployment_reference_launch_update BEFORE UPDATE ON linux_deployment_reference_launch
BEGIN SELECT RAISE(ABORT,'linux_deployment_reference_immutable'); END;
CREATE TRIGGER linux_deployment_reference_launch_delete BEFORE DELETE ON linux_deployment_reference_launch
BEGIN SELECT RAISE(ABORT,'linux_deployment_reference_immutable'); END;
CREATE TRIGGER linux_deployment_reference_admission_update BEFORE UPDATE ON linux_deployment_reference_admission
BEGIN SELECT RAISE(ABORT,'linux_deployment_reference_immutable'); END;
CREATE TRIGGER linux_deployment_reference_admission_delete BEFORE DELETE ON linux_deployment_reference_admission
BEGIN SELECT RAISE(ABORT,'linux_deployment_reference_immutable'); END;
CREATE TRIGGER linux_deployment_reference_launch_insert BEFORE INSERT ON linux_deployment_reference_launch
WHEN NOT EXISTS(SELECT 1 FROM linux_deployment_event WHERE serial=(SELECT max(serial) FROM linux_deployment_event)
  AND generation_id=NEW.generation_id AND phase='running')
BEGIN SELECT RAISE(ABORT,'linux_deployment_admission_phase'); END;
CREATE TRIGGER linux_deployment_reference_admission_insert BEFORE INSERT ON linux_deployment_reference_admission
WHEN NOT EXISTS(SELECT 1 FROM linux_deployment_event WHERE serial=(SELECT max(serial) FROM linux_deployment_event)
  AND generation_id=NEW.generation_id AND phase='running')
BEGIN SELECT RAISE(ABORT,'linux_deployment_admission_phase'); END;
