"""普通触发采用、Controller命令关联与带预算的资格撤回参考writer。"""
import copy,json
import continuation_storage_model as C
import trigger_flow_model as F
import qualification_model as Q
import build_continuation_trigger as G
M=C.M;B=C.B;P=C.P;R=C.R;I=C.I;raw=C.raw

def inserted(sql,args):
    if not sql.startswith('INSERT INTO '):return None,None
    table=sql.split()[2].split('(')[0];names=[x.strip() for x in sql.split('(',1)[1].split(')',1)[0].split(',')]
    return table,dict(zip(names,args))

def ingress_steps(db,request,ctx):
    M.require(db.in_transaction,'transaction_required');adapted=copy.deepcopy(ctx)
    for run,value in adapted['evaluations'].items():
        r=R.one(db,'run','run_id',run)
        if r['lifecycle']!='armed' or not r['dispatch_eligible'] or r['active_operation_id'] or not value['qualified'] or not value['matched']:continue
        rows=P.rows(db,'SELECT * FROM rc_request WHERE run_id=? AND generation=?',(run,r['arm_generation']))
        if not rows:continue
        req=json.loads(rows[0]['request_body']);plan=ctx['continuation_plans'][run]
        M.require(req['continuation_plan_ref']==plan['ref'] and plan['ref']['digest']==M.digest(plan['steps']) and value['steps']==plan['steps'],'approved_program')
        current=P.rows(db,'SELECT * FROM cn_current WHERE run_id=?',(run,))
        for step in value['steps']:
            matches=[x for x in current if json.loads(x['target_body'])['controller_scope']==step['controller_scope']]
            M.require(len(matches)==1,'continuation_current');c=matches[0];receipt=json.loads(c['receipt_body'])
            step['request']['continuation']=dict(transfer_id=c['transfer_id'],registration_id=c['registration_id'],adoption_digest=c['adoption_digest'],grant_ref=receipt['continuation_grant_ref'])
    writes=[]
    for sql,args in F.ingress_steps(db,request,adapted):
        writes.append((sql,args));table,v=inserted(sql,args)
        if table=='execution_step_plan' and v['kind']=='action':
            req=json.loads(v['plan_body'])['request'];binding=req.get('continuation')
            if binding:writes.append(I('cn_step',execution_id=v['execution_id'],step_id=v['step_id'],transfer_id=binding['transfer_id'],registration_id=binding['registration_id'],
                device_id=req['device_id'],adoption_digest=binding['adoption_digest'],grant_ref_body=raw(binding['grant_ref'])))
    return writes

def receive_event(db,request,ctx,fail_after=None):
    M.require(ctx['authorized'] and ctx['source_authenticated'],'source_authority');existing=[]
    def builder():
        prior=P.rows(db,'SELECT * FROM ingress_inbox WHERE source_id=? AND(event_id=? OR source_sequence=?)',(request['source_id'],request['event_id'],request['source_sequence']))
        if prior:
            M.require(len(prior)==1 and prior[0]['content_body']==raw(request),'event_conflict');existing.append(True);return []
        return ingress_steps(db,request,ctx)
    C.tx(db,builder,fail_after);return 'existing' if existing else 'accepted'

def command_binding(sd,submission):
    sub=R.one(sd,'command_submission','submission_id',submission)
    rows=P.rows(sd,'SELECT * FROM cn_step WHERE execution_id=? AND step_id=?',(sub['execution_id'],sub['step_id']));M.require(len(rows)==1,'command_continuation')
    n=rows[0];q=json.loads(R.one(sd,'rc_request','transfer_id',n['transfer_id'])['request_body'])
    adoption=R.one(sd,'rc_adoption','transfer_id',n['transfer_id']);a=json.loads(adoption['adoption_body'])
    link=R.one(sd,'rc_r5_link','transfer_id',n['transfer_id']);R.one(sd,'flow_commit_seal','commit_id',link['commit_id'])
    M.require(a['adoption_digest']==n['adoption_digest']==link['adoption_digest'],'adoption_original')
    e=R.one(sd,'execution','execution_id',sub['execution_id']);r=R.one(sd,'run','run_id',sub['run_id'])
    M.require(e['origin_kind']=='trigger' and e['state']=='running' and r['active_execution_id']==e['execution_id'] and r['lifecycle']=='running'
        and r['arm_generation']==e['arm_generation']==q['generation'] and r['dispatch_eligible']==1,'current_execution')
    M.require(sub['state']=='attempt_recorded','submission_not_attempted')
    M.require(bool(sd.execute('SELECT 1 FROM cn_current WHERE transfer_id=? AND registration_id=?',(n['transfer_id'],n['registration_id'])).fetchone()),'continuation_revoked')
    M.require(not sd.execute('SELECT 1 FROM pause_latch WHERE run_id=? AND cleared_start_id IS NULL',(sub['run_id'],)).fetchone(),'run_paused')
    return sub,n,q,a

def admission_link(sd,cd,submission,command_id,ctx):
    M.require(cd.in_transaction,'transaction_required');sub,n,q,a=command_binding(sd,submission)
    t=next(t for t in q['targets'] if M.scope_key(t['controller_scope'])==(sub['target_authority'],sub['target_database']))
    _,c=C.controller_snapshot(cd,q,t,ctx);R.one(cd,'cr_commit','transfer_id',q['transfer_id'])
    M.receipt_eligible(q,c['durable_receipt'],c)
    M.require(ctx['write_authorized'] and ctx['parameters_verified'] and ctx['plan_verified'],'admission_authority')
    body=dict(origin_scope=q['origin_scope'],run_id=q['run_id'],generation=q['generation'],execution_id=sub['execution_id'],step_id=sub['step_id'],submission_id=submission,
        adoption_digest=a['adoption_digest'],continuation_grant_ref=json.loads(n['grant_ref_body']))
    return I('cn_command',command_id=command_id,transfer_id=q['transfer_id'],execution_id=sub['execution_id'],step_id=sub['step_id'],submission_id=submission,
        request_digest=sub['request_digest'],adoption_digest=a['adoption_digest'],grant_ref_body=n['grant_ref_body'],binding_body=raw(body))

def withdrawal_steps(sd,cd,transfer_id,registration,ctx):
    M.require(sd.in_transaction,'transaction_required');M.require(ctx['receipt_verified'] and ctx['receipt_durable'],'withdrawal_provider')
    q=json.loads(R.one(sd,'rc_request','transfer_id',transfer_id)['request_body']);p=R.one(sd,'p1_preparation','registration_id',registration)
    scope=R.one(cd,'controller_scope','singleton',1)
    M.require((p['controller_authority'],p['controller_database'])==(scope['authority_service_id'],scope['database_instance_id']),'withdrawal_scope')
    issue=R.one(cd,'cr_issue','transfer_id',transfer_id);M.require(issue['request_body']==raw(q),'withdrawal_request')
    proof=R.one(cd,'cr_revocation','transfer_id',transfer_id);proof_body=raw({k:(v.hex() if isinstance(v,bytes) else v) for k,v in proof.items()})
    if sd.execute('SELECT 1 FROM cn_withdrawal WHERE transfer_id=? AND registration_id=?',(transfer_id,registration)).fetchone():return []
    value=Q.seal_withdrawal(dict(contract_version=Q.SCHEMA['$defs']['Withdrawal']['properties']['contract_version']['const'],event_id=transfer_id+'.withdrawal',
        binding=json.loads(p['binding_body']),reason='authorization_revoked',proof_ref=dict(scope=dict(authority_service_id=p['controller_authority'],database_instance_id=p['controller_database']),
        id=transfer_id+'.revocation',revision='1',digest=P.digest(proof_body))))
    Q.withdrawal_valid(value)
    return [I('cn_withdrawal',transfer_id=transfer_id,registration_id=registration,proof_body=proof_body)]+Q.invalidate_steps(sd,registration,'withdrawal',value)

def withdraw(sd,cd,transfer,registration,ctx,fail_after=None):
    return B.apply(sd,lambda:withdrawal_steps(sd,cd,transfer,registration,ctx),ctx,fail_after)
