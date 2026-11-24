import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {once} from 'node:events';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {openLinuxComposeChannel} from '../dist/linux-compose-channel.mjs';
import {linuxContainerCgroup,observeLinuxComposeCore,readLinuxCgroupHost,readLinuxCgroupLeader} from '../dist/linux-cgroup-retirement.mjs';

const image=process.env.LEAFSEAMER_COMPOSE_CONTROLLER_IMAGE;
const dockerHost=process.env.LEAFSEAMER_TEST_DOCKER_SOCKET;
const roles=['controller','seamer'];

test('实际 Compose 进程经核验的 Unix 对端继承 FD 3，宿主断连后关闭',{
  skip:process.platform!=='linux'||!dockerHost||!image,timeout:90000
},async t=>{
  assert.equal(process.getuid(),0);
  assert.equal(process.env.DOCKER_HOST,'unix://'+dockerHost);
  assert.match(image,/^sha256:[a-f0-9]{64}$/);
  const generationId=crypto.randomUUID(),project='leafseamer-channel-'+generationId.slice(0,8);
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-channel-'));
  const uid=65534,gid=65534,driver='cgroupfs',host=readLinuxCgroupHost();
  const paths=[],channels={},services={};
  const file=path.join(root,'compose.json');
  function docker(...args){
    const result=spawnSync('docker',['--host','unix://'+dockerHost,...args],{encoding:'utf8',timeout:40000});
    assert.equal(result.status,0,result.stderr||result.error?.message);
    return result.stdout.trim();
  }
  const compose=(...args)=>docker('compose','--project-name',project,'--file',file,...args);
  t.after(async()=>{
    for(const channel of Object.values(channels))channel.close();
    await Promise.all(Object.values(channels).map(channel=>channel.ended));
    if(fs.existsSync(file))compose('down','--timeout','1');
    for(const group of paths)fs.rmdirSync(group);
    assert.equal(path.dirname(root),os.tmpdir());
    fs.rmSync(root,{recursive:true,force:true});
  });
  fs.chmodSync(root,0o755);
  const helper=fileURLToPath(new URL('../dist/native/leafseamer_linux_compose_channel',import.meta.url));
  const child=["import {Socket} from 'node:net';",
    'const socket=new Socket({fd:3,readable:true,writable:true});',
    "socket.on('data',bytes=>socket.write(bytes));",
    "socket.once('end',()=>{socket.destroy();});"].join('\n');
  for(const role of roles){
    const {parent,groupPath}=linuxContainerCgroup({driver,generationId,role});
    const group='/sys/fs/cgroup'+groupPath;
    fs.mkdirSync(group);paths.push(group);
    const directory=path.join(root,role);
    fs.mkdirSync(directory,{mode:0o755});
    const channel=openLinuxComposeChannel({directory,uid,gid,timeoutMs:20000});
    channels[role]=channel;
    await channel.ready;
    services[role]={image,user:uid+':'+gid,network_mode:'none',read_only:true,cgroup:'private',cgroup_parent:parent,
      pull_policy:'never',cap_drop:['ALL'],security_opt:['no-new-privileges:true'],restart:'no',
      entrypoint:['/launcher','connect','/channel/bootstrap.sock','0','--','/usr/local/bin/node','--input-type=module','-e',child],
      volumes:[{type:'bind',source:helper,target:'/launcher',read_only:true},
        {type:'bind',source:directory,target:'/channel',read_only:true}]};
  }
  const parent=path.dirname(channels.controller.socketPath);
  fs.chmodSync(parent,0o775);
  try{
    const denied=spawnSync('docker',['--host','unix://'+dockerHost,'run','--rm','--network','none','--pull','never',
      '--user',uid+':'+gid,'--cap-drop','ALL','--security-opt','no-new-privileges',
      '--mount','type=bind,source='+helper+',target=/launcher,readonly',
      '--mount','type=bind,source='+parent+',target=/channel,readonly','--entrypoint','/launcher',
      image,...services.controller.entrypoint.slice(1)],{encoding:'utf8',timeout:10000});
    assert.equal(denied.status,1,denied.stderr||denied.error?.message);
  }finally{fs.chmodSync(parent,0o755);}
  fs.writeFileSync(file,JSON.stringify({services}),{mode:0o600});
  compose('up','--detach','--pull','never');
  function state(id){return JSON.parse(docker('container','inspect',id))[0].State;}
  const ids={},expected={};
  for(const role of roles){
    const containerId=compose('ps','--all','--quiet',role);
    ids[role]=containerId;
    const leader=readLinuxCgroupLeader(state(containerId).Pid);
    expected[role]=observeLinuxComposeCore({driver,generationId,role,host,leader,containerId,uid,gid});
  }
  const controller=channels.controller,seamer=channels.seamer;
  await assert.rejects(seamer.accept({driver,generationId,role:'controller',host,expected:expected.controller}),{code:'compose_channel_peer'});
  await seamer.ended;
  const socket=await controller.accept({driver,generationId,role:'controller',host,expected:expected.controller});
  await assert.rejects(controller.accept({driver,generationId,role:'controller',host,expected:expected.controller}),{code:'compose_channel_closed'});
  const original=Buffer.concat([Buffer.from('assignment bytes\n'),crypto.randomBytes(16384)]);
  const signal=AbortSignal.timeout(5000);
  socket.write(original);
  const returned=[];
  let length=0;
  while(length<original.length){
    const [bytes]=await once(socket,'data',{signal});
    returned.push(bytes);length+=bytes.length;
  }
  assert.deepEqual(Buffer.concat(returned),original);
  assert.equal(state(ids.controller).Running,true);
  socket.destroy();
  await controller.ended;
  for(const role of roles){
    const until=performance.now()+5000;
    let current=state(ids[role]);
    while(current.Running&&performance.now()<until){await delay(100);current=state(ids[role]);}
    assert.equal(current.Running,false);
    assert.equal(current.ExitCode,0);
    assert.equal(fs.existsSync(channels[role].socketPath),false);
  }
});
