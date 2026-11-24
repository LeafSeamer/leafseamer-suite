import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {openInstallationStore} from './installation-store.mjs';
import {readDeploymentFile} from './linux-ingress.mjs';
import {renderLinuxCompose,verifyLinuxComposeClockInputs} from './linux-compose.mjs';
import {observeLinuxComposeCore,readLinuxCgroupHost,readLinuxCgroupLeader,readLinuxCgroupParent} from './linux-cgroup-retirement.mjs';
import {openLinuxComposeChannel} from './linux-compose-channel.mjs';
import {admitLinuxMember} from './linux-member-bootstrap.mjs';

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

export function openLinuxComposeHost({installationDirectory,planFile,generationDirectory,socketPath='/run/docker.sock',pidFile='/run/docker.pid',source=null}={}){
  need(process.platform==='linux','compose_host_platform');
  absolute(installationDirectory);absolute(planFile);absolute(generationDirectory);absolute(socketPath);absolute(pidFile);
  need(!socketPath.includes(' '),'compose_host_socket');
  for(const filename of [installationDirectory,planFile,generationDirectory,socketPath,pidFile])protectedParents(filename);
  const planIdentity=protectedPath(planFile,stat=>stat.isFile()),outputIdentity=protectedPath(generationDirectory,stat=>stat.isDirectory());
  const planBytes=readDeploymentFile(planFile,65536),plan=JSON.parse(planBytes);
  const generated=renderLinuxCompose(plan,generationDirectory),compose=JSON.parse(generated['compose.json']);
  const clockInputs=verifyLinuxComposeClockInputs(plan);
  const {driver,generation_id,namespace}=plan.cgroup??{};
  const privateNamespace=namespace==='private';
  const supervised=Object.hasOwn(plan,'bootstrap');
  if(supervised)need(process.geteuid()===0,'compose_host_bootstrap');
  need(driver&&generation_id,'compose_host_cgroup');
  function verifyClockInputs(){
    need(equal(clockInputs,verifyLinuxComposeClockInputs(plan)),'compose_host_plan_changed');
  }
  function verifyFiles(){
    need(equal(planIdentity,protectedPath(planFile,stat=>stat.isFile()))&&planBytes.equals(readDeploymentFile(planFile,65536))&&
      equal(outputIdentity,protectedPath(generationDirectory,stat=>stat.isDirectory())),'compose_host_plan_changed');
    for(const [name,bytes]of Object.entries(generated)){
      const filename=path.join(generationDirectory,name);
      protectedPath(filename,stat=>stat.isFile());
      need(readDeploymentFile(filename,65536).equals(Buffer.from(bytes)),'compose_host_plan_changed');
    }
  }
  verifyFiles();
  const installation=openInstallationStore(installationDirectory);
  let journal;
  let starting=false;
  const channels=new Map();
  function closeChannels(){
    const closing=[...channels.values()];channels.clear();
    for(const channel of closing)channel.close();
    return Promise.all(closing.map(channel=>channel.ended));
  }
  try{
    const project='leafseamer-'+installation.identity.host_installation_id.replaceAll('-','')+'-'+generation_id.replaceAll('-','');
    const composeArgs=['compose','--project-name',project,'--project-directory',generationDirectory,'--env-file','/dev/null',
      '--file',path.join(generationDirectory,'compose.json')];
    const spec={generation_id,driver,compose_digest:fileHash(Buffer.from(generated['compose.json'])),
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
    function assertFreshProject(){
      need(containerIds().length===0&&networkIds().length===0,'compose_host_project_exists');
    }
    function prepareLaunch(){
      const info=JSON.parse(run(['info','--format','{{json .}}']));
      need(info.OSType==='linux'&&String(info.CgroupVersion)==='2'&&info.CgroupDriver===driver,'compose_host_engine');
      assertFreshProject();
      const before=parents();
      need(Object.values(before).every(group=>!group.populated),'compose_host_parent_populated');
      const images=Object.fromEntries(roles.map(role=>{
        const id=run(['image','inspect','--format','{{.Id}}',plan[role].image]).trim();
        need(imageId.test(id),'compose_host_image');
        return [role,id];
      }));
      return {before,images};
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
      const {before,images}=prepared;
      verifyFiles();verifyClockInputs();assertFreshProject();
      need(equal(before,parents()),'compose_host_parent_changed');
      run([...composeArgs,'up','--detach','--no-build','--pull','never','--no-recreate'],45000);
      const after=parents();
      need(coreRoles.every(role=>after[role].populated&&equal(before[role].group,after[role].group)),
        'compose_host_parent_changed');
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
            service.volumes.every(volume=>container.Mounts.some(mount=>mount.Type==='bind'&&mount.Source===volume.source&&
              mount.Destination===volume.target&&mount.RW===!volume.read_only)),'compose_host_bootstrap');
        }
      }
      return {controller:pids.controller,seamer:pids.seamer,runtime_binding:{project,daemon,containers,networks,images,
        ...(privateNamespace&&{core_containment})}};
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
      return digest({format:'leafseamer.compose-endpoints-closed/1',runtime_binding:bound});
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
      try{return journal.start(spec);}finally{prepared=null;}
    }
    async function admit(role,record){
      const bound=binding(record),expected=bound.core_containment[role],channel=channels.get(role),policy=plan.bootstrap[role];
      const scope={driver,generationId:generation_id,role,host:daemon.host,expected};
      const socket=await channel.accept(scope);
      const result=await admitLinuxMember({intent:{role,generation_id,service_id:spec[role].service_id,launch_id:crypto.randomUUID()},
        detail:{host:daemon.host,...expected}},{policy,source,socket,compose:true,commit(admission){
          verifyFiles();verifyClockInputs();
          const core=JSON.parse(run(['container','inspect',bound.containers[role]]));
          need(core.length===1&&core[0].Id===bound.containers[role]&&core[0].State?.Running===true&&
            equal(coreContainment(role,core[0]),expected)&&!socket.destroyed&&!socket.readableEnded,'compose_host_binding');
          return journal.recordAdmission(generation_id,role,admission);
        }});
      socket.once('data',channel.close);socket.resume();
      return result;
    }
    return Object.freeze({
      current:()=>journal.current(),
      admission:role=>journal.admission(generation_id,role),
      start(){idle();need(!supervised,'compose_host_bootstrap');return start();},
      async startSupervised(){
        idle();need(supervised&&journal.schemaRevision===2&&source&&typeof source.capture==='function'&&
          typeof source.tick==='function','compose_host_bootstrap');
        verifyFiles();verifyClockInputs();
        need(channels.size===0&&!journal.lookup(generation_id),'linux_deployment_generation_used');
        starting=true;
        try{
          for(const role of coreRoles){
            const {uid,gid}=plan[role];
            const channel=openLinuxComposeChannel({directory:path.join(generationDirectory,'bootstrap-'+role),uid,gid,
              timeoutMs:plan.bootstrap[role].bootstrap_timeout_ms});
            channels.set(role,channel);
            void channel.ended.then(closeChannels);
            await channel.ready;
          }
          need(channels.size===coreRoles.length,'compose_host_bootstrap');
          const record=start(),admissions={};
          for(const role of coreRoles)admissions[role]=await admit(role,record);
          return {record,admissions};
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
        closeChannels();
        run([...composeArgs,'down','--timeout','8'],45000);
        return journal.observeRetirement(generation_id);
      },
      close(){idle();closeChannels();try{journal.close();}finally{installation.close();}}
    });
  }catch(error){journal?.close();installation.close();throw error;}
}
