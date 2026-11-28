import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFile,execFileSync} from 'node:child_process';
import {DatabaseSync} from 'node:sqlite';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {createInstallationStore,openInstallationStore} from '@leafseamer/suite/installation';
import {digest} from '../dist/import-input.mjs';

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
  const {operation,input}=f.request(ledger,name,{coverage_digest:digest(coverage)});
  const ready=await ledger.collectSnapshots(operation.operation_id,1,{authorize,sourceDirectory:()=>f.source});
  assert.equal(ready.step,'snapshots_staged');
  const [{backup_operation_id:id,receipt}]=ledger.snapshots(ready.operation_id);
  const stage=path.join(f.root,'staging','backup-'+ready.operation_id);
  const directory=path.join(stage,'archive'),entry='db/controller.sqlite',report='reports/fixture.json';
  await fs.mkdir(path.join(directory,'files','db'),{recursive:true,mode:0o700});
  await fs.mkdir(path.join(directory,'files','reports'),{mode:0o700});
  await fs.copyFile(path.join(stage,id,'snapshot.partial','data.sqlite'),path.join(directory,'files',entry));
  const verified=Buffer.from('{"fixture":"structural checks passed"}');
  await fs.writeFile(path.join(directory,'files',report),verified,{mode:0o600});
  const reportHash=crypto.createHash('sha256').update(verified).digest('hex');
  const manifest={format:'leafseamer-backup-tar/1',backup_id:ready.operation_id,level:'L2',consistency:'online',
    files:[{role:'database',path:entry,size:receipt.bytes,sha256:receipt.sha256},
      {role:'validation_report',path:report,size:verified.length,sha256:reportHash}],
    databases:[{path:entry,service:receipt.scope.service_id,database_instance:receipt.scope.database_instance_id,
      schema:receipt.scope.schema_revision,engine:receipt.engine,consistency_point:id}],
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
