// 仅用于隔离部署联调。应用、存储与原生时钟来自安装制品。
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const load=name=>import(pathToFileURL(path.join(input.package_root,'dist',name)));
const {initializeStorage,migrateStorage,openStorage}=await load('storage.mjs');
const dataDir=input.data_dir;
initializeStorage(dataDir);
if(input.role==='controller'){
  const {currentStorageRevision}=await load('storage-revision.mjs');
  await migrateStorage(dataDir,currentStorageRevision);
  const store=openStorage(dataDir);
  try{
    const capability=store.enrollment.begin();
    await store.enrollment.complete({...input.login,mode:'suite_issuer',token_id:capability.token_id,secret:capability.secret});
    const {issuer_id,issuer_epoch}=store.enrollment.summary();
    const issuer={service_id:store.identity.service_id,issuer_id,issuer_epoch};
    process.stdout.write(JSON.stringify({identity:store.identity,issuer})+'\n');
  }finally{store.close();}
}else{
  migrateStorage(dataDir,'33');
  const {startSeamer}=await load('server.mjs');
  const credentials={cert:fs.readFileSync(input.cert),key:fs.readFileSync(input.key)};
  const app=await startSeamer({dataDir,pairing:{...credentials,host:'127.0.0.1',port:0,issuer:input.issuer,
    serverName:input.peerName,credential_id:crypto.randomUUID(),ca:[fs.readFileSync(input.ca)]},
    publicApi:{...credentials,binding_id:crypto.randomUUID(),allowedOrigins:[input.origin]}});
  const publicPort=app.publicOrigin?Number(new URL(app.publicOrigin).port):app.address.port;
  process.stdout.write(JSON.stringify({event:'started',identity:app.identity,public_port:publicPort,qualified:app.authenticationStatus().qualified})+'\n');
  process.stdin.resume();
  await new Promise(resolve=>process.stdin.once('end',resolve));
  await app.close();
}
