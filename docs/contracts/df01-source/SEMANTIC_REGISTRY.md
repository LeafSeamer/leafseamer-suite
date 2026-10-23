# DF01语义注册元数据候选

本稿落实[语义追踪](SEMANTIC_TRACE.md)的下一版推荐。`semantic-registry/0.1.0-draft.1`是**设计资料格式**，不是公共API版本、生产规则全集或已批准SDK。原draft.4／IPC0.3及等价source不变。以下均为待审阅设计，事实仅限附属离线检查实际执行的范围。

## 唯一源与规则身份

[Schema](semantic-registry.schema.json)定义Registry及Result；[正反例](semantic-registry-cases.json)提供绑定当前公共Schema原字节摘要的四条示例规则。规则唯一键为`rule_id`，每个注册包只接受一个`revision`；旧版本须进入独立版本包，不能由调用方选较宽松版本。`input_model_ref`必须定位当前源的具名`$defs`根。实现、上下文、错误、位置和业务向量计划均随规则版本变更；生成器应把注册表和Schema摘要一起纳入外层生成清单。

`implementation_bindings`当前只登记计划语言、模块和符号，`status=planned`。生产切换另需真实制品摘要、符号存在性、独立正反向量及跨语言接受集对账，不以虚构制品hash填空。`fixture_refs`引用包内业务向量计划，状态固定`planned_not_executed`；这些描述不计入已运行用例。当前四条示例也不等于13个历史入口的完整规则拆分。

## 选择器与条件

`instance_selector`是有限步骤数组，不接受JSONPath、脚本、任意递归、动态对象键或调用方提供的路径。参考检查器从具名根顺序解析并生成最终Schema Pointer、实例路径模板与条件列表：

| 步骤 | 语义与拒绝条件 |
| --- | --- |
| `property(name)` | 只能进入当前Schema的已声明properties；只生成固定字段位置，不能遍历additionalProperties |
| `items` | 只能进入数组的单一items Schema；实例位置记录数组槽位，不能输入实际索引 |
| `ref` | 只跟随显式本地`#/$defs/Name`；缺失、网络ref或其他目标拒绝，不自动猜模型 |
| `branch(keyword,index)` | 支持allOf/anyOf/oneOf的显式分支；越界拒绝。anyOf/oneOf记录父组合与分支条件，不能只校验选中分支就声称整个根有效 |
| `conditional(arm)` | then/else必须和当前节点的if成对；记录if位置与真假要求，不能绕过if直接调用规则 |

所有步骤在当前固定Schema上检查；bool Schema可作为终点，但不能继续寻址。`$ref`旁的约束和父层组合约束始终仍属于完整根验证，selector没有替换Schema验证的权力。候选不支持的prefixItems、动态ref等结构令注册失败，不静默降级；后续扩展须另版向量。

运行时先完成严格wire、完整根Schema和所需能力Schema校验，再依据同一次输入的分支结果选择语义实例。anyOf可有多个成功分支；相同规则/修订/实例只执行一次，分支条件不能从另一请求缓存借用。无匹配实例或可选字段缺省表示本次不调用该规则，由编排层记录适用性，**不伪造一条valid结果**。该运行编排及生成器尚未实现；当前检查器只编译元数据，不接收业务payload。

## 开放数据的双重边界

固定保护`Payload`根及`SchemaDescriptor.document`的Schema位置，并保护`CommandRequest.parameters`和`SchemaDescriptor.document`的实例位置。后者防止从allOf/then的具名覆盖分支绕过前者。第一方规则不能选中或深入这些位置；`dynamic_payload`或`schema_document`专用规则只能止于对应边界，且必须处于linked阶段并声明可信上下文。不得先降成第一方规则再递归扫描`descriptor_version`、`kind`或`not_before`等业务键。

注册表不能任意删掉这些基线保护；新增开放位置需要同步唯一源、边界表和正反例。本检查器仅识别列明的当前根/位置；不是能自动发现全部开放模型的通用证明。生产还需对每个导出根及ref别名生成完整边界映射并检查漏项。根级规则实现仍必须接受审阅：元数据约束不证明函数体不会私自遍历开放子树，更不构成不可信模块隔离。

## 可信上下文与判定结果

`phase=content`只依赖已校验输入，不能声明上下文；`phase=linked`至少声明一个`context_requirements`，以`context_id/model_ref/provider_id/policy_ref`关联可信运行时提供者及其策略。注册包把provider固定为`trusted_runtime`；客户端只能提交协议允许的对象引用，不能自报可信、fresh或durable来满足提供者。policy_ref在本候选只是具名策略绑定，真实性、授权、当前域/修订、采样年龄、撤销与耐久必须由对应运行时验证；字符串存在不是权威证据。

每次评估绑定同一快照及输入；上下文缺失、过期、错域或撤销均不回退到默认true或旧缓存。检查上下文时不隐式发命令、重试或联网取证。发送许可仍须在唯一出口重新核对保护状态，早期语义valid不会冻结未来权限。

| Result.status | 允许字段与含义 |
| --- | --- |
| valid | 仅rule_id/revision/status；只表示该次规则评估通过，不是命令受理、派发或完成 |
| invalid | 非空violations，每项只含该规则登记的reason_code和location_id |
| context_unavailable | 非空且不重复的context_ids，必须属于该规则声明；不能替换成输入非法或设备失败 |
| validator_fault | 固定fault_code枚举internal_error/budget_exhausted/cancelled；无异常文本、堆栈或输入片段 |

`location_id`映射到静态selector；结果不含用户键名、值、动态JSON Pointer或原始错误串。每个reason在规则中登记允许的location集合，不能把合法码配到任意位置。错误顺序按注册规则顺序、reason声明顺序和location声明顺序稳定归并；数量预算在wire/执行profile中另绑，不能靠截断错误得到valid。Result只是内部候选，公共ErrorCode映射仍另行审阅。

编排建议：单个规则有已确定违规但剩余检查因异常或上下文不足未完成时，结果保持对应非完成状态；内部诊断可以保留安全违规摘要，但本候选Result不混合状态。整个评估遇validator_fault/context_unavailable不得生成发送许可；invalid同样拒绝当前请求。响应属于已提交写命令时，任何校验故障都不能改写命令终态或自动重发，按已有operation查询和恢复流程处理。

## 验证与剩余门槛

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_semantic_registry.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_semantic_registry.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_semantic_registry.py --check-report --staged
```

本轮实际检查结构、源字节绑定、具名根/selector解析、边界与上下文关联、业务向量计划引用、四类结果及reason/location配对。人工预期与检查函数分开保存，报告列出每例实际错误集合以及基例生成路径；不运行目录唯一性、时间或动态能力的业务判定，不声称SP01—SP04已修复。报告仅绑定本稿、Schema、用例、检查器和公共Schema五份输入；不替代其他历史报告。

下一步仍须完成全部原子规则、HTTP/WS/IPC调用点与阶段/顺序覆盖、各导出根开放边界映射、原始解码上下文、摘要投影独立向量及生产实现绑定。分支选择与同一实例去重、上下文撤销竞争、异常隔离及跨语言一致性要在实现期执行。冻结审阅、SDK迁移和全系统设计关闭均未由本候选完成。
