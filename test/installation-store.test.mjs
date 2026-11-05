import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import Database from 'better-sqlite3';
import {createInstallationStore, openInstallationStore} from '../dist/installation-store.mjs';
import {digest, canonical} from '../dist/import-input.mjs';
import {authorizeFixture} from './fixtures/release-authorization.mjs';

const hash = bytes => 'sha256:' + crypto.createHash('sha256').update(bytes).digest('hex');
async function fixture(t, bytes = Buffer.from('synthetic archive bytes; never executed')) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'leafseamer-installation-')), root = path.join(base, 'installation');
  fs.mkdirSync(root); const identity = createInstallationStore(root); let store = openInstallationStore(root);
  const source = path.join(base, 'source.zip'); fs.writeFileSync(source, bytes);
  let authorized;
  const close = () => { authorized?.session.close(); store.close(); };
  t.after(() => {
    close(); assert.equal(path.dirname(path.resolve(base)), path.resolve(os.tmpdir())); fs.rmSync(base, {recursive: true, force: true});
  });
  const ref = kind => ({kind, authority_service_id: identity.authority_service_id, database_instance_id: identity.database_instance_id,
    object_id: kind + '.synthetic', revision: '1', digest: digest(kind)});
  const request = {identity: {host_installation_id: identity.host_installation_id, client_registration_id: 'client.synthetic', import_request_id: 'request.synthetic'},
    target_authority_service_id: 'controller.synthetic', source_attachment_id: 'attachment.synthetic', package_digest: hash(bytes), package_bytes: String(bytes.length),
    expected_manifest_digest: digest('manifest.synthetic'), host_trust_epoch: '1', release_authorization_ref: ref('release_authorization'), validation_policy_ref: ref('validation_policy')};
  authorized = await authorizeFixture(store,bytes,request.expected_manifest_digest); request.release_authorization_ref = authorized.result.reference;request.validation_policy_ref=authorized.validationPolicy.reference;
  return {root, base, source, bytes, identity, request, close,
    get store() { return store; }, reopen() { close(); store = openInstallationStore(root); return store; }
  };
}
function inspect(f, callback) {
  f.close(); const db = new Database(path.join(f.root, 'installation.db'), {fileMustExist: true});
  db.pragma('foreign_keys=ON'); db.pragma('recursive_triggers=ON');
  try { return callback(db); } finally { db.close(); f.reopen(); }
}
async function copy(f, request = f.request) {
  const fd = fs.openSync(f.source, 'r'); try { return await f.store.copyImport(request.identity, fd); } finally { fs.closeSync(fd); }
}
test('安装账本拥有独立稳定身份和单writer，缺库、复制目录及重新初始化不能隐式重建身份', async t => {
  const f = await fixture(t); assert.deepEqual(f.store.identity, f.identity); assert.throws(() => openInstallationStore(f.root), {code: 'installation_in_use'});
  assert.throws(() => createInstallationStore(f.root), {code: 'installation_initialization_conflict'});
  f.reopen(); assert.deepEqual(f.store.identity, f.identity);
  f.close(); const clone = path.join(f.base, 'clone'); fs.cpSync(f.root, clone, {recursive: true});
  assert.throws(() => openInstallationStore(clone), {code: 'installation_marker'});
  fs.unlinkSync(path.join(clone, 'installation.db')); assert.throws(() => openInstallationStore(clone), {code: 'installation_unavailable'});
  assert.equal(fs.existsSync(path.join(clone, 'installation.db')), false);
  assert.throws(() => createInstallationStore(clone), {code: 'installation_initialization_conflict'}); f.reopen();
});
test('受理按完整身份幂等，只排除attachment且持久保留取消，容量不删除旧请求', async t => {
  const f = await fixture(t), first = f.store.recordAcceptedImport(f.request);
  assert.equal(first.state, 'accepted'); assert.equal(first.receipt, null);
  assert.deepEqual(f.store.recordAcceptedImport({...f.request, source_attachment_id: 'attachment.reconnected'}), first);
  for (const patch of [{host_trust_epoch: '2'}, {package_bytes: '999'}, {target_authority_service_id: 'different'},
    {validation_policy_ref: {...f.request.validation_policy_ref, revision: '2'}}]) {
    assert.throws(() => f.store.recordAcceptedImport({...f.request, ...patch}), {code: 'import_identity_conflict'});
  }
  const peerBusy = {...f.request, identity: {...f.request.identity, import_request_id: 'another'}};
  assert.throws(() => f.store.recordAcceptedImport(peerBusy), {code: 'import_capacity'});
  const second = {...f.request, identity: {...f.request.identity, client_registration_id: 'client.second'}};
  f.store.recordAcceptedImport(second);
  assert.throws(() => f.store.recordAcceptedImport({...second, identity: {...second.identity, client_registration_id: 'client.third'}}), {code: 'import_capacity'});
  const cancelled = f.store.cancelImport(f.request.identity); assert.equal(cancelled.state, 'cancelled');
  assert.deepEqual(f.store.cancelImport(f.request.identity), cancelled);
  assert.deepEqual(f.store.recordAcceptedImport(f.request), cancelled);
  f.store.recordAcceptedImport(peerBusy); f.reopen(); assert.deepEqual(f.store.queryImport(f.request.identity), cancelled);
  assert.equal(f.store.queryImport({...f.request.identity, import_request_id: 'missing'}), null);
  assert.throws(() => f.store.queryImport({...f.request.identity, host_installation_id: 'wrong'}), {code: 'import_wrong_host'});
});
test('真实描述符复制核字节和摘要，提交后重启查原但不产生sealed或启动收据', async t => {
  const f = await fixture(t, Buffer.alloc(1024 * 1024, 17)); const accepted = f.store.recordAcceptedImport(f.request);
  const fd = fs.openSync(f.source, 'r'), mutableIdentity = {...f.request.identity};
  let result;
  try {
    const copying = f.store.copyImport(mutableIdentity, fd); mutableIdentity.import_request_id = 'mutated'; result = await copying;
  } finally { fs.closeSync(fd); }
  assert.equal(result.state, 'validating'); assert.equal(result.operation_id, accepted.operation_id); assert.equal(result.receipt, null);
  const artifact = f.store.copiedArtifact(f.request.identity); assert.deepEqual(fs.readFileSync(artifact.filename), f.bytes);
  assert.deepEqual(fs.readFileSync(f.source), f.bytes); assert.equal(artifact.package_digest, f.request.package_digest);
  assert.deepEqual(await copy(f), result); f.reopen(); assert.deepEqual(f.store.queryImport(f.request.identity), result);
  assert.deepEqual(f.store.copiedArtifact(f.request.identity), artifact);
  inspect(f, db => { assert.equal(db.prepare('SELECT count(*) FROM import_copy_attempt').pluck().get(), 1); assert.equal(db.prepare('SELECT count(*) FROM import_copy_receipt').pluck().get(), 1); });
  assert.equal(f.store.cancelImport(f.request.identity).state, 'cancelled'); assert.throws(() => f.store.copiedArtifact(f.request.identity), {code: 'import_copy_unavailable'});
});
test('包长度、摘要和源描述符失败保留拒绝原件，不以临时文件存在认定成功', async t => {
  for (const kind of ['short', 'long', 'hash', 'descriptor']) {
    const f = await fixture(t), request = structuredClone(f.request);
    if (kind === 'short') fs.writeFileSync(f.source,f.bytes.subarray(0,f.bytes.length-1));
    if (kind === 'long') fs.writeFileSync(f.source,Buffer.concat([f.bytes,Buffer.from('x')]));
    if (kind === 'hash') fs.writeFileSync(f.source,Buffer.alloc(f.bytes.length,0));
    f.store.recordAcceptedImport(request);
    const result = kind === 'descriptor' ? await f.store.copyImport(request.identity, 2147483647) : await copy(f, request);
    assert.equal(result.state, 'rejected'); assert.equal(result.reason_code, kind === 'descriptor' ? 'source_unavailable' : 'content_mismatch');
    assert.equal(result.receipt, null); assert.deepEqual(f.store.recordAcceptedImport(request), result);
    inspect(f, db => assert.equal(db.prepare('SELECT count(*) FROM import_copy_receipt').pluck().get(), 0));
  }
});
test('复制期间取消由同writer胜出；并行复制、关闭和迟到完成不能覆盖取消', async t => {
  const f = await fixture(t, Buffer.alloc(2 * 1024 * 1024, 23)); f.store.recordAcceptedImport(f.request);
  const fd = fs.openSync(f.source, 'r');
  try {
    const pending = f.store.copyImport(f.request.identity, fd);
    await assert.rejects(f.store.copyImport(f.request.identity, fd), {code: 'import_copy_in_progress'});
    assert.throws(() => f.store.close(), {code: 'import_copy_in_progress'});
    const cancelled = f.store.cancelImport(f.request.identity); assert.deepEqual(await pending, cancelled);
    assert.equal(cancelled.state, 'cancelled');
    inspect(f, db => assert.equal(db.prepare('SELECT count(*) FROM import_copy_receipt').pluck().get(), 0));
  } finally { fs.closeSync(fd); }
});
test('实际进程在copying提交后退出，沿原operation恢复新复制尝试且保留旧尝试', {timeout: 20000}, async t => {
  const f = await fixture(t, Buffer.alloc(16 * 1024 * 1024, 31)); const accepted = f.store.recordAcceptedImport(f.request); f.close();
  const child = spawn(process.execPath, ['--disallow-code-generation-from-strings', fileURLToPath(new URL('./fixtures/import-copy-child.mjs', import.meta.url)),
    f.root, f.source, JSON.stringify(f.request.identity)], {stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
  const closed = once(child, 'close'); let stderr = ''; child.stderr.on('data', chunk => { stderr += chunk; });
  let output = '';
  try {
    await new Promise((resolve, reject) => {
      child.on('error', reject); child.stdout.on('data', chunk => { output += chunk; if (output.includes('\n')) { child.kill(); resolve(); } });
      child.on('exit', () => { if (!output.includes('\n')) reject(new Error(stderr || 'child_no_copy_state')); });
    });
    await closed; assert.equal(JSON.parse(output.trim()).state, 'copying');
  } finally { if (child.exitCode === null && child.signalCode === null) { child.kill(); await closed; } }
  f.reopen(); assert.equal(f.store.queryImport(f.request.identity).state, 'copying');
  const recovered = await copy(f); assert.equal(recovered.state, 'validating'); assert.equal(recovered.operation_id, accepted.operation_id);
  inspect(f, db => { assert.equal(db.prepare('SELECT count(*) FROM import_copy_attempt').pluck().get(), 2); assert.equal(db.prepare('SELECT count(*) FROM import_copy_receipt').pluck().get(), 1); });
});
test('数据库约束拒绝删除/替换身份、无复制尝试的copying、无字节回执的validating及sealed旁路', async t => {
  const f = await fixture(t), accepted = f.store.recordAcceptedImport(f.request);
  inspect(f, db => {
    assert.throws(() => db.prepare('DELETE FROM import_operation WHERE operation_id=?').run(accepted.operation_id));
    assert.throws(() => db.exec('INSERT OR REPLACE INTO installation_identity SELECT * FROM installation_identity'));
    const detail = {}, values = state => [accepted.operation_id, 2, crypto.randomUUID(), state, null, Buffer.from(canonical(detail)), digest(detail)];
    const insert = db.prepare('INSERT INTO import_event(operation_id,revision,event_id,state,reason_code,detail_body,detail_digest) VALUES (?,?,?,?,?,?,?)');
    for (const state of ['copying', 'validating', 'sealed', 'indeterminate']) {
      db.exec('BEGIN');
      try { assert.throws(() => { insert.run(...values(state)); db.exec('COMMIT'); }); }
      finally { if (db.inTransaction) db.exec('ROLLBACK'); }
    }
  });
  assert.equal(f.store.queryImport(f.request.identity).state, 'accepted');
});
test('额外DDL及未知输入字段在使用前拒绝，不自动删除修复', async t => {
  const f = await fixture(t); f.close(); const filename = path.join(f.root, 'installation.db');
  const db = new Database(filename); db.exec('CREATE TABLE extra(value TEXT)'); db.close();
  assert.throws(() => openInstallationStore(f.root), {code: 'installation_integrity'});
  const repair = new Database(filename); repair.exec('DROP TABLE extra'); repair.close(); f.reopen();
  const request = structuredClone(f.request); request.extra = true;
  assert.throws(() => f.store.recordAcceptedImport(request), {code: 'import_invalid_request'});
  assert.equal(f.store.queryImport(f.request.identity), null);
});
test('注入隔离文件写入失败保留indeterminate，取消和重发不能伪装已确定结果', async t => {
  const f = await fixture(t); f.store.recordAcceptedImport(f.request); const originalOpen = fsp.open;
  fsp.open = async (filename, ...args) => {
    if (path.dirname(filename) === path.join(f.root, 'staging')) throw Object.assign(new Error('injected spool write failure'), {code: 'ENOSPC'});
    return originalOpen(filename, ...args);
  };
  let result;
  try { result = await copy(f); } finally { fsp.open = originalOpen; }
  assert.equal(result.state, 'indeterminate'); assert.equal(result.reason_code, 'storage_unknown');
  assert.throws(() => f.store.cancelImport(f.request.identity), {code: 'import_indeterminate'});
  await assert.rejects(copy(f), {code: 'import_indeterminate'});
  f.reopen(); assert.deepEqual(f.store.recordAcceptedImport(f.request), result);
});
test('安装目录身份变化锁存关闭当前writer，恢复路径不会复活该对象', async t => {
  const f = await fixture(t), staging = path.join(f.root, 'staging'), original = path.join(f.root, 'staging-original');
  fs.renameSync(staging, original); fs.mkdirSync(staging);
  assert.throws(() => f.store.queryImport(f.request.identity), {code: 'installation_directory_changed'});
  fs.rmdirSync(staging); fs.renameSync(original, staging);
  assert.throws(() => f.store.queryImport(f.request.identity), {code: 'installation_unavailable'});
  f.reopen(); assert.equal(f.store.queryImport(f.request.identity), null);
});
