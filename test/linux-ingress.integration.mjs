import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import https from 'node:https';
import crypto from 'node:crypto';
import {spawn,spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {once} from 'node:events';
import {setTimeout as delay} from 'node:timers/promises';

const issuer='39a80e85-7e89-4cfc-b9a4-d244de968241',seamer='04cce18e-03e0-4c14-bab5-aeb6401cb128';
const unlisted='2ed76ab6-4043-4c9f-8f5b-5dc2bb2ad065',wrongTls='c5e7e330-d7ab-463a-8f8a-6468732b09c8';
const management='manage.fixture.invalid',controllerName='controller.fixture.invalid',seamerName='seamer.fixture.invalid';
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const selection={contract_id:'leafseamer.api.v1.product9',contract_digest:'sha256:'+'2'.repeat(64)};
function command(binary,args,options){
  const result=spawnSync(binary,args,{encoding:'utf8',timeout:10000,...options});
  assert.equal(result.status,0,result.error?.message??result.stderr);return result.stdout;
}
async function listen(server){
  server.listen(0,'127.0.0.1');await once(server,'listening');return server.address().port;
}

test('Nginx 使用真实 TLS 提供静态 GUI 与固定逐服务路由', {skip:process.platform!=='linux',timeout:45000},async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-ingress-'));
  fs.chmodSync(root,0o755);
  const servers=[];let nginx,ended,diagnostic='';
  t.after(async()=>{
    if(nginx&&nginx.exitCode===null&&nginx.signalCode===null)nginx.kill('SIGQUIT');
    if(ended){const deadline=setTimeout(()=>nginx.kill('SIGKILL'),5000);await ended;clearTimeout(deadline);}
    await Promise.all(servers.map(server=>new Promise(resolve=>{server.close(resolve);server.closeAllConnections();})));
    assert.equal(path.dirname(root),os.tmpdir());fs.rmSync(root,{recursive:true,force:true});
  });
  function certificate(host){
    const cert=path.join(root,host+'.pem'),key=path.join(root,host+'.key');
    command('openssl',['req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN='+host,
      '-addext','subjectAltName=DNS:'+host,'-keyout',key,'-out',cert]);return {cert,key};
  }
  const site=certificate(management),controllerCert=certificate(controllerName),seamerCert=certificate(seamerName),seen=[];
  const makeUpstream=(service,tls)=>{
    const server=https.createServer({cert:fs.readFileSync(tls.cert),key:fs.readFileSync(tls.key)},(request,response)=>{
      const chunks=[];request.on('data',piece=>chunks.push(piece));request.on('end',()=>{
        const row={service,url:request.url,method:request.method,headers:request.headers,raw:request.rawHeaders,body:Buffer.concat(chunks).toString()};seen.push(row);
        if(request.url==='/api/v1/fault'){request.socket.destroy();return;}
        response.writeHead(request.url==='/api/v1/protected'?503:200,{'Content-Type':'application/json','Cache-Control':'public, max-age=100',
          'X-LeafSeamer-Contract':selection.contract_id,'X-LeafSeamer-Contract-Digest':selection.contract_digest});
        response.end(JSON.stringify({service,path:request.url}));
      });
    });
    server.on('upgrade',(request,socket)=>{
      seen.push({service,url:request.url,headers:request.headers});
      const accept=crypto.createHash('sha1').update(request.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
      socket.end('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: upgrade\r\nSec-WebSocket-Accept: '+accept+
        '\r\nSec-WebSocket-Protocol: '+request.headers['sec-websocket-protocol']+'\r\n\r\n');
    });
    servers.push(server);return server;
  };
  const controllerPort=await listen(makeUpstream(issuer,controllerCert)),seamerPort=await listen(makeUpstream(seamer,seamerCert));
  const reservation=net.createServer(),publicPort=await listen(reservation);await new Promise(resolve=>reservation.close(resolve));
  const authority=management+':'+publicPort,origin='https://'+authority,directory=path.join(root,'gui');
  fs.mkdirSync(path.join(directory,'assets'),{recursive:true});
  const plan={format:'leafseamer.linux-ingress/1',issuer_service_id:issuer,management:{address:'127.0.0.1',host:management,port:publicPort,
    certificate_file:site.cert,private_key_file:site.key},services:[
    {service_id:issuer,database_instance_id:crypto.randomUUID(),role:'controller',address:'127.0.0.1',port:controllerPort,server_name:controllerName,ca_file:controllerCert.cert},
    {service_id:seamer,database_instance_id:crypto.randomUUID(),role:'seamer',address:'127.0.0.1',port:seamerPort,server_name:seamerName,ca_file:seamerCert.cert},
    {service_id:wrongTls,database_instance_id:crypto.randomUUID(),role:'seamer',address:'127.0.0.1',port:seamerPort,server_name:'wrong.fixture.invalid',ca_file:seamerCert.cert},
  ]};
  const siteJson={format:'leafseamer.gui.site/2',service_id:issuer,database_instance_id:plan.services[0].database_instance_id,site_label:'测试入口',selection,
    seamer:{service_id:seamer,database_instance_id:plan.services[1].database_instance_id,base_url:origin+'/services/'+seamer,service_label:'Seamer'}};
  const assets={'index.html':'<!doctype html><title>LeafSeamer GUI</title>','assets/index-case.js':'console.log("LeafSeamer GUI")',
    'assets/index-case.css':'body { color: #000; }','site.json':JSON.stringify(siteJson),'SDK-LICENSE.txt':'test fixture'};
  for(const [name,body] of Object.entries(assets))fs.writeFileSync(path.join(directory,name),body);
  fs.writeFileSync(path.join(directory,'extra.txt'),'draft data');
  const manifest=JSON.stringify({format:'leafseamer.gui.build/1',sdk_manifest_sha256:'1'.repeat(64),selection,
    artifacts:Object.fromEntries(Object.entries(assets).map(([name,body])=>[name,hash(body)]))});
  fs.writeFileSync(path.join(directory,'gui-manifest.json'),manifest);
  plan.gui={directory,manifest_sha256:'sha256:'+hash(manifest)};
  const cli=fileURLToPath(new URL('../dist/linux-ingress.mjs',import.meta.url)),config=path.join(root,'plan.json'),nginxConfig=path.join(root,'nginx.conf');
  const writePlan=value=>fs.writeFileSync(config,JSON.stringify(value));
  const rejected=(value,error)=>{
    writePlan(value);const result=spawnSync(process.execPath,[cli,'--config',config],{encoding:'utf8'});
    assert.equal(result.status,1);assert.equal(JSON.parse(result.stderr).error,error);assert.equal(result.stdout,'');
  };
  rejected({...plan,issuer_service_id:seamer},'ingress_issuer');
  rejected({...plan,services:[...plan.services,plan.services[0]]},'ingress_service');
  rejected({...plan,management:{...plan.management,host:'manage.invalid;'}},'ingress_management');
  rejected({...plan,management:{...plan.management,host:'manage.invalid\n'}},'ingress_management');
  rejected({...plan,management:{...plan.management,host:'127.0.0.1'}},'ingress_management');
  fs.writeFileSync(path.join(directory,'site.json'),'unqualified');rejected(plan,'ingress_gui_digest');
  fs.writeFileSync(path.join(directory,'site.json'),assets['site.json']);
  writePlan(plan);fs.writeFileSync(nginxConfig,command(process.execPath,[cli,'--config',config]));
  command('nginx',['-t','-p',root+'/','-c',nginxConfig]);
  nginx=spawn('nginx',['-p',root+'/','-c',nginxConfig,'-g','daemon off;'],{stdio:['ignore','ignore','pipe']});
  ended=once(nginx,'close');nginx.stderr.setEncoding('utf8').on('data',chunk=>{diagnostic+=chunk;});

  function request(route,{method='GET',headers={},body}={}){
    return new Promise((resolve,reject)=>{
      const passed=Array.isArray(headers)?['Host',authority,...headers]:{Host:authority,...headers};
      const req=https.request({hostname:'127.0.0.1',port:publicPort,servername:management,path:route,ca:fs.readFileSync(site.cert),
        method,headers:passed,agent:false},response=>{
        const chunks=[];response.on('data',part=>chunks.push(part));response.on('error',reject);
        response.on('end',()=>resolve({status:response.statusCode,headers:response.headers,body:Buffer.concat(chunks).toString()}));
      });
      req.on('upgrade',(response,socket)=>{socket.destroy();resolve({status:response.statusCode,headers:response.headers});});
      req.on('error',reject);req.setTimeout(5000,()=>req.destroy(new Error('fixture_timeout')));req.end(body);
    });
  }
  const deadline=performance.now()+5000;
  for(;;){try{await request('/');break;}catch(error){if(performance.now()>deadline||nginx.exitCode!==null)throw new Error(diagnostic,{cause:error});await delay(25);}}
  assert.equal((await request('/')).body,assets['index.html']);
  assert.equal((await request('/assets/index-case.js')).body,assets['assets/index-case.js']);
  assert.match((await request('/site.json')).headers['content-security-policy'],/connect-src 'self'/);
  assert.equal((await request('/',{headers:{Host:'other.fixture.invalid'}})).status,421);
  for(const route of ['/internal/test','/auth/local-pairing/v1','/gui-manifest.json','/extra.txt','/unconfigured',
    '/.well-known/leafseamer-contracts',`/services/${unlisted}/api/v1/drafts`,`/services/${seamer}/auth/sessions`,`/services/${seamer}/internal/test`])
    assert.equal((await request(route)).status,404,route);
  const auth=await request('/auth/sessions',{headers:{Cookie:'fixture-cookie','X-Forwarded-Host':'other.fixture.invalid',Origin:origin}});
  assert.deepEqual(JSON.parse(auth.body),{service:issuer,path:'/auth/sessions'});
  assert.equal(seen.at(-1).headers.host,authority);assert.equal(seen.at(-1).headers.origin,origin);
  assert.equal(seen.at(-1).headers.cookie,'fixture-cookie');assert.equal(seen.at(-1).headers['x-forwarded-host'],undefined);
  assert.equal(JSON.parse((await request('/api/v1/devices')).body).service,issuer);
  const qualified=await request(`/services/${seamer}/api/v1/drafts?window=3`,{headers:['Cookie','fixture-cookie','Origin',origin,
    'X-LeafSeamer-Contract',selection.contract_id,'X-LeafSeamer-Contract',selection.contract_id]});
  assert.deepEqual(JSON.parse(qualified.body),{service:seamer,path:'/api/v1/drafts?window=3'});
  assert.equal(qualified.headers['x-leafseamer-contract-digest'],selection.contract_digest);
  assert.equal(qualified.headers['cache-control'],'no-store');assert.equal(seen.at(-1).headers.cookie,undefined);
  assert.equal(seen.at(-1).raw.filter((value,index)=>index%2===0&&value.toLowerCase()==='x-leafseamer-contract').length,2);
  assert.equal(JSON.parse((await request(`/services/${seamer}/.well-known/leafseamer-contracts`)).body).path,'/.well-known/leafseamer-contracts');
  assert.equal((await request(`/services/${seamer}/.well-known/leafseamer-contracts`,{method:'POST'})).status,405);
  const ws=await request(`/services/${seamer}/api/v1/events`,{headers:{Upgrade:'websocket',Connection:'Upgrade',Origin:origin,
    'Sec-WebSocket-Key':crypto.randomBytes(16).toString('base64'),'Sec-WebSocket-Version':'13','Sec-WebSocket-Protocol':'leafseamer.events'}});
  assert.equal(ws.status,101);assert.equal(ws.headers['sec-websocket-protocol'],'leafseamer.events');assert.equal(seen.at(-1).headers.origin,origin);
  const before=seen.length;
  assert.equal((await request(`/services/${wrongTls}/api/v1/drafts`)).status,502);assert.equal(seen.length,before);
  assert.equal((await request(`/services/${seamer}/api/v1/fault`,{method:'POST',body:'one-write'})).status,502);
  assert.deepEqual(seen.slice(before).map(({service,method,body})=>[service,method,body]),[[seamer,'POST','one-write']]);
  assert.equal((await request(`/services/${seamer}/api/v1/protected`)).status,503);
  assert.ok(!diagnostic.includes('fixture-cookie')&&!diagnostic.includes('one-write')&&!diagnostic.includes('window=3'));
});
