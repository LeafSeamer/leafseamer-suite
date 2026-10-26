"""采用可信监督库快照到既有出口；撤回证明不复活旧发送会话。"""
import json,sys
from jsonschema import Draft202012Validator
from referencing import Resource
import authorization_prepare_closure_model as N
import build_supervisor_retirement_adoption as G
sys.path.append(str(G.HERE.parent/'df02-supervisor'))
import retirement_source_model as S
M=N.M;P=N.P;I=N.I;HERE=G.HERE
REGISTRY=S.REGISTRY.with_resources((s['$id'],Resource.from_contents(s)) for s in (G.schema(),json.loads(G.ENC.read_bytes())))
def validate(name,v):Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=REGISTRY).validate(v)
def install(db):
    M.need(not db.in_transaction and db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('ce_exit','ce_retirement','cu_revocation','ij_write_attempt','authorization_close_ack')").fetchone()[0]==5,'supervisor_retirement_layout')
    db.executescript((HERE/'supervisor-retirement-adoption.sql').read_text('utf-8'))
def runtime(db,eid):
    e=M.E.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,));r=M.document(e['runtime_binding_body']);validate('RuntimeExitBinding',r)
    M.need(r==M.sealed(r,'binding_digest') and r['binding']['writer_exit_id']==eid and r['binding']['scope']==M.E.A.scope(db),'runtime_binding_identity')
    M.need(all(r['binding'][k]==e[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_session_id','device_id','clock_domain_id','descriptor_digest')),'runtime_exit_projection')
    a=r['admission_receipt'];intent=r['intent'];scope=r['binding']['scope']
    M.need(r['source']['service_id']==scope['authority_service_id'] and r['source']['database_instance_id']==scope['database_instance_id'] and intent['service_id']==scope['authority_service_id'],'runtime_source_scope')
    M.need(a['launch_id']==intent['launch_id'] and a['launch_intent_digest']==S.digest(intent) and a['member_id']==intent['member_id'] and a['member_boot_id']==e['worker_boot_id'] and a['role']==intent['role']=='worker' and a['containment_ref']==intent['containment_ref'] and a['artifact_manifest_ref']==intent['artifact_manifest_ref'] and e['device_id'] in intent['device_ids'],'runtime_admission_binding')
    M.need(a['domain_ref']==dict(clock_domain_id=e['clock_domain_id'],descriptor_digest=e['descriptor_digest']),'runtime_domain')
    return r,e
def bound_bundle(runtime,bundle):
    S.validate('Bundle',bundle);M.need(bundle['bundle_digest']==S.digest({k:v for k,v in bundle.items() if k!='bundle_digest'}) and bundle['source']==runtime['source'],'retirement_bundle_source')
    M.need(S.domain(bundle['old_descriptor'])==runtime['admission_receipt']['domain_ref'] and bundle['old_descriptor']['supervisor_instance_id']==runtime['intent']['supervisor_instance_id'],'retirement_bundle_domain')
    matches=[m for m in bundle['members'] if m['intent']['member_id']==runtime['intent']['member_id']]
    M.need(len(matches)==1 and matches[0]['intent']==runtime['intent'] and matches[0]['admission_receipt']==runtime['admission_receipt'] and matches[0]['state']=='retired','retirement_bundle_member')
def read(db,eid):
    r,e=runtime(db,eid);row=M.E.one(db,'SELECT * FROM sr_adoption WHERE exit_id=?',(eid,));v=M.document(row['body']);validate('RetirementAdoption',v);bound_bundle(r,v['source_bundle'])
    M.need(v==M.sealed(v,'adoption_digest') and v['adoption_id']==row['adoption_id'] and v['adoption_digest']==row['digest'] and v['binding']==r['binding'] and v['runtime_binding_ref']==M.reference(r,'binding_id','binding_digest') and row['binding_digest']==r['binding_digest'] and row['source_bundle_digest']==v['source_bundle']['bundle_digest'],'retirement_adoption_binding')
    old=M.E.one(db,'SELECT * FROM ce_retirement WHERE exit_id=?',(eid,));k=M.E.one(db,'SELECT * FROM sr_commit WHERE exit_id=?',(eid,));M.need(old['supervisor_evidence_body']==row['body']==k['outbox_body'],'retirement_adoption_seal')
    return v
def current(db,eid):return db.execute('SELECT 1 FROM sr_current WHERE exit_id=?',(eid,)).fetchone() is not None
def replay(db,eid,sid,evidence_id):
    old=read(db,eid);b=old['source_bundle']
    M.need(b['old_descriptor']['supervisor_instance_id']==sid and b['evidence']['evidence_id']==evidence_id,'retirement_replay_identity')
    return old,current(db,eid),[]
def adopt(db,eid,supervisor_db,sid,evidence_id,evaluator_domain,now_tick,fail_after=None):
    # 只接受已经打开的受信监督连接；不接受网络JSON自行重算摘要充当证明。
    M.need(not db.in_transaction,'retirement_nested_transaction')
    if db.execute('SELECT 1 FROM sr_adoption WHERE exit_id=?',(eid,)).fetchone():return N.transaction(db,lambda:replay(db,eid,sid,evidence_id))
    r,_=runtime(db,eid);bundle=S.capture(supervisor_db,sid,evidence_id,r['source'],evaluator_domain,now_tick);bound_bundle(r,bundle)
    def run():
        writes,write=N.writer(db,fail_after);actual,e=runtime(db,eid);M.need(actual==r,'runtime_binding_changed')
        if db.execute('SELECT 1 FROM sr_adoption WHERE exit_id=?',(eid,)).fetchone():
            old,valid,_=replay(db,eid,sid,evidence_id)
            M.need(all(old['source_bundle'][k]==bundle[k] for k in ('source','old_descriptor','evaluator_descriptor','evidence','members','observations')),'retirement_replay_conflict');return old,valid,writes
        state=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(e['device_id'],));M.need(state['gate_state']=='protected','retirement_requires_protection')
        ident=P.identity('supervisor_retirement',dict(exit_id=eid,bundle_digest=bundle['bundle_digest']))
        value=M.sealed(dict(format_version='supervisor-retirement-adoption/0.1.0-draft.1',adoption_id=ident,revision='1',binding=r['binding'],runtime_binding_ref=M.reference(r,'binding_id','binding_digest'),source_bundle=bundle),'adoption_digest');validate('RetirementAdoption',value)
        write('sr_adoption',exit_id=eid,adoption_id=ident,digest=value['adoption_digest'],binding_digest=r['binding_digest'],source_bundle_digest=bundle['bundle_digest'],body=M.raw(value))
        write('ce_retirement',exit_id=eid,supervisor_evidence_body=M.raw(value));write('sr_commit',exit_id=eid,audit_body=M.raw(value),outbox_body=M.raw(value));read(db,eid);M.need(current(db,eid),'retirement_not_current');return value,True,writes
    return N.transaction(db,run)
def revoke(db,eid,reason):
    def run():
        read(db,eid);proof=M.raw(reason);M.need(isinstance(reason,dict) and reason and len(proof)<=262144,'retirement_revocation_reason')
        old=db.execute("SELECT reason_body FROM cu_revocation WHERE kind='retirement' AND object_id=?",(eid,)).fetchone()
        if old:M.need(old[0]==proof,'retirement_revocation_conflict');return 'lookup_only'
        db.execute(*I('cu_revocation',kind='retirement',object_id=eid,reason_body=proof,audit_body=proof));M.need(not current(db,eid),'retirement_revocation_not_applied');return 'revoked'
    return N.transaction(db,run)
