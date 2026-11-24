import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {requireValue as need} from './import-input.mjs';

const rawSha=/^[0-9a-f]{64}$(?![\s\S])/;
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const matches=(value,pattern)=>typeof value==='string'&&pattern.test(value);
const descriptor=stat=>({device:String(stat.dev),inode:String(stat.ino)});

export function pinExecutable(file,expected,maximum){
  need(fs.realpathSync.native(file)===file,'linux_member_artifact_path');
  const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  try{
    const info=fs.fstatSync(fd,{bigint:true});
    need(info.isFile()&&info.nlink===1n&&info.uid===0n&&(info.mode&0o6022n)===0n&&info.size>0n&&info.size<=BigInt(maximum),
      'linux_member_artifact');
    const sum=crypto.createHash('sha256'),bytes=Buffer.alloc(65536);
    let offset=0;
    while(offset<Number(info.size)){
      const count=fs.readSync(fd,bytes,0,Math.min(bytes.length,Number(info.size)-offset),offset);
      need(count>0,'linux_member_artifact');
      sum.update(bytes.subarray(0,count));offset+=count;
    }
    const after=fs.fstatSync(fd,{bigint:true});
    need(after.size===info.size&&after.mtimeNs===info.mtimeNs&&after.ctimeNs===info.ctimeNs&&
      'sha256:'+sum.digest('hex')===expected,'linux_member_artifact_digest');
    return {fd,identity:descriptor(info),mtime:info.mtimeNs,ctime:info.ctimeNs};
  }catch(error){fs.closeSync(fd);throw error;}
}

export function pinLinuxHelper(helperFile,file,format){
  const stat=fs.lstatSync(file,{bigint:true});
  need(stat.isFile()&&stat.uid===0n&&(stat.mode&0o022n)===0n&&stat.size<=4096n,'linux_member_helper_manifest');
  for(let directory=path.dirname(helperFile);directory!=='/';directory=path.dirname(directory)){
    const info=fs.lstatSync(directory,{bigint:true});
    const sticky=(directory==='/tmp'||directory==='/var/tmp')&&(info.mode&0o1000n)!==0n;
    need(info.isDirectory()&&info.uid===0n&&((info.mode&0o022n)===0n||sticky),'linux_member_helper_manifest');
  }
  const value=JSON.parse(fs.readFileSync(file,'utf8'));
  need(fields(value,'arch,binary_sha256,format,platform,source_sha256')&&value.format===format&&
    value.arch===process.arch&&value.platform==='linux'&&matches(value.binary_sha256,rawSha)&&matches(value.source_sha256,rawSha),
  'linux_member_helper_manifest');
  const digest='sha256:'+value.binary_sha256;
  return {...pinExecutable(helperFile,digest,4*1024*1024),digest};
}
