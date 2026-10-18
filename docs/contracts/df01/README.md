# DF01固定向量与参考检查

[冻结方案](../../rebirth-df01-sdk-freeze.md)记录D1—D6推荐、SV01—SV20验收及待落实项。这里是设计用校验资料，不是正式SDK源，未变更draft4机器协议。

[vectors.json](vectors.json)的canonical文本、整数接受结果及floor／ceil预期由人工固定；检查时不得由被测函数重写预期。[参考报告](reference-report.json)列出实际版本、canonical UTF-8 hex／SHA-256、文件hash及未执行范围。

```powershell
python docs/contracts/df01/check_reference_vectors.py
```

需要既有Python验证环境的rfc8785 0.1.4和本机Node。Python核验15个JCS固定例；Python／Node分别核验19个字符串边界与6个精确除法例；Python Decimal另核验8个原始整数token的数学预期。6个原始报文反例仅登记，严格入口解析器仍未实现。两语言算术一致不等于JS JCS库已经验证。

本机Node为24.11.1时，结果只能记录该版本；候选Node24.22.0、canonicalize5.1.0、TS／Ajv生成、浏览器CSP及真实SDK验收仍未执行。signed_ns的字符串-0与25字符规则按draft4保留；本轮没有暗改已确认接受集合。

另有两项基线差异探针：确认draft4 Schema接受Revision尾部LF及有符号ns字符串-0，结果只证明缺口／差异存在，不代表修复完成。下一版建议拒绝，正式SDK放行前须显式修订及跨语言反例验证。
