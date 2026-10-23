"""动作失败保护的原子参考写集；关闭能力来自显式授信系统提供者。"""
import json
import build_failure_protection as G
import trigger_flow_model as F
A=F.A;P=F.P;R=F.R;I=F.I
def terminal_steps(db,execution,step_id,outcome,ctx):
    R.require(db.in_transaction,'transaction_required')
    base=F.terminal_steps(db,execution,step_id,outcome,ctx)
    required=db.execute('SELECT required FROM execution_step_plan WHERE execution_id=? AND step_id=?',(execution,step_id)).fetchone()[0]
    if outcome=='succeeded' or(outcome=='failed' and not required):return base
    R.require(ctx['trusted_system_closer'],'protection_authority')
    e=R.one(db,'execution','execution_id',execution);r=R.one(db,'run','run_id',e['run_id']);slot=R.one(db,'activation_slot','definition_id',r['definition_id'])
    gen=e['arm_generation'];terminal=execution+'.'+step_id+'.terminal';plan=terminal+'.protection'
    active=r['active_execution_id']==execution and r['arm_generation']==gen and r['lifecycle']!='completed'
    preparations=[x for x in P.rows(db,'SELECT * FROM p1_preparation WHERE run_id=? ORDER BY registration_id',(r['run_id'],)) if int(x['generation'])<=int(gen)]
    executions=[x for x in P.rows(db,'SELECT * FROM execution WHERE run_id=? ORDER BY execution_id',(r['run_id'],)) if int(x['arm_generation'])<=int(gen)]
    ids={x['execution_id'] for x in executions}
    submissions=[x for x in P.rows(db,'SELECT * FROM command_submission WHERE run_id=? ORDER BY submission_id',(r['run_id'],)) if x['execution_id'] in ids]
    members=[dict(kind='preparation',ref=x['registration_id'],body=x['binding_body'].hex().upper()) for x in preparations]
    members += [dict(kind='execution',ref=x['execution_id'],body=x['binding_digest']) for x in executions]
    members += [dict(kind='submission',ref=x['submission_id'],body=x['request_body'].hex().upper()) for x in submissions]
    targets=sorted({(x['controller_authority'],x['controller_database']) for x in preparations}|{(x['target_authority'],x['target_database']) for x in submissions})
    body=P.canonical(dict(terminal_id=terminal,outcome=outcome,run_id=r['run_id'],generation=gen,members=members,controllers=[list(x) for x in targets]))
    writes=[I('sf_plan',plan_id=plan,terminal_id=terminal,execution_id=execution,execution_state_before=e['state'],step_id=step_id,run_id=r['run_id'],generation=gen,current_generation=r['arm_generation'],
        revision_before=r['revision'],revision_after=P.inc(r['revision']) if active else r['revision'],lifecycle_before=r['lifecycle'],dispatch_before=r['dispatch_eligible'],
        active_execution_before=r['active_execution_id'],active_operation_before=r['active_operation_id'],slot_revision=slot['revision'],slot_run=slot['active_run_id'],slot_version=slot['version'],
        affects_current=int(active),latch_id=terminal+'.latch' if active else None,outcome=outcome,preparation_head=db.execute('SELECT coalesce(max(sequence),0) FROM p1_preparation').fetchone()[0],
        target_count=len(targets),inventory_body=P.canonical(members),plan_digest=P.digest(body),plan_body=body)]
    for sql,args in base:
        if sql.startswith('INSERT INTO step_terminal('):
            data=dict(zip(sql.split('(',1)[1].split(')',1)[0].split(','),args));data['protection_plan_id']=plan;writes.append(I('step_terminal',**data))
        else:writes.append((sql,args))
    origin=P.rows(db,'SELECT * FROM storage_scope')[0];bindings={}
    for i,(ca,cd) in enumerate(targets):
        target=plan+'.'+str(i);selector=dict(origin_scope=dict(authority_service_id=origin['authority_id'],database_instance_id=origin['database_id']),run_id=r['run_id'],deny_through_generation=gen)
        binding=dict(controller_scope=dict(authority_service_id=ca,database_instance_id=cd),operation_id=target,**selector,selector_digest=P.digest(P.canonical(selector)),target_set_digest=P.digest(body))
        bindings[target]=P.canonical(binding)
        writes.append(I('sf_target',plan_id=plan,target_id=target,controller_authority=ca,controller_database=cd,binding_body=bindings[target],dispatch_body=P.canonical(dict(kind='protect_registered_run',binding=binding))))
    writes.append(I('sp_plan',plan_id=plan,plan_digest=P.digest(body),target_count=len(targets),plan_body=body))
    writes += [I('sp_target',plan_id=plan,target_id=t,binding_body=b) for t,b in bindings.items()]
    writes.append(I('sp_plan_commit',plan_id=plan,validation_body=P.canonical(dict(failure_plan_id=plan))))
    writes.append(I('sf_commit',plan_id=plan,audit_body=P.canonical(dict(terminal_id=terminal)),notification_body=P.canonical(dict(kind='step_failure_protected',plan_id=plan))))
    return writes

def terminal(db,execution,step_id,outcome,ctx,fail_after=None):
    R.require(ctx['terminal_evidence_verified'],'terminal_unqualified');found=[]
    def builder():
        prior=P.rows(db,'SELECT * FROM step_terminal WHERE execution_id=? AND step_id=?',(execution,step_id))
        if prior:
            t=prior[0];R.require(t['outcome']==outcome and t['evidence_body']==P.canonical(dict(outcome=outcome,completion_ref=ctx.get('completion_command_ref'))),'terminal_identity_conflict')
            if t['protection_plan_id']:R.require(ctx['trusted_system_closer'],'protection_authority');R.one(db,'sf_commit','plan_id',t['protection_plan_id'])
            found.append(True);return []
        return terminal_steps(db,execution,step_id,outcome,ctx)
    A.apply(db,builder,fail_after);return 'existing' if found else 'committed'
