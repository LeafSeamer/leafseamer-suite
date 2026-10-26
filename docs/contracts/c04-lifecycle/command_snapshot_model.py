"""完整命令拒绝快照的封存、历史查原和OPEN前态组合；候选离线模型。"""
import re
import cancel_source_model as C
D=C.D;R=D.R;M=C.M;N=C.N;P=C.P;I=C.I;need=C.need;HERE=D.HERE

def install(db):
    need(not db.in_transaction and db.execute('PRAGMA foreign_keys').fetchone()[0]==1 and db.execute('PRAGMA recursive_triggers').fetchone()[0]==1,'command_snapshot_install')
    source=(HERE/'command_deny.sql').read_text('utf-8')
    for name in ('cd_expected','cd_head'):
        expected=re.search(r'CREATE VIEW '+name+r'\b.*?;',source,re.S).group(0).rstrip(';')
        need(C.one(db,'SELECT sql FROM sqlite_schema WHERE name=?',(name,))['sql']==expected,'command_snapshot_layout_anchor')
    need(db.execute("SELECT 1 FROM sqlite_schema WHERE name='cs_socket'").fetchone() is not None,'command_snapshot_source_required')
    try:db.executescript('BEGIN IMMEDIATE;\n'+(HERE/'command_snapshot.sql').read_text('utf-8')+'\nCOMMIT;')
    except Exception:
        if db.in_transaction:db.rollback()
        raise

def read(db,sid):
    need(db.in_transaction,'command_snapshot_transaction_required')
    r=C.one(db,'SELECT s.*,c.audit_body FROM ds_snapshot s JOIN ds_commit c USING(snapshot_id) WHERE snapshot_id=?',(sid,))
    body=C.decode('S8__DenySnapshot',r['body'],'snapshot_digest',r['snapshot_digest'])
    need(r['body']==r['audit_body'] and body['device_id']==r['device_id'] and body['snapshot_revision']==str(int(r['snapshot_revision'])) and len(body['entries'])==r['entry_count'],'command_snapshot_columns')
    need(body==C.snapshot_body(db,r['device_id'],body['snapshot_revision']),'command_snapshot_source');return body

def current(db,sid):
    body=read(db,sid);return body['snapshot_revision']==D.head(db,body['device_id'])

def capture(db,sid,device,fail_after=None):
    D.S.validate('Id',sid);D.S.validate('Id',device)
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM ds_snapshot WHERE snapshot_id=?',(sid,)).fetchone():
            body=read(db,sid);need(body['device_id']==device,'command_snapshot_replay_conflict');return body,current(db,sid),writes
        body=C.snapshot_body(db,device);raw=C.raw(body);need(len(raw)<=16777216,'command_snapshot_body_capacity')
        write('ds_snapshot',snapshot_id=sid,device_id=device,snapshot_revision=P.u(body['snapshot_revision']),entry_count=len(body['entries']),snapshot_digest=body['snapshot_digest'],body=raw)
        write('ds_commit',snapshot_id=sid,audit_body=raw);need(read(db,sid)==body and current(db,sid),'command_snapshot_readback');return body,True,writes
    return N.transaction(db,run)

def for_open(db,rid,fid,now):
    # 调用方必须在最终单writer写事务内使用，普通读事务只提供其快照时点的事实。
    sources=R.for_open(db,rid,fid,now);sid=sources['originals']['resource']['command_snapshot_id'];body=read(db,sid)
    need(current(db,sid),'command_snapshot_stale')
    need(body['scope']==sources['binding']['scope'] and body['device_id']==sources['binding']['device_id'],'command_snapshot_binding')
    for entry in body['entries']:
        cut=C.read_cut(db,entry['cut_ref']['id'])
        if 'prepare_cut_id' in C.one(db,'SELECT * FROM cc_cut WHERE cut_id=?',(cut['cut_id'],)):
            selection=C.read_prepare_cut(db,cut)
            if selection.get('format_version')=='retired-cancel-source/0.1.0-draft.1':
                import retired_cancel_model as retired
                retired.read(db,cut,live=True)
    sources['command_deny_snapshot']=body;return sources
