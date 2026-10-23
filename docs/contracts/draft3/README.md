# 归并基线：公共 draft.3／IPC 0.2

当前工程审阅入口：[F01—F07整体审阅](../../rebirth-draft3-review.md)。用户已同意各轮推荐方案，本目录将已确认候选挂接到实际对象／端点／IPC；仍是预发布资料，没有运行实现。

用户已同意公共draft.3／IPC 0.2、TS01—TS05及NF01—NF03。当前审阅入口转到[draft.4／IPC 0.3](../draft4/README.md)，显式归并受监督运行域与误差证据；本目录机器文件、版本与语义保持原样，供历史复验，不代表正式冻结或运行验收通过。

- [公共 Schema](first-loop.schema.json)：`1.0.0-draft.3`，`$defs` 按模型校验。
- [Controller OpenAPI](controller.openapi.json)、[Seamer OpenAPI](seamer.openapi.json)：自包含3.1.1文档，所有端点有类型与安全方案。
- [内部 IPC](ipc.schema.json)：`ipc/0.2.0-draft.1`，19类消息，引用同目录公共Schema。
- [人工正反例](examples.json)、[验证报告](validation-report.json)：结构、跨对象、IPC配对证据及输入摘要。

生成／检查沿用[上层锁定验证依赖](../requirements-validation.lock.txt)，不安装业务依赖：

```powershell
python docs/contracts/draft3/build_contracts.py
python docs/contracts/draft3/build_examples.py
python docs/contracts/draft3/validate_contracts.py --report
```

生成器读取旧定义源与人工夹具作历史输入，旧文件不改。检查工具先验证生成漂移，再检查新结构／引用／OpenAPI及人工反例；旧顶层与F02/F03、F04/F05、F06/F07仍按原入口单独检查。新版本不是旧写请求的宽松兼容层，禁止在解析失败时回退旧语义。

Schema只负责形状与可表达条件；摘要／身份／完整coverage／证据所属／计划关联由离线判定器覆盖部分规则，完整权威校验与时序必须在实现后测试。所有示例凭据、环境及证据引用是合成占位，绝不能作为生产授权或容量批准。具体冻结余项及限制见审阅稿。
