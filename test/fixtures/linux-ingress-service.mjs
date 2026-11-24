// 为隔离部署联调预置 Controller 人员身份，服务由正式 CLI 启动。
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const load=name=>import(pathToFileURL(path.join(input.package_root,'dist',name)));
const {initializeStorage,migrateStorage,openStorage}=await load('storage.mjs');
const {currentStorageRevision}=await load('storage-revision.mjs');
const dataDir=input.data_dir;
initializeStorage(dataDir);
await migrateStorage(dataDir,input.storage_revision??currentStorageRevision);
const store=openStorage(dataDir);
try{
  const capability=store.enrollment.begin();
  const {principal_id}=await store.enrollment.complete({...input.login,mode:'suite_issuer',token_id:capability.token_id,secret:capability.secret});
  const {issuer_id,issuer_epoch}=store.enrollment.summary();
  process.stdout.write(JSON.stringify({identity:store.identity,principal_id,issuer_id,issuer_epoch})+'\n');
}finally{store.close();}
