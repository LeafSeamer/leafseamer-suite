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

function readText(file,type){
  const fd=fs.openSync(file,fileFlags);
  try{
    need(fs.fstatSync(fd).isFile()&&fs.statfsSync(fdPath(fd)).type===type,'cgroup_filesystem');
    const bytes=Buffer.alloc(4097);
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
