#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {isIP} from 'node:net';
import {fileURLToPath} from 'node:url';
import {readDeploymentFile,renderLinuxIngress} from './linux-ingress.mjs';
import {linuxContainerCgroup} from './linux-cgroup-retirement.mjs';

const runtime='/etc/leafseamer';
const data='/var/lib/leafseamer';
const guiMount='/opt/leafseamer/gui';
const certificate=runtime+'/tls/certificate.pem',privateKey=runtime+'/tls/private-key.pem';
const httpsPort=8443;
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
  need(fields(plan,(withCgroup?'cgroup,':'')+'controller,format,gui,management,nginx,seamer,subnet')&&
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
  const inode=file=>{const {dev,ino}=fs.statSync(file,{bigint:true});return dev+':'+ino;};
  const keyInodes=keys.map(inode),publicInodes=new Set(publicFiles.map(inode));
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
  const proxy={...container(nginx),entrypoint:['/usr/sbin/nginx'],command:['-e','stderr','-p','/tmp/','-c',runtime+'/nginx.conf','-g','daemon off;'],
    volumes:[bind(output+'/nginx.conf',runtime+'/nginx.conf'),bind(gui.directory,guiMount),
      bind(management.certificate_file,certificate),bind(management.private_key_file,privateKey),
      bind(controller.ca_file,caPath('controller')),bind(seamer.ca_file,caPath('seamer'))],
    ports:[{target:httpsPort,published:String(management.port),host_ip:management.bind_address,protocol:'tcp'}],
    networks:{management:{},backend:{ipv4_address:nginx.address}},depends_on:['controller','seamer']};
  const compose={services:{controller:c.service,seamer:s.service,nginx:proxy},
    networks:{management:{driver:'bridge'},backend:{driver:'bridge',internal:true,ipam:{config:[{subnet}]}}}};
  return {'controller-ingress.json':json(c.profile),'seamer-ingress.json':json(s.profile),'nginx.conf':config,'compose.json':json(compose)};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{
    need(process.platform==='linux'&&process.argv.length===6&&process.argv[2]==='--config'&&process.argv[4]==='--output','compose_arguments');
    const output=absolute(process.argv[5]);
    existing(path.posix.dirname(output),'directory');
    const plan=JSON.parse(readDeploymentFile(absolute(process.argv[3]),65536));
    const files=renderLinuxCompose(plan,output);
    fs.mkdirSync(output,{mode:0o755});
    // Compose 文件最后落盘，只有完整生成后才出现可启动入口。
    for(const [name,bytes] of Object.entries(files))fs.writeFileSync(output+'/'+name,bytes,{flag:'wx',mode:0o644});
  }catch(error){
    const code=/^(?:compose|ingress|cgroup)_[a-z_]+$/.test(error.code??'')?error.code:'compose_input';
    process.stderr.write(json({error:code}));
    process.exitCode=1;
  }
}
