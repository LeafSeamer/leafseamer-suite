import crypto from 'node:crypto';
import {canonical,digest,requireValue as need,InstallationError} from './import-input.mjs';
import {decodeArtifactDocument} from './sdk/artifact-import.mjs';
import {observePreparedContent,holdPreparedContent} from './prepared-content.mjs';
import {installationObservationTick} from './local-peer.mjs';

export function materializationProvider({db,transact,identity,rows,decode,required,sealing,policies,trust,qualifications,
  preparedArtifact,validatedArtifact,contentDirectory,isUnavailable}){
  let active=0,previousTick=0n;const holds=new Set();const domainId=crypto.randomUUID();
  function tick(){const value=installationObservationTick();need(value>=previousTick&&value<=18446744073709551615n,'materialization_clock');previousTick=value;return value;}
  function descriptor(){
    tick();return Object.freeze({format:'leafseamer-materialization-clock/1',clock_domain_id:domainId,
      host_installation_id:identity.host_installation_id,authority_service_id:identity.authority_service_id,
      database_instance_id:identity.database_instance_id,backend:'windows_interrupt_precise',unit:'ns',scope:'windows-global',
      lifetime:'installation_store_open'});
  }
  function clockRef(){const value=descriptor();return {clock_domain_id:domainId,descriptor_digest:digest(value)};}
  function snapshot(request){
    const selected=transact(()=>{
      const row=rows(db,`SELECT o.intent_body,o.intent_digest FROM artifact_intake i JOIN import_operation o USING(operation_id)
        WHERE i.intake_id=? AND o.target_authority_service_id=?`,request.intake_id,request.target_authority_service_id)[0];
      if(!row)return null;const intent=decode(row.intent_body,row.intent_digest),record=required(intent.identity);
      need(record.state==='sealed','installation_record_integrity');return {intent,receipt:sealing.receipt(record)};
    });
    if(!selected)return null;
    const value=selected.intent.identity,history=sealing.sealedArtifact(value),prepared=preparedArtifact(value),validated=validatedArtifact(value);
    need(history.receipt.intake_id===request.intake_id&&history.verification.preparation_id===prepared.preparation_id&&
      history.verification.validation_id===validated.validation_id&&history.verification.validation_report_digest===validated.report_digest&&
      history.verification.root_identity===prepared.body.root_identity&&history.receipt.manifest_digest===validated.report.manifest_digest&&
      history.receipt.artifact_set_digest===validated.report.artifact_set_digest,'installation_record_integrity');
    return {...selected,prepared,validated};
  }
  async function inspect(kind,input,authorize=()=>{},includeContent=false){
    // 在首次等待前复制输入，网络入口另有64KiB帧预算及当前对端认证。
    const bytes=Buffer.from(canonical(input)),request=await decodeArtifactDocument(bytes,kind);authorize(request);
    const start=tick(),domain=clockRef();
    const answer=(result,receipt=null,content=null)=>includeContent?{status:result==='verified'?'available':'unavailable',content}:
      kind==='IntakeQuery'?{intake_id:request.intake_id,status:result==='verified'?'available':'unavailable',receipt:result==='verified'?receipt:null}:
      {request,result,evidence_id:result==='verified'?crypto.randomUUID():null,observer_domain:domain,observed_tick:String(tick())};
    need(active+holds.size<4,'materialization_capacity');++active;let pendingHold=null,delivered=false;
    try{
      policies.verifyImplementation();const selected=snapshot(request);if(!selected)return answer('unavailable');
      const schemaFile=includeContent==='configuration_schema'?selected.validated.report.inventory.files.find(file=>
        file.file_id===selected.validated.report.manifest.configuration_schema_file_id&&file.role==='schema'):null;
      need(includeContent!=='configuration_schema'||schemaFile,'installation_record_integrity');
      const capabilityFiles=includeContent==='capability_templates'?selected.validated.report.inventory.files.filter(file=>
        selected.validated.report.manifest.capability_template_file_ids.includes(file.file_id)&&file.role==='schema'):null;
      if(capabilityFiles)need(capabilityFiles.length===selected.validated.report.manifest.capability_template_file_ids.length&&
        capabilityFiles.reduce((total,file)=>total+BigInt(file.size_bytes),0n)<=1048576n,'content_read_capacity');
      if(kind==='VerifyMaterialization'&&(request.manifest_digest!==selected.receipt.manifest_digest||
        request.artifact_set_digest!==selected.receipt.artifact_set_digest||request.host_trust_epoch!==selected.receipt.host_trust_epoch))return answer('mismatch');
      let observed;
      const checkCurrent=()=>{
        authorize(request);need(tick()-start<4000000000n,'materialization_timeout');
        return transact(()=>{
          sealing.assertEpoch(selected.intent);policies.assertCurrent(selected.receipt.validation_policy_ref);
          if(observed)qualifications.assertObserved(selected.receipt.platform_profile_ref,observed);
          return trust.currentReleaseForArtifact(selected.receipt.release_authorization_ref,selected.intent);
        });
      };
      const hold=includeContent==='loader';
      const result=await (hold?holdPreparedContent:observePreparedContent)({parent_directory:contentDirectory,prepared:selected.prepared,validated:selected.validated,
        read_files:(schemaFile?[schemaFile]:capabilityFiles??[]).map(file=>({file_id:file.file_id,path:file.path}))},{
        checkCurrent,timeoutMs:4000,
        complete(description,flushed,documents){
          policies.verifyImplementation();checkCurrent();
          return transact(()=>{qualifications.assertObserved(selected.receipt.platform_profile_ref,description);observed=description;
            const content=includeContent?{format:'leafseamer-intake-content/1',
              intake_ref:{kind:'intake',authority_service_id:identity.authority_service_id,database_instance_id:identity.database_instance_id,
                object_id:selected.receipt.intake_id,revision:'1',digest:digest(selected.receipt)},
              receipt:selected.receipt,manifest:selected.validated.report.manifest,inventory:selected.validated.report.inventory}:null;
            if(hold)return answer('verified',selected.receipt,{...content,format:'leafseamer-loader-materialization/1',root:description,
              lifetime:{clock:domain,issued_tick:String(start),deadline_tick:String(start+4000000000n)}});
            if(capabilityFiles){
              need(documents?.length===capabilityFiles.length,'installation_record_integrity');
              const files=capabilityFiles.map((file,index)=>{const document=documents[index];need(document.file_id===file.file_id,'installation_record_integrity');
                const bytes=Buffer.from(document.bytes);need(String(bytes.length)===file.size_bytes&&'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex')===file.digest,'installation_record_integrity');return {file,bytes};});
              return answer('verified',selected.receipt,{format:'leafseamer-capability-template-files/1',intake_ref:content.intake_ref,
                manifest_digest:selected.receipt.manifest_digest,artifact_set_digest:selected.receipt.artifact_set_digest,files});
            }
            if(schemaFile){
              need(documents?.length===1&&documents[0].file_id===schemaFile.file_id,'installation_record_integrity');
              const bytes=Buffer.from(documents[0].bytes);need(String(bytes.length)===schemaFile.size_bytes&&
                'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex')===schemaFile.digest,'installation_record_integrity');
              return answer('verified',selected.receipt,{format:'leafseamer-configuration-schema/1',intake_ref:content.intake_ref,
                manifest_digest:selected.receipt.manifest_digest,artifact_set_digest:selected.receipt.artifact_set_digest,file:schemaFile,bytes});
            }
            return answer('verified',selected.receipt,content);});
        }
      });
      if(hold)pendingHold=result;
      checkCurrent();transact(()=>qualifications.assertObserved(selected.receipt.platform_profile_ref,observed));
      if(hold){
        const freeze=value=>{if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
        const held=Object.freeze({status:'available',content:freeze(result.value.content),assertCurrent:result.assertCurrent,close:result.close,closed:result.closed});
        holds.add(held);held.closed.then(()=>holds.delete(held));delivered=true;return held;
      }
      return result;
    }catch(error){
      if(isUnavailable())throw error;
      // 对端授权错误仍是协议错误，不能以unavailable隐藏当前调用者已经失权的事实。
      if(error instanceof InstallationError&&/^(trust_|import_trust_epoch|import_validation_policy|validation_implementation|platform_qualification|preparation_|content_|peer_native_artifact|materialization_timeout|sealing_)/.test(error.code))return answer('unavailable');
      throw error;
    }finally{if(pendingHold&&!delivered)await pendingHold.close();--active;}
  }
  return {get activeCount(){return active+holds.size;},descriptor,query:(value,authorize)=>inspect('IntakeQuery',value,authorize),
    describe:value=>inspect('IntakeQuery',value,undefined,true),
    configurationSchema:value=>inspect('IntakeQuery',value,undefined,'configuration_schema'),
    capabilityTemplates:value=>inspect('IntakeQuery',value,undefined,'capability_templates'),
    acquire:value=>inspect('IntakeQuery',value,undefined,'loader'),
    verify:(value,authorize)=>inspect('VerifyMaterialization',value,authorize)};
}
