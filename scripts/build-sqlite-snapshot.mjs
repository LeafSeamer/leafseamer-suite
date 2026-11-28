import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = path.join(root, 'native/sqlite-snapshot.c');
const sqlite = path.join(root, 'node_modules/better-sqlite3/deps/sqlite3');
const inputs = {
  'sqlite3.c': '6a2805f8c1ef020a7086e62258519323cf98b219e9fe87a42065d916cfebaefc',
  'sqlite3.h': '919e7f2e8ed1d8f56ac17b412b8971c76aa5d1a879752cc6058f75e7d5910e1d'
};
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const windows = process.platform === 'win32';
export const snapshotExecutable = 'native/leafseamer_sqlite_snapshot' + (windows ? '.exe' : '');

async function verifyInputs() {
  for (const [name, digest] of Object.entries(inputs)) {
    if (hash(await fs.readFile(path.join(sqlite, name))) !== digest) throw new Error('snapshot_build_sqlite');
  }
  return hash(await fs.readFile(source));
}

export async function buildSQLiteSnapshot() {
  if ((!windows && process.platform !== 'linux') || process.arch !== 'x64') throw new Error('snapshot_build_platform');
  const before = await verifyInputs();
  const compiler = windows ? process.env.LEAFSEAMER_SNAPSHOT_ZIG ?? 'zig' : 'cc';
  const version = execFileSync(compiler, [windows ? 'version' : '--version'], {encoding: 'utf8', windowsHide: true}).split(/\r?\n/)[0];
  if (windows && version !== '0.15.2') throw new Error('snapshot_build_compiler');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'leafseamer-snapshot-'));
  const executable = path.join(directory, path.basename(snapshotExecutable));
  try {
    const platformFlags = windows ? ['cc', '-target', 'x86_64-windows-gnu', '-municode', '-g0', '-s'] :
      ['-D_GNU_SOURCE', '-fPIE', '-pie', '-Wl,-z,relro,-z,now'];
    const args = [...platformFlags, '-O2', '-std=c11', '-Werror=implicit-function-declaration',
      '-fstack-protector-strong', '-DSQLITE_THREADSAFE=1', '-DSQLITE_OMIT_LOAD_EXTENSION', '-DSQLITE_DQS=0',
      '-I', sqlite, '-o', executable, source, path.join(sqlite, 'sqlite3.c'), ...(!windows ? ['-lm', '-lpthread'] : [])];
    execFileSync(compiler, args, {cwd: directory, stdio: 'inherit', windowsHide: true});
    if (await verifyInputs() !== before) throw new Error('snapshot_build_source_changed');
    const bytes = await fs.readFile(executable);
    return [[snapshotExecutable, bytes], ['native/sqlite-snapshot-manifest.json', Buffer.from(JSON.stringify({
      format: 'leafseamer-sqlite-snapshot-build/1', platform: process.platform, arch: process.arch,
      compiler: version, sqlite_sources: inputs, source_sha256: before, binary_sha256: hash(bytes)
    }, null, 2) + '\n')]];
  } finally {
    for (const filename of [executable, ...(windows ? [path.join(directory, 'leafseamer_sqlite_snapshot.pdb')] : [])]) {
      await fs.unlink(filename).catch(error => { if (error.code !== 'ENOENT') throw error; });
    }
    await fs.rmdir(directory);
  }
}
