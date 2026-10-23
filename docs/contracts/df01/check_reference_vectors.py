"""仅检查人工固定预期、另一语言参考JCS及精确算术，不实现生产SDK。"""
import hashlib
import json
import platform
import re
import subprocess
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator
from check_decoder_design import check as check_decoder_design

ROOT=Path(__file__).resolve().parent
v=json.loads((ROOT/'vectors.json').read_text(encoding='utf-8'))
digests={};outputs={}
for c in v['canonical']:
    expected=c['expected'].encode('utf-8')
    actual=rfc8785.dumps(json.loads(c['raw']))
    assert actual==expected,c['id']
    digests[c['id']]=hashlib.sha256(expected).hexdigest()
    outputs[c['id']]=dict(canonical_utf8_hex=expected.hex(),sha256=digests[c['id']])
for a,b in v['different_digest_pairs']:assert digests[a]!=digests[b],(a,b)
for c in v['integers']:
    signed=c['kind']=='signed_ns';length=20 if c['kind']=='revision' else 25 if signed else 24
    pattern=r'-?(0|[1-9][0-9]*)' if signed else r'(0|[1-9][0-9]*)'
    valid=len(c['text'])<=length and re.fullmatch(pattern,c['text']) is not None
    assert valid==c['valid'],c['id']
    if valid:assert str(int(c['text']))==c['value'],c['id']
for c in v['division']:
    n,d=int(c['n']),int(c['d']);assert d>0
    assert str(n//d)==c['floor'] and str(-((-n)//d))==c['ceil'],c['id']
for c in v['raw_integer']:
    # 固定合法JSON数字token的数学参考；不模拟完整JSON/Schema路径解析。
    value=Decimal(c['raw']);valid=value.is_finite() and value==value.to_integral_value() and abs(value)<=9007199254740991
    assert valid==c['valid'],c['id']
node=json.loads(subprocess.check_output(['node',str(ROOT/'check_integer_vectors.mjs')],text=True,encoding='utf-8'))
baseline_path=ROOT.parent/'draft4/first-loop.schema.json'
baseline=json.loads(baseline_path.read_text(encoding='utf-8'))['$defs']
for c in v['baseline_gaps']:
    model=baseline['Revision'] if c['model']=='Revision' else baseline['TimeBoundEvidence']['properties']['system_offset_ns']
    assert Draft202012Validator(model).is_valid(c['value'])==c['draft4_schema_accepts'],c['id']
decoder_design=check_decoder_design()
inputs=[ROOT/'vectors.json',ROOT/'check_integer_vectors.mjs',Path(__file__),ROOT/'README.md',ROOT.parent.parent/'rebirth-df01-sdk-freeze.md',baseline_path,
    ROOT/'check_decoder_design.py',ROOT/'decoder-design.schema.json',ROOT/'decoder-design-cases.json']
report=dict(all_passed=True,scope='固定向量参考验证；不是生成器、SDK解析器、JS JCS库或平台验收',
    python=platform.python_version(),rfc8785=version('rfc8785'),node=node,
    canonical_python_cases=len(v['canonical']),integer_cases_per_language=len(v['integers']),division_cases_per_language=len(v['division']),
    raw_integer_math_reference_cases=len(v['raw_integer']),planned_raw_rejections_not_executed=len(v['planned_raw_rejections']),
    baseline_gaps_verified=len(v['baseline_gaps']),baseline_gaps_fixed=False,
    sdk_toolchain_executed=False,canonicalize_5_1_0_executed=False,canonical_outputs=outputs,decoder_design=decoder_design,
    input_sha256={str(p.relative_to(ROOT.parent.parent)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
(ROOT/'reference-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({k:x for k,x in report.items() if k not in ('canonical_outputs','input_sha256')},ensure_ascii=False,indent=2))
