import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {once} from 'node:events';
import {pathToFileURL} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import canonicalize from 'canonicalize';
import {createInstallationStore,openInstallationStore} from '../dist/installation-store.mjs';
import {captureInstallationPeer,createInstallationChannel} from '../dist/local-peer.mjs';
import {serveInstallationClient} from '../dist/local-import.mjs';
import {authorizeFixture} from './fixtures/release-authorization.mjs';
import {artifactFixture,zipFixture,digestValue} from './fixtures/artifact-package.mjs';

// 显式选定待联调的Controller构建；产品安装包没有邻仓路径依赖。
const controller=process.env.LEAFSEAMER_CONTROLLER_TEST_ROOT;
assert.ok(controller&&path.isAbsolute(controller),'LEAFSEAMER_CONTROLLER_TEST_ROOT必须为已构建Controller的绝对路径');
const Database=createRequire(path.join(controller,'package.json'))('better-sqlite3');
const load=name=>import(pathToFileURL(path.join(controller,'dist',name)));
const {initializeStorage,migrateStorage,openStorage}=await load('storage.mjs');
const {initializeProcessHost,installedCoreDigest}=await load('process-host.mjs');
const {pinLaunchContent}=await load('launch-content.mjs');
const {startAuthenticationClock}=await load('auth-clock.mjs');
const {localIdentityPermissions}=await load('local-permission-store.mjs');
const {bind:bindCore,workerIntent}=await import(pathToFileURL(path.join(controller,'test/fixtures/core-binding.mjs')));
const {fixture:authenticationFixture}=await import(pathToFileURL(path.join(controller,'test/auth-clock-fixture.mjs')));
async function management(storage){
  const fixture=authenticationFixture(storage.authenticationClock.scope),clock=startAuthenticationClock(fixture.source,storage.authenticationClock,fixture.provider,{schedule:false});
  try{
    const sessions=storage.sessions(clock),logged=await sessions.login({login:'role.test',password:'Synthetic-role-password-123'});
    const auth={credential_id:logged.credential_id,secret:logged.secret,csrf:logged.csrf},current=sessions.localPermissions(auth);
    if(!current.permissions.includes('extension.manage'))sessions.replaceLocalPermissions(auth,{request_id:crypto.randomUUID(),principal_id:logged.session.principal_id,
      expected_revision:current.revision,permissions:[...localIdentityPermissions,'extension.manage','extension.read']});
    const issued=sessions.issueToken(auth,{request_id:crypto.randomUUID(),audience:storage.identity.service_id,requested_scopes:['extension.manage','extension.read']});
    return {sessions,clock,token:{token_id:issued.token.token_id,secret:issued.secret}};
  }catch(error){clock.stop();throw error;}
}
async function waitFor(fn){const end=performance.now()+15000;while(!fn()){assert.ok(performance.now()<end,'真实监督器事件等待超时');await delay(20);}return fn();}

for(const mode of ['verified','receipt','observer','challenge','target','peer','revoke_pending','timeout','stage','configuration','roles','review','approval','capability','launch_prepare','load_handoff','load_close','supervisor_load','supervisor_deny','supervisor_bad_root','supervisor_bad_manifest','supervisor_bad_entry','supervisor_create','supervisor_create_exit','supervisor_create_deny_pending','supervisor_create_bad_profile','supervisor_create_runtime','supervisor_create_module','supervisor_create_module_store_fail','supervisor_create_module_store_ignore'])test((['launch_prepare','load_handoff','load_close'].includes(mode)?'安装服务与启动准备联调（合成核心域）：':'安装服务与原生监督器联调：')+mode,{skip:process.platform!=='win32',timeout:30000},async t=>{
  const runtimeMode=['supervisor_create_runtime','supervisor_create_module','supervisor_create_module_store_fail','supervisor_create_module_store_ignore'].includes(mode);let runtimeInput=null;
  const creates=mode.startsWith('supervisor_create')&&mode!=='supervisor_create_bad_profile',loadsSuccessfully=mode==='supervisor_load'||mode==='supervisor_deny'||mode.startsWith('supervisor_create');
  const usesCapabilities=runtimeMode||['capability','launch_prepare','load_handoff','load_close','supervisor_create_runtime'].includes(mode);
  const usesRoles=runtimeMode||['roles','review','approval','capability','launch_prepare','load_handoff','load_close','supervisor_create_runtime'].includes(mode),usesConfiguration=usesRoles||mode==='configuration';
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-materialization-')),install=path.join(root,'install'),core=path.join(root,'core');
  fs.mkdirSync(install);fs.mkdirSync(core);createInstallationStore(install);const store=openInstallationStore(install);
  let service,intakeService,authorized,child,ended,contentPin;const frames=[];let stderr='';
  t.after(async()=>{service?.close();intakeService?.close();await service?.done.catch(()=>{});await intakeService?.done.catch(()=>{});if(child&&child.exitCode===null&&child.signalCode===null)child.kill();await ended;
    await contentPin?.close();authorized?.session.close();store.close();assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});});
  const coreIdentity=initializeStorage(core);await initializeProcessHost(core);
  const artifact=artifactFixture();
  if(usesRoles){
    artifact.manifest.roles=[{role_id:'device',kind:'device',minimum:1,maximum:1,purpose:'设备绑定'}];
    artifact.manifest.permission_templates=[{request_id:'device.request',kind:'device_scope',purpose:'请求设备动作',scope:{device_role:'device',action_ids:['get','set'],trigger_ids:[]}}];
  }
  if(usesCapabilities){
    const bytes=fs.readFileSync(new URL('./fixtures/static-capability.json',import.meta.url)),file={path:'payload/capability.json',role:'schema',bytes};
    artifact.payload.set('capability',file);artifact.inventory.files.push({file_id:'capability',path:file.path,size_bytes:String(bytes.length),
      digest:'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex'),role:file.role,executable:false});
    artifact.inventory.files.sort((a,b)=>a.file_id<b.file_id?-1:1);artifact.manifest.capability_template_file_ids=['capability'];
  }
  if(usesConfiguration){
    const bytes=Buffer.from(JSON.stringify({type:'object',properties:{count:{type:'integer',minimum:1,maximum:4}},required:['count'],additionalProperties:false}));
    artifact.payload.get('config').bytes=bytes;Object.assign(artifact.inventory.files.find(f=>f.file_id==='config'),{size_bytes:String(bytes.length),digest:'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex')});
    artifact.manifest.inventory_digest=digestValue(artifact.inventory);
  }
  if(mode==='supervisor_load'){
    for(let i=0;i<640;i++){
      const file_id='extra.'+String(i).padStart(4,'0')+'.'+'x'.repeat(117),file={path:'payload/'+file_id+'.mjs',role:'module',bytes:Buffer.from('export {};')};
      artifact.payload.set(file_id,file);artifact.inventory.files.push({file_id,path:file.path,role:file.role,size_bytes:String(file.bytes.length),digest:digestValue(file_id),executable:false});
      artifact.inventory.files.at(-1).digest='sha256:'+crypto.createHash('sha256').update(file.bytes).digest('hex');
    }
    artifact.inventory.files.sort((a,b)=>a.file_id<b.file_id?-1:1);artifact.manifest.inventory_digest=digestValue(artifact.inventory);
  }
  if(mode.startsWith('supervisor_create_module')){
    const module=artifact.payload.get('worker');module.bytes=fs.readFileSync(path.join(controller,'dist/simulator-module.mjs'));
    Object.assign(artifact.inventory.files.find(f=>f.file_id==='worker'),{size_bytes:String(module.bytes.length),digest:'sha256:'+crypto.createHash('sha256').update(module.bytes).digest('hex')});
    artifact.manifest.api_versions=['leafseamer-device-module/1'];artifact.manifest.ipc_versions=['device-module/1'];
    artifact.manifest.inventory_digest=digestValue(artifact.inventory);
  }
  const archive=zipFixture(artifact.entries()).bytes;
  authorized=await authorizeFixture(store,archive,digestValue(artifact.manifest));
  const identity={host_installation_id:store.identity.host_installation_id,client_registration_id:'client.synthetic',import_request_id:'request.synthetic'};
  const input={identity,target_authority_service_id:mode==='target'?'another.service':coreIdentity.service_id,source_attachment_id:'attachment.synthetic',host_trust_epoch:'1',
    package_digest:authorized.result.body.package_digest,package_bytes:authorized.result.body.package_bytes,expected_manifest_digest:authorized.result.body.expected_manifest_digest,
    release_authorization_ref:authorized.result.reference,validation_policy_ref:authorized.validationPolicy.reference};
  const file=path.join(root,'artifact.zip');fs.writeFileSync(file,archive);store.recordAcceptedImport(input);
  const fd=fs.openSync(file,'r');try{await store.copyImport(identity,fd);}finally{fs.closeSync(fd);}
  await store.validateImport(identity);assert.equal((await store.prepareMaterialization(identity,{reader_sids:[],release_authorization_ref:authorized.result.reference})).status,'prepared');
  const observed=store.platformQualifications.observe(identity),profile=store.platformQualifications.configure(identity,{profile_id:'platform.synthetic',approval_reference:'approval.synthetic',
    evidence_digest:digestValue('synthetic test qualification'),scope_digest:observed.scope_digest}).reference;
  assert.equal((await store.sealImport(identity,{platform_profile_ref:profile,release_authorization_ref:authorized.result.reference})).state,'sealed');
  const sealed=store.sealedArtifact(identity),receipt=sealed.receipt;
  if(mode==='stage'||usesConfiguration){
    const migration=await migrateStorage(core);assert.equal(migration.schema_revision,'24');
    let controllerStore=openStorage(core),manager;
    try{
      let installations=controllerStore.extensionInstallations;installations.bindSource(store);
      const slot=installations.createSlot({request_id:'slot.synthetic',extension_id:artifact.manifest.extension_id});
      const request={request_id:'stage.synthetic',slot_id:slot.record.slot_id,expected_slot_revision:'1',intake_ref:sealed.intake_ref};
      const result=await installations.stage(request);assert.equal(result.state,'verified');assert.equal(result.approval_ref,null);assert.deepEqual(result.runtime_binding_refs,[]);
      assert.deepEqual(installations.content(result.installation_ref).manifest,artifact.manifest);
      assert.deepEqual(installations.content(result.installation_ref).receipt,sealed.receipt);
      await assert.rejects(installations.stage({...request,request_id:'stale.synthetic'}),{code:'extension_slot_stale'});
      assert.deepEqual(await installations.stage(request),result);
      let configurationRequest,configured,roleRequest,resolved,reviewRequest,reviewed,approvalRequest,approved,launchPrepared,launchIntent;
      if(usesConfiguration){
        const described=await store.describeConfigurationSchema({intake_id:receipt.intake_id,target_authority_service_id:coreIdentity.service_id});
        assert.equal(described.status,'available');assert.deepEqual(described.content.bytes,artifact.payload.get('config').bytes);
        configurationRequest={request_id:'configuration.synthetic',installation_ref:result.installation_ref,expected_revision:'0',bytes:Buffer.from('{"count":2}')};
        configured=await installations.configurations.configure(configurationRequest);assert.deepEqual(configured.record.configuration,{count:2});
        assert.deepEqual(await installations.configurations.configure(configurationRequest),configured);
        await assert.rejects(installations.configurations.configure({...configurationRequest,request_id:'bad.configuration',expected_revision:'1',bytes:Buffer.from('{"count":9}')}),{code:'extension_configuration_schema_rejected'});
        assert.deepEqual(installations.configurations.current(result.installation_ref),configured);
        if(usesRoles){
          const capability=controllerStore.enrollment.begin();await controllerStore.enrollment.complete({token_id:capability.token_id,secret:capability.secret,login:'role.test',password:'Synthetic-role-password-123',mode:'standalone'});
          const registered=controllerStore.registerDevice({request_id:'device.synthetic',device_kind:'simulator',display_name:'测试设备'});
          controllerStore.configureVirtualDevice({request_id:'resource.synthetic',device_id:registered.device_id});
          roleRequest={request_id:'resolve.synthetic',installation_ref:result.installation_ref,configuration_ref:configured.configuration_ref,expected_revision:'0',
            bindings:[{role_id:'device',kind:'device',values:[installations.roles.deviceReference(registered.device_id)],configuration_ref:configured.configuration_ref}]};
          resolved=await installations.roles.resolve(roleRequest);assert.equal(resolved.record.permissions[0].scope.devices[0].object_id,registered.device_id);
          assert.deepEqual(installations.roles.current(result.installation_ref),resolved);assert.deepEqual(await installations.roles.resolve(roleRequest),resolved);
          if(runtimeMode||['review','approval','capability','launch_prepare','load_handoff','load_close'].includes(mode)){
            const proposed=structuredClone(resolved.record.permissions);proposed[0].scope.action_ids=['get'];
            reviewRequest={request_id:'review.synthetic',installation_ref:result.installation_ref,configuration_ref:configured.configuration_ref,
              role_resolution_ref:resolved.resolution_ref,expected_revision:'0',proposed_permissions:proposed};
            reviewed=await installations.reviews.review(reviewRequest);assert.deepEqual(reviewed.record.proposed_permissions[0].scope.action_ids,['get']);
            assert.deepEqual(reviewed.record.requested_permissions[0].scope.action_ids,['get','set']);
            assert.deepEqual(installations.reviews.current(result.installation_ref),reviewed);
            if(mode==='approval'||usesCapabilities){
              manager=await management(controllerStore);approvalRequest={request_id:'approve.synthetic',installation_ref:result.installation_ref,
                permission_review_ref:reviewed.review_ref,configuration_ref:configured.configuration_ref,approved_permission_ids:usesCapabilities?['device.request']:[]};
              if(mode==='approval')await assert.rejects(manager.sessions.approveExtension(manager.token,{...approvalRequest,approved_permission_ids:['device.request']}),/extension_capability_template_unavailable/);
              approved=await manager.sessions.approveExtension(manager.token,approvalRequest);assert.deepEqual(approved.permissions,usesCapabilities?proposed:[]);
              assert.deepEqual(manager.sessions.lookupExtensionApproval(manager.token,approvalRequest.request_id),approved);
              if(['launch_prepare','load_handoff','load_close'].includes(mode)){
                // 真实安装服务与业务SQLite；此处核心运行原件为合成，不宣称监督器已创建worker。
                const core=bindCore(controllerStore,{profile_id:receipt.platform_profile_ref.object_id,revision:receipt.platform_profile_ref.revision});
                installations.bindRuntimeSource({scope:{service_id:coreIdentity.service_id,database_instance_id:coreIdentity.database_instance_id,
                  supervisor_instance_id:core.descriptor.supervisor_instance_id,domain_ref:core.receipt.domain_ref},assertCurrent(){},current(){return {payload:{record:{admission_receipt:core.receipt}}};}});
                const plan=await manager.sessions.planExtension(manager.token,{request_id:'plan.synthetic',slot_id:result.slot.record.slot_id,expected_slot_revision:result.slot.slot_ref.revision,
                  selection:{kind:'activate',source_installation_ref:null,target_installation_ref:result.installation_ref,reuse_content_ref:null,configuration_ref:configured.configuration_ref}});
                const activation=await manager.sessions.activateExtension(manager.token,{request_id:'activate.synthetic',slot_id:result.slot.record.slot_id,expected_slot_revision:result.slot.slot_ref.revision,
                  target_installation_ref:result.installation_ref,approval_ref:approved.approval_ref,dependency_plan_ref:plan.plan_ref});assert.equal(activation.record.phase,'accepted');
                launchIntent=workerIntent(controllerStore,core,installations.content(result.installation_ref),approved,[registered.device_id]);
                launchPrepared=await controllerStore.workerLaunches.prepare(Buffer.from(canonicalize(launchIntent)));
                assert.deepEqual(launchPrepared.intent.extension_binding.approval_ref,approved.approval_ref);
                const dependencies=controllerStore.workerLaunches.dependencies({launch_id:launchIntent.launch_id,launch_intent_digest:digestValue(launchIntent)});
                assert.deepEqual(dependencies.devices.map(value=>value.object_id),[registered.device_id]);
                assert.equal(dependencies.resources.length,1);assert.deepEqual(dependencies.links[0].action_ids,['get','set']);
                assert.deepEqual(await controllerStore.workerLaunches.prepare(Buffer.from(canonicalize(launchIntent))),launchPrepared);
                if(mode==='load_handoff'||mode==='load_close'){
                  const key={launch_id:launchIntent.launch_id,launch_intent_digest:digestValue(launchIntent)},held=await controllerStore.workerLaunches.acquireContent(key);
                  const file=path.join(held.protection.root_path,held.protection.entry_path);
                  try{
                    assert.equal(held.materials.format,'leafseamer-worker-load/1');assert.equal(held.materials.root_identity,held.protection.root_identity);
                    assert.deepEqual(held.materials.manifest,artifact.manifest);assert.deepEqual(held.materials.inventory,artifact.inventory);
                    assert.ok(Object.isFrozen(held.materials)&&Object.isFrozen(held.materials.inventory.files[0]));
                    assert.equal(held.protection.entry_file_id,'worker');assert.equal(held.protection.manifest_digest,receipt.manifest_digest);
                    assert.ok(Object.isFrozen(held.protection));assert.throws(()=>fs.writeFileSync(file,'replacement'));
                    await held.verify();assert.throws(()=>fs.renameSync(file,file+'.moved'));
                    if(mode==='load_close'){
                      manager.clock.stop();controllerStore.close();await held.closed;
                      await assert.rejects(held.verify(),/content_pin_closed/);fs.writeFileSync(file,artifact.payload.get('worker').bytes);return;
                    }
                    store.advanceTrustEpoch({expected_epoch:'1',operation_id:'revoke.handoff'});
                    await assert.rejects(held.verify(),/extension_launch_source_unavailable/);await held.closed;
                    fs.writeFileSync(file,artifact.payload.get('worker').bytes);
                    await assert.rejects(controllerStore.workerLaunches.acquireContent(key),/extension_launch_loader_binding/);
                  }finally{await held.close();}
                  return;
                }
              }
            }
          }
        }
      }
      if(runtimeMode){
        runtimeInput={content:installations.content(result.installation_ref),slot_ref:result.slot.slot_ref,approved,devices:resolved.record.bindings.flatMap(binding=>binding.values.map(ref=>ref.object_id)).sort()};
      }else{
      manager?.clock.stop();controllerStore.close();controllerStore=openStorage(core);installations=controllerStore.extensionInstallations;installations.bindSource(store);
      assert.deepEqual(installations.query(request.request_id),result);assert.deepEqual(installations.content(result.installation_ref).inventory,artifact.inventory);
      if(launchPrepared)assert.equal(controllerStore.workerLaunches.query({launch_id:launchIntent.launch_id,launch_intent_digest:digestValue(launchIntent)}).current_boot,false);
      if(configured)assert.deepEqual(installations.configurations.query(configurationRequest.request_id),configured);
      if(resolved)assert.deepEqual(installations.roles.query(roleRequest.request_id),resolved);
      if(reviewed)assert.deepEqual(installations.reviews.query(reviewRequest.request_id),reviewed);
      if(approved){manager=await management(controllerStore);assert.equal(manager.sessions.getExtensionApproval(manager.token,approved.approval_ref).status,'approved');}
      if(usesCapabilities){const described=await store.describeCapabilityTemplates({intake_id:receipt.intake_id,target_authority_service_id:coreIdentity.service_id});
        assert.equal(described.status,'available');assert.deepEqual(described.content.files[0].bytes,artifact.payload.get('capability').bytes);}
      store.advanceTrustEpoch({expected_epoch:'1',operation_id:'revoke.synthetic'});
      assert.deepEqual(await installations.stage(request),result);
      await assert.rejects(installations.stage({...request,request_id:'revoked.synthetic',expected_slot_revision:'2'}),{code:'extension_intake_unavailable'});
      assert.equal(installations.query('revoked.synthetic'),null);
      if(configured){
        assert.deepEqual(await installations.configurations.configure(configurationRequest),configured);
        await assert.rejects(installations.configurations.configure({...configurationRequest,request_id:'revoked.configuration',expected_revision:'1'}),{code:'extension_configuration_source_unavailable'});
      }
      if(resolved){
        assert.deepEqual(await installations.roles.resolve(roleRequest),resolved);
        await assert.rejects(installations.roles.resolve({...roleRequest,request_id:'revoked.resolution',expected_revision:'1'}),{code:'extension_role_source_unavailable'});
      }
      if(reviewed){
        assert.deepEqual(await installations.reviews.review(reviewRequest),reviewed);
        await assert.rejects(installations.reviews.review({...reviewRequest,request_id:'revoked.review',expected_revision:'1'}),{code:'extension_review_source_unavailable'});
      }
      if(usesCapabilities)assert.equal((await store.describeCapabilityTemplates({intake_id:receipt.intake_id,target_authority_service_id:coreIdentity.service_id})).status,'unavailable');
      if(approved){
        const denied=manager.sessions.revokeExtensionApproval(manager.token,{request_id:'revoke-approval.synthetic',approval_ref:approved.approval_ref,reason:'集成撤销'});
        assert.ok(denied.deny_ref);assert.equal(manager.sessions.getExtensionApproval(manager.token,approved.approval_ref).status,'revoked');
      }
      }
    }finally{manager?.clock.stop();controllerStore.close();}
    if(!runtimeMode)return;
  }
  const moduleStorageFailure=mode==='supervisor_create_module_store_fail'||mode==='supervisor_create_module_store_ignore';
  if(moduleStorageFailure){
    const fault=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{fault.exec(`CREATE TRIGGER module_candidate_fault BEFORE INSERT ON device_module_frame_commit
      WHEN (SELECT message_type FROM device_module_frame WHERE message_id=NEW.message_id)='CAPTURED'
      BEGIN SELECT RAISE(${mode.endsWith('ignore')?'IGNORE':"ABORT,'synthetic_module_commit'"}); END`);}finally{fault.close();}
  }
  const binding={intake_ref:sealed.intake_ref,platform_profile_ref:profile,host_installation_id:store.identity.host_installation_id,
    host_trust_epoch:receipt.host_trust_epoch,manifest_digest:receipt.manifest_digest,artifact_set_digest:receipt.artifact_set_digest};
  if(mode==='receipt')binding.intake_ref={...binding.intake_ref,digest:digestValue('wrong receipt')};
  let materials;
  if(mode.startsWith('supervisor_')){
    const lease=await store.acquireMaterialization({intake_id:sealed.intake_ref.object_id,target_authority_service_id:coreIdentity.service_id});
    assert.equal(lease.status,'available');
    try{const content=lease.content;contentPin=await pinLaunchContent(content.root.path,content.inventory,content.root.root_identity);
      materials={format:'leafseamer-worker-load/1',root_path:content.root.path,root_identity:content.root.root_identity,manifest:structuredClone(content.manifest),inventory:structuredClone(content.inventory)};
    }finally{await lease.close();}
    if(mode==='supervisor_bad_root')materials.root_identity='0'.repeat(48);
    if(mode==='supervisor_bad_manifest')materials.manifest.extension_version='2';
    if(mode==='supervisor_load')assert.ok(Buffer.byteLength(canonicalize(materials))>262144);
  }
  if(runtimeInput)runtimeInput.installation_client={peer_module:new URL('../dist/local-peer.mjs',import.meta.url).href,client_module:new URL('../dist/local-import.mjs',import.meta.url).href,
    name:'\\\\.\\pipe\\LeafSeamer.Install.'+crypto.randomUUID(),channel_id:crypto.randomUUID(),server_pid:process.pid};
  const fixture=path.join(root,'fixture.json');fs.writeFileSync(fixture,JSON.stringify({binding,mode,materials,runtime:runtimeInput}));
  const peer=captureInstallationPeer(process.pid).descriptor,descriptor=store.materializationClock(),suffix=crypto.randomUUID(),channelId=crypto.randomUUID();
  const config={format:'leafseamer-installation-peer/1',pipe_suffix:suffix,channel_id:channelId,
    host_installation_id:store.identity.host_installation_id,authority_service_id:store.identity.authority_service_id,database_instance_id:store.identity.database_instance_id,
    server_pid:String(peer.pid),server_creation_time:peer.creation_time,session_id:String(peer.session_id),user_sid:peer.user_sid,authentication_id:peer.authentication_id,
    observer_domain:{clock_domain_id:descriptor.clock_domain_id,descriptor_digest:mode==='observer'?digestValue('other descriptor'):digestValue(descriptor)}};
  if(mode==='peer')config.server_creation_time=String(BigInt(config.server_creation_time)+1n);
  const policy={format:'leafseamer-core-bootstrap-policy/1',service_id:coreIdentity.service_id,database_instance_id:coreIdentity.database_instance_id,
    artifact_manifest_ref:{manifest_id:'synthetic-integration',revision:'1',digest:installedCoreDigest()},
    platform_profile_ref:{profile_id:profile.object_id,revision:profile.revision},policy_revision:'1',bootstrap_timeout_ms:10000,clock_backend_revision:'1'};
  let runtime=path.join(controller,'dist');
  if(['supervisor_create_exit','supervisor_create_deny_pending'].includes(mode)){
    runtime=path.join(root,'runtime');fs.cpSync(path.join(controller,'dist'),runtime,{recursive:true});
    const entry=path.join(runtime,'device-worker-entry.mjs');
    fs.writeFileSync(entry,(mode==='supervisor_create_exit'?'process.exit(23);\n':'await new Promise(resolve=>setTimeout(resolve,2000));\n')+fs.readFileSync(entry,'utf8'));
    const manifestFile=path.join(runtime,'build-manifest.json'),manifest=JSON.parse(fs.readFileSync(manifestFile));
    const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
    manifest.artifacts['device-worker-entry.mjs']=hash(fs.readFileSync(entry));fs.writeFileSync(manifestFile,JSON.stringify(manifest,null,2)+'\n');
    policy.artifact_manifest_ref.digest=digestValue({controller_build_sha256:hash(fs.readFileSync(manifestFile)),node_sha256:hash(fs.readFileSync(path.join(runtime,'runtime/node.exe')))});
  }
  if(mode==='supervisor_create_bad_profile')policy.platform_profile_ref.profile_id='different.profile';
  child=spawn(path.join(runtime,'native/leafseamer_process_host.exe'),[core,process.execPath,path.join(controller,'test/fixtures/materialization-core.mjs'),
    'contained-core-auth','--bootstrap-policy',canonicalize(policy),'--installation-peer',canonicalize(config),'--fixture',fixture],{stdio:['pipe','pipe','pipe'],windowsHide:true});
  ended=once(child,'close');child.stdin.on('error',()=>{});let stdout='';child.stdout.on('data',chunk=>{stdout+=chunk;});child.stderr.on('data',chunk=>{stderr+=chunk;for(;;){const at=stderr.indexOf('\n');if(at<0)break;
    const line=stderr.slice(0,at);stderr=stderr.slice(at+1);try{frames.push(JSON.parse(line));}catch{frames.push({event:'diagnostic',line});}}});
  if(mode==='peer'){assert.notEqual((await ended)[0],0);assert.match(stdout,/installation_peer/);return;}
  const clientPeer=captureInstallationPeer(child.pid);
  store.registerClient({client_registration_id:'coordinator.synthetic',role:'launch_coordinator',user_sid:clientPeer.descriptor.user_sid,
    target_authority_service_ids:[coreIdentity.service_id],permissions:['intake.query','materialization.verify'],approval_reference:'approval.synthetic'});
  const channel=createInstallationChannel({name:'\\\\.\\pipe\\LeafSeamer.Install.'+suffix,peer:clientPeer,server:true}),replies=[];
  // 注入响应延迟／错绑；查询与物化观察始终由真实store及原生文件检查完成。
  const instrumented={...store,bindImportClient(...args){const bound=store.bindImportClient(...args);return {...bound,async verifyMaterialization(request){
    if(['verified','revoke_pending','timeout'].includes(mode))await delay(mode==='timeout'?4200:2200);
    const result=await bound.verifyMaterialization(request);replies.push(result);
    return mode==='challenge'?{...result,request:{...result.request,challenge_id:'wrong.challenge'}}:result;
  }};}};
  service=serveInstallationClient({store:instrumented,registration_id:'coordinator.synthetic',channel_id:channelId,channel});service.done.catch(()=>{});
  if(runtimeMode){
    await waitFor(()=>frames.find(frame=>frame.event==='intake-peer')||child.exitCode!==null);
    const peerFrame=frames.find(frame=>frame.event==='intake-peer');assert.ok(peerFrame,JSON.stringify({frames,stdout,stderr}));const corePeer=captureInstallationPeer(peerFrame.pid);
    // 显式交接服务端创建完成，覆盖客户端先报告身份的调度顺序。
    await delay(100);
    store.registerClient({client_registration_id:'core.intake',role:'launch_coordinator',user_sid:corePeer.descriptor.user_sid,
      target_authority_service_ids:[coreIdentity.service_id],permissions:['intake.query'],approval_reference:'approval.synthetic'});
    const client=runtimeInput.installation_client,intakeChannel=createInstallationChannel({name:client.name,peer:corePeer,server:true});
    intakeService=serveInstallationClient({store,registration_id:'core.intake',channel_id:client.channel_id,channel:intakeChannel});intakeService.done.catch(()=>{});
    fs.writeFileSync(fixture+'.intake-ready','ready');
  }
  if(loadsSuccessfully){
    await waitFor(()=>frames.find(f=>f.event==='loaded'||f.event==='unavailable')||child.exitCode!==null);
    assert.ok(frames.find(f=>f.event==='loaded'),JSON.stringify({frames,stdout,stderr}));
    await contentPin.close();contentPin=null;
    const entry=path.join(materials.root_path,'payload/main.mjs');
    assert.throws(()=>fs.writeFileSync(entry,'mutation'));
    assert.throws(()=>fs.renameSync(entry,entry+'.moved'));
    fs.writeFileSync(fixture+'.continue','continue');
  }
  await waitFor(()=>frames.find(f=>f.event==='done')||child.exitCode!==null);
  const done=frames.find(f=>f.event==='done');assert.ok(done,JSON.stringify({frames,stdout,stderr}));
  if(moduleStorageFailure){
    assert.equal(frames.find(f=>f.event==='unavailable')?.code,'module_channel_closed');
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    assert.equal(frames.find(f=>f.event==='module-samples'),undefined);
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM device_module_channel').pluck().get(),1);
      assert.equal(db.prepare('SELECT count(*) FROM device_module_frame').pluck().get(),5);
      assert.equal(db.prepare('SELECT count(*) FROM device_module_frame_commit').pluck().get(),5);
      assert.equal(db.prepare("SELECT count(*) FROM device_module_frame WHERE message_type='CAPTURED'").pluck().get(),0);
      assert.equal(db.prepare("SELECT count(*) FROM device_module_frame WHERE message_type='CAPTURE'").pluck().get(),1);
      assert.equal(db.prepare('SELECT count(*) FROM worker_runtime_withdrawal').pluck().get(),1);
    }finally{db.close();}return;
  }
  assert.equal(done.record.state,creates?'retired':'registered',JSON.stringify(frames));assert.equal(done.record.creation_attempted,creates);
  if(creates){
    const admitted=frames.find(f=>f.event==='admitted')?.record;assert.equal(admitted?.state,(mode==='supervisor_create'||runtimeMode)?'admitted_closed':'indeterminate',JSON.stringify(frames));
    if(mode==='supervisor_create'||runtimeMode){assert.equal(admitted.admission_receipt.role,'worker');assert.equal(admitted.admission_receipt.gate_state,'closed');
      assert.deepEqual(frames.find(f=>f.event==='observed')?.receipt,admitted.admission_receipt);
      for(const event of ['copied-observation','withdrawn-observation'])assert.equal(frames.find(f=>f.event===event)?.code,'supervisor_worker_withdrawn');}
    else assert.equal(admitted.admission_receipt,null);
    if(mode==='supervisor_create_deny_pending')assert.equal(frames.find(f=>f.event==='created').record.state,'awaiting_bootstrap');
    if(runtimeMode){const adopted=frames.find(f=>f.event==='runtime-adopted')?.binding;assert.ok(adopted,JSON.stringify(frames));
      const plan=frames.find(f=>f.event==='plan-created')?.plan;assert.ok(plan);assert.equal(plan.plan_ref.kind,'dependency_plan');
      assert.deepEqual(plan.impacts.map(value=>value.object_ref.kind).sort(),['device','resource']);
      assert.deepEqual(plan.lifetime.clock,admitted.admission_receipt.domain_ref);
      assert.equal(frames.find(f=>f.event==='plan-invalidated')?.code,'extension_plan_slot_stale');
      const activation=frames.find(f=>f.event==='activation-accepted')?.activation;assert.equal(activation?.record.phase,'accepted');assert.equal(activation.owners.length,1);
      assert.equal(adopted.ref.kind,'runtime_binding');assert.deepEqual(adopted.binding.admission_receipt,admitted.admission_receipt);
      // 人员撤销可先由审批writer或监督观察发现；两条路径都必须永久撤回同一运行绑定。
      assert.ok(['source_changed','approval_changed'].includes(frames.find(f=>f.event==='runtime-withdrawn')?.binding.withdrawal.reason));
      if(mode==='supervisor_create_module'){
        const samples=frames.find(f=>f.event==='module-samples');assert.ok(samples,JSON.stringify(frames));
        assert.deepEqual(samples.connected.body.identity,{kind:'virtual',model:'leafseamer.simulator',revision:'1'});
        assert.deepEqual(samples.first.body.value,{value:0,sample_sequence:'1'});assert.deepEqual(samples.second.body.value,{value:0,sample_sequence:'2'});
        assert.notEqual(samples.first.body.capture_id,samples.second.body.capture_id);
        assert.equal(samples.first.body.device_session_id,samples.connected.body.device_session_id);
        assert.deepEqual(samples.first.binding.runtime_binding_ref,adopted.ref);
        assert.equal(samples.disconnected.type,'DISCONNECTED');
        assert.equal(samples.disconnected.body.device_session_id,samples.connected.body.device_session_id);
        assert.equal(frames.find(f=>f.event==='module-disconnected-read')?.code,'module_session');
        assert.notEqual(samples.reconnected.body.device_session_id,samples.connected.body.device_session_id);
        assert.equal(samples.third.body.device_session_id,samples.reconnected.body.device_session_id);
        assert.deepEqual(samples.third.body.value,{value:0,sample_sequence:'1'});
        assert.notEqual(frames.find(f=>f.event==='module-revoked')?.code,'unexpected_success');
        assert.ok(frames.find(f=>f.event==='module-revoked')?.code);
      }
    }
    assert.equal(frames.find(f=>f.event==='duplicate')?.code,runtimeMode?'worker_authorization_creation_attempted':'supervisor_indeterminate');
    const denied=frames.find(f=>f.event==='denied')?.record;
    if(runtimeMode)assert.ok(['indeterminate','retiring','retired'].includes(denied?.state));
    else assert.equal(denied?.state,'indeterminate');
    assert.equal(frames.find(f=>f.event==='retired')?.result.result,'confirmed_empty');
  }
  if(mode==='supervisor_create_bad_profile')assert.equal(frames.find(f=>f.event==='profile-rejected')?.code,'supervisor_invalid_binding');
  if(materials){
    if(loadsSuccessfully)assert.equal(frames.find(f=>f.event==='released')?.status,'released',JSON.stringify(frames));
    else assert.equal(frames.find(f=>f.event==='unavailable')?.code,'supervisor_load_unavailable',JSON.stringify(frames));
    await contentPin?.close();contentPin=null;
    fs.writeFileSync(path.join(materials.root_path,'payload/main.mjs'),'after release');
  }else if(mode==='verified'){
    const result=frames.find(f=>f.event==='verified');assert.ok(result,JSON.stringify(frames));assert.ok(result.elapsed_ms>=2200);
    assert.equal(result.result.observation.materialization_evidence_id,replies[0].evidence_id);
    assert.equal(result.result.observation.materialization_challenge_id,replies[0].request.challenge_id);
    assert.equal(replies[0].request.launch_intent_digest,result.result.key.launch_intent_digest);
    assert.deepEqual(['forged','unapproved','expired','revoked'].map(event=>frames.find(f=>f.event===event)?.code),
      ['supervisor_invalid_binding','supervisor_invalid_binding','supervisor_expired','supervisor_unauthorized']);
  }else assert.equal(frames.find(f=>f.event==='unavailable')?.code,mode==='revoke_pending'?'supervisor_unauthorized':'supervisor_materialization_unavailable',JSON.stringify(frames));
  child.stdin.end('stop\n');assert.equal((await ended)[0],0);
  if(creates){
    const db=new Database(path.join(core,'supervisor-journal.db'),{fileMustExist:true});
    try{
      assert.equal(db.prepare('SELECT count(*) FROM worker_creation').pluck().get(),1);assert.equal(db.prepare('SELECT count(*) FROM worker_observation').pluck().get(),1);
      const creation=JSON.parse(db.prepare('SELECT record_jcs FROM worker_creation').pluck().get()),observation=JSON.parse(db.prepare('SELECT record_jcs FROM worker_observation').pluck().get());
      assert.equal(observation.creation_id,creation.creation_id);assert.equal(observation.created_suspended,true);assert.equal(observation.assigned_at_creation,true);
      const retired=JSON.parse(db.prepare('SELECT observation_jcs FROM worker_retirement').pluck().get());assert.equal(retired.active_processes,0);assert.ok(retired.total_processes>=1);
      assert.equal(fs.readdirSync(core).some(name=>name.startsWith('worker-start-')),false);
    }finally{db.close();}
    if(runtimeMode){const business=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(business.prepare('SELECT count(*) FROM extension_activation').pluck().get(),1);
      assert.equal(business.prepare('SELECT count(*) FROM extension_resource_owner_head').pluck().get(),1);
      assert.equal(business.prepare('SELECT activation_operation_id FROM worker_launch_preparation').pluck().get(),frames.find(f=>f.event==='activation-accepted').activation.operation_ref.object_id);
      assert.equal(business.prepare('SELECT count(*) FROM worker_runtime_binding').pluck().get(),1);
      assert.equal(business.prepare('SELECT count(*) FROM worker_launch_authorization').pluck().get(),2);
      assert.equal(business.prepare('SELECT count(*) FROM worker_launch_denial').pluck().get(),1);
      const fences=business.prepare('SELECT body_jcs FROM worker_fence_snapshot ORDER BY revision').pluck().all().map(JSON.parse);
      assert.equal(fences.at(-1).items[0].disposition,'deny');
      assert.equal(business.prepare('SELECT count(*) FROM worker_fence_ack').pluck().get(),fences.length);
      assert.equal(business.prepare('SELECT count(*) FROM worker_runtime_commit').pluck().get(),1);
      assert.equal(business.prepare('SELECT count(*) FROM worker_runtime_withdrawal').pluck().get(),1);
      if(mode==='supervisor_create_module'){
        assert.equal(business.prepare('SELECT count(*) FROM device_module_channel').pluck().get(),1);
        assert.equal(business.prepare('SELECT count(*) FROM device_module_frame').pluck().get(),14);
        assert.equal(business.prepare('SELECT count(*) FROM device_module_frame_commit').pluck().get(),14);
        const captures=business.prepare("SELECT frame_jcs FROM device_module_frame WHERE message_type='CAPTURED' ORDER BY length(sequence),sequence").pluck().all().map(JSON.parse);
        assert.deepEqual(captures.map(f=>f.body.value.sample_sequence),['1','2','1']);
        assert.equal(new Set(captures.map(f=>f.body.device_session_id)).size,2);
        assert.throws(()=>business.exec('DELETE FROM device_module_frame'),/immutable_module_frame/);
      }
    }finally{business.close();}}
  }
});
