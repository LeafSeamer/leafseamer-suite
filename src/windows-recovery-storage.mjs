import fs from 'node:fs/promises';
import path from 'node:path';
import Database from 'better-sqlite3';
import {canonical,InstallationError,requireValue as need} from './import-input.mjs';

const markerName='recovery-storage.json';
const databaseName='controller.sqlite',journalName='supervisor-journal.db';
const identity=stat=>`${stat.dev}:${stat.ino}`;

export async function readWindowsRecoveryMarker(destination){
  const file=path.join(destination,markerName);
  const stat=await fs.lstat(file,{bigint:true}).catch(error=>{if(error.code!=='ENOENT')throw error;});
  if(!stat)return null;
  need(stat.isFile()&&stat.nlink===1n&&stat.size>0n&&stat.size<=4096n,'windows_recovery_data');
  const bytes=await fs.readFile(file);
  const marker=JSON.parse(bytes);
  need(marker&&typeof marker.root_identity==='string'&&/^[a-f0-9]{48}$/.test(marker.root_identity)&&
    bytes.equals(Buffer.from(canonical(marker))),'windows_recovery_data');
  return marker;
}

export async function inspectWindowsRecoveryStorage({native,pin,directory,member,selectionDigest,marker,existing}){
  native.protectObject(pin,member.directory_name,true,false);
  native.protectObject(pin,member.directory_name+'/'+databaseName,false,false);
  if(marker)native.protectObject(pin,markerName,false,false);
  const allowed=new Set([databaseName,journalName]);
  if(existing){
    for(const name of [databaseName,databaseName+'.owner'])for(const suffix of ['','-wal','-shm','-journal'])allowed.add(name+suffix);
    allowed.add(journalName+'-journal');
  }
  const files={};
  for(const name of (await fs.readdir(directory)).sort()){
    need(allowed.has(name),'windows_recovery_data');
    const stat=await fs.lstat(path.join(directory,name),{bigint:true});
    need(stat.isFile()&&stat.nlink===1n,'windows_recovery_data');
    files[name]={identity:identity(stat),size:String(stat.size),mtime:String(stat.mtimeNs),ctime:String(stat.ctimeNs)};
  }
  need(files[databaseName]&&files[journalName],'windows_recovery_data');
  const {root_identity}=native.preparedDescribe(pin);
  const layout={format:'leafseamer.windows-recovery-storage/1',selection_digest:selectionDigest,root_identity,
    directory_identity:identity(await fs.lstat(directory,{bigint:true})),database_identity:files[databaseName].identity,
    journal_identity:files[journalName].identity};
  if(marker)need(canonical(marker)===canonical(layout),'windows_recovery_data');
  return {layout,files};
}

export async function writeWindowsRecoveryMarker(native,pin,destination,layout){
  const file=await fs.open(path.join(destination,markerName),'wx');
  try{await file.writeFile(canonical(layout));await file.sync();}finally{await file.close();}
  native.protectObject(pin,markerName,false,true);
  native.flushPreparedObject(pin,markerName,false);
  native.flushPreparedObject(pin,'.',true);
}

// 只从日志中定位最新运行代，随后由原监督器在实例锁下验证退役原件。
export async function readWindowsRuntimeRetirement(supervisor,directory,scope){
  let db;
  try{
    const file=path.join(directory,journalName),stat=await fs.lstat(file,{bigint:true});
    need(stat.isFile()&&stat.nlink===1n&&stat.size<=16777216n,'windows_recovery_runtime_unproven');
    db=new Database(file,{readonly:true,fileMustExist:true,timeout:0});
    db.pragma('trusted_schema=OFF');
    need(db.pragma('journal_mode',{simple:true})==='delete','windows_recovery_runtime_unproven');
    const [attemptId,generation]=db.prepare(`SELECT a.attempt_id, json_extract(b.descriptor_jcs,'$.runtime_generation')
      FROM core_attempt a LEFT JOIN core_bootstrap b USING(attempt_id) ORDER BY a.rowid DESC LIMIT 1`).raw().get()??[];
    db.close();
    need(typeof generation==='string'&&/^[a-f0-9]{32}$/.test(generation),'windows_recovery_runtime_unproven');
    const proof=await supervisor.readProcessRecoveryRetirement({dataDir:directory,runtimeGeneration:generation,
      serviceId:scope.service_id,databaseInstanceId:scope.database_instance_id});
    need(proof.containment_id===attemptId&&proof.active_processes===0&&!proof.startup_fence,'windows_recovery_runtime_unproven');
    return proof;
  }catch(error){
    throw error instanceof InstallationError?error:new InstallationError('windows_recovery_runtime_unproven',{cause:error});
  }finally{if(db?.open)db.close();}
}
