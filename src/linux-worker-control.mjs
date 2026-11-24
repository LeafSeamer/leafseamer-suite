import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import Database from 'better-sqlite3';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {decodeWorkerControl,decodeWorkerIntent,workerControlVersion} from './sdk/worker-runtime.mjs';

const maximum=262144,windowNs=2000000000n;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$(?![\s\S])/;
const same=(a,b)=>canonical(a)===canonical(b);
const namespace=()=>{const value=fs.statSync('/proc/self/ns/time',{bigint:true});return `linux_${value.dev}_${value.ino}`;};
const identity=stat=>`${stat.dev}:${stat.ino}`;
const requests=new Set(['LAUNCH_QUERY','FENCE_PUT','LAUNCH_REGISTER','LAUNCH_CREATE','LAUNCH_MATERIALIZE','LAUNCH_LOAD','RETIRE_REQUEST']);
const schema=`
  CREATE TABLE identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1),body TEXT NOT NULL) STRICT;
  CREATE TABLE fence(revision INTEGER PRIMARY KEY CHECK(revision BETWEEN 1 AND 4096),body TEXT NOT NULL,digest TEXT NOT NULL) STRICT;
  CREATE TABLE denied(launch_id TEXT PRIMARY KEY,revision INTEGER NOT NULL REFERENCES fence(revision)) STRICT;
  CREATE TABLE registration(launch_id TEXT PRIMARY KEY,intent_digest TEXT NOT NULL,member_id TEXT NOT NULL UNIQUE,
    group_id TEXT NOT NULL UNIQUE,body TEXT NOT NULL,authorization TEXT NOT NULL) STRICT;
  CREATE TABLE attempt(launch_id TEXT PRIMARY KEY REFERENCES registration(launch_id),revision INTEGER NOT NULL REFERENCES fence(revision),
    materialization_id TEXT NOT NULL UNIQUE,body TEXT NOT NULL) STRICT;
  CREATE TABLE admission(launch_id TEXT PRIMARY KEY REFERENCES attempt(launch_id),body TEXT NOT NULL,digest TEXT NOT NULL) STRICT;
  CREATE TABLE retirement(launch_id TEXT PRIMARY KEY REFERENCES attempt(launch_id),body TEXT NOT NULL,digest TEXT NOT NULL,observation TEXT NOT NULL) STRICT;
`+['identity','fence','denied','registration','attempt','admission','retirement'].flatMap(table=>['UPDATE','DELETE'].map(operation=>
  `CREATE TRIGGER ${table}_${operation.toLowerCase()} BEFORE ${operation} ON ${table} BEGIN SELECT RAISE(ABORT,'worker_control_immutable'); END;`)).join('\n');

class RequestDenied extends Error{constructor(code){super(code);this.code=code;}}
function permit(ok,code){if(!ok)throw new RequestDenied(code);}

// 通道由同一次原生创建继承；每个核心准入只创建一次独立的追加账本。
export function bindLinuxWorkerControl({directory,socket,core,source,assertLive,checkGroup,acquire,launch}){
  const {intent:parent,descriptor,receipt,policy}=core;
  need(parent.role==='core'&&receipt.role==='core'&&receipt.gate_state==='closed'&&uuid.test(parent.launch_id)&&
    descriptor.clock_backend_id==='linux_boottime'&&descriptor.namespace_identity===namespace(),'linux_worker_control_scope');
  const scope={service_id:policy.service_id,database_instance_id:policy.database_instance_id,
    supervisor_instance_id:descriptor.supervisor_instance_id,domain_ref:receipt.domain_ref};
  const channelId=receipt.channel_binding_id.replaceAll('-','');
  const owner=fs.lstatSync(directory,{bigint:true});
  need(fs.realpathSync.native(directory)===directory&&owner.isDirectory()&&owner.uid===BigInt(process.geteuid())&&(owner.mode&0o077n)===0n,
    'linux_worker_control_directory');
  const filename=path.join(directory,'linux-worker-control-'+parent.launch_id+'.db');
  const fd=fs.openSync(filename,fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_WRONLY|fs.constants.O_NOFOLLOW,0o600);
  const fileIdentity=identity(fs.fstatSync(fd,{bigint:true}));fs.closeSync(fd);
  let db;
  try{
    db=new Database(filename,{fileMustExist:true,timeout:0});
    db.exec('PRAGMA journal_mode=DELETE;PRAGMA synchronous=EXTRA;PRAGMA locking_mode=EXCLUSIVE;PRAGMA foreign_keys=ON;PRAGMA trusted_schema=OFF;');
    const pragma=name=>db.prepare('PRAGMA '+name).raw().get()[0];
    need(pragma('journal_mode')==='delete'&&pragma('synchronous')===3&&pragma('locking_mode')==='exclusive'&&
      pragma('foreign_keys')===1&&pragma('trusted_schema')===0,'linux_worker_control_database');
    db.transaction(()=>{
      db.exec(schema);
      db.prepare('INSERT INTO identity VALUES(1,?)').run(canonical({format:'leafseamer.linux-worker-control/1',scope,core_receipt:receipt}));
    }).exclusive();
    const directoryFd=fs.openSync(directory,'r');try{fs.fsyncSync(directoryFd);}finally{fs.closeSync(directoryFd);}
  }catch(error){db?.close();throw error;}

  let buffer=Buffer.alloc(0),busy=false,closed=false,sequence=1n,lastTick=null;
  const staged=new Map(),workers=new Map();
  const coreKey={launch_id:receipt.launch_id,launch_intent_digest:receipt.launch_intent_digest};
  function live(){
    need(!closed&&!socket.destroyed&&identity(fs.lstatSync(directory,{bigint:true}))===identity(owner)&&
      identity(fs.lstatSync(filename,{bigint:true}))===fileIdentity&&descriptor.namespace_identity===namespace(),'linux_worker_control_lost');
    assertLive();
  }
  function now(){
    const tick=source.tick();
    need(typeof tick==='bigint'&&tick>=0n&&tick<=18446744073709551615n&&(lastTick===null||tick>=lastTick),'linux_worker_control_clock');
    lastTick=tick;return tick;
  }
  function currentFence(){
    const row=db.prepare('SELECT revision,body,digest FROM fence ORDER BY revision DESC LIMIT 1').raw().get();
    if(!row)return null;
    const [revision,text,checksum]=row,body=JSON.parse(text);
    need(canonical(body)===text&&digest(body)===checksum&&String(revision)===body.revision&&same(body.scope,scope),'linux_worker_control_journal');
    return body;
  }
  const denied=db.prepare('SELECT 1 FROM denied WHERE launch_id=?').pluck();
  async function fence(snapshot){
    const {digest:fenceDigest,...body}=snapshot,revision=BigInt(body.revision);
    permit(same(body.scope,scope)&&digest(body)===fenceDigest&&body.items.every((item,index)=>item.launch_id!==coreKey.launch_id&&
      (index===0||body.items[index-1].launch_id<item.launch_id)),'invalid_binding');
    permit(revision>0n&&revision<=4096n,'capacity');
    const previous=currentFence();
    if(previous){
      permit(revision>=BigInt(previous.revision),'stale_fence');
      if(body.revision===previous.revision){permit(same(body,previous),'identity_conflict');return;}
    }
    const items=new Map(body.items.map(item=>[item.launch_id,item]));
    for(const [launchId,checksum] of db.prepare('SELECT launch_id,intent_digest FROM registration').raw().all()){
      const item=items.get(launchId);
      permit(denied.get(launchId)||item,'invalid_binding');
      permit(!item||item.launch_intent_digest===checksum,'identity_conflict');
    }
    db.transaction(()=>{
      db.prepare('INSERT INTO fence VALUES(?,?,?)').run(Number(revision),canonical(body),fenceDigest);
      for(const item of body.items){
        if(item.disposition==='allow')permit(!denied.get(item.launch_id),'unauthorized');
        else db.prepare('INSERT OR IGNORE INTO denied VALUES(?,?)').run(item.launch_id,Number(revision));
      }
    }).immediate();
    for(const item of body.items)if(item.disposition==='deny'){
      await dropStage(item.launch_id);
      if(workers.has(item.launch_id))await retire(item);
    }
  }
  function registered(key){
    const row=db.prepare('SELECT intent_digest,body FROM registration WHERE launch_id=?').raw().get(key.launch_id);
    if(!row)return null;
    const [checksum,text]=row,intent=JSON.parse(text);
    need(canonical(intent)===text&&digest(intent)===checksum,'linux_worker_control_journal');
    permit(checksum===key.launch_intent_digest,'identity_conflict');return intent;
  }
  const attempted=id=>!!db.prepare('SELECT 1 FROM attempt WHERE launch_id=?').pluck().get(id);
  function historical(table,id){
    const row=db.prepare('SELECT body,digest FROM '+table+' WHERE launch_id=?').raw().get(id);
    if(!row)return null;
    const original=JSON.parse(row[0]);need(canonical(original)===row[0]&&digest(original)===row[1],'linux_worker_control_journal');return original;
  }
  function view(key){
    let admission=null,state='registered',creation=false,evidence=null;
    if(key.launch_id===coreKey.launch_id){permit(same(key,coreKey),'identity_conflict');admission=receipt;state='admitted_closed';creation=true;}
    else{
      if(!registered(key))return null;
      const id=key.launch_id,worker=workers.get(id);
      admission=historical('admission',id);evidence=historical('retirement',id);creation=attempted(id);
      if(evidence)state='retired';
      else if(creation){
        try{need(worker&&admission&&!denied.get(id),'linux_worker_unavailable');worker.assertCurrent();state='admitted_closed';}
        catch{state='indeterminate';}
      }else if(denied.get(id))state='rejected';
    }
    return {key,supervisor_instance_id:scope.supervisor_instance_id,state,creation_attempted:creation,
      admission_receipt:admission,retirement_evidence:evidence,gate_state:'closed'};
  }
  function allow(key){
    const current=currentFence(),item=current?.items.find(entry=>entry.launch_id===key.launch_id);
    permit(item?.disposition==='allow'&&item.launch_intent_digest===key.launch_intent_digest&&!denied.get(key.launch_id),'unauthorized');
    return current;
  }
  function authorize(intent,key,authorization){
    const binding=intent.extension_binding,{authorization_ref:ref,lifetime,...body}=authorization;
    permit(ref.kind==='launch_authorization'&&ref.authority_service_id===scope.service_id&&ref.database_instance_id===scope.database_instance_id&&
      ref.revision==='1'&&ref.digest===digest({...body,lifetime})&&body.launch_id===key.launch_id&&body.launch_intent_digest===key.launch_intent_digest&&
      body.supervisor_instance_id===scope.supervisor_instance_id&&same(lifetime.clock,scope.domain_ref)&&
      ['installation_ref','approval_ref','role_resolution_ref','permissions_digest'].every(field=>same(body[field],binding[field])),'invalid_binding');
    const issued=BigInt(lifetime.issued_tick),deadline=BigInt(lifetime.deadline_tick),tick=now();
    permit(tick>=issued&&tick<deadline&&deadline-issued<=windowNs,'expired');
    permit(allow(key).revision===body.fence_revision,'stale_fence');
    return deadline;
  }
  async function register({intent:input,authorization}){
    const intent=await decodeWorkerIntent(Buffer.from(canonical(input)),{authority:'controller',...scope});
    live();
    const key={launch_id:intent.launch_id,launch_intent_digest:digest(intent)},binding=intent.extension_binding;
    permit(uuid.test(key.launch_id)&&key.launch_id!==coreKey.launch_id&&intent.member_id!==parent.member_id&&
      intent.supervisor_instance_id===scope.supervisor_instance_id&&intent.runtime_generation===descriptor.runtime_generation&&
      intent.policy_revision===parent.policy_revision&&same(intent.artifact_manifest_ref,parent.artifact_manifest_ref)&&
      intent.containment_ref.backend==='linux_cgroup_v2'&&intent.containment_ref.generation===descriptor.runtime_generation&&
      intent.containment_ref.group_id!==parent.containment_ref.group_id&&binding.platform_profile_ref.object_id===descriptor.platform_profile_id&&
      binding.platform_profile_ref.revision===descriptor.platform_profile_revision,'invalid_binding');
    const deadline=authorize(intent,key,authorization);
    permit(!attempted(key.launch_id)&&checkGroup(intent),'invalid_binding');
    const original=view(key);
    if(original)return {key,record:original};
    permit(db.prepare('SELECT count(*) FROM registration').pluck().get()<256,'capacity');
    permit(!db.prepare('SELECT 1 FROM registration WHERE member_id=? OR group_id=?').pluck().get(intent.member_id,intent.containment_ref.group_id),'identity_conflict');
    permit(now()<deadline,'expired');
    db.transaction(()=>db.prepare('INSERT INTO registration VALUES(?,?,?,?,?,?)').run(key.launch_id,key.launch_intent_digest,intent.member_id,
      intent.containment_ref.group_id,canonical(intent),canonical(authorization))).immediate();
    return {key,record:view(key)};
  }
  async function dropStage(id){
    const entry=staged.get(id);staged.delete(id);await entry?.held?.discard();
  }
  async function materialize({key,observation_request_id}){
    permit(acquire&&launch,'unauthorized');
    const intent=registered(key);permit(intent&&!attempted(key.launch_id),'invalid_binding');allow(key);
    const id=key.launch_id;
    let entry=staged.get(id);
    if(entry)permit(entry.challenge===observation_request_id,'identity_conflict');
    else{
      permit(staged.size<4&&workers.size<4,'capacity');
      entry={challenge:observation_request_id,id:crypto.randomUUID(),held:null,failed:false};staged.set(id,entry);
      try{
        const held=await acquire(intent,entry.challenge);
        if(held.status!=='available')entry.failed=true;
        else if(closed||staged.get(id)!==entry){await held.discard();entry.failed=true;}
        else{
          entry.held=held;
          void held.closed.then(()=>{if(staged.get(id)===entry)return dropStage(id);}).catch(()=>stop());
        }
      }catch{entry.failed=true;}
    }
    if(entry.failed){await dropStage(id);return {key,observation_request_id,status:'unavailable',observation:null};}
    entry.held.assertCurrent();
    const life=entry.held.content.lifetime;
    return {key,observation_request_id,status:'verified',observation:{materialization_evidence_id:entry.id,
      materialization_challenge_id:entry.challenge,lifetime:{clock:scope.domain_ref,issued_tick:life.issued_tick,deadline_tick:life.deadline_tick}}};
  }
  async function create({key,authorization,materialization_evidence_id,materialization_challenge_id,load_id}){
    const id=key.launch_id,intent=registered(key),entry=staged.get(id);
    permit(launch&&intent&&!attempted(id)&&entry?.held&&entry.id===load_id&&entry.id===materialization_evidence_id&&
      entry.challenge===materialization_challenge_id,'unauthorized');
    permit(workers.size<4,'capacity');
    const deadline=authorize(intent,key,authorization),group=checkGroup(intent);
    permit(group,'invalid_binding');
    entry.held.assertCurrent();live();
    function assertCreate(){live();permit(now()<deadline,'expired');permit(allow(key).revision===authorization.fence_revision,'stale_fence');entry.held.assertCurrent();}
    assertCreate();
    db.transaction(()=>db.prepare('INSERT INTO attempt VALUES(?,?,?,?)').run(id,Number(authorization.fence_revision),entry.id,
      canonical({key,authorization,group,materialization_challenge_id,load_id}))).immediate();
    staged.delete(id);
    try{
      const worker=await launch(intent,group,entry.held,assertCreate,admitted=>{
        live();allow(key);
        db.transaction(()=>db.prepare('INSERT INTO admission VALUES(?,?,?)').run(id,canonical(admitted),digest(admitted))).immediate();
      });
      if(closed){await worker.retire();throw new RequestDenied('indeterminate');}
      workers.set(id,worker);
    }catch{await entry.held.close();throw new RequestDenied('indeterminate');}
    return {key,record:view(key)};
  }
  async function retire(key,containment=null){
    const intent=registered(key),id=key.launch_id;
    permit(intent&&(!containment||same(containment,intent.containment_ref)),'invalid_binding');
    const original=historical('retirement',id);if(original)return original;
    const worker=workers.get(id);permit(worker,'indeterminate');
    const observed=await worker.retire();live();
    const evidence={evidence_id:crypto.randomUUID(),service_id:scope.service_id,old_domain_ref:scope.domain_ref,
      evaluator_domain_ref:scope.domain_ref,target_scope:'member_group',target_member_ids:[intent.member_id],containment_ref:intent.containment_ref,
      launch_intake_closed:true,os_observation_refs:['observation_'+digest(observed).slice(7)],result:'confirmed_empty',observed_tick_ns:String(now())};
    db.transaction(()=>db.prepare('INSERT INTO retirement VALUES(?,?,?,?)').run(id,canonical(evidence),digest(evidence),canonical(observed))).immediate();
    workers.delete(id);return evidence;
  }
  async function handle(bytes){
    const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes),input=JSON.parse(text);
    need(requests.has(input.type)&&text===canonical(input),'linux_worker_control_frame');
    const frame=await decodeWorkerControl(bytes,input.type);
    live();
    need(frame.channel_id===channelId&&same(frame.scope,scope)&&frame.sequence===String(sequence)&&frame.reply_to===null,'linux_worker_control_frame');
    let type,payload;
    try{
      if(frame.type==='LAUNCH_QUERY'){type='LAUNCH_RESULT';payload={key:frame.payload,record:view(frame.payload)};}
      else if(frame.type==='FENCE_PUT'){
        await fence(frame.payload);type='FENCE_RESULT';payload={revision:frame.payload.revision,snapshot_digest:frame.payload.digest,journal_committed:true};
      }else if(frame.type==='LAUNCH_REGISTER'){type='LAUNCH_RESULT';payload=await register(frame.payload);}
      else if(frame.type==='LAUNCH_MATERIALIZE'){type='MATERIALIZATION_RESULT';payload=await materialize(frame.payload);}
      else if(frame.type==='LAUNCH_CREATE'){type='LAUNCH_RESULT';payload=await create(frame.payload);}
      else if(frame.type==='RETIRE_REQUEST'){type='RETIRE_RESULT';payload=await retire(frame.payload.key,frame.payload.containment_ref);}
      else throw new RequestDenied('unauthorized');
    }catch(error){
      if(!(error instanceof RequestDenied))throw error;
      type='ERROR';payload={code:error.code,retry_action:'query_only'};
    }
    live();const response=Buffer.from(canonical({version:workerControlVersion,type,scope,channel_id:channelId,sequence:String(sequence),
      message_id:crypto.randomUUID(),reply_to:frame.message_id,payload}));
    await decodeWorkerControl(response,type);live();
    sequence++;busy=false;socket.write(Buffer.concat([response,Buffer.from('\n')]),error=>{if(error)stop();});
  }
  function stop(){
    if(closed)return;closed=true;socket.destroy();db.close();
    for(const id of staged.keys())void dropStage(id).catch(()=>{});
    for(const worker of workers.values())void worker.retire().catch(()=>{});
  }
  socket.once('end',stop).once('close',stop).once('error',stop);
  socket.on('data',chunk=>{
    if(closed)return;
    if(busy||buffer.length+chunk.length>maximum+1){stop();return;}
    buffer=Buffer.concat([buffer,chunk]);const end=buffer.indexOf(10);
    if(end<0)return;
    if(end===0||end!==buffer.length-1){stop();return;}
    const bytes=buffer.subarray(0,end);buffer=Buffer.alloc(0);busy=true;
    void handle(bytes).catch(stop);
  });
}
