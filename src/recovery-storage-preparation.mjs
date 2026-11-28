import fs from 'node:fs/promises';
import {constants,createReadStream} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {Worker,isMainThread,parentPort,workerData} from 'node:worker_threads';
import {canonical,InstallationError,requireValue as need} from './import-input.mjs';
import {loadVerifiedDistributionModule} from './backup-domain-verification.mjs';
import {installationContentPlatform} from './local-peer.mjs';

const same=(a,b)=>canonical(a)===canonical(b);
const hash=/^[0-9a-f]{64}(?![\s\S])/;
const identity=stat=>`${stat.dev}:${stat.ino}`;
const readFlags=constants.O_RDONLY|(constants.O_NOFOLLOW??0);
const checkTime=deadline=>need(performance.now()<deadline,'backup_archive_deadline');
const filename=authority=>authority+'.sqlite';

export async function verifyProtectedRecoveryFiles(root,report,deadline){
  const rootStat=await fs.lstat(root,{bigint:true});
  need(rootStat.isDirectory()&&identity(rootStat)===report.root_identity,'recovery_preparation_files');
  const entries=await fs.readdir(root);
  need(entries.length===report.services.length,'recovery_preparation_files');
  for(const [index,service] of report.services.entries()){
    need(service.directory_name==='db-'+index,'recovery_preparation_files');
    const directory=path.join(root,service.directory_name),name=filename(service.next_scope.authority);
    const dirStat=await fs.lstat(directory,{bigint:true});
    const contents=await fs.readdir(directory);
    need(dirStat.isDirectory()&&identity(dirStat)===service.directory_identity&&contents.length===1&&contents[0]===name,
      'recovery_preparation_files');
    const file=path.join(directory,name),before=await fs.lstat(file,{bigint:true});
    const matches=stat=>stat.isFile()&&stat.nlink===1n&&stat.size===BigInt(service.bytes)&&
      ['dev','ino','mtimeNs','ctimeNs'].every(key=>before[key]===stat[key]);
    need(matches(before),'recovery_preparation_files');
    const handle=await fs.open(file,readFlags),checksum=createHash('sha256');
    try{
      need(matches(await handle.stat({bigint:true})),'recovery_preparation_files');
      for await(const chunk of createReadStream(file,{fd:handle.fd,autoClose:false})){checkTime(deadline);checksum.update(chunk);}
      need(checksum.digest('hex')===service.sha256&&matches(await handle.stat({bigint:true}))&&
        matches(await fs.lstat(file,{bigint:true}))&&identity(await fs.lstat(directory,{bigint:true}))===service.directory_identity,
      'recovery_preparation_files');
    }finally{await handle.close();}
  }
  need(identity(await fs.lstat(root,{bigint:true}))===report.root_identity,'recovery_preparation_files');
}

async function flushDirectory(directory){
  const handle=await fs.open(directory,readFlags|constants.O_DIRECTORY);
  try{await handle.sync();}finally{await handle.close();}
}

async function prepare({parent,attempt_id,plan_digest,inputs,distributions,deadline}){
  const win=process.platform==='win32';
  const readers=new Map();
  for(const [authority,distribution] of Object.entries(distributions)){
    const {prepareProtectedRecoveryStorage:convert}=await loadVerifiedDistributionModule(distribution,authority,'storage.mjs','recovery_preparation_distribution');
    need(typeof convert==='function','recovery_preparation_distribution');
    readers.set(authority,convert);
  }
  const space=await fs.statfs(parent,{bigint:true});
  const bytes=inputs.reduce((total,{receipt})=>total+BigInt(receipt.bytes),0n);
  need(space.bavail*space.bsize>=bytes*2n+2n*1024n**3n,'recovery_preparation_space');
  const native=win?installationContentPlatform():null;
  const root=path.join(parent,attempt_id),services=[];
  let pin;
  try{
    if(win)pin=native.prepareRoot(parent,attempt_id,[]);
    else await fs.mkdir(root,{mode:0o700});
    const root_identity=identity(await fs.lstat(root,{bigint:true}));
    const platform_root_identity=win?native.preparedDescribe(pin).root_identity:root_identity;
    for(const [index,{next_scope,receipt,sourceFile,data_generation_id}] of inputs.entries()){
      checkTime(deadline);
      const authority=next_scope.authority,directory_name='db-'+index,directory=path.join(root,directory_name);
      await fs.mkdir(directory,{mode:0o700});
      if(win)native.protectObject(pin,directory_name,true,true);
      const converted=await readers.get(authority)({sourceFile,receipt,targetDirectory:directory,nextScope:next_scope,
        planDigest:plan_digest,dataGenerationId:data_generation_id});
      const origin={format:'leafseamer.'+authority+'-recovery-origin/1',plan_digest,data_generation_id,
        snapshot_receipt_id:receipt.backup_operation_id,snapshot_sha256:receipt.sha256};
      need(converted?.format==='leafseamer.'+authority+'-protected-recovery-storage/1'&&
        same(converted.origin,origin)&&same(converted.next_scope,next_scope)&&Number.isSafeInteger(converted.bytes)&&
        converted.bytes>0&&converted.bytes<=32*1024**3&&typeof converted.sha256==='string'&&hash.test(converted.sha256)&&
        converted.history_retained_in_source===true,'recovery_preparation_receipt');
      if(win){
        const relative=directory_name+'/'+filename(authority);
        native.protectObject(pin,relative,false,true);
        native.flushPreparedObject(pin,relative,false);
        native.flushPreparedObject(pin,directory_name,true);
      }else await flushDirectory(directory);
      services.push({...converted,directory_name,directory_identity:identity(await fs.lstat(directory,{bigint:true}))});
    }
    if(win){native.flushPreparedObject(pin,'.',true);native.flushPreparedParent(pin);}
    else{await flushDirectory(root);await flushDirectory(parent);}
    return {root_identity,platform_root_identity,services,flush_method:win?'FlushFileBuffers':'fsync'};
  }finally{if(pin)native.preparedClose(pin);}
}

export function prepareRecoveryFiles(input,deadline){
  checkTime(deadline);
  return new Promise((resolve,reject)=>{
    const worker=new Worker(new URL(import.meta.url),{workerData:{format:'leafseamer-recovery-preparation-worker/1',...input,deadline}});
    let response,failure;
    const timer=setTimeout(()=>{failure=new InstallationError('backup_archive_deadline');void worker.terminate();},Math.max(1,deadline-performance.now()));
    worker.once('message',message=>{response=message;});
    worker.once('error',()=>{failure??=new InstallationError('recovery_preparation_worker');});
    worker.once('exit',code=>{
      clearTimeout(timer);
      if(failure||code!==0||!response?.report)reject(failure??new InstallationError(response?.error??'recovery_preparation_worker'));
      else resolve(response.report);
    });
  });
}

if(!isMainThread&&workerData?.format==='leafseamer-recovery-preparation-worker/1'){
  try{parentPort.postMessage({report:await prepare(workerData)});}
  catch(error){parentPort.postMessage({error:error instanceof InstallationError?error.code:'recovery_preparation_storage'});}
  finally{parentPort.close();}
}
