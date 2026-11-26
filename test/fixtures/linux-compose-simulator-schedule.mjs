import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {setTimeout as delay} from 'node:timers/promises';

const route='/auth/local-schedules/v1';
const id=()=>crypto.randomUUID();
const waitingForClock=(response,body)=>response.status===503&&['WORKER_NOT_READY','CLOCK_UNTRUSTED'].includes(body.error);
export const schedulePermissions=['schedule.read','schedule.publish','schedule.activate'];

export async function runComposeSimulatorSchedule({armed,compiled,localRequest,bearer,readRun,waitFor,withdrawReference=null,readDispatchWithdrawal=null}){
  async function request(operation,input,retryClock=false){
    const response=await localRequest(route,operation,input,bearer);
    const body=JSON.parse(response.data);
    if(retryClock&&waitingForClock(response,body))return null;
    assert.equal(response.status,200,operation+' '+response.data);
    return body.result;
  }
  async function context(operation_id){
    const {context_id}=await request('create-context',{operation_id,ttl_ms:30000,max_unique_requests:1});
    return {context_id,idempotency_key:id()};
  }
  const priorRun=withdrawReference?await readRun():null;
  if(priorRun){assert.equal(priorRun.lifecycle,'armed');assert.equal(priorRun.active_execution_id,null);}
  const schedule_id=id(),publish=await context('publishSchedule'),activate=await context('activateSchedule');
  const start=Date.now()+8000,local_start=new Date(start).toISOString().slice(0,-1);
  const actionSteps=compiled.program.groups.flatMap(group=>group.steps.filter(step=>step.kind==='action'));
  assert.equal(actionSteps.length,1);
  const [{step_id,parameters}]=actionSteps;
  const published=await waitFor(()=>request('publish',{schedule_id,version:{context:publish,definition_id:armed.definition_id,
    definition_version:armed.definition_version,expected_artifact_ref:armed.artifact_ref,expected_version:null,
    items:[{item_id:'show',one_shot_key:'once',local_start,offset:'+00:00',
      steps:[{step_id,role:'on_air',start_offset_ms:0,latest_start_offset_ms:12000}]}]}},true),2500,
    'Schedule publication did not acquire a trusted clock');
  const activation=await waitFor(()=>request('activate',{schedule_id,activation:{context:activate,expected_revision:null,schedule_version_ref:published.ref}},true),2500,
    'Schedule activation did not acquire a trusted clock');
  const read=async()=>{
    const response=await localRequest(route,'get',{schedule_id,version:null},bearer);
    const body=JSON.parse(response.data);
    if(waitingForClock(response,body))return null;
    assert.equal(response.status,200,response.data);
    return body.result.occurrences[0];
  };
  const tracking=await waitFor(read);
  assert.equal(tracking.state,'tracking',JSON.stringify(tracking));
  if(withdrawReference){
    assert.ok(Date.now()<start,'Schedule window opened before reference withdrawal');
    const restore=withdrawReference();
    let blocked;
    try{
      blocked=await waitFor(async()=>{
        const occurrence=await read();
        if(!occurrence)return null;
        assert.ok(['tracking','reference_unavailable','blocked'].includes(occurrence.state),JSON.stringify(occurrence));
        return occurrence.state==='blocked'&&occurrence;
      },16000,'Scheduled occurrence did not persist its stop');
      assert.equal(blocked.occurrence_id,tracking.occurrence_id);
      assert.equal(blocked.stop.reason,'reference_time_lost');
      assert.deepEqual(blocked.stop.boundary_ref,tracking.boundary_ref);
      assert.deepEqual(blocked.stop.activation_ref,activation.ref);
    }finally{restore();}
    await delay(750);
    assert.ok(Date.now()<start+12000,'The original step window expired before the stopped occurrence was checked again');
    assert.deepEqual(await waitFor(read),blocked);
    const run=await readRun();
    assert.equal(run.active_execution_id,null);
    assert.equal(run.lifecycle,'armed');
    assert.equal(run.last_execution_id,priorRun.last_execution_id);
    return blocked.stop;
  }
  let qualification=null;
  const admission=await waitFor(async()=>{
    await delay(350);
    const occurrence=await read();
    if(!occurrence)return null;
    qualification=occurrence.qualification??qualification;
    assert.ok(['tracking','accepted'].includes(occurrence.state),
      JSON.stringify({state:occurrence.state,reason:occurrence.stop?.reason,qualification}));
    return occurrence.state==='accepted'&&occurrence.admission;
  },22000);
  assert.deepEqual(admission.activation_ref,activation.ref);
  assert.equal(admission.first_step_id,step_id);
  let observedRun=null;
  const run=await waitFor(async()=>{
    await delay(350);
    const current=await readRun();
    observedRun={lifecycle:current.lifecycle,active:current.active_execution_id===admission.execution_id,
      completed:current.last_execution_id===admission.execution_id};
    if(readDispatchWithdrawal&&observedRun.lifecycle==='paused'){
      assert.equal(observedRun.active,true);
      assert.equal(observedRun.completed,false);
      return current;
    }
    assert.ok(['armed','running'].includes(current.lifecycle),JSON.stringify(observedRun));
    if(!observedRun.completed)return false;
    assert.equal(readDispatchWithdrawal,null,'Scheduled dispatch unexpectedly completed');
    assert.equal(current.lifecycle,'armed');
    assert.equal(current.active_execution_id,null);
    return current;
  },18000).catch(error=>{throw new Error('Scheduled run did not settle '+JSON.stringify(observedRun),{cause:error});});
  const withdrawal=readDispatchWithdrawal?.()??null;
  if(readDispatchWithdrawal)assert.ok(withdrawal,'Controller did not withdraw before the scheduled write');
  return {admission,parameters,run,withdrawal};
}

export function verifyDurableSimulatorScheduleStop(receiver,publisher,stopped,digest){
  const {occurrence_id}=stopped;
  const row=receiver.prepare('SELECT body_jcs,body_digest FROM schedule_occurrence_stop WHERE occurrence_id=?').get(occurrence_id);
  assert.deepEqual(JSON.parse(row.body_jcs),stopped);
  assert.equal(row.body_digest,digest(stopped));
  assert.equal(receiver.prepare('SELECT 1 FROM schedule_execution_admission WHERE occurrence_id=?').get(occurrence_id),undefined);
  assert.equal(publisher.prepare(`SELECT 1 FROM command_admission_source
    WHERE json_extract(body_jcs,'$.metadata.dispatch.mode')='scheduled'`).get(),undefined);
}

export function verifyDurableSimulatorDispatchWithdrawal(receiver,publisher,{admission,withdrawal},digest){
  const {execution_id,first_step_id}=admission,{command_id,permit_id,guard_id,tick_ns}=withdrawal;
  const saved=receiver.prepare('SELECT body_jcs,body_digest FROM schedule_execution_admission WHERE execution_id=?').get(execution_id);
  assert.deepEqual(JSON.parse(saved.body_jcs),admission);
  assert.equal(saved.body_digest,digest(admission));
  const terminal=JSON.parse(receiver.prepare('SELECT body_jcs FROM automation_execution_command_terminal WHERE execution_id=? AND step_id=?')
    .get(execution_id,first_step_id).body_jcs);
  assert.equal(terminal.command_ref.object_id,command_id);
  assert.equal(terminal.state.outcome,'blocked');
  assert.equal(terminal.state.reason_code,'execution_closed');
  assert.equal(receiver.prepare('SELECT 1 FROM automation_execution_commit WHERE execution_id=?').get(execution_id),undefined);
  const original=JSON.parse(publisher.prepare('SELECT body_jcs FROM command_admission_source WHERE command_id=?').get(command_id).body_jcs);
  assert.equal(original.schedule_binding.occurrence_ref.id,admission.occurrence_id);
  const final=JSON.parse(publisher.prepare('SELECT body_jcs FROM command_final_admission WHERE permit_id=? AND command_id=?').get(permit_id,command_id).body_jcs);
  assert.equal(final.guard.time_required,true);
  assert.equal(final.guard.guard_id,guard_id);
  assert.ok(BigInt(tick_ns)<BigInt(final.seal.send_window.before_tick_ns));
  const dispatch=publisher.prepare(`SELECT d.record_id,g.disposition FROM command_dispatch_request d
    JOIN command_guard_ack g USING(guard_id) WHERE d.permit_id=? AND d.guard_id=?`).get(permit_id,guard_id);
  assert.equal(dispatch.disposition,'installed');
  assert.equal(publisher.prepare('SELECT 1 FROM execution_write_attempt WHERE record_id=?').get(dispatch.record_id),undefined);
  for(const table of ['command_dispatch_write','command_dispatch_report','command_dispatch_evidence','command_settlement'])
    assert.equal(publisher.prepare('SELECT 1 FROM '+table+' WHERE permit_id=?').get(permit_id),undefined,table);
  const invalidation=JSON.parse(publisher.prepare('SELECT body_jcs FROM time_provider_reference_invalidation WHERE anchor_id=?')
    .get(original.accepted_reference.anchor_ref.id).body_jcs);
  assert.equal(invalidation.cause,'authority_changed');
  assert.equal(invalidation.minimum_time_generation,'2');
  assert.ok(publisher.prepare('SELECT 1 FROM execution_session_end WHERE ipc_session_id=?').get(final.seal.binding.ipc_session_id));
  const closure=JSON.parse(publisher.prepare('SELECT body_jcs FROM command_unsent_closure WHERE permit_id=?').get(permit_id).body_jcs);
  assert.equal(closure.evidence[0].body.kind,'never_sent');
  assert.equal(closure.future_writes_closed.automatic_resends,false);
  assert.equal(closure.record_digest,terminal.record_ref.digest);
}

export function verifyDurableSimulatorSchedule(receiver,publisher,{admission,parameters},digest){
  const {execution_id,first_step_id}=admission;
  const stored=receiver.prepare('SELECT body_jcs,body_digest FROM schedule_execution_admission WHERE execution_id=?').get(execution_id);
  assert.deepEqual(JSON.parse(stored.body_jcs),admission);
  assert.equal(stored.body_digest,digest(admission));
  const terminal=JSON.parse(receiver.prepare('SELECT body_jcs FROM automation_execution_command_terminal WHERE execution_id=? AND step_id=?')
    .get(execution_id,first_step_id).body_jcs);
  assert.equal(terminal.state.outcome,'succeeded');
  assert.equal(terminal.completion_achieved,'effect_verified');
  const {notification_jcs}=receiver.prepare('SELECT notification_jcs FROM automation_execution_commit WHERE execution_id=?').get(execution_id);
  assert.equal(JSON.parse(notification_jcs).event_id,execution_id+'.completed');
  const commandId=terminal.command_ref.object_id;
  const settled=publisher.prepare('SELECT body_jcs,body_digest FROM command_settlement WHERE command_id=?').get(commandId);
  const settlement=JSON.parse(settled.body_jcs);
  assert.equal(digest(settlement),settled.body_digest);
  assert.equal(settlement.record_digest,terminal.record_ref.digest);
  assert.equal(settlement.state_digest,terminal.state_ref.digest);
  assert.equal(settlement.module_settlement.module_settled,true);
  const installed=publisher.prepare(`SELECT frame_jcs FROM command_final_admission a
    JOIN command_guard_request g ON g.final_transaction_id=a.transaction_id
    JOIN execution_frame_record f ON f.record_id=g.record_id
    WHERE a.command_id=?`).get(commandId);
  const guard=JSON.parse(installed.frame_jcs).body;
  assert.equal(guard.guard.time_required,true);
  assert.equal(guard.reference_context.bundle_digest,guard.guard.reference_time.context_ref.digest);
  assert.ok(guard.schedule_guard);
  const effect=publisher.prepare("SELECT origin_jcs FROM device_source_event WHERE json_extract(origin_jcs,'$.payload.value.value')=?")
    .all(parameters.value);
  assert.equal(effect.length,1);
  assert.equal(JSON.parse(effect[0].origin_jcs).payload.value.write_sequence,'1');
  for(const db of [receiver,publisher])assert.ok(db.prepare('SELECT 1 FROM time_provider_reference_anchor LIMIT 1').get());
}
