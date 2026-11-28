import fs from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {openInstallationStore} from './installation-store.mjs';
import {installationContentPlatform} from './local-peer.mjs';
import {loadVerifiedDistributionModule} from './backup-domain-verification.mjs';
import {verifyProtectedRecoveryFiles} from './recovery-storage-preparation.mjs';
import {verifyProtectedRecoveryCandidate} from './recovery-site-review.mjs';
import {windowsRecoverySource,windowsRetirementFormat,windowsRetirementReader} from './windows-recovery-retirement.mjs';
import {inspectWindowsRecoveryStorage,readWindowsRecoveryMarker,readWindowsRuntimeRetirement,writeWindowsRecoveryMarker} from './windows-recovery-storage.mjs';

const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const same=(left,right)=>canonical(left)===canonical(right);
const identity=stat=>`${stat.dev}:${stat.ino}`;
const sha=/^sha256:[a-f0-9]{64}(?![\s\S])/;

export function openWindowsNativeHost({installationDirectory}={}){
  need(process.platform==='win32','windows_native_host');
  const installation=openInstallationStore(installationDirectory),content=path.join(installationDirectory,'content');
  let busy=false,runtime=null,closing=null;
  function recoveryContext({plan,configuration,selectionDigest}){
    const selected=installation.currentRecoverySelection();
    need(selected?.phase==='activated_protected'&&selected.selection_digest===selectionDigest,'windows_recovery_selection');
    const {deployment,activation,installation:scope}=selected;
    const recovery=installation.backupMaintenance().getRecoveryPlan(activation.plan_ref.restore_id);
    need(recovery?.phase==='activated_protected'&&same(recovery.activation,selected)&&
      recovery.retirement.evidence.format===windowsRetirementFormat,'windows_recovery_selection');
    const [service]=deployment.services,[member]=recovery.preparation.services;
    const approvedPlan=structuredClone(plan),core=structuredClone(configuration);
    need(deployment.services.length===1&&service.scope.authority==='controller'&&
      fields(approvedPlan,'configuration_ref,deployment_plan_ref,format,generation_id,release_manifest_digest')&&
      approvedPlan.format==='leafseamer.windows-native-recovery/1'&&digest(approvedPlan)===deployment.deployment_plan_digest&&
      approvedPlan.configuration_ref===service.configuration_ref&&approvedPlan.deployment_plan_ref===deployment.deployment_plan_ref&&
      approvedPlan.generation_id===deployment.generation_id&&approvedPlan.release_manifest_digest===deployment.release_manifest_digest,
      'windows_recovery_plan');
    need(fields(core,'bootstrap,distribution,format,host_installation_id,port')&&core.format==='leafseamer.windows-native-core/1'&&
      core.host_installation_id===scope.installation_id&&Number.isInteger(core.port)&&core.port>0&&core.port<=65535&&
      digest(core)===service.configuration_digest&&core.bootstrap?.service_id===service.scope.service_id&&
      core.bootstrap.database_instance_id===service.scope.database_instance_id&&fields(core.distribution,'directory,manifest_sha256')&&
      typeof core.distribution.directory==='string'&&/^[A-Za-z]:\\/.test(core.distribution.directory)&&
      path.resolve(core.distribution.directory)===core.distribution.directory&&sha.test(core.distribution.manifest_sha256)&&
      digest({controller:core.distribution})===recovery.preparation_intent.distributions_digest,'windows_recovery_configuration');
    need(same(service.scope,member.next_scope)&&same(service.data_ref,{attempt_id:recovery.preparation.attempt_id,
      directory_name:member.directory_name,bytes:member.bytes,sha256:member.sha256}),'windows_recovery_data');
    const destination=path.join(content,deployment.generation_id),directory=path.join(destination,member.directory_name);
    return {selected,deployment,activation,recovery,service,member,core,destination,directory};
  }
  const loadSupervisor=core=>loadVerifiedDistributionModule(core.distribution,'controller','process-host.mjs','windows_recovery_distribution');
  function reopen(native,deployment,marker){
    return marker?native.reopenPreparedRoot(content,deployment.generation_id,[],marker.root_identity):
      native.observePreparedRoot(content,deployment.generation_id);
  }

  return Object.freeze({
    async readRecoveryRetirement({plan,configuration,selectionDigest}={}){
      need(!busy&&!closing,'windows_recovery_busy');busy=true;
      let native,pin;
      try{
        const {deployment,service,member,core,destination,directory}=recoveryContext({plan,configuration,selectionDigest});
        const marker=await readWindowsRecoveryMarker(destination);
        native=installationContentPlatform();
        pin=reopen(native,deployment,marker);
        native.protectObject(pin,member.directory_name,true,false);
        const retirement=await readWindowsRuntimeRetirement(await loadSupervisor(core),directory,service.scope);
        await inspectWindowsRecoveryStorage({native,pin,directory,member,selectionDigest,marker,existing:true});
        return {selection_digest:selectionDigest,previous_retirement_digest:digest(retirement),retirement};
      }finally{
        try{if(pin)native.preparedClose(pin);}finally{busy=false;}
      }
    },
    async startRecovery({plan,configuration,selectionDigest,authorize,previousRetirementDigest=null}={}){
      need(!busy&&!runtime&&!closing,'windows_recovery_busy');busy=true;
      let pin,native;
      try{
        const existing=previousRetirementDigest!==null;
        need(typeof authorize==='function'&&(!existing||typeof previousRetirementDigest==='string'&&sha.test(previousRetirementDigest)),
          'windows_recovery_authority');
        const {selected,deployment,activation,recovery,service,member,core,destination,directory}=
          recoveryContext({plan,configuration,selectionDigest});
        native=installationContentPlatform();
        const retirement=recovery.retirement,retirement_digest=digest(retirement);
        const binding={plan_digest:activation.plan_ref.digest,retirement_id:retirement.retirement_id};
        const secret_binding_digest=service.secret_binding_digest;
        function assertCurrent(legacy_storage=false){
          need(installation.currentRecoverySelection()?.selection_digest===selectionDigest,'windows_recovery_selection');
          const decision=authorize(structuredClone({selection:selected,retirement_digest,secret_binding_digest,
            ...(existing&&{previous_retirement_digest:previousRetirementDigest,legacy_storage})}));
          need(decision?.allowed===true&&decision.selection_digest===selectionDigest&&decision.retirement_digest===retirement_digest&&
            decision.secret_binding_digest===secret_binding_digest&&decision.release_manifest_digest===deployment.release_manifest_digest&&
            (!existing||decision.previous_retirement_digest===previousRetirementDigest)&&(!legacy_storage||decision.legacy_storage_verified===true),
            'windows_recovery_authority');
          const source=windowsRecoverySource(decision,recovery.plan);
          need(digest(source)===retirement.evidence.source_digest,'windows_recovery_retirement');
          return source;
        }
        const old=await windowsRetirementReader(assertCurrent());
        need(same(await old.confirm(binding),retirement.evidence),'windows_recovery_retirement');
        const supervisor=await loadSupervisor(core);
        need(supervisor.installedCoreDigest()===core.bootstrap.artifact_manifest_ref?.digest,'windows_recovery_distribution');
        let marker;
        if(existing){
          marker=await readWindowsRecoveryMarker(destination);
          pin=reopen(native,deployment,marker);
        }else{
          const present=await fs.lstat(destination).catch(error=>{if(error.code!=='ENOENT')throw error;});
          need(!present,'windows_recovery_start_indeterminate');
          const deadline=performance.now()+1800000;
          await verifyProtectedRecoveryCandidate(content,recovery.preparation,deadline);
          assertCurrent();
          pin=native.prepareRoot(content,deployment.generation_id,[]);
          const relative=member.directory_name+'/controller.sqlite',file=path.join(directory,'controller.sqlite');
          await fs.mkdir(directory);
          native.protectObject(pin,member.directory_name,true,true);
          await fs.copyFile(path.join(content,service.data_ref.attempt_id,relative),file,constants.COPYFILE_EXCL);
          native.protectObject(pin,relative,false,true);
          await verifyProtectedRecoveryFiles(destination,{root_identity:identity(await fs.lstat(destination,{bigint:true})),
            services:[{...member,directory_identity:identity(await fs.lstat(directory,{bigint:true}))}]},deadline);
          native.flushPreparedObject(pin,relative,false);
          native.flushPreparedObject(pin,member.directory_name,true);
          native.flushPreparedObject(pin,'.',true);
          native.flushPreparedParent(pin);
          const pinned=await fs.lstat(file,{bigint:true});
          await supervisor.initializeProcessHost(directory);
          const current=await fs.lstat(file,{bigint:true});
          need(['dev','ino','size','mtimeNs','ctimeNs'].every(key=>current[key]===pinned[key]),'windows_recovery_data');
        }
        const inspect=()=>inspectWindowsRecoveryStorage({native,pin,directory,member,selectionDigest,marker,existing});
        if(existing){
          native.protectObject(pin,member.directory_name,true,false);
          need(digest(await readWindowsRuntimeRetirement(supervisor,directory,service.scope))===previousRetirementDigest,
            'windows_recovery_runtime_changed');
        }
        const storage=await inspect();
        if(!marker){
          assertCurrent(existing);
          await writeWindowsRecoveryMarker(native,pin,destination,storage.layout);
          marker=storage.layout;
        }
        need(same(await old.confirm(binding),retirement.evidence),'windows_recovery_retirement');
        await loadSupervisor(core);
        assertCurrent();
        if(existing)need(digest(await readWindowsRuntimeRetirement(supervisor,directory,service.scope))===previousRetirementDigest,
          'windows_recovery_runtime_changed');
        need(same(await inspect(),storage),'windows_recovery_data');
        runtime=await supervisor.startProcessHost({dataDir:directory,port:core.port,bootstrapPolicy:core.bootstrap});
        return Object.freeze({selection_digest:selectionDigest,containment:runtime.containment,exited:runtime.exited,close:runtime.close});
      }finally{
        try{if(pin)native.preparedClose(pin);}finally{busy=false;}
      }
    },
    close(){
      need(!busy,'windows_recovery_busy');
      return closing??=(async()=>{
        try{if(runtime)await runtime.close();}finally{installation.close();}
      })();
    }
  });
}
