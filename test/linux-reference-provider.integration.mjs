import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createInterface} from 'node:readline';
import test from 'node:test';
import {canonical,digest} from '../dist/import-input.mjs';
import {startLinuxReferenceProvider} from '../dist/linux-member-journal.mjs';

const executable=process.env.LEAFSEAMER_TEST_REFERENCE_PROVIDER;
const enabled=process.platform==='linux'&&process.env.LEAFSEAMER_TEST_NATIVE_CGROUP==='1'&&!!executable;

test('Linux 原生宿主先纳管再启动授时提供者，交付独占采集连接并证明退役',{
  skip:!enabled,timeout:25000
},async t=>{
  assert.equal(process.geteuid(),0);
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-reference-provider-'));
  const filename=path.join(directory,'provider');
  const groupPath='/leafseamer_reference_'+crypto.randomUUID().replaceAll('-','');
  const group='/sys/fs/cgroup'+groupPath;
  fs.mkdirSync(group);
  let running;
  t.after(async()=>{
    try{await running?.retire();}
    finally{fs.rmdirSync(group);fs.unlinkSync(filename);fs.rmdirSync(directory);}
  });
  fs.chmodSync(directory,0o755);fs.copyFileSync(executable,filename);fs.chmodSync(filename,0o555);
  const uid=65534,gid=65534,bootId=fs.readFileSync('/proc/sys/kernel/random/boot_id','utf8').trim();
  const ns=fs.statSync('/proc/self/ns/time',{bigint:true});
  const continuity='linux:'+ns.dev+':'+ns.ino;
  const nsIdentity='linux_'+ns.dev+'_'+ns.ino;
  const runtime={descriptor_version:'clock-domain/1',domain_kind:'supervised_runtime',authority_service_id:crypto.randomUUID(),
    runtime_generation:crypto.randomUUID(),supervisor_instance_id:crypto.randomUUID(),clock_backend_id:'linux_boottime',
    clock_backend_revision:'1',tick_unit:'ns',suspend_accounting:'included',namespace_identity:nsIdentity,
    os_boot_identity:{status:'verified',source:'linux-proc-boot-id',value:bootId,evidence_ref:bootId},
    platform_profile_id:'linux-test-profile',platform_profile_revision:'1'};
  const checksum=digest(runtime),domain={clock_domain_id:'clock_'+checksum.slice(7),descriptor_digest:checksum};
  const descriptor={...runtime,...domain};
  const receipt={role:'core',gate_state:'closed',domain_ref:domain,receipt_id:crypto.randomUUID()};
  const policy={policy_revision:'1',bootstrap_timeout_ms:3000,service_id:runtime.authority_service_id,database_instance_id:crypto.randomUUID()};
  const core={descriptor,receipt,policy};
  const imageDigest='sha256:'+crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
  const provider={artifact_manifest_ref:{manifest_id:'reference-provider',revision:'1',digest:imageDigest},image_path:filename,uid,gid};
  const source={capture:()=>({continuity}),tick(){
    const [seconds,hundredths]=fs.readFileSync('/proc/uptime','utf8').split(' ')[0].split('.');
    return BigInt(seconds)*1000000000n+BigInt(hundredths)*10000000n;
  }};
  let active=true,committed;
  const inputs={core,provider,groupPath,source,assertLive(){assert.equal(active,true);},commit(value){
    assert.equal(committed,undefined);committed=structuredClone(value);
    assert.match(fs.readFileSync(group+'/cgroup.events','utf8'),/^populated 1$/m);
    assert.match(fs.readFileSync('/proc/'+value.process_observation.provider_pid+'/status','utf8'),/^Uid:\s+65534\s+65534\s+65534\s+65534$/m);
  }};
  const counts=()=>fs.readFileSync(group+'/cgroup.events','utf8');
  await assert.rejects(startLinuxReferenceProvider({...inputs,provider:{...provider,artifact_manifest_ref:{...provider.artifact_manifest_ref,
    digest:'sha256:'+'0'.repeat(64)}}}),{code:'linux_member_artifact_digest'});
  assert.match(counts(),/^populated 0$/m);

  running=await startLinuxReferenceProvider(inputs);
  assert.deepEqual(running.admission,committed);
  assert.equal(committed.receipt.role,'time_provider');
  assert.equal(committed.receipt.gate_state,'closed');
  assert.deepEqual(committed.receipt.domain_ref,domain);
  const body={format:'leafseamer-time-provider-runtime-binding/2',service_id:runtime.authority_service_id,
    database_instance_id:policy.database_instance_id,service_boot_id:crypto.randomUUID(),core_receipt_id:receipt.receipt_id,
    launch_intent:committed.intent,clock_domain_descriptor:committed.descriptor,admission_receipt:committed.receipt,
    process_observation:committed.process_observation,gate_state:'closed'};
  const binding={...body,runtime_binding_id:'time-runtime.'+digest(body).slice(7)},bindingDigest=digest(binding);
  const requestId=crypto.randomUUID(),socket=running.collector,reader=createInterface({input:socket})[Symbol.asyncIterator]();
  const write=message=>socket.write(canonical(message)+'\n');
  write({type:'BIND',version:'time-provider-link/1',request_id:requestId,binding_digest:bindingDigest,binding});
  const request=JSON.parse((await reader.next()).value);
  assert.equal(request.type,'AUTH_READ');assert.equal(request.binding_digest,bindingDigest);
  write({type:'AUTH_RESULT',version:'time-provider-auth/1',reply_to:request.request_id,binding_digest:bindingDigest,sample:null});
  assert.deepEqual(JSON.parse((await reader.next()).value),{type:'BOUND',version:'time-provider-link/1',reply_to:requestId,binding_digest:bindingDigest});
  active=false;
  assert.throws(running.assertCurrent);
  await running.retire();
  assert.match(counts(),/^populated 0$/m);
  assert.equal(fs.existsSync('/proc/'+committed.process_observation.provider_pid),false);

  active=true;committed=undefined;
  await assert.rejects(startLinuxReferenceProvider({...inputs,commit(){throw new Error('fixture commit refused');}}),/fixture commit refused/);
  assert.match(counts(),/^populated 0$/m);
});
