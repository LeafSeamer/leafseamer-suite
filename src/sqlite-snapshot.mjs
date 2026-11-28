import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';

const exec = promisify(execFile);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const engine = '3.53.4';
const executable = fileURLToPath(new URL('./native/leafseamer_sqlite_snapshot' +
  (process.platform === 'win32' ? '.exe' : ''), import.meta.url));
const errors = new Set(['snapshot_source', 'snapshot_capacity', 'snapshot_disk_space', 'snapshot_destination',
  'snapshot_backup_init', 'snapshot_backup_step', 'snapshot_backup_finish', 'snapshot_deadline', 'snapshot_clock',
  'snapshot_validation', 'snapshot_close']);
const outputName = 'data.sqlite';
const maxBytes = 32 * 1024 ** 3;

function need(condition, code) {
  if (!condition) throw new Error(code);
}

function validScope(scope) {
  return scope && ['controller', 'seamer'].includes(scope.authority) &&
    [scope.service_id, scope.database_instance_id, scope.request_epoch].every(value => typeof value === 'string' && uuid.test(value)) &&
    (scope.authority === 'controller' ? typeof scope.control_epoch === 'string' && uuid.test(scope.control_epoch) :
      scope.control_epoch === null) &&
    typeof scope.schema_revision === 'string' && /^[1-9][0-9]{0,9}$/.test(scope.schema_revision) &&
    Number(scope.schema_revision) <= 2147483647;
}

async function copy(source, output, stage, scope, deadline) {
  const budget = Math.floor(deadline - performance.now());
  need(budget > 0, 'snapshot_deadline');
  let stdout;
  try {
    ({stdout} = await exec(executable, [source, output, stage, scope.authority, scope.service_id, scope.database_instance_id,
      scope.request_epoch, scope.control_epoch ?? '', scope.schema_revision],
    {windowsHide: true, timeout: budget, killSignal: 'SIGKILL', maxBuffer: 4096}));
  } catch (error) {
    need(performance.now() < deadline, 'snapshot_deadline');
    const reason = error.stderr?.trim();
    throw new Error(errors.has(reason) ? reason : 'snapshot_process');
  }
  let report;
  try { report = JSON.parse(stdout); }
  catch { throw new Error('snapshot_process'); }
  need(report && Number.isSafeInteger(report.page_count) && report.page_count > 0 &&
    Number.isSafeInteger(report.page_size) && report.page_size >= 512 && report.page_size <= 65536,
  'snapshot_process');
  return report.page_count * report.page_size;
}

async function digest(output, expectedBytes, deadline) {
  const fd = await fs.open(output, 'r+');
  try {
    const info = await fd.stat();
    need(info.isFile() && info.size === expectedBytes && info.size <= maxBytes, 'snapshot_output_size');
    await fd.sync();
    const hash = crypto.createHash('sha256');
    let bytes = 0;
    const stream = fd.createReadStream({autoClose: false, start: 0, end: expectedBytes});
    for await (const block of stream) {
      need(performance.now() < deadline, 'snapshot_deadline');
      bytes += block.length;
      hash.update(block);
    }
    need(bytes === expectedBytes, 'snapshot_output_size');
    return hash.digest('hex');
  } finally { await fd.close(); }
}

export async function stageSQLiteSnapshot({sourceDirectory, stagingDirectory, operationId, scope}) {
  const deadline = performance.now() + 1800000;
  need(typeof sourceDirectory === 'string' && path.isAbsolute(sourceDirectory) &&
    typeof stagingDirectory === 'string' && path.isAbsolute(stagingDirectory) &&
    typeof operationId === 'string' && uuid.test(operationId) && validScope(scope), 'snapshot_arguments');
  const identity = {authority: scope.authority, service_id: scope.service_id, database_instance_id: scope.database_instance_id,
    control_epoch: scope.control_epoch, request_epoch: scope.request_epoch, schema_revision: scope.schema_revision};
  const source = path.join(sourceDirectory, identity.authority + '.sqlite');
  need(await fs.lstat(source).then(info => info.isFile(), () => false), 'snapshot_source');
  const directory = await fs.realpath(stagingDirectory);
  const stage = path.join(directory, 'snapshot.partial');
  const output = path.join(stage, outputName);
  await fs.mkdir(stage, {mode: 0o700});
  try {
    const reserved = await fs.open(output, 'wx', 0o600);
    await reserved.close();
    const bytes = await copy(source, output, stage, identity, deadline);
    const sha256 = await digest(output, bytes, deadline);
    const files = await fs.readdir(stage);
    need(files.length === 1 && files[0] === outputName, 'snapshot_sidecar');
    need(performance.now() < deadline, 'snapshot_deadline');
    return Object.freeze({state: 'staged', backup_operation_id: operationId, scope: Object.freeze(identity), engine, bytes, sha256,
      path: output});
  } catch (error) {
    for (const suffix of ['', '-journal', '-wal', '-shm']) {
      await fs.unlink(output + suffix).catch(cleanup => { if (cleanup.code !== 'ENOENT') throw cleanup; });
    }
    await fs.rmdir(stage);
    throw error;
  }
}
