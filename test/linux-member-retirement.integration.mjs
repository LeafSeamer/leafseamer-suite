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
import {canonical} from '../dist/import-input.mjs';

const enabled=process.platform==='linux'&&process.env.LEAFSEAMER_TEST_NATIVE_CGROUP==='1';
const id=()=>crypto.randomUUID();
const hash=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');
const empty=group=>/^populated 0$/m.test(fs.readFileSync(group+'/cgroup.events','utf8'));
async function waitUntil(check){
  for(let i=0;i<100;i++){if(check())return;await delay(20);}
  assert.fail('expected cgroup state was not reached');
}

test('旧成员退出后仍等待整个子树，恢复后退役才能放行替代成员',{
  skip:!enabled,timeout:25000
},async t=>{
  assert.equal(process.getuid(),0);
  const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-member-retirement-'));
  const root=path.join(scratch,'installation'),image=path.join(scratch,'app'),directories=[];
  fs.chmodSync(scratch,0o755);fs.mkdirSync(root,{mode:0o700});
  fs.copyFileSync(process.env.LEAFSEAMER_TEST_NATIVE_MEMBER_FIXTURE,image);fs.chmodSync(image,0o755);
  let store,journal;
  t.after(async()=>{
    journal?.close();store?.close();
    for(const group of directories.filter(entry=>entry.split('/').length===5)){
      fs.writeFileSync(group+'/cgroup.kill','1');await waitUntil(()=>empty(group));
    }
    for(const group of directories.reverse())fs.rmdirSync(group);
    assert.equal(path.dirname(scratch),os.tmpdir());
    fs.rmSync(scratch,{recursive:true,force:true});
  });
  const installation=createInstallationStore(root);
  // 写入上版的原始布局与身份标记，以同一真实启动入口留下历史成员。
  const file=path.join(root,'linux-member.db'),marker=path.join(root,'linux-member.marker');
  fs.closeSync(fs.openSync(file,'wx',0o600));
  const legacy=new DatabaseSync(file),sql=fs.readFileSync(new URL('../dist/linux-member-journal.sql',import.meta.url),'utf8');
  const stat=fs.statSync(file,{bigint:true});
  const originalMarker=canonical({format:'leafseamer.linux-member-journal/1',host_installation_id:installation.host_installation_id,
    database_instance_id:installation.database_instance_id,installation_epoch:installation.installation_epoch,
    file_identity:{device:String(stat.dev),inode:String(stat.ino)},schema_digest:hash(sql)});
  try{
    legacy.exec("PRAGMA journal_mode=WAL; PRAGMA application_id=1280527437; PRAGMA user_version=1;");
    legacy.exec(sql);
    legacy.prepare('INSERT INTO linux_member_identity VALUES(1,?)').run(originalMarker);
  }finally{legacy.close();}
  fs.writeFileSync(marker,originalMarker,{mode:0o600});
  function open(){
    store=openInstallationStore(root);journal=store.openLinuxMemberJournal(()=>true);
  }
  function close(){journal.close();store.close();journal=store=null;}
  const imageDigest=hash(fs.readFileSync(image));
  function plan(role,descendant=false){
    const generation_id=id(),{groupPath}=linuxContainerCgroup({driver:'cgroupfs',generationId:generation_id,role});
    const parent='/sys/fs/cgroup'+groupPath,core=parent+'/core',sibling=parent+'/worker',nested=sibling+'/child';
    for(const group of [parent,core,sibling,nested]){fs.mkdirSync(group);directories.push(group);}
    return {parent,core,nested,intent:{role,generation_id,driver:'cgroupfs',launch_id:id(),service_id:id(),database_instance_id:id(),
      uid:65534,gid:65534,image_path:image,image_sha256:imageDigest,
      args:[core+'/cgroup.procs',sibling+'/cgroup.procs',...(descendant?['keep-descendant']:[])]}};
  }
  async function start(plan){
    const {record,bootstrap}=await journal.launch(plan.intent);
    const [message]=await once(bootstrap,'data',{signal:AbortSignal.timeout(2000)});
    return {record,bootstrap,message:message.toString()};
  }
  const former=plan('controller',true),replacement=plan('controller');
  open();
  assert.throws(()=>journal.lookupRetirement(former.intent.launch_id),{code:'linux_member_upgrade_required'});
  const old=await start(former);
  const descendant=old.message.match(/^descendant ([1-9][0-9]*)\n$/)?.[1];
  assert.ok(descendant);
  fs.writeFileSync(former.nested+'/cgroup.procs',descendant);
  close();
  await waitUntil(()=>empty(former.core));
  assert.equal(empty(former.parent),false);

  store=openInstallationStore(root);
  assert.deepEqual(store.upgradeLinuxMemberJournal(),{schema_revision:2,changed:true});
  assert.deepEqual(store.upgradeLinuxMemberJournal(),{schema_revision:2,changed:false});
  assert.equal(fs.readFileSync(marker,'utf8'),originalMarker);
  journal=store.openLinuxMemberJournal(()=>true);
  const launchId=former.intent.launch_id;
  assert.deepEqual(journal.lookup(launchId),old.record);
  assert.throws(()=>journal.observeRetirement(launchId),{code:'linux_member_intake_open'});
  const closing=journal.closeIntake(launchId);
  assert.equal(closing.phase,'closing');
  assert.deepEqual(journal.observeRetirement(launchId),closing);
  await assert.rejects(journal.launch(replacement.intent),{code:'linux_member_previous_unretired'});
  close();open();
  assert.deepEqual(journal.lookupRetirement(launchId),closing);
  assert.deepEqual(journal.observeRetirement(launchId),closing);
  journal.terminateRetirement(launchId);
  await waitUntil(()=>empty(former.parent));
  const retired=journal.observeRetirement(launchId);
  assert.equal(retired.phase,'retired');
  assert.equal(retired.evidence.populated,false);
  assert.deepEqual(retired.evidence.parent,old.record.detail.parent_group);
  assert.deepEqual(journal.lookup(launchId),old.record);
  close();open();
  assert.deepEqual(journal.lookupRetirement(launchId),retired);
  assert.deepEqual(await journal.launch(former.intent),{record:old.record,bootstrap:null});
  await assert.rejects(journal.launch({...former.intent,launch_id:id()}),{code:'linux_member_generation_used'});
  const opened=await start(replacement);
  assert.equal(opened.message,'application_entered\n');
  assert.equal(opened.record.phase,'executed_closed');
  opened.bootstrap.write('Q');
  await waitUntil(()=>empty(replacement.parent));

  const replaced=plan('seamer');
  const original=await start(replaced);
  original.bootstrap.write('Q');
  await waitUntil(()=>empty(replaced.parent));
  const seamerClosing=journal.closeIntake(replaced.intent.launch_id);
  const inode=fs.statSync(replaced.core,{bigint:true}).ino;
  fs.rmdirSync(replaced.core);fs.mkdirSync(replaced.core);
  assert.notEqual(fs.statSync(replaced.core,{bigint:true}).ino,inode);
  assert.throws(()=>journal.observeRetirement(replaced.intent.launch_id),{code:'linux_member_retirement_unproven'});
  assert.deepEqual(journal.lookupRetirement(replaced.intent.launch_id),seamerClosing);
  await assert.rejects(journal.launch(plan('seamer').intent),{code:'linux_member_previous_unretired'});
});
