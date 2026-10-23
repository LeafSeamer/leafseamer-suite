# 公共 draft.4／IPC 0.3 归并资料

用户已同意本目录公共draft.4／IPC 0.3归并基线；仍为预发布契约，尚无业务实现。详细边界见[整体审阅](../../rebirth-draft4-review.md)，后续[DF01冻结推荐](../../rebirth-df01-sdk-freeze.md)明确SDK源迁移、生成与数字规则；本目录机器文件保持原样。

- [公共Schema](first-loop.schema.json)：`1.0.0-draft.4`。
- [Controller OpenAPI](controller.openapi.json)、[Seamer OpenAPI](seamer.openapi.json)：自包含OpenAPI 3.1.1，新增内部只读证据查询。
- [IPC](ipc.schema.json)：`ipc/0.3.0-draft.1`，19类消息；不降级旧运行域语义。
- [正反例](examples.json)、[离线报告](validation-report.json)：结构、摘要、条件时间计算与人工配对。

使用[锁定验证依赖](../requirements-validation.lock.txt)，不安装业务库：

```powershell
python docs/contracts/draft4/build_contracts.py
python docs/contracts/draft4/build_examples.py
python docs/contracts/draft4/validate_contracts.py --report
```

生成器以未改动的draft3机器契约为历史输入，生成到本目录；`--check`检查生成漂移。旧draft3的反例独立复验。本版合成profile、引用及可信上下文只能用于离线验算，不得作为生产身份、时间精度、平台支持或发布批准。

Schema和OpenAPI表达形状与部分条件，摘要引用、跨对象匹配和数学边界另由判定器检查；进程隔离、批准来源、数据库持久化、真实并发、NTP和设备效果必须在实现后取得运行证据。
