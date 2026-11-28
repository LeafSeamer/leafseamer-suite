import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {digest, InstallationError, requireValue as need} from './import-input.mjs';

const executable = fileURLToPath(new URL('./native/leafseamer_backup_crypto' +
  (process.platform==='win32' ? '.exe' : ''),import.meta.url));
const maxArchive = 64 * 1024 ** 3;
const maxManifest = 16 * 1024 ** 2;
const hash = /^[0-9a-f]{64}(?![\s\S])/;
const recipient = /^age1[023456789acdefghjklmnpqrstuvwxyz]{58}(?![\s\S])/;

export function encryptionInput(mode, recipients, passphrase){
  if(mode==='x25519'){
    need(Array.isArray(recipients)&&recipients.length>0&&recipients.length<=16&&
      new Set(recipients).size===recipients.length&&recipients.every(key=>typeof key==='string'&&recipient.test(key))&&
      passphrase===undefined,'backup_archive_encryption');
    return {profile:{mode,recipients:[...recipients]},secret:null};
  }
  need(mode==='passphrase'&&recipients===undefined&&passphrase instanceof Uint8Array&&
    passphrase.byteLength>0&&passphrase.byteLength<=16384,'backup_archive_encryption');
  return {profile:{mode,recipients:[]},secret:Buffer.from(passphrase)};
}

export async function inspectBackupManifest(directory, operationId, plan, snapshots) {
  const file = path.join(directory,'manifest.json');
  const before = await fs.lstat(file);
  need(before.isFile()&&before.nlink===1&&before.size>0&&before.size<=maxManifest,'backup_archive_manifest');
  const fd = await fs.open(file,'r');
  let raw;
  try {
    const now = await fd.stat();
    need(now.isFile()&&now.dev===before.dev&&now.ino===before.ino&&now.size===before.size,'backup_archive_manifest');
    const chunks = [];
    let bytes = 0;
    for await(const chunk of fd.createReadStream({autoClose:false,start:0,end:before.size})){
      bytes+=chunk.length;
      chunks.push(chunk);
    }
    need(bytes===before.size,'backup_archive_manifest');
    raw = Buffer.concat(chunks,bytes);
  } finally {await fd.close();}
  let manifest;
  try { manifest=JSON.parse(raw); }
  catch { throw new InstallationError('backup_archive_manifest'); }
  need(manifest?.format==='leafseamer-backup-tar/1'&&manifest.backup_id===operationId&&
    manifest.level===plan.backup_level&&manifest.consistency===plan.consistency&&Array.isArray(manifest.coverage)&&
    digest(manifest.coverage)===plan.coverage_digest&&manifest.coverage.every(entry=>entry?.state!=='missing')&&
    Array.isArray(manifest.files)&&Array.isArray(manifest.databases)&&Array.isArray(manifest.validation_reports)&&
    manifest.databases.length===snapshots.length&&(snapshots.length===0||manifest.validation_reports.length>0),'backup_archive_coverage');
  const files = new Map(manifest.files.filter(file=>file?.role==='database').map(file=>[file.path,file]));
  const points = new Map(manifest.databases.map(entry=>[entry?.consistency_point,entry]));
  const seen = new Set();
  need(files.size===snapshots.length&&points.size===snapshots.length&&snapshots.every(snapshot=>{
    const record=points.get(snapshot.backup_operation_id),file=files.get(record?.path);
    if(!file||seen.has(record.path))return false;
    seen.add(record.path);
    return record.service===snapshot.scope.service_id&&record.database_instance===snapshot.scope.database_instance_id&&
      record.schema===snapshot.scope.schema_revision&&record.engine===snapshot.engine&&file.size===snapshot.bytes&&file.sha256===snapshot.sha256;
  }),'backup_archive_snapshots');
  return {manifest_sha256:crypto.createHash('sha256').update(raw).digest('hex'),files:manifest.files.length};
}

async function seal(directory, destination, manifest, profile, secret, deadline) {
  const args=['seal','--directory',directory,'--destination',destination,'--manifest-sha256',manifest,
    '--mode',profile.mode,...profile.recipients.flatMap(key=>['--recipient',key])];
  let result;
  try {
    result=await new Promise((resolve,reject)=>{
      const budget=deadline-performance.now();
      need(budget>0,'backup_archive_deadline');
      const child=spawn(executable,args,{windowsHide:true,stdio:['pipe','pipe','ignore']});
      const timer=setTimeout(()=>child.kill('SIGKILL'),budget);
      let size=0, failure=false;const chunks=[];
      child.on('error',()=>{failure=true;});
      child.stdout.on('data',chunk=>{
        size+=chunk.length;
        if(size<=4096)chunks.push(chunk);else{failure=true;child.kill('SIGKILL');}
      });
      child.stdin.on('error',()=>{failure=true;});
      child.on('close',code=>{
        clearTimeout(timer);
        if(code!==0||failure)reject(new InstallationError('backup_archive_seal'));
        else resolve(Buffer.concat(chunks,size));
      });
      child.stdin.end(secret??undefined);
    });
  }finally{secret?.fill(0);}
  let receipt;
  try {receipt=JSON.parse(result);}
  catch {throw new InstallationError('backup_archive_seal');}
  need(receipt?.state==='staged'&&Number.isSafeInteger(receipt.ciphertext_bytes)&&receipt.ciphertext_bytes>0&&
    receipt.ciphertext_bytes<=maxArchive&&typeof receipt.ciphertext_sha256==='string'&&hash.test(receipt.ciphertext_sha256),'backup_archive_seal');
  return receipt;
}

export async function materializeBackupArchive(directory,destination,manifest,profile,secret,deadline){
  const sealed=await seal(directory,destination,manifest,profile,secret,deadline);
  const file=path.join(destination,'archive.age'),stat=await fs.lstat(file);
  need(stat.isFile()&&stat.nlink===1&&stat.size===sealed.ciphertext_bytes,'backup_archive_ciphertext');
  const fd=await fs.open(file,'r');
  try {
    const before=await fd.stat(),check=crypto.createHash('sha256');
    need(before.dev===stat.dev&&before.ino===stat.ino&&before.size===stat.size,'backup_archive_ciphertext');
    let size=0;
    for await(const chunk of fd.createReadStream({autoClose:false,start:0,end:stat.size})){
      need(performance.now()<deadline,'backup_archive_deadline');
      size+=chunk.length;check.update(chunk);
    }
    const after=await fs.lstat(file);
    need(size===sealed.ciphertext_bytes&&check.digest('hex')===sealed.ciphertext_sha256&&
      after.ino===stat.ino&&after.dev===stat.dev&&after.ctimeMs===stat.ctimeMs,'backup_archive_ciphertext');
  }finally{await fd.close();}
  return {ciphertext_bytes:sealed.ciphertext_bytes,ciphertext_sha256:sealed.ciphertext_sha256};
}
