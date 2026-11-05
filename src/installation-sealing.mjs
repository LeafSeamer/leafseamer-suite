import crypto from 'node:crypto';
import {canonical,digest,requireValue as need,importIdentity} from './import-input.mjs';
import {verifyForSealing} from './prepared-content.mjs';
const id=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(value);
export function installationSealing({db,transact,identity,rows,decode,required,view,event,policies,trust,qualifications,
  preparedArtifact,validatedArtifact,contentDirectory,isUnavailable}){
  const active=new Set();
  const ref=(kind,objectId,bodyDigest)=>({kind,authority_service_id:identity.authority_service_id,
    database_instance_id:identity.database_instance_id,object_id:objectId,revision:'1',digest:bodyDigest});
  const epoch=()=>String(db.prepare('SELECT max(epoch) FROM installation_trust_epoch').pluck().get());
  const assertEpoch=intent=>need(intent.host_trust_epoch===epoch(),'import_trust_epoch');
  function current(value,policy,attempt){
    const prior=required(value);need(prior.state==='sealing'&&prior.revision===attempt.revision,'sealing_obsolete');
    assertEpoch(prior.intent);policies.assertCurrent(prior.intent.validation_policy_ref);
    trust.assertCurrentRelease(policy.release_authorization_ref,prior.intent);return prior;
  }
  function receipt(record){
    const row=rows(db,'SELECT * FROM artifact_intake WHERE operation_id=? AND sealed_revision=?',record.operation_id,record.revision)[0];
    need(row,'installation_record_integrity');const body=decode(row.body,row.body_digest);
    need(body.intake_id===row.intake_id&&body.import_operation_id===record.operation_id&&
      body.host_installation_id===identity.host_installation_id&&body.target_authority_service_id===record.target_authority_service_id&&
      body.host_trust_epoch===record.intent.host_trust_epoch,'installation_record_integrity');return body;
  }
  return {
    get activeCount(){return active.size;},receipt,assertEpoch,
    trustEpoch:()=>transact(epoch),
    advanceTrustEpoch(input){
      need(input&&Object.keys(input).sort().join(',')==='expected_epoch,operation_id'&&id(input.operation_id)&&
        typeof input.expected_epoch==='string'&&/^[1-9][0-9]{0,15}(?![\s\S])/.test(input.expected_epoch),'import_trust_epoch');
      return transact(()=>{
        const prior=rows(db,'SELECT * FROM installation_trust_epoch WHERE operation_id=?',input.operation_id)[0];
        if(prior){need(String(prior.previous_epoch)===input.expected_epoch,'import_identity_conflict');return String(prior.epoch);}
        need(epoch()===input.expected_epoch,'import_trust_epoch');const previous=Number(input.expected_epoch);
        need(Number.isSafeInteger(previous)&&previous<Number.MAX_SAFE_INTEGER,'import_capacity');
        db.prepare('INSERT INTO installation_trust_epoch VALUES (?,?,?)').run(previous+1,input.operation_id,previous);return String(previous+1);
      });
    },
    async seal(value,options){
      value=importIdentity(value);need(options&&Object.keys(options).sort().join(',')==='platform_profile_ref,release_authorization_ref','sealing_policy');
      const policy=JSON.parse(canonical(options));
      const original=transact(()=>{const prior=required(value);return ['sealed','cancelled','rejected'].includes(prior.state)?view(prior):null;});
      if(original)return original;
      policies.verifyImplementation();
      const prepared=preparedArtifact(value),validated=validatedArtifact(value);
      // 进入sealing前先核资格；后续commit仍以worker当前观察重核，不能用这次查询替代。
      qualifications.api.assertCurrent(value,policy.platform_profile_ref);
      const attempt=transact(()=>{
        const prior=required(value);need(['validating','sealing'].includes(prior.state)&&!active.has(prior.operation_id),'sealing_state');
        assertEpoch(prior.intent);policies.assertCurrent(prior.intent.validation_policy_ref);trust.assertCurrentRelease(policy.release_authorization_ref,prior.intent);
        need(db.prepare('SELECT count(*) FROM import_sealing_attempt WHERE operation_id=?').pluck().get(prior.operation_id)<16,'sealing_capacity');
        const sealId=crypto.randomUUID(),verificationId=crypto.randomUUID(),intakeId=crypto.randomUUID(),revision=prior.revision+1;
        event(prior.operation_id,revision,'sealing',null,{kind:'content_sealing',seal_id:sealId});
        db.prepare('INSERT INTO import_sealing_attempt(seal_id,operation_id,revision,preparation_id,policy_body,policy_digest,verification_id,intake_id) VALUES (?,?,?,?,?,?,?,?)')
          .run(sealId,prior.operation_id,revision,prepared.preparation_id,Buffer.from(canonical(policy)),digest(policy),verificationId,intakeId);
        return {seal_id:sealId,verification_id:verificationId,intake_id:intakeId,revision,operation_id:prior.operation_id};
      });
      active.add(attempt.operation_id);
      try{
        return await verifyForSealing({parent_directory:contentDirectory,prepared,validated},{
          checkCurrent:()=>transact(()=>current(value,policy,attempt)),
          commit(description,flushed){
            policies.verifyImplementation();
            return transact(()=>{
              const prior=current(value,policy,attempt);qualifications.assertObserved(policy.platform_profile_ref,description);
              need(description.root_identity===prepared.body.root_identity&&canonical(description.storage_identity)===canonical(prepared.body.storage_identity)&&
                flushed.parent_identity===description.parent_identity&&flushed.format==='windows-content-flush/1'&&flushed.method==='FlushFileBuffers'&&
                flushed.file_count===validated.report.file_count&&flushed.order==='files_then_directories_bottom_up_then_parent','sealing_observation');
              const verification={format:'leafseamer-seal-verification/1',seal_id:attempt.seal_id,preparation_id:prepared.preparation_id,
                host_trust_epoch:epoch(),validation_id:validated.validation_id,validation_report_digest:validated.report_digest,
                root_identity:description.root_identity,storage_identity:description.storage_identity,metadata_flush:flushed,
                platform_profile_ref:policy.platform_profile_ref,validation_policy_ref:prior.intent.validation_policy_ref,
                release_authorization_ref:policy.release_authorization_ref};
              db.prepare('INSERT INTO import_seal_verification VALUES (?,?,?,?)').run(attempt.verification_id,attempt.seal_id,Buffer.from(canonical(verification)),digest(verification));
              const report=validated.report,body={host_installation_id:identity.host_installation_id,host_trust_epoch:epoch(),
                import_operation_id:prior.operation_id,intake_id:attempt.intake_id,target_authority_service_id:prior.target_authority_service_id,
                manifest_digest:report.manifest_digest,artifact_set_digest:report.artifact_set_digest,package_bytes:prior.intent.package_bytes,
                file_inventory_digest:report.file_inventory_digest,dependency_lock_digest:report.dependency_lock_digest,
                platform_profile_ref:policy.platform_profile_ref,validation_policy_ref:prior.intent.validation_policy_ref,
                release_authorization_ref:policy.release_authorization_ref,verification_record_ref:ref('verification',attempt.verification_id,digest(verification))};
              event(prior.operation_id,prior.revision+1,'sealed',null,{kind:'content_sealed',intake_id:attempt.intake_id});
              db.prepare('INSERT INTO artifact_intake VALUES (?,?,?,?,?,?)').run(attempt.intake_id,prior.operation_id,prior.revision+1,attempt.verification_id,Buffer.from(canonical(body)),digest(body));
              return view(required(value));
            });
          }
        });
      }catch(error){
        if(isUnavailable())throw error;
        return transact(()=>{
          const prior=required(value);if(prior.state!=='sealing'||prior.revision!==attempt.revision)return view(prior);
          const code=error?.code??'';
          const trustFailure=/^(trust_|platform_qualification|import_trust_epoch|import_validation_policy|validation_implementation)/.test(code);
          const contentFailure=/^(content_|preparation_)/.test(code)&&!/(flush|open|directory|unavailable)/.test(code);
          const reason=trustFailure?'trust_denied':contentFailure?'content_mismatch':'storage_unknown';
          event(prior.operation_id,prior.revision+1,reason==='storage_unknown'?'indeterminate':'rejected',reason,{kind:'sealing_failed',seal_id:attempt.seal_id});
          return view(required(value));
        });
      }finally{active.delete(attempt.operation_id);}
    },
    sealedArtifact(value){
      return transact(()=>{
        const prior=required(value);need(prior.state==='sealed','intake_unavailable');const body=receipt(prior);
        const row=rows(db,'SELECT * FROM import_seal_verification WHERE verification_id=?',body.verification_record_ref.object_id)[0];
        need(row&&canonical(body.verification_record_ref)===canonical(ref('verification',row.verification_id,row.body_digest)),'installation_record_integrity');
        return {receipt:body,intake_ref:ref('intake',body.intake_id,digest(body)),verification:decode(row.body,row.body_digest)};
      });
    }
  };
}
