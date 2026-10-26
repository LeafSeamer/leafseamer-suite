"""从同一监督SQLite快照读取完整退役原件；只验证关联，不执行OS观察。"""
import hashlib,json
import rfc8785
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
import build_retirement_source as G
HERE=G.HERE;MAX_MEMBERS=256;MAX_BODY=262144;MAX_BUNDLE=16777216
FILES=[HERE/'supervisor.schema.json',HERE.parent/'draft4/first-loop.schema.json',HERE.parent/'c09-installation/installation-v02.schema.json']
REGISTRY=Registry().with_resources((s['$id'],Resource.from_contents(s)) for s in [G.schema()]+[json.loads(p.read_bytes()) for p in FILES])
class SourceError(ValueError):pass
def need(v,why):
    if not v:raise SourceError(why)
def raw(v):return rfc8785.dumps(v)
def digest(v):return 'sha256:'+hashlib.sha256(raw(v)).hexdigest()
def validate(name,v):Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=REGISTRY).validate(v)
def sup(name,v):Draft202012Validator({'$ref':G.SUP+'#/$defs/'+name},registry=REGISTRY).validate(v)
def document(data):
    need(isinstance(data,bytes) and 0<len(data)<=MAX_BODY,'source_body_size')
    def pairs(items):
        result={}
        for k,v in items:need(k not in result,'duplicate_key');result[k]=v
        return result
    value=json.loads(data,object_pairs_hook=pairs);need(raw(value)==data,'source_not_canonical');return value
def one(db,sql,args=()):
    c=db.execute(sql,args);rows=c.fetchmany(2);need(len(rows)==1,'source_cardinality');return dict(zip([d[0] for d in c.description],rows[0]))
def many(db,sql,args=()):
    c=db.execute(sql,args);rows=c.fetchmany(MAX_MEMBERS+1);need(len(rows)<=MAX_MEMBERS,'source_member_capacity');return [dict(zip([d[0] for d in c.description],r)) for r in rows]
def domain(d):return {k:d[k] for k in ('clock_domain_id','descriptor_digest')}
def runtime(db,sid):
    row=one(db,'SELECT * FROM runtime WHERE supervisor_id=?',(sid,));d=document(row['descriptor_jcs']);sup('ClockDomainDescriptor',d)
    h=digest({k:v for k,v in d.items() if k not in ('clock_domain_id','descriptor_digest')})
    need(d['descriptor_digest']==h==row['descriptor_digest'] and d['clock_domain_id']=='clock_'+h[7:]==row['domain_id'],'runtime_digest')
    need(d['authority_service_id']==row['service_id'] and d['supervisor_instance_id']==sid and d['runtime_generation']==row['runtime_generation'],'runtime_projection')
    return row,d
def capture(db,sid,evidence_id,source,evaluator_domain,now_tick):
    need(not db.in_transaction,'source_nested_transaction');validate('SourceIdentity',source);sup('ClockDomainRef',evaluator_domain);sup('U20',now_tick)
    try:
        db.execute('BEGIN');rows=[]
        def save(row):rows.append({k:({'blob_hex':v.hex()} if isinstance(v,bytes) else v) for k,v in row.items()});return row
        meta=save(one(db,'SELECT * FROM journal_meta WHERE singleton=1'))
        need(meta['host_installation_id']==source['host_installation_id'] and meta['incarnation_id']==source['incarnation_id'] and meta['format_version']=='supervisor-journal/0.1.0-draft.1','source_identity')
        old,descriptor=runtime(db,sid);save(old);scope=save(one(db,'SELECT * FROM control_scope WHERE supervisor_id=?',(sid,)))
        need(old['service_id']==scope['service_id']==source['service_id'] and scope['database_instance_id']==source['database_instance_id'],'source_scope')
        expected_scope=dict(service_id=source['service_id'],database_instance_id=source['database_instance_id'],supervisor_instance_id=sid,domain_ref=domain(descriptor))
        need(document(scope['scope_jcs'])==expected_scope,'scope_projection')
        e=save(one(db,'SELECT * FROM retirement_evidence WHERE supervisor_id=? AND evidence_id=?',(sid,evidence_id)));value=document(e['evidence_jcs']);sup('RetirementEvidence',value)
        observer,od=runtime(db,e['observer_supervisor_id']);save(observer)
        need(domain(od)==evaluator_domain and observer['service_id']==source['service_id'] and observer['phase']=='active','evaluator_identity')
        need(e['sealed']==1 and e['result']==value['result']=='confirmed_empty' and value['evidence_id']==evidence_id and value['service_id']==source['service_id'] and value['old_domain_ref']==domain(descriptor) and value['evaluator_domain_ref']==evaluator_domain and value['target_scope']==e['target_scope'] and value['launch_intake_closed'],'retirement_projection')
        targets=many(db,'SELECT * FROM retirement_target WHERE supervisor_id=? AND evidence_id=? ORDER BY launch_id',(sid,evidence_id));[save(t) for t in targets]
        need(len(targets)==e['target_count'],'retirement_target_count')
        if e['target_scope']=='runtime_domain':
            all_targets=many(db,'SELECT launch_id FROM launch_intent WHERE supervisor_id=? ORDER BY launch_id',(sid,))
            need([t['launch_id'] for t in targets]==[t['launch_id'] for t in all_targets] and old['phase']=='retired' and old['domain_retirement_id']==evidence_id,'runtime_coverage')
            containment=dict(group_id=old['root_group_id'],generation=old['root_group_generation'],backend=old['root_backend'])
        else:need(len(targets)==1 and targets[0]['launch_id']==e['target_launch_id'],'group_coverage');containment=None
        members=[]
        for t in targets:
            lid=t['launch_id'];r=save(one(db,'SELECT * FROM launch_intent WHERE supervisor_id=? AND launch_id=?',(sid,lid)));intent=document(r['intent_jcs']);sup('ExtensionLaunchIntent' if r['role']=='worker' else 'LaunchIntent',intent)
            need(digest(intent)==r['intent_digest'] and intent['launch_id']==lid and intent['supervisor_instance_id']==sid and intent['runtime_generation']==old['runtime_generation'] and intent['service_id']==source['service_id'] and intent['member_id']==r['member_id'] and intent['role']==r['role'] and intent['containment_ref']['group_id']==r['group_id'] and intent['containment_ref']['generation']==r['group_generation'],'intent_projection')
            if containment is None:containment=intent['containment_ref']
            state=save(one(db,'SELECT * FROM launch_state WHERE supervisor_id=? AND launch_id=?',(sid,lid)))
            need(state['state'] in ('retired','rejected') and (state['state']=='rejected' or state['retirement_id'] is not None),'member_not_terminal')
            if e['target_scope']=='member_group':need(state['retirement_id']==evidence_id,'group_retirement_identity')
            receipt=None
            if state['admission_id'] is not None:
                a=save(one(db,'SELECT * FROM admission_receipt WHERE supervisor_id=? AND launch_id=?',(sid,lid)));receipt=document(a['receipt_jcs']);sup('AdmissionReceipt',receipt)
                b=save(one(db,'SELECT * FROM bootstrap_challenge WHERE supervisor_id=? AND launch_id=?',(sid,lid)))
                need(receipt['receipt_id']==a['receipt_id']==state['admission_id'] and receipt['bootstrap_id']==a['bootstrap_id']==b['bootstrap_id'] and receipt['member_boot_id']==b['member_boot_id'] and receipt['channel_binding_id']==b['channel_binding_id'],'admission_identity')
                need(receipt['launch_id']==lid and receipt['launch_intent_digest']==r['intent_digest'] and receipt['member_id']==r['member_id'] and receipt['role']==r['role'] and receipt['artifact_manifest_ref']==intent['artifact_manifest_ref'] and receipt['domain_ref']==domain(descriptor) and receipt['containment_ref']==intent['containment_ref'] and receipt['admitted_tick_ns']==a['admitted_tick'],'admission_projection')
                need(receipt['os_observation_ref']==a['process_observation_id'] and int(b['issued_tick'])<=int(a['admitted_tick'])<int(b['expires_tick']),'admission_window')
            members.append(dict(intent=intent,admission_receipt=receipt,state=state['state']))
        mids=sorted(m['intent']['member_id'] for m in members)
        need(sorted(value['target_member_ids'])==mids and len(mids)==len(set(mids)) and value['containment_ref']==containment,'evidence_coverage')
        need(value['os_observation_refs']==[e['observation_id']],'observation_exact_set')
        o=save(one(db,'SELECT * FROM os_observation WHERE observation_id=?',(e['observation_id'],)));observation=document(o['evidence_jcs']);validate('Observation',observation)
        need(o['subject_supervisor_id']==sid and o['observer_supervisor_id']==e['observer_supervisor_id'] and o['subject_launch_id']==e['target_launch_id'] and o['kind']==('domain_exit' if e['target_scope']=='runtime_domain' else 'group_exit'),'observation_projection')
        need(observation['observation_id']==o['observation_id'] and observation['provider_id']==source['os_provider_id'] and observation['subject_domain_ref']==domain(descriptor) and observation['evaluator_domain_ref']==domain(od) and observation['containment_ref']==containment and o['group_id']==containment['group_id'] and o['group_generation']==containment['generation'] and sorted(observation['target_member_ids'])==mids,'observation_binding')
        need(observation['observed_tick_ns']==o['observed_tick']==value['observed_tick_ns'] and int(o['observed_tick'])<=int(now_tick),'observer_time')
        result=dict(format_version='retirement-source/0.1.0-draft.1',source=source,old_descriptor=descriptor,evaluator_descriptor=od,evidence=value,members=members,observations=[observation],journal_snapshot_digest=digest(rows))
        result['bundle_digest']=digest(result);validate('Bundle',result);need(len(raw(result))<=MAX_BUNDLE,'bundle_capacity');db.commit();return result
    except Exception:
        if db.in_transaction:db.rollback()
        raise
