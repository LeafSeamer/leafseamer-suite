import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url)), options={},args=process.argv.slice(2);
if(args.length!==4)throw new Error('native_build_arguments');
for(let i=0;i<args.length;i+=2){if(!['--headers','--node-library'].includes(args[i])||options[args[i]]||!path.isAbsolute(args[i+1]))throw new Error('native_build_arguments');options[args[i]]=args[i+1];}
const input=JSON.parse(fs.readFileSync(path.join(root,'native-inputs.json'))),hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
if(process.platform!=='win32'||process.arch!=='x64'||process.versions.node!==input.node_version)throw new Error('native_build_platform');
for(const [name,digest] of Object.entries(input.headers))if(hash(fs.readFileSync(path.join(options['--headers'],name)))!==digest)throw new Error('native_headers_mismatch');
if(hash(fs.readFileSync(options['--node-library']))!==input.windows_x64_node_lib)throw new Error('native_library_mismatch');
const output=path.join(root,'logs/installation-peer/build'),artifact=path.join(root,'logs/installation-peer/artifacts');
for(const command of [['-S',path.join(root,'native'),'-B',output,'-G','Visual Studio 17 2022','-A','x64','-DNODE_INCLUDE_DIR='+options['--headers'],'-DNODE_LIBRARY='+options['--node-library']],['--build',output,'--config','Release']]){
  const result=spawnSync('cmake',command,{cwd:root,stdio:'inherit',windowsHide:true});if(result.error||result.status!==0)throw new Error('native_build_failed');
}
const binary=fs.readFileSync(path.join(output,'Release/leafseamer_installation_peer.node'));fs.mkdirSync(artifact,{recursive:true});fs.writeFileSync(path.join(artifact,'leafseamer_installation_peer.node'),binary);
fs.writeFileSync(path.join(artifact,'manifest.json'),JSON.stringify({format:'leafseamer-installation-peer/1',platform:process.platform,arch:process.arch,node_version:input.node_version,napi_version:input.napi_version,
  binary_sha256:hash(binary),inputs_sha256:hash(fs.readFileSync(path.join(root,'native-inputs.json'))),source_sha256:hash(fs.readFileSync(path.join(root,'native/installation-peer.cc'))),
  cmake_sha256:hash(fs.readFileSync(path.join(root,'native/CMakeLists.txt'))),local_headers:Object.fromEntries(['content-root.h','content-preparation.h'].map(name=>[name,hash(fs.readFileSync(path.join(root,'native',name)))])),compiler:JSON.parse(fs.readFileSync(path.join(output,'compiler.json')))},null,2)+'\n');
console.log(JSON.stringify({native_artifact:'windows-x64',sha256:hash(binary)}));
