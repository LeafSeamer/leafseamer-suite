import {execute} from './suite.mjs';
const target=document.getElementById('result');
try {
  let blocked=false;try{Function('globalThis.__forbiddenEval=true')();}catch{blocked=true;}
  const script=document.createElement('script');script.textContent='globalThis.__forbiddenInline=true';document.body.append(script);
  await new Promise(r=>setTimeout(r,30));
  if(!blocked||globalThis.__forbiddenEval||globalThis.__forbiddenInline)throw new Error('csp_not_enforced');
  const isolated=location.pathname==='/isolated',page=await execute(isolated,'page');
  const worker=new Worker('/worker.mjs',{type:'module'});let result;
  try {result=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('worker_timeout')),120000);
    worker.onmessage=e=>{clearTimeout(timer);resolve(e.data);};worker.onerror=()=>{clearTimeout(timer);reject(new Error('worker_failed'));};
    worker.postMessage({isolated});
  });}finally{worker.terminate();}
  if(!result.all_passed)throw new Error(result.error);
  globalThis.__panelDone={all_passed:true,page,worker:result.result,eval_blocked:blocked,inline_blocked:true,worker_eval_blocked:result.eval_blocked,user_agent:navigator.userAgent};
  target.textContent=JSON.stringify({all_passed:true,page:page.cases_passed,worker:result.result.cases_passed});
}catch(e){globalThis.__panelDone={all_passed:false,error:e.message};target.textContent='FAIL: '+e.message;}
