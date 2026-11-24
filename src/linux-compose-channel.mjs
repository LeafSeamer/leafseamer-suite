import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {canonical,requireValue as need} from './import-input.mjs';
import {observeLinuxComposeCore} from './linux-cgroup-retirement.mjs';
import {pinLinuxHelper} from './linux-member-journal.mjs';

const helper=fileURLToPath(new URL('./native/leafseamer_linux_compose_channel',import.meta.url));
const manifest=new URL('./native/linux-compose-channel-manifest.json',import.meta.url);
const maxId=0xffffffff;
const nonRoot=value=>Number.isInteger(value)&&value>0&&value<maxId;
const same=(left,right)=>canonical(left)===canonical(right);
const sameFile=(left,right)=>left.dev===right.dev&&left.ino===right.ino;

function protectedDirectory(directory){
  need(typeof directory==='string'&&path.isAbsolute(directory)&&path.normalize(directory)===directory&&
    directory!=='/'&&!directory.endsWith('/')&&!directory.includes('\0'),'compose_channel_directory');
  const owner=BigInt(process.geteuid());
  const stat=fs.lstatSync(directory,{bigint:true});
  need(stat.uid===owner,'compose_channel_directory');
  for(let parent=directory;;parent=path.dirname(parent)){
    const entry=fs.lstatSync(parent,{bigint:true});
    const sticky=(parent==='/tmp'||parent==='/var/tmp')&&entry.uid===0n&&(entry.mode&0o1000n)!==0n;
    need(entry.isDirectory()&&(entry.uid===owner||entry.uid===0n)&&((entry.mode&0o022n)===0n||sticky),
      'compose_channel_directory');
    if(parent==='/')return stat;
  }
}

function controlFrames(stream){
  const reader=stream[Symbol.asyncIterator]();
  let pending='';
  return async function read(){
    while(!pending.includes('\n')){
      const chunk=await reader.next();
      need(!chunk.done,'compose_channel_closed');
      pending+=chunk.value.toString('ascii');
      need(pending.length<=64,'compose_channel_frame');
    }
    const end=pending.indexOf('\n'),line=pending.slice(0,end);
    pending=pending.slice(end+1);
    return line;
  };
}

// `expected` 由宿主从已核验的 Docker 运行代取得，连接方不提供自己的启动身份。
export function openLinuxComposeChannel({directory,uid,gid,timeoutMs}={}){
  need(process.platform==='linux'&&nonRoot(uid)&&nonRoot(gid)&&uid!==process.geteuid()&&
    Number.isInteger(timeoutMs)&&timeoutMs>0&&timeoutMs<=60000,'compose_channel_options');
  const parent=protectedDirectory(directory),socketPath=path.join(directory,'bootstrap.sock');
  need(Buffer.byteLength(socketPath)<=107&&!fs.lstatSync(socketPath,{throwIfNoEntry:false}),'compose_channel_path');
  const pinned=pinLinuxHelper(helper,manifest,'leafseamer-linux-compose-channel/1');
  let child;
  try{
    child=spawn('/proc/self/fd/4',['listen',socketPath,String(uid),String(gid)],{
      stdio:['pipe','pipe','ignore','pipe',pinned.fd],env:{LANG:'C',LC_ALL:'C',PATH:'/usr/bin:/bin'}
    });
  }finally{fs.closeSync(pinned.fd);}
  const socket=child.stdio[3],read=controlFrames(child.stdout);
  for(const handle of [child,child.stdin,child.stdout,socket])handle.on('error',()=>{});
  let closed=false,claimed=false,bound;
  const owner=BigInt(process.geteuid());
  const timer=setTimeout(close,timeoutMs);timer.unref();
  function checkBinding(){
    need(sameFile(parent,protectedDirectory(directory)),'compose_channel_path');
    const stat=fs.lstatSync(socketPath,{bigint:true});
    need(stat.isSocket()&&stat.uid===owner&&stat.gid===BigInt(gid)&&(stat.mode&0o777n)===0o660n&&
      (bound===undefined||sameFile(bound,stat)),'compose_channel_path');
    bound=stat;
  }
  function close(){
    if(closed)return;
    closed=true;clearTimeout(timer);child.stdin.destroy();socket.destroy();
  }
  const ended=new Promise(resolve=>child.once('close',()=>{
    close();
    if(bound){
      try{checkBinding();fs.unlinkSync(socketPath);}catch{/* 不清理身份已改变的路径。 */}
    }
    resolve();
  }));
  const ready=(async()=>{
    need(await read()==='ready'&&!closed,'compose_channel_frame');
    checkBinding();
  })();
  ready.catch(close);
  return Object.freeze({socketPath,ready,ended,close,
    async accept(scope={}){
      need(!closed&&!claimed,'compose_channel_closed');
      claimed=true;
      try{
        const {driver,generationId,role,host,expected}=structuredClone(scope);
        await ready;
        const peer=(await read()).match(/^peer ([1-9][0-9]{0,9})$/);
        need(!closed&&peer&&Number(peer[1])===expected?.leader?.pid,'compose_channel_peer');
        const observed=observeLinuxComposeCore({driver,generationId,role,host,leader:expected.leader,
          containerId:expected.container_id,uid,gid});
        need(same(observed,expected),'compose_channel_peer');
        checkBinding();
        await new Promise((resolve,reject)=>child.stdin.write('A',error=>error?reject(error):resolve()));
        need(await read()==='opened'&&!closed,'compose_channel_closed');
        clearTimeout(timer);
        return socket;
      }catch(error){close();throw error;}
    }
  });
}
