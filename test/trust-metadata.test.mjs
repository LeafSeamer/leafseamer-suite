import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import Database from 'better-sqlite3';
import https from 'node:https';
import {createInstallationStore, openInstallationStore, createReleaseTransport} from '../dist/installation-store.mjs';
import {inspectMetadata} from '../dist/tuf-input.mjs';
import tuf from '../dist/vendor/tuf-js/dist/index.js';
import {repository, rawHash, fixedTime} from './fixtures/tuf-repository.mjs';
import {certificate} from './fixtures/tls-certificate.mjs';
import {artifactFixture, zipFixture, digestValue} from './fixtures/artifact-package.mjs';
import {releaseFixture} from './fixtures/release-manifest.mjs';
import {releaseRepository,openReleaseFixture} from './fixtures/release-authorization.mjs';
function fixture(t, repo) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'leafseamer-trust-'));
  const identity = createInstallationStore(directory); let store = openInstallationStore(directory); const sessions = [];
  t.after(() => { sessions.forEach(s => s.close()); store.close(); assert.equal(path.dirname(path.resolve(directory)), path.resolve(os.tmpdir())); fs.rmSync(directory, {recursive: true, force: true}); });
  const root = repo.root();
  store.trust.initialize('synthetic', root, {host_installation_id: identity.host_installation_id, bootstrap_operation_id: 'bootstrap.synthetic',
    channel_kind: 'independent_authenticated_channel', initial_root_digest: rawHash(root), verifier_digest: rawHash(Buffer.from('fixture')),
    approval_reference: 'approval.synthetic'});
  return {get store() { return store; }, directory,
    keep(session) {sessions.push(session);return session;},
    reopen() { sessions.forEach(s => s.close()); store.close(); store = openInstallationStore(directory); },
    session(files, options = {}) {
      const session = store.trust.openVerification({trust_domain_id: 'synthetic', session_id: crypto.randomUUID(), fixed_reference_time: fixedTime,
        context: {anchor_id: 'anchor.synthetic', evidence_reference: 'evidence.synthetic', profile_id: 'profile.synthetic'},
        metadata_base_url: 'https://synthetic.invalid/metadata/', fetcher: repo.fetcher(files), ...options}); sessions.push(session); return session;
    }
  };
}
test('真实签名经固定客户端验证并逐角色写入安装库，固定时间不读取当前墙钟', async t => {
  const repo = repository(), f = fixture(t, repo), session = f.session(repo.current());
  assert.throws(() => f.session(repo.current()), {code: 'trust_verification_in_progress'});
  assert.throws(() => f.store.close(), {code: 'import_copy_in_progress'});
  const result = await session.refresh(); assert.equal(result.metadata_epoch, 1);
  const target = await session.target('release.zip'); assert.equal(target.length, 17); assert.equal(target.custom.channel, 'synthetic');
  assert.equal(await session.target('missing.zip'), null);
  await assert.rejects(session.refresh(), {code: 'trust_refresh_once'});
  f.reopen(); assert.equal(f.store.trust.current('synthetic').root_version, 1);
  const resumed = f.session(repo.current()); await resumed.refresh(); assert.equal((await resumed.target('release.zip')).hashes.sha256, target.hashes.sha256);
});
test('在线密钥A到B到A跨重开仍保留pending，最终根完成后新代际可接受低版本', async t => {
  const repo = repository(), f = fixture(t, repo); const first = f.session(repo.current(900)); await first.refresh(); first.close();
  const secondRoot = repo.root(2, '2');
  const failure = f.session(new Map([['2.root.json', secondRoot]]), {fetcher: repo.fetcher(new Map([['2.root.json', secondRoot]]), name => { if (name === '3.root.json') throw new Error('transport interrupted'); })});
  await assert.rejects(failure.refresh(), /transport interrupted/);
  assert.deepEqual(f.store.trust.current('synthetic'), {root_version: 2, root_digest: rawHash(secondRoot), metadata_epoch: 1, reset_pending: true});
  f.reopen(); const files = repo.current(1); files.set('3.root.json', repo.root(3, '1'));
  const resumed = f.session(files); assert.equal((await resumed.refresh()).metadata_epoch, 2);
  assert.equal((await resumed.target('release.zip')).custom.channel, 'synthetic');
  assert.equal(f.store.trust.current('synthetic').reset_pending, false);
});
test('不足阈值、到期、降版本和篡改目标元数据被拒绝，已提交的前序角色不回滚', async t => {
  const repo = repository(), f = fixture(t, repo);
  const badRoot = new Map([['2.root.json', repo.root(2, '2', ['r1'])]]);
  await assert.rejects(f.session(badRoot).refresh()); assert.equal(f.store.trust.current('synthetic').root_version, 1);
  await assert.rejects(f.session(repo.current(), {fixed_reference_time: Date.parse('2021-01-01T00:00:00Z')}).refresh(), /expired/);
  const valid = f.session(repo.current(3)); await valid.refresh(); valid.close(); f.reopen();
  await assert.rejects(f.session(repo.current(2)).refresh(), /less than current/);
  const damaged = repo.current(4, '1', ['t1']);
  await assert.rejects(f.session(damaged).refresh());
  f.reopen(); await assert.rejects(f.session(repo.current(3)).refresh(), /less than current/);
});
test('严格元数据预检保留原字节，拒绝重复键、危险键、不安全版本及归一化日期', () => {
  const repo = repository(), bytes = repo.root(); assert.equal(inspectMetadata(bytes).signed.version, 1);
  assert.throws(() => inspectMetadata(Buffer.from(bytes.toString().replace('"version":1', '"version":1,"version":2'))));
  for (const value of [9007199254740992, 1.5, 0]) {
    const document = JSON.parse(bytes); document.signed.version = value; assert.throws(() => inspectMetadata(Buffer.from(JSON.stringify(document))));
  }
  const document = JSON.parse(bytes); document.signed.expires = '2021-02-30T00:00:00Z'; assert.throws(() => inspectMetadata(Buffer.from(JSON.stringify(document))));
  assert.throws(() => inspectMetadata(Buffer.from('{"__proto__":{},"signed":{}}')));
  assert.throws(() => inspectMetadata(Buffer.from([0xc0, 0x80])));
});

test('根持有人换组必须同时满足旧根与新根阈值，仅根换组不重置在线缓存代际', async t => {
  const repo = repository(), f = fixture(t, repo), next = ['r4','r5','r6'];
  for (const signers of [['r1','r2'], ['r4','r5']]) {
    await assert.rejects(f.session(new Map([['2.root.json', repo.root(2, '1', signers, next)]])).refresh());
    assert.equal(f.store.trust.current('synthetic').root_version, 1);
  }
  const files = repo.current(); files.set('2.root.json', repo.root(2, '1', ['r1','r2','r4','r5'], next));
  const session = f.session(files); const result = await session.refresh(); assert.equal(result.metadata_epoch, 1);
  assert.equal(f.store.trust.current('synthetic').root_version, 2);
});
test('持久化或读取失败使客户端锁存不可用，不采用仅存内存的根与目标', async () => {
  const repo = repository(), root = repo.root(); let writes = 0;
  const updater = new tuf.Updater({metadataDir: '', metadataBaseUrl: 'https://synthetic.invalid/', fixedReferenceTime: fixedTime,
    fetcher: repo.fetcher(new Map([['2.root.json', repo.root(2, '2')]])), metadataStorage: {
      loadTrusted: role => role === 'root' ? root : null,
      persistVerified() { ++writes; throw new Error('commit unknown'); }, finalizeRootPhase() { throw new Error('must not continue'); }
    }});
  await assert.rejects(updater.refresh(), /storage failed/); assert.equal(writes, 1);
  await assert.rejects(updater.getTargetInfo('release.zip'), /discard this updater/);
  await assert.rejects(updater.refresh(), /discard this updater/);
  const failing = new tuf.Updater({metadataDir: '', metadataBaseUrl: 'https://synthetic.invalid/', fixedReferenceTime: fixedTime,
    fetcher: repo.fetcher(repo.current()), metadataStorage: {loadTrusted(role) { if (role === 'root') return root; throw new Error('unreadable'); }, persistVerified() { throw new Error('must not write'); }, finalizeRootPhase() {}}});
  await assert.rejects(failing.refresh(), /discard this updater/);
});

test('根转换提交后实际终止进程，重开保留旧原字节与pending，SQL拒绝回退及删历史', {timeout: 20000}, async t => {
  const repo = repository(), f = fixture(t, repo), second = repo.root(2, '2'); f.store.close();
  const filename = path.join(f.directory, 'synthetic-metadata.json');
  fs.writeFileSync(filename, JSON.stringify([['2.root.json', second.toString('base64')]]));
  const child = spawn(process.execPath, ['--disallow-code-generation-from-strings', fileURLToPath(new URL('./fixtures/trust-root-child.mjs', import.meta.url)), f.directory, filename], {stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
  const closed = once(child, 'close'); let output = '', stderr = '';
  child.stderr.on('data', data => { stderr += data; });
  try {
    await new Promise((resolve, reject) => {
      child.on('error', reject); child.stdout.on('data', data => { output += data; if (output.includes('\n')) { child.kill(); resolve(); } });
      child.on('exit', () => { if (!output.includes('\n')) reject(new Error(stderr || 'no root checkpoint')); });
    });
    await closed; assert.equal(JSON.parse(output.trim()).reset_pending, true);
  } finally { if (child.exitCode === null && child.signalCode === null) { child.kill(); await closed; } }
  f.reopen(); assert.equal(f.store.trust.current('synthetic').root_version, 2); assert.equal(f.store.trust.current('synthetic').reset_pending, true);
  const session = f.session(repo.current(1, '2')); await session.refresh(); session.close(); f.store.close();
  const db = new Database(path.join(f.directory, 'installation.db'));
  try {
    db.pragma('foreign_keys=ON'); db.pragma('recursive_triggers=ON');
    assert.equal(db.prepare("SELECT count(*) FROM trusted_metadata WHERE role='root'").pluck().get(), 2);
    assert.equal(db.prepare('SELECT count(*) FROM trust_rotation').pluck().get(), 1);
    assert.throws(() => db.exec("UPDATE trust_root_state SET metadata_id=(SELECT metadata_id FROM trusted_metadata WHERE role='root' AND version=1)"));
    assert.throws(() => db.exec('UPDATE trust_root_state SET metadata_epoch=1'));
    for (const table of ['trust_domain','trusted_metadata','trust_root_transition','trust_rotation','trust_metadata_head','trust_verification_session']) assert.throws(() => db.exec('DELETE FROM '+table));
  } finally { db.close(); }
  f.reopen(); assert.equal(f.store.trust.current('synthetic').metadata_epoch, 2);
});

async function repositoryServer(t, files, payloads, mode = {value: 'normal'}) {
  const targets = payloads instanceof Map ? payloads : new Map([['release.zip', payloads]]);
  const cert = certificate(), requests = [];
  const server = https.createServer(cert, (request, response) => {
    requests.push(request.url);
    if (request.url.startsWith('/metadata/')) {
      const bytes = files.get(request.url.slice('/metadata/'.length));
      if (!bytes) { response.writeHead(404); response.end(); return; }
      response.writeHead(200, {'content-length': String(bytes.length)}); response.end(bytes); return;
    }
    const match = [...targets].find(([name, bytes]) => { const parts = name.split('/'); parts[parts.length - 1] = rawHash(bytes).slice(7) + '.' + parts.at(-1); return request.url === '/targets/' + parts.join('/'); });
    if (match) {
      const payload = match[1];
      if (mode.value === 'redirect') { response.writeHead(302, {location: '/unexpected'}); response.end(); return; }
      if (mode.value === 'gzip') { response.writeHead(200, {'content-encoding': 'gzip'}); response.end(payload); return; }
      if (mode.value === 'oversize') { response.writeHead(200, {'content-length': String(payload.length + 1)}); response.end(Buffer.concat([payload, Buffer.from('x')])); return; }
      if (mode.value === 'hold') { response.writeHead(200, {'content-length': String(payload.length)}); response.write(payload.subarray(0, 1)); mode.started(); return; }
      response.writeHead(200, {'content-length': String(payload.length)});
      response.end(mode.value === 'corrupt' ? Buffer.alloc(payload.length, 7) : payload); return;
    }
    response.writeHead(404); response.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const base = 'https://127.0.0.1:' + server.address().port;
  return {requests, metadata_base_url: base + '/metadata/', target_base_url: base + '/targets/',
    fetcher: createReleaseTransport({metadataBaseUrl: base + '/metadata/', targetBaseUrl: base + '/targets/', ca: cert.cert}),
    untrusted: createReleaseTransport({metadataBaseUrl: base + '/metadata/', targetBaseUrl: base + '/targets/'})};
}
test('真实HTTPS发行清单与归档生成当前发行记录，受理经原引用接入复制和ZIP而不授运行许可', {timeout: 20000}, async t => {
  const repo = repository(), f = fixture(t, repo), artifact = artifactFixture(), payload = zipFixture(artifact.entries()).bytes;
  f.store.trust.configureRevocations('synthetic',{target_path:'revocations.json',approval_reference:'approval.synthetic'});
  const release = releaseRepository(payload,digestValue(artifact.manifest),{repo}), server = await repositoryServer(t,release.files,release.payloads);
  const opened = await openReleaseFixture(f.store,release,{domain:'synthetic',...server}), session = f.keep(opened.session);
  await assert.rejects(session.download({path: 'extension.zip'}), {code: 'trust_target_request'});
  const receipt = opened.archive, downloaded = f.store.trust.downloadedArtifact(receipt.download_id), authorization = await opened.authorize();
  assert.equal(receipt.package_digest, rawHash(payload)); assert.deepEqual(fs.readFileSync(downloaded.filename), payload);
  assert.equal(downloaded.metadata.length, 4); assert.equal(downloaded.target.hashes.sha256, rawHash(payload).slice(7));
  const policy=f.store.validationPolicies.configure({policy_id:'policy.synthetic',approval_reference:'approval.synthetic'});
  // 发行及校验策略Ref来自实际持久记录；目标管理权、批准来源与时间环境仍为合成。
  const request = {identity: {host_installation_id: f.store.identity.host_installation_id, client_registration_id: 'client.synthetic', import_request_id: 'import.synthetic'},
    target_authority_service_id: 'controller.synthetic', source_attachment_id: 'attachment.synthetic', package_digest: receipt.package_digest, package_bytes: receipt.package_bytes,
    expected_manifest_digest: digestValue(artifact.manifest), host_trust_epoch: '1', release_authorization_ref: authorization.reference, validation_policy_ref: policy.reference};
  f.store.recordAcceptedImport(request); const fd = fs.openSync(downloaded.filename, 'r');
  try { await f.store.copyImport(request.identity, fd); } finally { fs.closeSync(fd); }
  assert.equal((await f.store.validateImport(request.identity)).state, 'validating');
  session.close(); await assert.rejects(session.download('release.zip'), {code: 'trust_session_unavailable'});
  f.reopen(); assert.deepEqual(f.store.trust.downloadedArtifact(receipt.download_id), downloaded);
});

test('全域撤销按当前会话持久采用，修订和历史撤销跨重开与在线密钥轮换保持', {timeout: 20000}, async t => {
  const repo = repository(), f = fixture(t, repo), targetPath = 'policy/revocations.json';
  const policy = {target_path: targetPath, approval_reference: 'approval.synthetic'};
  assert.deepEqual(f.store.trust.configureRevocations('synthetic', policy), {trust_domain_id: 'synthetic', ...policy});
  assert.throws(() => f.store.trust.configureRevocations('synthetic', {...policy, target_path: 'other.json'}), {code: 'trust_revocation_policy_conflict'});
  const manifestDigest = rawHash(Buffer.from('manifest')), artifactDigest = rawHash(Buffer.from('artifact'));
  const original = {format: 'release-revocations/1', revision: '9007199254740993', revoked_release_ids: ['revoked.release'],
    revoked_manifest_digests: [manifestDigest], revoked_artifact_digests: [artifactDigest]};
  const payloads = new Map([[targetPath, Buffer.from(JSON.stringify(original))]]), files = repo.current(1, '1', ['t1','t2'], payloads);
  const server = await repositoryServer(t, files, payloads);
  async function adopt() {
    const session = f.session(files, server); await session.refresh();
    const download = await session.download(targetPath), document = await f.store.trust.inspectDownloadedDocument(download.download_id, 'revocations');
    return {session, document, adopt: () => session.adoptRevocations(document.document_id)};
  }
  const first = await adopt(), initial = await first.adopt();
  assert.equal(initial.revision, original.revision); assert.deepEqual(await first.adopt(), initial);
  first.session.close(); f.reopen();
  const record = f.store.trust.lookupRevocation('synthetic', 'release_id', 'revoked.release');
  assert.equal(record.snapshot_id, initial.snapshot_id);
  const second = await adopt(), repeat = await second.adopt();
  assert.equal(repeat.snapshot_id, initial.snapshot_id); assert.notEqual(repeat.adoption_id, initial.adoption_id); second.session.close();
  const replace = (value, version, online = '1', spaces) => {
    payloads.set(targetPath, Buffer.from(JSON.stringify(value, null, spaces))); files.clear();
    for (const [name, bytes] of repo.current(version, online, ['t1','t2'], payloads)) files.set(name, bytes);
  };
  // 同修订即使JSON语义一致，原字节不同也不能覆盖。
  replace(original, 2, '1', 2); const conflict = await adopt();
  await assert.rejects(conflict.adopt(), {code: 'trust_revocation_conflict'});
  replace({...original, revision: '9007199254740992'}, 3); const lower = await adopt();
  await assert.rejects(lower.adopt(), {code: 'trust_revocation_rollback'});
  const newer = {...original, revision: '9007199254740994', revoked_release_ids: [], revoked_manifest_digests: [], revoked_artifact_digests: []};
  replace(newer, 4); const next = await adopt(); await next.adopt(); next.session.close(); f.reopen();
  assert.deepEqual(f.store.trust.lookupRevocation('synthetic', 'release_id', 'revoked.release'), record);
  replace({...newer, revision: '9007199254740995'}, 1, '2'); files.set('2.root.json', repo.root(2, '2'));
  const rotated = await adopt(); const rotatedResult = await rotated.adopt(); assert.equal(rotatedResult.metadata_epoch, 2); rotated.session.close(); f.reopen();
  for (const [kind, value] of [['release_id','revoked.release'],['manifest_digest',manifestDigest],['artifact_digest',artifactDigest]])
    assert.equal(f.store.trust.lookupRevocation('synthetic', kind, value).snapshot_id, initial.snapshot_id);
  assert.equal(f.store.trust.lookupRevocation('synthetic', 'release_id', 'not.revoked'), null);
  replace(newer, 2, '2'); const afterRotation = await adopt(); await assert.rejects(afterRotation.adopt(), {code: 'trust_revocation_rollback'});
  f.store.close(); const db = new Database(path.join(f.directory, 'installation.db'));
  try {
    db.pragma('foreign_keys=ON'); db.pragma('recursive_triggers=ON');
    assert.equal(db.prepare('SELECT count(*) FROM trust_revocation_snapshot').pluck().get(), 3);
    assert.equal(db.prepare('SELECT count(*) FROM trust_revocation_record').pluck().get(), 3);
    assert.equal(db.prepare('SELECT count(*) FROM trust_revocation_adoption').pluck().get(), 4);
    for (const table of ['trust_revocation_policy','trust_revocation_snapshot','trust_revocation_record','trust_revocation_adoption']) assert.throws(() => db.exec('DELETE FROM ' + table));
    assert.throws(() => db.prepare('INSERT INTO trust_revocation_snapshot VALUES (?,?,?,?,?)').run(crypto.randomUUID(), 'synthetic', original.revision, first.document.document_id, first.document.package_digest));
  } finally { db.close(); } f.reopen();
});

test('撤销采用拒绝无配置、错误路径、跨会话原件及已关闭会话', {timeout: 20000}, async t => {
  const repo = repository(), f = fixture(t, repo), bytes = Buffer.from(JSON.stringify({format:'release-revocations/1',revision:'1',revoked_release_ids:[],revoked_manifest_digests:[],revoked_artifact_digests:[]}));
  const payloads = new Map([['revocations.json',bytes],['other.json',bytes]]), files = repo.current(1, '1', ['t1','t2'], payloads);
  const server = await repositoryServer(t, files, payloads);
  async function prepare(name) {
    const session = f.session(files, server); await session.refresh(); const download = await session.download(name);
    const document = await f.store.trust.inspectDownloadedDocument(download.download_id, 'revocations'); return {session, document};
  }
  const missing = await prepare('revocations.json');
  await assert.rejects(missing.session.adoptRevocations(missing.document.document_id), {code:'trust_revocation_source'});
  f.store.trust.configureRevocations('synthetic',{target_path:'revocations.json',approval_reference:'approval.synthetic'});
  const wrong = await prepare('other.json');
  await assert.rejects(wrong.session.adoptRevocations(wrong.document.document_id), {code:'trust_revocation_source'});
  const old = await prepare('revocations.json'); old.session.close();
  const current = f.session(files, server); await current.refresh();
  await assert.rejects(current.adoptRevocations(old.document.document_id), {code:'trust_revocation_source'});
  await assert.rejects(old.session.adoptRevocations(old.document.document_id), {code:'trust_session_unavailable'});
  assert.equal(f.store.trust.lookupRevocation('synthetic','release_id','any.release'), null);
});

test('局部委托签名不能通过指定路径取得全信任域撤销权', {timeout: 20000}, async t => {
  const repo = repository(), f = fixture(t, repo), targetPath = 'revocations.json';
  f.store.trust.configureRevocations('synthetic', {target_path: targetPath, approval_reference:'approval.synthetic'});
  const bytes = Buffer.from(JSON.stringify({format:'release-revocations/1',revision:'1',revoked_release_ids:['victim'],revoked_manifest_digests:[],revoked_artifact_digests:[]}));
  const ref = data => ({version:1,length:data.length,hashes:{sha256:rawHash(data).slice(7)}});
  const delegated = repo.sign({...repo.base('targets',1),targets:{[targetPath]:ref(bytes)}}, ['t1']);
  const targets = repo.sign({...repo.base('targets',1),targets:{},delegations:{keys:{t1:JSON.parse(repo.root()).signed.keys.t1},roles:[{name:'extension',keyids:['t1'],threshold:1,terminating:true,paths:[targetPath]}]}}, ['t1','t2']);
  const snapshot = repo.sign({...repo.base('snapshot',1),meta:{'targets.json':ref(targets),'extension.json':ref(delegated)}}, ['s1']);
  const timestamp = repo.sign({...repo.base('timestamp',1),meta:{'snapshot.json':ref(snapshot)}}, ['z1']);
  const files = new Map([['timestamp.json',timestamp],['1.snapshot.json',snapshot],['1.targets.json',targets],['1.extension.json',delegated]]);
  const server = await repositoryServer(t, files, new Map([[targetPath,bytes]]));
  const session = f.session(files, server); await session.refresh();
  const download = await session.download(targetPath), document = await f.store.trust.inspectDownloadedDocument(download.download_id,'revocations');
  await assert.rejects(session.adoptRevocations(document.document_id), {code:'trust_revocation_authority'});
  assert.equal(f.store.trust.lookupRevocation('synthetic','release_id','victim'),null);
});
test('真实HTTPS拒绝未信任证书、跨源、重定向、压缩、超长和错hash，会话关闭中止未完成下载', {timeout: 20000}, async t => {
  const repo = repository(), f = fixture(t, repo), payload = Buffer.from('synthetic payload'), files = repo.current(), mode = {value: 'normal'};
  const server = await repositoryServer(t, files, payload, mode);
  await assert.rejects(server.untrusted.downloadBytes(server.metadata_base_url + 'timestamp.json', 4194304));
  await assert.rejects(server.fetcher.downloadBytes('https://other.invalid/metadata/root.json', 4194304), {code: 'trust_transport_scope'});
  for (const value of ['redirect','gzip','oversize','corrupt']) {
    mode.value = value; const session = f.session(files, server); await session.refresh(); await assert.rejects(session.download('release.zip'));
  }
  assert.ok(!server.requests.includes('/unexpected'));
  let started; const reached = new Promise(resolve => { started = resolve; }); mode.started = started; mode.value = 'hold';
  const session = f.session(files, server); await session.refresh(); const pending = session.download('release.zip');
  const failed = assert.rejects(pending); await reached; session.close(); await failed;
  f.store.close(); const db = new Database(path.join(f.directory, 'installation.db'));
  try { assert.equal(db.prepare('SELECT count(*) FROM trust_download_attempt').pluck().get(), 5); assert.equal(db.prepare('SELECT count(*) FROM trust_download_receipt').pluck().get(), 0); }
  finally { db.close(); } f.reopen(); assert.equal(f.store.trust.current('synthetic').root_version, 1);
});

test('已验证下载的完整发行文档经SDK闭包检查持久查原，隔离文件变化不能替代原文档', {timeout: 20000}, async t => {
  const repo = repository(), f = fixture(t, repo), manifest = releaseFixture(), payload = Buffer.from(JSON.stringify(manifest));
  const files = repo.current(1, '1', ['t1','t2'], payload), server = await repositoryServer(t, files, payload);
  const session = f.session(files, server); await session.refresh();
  const first = await session.download('release.zip'), second = await session.download('release.zip');
  const result = await f.store.trust.inspectDownloadedDocument(first.download_id, 'release');
  assert.deepEqual(result.document, manifest); assert.equal(result.package_digest, rawHash(payload));
  await assert.rejects(f.store.trust.inspectDownloadedDocument(second.download_id, 'revocations'));
  const secondFile = f.store.trust.downloadedArtifact(second.download_id).filename;
  fs.writeFileSync(secondFile, Buffer.alloc(payload.length, 32));
  await assert.rejects(f.store.trust.inspectDownloadedDocument(second.download_id, 'release'), {code: 'trust_document_digest'});
  fs.writeFileSync(f.store.trust.downloadedArtifact(first.download_id).filename, Buffer.from('changed'));
  session.close(); f.reopen();
  assert.deepEqual(await f.store.trust.inspectDownloadedDocument(first.download_id, 'release'), result);
  f.store.close(); const db = new Database(path.join(f.directory, 'installation.db'));
  try { assert.equal(db.prepare('SELECT count(*) FROM trust_release_document').pluck().get(),1); assert.throws(()=>db.exec('DELETE FROM trust_release_document')); }
  finally { db.close(); } f.reopen();
});
