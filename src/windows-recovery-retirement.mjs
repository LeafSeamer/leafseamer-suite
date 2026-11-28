import path from 'node:path';
import {canonical,digest,InstallationError,requireValue as need} from './import-input.mjs';
import {loadVerifiedDistributionModule} from './backup-domain-verification.mjs';

export const historicalWindowsRetirementFormat='leafseamer-windows-deployment-retirement/1';
export const windowsRetirementFormat='leafseamer-windows-deployment-retirement/2';
const unproven='recovery_windows_retirement_unproven';
const generation=/^[0-9a-f]{32}(?![\s\S])/;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}(?![\s\S])/;
const hash=/^sha256:[a-f0-9]{64}(?![\s\S])/;
const matches=(pattern,value)=>typeof value==='string'&&pattern.test(value);
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const localDirectory=value=>typeof value==='string'&&/^[A-Za-z]:\\/.test(value)&&path.resolve(value)===value;
const same=(left,right)=>canonical(left)===canonical(right);

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

export function windowsRetirementFacts({generation_id,members}){
  return {generation_id,members:members.map(({startup_fence,...member})=>member)};
}

export function withWindowsStartupFences(preflight,binding){
  return {...preflight,format:windowsRetirementFormat,members:preflight.members.map(member=>({...member,startup_fence:binding}))};
}

async function nativeCall(fn){
  try{
    return await fn();
  }catch(error){
    if(error instanceof InstallationError)throw error;
    throw new InstallationError(error?.code==='process_recovery_fence_conflict'?'recovery_windows_fence_conflict':unproven);
  }
}

export async function windowsRetirementReader(source){
  const {readProcessRecoveryRetirement:read,fenceProcessRecoveryStartup:fence}=await nativeCall(()=>
    loadVerifiedDistributionModule(source.supervisor,'controller','process-host.mjs',unproven));
  need(typeof read==='function'&&typeof fence==='function','recovery_windows_supervisor_fencing_required');

  function options({data_directory,runtime_generation,service_id,database_instance_id}){
    return {dataDir:data_directory,runtimeGeneration:runtime_generation,serviceId:service_id,databaseInstanceId:database_instance_id};
  }

  async function observe(binding,requireFence){
    const members=[];
    for(const writer of source.writers){
      const proof=await nativeCall(()=>read(options(writer)));
      need(proof?.format==='leafseamer-windows-process-retirement/1'&&proof.runtime_generation===writer.runtime_generation&&
        proof.service_id===writer.service_id&&proof.database_instance_id===writer.database_instance_id&&proof.active_processes===0&&
        matches(hash,proof.retirement_digest)&&members.every(member=>member.directory_id!==proof.directory_id&&
          member.journal_incarnation!==proof.journal_incarnation),unproven);
      if(requireFence||proof.startup_fence)
        need(proof.startup_fence&&same(proof.startup_fence,binding),'recovery_windows_fence_conflict');
      members.push({...proof,authority:writer.authority});
    }
    const facts={generation_id:source.generation_id,members};
    return {format:requireFence?windowsRetirementFormat:historicalWindowsRetirementFormat,
      source_digest:digest(source),...(requireFence?facts:windowsRetirementFacts(facts))};
  }

  return {
    preflight:binding=>observe(binding,false),
    confirm:binding=>observe(binding,true),
    async seal(binding,expected,assertCurrent){
      for(const [index,writer] of source.writers.entries()){
        assertCurrent(writer);
        const proof=await nativeCall(()=>fence({...options(writer),planDigest:binding.plan_digest,retirementId:binding.retirement_id}));
        need(same({...proof,authority:writer.authority},expected.members[index]),'recovery_runtime_generation_changed');
      }
      const confirmed=await observe(binding,true);
      need(same(confirmed,expected),'recovery_runtime_generation_changed');
      return confirmed;
    }
  };
}
