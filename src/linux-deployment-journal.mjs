import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {InstallationError,canonical,digest,requireValue as need} from './import-input.mjs';
import {linuxContainerCgroup,openLinuxCgroupRetirement,readLinuxCgroupHost,readLinuxCgroupLeader} from './linux-cgroup-retirement.mjs';

const sql=fs.readFileSync(new URL('./linux-deployment-journal.sql',import.meta.url),'utf8');
const admissionSql=fs.readFileSync(new URL('./linux-deployment-admission.sql',import.meta.url),'utf8');
const currentSql=sql+'\n'+admissionSql;
const applicationId=0x4c53444c;
const schemaDigest='sha256:'+crypto.createHash('sha256').update(sql).digest('hex');
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$(?![\s\S])/;
const hash=/^sha256:[a-f0-9]{64}$(?![\s\S])/;
const roles=['controller','seamer'];
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const matches=(value,pattern)=>typeof value==='string'&&pattern.test(value);
const fileIdentity=file=>{
  const stat=fs.lstatSync(file,{bigint:true});
  need(stat.isFile()&&stat.nlink===1n,'linux_deployment_file');
  return stat.dev+':'+stat.ino;
};
function intent(value){
  need(fields(value,'compose_digest,controller,driver,generation_id,seamer')&&matches(value.compose_digest,hash),'linux_deployment_intent');
  for(const role of roles){
    const member=value[role];
    need(fields(member,'database_instance_id,service_id')&&Object.values(member).every(id=>matches(id,uuid)),'linux_deployment_intent');
    linuxContainerCgroup({driver:value.driver,generationId:value.generation_id,role});
  }
  need(value.controller.service_id!==value.seamer.service_id&&value.controller.database_instance_id!==value.seamer.database_instance_id,'linux_deployment_intent');
  return JSON.parse(canonical(value));
}
function ledgerIdentity(installation,filename){
  return {format:'leafseamer.linux-deployment-journal/1',host_installation_id:installation.host_installation_id,
    database_instance_id:installation.database_instance_id,installation_epoch:installation.installation_epoch,
    file_identity:fileIdentity(filename),schema_digest:schemaDigest};
}

export function linuxDeploymentJournal({root,installation,available,database,pragma,checkSchema,create,upgrade=false,runtime,onClose}){
  need(process.platform==='linux','linux_deployment_platform');
  const filename=path.join(root,'linux-deployment.db'),marker=path.join(root,'linux-deployment.marker');
  available();
  let db;
  try{
    if(create){
      need(!fs.existsSync(marker)&&!fs.existsSync(filename),'linux_deployment_initialized');
      fs.closeSync(fs.openSync(filename,'wx',0o600));
    }
    const identity=ledgerIdentity(installation,filename),identityText=canonical(identity);
    db=database(filename);
    if(create){
      need(pragma(db,'journal_mode=WAL')==='wal','linux_deployment_journal_mode');
      db.transaction(()=>{
        db.exec(currentSql);
        pragma(db,'application_id='+applicationId);
        pragma(db,'user_version=2');
        db.prepare('INSERT INTO linux_deployment_identity VALUES(1,?)').run(identityText);
      }).immediate();
      const fd=fs.openSync(marker,'wx',0o600);
      try{fs.writeFileSync(fd,identityText);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
      const directory=fs.openSync(root,'r');
      try{fs.fsyncSync(directory);}finally{fs.closeSync(directory);}
      db.close();
      return Object.freeze(identity);
    }
    const markerIdentity=fileIdentity(marker);
    need(fs.statSync(marker).size<=4096,'linux_deployment_identity');
    const version=pragma(db,'user_version');
    need(pragma(db,'application_id')===applicationId&&[1,2].includes(version)&&pragma(db,'journal_mode')==='wal'&&
      pragma(db,'quick_check')==='ok','linux_deployment_integrity');
    checkSchema(db,version===1?sql:currentSql);
    need(fs.readFileSync(marker).equals(Buffer.from(identityText))&&
      db.prepare('SELECT body FROM linux_deployment_identity WHERE singleton=1').pluck().get()===identityText,'linux_deployment_identity');
    db.exec('BEGIN EXCLUSIVE; COMMIT;');
    if(upgrade){
      if(version===1)db.transaction(()=>{
        need(pragma(db,'user_version')===1&&fileIdentity(filename)===identity.file_identity&&fileIdentity(marker)===markerIdentity,
          'linux_deployment_file');
        db.exec(admissionSql);
        pragma(db,'user_version=2');
        checkSchema(db,currentSql);
      }).exclusive();
      db.close();
      return Object.freeze({schema_revision:2,changed:version===1});
    }
    need(fields(runtime,'endpointClosure,launch')&&typeof runtime.launch==='function'&&typeof runtime.endpointClosure==='function','linux_deployment_runtime');
    const launch=runtime.launch,endpointClosure=runtime.endpointClosure;

    let closed=false,busy=false,poisoned=false,readers=null;
    function currentFile(){
      available();
      need(!closed&&!poisoned&&db.open,'linux_deployment_unavailable');
      try{need(fileIdentity(filename)===identity.file_identity&&fileIdentity(marker)===markerIdentity,'linux_deployment_file');}
      catch(error){poisoned=true;throw new InstallationError('linux_deployment_file',{cause:error});}
    }
    function operation(run){
      currentFile();need(!busy,'linux_deployment_busy');busy=true;
      try{return run();}finally{busy=false;}
    }
    function transaction(run){
      currentFile();
      try{return db.transaction(run).immediate();}
      catch(error){
        if(error instanceof InstallationError)throw error;
        poisoned=true;
        throw new InstallationError('linux_deployment_storage_unknown',{cause:error});
      }
    }
    function lookup(generationId){
      currentFile();
      const projection='SELECT generation_id,revision,phase,body,digest FROM linux_deployment_event ';
      const row=generationId===undefined?db.prepare(projection+'ORDER BY serial DESC LIMIT 1').raw().get():
        db.prepare(projection+'WHERE generation_id=? ORDER BY revision DESC LIMIT 1').raw().get(generationId);
      if(!row)return null;
      const [id,revision,phase,body,hashValue]=row,record=JSON.parse(body);
      need(canonical(record)===body&&digest(record)===hashValue&&record.intent.generation_id===id&&
        record.phase===phase&&record.revision===revision,'linux_deployment_integrity');
      return record;
    }
    function append(spec,revision,phase,detail){
      const record={intent:spec,revision,phase,detail};
      need(db.prepare('INSERT INTO linux_deployment_event(generation_id,revision,phase,body,digest) VALUES(?,?,?,?,?)')
        .run(spec.generation_id,revision,phase,canonical(record),digest(record)).changes===1,'linux_deployment_write');
      return record;
    }
    function unbind(){
      if(!readers)return;
      const prior=readers;readers=null;
      try{prior.controller?.close();}finally{prior.seamer?.close();}
    }
    function bind(spec,host,leaders,expected=null){
      const next={};
      try{
        for(const role of roles){
          next[role]=openLinuxCgroupRetirement({driver:spec.driver,generationId:spec.generation_id,role,host,leader:leaders[role]});
          need(expected===null||canonical(expected[role])===canonical(next[role].scope),'linux_deployment_observation_changed');
        }
      }catch(error){
        try{next.controller?.close();}finally{next.seamer?.close();}
        throw new InstallationError('linux_deployment_observation_lost',{cause:error});
      }
      readers=next;
      return Object.fromEntries(roles.map(role=>[role,next[role].scope]));
    }
    const active=(id,phase)=>{
      const prior=lookup();
      need(prior?.intent.generation_id===id&&prior.phase===phase,'linux_deployment_phase');
      return prior;
    };
    return Object.freeze({
      schemaRevision:version,
      current:()=>lookup(),
      lookup(id){need(matches(id,uuid),'linux_deployment_generation');return lookup(id);},
      admission(id,role){
        currentFile();need(version===2&&matches(id,uuid)&&roles.includes(role),'linux_deployment_admission');
        const row=db.prepare('SELECT body,digest FROM linux_deployment_admission WHERE generation_id=? AND role=?').raw().get(id,role);
        if(!row)return null;
        const value=JSON.parse(row[0]);
        need(canonical(value)===row[0]&&digest(value)===row[1],'linux_deployment_integrity');
        return value;
      },
      recordAdmission(id,role,value){return operation(()=>transaction(()=>{
        need(version===2&&roles.includes(role),'linux_deployment_admission');
        const prior=active(id,'running'),scope=prior.intent[role];
        need(value?.descriptor?.runtime_generation===id&&value.descriptor.authority_service_id===scope.service_id&&
          value.policy?.service_id===scope.service_id&&value.policy?.database_instance_id===scope.database_instance_id&&
          value.receipt?.gate_state==='closed'&&prior.detail.runtime_binding?.core_containment?.[role],
          'linux_deployment_admission');
        need(!db.prepare('SELECT 1 FROM linux_deployment_admission WHERE generation_id=? AND role=?').get(id,role),
          'linux_deployment_admission_used');
        const body=canonical(value);
        need(db.prepare('INSERT INTO linux_deployment_admission VALUES(?,?,?,?)').run(id,role,body,digest(value)).changes===1,
          'linux_deployment_write');
        return JSON.parse(body);
      }));},
      start(input){return operation(()=>{
        const spec=intent(input),host=readLinuxCgroupHost();
        transaction(()=>{
          const prior=lookup();
          need(!prior||prior.phase==='retired','linux_deployment_previous_open');
          need(!lookup(spec.generation_id),'linux_deployment_generation_used');
          append(spec,1,'launching',{host,predecessor:prior?.intent.generation_id??null});
        });
        try{
          const pids=launch(JSON.parse(canonical(spec)));
          need((fields(pids,'controller,seamer')||fields(pids,'controller,runtime_binding,seamer'))&&
            pids.controller!==pids.seamer,'linux_deployment_runtime');
          const leaders=Object.fromEntries(roles.map(role=>[role,readLinuxCgroupLeader(pids[role])]));
          const members=bind(spec,host,leaders);
          const detail={members,...(Object.hasOwn(pids,'runtime_binding')&&{runtime_binding:JSON.parse(canonical(pids.runtime_binding))})};
          return transaction(()=>append(active(spec.generation_id,'launching').intent,2,'running',detail));
        }catch(error){unbind();throw new InstallationError('linux_deployment_launch_unproven',{cause:error});}
      });},
      closeIntake(id){return operation(()=>transaction(()=>{
        const prior=lookup();
        need(prior?.intent.generation_id===id&&['running','closing'].includes(prior.phase),'linux_deployment_phase');
        return prior.phase==='closing'?prior:append(prior.intent,3,'closing',prior.detail);
      }));},
      observeRetirement(id){return operation(()=>{
        const result=transaction(()=>{
          const prior=active(id,'closing'),{members}=prior.detail;
          if(!readers){
            try{bind(prior.intent,members.controller.host,Object.fromEntries(roles.map(role=>[role,members[role].leader])),members);}
            catch{return append(prior.intent,4,'indeterminate',{...prior.detail,reason:'linux_deployment_observation_lost'});}
          }
          const observe=()=>roles.map(role=>readers[role].observe().result);
          const lost=()=>append(prior.intent,4,'indeterminate',{...prior.detail,reason:'linux_deployment_observation_lost'});
          const before=observe();
          if(before.includes('indeterminate'))return lost();
          if(before.includes('populated'))return prior;
          let endpointDigest;
          try{endpointDigest=endpointClosure(JSON.parse(canonical(prior)));}
          catch(error){throw new InstallationError('linux_deployment_endpoints_unavailable',{cause:error});}
          need(endpointDigest===null||matches(endpointDigest,hash),'linux_deployment_endpoints');
          if(endpointDigest===null)return prior;
          const after=observe();
          if(after.includes('indeterminate'))return lost();
          if(after.includes('populated'))return prior;
          return append(prior.intent,4,'retired',{...prior.detail,endpoint_evidence_digest:endpointDigest});
        });
        if(result.phase!=='closing')unbind();
        return result;
      });},
      close(){
        if(closed)return;
        need(!busy,'linux_deployment_busy');closed=true;
        try{unbind();}finally{try{db.close();}finally{onClose();}}
      }
    });
  }catch(error){
    if(db?.open)db.close();
    if(error instanceof InstallationError)throw error;
    throw new InstallationError(create?'linux_deployment_initialization_incomplete':'linux_deployment_unavailable',{cause:error});
  }
}
