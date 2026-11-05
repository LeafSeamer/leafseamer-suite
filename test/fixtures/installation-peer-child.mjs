import {captureInstallationPeer,createInstallationChannel} from '../../dist/local-peer.mjs';
let channel;
process.on('message',async message=>{
  if(message.type==='connect'){
    try{
      channel=createInstallationChannel({name:message.name,peer:captureInstallationPeer(message.server_pid),server:false});await channel.ready;process.send({type:'connected'});
      while(true){const bytes=await channel.receive();await channel.send(bytes);}
    }catch(error){process.send?.({type:'closed',code:error.code});channel?.close();}
  }else if(message.type==='stop'){channel?.close();process.disconnect();}
});
process.send({type:'ready'});
