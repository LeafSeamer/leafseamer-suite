import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {readDeploymentFile} from './linux-ingress.mjs';
import {openInstallationStore} from './installation-store.mjs';
import {validateLinuxBootstrapPolicy} from './linux-member-bootstrap.mjs';
import {linuxContainerCgroup,readLinuxCgroupHost,readLinuxCgroupParent} from './linux-cgroup-retirement.mjs';
import {pinExecutable} from './linux-native-artifact.mjs';
import {verifyProtectedRecoveryCandidate} from './recovery-site-review.mjs';
import {publishLinuxRecoveryStorage} from './linux-recovery-storage.mjs';

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
  let openPlan=null,recoveryBusy=false,journal;
  const verifyPlan=(file,expected)=>JSON.parse(pinnedFile(file,expected,65536));
  const planDirectory=path.join(installationDirectory,'linux-native');
  function verifyInputs(plan,spec,policy,{recovery=false,verifyData=true}={}){
    const {distribution,clock_profile,pairing_profile,data_directory}=plan;
    protectedPath(spec.image_path);
    inspectDistribution(distribution.directory,distribution.manifest_sha256,spec.role);
    protectedDependencies(distribution.directory);
    if(verifyData)protectedPath(data_directory,{directory:true,uid:spec.uid});
    if(!recovery||clock_profile!==null)profile(clock_profile,'leafseamer.'+spec.role+'-linux-clock-evidence-profile/2',spec);
    if(!recovery||pairing_profile!==null){
      const pairing=profile(pairing_profile,'leafseamer.'+spec.role+'-pairing-profile/2',spec);
      if(spec.role==='controller')need(same(pairing.bootstrap,policy),'linux_native_profile');
    }
  }
  try{
    journal=installation.openLinuxMemberJournal(record=>{
      need(openPlan!==null&&same(record.intent,openPlan.spec),'linux_native_plan');
      const {file,expected,spec,policy,recovery}=openPlan;
      recovery?.assertCurrent();
      const plan=verifyPlan(file,expected);
      verifyInputs(plan,spec,policy,{recovery:!!recovery});
      if(recovery&&record.phase!=='executed_closed'){
        const name=spec.role+'.sqlite',directory=fs.lstatSync(plan.data_directory,{bigint:true});
        const stat=fs.lstatSync(path.join(plan.data_directory,name),{bigint:true}),pin=recovery.pins.get(spec.launch_id);
        const entries=fs.readdirSync(plan.data_directory);
        need(directory.gid===BigInt(spec.gid)&&(directory.mode&0o7777n)===0o700n&&entries.length===1&&entries[0]===name&&
          stat.isFile()&&stat.nlink===1n&&stat.uid===BigInt(spec.uid)&&stat.gid===BigInt(spec.gid)&&(stat.mode&0o7777n)===0o600n&&
          ['dev','ino','size','mtimeNs','ctimeNs'].every(key=>stat[key]===pin[key]),'linux_recovery_data');
      }
      return true;
    });
    need(journal.schemaRevision===2,'linux_member_upgrade_required');
    const idle=()=>need(openPlan===null&&!recoveryBusy,'linux_member_busy');
    function readCorePlan(planFile,planDigest,recovery=false){
        const file=absolute(planFile);
        need(path.dirname(file)===planDirectory,'linux_native_plan_path');
        const plan=verifyPlan(file,planDigest);
        const required='bootstrap,clock_profile,data_directory,distribution,driver,format,generation_id,gid,host_installation_id,image,launch_id,pairing_profile,port,role,uid';
        const workerControl=plan.worker_control===true,workerRuntime=plan.worker_runtime;
        need(fields(plan,required+(workerControl?',worker_control':'')+(workerRuntime?',worker_runtime':''))&&(!workerControl||plan.role==='controller')&&
          (!workerRuntime||workerControl&&(fields(workerRuntime,'directory,gid,uid')||fields(workerRuntime,'channel_directory,directory,gid,uid')))&&
          plan.format==='leafseamer.linux-native-core/1'&&plan.host_installation_id===installation.identity.host_installation_id&&
          fields(plan.distribution,'directory,manifest_sha256')&&fields(plan.image,'file,sha256')&&
          (fields(plan.clock_profile,'file,sha256')||recovery&&plan.clock_profile===null)&&
          (fields(plan.pairing_profile,'file,sha256')||recovery&&plan.pairing_profile===null)&&
          (!recovery||!workerControl&&!workerRuntime)&&
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
            ...(plan.clock_profile?['--clock-evidence-profile',absolute(plan.clock_profile.file)]:[]),
            ...(plan.pairing_profile?['--pairing-profile',absolute(plan.pairing_profile.file)]:[]),
            ...(workerControl?['--worker-control','inherited']:[]),
            ...(workerRuntime&&Object.hasOwn(workerRuntime,'channel_directory')?['--worker-channel-dir',absolute(workerRuntime.channel_directory)]:[])]};
        const policy=validateLinuxBootstrapPolicy(spec,bootstrap);
        need(policy.artifact_manifest_ref.digest===digest({[role+'_build_sha256']:distribution.manifest_sha256.slice(7),node_sha256:image.sha256.slice(7)}),
          'linux_native_manifest');
        return {file,expected:planDigest,plan,spec,policy,workerControl,workerRuntime};
    }
    async function startCore(checked,recovery=null){
        const {file,expected,plan,spec,policy,workerControl,workerRuntime}=checked,{distribution}=plan;
        recovery?.assertCurrent();
        verifyInputs(verifyPlan(file,expected),spec,policy,{recovery:!!recovery});
        const runtime=workerRuntime?{uid:workerRuntime.uid,gid:workerRuntime.gid,directory:absolute(workerRuntime.directory),
          channelDirectory:Object.hasOwn(workerRuntime,'channel_directory')?absolute(workerRuntime.channel_directory):null,
          entry:path.join(absolute(distribution.directory),'device-worker-entry.mjs'),
          acquire:(...args)=>installation.acquireLinuxWorkerMaterialization(...args),
          assertCurrent(){verifyInputs(verifyPlan(file,expected),spec,policy);protectedPath(this.entry);
            if(this.channelDirectory){
              need(Buffer.byteLength(this.channelDirectory)<=60,'linux_worker_channel');
              protectedPath(this.channelDirectory,{directory:true});
            }}}:null;
        runtime?.assertCurrent();
        openPlan={file,expected,spec,policy,recovery};
        try{return (await journal.admit(spec,{policy,source,workerControl,workerRuntime:runtime})).record;}
        finally{openPlan=null;}
    }

    async function startRecovery({planFile,selectionDigest,authorize}={}){
      idle();recoveryBusy=true;
      const admitted=[];
      try{
        const selected=installation.currentRecoverySelection();
        need(selected?.phase==='activated_protected'&&selected.selection_digest===selectionDigest&&
          typeof authorize==='function'&&process.geteuid()===0,'linux_recovery_selection');
        const {deployment,activation}=selected,archive=installation.backupMaintenance().getRecoveryPlan(activation.plan_ref.restore_id);
        need(archive?.phase==='activated_protected'&&same(archive.activation,selected),'linux_recovery_selection');
        need(archive.retirement.evidence.format==='leafseamer-linux-native-retirement/1','linux_recovery_platform');
        const file=absolute(planFile);
        need(path.dirname(file)===planDirectory,'linux_native_plan_path');
        const plan=verifyPlan(file,deployment.deployment_plan_digest);
        need(fields(plan,'configuration_refs,deployment_plan_ref,format,generation_id,release_manifest_digest,runtime_root')&&
          plan.format==='leafseamer.linux-native-recovery/1'&&plan.deployment_plan_ref===deployment.deployment_plan_ref&&
          plan.release_manifest_digest===deployment.release_manifest_digest&&plan.generation_id===deployment.generation_id&&
          fields(plan.configuration_refs,'controller,seamer')&&deployment.services.length===2,'linux_recovery_plan');
        const runtimeRoot=absolute(plan.runtime_root);
        protectedPath(runtimeRoot,{directory:true});
        const root=fs.lstatSync(runtimeRoot,{bigint:true}),destination=path.join(runtimeRoot,deployment.generation_id);
        const sourceDirectory=path.join(installationDirectory,'content',archive.preparation.attempt_id);
        const members=deployment.services.map((service,index)=>{
          const {authority}=service.scope,member=archive.preparation.services[index];
          need(service.configuration_ref===plan.configuration_refs[authority]&&filename.test(service.configuration_ref)&&
            service.data_ref.attempt_id===archive.preparation.attempt_id&&service.data_ref.directory_name===member.directory_name&&
            service.data_ref.bytes===member.bytes&&service.data_ref.sha256===member.sha256&&same(service.scope,member.next_scope),'linux_recovery_plan');
          const core=readCorePlan(path.join(planDirectory,service.configuration_ref+'.json'),service.configuration_digest,true);
          const {spec}=core;
          need([spec.uid,spec.gid].every(id=>Number.isInteger(id)&&id>0&&id<4294967295)&&
            spec.role===authority&&spec.generation_id===deployment.generation_id&&spec.service_id===service.scope.service_id&&
            spec.database_instance_id===service.scope.database_instance_id&&core.plan.data_directory===path.join(destination,member.directory_name),
            'linux_recovery_plan');
          verifyInputs(core.plan,spec,core.policy,{recovery:true,verifyData:false});
          const image=pinExecutable(spec.image_path,spec.image_sha256,256*1024*1024);
          fs.closeSync(image.fd);
          return {...core,member};
        });
        const [first,second]=members;
        need(first.spec.role!==second.spec.role&&first.spec.launch_id!==second.spec.launch_id&&first.spec.uid!==second.spec.uid&&
          first.plan.port!==second.plan.port,'linux_recovery_plan');
        const distributions=Object.fromEntries(members.map(({spec,plan})=>[spec.role,plan.distribution]));
        need(digest(distributions)===archive.preparation_intent.distributions_digest,'linux_recovery_distribution');
        const secretBindingsDigest=digest(deployment.services.map(({scope,secret_binding_ref,secret_binding_digest,secret_policy_ref})=>
          ({scope,secret_binding_ref,secret_binding_digest,secret_policy_ref})));
        const recovery={assertCurrent(){
          need(installation.currentRecoverySelection()?.selection_digest===selectionDigest,'linux_recovery_selection');
          protectedPath(runtimeRoot,{directory:true});
          const current=fs.lstatSync(runtimeRoot,{bigint:true});
          need(current.dev===root.dev&&current.ino===root.ino,'linux_recovery_plan');
          const decision=authorize(structuredClone({selection:selected,secret_bindings_digest:secretBindingsDigest}));
          need(decision?.allowed===true&&decision.selection_digest===selectionDigest&&
            decision.release_manifest_digest===deployment.release_manifest_digest&&decision.secret_bindings_digest===secretBindingsDigest,
            'linux_recovery_authority');
        }};
        recovery.assertCurrent();
        need(members.every(({spec})=>journal.lookup(spec.launch_id)===null),'linux_recovery_start_indeterminate');
        const host=readLinuxCgroupHost();
        for(const {spec} of members){
          const input={generationId:spec.generation_id,driver:spec.driver,role:spec.role};
          const {groupPath}=linuxContainerCgroup(input);
          need(!readLinuxCgroupParent({...input,host}).populated&&fs.lstatSync('/sys/fs/cgroup'+groupPath+'/core').isDirectory(),
            'linux_recovery_group');
        }
        await verifyProtectedRecoveryCandidate(path.dirname(sourceDirectory),archive.preparation,performance.now()+1800000);
        recovery.pins=await publishLinuxRecoveryStorage({destination,source:sourceDirectory,members,assertCurrent:recovery.assertCurrent});
        for(const member of members){
          admitted.push(await startCore(member,recovery));
        }
        return {selection_digest:selectionDigest,phase:'executed_closed',members:admitted};
      }catch(error){
        for(const record of admitted){
          try{journal.closeIntake(record.intent.launch_id);}catch{/* The original launch remains queryable. */}
        }
        throw error;
      }finally{recoveryBusy=false;}
    }

    return Object.freeze({
      lookup(launchId){return {launch:journal.lookup(launchId),retirement:journal.lookupRetirement(launchId)};},
      async start({planFile,planDigest}={}){
        idle();need(installation.currentRecoverySelection()?.phase!=='activated_protected','linux_recovery_start_required');
        return startCore(readCorePlan(planFile,planDigest));
      },
      startRecovery,
      retire(launchId){idle();journal.closeIntake(launchId);return journal.observeRetirement(launchId);},
      close(){idle();try{journal.close();}finally{installation.close();}}
    });
  }catch(error){journal?.close();installation.close();throw error;}
}
