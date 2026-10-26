"""同库原件采用与撤回；批准权威和监督闭锁尚未实现，不授运行资格。"""
import copy,importlib.util,json,sys
from jsonschema import Draft202012Validator
from referencing import Resource
import build_provider_adoption as G
sys.path.append(str(G.BASE/'df02-supervisor'))
import time_provider_source_model as P
spec=importlib.util.spec_from_file_location('provider_gate_source',G.BASE/'df03-service/gate_snapshot_source_model.py')
F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)
T=F.T;raw=F.raw;need=F.need;one=F.one
REGISTRY=P.REGISTRY.with_resources((s['$id'],Resource.from_contents(s)) for s in (G.CHANNEL,G.TIME,G.schema()))
def validate(name,v):Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=REGISTRY).validate(v)
def cref(value,kind):return T.object_ref(value,kind+'_id',kind+'_digest')
def receipt_ref(runtime):return dict(id=runtime['admission_receipt']['receipt_id'],revision='1',digest=T.digest(runtime['admission_receipt']))
def insert(table,*args):return ('INSERT INTO '+table+' VALUES('+','.join('?' for _ in args)+')',args)
def install(db):
    need(not db.in_transaction,'provider_install_transaction')
    db.executescript((G.BASE/'df03-collector/collector-storage-v02.sql').read_text('utf-8'))
    db.executescript((G.HERE/'storage.sql').read_text('utf-8'))
def bound(runtime,channel,config):
    P.verify_domain(runtime,config['binding']['domain'])
    receipt=runtime['admission_receipt'];manifest=runtime['intent']['artifact_manifest_ref']
    need(channel['domain']==config['binding']['domain'] and channel['channel_id']==receipt['channel_binding_id'],'provider_channel_binding')
    need(config['bootstrap_receipt_ref']==channel['bootstrap_receipt_ref']==receipt_ref(runtime),'provider_receipt_binding')
    artifact=dict(id=manifest['manifest_id'],revision=manifest['revision'],digest=manifest['digest'])
    need(config['collector_artifact_ref']==config['profile']['collector_artifact_ref']==artifact,'provider_artifact_binding')
    need(T.intact(config,'config_digest'),'provider_config_digest')
    for k in ('source','profile','policy','approval'):
        need(T.intact(config[k],k+'_digest') and config['binding'][k+'_ref']==cref(config[k],k),'provider_config_original')
    approval=config['approval'];domain=config['binding']['domain']
    need(approval['status']=='approved' and approval['authority_service_id']==domain['authority_service_id'] and
        approval['source_ref']==config['binding']['source_ref'] and approval['profile_ref']==config['binding']['profile_ref'],'provider_approval_relation')
    # 上述只是原件关系，不能由结构上的approved推出真实当前批准。
    need(config['limits']['max_blob_bytes']<=config['profile']['max_packet_bytes'],'provider_packet_capacity')
def read(db,channel_id):
    need(db.in_transaction,'provider_read_transaction')
    a=one(db,'SELECT * FROM tp_adoption WHERE channel_id=?',(channel_id,));v=P.S.document(a['body']);validate('Adoption',v)
    need(T.intact(v,'adoption_digest') and v['adoption_id']==a['id'] and a['body']==a['audit_body']==a['outbox_body'],'provider_adoption_original')
    need(v['adoption_id']=='provider-adoption.'+T.digest(v['channel'])[7:],'provider_adoption_identity')
    delivery=one(db,'SELECT c.receipt_body,a.body AS audit,o.body AS outbox,z.body AS seal FROM ts_commit c '
        'JOIN ts_audit a ON a.commit_id=c.id JOIN ts_outbox o ON o.commit_id=c.id JOIN ts_seal z ON z.commit_id=c.id WHERE c.id=?',(a['bootstrap_commit'],))
    need(all(body==a['body'] for body in delivery.values()),'provider_adoption_delivery')
    runtime=v['runtime'];channel=v['channel'];config=v['configuration'];bound(runtime,channel,config)
    r=one(db,'SELECT * FROM tp_runtime WHERE id=?',(a['runtime_id'],))
    need(r['body']==raw(runtime) and r['id']==runtime['binding_id'] and r['digest']==runtime['binding_digest'],'provider_runtime_original')
    c=one(db,'SELECT * FROM tc_channel WHERE id=?',(channel_id,));b=one(db,'SELECT * FROM ts_binding WHERE id=?',(a['binding_id'],))
    need(c['body']==raw(channel) and channel_id==channel['channel_id'] and c['binding_id']==a['binding_id'] and
        c['config_id']==config['config_id'] and c['runtime_ref']==raw(P.reference(runtime)) and b['body']==raw(config['binding']),'provider_channel_original')
    need(v['binding_storage_id']==a['binding_id'] and v['bootstrap_commit_id']==a['bootstrap_commit'] and
        v['source_slot_id']==c['source_id'] and raw(v['interval_receipt_ref'])==c['interval_receipt'],'provider_storage_binding')
    source=one(db,'SELECT * FROM tc_source WHERE id=?',(c['source_id'],));need(source['body']==raw(config['source']),'provider_source_original')
    s=one(db,'SELECT * FROM ts_state WHERE commit_id=?',(a['bootstrap_commit'],));state=F.source(db,str(int(s['revision'])))
    need(state['status']=='collecting' and state['binding']==config['binding'] and v['bootstrap_state_ref']==cref(state,'state'),'provider_bootstrap_original')
    return v
def current(db):
    need(db.in_transaction,'provider_read_transaction')
    state=F.source(db,str(int(one(db,'SELECT revision FROM ts_head WHERE id=1')['revision'])))
    rid=state['binding']['domain']['runtime_binding_ref']['id']
    a=one(db,'SELECT channel_id FROM tp_adoption WHERE runtime_id=?',(rid,));v=read(db,a['channel_id'])
    P.verify_domain(v['runtime'],state['binding']['domain'])
    need(not db.execute('SELECT 1 FROM tp_revocation WHERE channel_id=?',(a['channel_id'],)).fetchone() and
        state['binding']==v['configuration']['binding'] and state['status'] in ('collecting','qualified'),'provider_revoked')
    return v,state,F.derive(state)
def transact(db,fn,fail_after=None,omit=None,commit_fault=False):
    need(not db.in_transaction,'provider_nested_transaction');writes=[]
    try:
        db.execute('BEGIN IMMEDIATE')
        def write(sql,args):
            index=len(writes);writes.append((sql,args))
            if index!=omit:db.execute(sql,args)
            if index==fail_after:raise RuntimeError('synthetic_write_fault')
        result=fn(write);db.commit()
        if commit_fault:raise RuntimeError('synthetic_commit_observation_lost')
        return result,writes
    except BaseException:
        if db.in_transaction:db.rollback()
        raise
def adopt(db,supervisor_db,sid,lid,source,channel,config,state,source_slot,binding_id,commit_id,interval_ref,**fault):
    need(not db.in_transaction,'provider_nested_transaction')
    # 核心配置与身份提供者仍是调用边界；实际生产必须在同一writer内复核其当前权威。
    runtime=P.capture(supervisor_db,sid,lid,source)
    value=T.seal(dict(format_version='time-provider-adoption/0.1.0-draft.1',adoption_id='provider-adoption.'+T.digest(channel)[7:],revision='1',
        runtime=runtime,channel=copy.deepcopy(channel),configuration=copy.deepcopy(config),bootstrap_state_ref=cref(state,'state'),
        source_slot_id=source_slot,binding_storage_id=binding_id,bootstrap_commit_id=commit_id,interval_receipt_ref=copy.deepcopy(interval_ref)),'adoption_digest')
    validate('Adoption',value);bound(runtime,channel,config);F.validate('AuthorityState',state);F.validate('Ref',interval_ref)
    need(T.intact(state,'state_digest') and state['revision']=='1' and state['binding']==config['binding'] and
        state['status']=='collecting' and state['current_anchor_ref'] is state['invalidation_ref'] is None,'provider_initial_state')
    def operation(write):
        old=db.execute('SELECT 1 FROM tp_adoption WHERE channel_id=?',(channel['channel_id'],)).fetchone()
        if old:
            need(read(db,channel['channel_id'])==value,'provider_adoption_conflict');return value
        need(not db.execute('SELECT 1 FROM ts_head').fetchone(),'provider_initial_only')
        sc=one(db,'SELECT * FROM ts_scope WHERE id=1');d=config['binding']['domain']
        need((sc['authority'],sc['database_id'])==(d['authority_service_id'],d['database_instance_id']),'provider_scope')
        need(one(db,'SELECT * FROM tc_source WHERE id=?',(source_slot,))['body']==raw(config['source']),'provider_source_original')
        write(*insert('tp_runtime',runtime['binding_id'],runtime['binding_digest'],raw(runtime)))
        write(*insert('ts_binding',binding_id,1,config['binding']['time_generation'].zfill(20),raw(config['binding'])))
        write(*insert('tp_adoption',channel['channel_id'],runtime['binding_id'],binding_id,commit_id,value['adoption_id'],raw(value),raw(value),raw(value)))
        write(*insert('ts_commit',commit_id,'bootstrap',raw(value)))
        write(*insert('ts_audit',commit_id,raw(value)));write(*insert('ts_outbox',commit_id,'notification',raw(value)))
        write(*insert('ts_state','1'.zfill(20),None,binding_id,'collecting',None,commit_id,raw(state)))
        write(*insert('ts_head',1,'1'.zfill(20)));write(*insert('ts_seal',commit_id,raw(value)))
        write(*insert('tc_channel',channel['channel_id'],source_slot,binding_id,config['config_id'],raw(P.reference(runtime)),raw(interval_ref),raw(channel)))
        read(db,channel['channel_id']);return value
    return transact(db,operation,**fault)
def revoke(db,channel_id,invalidation,commit_id,new_binding_id,stop_id,**fault):
    F.validate('Invalidation',invalidation);need(T.intact(invalidation,'invalidation_digest'),'provider_invalidation_digest')
    def operation(write):
        adoption=read(db,channel_id)
        value=T.seal(dict(format_version='time-provider-revocation/0.1.0-draft.1',revocation_id=stop_id,revision='1',
            adoption_ref=cref(adoption,'adoption'),invalidation_ref=cref(invalidation,'invalidation'),cause_ref=invalidation['cause_ref'],
            invalidation_commit_id=commit_id,next_binding_storage_id=new_binding_id),'revocation_digest');validate('Revocation',value)
        old=db.execute('SELECT * FROM tp_revocation WHERE channel_id=?',(channel_id,)).fetchone()
        if old:
            r=one(db,'SELECT * FROM tp_revocation WHERE channel_id=?',(channel_id,))
            need(r['body']==raw(value) and r['invalidation_commit']==commit_id and r['stop_id']==stop_id,'provider_revocation_conflict')
            i=one(db,'SELECT * FROM ts_invalidation WHERE commit_id=?',(commit_id,));stop=one(db,'SELECT * FROM tc_stop WHERE id=?',(stop_id,))
            need(i['body']==raw(invalidation) and i['new_binding']==new_binding_id and stop['body']==raw(value) and
                stop['invalidation_commit']==commit_id and stop['channel_id']==channel_id,'provider_revocation_original')
            state=one(db,'SELECT revision FROM ts_state WHERE commit_id=?',(commit_id,));F.source(db,str(int(state['revision'])))
            return value
        actual,state,_=current(db);need(actual==adoption and invalidation['old_binding']==state['binding'],'provider_invalidation_binding')
        need(int(invalidation['next_time_generation'])==int(state['binding']['time_generation'])+1,'provider_invalidation_generation')
        next_state=copy.deepcopy(state);need(T.invalidate(invalidation,next_state,state['revision'])=='closed_pending_fence','provider_invalidation')
        row=one(db,'SELECT * FROM ts_current');cid=channel_id
        write(*insert('ts_binding',new_binding_id,1,invalidation['next_time_generation'].zfill(20),raw(next_state['binding'])))
        write(*insert('ts_commit',commit_id,'invalidate',raw(value)));write(*insert('ts_audit',commit_id,raw(value)))
        write(*insert('ts_outbox',commit_id,'time_fence',raw(invalidation)))
        write(*insert('ts_invalidation',invalidation['invalidation_id'],row['binding_id'],new_binding_id,commit_id,raw(invalidation['protection_operation_ref']),raw(invalidation)))
        write(*insert('tp_revocation',cid,commit_id,stop_id,raw(value)))
        # 固定STOP意图；有序出口稍后分配切点，不伪造STOP帧或ACK。
        write(*insert('tc_stop',stop_id,cid,commit_id,raw(value)))
        write(*insert('ts_state',next_state['revision'].zfill(20),state['revision'].zfill(20),new_binding_id,'unavailable',None,commit_id,raw(next_state)))
        write('UPDATE ts_head SET revision=? WHERE id=1',(next_state['revision'].zfill(20),))
        write(*insert('ts_seal',commit_id,raw(value)));F.source(db,next_state['revision']);return value
    return transact(db,operation,**fault)
