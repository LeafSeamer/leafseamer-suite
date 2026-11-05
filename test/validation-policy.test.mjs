import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import Database from 'better-sqlite3';
import {createInstallationStore,openInstallationStore} from '../dist/installation-store.mjs';
import {canonical,digest} from '../dist/import-input.mjs';
import {authorizeFixture} from './fixtures/release-authorization.mjs';
import {artifactFixture,zipFixture,digestValue} from './fixtures/artifact-package.mjs';
function directory(t,beforeRemove){const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-policy-'));t.after(()=>{beforeRemove();
  assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});});return root;}
async function fixture(t){
  let close=()=>{};const root=directory(t,()=>close()),data=path.join(root,'data');fs.mkdirSync(data);createInstallationStore(data);let store=openInstallationStore(data);
  const artifact=artifactFixture(),bytes=zipFixture(artifact.entries()).bytes,authorized=await authorizeFixture(store,bytes,digestValue(artifact.manifest));
  const policy=authorized.validationPolicy,request={identity:{host_installation_id:store.identity.host_installation_id,client_registration_id:'client.synthetic',import_request_id:'request.synthetic'},
    target_authority_service_id:'controller.synthetic',source_attachment_id:'attachment.synthetic',package_digest:authorized.result.body.package_digest,
    package_bytes:String(bytes.length),expected_manifest_digest:digestValue(artifact.manifest),host_trust_epoch:'1',release_authorization_ref:authorized.result.reference,validation_policy_ref:policy.reference};
  close=()=>{authorized.session.close();store.close();};
  const filename=path.join(root,'source.zip');fs.writeFileSync(filename,bytes);
  return {root,data,request,policy,close,get store(){return store;},reopen(){close();store=openInstallationStore(data);},
    async copy(){store.recordAcceptedImport(request);const fd=fs.openSync(filename,'r');try{return await store.copyImport(request.identity,fd);}finally{fs.closeSync(fd);}}};
}

test('新导入只接受同库校验策略原件，策略绑定实际构建及依赖且SQL拒绝伪造引用',async t=>{
  const f=await fixture(t),ref=f.policy.reference;
  assert.deepEqual(f.store.validationPolicies.configure({policy_id:'policy.synthetic',approval_reference:'approval.synthetic'}),f.policy);
  assert.equal(f.policy.body.implementation.dependencies.yauzl.version,'3.4.0');assert.match(f.policy.body.implementation.build_manifest_digest,/^sha256:/);
  assert.throws(()=>f.store.validationPolicies.configure({policy_id:'policy.synthetic',approval_reference:'changed'}),{code:'import_validation_policy_conflict'});
  for(const patch of [{object_id:'invented'},{authority_service_id:'other'},{database_instance_id:'other'},{revision:'2'},{digest:digest('wrong')},{extra:true}]){
    assert.throws(()=>f.store.recordAcceptedImport({...f.request,validation_policy_ref:{...ref,...patch}}));assert.equal(f.store.queryImport(f.request.identity),null);
  }
  const accepted=f.store.recordAcceptedImport(f.request);f.close();const db=new Database(path.join(f.data,'installation.db'));
  try{
    const {source_attachment_id,...intent}={...f.request,identity:{...f.request.identity,import_request_id:'sql.fake'},validation_policy_ref:{...ref,digest:digest('wrong')}};
    assert.throws(()=>db.prepare('INSERT INTO import_operation VALUES (?,?,?,?,?,?,?)').run(crypto.randomUUID(),...Object.values(intent.identity),intent.target_authority_service_id,digest(intent),Buffer.from(canonical(intent))),/import_validation_policy_binding/);
    for(const sql of ['DELETE FROM installation_validation_policy',"UPDATE installation_validation_policy SET body_digest='changed'"])assert.throws(()=>db.exec(sql));
  }finally{db.close();f.reopen();}
  assert.deepEqual(f.store.queryImport(f.request.identity),accepted);assert.deepEqual(f.store.validationPolicies.historical(ref),f.policy);
});

test('策略撤销阻止新受理及迟到校验成功，跨重开保留原操作和历史策略',async t=>{
  const f=await fixture(t);await f.copy();
  const validation=f.store.validateImport(f.request.identity),revoked=f.store.validationPolicies.revoke('policy.synthetic','revoke.synthetic');
  const result=await validation;assert.equal(result.state,'rejected');assert.equal(result.reason_code,'trust_denied');
  assert.throws(()=>f.store.validatedArtifact(f.request.identity),{code:'import_validation_unavailable'});
  assert.throws(()=>f.store.recordAcceptedImport({...f.request,identity:{...f.request.identity,import_request_id:'new'}}),{code:'import_validation_policy_revoked'});
  assert.deepEqual(f.store.recordAcceptedImport(f.request),result);
  f.reopen();assert.deepEqual(f.store.validationPolicies.revoke('policy.synthetic','another.operation'),revoked);
  assert.deepEqual(f.store.validationPolicies.historical(f.policy.reference),f.policy);
  assert.throws(()=>f.store.validationPolicies.configure({policy_id:'policy.synthetic',approval_reference:'approval.synthetic'}),{code:'import_validation_policy_revoked'});
  assert.deepEqual(f.store.queryImport(f.request.identity),result);
});

test('隔离安装副本发生实际校验器字节变化，即使重写清单也不能在原进程重新批准',async t=>{
  const root=directory(t,()=>{}),dist=path.join(root,'dist'),data=path.join(root,'data');
  fs.cpSync(fileURLToPath(new URL('../dist',import.meta.url)),dist,{recursive:true});fs.mkdirSync(data);
  const require=createRequire(import.meta.url),modules=path.dirname(path.dirname(path.dirname(require.resolve('canonicalize'))));
  fs.symlinkSync(modules,path.join(root,'node_modules'),'junction');
  const moduleUrl=pathToFileURL(path.join(dist,'installation-store.mjs')).href,record=path.join(root,'policy.json');
  // 实际原生模块加载后由进程持有DLL，整个隔离运行退出后再清理其目录。
  const first=spawnSync(process.execPath,['--disallow-code-generation-from-strings','--input-type=module','-e',`
    import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
    const [moduleUrl,data,dist,record]=process.argv.slice(1),module=await import(moduleUrl);module.createInstallationStore(data);const store=module.openInstallationStore(data);
    try{
      const policy=store.validationPolicies.configure({policy_id:'policy.copy',approval_reference:'approval.synthetic'}),source=path.join(dist,'archive-verifier.mjs');
      fs.appendFileSync(source,'\\n// changed deployment bytes\\n');
      assert.throws(()=>store.validationPolicies.configure({policy_id:'policy.changed',approval_reference:'approval.synthetic'}),{code:'validation_implementation'});
      const manifestFile=path.join(dist,'build-manifest.json'),manifest=JSON.parse(fs.readFileSync(manifestFile));
      manifest.artifacts['archive-verifier.mjs']=crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex');fs.writeFileSync(manifestFile,JSON.stringify(manifest));
      assert.throws(()=>store.validationPolicies.verifyImplementation(),{code:'validation_implementation'});
      assert.deepEqual(store.validationPolicies.historical(policy.reference),policy);fs.writeFileSync(record,JSON.stringify(policy));
    }finally{store.close();}
  `,moduleUrl,data,dist,record],{encoding:'utf8',windowsHide:true,timeout:10000});
  assert.equal(first.status,0,first.stderr);const policy=JSON.parse(fs.readFileSync(record));
  const restarted=spawnSync(process.execPath,['--disallow-code-generation-from-strings','--input-type=module','-e',`
    import assert from 'node:assert/strict';
    const [moduleUrl,data,encoded]=process.argv.slice(1),module=await import(moduleUrl),store=module.openInstallationStore(data),ref=JSON.parse(encoded);
    try{
      assert.deepEqual(store.validationPolicies.historical(ref).reference,ref);
      assert.throws(()=>store.validationPolicies.assertCurrent(ref),{code:'validation_implementation'});
      assert.throws(()=>store.validationPolicies.configure({policy_id:'policy.copy',approval_reference:'approval.synthetic'}),{code:'import_validation_policy_conflict'});
      assert.equal(store.validationPolicies.configure({policy_id:'policy.new-build',approval_reference:'approval.synthetic'}).reference.object_id,'policy.new-build');
    }finally{store.close();}
  `,moduleUrl,data,JSON.stringify(policy.reference)],{encoding:'utf8',windowsHide:true,timeout:10000});
  assert.equal(restarted.status,0,restarted.stderr);
});
