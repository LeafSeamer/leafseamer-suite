import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {canonical, digest, InstallationError, requireValue as need} from './import-input.mjs';
import {stageSQLiteSnapshot} from './sqlite-snapshot.mjs';

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}(?![\s\S])/;
const id = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/;
const counter = /^(0|[1-9][0-9]{0,19})(?![\s\S])/;
const hash = /^sha256:[a-f0-9]{64}(?![\s\S])/;
const rawHash = /^[a-f0-9]{64}(?![\s\S])/;
const matches = (pattern, value) => typeof value === 'string' && pattern.test(value);
const fields = (value, names) => value && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value).sort().join(',') === names;
const bytes = value => Buffer.from(canonical(value));
const method = 'POST', route = '/api/v1/maintenance/operations';
const operation = 'requestMaintenanceOperation';

function validScope(scope) {
  return fields(scope, 'authority,control_epoch,database_instance_id,request_epoch,schema_revision,service_id') &&
    ['controller','seamer'].includes(scope.authority) &&
    [scope.service_id,scope.database_instance_id,scope.request_epoch].every(value=>matches(uuid,value)) &&
    (scope.authority==='controller' ? matches(uuid,scope.control_epoch) : scope.control_epoch===null) &&
    matches(counter,scope.schema_revision) && Number(scope.schema_revision)>0 && Number(scope.schema_revision)<=2147483647;
}

function backupPlan(value) {
  const levels = ['L0','L1','L2','L3'];
  need(fields(value,'backup_level,consistency,coverage_digest,deployment_plan_ref,encryption_profile_ref,expected_generation,kind,resource_profile_ref,target_service_scopes') &&
    value.kind==='backup' && levels.includes(value.backup_level) && ['online','maintenance'].includes(value.consistency) &&
    matches(hash,value.coverage_digest) && matches(counter,value.expected_generation) &&
    [value.deployment_plan_ref,value.encryption_profile_ref,value.resource_profile_ref].every(ref=>matches(id,ref)) &&
    Array.isArray(value.target_service_scopes) && value.target_service_scopes.length<=256 &&
    (levels.indexOf(value.backup_level)>=2 || value.target_service_scopes.length===0) &&
    value.target_service_scopes.every(validScope) &&
    new Set(value.target_service_scopes.map(item=>item.database_instance_id)).size===value.target_service_scopes.length,
  'backup_plan_invalid');
  return JSON.parse(canonical(value));
}

export function backupMaintenance({db, transact, rows, decode, identity, staging}) {
  const runtime = crypto.randomUUID();
  const installation = {installation_id:identity.host_installation_id, installation_epoch:identity.installation_epoch};
  let active = 0;

  function key(value) {
    const human = value?.origin==='human';
    const expected = human ?
      'idempotency_key,installation_epoch,installation_id,issuer_epoch,issuer_id,operation,origin,principal_id,request_epoch' :
      'idempotency_key,installation_epoch,installation_id,operation,origin,os_subject,request_epoch';
    need(fields(value,expected) && (human || value.origin==='local_os') && value.operation===operation &&
      value.installation_id===installation.installation_id && value.installation_epoch===installation.installation_epoch &&
      Object.values(value).every(item=>matches(id,item)), 'backup_request_key');
    return bytes(value);
  }

  function planRef(planId, hashValue) {
    return {...installation,plan_id:planId,revision:'1',digest:hashValue};
  }

  function readPlan(ref) {
    need(fields(ref,'digest,installation_epoch,installation_id,plan_id,revision') && matches(uuid,ref.plan_id) && matches(hash,ref.digest) &&
      canonical(ref)===canonical(planRef(ref.plan_id,ref.digest)), 'backup_plan_ref');
    const [row] = rows(db,'SELECT * FROM maintenance_backup_plan WHERE plan_id=?',ref.plan_id);
    need(row && row.digest===ref.digest, 'backup_plan_missing');
    return {plan_ref:planRef(row.plan_id,row.digest),plan:decode(row.body,row.digest)};
  }

  function current(operationId) {
    need(matches(uuid,operationId), 'backup_operation_id');
    const [row] = rows(db,`SELECT o.*,e.revision,e.phase,e.step,e.runtime_id,e.cancel_requested,e.detail,e.detail_digest,
        p.body AS plan_body,p.digest AS plan_digest
      FROM maintenance_backup_operation o JOIN maintenance_backup_current e USING(operation_id)
      JOIN maintenance_backup_plan p USING(plan_id) WHERE o.operation_id=?`,operationId);
    need(row, 'backup_operation_missing');
    const requestKey = JSON.parse(row.request_key.toString('utf8'));
    need(key(requestKey).equals(row.request_key),'backup_request_integrity');
    return {...row,plan:decode(row.plan_body,row.plan_digest),key:requestKey,detail:decode(row.detail,row.detail_digest)};
  }

  function view(row) {
    const [approval] = rows(db,`SELECT detail,detail_digest FROM maintenance_backup_event
      WHERE operation_id=? AND revision=2 AND phase='queued'`,row.operation_id);
    return {operation_id:row.operation_id,plan_ref:planRef(row.plan_id,row.plan_digest),revision:row.revision,
      phase:row.phase,step:row.step,cancel_requested:!!row.cancel_requested,reason_code:row.detail.reason??null,
      local_approval_ref:approval ? decode(approval.detail,approval.detail_digest).approval.approval_ref : null};
  }

  function event(operationId, revision, phase, step, runtimeId, cancelRequested, detail) {
    db.prepare('INSERT INTO maintenance_backup_event VALUES (?,?,?,?,?,?,?,?)')
      .run(operationId,revision,phase,step,runtimeId,Number(cancelRequested),bytes(detail),digest(detail));
  }

  function expect(operationId, revision) {
    const row = current(operationId);
    need(Number.isSafeInteger(revision) && revision===row.revision, 'backup_operation_revision');
    return row;
  }

  function authorized(authority, action, requestKey, plan, row = null, approval = null) {
    need(typeof authority==='function', 'backup_authority');
    const decision = authority({action,request_key:structuredClone(requestKey),plan:structuredClone(plan),
      operation:row ? view(row) : null,approval:approval ? structuredClone(approval) : null});
    need(decision?.allowed===true,'backup_not_authorized');
    need(decision.generation===plan.expected_generation,'backup_generation_conflict');
  }

  function snapshots(operationId) {
    return rows(db,`SELECT t.target_index,t.backup_operation_id,s.body,s.digest
      FROM maintenance_backup_target t LEFT JOIN maintenance_backup_snapshot s USING(backup_operation_id)
      WHERE operation_id=? ORDER BY target_index`,operationId);
  }

  function recover() {
    return transact(()=>{
      const interrupted = rows(db,`SELECT operation_id,revision,runtime_id,cancel_requested FROM maintenance_backup_current
        WHERE phase='running' AND step='snapshotting' AND runtime_id<>?`,runtime);
      for(const row of interrupted) event(row.operation_id,row.revision+1,'indeterminate','stopped',row.runtime_id,
        row.cancel_requested,{reason:'backup_helper_unconfirmed'});
    });
  }

  function finish(row, phase, step, reason = null) {
    event(row.operation_id,row.revision+1,phase,step,runtime,row.cancel_requested,reason ? {reason} : {});
    return view(current(row.operation_id));
  }

  async function collect(operationId, revision, {authorize,sourceDirectory} = {}) {
    need(typeof sourceDirectory==='function','backup_source_authority');
    const claimed = transact(()=>{
      const row = expect(operationId,revision);
      need(row.phase==='queued','backup_operation_phase');
      authorized(authorize,'begin',row.key,row.plan,row);
      need(!db.prepare(`SELECT 1 FROM maintenance_backup_current WHERE phase='indeterminate'
        OR (phase='running' AND step='snapshotting') LIMIT 1`).pluck().get(),'backup_helper_in_use');
      const targets = snapshots(operationId);
      need(targets.length===row.plan.target_service_scopes.length &&
        targets.every((target,index)=>target.target_index===index && target.body===null && matches(uuid,target.backup_operation_id)),
      'backup_target_integrity');
      event(operationId,revision+1,'running',targets.length ? 'snapshotting' : 'snapshots_staged',runtime,false,{});
      return {...row,targets};
    });
    if(!claimed.targets.length) return transact(()=>view(current(operationId)));
    active++;
    try {
      const targetRoot = path.join(staging,'backup-'+operationId);
      await fs.mkdir(targetRoot,{mode:0o700});
      for(const target of claimed.targets){
        const scope = claimed.plan.target_service_scopes[target.target_index];
        const folder = path.join(targetRoot,target.backup_operation_id);
        await fs.mkdir(folder,{mode:0o700});
        const source = sourceDirectory(structuredClone(scope));
        need(typeof source==='string' && path.isAbsolute(source),'backup_source_authority');
        const cancelled = transact(()=>{
          const row = current(operationId);
          if(row.cancel_requested) return finish(row,'cancelled','stopped','backup_cancelled');
          authorized(authorize,'snapshot',row.key,row.plan,row);
          return null;
        });
        if(cancelled) return cancelled;
        const result = await stageSQLiteSnapshot({sourceDirectory:source,stagingDirectory:folder,operationId:target.backup_operation_id,scope});
        const final = transact(()=>{
          const row = current(operationId);
          need(row.phase==='running' && row.step==='snapshotting' && row.runtime_id===runtime,'backup_operation_phase');
          if(row.cancel_requested) return finish(row,'cancelled','stopped','backup_cancelled');
          authorized(authorize,'adopt_snapshot',row.key,row.plan,row);
          const {path:output,...receipt} = result;
          need(output===path.join(folder,'snapshot.partial','data.sqlite') && receipt.state==='staged' &&
            receipt.backup_operation_id===target.backup_operation_id && canonical(receipt.scope)===canonical(scope) &&
            matches(rawHash,receipt.sha256) && Number.isSafeInteger(receipt.bytes) && receipt.bytes>0,'backup_target_receipt');
          db.prepare('INSERT INTO maintenance_backup_snapshot VALUES (?,?,?)')
            .run(target.backup_operation_id,bytes(receipt),digest(receipt));
          const last = target.target_index+1===claimed.targets.length;
          const next = finish(row,'running',last ? 'snapshots_staged' : 'snapshotting');
          return last ? next : null;
        });
        if(final) return final;
      }
    } catch(error) {
      if(error instanceof InstallationError && ['installation_storage_unknown','installation_unavailable','installation_directory_changed'].includes(error.code))
        throw error;
      return transact(()=>{
        const row = current(operationId);
        need(row.phase==='running' && row.runtime_id===runtime,'backup_operation_phase');
        return row.cancel_requested ? finish(row,'cancelled','stopped','backup_cancelled') :
          finish(row,'failed','stopped',error?.code==='backup_generation_conflict' ? error.code : 'backup_snapshot_failed');
      });
    } finally { active--; }
  }

  const api = Object.freeze({
    createPlan(value, authority){
      const plan = backupPlan(value);
      return transact(()=>{
        authorized(authority,'plan',null,plan);
        const planId = crypto.randomUUID(), hashValue = digest(plan);
        db.prepare('INSERT INTO maintenance_backup_plan VALUES (?,?,?)').run(planId,bytes(plan),hashValue);
        return planRef(planId,hashValue);
      });
    },
    getPlan(ref){return transact(()=>readPlan(ref));},
    request(input,authority){
      need(fields(input,'expected_generation,plan_ref,request_key'),'backup_request_invalid');
      const {request_key,plan_ref,expected_generation}=input;
      const requestKey = key(request_key);
      need(matches(counter,expected_generation),'backup_generation_conflict');
      const requestDigest = digest({method,path:route,body:{plan_ref,expected_generation}});
      return transact(()=>{
        const [prior] = rows(db,'SELECT operation_id,request_digest FROM maintenance_backup_operation WHERE request_key=?',requestKey);
        if(prior){
          need(prior.request_digest===requestDigest,'backup_request_conflict');
          return view(current(prior.operation_id));
        }
        const {plan} = readPlan(plan_ref);
        need(plan.expected_generation===expected_generation,'backup_generation_conflict');
        authorized(authority,'accept',request_key,plan);
        const operationId = crypto.randomUUID();
        db.prepare('INSERT INTO maintenance_backup_operation VALUES (?,?,?,?)')
          .run(operationId,plan_ref.plan_id,requestKey,requestDigest);
        const insert = db.prepare('INSERT INTO maintenance_backup_target VALUES (?,?,?)');
        plan.target_service_scopes.forEach((_,index)=>insert.run(operationId,index,crypto.randomUUID()));
        event(operationId,1,plan.consistency==='maintenance'||plan.backup_level==='L3' ? 'awaiting_local_approval' : 'queued',
          'pending',null,false,{});
        return view(current(operationId));
      });
    },
    lookup(requestKey){
      const encoded = key(requestKey);
      return transact(()=>{
        const found = db.prepare('SELECT operation_id FROM maintenance_backup_operation WHERE request_key=?').pluck().get(encoded);
        return found ? view(current(found)) : null;
      });
    },
    get(operationId){return transact(()=>view(current(operationId)));},
    approve(operationId,revision,approval,authority){
      need(fields(approval,'approval_ref,expected_generation,os_subject,plan_digest') &&
        matches(id,approval.approval_ref) && matches(id,approval.os_subject),'backup_approval_invalid');
      return transact(()=>{
        const row = expect(operationId,revision);
        need(row.phase==='awaiting_local_approval','backup_operation_phase');
        need(row.plan_digest===approval.plan_digest && row.plan.expected_generation===approval.expected_generation,'backup_approval_invalid');
        authorized(authority,'approve',row.key,row.plan,row,approval);
        event(operationId,revision+1,'queued','pending',null,false,{approval});
        return view(current(operationId));
      });
    },
    cancel(operationId,revision,authority){
      return transact(()=>{
        const row = expect(operationId,revision);
        authorized(authority,'cancel',row.key,row.plan,row);
        if(row.phase==='running' && row.step==='snapshotting'){
          need(row.runtime_id===runtime,'backup_operation_phase');
          if(!row.cancel_requested) event(operationId,revision+1,'running','snapshotting',runtime,true,{});
        }else{
          need(['queued','awaiting_local_approval'].includes(row.phase) ||
            row.phase==='running' && row.step==='snapshots_staged','backup_operation_phase');
          event(operationId,revision+1,'cancelled','stopped',null,true,{reason:'backup_cancelled'});
        }
        return view(current(operationId));
      });
    },
    collectSnapshots:collect,
    snapshots(operationId){
      return transact(()=>{
        const row = current(operationId);
        return snapshots(operationId).map(target=>({
          backup_operation_id:target.backup_operation_id, scope:row.plan.target_service_scopes[target.target_index],
          receipt:target.body===null ? null : decode(target.body,target.digest)
        }));
      });
    }
  });
  return {api,recover,get active(){return active;}};
}
