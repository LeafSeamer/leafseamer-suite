import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {crc32} from 'node:zlib';
import {once} from 'node:events';
import {Readable} from 'node:stream';
import yauzl from 'yauzl';
import {decodeArtifactDocument, artifactImportSelection} from './sdk/artifact-import.mjs';
import {digest, InstallationError, requireValue as need} from './import-input.mjs';

const fail = reason => { throw new InstallationError(reason); };
const signature = {end: 0x06054b50, locator: 0x07064b50, end64: 0x06064b50, descriptor: 0x08074b50};
function number64(bytes, offset) {
  const n = bytes.readBigUInt64LE(offset); need(n <= BigInt(Number.MAX_SAFE_INTEGER), 'archive_integer'); return Number(n);
}
function portable(name, directory = false) {
  const value = directory ? name.slice(0, -1) : name;
  need(value.length > 0 && value.length <= 240 && value.split('/').every(part => /^[A-Za-z0-9_.-]+$/.test(part) &&
    part !== '.' && part !== '..' && !part.endsWith('.') && !/^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(part.split('.')[0])), 'archive_path');
  return value;
}
function extraFields(raw, name) {
  const parsed = yauzl.parseExtraFields(raw), seen = new Set();
  for (const field of parsed) {
    need(!seen.has(field.id) && [1, 10, 0x5455, 0x7875, 0x7075, 0x6375].includes(field.id), 'archive_extra_field'); seen.add(field.id);
    if (field.id === 0x7075) need(field.data.length >= 5 && field.data[0] === 1 && field.data.readUInt32LE(1) === crc32(name) &&
      field.data.subarray(5).equals(name), 'archive_unicode_path');
  }
  return parsed;
}
function manifestClosure(manifest, inventory, platform) {
  need(manifest.inventory_digest === digest(inventory) && manifest.platforms.includes(platform), 'archive_manifest_binding');
  const byId = new Map(inventory.files.map(file => [file.file_id, file]));
  const has = (id, role) => byId.get(id)?.role === role;
  need(has(manifest.dependency_lock_file_id, 'dependency_lock') && has(manifest.configuration_schema_file_id, 'schema') &&
    manifest.license_file_ids.every(id => has(id, 'license')) && manifest.capability_template_file_ids.every(id => has(id, 'schema')), 'archive_file_role');
  const entryIds = new Set();
  for (const entry of manifest.entrypoints) {
    need(!entryIds.has(entry.entry_id), 'archive_entry_identity'); entryIds.add(entry.entry_id);
    const [role, loader] = {worker: ['module', 'node_module'], helper: ['native_helper', 'native_binary'], panel: ['panel', 'static_document']}[entry.kind];
    need(has(entry.file_id, role) && entry.loader === loader && (entry.kind === 'panel' ? entry.io_policy_file_id === null : has(entry.io_policy_file_id, 'policy')), 'archive_entry_role');
  }
  need(inventory.files.every(file => file.executable === (file.role === 'native_helper')), 'archive_executable');
  const roles = new Map();
  for (const role of manifest.roles) {
    need(!roles.has(role.role_id) && role.minimum <= role.maximum, 'archive_role_declaration'); roles.set(role.role_id, role);
  }
  let previous = ''; const usedRoles = new Set(), templates = new Map(manifest.permission_templates.map(item => [item.request_id, item]));
  const take = (id, kind) => { need(roles.get(id)?.kind === kind, 'archive_role_reference'); usedRoles.add(id); };
  for (const template of manifest.permission_templates) {
    need(template.request_id > previous, 'archive_template_order'); previous = template.request_id;
    if (template.kind === 'helper_artifact') need(has(template.scope.helper_file_id, 'native_helper'), 'archive_helper_file');
    for (const field of ['action_ids', 'trigger_ids', 'method_ids', 'object_roles', 'frame_classes']) if (field in template.scope)
      need(template.scope[field].every((id, i, ids) => i === 0 || ids[i - 1] < id), 'archive_template_order');
    const scope = template.scope;
    const fields = {
      device_scope: {device_role: 'device'}, data_scope: {data_role: 'data_object'},
      network_endpoint: {endpoint_role: 'endpoint', protocol_profile_role: 'protocol_profile'},
      secret_role: {secret_role: 'secret_role', device_role: 'device', source_role: 'source'},
      filesystem_root_role: {filesystem_role: 'filesystem_role'},
      helper_artifact: {helper_role: 'helper_artifact', launch_policy_role: 'validation_policy'},
      protocol_io: {protocol_profile_role: 'protocol_profile'}, panel_method: {}
    }[template.kind];
    for (const [field, kind] of Object.entries(fields)) if (scope[field] !== null) take(scope[field], kind);
    if (template.kind === 'device_scope') need(scope.action_ids.length + scope.trigger_ids.length > 0, 'archive_empty_scope');
    if (template.kind === 'network_endpoint') need(scope.min_port <= scope.max_port, 'archive_endpoint_range');
    if (template.kind === 'secret_role') need(scope.device_role !== null || scope.source_role !== null, 'archive_empty_scope');
    if (template.kind === 'protocol_io') need(templates.get(scope.endpoint_request_id)?.kind === 'network_endpoint', 'archive_endpoint_reference');
    if (template.kind === 'panel_method') for (const id of scope.object_roles) {
      const kind = roles.get(id)?.kind; need(['device', 'data_object', 'run'].includes(kind), 'archive_role_reference'); take(id, kind);
    }
  }
  need(usedRoles.size === roles.size, 'archive_unused_role');
}

// 使用yauzl公开的随机读取接口；ZIP对象关闭不接管本函数持有的FD。
class ArchiveReader extends yauzl.RandomAccessReader {
  constructor(handle) { super(); this.handle = handle; }
  _readStreamForRange(start, end) {
    const handle = this.handle;
    return Readable.from((async function* () {
      let offset = start;
      while (offset < end) {
        const buffer = Buffer.alloc(Math.min(65536, end - offset));
        const {bytesRead} = await handle.read(buffer, 0, buffer.length, offset);
        need(bytesRead > 0, 'archive_truncated'); offset += bytesRead; yield buffer.subarray(0, bytesRead);
      }
    })(), {objectMode: false});
  }
}

export async function verifyArchive(filename, expected, outputDirectory, {platform = process.platform === 'win32' ? 'windows-x64' : 'linux-x64', checkCurrent = () => {}} = {}) {
  need(['windows-x64', 'linux-x64'].includes(platform) && process.arch === 'x64', 'archive_platform');
  need(typeof expected.package_bytes === 'string' && /^(0|[1-9][0-9]{0,19})$/.test(expected.package_bytes) &&
    BigInt(expected.package_bytes) > 0n && BigInt(expected.package_bytes) <= 536870912n, 'archive_capacity');
  need(typeof outputDirectory === 'string' && path.isAbsolute(outputDirectory), 'archive_output');
  const start = performance.now(); let fd, zip;
  const current = () => { need(performance.now() - start < 600000, 'archive_timeout'); checkCurrent(); };
  const size = Number(expected.package_bytes);
  async function readAt(offset, length) {
    current(); need(Number.isSafeInteger(offset) && Number.isSafeInteger(length) && offset >= 0 && length >= 0 && offset + length <= size, 'archive_bounds');
    const buffer = Buffer.alloc(length); let used = 0;
    while (used < length) { const result = await fd.read(buffer, used, length - used, offset + used); need(result.bytesRead > 0, 'archive_truncated'); used += result.bytesRead; current(); }
    return buffer;
  }
  async function packageHash() {
    const hash = crypto.createHash('sha256');
    for (let offset = 0; offset < size; offset += 65536) hash.update(await readAt(offset, Math.min(65536, size - offset)));
    return 'sha256:' + hash.digest('hex');
  }
  async function footer() {
    const tail = await readAt(Math.max(0, size - 65557), Math.min(size, 65557)); let offset = -1;
    for (let n = tail.length - 22; n >= 0; --n) if (tail.readUInt32LE(n) === signature.end && n + 22 + tail.readUInt16LE(n + 20) === tail.length) { offset = n; break; }
    need(offset >= 0, 'archive_footer'); const end = size - tail.length + offset, eocd = tail.subarray(offset);
    need(eocd.readUInt16LE(4) === 0 && eocd.readUInt16LE(6) === 0, 'archive_multidisk');
    let count = eocd.readUInt16LE(10), centralSize = eocd.readUInt32LE(12), centralOffset = eocd.readUInt32LE(16), centralEnd = end;
    need(eocd.readUInt16LE(8) === count, 'archive_multidisk');
    const locator = end >= 20 ? await readAt(end - 20, 20) : null;
    if (locator?.readUInt32LE(0) === signature.locator) {
      need(locator.readUInt32LE(4) === 0 && locator.readUInt32LE(16) === 1, 'archive_multidisk');
      centralEnd = number64(locator, 8); const record = await readAt(centralEnd, 56), length = number64(record, 4);
      need(record.readUInt32LE(0) === signature.end64 && length >= 44 && centralEnd + 12 + length === end - 20 &&
        record.readUInt32LE(16) === 0 && record.readUInt32LE(20) === 0, 'archive_footer');
      const count64 = number64(record, 32), bytes64 = number64(record, 40), offset64 = number64(record, 48);
      need(number64(record, 24) === count64 && (count === 65535 || count === count64) &&
        (centralSize === 0xffffffff || centralSize === bytes64) && (centralOffset === 0xffffffff || centralOffset === offset64), 'archive_footer');
      count = count64; centralSize = bytes64; centralOffset = offset64;
    }
    need(count >= 3 && count <= 65536 * 121 + 2 && centralSize >= count * 46 && centralOffset + centralSize === centralEnd, 'archive_central_bounds');
    return {count, centralSize, centralOffset};
  }
  async function openZip() {
    zip = await yauzl.fromRandomAccessReaderPromise(new ArchiveReader(fd), size, {autoClose: false, decodeStrings: false, validateEntrySizes: true, strictFileNames: true});
    // 保留错误监听直到close；各公开迭代/流API负责传播具体失败。
    zip.on('error', () => {}); return zip;
  }
  async function closeZip() { if (zip) { const currentZip = zip; zip = undefined; const closed = once(currentZip, 'close'); currentZip.close(); await closed; } }
  function entryName(entry) {
    need(entry.fileName.every(byte => byte < 128), 'archive_path'); const name = entry.fileName.toString('ascii'), directory = name.endsWith('/'); portable(name, directory);
    const type = (entry.externalFileAttributes >>> 16) & 0xf000;
    need((type === 0 || type === (directory ? 0x4000 : 0x8000)) && !(entry.externalFileAttributes & 0x400) &&
      (!(entry.externalFileAttributes & 0x10) || directory), 'archive_file_type');
    need([0, 8].includes(entry.compressionMethod) && (entry.generalPurposeBitFlag & ~0x080e) === 0 &&
      (entry.compressionMethod === 8 || !(entry.generalPurposeBitFlag & 6)) && entry.versionNeededToExtract >= (entry.compressionMethod === 8 ? 20 : 10) &&
      entry.versionNeededToExtract <= 45, 'archive_compression');
    need(Number.isSafeInteger(entry.uncompressedSize) && Number.isSafeInteger(entry.compressedSize) && entry.uncompressedSize >= 0 &&
      entry.compressedSize >= 0 && entry.uncompressedSize <= 268435456 && entry.compressedSize <= size &&
      entry.uncompressedSize <= entry.compressedSize * 100, 'archive_capacity');
    if (directory) need(entry.uncompressedSize === 0, 'archive_directory_data');
    extraFields(entry.extraFieldRaw, entry.fileName); return {name, directory};
  }
  async function bytes(entry, limit, sink) {
    need(entry.uncompressedSize <= limit, 'archive_capacity'); const stream = await zip.openReadStreamPromise(entry); let count = 0, crc = 0;
    const hash = crypto.createHash('sha256'), buffers = [];
    try {
      for await (const chunk of stream) {
        current(); count += chunk.length; need(count <= limit, 'archive_capacity'); crc = crc32(chunk, crc); hash.update(chunk);
        if (sink) {
          let offset = 0;
          while (offset < chunk.length) { const written = await sink.write(chunk, offset, chunk.length - offset); need(written.bytesWritten > 0, 'archive_write'); offset += written.bytesWritten; }
        } else buffers.push(chunk);
      }
      need(count === entry.uncompressedSize && crc === entry.crc32, 'archive_crc');
      return {bytes: sink ? null : Buffer.concat(buffers), size: count, digest: 'sha256:' + hash.digest('hex')};
    } finally { stream.destroy(); }
  }
  async function localRange(entry, centralRaw, bounds) {
    const local = await zip.readLocalFileHeaderPromise(entry);
    need(local.fileName.equals(entry.fileName) && ['versionNeededToExtract', 'generalPurposeBitFlag', 'compressionMethod', 'lastModFileDate', 'lastModFileTime'].every(k => local[k] === entry[k]), 'archive_local_mismatch');
    const extras = extraFields(local.extraField, local.fileName), zip64 = extras.find(field => field.id === 1)?.data;
    let localSize = local.uncompressedSize, localCompressed = local.compressedSize, index = 0;
    for (const field of ['size', 'compressed']) if ((field === 'size' ? localSize : localCompressed) === 0xffffffff) {
      need(zip64 && index + 8 <= zip64.length, 'archive_zip64'); const value = number64(zip64, index); index += 8;
      if (field === 'size') localSize = value; else localCompressed = value;
    }
    let end = local.fileDataStart + entry.compressedSize;
    need(entry.relativeOffsetOfLocalHeader >= 0 && end <= bounds.centralOffset, 'archive_overlap');
    if (!(entry.generalPurposeBitFlag & 8)) need(local.crc32 === entry.crc32 && localSize === entry.uncompressedSize && localCompressed === entry.compressedSize, 'archive_local_mismatch');
    else {
      need([0, entry.crc32].includes(local.crc32) && [0, entry.uncompressedSize].includes(localSize) && [0, entry.compressedSize].includes(localCompressed), 'archive_local_mismatch');
      const large = local.compressedSize === 0xffffffff || local.uncompressedSize === 0xffffffff || centralRaw.readUInt32LE(20) === 0xffffffff || centralRaw.readUInt32LE(24) === 0xffffffff;
      const length = large ? 20 : 12, data = await readAt(end, Math.min(length + 4, bounds.centralOffset - end)); const matches = [];
      for (const shift of [0, 4]) if (data.length >= shift + length && (shift === 0 || data.readUInt32LE(0) === signature.descriptor)) {
        const compressed = large ? data.readBigUInt64LE(shift + 4) : BigInt(data.readUInt32LE(shift + 4));
        const uncompressed = large ? data.readBigUInt64LE(shift + 12) : BigInt(data.readUInt32LE(shift + 8));
        if (data.readUInt32LE(shift) === entry.crc32 && compressed === BigInt(entry.compressedSize) && uncompressed === BigInt(entry.uncompressedSize)) matches.push(length + shift);
      }
      need(matches.length === 1, 'archive_descriptor'); end += matches[0];
    }
    return {start: entry.relativeOffsetOfLocalHeader, end};
  }
  try {
    fd = await fsp.open(filename, 'r');
    const stat = await fd.stat(); need(stat.isFile() && stat.nlink === 1 && stat.size === size, 'archive_package_size');
    need(await packageHash() === expected.package_digest, 'archive_package_digest'); const bounds = await footer(), control = new Map();
    await openZip();
    for await (const entry of zip.eachEntry()) {
      current(); const {name, directory} = entryName(entry);
      if (!directory && ['extension.json', 'files.json'].includes(name)) {
        need(!control.has(name), 'archive_duplicate'); control.set(name, (await bytes(entry, 4194304)).bytes);
      }
    }
    await closeZip(); need(control.size === 2, 'archive_control_files');
    const manifest = await decodeArtifactDocument(control.get('extension.json'), 'Manifest');
    const inventory = await decodeArtifactDocument(control.get('files.json'), 'FileInventory');
    need(digest(manifest) === expected.expected_manifest_digest, 'archive_manifest_digest'); manifestClosure(manifest, inventory, platform);
    const files = new Map(inventory.files.map(file => [file.path, file])), directories = new Set();
    for (const file of files.keys()) { const parts = file.split('/'); for (let n = 1; n < parts.length; ++n) directories.add(parts.slice(0, n).join('/') + '/'); }
    need(bounds.count <= files.size + directories.size + 2, 'archive_entry_count');
    await fsp.mkdir(outputDirectory, {mode: 0o700});
    await openZip(); const seen = new Set(), ranges = []; let centralBytes = 0, count = 0, total = 0;
    for await (const entry of zip.eachEntry()) {
      current(); const {name, directory} = entryName(entry);
      need(!seen.has(name.toLowerCase()), 'archive_duplicate'); seen.add(name.toLowerCase());
      need(directory ? directories.has(name) : files.has(name) || control.has(name), 'archive_inventory');
      const raw = await readAt(bounds.centralOffset + centralBytes, 46); need(raw.readUInt16LE(34) === 0, 'archive_multidisk');
      centralBytes += 46 + entry.fileNameLength + entry.extraFieldLength + entry.fileCommentLength; ++count;
      need(centralBytes <= bounds.centralSize && count <= bounds.count, 'archive_central_bounds');
      ranges.push(await localRange(entry, raw, bounds));
      if (directory) { await bytes(entry, 0); continue; }
      if (control.has(name)) { need((await bytes(entry, 4194304)).bytes.equals(control.get(name)), 'archive_control_changed'); continue; }
      const declared = files.get(name); need(entry.uncompressedSize === Number(declared.size_bytes), 'archive_inventory_size');
      const target = path.join(outputDirectory, ...name.split('/')); await fsp.mkdir(path.dirname(target), {recursive: true, mode: 0o700});
      const output = await fsp.open(target, 'wx', 0o600);
      try { const actual = await bytes(entry, Number(declared.size_bytes), output); need(actual.digest === declared.digest, 'archive_file_digest'); total += actual.size; await output.sync(); }
      finally { await output.close(); }
    }
    await closeZip(); need(count === bounds.count && centralBytes === bounds.centralSize && [...files.keys()].every(name => seen.has(name.toLowerCase())), 'archive_inventory');
    ranges.sort((a, b) => a.start - b.start); let end = 0;
    for (const range of ranges) { need(range.start === end && range.end >= range.start, 'archive_overlap'); end = range.end; }
    need(end === bounds.centralOffset, 'archive_unlisted_data');
    need(await packageHash() === expected.package_digest, 'archive_package_changed'); current();
    return {format: 'leafseamer-archive-validation/1', package_digest: expected.package_digest, package_bytes: expected.package_bytes,
      manifest_digest: digest(manifest), artifact_set_digest: digest(inventory), file_inventory_digest: digest(inventory),
      dependency_lock_digest: inventory.files.find(file => file.file_id === manifest.dependency_lock_file_id).digest,
      platform, file_count: files.size, payload_bytes: String(total), decoder_selection: artifactImportSelection,
      archive_reader: 'yauzl/3.4.0', manifest, inventory};
  } catch (error) {
    if (error instanceof InstallationError) throw error;
    if (['EACCES', 'EPERM', 'EIO', 'ENOSPC', 'EROFS', 'EMFILE', 'ENFILE', 'EDQUOT', 'ENOENT', 'EEXIST'].includes(error?.code)) fail('archive_storage_unknown');
    fail(error?.stage ? 'archive_document' : 'archive_invalid');
  } finally { try { await closeZip(); } finally { await fd?.close(); } }
}
