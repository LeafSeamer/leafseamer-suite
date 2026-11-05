import crypto from 'node:crypto';
import {deflateRawSync, crc32} from 'node:zlib';
import canonicalize from 'canonicalize';
export const rawDigest = value => 'sha256:' + crypto.createHash('sha256').update(value).digest('hex');
export const digestValue = value => rawDigest(canonicalize(value));
export function artifactFixture() {
  const payload = new Map([
    ['config', {path: 'payload/config.json', role: 'schema', bytes: Buffer.from('{"type":"object"}')}],
    ['license', {path: 'LICENSE.txt', role: 'license', bytes: Buffer.from('Synthetic fixture license.')}],
    ['lock', {path: 'payload/lock.json', role: 'dependency_lock', bytes: Buffer.from('{"dependencies":[]}')}],
    ['policy', {path: 'payload/policy.json', role: 'policy', bytes: Buffer.from('{"network":false}')}],
    ['worker', {path: 'payload/main.mjs', role: 'module', bytes: Buffer.from('globalThis.archiveExecuted = true;\n')}]
  ]);
  const inventory = {inventory_version: 'extension-files/1', files: [...payload].map(([file_id, file]) => ({file_id, path: file.path,
    size_bytes: String(file.bytes.length), digest: rawDigest(file.bytes), role: file.role, executable: false}))};
  const manifest = {manifest_version: 'extension-artifact/0.1.0-draft.1', extension_id: 'extension.synthetic', extension_version: '1', kind: 'device_module',
    publisher_id: 'publisher.synthetic', source_revision: 'source.synthetic', inventory_digest: digestValue(inventory), dependency_lock_file_id: 'lock',
    license_file_ids: ['license'], capability_template_file_ids: [], configuration_schema_file_id: 'config', platforms: ['windows-x64', 'linux-x64'],
    api_versions: ['api.synthetic'], ipc_versions: ['ipc.synthetic'], required_features: [],
    entrypoints: [{entry_id: 'worker', kind: 'worker', file_id: 'worker', loader: 'node_module', io_policy_file_id: 'policy'}], roles: [], permission_templates: []};
  const entries = () => [{name: 'extension.json', bytes: Buffer.from(JSON.stringify(manifest))}, {name: 'files.json', bytes: Buffer.from(JSON.stringify(inventory))},
    {name: 'payload/', bytes: Buffer.alloc(0)}, ...[...payload.values()].map(file => ({name: file.path, bytes: file.bytes}))];
  return {manifest, inventory, payload, entries};
}
// 测试专用ZIP字节构造器，可精确变异local/central/descriptor，不执行归档内容。
export function zipFixture(entries, {deflate = false, descriptor = false, zip64 = false, reverseCentral = false} = {}) {
  const local = [], records = []; let offset = 0;
  for (const item of entries) {
    const name = Buffer.from(item.name), method = deflate && item.bytes.length ? 8 : 0, compressed = method ? deflateRawSync(item.bytes) : item.bytes;
    const crc = crc32(item.bytes), extra = zip64 ? Buffer.alloc(20) : Buffer.alloc(0);
    if (zip64) { extra.writeUInt16LE(1); extra.writeUInt16LE(16, 2); extra.writeBigUInt64LE(BigInt(item.bytes.length), 4); extra.writeBigUInt64LE(BigInt(compressed.length), 12); }
    const header = Buffer.alloc(30); header.writeUInt32LE(0x04034b50); header.writeUInt16LE(zip64 ? 45 : 20, 4);
    header.writeUInt16LE(descriptor ? 8 : 0, 6); header.writeUInt16LE(method, 8); header.writeUInt32LE(descriptor ? 0 : crc, 14);
    header.writeUInt32LE(zip64 ? 0xffffffff : descriptor ? 0 : compressed.length, 18);
    header.writeUInt32LE(zip64 ? 0xffffffff : descriptor ? 0 : item.bytes.length, 22); header.writeUInt16LE(name.length, 26); header.writeUInt16LE(extra.length, 28);
    const dd = descriptor ? Buffer.alloc(zip64 ? 24 : 16) : Buffer.alloc(0);
    if (descriptor) {
      dd.writeUInt32LE(0x08074b50); dd.writeUInt32LE(crc, 4);
      if (zip64) { dd.writeBigUInt64LE(BigInt(compressed.length), 8); dd.writeBigUInt64LE(BigInt(item.bytes.length), 16); }
      else { dd.writeUInt32LE(compressed.length, 8); dd.writeUInt32LE(item.bytes.length, 12); }
    }
    records.push({item, name, method, crc, compressed, localOffset: offset, descriptorOffset: offset + header.length + name.length + extra.length + compressed.length});
    local.push(header, name, extra, compressed, dd); offset += header.length + name.length + extra.length + compressed.length + dd.length;
  }
  const centralOffset = offset, central = [];
  for (const record of reverseCentral ? [...records].reverse() : records) {
    const {item, name, method, crc, compressed, localOffset} = record, extra = zip64 ? Buffer.alloc(28) : Buffer.alloc(0);
    if (zip64) { extra.writeUInt16LE(1); extra.writeUInt16LE(24, 2); extra.writeBigUInt64LE(BigInt(item.bytes.length), 4); extra.writeBigUInt64LE(BigInt(compressed.length), 12); extra.writeBigUInt64LE(BigInt(localOffset), 20); }
    const header = Buffer.alloc(46); header.writeUInt32LE(0x02014b50); header.writeUInt16LE(3 * 256 + (zip64 ? 45 : 20), 4);
    header.writeUInt16LE(zip64 ? 45 : 20, 6); header.writeUInt16LE(descriptor ? 8 : 0, 8); header.writeUInt16LE(method, 10);
    header.writeUInt32LE(crc, 16); header.writeUInt32LE(zip64 ? 0xffffffff : compressed.length, 20); header.writeUInt32LE(zip64 ? 0xffffffff : item.bytes.length, 24);
    header.writeUInt16LE(name.length, 28); header.writeUInt16LE(extra.length, 30);
    header.writeUInt32LE(((item.name.endsWith('/') ? 0x41c0 : 0x8180) * 65536 + (item.name.endsWith('/') ? 16 : 0)) >>> 0, 38);
    header.writeUInt32LE(zip64 ? 0xffffffff : localOffset, 42); record.centralOffset = offset; central.push(header, name, extra); offset += 46 + name.length + extra.length;
  }
  const end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(zip64 ? 65535 : records.length, 8); end.writeUInt16LE(zip64 ? 65535 : records.length, 10);
  end.writeUInt32LE(zip64 ? 0xffffffff : offset - centralOffset, 12); end.writeUInt32LE(zip64 ? 0xffffffff : centralOffset, 16);
  const footer = [];
  if (zip64) {
    const full = Buffer.alloc(56), locator = Buffer.alloc(20); full.writeUInt32LE(0x06064b50); full.writeBigUInt64LE(44n, 4);
    full.writeUInt16LE(45, 12); full.writeUInt16LE(45, 14); full.writeBigUInt64LE(BigInt(records.length), 24); full.writeBigUInt64LE(BigInt(records.length), 32);
    full.writeBigUInt64LE(BigInt(offset - centralOffset), 40); full.writeBigUInt64LE(BigInt(centralOffset), 48);
    locator.writeUInt32LE(0x07064b50); locator.writeBigUInt64LE(BigInt(offset), 8); locator.writeUInt32LE(1, 16); footer.push(full, locator);
  }
  return {bytes: Buffer.concat([...local, ...central, ...footer, end]), records, centralOffset};
}
