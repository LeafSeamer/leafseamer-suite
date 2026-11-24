import fs from 'node:fs';

const cgroupRoot='/sys/fs/cgroup',procRoot='/proc';
const cgroupMagic=0x63677270,procMagic=0x9fa0;
const directoryFlags=fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW;
const fileFlags=fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$(?![\s\S])/;
const digits=/^(0|[1-9][0-9]{0,19})$(?![\s\S])/;
const roleNames=new Set(['controller','seamer']);
const fdPath=fd=>procRoot+'/self/fd/'+fd;
const fail=code=>{throw Object.assign(new Error(code),{code});};
const need=(condition,code)=>{if(!condition)fail(code);};
const sameIdentity=(left,right)=>left?.device===right?.device&&left?.inode===right?.inode;
const sameLeader=(left,right)=>left?.pid===right?.pid&&left?.start_ticks===right?.start_ticks&&left?.group_path===right?.group_path;
const identity=stat=>Object.freeze({device:String(stat.dev),inode:String(stat.ino)});
const pathIdentity=file=>identity(fs.statSync(file,{bigint:true}));
const descriptorIdentity=fd=>identity(fs.fstatSync(fd,{bigint:true}));

export function linuxContainerCgroup({driver,generationId,role}={}){
  need(['cgroupfs','systemd'].includes(driver)&&typeof generationId==='string'&&uuid.test(generationId)&&roleNames.has(role),'cgroup_scope');
  const stem='leafseamer_'+generationId.replaceAll('-','')+'_'+role;
  const groupPath='/'+stem+(driver==='systemd'?'.slice':'');
  return Object.freeze({parent:driver==='systemd'?groupPath.slice(1):groupPath,groupPath});
}

function readText(file,type,maximum=4096){
  const fd=fs.openSync(file,fileFlags);
  try{
    need(fs.fstatSync(fd).isFile()&&fs.statfsSync(fdPath(fd)).type===type,'cgroup_filesystem');
    const bytes=Buffer.alloc(maximum+1);
    let total=0,count;
    while(total<bytes.length&&(count=fs.readSync(fd,bytes,total,bytes.length-total,null))>0)total+=count;
    need(total>0&&total<bytes.length,'cgroup_read');
    return bytes.subarray(0,total).toString('utf8');
  }finally{fs.closeSync(fd);}
}

export function readLinuxCgroupHost(){
  need(process.platform==='linux'&&fs.statfsSync(procRoot).type===procMagic&&fs.statfsSync(cgroupRoot).type===cgroupMagic,'cgroup_platform');
  const boot=readText(procRoot+'/sys/kernel/random/boot_id',procMagic);
  need(boot.endsWith('\n')&&uuid.test(boot.slice(0,-1)),'cgroup_boot');
  const pid_namespace=pathIdentity(procRoot+'/self/ns/pid'),cgroup_namespace=pathIdentity(procRoot+'/self/ns/cgroup');
  need(sameIdentity(pid_namespace,pathIdentity(procRoot+'/1/ns/pid'))&&
    sameIdentity(cgroup_namespace,pathIdentity(procRoot+'/1/ns/cgroup')),'cgroup_namespace');
  return Object.freeze({boot_id:boot.slice(0,-1),pid_namespace,cgroup_namespace,
    mount_namespace:pathIdentity(procRoot+'/self/ns/mnt'),root:pathIdentity(cgroupRoot)});
}

function assertHost(expected){
  const local=readLinuxCgroupHost();
  need(expected?.boot_id===local.boot_id&&sameIdentity(expected.pid_namespace,local.pid_namespace)&&
    sameIdentity(expected.cgroup_namespace,local.cgroup_namespace)&&sameIdentity(expected.mount_namespace,local.mount_namespace)&&
    sameIdentity(expected.root,local.root),'cgroup_host_changed');
  return local;
}

function leaderState(fd,pid){
  let text;
  try{text=readText(fdPath(fd)+'/stat',procMagic);}
  catch(error){if(error.code==='ENOENT'||error.code==='ESRCH')return null;throw error;}
  const end=text.lastIndexOf(') '),stats=text.slice(end+2).trimEnd().split(' ');
  need(text.startsWith(pid+' (')&&end>0&&/^[A-Za-z]$/.test(stats[0])&&digits.test(stats[19]??''),'cgroup_leader_stat');
  return {dead:['Z','X','x'].includes(stats[0]),start_ticks:stats[19]};
}

function readLeader(fd,pid){
  const before=leaderState(fd,pid);
  if(!before||before.dead)return null;
  let membership;
  try{membership=readText(fdPath(fd)+'/cgroup',procMagic);}
  catch(error){
    if(error.code==='ENOENT'||error.code==='ESRCH'){
      const state=leaderState(fd,pid);
      if(!state||state.dead)return null;
    }
    throw error;
  }
  const path=membership.match(/^0::(\/[^\n]*)\n$(?![\s\S])/);
  need(path&&path[1].split('/').every(part=>part!=='.'&&part!=='..'),'cgroup_leader_membership');
  const after=leaderState(fd,pid);
  if(!after||after.dead)return null;
  need(before.start_ticks===after.start_ticks,'cgroup_leader_changed');
  return Object.freeze({pid,start_ticks:after.start_ticks,group_path:path[1]});
}

function openLeader(pid){
  need(Number.isInteger(pid)&&pid>1&&pid<=2147483647,'cgroup_leader_pid');
  const fd=fs.openSync(procRoot+'/'+pid,directoryFlags);
  try{
    need(fs.statfsSync(fdPath(fd)).type===procMagic,'cgroup_filesystem');
    return fd;
  }catch(error){fs.closeSync(fd);throw error;}
}

export function readLinuxCgroupLeader(pid){
  const fd=openLeader(pid);
  try{
    const leader=readLeader(fd,pid);
    need(leader!==null,'cgroup_leader_missing');
    return leader;
  }finally{fs.closeSync(fd);}
}

function populated(fd){
  const events=readText(fdPath(fd)+'/cgroup.events',cgroupMagic);
  const values=events.split('\n').filter(line=>line.startsWith('populated '));
  need(values.length===1&&['populated 0','populated 1'].includes(values[0]),'cgroup_events');
  return values[0]==='populated 1';
}

export function readLinuxCgroupParent({driver,generationId,role,host}={}){
  const {groupPath}=linuxContainerCgroup({driver,generationId,role});
  const local=assertHost(host),location=cgroupRoot+groupPath;
  const fd=fs.openSync(location,directoryFlags);
  try{
    const group=descriptorIdentity(fd);
    need(group.device===local.root.device&&fs.statfsSync(fdPath(fd)).type===cgroupMagic,'cgroup_filesystem');
    const live=populated(fd);
    assertHost(local);
    need(fs.fstatSync(fd).nlink>0&&sameIdentity(group,pathIdentity(location)),'cgroup_group_changed');
    return Object.freeze({group,populated:live});
  }finally{fs.closeSync(fd);}
}

function composeMount(processPath,groupPath,mountFd){
  const descriptor=readText(procRoot+'/self/fdinfo/'+mountFd,procMagic);
  const id=descriptor.match(/^mnt_id:\s+([0-9]+)$/m)?.[1];
  const mounts=readText(processPath+'/mountinfo',procMagic,131072).split('\n').map(line=>line.split(' '))
    .filter(fields=>fields[4]===cgroupRoot);
  const fields=mounts[0],separator=fields?.indexOf('-')??-1;
  need(id&&mounts.length===1&&separator>5&&fields[0]===id&&fields[3]===groupPath&&
    fields[5].split(',').includes('ro')&&fields[separator+1]==='cgroup2','cgroup_compose_mount');
  return id;
}

export function observeLinuxComposeCore({driver,generationId,role,host,leader,containerId,uid,gid}){
  const {groupPath:parent}=linuxContainerCgroup({driver,generationId,role});
  const local=assertHost(host);
  need(typeof containerId==='string'&&/^[a-f0-9]{64}$(?![\s\S])/.test(containerId),'cgroup_compose_container');
  const member=driver==='systemd'?'docker-'+containerId+'.scope':containerId;
  const group_path=parent+'/'+member,location=cgroupRoot+group_path;
  need(leader?.group_path===group_path,'cgroup_compose_container');
  const processFd=openLeader(leader.pid),processPath=fdPath(processFd);
  let groupFd,mountFd;
  try{
    need(sameLeader(readLeader(processFd,leader.pid),leader),'cgroup_leader_changed');
    groupFd=fs.openSync(location,directoryFlags);
    mountFd=fs.openSync(processPath+'/root'+cgroupRoot,directoryFlags);
    const group=descriptorIdentity(groupFd),mount=descriptorIdentity(mountFd);
    need(fs.statfsSync(fdPath(groupFd)).type===cgroupMagic&&fs.statfsSync(fdPath(mountFd)).type===cgroupMagic&&
      group.device===local.root.device&&sameIdentity(group,mount),'cgroup_compose_mount');
    const cgroup_namespace=pathIdentity(processPath+'/ns/cgroup'),mount_namespace=pathIdentity(processPath+'/ns/mnt');
    need(!sameIdentity(cgroup_namespace,local.cgroup_namespace)&&!sameIdentity(mount_namespace,local.mount_namespace),
      'cgroup_compose_namespace');
    const cgroup_mount_id=composeMount(processPath,group_path,mountFd);
    const status=new Map(readText(processPath+'/status',procMagic,32768).split('\n').filter(line=>line.includes(':'))
      .map(line=>{const end=line.indexOf(':');return [line.slice(0,end),line.slice(end+1).trim()];}));
    const account=(field,id)=>Number.isInteger(id)&&id>0&&status.get(field)?.split(/\s+/).join(' ')===Array(4).fill(id).join(' ');
    need(account('Uid',uid)&&account('Gid',gid)&&status.get('NoNewPrivs')==='1'&&
      ['CapInh','CapPrm','CapEff','CapAmb'].every(field=>/^0+$/.test(status.get(field)??'')),'cgroup_compose_account');
    assertHost(local);
    need(sameLeader(readLeader(processFd,leader.pid),leader)&&populated(groupFd)&&fs.fstatSync(groupFd).nlink>0&&
      sameIdentity(group,pathIdentity(location))&&sameIdentity(mount,pathIdentity(processPath+'/root'+cgroupRoot))&&
      sameIdentity(cgroup_namespace,pathIdentity(processPath+'/ns/cgroup'))&&sameIdentity(mount_namespace,pathIdentity(processPath+'/ns/mnt'))&&
      composeMount(processPath,group_path,mountFd)===cgroup_mount_id,
      'cgroup_compose_changed');
    return Object.freeze({format:'leafseamer.compose-core-containment/1',container_id:containerId,leader,group_path,group,
      cgroup_namespace,mount_namespace,cgroup_mount_id});
  }finally{
    if(mountFd!==undefined)fs.closeSync(mountFd);
    if(groupFd!==undefined)fs.closeSync(groupFd);
    fs.closeSync(processFd);
  }
}

export function observeLinuxMemberRetirement({driver,generationId,role,host,parent,core,leader,uid},terminate=false){
  const {groupPath}=linuxContainerCgroup({driver,generationId,role});
  const local=assertHost(host),location=cgroupRoot+groupPath,corePath=location+'/core';
  need(leader?.group_path===groupPath+'/core'&&Number.isSafeInteger(uid)&&uid>0,'cgroup_retirement_scope');
  const parentFd=fs.openSync(location,directoryFlags);
  let coreFd;
  function protect(file){
    const entry=fs.lstatSync(file,{bigint:true}),procs=fs.lstatSync(file+'/cgroup.procs',{bigint:true});
    const trusted=stat=>(stat.uid===0n||stat.uid===BigInt(process.geteuid()))&&stat.uid!==BigInt(uid)&&(stat.mode&0o022n)===0n;
    need(entry.isDirectory()&&procs.isFile()&&trusted(entry)&&trusted(procs),'cgroup_retirement_permissions');
  }
  function assertCurrent(){
    assertHost(local);
    need(parent.device===local.root.device&&core.device===parent.device&&
      sameIdentity(parent,descriptorIdentity(parentFd))&&sameIdentity(core,descriptorIdentity(coreFd))&&
      fs.fstatSync(parentFd).nlink>0&&fs.fstatSync(coreFd).nlink>0&&
      sameIdentity(parent,pathIdentity(location))&&sameIdentity(core,pathIdentity(corePath)),'cgroup_group_changed');
    protect(cgroupRoot);protect(location);protect(corePath);
  }
  function currentLeader(){
    let fd;
    try{fd=openLeader(leader.pid);}
    catch(error){if(error.code==='ENOENT'||error.code==='ESRCH')return null;throw error;}
    try{
      const current=readLeader(fd,leader.pid);
      need(current===null||sameLeader(current,leader),'cgroup_leader_changed');
      return current;
    }finally{fs.closeSync(fd);}
  }
  try{
    coreFd=fs.openSync(fdPath(parentFd)+'/core',directoryFlags);
    need(fs.statfsSync(fdPath(parentFd)).type===cgroupMagic&&fs.statfsSync(fdPath(coreFd)).type===cgroupMagic,
      'cgroup_filesystem');
    assertCurrent();currentLeader();
    if(terminate&&populated(parentFd)){
      const handle=fs.openSync(fdPath(parentFd)+'/cgroup.kill',fs.constants.O_WRONLY|fs.constants.O_NOFOLLOW);
      try{
        need(fs.fstatSync(handle).isFile()&&fs.statfsSync(fdPath(handle)).type===cgroupMagic,'cgroup_filesystem');
        assertCurrent();
        need(fs.writeSync(handle,'1')===1,'cgroup_retirement_signal');
      }finally{fs.closeSync(handle);}
    }
    const live=populated(parentFd),current=currentLeader();
    need(live||current===null,'cgroup_leader_live');
    assertCurrent();
    return Object.freeze({host:local,group_path:groupPath,parent,core,leader,populated:live});
  }finally{
    if(coreFd!==undefined)fs.closeSync(coreFd);
    fs.closeSync(parentFd);
  }
}

// An empty observation must be combined with the supervisor's separate launch-intake closure.
export function openLinuxCgroupRetirement({driver,generationId,role,host,leader}={}){
  const {groupPath}=linuxContainerCgroup({driver,generationId,role});
  const local=assertHost(host),location=cgroupRoot+groupPath;
  let groupFd,leaderFd,closed=false,loss=null;
  function close(){
    if(closed)return;
    closed=true;
    try{if(leaderFd!==undefined)fs.closeSync(leaderFd);}
    finally{if(groupFd!==undefined)fs.closeSync(groupFd);}
  }
  try{
    groupFd=fs.openSync(location,directoryFlags);
    const group=descriptorIdentity(groupFd);
    need(group.device===local.root.device&&fs.statfsSync(fdPath(groupFd)).type===cgroupMagic,'cgroup_filesystem');
    function assertCurrent(){
      assertHost(local);
      need(fs.fstatSync(groupFd).nlink>0&&sameIdentity(group,pathIdentity(location)),'cgroup_group_changed');
    }
    const pid=leader?.pid;
    leaderFd=openLeader(pid);
    const original=readLeader(leaderFd,pid);
    need(original&&sameLeader(original,leader)&&original.group_path.startsWith(groupPath+'/'),'cgroup_leader_scope');
    need(populated(groupFd)&&sameLeader(readLeader(leaderFd,pid),original),'cgroup_leader_changed');
    assertCurrent();
    const scope=Object.freeze({driver,generation_id:generationId,role,host:local,group_path:groupPath,group,leader:original});
    function checkLeader(){
      const current=readLeader(leaderFd,pid);
      need(current===null||sameLeader(current,original),'cgroup_leader_changed');
      return current;
    }
    return Object.freeze({scope,close,observe(){
      need(!closed,'cgroup_observer_closed');
      if(!loss){
        try{
          assertCurrent();
          checkLeader();
          const live=populated(groupFd);
          const current=checkLeader();
          need(live||current===null,'cgroup_leader_live');
          assertCurrent();
          return Object.freeze({scope,result:live?'populated':'empty'});
        }catch(error){loss=/^cgroup_[a-z_]+$/.test(error.code??'')?error.code:'cgroup_observation_lost';}
      }
      return Object.freeze({scope,result:'indeterminate',reason:loss});
    }});
  }catch(error){close();throw error;}
}
