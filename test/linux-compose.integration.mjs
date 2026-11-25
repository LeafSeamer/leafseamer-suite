import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import https from 'node:https';
import net from 'node:net';
import dgram from 'node:dgram';
import {once} from 'node:events';
import {spawn,spawnSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {DatabaseSync} from 'node:sqlite';
import {inflateRawSync} from 'node:zlib';

const images={controller:process.env.LEAFSEAMER_COMPOSE_CONTROLLER_IMAGE,seamer:process.env.LEAFSEAMER_COMPOSE_SEAMER_IMAGE,nginx:process.env.LEAFSEAMER_COMPOSE_NGINX_IMAGE};
const guiRoot=process.env.LEAFSEAMER_COMPOSE_GUI_ROOT;
const socketPath=process.env.LEAFSEAMER_TEST_DOCKER_SOCKET,pidFile=process.env.LEAFSEAMER_TEST_DOCKER_PID_FILE;
const file=name=>fileURLToPath(new URL(name,import.meta.url));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const parseFile=name=>JSON.parse(fs.readFileSync(name,'utf8'));
function run(program,args,timeout=30000){
  const result=spawnSync(program,args,{encoding:'utf8',timeout});
  assert.equal(result.status,0,result.stderr||result.error?.message);
  return result.stdout;
}
const docker=(...args)=>run('docker',args,90000);

async function startReferenceNTS(t,root,name,{certificate_file,private_key_file}){
  const udp=dgram.createSocket('udp4'),tcp=net.createServer();
  udp.bind(0,'127.0.0.1');tcp.listen(0,'127.0.0.1');
  await Promise.all([once(udp,'listening'),once(tcp,'listening')]);
  const port=udp.address().port,keyPort=tcp.address().port;
  await Promise.all([new Promise(resolve=>udp.close(resolve)),new Promise(resolve=>tcp.close(resolve))]);
  const config=path.join(root,'reference-nts.conf');
  const commandSocket=path.join(fs.mkdtempSync(path.join(root,'nts-control-')),'server.sock');
  fs.writeFileSync(config,['user root','bindaddress 127.0.0.1','allow 127.0.0.1','cmdport 0',
    'bindcmdaddress '+commandSocket,'pidfile '+path.join(root,'reference-nts.pid'),
    'port '+port,'ntsport '+keyPort,'local stratum 9','ntsservercert '+certificate_file,'ntsserverkey '+private_key_file].join('\n')+'\n',
  {mode:0o600});
  const service=spawn('/usr/sbin/chronyd',['-d','-x','-f',config],{stdio:['ignore','ignore','pipe']});
  const exited=once(service,'close');
  let diagnostics='';
  service.stderr.setEncoding('utf8').on('data',chunk=>{diagnostics=(diagnostics+chunk).slice(-8192);});
  t.after(async()=>{if(service.exitCode===null)service.kill();await exited;});
  const deadline=performance.now()+4000;
  for(;;){
    assert.ok(service.exitCode===null&&performance.now()<deadline,'NTS server unavailable '+diagnostics);
    const probe=net.createConnection(keyPort,'127.0.0.1');
    try{await once(probe,'connect');break;}catch{await delay(100);}finally{probe.destroy();}
  }
  const network={authentication:'nts',server_name:name,key_endpoint:'127.0.0.1:'+keyPort,
    root_der:[new crypto.X509Certificate(fs.readFileSync(certificate_file)).raw.toString('base64url')],
    default_target:{name:'127.0.0.1',port},targets:[{name:'127.0.0.1',port,endpoint:'127.0.0.1:'+port}]};
  const stats=()=>run('/usr/bin/chronyc',['-u','root','-n','-h',commandSocket,'serverstats'],1000);
  assert.ok(fs.existsSync(commandSocket),diagnostics);
  stats();
  return {network,stats,count(){
    const count=/^Authenticated NTP packets\s*:\s*(\d+)$/m.exec(stats());
    assert.ok(count,'Chrony authenticated packet counter missing');
    return Number(count[1]);
  }};
}

test('Compose 从固定镜像启动双服务和 Nginx 并隔离端口、TLS 及数据',{
  skip:process.platform!=='linux'||!guiRoot||Object.values(images).some(value=>!value),timeout:180000
},async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-compose-'));
  const output=path.join(root,'generation'),planPath=path.join(root,'plan.json');
  let composePath=path.join(output,'compose.json'),project='leafseamer-test-'+crypto.randomBytes(6).toString('hex');
  const compose=(...args)=>docker('compose','--project-name',project,'--file',composePath,...args);
  let created=false,managedHost,extraContainer;
  const groups=[];
  t.after(async()=>{
    try{
      await managedHost?.close();
      if(extraContainer)docker('container','rm','--force',extraContainer);
      if(created)compose('down','--timeout','8');
    }
    finally{
      for(const group of groups)fs.rmdirSync(group);
      assert.equal(path.dirname(root),os.tmpdir());fs.rmSync(root,{recursive:true,force:true});
    }
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
  const referenceExecutable=process.env.LEAFSEAMER_TEST_COMPOSE_REFERENCE_PROVIDER,legacyReference={};
  let enrollment;
  function certificates(role,serverName,loopback=false){
    const certificate_file=path.join(root,role+'.pem'),private_key_file=path.join(root,role+'.key');
    run('openssl',['req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN='+serverName,
      '-addext','subjectAltName=DNS:'+serverName+(loopback?',IP:127.0.0.1':''),'-keyout',private_key_file,'-out',certificate_file]);
    owned(private_key_file);
    return {certificate_file,private_key_file};
  }
  function bootstrap(role,directory,extraMounts,args){
    return docker('run','--rm','--pull','never','--network','none','--user',user,'--read-only','--cap-drop','ALL',
      '--tmpfs','/tmp:rw,noexec,nosuid,nodev,mode=1777,size=67108864',
      '--mount','type=bind,source='+directory+',target=/var/lib/leafseamer',...extraMounts,
      '--entrypoint','/usr/local/bin/node',images[role],...args);
  }
  function setupService(role,number){
    const data_dir=path.join(root,role);
    fs.mkdirSync(data_dir,{mode:0o700});owned(data_dir);
    let identity;
    const args=['/opt/leafseamer/dist/cli.mjs'],directoryArgs=['--data-dir','/var/lib/leafseamer'];
    if(role==='controller'){
      const config=path.join(root,'controller-init.json');
      fs.writeFileSync(config,JSON.stringify({package_root:'/opt/leafseamer',data_dir:'/var/lib/leafseamer',login,
        ...(referenceExecutable&&{storage_revision:109})}),{mode:0o600});owned(config);
      const seed=bootstrap(role,data_dir,['--mount','type=bind,source='+file('./fixtures/linux-ingress-service.mjs')+',target=/tmp/seed.mjs,readonly',
        '--mount','type=bind,source='+config+',target=/tmp/config.json,readonly'],['/tmp/seed.mjs','/tmp/config.json']);
      enrollment=JSON.parse(seed);
      identity=enrollment.identity;
    }else{
      identity=JSON.parse(bootstrap(role,data_dir,[],[...args,'init-storage',...directoryArgs]));
      bootstrap(role,data_dir,[],[...args,'migrate-storage',...directoryArgs,'--to-revision','33']);
    }
    if(referenceExecutable){
      const filename=path.join(data_dir,role+'.sqlite');
      const db=new DatabaseSync(filename);
      try{legacyReference[role]=seedPreviousReferenceBinding(db,role,identity);}
      finally{db.close();}
      bootstrap(role,data_dir,[],[...args,'migrate-storage',...directoryArgs,'--to-revision',role==='controller'?'110':'34']);
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
  assert.equal(Boolean(socketPath),Boolean(pidFile));
  const manage=Boolean(socketPath),generationId=crypto.randomUUID();
  const supervised=process.env.LEAFSEAMER_TEST_COMPOSE_BOOTSTRAP==='1';
  const workerControl=process.env.LEAFSEAMER_TEST_COMPOSE_WORKER_CONTROL==='1';
  assert.ok(!supervised||manage);
  assert.ok(!workerControl||supervised);
  if(manage)assert.equal(process.env.DOCKER_HOST,'unix://'+socketPath);
  const plan={format:'leafseamer.linux-compose-protected/1',subnet:range+'.0/29',management,controller,seamer,
    nginx:{image:images.nginx,uid,gid,address:range+'.4'},gui:{directory,manifest_sha256:'sha256:'+hash(manifestBytes)},
    ...(manage&&{cgroup:{driver:'cgroupfs',generation_id:generationId,namespace:'private'}}),...(workerControl&&{worker_control:true})};
  let source,admissions,referenceAdmissions;
  assert.ok(!referenceExecutable||supervised);
  if(referenceExecutable){
    const executable=path.join(root,'reference-provider');
    fs.copyFileSync(referenceExecutable,executable);fs.chmodSync(executable,0o555);
    plan.reference_providers={image:{file:executable,sha256:'sha256:'+hash(fs.readFileSync(executable))},
      controller:{uid:1002,gid:1002},seamer:{uid:1003,gid:1003}};
  }
  const chronyFile=process.env.LEAFSEAMER_TEST_CHRONY_PROFILE;
  const captureTest=process.env.LEAFSEAMER_TEST_COMPOSE_REFERENCE_CAPTURE==='1';
  const qualifyReference=process.env.LEAFSEAMER_TEST_COMPOSE_REFERENCE_QUALIFICATION==='1';
  const captureNTS=process.env.LEAFSEAMER_TEST_COMPOSE_REFERENCE_NTS==='1';
  const captureKeys={},capturePackets=new Map(),independentSources={};
  let ntsServer;
  assert.ok(!captureTest||referenceExecutable&&chronyFile);
  assert.ok(!qualifyReference||captureTest);
  assert.ok(!captureNTS||captureTest&&!qualifyReference);
  if(captureTest){
    let network;
    if(captureNTS){
      const name='reference-nts.fixture.invalid';
      ntsServer=await startReferenceNTS(t,root,name,certificates('reference-nts',name));
      network=ntsServer.network;
    }else{
      const provider=dgram.createSocket('udp4');
      provider.bind(0,'127.0.0.1');await once(provider,'listening');
      t.after(()=>new Promise(resolve=>provider.close(resolve)));
      provider.on('message',(request,peer)=>{
        if(request.length!==48||request[0]!==35)return;
        const reply=Buffer.alloc(48);reply[0]=36;reply[1]=1;
        if(qualifyReference){
          const received=BigInt(Date.now()),stamp=(offset,ms)=>{
            reply.writeUInt32BE(Number((ms/1000n+2208988800n)&0xffffffffn),offset);
            reply.writeUInt32BE(Number((ms%1000n)*(1n<<32n)/1000n),offset+4);
          };
          reply.writeInt8(-20,3);
          stamp(16,received-(capturePackets.size<2?1000n:180000n));
          stamp(32,received);stamp(40,BigInt(Date.now()));
        }else{reply[19]=1;reply[35]=2;reply[43]=3;}
        request.copy(reply,24,40,48);
        capturePackets.set(request.toString('base64url'),reply.toString('base64url'));
        provider.send(reply,peer.port,peer.address);
      });
      network={authentication:'trusted_network',endpoint:'127.0.0.1:'+provider.address().port};
    }
    const {canonical}=await import('../dist/import-input.mjs'),now=BigInt(Date.now())*1000000n;
    plan.reference_providers.capture=Object.fromEntries([['controller',controller],['seamer',seamer]].map(([role,scope])=>{
      const directory=path.join(root,role+'-reference-source'),key=crypto.randomBytes(32);
      fs.mkdirSync(directory,{mode:0o750});fs.chownSync(directory,0,scope.gid);
      captureKeys[role]=key;
      const original=label=>({id:crypto.randomUUID(),revision:'1',digest:'sha256:'+hash('compose-reference:'+label)});
      const qualified=qualifyReference?{utc_mode:'normal_utc_no_smear',elapsed_error_ppm:100,span_quantization_ns:'1000',
        t2_error_ns:'20000000',t3_error_ns:'20000000',tref_error_ns:'20000000',max_upstream_age_ns:'60000000000',max_half_width_ns:'500000000',
        independent_source_ref:independentSources[role]=original(role+'-chrony'),monitoring_ref:original('loopback-monitoring'),
        platform_qualification_ref:original('vm-clock-boottime'),source_provenance_ref:original('loopback-server'),
        leap_schedule:{bulletin_ref:original('isolated-test-leap-window'),events:[],valid_from_ns:String(now-60000000000n),
          valid_until_ns:String(now+180000000000n)}}:null;
      const approval=canonical({format:'leafseamer-linux-reference-capture-approval/'+(qualified?'2':'1'),
        scope:{service_id:scope.service_id,database_instance_id:scope.database_instance_id},
        provider_digest:plan.reference_providers.image.sha256,approval_id:crypto.randomUUID(),approval_revision:'1',network,
        archive_budget_bytes:captureNTS?458752:65536,capture_key_id:crypto.randomUUID(),
        not_before_ns:String(now-60000000000n),expires_ns:String(now+180000000000n),
        ...(qualified&&{reference:qualified})});
      for(const [name,bytes] of [['approval.json',approval],['capture.key',key]]){
        const filename=path.join(directory,name);fs.writeFileSync(filename,bytes,{mode:0o440});fs.chownSync(filename,0,scope.gid);
      }
      return [role,{directory,approval_sha256:'sha256:'+hash(approval)}];
    }));
  }
  const pairingTest=process.env.LEAFSEAMER_TEST_COMPOSE_PAIRING==='1';
  const pairedSimulator=process.env.LEAFSEAMER_TEST_COMPOSE_PAIRED_SIMULATOR==='1';
  assert.ok(!pairingTest||chronyFile);
  assert.ok(!pairedSimulator||pairingTest&&workerControl&&process.env.LEAFSEAMER_COMPOSE_WORKER_FIXTURE_IMAGE);
  assert.ok(!process.env.LEAFSEAMER_TEST_COMPOSE_BROWSER||pairingTest);
  assert.ok(process.env.LEAFSEAMER_TEST_COMPOSE_PUBLICATION!=='1'||pairingTest);
  const clocks={};
  let clockValues;
  if(supervised){
    const {canonical}=await import('../dist/import-input.mjs');
    const clockDir=process.env.LEAFSEAMER_TEST_COMPOSE_CLOCK_DIST;
    assert.ok(clockDir);
    source=(await import(pathToFileURL(path.join(clockDir,'native-clock.mjs')))).openNativeClock();
    if(chronyFile){
      assert.equal(process.getuid(),0);
      clockValues=await import(pathToFileURL(path.join(clockDir,'auth-clock-value.mjs')));
      plan.clock_evidence={};
    }
    plan.bootstrap={};
    for(const [role,scope] of [['controller',controller],['seamer',seamer]]){
      const node=bootstrap(role,scope.data_dir,[],['-e',"process.stdout.write(require('crypto').createHash('sha256').update(require('fs').readFileSync('/proc/self/exe')).digest('hex'))"]);
      const manifest=bootstrap(role,scope.data_dir,[],['-e',"process.stdout.write(require('crypto').createHash('sha256').update(require('fs').readFileSync('/opt/leafseamer/dist/build-manifest.json')).digest('hex'))"]);
      assert.match(node,/^[a-f0-9]{64}$/);assert.match(manifest,/^[a-f0-9]{64}$/);
      plan.bootstrap[role]={format:'leafseamer-core-bootstrap-policy/1',service_id:scope.service_id,database_instance_id:scope.database_instance_id,
        artifact_manifest_ref:{manifest_id:role+'.compose',revision:'1',digest:'sha256:'+hash(canonical({[role+'_build_sha256']:manifest,node_sha256:node}))},
        platform_profile_ref:{profile_id:'compose-'+role+'-test',revision:'1'},bootstrap_timeout_ms:45000,clock_backend_revision:'1',policy_revision:'1'};
      if(chronyFile){
        const {seal,digest}=clockValues,chrony=parseFile(chronyFile);
        const admin=path.join(root,role+'-signer'),exchange=path.join(root,role+'-exchange'),key=path.join(root,role+'-clock-public.pem');
        fs.mkdirSync(admin,{mode:0o700});fs.mkdirSync(exchange,{mode:0o700});owned(exchange);
        const {publicKey,privateKey}=crypto.generateKeyPairSync('ed25519');
        const publicBytes=publicKey.export({format:'pem',type:'spki'});
        fs.writeFileSync(key,publicBytes,{mode:0o644});
        const privateFile=path.join(admin,'private.pem');
        fs.writeFileSync(privateFile,privateKey.export({format:'pem',type:'pkcs8'}),{mode:0o600});
        const approval=()=>({id:crypto.randomUUID(),revision:'1',digest:'sha256:'+'a'.repeat(64)});
        const policy=seal({id:crypto.randomUUID(),revision:'1',service_id:scope.service_id,runtime_profile_ref:approval(),
          native_artifact_ref:approval(),system_time_source_ref:independentSources[role]??approval(),environment_approval_ref:approval(),
          health_profile_ref:{...approval(),digest:digest(chrony)},max_system_error_ns:'100000000',
          wall_quantization_ns:'100',monotonic_quantization_ns:'10',drift_ppb:1000,capture_limit_ns:'20000000',sample_period_ns:'500000000',
          sample_ttl_ns:'5000000000',sample_window_policy:'authentication-clock-sample/2'});
        plan.clock_evidence[role]={exchange_directory:exchange,policy_digest:policy.digest,public_key_file:key,public_key_sha256:'sha256:'+hash(publicBytes)};
        clocks[role]={admin,exchange,privateFile,policy,chrony,clockDir};
      }
    }
  }
  assert.ok(!chronyFile||supervised);
  const aliasOfKey=path.join(root,'ca-alias.pem');
  fs.linkSync(controller.private_key_file,aliasOfKey);
  const generate=['--disallow-code-generation-from-strings',file('../dist/linux-compose.mjs'),'--config',planPath,'--output',output];
  for(const [invalid,code]of [
    [{...plan,controller:{...controller,image:'controller:latest'}},'compose_image_or_user'],
    [{...plan,seamer:{...seamer,address:controller.address}},'compose_network'],
    [{...plan,seamer:{...seamer,data_dir:controller.data_dir}},'compose_path_overlap'],
    [{...plan,seamer:{...seamer,ca_file:controller.private_key_file}},'compose_tls_scope'],
    [{...plan,seamer:{...seamer,ca_file:aliasOfKey}},'compose_tls_scope'],
    [{...plan,seamer:{...seamer,database_instance_id:controller.database_instance_id}},'compose_identity'],
    [{...plan,cgroup:{driver:'auto',generation_id:crypto.randomUUID(),namespace:'private'}},'cgroup_scope'],
    [{...plan,cgroup:{driver:'cgroupfs',generation_id:generationId,namespace:'host'}},workerControl?'compose_worker_control':referenceExecutable?'compose_reference_providers':'compose_cgroup'],
    ...(referenceExecutable?[[{...plan,reference_providers:{...plan.reference_providers,controller:{uid,gid}}},'compose_reference_providers']]:[]),
    ...(workerControl?[ [{...plan,worker_control:false},'compose_worker_control'] ]:[]),
    ...(chronyFile?[
      [{...plan,clock_evidence:{...plan.clock_evidence,seamer:{...plan.clock_evidence.seamer,exchange_directory:clocks.controller.exchange}}},'compose_clock_scope'],
      [{...plan,clock_evidence:{...plan.clock_evidence,controller:{...plan.clock_evidence.controller,public_key_sha256:'sha256:'+'0'.repeat(64)}}},'compose_clock_key']
    ]:[])
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
  const stem='leafseamer_'+generationId.replaceAll('-','');
  for(const driver of ['cgroupfs','systemd']){
    const observedOutput=path.join(root,'cgroup-'+driver);
    const {bootstrap:_policy,clock_evidence:_clock,worker_control:_workerControl,reference_providers:_reference,...protectedPlan}=plan;
    fs.writeFileSync(planPath,JSON.stringify({...protectedPlan,cgroup:{driver,generation_id:generationId,namespace:'private'}}));
    run(process.execPath,[...generate.slice(0,-1),observedOutput]);
    const {services}=JSON.parse(docker('compose','--project-name',project,'--file',path.join(observedOutput,'compose.json'),'config','--format','json'));
    const parent=role=>driver==='cgroupfs'?'/'+stem+'_'+role:stem+'_'+role+'.slice';
    assert.equal(services.controller.cgroup_parent,parent('controller'));
    assert.equal(services.seamer.cgroup_parent,parent('seamer'));
    assert.equal(services.controller.cgroup,'private');
    assert.equal(services.seamer.cgroup,'private');
    assert.equal(services.nginx.cgroup_parent,undefined);
    assert.equal(services.nginx.cgroup,undefined);
  }
  fs.writeFileSync(planPath,JSON.stringify(plan));
  const installationDirectory=path.join(root,'installation');
  const hostOptions={installationDirectory,planFile:planPath,generationDirectory:output,socketPath,pidFile,source};
  let openLinuxComposeHost,installation;
  const prepareParents=async id=>{
    const {linuxContainerCgroup}=await import('../dist/linux-cgroup-retirement.mjs');
    for(const role of ['controller','seamer']){
      const group='/sys/fs/cgroup'+linuxContainerCgroup({driver:'cgroupfs',generationId:id,role}).groupPath;
      fs.mkdirSync(group);groups.push(group);
      if(referenceExecutable&&id===generationId){fs.mkdirSync(group+'/reference');groups.unshift(group+'/reference');}
    }
  };
  const projectFor=(id,hostId=installation.host_installation_id)=>'leafseamer-'+hostId.replaceAll('-','')+'-'+id.replaceAll('-','');
  if(manage){
    ({openLinuxComposeHost}=await import('../dist/linux-compose-host.mjs'));
    const {createInstallationStore,openInstallationStore}=await import('../dist/installation-store.mjs');
    fs.mkdirSync(installationDirectory,{mode:0o700});
    installation=createInstallationStore(installationDirectory);
    const store=openInstallationStore(installationDirectory);
    try{store.initializeLinuxDeploymentJournal();}finally{store.close();}
    project=projectFor(generationId);
    const unchanged=fs.readFileSync(composePath);
    fs.appendFileSync(composePath,'\n');
    assert.throws(()=>openLinuxComposeHost(hostOptions),{code:'compose_host_plan_changed'});
    fs.writeFileSync(composePath,unchanged);
    const wrongPid=path.join(root,'wrong.pid');
    fs.writeFileSync(wrongPid,String(process.pid));
    assert.throws(()=>openLinuxComposeHost({...hostOptions,pidFile:wrongPid}),{code:'compose_host_daemon'});
    if(referenceExecutable){
      const legacy=new DatabaseSync(path.join(installationDirectory,'linux-deployment.db'));
      try{legacy.exec('DROP TABLE linux_deployment_reference_admission; DROP TABLE linux_deployment_reference_launch; PRAGMA user_version=2');}
      finally{legacy.close();}
      managedHost=openLinuxComposeHost(hostOptions);
      await assert.rejects(managedHost.startSupervised(),{code:'compose_host_bootstrap'});
      assert.equal(managedHost.current(),null);
      await managedHost.close();
      const migration=openInstallationStore(installationDirectory);
      try{assert.deepEqual(migration.upgradeLinuxDeploymentJournal(),{schema_revision:3,changed:true});}finally{migration.close();}
    }
    managedHost=openLinuxComposeHost(hostOptions);
    if(supervised){
      assert.throws(()=>managedHost.start(),{code:'compose_host_bootstrap'});
      await assert.rejects(managedHost.startSupervised(),{code:'compose_host_parent_unavailable'});
    }else assert.throws(()=>managedHost.start(),{code:'compose_host_parent_unavailable'});
    assert.equal(managedHost.current(),null);
    await prepareParents(generationId);
  }
  created=true;
  if(manage){
    const outcome=supervised?await managedHost.startSupervised():{record:managedHost.start()};
    const {record:started}=outcome;
    admissions=outcome.admissions;
    referenceAdmissions=outcome.referenceAdmissions;
    if(supervised)for(const role of ['controller','seamer']){
      assert.deepEqual(managedHost.admission(role),admissions[role]);
      assert.equal(admissions[role].receipt.gate_state,'closed');
      if(referenceExecutable){
        const provider=referenceAdmissions[role];
        assert.deepEqual(managedHost.referenceAdmission(role),provider);
        assert.deepEqual(provider.receipt.domain_ref,admissions[role].receipt.domain_ref);
        assert.equal(provider.intent.role,'time_provider');
        assert.equal(provider.intent.artifact_manifest_ref.digest,plan.reference_providers.image.sha256);
        const pid=provider.process_observation.provider_pid,group=started.detail.runtime_binding.reference_groups[role];
        assert.equal(fs.readFileSync('/proc/'+pid+'/cgroup','utf8'),'0::'+group.group_path+'\n');
        assert.equal(fs.readlinkSync('/proc/'+pid+'/exe'),plan.reference_providers.image.file);
      }
    }
    if(workerControl){
      const generated=JSON.parse(fs.readFileSync(composePath,'utf8')).services;
      assert.ok(generated.controller.command.includes('--worker-control'));
      assert.ok(!generated.seamer.command.includes('--worker-control'));
    }
    assert.equal(started.phase,'running');
    assert.equal(started.detail.runtime_binding.project,project);
    const {observeLinuxComposeCore}=await import('../dist/linux-cgroup-retirement.mjs');
    const {core_containment,containers,daemon}=started.detail.runtime_binding;
    for(const role of ['controller','seamer']){
      const saved=core_containment[role],{leader}=started.detail.members[role];
      const request={driver:'cgroupfs',generationId,role,host:daemon.host,leader,containerId:containers[role],uid,gid};
      assert.deepEqual(saved,observeLinuxComposeCore(request));
      const identity=location=>{const {dev,ino}=fs.statSync(location,{bigint:true});return {device:String(dev),inode:String(ino)};};
      assert.deepEqual(saved.group,identity('/sys/fs/cgroup'+leader.group_path));
      assert.deepEqual(saved.group,identity('/proc/'+leader.pid+'/root/sys/fs/cgroup'));
      assert.notDeepEqual(saved.cgroup_namespace,daemon.host.cgroup_namespace);
      const mount=fs.readFileSync('/proc/'+leader.pid+'/mountinfo','utf8').split('\n')
        .map(line=>line.split(' ')).find(fields=>fields[4]==='/sys/fs/cgroup');
      assert.equal(saved.cgroup_mount_id,mount[0]);
      assert.ok(mount[5].split(',').includes('ro'));
      assert.throws(()=>observeLinuxComposeCore({...request,containerId:'0'.repeat(64)}),{code:'cgroup_compose_container'});
      assert.throws(()=>observeLinuxComposeCore({...request,gid:gid+1}),{code:'cgroup_compose_account'});
    }
    if(supervised)await assert.rejects(managedHost.startSupervised(),{code:'linux_deployment_generation_used'});
    else assert.throws(()=>managedHost.start(),{code:'linux_deployment_previous_open'});
  }else compose('up','--detach','--no-build','--pull','never');
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
      assert.deepEqual(container.Mounts.filter(value=>value.RW).map(value=>value.Destination).sort(),
        [...(chronyFile?['/run/leafseamer-clock']:[]),'/var/lib/leafseamer']);
      if(chronyFile){
        assert.deepEqual(container.Mounts.filter(value=>value.Destination.startsWith('/etc/leafseamer/clock')).map(value=>[value.Source,value.RW]).sort(),
          [[path.join(output,role+'-clock.json'),false],[plan.clock_evidence[role].public_key_file,false]].sort());
      }
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
  if(captureTest){
    const expires=performance.now()+10000;
    for(const role of ['controller','seamer']){
      while(!bindClockPublisher(role,admissions[role].descriptor)){
        assert.ok(performance.now()<expires,role+' did not issue its authentication challenge');await delay(100);
      }
      clocks[role].publish();
    }
  }
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
  function bindClockPublisher(role,descriptor){
    const {canonical,ref,seal}=clockValues;
    const clock=clocks[role];
    const challenges=fs.readdirSync(clock.exchange).filter(name=>/^challenge-[a-f0-9-]+\.json$/.test(name))
      .map(name=>parseFile(path.join(clock.exchange,name))).filter(challenge=>challenge.descriptor_digest===descriptor.descriptor_digest);
    if(challenges.length===0)return false;
    assert.equal(challenges.length,1);
    const [challenge]=challenges;
    const {service_id,service_boot_id,database_instance_id,clock_domain_id,descriptor_digest,continuity,native_binary_digest}=challenge;
    assert.equal(service_id,plan[role].service_id);
    assert.equal(database_instance_id,plan[role].database_instance_id);
    assert.equal(clock_domain_id,descriptor.clock_domain_id);
    assert.equal(descriptor_digest,descriptor.descriptor_digest);
    const {policy,chrony,admin,privateFile,exchange,clockDir}=clock;
    const {runtime_profile_ref,native_artifact_ref,health_profile_ref,system_time_source_ref,environment_approval_ref}=policy;
    clock.runtime=seal({id:crypto.randomUUID(),revision:'1',service_id,service_boot_id,clock_domain_id,descriptor_digest,
      policy_ref:ref(policy),runtime_profile_ref,native_artifact_ref,environment_approval_ref,
      continuity,native_binary_digest,valid_before_tick_ns:String(source.tick()+60000000000n)});
    const profile=path.join(admin,'profile.json'),statement=path.join(admin,'statement.json'),signed=path.join(admin,'evidence.json');
    fs.writeFileSync(profile,canonical({format:'leafseamer.authentication-clock-signing-profile/2',service_id,database_instance_id,
      policy_digest:policy.digest,native_binary_digest,private_key_file:privateFile,evidence_file:signed,chrony}),{mode:0o600});
    clock.publish=()=>{
      const health=seal({id:crypto.randomUUID(),revision:'1',service_id,service_boot_id,clock_domain_id,runtime_ref:ref(clock.runtime),
        policy_ref:ref(policy),health_profile_ref,system_time_source_ref,environment_approval_ref,state:'synchronized',holdover_ref:null,
        valid_before_tick_ns:String(source.tick()+4600000000n)});
      fs.writeFileSync(statement,canonical({challenge,evidence:{policy,runtime:clock.runtime,health}}),{mode:0o600});
      const result=run(process.execPath,[path.join(clockDir,'clock-evidence.mjs'),'--profile',profile,'--statement',statement],5000);
      assert.deepEqual(JSON.parse(result),{state:'published',service_id,service_boot_id});
      owned(signed);
      fs.renameSync(signed,path.join(exchange,'evidence-'+service_boot_id+'.json'));
      return health;
    };
    return true;
  }
  if(chronyFile){
    if(!captureTest)for(const role of ['controller','seamer'])assert.ok(bindClockPublisher(role,admissions[role].descriptor));
    const ready=role=>{
      const lines=docker('logs',containers[role].Id).split('\n').filter(line=>line.startsWith('{'));
      const {port:localPort}=lines.map(line=>JSON.parse(line)).find(event=>event.event==='listening');
      const options={hostname:role==='seamer'?'127.0.0.1':plan[role].address,port:localPort,path:'/health/ready',
        ...(role==='controller'&&{servername:plan[role].server_name,ca:fs.readFileSync(plan[role].certificate_file,'utf8')})};
      const probe=`const request=require(${JSON.stringify(role==='controller'?'node:https':'node:http')}).get(${JSON.stringify(options)},res=>{
        let body='';res.on('data',data=>body+=data);res.on('end',()=>process.stdout.write(JSON.stringify([res.statusCode,JSON.parse(body)])));
      });request.setTimeout(2000,()=>request.destroy());`;
      return JSON.parse(docker('exec',containers[role].Id,'/usr/local/bin/node','-e',probe));
    };
    const state=(role,expected,evidence)=>{
      const [status,body]=ready(role);
      assert.equal(status,503);
      assert.equal(body.ready,false);
      assert.equal(body.authentication_clock_evidence,evidence);
      assert.equal(body.authentication_clock,expected);
    };
    if(!captureTest)for(const role of ['controller','seamer']){
      state(role,'unqualified','missing');clocks[role].publish();
    }
    await delay(850);
    for(const role of ['controller','seamer'])state(role,'available','verified');
    if(captureTest){
      const countCaptures=()=>ntsServer?.count()??capturePackets.size;
      async function awaitCaptures(expected,wait){
        const deadline=performance.now()+wait;
        let count;
        while((count=countCaptures())<expected){
          if(performance.now()>=deadline)assert.fail('reference capture timeout\n'+(ntsServer?.stats()??'')+compose('logs','--no-color'));
          clocks.controller.publish();clocks.seamer.publish();await delay(1000);
        }
        assert.equal(count,expected);
      }
      await awaitCaptures(2,6000);
      if(captureNTS)await delay(500);
      const directory=plan.reference_providers.capture.controller.directory;
      fs.renameSync(path.join(directory,'approval.json'),path.join(directory,'withdrawn.json'));
      await awaitCaptures(3,22000);
      await delay(500);
      assert.equal(countCaptures(),3);
    }
    const old=clocks.controller.publish();
    for(let i=0;i<4;i++){
      clocks.seamer.publish();
      await delay(1400);
      state('seamer','available','verified');
    }
    assert.ok(source.tick()>=BigInt(old.valid_before_tick_ns));
    state('controller','faulted','expired');
    clocks.controller.publish();
    state('controller','faulted','verified');
    assert.equal((await send('/auth/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(login)})).status,503);
    assert.equal((await send(draft)).status,401);
  }
  const [backend]=Object.values(containers.seamer.NetworkSettings.Networks);
  assert.equal(JSON.parse(docker('network','inspect',backend.NetworkID))[0].Internal,true);
  compose('stop','--timeout','8','nginx');
  for(const role of ['controller','seamer']){
    const [state]=JSON.parse(docker('inspect',containers[role].Id));
    assert.equal(state.State.Running,true);
    assert.equal(state.State.StartedAt,containers[role].State.StartedAt);
  }
  if(manage){
    extraContainer=docker('run','--detach','--pull','never','--network','none','--label','com.docker.compose.project='+project,
      '--entrypoint','/bin/sleep',images.nginx,'120').trim();
    assert.throws(()=>managedHost.retire(),{code:'compose_host_inventory_changed'});
    for(const role of ['controller','seamer'])assert.equal(JSON.parse(docker('container','inspect',containers[role].Id))[0].State.Running,true);
    docker('container','rm','--force',extraContainer);
    extraContainer=null;
    docker('container','rm',containers.nginx.Id);
    const active=managedHost.current();
    assert.equal(active.phase,'closing');
    if(!supervised){
      managedHost.close();
      managedHost=openLinuxComposeHost(hostOptions);
      assert.deepEqual(managedHost.current(),active);
    }
    if(workerControl){
      const controllerLog=new DatabaseSync(path.join(controller.data_dir,'controller.sqlite'),{readOnly:true});
      try{
        const deadline=performance.now()+5000,ack=controllerLog.prepare('SELECT 1 FROM worker_fence_ack');
        while(!ack.get()){
          assert.ok(performance.now()<deadline,'Controller did not persist the initial worker fence acknowledgement');
          await delay(50);
        }
      }finally{controllerLog.close();}
      const original=fs.readFileSync(composePath);
      // 使原监督器主动关闭连接，并保留它已持有的进程和 cgroup 描述符用于退役。
      fs.appendFileSync(composePath,'\n');
      try{
        const limit=performance.now()+15000;
        for(const role of ['controller','seamer']){
          while(JSON.parse(docker('container','inspect',containers[role].Id))[0].State.Running){
            assert.ok(performance.now()<limit,role+' did not exit after the plan changed');
            await delay(50);
          }
        }
      }finally{fs.writeFileSync(composePath,original);}
    }
    if(referenceExecutable&&!workerControl){
      const pid=referenceAdmissions.controller.process_observation.provider_pid;
      assert.equal(fs.readlinkSync('/proc/'+pid+'/exe'),plan.reference_providers.image.file);
      process.kill(pid,'SIGTERM');
      const deadline=performance.now()+10000;
      for(const role of ['controller','seamer'])while(JSON.parse(docker('container','inspect',containers[role].Id))[0].State.Running){
        assert.ok(performance.now()<deadline,role+' did not exit after the reference provider was lost');
        await delay(50);
      }
    }
    let retired=managedHost.retire();
    if(referenceExecutable){
      const deadline=performance.now()+5000;
      while(retired.phase==='closing'&&performance.now()<deadline){await delay(50);retired=managedHost.retire();}
      for(const role of ['controller','seamer']){
        assert.equal(fs.existsSync('/proc/'+referenceAdmissions[role].process_observation.provider_pid),false);
        const group=retired.detail.runtime_binding.reference_groups[role];
        assert.match(fs.readFileSync('/sys/fs/cgroup'+group.group_path+'/cgroup.events','utf8'),/^populated 0$/m);
      }
    }
    assert.equal(retired.phase,'retired');
    assert.match(retired.detail.endpoint_evidence_digest,/^sha256:[a-f0-9]{64}$/);
    assert.deepEqual(managedHost.retire(),retired);
    assert.equal(compose('ps','--all','--quiet').trim(),'');
    created=false;
    await managedHost.close();
    if(supervised){
      managedHost=openLinuxComposeHost(hostOptions);
      assert.deepEqual(managedHost.current(),retired);
      for(const role of ['controller','seamer']){
        assert.deepEqual(managedHost.admission(role),admissions[role]);
        if(referenceExecutable)assert.deepEqual(managedHost.referenceAdmission(role),referenceAdmissions[role]);
      }
      await managedHost.close();
      if(referenceExecutable){
        const ledger=new DatabaseSync(path.join(installationDirectory,'linux-deployment.db'));
        try{
          assert.deepEqual(ledger.prepare('PRAGMA foreign_key_check').all(),[]);
          const originals=ledger.prepare('SELECT role, body FROM linux_deployment_reference_launch WHERE generation_id=? ORDER BY role').all(generationId);
          assert.deepEqual(originals.map(value=>value.role),['controller','seamer']);
          for(const {role,body} of originals){
            const original=JSON.parse(body);
            assert.equal(original.core_receipt_id,admissions[role].receipt.receipt_id);
            assert.deepEqual(original.intent,referenceAdmissions[role].intent);
            assert.deepEqual(original.group,retired.detail.runtime_binding.reference_groups[role].group);
          }
          assert.throws(()=>ledger.exec('UPDATE linux_deployment_reference_launch SET digest=digest'),/linux_deployment_reference_immutable/);
          assert.throws(()=>ledger.exec('DELETE FROM linux_deployment_reference_admission'),/linux_deployment_reference_immutable/);
        }finally{ledger.close();}
      }
    }
  }else compose('stop','--timeout','8');
  for(const role of ['controller','seamer']){
    const db=new DatabaseSync(path.join(plan[role].data_dir,role+'.sqlite'),{readOnly:true});
    try{
      assert.equal(db.prepare('SELECT count(*) AS count FROM service_boot WHERE state=?').get('started').count,0);
      assert.equal(db.prepare('SELECT service_id FROM service_state').get().service_id,plan[role].service_id);
      if(supervised){
        const receipt=db.prepare('SELECT receipt_jcs FROM core_runtime_binding WHERE receipt_id=?').all(admissions[role].receipt.receipt_id);
        assert.equal(receipt.length,1);
        assert.deepEqual(JSON.parse(receipt[0].receipt_jcs),admissions[role].receipt);
        if(referenceExecutable){
          const rows=db.prepare('SELECT body_jcs,body_digest FROM time_provider_runtime_binding WHERE receipt_id=?').all(referenceAdmissions[role].receipt.receipt_id);
          assert.equal(rows.length,1);
          const {body_jcs,body_digest}=rows[0],binding=JSON.parse(body_jcs),saved=referenceAdmissions[role];
          assert.equal(binding.format,'leafseamer-time-provider-runtime-binding/2');
          assert.equal(binding.core_receipt_id,admissions[role].receipt.receipt_id);
          assert.deepEqual(binding.admission_receipt,saved.receipt);
          assert.deepEqual(binding.process_observation,saved.process_observation);
          assert.equal(body_digest,'sha256:'+hash(body_jcs));
          const prior=legacyReference[role];
          const original=db.prepare('SELECT body_jcs,body_digest FROM time_provider_runtime_binding WHERE service_boot_id=?').get(prior.id);
          assert.equal(original.body_jcs,prior.text);
          assert.equal(original.body_digest,prior.digest);
          assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(),[]);
          if(captureTest)checkReferenceCaptures(db,role,captureKeys[role],capturePackets,plan.reference_providers.capture[role],qualifyReference,captureNTS);
        }
      }
      if(workerControl&&role==='controller'){
        const {receipt,descriptor}=admissions.controller;
        const hostLog=new DatabaseSync(path.join(installationDirectory,'linux-worker-control-'+receipt.launch_id+'.db'),{readOnly:true});
        try{
          const stored=JSON.parse(hostLog.prepare('SELECT body FROM identity').get().body);
          assert.deepEqual(stored.core_receipt,receipt);
          assert.deepEqual(stored.scope.domain_ref,receipt.domain_ref);
          assert.equal(stored.scope.supervisor_instance_id,descriptor.supervisor_instance_id);
          const fence=hostLog.prepare('SELECT revision,digest,body FROM fence').get();
          const ack=db.prepare('SELECT revision,body_jcs FROM worker_fence_ack').get();
          assert.ok(fence&&ack,'the confirmed worker fence must survive retirement');
          assert.deepEqual(JSON.parse(fence.body),{scope:stored.scope,revision:String(fence.revision),items:[]});
          assert.equal(ack.revision,fence.revision);
          assert.deepEqual(JSON.parse(ack.body_jcs),{revision:String(fence.revision),snapshot_digest:fence.digest,journal_committed:true});
          assert.equal(hostLog.prepare('SELECT count(*) AS total FROM attempt').get().total,0);
        }finally{hostLog.close();}
      }
      if(chronyFile){
        const {service_boot_id,clock_domain_id}=clocks[role].runtime,args=[service_boot_id,clock_domain_id];
        const history=db.prepare('SELECT DISTINCT health_digest FROM authentication_clock_acquisition WHERE service_boot_id=? AND clock_domain_id=?').all(...args);
        assert.ok(history.length>=2,role+' did not persist a renewal');
        const faults=db.prepare('SELECT count(*) AS count FROM authentication_clock_fault WHERE service_boot_id=? AND clock_domain_id=?').get(...args);
        assert.equal(faults.count,role==='controller'?1:0);
      }
    }finally{db.close();}
  }
  if(manage){
    const nextId=crypto.randomUUID(),nextDirectory=path.join(root,'next');
    const {bootstrap:_policy,clock_evidence:_clock,worker_control:_workerControl,reference_providers:_reference,...protectedPlan}=plan;
    fs.writeFileSync(planPath,JSON.stringify({...protectedPlan,cgroup:{driver:'cgroupfs',generation_id:nextId}}));
    run(process.execPath,[...generate.slice(0,-1),nextDirectory]);
    await prepareParents(nextId);
    project=projectFor(nextId);
    composePath=path.join(nextDirectory,'compose.json');
    managedHost=openLinuxComposeHost({...hostOptions,generationDirectory:nextDirectory});
    created=true;
    const next=managedHost.start();
    assert.equal(next.intent.generation_id,nextId);
    assert.equal(next.detail.runtime_binding.core_containment,undefined);
    assert.equal(managedHost.retire().phase,'retired');
  }else compose('down','--timeout','8');
  assert.equal(compose('ps','--all','--quiet').trim(),'');
  created=false;
  delete plan.reference_providers;
  if(process.env.LEAFSEAMER_COMPOSE_WORKER_FIXTURE_IMAGE){
    assert.ok(workerControl);
    managedHost.close();managedHost=null;
    const fixtureImage=process.env.LEAFSEAMER_COMPOSE_WORKER_FIXTURE_IMAGE;
    const dist=process.env.LEAFSEAMER_COMPOSE_WORKER_FIXTURE_DIST,node=process.env.LEAFSEAMER_COMPOSE_WORKER_FIXTURE_NODE;
    const generation=crypto.randomUUID(),deployment=path.join(root,'worker'),launchId=crypto.randomUUID();
    const dataDir=path.join(root,'worker-controller'),directory=path.join(root,'worker-stage'),channelDirectory=path.join(root,'worker-sockets');
    fs.mkdirSync(dataDir,{mode:0o700});owned(dataDir);
    fs.mkdirSync(directory,{mode:0o711});fs.mkdirSync(channelDirectory,{mode:0o755});
    const storageArgs=['/opt/leafseamer/dist/cli.mjs'],dataArgs=['--data-dir','/var/lib/leafseamer'];
    const identity=JSON.parse(bootstrap('controller',dataDir,[],[...storageArgs,'init-storage',...dataArgs]));
    bootstrap('controller',dataDir,[],[...storageArgs,'migrate-storage',...dataArgs,'--to-revision','109']);
    const workerGui=path.join(root,'worker-gui');fs.cpSync(plan.gui.directory,workerGui,{recursive:true});
    const workerSite=JSON.stringify({...site,service_id:identity.service_id,database_instance_id:identity.database_instance_id})+'\n';
    fs.writeFileSync(path.join(workerGui,'site.json'),workerSite);
    const workerManifest=structuredClone(manifest);workerManifest.artifacts['site.json']=hash(workerSite);
    const workerGuiManifest=JSON.stringify(workerManifest)+'\n';fs.writeFileSync(path.join(workerGui,'gui-manifest.json'),workerGuiManifest);
    const {canonical,digest}=await import('../dist/import-input.mjs');
    const {linuxContainerCgroup}=await import('../dist/linux-cgroup-retirement.mjs');
    const {openInstallationStore}=await import('../dist/installation-store.mjs');
    const {sealSimulatorWorker}=await import('./fixtures/linux-worker-materialization.mjs');
    const {deviceModuleEventProtocol}=await import(pathToFileURL(path.join(dist,'sdk','device-module.mjs')));
    const workerTls=certificates('worker-controller',controller.server_name,true);
    const workerPlan={...plan,controller:{...controller,...workerTls,ca_file:workerTls.certificate_file,image:fixtureImage,data_dir:dataDir,
      service_id:identity.service_id,database_instance_id:identity.database_instance_id},
      gui:{directory:workerGui,manifest_sha256:'sha256:'+hash(workerGuiManifest)},
      cgroup:{...plan.cgroup,generation_id:generation},bootstrap:{...plan.bootstrap},
      worker_runtime:{directory,channel_directory:channelDirectory,uid:1001,gid:1001,
        distribution:{directory:dist,manifest_sha256:'sha256:'+hash(fs.readFileSync(path.join(dist,'build-manifest.json')))},
        image:{file:node,sha256:'sha256:'+hash(fs.readFileSync(node))}}};
    workerPlan.bootstrap.controller={...plan.bootstrap.controller,service_id:identity.service_id,database_instance_id:identity.database_instance_id,
      artifact_manifest_ref:{...plan.bootstrap.controller.artifact_manifest_ref,
        digest:digest({controller_build_sha256:workerPlan.worker_runtime.distribution.manifest_sha256.slice(7),node_sha256:workerPlan.worker_runtime.image.sha256.slice(7)})}};
    delete workerPlan.clock_evidence;
    fs.writeFileSync(planPath,JSON.stringify(workerPlan));run(process.execPath,[...generate.slice(0,-1),deployment]);
    await prepareParents(generation);
    const parent=linuxContainerCgroup({driver:'cgroupfs',generationId:generation,role:'controller'}).groupPath;
    const group_path=parent+'/worker_'+launchId.replaceAll('-',''),groupFile='/sys/fs/cgroup'+group_path;
    fs.mkdirSync(groupFile);groups.unshift(groupFile);
    const {dev,ino}=fs.statSync(groupFile,{bigint:true}),boot_id=fs.readFileSync('/proc/sys/kernel/random/boot_id','utf8').trim();
    const containment={backend:'linux_cgroup_v2',generation,group_id:'group_'+digest({boot_id,group_path,group:{device:String(dev),inode:String(ino)}}).slice(7)};
    const store=openInstallationStore(installationDirectory);
    let sealed,failure;
    try{
      sealed=await sealSimulatorWorker(t,{dist,directory:root,serviceId:identity.service_id,profileId:workerPlan.bootstrap.controller.platform_profile_ref.profile_id,
        protocol:deviceModuleEventProtocol,store});
      fs.writeFileSync(path.join(dataDir,'worker-test.json'),canonical({policy:workerPlan.bootstrap.controller,launchId,containment,
        channelDirectory:'/run/leafseamer-worker',data:'/var/lib/leafseamer',start:'/var/lib/leafseamer/worker-start',
        result:'/var/lib/leafseamer/worker-result.json',intakeRef:sealed.intakeRef}));
      project=projectFor(generation);composePath=path.join(deployment,'compose.json');
      managedHost=openLinuxComposeHost({...hostOptions,generationDirectory:deployment,installationStore:store});
      created=true;
      const outcome=await managedHost.startSupervised().catch(error=>{
        throw new Error(compose('logs','--no-color','controller','seamer').trim(),{cause:error});
      });
      fs.writeFileSync(path.join(dataDir,'worker-start'),'');
      const limit=performance.now()+15000,resultPath=path.join(dataDir,'worker-result.json');
      while(!fs.existsSync(resultPath)||!fs.statSync(resultPath).size){
        assert.ok(performance.now()<limit,'Compose Worker did not finish the launch and revoke flow');await delay(50);
      }
      const result=parseFile(resultPath);assert.equal(result.ok,true,result.error);
      assert.equal(result.workerReceipt.gate_state,'closed');
      assert.deepEqual(result.simulatorEvent.event.origin.payload.value,{value:7,write_sequence:'1'});
      assert.match(fs.readFileSync(groupFile+'/cgroup.events','utf8'),/^populated 0$/m);
      assert.deepEqual(fs.readdirSync(directory),[]);
      assert.ok(fs.readdirSync(channelDirectory).every(name=>name==='installation.sock'));
      const {receipt}=outcome.admissions.controller;
      assert.equal(managedHost.retire().phase,'retired');created=false;
      const log=new DatabaseSync(path.join(installationDirectory,'linux-worker-control-'+receipt.launch_id+'.db'),{readOnly:true});
      const controllerDb=new DatabaseSync(path.join(dataDir,'controller.sqlite'),{readOnly:true});
      try{
        assert.equal(log.prepare('SELECT count(*) AS total FROM attempt').get().total,1);
        assert.deepEqual(JSON.parse(log.prepare('SELECT body FROM admission').get().body),result.workerReceipt);
        assert.equal(JSON.parse(log.prepare('SELECT body FROM retirement').get().body).result,'confirmed_empty');
        assert.equal(controllerDb.prepare('SELECT count(*) AS total FROM execution_handshake').get().total,1);
        assert.equal(controllerDb.prepare('SELECT count(*) AS total FROM device_baseline_sample').get().total,1);
        assert.equal(controllerDb.prepare('SELECT count(*) AS total FROM device_event_source').get().total,1);
        const originals=controllerDb.prepare(`SELECT e.origin_jcs,e.origin_digest,o.body_jcs AS outbox
          FROM device_source_event e JOIN device_source_event_outbox o USING(record_id,transaction_id)`).all();
        assert.equal(originals.length,1);
        const {origin_jcs,origin_digest,outbox}=originals[0],event=result.simulatorEvent.event;
        assert.deepEqual({origin:JSON.parse(origin_jcs),origin_digest},event);
        assert.equal(digest(event.origin),origin_digest);
        assert.deepEqual(JSON.parse(outbox).origin,event.origin);
        assert.equal(controllerDb.prepare("SELECT count(*) AS total FROM device_module_frame WHERE message_type='EVENT_ACKED'").get().total,1);
        assert.equal(controllerDb.prepare('SELECT count(*) AS total FROM command_settlement').get().total,1);
        const revoked=controllerDb.prepare('SELECT reference_jcs FROM device_subscription_scope_revocation WHERE scope_id=?')
          .get(result.simulatorEvent.scope_ref.entity_id);
        assert.deepEqual(JSON.parse(revoked.reference_jcs),result.simulatorEvent.scope_ref);
      }finally{log.close();controllerDb.close();}
      await managedHost.close();managedHost=null;
      const cleanupDeadline=performance.now()+5000;
      while(fs.readdirSync(channelDirectory).length){
        assert.ok(performance.now()<cleanupDeadline,'Installation socket remained after Controller retirement');
        await delay(20);
      }

      const normalGeneration=crypto.randomUUID(),normalDeployment=path.join(root,'worker-service');
      const normalDist=process.env.LEAFSEAMER_TEST_COMPOSE_CLOCK_DIST;
      const normalManifest='sha256:'+hash(fs.readFileSync(path.join(normalDist,'build-manifest.json')));
      const normalPlan={...workerPlan,controller:{...workerPlan.controller,image:images.controller},
        cgroup:{...workerPlan.cgroup,generation_id:normalGeneration},
        bootstrap:{...workerPlan.bootstrap,controller:{...workerPlan.bootstrap.controller,
          artifact_manifest_ref:{...plan.bootstrap.controller.artifact_manifest_ref}}},
        worker_runtime:{...workerPlan.worker_runtime,distribution:{directory:normalDist,manifest_sha256:normalManifest}}};
      fs.writeFileSync(planPath,JSON.stringify(normalPlan));
      run(process.execPath,[...generate.slice(0,-1),normalDeployment]);await prepareParents(normalGeneration);
      project=projectFor(normalGeneration);composePath=path.join(normalDeployment,'compose.json');
      managedHost=openLinuxComposeHost({...hostOptions,generationDirectory:normalDeployment,installationStore:store});
      created=true;
      await managedHost.startSupervised().catch(error=>{
        throw new Error(compose('logs','--no-color','controller','seamer').trim(),{cause:error});
      });
      const normalDeadline=performance.now()+10000;
      for(;;){
        const logs=compose('logs','--no-color','controller');
        if(logs.includes('"event":"listening"'))break;
        assert.ok(performance.now()<normalDeadline,logs||'Controller CLI did not start with the installation source');
        await delay(50);
      }
      assert.deepEqual(fs.readdirSync(channelDirectory),['installation.sock']);
      assert.equal(managedHost.retire().phase,'retired');created=false;
    }catch(error){failure=error;throw error;}
    finally{
      try{
        await managedHost?.close();managedHost=null;
        sealed?.close();store.close();
      }catch(error){
        if(failure)throw new AggregateError([failure,error],'Compose installation test and cleanup failed');
        throw error;
      }
    }
  }
  if(pairingTest){
    const {completeLinuxComposeFirstPairing}=await import('./fixtures/linux-compose-first-pairing.mjs');
    const {readSimulatorFile}=await import('./fixtures/linux-compose-simulator-subscription.mjs');
    let pairingWorkerRuntime,simulator;
    let pairPlan=plan;
    if(workerControl){
      const directory=path.join(root,'pairing-worker'),channel_directory=path.join(root,'pairing-sockets');
      fs.mkdirSync(directory,{mode:0o711});fs.mkdirSync(channel_directory,{mode:0o755});
      const dist=pairedSimulator?process.env.LEAFSEAMER_COMPOSE_WORKER_FIXTURE_DIST:process.env.LEAFSEAMER_TEST_COMPOSE_CLOCK_DIST;
      const image=pairedSimulator?process.env.LEAFSEAMER_COMPOSE_WORKER_FIXTURE_NODE:process.execPath;
      pairingWorkerRuntime={directory,channel_directory,uid:1001,gid:1001,
        distribution:{directory:dist,manifest_sha256:'sha256:'+hash(fs.readFileSync(path.join(dist,'build-manifest.json')))},
        image:{file:image,sha256:'sha256:'+hash(fs.readFileSync(image))}};
    }
    if(pairedSimulator){
      const {digest}=clockValues,{distribution,image}=pairingWorkerRuntime;
      pairPlan={...plan,controller:{...controller,image:process.env.LEAFSEAMER_COMPOSE_WORKER_FIXTURE_IMAGE},bootstrap:{...plan.bootstrap,
        controller:{...plan.bootstrap.controller,artifact_manifest_ref:{...plan.bootstrap.controller.artifact_manifest_ref,
          digest:digest({controller_build_sha256:distribution.manifest_sha256.slice(7),node_sha256:image.sha256.slice(7)})}}}};
      const rootDir=path.join(root,'paired-simulator');
      const installDir=path.join(rootDir,'installation');
      const {createInstallationStore,openInstallationStore}=await import('../dist/installation-store.mjs');
      fs.mkdirSync(installDir,{recursive:true,mode:0o700});createInstallationStore(installDir);
      const installation=openInstallationStore(installDir);
      let sealed;
      t.after(()=>{try{sealed?.close();}finally{installation.close();}});
      installation.initializeLinuxDeploymentJournal();
      const {sealSimulatorWorker}=await import('./fixtures/linux-worker-materialization.mjs');
      const dist=distribution.directory;
      const {deviceModuleEventProtocol}=await import(pathToFileURL(path.join(dist,'sdk','device-module.mjs')));
      const deviceCount=process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_ARM_PREFLIGHT==='1'?2:1;
      sealed=await sealSimulatorWorker(t,{dist,directory:rootDir,serviceId:controller.service_id,profileId:plan.bootstrap.controller.platform_profile_ref.profile_id,
        protocol:deviceModuleEventProtocol,store:installation,deviceCount});
      simulator={installation,installDir,intakeRef:sealed.intakeRef,launchId:crypto.randomUUID()};
    }
    async function launch(pairing){
      const id=crypto.randomUUID(),generationDirectory=path.join(root,id);
      fs.writeFileSync(planPath,JSON.stringify({...pairPlan,pairing,cgroup:{...plan.cgroup,generation_id:id},
        ...(pairingWorkerRuntime&&{worker_runtime:pairingWorkerRuntime})}));
      run(process.execPath,[...generate.slice(0,-1),generationDirectory]);
      await prepareParents(id);
      let simulatorFiles=null;
      if(simulator){
        const {linuxContainerCgroup}=await import('../dist/linux-cgroup-retirement.mjs');
        const parent=linuxContainerCgroup({driver:'cgroupfs',generationId:id,role:'controller'}).groupPath;
        const {launchId,intakeRef}=simulator;
        const group_path=parent+'/worker_'+launchId.replaceAll('-',''),groupFile='/sys/fs/cgroup'+group_path;
        fs.mkdirSync(groupFile);groups.unshift(groupFile);
        const {dev,ino}=fs.statSync(groupFile,{bigint:true}),boot_id=fs.readFileSync('/proc/sys/kernel/random/boot_id','utf8').trim();
        const containment={backend:'linux_cgroup_v2',generation:id,
          group_id:'group_'+clockValues.digest({boot_id,group_path,group:{device:String(dev),inode:String(ino)}}).slice(7)};
        const data='/var/lib/leafseamer',fileFor=name=>path.join(data,name);
        const paired={login,ready:fileFor('simulator-ready.json'),proceed:fileFor('simulator-write'),finish:fileFor('simulator-finish'),
          runApproval:process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_RUN_APPROVAL==='1',
          armPreflight:process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_ARM_PREFLIGHT==='1',
          armCompletion:process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_ARM_COMPLETION==='1'};
        const start=fileFor('worker-start'),result=fileFor('worker-result.json');
        fs.writeFileSync(path.join(controller.data_dir,'worker-test.json'),clockValues.canonical({
          policy:pairPlan.bootstrap.controller,launchId,containment,channelDirectory:'/run/leafseamer-worker',data,start,result,intakeRef,paired
        }),{mode:0o640});
        owned(path.join(controller.data_dir,'worker-test.json'));
        const hostFile=file=>path.join(controller.data_dir,path.basename(file));
        simulatorFiles={start:hostFile(start),result:hostFile(result),ready:hostFile(paired.ready),
          proceed:hostFile(paired.proceed),finish:hostFile(paired.finish),groupFile};
      }
      await managedHost?.close();
      managedHost=openLinuxComposeHost({...hostOptions,generationDirectory,
        ...(simulator&&{installationDirectory:simulator.installDir,installationStore:simulator.installation})});
      project=projectFor(id,simulator?.installation.identity.host_installation_id);composePath=path.join(generationDirectory,'compose.json');created=true;
      const {record,admissions}=await managedHost.startSupervised();
      if(simulatorFiles)fs.writeFileSync(simulatorFiles.start,'');
      for(const role of ['controller','seamer']){
        const limit=performance.now()+5000;
        while(!bindClockPublisher(role,admissions[role].descriptor)){
          if(simulatorFiles)readSimulatorFile(simulatorFiles,'ready');
          assert.ok(performance.now()<limit,role+' clock challenge did not arrive');
          await delay(50);
        }
        clocks[role].publish();
      }
      let renewalFailure=null,phase=record.phase;
      const renew=setInterval(()=>{
        try{for(const role of ['controller','seamer'])clocks[role].publish();}
        catch(error){renewalFailure=error;clearInterval(renew);}
      },1200);
      const containers=record.detail.runtime_binding.containers;
      return {containers,inbox:path.join(generationDirectory,'first-pairing'),phase:()=>phase,
        simulator:simulatorFiles,
        events:role=>docker('logs',containers[role]).split('\n').filter(line=>line.startsWith('{')).map(line=>JSON.parse(line)),
        async stop(){
          clearInterval(renew);
          try{
            phase=managedHost.retire().phase;
            assert.equal(phase,'retired');
            created=false;
          }finally{await managedHost.close();managedHost=null;}
          assert.ifError(renewalFailure);
        }};
    }
    let verifyBrowser=null;
    if(process.env.LEAFSEAMER_TEST_COMPOSE_BROWSER){
      verifyBrowser=async()=>{
        // Playwright 将页面求值函数序列化，与受保护核心的入口独立运行。
        const browser=spawn(process.execPath,[file('./fixtures/linux-compose-browser.mjs')],{
          stdio:['pipe','pipe','pipe'],signal:AbortSignal.timeout(65000)
        });
        let output='',diagnostic='';
        browser.stdout.setEncoding('utf8').on('data',chunk=>output+=chunk);
        browser.stderr.setEncoding('utf8').on('data',chunk=>diagnostic+=chunk);
        const closed=once(browser,'close');
        browser.stdin.on('error',()=>{});
        browser.stdin.end(JSON.stringify({origin,management:{certificate_file:management.certificate_file},login,
          seamer:{service_id:seamer.service_id,database_instance_id:seamer.database_instance_id}}));
        assert.equal((await closed)[0],0,diagnostic);
        return JSON.parse(output);
      };
    }
    await completeLinuxComposeFirstPairing({root,plan:pairPlan,enrollment,login,clockValues,launch,send,selection:manifest.selection,verifyBrowser,
      verifyLocalExtension:!!pairingWorkerRuntime&&!pairedSimulator,pairedSimulator});
    if(pairedSimulator)t.diagnostic('同代模拟器来源原件、Seamer 摄取和 Controller 确认已核对');
    if(process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_PUBLICATION==='1')t.diagnostic('模拟器定义发布、审批原件和未布防运行已核对');
    if(process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_RUN_APPROVAL==='1')t.diagnostic('模拟器运行的人类审批、Controller 认可和布防前置观察已核对');
    if(process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_ARM_PREFLIGHT==='1')t.diagnostic('受保护资格下的模拟器布防预检已持久记录');
    if(process.env.LEAFSEAMER_TEST_COMPOSE_SIMULATOR_ARM_COMPLETION==='1')t.diagnostic('模拟器正式布防、目标准备和基线封存已核对');
  }
});

function checkReferenceCaptures(db,role,key,packets,settings,qualified,nts){
  const rows=db.prepare(`SELECT c.ciphertext,c.nonce,c.tag,c.body_jcs,r.body_jcs AS reservation,x.confirmation_jcs AS acknowledgement,
    a.body_jcs AS attempt FROM time_provider_capture c JOIN time_provider_poll_reservation r USING(poll_id)
    JOIN time_provider_poll_attempt a USING(poll_id) JOIN time_provider_poll_release x USING(poll_id) ORDER BY c.rowid`).all();
  assert.equal(rows.length,role==='controller'?1:2);
  assert.equal(db.prepare('SELECT count(*) AS count FROM time_provider_poll_attempt').get().count,rows.length);
  let previous;
  for(const [index,row] of rows.entries()){
    const capture=JSON.parse(row.body_jcs),reservation=JSON.parse(row.reservation),attempt=JSON.parse(row.attempt);
    const ack=JSON.parse(row.acknowledgement);
    assert.equal(reservation.authorization.configuration_ref.digest,settings.approval_sha256);
    if(!qualified) assert.equal(reservation.authorization.approval_ref.digest,settings.approval_sha256);
    assert.equal(ack.type,'POLL_STORED_ACK');assert.equal(ack.receipt.capture_ref.id,capture.capture_id);
    assert.equal(ack.receipt.plaintext_digest,capture.plaintext_digest);
    const decipher=crypto.createDecipheriv('aes-256-gcm',key,row.nonce);decipher.setAuthTag(row.tag);
    decipher.setAAD(Buffer.from(row.body_jcs));
    const plain=Buffer.concat([decipher.update(row.ciphertext),decipher.final()]);
    try{
      assert.equal('sha256:'+hash(plain),capture.plaintext_digest);
      const candidate=JSON.parse(plain.toString('utf8'));
      if(nts){
        assert.equal(reservation.reserved_bytes,114688);
        assert.equal(reservation.authorization.poll_lease_ns,'5000000000');
        const ke=Buffer.from(candidate.key_reply,'base64url');
        try{
          assert.equal(candidate.key_reply_digest,'sha256:'+hash(ke));
          const records=[];
          for(let offset=0;offset<ke.length;){
            assert.ok(ke.length-offset>=4);
            const type=ke.readUInt16BE(offset)&0x7fff,length=ke.readUInt16BE(offset+2);
            assert.ok(offset+4+length<=ke.length);records.push(type);offset+=4+length;
          }
          assert.ok([1,4,5].every(type=>records.includes(type)));
          assert.equal(records.at(-1),0);
          const request=Buffer.from(candidate.request,'base64url'),response=Buffer.from(candidate.response,'base64url');
          assert.ok(request.length>48&&response.length>48);
          assert.deepEqual(request.subarray(40,48),response.subarray(24,32));
          assert.equal(request.readUInt16BE(48),0x0104);
          assert.equal(response.readUInt16BE(48),0x0104);
          assert.deepEqual(request.subarray(52,84),response.subarray(52,84));
        }finally{ke.fill(0);}
      }else assert.equal(packets.get(candidate.request),candidate.response);
      assert.ok(BigInt(candidate.m1_tick_ns)>=BigInt(attempt.attempted_tick_ns));
      if(previous)assert.ok(BigInt(candidate.m1_tick_ns)-BigInt(previous.m4_tick_ns)>=16000000000n);
      previous=candidate;
      const anchors=db.prepare('SELECT body_jcs,body_digest FROM time_provider_reference_anchor WHERE capture_id=?').all(capture.capture_id);
      assert.equal(anchors.length,qualified&&index===0?1:0);
      if(anchors.length){
        const [{body_jcs,body_digest}]=anchors,anchor=JSON.parse(body_jcs);
        assert.equal(body_digest,'sha256:'+hash(body_jcs));
        const packed=anchor.reference_bundle;
        const bundle=JSON.parse(inflateRawSync(Buffer.from(packed.body,'base64url'))).bundle;
        assert.equal(packed.digest,bundle.bundle_digest);
        assert.deepEqual(bundle.anchor.utc_at_anchor,{lower_ns:anchor.lower_utc_ns,upper_ns:anchor.upper_utc_ns});
        assert.equal(bundle.exchange.parser_receipt_ref.id,capture.capture_id);
        assert.deepEqual(bundle.era.independent_time_ref,anchor.qualification_original.clock_sample.acquisition_ref);
        const authority=db.prepare('SELECT id,revision,digest FROM authentication_clock_acquisition WHERE id=? AND service_boot_id=?')
          .get(bundle.era.independent_time_ref.id,anchor.service_boot_id);
        assert.deepEqual({...authority},bundle.era.independent_time_ref);
        assert.equal(bundle.error.upstream_age_upper_at_m1_ns,anchor.evidence.upstream_age_at_m1_ns);
        assert.ok(BigInt(anchor.evidence.upstream_age_at_m1_ns)>1000000000n);
        assert.ok(BigInt(anchor.published_tick_ns)>=BigInt(anchor.m4_tick_ns));
      }
    }finally{plain.fill(0);}
  }
  if(qualified&&role==='controller'){
    const failures=db.prepare('SELECT cause FROM time_provider_reference_invalidation').all();
    assert.deepEqual(failures.map(row=>row.cause),['authority_changed']);
  }
}

function seedPreviousReferenceBinding(db,role,identity){
  const id=crypto.randomUUID(),next=()=>crypto.randomUUID();
  const {service_id,database_instance_id}=identity;
  const core={receipt_id:next(),bootstrap_id:next(),member_boot_id:next(),gate_state:'closed'};
  const descriptor={clock_backend_id:'windows_interrupt_precise'},provider={receipt_id:next(),bootstrap_id:next(),member_boot_id:next()};
  const time=JSON.stringify({format:'leafseamer-time-provider-runtime-binding/1',service_id,database_instance_id,service_boot_id:id,
    core_receipt_id:core.receipt_id,runtime_binding_id:next(),launch_intent:{launch_id:next(),role:'time_provider'},
    clock_domain_descriptor:descriptor,admission_receipt:provider,gate_state:'closed'});
  const digest='sha256:'+hash(time),body=JSON.parse(time);
  const started=new Date().toISOString();
  if(role==='controller')db.prepare("INSERT INTO service_boot VALUES(?,?,?,?,NULL,'started')").run(service_id,database_instance_id,id,started);
  else db.prepare("INSERT INTO service_boot VALUES(?,?,?,'started')").run(service_id,database_instance_id,id);
  db.prepare('INSERT INTO core_runtime_binding VALUES(?,?,?,?,?,?,?,?)').run(id,core.receipt_id,core.bootstrap_id,core.member_boot_id,
    JSON.stringify({role:'core',service_id}),JSON.stringify(descriptor),JSON.stringify(core),JSON.stringify({service_id,database_instance_id}));
  db.prepare('INSERT INTO time_provider_runtime_binding VALUES(?,?,?,?,?,?,?,?)').run(id,body.runtime_binding_id,body.launch_intent.launch_id,
    provider.receipt_id,provider.bootstrap_id,provider.member_boot_id,time,digest);
  if(role==='controller')db.prepare("UPDATE service_boot SET state='stopped',stopped_utc=? WHERE service_boot_id=?").run(started,id);
  else db.prepare("UPDATE service_boot SET state='stopped' WHERE service_boot_id=?").run(id);
  return {id,text:time,digest};
}
