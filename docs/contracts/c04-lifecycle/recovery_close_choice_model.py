"""在既有恢复seal中消费完整ACK或退役完成；快照提供者真实性仍独立验证。"""
from jsonschema import Draft202012Validator
from referencing import Resource
import retired_close_set_model as X
import build_recovery_close_choice as G
R=X.R;N=X.N;M=X.M;P=X.P;C=X.C;I=X.I;A=N.A
REGISTRY=X.REGISTRY.with_resource(G.SID,Resource.from_contents(G.schema()))
def validate(v):Draft202012Validator({'$ref':G.SID+'#/$defs/RecoveryCloseChoice'},registry=REGISTRY).validate(v)
def install(db):
    M.need(not db.in_transaction,'recovery_choice_install_transaction')
    for name,expected in G.originals().items():
        actual=M.E.one(db,'SELECT sql FROM sqlite_schema WHERE name=?',(name,))['sql'];M.need(actual.rstrip(';')==expected.rstrip(';'),'recovery_choice_layout_anchor')
    M.E.one(db,"SELECT sql FROM sqlite_schema WHERE name='retired_close_usable'")
    try:db.executescript('BEGIN IMMEDIATE;\n'+G.sql().decode()+'\nCOMMIT;')
    except Exception:
        if db.in_transaction:db.rollback()
        raise
def close_ref(db,cid):
    c=M.E.one(db,'SELECT * FROM go_close WHERE close_id=?',(cid,));return M.E.ref(cid,str(int(c['revision'])),M.F.digest(C.columns(c)))
def choice(db,selection):
    cid=selection['close_id'];close=close_ref(db,cid)
    if selection['kind']=='worker_ack':
        M.need(set(selection)=={'kind','close_id'},'recovery_ack_selection_fields')
        ack,_=N.CE.ack(db,cid);a=N.CE.ack_row(db,cid)
        row=M.E.one(db,'SELECT p.* FROM pd_close_completion c JOIN pd_closure p USING(closure_id) WHERE c.close_id=? AND c.ack_id=?',(cid,a['adopted_ack_id']))
        p=M.document(row['body']);N.validate('PreparationClosure',p);M.need(p==M.sealed(p,'closure_digest') and p['closure_digest']==row['closure_digest'],'recovery_prepare_original')
        return dict(kind='worker_ack',close_ref=close,ack_ref=M.reference(ack,'ack_id','ack_digest'),preparation_closure_ref=M.reference(p,'closure_id','closure_digest')),a['adopted_ack_id']
    M.need(selection['kind']=='supervisor_retired' and set(selection)=={'kind','close_id','completion_id'},'recovery_retired_selection_fields')
    v=X.read(db,selection['completion_id']);ts=[t for t in v['targets'] if t['close_ref']==close];M.need(len(ts)==1,'recovery_retired_close_binding')
    return dict(kind='supervisor_retired',close_ref=close,retired_completion_ref=M.reference(v,'completion_id','completion_digest'),writer_exit_id=ts[0]['binding']['writer_exit_id']),None
def snapshot_ref(snapshot,holds):return M.E.ref(snapshot['snapshot_id'],1,M.F.digest(dict(snapshot=C.columns(snapshot),holds=[C.columns(h) for h in holds])))
def receipt(db,rid,snapshot,holds,selections,tick,provider):
    M.validate('Ref',provider);M.need(len(selections)>0 and len(selections)<=256 and len(holds)<=4096,'recovery_choice_capacity')
    binding=R.runtime(db,snapshot['exit_id'])[0]['binding'];M.need(binding['device_id']==snapshot['device_id'],'recovery_snapshot_device')
    targets=[choice(db,s)[0] for s in selections];targets.sort(key=lambda t:t['close_ref']['id'])
    M.need(len({t['close_ref']['id'] for t in targets})==len(targets),'recovery_duplicate_close')
    v=M.sealed(dict(format_version='recovery-close-choice/0.1.0-draft.1',recovery_id=rid,revision='1',binding=binding,snapshot_ref=snapshot_ref(snapshot,holds),provider_ref=provider,selected_tick_ns=str(int(P.u(tick))),targets=targets),'recovery_digest');validate(v)
    M.need(len(M.raw(v))<=16777216,'recovery_choice_bytes');return v
def current(db,rid):return db.execute('SELECT 1 FROM go_valid_recovery WHERE recovery_id=?',(rid,)).fetchone() is not None
def read(db,rid):
    row=M.E.one(db,'SELECT * FROM go_recovery WHERE recovery_id=?',(rid,));v=M.document(row['body']);validate(v)
    snapshot=M.E.one(db,'SELECT * FROM go_snapshot WHERE snapshot_id=?',(row['snapshot_id'],));holds=P.rows(db,'SELECT * FROM go_hold WHERE snapshot_id=? ORDER BY hold_id',(row['snapshot_id'],))
    selections=[]
    for t in P.rows(db,'SELECT * FROM gr_all_target WHERE recovery_id=? ORDER BY close_id',(rid,)):
        s=dict(close_id=t['close_id'],kind=t['kind'])
        if t['kind']=='supervisor_retired':s['completion_id']=t['completion_id']
        expected,aid=choice(db,s);M.need(t['ack_id']==aid and (t['kind']=='worker_ack' or t['exit_id']==expected['writer_exit_id']),'recovery_target_projection');selections.append(s)
    actual=receipt(db,rid,snapshot,holds,selections,str(int(row['now_tick'])),M.document(row['provider_ref'].encode()))
    seal=M.E.one(db,'SELECT * FROM go_recovery_commit WHERE recovery_id=?',(rid,));M.need(v==actual and row['device_id']==v['binding']['device_id'] and row['recovery_digest']==v['recovery_digest'] and seal['audit_body']==seal['outbox_body']==row['body'],'recovery_choice_original')
    return v
def complete(db,rid,snapshot,holds,selections,tick,provider,fail_after=None):
    """snapshot及holds来自外部快照提供者；本模型仅检查结构和同库关系。"""
    def run():
        writes,write=N.writer(db,fail_after);ordered=sorted(holds,key=lambda h:h['hold_id']);v=receipt(db,rid,snapshot,ordered,selections,tick,provider)
        if db.execute('SELECT 1 FROM go_recovery WHERE recovery_id=?',(rid,)).fetchone():
            old=read(db,rid);M.need(old==v,'recovery_choice_replay_conflict');return old,current(db,rid),writes
        state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(snapshot['device_id'],));M.need(state['gate_state']=='protected','recovery_choice_requires_protection')
        for t in v['targets']:
            if t['kind']=='supervisor_retired':M.need(X.current(db,t['retired_completion_ref']['id']),'recovery_retired_not_current')
            else:M.need(N.current(db,t['close_ref']['id']),'recovery_ack_not_current')
        body=M.raw(v)
        write('go_recovery',recovery_id=rid,device_id=snapshot['device_id'],snapshot_id=snapshot['snapshot_id'],now_tick=P.u(tick),recovery_digest=v['recovery_digest'],body=body,provider_ref=M.raw(provider).decode())
        write('go_snapshot',**snapshot)
        for h in ordered:write('go_hold',**h)
        write('go_snapshot_commit',snapshot_id=snapshot['snapshot_id'],audit_body=body)
        for s in selections:
            value,aid=choice(db,s)
            if s['kind']=='worker_ack':write('go_recovery_target',recovery_id=rid,close_id=s['close_id'],ack_id=aid)
            else:write('gr_retired_target',recovery_id=rid,close_id=s['close_id'],completion_id=s['completion_id'],exit_id=value['writer_exit_id'])
        write('go_recovery_commit',recovery_id=rid,audit_body=body,outbox_body=body)
        M.need(current(db,rid),'recovery_choice_not_current');read(db,rid);return v,True,writes
    return N.transaction(db,run)
