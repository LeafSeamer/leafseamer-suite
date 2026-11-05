import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import {captureInstallationPeer,createInstallationChannel,installationChannelPeer} from '../dist/local-peer.mjs';
async function child(t){
  const value=spawn(process.execPath,[fileURLToPath(new URL('./fixtures/installation-peer-child.mjs',import.meta.url))],{stdio:['ignore','pipe','pipe','ipc'],windowsHide:true});
  const closed=once(value,'close');let stderr='';value.stderr.on('data',b=>{stderr+=b;});const messages=[];value.on('message',m=>messages.push(m));
  await new Promise((resolve,reject)=>{value.once('message',resolve);value.once('error',reject);value.once('exit',()=>reject(new Error(stderr||'child_exit')));});
  t.after(async()=>{if(value.exitCode===null&&value.signalCode===null)value.kill();await closed;});return {value,closed,messages};
}
test('Windows实际命名管道固定双向进程实例并传输完整有界字节，普通对象不能冒充连接',{skip:process.platform!=='win32',timeout:15000},async t=>{
  const c=await child(t),peer=captureInstallationPeer(c.value.pid),name='\\\\.\\pipe\\LeafSeamer.Install.'+crypto.randomUUID();
  const server=createInstallationChannel({name,peer,server:true});t.after(()=>server.close());
  assert.throws(()=>createInstallationChannel({name,peer,server:true}),{code:'peer_endpoint_unavailable'});
  assert.throws(()=>installationChannelPeer({}),{code:'peer_channel_required'});
  c.value.send({type:'connect',name,server_pid:process.pid});await server.ready;
  const actual=installationChannelPeer(server);assert.equal(actual.pid,c.value.pid);assert.equal(actual.creation_time,peer.descriptor.creation_time);assert.match(actual.user_sid,/^S-1-/);
  const bytes=crypto.randomBytes(65536);await server.send(bytes);assert.deepEqual(await server.receive(),bytes);
  c.value.kill();await c.closed;
  assert.throws(()=>installationChannelPeer(server));server.close();assert.throws(()=>installationChannelPeer(server));
});
test('同用户错误进程、错误服务端和重新占名不能通过已固定进程检查',{skip:process.platform!=='win32',timeout:15000},async t=>{
  const c=await child(t),other=await child(t),name='\\\\.\\pipe\\LeafSeamer.Install.'+crypto.randomUUID();
  const server=createInstallationChannel({name,peer:captureInstallationPeer(c.value.pid),server:true});t.after(()=>server.close());
  other.value.send({type:'connect',name,server_pid:process.pid});await assert.rejects(server.ready,{code:'peer_process_mismatch'});
  const name2='\\\\.\\pipe\\LeafSeamer.Install.'+crypto.randomUUID(),second=createInstallationChannel({name:name2,peer:captureInstallationPeer(c.value.pid),server:true});t.after(()=>second.close());
  c.value.send({type:'connect',name:name2,server_pid:other.value.pid});
  await new Promise(resolve=>{const onMessage=m=>{if(m.type==='closed'){c.value.off('message',onMessage);resolve();}};c.value.on('message',onMessage);});
  assert.ok(c.messages.some(m=>m.code==='peer_process_mismatch'));
});
