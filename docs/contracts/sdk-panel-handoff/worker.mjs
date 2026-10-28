import {execute} from './suite.mjs';
self.onmessage=async e=>{try{
  let blocked=false;try{Function('return 1')();}catch{blocked=true;}
  if(!blocked)throw new Error('worker_csp');
  self.postMessage({all_passed:true,result:await execute(e.data.isolated,'worker'),eval_blocked:blocked});
}catch(error){self.postMessage({all_passed:false,error:error.message});}};
