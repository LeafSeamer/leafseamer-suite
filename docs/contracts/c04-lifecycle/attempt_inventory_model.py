"""固定修订库存的SQLite参考装配与读取；不实现真实身份、TIME或设备提供者。"""
import copy,json
import attempt_projection_model as A
import command_evidence_model as E
import build_attempt_inventory as G
M=A.M;P=M.P;R=M.R;I=M.I;need=M.need;digest=M.digest;raw=M.raw

def transmission(p,committed,exit_row,command):
    body=json.loads(p['permit_body']);M.validate('TransmissionPermit',body)
    t=body['transmission'];intent=t['intent'];original=json.loads(committed['dispatch_intent_body'])
    need((body['permit_id'],body['command_id'],body['attempt_id'],t['packet_ref']['packet_id'],intent['attempt_id'],t['ordinal'])==
        (p['permit_id'],command,p['attempt_id'],p['packet_id'],p['attempt_id'],str(p['ordinal'])),'inventory_permit_columns')
    need(committed['permit_id']==p['permit_id'] and all(original.get(k)==v for k,v in intent.items()),'inventory_intent_original')
    need(intent['command_id']==command and intent['permit_id']==p['permit_id'] and all(body[k]==intent[k] for k in set(body)&set(intent)),'inventory_permit_intent')
    need(p['exit_id']==exit_row['exit_id'] and all(intent[k]==exit_row[k] for k in A.EXIT_FIELDS if k!='exit_id'),'inventory_permit_exit')
    return dict(permit_id=p['permit_id'],packet_id=p['packet_id'],attempt_id=p['attempt_id'],exit_id=p['exit_id'],ordinal=p['ordinal'],transmission_id=t['transmission_id'],dispatch_intent_id=intent['dispatch_intent_id'])

def capture(db,command,revision,provider,*,cut=None):
    need(db.in_transaction,'inventory_transaction_required');rev=M.U(revision)
    state_row=P.rows(db,'SELECT * FROM cm_revision WHERE command_id=? AND revision=?',(command,rev))[0]
    state=json.loads(state_row['state_body']);scope=M.C.scope(db)
    need(provider['state_ref']==M.V.state_ref(state) and provider['scope']==scope,'inventory_provider_binding')
    need(all(provider[k] is True for k in ('originals_verified','redaction_verified','decisions_verified','time_verified')),'inventory_provider')
    maximum=provider['max_members'];need(type(maximum) is int and 1<=maximum<=4096,'inventory_member_profile')
    byte_limit=provider['max_inventory_bytes'];need(type(byte_limit) is int and 1<=byte_limit<=16777216,'inventory_byte_profile')
    bundle_limit=provider['max_bundle_bytes'];need(type(bundle_limit) is int and 1<=bundle_limit<=16777216,'inventory_bundle_profile')
    def fetch(sql,args,key,group,ids=None):
        expected=None
        if cut is not None:
            expected=ids if ids is not None else [r[key.split('.')[-1]] for r in cut[group]]
            need(len(expected)==len(set(expected)) and len(expected)<=maximum,'inventory_duplicate_cut')
            sql+=' AND '+key+' IN (SELECT value FROM json_each(?))';args=(*args,json.dumps(expected))
        rows=P.rows(db,sql+' ORDER BY '+key+' LIMIT ?',(*args,maximum+1));need(len(rows)<=maximum,'inventory_member_capacity')
        if expected is not None:need({r[key.split('.')[-1]] for r in rows}==set(expected),'inventory_original_missing')
        return rows
    attempts=P.rows(db,'SELECT a.* FROM cm_attempt a JOIN cm_revision_attempt r USING(attempt_id) WHERE r.command_id=? AND r.revision=? ORDER BY a.ordinal',(command,rev))
    need([a['attempt_id'] for a in attempts]==state['attempt_ids'],'inventory_attempt_set')
    for a in attempts:need(a['command_id']==command and R.one(db,'ce_attempt','attempt_id',a['attempt_id'])['command_id']==command,'inventory_attempt_owner')
    packet_rows=fetch('SELECT p.* FROM ce_packet p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=? AND a.revision=?',(command,rev),'p.packet_id','packets')
    packets=[]
    for p in packet_rows:
        b=json.loads(p['packet_body']);need((b['packet_id'],b['attempt_id'],b['writer_exit_id'],b['primitive_id'])==(p['packet_id'],p['attempt_id'],p['exit_id'],p['primitive_id']),'inventory_packet_columns');packets.append(b)
    assignment_rows=fetch("SELECT p.* FROM ep_request p JOIN cm_revision_attempt a ON a.attempt_id=p.proposed_attempt_id WHERE a.command_id=? AND a.revision=? AND p.kind='ordinary'",(command,rev),'p.prepare_id','assignments')
    assignments=[]
    for a in assignment_rows:
        need(a['command_id']==command and db.execute('SELECT 1 FROM ep_request_commit WHERE prepare_id=?',(a['prepare_id'],)).fetchone(),'inventory_assignment_original')
        assignments.append(dict(prepare_id=a['prepare_id'],attempt_id=a['proposed_attempt_id'],exit_id=a['exit_id'],command_id=a['command_id'],request_digest=a['request_digest']))
    exit_ids=sorted({p['exit_id'] for p in packet_rows}|{a['exit_id'] for a in assignments})
    exits=[]
    for eid in exit_ids:
        row=R.one(db,'ce_exit','exit_id',eid);exits.append({k:row[k] for k in A.EXIT_FIELDS})
    attempt_views=[]
    for a in attempts:
        prepared=P.rows(db,'SELECT * FROM cm_revision WHERE command_id=? AND revision=?',(command,a['prepared_revision']))[0]
        need(prepared['kind']=='prepare' and digest(json.loads(prepared['state_body']))==prepared['state_digest'],'inventory_prepared_original')
        attempt_views.append(dict(attempt_id=a['attempt_id'],ordinal=a['ordinal'],prepared_state=json.loads(prepared['state_body']),
            exit_ids=sorted({p['exit_id'] for p in packet_rows if p['attempt_id']==a['attempt_id']}|{x['exit_id'] for x in assignments if x['attempt_id']==a['attempt_id']})))
    permit_rows=fetch('SELECT p.* FROM ce_permit p JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=? AND a.revision=?',(command,rev),'p.permit_id','transmissions')
    transmissions=[]
    for p in permit_rows:
        transmissions.append(transmission(p,R.one(db,'ce_transmission_commit','permit_id',p['permit_id']),R.one(db,'ce_exit','exit_id',p['exit_id']),command))
    report_rows=fetch('SELECT r.* FROM ce_report r JOIN ce_permit p USING(permit_id) JOIN cm_revision_attempt a USING(attempt_id) WHERE a.command_id=? AND a.revision=?',(command,rev),'r.report_id','reports')
    reports=[]
    for r in report_rows:
        receipt=R.one(db,'cm_report_receipt','stored_report_id',r['report_id']);body=json.loads(r['evidence_body']);ex=R.one(db,'ce_exit','exit_id',r['exit_id'])
        need(receipt['command_id']==command and receipt['revision']<=rev and receipt['report_digest']==digest(body),'inventory_report_receipt')
        need((receipt['worker_boot_id'],receipt['ipc_session_id'])==(ex['worker_boot_id'],ex['ipc_session_id']),'inventory_report_origin')
        need((body['permit_id'],body['disposition'],body['proof'])==(r['permit_id'],r['disposition'],r['proof']),'inventory_report_columns')
        reports.append(dict(report_id=r['report_id'],worker_report_id=receipt['worker_report_id'],exit_id=r['exit_id'],worker_boot_id=receipt['worker_boot_id'],ipc_session_id=receipt['ipc_session_id'],body=body))
    # 证据已有first_state_revision且不可改，历史无需借最新全集或调用方传入成员。
    evidence_rows=P.rows(db,'SELECT * FROM cv_evidence WHERE command_id=? AND first_state_revision<=? ORDER BY evidence_id,revision LIMIT ?',(command,rev,maximum+1))
    need(len(evidence_rows)<=maximum,'inventory_member_capacity');evidence=[E.evidence(r,scope,command) for r in evidence_rows]
    valid=provider['valid_decision_refs'];need(len(valid)==len({raw(x) for x in valid}),'inventory_duplicate_validity')
    need(all(r in [e['source_ref'] for e in evidence if e['kind']=='decision'] for r in valid),'inventory_validity_original')
    inventory=dict(scope=scope,command_id=command,state=state,state_ref=M.V.state_ref(state),complete=True,originals_verified=True,redaction_verified=True,
        attempts=attempt_views,packets=packets,exits=exits,transmissions=transmissions,reports=reports,evidence=evidence,assignments=assignments,
        valid_decision_refs=copy.deepcopy(valid),time_projections=copy.deepcopy(provider['time_projections']))
    need(len(raw(inventory))<=byte_limit,'inventory_byte_capacity')
    if cut is not None:need(inventory==cut,'inventory_original_changed')
    return inventory

def publication_steps(db,command,revision,inventory,selections,provider):
    need(db.in_transaction,'inventory_transaction_required');rev=M.U(revision)
    need(not db.execute('SELECT 1 FROM cm_commit WHERE command_id=? AND revision=?',(command,rev)).fetchone(),'inventory_already_published')
    actual=capture(db,command,revision,provider);need(actual==inventory,'inventory_capture_changed')
    row=P.rows(db,'SELECT * FROM cv_record WHERE command_id=? AND revision=?',(command,rev))[0];record=json.loads(row['record_body'])
    projection=A.project(record,actual,selections);A.verify(record,actual,selections,projection)
    need(sum(len(raw(v)) for v in (actual,selections,projection,provider))<=provider['max_bundle_bytes'],'inventory_bundle_capacity')
    return [I('av_snapshot',command_id=command,revision=rev,inventory_digest=digest(actual),inventory_body=raw(actual),selection_digest=digest(selections),selection_body=raw(selections),
        projection_digest=projection['projection_digest'],projection_body=raw(projection),provider_digest=digest(provider),provider_body=raw(provider))]

def source(db,command,revision):
    need(db.in_transaction,'inventory_transaction_required')
    rows=P.rows(db,'SELECT * FROM av_snapshot WHERE command_id=? AND revision=?',(command,M.U(revision)));need(len(rows)==1,'attempt_originals_unavailable');s=rows[0]
    inventory=json.loads(s['inventory_body']);selections=json.loads(s['selection_body']);projection=json.loads(s['projection_body']);provider=json.loads(s['provider_body'])
    need(sum(len(s[k]) for k in ('inventory_body','selection_body','projection_body','provider_body'))<=provider['max_bundle_bytes'],'inventory_bundle_capacity')
    need(digest(inventory)==s['inventory_digest'] and digest(selections)==s['selection_digest'] and digest(provider)==s['provider_digest'],'inventory_stored_digest')
    need(projection['projection_digest']==s['projection_digest'] and M.V.valid_digest(projection,'projection_digest'),'inventory_projection_digest')
    capture(db,command,revision,provider,cut=inventory)
    return inventory,selections,projection

def read(db,command,auth,revision=None):return M.read(db,command,auth,revision,attempt_source=source)
def page(db,command,revision,limit,auth,clock,keys,cursor=None):return E.page(db,command,revision,limit,auth,clock,keys,cursor,attempt_source=source)
