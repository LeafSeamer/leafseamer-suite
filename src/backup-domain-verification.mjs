import crypto from 'node:crypto';
import {createReadStream} from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {isMainThread,parentPort,Worker,workerData} from 'node:worker_threads';
import {canonical,digest,InstallationError,requireValue as need} from './import-input.mjs';

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

async function verifyBatch({distributions,inputs}){
  const readers=new Map(),reports=[];
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
  return reports;
}

if(!isMainThread&&workerData?.format===workerFormat){
  const {inputs,distributions}=workerData;
  parentPort.postMessage(await verifyBatch({inputs,distributions}));
}

export async function verifyBackupSnapshots(inputs,distributions,deadline){
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
  const reports=await new Promise((resolve,reject)=>{
    const selected=Object.fromEntries(verifiers.map(({authority,manifest_sha256})=>
      [authority,{directory:distributions[authority].directory,manifest_sha256}]));
    const worker=new Worker(new URL(import.meta.url),{
      workerData:{format:workerFormat,inputs,distributions:selected},
      resourceLimits:{maxOldGenerationSizeMb:256}
    });
    let stopped=false,result;
    const timer=setTimeout(()=>{stopped=true;void worker.terminate();},remaining);
    worker.once('message',value=>{result=value;});
    worker.once('error',()=>{});
    worker.once('exit',code=>{
      clearTimeout(timer);
      if(stopped)reject(new InstallationError('backup_archive_deadline'));
      else if(code!==0||!Array.isArray(result))reject(new InstallationError(verificationError));
      else resolve(result);
    });
  });
  return {reports,verifiers,verification_ref:digest({verifiers,reports:reports.map(({path,size,sha256})=>({path,size,sha256}))})};
}
