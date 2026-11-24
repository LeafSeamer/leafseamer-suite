import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import https from 'node:https';
import crypto from 'node:crypto';
import {spawn,spawnSync} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {DatabaseSync} from 'node:sqlite';

const controller=process.env.LEAFSEAMER_CONTROLLER_TEST_ROOT,seamer=process.env.LEAFSEAMER_SEAMER_TEST_ROOT;
const file=name=>fileURLToPath(new URL(name,import.meta.url));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function tool(binary,args,timeout=10000){const result=spawnSync(binary,args,{encoding:'utf8',timeout});assert.equal(result.status,0,result.stderr);return result.stdout;}
async function freePort(address){
  const listener=net.createServer();listener.listen(0,address);await once(listener,'listening');
  const port=listener.address().port;
  await new Promise(resolve=>listener.close(resolve));return port;
}

test('Linux Nginx 对接实际 Controller 和 Seamer 的受保护入口',{
  skip:process.platform!=='linux'||!controller||!seamer,timeout:140000
},async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-real-ingress-')),children=[];
  fs.chmodSync(root,0o755);
  t.after(async()=>{
    for(const {child,exit,stop} of children.reverse()){
      if(child.exitCode===null&&child.signalCode===null)stop();
      const deadline=setTimeout(()=>child.kill('SIGKILL'),5000);await exit;clearTimeout(deadline);
    }
    assert.equal(path.dirname(root),os.tmpdir());fs.rmSync(root,{recursive:true,force:true});
  });
  function certificate(host,peer=false){
    const cert=path.join(root,host+'.pem'),key=path.join(root,host+'.key');
    if(peer){
      const ca=path.join(root,'peer-ca.pem'),caKey=path.join(root,'peer-ca.key'),csr=path.join(root,'peer.csr'),ext=path.join(root,'peer.ext');
      tool('openssl',['req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','2','-sha256','-subj','/CN=Ingress test CA',
        '-addext','basicConstraints=critical,CA:TRUE,pathlen:0','-keyout',caKey,'-out',ca]);
      tool('openssl',['req','-new','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-subj','/CN='+host,'-keyout',key,'-out',csr]);
      fs.writeFileSync(ext,'basicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth,clientAuth\nsubjectAltName=DNS:'+host+'\n');
      tool('openssl',['x509','-req','-in',csr,'-CA',ca,'-CAkey',caKey,'-CAcreateserial','-days','1','-sha256','-extfile',ext,'-out',cert]);
      return {cert,key,ca,peerName:host};
    }
    tool('openssl',['req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN='+host,
      '-addext','subjectAltName=DNS:'+host,'-keyout',key,'-out',cert]);return {cert,key,ca:cert};
  }
  const host='manage.fixture.invalid',controlName='controller.fixture.invalid',seamerName='seamer.fixture.invalid';
  const site=certificate(host),controlTls=certificate(controlName),seamerTls=certificate(seamerName,true);
  const port=await freePort('127.0.0.1'),authority=host+':'+port,origin='https://'+authority;
  const login={login:'ingress.fixture',password:'Synthetic-ingress-test-password-321'};
  function fixture(role,packageRoot,tls,issuer){
    const config=path.join(root,role+'.json');
    fs.writeFileSync(config,JSON.stringify({role,package_root:packageRoot,data_dir:path.join(root,role),origin,...tls,login,issuer}));
    return [file('./fixtures/linux-ingress-service.mjs'),config];
  }
  async function start(args,stop){
    const child=spawn(process.execPath,args,{stdio:['pipe','pipe','pipe']});
    child.stdin.on('error',()=>{});const exit=once(child,'close');children.push({child,exit,stop:()=>stop(child)});
    let output='',errors='';child.stdout.setEncoding('utf8').on('data',data=>{output+=data;});child.stderr.setEncoding('utf8').on('data',data=>{errors+=data;});
    const deadline=performance.now()+65000;
    while(!output.includes('\n')){assert.ok(performance.now()<deadline&&child.exitCode===null,errors);await delay(25);}
    return {child,exit,result:JSON.parse(output.split('\n')[0])};
  }
  const c=JSON.parse(tool(process.execPath,fixture('controller',controller,controlTls),65000));
  const controllerAddress=Object.values(os.networkInterfaces()).flat().find(entry=>entry.family==='IPv4'&&!entry.internal)?.address;
  assert.ok(controllerAddress,'需要容器桥接接口');
  c.public_port=await freePort(controllerAddress);
  const dataDir=path.join(root,'controller'),profileFile=path.join(root,'controller-ingress.json');
  const profile={format:'leafseamer.controller-protected-ingress/1',address:controllerAddress,port:c.public_port,origin,
    service_id:c.identity.service_id,database_instance_id:c.identity.database_instance_id,
    certificate_file:controlTls.cert,private_key_file:controlTls.key};
  const cliArgs=['--disallow-code-generation-from-strings',path.join(controller,'dist/cli.mjs'),'start-protected-ingress',
    '--data-dir',dataDir,'--ingress-profile',profileFile];
  function bootRows(){
    const db=new DatabaseSync(path.join(dataDir,'controller.sqlite'),{readOnly:true});
    try{return db.prepare('SELECT service_boot_id,state FROM service_boot ORDER BY service_boot_id').all();}
    finally{db.close();}
  }
  const before=bootRows();
  for(const [overrides,code]of [
    [{database_instance_id:crypto.randomUUID()},'protected_ingress_identity'],
    [{service_id:crypto.randomUUID()},'protected_ingress_identity'],
    [{address:'0.0.0.0'},'protected_ingress_address'],
    [{origin:'http://'+authority},'protected_ingress_profile'],
    [{private_key_file:site.key},'protected_ingress_profile']
  ]){
    fs.writeFileSync(profileFile,JSON.stringify({...profile,...overrides}),{mode:0o600});
    const failed=spawnSync(process.execPath,cliArgs,{encoding:'utf8',timeout:10000});
    assert.equal(failed.status,1,failed.stderr);assert.equal(failed.stdout,'');assert.equal(JSON.parse(failed.stderr).error,code);
  }
  assert.deepEqual(bootRows(),before);
  fs.writeFileSync(profileFile,JSON.stringify(profile),{mode:0o600});
  const control=await start(cliArgs,child=>child.kill('SIGTERM'));
  assert.equal(control.result.event,'listening');assert.equal(control.result.ready,false);
  assert.equal(control.result.host,controllerAddress);assert.equal(control.result.port,c.public_port);
  assert.equal(control.result.service_id,c.identity.service_id);
  assert.equal(control.result.database_instance_id,c.identity.database_instance_id);
  const {result:s}=await start(fixture('seamer',seamer,seamerTls,c.issuer),child=>child.stdin.end());
  assert.equal(s.event,'started');assert.equal(s.qualified,false);
  const loadSelection=async root=>(await import(pathToFileURL(path.join(root,'dist/sdk/index.mjs')))).contractSelection;
  const selection=await loadSelection(controller);assert.deepEqual(await loadSelection(seamer),selection);
  const directory=path.join(root,'gui');fs.mkdirSync(path.join(directory,'assets'),{recursive:true});
  const siteConfig={format:'leafseamer.gui.site/2',service_id:c.identity.service_id,database_instance_id:c.identity.database_instance_id,
    site_label:'套件联调',selection,seamer:{service_id:s.identity.service_id,database_instance_id:s.identity.database_instance_id,
      base_url:origin+'/services/'+s.identity.service_id,service_label:'Seamer'}};
  const assets={'index.html':'<!doctype html><title>LeafSeamer</title>','assets/index-case.js':'void 0;',
    'assets/index-case.css':'body {}','site.json':JSON.stringify(siteConfig),'SDK-LICENSE.txt':'test fixture'};
  for(const [name,content]of Object.entries(assets))fs.writeFileSync(path.join(directory,name),content);
  const manifest=JSON.stringify({format:'leafseamer.gui.build/1',sdk_manifest_sha256:hash(fs.readFileSync(path.join(controller,'dist/sdk/build-manifest.json'))),
    selection,artifacts:Object.fromEntries(Object.entries(assets).map(([name,content])=>[name,hash(content)]))});
  fs.writeFileSync(path.join(directory,'gui-manifest.json'),manifest);
  const backend=(role,r,name,tls)=>({role,service_id:r.identity.service_id,database_instance_id:r.identity.database_instance_id,
    address:role==='controller'?controllerAddress:'127.0.0.1',port:r.public_port,server_name:name,ca_file:tls.ca});
  const plan=path.join(root,'plan.json'),config=path.join(root,'nginx.conf');
  fs.writeFileSync(plan,JSON.stringify({format:'leafseamer.linux-ingress/1',issuer_service_id:c.identity.service_id,
    management:{address:'127.0.0.1',port,host,certificate_file:site.cert,private_key_file:site.key},
    services:[backend('controller',c,controlName,controlTls),backend('seamer',s,seamerName,seamerTls)],gui:{directory,manifest_sha256:'sha256:'+hash(manifest)}}));
  fs.writeFileSync(config,tool(process.execPath,[file('../dist/linux-ingress.mjs'),'--config',plan]));
  tool('nginx',['-t','-p',root+'/','-c',config]);
  const nginx=spawn('nginx',['-p',root+'/','-c',config,'-g','daemon off;'],{stdio:['ignore','ignore','pipe']});
  let errors='';nginx.stderr.setEncoding('utf8').on('data',data=>{errors+=data;});children.push({child:nginx,exit:once(nginx,'close'),stop:()=>nginx.kill('SIGQUIT')});
  const contract={'X-LeafSeamer-Contract':selection.contract_id,'X-LeafSeamer-Contract-Digest':selection.contract_digest};
  function send(route,{method='GET',headers={},body}={}){
    return new Promise((resolve,reject)=>{
      const req=https.request({hostname:'127.0.0.1',port,servername:host,path:route,ca:fs.readFileSync(site.cert),method,
        headers:{Host:authority,...contract,Origin:origin,...headers},agent:false,timeout:5000},response=>{
        const chunks=[];response.on('data',piece=>chunks.push(piece));response.once('error',reject);
        response.on('end',()=>resolve({status:response.statusCode,headers:response.headers,body:Buffer.concat(chunks).toString()}));
      });
      req.on('error',reject);req.on('timeout',()=>req.destroy(new Error('ingress_request_timeout')));req.end(body);
    });
  }
  const deadline=performance.now()+5000;
  for(;;){try{assert.deepEqual(JSON.parse((await send('/site.json')).body),siteConfig);break;}
    catch(error){if(performance.now()>deadline||nginx.exitCode!==null)throw new Error(errors,{cause:error});await delay(30);}}
  const signedIn=await send('/auth/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(login)});
  assert.equal(signedIn.status,503,signedIn.body);
  assert.equal(signedIn.headers['set-cookie'],undefined);
  assert.equal(JSON.parse(signedIn.body).service_id,c.identity.service_id);
  assert.equal(JSON.parse(signedIn.body).service_boot_id,control.result.service_boot_id);
  const session=await send(`/services/${c.identity.service_id}/api/v1/session`);
  assert.ok([401,503].includes(session.status));assert.equal(JSON.parse(session.body).service_id,c.identity.service_id);
  const draft=`/services/${s.identity.service_id}/api/v1/definitions/${crypto.randomUUID()}/draft`;
  const protectedDraft=await send(draft);
  assert.equal(protectedDraft.status,401,protectedDraft.body);assert.equal(JSON.parse(protectedDraft.body).code,'AUTH_REQUIRED');
  assert.equal(protectedDraft.headers['access-control-allow-origin'],origin);
  assert.equal((await send(draft,{headers:{Origin:'https://unqualified.fixture.invalid'}})).status,403);
  assert.equal((await send(`/services/${s.identity.service_id}/auth/local-permissions/v1`)).status,404);
  assert.equal((await send('/auth/local-pairing/v1')).status,404);
  assert.equal((await send('/internal/test')).status,404);
  control.child.kill('SIGTERM');
  assert.deepEqual(await control.exit,[0,null]);
  assert.equal(bootRows().find(row=>row.service_boot_id===control.result.service_boot_id)?.state,'stopped');
});
