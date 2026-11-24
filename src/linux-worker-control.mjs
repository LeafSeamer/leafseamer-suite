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
`+['identity','fence','denied','registration'].flatMap(table=>['UPDATE','DELETE'].map(operation=>
  `CREATE TRIGGER ${table}_${operation.toLowerCase()} BEFORE ${operation} ON ${table} BEGIN SELECT RAISE(ABORT,'worker_control_immutable'); END;`)).join('\n');

class RequestDenied extends Error{constructor(code){super(code);this.code=code;}}
function permit(ok,code){if(!ok)throw new RequestDenied(code);}

// 通道由同一次原生创建继承；每个核心准入只创建一次独立的追加账本。
export function bindLinuxWorkerControl({directory,socket,core,source,assertLive,checkGroup}){
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
  function fence(snapshot){
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
  }
  function view(key){
    let admission=null,state='registered';
    if(key.launch_id===coreKey.launch_id){permit(same(key,coreKey),'identity_conflict');admission=receipt;state='admitted_closed';}
    else{
      const row=db.prepare('SELECT intent_digest,body FROM registration WHERE launch_id=?').raw().get(key.launch_id);
      if(!row)return null;
      const [checksum,text]=row,intent=JSON.parse(text);
      need(canonical(intent)===text&&digest(intent)===checksum,'linux_worker_control_journal');
      permit(checksum===key.launch_intent_digest,'identity_conflict');
      if(denied.get(key.launch_id))state='rejected';
    }
    return {key,supervisor_instance_id:scope.supervisor_instance_id,state,creation_attempted:admission!==null,
      admission_receipt:admission,retirement_evidence:null,gate_state:'closed'};
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
    const {authorization_ref:ref,lifetime,...body}=authorization;
    permit(ref.kind==='launch_authorization'&&ref.authority_service_id===scope.service_id&&ref.database_instance_id===scope.database_instance_id&&
      ref.revision==='1'&&ref.digest===digest({...body,lifetime})&&body.launch_id===key.launch_id&&body.launch_intent_digest===key.launch_intent_digest&&
      body.supervisor_instance_id===scope.supervisor_instance_id&&same(lifetime.clock,scope.domain_ref)&&
      ['installation_ref','approval_ref','role_resolution_ref','permissions_digest'].every(field=>same(body[field],binding[field])),'invalid_binding');
    const issued=BigInt(lifetime.issued_tick),deadline=BigInt(lifetime.deadline_tick),tick=now();
    permit(tick>=issued&&tick<deadline&&deadline-issued<=windowNs,'expired');
    const current=currentFence(),item=current?.items.find(entry=>entry.launch_id===key.launch_id);
    permit(current?.revision===body.fence_revision,'stale_fence');
    permit(item?.disposition==='allow'&&item.launch_intent_digest===key.launch_intent_digest&&!denied.get(key.launch_id),'unauthorized');
    permit(checkGroup(intent),'invalid_binding');
    const original=view(key);
    if(original)return {key,record:original};
    permit(db.prepare('SELECT count(*) FROM registration').pluck().get()<256,'capacity');
    permit(!db.prepare('SELECT 1 FROM registration WHERE member_id=? OR group_id=?').pluck().get(intent.member_id,intent.containment_ref.group_id),'identity_conflict');
    permit(now()<deadline,'expired');
    db.transaction(()=>db.prepare('INSERT INTO registration VALUES(?,?,?,?,?,?)').run(key.launch_id,key.launch_intent_digest,intent.member_id,
      intent.containment_ref.group_id,canonical(intent),canonical(authorization))).immediate();
    return {key,record:view(key)};
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
        fence(frame.payload);type='FENCE_RESULT';payload={revision:frame.payload.revision,snapshot_digest:frame.payload.digest,journal_committed:true};
      }else if(frame.type==='LAUNCH_REGISTER'){type='LAUNCH_RESULT';payload=await register(frame.payload);}
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
  function stop(){if(!closed){closed=true;socket.destroy();db.close();}}
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
