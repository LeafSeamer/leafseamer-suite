import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {verifyArchive} from '../dist/archive-verifier.mjs';
import {createInstallationStore, openInstallationStore} from '../dist/installation-store.mjs';
import {artifactFixture, zipFixture, rawDigest, digestValue} from './fixtures/artifact-package.mjs';
import {authorizeFixture} from './fixtures/release-authorization.mjs';
function directory(t, beforeRemove = () => {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'leafseamer-archive-'));
  t.after(() => { beforeRemove(); assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir())); fs.rmSync(root, {recursive: true, force: true}); }); return root;
}
async function run(t, fixture, archive) {
  const root = directory(t), filename = path.join(root, 'package.zip'), output = path.join(root, 'payload'); fs.writeFileSync(filename, archive.bytes);
  const result = await verifyArchive(filename, {package_bytes: String(archive.bytes.length), package_digest: rawDigest(archive.bytes), expected_manifest_digest: digestValue(fixture.manifest)}, output);
  return {root, output, result};
}
test('真实ZIP支持stored/deflate、数据描述符、ZIP64及中央目录乱序，不执行payload', {timeout: 20000}, async t => {
  for (const options of [{}, {deflate: true, descriptor: true}, {deflate: true, zip64: true}, {deflate: true, zip64: true, descriptor: true, reverseCentral: true}]) {
    const fixture = artifactFixture(), archive = zipFixture(fixture.entries(), options); const {output, result} = await run(t, fixture, archive);
    assert.equal(result.file_count, fixture.inventory.files.length); assert.equal(result.artifact_set_digest, digestValue(fixture.inventory));
    for (const file of fixture.payload.values()) assert.deepEqual(fs.readFileSync(path.join(output, file.path)), file.bytes);
    assert.equal(fs.existsSync(path.join(output, 'extension.json')), false); assert.equal(globalThis.archiveExecuted, undefined);
  }
});
test('实际归档拒绝local/central冲突、CRC错误、重叠、跨盘、加密及未知条目', {timeout: 20000}, async t => {
  const mutations = [
    a => { a.bytes[a.records[0].localOffset + 30] = 'z'.charCodeAt(0); },
    a => { a.bytes.writeUInt32LE(9, a.records[0].localOffset + 14); a.bytes.writeUInt32LE(9, a.records[0].centralOffset + 16); },
    a => { a.bytes.writeUInt32LE(a.records[0].localOffset, a.records[1].centralOffset + 42); },
    a => { a.bytes.writeUInt16LE(1, a.records[0].centralOffset + 34); },
    a => { a.bytes.writeUInt16LE(1, a.records[0].centralOffset + 8); }
  ];
  for (const mutate of mutations) { const f = artifactFixture(), a = zipFixture(f.entries()); mutate(a); await assert.rejects(run(t, f, a)); }
  const f = artifactFixture(); await assert.rejects(run(t, f, zipFixture([...f.entries(), {name: 'unlisted.txt', bytes: Buffer.from('x')}])), {code: 'archive_entry_count'});
});
test('ZIP拒绝路径穿越、大小写别名、符号链接、错误清单及控制文档重复键', {timeout: 20000}, async t => {
  for (const name of ['../escape', 'payload/../escape', 'payload\\escape', 'CON', 'file:stream']) {
    const f = artifactFixture(); await assert.rejects(run(t, f, zipFixture([...f.entries(), {name, bytes: Buffer.from('x')}])));
  }
  {
    const f = artifactFixture(), a = zipFixture(f.entries()); a.bytes.writeUInt32LE(0xa1ff0000, a.records.at(-1).centralOffset + 38);
    await assert.rejects(run(t, f, a), {code: 'archive_file_type'});
  }
  {
    const f = artifactFixture(), entries = f.entries(); entries[0].bytes = Buffer.from(entries[0].bytes.toString().replace('{', '{"extension_id":"duplicate",'));
    await assert.rejects(run(t, f, zipFixture(entries)), {code: 'archive_document'});
  }
  {
    const f = artifactFixture(); f.inventory.files[0].digest = rawDigest('wrong'); f.manifest.inventory_digest = digestValue(f.inventory);
    await assert.rejects(run(t, f, zipFixture(f.entries())), {code: 'archive_file_digest'});
  }
  {
    const f = artifactFixture(); f.manifest.dependency_lock_file_id = 'worker'; await assert.rejects(run(t, f, zipFixture(f.entries())), {code: 'archive_file_role'});
  }
  {
    const f = artifactFixture(); f.manifest.permission_templates = [{request_id: 'device', kind: 'device_scope', purpose: 'synthetic',
      scope: {device_role: 'undeclared', action_ids: ['read'], trigger_ids: []}}];
    await assert.rejects(run(t, f, zipFixture(f.entries())), {code: 'archive_role_reference'});
  }
  {
    const f = artifactFixture(); f.inventory.files[1].path = f.inventory.files[0].path.toUpperCase(); f.manifest.inventory_digest = digestValue(f.inventory);
    await assert.rejects(run(t, f, zipFixture(f.entries())), {code: 'archive_document'});
  }
});
async function imported(t, fixture, archive) {
  let store;
  const root = directory(t, () => store?.close()), installation = path.join(root, 'installation'); fs.mkdirSync(installation);
  const host = createInstallationStore(installation); store = openInstallationStore(installation);
  const ref = kind => ({kind, authority_service_id: host.authority_service_id, database_instance_id: host.database_instance_id,
    object_id: kind + '.synthetic', revision: '1', digest: digestValue(kind)});
  const request = {identity: {host_installation_id: host.host_installation_id, client_registration_id: 'client.synthetic', import_request_id: 'request.synthetic'},
    target_authority_service_id: 'controller.synthetic', source_attachment_id: 'attachment.synthetic', package_digest: rawDigest(archive.bytes),
    package_bytes: String(archive.bytes.length), expected_manifest_digest: digestValue(fixture.manifest), host_trust_epoch: '1',
    release_authorization_ref: ref('release_authorization'), validation_policy_ref: ref('validation_policy')};
  const authorized = await authorizeFixture(store,archive.bytes,request.expected_manifest_digest);
  try { request.release_authorization_ref=authorized.result.reference;request.validation_policy_ref=authorized.validationPolicy.reference; store.recordAcceptedImport(request); } finally { authorized.session.close(); }
  const filename = path.join(root, 'package.zip'); fs.writeFileSync(filename, archive.bytes); const fd = fs.openSync(filename, 'r');
  try { await store.copyImport(request.identity, fd); } finally { fs.closeSync(fd); }
  return {request, get store() { return store; }, reopen() { store.close(); store = openInstallationStore(installation); }};
}
test('Suite受理、复制、静态解压及原件查回形成真实文件库闭环，重启和重复请求不重复验证', {timeout: 20000}, async t => {
  const f = artifactFixture(), state = await imported(t, f, zipFixture(f.entries(), {deflate: true, descriptor: true, zip64: true}));
  assert.throws(() => state.store.validatedArtifact(state.request.identity), {code: 'import_validation_unavailable'});
  const result = await state.store.validateImport(state.request.identity); assert.equal(result.state, 'validating'); assert.equal(result.receipt, null);
  const artifact = state.store.validatedArtifact(state.request.identity);
  for (const file of f.payload.values()) assert.deepEqual(fs.readFileSync(path.join(artifact.payload_directory, file.path)), file.bytes);
  assert.equal(artifact.report.manifest_digest, state.request.expected_manifest_digest); assert.equal(artifact.report.artifact_set_digest, digestValue(f.inventory));
  assert.deepEqual(await state.store.validateImport(state.request.identity), result); state.reopen();
  assert.deepEqual(state.store.validatedArtifact(state.request.identity), artifact); assert.deepEqual(state.store.recordAcceptedImport(state.request), result);
});
test('静态验证失败永久拒绝原operation，取消先提交时不采用迟到结果', {timeout: 20000}, async t => {
  {
    const f = artifactFixture(), entries = f.entries(); entries[0].bytes = Buffer.from('{}'); const state = await imported(t, f, zipFixture(entries));
    const result = await state.store.validateImport(state.request.identity); assert.equal(result.state, 'rejected'); assert.equal(result.reason_code, 'invalid_archive');
    assert.deepEqual(await state.store.validateImport(state.request.identity), result); state.reopen(); assert.deepEqual(state.store.recordAcceptedImport(state.request), result);
  }
  {
    const f = artifactFixture(), state = await imported(t, f, zipFixture(f.entries()));
    const pending = state.store.validateImport(state.request.identity);
    await assert.rejects(state.store.validateImport(state.request.identity), {code: 'import_validation_in_progress'});
    const cancelled = state.store.cancelImport(state.request.identity); assert.deepEqual(await pending, cancelled);
    assert.throws(() => state.store.validatedArtifact(state.request.identity), {code: 'import_validation_unavailable'});
  }
});

test('验证前隔离包不可读取保留存储未知，不误判为永久无效归档', async t => {
  const f = artifactFixture(), state = await imported(t, f, zipFixture(f.entries()));
  const original = state.store.copiedArtifact(state.request.identity);
  fs.renameSync(original.filename, original.filename + '.unavailable');
  const result = await state.store.validateImport(state.request.identity);
  assert.equal(result.state, 'indeterminate'); assert.equal(result.reason_code, 'storage_unknown');
  fs.renameSync(original.filename + '.unavailable', original.filename);
  assert.throws(() => state.store.cancelImport(state.request.identity), {code: 'import_indeterminate'});
  state.reopen(); assert.deepEqual(state.store.recordAcceptedImport(state.request), result);
  assert.deepEqual(await state.store.validateImport(state.request.identity), result);
  assert.throws(() => state.store.validatedArtifact(state.request.identity), {code: 'import_validation_unavailable'});
});
