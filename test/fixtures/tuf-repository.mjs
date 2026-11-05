import crypto from 'node:crypto';
import {Metadata, MetadataKind, Signature} from '@tufjs/models';
import tuf from '../../dist/vendor/tuf-js/dist/index.js';
export const rawHash = value => 'sha256:' + crypto.createHash('sha256').update(value).digest('hex');
export const fixedTime = Date.parse('2020-01-01T00:00:00Z');
export function repository() {
  const keys = new Map();
  for (const id of ['r1', 'r2', 'r3', 'r4', 'r5', 'r6', 't1', 't2', 't3', 's1', 's2', 'z1', 'z2']) {
    const pair = crypto.generateKeyPairSync('ed25519');
    keys.set(id, {...pair, json: {keytype: 'ed25519', scheme: 'ed25519', keyval: {public: pair.publicKey.export({format: 'der', type: 'spki'}).subarray(-32).toString('hex')}}});
  }
  function sign(signed, ids) {
    const metadata = Metadata.fromJSON(MetadataKind[signed._type[0].toUpperCase() + signed._type.slice(1)], {signed, signatures: []});
    for (const id of ids) metadata.sign(bytes => new Signature({keyID: id, sig: crypto.sign(null, bytes, keys.get(id).privateKey).toString('hex')}), true);
    return Buffer.from(JSON.stringify(metadata.toJSON()));
  }
  const base = (_type, version) => ({_type, version, spec_version: '1.0.31', expires: '2021-01-01T00:00:00Z'});
  function root(version = 1, online = '1', signerIds = ['r1', 'r2'], rootIds = ['r1','r2','r3']) {
    const roles = {root: {keyids: rootIds, threshold: 2}, targets: {keyids: ['t1','t2','t3'], threshold: 2},
      snapshot: {keyids: ['s' + online], threshold: 1}, timestamp: {keyids: ['z' + online], threshold: 1}};
    return sign({...base('root', version), consistent_snapshot: true, keys: Object.fromEntries([...keys].map(([id, key]) => [id, key.json])), roles}, signerIds);
  }
  const ref = (bytes, version) => ({version, length: bytes.length, hashes: {sha256: rawHash(bytes).slice(7)}});
  function current(version = 1, online = '1', signerIds = ['t1','t2'], target = Buffer.from('synthetic payload'), custom = new Map()) {
    const payloads = target instanceof Map ? target : new Map([['release.zip', target]]);
    const targets = sign({...base('targets', version), targets: Object.fromEntries([...payloads].map(([name, bytes]) => [name, {...ref(bytes, version), custom: custom.get(name) ?? {channel: 'synthetic'}}]))}, signerIds);
    const snapshot = sign({...base('snapshot', version), meta: {'targets.json': ref(targets, version)}}, ['s' + online]);
    const timestamp = sign({...base('timestamp', version), meta: {'snapshot.json': ref(snapshot, version)}}, ['z' + online]);
    return new Map([['timestamp.json', timestamp], [`${version}.snapshot.json`, snapshot], [`${version}.targets.json`, targets]]);
  }
  function fetcher(files, before = () => {}) {
    return {async downloadBytes(url, maxLength) {
      const name = decodeURIComponent(new URL(url).pathname.split('/').at(-1)); before(name);
      const bytes = files.get(name); if (!bytes) throw new tuf.DownloadHTTPError('Synthetic not found', 404);
      if (bytes.length > maxLength) throw new Error('length'); return Buffer.from(bytes);
    }};
  }
  return {root, current, sign, base, fetcher};
}
