import path from 'node:path';
import {digest,InstallationError,requireValue as need} from './import-input.mjs';
import {loadDistributionExport} from './backup-domain-verification.mjs';

export const windowsRetirementFormat='leafseamer-windows-deployment-retirement/1';
const unproven='recovery_windows_retirement_unproven';
const generation=/^[0-9a-f]{32}(?![\s\S])/;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}(?![\s\S])/;
const hash=/^sha256:[a-f0-9]{64}(?![\s\S])/;
const matches=(pattern,value)=>typeof value==='string'&&pattern.test(value);
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const localDirectory=value=>typeof value==='string'&&/^[A-Za-z]:\\/.test(value)&&path.resolve(value)===value;

export function windowsRecoverySource(decision,plan){
  const {runtime_generation_id:id,windows_runtime:runtime}=decision;
  need(matches(uuid,id)&&id!==plan.target.generation_id&&fields(runtime,'supervisor,writers,writers_fenced')&&
    runtime.writers_fenced===true&&fields(runtime.supervisor,'directory,manifest_sha256')&&localDirectory(runtime.supervisor.directory)&&
    matches(hash,runtime.supervisor.manifest_sha256)&&Array.isArray(runtime.writers)&&runtime.writers.length>0&&runtime.writers.length<=256,
  'recovery_windows_runtime');
  const scopes=new Map(),directories=new Set(),generations=new Set();
  for(const writer of runtime.writers){
    need(fields(writer,'authority,data_directory,database_instance_id,runtime_generation,service_id')&&
      ['controller','seamer'].includes(writer.authority)&&matches(uuid,writer.service_id)&&matches(uuid,writer.database_instance_id)&&
      matches(generation,writer.runtime_generation)&&localDirectory(writer.data_directory),'recovery_windows_runtime');
    const {database_instance_id,runtime_generation,data_directory}=writer,location=data_directory.toLowerCase();
    need(!scopes.has(database_instance_id)&&!directories.has(location)&&!generations.has(runtime_generation),'recovery_windows_runtime');
    scopes.set(database_instance_id,writer);directories.add(location);generations.add(runtime_generation);
  }
  need(plan.services.every(({source_scope:scope})=>{
    const writer=scopes.get(scope.database_instance_id);
    return writer?.authority===scope.authority&&writer.service_id===scope.service_id;
  }),'recovery_retirement_target_mismatch');
  const writers=[...scopes.keys()].sort().map(key=>scopes.get(key));
  return structuredClone({generation_id:id,supervisor:runtime.supervisor,writers});
}

export async function readWindowsRetirement(source){
  try{
    const read=await loadDistributionExport(source.supervisor,'controller','process-host.mjs','readProcessRecoveryRetirement',unproven);
    const members=[];
    for(const {authority,data_directory,runtime_generation,service_id,database_instance_id} of source.writers){
      const proof=await read({dataDir:data_directory,runtimeGeneration:runtime_generation,serviceId:service_id,databaseInstanceId:database_instance_id});
      need(proof?.format==='leafseamer-windows-process-retirement/1'&&proof.runtime_generation===runtime_generation&&
        proof.service_id===service_id&&proof.database_instance_id===database_instance_id&&proof.active_processes===0&&
        matches(hash,proof.retirement_digest)&&members.every(member=>member.directory_id!==proof.directory_id&&
          member.journal_incarnation!==proof.journal_incarnation),unproven);
      members.push({...proof,authority});
    }
    return {format:windowsRetirementFormat,generation_id:source.generation_id,source_digest:digest(source),members};
  }catch(error){
    if(error instanceof InstallationError)throw error;
    throw new InstallationError(unproven);
  }
}
