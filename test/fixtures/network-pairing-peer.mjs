import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import https from 'node:https';
import os from 'node:os';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import * as controller from '../../../leafseamer-controller/dist/storage.mjs';
import * as seamer from '../../../leafseamer/dist/storage.mjs';
import {canonical,digest,ref,seal} from '../../../leafseamer-controller/dist/auth-clock-value.mjs';
import {normalizeCapture} from '../../../leafseamer-controller/dist/native-clock.mjs';
import {pairingCertificate} from '../../../leafseamer-controller/dist/peer-pairing-value.mjs';
import {createIntrospectionEndpoint} from '../../../leafseamer-controller/dist/introspection-http.mjs';
import {createPeerIdentityReceiver} from '../../../leafseamer/dist/peer-identity.mjs';

const [role,exchange]=process.argv.slice(2);
assert.ok(['controller','seamer'].includes(role)&&path.isAbsolute(exchange));
const id=()=>crypto.randomUUID(),port=47361,serverName=role+'.test';
const host=Object.values(os.networkInterfaces()).flat().find(entry=>entry.family==='IPv4'&&!entry.internal)?.address;
assert.ok(host&&host!== '127.0.0.1');
const origin='https://'+host+':'+port;
const file=name=>path.join(exchange,name);
const pem=name=>fs.readFileSync(file(name+'.pem'),'utf8');
const ca=pem('ca'),cert=pem(role),key=pem(role+'-key');
const publish=(name,value)=>{const temporary=file(name+'.new');fs.writeFileSync(temporary,canonical(value));fs.renameSync(temporary,file(name));};
async function receive(name){
 const deadline=performance.now()+60000;
 while(!fs.existsSync(file(name))){assert.ok(performance.now()<deadline,'missing '+name);await delay(30);}
 return JSON.parse(fs.readFileSync(file(name),'utf8'));
}

// 受控采集证明只用于联调。两端各自保持单调域和持久认证账本。
function clockFor(store,{startAuthenticationClock}){
 const tick=()=>process.hrtime.bigint()/100n*100n,anchor=tick(),wall=BigInt(Date.now())*1000000n;
 const source={tick,artifactDigest:digest('controlled network fixture'),capture(){
  const before=tick(),time=wall+before-anchor;
  return normalizeCapture({format:'leafseamer-native-clock/1',platform:'win32',before_100ns:String(before/100n),after_100ns:String(tick()/100n),
   wall_filetime_100ns:String(116444736000000000n+time/100n),continuity_before:'0',continuity_after:'0',continuity_monitor:'power_notifications'});
 }};
 const scope=store.authenticationClock.scope,reference=()=>ref(seal({id:id(),revision:'1'})),valid_before_tick_ns=String(anchor+120000000000n);
 const policy=seal({id:id(),revision:'1',service_id:scope.service_id,runtime_profile_ref:reference(),native_artifact_ref:reference(),
  system_time_source_ref:reference(),environment_approval_ref:reference(),health_profile_ref:reference(),max_system_error_ns:'10000000',
  wall_quantization_ns:'100',monotonic_quantization_ns:'100',drift_ppb:1000000,capture_limit_ns:'20000000',sample_period_ns:'500000000',
  sample_ttl_ns:'5000000000',sample_window_policy:'authentication-clock-sample/2'});
 const runtime=seal({id:id(),revision:'1',...scope,clock_domain_id:id(),descriptor_digest:digest('clock '+role),policy_ref:ref(policy),
  runtime_profile_ref:policy.runtime_profile_ref,native_artifact_ref:policy.native_artifact_ref,environment_approval_ref:policy.environment_approval_ref,
  native_binary_digest:source.artifactDigest,continuity:source.capture().continuity,valid_before_tick_ns});
 const health=seal({id:id(),revision:'1',...scope,clock_domain_id:runtime.clock_domain_id,runtime_ref:ref(runtime),policy_ref:ref(policy),
  health_profile_ref:policy.health_profile_ref,system_time_source_ref:policy.system_time_source_ref,environment_approval_ref:policy.environment_approval_ref,
  state:'synchronized',holdover_ref:null,valid_before_tick_ns});
 const clock=startAuthenticationClock(source,store.authenticationClock,{read:()=>({policy,runtime,health})});
 assert.equal(clock.status().qualified,true);
 return clock;
}

function peer(identity){return {identity,origin,server_name:serverName,trust_bundle_digest:digest([
 'sha256:'+crypto.createHash('sha256').update(new crypto.X509Certificate(ca).raw).digest('hex')])};}
function configuration(value){return {...value.identity,...pairingCertificate(new crypto.X509Certificate(cert).raw),trust_bundle_digest:value.trust_bundle_digest,
 endpoint_config_digest:digest({origin:value.origin,server_name:value.server_name})};}
const dataDir=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-network-'));
const controllerRole=role==='controller';
const localProfile=identity=>({credential_id:identity.credential_id,host,port,network:true,server_name:serverName,
 certificate_file:file(role+'.pem'),private_key_file:file(role+'-key.pem'),ca_files:[file('ca.pem')]});
const remoteProfile=(value,name)=>({identity:value.identity,origin:value.origin,server_name:value.server_name,
 certificate_file:file(name+'.pem'),trust_bundle_digest:value.trust_bundle_digest});
function clockProfile(){
 const public_key_file=path.join(dataDir,'clock-key.pem');
 fs.writeFileSync(public_key_file,crypto.generateKeyPairSync('ed25519').publicKey.export({type:'spki',format:'pem'}));
 return {policy_digest:digest('fixture clock'),public_key_file,evidence_file:path.join(dataDir,'clock-evidence.json')};
}
function readProfile(reader,profile,...args){
 const json=path.join(dataDir,'fixture-profile.json');
 const read=value=>{fs.writeFileSync(json,canonical(value));return reader(json,...args);};
 assert.throws(()=>read({...profile,local:{...profile.local,network:false}}),{code:'pairing_profile_invalid'});
 return read(profile);
}
let store,clock,transport,receiver;
try{
 if(controllerRole){
  const {startAuthenticationClock}=await import('../../../leafseamer-controller/dist/auth-clock.mjs');
  const {startPeerPairingTransport}=await import('../../../leafseamer-controller/dist/peer-pairing-transport.mjs');
  const {readTrustedPairingProfile}=await import('../../../leafseamer-controller/dist/trusted-pairing-profile.mjs');
  controller.initializeStorage(dataDir);await controller.migrateStorage(dataDir,93);
  store=controller.openStorage(dataDir);clock=clockFor(store,{startAuthenticationClock});
  const bootstrap=store.enrollment.begin(),credentials={login:'network.test',password:'Synthetic-network-test-123'};
  await store.enrollment.complete({token_id:bootstrap.token_id,secret:bootstrap.secret,...credentials,mode:'standalone'});
  const sessions=store.sessions(clock),login=await sessions.login(credentials),{principal_id,issuer_id,issuer_epoch}=login.session;
  const auth={credential_id:login.credential_id,secret:login.secret,csrf:login.csrf},api=sessions.peerPairings;
  const selected=peer({service_id:store.identity.service_id,database_instance_id:store.identity.database_instance_id,
   service_kind:role,issuer_id,issuer_epoch,credential_id:id()});
  publish('controller.json',{...selected,principal_id});
  const other=await receive('seamer.json');
  assert.notEqual(new URL(other.origin).hostname,host);
  const profile=readProfile(readTrustedPairingProfile,{format:'leafseamer.controller-pairing-profile/1',
   bootstrap:{format:'leafseamer-core-bootstrap-policy/1',service_id:store.identity.service_id,database_instance_id:store.identity.database_instance_id,
    artifact_manifest_ref:{manifest_id:'fixture',revision:'1',digest:digest('fixture manifest')},platform_profile_ref:{profile_id:'fixture',revision:'1'},
    policy_revision:'1',bootstrap_timeout_ms:10000,clock_backend_revision:'1'},
   https:{origin:'https://127.0.0.1:47362',certificate_file:file('controller.pem'),private_key_file:file('controller-key.pem')},
   clock:clockProfile(),local:localProfile(selected.identity),seamer:remoteProfile(other,'seamer')},'127.0.0.1',47362);
  const {peers,...pairing}=profile.pairing,options={pairings:api,clock,identity:selected.identity,...pairing};
  await assert.rejects(startPeerPairingTransport({...options,network:false}),{code:'peer_pairing_listen'});
  await assert.rejects(startPeerPairingTransport({...options,host:'0.0.0.0',network:true}),{code:'peer_pairing_listen'});
  transport=await startPeerPairingTransport({...options,introspection:createIntrospectionEndpoint({sessions,
   serviceId:store.identity.service_id,serviceBootId:store.serviceBootId})});
  assert.equal(transport.origin,origin);assert.deepEqual(transport.configuration,configuration(selected));
  transport.bindPeers(peers);
  const now=clock.pairingSample(),begin=BigInt(now.lower_ns)-1000000000n,end=begin+60000000000n;
  const party=(config,permissions)=>({...config,binding_id:id(),permissions,object_scope_digest:digest({devices:[]}),not_before_ns:String(begin),expires_ns:String(end)});
  const remoteConfig={...other.identity,...pairingCertificate(new crypto.X509Certificate(pem('seamer')).raw),trust_bundle_digest:other.trust_bundle_digest,
   endpoint_config_digest:digest({origin:other.origin,server_name:other.server_name})};
  const transcript={format:'leafseamer.peer-pairing/1',pair_attempt_id:id(),parties:[party(transport.configuration,[]),party(remoteConfig,['auth.introspect'])]};
  const staged=api.stage(auth,{request_id:id(),transcript});
  publish('authorization.json',api.exportFirstPairingAuthorization(auth,{binding_id:staged.binding_id,transcript_digest:staged.transcript_digest}));
  await receive('seamer-staged');await transport.prove(staged.binding_id);publish('controller-proved',true);
  await receive('seamer-proved');
  const proved=api.get(auth,staged.binding_id);
  assert.equal(proved.state,'proved');assert.equal(proved.proof_refs.length,2);
  const active=api.activate(auth,{request_id:id(),binding_id:proved.binding_id,expected_revision:proved.revision,transcript_digest:proved.transcript_digest});
  publish('controller-active',true);await receive('seamer-active');
  const permissions=['auth.manage','auth.read'];
  sessions.remotePermissions.replace(auth,{request_id:id(),principal_id,audience:other.identity.service_id,expected_revision:null,permissions,
   pairing_ref:{id:active.binding_id,revision:active.revision,digest:active.digest},not_before_ns:active.not_before_ns,expires_ns:active.expires_ns});
  const token=sessions.issueToken(auth,{request_id:id(),audience:other.identity.service_id,requested_scopes:permissions});
  publish('token',{value:'v1.'+token.token.token_id+'.'+token.secret});
  await receive('identity-verified');
  api.revoke(auth,{request_id:id(),binding_id:active.binding_id,expected_revision:active.revision});
  publish('controller-revoked',true);await receive('passed');
 }else{
  const other=await receive('controller.json'),{service_id,issuer_id,issuer_epoch}=other.identity,issuer={service_id,issuer_id,issuer_epoch};
  const identity=seamer.initializeStorage(dataDir);seamer.migrateStorage(dataDir,'19');
  const selected=peer({service_id:identity.service_id,database_instance_id:identity.database_instance_id,
   service_kind:role,issuer_id,issuer_epoch,credential_id:id()});
  publish('seamer.json',selected);
  const envelope=await receive('authorization.json'),authorizationId=envelope.authorization.authorization_id;
  seamer.importFirstPairingAuthorization(dataDir,{bytes:Buffer.from(canonical(envelope)),controllerCertificate:Buffer.from(pem('controller')),seamerCertificate:Buffer.from(cert)});
  const {startAuthenticationClock}=await import('../../../leafseamer/dist/runtime/auth-clock.mjs');
  const {startPeerPairingTransport}=await import('../../../leafseamer/dist/runtime/peer-pairing-transport.mjs');
  const {readTrustedPairingProfile}=await import('../../../leafseamer/dist/trusted-pairing-profile.mjs');
  const profile=readProfile(readTrustedPairingProfile,{format:'leafseamer.seamer-pairing-profile/1',
   scope:{service_id:identity.service_id,database_instance_id:identity.database_instance_id},first_pairing_authorization_id:authorizationId,
   local:localProfile(selected.identity),controller:remoteProfile(other,'controller'),clock:clockProfile()});
  store=seamer.openStorage(dataDir);clock=clockFor(store,{startAuthenticationClock});
  const api=store.bindPeerPairings({clock,issuer});
  transport=await startPeerPairingTransport({pairings:api,clock,identity:selected.identity,...profile.pairing});
  assert.equal(transport.origin,origin);assert.deepEqual(transport.configuration,configuration(selected));
  const {principal_id}=other;transport.bindPeers([profile.peer]);
  const staged=api.stageFirstPairing(authorizationId);publish('seamer-staged',true);
  await receive('controller-proved');await transport.prove(staged.binding_id);publish('seamer-proved',true);
  await receive('controller-active');
  const remote=await transport.status(staged.binding_id);
  const active=api.activateFirstPairing(authorizationId,remote);
  assert.equal(active.administrator.principal_id,principal_id);assert.deepEqual(api.readFirstPairingCompletion(authorizationId),active);
  publish('seamer-active',true);
  const {value:token}=await receive('token');
  receiver=createPeerIdentityReceiver({service:store.identity,clock,pairings:api,transport,issuer,watermarks:store.identityWatermarks,denials:store.bindSessionDenials({issuer})});
  const local=store.bindLocalAuthorization({clock,receiver,issuer});
  const handle=await receiver.prepare({binding_id:staged.binding_id,token});
  assert.deepEqual(local.get(handle,principal_id).permissions,['auth.manage','auth.read']);
  const request=(headers={},material={cert,key})=>new Promise((resolve,reject)=>{
   const req=https.get(other.origin+'/internal/pairings/'+remote.binding_ref.id+'/status',{ca,...material,headers,agent:false,servername:'controller.test'},res=>{
    res.resume();res.once('end',()=>resolve(res.statusCode));
   });req.once('error',reject);req.setTimeout(5000,()=>req.destroy(new Error('timeout')));
  });
  assert.equal(await request(),200);
  assert.equal(await request({Host:'seamer.test'}),403);
  assert.equal(await request({'X-Forwarded-Host':'controller.test'}),403);
  assert.equal(await request({}, {cert:pem('wrong'),key:pem('wrong-key')}),403);
  await assert.rejects(request({},{}));
  publish('identity-verified',true);await receive('controller-revoked');
  await assert.rejects(receiver.prepare({binding_id:staged.binding_id,token}));
  assert.equal(await request(),403);publish('passed',true);
 }
}finally{
 receiver?.close();await transport?.close();clock?.stop();store?.close();
 fs.rmSync(dataDir,{recursive:true,force:true});
}
