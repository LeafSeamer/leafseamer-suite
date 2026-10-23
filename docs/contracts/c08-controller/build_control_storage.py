"""控制受理与转交持久化候选；只生成设计SQL，不执行产品迁移。"""
import argparse
from pathlib import Path
import build_protection_outbox as G

HERE=Path(__file__).resolve().parent
TABLES=('ct_change','ct_state','ct_operation','ct_operation_event','ct_attempt',
        'ct_offer','ct_offer_event','ct_request','ct_audit','ct_outbox','ct_commit')
SOURCES=G.SOURCES+[HERE/'build_protection_outbox.py',HERE/'build_control_storage.py']

def counter(name):
    return f"{name} TEXT NOT NULL CHECK(length({name})=20 AND {name} NOT GLOB '*[^0-9]*')"

def successor(v):
    return f"printf('%010d%010d',CAST(substr({v},1,10) AS INTEGER)+(substr({v},11,10)='9999999999'),(CAST(substr({v},11,10) AS INTEGER)+1)%10000000000)"

def principal(prefix,nullable=False):
    return ',\n'.join(f"{prefix}_{n} TEXT"+('' if nullable else ' NOT NULL')+
                     f" CHECK({prefix}_{n} IS NULL OR length({prefix}_{n})>0)" for n in ('issuer','epoch','id'))

def same(a,b):
    return ' AND '.join(f'{a}_{n} IS {b}_{n}' for n in ('issuer','epoch','id'))

def build():
    sql=G.build().decode()+f'''
-- 控制受理148表候选；effective及ready尚未归并，不可部署。
CREATE TABLE ct_change(
 change_id TEXT PRIMARY KEY CHECK(length(change_id)>0),
 scope_id INTEGER NOT NULL CHECK(scope_id=1) REFERENCES controller_scope(singleton),
 device_id TEXT NOT NULL CHECK(length(device_id)>0),
 {counter('sequence')}, previous_id TEXT REFERENCES ct_change(change_id),
 kind TEXT NOT NULL CHECK(kind IN ('bootstrap','offer','accept','acquire','release','cancel','expire','unknown','reject','retry','restart')),
 state_id TEXT REFERENCES ct_state(change_id) DEFERRABLE INITIALLY DEFERRED,
 operation_id TEXT REFERENCES ct_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 offer_id TEXT REFERENCES ct_offer(offer_id) DEFERRABLE INITIALLY DEFERRED,
 request_id TEXT REFERENCES ct_request(change_id) DEFERRABLE INITIALLY DEFERRED,
 clock_domain TEXT NOT NULL CHECK(length(clock_domain)>0),
 descriptor TEXT NOT NULL CHECK(length(descriptor)>0), {counter('now_tick')},
 UNIQUE(device_id,sequence),
 FOREIGN KEY(change_id) REFERENCES ct_commit(change_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(state_id IS CASE WHEN kind IN ('bootstrap','accept','acquire','release','unknown','reject','restart') THEN change_id END),
 CHECK(request_id IS CASE WHEN kind IN ('offer','accept','acquire','release','cancel') THEN change_id END),
 CHECK((operation_id IS NOT NULL)=(kind IN ('accept','acquire','release','unknown','reject','retry'))),
 CHECK((offer_id IS NOT NULL)=(kind IN ('offer','accept','cancel','expire')))
) STRICT;
CREATE TABLE ct_state(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 {counter('record_revision')}, control_epoch TEXT NOT NULL CHECK(length(control_epoch)>0),
 {counter('effective_version')}, {counter('reserved_version')},
 mode TEXT NOT NULL CHECK(mode IN ('automatic','manual')), {principal('holder',True)},
 pending_operation_id TEXT REFERENCES ct_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 gate_state TEXT NOT NULL CHECK(gate_state IN ('protected','fencing')),
 record_digest TEXT NOT NULL CHECK(length(record_digest)>0),
 record_body BLOB NOT NULL CHECK(length(record_body)>0),
 CHECK(effective_version<=reserved_version),
 CHECK((mode='automatic' AND holder_issuer IS NULL AND holder_epoch IS NULL AND holder_id IS NULL) OR
       (mode='manual' AND holder_issuer IS NOT NULL AND holder_epoch IS NOT NULL AND holder_id IS NOT NULL))
) STRICT;
CREATE TABLE ct_operation(
 operation_id TEXT PRIMARY KEY CHECK(length(operation_id)>0),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_change(change_id),
 kind TEXT NOT NULL CHECK(kind IN ('acquire','release','transfer')),
 {principal('requester')}, {principal('target',True)},
 expected_state_id TEXT NOT NULL REFERENCES ct_state(change_id), {counter('target_version')},
 offer_id TEXT UNIQUE REFERENCES ct_offer(offer_id),
 force INTEGER NOT NULL CHECK(force IN (0,1)), reason TEXT NOT NULL CHECK(length(trim(reason))>0),
 CHECK((kind='release' AND target_issuer IS NULL AND target_epoch IS NULL AND target_id IS NULL) OR
       (kind!='release' AND target_issuer IS NOT NULL AND target_epoch IS NOT NULL AND target_id IS NOT NULL)),
 CHECK((offer_id IS NOT NULL)=(kind='transfer'))
) STRICT;
CREATE TABLE ct_attempt(
 attempt_id TEXT PRIMARY KEY CHECK(length(attempt_id)>0),
 operation_id TEXT NOT NULL REFERENCES ct_operation(operation_id),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_change(change_id), {counter('ordinal')},
 UNIQUE(operation_id,ordinal), UNIQUE(attempt_id,operation_id)
) STRICT;
CREATE TABLE ct_operation_event(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 operation_id TEXT NOT NULL REFERENCES ct_operation(operation_id), {counter('revision')},
 state TEXT NOT NULL CHECK(state IN ('pending','indeterminate','rejected')),
 attempt_id TEXT NOT NULL, failure_code TEXT,
 result_digest TEXT NOT NULL CHECK(length(result_digest)>0), result_body BLOB NOT NULL CHECK(length(result_body)>0),
 UNIQUE(operation_id,revision),
 FOREIGN KEY(attempt_id,operation_id) REFERENCES ct_attempt(attempt_id,operation_id),
 CHECK((state='pending' AND failure_code IS NULL) OR (state!='pending' AND failure_code IS NOT NULL AND length(failure_code)>0))
) STRICT;
CREATE TABLE ct_offer(
 offer_id TEXT PRIMARY KEY CHECK(length(offer_id)>0),
 change_id TEXT NOT NULL UNIQUE REFERENCES ct_change(change_id),
 {principal('sender')}, {principal('target')},
 expected_state_id TEXT NOT NULL REFERENCES ct_state(change_id),
 clock_domain TEXT NOT NULL CHECK(length(clock_domain)>0), descriptor TEXT NOT NULL CHECK(length(descriptor)>0),
 {counter('issued_tick')}, {counter('expires_tick')}, reason TEXT NOT NULL CHECK(length(trim(reason))>0),
 CHECK(issued_tick<expires_tick), CHECK(NOT({same('sender','target')}))
) STRICT;
CREATE TABLE ct_offer_event(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 offer_id TEXT NOT NULL REFERENCES ct_offer(offer_id), {counter('revision')},
 state TEXT NOT NULL CHECK(state IN ('offered','accepted','expired','cancelled')),
 accepted_operation_id TEXT UNIQUE REFERENCES ct_operation(operation_id) DEFERRABLE INITIALLY DEFERRED,
 result_digest TEXT NOT NULL CHECK(length(result_digest)>0), result_body BLOB NOT NULL CHECK(length(result_body)>0),
 UNIQUE(offer_id,revision), CHECK((accepted_operation_id IS NOT NULL)=(state='accepted'))
) STRICT;
CREATE TABLE ct_request(
 change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id), {principal('actor')},
 request_epoch TEXT NOT NULL CHECK(length(request_epoch)>0),
 api_operation TEXT NOT NULL CHECK(api_operation IN ('offerTransfer','acceptTransfer','acquireControl','releaseControl','cancelTransfer')),
 idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)>0),
 request_digest TEXT NOT NULL CHECK(length(request_digest)>0), request_body BLOB NOT NULL CHECK(length(request_body)>0),
 result_kind TEXT NOT NULL CHECK(result_kind IN ('control_operation','transfer_offer')),
 initial_result_id TEXT NOT NULL CHECK(length(initial_result_id)>0),
 initial_result_revision TEXT NOT NULL CHECK(length(initial_result_revision)=20 AND initial_result_revision NOT GLOB '*[^0-9]*'),
 initial_result_digest TEXT NOT NULL CHECK(length(initial_result_digest)>0),
 UNIQUE(actor_issuer,actor_epoch,actor_id,request_epoch,api_operation,idempotency_key)
) STRICT;
CREATE TABLE ct_audit(change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 body BLOB NOT NULL CHECK(length(body)>0)) STRICT;
CREATE TABLE ct_outbox(change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 event_id TEXT NOT NULL UNIQUE CHECK(length(event_id)>0), body BLOB NOT NULL CHECK(length(body)>0)) STRICT;
CREATE TABLE ct_commit(change_id TEXT PRIMARY KEY REFERENCES ct_change(change_id),
 FOREIGN KEY(change_id) REFERENCES ct_audit(change_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(change_id) REFERENCES ct_outbox(change_id) DEFERRABLE INITIALLY DEFERRED) STRICT;
CREATE VIEW ct_current_change AS SELECT c.* FROM ct_change c JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM ct_change n JOIN ct_commit nk ON nk.change_id=n.change_id WHERE n.device_id=c.device_id AND n.sequence>c.sequence);
CREATE VIEW ct_current_state AS SELECT s.*,c.device_id FROM ct_state s JOIN ct_change c USING(change_id) JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM ct_state n JOIN ct_change nc ON nc.change_id=n.change_id JOIN ct_commit nk ON nk.change_id=n.change_id
 WHERE nc.device_id=c.device_id AND n.record_revision>s.record_revision);
CREATE VIEW ct_current_operation AS SELECT e.* FROM ct_operation_event e JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM ct_operation_event n JOIN ct_commit nk ON nk.change_id=n.change_id WHERE n.operation_id=e.operation_id AND n.revision>e.revision);
CREATE VIEW ct_current_offer AS SELECT e.* FROM ct_offer_event e JOIN ct_commit k USING(change_id)
 WHERE NOT EXISTS(SELECT 1 FROM ct_offer_event n JOIN ct_commit nk ON nk.change_id=n.change_id WHERE n.offer_id=e.offer_id AND n.revision>e.revision);
CREATE TRIGGER ct_seal BEFORE INSERT ON ct_commit BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND
  ((c.kind='bootstrap' AND c.previous_id IS NULL AND c.sequence='00000000000000000001' AND NOT EXISTS(SELECT 1 FROM ct_current_change p WHERE p.device_id=c.device_id)) OR
   (c.kind!='bootstrap' AND EXISTS(SELECT 1 FROM ct_current_change p WHERE p.change_id=c.previous_id AND p.device_id=c.device_id AND p.sequence<'99999999999999999999' AND c.sequence={successor('p.sequence')})))) THEN RAISE(ABORT,'control_change_cas') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ct_audit a JOIN ct_outbox o USING(change_id) WHERE a.change_id=NEW.change_id) THEN RAISE(ABORT,'control_commit_pair') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c WHERE c.change_id=NEW.change_id AND
  ((SELECT count(*) FROM ct_state WHERE change_id=c.change_id)!=(c.state_id IS NOT NULL) OR
   (SELECT count(*) FROM ct_request WHERE change_id=c.change_id)!=(c.request_id IS NOT NULL) OR
   (SELECT count(*) FROM ct_operation_event WHERE change_id=c.change_id)!=(c.operation_id IS NOT NULL) OR
   (SELECT count(*) FROM ct_operation WHERE change_id=c.change_id)!=(c.kind IN ('acquire','release','accept')) OR
   (SELECT count(*) FROM ct_attempt WHERE change_id=c.change_id)!=(c.kind IN ('acquire','release','accept','retry')) OR
   (SELECT count(*) FROM ct_offer WHERE change_id=c.change_id)!=(c.kind='offer') OR
   (SELECT count(*) FROM ct_offer_event WHERE change_id=c.change_id)!=(c.offer_id IS NOT NULL))) THEN RAISE(ABORT,'control_member_set') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_request q USING(change_id) WHERE c.change_id=NEW.change_id AND
  (q.api_operation!=CASE c.kind WHEN 'offer' THEN 'offerTransfer' WHEN 'accept' THEN 'acceptTransfer' WHEN 'acquire' THEN 'acquireControl' WHEN 'release' THEN 'releaseControl' WHEN 'cancel' THEN 'cancelTransfer' END OR
   NOT ((q.result_kind='control_operation' AND EXISTS(SELECT 1 FROM ct_operation_event e WHERE e.change_id=c.change_id AND e.operation_id=q.initial_result_id AND e.revision=q.initial_result_revision AND e.result_digest=q.initial_result_digest)) OR
        (q.result_kind='transfer_offer' AND EXISTS(SELECT 1 FROM ct_offer_event e WHERE e.change_id=c.change_id AND e.offer_id=q.initial_result_id AND e.revision=q.initial_result_revision AND e.result_digest=q.initial_result_digest))) OR
   (q.result_kind='control_operation')!=(c.kind IN ('acquire','release','accept')))) THEN RAISE(ABORT,'control_receipt_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_state s USING(change_id) WHERE c.change_id=NEW.change_id AND
  ((c.kind='bootstrap' AND (s.record_revision!='00000000000000000001' OR s.pending_operation_id IS NOT NULL OR s.gate_state!='protected')) OR
   (c.kind!='bootstrap' AND NOT EXISTS(SELECT 1 FROM ct_current_state p WHERE p.device_id=c.device_id AND p.record_revision<'99999999999999999999' AND
     s.record_revision={successor('p.record_revision')} AND s.control_epoch=p.control_epoch AND s.effective_version=p.effective_version AND s.mode=p.mode AND {same('s.holder','p.holder')} AND
     ((c.kind IN ('acquire','release','accept') AND p.pending_operation_id IS NULL AND p.reserved_version<'99999999999999999999' AND s.reserved_version={successor('p.reserved_version')} AND s.pending_operation_id IS c.operation_id AND s.gate_state='fencing') OR
      (c.kind IN ('unknown','reject') AND p.pending_operation_id IS c.operation_id AND s.reserved_version=p.reserved_version AND s.pending_operation_id IS CASE WHEN c.kind='unknown' THEN c.operation_id END AND s.gate_state='protected') OR
      (c.kind='restart' AND s.reserved_version=p.reserved_version AND s.pending_operation_id IS p.pending_operation_id AND s.gate_state='protected')))))) THEN RAISE(ABORT,'control_state_transition') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_operation o ON o.change_id=c.change_id JOIN ct_request q ON q.change_id=c.change_id
  WHERE c.change_id=NEW.change_id AND (o.operation_id IS NOT c.operation_id OR o.kind!=CASE c.kind WHEN 'accept' THEN 'transfer' ELSE c.kind END OR NOT({same('o.requester','q.actor')}) OR
  NOT EXISTS(SELECT 1 FROM ct_current_state p JOIN ct_state s ON s.change_id=c.change_id WHERE p.device_id=c.device_id AND o.expected_state_id=p.change_id AND o.target_version=s.reserved_version AND
   ((c.kind='release' AND p.mode='manual' AND {same('o.requester','p.holder')} AND o.force=0) OR
    (c.kind IN ('acquire','accept') AND {same('o.target','o.requester')} AND NOT({same('o.requester','p.holder')}) AND
      (c.kind='accept' OR p.mode='automatic' OR o.force=1)))) OR (c.kind='accept' AND (o.offer_id IS NOT c.offer_id OR o.force!=0)))) THEN RAISE(ABORT,'control_operation_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_change c JOIN ct_operation_event e USING(change_id) JOIN ct_operation o ON o.operation_id=e.operation_id
  JOIN ct_change oc ON oc.change_id=o.change_id WHERE c.change_id=NEW.change_id AND
  (e.operation_id IS NOT c.operation_id OR oc.device_id!=c.device_id OR
   (c.kind IN ('acquire','release','accept') AND (e.revision!='00000000000000000001' OR e.state!='pending')) OR
   (c.kind IN ('unknown','reject','retry') AND NOT EXISTS(SELECT 1 FROM ct_current_operation p JOIN ct_current_state s ON s.device_id=c.device_id
     WHERE p.operation_id=e.operation_id AND p.state IN ('pending','indeterminate') AND s.pending_operation_id IS e.operation_id AND p.revision<'99999999999999999999' AND e.revision={successor('p.revision')} AND
     ((c.kind='unknown' AND e.state='indeterminate' AND e.attempt_id=p.attempt_id) OR
      (c.kind='reject' AND e.state='rejected' AND e.attempt_id=p.attempt_id) OR
      (c.kind='retry' AND p.state='indeterminate' AND e.state='indeterminate' AND e.attempt_id!=p.attempt_id)))) OR
   (c.kind IN ('acquire','release','accept','retry') AND NOT EXISTS(SELECT 1 FROM ct_attempt a WHERE a.change_id=c.change_id AND a.attempt_id=e.attempt_id AND a.operation_id=e.operation_id)) OR
   (c.kind IN ('unknown','reject') AND EXISTS(SELECT 1 FROM ct_attempt a WHERE a.change_id=c.change_id)))) THEN RAISE(ABORT,'control_operation_transition') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_attempt a JOIN ct_change c USING(change_id) WHERE c.change_id=NEW.change_id AND
  (a.operation_id IS NOT c.operation_id OR
   (c.kind!='retry' AND a.ordinal!='00000000000000000001') OR
   (c.kind='retry' AND NOT EXISTS(SELECT 1 FROM ct_attempt p JOIN ct_current_operation e ON e.attempt_id=p.attempt_id WHERE e.operation_id=a.operation_id AND p.ordinal<'99999999999999999999' AND a.ordinal={successor('p.ordinal')})))) THEN RAISE(ABORT,'control_attempt_successor') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_offer o JOIN ct_change c USING(change_id) JOIN ct_request q USING(change_id)
  WHERE c.change_id=NEW.change_id AND (o.offer_id IS NOT c.offer_id OR NOT({same('o.sender','q.actor')}) OR o.clock_domain!=c.clock_domain OR o.descriptor!=c.descriptor OR o.issued_tick!=c.now_tick OR
   NOT EXISTS(SELECT 1 FROM ct_current_state s WHERE s.device_id=c.device_id AND s.change_id=o.expected_state_id AND s.mode='manual' AND s.pending_operation_id IS NULL AND {same('o.sender','s.holder')}))) THEN RAISE(ABORT,'control_offer_binding') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ct_offer_event e JOIN ct_change c USING(change_id) JOIN ct_offer o ON o.offer_id=e.offer_id JOIN ct_change oc ON oc.change_id=o.change_id
  WHERE c.change_id=NEW.change_id AND (e.offer_id IS NOT c.offer_id OR oc.device_id!=c.device_id OR
   (c.kind='offer' AND (e.state!='offered' OR e.revision!='00000000000000000001')) OR
   (c.kind!='offer' AND NOT EXISTS(SELECT 1 FROM ct_current_offer p WHERE p.offer_id=e.offer_id AND p.state='offered' AND p.revision<'99999999999999999999' AND e.revision={successor('p.revision')})) OR
   (c.kind='accept' AND (e.state!='accepted' OR e.accepted_operation_id IS NOT c.operation_id OR o.clock_domain!=c.clock_domain OR o.descriptor!=c.descriptor OR c.now_tick<o.issued_tick OR c.now_tick>=o.expires_tick OR
     NOT EXISTS(SELECT 1 FROM ct_request q JOIN ct_current_state s ON s.device_id=c.device_id JOIN ct_state old ON old.change_id=o.expected_state_id
      WHERE q.change_id=c.change_id AND {same('o.target','q.actor')} AND {same('o.sender','s.holder')} AND s.control_epoch=old.control_epoch AND s.effective_version=old.effective_version))) OR
   (c.kind='cancel' AND (e.state!='cancelled' OR NOT EXISTS(SELECT 1 FROM ct_request q WHERE q.change_id=c.change_id AND {same('q.actor','o.sender')}))) OR
   (c.kind='expire' AND (e.state!='expired' OR (c.clock_domain=o.clock_domain AND c.descriptor=o.descriptor AND c.now_tick<o.expires_tick))))) THEN RAISE(ABORT,'control_offer_transition') END;
END;
'''
    for t in TABLES:
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            sql+=f"\nCREATE TRIGGER {t}_{suffix} BEFORE {action} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_control_history'); END;\n"
        if t not in ('ct_change','ct_commit'):
            sql+=f"\nCREATE TRIGGER {t}_sealed BEFORE INSERT ON {t} WHEN EXISTS(SELECT 1 FROM ct_commit WHERE change_id=NEW.change_id) BEGIN SELECT RAISE(ABORT,'control_already_sealed'); END;\n"
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-control.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
