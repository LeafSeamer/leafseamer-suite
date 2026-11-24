import {canonical,requireValue as need} from './import-input.mjs';

const version='leafseamer-linux-installation-read/1';
const maxRequest=1024,maxResponse=9*1024*1024;
const id=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(value);
const methods=new Map([
  ['intake','describeIntake'],
  ['configuration_schema','describeConfigurationSchema'],
  ['capability_templates','describeCapabilityTemplates']
]);

function encode(result,operation){
  if(result.status==='unavailable'&&result.content===null)return result;
  const {content}=result;
  need(result.status==='available'&&content,'linux_installation_result');
  if(operation==='configuration_schema')return {...result,content:{...content,bytes:content.bytes.toString('base64')}};
  if(operation==='capability_templates')return {...result,content:{...content,files:content.files.map(
    ({file,bytes})=>({file,bytes:bytes.toString('base64')}))}};
  return result;
}

// The authenticated socket belongs to the current Controller process. The target never comes from the request.
export async function serveLinuxInstallationRead({socket,installation,receipt,serviceId,assertCurrent}){
  const {authority_service_id,database_instance_id,host_installation_id}=installation.identity;
  const identity={authority_service_id,database_instance_id,host_installation_id};
  let buffer=Buffer.alloc(0);
  function assertReaderCurrent(){
    need(!socket.destroyed,'linux_installation_closed');
    assertCurrent();
  }
  try{
    for await(const chunk of socket){
      need(buffer.length+chunk.length<=maxRequest,'linux_installation_frame');
      buffer=Buffer.concat([buffer,chunk]);
      const end=buffer.indexOf(10);
      if(end<0)continue;
      need(end>0&&end===buffer.length-1,'linux_installation_frame');
      const text=new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,end));
      buffer=Buffer.alloc(0);
      const request=JSON.parse(text);
      need(request&&Object.keys(request).sort().join(',')==='channel_binding_id,intake_id,operation,request_id,version'&&
        canonical(request)===text&&request.version===version&&request.channel_binding_id===receipt.channel_binding_id&&
        typeof request.request_id==='string'&&/^[a-f0-9]{32}(?![\s\S])/.test(request.request_id),'linux_installation_frame');
      const {operation,intake_id,request_id}=request;
      const method=methods.get(operation);
      need(operation==='identity'?intake_id===null:method&&id(intake_id),'linux_installation_request');
      assertReaderCurrent();
      const result=method?encode(await installation[method]({intake_id,target_authority_service_id:serviceId},assertReaderCurrent),operation):identity;
      assertReaderCurrent();
      const frame={version,channel_binding_id:receipt.channel_binding_id,operation,request_id,result};
      let reply=Buffer.from(canonical(frame)+'\n');
      if(reply.length>maxResponse)reply=Buffer.from(canonical({...frame,result:{status:'unavailable',content:null}})+'\n');
      await new Promise((resolve,reject)=>socket.write(reply,error=>error?reject(error):resolve()));
    }
  }finally{socket.destroy();}
}
