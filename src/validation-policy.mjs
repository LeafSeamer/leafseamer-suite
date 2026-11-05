import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {canonical,digest,requireValue as need,InstallationError} from './import-input.mjs';
const require=createRequire(import.meta.url),root=fileURLToPath(new URL('./',import.meta.url));
const hash=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');
const id=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(value);
function implementation(){
  try{
    const bytes=fs.readFileSync(path.join(root,'build-manifest.json')),manifest=JSON.parse(bytes);
    need(manifest.format==='leafseamer-suite-build/1'&&manifest.artifacts&&Object.keys(manifest.artifacts).length<=256,'validation_implementation');
    for(const [name,expected] of Object.entries(manifest.artifacts)){
      need(/^[a-zA-Z0-9/_.-]+$/.test(name)&&name.split('/').every(part=>part&&part!=='.'&&part!=='..'),'validation_implementation');
      need(hash(fs.readFileSync(path.join(root,name)))==='sha256:'+expected,'validation_implementation');
    }
    for(const name of ['archive-verifier.mjs','validation-policy.mjs','import-input.mjs','sdk/artifact-import.mjs'])need(manifest.artifacts[name],'validation_implementation');
    // 固定静态校验依赖的全部可执行入口；更新依赖时随产品代码明确更新闭包。
    const dependencies={};
    for(const [name,version,relative,files] of [
      ['yauzl','3.4.0','.', ['package.json','index.js','fd-slicer.js','crc32.js']],
      ['pend','1.2.0','.', ['package.json','index.js']],
      ['canonicalize','5.1.0','..', ['package.json','lib/canonicalize.js']]
    ]){
      const resolver=name==='pend'?createRequire(require.resolve('yauzl')):require;
      const directory=path.resolve(path.dirname(resolver.resolve(name)),relative),metadata=JSON.parse(fs.readFileSync(path.join(directory,'package.json')));
      need(metadata.name===name&&metadata.version===version,'validation_implementation');
      dependencies[name]={version,files:Object.fromEntries(files.map(file=>[file,hash(fs.readFileSync(path.join(directory,file)))]))};
    }
    return {format:'leafseamer-validation-implementation/1',build_manifest_digest:hash(bytes),node_version:process.versions.node,
      platform:process.platform,arch:process.arch,dependencies};
  }catch(error){throw error instanceof InstallationError?error:new InstallationError('validation_implementation',{cause:error});}
}
// 当前进程启动时绑定实际部署字节；后续漂移拒绝，不能为已加载旧代码重新批准新磁盘身份。
const loaded=canonical(implementation());
export function validationPolicies({db,transact,identity,rows,decode}){
  const reference=(policyId,bodyDigest)=>({kind:'validation_policy',authority_service_id:identity.authority_service_id,
    database_instance_id:identity.database_instance_id,object_id:policyId,revision:'1',digest:bodyDigest});
  function historical(ref){
    need(ref&&id(ref.object_id),'import_validation_policy');
    const row=rows(db,'SELECT * FROM installation_validation_policy WHERE policy_id=?',ref.object_id)[0];
    need(row&&canonical(ref)===canonical(reference(row.policy_id,row.body_digest)),'import_validation_policy');
    const body=decode(row.body,row.body_digest);
    need(body.format==='leafseamer-validation-policy/1'&&body.policy_id===row.policy_id&&body.host_installation_id===identity.host_installation_id&&id(body.approval_reference),'import_validation_policy');
    return {reference:reference(row.policy_id,row.body_digest),body};
  }
  function current(ref){
    const record=historical(ref);
    need(!db.prepare('SELECT 1 FROM installation_validation_policy_revocation WHERE policy_id=?').pluck().get(ref.object_id),'import_validation_policy_revoked');
    need(canonical(record.body.implementation)===loaded,'validation_implementation');return record;
  }
  return Object.freeze({
    configure(input){
      need(input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).sort().join(',')==='approval_reference,policy_id','import_validation_policy');
      const {policy_id:policyId,approval_reference:approvalReference}=input;need(id(policyId)&&id(approvalReference),'import_validation_policy');
      need(canonical(implementation())===loaded,'validation_implementation');
      const body={format:'leafseamer-validation-policy/1',policy_id:policyId,host_installation_id:identity.host_installation_id,
        approval_reference:approvalReference,implementation:JSON.parse(loaded)};
      return transact(()=>{
        const prior=rows(db,'SELECT * FROM installation_validation_policy WHERE policy_id=?',policyId)[0];
        if(prior)need(prior.body_digest===digest(body),'import_validation_policy_conflict');
        else db.prepare('INSERT INTO installation_validation_policy VALUES (?,?,?)').run(policyId,Buffer.from(canonical(body)),digest(body));
        return current(reference(policyId,digest(body)));
      });
    },
    revoke(policyId,operationId){
      need(id(policyId)&&id(operationId),'import_validation_policy');return transact(()=>{
        need(db.prepare('SELECT 1 FROM installation_validation_policy WHERE policy_id=?').pluck().get(policyId),'import_validation_policy');
        const prior=rows(db,'SELECT * FROM installation_validation_policy_revocation WHERE policy_id=?',policyId)[0];if(prior)return prior;
        need(!db.prepare('SELECT 1 FROM installation_validation_policy_revocation WHERE operation_id=?').pluck().get(operationId),'import_validation_policy_conflict');
        db.prepare('INSERT INTO installation_validation_policy_revocation VALUES (?,?)').run(policyId,operationId);return {policy_id:policyId,operation_id:operationId};
      });
    },
    historical:ref=>transact(()=>historical(ref)),
    verifyImplementation(){need(canonical(implementation())===loaded,'validation_implementation');},
    assertCurrent:ref=>db.inTransaction?current(ref):transact(()=>current(ref))
  });
}
