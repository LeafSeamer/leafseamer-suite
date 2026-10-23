-- 仅供内存设计探针；不是生产迁移或完整领域数据库。
PRAGMA foreign_keys = ON;
CREATE TABLE panel_session (
 session_key TEXT PRIMARY KEY NOT NULL,
 authority_service_id TEXT NOT NULL, database_instance_id TEXT NOT NULL,
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, auth_session_id TEXT NOT NULL,
 panel_session_id TEXT NOT NULL, document_generation TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('active','closing','closed','revoked','expired')),
 revision INTEGER NOT NULL CHECK(revision >= 0),
 lease_revision INTEGER NOT NULL CHECK(lease_revision >= 0),
 hard_tick INTEGER NOT NULL, lease_tick INTEGER NOT NULL CHECK(lease_tick <= hard_tick),
 activation_id TEXT NOT NULL,
 UNIQUE(authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,panel_session_id,document_generation),
 UNIQUE(session_key,authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,panel_session_id,document_generation)
) STRICT;
CREATE TABLE panel_request (
 request_pk TEXT PRIMARY KEY NOT NULL, session_key TEXT NOT NULL,
 authority_service_id TEXT NOT NULL, database_instance_id TEXT NOT NULL,
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, auth_session_id TEXT NOT NULL,
 panel_session_id TEXT NOT NULL, document_generation TEXT NOT NULL, request_id TEXT NOT NULL,
 intent_digest TEXT NOT NULL CHECK(length(intent_digest)=64 AND intent_digest NOT GLOB '*[^0-9a-f]*'),
 activation_id TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending_confirmation','accepted','rejected','cancelled')),
 accepted_result_ref TEXT,
 CHECK((state='accepted' AND accepted_result_ref IS NOT NULL) OR (state<>'accepted' AND accepted_result_ref IS NULL)),
 UNIQUE(authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,panel_session_id,document_generation,request_id),
 UNIQUE(request_pk,session_key), UNIQUE(request_pk,session_key,accepted_result_ref),
 FOREIGN KEY(session_key,authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,panel_session_id,document_generation)
 REFERENCES panel_session(session_key,authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,panel_session_id,document_generation),
 FOREIGN KEY(accepted_result_ref,request_pk,session_key) REFERENCES admission(admission_id,request_pk,session_key) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE admission (
 admission_id TEXT PRIMARY KEY NOT NULL, request_pk TEXT NOT NULL UNIQUE, session_key TEXT NOT NULL,
 UNIQUE(admission_id,request_pk,session_key),
 FOREIGN KEY(request_pk,session_key) REFERENCES panel_request(request_pk,session_key)
) STRICT;
CREATE TABLE confirmation (
 preview_id TEXT PRIMARY KEY NOT NULL, request_pk TEXT NOT NULL UNIQUE, session_key TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('offered','consumed','cancelled','expired','revoked')),
 deadline_tick INTEGER NOT NULL, accepted_result_ref TEXT,
 CHECK((state='consumed' AND accepted_result_ref IS NOT NULL) OR (state<>'consumed' AND accepted_result_ref IS NULL)),
 FOREIGN KEY(request_pk,session_key) REFERENCES panel_request(request_pk,session_key),
 FOREIGN KEY(request_pk,session_key,accepted_result_ref)
 REFERENCES panel_request(request_pk,session_key,accepted_result_ref) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER request_terminal BEFORE UPDATE OF state,accepted_result_ref ON panel_request
 WHEN OLD.state<>'pending_confirmation' AND (NEW.state<>OLD.state OR NEW.accepted_result_ref IS NOT OLD.accepted_result_ref)
 BEGIN SELECT RAISE(ABORT,'terminal_request'); END;
CREATE TRIGGER request_identity BEFORE UPDATE OF session_key,authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,panel_session_id,document_generation,request_id,intent_digest,activation_id ON panel_request
 BEGIN SELECT RAISE(ABORT,'immutable_request'); END;
CREATE TRIGGER preview_terminal BEFORE UPDATE ON confirmation
 WHEN OLD.state<>'offered' BEGIN SELECT RAISE(ABORT,'terminal_preview'); END;
CREATE TRIGGER preview_binding BEFORE UPDATE OF request_pk,session_key,deadline_tick ON confirmation
 BEGIN SELECT RAISE(ABORT,'immutable_preview'); END;
CREATE TABLE lifecycle_operation (
 authority_service_id TEXT NOT NULL, database_instance_id TEXT NOT NULL,
 issuer_id TEXT NOT NULL, issuer_epoch TEXT NOT NULL, auth_session_id TEXT NOT NULL,
 gui_instance_id TEXT NOT NULL, host_operation_id TEXT NOT NULL,
 operation TEXT NOT NULL, content_digest TEXT NOT NULL, session_key TEXT NOT NULL REFERENCES panel_session(session_key),
 committed_lease_revision INTEGER NOT NULL,
 PRIMARY KEY(authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,gui_instance_id,host_operation_id)
) STRICT;
CREATE TABLE close_operation (
 operation_id TEXT PRIMARY KEY NOT NULL, session_key TEXT NOT NULL UNIQUE REFERENCES panel_session(session_key),
 selector_digest TEXT NOT NULL
) STRICT;
CREATE TABLE close_target (
 operation_id TEXT NOT NULL REFERENCES close_operation(operation_id), target_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','acknowledged','indeterminate')),
 PRIMARY KEY(operation_id,target_id)
) STRICT;
CREATE TABLE audit (
 event_id TEXT PRIMARY KEY NOT NULL, event_type TEXT NOT NULL, owner_id TEXT NOT NULL
) STRICT;
CREATE TABLE outbox (
 message_id TEXT PRIMARY KEY NOT NULL, owner_id TEXT NOT NULL, message_type TEXT NOT NULL
) STRICT;
