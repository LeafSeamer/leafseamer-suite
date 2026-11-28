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

const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const same=(left,right)=>canonical(left)===canonical(right);
const identity=stat=>`${stat.dev}:${stat.ino}`;
const sha=/^sha256:[a-f0-9]{64}(?![\s\S])/;

export function openWindowsNativeHost({installationDirectory}={}){
  need(process.platform==='win32','windows_native_host');
  const installation=openInstallationStore(installationDirectory),content=path.join(installationDirectory,'content');
  let busy=false,runtime=null,closing=null;
  return Object.freeze({
    async startRecovery({plan,configuration,selectionDigest,authorize}={}){
      need(!busy&&!runtime&&!closing,'windows_recovery_busy');busy=true;
      let pin,native;
      try{
        native=installationContentPlatform();
        const selected=installation.currentRecoverySelection();
        need(selected?.phase==='activated_protected'&&selected.selection_digest===selectionDigest&&typeof authorize==='function',
          'windows_recovery_selection');
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
        const retirement=recovery.retirement,retirement_digest=digest(retirement);
        const binding={plan_digest:activation.plan_ref.digest,retirement_id:retirement.retirement_id};
        const secret_binding_digest=service.secret_binding_digest;
        function assertCurrent(){
          need(installation.currentRecoverySelection()?.selection_digest===selectionDigest,'windows_recovery_selection');
          const decision=authorize(structuredClone({selection:selected,retirement_digest,secret_binding_digest}));
          need(decision?.allowed===true&&decision.selection_digest===selectionDigest&&decision.retirement_digest===retirement_digest&&
            decision.secret_binding_digest===secret_binding_digest&&decision.release_manifest_digest===deployment.release_manifest_digest,
            'windows_recovery_authority');
          const source=windowsRecoverySource(decision,recovery.plan);
          need(digest(source)===retirement.evidence.source_digest,'windows_recovery_retirement');
          return source;
        }
        const old=await windowsRetirementReader(assertCurrent());
        need(same(await old.confirm(binding),retirement.evidence),'windows_recovery_retirement');
        const supervisor=await loadVerifiedDistributionModule(core.distribution,'controller','process-host.mjs','windows_recovery_distribution');
        need(supervisor.installedCoreDigest()===core.bootstrap.artifact_manifest_ref?.digest,'windows_recovery_distribution');
        const destination=path.join(content,deployment.generation_id);
        const existing=await fs.lstat(destination).catch(error=>{if(error.code!=='ENOENT')throw error;});
        need(!existing,'windows_recovery_start_indeterminate');
        const deadline=performance.now()+1800000;
        await verifyProtectedRecoveryCandidate(content,recovery.preparation,deadline);
        assertCurrent();
        pin=native.prepareRoot(content,deployment.generation_id,[]);
        const directory=path.join(destination,member.directory_name),relative=member.directory_name+'/controller.sqlite';
        const file=path.join(directory,'controller.sqlite');
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
        need(same(await old.confirm(binding),retirement.evidence),'windows_recovery_retirement');
        await loadVerifiedDistributionModule(core.distribution,'controller','process-host.mjs','windows_recovery_distribution');
        native.protectObject(pin,relative,false,false);
        const current=await fs.lstat(file,{bigint:true});
        const entries=await fs.readdir(directory);
        need(current.isFile()&&current.nlink===1n&&['dev','ino','size','mtimeNs','ctimeNs'].every(key=>current[key]===pinned[key])&&
          ['-wal','-shm','-journal'].every(suffix=>!entries.includes('controller.sqlite'+suffix)),'windows_recovery_data');
        assertCurrent();
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
