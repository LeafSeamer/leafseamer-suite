import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {openInstallationStore,requireInstallationStore} from './installation-store.mjs';
import {readDeploymentFile} from './linux-ingress.mjs';
import {composePairingLabel,renderLinuxCompose,verifyLinuxComposeClockInputs,verifyLinuxComposePairingInputs,verifyLinuxComposeReferenceCapture} from './linux-compose.mjs';
import {checkLinuxWorkerGroup,observeLinuxComposeCore,readLinuxCgroupHost,readLinuxCgroupLeader,readLinuxCgroupParent,readLinuxReferenceGroup} from './linux-cgroup-retirement.mjs';
import {openLinuxComposeChannel,openLinuxInstallationChannel,openLinuxReferenceChannel,openLinuxReferenceRetirementChannel} from './linux-compose-channel.mjs';
import {serveLinuxInstallationRead} from './linux-installation-read.mjs';
import {admitLinuxMember} from './linux-member-bootstrap.mjs';
import {bindLinuxWorkerControl} from './linux-worker-control.mjs';
import {linuxWorkerRuntimeOptions,startLinuxReferenceProvider} from './linux-member-journal.mjs';
import {pinExecutable} from './linux-native-artifact.mjs';
import {composeLinuxWorkerRuntime} from './linux-native-host.mjs';

const docker='/usr/bin/docker';
const roles=['controller','seamer','nginx'];
const coreRoles=['controller','seamer'];
const env=Object.freeze({PATH:'/usr/sbin:/usr/bin:/sbin:/bin',HOME:'/nonexistent',DOCKER_CONFIG:'/etc/docker',LC_ALL:'C'});
const imageId=/^sha256:[a-f0-9]{64}$(?![\s\S])/;
const objectId=/^[a-f0-9]{64}$(?![\s\S])/;
const fileHash=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');
const equal=(left,right)=>canonical(left)===canonical(right);
const within=(found,approved)=>found.every(id=>approved.includes(id));
function absolute(value){
  need(typeof value==='string'&&value.length<=512&&/^\/[A-Za-z0-9_./ -]+$(?![\s\S])/.test(value)&&
    path.posix.normalize(value)===value&&value!=='/'&&!value.endsWith('/'),'compose_host_path');
  return value;
}
function protectedPath(value,check){
  const filename=absolute(value),stat=fs.lstatSync(filename,{bigint:true});
  need(check(stat)&&stat.uid===BigInt(process.geteuid())&&(stat.mode&0o022n)===0n,'compose_host_path');
  return {device:String(stat.dev),inode:String(stat.ino)};
}
function protectedParents(filename){
  let directory=path.posix.dirname(filename);
  for(;;){
    const stat=fs.lstatSync(directory,{bigint:true});
    const trustedOwner=stat.uid===0n||stat.uid===BigInt(process.geteuid());
    need(stat.isDirectory()&&trustedOwner&&((stat.mode&0o022n)===0n||(stat.mode&0o1000n)!==0n),'compose_host_path');
    if(directory==='/')return;
    directory=path.posix.dirname(directory);
  }
}

function listenInodes(socketNames){
  const fd=fs.openSync('/proc/net/unix','r');
  try{
    const buffer=Buffer.alloc(1048577);
    let length=0,count;
    while(length<buffer.length&&(count=fs.readSync(fd,buffer,length,buffer.length-length,null))>0)length+=count;
    need(length<buffer.length,'compose_host_daemon');
    return buffer.subarray(0,length).toString('utf8').split('\n').slice(1).flatMap(line=>{
      const parts=line.trim().split(/\s+/);
      return parts.length===8&&parts[3]==='00010000'&&parts[4]==='0001'&&parts[5]==='01'&&socketNames.has(parts[7])?[parts[6]]:[];
    });
  }finally{fs.closeSync(fd);}
}
function daemonIdentity(socketPath,pidFile){
  // Docker permits group access to the socket. Its owning process and listening inode are checked independently.
  const socket=fs.lstatSync(socketPath,{bigint:true});
  need(socket.isSocket()&&socket.uid===BigInt(process.geteuid()),'compose_host_socket');
  const pidSource=protectedPath(pidFile,stat=>stat.isFile());
  const value=readDeploymentFile(pidFile,32).toString('utf8').trim();
  need(/^[1-9][0-9]{0,9}$/.test(value),'compose_host_daemon');
  const pid=Number(value),leader=readLinuxCgroupLeader(pid),root='/proc/'+pid;
  need(path.basename(fs.readlinkSync(root+'/exe'))==='dockerd','compose_host_daemon');
  const names=new Set([socketPath,fs.realpathSync(socketPath)]);
  if(socketPath==='/run/docker.sock')names.add('/var/run/docker.sock');
  const sockets=listenInodes(names);
  need(sockets.length===1,'compose_host_daemon');
  const expected='socket:['+sockets[0]+']';
  const descriptors=fs.readdirSync(root+'/fd');
  need(descriptors.length<=65536&&descriptors.some(name=>{
    try{return fs.readlinkSync(root+'/fd/'+name)===expected;}
    catch(error){if(error.code==='ENOENT')return false;throw error;}
  }),'compose_host_daemon');
  const after=fs.lstatSync(socketPath,{bigint:true});
  need(socket.dev===after.dev&&socket.ino===after.ino&&equal(leader,readLinuxCgroupLeader(pid))&&
    equal(pidSource,protectedPath(pidFile,stat=>stat.isFile())),'compose_host_daemon_changed');
  return {host:readLinuxCgroupHost(),leader,listener:sockets[0],socket:{device:String(socket.dev),inode:String(socket.ino)}};
}

async function openPinnedClock(directory,artifact){
  protectedParents(directory);
  protectedPath(directory,stat=>stat.isDirectory());
  const manifestFile=path.join(directory,'build-manifest.json');
  protectedPath(manifestFile,stat=>stat.isFile());
  const bytes=readDeploymentFile(manifestFile,1048576);
  const controller_build_sha256=fileHash(bytes).slice(7),node_sha256=fileHash(fs.readFileSync('/proc/self/exe')).slice(7);
  need(digest({controller_build_sha256,node_sha256})===artifact,'compose_host_clock_artifact');
  const manifest=JSON.parse(bytes);
  need(manifest.format==='leafseamer-controller-build/1','compose_host_clock_artifact');
  for(const name of ['native-clock.mjs','linux-kernel-sleep.mjs','native/manifest.json','native/leafseamer_clock.node']){
    const file=path.join(directory,name),expected=manifest.artifacts?.[name];
    need(typeof expected==='string'&&imageId.test('sha256:'+expected),'compose_host_clock_artifact');
    protectedParents(file);
    const {fd}=pinExecutable(file,'sha256:'+expected,4*1024*1024);
    fs.closeSync(fd);
  }
  const {openNativeClock}=await import(pathToFileURL(path.join(directory,'native-clock.mjs')));
  return openNativeClock();
}

export function openLinuxComposeHost({installationDirectory,installationStore=null,planFile,generationDirectory,socketPath='/run/docker.sock',pidFile='/run/docker.pid',source=null,clockDirectory=null}={}){
  need(process.platform==='linux','compose_host_platform');
  absolute(installationDirectory);absolute(planFile);absolute(generationDirectory);absolute(socketPath);absolute(pidFile);
  need(!socketPath.includes(' '),'compose_host_socket');
  for(const filename of [installationDirectory,planFile,generationDirectory,socketPath,pidFile])protectedParents(filename);
  const planIdentity=protectedPath(planFile,stat=>stat.isFile()),outputIdentity=protectedPath(generationDirectory,stat=>stat.isDirectory());
  const planBytes=readDeploymentFile(planFile,65536),plan=JSON.parse(planBytes);
  const generated=renderLinuxCompose(plan,generationDirectory),compose=JSON.parse(generated['compose.json']);
  const clockInputs=verifyLinuxComposeClockInputs(plan);
  const pairingInputs=verifyLinuxComposePairingInputs(plan);
  const inbox=plan.pairing?.seamer.await_first_pairing?path.join(generationDirectory,'first-pairing'):null;
  const inboxIdentity=inbox&&protectedPath(inbox,stat=>stat.isDirectory());
  const {driver,generation_id,namespace}=plan.cgroup??{};
  const privateNamespace=namespace==='private';
  const supervised=Object.hasOwn(plan,'bootstrap');
  if(clockDirectory!==null){absolute(clockDirectory);need(supervised&&source===null,'compose_host_bootstrap');}
  const reference=plan.reference_providers??null;
  const workerControl=plan.worker_control===true;
  if(supervised)need(process.geteuid()===0,'compose_host_bootstrap');
  const controlDirectory=workerControl&&protectedPath(installationDirectory,stat=>stat.isDirectory()&&(stat.mode&0o077n)===0n);
  need(driver&&generation_id,'compose_host_cgroup');
  function verifyAdmissionInputs(){
    need(equal(clockInputs,verifyLinuxComposeClockInputs(plan))&&equal(pairingInputs,verifyLinuxComposePairingInputs(plan)),'compose_host_plan_changed');
    verifyLinuxComposeReferenceCapture(plan);
    if(inbox)need(equal(inboxIdentity,protectedPath(inbox,stat=>stat.isDirectory())),'compose_host_plan_changed');
  }
  function verifyFiles(){
    need(equal(planIdentity,protectedPath(planFile,stat=>stat.isFile()))&&planBytes.equals(readDeploymentFile(planFile,65536))&&
      equal(outputIdentity,protectedPath(generationDirectory,stat=>stat.isDirectory())),'compose_host_plan_changed');
    if(workerControl)need(equal(controlDirectory,protectedPath(installationDirectory,stat=>stat.isDirectory()&&(stat.mode&0o077n)===0n)),
      'compose_host_plan_changed');
    for(const [name,bytes]of Object.entries(generated)){
      const filename=path.join(generationDirectory,name);
      protectedPath(filename,stat=>stat.isFile());
      need(readDeploymentFile(filename,65536).equals(Buffer.from(bytes)),'compose_host_plan_changed');
    }
  }
  verifyFiles();
  const installation=installationStore===null?openInstallationStore(installationDirectory):requireInstallationStore(installationStore,installationDirectory);
  const closeInstallation=()=>{if(installationStore===null)installation.close();};
  let journal;
  let starting=false,startedHere=false;
  let control=null,installationReader=null,closing=null,draining=null;
  const loss=Promise.withResolvers();
  const channels=new Map(),providers=new Map();
  function closeChannels(){
    if(draining)return draining;
    const active=[...channels.values()];channels.clear();
    const children=[...providers.values()];providers.clear();
    const finished=children.map(provider=>provider.retire());
    for(const channel of active)channel.close();
    control?.close();control=null;
    return draining=Promise.all([...active.map(channel=>channel.ended),installationReader,...finished]);
  }
  const closeAfterLoss=()=>{
    if(!draining)loss.resolve();
    void closeChannels().catch(()=>{});
  };
  try{
    const worker=plan.worker_runtime?composeLinuxWorkerRuntime(plan.worker_runtime,plan.controller,plan.bootstrap.controller,installation):null;
    if(worker){
      const overlaps=(a,b)=>a===b||a.startsWith(b+'/')||b.startsWith(a+'/');
      need(![worker.runtime.directory,worker.runtime.channelDirectory,plan.worker_runtime.distribution.directory].some(dir=>
        overlaps(dir,installationDirectory)),'compose_worker_runtime');
    }
    const project='leafseamer-'+installation.identity.host_installation_id.replaceAll('-','')+'-'+generation_id.replaceAll('-','');
    const composeArgs=['compose','--project-name',project,'--project-directory',generationDirectory,'--env-file','/dev/null',
      '--file',path.join(generationDirectory,'compose.json')];
    const spec={generation_id,driver,compose_digest:fileHash(Buffer.from(generated['compose.json'])),
      ...(reference&&{reference_digest:digest(reference)}),
      ...Object.fromEntries(coreRoles.map(role=>[role,{
        service_id:plan[role].service_id,database_instance_id:plan[role].database_instance_id}]))};
    const daemon=daemonIdentity(socketPath,pidFile);
    function assertDaemon(){
      need(equal(daemon,daemonIdentity(socketPath,pidFile)),'compose_host_daemon_changed');
    }
    function run(args,timeout=8000){
      assertDaemon();
      const result=spawnSync(docker,['--host','unix://'+socketPath,...args],{env,cwd:generationDirectory,encoding:'utf8',timeout,maxBuffer:262144});
      assertDaemon();
      need(result.status===0,'compose_host_docker_failed');
      return result.stdout;
    }
    const label='label=com.docker.compose.project='+project;
    function list(ids){
      const values=ids.trim()===''?[]:ids.trim().split('\n');
      need(values.length<=16&&new Set(values).size===values.length&&values.every(id=>objectId.test(id)),'compose_host_inventory');
      return values;
    }
    const containerIds=()=>list(run(['container','ls','--all','--no-trunc','--quiet','--filter',label]));
    const networkIds=()=>list(run(['network','ls','--no-trunc','--quiet','--filter',label]));
    function parents(){
      try{
        return Object.fromEntries(coreRoles.map(role=>[role,
          readLinuxCgroupParent({driver,generationId:generation_id,role,host:daemon.host})]));
      }catch{need(false,'compose_host_parent_unavailable');}
    }
    const referenceGroup=role=>readLinuxReferenceGroup({driver,generationId:generation_id,role,host:daemon.host});
    const referenceGroups=()=>Object.fromEntries(coreRoles.map(role=>[role,referenceGroup(role)]));
    function assertFreshProject(){
      need(containerIds().length===0&&networkIds().length===0,'compose_host_project_exists');
    }
    function prepareLaunch(){
      if(worker){
        worker.runtime.assertCurrent();
        need(fs.readdirSync(worker.runtime.channelDirectory).length===0,'compose_host_worker_mount');
      }
      const info=JSON.parse(run(['info','--format','{{json .}}']));
      need(info.OSType==='linux'&&String(info.CgroupVersion)==='2'&&info.CgroupDriver===driver,'compose_host_engine');
      assertFreshProject();
      const before=parents();
      need(Object.values(before).every(group=>!group.populated),'compose_host_parent_populated');
      const referenceBefore=reference&&referenceGroups();
      if(reference){
        need(Object.values(referenceBefore).every(group=>!group.populated),'compose_host_reference_populated');
        const executable=pinExecutable(reference.image.file,reference.image.sha256,64*1024*1024);
        fs.closeSync(executable.fd);
      }
      const images=Object.fromEntries(roles.map(role=>{
        const id=run(['image','inspect','--format','{{.Id}}',plan[role].image]).trim();
        need(imageId.test(id),'compose_host_image');
        return [role,id];
      }));
      return {before,images,referenceBefore};
    }
    function coreContainment(role,container){
      need(container.HostConfig?.CgroupnsMode==='private','compose_host_cgroup_namespace');
      const {uid,gid}=plan[role];
      return observeLinuxComposeCore({driver,generationId:generation_id,role,host:daemon.host,
        leader:readLinuxCgroupLeader(container.State.Pid),containerId:container.Id,uid,gid});
    }
    let prepared=null;
    function launch(config){
      need(prepared&&equal(config,spec),'compose_host_intent');
      const {before,images,referenceBefore}=prepared;
      verifyFiles();verifyAdmissionInputs();assertFreshProject();
      need(equal(before,parents()),'compose_host_parent_changed');
      run([...composeArgs,'up','--detach','--no-build','--pull','never','--no-recreate'],45000);
      const after=parents();
      need(coreRoles.every(role=>after[role].populated&&equal(before[role].group,after[role].group)),
        'compose_host_parent_changed');
      if(reference)need(equal(referenceBefore,referenceGroups()),'compose_host_reference_group_changed');
      const ids=containerIds(),networks=networkIds();
      need(ids.length===3&&networks.length===2,'compose_host_inventory');
      const observed=JSON.parse(run(['container','inspect',...ids])),containers={},pids={},core_containment={};
      need(Array.isArray(observed)&&observed.length===3,'compose_host_inventory');
      for(const container of observed){
        const labels=container.Config?.Labels,role=labels?.['com.docker.compose.service'],config=container.HostConfig;
        need(roles.includes(role)&&!Object.hasOwn(containers,role)&&ids.includes(container.Id)&&
          labels['com.docker.compose.project']===project&&labels['com.docker.compose.container-number']==='1'&&
          container.Image===images[role]&&container.State?.Running===true&&Number.isInteger(container.State.Pid)&&container.State.Pid>1&&
          config?.RestartPolicy?.Name==='no'&&config.Privileged===false&&config.ReadonlyRootfs===true&&
          config.CgroupParent===(compose.services[role].cgroup_parent??'')&&config.PidMode!=='host','compose_host_container');
        containers[role]=container.Id;
        pids[role]=container.State.Pid;
        if(privateNamespace&&coreRoles.includes(role))core_containment[role]=coreContainment(role,container);
        if(supervised&&coreRoles.includes(role)){
          const service=compose.services[role];
          need(equal(container.Config.Entrypoint,service.entrypoint)&&equal(container.Config.Cmd,service.command)&&
            labels[composePairingLabel]===service.labels?.[composePairingLabel]&&
            service.volumes.every(volume=>container.Mounts.some(mount=>mount.Type==='bind'&&mount.Source===volume.source&&
              mount.Destination===volume.target&&mount.RW===!volume.read_only)),'compose_host_bootstrap');
        }
      }
      return {controller:pids.controller,seamer:pids.seamer,runtime_binding:{project,daemon,containers,networks,images,
        ...(privateNamespace&&{core_containment}),...(reference&&{reference_groups:referenceBefore})}};
    }
    function binding(record){
      const bound=record?.detail.runtime_binding;
      need(record&&equal(record.intent,spec)&&bound?.project===project&&equal(bound.daemon,daemon)&&
        roles.every(role=>objectId.test(bound.containers?.[role]??'')),'compose_host_binding');
      if(privateNamespace)need(coreRoles.every(role=>{
        const scope=bound.core_containment?.[role];
        return scope?.container_id===bound.containers[role]&&equal(scope.leader,record.detail.members[role].leader);
      }),'compose_host_binding');
      return bound;
    }
    function endpointClosure(record){
      verifyFiles();
      const bound=binding(record);
      if(containerIds().length!==0||networkIds().length!==0)return null;
      const endpointDigest=digest({format:'leafseamer.compose-endpoints-closed/1',runtime_binding:bound});
      if(!reference)return endpointDigest;
      const groups=referenceGroups(),proof={};
      for(const role of coreRoles){
        const observed=groups[role],original=bound.reference_groups[role];
        need(equal(observed.group,original.group)&&observed.group_path===original.group_path,'compose_host_reference_group_changed');
        if(observed.populated)return null;
        const admission=journal.referenceAdmission(generation_id,role);
        if(!admission){proof[role]=null;continue;}
        const {provider_pid,start_ticks}=admission.process_observation;
        let live;
        try{live=readLinuxCgroupLeader(provider_pid);}
        catch(error){if(!['ENOENT','ESRCH','cgroup_leader_missing'].includes(error.code))throw error;}
        if(live?.start_ticks===start_ticks)return null;
        proof[role]={group:observed.group,group_path:observed.group_path,provider_pid,start_ticks};
      }
      return {digest:endpointDigest,reference_retirement:proof};
    }
    function assertSurvivingCores(bound,present){
      const ids=coreRoles.map(role=>bound.containers[role]).filter(id=>present.includes(id));
      if(!ids.length)return;
      const cores=JSON.parse(run(['container','inspect',...ids]));
      need(Array.isArray(cores)&&cores.length===ids.length&&ids.every(id=>cores.filter(core=>core.Id===id).length===1),
        'compose_host_inventory_changed');
      for(const role of coreRoles){
        const core=cores.find(core=>core.Id===bound.containers[role]);
        if(core?.State?.Running===true)need(equal(coreContainment(role,core),bound.core_containment[role]),'compose_host_binding');
      }
    }
    journal=installation.openLinuxDeploymentJournal({launch,endpointClosure});
    const idle=()=>need(!starting,'compose_host_bootstrap_busy');
    function start(){
      verifyFiles();assertDaemon();
      const prior=journal.current();
      need(!prior||prior.phase==='retired','linux_deployment_previous_open');
      need(!journal.lookup(generation_id),'linux_deployment_generation_used');
      prepared=prepareLaunch();
      try{
        const result=journal.start(spec);
        startedHere=true;
        return result;
      }finally{prepared=null;}
    }
    async function admit(role,record){
      const bound=binding(record),expected=bound.core_containment[role],channel=channels.get(role),policy=plan.bootstrap[role];
      const scope={driver,generationId:generation_id,role,host:daemon.host,expected};
      const socket=await channel.accept(scope);
      const controllerControl=workerControl&&role==='controller';
      const result=await admitLinuxMember({intent:{role,generation_id,service_id:spec[role].service_id,launch_id:crypto.randomUUID()},
        detail:{host:daemon.host,...expected}},{policy,source,socket,compose:true,async commit(admission){
          verifyFiles();verifyAdmissionInputs();
          const core=JSON.parse(run(['container','inspect',bound.containers[role]]));
          need(core.length===1&&core[0].Id===bound.containers[role]&&core[0].State?.Running===true&&
            equal(coreContainment(role,core[0]),expected)&&!socket.destroyed&&!socket.readableEnded,'compose_host_binding');
          const saved=journal.recordAdmission(generation_id,role,admission);
          if(reference)await startReference(role,record,saved);
          if(controllerControl){
            const {uid,gid}=plan.controller;
            function assertLive(){
              verifyFiles();
              need(equal(observeLinuxComposeCore({...scope,leader:expected.leader,containerId:expected.container_id,uid,gid}),expected),
                'compose_host_binding');
            }
            if(worker){
              const identity=file=>{const {dev,ino}=fs.statSync(file,{bigint:true});return {device:String(dev),inode:String(ino)};};
              worker.runtime.assertCurrent();
              need(equal(identity('/proc/'+expected.leader.pid+'/root/run/leafseamer-worker'),identity(worker.runtime.channelDirectory)),
                'compose_host_worker_mount');
              const reader=openLinuxInstallationChannel({directory:worker.runtime.channelDirectory,uid,gid,
                corePid:expected.leader.pid,timeoutMs:policy.bootstrap_timeout_ms,assertCurrent:assertLive});
              channels.set('installation',reader);
              void reader.ended.then(closeAfterLoss);
              installationReader=reader.peer.then(connection=>serveLinuxInstallationRead({socket:connection,installation,receipt:admission.receipt,
                serviceId:policy.service_id,assertCurrent:assertLive})).catch(reader.close);
              await reader.ready;
            }
            control=bindLinuxWorkerControl({directory:installationDirectory,socket,core:admission,source,
              assertLive,
              checkGroup:intent=>checkLinuxWorkerGroup({driver,generationId:generation_id,host:daemon.host,
                launchId:intent.launch_id,groupId:intent.containment_ref.group_id}),
              ...linuxWorkerRuntimeOptions({runtime:worker?.runtime,core:admission,spec:worker?.spec,host:daemon.host,
                source,corePid:expected.leader.pid})});
          }
          return saved;
        }});
      if(!controllerControl)socket.once('data',channel.close);
      socket.resume();
      return result;
    }
    async function startReference(role,record,core){
      const bound=binding(record),expected=bound.core_containment[role],assigned=bound.reference_groups[role];
      const {uid,gid}=plan[role],scope={driver,generationId:generation_id,role,host:daemon.host,expected};
      function assertLive(){
        verifyFiles();
        const {group,group_path}=referenceGroup(role),phase=journal.current();
        need(channels.has(role)&&phase?.phase==='running'&&phase.intent.generation_id===generation_id&&
          equal({group,group_path},{group:assigned.group,group_path:assigned.group_path})&&
          equal(observeLinuxComposeCore({...scope,leader:expected.leader,containerId:expected.container_id,uid,gid}),expected),
        'compose_host_reference_binding');
      }
      const provider=await startLinuxReferenceProvider({core,groupPath:assigned.group_path,source,assertLive,
        provider:{...reference[role],image_path:reference.image.file,
          artifact_manifest_ref:{manifest_id:'linux-reference-time-provider',revision:'1',digest:reference.image.sha256}},
        reserve(original){
          need(equal(original.group,assigned.group),'compose_host_reference_group_changed');
          journal.reserveReference(generation_id,role,reference,original);
        },
        commit(original){journal.recordReferenceAdmission(generation_id,role,original);}
      });
      if(draining){await provider.retire();need(false,'compose_host_reference_binding');}
      providers.set(role,provider);
      void provider.ended.then(closeAfterLoss);
      const directory=path.join(generationDirectory,'bootstrap-'+role),timeoutMs=core.policy.bootstrap_timeout_ms;
      const retirement=reference.capture&&openLinuxReferenceRetirementChannel({directory,uid,gid,corePid:expected.leader.pid,timeoutMs,
        coreReceiptId:core.receipt.receipt_id,assertCurrent:assertLive,read(key){
          if(key.generation_id===generation_id)return null;
          const scope=journal.lookup(key.generation_id)?.intent?.[role];
          if(!scope||!equal(scope,spec[role]))return null;
          const original=journal.referenceRetirement(key.generation_id,role);
          return original?.launch_intent.launch_id===key.launch_id&&original.core_receipt_id===key.core_receipt_id&&
            digest(original.launch_intent)===key.launch_intent_digest?original:null;
        }});
      if(retirement){
        channels.set('reference-retirement-'+role,retirement);
        void retirement.ended.then(closeAfterLoss);
        await retirement.ready;
      }
      const forward=openLinuxReferenceChannel({directory,uid,gid,
        corePid:expected.leader.pid,timeoutMs,provider,coreReceiptId:core.receipt.receipt_id,retirement:!!retirement});
      channels.set('reference-'+role,forward);
      void forward.ended.then(closeAfterLoss);
      await forward.ready;
    }
    return Object.freeze({
      generationId:generation_id,
      channelLost:loss.promise,
      startedHere:()=>startedHere,
      current:()=>journal.current(),
      admission:role=>journal.admission(generation_id,role),
      referenceAdmission:role=>journal.referenceAdmission(generation_id,role),
      start(){idle();need(!supervised,'compose_host_bootstrap');return start();},
      async startSupervised(){
        idle();need(supervised&&journal.schemaRevision>=2&&(!reference||journal.schemaRevision>=3)&&
          (clockDirectory!==null||source&&typeof source.capture==='function'&&typeof source.tick==='function'),'compose_host_bootstrap');
        verifyFiles();verifyAdmissionInputs();
        need(channels.size===0&&!journal.lookup(generation_id),'linux_deployment_generation_used');
        starting=true;
        draining=null;
        try{
          if(clockDirectory!==null&&source===null)source=await openPinnedClock(clockDirectory,plan.bootstrap.controller.artifact_manifest_ref.digest);
          need(source&&typeof source.capture==='function'&&typeof source.tick==='function','compose_host_bootstrap');
          for(const role of coreRoles){
            const {uid,gid}=plan[role];
            const channel=openLinuxComposeChannel({directory:path.join(generationDirectory,'bootstrap-'+role),uid,gid,
              timeoutMs:plan.bootstrap[role].bootstrap_timeout_ms});
            channels.set(role,channel);
            void channel.ended.then(closeAfterLoss);
            await channel.ready;
          }
          need(channels.size===coreRoles.length,'compose_host_bootstrap');
          const record=start(),admissions={};
          for(const role of coreRoles)admissions[role]=await admit(role,record);
          if(!reference)return {record,admissions};
          return {record,admissions,referenceAdmissions:Object.fromEntries(coreRoles.map(role=>[role,providers.get(role).admission]))};
        }catch(error){await closeChannels();throw error;}
        finally{starting=false;}
      },
      retire(){
        idle();
        verifyFiles();assertDaemon();
        const prior=journal.current(),bound=binding(prior);
        if(prior.phase==='retired')return prior;
        need(['running','closing'].includes(prior.phase),'compose_host_phase');
        journal.closeIntake(generation_id);
        // Rebind live original members before removing any container after a host helper restart.
        const observation=journal.observeRetirement(generation_id);
        if(observation.phase!=='closing')return observation;
        const present=containerIds();
        need(within(present,Object.values(bound.containers))&&within(networkIds(),bound.networks),'compose_host_inventory_changed');
        if(privateNamespace)assertSurvivingCores(bound,present);
        void closeChannels().catch(()=>{});
        run([...composeArgs,'down','--timeout','8'],45000);
        return journal.observeRetirement(generation_id);
      },
      close(){
        idle();
        if(closing)return closing;
        const drained=closeChannels();
        try{journal.close();}finally{
          if(installationReader||reference)closing=drained.finally(closeInstallation);
          else{closeInstallation();closing=drained;}
        }
        return closing;
      }
    });
  }catch(error){journal?.close();closeInstallation();throw error;}
}
