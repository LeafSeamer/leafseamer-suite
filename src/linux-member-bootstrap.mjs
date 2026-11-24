import crypto from 'node:crypto';
import fs from 'node:fs';
import {decodeBootstrap,decodeProtectedLaunchIntent,bootstrapVersion} from './sdk/bootstrap.mjs';
import {canonical,digest,requireValue as need} from './import-input.mjs';

const maximum=16384;
const nonce=()=>crypto.randomBytes(32).toString('base64url');
const id=()=>crypto.randomUUID();
const same=(left,right)=>canonical(left)===canonical(right);
const fields=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys;
const token=value=>typeof value==='string'&&/^[A-Za-z0-9_.:-]{1,128}$(?![\s\S])/.test(value);
const revision=value=>typeof value==='string'&&/^(0|[1-9][0-9]{0,19})$(?![\s\S])/.test(value);

export function validateLinuxBootstrapPolicy(intent,input){
  need(fields(input,'artifact_manifest_ref,bootstrap_timeout_ms,clock_backend_revision,database_instance_id,format,platform_profile_ref,policy_revision,service_id')&&
    input.format==='leafseamer-core-bootstrap-policy/1'&&input.service_id===intent.service_id&&
    input.database_instance_id===intent.database_instance_id&&token(input.clock_backend_revision)&&revision(input.policy_revision)&&
    Number.isInteger(input.bootstrap_timeout_ms)&&input.bootstrap_timeout_ms>=1&&input.bootstrap_timeout_ms<=60000,
  'linux_bootstrap_policy');
  const a=input.artifact_manifest_ref,p=input.platform_profile_ref;
  need(fields(a,'digest,manifest_id,revision')&&token(a.manifest_id)&&revision(a.revision)&&
    typeof a.digest==='string'&&/^sha256:[0-9a-f]{64}$(?![\s\S])/.test(a.digest)&&
    fields(p,'profile_id,revision')&&token(p.profile_id)&&revision(p.revision),'linux_bootstrap_policy');
  return JSON.parse(canonical(input));
}

function readProof(socket,timeout){
  return new Promise((resolve,reject)=>{
    let buffer=Buffer.alloc(0);
    const finish=(error,bytes)=>{
      clearTimeout(timer);
      socket.pause();
      socket.removeListener('data',data).removeListener('end',closed).removeListener('close',closed).removeListener('error',closed);
      if(error)reject(error);else resolve(bytes);
    };
    const closed=()=>finish(Object.assign(new Error('linux_bootstrap_channel'),{code:'linux_bootstrap_channel'}));
    const invalid=()=>finish(Object.assign(new Error('linux_bootstrap_frame'),{code:'linux_bootstrap_frame'}));
    function data(chunk){
      if(!Buffer.isBuffer(chunk)||buffer.length+chunk.length>maximum+1){invalid();return;}
      buffer=Buffer.concat([buffer,chunk]);
      const end=buffer.indexOf(10);
      if(end<0)return;
      if(end!==buffer.length-1){invalid();return;}
      finish(null,buffer.subarray(0,end));
    }
    const timer=setTimeout(()=>finish(Object.assign(new Error('linux_bootstrap_timeout'),{code:'linux_bootstrap_timeout'})),timeout);
    socket.on('data',data).once('end',closed).once('close',closed).once('error',closed);
    if(socket.destroyed||socket.readableEnded)closed();
  });
}

function send(socket,type,payload){
  const body=canonical({version:bootstrapVersion,type,payload});
  need(Buffer.byteLength(body)<=maximum,'linux_bootstrap_frame');
  return new Promise((resolve,reject)=>socket.write(body+'\n',error=>error?reject(error):resolve()));
}

export async function admitLinuxMember(record,{policy,source,socket,commit,compose=false}){
  const {intent,detail}=record;
  const namespace=fs.statSync('/proc/self/ns/time',{bigint:true});
  const namespaceIdentity=String(namespace.dev)+':'+namespace.ino;
  const boot=detail.host.boot_id;
  const descriptorBody={descriptor_version:'clock-domain/1',domain_kind:'supervised_runtime',authority_service_id:intent.service_id,
    runtime_generation:intent.generation_id,supervisor_instance_id:id(),clock_backend_id:'linux_boottime',
    clock_backend_revision:policy.clock_backend_revision,tick_unit:'ns',suspend_accounting:'included',
    namespace_identity:'linux_'+namespaceIdentity.replace(':','_'),
    os_boot_identity:{status:'verified',source:'linux-proc-boot-id',value:boot,evidence_ref:boot},
    platform_profile_id:policy.platform_profile_ref.profile_id,platform_profile_revision:policy.platform_profile_ref.revision};
  const descriptorDigest=digest(descriptorBody),domain={clock_domain_id:'clock_'+descriptorDigest.slice(7),descriptor_digest:descriptorDigest};
  const descriptor={...descriptorBody,...domain};
  const group=compose?{boot_id:boot,generation:intent.generation_id,service_kind:intent.role,group:detail.group}:
    {boot_id:boot,group_path:detail.group_path,group:detail.group};
  const containment={backend:'linux_cgroup_v2',generation:intent.generation_id,group_id:'group_'+digest(group).slice(7)};
  const launch=await decodeProtectedLaunchIntent(Buffer.from(canonical({launch_id:intent.launch_id,service_id:intent.service_id,
    supervisor_instance_id:descriptor.supervisor_instance_id,runtime_generation:intent.generation_id,member_id:id(),role:'core',
    artifact_manifest_ref:policy.artifact_manifest_ref,containment_ref:containment,device_ids:[],policy_revision:policy.policy_revision})));
  return exchangeAdmission({launch,descriptor,detail,policy,source,socket,commit});
}

export function admitLinuxWorker({intent,descriptor,detail,policy,source,socket,commit}){
  need(intent.role==='worker'&&intent.supervisor_instance_id===descriptor.supervisor_instance_id&&
    intent.runtime_generation===descriptor.runtime_generation&&detail.host.boot_id===descriptor.os_boot_identity.value,'linux_bootstrap_worker');
  return exchangeAdmission({launch:intent,descriptor,detail,policy,source,socket,commit});
}

export function admitLinuxReferenceProvider({intent,descriptor,detail,policy,source,socket,commit}){
  need(intent.role==='time_provider'&&intent.device_ids.length===0&&intent.service_id===descriptor.authority_service_id&&
    intent.supervisor_instance_id===descriptor.supervisor_instance_id&&intent.runtime_generation===descriptor.runtime_generation&&
    detail.host.boot_id===descriptor.os_boot_identity.value,'linux_bootstrap_time_provider');
  return exchangeAdmission({launch:intent,descriptor,detail,policy,source,socket,commit});
}

async function exchangeAdmission({launch,descriptor,detail,policy,source,socket,commit}){
  const domain={clock_domain_id:descriptor.clock_domain_id,descriptor_digest:descriptor.descriptor_digest};
  function tick(){
    const sample=source.capture(),now=source.tick();
    need(typeof sample.continuity==='string'&&sample.continuity.startsWith('linux:')&&
      'linux_'+sample.continuity.slice(6).replace(':','_')===descriptor.namespace_identity&&typeof now==='bigint'&&now>=0n&&now<=(1n<<64n)-1n,
    'linux_bootstrap_clock');
    return now;
  }
  const issued=tick(),expires=issued+BigInt(policy.bootstrap_timeout_ms)*1000000n;
  need(expires<=(1n<<64n)-1n,'linux_bootstrap_clock');
  const memberBoot=launch.role==='time_provider'?crypto.randomBytes(16).toString('hex'):id();
  const common={bootstrap_id:id(),launch_id:launch.launch_id,launch_intent_digest:digest(launch),member_id:launch.member_id,member_boot_id:memberBoot,
    role:launch.role,artifact_manifest_ref:launch.artifact_manifest_ref,channel_binding_id:id()};
  const projection={...common,...domain,bootstrap_version:bootstrapVersion,challenge_id:id(),
    challenge_nonce:nonce(),issued_tick_ns:String(issued),expires_tick_ns:String(expires)};
  const key=crypto.randomBytes(32);
  try{
    const {clock_domain_id,descriptor_digest,...challenge}=projection;
    const assignment={...challenge,clock_domain_descriptor:descriptor,secret:key.toString('base64url')};
    await decodeBootstrap(Buffer.from(canonical({version:bootstrapVersion,type:'ASSIGNMENT',payload:assignment})),'ASSIGNMENT');
    const reading=readProof(socket,policy.bootstrap_timeout_ms);
    const [,bytes]=await Promise.all([send(socket,'ASSIGNMENT',assignment),reading]);
    const {payload:{proof,...returned}}=await decodeBootstrap(bytes,'PROOF');
    const {challenge_nonce,issued_tick_ns,expires_tick_ns,...expected}=projection;
    need(same(returned,expected),'linux_bootstrap_proof');
    const mac=crypto.createHmac('sha256',key).update('leafseamer-bootstrap-proof/v1\0','ascii').update(canonical(projection)).digest();
    const candidate=Buffer.from(proof,'base64url');
    need(candidate.length===mac.length&&candidate.toString('base64url')===proof&&crypto.timingSafeEqual(candidate,mac),'linux_bootstrap_proof');
    const admitted=tick();
    need(admitted>=issued&&admitted<expires,'linux_bootstrap_expired');
    const receipt={...common,receipt_id:id(),domain_ref:domain,containment_ref:launch.containment_ref,
      os_observation_ref:'observation_'+digest(detail).slice(7),admitted_tick_ns:String(admitted),gate_state:'closed'};
    await decodeBootstrap(Buffer.from(canonical({version:bootstrapVersion,type:'ADMISSION',payload:receipt})),'ADMISSION');
    const record=await commit({intent:launch,descriptor,receipt,policy});
    const current=tick();
    need(current>=admitted&&current<expires,'linux_bootstrap_expired');
    await send(socket,'ADMISSION',receipt);
    return record;
  }finally{key.fill(0);}
}
