import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {setTimeout as delay} from 'node:timers/promises';
import {DatabaseSync} from 'node:sqlite';
import {linuxPairingCertificates} from './linux-first-pairing.mjs';
import {readSimulatorFile,verifyComposeSimulatorSubscription,verifyDurableSimulatorSubscription} from './linux-compose-simulator-subscription.mjs';
import {approveComposeSimulatorRun,publishComposeSimulatorDefinition,runApprovalRoute,verifyDurableSimulatorPublication,
  verifyDurableSimulatorRunApproval} from './linux-compose-simulator-publication.mjs';

const id=()=>crypto.randomUUID();
const sha=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');
const mount='/etc/leafseamer/pairing/';
const node='/usr/local/bin/node',cli='/opt/leafseamer/dist/cli.mjs',loopback='https://127.0.0.1:8444';
const permissions=['auth.manage','auth.read'];

export async function completeLinuxComposeFirstPairing({root,plan,enrollment,login,clockValues,launch,send,selection,verifyBrowser=null,verifyLocalExtension=false,pairedSimulator=false}){
  const {canonical,digest}=clockValues;
  const {controller,seamer}=plan,{principal_id,issuer_id,issuer_epoch}=enrollment;
  const certificates=path.join(root,'pairing-certificates');
  fs.mkdirSync(certificates,{mode:0o700});
  const tls=linuxPairingCertificates(certificates,[controller.address,seamer.address]);
  const ca=fs.readFileSync(tls.caFile),trust=digest([sha(new crypto.X509Certificate(ca).raw)]);
  const roles={
    controller:{...controller,certificate:tls.c,credential_id:id()},
    seamer:{...seamer,certificate:tls.s,credential_id:id()}
  };
  function identity(kind){
    const {service_id,database_instance_id,credential_id}=roles[kind];
    return {service_id,database_instance_id,service_kind:kind,credential_id,issuer_id,issuer_epoch};
  }
  const peerOrigin=role=>'https://'+roles[role].address+':9443';
  const local=role=>({credential_id:roles[role].credential_id,host:roles[role].address,port:9443,network:true,server_name:roles[role].address,
    certificate_file:mount+'member.pem',private_key_file:mount+'member-key.pem',ca_files:[mount+'ca.pem']});
  const peer=role=>({identity:identity(role),origin:peerOrigin(role),server_name:roles[role].address,
    certificate_file:mount+'peer.pem',trust_bundle_digest:trust});
  const loopbackTls={certificate_file:mount+'member.pem',private_key_file:mount+'member-key.pem'};
  function profile(role,other,body,additionalFiles={}){
    const directory=path.join(root,role+'-pairing');
    fs.mkdirSync(directory,{mode:0o755});
    const inputs={'profile.json':Buffer.from(canonical({format:'leafseamer.'+role+'-pairing-profile/2',local:local(role),[other]:peer(other),...body})),
      'ca.pem':ca,'member.pem':fs.readFileSync(roles[role].certificate.certificate_file),
      'member-key.pem':fs.readFileSync(roles[role].certificate.private_key_file),'peer.pem':fs.readFileSync(roles[other].certificate.certificate_file),
      ...additionalFiles};
    for(const [name,bytes] of Object.entries(inputs)){
      const file=path.join(directory,name),secret=name==='member-key.pem';
      fs.writeFileSync(file,bytes,{mode:secret?0o640:0o644});
      if(secret)fs.chownSync(file,0,roles[role].gid);
    }
    return {directory,files:Object.fromEntries(Object.entries(inputs).map(([name,bytes])=>[name,sha(bytes)]))};
  }
  const controllerPairing=profile('controller','seamer',{bootstrap:plan.bootstrap.controller,https:{origin:loopback,...loopbackTls}});
  function execute(container,args,input){
    const child=spawn('docker',['exec','--interactive',container,node,...args],{stdio:['pipe','pipe','pipe'],signal:AbortSignal.timeout(14000)});
    let output='',diagnostic='';
    child.stdout.setEncoding('utf8').on('data',data=>output+=data);
    child.stderr.setEncoding('utf8').on('data',data=>diagnostic+=data);
    child.stdin.on('error',()=>{});child.stdin.end(canonical(input));
    return once(child,'close').then(([status])=>({status,output,diagnostic}));
  }
  async function admin(generation,operation,request,expectedError=null){
    const result=await execute(generation.containers.controller,[cli,'pairing-admin','--origin',loopback,'--ca-file',mount+'ca.pem'],
      {...login,operation,request});
    if(expectedError){
      assert.equal(result.status,1,operation+' '+result.output);
      assert.equal(JSON.parse(result.diagnostic).error,expectedError);
      return;
    }
    assert.equal(result.status,0,operation+' '+result.diagnostic);
    return JSON.parse(result.output);
  }
  async function waitFor(operation){
    const deadline=performance.now()+12000;
    do{
      const result=await operation();
      if(result)return result;
      await delay(100);
    }while(performance.now()<deadline);
    assert.fail('Compose pairing state did not become available');
  }
  async function loginThroughProxy(){
    const request={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(login)};
    return waitFor(async()=>{
      const response=await send('/auth/sessions',request).catch(()=>null);
      if(!response||[502,503].includes(response.status))return null;
      assert.equal(response.status,201,response.body.toString());
      const cookie=response.headers['set-cookie'][0].split(';')[0],csrf=response.headers['x-csrf-token'];
      return {Cookie:cookie,'X-CSRF-Token':csrf};
    });
  }
  async function issueToken(actor,audience,requested_scopes){
    const token=await send('/auth/service-tokens',{method:'POST',headers:{...actor,'Content-Type':'application/json'},
      body:JSON.stringify({audience,requested_scopes,extension_instance_id:null})});
    assert.equal(token.status,201,token.body.toString());
    return 'Bearer '+JSON.parse(token.body).data.access_token;
  }
  const start=BigInt(Date.now()-5000)*1000000n,end=start+110000000000n;
  function party(role,permissions){
    const {certificate}=roles[role].certificate;
    return {...identity(role),binding_id:id(),permissions,object_scope_digest:digest({devices:[]}),not_before_ns:String(start),expires_ns:String(end),
      certificate_der_sha256:sha(certificate.raw),spki_sha256:sha(certificate.publicKey.export({type:'spki',format:'der'})),
      trust_bundle_digest:trust,endpoint_config_digest:digest({origin:peerOrigin(role),server_name:roles[role].address})};
  }
  const localParty=party('seamer',['auth.introspect']);
  const {service_id,database_instance_id}=seamer;
  const verifyPublication=process.env.LEAFSEAMER_TEST_COMPOSE_PUBLICATION==='1';
  const simulatorPublication=process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_PUBLICATION==='1';
  const simulatorRunApproval=process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_RUN_APPROVAL==='1';
  assert.ok(!simulatorPublication||pairedSimulator&&!verifyPublication);
  assert.ok(!simulatorRunApproval||simulatorPublication);
  const verifySourceSubscription=pairedSimulator||process.env.LEAFSEAMER_TEST_COMPOSE_SOURCE_SUBSCRIPTION==='1';
  if(verifySourceSubscription)localParty.permissions.push('event.internal.subscribe');
  if(simulatorPublication)localParty.permissions.push('automation.bindings.read','events.internal.read');
  if(simulatorRunApproval)localParty.permissions.push('automation.prepare','automation.prepare.read');
  localParty.permissions.sort();
  const policyScope={authority_service_id:service_id,database_instance_id};
  const eventLimits={event_age_limits:[{authority_id:controller.service_id,registration_ref:{id:id(),revision:'1',digest:digest('fixture-registration')},
    capture_semantics:'event_occurrence',max_age_ms:1000}],max_condition_nodes:16};
  const policyRef={kind:'policy',scope:policyScope,object_id:'compose-publication-fixture',revision:'1',
    digest:digest(simulatorPublication?{purpose:'simulator_definition_publication'}:eventLimits)};
  const approvalFile='publication-approval.json';
  const approval=Buffer.from(canonical({format:simulatorPublication?'leafseamer.publication-policy-approval/1':'leafseamer.publication-policy-approval/2',
    policy_ref:policyRef,not_before_ns:String(start),expires_ns:String(end),...(!simulatorPublication&&eventLimits)}));
  const publicationProfile=verifyPublication||simulatorPublication?{publication_policy:{approval_file:mount+approvalFile,approval_sha256:sha(approval)}}:{};
  const seamerPairing=profile('seamer','controller',{scope:{service_id,database_instance_id},first_pairing_authorization_id:null,
    public_api:{...loopbackTls,host:'127.0.0.1',port:8444,binding_id:localParty.binding_id,allowed_origins:[],local_permissions:true,
      ...(verifySourceSubscription&&{local_source_subscriptions:true}),...(simulatorPublication&&{local_event_bindings:true}),
      ...(simulatorRunApproval&&{local_run_approvals:true})},
    ...publicationProfile},verifyPublication||simulatorPublication?{[approvalFile]:approval}:{});
  const generation=await launch({controller:controllerPairing,seamer:{...seamerPairing,await_first_pairing:true}});
  let activated,authorizationId,browserDraft,eventConsumer,simulatorSubscription,publishedSimulator,approvedSimulator;
  try{
    const baseline=pairedSimulator?await waitFor(()=>readSimulatorFile(generation.simulator,'ready')):null;
    if(baseline)localParty.object_scope_digest=digest({format:'leafseamer.device-binding-scope/1',authority_service_id:controller.service_id,
      database_instance_id:controller.database_instance_id,device_ids:[baseline.device]});
    const actor=await loginThroughProxy();
    const identityToken=await issueToken(actor,controller.service_id,['session.read']);
    const session=await send('/api/v1/session',{headers:{Authorization:identityToken}});
    assert.equal(session.status,200,session.body.toString());
    assert.equal((await send('/auth/local-pairing/v1',{method:'POST',headers:actor,body:'{}'})).status,404);
    if(verifyLocalExtension){
      assert.equal((await send('/auth/local-extension/v1',{method:'POST',headers:actor,body:'{}'})).status,404);
      const denied=await execute(generation.containers.controller,[cli,'extension-admin','--origin',loopback,'--ca-file',mount+'ca.pem'],
        {...login,operation:'start',request:{}});
      assert.equal(denied.status,1,denied.diagnostic);
      assert.equal(JSON.parse(denied.diagnostic).error,'extension_management_denied');
    }
    const controllerPurposes=simulatorRunApproval?['automation.prepare.read']:[];
    const staged=await admin(generation,'stage',{request_id:id(),transcript:{format:'leafseamer.peer-pairing/1',pair_attempt_id:id(),parties:[party('controller',controllerPurposes),localParty]}});
    const authorization=await admin(generation,'export',{binding_id:staged.binding_id,transcript_digest:staged.transcript_digest});
    assert.equal(authorization.authorization.administrator.principal_id,principal_id);
    authorizationId=authorization.authorization.authorization_id;
    await waitFor(async()=>{
      const response=await send('/services/'+service_id+'/api/v1/definitions/'+id()+'/draft').catch(()=>null);
      return response?.status===401;
    });
    assert.deepEqual(fs.readdirSync(generation.inbox),[]);
    assert.equal(generation.events('seamer').some(event=>event.event==='first_pairing_staged'),false);
    const temporary=path.join(generation.inbox,'.authorization');
    fs.writeFileSync(temporary,canonical(authorization),{mode:0o640,flag:'wx'});
    fs.chownSync(temporary,0,seamer.gid);
    fs.renameSync(temporary,path.join(generation.inbox,'authorization.json'));
    await waitFor(()=>generation.events('seamer').some(event=>event.event==='first_pairing_staged'&&event.authorization_id===authorizationId));
    const proof=await admin(generation,'prove',{binding_id:staged.binding_id});
    const proved=proof.state==='proved'?proof:await waitFor(async()=>{
      const state=await admin(generation,'inspect',{binding_id:staged.binding_id});
      return state.state==='proved'&&state;
    });
    activated=await admin(generation,'activate',{request_id:id(),binding_id:staged.binding_id,expected_revision:proved.revision,transcript_digest:proved.transcript_digest});
    assert.equal(activated.state,'activated');
    assert.equal(activated.service_boot_id,staged.service_boot_id);
    if(verifyLocalExtension){
      const request={request_id:id(),display_name:'Compose source consumer'};
      eventConsumer=await admin(generation,'create-event-consumer',request);
      assert.equal(eventConsumer.purpose,'event_consumer');
      assert.equal(eventConsumer.state,'disabled');
      assert.deepEqual(await admin(generation,'create-event-consumer',request),eventConsumer);
      await admin(generation,'approve-event-consumer',{permissions:['event.internal.subscribe','device.command']},'service_identity_input');
      await admin(generation,'approve-event-policy',{permissions:['event.internal.subscribe','device.command']},'service_identity_input');
    }
    const definitions=verifyBrowser||verifyPublication||simulatorPublication?['definition.edit','definition.read','request.create','request.read']:[];
    const audiencePermissions=[...permissions,...definitions,...(verifyPublication||simulatorPublication?['definition.publish']:[]),
      ...(simulatorPublication?['run.manage','run.read']:[]),...(simulatorRunApproval?['run.approve']:[])].sort();
    await admin(generation,'grant-audience',{request_id:id(),principal_id,audience:service_id,expected_revision:null,permissions:audiencePermissions,
      not_before_ns:activated.not_before_ns,expires_ns:activated.expires_ns,pairing_ref:{id:activated.binding_id,revision:activated.revision,digest:activated.digest}});
    const bearer=await issueToken(actor,service_id,permissions);
    assert.equal((await send('/services/'+service_id+'/auth/local-permissions/v1',{method:'POST',headers:{Authorization:bearer},body:'{}'})).status,404);
    if(simulatorRunApproval)assert.equal((await send('/services/'+service_id+runApprovalRoute,{method:'POST',headers:{Authorization:bearer},body:'{}'})).status,404);
    const inspection=`const https=require('node:https'),fs=require('node:fs');
      const input=JSON.parse(fs.readFileSync(0,'utf8')),body=Buffer.from(input.body);
      const req=https.request(${JSON.stringify(loopback)}+input.route,{ca:fs.readFileSync(${JSON.stringify(mount+'ca.pem')}),
        method:'POST',headers:{Authorization:input.bearer,'Content-Type':'application/json','Content-Length':body.length}},res=>{
        let data='';res.on('data',chunk=>data+=chunk);res.on('end',()=>process.stdout.write(JSON.stringify({status:res.statusCode,data})));
      });req.setTimeout(5000,()=>req.destroy());req.end(body);`;
    async function localRequest(route,operation,request,authorization=bearer){
      const response=await execute(generation.containers.seamer,['-e',inspection],{route,bearer:authorization,body:canonical({operation,request})});
      assert.equal(response.status,0,response.diagnostic);
      return JSON.parse(response.output);
    }
    const localPermissions=(operation,request)=>localRequest('/auth/local-permissions/v1',operation,request);
    const grant=await waitFor(async()=>{
      const {status,data}=await localPermissions('inspect',{principal_id});
      if(status!==200)return null;
      return JSON.parse(data).result;
    });
    assert.deepEqual(grant.permissions,permissions);
    if(verifyBrowser||verifyPublication||simulatorPublication){
      const changed=await localPermissions('replace',{request_id:id(),principal_id,principal_kind:'human',expected_revision:grant.revision,
        permissions:audiencePermissions,definition_scope:grant.definition_scope,not_before_ns:grant.not_before_ns,expires_ns:grant.expires_ns});
      assert.equal(changed.status,200,changed.data);
    }
    if(pairedSimulator){
      const beforeWrite=simulatorPublication?async()=>{
        const publicationBearer=await issueToken(actor,service_id,audiencePermissions);
        publishedSimulator=await publishComposeSimulatorDefinition({serviceId:service_id,controller,baseline,bindingId:localParty.binding_id,
          policyRef,selection,bearer:publicationBearer,send,localRequest,canonical,digest});
        if(simulatorRunApproval)approvedSimulator=await approveComposeSimulatorRun({run:publishedSimulator.run,baseline,controller,principalId:principal_id,
          bindingId:localParty.binding_id,pairing:activated,admin:(operation,request)=>admin(generation,operation,request),
          localRequest,issueBearer:scopes=>issueToken(actor,service_id,scopes)});
      }:null;
      const afterWrite=simulatorRunApproval?async()=>{
        approvedSimulator.preflight=await approvedSimulator.observePreflight('synchronized');
      }:null;
      simulatorSubscription=await verifyComposeSimulatorSubscription({plan,simulator:generation.simulator,baseline,pairing:activated,
        admin:(operation,request)=>admin(generation,operation,request),localRequest,waitFor,digest,beforeWrite,afterWrite});
    }else if(verifySourceSubscription){
      const route='/auth/local-source-subscriptions/v1',reference=entity_kind=>({authority_service_id:controller.service_id,
        database_instance_id:controller.database_instance_id,entity_kind,entity_id:id(),entity_epoch:id(),revision:'1',content_digest:'a'.repeat(64)});
      const request={request_id:id(),consumer_id:'compose-unapproved',scope:{scope_id:id(),scope_revision:'1',
        projection_profile_ref:reference('projection_profile'),collections:[{entity_kind:'sources',selector_ref:reference('selector'),
          relation_policy:'authorized_reference',history_policy:'current'}]}};
      assert.equal((await send('/services/'+service_id+route,{method:'POST',headers:{Authorization:bearer},body:'{}'})).status,404);
      assert.equal((await localRequest(route,'connect',request,'')).status,401);
      const denied=await localRequest(route,'connect',request);
      assert.equal(denied.status,403,denied.data);
      assert.deepEqual(JSON.parse(denied.data),{error:'PERMISSION_DENIED'});
    }
    if(verifyBrowser)browserDraft=await verifyBrowser();
    if(verifyPublication){
      const token=await issueToken(actor,service_id,[...definitions,'definition.publish'].sort());
      const api='/services/'+service_id+'/api/v1';
      const post=(target,body,headers={})=>send(api+target,{method:'POST',headers:{Authorization:token,'Content-Type':'application/json',...headers},body:canonical(body)});
      const context=async operations=>{
        const response=await post('/request-contexts',{audience:service_id,selection,operations,ttl_ms:30000,max_unique_requests:1});
        assert.equal(response.status,201,response.body.toString());
        return {id:JSON.parse(response.body).data.context_id,csrf:response.headers['x-csrf-token']};
      };
      const program={kind:'rule',trigger_binding_id:'fixture-input',condition:{kind:'literal',value:true},
        groups:[{mode:'sequence',steps:[{step_id:'fixture-delay',depends_on:[],required:true,failure_policy:'stop',kind:'delay',delay_ms:0,max_lateness_ms:100}]}]};
      const missingSelection={kind:'input',binding_id:'fixture-input',content_ref:{id:id(),revision:'1',digest:digest('unapproved-input')}};
      async function createDraft(policy_ref,selections){
        const create=await context(['createDefinition','getDraft']);
        const draft=await post('/definitions',{context:{context_id:create.id,idempotency_key:id()},content:{program,selections,policy_ref},
          metadata:{name:'Compose 发布保护验收',description:'',layout:{}}});
        assert.equal(draft.status,201,draft.body.toString());
        return JSON.parse(draft.body);
      }
      async function expectBlockedPublication({definition_id,revision,content_digest,selection_digest},expected){
        const publish=await context(['publishDefinition']);
        assert.match(publish.csrf,/^[A-Za-z0-9_-]{43}$/);
        const attempt=await post('/definitions/'+definition_id+'/publish',{context:{context_id:publish.id,idempotency_key:id()},
          expected_draft_revision:revision,expected_content_digest:content_digest,expected_selection_digest:selection_digest},{'X-CSRF-Token':publish.csrf});
        assert.equal(attempt.status,expected,attempt.body.toString());
      }
      const matching=await createDraft(policyRef,[]);
      // 编译器拒绝缺少触发器的规则。错策略及未批准的选择在到达编译器前就拒绝。
      await expectBlockedPublication(matching,503);
      await expectBlockedPublication(await createDraft({...policyRef,revision:'2'},[]),403);
      await expectBlockedPublication(await createDraft(policyRef,[missingSelection]),403);
      const mountedApproval=path.join(seamerPairing.directory,approvalFile);
      try{
        fs.appendFileSync(mountedApproval,'\n');
        await expectBlockedPublication(matching,403);
      }finally{fs.writeFileSync(mountedApproval,approval);}
      await expectBlockedPublication(matching,403);
    }
  }finally{await generation.stop();}
  assert.equal(generation.phase(),'retired');
  const store=new DatabaseSync(path.join(seamer.data_dir,'seamer.sqlite'),{readOnly:true});
  const issuer=new DatabaseSync(path.join(controller.data_dir,'controller.sqlite'),{readOnly:true});
  try{
    assert.equal(store.prepare('SELECT authorization_id FROM first_pairing_completion').get().authorization_id,authorizationId);
    assert.equal(issuer.prepare('SELECT binding_id FROM peer_pairing_head').get().binding_id,activated.binding_id);
    if(simulatorSubscription)verifyDurableSimulatorSubscription({receiver:store,publisher:issuer,...simulatorSubscription});
    if(simulatorPublication){assert.ok(publishedSimulator);verifyDurableSimulatorPublication(store,publishedSimulator,digest);}
    if(simulatorRunApproval){assert.ok(approvedSimulator);verifyDurableSimulatorRunApproval(store,issuer,approvedSimulator,digest);}
    if(eventConsumer){
      const stored=issuer.prepare(`SELECT body_jcs FROM service_principal_revision
        WHERE principal_id=? AND revision=1`).get(eventConsumer.id);
      assert.deepEqual(JSON.parse(stored.body_jcs),eventConsumer);
      assert.equal(issuer.prepare('SELECT count(*) AS n FROM service_approval WHERE principal_id=?').get(eventConsumer.id).n,0);
    }
    if(browserDraft&&!verifyPublication)assert.deepEqual(store.prepare('SELECT definition_id FROM definition_identity').all().map(row=>row.definition_id),[browserDraft]);
    if(verifyPublication){
      assert.equal(store.prepare('SELECT count(*) AS n FROM definition_version_reservation').get().n,5);
      assert.equal(store.prepare('SELECT count(*) AS n FROM definition_publication').get().n,0);
      assert.equal(store.prepare('SELECT count(*) AS n FROM definition_publication_proof').get().n,0);
    }
  }finally{store.close();issuer.close();}
}
