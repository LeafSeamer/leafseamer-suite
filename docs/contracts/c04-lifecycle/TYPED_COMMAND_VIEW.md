# Controller完整公开记录持久化候选

状态：`approved=false`。本轮复用[公共命令单一类型图](COMMAND_CONTRACT.md)，将[完整受理](TYPED_CONTROLLER.md)中的简化内部投影替换为可校验的初始CommandRecord。交付[237表组合DDL](controller-command-view.sql)、[字段约束](typed-command-view.sql)、[生成器](build_typed_command_view.py)、[参考writer/reader](typed_command_view_model.py)、[检查](check_typed_command_view.py)及[报告](typed-command-view-report.json)。没有实现HTTP服务或设备发送。

## 已知事实与变更依据

此前cm_revision.state_body只有命令身份、修订及四个状态字段，cv_record.record_body只有metadata/state/snapshot摘要，缺公开State和CommandRecord的必需字段。原受理Ref指向不可变初始命令对象，不能改成当前CommandRecord摘要；当前读取必须联接cm_current，不能用历史最大修订绕过风险遮蔽。（来源：[旧受理writer](typed_controller_model.py)、[公开记录契约](../c02-command-view/README.md)、[公开存储](../c02-command-view/STORAGE.md)。）

新候选保留原237张表，以完整JSON正文、列对账和事务封存约束升级新库。旧简化受理写集在新布局中被拒绝；默认旧模型仍用于原回归，新候选通过本地initial_factory注入完整初始写集。该工厂是内部编程接口，不能由HTTP调用方指定。没有就地替换旧历史或修改旧版本接受集。

## 字段来源与持久化

| 公开字段 | 固定来源及验证 |
|---|---|
| command_id、scope、request_identity | ca_command_initial、ca_request_key及实际Controller scope，完整请求内容摘要重算 |
| initial_command_ref | 原RequestAdjudication.command_ref，绑定实际初始命令正文；不会随公开修订变化 |
| target、origin、run_binding、automation_binding | 已受理CommandContent完整原件，不改设备、来源和run代次 |
| actor | 显式可信本地提供者的完整Actor，与原RequestKey的principal/issuer/issuer_epoch精确一致 |
| accepted_at | 首次受理的应用参考时间，由可信时间提供者返回并在Schema中验证时间格式；重读不取当前系统时钟替换 |
| dispatch、control_binding | 原请求排期及expected_control，不替换为当前持有人或新排期 |
| policy | 完成/释放政策Ref、原受理Ref、max_attempts及原deadline Ref；政策摘要对提供者原件复核 |
| original_deadline_ref | 独立原截止原件的摘要引用，正文保存在cm_policy.original_deadline_body；不得仅把Dispatch摘要冒充原截止证据 |
| state及state_ref | 完整公共State与cm_revision列逐项匹配；修订为线上十进制字符串，库内排序使用20位文本 |
| completion、attempts、cancellation | 与同一State修订的原件和索引绑定；初始值分别为未达成、空集合和null |
| evidence_index | 同修订固定manifest的ID/摘要、StateRef及total；空快照也必须持久 |
| record_digest | 完整CommandRecord除自身摘要字段的JCS摘要，与State摘要及初始命令摘要分开 |

提供者输入是设计测试边界，不是用户可提交的认证声明。accepted_time_verified/deadline_verified等布尔值并未实现NTP或监督证据校验；应用参考时钟、误差区间与真实deadline计算仍按既有时间方案继续归并，不能以本轮格式检查声称时间模型已经落地。

## 原子发布与读取

受理同一事务保存完整metadata、policy、State、snapshot、CommandRecord、状态审计/outbox、容量预留、原裁决和受理提交。缺写任一必需行或任意写后异常均回滚。Schema/JCS在writer检查；SQL进一步核对原身份、actor归属、目标、完整State、policy、metadata、快照及attempt集合，禁止只有摘要外壳的投影进入新cm_commit。

getCommand/getCommandRevision参考读取只使用已提交快照；传入正在进行的writer事务立即拒绝。读取前先验证当前认证、授权修订有效性、command.read及本库scope，再核设备范围或受信Seamer的精确origin scope。历史读取不要求原动作grant重新有效，但每次仍需当前读取权限，响应阶段失权不输出正文。HTTP状态码封装和真实权限提供者尚未实现。

current仅查询cv_current；没有可发布投影时返回state_projection_pending，不降级为max(revision)。历史明确返回historical，保留当时状态，不授当前写权。内部读取核对JCS、原受理、policy来源、原deadline、完整manifest、attempt身份和prepared StateRef、completion原件及固定取消修订；GET不创建State修订、attempt或设备调用。

原件中的Actor、时间、排期、控制版本和初始Ref均不可更新。两个独立Controller的同类操作仍依各自scope读取，不能跨库借用权限。永久拒收只产生墓碑，不创建伪CommandRecord。

## 排队终态与故障验收

本轮附带未准备且无attempt的queued→blocked/expired完整修订，展示公开字段变化必须与State同事务发布。可信监督证明必须绑定原StateRef、Controller scope和原deadline Ref；过期另需原截止已达证明。新修订为finished和paused_latched，保留not_sent、clear及空完成证据，不能将其描述为succeeded。

当前辅助writer拒绝已有attempt或证据的输入；它不能替代正在执行命令的屏障、取消、资源释放或全部生命周期writer。终态不允许再次阻断、换结论或复活；历史revision1、初始受理Ref和原policy保持原样。

验收覆盖：完整受理逐写漏项/异常、旧简化正文拒绝、元数据证明/actor/时间/截止错绑、当前权限/配对/设备/来源隔离、事务内读取拒绝、grant撤回后有权历史读取、两Controller初始记录和新终态、原件不可改、墓碑无命令记录。current遮蔽检查通过测试库临时视图模拟，证明reader不回退历史；本轮没有重跑完整资源撤回/屏障链，不能据模拟声称实际设备风险处理通过。

## 剩余冻结与交付

- 完整公开初始记录及排队终态已持久，不能由此声称所有生命周期writer已类型化。实际attempt的packet/出口/会话/发送时间、完成/释放/Resolution原件、取消修订和全证据快照写入仍需逐项接入。
- reader对已有attempt检查身份、ordinal、prepared StateRef，但packet/出口及逐attempt结果的权威提供者映射尚未闭合；完整运行态读取不得提前作为可部署功能开放。
- 证据页和签名游标、取消HTTP、普通arm/recovery/manual受理、Seamer消费实际完成证据、最终AdmissionSeal和SDK全系统生成仍未完成。
- 原生制品、磁盘崩溃、跨进程并发、真实HTTP/IPC、认证/参考时钟及设备未验；完整正文带来的CostManifest和持久容量尚未证明。阶段0保持未关闭，业务代码未修改。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_typed_command_view.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_controller.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_adjudication_receive.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_command_view.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_command_view.py --check-report
```
