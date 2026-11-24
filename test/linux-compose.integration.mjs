import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import https from 'node:https';
import net from 'node:net';
import {once} from 'node:events';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {DatabaseSync} from 'node:sqlite';

const images={controller:process.env.LEAFSEAMER_COMPOSE_CONTROLLER_IMAGE,seamer:process.env.LEAFSEAMER_COMPOSE_SEAMER_IMAGE,nginx:process.env.LEAFSEAMER_COMPOSE_NGINX_IMAGE};
const guiRoot=process.env.LEAFSEAMER_COMPOSE_GUI_ROOT;
const file=name=>fileURLToPath(new URL(name,import.meta.url));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const parseFile=name=>JSON.parse(fs.readFileSync(name,'utf8'));
function run(program,args,timeout=30000){
  const result=spawnSync(program,args,{encoding:'utf8',timeout});
  assert.equal(result.status,0,result.stderr||result.error?.message);
  return result.stdout;
}
const docker=(...args)=>run('docker',args,90000);

test('Compose 从固定镜像启动双服务和 Nginx 并隔离端口、TLS 及数据',{
  skip:process.platform!=='linux'||!guiRoot||Object.values(images).some(value=>!value),timeout:180000
},async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-compose-'));
  const output=path.join(root,'generation'),planPath=path.join(root,'plan.json'),composePath=path.join(output,'compose.json');
  const project='leafseamer-test-'+crypto.randomBytes(6).toString('hex');
  const compose=(...args)=>docker('compose','--project-name',project,'--file',composePath,...args);
  let created=false;
  t.after(()=>{
    try{if(created)compose('down','--timeout','8');}
    finally{assert.equal(path.dirname(root),os.tmpdir());fs.rmSync(root,{recursive:true,force:true});}
  });
  fs.chmodSync(root,0o755);
  const uid=process.getuid()||1000,gid=process.getgid()||1000,user=uid+':'+gid;
  function owned(name){if(process.getuid()===0)fs.chownSync(name,uid,gid);}
  const listener=net.createServer();
  listener.listen(0,'127.0.0.1');
  await once(listener,'listening');
  const port=listener.address().port;
  await new Promise(resolve=>listener.close(resolve));
  const host='manage.fixture.invalid',authority=host+':'+port,origin='https://'+authority;
  const range='10.234.'+crypto.randomInt(1,255);
  const login={login:'compose.fixture',password:'Synthetic-compose-test-password-632'};
  function certificates(role,serverName){
    const certificate_file=path.join(root,role+'.pem'),private_key_file=path.join(root,role+'.key');
    run('openssl',['req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN='+serverName,
      '-addext','subjectAltName=DNS:'+serverName,'-keyout',private_key_file,'-out',certificate_file]);
    owned(private_key_file);
    return {certificate_file,private_key_file};
  }
  function bootstrap(role,directory,extraMounts,args){
    return docker('run','--rm','--pull','never','--network','none','--user',user,'--read-only','--cap-drop','ALL',
      '--mount','type=bind,source='+directory+',target=/var/lib/leafseamer',...extraMounts,
      '--entrypoint','/usr/local/bin/node',images[role],...args);
  }
  function setupService(role,number){
    const data_dir=path.join(root,role);
    fs.mkdirSync(data_dir,{mode:0o700});owned(data_dir);
    let identity;
    if(role==='controller'){
      const config=path.join(root,'controller-init.json');
      fs.writeFileSync(config,JSON.stringify({package_root:'/opt/leafseamer',data_dir:'/var/lib/leafseamer',login}),{mode:0o600});owned(config);
      const seed=bootstrap(role,data_dir,['--mount','type=bind,source='+file('./fixtures/linux-ingress-service.mjs')+',target=/tmp/seed.mjs,readonly',
        '--mount','type=bind,source='+config+',target=/tmp/config.json,readonly'],['/tmp/seed.mjs','/tmp/config.json']);
      identity=JSON.parse(seed).identity;
    }else{
      const args=['/opt/leafseamer/dist/cli.mjs'],directory=['--data-dir','/var/lib/leafseamer'];
      identity=JSON.parse(bootstrap(role,data_dir,[],[...args,'init-storage',...directory]));
      bootstrap(role,data_dir,[],[...args,'migrate-storage',...directory,'--to-revision','33']);
    }
    const server_name=role+'.fixture.invalid',tls=certificates(role,server_name);
    return {image:images[role],uid,gid,address:range+'.'+number,data_dir,server_name,
      service_id:identity.service_id,database_instance_id:identity.database_instance_id,...tls,ca_file:tls.certificate_file};
  }
  const controller=setupService('controller',2),seamer=setupService('seamer',3);
  const management={bind_address:'127.0.0.1',host,port,...certificates('management',host)};
  const directory=path.join(root,'gui');
  fs.mkdirSync(directory);
  const manifest=parseFile(path.join(guiRoot,'gui-manifest.json'));
  const site={format:'leafseamer.gui.site/2',service_id:controller.service_id,database_instance_id:controller.database_instance_id,
    site_label:'套件联调',selection:manifest.selection,seamer:{service_id:seamer.service_id,database_instance_id:seamer.database_instance_id,
      base_url:origin+'/services/'+seamer.service_id,service_label:'Seamer'}};
  for(const [name,digest] of Object.entries(manifest.artifacts)){
    if(name==='site.json')continue;
    const bytes=fs.readFileSync(path.join(guiRoot,name));
    assert.equal(hash(bytes),digest);
    const destination=path.join(directory,name);
    fs.mkdirSync(path.dirname(destination),{recursive:true});
    fs.writeFileSync(destination,bytes);
  }
  const siteBytes=JSON.stringify(site)+'\n';
  fs.writeFileSync(path.join(directory,'site.json'),siteBytes);
  manifest.artifacts['site.json']=hash(siteBytes);
  const manifestBytes=JSON.stringify(manifest);
  fs.writeFileSync(path.join(directory,'gui-manifest.json'),manifestBytes);
  const plan={format:'leafseamer.linux-compose-protected/1',subnet:range+'.0/29',management,controller,seamer,
    nginx:{image:images.nginx,uid,gid,address:range+'.4'},gui:{directory,manifest_sha256:'sha256:'+hash(manifestBytes)}};
  const aliasOfKey=path.join(root,'ca-alias.pem');
  fs.linkSync(controller.private_key_file,aliasOfKey);
  const generate=['--disallow-code-generation-from-strings',file('../dist/linux-compose.mjs'),'--config',planPath,'--output',output];
  for(const [invalid,code]of [
    [{...plan,controller:{...controller,image:'controller:latest'}},'compose_image_or_user'],
    [{...plan,seamer:{...seamer,address:controller.address}},'compose_network'],
    [{...plan,seamer:{...seamer,data_dir:controller.data_dir}},'compose_path_overlap'],
    [{...plan,seamer:{...seamer,ca_file:controller.private_key_file}},'compose_tls_scope'],
    [{...plan,seamer:{...seamer,ca_file:aliasOfKey}},'compose_tls_scope'],
    [{...plan,seamer:{...seamer,database_instance_id:controller.database_instance_id}},'compose_identity']
  ]){
    fs.writeFileSync(planPath,JSON.stringify(invalid));
    const bad=spawnSync(process.execPath,generate,{encoding:'utf8',timeout:10000});
    assert.equal(bad.status,1,bad.stderr);
    assert.equal(JSON.parse(bad.stderr).error,code);
    assert.equal(fs.existsSync(output),false);
  }
  fs.writeFileSync(planPath,JSON.stringify(plan));
  run(process.execPath,generate);
  const composeDigest=hash(fs.readFileSync(composePath));
  assert.equal(spawnSync(process.execPath,generate,{encoding:'utf8',timeout:10000}).status,1);
  assert.equal(hash(fs.readFileSync(composePath)),composeDigest);
  assert.deepEqual(compose('config','--services').trim().split('\n').sort(),['controller','nginx','seamer']);
  created=true;
  compose('up','--detach','--no-build','--pull','never');
  const containers=Object.fromEntries(['controller','seamer','nginx'].map(role=>{
    const id=compose('ps','--all','--quiet',role).trim();
    assert.ok(id,role);
    return [role,JSON.parse(docker('inspect',id))[0]];
  }));
  for(const [role,container] of Object.entries(containers)){
    assert.equal(container.Image,docker('image','inspect','--format','{{.Id}}',images[role]).trim());
    assert.equal(container.Config.User,user);
    assert.equal(container.HostConfig.ReadonlyRootfs,true);
    assert.equal(container.HostConfig.Privileged,false);
    assert.equal(container.HostConfig.RestartPolicy.Name,'no');
    assert.deepEqual(container.HostConfig.CapDrop,['ALL']);
    assert.ok(container.HostConfig.SecurityOpt.some(option=>option.startsWith('no-new-privileges')));
    const bindings=container.HostConfig.PortBindings??{};
    if(role==='nginx'){
      assert.deepEqual(bindings,{'8443/tcp':[{HostIp:'127.0.0.1',HostPort:String(port)}]});
      assert.equal(container.Mounts.every(value=>!value.RW),true);
      assert.ok(!container.Mounts.some(value=>[controller.private_key_file,seamer.private_key_file].includes(value.Source)));
    }else{
      assert.deepEqual(bindings,{});
      assert.deepEqual(container.Mounts.filter(value=>value.RW).map(value=>value.Destination),['/var/lib/leafseamer']);
      assert.deepEqual(container.Mounts.filter(value=>value.Destination.endsWith('/private-key.pem')).map(value=>value.Source),[plan[role].private_key_file]);
      assert.equal(Object.keys(container.NetworkSettings.Networks).length,1);
    }
  }
  const {contract_id,contract_digest}=manifest.selection;
  function send(route,{method='GET',headers={},body}={}){
    return new Promise((resolve,reject)=>{
      const request=https.request({hostname:'127.0.0.1',port,servername:host,ca:fs.readFileSync(management.certificate_file),
        path:route,method,headers:{Host:authority,Origin:origin,'X-LeafSeamer-Contract':contract_id,'X-LeafSeamer-Contract-Digest':contract_digest,...headers},
        timeout:3000,agent:false},response=>{
        const chunks=[];
        response.on('data',chunk=>chunks.push(chunk));response.on('error',reject);
        response.on('end',()=>resolve({status:response.statusCode,headers:response.headers,body:Buffer.concat(chunks)}));
      });
      request.on('error',reject);request.on('timeout',()=>request.destroy(new Error('compose_https_timeout')));request.end(body);
    });
  }
  const draft='/services/'+seamer.service_id+'/api/v1/definitions/'+crypto.randomUUID()+'/draft';
  const deadline=performance.now()+15000;
  let signedIn,protectedDraft;
  for(;;){
    try{
      assert.deepEqual(JSON.parse((await send('/site.json')).body),site);
      signedIn=await send('/auth/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(login)});
      protectedDraft=await send(draft);
      if(signedIn.status===503&&protectedDraft.status===401)break;
      throw new Error('Controller '+signedIn.status+' Seamer '+protectedDraft.status);
    }catch(error){
      if(performance.now()>=deadline)throw new Error(compose('logs','--no-color'),{cause:error});
      await delay(100);
    }
  }
  assert.equal(signedIn.headers['set-cookie'],undefined);
  assert.equal(JSON.parse(signedIn.body).service_id,controller.service_id);
  assert.equal(JSON.parse(protectedDraft.body).code,'AUTH_REQUIRED');
  assert.equal((await send(draft,{headers:{Origin:'https://wrong.fixture.invalid'}})).status,403);
  const script=Object.keys(manifest.artifacts).find(name=>name.endsWith('.js'));
  assert.equal(hash((await send('/')).body),manifest.artifacts['index.html']);
  assert.equal(hash((await send('/'+script)).body),manifest.artifacts[script]);
  const [backend]=Object.values(containers.seamer.NetworkSettings.Networks);
  assert.equal(JSON.parse(docker('network','inspect',backend.NetworkID))[0].Internal,true);
  compose('stop','--timeout','8','nginx');
  for(const role of ['controller','seamer']){
    const [state]=JSON.parse(docker('inspect',containers[role].Id));
    assert.equal(state.State.Running,true);
    assert.equal(state.State.StartedAt,containers[role].State.StartedAt);
  }
  compose('stop','--timeout','8');
  for(const role of ['controller','seamer']){
    const db=new DatabaseSync(path.join(plan[role].data_dir,role+'.sqlite'),{readOnly:true});
    try{
      assert.equal(db.prepare('SELECT count(*) AS count FROM service_boot WHERE state=?').get('started').count,0);
      assert.equal(db.prepare('SELECT service_id FROM service_state').get().service_id,plan[role].service_id);
    }finally{db.close();}
  }
  compose('down','--timeout','8');
  assert.equal(compose('ps','--all','--quiet').trim(),'');
  created=false;
});
