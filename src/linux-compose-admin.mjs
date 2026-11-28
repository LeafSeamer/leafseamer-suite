#!/usr/bin/env node
import {parseArgs} from 'node:util';
import {setTimeout as delay} from 'node:timers/promises';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {once} from 'node:events';
import {openInstallationStore} from './installation-store.mjs';
import {openLinuxComposeHost} from './linux-compose-host.mjs';
import {requireValue as need} from './import-input.mjs';

const usage=`Usage:
  leafseamer-compose status --installation DIR
  leafseamer-compose run --installation DIR --plan FILE --generation DIR --controller-dist DIR
  leafseamer-compose retire --installation DIR --plan FILE --generation DIR
Run and retire accept --docker-socket FILE and --docker-pid-file FILE.
`;
const emit=value=>process.stdout.write(JSON.stringify(value)+'\n');
function view(record){
  if(!record)return {generation_id:null,phase:'empty'};
  return {generation_id:record.intent.generation_id,phase:record.phase,revision:record.revision,
    ...(record.detail.reason&&{reason:record.detail.reason})};
}

function query(directory){
  const installation=openInstallationStore(directory);
  try{
    const disabled=()=>{throw new Error('compose_admin_read_only');};
    const journal=installation.openLinuxDeploymentJournal({launch:disabled,endpointClosure:disabled});
    try{return journal.current();}finally{journal.close();}
  }finally{installation.close();}
}

function statusEndpoint(directory){
  need(directory!=='/'&&path.posix.normalize(directory)===directory&&!directory.endsWith('/')&&
    fs.realpathSync.native(directory)===directory,'compose_admin_directory');
  for(let current=directory;current!=='/';current=path.dirname(current)){
    const info=fs.lstatSync(current);
    const sticky=current!==directory&&(info.mode&0o1000)!==0;
    need(info.isDirectory()&&info.uid===0&&(current===directory?(info.mode&0o077)===0:(info.mode&0o022)===0||sticky),
      'compose_admin_directory');
  }
  const endpoint=path.join(directory,'compose-status.sock');
  need(Buffer.byteLength(endpoint)<108,'compose_admin_status_path');
  return endpoint;
}

function statusSocket(endpoint){
  const info=fs.lstatSync(endpoint,{throwIfNoEntry:false});
  if(!info)return false;
  need(info.isSocket()&&info.uid===0&&(info.mode&0o077)===0,'compose_admin_status_socket');
  return true;
}

async function readLiveStatus(endpoint){
  if(!statusSocket(endpoint))return null;
  const client=net.createConnection({path:endpoint});
  client.setTimeout(1500,()=>client.destroy(Object.assign(new Error('status timeout'),{code:'compose_admin_status_timeout'})));
  try{
    let json='';
    for await(const bytes of client){
      json+=bytes.toString('utf8');
      need(json.length<=1024,'compose_admin_status');
    }
    return JSON.parse(json);
  }catch(error){
    if(['ECONNREFUSED','ENOENT'].includes(error?.code))return null;
    throw error;
  }finally{client.destroy();}
}

async function serveStatus(endpoint,host){
  // The caller already holds the exclusive installation writer.
  if(statusSocket(endpoint))fs.unlinkSync(endpoint);
  const server=net.createServer(socket=>{
    socket.on('error',()=>socket.destroy());
    socket.setTimeout(1000,()=>socket.destroy());
    try{socket.end(JSON.stringify(view(host.current()))+'\n');}
    catch{socket.destroy();}
  });
  server.maxConnections=4;
  const listening=once(server,'listening');
  server.listen(endpoint);
  await listening;
  const close=()=>new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));
  try{fs.chmodSync(endpoint,0o600);}catch(error){await close();throw error;}
  return close;
}

function startedView(started){
  const {containers}=started.record.detail.runtime_binding;
  const members=Object.fromEntries(Object.entries(started.admissions).map(([role,value])=>[role,{
    container_id:containers[role],member_boot_id:value.receipt.member_boot_id,
    clock_domain_id:value.descriptor.clock_domain_id,descriptor_digest:value.descriptor.descriptor_digest
  }]));
  return {...view(started.record),event:'started',members};
}

async function retire(host){
  const deadline=performance.now()+10000;
  let record=host.retire();
  while(record.phase==='closing'&&performance.now()<deadline){
    await delay(100);
    record=host.retire();
  }
  return record;
}

async function supervise(host){
  const stopping=Promise.withResolvers();
  const interrupt=()=>stopping.resolve('interrupt');
  const terminate=()=>stopping.resolve('terminate');
  process.on('SIGINT',interrupt);
  process.on('SIGTERM',terminate);
  try{
    let started;
    try{started=await host.startSupervised();}
    catch(error){
      const record=host.current();
      if(host.startedHere()&&record?.intent.generation_id===host.generationId&&['running','closing'].includes(record.phase)){
        emit({...view(await retire(host)),event:'stopped',cause:'startup_failed'});
      }
      throw error;
    }
    emit(startedView(started));
    const cause=await Promise.race([stopping.promise,host.channelLost.then(()=>'channel_lost')]);
    const result=await retire(host);
    emit({...view(result),event:'stopped',cause});
    return result.phase==='retired'&&cause!=='channel_lost'?0:1;
  }finally{
    process.off('SIGINT',interrupt);
    process.off('SIGTERM',terminate);
  }
}

async function main(args){
  if(args.length===1&&args[0]==='--help'){process.stdout.write(usage);return 0;}
  const [action,...options]=args;
  need(process.platform==='linux'&&process.geteuid()===0,'compose_admin_platform');
  need(['status','run','retire'].includes(action),'compose_admin_arguments');
  const keys=action==='status'?['installation']:['installation','plan','generation','docker-socket','docker-pid-file',
    ...(action==='run'?['controller-dist']:[])];
  let parsed;
  try{
    parsed=parseArgs({args:options,options:Object.fromEntries(keys.map(name=>[name,{type:'string'}])),tokens:true});
  }catch{
    need(false,'compose_admin_arguments');
  }
  const {values,tokens}=parsed;
  need(tokens.every(token=>token.kind==='option')&&new Set(tokens.map(token=>token.name)).size===tokens.length&&
    Object.values(values).every(value=>value?.startsWith('/')),
    'compose_admin_arguments');
  const {installation:installationDirectory,plan:planFile,generation:generationDirectory}=values;
  need(installationDirectory,'compose_admin_arguments');
  const endpoint=statusEndpoint(installationDirectory);
  if(action==='status'){emit(await readLiveStatus(endpoint)??view(query(installationDirectory)));return 0;}
  need(planFile&&generationDirectory&&(action!=='run'||values['controller-dist']),'compose_admin_arguments');
  const host=openLinuxComposeHost({installationDirectory,planFile,generationDirectory,
    socketPath:values['docker-socket'],pidFile:values['docker-pid-file'],clockDirectory:values['controller-dist']??null});
  try{
    if(action==='run'){
      const closeStatus=await serveStatus(endpoint,host);
      try{return await supervise(host);}finally{await closeStatus();}
    }
    const record=await retire(host);
    emit(view(record));
    return record.phase==='retired'?0:1;
  }finally{await host.close();}
}

try{process.exitCode=await main(process.argv.slice(2));}
catch(error){
  const code=value=>/^(?:compose|linux|ingress|native|clock|cgroup|installation)_[a-z_]+$/.test(value??'')?value:null;
  process.stderr.write(JSON.stringify({error:code(error?.code)??'compose_admin_failed',
    ...(code(error?.cause?.code)&&{cause:code(error.cause.code)})})+'\n');
  process.exitCode=1;
}
