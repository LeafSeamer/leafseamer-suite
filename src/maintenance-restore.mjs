import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {canonical,digest,InstallationError,requireValue as need} from './import-input.mjs';
import {expandPublishedArchive,inspectBackupManifest} from './maintenance-backup-archive.mjs';
import {verifyBackupSnapshots} from './backup-domain-verification.mjs';
import {initializeInstallationContentDirectory} from './local-peer.mjs';
import {recoveryPlanStore} from './maintenance-recovery-plan.mjs';

const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}(?![\s\S])/;
const generation=/^(0|[1-9][0-9]{0,19})(?![\s\S])/;
const matches=(pattern,value)=>typeof value==='string'&&pattern.test(value);
const bytes=value=>Buffer.from(canonical(value));
const unknownStorage=new Set(['installation_storage_unknown','installation_unavailable','installation_directory_changed']);

export function restoreMaintenance({db,transact,rows,decode,identity,staging,contentDirectory,runtime,published,claimHelper,
  requireFreeHelper,recoveryPlansEnabled,retirementEnabled,readLinuxRetirement}){
  const buildPlans=()=>recoveryPlanStore({db,transact,rows,decode,identity,staging,published,original,claimHelper,requireFreeHelper,
    retirementEnabled,readLinuxRetirement});
  let plans=recoveryPlansEnabled?buildPlans():null;
  function original(restoreId){
    return rows(db,`SELECT i.*,r.state,r.body,r.digest FROM maintenance_restore_intent i
      LEFT JOIN maintenance_restore_result r USING(restore_id) WHERE restore_id=?`,restoreId)[0];
  }

  function view(row){
    if(!row)return null;
    return {restore_id:row.restore_id,archive_id:row.archive_id,expected_generation:row.expected_generation,
      phase:row.state??'running',...(row.state===null?{}:decode(row.body,row.digest))};
  }

  function result(restoreId,state,body){
    db.prepare('INSERT INTO maintenance_restore_result VALUES (?,?,?,?)').run(restoreId,state,bytes(body),digest(body));
    return view(original(restoreId));
  }

  function authorized(authority,action,archive,restore,expected){
    need(typeof authority==='function','restore_authority');
    const decision=authority({action,archive:structuredClone(archive),restore:structuredClone(restore),
      expected_generation:expected});
    need(decision?.allowed===true,'restore_not_authorized');
    need(decision.generation===expected,'restore_generation_conflict');
  }

  async function stage(input,authority){
    const {restore_id:id,archive_id:archiveId,expected_generation:expected}=input??{};
    need(matches(uuid,id)&&matches(uuid,archiveId)&&matches(generation,expected),'restore_request');
    const deadline=performance.now()+1800000;
    const release=claimHelper();
    const directory=path.join(staging,'restore-'+id);
    let claimed=false,created=false,stageIdentity,secret;
    try{
      const source=transact(()=>{
        const value=published(archiveId);
        const row=original(id);
        const candidate={restore_id:id,archive_id:archiveId};
        authorized(authority,'stage_restore',value.archive,candidate,expected);
        if(row){
          need(row.archive_id===archiveId&&row.expected_generation===expected&&row.source_digest===value.sourceDigest,
            'restore_request_conflict');
          return {prior:view(row)};
        }
        requireFreeHelper();
        need(value.receipts.length>0&&Array.isArray(value.proof.verifiers),'restore_domain_reports_required');
        need(input.secret instanceof Uint8Array&&input.secret.byteLength>0&&input.secret.byteLength<=16384,
          'restore_secret_required');
        secret=Buffer.from(input.secret);
        db.prepare('INSERT INTO maintenance_restore_intent VALUES (?,?,?,?,?)')
          .run(id,archiveId,runtime,expected,value.sourceDigest);
        return value;
      });
      if(source.prior)return source.prior;
      claimed=true;
      const {archive,plan,proof,receipts}=source;
      await fs.mkdir(directory,{mode:0o700});
      created=true;
      stageIdentity=await fs.lstat(directory,{bigint:true});
      need(stageIdentity.isDirectory(),'restore_staging_failed');
      if(process.platform==='win32')initializeInstallationContentDirectory(directory);
      const file=path.join(contentDirectory,archiveId,'archive.age');
      const expanded=await expandPublishedArchive(file,directory,archive,proof,secret,deadline);
      const reportEntries=[];
      for(const {backup_operation_id} of receipts){
        const reportPath='reports/'+backup_operation_id+'.json';
        const file=path.join(expanded,'files',reportPath);
        const stat=await fs.lstat(file);
        need(stat.isFile()&&stat.nlink===1&&stat.size>0&&stat.size<=65536,'restore_domain_reports_required');
        const buffer=await fs.readFile(file);
        need(buffer.length===stat.size,'restore_domain_reports_required');
        reportEntries.push({path:reportPath,size:stat.size,sha256:crypto.createHash('sha256').update(buffer).digest('hex')});
      }
      need(digest({verifiers:proof.verifiers,reports:reportEntries})===proof.verification_ref,'restore_domain_reports_required');
      const manifest=await inspectBackupManifest(expanded,archiveId,plan,receipts,reportEntries);
      need(manifest.manifest_sha256===proof.manifest_sha256,'restore_manifest');
      const inputs=receipts.map((receipt,index)=>({receipt,
        file:path.join(expanded,'files',manifest.databaseMembers[index])}));
      const verified=await verifyBackupSnapshots(inputs,input.distributions,deadline,{reviewCommands:true});
      need(verified.verification_ref===proof.verification_ref,'restore_domain_reports_required');
      const receipt={manifest_sha256:manifest.manifest_sha256,verification_ref:verified.verification_ref,
        source_digest:source.sourceDigest,snapshot_count:receipts.length,command_review:verified.command_review};
      return transact(()=>{
        need(performance.now()<deadline,'backup_archive_deadline');
        authorized(authority,'adopt_isolated_restore',archive,{restore_id:id,archive_id:archiveId,...receipt},expected);
        return result(id,'isolated_validated',receipt);
      });
    }catch(error){
      if(!claimed||unknownStorage.has(error?.code))throw error;
      let phase='failed',reason=error instanceof InstallationError?error.code:'restore_staging_failed';
      if(created){
        try{
          const actual=await fs.lstat(directory,{bigint:true,throwIfNoEntry:false});
          if(actual){
            need(actual.isDirectory()&&actual.dev===stageIdentity?.dev&&actual.ino===stageIdentity?.ino,'restore_cleanup_unconfirmed');
            await fs.rm(directory,{recursive:true,force:true,maxRetries:4,retryDelay:50});
          }
        }
        catch{phase='indeterminate';reason='restore_cleanup_unconfirmed';}
      }
      return transact(()=>result(id,phase,{reason_code:reason}));
    }finally{
      secret?.fill(0);
      release();
    }
  }

  return {
    stage,
    preparePlan(id,target,authority){
      need(plans,'recovery_plan_migration_required');
      return plans.prepare(id,target,authority);
    },
    approvePlan(input,authority){
      need(plans,'recovery_plan_migration_required');
      return plans.approve(input,authority);
    },
    getPlan(id){
      need(plans,'recovery_plan_migration_required');
      return plans.get(id);
    },
    enablePlans(){plans=buildPlans();},
    enableRetirement(){retirementEnabled=true;plans=buildPlans();},
    recordLinuxRetirement(input,authority,native=false){
      need(plans,'recovery_plan_migration_required');
      return plans.recordLinuxRetirement(input,authority,native);
    },
    get(restoreId){
      need(matches(uuid,restoreId),'restore_request');
      return transact(()=>view(original(restoreId)));
    },
    inUse(){
      return db.prepare(`SELECT 1 FROM maintenance_restore_intent i LEFT JOIN maintenance_restore_result r USING(restore_id)
        WHERE r.state IS NULL OR r.state='indeterminate' LIMIT 1`).pluck().get()!==undefined;
    },
    recover(){
      for(const {restore_id:id} of rows(db,`SELECT i.restore_id FROM maintenance_restore_intent i
        LEFT JOIN maintenance_restore_result r USING(restore_id) WHERE i.runtime_id<>? AND r.restore_id IS NULL`,runtime)){
        result(id,'indeterminate',{reason_code:'restore_helper_unconfirmed'});
      }
    }
  };
}
