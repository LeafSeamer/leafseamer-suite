import fs from 'node:fs';
import os from 'node:os';
import crypto from 'node:crypto';
import {canonical,digest,requireValue as need} from './import-input.mjs';
const id=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(value);
const hash=value=>typeof value==='string'&&/^sha256:[0-9a-f]{64}(?![\s\S])/.test(value);
const buildDigest='sha256:'+crypto.createHash('sha256').update(fs.readFileSync(new URL('./build-manifest.json',import.meta.url))).digest('hex');

// 只由可信安装入口写入外部验收的批准引用；刷新成功不会调用configure。
export function platformQualifications({db,transact,identity,rows,decode,withPrepared,verifyImplementation}){
  const reference=(profileId,bodyDigest)=>({kind:'platform_profile',authority_service_id:identity.authority_service_id,
    database_instance_id:identity.database_instance_id,object_id:profileId,revision:'1',digest:bodyDigest});
  function scope(description){
    return {format:'leafseamer-installation-durability-scope/1',host_installation_id:identity.host_installation_id,
      installation_epoch:identity.installation_epoch,installation_directory_identity:identity.directory_identity,
      content_parent_identity:description.parent_identity,storage_identity:description.storage_identity,
      writer_sid:description.writer_sid,platform:process.platform,arch:process.arch,os_release:os.release(),
      node_version:process.versions.node,build_manifest_digest:buildDigest,
      sqlite_engine:db.prepare('SELECT sqlite_version(),sqlite_source_id()').raw().get(),
      sqlite_policy:{journal_mode:'wal',synchronous:'full',locking_mode:'exclusive'},
      dacl_profile:'windows-installer-only-write/1',flush_method:'FlushFileBuffers',
      flush_order:'files_then_directories_bottom_up_then_parent'};
  }
  function historical(ref){
    need(ref&&id(ref.object_id),'platform_qualification');
    const row=rows(db,'SELECT * FROM installation_platform_qualification WHERE profile_id=?',ref.object_id)[0];
    need(row&&canonical(ref)===canonical(reference(row.profile_id,row.body_digest)),'platform_qualification');
    const body=decode(row.body,row.body_digest);
    need(body.format==='leafseamer-platform-qualification/1'&&body.profile_id===row.profile_id&&
      body.scope.host_installation_id===identity.host_installation_id&&body.scope_digest===digest(body.scope)&&
      id(body.approval_reference)&&hash(body.evidence_digest),'installation_record_integrity');
    return {reference:reference(row.profile_id,row.body_digest),body};
  }
  function current(ref,observed){
    const record=historical(ref);
    need(!db.prepare('SELECT 1 FROM installation_platform_qualification_revocation WHERE profile_id=?').pluck().get(ref.object_id),'platform_qualification_revoked');
    need(canonical(record.body.scope)===canonical(observed),'platform_qualification_scope');return record;
  }
  const inspect=(value,fn)=>{
    verifyImplementation();
    return withPrepared(value,description=>transact(()=>fn(scope(description))));
  };
  const api=Object.freeze({
    observe:value=>inspect(value,observed=>({scope:observed,scope_digest:digest(observed)})),
    configure(value,input){
      need(input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).sort().join(',')===
        'approval_reference,evidence_digest,profile_id,scope_digest'&&id(input.profile_id)&&id(input.approval_reference)&&
        hash(input.evidence_digest)&&hash(input.scope_digest),'platform_qualification');
      const selected=JSON.parse(canonical(input));
      return inspect(value,observed=>{
        need(selected.scope_digest===digest(observed),'platform_qualification_scope');
        const body={format:'leafseamer-platform-qualification/1',...selected,scope:observed};
        const prior=rows(db,'SELECT * FROM installation_platform_qualification WHERE profile_id=?',selected.profile_id)[0];
        if(prior)need(prior.body_digest===digest(body),'platform_qualification_conflict');
        else{
          need(db.prepare('SELECT count(*) FROM installation_platform_qualification').pluck().get()<256,'platform_qualification_capacity');
          db.prepare('INSERT INTO installation_platform_qualification VALUES (?,?,?)').run(selected.profile_id,Buffer.from(canonical(body)),digest(body));
        }
        return current(reference(selected.profile_id,digest(body)),observed);
      });
    },
    historical:ref=>transact(()=>historical(ref)),
    assertCurrent:(value,ref)=>inspect(value,observed=>current(ref,observed)),
    revoke(profileId,operationId){
      need(id(profileId)&&id(operationId),'platform_qualification');return transact(()=>{
        need(db.prepare('SELECT 1 FROM installation_platform_qualification WHERE profile_id=?').pluck().get(profileId),'platform_qualification');
        const prior=rows(db,'SELECT * FROM installation_platform_qualification_revocation WHERE profile_id=?',profileId)[0];if(prior)return prior;
        need(!db.prepare('SELECT 1 FROM installation_platform_qualification_revocation WHERE operation_id=?').pluck().get(operationId),'platform_qualification_conflict');
        db.prepare('INSERT INTO installation_platform_qualification_revocation VALUES (?,?)').run(profileId,operationId);
        return {profile_id:profileId,operation_id:operationId};
      });
    }
  });
  return {api,assertObserved(ref,description){need(db.inTransaction,'installation_outer_transaction');return current(ref,scope(description));}};
}
