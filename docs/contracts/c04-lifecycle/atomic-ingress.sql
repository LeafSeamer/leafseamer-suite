-- 独立、不可变封存行；两向延迟外键要求同事务中既有原件又有sealed=1的父记录。
CREATE TABLE ingress_commit_seal(
 commit_id TEXT PRIMARY KEY NOT NULL,
 sealed INTEGER NOT NULL DEFAULT 1 CHECK(sealed=1),
 UNIQUE(commit_id,sealed),
 FOREIGN KEY(commit_id,sealed) REFERENCES ingress_commit(commit_id,sealed) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER ingress_commit_seal_update BEFORE UPDATE ON ingress_commit_seal BEGIN SELECT RAISE(ABORT,'immutable_ingress_seal'); END;
CREATE TRIGGER ingress_commit_seal_delete BEFORE DELETE ON ingress_commit_seal BEGIN SELECT RAISE(ABORT,'immutable_ingress_seal'); END;
