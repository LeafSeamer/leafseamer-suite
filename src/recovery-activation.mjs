import {canonical,digest,requireValue as need} from './import-input.mjs';
import {verifyProtectedRecoveryCandidate} from './recovery-site-review.mjs';

const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}(?![\s\S])/;
const hash=/^sha256:[a-f0-9]{64}(?![\s\S])/;
const reference=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/;
const counter=/^(0|[1-9][0-9]{0,19})(?![\s\S])/;
const osSubject=process.platform==='win32'?/^S-1-[0-9]+(?:-[0-9]+){1,15}(?![\s\S])/u:/^uid:(?:0|[1-9][0-9]{0,9})(?![\s\S])/u;
const matches=(pattern,value)=>typeof value==='string'&&pattern.test(value);
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const same=(left,right)=>canonical(left)===canonical(right);
const serviceKeys=services=>services.map(({scope})=>scope.authority+':'+scope.service_id).sort();

function writerKeys(services){
  return services.map(({authority,service_id,database_instance_id})=>authority+':'+service_id+':'+database_instance_id).sort();
}

function baseline(input,validScope){
  need(fields(input,'deployment_plan_digest,deployment_plan_ref,generation,generation_id,release_manifest_digest,services')&&
    matches(counter,input.generation)&&matches(uuid,input.generation_id)&&matches(reference,input.deployment_plan_ref)&&
    matches(hash,input.deployment_plan_digest)&&matches(hash,input.release_manifest_digest)&&
    Array.isArray(input.services)&&input.services.length>=2&&input.services.length<=256,'active_deployment_baseline');
  for(const service of input.services){
    need(fields(service,'configuration_digest,configuration_ref,data_generation_id,data_ref,scope,secret_binding_digest,secret_binding_ref,secret_policy_ref')&&
      validScope(service.scope)&&matches(uuid,service.data_generation_id)&&
      [service.configuration_ref,service.data_ref,service.secret_binding_ref,service.secret_policy_ref].every(value=>matches(reference,value))&&
      [service.configuration_digest,service.secret_binding_digest].every(value=>matches(hash,value)),'active_deployment_baseline');
  }
  const {services}=input;
  need(new Set(serviceKeys(services)).size===services.length&&new Set(services.map(item=>item.data_generation_id)).size===services.length&&
    ['controller','seamer'].every(role=>services.some(({scope})=>scope.authority===role)),'active_deployment_baseline');
  return structuredClone(input);
}

export function recoveryActivationStore({db,transact,rows,decode,installation,contentDirectory,claimHelper,requireFreeHelper,
  authorized,validScope,load}){
  function read(row){
    if(!row)return null;
    const selection=decode(row.body,row.digest);
    need(selection.format==='leafseamer-active-deployment/1'&&same(selection.installation,installation)&&
      selection.deployment.generation===row.generation&&selection.deployment.generation_id===row.generation_id&&
      (selection.activation?.activation_id??null)===row.activation_id&&(selection.activation?.plan_ref.restore_id??null)===row.restore_id&&
      (selection.activation?.review_digest??null)===row.review_digest&&
      (selection.activation?.expected_selection_digest??null)===row.previous_digest&&
      selection.phase===(selection.activation?'activated_protected':'registered'),'deployment_selection_integrity');
    return {...selection,selection_digest:row.digest};
  }

  const active=()=>read(rows(db,`SELECT s.* FROM installation_active_deployment p
    JOIN installation_deployment_selection s ON s.digest=p.selection_digest WHERE p.singleton=1`)[0]);
  const byOperation=id=>read(rows(db,'SELECT * FROM installation_deployment_selection WHERE activation_id=?',id)[0]);

  function insert(deployment,activation,os_subject){
    const selection={format:'leafseamer-active-deployment/1',installation,phase:activation?'activated_protected':'registered',
      deployment,activation,os_subject};
    const body=Buffer.from(canonical(selection)),selection_digest=digest(selection);
    need(body.length<=524288,'deployment_selection_capacity');
    db.prepare('INSERT INTO installation_deployment_selection VALUES (?,?,?,?,?,?,?,?)').run(selection_digest,
      deployment.generation,deployment.generation_id,activation?.expected_selection_digest??null,activation?.activation_id??null,
      activation?.plan_ref.restore_id??null,activation?.review_digest??null,body);
    return {...selection,selection_digest};
  }

  function checkLocal(decision){
    need(['linux','win32'].includes(process.platform)&&decision.origin==='local_os'&&matches(osSubject,decision.os_subject)&&
      decision.os_subject.length<=184,'recovery_local_admin_required');
    return decision.os_subject;
  }

  function registerActive(input,authority){
    const deployment=baseline(input,validScope),deployment_digest=digest(deployment);
    return transact(()=>{
      requireFreeHelper();
      const decision=authorized(authority,'register_active_deployment',deployment.generation,{installation,deployment,deployment_digest});
      const subject=checkLocal(decision);
      need(decision.active_current===true&&decision.deployment_digest===deployment_digest,'active_deployment_authority');
      const previous=active();
      if(previous){
        need(previous.phase==='registered'&&same(previous.deployment,deployment),'deployment_selection_conflict');
        return previous;
      }
      const selected=insert(deployment,null,subject);
      db.prepare('INSERT INTO installation_active_deployment VALUES (1,?)').run(selected.selection_digest);
      return selected;
    });
  }

  function current(id,candidate){
    const selected=read(rows(db,'SELECT * FROM installation_deployment_selection WHERE restore_id=?',id)[0]);
    if(!selected)return candidate;
    need(same(selected.activation.plan_ref,candidate.plan_ref)&&selected.activation.review_digest===candidate.site_review?.review_digest&&
      selected.activation.preparation_digest===digest(candidate.preparation)&&selected.activation.retirement_digest===digest(candidate.retirement),'deployment_selection_integrity');
    return {...candidate,phase:'activated_protected',activation:selected};
  }

  async function activate(input,authority){
    need(fields(input,'activation_id,expected_selection_digest,plan_ref,review_digest')&&matches(uuid,input.plan_ref?.restore_id)&&
      matches(uuid,input.activation_id)&&matches(hash,input.expected_selection_digest)&&matches(hash,input.review_digest),'recovery_activation_request');
    const request=structuredClone(input),id=request.plan_ref.restore_id,deadline=performance.now()+1800000;
    const unlock=claimHelper();
    try{
      function confirm(action,context,previous,deployment){
        const deployment_digest=digest(deployment);
        const decision=authorized(authority,action,previous.deployment.generation,
          {...context,confirmation:request,previous,deployment,deployment_digest});
        const subject=checkLocal(decision);
        need(decision.retirement_current===true&&decision.target_inactive===true&&decision.deployment_digest===deployment_digest&&
          decision.release_manifest_digest===deployment.release_manifest_digest&&decision.review_digest===request.review_digest,'recovery_activation_authority');
        return subject;
      }
      const selected=transact(()=>{
        const prior=byOperation(request.activation_id);
        if(prior){
          need(Object.keys(request).every(key=>same(prior.activation[key],request[key])),'deployment_selection_conflict');
          return {prior};
        }
        const context=load(id,request.plan_ref),previous=active();
        need(previous,'active_deployment_required');
        need(context.phase==='prepared_protected'&&context.site_review?.review_digest===request.review_digest,'recovery_activation_review');
        const {plan,retirement,site_review,preparation}=context,{target}=plan;
        need(previous.selection_digest===request.expected_selection_digest&&previous.deployment.generation===plan.expected_generation&&
          previous.deployment.generation_id===retirement.evidence.generation_id&&
          same(serviceKeys(previous.deployment.services),serviceKeys(site_review.evidence.services))&&
          same(writerKeys(previous.deployment.services.map(({scope})=>scope)),writerKeys(retirement.evidence.members))&&
          !site_review.evidence.services.some(service=>previous.deployment.services.some(old=>old.data_generation_id===service.data_generation_id))&&
          !rows(db,'SELECT 1 FROM installation_deployment_selection WHERE generation_id=?',target.generation_id).length,'deployment_selection_conflict');
        const generation=String(BigInt(previous.deployment.generation)+1n);
        need(matches(counter,generation),'deployment_selection_capacity');
        const deployment={deployment_plan_ref:target.deployment_plan_ref,deployment_plan_digest:target.deployment_plan_digest,
          release_manifest_digest:target.release_manifest_digest,generation_id:target.generation_id,generation,
          services:site_review.evidence.services.map((service,index)=>{
            const member=preparation.services[index];
            return {...service,data_ref:{attempt_id:preparation.attempt_id,directory_name:member.directory_name,
              sha256:member.sha256,bytes:member.bytes}};
          })};
        requireFreeHelper();
        const subject=confirm('check_recovery_activation',context,previous,deployment);
        return {context,previous,deployment,subject};
      });
      if(selected.prior)return selected.prior;
      const {context,previous,deployment,subject}=selected;
      await verifyProtectedRecoveryCandidate(contentDirectory,context.preparation,deadline);
      return transact(()=>{
        need(performance.now()<deadline,'backup_archive_deadline');
        const latest=load(id,request.plan_ref);
        need(active()?.selection_digest===previous.selection_digest&&same(latest,context),'deployment_selection_conflict');
        requireFreeHelper();
        need(confirm('adopt_recovery_activation',latest,previous,deployment)===subject,'recovery_local_admin_required');
        const result=insert(deployment,{...request,preparation_digest:digest(context.preparation),
          retirement_digest:digest(context.retirement)},subject);
        const {changes}=db.prepare('UPDATE installation_active_deployment SET selection_digest=? WHERE singleton=1 AND selection_digest=?')
          .run(result.selection_digest,request.expected_selection_digest);
        need(changes===1,'deployment_selection_conflict');
        return result;
      });
    }finally{unlock();}
  }

  return {registerActive,current,activate,active:()=>transact(active),query(id){
    need(matches(uuid,id),'recovery_activation_request');
    return transact(()=>byOperation(id));
  }};
}
