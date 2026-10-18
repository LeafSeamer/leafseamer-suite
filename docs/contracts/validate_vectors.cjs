// 仅验证人工固定向量，不作为生产SDK的规范化实现。
const fs = require('node:fs');
const path = require('node:path');
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, 'canonical-vectors.json'), 'utf8'));
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  }
  return JSON.stringify(value);
}
for (const vector of vectors) {
  if (canonical(vector.input) !== vector.canonical) throw new Error('规范化向量不匹配：' + vector.case_id);
}
const identities = JSON.parse(fs.readFileSync(path.join(__dirname, 'identity-vectors.json'), 'utf8'));
for (const vector of identities) {
  const body = structuredClone(vector.body);
  for (const key of ['context_id', 'idempotency_key', 'correlation_id']) delete body[key];
  if (vector.operation === 'acquireControl' && body.force === undefined) body.force = false;
  if (canonical(body) !== vector.canonical) throw new Error('请求内容向量不匹配：' + vector.case_id);
}
process.stdout.write('Node 规范化固定向量通过：' + vectors.length + '\n');
