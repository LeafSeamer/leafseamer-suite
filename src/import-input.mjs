import crypto from 'node:crypto';
import canonicalize from 'canonicalize';

export class InstallationError extends Error {
  constructor(code, options) { super(code, options); this.name = 'InstallationError'; this.code = code; }
}
export const requireValue = (ok, code) => { if (!ok) throw new InstallationError(code); };
export const canonical = value => {
  const text = canonicalize(value); requireValue(typeof text === 'string', 'import_invalid_request'); return text;
};
export const digest = value => 'sha256:' + crypto.createHash('sha256').update(canonical(value)).digest('hex');
const id = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value) && value.trim() === value;
const u20 = value => typeof value === 'string' && /^(0|[1-9][0-9]{0,19})$/.test(value) && value.trim() === value;
const hash = value => typeof value === 'string' && value.length === 71 && /^sha256:[0-9a-f]{64}$/.test(value);
function fields(value, keys) {
  requireValue(value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === keys.sort().join(','), 'import_invalid_request');
}
export function importIdentity(value) {
  fields(value, ['host_installation_id', 'client_registration_id', 'import_request_id']);
  requireValue(Object.values(value).every(id), 'import_invalid_identity');
  return {host_installation_id: value.host_installation_id, client_registration_id: value.client_registration_id, import_request_id: value.import_request_id};
}
function reference(value, kind) {
  fields(value, ['kind', 'authority_service_id', 'database_instance_id', 'object_id', 'revision', 'digest']);
  requireValue(value.kind === kind && ['authority_service_id', 'database_instance_id', 'object_id'].every(k => id(value[k])) &&
    u20(value.revision) && hash(value.digest), 'import_invalid_reference');
}
// 可信安装代码的内部对象入口；网络原始字节须先经独立导入协议的严格解码和对端授权。
export function importRequest(input) {
  fields(input, ['identity', 'target_authority_service_id', 'source_attachment_id', 'package_digest', 'package_bytes',
    'expected_manifest_digest', 'host_trust_epoch', 'release_authorization_ref', 'validation_policy_ref']);
  importIdentity(input.identity);
  requireValue(id(input.target_authority_service_id) && id(input.source_attachment_id) && hash(input.package_digest) &&
    hash(input.expected_manifest_digest) && u20(input.package_bytes) && u20(input.host_trust_epoch), 'import_invalid_request');
  requireValue(BigInt(input.package_bytes) > 0n && BigInt(input.package_bytes) <= 536870912n, 'import_capacity');
  reference(input.release_authorization_ref, 'release_authorization'); reference(input.validation_policy_ref, 'validation_policy');
  const {source_attachment_id, ...intent} = input;
  const text = canonical(intent); requireValue(Buffer.byteLength(text) <= 65536, 'import_capacity');
  return {intent: JSON.parse(text), text, digest: digest(intent)};
}
