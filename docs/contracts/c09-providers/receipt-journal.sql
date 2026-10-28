PRAGMA application_id = 1280528970;
PRAGMA user_version = 1;
CREATE TABLE journal_scope (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  body BLOB NOT NULL CHECK(typeof(body)='blob' AND length(body) BETWEEN 1 AND 4096)
) STRICT;
CREATE TABLE request_origin (
  identity_key TEXT PRIMARY KEY CHECK(length(identity_key)=64),
  request BLOB NOT NULL CHECK(typeof(request)='blob' AND length(request) BETWEEN 1 AND 65536),
  invocation BLOB NOT NULL CHECK(typeof(invocation)='blob' AND length(invocation) BETWEEN 1 AND 65536)
) STRICT;
CREATE TABLE request_receipt (
  identity_key TEXT NOT NULL REFERENCES request_origin(identity_key),
  ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 64),
  body BLOB NOT NULL CHECK(typeof(body)='blob' AND length(body) BETWEEN 1 AND 65536),
  PRIMARY KEY(identity_key,ordinal)
) STRICT;
CREATE TRIGGER receipt_sequence BEFORE INSERT ON request_receipt
WHEN NEW.ordinal != COALESCE((SELECT MAX(ordinal)+1 FROM request_receipt WHERE identity_key=NEW.identity_key),1)
BEGIN SELECT RAISE(ABORT,'receipt_sequence'); END;
CREATE TRIGGER scope_update BEFORE UPDATE ON journal_scope BEGIN SELECT RAISE(ABORT,'immutable_scope'); END;
CREATE TRIGGER scope_replace BEFORE INSERT ON journal_scope WHEN EXISTS(SELECT 1 FROM journal_scope)
BEGIN SELECT RAISE(ABORT,'immutable_scope'); END;
CREATE TRIGGER scope_delete BEFORE DELETE ON journal_scope BEGIN SELECT RAISE(ABORT,'immutable_scope'); END;
CREATE TRIGGER origin_update BEFORE UPDATE ON request_origin BEGIN SELECT RAISE(ABORT,'immutable_origin'); END;
CREATE TRIGGER origin_replace BEFORE INSERT ON request_origin WHEN EXISTS(SELECT 1 FROM request_origin WHERE identity_key=NEW.identity_key)
BEGIN SELECT RAISE(ABORT,'immutable_origin'); END;
CREATE TRIGGER origin_delete BEFORE DELETE ON request_origin BEGIN SELECT RAISE(ABORT,'immutable_origin'); END;
CREATE TRIGGER receipt_update BEFORE UPDATE ON request_receipt BEGIN SELECT RAISE(ABORT,'immutable_receipt'); END;
CREATE TRIGGER receipt_delete BEFORE DELETE ON request_receipt BEGIN SELECT RAISE(ABORT,'immutable_receipt'); END;
