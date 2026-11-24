import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createInstallationStore,openInstallationStore} from '../../dist/installation-store.mjs';
import {artifactFixture,digestValue,rawDigest,zipFixture} from './artifact-package.mjs';
import {authorizeFixture} from './release-authorization.mjs';

export async function sealLinuxWorker(t,{directory,serviceId,moduleBytes,protocol,sharedStore=null,profileId='worker.test.platform',customize=()=>{},
  apiVersions=['leafseamer-device-module/2']}){
  const data=path.join(directory,'installation');
  if(sharedStore===null){fs.mkdirSync(data,{mode:0o700});createInstallationStore(data);}
  const store=sharedStore??openInstallationStore(data);let authorization,closed=false;
  const close=()=>{if(!closed){authorization?.session.close();if(sharedStore===null)store.close();closed=true;}};
  t.after(close);
  const artifact=artifactFixture(),entry=artifact.payload.get('worker');
  entry.bytes=moduleBytes;
  Object.assign(artifact.inventory.files.find(file=>file.file_id==='worker'),{size_bytes:String(moduleBytes.length),digest:rawDigest(moduleBytes)});
  customize(artifact);
  Object.assign(artifact.manifest,{inventory_digest:digestValue(artifact.inventory),api_versions:apiVersions,ipc_versions:[protocol]});
  const bytes=zipFixture(artifact.entries()).bytes,manifestDigest=digestValue(artifact.manifest);
  authorization=await authorizeFixture(store,bytes,manifestDigest);
  const {result,validationPolicy}=authorization;
  const identity={host_installation_id:store.identity.host_installation_id,client_registration_id:'client.synthetic',import_request_id:'worker.synthetic'};
  store.recordAcceptedImport({identity,target_authority_service_id:serviceId,package_digest:result.body.package_digest,
    package_bytes:String(bytes.length),expected_manifest_digest:manifestDigest,host_trust_epoch:'1',source_attachment_id:'source.synthetic',
    release_authorization_ref:result.reference,validation_policy_ref:validationPolicy.reference});
  const source=path.join(data,'source.zip');fs.writeFileSync(source,bytes,{mode:0o600});
  const fd=fs.openSync(source,'r');
  try{await store.copyImport(identity,fd);}finally{fs.closeSync(fd);}
  assert.equal((await store.validateImport(identity)).state,'validating');
  const prepared=await store.prepareMaterialization(identity,{reader_sids:[],release_authorization_ref:result.reference});
  assert.equal(prepared.status,'prepared');
  const qualification=store.platformQualifications.configure(identity,{profile_id:profileId,approval_reference:'worker.test.approval',
    evidence_digest:digestValue('temporary integration filesystem'),scope_digest:store.platformQualifications.observe(identity).scope_digest});
  const sealed=await store.sealImport(identity,{platform_profile_ref:qualification.reference,release_authorization_ref:result.reference});
  assert.equal(sealed.state,'sealed');
  return {store,artifact,sealed:store.sealedArtifact(identity),close};
}

export async function sealSimulatorWorker(t,{dist,directory,serviceId,profileId,protocol,store}){
  const template=JSON.parse(fs.readFileSync(path.join(dist,'simulator-control-capability.json'),'utf8'));
  const bytes=Buffer.from(JSON.stringify(template));
  const sealed=await sealLinuxWorker(t,{directory,serviceId,profileId,protocol,sharedStore:store,
    moduleBytes:fs.readFileSync(path.join(dist,'simulator-control-module.mjs')),
    apiVersions:['leafseamer-device-event-capture/1','leafseamer-device-module/2','leafseamer-device-primitives/1'],customize({payload,manifest,inventory}){
      function add(fileId,file){
        payload.set(fileId,file);
        const entry={file_id:fileId,path:file.path,role:file.role,size_bytes:String(file.bytes.length),digest:rawDigest(file.bytes),executable:false};
        const prior=inventory.files.find(value=>value.file_id===fileId);
        if(prior)Object.assign(prior,entry);else inventory.files.unshift(entry);
      }
      add('config',{path:'config.txt',role:'schema',bytes:Buffer.from('{}')});
      add('policy',{...payload.get('policy'),bytes:fs.readFileSync(path.join(dist,'simulator-control-policy.json'))});
      add('capability',{path:'capability.json',role:'schema',bytes});
      manifest.capability_template_file_ids=['capability'];
      manifest.roles=[{role_id:'device',kind:'device',minimum:1,maximum:1,purpose:'设备绑定'}];
      manifest.permission_templates=[{request_id:'device.request',kind:'device_scope',purpose:'请求设备动作',
        scope:{device_role:'device',action_ids:template.actions.map(action=>action.action_id),trigger_ids:[]}}];
    }});
  const {host_installation_id,authority_service_id,database_instance_id}=store.identity;
  const {receipt,intake_ref}=sealed.sealed,{manifest,inventory}=sealed.artifact;
  return {close:sealed.close,materialization:{identity:{host_installation_id,authority_service_id,database_instance_id},
    content:{format:'leafseamer-intake-content/1',intake_ref,receipt,manifest,inventory}}};
}
