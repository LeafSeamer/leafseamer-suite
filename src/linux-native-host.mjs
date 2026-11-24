import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {readDeploymentFile} from './linux-ingress.mjs';
import {openInstallationStore} from './installation-store.mjs';
import {validateLinuxBootstrapPolicy} from './linux-member-bootstrap.mjs';
import {linuxContainerCgroup} from './linux-cgroup-retirement.mjs';
import {pinExecutable} from './linux-native-artifact.mjs';

const sha=/^sha256:[a-f0-9]{64}$(?![\s\S])/;
const filename=/^[A-Za-z0-9_.-]+$(?![\s\S])/;
const hash=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const same=(left,right)=>canonical(left)===canonical(right);

function absolute(value){
  need(typeof value==='string'&&value.length<=4096&&path.isAbsolute(value)&&value!=='/'&&
    !value.includes('\0')&&!value.endsWith('/')&&path.normalize(value)===value,'linux_native_path');
  return value;
}

function protectedPath(file,{directory=false,uid=0}={}){
  absolute(file);
  const stat=fs.lstatSync(file);
  need((directory?stat.isDirectory():stat.isFile())&&stat.uid===uid&&(stat.mode&0o022)===0,'linux_native_path');
  for(let parent=path.dirname(file);;parent=path.dirname(parent)){
    const entry=fs.lstatSync(parent);
    const temporary=(parent==='/tmp'||parent==='/var/tmp')&&(entry.mode&0o1000)!==0;
    const owner=entry.uid===0||entry.uid===process.geteuid();
    need(entry.isDirectory()&&owner&&((entry.mode&0o022)===0||temporary),'linux_native_path');
    if(parent==='/')return;
  }
}

function pinnedFile(file,expected,limit){
  need(typeof expected==='string'&&sha.test(expected),'linux_native_digest');
  protectedPath(file);
  const bytes=readDeploymentFile(file,limit);
  need(hash(bytes)===expected,'linux_native_artifact_changed');
  return bytes;
}

function profile(reference,format,identity){
  need(fields(reference,'file,sha256'),'linux_native_profile');
  const value=JSON.parse(pinnedFile(reference.file,reference.sha256,65536));
  need(value?.format===format,'linux_native_profile');
  const bound=value.scope??value.bootstrap??value;
  need(bound.service_id===identity.service_id&&bound.database_instance_id===identity.database_instance_id,'linux_native_profile');
  return value;
}

function inspectDistribution(root,expected,role){
  protectedPath(root,{directory:true});
  const manifest=JSON.parse(pinnedFile(path.join(root,'build-manifest.json'),expected,262144));
  need(manifest?.format==='leafseamer-'+role+'-build/1'&&manifest.artifacts&&
    typeof manifest.artifacts==='object'&&!Array.isArray(manifest.artifacts)&&Object.hasOwn(manifest.artifacts,'cli.mjs'),
  'linux_native_manifest');
  const assets=Object.entries(manifest.artifacts);
  need(assets.length>0&&assets.length<=1024,'linux_native_manifest');
  const expectedFiles=new Map(),expectedDirectories=new Set();
  for(const [relative,checksum] of assets){
    const parts=relative.split('/');
    need(parts.length<=16&&relative!=='build-manifest.json'&&parts.every(part=>part!=='.'&&part!=='..'&&filename.test(part))&&
      typeof checksum==='string'&&/^[a-f0-9]{64}$(?![\s\S])/.test(checksum),'linux_native_manifest');
    expectedFiles.set(relative,checksum);
    for(let i=1;i<parts.length;i++)expectedDirectories.add(parts.slice(0,i).join('/'));
  }
  let total=0;
  function visit(directory,prefix=''){
    protectedPath(directory,{directory:true});
    for(const entry of fs.readdirSync(directory,{withFileTypes:true})){
      const file=path.join(directory,entry.name),relative=prefix+entry.name;
      if(relative==='build-manifest.json')continue;
      if(entry.isDirectory()){
        need(expectedDirectories.has(relative),'linux_native_manifest');
        visit(file,relative+'/');
      }else{
        const checksum=expectedFiles.get(relative);
        need(entry.isFile()&&checksum!==undefined,'linux_native_manifest');
        total+=pinnedFile(file,'sha256:'+checksum,16777216).length;
        need(total<=67108864,'linux_native_manifest');
        expectedFiles.delete(relative);
      }
    }
  }
  visit(root);
  need(expectedFiles.size===0,'linux_native_manifest');
}

function protectedDependencies(distribution){
  const examined=new Set();
  let entries=0;
  function visit(file){
    const stat=fs.lstatSync(file);
    need(++entries<=32768&&stat.uid===0,'linux_native_dependency');
    if(stat.isSymbolicLink()){
      const actual=fs.realpathSync.native(file),target=fs.lstatSync(actual);
      protectedPath(actual,{directory:target.isDirectory()});
      visit(actual);
      return;
    }
    need((stat.isDirectory()||stat.isFile())&&(stat.mode&0o022)===0,'linux_native_dependency');
    if(!stat.isDirectory()||examined.has(file))return;
    examined.add(file);
    for(const entry of fs.readdirSync(file))visit(path.join(file,entry));
  }
  for(let directory=distribution;;directory=path.dirname(directory)){
    const dependencies=path.join(directory,'node_modules'),stat=fs.lstatSync(dependencies,{throwIfNoEntry:false});
    if(stat)visit(dependencies);
    if(directory==='/')return;
  }
}

export function composeLinuxWorkerRuntime(config,controller,policy,installation){
  const {distribution,image,uid,gid}=config;
  const directory=absolute(config.directory),channelDirectory=absolute(config.channel_directory);
  const entry=path.join(absolute(distribution.directory),'device-worker-entry.mjs');
  const image_path=absolute(image.file),image_sha256=image.sha256;
  need(policy.artifact_manifest_ref.digest===digest({controller_build_sha256:distribution.manifest_sha256.slice(7),
    node_sha256:image_sha256.slice(7)}),'linux_native_manifest');
  const paths=[directory,channelDirectory],initial=paths.map(dir=>{
    protectedPath(dir,{directory:true});return fs.lstatSync(dir,{bigint:true});
  });
  const runtime={uid,gid,directory,channelDirectory,entry,
    acquire:(...args)=>installation.acquireLinuxWorkerMaterialization(...args),
    assertCurrent(){
      for(const [index,dir] of paths.entries()){
        protectedPath(dir,{directory:true});const actual=fs.lstatSync(dir,{bigint:true});
        need(actual.dev===initial[index].dev&&actual.ino===initial[index].ino,'linux_worker_directory_changed');
      }
      inspectDistribution(distribution.directory,distribution.manifest_sha256,'controller');
      protectedDependencies(distribution.directory);protectedPath(entry);
    }};
  runtime.assertCurrent();
  const executable=pinExecutable(image_path,image_sha256,256*1024*1024);
  fs.closeSync(executable.fd);
  return {runtime,spec:{uid:controller.uid,gid:controller.gid,service_id:controller.service_id,
    database_instance_id:controller.database_instance_id,image_path,image_sha256}};
}

// 受信宿主传入本机时钟和已批准的计划摘要，运行账户只能读取安装物。
export function openLinuxNativeHost({installationDirectory,source}={}){
  need(process.platform==='linux','linux_native_host');
  need(source&&typeof source.capture==='function'&&typeof source.tick==='function','linux_bootstrap_clock');
  protectedPath(installationDirectory,{directory:true,uid:process.geteuid()});
  const installation=openInstallationStore(installationDirectory);
  let openPlan=null,journal;
  const verifyPlan=(file,expected)=>JSON.parse(pinnedFile(file,expected,65536));
  function verifyInputs(plan,spec,policy){
    const {distribution,clock_profile,pairing_profile,data_directory}=plan;
    protectedPath(spec.image_path);
    inspectDistribution(distribution.directory,distribution.manifest_sha256,spec.role);
    protectedDependencies(distribution.directory);
    protectedPath(data_directory,{directory:true,uid:spec.uid});
    profile(clock_profile,'leafseamer.'+spec.role+'-linux-clock-evidence-profile/2',spec);
    const pairing=profile(pairing_profile,'leafseamer.'+spec.role+'-pairing-profile/2',spec);
    if(spec.role==='controller')need(same(pairing.bootstrap,policy),'linux_native_profile');
  }
  try{
    journal=installation.openLinuxMemberJournal(record=>{
      need(openPlan!==null&&same(record.intent,openPlan.spec),'linux_native_plan');
      const {file,expected,spec,policy}=openPlan;
      verifyInputs(verifyPlan(file,expected),spec,policy);
      return true;
    });
    need(journal.schemaRevision===2,'linux_member_upgrade_required');
    const idle=()=>need(openPlan===null,'linux_member_busy');
    return Object.freeze({
      lookup(launchId){return {launch:journal.lookup(launchId),retirement:journal.lookupRetirement(launchId)};},
      async start({planFile,planDigest}={}){
        idle();
        const file=absolute(planFile);
        need(path.dirname(file)===path.join(installationDirectory,'linux-native'),'linux_native_plan_path');
        const plan=verifyPlan(file,planDigest);
        const required='bootstrap,clock_profile,data_directory,distribution,driver,format,generation_id,gid,host_installation_id,image,launch_id,pairing_profile,port,role,uid';
        const workerControl=plan.worker_control===true,workerRuntime=plan.worker_runtime;
        need(fields(plan,required+(workerControl?',worker_control':'')+(workerRuntime?',worker_runtime':''))&&(!workerControl||plan.role==='controller')&&
          (!workerRuntime||workerControl&&(fields(workerRuntime,'directory,gid,uid')||fields(workerRuntime,'channel_directory,directory,gid,uid')))&&
          plan.format==='leafseamer.linux-native-core/1'&&plan.host_installation_id===installation.identity.host_installation_id&&
          fields(plan.distribution,'directory,manifest_sha256')&&fields(plan.image,'file,sha256')&&
          fields(plan.clock_profile,'file,sha256')&&fields(plan.pairing_profile,'file,sha256')&&
          Number.isInteger(plan.port)&&plan.port>0&&plan.port<=65535,'linux_native_plan');
        const {role,driver,generation_id,launch_id,uid,gid,bootstrap,distribution,image}=plan;
        linuxContainerCgroup({role,driver,generationId:generation_id});
        need(uid!==process.geteuid(),'linux_native_account');
        need(typeof image.sha256==='string'&&sha.test(image.sha256)&&typeof distribution.manifest_sha256==='string'&&
          sha.test(distribution.manifest_sha256),'linux_native_digest');
        const service_id=bootstrap?.service_id,database_instance_id=bootstrap?.database_instance_id;
        const spec={role,driver,generation_id,launch_id,uid,gid,service_id,database_instance_id,image_path:absolute(image.file),image_sha256:image.sha256,
          args:['--disallow-code-generation-from-strings',path.join(absolute(distribution.directory),'cli.mjs'),'contained-core-linux',
            '--data-dir',absolute(plan.data_directory),'--port',String(plan.port),'--bootstrap-policy',canonical(bootstrap),
            '--clock-evidence-profile',absolute(plan.clock_profile.file),'--pairing-profile',absolute(plan.pairing_profile.file),
            ...(workerControl?['--worker-control','inherited']:[]),
            ...(workerRuntime&&Object.hasOwn(workerRuntime,'channel_directory')?['--worker-channel-dir',absolute(workerRuntime.channel_directory)]:[])]};
        const policy=validateLinuxBootstrapPolicy(spec,bootstrap);
        need(policy.artifact_manifest_ref.digest===digest({[role+'_build_sha256']:distribution.manifest_sha256.slice(7),node_sha256:image.sha256.slice(7)}),
          'linux_native_manifest');
        verifyInputs(plan,spec,policy);
        const runtime=workerRuntime?{uid:workerRuntime.uid,gid:workerRuntime.gid,directory:absolute(workerRuntime.directory),
          channelDirectory:Object.hasOwn(workerRuntime,'channel_directory')?absolute(workerRuntime.channel_directory):null,
          entry:path.join(absolute(distribution.directory),'device-worker-entry.mjs'),
          acquire:(...args)=>installation.acquireLinuxWorkerMaterialization(...args),
          assertCurrent(){verifyInputs(verifyPlan(file,planDigest),spec,policy);protectedPath(this.entry);
            if(this.channelDirectory){
              need(Buffer.byteLength(this.channelDirectory)<=60,'linux_worker_channel');
              protectedPath(this.channelDirectory,{directory:true});
            }}}:null;
        runtime?.assertCurrent();
        openPlan={file,expected:planDigest,spec,policy};
        try{return (await journal.admit(spec,{policy,source,workerControl,workerRuntime:runtime})).record;}
        finally{openPlan=null;}
      },
      retire(launchId){idle();journal.closeIntake(launchId);return journal.observeRetirement(launchId);},
      close(){idle();try{journal.close();}finally{installation.close();}}
    });
  }catch(error){journal?.close();installation.close();throw error;}
}
