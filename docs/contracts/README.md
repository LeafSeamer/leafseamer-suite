# 首闭环机器可校验契约

本目录是协议资料及离线验证工具，没有 Controller、Seamer、GUI 或设备驱动实现。用户已同意首闭环推荐方案；当前采用 `1.0.0-draft.2` 协议草案，未宣布稳定 v1 或生产可用。行为依据见 [首闭环设计](../rebirth-first-loop-contract.md)，本轮变化及 F01—F07 状态见 [边界审阅](../rebirth-contract-review.md)。

## 文件与权威来源

| 文件 | 用途 |
| --- | --- |
| [build_contracts.py](build_contracts.py) | 当前人工维护的 Schema／OpenAPI 定义源；仅生成文档 |
| [first-loop.schema.json](first-loop.schema.json) | JSON Schema 2020-12 模型库，按 `$defs/<模型名>` 校验实例；根是模型库，不能直接校验根后声称某个实例合格 |
| [controller.openapi.json](controller.openapi.json)、[seamer.openapi.json](seamer.openapi.json) | 自包含 OpenAPI 3.1.1，各自含请求、响应、错误、路径参数、鉴权声明；共同模型自动生成，禁止独立修改造成漂移 |
| [routes.json](routes.json) | HTTP 业务路径／模型对应清单；WS 升级另在两份 OpenAPI 中声明 |
| [build_examples.py](build_examples.py)、[examples.json](examples.json) | 人工编排的正反例及生成文件，不从 Schema 自动生成“必然通过”的例子 |
| [boundary-traces.json](boundary-traces.json) | 命令与接管的人工模型轨迹，覆盖允许／禁止的顺序 |
| [canonical-vectors.json](canonical-vectors.json)、[identity-vectors.json](identity-vectors.json) | JCS 固定向量及请求内容投影向量；后者单测投影，不把其精简 body 当完整请求正例 |
| [capability-cases.json](capability-cases.json)、[invalid-wire.json](invalid-wire.json) | 动态能力参数的二次校验及重复键／非法 JSON 输入反例 |
| [validate_contracts.py](validate_contracts.py)、[validate_vectors.cjs](validate_vectors.cjs) | 离线校验工具；不连接服务、数据库或设备，不提供产品运行逻辑 |
| [validation-report.json](validation-report.json) | 最近一次实际执行的静态检查结果；不是 FC01—FC24 的运行报告 |

模型所有权仍归 SDK。现阶段资料在 Suite 审阅，不创建另一套运行 SDK；转交 SDK 时固定版本和提交来源，Suite 引用发行产物，不长期双重维护。

用户已同意公共 draft.2 基线。[F02／F03 内部 IPC 资料](f02-f03/README.md)另用 `ipc/0.1.0-draft.1`，复用公共请求／许可／ACK 模型并提供独立离线检查，不修改公共 Schema／OpenAPI。其 [实际报告](f02-f03/validation-report.json)与本目录报告分别记录范围；父验证器不递归运行内部 IPC 检查。

用户已同意 F02／F03 推荐方案。[F04／F05 候选资料](f04-f05/README.md)提供身份与精确撤销、时间质量及容量模型、实验配置和边界向量，另有 [独立报告](f04-f05/validation-report.json)。新 API／执行守卫／撤销和时间屏障须在下一版规范显式合并，未改本目录公共 draft.2，也未将实验数值认定为生产参数。

## 校验层次与限制

1. **原始 JSON 层**：拒绝重复键、NaN／Infinity、孤立代理字符及不能安全表达的 JSON 整数。修订使用十进制字符串；这类输入不能仅靠解析后的 Schema 拒绝。
2. **Schema 层**：检查类型、必填／null、未知写字段、长度／数值上界、联合类型、条件必填、Q72 结构限制、命令结果组合和接管生效所需字段。启用 `FormatChecker`，不能把 format 当注释后忽略日期校验。
3. **静态语义层**：检查本 JSON 内能判断的时间顺序、版本递增、屏障／进程／设备身份一致、在途及未知清单、Schema 摘要和状态引用。`contract_valid` 只指这些离线检查，不代表服务已经授权。
4. **运行层**：权限交集、当前控制版本、批准定义、证据真实性／新鲜度、唯一发送出口、在途锁、数据库耐久、进程／网络竞态、撤销传播及生产性能，仍须实施后验证。不得用字段 `durable=true` 或 `all_write_exits_fenced=true` 替代真实证据。

动态 `parameters`／`payload`／`values` 是显式开放容器，须再用当前能力目录中固定摘要的 Schema 校验；普通写请求及内部对象均关闭额外字段。OBS 首场景参数已直接关联 `ObsSceneParameters`。内嵌 Schema 必须元校验、核验摘要并禁止未经批准的外部引用；示例验证器不联网抓取 Schema。生产解析深度、字节限额和复杂 Schema 计算预算仍在 F05 冻结。

OpenAPI 描述 HTTP 和 WS 升级入口；升级后的消息由 `WsFrame` 校验，不能把 OpenAPI 通过称为完成 WebSocket 协议运行验收。`bearerAuth` 仅说明业务入口需要身份凭据，未选定 JWT、签发算法或认证库，详见 F04。`.example.invalid` 和 `leafseamer.invalid` 均为文档标识，不是部署地址或要求访问的服务。

关闭额外字段的响应模型用于本次预发布版本的生产者基线检查，不是将来旧客户端的通用接收规则。Q61要求同主版本已协商的非语义新增读字段可兼容；客户端接收校验profile／代码生成须在F01后续验证，不能拿严格旧响应Schema否定既定兼容政策。未知状态、写字段或执行语义不在这个忽略范围内。

本轮 Schema 的 24 小时时长硬上界、对象／数组尺寸等是草案编码护栏，实验 `sim-first-loop` 使用更小限额；它们不是实测生产默认值。服务必须应用发布配置中的更严格预算。更改护栏需要契约审阅，不能静默接受无限值。

## 请求身份与规范化

顺序为：认证与授权查询范围→查原请求身份→对新受理内容做原始 JSON／Schema／能力校验→补齐已批准默认值→固定内容投影→JCS→SHA-256→保存身份及命令事务。已有同身份请求也要核对固定内容摘要，不得因查到身份而跳过不同内容冲突判断；旧能力版本所需 Schema／默认值与记录一并保留。

投影排除顶层 `context_id`、`idempotency_key`、`correlation_id`，它们分别属于幂等域或跟踪，不从嵌套业务参数删除同名字段。`acquireControl.force` 缺省补 false；其余请求必填字段不自动补猜测值。规范化保留数组顺序和 Unicode 原字符，不做 NFC 转换；整数修订不转 number。服务摘要使用 `sha256:<小写十六进制>`，幂等域仍绑定目标服务、主体、上下文世代和操作。

当前 Python 与 Node 验证固定向量的一致性；Node 脚本只是向量检查器，不能作为完整生产 JCS 实现。其他语言、边界数值全集及厂商参数默认值仍需扩展测试。

## 当前归并版本

用户已同意NF01—NF03；当前工程审阅入口为[draft.4／IPC 0.3](draft4/README.md)，归并运行域、NTP误差证据及实际对象／内部查询。本目录顶层draft.2、三个候选子目录和draft.3保留历史；旧写请求不能直接发往新版本。旧检查与新检查分开运行，均不是业务运行验收。

## 本地复现

保存报告后运行 `python docs/contracts/check_report_bindings.py`，提交前使用 `--staged`，提交后使用 `--ref HEAD`。该只读工具按生成器的明确路径基准，核对10份报告声明的原始输入SHA-256；不做换行/JCS归一化，不重新执行测试，也不证明输入列表完整或报告可信。新增报告必须更新其显式清单。合成反例通过 `python docs/contracts/test_report_bindings.py` 运行。

先将受版本控制文本按仓库`.gitattributes`保存为LF，再运行相应验证器的报告生成入口；不要直接改报告摘要。修改报告所引用的文档同样使报告过期。工作区验证通过与Git保存字节相符需要分别检查。

后续候选资料独立验证：[F02／F03 IPC](f02-f03/README.md)、[F04／F05 身份与时间容量](f04-f05/README.md)、[F06／F07 OBS／依赖／恢复](f06-f07/README.md)。本目录顶层检查不会递归运行这些检查，不能用顶层报告代替它们；公共 draft.2 文件保持原版。

依赖安装到独立虚拟环境或临时目录，不修改组件依赖。Python 3.14 与 Node.js 本轮实际用于离线校验；工具顶层版本见 [requirements-validation.txt](requirements-validation.txt)，本轮完整解析版本见 [requirements-validation.lock.txt](requirements-validation.lock.txt)。这不是产品运行时支持矩阵。

```powershell
python -m venv docs/contracts/.venv
docs/contracts/.venv/Scripts/python.exe -m pip install -r docs/contracts/requirements-validation.lock.txt
docs/contracts/.venv/Scripts/python.exe docs/contracts/build_contracts.py
docs/contracts/.venv/Scripts/python.exe docs/contracts/build_examples.py
docs/contracts/.venv/Scripts/python.exe docs/contracts/validate_contracts.py --report
```

验证脚本要求 Node 在 PATH 中；校验运行本身不需要网络。修改定义源或人工例子后先重新生成；`--check` 会拒绝与定义源不一致的生成物。校验报告仅在全部步骤通过后写出，失败应以进程非零退出码为准，不能用旧报告证明新内容通过。

格式依据为 [OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html)、[JSON Schema 2020-12](https://json-schema.org/draft/2020-12/json-schema-core.html) 和 [RFC 8785 JCS](https://www.rfc-editor.org/rfc/rfc8785)。这些规范只支持表示与校验方法；LeafSeamer 的接管、权限及直播保护语义来自项目已确认决策。
