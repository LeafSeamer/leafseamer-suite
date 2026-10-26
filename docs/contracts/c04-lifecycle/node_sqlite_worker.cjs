'use strict';
// 隔离验收桥：每个进程仅一个存储线程；不作为服务运行代码。
const {Worker,isMainThread,parentPort,workerData}=require('node:worker_threads');
const fs=require('node:fs');const path=require('node:path');const readline=require('node:readline');
if(isMainThread){
  const worker=new Worker(__filename,{workerData:{packageRoot:process.argv[2]}});
  const input=readline.createInterface({input:process.stdin});
  input.on('line',line=>worker.postMessage(JSON.parse(line)));
  input.on('close',()=>worker.terminate());
  worker.on('message',value=>process.stdout.write(JSON.stringify(value)+'\n'));
  worker.on('error',()=>{process.stderr.write('storage_worker_failed\n');process.exitCode=1;input.close();});
}else{
  const packageRoot=path.resolve(workerData.packageRoot);
  const metadata=JSON.parse(fs.readFileSync(path.join(packageRoot,'package.json'),'utf8'));
  if(metadata.name!=='better-sqlite3'||metadata.version!=='13.0.3'||process.version!=='v24.22.0'||process.platform!=='win32'||process.arch!=='x64')throw Error('runtime_profile_mismatch');
  const Database=require(path.join(packageRoot,'lib','win32-x64.js'));
  const decode=v=>v&&typeof v==='object'&&'$blob' in v?Buffer.from(v.$blob,'hex'):v&&typeof v==='object'&&'$integer' in v?BigInt(v.$integer):v;
  const encode=v=>typeof v==='bigint'?{$integer:String(v)}:Buffer.isBuffer(v)?{$blob:v.toString('hex')}:v;
  let db;
  function open(filename){
    const folder=path.dirname(path.resolve(filename));
    if(path.basename(filename)!=='case.sqlite'||fs.readFileSync(path.join(folder,'.leafseamer-offline-test'),'utf8')!=='node-sqlite-retired-cancel/1')throw Error('test_path_required');
    db=new Database(filename,{timeout:0,fileMustExist:true});db.defaultSafeIntegers(true);
    db.pragma('foreign_keys=ON');db.pragma('recursive_triggers=ON');db.pragma('synchronous=FULL');db.pragma('wal_autocheckpoint=1000');
  }
  function close(){if(db){db.close();db=undefined;}}
  function snapshot(){
    const result={};
    for(const row of db.prepare("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").all()){
      const name=row.name;const quote='"'+name.replaceAll('"','""')+'"';
      result[name]=db.prepare('SELECT * FROM '+quote).raw().all().map(row=>row.map(encode));
    }
    return result;
  }
  function facts(){return {node:process.version,napi:process.versions.napi,driver:metadata.version,sqlite:db.prepare('SELECT sqlite_version() AS version,sqlite_source_id() AS source_id').get(),compile_options:db.pragma('compile_options').map(r=>r.compile_options),pragmas:Object.fromEntries(['journal_mode','synchronous','foreign_keys','recursive_triggers','busy_timeout','wal_autocheckpoint','mmap_size'].map(n=>[n,encode(db.pragma(n,{simple:true}))]))};}
  parentPort.on('message',request=>{
    try{
      if(request.action==='ping'){parentPort.postMessage({ok:true});return;}
      if(request.action==='close'){close();parentPort.postMessage({ok:true});return;}
      close();open(request.path);
      if(request.action==='setup'){
        if(!['DELETE','WAL'].includes(request.mode))throw Error('journal_mode_required');
        db.pragma('journal_mode='+request.mode);const value=facts();close();parentPort.postMessage({ok:true,facts:value});return;
      }
      if(request.action==='write'){
        if(!['after_member','after_seal','after_commit'].includes(request.phase))throw Error('phase_required');
        db.exec('BEGIN IMMEDIATE');
        for(const statement of request.statements){
          if(!/^INSERT INTO [a-z_]+ /.test(statement.sql))throw Error('insert_workload_required');
          db.prepare(statement.sql).run(...statement.parameters.map(decode));
          if((request.phase==='after_member'&&statement.sql.startsWith('INSERT INTO crp_member '))||(request.phase==='after_seal'&&statement.sql.startsWith('INSERT INTO cc_cut_commit '))){parentPort.postMessage({ok:true,barrier:request.phase,in_transaction:db.inTransaction});return;}
        }
        if(request.phase!=='after_commit')throw Error('barrier_not_reached');
        db.exec('COMMIT');parentPort.postMessage({ok:true,barrier:request.phase,in_transaction:db.inTransaction});return;
      }
      if(request.action!=='inspect')throw Error('unknown_operation');
      const value={ok:true,integrity:db.pragma('integrity_check').map(r=>r.integrity_check),foreign_keys:db.pragma('foreign_key_check'),facts:facts(),state:snapshot()};
      close();parentPort.postMessage(value);
    }catch(error){
      const result={ok:false,code:typeof error.code==='string'?error.code:'test_operation_failed'};
      try{close();}catch{result.close_failed=true;}
      parentPort.postMessage(result);
    }
  });
}
