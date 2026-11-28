import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {canonical,digest,InstallationError,requireValue as need} from './import-input.mjs';
import {readExpandedManifest,verifyExpandedArchive} from './maintenance-backup-archive.mjs';
import {prepareRecoveryFiles,verifyProtectedRecoveryFiles} from './recovery-storage-preparation.mjs';
import {historicalWindowsRetirementFormat,windowsRecoverySource,windowsRetirementFacts,windowsRetirementFormat,
  windowsRetirementReader,withWindowsStartupFences} from './windows-recovery-retirement.mjs';

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

export function recoveryPlanStore({db,transact,rows,decode,identity,staging,contentDirectory,published,original,claimHelper,requireFreeHelper,
  readLinuxRetirement,retirementEnabled,windowsFenceEnabled,preparationEnabled}){
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

  function retirementView(id){
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
    if(proof){
      const retirement=decode(proof.body,proof.digest);
      need(approval&&proof.approval_id===approval.approval_id&&proof.plan_digest===plan_ref.digest&&
        retirement.retirement_id===proof.retirement_id&&retirement.approval_id===approval.approval_id&&
        same(retirement.plan_ref,plan_ref),'recovery_plan_integrity');
      if(retirement.evidence.format!==historicalWindowsRetirementFormat)return {...value,phase:'old_writers_retired',retirement};
      value.historical_retirement=retirement;
    }
    if(!windowsFenceEnabled)return value;
    const [intent]=rows(db,`SELECT i.*,r.body,r.digest FROM maintenance_recovery_windows_fence i
      LEFT JOIN maintenance_recovery_windows_fence_result r USING(restore_id) WHERE i.restore_id=?`,id);
    if(!intent)return value;
    const {retirement_id,approval_id,plan_digest,generation_id,source_digest,preflight_digest}=intent;
    need(approval&&approval_id===approval.approval_id&&plan_digest===plan_ref.digest&&matches(uuid,retirement_id)&&
      matches(uuid,generation_id)&&matches(hash,source_digest)&&matches(hash,preflight_digest),'recovery_plan_integrity');
    value.retirement_intent={retirement_id,approval_id,generation_id,source_digest,preflight_digest};
    if(intent.body===null)return value;
    const retirement=decode(intent.body,intent.digest),evidence=retirement.evidence;
    need(Array.isArray(evidence?.members)&&evidence.members.length>0,'recovery_plan_integrity');
    const facts=windowsRetirementFacts(evidence);
    need(retirement.retirement_id===retirement_id&&retirement.approval_id===approval_id&&same(retirement.plan_ref,plan_ref)&&
      evidence.format===windowsRetirementFormat&&evidence.generation_id===generation_id&&evidence.source_digest===source_digest&&
      digest({...facts,source_digest,format:historicalWindowsRetirementFormat})===preflight_digest&&
      evidence.members.every(member=>member.startup_fence&&same(member.startup_fence,{plan_digest,retirement_id})),
    'recovery_plan_integrity');
    return {...value,phase:'old_writers_retired',retirement};
  }

  function current(id){
    const value=retirementView(id);
    if(!preparationEnabled||!value)return value;
    const [row]=rows(db,`SELECT i.preparation_id,i.body AS intent,i.digest AS intent_digest,r.attempt_id,r.body,r.digest
      FROM maintenance_recovery_preparation i LEFT JOIN maintenance_recovery_preparation_result r USING(restore_id) WHERE i.restore_id=?`,id);
    if(!row)return value;
    const preparation_intent=decode(row.intent,row.intent_digest);
    need(value.phase==='old_writers_retired'&&preparation_intent.preparation_id===row.preparation_id&&
      same(preparation_intent.plan_ref,value.plan_ref)&&preparation_intent.retirement_digest===digest(value.retirement),'recovery_plan_integrity');
    if(!row.attempt_id)return {...value,preparation_intent};
    const preparation=decode(row.body,row.digest);
    need(preparation.format==='leafseamer-protected-recovery-preparation/1'&&preparation.attempt_id===row.attempt_id&&matches(uuid,row.attempt_id)&&
      preparation.intent_digest===row.intent_digest&&Array.isArray(preparation.services)&&preparation.services.length===value.plan.services.length&&
      preparation.services.every((service,index)=>service.directory_name==='db-'+index&&same(service.next_scope,value.plan.services[index].next_scope)&&
        service.origin?.data_generation_id===value.plan.target.services[index].data_generation_id),'recovery_plan_integrity');
    return {...value,phase:'prepared_protected',preparation_intent,preparation};
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

  function retirementRequest(input,platform){
    need(retirementEnabled,'recovery_retirement_migration_required');
    need(process.platform===platform,'recovery_retirement_platform');
    need(fields(input,'plan_ref,retirement_id')&&matches(uuid,input.plan_ref?.restore_id)&&
      matches(uuid,input.retirement_id),'recovery_retirement_request');
    return structuredClone(input);
  }

  function retirementContext(request,runtime_profile){
    const id=request.plan_ref.restore_id,{source,row}=isolation(id),candidate=current(id);
    need(candidate&&same(candidate.plan_ref,request.plan_ref),'recovery_plan_ref');
    need(candidate.approval&&candidate.plan.isolation_digest===row.digest,'recovery_retirement_not_approved');
    return {archive:source.archive,...candidate,retirement_request_id:request.retirement_id,runtime_profile};
  }

  function persistRetirement(request,context,evidence){
    requireUnusedRetirementId(request);
    const id=request.plan_ref.restore_id,receipt={...request,approval_id:context.approval.approval_id,evidence};
    const body=encode(receipt);
    need(body.length<=8192,'recovery_retirement_capacity');
    db.prepare('INSERT INTO maintenance_recovery_retirement VALUES (?,?,?,?,?,?)')
      .run(id,request.retirement_id,receipt.approval_id,context.plan_ref.digest,body,digest(receipt));
    return current(id);
  }

  function requireUnusedRetirementId(request,allowHistorical=false){
    const prior=db.prepare('SELECT restore_id FROM maintenance_recovery_retirement WHERE retirement_id=?').pluck().get(request.retirement_id);
    need(!prior||(allowHistorical&&prior===request.plan_ref.restore_id),'recovery_retirement_conflict');
    if(windowsFenceEnabled)need(!db.prepare('SELECT 1 FROM maintenance_recovery_windows_fence WHERE retirement_id=?').get(request.retirement_id),
      'recovery_retirement_conflict');
  }

  function recordLinuxRetirement(input,authority,native){
    const request=retirementRequest(input,'linux');
    const evidenceFormat=native?'leafseamer-linux-native-retirement/1':'leafseamer-linux-deployment-retirement/1';
    const unlock=claimHelper();
    try{
      return transact(()=>{
        const context=retirementContext(request,native?'linux_native':'linux_compose');
        need(!context.historical_retirement&&!context.retirement_intent,'recovery_retirement_conflict');
        const {plan,retirement}=context;
        const decision=authorized(authority,'read_recovery_retirement',plan.expected_generation,context);
        const generationId=decision.runtime_generation_id;
        if(retirement){
          need(retirement.retirement_id===request.retirement_id&&
            retirement.evidence.generation_id===generationId&&retirement.evidence.format===evidenceFormat,
          'recovery_retirement_conflict');
          return current(request.plan_ref.restore_id);
        }
        requireFreeHelper();
        const evidence=readLinuxRetirement(generationId,plan.target.generation_id,native);
        need(evidence.format===evidenceFormat&&plan.services.every(({source_scope})=>evidence.members.some(member=>
          member.authority===source_scope.authority&&member.service_id===source_scope.service_id)),
        'recovery_retirement_target_mismatch');
        const checked=authorized(authority,'adopt_recovery_retirement',plan.expected_generation,{...context,evidence});
        need(checked.runtime_generation_id===generationId,'recovery_runtime_generation_changed');
        need(same(readLinuxRetirement(generationId,plan.target.generation_id,native),evidence),'recovery_runtime_generation_changed');
        return persistRetirement(request,context,evidence);
      });
    }finally{unlock();}
  }

  async function recordWindowsRetirement(input,authority){
    const request=retirementRequest(input,'win32'),id=request.plan_ref.restore_id;
    need(windowsFenceEnabled,'recovery_windows_fencing_migration_required');
    const unlock=claimHelper();
    try{
      const binding={plan_digest:request.plan_ref.digest,retirement_id:request.retirement_id};
      const checkAuthority=(action,context,extra)=>windowsRecoverySource(
        authorized(authority,action,context.plan.expected_generation,{...context,...extra}),context.plan);
      const selection=transact(()=>{
        const context=retirementContext(request,'windows_native'),{retirement,retirement_intent,historical_retirement}=context;
        const source=checkAuthority('read_recovery_retirement',context),sourceDigest=digest(source);
        if(retirement){
          need(retirement.retirement_id===request.retirement_id&&retirement.evidence.format===windowsRetirementFormat&&
            retirement.evidence.source_digest===sourceDigest,'recovery_retirement_conflict');
          return {prior:current(id)};
        }
        if(historical_retirement)need(historical_retirement.retirement_id===request.retirement_id,'recovery_retirement_conflict');
        if(retirement_intent)need(retirement_intent.retirement_id===request.retirement_id&&retirement_intent.source_digest===sourceDigest,
          'recovery_retirement_conflict');
        else{
          requireUnusedRetirementId(request,!!historical_retirement);
          need(!db.prepare('SELECT 1 FROM maintenance_recovery_windows_fence WHERE generation_id=?').get(source.generation_id),
            'recovery_retirement_conflict');
        }
        requireFreeHelper();
        return {context,source};
      });
      if(selection.prior)return selection.prior;
      const {context,source}=selection,reader=await windowsRetirementReader(source);
      const preflight=await reader.preflight(binding);
      if(context.historical_retirement)need(same(windowsRetirementFacts(context.historical_retirement.evidence),
        windowsRetirementFacts(preflight)),'recovery_runtime_generation_changed');
      const intent={retirement_id:request.retirement_id,approval_id:context.approval.approval_id,
        generation_id:preflight.generation_id,source_digest:preflight.source_digest,preflight_digest:digest(preflight)};
      const receipt={...request,approval_id:intent.approval_id,evidence:withWindowsStartupFences(preflight,binding)};
      const body=encode(receipt);
      need(body.length<=8192,'recovery_retirement_capacity');
      transact(()=>{
        const latest=retirementContext(request,'windows_native');
        need(same(latest,context),'recovery_retirement_conflict');
        requireFreeHelper();
        need(same(checkAuthority('begin_recovery_fencing',latest,{preflight}),source),'recovery_runtime_generation_changed');
        if(latest.retirement_intent)need(same(latest.retirement_intent,intent),'recovery_runtime_generation_changed');
        else db.prepare('INSERT INTO maintenance_recovery_windows_fence VALUES (?,?,?,?,?,?,?)')
          .run(id,intent.retirement_id,intent.approval_id,binding.plan_digest,intent.generation_id,intent.source_digest,intent.preflight_digest);
      });
      function requireCurrentIntent(action,extra){
        const latest=retirementContext(request,'windows_native');
        need(!latest.retirement&&same(latest.retirement_intent,intent),'recovery_retirement_conflict');
        requireFreeHelper();
        need(same(checkAuthority(action,latest,extra),source),'recovery_runtime_generation_changed');
      }
      const evidence=await reader.seal(binding,receipt.evidence,writer=>
        transact(()=>requireCurrentIntent('fence_recovery_startup',{writer})));
      return transact(()=>{
        requireCurrentIntent('adopt_recovery_retirement',{evidence});
        db.prepare('INSERT INTO maintenance_recovery_windows_fence_result VALUES (?,?,?)').run(id,body,digest(receipt));
        return current(id);
      });
    }finally{unlock();}
  }

  async function prepareStorage(input,authority){
    need(preparationEnabled,'recovery_preparation_migration_required');
    need(['linux','win32'].includes(process.platform),'recovery_preparation_platform');
    need(fields(input,'plan_ref,preparation_id')&&matches(uuid,input.plan_ref?.restore_id)&&
      matches(uuid,input.preparation_id),'recovery_preparation_request');
    const request=structuredClone(input),id=request.plan_ref.restore_id,deadline=performance.now()+1800000;
    const unlock=claimHelper();
    try{
      function load(){
        const {source}=isolation(id),candidate=current(id);
        need(candidate&&same(candidate.plan_ref,request.plan_ref),'recovery_plan_ref');
        need(['old_writers_retired','prepared_protected'].includes(candidate.phase),'recovery_retirement_required');
        return {archive:source.archive,...candidate};
      }
      function distributionFor(action,context,extra){
        const decision=authorized(authority,action,context.plan.expected_generation,{...context,...extra,preparation_request:request});
        const {distributions}=decision,roles=[...new Set(context.plan.services.map(({next_scope})=>next_scope.authority))].sort();
        need(decision.retirement_current===true&&decision.target_inactive===true&&
          decision.release_manifest_digest===context.plan.target.release_manifest_digest,'recovery_preparation_authority');
        need(fields(distributions,roles.join(','))&&roles.every(role=>{
          const pinned=distributions[role];
          return ['controller','seamer'].includes(role)&&fields(pinned,'directory,manifest_sha256')&&
            typeof pinned.directory==='string'&&path.isAbsolute(pinned.directory)&&path.resolve(pinned.directory)===pinned.directory&&
            matches(hash,pinned.manifest_sha256);
        }),'recovery_preparation_distribution');
        return structuredClone(distributions);
      }
      const selected=transact(()=>{
        const context=load(),distributions=distributionFor('begin_recovery_preparation',context);
        const intent={...request,retirement_digest:digest(context.retirement),distributions_digest:digest(distributions)};
        const prior=context.preparation_intent;
        if(prior)need(same(prior,intent),'recovery_preparation_conflict');
        if(context.preparation)return {completed:current(id)};
        requireFreeHelper();
        if(!prior){
          need(!db.prepare('SELECT 1 FROM maintenance_recovery_preparation WHERE preparation_id=?').get(request.preparation_id),
            'recovery_preparation_conflict');
          db.prepare('INSERT INTO maintenance_recovery_preparation VALUES (?,?,?,?)').run(id,request.preparation_id,encode(intent),digest(intent));
        }
        return {context,distributions,intent,receipts:isolation(id).source.receipts};
      });
      if(selected.completed)return selected.completed;
      const {context,distributions,intent,receipts}=selected,expanded=candidateDirectory(id),parent=contentDirectory;
      const manifest=await verifyExpandedArchive(expanded,context.plan.manifest_sha256,deadline);
      const inputs=context.plan.services.map(({source_scope,snapshot_receipt_id,snapshot_sha256,next_scope},index)=>{
        const receipt=receipts[index],data_generation_id=context.plan.target.services[index].data_generation_id;
        const member=manifest.databases.find(record=>record.consistency_point===snapshot_receipt_id);
        need(receipt?.backup_operation_id===snapshot_receipt_id&&receipt.sha256===snapshot_sha256&&same(receipt.scope,source_scope)&&
          member?.service===source_scope.service_id&&member.database_instance===source_scope.database_instance_id&&
          manifest.files.some(file=>file.path===member.path&&file.role==='database'&&file.size===receipt.bytes&&file.sha256===receipt.sha256),
        'recovery_preparation_source');
        return {next_scope,receipt,data_generation_id,sourceFile:path.join(expanded,'files',member.path)};
      });
      const attempt_id=randomUUID();
      function checked(action,extra){
        const latest=load();
        need(latest.phase==='old_writers_retired'&&same(latest.preparation_intent,intent),'recovery_preparation_conflict');
        requireFreeHelper();
        need(same(distributionFor(action,latest,extra),distributions),'recovery_preparation_distribution');
      }
      transact(()=>{
        checked('create_recovery_preparation_attempt',{attempt_id});
        db.prepare('INSERT INTO maintenance_recovery_preparation_attempt VALUES (?,?)').run(attempt_id,id);
      });
      const report=await prepareRecoveryFiles({parent,attempt_id,plan_digest:request.plan_ref.digest,inputs,distributions},deadline);
      await verifyProtectedRecoveryFiles(path.join(parent,attempt_id),report,deadline);
      const result={format:'leafseamer-protected-recovery-preparation/1',attempt_id,intent_digest:digest(intent),...report};
      const body=encode(result);
      need(body.length<=524288,'recovery_preparation_capacity');
      return transact(()=>{
        need(performance.now()<deadline,'backup_archive_deadline');
        checked('adopt_recovery_preparation',{result});
        db.prepare('INSERT INTO maintenance_recovery_preparation_result VALUES (?,?,?,?)').run(id,attempt_id,body,digest(result));
        return current(id);
      });
    }finally{unlock();}
  }

  return {prepare,approve,recordLinuxRetirement,recordWindowsRetirement,prepareStorage,
    get(id){need(matches(uuid,id),'restore_request');return transact(()=>current(id));}};
}
