import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {canonical,digest,InstallationError,requireValue as need} from './import-input.mjs';
import {readExpandedManifest,verifyExpandedArchive} from './maintenance-backup-archive.mjs';

const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}(?![\s\S])/;
const reference=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/;
const hash=/^sha256:[a-f0-9]{64}(?![\s\S])/;
const schema=/^[1-9][0-9]{0,9}(?![\s\S])/;
const osSubject=/^(?:uid:(?:0|[1-9][0-9]{0,9})|S-1-[0-9]+(?:-[0-9]+){1,15})(?![\s\S])/;
const matches=(pattern,value)=>typeof value==='string'&&pattern.test(value);
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const same=(left,right)=>canonical(left)===canonical(right);
const encode=value=>Buffer.from(canonical(value));

function targetPlan(value,receipts){
  need(fields(value,'deployment_plan_digest,deployment_plan_ref,generation_id,release_manifest_digest,services')&&
    matches(reference,value.deployment_plan_ref)&&matches(hash,value.deployment_plan_digest)&&matches(hash,value.release_manifest_digest)&&
    matches(uuid,value.generation_id)&&Array.isArray(value.services)&&value.services.length===receipts.length,
  'recovery_target_plan');
  const targets=new Map(),generations=new Set();
  for(const service of value.services){
    need(fields(service,'configuration_ref,data_generation_id,schema_revision,secret_policy_ref,source_database_instance_id')&&
      matches(uuid,service.source_database_instance_id)&&matches(uuid,service.data_generation_id)&&
      matches(reference,service.configuration_ref)&&matches(reference,service.secret_policy_ref)&&
      matches(schema,service.schema_revision)&&Number(service.schema_revision)<=2147483647&&
      !targets.has(service.source_database_instance_id)&&!generations.has(service.data_generation_id),'recovery_target_plan');
    targets.set(service.source_database_instance_id,service);
    generations.add(service.data_generation_id);
  }
  const services=receipts.map(({scope})=>{
    const target=targets.get(scope.database_instance_id);
    need(target&&Number(target.schema_revision)>=Number(scope.schema_revision),'recovery_target_plan');
    return target;
  });
  return structuredClone({...value,services});
}

export function recoveryPlanStore({db,transact,rows,decode,identity,staging,published,original,claimHelper,requireFreeHelper,
  readLinuxRetirement,retirementEnabled}){
  const installation={installation_id:identity.host_installation_id,installation_epoch:identity.installation_epoch};
  const candidateDirectory=id=>path.join(staging,'restore-'+id,'restored.partial');
  const planReference=(id,planId,hashValue)=>({...installation,restore_id:id,plan_id:planId,revision:'1',digest:hashValue});

  function isolation(id){
    const row=original(id);
    need(row?.state==='isolated_validated','recovery_plan_not_isolated');
    const value=decode(row.body,row.digest),source=published(row.archive_id);
    need(value.source_digest===source.sourceDigest&&row.source_digest===source.sourceDigest&&
      value.manifest_sha256===source.proof.manifest_sha256&&value.verification_ref===source.proof.verification_ref&&
      value.snapshot_count===source.receipts.length&&matches(hash,value.command_review?.review_digest),'recovery_isolation_evidence');
    return {row,value,source};
  }

  function current(id){
    const [row]=rows(db,`SELECT p.*,a.body AS approval_body,a.digest AS approval_digest,a.approval_id
      FROM maintenance_recovery_plan p LEFT JOIN maintenance_recovery_approval a USING(restore_id) WHERE restore_id=?`,id);
    if(!row)return null;
    const plan=decode(row.body,row.digest),plan_ref=planReference(id,row.plan_id,row.digest);
    need(plan.restore_id===id&&plan.isolation_digest===row.isolation_digest,'recovery_plan_integrity');
    const approval=row.approval_id===null?null:decode(row.approval_body,row.approval_digest);
    if(approval)need(approval.approval_id===row.approval_id&&same(approval.plan_ref,plan_ref),'recovery_plan_integrity');
    const value={phase:approval?'plan_reviewed':'awaiting_local_approval',plan_ref,plan,approval};
    if(!retirementEnabled)return value;
    const [proof]=rows(db,'SELECT * FROM maintenance_recovery_retirement WHERE restore_id=?',id);
    if(!proof)return value;
    const retirement=decode(proof.body,proof.digest);
    need(approval&&proof.approval_id===approval.approval_id&&proof.plan_digest===plan_ref.digest&&
      retirement.retirement_id===proof.retirement_id&&retirement.approval_id===approval.approval_id&&
      same(retirement.plan_ref,plan_ref),'recovery_plan_integrity');
    return {...value,phase:'old_writers_retired',retirement};
  }

  function authorized(authority,action,expected,context){
    need(typeof authority==='function','restore_authority');
    const decision=authority(structuredClone({action,expected_generation:expected,...context}));
    need(decision?.allowed===true,'restore_not_authorized');
    need(decision.generation===expected,'restore_generation_conflict');
    return decision;
  }

  async function prepare(id,input,authority){
    need(matches(uuid,id),'restore_request');
    const unlock=claimHelper();
    try{
      const selection=transact(()=>{
        const {row,value,source}=isolation(id),target=targetPlan(input,source.receipts);
        authorized(authority,'prepare_recovery_plan',row.expected_generation,{archive:source.archive,restore_id:id,target});
        const prior=current(id);
        if(prior)need(same(prior.plan.target,target),'recovery_plan_conflict');
        return {row,value,source,target,prior};
      });
      if(selection.prior)return selection.prior;
      const {row,value,source,target}=selection;
      const manifest=await readExpandedManifest(candidateDirectory(id),value.manifest_sha256);
      const repairs=manifest.coverage.filter(item=>item.state!=='included').map(({kind,reference,state})=>({kind,reference,state}));
      const plan={format:'leafseamer-recovery-plan/1',...installation,restore_id:id,archive_id:row.archive_id,
        isolation_digest:row.digest,expected_generation:row.expected_generation,manifest_sha256:value.manifest_sha256,
        verification_ref:value.verification_ref,command_review:value.command_review,coverage_digest:digest(manifest.coverage),
        uncovered_count:repairs.length,unresolved_digest:digest(manifest.unresolved),unresolved_count:manifest.unresolved.length,
        has_review_items:value.command_review.state==='requires_review'||manifest.unresolved.length>0||repairs.length>0,
        requires_site_review:true,
        target,services:source.receipts.map(({scope,sha256,backup_operation_id},index)=>({
          source_scope:scope,snapshot_sha256:sha256,snapshot_receipt_id:backup_operation_id,
          next_scope:{...scope,database_instance_id:randomUUID(),request_epoch:randomUUID(),
            control_epoch:scope.authority==='controller'?randomUUID():null,schema_revision:target.services[index].schema_revision}
        })),requires_protected_start:true};
      const body=encode(plan);
      need(body.length<=524288,'recovery_plan_capacity');
      return transact(()=>{
        need(isolation(id).row.digest===row.digest,'recovery_isolation_evidence');
        authorized(authority,'adopt_recovery_plan',row.expected_generation,{archive:source.archive,plan});
        db.prepare('INSERT INTO maintenance_recovery_plan VALUES (?,?,?,?,?)')
          .run(id,randomUUID(),row.digest,body,digest(plan));
        return current(id);
      });
    }finally{unlock();}
  }

  async function approve(input,authority){
    need(fields(input,'approval_id,command_review_digest,coverage_digest,plan_ref,unresolved_digest')&&
      matches(uuid,input.approval_id)&&matches(uuid,input.plan_ref?.restore_id),'recovery_approval_invalid');
    const confirmation=structuredClone(input),id=confirmation.plan_ref.restore_id;
    const deadline=performance.now()+1800000;
    const unlock=claimHelper();
    try{
      const selection=transact(()=>{
        const {source,row}=isolation(id),candidate=current(id);
        need(candidate&&same(confirmation.plan_ref,candidate.plan_ref),'recovery_plan_ref');
        const {plan}=candidate;
        need(plan.isolation_digest===row.digest&&plan.command_review.review_digest===confirmation.command_review_digest&&
          plan.coverage_digest===confirmation.coverage_digest&&plan.unresolved_digest===confirmation.unresolved_digest,
        'recovery_approval_invalid');
        if(candidate.approval)need(candidate.approval.approval_id===confirmation.approval_id,'recovery_approval_conflict');
        else requireFreeHelper();
        const context={archive:source.archive,...candidate,confirmation};
        const decision=authorized(authority,'check_recovery_approval',plan.expected_generation,context);
        need(decision.origin==='local_os'&&matches(osSubject,decision.os_subject)&&decision.os_subject.length<=184,
          'recovery_local_admin_required');
        return {candidate,context,os_subject:decision.os_subject};
      });
      const {candidate,context,os_subject}=selection,{plan}=candidate;
      if(candidate.approval){
        need(candidate.approval.os_subject===os_subject,'recovery_approval_conflict');
        return candidate;
      }
      try{await verifyExpandedArchive(candidateDirectory(id),plan.manifest_sha256,deadline);}
      catch(error){
        if(error instanceof InstallationError&&error.code==='backup_archive_deadline')throw error;
        throw new InstallationError('restore_candidate_changed');
      }
      return transact(()=>{
        need(performance.now()<deadline,'backup_archive_deadline');
        const latest=current(id);
        need(latest&&!latest.approval&&same(latest.plan_ref,candidate.plan_ref)&&isolation(id).row.digest===plan.isolation_digest,
          'recovery_plan_conflict');
        requireFreeHelper();
        const decision=authorized(authority,'approve_recovery_plan',plan.expected_generation,context);
        need(decision.origin==='local_os'&&decision.os_subject===os_subject,'recovery_local_admin_required');
        need(!db.prepare('SELECT 1 FROM maintenance_recovery_approval WHERE approval_id=?').get(confirmation.approval_id),
          'recovery_approval_conflict');
        const approval={...confirmation,os_subject};
        db.prepare('INSERT INTO maintenance_recovery_approval VALUES (?,?,?,?,?)')
          .run(id,candidate.plan_ref.digest,confirmation.approval_id,encode(approval),digest(approval));
        return current(id);
      });
    }finally{unlock();}
  }

  function recordLinuxRetirement(input,authority){
    need(retirementEnabled,'recovery_retirement_migration_required');
    need(process.platform==='linux','recovery_retirement_platform');
    need(fields(input,'plan_ref,retirement_id')&&matches(uuid,input.plan_ref?.restore_id)&&
      matches(uuid,input.retirement_id),'recovery_retirement_request');
    const request=structuredClone(input),id=request.plan_ref.restore_id;
    const unlock=claimHelper();
    try{
      return transact(()=>{
        const {source,row}=isolation(id),candidate=current(id);
        need(candidate&&same(candidate.plan_ref,request.plan_ref),'recovery_plan_ref');
        const {plan,approval}=candidate;
        need(approval&&plan.isolation_digest===row.digest,'recovery_retirement_not_approved');
        const context={archive:source.archive,...candidate,retirement_request_id:request.retirement_id};
        const decision=authorized(authority,'read_recovery_retirement',plan.expected_generation,context);
        const generationId=decision.runtime_generation_id;
        if(candidate.retirement){
          need(candidate.retirement.retirement_id===request.retirement_id&&
            candidate.retirement.evidence.generation_id===generationId,'recovery_retirement_conflict');
          return candidate;
        }
        requireFreeHelper();
        const evidence=readLinuxRetirement(generationId,plan.target.generation_id);
        need(plan.services.every(({source_scope})=>evidence.members.some(member=>
          member.authority===source_scope.authority&&member.service_id===source_scope.service_id)),
        'recovery_retirement_target_mismatch');
        const checked=authorized(authority,'adopt_recovery_retirement',plan.expected_generation,{...context,evidence});
        need(checked.runtime_generation_id===generationId,'recovery_runtime_generation_changed');
        need(same(readLinuxRetirement(generationId,plan.target.generation_id),evidence),'recovery_runtime_generation_changed');
        need(!db.prepare('SELECT 1 FROM maintenance_recovery_retirement WHERE retirement_id=?').get(request.retirement_id),
          'recovery_retirement_conflict');
        const receipt={...request,approval_id:approval.approval_id,evidence};
        db.prepare('INSERT INTO maintenance_recovery_retirement VALUES (?,?,?,?,?,?)')
          .run(id,request.retirement_id,approval.approval_id,candidate.plan_ref.digest,encode(receipt),digest(receipt));
        return current(id);
      });
    }finally{unlock();}
  }

  return {prepare,approve,recordLinuxRetirement,get(id){need(matches(uuid,id),'restore_request');return transact(()=>current(id));}};
}
