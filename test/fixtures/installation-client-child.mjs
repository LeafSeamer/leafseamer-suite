import {captureInstallationPeer,createInstallationChannel} from '../../dist/local-peer.mjs';
import {createInstallationClient} from '../../dist/local-import.mjs';
import fs from 'node:fs';
let channel,client;
process.on('message',async message=>{
  try{
    if(message.type==='connect'){
      channel=createInstallationChannel({name:message.name,peer:captureInstallationPeer(message.server_pid),server:false});await channel.ready;
      client=createInstallationClient({channel,channel_id:message.channel_id});process.send({request:message.request,type:'connected'});
    }else if(message.type==='query'||message.type==='cancel')process.send({request:message.request,result:await client[message.type](message.identity)});
    else if(message.type==='begin')process.send({request:message.request,result:await client.begin(message.input)});
    else if(['queryIntake','verifyMaterialization'].includes(message.type))process.send({request:message.request,result:await client[message.type](message.input)});
    else if(message.type==='attach'){
      const fd=fs.openSync(message.filename,message.mode??'r');
      try{process.send({request:message.request,result:await client.attach(fd)});}finally{fs.closeSync(fd);}
    }
    else if(message.type==='raw'){await channel.send(Buffer.from(message.bytes,message.encoding??'utf8'));process.send({request:message.request,bytes:(await channel.receive()).toString(message.encoding??'utf8')});}
    else if(message.type==='close'){client?.close();process.send({request:message.request,type:'closed'});}
  }catch(error){process.send?.({request:message.request,error:error.code??'client_error'});}
});
process.send({type:'ready'});
