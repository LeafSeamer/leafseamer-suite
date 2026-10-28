// 仅启动独立浏览器配置和本机合成服务，固定快照必须先通过交接校验。
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const arg=n=>{const i=process.argv.indexOf(n);if(i<0)throw new Error('需要'+n);return path.resolve(process.argv[i+1]);};
const sdk=arg('--snapshot'),browserPath=arg('--browser'),output=arg('--output'),profile=arg('--profile');
assert(!fs.existsSync(profile),'需要全新的浏览器配置目录');fs.mkdirSync(profile,{recursive:true});
const hash=b=>crypto.createHash('sha256').update(b).digest('hex'),manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json')));
const assets=new Map(),artifactHashes={},sourceHashes={};
for(const [p,h] of Object.entries(manifest.snapshot_files)) {
  const raw=fs.readFileSync(path.join(sdk,p));assert.equal(hash(raw),h,p);
  if(!p.endsWith('.mjs')&&!p.endsWith('.json'))continue;
  let bytes=raw;
  if(p==='contracts/panel-wire/runtime-tests.mjs') {
    const line="      await reject('空正文拒共享缓冲:'+i,()=>decoder.assertEmpty(new Uint8Array(new SharedArrayBuffer(0)),b.handle),'shared_buffer');";
    const text=raw.toString('utf8');assert.equal(text.split(line).length,2,'转换边界');
    bytes=Buffer.from(text.replace(line,"      if(typeof SharedArrayBuffer!=='undefined')"+line.trim()));
  }
  assets.set('/'+p,bytes);artifactHashes[p]=hash(bytes);sourceHashes[p]=h;
}
for(const name of ['browser.html','browser.mjs','worker.mjs','suite.mjs']) {
  const raw=fs.readFileSync(path.join(root,name));assets.set('/'+name,raw);artifactHashes[name]=hash(raw);
}
const {createHttpAdapter}=await import(pathToFileURL(path.join(sdk,'contracts/panel-http/adapter.mjs')).href);
const adapter=createHttpAdapter(manifest.selection),cases=JSON.parse(fs.readFileSync(path.join(sdk,'contracts/panel-http/panel-cases.json'))).cases;
const csp="default-src 'none'; script-src 'self'; worker-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'";
const servers=[],contexts={},failures=[],reports={},requests={};
for(const mode of ['plain','isolated']) {
  const headers={'Content-Security-Policy':csp,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
    ...(mode==='isolated'?{'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin'}:{})};
  requests[mode]=new Set();contexts[mode]={page:0,worker:0};
  const server=http.createServer(async(req,res)=>{
    for(const [k,v] of Object.entries(headers))res.setHeader(k,v);
    try {
      const bridge=/^\/bridge\/(page|worker)\/(controller|seamer)\/(response|unavailable|old_result)(\/api\/.*)$/.exec(req.url);
      if(req.method==='POST'&&bridge) {
        const [,context,authority,result,target]=bridge;contexts[mode][context]++;
        const chunks=[];let size=0;for await(const part of req){size+=part.length;assert(size<=8*1024*1024);chunks.push(part);}
        const rawHeaders=Array.from({length:req.rawHeaders.length/2},(_,i)=>req.rawHeaders.slice(i*2,i*2+2));
        const handle=adapter.prepareRequest(authority,'POST',target,rawHeaders),decoded=await adapter.decodeRequest(Buffer.concat(chunks),handle);
        assert.equal(handle.operation_id,'invokePanelMethod');assert.equal(handle.authorization_granted,false);
        const fixture=cases.find(c=>c.authority===authority&&c.method===decoded.value.intent.method);assert(fixture);assert.deepEqual(decoded.value,fixture.request);
        res.writeHead(200,{'Cache-Control':'no-store','Content-Type':'application/json','X-LeafSeamer-Contract':manifest.selection.contract_id,'X-LeafSeamer-Contract-Digest':manifest.selection.contract_digest});
        res.end(JSON.stringify(fixture[result]));return;
      }
      const target=req.url==='/'+mode?'/browser.html':req.url;
      if(req.method!=='GET'||!assets.has(target)){res.writeHead(404);res.end();return;}
      requests[mode].add(target.slice(1));res.setHeader('Content-Type',target.endsWith('.html')?'text/html; charset=utf-8':target.endsWith('.mjs')?'text/javascript; charset=utf-8':'application/json');res.end(assets.get(target));
    }catch(e){failures.push(e.message);res.writeHead(400);res.end();}
  });
  servers.push(server);await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  reports[mode]={headers,url:'http://127.0.0.1:'+server.address().port+'/'+mode};
}
const child=spawn(browserPath,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking',
  '--remote-debugging-port=0','--remote-debugging-address=127.0.0.1','--user-data-dir='+profile,'about:blank'],{stdio:'ignore',windowsHide:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));let ws;
try {
  const active=path.join(profile,'DevToolsActivePort');const started=Date.now();
  while(!fs.existsSync(active)){assert(Date.now()-started<30000,'浏览器启动超时');assert(child.exitCode===null,'浏览器已退出');await sleep(200);}
  const [port,endpoint]=fs.readFileSync(active,'utf8').trim().split(/\r?\n/);
  ws=new WebSocket('ws://127.0.0.1:'+port+endpoint);await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
  let id=0;const pending=new Map();
  ws.addEventListener('message',event=>{const value=JSON.parse(event.data);if(!value.id)return;const item=pending.get(value.id);if(!item)return;pending.delete(value.id);clearTimeout(item.timer);value.error?item.reject(new Error(JSON.stringify(value.error))):item.resolve(value.result);});
  const command=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(new Error('CDP超时:'+method));},30000);pending.set(n,{resolve,reject,timer});ws.send(JSON.stringify({id:n,method,params,...(sessionId?{sessionId}:{})}));});
  const browser=await command('Browser.getVersion');
  for(const mode of ['plain','isolated']) {
    const {targetId}=await command('Target.createTarget',{url:reports[mode].url});
    const {sessionId}=await command('Target.attachToTarget',{targetId,flatten:true});let result;const start=Date.now();
    while(!result) {
      assert(Date.now()-start<120000,'浏览器验收超时:'+mode);
      const value=await command('Runtime.evaluate',{expression:'globalThis.__panelDone',returnByValue:true},sessionId);
      result=value.result?.value;if(!result)await sleep(500);
    }
    assert(result.all_passed,JSON.stringify(result));delete reports[mode].url;reports[mode].report=result;
    reports[mode].requests=[...requests[mode]].sort();reports[mode].http_exchanges=contexts[mode];
    assert.deepEqual(contexts[mode],{page:105,worker:105});
    console.log(JSON.stringify({mode,all_passed:true,page_checks:result.page.cases_passed,worker_checks:result.worker.cases_passed}));
    await command('Target.closeTarget',{targetId});
  }
  assert.deepEqual(failures,[]);
  const own=Object.fromEntries(['run-browser.mjs','browser.html','browser.mjs','worker.mjs','suite.mjs','manifest.json'].map(n=>[n,hash(fs.readFileSync(path.join(root,n)))]));
  const used=new Set(Object.values(reports).flatMap(r=>r.requests));
  const result={format:'sdk-panel-browser/1',approved:false,runtime_ready:false,all_passed:true,sdk_commit:manifest.sdk_main_commit,selection:manifest.selection,
    browser:{product:browser.product,revision:browser.revision,js_version:browser.jsVersion,user_agent:browser.userAgent,executable_sha256:hash(fs.readFileSync(browserPath))},
    node:{version:process.version,executable_sha256:hash(fs.readFileSync(process.execPath))},own_inputs:own,
    served_artifacts:Object.fromEntries([...used].sort().map(p=>[p,artifactHashes[p]])),source_artifacts:Object.fromEntries([...used].filter(p=>sourceHashes[p]).sort().map(p=>[p,sourceHashes[p]])),
    reports,http_exchanges:420,production_authorization_executed:false,product_business_executed:false,device_executed:false};
  fs.writeFileSync(output,JSON.stringify(result,null,2)+'\n');await command('Browser.close');
}finally {ws?.close();if(child.exitCode===null)child.kill();for(const s of servers){s.closeAllConnections();await new Promise(r=>s.close(r));}}
