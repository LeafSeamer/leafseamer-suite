import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
export async function buildTuf() {
  const upstream = path.join(root, 'node_modules/tuf-js');
  const lock = JSON.parse(await fs.readFile(path.join(root, 'tuf-inputs.json'), 'utf8'));
  const files = new Map();
  for (const [name, expected] of Object.entries(lock.files)) {
    if (!/^[A-Za-z0-9/_.-]+$/.test(name) || name.split('/').includes('..')) throw new Error('tuf_input_path');
    const bytes = await fs.readFile(path.join(upstream, name));
    if (hash(bytes) !== expected) throw new Error('tuf_input_drift:' + name);
    files.set(name, bytes);
  }
  const replace = (file, before, after) => {
    const text = files.get(file).toString('utf8');
    if (text.split(before).length !== 2) throw new Error('tuf_patch_preimage:' + file);
    files.set(file, Buffer.from(text.replace(before, after)));
  };
  replace('dist/store.js', 'constructor(rootData) {', 'constructor(rootData, fixedReferenceTime) {');
  replace('dist/store.js', 'this.referenceTime = new Date();', `if (fixedReferenceTime !== undefined && (!Number.isSafeInteger(fixedReferenceTime) || Math.abs(fixedReferenceTime) > 8640000000000000)) {
            throw new error_1.RuntimeError('Invalid fixed reference time');
        }
        this.referenceTime = fixedReferenceTime === undefined ? new Date() : new Date(fixedReferenceTime);`);
  replace('dist/store.js', '    get root() {', `    checkFinalRoot() {
        if (this.root.signed.isExpired(this.referenceTime)) throw new error_1.ExpiredMetadataError('Final root.json is expired');
    }
    get root() {`);
  replace('dist/store.d.ts', 'constructor(rootData: Buffer);', 'constructor(rootData: Buffer, fixedReferenceTime?: number);\n    checkFinalRoot(): void;');
  replace('dist/updater.js', '    constructor(options) {', `    metadataStorage;
    storageFailed = false;
    currentRootBytes;
    constructor(options) {`);
  replace('dist/updater.js', '        this.dir = metadataDir;', `        this.metadataStorage = options.metadataStorage;
        if (this.metadataStorage && (options.forceCache || !Number.isSafeInteger(options.fixedReferenceTime))) {
            throw new error_1.ValueError('Storage adapter requires a fixed reference time and remote refresh');
        }
        this.dir = metadataDir;`);
  replace('dist/updater.js', '        this.trustedSet = new store_1.TrustedMetadataStore(data);', `        this.currentRootBytes = Buffer.from(data);
        this.trustedSet = new store_1.TrustedMetadataStore(data, options.fixedReferenceTime);`);
  replace('dist/updater.js', `                    retry: this.config.fetchRetries ?? this.config.fetchRetry,
                });`, `                    retry: this.config.fetchRetries ?? this.config.fetchRetry,
                });
        if (this.metadataStorage) {
            const delegate = this.fetcher;
            this.fetcher = {
                downloadBytes: (...args) => { this.assertStorage(); return delegate.downloadBytes(...args); },
                downloadFile: (...args) => { this.assertStorage(); return delegate.downloadFile(...args); }
            };
        }`);
  for (const method of ['refresh()', 'getTargetInfo(targetPath)', 'downloadTarget(targetInfo, filePath, targetBaseUrl)', 'findCachedTarget(targetInfo, filePath)']) {
    replace('dist/updater.js', `    async ${method} {`, `    async ${method} {\n        this.assertStorage();`);
  }
  replace('dist/updater.js', '    loadLocalMetadata(fileName) {', `    assertStorage() {
        if (this.storageFailed) throw new error_1.PersistError('Metadata storage unavailable; discard this updater');
    }
    callStorage(method, ...args) {
        this.assertStorage();
        try {
            const result = this.metadataStorage[method](...args);
            if (result && typeof result.then === 'function') throw new Error('Metadata storage must commit synchronously');
            return result;
        } catch (error) {
            this.storageFailed = true;
            throw new error_1.PersistError('Metadata storage failed; discard this updater', {cause: error});
        }
    }
    loadLocalMetadata(fileName) {
        this.assertStorage();
        if (this.metadataStorage) {
            const bytes = this.callStorage('loadTrusted', fileName);
            if (bytes === null) throw new error_1.RuntimeError('Trusted metadata absent');
            if (!Buffer.isBuffer(bytes)) { this.storageFailed = true; this.assertStorage(); }
            return Buffer.from(bytes);
        }`);
  replace('dist/updater.js', `                this.trustedSet.updateRoot(bytesData);
                // Client workflow 5.3.8: persist root metadata file
                this.persistMetadata(models_1.MetadataKind.Root, bytesData);`, `                const previousRoot = this.trustedSet.root;
                const acceptedRoot = this.trustedSet.updateRoot(bytesData);
                // Preserve every verified transition, including A -> B -> A across restarts.
                const onlineKeys = (root, role) => root.signed.roles[role].keyIDs.slice().sort().map(id => {
                    const key = root.signed.keys[id];
                    return [id, key.keyType, key.scheme, key.keyVal];
                });
                const changed = ['timestamp', 'snapshot'].some(role => !require('node:util').isDeepStrictEqual(onlineKeys(previousRoot, role), onlineKeys(acceptedRoot, role)));
                this.persistMetadata(models_1.MetadataKind.Root, bytesData, {
                    kind: 'root', previous_version: previousRoot.signed.version, version: acceptedRoot.signed.version,
                    previous_bytes: Buffer.from(this.currentRootBytes), online_keys_changed: changed
                });
                this.currentRootBytes = Buffer.from(bytesData);`);
  replace('dist/updater.js', `    // Load local and remote timestamp metadata.`, `    finalizeRootPhase() {
        if (this.metadataStorage) {
            this.trustedSet.checkFinalRoot();
            this.callStorage('finalizeRootPhase', {version: this.trustedSet.root.signed.version, bytes: Buffer.from(this.currentRootBytes)});
        }
    }
    // Load local and remote timestamp metadata.`);
  replace('dist/updater.js', `    async loadTimestamp({ checkRemote } = { checkRemote: true }) {`, `    async loadTimestamp({ checkRemote } = { checkRemote: true }) {
        this.finalizeRootPhase();`);
  replace('dist/updater.js', '    persistMetadata(metaDataName, bytesData) {', `    persistMetadata(metaDataName, bytesData, transition = {kind: 'metadata'}) {
        this.assertStorage();
        if (this.metadataStorage) {
            this.callStorage('persistVerified', metaDataName, Buffer.from(bytesData), transition);
            return;
        }`);
  replace('dist/updater.d.ts', 'export interface UpdaterOptions {', `export interface MetadataStorage {
    loadTrusted(role: string): Buffer | null;
    persistVerified(role: string, bytes: Buffer, transition: {kind: 'metadata'} | {kind: 'root'; previous_version: number; version: number; previous_bytes: Buffer; online_keys_changed: boolean}): undefined;
    finalizeRootPhase(root: {version: number; bytes: Buffer}): undefined;
}
export interface UpdaterOptions {
    fixedReferenceTime?: number;
    metadataStorage?: MetadataStorage;`);
  replace('dist/index.d.ts', "export type { UpdaterOptions } from './updater';", "export type { UpdaterOptions, MetadataStorage } from './updater';");
  replace('dist/index.js', 'exports.Updater = exports.BaseFetcher = exports.TargetFile = void 0;', 'exports.DownloadHTTPError = require("./error").DownloadHTTPError;\nexports.Updater = exports.BaseFetcher = exports.TargetFile = void 0;');
  files.set('dist/index.d.ts', Buffer.concat([files.get('dist/index.d.ts'), Buffer.from("export { DownloadHTTPError } from './error';\n")]));
  const metadata = JSON.parse(files.get('package.json'));
  if (metadata.version !== '6.0.0') throw new Error('tuf_version');
  metadata.version = '6.0.0-leafseamer.1'; metadata.private = true;
  files.set('package.json', Buffer.from(JSON.stringify(metadata, null, 2) + '\n'));
  files.set('leafseamer-patch.json', Buffer.from(JSON.stringify({format: 'leafseamer-tuf-patch/1',
    upstream: lock.upstream, patch_sha256: hash(await fs.readFile(fileURLToPath(import.meta.url))),
    inputs: lock.files, outputs: Object.fromEntries([...files].map(([name, bytes]) => [name, hash(bytes)]))}, null, 2) + '\n'));
  return [...files].map(([name, bytes]) => ['vendor/tuf-js/' + name, bytes]);
}
