import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import Database from 'better-sqlite3';
import {createInstallationStore,openInstallationStore} from '../dist/installation-store.mjs';
import {artifactFixture,zipFixture,digestValue} from './fixtures/artifact-package.mjs';
import {authorizeFixture,openReleaseFixture,releaseRepository,initializeReleaseFixture} from './fixtures/release-authorization.mjs';
import {decodeArtifactDocument} from '../dist/sdk/artifact-import.mjs';
import {installationContentPlatform,installationObservationTick} from '../dist/local-peer.mjs';
import {withPreparedContent} from '../dist/prepared-content.mjs';
async function fixture(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-content-')),data=path.join(root,'data');fs.mkdirSync(data);createInstallationStore(data);
  let store=openInstallationStore(data),authorized;const jobs=[];
  t.after(async()=>{await Promise.allSettled(jobs);authorized?.session.close();store.close();assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});});
  const artifact=artifactFixture(),bytes=zipFixture(artifact.entries()).bytes;authorized=await authorizeFixture(store,bytes,digestValue(artifact.manifest));
  const request={identity:{host_installation_id:store.identity.host_installation_id,client_registration_id:'client.synthetic',import_request_id:'request.synthetic'},
    target_authority_service_id:'controller.synthetic',source_attachment_id:'source.synthetic',package_digest:authorized.result.body.package_digest,package_bytes:String(bytes.length),
    expected_manifest_digest:digestValue(artifact.manifest),host_trust_epoch:'1',release_authorization_ref:authorized.result.reference,validation_policy_ref:authorized.validationPolicy.reference};
  store.recordAcceptedImport(request);const source=path.join(root,'source.zip');fs.writeFileSync(source,bytes);const fd=fs.openSync(source,'r');
  try{await store.copyImport(request.identity,fd);}finally{fs.closeSync(fd);}await store.validateImport(request.identity);
  const options={reader_sids:['S-1-1-0'],release_authorization_ref:authorized.result.reference};
  return {root,data,artifact,request,options,get store(){return store;},prepare(value=options){const job=store.prepareMaterialization(request.identity,value);jobs.push(job);return job;},
    seal(value){const job=store.sealImport(request.identity,value);jobs.push(job);return job;},
    async renewTrust(){const release=authorized.release;authorized.session.close();const opened=await openReleaseFixture(store,release);
      authorized={...opened,release,result:await opened.authorize()};return authorized.result.reference;},
    reopen(){authorized.session.close();store.close();store=openInstallationStore(data);}};
}
test('固定内容句柄只读原库存文件且受字节预算和同步作用域限制',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t);assert.equal((await f.prepare()).status,'prepared');let borrowed;
  const value=withPreparedContent(path.join(f.data,'content'),f.store.preparedArtifact(f.request.identity),f.store.validatedArtifact(f.request.identity),(description,flushed,read)=>{
    borrowed=read;assert.throws(()=>read('not-in-inventory.json',1048576));assert.throws(()=>read('payload/config.json',1));
    return read('payload/config.json',1048576);
  });
  assert.deepEqual(value,f.artifact.payload.get('config').bytes);assert.throws(()=>borrowed('payload/config.json',1048576));
});

test('实际库存复制到新内容根并核显式ACL、字节和文件sync，持久结果仍不授sealed',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),prepared=await f.prepare();assert.equal(prepared.status,'prepared',JSON.stringify(prepared));
  const original=f.store.preparedArtifact(f.request.identity);assert.equal(original.body.root_identity.length,48);assert.equal(original.body.directory_durability,'unqualified');
  const storage=original.body.storage_identity;
  assert.equal(storage.format,'windows-content-volume/1');assert.match(storage.volume_guid_path,/^\\\\\?\\Volume\{[0-9a-f-]{36}\}\\$/i);
  assert.ok(storage.filesystem.length>0);assert.match(storage.filesystem_serial,/^[0-9]+$/);
  assert.equal(storage.file_id_volume_serial,original.body.root_identity.slice(0,16));
  assert.ok(BigInt(storage.bytes_per_sector)>0n&&BigInt(storage.sectors_per_allocation_unit)>0n);
  const flushed=original.body.metadata_flush;
  assert.equal(flushed.format,'windows-content-flush/1');assert.equal(flushed.method,'FlushFileBuffers');assert.equal(flushed.completed,true);
  assert.equal(flushed.file_count,5);assert.equal(flushed.directory_count,2);assert.equal(flushed.order,'files_then_directories_bottom_up_then_parent');
  assert.match(flushed.parent_identity,/^[0-9a-f]{48}$/);assert.notEqual(flushed.parent_identity,original.body.root_identity);
  assert.equal(flushed.parent_identity.slice(0,16),original.body.root_identity.slice(0,16));
  for(const file of f.artifact.payload.values())assert.deepEqual(fs.readFileSync(path.join(original.content_directory,file.path)),file.bytes);
  assert.equal(prepared.body.sealed,false);assert.equal(prepared.body.file_flush_completed,true);assert.equal(f.store.queryImport(f.request.identity).receipt,null);
  assert.deepEqual(await f.prepare(),prepared);assert.equal(f.store.queryImport(f.request.identity).state,'validating');
  f.reopen();assert.deepEqual(f.store.preparedArtifact(f.request.identity),original);
  fs.writeFileSync(path.join(original.content_directory,'payload/main.mjs'),'changed by trusted installer');
  assert.deepEqual(f.store.preparedArtifact(f.request.identity),original); // 历史记录不自称当前实物可用。
  f.store.close();const db=new Database(path.join(f.data,'installation.db'));
  try{for(const table of ['import_preparation_attempt','import_preparation_result'])assert.throws(()=>db.exec('DELETE FROM '+table));}finally{db.close();}
});
test('隔离内容改变或额外文件拒绝物化，沿原operation重新核验后可准备',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),source=f.store.validatedArtifact(f.request.identity).payload_directory,file=path.join(source,'payload/main.mjs'),bytes=fs.readFileSync(file);
  fs.writeFileSync(file,'changed');const mismatch=await f.prepare();assert.equal(mismatch.status,'failed');assert.match(mismatch.body.reason_code,/^content_/);
  assert.throws(()=>f.store.preparedArtifact(f.request.identity),{code:'preparation_unavailable'});
  fs.writeFileSync(file,bytes);const extra=path.join(source,'extra.txt');fs.writeFileSync(extra,'extra');assert.equal((await f.prepare()).status,'failed');fs.unlinkSync(extra);
  assert.equal((await f.prepare()).status,'prepared');assert.equal(f.store.queryImport(f.request.identity).state,'validating');
});
test('取消不等待物化worker，迟到实物不能登记为prepared且旧操作保持取消',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),pending=f.prepare();const cancelled=f.store.cancelImport(f.request.identity);assert.equal(cancelled.state,'cancelled');
  const result=await pending;assert.equal(result.status,'obsolete');assert.deepEqual(f.store.queryImport(f.request.identity),cancelled);
  assert.throws(()=>f.store.preparedArtifact(f.request.identity),{code:'preparation_unavailable'});
});
test('父目录允许普通主体写入时拒绝创建内容根，不将不安全ACL当作保护',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),parent=path.join(f.data,'content');
  const command=spawnSync('icacls.exe',[parent,'/grant','*S-1-1-0:(OI)(CI)M'],{encoding:'utf8',windowsHide:true});assert.equal(command.status,0,command.stderr);
  const result=await f.prepare();assert.equal(result.status,'failed');assert.equal(result.body.reason_code,'preparation_parent_acl');assert.equal(fs.readdirSync(parent).length,0);
});

test('原生目录刷新仅作用于固定内容根和父目录，文件写共享失败关闭准备句柄',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),native=installationContentPlatform();
  const root=native.prepareRoot(path.join(f.data,'content'),crypto.randomUUID(),[]);let pin;
  try{
    const description=native.preparedDescribe(root),file=path.join(description.path,'sample.txt');fs.writeFileSync(file,'x');
    native.protectObject(root,'sample.txt',false,true);native.flushPreparedObject(root,'sample.txt',false);
    native.flushPreparedObject(root,'.',true);assert.match(native.flushPreparedParent(root),/^[0-9a-f]{48}$/);
    const inventory=[{file_id:'sample',path:'sample.txt',size_bytes:'1',digest:'sha256:'+crypto.createHash('sha256').update('x').digest('hex'),role:'resource',executable:false}];
    pin=native.contentPin(description.path,inventory);
    assert.throws(()=>native.flushPreparedObject(root,'sample.txt',false),{code:'preparation_flush_open'});
    assert.throws(()=>native.preparedDescribe(root),{code:'preparation_closed'});
    native.contentVerify(pin);
  }finally{if(pin)native.contentClose(pin);native.preparedClose(root);}
});

function qualificationInput(scopeDigest){return {profile_id:'platform.synthetic',approval_reference:'approval.synthetic',
  evidence_digest:digestValue({fixture:'synthetic durability evidence; not platform acceptance'}),scope_digest:scopeDigest};}
test('平台资格显式绑定实际卷和实现，批准及撤销可重启查原，刷新不生成批准',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t);assert.equal((await f.prepare()).status,'prepared');
  let q=f.store.platformQualifications;const observation=q.observe(f.request.identity),input=qualificationInput(observation.scope_digest);
  assert.deepEqual(observation.scope.storage_identity,f.store.preparedArtifact(f.request.identity).body.storage_identity);
  assert.equal(observation.scope.platform,'win32');assert.equal(observation.scope.node_version,process.versions.node);
  assert.throws(()=>q.configure(f.request.identity,{...input,scope_digest:digestValue('wrong scope')}),{code:'platform_qualification_scope'});
  const approved=q.configure(f.request.identity,input);assert.equal(approved.reference.kind,'platform_profile');
  assert.deepEqual(q.configure(f.request.identity,input),approved);
  assert.throws(()=>q.configure(f.request.identity,{...input,evidence_digest:digestValue('different evidence')}),{code:'platform_qualification_conflict'});
  assert.deepEqual(q.assertCurrent(f.request.identity,approved.reference),approved);
  assert.equal(f.store.queryImport(f.request.identity).state,'validating');assert.equal(f.store.queryImport(f.request.identity).receipt,null);
  f.reopen();q=f.store.platformQualifications;assert.deepEqual(q.historical(approved.reference),approved);
  assert.deepEqual(q.assertCurrent(f.request.identity,approved.reference),approved);
  assert.throws(()=>q.historical({...approved.reference,database_instance_id:'other.database'}),{code:'platform_qualification'});
  const revoked=q.revoke(input.profile_id,'revoke.synthetic');assert.deepEqual(q.revoke(input.profile_id,'retry.synthetic'),revoked);
  assert.throws(()=>q.assertCurrent(f.request.identity,approved.reference),{code:'platform_qualification_revoked'});
  assert.throws(()=>q.configure(f.request.identity,input),{code:'platform_qualification_revoked'});
  f.reopen();q=f.store.platformQualifications;assert.deepEqual(q.historical(approved.reference),approved);
  assert.throws(()=>q.assertCurrent(f.request.identity,approved.reference),{code:'platform_qualification_revoked'});
  f.store.close();const db=new Database(path.join(f.data,'installation.db'));
  try{for(const table of ['installation_platform_qualification','installation_platform_qualification_revocation']){
    assert.throws(()=>db.exec('DELETE FROM '+table));assert.throws(()=>db.exec('UPDATE '+table+' SET profile_id=profile_id'));
  }}finally{db.close();}
});

test('当前资格核验拒绝内容及ACL漂移，原件保持历史且不会自动修复权限',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t);await f.prepare();const q=f.store.platformQualifications,prepared=f.store.preparedArtifact(f.request.identity);
  const approved=q.configure(f.request.identity,qualificationInput(q.observe(f.request.identity).scope_digest));
  const file=path.join(prepared.content_directory,'payload/main.mjs'),bytes=fs.readFileSync(file);fs.writeFileSync(file,'changed');
  assert.throws(()=>q.assertCurrent(f.request.identity,approved.reference),error=>/^content_/.test(error.code));
  assert.deepEqual(q.historical(approved.reference),approved);fs.writeFileSync(file,bytes);
  assert.deepEqual(q.assertCurrent(f.request.identity,approved.reference),approved);
  const command=spawnSync('icacls.exe',[file,'/grant','*S-1-1-0:M'],{encoding:'utf8',windowsHide:true});assert.equal(command.status,0,command.stderr);
  for(let i=0;i<2;i++)assert.throws(()=>q.assertCurrent(f.request.identity,approved.reference),error=>/^preparation_/.test(error.code));
  assert.deepEqual(q.historical(approved.reference),approved);assert.equal(f.store.queryImport(f.request.identity).receipt,null);
});

test('重开物化根核对原身份，拒绝同名替换且不创建缺失目录',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t);await f.prepare();const prepared=f.store.preparedArtifact(f.request.identity),native=installationContentPlatform();
  const parent=path.join(f.data,'content'),original=prepared.content_directory,backup=original+'.saved';fs.renameSync(original,backup);
  assert.throws(()=>native.reopenPreparedRoot(parent,prepared.preparation_id,prepared.body.reader_sids,prepared.body.root_identity),{code:'preparation_directory'});
  assert.equal(fs.existsSync(original),false);fs.mkdirSync(original);
  assert.throws(()=>native.reopenPreparedRoot(parent,prepared.preparation_id,prepared.body.reader_sids,prepared.body.root_identity),{code:'preparation_identity'});
  fs.rmdirSync(original);fs.renameSync(backup,original);
  assert.ok(f.store.platformQualifications.observe(f.request.identity).scope_digest);
});

async function sealingOptions(f){
  assert.equal((await f.prepare()).status,'prepared');const q=f.store.platformQualifications;
  const approved=q.configure(f.request.identity,qualificationInput(q.observe(f.request.identity).scope_digest));
  return {platform_profile_ref:approved.reference,release_authorization_ref:f.options.release_authorization_ref};
}
test('实际刷新后原子封存，SDK接受完整收据，重启和后续撤销不改写历史',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),options=await sealingOptions(f),filename=path.join(f.store.preparedArtifact(f.request.identity).content_directory,'payload/main.mjs');
  const prepare=Database.prototype.prepare;let heldAtCommit=false;
  const patched=t.mock.method(Database.prototype,'prepare',function(sql){const statement=prepare.call(this,sql);
    if(sql.startsWith('INSERT INTO artifact_intake VALUES')){const run=statement.run;statement.run=function(...args){
      let fd;assert.throws(()=>{try{fd=fs.openSync(filename,'r+');}finally{if(fd!==undefined)fs.closeSync(fd);}});heldAtCommit=true;return run.apply(this,args);};}
    return statement;});
  const pending=f.seal(options);
  assert.equal(f.store.queryImport(f.request.identity).state,'sealing');assert.throws(()=>f.store.close(),{code:'import_copy_in_progress'});
  const status=await pending;patched.mock.restore();assert.equal(heldAtCommit,true);assert.equal(status.state,'sealed');assert.equal(status.receipt.host_trust_epoch,f.store.trustEpoch());
  assert.deepEqual(await decodeArtifactDocument(Buffer.from(JSON.stringify(status)),'ImportStatus'),status);
  const original=f.store.sealedArtifact(f.request.identity);assert.equal(original.receipt.intake_id,status.receipt.intake_id);
  assert.equal(original.verification.metadata_flush.completed,true);
  assert.equal(original.verification.preparation_id,f.store.preparedArtifact(f.request.identity).preparation_id);
  assert.deepEqual(f.store.cancelImport(f.request.identity),status);assert.deepEqual(await f.seal(options),status);
  f.reopen();assert.deepEqual(f.store.queryImport(f.request.identity),status);assert.deepEqual(f.store.sealedArtifact(f.request.identity),original);
  f.store.platformQualifications.revoke(options.platform_profile_ref.object_id,'after.sealed');
  assert.equal(f.store.advanceTrustEpoch({expected_epoch:'1',operation_id:'epoch.synthetic'}),'2');
  assert.equal(f.store.advanceTrustEpoch({expected_epoch:'1',operation_id:'epoch.synthetic'}),'2');
  assert.throws(()=>f.store.advanceTrustEpoch({expected_epoch:'2',operation_id:'epoch.synthetic'}),{code:'import_identity_conflict'});
  fs.unlinkSync(path.join(f.store.preparedArtifact(f.request.identity).content_directory,'payload/main.mjs'));
  assert.deepEqual(f.store.queryImport(f.request.identity),status);assert.deepEqual(await f.seal(options),status);
  f.reopen();assert.equal(f.store.trustEpoch(),'2');assert.deepEqual(f.store.sealedArtifact(f.request.identity),original);
  f.store.close();const db=new Database(path.join(f.data,'installation.db'));try{
    assert.equal(db.prepare('SELECT count(*) FROM artifact_intake').pluck().get(),1);
    assert.equal(db.prepare('SELECT count(*) FROM import_seal_verification').pluck().get(),1);
    for(const table of ['import_sealing_attempt','import_seal_verification','artifact_intake','installation_trust_epoch'])assert.throws(()=>db.exec('DELETE FROM '+table));
  }finally{db.close();}
});
test('取消先于封存提交则保持取消且没有收据，worker资源回收后可以关闭',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),options=await sealingOptions(f),pending=f.seal(options);
  const cancelled=f.store.cancelImport(f.request.identity);assert.equal(cancelled.state,'cancelled');
  assert.deepEqual(await pending,cancelled);assert.deepEqual(await f.seal(options),cancelled);
  f.reopen();assert.deepEqual(f.store.queryImport(f.request.identity),cancelled);
  assert.throws(()=>f.store.sealedArtifact(f.request.identity),{code:'intake_unavailable'});
});
test('封存期间的平台撤销与宿主信任代变化均阻止收据提交',{skip:process.platform!=='win32',timeout:20000},async t=>{
  for(const kind of ['platform','epoch']){
    const f=await fixture(t),options=await sealingOptions(f),pending=f.seal(options);
    if(kind==='platform')f.store.platformQualifications.revoke(options.platform_profile_ref.object_id,'during.sealing');
    else f.store.advanceTrustEpoch({expected_epoch:'1',operation_id:'during.sealing'});
    const status=await pending;assert.equal(status.state,'rejected');assert.equal(status.reason_code,'trust_denied');assert.equal(status.receipt,null);
    assert.throws(()=>f.store.sealedArtifact(f.request.identity),{code:'intake_unavailable'});
  }
});
test('宿主信任代来自持久库，拒绝调用者在新操作中自报其他代',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t);assert.equal(f.store.trustEpoch(),'1');
  const request=structuredClone(f.request);request.identity.import_request_id='other.request';request.host_trust_epoch='2';
  assert.throws(()=>f.store.recordAcceptedImport(request),{code:'import_trust_epoch'});
  f.store.advanceTrustEpoch({expected_epoch:'1',operation_id:'epoch.before.seal'});
  const options=await sealingOptions(f);await assert.rejects(f.seal(options),{code:'import_trust_epoch'});
  assert.equal(f.store.queryImport(f.request.identity).state,'validating');
});
test('收据写入故障回滚整个封存事务，重开后沿原操作和新发行授权恢复',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),options=await sealingOptions(f),prepare=Database.prototype.prepare;
  const patched=t.mock.method(Database.prototype,'prepare',function(sql){const statement=prepare.call(this,sql);
    if(sql.startsWith('INSERT INTO artifact_intake VALUES')){const run=statement.run;statement.run=function(...args){run.apply(this,args);throw new Error('synthetic intake write interruption');};}
    return statement;});
  await assert.rejects(f.seal(options),{code:'installation_storage_unknown'});patched.mock.restore();
  assert.throws(()=>f.store.queryImport(f.request.identity),{code:'installation_unavailable'});
  f.reopen();const interrupted=f.store.queryImport(f.request.identity);assert.equal(interrupted.state,'sealing');assert.equal(interrupted.receipt,null);
  const release=await f.renewTrust(),completed=await f.seal({...options,release_authorization_ref:release});
  assert.equal(completed.state,'sealed');assert.equal(completed.operation_id,interrupted.operation_id);
  assert.deepEqual(completed.receipt.release_authorization_ref,release);f.reopen();assert.deepEqual(f.store.queryImport(f.request.identity),completed);
});

function materializationRequest(status){return {intake_id:status.receipt.intake_id,target_authority_service_id:status.target_authority_service_id,
  manifest_digest:status.receipt.manifest_digest,artifact_set_digest:status.receipt.artifact_set_digest,host_trust_epoch:status.receipt.host_trust_epoch,
  challenge_id:'challenge.synthetic',launch_intent_digest:digestValue('synthetic launch intent')};}
test('当前物化观察核真实内容并回显完整挑战，原生时钟观察域在重开后更换',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),status=await f.seal(await sealingOptions(f)),request=materializationRequest(status);
  const query={intake_id:request.intake_id,target_authority_service_id:request.target_authority_service_id};
  assert.deepEqual(await f.store.queryIntake(query),{intake_id:query.intake_id,status:'available',receipt:status.receipt});
  const before=installationObservationTick(),mutable=structuredClone(request),pending=f.store.verifyMaterialization(mutable);mutable.challenge_id='mutated';
  const result=await pending,after=installationObservationTick();assert.equal(result.result,'verified');assert.deepEqual(result.request,request);
  assert.ok(BigInt(result.observed_tick)>=before&&BigInt(result.observed_tick)<=after);
  assert.equal(result.observer_domain.descriptor_digest,digestValue(f.store.materializationClock()));
  assert.deepEqual(await decodeArtifactDocument(Buffer.from(JSON.stringify(result)),'MaterializationResult'),result);
  const mismatch=await f.store.verifyMaterialization({...request,manifest_digest:digestValue('wrong')});assert.equal(mismatch.result,'mismatch');assert.equal(mismatch.evidence_id,null);
  const unknown=await f.store.verifyMaterialization({...request,intake_id:'unknown'});assert.equal(unknown.result,'unavailable');assert.equal(unknown.evidence_id,null);
  f.reopen();assert.notEqual(f.store.materializationClock().clock_domain_id,result.observer_domain.clock_domain_id);
  assert.equal((await f.store.queryIntake(query)).status,'unavailable'); // 旧发行会话不能跨进程当作当前授权。
  const renewed=await f.renewTrust();assert.notDeepEqual(renewed,status.receipt.release_authorization_ref);
  assert.deepEqual(await f.store.queryIntake(query),{intake_id:query.intake_id,status:'available',receipt:status.receipt});
  assert.deepEqual(f.store.queryImport(f.request.identity),status);
});

test('物化查询发现内容漂移或资格撤销即不可用，历史sealed保持不变',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),options=await sealingOptions(f),status=await f.seal(options),request=materializationRequest(status);
  const file=path.join(f.store.preparedArtifact(f.request.identity).content_directory,'payload/main.mjs'),bytes=fs.readFileSync(file);
  fs.writeFileSync(file,'tampered');const changed=await f.store.verifyMaterialization(request);assert.equal(changed.result,'unavailable');assert.equal(changed.evidence_id,null);
  assert.equal((await f.store.queryIntake({intake_id:request.intake_id,target_authority_service_id:request.target_authority_service_id})).receipt,null);
  fs.writeFileSync(file,bytes);assert.equal((await f.store.verifyMaterialization(request)).result,'verified');
  f.store.platformQualifications.revoke(options.platform_profile_ref.object_id,'revoke.observation');
  assert.equal((await f.store.verifyMaterialization(request)).result,'unavailable');assert.deepEqual(f.store.queryImport(f.request.identity),status);
});

test('加载内容交接持有实际文件句柄，容量有界且释放后借出的资格失效',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),status=await f.seal(await sealingOptions(f)),query={intake_id:status.receipt.intake_id,target_authority_service_id:status.target_authority_service_id};
  const holds=[];
  try{
    for(let i=0;i<4;i++)holds.push(await f.store.acquireMaterialization(query));
    const held=holds[0];assert.equal(held.status,'available');held.assertCurrent();
    assert.equal(held.content.format,'leafseamer-loader-materialization/1');assert.equal(held.content.intake_ref.digest,digestValue(status.receipt));
    assert.deepEqual(held.content.inventory,f.artifact.inventory);assert.equal(held.content.root.root_identity,f.store.preparedArtifact(f.request.identity).body.root_identity);
    assert.equal(BigInt(held.content.lifetime.deadline_tick)-BigInt(held.content.lifetime.issued_tick),4000000000n);
    assert.ok(Object.isFrozen(held.content.root));assert.throws(()=>{held.content.root.path='changed';},TypeError);
    const file=path.join(held.content.root.path,'payload/main.mjs');assert.deepEqual(fs.readFileSync(file),f.artifact.payload.get('worker').bytes);
    assert.throws(()=>fs.writeFileSync(file,'replacement'));assert.throws(()=>fs.renameSync(file,file+'.moved'));
    await assert.rejects(f.store.acquireMaterialization(query),{code:'materialization_capacity'});
    assert.throws(()=>f.store.close(),{code:'import_copy_in_progress'});
  }finally{assert.ok((await Promise.all(holds.map(held=>held.close()))).every(value=>value.status==='released'));}
  for(const held of holds)assert.throws(()=>held.assertCurrent(),{code:'materialization_hold_closed'});
  const file=path.join(holds[0].content.root.path,'payload/main.mjs');fs.writeFileSync(file,f.artifact.payload.get('worker').bytes);
});

test('加载交接等待中的平台、策略与信任撤销均立即使当前断言失败并释放句柄',{skip:process.platform!=='win32',timeout:30000},async t=>{
  for(const kind of ['platform','policy','epoch']){
    const f=await fixture(t),options=await sealingOptions(f),status=await f.seal(options),query={intake_id:status.receipt.intake_id,target_authority_service_id:status.target_authority_service_id};
    const held=await f.store.acquireMaterialization(query);assert.equal(held.status,'available');
    try{
      if(kind==='platform')f.store.platformQualifications.revoke(options.platform_profile_ref.object_id,'revoke.hold');
      else if(kind==='policy')f.store.validationPolicies.revoke(f.request.validation_policy_ref.object_id,'revoke.hold');
      else f.store.advanceTrustEpoch({expected_epoch:'1',operation_id:'revoke.hold'});
      assert.throws(()=>held.assertCurrent());assert.equal((await held.closed).status,'invalidated');
      assert.equal((await f.store.acquireMaterialization(query)).status,'unavailable');
      assert.deepEqual(f.store.queryImport(f.request.identity),status);
    }finally{await held.close();}
  }
});

test('加载交接固定截止后自动失效，保留路径副本不能延长原句柄持有',{skip:process.platform!=='win32',timeout:15000},async t=>{
  const f=await fixture(t),status=await f.seal(await sealingOptions(f)),query={intake_id:status.receipt.intake_id,target_authority_service_id:status.target_authority_service_id};
  const held=await f.store.acquireMaterialization(query),file=path.join(held.content.root.path,'payload/main.mjs');
  try{assert.throws(()=>fs.writeFileSync(file,'replacement'));const ended=await held.closed;
    assert.equal(ended.status,'invalidated');assert.match(ended.code,/materialization_timeout|materialization_hold_closed/);
    assert.throws(()=>held.assertCurrent(),{code:'materialization_hold_closed'});fs.writeFileSync(file,f.artifact.payload.get('worker').bytes);
  }finally{await held.close();}
});

test('当前校验策略与宿主信任代失效不能继续出具verified',{skip:process.platform!=='win32',timeout:20000},async t=>{
  for(const kind of ['policy','epoch']){
    const f=await fixture(t),status=await f.seal(await sealingOptions(f)),request=materializationRequest(status);
    const pending=f.store.verifyMaterialization(request);
    if(kind==='policy')f.store.validationPolicies.revoke(f.request.validation_policy_ref.object_id,'revoked.observation');
    else f.store.advanceTrustEpoch({expected_epoch:'1',operation_id:'new.observation.epoch'});
    assert.equal((await pending).result,'unavailable');assert.deepEqual(f.store.queryImport(f.request.identity),status);
  }
});

test('相同包在另一信任域获批不能替代封存原信任域的当前授权',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await fixture(t),status=await f.seal(await sealingOptions(f)),request=materializationRequest(status);f.reopen();
  const release=releaseRepository(fs.readFileSync(path.join(f.root,'source.zip')),digestValue(f.artifact.manifest));
  initializeReleaseFixture(f.store,release.repo,'other.synthetic');const opened=await openReleaseFixture(f.store,release,{domain:'other.synthetic'});
  try{await opened.authorize();assert.equal((await f.store.verifyMaterialization(request)).result,'unavailable');
    assert.deepEqual(f.store.queryImport(f.request.identity),status);
  }finally{opened.session.close();}
});
