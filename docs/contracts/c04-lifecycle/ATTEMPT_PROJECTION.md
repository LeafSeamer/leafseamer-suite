# 固定attempt原件映射候选

状态：`approved=false`；内部候选`attempt-projection/0.1.0-draft.1`。本轮交付[Schema生成器](build_attempt_projection.py)、[Schema](attempt-projection.schema.json)、[独立映射器](attempt_projection_model.py)、[检查](check_attempt_projection.py)与[报告](attempt-projection-report.json)。公共HTTP和IPC版本不变，不新增设备控制入口。

## 已知事实与修正

原完整记录reader核对cm_attempt身份、序号和prepared StateRef，但将待验证的attempts同时传作期望值；因此packet/出口/时间/结果字段不能仅靠完整记录摘要得到原件保证。本轮保留原读取授权和事务边界，增加独立来源适配器及逐字段重建验证。没有来源时，非空attempt读取返回内部`attempt_originals_unavailable`；HTTP适配层仍须映射既定不可用错误，不泄漏内部提供者信息。（来源：[完整记录reader](typed_command_view_model.py)、[公共语义校验](../c02-command-view/reference_model.py)、[既有字段定义](command-contract.schema.json)。）

以下为设计方案及合成验证结果。来源资格、库存完整性、脱敏、时间投影有效性仍由可信提供者表达，测试中的布尔值是显式合成夹具，不能成为API字段或部署放行依据。新增拒绝是未闭合路径的保护，不是用删除执行态查询替代最终功能。

## 固定修订输入与字段来源

本地`attempt_source(db, command_id, revision)`在reader已有读取事务内返回固定库存、结果选择及已封存投影。三个值必须来自该State修订的独立来源，不能从record.attempts反推，也不能读取最新worker代替旧出口。完整生产存储适配器尚未实现；本轮实际数据库正例仅覆盖prepared阶段，丰富传输原件正例是人工构造的独立库存。

| 字段 | 原件及规则 |
|---|---|
| attempt_id / ordinal | 同修订cm_revision_attempt与cm_attempt，顺序从1连续，受原max_attempts限制 |
| prepared_state_ref | 原prepared完整State的ID、修订与摘要；同命令/scope、queued/pending，新增attempt为当时末项，不能引用未来State |
| packet_refs | 该固定修订已公开的完整TransportPacket；重算packet_digest，绑定command/attempt/primitive及原出口设备会话 |
| exits | 该attempt已指派的全部出口，包含编码尚未产出packet的出口；绑定不可变ce_exit身份，不能只取当前连接 |
| exit_ref | 对exit_id、device_id、controller_boot_id、worker_boot_id、ipc_session_id、device_session_id、clock_domain_id、descriptor_digest八字段规范正文作摘要；revision固定1，与运行注册证明原件引用分开 |
| protocol_request_ids | 从该attempt/出口的完整SEND_REPORT协议请求ID去重排序；不能以tracking_ids、wire_packet_id或GUI请求ID替代 |
| send_started_at | 对同出口in_flight报告按精确单调tick选择最早原件，再采用该报告的已验证TIME投影；没有最早投影时为null，不能用较晚报告或接收墙钟补值 |
| evidence_refs | 固定证据快照中明确指向该attempt的全部证据，按id及数值revision排序；不只保留最终选中的裁决 |
| outcome | 明确结果选择绑定有效原决策，或固定unknown State；不能用request accepted、传输entered或单纯packet存在推导成功 |

每份报告先核原permit、packet及摘要、ordinal、transmission_id、dispatch_intent_id，再核原worker/IPC/device会话。发送许可历史只证明来源关系，不授当前发送权。TIME输入必须绑定报告原件摘要、entered tick及原监督域；参考映射器核这些关联和时间格式，完整reference-bound时钟证明仍由TIME实现验收。

源清单保存类型与摘要引用，State及prepared State使用实际修订；证据原件摘要和EvidenceRecord投影摘要分开。Schema从现有单一命令类型图抽取原定义，不另手写一份AttemptView。`projection_digest`覆盖原件清单、选择与重建结果；公开record_digest重新计算不能绕过独立库存比较。

## 结果选择与不可恢复的误报

- pending仅用于尚未终结且没有适用决策的attempt；不得隐藏已知失败或完成原件。
- decision必须在同attempt固定证据集合内，且由该修订有效性提供者确认有效，completion_policy_ref必须等于原政策。completion达到原required_completion才可succeeded；failure为failed；cancellation为cancelled；resolution采用显式resolved_outcome，包括not_sent。
- unknown必须绑定原unknown State及其最后attempt，不能给其他旧attempt套用当前命令结论。固定unknown后迟到成功只增加证据；不得悄悄改写原attempt为成功。显式Resolution由既有独立字段展示。
- 状态机是否可以提交全命令终态、资源是否释放、是否准许重试，继续由生命周期/保护契约裁决。此映射器不能决定设备动作成败或签发许可。

## 故障时序与验收边界

读取事务先核当前授权及指定State，再从同一固定切点加载原件并重建attempts，随后核完整CommandRecord，提交只读事务，最后核响应权限。证据页使用同一验证入口；没有来源的非空attempt不能通过分页绕开检查。单条证据查询按自身来源约束读取，不因此扩大命令读权。

1. 旧修订发布后出现新packet/report：新事实只能进入新库存和新公开修订，旧投影不补写，不能在读取时临时查询最新全量代替固定清单。
2. 原报告来自旧IPC会话或引用另一packet：即使报告、投影和CommandRecord摘要重新计算，独立关系校验仍拒绝。
3. 最早进入发送的报告TIME投影缺失：返回null发送时间，不选择较晚报告冒充最早；动作结果不因此升级或降级。
4. 完成原件失效：不把它继续列作当前有效结果依据；历史快照仍须按当时固定有效性记录解释，撤回通过新修订和保护传播。
5. 原件适配器不可用：当前和指定执行态历史读取拒绝；无attempt的受理历史仍可读。适配器返回另一修订时拒绝，不能自动改查最新。

67项检查通过，覆盖独立双出口库存、超过2^53的发送tick、最早时间缺失、编码未知保留指派出口、所有公开attempt字段的重新摘要篡改、原件错绑/重复/跨设备与TIME撤回、六种结果以及unknown后迟到成功。明确撤回不能由有效列表覆盖，撤回证据沿subject进入attempt清单。实际237表内另行执行prepared修订发布、读取及证据页接线，并核旧历史保持空attempt与外键完整。传输与结果正例尚未通过最终发送链生成，不能当作真实设备或完整T2验收。

完整库存及有效性清单的物理封存/完整差集、全部生命周期writer、AUTH/TIME原件提供者、结果撤回传播、成本/GC、HTTP错误适配及SDK最终归并仍待完成。本轮不新增SQL表，不关闭阶段0，不声称服务、进程恢复、磁盘或设备运行成功。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_attempt_projection.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_attempt_projection.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_attempt_projection.py --check-report
```
