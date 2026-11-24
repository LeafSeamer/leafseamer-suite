import assert from 'node:assert/strict';
import crypto from 'node:crypto';

const id=()=>crypto.randomUUID();
const condition={kind:'literal',value:true};
const eventRoute='/auth/local-event-bindings/v1';

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
  const query={binding_id:bindingId,scope:{format:'leafseamer.device-binding-scope/1',authority_service_id:controller.service_id,
    database_instance_id:controller.database_instance_id,device_ids:[baseline.device]},device_id:baseline.device,expected_registration_ref:null};
  const source={...query,expected_source_ref:baseline.source_ref};
  const candidate=await event('candidate',{definition_id,query:source});
  assert.deepEqual(candidate.source_ref,baseline.source_ref);
  assert.deepEqual(candidate.source_key,baseline.baseline.origin.source_key);
  const eventContext=await event('create-context',{ttl_ms:30000,max_unique_requests:1});
  const eventApproval=await event('approve',{query:source,context_id:eventContext.context_id,
    approval:{request_id:id(),approval_id:id(),definition_id,expected_candidate_digest:candidate.candidate_digest}});
  assert.equal(eventApproval.state,'approved');
  assert.deepEqual(eventApproval.candidate,candidate);
  const deviceQuery={...query,expected_registration_ref:candidate.device_registration_ref};
  const {body:deviceCandidate}=await request('POST',target+'/binding-candidates/query',deviceQuery,200);
  const deviceContext=await context(['approveDefinitionBindings']);
  const {body:deviceApproval}=await request('POST',target+'/binding-approvals',{context:{context_id:deviceContext.context_id},
    request_id:id(),approval_id:id(),source:deviceQuery,expected_bundle_digest:deviceCandidate.bundle_digest},201,deviceContext.csrf);
  assert.equal(deviceApproval.state,'approved');
  const action=deviceApproval.bundle.bindings.find(binding=>binding.kind==='action');
  assert.equal(action.value.device_id,baseline.device);
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
