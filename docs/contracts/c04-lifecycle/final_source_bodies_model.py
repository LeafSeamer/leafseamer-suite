"""核对最终来源的完整存储正文、自摘要及物理关系；不授发送权。"""
import json
from jsonschema import Draft202012Validator
import final_resource_source_model as R
import build_final_source_bodies as G
E=R.E;F=R.F;need=F.need;one=R.one;ref=R.ref;raw=E.raw
SCHEMA=G.build()
def validate(name,v):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name}).validate(v)
def sealed(v,key):return F.seal(v,key)
def counter(v):return str(int(v))

def decode(name,b,key,expected):
    need(isinstance(b,bytes) and len(b)<=16777216,'source_body_capacity')
    def pairs(items):
        result={}
        for k,v in items:need(k not in result,'source_duplicate_key');result[k]=v
        return result
    value=json.loads(b,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('source_nonfinite')))
    validate(name,value);need(raw(value)==b,'source_body_not_canonical')
    need(value==sealed(value,key) and value[key]==expected,'source_body_digest');return value

def binding(db,eid):
    e=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,))
    return dict(scope=E.A.scope(db),writer_exit_id=eid,**{k:e[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','device_session_id','clock_domain_id','descriptor_digest')})

def control_body(db,s):
    change=one(db,'SELECT * FROM ct_change WHERE change_id=?',(s['change_id'],))
    holder=None if s['holder_id'] is None else dict(kind='human',issuer_id=s['holder_issuer'],issuer_epoch=s['holder_epoch'],principal_id=s['holder_id'])
    value=dict(format_version='control-storage-body/1',change_id=s['change_id'],revision=counter(s['record_revision']),scope=E.A.scope(db),device_id=change['device_id'],change_kind=change['kind'],
        control_epoch=s['control_epoch'],effective_version=counter(s['effective_version']),reserved_version=counter(s['reserved_version']),mode=s['mode'],holder=holder,
        pending_operation_id=s['pending_operation_id'],gate_state=s['gate_state'],clock_domain_id=change['clock_domain'],descriptor_digest=change['descriptor'],observed_tick_ns=counter(change['now_tick']))
    return sealed(value,'record_digest')

def control(db,cid):
    need(db.in_transaction,'source_transaction_required');row=one(db,'SELECT * FROM ct_state WHERE change_id=?',(cid,))
    value=decode('ControlStorageRecord',row['record_body'],'record_digest',row['record_digest'])
    need(value==control_body(db,row),'source_control_columns');return value

def control_ref(value):return ref(value['change_id'],value['revision'],value['record_digest'])

def safety(db,device,revision):
    need(db.in_transaction,'source_transaction_required');validate('Counter',revision)
    row=db.execute('SELECT source_kind,source_id,recovery_id FROM go_hazard WHERE device_id=? AND revision=?',(device,E.E.u(revision))).fetchone()
    need((row is None)==(revision=='0'),'source_safety_head')
    value=dict(format_version='resource-safety-cut/1',scope=E.A.scope(db),device_id=device,revision=revision,head=dict(zip(('source_kind','source_id','recovery_id'),row)) if row else None)
    value=sealed(value,'cut_digest');validate('ResourceSafetyCut',value);return value

def safety_ref(value):return ref('resource_safety_'+F.digest(dict(scope=value['scope'],device_id=value['device_id']))[7:],value['revision'],value['cut_digest'])

def ownership_content(db,s,identity):
    a=control(db,s['authority_state_id'])
    return dict(scope=E.A.scope(db),device_id=s['device_id'],hold_ref=ref(s['hold_id'],1,s['hold_digest']),identity=identity,control_authority_ref=control_ref(a),
        control_epoch=s['control_epoch'],effective_version=counter(s['effective_version']),clock_domain_id=s['clock_domain'],descriptor_digest=s['descriptor'],acquired_tick_ns=counter(s['acquired_tick']))

def receipt_body(db,s,identity):
    value=dict(format_version='ownership-source/1',source_id=s['source_id'],revision=counter(s['source_revision']),provider_id=s['provider_ref'],sampled_tick_ns=counter(s['sampled_tick']),
        expires_tick_ns=counter(s['expires_tick']),content=ownership_content(db,s,identity))
    return sealed(value,'receipt_digest')

def ownership_body(db,o):
    s=one(db,'SELECT * FROM ow_source WHERE source_id=?',(o['source_id'],));receipt=decode('OwnershipReceipt',s['receipt_body'],'receipt_digest',s['source_digest'])
    return sealed(dict(format_version='hold-ownership/0.1.0-draft.1',ownership_id=o['ownership_id'],revision=counter(o['revision']),**receipt['content'],
        source_receipt_ref=ref(s['source_id'],s['source_revision'],s['source_digest'])),'ownership_digest')

def ownership(db,oid):
    need(db.in_transaction,'source_transaction_required');o=one(db,'SELECT * FROM ow_ownership WHERE ownership_id=?',(oid,));s=one(db,'SELECT * FROM ow_source WHERE source_id=?',(o['source_id'],))
    value=decode('Ownership',o['ownership_body'],'ownership_digest',o['ownership_digest']);receipt=decode('OwnershipReceipt',s['receipt_body'],'receipt_digest',s['source_digest'])
    need(value==ownership_body(db,o) and receipt==receipt_body(db,s,value['identity']),'source_ownership_receipt')
    identity=value['identity'];principal=identity['requester']
    need(identity['kind']==s['kind'] and identity['origin']==s['origin'] and identity['command_ref']['id']==s['command_id'],'source_ownership_identity')
    need(principal==dict(kind=s['principal_kind'],**{k:s[k] for k in ('issuer_id','issuer_epoch','principal_id')}),'source_ownership_principal')
    if s['kind']=='ordinary':need(identity['attempt_ref']['id']==s['attempt_id'],'source_ownership_attempt')
    else:need(identity['cancellation_ref']['id']==s['cancellation_id'] and identity['execution_ref']['id']==s['execution_id'],'source_ownership_execution')
    h=one(db,'SELECT * FROM cr_hold WHERE hold_id=?',(o['hold_id'],))
    need(value['hold_ref']==ref(h['hold_id'],1,h['hold_digest']) and s['hold_id']==h['hold_id'],'source_ownership_hold')
    return value

def snapshot_body(db,s,observations):
    holds=[]
    for obs in sorted(observations,key=lambda x:x['hold_id']):
        o=ownership(db,obs['owner_ref'])
        need(obs['hold_id']==o['hold_ref']['id'],'source_snapshot_hold')
        need(ref(o['ownership_id'],o['revision'],o['ownership_digest'])==ref(obs['owner_ref'],obs['owner_revision'],obs['owner_digest']),'source_snapshot_owner')
        need(o['control_authority_ref']['id']==obs['authority_state_id'],'source_snapshot_authority')
        holds.append(dict(hold_ref=o['hold_ref'],owner_ref=ref(o['ownership_id'],o['revision'],o['ownership_digest']),control_authority_ref=o['control_authority_ref'],state=obs['classification']))
    need(len(holds)<=65536 and len({x['hold_ref']['id'] for x in holds})==len(holds),'source_snapshot_members')
    value=dict(format_version='resource-snapshot-body/1',snapshot_id=s['snapshot_id'],revision='1',binding=binding(db,s['exit_id']),control_authority_ref=control_ref(control(db,s['authority_state_id'])),
        control_state_ref=control_ref(control(db,s['control_state_id'])),resource_safety_ref=safety_ref(safety(db,s['device_id'],counter(s['safety_revision']))),
        authorization_id=s['authorization_ref'],resource_id=s['resource_ref'],run_snapshot_id=s['run_snapshot_ref'],command_snapshot_id=s['command_snapshot_ref'],time_snapshot_id=s['time_snapshot_ref'],
        sampled_tick_ns=counter(s['sampled_tick']),expires_tick_ns=counter(s['expires_tick']),provider_id=s['provider_ref'],holds=holds)
    need(value['binding']['device_id']==s['device_id'],'source_snapshot_device')
    return sealed(value,'evidence_digest')

def snapshot(db,sid):
    need(db.in_transaction,'source_transaction_required');s=one(db,'SELECT s.* FROM go_snapshot s JOIN go_snapshot_commit c USING(snapshot_id) WHERE snapshot_id=?',(sid,))
    observations=R.rows(db,'SELECT * FROM go_hold WHERE snapshot_id=? ORDER BY hold_id LIMIT 65537',(sid,));need(len(observations)<=65536,'source_snapshot_capacity')
    value=decode('ResourceSnapshotRecord',s['evidence_body'],'evidence_digest',s['evidence_digest'])
    need(value==snapshot_body(db,s,observations),'source_snapshot_columns');return value

def read(db,seal,before_id,after_id):
    c=one(db,'SELECT * FROM go_authority WHERE device_id=?',(seal['binding']['device_id'],));control(db,c['change_id'])
    current=one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(seal['binding']['device_id'],));control(db,current['change_id'])
    o=one(db,'SELECT * FROM ow_record WHERE hold_id=?',(seal['hold_ref']['id'],));owner=ownership(db,o['ownership_id'])
    need(owner['identity']==seal['identity'],'source_full_identity')
    before=snapshot(db,before_id);after=snapshot(db,after_id)
    head=db.execute("SELECT coalesce(max(revision),'00000000000000000000') FROM go_hazard WHERE device_id=?",(seal['binding']['device_id'],)).fetchone()[0]
    cut=safety(db,seal['binding']['device_id'],counter(head));reference=safety_ref(cut)
    need(before['resource_safety_ref']==after['resource_safety_ref']==reference,'source_snapshot_safety')
    originals=R.read(db,seal,before_id,after_id,reference)
    originals['resource_safety']=E.original('resource_safety',seal['transaction_id'],seal['binding'],seal['identity'],reference)
    return originals

def verify(db,seal,originals):
    actual=read(db,seal,originals['resource_before']['source_ref']['id'],originals['resource_after']['source_ref']['id'])
    for role,v in actual.items():need(v==originals[role] and seal['inputs'][role]==v['ref'],'source_projection_'+role)
    return 'stored_bodies_and_relationships_valid_requires_current_providers'
