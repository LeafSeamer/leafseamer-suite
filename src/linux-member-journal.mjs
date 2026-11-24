import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {InstallationError,canonical,digest,requireValue as need} from './import-input.mjs';
import {linuxContainerCgroup,observeLinuxMemberRetirement,readLinuxCgroupHost,readLinuxCgroupLeader,readLinuxCgroupParent} from './linux-cgroup-retirement.mjs';
import {admitLinuxMember,validateLinuxBootstrapPolicy} from './linux-member-bootstrap.mjs';
import {bindLinuxWorkerControl} from './linux-worker-control.mjs';

const sql=fs.readFileSync(new URL('./linux-member-journal.sql',import.meta.url),'utf8');
const retirementSql=fs.readFileSync(new URL('./linux-member-retirement.sql',import.meta.url),'utf8');
const currentSql=sql+'\n'+retirementSql;
const applicationId=0x4c534c4d;
const hash=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$(?![\s\S])/;
const sha=/^sha256:[0-9a-f]{64}$(?![\s\S])/;
const rawSha=/^[0-9a-f]{64}$(?![\s\S])/;
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const matches=(value,pattern)=>typeof value==='string'&&pattern.test(value);
const descriptor=stat=>({device:String(stat.dev),inode:String(stat.ino)});
const same=(left,right)=>canonical(left)===canonical(right);
const fileIdentity=file=>{
  const stat=fs.lstatSync(file,{bigint:true});
  need(stat.isFile()&&stat.nlink===1n,'linux_member_file_identity');
  return descriptor(stat);
};

function intent(value){
  need(fields(value,'args,database_instance_id,driver,generation_id,gid,image_path,image_sha256,launch_id,role,service_id,uid')&&
    [value.database_instance_id,value.generation_id,value.launch_id,value.service_id].every(id=>matches(id,uuid))&&
    [value.uid,value.gid].every(id=>Number.isSafeInteger(id)&&id>0&&id<0xffffffff)&&
    typeof value.image_path==='string'&&value.image_path.length<=4096&&path.isAbsolute(value.image_path)&&
    !value.image_path.includes('\0')&&path.normalize(value.image_path)===value.image_path&&
    matches(value.image_sha256,sha)&&Array.isArray(value.args)&&value.args.length<=64&&
    value.args.every(arg=>typeof arg==='string'&&!arg.includes('\0')&&Buffer.byteLength(arg)<=4096),
  'linux_member_intent');
  const body=canonical(value);
  need(Buffer.byteLength(body)<=16384,'linux_member_intent');
  const group=linuxContainerCgroup({driver:value.driver,generationId:value.generation_id,role:value.role});
  return {spec:JSON.parse(body),groupPath:group.groupPath+'/core'};
}

function pinExecutable(file,expected,maximum){
  need(fs.realpathSync.native(file)===file,'linux_member_artifact_path');
  const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  try{
    const info=fs.fstatSync(fd,{bigint:true});
    need(info.isFile()&&info.nlink===1n&&info.uid===0n&&(info.mode&0o6022n)===0n&&info.size>0n&&info.size<=BigInt(maximum),
      'linux_member_artifact');
    const sum=crypto.createHash('sha256'),bytes=Buffer.alloc(65536);
    let offset=0;
    while(offset<Number(info.size)){
      const count=fs.readSync(fd,bytes,0,Math.min(bytes.length,Number(info.size)-offset),offset);
      need(count>0,'linux_member_artifact');
      sum.update(bytes.subarray(0,count));offset+=count;
    }
    const after=fs.fstatSync(fd,{bigint:true});
    need(after.size===info.size&&after.mtimeNs===info.mtimeNs&&after.ctimeNs===info.ctimeNs&&
      'sha256:'+sum.digest('hex')===expected,'linux_member_artifact_digest');
    return {fd,identity:descriptor(info),mtime:info.mtimeNs,ctime:info.ctimeNs};
  }catch(error){fs.closeSync(fd);throw error;}
}

const helperFile=fileURLToPath(new URL('./native/leafseamer_linux_member',import.meta.url));
export function pinLinuxHelper(helperFile,file,format){
  const stat=fs.lstatSync(file,{bigint:true});
  need(stat.isFile()&&stat.uid===0n&&(stat.mode&0o022n)===0n&&stat.size<=4096n,'linux_member_helper_manifest');
  for(let directory=path.dirname(helperFile);directory!=='/';directory=path.dirname(directory)){
    const info=fs.lstatSync(directory,{bigint:true});
    const sticky=(directory==='/tmp'||directory==='/var/tmp')&&(info.mode&0o1000n)!==0n;
    need(info.isDirectory()&&info.uid===0n&&((info.mode&0o022n)===0n||sticky),'linux_member_helper_manifest');
  }
  const value=JSON.parse(fs.readFileSync(file,'utf8'));
  need(fields(value,'arch,binary_sha256,format,platform,source_sha256')&&value.format===format&&
    value.arch===process.arch&&value.platform==='linux'&&matches(value.binary_sha256,rawSha)&&matches(value.source_sha256,rawSha),
  'linux_member_helper_manifest');
  const digest='sha256:'+value.binary_sha256;
  return {...pinExecutable(helperFile,digest,4*1024*1024),digest};
}
function pinHelper(){
  return pinLinuxHelper(helperFile,new URL('./native/linux-member-manifest.json',import.meta.url),'leafseamer-linux-member/1');
}

function groupIdentity(groupPath){
  const location='/sys/fs/cgroup'+groupPath;
  need(fs.realpathSync.native(location)===location&&fs.statfsSync(location).type===0x63677270,'linux_member_group');
  const stat=fs.lstatSync(location,{bigint:true});
  need(stat.isDirectory(),'linux_member_group');
  return descriptor(stat);
}

function nativeFrames(stream){
  const reader=stream[Symbol.asyncIterator]();
  let pending=Buffer.alloc(0);
  return async (phase,group,image)=>{
    for(;;){
      const newline=pending.indexOf(10);
      if(newline>=0){
        const frame=JSON.parse(pending.subarray(0,newline).toString('utf8'));
        pending=pending.subarray(newline+1);
        need(fields(frame,'group_device,group_inode,image_device,image_inode,phase,pid')&&frame.phase===phase&&
          frame.group_device===group.device&&frame.group_inode===group.inode&&frame.image_device===image.device&&
          frame.image_inode===image.inode&&Number.isSafeInteger(frame.pid)&&frame.pid>1,'linux_member_native_frame');
        return frame.pid;
      }
      const next=await reader.next();
      need(!next.done&&pending.length+next.value.length<=1024,'linux_member_native_frame');
      pending=Buffer.concat([pending,next.value]);
    }
  };
}

export function linuxMemberJournal({root,installation,available,database,pragma,checkSchema,create,upgrade=false,assertCurrent,onClose}){
  need(process.platform==='linux','linux_member_platform');
  const file=path.join(root,'linux-member.db'),marker=path.join(root,'linux-member.marker');
  available();
  const installationDirectory=fs.lstatSync(root,{bigint:true});
  need(installationDirectory.uid===BigInt(process.geteuid())&&(installationDirectory.mode&0o022n)===0n,'linux_member_directory');
  let db;
  try{
    if(create){
      need(!fs.existsSync(file)&&!fs.existsSync(marker),'linux_member_initialized');
      fs.closeSync(fs.openSync(file,'wx',0o600));
    }
    const identity={format:'leafseamer.linux-member-journal/1',host_installation_id:installation.host_installation_id,
      database_instance_id:installation.database_instance_id,installation_epoch:installation.installation_epoch,
      file_identity:fileIdentity(file),schema_digest:hash(sql)};
    const identityText=canonical(identity);
    db=database(file);
    if(create){
      need(pragma(db,'journal_mode=WAL')==='wal','linux_member_database');
      db.transaction(()=>{
        db.exec(currentSql);
        pragma(db,'application_id='+applicationId);
        pragma(db,'user_version=2');
        db.prepare('INSERT INTO linux_member_identity VALUES(1,?)').run(identityText);
      }).immediate();
      const fd=fs.openSync(marker,'wx',0o600);
      try{fs.writeFileSync(fd,identityText);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
      const dir=fs.openSync(root,'r');
      try{fs.fsyncSync(dir);}finally{fs.closeSync(dir);}
      db.close();
      return Object.freeze(identity);
    }
    const markerIdentity=fileIdentity(marker);
    const version=pragma(db,'user_version');
    need(fs.statSync(marker).size<=4096&&fs.readFileSync(marker).equals(Buffer.from(identityText))&&
      pragma(db,'application_id')===applicationId&&[1,2].includes(version)&&pragma(db,'journal_mode')==='wal'&&
      pragma(db,'quick_check')==='ok'&&db.prepare('SELECT body FROM linux_member_identity WHERE singleton=1').pluck().get()===identityText,
    'linux_member_database');
    checkSchema(db,version===1?sql:currentSql);
    if(upgrade){
      if(version===1)db.transaction(()=>{
        need(pragma(db,'user_version')===1&&same(identity.file_identity,fileIdentity(file))&&same(markerIdentity,fileIdentity(marker)),
          'linux_member_file_identity');
        db.exec(retirementSql);
        pragma(db,'user_version=2');
        checkSchema(db,currentSql);
      }).exclusive();
      db.close();
      return Object.freeze({schema_revision:2,changed:version===1});
    }
    need(typeof assertCurrent==='function','linux_member_authority');
    db.exec('BEGIN EXCLUSIVE; COMMIT;');
    let closed=false,busy=false,failed=false;
    const live=new Map();
    function open(){
      available();
      need(!closed&&!failed&&db.open,'linux_member_unavailable');
      try{
        need(same(identity.file_identity,fileIdentity(file))&&same(markerIdentity,fileIdentity(marker)),'linux_member_file_identity');
      }catch(error){
        failed=true;throw new InstallationError('linux_member_file_identity',{cause:error});
      }
    }
    function lookup(id){
      open();
      need(matches(id,uuid),'linux_member_launch_id');
      const row=db.prepare('SELECT role,revision,phase,body,digest FROM linux_member_event WHERE launch_id=? ORDER BY revision DESC LIMIT 1').raw().get(id);
      if(!row)return null;
      const [role,revision,phase,body,stored]=row,record=JSON.parse(body);
      need(canonical(record)===body&&digest(record)===stored&&record.intent.launch_id===id&&record.intent.role===role&&
        record.revision===revision&&record.phase===phase,'linux_member_record_integrity');
      return record;
    }
    function append(spec,revision,phase,detail){
      open();
      const record={intent:spec,revision,phase,detail};
      try{
        db.transaction(()=>{
          if(revision===1){
            const occupied=version===1?'SELECT 1 FROM linux_member_event WHERE role=? LIMIT 1':`SELECT 1 FROM linux_member_event e
              WHERE e.role=? AND e.revision=1 AND NOT EXISTS
                (SELECT 1 FROM linux_member_retirement r WHERE r.launch_id=e.launch_id AND r.phase='retired') LIMIT 1`;
            need(!db.prepare(occupied).pluck().get(spec.role),'linux_member_previous_unretired');
            need(!db.prepare("SELECT 1 FROM linux_member_event WHERE role=? AND revision=1 AND json_extract(body,'$.intent.generation_id')=? LIMIT 1")
              .pluck().get(spec.role,spec.generation_id),'linux_member_generation_used');
          }
          db.prepare('INSERT INTO linux_member_event VALUES(?,?,?,?,?,?)').run(spec.launch_id,spec.role,revision,phase,canonical(record),digest(record));
        }).immediate();
      }catch(error){
        if(error instanceof InstallationError)throw error;
        failed=true;throw new InstallationError('linux_member_storage_unknown',{cause:error});
      }
      return record;
    }
    function authorize(record){
      need(assertCurrent(JSON.parse(canonical(record)))===true,'linux_member_authorization');
      open();
    }
    function stop(id){
      const child=live.get(id);
      if(child){child.stdin.destroy();child.stdio[3].destroy();}
    }
    function lookupRetirement(id){
      open();
      need(version===2,'linux_member_upgrade_required');
      need(matches(id,uuid),'linux_member_launch_id');
      const row=db.prepare('SELECT source_revision,revision,phase,body,digest FROM linux_member_retirement WHERE launch_id=? ORDER BY revision DESC LIMIT 1').raw().get(id);
      if(!row)return null;
      const [sourceRevision,revision,phase,body,stored]=row,record=JSON.parse(body);
      const launch=lookup(id);
      need(canonical(record)===body&&digest(record)===stored&&record.launch_id===id&&record.revision===revision&&
        record.phase===phase&&launch?.revision===sourceRevision&&same(record.source,{revision:sourceRevision,digest:digest(launch)}),
      'linux_member_retirement_integrity');
      return record;
    }
    function appendRetirement(launch,revision,phase,evidence){
      open();
      const record={launch_id:launch.intent.launch_id,revision,phase,source:{revision:launch.revision,digest:digest(launch)},evidence};
      try{
        db.transaction(()=>db.prepare('INSERT INTO linux_member_retirement VALUES(?,?,?,?,?,?)')
          .run(record.launch_id,launch.revision,revision,phase,canonical(record),digest(record))).immediate();
      }catch(error){
        failed=true;throw new InstallationError('linux_member_storage_unknown',{cause:error});
      }
      return record;
    }
    function closeIntake(id){
      need(!busy,'linux_member_busy');
      const prior=lookupRetirement(id);
      if(prior){stop(id);return prior;}
      const launch=lookup(id);
      need(launch?.detail.leader&&launch.revision>=2,'linux_member_retirement_unproven');
      try{return appendRetirement(launch,1,'closing',null);}
      finally{stop(id);}
    }
    function retire(id,terminate){
      need(!busy,'linux_member_busy');
      const prior=lookupRetirement(id);
      need(prior,'linux_member_intake_open');
      if(prior.phase==='retired')return prior;
      stop(id);
      const launch=lookup(id),{intent,detail}=launch;
      let observation;
      try{
        observation=observeLinuxMemberRetirement({driver:intent.driver,generationId:intent.generation_id,role:intent.role,
          host:detail.host,parent:detail.parent_group,core:detail.group,leader:detail.leader,uid:intent.uid},terminate);
      }catch(error){throw new InstallationError('linux_member_retirement_unproven',{cause:error});}
      if(observation.populated)return prior;
      return appendRetirement(launch,2,'retired',observation);
    }
    async function launch(input,bootstrap=null){
      open();
      need(!busy,'linux_member_busy');
      busy=true;
      let helper,image,child,executed=false;
      try{
        const {spec,groupPath}=intent(input),prior=lookup(spec.launch_id);
        const policy=bootstrap?validateLinuxBootstrapPolicy(spec,bootstrap.policy):null;
        const policyDigest=policy?digest(policy):null;
        if(prior){
          need(same(prior.intent,spec)&&(prior.detail.bootstrap_policy_digest??null)===policyDigest,'linux_member_launch_conflict');
          return {record:prior,bootstrap:null};
        }
        const host=readLinuxCgroupHost();
        const parentInput={driver:spec.driver,generationId:spec.generation_id,role:spec.role,host};
        const parent=readLinuxCgroupParent(parentInput);
        const group=groupIdentity(groupPath);
        need(!parent.populated&&group.device===parent.group.device,'linux_member_group');
        helper=pinHelper();
        image=pinExecutable(spec.image_path,spec.image_sha256,256*1024*1024);
        const detail={host,parent_group:parent.group,group_path:groupPath,group,image:image.identity,helper_digest:helper.digest,
          ...(policy&&{bootstrap_policy_digest:policyDigest})};
        function checkGroup(){
          const current=readLinuxCgroupParent(parentInput);
          need(current.populated&&same(parent.group,current.group)&&same(group,groupIdentity(groupPath)),
            'linux_member_group_changed');
        }
        const reserved=append(spec,1,'reserved',detail);
        authorize(reserved);
        child=spawn('/proc/self/fd/4',['/sys/fs/cgroup'+groupPath,group.device,group.inode,spec.image_path,
          image.identity.device,image.identity.inode,String(spec.uid),String(spec.gid),'--',...spec.args],
        {stdio:['pipe','pipe','ignore','pipe',helper.fd],env:{LANG:'C',LC_ALL:'C',PATH:'/usr/bin:/bin'}});
        child.on('error',()=>{});
        child.stdin.on('error',()=>{});
        child.stdio[3].on('error',()=>{});
        const member=child;
        member.once('close',()=>live.delete(spec.launch_id));
        const frames=nativeFrames(member.stdout),pid=await frames('created_closed',group,image.identity);
        const leader=readLinuxCgroupLeader(pid);
        need(leader.group_path===groupPath,'linux_member_group_changed');
        checkGroup();
        const closedRecord=append(spec,2,'created_closed',{...detail,leader});
        authorize(closedRecord);
        const currentImage=fs.fstatSync(image.fd,{bigint:true});
        need(same(image.identity,fileIdentity(spec.image_path))&&currentImage.mtimeNs===image.mtime&&currentImage.ctimeNs===image.ctime,
          'linux_member_artifact_changed');
        checkGroup();
        append(spec,3,'release_requested',closedRecord.detail);
        member.stdin.write('R');
        need(await frames('executed',group,image.identity)===pid&&same(leader,readLinuxCgroupLeader(pid)),
          'linux_member_execution_changed');
        checkGroup();
        function assertCoreCurrent(){
          open();checkGroup();
          need(same(leader,readLinuxCgroupLeader(pid)),'linux_member_execution_changed');
        }
        const socket=member.stdio[3];
        function commit(admission){
          assertCoreCurrent();
          const detail={...closedRecord.detail,...(admission&&{admission})};
          if(admission)authorize({intent:spec,revision:4,phase:'executed_closed',detail});
          const record=append(spec,4,'executed_closed',detail);
          if(bootstrap?.workerControl)bindLinuxWorkerControl({directory:root,socket,core:admission,source:bootstrap.source,
            assertLive:assertCoreCurrent,checkGroup(intent){
              const group_path=groupPath.slice(0,-'/core'.length)+'/worker_'+intent.launch_id.replaceAll('-','');
              try{
                const worker=groupIdentity(group_path),directory='/sys/fs/cgroup'+group_path;
                const stat=fs.lstatSync(directory,{bigint:true}),procs=fs.lstatSync(directory+'/cgroup.procs',{bigint:true});
                return stat.uid===BigInt(process.geteuid())&&(stat.mode&0o022n)===0n&&
                  procs.isFile()&&procs.uid===stat.uid&&(procs.mode&0o022n)===0n&&
                  /^populated 0$/m.test(fs.readFileSync(directory+'/cgroup.events','utf8'))&&
                  intent.containment_ref.group_id==='group_'+digest({boot_id:host.boot_id,group_path,group:worker}).slice(7);
              }catch(error){if(error.code==='ENOENT')return false;throw error;}
            }});
          return record;
        }
        const record=bootstrap?await admitLinuxMember(closedRecord,{policy,source:bootstrap.source,socket,commit}):commit(null);
        if(bootstrap){
          const stop=()=>{member.stdin.destroy();socket.destroy();};
          socket.once('end',stop).once('error',stop).once('close',stop);
          if(!bootstrap.workerControl)socket.once('data',stop);
          socket.resume();
        }
        live.set(spec.launch_id,member);executed=true;
        return {record,bootstrap:bootstrap?null:socket};
      }finally{
        busy=false;
        if(child&&!executed){child.stdin.destroy();child.stdio[3].destroy();}
        if(image)fs.closeSync(image.fd);
        if(helper)fs.closeSync(helper.fd);
      }
    }
    return Object.freeze({schemaRevision:version,lookup,lookupRetirement,closeIntake,observeRetirement:id=>retire(id,false),terminateRetirement:id=>retire(id,true),
      launch:input=>launch(input),admit(input,{policy,source,workerControl=false}={}){
      need(source&&typeof source.capture==='function'&&typeof source.tick==='function','linux_bootstrap_clock');
      need(workerControl===false||workerControl===true&&input.role==='controller'&&version===2,'linux_worker_control_scope');
      return launch(input,{policy,source,workerControl});
    },close(){
      if(closed)return;
      need(!busy,'linux_member_busy');
      closed=true;
      for(const id of live.keys())stop(id);
      try{db.close();}finally{onClose();}
    }});
  }catch(error){
    if(db?.open)db.close();
    if(error instanceof InstallationError)throw error;
    throw new InstallationError(create?'linux_member_initialization_incomplete':'linux_member_unavailable',{cause:error});
  }
}
