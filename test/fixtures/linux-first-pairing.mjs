import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import https from 'node:https';
import net from 'node:net';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';
import {once} from 'node:events';
import {DatabaseSync} from 'node:sqlite';
import {setTimeout as delay} from 'node:timers/promises';
import {pathToFileURL} from 'node:url';

const id=()=>crypto.randomUUID();
const origin=port=>'https://127.0.0.1:'+port;
const sha=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');

function certificates(directory){
  const config=path.join(directory,'openssl.cnf');
  fs.writeFileSync(config,'[req]\ndistinguished_name=subject\n[subject]\n');
  function openssl(...args){
    const result=spawnSync('/usr/bin/openssl',args,{cwd:directory,encoding:'utf8',timeout:5000,env:{...process.env,OPENSSL_CONF:config}});
    assert.equal(result.status,0,result.stderr||result.error?.message);
  }
  function key(file){openssl('genpkey','-algorithm','EC','-pkeyopt','ec_paramgen_curve:P-256','-out',file);}
  key('ca.key');
  openssl('req','-new','-x509','-key','ca.key','-subj','/CN=Pairing test CA','-days','2',
    '-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign','-out','ca.pem');
  fs.writeFileSync(path.join(directory,'leaf.ext'),'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth,clientAuth\nsubjectAltName=IP:127.0.0.1\n');
  function leaf(role,serial){
    key(role+'.key');
    openssl('req','-new','-key',role+'.key','-subj','/CN=localhost','-out',role+'.csr');
    openssl('x509','-req','-in',role+'.csr','-CA','ca.pem','-CAkey','ca.key','-set_serial',serial,'-days','1',
      '-extfile','leaf.ext','-out',role+'.pem');
    const private_key_file=path.join(directory,role+'.key'),certificate_file=path.join(directory,role+'.pem');
    fs.chownSync(private_key_file,0,65534);fs.chmodSync(private_key_file,0o640);
    return {certificate_file,private_key_file,certificate:new crypto.X509Certificate(fs.readFileSync(certificate_file))};
  }
  return {caFile:path.join(directory,'ca.pem'),c:leaf('controller','11'),s:leaf('seamer','12')};
}

export async function completeLinuxFirstPairing({controller,seamer,scratch,target,admit,stop,clockPublisher,readClockChallenge}){
  const {canonical,digest}=await import(pathToFileURL(path.join(controller,'auth-clock-value.mjs')));
  const {contractSelection}=await import(pathToFileURL(path.join(controller,'sdk','index.mjs')));
  const {currentStorageRevision}=await import(pathToFileURL(path.join(controller,'storage-revision.mjs')));
  const seamerRevision='33';
  const credentials={login:'first.pair',password:'Fixture-6!'+crypto.randomBytes(18).toString('base64url')};
  let principal_id,issuer;
  const reservations=Array.from({length:3},()=>net.createServer().listen(0,'127.0.0.1'));
  await Promise.all(reservations.map(server=>once(server,'listening')));
  const [controllerPeer,seamerPeer,seamerPublic]=reservations.map(server=>server.address().port);
  await Promise.all(reservations.map(server=>new Promise(resolve=>server.close(resolve))));
  const c=await target('controller',controller,'pair-controller',{authenticateClock:true,targetRevision:currentStorageRevision,
    async provision(storage){
      const {token_id,secret}=storage.enrollment.begin();
      ({principal_id}=await storage.enrollment.complete({token_id,secret,...credentials,mode:'standalone'}));
      issuer=storage.enrollment.summary();
    }});
  const s=await target('seamer',seamer,'pair-seamer',{authenticateClock:true,targetRevision:seamerRevision,
    generation_id:c.intent.generation_id,sharedInstallation:c.installation});
  const tls=certificates(scratch),ca=fs.readFileSync(tls.caFile),trust=digest([sha(new crypto.X509Certificate(ca).raw)]);
  function write(name,value){const file=path.join(scratch,name);fs.writeFileSync(file,value,{mode:0o644});return file;}
  function scope(actual){return {service_id:actual.policy.service_id,database_instance_id:actual.policy.database_instance_id};}
  function identity(actual,kind){return {...scope(actual),service_kind:kind,credential_id:id(),issuer_id:issuer.issuer_id,issuer_epoch:issuer.issuer_epoch};}
  const a=identity(c,'controller'),b=identity(s,'seamer');
  function local(identity,port,certificate){return {credential_id:identity.credential_id,host:'127.0.0.1',port,
    certificate_file:certificate.certificate_file,private_key_file:certificate.private_key_file,ca_files:[tls.caFile]};}
  function peer(identity,port,certificate){return {identity,origin:origin(port),server_name:'127.0.0.1',
    certificate_file:certificate.certificate_file,trust_bundle_digest:trust};}
  c.intent.args.push('--pairing-profile',write('controller-pairing.json',canonical({format:'leafseamer.controller-pairing-profile/2',bootstrap:c.policy,
    https:{origin:origin(c.port),certificate_file:tls.c.certificate_file,private_key_file:tls.c.private_key_file},
    local:local(a,controllerPeer,tls.c),seamer:peer(b,seamerPeer,tls.s)})));
  const headers={'x-leafseamer-contract':contractSelection.contract_id,'x-leafseamer-contract-digest':contractSelection.contract_digest};
  function send(port,target,body,extra={}){
    const bytes=body===undefined?null:Buffer.from(canonical(body));
    return new Promise((resolve,reject)=>{
      const req=https.request(origin(port)+target,{ca,agent:false,method:bytes?'POST':'GET',headers:{...headers,...extra,
        ...(bytes&&{'Content-Type':'application/json','Content-Length':bytes.length})},signal:AbortSignal.timeout(8000)},res=>{
        const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.on('error',reject);
        res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks)}));
      });req.on('error',reject);req.end(bytes);
    });
  }
  const renewals=[],renewalStop=new AbortController();
  let failure,lastPermission=null,stage='controller-admission';
  async function until(check){
    const end=performance.now()+12000;
    do{if(failure)throw failure;const result=await check();if(result)return result;await delay(50);}while(performance.now()<end);
    assert.fail('Linux first pairing did not reach the expected state');
  }
  async function admitClock(actual,httpsPort){
    const {record}=await admit(actual);
    assert.equal(record.phase,'executed_closed');
    await until(()=>fs.readdirSync(actual.clock.directory).some(name=>name.startsWith('challenge-')));
    await assert.rejects(send(httpsPort,'/health/ready'),{code:'ECONNREFUSED'});
    const challenge=readClockChallenge(actual,record.detail.admission.descriptor);
    const publish=clockPublisher({actual,challenge},120000000000n,{asynchronous:true});
    await publish({useChrony:true});
    renewals.push((async()=>{
      try{
        while(!renewalStop.signal.aborted){
          await delay(500,undefined,{signal:renewalStop.signal});
          await publish({useChrony:true});
        }
      }catch(error){if(!renewalStop.signal.aborted)failure??=error;}
    })());
    return challenge;
  }
  let actor;
  const admin=async(operation,request)=>{
    const result=await send(c.port,'/auth/local-pairing/v1',{operation,request},actor);
    assert.equal(result.status,200,result.body.toString());
    return JSON.parse(result.body);
  };
  try{
    const controllerChallenge=await admitClock(c,c.port);
    stage='controller-login';
    await until(async()=>{try{const result=await send(c.port,'/health/ready');return result.status===503&&JSON.parse(result.body).authentication_clock==='available';}
      catch(error){if(error.code!=='ECONNREFUSED')throw error;}});
    const login=await send(c.port,'/auth/sessions',credentials,{Origin:origin(c.port)});
    assert.equal(login.status,201,login.body.toString());
    actor={Origin:origin(c.port),Cookie:login.headers['set-cookie'][0].split(';')[0],'X-CSRF-Token':login.headers['x-csrf-token']};
    const start=BigInt(Date.now()-5000)*1000000n,end=start+110000000000n;
    function party(identity,port,{certificate},permissions){return {...identity,binding_id:id(),permissions,object_scope_digest:digest({devices:[]}),
      not_before_ns:String(start),expires_ns:String(end),certificate_der_sha256:sha(certificate.raw),
      spki_sha256:sha(certificate.publicKey.export({type:'spki',format:'der'})),trust_bundle_digest:trust,
      endpoint_config_digest:digest({origin:origin(port),server_name:'127.0.0.1'})};}
    const localParty=party(b,seamerPeer,tls.s,['auth.introspect']);
    stage='authorization-export';
    const staged=await admin('stage',{request_id:id(),transcript:{format:'leafseamer.peer-pairing/1',pair_attempt_id:id(),
      parties:[party(a,controllerPeer,tls.c,[]),localParty]}});
    const authorization=await admin('export',{binding_id:staged.binding_id,transcript_digest:staged.transcript_digest});
    const authorizationId=authorization.authorization.authorization_id;
    assert.equal(authorization.authorization.administrator.principal_id,principal_id);
    stage='authorization-import';
    const imported=spawn(process.execPath,[path.join(seamer,'cli.mjs'),'import-first-pairing','--data-dir',s.data,
      '--authorization-file',write('authorization.json',canonical(authorization)),'--controller-certificate',tls.c.certificate_file,
      '--seamer-certificate',tls.s.certificate_file],{stdio:['ignore','ignore','pipe'],signal:AbortSignal.timeout(10000)});
    let diagnostic='';imported.stderr.setEncoding('utf8').on('data',chunk=>{diagnostic+=chunk;});
    assert.equal((await once(imported,'close'))[0],0,diagnostic);
    s.intent.args.push('--pairing-profile',write('seamer-pairing.json',canonical({format:'leafseamer.seamer-pairing-profile/2',scope:scope(s),
      first_pairing_authorization_id:authorizationId,local:local(b,seamerPeer,tls.s),controller:peer(a,controllerPeer,tls.c),
      public_api:{host:'127.0.0.1',port:seamerPublic,certificate_file:tls.s.certificate_file,private_key_file:tls.s.private_key_file,
        binding_id:localParty.binding_id,allowed_origins:[origin(c.port)],local_permissions:true}})));
    stage='seamer-admission';
    const seamerChallenge=await admitClock(s,seamerPublic);
    await until(async()=>{try{return (await send(seamerPublic,'/health/ready')).status>0;}
      catch(error){if(error.code!=='ECONNREFUSED')throw error;}});
    stage='pairing-proof';
    const firstProof=await admin('prove',{binding_id:staged.binding_id});
    const proved=firstProof.state==='proved'?firstProof:await until(async()=>{
      const view=await admin('inspect',{binding_id:staged.binding_id});
      return view.state==='proved'&&view;
    });
    stage='pairing-activation';
    const activated=await admin('activate',{request_id:id(),binding_id:staged.binding_id,expected_revision:proved.revision,
      transcript_digest:proved.transcript_digest});
    assert.equal(activated.state,'activated');
    const permissions=['auth.manage','auth.read'];
    stage='token-issuance';
    await admin('grant-audience',{request_id:id(),principal_id,audience:b.service_id,expected_revision:null,permissions,
      not_before_ns:activated.not_before_ns,expires_ns:activated.expires_ns,
      pairing_ref:{id:activated.binding_id,revision:activated.revision,digest:activated.digest}});
    const token=await send(c.port,'/auth/service-tokens',{audience:b.service_id,requested_scopes:permissions,extension_instance_id:null},actor);
    assert.equal(token.status,201,token.body.toString());
    const bearer='Bearer '+JSON.parse(token.body).data.access_token;
    const inspect=()=>send(seamerPublic,'/auth/local-permissions/v1',{operation:'inspect',request:{principal_id}},{Authorization:bearer});
    stage='permissions-read';
    const grant=await until(async()=>{
      const result=await inspect();
      if(result.status===200)return JSON.parse(result.body).result;
      lastPermission={status:result.status,body:result.body.toString()};
    });
    assert.deepEqual(grant.permissions,permissions);
    assert.ifError(failure);
    stage='retirement-and-persistence';
    await stop(c,s);
    await assert.rejects(inspect(),{code:'ECONNREFUSED'});
    const database=new DatabaseSync(path.join(s.data,'seamer.sqlite'),{readOnly:true});
    try{
      assert.equal(database.prepare('PRAGMA user_version').get().user_version,Number(seamerRevision));
      assert.equal(database.prepare('SELECT authorization_id FROM first_pairing_completion').get().authorization_id,authorizationId);
      assert.equal(database.prepare('SELECT service_boot_id FROM core_runtime_binding').get().service_boot_id,seamerChallenge.service_boot_id);
      assert.ok(database.prepare('SELECT count(*) AS n FROM authentication_clock_acquisition WHERE service_boot_id=?').get(seamerChallenge.service_boot_id).n>0);
    }finally{database.close();}
    const controllerDatabase=new DatabaseSync(path.join(c.data,'controller.sqlite'),{readOnly:true});
    try{
      assert.equal(controllerDatabase.prepare('PRAGMA user_version').get().user_version,currentStorageRevision);
      assert.equal(controllerDatabase.prepare('SELECT service_boot_id FROM core_runtime_binding').get().service_boot_id,controllerChallenge.service_boot_id);
      assert.equal(controllerDatabase.prepare('SELECT binding_id FROM peer_pairing_head').get().binding_id,activated.binding_id);
    }finally{controllerDatabase.close();}
  }catch(error){
    const states=await Promise.allSettled([send(c.port,'/health/ready'),fetch('http://127.0.0.1:'+s.port+'/health/ready',{signal:AbortSignal.timeout(2000)}).then(async response=>({body:await response.text()}))]);
    const details=states.map(result=>result.status==='fulfilled'?result.value.body.toString():result.reason.code??result.reason.cause?.code??'unavailable');
    throw new Error(`Linux first pairing at ${stage}: ${error.code??error.message}; controller=${details[0]}; seamer=${details[1]}; permission=${JSON.stringify(lastPermission)}`,{cause:failure??error});
  }finally{renewalStop.abort();await Promise.all(renewals);}
}
