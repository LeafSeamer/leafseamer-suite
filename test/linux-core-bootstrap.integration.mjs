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
import {canonical} from '../dist/import-input.mjs';

const controller=process.env.LEAFSEAMER_CONTROLLER_BOOTSTRAP_DIST;
const seamer=process.env.LEAFSEAMER_SEAMER_BOOTSTRAP_DIST;
const enabled=process.platform==='linux'&&process.env.LEAFSEAMER_TEST_NATIVE_CGROUP==='1'&&Boolean(controller);
const id=()=>crypto.randomUUID();
const sum=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');

test('实际 Linux 核心经专用通道持久双向准入，错库无回执，断开即关闭',{
  skip:!enabled,timeout:65000
},async t=>{
  assert.equal(process.getuid(),0);
  const {openNativeClock}=await import(pathToFileURL(path.join(controller,'native-clock.mjs')));
  const source=openNativeClock(),scratch=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-core-admission-'));
  const image=path.join(scratch,'node'),directories=[];
  fs.chmodSync(scratch,0o755);
  fs.copyFileSync(process.execPath,image);
  fs.chmodSync(image,0o755);
  const nodeDigest=sum(fs.readFileSync(image));
  const cores=[['controller',controller],...(seamer?[['seamer',seamer]]:[])];
  let store,journal;
  async function empty(group){
    for(let index=0;index<80;index++){
      if(/^populated 0$/m.test(fs.readFileSync(group+'/cgroup.events','utf8')))return;
      await delay(25);
    }
    assert.fail('member not retired');
  }
  t.after(async()=>{
    journal?.close();
    store?.close();
    for(const directory of directories.filter(group=>group.endsWith('/core'))){
      fs.writeFileSync(directory+'/cgroup.kill','1');await empty(directory);
    }
    for(const directory of directories.reverse())fs.rmdirSync(directory);
    assert.equal(path.dirname(scratch),os.tmpdir());
    fs.rmSync(scratch,{recursive:true,force:true});
  });
  async function target(role,distribution,label,{wrongDatabase=false,sharedInstallation=null,generation_id=id(),
    targetRevision=role==='controller'?11:'20'}={}){
    const {initializeStorage,migrateStorage}=await import(pathToFileURL(path.join(distribution,'storage.mjs')));
    const root=path.join(scratch,label),data=path.join(root,role);
    const installation=sharedInstallation??path.join(root,'installation');
    fs.mkdirSync(root,{mode:0o755});fs.mkdirSync(data,{mode:0o700});
    const identity=initializeStorage(data);
    await migrateStorage(data,targetRevision);
    for(const entry of fs.readdirSync(data))fs.chownSync(path.join(data,entry),65534,65534);
    fs.chownSync(data,65534,65534);
    const listener=net.createServer().listen(0,'127.0.0.1');
    await once(listener,'listening');
    const {port}=listener.address();
    await new Promise(resolve=>listener.close(resolve));
    const buildDigest=sum(fs.readFileSync(path.join(distribution,'build-manifest.json')));
    const artifact={manifest_id:role+'.test',revision:'1',
      digest:'sha256:'+sum(canonical({[role+'_build_sha256']:buildDigest,node_sha256:nodeDigest}))};
    const policy={format:'leafseamer-core-bootstrap-policy/1',service_id:identity.service_id,
      database_instance_id:wrongDatabase?id():identity.database_instance_id,artifact_manifest_ref:artifact,
      platform_profile_ref:{profile_id:'linux-native-'+role+'-test',revision:'1'},
      bootstrap_timeout_ms:5000,clock_backend_revision:'1',policy_revision:'1'};
    const {groupPath}=linuxContainerCgroup({role,driver:'cgroupfs',generationId:generation_id});
    const parent='/sys/fs/cgroup'+groupPath,group=parent+'/core';
    for(const directory of [parent,group]){fs.mkdirSync(directory);directories.push(directory);}
    const intent={role,driver:'cgroupfs',launch_id:id(),generation_id,
      service_id:policy.service_id,database_instance_id:policy.database_instance_id,uid:65534,gid:65534,image_path:image,
      image_sha256:'sha256:'+nodeDigest,args:['--disallow-code-generation-from-strings',path.join(distribution,'cli.mjs'),
        'contained-core-linux','--data-dir',data,'--port',String(port),'--bootstrap-policy',canonical(policy)]};
    if(sharedInstallation===null){
      fs.mkdirSync(installation,{mode:0o700});
      createInstallationStore(installation);
      store=openInstallationStore(installation);
      store.initializeLinuxMemberJournal();
      journal=store.openLinuxMemberJournal(record=>{
        if(record.detail.admission)assert.equal(journal.lookup(record.intent.launch_id).phase,'release_requested');
        return true;
      });
    }
    return {intent,policy,group,data,installation,port};
  }
  for(const [role,distribution] of cores){
    const wrong=await target(role,distribution,role+'-wrong-database',{wrongDatabase:true});
    await assert.rejects(journal.admit(wrong.intent,{policy:wrong.policy,source}),{code:'linux_bootstrap_channel'});
    assert.equal(journal.lookup(wrong.intent.launch_id).phase,'release_requested');
    await empty(wrong.group);
    journal.close();store.close();journal=store=null;
  }
  if(seamer){
    const old=await target('seamer',seamer,'seamer-old-schema',{targetRevision:'19'});
    await assert.rejects(journal.admit(old.intent,{policy:old.policy,source}),{code:'linux_bootstrap_channel'});
    assert.equal(journal.lookup(old.intent.launch_id).phase,'release_requested');
    await empty(old.group);
    const detail=new DatabaseSync(path.join(old.data,'seamer.sqlite'),{readOnly:true});
    try{
      assert.equal(detail.prepare('PRAGMA user_version').get().user_version,19);
      assert.equal(detail.prepare("SELECT count(*) AS total FROM sqlite_schema WHERE name='core_runtime_binding'").get().total,0);
    }finally{detail.close();}
    journal.close();store.close();journal=store=null;
  }
  const accepted=[];
  for(const [role,distribution] of cores){
    const existing=accepted[0]?.actual;
    const actual=await target(role,distribution,role+'-accepted',{sharedInstallation:existing?.installation??null,
      generation_id:existing?.intent.generation_id});
    const {record,bootstrap}=await journal.admit(actual.intent,{policy:actual.policy,source});
    assert.equal(bootstrap,null);
    assert.equal(record.phase,'executed_closed');
    const {receipt,descriptor}=record.detail.admission;
    assert.equal(receipt.gate_state,'closed');
    assert.equal(receipt.containment_ref.backend,'linux_cgroup_v2');
    assert.equal(descriptor.clock_backend_id,'linux_boottime');
    assert.equal(descriptor.os_boot_identity.value,record.detail.host.boot_id);
    assert.deepEqual(await journal.admit(actual.intent,{policy:actual.policy,source}),{record,bootstrap:null});
    const url='http://127.0.0.1:'+actual.port+'/health/ready';
    let response;
    for(let index=0;index<100&&!response;index++){
      try{response=await fetch(url,{signal:AbortSignal.timeout(250)});}
      catch{await delay(25);}
    }
    assert.equal(response?.status,503);
    await response.json();
    accepted.push({role,actual,record,receipt,url});
  }
  for(const {url} of accepted){
    const response=await fetch(url,{signal:AbortSignal.timeout(1000)});
    assert.equal(response.status,503);
    await response.json();
  }
  journal.close();store.close();journal=store=null;
  for(const {role,actual,receipt,url} of accepted){
    await empty(actual.group);
    await assert.rejects(fetch(url,{signal:AbortSignal.timeout(500)}));
    const detail=new DatabaseSync(path.join(actual.data,role+'.sqlite'),{readOnly:true});
    try{
      const saved=detail.prepare('SELECT receipt_jcs FROM core_runtime_binding').get();
      assert.equal(saved?.receipt_jcs,canonical(receipt));
      assert.equal(detail.prepare('SELECT count(*) AS total FROM core_runtime_binding').get().total,1);
    }finally{detail.close();}
  }
  store=openInstallationStore(accepted[0].actual.installation);
  journal=store.openLinuxMemberJournal(()=>false);
  for(const {actual,record} of accepted){
    assert.deepEqual(await journal.admit(actual.intent,{policy:actual.policy,source}),{record,bootstrap:null});
  }
});
