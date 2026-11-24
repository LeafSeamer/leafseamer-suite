import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import {spawn,spawnSync} from 'node:child_process';
import {once} from 'node:events';
import os from 'node:os';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import test from 'node:test';
import {linuxContainerCgroup,openLinuxCgroupRetirement,readLinuxCgroupHost,readLinuxCgroupLeader} from '../dist/linux-cgroup-retirement.mjs';

test('Compose 的 cgroupfs 和 systemd 父组按服务与启动代区分',()=>{
  const generationId='11111111-2222-4333-8444-555555555555';
  const controller='leafseamer_11111111222243338444555555555555_controller';
  const seamer='leafseamer_11111111222243338444555555555555_seamer';
  assert.deepEqual(linuxContainerCgroup({driver:'cgroupfs',generationId,role:'controller'}),{parent:'/'+controller,groupPath:'/'+controller});
  assert.deepEqual(linuxContainerCgroup({driver:'systemd',generationId,role:'seamer'}),{parent:seamer+'.slice',groupPath:'/'+seamer+'.slice'});
  for(const input of [{driver:'auto'},{generationId:'../tmp'},{role:'nginx'}]){
    assert.throws(()=>linuxContainerCgroup({driver:'cgroupfs',generationId,role:'controller',...input}),{code:'cgroup_scope'});
  }
});

test('实际 cgroup v2 保留同一父组，旧主进程退出后继续观察子组',{
  skip:process.platform!=='linux'||process.env.LEAFSEAMER_TEST_CGROUP_HOST!=='1',timeout:20000
},async t=>{
  const driver='cgroupfs',generationId=crypto.randomUUID(),host=readLinuxCgroupHost();
  const locate=role=>'/sys/fs/cgroup'+linuxContainerCgroup({driver,generationId,role}).groupPath;
  const groups=[],members=[],readers=[];
  const create=group=>{fs.mkdirSync(group);groups.push(group);return group;};
  function remove(group){fs.rmdirSync(group);groups.splice(groups.indexOf(group),1);}
  async function stop(member){
    if(member.child.exitCode===null&&member.child.signalCode===null)member.child.stdin.end();
    const timer=setTimeout(()=>member.child.kill('SIGKILL'),2000);
    try{return await member.exit;}
    finally{clearTimeout(timer);}
  }
  t.after(async()=>{
    for(const reader of readers)reader.close();
    await Promise.all(members.map(stop));
    for(const group of [...groups].reverse())remove(group);
  });
  const controller=create(locate('controller')),seamer=create(locate('seamer'));
  const main=create(controller+'/service'),childGroup=create(main+'/worker'),otherGroup=create(seamer+'/service');
  async function member(group){
    const child=spawn(process.execPath,['--eval',"process.stdin.resume();process.stdout.write('ready\\n');"],{stdio:['pipe','pipe','inherit']});
    child.stdin.on('error',()=>{});
    const entry={child,exit:once(child,'close')};
    members.push(entry);
    await Promise.race([once(child.stdout,'data'),entry.exit.then(()=>{throw new Error('fixture_exit');})]);
    fs.writeFileSync(group+'/cgroup.procs',String(child.pid));
    return entry;
  }
  const leader=await member(main),worker=await member(childGroup),unrelated=await member(otherGroup);
  const controllerProof=readLinuxCgroupLeader(leader.child.pid);
  const seamerProof=readLinuxCgroupLeader(unrelated.child.pid);
  const expected={driver,generationId,host,role:'controller',leader:controllerProof};
  assert.throws(()=>openLinuxCgroupRetirement({...expected,leader:seamerProof}),{code:'cgroup_leader_scope'});
  assert.throws(()=>openLinuxCgroupRetirement({...expected,leader:{...controllerProof,start_ticks:'0'}}),{code:'cgroup_leader_scope'});
  assert.throws(()=>openLinuxCgroupRetirement({...expected,host:{...host,boot_id:crypto.randomUUID()}}),{code:'cgroup_host_changed'});
  const observer=openLinuxCgroupRetirement(expected);
  readers.push(observer);
  assert.equal(observer.observe().result,'populated');
  assert.deepEqual(await stop(leader),[0,null]);
  assert.equal(observer.observe().result,'populated');
  assert.deepEqual(await stop(worker),[0,null]);
  assert.equal(observer.observe().result,'empty');
  assert.equal(unrelated.child.exitCode,null);
  assert.deepEqual(observer.observe().scope.leader,controllerProof);

  remove(childGroup);remove(main);remove(controller);
  create(controller);
  assert.equal(observer.observe().result,'indeterminate');
  assert.equal(observer.observe().result,'indeterminate');
  assert.throws(()=>openLinuxCgroupRetirement(expected));
  observer.close();
  assert.throws(()=>observer.observe(),{code:'cgroup_observer_closed'});
});

test('活主进程离开已绑定父组时保持退役未证实',{
  skip:process.platform!=='linux'||process.env.LEAFSEAMER_TEST_CGROUP_HOST!=='1',timeout:15000
},async t=>{
  const driver='cgroupfs',generationId=crypto.randomUUID(),role='controller';
  const host=readLinuxCgroupHost();
  const scope={driver,generationId,role};
  const root='/sys/fs/cgroup'+linuxContainerCgroup(scope).groupPath;
  const alternative='/sys/fs/cgroup'+linuxContainerCgroup({...scope,role:'seamer'}).groupPath;
  const childGroup=root+'/service',groups=[];
  let child,exit,observer;
  t.after(async()=>{
    observer?.close();
    if(exit){
      child.stdin.end();
      const timer=setTimeout(()=>child.kill('SIGKILL'),2000);
      try{await exit;}finally{clearTimeout(timer);}
    }
    for(const group of groups.reverse())fs.rmdirSync(group);
  });
  for(const group of [root,childGroup,alternative]){
    fs.mkdirSync(group);groups.push(group);
  }
  child=spawn(process.execPath,['--eval',"process.stdin.resume();process.stdout.write('ready\\n');"],{stdio:['pipe','pipe','inherit']});
  child.stdin.on('error',()=>{});
  exit=once(child,'close');
  await Promise.race([once(child.stdout,'data'),exit.then(()=>{throw new Error('fixture_exit');})]);
  fs.writeFileSync(childGroup+'/cgroup.procs',String(child.pid));
  observer=openLinuxCgroupRetirement({...scope,host,leader:readLinuxCgroupLeader(child.pid)});
  assert.equal(observer.observe().result,'populated');
  fs.writeFileSync(alternative+'/cgroup.procs',String(child.pid));
  assert.deepEqual(observer.observe(),{scope:observer.scope,result:'indeterminate',reason:'cgroup_leader_changed'});
  fs.writeFileSync(childGroup+'/cgroup.procs',String(child.pid));
  assert.equal(observer.observe().result,'indeterminate');
});

test('实际 systemd slice 内的已退出服务由同一父组报告为空',{
  skip:process.platform!=='linux'||process.env.LEAFSEAMER_TEST_SYSTEMD_CGROUP!=='1',timeout:15000
},async t=>{
  const scope={driver:'systemd',generationId:crypto.randomUUID(),role:'seamer'};
  const {parent,groupPath}=linuxContainerCgroup(scope);
  const unit=parent.replace(/\.slice$/,'.service');
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-cgroup-systemd-'));
  const finish=path.join(root,'finish');
  const tool=(program,args)=>{
    const result=spawnSync(program,args,{encoding:'utf8',timeout:5000});
    assert.equal(result.status,0,result.stderr||result.error?.message);
    return result.stdout;
  };
  let started=false,observer;
  t.after(()=>{
    observer?.close();
    try{if(started)tool('systemctl',['stop',unit,parent]);}
    finally{
      if(fs.existsSync(finish))fs.unlinkSync(finish);
      fs.rmdirSync(root);
    }
  });
  tool('systemd-run',['--quiet','--unit',unit,'--slice',parent,'--service-type=exec','--property=RemainAfterExit=yes',
    '/bin/sh','-c','while [ ! -e "$1" ]; do sleep 0.05; done','leafseamer-test',finish]);
  started=true;
  const pid=Number(tool('systemctl',['show','--property=MainPID','--value',unit]).trim());
  const leader=readLinuxCgroupLeader(pid);
  assert.equal(leader.group_path,groupPath+'/'+unit);
  observer=openLinuxCgroupRetirement({...scope,host:readLinuxCgroupHost(),leader});
  assert.equal(observer.observe().result,'populated');
  fs.writeFileSync(finish,'');
  const limit=performance.now()+5000;
  while(tool('systemctl',['show','--property=SubState','--value',unit]).trim()!=='exited'){
    assert.ok(performance.now()<limit);
    await delay(50);
  }
  assert.equal(observer.observe().result,'empty');
});
