import crypto from 'node:crypto';
import {canonical,digest,requireValue} from './import-input.mjs';

const conflict='restore_command_conflict';
const need=value=>requireValue(value,conflict);
const same=(left,right)=>canonical(left)===canonical(right);
const scoped=({authority_service_id,database_instance_id})=>authority_service_id+':'+database_instance_id;
const scopeOf=({service_id,database_instance_id})=>({authority_service_id:service_id,database_instance_id});
const ref=(kind,scope,object_id,body)=>({kind,scope,object_id,revision:'1',digest:digest(body)});

function decode(text,hash){
  const value=JSON.parse(text);
  need(canonical(value)===text&&digest(value)===hash);
  return value;
}

function submissions({db,scope,revision,protocol}){
  const readers=[];
  for(const prefix of ['automation_execution','automation_recovery_dispatch']){
    const recovery=prefix==='automation_recovery_dispatch';
    if(revision<(recovery?45:29))continue;
    const terminals=revision>=30;
    const select=`SELECT s.execution_id,s.step_id,s.idempotency_key,s.body_jcs,s.body_digest,
        a.body_jcs,a.body_digest,d.body_jcs,d.body_digest,${terminals?'t.body_jcs,t.body_digest':'NULL,NULL'}
      FROM ${prefix}_submission s LEFT JOIN ${prefix}_submission_attempt a USING(execution_id,step_id)
      LEFT JOIN ${prefix}_submission_adjudication d USING(execution_id,step_id)
      ${terminals?`LEFT JOIN ${prefix}_command_terminal t USING(execution_id,step_id)`:''}`;
    readers.push({recovery,
      entries:db.prepare(select+' ORDER BY s.execution_id,s.step_id').raw(),
      lookup:db.prepare(select+' WHERE s.execution_id=? AND s.step_id=?').raw()});
  }
  function read(row,recovery){
    const [execution,step,key,text,bodyHash,attemptText,attemptHash,decisionText,decisionHash,terminalText,terminalHash]=row;
    const body=decode(text,bodyHash),{request,identity}=body;
    const {controller_scope:target,origin_scope:origin}=request.action.preparation.lookup;
    protocol.automationCommandRequest(request,target);
    need(['leafseamer.action-submission/1','leafseamer.action-submission/2'].includes(body.format)&&
      request.action.execution_ref.revision===(recovery?'2':'1')&&same(origin,scope)&&request.action.execution_ref.object_id===execution&&
      request.action.step_id===step&&request.idempotency_key===key&&
      same(identity,protocol.automationCommandIdentity(request,identity.key)));
    const attempt=attemptText===null?null:decode(attemptText,attemptHash);
    const adjudication=decisionText===null?null:protocol.automationCommandAdjudication(decode(decisionText,decisionHash),request);
    need(!adjudication||(attempt&&same(adjudication.identity,identity)));
    if(attempt)need(attempt.format==='leafseamer.action-submission-attempt/1'&&attempt.submission_digest===bodyHash);
    const terminal=terminalText===null?null:protocol.automationCommandTerminal(decode(terminalText,terminalHash),adjudication);
    return {execution,step,target,origin,request,identity,attempt,adjudication,terminal,
      source:recovery?'recovery':'ordinary',bodyHash,attemptHash,decisionHash,terminalHash};
  }
  return {
    *entries(){for(const reader of readers)for(const row of reader.entries.iterate())yield read(row,reader.recovery);},
    lookup(execution,step){
      const found=readers.flatMap(reader=>{
        const row=reader.lookup.get(execution,step);
        return row?[read(row,reader.recovery)]:[];
      });
      need(found.length<=1);
      return found[0];
    }
  };
}

function commands({db,scope,revision,protocol,commandRecords}){
  if(revision<95)return {entries:function*(){},lookup:()=>undefined};
  const select=`SELECT origin_service_id,origin_database_instance_id,execution_id,step_id,idempotency_key,
    decision,command_id,request_digest,body_jcs,body_digest FROM automation_command_adjudication`;
  const entries=db.prepare(select+` WHERE (origin_service_id,origin_database_instance_id,execution_id,step_id)>(?,?,?,?)
    ORDER BY origin_service_id,origin_database_instance_id,execution_id,step_id LIMIT 16`).raw();
  const lookup=db.prepare(select+` WHERE origin_service_id=? AND origin_database_instance_id=?
    AND ((execution_id=? AND step_id=?) OR idempotency_key=?)`).raw();
  const materialized=db.prepare('SELECT 1 FROM command_admission_source WHERE command_id=?').pluck();
  function read(row){
    const [originService,originDatabase,execution,step,key,decision,id,requestHash,text,bodyHash]=row;
    const {request,adjudication,command,commit}=decode(text,bodyHash);
    const origin={authority_service_id:originService,database_instance_id:originDatabase};
    protocol.automationCommandRequest(request,scope);
    protocol.automationCommandAdjudication(adjudication,request);
    const {identity}=adjudication,action=request.action;
    need(same(action.preparation.lookup.origin_scope,origin)&&action.execution_ref.object_id===execution&&
      action.step_id===step&&request.idempotency_key===key&&requestHash===identity.request_digest&&
      adjudication.decision===decision&&commit.format==='leafseamer.automation-adjudication-commit/1'&&
      same(commit.identity,identity)&&commit.decision===decision&&same(commit.command_ref,adjudication.command_ref)&&
      same(adjudication.commit_ref,ref('controller_commit',scope,commit.commit_id,commit)));
    if(decision==='rejected')need(id===null&&command===null);
    else need(id===command.command_id&&same(command.identity,identity)&&same(command.target,request.target)&&
      same(adjudication.command_ref,ref('command',scope,id,command)));
    return {origin,execution,step,request,adjudication,target:scope,bodyHash};
  }
  const outcome=adjudication=>db.transaction(()=>{
    const command=adjudication.command_ref;
    if(command===null||!materialized.get(command.object_id))return {terminal:null,unresolved:false};
    const saved=commandRecords.readCommandRecord(db,command.object_id),head=saved.record;
    need(head.origin==='automation'&&same(head.initial_command_ref,command)&&same(saved.adjudication,adjudication));
    const resource=commandRecords.readCommandResource(db,saved);
    if(head.state.phase!=='finished')return {terminal:null,unresolved:resource.status==='unresolved'};
    const revision=head.state.terminal_revision;
    const original=head.revision===revision?head:commandRecords.readCommandRevision(db,command.object_id,revision).record;
    const terminal=protocol.automationCommandTerminal({format:'leafseamer.automation-command-terminal/1',command_ref:command,
      record_ref:{...command,revision:original.revision,digest:original.record_digest},state_ref:original.state_ref,
      state:original.state,completion_achieved:original.completion.achieved},adjudication);
    return {terminal,unresolved:resource.status==='unresolved'||terminal.state.outcome==='unknown'};
  })();
  return {
    *entries(){
      let cursor=['','','',''];
      for(;;){
        const batch=entries.all(...cursor);
        if(!batch.length)return;
        for(const row of batch)yield read(row);
        cursor=batch.at(-1).slice(0,4);
      }
    },
    lookup(submission){
      const {origin,execution,step,request}=submission;
      const rows=lookup.all(origin.authority_service_id,origin.database_instance_id,execution,step,request.idempotency_key);
      need(rows.length<=1);
      return rows.length?read(rows[0]):undefined;
    },
    outcome
  };
}

export function reviewRestoredCommands(snapshots){
  const controllers=new Map(),seamers=new Map();
  for(const snapshot of snapshots){
    const {receipt}=snapshot,scope=scopeOf(receipt.scope);
    const reader={...snapshot,scope,revision:Number(receipt.scope.schema_revision)};
    const key=scoped(scope);
    const target=receipt.scope.authority==='controller'?controllers:seamers;
    need(!target.has(key));
    target.set(key,receipt.scope.authority==='controller'?commands(reader):submissions(reader));
  }
  const reasons={},review=crypto.createHash('sha256');
  for(const {receipt:{scope,sha256,backup_operation_id}} of snapshots)
    review.update(canonical({scope,sha256,backup_operation_id})+'\n');
  let checked=0,needsReview=0;
  function record(submission,command,terminal,issues){
    const {origin,target,execution,step}=submission??command;
    checked++;
    if(issues.length)needsReview++;
    for(const reason of issues)reasons[reason]=(reasons[reason]??0)+1;
    review.update(canonical({origin,target,execution,step,issues,
      submission:submission?[submission.source,submission.bodyHash,submission.attemptHash,submission.decisionHash,submission.terminalHash]:null,
      command:command?.bodyHash??null,terminal:terminal?.record_ref??null})+'\n');
  }
  for(const seamer of seamers.values())for(const submission of seamer.entries()){
    const controller=controllers.get(scoped(submission.target)),command=controller?.lookup(submission);
    if(!command){
      record(submission,null,null,[controller?'controller_original_missing':'controller_snapshot_missing']);
      continue;
    }
    const {request,identity,adjudication,terminal}=submission;
    need(same(command.request,request)&&same(command.adjudication.identity,identity)&&
      (!adjudication||same(command.adjudication,adjudication)));
    const current=controller.outcome(command.adjudication),issues=[];
    if(!submission.attempt)issues.push('seamer_attempt_missing');
    else if(!adjudication)issues.push('seamer_adjudication_missing');
    if(command.adjudication.decision==='accepted'){
      if(!current.terminal)issues.push('controller_terminal_missing');
      else if(!terminal)issues.push('seamer_terminal_missing');
      else need(same(current.terminal,terminal));
      if(current.unresolved)issues.push('controller_effect_unresolved');
    }
    record(submission,command,current.terminal,issues);
  }
  for(const controller of controllers.values())for(const command of controller.entries()){
    const seamer=seamers.get(scoped(command.origin)),submission=seamer?.lookup(command.execution,command.step);
    if(submission){
      need(same(submission.target,command.target)&&same(submission.request,command.request));
      continue;
    }
    const {terminal,unresolved}=controller.outcome(command.adjudication);
    const issues=[seamer?'seamer_original_missing':'seamer_snapshot_missing'];
    if(command.adjudication.decision==='accepted'&&!terminal)issues.push('controller_terminal_missing');
    if(unresolved)issues.push('controller_effect_unresolved');
    record(null,command,terminal,issues);
  }
  return {state:needsReview?'requires_review':'matched',checked,requires_review:needsReview,reasons,
    review_digest:'sha256:'+review.digest('hex')};
}
