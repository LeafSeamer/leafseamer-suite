import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {canonical,requireValue as need} from './import-input.mjs';
import {observeLinuxComposeCore} from './linux-cgroup-retirement.mjs';
import {pinLinuxHelper} from './linux-native-artifact.mjs';

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

function openChannel({directory,name,uid,gid,timeoutMs,upstream=null,expectedPid=null}){
  need(process.platform==='linux'&&nonRoot(uid)&&nonRoot(gid)&&uid!==process.geteuid()&&
    Number.isInteger(timeoutMs)&&timeoutMs>0&&timeoutMs<=60000,'compose_channel_options');
  const parent=protectedDirectory(directory),socketPath=path.join(directory,name);
  need(Buffer.byteLength(socketPath)<=107&&!fs.lstatSync(socketPath,{throwIfNoEntry:false}),'compose_channel_path');
  const pinned=pinLinuxHelper(helper,manifest,'leafseamer-linux-compose-channel/1');
  let child;
  try{
    const args=[expectedPid===null?'listen':'listen-worker',socketPath,String(uid),String(gid)];
    if(expectedPid!==null)args.push(String(expectedPid));
    child=spawn('/proc/self/fd/4',args,{
      stdio:['pipe','pipe','ignore',upstream??'pipe',pinned.fd],env:{LANG:'C',LC_ALL:'C',PATH:'/usr/bin:/bin'}
    });
  }finally{fs.closeSync(pinned.fd);}
  const socket=child.stdio[3],read=controlFrames(child.stdout);
  for(const handle of [child,child.stdin,child.stdout,socket])handle?.on('error',()=>{});
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
    closed=true;clearTimeout(timer);child.stdin.destroy();socket?.destroy();
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
    if(expectedPid!==null)clearTimeout(timer);
  })();
  ready.catch(close);
  return Object.freeze({socketPath,ready,ended,close,
    async accept(checkPeer){
      need(!closed&&!claimed,'compose_channel_closed');
      claimed=true;
      try{
        await ready;
        const peer=(await read()).match(/^peer ([1-9][0-9]{0,9})$/);
        need(!closed&&peer,'compose_channel_peer');checkPeer(Number(peer[1]));
        checkBinding();
        await new Promise((resolve,reject)=>child.stdin.write('A',error=>error?reject(error):resolve()));
        need(await read()==='opened'&&!closed,'compose_channel_closed');
        clearTimeout(timer);
        return socket;
      }catch(error){close();throw error;}
    }
  });
}

// `expected` 由宿主从已核验的 Docker 运行代取得，连接方不提供自己的启动身份。
export function openLinuxComposeChannel({directory,uid,gid,timeoutMs}={}){
  const channel=openChannel({directory,uid,gid,timeoutMs,name:'bootstrap.sock'});
  return Object.freeze({...channel,accept(scope={}){
    const {driver,generationId,role,host,expected}=structuredClone(scope);
    return channel.accept(pid=>{
      need(pid===expected?.leader?.pid,'compose_channel_peer');
      const observed=observeLinuxComposeCore({driver,generationId,role,host,leader:expected.leader,
        containerId:expected.container_id,uid,gid});
      need(same(observed,expected),'compose_channel_peer');
    });
  }});
}

export function openLinuxWorkerChannel({directory,memberBootId,purpose,uid,gid,corePid,timeoutMs,upstream,assertCurrent}){
  need(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$(?![\s\S])/.test(memberBootId)&&
    ['module','execution'].includes(purpose)&&Number.isInteger(corePid)&&corePid>1&&upstream&&!upstream.destroyed&&
    typeof assertCurrent==='function','linux_worker_channel');
  const channel=openChannel({directory,name:memberBootId+'.'+purpose,uid,gid,timeoutMs,upstream,expectedPid:corePid});
  void channel.accept(pid=>{need(pid===corePid,'compose_channel_peer');assertCurrent();}).catch(channel.close);
  return channel;
}

export function openLinuxInstallationChannel({directory,uid,gid,corePid,timeoutMs,assertCurrent}){
  need(Number.isInteger(corePid)&&corePid>1&&typeof assertCurrent==='function','linux_installation_channel');
  const channel=openChannel({directory,name:'installation.sock',uid,gid,timeoutMs,expectedPid:corePid});
  const peer=channel.accept(pid=>{need(pid===corePid,'compose_channel_peer');assertCurrent();});
  peer.catch(channel.close);
  return Object.freeze({...channel,peer});
}

export function openLinuxReferenceChannel({directory,uid,gid,corePid,timeoutMs,provider,coreReceiptId}){
  need(Number.isInteger(corePid)&&corePid>1&&provider?.collector&&!provider.collector.destroyed,'compose_reference_channel');
  const {intent,descriptor,receipt,process_observation}=provider.admission;
  const preamble=canonical({format:'leafseamer-linux-reference-admission/1',core_receipt_id:coreReceiptId,
    provider:{intent,descriptor,receipt,process_observation}})+'\n';
  need(Buffer.byteLength(preamble)<=16385,'compose_reference_channel');
  const channel=openChannel({directory,name:'reference.sock',uid,gid,timeoutMs,expectedPid:corePid});
  const timer=setTimeout(channel.close,timeoutMs);timer.unref();
  void channel.ended.then(()=>clearTimeout(timer));
  void channel.accept(pid=>{need(pid===corePid,'compose_channel_peer');provider.assertCurrent();}).then(async socket=>{
    socket.once('end',channel.close).once('close',channel.close).once('error',channel.close);
    provider.collector.once('end',channel.close).once('close',channel.close).once('error',channel.close);
    await new Promise((resolve,reject)=>socket.write(preamble,error=>error?reject(error):resolve()));
    provider.assertCurrent();
    provider.collector.pipe(socket,{end:false});
    socket.pipe(provider.collector,{end:false});
    clearTimeout(timer);
  }).catch(channel.close);
  return channel;
}
