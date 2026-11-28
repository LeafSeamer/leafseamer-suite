import fs from 'node:fs/promises';
import {lstatSync,readdirSync} from 'node:fs';
import {constants,createReadStream,createWriteStream} from 'node:fs';
import {createHash} from 'node:crypto';
import {Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import path from 'node:path';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {readDeploymentFile} from './linux-ingress.mjs';

const flags=constants.O_RDONLY|constants.O_NOFOLLOW;
const markerName='.recovery-storage.json';
const identity=stat=>({device:String(stat.dev),inode:String(stat.ino)});

export function inspectLinuxRecoveryStorage(root,{member,spec},running=false){
  const directory=path.join(root,member.directory_name),name=spec.role+'.sqlite';
  const uid=BigInt(spec.uid),gid=BigInt(spec.gid);
  const folder=lstatSync(directory,{bigint:true}),stat=lstatSync(path.join(directory,name),{bigint:true});
  const owned=entry=>entry.uid===uid&&entry.gid===gid;
  need(folder.isDirectory()&&owned(folder)&&(folder.mode&0o7777n)===0o700n,'linux_recovery_data');
  const allowed=new Set([name]);
  if(running){
    for(const ending of ['-wal','-shm','-journal'])allowed.add(name+ending);
    if(spec.role==='controller')for(const ending of ['','-journal','-wal','-shm'])allowed.add(name+'.owner'+ending);
  }
  for(const entry of readdirSync(directory)){
    if(entry===name)continue;
    const file=lstatSync(path.join(directory,entry),{bigint:true});
    need(allowed.has(entry)&&owned(file)&&file.isFile()&&file.nlink===1n&&(file.mode&0o022n)===0n,'linux_recovery_data');
  }
  need(stat.isFile()&&stat.nlink===1n&&owned(stat)&&(stat.mode&0o7777n)===0o600n,'linux_recovery_data');
  return {binding:{directory:identity(folder),database:identity(stat)},stat};
}

function storageLayout(destination,selectionDigest,members){
  const folder=lstatSync(destination,{bigint:true});
  need(folder.isDirectory()&&folder.uid===0n&&(folder.mode&0o7777n)===0o711n,'linux_recovery_data');
  const root=identity(folder),entries=readdirSync(destination).filter(entry=>entry!==markerName).sort();
  need(canonical(entries)===canonical(members.map(({member})=>member.directory_name).sort()),'linux_recovery_data');
  return {format:'leafseamer.linux-recovery-storage/1',selection_digest:selectionDigest,root,
    services:members.map(entry=>({role:entry.spec.role,...inspectLinuxRecoveryStorage(destination,entry,true).binding}))};
}

async function writeLayout(directory,layout){
  const marker=await fs.open(path.join(directory,markerName),'wx',0o600);
  try{await marker.writeFile(canonical(layout));await marker.sync();}finally{await marker.close();}
}

export async function reopenLinuxRecoveryStorage({destination,selectionDigest,members,legacy,assertCurrent}){
  const layout=storageLayout(destination,selectionDigest,members),file=path.join(destination,markerName);
  const stat=await fs.lstat(file,{bigint:true}).catch(error=>{if(error.code!=='ENOENT')throw error;});
  if(stat){
    need(stat.isFile()&&stat.uid===0n&&stat.nlink===1n&&(stat.mode&0o7777n)===0o600n&&
      readDeploymentFile(file,16384).equals(Buffer.from(canonical(layout))),'linux_recovery_data');
  }else{
    need(legacy,'linux_recovery_data');
    assertCurrent(true);
    await writeLayout(destination,layout);
    await syncDirectory(destination);
  }
  return {layout,storageDigest:digest(layout)};
}

async function syncDirectory(directory){
  const handle=await fs.open(directory,flags|constants.O_DIRECTORY);
  try{await handle.sync();}finally{await handle.close();}
}

async function copyDatabase(source,destination,member,uid,gid){
  const reader=await fs.open(source,flags);
  try{
    const initial=await reader.stat({bigint:true}),sha=createHash('sha256');
    let bytes=0;
    const check=stat=>need(stat.isFile()&&stat.nlink===1n&&stat.size===BigInt(member.bytes)&&
      ['dev','ino','ctimeNs','mtimeNs'].every(key=>stat[key]===initial[key]),'linux_recovery_data');
    check(initial);
    const digestStream=new Transform({transform(chunk,encoding,done){
      bytes+=chunk.length;sha.update(chunk);done(null,chunk);
    }});
    await pipeline(createReadStream(source,{fd:reader.fd,autoClose:false}),digestStream,
      createWriteStream(destination,{flags:'wx',mode:0o600}));
    check(await reader.stat({bigint:true}));
    check(await fs.lstat(source,{bigint:true}));
    need(bytes===member.bytes&&sha.digest('hex')===member.sha256,'linux_recovery_data');
    const writer=await fs.open(destination,flags);
    try{
      await writer.chown(uid,gid);await writer.sync();
      return await writer.stat({bigint:true});
    }finally{await writer.close();}
  }finally{await reader.close();}
}

export async function publishLinuxRecoveryStorage({destination,source,members,selectionDigest,assertCurrent}){
  const parent=path.dirname(destination);
  need(!(await fs.lstat(destination).catch(error=>{if(error.code!=='ENOENT')throw error;})),
    'linux_recovery_start_indeterminate');
  const temporary=await fs.mkdtemp(path.join(parent,'.recovery-'));
  const pins=new Map();
  let published=false;
  try{
    for(const {member,spec} of members){
      const {uid,gid,role}=spec,{directory_name}=member;
      const directory=path.join(temporary,directory_name),name=role+'.sqlite';
      await fs.mkdir(directory,{mode:0o700});
      pins.set(spec.launch_id,await copyDatabase(path.join(source,directory_name,name),path.join(directory,name),member,uid,gid));
      await fs.chown(directory,uid,gid);
      await syncDirectory(directory);
    }
    await fs.chmod(temporary,0o711);
    const layout=storageLayout(temporary,selectionDigest,members);
    await writeLayout(temporary,layout);
    await syncDirectory(temporary);
    assertCurrent();
    await fs.rename(temporary,destination);
    published=true;
    await syncDirectory(parent);
    return {pins,layout,storageDigest:digest(layout)};
  }finally{
    if(!published)await fs.rm(temporary,{recursive:true,force:true});
  }
}
