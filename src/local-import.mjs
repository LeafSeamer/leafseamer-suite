import crypto from 'node:crypto';
import {decodeImportFrame,artifactImportVersion} from './sdk/artifact-import.mjs';
import {installationChannelPeer,installationSourceHandle} from './local-peer.mjs';
import {canonical,InstallationError,requireValue as need} from './import-input.mjs';
const id=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(value);
const requests=new Set(['IMPORT_BEGIN','IMPORT_QUERY','IMPORT_CANCEL','INTAKE_QUERY','VERIFY_MATERIALIZATION']);
const frame=(type,channel,sequence,reply,payload)=>({ipc_version:artifactImportVersion,type,channel_id:channel,sequence:String(sequence),message_id:crypto.randomUUID(),reply_to:reply,payload});
async function decode(bytes,types){
  need(Buffer.isBuffer(bytes)&&bytes.length<=65536,'import_channel_frame');
  const type=JSON.parse(bytes.toString('utf8')).type;need(types.has(type),'import_channel_direction');return decodeImportFrame(bytes,type);
}
export function serveInstallationClient({store,registration_id:registrationId,channel_id:channelId,channel,validation_policy_ref:validationPolicyRef=null,reader_sids:readerSids=[],platform_profile_ref:platformProfileRef=null}){
  need(id(registrationId)&&id(channelId),'import_channel_identity');let closed=false,binding;const jobs=new Set();
  // 启动配置在首次await前复制；管理工具不能通过IMPORT_BEGIN指定本机读取身份。
  const fixedReaders=Array.isArray(readerSids)?[...readerSids]:readerSids;
  const fixedPlatform=platformProfileRef===null?null:JSON.parse(canonical(platformProfileRef));
  const close=()=>{closed=true;binding?.close();channel.close();};
  const done=(async()=>{
    try{
      await channel.ready;binding=store.bindImportClient(channel,registrationId,{validationPolicyRef,readerSids:fixedReaders,platformProfileRef:fixedPlatform});let incoming=1n,outgoing=1n,attachments=0;const messages=new Set();
      while(!closed){
        const received=await channel.receive();
        // Windows传输附件记录，不属于SDK业务帧；请求固定为标记0及uint64句柄。
        if(received[0]===0){
          need(received.length===9&&++attachments<=4096,'import_attachment_frame');installationChannelPeer(channel);let response;
          try{const attachment=binding.registerAttachment(String(received.readBigUInt64LE(1)));response=Buffer.concat([Buffer.from([0,1]),Buffer.from(attachment,'ascii')]);}
          catch{response=Buffer.from([0,0]);}
          installationChannelPeer(channel);await channel.send(response);continue;
        }
        const value=await decode(received,requests);
        need(value.channel_id===channelId&&value.sequence===String(incoming)&&value.reply_to===null&&!messages.has(value.message_id)&&messages.size<4096,'import_channel_binding');
        installationChannelPeer(channel);messages.add(value.message_id);++incoming;let type='IMPORT_STATUS',payload;
        try{
          if(value.type==='IMPORT_BEGIN'){
            const operation=binding.beginImport(value.payload);payload=operation.status;jobs.add(operation.completion);
            operation.completion.finally(()=>jobs.delete(operation.completion)).catch(()=>{});
          }else if(value.type==='IMPORT_QUERY')payload=binding.queryImport(value.payload);
          else if(value.type==='IMPORT_CANCEL')payload=binding.cancelImport(value.payload);
          else if(value.type==='INTAKE_QUERY'){type='INTAKE_RESULT';payload=await binding.queryIntake(value.payload);}
          else if(value.type==='VERIFY_MATERIALIZATION'){type='MATERIALIZATION_RESULT';payload=await binding.verifyMaterialization(value.payload);}
          else throw new InstallationError('import_local_operation_unavailable');
        }catch(error){
          type='ERROR';payload={operation_id:null,code:({import_peer_unauthorized:'unauthorized_peer',import_not_found_or_invisible:'not_found_or_invisible',
            import_identity_conflict:'identity_conflict',import_capacity:'capacity',import_source_attachment:'invalid_request',import_validation_policy:'invalid_request',
            import_validation_policy_revoked:'invalid_request',validation_implementation:'invalid_request',
            import_trust_epoch:'invalid_request',
            materialization_capacity:'capacity',
            preparation_identity_conflict:'identity_conflict',preparation_policy:'invalid_request',
            import_local_operation_unavailable:'invalid_request',import_indeterminate:'unknown_outcome'})[error.code]??'unknown_outcome'};
        }
        const response=frame(type,channelId,outgoing++,value.message_id,payload),bytes=Buffer.from(canonical(response));await decodeImportFrame(bytes,type);
        installationChannelPeer(channel);await channel.send(bytes);
      }
    }catch(error){if(!closed)throw error;}finally{close();await Promise.allSettled(jobs);}
  })();done.catch(()=>{});return Object.freeze({done,close});
}
export function createInstallationClient({channel,channel_id:channelId}){
  need(id(channelId),'import_channel_identity');let outgoing=1n,incoming=1n,busy=false,closed=false;const messages=new Set();
  const close=()=>{closed=true;channel.close();};
  async function call(type,payload,expected='IMPORT_STATUS'){
    need(!busy&&!closed&&messages.size<4096,'import_channel_unavailable');busy=true;
    try{
      const request=frame(type,channelId,outgoing++,null,JSON.parse(canonical(payload))),bytes=Buffer.from(canonical(request));await decodeImportFrame(bytes,type);await channel.send(bytes);
      const response=await decode(await channel.receive(),new Set([expected,'ERROR']));
      need(response.channel_id===channelId&&response.sequence===String(incoming++)&&response.reply_to===request.message_id&&!messages.has(response.message_id),'import_channel_binding');
      messages.add(response.message_id);
      if(response.type==='ERROR')return {error:response.payload};
      if(expected==='MATERIALIZATION_RESULT')need(canonical(response.payload.request)===canonical(request.payload),'import_channel_binding');
      if(expected==='INTAKE_RESULT')need(response.payload.intake_id===request.payload.intake_id&&
        (response.payload.receipt===null||response.payload.receipt.intake_id===request.payload.intake_id&&
          response.payload.receipt.target_authority_service_id===request.payload.target_authority_service_id),'import_channel_binding');
      return expected==='IMPORT_STATUS'?{status:response.payload}:{result:response.payload};
    }catch(error){close();throw error;}finally{busy=false;}
  }
  return Object.freeze({
    async attach(fd){
      need(!busy&&!closed,'import_channel_unavailable');busy=true;
      try{
        const bytes=Buffer.alloc(9);bytes.writeBigUInt64LE(BigInt(installationSourceHandle(fd)),1);await channel.send(bytes);
        const reply=await channel.receive();need(reply[0]===0&&(reply.length===2&&reply[1]===0||reply.length===38&&reply[1]===1),'import_attachment_frame');
        if(reply[1]===0)return {error:'source_attachment_rejected'};
        const attachment=reply.subarray(2).toString('ascii');need(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(attachment),'import_attachment_frame');
        return {source_attachment_id:attachment};
      }catch(error){close();throw error;}finally{busy=false;}
    },
    begin:input=>call('IMPORT_BEGIN',input),query:identity=>call('IMPORT_QUERY',identity),cancel:identity=>call('IMPORT_CANCEL',identity),
    queryIntake:input=>call('INTAKE_QUERY',input,'INTAKE_RESULT'),verifyMaterialization:input=>call('VERIFY_MATERIALIZATION',input,'MATERIALIZATION_RESULT'),close});
}
