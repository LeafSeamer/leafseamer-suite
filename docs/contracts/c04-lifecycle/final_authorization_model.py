"""同writer内检查持久授权绑定及撤销下界；不证明签发者、UTC或scope取证真实性。"""
import json
from jsonschema import Draft202012Validator,FormatChecker
import build_final_authorization as G
import final_encoding_source_model as E
import continuation_binding_model as CB
F=E.F;need=F.need;raw=E.raw;SCHEMA=G.build()
import authorization_validity_model as V

def validate(name,value):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name},format_checker=FormatChecker()).validate(value)
def sealed(v,key):return F.seal(v,key)
def document(body):
    need(isinstance(body,bytes) and 0<len(body)<=16777216,'authorization_body_capacity')
    def pairs(items):
        out={}
        for k,v in items:need(k not in out,'authorization_duplicate_key');out[k]=v
        return out
    v=json.loads(body,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('authorization_nonfinite')))
    need(raw(v)==body,'authorization_body_digest');return v

def decode(name,body,digest,key):
    v=document(body);validate(name,v);need(sealed(v,key)==v and v[key]==digest,'authorization_body_digest');return v

def writer(db):
    need(db.in_transaction,'authorization_transaction_required')
    # 先取同库writer锁；已读过的陈旧DEFERRED快照升级失败须整事务回滚，不能继续。
    db.execute('UPDATE authorization_use SET use_id=use_id WHERE 0')

def reference(v,id_key,digest_key):return E.ref(v[id_key],v['revision'],v[digest_key])

def scope_reference(value):
    digest=E.digest(value);return E.ref('command_scope_'+digest[7:],1,digest)

def validate_scope(value):
    validate('CommandScope',value)
    need(value['permissions']==sorted(value['permissions']),'authorization_scope_permission_order')
    need(value['targets']==sorted(value['targets'],key=lambda x:(x['device_id'],x['action_id'],x['capability_version'])),'authorization_scope_target_order')

def store_scope(db,value):
    writer(db);validate_scope(value);need(value['scope']==E.A.scope(db),'authorization_scope_authority')
    ref_value=scope_reference(value)
    old=db.execute('SELECT body FROM authorization_command_scope WHERE digest=?',(ref_value['digest'],)).fetchone()
    if old:need(old[0]==raw(value),'authorization_scope_identity');return ref_value
    db.execute('INSERT INTO authorization_command_scope VALUES(?,?,?)',(ref_value['id'],ref_value['digest'],raw(value)));return ref_value

def command_scope(db,ref_value):
    validate('Ref',ref_value)
    row=db.execute('SELECT scope_id,digest,body FROM authorization_command_scope WHERE scope_id=?',(ref_value['id'],)).fetchone();need(row is not None,'authorization_scope_missing')
    value=document(row[2]);validate_scope(value)
    need(scope_reference(value)==ref_value and row[0]==ref_value['id'] and row[1]==ref_value['digest'],'authorization_scope_digest');return value

def store_context(db,value):
    writer(db);validate('RequestContextBinding',value);need(sealed(value,'context_digest')==value,'authorization_context_digest')
    need(value['scope']==E.A.scope(db),'authorization_context_scope')
    n=E.one(db,'SELECT * FROM ca_namespace WHERE namespace_id=?',(value['namespace_id'],))
    need(all(value['requester'][key]==n[key] for key in ('issuer_id','issuer_epoch','principal_id')) and value['request_epoch']==n['request_epoch'],'authorization_context_owner')
    original=command_scope(db,value['original_scope_ref'])
    need(original['scope']==value['scope'] and original['requester']==value['requester'] and original['credential_id']==value['credential_id'],'authorization_context_original_scope')
    old=db.execute('SELECT body FROM authorization_context WHERE context_id=?',(value['context_id'],)).fetchone()
    if old:need(old[0]==raw(value),'authorization_context_identity');return
    need(not db.execute('SELECT 1 FROM ca_request_key WHERE namespace_id=? AND json_extract(transport_body,\'$.context_id\')=?',(value['namespace_id'],value['context_id'])).fetchone(),'authorization_context_late_registration')
    db.execute('INSERT INTO authorization_context VALUES(?,?,?,?)',(value['context_id'],value['namespace_id'],value['context_digest'],raw(value)))

def scope_details(db,u):
    """查原并形成具名描述；是否允许目标由scope_proof另行判断。"""
    identity=u['identity'];cid=identity['command_ref']['id']
    request=E.one(db,'SELECT k.* FROM ca_request_key k JOIN ca_command_initial i USING(key_id) WHERE i.command_id=?',(cid,))
    transport=document(request['transport_body']);content=document(request['content_body'])
    row=db.execute('SELECT namespace_id,digest,body FROM authorization_context WHERE context_id=?',(transport['context_id'],)).fetchone();need(row is not None,'authorization_context_missing')
    context=decode('RequestContextBinding',row[2],row[1],'context_digest')
    need(context['context_id']==transport['context_id'] and context['namespace_id']==row[0]==request['namespace_id'],'authorization_context_columns')
    current_row=db.execute('SELECT scope_id,digest FROM authorization_command_scope WHERE digest=?',(u['snapshot']['scope_digest'],)).fetchone();need(current_row is not None,'authorization_current_scope_missing')
    current_ref=E.ref(current_row[0],1,current_row[1]);original=command_scope(db,context['original_scope_ref']);current=command_scope(db,current_ref)
    proof=dict(format_version='command-scope-proof/1',scope=E.A.scope(db),command_ref=identity['command_ref'],request_ref=identity['source_ref'],
        context_ref=reference(context,'context_id','context_digest'),original_scope_ref=context['original_scope_ref'],current_scope_ref=current_ref,
        authority_response_ref=u['authority_evidence_ref'],target={key:content[key] for key in ('device_id','action_id','capability_version')})
    validate('CommandScopeProof',proof)
    return context,original,current,proof,document(request['request_key_body'])

def scope_proof_reference(proof):return E.ref('scope_proof_'+E.digest(proof)[7:],1,E.digest(proof))

def scope_proof(db,u):
    context,original,current,proof,key=scope_details(db,u);a=u['authorization_binding'];s=u['snapshot']
    need(context['scope']==u['binding']['scope']==key['target_scope'] and context['request_epoch']==key['request_epoch'],'authorization_context_request')
    need(context['requester']==u['identity']['requester'] and all(context['requester'][k]==key[k] for k in ('issuer_id','issuer_epoch','principal_id')),'authorization_context_requester')
    need(context['credential_id']==a['credential_id'] and context['session_id']==a['session_id'],'authorization_context_credential_chain')
    need(key['operation_id'] in context['operations'],'authorization_context_operation')
    for scope in (original,current):
        need(scope['scope']==u['binding']['scope'] and scope['requester']==u['identity']['requester'] and scope['credential_id']==a['credential_id'],'authorization_target_scope_binding')
        need('device.command' in scope['permissions'] and proof['target'] in scope['targets'],'authorization_target_not_allowed')
    need(current['permissions']==sorted(s['permissions']),'authorization_scope_permissions')
    ref_value=scope_proof_reference(proof);need(u['scope_evidence_ref']==ref_value,'authorization_scope_proof_ref');return ref_value

def store_challenge(db,value):
    writer(db);validate('AuthorizationChallenge',value);need(sealed(value,'challenge_digest')==value,'authorization_challenge_digest')
    need(value['binding']['scope']==E.A.scope(db),'authorization_challenge_scope')
    old=db.execute('SELECT body FROM authorization_challenge WHERE challenge_id=?',(value['challenge_id'],)).fetchone()
    if old:need(old[0]==raw(value),'authorization_challenge_identity');return
    db.execute('INSERT INTO authorization_challenge VALUES(?,?,?)',(value['challenge_id'],value['challenge_digest'],raw(value)))

def challenge(db,reference_value):
    validate('Ref',reference_value)
    row=db.execute('SELECT digest,body FROM authorization_challenge WHERE challenge_id=?',(reference_value['id'],)).fetchone();need(row is not None,'authorization_challenge_missing')
    value=decode('AuthorizationChallenge',row[1],row[0],'challenge_digest')
    need(reference(value,'challenge_id','challenge_digest')==reference_value,'authorization_challenge_ref');return value

def response_binding(db,value):
    c=challenge(db,value['challenge_ref']);s=value['snapshot'];who=c['requester']
    need(value['scope']==c['binding']['scope']==E.A.scope(db),'authorization_response_scope')
    need(s['challenge_id']==c['challenge_id'],'authorization_response_challenge')
    need(who==dict(kind=s['principal_kind'],**{k:s[k] for k in ('issuer_id','issuer_epoch','principal_id')}),'authorization_response_requester')
    for k in ('credential_id','audience','scope_digest'):need(c[k]==s[k],'authorization_response_'+k)
    need(int(c['sent_tick_ns'])<=int(value['received_tick_ns']),'authorization_response_order');return c

def store_response(db,value):
    """仅供未来受信认证传输接收端调用；本候选不验证channel_evidence_ref的TLS来源。"""
    writer(db);validate('AuthorityResponse',value);need(sealed(value,'response_digest')==value,'authorization_response_digest')
    response_binding(db,value)
    rows=db.execute('SELECT body FROM authorization_response WHERE response_id=? OR challenge_id=?',(value['response_id'],value['challenge_ref']['id'])).fetchall()
    if rows:need(len(rows)==1 and rows[0][0]==raw(value),'authorization_response_identity');return
    db.execute('INSERT INTO authorization_response VALUES(?,?,?,?)',(value['response_id'],value['challenge_ref']['id'],value['response_digest'],raw(value)))

def authority_response(db,u):
    ref_value=u['authority_evidence_ref']
    row=db.execute('SELECT response_id,challenge_id,digest,body FROM authorization_response WHERE response_id=?',(ref_value['id'],)).fetchone()
    need(row is not None,'authorization_response_missing');value=decode('AuthorityResponse',row[3],row[2],'response_digest')
    need(reference(value,'response_id','response_digest')==ref_value and value['response_id']==row[0] and value['challenge_ref']['id']==row[1],'authorization_response_ref')
    c=response_binding(db,value)
    need(value['snapshot']==u['snapshot'],'authorization_response_snapshot')
    need(c['binding']==u['binding'] and c['requester']==u['identity']['requester'],'authorization_challenge_binding')
    need(c['sent_tick_ns']==u['challenge_sent_tick_ns'] and value['received_tick_ns']==u['received_tick_ns'],'authorization_capture_ticks')
    return ref_value

def continuation(db,u):
    """从已受理命令与当前转交原件取scope/grant，不以AuthorizationBinding自报值作为原件。"""
    identity=u['identity'];b=u['binding'];a=u['authorization_binding'];command_id=identity['command_ref']['id']
    s=E.E.source(db,command_id,identity['attempt_ref']['id'],b['writer_exit_id']);k=s['key'];initial=s['initial']
    content=document(k['content_body']);CB.validate('CommandContent',content)
    need(E.digest(content)==k['request_digest'],'authorization_command_digest')
    need(identity['command_ref']==E.ref(command_id,initial['revision'],initial['command_digest']),'authorization_command_ref')
    need(content['origin']=='automation' and content['device_id']==b['device_id'],'authorization_command_device')
    ab=content['automation_binding'];rb=content['run_binding'];selected=ab['continuation']
    need(ab['authorization_mode']=='continuation' and selected is not None,'authorization_continuation_required')
    n=E.one(db,'SELECT * FROM cn_live_command WHERE command_id=?',(command_id,))
    issue=E.one(db,'SELECT * FROM cr_current WHERE transfer_id=?',(n['transfer_id'],))
    q=document(issue['request_body']);target=document(issue['target_body']);receipt=document(issue['receipt_body']);grant=document(issue['grant_body'])
    CB.M.request_shape(q);CB.M.validate('Receipt',receipt)
    need(q['transfer_id']==issue['transfer_id']==n['transfer_id'] and q['request_digest']==issue['request_digest'],'authorization_transfer_columns')
    need(receipt==CB.M.seal(receipt,'receipt_digest') and receipt['receipt_digest']==issue['receipt_digest'],'authorization_receipt_digest')
    expected_targets=[t for t in q['targets'] if t['controller_scope']==b['scope']]
    need(len(expected_targets)==1 and expected_targets[0]==target,'authorization_grant_target')
    grant_content=dict(scope='run_generation',request_digest=q['request_digest'],target_digest=E.digest(target),plan_ref=q['continuation_plan_ref'],parent_preparation_ref=target['preparation_ref'],activation='adoption_and_r5')
    grant_ref=dict(scope=b['scope'],id=issue['grant_id'],revision='1',digest=E.digest(grant_content))
    need(grant==dict(grant_content,ref=grant_ref) and grant_ref==receipt['continuation_grant_ref']==selected['grant_ref'],'authorization_grant_original')
    stored=E.one(db,'SELECT * FROM typed_command_source WHERE command_id=?',(command_id,))
    execution=document(stored['execution_body']);adoption=document(stored['adoption_body']);evidence=document(stored['evidence_body'])
    need(adoption==CB.M.seal(adoption,'adoption_digest') and n['adoption_digest']==adoption['adoption_digest'],'authorization_adoption_original')
    CB.validate_execution(execution,q,adoption,evidence['receipts'])
    need(selected==CB.selection(q,adoption,receipt,target) and ab['execution_binding_ref']==CB.eref(execution),'authorization_execution_original')
    need(all(ab[key]==execution[key] for key in ('run_id','arm_generation','execution_id')) and ab['origin_scope']==execution['scope'],'authorization_execution_scope')
    need(n['execution_id']==ab['execution_id'] and n['step_id']==ab['step_id'],'authorization_command_execution')
    need(ab==document(n['binding_body'])==document(initial['admission_binding_body'])==document(s['command']['binding_body']),'authorization_admission_original')
    need(document(n['grant_ref_body'])==grant_ref and n['request_digest']==k['request_digest'],'authorization_command_grant')
    need(rb==dict(run_id=q['run_id'],definition_version=ab['definition_version'],grant_id=grant_ref['id'],grant_revision=grant_ref['revision'],arm_generation=q['generation'],step_id=ab['step_id'],logical_action_id=ab['logical_action_id']),'authorization_run_binding')
    need(all(a[key]==rb[key] for key in ('grant_id','grant_revision','arm_generation')),'authorization_current_grant')
    devices=db.execute('SELECT device_id,device_body FROM cr_device WHERE transfer_id=? ORDER BY device_id',(issue['transfer_id'],)).fetchall()
    expected=sorted(target['devices'],key=lambda x:x['device_id'])
    need([(r[0],document(r[1])) for r in devices]==[(d['device_id'],d) for d in expected] and b['device_id'] in [d['device_id'] for d in expected],'authorization_device_membership')
    value=dict(format_version='continuation-authorization/1',scope=b['scope'],command_ref=identity['command_ref'],request_ref=identity['source_ref'],
        **{key:content[key] for key in ('device_id','action_id','capability_version')},transfer_ref=selected['transfer_ref'],grant_ref=grant_ref,arm_generation=q['generation'],target_digest=E.digest(target))
    validate('ContinuationAuthorization',value)
    return E.ref('continuation_auth_'+E.digest(value)[7:],1,E.digest(value))

def store_use(db,value):
    writer(db);validate('AuthorizationUse',value);need(sealed(value,'use_digest')==value,'authorization_use_digest')
    need(value['binding']['scope']==E.A.scope(db),'authorization_scope')
    db.execute('INSERT INTO authorization_use VALUES(?,?,?)',(value['use_id'],value['use_digest'],raw(value)))

def install_floor(db,value):
    writer(db);validate('FloorEvent',value);need(sealed(value,'event_digest')==value,'authorization_floor_digest')
    need(value['scope']==E.A.scope(db),'authorization_floor_scope');s=value['selector']
    old=db.execute('SELECT body FROM authorization_floor_event WHERE event_id=?',(value['event_id'],)).fetchone()
    if old:need(old[0]==raw(value),'authorization_floor_identity');return
    # 乱序事件可保留；判定取所有已见事件，不以最后到达覆盖较高下界或永久撤销。
    db.execute('INSERT INTO authorization_floor_event VALUES(?,?,?,?,?,?,?,?)',
        (value['event_id'],s['kind'],s['issuer_id'],s['issuer_epoch'],s['target_id'],s['revision_floor'].zfill(20),value['event_digest'],raw(value)))

def dependencies(a):
    out=[('principal',a['principal_id'],a['subject_revision']),('credential',a['credential_id'],None),('trust',None,None)]
    if a['session_id'] is not None:out.append(('session',a['session_id'],a['session_revision']))
    if a['grant_id'] is not None:out.append(('grant',a['grant_id'],a['grant_revision']))
    if a['extension_instance_id'] is not None:out.append(('extension',a['extension_instance_id'],a['extension_approval_revision']))
    return out

def read(db,use_ref,seal):
    writer(db);validate('Ref',use_ref);E.A.candidate(db,seal)
    row=db.execute('SELECT digest,body FROM authorization_use WHERE use_id=?',(use_ref['id'],)).fetchone();need(row is not None,'authorization_use_missing')
    u=decode('AuthorizationUse',row[1],row[0],'use_digest')
    need(use_ref==E.ref(u['use_id'],u['revision'],u['use_digest']),'authorization_use_ref')
    need(u['binding']==seal['binding'] and u['binding']['scope']==E.A.scope(db) and u['identity']==seal['identity'],'authorization_use_binding')
    # 暂不开放取消及面板委托：它们的发起人/代行者和授权链另有具名契约，不借此入口降级。
    need(u['identity']['kind']=='ordinary','authorization_ordinary_only')
    a=u['authorization_binding'];s=u['snapshot'];who=u['identity']['requester']
    need(a['extension_instance_id'] is None,'authorization_delegation_not_integrated')
    need(who==dict(kind=a['principal_kind'],**{k:a[k] for k in ('issuer_id','issuer_epoch','principal_id')}),'authorization_requester')
    need(a['origin']==u['identity']['origin'] and (a['principal_kind'],a['origin']) in (('human','manual'),('service','automation')),'authorization_purpose')
    need(a['audience']==seal['binding']['scope']['authority_service_id'],'authorization_audience')
    for k in set(a)&set(s):need(a[k]==s[k],'authorization_snapshot_'+k)
    need(s['state']=='active' and 'device.command' in s['permissions'],'authorization_permission')
    sent=int(u['challenge_sent_tick_ns']);received=int(u['received_tick_ns']);selected=int(seal['selected_tick_ns']);now=int(seal['sealed_tick_ns'])
    lower=int(u['not_before_tick_ns']);upper=min(int(u['authorization_before_tick_ns']),sent+min(s['fresh_for_ms'],u['local_freshness_limit_ms'])*1000000)
    need(sent<=received<=selected<=now and lower<=received and lower<=now<upper and received<upper,'authorization_window')
    response_ref=authority_response(db,u)
    continuation_ref=continuation(db,u) if u['identity']['origin']=='automation' else None
    scope_ref=scope_proof(db,u) if u['identity']['origin']=='automation' else None
    validity_cut=V.resolve(db,u,seal)
    lower=int(validity_cut['not_before_tick_ns']);upper=int(validity_cut['before_tick_ns'])
    floors=[]
    for kind,target,revision in dependencies(a):
        query='SELECT event_id,kind,issuer_id,issuer_epoch,target_id,revision_floor,digest,body FROM authorization_floor_event WHERE kind=? AND issuer_id=? AND issuer_epoch=?'
        args=[kind,a['issuer_id'],a['issuer_epoch']]
        if target is not None:query+=' AND target_id=?';args.append(target)
        rows=db.execute(query+' ORDER BY event_id LIMIT 4097',args).fetchall();need(len(rows)<=4096,'authorization_floor_capacity')
        for r in rows:
            event=decode('FloorEvent',r[7],r[6],'event_digest');x=event['selector']
            need(event['scope']==E.A.scope(db) and tuple(r[:6])==(event['event_id'],x['kind'],x['issuer_id'],x['issuer_epoch'],x['target_id'],x['revision_floor'].zfill(20)),'authorization_floor_columns')
            need(kind not in ('credential','trust'),'authorization_permanent_denial')
            need(int(revision)>=int(x['revision_floor']),'authorization_revision_floor')
            floors.append(E.ref(event['event_id'],1,event['event_digest']))
    source=dict(format_version='authorization-cut/1',scope=E.A.scope(db),use_ref=use_ref,transaction_id=seal['transaction_id'],
        selected_tick_ns=seal['selected_tick_ns'],sealed_tick_ns=seal['sealed_tick_ns'],authority_response_ref=response_ref,
        validity_cut=validity_cut,continuation_ref=continuation_ref,scope_proof_ref=scope_ref,floor_refs=sorted(floors,key=lambda x:x['id']))
    validate('AuthorizationCut',source)
    source_ref=E.ref('authorization_cut_'+F.digest(source)[7:],1,F.digest(source))
    return E.original('authorization',seal['transaction_id'],seal['binding'],seal['identity'],source_ref,not_before_tick_ns=str(lower),before_tick_ns=str(upper))

def planned(db,seal,originals,cut,pid,provider,use_ref):
    current=read(db,use_ref,seal)
    need(originals['authorization']==current and seal['inputs']['authorization']==current['ref'],'authorization_current_projection')
    return E.planned(db,seal,originals,cut,pid,provider)
