import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {composeSimulatorDeviceScope} from './linux-compose-simulator-publication.mjs';

const id=()=>crypto.randomUUID();
const reference=({id,revision,digest})=>({id,revision,digest});
const route='/auth/local-source-subscriptions/v1';

export function readSimulatorFile(files,name){
  const failure=fs.existsSync(files.result)&&fs.statSync(files.result).size?JSON.parse(fs.readFileSync(files.result,'utf8')):null;
  if(failure)assert.equal(failure.ok,true,failure.error);
  return fs.existsSync(files[name])&&fs.statSync(files[name]).size?JSON.parse(fs.readFileSync(files[name],'utf8')):null;
}

export async function verifyComposeSimulatorSubscription({plan,simulator,baseline,pairing,admin,localRequest,waitFor,digest,beforeWrite=null,afterWrite=null,scheduledDispatch=false}){
  const {controller,seamer}=plan,{scope}=baseline;
  const pairing_ref={id:pairing.binding_id,revision:pairing.revision,digest:pairing.digest};
  const {not_before_ns,expires_ns}=pairing;
  const consumer_id='canonical-simulator',permissions=['event.internal.subscribe','status.read'];
  const consumer_slots=[{publisher_service_id:controller.service_id,consumer_service_id:seamer.service_id,
    consumer_database_instance_id:seamer.database_instance_id,consumer_id,purpose:'canonical_trigger',max_subscriptions:1,
    allowed_scope_ref:scope.scope_ref,pairing_ref}];
  const principal=await admin('create-event-consumer',{request_id:id(),display_name:'Compose simulator events'});
  const request={request_id:id(),consumer_id,scope:scope.scope};
  const submit=()=>localRequest(route,'connect',request);
  assert.equal((await submit()).status,403);
  const {device_ids}=composeSimulatorDeviceScope(controller,baseline);
  const common={principal_id:principal.id,permissions,device_ids,not_before_ns,expires_ns,consumer_slots};
  const {approval,principal:subject}=await admin('approve-event-consumer',{...common,request_id:id(),expected_revision:principal.revision,audiences:[controller.service_id]});
  assert.equal(approval.format,'local-service-approval/2');
  assert.equal((await submit()).status,403);
  const policy=await admin('approve-event-policy',{...common,request_id:id(),subject_ref:reference(subject),
    approval_ref:reference(approval),audience:controller.service_id});
  assert.equal(policy.format,'local-service-receiver-policy/2');
  const linked=await waitFor(async()=>{
    const {status,data}=await submit();
    assert.equal(status,200,data);
    const {result}=JSON.parse(data);
    return result.transport_ready&&result;
  });
  assert.equal(linked.state,'confirmed');
  await beforeWrite?.();
  const publisher=new DatabaseSync(path.join(controller.data_dir,'controller.sqlite'),{readOnly:true,timeout:500});
  try{
    fs.writeFileSync(simulator.proceed,'');
    await waitFor(()=>{
      readSimulatorFile(simulator,'result');
      const event=publisher.prepare(`SELECT d.cursor FROM service_subscription_delivery d
        JOIN service_subscription_delivery_ack a USING(subscription_id,cursor)
        WHERE d.subscription_id=? AND json_extract(d.body_jcs,'$.payload.origin.source_sequence')='2'`).get(linked.subscription_id);
      return event&&publisher.prepare(`SELECT 1 FROM service_subscription_delivery d
        JOIN service_subscription_delivery_ack a USING(subscription_id,cursor)
        WHERE d.subscription_id=? AND d.cursor>? AND json_extract(d.body_jcs,'$.entry_kind')='entity.upsert'`).get(linked.subscription_id,event.cursor);
    });
    const original=publisher.prepare('SELECT origin_jcs,origin_digest FROM device_source_event WHERE source_sequence=?').get('2');
    const event={origin:JSON.parse(original.origin_jcs),origin_digest:original.origin_digest};
    assert.equal(digest(event.origin),event.origin_digest);
    assert.deepEqual(event.origin.payload.value,{value:23,write_sequence:'2'});
    const replay=await submit();
    assert.equal(replay.status,200,replay.data);
    assert.deepEqual(JSON.parse(replay.data).result,linked);
    await afterWrite?.();
    fs.writeFileSync(simulator.finish,'');
    const result=await waitFor(()=>readSimulatorFile(simulator,'result'));
    assert.deepEqual(result.simulatorEvent.incremental.event,event);
    assert.match(fs.readFileSync(simulator.groupFile+'/cgroup.events','utf8'),/^populated 0$/m);
    assert.equal(publisher.prepare('SELECT count(*) AS n FROM command_settlement').get().n,scheduledDispatch?3:2);
    return {linked,event,sourceKey:baseline.baseline.origin.source_key};
  }finally{publisher.close();}
}

// Seamer 正常运行时独占文件库，退役后对照两端的原始提交。
export function verifyDurableSimulatorSubscription({receiver,publisher,linked,event,sourceKey,scheduledDispatch=false}){
  const snapshot=receiver.prepare('SELECT body_jcs,receipt_jcs FROM snapshot_ingest_apply WHERE apply_id=?').get(linked.apply_id);
  const stored=JSON.parse(snapshot.body_jcs),receipt=JSON.parse(snapshot.receipt_jcs);
  assert.equal(receipt.delivery_binding.subscription_id,linked.subscription_id);
  assert.equal(stored.projection.records.length,1);
  assert.deepEqual(stored.projection.records[0].view.source_key,sourceKey);
  assert.equal(stored.projection.records[0].view.contiguous_sequence,'1');
  const consumed=receiver.prepare(`SELECT body_jcs,body_digest,observation_jcs,receiver_boot_id,
    connection_generation,cursor,receive_sequence FROM subscription_reconcile_inbox WHERE apply_id=? AND event_id=?`).get(linked.apply_id,event.origin.event_id);
  assert.deepEqual(JSON.parse(consumed.body_jcs),{entry_kind:'source.event',payload:event});
  const observation=JSON.parse(consumed.observation_jcs);
  assert.equal(consumed.receiver_boot_id,receipt.service_boot_id);
  assert.equal(consumed.receive_sequence,1);
  assert.equal(observation.delivery_mode,'live');
  if(scheduledDispatch)assert.ok(['trusted_utc','unproven'].includes(observation.age_basis));
  else assert.equal(observation.age_basis,'unproven');
  assert.equal(observation.disposition.state,'observed_only');
  const acknowledged=publisher.prepare(`SELECT d.body_digest,a.connection_generation FROM service_subscription_delivery d
    JOIN service_subscription_delivery_ack a USING(subscription_id,cursor) WHERE d.subscription_id=? AND d.cursor=?`)
    .get(linked.subscription_id,consumed.cursor);
  assert.equal(acknowledged.body_digest,consumed.body_digest);
  assert.equal(acknowledged.connection_generation,consumed.connection_generation);
  assert.equal(receiver.prepare('SELECT count(*) AS n FROM subscription_reconcile_inbox WHERE event_id IS NOT NULL').get().n,1);
  assert.deepEqual(receiver.prepare('PRAGMA foreign_key_check').all(),[]);
}
