import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash, randomUUID} from 'node:crypto';
import {once} from 'node:events';
import {mkdtempSync, readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import os from 'node:os';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {initializeStorage, openStorage} from '/controller/dist/storage.mjs';
import {createObsDeviceModule} from '/controller/dist/obs-device-module.mjs';
import {canonical} from '/controller/dist/auth-clock-value.mjs';

const cli = '/controller/dist/cli.mjs';
const require = createRequire(cli);
const Database = require('better-sqlite3');
const WebSocket = require('ws');
const suiteDataDirectory = process.env.OBS_FIXTURE_DATA_DIR;
const dir = suiteDataDirectory ?? mkdtempSync(path.join(os.tmpdir(), 'leafseamer-obs-resource-'));
const filename = path.join(dir, 'controller.sqlite');
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const {port, password, obs_pid} = JSON.parse(Buffer.concat(chunks));
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

if (suiteDataDirectory === undefined) initializeStorage(dir);
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

const observe = input => command('observe-obs-resource', ['--data-dir', dir], input);
const input = {device_id: device, password, samples: 2};
assert.equal((await observe({...input, device_id: alias})).errors?.error, 'obs_resource_unregistered');
const observation = await observe(input);
assert.equal(observation.code, 0, JSON.stringify(observation.errors));
assert.equal(observation.output.event, 'obs_resource_observed');
assert.equal(observation.output.ready, false);
assert.deepEqual(observation.output.resource_ref, created.output.resource_ref);
assert.deepEqual(observation.output.samples, ['1', '2'].map(sample_sequence => ({sample_sequence, program_scene_uuid: scenes[0]})));
assert.deepEqual(observation.output.catalog.action_ids, []);
assert.deepEqual(observation.output.catalog.trigger_ids, []);

const secretDirectory = process.env.OBS_FIXTURE_SECRET_DIR;
if (secretDirectory !== undefined) {
  const options = ['--data-dir', dir, '--secret-dir', secretDirectory];
  const seal = input => command('seal-obs-resource-credential', options, input);
  const protectedObserve = input => command('observe-obs-resource', options, input);
  const credential = {device_id: device, password, version: '1'};
  assert.equal((await seal({...credential, password: 'incorrect-synthetic-password'})).errors?.error, 'obs_authentication');
  const sealed = await seal(credential);
  assert.equal(sealed.code, 0, JSON.stringify(sealed.errors));
  assert.equal(sealed.output.event, 'obs_resource_credential_sealed');
  const secret_ref = sealed.output.secret_ref;
  assert.equal(secret_ref.secret_id, created.output.resource_ref.object_id);
  assert.equal(secret_ref.owner_service_id, identity.service_id);
  assert.deepEqual(await seal(credential), sealed);
  const second = await seal({...credential, version: '2'});
  assert.equal(second.code, 0, JSON.stringify(second.errors));
  const protectedInput = {device_id: device, samples: 2, secret_ref};
  const fromStore = await protectedObserve(protectedInput);
  assert.equal(fromStore.code, 0, JSON.stringify(fromStore.errors));
  assert.deepEqual(fromStore.output.samples, observation.output.samples);
  for (const [field, bad, code] of [
    ['secret_id', randomUUID(), 'obs_resource_secret_binding'],
    ['owner_service_id', randomUUID(), 'secret_store_reference'],
    ['purpose', 'runtime_tls', 'secret_store_reference']
  ]) {
    assert.equal((await protectedObserve({...protectedInput, secret_ref: {...secret_ref, [field]: bad}})).errors?.error, code);
  }
  const ledger = new Database(path.join(secretDirectory, 'nonce.sqlite'), {readonly: true, fileMustExist: true});
  try { assert.equal(ledger.prepare('SELECT count(*) FROM secret_nonce').pluck().get(), 2); }
  finally { ledger.close(); }
  const firstFile = path.join(secretDirectory, secret_ref.secret_id + '.1.secret');
  const secondFile = path.join(secretDirectory, secret_ref.secret_id + '.2.secret');
  const envelope = readFileSync(firstFile, 'utf8');
  assert.ok(!envelope.includes(password));
  const broken = JSON.parse(envelope);
  assert.notEqual(broken.nonce, JSON.parse(readFileSync(secondFile, 'utf8')).nonce);
  const shortTag = Buffer.from(broken.tag, 'base64url').subarray(0, 12).toString('base64url');
  writeFileSync(firstFile, canonical({...broken, tag: shortTag}));
  assert.equal((await protectedObserve(protectedInput)).errors?.error, 'secret_store_envelope');
  broken.tag = Buffer.from(broken.tag, 'base64url');
  broken.tag[0] ^= 1;
  writeFileSync(firstFile, canonical({...broken, tag: broken.tag.toString('base64url')}));
  assert.equal((await protectedObserve(protectedInput)).errors?.error, 'secret_store_envelope');
  writeFileSync(firstFile, envelope);
  const aad = JSON.parse(envelope);
  writeFileSync(secondFile, canonical({...aad, header: {...aad.header, version: '2'}}));
  assert.equal((await protectedObserve({...protectedInput, secret_ref: second.output.secret_ref})).errors?.error, 'secret_store_envelope');
  console.log('OBS 密文封存、只读凭据挂载、按引用采样和错误认证标签拒绝通过');
}

const lifetime = new AbortController(), resource = created.output.record;
const open = () => createObsDeviceModule({resource, password, signal: lifetime.signal});
const binding = {device_id: device, device_session_id: randomUUID(), signal: lifetime.signal};
const module = open();
const obsIdentity = await module.connectReadOnly(binding);
assert.equal(obsIdentity.model, 'obs.studio');
await assert.rejects(module.captureBaseline({...binding, device_session_id: randomUUID()}), {code: 'obs_device_session'});
assert.deepEqual(await module.captureBaseline(binding), {sample_sequence: '1', program_scene_uuid: scenes[0]});

// 仅供当前无外网夹具的独立操作方。产品会话必须观察真实 OBS 的变化和关闭。
async function fixtureOperation(requestType, requestData) {
  const socket = new WebSocket('ws://127.0.0.1:' + port, 'obswebsocket.json');
  const hash = value => createHash('sha256').update(value).digest('base64');
  const requestId = randomUUID();
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('OBS fixture operation timeout')), 5000);
      const settle = (error) => { clearTimeout(timer); if (error) reject(error); else resolve(); };
      socket.on('error', settle);
      socket.on('message', raw => {
        try {
          const {op, d} = JSON.parse(raw);
          if (op === 0) {
            const {salt, challenge} = d.authentication;
            socket.send(JSON.stringify({op: 1, d: {rpcVersion: 1, authentication: hash(hash(password + salt) + challenge), eventSubscriptions: 0}}));
          } else if (op === 2) {
            socket.send(JSON.stringify({op: 6, d: {requestType, requestId, requestData}}));
          } else if (op === 7) {
            assert.equal(d.requestId, requestId);
            assert.equal(d.requestType, requestType);
            assert.equal(d.requestStatus.result, true);
            settle();
          }
        } catch (error) { settle(error); }
      });
    });
  } finally { socket.terminate(); }
}
async function losesCatalog(selected, live, expectedCode) {
  for (let i = 0; i < 100; i++) {
    try { await selected.proposeCatalog({...live, identity: obsIdentity}); }
    catch (error) { assert.ok(expectedCode.includes(error.code), error.code); return; }
    await delay(25);
  }
  assert.fail('OBS 会话没有停止采用目录');
}

await fixtureOperation('SetCurrentProgramScene', {sceneUuid: scenes[1]});
// 已完成写入的独立客户端先离开，工作模块在同一条连接发起新的读取。
await delay(100);
assert.deepEqual(await module.captureBaseline(binding), {sample_sequence: '2', program_scene_uuid: scenes[1]});
await fixtureOperation('SetCurrentSceneCollection', {sceneCollectionName: 'Alternate'});
await losesCatalog(module, binding, ['obs_observation_changed']);
await assert.rejects(module.captureBaseline(binding), {code: 'obs_observation_changed'});
await assert.rejects(open().connectReadOnly({...binding, device_session_id: randomUUID()}), {code: 'obs_resource_catalog_changed'});
await fixtureOperation('SetCurrentSceneCollection', {sceneCollectionName: 'LeafSeamer'});
await assert.rejects(module.proposeCatalog({...binding, identity: obsIdentity}), {code: 'obs_observation_changed'});

const restarted = open(), anotherBinding = {...binding, device_session_id: randomUUID()};
await delay(100);
await restarted.connectReadOnly(anotherBinding);
assert.equal((await restarted.captureBaseline(anotherBinding)).sample_sequence, '1');
assert.ok(Number.isInteger(obs_pid) && obs_pid > 1);
process.kill(obs_pid, 'SIGTERM');
await losesCatalog(restarted, anotherBinding, ['obs_observation_changed', 'obs_disconnected', 'obs_transport']);
await assert.rejects(restarted.captureBaseline(anotherBinding), {code: /^obs_(observation_changed|disconnected|transport)$/});
lifetime.abort();
inspect(db => assert.equal(db.prepare('SELECT count(*) FROM device_catalog_approval').pluck().get(), 0));
console.log('OBS 同会话新读回、集合及断连失效通过');
