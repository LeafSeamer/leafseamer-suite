"""快照序号从本库事务派生，换域只追加protected控制记录，不开放出口。"""
import sqlite3
from jsonschema import Draft202012Validator
from referencing import Resource
import recovery_close_choice_model as Y
import build_snapshot_domain_order as G
X=Y.X;R=Y.R;N=Y.N;M=Y.M;P=Y.P;I=Y.I;S=P.S
REGISTRY=Y.REGISTRY.with_resource(G.SID,Resource.from_contents(G.schema()))
def validate(name,v):Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=REGISTRY).validate(v)
def statements(db,text):
    pending=''
    for line in text.splitlines(keepends=True):
        pending+=line
        if sqlite3.complete_statement(pending):db.execute(pending);pending=''
    M.need(not pending.strip(),'snapshot_order_sql_incomplete')
def install(db):
    def run():
        old=M.E.one(db,"SELECT sql FROM sqlite_schema WHERE name='go_current_snapshot'")['sql'];M.need(old.rstrip(';')==G.original().rstrip(';'),'snapshot_order_layout_anchor')
        # 旧候选只允许单域且严格tick次序的已封存历史回填，绝不猜测跨域顺序。
        rows=P.rows(db,'SELECT s.*,e.clock_domain_id,e.descriptor_digest FROM go_snapshot s JOIN ce_exit e ON e.exit_id=s.exit_id ORDER BY s.device_id,s.sampled_tick')
        domains={};last={}
        for row in rows:
            device=row['device_id'];domain=(row['clock_domain_id'],row['descriptor_digest'])
            M.need(domains.get(device,domain)==domain and row['sampled_tick']>last.get(device,''),'snapshot_order_ambiguous_history')
            M.E.one(db,'SELECT * FROM go_snapshot_commit WHERE snapshot_id=?',(row['snapshot_id'],));domains[device]=domain;last[device]=row['sampled_tick']
        prefix,suffix=(G.HERE/'snapshot-domain-order.sql').read_text('utf-8').split('-- BACKFILL_BOUNDARY');statements(db,prefix);counts={}
        for row in rows:
            device=row['device_id'];counts[device]=counts.get(device,0)+1
            db.execute(*I('gso_order',snapshot_id=row['snapshot_id'],device_id=device,ordinal=P.u(counts[device]),clock_domain_id=row['clock_domain_id'],descriptor_digest=row['descriptor_digest']))
        statements(db,suffix)
    return N.transaction(db,run)
def domain_descriptor(value):
    sid=R.G.external(R.G.SUP,'ClockDomainDescriptor')
    Draft202012Validator(sid,registry=REGISTRY).validate(value)
    digest=M.F.digest({k:v for k,v in value.items() if k not in ('clock_domain_id','descriptor_digest')})
    M.need(value['descriptor_digest']==digest and value['clock_domain_id']=='clock_'+digest[7:],'domain_descriptor_digest')
def order(db,sid):
    s=M.E.one(db,'SELECT s.*,o.ordinal,o.clock_domain_id,o.descriptor_digest FROM go_snapshot s JOIN gso_order o USING(snapshot_id) JOIN go_snapshot_commit k USING(snapshot_id) WHERE snapshot_id=?',(sid,))
    b=S.binding(db,s['exit_id']);M.need((s['clock_domain_id'],s['descriptor_digest'])==(b['clock_domain_id'],b['descriptor_digest']),'snapshot_order_domain')
    v=dict(format_version='snapshot-domain-order/0.1.0-draft.1',binding=b,snapshot_ref=M.E.ref(sid,1,s['evidence_digest']),ordinal=str(int(s['ordinal'])));validate('SnapshotDomainOrder',v);return v
def read(db,ident):
    if not db.in_transaction:return N.transaction(db,lambda:read(db,ident))
    row=M.E.one(db,'SELECT * FROM gso_transition WHERE change_id=?',(ident,));v=M.document(row['body']);validate('ProtectedDomainTransition',v);domain_descriptor(v['new_clock_descriptor'])
    c=M.E.one(db,'SELECT * FROM ct_change WHERE change_id=?',(ident,));prior=M.E.one(db,'SELECT s.change_id FROM ct_state s JOIN ct_change h USING(change_id) JOIN ct_commit k USING(change_id) WHERE h.device_id=? AND h.sequence<? ORDER BY h.sequence DESC LIMIT 1',(c['device_id'],c['sequence']));before=S.control(db,prior['change_id']);after=S.control(db,ident)
    M.need(v==M.sealed(v,'transition_digest') and v['transition_id']==ident and row['digest']==v['transition_digest'] and c['clock_domain']==v['new_clock_descriptor']['clock_domain_id'] and c['descriptor']==v['new_clock_descriptor']['descriptor_digest'] and c['now_tick']==P.u(v['selected_tick_ns']),'domain_transition_original')
    M.need(S.control_ref(before)==v['before_control_ref'] and S.control_ref(after)==v['after_control_ref'],'domain_transition_controls');return v
def restart(db,device,ident,descriptor,tick,provider,fail_after=None):
    def run():
        domain_descriptor(descriptor);M.validate('Ref',provider);M.need(descriptor['authority_service_id']==M.E.A.scope(db)['authority_service_id'],'domain_transition_scope')
        writes,write=N.writer(db,fail_after)
        if db.execute('SELECT 1 FROM gso_transition WHERE change_id=?',(ident,)).fetchone():
            old=read(db,ident);c=M.E.one(db,'SELECT * FROM ct_change WHERE change_id=?',(ident,))
            M.need(c['device_id']==device and old['new_clock_descriptor']==descriptor and old['selected_tick_ns']==str(int(P.u(tick))) and old['provider_ref']==provider,'domain_transition_replay_conflict');return old,writes
        previous=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(device,));state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(device,));before=S.control(db,state['change_id'])
        change=dict(previous,change_id=ident,previous_id=previous['change_id'],sequence=P.u(int(previous['sequence'])+1),kind='restart',state_id=ident,operation_id=None,offer_id=None,request_id=None,clock_domain=descriptor['clock_domain_id'],descriptor=descriptor['descriptor_digest'],now_tick=P.u(tick))
        write('ct_change',**change);after={k:v for k,v in state.items() if k!='device_id'};after.update(change_id=ident,record_revision=P.u(int(state['record_revision'])+1),gate_state='protected')
        body=S.control_body(db,after);after.update(record_digest=body['record_digest'],record_body=M.raw(body));write('ct_state',**after)
        value=M.sealed(dict(format_version='protected-domain-transition/0.1.0-draft.1',transition_id=ident,revision='1',before_control_ref=S.control_ref(before),after_control_ref=S.control_ref(body),new_clock_descriptor=descriptor,provider_ref=provider,selected_tick_ns=str(int(P.u(tick)))),'transition_digest');validate('ProtectedDomainTransition',value);raw=M.raw(value)
        write('gso_transition',change_id=ident,digest=value['transition_digest'],body=raw)
        write('ct_audit',change_id=ident,body=raw);write('ct_outbox',change_id=ident,event_id=ident,body=raw);write('ct_commit',change_id=ident)
        read(db,ident);return value,writes
    return N.transaction(db,run)
