import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {setTimeout as delay} from 'node:timers/promises';

const route='/auth/local-schedules/v1';
const id=()=>crypto.randomUUID();
const waitingForClock=(response,body)=>response.status===503&&['WORKER_NOT_READY','CLOCK_UNTRUSTED'].includes(body.error);
export const schedulePermissions=['schedule.read','schedule.publish','schedule.activate'];

export async function runComposeSimulatorSchedule({armed,compiled,localRequest,bearer,readRun,waitFor}){
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
  const schedule_id=id(),publish=await context('publishSchedule'),activate=await context('activateSchedule');
  const local_start=new Date(Date.now()+8000).toISOString().slice(0,-1);
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
  const completedRun=await waitFor(async()=>{
    await delay(350);
    const current=await readRun();
    observedRun={lifecycle:current.lifecycle,active:current.active_execution_id===admission.execution_id,
      completed:current.last_execution_id===admission.execution_id};
    assert.ok(['armed','running'].includes(current.lifecycle),JSON.stringify(observedRun));
    if(!observedRun.completed)return false;
    assert.equal(current.lifecycle,'armed');
    assert.equal(current.active_execution_id,null);
    return current;
  },18000).catch(error=>{throw new Error('Scheduled run did not settle '+JSON.stringify(observedRun),{cause:error});});
  return {admission,parameters,completedRun};
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
