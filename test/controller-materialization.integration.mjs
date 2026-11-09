import {deviceExecutionCapabilities} from '../dist/sdk/device-execution.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn,spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {once} from 'node:events';
import {pathToFileURL,fileURLToPath} from 'node:url';
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
const {certificate}=await import(pathToFileURL(path.join(controller,'test/https-auth-fixture.mjs')));
async function verifySuccessorMigration(directory){
  const snapshot=db=>Object.fromEntries(db.prepare("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN('service_state','schema_migration') ORDER BY name").pluck().all().map(name=>{
    assert.match(name,/^[a-z_][a-z0-9_]*$/);const rows=db.prepare('SELECT * FROM '+name).raw().all().map(row=>JSON.stringify(row)).sort();
    return [name,{rows:rows.length,digest:crypto.createHash('sha256').update(JSON.stringify(rows)).digest('hex')}];
  }));
  let db=new Database(path.join(directory,'controller.sqlite'),{fileMustExist:true});let before,identity,history,commandId,permitId;
  try{
    assert.equal(db.pragma('user_version',{simple:true}),56);
    before=snapshot(db);identity=db.prepare('SELECT service_id,database_instance_id,control_epoch,request_epoch FROM service_state').raw().get();
    history=db.prepare('SELECT * FROM schema_migration ORDER BY CAST(to_revision AS INTEGER)').raw().all();
    [commandId,permitId]=db.prepare('SELECT command_id,permit_id FROM command_settlement').raw().get();
    assert.equal(before.command_settlement.rows,1);assert.equal(before.command_preparation_cleanup.rows,4);
    assert.equal(before.command_device_hold.rows,1);assert.equal(before.command_hold_release.rows,1);
  }finally{db.close();}
  const migration=await migrateStorage(directory,57);assert.equal(migration.schema_revision,'57');assert.equal(migration.steps.length,1);
  db=new Database(path.join(directory,'controller.sqlite'),{fileMustExist:true});try{
    db.pragma('foreign_keys=ON');assert.equal(db.pragma('user_version',{simple:true}),57);
    assert.deepEqual(snapshot(db),before,'迁移不能改写或丢弃任何既有业务行');
    assert.deepEqual(db.prepare('SELECT service_id,database_instance_id,control_epoch,request_epoch FROM service_state').raw().get(),identity);
    assert.deepEqual(db.prepare("SELECT * FROM schema_migration WHERE to_revision!='57' ORDER BY CAST(to_revision AS INTEGER)").raw().all(),history);
    const {readCommandRecord}=await load('command-record-store.mjs'),{readCommandPreparationCleanup}=await load('command-preparation-cleanup.mjs');
    db.transaction(()=>{
      const saved=readCommandRecord(db,commandId),cleanup=readCommandPreparationCleanup(db,permitId);
      assert.equal(saved.record.state.outcome,'succeeded');assert.equal(saved.record.revision,'5');
      assert.equal(cleanup.steps.release_ack.frame.frame.body.cache_empty,true);
    }).immediate();
    assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),8);
    assert.deepEqual(db.pragma('foreign_key_check'),[]);
  }finally{db.close();}
}
const commandAdmissionFaults=['source','notification'].map(part=>'supervisor_create_module_writable_evidence_resource_open_dispatch_ready_command_'+part+'_ignore');
const commandLifecycleFaults=['commit','head'].map(part=>'supervisor_create_module_writable_evidence_resource_open_dispatch_ready_lifecycle_'+part+'_ignore');
const commandLifecycleCases=['queue_deadline','execution_closed'].map(part=>'supervisor_create_module_writable_evidence_resource_open_dispatch_ready_'+part);
const finalAdmissionOmissions=Object.fromEntries(['command_final_admission','command_device_hold','command_transmission_issue','command_attempt_inventory','command_lifecycle_revision','command_lifecycle_commit','command_lifecycle_head']
 .map(table=>['supervisor_create_module_writable_evidence_resource_open_dispatch_ready_encoding_t2_'+table+'_omit',table]));
const guardOmissions=Object.fromEntries(['command_guard_request','command_guard_ack','execution_guard_frame','execution_effect_commit'].map(table=>['supervisor_create_module_writable_evidence_resource_open_dispatch_ready_encoding_t2_guard_'+table+'_omit',table]));
const dispatchOmissions=Object.fromEntries([["request", "command_dispatch_request", "INSERT", ""], ["write", "command_dispatch_write", "INSERT", ""], ["report", "command_dispatch_report", "INSERT", ""], ["evidence", "command_dispatch_evidence", "INSERT", ""], ["frame", "execution_dispatch_frame", "INSERT", "NEW.phase='request'"], ["effect", "execution_effect_commit", "INSERT", "json_extract(NEW.audit_jcs,'$.kind')='command_dispatch_request'"], ["write_commit", "command_lifecycle_commit", "INSERT", "NEW.revision=3"], ["write_head", "command_lifecycle_head", "UPDATE", "NEW.revision=3"], ["report_commit", "command_lifecycle_commit", "INSERT", "NEW.revision=4"], ["report_head", "command_lifecycle_head", "UPDATE", "NEW.revision=4"]].map(([part,table,operation,condition])=>['supervisor_create_module_writable_evidence_resource_open_dispatch_ready_encoding_t2_guard_dispatch_'+part+'_omit',{part,table,operation,condition}]));
const settlementOmissions=Object.fromEntries([
 ['request','command_closure_request','INSERT',''],['ack','command_closure_ack','INSERT',''],
 ['write','execution_write_attempt','INSERT',"EXISTS(SELECT 1 FROM command_closure_request c WHERE c.record_id=NEW.record_id)"],
 ['settlement','command_settlement','INSERT',''],['evidence','command_evidence_record','INSERT',''],['release','command_hold_release','INSERT',''],
 ['commit','command_lifecycle_commit','INSERT','NEW.revision=5'],['head','command_lifecycle_head','UPDATE','NEW.revision=5']
].map(([part,table,operation,condition])=>['supervisor_create_module_writable_evidence_resource_open_dispatch_ready_encoding_t2_guard_dispatch_closure_'+part+'_omit',{part,table,operation,condition}]));
const cleanupOmissions=Object.fromEntries(['deny_request','deny_ack','release_request','release_ack'].map(phase=>
 ['supervisor_create_module_writable_evidence_resource_open_dispatch_ready_encoding_t2_guard_dispatch_closure_cleanup_'+phase+'_omit',
 {phase,table:'command_preparation_cleanup',operation:'INSERT',condition:"NEW.phase='"+phase+"'"}]));
const commandEncodingCases=[...['','_request_ignore','_response_ignore','_changed_input','_t2','_t2_guard','_t2_guard_changed','_t2_guard_dispatch','_t2_guard_dispatch_closure','_t2_guard_dispatch_closure_late','_t2_guard_dispatch_closure_cleanup','_t2_guard_dispatch_closure_cleanup_late','_t2_guard_dispatch_closure_cleanup_successor','_t2_observation_omit'].map(part=>'supervisor_create_module_writable_evidence_resource_open_dispatch_ready_encoding'+part),...Object.keys(finalAdmissionOmissions),...Object.keys(guardOmissions),...Object.keys(dispatchOmissions),...Object.keys(settlementOmissions),...Object.keys(cleanupOmissions)];
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
async function waitFor(fn,timeout=15000){const end=performance.now()+timeout;while(!fn()){assert.ok(performance.now()<end,'真实监督器事件等待超时');await delay(20);}return fn();}

for(const mode of ['verified','receipt','observer','challenge','target','peer','revoke_pending','timeout','stage','configuration','roles','review','approval','capability','launch_prepare','load_handoff','load_close','supervisor_load','supervisor_deny','supervisor_bad_root','supervisor_bad_manifest','supervisor_bad_entry','supervisor_create','supervisor_create_exit','supervisor_create_deny_pending','supervisor_create_bad_profile','supervisor_create_runtime','supervisor_create_module','supervisor_create_module_store_fail','supervisor_create_module_store_ignore','supervisor_create_module_catalog_template','supervisor_create_module_catalog_policy','supervisor_create_module_catalog_fail','supervisor_create_module_catalog_ignore','supervisor_create_module_baseline_fail','supervisor_create_module_baseline_ignore','supervisor_create_module_control','supervisor_create_module_writable','supervisor_create_module_writable_catalog_template','supervisor_create_module_writable_catalog_policy','supervisor_create_module_writable_binding_fail','supervisor_create_module_writable_binding_ignore','supervisor_create_module_writable_handshake_fail','supervisor_create_module_writable_handshake_write_ignore','supervisor_create_module_writable_control_fence_request_fail','supervisor_create_module_writable_control_fence_ack_ignore','supervisor_create_module_writable_control_fence_write_ignore','supervisor_create_module_writable_manual_authority_source_fail','supervisor_create_module_writable_manual_authority_commit_ignore','supervisor_create_module_writable_manual_authority_core_source_fail','supervisor_create_module_writable_manual_authority_core_commit_ignore','supervisor_create_module_writable_evaluator_source_fail','supervisor_create_module_writable_evaluator_commit_ignore','supervisor_create_module_writable_recovery_request_ignore','supervisor_create_module_writable_recovery_authorization_ignore','supervisor_create_module_writable_recovery_commit_ignore','supervisor_create_module_writable_consumption_record_ignore','supervisor_create_module_writable_consumption_state_ignore','supervisor_create_module_writable_consumption_commit_ignore','supervisor_create_module_writable_consumption_head_ignore','supervisor_create_module_writable_manual_challenge_record_ignore','supervisor_create_module_writable_manual_challenge_commit_ignore','supervisor_create_module_writable_manual_challenge_response_ignore','supervisor_create_module_writable_manual_challenge_checks','supervisor_create_module_writable_evidence_checks','supervisor_create_module_writable_evidence_cut_ignore','supervisor_create_module_writable_evidence_record_ignore','supervisor_create_module_writable_evidence_commit_ignore','supervisor_create_module_writable_evidence_head_ignore','supervisor_create_module_writable_evidence_resource_checks','supervisor_create_module_writable_evidence_resource_record_ignore','supervisor_create_module_writable_evidence_resource_commit_ignore','supervisor_create_module_writable_evidence_resource_open_checks','supervisor_create_module_writable_evidence_resource_open_record_ignore','supervisor_create_module_writable_evidence_resource_open_commit_ignore',"supervisor_create_module_writable_evidence_resource_open_dispatch","supervisor_create_module_writable_evidence_resource_open_dispatch_stale","supervisor_create_module_writable_evidence_resource_open_dispatch_expired","supervisor_create_module_writable_evidence_resource_open_dispatch_request_ignore","supervisor_create_module_writable_evidence_resource_open_dispatch_ack_ignore","supervisor_create_module_writable_evidence_resource_open_dispatch_ready","supervisor_create_module_writable_evidence_resource_open_dispatch_ready_stale","supervisor_create_module_writable_evidence_resource_open_dispatch_ready_expired","supervisor_create_module_writable_evidence_resource_open_dispatch_ready_ignore","supervisor_create_module_writable_evidence_resource_open_dispatch_ready_control_ignore",...commandAdmissionFaults,...commandLifecycleFaults,...commandLifecycleCases,...commandEncodingCases])test((['launch_prepare','load_handoff','load_close'].includes(mode)?'安装服务与启动准备联调（合成核心域）：':'安装服务与原生监督器联调：')+mode,{skip:process.platform!=='win32',timeout:60000},async t=>{
  const commandSettled=mode.includes('_dispatch_closure'),commandDispatch=mode.includes('_guard_dispatch'),commandDispatchFailure=dispatchOmissions[mode],settlementFailure=settlementOmissions[mode],cleanupFailure=cleanupOmissions[mode];
  const runtimeMode=['supervisor_create_runtime','supervisor_create_module','supervisor_create_module_store_fail','supervisor_create_module_store_ignore','supervisor_create_module_catalog_template','supervisor_create_module_catalog_policy','supervisor_create_module_catalog_fail','supervisor_create_module_catalog_ignore','supervisor_create_module_baseline_fail','supervisor_create_module_baseline_ignore','supervisor_create_module_control','supervisor_create_module_writable','supervisor_create_module_writable_catalog_template','supervisor_create_module_writable_catalog_policy','supervisor_create_module_writable_binding_fail','supervisor_create_module_writable_binding_ignore','supervisor_create_module_writable_handshake_fail','supervisor_create_module_writable_handshake_write_ignore','supervisor_create_module_writable_control_fence_request_fail','supervisor_create_module_writable_control_fence_ack_ignore','supervisor_create_module_writable_control_fence_write_ignore','supervisor_create_module_writable_manual_authority_source_fail','supervisor_create_module_writable_manual_authority_commit_ignore','supervisor_create_module_writable_manual_authority_core_source_fail','supervisor_create_module_writable_manual_authority_core_commit_ignore','supervisor_create_module_writable_evaluator_source_fail','supervisor_create_module_writable_evaluator_commit_ignore','supervisor_create_module_writable_recovery_request_ignore','supervisor_create_module_writable_recovery_authorization_ignore','supervisor_create_module_writable_recovery_commit_ignore','supervisor_create_module_writable_consumption_record_ignore','supervisor_create_module_writable_consumption_state_ignore','supervisor_create_module_writable_consumption_commit_ignore','supervisor_create_module_writable_consumption_head_ignore','supervisor_create_module_writable_manual_challenge_record_ignore','supervisor_create_module_writable_manual_challenge_commit_ignore','supervisor_create_module_writable_manual_challenge_response_ignore','supervisor_create_module_writable_manual_challenge_checks','supervisor_create_module_writable_evidence_checks','supervisor_create_module_writable_evidence_cut_ignore','supervisor_create_module_writable_evidence_record_ignore','supervisor_create_module_writable_evidence_commit_ignore','supervisor_create_module_writable_evidence_head_ignore','supervisor_create_module_writable_evidence_resource_checks','supervisor_create_module_writable_evidence_resource_record_ignore','supervisor_create_module_writable_evidence_resource_commit_ignore','supervisor_create_module_writable_evidence_resource_open_checks','supervisor_create_module_writable_evidence_resource_open_record_ignore','supervisor_create_module_writable_evidence_resource_open_commit_ignore',"supervisor_create_module_writable_evidence_resource_open_dispatch","supervisor_create_module_writable_evidence_resource_open_dispatch_stale","supervisor_create_module_writable_evidence_resource_open_dispatch_expired","supervisor_create_module_writable_evidence_resource_open_dispatch_request_ignore","supervisor_create_module_writable_evidence_resource_open_dispatch_ack_ignore","supervisor_create_module_writable_evidence_resource_open_dispatch_ready","supervisor_create_module_writable_evidence_resource_open_dispatch_ready_stale","supervisor_create_module_writable_evidence_resource_open_dispatch_ready_expired","supervisor_create_module_writable_evidence_resource_open_dispatch_ready_ignore","supervisor_create_module_writable_evidence_resource_open_dispatch_ready_control_ignore",...commandAdmissionFaults,...commandLifecycleFaults,...commandLifecycleCases,...commandEncodingCases].includes(mode);let runtimeInput=null;
  const writable=mode.startsWith('supervisor_create_module_writable'),requestedActions=writable?['leafseamer.simulator.value.set']:['get','set'],proposedActions=writable?requestedActions:['get'];
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
    artifact.manifest.permission_templates=[{request_id:'device.request',kind:'device_scope',purpose:'请求设备动作',scope:{device_role:'device',action_ids:requestedActions,trigger_ids:[]}}];
  }
  if(usesCapabilities){
    const template=JSON.parse(fs.readFileSync(writable?path.join(controller,'dist/simulator-control-capability.json'):new URL('./fixtures/static-capability.json',import.meta.url)));
    if(mode==='supervisor_create_module_writable_catalog_template')template.actions[0].completion.default='acknowledged';
    if(!writable&&mode.startsWith('supervisor_create_module')&&mode!=='supervisor_create_module_catalog_template')template.state_schema=(await load('simulator-module.mjs')).simulatorCatalog().state_schema;
    const bytes=Buffer.from(JSON.stringify(template)),file={path:'payload/capability.json',role:'schema',bytes};
    artifact.payload.set('capability',file);artifact.inventory.files.push({file_id:'capability',path:file.path,size_bytes:String(bytes.length),
      digest:'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex'),role:file.role,executable:false});
    artifact.inventory.files.sort((a,b)=>a.file_id<b.file_id?-1:1);artifact.manifest.capability_template_file_ids=['capability'];
  }
  if(usesConfiguration){
    const bytes=Buffer.from(JSON.stringify(writable?{type:'object',additionalProperties:false}:{type:'object',properties:{count:{type:'integer',minimum:1,maximum:4}},required:['count'],additionalProperties:false}));
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
    const module=artifact.payload.get('worker');module.bytes=fs.readFileSync(path.join(controller,writable?'dist/simulator-control-module.mjs':'dist/simulator-module.mjs'));
    Object.assign(artifact.inventory.files.find(f=>f.file_id==='worker'),{size_bytes:String(module.bytes.length),digest:'sha256:'+crypto.createHash('sha256').update(module.bytes).digest('hex')});
    const policy=artifact.payload.get('policy');policy.bytes=mode==='supervisor_create_module_catalog_policy'?Buffer.from('{"network":false}'):fs.readFileSync(path.join(controller,writable&&mode!=='supervisor_create_module_writable_catalog_policy'?'dist/simulator-control-policy.json':'dist/simulator-policy.json'));
    Object.assign(artifact.inventory.files.find(f=>f.file_id==='policy'),{size_bytes:String(policy.bytes.length),digest:'sha256:'+crypto.createHash('sha256').update(policy.bytes).digest('hex')});
    artifact.manifest.api_versions=writable?['leafseamer-device-module/2','leafseamer-device-primitives/1']:['leafseamer-device-module/2'];artifact.manifest.ipc_versions=['device-module/3'];
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
    const schema=mode.endsWith('_cleanup_successor')?57:mode.includes('_closure_cleanup')?56:mode.includes('_dispatch_closure')?55:mode.includes('_guard_dispatch')?54:mode.includes('_t2_guard')?53:mode.includes('_encoding_t2')?52:commandEncodingCases.includes(mode)?51:50;const migration=await migrateStorage(core,schema);assert.equal(migration.schema_revision,String(schema));
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
        configurationRequest={request_id:'configuration.synthetic',installation_ref:result.installation_ref,expected_revision:'0',bytes:Buffer.from(writable?'{}':'{"count":2}')};
        configured=await installations.configurations.configure(configurationRequest);assert.deepEqual(configured.record.configuration,writable?{}:{count:2});
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
            const proposed=structuredClone(resolved.record.permissions);proposed[0].scope.action_ids=proposedActions;
            reviewRequest={request_id:'review.synthetic',installation_ref:result.installation_ref,configuration_ref:configured.configuration_ref,
              role_resolution_ref:resolved.resolution_ref,expected_revision:'0',proposed_permissions:proposed};
            reviewed=await installations.reviews.review(reviewRequest);assert.deepEqual(reviewed.record.proposed_permissions[0].scope.action_ids,proposedActions);
            assert.deepEqual(reviewed.record.requested_permissions[0].scope.action_ids,requestedActions);
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
  const catalogFailure=mode.includes('_catalog_'),baselineFailure=mode.includes('_baseline_');
  const bindingFailure=mode.includes('_binding_'),handshakeFailure=mode.includes('_handshake_'),controlFenceFailure=mode.includes('_control_fence_');
  const readyMode=mode.includes('_open_dispatch_ready'),commandFailure=commandAdmissionFaults.includes(mode),lifecycleFailure=commandLifecycleFaults.includes(mode),encodingFailure=commandEncodingCases.includes(mode)&&mode.endsWith('_ignore'),finalFailure=Object.hasOwn(finalAdmissionOmissions,mode),observationFailure=mode.endsWith('_t2_observation_omit'),guardFailure=Object.hasOwn(guardOmissions,mode);
  const dispatchMode=mode.includes('_open_dispatch'),dispatchFailure=dispatchMode&&!readyMode&&(mode.endsWith('_request_ignore')||mode.endsWith('_ack_ignore'));
  const openingMode=mode.includes('_resource_open_'),openingFailure=openingMode&&!dispatchMode&&!mode.endsWith('_checks');
  const resourceMode=mode.includes('_resource_'),resourceFailure=resourceMode&&!openingMode&&!mode.endsWith('_checks');
  if(commandFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const table=mode.endsWith('_source_ignore')?'command_admission_source':'ca_notification';
      db.exec('CREATE TRIGGER injected_command_omission BEFORE INSERT ON '+table+' BEGIN SELECT RAISE(IGNORE); END;');
    }finally{db.close();}
  }
  if(encodingFailure){
    const db=new Database(path.join(core,'controller.sqlite'));try{const table=mode.endsWith('_request_ignore')?'command_encoding_request':'command_encoding_response';
      db.exec('CREATE TRIGGER injected_encoding_omission BEFORE INSERT ON '+table+' BEGIN SELECT RAISE(IGNORE); END;');
    }finally{db.close();}
  }
  if(finalFailure){const db=new Database(path.join(core,'controller.sqlite'));try{
    const table=finalAdmissionOmissions[mode],when=table.startsWith('command_lifecycle_')?' WHEN EXISTS(SELECT 1 FROM command_final_admission f WHERE f.command_id=NEW.command_id)':'';
    db.exec('CREATE TRIGGER injected_final_omission BEFORE INSERT ON '+table+when+' BEGIN SELECT RAISE(IGNORE); END;');
  }finally{db.close();}}
  if(guardFailure){const db=new Database(path.join(core,'controller.sqlite'));try{
    const table=guardOmissions[mode],when=table==='execution_effect_commit'?" WHEN json_extract(NEW.audit_jcs,'$.kind') IN('command_guard_request','command_guard_response')":'';
    db.exec('CREATE TRIGGER injected_guard_omission BEFORE INSERT ON '+table+when+' BEGIN SELECT RAISE(IGNORE); END;');
  }finally{db.close();}}
  if(observationFailure){const db=new Database(path.join(core,'controller.sqlite'));try{
    db.exec('CREATE TRIGGER injected_observation_omission BEFORE INSERT ON command_final_observation BEGIN SELECT RAISE(IGNORE); END;');
  }finally{db.close();}}
  if(lifecycleFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const table=mode.endsWith('_commit_ignore')?'command_lifecycle_commit':'command_lifecycle_head';
      db.exec('CREATE TRIGGER injected_lifecycle_omission BEFORE INSERT ON '+table+' BEGIN SELECT RAISE(IGNORE); END;');
    }finally{db.close();}
  }
  if(readyMode&&mode.endsWith('_ignore')&&!commandFailure&&!lifecycleFailure&&!encodingFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      if(mode.endsWith('_control_ignore'))db.exec("CREATE TRIGGER injected_ready_control BEFORE INSERT ON control_change_commit WHEN NEW.kind='ready' BEGIN SELECT RAISE(IGNORE); END;");
      else db.exec('CREATE TRIGGER injected_ready_record BEFORE INSERT ON device_initial_ready BEGIN SELECT RAISE(IGNORE); END;');
    }finally{db.close();}
  }
  if(dispatchFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const table=mode.endsWith('_request_ignore')?'execution_initial_open_dispatch':'execution_initial_open_ack';
      db.exec('CREATE TRIGGER injected_open_dispatch_omission BEFORE INSERT ON '+table+' BEGIN SELECT RAISE(IGNORE); END;');
    }finally{db.close();}
  }
  if(openingFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const table=mode.endsWith('_record_ignore')?'device_initial_open':'device_initial_open_commit';
      db.exec('CREATE TRIGGER injected_opening_omission BEFORE INSERT ON '+table+' BEGIN SELECT RAISE(IGNORE); END;');
    }finally{db.close();}
  }
  if(resourceFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const table=mode.endsWith('_record_ignore')?'device_initial_resource':'device_initial_resource_commit';
      db.exec('CREATE TRIGGER injected_resource_omission BEFORE INSERT ON '+table+' BEGIN SELECT RAISE(IGNORE); END;');
    }finally{db.close();}
  }
  const evidenceMode=!resourceMode&&mode.includes('_evidence_'),evidenceFailure=evidenceMode&&!mode.endsWith('_checks');
  if(evidenceFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{const table=mode.includes('_cut_')?'device_authorization_revocation_cut':mode.includes('_record_')?'device_authorization_evidence':mode.includes('_commit_')?'device_authorization_evidence_commit':'device_authorization_evidence_head';
      db.exec(`CREATE TRIGGER evidence_fault BEFORE INSERT ON ${table} BEGIN SELECT RAISE(IGNORE); END`);
    }finally{db.close();}
  }
  const manualAuthorityFailure=mode.includes('_manual_authority_');
  const manualChallengeFailure=mode.includes('_manual_challenge_')&&!mode.endsWith('_checks');
  if(manualChallengeFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{const table=mode.includes('_response_')?'manual_execution_challenge_response':mode.includes('_commit_')?'manual_execution_challenge_commit':'manual_execution_challenge';
      db.exec(`CREATE TRIGGER manual_challenge_fault BEFORE INSERT ON ${table} BEGIN SELECT RAISE(IGNORE); END`);
    }finally{db.close();}
  }
  const evaluatorFailure=mode.includes('_evaluator_');
  const recoveryFailure=mode.includes('_recovery_');
  const consumptionFailure=mode.includes('_consumption_');
  if(consumptionFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{const table=mode.includes('_record_')?'device_recovery_consumption':mode.includes('_state_')?'device_authorization_state':mode.includes('_commit_')?'device_authorization_commit':'device_authorization_head';
      const when=table==='device_authorization_state'?"WHEN json_extract(NEW.body_jcs,'$.status')='policy_selected'":
        table==='device_authorization_commit'?"WHEN json_extract(NEW.body_jcs,'$.format_version')='device-authorization-selection-commit/1'":
        table==='device_authorization_head'?"WHEN NEW.state_id IN (SELECT state_id FROM device_authorization_state WHERE json_extract(body_jcs,'$.status')='policy_selected')":'';
      db.exec(`CREATE TRIGGER consumption_fault BEFORE ${table==='device_authorization_head'?'UPDATE':'INSERT'} ON ${table} ${when} BEGIN SELECT RAISE(IGNORE); END`);
    }finally{db.close();}
  }
  if(recoveryFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{const table=mode.includes('_request_')?'device_recovery_request':mode.includes('_authorization_')?'device_recovery_authorization':'device_recovery_commit';
      db.exec(`CREATE TRIGGER recovery_fault BEFORE INSERT ON ${table} BEGIN SELECT RAISE(IGNORE); END`);
    }finally{db.close();}
  }
  if(evaluatorFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      db.exec(mode.endsWith('source_fail')?"CREATE TRIGGER evaluator_fault BEFORE INSERT ON device_evaluator_source BEGIN SELECT RAISE(ABORT,'synthetic_evaluator'); END":
        "CREATE TRIGGER evaluator_fault BEFORE INSERT ON device_evaluator_operation WHEN NEW.kind='source' BEGIN SELECT RAISE(IGNORE); END");
    }finally{db.close();}
  }
  if(manualAuthorityFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const table=mode.includes('_core_')?(mode.endsWith('source_fail')?'core_runtime_source':'core_runtime_source_commit'):
        (mode.endsWith('source_fail')?'execution_manual_authority':'execution_manual_authority_commit');
      db.exec(`CREATE TRIGGER authority_fault BEFORE INSERT ON ${table} BEGIN SELECT RAISE(${mode.endsWith('source_fail')?"ABORT,'synthetic_authority'":'IGNORE'}); END`);
    }finally{db.close();}
  }
  if(controlFenceFailure){
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      if(mode.endsWith('request_fail'))db.exec("CREATE TRIGGER control_fault BEFORE INSERT ON execution_control_frame WHEN NEW.phase='request' BEGIN SELECT RAISE(ABORT,'synthetic_control_request'); END");
      else if(mode.endsWith('ack_ignore'))db.exec("CREATE TRIGGER control_fault BEFORE INSERT ON execution_control_frame WHEN NEW.phase='ack' BEGIN SELECT RAISE(IGNORE); END");
      else db.exec("CREATE TRIGGER control_fault BEFORE INSERT ON execution_write_attempt WHEN (SELECT message_type FROM execution_frame_record WHERE record_id=NEW.record_id)='FENCE' BEGIN SELECT RAISE(IGNORE); END");
    }finally{db.close();}
  }
  if(handshakeFailure){
    const fault=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{fault.exec(`CREATE TRIGGER handshake_fault BEFORE INSERT ON ${mode.endsWith('ignore')?'execution_write_attempt':'execution_handshake_frame'} BEGIN SELECT RAISE(${mode.endsWith('ignore')?'IGNORE':"ABORT,'synthetic_handshake_commit'"}); END`);}finally{fault.close();}
  }
  if(bindingFailure){
    const fault=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{fault.exec(`CREATE TRIGGER binding_fault BEFORE INSERT ON device_execution_binding_commit BEGIN SELECT RAISE(${mode.endsWith('ignore')?'IGNORE':"ABORT,'synthetic_binding_commit'"}); END`);}finally{fault.close();}
  }
  if((catalogFailure&&!mode.endsWith('template')&&!mode.endsWith('policy'))||baselineFailure){
    const fault=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{fault.exec(`CREATE TRIGGER catalog_fault BEFORE INSERT ON ${catalogFailure?'device_catalog_approval':'device_baseline_sample'} BEGIN SELECT RAISE(${mode.endsWith('ignore')?'IGNORE':"ABORT,'synthetic_catalog_commit'"}); END`);}finally{fault.close();}
  }
  if(moduleStorageFailure){
    const fault=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{fault.exec(`CREATE TRIGGER module_candidate_fault BEFORE INSERT ON device_module_frame_commit
      WHEN (SELECT message_type FROM device_module_frame WHERE message_id=NEW.message_id)='CAPTURED'
      BEGIN SELECT RAISE(${mode.endsWith('ignore')?'IGNORE':"ABORT,'synthetic_module_commit'"}); END`);}finally{fault.close();}
  }
  if(commandDispatchFailure||settlementFailure||cleanupFailure){const {table,operation,condition}=commandDispatchFailure??settlementFailure??cleanupFailure;const fault=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
    try{fault.exec(`CREATE TRIGGER dispatch_fault BEFORE ${operation} ON ${table}${condition?' WHEN '+condition:''} BEGIN SELECT RAISE(IGNORE); END`);}finally{fault.close();}}
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
  const fixture=path.join(root,'fixture.json');fs.writeFileSync(fixture,JSON.stringify({binding,mode,materials,runtime:runtimeInput,
    ...((mode==='supervisor_create_module_writable_evidence_resource_open_dispatch_ready'||commandLifecycleCases.includes(mode)||commandEncodingCases.includes(mode))?{command_tls:certificate()}:{})}));
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
  try{await waitFor(()=>frames.find(f=>f.event==='done')||child.exitCode!==null,30000);}
  catch(error){error.message+=' '+JSON.stringify({events:frames.map(({event,code,cause,reported_ms})=>({event,code,cause,reported_ms})),stderr});throw error;}
  const done=frames.find(f=>f.event==='done');assert.ok(done,JSON.stringify({frames,stdout,stderr}));
  if(mode==='supervisor_create_module_control'){
    assert.equal(frames.find(f=>f.event==='unavailable'),undefined,JSON.stringify(frames));
    const results=frames.filter(f=>f.event==='control-result');assert.equal(results.length,2,JSON.stringify(frames));
    assert.equal(results[0].operation.state,'effective');assert.equal(results[0].control.mode,'manual');assert.ok(results[0].control.holder);assert.equal(results[0].control.effective_version,'1');
    assert.equal(results[1].operation.state,'effective');assert.equal(results[1].control.mode,'automatic');assert.equal(results[1].control.holder,null);assert.equal(results[1].control.effective_version,'2');
    assert.ok(results.every(v=>v.control.gate_state==='protected'&&v.control.pending_change===null));
    assert.ok(frames.filter(f=>f.event==='control-replay').every(v=>v.replay.replay));
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM control_request').pluck().get(),2);assert.equal(db.prepare('SELECT count(*) FROM control_barrier_evidence').pluck().get(),2);
      const proofs=db.prepare('SELECT body_jcs FROM control_barrier_evidence').pluck().all().map(JSON.parse);
      assert.ok(proofs.every(v=>v.targets.length===1&&v.receipts.length===1&&v.receipts[0].retirement.result==='confirmed_empty'));
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(consumptionFailure){
    assert.equal(frames.find(f=>f.event==='unavailable')?.code,'control_authorization_selection_storage');
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    assert.ok(frames.find(f=>f.event==='recovery-accepted'));assert.equal(frames.find(f=>f.event==='recovery-consumed'),undefined);
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM device_recovery_consumption').pluck().get(),0);
      for(const table of ['device_recovery_request','device_recovery_authorization','device_recovery_commit','device_authorization_state','device_authorization_commit'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),2);
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
      assert.equal(db.prepare("SELECT json_extract(s.body_jcs,'$.status') FROM device_authorization_head h JOIN device_authorization_state s USING(state_id)").pluck().get(),'protected');
    }finally{db.close();}return;
  }
  if(recoveryFailure){
    assert.equal(frames.find(f=>f.event==='unavailable')?.code,'device_recovery_storage');
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    assert.equal(frames.find(f=>f.event==='recovery-accepted'),undefined);
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      for(const table of ['device_recovery_request','device_recovery_authorization','device_recovery_commit'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),0);
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
      assert.equal(db.prepare("SELECT json_extract(body_jcs,'$.status') FROM device_authorization_state ORDER BY revision DESC LIMIT 1").pluck().get(),'protected');
    }finally{db.close();}return;
  }
  if(evaluatorFailure){
    assert.equal(frames.find(f=>f.event==='unavailable')?.code,mode.endsWith('source_fail')?'SQLITE_CONSTRAINT_TRIGGER':'evaluator_source_storage');
    assert.equal(frames.find(f=>f.event==='evaluator-source'),undefined);assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM device_evaluator_source').pluck().get(),0);
      assert.equal(db.prepare("SELECT count(*) FROM device_evaluator_operation WHERE kind='source'").pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM device_evaluator_challenge').pluck().get(),1);
      assert.equal(db.prepare('SELECT count(*) FROM ca_adjudication').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM worker_runtime_withdrawal').pluck().get(),1);assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(readyMode){
    const unavailable=frames.find(f=>f.event==='unavailable'),ready=frames.find(f=>f.event==='initial-ready');
    if(mode.endsWith('_cleanup_successor')){
      assert.equal(unavailable,undefined,JSON.stringify({unavailable,events:frames.map(({event,stage,code,reason,remaining_ms,reported_ms})=>({event,stage,code,reason,remaining_ms,reported_ms})),failures:frames.filter(f=>f.event==='worker_gate_failure')}));const next=frames.find(f=>f.event==='successor-command'),resource=frames.find(f=>f.event==='successor-resource');
      assert.ok(next&&resource);assert.equal(next.accepted.status,202);assert.equal(next.current.status,200);assert.equal(next.replayed.status,200);
      assert.equal(next.current.body.record.state.outcome,'succeeded');assert.equal(next.current.body.record.state.resource_status,'clear');assert.equal(next.current.body.record.accepted_at,null);
      assert.equal(resource.resource.value.format,'leafseamer-device-resource-successor/1');assert.equal(resource.resource.value.inventory.observed_write_sequence,'1');
      assert.equal(resource.resource.value.inventory.retired_preparation_refs.length,1);assert.equal(next.closed.ack.frame.body.transmission_coverage.length,2);
      assert.equal(next.closed.ack.frame.body.issued_cut_revision,'2');assert.equal(next.cleaned.steps.release_ack.frame.body.cache_empty,true);
      child.stdin.write('stop\n');await ended;const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
      try{
        for(const table of ['command_final_admission','command_settlement','command_hold_release','command_device_hold','command_transmission_issue','command_preparation_retirement','device_initial_open'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),2,table);
        assert.equal(db.prepare('SELECT count(*) FROM command_preparation_cleanup').pluck().get(),8);assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),16);
        const {readCommandRecord}=await load('command-record-store.mjs');for(const id of db.prepare('SELECT command_id FROM command_settlement').pluck().all()){
          const saved=db.transaction(()=>readCommandRecord(db,id)).immediate();assert.equal(saved.record.state.outcome,'succeeded');assert.equal(saved.record.revision,'5');}
        const observations=db.prepare('SELECT f.frame_jcs FROM command_dispatch_evidence e JOIN execution_frame_record f USING(record_id) ORDER BY f.sequence').pluck().all().map(v=>JSON.parse(v).body.payload.observation.response);
        assert.deepEqual(observations,[{value:7,write_sequence:'1'},{value:23,write_sequence:'2'}]);assert.deepEqual(db.pragma('foreign_key_check'),[]);
      }finally{db.close();}return;
    }
    if(mode.endsWith('_closure_late')||mode.endsWith('_cleanup_late')){
      assert.equal(unavailable,undefined,JSON.stringify(unavailable));const history=frames.find(v=>v.event==='command-history'),closed=frames.find(v=>v.event==='command-closed');
      assert.ok(history&&closed);assert.equal(history.http_status,200);assert.equal(history.current.record.state.phase,'finished');assert.equal(history.current.record.state.outcome,'unknown');
      assert.equal(history.current.record.state.resource_status,'unresolved');assert.equal(history.current.record.state.effect_status,'possible');assert.equal(history.current.record.state.automation_continuation,'paused_latched');
      assert.equal(history.current.record.completion.achieved,null);assert.equal(history.current.record.evidence_index.total,'1');assert.equal(history.current.record.attempts[0].outcome,'unknown');
      child.stdin.write('stop\n');await ended;const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
      try{assert.equal(db.prepare('SELECT count(*) FROM command_hold_release').pluck().get(),0);assert.equal(db.prepare('SELECT count(*) FROM command_device_hold').pluck().get(),1);
       const s=JSON.parse(db.prepare('SELECT body_jcs FROM command_settlement').pluck().get()),received=db.prepare('SELECT f.observed_tick FROM command_dispatch_evidence e JOIN execution_frame_record f USING(record_id)').pluck().get();
       assert.ok(BigInt(received)>=BigInt(s.module_settlement.evidence_deadline_tick_ns));assert.equal(s.module_settlement.module_settled,false);
       if(mode.endsWith('_cleanup_late')){const cleaned=frames.find(f=>f.event==='command-cleaned');assert.ok(cleaned);
        assert.equal(cleaned.value.steps.release_ack.frame.body.cache_empty,true);
        assert.equal(db.prepare('SELECT count(*) FROM command_preparation_cleanup').pluck().get(),4);
        assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),8);}
       assert.deepEqual(db.pragma('foreign_key_check'),[]);
      }finally{db.close();}return;
    }
    if(cleanupFailure){
      assert.ok(ready);assert.equal(unavailable?.code,'preparation_cleanup_storage',JSON.stringify(unavailable));assert.equal(unavailable.execution_state.phase,'closed');
      child.stdin.write('stop\n');await ended;const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
      try{const phases=['deny_request','deny_ack','release_request','release_ack'],completed=phases.indexOf(cleanupFailure.phase);
        assert.deepEqual(db.prepare('SELECT phase FROM command_preparation_cleanup ORDER BY rowid').pluck().all(),phases.slice(0,completed));
        assert.equal(db.prepare('SELECT count(*) FROM command_preparation_retirement').pluck().get(),+(completed>0));
        assert.equal(db.prepare("SELECT count(*) FROM execution_dispatch_frame WHERE phase IN('deny_request','deny_ack','release_request','release_ack')").pluck().get(),completed);
        assert.equal(db.prepare('SELECT count(*) FROM execution_write_attempt w JOIN command_preparation_cleanup c ON c.record_id=w.record_id').pluck().get(),Math.ceil(completed/2));
        const {readCommandRecord}=await load('command-record-store.mjs'),id=db.prepare('SELECT command_id FROM command_settlement').pluck().get(),saved=db.transaction(()=>readCommandRecord(db,id)).immediate();
        assert.equal(saved.record.revision,'5');assert.equal(saved.record.state.outcome,'succeeded');assert.equal(saved.record.state.resource_status,'clear');
        assert.equal(db.prepare('SELECT count(*) FROM command_hold_release').pluck().get(),1);assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),8);
        assert.deepEqual(db.pragma('foreign_key_check'),[]);
      }finally{db.close();}return;
    }
    if(settlementFailure){
      assert.ok(ready);assert.match(unavailable?.code??'',/^(command_settlement_storage|execution_closure_storage)$/);assert.equal(unavailable.execution_state.phase,'closed');
      child.stdin.write('stop\n');await ended;const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});
      try{const part=settlementFailure.part,requested=part!=='request',wrote=requested&&part!=='write',acknowledged=wrote&&part!=='ack';
        assert.equal(db.prepare('SELECT count(*) FROM command_closure_request').pluck().get(),+requested);
        assert.equal(db.prepare('SELECT count(*) FROM command_closure_ack').pluck().get(),+acknowledged);
        assert.equal(db.prepare('SELECT count(*) FROM execution_write_attempt w JOIN command_closure_request c ON c.record_id=w.record_id').pluck().get(),+wrote);
        for(const table of ['command_settlement','command_evidence_record','command_hold_release'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),0);
        const {readCommandRecord}=await load('command-record-store.mjs'),id=db.prepare('SELECT command_id FROM command_final_admission').pluck().get(),saved=db.transaction(()=>readCommandRecord(db,id)).immediate();
        assert.equal(saved.record.revision,'4');assert.equal(saved.record.state.outcome,'pending');assert.equal(saved.record.state.resource_status,'held');assert.equal(saved.record.state.effect_status,'possible');
        assert.equal(db.prepare('SELECT count(*) FROM command_device_hold').pluck().get(),1);assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),8);
        assert.equal(db.prepare('SELECT count(*) FROM command_lifecycle_revision').pluck().get(),3);assert.equal(db.prepare('SELECT count(*) FROM command_lifecycle_commit').pluck().get(),3);
        assert.deepEqual(db.pragma('foreign_key_check'),[]);
      }finally{db.close();}return;
    }
    if(commandDispatchFailure){
      assert.ok(ready);assert.equal(unavailable?.code,'command_dispatch_storage',JSON.stringify(unavailable));
      assert.equal(unavailable.execution_state.phase,'closed');assert.equal(unavailable.execution_state.close_failure,null);
      assert.equal(frames.find(f=>f.event==='command-dispatched'),undefined);child.stdin.write('stop\n');await ended;
      const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
        const part=commandDispatchFailure.part,requested=!['request','frame','effect'].includes(part),wrote=requested&&!['write','write_commit','write_head'].includes(part),reported=wrote&&part==='evidence';
        for(const [table,n]of [['command_dispatch_request',+requested],['command_dispatch_write',+wrote],['command_dispatch_report',+reported],['command_dispatch_evidence',0]])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),n,part+':'+table);
        assert.equal(db.prepare('SELECT count(*) FROM execution_dispatch_frame').pluck().get(),+requested+ +reported);
        assert.equal(db.prepare("SELECT count(*) FROM execution_write_attempt w JOIN execution_frame_record f USING(record_id) WHERE f.message_type='DISPATCH'").pluck().get(),+wrote);
        assert.equal(db.prepare('SELECT count(*) FROM command_device_hold').pluck().get(),1);assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),8);
        const {readCommandRecord}=await load('command-record-store.mjs'),id=db.prepare('SELECT command_id FROM command_final_admission').pluck().get(),record=db.transaction(()=>readCommandRecord(db,id)).immediate().record;
        const revision=reported?4:wrote?3:2;assert.equal(record.revision,String(revision));assert.equal(record.accepted_at,null);
        assert.equal(record.state.phase,reported?'awaiting_evidence':wrote?'dispatching':'queued');assert.equal(record.state.effect_status,wrote?'possible':'not_sent');
        assert.equal(record.state.outcome,'pending');assert.equal(record.state.resource_status,'held');assert.equal(record.attempts.length,1);
        assert.equal(db.prepare('SELECT count(*) FROM command_lifecycle_commit').pluck().get(),revision-1);
        assert.equal(db.prepare('SELECT count(*) FROM command_lifecycle_revision').pluck().get(),revision-1);
        assert.deepEqual(db.pragma('foreign_key_check'),[]);
      }finally{db.close();}return;
    }

    const expired=mode.endsWith('_expired'),omission=mode.endsWith('_ignore')&&!commandFailure&&!lifecycleFailure&&!encodingFailure,stale=mode.endsWith('_stale');
    if(!omission)assert.ok(frames.find(f=>f.event==='open-confirmed'),JSON.stringify(unavailable));
    else assert.equal(frames.find(f=>f.event==='open-confirmed'),undefined);
    if(commandFailure)assert.equal(unavailable?.code,'command_storage',JSON.stringify(unavailable));
    else if(encodingFailure)assert.equal(unavailable?.code,'execution_encoding_storage',JSON.stringify({unavailable,diagnostics:frames.filter(f=>['ready-window','http-command-error'].includes(f.event))}));
    else if(finalFailure)assert.equal(unavailable?.code,'command_final_storage',JSON.stringify({unavailable,diagnostics:frames.filter(f=>['ready-window','http-command-error'].includes(f.event))}));
    else if(guardFailure)assert.equal(unavailable?.code,'command_guard_storage',JSON.stringify(unavailable));
    else if(observationFailure)assert.equal(unavailable?.code,'command_final_observer_storage',JSON.stringify(unavailable));
    else if(lifecycleFailure){assert.equal(unavailable?.code,'command_lifecycle_unavailable',JSON.stringify(unavailable));assert.equal(unavailable?.cause,'command_lifecycle_storage');}
    else if(expired)assert.ok(unavailable&&/expired|not_current|session_ended|closed/.test(unavailable.code),JSON.stringify(unavailable));
    else if(omission)assert.ok(unavailable&&/storage/.test(unavailable.code),JSON.stringify(unavailable));
    else if(stale){assert.ok(unavailable&&['initial_resource_changed','module_channel_closed'].includes(unavailable.code),JSON.stringify(unavailable));
      assert.equal(unavailable.execution_state.close_reason,'initial_resource_changed',JSON.stringify(unavailable));
      assert.equal(unavailable.execution_state.close_failure,null);}
    else assert.equal(unavailable,undefined,JSON.stringify(frames.map(({event,code,stage,remaining_ms,reported_ms,message,reason,error,error_name})=>({event,code,stage,remaining_ms,reported_ms,message,reason,error,error_name}))));
    if(!expired&&!omission){assert.ok(ready);assert.equal(ready.control.gate_state,'ready');
      const plan=frames.find(f=>f.event==='initial-open').value.value;
      assert.deepEqual(ready.value.value.control_before_ref,plan.plan.state_refs.control);
      assert.deepEqual(ready.value.value.eligibility_refs.authorization,plan.access.authorization_ref);
      if(commandFailure)assert.equal(frames.find(f=>f.event==='command-accepted'),undefined);
      else if(encodingFailure){assert.equal(frames.find(f=>f.event==='command-accepted')?.accepted.adjudication.decision,'accepted');assert.equal(frames.find(f=>f.event==='command-encoded'),undefined);}
      else if(finalFailure||observationFailure){assert.equal(frames.find(f=>f.event==='command-encoded')?.disposition,'prepared');assert.equal(frames.find(f=>f.event==='command-final-admission'),undefined);}
      else if(guardFailure){assert.ok(frames.find(f=>f.event==='command-final-admission'));assert.equal(frames.find(f=>f.event==='command-guard-installed'),undefined);}
      else if(lifecycleFailure){assert.equal(frames.find(f=>f.event==='command-accepted')?.accepted.adjudication.decision,'accepted');assert.equal(frames.find(f=>f.event==='command-history'),undefined);}
      else if(!stale){const stopped=frames.find(f=>f.event==='ready-expired');assert.equal(stopped?.state.phase,mode.includes('_dispatch_closure')?'ready':'closed');assert.deepEqual(stopped?.state.ready_devices,[]);assert.equal(stopped?.state.close_failure,null,JSON.stringify(stopped?.state));assert.equal(stopped?.control.gate_state,'protected');
        const command=frames.find(f=>f.event==='command-accepted');assert.ok(command);
        assert.equal(command.accepted.replay,false);assert.equal(command.replayed.replay,true);
        assert.equal(command.accepted.adjudication.decision,'accepted');assert.deepEqual(command.accepted.adjudication,command.replayed.adjudication);
        assert.equal(command.current.record.accepted_at,null);assert.ok((commandSettled?['finished']:commandDispatch?['awaiting_evidence']:['queued','finished']).includes(command.current.record.state.phase));
        assert.equal(command.current.record.state.effect_status,commandSettled?'verified':commandDispatch?'possible':'not_sent');assert.ok(mode.includes('_encoding_t2')?[0,1].includes(command.current.record.attempts.length):command.current.record.attempts.length===0);
        assert.deepEqual(command.current.record.initial_command_ref,command.accepted.adjudication.command_ref);
        assert.ok([[202,200,200],[202,200,503,200]].some(v=>JSON.stringify(v)===JSON.stringify(command.http_statuses)),JSON.stringify(command.http_statuses));
        if(commandEncodingCases.includes(mode)){
          const encoded=frames.find(f=>f.event==='command-encoded');assert.ok(encoded);assert.equal(encoded.disposition,'prepared');
          assert.equal(encoded.packet.command_id,command.accepted.adjudication.command_ref.object_id);
          const bytes=Buffer.from(encoded.bytes_hex,'hex');assert.equal(bytes.length,8);assert.equal(bytes.subarray(0,4).toString('ascii'),'LSM1');
          assert.equal(bytes.readInt32BE(4),command.request.parameters.value);assert.deepEqual(encoded.original_ref,encoded.replay_ref);
          const schema=JSON.parse(fs.readFileSync(new URL('../docs/contracts/c08-controller/encoding-authority.schema.json',import.meta.url))).$defs.EncodingEvidence;
          const {evidence_digest,...unsigned}=encoded.evidence;
          assert.deepEqual(Object.keys(encoded.evidence).sort(),schema.required.slice().sort());
          assert.equal(evidence_digest,'sha256:'+crypto.createHash('sha256').update(canonicalize(unsigned)).digest('hex'));
          assert.deepEqual(encoded.evidence.binding,ready.value.value.binding);
          assert.deepEqual(encoded.evidence.packet_ref,{packet_id:encoded.packet.packet_id,packet_digest:encoded.packet.packet_digest});
          assert.equal(encoded.evidence.bytes_digest,'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex'));
          assert.equal(encoded.evidence.byte_length,8);assert.equal(encoded.evidence.revision,'1');
          const selected=frames.find(f=>f.event==='command-finalization-inputs')?.value;
          if(mode.includes('_encoding_t2')){assert.equal(selected,undefined);}
          else if(mode.endsWith('_changed_input')){
            assert.equal(selected,undefined);
            assert.equal(frames.find(f=>f.event==='command-finalization-rejected')?.code,'initial_resource_changed');
          }else{assert.ok(selected);
          assert.equal(selected.command_id,encoded.packet.command_id);assert.deepEqual(selected.encoding_ref,encoded.original_ref);
          assert.deepEqual(selected.packet_ref,encoded.evidence.packet_ref);assert.equal(selected.bytes_digest,encoded.evidence.bytes_digest);
          assert.equal(selected.byte_length,8);assert.equal(selected.command_state_ref.revision,'1');
          assert.equal(selected.authorization_binding.principal_kind,'human');assert.equal(selected.authorization_binding.origin,'manual');
          for(const key of ['issuer_id','issuer_epoch','principal_id','session_id'])assert.equal(selected.authorization_binding[key],command.current.record.actor[key]);
          assert.equal(selected.authorization_binding.policy_revision,command.current.record.actor.authorization_revision);
          for(const key of ['subject_revision','session_revision','policy_revision'])assert.match(selected.authorization_binding[key],/^[1-9][0-9]*$/);
          for(const key of ['grant_id','grant_revision','arm_generation','extension_instance_id','extension_approval_revision'])assert.equal(selected.authorization_binding[key],null);
          assert.deepEqual(selected.encoding_evidence_ref,{id:encoded.evidence.evidence_id,revision:'1',digest:evidence_digest});
          assert.ok(BigInt(selected.send_window.not_before_tick_ns)<=BigInt(selected.selected_tick_ns));
          assert.ok(BigInt(selected.selected_tick_ns)<BigInt(selected.send_window.before_tick_ns));
          }
        }
        const history=frames.find(f=>f.event==='command-history'),finalized=mode.endsWith('_t2')||mode.includes('_t2_guard');assert.equal(history.http_status,200);assert.equal(history.current.record.state.phase,commandSettled?'finished':commandDispatch?'awaiting_evidence':finalized?'queued':'finished');
        assert.equal(history.current.record.state.outcome,commandSettled?'succeeded':finalized?'pending':mode.endsWith('_queue_deadline')?'expired':'blocked');
        if(mode.endsWith('_queue_deadline'))assert.equal(history.current.record.state.reason_code,'queue_expired');
        if(mode.endsWith('_execution_closed'))assert.equal(history.current.record.state.reason_code,'execution_closed');assert.equal(history.current.record.revision,commandSettled?'5':commandDispatch?'4':'2');
        assert.equal(history.current.record.state.effect_status,commandSettled?'verified':commandDispatch?'possible':'not_sent');assert.equal(history.current.record.state.resource_status,commandSettled?'clear':finalized?'held':'clear');
        assert.equal(history.current.record.state.automation_continuation,finalized?'eligible':'paused_latched');
        if(finalized){const committed=frames.find(f=>f.event==='command-final-admission');assert.ok(committed);assert.equal(committed.replay,false);
          if(!commandDispatch)assert.deepEqual(history.current.record,committed.record);
          else {const sent=frames.find(f=>f.event==='command-dispatched'),r=sent.value.report.frame.body,o=sent.value.evidence.frame.body.payload.observation;
           assert.equal(sent.value.qualification,null);assert.equal(sent.replay_qualification,null);assert.deepEqual(sent.replay_ref,sent.value.ref);
           assert.equal(r.disposition,'in_flight');assert.equal(r.proof,'transport_entered');assert.equal(o.bytes_written,8);
           if(mode.includes('_dispatch_closure')){const closed=frames.find(f=>f.event==='command-closed');assert.ok(closed);assert.deepEqual(closed.value.ref,closed.replay_ref);assert.equal(closed.value.qualification,null);assert.equal(closed.value.ack.frame.body.transmission_coverage.length,1);assert.equal(closed.value.ack.frame.body.transmission_coverage[0].proof,'transport_entered');assert.equal(closed.value.ack.frame.body.ack.all_write_exits_fenced,true);assert.deepEqual(closed.state.ready_devices,[]);}
           if(mode.includes('_closure_cleanup')){const cleanup=frames.find(f=>f.event==='command-cleaned');assert.ok(cleanup);
            assert.deepEqual(cleanup.value.ref,cleanup.replay_ref);assert.equal(cleanup.value.qualification,null);
            assert.deepEqual(Object.keys(cleanup.value.steps),['deny_request','deny_ack','release_request','release_ack']);
            assert.equal(cleanup.value.steps.deny_ack.frame.body.future_use_denied,true);
            const released=cleanup.value.steps.release_ack.frame.body;
            for(const key of ['encoder_quiescent','consumers_quiescent','cache_empty'])assert.equal(released[key],true);
            assert.equal(released.state,'released');assert.deepEqual(cleanup.state.ready_devices,[]);
           }
           assert.equal(o.response.value,command.request.parameters.value);assert.equal(o.response.write_sequence,'1');
           assert.equal(r.permit_id,committed.value.permit.permit_id);assert.equal(o.permit_id,r.permit_id);
           assert.deepEqual(history.current.record.attempts[0].prepared_state_ref,committed.record.state_ref);
           assert.equal(history.current.record.attempts[0].exits[0].send_started_at,null);
           assert.equal(history.current.record.state.outcome,commandSettled?'succeeded':'pending');assert.equal(history.current.record.evidence_index.total,commandSettled?'2':'0');
          }assert.equal(committed.record.attempts.length,1);
          assert.equal(committed.value.seal.inputs.ordinary_closure,null);assert.equal(Object.keys(committed.value.projections).length,18);
          assert.equal(committed.value.resource_after.holds.length,1);assert.equal(committed.value.transmission_charge.issued_revision,'1');
          assert.deepEqual(committed.record.attempts[0].prepared_state_ref,committed.record.state_ref);
          assert.equal(committed.record.attempts[0].exits[0].send_started_at,null);
          assert.equal(committed.observation.outcome,'committed');
          const qualified=frames.find(f=>f.event==='command-prepared-current')?.value;assert.ok(qualified);
          assert.deepEqual(qualified.resource,committed.value.resource_after);assert.equal(qualified.final_admission_ref.id,committed.value.transaction_id);
          assert.equal(qualified.permit_id,committed.value.permit.permit_id);assert.deepEqual(qualified.send_window,committed.value.seal.send_window);
          if(mode.includes('_t2_guard')){const guard=frames.find(f=>f.event==='command-guard-installed');assert.ok(guard);assert.equal(guard.disposition,'installed');
           assert.equal(guard.body.guard_id,committed.value.guard.guard_id);assert.equal(guard.body.guard_digest,committed.value.guard.guard_digest);
           assert.equal(guard.body.permit_id,committed.value.permit.permit_id);if(!mode.endsWith('_guard_changed')){assert.equal(guard.replay_ref.digest,guard.original_ref.digest);assert.equal(guard.replay_qualification,null);}
           if(mode.endsWith('_guard_changed'))assert.equal(frames.find(f=>f.event==='command-prepared-rejected')?.code,'initial_resource_changed');}
          assert.deepEqual(qualified.observation,committed.observation);assert.ok(BigInt(qualified.selected_tick_ns)<BigInt(qualified.send_window.before_tick_ns));
          const specimen=path.join(root,'final-admission.json');fs.writeFileSync(specimen,JSON.stringify(committed));
          const suiteRoot=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
          const python=path.join(suiteRoot,'docs/contracts/.venv/Scripts/python.exe');
          const check=spawnSync(python,['-c',`import json,sys
from pathlib import Path
import final_admission_model as M
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
sys.path.insert(0,str(Path.cwd().parent/'c08-controller'))
import build_hold_ownership as H
schemas=[H.build(),H.L.build(),H.L.O.build(),json.loads(H.L.O.IPC.read_bytes())]
registry=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in schemas])
x=json.load(open(sys.argv[1],encoding='utf8'));v=x['value'];s=v['seal']
cut=dict(transaction_id=s['transaction_id'],binding=s['binding'],identity=s['identity'],command_state_ref=s['command_state_ref'],selected_tick_ns=int(s['selected_tick_ns']),sealed_tick_ns=int(s['sealed_tick_ns']),previous_issue_revision=int(v['transmission_charge']['previous_revision']))
assert M.verify(s,v['projections'],cut)=='cross_object_binding_valid'
owner=v['ownership'];receipt=v['ownership_receipt']
assert receipt['content']=={k:owner[k] for k in ('scope','device_id','hold_ref','identity','control_authority_ref','control_epoch','effective_version','clock_domain_id','descriptor_digest','acquired_tick_ns')}
assert owner['source_receipt_ref']==dict(id=receipt['receipt_id'],revision='1',digest=M.digest(receipt))
for name,key in [('Ownership','ownership'),('PermitAuthority','permit_authority')]:
 Draft202012Validator({'$ref':H.SID+'#/$defs/'+name},registry=registry).validate(v[key])
assert M.observe(s,x['observation'])=='committed_requires_recheck'
print('schema and cross-object checks passed')`,specimen],{cwd:path.join(suiteRoot,'docs/contracts/c04-lifecycle'),encoding:'utf8'});
          assert.equal(check.status,0,check.stderr||check.error?.message);assert.match(check.stdout,/checks passed/);
        }
        assert.deepEqual(history.current.record.initial_command_ref,command.current.record.initial_command_ref);
        assert.equal(history.current.record.accepted_at,null);
        assert.deepEqual(history.replayed.adjudication,command.accepted.adjudication);assert.equal(history.replayed.replay,true);
        assert.equal(history.conflict,'command_conflict');assert.equal(history.denied,'command_permission');assert.equal(history.missing,'command_not_found');
        assert.equal(frames.find(f=>f.event==='command-source'&&f.stage==='ready-expired')?.code,commandSettled?'command_gate_not_ready':'command_execution_unavailable');
      }else assert.equal(frames.find(f=>f.event==='command-source'&&f.stage==='ready-stale')?.code,'command_execution_unavailable');
    }else assert.equal(ready,undefined);
    assert.equal(frames.find(f=>f.event==='retired'||f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const count=expired||omission?0:1;assert.equal(db.prepare('SELECT count(*) FROM device_initial_ready').pluck().get(),count);
      assert.equal(db.prepare('SELECT count(*) FROM execution_initial_open_ack').pluck().get(),omission?0:1);
      assert.equal(db.prepare("SELECT count(*) FROM control_change_commit WHERE kind='ready'").pluck().get(),count);
      assert.equal(db.prepare("SELECT count(*) FROM control_change_commit WHERE kind='gate_protect'").pluck().get(),count);
      const commands=expired||omission||stale||commandFailure?0:1;
      assert.equal(db.prepare('SELECT count(*) FROM ca_command_initial').pluck().get(),commands);
      for(const table of ['command_admission_source','command_policy','command_resource_claim','command_context_charge','command_revision'])
        assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),commands);
      assert.equal(db.prepare('SELECT coalesce(sum(after_count-before_count),0) FROM command_context_charge').pluck().get(),commands);
      for(const table of ['ca_request_key','ca_adjudication','ca_commit','ca_audit','ca_notification','ca_reservation'])
        assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),commands);
      assert.equal(db.prepare('SELECT sum(used_count) FROM request_context').pluck().get(),1+commands);
      for(const table of ['command_lifecycle_revision','command_lifecycle_commit','command_lifecycle_head']){
        const actual=db.prepare('SELECT count(*) FROM '+table).pluck().get();
        if(encodingFailure||finalFailure)assert.ok(actual===0||actual===1);else assert.equal(actual,lifecycleFailure?0:commandDispatch&&table!=='command_lifecycle_head'?commands*(commandSettled?4:3):commands);
        if(actual&&!lifecycleFailure)assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_command_lifecycle/);
      }
      if(commandEncodingCases.includes(mode)){
        if(encodingFailure){
          const requested=mode.endsWith('_request_ignore')?0:1;
          assert.equal(db.prepare('SELECT count(*) FROM command_encoding_request').pluck().get(),requested);
          assert.equal(db.prepare('SELECT count(*) FROM command_encoding_reservation').pluck().get(),requested);
          assert.equal(db.prepare('SELECT count(*) FROM command_encoding_response').pluck().get(),0);
          assert.equal(db.prepare('SELECT count(*) FROM execution_encoding_frame').pluck().get(),requested);
          const heads=['command_lifecycle_head','command_lifecycle_revision','command_lifecycle_commit'].map(t=>db.prepare('SELECT count(*) FROM '+t).pluck().get());
          assert.equal(new Set(heads).size,1);
        }else{
        for(const table of ['command_encoding_request','command_encoding_response','command_encoding_reservation']){
          assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),1);
          assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_command_encoding/);
        }
        assert.equal(db.prepare('SELECT count(*) FROM execution_encoding_frame').pluck().get(),2);
        assert.equal(db.prepare("SELECT count(*) FROM execution_frame_record WHERE message_type IN('GUARD_INSTALL','DISPATCH','RESEND_DISPATCH')").pluck().get(),commandDispatch?2:mode.includes('_t2_guard')&&(!guardFailure||guardOmissions[mode]==='command_guard_ack')?1:0);
        assert.equal(db.prepare("SELECT count(*) FROM execution_write_attempt w JOIN execution_frame_record f USING(record_id) WHERE f.message_type='ENCODE_PACKET'").pluck().get(),1);
        assert.equal(db.prepare("SELECT disposition FROM command_encoding_response").pluck().get(),'prepared');
        if(mode.endsWith('_t2')||mode.includes('_t2_guard')||observationFailure)for(const table of ['command_final_admission','command_device_hold','command_transmission_issue','command_attempt_inventory']){
          assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),1);
          assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_command_final_admission/);
        }
        if(mode.endsWith('_t2')||mode.includes('_t2_guard'))assert.equal(db.prepare('SELECT count(*) FROM command_final_observation').pluck().get(),1);
        if(observationFailure){
          assert.equal(db.prepare('SELECT count(*) FROM command_final_observation').pluck().get(),0);
          const record=JSON.parse(db.prepare('SELECT record_jcs FROM command_lifecycle_revision').pluck().get());
          assert.equal(record.state.resource_status,'held');assert.equal(record.state.outcome,'pending');assert.equal(record.attempts.length,1);
          assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),8);
        }
        if(mode.includes('_t2_guard')){
          const requestCount=!guardFailure||guardOmissions[mode]==='command_guard_ack'?1:0,ackCount=guardFailure?0:1;
          assert.equal(db.prepare('SELECT count(*) FROM command_guard_request').pluck().get(),requestCount);
          assert.equal(db.prepare('SELECT count(*) FROM command_guard_ack').pluck().get(),ackCount);
          assert.equal(db.prepare('SELECT count(*) FROM execution_guard_frame').pluck().get(),requestCount+ackCount);
          assert.equal(db.prepare("SELECT count(*) FROM execution_frame_record WHERE domain_kind='command_guard'").pluck().get(),requestCount+ackCount);
          assert.equal(db.prepare("SELECT count(*) FROM execution_write_attempt w JOIN execution_frame_record f USING(record_id) WHERE f.message_type='GUARD_INSTALL'").pluck().get(),requestCount);
          assert.equal(db.prepare("SELECT count(*) FROM execution_frame_record WHERE message_type IN('DISPATCH','RESEND_DISPATCH')").pluck().get(),commandDispatch?1:0);
          if(ackCount){assert.equal(db.prepare('SELECT disposition FROM command_guard_ack').pluck().get(),'installed');
            for(const table of ['command_guard_request','command_guard_ack','execution_guard_frame'])assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_command_guard/);}
          assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),8);
        }
        if(mode.includes('_closure_cleanup')){
          assert.equal(db.prepare('SELECT count(*) FROM command_preparation_retirement').pluck().get(),1);
          assert.equal(db.prepare('SELECT count(*) FROM command_preparation_cleanup').pluck().get(),4);
          assert.equal(db.prepare('SELECT count(*) FROM execution_write_attempt w JOIN command_preparation_cleanup c ON c.record_id=w.record_id').pluck().get(),2);
          assert.equal(db.prepare('SELECT count(*) FROM command_encoding_reservation').pluck().get(),1);
          assert.equal(db.prepare('SELECT count(*) FROM command_device_hold').pluck().get(),1);
          assert.equal(db.prepare('SELECT sum(charged_bytes) FROM command_transmission_issue').pluck().get(),8);
          for(const table of ['command_preparation_retirement','command_preparation_cleanup'])assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_preparation_cleanup/);
        }
        if(commandSettled){
          for(const table of ['command_closure_request','command_closure_ack','command_settlement','command_hold_release'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),1);
          assert.equal(db.prepare('SELECT count(*) FROM command_evidence_record').pluck().get(),2);
          assert.equal(db.prepare("SELECT count(*) FROM execution_write_attempt w JOIN command_closure_request c ON c.record_id=w.record_id").pluck().get(),1);
          const e=frames.find(v=>v.event==='command-evidence');assert.ok(e);
          for(const response of [e.first,e.second,e.original,e.prior])assert.equal(response.status,200,JSON.stringify(response));
          assert.equal(e.first.body.total,'2');assert.equal(e.first.body.offset,'0');assert.equal(e.first.body.items.length,1);assert.equal(e.second.body.offset,'1');assert.equal(e.second.body.next_cursor,null);
          assert.deepEqual(e.original.body,e.first.body.items[0]);assert.deepEqual(e.prior.body.items,[]);assert.equal(e.prior.body.total,'0');assert.equal(e.denied,'command_permission');
          for(const page of [e.first.body,e.second.body,e.prior.body]){const {page_digest,...body}=page;assert.equal(page_digest,digestValue(body));}
          for(const item of [...e.first.body.items,...e.second.body.items]){const {view_digest,...body}=item;assert.equal(view_digest,digestValue(body));const {evidence_digest,...proof}=item.body;assert.equal(evidence_digest,digestValue(proof));assert.equal(item.source_ref.digest,evidence_digest);}
        }
        if(commandDispatch){
          for(const table of ['command_dispatch_request','command_dispatch_write','command_dispatch_report','command_dispatch_evidence']){assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),1);assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_command_dispatch/);}
          assert.equal(db.prepare('SELECT count(*) FROM execution_dispatch_frame').pluck().get(),mode.includes('_closure_cleanup')?9:commandSettled?5:3);
          assert.equal(db.prepare("SELECT count(*) FROM execution_write_attempt w JOIN execution_frame_record f USING(record_id) WHERE f.message_type='DISPATCH'").pluck().get(),1);
        }
        if(finalFailure){
          for(const table of ['command_final_admission','command_device_hold','command_transmission_issue','command_attempt_inventory','command_final_observation'])
            assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),0);
          assert.equal(new Set(['command_lifecycle_revision','command_lifecycle_commit','command_lifecycle_head'].map(table=>db.prepare('SELECT count(*) FROM '+table).pluck().get())).size,1);
        }
        }
      }
      if(count){const values=db.prepare("SELECT body_jcs FROM control_state_source ORDER BY revision").pluck().all().map(JSON.parse);
        const adopted=values.find(v=>v.change_kind==='ready'),before=values.find(v=>v.revision===String(BigInt(adopted.revision)-1n));
        for(const key of ['holder','mode','control_epoch','effective_version','reserved_version'])assert.deepEqual(adopted[key],before[key]);
        const protectedState=JSON.parse(db.prepare('SELECT s.body_jcs FROM device_authorization_state s JOIN device_authorization_head h USING(state_id)').pluck().get());
        assert.equal(protectedState.status,'protected');assert.throws(()=>db.exec('DELETE FROM device_initial_ready'),/immutable_initial_ready/);
      }assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}
    if(mode.endsWith('_dispatch_closure_cleanup'))await verifySuccessorMigration(core);
    return;
  }
  if(dispatchMode){
    const unavailable=frames.find(f=>f.event==='unavailable'),confirmation=frames.find(f=>f.event==='open-confirmed');
    const expired=mode.endsWith('_expired'),stale=mode.endsWith('_stale'),requestOmission=mode.endsWith('_request_ignore'),ackOmission=mode.endsWith('_ack_ignore');
    if(dispatchFailure)assert.equal(unavailable?.code,'execution_open_storage',JSON.stringify(unavailable));
    else if(expired){
      const boundary=frames.find(f=>f.event==='open-expiry-boundary');assert.ok(boundary&&BigInt(boundary.tick)>=BigInt(boundary.expires));
      assert.ok(unavailable&&/expired|not_current|core_observation/.test(unavailable.code),JSON.stringify(unavailable));
    }else if(stale)assert.equal(unavailable?.code,'initial_resource_changed',JSON.stringify(unavailable));
    else assert.equal(unavailable,undefined,JSON.stringify(frames.map(({event,code,reported_ms})=>({event,code,reported_ms}))));
    if(!expired&&!dispatchFailure){
      assert.ok(confirmation);assert.equal(confirmation.result.confirmation.gate_state,'open_observed');assert.equal(confirmation.state.gate_state,'closed');
      assert.equal(frames.find(f=>f.event==='open-stale'),undefined);
    }else assert.equal(confirmation,undefined);
    const retirement=frames.find(f=>f.event==='retired'||f.event==='module-failed-retired');assert.equal(retirement?.result.result,'confirmed_empty');
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const requests=expired||requestOmission?0:1,acks=confirmation?1:0;
      assert.equal(db.prepare('SELECT count(*) FROM execution_initial_open_dispatch').pluck().get(),requests);
      assert.equal(db.prepare('SELECT count(*) FROM execution_initial_open_ack').pluck().get(),acks);
      assert.equal(db.prepare('SELECT count(*) FROM execution_open_frame').pluck().get(),requests+acks);
      for(const [type,count] of [['OPEN_GATE',requests],['OPEN_GATE_ACK',acks]])assert.equal(db.prepare('SELECT count(*) FROM execution_frame_record WHERE message_type=?').pluck().get(type),count);
      assert.equal(db.prepare('SELECT count(*) FROM ca_command_initial').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM device_initial_open').pluck().get(),1);
      assert.equal(db.prepare('SELECT count(*) FROM device_initial_open_commit').pluck().get(),1);
      const rows=db.prepare("SELECT body_jcs FROM control_record_revision WHERE json_extract(body_jcs,'$.gate_state')='ready'").pluck().all();assert.deepEqual(rows,[]);
      if(confirmation){
        const request=JSON.parse(db.prepare("SELECT frame_jcs FROM execution_frame_record WHERE message_type='OPEN_GATE'").pluck().get());
        const ack=JSON.parse(db.prepare("SELECT frame_jcs FROM execution_frame_record WHERE message_type='OPEN_GATE_ACK'").pluck().get());
        const plan=frames.find(f=>f.event==='initial-open').value.value.plan;assert.deepEqual(request.body,plan.body);assert.equal(ack.reply_to,request.message_id);
        assert.equal(ack.body.gate_token,plan.body.gate_token);assert.equal(ack.body.reference_time_snapshot_ref,null);assert.equal(ack.body.gate_access_ref.digest,plan.body.gate_access.access_digest);
        const sent=db.prepare("SELECT r.result FROM execution_write_result r JOIN execution_write_attempt a USING(attempt_id) JOIN execution_frame_record f USING(record_id) WHERE f.message_type='OPEN_GATE'").pluck().all();assert.deepEqual(sent,['complete']);
      }
      for(const table of ['execution_initial_open_dispatch','execution_initial_open_ack','execution_open_frame'])if(db.prepare('SELECT count(*) FROM '+table).pluck().get())assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_execution_open/);
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(resourceMode){
    const unavailable=frames.find(f=>f.event==='unavailable');
    if(resourceFailure||openingFailure){assert.equal(unavailable?.code,openingFailure?'initial_open_storage':'initial_resource_storage',JSON.stringify(unavailable));
      assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    }else{
      assert.equal(unavailable,undefined,JSON.stringify(frames.map(({event,code,cause,reported_ms})=>({event,code,cause,reported_ms}))));
      const selected=frames.find(f=>f.event==='initial-resource'),history=frames.find(f=>f.event==='initial-resource-history');
      assert.ok(selected&&history);if(!openingMode)assert.deepEqual(selected.current,{...selected.value,pending_admission_refs:[]});assert.deepEqual(history.value,selected.value);assert.deepEqual(history.replayed,selected.value);
      assert.deepEqual(frames.find(f=>f.event==='initial-resource-reconnected-history').value,selected.value);
      assert.notEqual(frames.find(f=>f.event==='initial-resource-expired').code,'unexpected_success');
      assert.equal(frames.find(f=>f.event==='initial-resource-conflict').code,'initial_resource_conflict');
      if(!openingMode)assert.equal(frames.find(f=>f.event==='initial-resource-new-sample').code,'initial_resource_changed');
      assert.equal(frames.find(f=>f.event==='initial-resource-reconnected').code,'initial_resource_changed');
      const value=selected.value.value,inventory=value.inventory;
      assert.equal(value.format,'leafseamer-initial-resource-source/2');assert.equal(value.provider,'fixed_memory_control_initial/1');
      const denials=value.deny_snapshots;assert.equal(denials.format,'initial-manual-deny-snapshots/2');
      assert.equal(denials.schema_revision,'50');assert.equal(denials.accepted_command_count,0);
      assert.deepEqual(denials.scope,value.binding.scope);assert.equal(denials.device_id,value.binding.device_id);
      for(const snapshot of [denials.run_deny_snapshot,denials.command_deny_snapshot]){
        assert.equal(snapshot.snapshot_revision,'0');assert.deepEqual(snapshot.entries,[]);
        assert.equal(snapshot.snapshot_digest,digestValue((({snapshot_digest,...body})=>body)(snapshot)));
      }
      assert.deepEqual(denials.run_deny_snapshot.controller_scope,value.binding.scope);
      assert.deepEqual(denials.command_deny_snapshot.scope,value.binding.scope);assert.equal(denials.command_deny_snapshot.device_id,value.binding.device_id);
      assert.ok(denials.outgoing_frame_refs.length>=inventory.outgoing_records.length);
      assert.deepEqual(inventory.command_ids,[]);assert.deepEqual(inventory.external_resources,[]);assert.equal(inventory.observed_write_sequence,'0');
      assert.ok(inventory.outgoing_records.length>=2);assert.ok(inventory.outgoing_records.every(v=>['HELLO_ACK','FENCE'].includes(v.type)));
      assert.equal(value.digest,digestValue((({digest,...body})=>body)(value)));assert.deepEqual(selected.value.ref,{id:value.id,revision:'1',digest:value.digest});
      if(openingMode){
        const opening=frames.find(f=>f.event==='initial-open'),historical=frames.find(f=>f.event==='initial-open-history');
        assert.ok(opening&&historical);assert.deepEqual(opening.value,opening.current);assert.deepEqual(historical.value,opening.value);assert.deepEqual(historical.replayed,opening.value);
        assert.deepEqual(frames.find(f=>f.event==='initial-open-reconnected-history').value,opening.value);
        assert.equal(frames.find(f=>f.event==='initial-open-conflict').code,'initial_open_conflict');
        assert.equal(frames.find(f=>f.event==='initial-open-second').code,'initial_open_already_selected');
        assert.equal(frames.find(f=>f.event==='initial-open-new-sample').code,'initial_resource_changed');
        assert.notEqual(frames.find(f=>f.event==='initial-open-expired').code,'unexpected_success');
        assert.equal(frames.find(f=>f.event==='initial-open-reconnected').code,'initial_resource_changed');
        const prepared=opening.value.value,p=prepared.plan;
        assert.equal(prepared.resource_safety.state,'clear');assert.equal(prepared.gate_safety.state,'fenced');assert.equal(prepared.gate.phase,'fenced');
        assert.equal(prepared.gate.activation_id,null);assert.equal(p.body.reference_time_snapshot,null);assert.equal(p.body.protection_assessment,null);
        assert.deepEqual(p.body.gate_access,prepared.access);assert.deepEqual(prepared.resource.provider_source_ref,selected.value.ref);
        assert.deepEqual(p.body.run_deny_snapshot,denials.run_deny_snapshot);assert.deepEqual(p.body.command_deny_snapshot,denials.command_deny_snapshot);
        assert.equal(p.expires_tick_ns,value.expires_tick_ns);assert.equal(p.body.lease_until_tick_ns,value.expires_tick_ns);
        const {decodeExecutionPayload}=await load('device-execution-channel.mjs'),{deviceExecutionVersion}=await load('sdk/device-execution.mjs');
        const b=p.binding,frame={ipc_version:deviceExecutionVersion,type:'OPEN_GATE',message_id:'shape_only',reply_to:null,ipc_session_id:b.ipc_session_id,
          controller_boot_id:b.controller_boot_id,worker_boot_id:b.worker_boot_id,seq:'1',device_id:b.device_id,body:p.body,
          clock_domain_id:b.clock_domain_id,descriptor_digest:b.descriptor_digest,journal_mode:'durable'};
        assert.deepEqual((await decodeExecutionPayload(Buffer.from(JSON.stringify(frame)),'c2w')).frame,frame);
      }
    }
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM device_authorization_evidence').pluck().get(),1);
      assert.equal(db.prepare('SELECT count(*) FROM device_recovery_consumption').pluck().get(),1);
      for(const table of ['device_initial_resource','device_initial_resource_commit']){
        assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),resourceFailure?0:1);
        if(!resourceFailure){assert.throws(()=>db.exec('UPDATE '+table+' SET body_digest=body_digest'),/immutable_initial_resource/);assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_initial_resource/);}
      }
      if(openingMode){
        for(const table of ['device_initial_open','device_initial_open_commit']){
          assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),openingFailure?0:1);
          if(!openingFailure){assert.throws(()=>db.exec('UPDATE '+table+' SET body_digest=body_digest'),/immutable_initial_open/);assert.throws(()=>db.exec('DELETE FROM '+table),/immutable_initial_open/);}
        }
        assert.equal(db.prepare("SELECT count(*) FROM execution_frame_record WHERE message_type='OPEN_GATE'").pluck().get(),0);
      }
      if(!resourceFailure){
        const value=JSON.parse(db.prepare('SELECT body_jcs FROM device_initial_resource').pluck().get()),i=value.inventory;
        for(const [table,column,reference] of [['device_execution_binding','binding_id',i.binding_ref],['device_baseline_sample','sample_id',i.baseline_ref],['execution_initial_fence','fence_id',i.initial_fence_ref]])
          assert.equal(db.prepare('SELECT body_digest FROM '+table+' WHERE '+column+'=?').pluck().get(reference.id),reference.digest);
        assert.equal(db.prepare('SELECT body_digest FROM device_authorization_evidence WHERE evidence_id=?').pluck().get(i.authorization_evidence_ref.id),i.authorization_evidence_ref.digest);
        assert.equal(db.prepare('SELECT count(*) FROM ca_command_initial').pluck().get(),0);
        for(const reference of value.deny_snapshots.outgoing_frame_refs)
          assert.equal(db.prepare("SELECT record_digest FROM execution_frame_record WHERE record_id=? AND direction='c2w'").pluck().get(reference.id),reference.digest);
      }
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(evidenceMode){
    if(evidenceFailure){
      assert.equal(frames.find(f=>f.event==='unavailable')?.code,'device_evidence_storage',JSON.stringify(frames.filter(v=>v.event==='unavailable')));
      assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    }else{
      assert.equal(frames.find(f=>f.event==='unavailable'),undefined,JSON.stringify(frames.map(f=>({event:f.event,code:f.code,cause:f.cause,reason:f.reason,reported_ms:f.reported_ms}))));
      const first=frames.find(f=>f.event==='authorization-evidence'),renewed=frames.find(f=>f.event==='evidence-renewed');
      assert.ok(first&&renewed);assert.deepEqual(first.value,first.current);assert.deepEqual(first.value,first.replayed);assert.deepEqual(renewed.value,renewed.current);
      assert.deepEqual(first.value.value.state_ref,renewed.value.value.state_ref);assert.notDeepEqual(first.value.ref,renewed.value.ref);
      assert.deepEqual(renewed.value.commit.previous_evidence_ref,first.value.ref);assert.equal(renewed.value.commit.generation,'2');
      const extended=frames.find(f=>f.event==='evidence-after-recovery-window');assert.ok(extended);
      assert.deepEqual(extended.state,renewed.value.value.state_ref);assert.deepEqual(extended.source.value.authorization_state_ref,extended.state);
      assert.ok(BigInt(extended.recovery_before)<=BigInt(extended.now_tick)&&BigInt(extended.now_tick)<BigInt(extended.evidence_before));
      for(const item of [first.value,renewed.value]){
        const v=item.value,r=v.requirement,cut=item.cut;
        assert.equal(v.format_version,'device-authorization-evidence/0.1.0-draft.1');assert.equal(v.evidence_digest,digestValue((({evidence_digest,...body})=>body)(v)));
        assert.equal(r.format_version,'open-authorization-requirement/0.1.0-draft.1');assert.equal(r.requirement_digest,digestValue((({requirement_digest,...body})=>body)(r)));
        assert.deepEqual(r.authorization_state_ref,v.state_ref);assert.equal(r.control_mode,'manual');assert.equal(r.purpose,'ordinary');assert.equal(r.cancel_evidence,null);
        assert.equal(cut.format,'local-manual-device-revocation-cut/1');assert.deepEqual(cut.binding,r.binding);assert.equal(cut.context_digest,v.context_digest);
        assert.deepEqual(cut.identity_dependencies.map(v=>v.role),['evaluator','manual']);assert.ok(cut.identity_dependencies.every(v=>v.result==='no_matching_denial'));
        assert.deepEqual(r.revocation_cut_ref,{id:cut.id,revision:cut.revision,digest:cut.digest});assert.equal(cut.digest,digestValue((({digest,...body})=>body)(cut)));
        assert.equal(cut.extension.approval_ref.kind,'approval');assert.ok(cut.trust.local_issuer.issuer_id&&cut.trust.host_trust_epoch);
        assert.deepEqual(r.holder_evidence.response_ref,cut.source_refs.holder);assert.deepEqual(r.evaluator.authority_response_ref,cut.source_refs.evaluator);
        assert.deepEqual(v.windows.map(v=>v.role),['evaluator','holder']);assert.equal(r.expires_tick_ns,String(v.windows.map(v=>BigInt(v.before_tick_ns)).reduce((a,b)=>a<b?a:b)));
      }
      assert.equal(frames.find(f=>f.event==='evidence-clear-bypass')?.code,'device_evidence_selection_conflict');
      assert.equal(frames.find(f=>f.event==='evidence-request-conflict')?.code,'device_evidence_conflict');
      assert.ok(frames.find(f=>f.event==='evidence-expired')?.code);assert.notEqual(frames.find(f=>f.event==='evidence-expired')?.code,'unexpected_success');
      assert.equal(frames.find(f=>f.event==='evidence-protected')?.code,'device_evidence_protected');
      for(const event of ['evidence-history','evidence-protected-history'])assert.deepEqual(frames.find(f=>f.event===event)?.value,renewed.value);
      assert.equal(frames.find(f=>f.event==='retired')?.result.result,'confirmed_empty');
    }
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      for(const table of ['device_authorization_revocation_cut','device_authorization_evidence','device_authorization_evidence_commit'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),evidenceFailure?0:2);
      assert.equal(db.prepare('SELECT count(*) FROM device_authorization_evidence_head').pluck().get(),evidenceFailure?0:1);
      assert.equal(db.prepare('SELECT count(*) FROM device_recovery_consumption').pluck().get(),1);
      assert.equal(db.prepare('SELECT count(*) FROM ca_adjudication').pluck().get(),0);
      if(!evidenceFailure){
        for(const table of ['device_authorization_revocation_cut','device_authorization_evidence','device_authorization_evidence_commit']){
          assert.throws(()=>db.prepare('UPDATE '+table+' SET body_jcs=body_jcs').run(),/immutable_device_evidence/);
          assert.throws(()=>db.prepare('DELETE FROM '+table).run(),/immutable_device_evidence/);
        }
        assert.throws(()=>db.prepare('DELETE FROM device_authorization_evidence_head').run(),/device_evidence_head_retained/);
        assert.equal(db.prepare('SELECT count(*) FROM device_authorization_evidence_head e JOIN device_authorization_head s USING(state_id)').pluck().get(),0);
      }
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(manualChallengeFailure){
    assert.equal(frames.find(f=>f.event==='unavailable')?.code,'manual_authority_challenge_storage');
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    assert.equal(frames.find(f=>f.event==='manual-source'),undefined);
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const retained=mode.includes('_response_')?1:0;
      for(const table of ['manual_execution_challenge','manual_execution_challenge_commit','core_runtime_source','core_runtime_source_commit'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),retained);
      for(const table of ['manual_execution_challenge_response','execution_manual_authority','execution_manual_authority_commit','ca_adjudication'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),0);
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(mode.endsWith('_manual_challenge_checks')){
    assert.equal(frames.find(f=>f.event==='unavailable'),undefined);
    for(const [event,code] of [['wrong-nonce','response'],['bypass','required'],['conflict','conflict'],['expired','expired']])
      assert.equal(frames.find(f=>f.event==='manual-challenge-'+event)?.code,'manual_authority_challenge_'+code);
    assert.equal(frames.find(f=>f.event==='retired')?.result.result,'confirmed_empty');
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      for(const table of ['manual_execution_challenge','manual_execution_challenge_commit','manual_execution_challenge_response','execution_manual_authority','execution_manual_authority_commit'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),2);
      for(const table of ['manual_execution_challenge','manual_execution_challenge_commit','manual_execution_challenge_response']){
        assert.throws(()=>db.prepare('UPDATE '+table+' SET challenge_id=challenge_id').run(),/immutable_manual_challenge/);
        assert.throws(()=>db.prepare('DELETE FROM '+table).run(),/immutable_manual_challenge/);
      }
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(manualAuthorityFailure){
    assert.equal(frames.find(f=>f.event==='unavailable')?.code,mode.endsWith('source_fail')?'SQLITE_CONSTRAINT_TRIGGER':mode.includes('_core_')?'core_runtime_source_storage':'manual_authority_storage');
    assert.equal(frames.find(f=>f.event==='manual-source'),undefined);
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM execution_manual_authority').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM execution_manual_authority_commit').pluck().get(),0);
      for(const table of ['core_runtime_source','core_runtime_source_commit','manual_execution_challenge','manual_execution_challenge_commit'])assert.equal(db.prepare('SELECT count(*) FROM '+table).pluck().get(),mode.includes('_core_')?0:1);
      assert.equal(db.prepare('SELECT count(*) FROM manual_execution_challenge_response').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM ca_adjudication').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM worker_runtime_withdrawal').pluck().get(),1);
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(controlFenceFailure){
    const error=frames.find(f=>f.event==='unavailable');assert.ok(error,JSON.stringify(frames));
    assert.equal(error.code,mode.endsWith('request_fail')?'SQLITE_CONSTRAINT_TRIGGER':'execution_control_storage');
    assert.equal(frames.find(f=>f.event==='initial-control-fence'),undefined);
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      const requestSaved=!mode.endsWith('request_fail'),writeSaved=mode.endsWith('ack_ignore');
      assert.equal(db.prepare('SELECT count(*) FROM execution_frame_record').pluck().get(),requestSaved?3:2);
      assert.equal(db.prepare('SELECT count(*) FROM execution_initial_fence').pluck().get(),requestSaved?1:0);
      assert.equal(db.prepare('SELECT count(*) FROM execution_initial_fence_ack').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM execution_control_frame').pluck().get(),requestSaved?1:0);
      assert.equal(db.prepare('SELECT count(*) FROM execution_write_attempt').pluck().get(),writeSaved?2:1);
      assert.equal(db.prepare('SELECT count(*) FROM ca_adjudication').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM worker_runtime_withdrawal').pluck().get(),1);
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(handshakeFailure){
    const error=frames.find(f=>f.event==='unavailable');assert.ok(error,JSON.stringify(frames));
    assert.equal(error.code,mode.endsWith('ignore')?'execution_handshake_storage':'SQLITE_CONSTRAINT_TRIGGER');
    assert.equal(frames.find(f=>f.event==='execution-negotiated'),undefined);
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM execution_frame_record').pluck().get(),mode.endsWith('ignore')?2:0);
      assert.equal(db.prepare('SELECT count(*) FROM execution_handshake').pluck().get(),mode.endsWith('ignore')?1:0);
      assert.equal(db.prepare('SELECT count(*) FROM execution_write_attempt').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM execution_write_result').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM worker_runtime_withdrawal').pluck().get(),1);
      assert.ok(['storage_failed','protocol_error'].includes(db.prepare('SELECT reason FROM execution_session_end').pluck().get()));
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(bindingFailure){
    const error=frames.find(f=>f.event==='unavailable');assert.ok(error,JSON.stringify(frames));
    assert.equal(error.code,mode.endsWith('ignore')?'execution_binding_storage':'SQLITE_CONSTRAINT_TRIGGER');
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    assert.equal(frames.find(f=>f.event==='execution-bound'),undefined);
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM device_execution_binding').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM device_execution_binding_commit').pluck().get(),0);
      assert.equal(db.prepare('SELECT count(*) FROM worker_runtime_withdrawal').pluck().get(),1);
      assert.equal(db.prepare('SELECT reason FROM execution_session_end').pluck().get(),'runtime_lost');
      assert.deepEqual(db.pragma('foreign_key_check'),[]);
    }finally{db.close();}return;
  }
  if(moduleStorageFailure||catalogFailure||baselineFailure){
    assert.equal(frames.find(f=>f.event==='unavailable')?.code,'module_channel_closed');
    assert.equal(frames.find(f=>f.event==='module-failed-retired')?.result.result,'confirmed_empty');
    assert.equal(frames.find(f=>f.event==='module-samples'),undefined);
    child.stdin.write('stop\n');await ended;
    const db=new Database(path.join(core,'controller.sqlite'),{fileMustExist:true});try{
      assert.equal(db.prepare('SELECT count(*) FROM device_module_channel').pluck().get(),1);
      const count=catalogFailure?4:baselineFailure?6:5;
      assert.equal(db.prepare('SELECT count(*) FROM device_module_frame').pluck().get(),count);
      assert.equal(db.prepare('SELECT count(*) FROM device_module_frame_commit').pluck().get(),count);
      assert.equal(db.prepare('SELECT count(*) FROM device_catalog_approval').pluck().get(),catalogFailure?0:1);
      assert.equal(db.prepare('SELECT count(*) FROM device_baseline_sample').pluck().get(),0);
      assert.equal(db.prepare("SELECT count(*) FROM device_module_frame WHERE message_type='CAPTURED'").pluck().get(),baselineFailure?1:0);
      assert.equal(db.prepare("SELECT count(*) FROM device_module_frame WHERE message_type='CAPTURE'").pluck().get(),catalogFailure?0:1);
      assert.equal(db.prepare('SELECT count(*) FROM worker_runtime_withdrawal').pluck().get(),1);
    }finally{db.close();}return;
  }
  assert.equal(done.record.state,creates?'retired':'registered',JSON.stringify(frames));assert.equal(done.record.creation_attempted,creates);
  if(creates){
    const admitted=frames.find(f=>f.event==='admitted')?.record;assert.equal(admitted?.state,(mode==='supervisor_create'||runtimeMode)?'admitted_closed':'indeterminate',JSON.stringify(frames));
    if(mode==='supervisor_create'||runtimeMode){assert.equal(admitted.admission_receipt.role,'worker');assert.equal(admitted.admission_receipt.gate_state,'closed');
      assert.deepEqual(frames.find(f=>f.event==='observed')?.receipt,admitted.admission_receipt,
        JSON.stringify(frames.map(f=>({event:f.event,code:f.code,cause:f.cause,reason:f.reason,reported_ms:f.reported_ms,...(f.event==='unavailable'?{stack:f.stack}:{})}))));
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
      if(mode==='supervisor_create_module'||mode==='supervisor_create_module_writable'){
        const samples=frames.find(f=>f.event==='module-samples');assert.ok(samples,JSON.stringify(frames));
        const execution=frames.find(f=>f.event==='execution-session');assert.ok(execution,JSON.stringify(frames));
        assert.equal(execution.binding.controller_boot_id,execution.controller_boot_id);
        assert.equal(execution.binding.worker_boot_id,admitted.admission_receipt.member_boot_id);
        assert.equal(execution.binding.runtime_binding_id,adopted.ref.object_id);
        assert.equal(execution.binding.clock_domain_id,admitted.admission_receipt.domain_ref.clock_domain_id);
        const identity=(await load('device-execution-channel.mjs')).executionSessionIdentity({authority_service_id:execution.binding.service_id,
          database_instance_id:execution.binding.database_instance_id,controller_boot_id:execution.controller_boot_id,worker_boot_id:admitted.admission_receipt.member_boot_id,
          clock_domain_id:execution.binding.clock_domain_id,descriptor_digest:execution.binding.descriptor_digest});
        assert.equal(execution.binding.ipc_session_id,identity.ipc_session_id);
        if(writable){
          const control=frames.find(f=>f.event==='command-control');assert.equal(control?.operation.state,'effective');assert.equal(control.control.mode,'manual');assert.equal(control.control.gate_state,'protected');
          assert.deepEqual(frames.filter(f=>f.event==='command-source').map(f=>[f.stage,f.code]),[
            ['connected','command_gate_not_ready'],['wrong-capability','command_capability'],['old-control','command_control_conflict'],
            ['disconnected','command_execution_unavailable'],['before-rebind','command_execution_unavailable'],['rebound','command_gate_not_ready']]);
          const handshake=frames.find(f=>f.event==='execution-negotiated');assert.ok(handshake,JSON.stringify(frames));
          assert.equal(handshake.state.phase,'ready');assert.equal(handshake.state.gate_state,'closed');
          assert.deepEqual(handshake.state.selected_features,[...deviceExecutionCapabilities.base,...deviceExecutionCapabilities.initial_control,...deviceExecutionCapabilities.manual,...deviceExecutionCapabilities.without_reference]);
          assert.equal(handshake.negotiation.ipc_session_id,execution.binding.ipc_session_id);
          assert.equal(handshake.negotiation.gate_state,'closed');
          const fenced=frames.find(f=>f.event==='initial-control-fence'),refenced=frames.find(f=>f.event==='initial-control-refence');
          assert.ok(fenced&&refenced,JSON.stringify(frames));assert.deepEqual(fenced.first,fenced.repeated);
          assert.equal(fenced.first.confirmation.gate_state,'closed');assert.notEqual(fenced.first.ref.id,refenced.receipt.ref.id);
          const personnel=frames.find(f=>f.event==='manual-source'),renewed=frames.find(f=>f.event==='manual-source-rebound');
          assert.deepEqual(personnel.source,personnel.current);assert.deepEqual(renewed.source,renewed.current);
          assert.equal(frames.find(f=>f.event==='manual-source-expired')?.code,'manual_authority_expired');
          assert.equal(frames.find(f=>f.event==='manual-source-disconnected')?.code,'manual_authority_execution');
          assert.equal(frames.find(f=>f.event==='manual-source-logged-out')?.code,'token_invalid');
          assert.equal(frames.find(f=>f.event==='manual-source-bad-secret')?.code,'token_invalid');
          assert.equal(frames.find(f=>f.event==='manual-source-read-only')?.code,'manual_authority_permission');
          assert.equal(frames.find(f=>f.event==='core-observation-copy')?.code,'supervisor_core_observation');
          assert.equal(frames.find(f=>f.event==='core-observation-expired')?.code,'supervisor_core_observation');
          assert.notEqual(personnel.source.value.binding_ref.id,renewed.source.value.binding_ref.id);
          assert.notEqual(personnel.source.value.session_id,renewed.source.value.session_id);
          assert.deepEqual(personnel.source.value.holder,control.control.holder);
          assert.equal(personnel.source.value.authorization_state_ref.revision,'2');assert.equal(renewed.source.value.authorization_state_ref.revision,'4');
          const bound=frames.find(f=>f.event==='execution-bound'),fresh=frames.find(f=>f.event==='execution-rebound')?.binding;
          assert.ok(bound&&fresh,JSON.stringify(frames));assert.deepEqual(bound.first,bound.repeated);
          if(mode==='supervisor_create_module_writable'){
            const configured=frames.find(f=>f.event==='execution-configured');assert.deepEqual(configured.first,bound.first);assert.deepEqual(configured.repeated,bound.first);
            assert.deepEqual(frames.find(f=>f.event==='execution-reconfigured').binding,fresh);
          }
          for(const [record,source] of [[bound.first,samples.accepted],[fresh,samples.fresh]]){
            assert.equal(record.ref.digest,digestValue(record.value));assert.equal(record.value.state,'bound_closed');assert.equal(record.value.write_eligible,false);
            assert.deepEqual(record.value.runtime_binding_ref,adopted.ref);assert.equal(record.value.session_ref.id,execution.binding.ipc_session_id);
            assert.equal(record.value.catalog_approval_ref.id,source.approval.approval_id);assert.equal(record.value.initial_sample_ref.id,source.sample.sample_id);
            assert.equal(record.value.binding.device_session_id,source.approval.device_session_id);
            assert.equal(record.value.transport_profile.transport,'memory');assert.equal(record.value.transport_profile.automatic_resends,false);
            assert.equal(record.value.primitive_plan.primitive_id,'simulator_value_set');
            assert.equal(record.value.transport_profile_ref.digest,digestValue(record.value.transport_profile));
            assert.equal(record.value.primitive_plan_ref.digest,digestValue(record.value.primitive_plan));
          }
          assert.notEqual(bound.first.value.binding.writer_exit_id,fresh.value.binding.writer_exit_id);
          assert.notEqual(bound.first.ref.id,fresh.ref.id);assert.equal(frames.find(f=>f.event==='execution-disconnected')?.code,'module_session');
          assert.ok(frames.find(f=>f.event==='execution-revoked')?.code);assert.notEqual(frames.find(f=>f.event==='execution-revoked')?.code,'unexpected_success');
        }
        assert.equal(samples.accepted.approval.evidence_policy.write_eligible,false);
        assert.equal(samples.accepted.approval.qualification.qualification,writable?'fixed_memory_control_catalog/1':'fixed_memory_read_only/1');
        assert.deepEqual(samples.connected.body.catalog.action_ids,writable?requestedActions:[]);
        assert.equal(samples.accepted.sample.value.sample_sequence,'2');assert.equal(samples.fresh.sample.value.sample_sequence,'1');
        assert.notEqual(samples.accepted.catalog_approval_ref.object_id,samples.fresh.catalog_approval_ref.object_id);
        assert.equal(frames.find(f=>f.event==='catalog-disconnected')?.code,'module_session');
        assert.ok(frames.find(f=>f.event==='catalog-revoked')?.code);assert.notEqual(frames.find(f=>f.event==='catalog-revoked')?.code,'unexpected_success');
        assert.deepEqual(samples.connected.body.identity,{kind:'virtual',model:writable?'leafseamer.simulator.control':'leafseamer.simulator',revision:'1'});
        assert.deepEqual(samples.first.body.value,writable?{value:0,sample_sequence:'1',write_sequence:'0'}:{value:0,sample_sequence:'1'});assert.deepEqual(samples.second.body.value,writable?{value:0,sample_sequence:'2',write_sequence:'0'}:{value:0,sample_sequence:'2'});
        assert.notEqual(samples.first.body.capture_id,samples.second.body.capture_id);
        assert.equal(samples.first.body.device_session_id,samples.connected.body.device_session_id);
        assert.deepEqual(samples.first.binding.runtime_binding_ref,adopted.ref);
        assert.equal(samples.disconnected.type,'DISCONNECTED');
        assert.equal(samples.disconnected.body.device_session_id,samples.connected.body.device_session_id);
        assert.equal(frames.find(f=>f.event==='module-disconnected-read')?.code,'module_session');
        assert.notEqual(samples.reconnected.body.device_session_id,samples.connected.body.device_session_id);
        assert.equal(samples.third.body.device_session_id,samples.reconnected.body.device_session_id);
        assert.deepEqual(samples.third.body.value,writable?{value:0,sample_sequence:'1',write_sequence:'0'}:{value:0,sample_sequence:'1'});
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
      if(mode==='supervisor_create_module'||mode==='supervisor_create_module_writable'){
        assert.equal(business.prepare('SELECT count(*) FROM execution_session').pluck().get(),1);
        assert.equal(business.prepare('SELECT count(*) FROM execution_session_commit').pluck().get(),1);
        assert.equal(business.prepare('SELECT reason FROM execution_session_end').pluck().get(),'runtime_lost');
        assert.equal(business.prepare('SELECT count(*) FROM execution_rejection').pluck().get(),0);
        assert.equal(business.prepare('SELECT count(*) FROM device_execution_binding').pluck().get(),writable?2:0);
        assert.equal(business.prepare('SELECT count(*) FROM device_execution_binding_commit').pluck().get(),writable?2:0);
        assert.deepEqual(business.pragma('foreign_key_check'),[]);
        if(writable){
          const service=frames.find(f=>f.event==='service-identity-active');assert.equal(service?.principal.kind,'service');
          assert.equal(service.principal.state,'active');assert.equal(service.credential.state,'active');assert.deepEqual(service.credential.proof_ref,service.proof_ref);
          assert.equal(business.prepare("SELECT count(*) FROM subject WHERE kind='service'").pluck().get(),1);
          assert.equal(business.prepare('SELECT count(*) FROM local_principal WHERE principal_id=?').pluck().get(service.principal.id),0);
          assert.equal(business.prepare('SELECT count(*) FROM auth_session WHERE principal_id=?').pluck().get(service.principal.id),0);
          assert.equal(business.prepare('SELECT count(*) FROM service_credential_revision').pluck().get(),4);
          assert.equal(business.prepare('SELECT count(*) FROM service_identity_operation').pluck().get(),6);
          const serviceToken=frames.find(f=>f.event==='service-token-verified');assert.equal(serviceToken?.authorization.principal_kind,'service');
          assert.equal(serviceToken.principal.id,service.principal.id);assert.equal(serviceToken.binding.credential_ref.id,service.credential.id);
          assert.deepEqual(serviceToken.authorization.device_ids,runtimeInput.devices);assert.equal(serviceToken.binding.policy_ref.id,serviceToken.policy.id);
          assert.equal(business.prepare('SELECT count(*) FROM service_access_token').pluck().get(),1);
          assert.equal(business.prepare('SELECT count(*) FROM service_token_operation').pluck().get(),3);
          assert.equal(frames.find(f=>f.event==='service-principal-revoked')?.operation.principal.state,'revoked');
          assert.equal(frames.find(f=>f.event==='service-principal-token-revoked')?.code,'service_token_invalid');
          assert.equal(business.prepare('SELECT r.state FROM service_principal_head h JOIN service_principal_revision r USING(principal_id,revision)').pluck().get(),'revoked');
          assert.equal(business.prepare('SELECT state FROM service_access_token_terminal').pluck().get(),'revoked');
          const evaluator=frames.find(f=>f.event==='evaluator-source');assert.ok(evaluator);assert.deepEqual(evaluator.source,evaluator.current);assert.deepEqual(evaluator.source,evaluator.replayed);
          assert.equal(evaluator.source.value.credential_ref.id,service.credential.id);assert.equal(evaluator.source.value.policy_ref.id,frames.find(f=>f.event==='evaluator-policy').policy.id);
          assert.equal(frames.find(f=>f.event==='evaluator-wrong-secret')?.code,'service_identity_credential_invalid');
          assert.equal(frames.find(f=>f.event==='evaluator-wrong-nonce')?.code,'evaluator_source_response_binding');
          assert.equal(frames.find(f=>f.event==='evaluator-conflict')?.code,'evaluator_source_conflict');
          assert.notEqual(frames.find(f=>f.event==='evaluator-expired')?.code,'unexpected_success');assert.ok(frames.find(f=>f.event==='evaluator-expired')?.code);
          assert.equal(frames.find(f=>f.event==='evaluator-revoked')?.code,'service_identity_approval_required');
          assert.equal(business.prepare('SELECT count(*) FROM device_evaluator_source').pluck().get(),3);
          assert.equal(business.prepare('SELECT count(*) FROM device_evaluator_challenge').pluck().get(),3);
          assert.equal(business.prepare('SELECT count(*) FROM device_evaluator_operation').pluck().get(),7);
          const context=frames.find(f=>f.event==='authorization-context')?.value,refreshedContext=frames.find(f=>f.event==='authorization-context-refreshed')?.value,
            reboundContext=frames.find(f=>f.event==='authorization-context-rebound')?.value;
          assert.ok(context&&refreshedContext&&reboundContext);assert.equal(context.context_digest,digestValue(context.context));
          assert.deepEqual(context.context,refreshedContext.context);assert.deepEqual(context.state_ref,refreshedContext.state_ref);
          assert.notEqual(context.source_refs.holder.id,refreshedContext.source_refs.holder.id);assert.notEqual(context.source_refs.evaluator.id,refreshedContext.source_refs.evaluator.id);
          assert.notDeepEqual(context.context.holder_lineage,reboundContext.context.holder_lineage);assert.notEqual(context.binding.device_session_id,reboundContext.binding.device_session_id);
          assert.deepEqual(context.context.evaluator_lineage,reboundContext.context.evaluator_lineage);
          assert.equal(context.context.holder_lineage.principal_kind,'human');assert.equal(context.context.evaluator_lineage.principal_kind,'service');
          assert.deepEqual(context.authorization_dependencies.map(v=>v.role),['evaluator','manual']);
          for(const v of [context,refreshedContext,reboundContext]){
            assert.deepEqual(v.windows.map(w=>w.role),['evaluator','holder']);
            assert.equal(v.expires_tick_ns,String(v.windows.map(w=>BigInt(w.before_tick_ns)).reduce((a,b)=>a<b?a:b)));
            assert.ok(BigInt(v.selected_tick_ns)<BigInt(v.expires_tick_ns));
          }
          assert.equal(frames.find(f=>f.event==='authorization-context-device')?.code,'device_authorization_device');
          for(const event of ['authorization-context-injected','authorization-context-missing'])assert.equal(frames.find(f=>f.event===event)?.code,'device_authorization_input');
          assert.equal(frames.find(f=>f.event==='authorization-context-revoked')?.code,'service_identity_approval_required');
          const recovery=frames.find(f=>f.event==='recovery-accepted');assert.ok(recovery);
          assert.deepEqual(recovery.value,recovery.replayed);assert.deepEqual(recovery.value,recovery.current);
          assert.deepEqual(frames.find(f=>f.event==='recovery-history')?.value,recovery.value);assert.deepEqual(frames.find(f=>f.event==='recovery-history')?.replayed,recovery.value);
          assert.equal(frames.find(f=>f.event==='recovery-no-permission')?.code,'device_recovery_permission');
          assert.equal(frames.find(f=>f.event==='recovery-wrong-context')?.code,'device_recovery_context');
          assert.equal(frames.find(f=>f.event==='recovery-conflict')?.code,'device_recovery_conflict');
          assert.ok(frames.find(f=>f.event==='recovery-expired')?.code);assert.notEqual(frames.find(f=>f.event==='recovery-expired')?.code,'unexpected_success');
          const recoveryAuthorization=recovery.value.authorization;
          assert.equal(recoveryAuthorization.requester_kind,'human');assert.equal(recoveryAuthorization.proposed_context_digest,context.context_digest);
          assert.deepEqual(recoveryAuthorization.binding,context.binding);assert.deepEqual(recoveryAuthorization.protected_state_ref,context.state_ref);
          assert.deepEqual(recovery.value.receipt.request.manual_source_ref,refreshedContext.source_refs.holder);
          assert.deepEqual(recovery.value.receipt.request.evaluator_source_ref,refreshedContext.source_refs.evaluator);
          assert.ok(BigInt(recoveryAuthorization.expires_tick_ns)<=BigInt(refreshedContext.expires_tick_ns));
          for(const table of ['device_recovery_request','device_recovery_authorization','device_recovery_commit']){
            assert.equal(business.prepare('SELECT count(*) FROM '+table).pluck().get(),2);
            assert.throws(()=>business.prepare('UPDATE '+table+' SET body_jcs=body_jcs').run(),/immutable_device_recovery/);
          }
          const consumed=frames.find(f=>f.event==='recovery-consumed');assert.ok(consumed);assert.deepEqual(consumed.value,consumed.replayed);
          assert.equal(consumed.value.value.status,'policy_selected');assert.deepEqual(consumed.value.value.parent_ref,context.state_ref);
          assert.deepEqual(consumed.value.value.context,context.context);assert.equal(consumed.value.recovery.authorization.authorization_id,recoveryAuthorization.authorization_id);
          const selectedContext=frames.find(f=>f.event==='authorization-context-selected')?.value;
          assert.deepEqual(selectedContext.state_ref,consumed.value.ref);assert.deepEqual(selectedContext.context,context.context);
          for(const event of ['recovery-consumed-history','recovery-old-history'])assert.deepEqual(frames.find(f=>f.event===event)?.value,consumed.value);
          assert.equal(frames.find(f=>f.event==='recovery-old-state')?.code,'device_recovery_state');
          assert.equal(frames.find(f=>f.event==='recovery-expired-consumption')?.code,'manual_authority_expired');
          assert.equal(business.prepare('SELECT count(*) FROM device_recovery_consumption').pluck().get(),1);
          assert.throws(()=>business.prepare('UPDATE device_recovery_consumption SET body_jcs=body_jcs').run(),/immutable_device_recovery_consumption/);
          const {collectAuthorizationDependencies,currentAuthorizationDependencies}=await load('authorization-dependencies.mjs');
          const [serviceId,databaseId]=business.prepare('SELECT service_id,database_instance_id FROM service_state').raw().get();
          const dependencyService={service_id:serviceId,database_instance_id:databaseId};
          const verifyDependencies=(value,role)=>{
            const snapshot=value.authorization_dependencies;
            assert.equal(snapshot?.format,'local-device-authorization-dependencies/1');assert.equal(snapshot.role,role);
            assert.deepEqual(snapshot.scope,{authority_service_id:serviceId,database_instance_id:databaseId});
            assert.equal(snapshot.device_id,role==='manual'?value.binding.device_id:value.device_id);
            assert.deepEqual(snapshot.records.map(v=>v.kind),role==='manual'?['access_token','credential','issuer','policy','principal','session','subject']:['approval','credential','issuer','policy','principal','subject']);
            assert.equal(snapshot.result,'no_matching_denial');assert.deepEqual(snapshot.denied,[]);
            const {digest,...body}=snapshot;assert.equal(digest,digestValue(body));
            const revoked=role==='evaluator'||value.session_id===frames.find(f=>f.event==='manual-source-rebound').source.value.session_id;
            if(revoked)business.transaction(()=>{
              const current=collectAuthorizationDependencies(business,dependencyService,role,value);
              assert.equal(current.result,'denied');assert.ok(current.denied.includes(role==='manual'?'session_floor':'principal'));
              assert.ok(current.events.some(v=>v.kind===(role==='manual'?'session':'principal')));
              assert.throws(()=>currentAuthorizationDependencies(business,dependencyService,role,value),e=>e.code==='authorization_dependencies_changed');
            }).immediate();
          };
          const verifyAuthenticationWindow=value=>{
            const window=value.authentication_window;assert.equal(window?.format,'authentication-monotonic-window/1');
            assert.equal(window.before_tick_ns,value.expires_tick_ns);assert.equal(window.selected_tick_ns,value.selected_tick_ns);
            const bytes=business.prepare('SELECT body FROM authentication_clock_acquisition WHERE id=?').pluck().get(window.acquisition_ref.id),a=JSON.parse(bytes.toString());
            const runtime=JSON.parse(business.prepare('SELECT body_jcs FROM core_runtime_source WHERE source_id=?').pluck().get(value.core_runtime_source_ref.id));
            assert.deepEqual(window.domain_ref,runtime.domain_ref);assert.equal(a.clock_domain_id,runtime.domain_ref.clock_domain_id);assert.equal(a.descriptor_digest,runtime.domain_ref.descriptor_digest);
            assert.equal(a.raw.platform,'win32');assert.equal(a.digest,window.acquisition_ref.digest);
            const nativeRuntime=JSON.parse(business.prepare('SELECT body FROM authentication_clock_evidence WHERE id=?').pluck().get(a.runtime_ref.id).toString());
            const installed=JSON.parse(fs.readFileSync(path.join(controller,'dist/native/manifest.json'),'utf8'));assert.equal(nativeRuntime.native_binary_digest,'sha256:'+installed.binary_sha256);
            const wallDeadline=BigInt(a.b)+(BigInt(window.valid_before_ns)-BigInt(a.effective_upper_ns)-1n)*1000000000n/(1000000000n+BigInt(a.drift_ppb))+1n;
            assert.ok(BigInt(window.before_tick_ns)<=wallDeadline&&BigInt(window.before_tick_ns)<=BigInt(a.valid_before_tick_ns)&&BigInt(window.before_tick_ns)<=BigInt(runtime.expires_tick_ns));
            const {digest,...body}=window;assert.equal(digest,digestValue(body));
          };
          for(const body of business.prepare('SELECT body_jcs FROM device_evaluator_source').pluck().all()){
            const v=JSON.parse(body);assert.equal('secret'in v,false);assert.ok(BigInt(v.selected_tick_ns)<BigInt(v.expires_tick_ns));
            verifyAuthenticationWindow(v);
            verifyDependencies(v,'evaluator');
          }
          const serviceApproval=JSON.parse(business.prepare('SELECT body_jcs FROM service_approval').pluck().get());
          assert.equal(service.credential.principal_id,service.principal.id);assert.deepEqual(serviceApproval.device_ids,runtimeInput.devices);
          assert.equal(business.prepare('SELECT count(*) FROM ca_command_initial').pluck().get(),0);
          assert.equal(business.prepare('SELECT count(*) FROM ca_adjudication').pluck().get(),0);
          assert.equal(business.prepare('SELECT sum(used_count) FROM request_context').pluck().get(),1); // 只有实际人员接管消耗预算。
          const negotiation=JSON.parse(business.prepare('SELECT body_jcs FROM execution_handshake').pluck().get());
          assert.deepEqual(negotiation,(({ref,...body})=>body)(frames.find(f=>f.event==='execution-negotiated').negotiation));
          assert.equal(business.prepare('SELECT count(*) FROM execution_frame_record').pluck().get(),6);
          assert.equal(business.prepare('SELECT count(*) FROM execution_effect_commit').pluck().get(),6);
          assert.equal(business.prepare('SELECT count(*) FROM execution_write_attempt').pluck().get(),3);
          assert.equal(business.prepare('SELECT count(*) FROM execution_initial_fence').pluck().get(),2);
          assert.equal(business.prepare('SELECT count(*) FROM execution_initial_fence_ack').pluck().get(),2);
          assert.equal(business.prepare('SELECT count(*) FROM execution_control_frame').pluck().get(),4);
          for(const table of ['manual_execution_challenge','manual_execution_challenge_commit','manual_execution_challenge_response'])assert.equal(business.prepare('SELECT count(*) FROM '+table).pluck().get(),4);
          assert.equal(business.prepare('SELECT count(*) FROM execution_manual_authority').pluck().get(),4);
          assert.equal(business.prepare('SELECT count(*) FROM execution_manual_authority_commit').pluck().get(),4);
          for(const [text,digest] of business.prepare('SELECT body_jcs,body_digest FROM execution_manual_authority').raw().all()){
            const value=JSON.parse(text),{digest:own,...body}=value;assert.equal(digestValue(body),digest);assert.equal(own,digest);
            verifyAuthenticationWindow(value);
            verifyDependencies(value,'manual');
            const challenge=JSON.parse(business.prepare('SELECT body_jcs FROM manual_execution_challenge WHERE challenge_id=?').pluck().get(value.challenge_ref.id));
            const {digest:challengeDigest,...challengeBody}=challenge;assert.equal(challengeDigest,digestValue(challengeBody));
            assert.equal(challenge.format,'manual-execution-challenge/1');assert.deepEqual(value.challenge_ref,{id:challenge.id,revision:'1',digest:challengeDigest});
            assert.match(challenge.nonce,/^[A-Za-z0-9_-]{43}$/);assert.equal(Buffer.from(challenge.nonce,'base64url').length,32);
            for(const field of ['binding','binding_ref','control_state_ref','control_authority_ref','token_id','session_id','credential_id','policy_ref','core_runtime_source_ref'])assert.deepEqual(value[field],challenge[field]);
            assert.equal(value.authorization.digest,challenge.authorization_digest);
            assert.equal(value.challenge_response_digest,digestValue({request_id:value.challenge_response_id,challenge_ref:value.challenge_ref,nonce:challenge.nonce}));
            assert.deepEqual(business.prepare('SELECT challenge_id,request_id,request_digest FROM manual_execution_challenge_response WHERE source_id=?').raw().get(value.id),[challenge.id,value.challenge_response_id,value.challenge_response_digest]);
            assert.ok(BigInt(challenge.issued_tick_ns)<=BigInt(value.selected_tick_ns)&&BigInt(value.expires_tick_ns)<=BigInt(challenge.expires_tick_ns));

            assert.ok(BigInt(value.expires_tick_ns)>BigInt(value.selected_tick_ns)&&BigInt(value.expires_tick_ns)-BigInt(value.selected_tick_ns)<=2000000000n);
            assert.equal(value.authorization.permissions.includes('device.command'),true);
            const runtime=JSON.parse(business.prepare('SELECT body_jcs FROM core_runtime_source WHERE source_id=?').pluck().get(value.core_runtime_source_ref.id));
            assert.equal(runtime.digest,value.core_runtime_source_ref.digest);assert.ok(BigInt(value.expires_tick_ns)<=BigInt(runtime.expires_tick_ns));
            const {digest:runtimeDigest,...runtimeBody}=runtime;assert.equal(runtimeDigest,digestValue(runtimeBody));
            const observation=runtime.observation;
            assert.equal(observation.response.reply_to,observation.request.message_id);
            assert.deepEqual(observation.request.scope,observation.response.scope);
            assert.deepEqual(observation.response.payload.record.admission_receipt,runtime.core.receipt);
            assert.equal(BigInt(observation.expires_tick_ns)-BigInt(observation.issued_tick_ns),2000000000n);
            assert.equal('secret' in value,false);assert.equal('verifier' in value,false);
          }
          assert.throws(()=>business.exec('DELETE FROM execution_manual_authority'),/immutable_manual_authority/);
          const observedSources=[...new Set(['manual_execution_challenge','device_evaluator_challenge'].flatMap(table=>
            business.prepare("SELECT json_extract(body_jcs,'$.core_runtime_source_ref.id') FROM "+table).pluck().all()))].sort();
          assert.ok(observedSources.length>=2);
          assert.deepEqual(business.prepare('SELECT source_id FROM core_runtime_source ORDER BY source_id').pluck().all(),observedSources);
          assert.deepEqual(business.prepare('SELECT source_id FROM core_runtime_source_commit ORDER BY source_id').pluck().all(),observedSources);
          assert.throws(()=>business.exec('DELETE FROM core_runtime_source'),/immutable_core_runtime_source/);
          const sources=business.prepare('SELECT source_id,body_jcs,body_digest FROM control_state_source ORDER BY revision').raw().all();
          assert.equal(sources.length,2);
          const {currentControlSource}=await load('device-control-source.mjs');
          const selected=business.transaction(()=>currentControlSource(business,JSON.parse(sources[1][1]).device_id))();
          assert.deepEqual(selected.current.ref,selected.authority.ref);assert.equal(selected.current.value.change_kind,'effective');
          const {currentDeviceAuthorization}=await load('device-authorization-state.mjs');
          const authorization=business.transaction(()=>currentDeviceAuthorization(business,selected.current.value.device_id))();
          assert.equal(authorization.value.status,'protected');assert.equal(authorization.value.recovery_ref,null);
          assert.equal(authorization.value.context.evaluator_lineage,null);
          assert.deepEqual(authorization.value.context.control_authority_ref,selected.authority.ref);
          assert.deepEqual(authorization.ref,frames.find(f=>f.event==='manual-source-rebound').source.value.authorization_state_ref);
          assert.equal(authorization.value.reasons[0],'runtime_changed');assert.equal(authorization.value.revision,'4');
          assert.equal(business.prepare('SELECT count(*) FROM device_authorization_state').pluck().get(),4);
          assert.equal(business.prepare('SELECT count(*) FROM device_authorization_commit').pluck().get(),4);
          assert.equal(business.prepare('SELECT count(*) FROM device_authorization_head').pluck().get(),1);
          assert.deepEqual(business.prepare('SELECT protection_jcs FROM device_authorization_commit ORDER BY rowid').pluck().all().map(text=>JSON.parse(text).kind),
            ['device_authorization_protection_intent','device_authorization_protection_intent','device_authorization_recovery_intent','device_authorization_protection_intent']);
          for(const [id,text,digest] of sources){const value=JSON.parse(text),{record_digest,...body}=value;
            assert.equal(canonicalize(value),text);assert.equal(digestValue(body),digest);assert.equal(record_digest,digest);assert.equal(value.change_id,id);
            assert.equal(value.clock_domain_id,frames.find(f=>f.event==='execution-session').binding.clock_domain_id);
          }
          for(const text of business.prepare('SELECT body_jcs FROM execution_initial_fence').pluck().all()){
            const value=JSON.parse(text);assert.deepEqual(value.control_source_ref,selected.current.ref);assert.notEqual(value.control_source_ref.id,value.control_record.record_id);
          }
          assert.throws(()=>business.exec('DELETE FROM control_state_source'),/immutable_control_source/);
          assert.equal(business.prepare('SELECT result FROM execution_write_result').pluck().get(),'complete');
          const hello=JSON.parse(business.prepare("SELECT frame_jcs FROM execution_frame_record WHERE direction='w2c'").pluck().get());
          const ack=JSON.parse(business.prepare("SELECT frame_jcs FROM execution_frame_record WHERE direction='c2w'").pluck().get());
          assert.equal(hello.type,'HELLO');assert.equal(ack.type,'HELLO_ACK');assert.equal(ack.reply_to,hello.message_id);
          assert.ok(negotiation.selected_features.every(feature=>hello.body.supported_features.includes(feature)));
          assert.ok(hello.body.supported_features.includes('encoding_authority_before_issue'));
          assert.ok(hello.body.supported_features.includes('reference_time_absent'));
          assert.deepEqual(ack.body.selected_features,negotiation.selected_features);
          assert.equal(hello.body.module_digest,negotiation.module_digest);assert.equal(hello.worker_boot_id,frames.find(f=>f.event==='execution-session').binding.worker_boot_id);
          const records=business.prepare('SELECT body_jcs,body_digest FROM device_execution_binding').raw().all();
          for(const [body,digest] of records){const value=JSON.parse(body);assert.equal(digestValue(value),digest);assert.equal(value.write_eligible,false);}
          assert.throws(()=>business.exec('DELETE FROM device_execution_binding'),/immutable_execution_binding/);
          assert.throws(()=>business.exec('UPDATE device_execution_binding_commit SET transaction_id=transaction_id'),/immutable_execution_binding/);
        }
        assert.equal(business.prepare('SELECT count(*) FROM device_catalog_approval').pluck().get(),2);
        assert.equal(business.prepare('SELECT count(*) FROM device_baseline_sample').pluck().get(),3);
        assert.throws(()=>business.exec('DELETE FROM device_catalog_approval'),/immutable_device_catalog/);
        assert.throws(()=>business.exec('UPDATE device_baseline_sample SET sample_sequence=sample_sequence'),/immutable_device_baseline/);
        assert.equal(business.prepare('SELECT count(*) FROM device_module_channel').pluck().get(),1);
        assert.equal(business.prepare('SELECT count(*) FROM device_module_frame').pluck().get(),mode==='supervisor_create_module_writable'?20:14);
        assert.equal(business.prepare('SELECT count(*) FROM device_module_frame_commit').pluck().get(),mode==='supervisor_create_module_writable'?20:14);
        if(mode==='supervisor_create_module_writable'){
          const boundFrames=business.prepare("SELECT frame_jcs FROM device_module_frame WHERE message_type='EXECUTION_BOUND' ORDER BY length(sequence),sequence").pluck().all().map(JSON.parse);
          assert.equal(boundFrames.length,3);assert.deepEqual(boundFrames[0].body.execution_ref,boundFrames[1].body.execution_ref);
          assert.notDeepEqual(boundFrames[0].body.execution_ref,boundFrames[2].body.execution_ref);
        }
        const captures=business.prepare("SELECT frame_jcs FROM device_module_frame WHERE message_type='CAPTURED' ORDER BY length(sequence),sequence").pluck().all().map(JSON.parse);
        assert.deepEqual(captures.map(f=>f.body.value.sample_sequence),['1','2','1']);
        assert.equal(new Set(captures.map(f=>f.body.device_session_id)).size,2);
        assert.throws(()=>business.exec('DELETE FROM device_module_frame'),/immutable_module_frame/);
      }
    }finally{business.close();}}
  }
});
