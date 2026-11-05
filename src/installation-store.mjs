import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {promisify} from 'node:util';
import Database from 'better-sqlite3';
import {InstallationError, requireValue as need, canonical, digest, importIdentity, importRequest} from './import-input.mjs';
import {verifyArchive} from './archive-verifier.mjs';
import {trustMetadataStore} from './trust-metadata.mjs';
import {installationChannelPeer,installationChannelSource,initializeInstallationContentDirectory} from './local-peer.mjs';
import {validationPolicies} from './validation-policy.mjs';
import {prepareContent} from './content-preparation.mjs';
import {withPreparedContent} from './prepared-content.mjs';
import {platformQualifications} from './platform-qualification.mjs';
import {installationSealing} from './installation-sealing.mjs';
import {materializationProvider} from './materialization.mjs';
export {createReleaseTransport} from './release-transport.mjs';
export {InstallationError};

const read = promisify(fs.read);
const sql = ['installation.sql','trust-metadata.sql','installation-sealing.sql'].map(name=>fs.readFileSync(new URL('./'+name,import.meta.url),'utf8')).join('\n');
const schemaDigest = 'sha256:' + crypto.createHash('sha256').update(sql).digest('hex');
const engine = ['3.53.4', '2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc'];
const applicationId = 0x4c53494e;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const rows = (db, source, ...args) => {
  const statement = db.prepare(source), names = statement.columns().map(column => column.name);
  return statement.raw().all(...args).map(values => Object.fromEntries(names.map((name, i) => [name, values[i]])));
};
const pragma = (db, source) => {
  const statement = db.prepare('PRAGMA ' + source); return statement.reader ? statement.raw().get()?.[0] : statement.run();
};
const fileIdentity = filename => { const stat = fs.statSync(filename, {bigint: true}); return stat.dev + ':' + stat.ino; };
function readerPolicy(value){
  need(Array.isArray(value)&&value.length<=16&&new Set(value).size===value.length&&
    value.every(sid=>typeof sid==='string'&&/^S-1-[0-9]+(?:-[0-9]+){1,15}(?![\s\S])/.test(sid)&&sid.length<=184),'preparation_policy');
  return [...value];
}
function location(input) {
  need(typeof input === 'string' && path.isAbsolute(input), 'installation_absolute_directory');
  const root = path.resolve(input); const stat = fs.lstatSync(root);
  need(stat.isDirectory() && !stat.isSymbolicLink(), 'installation_directory');
  return {root: fs.realpathSync.native(root), directory_identity: fileIdentity(root)};
}
function database(filename) {
  const db = new Database(filename, {fileMustExist: true, timeout: 0});
  try {
    need(canonical(db.prepare('SELECT sqlite_version(),sqlite_source_id()').raw().get()) === canonical(engine), 'installation_engine');
    pragma(db, 'foreign_keys=ON'); pragma(db, 'recursive_triggers=ON'); pragma(db, 'trusted_schema=OFF');
    pragma(db, 'locking_mode=EXCLUSIVE'); pragma(db, 'wal_autocheckpoint=0'); pragma(db, 'synchronous=FULL');
    need(pragma(db, 'foreign_keys') === 1 && pragma(db, 'recursive_triggers') === 1 && pragma(db, 'trusted_schema') === 0 &&
      pragma(db, 'locking_mode') === 'exclusive' && pragma(db, 'synchronous') === 2 && pragma(db, 'wal_autocheckpoint') === 0, 'installation_connection');
    return db;
  } catch (error) { db.close(); throw error; }
}
function shape(db) { return db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").raw().all(); }
let expectedShape;
function schemaShape() {
  if (!expectedShape) {
    const db = new Database(':memory:');
    try { db.exec(sql); expectedShape = canonical(shape(db)); } finally { db.close(); }
  }
  return expectedShape;
}
function decode(body, hash) {
  const value = JSON.parse(body.toString('utf8'));
  need(Buffer.from(canonical(value)).equals(body) && digest(value) === hash, 'installation_record_integrity'); return value;
}
// 仅由可信首次安装入口调用。目录必须已由安装器保护且为空；缺库不能自动调用本函数。
export function createInstallationStore(dataDirectory) {
  const {root, directory_identity} = location(dataDirectory);
  need(fs.readdirSync(root).length === 0, 'installation_initialization_conflict');
  const filename = path.join(root, 'installation.db'); let db;
  try {
    const fd = fs.openSync(filename, 'wx', 0o600); fs.closeSync(fd);
    db = database(filename); need(pragma(db, 'journal_mode=WAL') === 'wal', 'installation_journal');
    const identity = {host_installation_id: crypto.randomUUID(), authority_service_id: crypto.randomUUID(),
      database_instance_id: crypto.randomUUID(), installation_epoch: crypto.randomUUID(), directory_identity, schema_digest: schemaDigest};
    db.transaction(() => {
      db.exec(sql); pragma(db, 'application_id=' + applicationId); pragma(db, 'user_version=1');
      db.prepare('INSERT INTO installation_identity VALUES (1,?,?,?,?,?,?)').run(...Object.values(identity));
    }).immediate();
    fs.mkdirSync(path.join(root, 'staging'), {mode: 0o700});
    fs.mkdirSync(path.join(root, 'content'), {mode: 0o700});
    if(process.platform==='win32')initializeInstallationContentDirectory(path.join(root,'content'));
    const marker = Buffer.from(canonical({format: 'leafseamer-installation-marker/1', ...identity, database_file_identity: fileIdentity(filename),content_directory_identity:fileIdentity(path.join(root,'content'))}));
    const markerFd = fs.openSync(path.join(root, 'installation.marker'), 'wx', 0o600);
    try { fs.writeFileSync(markerFd, marker); fs.fsyncSync(markerFd); } finally { fs.closeSync(markerFd); }
    return Object.freeze(identity);
  } catch (error) {
    if (error instanceof InstallationError) throw error;
    throw new InstallationError('installation_initialization_incomplete');
  } finally { db?.close(); }
}
export function openInstallationStore(dataDirectory) {
  const {root, directory_identity} = location(dataDirectory), filename = path.join(root, 'installation.db'); let db;
  try {
    for (const name of ['installation.db', 'installation.marker']) {
      const stat = fs.lstatSync(path.join(root, name)); need(stat.isFile() && !stat.isSymbolicLink() && stat.nlink === 1, 'installation_file_identity');
    }
    const staging = path.join(root, 'staging'), stagingStat = fs.lstatSync(staging);
    need(stagingStat.isDirectory() && !stagingStat.isSymbolicLink(), 'installation_staging');
    const stagingIdentity = fileIdentity(staging);
    const contentDirectory=path.join(root,'content'),contentStat=fs.lstatSync(contentDirectory);
    need(contentStat.isDirectory()&&!contentStat.isSymbolicLink(),'installation_content');const contentIdentity=fileIdentity(contentDirectory);
    const markerBytes = fs.readFileSync(path.join(root, 'installation.marker')); need(markerBytes.length <= 4096, 'installation_marker');
    const marker = JSON.parse(markerBytes.toString());
    need(Buffer.from(canonical(marker)).equals(markerBytes) && marker.format === 'leafseamer-installation-marker/1' &&
      marker.directory_identity === directory_identity && marker.database_file_identity === fileIdentity(filename)&&marker.content_directory_identity===contentIdentity, 'installation_marker');
    db = database(filename);
    need(pragma(db, 'application_id') === applicationId && pragma(db, 'user_version') === 1 && pragma(db, 'journal_mode') === 'wal', 'installation_schema');
    need(canonical(shape(db)) === schemaShape() && pragma(db, 'quick_check') === 'ok' && rows(db, 'PRAGMA foreign_key_check').length === 0, 'installation_integrity');
    const identities = rows(db, 'SELECT * FROM installation_identity');
    need(identities.length === 1, 'installation_identity');
    const {singleton, ...identity} = identities[0];
    need(singleton === 1 && identity.schema_digest === schemaDigest && identity.directory_identity === directory_identity &&
      ['host_installation_id', 'authority_service_id', 'database_instance_id', 'installation_epoch'].every(k => uuid.test(identity[k])) &&
      canonical(marker) === canonical({format: 'leafseamer-installation-marker/1', ...identity, database_file_identity: fileIdentity(filename),content_directory_identity:contentIdentity}), 'installation_identity');
    db.exec('BEGIN EXCLUSIVE; COMMIT;');
    let poisoned = false, closed = false; const activeCopies = new Set(), activeValidations = new Set(),activePreparations=new Set(), activeImports=new Map(), clientBindings = new Set();
    const available = () => {
      need(!closed && db.open && !poisoned, 'installation_unavailable');
      try {
        need(fileIdentity(root) === directory_identity && fileIdentity(staging) === stagingIdentity &&
          fileIdentity(filename) === marker.database_file_identity&&fileIdentity(contentDirectory)===contentIdentity, 'installation_directory_changed');
      } catch {
        poisoned = true; throw new InstallationError('installation_directory_changed');
      }
    };
    const transact = fn => {
      available(); need(!db.inTransaction, 'installation_outer_transaction');
      try { return db.transaction(fn).immediate(); }
      catch (error) {
        if (error instanceof InstallationError) throw error;
        poisoned = true; throw new InstallationError('installation_storage_unknown', {cause: error});
      }
    };
    function key(value) {
      const checked = importIdentity(value); need(checked.host_installation_id === identity.host_installation_id, 'import_wrong_host');
      return [checked.host_installation_id, checked.client_registration_id, checked.import_request_id];
    }
    function find(value) {
      const record = rows(db, `SELECT o.*,e.revision,e.state,e.reason_code,e.detail_body,e.detail_digest FROM import_operation o
        JOIN import_current c USING(operation_id) JOIN import_event e USING(operation_id,revision)
        WHERE host_installation_id=? AND client_registration_id=? AND import_request_id=?`, ...key(value))[0];
      if (!record) return null;
      const intent = decode(record.intent_body, record.intent_digest), detail = decode(record.detail_body, record.detail_digest);
      need(canonical(intent.identity) === canonical(importIdentity(value)) && intent.target_authority_service_id === record.target_authority_service_id, 'installation_record_integrity');
      return {...record, intent, detail};
    }
    const required = value => { const record = find(value); need(record, 'import_not_found'); return record; };
    function view(record) {
      return {identity: record.intent.identity, intent_digest: record.intent_digest, operation_id: record.operation_id,
        state: record.state, target_authority_service_id: record.target_authority_service_id,
        package_digest: record.intent.package_digest, receipt: record.state==='sealed'?sealing.receipt(record):null, reason_code: record.reason_code};
    }
    function event(operation, revision, state, reason, detail) {
      db.prepare('INSERT INTO import_event(operation_id,revision,event_id,state,reason_code,detail_body,detail_digest) VALUES (?,?,?,?,?,?,?)')
        .run(operation, revision, crypto.randomUUID(), state, reason, Buffer.from(canonical(detail)), digest(detail));
    }
    const trust = trustMetadataStore({db, transact, installationIdentity: identity, staging});
    const policies=validationPolicies({db,transact,identity,rows,decode});
    const qualifications=platformQualifications({db,transact,identity,rows,decode,verifyImplementation:policies.verifyImplementation,
      withPrepared(value,fn){
        const prepared=store.preparedArtifact(value),validated=store.validatedArtifact(value);
        return withPreparedContent(contentDirectory,prepared,validated,fn);
      }});
    const sealing=installationSealing({db,transact,identity,rows,decode,required,view,event,policies,trust,qualifications,contentDirectory,
      preparedArtifact:value=>store.preparedArtifact(value),validatedArtifact:value=>store.validatedArtifact(value),isUnavailable:()=>poisoned||closed});
    const materialization=materializationProvider({db,transact,identity,rows,decode,required,sealing,policies,trust,qualifications,contentDirectory,
      preparedArtifact:value=>store.preparedArtifact(value),validatedArtifact:value=>store.validatedArtifact(value),isUnavailable:()=>poisoned||closed});
    const clientId = value => typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(value);
    function clientPolicy(registrationId){
      const row=rows(db,'SELECT * FROM installation_client_registration WHERE client_registration_id=?',registrationId)[0];
      need(row&&!db.prepare('SELECT 1 FROM installation_client_revocation WHERE client_registration_id=?').pluck().get(registrationId),'import_peer_unauthorized');
      return decode(row.policy_body,row.policy_digest);
    }
    function cancelValue(value){
      const prior=required(value);if(['sealed','cancelled','rejected'].includes(prior.state))return view(prior);
      need(prior.state!=='indeterminate','import_indeterminate');
      event(prior.operation_id,prior.revision+1,'cancelled','operator_cancelled',{kind:'operator_cancelled'});return view(required(value));
    }
    function accept(request){
      const prior=find(request.intent.identity);
      if(prior){need(prior.intent_digest===request.digest,'import_identity_conflict');return view(prior);}
      sealing.assertEpoch(request.intent);
      trust.assertCurrentRelease(request.intent.release_authorization_ref,request.intent);
      policies.assertCurrent(request.intent.validation_policy_ref);
      need(db.prepare('SELECT count(*) FROM import_operation').pluck().get()<4096,'import_capacity');
      const active=rows(db,`SELECT o.client_registration_id FROM import_operation o JOIN import_current c USING(operation_id)
        JOIN import_event e USING(operation_id,revision) WHERE e.state NOT IN ('sealed','cancelled','rejected')`);
      need(active.length<2&&!active.some(row=>row.client_registration_id===request.intent.identity.client_registration_id),'import_capacity');
      const operation=crypto.randomUUID();
      db.prepare('INSERT INTO import_operation VALUES (?,?,?,?,?,?,?)').run(operation,...key(request.intent.identity),request.intent.target_authority_service_id,request.digest,Buffer.from(request.text));
      event(operation,1,'accepted',null,{kind:'import_accepted'});return view(required(request.intent.identity));
    }
    const store = {
      trust,
      validationPolicies:policies,
      platformQualifications:qualifications.api,
      trustEpoch:sealing.trustEpoch,advanceTrustEpoch:sealing.advanceTrustEpoch,
      sealImport:sealing.seal,sealedArtifact:sealing.sealedArtifact,
      queryIntake:value=>materialization.query(value),verifyMaterialization:value=>materialization.verify(value),materializationClock:materialization.descriptor,
      describeIntake:value=>materialization.describe(value),
      describeConfigurationSchema:value=>materialization.configurationSchema(value),
      describeCapabilityTemplates:value=>materialization.capabilityTemplates(value),
      acquireMaterialization:value=>materialization.acquire(value),
      identity: Object.freeze(identity),
      registerClient(policy){
        need(policy&&Object.keys(policy).sort().join(',')==='approval_reference,client_registration_id,permissions,role,target_authority_service_ids,user_sid'&&
          clientId(policy.client_registration_id)&&clientId(policy.approval_reference)&&['management_tool','authority','launch_coordinator'].includes(policy.role)&&typeof policy.user_sid==='string'&&
          /^S-1-[0-9]+(?:-[0-9]+){1,15}(?![\s\S])/.test(policy.user_sid)&&policy.user_sid.length<=184&&
          Array.isArray(policy.target_authority_service_ids)&&policy.target_authority_service_ids.length>0&&policy.target_authority_service_ids.length<=256&&
          policy.target_authority_service_ids.every(clientId)&&new Set(policy.target_authority_service_ids).size===policy.target_authority_service_ids.length&&
          Array.isArray(policy.permissions)&&policy.permissions.length>0&&policy.permissions.length<=3&&new Set(policy.permissions).size===policy.permissions.length&&
          policy.permissions.every(p=>({management_tool:['import.begin','import.query','import.cancel'],authority:['intake.query'],launch_coordinator:['intake.query','materialization.verify']})[policy.role].includes(p)),'import_client_policy');
        const body=Buffer.from(canonical(policy));need(body.length<=65536,'import_client_policy');
        return transact(()=>{
          const prior=rows(db,'SELECT * FROM installation_client_registration WHERE client_registration_id=?',policy.client_registration_id)[0];
          if(prior)need(prior.policy_digest===digest(policy),'import_client_conflict');
          else db.prepare('INSERT INTO installation_client_registration VALUES (?,?,?)').run(policy.client_registration_id,body,digest(policy));
          clientPolicy(policy.client_registration_id);return {client_registration_id:policy.client_registration_id,policy_digest:digest(policy)};
        });
      },
      revokeClient(registrationId,operationId){
        need(clientId(registrationId)&&clientId(operationId),'import_client_policy');
        const result=transact(()=>{
          need(db.prepare('SELECT 1 FROM installation_client_registration WHERE client_registration_id=?').pluck().get(registrationId),'import_peer_unauthorized');
          const prior=rows(db,'SELECT * FROM installation_client_revocation WHERE client_registration_id=?',registrationId)[0];
          if(!prior)db.prepare('INSERT INTO installation_client_revocation VALUES (?,?)').run(registrationId,operationId);
          return prior??{client_registration_id:registrationId,operation_id:operationId};
        });
        for(const binding of clientBindings)if(binding.registrationId===registrationId)binding.close();return result;
      },
      bindImportClient(channel,registrationId,{validationPolicyRef=null,readerSids=[],platformProfileRef=null}={}){
        need(clientId(registrationId),'import_client_policy');let released=false;const attachments=new Map();let attachmentCount=0;
        const selectedPolicy=validationPolicyRef===null?null:canonical(validationPolicyRef);
        const preparationReaders=readerPolicy(readerSids),selectedPlatform=platformProfileRef===null?null:canonical(platformProfileRef);
        const preparationKey=canonical({reader_sids:preparationReaders,platform_profile:selectedPlatform});
        const expected=installationChannelPeer(channel);
        function authority(permission){
          need(!released,'import_peer_unauthorized');const actual=installationChannelPeer(channel),policy=clientPolicy(registrationId);
          need(canonical(actual)===canonical(expected)&&actual.user_sid===policy.user_sid&&policy.permissions.includes(permission),'import_peer_unauthorized');
          return policy;
        }
        function authorize(permission,value){
          const policy=authority(permission);
          key(value);need(value.client_registration_id===registrationId,'import_peer_unauthorized');
          const record=find(value);need(record&&policy.target_authority_service_ids.includes(record.target_authority_service_id),'import_not_found_or_invisible');return record;
        }
        const authorizeMaterialization=permission=>request=>transact(()=>{
          const policy=authority(permission);need(policy.target_authority_service_ids.includes(request.target_authority_service_id),'import_not_found_or_invisible');
        });
        transact(()=>{const policy=clientPolicy(registrationId);need(expected.user_sid===policy.user_sid,'import_peer_unauthorized');});
        const binding={registrationId,close(){if(released)return;released=true;clientBindings.delete(binding);channel.close();for(const source of attachments.values())source.close();attachments.clear();}};clientBindings.add(binding);
        return Object.freeze({
          registerAttachment(handle){
            transact(()=>{authority('import.begin');need(attachments.size<8&&attachmentCount<4096,'import_capacity');});
            const source=installationChannelSource(channel,handle),attachmentId=crypto.randomUUID();attachments.set(attachmentId,source);++attachmentCount;return attachmentId;
          },
          beginImport(input){
            const request=importRequest(input);policies.verifyImplementation();let source,ongoing;
            const status=transact(()=>{
              const policy=authority('import.begin');key(request.intent.identity);
              need(request.intent.identity.client_registration_id===registrationId&&policy.target_authority_service_ids.includes(request.intent.target_authority_service_id),'import_peer_unauthorized');
              need(selectedPolicy!==null&&canonical(request.intent.validation_policy_ref)===selectedPolicy,'import_validation_policy');
              const prior=find(request.intent.identity);
              if(prior)need(prior.intent_digest===request.digest,'import_identity_conflict');
              ongoing=prior?activeImports.get(prior.operation_id):null;
              if(ongoing)need(ongoing.preparationKey===preparationKey,'preparation_identity_conflict');
              if(!ongoing&&(!prior||['accepted','copying'].includes(prior.state))){
                source=attachments.get(input.source_attachment_id);need(source,'import_source_attachment');
                need(!prior||!activeCopies.has(prior.operation_id),'import_copy_in_progress');
              }
              return accept(request);
            });
            if(ongoing)return {status,completion:ongoing.completion};
            if(!source&&!['validating','sealing'].includes(status.state))return {status,completion:Promise.resolve(status)};
            if(source)attachments.delete(input.source_attachment_id);
            const completion=(async()=>{
              try{
                let current=source?await store.copyImport(request.intent.identity,source.fd):status;
                if(current.state==='validating')current=await store.validateImport(request.intent.identity);
                if(current.state==='validating'){
                  const prepared=await store.prepareMaterialization(request.intent.identity,{
                    reader_sids:preparationReaders,release_authorization_ref:request.intent.release_authorization_ref});
                  if(prepared.status==='failed')throw new InstallationError(prepared.body.reason_code);
                }
                current=store.queryImport(request.intent.identity);
                if(selectedPlatform!==null&&['validating','sealing'].includes(current.state))return await store.sealImport(request.intent.identity,{
                  platform_profile_ref:JSON.parse(selectedPlatform),release_authorization_ref:request.intent.release_authorization_ref});
                return store.queryImport(request.intent.identity);
              }finally{try{source?.close();}finally{activeImports.delete(status.operation_id);}}
            })();
            activeImports.set(status.operation_id,{completion,preparationKey});completion.catch(()=>{});return {status,completion};
          },
          queryImport(value){return transact(()=>view(authorize('import.query',value)));},
          cancelImport(value){return transact(()=>{authorize('import.cancel',value);return cancelValue(value);});},
          queryIntake:value=>materialization.query(value,authorizeMaterialization('intake.query')),
          verifyMaterialization:value=>materialization.verify(value,authorizeMaterialization('materialization.verify')),close:binding.close});
      },
      // 本机agent核当前peer、目标管理权与策略后调用；本事务从同库当前发行原件核包绑定。
      // 发行签名不替代安装管理权、物化或运行批准。
      recordAcceptedImport(input) {
        const request = importRequest(input); key(request.intent.identity);
        policies.verifyImplementation();
        return transact(()=>accept(request));
      },
      queryImport(value) { return transact(() => { const record = find(value); return record ? view(record) : null; }); },
      cancelImport(value) { return transact(()=>cancelValue(value)); },
      async copyImport(value, sourceFd) {
        value = importIdentity(value);
        need(Number.isInteger(sourceFd) && sourceFd >= 0, 'import_source_descriptor'); key(value);
        const first = transact(() => {
          const prior = required(value);
          if (['validating', 'sealing', 'sealed', 'cancelled', 'rejected'].includes(prior.state)) return {original: view(prior)};
          need(['accepted', 'copying'].includes(prior.state), 'import_indeterminate');
          need(!activeCopies.has(prior.operation_id), 'import_copy_in_progress'); need(prior.revision < 1024, 'import_capacity');
          const revision = prior.revision + 1, spool = crypto.randomUUID();
          event(prior.operation_id, revision, 'copying', null, {kind: 'copy_started', spool_id: spool});
          db.prepare('INSERT INTO import_copy_attempt VALUES (?,?,?)').run(prior.operation_id, revision, spool);
          return {operation: prior.operation_id, revision, spool, intent: prior.intent};
        });
        if (first.original) return first.original;
        activeCopies.add(first.operation); let output, stage = 'source';
        const start = performance.now(); const limit = Number(first.intent.package_bytes), buffer = Buffer.alloc(65536);
        const isCurrent = () => transact(() => {
          const prior = required(value);
          return prior.state === 'copying' && prior.revision === first.revision ? null : view(prior);
        });
        const failure = reason => transact(() => {
          const prior = required(value);
          if (prior.state !== 'copying' || prior.revision !== first.revision) return view(prior);
          event(first.operation, first.revision + 1, reason === 'storage_unknown' ? 'indeterminate' : 'rejected', reason,
            {kind: 'copy_failed', spool_id: first.spool}); return view(required(value));
        });
        try {
          need(fs.fstatSync(sourceFd).isFile(), 'import_source_descriptor'); stage = 'storage';
          output = await fsp.open(path.join(staging, first.spool + '.zip'), 'wx', 0o600);
          const hash = crypto.createHash('sha256'); let offset = 0;
          for (;;) {
            const stopped = isCurrent(); if (stopped) return stopped;
            if (performance.now() - start >= 600000) return failure('capacity');
            stage = 'source'; const {bytesRead} = await read(sourceFd, buffer, 0, Math.min(buffer.length, limit + 1 - offset), offset);
            if (!bytesRead) break;
            if (offset + bytesRead > limit) return failure('content_mismatch');
            hash.update(buffer.subarray(0, bytesRead)); stage = 'storage';
            let written = 0;
            while (written < bytesRead) {
              const result = await output.write(buffer, written, bytesRead - written, offset + written);
              need(result.bytesWritten > 0, 'import_spool_write'); written += result.bytesWritten;
            }
            offset += bytesRead;
          }
          const actualDigest = 'sha256:' + hash.digest('hex');
          if (offset !== limit || actualDigest !== first.intent.package_digest) return failure('content_mismatch');
          stage = 'storage'; await output.sync(); await output.close(); output = undefined;
          if (performance.now() - start >= 600000) return failure('capacity');
          return transact(() => {
            const prior = required(value);
            if (prior.state !== 'copying' || prior.revision !== first.revision) return view(prior);
            event(first.operation, first.revision + 1, 'validating', null, {kind: 'copy_completed', spool_id: first.spool});
            db.prepare('INSERT INTO import_copy_receipt VALUES (?,?,?,?,?)').run(first.operation, first.revision, first.revision + 1, actualDigest, String(offset));
            return view(required(value));
          });
        } catch (error) {
          if (poisoned || closed) throw error;
          return failure(stage === 'source' ? 'source_unavailable' : 'storage_unknown');
        } finally {
          try { await output?.close(); } finally { activeCopies.delete(first.operation); }
        }
      },
      copiedArtifact(value) {
        return transact(() => {
          const current = required(value); need(current.state === 'validating', 'import_copy_unavailable');
          const copied = rows(db, `SELECT a.spool_id,r.package_digest,r.package_bytes FROM import_copy_attempt a JOIN import_copy_receipt r USING(operation_id,revision)
            WHERE a.operation_id=? AND r.result_revision=?`, current.operation_id, current.revision)[0];
          need(copied && uuid.test(copied.spool_id) && copied.package_digest === current.intent.package_digest && copied.package_bytes === current.intent.package_bytes,
            'installation_record_integrity');
          return Object.freeze({...copied, filename: path.join(staging, copied.spool_id + '.zip'), operation_id: current.operation_id});
        });
      },
      async validateImport(value) {
        value = importIdentity(value);
        const first = transact(() => {
          const prior = required(value);
          if (['cancelled', 'rejected', 'indeterminate'].includes(prior.state)) return {original: view(prior)};
          need(prior.state === 'validating', 'import_copy_unavailable'); need(!activeValidations.has(prior.operation_id), 'import_validation_in_progress');
          const existing = db.prepare('SELECT validation_id FROM import_validation_result WHERE operation_id=? AND copy_revision=?').pluck().get(prior.operation_id, prior.revision);
          if (existing) return {original: view(prior)};
          try{policies.assertCurrent(prior.intent.validation_policy_ref);}catch(error){
            if(!['import_validation_policy','import_validation_policy_revoked','validation_implementation'].includes(error.code))throw error;
            event(prior.operation_id,prior.revision+1,'rejected','trust_denied',{kind:'validation_policy_unavailable'});return {original:view(required(value))};
          }
          need(db.prepare('SELECT count(*) FROM import_validation_attempt WHERE operation_id=?').pluck().get(prior.operation_id) < 1024, 'import_capacity');
          const validation = crypto.randomUUID();
          db.prepare('INSERT INTO import_validation_attempt VALUES (?,?,?)').run(validation, prior.operation_id, prior.revision);
          const spool = db.prepare(`SELECT a.spool_id FROM import_copy_attempt a JOIN import_copy_receipt r USING(operation_id,revision)
            WHERE a.operation_id=? AND r.result_revision=?`).pluck().get(prior.operation_id, prior.revision);
          need(uuid.test(spool), 'installation_record_integrity');
          return {operation: prior.operation_id, revision: prior.revision, validation, spool, intent: prior.intent};
        });
        if (first.original) return first.original;
        activeValidations.add(first.operation);
        const checkCurrent = () => transact(() => {
          const prior = required(value); need(prior.state === 'validating' && prior.revision === first.revision, 'import_validation_obsolete');
        });
        try {
          policies.verifyImplementation();
          const report = await verifyArchive(path.join(staging, first.spool + '.zip'), first.intent, path.join(staging, first.validation + '.payload'), {checkCurrent});
          policies.verifyImplementation();
          return transact(() => {
            const prior = required(value);
            if (prior.state !== 'validating' || prior.revision !== first.revision) return view(prior);
            policies.assertCurrent(prior.intent.validation_policy_ref);
            db.prepare('INSERT INTO import_validation_result VALUES (?,?,?,?,?)').run(first.validation, first.operation, first.revision, Buffer.from(canonical(report)), digest(report));
            return view(prior);
          });
        } catch (error) {
          if (poisoned || closed) throw error;
          return transact(() => {
            const prior = required(value); if (prior.state !== 'validating' || prior.revision !== first.revision) return view(prior);
            const code = error?.code;
            const reason = ['import_validation_policy','import_validation_policy_revoked','validation_implementation'].includes(code)?'trust_denied':code === 'archive_storage_unknown' || !code ? 'storage_unknown' :
              ['archive_capacity', 'archive_timeout'].includes(code) ? 'capacity' :
              ['archive_package_size', 'archive_package_digest', 'archive_package_changed', 'archive_file_digest', 'archive_manifest_digest', 'archive_inventory_size'].includes(code) ? 'content_mismatch' : 'invalid_archive';
            event(first.operation, prior.revision + 1, reason === 'storage_unknown' ? 'indeterminate' : 'rejected', reason,
              {kind: 'archive_validation_failed', validation_id: first.validation}); return view(required(value));
          });
        } finally { activeValidations.delete(first.operation); }
      },
      validatedArtifact(value) {
        return transact(() => {
          const prior = required(value); need(['validating','sealing','sealed'].includes(prior.state), 'import_validation_unavailable');
          const result = rows(db, 'SELECT * FROM import_validation_result WHERE operation_id=? AND copy_revision<=? ORDER BY copy_revision DESC LIMIT 1', prior.operation_id, prior.revision)[0];
          need(result && uuid.test(result.validation_id), 'import_validation_unavailable');
          const report = decode(result.report_body, result.report_digest);
          need(report.format === 'leafseamer-archive-validation/1' && report.package_digest === prior.intent.package_digest && report.package_bytes === prior.intent.package_bytes &&
            report.manifest_digest === prior.intent.expected_manifest_digest && digest(report.manifest) === report.manifest_digest &&
            digest(report.inventory) === report.artifact_set_digest, 'installation_record_integrity');
          return {validation_id: result.validation_id, report_digest: result.report_digest, report, payload_directory: path.join(staging, result.validation_id + '.payload')};
        });
      },
      async prepareMaterialization(value,options){
        value=importIdentity(value);
        need(options&&Object.keys(options).sort().join(',')==='reader_sids,release_authorization_ref','preparation_policy');readerPolicy(options.reader_sids);
        const policy=JSON.parse(canonical(options));policies.verifyImplementation();
        const validated=store.validatedArtifact(value);
        const first=transact(()=>{
          const prior=required(value);need(prior.state==='validating'&&!activePreparations.has(prior.operation_id),'preparation_state');
          policies.assertCurrent(prior.intent.validation_policy_ref);trust.assertCurrentRelease(policy.release_authorization_ref,prior.intent);
          const original=rows(db,`SELECT r.* FROM import_preparation_result r JOIN import_preparation_attempt a USING(preparation_id)
            WHERE a.operation_id=? AND a.copy_revision=? AND r.status='prepared'`,prior.operation_id,prior.revision)[0];
          if(original){const body=decode(original.body,original.body_digest);need(canonical(body.reader_sids)===canonical(policy.reader_sids),'preparation_identity_conflict');return {original:{preparation_id:original.preparation_id,status:original.status,body}};}
          need(db.prepare('SELECT count(*) FROM import_preparation_attempt WHERE operation_id=?').pluck().get(prior.operation_id)<16,'preparation_capacity');
          const preparation=crypto.randomUUID();db.prepare('INSERT INTO import_preparation_attempt VALUES (?,?,?,?,?,?)').run(preparation,prior.operation_id,prior.revision,validated.validation_id,Buffer.from(canonical(policy)),digest(policy));
          return {preparation,operation:prior.operation_id,revision:prior.revision,intent:prior.intent};
        });
        if(first.original)return first.original;activePreparations.add(first.operation);
        const checkCurrent=()=>transact(()=>{
          const current=required(value);need(current.state==='validating'&&current.revision===first.revision,'preparation_obsolete');
          policies.assertCurrent(current.intent.validation_policy_ref);trust.assertCurrentRelease(policy.release_authorization_ref,current.intent);
        });
        const save=(status,body)=>{db.prepare('INSERT INTO import_preparation_result VALUES (?,?,?,?)').run(first.preparation,status,Buffer.from(canonical(body)),digest(body));return {preparation_id:first.preparation,status,body};};
        try{
          const report=await prepareContent({source_directory:validated.payload_directory,parent_directory:contentDirectory,directory_id:first.preparation,
            inventory:validated.report.inventory,reader_sids:policy.reader_sids},{checkCurrent});
          policies.verifyImplementation();
          return transact(()=>{
            const prior=required(value);if(prior.state!=='validating'||prior.revision!==first.revision)return save('obsolete',{reason_code:'preparation_obsolete'});
            policies.assertCurrent(prior.intent.validation_policy_ref);trust.assertCurrentRelease(policy.release_authorization_ref,prior.intent);
            need(report.format==='leafseamer-content-preparation/1'&&report.content_directory===first.preparation&&report.sealed===false&&
              report.directory_durability==='unqualified'&&report.file_flush_completed===true&&report.file_count===validated.report.file_count&&
              report.payload_bytes===validated.report.payload_bytes,'preparation_report');
            need(report.storage_identity?.format==='windows-content-volume/1'&&report.storage_identity.file_id_volume_serial===report.root_identity.slice(0,16),'preparation_report');
            const directories=new Set();for(const file of validated.report.inventory.files){const parts=file.path.split('/');for(let i=1;i<parts.length;i++)directories.add(parts.slice(0,i).join('/'));}
            const flushed=report.metadata_flush;
            need(flushed?.format==='windows-content-flush/1'&&flushed.method==='FlushFileBuffers'&&flushed.completed===true&&
              flushed.file_count===validated.report.file_count&&flushed.directory_count===directories.size+1&&
              flushed.order==='files_then_directories_bottom_up_then_parent'&&/^[0-9a-f]{48}$/.test(flushed.parent_identity)&&
              flushed.parent_identity.slice(0,16)===report.root_identity.slice(0,16),'preparation_report');
            return save('prepared',{...report,validation_id:validated.validation_id,validation_report_digest:validated.report_digest,
              package_digest:first.intent.package_digest,manifest_digest:validated.report.manifest_digest,artifact_set_digest:validated.report.artifact_set_digest,
              release_authorization_ref:policy.release_authorization_ref,validation_policy_ref:first.intent.validation_policy_ref});
          });
        }catch(error){
          if(poisoned||closed)throw error;
          return transact(()=>{const prior=required(value),obsolete=prior.state!=='validating'||prior.revision!==first.revision;
            return save(obsolete?'obsolete':'failed',{reason_code:obsolete?'preparation_obsolete':typeof error.code==='string'&&/^[a-z_]{1,96}$/.test(error.code)?error.code:'preparation_unavailable'});});
        }finally{activePreparations.delete(first.operation);}
      },
      preparedArtifact(value){
        return transact(()=>{
          const current=required(value),row=rows(db,`SELECT r.* FROM import_preparation_result r JOIN import_preparation_attempt a USING(preparation_id)
            WHERE a.operation_id=? AND r.status='prepared' ORDER BY a.rowid DESC LIMIT 1`,current.operation_id)[0];
          need(row&&uuid.test(row.preparation_id),'preparation_unavailable');const body=decode(row.body,row.body_digest);
          need(body.content_directory===row.preparation_id&&body.package_digest===current.intent.package_digest&&body.sealed===false,'installation_record_integrity');
          return {preparation_id:row.preparation_id,body,content_directory:path.join(contentDirectory,row.preparation_id)};
        });
      },
      close() { need(activeCopies.size === 0 && activeValidations.size === 0&&activePreparations.size===0&&sealing.activeCount===0&&materialization.activeCount===0&&activeImports.size===0 && trust.activeCount === 0 && clientBindings.size===0, 'import_copy_in_progress'); if (!closed) { closed = true; db.close(); } }
    };
    return Object.freeze(store);
  } catch (error) {
    db?.close(); if (error instanceof InstallationError) throw error;
    throw new InstallationError(error.code === 'SQLITE_BUSY' ? 'installation_in_use' : 'installation_unavailable');
  }
}
