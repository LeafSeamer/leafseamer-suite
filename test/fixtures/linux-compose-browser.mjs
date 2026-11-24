import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash,X509Certificate} from 'node:crypto';

async function verifyLinuxComposeBrowser({origin,management,login,seamer}){
  const {LEAFSEAMER_TEST_COMPOSE_BROWSER:executablePath,LEAFSEAMER_TEST_COMPOSE_PLAYWRIGHT:playwright,
    LEAFSEAMER_TEST_COMPOSE_SCREENSHOTS:output}=process.env;
  assert.ok([executablePath,playwright,output].every(value=>value&&path.isAbsolute(value)),'browser fixture paths must be absolute');
  const {chromium}=createRequire(import.meta.url)(playwright);
  const cert=new X509Certificate(fs.readFileSync(management.certificate_file));
  const pin=createHash('sha256').update(cert.publicKey.export({type:'spki',format:'der'})).digest('base64');
  const hostname=new URL(origin).hostname;
  const browser=await chromium.launch({executablePath,headless:true,args:[
    '--ignore-certificate-errors-spki-list='+pin,'--host-resolver-rules=MAP '+hostname+' 127.0.0.1'
  ]});
  fs.mkdirSync(output,{recursive:true,mode:0o700});
  const errors=[],unexpected=[],traffic=[];
  let loseResponse=false,committed=null;
  try{
    const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'zh-CN'});
    const page=await context.newPage();
    page.setDefaultTimeout(10000);
    const seamerPath='/services/'+seamer.service_id+'/api/v1',definitions=seamerPath+'/definitions';
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',event=>{
      if(!['warning','error'].includes(event.type()))return;
      const {url}=event.location(),message=event.text();
      if(url===origin+'/favicon.ico'||loseResponse&&url===origin+definitions&&/ERR_FAILED/.test(message))return;
      unexpected.push(message);
    });
    page.on('request',request=>{
      const target=new URL(request.url());
      traffic.push({origin:target.origin,path:target.pathname,method:request.method()});
    });
    const response=(target,method)=>page.waitForResponse(value=>value.url()===origin+target&&value.request().method()===method);
    const loginHeading=page.getByRole('heading',{name:'登录工作台',exact:true});
    const landing=await page.goto(origin);
    assert.equal(landing.status(),200);
    assert.equal(new URL(page.url()).origin,origin);
    assert.match(await page.title(),/LeafSeamer/);
    assert.match(landing.headers()['content-security-policy'],/connect-src 'self';/);
    await loginHeading.waitFor();
    assert.equal(await page.locator('vite-error-overlay').count(),0);
    async function signIn(){
      await page.getByLabel('用户名',{exact:true}).fill(login.login);
      await page.getByLabel('密码',{exact:true}).fill(login.password);
      const signed=response('/auth/sessions','POST');
      await page.getByRole('button',{name:'登录',exact:true}).click();
      assert.equal((await signed).status(),201);
    }
    await signIn();
    const [session]=await context.cookies();
    assert.ok(session?.secure&&session.httpOnly);
    assert.equal(session.sameSite,'Strict');
    assert.equal(session.path,'/auth');
    await page.getByRole('button',{name:'当前会话',exact:true}).click();
    const refreshed=response('/auth/sessions/refresh','POST');
    await page.getByRole('button',{name:'续期会话',exact:true}).click();
    assert.equal((await refreshed).status(),200);
    async function openDrafts(){
      await page.getByRole('button',{name:'自动化',exact:true}).click();
      await page.getByRole('heading',{name:'自动化草稿',exact:true}).waitFor();
    }
    const content={program:{kind:'rule',trigger_binding_id:'fixture-trigger',condition:{kind:'literal',value:true},
      groups:[{mode:'sequence',steps:[{step_id:'fixture-delay',depends_on:[],required:true,failure_policy:'stop',
        kind:'delay',delay_ms:0,max_lateness_ms:100}]}]},selections:[],policy_ref:{kind:'policy',
      scope:{authority_service_id:seamer.service_id,database_instance_id:seamer.database_instance_id},
      object_id:'fixture-policy',revision:'1',digest:'sha256:'+'a'.repeat(64)}};
    await openDrafts();
    await page.getByLabel('名称',{exact:true}).fill('Compose 浏览器草稿');
    await page.getByLabel('定义内容文档',{exact:true}).fill(JSON.stringify(content));
    let writeFailure=null;
    const interception=await context.newCDPSession(page);
    await interception.send('Fetch.enable',{patterns:[{urlPattern:origin+definitions,requestStage:'Response'}]});
    interception.on('Fetch.requestPaused', async ({requestId,request,responseStatusCode})=>{
      if(request.method!=='POST'){await interception.send('Fetch.continueRequest',{requestId});return;}
      try{
        const {body,base64Encoded}=await interception.send('Fetch.getResponseBody',{requestId});
        const text=base64Encoded?Buffer.from(body,'base64').toString('utf8'):body;
        assert.equal(responseStatusCode,201,text);
        committed=JSON.parse(text);
        loseResponse=true;
      }catch(error){writeFailure=error;}
      await interception.send('Fetch.failRequest',{requestId,errorReason:'Failed'});
    });
    await page.getByRole('button',{name:'创建草稿',exact:true}).click();
    await loginHeading.waitFor();
    assert.ifError(writeFailure);
    assert.ok(committed);
    await interception.send('Fetch.disable');
    await interception.detach();
    loseResponse=false;
    const countWrites=()=>traffic.filter(event=>event.method==='POST'&&event.path===definitions).length;
    assert.equal(countWrites(),1);
    await page.reload();
    await signIn();
    await openDrafts();
    const pending=await page.evaluate(()=>Object.values(sessionStorage));
    assert.equal(pending.length,1);
    assert.doesNotMatch(pending[0],/access_token|policy_ref|password/);
    assert.equal(await page.getByRole('button',{name:'创建草稿',exact:true}).isDisabled(),true);
    await page.getByRole('button',{name:'查询原请求',exact:true}).click();
    const current=page.getByRole('button',{name:'读取当前草稿',exact:true});
    await current.waitFor();
    const reading=response(definitions+'/'+committed.definition_id+'/draft','GET');
    await current.click();
    const loaded=await reading;
    assert.equal(loaded.status(),200);
    assert.equal((await loaded.json()).definition_id,committed.definition_id);
    await page.getByText(committed.definition_id,{exact:true}).waitFor();
    assert.equal(await page.getByLabel('名称',{exact:true}).inputValue(),'Compose 浏览器草稿');
    assert.equal(countWrites(),1);
    const storage=await page.evaluate(()=>({cookie:document.cookie,local:Object.keys(localStorage),session:Object.keys(sessionStorage)}));
    assert.deepEqual(storage,{cookie:'',local:[],session:[]});
    assert.ok(traffic.every(event=>event.origin===origin));
    await page.screenshot({path:path.join(output,'compose-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(output,'compose-mobile.png')});
    await page.getByRole('button',{name:'当前会话',exact:true}).click();
    const logout=response('/auth/sessions/current','DELETE');
    await page.getByRole('button',{name:'退出登录',exact:true}).click();
    assert.equal((await logout).status(),202);
    await loginHeading.waitFor();
    assert.deepEqual(errors,[]);
    assert.deepEqual(unexpected,[]);
    return committed.definition_id;
  }finally{await browser.close();}
}

const config=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(await verifyLinuxComposeBrowser(config))+'\n');
