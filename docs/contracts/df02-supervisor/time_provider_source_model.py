"""从受信监督连接读取时间提供者准入快照；不把快照当持续OS活性证明。"""
import copy,json
from jsonschema import Draft202012Validator
from referencing import Resource
import retirement_source_model as S
import build_time_provider_source as G

REGISTRY=S.REGISTRY.with_resource(G.SID,Resource.from_contents(G.schema()))
TIME=json.loads((G.HERE.parent/'df03-reference/reference.schema.json').read_bytes())
need=S.need;one=S.one;raw=S.raw;digest=S.digest
def validate(name,value):Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=REGISTRY).validate(value)
def reference(value):return dict(id=value['binding_id'],revision=value['revision'],digest=value['binding_digest'])


def capture(db,sid,lid,source):
    need(not db.in_transaction,'provider_source_nested_transaction');S.validate('SourceIdentity',source)
    try:
        db.execute('BEGIN')
        meta=one(db,'SELECT * FROM journal_meta WHERE singleton=1')
        need(all(meta[k]==source[k] for k in ('host_installation_id','incarnation_id')),'provider_journal_identity')
        runtime,descriptor=S.runtime(db,sid)
        need(runtime['phase']=='active' and runtime['service_id']==source['service_id'],'provider_runtime_closed')
        scope=one(db,'SELECT * FROM control_scope WHERE supervisor_id=?',(sid,))
        need(scope['database_instance_id']==source['database_instance_id'] and S.document(scope['scope_jcs'])==
            dict(service_id=source['service_id'],database_instance_id=source['database_instance_id'],supervisor_instance_id=sid,domain_ref=S.domain(descriptor)),'provider_scope')
        row=one(db,'SELECT * FROM launch_intent WHERE supervisor_id=? AND launch_id=?',(sid,lid))
        intent=S.document(row['intent_jcs']);S.sup('ProtectedLaunchIntent',intent)
        need(row['role']==intent['role']=='time_provider' and row['origin']=='protected_config','provider_role')
        need(digest(intent)==row['intent_digest'] and intent['launch_id']==lid and intent['supervisor_instance_id']==sid and
            intent['runtime_generation']==runtime['runtime_generation'] and intent['service_id']==source['service_id'] and
            intent['member_id']==row['member_id'] and (intent['containment_ref']['group_id'],intent['containment_ref']['generation'])==(row['group_id'],row['group_generation']),'provider_intent')
        need(S.document(row['origin_binding_jcs'])==dict(protected_policy_digest=runtime['protected_policy_digest'],intent_digest=row['intent_digest']),'provider_protected_origin')
        state=one(db,'SELECT * FROM launch_state WHERE supervisor_id=? AND launch_id=?',(sid,lid))
        need(state['state']=='admitted_closed' and state['creation_attempted']==1 and state['retirement_id'] is None,'provider_member_closed')
        attempt=one(db,'SELECT * FROM creation_attempt WHERE supervisor_id=? AND launch_id=?',(sid,lid))
        need(all(attempt[k] is None for k in ('fence_revision','authorization_jcs','materialization_observation_id')),'provider_protected_attempt')
        receipt_row=one(db,'SELECT * FROM admission_receipt WHERE supervisor_id=? AND launch_id=?',(sid,lid))
        receipt=S.document(receipt_row['receipt_jcs']);S.sup('AdmissionReceipt',receipt)
        boot=one(db,'SELECT * FROM bootstrap_challenge WHERE supervisor_id=? AND launch_id=?',(sid,lid))
        need(receipt['receipt_id']==receipt_row['receipt_id']==state['admission_id'] and
            receipt['bootstrap_id']==receipt_row['bootstrap_id']==boot['bootstrap_id'] and
            receipt['member_boot_id']==boot['member_boot_id'] and receipt['channel_binding_id']==boot['channel_binding_id'],'provider_bootstrap')
        need(receipt['launch_id']==lid and receipt['launch_intent_digest']==row['intent_digest'] and
            receipt['member_id']==intent['member_id'] and receipt['role']=='time_provider' and
            receipt['artifact_manifest_ref']==intent['artifact_manifest_ref'] and receipt['containment_ref']==intent['containment_ref'] and
            receipt['domain_ref']==S.domain(descriptor) and receipt['admitted_tick_ns']==receipt_row['admitted_tick'],'provider_admission')
        need(int(attempt['origin_tick'])<=int(boot['issued_tick'])<=int(receipt_row['admitted_tick'])<int(boot['expires_tick']),'provider_admission_window')
        obs=one(db,'SELECT * FROM os_observation WHERE observation_id=?',(receipt_row['process_observation_id'],))
        observation=S.document(obs['evidence_jcs']);validate('ProcessObservation',observation)
        need(obs['kind']=='process_instance' and obs['subject_supervisor_id']==obs['observer_supervisor_id']==sid and obs['subject_launch_id']==lid and
            observation['observation_id']==obs['observation_id']==receipt['os_observation_ref'] and observation['provider_id']==source['os_provider_id'] and
            observation['domain_ref']==S.domain(descriptor) and observation['containment_ref']==intent['containment_ref'] and
            (obs['group_id'],obs['group_generation'])==(row['group_id'],row['group_generation']) and
            observation['observed_tick_ns']==obs['observed_tick'] and int(boot['issued_tick'])<=int(obs['observed_tick'])<=int(receipt['admitted_tick_ns']) and
            all(observation[k]==receipt[k] for k in ('member_id','member_boot_id','channel_binding_id','artifact_manifest_ref')),'provider_process_observation')
        value=dict(format_version='time-provider-runtime/0.1.0-draft.1',revision='1',source=copy.deepcopy(source),descriptor=descriptor,
            intent=intent,admission_receipt=receipt,process_observation=observation)
        value['binding_id']='time-runtime.'+digest(value)[7:];value['binding_digest']=digest(value);validate('ProviderRuntime',value)
        db.commit();return value
    except Exception:
        if db.in_transaction:db.rollback()
        raise


def verify_domain(value,domain):
    validate('ProviderRuntime',value)
    Draft202012Validator({'$defs':TIME['$defs'],'$ref':'#/$defs/Domain'}).validate(domain)
    need(value['binding_digest']==digest({k:v for k,v in value.items() if k!='binding_digest'}),'provider_binding_digest')
    stable={k:v for k,v in value.items() if k not in ('binding_id','binding_digest')}
    need(value['binding_id']=='time-runtime.'+digest(stable)[7:],'provider_binding_id')
    expected=dict(authority_service_id=value['source']['service_id'],database_instance_id=value['source']['database_instance_id'],
        provider_id=value['intent']['member_id'],provider_boot_id=value['admission_receipt']['member_boot_id'],runtime_binding_ref=reference(value),**S.domain(value['descriptor']))
    need(all(domain.get(k)==v for k,v in expected.items()),'provider_time_domain')
    # clock_generation由Controller时间State管理，不把不透明runtime_generation强制转成整数。
    return True
