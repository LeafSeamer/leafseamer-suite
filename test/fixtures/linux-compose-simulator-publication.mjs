import assert from 'node:assert/strict';
import crypto from 'node:crypto';

const id=()=>crypto.randomUUID();
const condition={kind:'literal',value:true};
const eventRoute='/auth/local-event-bindings/v1';
export const runApprovalRoute='/auth/local-run-approvals/v1';
export function composeSimulatorDeviceScope(controller,{device,target_device}){
  return {format:'leafseamer.device-binding-scope/1',authority_service_id:controller.service_id,
    database_instance_id:controller.database_instance_id,device_ids:target_device?[device,target_device].sort():[device]};
}

export async function publishComposeSimulatorDefinition({serviceId,controller,baseline,bindingId,policyRef,selection,
  bearer,send,localRequest,canonical,digest}){
  const base='/services/'+serviceId+'/api/v1';
  async function request(method,target,body,expected,csrf){
    const response=await send(base+target,{method,headers:{Authorization:bearer,
      ...(body&&{'Content-Type':'application/json'}),...(csrf&&{'X-CSRF-Token':csrf})},body:body&&canonical(body)});
    assert.equal(response.status,expected,method+' '+target+' '+response.body.toString());
    return {body:JSON.parse(response.body),csrf:response.headers['x-csrf-token']};
  }
  async function context(operations){
    const response=await request('POST','/request-contexts',{audience:serviceId,selection,operations,ttl_ms:30000,max_unique_requests:2},201);
    return {context_id:response.body.data.context_id,csrf:response.csrf};
  }
  const use=({context_id})=>({context_id,idempotency_key:id()});
  async function event(operation,input){
    const response=await localRequest(eventRoute,operation,input,bearer);
    assert.equal(response.status,200,operation+' '+response.data);
    return JSON.parse(response.data).result;
  }

  const create=await context(['createDefinition','updateDraft']);
  const draftContent={policy_ref:policyRef,selections:[],program:{kind:'rule',condition,trigger_binding_id:'pending-input',
    groups:[{mode:'sequence',steps:[{step_id:'wait',depends_on:[],required:true,failure_policy:'stop',kind:'delay',delay_ms:0,max_lateness_ms:100}]}]}};
  const {body:initial}=await request('POST','/definitions',{context:use(create),content:draftContent,
    metadata:{name:'模拟器事件规则',description:'',layout:{}}},201);
  const definition_id=initial.definition_id,target='/definitions/'+definition_id;
  const query={binding_id:bindingId,scope:composeSimulatorDeviceScope(controller,baseline),device_id:baseline.device,expected_registration_ref:null};
  const source={...query,expected_source_ref:baseline.source_ref};
  const candidate=await event('candidate',{definition_id,query:source});
  assert.deepEqual(candidate.source_ref,baseline.source_ref);
  assert.deepEqual(candidate.source_key,baseline.baseline.origin.source_key);
  const eventContext=await event('create-context',{ttl_ms:30000,max_unique_requests:1});
  const eventApproval=await event('approve',{query:source,context_id:eventContext.context_id,
    approval:{request_id:id(),approval_id:id(),definition_id,expected_candidate_digest:candidate.candidate_digest}});
  assert.equal(eventApproval.state,'approved');
  assert.deepEqual(eventApproval.candidate,candidate);
  const targetDevice=baseline.target_device??baseline.device;
  const deviceQuery={...query,device_id:targetDevice,expected_registration_ref:baseline.target_device?null:candidate.device_registration_ref};
  const {body:deviceCandidate}=await request('POST',target+'/binding-candidates/query',deviceQuery,200);
  const deviceContext=await context(['approveDefinitionBindings']);
  const {body:deviceApproval}=await request('POST',target+'/binding-approvals',{context:{context_id:deviceContext.context_id},
    request_id:id(),approval_id:id(),source:{...deviceQuery,expected_registration_ref:deviceCandidate.bundle.registration_ref},
    expected_bundle_digest:deviceCandidate.bundle_digest},201,deviceContext.csrf);
  assert.equal(deviceApproval.state,'approved');
  const action=deviceApproval.bundle.bindings.find(binding=>binding.kind==='action');
  assert.equal(action.value.device_id,targetDevice);
  const input=candidate.binding;
  const program={kind:'rule',trigger_binding_id:input.binding_id,condition,groups:[{mode:'sequence',steps:[{
    kind:'action',step_id:'set-simulator',depends_on:[],required:true,failure_policy:'stop',action_binding_id:action.binding_id,
    parameters:{value:31},parameter_bindings:[],guard:condition}]}]};
  const selections=[input,action].map(({kind,binding_id,content_ref})=>({kind,binding_id,content_ref}));
  const {body:draft}=await request('PUT',target+'/draft',{context:use(create),expected_draft_revision:initial.revision,
    content:{program,selections,policy_ref:policyRef}},200);
  const publication=await context(['publishDefinition']);
  const publishBody={context:use(publication),expected_draft_revision:draft.revision,expected_content_digest:draft.content_digest,
    expected_selection_digest:draft.selection_digest};
  await request('POST',target+'/publish',publishBody,403);
  const {body:published}=await request('POST',target+'/publish',publishBody,201,publication.csrf);
  assert.deepEqual((await request('POST',target+'/publish',publishBody,201,publication.csrf)).body,published);
  const version=target+'/versions/'+published.definition_version;
  const {body:compiled}=await request('GET',version+'/program',null,200);
  const {body:artifact}=await request('GET',version+'/artifact',null,200);
  assert.deepEqual(compiled.input_bindings,[input.value]);
  assert.deepEqual(compiled.action_bindings,[action.value]);
  assert.deepEqual(compiled.program,program);
  assert.equal(digest(compiled),published.program_digest);
  assert.equal(artifact.manifest_digest,published.artifact_ref.digest);
  const runContext=await context(['createRun']);
  const {body:run}=await request('POST','/runs',{context:use(runContext),definition_id,definition_version:published.definition_version,
    expected_artifact_ref:published.artifact_ref},201,runContext.csrf);
  assert.equal(run.lifecycle,'disarmed');
  assert.equal(run.dispatch_eligible,false);
  assert.equal(run.last_receive_seq,'0');
  assert.deepEqual((await request('GET','/runs/'+run.run_id,null,200)).body,run);
  return {published,compiled,artifact,run,policyRef,
    approvals:[{binding_id:input.binding_id,kind:'event',approval_ref:eventApproval.approval_ref},
      {binding_id:action.binding_id,kind:'device',approval_ref:deviceApproval.approval_ref}]};
}

export function verifyDurableSimulatorPublication(store,{published,compiled,artifact,run,policyRef,approvals},digest){
  const {definition_id,definition_version}=published;
  const row=store.prepare('SELECT bundle_jcs,bundle_digest FROM definition_publication WHERE definition_id=? AND definition_version=?')
    .get(definition_id,definition_version);
  const original=JSON.parse(row.bundle_jcs);
  assert.equal(digest(original),row.bundle_digest);
  assert.deepEqual(original.result,published);
  assert.deepEqual(original.program,compiled);
  assert.deepEqual(original.artifact,artifact);
  assert.deepEqual(original.snapshot.review.policy_ref,policyRef);
  assert.deepEqual(original.snapshot.review.binding_approval_refs,approvals);
  assert.equal(original.publisher.authorization.actor.principal_kind,'human');
  assert.equal(store.prepare('SELECT count(*) AS n FROM definition_publication WHERE definition_id=?').get(definition_id).n,1);
  const saved=store.prepare('SELECT body_jcs FROM automation_run_creation WHERE run_id=?').get(run.run_id);
  const {last_receive_cursor,ingest_revision,dependency_digest,...state}=JSON.parse(saved.body_jcs).run;
  assert.deepEqual({...state,last_receive_seq:last_receive_cursor.receive_sequence},run);
}

export async function approveComposeSimulatorRun({run,baseline,controller,principalId,bindingId,pairing,admin,localRequest,issueBearer}){
  const run_id=run.run_id,context={ttl_ms:30000,max_unique_requests:1};
  const targetDevice=baseline.target_device??baseline.device;
  const approver=await issueBearer(['run.approve','run.read','request.create']);
  const reader=await issueBearer(['run.read','request.create']);
  async function operation(name,request,granted=true,expected=200){
    const result=await localRequest(runApprovalRoute,name,request,granted?approver:reader);
    assert.equal(result.status,expected,name+' '+result.data);
    return JSON.parse(result.data).result;
  }
  assert.equal(await operation('inspect',{run_id}),null);
  await operation('inspect-arm-prerequisites',{run_id,expected_revision:run.revision},true,409);
  await operation('create-proposal-context',context,false,403);
  const {targets:[target]}=await operation('targets',{run_id});
  assert.deepEqual(target.controller_scope,{authority_service_id:controller.service_id,database_instance_id:controller.database_instance_id});
  assert.equal(target.device_actions.length,1);
  assert.equal(target.device_actions[0].device_id,targetDevice);
  const principal=await admin('create-automation-principal',{request_id:id(),display_name:'Compose simulator automation'});
  assert.equal(principal.purpose,'automation');
  assert.equal(principal.state,'disabled');
  const service_principal={issuer_id:principal.issuer_id,issuer_epoch:principal.issuer_epoch,principal_id:principal.id};
  const {not_before_ns,expires_ns}=pairing,interval={not_before_ns,expires_ns};
  const pairing_ref={id:pairing.binding_id,revision:pairing.revision,digest:pairing.digest};
  const device_scope=composeSimulatorDeviceScope(controller,baseline);
  const {principal:approved}=await admin('approve-automation-principal',{request_id:id(),principal_id:principal.id,
    expected_revision:principal.revision,audiences:[controller.service_id],permissions:['automation.prepare'],
    device_ids:[targetDevice],...interval,automation_origin:{seamer_scope:run.scope,pairing_ref,device_scope}});
  const human={issuer_id:principal.issuer_id,issuer_epoch:principal.issuer_epoch,principal_id:principalId};
  const policy=await admin('replace-run-endorsement-policy',{request_id:id(),expected_policy_ref:null,
    human,service_principal,service_approval_ref:approved.approval_ref,device_actions:target.device_actions,parameter_constraints:[],...interval});
  const {context_id}=await operation('create-proposal-context',context);
  const proposalRequest={run_id,proposal:{context:{context_id,idempotency_key:id()},artifact_ref:run.artifact_ref,expected_run_revision:run.revision,
    service_principal,source:{binding_id:bindingId,approval_ref:approved.approval_ref},validity:{
      not_before:new Date(Number((BigInt(not_before_ns)+999999n)/1000000n)).toISOString(),
      not_after:new Date(Number(BigInt(expires_ns)/1000000n)-1000).toISOString()},controller_constraints:[]}};
  const {proposal_ref}=await operation('propose',proposalRequest);
  const endorsementRequest={binding_id:pairing.binding_id,proposal_ref,idempotency_key:id()};
  const {endorsement_ref}=await admin('endorse-run',endorsementRequest);
  assert.deepEqual((await admin('endorse-run',endorsementRequest)).endorsement_ref,endorsement_ref);
  const approvalContext=await operation('create-approval-context',context);
  const approvalRequest={context:{context_id:approvalContext.context_id,idempotency_key:id()},controller_endorsement_refs:[endorsement_ref],
    expected_prior_approval_ref:null,expected_run_revision:run.revision,proposal_ref};
  await operation('approve',{run_id,approval:{...approvalRequest,controller_endorsement_refs:[]}},true,422);
  assert.equal(await operation('inspect',{run_id}),null);
  const {approval_ref}=await operation('approve',{run_id,approval:approvalRequest});
  const current=await operation('inspect',{run_id});
  assert.equal(current.state,'active');
  assert.deepEqual(current.object_ref,approval_ref);
  assert.deepEqual(current.approval.approved_by,human);
  async function observePreflight(sourceState){
    const preflight=await operation('inspect-arm-prerequisites',{run_id,expected_revision:'2'});
    assert.deepEqual(preflight.approval_ref,approval_ref);
    assert.deepEqual(preflight.targets,[target]);
    assert.deepEqual(preflight.sources.map(source=>[source.state,source.transport?.state]),[[sourceState,'ready']]);
    const [control]=preflight.control_observations;
    assert.deepEqual(control.endorsement_ref,endorsement_ref);
    assert.equal(control.devices.length,1);
    assert.equal(control.devices[0].device_id,targetDevice);
    assert.equal(control.devices[0].state,baseline.target_device?'automatic':'manual');
    if(baseline.target_device)assert.equal(control.devices[0].control.gate_state,'protected');
    assert.equal(preflight.can_arm,false);
    return preflight;
  }
  await observePreflight('baseline_required');
  return {proposal_ref,endorsement_ref,approval_ref,proposalRequest,policy,observePreflight};
}

export function verifyDurableSimulatorRunApproval(receiver,publisher,{proposal_ref,endorsement_ref,approval_ref,policy,preflight},digest,
  expectedRunRevision=preflight.run_revision){
  function verify(db,query,reference){
    const {body_jcs,body_digest}=db.prepare(query).get(reference.object_id);
    const body=JSON.parse(body_jcs);
    assert.equal(digest(body),body_digest);
    assert.equal(body_digest,reference.digest);
    return body;
  }
  const proposal=verify(receiver,'SELECT body_jcs,body_digest FROM automation_run_approval_proposal WHERE proposal_id=?',proposal_ref);
  const endorsement=verify(publisher,'SELECT body_jcs,body_digest FROM run_approval_endorsement WHERE endorsement_id=?',endorsement_ref);
  const approved=verify(receiver,'SELECT body_jcs,body_digest FROM automation_run_approval WHERE approval_id=?',approval_ref);
  assert.equal(proposal.run_id,approved.run_id);
  assert.deepEqual(endorsement.proposal_ref,proposal_ref);
  assert.equal(endorsement.authorization_basis_refs[0].digest,policy.digest);
  assert.deepEqual(approved.controller_endorsement_refs,[endorsement_ref]);
  const head=receiver.prepare('SELECT approval_id,run_revision FROM automation_run_approval_head WHERE run_id=?').get(approved.run_id);
  assert.equal(head.approval_id,approval_ref.object_id);
  assert.equal(head.run_revision,expectedRunRevision);
}
