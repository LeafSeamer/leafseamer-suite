import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {Worker,isMainThread,parentPort,workerData} from 'node:worker_threads';
import {installationContentPlatform} from './local-peer.mjs';
import {InstallationError,requireValue as need} from './import-input.mjs';

async function prepare(input){
  const native=installationContentPlatform();let sourcePin,targetPin,root;
  try{
    sourcePin=native.contentPin(input.source_directory,input.inventory.files);
    root=native.prepareRoot(input.parent_directory,input.directory_id,input.reader_sids);
    const description=native.preparedDescribe(root),directories=new Set();let total=0;
    for(const file of input.inventory.files){
      const parts=file.path.split('/');for(let i=1;i<parts.length;i++)directories.add(parts.slice(0,i).join('/'));
    }
    for(const directory of [...directories].sort((a,b)=>a.split('/').length-b.split('/').length||a.localeCompare(b))){
      await fsp.mkdir(path.join(description.path,...directory.split('/')));native.protectObject(root,directory,true,true);
    }
    for(const file of input.inventory.files){
      const source=await fsp.open(path.join(input.source_directory,...file.path.split('/')),'r');let target;
      try{
        target=await fsp.open(path.join(description.path,...file.path.split('/')),'wx',0o600);
        const hash=crypto.createHash('sha256'),buffer=Buffer.alloc(65536),limit=Number(file.size_bytes);let offset=0;
        for(;;){
          const {bytesRead}=await source.read(buffer,0,Math.min(buffer.length,limit+1-offset),offset);if(!bytesRead)break;
          need(offset+bytesRead<=limit,'preparation_size');hash.update(buffer.subarray(0,bytesRead));let written=0;
          while(written<bytesRead){const result=await target.write(buffer,written,bytesRead-written,offset+written);need(result.bytesWritten>0,'preparation_write');written+=result.bytesWritten;}
          offset+=bytesRead;
        }
        need(offset===limit&&'sha256:'+hash.digest('hex')===file.digest,'preparation_digest');total+=offset;await target.sync();
      }finally{try{await target?.close();}finally{await source.close();}}
      native.protectObject(root,file.path,false,true);
      // ACL设置在首次文件sync之后；在只读内容锁建立前再刷新一次文件元数据。
      native.flushPreparedObject(root,file.path,false);
    }
    native.contentVerify(sourcePin);targetPin=native.contentPin(description.path,input.inventory.files);
    native.protectObject(root,'.',true,false);
    for(const directory of directories)native.protectObject(root,directory,true,false);
    for(const file of input.inventory.files)native.protectObject(root,file.path,false,false);
    native.contentVerify(targetPin);
    for(const directory of [...directories].sort((a,b)=>b.split('/').length-a.split('/').length||a.localeCompare(b)))native.flushPreparedObject(root,directory,true);
    native.flushPreparedObject(root,'.',true);
    const parentIdentity=native.flushPreparedParent(root);
    native.contentVerify(targetPin);
    const finalDescription=native.preparedDescribe(root);
    need(JSON.stringify(description.storage_identity)===JSON.stringify(finalDescription.storage_identity),'preparation_storage_changed');
    return {format:'leafseamer-content-preparation/1',content_directory:input.directory_id,root_identity:description.root_identity,
      storage_identity:description.storage_identity,
      metadata_flush:{format:'windows-content-flush/1',method:'FlushFileBuffers',file_count:input.inventory.files.length,
        directory_count:directories.size+1,parent_identity:parentIdentity,order:'files_then_directories_bottom_up_then_parent',completed:true},
      writer_sid:description.writer_sid,reader_sids:input.reader_sids,dacl_profile:'windows-installer-only-write/1',
      file_count:input.inventory.files.length,payload_bytes:String(total),file_flush_completed:true,directory_durability:'unqualified',sealed:false};
  }finally{if(targetPin)native.contentClose(targetPin);if(root)native.preparedClose(root);if(sourcePin)native.contentClose(sourcePin);}
}

export function prepareContent(input,{checkCurrent}){
  need(isMainThread,'preparation_host');checkCurrent();
  return new Promise((resolve,reject)=>{
    const worker=new Worker(new URL('./content-preparation.mjs',import.meta.url),{workerData:input});let result,failure;
    const stop=error=>{failure??=error;worker.terminate().catch(()=>{});};
    const timer=setInterval(()=>{try{checkCurrent();}catch(error){stop(error);}},100);
    const deadline=setTimeout(()=>stop(new InstallationError('preparation_timeout')),600000);
    worker.on('message',message=>{if(result)stop(new InstallationError('preparation_worker'));else result=message;});
    worker.on('error',()=>{failure??=new InstallationError('preparation_worker');});
    worker.on('exit',code=>{
      clearInterval(timer);clearTimeout(deadline);
      try{
        if(failure)throw failure;need(code===0&&result,'preparation_worker');
        if(result.error)throw new InstallationError(result.error);
        checkCurrent();resolve(result.report);
      }catch(error){reject(error);}
    });
  });
}
if(!isMainThread){
  try{parentPort.postMessage({report:await prepare(workerData)});}
  catch(error){parentPort.postMessage({error:typeof error.code==='string'&&/^(preparation|content|peer)_[a-z_]{1,64}$/.test(error.code)?error.code:'preparation_unavailable'});}
  finally{parentPort.close();}
}
