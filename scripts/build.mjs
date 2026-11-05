import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {buildTuf} from './build-tuf.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const names = ['installation-store.mjs', 'installation.sql', 'import-input.mjs', 'archive-verifier.mjs', 'trust-metadata.mjs', 'trust-metadata.sql', 'tuf-input.mjs', 'release-transport.mjs', 'release-authorization.mjs', 'local-peer.mjs', 'local-import.mjs', 'validation-policy.mjs'];
const files = await Promise.all(names.map(async name => [name, await fs.readFile(path.join(root, 'src', name))]));
files.push(['content-preparation.mjs',await fs.readFile(path.join(root,'src/content-preparation.mjs'))]);
for(const name of ['prepared-content.mjs','platform-qualification.mjs','installation-sealing.mjs','installation-sealing.sql','materialization.mjs'])files.push([name,await fs.readFile(path.join(root,'src',name))]);
files.push(...await buildTuf());
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
if(process.platform==='win32'){
  const location=path.join(root,'logs/installation-peer/artifacts'),bytes=await fs.readFile(path.join(location,'leafseamer_installation_peer.node'));
  const manifestBytes=await fs.readFile(path.join(location,'manifest.json')),manifest=JSON.parse(manifestBytes);
  if(manifest.binary_sha256!==hash(bytes)||manifest.source_sha256!==hash(await fs.readFile(path.join(root,'native/installation-peer.cc')))||
    manifest.inputs_sha256!==hash(await fs.readFile(path.join(root,'native-inputs.json')))||manifest.cmake_sha256!==hash(await fs.readFile(path.join(root,'native/CMakeLists.txt'))))throw new Error('peer_native_build_drift');
  for(const name of ['content-root.h','content-preparation.h'])if(manifest.local_headers?.[name]!==hash(await fs.readFile(path.join(root,'native',name))))throw new Error('peer_native_build_drift');
  files.push(['native/leafseamer_installation_peer.node',bytes],['native/installation-peer-manifest.json',manifestBytes]);
}
const sdkRoot = new URL('./', import.meta.resolve('@leafseamer/sdk'));
const sdkLock = JSON.parse(await fs.readFile(path.join(root, 'sdk-runtime.json'), 'utf8'));
const sdkManifestBytes = await fs.readFile(new URL('build-manifest.json', sdkRoot));
if (hash(sdkManifestBytes) !== sdkLock.manifest_sha256) throw new Error('sdk_manifest_drift');
const sdkManifest = JSON.parse(sdkManifestBytes);
if (JSON.stringify(sdkManifest.selection) !== JSON.stringify(sdkLock.selection)) throw new Error('sdk_selection_drift');
for (const [name, expected] of Object.entries(sdkManifest.artifacts)) {
  if (!/^[a-zA-Z0-9/_.-]+$/.test(name) || name.split('/').some(part => !part || part === '.' || part === '..')) throw new Error('sdk_artifact_path');
  const bytes = await fs.readFile(new URL(name, sdkRoot)); if (hash(bytes) !== expected) throw new Error('sdk_artifact_drift');
  files.push(['sdk/' + name, bytes]);
}
const sdkLicense = await fs.readFile(new URL('../LICENSE', sdkRoot));
if (hash(sdkLicense) !== sdkLock.license_sha256) throw new Error('sdk_license_drift');
files.push(['sdk/build-manifest.json', sdkManifestBytes], ['sdk/LICENSE', sdkLicense]);
const output = path.resolve(root, 'dist');
if (path.dirname(output) !== path.resolve(root)) throw new Error('output_path');
await fs.rm(output, {recursive: true, force: true}); await fs.mkdir(output);
for (const [name, bytes] of files) { await fs.mkdir(path.dirname(path.join(output, name)), {recursive: true}); await fs.writeFile(path.join(output, name), bytes); }
await fs.writeFile(path.join(output, 'build-manifest.json'), JSON.stringify({format: 'leafseamer-suite-build/1',
  artifacts: Object.fromEntries(files.map(([name, bytes]) => [name, crypto.createHash('sha256').update(bytes).digest('hex')]))}, null, 2) + '\n');
console.log(JSON.stringify({artifacts: files.length, runtime_ready: false}));
