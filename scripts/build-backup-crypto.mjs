import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const source = fileURLToPath(new URL('../native/backup-crypto/', import.meta.url));
const version = 'go1.27.2';
const sourceFiles = ['main.go', 'go.mod', 'go.sum'];
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const sourceHashes = async () => Object.fromEntries(await Promise.all(sourceFiles.map(async name =>
  [name, sha256(await fs.readFile(path.join(source, name)))])));

export const backupCryptoExecutable = 'native/leafseamer_backup_crypto' + (process.platform === 'win32' ? '.exe' : '');

export async function buildBackupCrypto() {
  const goos = {linux: 'linux', win32: 'windows'}[process.platform];
  const goarch = {x64: 'amd64', arm64: 'arm64'}[process.arch];
  if (!goos || !goarch) throw new Error('backup_crypto_build_platform');
  const go = process.env.LEAFSEAMER_BACKUP_GO ?? 'go';
  const env = {...process.env, GOENV: 'off', GOFLAGS: '', GOWORK: 'off', GOTOOLCHAIN: 'local',
    GOEXPERIMENT: '', CGO_ENABLED: '0', GOOS: goos, GOARCH: goarch, GOAMD64: 'v1', GOARM64: 'v8.0'};
  const run = args => execFileSync(go, args, {cwd: source, env, encoding: 'utf8', windowsHide: true}).trim();
  const goVersion = run(['env', 'GOVERSION']);
  if (goVersion !== version) throw new Error('backup_crypto_build_toolchain');
  const before = await sourceHashes();
  const staging = await fs.mkdtemp(path.join(os.tmpdir(), 'leafseamer-backup-crypto-'));
  try {
    const executable = path.join(staging, path.basename(backupCryptoExecutable));
    run(['build', '-mod=readonly', '-trimpath', '-buildvcs=false', '-o', executable, '.']);
    run(['mod', 'verify']);
    const modules = run(['list', '-mod=readonly', '-deps', '-f',
      '{{with .Module}}{{if not .Main}}{{.Path}}\t{{.Version}}\t{{.Dir}}{{end}}{{end}}', '.']);
    const licenses = new Map([
      ['go', {version: goVersion, directory: run(['env', 'GOROOT'])}],
    ]);
    for (const line of modules.split(/\r?\n/).filter(Boolean)) {
      const [name, resolved, directory] = line.split('\t');
      licenses.set(name, {version: resolved, directory});
    }
    const files = [];
    for (const [name, {directory}] of licenses) {
      for (const filename of ['LICENSE', 'PATENTS']) {
        const bytes = await fs.readFile(path.join(directory, filename)).catch(error => {
          if (filename !== 'PATENTS' || error.code !== 'ENOENT') throw error;
        });
        if (bytes) files.push(['native/backup-crypto-licenses/' + name + '/' + filename, bytes]);
      }
    }
    if (JSON.stringify(before) !== JSON.stringify(await sourceHashes())) throw new Error('backup_crypto_build_source_changed');
    const bytes = await fs.readFile(executable);
    return [...files, [backupCryptoExecutable, bytes], ['native/backup-crypto-manifest.json', Buffer.from(JSON.stringify({
      format: 'leafseamer-backup-crypto-build/1', platform: process.platform, arch: process.arch,
      go: goVersion, sources: before, binary_sha256: sha256(bytes),
      modules: Object.fromEntries([...licenses].map(([name, entry]) => [name, entry.version])),
      licenses: Object.fromEntries(files.map(([name, bytes]) => [name, sha256(bytes)])),
    }, null, 2) + '\n')]];
  } finally {
    // Only this uniquely allocated directory and its single output were created by the build.
    await fs.unlink(path.join(staging, path.basename(backupCryptoExecutable))).catch(error => {
      if (error.code !== 'ENOENT') throw error;
    });
    await fs.rmdir(staging);
  }
}
