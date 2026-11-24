import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import https from 'node:https';
import crypto from 'node:crypto';
import {once} from 'node:events';
import {execFile,spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
import {promisify} from 'node:util';
import {pathToFileURL} from 'node:url';
import Database from 'better-sqlite3';

const exec=promisify(execFile);
const controller=process.env.LEAFSEAMER_CONTROLLER_TEST_ROOT;
const gui=process.env.LEAFSEAMER_GUI_TEST_ROOT;
const edge=process.env.LEAFSEAMER_EDGE_TEST_EXECUTABLE;
const load=(root,file)=>import(pathToFileURL(path.join(root,file)).href);
const digest=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');
const contractHeaders=selection=>({'X-LeafSeamer-Contract':selection.contract_id,'X-LeafSeamer-Contract-Digest':selection.contract_digest});
async function waitFor(read,detail=()=>'',timeout=12000){
 const end=performance.now()+timeout;
 for(;;){const result=read();if(result)return result;assert.ok(performance.now()<end,detail());await delay(35);}
}
function request(origin,ca,route,{method='GET',headers={},body=null}={}){
 return new Promise((resolve,reject)=>{
  const req=https.request(origin+route,{method,ca,headers,timeout:5000},res=>{
   const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.once('error',reject);
   res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks)}));
  });
  req.on('error',reject);req.on('timeout',()=>req.destroy(new Error('standalone_request_timeout')));req.end(body);
 });
}

test('Windows 安装入口独立启动已绑定 GUI 的 Controller，并保留重启保护',{
 skip:process.platform!=='win32'||!controller||!gui,timeout:160000
},async t=>{
 assert.ok(path.isAbsolute(controller)&&path.isAbsolute(gui));
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-standalone-')),data=path.join(root,'controller'),assets=path.join(root,'gui');
 const children=new Set();
 function exitedGroups(){
  try{const db=new Database(path.join(data,'supervisor-journal.db'),{readonly:true,fileMustExist:true});
   try{return db.prepare('SELECT active_processes FROM core_exit').pluck().all();}finally{db.close();}
  }catch(error){if(['SQLITE_BUSY','SQLITE_CANTOPEN'].includes(error.code))return [];throw error;}
 }
 async function stop(run){
  if(run.child.exitCode===null&&run.child.signalCode===null)run.child.stdin.end('stop\n');
  const result=await run.exit;
  children.delete(run);
  return result;
 }
 t.after(async()=>{
  for(const run of children)await stop(run);
  assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));
  fs.rmSync(root,{recursive:true,force:true,maxRetries:5,retryDelay:100});
 });
 const file=(name,bytes)=>{const target=path.join(root,name);fs.writeFileSync(target,bytes);return target;};
 const cli=path.join(controller,'dist/cli.mjs');
 const invoke=async(...args)=>JSON.parse((await exec(process.execPath,[cli,...args],{windowsHide:true,timeout:65000})).stdout);
 const identity=await invoke('init-storage','--data-dir',data);
 const {currentStorageRevision}=await load(controller,'dist/storage-revision.mjs');
 assert.ok(currentStorageRevision>100);
 const migrated=await invoke('migrate-storage','--data-dir',data,'--to-revision',String(currentStorageRevision-1));
 assert.equal(migrated.schema_revision,String(currentStorageRevision-1));
 const current=await invoke('migrate-storage','--data-dir',data,'--to-revision','current');
 assert.equal(current.schema_revision,String(currentStorageRevision));
 assert.equal(current.steps.length,1);
 await invoke('init-process-host','--data-dir',data);
 const {openStorage}=await load(controller,'dist/storage.mjs');
 const login={login:'standalone.test',password:'Synthetic-standalone-login-123'};
 const initial=openStorage(data);
 let principal;
 try{
  assert.equal(initial.identity.service_id,identity.service_id);
  assert.equal(initial.identity.database_instance_id,identity.database_instance_id);
  const capability=initial.enrollment.begin();
  principal=await initial.enrollment.complete({...login,mode:'standalone',token_id:capability.token_id,secret:capability.secret});
 }finally{initial.close();}
 const siteConfig=file('site-config.json',JSON.stringify({site_label:'独立现场',service_id:identity.service_id,database_instance_id:identity.database_instance_id}));
 await exec(process.execPath,[path.join(gui,'scripts/build.mjs'),'--config',siteConfig,'--out-dir',assets],{cwd:gui,windowsHide:true,timeout:30000});
 const guiManifest=fs.readFileSync(path.join(assets,'gui-manifest.json')),pinned=digest(guiManifest),manifest=JSON.parse(guiManifest);
 const {installedCoreDigest}=await load(controller,'dist/process-host.mjs');
 const {openNativeClock}=await load(controller,'dist/native-clock.mjs');
 const {canonical,seal,ref}=await load(controller,'dist/auth-clock-value.mjs');
 const {fixture:clockFixture}=await load(controller,'test/auth-clock-fixture.mjs');
 const {peerCertificates}=await load(controller,'test/fixtures/peer-certificates.mjs');
 const {ca,leaves:[site]}=peerCertificates(),{publicKey,privateKey}=crypto.generateKeyPairSync('ed25519');
 const source=openNativeClock(),issued=clockFixture({service_id:identity.service_id,service_boot_id:crypto.randomUUID()}, {source},
  {sampleWindowPolicy:'authentication-clock-sample/2'}).evidence;
 const reservation=net.createServer();await new Promise((resolve,reject)=>reservation.once('error',reject).listen(0,'127.0.0.1',resolve));
 const port=reservation.address().port;await new Promise(resolve=>reservation.close(resolve));
 const origin='https://127.0.0.1:'+port,evidenceFile=path.join(root,'clock-evidence.json');
 const profile={format:'leafseamer.controller-standalone-profile/1',bootstrap:{format:'leafseamer-core-bootstrap-policy/1',
  service_id:identity.service_id,database_instance_id:identity.database_instance_id,
  artifact_manifest_ref:{manifest_id:'standalone-integration',revision:'1',digest:installedCoreDigest()},
  platform_profile_ref:{profile_id:'synthetic-windows-profile',revision:'1'},policy_revision:'1',bootstrap_timeout_ms:10000,clock_backend_revision:'1'},
  https:{origin,certificate_file:file('site.pem',site.cert),private_key_file:file('site-key.pem',site.key)},
  clock:{policy_digest:issued.policy.digest,evidence_file:evidenceFile,public_key_file:file('clock.pem',publicKey.export({type:'spki',format:'pem'}))},
  gui:{directory:assets,manifest_sha256:pinned}};
 const valid=file('standalone.json',canonical(profile)),invalid=file('manifest-drift.json',canonical({...profile,gui:{...profile.gui,manifest_sha256:digest('wrong')}}));
 await assert.rejects(invoke('supervise','--data-dir',data,'--port',String(port),'--standalone-profile',valid,'--pairing-profile',valid),
  error=>JSON.parse(error.stderr).error==='standalone_profile_conflict');
 async function boot(config,{invalidClock=false}={}){
  const child=spawn(process.execPath,[cli,'supervise','--data-dir',data,'--port',String(port),'--standalone-profile',config,'--stdin-control','pipe'],
   {stdio:['pipe','pipe','pipe'],windowsHide:true});
  child.stdin.on('error',()=>{});
  const frames=[],output=[];
  for(const [stream,records] of [[child.stderr,frames],[child.stdout,output]]){
   let pending='';stream.setEncoding('utf8').on('data',chunk=>{
    pending+=chunk;
    for(let at;(at=pending.indexOf('\n'))>=0;){const line=pending.slice(0,at);pending=pending.slice(at+1);
     try{records.push(JSON.parse(line));}catch{records.push({event:'unstructured_output'});}}
   });
  }
  const run={child,exit:once(child,'close'),frames,output};children.add(run);
  const challenge=await waitFor(()=>frames.find(frame=>frame.event==='authentication_clock_challenge'),()=>JSON.stringify(frames));
  assert.equal(challenge.database_instance_id,identity.database_instance_id);
  const {digest:oldRuntime,...runtimeBody}=issued.runtime,{digest:oldHealth,...healthBody}=issued.health;
  const expiry=String(BigInt(challenge.tick_ns)+90000000000n);
  const runtime=seal({...runtimeBody,id:crypto.randomUUID(),service_boot_id:challenge.service_boot_id,
   clock_domain_id:invalidClock?crypto.randomUUID():challenge.clock_domain_id,descriptor_digest:challenge.descriptor_digest,
   continuity:challenge.continuity,valid_before_tick_ns:expiry});
  const health=seal({...healthBody,id:crypto.randomUUID(),service_boot_id:challenge.service_boot_id,clock_domain_id:runtime.clock_domain_id,
   runtime_ref:ref(runtime),valid_before_tick_ns:expiry});
  const format='leafseamer.authentication-clock-evidence/1',evidence={policy:issued.policy,runtime,health};
  const signature=crypto.sign(null,Buffer.from(format+'\0'+canonical(evidence)),privateKey).toString('base64url');
  fs.renameSync(file('clock-next.json',canonical({format,evidence,signature})),evidenceFile);
  return run;
 }
 async function rejected(config,settings){
  const run=await boot(config,settings);assert.notEqual((await run.exit)[0],0);
  assert.equal(run.frames.some(value=>value.event==='listening'),false);
  assert.ok(run.output.some(value=>value.event==='process_group_empty'&&value.active_processes===0));
  children.delete(run);return run.frames;
 }
 assert.ok((await rejected(valid,{invalidClock:true})).some(frame=>frame.event==='authentication_clock_rejected'&&frame.reason==='pairing_clock_domain'));
 await rejected(invalid);
 const active=await boot(valid),first=await waitFor(()=>active.frames.find(frame=>frame.event==='listening'),()=>JSON.stringify(active.frames));
 assert.equal(first.pairing_origin,undefined);
 assert.equal(first.service_id,identity.service_id);
 assert.equal(first.database_instance_id,identity.database_instance_id);
 assert.equal(first.ready,false);
 assert.ok(active.output.some(value=>value.event==='process_contained'&&value.bootstrap_authenticated));
 for(const [name,hash] of Object.entries(manifest.artifacts)){
  const asset=await request(origin,ca,'/'+name);assert.equal(asset.status,200,name);assert.equal(digest(asset.body),'sha256:'+hash,name);
 }
 if(edge){
  assert.ok(path.isAbsolute(edge));
  const spki=crypto.createHash('sha256').update(new crypto.X509Certificate(site.cert).publicKey.export({type:'spki',format:'der'})).digest('base64');
  const {stdout}=await exec(edge,['--headless=new','--virtual-time-budget=4000','--disable-background-networking','--no-first-run','--disable-extensions','--lang=zh-CN',
   '--user-data-dir='+path.join(root,'edge'), '--ignore-certificate-errors-spki-list='+spki,'--dump-dom',origin],
   {windowsHide:true,timeout:25000});
  assert.match(stdout,/<h1[^>]*>登录工作台<\/h1>/);
 }
 assert.equal((await request(origin,ca,'/',{headers:{Origin:'https://other.invalid'}})).status,403);
 assert.equal((await request(origin,ca,'/internal/bindings')).status,404);
 assert.deepEqual(JSON.parse((await request(origin,ca,'/health/ready')).body),{ready:false,reason:'business_incomplete'});
 const headers={...contractHeaders(manifest.selection),Origin:origin,'Content-Type':'application/json'};
 async function verifySignIn(){
  const signIn=await request(origin,ca,'/auth/sessions',{method:'POST',headers,body:JSON.stringify(login)});
  assert.equal(signIn.status,201);
  assert.match(signIn.headers['set-cookie'][0],/Path=\/auth; Secure; HttpOnly; SameSite=Strict/);
  const token=await request(origin,ca,'/auth/service-tokens',{method:'POST',headers:{...headers,Cookie:signIn.headers['set-cookie'][0].split(';')[0],
   'X-CSRF-Token':signIn.headers['x-csrf-token']},body:JSON.stringify({audience:identity.service_id,requested_scopes:['session.read'],extension_instance_id:null})});
  assert.equal(token.status,201);
  const session=await request(origin,ca,'/api/v1/session',{headers:{...contractHeaders(manifest.selection),
   Authorization:'Bearer '+JSON.parse(token.body).data.access_token}});
  assert.equal(session.status,200);
  assert.equal(JSON.parse(session.body).data.principal_id,principal.principal_id);
 }
 await verifySignIn();
 assert.equal((await stop(active))[0],0);
 assert.ok(active.output.some(value=>value.event==='process_group_empty'&&value.stop_requested&&!value.forced));
 const restarted=await boot(valid),second=await waitFor(()=>restarted.frames.find(frame=>frame.event==='listening'),()=>JSON.stringify(restarted.frames));
 assert.notEqual(second.service_boot_id,first.service_boot_id);
 assert.equal(second.service_id,first.service_id);
 await verifySignIn();
 assert.equal((await stop(restarted))[0],0);
 assert.ok(restarted.output.some(value=>value.event==='process_group_empty'&&value.stop_requested&&!value.forced));
 assert.deepEqual(exitedGroups(),[0,0,0,0]);
});
