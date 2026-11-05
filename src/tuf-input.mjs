import {requireValue as need} from './import-input.mjs';

// 只检查原始JSON的资源与词法边界；验签仍接收完全相同的原字节。
export function inspectMetadata(bytes) {
  need(Buffer.isBuffer(bytes) && bytes.length > 0 && bytes.length <= 4194304, 'trust_metadata_capacity');
  let text;
  try { text = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes); } catch { need(false, 'trust_metadata_utf8'); }
  let i = 0, nodes = 0;
  const ws = () => { while (i < text.length && /[\x20\t\r\n]/.test(text[i])) ++i; };
  function string() {
    need(text[i++] === '"', 'trust_metadata_json'); const start = i - 1;
    while (i < text.length) {
      const ch = text[i++];
      if (ch === '"') { try { return JSON.parse(text.slice(start, i)); } catch { need(false, 'trust_metadata_json'); } }
      if (ch === '\\') ++i;
    }
    need(false, 'trust_metadata_json');
  }
  function value(depth = 0) {
    need(depth < 48 && ++nodes <= 262144, 'trust_metadata_capacity'); ws();
    if (text[i] === '{') {
      ++i; ws(); const keys = new Set();
      if (text[i] === '}') { ++i; return; }
      for (;;) {
        ws(); const key = string(); need(!keys.has(key) && !['__proto__', 'constructor', 'prototype'].includes(key), 'trust_metadata_key'); keys.add(key);
        ws(); need(text[i++] === ':', 'trust_metadata_json'); value(depth + 1); ws();
        const next = text[i++]; if (next === '}') return; need(next === ',', 'trust_metadata_json');
      }
    }
    if (text[i] === '[') {
      ++i; ws(); if (text[i] === ']') { ++i; return; }
      for (;;) { value(depth + 1); ws(); const next = text[i++]; if (next === ']') return; need(next === ',', 'trust_metadata_json'); }
    }
    if (text[i] === '"') { string(); return; }
    const token = /^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/.exec(text.slice(i));
    need(token, 'trust_metadata_json'); i += token[0].length;
    if (/[-0-9]/.test(token[0][0])) need(Number.isFinite(Number(token[0])), 'trust_metadata_number');
  }
  value(); ws(); need(i === text.length, 'trust_metadata_json');
  const document = JSON.parse(text), signed = document?.signed;
  need(signed && typeof signed === 'object' && ['root', 'timestamp', 'snapshot', 'targets'].includes(signed._type), 'trust_metadata_type');
  const version = n => need(Number.isSafeInteger(n) && n >= 1, 'trust_metadata_version'); version(signed.version);
  need(typeof signed.expires === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(signed.expires), 'trust_metadata_expiry');
  const instant = new Date(signed.expires);
  need(Number.isFinite(instant.getTime()) && instant.toISOString().replace('.000Z', 'Z') === signed.expires, 'trust_metadata_expiry');
  if (['timestamp', 'snapshot'].includes(signed._type)) {
    need(signed.meta && typeof signed.meta === 'object' && !Array.isArray(signed.meta), 'trust_metadata_references');
    for (const ref of Object.values(signed.meta)) {
      version(ref.version);
      need(Number.isSafeInteger(ref.length) && ref.length > 0 && ref.length <= 4194304 && typeof ref.hashes?.sha256 === 'string' && /^[0-9a-f]{64}$/.test(ref.hashes.sha256), 'trust_metadata_references');
    }
  }
  return document;
}
