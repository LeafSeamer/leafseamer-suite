"""从实际候选SQL原件投影协议；认证来自合成可信上下文，不是HTTP服务。"""
import json,sqlite3
from jsonschema import Draft202012Validator
import build_continuation_protocol as G
import continuation_trigger_model as T
C=T.C;M=C.M;P=C.P;R=C.R;need=M.require
SCHEMA=G.build()['continuation-protocol.schema.json']
def validate(name,value):
    Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']}).validate(value)
    cap=270336 if name=='IssueInput' else 1048576 if name.endswith(('Record','Lookup')) else 20480
    need(len(C.raw(value))<=cap,'body_capacity')
    for key,kind in [('request','Request'),('receipt','Receipt'),('adoption','Adoption')]:
        if value.get(key) is not None:M.validate(kind,value[key])

def identity(q,target):return dict(target_scope=target,origin_scope=q['origin_scope'],transfer_id=q['transfer_id'],request_digest=q['request_digest'])
def request_ref(q):return dict(scope=q['origin_scope'],id=q['transfer_id'],revision='1',digest=q['request_digest'])
def adoption_ref(a):return dict(scope=a['origin_scope'],id=a['adoption_id'],revision=a['revision'],digest=a['adoption_digest'])

def authorize(operation,target,origin,ctx,controller=None):
    route=next(r for r in G.ROUTES if r[2]==operation)
    need(ctx['mtls_verified'] and ctx['pairing_current'],'unauthenticated')
    need(ctx['server_scope']==target and origin in ctx['allowed_origins'],'target_or_origin_scope')
    need(route[5] in ctx['permissions'] and ctx['read_authorized'],'forbidden')
    if route[6]=='origin':need(ctx['peer_scope']==origin,'peer_origin')
    else:need(controller is not None and ctx['peer_scope']==controller,'peer_controller')
    need(ctx['response_authorized'],'response_authority')

def namespace(q,ctx):
    # 旧Request无issuer_epoch；通过受信历史namespace和审批者记录精确回绑，不能猜默认epoch。
    n=ctx['namespace_binding'];actor=ctx['approval_actor']
    need(n['request_epoch']==q['request_epoch'] and {k:n[k] for k in ('issuer_id','principal_id')}==q['actor'],'namespace_binding')
    need(all(n[k]==actor[k] for k in ('issuer_id','issuer_epoch','principal_id')),'actor_epoch')
    need(ctx['namespace_current'] and ctx['approval_current'],'namespace_or_approval_expired')

def validate_issue(body,ctx,role):
    validate('IssueInput',body);q=body['request'];M.request_shape(q)
    authorize('issueContinuation' if role=='controller' else 'registerContinuation',body['target_scope'],q['origin_scope'],ctx)
    if role=='controller':need(body['target_scope'] in [x['controller_scope'] for x in q['targets']],'unexpected_target')
    else:need(body['target_scope']==q['origin_scope'],'origin_target')
    namespace(q,ctx);return q

def validate_seamer_input(sd,operation,value,auth,cd=None):
    """写入前的格式/归属/原件关联；当前执行门槛仍由既有事务writer重核。"""
    kind={'observeContinuationReceipt':'ReceiptInput','adoptContinuation':'AdoptionInput','finishContinuation':'FinishInput'}[operation]
    validate(kind,value)
    inner=value['receipt'] if kind=='ReceiptInput' else value['adoption'] if kind=='AdoptionInput' else value['identity']
    target=value['identity']['target_scope'] if kind=='FinishInput' else value['target_scope']
    authorize(operation,target,inner['origin_scope'],auth,inner.get('controller_scope'))
    scope=R.one(sd,'storage_scope','singleton',1)
    need(target==inner['origin_scope']==dict(authority_service_id=scope['authority_id'],database_instance_id=scope['database_id']),'origin_target')
    q=json.loads(R.one(sd,'rc_request','transfer_id',inner['transfer_id'])['request_body']);R.one(sd,'rc_request_commit','transfer_id',q['transfer_id'])
    if kind=='ReceiptInput':
        M.common(inner,q);need(cd is not None,'receipt_provider')
        current=R.one(cd,'controller_scope','singleton',1)
        need(inner['controller_scope']=={k:current[k] for k in ('authority_service_id','database_instance_id')},'receipt_provider_scope')
        issue=R.one(cd,'cr_issue','transfer_id',q['transfer_id']);R.one(cd,'cr_commit','transfer_id',q['transfer_id'])
        need(issue['request_body']==C.raw(q) and issue['receipt_body']==C.raw(inner),'receipt_original')
    elif kind=='AdoptionInput':
        M.common(inner,q)
        receipts=[json.loads(r['receipt_body']) for r in P.rows(sd,'SELECT * FROM rc_receipt WHERE transfer_id=?',(q['transfer_id'],))]
        receipts.sort(key=lambda r:M.scope_key(r['controller_scope']))
        need(inner['receipt_refs']==[M.receipt_ref(r) for r in receipts] and len(receipts)==len(q['targets']),'receipt_set')
    else:
        need(inner==identity(q,target),'identity_conflict')
        a=json.loads(R.one(sd,'rc_adoption','transfer_id',q['transfer_id'])['adoption_body']);R.one(sd,'rc_adoption_commit','transfer_id',q['transfer_id'])
        need(value['adoption_ref']==adoption_ref(a),'adoption_original')
    return q

def receipt_ack(q,r):
    value=dict(protocol_version=G.VERSION,identity=identity(q,q['origin_scope']),controller_scope=r['controller_scope'],receipt_ref=M.receipt_ref(r),
        receipt_state='recorded',activation='not_asserted')
    validate('ReceiptAck',value);return value

def validate_record(role,record):
    validate(role+'Record',record);q=record['request'];M.request_shape(q)
    receipts=[record['receipt']] if role=='Controller' else record['receipts']
    keys=[M.scope_key(r['controller_scope']) for r in receipts];need(keys==sorted(set(keys)),'receipt_order')
    for r in receipts:
        M.validate('Receipt',r);M.common(r,q)
        targets=[t for t in q['targets'] if t['controller_scope']==r['controller_scope']];need(len(targets)==1,'target')
        t=targets[0];need(r['target_digest']==M.digest(t) and r['preparation_ref']==t['preparation_ref'] and r['recovery_grant_ref']==t['recovery_grant_ref'],'target_binding')
        need(r['continuation_grant_ref']['scope']==r['controller_scope'] and r['qualification_ref']['scope']==r['controller_scope'],'receipt_issuer')
        need(M.ref_key(r['continuation_grant_ref'])!=M.ref_key(r['recovery_grant_ref']),'distinct_grant')
    if role=='Seamer' and record['adoption'] is not None:
        a=record['adoption'];M.validate('Adoption',a);M.common(a,q)
        need(keys==[M.scope_key(t['controller_scope']) for t in q['targets']] and a['receipt_refs']==[M.receipt_ref(r) for r in receipts],'adopted_receipt_set')
        if record['finish'] is not None:
            f=record['finish'];need(f['execution_id']==q['recovery_execution_id'] and f['adoption_digest']==a['adoption_digest'],'finish_binding')
            need(f['commit_body_digest']==M.digest(dict(transfer_id=q['transfer_id'],adoption_digest=a['adoption_digest'])),'finish_digest')

def lookup(db,role,body,ctx):
    validate('LookupInput',body);key=body['identity']
    authorize('lookup'+role+'Continuation',key['target_scope'],key['origin_scope'],ctx)
    if not ctx['storage_readable']:return dict(state='indeterminate',record=None)
    need(not db.in_transaction,'snapshot_transaction_owner');db.execute('BEGIN')
    try:
        if role=='Controller':
            actual=R.one(db,'controller_scope','singleton',1);prefix='cr_issue'
        else:actual=R.one(db,'storage_scope','singleton',1);prefix='rc_request'
        actual_scope=({k:actual[k] for k in ('authority_service_id','database_instance_id')} if role=='Controller'
            else dict(authority_service_id=actual['authority_id'],database_instance_id=actual['database_id']))
        need(actual_scope==key['target_scope'],'database_scope')
        rows=P.rows(db,'SELECT * FROM '+prefix+' WHERE transfer_id=?',(key['transfer_id'],))
        if not rows:return dict(state='not_found',record=None)
        row=rows[0];q=json.loads(row['request_body'])
        need(identity(q,key['target_scope'])==key,'identity_conflict')
        if role=='Controller':
            R.one(db,'cr_commit','transfer_id',q['transfer_id'])
            record=dict(protocol_version=G.VERSION,request=q,receipt=json.loads(row['receipt_body']),qualification='not_asserted')
        else:
            R.one(db,'rc_request_commit','transfer_id',q['transfer_id'])
            receipts=[json.loads(r['receipt_body']) for r in P.rows(db,'SELECT * FROM rc_receipt WHERE transfer_id=?',(q['transfer_id'],))]
            receipts.sort(key=lambda r:M.scope_key(r['controller_scope']))
            ads=P.rows(db,'SELECT * FROM rc_adoption WHERE transfer_id=?',(q['transfer_id'],));a=json.loads(ads[0]['adoption_body']) if ads else None
            if a:R.one(db,'rc_adoption_commit','transfer_id',q['transfer_id'])
            rows=P.rows(db,'SELECT * FROM rc_r5_link WHERE transfer_id=?',(q['transfer_id'],));finish=None
            if rows:
                link=rows[0];R.one(db,'flow_commit_seal','commit_id',link['commit_id']);commit=R.one(db,'transition_commit','commit_id',link['commit_id'])
                need(commit['commit_digest']==M.digest(json.loads(commit['commit_body'])),'commit_original')
                finish=dict(commit_id=commit['commit_id'],execution_id=commit['execution_id'],adoption_digest=link['adoption_digest'],commit_body_digest=commit['commit_digest'])
            record=dict(protocol_version=G.VERSION,request=q,receipts=receipts,adoption=a,finish=finish,qualification='not_asserted')
        validate_record(role,record);need(ctx['response_authorized'],'response_authority')
        return dict(state='found',record=record)
    except sqlite3.DatabaseError:return dict(state='indeterminate',record=None)
    finally:
        db.rollback();need(ctx['response_authorized'],'response_authority')

def notice(sd,cd,transfer):
    q=json.loads(R.one(sd,'rc_request','transfer_id',transfer)['request_body']);issue=R.one(cd,'cr_issue','transfer_id',transfer)
    need(issue['request_body']==C.raw(q),'request_original');r=json.loads(issue['receipt_body'])
    proof=R.one(cd,'cr_revocation','transfer_id',transfer)
    proof_body=C.raw({k:(v.hex() if isinstance(v,bytes) else v) for k,v in proof.items()})
    return M.seal(dict(protocol_version=G.VERSION,identity=identity(q,q['origin_scope']),controller_scope=r['controller_scope'],
        receipt_ref=M.receipt_ref(r),revocation_ref=dict(scope=r['controller_scope'],id=transfer+'.revocation',revision='1',digest=P.digest(proof_body))),'notice_digest')

def receive_withdrawal(sd,cd,value,auth,ctx):
    validate('WithdrawalNotice',value);key=value['identity']
    authorize('observeContinuationWithdrawal',key['target_scope'],key['origin_scope'],auth,value['controller_scope'])
    need(value==notice(sd,cd,key['transfer_id']),'withdrawal_original')
    rows=P.rows(sd,'SELECT * FROM rc_target WHERE transfer_id=?',(key['transfer_id'],))
    targets=[r for r in rows if json.loads(r['target_body'])['controller_scope']==value['controller_scope']];need(len(targets)==1,'target')
    registration=targets[0]['registration_id'];T.withdraw(sd,cd,key['transfer_id'],registration,ctx)
    plans=P.rows(sd,'SELECT * FROM pq_plan WHERE registration_id=?',(registration,));need(len(plans)==1,'protection_plan')
    R.one(sd,'pq_commit','plan_id',plans[0]['plan_id'])
    result=dict(protocol_version=G.VERSION,identity=key,controller_scope=value['controller_scope'],notice_digest=value['notice_digest'],
        protection_plan_id=plans[0]['plan_id'],receipt_state='recorded',protection_completion='not_asserted')
    validate('WithdrawalAck',result);need(auth['response_authorized'],'response_authority');return result

def command_binding(sd,submission):
    sub,n,q,a=T.command_binding(sd,submission)
    r=json.loads(P.rows(sd,'SELECT receipt_body FROM rc_receipt WHERE transfer_id=? AND registration_id=?',(n['transfer_id'],n['registration_id']))[0]['receipt_body'])
    value=dict(origin_scope=q['origin_scope'],run_id=q['run_id'],generation=q['generation'],execution_id=sub['execution_id'],step_id=sub['step_id'],submission_id=submission,
        device_id=n['device_id'],transfer_ref=request_ref(q),adoption_ref=adoption_ref(a),receipt_ref=M.receipt_ref(r),grant_ref=json.loads(n['grant_ref_body']),plan_ref=q['continuation_plan_ref'])
    validate('CommandGrantBinding',value);return value

def public_ref(value,kind):
    # 类型来自调用点的固定语义，绝不通过对象ID或默认kind猜测。
    validate('Ref',value);need(kind in ('grant','artifact'),'reference_kind')
    return dict(kind=kind,scope=value['scope'],object_id=value['id'],revision=value['revision'],digest=value['digest'])
