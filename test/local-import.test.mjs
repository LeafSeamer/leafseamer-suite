import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {spawn,spawnSync} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import Database from 'better-sqlite3';
import {createInstallationStore,openInstallationStore} from '../dist/installation-store.mjs';
import {captureInstallationPeer,createInstallationChannel} from '../dist/local-peer.mjs';
import {serveInstallationClient,createInstallationClient} from '../dist/local-import.mjs';
import {authorizeFixture} from './fixtures/release-authorization.mjs';
import {rawHash} from './fixtures/tuf-repository.mjs';
import {artifactFixture,zipFixture,digestValue} from './fixtures/artifact-package.mjs';
async function prepare(t,{permissions=['import.query','import.cancel'],targets=['controller.synthetic'],fresh=false,payloadBytes=0,readerSids=[],seal=false,role='management_tool'}={}){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-local-import-'));createInstallationStore(root);let store=openInstallationStore(root),service;
  const child=spawn(process.execPath,[fileURLToPath(new URL('./fixtures/installation-client-child.mjs',import.meta.url))],{stdio:['ignore','pipe','pipe','ipc'],windowsHide:true}),ended=once(child,'close');
  let authorization;
  t.after(async()=>{service?.close();await service?.done.catch(()=>{});authorization?.session.close();if(child.exitCode===null&&child.signalCode===null)child.kill();await ended;store.close();assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});});
  await once(child,'message');
  const fixture=artifactFixture();
  if(payloadBytes){const bytes=Buffer.alloc(payloadBytes,59);fixture.payload.get('worker').bytes=bytes;
    Object.assign(fixture.inventory.files.find(f=>f.file_id==='worker'),{size_bytes:String(bytes.length),digest:rawHash(bytes)});fixture.manifest.inventory_digest=digestValue(fixture.inventory);}
  const archive=zipFixture(fixture.entries()),bytes=fresh?archive.bytes:Buffer.from('synthetic archive');
  const peer=captureInstallationPeer(child.pid),authorized=authorization=await authorizeFixture(store,bytes,fresh?digestValue(fixture.manifest):rawHash(Buffer.from('manifest')));
  const identity={host_installation_id:store.identity.host_installation_id,client_registration_id:'client.synthetic',import_request_id:'request.synthetic'};
  const input={identity,target_authority_service_id:'controller.synthetic',source_attachment_id:'attachment.synthetic',host_trust_epoch:'1',
    package_digest:authorized.result.body.package_digest,package_bytes:authorized.result.body.package_bytes,expected_manifest_digest:authorized.result.body.expected_manifest_digest,
    release_authorization_ref:authorized.result.reference,validation_policy_ref:authorized.validationPolicy.reference};
  if(!fresh)try{store.recordAcceptedImport(input);}finally{authorized.session.close();}
  let platformProfileRef=null;
  if(seal){
    const seed={...input,identity:{...identity,import_request_id:'qualification.seed'}},filename=path.join(root,'qualification.zip');fs.writeFileSync(filename,bytes);
    store.recordAcceptedImport(seed);const fd=fs.openSync(filename,'r');try{await store.copyImport(seed.identity,fd);}finally{fs.closeSync(fd);}
    await store.validateImport(seed.identity);assert.equal((await store.prepareMaterialization(seed.identity,{reader_sids:readerSids,release_authorization_ref:authorized.result.reference})).status,'prepared');
    const observed=store.platformQualifications.observe(seed.identity);
    platformProfileRef=store.platformQualifications.configure(seed.identity,{profile_id:'platform.synthetic',approval_reference:'approval.synthetic',
      evidence_digest:digestValue('synthetic qualification only'),scope_digest:observed.scope_digest}).reference;
    store.cancelImport(seed.identity);
    if(role!=='management_tool'){
      store.recordAcceptedImport(input);const fd=fs.openSync(filename,'r');try{await store.copyImport(input.identity,fd);}finally{fs.closeSync(fd);}
      await store.validateImport(input.identity);await store.prepareMaterialization(input.identity,{reader_sids:readerSids,release_authorization_ref:authorized.result.reference});
      assert.equal((await store.sealImport(input.identity,{platform_profile_ref:platformProfileRef,release_authorization_ref:authorized.result.reference})).state,'sealed');
    }
  }
  const policy={client_registration_id:'client.synthetic',role,user_sid:peer.descriptor.user_sid,target_authority_service_ids:targets,permissions,approval_reference:'approval.synthetic'};
  store.registerClient(policy);assert.throws(()=>store.registerClient({...policy,approval_reference:'other'}),{code:'import_client_conflict'});
  const channelId=crypto.randomUUID(),name='\\\\.\\pipe\\LeafSeamer.Install.'+crypto.randomUUID();
  const channel=createInstallationChannel({name,peer,server:true});service=serveInstallationClient({store,registration_id:'client.synthetic',channel_id:channelId,channel,validation_policy_ref:input.validation_policy_ref,reader_sids:readerSids,platform_profile_ref:platformProfileRef});
  const call=message=>new Promise((resolve,reject)=>{const request=crypto.randomUUID(),timer=setTimeout(()=>{child.off('message',received);reject(new Error('fixture_timeout'));},6000);
    function received(reply){if(reply.request===request){clearTimeout(timer);child.off('message',received);resolve(reply);}}child.on('message',received);child.send({...message,request});});
  assert.equal((await call({type:'connect',name,server_pid:process.pid,channel_id:channelId})).type,'connected');
  return {identity,input,bytes,root,service,call,channelId,platformProfileRef,get store(){return store;},async reopen(){service.close();await service.done.catch(()=>{});authorization.session.close();store.close();store=openInstallationStore(root);}};
}

test('可信服务配置的平台资格驱动真实IPC导入到sealed，查询与取消返回同一收据',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await prepare(t,{fresh:true,seal:true,permissions:['import.begin','import.query','import.cancel']}),filename=path.join(f.root,'source.zip');
  fs.writeFileSync(filename,f.bytes);f.platformProfileRef.object_id='caller.mutation';
  const attachment=(await f.call({type:'attach',filename})).result,input={...f.input,...attachment};
  const started=(await f.call({type:'begin',input})).result.status;assert.equal(started.state,'accepted');
  const deadline=performance.now()+6000;let status;
  for(;;){status=(await f.call({type:'query',identity:f.identity})).result.status;if(status.state==='sealed')break;
    assert.ok(['accepted','copying','validating','sealing'].includes(status.state),JSON.stringify(status));assert.ok(performance.now()<deadline);await new Promise(resolve=>setTimeout(resolve,10));}
  assert.equal(status.operation_id,started.operation_id);assert.equal(status.receipt.platform_profile_ref.object_id,'platform.synthetic');
  assert.deepEqual((await f.call({type:'cancel',identity:f.identity})).result.status,status);
  assert.deepEqual((await f.call({type:'begin',input:{...input,source_attachment_id:'old.attachment'}})).result.status,status);
  assert.equal((await f.call({type:'queryIntake',input:{intake_id:status.receipt.intake_id,target_authority_service_id:status.target_authority_service_id}})).result.error.code,'unauthorized_peer');
  await f.reopen();assert.deepEqual(f.store.queryImport(f.identity),status);
});

test('实际协调者IPC核当前intake并绑定完整挑战，跨目标与管理操作拒绝',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await prepare(t,{fresh:true,seal:true,role:'launch_coordinator',permissions:['intake.query','materialization.verify']});
  const sealed=f.store.queryImport(f.identity),query={intake_id:sealed.receipt.intake_id,target_authority_service_id:sealed.target_authority_service_id};
  const result=(await f.call({type:'queryIntake',input:query})).result.result;assert.equal(result.status,'available');assert.deepEqual(result.receipt,sealed.receipt);
  assert.equal((await f.call({type:'queryIntake',input:{...query,target_authority_service_id:'other.authority'}})).result.error.code,'not_found_or_invisible');
  const request={...query,manifest_digest:sealed.receipt.manifest_digest,artifact_set_digest:sealed.receipt.artifact_set_digest,
    host_trust_epoch:sealed.receipt.host_trust_epoch,challenge_id:'challenge.synthetic',launch_intent_digest:digestValue('synthetic intent')};
  const observed=(await f.call({type:'verifyMaterialization',input:request})).result.result;
  assert.equal(observed.result,'verified');assert.deepEqual(observed.request,request);assert.ok(observed.evidence_id);
  assert.equal((await f.call({type:'cancel',identity:f.identity})).result.error.code,'unauthorized_peer');
  f.store.advanceTrustEpoch({expected_epoch:'1',operation_id:'ipc.observer.epoch'});
  assert.equal((await f.call({type:'queryIntake',input:query})).result.result.status,'unavailable');
  assert.equal((await f.call({type:'verifyMaterialization',input:request})).result.result.result,'unavailable');
  assert.deepEqual(f.store.queryImport(f.identity),sealed);
});

test('authority只允许当前intake查询，不能借相同SID取得启动物化权限',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await prepare(t,{fresh:true,seal:true,role:'authority',permissions:['intake.query']}),sealed=f.store.queryImport(f.identity);
  const query={intake_id:sealed.receipt.intake_id,target_authority_service_id:sealed.target_authority_service_id};
  assert.equal((await f.call({type:'queryIntake',input:query})).result.result.status,'available');
  const request={...query,manifest_digest:sealed.receipt.manifest_digest,artifact_set_digest:sealed.receipt.artifact_set_digest,
    host_trust_epoch:sealed.receipt.host_trust_epoch,challenge_id:'challenge.synthetic',launch_intent_digest:digestValue('synthetic intent')};
  assert.equal((await f.call({type:'verifyMaterialization',input:request})).result.error.code,'unauthorized_peer');
  assert.equal((await f.call({type:'queryIntake',input:{...query,intake_id:'unknown'}})).result.result.status,'unavailable');
});

test('客户端拒绝消息关联正确但intake或挑战回显错绑的响应',async()=>{
  for(const kind of ['intake','materialization']){
    let sent,closed=false;const request={intake_id:'intake.synthetic',target_authority_service_id:'authority.synthetic'};
    const input=kind==='intake'?request:{...request,manifest_digest:digestValue('manifest'),artifact_set_digest:digestValue('artifacts'),
      host_trust_epoch:'1',challenge_id:'challenge.synthetic',launch_intent_digest:digestValue('intent')};
    const channel={async send(bytes){sent=JSON.parse(bytes);},async receive(){return Buffer.from(JSON.stringify({ipc_version:'extension-import/0.1.0-draft.1',
      type:kind==='intake'?'INTAKE_RESULT':'MATERIALIZATION_RESULT',channel_id:sent.channel_id,sequence:'1',message_id:'response.synthetic',reply_to:sent.message_id,
      payload:kind==='intake'?{intake_id:'wrong.intake',status:'unavailable',receipt:null}:{request:{...input,challenge_id:'wrong.challenge'},result:'unavailable',
        evidence_id:null,observer_domain:{clock_domain_id:'observer.synthetic',descriptor_digest:digestValue('descriptor')},observed_tick:'1'}}));},close(){closed=true;}};
    const client=createInstallationClient({channel,channel_id:'channel.synthetic'});
    await assert.rejects(kind==='intake'?client.queryIntake(input):client.verifyMaterialization(input),{code:'import_channel_binding'});assert.equal(closed,true);
  }
});

test('真实导入IPC自动推进复制、静态校验及受保护内容准备，重投和断连不重复任务',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const readerSids=[];
  const f=await prepare(t,{fresh:true,permissions:['import.begin','import.query','import.cancel'],readerSids}),filename=path.join(f.root,'source.zip');fs.writeFileSync(filename,f.bytes);
  readerSids.push('S-1-1-0'); // 修改调用者原数组不能扩大已选的本机读取权限。
  const attached=(await f.call({type:'attach',filename})).result;assert.ok(attached.source_attachment_id);
  const input={...f.input,...attached};
  assert.equal((await f.call({type:'begin',input:{...input,validation_policy_ref:{...input.validation_policy_ref,object_id:'untrusted'}}})).result.error.code,'invalid_request');
  assert.equal(f.store.queryImport(f.identity),null);
  assert.equal((await f.call({type:'begin',input:{...input,target_authority_service_id:'another.controller'}})).result.error.code,'unauthorized_peer');
  assert.equal((await f.call({type:'begin',input:{...input,source_attachment_id:'invented'}})).result.error.code,'invalid_request');
  const started=(await f.call({type:'begin',input})).result.status;assert.equal(started.state,'accepted');
  const deadline=performance.now()+3000;
  for(;;){try{f.store.validatedArtifact(f.identity);break;}catch{assert.ok(performance.now()<deadline);await new Promise(resolve=>setTimeout(resolve,10));}}
  const original=(await f.call({type:'begin',input:{...input,source_attachment_id:'old.attachment'}})).result.status;
  assert.equal(original.operation_id,started.operation_id);assert.equal(original.state,'validating');
  assert.equal((await f.call({type:'begin',input:{...input,package_digest:rawHash(Buffer.from('different'))}})).result.error.code,'identity_conflict');
  // close会等待本连接已受理的静态任务结束，查询和取消没有排在复制后面。
  f.service.close();await f.service.done;
  assert.equal(f.store.queryImport(f.identity).state,'validating');
  assert.equal(f.store.validatedArtifact(f.identity).report.package_digest,input.package_digest);
  const prepared=f.store.preparedArtifact(f.identity),validated=f.store.validatedArtifact(f.identity);
  assert.deepEqual(prepared.body.reader_sids,[]);assert.equal(prepared.body.sealed,false);assert.equal(prepared.body.directory_durability,'unqualified');
  for(const file of validated.report.inventory.files)assert.equal(rawHash(fs.readFileSync(path.join(prepared.content_directory,...file.path.split('/')))),file.digest);
  assert.equal(f.store.queryImport(f.identity).receipt,null);assert.equal(globalThis.archiveExecuted,undefined);
  await f.reopen();assert.equal(f.store.queryImport(f.identity).operation_id,started.operation_id);assert.deepEqual(f.store.preparedArtifact(f.identity),prepared);
  f.store.close();const db=new Database(path.join(f.root,'installation.db'));
  try{assert.equal(db.prepare('SELECT count(*) FROM import_copy_attempt').pluck().get(),1);assert.equal(db.prepare('SELECT count(*) FROM import_preparation_attempt').pluck().get(),1);}
  finally{db.close();}
});

test('IPC沿已有静态校验的原operation继续内容准备，无需重传附件或重建导入',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await prepare(t,{fresh:true,permissions:['import.begin','import.query']}),filename=path.join(f.root,'source.zip');fs.writeFileSync(filename,f.bytes);
  const original=f.store.recordAcceptedImport(f.input),fd=fs.openSync(filename,'r');
  try{await f.store.copyImport(f.identity,fd);}finally{fs.closeSync(fd);}
  await f.store.validateImport(f.identity);
  assert.throws(()=>f.store.preparedArtifact(f.identity),{code:'preparation_unavailable'});
  const resumed=(await f.call({type:'begin',input:{...f.input,source_attachment_id:'not.retransmitted'}})).result.status;
  assert.equal(resumed.operation_id,original.operation_id);assert.equal(resumed.state,'validating');
  f.service.close();await f.service.done;
  assert.equal(f.store.preparedArtifact(f.identity).body.sealed,false);
  assert.equal(f.store.queryImport(f.identity).operation_id,original.operation_id);
});

test('内容准备已创建目标目录时IPC取消仍独立执行，迟到worker不能提交prepared',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await prepare(t,{fresh:true,payloadBytes:32*1024*1024,permissions:['import.begin','import.query','import.cancel']}),filename=path.join(f.root,'source.zip');fs.writeFileSync(filename,f.bytes);
  const attached=(await f.call({type:'attach',filename})).result,input={...f.input,...attached};
  assert.equal((await f.call({type:'begin',input})).result.status.state,'accepted');
  const deadline=performance.now()+6000;
  while(fs.readdirSync(path.join(f.root,'content')).length===0){assert.ok(performance.now()<deadline);await new Promise(resolve=>setTimeout(resolve,1));}
  const reply=await f.call({type:'cancel',identity:f.identity});assert.ok(reply.result?.status,JSON.stringify(reply));
  const cancelled=reply.result.status;assert.equal(cancelled.state,'cancelled');
  f.service.close();await f.service.done;
  assert.deepEqual(f.store.queryImport(f.identity),cancelled);
  assert.throws(()=>f.store.preparedArtifact(f.identity),{code:'preparation_unavailable'});
  await f.reopen();assert.deepEqual(f.store.queryImport(f.identity),cancelled);
});

test('自动准备遇到不安全父目录时保留失败原件并释放后台任务，不冒充准备成功',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await prepare(t,{fresh:true,permissions:['import.begin','import.query']}),filename=path.join(f.root,'source.zip');fs.writeFileSync(filename,f.bytes);
  const changed=spawnSync('icacls.exe',[path.join(f.root,'content'),'/grant','*S-1-1-0:(OI)(CI)M'],{encoding:'utf8',windowsHide:true});assert.equal(changed.status,0,changed.stderr);
  const attached=(await f.call({type:'attach',filename})).result;
  assert.equal((await f.call({type:'begin',input:{...f.input,...attached}})).result.status.state,'accepted');
  f.service.close();await f.service.done;
  assert.equal(f.store.queryImport(f.identity).state,'validating');assert.throws(()=>f.store.preparedArtifact(f.identity),{code:'preparation_unavailable'});
  await f.reopen();f.store.close();const db=new Database(path.join(f.root,'installation.db'));
  try{
    const [status,body]=db.prepare('SELECT status,body FROM import_preparation_result').raw().get();
    assert.equal(status,'failed');assert.equal(JSON.parse(body).reason_code,'preparation_parent_acl');
  }finally{db.close();}
});

test('实际导入任务不阻塞取消，迟到复制或校验结果不能覆盖持久取消',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await prepare(t,{fresh:true,payloadBytes:8*1024*1024,permissions:['import.begin','import.query','import.cancel']}),filename=path.join(f.root,'source.zip');fs.writeFileSync(filename,f.bytes);
  const attached=(await f.call({type:'attach',filename})).result,input={...f.input,...attached};
  assert.equal((await f.call({type:'begin',input})).result.status.state,'accepted');
  const reply=await f.call({type:'cancel',identity:f.identity});assert.ok(reply.result?.status,JSON.stringify(reply));
  const cancelled=reply.result.status;assert.equal(cancelled.state,'cancelled');
  f.service.close();await f.service.done;assert.deepEqual(f.store.queryImport(f.identity),cancelled);
  await f.reopen();assert.deepEqual(f.store.queryImport(f.identity),cancelled);
});

test('附件权限、容量、可写文件及伪造句柄被拒绝，拒绝不创建导入',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const limited=await prepare(t,{fresh:true}),filename=path.join(limited.root,'source.zip');fs.writeFileSync(filename,limited.bytes);
  assert.equal((await limited.call({type:'attach',filename})).result.error,'source_attachment_rejected');
  assert.equal(limited.store.queryImport(limited.identity),null);
  const f=await prepare(t,{fresh:true,permissions:['import.begin','import.query']}),source=path.join(f.root,'source.zip');fs.writeFileSync(source,f.bytes);
  const invalid=Buffer.alloc(9);invalid.writeBigUInt64LE(0xffffffffffffffffn,1);
  assert.deepEqual(Buffer.from((await f.call({type:'raw',bytes:invalid.toString('base64'),encoding:'base64'})).bytes,'base64'),Buffer.from([0,0]));
  for(let i=0;i<8;i++)assert.ok((await f.call({type:'attach',filename:source})).result.source_attachment_id);
  assert.equal((await f.call({type:'attach',filename:source})).result.error,'source_attachment_rejected');
  assert.equal((await f.call({type:'attach',filename:source,mode:'r+'})).error,'peer_source_read_only');
  await assert.rejects(f.service.done);assert.equal(f.store.queryImport(f.identity),null);
});
test('实际注册工具经SDK帧查询和取消同一安装操作，结果与SQLite原件一致',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const f=await prepare(t);
  assert.equal((await f.call({type:'query',identity:f.identity})).result.status.state,'accepted');
  const reply=await f.call({type:'cancel',identity:f.identity});assert.ok(reply.result?.status,JSON.stringify(reply));
  const cancelled=reply.result.status;assert.equal(cancelled.state,'cancelled');
  assert.deepEqual((await f.call({type:'cancel',identity:f.identity})).result.status,cancelled);
  assert.deepEqual(f.store.queryImport(f.identity),cancelled);
  assert.equal((await f.call({type:'query',identity:{...f.identity,client_registration_id:'self.claimed'}})).result.error.code,'unauthorized_peer');
  await f.reopen();assert.deepEqual(f.store.queryImport(f.identity),cancelled);
});
test('当前目标范围与取消权限逐请求核验，注册撤销主动关闭连接并永久保留',{skip:process.platform!=='win32',timeout:20000},async t=>{
  const limited=await prepare(t,{permissions:['import.query']});
  assert.equal((await limited.call({type:'cancel',identity:limited.identity})).result.error.code,'unauthorized_peer');
  assert.equal(limited.store.queryImport(limited.identity).state,'accepted');
  const result=limited.store.revokeClient('client.synthetic','revoke.synthetic');assert.equal(result.operation_id,'revoke.synthetic');
  await assert.rejects(limited.service.done);assert.ok((await limited.call({type:'query',identity:limited.identity})).error);
  await limited.reopen();assert.deepEqual(limited.store.revokeClient('client.synthetic','ignored.retry'),result);
  const scoped=await prepare(t,{targets:['another.controller']});
  assert.equal((await scoped.call({type:'query',identity:scoped.identity})).result.error.code,'not_found_or_invisible');
  assert.equal(scoped.store.queryImport(scoped.identity).state,'accepted');
});
test('管道实际来源正确也拒绝重放序号和错通道，协议故障不更改业务状态',{skip:process.platform!=='win32',timeout:20000},async t=>{
  for(const fault of ['replay','channel']){
    const f=await prepare(t),packet={ipc_version:'extension-import/0.1.0-draft.1',type:'IMPORT_QUERY',channel_id:f.channelId,
      sequence:'1',message_id:crypto.randomUUID(),reply_to:null,payload:f.identity};
    if(fault==='replay')assert.equal(JSON.parse((await f.call({type:'raw',bytes:JSON.stringify(packet)})).bytes).type,'IMPORT_STATUS');
    else packet.channel_id='wrong.channel';
    assert.ok((await f.call({type:'raw',bytes:JSON.stringify(packet)})).error);await assert.rejects(f.service.done,{code:'import_channel_binding'});
    assert.equal(f.store.queryImport(f.identity).state,'accepted');
    await f.reopen();f.store.close();const db=new Database(path.join(f.root,'installation.db'));
    try{for(const table of ['installation_client_registration'])assert.throws(()=>db.exec('DELETE FROM '+table));}finally{db.close();}
  }
});
