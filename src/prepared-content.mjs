import {installationContentPlatform} from './local-peer.mjs';
import {canonical,requireValue as need} from './import-input.mjs';
import {Worker,isMainThread,parentPort,workerData} from 'node:worker_threads';
import {InstallationError} from './import-input.mjs';

// 持有祖先、目录及文件句柄直到同步回调结束；不修复ACL，不采用未登记目录。
export function withPreparedContent(parentDirectory,prepared,validated,fn,{refresh=false}={}){
  const native=installationContentPlatform(),report=prepared.body;let root,pin;
  try{
    need(report.validation_id===validated.validation_id&&report.validation_report_digest===validated.report_digest&&
      report.metadata_flush?.completed===true,'preparation_report');
    root=native.reopenPreparedRoot(parentDirectory,prepared.preparation_id,report.reader_sids,report.root_identity);
    const observed=native.preparedDescribe(root);
    need(observed.writer_sid===report.writer_sid&&canonical(observed.storage_identity)===canonical(report.storage_identity)&&
      observed.parent_identity===report.metadata_flush.parent_identity,'preparation_storage_changed');
    const directories=new Set();
    for(const file of validated.report.inventory.files){
      const parts=file.path.split('/');for(let i=1;i<parts.length;i++)directories.add(parts.slice(0,i).join('/'));
      native.protectObject(root,file.path,false,false);
      if(refresh)native.flushPreparedObject(root,file.path,false);
    }
    pin=native.contentPin(observed.path,validated.report.inventory.files);
    for(const directory of directories)native.protectObject(root,directory,true,false);
    native.contentVerify(pin);
    let flushed=null;
    if(refresh){
      for(const directory of [...directories].sort((a,b)=>b.split('/').length-a.split('/').length||a.localeCompare(b)))native.flushPreparedObject(root,directory,true);
      native.flushPreparedObject(root,'.',true);const parent=native.flushPreparedParent(root);
      need(parent===observed.parent_identity,'preparation_storage_changed');native.contentVerify(pin);
      need(canonical(native.preparedDescribe(root))===canonical(observed),'preparation_storage_changed');
      flushed={format:'windows-content-flush/1',method:'FlushFileBuffers',file_count:validated.report.inventory.files.length,
        directory_count:directories.size+1,parent_identity:parent,order:'files_then_directories_bottom_up_then_parent',completed:true};
    }
    const result=fn(observed,flushed,(path,limit)=>native.contentRead(pin,path,limit));need(!result||typeof result.then!=='function','preparation_async_observation');return result;
  }finally{if(pin)native.contentClose(pin);if(root)native.preparedClose(root);}
}

// worker在等待writer裁决时仍持有内容句柄；回调只能同步提交，不能将句柄生命周期延伸到Promise。
export function verifyForSealing(input,{checkCurrent,commit}){
  return observePreparedContent(input,{checkCurrent,complete:commit,refresh:true,timeoutMs:600000});
}
export function observePreparedContent(input,{checkCurrent,complete,refresh=false,timeoutMs=4000}){
  need(isMainThread,'preparation_host');checkCurrent();
  return new Promise((resolve,reject)=>{
    const releaseSignal=new SharedArrayBuffer(4),signal=new Int32Array(releaseSignal);
    const worker=new Worker(new URL('./prepared-content.mjs',import.meta.url),{workerData:{...input,format:'leafseamer-prepared-observation/1',refresh,timeout_ms:timeoutMs,release_signal:releaseSignal}});let result,failure,received=false,committed=false;
    const stop=error=>{failure??=error;Atomics.store(signal,0,2);Atomics.notify(signal,0);worker.terminate().catch(()=>{});};
    const timer=setInterval(()=>{if(!committed)try{checkCurrent();}catch(error){stop(error);}},100);
    const deadline=setTimeout(()=>stop(new InstallationError(refresh?'sealing_timeout':'preparation_observation_timeout')),timeoutMs);
    worker.on('message',message=>{
      try{
        need(!received&&!failure,'sealing_worker');received=true;
        if(message.error)throw new InstallationError(message.error);
        need(message.description&&(!refresh||message.flushed?.completed===true),'sealing_worker');checkCurrent();
        result=complete(message.description,message.flushed,message.documents);need(!result||typeof result.then!=='function','preparation_async_observation');committed=true;
        Atomics.store(signal,0,1);Atomics.notify(signal,0);
      }catch(error){stop(error);}
    });
    worker.on('error',()=>stop(new InstallationError('sealing_worker')));
    worker.on('exit',code=>{
      clearInterval(timer);clearTimeout(deadline);
      if(committed)resolve(result);
      else reject(failure??new InstallationError(code===0?'sealing_worker':'sealing_interrupted'));
    });
  });
}

// 仅供可信启动器交接内容。固定截止不续期；调用者必须在释放前建立自己的加载保护。
export function holdPreparedContent(input,{checkCurrent,complete,timeoutMs=4000}){
  need(isMainThread&&Number.isInteger(timeoutMs)&&timeoutMs>0&&timeoutMs<=4000,'preparation_host');checkCurrent();
  return new Promise((resolve,reject)=>{
    const releaseSignal=new SharedArrayBuffer(4),signal=new Int32Array(releaseSignal);
    const worker=new Worker(new URL('./prepared-content.mjs',import.meta.url),{workerData:{...input,format:'leafseamer-prepared-observation/1',
      refresh:false,hold:true,timeout_ms:timeoutMs,release_signal:releaseSignal}});
    let delivered=false,received=false,ending=false,failure=null,finish;
    const closed=new Promise(resolve=>{finish=resolve;});
    const stop=error=>{
      if(ending)return;ending=true;failure=error;clearInterval(timer);clearTimeout(deadline);
      Atomics.store(signal,0,error?2:1);Atomics.notify(signal,0);if(error)worker.terminate().catch(()=>{});
    };
    const assertCurrent=()=>{
      need(!ending&&Atomics.load(signal,0)===0,'materialization_hold_closed');
      try{checkCurrent();}catch(error){stop(error);throw error;}
    };
    const timer=setInterval(()=>{try{assertCurrent();}catch(error){stop(error);}},100);
    const deadline=setTimeout(()=>stop(new InstallationError('materialization_timeout')),timeoutMs);
    worker.on('message',message=>{
      try{
        need(!received&&!ending,'sealing_worker');received=true;
        if(message.error)throw new InstallationError(message.error);
        need(message.description,'sealing_worker');assertCurrent();const value=complete(message.description);
        need(!value||typeof value.then!=='function','preparation_async_observation');assertCurrent();delivered=true;
        resolve(Object.freeze({value,assertCurrent,close(){stop(null);return closed;},closed}));
      }catch(error){stop(error);}
    });
    worker.on('error',()=>stop(new InstallationError('sealing_worker')));
    worker.on('exit',code=>{
      if(!ending){ending=true;failure=new InstallationError(code===0?'materialization_hold_closed':'sealing_interrupted');}
      clearInterval(timer);clearTimeout(deadline);Atomics.store(signal,0,3);
      if(!delivered)reject(failure??new InstallationError('sealing_worker'));
      finish(Object.freeze({status:failure?'invalidated':'released',code:failure?.code??null}));
    });
  });
}
if(!isMainThread&&workerData?.format==='leafseamer-prepared-observation/1'){
  // Atomics.wait让同步保护作用域保持存活，直到writer通过共享标志释放。
  const signal=new Int32Array(workerData.release_signal);
  try{
    withPreparedContent(workerData.parent_directory,workerData.prepared,workerData.validated,(description,flushed,read)=>{
      const requested=workerData.read_files??[];need(Array.isArray(requested)&&requested.length<=64,'preparation_read_capacity');let remaining=1048576;
      const documents=requested.map(file=>{need(remaining>0,'preparation_read_capacity');const bytes=read(file.path,remaining);remaining-=bytes.length;return {file_id:file.file_id,bytes};});
      parentPort.postMessage({description,flushed,documents});Atomics.wait(signal,0,0,workerData.timeout_ms);
      if(workerData.hold)Atomics.compareExchange(signal,0,0,3);
    },{refresh:workerData.refresh});
  }catch(error){parentPort.postMessage({error:typeof error.code==='string'&&/^(preparation|content|peer)_[a-z_]{1,64}$/.test(error.code)?error.code:'sealing_unavailable'});}
  finally{parentPort.close();}
}
