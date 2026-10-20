# DF01历史语义、投影和出口追踪

本资料落实[DF01第11节](../../rebirth-df01-sdk-freeze.md#11-语义迁移与导出边界的证据)，仅描述固定Suite提交`595a6b772fed2dce48e3a28511111b41ad3e7fc3`的实际行为和下一版推荐，不修改draft.4／IPC0.3、不实现产品SDK，也不将整个系统设计宣布完成。

## 可复验事实

[semantic-trace-map.json](semantic-trace-map.json)登记13个实际判定入口及8个不在232例执行链内的历史函数；[digest-projection-map.json](digest-projection-map.json)登记12种摘要投影及1种历史请求身份规范化投影，含字段排除/选取/排序/缺省、实现符号和相关夹具。DP13引用的旧Python向量段只比较canonical bytes，此定位不证明SHA256步骤。投影表是人工源码审阅结果，工具只核对其符号、模型和夹具定位，不执行文字算法，不把相关正例当作每个投影已有独立反例。

[audit_semantic_trace.py](audit_semantic_trace.py)先完整执行历史draft.4检查，再单独追踪232例各自的判定函数进入情况；观察按case_id记录在[semantic-trace-report.json](semantic-trace-report.json)。输入报告、历史源码与机器资料逐字节核对固定Git提交；报告绑定本脚本、两份追踪表和历史报告全部声明输入。`--check-report`只核对原字节，不重跑历史测试。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/audit_semantic_trace.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/audit_semantic_trace.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/audit_semantic_trace.py --check-report --staged
```

| 历史分组 | 实际证据 |
| --- | --- |
| 160个公共例 | 143正例、11结构反例、6语义反例；结构通过后才跑语义 |
| 24个IPC例 | 20正例、4结构反例，仅IPC Schema |
| 48个关联例 | 13正例、35反例；guard16、time12、fence6、age4、recovery3、handshake3、assessment3、OBS候选1 |
| 函数进入追踪 | 13个入口均被至少一个例进入；不证明该函数所有分支或每个规则被测试 |
| 明确未进入 | 原始wire解析、接管/命令轨迹、精确撤销、快照fresh、旧age、容量决策、失败继续、恢复单次消费 |

公共语义反例仅覆盖descriptor两项、evidence三项、profile一项。历史主循环只断言错误列表是否为空，不绑定具体原因；例如`evidence-utc-as-monotonic`同时出现三种错误，不能据此认定每项约束独立有效。导入旧模块、报告列出旧文件hash、或存在同名正例均不能补足未执行的分支。当前追踪不修改或扩大“232”的含义，旧独立验收集仍须完整保留、适配新协议并单独执行。

## 新增缺口探针

SP01—SP04的预期由源码审阅固定，独立于232例。通过表示复现了历史问题，`fixed=false`；测试只针对公共Schema与离线语义，不表示实际模块能力Schema认可这些参数，更不涉及实际设备。

| 探针 | Schema与历史结果 | 下一版推荐 |
| --- | --- | --- |
| SP01 | 通用CommandRequest.parameters含descriptor_version，Schema通过而语义抛KeyError | 不把开放参数按键名识别成运行域描述符 |
| SP02 | 参数含not_before/not_after且字面顺序反转，Schema通过而旧窗口规则拒绝 | 只对契约声明的窗口对象执行窗口规则 |
| SP03 | CatalogBinding两条entry同scene_id、不同合法UUID，Schema及当前语义都通过 | 显式接入scene_id与obs_scene_uuid分别唯一的规则；F06旧函数已有此分支但归并入口未调用 |
| SP04 | 参数含kind=state_machine但无states，Schema通过而语义抛KeyError | 不把任意业务kind当作首方状态机 |

同一根因还影响definition摘要：旧实现递归遇到step_id就删除independence_proof，可能删掉开放业务数据。等价档案必须保留旧行为以解释历史摘要；生产候选必须通过新版明确路径投影修复。不能把异常统一改为拒绝后宣称旧接受集合未变化，也不能把错误改名当成修复。

## 引用图观察与出口推荐

扫描两份OpenAPI操作的请求、响应、参数及WS两个字符串扩展根，随后沿公共Schema的`$ref`取闭包。另算`/internal/`及IPC外部根。当前固定资料没有Path Item级共享参数；未来新增该结构必须扩展观察器再归并，不能机械套用当前计数。

| 观察范围 | 根数 | 闭包 |
| --- | --- | --- |
| 普通HTTP联合 | 60 | 与WS合并后计算 |
| 非/internal HTTP＋WS联合 | 62 | 166 |
| /internal联合 | 9 | 24 |
| IPC外部公共模型引用 | 15 | 31 |

三类并集覆盖183个模型；17个仅内部／IPC可达，剩余`AuthorizationSnapshotResponse`、`RunGrant`未被这些入口引用。报告给出全部名称与每服务集合，不以计数代替逐项名单。185个components仅复现历史自包含OpenAPI，不应直接成为SDK公共导出。

推荐以版本化`exports`清单划分public、internal、ipc三个具名入口，共用模型从唯一源投影；未引用模型保留在迁移档案但不自动导出或删除。服务器构建可以按受控入口使用内部类型，浏览器构建不导出内部操作客户端；类型隐藏不代替服务端鉴权。`Payload/JsonValue`可达性不能约束运行数据内容，内部证据仍须使用显式响应投影与字段级脱敏；公开根不等于匿名可读。

## 实施前必须落实的语义注册契约

推荐每项生产规则记录：`rule_id`、`revision`、`input_model_ref`、`instance_selector`、`phase`、`context_requirements`、`reason_codes`、`implementation_bindings`、`fixture_refs`。selector由声明的模型根与Schema路径生成，明确选择哪个条件分支；不得在任意对象树中按键集合猜测模型。开放Payload与SchemaDescriptor.document止步于动态能力／Schema专用校验器，不递归套用首方对象规则。

纯结构/内容规则与需要可信上下文的关联规则分开。前者在合法输入和有限预算内返回稳定结果，后者缺少当前域、批准profile、授权或目录上下文时返回明确“无法评估”；不能用默认true或夹具标志填补权威。内部判定结果区分`valid`、`invalid`、`context_unavailable`、`validator_fault`，最后一种不能伪装成命令失败或自动重试依据。错误只携带登记的rule/reason及安全路径，不回显参数或秘密；公共API错误映射单独审阅，当前中文/英文历史标签不直接升级为公共ErrorCode。

注册表只有可追踪信息，不是从自然语言生成可执行规则。各语言实现由`implementation_bindings`固定到制品/符号，与相同独立预期逐项对照；规则中的分支、字段保留/排除、排序和默认分别需要正反例。历史异常与误判、目录唯一性补接、限定definition路径均导致显式语义修订。后续已有[局部注册格式与离线元数据检查](SEMANTIC_REGISTRY.md)，但完整规则表、完整原始入口、wire profiles、完整投影向量及TS实现尚未交付；本资料不关闭SV01/SV03/SV16或C01。
