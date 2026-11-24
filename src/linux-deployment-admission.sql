CREATE TABLE linux_deployment_admission (
  generation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('controller','seamer')),
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 32768),
  digest TEXT NOT NULL,
  PRIMARY KEY(generation_id,role)
) STRICT;
CREATE TRIGGER linux_deployment_admission_update BEFORE UPDATE ON linux_deployment_admission
BEGIN SELECT RAISE(ABORT,'linux_deployment_admission_immutable'); END;
CREATE TRIGGER linux_deployment_admission_delete BEFORE DELETE ON linux_deployment_admission
BEGIN SELECT RAISE(ABORT,'linux_deployment_admission_immutable'); END;
CREATE TRIGGER linux_deployment_admission_insert BEFORE INSERT ON linux_deployment_admission
WHEN NOT EXISTS(SELECT 1 FROM linux_deployment_event WHERE serial=(SELECT max(serial) FROM linux_deployment_event)
  AND generation_id=NEW.generation_id AND phase='running')
BEGIN SELECT RAISE(ABORT,'linux_deployment_admission_phase'); END;
