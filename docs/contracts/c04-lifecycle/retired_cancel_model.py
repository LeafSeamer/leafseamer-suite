"""以完整退役原件核销跨域取消准备；不产生旧域tick或新执行资格。"""
import json
from jsonschema import Draft202012Validator
import cancel_source_model as C
import retired_close_set_model as X
import build_retired_cancel as G
N=C.N;P=C.P;I=C.I;need=C.need;one=C.one;rows=C.rows;raw=C.raw;digest=C.digest
VERSION='retired-cancel-source/0.1.0-draft.1';SCHEMA=G.schema()
def validate(name,v):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name}).validate(v)
def install(db):
    need(not db.in_transaction and db.execute('PRAGMA foreign_keys').fetchone()[0]==1,'retired_cancel_install')
    need(one(db,"SELECT sql FROM sqlite_schema WHERE name='pd_cut_seal'")['sql']==G.original().rstrip(';'),'retired_cancel_layout_anchor')
    need(db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN('rcs_current','sr_current','cs_socket')").fetchone()[0]==3,'retired_cancel_dependencies')
    try:db.executescript('BEGIN IMMEDIATE;\n'+(G.HERE/'retired-cancel.sql').read_text('utf-8')+'\nDROP TRIGGER pd_cut_seal;\n'+G.trigger()+'\nCOMMIT;')
    except Exception:
        if db.in_transaction:db.rollback()
        raise
def proof(db,member,selection,completion_id,*,live):
    complete=X.read(db,completion_id);eid=member['exit_id'];adoption=X.R.read(db,eid);bundle=adoption['source_bundle'];e=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,))
    need(e['clock_domain_id']!=selection['clock_domain_id'],'retired_cancel_distinct_domain')
    need(all(bundle['evaluator_descriptor'][k]==selection[k] for k in ('clock_domain_id','descriptor_digest')),'retired_cancel_evaluator')
    need(P.u(bundle['evidence']['observed_tick_ns'])<=P.u(selection['selected_tick_ns']),'retired_cancel_future_observation')
    targets=[t for t in complete['targets'] if t['binding']['writer_exit_id']==eid];need(len(targets)==1,'retired_cancel_exit')
    preparations=[p for p in targets[0]['preparations'] if p['prepare_id']==member['prepare_id']];need(len(preparations)==1,'retired_cancel_prepare')
    p=preparations[0];need(p['encoding_authorization_ref']['id']==member['authorization_id'] and p['encoding_authorization_ref']['digest']==member['authorization_digest'],'retired_cancel_authorization')
    need(targets[0]['retirement_adoption_ref']==C.reference(adoption['adoption_id'],adoption['adoption_digest']),'retired_cancel_adoption')
    if live:need(X.current(db,completion_id) and X.R.current(db,eid),'retired_cancel_not_current')
    value=dict(member,completion_ref=C.reference(completion_id,complete['completion_digest']),adoption_ref=targets[0]['retirement_adoption_ref'],revocation_ref=p['revocation_ref']);validate('RetiredCancelMember',value);return value
def read(db,cut,*,live=False):
    need(db.in_transaction,'cancel_source_transaction_required')
    r=one(db,'SELECT p.*,k.committed_tick,k.audit_body,k.outbox_body FROM cc_cut c JOIN pd_cut p ON p.cut_id=c.prepare_cut_id JOIN pd_cut_commit k ON k.cut_id=p.cut_id WHERE c.cut_id=?',(cut['cut_id'],))
    source=C.M.document(r['selector_body']);validate('RetiredCancelSource',source);s=source['selection'];ctx={k:s[k] for k in ('clock_domain_id','descriptor_digest','selected_tick_ns')}
    need(raw(source)==r['selector_body']==r['audit_body']==r['outbox_body'] and digest(source)==r['selector_digest'] and r['kind']=='cancel' and r['cancel_id']==cut['cut_id'] and r['selected_tick']==r['committed_tick']==P.u(s['selected_tick_ns']),'retired_cancel_original')
    need(s==C.prepare_source(db,cut,r['prepare_head'],ctx,s['control_change_id']),'retired_cancel_selection')
    cols='prepare_id,exit_id,authorization_id,authorization_digest';expected=rows(db,'SELECT '+cols+' FROM pd_expected WHERE cut_id=? ORDER BY prepare_id',(r['cut_id'],));members=rows(db,'SELECT '+cols+' FROM pd_member WHERE cut_id=? ORDER BY prepare_id',(r['cut_id'],))
    need(members==expected and len(members)<=4096,'retired_cancel_members')
    records=rows(db,'SELECT * FROM crp_member WHERE cut_id=? ORDER BY prepare_id',(r['cut_id'],));mapping={p['prepare_id']:p for p in source['retirements']}
    need(len(mapping)==len(records)==len(source['retirements']) and list(mapping)==sorted(mapping),'retired_cancel_proof_set')
    rebuilt=[]
    for m in members:
        e=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(m['exit_id'],));rev=one(db,'SELECT * FROM ep_revocation WHERE prepare_id=?',(m['prepare_id'],));request=one(db,'SELECT * FROM ep_request_commit WHERE prepare_id=?',(m['prepare_id'],))
        reason=C.M.document(rev['reason_body']);need(raw(reason)==rev['reason_body']==rev['audit_body']==rev['outbox_body'] and digest(reason)==rev['revocation_digest'],'retired_cancel_revocation_original')
        if all(e[k]==ctx[k] for k in ('clock_domain_id','descriptor_digest')):
            need(m['prepare_id'] not in mapping and request['committed_tick']<=r['committed_tick'] and rev['revoked_tick']<=r['committed_tick'],'retired_cancel_same_domain_time');continue
        need(m['prepare_id'] in mapping,'retired_cancel_missing_proof');v=proof(db,m,s,mapping[m['prepare_id']]['completion_ref']['id'],live=live);need(v==mapping[m['prepare_id']],'retired_cancel_proof_binding');rebuilt.append(v)
    need(rebuilt==source['retirements'],'retired_cancel_exact_set')
    for v,rp in zip(rebuilt,records):need(rp['prepare_id']==v['prepare_id'] and rp['exit_id']==v['exit_id'] and rp['completion_id']==v['completion_ref']['id'] and rp['body']==rp['audit_body']==raw(v),'retired_cancel_proof_original')
    return source
def capture(db,cid,cut_id,stage,retirements,context,fail_after=None):
    need(stage in ('ordinary','all') and isinstance(retirements,dict) and 0<len(retirements)<=4096,'retired_cancel_arguments')
    def run():
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM cc_cut WHERE cut_id=?',(cut_id,)).fetchone():
            cut=C.read_cut(db,cut_id);source=read(db,cut);s=source['selection']
            need(cut['stage']==stage and cut['binding']['cancellation_id']==cid and context=={k:s[k] for k in ('clock_domain_id','descriptor_digest','selected_tick_ns')} and retirements=={p['prepare_id']:p['completion_ref']['id'] for p in source['retirements']},'retired_cancel_replay_conflict');return cut,writes
        previous=C.read_cut(db,one(db,"SELECT cut_id FROM cc_cut WHERE cancellation_id=? AND stage='ordinary'",(cid,))['cut_id']) if stage=='all' else None
        c=one(db,'SELECT * FROM cv_cancel WHERE cancellation_id=?',(cid,));issued=str(int(c['cut_revision'])) if stage=='ordinary' else str(int(db.execute("SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue").fetchone()[0]));cut=C.expected(db,cid,cut_id,stage,issued,previous)
        if stage=='ordinary':need(raw(cut)==c['cut_body'] and cut['cut_digest']==c['cut_digest'],'cancel_ordinary_admission_cut')
        pid='cancel_prepare_'+digest(dict(cut_id=cut_id)).split(':')[1];device=one(db,'SELECT device_id FROM ce_command WHERE command_id=?',(cut['binding']['parent_command_id'],))['device_id'];change=one(db,'SELECT change_id FROM ct_current_change WHERE device_id=?',(device,))['change_id'];head=db.execute("SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration").fetchone()[0]
        selection=C.prepare_source(db,cut,head,context,change)
        write('cc_cut',cut_id=cut_id,cancellation_id=cid,stage=stage,previous_cut_id=previous['cut_id'] if previous else None,issued_revision=P.u(issued),cut_digest=cut['cut_digest'],cut_body=raw(cut),prepare_cut_id=pid)
        for t in cut['targets']:
            eid=t['exit']['writer_exit_id'];write('cc_target',cut_id=cut_id,exit_id=eid,target_digest=t['target_digest'],target_body=raw(t))
            for permit in [p['intent']['permit_id'] for p in t['ordinary_transmissions']]+[p['permit_id'] for p in t['cancel_transmissions']]:
                fact=db.execute('SELECT disposition FROM ce_current_disposition WHERE permit_id=? UNION ALL SELECT disposition FROM cf_disposition WHERE permit_id=?',(permit,permit)).fetchone();write('cc_member',cut_id=cut_id,exit_id=eid,permit_id=permit,entered_known=int(fact is not None and fact[0]=='in_flight'))
            for prepare in t['cancel_prepare_ids']:write('cc_cut_prepare',cut_id=cut_id,exit_id=eid,prepare_id=prepare)
        members=rows(db,"SELECT prepare_id,exit_id,authorization_id,authorization_digest FROM pd_source WHERE command_id=? AND sequence<=? AND (?='all' OR kind='ordinary') ORDER BY prepare_id LIMIT 4097",(cut['binding']['parent_command_id'],head,stage));need(len(members)<=4096,'cancel_prepare_capacity');proofs=[]
        for m in members:
            e=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(m['exit_id'],))
            if all(e[k]==context[k] for k in ('clock_domain_id','descriptor_digest')):need(m['prepare_id'] not in retirements,'retired_cancel_unneeded_proof')
            else:
                need(m['prepare_id'] in retirements,'retired_cancel_missing_proof');proofs.append(proof(db,m,selection,retirements[m['prepare_id']],live=True))
        need(set(retirements)=={p['prepare_id'] for p in proofs},'retired_cancel_exact_set');source=dict(format_version=VERSION,selection=selection,retirements=proofs);validate('RetiredCancelSource',source);body=raw(source);need(len(body)<=16777216,'retired_cancel_capacity')
        write('pd_cut',cut_id=pid,kind='cancel',control_id=None,cancel_id=cut_id,run_id=None,close_id=None,prepare_head=head,selected_tick=P.u(context['selected_tick_ns']),selector_digest=digest(source),selector_body=body)
        for m in members:
            write('pd_member',cut_id=pid,**m)
            if m['prepare_id'] in retirements:
                v=next(p for p in proofs if p['prepare_id']==m['prepare_id']);write('crp_member',cut_id=pid,prepare_id=m['prepare_id'],exit_id=m['exit_id'],completion_id=v['completion_ref']['id'],body=raw(v),audit_body=raw(v))
            elif not db.execute('SELECT 1 FROM ep_revocation WHERE prepare_id=?',(m['prepare_id'],)).fetchone():
                event=dict(kind='cancel_prepare_revocation',source_ref=C.reference(pid,digest(source)),prepare=m,revoked_tick_ns=context['selected_tick_ns']);rid='cancel_revoke_'+digest(event).split(':')[1];b=raw(event);write('ep_revocation',prepare_id=m['prepare_id'],revocation_id=rid,revocation_revision=P.u(1),revocation_digest=digest(event),revoked_tick=P.u(context['selected_tick_ns']),reason_body=b,audit_body=b,outbox_id=rid,outbox_body=b)
        write('pd_cut_commit',cut_id=pid,committed_tick=P.u(context['selected_tick_ns']),audit_body=body,outbox_body=body);read(db,cut,live=True)
        write('cc_cut_commit',cut_id=cut_id,validation_body=raw(cut),audit_body=raw(cut),outbox_id=cut_id+'.event',outbox_body=raw(cut));need(C.read_cut(db,cut_id)==cut,'retired_cancel_readback');return cut,writes
    return N.transaction(db,run)
