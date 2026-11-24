import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canonical,InstallationError,requireValue as need} from './import-input.mjs';

const {O_RDONLY,O_DIRECTORY,O_NOFOLLOW,O_NONBLOCK,O_WRONLY,O_CREAT,O_EXCL}=fs.constants;
const readFlags=O_RDONLY|O_NOFOLLOW|O_NONBLOCK;
const identity=stat=>`${stat.dev}:${stat.ino}`;
const attributes=fd=>fs.fstatSync(fd,{bigint:true});
const mode=value=>value.mode&0o7777n;
const descriptor=fd=>`/proc/self/fd/${fd}`;
const entry=(fd,name)=>descriptor(fd)+'/'+name;
const safeName=name=>typeof name==='string'&&/^[A-Za-z0-9_.-]{1,255}$(?![\s\S])/.test(name)&&name!=='.'&&name!=='..';
const same=(a,b)=>canonical(a)===canonical(b);

export const linuxFlush=Object.freeze({format:'linux-content-flush/1',method:'fsync',order:'files_then_directories_bottom_up_then_parent'});

function checked(operation){
  try{return operation();}catch(error){
    if(error instanceof InstallationError)throw error;
    const reason=['ELOOP','ENOTDIR','ENOENT'].includes(error.code)?'content_missing_or_unlinked':'preparation_linux_unavailable';
    throw new InstallationError(reason,{cause:error});
  }
}

function using(filename,flags,fn,permissions=0o600){
  const fd=fs.openSync(filename,flags,permissions);
  try{return fn(fd);}finally{fs.closeSync(fd);}
}

// 路径逐段打开，并持有从根到内容的目录描述符。发布者可读写自身安装库，普通运行账户不能更换其路径。
function withProtectedDirectory(filename,fn,permissions=0o700n){
  need(typeof filename==='string'&&path.isAbsolute(filename)&&path.normalize(filename)===filename&&filename!=='/'&&
    fs.statfsSync('/proc/self/fd').type===0x9fa0,'preparation_linux_directory');
  const parts=filename.slice(1).split('/'),uid=BigInt(process.geteuid());
  need(parts.length<=128&&parts.every(part=>part.length>0&&!part.includes('\0')),'preparation_linux_directory');
  const pinned=[];
  function visit(current,index,name){
    return using(name,readFlags|O_DIRECTORY,fd=>{
      const stat=attributes(fd),sticky=(current==='/tmp'||current==='/var/tmp')&&stat.uid===0n&&(stat.mode&0o1000n)!==0n;
      need(stat.isDirectory()&&(stat.uid===uid||stat.uid===0n)&&((stat.mode&0o022n)===0n||sticky),'preparation_linux_directory');
      pinned.push({fd,name,identity:identity(stat)});
      if(index<parts.length)return visit(path.join(current,parts[index]),index+1,entry(fd,parts[index]));
      need(stat.uid===uid&&mode(stat)===permissions,'preparation_linux_permissions');
      const assertLinked=()=>{
        for(const item of pinned)need(identity(fs.lstatSync(item.name,{bigint:true}))===item.identity&&
          identity(attributes(item.fd))===item.identity,'preparation_storage_changed');
      };
      assertLinked();return fn(fd,stat,assertLinked);
    });
  }
  return visit('/',0,'/');
}

function inventoryTree(inventory){
  const tree=new Map();
  for(const file of inventory.files){
    const parts=file.path.split('/');need(parts.length<=121&&parts.every(safeName),'content_path');
    let directory=tree;
    for(const part of parts.slice(0,-1)){
      if(!directory.has(part))directory.set(part,new Map());
      directory=directory.get(part);need(directory instanceof Map,'content_path');
    }
    const name=parts.at(-1);need(!directory.has(name),'content_path');directory.set(name,file);
  }
  return tree;
}

function verifyFile(fd,file,buffer,output=null,readLimit=null){
  const size=Number(file.size_bytes),hash=crypto.createHash('sha256');
  need(Number.isSafeInteger(size)&&size>=0&&attributes(fd).size===BigInt(size),'content_size');
  const bytes=readLimit===null?null:Buffer.alloc(Math.min(size,readLimit));
  need(!bytes||bytes.length===size,'content_read_capacity');
  let offset=0;
  while(offset<size){
    const count=fs.readSync(fd,buffer,0,Math.min(buffer.length,size-offset),offset);
    need(count>0,'content_size');hash.update(buffer.subarray(0,count));bytes?.set(buffer.subarray(0,count),offset);
    if(output!==null){
      let written=0;
      while(written<count){
        const step=fs.writeSync(output,buffer,written,count-written,offset+written);
        need(step>0,'preparation_write');written+=step;
      }
    }
    offset+=count;
  }
  need(fs.readSync(fd,buffer,0,1,size)===0&&'sha256:'+hash.digest('hex')===file.digest,'content_digest');
  return bytes;
}

function scan(root,tree,{copyTo=null,refresh=false,readerGid=null}={}){
  const anchor=attributes(root),sum=crypto.createHash('sha256'),buffer=Buffer.alloc(65536);let dirs=0,bytes=0;
  const copying=copyTo!==null;
  function walk(fd,directory,relative,target){
    const found=fs.readdirSync(descriptor(fd),{withFileTypes:true});
    need(found.length===directory.size&&found.every(item=>directory.has(item.name)),'content_inventory');
    dirs++;
    for(const [name,item] of directory){
      const isDirectory=item instanceof Map,full=relative+name;
      using(entry(fd,name),readFlags|(isDirectory?O_DIRECTORY:0),child=>{
        const stat=attributes(child);
        const archive=copying&&readerGid===null;
        need(stat.uid===anchor.uid&&stat.dev===anchor.dev&&mode(stat)===(isDirectory?(archive?0o700n:0o500n):(archive?0o600n:0o400n))&&
          (isDirectory?stat.isDirectory():stat.isFile()&&stat.nlink===1n),'content_permissions');
        sum.update(canonical([full,identity(stat)])+'\n');
        if(isDirectory){
          if(copying){
            fs.mkdirSync(entry(target,name),{mode:0o700});
            using(entry(target,name),readFlags|O_DIRECTORY,output=>walk(child,item,full+'/',output));
          }else walk(child,item,full+'/',null);
        }else{
          const inspect=output=>verifyFile(child,item,buffer,output);
          if(copying)using(entry(target,name),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,output=>{
            inspect(output);
            if(readerGid!==null)fs.fchownSync(output,0,readerGid);
            fs.fchmodSync(output,readerGid===null?0o400:0o440);fs.fsyncSync(output);
          });
          else{inspect(null);if(refresh)fs.fsyncSync(child);}
          bytes+=Number(item.size_bytes);
        }
        const after=attributes(child);
        need(after.ctimeNs===stat.ctimeNs&&identity(fs.lstatSync(entry(fd,name),{bigint:true}))===identity(stat),'preparation_storage_changed');
      });
    }
    if(copying&&readerGid===null)fs.fchmodSync(target,0o500);
    if(readerGid!==null&&target!==copyTo){fs.fchownSync(target,0,readerGid);fs.fchmodSync(target,0o550);}
  }
  walk(root,tree,'',copyTo);
  need(attributes(root).ctimeNs===anchor.ctimeNs,'preparation_storage_changed');
  return {tree_identity:'sha256:'+sum.digest('hex'),directories:dirs,bytes};
}

function flushDirectories(root,tree){
  for(const [name,item] of tree){
    if(item instanceof Map)using(entry(root,name),readFlags|O_DIRECTORY,child=>flushDirectories(child,item));
  }
  fs.fsyncSync(root);
}

function withRoot(parentDirectory,id,fn){
  need(safeName(id),'preparation_linux_directory');
  return withProtectedDirectory(parentDirectory,(parent,parentStat,assertParent)=>fn({parent,parentStat,assertParent,target:entry(parent,id)}));
}

function observe(root,parentStat,absolute){
  const stat=attributes(root);
  need(stat.isDirectory()&&stat.uid===parentStat.uid&&stat.dev===parentStat.dev&&mode(stat)===0o500n,'preparation_linux_permissions');
  return {path:absolute,root_identity:identity(stat),parent_identity:identity(parentStat),writer_uid:String(stat.uid),
    storage_identity:{format:'linux-content-filesystem/1',device:String(stat.dev),filesystem_type:fs.statfsSync(descriptor(root)).type.toString(16)}};
}

function flushReport(observed,summary,inventory){
  return {...linuxFlush,file_count:inventory.files.length,directory_count:summary.directories,parent_identity:observed.parent_identity,completed:true};
}

export function prepareLinuxContent({source_directory,parent_directory,directory_id,inventory,reader_sids}){
  need(Array.isArray(reader_sids)&&reader_sids.length===0,'preparation_policy');
  return checked(()=>withRoot(parent_directory,directory_id,({parent,parentStat,assertParent,target})=>{
    const tree=inventoryTree(inventory);
    return withProtectedDirectory(source_directory,(source,_stat,assertSource)=>{
      fs.mkdirSync(target,{mode:0o700});
      return using(target,readFlags|O_DIRECTORY,output=>{
        scan(source,tree,{copyTo:output});assertSource();
        const description=observe(output,parentStat,path.join(parent_directory,directory_id));
        const summary=scan(output,tree);flushDirectories(output,tree);fs.fsyncSync(parent);assertParent();
        need(identity(fs.lstatSync(target,{bigint:true}))===description.root_identity,'preparation_storage_changed');
        return {format:'leafseamer-content-preparation/1',content_directory:directory_id,root_identity:description.root_identity,
          storage_identity:description.storage_identity,metadata_flush:flushReport(description,summary,inventory),
          writer_uid:description.writer_uid,reader_sids:[],access_profile:'linux-installer-only/1',tree_identity:summary.tree_identity,
          file_count:inventory.files.length,payload_bytes:String(summary.bytes),file_flush_completed:true,directory_durability:'unqualified',sealed:false};
      });
    });
  }));
}

export function withLinuxPreparedContent(parentDirectory,prepared,validated,fn,{refresh=false,stage=null}={}){
  const report=prepared.body,inventory=validated.report.inventory,tree=inventoryTree(inventory);
  return checked(()=>withRoot(parentDirectory,prepared.preparation_id,({parent,parentStat,assertParent,target})=>using(target,readFlags|O_DIRECTORY,root=>{
    const observed=observe(root,parentStat,path.join(parentDirectory,prepared.preparation_id));
    need(report.access_profile==='linux-installer-only/1'&&same(report.reader_sids,[])&&observed.writer_uid===report.writer_uid&&
      observed.root_identity===report.root_identity&&observed.parent_identity===report.metadata_flush.parent_identity&&
      same(observed.storage_identity,report.storage_identity),'preparation_storage_changed');
    const summary=stage===null?scan(root,tree,{refresh}):withStage(stage,0o700n,target=>{
      need(fs.readdirSync(descriptor(target)).length===0,'preparation_stage_conflict');
      const copied=scan(root,tree,{copyTo:target,readerGid:stage.reader_gid});
      flushDirectories(target,tree);
      return copied;
    });
    if(refresh){flushDirectories(root,tree);fs.fsyncSync(parent);}
    assertParent();
    need(summary.tree_identity===report.tree_identity&&identity(fs.lstatSync(target,{bigint:true}))===observed.root_identity,'preparation_storage_changed');
    const read=(relative,limit)=>{
      const parts=relative.split('/'),file=inventory.files.find(candidate=>candidate.path===relative);
      need(file&&parts.every(safeName),'content_path');
      const open=(fd,index)=>{
        const isFile=index===parts.length-1;
        return using(entry(fd,parts[index]),readFlags|(isFile?0:O_DIRECTORY),input=>{
          const stat=attributes(input);
          need(stat.dev===parentStat.dev&&stat.uid===parentStat.uid&&
            (isFile?stat.isFile()&&stat.nlink===1n&&mode(stat)===0o400n:mode(stat)===0o500n),'content_permissions');
          return isFile?verifyFile(input,file,Buffer.alloc(65536),null,limit):open(input,index+1);
        });
      };
      return open(root,0);
    };
    const result=fn(observed,refresh?flushReport(observed,summary,inventory):null,read);
    need(!result||typeof result.then!=='function','preparation_async_observation');return result;
  })));
}

function withStage(stage,permissions,fn){
  return withProtectedDirectory(stage.directory,(parent,stat,assertParent)=>{
    const name=path.basename(stage.path),target=entry(parent,name);
    need(identity(stat)===stage.parent_identity&&safeName(name)&&stage.path===path.join(stage.directory,name),'preparation_stage_identity');
    return using(target,readFlags|O_DIRECTORY,(fd)=>{
      const current=attributes(fd);
      need(identity(current)===stage.root_identity&&current.dev===stat.dev&&current.uid===0n&&mode(current)===permissions&&
        (permissions===0o700n||current.gid===BigInt(stage.reader_gid)),'preparation_stage_identity');
      assertParent();return fn(fd,target);
    });
  },0o711n);
}

// 私有准备根在持久资格重核后才可由指定Worker组读取。
export function createLinuxWorkerStage({directory,uid,gid}){
  need(process.platform==='linux'&&process.geteuid()===0&&[uid,gid].every(value=>Number.isInteger(value)&&value>0&&value<4294967295),
    'preparation_stage_account');
  return checked(()=>withProtectedDirectory(directory,(parent,stat)=>{
    const name='worker-'+crypto.randomUUID(),target=entry(parent,name);
    fs.mkdirSync(target,{mode:0o700});
    const stage=Object.freeze({directory,path:path.join(directory,name),parent_identity:identity(stat),
      root_identity:identity(fs.lstatSync(target,{bigint:true})),reader_uid:uid,reader_gid:gid});
    let published=false,discarded=false;
    return Object.freeze({stage,publish(){
      checked(()=>withStage(stage,0o700n,fd=>{fs.fchownSync(fd,0,gid);fs.fchmodSync(fd,0o550);}));published=true;
    },assertCurrent(){
      need(published&&!discarded,'preparation_stage_unavailable');checked(()=>withStage(stage,0o550n,()=>{}));
    },discard(){
      if(!discarded){
        checked(()=>withStage(stage,published?0o550n:0o700n,(_fd,targetPath)=>fs.rmSync(targetPath,{recursive:true})));
        discarded=true;
      }
    }});
  },0o711n));
}
