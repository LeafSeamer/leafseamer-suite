import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import test from 'node:test';

const controller=process.env.LEAFSEAMER_CONTROLLER_TEST_ROOT,seamer=process.env.LEAFSEAMER_SEAMER_TEST_ROOT;
const modules=process.platform==='linux'&&controller&&seamer?[
  pathToFileURL(path.join(controller,'dist/native-clock.mjs')).href,
  pathToFileURL(path.join(seamer,'dist/runtime/native-clock.mjs')).href
]:null;

test('双服务 Linux 原生墙钟观察在采集两侧锁存故障，单调读取继续可用',{
  skip:modules===null,timeout:30000
},async t=>{
  const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'leafseamer-clock-wall-'));
  t.after(()=>{
    assert.equal(path.dirname(scratch),os.tmpdir());
    fs.rmSync(scratch,{recursive:true,force:true});
  });
  const shim=path.join(scratch,'clock-fault.so');
  const source=fileURLToPath(new URL('./fixtures/linux-clock-fault.c',import.meta.url));
  const compiled=spawnSync('cc',['-shared','-fPIC','-Wall','-Wextra','-Werror','-o',shim,source,'-ldl'],{encoding:'utf8',timeout:10000});
  assert.equal(compiled.status,0,compiled.stderr);
  const invoke=(mode,program)=>{
    const env={...process.env,LD_PRELOAD:shim,LEAFSEAMER_TEST_WALL_MONITOR:mode};
    const result=spawnSync(process.execPath,['--disallow-code-generation-from-strings','--input-type=module','--eval',program],
      {env,encoding:'utf8',timeout:10000});
    assert.equal(result.status,0,result.stderr||result.error?.message);
  };
  for(const module of modules){
    const {openNativeClock}=await import(module);
    const healthy=openNativeClock(),start=healthy.tick(),capture=healthy.capture();
    assert(start<=BigInt(capture.a)&&BigInt(capture.b)<=healthy.tick());
    assert.equal(capture.continuity_available,false);
    for(const [mode,expected] of [['before','clock_wall_discontinuity'],['after','clock_wall_discontinuity'],
      ['read','clock_wall_monitor_unavailable'],['arm','clock_wall_monitor_unavailable']]){
      invoke(mode,`
import assert from 'node:assert/strict';
import {ClockError,openNativeClock} from ${JSON.stringify(module)};
const source=openNativeClock(),start=source.tick();
if (${JSON.stringify(mode)}!=='arm') assert.equal(source.capture().continuity_available,false);
for(const clock of [source,source,openNativeClock()]){
  assert.throws(()=>clock.capture(),error=>error instanceof ClockError&&error.code===${JSON.stringify(expected)});
  assert(clock.tick()>=start);
}
`);
    }
  }
  const directory=path.join(scratch,'controller');
  invoke('after',`
import assert from 'node:assert/strict';
import path from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {initializeStorage,migrateStorage} from ${JSON.stringify(pathToFileURL(path.join(controller,'dist/storage.mjs')).href)};
import {startController} from ${JSON.stringify(pathToFileURL(path.join(controller,'dist/server.mjs')).href)};
const directory=${JSON.stringify(directory)};
initializeStorage(directory);
await migrateStorage(directory,3);
const app=await startController({dataDir:directory});
try{
  const endpoint='http://127.0.0.1:'+app.address.port+'/health/ready';
  for(let index=0;index<2;++index){
    const response=await fetch(endpoint,{signal:AbortSignal.timeout(2000)});
    assert.equal(response.status,503);
    assert.equal((await response.json()).reason,'authentication_clock_unavailable');
  }
}finally{await app.close();}
const db=new DatabaseSync(path.join(directory,'controller.sqlite'),{readOnly:true});
try{
  const record=db.prepare('SELECT state,reason,sequence FROM authentication_clock_diagnostic').get();
  assert.equal(record.state,'faulted');
  assert.equal(record.reason,'clock_wall_discontinuity');
  assert.equal(record.sequence,1);
}finally{db.close();}
`);
});
