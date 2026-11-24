import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {once} from 'node:events';
import {DatabaseSync} from 'node:sqlite';
import {setTimeout as delay} from 'node:timers/promises';
import test from 'node:test';
import {createInstallationStore,openInstallationStore} from '../dist/installation-store.mjs';
import {linuxContainerCgroup} from '../dist/linux-cgroup-retirement.mjs';

const enabled=process.platform==='linux'&&process.env.LEAFSEAMER_TEST_NATIVE_CGROUP==='1';
const id=()=>crypto.randomUUID();
const hash=data=>'sha256:'+crypto.createHash('sha256').update(data).digest('hex');

test('原生成员只在意图、闭锁观察和释放请求持久化后执行，重开不重放',{
  skip:!enabled,timeout:25000
},async t=>{
  assert.equal(process.getuid(),0);
  const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-member-ledger-')),directories=[];
  const root=path.join(scratch,'installation'),image=path.join(scratch,'app');
  fs.chmodSync(scratch,0o755);
  fs.mkdirSync(root,{mode:0o700});
  fs.copyFileSync(process.env.LEAFSEAMER_TEST_NATIVE_MEMBER_FIXTURE,image);
  fs.chmodSync(image,0o755);
  const imageDigest=hash(fs.readFileSync(image));
  let store,journal;
  const vacant=group=>!/^populated 1$/m.test(fs.readFileSync(group+'/cgroup.events','utf8'));
  async function empty(group){
    for(let i=0;i<60&&!vacant(group);++i)await delay(20);
    assert.equal(vacant(group),true);
  }
  t.after(async()=>{
    journal?.close();
    store?.close();
    for(const group of directories.filter(group=>group.endsWith('/core'))){
      fs.writeFileSync(group+'/cgroup.kill','1');
      await empty(group);
    }
    for(const group of directories.reverse())fs.rmdirSync(group);
    assert.equal(path.dirname(scratch),os.tmpdir());
    fs.rmSync(scratch,{recursive:true,force:true});
  });
  function plan(role){
    const generation_id=id(),{groupPath}=linuxContainerCgroup({driver:'cgroupfs',generationId:generation_id,role});
    const parent='/sys/fs/cgroup'+groupPath,group=parent+'/core',sibling=parent+'/sibling';
    for(const directory of [parent,group,sibling]){fs.mkdirSync(directory);directories.push(directory);}
    return {group,spec:{role,generation_id,driver:'cgroupfs',launch_id:id(),service_id:id(),database_instance_id:id(),
      uid:65534,gid:65534,image_path:image,image_sha256:imageDigest,args:[group+'/cgroup.procs',sibling+'/cgroup.procs']}};
  }
  const denied=plan('controller'),accepted=plan('seamer');
  createInstallationStore(root);
  store=openInstallationStore(root);
  assert.throws(()=>store.openLinuxMemberJournal(()=>true),{code:'linux_member_unavailable'});
  store.initializeLinuxMemberJournal();
  assert.throws(()=>store.initializeLinuxMemberJournal(),{code:'linux_member_initialized'});
  const observations=[];
  journal=store.openLinuxMemberJournal(record=>{
    assert.deepEqual(journal.lookup(record.intent.launch_id),record);
    observations.push([record.intent.role,record.phase]);
    if(record.phase==='reserved')assert.equal(vacant('/sys/fs/cgroup'+record.detail.group_path),true);
    if(record.phase==='created_closed')assert.ok(record.detail.leader.pid>1);
    return record.intent.role!=='controller'||record.phase!=='created_closed';
  });
  assert.throws(()=>store.close(),{code:'linux_member_in_use'});
  await assert.rejects(journal.launch(denied.spec),{code:'linux_member_authorization'});
  await empty(denied.group);
  const held=journal.lookup(denied.spec.launch_id);
  assert.equal(held.phase,'created_closed');
  assert.deepEqual(await journal.launch(denied.spec),{record:held,bootstrap:null});
  await assert.rejects(journal.launch({...denied.spec,uid:65533}),{code:'linux_member_launch_conflict'});
  const other=plan('controller');
  await assert.rejects(journal.launch(other.spec),{code:'linux_member_previous_unretired'});
  assert.equal(vacant(other.group),true);

  const {record,bootstrap}=await journal.launch(accepted.spec);
  assert.equal(record.phase,'executed_closed');
  assert.equal(record.detail.group_path,accepted.group.slice('/sys/fs/cgroup'.length));
  assert.deepEqual(observations,[
    ['controller','reserved'],['controller','created_closed'],['seamer','reserved'],['seamer','created_closed']
  ]);
  const [entered]=await once(bootstrap,'data',{signal:AbortSignal.timeout(2000)});
  assert.equal(entered.toString(),'application_entered\n');
  assert.deepEqual(await journal.launch(accepted.spec),{record,bootstrap:null});
  bootstrap.write('Q');
  await empty(accepted.group);
  journal.close();store.close();journal=store=null;

  const db=new DatabaseSync(path.join(root,'linux-member.db'),{readOnly:true});
  try{
    const phases=db.prepare('SELECT role,revision,phase FROM linux_member_event ORDER BY role,revision').all().map(row=>[row.role,row.revision,row.phase]);
    assert.deepEqual(phases,[['controller',1,'reserved'],['controller',2,'created_closed'],['seamer',1,'reserved'],
      ['seamer',2,'created_closed'],['seamer',3,'release_requested'],['seamer',4,'executed_closed']]);
  }finally{db.close();}
  store=openInstallationStore(root);
  journal=store.openLinuxMemberJournal(()=>{throw new Error('an original lookup must not launch');});
  assert.deepEqual(await journal.launch(accepted.spec),{record,bootstrap:null});
  assert.deepEqual(await journal.launch(denied.spec),{record:held,bootstrap:null});
  journal.close();store.close();journal=store=null;

  const damagedRoot=path.join(scratch,'damaged-installation'),damaged=plan('controller');
  fs.mkdirSync(damagedRoot,{mode:0o700});
  createInstallationStore(damagedRoot);
  store=openInstallationStore(damagedRoot);
  store.initializeLinuxMemberJournal();
  const marker=path.join(damagedRoot,'linux-member.marker'),temporarilyAbsent=marker+'.held';
  journal=store.openLinuxMemberJournal(record=>{
    if(record.phase==='created_closed')fs.renameSync(marker,temporarilyAbsent);
    return true;
  });
  await assert.rejects(journal.launch(damaged.spec),{code:'linux_member_file_identity'});
  await empty(damaged.group);
  assert.throws(()=>journal.lookup(damaged.spec.launch_id),{code:'linux_member_unavailable'});
  fs.renameSync(temporarilyAbsent,marker);
  journal.close();store.close();journal=store=null;
  store=openInstallationStore(damagedRoot);
  journal=store.openLinuxMemberJournal(()=>false);
  const original=journal.lookup(damaged.spec.launch_id);
  assert.equal(original.phase,'created_closed');
  assert.deepEqual(await journal.launch(damaged.spec),{record:original,bootstrap:null});
});
