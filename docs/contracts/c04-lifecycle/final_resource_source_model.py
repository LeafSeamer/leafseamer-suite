"""最终封存的控制、归属及资源集合读取；只核本库关系，不替代外部资格。"""
import final_encoding_source_model as E
F=E.F;need=F.need;one=E.one;ref=E.ref

def rows(db,sql,args=()):
    cursor=db.execute(sql,args);names=[x[0] for x in cursor.description]
    return [dict(zip(names,row)) for row in cursor.fetchall()]

def control(db,binding,identity,tx):
    need(db.in_transaction,'resource_transaction_required')
    need(E.A.scope(db)==binding['scope'],'resource_scope')
    device=binding['device_id'];a=one(db,'SELECT * FROM go_authority WHERE device_id=?',(device,))
    current=one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(device,))
    change=one(db,'SELECT * FROM ct_change WHERE change_id=?',(current['change_id'],))
    ex=one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(binding['writer_exit_id'],))
    need(all(ex[k if k!='writer_exit_id' else 'exit_id']==v for k,v in binding.items() if k!='scope'),'resource_exit')
    need(change['clock_domain']==binding['clock_domain_id'] and change['descriptor']==binding['descriptor_digest'],'resource_clock')
    need(a['pending_operation_id'] is None and current['pending_operation_id'] is None,'resource_pending_control')
    need(a['control_epoch']==current['control_epoch'] and a['effective_version']==current['effective_version'],'resource_control_version')
    holder=None if a['holder_id'] is None else dict(kind='human',issuer_id=a['holder_issuer'],issuer_epoch=a['holder_epoch'],principal_id=a['holder_id'])
    need((identity['origin']=='manual' and a['mode']=='manual' and holder==identity['requester']) or
        (identity['origin']=='automation' and a['mode']=='automatic' and holder is None),'resource_control_principal')
    source=ref(a['change_id'],a['record_revision'],a['record_digest'])
    return E.original('control',tx,binding,identity,source,pending_operation_id=None,control_epoch=a['control_epoch'],
        effective_version=str(int(a['effective_version'])),mode=a['mode'],holder=holder)

def inventory(db,snapshot_id,device,now,*,current=False):
    need(db.in_transaction,'resource_transaction_required')
    s=one(db,'SELECT s.* FROM go_snapshot s JOIN go_snapshot_commit c USING(snapshot_id) WHERE snapshot_id=?',(snapshot_id,))
    need(s['device_id']==device and int(s['sampled_tick'])<=now<int(s['expires_tick']),'resource_snapshot_window')
    observations=rows(db,'SELECT * FROM go_hold WHERE snapshot_id=? ORDER BY hold_id LIMIT 65537',(snapshot_id,));holds=[]
    need(len(observations)<=65536,'resource_capacity')
    mapping={'active':'active','unknown':'unknown','failed_unresolved':'unresolved','orphaned':'stale','proof_revoked':'stale'}
    for observation in observations:
        h=one(db,'SELECT h.*,c.device_id FROM cr_hold h JOIN ce_command c USING(command_id) WHERE hold_id=?',(observation['hold_id'],))
        owner=one(db,'SELECT * FROM ow_record WHERE ownership_id=?',(observation['owner_ref'],))
        need(h['device_id']==device and owner['hold_id']==h['hold_id'] and owner['hold_digest']==h['hold_digest'],'resource_hold_owner')
        need(observation['owner_revision']==owner['revision'] and observation['owner_digest']==owner['ownership_digest']
            and observation['authority_state_id']==owner['authority_state_id'],'resource_ownership_original')
        holds.append(dict(hold_ref=ref(h['hold_id'],1,h['hold_digest']),ownership_ref=ref(owner['ownership_id'],owner['revision'],owner['ownership_digest']),classification=mapping[observation['classification']]))
    need(len(holds)<=65536,'resource_capacity')
    if current:
        need(bool(db.execute('SELECT 1 FROM go_current_snapshot WHERE snapshot_id=?',(snapshot_id,)).fetchone()),'resource_snapshot_not_current')
        risk={r[0] for r in db.execute('SELECT hold_id FROM cr_risk_hold WHERE device_id=?',(device,))}
        need({h['hold_ref']['id'] for h in holds}==risk,'resource_risk_set')
    return s,holds

def pair(db,before_id,after_id,device,hold_id,transition,selected,now):
    """关系子检查也可用于保护hold；普通/取消语义仍由完整Seal决定。"""
    need(selected<=now,'resource_sampling_order')
    before,old=inventory(db,before_id,device,now);after,new=inventory(db,after_id,device,now,current=True)
    need(int(before['sampled_tick'])<=selected and int(after['sampled_tick'])<=now,'resource_cut_order')
    need(before['authority_state_id']==after['authority_state_id'] and before['exit_id']==after['exit_id'],'resource_cut_authority')
    hazard=db.execute("SELECT coalesce(max(revision),'00000000000000000000') FROM go_hazard WHERE device_id=?",(device,)).fetchone()[0]
    need(before['safety_revision']==after['safety_revision']==hazard,'resource_safety_changed')
    old_map={x['hold_ref']['id']:x for x in old};new_map={x['hold_ref']['id']:x for x in new}
    if transition=='create':
        need(before_id!=after_id and hold_id not in old_map and set(new_map)==set(old_map)|{hold_id},'resource_create_set')
        need(all(new_map[k]==v for k,v in old_map.items()),'resource_prior_hold_changed')
    else:
        need(transition=='reuse' and old==new and hold_id in old_map,'resource_reuse_set')
    need(new_map[hold_id]['classification']=='active','resource_selected_hold_not_active')
    return before,old,after,new

def ownership(db,seal,control_original):
    hold_id=seal['hold_ref']['id'];h=one(db,'SELECT * FROM cr_hold WHERE hold_id=?',(hold_id,))
    owner=one(db,'SELECT * FROM ow_current_owner WHERE hold_id=?',(hold_id,));identity=seal['identity'];binding=seal['binding'];now=int(seal['sealed_tick_ns'])
    need(owner['device_id']==binding['device_id'] and owner['command_id']==identity['command_ref']['id'] and owner['kind']==identity['kind'],'resource_owner_subject')
    need(ref(h['hold_id'],1,h['hold_digest'])==seal['hold_ref'] and h['hold_digest']==owner['hold_digest'],'resource_owner_hold')
    need(owner['authority_state_id']==control_original['source_ref']['id'] and owner['control_epoch']==control_original['body']['control_epoch']
        and str(int(owner['effective_version']))==control_original['body']['effective_version'],'resource_owner_authority')
    need(owner['clock_domain']==binding['clock_domain_id'] and owner['descriptor']==binding['descriptor_digest'],'resource_owner_clock')
    need(dict(kind=owner['principal_kind'],**{k:owner[k] for k in ('issuer_id','issuer_epoch','principal_id')})==identity['requester'] and owner['origin']==identity['origin'],'resource_owner_requester')
    committed=one(db,'SELECT * FROM ow_commit WHERE ownership_id=?',(owner['ownership_id'],))
    need(int(owner['sampled_tick'])<=int(owner['acquired_tick'])<=int(committed['committed_tick'])<int(owner['expires_tick'])
        and int(committed['committed_tick'])<=int(seal['selected_tick_ns'])<=now,'resource_owner_window')
    if identity['kind']=='ordinary':need(owner['attempt_id']==identity['attempt_ref']['id'] and h['attempt_id']==owner['attempt_id'],'resource_owner_attempt')
    else:need(owner['cancellation_id']==identity['cancellation_ref']['id'] and owner['execution_id']==identity['execution_ref']['id'] and h['cancel_execution_id']==owner['execution_id'],'resource_owner_cancel')
    return E.original('ownership',seal['transaction_id'],binding,identity,ref(owner['ownership_id'],owner['revision'],owner['ownership_digest']),
        hold_ref=seal['hold_ref'],control_authority_ref=control_original['source_ref'],control_epoch=owner['control_epoch'],effective_version=str(int(owner['effective_version'])))

def read(db,seal,before_id,after_id,resource_safety_ref):
    F.validate('Seal',seal);need(F.seal(seal)==seal,'resource_seal_digest');F.validate('Ref',resource_safety_ref)
    c=control(db,seal['binding'],seal['identity'],seal['transaction_id']);o=ownership(db,seal,c)
    b,old,a,new=pair(db,before_id,after_id,seal['binding']['device_id'],seal['hold_ref']['id'],seal['hold_transition'],int(seal['selected_tick_ns']),int(seal['sealed_tick_ns']))
    if seal['identity']['kind']=='ordinary':
        need(bool(db.execute('SELECT 1 FROM go_valid_snapshot WHERE snapshot_id=?',(after_id,)).fetchone()),'resource_ordinary_safety')
    need(a['authority_state_id']==c['source_ref']['id'] and a['exit_id']==seal['binding']['writer_exit_id'],'resource_final_binding')
    need(next(x['ownership_ref'] for x in new if x['hold_ref']==seal['hold_ref'])==o['source_ref'],'resource_final_owner')
    result=dict(control=c,ownership=o)
    for role,s,holds in [('resource_before',b,old),('resource_after',a,new)]:
        result[role]=E.original(role,seal['transaction_id'],seal['binding'],seal['identity'],ref(s['snapshot_id'],1,s['evidence_digest']),resource_safety_ref=resource_safety_ref,holds=holds)
    return result

def verify(db,seal,originals):
    actual=read(db,seal,originals['resource_before']['source_ref']['id'],originals['resource_after']['source_ref']['id'],originals['resource_safety']['source_ref'])
    for role,v in actual.items():need(v==originals[role] and seal['inputs'][role]==v['ref'],'resource_projection_'+role)
    return 'storage_relationships_valid_requires_provider_verification'
