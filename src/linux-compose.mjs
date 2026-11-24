#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {isIP} from 'node:net';
import {fileURLToPath} from 'node:url';
import {readDeploymentFile,renderLinuxIngress} from './linux-ingress.mjs';
import {linuxContainerCgroup} from './linux-cgroup-retirement.mjs';
import {canonical} from './import-input.mjs';
import {validateLinuxBootstrapPolicy} from './linux-member-bootstrap.mjs';

const runtime='/etc/leafseamer';
const data='/var/lib/leafseamer';
const guiMount='/opt/leafseamer/gui';
const certificate=runtime+'/tls/certificate.pem',privateKey=runtime+'/tls/private-key.pem';
const clockKey=runtime+'/clock-public.pem',clockExchange='/run/leafseamer-clock';
const pairingMount=runtime+'/pairing';
const pairingInbox='/run/leafseamer-first-pairing';
export const composePairingLabel='io.leafseamer.pairing-inputs';
const httpsPort=8443;
const channelHelper=fileURLToPath(new URL('./native/leafseamer_linux_compose_channel',import.meta.url));
const json=value=>JSON.stringify(value,null,2)+'\n';
const fail=code=>{throw Object.assign(new Error(code),{code});};
const need=(condition,code)=>{if(!condition)fail(code);};
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const contained=(directory,file)=>file===directory||file.startsWith(directory+'/');
const id=value=>Number.isSafeInteger(value)&&value>0&&value<4294967295;
const validImage=value=>typeof value==='string'&&value.length<=255&&
  /^(?:[a-z0-9][a-z0-9._:/-]*@)?sha256:[0-9a-f]{64}$(?![\s\S])/.test(value);
const port=value=>Number.isInteger(value)&&value>0&&value<=65535;

function absolute(value){
  need(typeof value==='string'&&value.length<=512&&/^\/[A-Za-z0-9_./ -]+$(?![\s\S])/.test(value)&&
    path.posix.normalize(value)===value&&value!=='/'&&!value.endsWith('/'),'compose_path');
  return value;
}
function existing(value,kind){
  const location=absolute(value);
  need(fs.realpathSync(location)===location,'compose_path');
  const stat=fs.statSync(location);
  need(kind==='directory'?stat.isDirectory():stat.isFile()&&stat.size>0,'compose_path');
  return location;
}
function inode(stat){return stat.dev+':'+stat.ino;}
function fileInode(file){return inode(fs.statSync(file,{bigint:true}));}
function rootControlledParents(location,code='compose_clock_scope'){
  for(let parent=path.posix.dirname(location);parent!=='/';parent=path.posix.dirname(parent)){
    const stat=fs.lstatSync(parent);
    const sticky=['/tmp','/var/tmp'].includes(parent)&&(stat.mode&0o1000)!==0;
    need(stat.isDirectory()&&stat.uid===0&&((stat.mode&0o022)===0||sticky),code);
  }
}

export function verifyLinuxComposeClockInputs(plan){
  if(!Object.hasOwn(plan,'clock_evidence'))return null;
  need(process.platform==='linux'&&process.geteuid()===0&&plan.cgroup?.namespace==='private'&&
    fields(plan.bootstrap,'controller,seamer')&&fields(plan.clock_evidence,'controller,seamer'),'compose_clock_scope');
  const witnesses={};
  for(const role of ['controller','seamer']){
    const config=plan.clock_evidence[role];
    need(fields(config,'exchange_directory,policy_digest,public_key_file,public_key_sha256')&&
      [config.policy_digest,config.public_key_sha256].every(value=>typeof value==='string'&&/^sha256:[a-f0-9]{64}$(?![\s\S])/.test(value)),
      'compose_clock_scope');
    const directory=existing(config.exchange_directory,'directory'),file=existing(config.public_key_file,'file');
    rootControlledParents(directory);rootControlledParents(file);
    const exchange=fs.lstatSync(directory,{bigint:true}),key=fs.lstatSync(file,{bigint:true});
    need(exchange.isDirectory()&&exchange.uid===BigInt(plan[role].uid)&&exchange.gid===BigInt(plan[role].gid)&&
      (exchange.mode&0o777n)===0o700n&&key.isFile()&&key.uid===0n&&(key.mode&0o022n)===0n&&
      (key.mode&0o004n)!==0n,'compose_clock_scope');
    const bytes=readDeploymentFile(file,16384);
    need(/^-----BEGIN PUBLIC KEY-----\r?\n[A-Za-z0-9+/=\r\n]+-----END PUBLIC KEY-----\r?\n?$(?![\s\S])/.test(bytes.toString('ascii'))&&
      'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex')===config.public_key_sha256,'compose_clock_key');
    let keyObject;
    try{keyObject=crypto.createPublicKey(bytes);}
    catch{fail('compose_clock_key');}
    need(keyObject.asymmetricKeyType==='ed25519','compose_clock_key');
    witnesses[role]={exchange_inode:inode(exchange),key_inode:inode(key)};
  }
  return witnesses;
}
export function verifyLinuxComposePairingInputs(plan,excluded=[]){
  if(!Object.hasOwn(plan,'pairing'))return null;
  need(process.platform==='linux'&&process.geteuid()===0&&plan.cgroup?.namespace==='private'&&
    Object.hasOwn(plan,'clock_evidence')&&fields(plan.pairing,'controller,seamer'),'compose_pairing_scope');
  const witnesses={},profiles={},privateFiles=new Map();
  for(const [role,other] of [['controller','seamer'],['seamer','controller']]){
    const config=plan.pairing[role],scope=plan[role],peer=plan[other];
    const inbox=role==='seamer'&&config?.await_first_pairing===true;
    need(fields(config,inbox?'await_first_pairing,directory,files':'directory,files')&&
      config.files&&typeof config.files==='object'&&!Array.isArray(config.files),'compose_pairing_scope');
    const entries=Object.entries(config.files);
    need(entries.length>=4&&entries.length<=20&&Object.hasOwn(config.files,'profile.json')&&
      entries.every(([name,hash])=>/^[a-z][a-z0-9-]{0,47}\.(?:json|pem)$/.test(name)&&
        typeof hash==='string'&&/^sha256:[a-f0-9]{64}$/.test(hash)),'compose_pairing_scope');
    const directory=existing(config.directory,'directory');
    rootControlledParents(directory+'/profile.json','compose_pairing_scope');
    need(excluded.every(root=>!contained(root,directory)&&!contained(directory,root)),'compose_pairing_scope');
    let profile;
    witnesses[role]={};
    for(const [name,digest] of entries){
      const file=directory+'/'+name,stat=fs.lstatSync(file,{bigint:true});
      need(stat.isFile()&&stat.uid===0n&&(stat.mode&0o022n)===0n&&
        ((stat.mode&0o004n)!==0n||stat.gid===BigInt(scope.gid)&&(stat.mode&0o040n)!==0n),'compose_pairing_scope');
      const bytes=readDeploymentFile(file,65536);
      need('sha256:'+crypto.createHash('sha256').update(bytes).digest('hex')===digest,'compose_pairing_digest');
      if(name==='profile.json')profile=JSON.parse(bytes.toString('utf8'));
      witnesses[role][name]=inode(stat);
    }
    const own=role==='controller'?profile?.bootstrap:profile?.scope;
    const {local,https,public_api}=profile??{},remote=profile?.[other];
    const admin=role==='controller'?https:public_api;
    need(profile?.format==='leafseamer.'+role+'-pairing-profile/2'&&own?.service_id===scope.service_id&&
      own?.database_instance_id===scope.database_instance_id&&remote?.identity?.service_id===peer.service_id&&
      remote.identity.database_instance_id===peer.database_instance_id&&remote.identity.service_kind===other&&
      local?.host===scope.address&&local.port===9443&&local.network===true&&
      remote.origin==='https://'+peer.address+':9443'&&typeof local.server_name==='string'&&
      (role==='controller'?admin?.origin==='https://127.0.0.1:8444'&&canonical(own)===canonical(plan.bootstrap.controller)&&!Object.hasOwn(profile,'gui'):
        admin?.host==='127.0.0.1'&&admin.port===8444&&
        (!inbox||profile.first_pairing_authorization_id===null)),'compose_pairing_scope');
    need(Array.isArray(local.ca_files)&&local.ca_files.length>0&&local.ca_files.length<=8,'compose_pairing_scope');
    const referenced=new Set(['profile.json']);
    for(const entry of [local.certificate_file,local.private_key_file,...local.ca_files,remote.certificate_file,admin.certificate_file,admin.private_key_file]){
      const name=typeof entry==='string'&&entry.startsWith(pairingMount+'/')?entry.slice(pairingMount.length+1):'';
      need(name.endsWith('.pem')&&Object.hasOwn(config.files,name),'compose_pairing_scope');
      referenced.add(name);
    }
    if(role==='seamer'&&Object.hasOwn(profile,'publication_policy')){
      const policy=profile.publication_policy;
      need(fields(policy,'approval_file,approval_sha256')&&typeof policy.approval_file==='string'&&
        policy.approval_file.startsWith(pairingMount+'/')&&typeof policy.approval_sha256==='string','compose_pairing_scope');
      const name=policy.approval_file.slice(pairingMount.length+1);
      need(name!=='profile.json'&&name.endsWith('.json')&&Object.hasOwn(config.files,name),'compose_pairing_scope');
      need(config.files[name]===policy.approval_sha256,'compose_pairing_digest');
      referenced.add(name);
    }
    need(referenced.size===entries.length,'compose_pairing_scope');
    for(const file of [local.private_key_file,admin.private_key_file]){
      const name=path.posix.basename(file),stat=fs.lstatSync(directory+'/'+name);
      need(stat.gid===scope.gid&&(stat.mode&0o777)===0o640&&
        (!privateFiles.has(inode(stat))||privateFiles.get(inode(stat))===role),'compose_pairing_scope');
      privateFiles.set(inode(stat),role);
    }
    profiles[role]=profile;
  }
  for(const [role,files] of Object.entries(witnesses))for(const file of Object.values(files))
    need(!privateFiles.has(file)||privateFiles.get(file)===role,'compose_pairing_scope');
  const {controller,seamer}=profiles;
  need(controller.seamer.identity.credential_id===seamer.local.credential_id&&seamer.controller.identity.credential_id===controller.local.credential_id&&
    controller.seamer.server_name===seamer.local.server_name&&seamer.controller.server_name===controller.local.server_name&&
    controller.seamer.trust_bundle_digest===seamer.controller.trust_bundle_digest,'compose_pairing_scope');
  return witnesses;
}
function ipv4(value){
  need(isIP(value)===4,'compose_network');
  return value.split('.').reduce((number,part)=>number*256+Number(part),0);
}
function checkNetwork(subnet,addresses){
  need(typeof subnet==='string'&&/^(?:[0-9]{1,3}\.){3}[0-9]{1,3}\/(?:1[6-9]|2[0-9])$(?![\s\S])/.test(subnet),'compose_network');
  const [network,bits]=subnet.split('/'),base=ipv4(network),size=2**(32-Number(bits)),end=base+size;
  const privateRanges=[['10.0.0.0','11.0.0.0'],['172.16.0.0','172.32.0.0'],['192.168.0.0','192.169.0.0']];
  need(base%size===0&&privateRanges.some(([low,high])=>base>=ipv4(low)&&end<=ipv4(high))&&
    new Set(addresses).size===addresses.length&&addresses.every(address=>{const host=ipv4(address);return host>=base+2&&host<end-1;}),'compose_network');
}
function tlsFiles(record){
  return [existing(record.certificate_file,'file'),existing(record.private_key_file,'file')];
}
function bind(source,target,readOnly=true){
  return {type:'bind',source,target,read_only:readOnly,bind:{create_host_path:false}};
}
function container(record){
  need(validImage(record.image)&&id(record.uid)&&id(record.gid),'compose_image_or_user');
  return {image:record.image,platform:'linux/amd64',pull_policy:'never',user:record.uid+':'+record.gid,read_only:true,
    cap_drop:['ALL'],security_opt:['no-new-privileges:true'],restart:'no',stop_grace_period:'10s',
    tmpfs:['/tmp:rw,noexec,nosuid,nodev,mode=1777,size=67108864'],logging:{driver:'local'}};
}
function member(role,record,origin,output){
  return {
    profile:{format:'leafseamer.'+role+'-protected-ingress/1',address:record.address,port:httpsPort,origin,
      service_id:record.service_id,database_instance_id:record.database_instance_id,certificate_file:certificate,private_key_file:privateKey},
    service:{...container(record),entrypoint:['/usr/local/bin/node','--disallow-code-generation-from-strings','/opt/leafseamer/dist/cli.mjs'],
      command:['start-protected-ingress','--data-dir',data,'--ingress-profile',runtime+'/ingress.json'],
      volumes:[bind(record.data_dir,data,false),bind(output+'/'+role+'-ingress.json',runtime+'/ingress.json'),
        bind(record.certificate_file,certificate),bind(record.private_key_file,privateKey)],
      networks:{backend:{ipv4_address:record.address}}}
  };
}

export function renderLinuxCompose(plan,output){
  absolute(output);
  const withCgroup=plan!==null&&typeof plan==='object'&&Object.hasOwn(plan,'cgroup');
  const withBootstrap=plan!==null&&typeof plan==='object'&&Object.hasOwn(plan,'bootstrap');
  const withClock=plan!==null&&typeof plan==='object'&&Object.hasOwn(plan,'clock_evidence');
  const withPairing=plan!==null&&typeof plan==='object'&&Object.hasOwn(plan,'pairing');
  need(fields(plan,(withBootstrap?'bootstrap,':'')+(withCgroup?'cgroup,':'')+(withClock?'clock_evidence,':'')+
    'controller,format,gui,management,nginx,'+(withPairing?'pairing,':'')+'seamer,subnet')&&
    plan.format==='leafseamer.linux-compose-protected/1','compose_plan');
  const {controller,seamer,nginx,management,gui,subnet,cgroup}=plan;
  const memberFields='address,ca_file,certificate_file,data_dir,database_instance_id,gid,image,private_key_file,server_name,service_id,uid';
  need(fields(controller,memberFields)&&fields(seamer,memberFields)&&fields(nginx,'address,gid,image,uid')&&
    fields(management,'bind_address,certificate_file,host,port,private_key_file')&&fields(gui,'directory,manifest_sha256'),'compose_plan');
  checkNetwork(subnet,[controller.address,seamer.address,nginx.address]);
  need(isIP(management.bind_address)>0&&port(management.port),'compose_management');
  const direct=[controller,seamer];
  const [controllerData,seamerData,guiDirectory]=[...direct.map(record=>existing(record.data_dir,'directory')),existing(gui.directory,'directory')];
  const roots=[controllerData,seamerData,guiDirectory,output];
  need(roots.every((dir,index)=>roots.every((other,i)=>i===index||!contained(dir,other))),'compose_path_overlap');
  const certs=[management,...direct].map(tlsFiles);
  const cas=direct.map(record=>existing(record.ca_file,'file'));
  const keys=certs.map(([,key])=>key),publicFiles=[...certs.map(([cert])=>cert),...cas];
  const keyInodes=keys.map(fileInode),publicInodes=new Set(publicFiles.map(fileInode));
  need(new Set(keyInodes).size===keys.length&&keyInodes.every(key=>!publicInodes.has(key))&&
    [...keys,...publicFiles].every(file=>roots.every(dir=>!contained(dir,file))),'compose_tls_scope');
  need(controller.service_id!==seamer.service_id&&controller.database_instance_id!==seamer.database_instance_id,'compose_identity');
  const caPath=role=>runtime+'/tls/'+role+'-ca.pem';
  const config=renderLinuxIngress({format:'leafseamer.linux-ingress/1',gui,issuer_service_id:controller.service_id,
    management:{address:'0.0.0.0',port:management.port,host:management.host,certificate_file:certificate,private_key_file:privateKey},
    services:['controller','seamer'].map((role,i)=>{
      const {service_id,database_instance_id,address,server_name}=direct[i];
      return {role,service_id,database_instance_id,address,server_name,port:httpsPort,ca_file:caPath(role)};
    })
  },{listenPort:httpsPort,guiMount,tempDirectory:'/tmp'});
  const origin='https://'+management.host+(management.port===443?'':':'+management.port);
  const c=member('controller',controller,origin,output),s=member('seamer',seamer,origin,output);
  if(withCgroup){
    const privateNamespace=fields(cgroup,'driver,generation_id,namespace')&&cgroup.namespace==='private';
    need(fields(cgroup,'driver,generation_id')||privateNamespace,'compose_cgroup');
    const scope={driver:cgroup.driver,generationId:cgroup.generation_id};
    c.service.cgroup_parent=linuxContainerCgroup({...scope,role:'controller'}).parent;
    s.service.cgroup_parent=linuxContainerCgroup({...scope,role:'seamer'}).parent;
    if(privateNamespace){c.service.cgroup='private';s.service.cgroup='private';}
  }
  const clockFiles={};
  if(withClock){
    const witnesses=verifyLinuxComposeClockInputs(plan);
    const clocks=Object.values(plan.clock_evidence),directories=clocks.map(clock=>clock.exchange_directory);
    const dataInodes=[controllerData,seamerData,guiDirectory].map(fileInode);
    const exchanges=Object.values(witnesses).map(witness=>witness.exchange_inode);
    const allRoots=[...roots,...directories];
    need(allRoots.every((dir,index)=>allRoots.every((other,i)=>i===index||!contained(dir,other)))&&
      new Set([...exchanges,...dataInodes]).size===exchanges.length+dataInodes.length&&
      Object.values(witnesses).every(witness=>!keyInodes.includes(witness.key_inode))&&
      [...keys,...publicFiles,...clocks.map(clock=>clock.public_key_file)].every(file=>allRoots.every(dir=>!contained(dir,file))),
      'compose_clock_scope');
  }
  if(withPairing){
    const witnesses=verifyLinuxComposePairingInputs(plan,[...roots,...Object.values(plan.clock_evidence??{}).map(clock=>clock.exchange_directory)]);
    need(!contained(plan.pairing.controller.directory,plan.pairing.seamer.directory)&&
      !contained(plan.pairing.seamer.directory,plan.pairing.controller.directory),'compose_pairing_scope');
    need(Object.values(witnesses).every(role=>Object.values(role).every(file=>!keyInodes.includes(file))),'compose_pairing_scope');
  }
  if(withBootstrap){
    need(cgroup?.namespace==='private'&&fields(plan.bootstrap,'controller,seamer'),'compose_bootstrap');
    existing(channelHelper,'file');
    for(const [role,record,{service}]of [['controller',controller,c],['seamer',seamer,s]]){
      const policy=validateLinuxBootstrapPolicy(record,plan.bootstrap[role]);
      service.command=['connect',runtime+'/bootstrap/bootstrap.sock','0','--',...service.entrypoint,
        'contained-compose-linux','--data-dir',data,'--ingress-profile',runtime+'/ingress.json','--bootstrap-policy',canonical(policy)];
      service.entrypoint=[runtime+'/compose-channel'];
      service.init=false;
      service.volumes.push(bind(channelHelper,runtime+'/compose-channel'),bind(output+'/bootstrap-'+role,runtime+'/bootstrap'));
      if(withClock){
        const {exchange_directory,policy_digest,public_key_file}=plan.clock_evidence[role];
        const name=role+'-clock.json',target=runtime+'/clock.json';
        clockFiles[name]=json({format:'leafseamer.'+role+'-linux-clock-evidence-profile/2',service_id:record.service_id,
          database_instance_id:record.database_instance_id,policy_digest,public_key_file:clockKey,exchange_directory:clockExchange});
        service.command.push('--clock-evidence-profile',target);
        service.volumes.push(bind(output+'/'+name,target),bind(public_key_file,clockKey),bind(exchange_directory,clockExchange,false));
      }
      if(withPairing){
        const {directory,files}=plan.pairing[role];
        service.command.push('--pairing-profile',pairingMount+'/profile.json');
        service.labels={[composePairingLabel]:'sha256:'+crypto.createHash('sha256').update(canonical(files)).digest('hex')};
        for(const name of Object.keys(files).sort())service.volumes.push(bind(directory+'/'+name,pairingMount+'/'+name));
        if(role==='seamer'&&plan.pairing.seamer.await_first_pairing){
          service.command.push('--first-pairing-inbox',pairingInbox);
          service.volumes.push(bind(output+'/first-pairing',pairingInbox));
        }
      }
    }
  }
  const proxy={...container(nginx),entrypoint:['/usr/sbin/nginx'],command:['-e','stderr','-p','/tmp/','-c',runtime+'/nginx.conf','-g','daemon off;'],
    volumes:[bind(output+'/nginx.conf',runtime+'/nginx.conf'),bind(gui.directory,guiMount),
      bind(management.certificate_file,certificate),bind(management.private_key_file,privateKey),
      bind(controller.ca_file,caPath('controller')),bind(seamer.ca_file,caPath('seamer'))],
    ports:[{target:httpsPort,published:String(management.port),host_ip:management.bind_address,protocol:'tcp'}],
    networks:{management:{},backend:{ipv4_address:nginx.address}},depends_on:['controller','seamer']};
  const compose={services:{controller:c.service,seamer:s.service,nginx:proxy},
    networks:{management:{driver:'bridge'},backend:{driver:'bridge',internal:true,ipam:{config:[{subnet}]}}}};
  return {'controller-ingress.json':json(c.profile),'seamer-ingress.json':json(s.profile),...clockFiles,'nginx.conf':config,'compose.json':json(compose)};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{
    need(process.platform==='linux'&&process.argv.length===6&&process.argv[2]==='--config'&&process.argv[4]==='--output','compose_arguments');
    const output=absolute(process.argv[5]);
    existing(path.posix.dirname(output),'directory');
    const plan=JSON.parse(readDeploymentFile(absolute(process.argv[3]),65536));
    const files=renderLinuxCompose(plan,output);
    fs.mkdirSync(output,{mode:0o755});
    if(Object.hasOwn(plan,'bootstrap'))for(const role of ['controller','seamer'])fs.mkdirSync(output+'/bootstrap-'+role,{mode:0o755});
    if(plan.pairing?.seamer.await_first_pairing)fs.mkdirSync(output+'/first-pairing',{mode:0o755});
    // Compose 文件最后落盘，只有完整生成后才出现可启动入口。
    for(const [name,bytes] of Object.entries(files))fs.writeFileSync(output+'/'+name,bytes,{flag:'wx',mode:0o644});
  }catch(error){
    const code=/^(?:compose|ingress|cgroup)_[a-z_]+$/.test(error.code??'')?error.code:'compose_input';
    process.stderr.write(json({error:code}));
    process.exitCode=1;
  }
}
