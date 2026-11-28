import fs from 'node:fs/promises';
import path from 'node:path';
import {canonical,digest,requireValue as need} from './import-input.mjs';
import {installationContentPlatform} from './local-peer.mjs';
import {verifyProtectedRecoveryFiles} from './recovery-storage-preparation.mjs';

const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}(?![\s\S])/;
const hash=/^sha256:[a-f0-9]{64}(?![\s\S])/;
const reference=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/;
const osSubject=process.platform==='win32'?/^S-1-[0-9]+(?:-[0-9]+){1,15}(?![\s\S])/:/^uid:(?:0|[1-9][0-9]{0,9})(?![\s\S])/;
const matches=(pattern,value)=>typeof value==='string'&&pattern.test(value);
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const same=(left,right)=>canonical(left)===canonical(right);

function checkEvidence(evidence,plan){
  const {coverage_digest,unresolved_digest,command_review}=plan;
  need(fields(evidence,'command_review_digest,coverage_digest,services,site_observation_digest,site_observation_ref,unresolved_digest,unresolved_disposition')&&
    evidence.coverage_digest===coverage_digest&&evidence.unresolved_digest===unresolved_digest&&
    evidence.command_review_digest===command_review.review_digest&&evidence.unresolved_disposition==='hold_without_replay'&&
    matches(reference,evidence.site_observation_ref)&&matches(hash,evidence.site_observation_digest)&&
    Array.isArray(evidence.services)&&evidence.services.length===plan.services.length,'recovery_site_evidence');
  for(const [index,service] of evidence.services.entries()){
    const target=plan.target.services[index];
    need(fields(service,'configuration_digest,configuration_ref,data_generation_id,scope,secret_binding_digest,secret_binding_ref,secret_policy_ref,secret_state')&&
      same(service.scope,plan.services[index].next_scope)&&service.data_generation_id===target.data_generation_id&&
      service.configuration_ref===target.configuration_ref&&service.secret_policy_ref===target.secret_policy_ref&&
      matches(hash,service.configuration_digest)&&matches(reference,service.secret_binding_ref)&&matches(hash,service.secret_binding_digest)&&
      ['reconfigured','not_required'].includes(service.secret_state),'recovery_site_evidence');
  }
}

export async function verifyProtectedRecoveryCandidate(parent,preparation,deadline){
  const root=path.join(parent,preparation.attempt_id);
  if(process.platform==='win32'){
    const native=installationContentPlatform();
    const pin=native.reopenPreparedRoot(parent,preparation.attempt_id,[],preparation.platform_root_identity);
    try{
      await verifyProtectedRecoveryFiles(root,preparation,deadline);
      for(const {directory_name,next_scope} of preparation.services){
        native.protectObject(pin,directory_name,true,false);
        native.protectObject(pin,directory_name+'/'+next_scope.authority+'.sqlite',false,false);
      }
    }finally{native.preparedClose(pin);}
  }else{
    const uid=BigInt(process.geteuid());
    async function privateEntry(file,directory){
      const stat=await fs.lstat(file,{bigint:true});
      need((directory?stat.isDirectory():stat.isFile())&&stat.uid===uid&&(stat.mode&0o7777n)===(directory?0o700n:0o600n),
        'recovery_preparation_protection');
    }
    await verifyProtectedRecoveryFiles(root,preparation,deadline);
    await privateEntry(root,true);
    for(const {directory_name,next_scope} of preparation.services){
      const directory=path.join(root,directory_name);
      await privateEntry(directory,true);
      await privateEntry(path.join(directory,next_scope.authority+'.sqlite'),false);
    }
  }
}

export function recoverySiteReviewStore({db,transact,rows,decode,contentDirectory,claimHelper,requireFreeHelper,authorized,load}){
  function current(id,candidate){
    const row=rows(db,'SELECT * FROM maintenance_recovery_site_review WHERE restore_id=? ORDER BY revision DESC LIMIT 1',id)[0];
    if(!row)return candidate;
    const review=decode(row.body,row.digest);
    need(review.format==='leafseamer-recovery-site-review/1'&&review.review_id===row.review_id&&review.revision===row.revision&&
      review.previous_review_digest===row.previous_digest&&same(review.plan_ref,candidate.plan_ref)&&candidate.preparation&&
      review.preparation_digest===digest(candidate.preparation)&&review.evidence_digest===digest(review.evidence),'recovery_plan_integrity');
    return {...candidate,site_review:{...review,review_digest:row.digest}};
  }

  async function record(input,authority){
    need(['linux','win32'].includes(process.platform),'recovery_site_platform');
    need(fields(input,'evidence,plan_ref,preparation_digest,previous_review_digest,review_id')&&input.evidence&&typeof input.evidence==='object'&&
      matches(uuid,input.plan_ref?.restore_id)&&
      matches(uuid,input.review_id)&&matches(hash,input.preparation_digest)&&
      (input.previous_review_digest===null||matches(hash,input.previous_review_digest)),'recovery_site_request');
    const request=structuredClone(input),id=request.plan_ref.restore_id,deadline=performance.now()+1800000;
    const unlock=claimHelper();
    try{
      const evidence_digest=digest(request.evidence);
      function checkAuthority(action,context){
        const decision=authorized(authority,action,context.plan.expected_generation,{...context,confirmation:request,evidence_digest});
        need(decision.origin==='local_os'&&matches(osSubject,decision.os_subject)&&decision.os_subject.length<=184,'recovery_local_admin_required');
        need(decision.retirement_current===true&&decision.target_inactive===true&&decision.evidence_digest===evidence_digest&&
          decision.release_manifest_digest===context.plan.target.release_manifest_digest,'recovery_site_authority');
        return decision.os_subject;
      }
      const selected=transact(()=>{
        const context=load(id,request.plan_ref);
        need(['prepared_protected','activated_protected'].includes(context.phase)&&
          digest(context.preparation)===request.preparation_digest,'recovery_site_preparation');
        checkEvidence(request.evidence,context.plan);
        const os_subject=checkAuthority('check_recovery_site_review',context);
        const [prior]=rows(db,'SELECT restore_id,body,digest FROM maintenance_recovery_site_review WHERE review_id=?',request.review_id);
        if(prior){
          const review=decode(prior.body,prior.digest);
          need(prior.restore_id===id&&review.os_subject===os_subject&&Object.keys(request).every(key=>same(request[key],review[key])),
            'recovery_site_review_conflict');
          return {prior:{...review,review_digest:prior.digest}};
        }
        need(context.phase==='prepared_protected','recovery_site_preparation');
        need((context.site_review?.review_digest??null)===request.previous_review_digest,'recovery_site_review_conflict');
        requireFreeHelper();
        return {context,os_subject};
      });
      if(selected.prior)return selected.prior;
      const {context,os_subject}=selected;
      await verifyProtectedRecoveryCandidate(contentDirectory,context.preparation,deadline);
      return transact(()=>{
        need(performance.now()<deadline,'backup_archive_deadline');
        const latest=load(id,request.plan_ref);
        need(same(latest,context),'recovery_site_review_conflict');
        requireFreeHelper();
        need(checkAuthority('adopt_recovery_site_review',latest)===os_subject,'recovery_local_admin_required');
        const review={format:'leafseamer-recovery-site-review/1',...request,os_subject,evidence_digest,revision:(context.site_review?.revision??0)+1};
        const body=Buffer.from(canonical(review)),review_digest=digest(review);
        need(body.length<=524288,'recovery_site_capacity');
        db.prepare('INSERT INTO maintenance_recovery_site_review VALUES (?,?,?,?,?,?)')
          .run(request.review_id,id,review.revision,request.previous_review_digest,body,review_digest);
        return {...review,review_digest};
      });
    }finally{unlock();}
  }

  return {record,current};
}
