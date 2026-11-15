import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import path from 'node:path';
// 由真实Schema64运行场景停机后调用，不伪造来源原件或降级现有数据库。
export async function verifyEventScopeMigration({directory,Database,migrateStorage}){
 const file=path.join(directory,'controller.sqlite');
 const snapshot=db=>Object.fromEntries(db.prepare("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN('service_state','schema_migration') ORDER BY name").pluck().all().map(name=>{
  assert.match(name,/^[a-z_][a-z0-9_]*$/);const rows=db.prepare('SELECT * FROM '+name).raw().all().map(JSON.stringify).sort();
  return [name,{rows:rows.length,digest:crypto.createHash('sha256').update(JSON.stringify(rows)).digest('hex')}];
 }));
 let db=new Database(file,{fileMustExist:true}),before,history,identity;
 try{assert.equal(db.pragma('user_version',{simple:true}),64);before=snapshot(db);assert.equal(before.device_source_event.rows,2);assert.equal(before.device_event_source.rows,2);assert.equal(before.device_source_event_outbox.rows,2);
  history=db.prepare('SELECT * FROM schema_migration ORDER BY rowid').raw().all();identity=db.prepare('SELECT service_id,database_instance_id,control_epoch,request_epoch FROM service_state').raw().get();
 }finally{db.close();}
 const result=await migrateStorage(directory,65);assert.equal(result.schema_revision,'65');assert.equal(result.steps.length,1);
 db=new Database(file,{fileMustExist:true});try{
  assert.equal(db.pragma('user_version',{simple:true}),65);const after=snapshot(db);for(const [table,value]of Object.entries(before))assert.deepEqual(after[table],value,table);
  const added=Object.keys(after).filter(name=>!Object.hasOwn(before,name)).sort();assert.deepEqual(added,['device_subscription_scope','device_subscription_scope_member','device_subscription_scope_revocation','device_subscription_scope_seal']);
  for(const name of added)assert.equal(after[name].rows,0);
  assert.deepEqual(db.prepare('SELECT * FROM schema_migration ORDER BY rowid').raw().all().slice(0,-1),history);assert.deepEqual(db.prepare('SELECT service_id,database_instance_id,control_epoch,request_epoch FROM service_state').raw().get(),identity);
  assert.deepEqual(db.pragma('foreign_key_check'),[]);assert.equal(db.pragma('integrity_check',{simple:true}),'ok');
 }finally{db.close();}
 return {from:'64',to:'65',source_events:2,original_tables_preserved:Object.keys(before).length};
}
