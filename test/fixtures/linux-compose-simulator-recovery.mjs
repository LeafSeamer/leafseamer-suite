import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {runApprovalRoute} from './linux-compose-simulator-publication.mjs';

const id=()=>crypto.randomUUID();
export const recoveryPermissions=['run.approval.revoke','run.resume'];

export async function reconcileComposeSimulatorWrite({scheduled,priorApproval,bindingId,admin,localRequest,bearer,readRun,waitFor,digest}){
  const {run_id,revision}=scheduled.run,{execution_id,first_step_id}=scheduled.admission;
  const approval=priorApproval.approval_ref;
  async function send(operation,input){
    const reply=await localRequest(runApprovalRoute,operation,input,bearer);
    return {...reply,body:JSON.parse(reply.data)};
  }
  async function call(operation,request,status=200){
    const reply=await send(operation,request);
    assert.equal(reply.status,status,operation+' '+reply.data);
    return reply.body.result;
  }
  async function context(operation,max_unique_requests=1){
    const {context_id}=await call(operation,{ttl_ms:30000,max_unique_requests});
    return {context_id,idempotency_key:id()};
  }
  async function until(operation,request,ready){
    let latest;
    return waitFor(async()=>{
      latest=await call(operation,request);
      return ready(latest)&&latest;
    },12000).catch(error=>{throw new Error(operation+' '+JSON.stringify(latest),{cause:error});});
  }
  const revoked=await call('revoke',{approval_id:approval.object_id,revocation:{context:await context('create-revocation-context'),
    approval_ref:approval,expected_status_revision:'1',reason:'核对已完成的模拟器效果'}});
  await until('inspect-operation',{operation_id:revoked.operation_id},value=>value.state==='applied');
  const original={run_id,execution_id};
  const preflight=await call('preflight-recovery',original);
  assert.equal(preflight.current_protection.state,'verified',JSON.stringify(preflight.current_protection));
  assert.equal(preflight.current_resources.state,'verified',JSON.stringify(preflight.current_resources));
  assert.deepEqual(preflight.current_resources.steps.map(step=>step.state),['released']);
  assert.deepEqual(preflight.steps.map(step=>step.terminal.outcome),['succeeded']);

  const paused=await readRun();
  assert.equal(paused.lifecycle,'paused');
  assert.notEqual(paused.revision,revision);
  const resumeContext=await context('create-resume-context',4);
  const {operation}=await waitFor(async()=>{
    const {preview_ref,preview}=await call('preview-recovery',{...original,expected_revision:paused.revision});
    assert.equal(preview_ref.digest,digest(preview));
    assert.equal(preview.plan.mode,'reconcile_commit',JSON.stringify(preview.plan));
    assert.deepEqual(preview.plan.items.map(item=>[item.step_id,item.decision]),[[first_step_id,'retain_success']]);
    const reply=await send('resume',{run_id,reservation:{context:resumeContext,expected_revision:paused.revision,preview_ref}});
    if(reply.status===409&&reply.body.error==='PREFLIGHT_EXPIRED')return null;
    assert.equal(reply.status,202,'resume '+reply.data);
    return reply.body.result;
  },8000,'Fresh recovery preview expired before reservation');
  const {operation_id,new_execution_id}=operation;
  const pending=await readRun();
  assert.equal(pending.active_execution_id,new_execution_id);

  const {proposal_ref}=await call('propose',{run_id,proposal:{...priorApproval.proposalRequest.proposal,
    context:await context('create-proposal-context'),expected_run_revision:pending.revision}});
  const {endorsement_ref}=await admin('endorse-run',{binding_id:bindingId,proposal_ref,idempotency_key:id()});
  const {approval_ref}=await call('approve',{run_id,approval:{context:await context('create-approval-context'),
    controller_endorsement_refs:[endorsement_ref],expected_prior_approval_ref:approval,expected_run_revision:pending.revision,proposal_ref}});
  const choose={run_id,operation_id},{context_id}=resumeContext;
  const prepared=await until('prepare-recovery',{...choose,context_id},value=>value.state==='receipts_observed');
  assert.equal(prepared.targets.length,1);
  const {binding_ref}=await call('bind-recovery-execution',{...choose,context_id});
  const start={binding_ref,context_id};
  const started=await call('start-recovery-execution',{...choose,start},202);
  assert.deepEqual(started.start.steps.map(step=>[step.decision,step.grant_ref]),[['retain_success',null]]);
  const result=await until('get-recovery-operation',choose,value=>value.completion);
  const {completion}=result;
  assert.equal(completion.digest,digest(completion.body));
  assert.equal(completion.body.source_execution_ref.object_id,execution_id);
  assert.equal(completion.notification.event_id,new_execution_id+'.completed');
  const finished=await readRun();
  assert.equal(finished.lifecycle,'paused');
  assert.equal(finished.active_execution_id,null);
  assert.equal(finished.active_operation_id,null);
  assert.equal(finished.last_execution_id,new_execution_id);
  assert.deepEqual(await call('start-recovery-execution',{...choose,start},202),started);
  assert.deepEqual(await call('get-recovery-operation',choose),result);
  return {operationId:operation_id,completion,preparation:prepared.targets[0],approval:{...priorApproval,proposal_ref,endorsement_ref,approval_ref}};
}
