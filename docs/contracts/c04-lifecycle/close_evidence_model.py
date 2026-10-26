"""按唯一持久关闭来源选择读取器，调用者不能指定降级分支。"""
import authorization_close_ack_model as A
M=A.M

def kind(db,close_id,required=True):
    auth=db.execute('SELECT 1 FROM authorization_close_dispatch WHERE close_id=?',(close_id,)).fetchone() is not None
    installed=db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='gate_close_dispatch'").fetchone() is not None
    gate=installed and db.execute('SELECT 1 FROM gate_close_dispatch WHERE close_id=?',(close_id,)).fetchone() is not None
    M.need(not(auth and gate),'ambiguous_close_original')
    M.need(not required or auth or gate,'missing_close_original')
    return 'gate' if gate else 'authentication' if auth else None

def reader(db,close_id):
    if kind(db,close_id)=='authentication':return A
    import gate_close_ack_model as G
    return G

def dispatch(db,close_id):return reader(db,close_id).D.read(db,close_id)
def ack(db,close_id):return reader(db,close_id).read(db,close_id)
def ack_row(db,close_id):
    table='gate_close_ack' if kind(db,close_id)=='gate' else 'authorization_close_ack'
    return M.E.one(db,'SELECT * FROM '+table+' WHERE close_id=?',(close_id,))
def usable(db,close_id,ack_id):
    selected=reader(db,close_id)
    row=ack_row(db,close_id)
    return row is not None and row['ack_id']==ack_id and selected.usable(db,ack_id)
def current_view(db,close_id):
    source=kind(db,close_id,required=False)
    return {'gate':'gate_close_usable_ack','authentication':'authorization_close_usable_ack',None:None}[source]
