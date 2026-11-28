import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {DatabaseSync} from 'node:sqlite';
import {setTimeout as delay} from 'node:timers/promises';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';
import {stageSQLiteSnapshot} from '@leafseamer/suite/sqlite-snapshot';

const exec = promisify(execFile);
const executable = name => fileURLToPath(new URL('../dist/native/leafseamer_' + name +
  (process.platform === 'win32' ? '.exe' : ''), import.meta.url));
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

async function fixture(t, authority, {exclusive = false, corrupt = false, payload = false} = {}) {
  const parent = await fs.mkdtemp(path.join(os.tmpdir(), 'leafseamer-snapshot-'));
  const sourceDirectory = path.join(parent, '业务数据'), stagingDirectory = path.join(parent, '暂存');
  await fs.mkdir(sourceDirectory);
  await fs.mkdir(stagingDirectory);
  const db = new DatabaseSync(path.join(sourceDirectory, authority + '.sqlite'), {enableForeignKeyConstraints: false});
  t.after(async () => {
    if (db.isOpen) db.close();
    await fs.rm(parent, {recursive: true, force: true});
  });
  const control = authority === 'controller';
  const scope = {authority, service_id: crypto.randomUUID(), database_instance_id: crypto.randomUUID(),
    request_epoch: crypto.randomUUID(), control_epoch: control ? crypto.randomUUID() : null, schema_revision: control ? '113' : '20'};
  db.exec(`PRAGMA locking_mode=${exclusive ? 'EXCLUSIVE' : 'NORMAL'};
    PRAGMA journal_mode=WAL;
    PRAGMA wal_autocheckpoint=0;
    PRAGMA application_id=${control ? 0x4c53434c : 0x4c53534d};
    PRAGMA user_version=${scope.schema_revision};
    CREATE TABLE service_state(singleton INTEGER PRIMARY KEY, authority TEXT, service_id TEXT, database_instance_id TEXT,
      request_epoch TEXT, schema_revision TEXT${control ? ', control_epoch TEXT' : ''}) STRICT;
    CREATE TABLE first_value (value INTEGER PRIMARY KEY);
    CREATE TABLE second_value (value INTEGER PRIMARY KEY);
    CREATE TABLE child (parent INTEGER REFERENCES first_value(value));
    INSERT INTO first_value VALUES (0);
    INSERT INTO second_value VALUES (0);`);
  const insert = db.prepare('INSERT INTO service_state VALUES(1,?,?,?,?,?' + (control ? ',?' : '') + ')');
  insert.run(scope.authority, scope.service_id, scope.database_instance_id, scope.request_epoch, scope.schema_revision,
    ...(control ? [scope.control_epoch] : []));
  if (corrupt) db.exec('INSERT INTO child VALUES (99)');
  if (payload) db.exec(`CREATE TABLE pages(data BLOB);
    WITH RECURSIVE rows(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM rows WHERE n<3840)
    INSERT INTO pages SELECT zeroblob(8192) FROM rows;`);
  return {parent, db, input: {sourceDirectory, stagingDirectory, operationId: crypto.randomUUID(), scope}};
}

test('copies a live WAL Controller snapshot and passes it to the packaged archive tool', {timeout: 30000}, async t => {
  const {parent, db, input} = await fixture(t, 'controller', {payload: true});
  const stagedFile = path.join(input.stagingDirectory, 'snapshot.partial', 'data.sqlite');
  let finished = false;
  const pending = stageSQLiteSnapshot(input).finally(() => { finished = true; });
  // Keep the original rejection observable even if setup exits early.
  pending.catch(() => {});
  try {
    for (let i = 0; i < 2000 && !finished; i++) {
      if (await fs.stat(stagedFile).then(info => info.size > 0, () => false)) break;
      await delay(2);
    }
    assert.equal(finished, false, 'copy still running when the source writes');
    assert.ok((await fs.stat(stagedFile)).size > 0, 'native helper has copied pages');
    db.exec('BEGIN IMMEDIATE; UPDATE first_value SET value=1; UPDATE second_value SET value=1; COMMIT');
  } finally {
    await pending;
  }
  const captured = await pending;
  assert.equal(captured.state, 'staged');
  assert.equal(captured.backup_operation_id, input.operationId);
  assert.deepEqual(captured.scope, input.scope);
  assert.equal(captured.path, stagedFile);
  const content = await fs.readFile(stagedFile);
  assert.equal(captured.bytes, content.length);
  assert.equal(captured.sha256, sha256(content));
  const snapshot = new DatabaseSync(stagedFile, {readOnly: true});
  try {
    const values = snapshot.prepare('SELECT first_value.value AS a, second_value.value AS b FROM first_value, second_value').get();
    assert.equal(values.a, values.b);
    assert.ok(values.a === 0 || values.a === 1);
    assert.equal(snapshot.prepare('SELECT count(*) AS n FROM pages').get().n, 3840);
    assert.equal(snapshot.prepare('PRAGMA journal_mode').get().journal_mode, 'delete');
  } finally { snapshot.close(); }
  assert.equal(db.prepare('SELECT value FROM first_value').get().value, 1);
  await assert.rejects(stageSQLiteSnapshot(input), {code: 'EEXIST'});

  const archive = path.join(parent, 'archive');
  const entry = 'db/controller.sqlite';
  await fs.mkdir(path.join(archive, 'files', 'db'), {recursive: true});
  await fs.copyFile(stagedFile, path.join(archive, 'files', entry));
  const manifest = {format: 'leafseamer-backup-tar/1', backup_id: input.operationId, level: 'L2', consistency: 'online',
    files: [{role: 'database', path: entry, size: captured.bytes, sha256: captured.sha256}],
    databases: [{path: entry, service: captured.scope.service_id, database_instance: captured.scope.database_instance_id,
      schema: captured.scope.schema_revision, engine: captured.engine, consistency_point: captured.backup_operation_id}],
    coverage: [], unresolved: [], validation_reports: []};
  await fs.writeFile(path.join(archive, 'manifest.json'), JSON.stringify(manifest));
  const packed = await exec(executable('backup_crypto'), ['pack', '--directory', archive], {windowsHide: true});
  assert.equal(JSON.parse(packed.stdout).state, 'staged');
  await fs.rename(path.join(archive, 'plaintext.tar'), path.join(archive, 'plaintext.tar.partial'));
  const verified = await exec(executable('backup_crypto'), ['verify', '--directory', archive], {windowsHide: true});
  assert.deepEqual(JSON.parse(verified.stdout), {...JSON.parse(packed.stdout), state: 'verified'});
});

test('requires an exclusive Seamer connection to close before its maintenance snapshot', async t => {
  const {db, input} = await fixture(t, 'seamer', {exclusive: true});
  await assert.rejects(stageSQLiteSnapshot(input), {message: 'snapshot_source'});
  assert.deepEqual(await fs.readdir(input.stagingDirectory), []);
  db.close();
  await assert.rejects(stageSQLiteSnapshot({...input, scope: {...input.scope, database_instance_id: crypto.randomUUID()}}),
    {message: 'snapshot_source'});
  assert.deepEqual(await fs.readdir(input.stagingDirectory), []);
  const staged = await stageSQLiteSnapshot(input);
  assert.equal(staged.state, 'staged');
  assert.equal(staged.scope.authority, 'seamer');
});

test('rejects a copied database with inconsistent foreign keys and removes its stage', async t => {
  const {input} = await fixture(t, 'controller', {corrupt: true});
  await assert.rejects(stageSQLiteSnapshot(input), {message: 'snapshot_validation'});
  assert.deepEqual(await fs.readdir(input.stagingDirectory), []);
});
