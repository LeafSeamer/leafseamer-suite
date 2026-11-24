#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {isIP} from 'node:net';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';

const fail=code=>{throw Object.assign(new Error(code),{code});};
const need=(condition,code)=>{if(!condition)fail(code);};
const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const uuid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$(?![\s\S])/.test(value);
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const checksum=value=>typeof value==='string'&&/^[a-f0-9]{64}$(?![\s\S])/.test(value);
const port=value=>Number.isInteger(value)&&value>=1&&value<=65535;
const dnsName=value=>typeof value==='string'&&isIP(value)===0&&value.length<=253&&
  value.split('.').every(label=>/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$(?![\s\S])/.test(label));
const address=value=>typeof value==='string'&&isIP(value)>0;
const socket=(host,number)=>`${isIP(host)===6?'['+host+']':host}:${number}`;
function absolute(value){
  need(typeof value==='string'&&value.length<=512&&/^\/[A-Za-z0-9_./ -]+$(?![\s\S])/.test(value)&&path.posix.normalize(value)===value&&
    value!=='/'&&!value.endsWith('/'),'ingress_path');
  return value;
}
const quote=value=>'"'+value+'"';
export function readDeploymentFile(file,limit){
  const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  try{
    const stat=fs.fstatSync(fd);need(stat.isFile()&&stat.size>0&&stat.size<=limit,'ingress_file');
    const value=Buffer.alloc(stat.size+1);
    let length=0,count;
    while(length<value.length&&(count=fs.readSync(fd,value,length,value.length-length))>0)length+=count;
    need(length===stat.size,'ingress_file');return value.subarray(0,length);
  }finally{fs.closeSync(fd);}
}
function selection(value){
  return exact(value,'contract_digest,contract_id')&&typeof value.contract_id==='string'&&
    /^leafseamer\.api\.v1\.product[1-9][0-9]*$(?![\s\S])/.test(value.contract_id)&&typeof value.contract_digest==='string'&&
    value.contract_digest.startsWith('sha256:')&&checksum(value.contract_digest.slice(7));
}
function guiAssets(gui,origin,issuer,services){
  need(exact(gui,'directory,manifest_sha256')&&typeof gui.manifest_sha256==='string'&&gui.manifest_sha256.startsWith('sha256:')&&
    checksum(gui.manifest_sha256.slice(7)),'ingress_gui');
  const root=absolute(gui.directory),bytes=readDeploymentFile(root+'/gui-manifest.json',65536);
  need(gui.manifest_sha256==='sha256:'+hash(bytes),'ingress_gui_manifest');
  const manifest=JSON.parse(bytes);
  need(exact(manifest,'artifacts,format,sdk_manifest_sha256,selection')&&manifest.format==='leafseamer.gui.build/1'&&
    checksum(manifest.sdk_manifest_sha256)&&selection(manifest.selection)&&manifest.artifacts&&typeof manifest.artifacts==='object'&&
    !Array.isArray(manifest.artifacts),'ingress_gui_manifest');
  const entries=Object.entries(manifest.artifacts).sort(([a],[b])=>a<b?-1:a>b?1:0);
  need(entries.length>=4&&entries.length<=128,'ingress_gui_manifest');
  let site=null,total=0;
  for(const [file,digest] of entries){
    need(/^(index\.html|site\.json|SDK-LICENSE\.txt|THIRD-PARTY-LICENSES\.txt|assets\/[A-Za-z0-9_-]+\.(?:js|css))$(?![\s\S])/.test(file)&&checksum(digest),'ingress_gui_asset');
    const content=readDeploymentFile(root+'/'+file,file==='site.json'?32768:16777216);total+=content.length;
    need(total<=33554432&&hash(content)===digest,'ingress_gui_digest');
    if(file==='site.json')site=JSON.parse(content);
  }
  const listed=entries.map(([file])=>file);
  need(listed.includes('index.html')&&listed.includes('SDK-LICENSE.txt')&&listed.some(file=>file.endsWith('.js'))&&listed.some(file=>file.endsWith('.css'))&&
    site&&['leafseamer.gui.site/1','leafseamer.gui.site/2','leafseamer.gui.site/3'].includes(site.format)&&site.service_id===issuer.service_id&&
    site.database_instance_id===issuer.database_instance_id&&selection(site.selection)&&site.selection.contract_id===manifest.selection.contract_id&&
    site.selection.contract_digest===manifest.selection.contract_digest,'ingress_gui_scope');
  if(site.seamer!==undefined&&site.seamer!==null){
    const seamer=services.find(service=>service.role==='seamer'&&service.service_id===site.seamer.service_id);
    need(seamer&&seamer.database_instance_id===site.seamer.database_instance_id&&site.seamer.base_url===origin+'/services/'+seamer.service_id,'ingress_gui_scope');
  }
  return {root,listed};
}

const csp="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
function staticLocation(route,file){
  const type={'.html':'text/html','.json':'application/json','.js':'text/javascript','.css':'text/css','.txt':'text/plain'}[path.posix.extname(file)];
  return `    location = ${route} {
      alias ${quote(file)};
      default_type ${type};
      disable_symlinks on;
      if ($request_method !~ ^(?:GET|HEAD)$) { return 405; }
      add_header Cache-Control "no-store" always;
      add_header Content-Security-Policy ${quote(csp)} always;
      add_header X-Content-Type-Options nosniff always;
      add_header Referrer-Policy no-referrer always;
      add_header X-Frame-Options DENY always;
    }`;
}
function proxyLocation(route,upstream,service,authority,websocket=false){
  const readOnly=websocket||upstream==='/.well-known/leafseamer-contracts';
  const upstreamHost=service.role==='controller'?authority:socket(service.address,service.port);
  const events=websocket?`
      proxy_set_header Upgrade $leaf_upgrade;
      proxy_set_header Connection $leaf_connection;
      proxy_read_timeout 60s;`:`
      proxy_set_header Connection "";
      proxy_set_header Upgrade "";`;
  return `    location ${route} {
${readOnly?'      if ($request_method !~ ^(?:GET|HEAD)$) { return 405; }\n':''}      client_max_body_size ${service.role==='controller'?'16k':'16m'};
      proxy_pass https://${socket(service.address,service.port)}${upstream};
      proxy_ssl_server_name on;
      proxy_ssl_name ${service.server_name};
      proxy_ssl_trusted_certificate ${quote(service.ca_file)};
      proxy_ssl_verify on;
      proxy_set_header Host ${quote(upstreamHost)};
      proxy_set_header Origin $http_origin;
${upstream.startsWith('/auth/')?'':'      proxy_set_header Cookie "";\n'}      proxy_set_header Forwarded "";
      proxy_set_header X-Forwarded-For "";
      proxy_set_header X-Forwarded-Host "";
      proxy_set_header X-Forwarded-Proto "";
      proxy_set_header X-Forwarded-Port "";
      proxy_set_header X-Real-IP "";${events}
      proxy_hide_header Cache-Control;
      add_header Cache-Control "no-store" always;
      add_header X-Content-Type-Options nosniff always;
    }`;
}

export function renderLinuxIngress(plan,{listenPort,guiMount,tempDirectory}={}){
  need(exact(plan,'format,gui,issuer_service_id,management,services')&&plan.format==='leafseamer.linux-ingress/1'&&uuid(plan.issuer_service_id),'ingress_plan');
  const {management:m,services}=plan;
  need(exact(m,'address,certificate_file,host,port,private_key_file')&&address(m.address)&&dnsName(m.host)&&port(m.port),'ingress_management');
  const certificate=absolute(m.certificate_file),key=absolute(m.private_key_file),authority=m.host+(m.port===443?'':':'+m.port);
  const listener=listenPort??m.port;
  need(port(listener),'ingress_management');
  need(Array.isArray(services)&&services.length>=1&&services.length<=32,'ingress_services');
  const ids=new Set();
  for(const service of services){
    need(exact(service,'address,ca_file,database_instance_id,port,role,server_name,service_id')&&uuid(service.service_id)&&uuid(service.database_instance_id)&&
      !ids.has(service.service_id)&&['controller','seamer'].includes(service.role)&&address(service.address)&&port(service.port)&&dnsName(service.server_name)&&
      socket(service.address,service.port)!==socket(m.address,listener),'ingress_service');
    absolute(service.ca_file);ids.add(service.service_id);
  }
  const issuer=services.find(service=>service.service_id===plan.issuer_service_id&&service.role==='controller');need(issuer,'ingress_issuer');
  const {root,listed}=guiAssets(plan.gui,'https://'+authority,issuer,services);
  const assetRoot=guiMount===undefined?root:absolute(guiMount);
  const scratch=tempDirectory===undefined?null:absolute(tempDirectory);
  const tempPaths=scratch===null?'':['client_body','proxy','fastcgi','uwsgi','scgi'].map(kind=>
    '  '+kind+'_temp_path '+quote(scratch+'/'+kind)+';\n').join('');
  const locations=listed.map(file=>staticLocation('/'+file,assetRoot+'/'+file));
  locations.push('    location = / { rewrite ^ /index.html last; }');
  for(const auth of ['/auth/sessions','/auth/sessions/refresh','/auth/sessions/current','/auth/service-tokens'])
    locations.push(proxyLocation('= '+auth,auth,issuer,authority));
  // 当前同源 GUI 使用签发 Controller 的 /api/v1/。逐服务路径始终固定为配置中的服务。
  locations.push(proxyLocation('= /api/v1/events','/api/v1/events',issuer,authority,true),proxyLocation('^~ /api/v1/','/api/v1/',issuer,authority));
  for(const service of services){
    const prefix='/services/'+service.service_id;
    locations.push(proxyLocation('= '+prefix+'/.well-known/leafseamer-contracts','/.well-known/leafseamer-contracts',service,authority),
      proxyLocation('= '+prefix+'/api/v1/events','/api/v1/events',service,authority,true),proxyLocation('^~ '+prefix+'/api/v1/','/api/v1/',service,authority));
  }
  return `worker_processes 1;
error_log stderr crit;
pid nginx.pid;
events { worker_connections 256; }
http {
  access_log off;
  server_tokens off;
  client_header_timeout 5s;
  client_body_timeout 5s;
  client_header_buffer_size 2k;
  large_client_header_buffers 4 4k;
  proxy_http_version 1.1;
  proxy_connect_timeout 3s;
  proxy_send_timeout 10s;
  proxy_read_timeout 10s;
  proxy_next_upstream off;
  proxy_intercept_errors off;
  proxy_redirect off;
  proxy_cache off;
  proxy_ssl_protocols TLSv1.2 TLSv1.3;
  map $http_upgrade $leaf_upgrade { default ""; ~*^websocket$ websocket; }
  map $leaf_upgrade $leaf_connection { default upgrade; "" ""; }
${tempPaths}  server {
    listen ${socket(m.address,listener)} ssl default_server;
    ssl_reject_handshake on;
    return 421;
  }
  server {
    listen ${socket(m.address,listener)} ssl;
    server_name ${m.host};
    ssl_certificate ${quote(certificate)};
    ssl_certificate_key ${quote(key)};
    ssl_protocols TLSv1.2 TLSv1.3;
    if ($http_host != ${quote(authority)}) { return 421; }
${locations.join('\n')}
    location / { return 404; }
  }
}
`;
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{
    need(process.argv.length===4&&process.argv[2]==='--config','ingress_arguments');
    const plan=JSON.parse(readDeploymentFile(absolute(process.argv[3]),65536));
    process.stdout.write(renderLinuxIngress(plan));
  }catch(error){
    const code=/^ingress_[a-z_]+$/.test(error.code??'')?error.code:'ingress_input';
    process.stderr.write(JSON.stringify({error:code})+'\n');process.exitCode=1;
  }
}
