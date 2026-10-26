"""退役worker全出口与准备原件核销；仅独立完成证据，不放行恢复。"""
from jsonschema import Draft202012Validator
from referencing import Resource
import supervisor_retirement_adoption_model as R
import build_retired_close_set as G
N=R.N;M=R.M;P=R.P;C=N.C;I=R.I
REGISTRY=R.REGISTRY.with_resource(G.SID,Resource.from_contents(G.schema()))
MAX_EXITS=256;MAX_PREPARES=4096;MAX_BYTES=16777216
def validate(v):Draft202012Validator({'$ref':G.SID+'#/$defs/RetiredCloseSet'},registry=REGISTRY).validate(v)
def install(db):
    M.need(not db.in_transaction and db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('sr_current','sr_commit','pd_cut_commit','authorization_close_dispatch')").fetchone()[0]==4,'retired_close_layout')
    db.executescript((G.HERE/'retired-close-set.sql').read_text('utf-8'))
def worker(r):return dict(source=r['source'],intent=r['intent'],admission_receipt=r['admission_receipt'])
def inventory(db,eid):
    r,e=R.runtime(db,eid)
    exits=P.rows(db,'SELECT exit_id FROM ce_exit WHERE (worker_boot_id,clock_domain_id,descriptor_digest)=(?,?,?) ORDER BY exit_id LIMIT ?',tuple(e[k] for k in ('worker_boot_id','clock_domain_id','descriptor_digest'))+(MAX_EXITS+1,))
    M.need(0<len(exits)<=MAX_EXITS,'retired_close_exit_capacity')
    for x in exits:M.need(worker(R.runtime(db,x['exit_id'])[0])==worker(r),'retired_close_worker_collision')
    return r,[x['exit_id'] for x in exits]
def target(db,eid,cid):
    r,_=R.runtime(db,eid);adoption=R.read(db,eid);close=M.E.one(db,'SELECT * FROM go_close WHERE close_id=? AND exit_id=?',(cid,eid))
    cut=M.E.one(db,'SELECT * FROM pd_cut WHERE cut_id=?',(close['prepare_cut_id'],));seal=M.E.one(db,'SELECT * FROM pd_cut_commit WHERE cut_id=?',(cut['cut_id'],))
    M.need(cut['kind']=='close' and cut['close_id']==cid and M.F.digest(M.document(cut['selector_body']))==cut['selector_digest'],'retired_close_cut_source')
    members=P.rows(db,'SELECT * FROM pd_member WHERE cut_id=? ORDER BY prepare_id LIMIT ?',(cut['cut_id'],MAX_PREPARES+1))
    M.need(len(members)<=MAX_PREPARES,'retired_close_prepare_capacity')
    preparations=[]
    for m in members:
        pid=m['prepare_id'];dispatch,original,member,request,auth,encoded,rev=N.source(db,cid,pid)
        M.need(dispatch['target']['binding']==r['binding'] and member['exit_id']==eid,'retired_close_prepare_binding')
        registration=M.E.one(db,'SELECT * FROM pd_registration WHERE prepare_id=?',(pid,));M.need(registration['sequence']<=cut['prepare_head'],'retired_close_prepare_head')
        M.E.one(db,'SELECT * FROM ep_request_commit WHERE prepare_id=?',(pid,));N.stored_frame(db,encoded['frame_id'])
        M.E.one(db,'SELECT * FROM ij_commit WHERE frame_id=?',(encoded['frame_id'],))
        preparations.append(dict(prepare_id=pid,encoding_authorization_ref=M.reference(auth,'authorization_id','authorization_digest'),revocation_ref=M.E.ref(rev['revocation_id'],str(int(rev['revocation_revision'])),rev['revocation_digest']),encoding_frame_ref=M.E.ref(encoded['frame_id'],1,encoded['frame_digest']),basis='retired'))
    return dict(binding=r['binding'],runtime_binding_ref=M.reference(r,'binding_id','binding_digest'),retirement_adoption_ref=M.reference(adoption,'adoption_id','adoption_digest'),close_ref=M.E.ref(cid,str(int(close['revision'])),M.F.digest(C.columns(close))),cut_ref=M.E.ref(cut['cut_id'],1,M.F.digest(dict(cut=C.columns(cut),seal=C.columns(seal)))),prepare_head=str(int(cut['prepare_head'])),preparations=preparations)
def current(db,ident):return db.execute('SELECT 1 FROM rcs_current WHERE completion_id=?',(ident,)).fetchone() is not None
def read(db,ident):
    row=M.E.one(db,'SELECT * FROM rcs_completion WHERE completion_id=?',(ident,));v=M.document(row['body']);validate(v)
    M.need(v==M.sealed(v,'completion_digest') and v['completion_id']==ident and row['anchor_exit_id']==v['anchor_exit_id'] and row['digest']==v['completion_digest'],'retired_close_digest')
    r,exits=inventory(db,v['anchor_exit_id']);M.need(v['worker_identity_digest']==M.F.digest(worker(r)) and [t['binding']['writer_exit_id'] for t in v['targets']]==exits,'retired_close_inventory')
    stored=P.rows(db,'SELECT * FROM rcs_target WHERE completion_id=? ORDER BY exit_id',(ident,));M.need(len(stored)==len(exits),'retired_close_projection_count')
    for t,s in zip(v['targets'],stored):
        M.need(t==target(db,s['exit_id'],s['close_id']) and s['body']==M.raw(t) and s['adoption_digest']==t['retirement_adoption_ref']['digest'],'retired_close_target_original')
    seal=M.E.one(db,'SELECT * FROM rcs_commit WHERE completion_id=?',(ident,));M.need(seal['audit_body']==seal['outbox_body']==row['body'],'retired_close_seal')
    return v
def complete(db,eid,ident,fail_after=None):
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM rcs_completion WHERE completion_id=?',(ident,)).fetchone():
            old=read(db,ident);M.need(old['anchor_exit_id']==eid,'retired_close_replay_anchor');return old,current(db,ident),writes
        r,exits=inventory(db,eid);targets=[]
        for exit_id in exits:
            M.need(R.current(db,exit_id),'retired_close_adoption_not_current')
            close=M.E.one(db,'SELECT * FROM go_latest_close WHERE exit_id=?',(exit_id,));e=M.E.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(exit_id,))
            state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(e['device_id'],));M.need(state['gate_state']=='protected','retired_close_requires_protection')
            t=target(db,exit_id,close['close_id']);targets.append(t)
            expected=[x['prepare_id'] for x in P.rows(db,'SELECT prepare_id FROM ep_request WHERE exit_id=? ORDER BY prepare_id LIMIT ?',(exit_id,MAX_PREPARES+1))]
            M.need(expected==[p['prepare_id'] for p in t['preparations']],'retired_close_prepare_inventory')
        M.need(sum(len(t['preparations']) for t in targets)<=MAX_PREPARES,'retired_close_total_prepares')
        v=M.sealed(dict(format_version='retired-close-set/0.1.0-draft.1',completion_id=ident,revision='1',anchor_exit_id=eid,worker_identity_digest=M.F.digest(worker(r)),targets=targets),'completion_digest');validate(v)
        body=M.raw(v);M.need(len(body)<=MAX_BYTES,'retired_close_bytes')
        write('rcs_completion',completion_id=ident,anchor_exit_id=eid,digest=v['completion_digest'],body=body)
        for t in targets:write('rcs_target',completion_id=ident,exit_id=t['binding']['writer_exit_id'],close_id=t['close_ref']['id'],adoption_digest=t['retirement_adoption_ref']['digest'],body=M.raw(t))
        write('rcs_commit',completion_id=ident,audit_body=body,outbox_body=body)
        read(db,ident);M.need(current(db,ident),'retired_close_not_current');return v,True,writes
    return N.transaction(db,run)
