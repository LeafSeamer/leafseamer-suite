"""从已提交运行拒绝账本读取、封存和重建完整快照，不生成OPEN帧。"""
import re
from pathlib import Path
from jsonschema import Draft202012Validator
import open_source_model as O
M=O.M;N=O.N;P=O.P;S=O.S;I=O.I;need=M.need;HERE=Path(__file__).resolve().parent
IPC=O.O.IPC
VALIDATOR=Draft202012Validator({'$defs':IPC['$defs'],'$ref':'#/$defs/S2__RunDenySnapshot'})
MAX_ENTRIES=4096

def install(db):
    need(not db.in_transaction,'run_snapshot_install_transaction')
    need(db.execute('PRAGMA foreign_keys').fetchone()[0]==1,'run_snapshot_foreign_keys')
    source=(HERE.parent/'c08-controller/common.sql').read_text(encoding='utf-8')
    for name in ('run_deny_committed','run_deny_current','run_deny_snapshot_revision'):
        expected=re.search(r'CREATE VIEW '+name+r'\b.*?;',source,re.S).group(0).rstrip(';')
        actual=M.E.one(db,'SELECT sql FROM sqlite_schema WHERE name=?',(name,))['sql'];need(actual==expected,'run_snapshot_layout_anchor')
    try:db.executescript('BEGIN IMMEDIATE;\n'+(HERE/'run_snapshot.sql').read_text(encoding='utf-8')+'\nCOMMIT;')
    except Exception:
        if db.in_transaction:db.rollback()
        raise

def head(db):return str(int(db.execute('SELECT revision FROM run_deny_snapshot_revision').fetchone()[0]))

def materialize(db,revision):
    need(db.in_transaction,'run_snapshot_transaction_required');S.validate('Counter',revision)
    need(int(revision)<=int(head(db)),'run_snapshot_future')
    if revision!='0':need(db.execute('SELECT 1 FROM run_deny_committed WHERE snapshot_revision=?',(P.u(revision),)).fetchone() is not None,'run_snapshot_missing_frontier')
    rows=O.rows(db,"""SELECT d.* FROM run_deny_committed d WHERE d.snapshot_revision<=?
      AND NOT EXISTS(SELECT 1 FROM run_deny_committed n WHERE n.snapshot_revision<=?
        AND (n.origin_authority,n.origin_database,n.run_id)=(d.origin_authority,d.origin_database,d.run_id)
        AND n.generation>d.generation)
      ORDER BY d.origin_authority COLLATE BINARY,d.origin_database COLLATE BINARY,d.run_id COLLATE BINARY LIMIT 4097""",(P.u(revision),P.u(revision)))
    need(len(rows)<=MAX_ENTRIES,'run_snapshot_capacity')
    entries=[dict(selector=dict(kind='run_generation',origin_scope=dict(authority_service_id=r['origin_authority'],database_instance_id=r['origin_database']),run_id=r['run_id'],deny_through_generation=str(int(r['generation']))),deny_revision=str(int(r['deny_revision']))) for r in rows]
    body=M.sealed(dict(controller_scope=M.E.A.scope(db),snapshot_revision=revision,entries=entries),'snapshot_digest');VALIDATOR.validate(body);return body

def read(db,sid):
    need(db.in_transaction,'run_snapshot_transaction_required')
    row=M.E.one(db,'SELECT s.*,c.audit_body FROM rs_snapshot s JOIN rs_commit c USING(snapshot_id) WHERE snapshot_id=?',(sid,))
    body=M.document(row['body']);VALIDATOR.validate(body)
    need(M.raw(body)==row['body']==row['audit_body'] and body==M.sealed(body,'snapshot_digest') and body['snapshot_digest']==row['snapshot_digest'],'run_snapshot_original')
    need(body==materialize(db,str(int(row['snapshot_revision']))) and row['entry_count']==len(body['entries']),'run_snapshot_source');return body

def current(db,sid):
    body=read(db,sid);return body['snapshot_revision']==head(db)

def capture(db,sid,fail_after=None):
    S.validate('Id',sid)
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM rs_snapshot WHERE snapshot_id=?',(sid,)).fetchone():return read(db,sid),current(db,sid),writes
        body=materialize(db,head(db));raw=M.raw(body);need(len(raw)<=16777216,'run_snapshot_body_capacity')
        write('rs_snapshot',snapshot_id=sid,snapshot_revision=P.u(body['snapshot_revision']),entry_count=len(body['entries']),snapshot_digest=body['snapshot_digest'],body=raw)
        write('rs_commit',snapshot_id=sid,audit_body=raw);need(read(db,sid)==body and current(db,sid),'run_snapshot_readback');return body,True,writes
    return N.transaction(db,run)

def for_open(db,rid,fid,now):
    sources=O.before_open(db,rid,fid,now);sid=sources['originals']['resource']['run_snapshot_id'];body=read(db,sid)
    need(current(db,sid),'run_snapshot_stale')
    need(body['controller_scope']==sources['binding']['scope'],'run_snapshot_scope')
    sources['run_deny_snapshot']=body;return sources
