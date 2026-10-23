-- 资源验证的完整直接来源与取消结果祖先；须与独立占用129表组合。
CREATE TABLE cd_manifest (
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cr_validation(validation_id),
 basis TEXT NOT NULL CHECK(basis IN ('independent','cancel_result')),
 source_count INTEGER NOT NULL CHECK(source_count BETWEEN 0 AND 256),
 manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=71 AND substr(manifest_digest,1,7)='sha256:'
  AND substr(manifest_digest,8) NOT GLOB '*[^0-9a-f]*'),
 manifest_body BLOB NOT NULL CHECK(length(manifest_body)>0),
 CHECK((basis='independent' AND source_count=0) OR (basis='cancel_result' AND source_count>0)),
 FOREIGN KEY(validation_id) REFERENCES cd_manifest_commit(validation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE cd_result_source (
 validation_id TEXT NOT NULL REFERENCES cd_manifest(validation_id),
 result_id TEXT NOT NULL REFERENCES cg_result_commit(result_id),
 result_digest TEXT NOT NULL,
 PRIMARY KEY(validation_id,result_id)
) STRICT;
CREATE TABLE cd_manifest_commit (
 validation_id TEXT PRIMARY KEY NOT NULL REFERENCES cd_manifest(validation_id),
 provider_ref TEXT NOT NULL CHECK(length(provider_ref)>0),
 manifest_digest TEXT NOT NULL,
 receipt_body BLOB NOT NULL CHECK(length(receipt_body)>0),
 audit_body BLOB NOT NULL CHECK(length(audit_body)>0)
) STRICT;
-- 只走实际传输采用的结果，不把计划上的未执行边当作事实依赖。
CREATE VIEW cd_result_ancestor AS
 WITH RECURSIVE ancestry(root_result_id,result_id) AS (
  SELECT result_id,result_id FROM cg_result_commit
  UNION
  SELECT a.root_result_id,d.result_id FROM ancestry a
   JOIN cg_result_member m ON m.result_id=a.result_id
   JOIN cg_dispatch_dependency d ON d.permit_id=m.permit_id
 ) SELECT root_result_id,result_id FROM ancestry;
CREATE VIEW cd_affected_validation AS
 SELECT DISTINCT s.validation_id,a.result_id FROM cd_result_source s
 JOIN cd_result_ancestor a ON a.root_result_id=s.result_id;
DROP VIEW cr_valid_validation;
CREATE VIEW cr_valid_validation AS
 SELECT v.* FROM cr_validation v JOIN cd_manifest_commit k USING(validation_id)
 WHERE NOT EXISTS(SELECT 1 FROM cr_validation_revocation r WHERE r.validation_id=v.validation_id)
 AND NOT EXISTS(SELECT 1 FROM cd_affected_validation a JOIN cg_revocation r USING(result_id)
  WHERE a.validation_id=v.validation_id);
CREATE TRIGGER cd_source_frozen BEFORE INSERT ON cd_result_source
 WHEN EXISTS(SELECT 1 FROM cd_manifest_commit WHERE validation_id=NEW.validation_id)
 BEGIN SELECT RAISE(ABORT,'dependency_manifest_frozen'); END;
CREATE TRIGGER cd_manifest_seal BEFORE INSERT ON cd_manifest_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cd_manifest m JOIN cr_validation v USING(validation_id)
  WHERE m.validation_id=NEW.validation_id AND m.manifest_digest=NEW.manifest_digest
   AND v.provider_ref=NEW.provider_ref AND v.receipt_body=NEW.receipt_body
   AND m.source_count=(SELECT count(*) FROM cd_result_source WHERE validation_id=m.validation_id))
  THEN RAISE(ABORT,'dependency_manifest_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cd_result_source s JOIN cr_validation v USING(validation_id)
  LEFT JOIN cg_valid_success r ON r.result_id=s.result_id
  LEFT JOIN cg_plan p ON p.execution_id=r.execution_id
  LEFT JOIN cv_cancel c ON c.cancellation_id=p.cancellation_id
  LEFT JOIN ce_command cmd ON cmd.command_id=c.command_id
  WHERE s.validation_id=NEW.validation_id AND (r.result_id IS NULL OR s.result_digest!=r.evidence_digest
   OR cmd.device_id!=v.device_id OR (v.command_id IS NOT NULL AND c.command_id!=v.command_id)))
  THEN RAISE(ABORT,'dependency_result_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cd_affected_validation a JOIN cg_revocation r USING(result_id)
  WHERE a.validation_id=NEW.validation_id)
  OR EXISTS(SELECT 1 FROM cr_validation_revocation WHERE validation_id=NEW.validation_id)
  THEN RAISE(ABORT,'dependency_revoked') END;
END;
-- 撤回记录、全部验证失效、既有释放失效和本机保护在同一SQLite事务中。
-- 祖先通过视图一次求闭包；原资源触发链仍须启用recursive_triggers。
CREATE TRIGGER cd_result_revoke AFTER INSERT ON cg_revocation BEGIN
 INSERT OR IGNORE INTO cr_validation_revocation(validation_id,reason_body,audit_body)
 SELECT DISTINCT a.validation_id,NEW.reason_body,NEW.audit_body FROM cd_affected_validation a
 JOIN cd_manifest_commit k USING(validation_id) WHERE a.result_id=NEW.result_id;
END;
