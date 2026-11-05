import fs from 'node:fs';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {requireValue as need,InstallationError} from './import-input.mjs';
const require=createRequire(import.meta.url),peers=new WeakMap(),channels=new WeakMap();let native;
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function implementation(){
  if(native)return native;
  need(process.platform==='win32'&&process.arch==='x64','peer_platform_unavailable');
  const manifest=JSON.parse(fs.readFileSync(new URL('./native/installation-peer-manifest.json',import.meta.url)));
  const binary=new URL('./native/leafseamer_installation_peer.node',import.meta.url);
  need(manifest.format==='leafseamer-installation-peer/1'&&manifest.platform===process.platform&&manifest.arch===process.arch&&manifest.node_version===process.versions.node&&
    hash(fs.readFileSync(binary))===manifest.binary_sha256,'peer_native_artifact');
  native=require(fileURLToPath(binary));return native;
}
export function captureInstallationPeer(pid){
  need(Number.isSafeInteger(pid)&&pid>0&&pid<=4294967295,'peer_argument');
  const module=implementation(),handle=module.capture(pid),descriptor=module.describe(handle),value=Object.freeze({descriptor});peers.set(value,handle);return value;
}
export function createInstallationChannel({name,peer,server}){
  need(peers.has(peer)&&typeof server==='boolean'&&typeof name==='string','peer_argument');
  const module=implementation(),handle=module.endpoint(name,peers.get(peer),server),queue=[];
  let closed=false,connected=false,failure=null,timer,receiver=null,writer=null,resolveReady,rejectReady;
  const ready=new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;});ready.catch(()=>{});
  const handshake=setTimeout(()=>finish(new InstallationError('peer_connect_timeout')),5000);
  function finish(error=new InstallationError('peer_closed')){
    if(closed)return;closed=true;failure=error;clearInterval(timer);clearTimeout(handshake);module.close(handle);queue.length=0;rejectReady(error);
    for(const pending of [receiver,writer])if(pending){clearTimeout(pending.timeout);pending.reject(error);}receiver=null;writer=null;
  }
  function pending(kind){
    let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const value={resolve,reject,timeout:setTimeout(()=>finish(new InstallationError('peer_'+kind+'_timeout')),5000)};return {promise,value};
  }
  timer=setInterval(()=>{
    if(closed)return;
    try{
      const state=module.poll(handle);
      if(state.connected&&!connected){connected=true;clearTimeout(handshake);resolveReady();}
      if(state.writable&&writer){const completed=writer;writer=null;clearTimeout(completed.timeout);completed.resolve();}
      if(state.packet.length){
        if(receiver){const pending=receiver;receiver=null;clearTimeout(pending.timeout);pending.resolve(state.packet);}
        else{need(queue.length<16,'peer_receive_capacity');queue.push(state.packet);}
      }
    }catch(error){finish(error);}
  },5);
  const value=Object.freeze({
    ready,
    async send(bytes){await ready;if(closed)throw failure;need(Buffer.isBuffer(bytes)&&bytes.length>0&&bytes.length<=65536&&!writer,'peer_send_state');
      const operation=pending('write');writer=operation.value;try{module.send(handle,bytes);}catch(error){finish(error);}return operation.promise;},
    async receive(){await ready;if(closed)throw failure;need(!receiver,'peer_receive_state');if(queue.length)return queue.shift();const operation=pending('read');receiver=operation.value;return operation.promise;},
    close:finish
  });
  channels.set(value,{source(sourceHandle){
    need(!closed&&connected&&server,'peer_server_required');const fd=module.duplicateSource(handle,sourceHandle);let released=false;
    return Object.freeze({fd,close(){if(released)return;released=true;fs.closeSync(fd);}});
  },assert(){
    try{if(closed)throw failure;need(connected&&server,'peer_server_required');module.check(handle);return module.describe(peers.get(peer));}
    catch(error){finish(error);throw error instanceof InstallationError?error:new InstallationError(error.code??'peer_unavailable');}
  }});return value;
}
export function installationChannelPeer(channel){need(channels.has(channel),'peer_channel_required');return channels.get(channel).assert();}
export function installationSourceHandle(fd){need(Number.isInteger(fd)&&fd>=0,'peer_argument');return implementation().sourceHandle(fd);}
export function installationChannelSource(channel,handle){installationChannelPeer(channel);return channels.get(channel).source(handle);}
export function initializeInstallationContentDirectory(directory){try{implementation().initializeContentDirectory(directory);}catch(error){throw new InstallationError(error.code??'preparation_unavailable');}}
export function installationObservationTick(){return BigInt(implementation().materializationTick());}
// 仅供安装器的独立静态物化worker使用，不是设备或第三方扩展API。
export function installationContentPlatform(){const module=implementation();return Object.freeze(Object.fromEntries(
  ['contentPin','contentVerify','contentRead','contentClose','prepareRoot','reopenPreparedRoot','protectObject','preparedDescribe','preparedClose','flushPreparedObject','flushPreparedParent'].map(name=>[name,module[name]])));}
