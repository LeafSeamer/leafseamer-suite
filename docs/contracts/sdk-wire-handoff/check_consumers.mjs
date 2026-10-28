// 仅检查固定客户端的构造边界，不发送HTTP或启动业务服务。
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const [root,input]=process.argv.slice(2);
const {previous,current}=JSON.parse(await readFile(input,'utf8'));
const checks=[];
const check=(name,value)=>{if(!value)throw new Error(name);checks.push({name,passed:true});};
let blocked=false;try{Function('return 1')();}catch{blocked=true;}
check('动态代码生成被禁用',blocked&&process.execArgv.includes('--disallow-code-generation-from-strings'));
const load=path=>import(pathToFileURL(resolve(root,path)).href);
const {createDecoder}=await load('contracts/wire-routing/decoder.mjs');
const {createHttpAdapter}=await load('contracts/http-envelope/adapter.mjs');
const {createClient}=await load('contracts/typed-client/client.mjs');
let sends=0;
const factories={
 'wire-routing':s=>createDecoder(s),
 'http-envelope':s=>createHttpAdapter(s),
 'typed-client':s=>createClient('controller',s,()=>{sends++;throw new Error('不应发送');})
};
for(const [name,create] of Object.entries(factories)){
 check(name+':原选择可构造',typeof create(previous)==='object');
 for(const [label,selection] of [
  ['新选择拒绝',current],
  ['原ID错摘要拒绝',{...previous,contract_digest:'sha256:'+'0'.repeat(64)}],
  ['新ID原摘要拒绝',{...previous,contract_id:current.contract_id}],
  ['原ID新摘要拒绝',{...previous,contract_digest:current.contract_digest}]
 ]){
  let rejected=false;try{create(selection);}catch(error){rejected=error.stage==='binding'&&error.reason==='contract_selection';}
  check(name+':'+label,rejected);
 }
}
check('未发生传输调用',sends===0);
process.stdout.write(JSON.stringify({all_passed:true,cases_passed:checks.length,checks,node_version:process.version,dynamic_codegen_blocked:blocked,transport_calls:sends}));
