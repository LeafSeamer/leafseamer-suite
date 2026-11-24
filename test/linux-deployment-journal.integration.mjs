import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';
import {createInstallationStore,openInstallationStore} from '../dist/installation-store.mjs';
import {linuxContainerCgroup} from '../dist/linux-cgroup-retirement.mjs';

const enabled=process.platform==='linux'&&process.env.LEAFSEAMER_TEST_CGROUP_HOST==='1';
const id=()=>crypto.randomUUID();
const hash=value=>'sha256:'+crypto.createHash('sha256').update(value).digest('hex');
const target=()=>({service_id:id(),database_instance_id:id()});
const generation=(controller=target(),seamer=target())=>({generation_id:id(),driver:'cgroupfs',
  compose_digest:hash('synthetic protected compose plan'),controller,seamer});

function installation(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-deployment-journal-'));
  t.after(()=>{assert.equal(path.dirname(root),os.tmpdir());fs.rmSync(root,{recursive:true,force:true});});
  return root;
}
async function stop(member){
  if(member.child.exitCode===null&&member.child.signalCode===null)member.child.stdin.end();
  const timer=setTimeout(()=>member.child.kill('SIGKILL'),2000);
  try{assert.deepEqual(await member.exit,[0,null]);}finally{clearTimeout(timer);}
}

test('宿主账本持久关闭旧入口，等待真实父组与端点，再放行新代',{skip:!enabled,timeout:20000},async t=>{
  const root=installation(t),groups=[],members=[];
  const first=generation(),second=generation(first.controller,first.seamer);
  let installationStore,journal,launches=0,endpointChecks=0,endpoint,endpointFailure=false;
  t.after(async()=>{
    if(endpoint?.listening)await new Promise(resolve=>endpoint.close(resolve));
    journal?.close();installationStore?.close();
    await Promise.all(members.map(stop));
    for(const group of groups.reverse())fs.rmdirSync(group);
  });
  const endpointPath=path.join(root,'diagnostic.sock');
  const endpointEvidence=hash('closed:'+endpointPath);
  function createGroup(group){fs.mkdirSync(group);groups.push(group);return group;}
  function member(group){
    const child=spawn('/bin/cat',{stdio:['pipe','ignore','inherit']});
    child.stdin.on('error',()=>{});
    const started={child,exit:once(child,'close')};
    members.push(started);
    fs.writeFileSync(group+'/cgroup.procs',String(child.pid));
    return child.pid;
  }
  const runtime={
    launch(spec){
      launches++;
      const current=journal.current();
      assert.equal(current.intent.generation_id,spec.generation_id);
      assert.equal(current.phase,'launching');
      const result={};
      for(const role of ['controller','seamer']){
        const {groupPath}=linuxContainerCgroup({driver:spec.driver,generationId:spec.generation_id,role});
        const parent=createGroup('/sys/fs/cgroup'+groupPath);
        result[role]=member(createGroup(parent+'/core'));
        if(role==='controller')member(createGroup(parent+'/worker'));
      }
      return result;
    },
    endpointClosure(record){
      endpointChecks++;
      assert.equal(journal.current().phase,'closing');
      assert.equal(record.intent.generation_id,first.generation_id);
      if(endpointFailure)throw new Error('synthetic endpoint reader unavailable');
      return fs.existsSync(endpointPath)?null:endpointEvidence;
    }
  };
  createInstallationStore(root);
  installationStore=openInstallationStore(root);
  assert.throws(()=>installationStore.openLinuxDeploymentJournal(runtime),{code:'linux_deployment_unavailable'});
  installationStore.initializeLinuxDeploymentJournal();
  assert.throws(()=>installationStore.initializeLinuxDeploymentJournal(),{code:'linux_deployment_initialized'});
  journal=installationStore.openLinuxDeploymentJournal(runtime);
  assert.throws(()=>installationStore.openLinuxDeploymentJournal(runtime),{code:'linux_deployment_in_use'});
  assert.throws(()=>installationStore.close(),{code:'linux_deployment_in_use'});
  assert.equal(journal.start(first).phase,'running');
  assert.throws(()=>journal.start(second),{code:'linux_deployment_previous_open'});
  assert.equal(launches,1);
  assert.equal(journal.closeIntake(first.generation_id).phase,'closing');
  const closed=journal.current();
  assert.deepEqual(journal.closeIntake(first.generation_id),closed);
  journal.close();installationStore.close();
  installationStore=openInstallationStore(root);
  journal=installationStore.openLinuxDeploymentJournal(runtime);
  assert.deepEqual(journal.current(),closed);
  // 丢弃旧文件描述符后，仍活着的原进程与原组必须逐项重核。
  assert.equal(journal.observeRetirement(first.generation_id).phase,'closing');
  assert.deepEqual(journal.current().detail,closed.detail);
  endpoint=net.createServer();
  endpoint.listen(endpointPath);
  await once(endpoint,'listening');
  await Promise.all([stop(members[0]),stop(members[2])]);
  assert.equal(journal.observeRetirement(first.generation_id).phase,'closing');
  assert.equal(endpointChecks,0);
  await stop(members[1]);
  assert.equal(journal.observeRetirement(first.generation_id).phase,'closing');
  assert.equal(endpointChecks,1);
  assert.throws(()=>journal.start(second),{code:'linux_deployment_previous_open'});
  await new Promise(resolve=>endpoint.close(resolve));
  endpointFailure=true;
  assert.throws(()=>journal.observeRetirement(first.generation_id),{code:'linux_deployment_endpoints_unavailable'});
  assert.equal(journal.current().phase,'closing');
  endpointFailure=false;
  const retired=journal.observeRetirement(first.generation_id);
  assert.equal(retired.phase,'retired');
  assert.equal(retired.detail.endpoint_evidence_digest,endpointEvidence);
  journal.close();installationStore.close();
  const raw=new DatabaseSync(path.join(root,'linux-deployment.db'));
  try{
    assert.throws(()=>raw.exec('DELETE FROM linux_deployment_event'),/linux_deployment_event_immutable/);
    // 准入表在旧版布局中不存在。保留已退役的实际运行代和原身份标记。
    raw.exec('DROP TABLE linux_deployment_admission; PRAGMA user_version=1');
  }
  finally{raw.close();}
  installationStore=openInstallationStore(root);
  journal=installationStore.openLinuxDeploymentJournal(runtime);
  assert.equal(journal.schemaRevision,1);
  assert.deepEqual(journal.lookup(first.generation_id),retired);
  assert.throws(()=>journal.admission(first.generation_id,'controller'),{code:'linux_deployment_admission'});
  journal.close();
  assert.deepEqual(installationStore.upgradeLinuxDeploymentJournal(),{schema_revision:2,changed:true});
  assert.deepEqual(installationStore.upgradeLinuxDeploymentJournal(),{schema_revision:2,changed:false});
  journal=installationStore.openLinuxDeploymentJournal(runtime);
  assert.equal(journal.schemaRevision,2);
  assert.equal(journal.admission(first.generation_id,'controller'),null);
  assert.deepEqual(journal.lookup(first.generation_id),retired);
  assert.throws(()=>journal.start(first),{code:'linux_deployment_generation_used'});
  assert.equal(journal.start(second).phase,'running');
  assert.equal(launches,2);
  journal.closeIntake(second.generation_id);
  journal.close();installationStore.close();
  await Promise.all(members.slice(3).map(stop));
  installationStore=openInstallationStore(root);
  journal=installationStore.openLinuxDeploymentJournal(runtime);
  assert.equal(journal.observeRetirement(second.generation_id).phase,'indeterminate');
  assert.throws(()=>journal.start(generation(first.controller,first.seamer)),{code:'linux_deployment_previous_open'});
  assert.equal(launches,2);
});

test('不确定的启动结果保留原预留并阻止重试',{skip:!enabled},t=>{
  const root=installation(t),first=generation();
  let launches=0;
  const runtime={launch(){launches++;throw Error('synthetic missing launch receipt');},endpointClosure(){return null;}};
  createInstallationStore(root);
  const install=openInstallationStore(root);
  let journal;
  try{
    install.initializeLinuxDeploymentJournal();
    journal=install.openLinuxDeploymentJournal(runtime);
    assert.throws(()=>journal.start(first),{code:'linux_deployment_launch_unproven'});
    assert.equal(journal.lookup(first.generation_id).phase,'launching');
    journal.close();
    journal=install.openLinuxDeploymentJournal(runtime);
    assert.throws(()=>journal.start(first),{code:'linux_deployment_previous_open'});
    assert.equal(launches,1);
  }finally{journal?.close();install.close();}
});
