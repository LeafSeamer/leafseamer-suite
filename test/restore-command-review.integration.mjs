import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import Database from 'better-sqlite3';
import {canonical,digest} from '../dist/import-input.mjs';
import {reviewRestoredCommands} from '../dist/restore-command-review.mjs';

const controllerDist=process.env.LEAFSEAMER_TEST_BACKUP_CONTROLLER_DIST;
const ref=(kind,scope,object_id,body,revision='1')=>({kind,scope,object_id,revision,digest:digest(body)});

test('joins both submission families to adjudication and original terminal revision, keeping uneven cuts unresolved',{
  skip:!controllerDist
},async t=>{
  const protocol=await import(pathToFileURL(path.join(controllerDist,'peer-automation-command.mjs')).href);
  const receiver=new Database(':memory:'),sender=new Database(':memory:');
  t.after(()=>{sender.close();receiver.close();});
  const origin={authority_service_id:randomUUID(),database_instance_id:randomUUID()};
  const target={authority_service_id:randomUUID(),database_instance_id:randomUUID()};
  const principal={issuer_id:randomUUID(),issuer_epoch:randomUUID(),principal_id:randomUUID()};
  const family=['automation_execution','automation_recovery_dispatch'];
  for(const name of family){
    receiver.exec(`CREATE TABLE ${name}_submission (execution_id TEXT,step_id TEXT,idempotency_key TEXT,body_jcs TEXT,body_digest TEXT);
      CREATE TABLE ${name}_submission_attempt (execution_id TEXT,step_id TEXT,body_jcs TEXT,body_digest TEXT);
      CREATE TABLE ${name}_submission_adjudication (execution_id TEXT,step_id TEXT,body_jcs TEXT,body_digest TEXT);
      CREATE TABLE ${name}_command_terminal (execution_id TEXT,step_id TEXT,body_jcs TEXT,body_digest TEXT);`);
  }
  sender.exec(`CREATE TABLE automation_command_adjudication (
    origin_service_id TEXT,origin_database_instance_id TEXT,execution_id TEXT,step_id TEXT,idempotency_key TEXT,
    decision TEXT,command_id TEXT,request_digest TEXT,body_jcs TEXT,body_digest TEXT);
    CREATE TABLE command_admission_source(command_id TEXT PRIMARY KEY);`);
  const saved=new Map();
  const commandRecords={
    readCommandRecord:(_,id)=>saved.get(id),
    readCommandRevision(db,id,revision){
      assert.equal(db.inTransaction,true);
      assert.equal(saved.get(id).original.revision,revision);
      return {record:saved.get(id).original};
    },
    readCommandResource:(_,entry)=>({status:entry.resource})
  };
  function store({recovery=false,seamer=true,controller=true,seamerTerminal=true,unknown=false,rejected=false}={}){
    const execution=randomUUID(),step='step',key=randomUUID(),id=randomUUID(),name=family[Number(recovery)];
    const request={action:{preparation:{
      lookup:{controller_scope:target,origin_scope:origin,preparation_id:randomUUID(),request_digest:digest('preparation')},
      receipt_ref:ref('preparation_receipt',target,randomUUID(),'receipt'),
      grant_ref:ref('grant',target,randomUUID(),'grant')},
      execution_ref:ref('execution',origin,execution,'execution',recovery?'2':'1'),step_id:step,
      parameters_ref:ref('action_parameters',origin,step,'parameters')},
      target:{device_id:randomUUID(),action_id:'fixture.action',capability_version:'1.0.0'},idempotency_key:key};
    const identity=protocol.automationCommandIdentity(request,principal),decision=rejected?'rejected':'accepted';
    const command=rejected?null:{command_id:id,identity,target:request.target};
    const command_ref=rejected?null:ref('command',target,id,command);
    const commit={format:'leafseamer.automation-adjudication-commit/1',commit_id:randomUUID(),identity,decision,command_ref};
    const unsigned={contract_version:'command-admission/0.1.0-draft.1',adjudication_id:randomUUID(),revision:'1',identity,decision,
      command_ref,commit_ref:ref('controller_commit',target,commit.commit_id,commit)};
    const adjudication={...unsigned,adjudication_digest:digest(unsigned)};
    const evidence={id:'evidence',revision:'1',digest:digest('terminal evidence')},revision='2';
    const state={phase:'finished',command_id:id,revision,terminal_revision:revision,scope:target,
      outcome:unknown?'unknown':'succeeded',effect_status:unknown?'indeterminate':'verified',
      resource_status:unknown?'unresolved':'clear',automation_continuation:unknown?'blocked':'eligible',
      attempt_ids:[],reason_code:null,resolution_ref:null,resource_evidence_refs:[evidence],completion_evidence_refs:[evidence]};
    const state_ref={id:id+'_state_'+revision,revision,digest:digest(state)};
    const original={revision,state,state_ref,record_digest:digest('original terminal record'),
      completion:{achieved:unknown?null:'effect_verified'}};
    const terminal={format:'leafseamer.automation-command-terminal/1',command_ref,
      record_ref:{...command_ref,revision,digest:original.record_digest},state_ref,state,completion_achieved:original.completion.achieved};
    if(controller){
      const body={request,adjudication,command,commit};
      sender.prepare('INSERT INTO automation_command_adjudication VALUES(?,?,?,?,?,?,?,?,?,?)').run(
        origin.authority_service_id,origin.database_instance_id,execution,step,key,decision,rejected?null:id,
        identity.request_digest,canonical(body),digest(body));
      if(!rejected){
        sender.prepare('INSERT INTO command_admission_source VALUES(?)').run(id);
        saved.set(id,{record:{...original,revision:'3',origin:'automation',initial_command_ref:command_ref},adjudication,original,
          resource:unknown?'unresolved':'released'});
      }
    }
    if(seamer){
      const original={format:'leafseamer.action-submission/2',request,identity};
      receiver.prepare(`INSERT INTO ${name}_submission VALUES(?,?,?,?,?)`).run(execution,step,key,canonical(original),digest(original));
      function add(table,value){
        receiver.prepare(`INSERT INTO ${name}_${table} VALUES(?,?,?,?)`).run(execution,step,canonical(value),digest(value));
      }
      add('submission_attempt',{format:'leafseamer.action-submission-attempt/1',submission_digest:digest(original)});
      add('submission_adjudication',adjudication);
      if(seamerTerminal&&!rejected)add('command_terminal',terminal);
    }
    return {terminal,execution,step};
  }
  const matched=store();
  store({recovery:true,unknown:true});
  store({controller:false});
  store({seamer:false});
  store({seamerTerminal:false});
  store({rejected:true});
  function receipt(authority,scope,schema_revision){
    return {scope:{authority,service_id:scope.authority_service_id,database_instance_id:scope.database_instance_id,schema_revision},
      backup_operation_id:randomUUID(),sha256:'0'.repeat(64)};
  }
  const snapshots=[{db:sender,protocol,commandRecords,receipt:receipt('controller',target,'116')},
    {db:receiver,protocol,receipt:receipt('seamer',origin,'48')}];
  const review=reviewRestoredCommands(snapshots);
  assert.equal(review.state,'requires_review');
  assert.equal(review.checked,6);
  assert.equal(review.requires_review,4);
  assert.deepEqual(review.reasons,{controller_effect_unresolved:1,controller_original_missing:1,
    seamer_original_missing:1,seamer_terminal_missing:1});
  assert.deepEqual(reviewRestoredCommands(snapshots),review);
  assert.equal(reviewRestoredCommands([snapshots[1]]).reasons.controller_snapshot_missing,5);
  assert.equal(reviewRestoredCommands([snapshots[0]]).reasons.seamer_snapshot_missing,5);

  const changed={...matched.terminal,record_ref:{...matched.terminal.record_ref,digest:digest('different terminal record')}};
  receiver.prepare('UPDATE automation_execution_command_terminal SET body_jcs=?,body_digest=? WHERE execution_id=? AND step_id=?')
    .run(canonical(changed),digest(changed),matched.execution,matched.step);
  assert.throws(()=>reviewRestoredCommands(snapshots),{code:'restore_command_conflict'});
});
