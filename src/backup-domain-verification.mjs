import crypto from 'node:crypto';
import {createReadStream} from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {isMainThread,parentPort,Worker,workerData} from 'node:worker_threads';
import Database from 'better-sqlite3';
import {canonical,digest,InstallationError,requireValue as need} from './import-input.mjs';
import {reviewRestoredCommands} from './restore-command-review.mjs';

const verificationError='backup_snapshot_verification';
const manifestHash=/^sha256:[a-f0-9]{64}(?![\s\S])/;
const checksum=/^[a-f0-9]{64}(?![\s\S])/;
const filename=/^[A-Za-z0-9_.-]+(?![\s\S])/;
const reportLimit=65536;
const authorities=['controller','seamer'];
const workerFormat='leafseamer-backup-verifier/1';

async function loadVerifier({directory,manifest_sha256},authority){
  const manifestFile=path.join(directory,'build-manifest.json');
  const stat=await fs.lstat(manifestFile);
  need(stat.isFile()&&stat.nlink===1&&stat.size>0&&stat.size<=262144,verificationError);
  const raw=await fs.readFile(manifestFile);
  need('sha256:'+crypto.createHash('sha256').update(raw).digest('hex')===manifest_sha256,verificationError);
  const manifest=JSON.parse(raw);
  need(manifest?.format==='leafseamer-'+authority+'-build/1'&&manifest.artifacts&&
    typeof manifest.artifacts==='object'&&!Array.isArray(manifest.artifacts)&&
    Object.hasOwn(manifest.artifacts,'storage.mjs'),verificationError);
  const assets=Object.entries(manifest.artifacts);
  need(assets.length<=1024,verificationError);
  let total=0;
  const expectedFiles=new Map(),expectedDirs=new Set();
  for(const [name,sha] of assets){
    const parts=name.split('/');
    need(name!=='build-manifest.json'&&parts.length<=16&&
      parts.every(part=>part!=='.'&&part!=='..'&&!part.endsWith('.')&&filename.test(part))&&
      typeof sha==='string'&&checksum.test(sha),verificationError);
    expectedFiles.set(name,sha);
    for(let i=1;i<parts.length;i++)expectedDirs.add(parts.slice(0,i).join('/'));
  }
  async function verifyFiles(base,prefix=''){
    need((await fs.lstat(base)).isDirectory(),verificationError);
    for(const entry of await fs.readdir(base,{withFileTypes:true})){
      const name=prefix+entry.name,file=path.join(base,entry.name);
      if(name==='build-manifest.json')continue;
      if(entry.isDirectory()){
        need(expectedDirs.has(name),verificationError);
        await verifyFiles(file,name+'/');
        continue;
      }
      const info=await fs.lstat(file),sha=expectedFiles.get(name);
      total+=info.size;
      need(info.isFile()&&info.nlink===1&&sha!==undefined&&total<=512*1024**2,verificationError);
      const hash=crypto.createHash('sha256');
      for await(const chunk of createReadStream(file))hash.update(chunk);
      need(hash.digest('hex')===sha,verificationError);
      expectedFiles.delete(name);
    }
  }
  await verifyFiles(directory);
  need(expectedFiles.size===0,verificationError);
  const {verifyBackupSnapshot}=await import(pathToFileURL(path.join(directory,'storage.mjs')).href);
  need(typeof verifyBackupSnapshot==='function',verificationError);
  return verifyBackupSnapshot;
}

async function reviewBatch(inputs,distributions){
  const readers=new Map(),snapshots=[];
  try{
    for(const {receipt,file} of inputs){
      const authority=receipt.scope.authority;
      if(!readers.has(authority)){
        const {directory}=distributions[authority];
        const load=name=>import(pathToFileURL(path.join(directory,name)).href);
        readers.set(authority,authority==='controller'?
          {protocol:await load('peer-automation-command.mjs'),commandRecords:await load('command-record-store.mjs')}:
          {protocol:await load('runtime/peer-automation-command.mjs')});
      }
      const db=new Database(file,{readonly:true,fileMustExist:true,timeout:0});
      snapshots.push({db,receipt,...readers.get(authority)});
      db.pragma('trusted_schema=OFF');
      db.pragma('query_only=ON');
      db.pragma('cache_size=-256');
    }
    return reviewRestoredCommands(snapshots);
  }finally{
    for(const {db} of snapshots)db.close();
  }
}

async function verifyBatch({distributions,inputs,reviewCommands}){
  const readers=new Map(),reports=[];
  const original=reviewCommands?await Promise.all(inputs.map(({file})=>fs.lstat(file,{bigint:true}))):null;
  for(const {file,receipt} of inputs){
    const authority=receipt.scope.authority;
    if(!readers.has(authority))readers.set(authority,await loadVerifier(distributions[authority],authority));
    const report=readers.get(authority)(file,receipt);
    need(report?.format==='leafseamer.'+authority+'-backup-validation/1'&&
      report.backup_operation_id===receipt.backup_operation_id&&report.engine?.version===receipt.engine&&
      report.bytes===receipt.bytes&&report.sha256===receipt.sha256&&canonical(report.scope)===canonical(receipt.scope),
    verificationError);
    const text=canonical(report),size=Buffer.byteLength(text);
    need(size<=reportLimit,verificationError);
    reports.push({path:'reports/'+receipt.backup_operation_id+'.json',text,size,
      sha256:crypto.createHash('sha256').update(text).digest('hex')});
  }
  if(!reviewCommands)return {reports};
  const command_review=await reviewBatch(inputs,distributions);
  for(const [index,{file}] of inputs.entries()){
    const stat=await fs.lstat(file,{bigint:true}),before=original[index];
    need(stat.isFile()&&stat.nlink===1n&&['dev','ino','size','mtimeNs','ctimeNs'].every(key=>stat[key]===before[key]),verificationError);
  }
  return {reports,command_review};
}

if(!isMainThread&&workerData?.format===workerFormat){
  try{parentPort.postMessage(await verifyBatch(workerData));}
  catch(error){
    parentPort.postMessage({error:error?.code==='restore_command_conflict'?error.code:verificationError});
  }
}

export async function verifyBackupSnapshots(inputs,distributions,deadline,{reviewCommands=false}={}){
  need(distributions&&typeof distributions==='object'&&!Array.isArray(distributions),verificationError);
  const required=authorities.filter(authority=>inputs.some(({receipt})=>receipt.scope.authority===authority));
  need(Object.keys(distributions).length===required.length,verificationError);
  const verifiers=required.map(authority=>{
    const value=distributions[authority];
    need(value&&typeof value.directory==='string'&&path.isAbsolute(value.directory)&&
      path.resolve(value.directory)===value.directory&&typeof value.manifest_sha256==='string'&&
      manifestHash.test(value.manifest_sha256),verificationError);
    return {authority,manifest_sha256:value.manifest_sha256};
  });
  const remaining=deadline-performance.now();
  need(remaining>0,'backup_archive_deadline');
  const {reports,command_review}=await new Promise((resolve,reject)=>{
    const selected=Object.fromEntries(verifiers.map(({authority,manifest_sha256})=>
      [authority,{directory:distributions[authority].directory,manifest_sha256}]));
    const worker=new Worker(new URL(import.meta.url),{
      workerData:{format:workerFormat,inputs,distributions:selected,reviewCommands},
      execArgv:[],
      resourceLimits:{maxOldGenerationSizeMb:256}
    });
    let stopped=false,result;
    const timer=setTimeout(()=>{stopped=true;void worker.terminate();},remaining);
    worker.once('message',value=>{result=value;});
    worker.once('error',()=>{});
    worker.once('exit',code=>{
      clearTimeout(timer);
      if(stopped)reject(new InstallationError('backup_archive_deadline'));
      else if(code!==0||!Array.isArray(result?.reports))reject(new InstallationError(result?.error??verificationError));
      else resolve(result);
    });
  });
  return {reports,verifiers,verification_ref:digest({verifiers,reports:reports.map(({path,size,sha256})=>({path,size,sha256}))}),
    ...(reviewCommands&&{command_review})};
}
