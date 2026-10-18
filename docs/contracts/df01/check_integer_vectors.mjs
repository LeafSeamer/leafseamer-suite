// 设计用参考算术；不是SDK入口解析器或产品实现，不实现JCS。
import fs from 'node:fs';
const vectors = JSON.parse(fs.readFileSync(new URL('./vectors.json', import.meta.url), 'utf8'));
for (const c of vectors.integers) {
  const signed = c.kind === 'signed_ns';
  const length = c.kind === 'revision' ? 20 : signed ? 25 : 24;
  const valid = c.text.length <= length && (signed ? /^-?(0|[1-9][0-9]*)$/ : /^(0|[1-9][0-9]*)$/).test(c.text);
  if (valid !== c.valid) throw new Error(c.id);
  if (valid && BigInt(c.text).toString() !== c.value) throw new Error(c.id);
}
for (const c of vectors.division) {
  const n = BigInt(c.n), d = BigInt(c.d);
  if (d <= 0n) throw new Error('固定用例要求正分母');
  const q = n / d, r = n % d;
  const floor = q - (r < 0n ? 1n : 0n), ceil = q + (r > 0n ? 1n : 0n);
  if (floor.toString() !== c.floor || ceil.toString() !== c.ceil) throw new Error(c.id);
}
process.stdout.write(JSON.stringify({node:process.version,integer_cases:vectors.integers.length,division_cases:vectors.division.length,jcs_library_tested:false}));
