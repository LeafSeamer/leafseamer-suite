"""以同库完整提供者原件解析恢复时间下界；不把历史来源变成UTC资格。"""
import importlib.util,sys
import open_time_source_model as O
HERE=O.HERE;N=O.N;M=O.M;T=O.T
sys.path.append(str(HERE.parent/'df03-provider'))
spec=importlib.util.spec_from_file_location('open_provider_adoption',HERE.parent/'df03-provider/adoption_model.py')
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
def floor_source(db):
    M.need(db.in_transaction,'provider_floor_transaction')
    state=T.source(db,str(int(T.one(db,'SELECT revision FROM ts_head WHERE id=1')['revision'])))
    runtime_id=state['binding']['domain']['runtime_binding_ref']['id']
    a=T.one(db,'SELECT * FROM tp_adoption WHERE runtime_id=?',(runtime_id,));adoption=P.read(db,a['channel_id'])
    P.P.verify_domain(adoption['runtime'],state['binding']['domain'])
    initial=adoption['configuration']['binding']
    M.need(all(state['binding'][k]==v for k,v in initial.items() if k!='time_generation') and
        int(state['binding']['time_generation'])>=int(initial['time_generation']),'provider_floor_lineage')
    if state['status'] in ('collecting','qualified'):
        active,actual,snapshot=P.current(db);M.need(active==adoption and actual==state,'provider_floor_current')
        return adoption,state,snapshot,'current_adoption'
    M.need(state['status']=='unavailable','provider_floor_status')
    # 撤回后只接受与当前失效提交完整关联的原件；不传入伪造的expectedDomain。
    row=T.one(db,'SELECT * FROM tp_revocation WHERE channel_id=?',(a['channel_id'],))
    value=P.P.S.document(row['body']);P.validate('Revocation',value)
    M.need(P.T.intact(value,'revocation_digest') and value['adoption_ref']==P.cref(adoption,'adoption') and
        value['revocation_id']==row['stop_id'] and value['invalidation_commit_id']==row['invalidation_commit'],'provider_floor_revocation')
    physical=T.one(db,'SELECT * FROM ts_current');inv=T.one(db,'SELECT * FROM ts_invalidation WHERE commit_id=?',(row['invalidation_commit'],))
    invalidation=T.original(inv['body'],'Invalidation','invalidation_digest')
    M.need(physical['commit_id']==row['invalidation_commit'] and physical['binding_id']==inv['new_binding']==value['next_binding_storage_id'] and
        value['invalidation_ref']==state['invalidation_ref']==P.cref(invalidation,'invalidation') and
        value['cause_ref']==invalidation['cause_ref'] and inv['old_binding']==a['binding_id'] and invalidation['old_binding']==initial,'provider_floor_invalidation')
    stop=T.one(db,'SELECT * FROM tc_stop WHERE id=?',(row['stop_id'],))
    M.need(stop['channel_id']==a['channel_id'] and stop['invalidation_commit']==row['invalidation_commit'] and stop['body']==row['body'],'provider_floor_stop')
    delivery=T.one(db,'SELECT c.receipt_body,a.body AS audit,o.body AS outbox,z.body AS seal FROM ts_commit c '
        'JOIN ts_audit a ON a.commit_id=c.id JOIN ts_outbox o ON o.commit_id=c.id JOIN ts_seal z ON z.commit_id=c.id WHERE c.id=?',(row['invalidation_commit'],))
    M.need(delivery['receipt_body']==delivery['audit']==delivery['seal']==row['body'] and delivery['outbox']==inv['body'],'provider_floor_delivery')
    return adoption,state,T.derive(state),'withdrawn_floor_only'
def for_open(db,recovery_id,fence_id,now,retained=None):
    adoption,state,snapshot,provenance=floor_source(db)
    result=O.for_open(db,recovery_id,fence_id,now,state['binding']['domain'],retained)
    M.need(result['reference_time_snapshot']==snapshot,'provider_floor_snapshot')
    result['originals']['time_provider_adoption']=adoption
    result['originals']['time_state']=state
    result['time_source_provenance']=provenance
    return result
