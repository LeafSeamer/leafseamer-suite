import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {once} from 'node:events';
import {DatabaseSync} from 'node:sqlite';
import {pathToFileURL} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import test from 'node:test';
import {createInstallationStore,openInstallationStore} from '../dist/installation-store.mjs';
import {linuxContainerCgroup} from '../dist/linux-cgroup-retirement.mjs';
import {canonical,digest} from '../dist/import-input.mjs';
import {sealLinuxWorker} from './fixtures/linux-worker-materialization.mjs';

const controller=process.env.LEAFSEAMER_CONTROLLER_BOOTSTRAP_DIST;
const options={skip:process.platform!=='linux'||process.env.LEAFSEAMER_TEST_NATIVE_CGROUP!=='1'||!controller,timeout:40000};
const id=()=>crypto.randomUUID();
const sum=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const empty=group=>/^populated 0$/m.test(fs.readFileSync(group+'/cgroup.events','utf8'));
const load=name=>import(pathToFileURL(path.join(controller,name)));
async function until(operation){
  for(let attempt=0;attempt<160;attempt++){
    const answer=await operation();if(answer)return answer;
    await delay(50);
  }
  assert.fail('Linux native control did not reach the expected state');
}

async function start(t,{authorization=false,create=false}={}){
  assert.equal(process.geteuid(),0);
  const {initializeStorage,migrateStorage}=await load('storage.mjs'),{openNativeClock}=await load('native-clock.mjs');
  const source=openNativeClock(),scratch=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-worker-control-'));
  const data=path.join(scratch,'controller'),installation=path.join(scratch,'installation');
  fs.chmodSync(scratch,0o755);
  fs.mkdirSync(data,{mode:0o700});fs.mkdirSync(installation,{mode:0o700});
  const identity=initializeStorage(data);await migrateStorage(data,109);
  for(const entry of fs.readdirSync(data))fs.chownSync(path.join(data,entry),65534,65534);
  fs.chownSync(data,65534,65534);
  createInstallationStore(installation);const store=openInstallationStore(installation);
  store.initializeLinuxMemberJournal();const journal=store.openLinuxMemberJournal(()=>true);
  const generation=id(),launchId=id(),workerId=id(),role='controller';
  const {groupPath}=linuxContainerCgroup({driver:'cgroupfs',generationId:generation,role});
  const parent='/sys/fs/cgroup'+groupPath,core=parent+'/core',worker=parent+'/worker_'+workerId.replaceAll('-','');
  for(const directory of [parent,core,worker])fs.mkdirSync(directory);
  let closed=false,sealed;
  function close(){if(!closed){closed=true;sealed?.close();journal.close();store.close();}}
  t.after(async()=>{
    close();fs.writeFileSync(parent+'/cgroup.kill','1');await until(()=>empty(parent));
    for(const directory of [worker,core,parent])fs.rmdirSync(directory);
    assert.equal(path.dirname(scratch),os.tmpdir());fs.rmSync(scratch,{recursive:true});
  });
  const node=fs.realpathSync(process.execPath),nodeDigest=sum(fs.readFileSync(node));
  const artifactDigest=digest({controller_build_sha256:sum(fs.readFileSync(path.join(controller,'build-manifest.json'))),node_sha256:nodeDigest});
  const policy={format:'leafseamer-core-bootstrap-policy/1',service_id:identity.service_id,database_instance_id:identity.database_instance_id,
    artifact_manifest_ref:{manifest_id:'controller.test',revision:'1',digest:artifactDigest},platform_profile_ref:{profile_id:'linux.test',revision:'1'},
    policy_revision:'1',bootstrap_timeout_ms:5000,clock_backend_revision:'1'};
  const listener=net.createServer().listen(0,'127.0.0.1');await once(listener,'listening');
  const {port}=listener.address();await new Promise(resolve=>listener.close(resolve));
  const args=['--disallow-code-generation-from-strings'];
  const result=path.join(data,'authorization.json');
  let materialization=null,runtime=null,channelDirectory;
  if(create){
    const {deviceModuleEventProtocol}=await load('sdk/device-module.mjs');
    const directory=path.join(scratch,'worker-runtime');fs.mkdirSync(directory,{mode:0o711});
    channelDirectory=path.join(scratch,'channels');fs.mkdirSync(channelDirectory,{mode:0o755});
    const capability=JSON.parse(fs.readFileSync(path.join(controller,'simulator-control-capability.json'),'utf8'));
    const template=Buffer.from(JSON.stringify(capability));
    const fileHash=bytes=>'sha256:'+sum(bytes);
    sealed=await sealLinuxWorker(t,{directory:scratch,serviceId:identity.service_id,sharedStore:store,profileId:policy.platform_profile_ref.profile_id,
      moduleBytes:fs.readFileSync(path.join(controller,'simulator-control-module.mjs')),protocol:deviceModuleEventProtocol,
      apiVersions:['leafseamer-device-event-capture/1','leafseamer-device-module/2','leafseamer-device-primitives/1'],customize({payload,manifest,inventory}){
        const config={path:'config.txt',role:'schema',bytes:Buffer.from('{}')};payload.set('config',config);
        Object.assign(inventory.files.find(file=>file.file_id==='config'),{path:config.path,size_bytes:'2',digest:fileHash(config.bytes)});
        const policy=payload.get('policy');policy.bytes=fs.readFileSync(path.join(controller,'simulator-control-policy.json'));
        Object.assign(inventory.files.find(file=>file.file_id==='policy'),{size_bytes:String(policy.bytes.length),digest:fileHash(policy.bytes)});
        payload.set('capability',{path:'capability.json',role:'schema',bytes:template});
        inventory.files.unshift({file_id:'capability',path:'capability.json',role:'schema',size_bytes:String(template.length),digest:fileHash(template),executable:false});
        manifest.capability_template_file_ids=['capability'];
        manifest.roles=[{role_id:'device',kind:'device',minimum:1,maximum:1,purpose:'设备绑定'}];
        manifest.permission_templates=[{request_id:'device.request',kind:'device_scope',purpose:'请求设备动作',
          scope:{device_role:'device',action_ids:capability.actions.map(action=>action.action_id),trigger_ids:[]}}];
      }});
    const {host_installation_id,authority_service_id,database_instance_id}=store.identity;
    const {receipt,intake_ref}=sealed.sealed,{manifest,inventory}=sealed.artifact;
    materialization={identity:{host_installation_id,authority_service_id,database_instance_id},
      content:{format:'leafseamer-intake-content/1',intake_ref,receipt,manifest,inventory}};
    runtime={directory,channelDirectory,uid:65533,gid:65533,entry:path.join(controller,'device-worker-entry.mjs'),assertCurrent(){},
      acquire:(...args)=>store.acquireLinuxWorkerMaterialization(...args)};
  }
  if(authorization){
    const group=fs.lstatSync(worker,{bigint:true}),boot_id=fs.readFileSync('/proc/sys/kernel/random/boot_id','utf8').trim();
    const group_path=worker.slice('/sys/fs/cgroup'.length);
    const containment={backend:'linux_cgroup_v2',generation,group_id:'group_'+digest({boot_id,group_path,
      group:{device:String(group.dev),inode:String(group.ino)}}).slice(7)};
    const config=path.join(scratch,'input.json');fs.writeFileSync(config,canonical({policy,data,result,containment,launchId:workerId,materialization,
      ...(channelDirectory&&{channelDirectory})}),{mode:0o644});
    args.push(path.resolve(controller,'../test/fixtures/linux-worker-authorization.mjs'),config);
  }else args.push(path.join(controller,'cli.mjs'),'contained-core-linux','--data-dir',data,'--port',String(port),
    '--bootstrap-policy',canonical(policy),'--worker-control','inherited');
  const issued=await journal.admit({role,driver:'cgroupfs',generation_id:generation,launch_id:launchId,service_id:identity.service_id,
    database_instance_id:identity.database_instance_id,uid:65534,gid:65534,image_path:node,image_sha256:'sha256:'+nodeDigest,args},
  {policy,source,workerControl:true,workerRuntime:runtime});
  assert.equal(issued.record.phase,'executed_closed');
  return {close,core,worker,result,port,runtime,coreReceipt:issued.record.detail.admission.receipt,
    business:path.join(data,'controller.sqlite'),control:path.join(installation,'linux-worker-control-'+launchId+'.db')};
}

function inspect(file,operation){
  const db=new DatabaseSync(file,{readOnly:true});try{return operation(db);}finally{db.close();}
}

test('Linux Controller 实际入口持续交换核心确认，断开监督后退出并保留同域 fence',options,async t=>{
  const running=await start(t),url='http://127.0.0.1:'+running.port+'/health/ready';
  const response=await until(async()=>{try{return await fetch(url,{signal:AbortSignal.timeout(250)});}catch{return null;}});
  assert.equal(response.status,503);await response.text();
  // 超过首条确认的期限，后续请求仍经定时续采的活连接服务。
  await delay(2300);
  assert.equal((await fetch(url)).status,503);
  running.close();await until(()=>empty(running.core));
  await assert.rejects(fetch(url,{signal:AbortSignal.timeout(500)}));
  const ack=inspect(running.business,db=>db.prepare('SELECT revision,body_jcs FROM worker_fence_ack').get());
  const persisted=inspect(running.control,db=>({
    fence:db.prepare('SELECT revision,digest FROM fence').get(),identity:JSON.parse(db.prepare('SELECT body FROM identity').get().body)}));
  assert.equal(ack.revision,persisted.fence.revision);
  assert.equal(JSON.parse(ack.body_jcs).snapshot_digest,persisted.fence.digest);
  assert.deepEqual(persisted.identity.core_receipt,running.coreReceipt);
});

test('Linux CREATE 单次启动受监督 Worker，模块与执行通道闭环并在撤销后退役',options,async t=>{
  const running=await start(t,{authorization:true,create:true});
  const result=await until(()=>fs.existsSync(running.result)?JSON.parse(fs.readFileSync(running.result,'utf8')):null);
  assert.equal(result.ok,true,result.error);assert(result.workerReceipt);await until(()=>empty(running.core));
  assert(empty(running.worker));assert.deepEqual(fs.readdirSync(running.runtime.directory),[]);
  assert.deepEqual(fs.readdirSync(running.runtime.channelDirectory),[]);
  const proof=inspect(running.control,db=>({
    attempts:db.prepare('SELECT count(*) AS total FROM attempt').get().total,
    admission:JSON.parse(db.prepare('SELECT body FROM admission').get().body),
    retirement:JSON.parse(db.prepare('SELECT body FROM retirement').get().body)}));
  assert.equal(proof.attempts,1);assert.deepEqual(proof.admission,result.workerReceipt);
  assert.equal(proof.retirement.result,'confirmed_empty');
  assert.deepEqual(proof.retirement.containment_ref,proof.admission.containment_ref);
  inspect(running.business,db=>{
    const originals=db.prepare('SELECT body_jcs FROM worker_runtime_binding').all();
    assert.equal(originals.length,1);assert.deepEqual(JSON.parse(originals[0].body_jcs).admission_receipt,proof.admission);
    assert.equal(db.prepare('SELECT count(*) AS total FROM worker_runtime_commit').get().total,1);
    assert.equal(db.prepare('SELECT count(*) AS total FROM worker_runtime_withdrawal').get().total,1);
    assert.equal(db.prepare('SELECT count(*) AS total FROM device_baseline_sample').get().total,1);
    assert.equal(db.prepare('SELECT count(*) AS total FROM execution_handshake').get().total,1);
    assert.equal(db.prepare('SELECT count(*) AS total FROM execution_session_end').get().total,1);
    assert.equal(db.prepare('SELECT count(*) AS total FROM device_event_source').get().total,1);
  });
});

test('Linux 业务启动授权穿过实际监督通道登记并持久撤销',options,async t=>{
  const running=await start(t,{authorization:true});
  const result=await until(()=>fs.existsSync(running.result)?JSON.parse(fs.readFileSync(running.result,'utf8')):null);
  assert.equal(result.ok,true,result.error);await until(()=>empty(running.core));
  assert.equal(result.coreReceipt,running.coreReceipt.receipt_id);assert(empty(running.worker));
  const facts=inspect(running.control,db=>({
    stored:db.prepare('SELECT intent_digest FROM registration WHERE launch_id=?').get(result.key.launch_id),
    denied:db.prepare('SELECT revision FROM denied WHERE launch_id=?').get(result.key.launch_id),
    fence:db.prepare('SELECT revision,body,digest FROM fence ORDER BY revision DESC LIMIT 1').get()}));
  assert.equal(facts.stored.intent_digest,result.key.launch_intent_digest);
  assert.equal(facts.denied.revision,Number(result.deniedRevision));assert.equal(facts.fence.revision,facts.denied.revision);
  assert.deepEqual(JSON.parse(facts.fence.body).items,[{...result.key,disposition:'deny'}]);
  inspect(running.business,db=>{
    assert.equal(db.prepare('SELECT count(*) AS total FROM worker_launch_authorization').get().total,3);
    assert.equal(db.prepare('SELECT count(*) AS total FROM worker_runtime_binding').get().total,0);
    assert.equal(db.prepare('SELECT count(*) AS total FROM worker_launch_denial').get().total,1);
    const ack=JSON.parse(db.prepare('SELECT body_jcs FROM worker_fence_ack WHERE revision=?').get(facts.fence.revision).body_jcs);
    assert.equal(ack.snapshot_digest,facts.fence.digest);
  });
});
