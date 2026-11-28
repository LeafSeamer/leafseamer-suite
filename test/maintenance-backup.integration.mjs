import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import {mkdirSync,rmdirSync,writeFileSync} from 'node:fs';
import os from 'node:os';
import net from 'node:net';
import path from 'node:path';
import {execFile,execFileSync,spawn} from 'node:child_process';
import {once} from 'node:events';
import {setTimeout as delay} from 'node:timers/promises';
import {DatabaseSync} from 'node:sqlite';
import {promisify} from 'node:util';
import {fileURLToPath,pathToFileURL} from 'node:url';
import test from 'node:test';
import {createInstallationStore,openInstallationStore} from '@leafseamer/suite/installation';
import {canonical,digest} from '../dist/import-input.mjs';
import {linuxContainerCgroup} from '../dist/linux-cgroup-retirement.mjs';

const exec = promisify(execFile);
const generation = '7';
const authorize = () => ({allowed:true,generation});
const cryptoTool = fileURLToPath(new URL('../dist/native/leafseamer_backup_crypto'+(process.platform==='win32'?'.exe':''),import.meta.url));

async function fixture(t) {
  const base = await fs.mkdtemp(path.join(os.tmpdir(),'leafseamer-backup-ledger-'));
  const root = path.join(base,'installation'), source = path.join(base,'source');
  await fs.mkdir(root);
  await fs.mkdir(source);
  const identity = createInstallationStore(root);
  let store = openInstallationStore(root);
  const scope = {authority:'controller',service_id:crypto.randomUUID(),database_instance_id:crypto.randomUUID(),
    request_epoch:crypto.randomUUID(),control_epoch:crypto.randomUUID(),schema_revision:'113'};
  const db = new DatabaseSync(path.join(source,'controller.sqlite'));
  db.exec(`PRAGMA journal_mode=WAL;
    PRAGMA application_id=1280525132;
    PRAGMA user_version=113;
    CREATE TABLE service_state(singleton INTEGER PRIMARY KEY,authority TEXT,service_id TEXT,database_instance_id TEXT,
      request_epoch TEXT,schema_revision TEXT,control_epoch TEXT) STRICT;
    CREATE TABLE fixture(value TEXT);
    INSERT INTO fixture VALUES('source receipt');`);
  db.prepare('INSERT INTO service_state VALUES(1,?,?,?,?,?,?)').run(scope.authority,scope.service_id,scope.database_instance_id,
    scope.request_epoch,scope.schema_revision,scope.control_epoch);
  t.after(async()=>{
    db.close();
    store.close();
    assert.equal(path.dirname(path.resolve(base)),path.resolve(os.tmpdir()));
    await fs.rm(base,{recursive:true,force:true,maxRetries:5,retryDelay:50});
  });
  const key = (name,origin='local_os') => ({installation_id:identity.host_installation_id,
    installation_epoch:identity.installation_epoch,origin,operation:'requestMaintenanceOperation',
    idempotency_key:name,request_epoch:'request.fixture',
    ...(origin==='human' ? {principal_id:'person.fixture',issuer_id:'issuer.fixture',issuer_epoch:'epoch.fixture'} : {os_subject:'uid:777'})});
  const plan = overrides => ({kind:'backup',deployment_plan_ref:'deployment.fixture',expected_generation:generation,
    target_service_scopes:[scope],backup_level:'L2',consistency:'online',encryption_profile_ref:'age.fixture',
    resource_profile_ref:'budget.fixture',coverage_digest:digest('coverage.fixture'),...overrides});
  const request = (ledger,name,options={},origin) => {
    const plan_ref = ledger.createPlan(plan(options),authorize), request_key = key(name,origin);
    const input = {plan_ref,request_key,expected_generation:generation};
    return {input,operation:ledger.request(input,authorize)};
  };
  return {root,source,identity,scope,key,plan,request,get store(){return store;},
    close(){store.close();},reopen(){store.close();store=openInstallationStore(root);return store;}};
}

test('explicitly adds backup ledger while preserving installed identity, marker and existing rows', async t=>{
  const f = await fixture(t);
  const file = path.join(f.root,'installation.db');
  const marker = await fs.readFile(path.join(f.root,'installation.marker'));
  assert.throws(()=>f.store.backupMaintenance(),{code:'backup_maintenance_migration_required'});
  f.close();
  const writable = new DatabaseSync(file);
  writable.prepare('INSERT INTO installation_client_registration VALUES(?,?,?)')
    .run('client.fixture',Buffer.from('fixture'),digest('client.fixture'));
  writable.close();
  f.reopen();
  assert.throws(()=>f.store.backupMaintenance(),{code:'backup_maintenance_migration_required'});
  assert.equal(f.store.enableBackupMaintenance(),f.store.enableBackupMaintenance());
  assert.deepEqual(f.reopen().identity,f.identity);
  assert.deepEqual(await fs.readFile(path.join(f.root,'installation.marker')),marker);
  f.close();
  const inspection = new DatabaseSync(file,{readOnly:true});
  assert.equal(inspection.prepare('PRAGMA user_version').get().user_version,2);
  assert.equal(inspection.prepare('SELECT count(*) AS count FROM installation_client_registration').get().count,1);
  inspection.close();
});

test('deduplicates immutable requests and requires scoped local approval before maintenance', async t=>{
  const f = await fixture(t), ledger = f.store.enableBackupMaintenance();
  const initial = f.request(ledger,'maintenance',{consistency:'maintenance'},'human');
  assert.equal(initial.operation.phase,'awaiting_local_approval');
  assert.deepEqual(ledger.request(initial.input,authorize),initial.operation);
  assert.throws(()=>ledger.request({...initial.input,plan_ref:ledger.createPlan(f.plan(),authorize)},authorize),{code:'backup_request_conflict'});
  await assert.rejects(ledger.collectSnapshots(initial.operation.operation_id,1,{authorize,sourceDirectory:()=>f.source}),
    {code:'backup_operation_phase'});
  const approval = {approval_ref:'approval.fixture',os_subject:'uid:777',plan_digest:initial.input.plan_ref.digest,
    expected_generation:generation};
  assert.throws(()=>ledger.approve(initial.operation.operation_id,1,approval,()=>({allowed:false,generation})),{code:'backup_not_authorized'});
  assert.throws(()=>ledger.approve(initial.operation.operation_id,1,{...approval,expected_generation:'8'},authorize),{code:'backup_approval_invalid'});
  const queued = ledger.approve(initial.operation.operation_id,1,approval,authorize);
  assert.equal(queued.local_approval_ref,approval.approval_ref);
  assert.equal(queued.phase,'queued');
  assert.throws(()=>ledger.cancel(queued.operation_id,1,authorize),{code:'backup_operation_revision'});
  const cancelled = ledger.cancel(queued.operation_id,queued.revision,authorize);
  assert.equal(cancelled.phase,'cancelled');
  const reopened = f.reopen().backupMaintenance();
  assert.deepEqual(reopened.lookup(initial.input.request_key),cancelled);
  assert.deepEqual(reopened.request(initial.input,authorize),cancelled);
});

test('records a real SQLite snapshot and returns its original receipt after reopen', async t=>{
  const f = await fixture(t), ledger = f.store.enableBackupMaintenance();
  const {input,operation} = f.request(ledger,'snapshot');
  const result = await ledger.collectSnapshots(operation.operation_id,operation.revision,{authorize,sourceDirectory:()=>f.source});
  assert.equal(result.phase,'running');
  assert.equal(result.step,'snapshots_staged');
  const staged = ledger.snapshots(operation.operation_id);
  assert.equal(staged.length,1);
  const [{receipt,backup_operation_id:id}] = staged;
  assert.equal(receipt.backup_operation_id,id);
  assert.equal(receipt.state,'staged');
  const file = path.join(f.root,'staging','backup-'+operation.operation_id,id,'snapshot.partial','data.sqlite');
  const content = await fs.readFile(file);
  assert.equal(receipt.bytes,content.length);
  assert.equal(receipt.sha256,crypto.createHash('sha256').update(content).digest('hex'));
  const db = new DatabaseSync(file,{readOnly:true});
  assert.equal(db.prepare('SELECT value FROM fixture').get().value,'source receipt');
  db.close();
  const reopened = f.reopen().backupMaintenance();
  assert.deepEqual(reopened.lookup(input.request_key),result);
  assert.deepEqual(reopened.snapshots(operation.operation_id),staged);
  await assert.rejects(reopened.collectSnapshots(operation.operation_id,result.revision,{authorize,sourceDirectory:()=>f.source}),
    {code:'backup_operation_phase'});
});

test('defers cancellation to a safe snapshot boundary and checks generation again on adoption', async t=>{
  const f = await fixture(t), ledger = f.store.enableBackupMaintenance();
  const first = f.request(ledger,'cancel');
  const pending = ledger.collectSnapshots(first.operation.operation_id,1,{authorize,sourceDirectory:()=>f.source});
  const running = ledger.get(first.operation.operation_id);
  assert.equal(running.step,'snapshotting');
  assert.throws(()=>f.store.close(),{code:'backup_helper_in_use'});
  assert.equal(ledger.cancel(running.operation_id,running.revision,authorize).cancel_requested,true);
  assert.equal((await pending).phase,'cancelled');
  assert.equal(ledger.snapshots(running.operation_id)[0].receipt,null);

  const second = f.request(ledger,'generation');
  const failed = await ledger.collectSnapshots(second.operation.operation_id,1,{
    authorize:({action})=>({allowed:true,generation:action==='adopt_snapshot' ? '8' : generation}),
    sourceDirectory:()=>f.source
  });
  assert.equal(failed.phase,'failed');
  assert.equal(failed.reason_code,'backup_generation_conflict');
  assert.equal(ledger.snapshots(second.operation.operation_id)[0].receipt,null);
});

test('missing second target retains the first snapshot without sealing the set', async t=>{
  const f = await fixture(t), ledger = f.store.enableBackupMaintenance();
  const missing = {...f.scope,database_instance_id:crypto.randomUUID()};
  const {operation} = f.request(ledger,'partial',{target_service_scopes:[f.scope,missing]});
  const result = await ledger.collectSnapshots(operation.operation_id,1,{authorize,sourceDirectory:()=>f.source});
  assert.equal(result.step,'stopped');
  assert.equal(result.phase,'failed');
  const [first,second] = f.reopen().backupMaintenance().snapshots(operation.operation_id);
  assert.equal(first.receipt.state,'staged');
  assert.equal(second.receipt,null);
});

test('process interruption keeps the original operation indeterminate and prevents another copy', async t=>{
  const f = await fixture(t), ledger = f.store.enableBackupMaintenance();
  const first = f.request(ledger,'interrupted'), second = f.request(ledger,'next');
  f.close();
  const child = `
    import {openInstallationStore} from '@leafseamer/suite/installation';
    const store=openInstallationStore(process.argv[1]);
    await store.backupMaintenance().collectSnapshots(process.argv[2],1,{
      authorize:()=>({allowed:true,generation:'7'}),
      sourceDirectory(){process.exit(73);}
    });
  `;
  await assert.rejects(exec(process.execPath,['--disallow-code-generation-from-strings','--input-type=module','--eval',child,f.root,first.operation.operation_id],
    {cwd:new URL('../',import.meta.url),windowsHide:true}),{code:73});
  const reopened = f.reopen().backupMaintenance();
  const recovered = reopened.lookup(first.input.request_key);
  assert.equal(recovered.phase,'indeterminate');
  assert.equal(recovered.reason_code,'backup_helper_unconfirmed');
  assert.equal(recovered.revision,3);
  assert.deepEqual(reopened.request(first.input,authorize),recovered);
  await assert.rejects(reopened.collectSnapshots(second.operation.operation_id,1,{authorize,sourceDirectory:()=>f.source}),
    {code:'backup_helper_in_use'});
  assert.deepEqual(f.reopen().backupMaintenance().lookup(first.input.request_key),recovered);
});

async function publicationFixture(f,ledger,name,coverage=[]){
  const {operation,input}=f.request(ledger,name,{coverage_digest:digest(coverage),
    backup_level:'L1',target_service_scopes:[]});
  const ready=await ledger.collectSnapshots(operation.operation_id,1,{authorize,sourceDirectory:()=>f.source});
  assert.equal(ready.step,'snapshots_staged');
  const stage=path.join(f.root,'staging','backup-'+ready.operation_id);
  const directory=path.join(stage,'archive'),report='reports/fixture.json';
  await fs.mkdir(path.join(directory,'files','reports'),{recursive:true,mode:0o700});
  const verified=Buffer.from('{"fixture":"structural checks passed"}');
  await fs.writeFile(path.join(directory,'files',report),verified,{mode:0o600});
  const reportHash=crypto.createHash('sha256').update(verified).digest('hex');
  const manifest={format:'leafseamer-backup-tar/1',backup_id:ready.operation_id,level:'L1',consistency:'online',
    files:[{role:'validation_report',path:report,size:verified.length,sha256:reportHash}],
    databases:[],
    coverage,unresolved:[],validation_reports:[report]};
  const raw=Buffer.from(JSON.stringify(manifest));
  await fs.writeFile(path.join(directory,'manifest.json'),raw,{mode:0o600});
  await exec(cryptoTool,['pack','--directory',directory],{windowsHide:true});
  return {operation:ready,input,directory,manifestHash:crypto.createHash('sha256').update(raw).digest('hex'),
    options:{verification_ref:digest(reportHash),mode:'passphrase',passphrase:Buffer.from('synthetic publication secret')}};
}

function publisher(fixture){
  return ({archive})=>({allowed:true,generation,verified:archive?.verification_ref===fixture.options.verification_ref&&
    archive?.manifest_sha256===fixture.manifestHash&&archive.encryption_profile_ref==='age.fixture'&&archive.encryption.mode==='passphrase'});
}

test('publishes a verified archive atomically and preserves its original across failed candidates and reopen',{timeout:30000},async t=>{
  const f=await fixture(t),old=f.store.enableBackupMaintenance();
  const prepared=await publicationFixture(f,old,'archive');
  const {operation,input,options}=prepared;
  await assert.rejects(old.publishArchive(operation.operation_id,operation.revision,options,publisher(prepared)),
    {code:'backup_publication_migration_required'});
  const ledger=f.store.enableBackupPublication();
  assert.deepEqual(ledger.lookup(input.request_key),operation);
  await assert.rejects(ledger.publishArchive(operation.operation_id,operation.revision,options,authorize),
    {code:'backup_archive_verification'});
  const result=await ledger.publishArchive(operation.operation_id,operation.revision,options,publisher(prepared));
  assert.equal(result.phase,'succeeded');
  assert.equal(result.step,'published');
  const archive=result.archive;
  assert.deepEqual(ledger.getArchive(operation.operation_id),archive);
  const published=path.join(f.root,'content',archive.archive_id,'archive.age');
  const encrypted=await fs.readFile(published);
  assert.equal(archive.ciphertext_bytes,encrypted.length);
  assert.equal(archive.ciphertext_sha256,crypto.createHash('sha256').update(encrypted).digest('hex'));
  const restore=path.join(prepared.directory,'restore');
  await fs.mkdir(restore);
  await fs.writeFile(path.join(restore,'ciphertext.age'),encrypted);
  execFileSync(cryptoTool,['open','--mode','passphrase','--directory',restore,'--expected-bytes',String(encrypted.length),
    '--expected-sha256',archive.ciphertext_sha256],{windowsHide:true,input:options.passphrase});
  const verified=await exec(cryptoTool,['verify','--directory',restore],{windowsHide:true});
  assert.equal(JSON.parse(verified.stdout).manifest_sha256,prepared.manifestHash);
  const reopened=f.reopen().backupMaintenance();
  assert.deepEqual(reopened.request(input,authorize),result);
  assert.deepEqual(reopened.getArchive(archive.archive_id),archive);
  assert.throws(()=>reopened.cancel(operation.operation_id,result.revision,authorize),{code:'backup_operation_phase'});

  const incomplete=await publicationFixture(f,reopened,'coverage',[{kind:'configuration',reference:'fixture.missing',state:'missing',path:''}]);
  await assert.rejects(reopened.publishArchive(incomplete.operation.operation_id,incomplete.operation.revision,incomplete.options,publisher(incomplete)),
    {code:'backup_archive_coverage'});
  assert.equal(reopened.getArchive(incomplete.operation.operation_id),null);
  const corrupt=await publicationFixture(f,reopened,'corrupt');
  const plaintext=path.join(corrupt.directory,'plaintext.tar');
  await fs.truncate(plaintext,(await fs.stat(plaintext)).size-512);
  const failed=await reopened.publishArchive(corrupt.operation.operation_id,corrupt.operation.revision,corrupt.options,publisher(corrupt));
  assert.equal(failed.phase,'failed');
  assert.equal(reopened.getArchive(corrupt.operation.operation_id),null);
  assert.deepEqual(await fs.readFile(published),encrypted);
  assert.deepEqual(reopened.getArchive(archive.archive_id),archive);
});

const distributionDirectories={
  controller:process.env.LEAFSEAMER_TEST_BACKUP_CONTROLLER_DIST,
  seamer:process.env.LEAFSEAMER_TEST_BACKUP_SEAMER_DIST
};

function writeDeploymentFixture(root,scopes){
  const roleNames=['controller','seamer'],generation_id=crypto.randomUUID(),driver='cgroupfs';
  const intent={generation_id,driver,compose_digest:digest('fixture compose'),
    ...Object.fromEntries(scopes.map(({authority,service_id,database_instance_id})=>[authority,{service_id,database_instance_id}]))};
  const host={boot_id:crypto.randomUUID(),root:{device:'3',inode:'1'}};
  const members=Object.fromEntries(roleNames.map((role,index)=>{
    const {groupPath}=linuxContainerCgroup({driver,generationId:generation_id,role});
    return [role,{driver,generation_id,role,host,group_path:groupPath,group:{device:'3',inode:String(index+2)},
      leader:{pid:100+index,start_ticks:'10',group_path:groupPath+'/core'}}];
  }));
  function event(revision,phase,detail){
    const db=new DatabaseSync(path.join(root,'linux-deployment.db'));
    try{
      const record={intent,revision,phase,detail};
      db.prepare('INSERT INTO linux_deployment_event(generation_id,revision,phase,body,digest) VALUES (?,?,?,?,?)')
        .run(generation_id,revision,phase,canonical(record),digest(record));
    }finally{db.close();}
  }
  event(1,'launching',{host,predecessor:null});
  event(2,'running',{members});
  event(3,'closing',{members});
  const endpoint_evidence_digest=digest('fixture closed endpoints');
  return {generation_id,endpoint_evidence_digest,finish(){
    event(4,'retired',{members,endpoint_evidence_digest});
  }};
}

async function liveDeploymentFixture(store,scopes){
  const generation_id=crypto.randomUUID(),driver='cgroupfs';
  const intent={generation_id,driver,compose_digest:digest('fixture live deployment'),
    ...Object.fromEntries(scopes.map(({authority,service_id,database_instance_id})=>[authority,{service_id,database_instance_id}]))};
  const children=[],groups=[],endpoint_evidence_digest=digest('fixture closed endpoints');
  const journal=store.openLinuxDeploymentJournal({
    launch(){
      return Object.fromEntries(['controller','seamer'].map(role=>{
        const {groupPath}=linuxContainerCgroup({driver,generationId:generation_id,role});
        const base='/sys/fs/cgroup'+groupPath,core=base+'/core';
        for(const directory of [base,core]){mkdirSync(directory);groups.push(directory);}
        const child=spawn('/bin/cat',{stdio:['pipe','ignore','inherit']});
        child.stdin.on('error',()=>{});
        children.push({child,exit:once(child,'close')});
        writeFileSync(core+'/cgroup.procs',String(child.pid));
        return [role,child.pid];
      }));
    },
    endpointClosure(){return endpoint_evidence_digest;}
  });
  async function stop(){
    for(const {child} of children)child.stdin.end();
    const timer=setTimeout(()=>{for(const {child} of children)if(child.exitCode===null)child.kill('SIGKILL');},2000);
    try{await Promise.all(children.map(({exit})=>exit));}finally{clearTimeout(timer);}
  }
  async function close(){
    try{await stop();}finally{
      journal.close();
      for(const group of groups.reverse())rmdirSync(group);
    }
  }
  try{
    assert.equal(journal.start(intent).phase,'running');
    assert.equal(journal.closeIntake(generation_id).phase,'closing');
    assert.equal(journal.observeRetirement(generation_id).phase,'closing');
    return {generation_id,endpoint_evidence_digest,close,async finish(){
      await stop();
      assert.equal(journal.observeRetirement(generation_id).phase,'retired');
    }};
  }catch(error){await close();throw error;}
}

async function nativeDeploymentFixture(store,scopes){
  const generation_id=crypto.randomUUID(),driver='cgroupfs';
  const image_path=process.env.LEAFSEAMER_TEST_NATIVE_MEMBER_FIXTURE;
  const image_sha256='sha256:'+crypto.createHash('sha256').update(await fs.readFile(image_path)).digest('hex');
  const journal=store.openLinuxMemberJournal(()=>true),started=[],directories=[];
  async function finish(launchId){
    journal.closeIntake(launchId);
    for(let attempt=0;attempt<100;attempt++){
      if(journal.observeRetirement(launchId).phase==='retired')return;
      await delay(20);
    }
    assert.fail('native test member did not retire');
  }
  async function close(){
    try{for(const launchId of started)await finish(launchId);}
    finally{
      journal.close();
      for(const directory of directories.reverse())rmdirSync(directory);
    }
  }
  try{
    for(const {authority:role,service_id,database_instance_id} of scopes){
      const {groupPath}=linuxContainerCgroup({driver,generationId:generation_id,role});
      const base='/sys/fs/cgroup'+groupPath,core=base+'/core';
      for(const directory of [base,core]){mkdirSync(directory);directories.push(directory);}
      const launch_id=crypto.randomUUID();
      const {record,bootstrap}=await journal.launch({generation_id,driver,role,service_id,database_instance_id,
        launch_id,uid:65534,gid:65534,image_path,image_sha256,args:[core+'/cgroup.procs',core+'/cgroup.procs']});
      started.push(launch_id);
      const [message]=await once(bootstrap,'data',{signal:AbortSignal.timeout(2000)});
      assert.equal(record.phase,'executed_closed');
      assert.equal(message.toString(),'application_entered\n');
    }
    return {generation_id,close,finishFirst:()=>finish(started[0]),async finish(){
      for(const launchId of started)await finish(launchId);
    }};
  }catch(error){await close();throw error;}
}

async function prepareNativeRecoveryFixture(f,target,review,distributions,plan){
  const planDirectory=path.join(f.root,'linux-native'),planFile=path.join(planDirectory,'recovery.json');
  await fs.chmod(path.dirname(f.root),0o711);
  await fs.mkdir(planDirectory,{mode:0o700});
  await fs.mkdir(plan.runtime_root,{mode:0o711});
  await fs.writeFile(planFile,canonical(plan),{mode:0o600});
  const image={file:process.execPath,sha256:'sha256:'+crypto.createHash('sha256').update(await fs.readFile(process.execPath)).digest('hex')};
  const listeners=review.plan.services.map(()=>net.createServer().listen(0,'127.0.0.1'));
  await Promise.all(listeners.map(listener=>once(listener,'listening')));
  const ports=listeners.map(listener=>listener.address().port);
  await Promise.all(listeners.map(listener=>new Promise(resolve=>listener.close(resolve))));
  const members=await Promise.all(review.plan.services.map(async ({next_scope},index)=>{
    const {authority:role,service_id,database_instance_id}=next_scope,distribution=distributions[role];
    const core={format:'leafseamer.linux-native-core/1',host_installation_id:f.identity.host_installation_id,
      role,driver:'cgroupfs',generation_id:target.generation_id,launch_id:crypto.randomUUID(),uid:65532+index,gid:65532+index,
      port:ports[index],image,distribution,clock_profile:null,pairing_profile:null,
      data_directory:path.join(plan.runtime_root,target.generation_id,'db-'+index),
      bootstrap:{format:'leafseamer-core-bootstrap-policy/1',service_id,database_instance_id,bootstrap_timeout_ms:12000,
        clock_backend_revision:'1',policy_revision:'1',platform_profile_ref:{profile_id:'fixture.recovery',revision:'1'},
        artifact_manifest_ref:{manifest_id:'fixture.release',revision:'1',digest:digest({
          [role+'_build_sha256']:distribution.manifest_sha256.slice(7),node_sha256:image.sha256.slice(7)})}}};
    const file=path.join(planDirectory,plan.configuration_refs[role]+'.json');
    await fs.writeFile(file,canonical(core),{mode:0o600});
    return {file,digest:digest(core),core};
  }));
  return {planFile,members};
}

async function checkNativeRecoveryStartup(f,{planFile,members},selected){
  const {openLinuxNativeHost}=await import('../dist/linux-native-host.mjs');
  const {openNativeClock}=await import(pathToFileURL(path.join(distributionDirectories.controller,'native-clock.mjs')));
  f.close();
  const openHost=()=>openLinuxNativeHost({installationDirectory:f.root,source:openNativeClock()});
  let host=openHost();
  const directories=[],start={planFile,selectionDigest:selected.selection_digest,
    authorize({selection,secret_bindings_digest,restart,retirement_digest}){return {allowed:true,selection_digest:selection.selection_digest,
      release_manifest_digest:selection.deployment.release_manifest_digest,secret_bindings_digest,
      ...(restart&&{runtime_generation_id:restart.runtimeGenerationId,retirement_digest})};}};
  const previousLaunchIds=Object.fromEntries(members.map(({core})=>[core.role,core.launch_id]));
  const restart={previousLaunchIds,runtimeGenerationId:crypto.randomUUID(),launchIds:{controller:crypto.randomUUID(),seamer:crypto.randomUUID()}};
  const allLaunches=[...Object.values(previousLaunchIds),...Object.values(restart.launchIds)];
  async function makeGroups(runtimeGenerationId){
    for(const {core} of members){
      const {groupPath}=linuxContainerCgroup({driver:core.driver,role:core.role,generationId:runtimeGenerationId});
      for(const directory of ['/sys/fs/cgroup'+groupPath,'/sys/fs/cgroup'+groupPath+'/core']){
        await fs.mkdir(directory);directories.push(directory);
      }
    }
  }
  async function retire(launchId){
    for(let attempt=0;attempt<100;attempt++){
      if(host.retire(launchId).phase==='retired')return;
      await delay(20);
    }
    assert.fail('recovery writer did not retire');
  }
  async function checkProtectedHealth(port){
    let health;
    for(let attempt=0;attempt<50;attempt++){
      health=await fetch('http://127.0.0.1:'+port+'/health/ready',{signal:AbortSignal.timeout(300)}).catch(()=>null);
      if(health)break;
      await delay(20);
    }
    assert.equal(health?.status,503);
    assert.equal((await health.json()).ready,false);
  }
  try{
    await makeGroups(members[0].core.generation_id);
    await assert.rejects(host.start({planFile:members[0].file,planDigest:members[0].digest}),{code:'linux_recovery_start_required'});
    await assert.rejects(host.startRecovery({...start,selectionDigest:digest('wrong selection')}),{code:'linux_recovery_selection'});
    await assert.rejects(host.startRecovery({...start,authorize:()=>({allowed:false})}),{code:'linux_recovery_authority'});
    const changed=members[1].file,bytes=await fs.readFile(changed);
    await fs.appendFile(changed,'\n');
    try{await assert.rejects(host.startRecovery(start),{code:'linux_native_artifact_changed'});}
    finally{await fs.writeFile(changed,bytes);}
    for(const {core} of members)assert.equal(host.lookup(core.launch_id).launch,null);
    assert.equal(await fs.stat(path.dirname(members[0].core.data_directory)).catch(error=>error.code),'ENOENT');
    const result=await host.startRecovery(start);
    assert.equal(result.phase,'executed_closed');
    assert.deepEqual(result.members.map(member=>member.intent.database_instance_id),members.map(({core})=>core.bootstrap.database_instance_id));
    for(const [index,{core}] of members.entries()){
      assert.equal(result.members[index].detail.admission.receipt.gate_state,'closed');
      assert.equal((await fs.stat(core.data_directory)).uid,core.uid);
      await checkProtectedHealth(core.port);
    }
    await assert.rejects(host.startRecovery(start),{code:'linux_recovery_start_indeterminate'});
    await makeGroups(restart.runtimeGenerationId);
    await assert.rejects(host.startRecovery({...start,restart}),{code:'recovery_linux_native_retirement_unproven'});
    for(const id of Object.values(previousLaunchIds))await retire(id);
    host.close();
    host=null;
    host=openHost();
    await assert.rejects(host.startRecovery({...start,restart:{...restart,previousLaunchIds:{...previousLaunchIds,controller:crypto.randomUUID()}}}),
      {code:'linux_recovery_restart'});
    await assert.rejects(host.startRecovery({...start,restart,authorize:context=>({...start.authorize(context),retirement_digest:digest('obsolete')})}),
      {code:'linux_recovery_authority'});
    const {core}=members[0],runtimeFile=path.join(core.data_directory,core.role+'.sqlite'),originalFile=path.join(f.root,'first-runtime.sqlite');
    await fs.rename(runtimeFile,originalFile);
    try{
      await fs.copyFile(originalFile,runtimeFile);
      await fs.chown(runtimeFile,core.uid,core.gid);
      await assert.rejects(host.startRecovery({...start,restart}),{code:'linux_recovery_data'});
    }finally{await fs.rename(originalFile,runtimeFile);}
    for(const id of Object.values(restart.launchIds))assert.equal(host.lookup(id).launch,null);
    const restarted=await host.startRecovery({...start,restart});
    assert.equal(restarted.selection_digest,result.selection_digest);
    assert.equal(restarted.phase,'executed_closed');
    for(const [index,{core}] of members.entries()){
      const prior=result.members[index],current=restarted.members[index];
      assert.notEqual(prior.detail.admission.receipt.member_boot_id,current.detail.admission.receipt.member_boot_id);
      assert.equal(current.intent.generation_id,restart.runtimeGenerationId);
      assert.equal(current.intent.database_instance_id,prior.intent.database_instance_id);
      assert.equal(current.detail.admission.receipt.gate_state,'closed');
      assert.deepEqual(current.detail.recovery,prior.detail.recovery);
      await checkProtectedHealth(core.port);
      await retire(current.intent.launch_id);
      const retained=path.join(f.root,core.role+'-restart-check.sqlite'),database=path.join(core.data_directory,core.role+'.sqlite');
      await fs.copyFile(database,retained);
      await fs.copyFile(database+'-wal',retained+'-wal').catch(error=>{if(error.code!=='ENOENT')throw error;});
      const after=new DatabaseSync(retained);
      try{assert.equal(after.prepare('SELECT count(*) AS count FROM service_boot').get().count,2);}
      finally{after.close();}
    }
    host.close();
    host=null;
    const journal=f.reopen().openLinuxMemberJournal(null);
    try{
      const nextGeneration=crypto.randomUUID();
      const after=journal.recoveryRetirement(selected.deployment.generation_id,nextGeneration);
      assert.deepEqual(after.members.map(entry=>entry.generation_id),[restart.runtimeGenerationId,restart.runtimeGenerationId]);
      assert.deepEqual(journal.recoveryRetirement(restart.runtimeGenerationId,nextGeneration),after);
    }finally{journal.close();f.close();}
  }finally{
    try{
      for(const id of host?allLaunches:[]){
        const record=host.lookup(id);
        if(record.launch?.detail.leader&&record.retirement?.phase!=='retired')await retire(id);
      }
    }finally{host?.close();}
    for(const directory of directories.reverse())await fs.rmdir(directory);
  }
}

async function checkWindowsRecoveryStartup({f,plan,configuration,activated,windowsAuthority}){
  const {openWindowsNativeHost}=await import('@leafseamer/suite/windows-native-host');
  const {readProcessRecoveryRetirement}=await import(pathToFileURL(path.join(configuration.distribution.directory,'process-host.mjs')));
  f.close();
  const open=()=>openWindowsNativeHost({installationDirectory:f.root}),host=open();
  const start={plan,configuration,selectionDigest:activated.selection_digest,
    authorize({selection,retirement_digest,secret_binding_digest}){
      return {...windowsAuthority(),selection_digest:selection.selection_digest,
        release_manifest_digest:selection.deployment.release_manifest_digest,retirement_digest,secret_binding_digest};
    }};
  const {data_ref,scope}=activated.deployment.services[0],content=path.join(f.root,'content');
  const source=path.join(content,data_ref.attempt_id,data_ref.directory_name,'controller.sqlite');
  const directory=path.join(content,plan.generation_id,data_ref.directory_name);
  try{
    await assert.rejects(host.startRecovery({...start,selectionDigest:digest('obsolete deployment')}),{code:'windows_recovery_selection'});
    await assert.rejects(host.startRecovery({...start,configuration:{...configuration,port:1}}),{code:'windows_recovery_configuration'});
    await assert.rejects(host.startRecovery({...start,authorize:context=>({...start.authorize(context),secret_binding_digest:digest('old secrets')})}),
      {code:'windows_recovery_authority'});
    await assert.rejects(host.startRecovery({...start,authorize:context=>({...start.authorize(context),runtime_generation_id:crypto.randomUUID()})}),
      {code:'windows_recovery_retirement'});
    const bytes=await fs.readFile(source),damaged=Buffer.from(bytes);
    damaged[damaged.length-1]^=1;
    await fs.writeFile(source,damaged);
    try{await assert.rejects(host.startRecovery(start),{code:'recovery_preparation_files'});}
    finally{await fs.writeFile(source,bytes);}
    assert.equal(await fs.stat(directory).catch(error=>error.code),'ENOENT');
    const runtime=await host.startRecovery(start);
    assert.equal(runtime.selection_digest,activated.selection_digest);
    assert.equal(runtime.containment.bootstrap_authenticated,true);
    assert.equal(runtime.containment.runtime_admitted,false);
    let health;
    for(let attempt=0;attempt<100;attempt++){
      health=await fetch('http://127.0.0.1:'+configuration.port+'/health/ready',{signal:AbortSignal.timeout(300)}).catch(()=>null);
      if(health)break;
      await delay(20);
    }
    assert.equal(health?.status,503);
    assert.equal((await health.json()).ready,false);
    assert.equal((await runtime.close()).active_processes,0);
    const journal=new DatabaseSync(path.join(directory,'supervisor-journal.db'),{readOnly:true});
    let runtimeGeneration;
    try{
      runtimeGeneration=journal.prepare("SELECT json_extract(descriptor_jcs,'$.runtime_generation') AS id FROM core_bootstrap").get().id;
    }finally{journal.close();}
    const receipt=await readProcessRecoveryRetirement({dataDir:directory,runtimeGeneration,
      serviceId:scope.service_id,databaseInstanceId:scope.database_instance_id});
    assert.equal(receipt.containment_id,runtime.containment.containment_id);
    assert.equal(receipt.active_processes,0);
  }finally{await host.close();}
  const reopened=open();
  try{await assert.rejects(reopened.startRecovery(start),{code:'windows_recovery_start_indeterminate'});}
  finally{await reopened.close();}
}

async function checkWindowsRetirement(t,{f,sources,scopes,distributions,retiredPlan,retirementRequest,acceptedPlan}){
  const supervisor=distributions.controller;
  const {initializeProcessHost,installedCoreDigest,startProcessHost,readProcessRecoveryRetirement}=await import(
    pathToFileURL(path.join(supervisor.directory,'process-host.mjs')).href);
  for(const directory of Object.values(sources))await initializeProcessHost(directory);
  const policy=(scope,artifactDigest)=>({format:'leafseamer-core-bootstrap-policy/1',service_id:scope.service_id,
    database_instance_id:scope.database_instance_id,artifact_manifest_ref:{manifest_id:'fixture.runtime',revision:'1',digest:artifactDigest},
    platform_profile_ref:{profile_id:'fixture.windows',revision:'1'},policy_revision:'1',bootstrap_timeout_ms:10000,clock_backend_revision:'1'});
  const [controller,seamer]=scopes;
  async function startController(){
    let output='';
    const app=await startProcessHost({dataDir:sources.controller,bootstrapPolicy:policy(controller,installedCoreDigest()),
      onCoreOutput:chunk=>{output+=chunk;}});
    t.after(()=>app.close());
    const deadline=performance.now()+12000;
    while(!output.includes('"event":"listening"')){
      assert.ok(performance.now()<deadline,'Controller did not listen: '+output);
      await delay(20);
    }
    return app;
  }
  const controllerHost=await startController();
  if(!seamer){
    assert.equal((await controllerHost.close()).exitCode,0);
    const runtime_generation_id=crypto.randomUUID();
    const windows_runtime={supervisor,writers_fenced:true,writers:[{authority:'controller',service_id:controller.service_id,
      database_instance_id:controller.database_instance_id,data_directory:sources.controller,runtime_generation:journalGeneration(sources.controller)}]};
    const authority=()=>({...authorize(),runtime_generation_id,windows_runtime});
    const ledger=f.store.enableWindowsRecoveryFencing();
    const retired=await ledger.recordWindowsRecoveryRetirement(retirementRequest,authority);
    assert.equal(retired.retirement.evidence.members.length,1);
    assert.equal(retired.retirement.evidence.format,'leafseamer-windows-deployment-retirement/2');
    await assert.rejects(startProcessHost({dataDir:sources.controller}),{code:'process_recovery_startup_fenced'});
    return authority;
  }
  const seamerHost=path.join(f.root,'fixture-seamer-host'),artifacts={};
  for(const name of ['native/leafseamer_process_host.exe','runtime/node.exe']){
    const target=path.join(seamerHost,name);
    await fs.mkdir(path.dirname(target),{recursive:true});
    await fs.copyFile(path.join(supervisor.directory,name),target);
    artifacts[name]=crypto.createHash('sha256').update(await fs.readFile(target)).digest('hex');
  }
  const importURL=name=>JSON.stringify(pathToFileURL(path.join(distributions.seamer.directory,name)).href);
  const entry=`import {openStorage} from ${importURL('storage.mjs')};
    import {createCoreBootstrapChannel,verifyCoreAssignment,verifyCoreAdmission,validateBootstrapPolicy} from ${importURL('core-bootstrap.mjs')};
    const dataDirectory=process.argv[process.argv.indexOf('--data-dir')+1];
    const policy=validateBootstrapPolicy(JSON.parse(process.argv[process.argv.indexOf('--bootstrap-policy')+1]));
    const db=openStorage(dataDirectory);
    const channel=createCoreBootstrapChannel(process.stdin,process.stdout,{timeoutMs:policy.bootstrap_timeout_ms});
    const assignment=await channel.assignment();
    verifyCoreAssignment(assignment,policy,db.identity);
    const binding=await verifyCoreAdmission(assignment,await channel.proveAndReceive(assignment),policy);
    channel.release();
    process.stderr.write(binding.descriptor.runtime_generation+'\\n');
    process.stdin.once('data',()=>process.stdin.destroy());
    process.stdin.once('close',()=>db.close());
    process.stdin.resume();`;
  await fs.writeFile(path.join(seamerHost,'core.mjs'),entry);
  artifacts['core.mjs']=crypto.createHash('sha256').update(entry).digest('hex');
  const manifest=JSON.stringify({format:'leafseamer-controller-build/1',artifacts});
  await fs.writeFile(path.join(seamerHost,'build-manifest.json'),manifest);
  const seamerPolicy=policy(seamer,digest({controller_build_sha256:crypto.createHash('sha256').update(manifest).digest('hex'),
    node_sha256:artifacts['runtime/node.exe']}));
  const peer=spawn(path.join(seamerHost,'native/leafseamer_process_host.exe'),
    [sources.seamer,path.join(seamerHost,'runtime/node.exe'),path.join(seamerHost,'core.mjs'),'contained-core-auth',
      '--bootstrap-policy',canonical(seamerPolicy)],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  const ended=once(peer,'close');ended.catch(()=>{});peer.stdin.on('error',()=>{});peer.stdout.resume();
  const finishSeamer=()=>{if(!peer.stdin.writableEnded)peer.stdin.end('stop\n');return ended;};
  t.after(finishSeamer);
  const [message]=await once(peer.stderr,'data',{signal:AbortSignal.timeout(15000)});
  const seamerGeneration=message.toString().trim();
  assert.match(seamerGeneration,/^[a-f0-9]{32}$/);
  assert.equal((await controllerHost.close()).exitCode,0);
  function journalGeneration(directory){
    const db=new DatabaseSync(path.join(directory,'supervisor-journal.db'),{readOnly:true});
    try{return db.prepare("SELECT json_extract(descriptor_jcs,'$.runtime_generation') AS id FROM core_bootstrap ORDER BY rowid DESC LIMIT 1").get().id;}
    finally{db.close();}
  }
  const windows_runtime={supervisor,writers_fenced:true,writers:scopes.map((scope,index)=>({authority:scope.authority,
    service_id:scope.service_id,database_instance_id:scope.database_instance_id,data_directory:sources[scope.authority],
    runtime_generation:index===0?journalGeneration(sources.controller):seamerGeneration}))};
  const runtime_generation_id=crypto.randomUUID();
  const authority=()=>({...authorize(),runtime_generation_id,windows_runtime});
  await assert.rejects(retiredPlan.recordWindowsRecoveryRetirement(retirementRequest,authority),
    {code:'recovery_windows_fencing_migration_required'});
  let ledger=f.store.enableWindowsRecoveryFencing();
  const record=(choose=authority,request=retirementRequest)=>ledger.recordWindowsRecoveryRetirement(request,choose);
  const withWriters=writers=>()=>({...authority(),windows_runtime:{...windows_runtime,writers}});
  await assert.rejects(record(withWriters(windows_runtime.writers.slice(0,1))),{code:'recovery_retirement_target_mismatch'});
  await assert.rejects(record(withWriters([{...windows_runtime.writers[0],database_instance_id:crypto.randomUUID()},
    windows_runtime.writers[1]])),{code:'recovery_retirement_target_mismatch'});
  await assert.rejects(record(()=>({...authority(),windows_runtime:{...windows_runtime,writers_fenced:false}})),{code:'recovery_windows_runtime'});
  await assert.rejects(record(),{code:'recovery_windows_retirement_unproven'});
  assert.deepEqual(retiredPlan.getRecoveryPlan(retirementRequest.plan_ref.restore_id),acceptedPlan);
  assert.deepEqual(await finishSeamer(),[0,null]);
  await assert.rejects(record(()=>({...authority(),windows_runtime:{...windows_runtime,
    supervisor:{...supervisor,manifest_sha256:'sha256:'+'0'.repeat(64)}}})),{code:'recovery_windows_retirement_unproven'});
  const newer=await startController();
  assert.equal((await newer.close()).exitCode,0);
  await assert.rejects(record(),{code:'recovery_windows_retirement_unproven'});
  windows_runtime.writers[0].runtime_generation=journalGeneration(sources.controller);

  const sorted=windows_runtime.writers.slice().sort((a,b)=>a.database_instance_id<b.database_instance_id?-1:1);
  const readMember=({data_directory,runtime_generation,service_id,database_instance_id})=>readProcessRecoveryRetirement({
    dataDir:data_directory,runtimeGeneration:runtime_generation,serviceId:service_id,databaseInstanceId:database_instance_id});
  const originalMembers=await Promise.all(sorted.map(async writer=>({...await readMember(writer),authority:writer.authority})));
  assert.ok(originalMembers.every(member=>!member.startup_fence));
  const historical={...retirementRequest,approval_id:acceptedPlan.approval.approval_id,evidence:{
    format:'leafseamer-windows-deployment-retirement/1',generation_id:runtime_generation_id,
    source_digest:digest('prior verified supervisor distribution'),members:originalMembers}};
  // 模拟升级前已经持久化的只读见证，字节与摘要必须能够原样查回。
  f.close();
  const installationDb=new DatabaseSync(path.join(f.root,'installation.db'));
  try{installationDb.prepare('INSERT INTO maintenance_recovery_retirement VALUES (?,?,?,?,?,?)').run(retirementRequest.plan_ref.restore_id,
    retirementRequest.retirement_id,historical.approval_id,retirementRequest.plan_ref.digest,Buffer.from(canonical(historical)),digest(historical));}
  finally{installationDb.close();}
  ledger=f.reopen().backupMaintenance();
  const historicalView={...acceptedPlan,historical_retirement:historical};
  assert.deepEqual(ledger.getRecoveryPlan(retirementRequest.plan_ref.restore_id),historicalView);

  const expectedFence={plan_digest:retirementRequest.plan_ref.digest,retirement_id:retirementRequest.retirement_id};
  await assert.rejects(record(({action,writer})=>({...authority(),
    allowed:action!=='fence_recovery_startup'||writer.database_instance_id!==sorted[1].database_instance_id})),{code:'restore_not_authorized'});
  assert.deepEqual((await readMember(sorted[0])).startup_fence,expectedFence);
  assert.equal((await readMember(sorted[1])).startup_fence,undefined);
  ledger=f.reopen().backupMaintenance();
  const pending=ledger.getRecoveryPlan(retirementRequest.plan_ref.restore_id);
  assert.equal(pending.phase,'plan_reviewed');
  assert.deepEqual(pending.historical_retirement,historical);
  assert.equal(pending.retirement_intent.retirement_id,retirementRequest.retirement_id);
  await assert.rejects(record(authority,{...retirementRequest,retirement_id:crypto.randomUUID()}),{code:'recovery_retirement_conflict'});
  await assert.rejects(record(({action})=>({...authority(),
    ...(action==='adopt_recovery_retirement'&&{runtime_generation_id:crypto.randomUUID()})})),{code:'recovery_runtime_generation_changed'});
  assert.deepEqual(ledger.getRecoveryPlan(retirementRequest.plan_ref.restore_id),pending);
  for(const writer of sorted){
    assert.deepEqual((await readMember(writer)).startup_fence,expectedFence);
    await assert.rejects(startProcessHost({dataDir:writer.data_directory}),{code:'process_recovery_startup_fenced'});
  }
  const retired=await record();
  assert.equal(retired.phase,'old_writers_retired');
  assert.equal(retired.retirement.approval_id,acceptedPlan.approval.approval_id);
  assert.equal(retired.retirement.evidence.format,'leafseamer-windows-deployment-retirement/2');
  assert.deepEqual(retired.retirement.evidence.members.map(({authority,service_id,database_instance_id})=>
    ({authority,service_id,database_instance_id})).sort((a,b)=>a.authority.localeCompare(b.authority)),
  scopes.map(({authority,service_id,database_instance_id})=>({authority,service_id,database_instance_id})));
  assert.deepEqual(retired.retirement.evidence.members,originalMembers.map(member=>({...member,startup_fence:expectedFence})));
  assert.deepEqual(retired.historical_retirement,historical);
  const reopened=f.reopen().backupMaintenance();
  assert.deepEqual(reopened.getRecoveryPlan(retirementRequest.plan_ref.restore_id),retired);
  assert.deepEqual(await reopened.recordWindowsRecoveryRetirement(retirementRequest,authority),retired);
}

for(const standalone of [false,true])test(standalone?'recovers and starts the standalone Windows Controller':
  'publishes a dual-service archive and verifies its exact snapshots in isolated recovery',{
  timeout:360000,skip:standalone?(process.platform!=='win32'||!distributionDirectories.controller):!Object.values(distributionDirectories).every(Boolean)
},async t=>{
  const f=await fixture(t);
  f.store.enableBackupMaintenance();
  const ledger=f.store.enableBackupPublication();
  const distributions={},sources={},scopes=[];
  const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
  for(const [authority,directory] of Object.entries(distributionDirectories)){
    if(standalone&&authority!=='controller')continue;
    const source=path.join(f.root,'source-'+authority);
    const storage=await import(pathToFileURL(path.join(directory,'storage.mjs')).href);
    const initial=storage.initializeStorage(source);
    const revision=authority==='controller'?(await import(pathToFileURL(path.join(directory,'storage-revision.mjs')).href)).currentStorageRevision:'48';
    await storage.migrateStorage(source,revision);
    const opened=storage.openStorage(source),state=opened.identity;
    opened.close();
    assert.equal(state.service_id,initial.service_id);
    scopes.push({authority,service_id:state.service_id,database_instance_id:state.database_instance_id,
      schema_revision:state.schema_revision,request_epoch:state.request_epoch,control_epoch:state.control_epoch??null});
    distributions[authority]={directory,manifest_sha256:'sha256:'+hash(await fs.readFile(path.join(directory,'build-manifest.json')))};
    sources[authority]=source;
  }
  const coverage=[{kind:'secret',reference:'fixture.device-credential',state:'excluded',path:''}];
  const archiveUnresolved=['fixture.site-check'];
  const {operation}=f.request(ledger,'real-domains',{target_service_scopes:scopes,coverage_digest:digest(coverage)});
  const ready=await ledger.collectSnapshots(operation.operation_id,operation.revision,
    {authorize,sourceDirectory:scope=>sources[scope.authority]});
  assert.equal(ready.step,'snapshots_staged');
  const {operation_id:id,revision}=ready;
  const {reports,verifiers,verification_ref}=await ledger.verifySnapshots(id,revision,distributions,authorize);
  assert.equal(reports.length,scopes.length);
  assert.deepEqual(reports.map(report=>JSON.parse(report.text).scope),scopes);
  assert.ok(JSON.parse(reports[0].text).command_inventory);
  if(!standalone)assert.ok(JSON.parse(reports[1].text).execution_inventory);
  await assert.rejects(ledger.verifySnapshots(id,revision,{...distributions,
    controller:{...distributions.controller,manifest_sha256:'sha256:'+'0'.repeat(64)}},authorize),
  {code:'backup_snapshot_verification'});

  const stage=path.join(f.root,'staging','backup-'+id),directory=path.join(stage,'archive');
  await fs.mkdir(path.join(directory,'files','db'),{recursive:true,mode:0o700});
  await fs.mkdir(path.join(directory,'files','reports'),{mode:0o700});
  const files=[],databases=[];
  for(const {receipt,backup_operation_id:point} of ledger.snapshots(id)){
    const {authority,service_id,database_instance_id,schema_revision}=receipt.scope;
    const entry='db/'+authority+'.sqlite';
    await fs.copyFile(path.join(stage,point,'snapshot.partial','data.sqlite'),path.join(directory,'files',entry));
    files.push({role:'database',path:entry,size:receipt.bytes,sha256:receipt.sha256});
    databases.push({path:entry,service:service_id,database_instance:database_instance_id,
      schema:schema_revision,engine:receipt.engine,consistency_point:point});
  }
  for(const report of reports){
    await fs.writeFile(path.join(directory,'files',report.path),report.text);
    files.push({role:'validation_report',path:report.path,size:report.size,sha256:report.sha256});
  }
  files.sort((a,b)=>a.path<b.path?-1:1);
  const manifest={format:'leafseamer-backup-tar/1',backup_id:id,level:'L2',consistency:'online',
    files,databases,coverage,unresolved:archiveUnresolved,validation_reports:reports.map(report=>report.path)};
  const manifestFile=path.join(directory,'manifest.json'),manifestRaw=JSON.stringify(manifest);
  const actions=[];
  const authority=({action,archive})=>{
    actions.push(action);
    return {...authorize(),verified:archive?.verification_ref===verification_ref&&
      archive?.manifest_sha256===hash(manifestRaw)&&Array.isArray(archive?.verifiers)&&
      digest(archive.verifiers)===digest(verifiers)};
  };
  const options={distributions,mode:'passphrase',passphrase:Buffer.from('synthetic publication secret')};
  await assert.rejects(ledger.publishArchive(id,revision,{...options,verification_ref},()=>({...authorize(),verified:true})),
    {code:'backup_archive_verification'});
  const badFiles=files.map(file=>file.path===reports[0].path?{...file,sha256:'0'.repeat(64)}:file);
  await fs.writeFile(manifestFile,JSON.stringify({...manifest,files:badFiles}));
  await assert.rejects(ledger.publishArchive(id,revision,options,()=>({...authorize(),verified:true})),
    {code:'backup_archive_domain_reports'});
  assert.equal(ledger.getArchive(id),null);
  await fs.writeFile(manifestFile,manifestRaw);
  await exec(cryptoTool,['pack','--directory',directory],{windowsHide:true});
  const result=await ledger.publishArchive(id,revision,options,authority);
  assert.equal(result.phase,'succeeded');
  assert.deepEqual(actions,['verify_snapshots','seal_archive','publish_archive']);
  const reopened=f.reopen(),beforeRestore=reopened.backupMaintenance();
  assert.deepEqual(beforeRestore.getArchive(id),result.archive);
  const restoreId=crypto.randomUUID();
  assert.throws(()=>beforeRestore.getRestore(restoreId),{code:'restore_migration_required'});
  const recovery=reopened.enableBackupRestore();
  const request={restore_id:restoreId,archive_id:id,expected_generation:generation,distributions,secret:options.passphrase};
  assert.deepEqual(recovery.getArchive(id),result.archive);
  await assert.rejects(recovery.stageRestore(request,()=>({allowed:true,generation:'8'})),{code:'restore_generation_conflict'});
  assert.equal(recovery.getRestore(restoreId),null);
  const failedId=crypto.randomUUID();
  const failed=await recovery.stageRestore({...request,restore_id:failedId,secret:Buffer.from('wrong secret')},authorize);
  assert.equal(failed.phase,'failed');
  assert.equal(failed.reason_code,'restore_decrypt');
  await assert.rejects(fs.stat(path.join(f.root,'staging','restore-'+failedId)),{code:'ENOENT'});
  assert.equal(recovery.getRestore(failedId).phase,'failed');
  const restoreActions=[];
  const restored=await recovery.stageRestore(request,({action,archive,restore})=>{
    restoreActions.push(action);
    assert.deepEqual(archive,result.archive);
    if(action==='adopt_isolated_restore')assert.equal(restore.verification_ref,verification_ref);
    return authorize();
  });
  assert.equal(restored.phase,'isolated_validated');
  assert.equal(restored.snapshot_count,scopes.length);
  assert.equal(restored.command_review.state,'matched');
  assert.equal(restored.command_review.checked,0);
  assert.match(restored.command_review.review_digest,/^sha256:[a-f0-9]{64}$/);
  assert.equal(restored.manifest_sha256,hash(manifestRaw));
  assert.deepEqual(restoreActions,['stage_restore','adopt_isolated_restore']);
  const isolated=path.join(f.root,'staging','restore-'+restoreId);
  assert.deepEqual(await fs.readdir(isolated),['restored.partial']);
  for(const {path:member,sha256} of files)
    assert.equal(hash(await fs.readFile(path.join(isolated,'restored.partial','files',member))),sha256);
  const durable=f.reopen().backupMaintenance();
  assert.deepEqual(durable.getRestore(restoreId),restored);
  assert.deepEqual(await durable.stageRestore({...request,secret:undefined},authorize),restored);
  assert.throws(()=>durable.getRecoveryPlan(restoreId),{code:'recovery_plan_migration_required'});

  const plans=f.store.enableRecoveryPlans();
  const nativeStart=process.platform==='linux'&&process.env.LEAFSEAMER_TEST_NATIVE_CGROUP==='1'&&
    process.env.LEAFSEAMER_TEST_RECOVERY_NATIVE_BOOT==='1';
  const target={deployment_plan_ref:'deployment.fixture.next',deployment_plan_digest:digest('approved deployment'),
    release_manifest_digest:digest('approved release'),generation_id:crypto.randomUUID(),
    services:scopes.map(scope=>({source_database_instance_id:scope.database_instance_id,data_generation_id:crypto.randomUUID(),
      schema_revision:scope.schema_revision,configuration_ref:'configuration.fixture.'+scope.authority,secret_policy_ref:'secrets.fixture.reconfigure'}))};
  const linuxPlan=nativeStart?{format:'leafseamer.linux-native-recovery/1',deployment_plan_ref:target.deployment_plan_ref,
    generation_id:target.generation_id,release_manifest_digest:target.release_manifest_digest,runtime_root:path.join(path.dirname(f.root),'runtime'),
    configuration_refs:Object.fromEntries(scopes.map((scope,index)=>[scope.authority,target.services[index].configuration_ref]))}:null;
  if(linuxPlan)target.deployment_plan_digest=digest(linuxPlan);
  const windowsPlan=standalone?{format:'leafseamer.windows-native-recovery/1',deployment_plan_ref:target.deployment_plan_ref,
    generation_id:target.generation_id,release_manifest_digest:target.release_manifest_digest,configuration_ref:target.services[0].configuration_ref}:null;
  if(windowsPlan)target.deployment_plan_digest=digest(windowsPlan);
  await assert.rejects(plans.prepareRecoveryPlan(restoreId,{...target,services:target.services.slice(1)},authorize),
    {code:'recovery_target_plan'});
  const review=await plans.prepareRecoveryPlan(restoreId,target,authorize);
  assert.equal(review.phase,'awaiting_local_approval');
  assert.equal(review.plan.expected_generation,generation);
  assert.equal(review.plan.coverage_digest,digest(coverage));
  assert.equal(review.plan.unresolved_digest,digest(archiveUnresolved));
  assert.equal(review.plan.uncovered_count,1);
  assert.equal(review.plan.unresolved_count,1);
  assert.equal(review.plan.has_review_items,true);
  assert.equal(review.plan.requires_site_review,true);
  assert.equal(review.plan.requires_protected_start,true);
  assert.deepEqual(review.plan.target,target);
  assert.deepEqual(review.plan.services.map(service=>service.source_scope),scopes);
  for(const {source_scope:source,next_scope:next} of review.plan.services){
    assert.equal(next.service_id,source.service_id);
    assert.notEqual(next.database_instance_id,source.database_instance_id);
    assert.notEqual(next.request_epoch,source.request_epoch);
    if(source.authority==='controller')assert.notEqual(next.control_epoch,source.control_epoch);
    else assert.equal(next.control_epoch,null);
  }
  assert.deepEqual(await plans.prepareRecoveryPlan(restoreId,target,authorize),review);
  await assert.rejects(plans.prepareRecoveryPlan(restoreId,{...target,release_manifest_digest:digest('other release')},authorize),
    {code:'recovery_plan_conflict'});

  const approval={approval_id:crypto.randomUUID(),plan_ref:review.plan_ref,
    command_review_digest:review.plan.command_review.review_digest,coverage_digest:review.plan.coverage_digest,
    unresolved_digest:review.plan.unresolved_digest};
  const subject=process.platform==='win32'?'S-1-5-21-1-2-3-1001':'uid:0';
  const admin=()=>({...authorize(),origin:'local_os',os_subject:subject});
  await assert.rejects(plans.approveRecoveryPlan(approval,authorize),{code:'recovery_local_admin_required'});
  await assert.rejects(plans.approveRecoveryPlan({...approval,unresolved_digest:digest([])},admin),
    {code:'recovery_approval_invalid'});
  const database=path.join(isolated,'restored.partial','files',databases[0].path);
  const originalDatabase=await fs.readFile(database),changed=Buffer.from(originalDatabase);
  changed[changed.length-1]^=1;
  await fs.writeFile(database,changed);
  await assert.rejects(plans.approveRecoveryPlan(approval,admin),{code:'restore_candidate_changed'});
  await fs.writeFile(database,originalDatabase);
  await fs.writeFile(database+'-wal','unexpected sidecar');
  await assert.rejects(plans.approveRecoveryPlan(approval,admin),{code:'restore_candidate_changed'});
  await fs.unlink(database+'-wal');
  await assert.rejects(plans.approveRecoveryPlan(approval,({action})=>
    ({...admin(),generation:action==='approve_recovery_plan'?'8':generation})),{code:'restore_generation_conflict'});
  assert.equal(plans.getRecoveryPlan(restoreId).approval,null);
  const acceptedPlan=await plans.approveRecoveryPlan(approval,admin);
  assert.equal(acceptedPlan.phase,'plan_reviewed');
  assert.deepEqual(acceptedPlan.approval,{...approval,os_subject:subject});
  assert.equal(acceptedPlan.plan.requires_site_review,true);
  const approved=f.reopen().backupMaintenance();
  assert.deepEqual(approved.getRecoveryPlan(restoreId),acceptedPlan);
  assert.deepEqual(await approved.approveRecoveryPlan(approval,admin),acceptedPlan);
  await assert.rejects(approved.approveRecoveryPlan({...approval,approval_id:crypto.randomUUID()},admin),
    {code:'recovery_approval_conflict'});
  assert.deepEqual(approved.getRestore(restoreId),restored);
  const retirementRequest={plan_ref:review.plan_ref,retirement_id:crypto.randomUUID()};
  await assert.rejects(approved.recordWindowsRecoveryRetirement(retirementRequest,authorize),
    {code:'recovery_retirement_migration_required'});
  assert.throws(()=>approved.recordLinuxRecoveryRetirement(retirementRequest,authorize),
    {code:'recovery_retirement_migration_required'});
  const retiredPlan=f.store.enableRecoveryRetirement();
  let windowsAuthority;
  if(process.platform==='linux'){
    await assert.rejects(retiredPlan.recordWindowsRecoveryRetirement(retirementRequest,authorize),{code:'recovery_retirement_platform'});
    const native=process.env.LEAFSEAMER_TEST_NATIVE_CGROUP==='1';
    if(native)f.store.initializeLinuxMemberJournal();
    else f.store.initializeLinuxDeploymentJournal();
    const fixture=native?await nativeDeploymentFixture(f.store,scopes):process.env.LEAFSEAMER_TEST_CGROUP_HOST==='1'
      ? await liveDeploymentFixture(f.store,scopes):writeDeploymentFixture(f.root,scopes);
    const method=native?'recordLinuxNativeRecoveryRetirement':'recordLinuxRecoveryRetirement';
    const unproven=native?'recovery_linux_native_retirement_unproven':'recovery_linux_retirement_unproven';
    const hostAuthority=()=>({...authorize(),runtime_generation_id:fixture.generation_id});
    let retired;
    try{
      assert.throws(()=>retiredPlan[method](retirementRequest,hostAuthority),{code:unproven});
      assert.deepEqual(retiredPlan.getRecoveryPlan(restoreId),acceptedPlan);
      if(native){
        await fixture.finishFirst();
        assert.throws(()=>retiredPlan[method](retirementRequest,hostAuthority),{code:unproven});
      }
      await fixture.finish();
      assert.throws(()=>retiredPlan[method](retirementRequest,
        ()=>({...authorize(),runtime_generation_id:crypto.randomUUID()})),{code:unproven});
      assert.throws(()=>retiredPlan[method](retirementRequest,({action})=>({...hostAuthority(),
        ...(action==='adopt_recovery_retirement'&&{runtime_generation_id:crypto.randomUUID()})})),
      {code:'recovery_runtime_generation_changed'});
      retired=retiredPlan[method](retirementRequest,hostAuthority);
    }finally{await fixture.close?.();}
    assert.equal(retired.phase,'old_writers_retired');
    assert.deepEqual(retired.retirement.plan_ref,review.plan_ref);
    assert.equal(retired.retirement.approval_id,approval.approval_id);
    if(native){
      assert.equal(retired.retirement.evidence.format,'leafseamer-linux-native-retirement/1');
      assert.equal(retired.retirement.evidence.members.length,2);
      assert.throws(()=>retiredPlan.recordLinuxRecoveryRetirement(retirementRequest,hostAuthority),
        {code:'recovery_retirement_conflict'});
    }else assert.equal(retired.retirement.evidence.endpoint_evidence_digest,fixture.endpoint_evidence_digest);
    const reopenedRetirement=f.reopen().backupMaintenance();
    assert.deepEqual(reopenedRetirement.getRecoveryPlan(restoreId),retired);
    assert.deepEqual(reopenedRetirement[method](retirementRequest,hostAuthority),retired);
    const upgraded=f.store.enableWindowsRecoveryFencing();
    assert.deepEqual(upgraded.getRecoveryPlan(restoreId),retired);
    assert.deepEqual(upgraded[method](retirementRequest,hostAuthority),retired);
  }else{
    assert.throws(()=>retiredPlan.recordLinuxRecoveryRetirement(retirementRequest,authorize),
      {code:'recovery_retirement_platform'});
    assert.throws(()=>retiredPlan.recordLinuxNativeRecoveryRetirement(retirementRequest,authorize),
      {code:'recovery_retirement_platform'});
    if(process.platform==='win32')await t.test(standalone?'fences the old standalone Controller Job':'adopts both Windows writer Jobs into the approved plan',async t=>{
      windowsAuthority=await checkWindowsRetirement(t,{f,sources,scopes,distributions,retiredPlan,retirementRequest,acceptedPlan});
    });
  }

  if(['linux','win32'].includes(process.platform)){
    const prepareInput={plan_ref:review.plan_ref,preparation_id:crypto.randomUUID()};
    const preparationAuthority=()=>({...authorize(),retirement_current:true,target_inactive:true,
      release_manifest_digest:target.release_manifest_digest,distributions});
    const retired=f.store.backupMaintenance();
    const retiredView=retired.getRecoveryPlan(restoreId);
    await assert.rejects(retired.prepareProtectedRecovery(prepareInput,preparationAuthority),{code:'recovery_preparation_migration_required'});
    const preparationLedger=f.store.enableProtectedRecoveryPreparation();
    await assert.rejects(preparationLedger.prepareProtectedRecovery(prepareInput,()=>({...preparationAuthority(),retirement_current:false})),
      {code:'recovery_preparation_authority'});
    assert.deepEqual(preparationLedger.getRecoveryPlan(restoreId),retiredView);
    const filePath=path.join(isolated,'restored.partial','files',databases[0].path),original=await fs.readFile(filePath);
    await fs.appendFile(filePath,'changed');
    try{await assert.rejects(preparationLedger.prepareProtectedRecovery(prepareInput,preparationAuthority),{code:'restore_candidate_changed'});}
    finally{await fs.writeFile(filePath,original);}
    const pending=f.reopen().backupMaintenance();
    assert.equal(pending.getRecoveryPlan(restoreId).phase,'old_writers_retired');
    assert.equal(pending.getRecoveryPlan(restoreId).preparation_intent.preparation_id,prepareInput.preparation_id);
    await assert.rejects(pending.prepareProtectedRecovery({...prepareInput,preparation_id:crypto.randomUUID()},preparationAuthority),
      {code:'recovery_preparation_conflict'});
    const used=[];
    await assert.rejects(pending.prepareProtectedRecovery(prepareInput,({action,result})=>{
      if(action==='adopt_recovery_preparation')used.push(result.attempt_id);
      return {...preparationAuthority(),target_inactive:action!=='adopt_recovery_preparation'};
    }),{code:'recovery_preparation_authority'});
    assert.equal(pending.getRecoveryPlan(restoreId).phase,'old_writers_retired');
    const retried=f.reopen().backupMaintenance();
    const prepared=await retried.prepareProtectedRecovery(prepareInput,preparationAuthority);
    assert.equal(prepared.phase,'prepared_protected');
    assert.equal(prepared.preparation.flush_method,process.platform==='win32'?'FlushFileBuffers':'fsync');
    assert.notEqual(prepared.preparation.attempt_id,used[0]);
    assert.deepEqual(prepared.preparation.services.map(service=>service.next_scope),review.plan.services.map(service=>service.next_scope));
    for(const [index,service] of prepared.preparation.services.entries()){
      const {authority,service_id,database_instance_id,request_epoch}=service.next_scope;
      assert.equal(service.origin.data_generation_id,target.services[index].data_generation_id);
      const generationDirectory=path.join(f.root,'content',prepared.preparation.attempt_id,service.directory_name);
      const name=authority+'.sqlite',output=path.join(generationDirectory,name);
      assert.deepEqual(await fs.readdir(generationDirectory),[name]);
      assert.equal(hash(await fs.readFile(output)),service.sha256);
      const inspection=path.join(f.root,'prepared-inspection-'+index+'.sqlite');
      await fs.copyFile(output,inspection);
      const db=new DatabaseSync(inspection,{readOnly:true});
      try{
        assert.deepEqual({...db.prepare('SELECT service_id,database_instance_id,request_epoch,maintenance_state FROM service_state').get()},
          {service_id,database_instance_id,request_epoch,maintenance_state:'protected'});
        assert.equal(db.prepare('SELECT count(*) AS count FROM service_boot').get().count,0);
      }finally{db.close();}
    }
    const reopened=f.reopen().backupMaintenance();
    assert.deepEqual(reopened.getRecoveryPlan(restoreId),prepared);
    assert.deepEqual(await reopened.prepareProtectedRecovery(prepareInput,preparationAuthority),prepared);
    assert.deepEqual(await fs.readFile(filePath),original);

    const nativeFixture=linuxPlan?await prepareNativeRecoveryFixture(f,target,review,distributions,linuxPlan):null;
    let windowsCore=null;
    if(windowsPlan){
      const {installedCoreDigest}=await import(pathToFileURL(path.join(distributions.controller.directory,'process-host.mjs')));
      const listener=net.createServer().listen(0,'127.0.0.1');
      await once(listener,'listening');
      const {port}=listener.address();
      await new Promise(resolve=>listener.close(resolve));
      const {service_id,database_instance_id}=review.plan.services[0].next_scope;
      windowsCore={format:'leafseamer.windows-native-core/1',host_installation_id:f.identity.host_installation_id,
        distribution:distributions.controller,port,
        bootstrap:{format:'leafseamer-core-bootstrap-policy/1',service_id,database_instance_id,bootstrap_timeout_ms:12000,
          clock_backend_revision:'1',policy_revision:'1',platform_profile_ref:{profile_id:'fixture.recovery',revision:'1'},
          artifact_manifest_ref:{manifest_id:'fixture.windows',revision:'1',digest:installedCoreDigest()}}};
    }
    const siteEvidence={coverage_digest:review.plan.coverage_digest,unresolved_digest:review.plan.unresolved_digest,
      command_review_digest:review.plan.command_review.review_digest,site_observation_ref:'site.fixture',
      site_observation_digest:digest('observed site'),unresolved_disposition:'hold_without_replay',
      services:review.plan.target.services.map((service,index)=>({scope:review.plan.services[index].next_scope,
        data_generation_id:service.data_generation_id,configuration_ref:service.configuration_ref,
        configuration_digest:nativeFixture?.members[index].digest??(windowsCore?digest(windowsCore):digest(['configuration',index])),
        secret_policy_ref:service.secret_policy_ref,secret_binding_ref:'secrets.fixture.'+index,secret_binding_digest:digest(['secret binding',index]),
        secret_state:index===0?'reconfigured':'not_required'}))};
    const siteInput={plan_ref:review.plan_ref,review_id:crypto.randomUUID(),previous_review_digest:null,
      preparation_digest:digest(prepared.preparation),evidence:siteEvidence};
    const evidenceAuthority=evidence=>()=>({...preparationAuthority(),origin:'local_os',os_subject:subject,evidence_digest:digest(evidence)});
    const siteAuthority=evidenceAuthority(siteEvidence);
    await assert.rejects(reopened.recordRecoverySiteReview(siteInput,siteAuthority),{code:'recovery_site_review_migration_required'});
    const reviewLedger=f.store.enableRecoverySiteReview();
    await assert.rejects(reviewLedger.recordRecoverySiteReview(siteInput,preparationAuthority),{code:'recovery_local_admin_required'});
    await assert.rejects(reviewLedger.recordRecoverySiteReview({...siteInput,preparation_digest:digest('wrong attempt')},siteAuthority),
      {code:'recovery_site_preparation'});
    await assert.rejects(reviewLedger.recordRecoverySiteReview({...siteInput,evidence:{...siteEvidence,unresolved_disposition:'replay'}},siteAuthority),
      {code:'recovery_site_evidence'});
    const wrongSecret=structuredClone(siteInput);wrongSecret.evidence.services[0].secret_policy_ref='unapproved.secret.policy';
    await assert.rejects(reviewLedger.recordRecoverySiteReview(wrongSecret,evidenceAuthority(wrongSecret.evidence)),{code:'recovery_site_evidence'});

    const first=prepared.preparation.services[0],output=path.join(f.root,'content',prepared.preparation.attempt_id,
      first.directory_name,first.next_scope.authority+'.sqlite');
    const verifiedBytes=await fs.readFile(output);
    const damaged=Buffer.from(verifiedBytes);damaged[damaged.length-1]^=1;
    await fs.writeFile(output,damaged);
    try{await assert.rejects(reviewLedger.recordRecoverySiteReview(siteInput,siteAuthority),{code:'recovery_preparation_files'});}
    finally{await fs.writeFile(output,verifiedBytes);}
    if(process.platform==='linux'){
      await fs.chmod(output,0o644);
      try{await assert.rejects(reviewLedger.recordRecoverySiteReview(siteInput,siteAuthority),{code:'recovery_preparation_protection'});}
      finally{await fs.chmod(output,0o600);}
    }
    await assert.rejects(reviewLedger.recordRecoverySiteReview(siteInput,({action})=>({...siteAuthority(),
      retirement_current:action!=='adopt_recovery_site_review'})),{code:'recovery_site_authority'});
    assert.deepEqual(reviewLedger.getRecoveryPlan(restoreId),prepared);

    const approvedSite=await reviewLedger.recordRecoverySiteReview(siteInput,siteAuthority);
    assert.equal(approvedSite.revision,1);
    assert.equal(approvedSite.evidence_digest,digest(siteEvidence));
    assert.equal(approvedSite.os_subject,subject);
    const reviewed=f.reopen().backupMaintenance();
    assert.deepEqual(reviewed.getRecoveryPlan(restoreId),{...prepared,site_review:approvedSite});
    const updatedEvidence={...siteEvidence,site_observation_digest:digest('site observed after reconfiguration')};
    const secondInput={...siteInput,review_id:crypto.randomUUID(),evidence:updatedEvidence};
    await assert.rejects(reviewed.recordRecoverySiteReview(secondInput,evidenceAuthority(updatedEvidence)),{code:'recovery_site_review_conflict'});
    const refreshed=await reviewed.recordRecoverySiteReview({...secondInput,previous_review_digest:approvedSite.review_digest},evidenceAuthority(updatedEvidence));
    assert.equal(refreshed.revision,2);
    assert.deepEqual(reviewed.getRecoveryPlan(restoreId),{...prepared,site_review:refreshed});
    assert.deepEqual(await reviewed.recordRecoverySiteReview(siteInput,siteAuthority),approvedSite);

    const activeInput={generation:review.plan.expected_generation,generation_id:prepared.retirement.evidence.generation_id,
      deployment_plan_ref:'deployment.previous',deployment_plan_digest:digest('previous deployment'),
      release_manifest_digest:digest('previous release'),services:scopes.map((scope,index)=>({
        scope,data_generation_id:crypto.randomUUID(),data_ref:'data.previous.'+index,
        configuration_ref:'configuration.previous.'+index,configuration_digest:digest(['previous configuration',index]),
        secret_policy_ref:'secrets.previous.policy.'+index,secret_binding_ref:'secrets.previous.binding.'+index,
        secret_binding_digest:digest(['previous secret binding',index])}))};
    const activeAuthority=({deployment_digest})=>({allowed:true,generation:activeInput.generation,
      origin:'local_os',os_subject:subject,active_current:true,deployment_digest});
    const activationInput={activation_id:crypto.randomUUID(),plan_ref:siteInput.plan_ref,
      expected_selection_digest:digest('no active selection'),review_digest:refreshed.review_digest};
    const activationAuthority=({deployment_digest})=>({...preparationAuthority(),origin:'local_os',os_subject:subject,
      deployment_digest,review_digest:refreshed.review_digest});
    assert.throws(()=>reviewed.getActiveDeployment(),{code:'recovery_activation_migration_required'});
    const ledger=f.store.enableProtectedRecoveryActivation();
    assert.equal(ledger.getActiveDeployment(),null);
    await assert.rejects(ledger.activateProtectedRecovery(activationInput,activationAuthority),{code:'active_deployment_required'});
    assert.throws(()=>ledger.registerActiveDeployment({...activeInput,services:[]},activeAuthority),
      {code:'active_deployment_baseline'});
    assert.throws(()=>ledger.registerActiveDeployment(activeInput,()=>({...activeAuthority({}),origin:'remote'})),
      {code:'recovery_local_admin_required'});
    const initial=ledger.registerActiveDeployment(activeInput,activeAuthority);
    activationInput.expected_selection_digest=initial.selection_digest;
    assert.deepEqual(ledger.registerActiveDeployment(activeInput,activeAuthority),initial);
    assert.throws(()=>ledger.registerActiveDeployment({...activeInput,generation_id:crypto.randomUUID()},activeAuthority),
      {code:'deployment_selection_conflict'});
    await assert.rejects(ledger.activateProtectedRecovery({...activationInput,expected_selection_digest:digest('obsolete')},activationAuthority),
      {code:'deployment_selection_conflict'});
    await assert.rejects(ledger.activateProtectedRecovery({...activationInput,review_digest:approvedSite.review_digest},activationAuthority),
      {code:'recovery_activation_review'});
    await assert.rejects(ledger.activateProtectedRecovery(activationInput,context=>({...activationAuthority(context),
      retirement_current:context.action!=='adopt_recovery_activation'})),{code:'recovery_activation_authority'});
    await fs.writeFile(output,damaged);
    try{await assert.rejects(ledger.activateProtectedRecovery(activationInput,activationAuthority),{code:'recovery_preparation_files'});}
    finally{await fs.writeFile(output,verifiedBytes);}
    assert.equal(ledger.getRecoveryActivation(activationInput.activation_id),null);
    assert.deepEqual(ledger.getActiveDeployment(),initial);

    const activated=await ledger.activateProtectedRecovery(activationInput,activationAuthority);
    assert.equal(activated.phase,'activated_protected');
    assert.equal(activated.deployment.generation,'8');
    assert.equal(activated.deployment.generation_id,review.plan.target.generation_id);
    assert.equal(activated.deployment.release_manifest_digest,review.plan.target.release_manifest_digest);
    assert.equal(activated.deployment.deployment_plan_digest,review.plan.target.deployment_plan_digest);
    assert.deepEqual(activated.deployment.services,updatedEvidence.services.map((service,index)=>({
      ...service,data_ref:{attempt_id:prepared.preparation.attempt_id,directory_name:prepared.preparation.services[index].directory_name,
        sha256:prepared.preparation.services[index].sha256,bytes:prepared.preparation.services[index].bytes}
    })));
    const durable=f.reopen().backupMaintenance();
    assert.deepEqual(durable.getActiveDeployment(),activated);
    assert.deepEqual(durable.getRecoveryActivation(activationInput.activation_id),activated);
    assert.deepEqual(durable.getRecoveryPlan(restoreId),{...prepared,site_review:refreshed,phase:'activated_protected',activation:activated});
    assert.deepEqual(await durable.activateProtectedRecovery(activationInput,()=>assert.fail('a committed activation must only be read')),activated);
    await assert.rejects(durable.activateProtectedRecovery({...activationInput,review_digest:approvedSite.review_digest},activationAuthority),
      {code:'deployment_selection_conflict'});
    await assert.rejects(durable.activateProtectedRecovery({...activationInput,activation_id:crypto.randomUUID()},activationAuthority),
      {code:'recovery_activation_review'});
    await assert.rejects(durable.recordRecoverySiteReview({...secondInput,review_id:crypto.randomUUID(),
      previous_review_digest:refreshed.review_digest},evidenceAuthority(updatedEvidence)),{code:'recovery_site_preparation'});
    assert.deepEqual(await durable.recordRecoverySiteReview(siteInput,siteAuthority),approvedSite);
    assert.deepEqual(await fs.readFile(filePath),original);
    if(nativeFixture){
      await t.test('restarts both selected recovery cores without losing their runtime databases',()=>checkNativeRecoveryStartup(f,nativeFixture,activated));
      assert.deepEqual(await fs.readFile(output),verifiedBytes);
      assert.deepEqual(f.reopen().backupMaintenance().getActiveDeployment(),activated);
    }
    if(windowsCore){
      await t.test('starts the selected Controller in an authenticated Windows Job',()=>
        checkWindowsRecoveryStartup({f,plan:windowsPlan,configuration:windowsCore,activated,windowsAuthority}));
      assert.deepEqual(await fs.readFile(output),verifiedBytes);
      assert.deepEqual(f.reopen().backupMaintenance().getActiveDeployment(),activated);
    }
  }

  const interrupted=crypto.randomUUID();
  f.close();
  const child=`
    import {openInstallationStore} from '@leafseamer/suite/installation';
    const store=openInstallationStore(process.argv[1]);
    await store.backupMaintenance().stageRestore({
      archive_id:process.argv[2], restore_id:process.argv[3], expected_generation:'7',
      distributions:JSON.parse(process.argv[4]), secret:Buffer.from('synthetic publication secret')
    },({action})=>{
      if(action==='adopt_isolated_restore')process.exit(74);
      return {allowed:true,generation:'7'};
    });
  `;
  await assert.rejects(exec(process.execPath,['--disallow-code-generation-from-strings','--input-type=module','--eval',
    child,f.root,id,interrupted,JSON.stringify(distributions)],
  {cwd:new URL('../',import.meta.url),windowsHide:true}),{code:74});
  const afterCrash=f.reopen().backupMaintenance();
  const unresolved=afterCrash.getRestore(interrupted);
  assert.equal(unresolved.phase,'indeterminate');
  assert.equal(unresolved.reason_code,'restore_helper_unconfirmed');
  await assert.rejects(afterCrash.stageRestore({...request,restore_id:crypto.randomUUID()},authorize),{code:'backup_helper_in_use'});
  assert.deepEqual(await afterCrash.stageRestore({...request,restore_id:interrupted,secret:undefined},authorize),unresolved);
  assert.deepEqual(afterCrash.getArchive(id),result.archive);
});

test('a process exit after file synchronization leaves an unpublished orphan and an indeterminate task',{timeout:30000},async t=>{
  const f=await fixture(t);
  f.store.enableBackupMaintenance();
  const ledger=f.store.enableBackupPublication();
  const {operation,input,options}=await publicationFixture(f,ledger,'orphan');
  const pending=f.request(ledger,'queued-after-orphan');
  f.close();
  const child=`
    import {openInstallationStore} from '@leafseamer/suite/installation';
    const store=openInstallationStore(process.argv[1]);
    await store.backupMaintenance().publishArchive(process.argv[2],Number(process.argv[3]),{
      verification_ref:process.argv[4],mode:'passphrase',passphrase:Buffer.alloc(24,97)
    },({action})=>{
      if(action==='publish_archive')process.exit(73);
      return {allowed:true,generation:'7',verified:true};
    });
  `;
  await assert.rejects(exec(process.execPath,['--disallow-code-generation-from-strings','--input-type=module','--eval',
    child,f.root,operation.operation_id,String(operation.revision),options.verification_ref],
  {cwd:new URL('../',import.meta.url),windowsHide:true}),{code:73});
  const file=path.join(f.root,'content',operation.operation_id,'archive.age');
  assert.ok((await fs.stat(file)).size>0);
  const reopened=f.reopen().backupMaintenance();
  assert.equal(reopened.getArchive(operation.operation_id),null);
  const record=reopened.lookup(input.request_key);
  assert.equal(record.phase,'indeterminate');
  assert.equal(record.reason_code,'backup_helper_unconfirmed');
  assert.equal(record.revision,operation.revision+2);
  await assert.rejects(reopened.collectSnapshots(pending.operation.operation_id,1,{authorize,sourceDirectory:()=>f.source}),
    {code:'backup_helper_in_use'});
  assert.deepEqual(f.reopen().backupMaintenance().lookup(input.request_key),record);
});
