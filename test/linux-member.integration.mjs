import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import test from 'node:test';

const binary=fileURLToPath(new URL('../dist/native/leafseamer_linux_member',import.meta.url));
const enabled=process.platform==='linux'&&process.env.LEAFSEAMER_TEST_NATIVE_CGROUP==='1';

test('实际 clone3 先纳管，再释放固定制品，拒绝并发、错组与被禁用的内核路径',{
  skip:!enabled,timeout:25000
},async t=>{
  assert.equal(process.getuid(),0);
  assert.equal(fs.statfsSync('/sys/fs/cgroup').type,0x63677270);
  const fixture=process.env.LEAFSEAMER_TEST_NATIVE_MEMBER_FIXTURE;
  assert.ok(path.isAbsolute(fixture));
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-native-member-'));
  const image=path.join(root,'member');
  const scope='/sys/fs/cgroup/leafseamer_member_'+crypto.randomUUID().replaceAll('-','');
  const member=scope+'/member',sibling=scope+'/sibling';
  fs.mkdirSync(scope);
  const directories=[scope];
  const processes=[];
  t.after(async()=>{
    for(const {child} of processes)if(child.exitCode===null&&child.signalCode===null)child.kill('SIGKILL');
    for(const group of directories.slice(1)) {
      fs.writeFileSync(group+'/cgroup.kill','1');
      await empty(group);
    }
    await Promise.all(processes.map(process=>process.exit));
    for(const group of directories.reverse())fs.rmdirSync(group);
    if(fs.existsSync(image))fs.unlinkSync(image);
    fs.rmdirSync(root);
  });
  for(const group of [member,sibling]){fs.mkdirSync(group);directories.push(group);}
  function populated(group){return /^populated 1$/m.test(fs.readFileSync(group+'/cgroup.events','utf8'));}
  async function empty(group){
    for(let i=0;i<60&&populated(group);++i)await delay(15);
    assert.equal(populated(group),false);
  }
  fs.chmodSync(root,0o755);
  fs.copyFileSync(fixture,image);
  fs.chmodSync(image,0o755);
  const imageStat=fs.statSync(image,{bigint:true}),groupStat=fs.statSync(member,{bigint:true});
  function launch({inode=groupStat.ino,uid='65534',deny=false}={}){
    const argv=[member,String(groupStat.dev),String(inode),image,String(imageStat.dev),String(imageStat.ino),
      uid,'65534','--',member+'/cgroup.procs',sibling+'/cgroup.procs'];
    const leaked=fs.openSync('/dev/null','r');
    let child;
    try{child=spawn(deny?image:binary,deny?['deny-clone3',binary,...argv]:argv,{stdio:['pipe','pipe','pipe','pipe',leaked]});}
    finally{fs.closeSync(leaked);}
    let error='',application='';
    child.stderr.setEncoding('utf8').on('data',text=>{error+=text;});
    child.stdio[3].setEncoding('utf8').on('data',text=>{application+=text;});
    const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
    child.stdin.on('error',()=>{});
    child.stdio[3].on('error',()=>{});
    const exit=once(child,'close'),run={child,exit,lines,error:()=>error,application:()=>application};
    processes.push(run);
    return run;
  }
  async function frame(run){
    const row=await run.lines.next();
    assert.equal(row.done,false,run.error());
    return JSON.parse(row.value);
  }
  async function rejected(run,reason){
    assert.deepEqual(await run.exit,[1,null]);
    assert.equal(run.error().trim(),reason);
    assert.equal(run.application(),'');
    assert.equal((await run.lines.next()).done,true);
  }
  await rejected(launch({inode:groupStat.ino+1n}),'linux_member_group');
  await rejected(launch({uid:'0'}),'linux_member_inputs');
  await rejected(launch({deny:true}),'linux_member_clone');
  const scopeMode=fs.statSync(scope).mode&0o777;
  fs.chmodSync(scope,0o777);
  try{await rejected(launch(),'linux_member_group');}
  finally{fs.chmodSync(scope,scopeMode);}
  await empty(member);

  const concurrent=[launch(),launch()];
  const first=await Promise.all(concurrent.map(run=>run.lines.next()));
  assert.equal(first.filter(row=>!row.done).length,1);
  const winner=first.findIndex(row=>!row.done);
  const closed=concurrent[winner],created=JSON.parse(first[winner].value);
  await rejected(concurrent[1-winner],'linux_member_group');
  assert.equal(created.phase,'created_closed');
  assert.equal(created.group_inode,String(groupStat.ino));
  assert.equal(created.image_inode,String(imageStat.ino));
  assert.equal(fs.readFileSync('/proc/'+created.pid+'/cgroup','utf8'),'0::'+member.slice('/sys/fs/cgroup'.length)+'\n');
  assert.equal(closed.application(),'');
  closed.child.stdin.end();
  assert.deepEqual(await closed.exit,[1,null]);
  assert.equal(closed.error().trim(),'linux_member_closed');
  assert.equal(closed.application(),'');
  await empty(member);

  const migrated=launch(),pending=await frame(migrated);
  fs.writeFileSync(sibling+'/cgroup.procs',String(pending.pid));
  assert.equal(populated(sibling),true);
  migrated.child.stdin.write('R');
  assert.deepEqual(await migrated.exit,[1,null]);
  assert.equal(migrated.error().trim(),'linux_member_closed');
  assert.equal(migrated.application(),'');
  await empty(sibling);

  const running=launch(),original=await frame(running);
  running.child.stdin.write('R');
  assert.deepEqual(await frame(running),{...original,phase:'executed'});
  for(let i=0;i<60&&!running.application();++i)await delay(15);
  assert.equal(running.application(),'application_entered\n');
  const status=fs.readFileSync('/proc/'+original.pid+'/status','utf8');
  assert.match(status,/^Uid:\s+65534\s+65534\s+65534\s+65534$/m);
  assert.match(status,/^Gid:\s+65534\s+65534\s+65534\s+65534$/m);
  for(const name of ['Inh','Prm','Eff','Amb'])assert.match(status,new RegExp('^Cap'+name+':\\s+0+$','m'));
  assert.match(status,/^Groups:[ \t]*$/m);
  assert.match(status,/^NoNewPrivs:\s+1$/m);
  running.child.stdio[3].write('Q');
  assert.deepEqual(await running.exit,[0,null]);
  await empty(member);

  const lost=launch();
  await frame(lost);
  lost.child.stdin.write('R');
  await frame(lost);
  lost.child.kill('SIGKILL');
  assert.deepEqual(await lost.exit,[null,'SIGKILL']);
  await empty(member);
});
