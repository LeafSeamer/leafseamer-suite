import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtempSync, readdirSync} from 'node:fs';
import {createRequire} from 'node:module';
import os from 'node:os';
import path from 'node:path';
import {initializeStorage, openStorage} from '/controller/dist/storage.mjs';

const cli = '/controller/dist/cli.mjs';
const require = createRequire(cli);
const Database = require('better-sqlite3');
const dir = mkdtempSync(path.join(os.tmpdir(), 'leafseamer-obs-resource-'));
const filename = path.join(dir, 'controller.sqlite');
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const {port, password} = JSON.parse(Buffer.concat(chunks));
const scenes = ['ebc75716-e090-42b1-b9e5-ee8a1dd15879', 'c3a343d6-9f64-4862-a151-baf6201a5ae6'];

async function command(name, args, input) {
  // Bash 给 CLI 创建真实匿名管道。Node 在 Linux 上的 spawn pipe 可实现为 socketpair。
  const child = spawn('bash', ['-o', 'pipefail', '-c', 'cat | "$@" | cat', 'obs-fixture',
    process.execPath, '--disallow-code-generation-from-strings', cli, name, ...args], {stdio: ['pipe', 'pipe', 'pipe']});
  const done = once(child, 'close');
  let output = '', errors = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { errors += chunk; });
  child.stdin.end(input === undefined ? undefined : JSON.stringify(input));
  const timer = setTimeout(() => child.kill(), 60000);
  try {
    const [code] = await done;
    assert.ok(!output.includes(password) && !errors.includes(password));
    return {code, output: output ? JSON.parse(output) : null, errors: errors ? JSON.parse(errors) : null};
  } finally { clearTimeout(timer); }
}
function inspect(check) {
  const db = new Database(filename, {fileMustExist: true});
  try { return check(db); } finally { db.close(); }
}
function history(db) {
  return db.prepare('SELECT * FROM schema_migration ORDER BY CAST(to_revision AS INTEGER)').raw().all();
}
const migrate = revision => command('migrate-storage', ['--data-dir', dir, '--to-revision', String(revision)]);
const register = input => command('register-obs-resource', ['--data-dir', dir], input);

initializeStorage(dir);
let migrated = await migrate(97);
assert.equal(migrated.code, 0, JSON.stringify(migrated.errors));
const storage = openStorage(dir);
const identity = storage.identity;
const admin = storage.enrollment.begin();
await storage.enrollment.complete({
  token_id: admin.token_id, secret: admin.secret, login: 'isolated-obs-admin',
  password: 'fixture-only-obs-admin-passphrase', mode: 'standalone'
});
const addDevice = (id, kind = 'obs') => storage.registerDevice({request_id: id, device_kind: kind, display_name: id}).device_id;
const device = addDevice('obs-test'), alias = addDevice('obs-alias'), simulator = addDevice('memory-simulator', 'simulator');
storage.close();
const prior = inspect(history);
const selected = {request_id: 'obs-register', device_id: device, port, collection_name: 'LeafSeamer', scene_uuids: scenes, password};
assert.equal((await register(selected)).errors?.error, 'obs_resource_migration_required');

// 验证迁移中途失败时恢复原版本，并复用同一份临时库完成正式入口的迁移。
inspect(db => db.exec('CREATE TABLE obs_local_resource (conflict TEXT)'));
assert.equal((await migrate(98)).errors?.error, 'migration_failed');
inspect(db => {
  assert.equal(db.pragma('user_version', {simple: true}), 97);
  assert.deepEqual(history(db), prior);
  db.exec('DROP TABLE obs_local_resource');
});
migrated = await migrate(98);
assert.equal(migrated.code, 0, JSON.stringify(migrated.errors));
assert.equal(migrated.output.steps.length, 1);
assert.ok(readdirSync(dir).includes(migrated.output.backup_file));
inspect(db => {
  assert.deepEqual(history(db).slice(0, -1), prior);
  assert.deepEqual(db.prepare('SELECT service_id,database_instance_id,control_epoch,request_epoch FROM service_state').raw().get(),
    ['service_id','database_instance_id','control_epoch','request_epoch'].map(key => identity[key]));
  assert.equal(db.prepare('SELECT count(*) FROM device_record').pluck().get(), 3);
  assert.deepEqual(db.pragma('foreign_key_check'), []);
});

assert.equal((await register({...selected, device_id: simulator})).errors?.error, 'obs_resource_device_kind');
assert.equal((await register({...selected, password: 'incorrect-synthetic-password'})).errors?.error, 'obs_authentication');
assert.equal((await register({...selected, scene_uuids: [scenes[0], 'ba76b876-35d6-4476-b28c-0b10cb0cafd3']})).errors?.error, 'obs_resource_catalog_changed');
inspect(db => assert.equal(db.prepare('SELECT count(*) FROM obs_local_resource').pluck().get(), 0));

const created = await register(selected);
assert.equal(created.code, 0, JSON.stringify(created.errors));
assert.equal(created.output.event, 'obs_resource_registered');
assert.equal(created.output.ready, false);
assert.equal(created.output.record.device_ref.object_id, device);
assert.equal(created.output.record.endpoint.port, port);
assert.deepEqual(created.output.record.scene_uuids, [...scenes].sort());
const repeated = await register({...selected, scene_uuids: [...scenes].reverse()});
assert.deepEqual(repeated, created);
assert.equal((await register({...selected, collection_name: 'changed'})).errors?.error, 'obs_resource_request_conflict');
assert.equal((await register({...selected, request_id: 'another-request'})).errors?.error, 'obs_resource_device_bound');
assert.equal((await register({...selected, request_id: 'another-endpoint', device_id: alias})).errors?.error, 'obs_resource_endpoint_bound');
inspect(db => {
  const [body, digest] = db.prepare('SELECT body_jcs,body_digest FROM obs_local_resource').raw().get();
  assert.deepEqual(JSON.parse(body), created.output.record);
  assert.equal(digest, created.output.resource_ref.digest);
  const audits = db.prepare('SELECT audit_jcs FROM obs_local_resource_commit').pluck().all();
  assert.equal(audits.length, 1);
  assert.deepEqual(JSON.parse(audits[0]).resource_ref, created.output.resource_ref);
  assert.ok(!body.includes(password) && !audits[0].includes(password));
  assert.equal(db.prepare("SELECT count(*) FROM control_record_revision WHERE device_id=? AND json_extract(body_jcs,'$.gate_state')!='protected'").pluck().get(device), 0);
  assert.equal(db.prepare('SELECT count(*) FROM device_catalog_approval').pluck().get(), 0);
  assert.deepEqual(db.pragma('foreign_key_check'), []);
  assert.throws(() => db.exec('UPDATE obs_local_resource SET endpoint_port=1'), /immutable_obs_resource/);
});
console.log('OBS 本机资源登记、显式迁移回滚、持久回执与端口互斥通过');
