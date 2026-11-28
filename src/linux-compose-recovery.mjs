import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {readDeploymentFile} from './linux-ingress.mjs';
import {publishLinuxRecoveryStorage,inspectLinuxRecoveryStorage} from './linux-recovery-storage.mjs';
import {verifyProtectedRecoveryCandidate} from './recovery-site-review.mjs';

const same=(left,right)=>canonical(left)===canonical(right);
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const identity=stat=>({device:String(stat.dev),inode:String(stat.ino)});

export async function prepareLinuxComposeRecovery({installation,installationDirectory,planFile,recoveryPlan,selectionDigest,authorize,pinRuntimeRoot}){
  const selection=installation.currentRecoverySelection();
  need(selection?.phase==='activated_protected'&&selection.selection_digest===selectionDigest&&
    typeof authorize==='function'&&process.geteuid()===0,'compose_recovery_selection');
  const {deployment,activation}=selection,record=installation.backupMaintenance().getRecoveryPlan(activation.plan_ref.restore_id);
  need(record?.phase==='activated_protected'&&same(record.activation,selection)&&
    record.retirement.evidence.format==='leafseamer-linux-deployment-retirement/1','compose_recovery_platform');
  const approval=structuredClone(recoveryPlan);
  need(fields(approval,'configuration_refs,deployment_plan_ref,format,generation_id,release_manifest_digest,runtime_root')&&
    approval.format==='leafseamer.linux-compose-recovery/1'&&digest(approval)===deployment.deployment_plan_digest&&
    approval.deployment_plan_ref===deployment.deployment_plan_ref&&approval.generation_id===deployment.generation_id&&
    approval.release_manifest_digest===deployment.release_manifest_digest&&fields(approval.configuration_refs,'controller,seamer')&&
    deployment.services.length===2,'compose_recovery_plan');
  const {runtime_root}=approval,root=pinRuntimeRoot(runtime_root),destination=path.join(runtime_root,deployment.generation_id);
  const bytes=readDeploymentFile(planFile,65536),plan=JSON.parse(bytes),configuration_digest='sha256:'+createHash('sha256').update(bytes).digest('hex');
  need(fields(plan.bootstrap,'controller,seamer')&&plan.cgroup?.namespace==='private'&&
    plan.cgroup.generation_id===deployment.generation_id&&!plan.worker_control&&!plan.worker_runtime,'compose_recovery_plan');
  const members=deployment.services.map((service,index)=>{
    const {authority}=service.scope,configuration=plan[authority],member=record.preparation.services[index];
    need(service.configuration_ref===approval.configuration_refs[authority]&&configuration_digest===service.configuration_digest&&
      same(service.scope,member.next_scope)&&service.data_ref.attempt_id===record.preparation.attempt_id&&
      service.data_ref.directory_name===member.directory_name&&service.data_ref.bytes===member.bytes&&service.data_ref.sha256===member.sha256&&
      configuration?.data_dir===path.join(destination,member.directory_name)&&configuration.service_id===service.scope.service_id&&
      configuration.database_instance_id===service.scope.database_instance_id&&
      [configuration.uid,configuration.gid].every(id=>Number.isInteger(id)&&id>0&&id<4294967295),'compose_recovery_plan');
    return {member,spec:{role:authority,uid:configuration.uid,gid:configuration.gid,launch_id:service.scope.database_instance_id}};
  });
  need(members[0].spec.role!==members[1].spec.role&&members[0].spec.uid!==members[1].spec.uid,'compose_recovery_plan');
  const secret_bindings_digest=digest(deployment.services.map(({scope,secret_binding_ref,secret_binding_digest,secret_policy_ref})=>
    ({scope,secret_binding_ref,secret_binding_digest,secret_policy_ref})));
  const preparation_distributions_digest=record.preparation_intent.distributions_digest;
  function assertCurrent(){
    need(installation.currentRecoverySelection()?.selection_digest===selectionDigest&&
      same(root,pinRuntimeRoot(runtime_root))&&bytes.equals(readDeploymentFile(planFile,65536)),'compose_recovery_selection');
    const decision=authorize(structuredClone({selection,configuration_digest,preparation_distributions_digest,secret_bindings_digest}));
    need(decision?.allowed===true&&decision.selection_digest===selectionDigest&&decision.configuration_digest===configuration_digest&&
      decision.release_manifest_digest===deployment.release_manifest_digest&&decision.secret_bindings_digest===secret_bindings_digest&&
      decision.preparation_distributions_digest===preparation_distributions_digest,'compose_recovery_authority');
  }
  function verifyRetirement(journal){
    const evidence=journal.recoveryRetirement(record.retirement.evidence.generation_id,deployment.generation_id);
    need(same(evidence,record.retirement.evidence),'compose_recovery_retirement');
  }
  assertCurrent();
  const journal=installation.openLinuxDeploymentJournal(null);
  try{verifyRetirement(journal);}finally{journal.close();}
  const content=path.join(installationDirectory,'content'),preparation=record.preparation;
  await verifyProtectedRecoveryCandidate(content,preparation,performance.now()+1800000);
  const storage=await publishLinuxRecoveryStorage({destination,source:path.join(content,preparation.attempt_id),members,
    selectionDigest,assertCurrent});

  return {plan,assertCurrent,verifyRetirement,assertSeed(){
    need(same(identity(fs.lstatSync(destination,{bigint:true})),storage.layout.root),'compose_recovery_data');
    for(const entry of members){
      const {binding,stat}=inspectLinuxRecoveryStorage(destination,entry),{role,launch_id}=entry.spec;
      const expected=storage.layout.services.find(service=>service.role===role),pin=storage.pins.get(launch_id);
      need(same({role,...binding},expected)&&['size','mtimeNs','ctimeNs'].every(key=>stat[key]===pin[key]),'compose_recovery_data');
    }
  },assertMount(role,pid){
    const expected=storage.layout.services.find(service=>service.role===role);
    const mounted=fs.statSync('/proc/'+pid+'/root/var/lib/leafseamer',{bigint:true});
    need(mounted.isDirectory()&&same(identity(mounted),expected.directory),'compose_recovery_mount');
  }};
}
