import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import Database from 'better-sqlite3';
import {createInstallationStore,openInstallationStore} from '../dist/installation-store.mjs';
import {releaseFixture} from './fixtures/release-manifest.mjs';
import {rawHash} from './fixtures/tuf-repository.mjs';
import {releaseRepository,initializeReleaseFixture,openReleaseFixture,validationPolicyFixture} from './fixtures/release-authorization.mjs';
const extensionDigest=rawHash(Buffer.from('extension manifest')), payload=Buffer.from('signed synthetic extension');
function setup(t) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-release-'));createInstallationStore(root);let store=openInstallationStore(root);
  const initial=releaseRepository(payload,extensionDigest),sessions=[];initializeReleaseFixture(store,initial.repo);
  const close=()=>{sessions.forEach(session=>session.close());store.close();};
  t.after(()=>{close();assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});});
  return {root,initial,get store(){return store;},close,reopen(){close();store=openInstallationStore(root);},
    async open(release=initial,options){const opened=await openReleaseFixture(store,release,options);sessions.push(opened.session);return opened;}};
}
function request(f,authorization,id='import.one') {
  return {identity:{host_installation_id:f.store.identity.host_installation_id,client_registration_id:'client.synthetic',import_request_id:id},
    target_authority_service_id:'controller.synthetic',source_attachment_id:'attachment.synthetic',host_trust_epoch:'1',
    package_digest:authorization.body.package_digest,package_bytes:authorization.body.package_bytes,expected_manifest_digest:authorization.body.expected_manifest_digest,
    release_authorization_ref:authorization.reference,validation_policy_ref:validationPolicyFixture(f.store).reference};
}
function replaceFiles(release,version=1,online='1') {
  const files=release.repo.current(version,online,['t1','t2'],release.payloads,release.custom);
  release.files.clear();for(const [name,bytes] of files)release.files.set(name,bytes);
}
test('新受理必须查到当前同库发行原件，历史查询及重复受理不恢复新请求资格',async t=>{
  const f=setup(t),opened=await f.open(),authorized=await opened.authorize();assert.deepEqual(await opened.authorize(),authorized);
  const input=request(f,authorized);
  for(const patch of [{package_bytes:'1'},{package_digest:extensionDigest},{expected_manifest_digest:rawHash(Buffer.from('other'))},
    {release_authorization_ref:{...authorized.reference,object_id:crypto.randomUUID()}},{release_authorization_ref:{...authorized.reference,database_instance_id:'other'}}])
    assert.throws(()=>f.store.recordAcceptedImport({...input,...patch}));
  assert.equal(f.store.queryImport(input.identity),null);
  const accepted=f.store.recordAcceptedImport(input);assert.equal(accepted.state,'accepted');
  opened.session.close();assert.deepEqual(f.store.recordAcceptedImport(input),accepted);
  assert.throws(()=>f.store.recordAcceptedImport(request(f,authorized,'new.request')),{code:'trust_session_unavailable'});
  f.reopen();assert.deepEqual(f.store.trust.releaseAuthorization(authorized.reference),authorized.body);
  assert.deepEqual(f.store.queryImport(input.identity),accepted);
  assert.throws(()=>f.store.recordAcceptedImport(request(f,authorized,'new.boot')),{code:'trust_session_unavailable'});
});
test('一个完整发行序号可绑定多个包，但每包目标与所选profile分别查原',async t=>{
  const f=setup(t),release=f.initial,secondBytes=Buffer.from('second signed extension');
  const extra={...release.manifest.artifacts.at(-1),artifact_id:'extension.second',path:'extensions/second.zip',size_bytes:secondBytes.length,sha256:rawHash(secondBytes)};
  release.manifest.artifacts.push(extra);release.manifest.component_bindings.find(c=>c.component_id==='leafseamer-suite').artifact_refs.push(extra.artifact_id);
  release.manifest.deployment_profiles[0].artifact_refs.push(extra.artifact_id);
  const bytes=Buffer.from(JSON.stringify(release.manifest));release.payloads.set('manifest.json',bytes);release.payloads.set('second.zip',secondBytes);
  release.binding.release_manifest.size_bytes=bytes.length;release.binding.release_manifest.digest=rawHash(bytes);
  release.custom.set('second.zip',{leafseamer:{...release.binding,artifact_id:extra.artifact_id,extension_manifest_digest:rawHash(Buffer.from('second manifest'))}});replaceFiles(release);
  const opened=await f.open(),first=await opened.authorize(),second=await opened.session.download('second.zip');
  const authorization=await opened.session.authorizeExtension({release_document_id:opened.document.document_id,package_download_id:second.download_id});
  assert.notEqual(authorization.reference.object_id,first.reference.object_id);assert.equal(authorization.body.release_manifest_digest,first.body.release_manifest_digest);
  assert.equal(authorization.body.package_digest,rawHash(secondBytes));
  const rev=await opened.session.download('revocations.json'),doc=await f.store.trust.inspectDownloadedDocument(rev.download_id,'revocations');
  await opened.session.adoptRevocations(doc.document_id);assert.deepEqual(await opened.authorize(),first);
  f.close();const db=new Database(path.join(f.root,'installation.db'));
  try{assert.equal(db.prepare('SELECT count(*) FROM trust_release_approval').pluck().get(),1);assert.equal(db.prepare('SELECT count(*) FROM trust_release_authorization').pluck().get(),2);
    for(const table of ['trust_release_approval','trust_release_authorization'])assert.throws(()=>db.exec('DELETE FROM '+table));
  }finally{db.close();}f.reopen();
});
test('发行序号与ID绑定完整原字节，回退和跨metadata代际复用均被拒绝',async t=>{
  const f=setup(t),first=await f.open();await first.authorize();first.session.close();f.reopen();
  const make=(sequence,id,version,online='1')=>{const manifest=releaseFixture();manifest.release_sequence=sequence;manifest.release_id=id;return releaseRepository(payload,extensionDigest,{manifest,repo:f.initial.repo,version,online});};
  const changed=f.initial,pretty=Buffer.from(JSON.stringify(changed.manifest,null,2));changed.payloads.set('manifest.json',pretty);
  changed.binding.release_manifest.size_bytes=pretty.length;changed.binding.release_manifest.digest=rawHash(pretty);replaceFiles(changed,2);
  const conflict=await f.open(changed);await assert.rejects(conflict.authorize(),{code:'trust_release_sequence_conflict'});
  const lower=await f.open(make('9007199254740992','older.release',3));await assert.rejects(lower.authorize(),{code:'trust_release_rollback'});
  const reused=await f.open(make('9007199254740994','synthetic.release',4));await assert.rejects(reused.authorize(),{code:'trust_release_identity_conflict'});
  const fresh=await f.open(make('9007199254740994','new.release',5));await fresh.authorize();fresh.session.close();f.reopen();
  const rotatedRelease=make('9007199254740993','rollback.after.rotation',1,'2');rotatedRelease.files.set('2.root.json',f.initial.repo.root(2,'2'));
  const rotated=await f.open(rotatedRelease);assert.equal(f.store.trust.current('release.synthetic').metadata_epoch,2);
  await assert.rejects(rotated.authorize(),{code:'trust_release_rollback'});
  f.close();const db=new Database(path.join(f.root,'installation.db'));
  try{assert.equal(db.prepare('SELECT count(*) FROM trust_release_approval').pluck().get(),2);}finally{db.close();}f.reopen();
});
test('当前会话未采用撤销原件时不推进发行序号，补足后才可受理',async t=>{
  const f=setup(t),missing=await f.open(f.initial,{adoptRevocations:false});
  await assert.rejects(missing.authorize(),{code:'trust_release_revocations'});
  f.close();const db=new Database(path.join(f.root,'installation.db'));
  try{assert.equal(db.prepare('SELECT count(*) FROM trust_release_approval').pluck().get(),0);}finally{db.close();}f.reopen();
  const valid=await f.open(),authorized=await valid.authorize();assert.equal(f.store.recordAcceptedImport(request(f,authorized)).state,'accepted');
});
test('签名合法仍拒绝清单关联错配、未列归档及撤销的发行或所选文件',async t=>{
  for(const kind of ['manifest','artifact','profile','release_revoked','manifest_revoked','artifact_revoked']){
    const f=setup(t);let release;
    if(kind.endsWith('_revoked')){
      const revocations={format:'release-revocations/1',revision:'1',revoked_release_ids:[],revoked_manifest_digests:[],revoked_artifact_digests:[]};
      if(kind==='release_revoked')revocations.revoked_release_ids.push('synthetic.release');
      if(kind==='manifest_revoked')revocations.revoked_manifest_digests.push(rawHash(f.initial.payloads.get('manifest.json')));
      if(kind==='artifact_revoked')revocations.revoked_artifact_digests.push(rawHash(payload));
      release=releaseRepository(payload,extensionDigest,{repo:f.initial.repo,revocations});
    }else release=releaseRepository(payload,extensionDigest,{repo:f.initial.repo,mutateBinding(binding){
      if(kind==='manifest')binding.release_manifest.digest=extensionDigest;
      if(kind==='artifact')binding.artifact_id='node';
      if(kind==='profile')binding.deployment_profile_id='missing';
    }});
    const opened=await f.open(release);await assert.rejects(opened.authorize(),{code:kind.endsWith('_revoked')?'trust_release_revoked':kind==='manifest'?'trust_release_binding':'trust_release_artifact'});
  }
});
