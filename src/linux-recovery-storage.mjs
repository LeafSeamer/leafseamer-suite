import fs from 'node:fs/promises';
import {constants,createReadStream,createWriteStream} from 'node:fs';
import {createHash} from 'node:crypto';
import {Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import path from 'node:path';
import {requireValue as need} from './import-input.mjs';

const flags=constants.O_RDONLY|constants.O_NOFOLLOW;

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

export async function publishLinuxRecoveryStorage({destination,source,members,assertCurrent}){
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
    await syncDirectory(temporary);
    assertCurrent();
    await fs.rename(temporary,destination);
    published=true;
    await syncDirectory(parent);
    return pins;
  }finally{
    if(!published)await fs.rm(temporary,{recursive:true,force:true});
  }
}
