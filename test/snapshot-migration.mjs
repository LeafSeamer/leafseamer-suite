import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import path from 'node:path';
// 真实67版事件、范围及订阅停止后验证增量迁移，不对既有原件补造快照。
export async function verifySnapshotMigration({directory,Database,migrateStorage}){
 const file=path.join(directory,'controller.sqlite'),snapshot=db=>Object.fromEntries(db.prepare("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN('service_state','schema_migration') ORDER BY name").pluck().all().map(name=>{
  assert.match(name,/^[a-z_][a-z0-9_]*$/);const rows=db.prepare('SELECT * FROM '+name).raw().all().map(JSON.stringify).sort();return [name,{rows:rows.length,digest:crypto.createHash('sha256').update(JSON.stringify(rows)).digest('hex')}];
 }));
 let db=new Database(file,{fileMustExist:true}),before,history,identity;
 try{assert.equal(db.pragma('user_version',{simple:true}),67);before=snapshot(db);assert.equal(before.device_source_event.rows,2);assert.equal(before.service_event_subscription.rows,2);assert.equal(before.device_subscription_scope.rows,2);
  history=db.prepare('SELECT * FROM schema_migration ORDER BY rowid').raw().all();identity=db.prepare('SELECT service_id,database_instance_id,control_epoch,request_epoch FROM service_state').raw().get();
 }finally{db.close();}
 const result=await migrateStorage(directory,68);assert.equal(result.schema_revision,'68');assert.equal(result.steps.length,1);
 db=new Database(file,{fileMustExist:true});try{const after=snapshot(db);for(const [table,value]of Object.entries(before))assert.deepEqual(after[table],value,table);
  const added=Object.keys(after).filter(name=>!Object.hasOwn(before,name)).sort();assert.deepEqual(added,['service_snapshot_build','service_snapshot_end','service_snapshot_manifest','service_snapshot_page']);for(const name of added)assert.equal(after[name].rows,0);
  assert.deepEqual(db.prepare('SELECT * FROM schema_migration ORDER BY rowid').raw().all().slice(0,-1),history);assert.deepEqual(db.prepare('SELECT service_id,database_instance_id,control_epoch,request_epoch FROM service_state').raw().get(),identity);
  assert.deepEqual(db.pragma('foreign_key_check'),[]);assert.equal(db.pragma('integrity_check',{simple:true}),'ok');
 }finally{db.close();}
 return {from:'67',to:'68',source_events:2,subscriptions:2,original_tables_preserved:Object.keys(before).length};
}
