# Controller完整命令受理与查原候选

状态：`approved=false`。本候选将实际[Seamer完整写集](TYPED_SEAMER.md)产生的请求接入独立Controller内存SQLite，提供[布局生成器](build_typed_controller.py)、[237表DDL](controller-typed.sql)、[新增约束](typed-controller.sql)、[本地writer](typed_controller_model.py)、[故障检查](check_typed_controller.py)及[报告](typed-controller-report.json)。业务服务尚未实现。

## 已知事实与设计变更

旧参考受理从Seamer数据库直接读取submission，并把简化测试正文写入Controller。新writer只持有Controller连接，输入为完整RequestIdentity、CommandRequest、当前认证上下文和显式可信证据提供者。测试夹具负责从Seamer导出证据，不能据此声称真实网络证据已验证。（来源：[旧受理夹具](check_continuation_trigger.py)、[新writer](typed_controller_model.py)。）

ca_namespace已经持久issuer_epoch并包含主体和请求代次；新ca_request_key额外保存完整RequestKey及首次运输正文。列、命名空间与本库scope必须相等。content_body只保存CommandContent，request_digest仅摘要该内容。context_id、idempotency_key、correlation_id仅从顶层排除；同内容不同correlation重试返回原裁决并保留首次运输原件。

cn_command不再要求Seamer内部submission_id。该ID不是公共请求字段，不能从Controller自行补造或加入线上契约。其唯一动作身份继续采用transfer/execution/step；完整automation_binding保存到ce_command和cn_command，原grant路径改为automation_binding.continuation，转交ID和采用摘要取各自Ref。原准备归属、控制状态、撤权视图、attempt和最终发送守卫保留。

## 事务边界

新受理在BEGIN IMMEDIATE内查原、核命名空间、从本地cr_current取得转交与回执，核对完整ExecutionBinding、采用和全目标回执、固定执行计划摘要、步骤/设备/能力/参数/时间政策及expected_control。新的typed_command_source与原命令、初始状态、公开内部投影、预算预留事实、审计和通知同事务。缺任何必需写入或中途异常均回滚，提交前保留独立foreign_key_check。

请求身份的内容摘要错误在写入前拒绝；同完整键已有不同摘要时冲突，不能通过改设备或grant分裂为第二个请求。新键还须当前namespace和全部执行资格；历史查原仍要求当前认证、相应权限、精确历史owner、目标scope和读取资格，但不要求旧grant重新有效。namespace关闭及grant撤回后可查原，不能新受理；查原不建attempt或触发设备。

永久拒收沿既有协议：未裁决键写rejected墓碑及拒收操作/审计/outbox，不创建命令或设备容量预留。已有accepted键只登记拒收操作并返回原accepted裁决，不能把拒收解释为取消。拒收操作按当前actor与operation ID幂等，重绑其他键或正文冲突。关闭命名空间仍允许当前有权主体拒收；迟到提交只能返回墓碑。响应阶段失权不能撤销已提交事实，后续有权查原返回持久结果。

裁决正文通过单一公共Schema，command_ref和commit_ref分别绑定实际内部命令原件与创建提交正文摘要。initial_command_ref本就指受理时的不可变初始对象，而非后续完整记录摘要，两个引用都对实际持久正文验证。内部cm/cv初始状态仍为明确的局部投影，不能作为完整公共CommandRecord输出。（来源：[命令读取契约](../c02-command-view/README.md)、[受理存储契约](../c02-admission/STORAGE.md)。）

## 剩余冻结事项

- 本轮新受理正例为继续运行automation，manual和普通arm/recovery受理仍须类型化扩展；新seal会拒绝未升级路径，不能部署为完整Controller。
- 证据真实性、命名空间创建、AUTH/TIME及容量提供者仍由合成上下文表达。完整计划原件及R5当前性必须由可信提供者保证；保存证据正文不等于验证签名、远端提交或实时状态。
- 真实CostManifest、保留拒收空间和持续库存成本、完全公开CommandRecord/证据视图、最终AdmissionSeal与Guard/Permit/Intent落库衔接仍待完成；本轮受理成功不开放最终发送出口。
- 所选原生SQLite制品、物理磁盘崩溃、并发HTTP、跨进程IPC及设备未测试。Seamer目前接收裁决的旧简化receipt模型仍须替换为本轮完整RequestAdjudication，阶段0未关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_typed_controller.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_controller.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_controller.py --check-report
```
