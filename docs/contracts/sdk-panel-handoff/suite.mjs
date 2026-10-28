import {run} from '/contracts/panel-wire/runtime-tests.mjs';
import {createDecoder,WireError,profile} from '/contracts/panel-wire/decoder.mjs';
import {createHttpAdapter} from '/contracts/panel-http/adapter.mjs';
import {createClient,ClientError} from '/contracts/panel-client/client.mjs';
import {createDecoder as oldDecoder} from '/contracts/wire-routing/decoder.mjs';
import {createHttpAdapter as oldAdapter} from '/contracts/http-envelope/adapter.mjs';
import {createClient as oldClient} from '/contracts/typed-client/client.mjs';
const read=async p=>{const r=await fetch('/contracts/'+p,{cache:'no-store'});if(!r.ok)throw new Error('fixture_load');return r.json();};
export async function execute(isolated,context) {
  const [inv,selection,messages,examples,oracle,service,legacy,previous]=await Promise.all([
    'panel-wire/preview/inventory.json','panel-wire/contract/selection.json','panel-wire/contract/worker-messages.json','integration/source/frames.json',
    'panel-wire/oracle.json','panel-http/panel-cases.json','event-integration/preview/selection.json','panel-integration/preview/selection.json'].map(read));
  const base=await run(inv,selection,messages.ipc_version,examples,oracle.event_samples,oracle),checks=[];
  const check=(name,yes)=>{if(!yes)throw new Error(name);checks.push({name,passed:true});};
  check('实际隔离状态',crossOriginIsolated===isolated);
  check('共享缓冲能力', (typeof SharedArrayBuffer!=='undefined')===isolated);
  const bytes=v=>new TextEncoder().encode(JSON.stringify(v)),decoder=createDecoder(selection);
  const options={profile:profile({parse_deadline_ms:5000})};
  for(const c of oracle.panel_cases) {
    let accepted=false;
    try {const dto=await decoder.decode(new TextEncoder().encode(c.raw),decoder.panel(c.group,c.type),options);accepted=true;check('DTO冻结:'+c.label,Object.isFrozen(dto.value));}
    catch(e){if(!(e instanceof WireError))throw e;}
    check('面板接受集:'+c.label,accepted===c.accepted);
  }
  let unexpected=0;const sink=()=>{unexpected++;throw new Error('unexpected_transport');};
  for(const [name,make] of [['decoder',createDecoder],['http',createHttpAdapter],['client',s=>createClient('controller',s,sink)]]) {
    check('当前选择:'+name,typeof make(selection)==='object');
    for(const old of [legacy,previous,{...selection,contract_digest:previous.contract_digest},{...previous,contract_digest:selection.contract_digest}]) {
      let rejected=false;try{make(old);}catch(e){rejected=e.reason==='contract_selection';}check('旧或混合选择:'+name+old.contract_id+old.contract_digest,rejected);
    }
  }
  for(const [name,make] of [['decoder',oldDecoder],['http',oldAdapter],['client',s=>oldClient('controller',s,sink)]]) {
    check('旧选择保留:'+name,typeof make(legacy)==='object');let rejected=false;
    try{make(selection);}catch(e){rejected=e.reason==='contract_selection';}check('旧消费者拒当前:'+name,rejected);
  }
  check('构造不传输',unexpected===0);
  const h=decoder.http('controller','openEvents','response','401'),value={code:'authentication_required',request_id:'browser',retry_action:'do_not_retry'};
  const buffer=new TextEncoder().encode(' '.repeat(40)+JSON.stringify(value));
  const pending=decoder.decode(buffer,h,{contentType:'application/json',profile:profile({slice_units:8,parse_deadline_ms:5000})});
  const transferred=structuredClone(buffer,{transfer:[buffer.buffer]});
  check('缓冲实际转移',buffer.byteLength===0&&transferred.byteLength>0);check('首await前复制',(await pending).value.code===value.code);
  let mode='response',sent=0;
  const transport=async request=>{
    sent++;const response=await fetch('/bridge/'+context+'/'+request.authority+'/'+mode+request.target,{method:request.method,
      headers:request.headers.filter(([n])=>n.toLowerCase()!=='content-length'),body:request.body,signal:request.signal,redirect:'error',cache:'no-store'});
    return {status:String(response.status),headers:[...response.headers],body:new Uint8Array(await response.arrayBuffer())};
  };
  const clients=Object.fromEntries(['controller','seamer'].map(a=>[a,createClient(a,selection,transport)]));
  for(const c of service.cases) {
    const input={path:{session_id:c.request.intent.identity.panel_session_id},headers:{Origin:location.origin},body:c.request};
    for(const kind of ['response','unavailable']) {mode=kind;const before=sent,r=await clients[c.authority].call('invokePanelMethod',input);
      check(kind+':'+c.method,r.status==='200'&&JSON.stringify(r.body)===JSON.stringify(c[kind])&&!r.authorization_granted&&sent===before+1);}
    let before=sent,rejected=false;
    try{await clients[c.authority].call('invokePanelMethod',{...input,body:c.old_input});}catch(e){rejected=e instanceof ClientError&&e.state==='not_sent';}
    check('旧输入零发送:'+c.method,rejected&&sent===before);
    mode='old_result';before=sent;rejected=false;
    try{await clients[c.authority].call('invokePanelMethod',input);}catch(e){rejected=e instanceof ClientError&&e.state==='response_rejected';}
    check('旧结果拒绝无重试:'+c.method,rejected&&sent===before+1);
  }
  check('实际HTTP完整收发',sent===105);
  const all=[...base.checks,...checks],digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(all)));
  return {all_passed:true,cases_passed:all.length,checks_sha256:Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join(''),
    base_checks:base.cases_passed,panel_cases:oracle.panel_cases.length,frame_types:inv.panel.length,methods:service.cases.length,http_exchanges:sent,
    cross_origin_isolated:crossOriginIsolated,shared_array_buffer_available:typeof SharedArrayBuffer!=='undefined',skipped_shared_buffer_checks:isolated?0:100,
    production_authorization_executed:false,product_business_executed:false};
}
